"""第 02 章 · 分层 Prompt 装配 + 上下文预算 + badcase 归因

运行：python ch02_prompt_harness/main.py
导出模板资产：python ch02_prompt_harness/main.py --dump
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from mock_llm import estimate_tokens  # noqa: E402

LAYERS = ["L0", "L1", "L2", "L3", "L4"]
BAD_LABELS = ["知识缺失", "指令冲突", "格式错误", "幻觉", "拒答失败"]


@dataclass
class PromptBuilder:
    """五层 Prompt 资产，可版本化、可回滚、可跨业务复用 L0/L3。"""

    version: str = "v1.0"
    layers: dict[str, str] = field(default_factory=dict)
    _history: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def add(self, layer: str, text: str) -> "PromptBuilder":
        if layer not in LAYERS:
            raise ValueError(f"未知层：{layer}")
        self.layers[layer] = text.strip()
        return self

    def render(self) -> str:
        missing = [l for l in LAYERS if not self.layers.get(l)]
        if missing:
            raise ValueError(f"Prompt 层缺失：{missing}")
        return "\n".join(f"<{l}>\n{self.layers[l]}\n</{l}>" for l in LAYERS)

    def bump(self, new_version: str) -> "PromptBuilder":
        self._history.append((self.version, dict(self.layers)))
        self.version = new_version
        return self

    def rollback(self) -> "PromptBuilder":
        if not self._history:
            raise RuntimeError("无可回滚版本")
        self.version, self.layers = self._history.pop()
        return self


@dataclass
class ContextBudget:
    """上下文预算表：按比例分配，超限时按优先级裁剪。"""

    total: int = 1200
    ratios: dict[str, float] = field(
        default_factory=lambda: {
            "system": 0.15,
            "fewshot": 0.15,
            "retrieval": 0.45,
            "history": 0.15,
            "reserved_output": 0.10,
        }
    )

    def cap(self, block: str) -> int:
        return int(self.total * self.ratios[block])

    def fit(self, sections: dict[str, str]) -> tuple[dict[str, str], dict[str, int]]:
        """返回裁剪后的 sections 与每块 token 用量。

        裁剪顺序：retrieval（按段落边界截断，保留首段与末段）→ fewshot → history。
        system 永不裁剪。
        """
        used: dict[str, int] = {}
        out = dict(sections)
        for block in ["retrieval", "fewshot", "history"]:
            text = out.get(block, "")
            cap = self.cap(block)
            t = estimate_tokens(text)
            if t > cap:
                paras = [p for p in text.split("\n\n") if p.strip()]
                if len(paras) <= 1:
                    out[block] = text[: max(1, int(len(text) * cap / t))]
                else:
                    keep: list[str] = []
                    for p in paras:  # 按顺序贪心装入，装不下就跳过（保证不越预算）
                        cand = keep + [p]
                        if estimate_tokens("\n\n".join(cand)) <= cap:
                            keep.append(p)
                    if not keep:  # 单段即超预算 → 硬截断
                        p0 = paras[0]
                        keep = [p0[: max(1, int(len(p0) * cap / max(estimate_tokens(p0), 1)))]]
                    out[block] = "\n\n".join(keep)
            used[block] = estimate_tokens(out[block])
        used["system"] = estimate_tokens(out.get("system", ""))
        used["reserved_output"] = self.cap("reserved_output")
        return out, used

    def is_within(self, sections: dict[str, str]) -> bool:
        body = sum(estimate_tokens(v) for k, v in sections.items() if k != "reserved_output")
        return body + self.cap("reserved_output") <= self.total


def total_tokens(sections: dict[str, str]) -> int:
    return sum(estimate_tokens(v) for v in sections.values())


def load_badcases(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def badcase_stats(cases: list[dict]) -> dict:
    labels = {}
    for c in cases:
        labels[c.get("label", "UNLABELED")] = labels.get(c.get("label", "UNLABELED"), 0) + 1
    complete = all(
        c.get("input") and c.get("expected") and c.get("actual") and c.get("label") and c.get("fix")
        for c in cases
    )
    return {"count": len(cases), "labels": labels, "fields_complete": complete}


BASE = {
    "L0": """你是医疗知识库助手。
能做：基于给定资料解释术语、比对参考区间、整理要点。
绝不做：给出诊断结论、推荐具体剂量、替代医生决策。""",
    "L1": """任务：回答用户问题，输出结论 + 依据 + 引用。
成功标准：结论可被引用段落直接支撑；无支撑时必须拒答。""",
    "L2": """上下文数据：以下为检索到的资料片段，仅可引用其中内容。
每段以 [doc#p] 标注来源；资料未覆盖的问题一律回答"资料不足"。""",
    "L3": """输出格式：先"结论"（≤3句），再"依据"（要点列表，每条带 [doc#p]），最后"免责"一行。
长度：≤300 字。禁止出现的内容：具体用药剂量、预后判断。""",
    "L4": """正例：问"谷丙转氨酶偏高意味着什么" → 结论：可能提示肝细胞受损，需结合其他指标；依据：引用 doc#3 段落。
反例（错误示范）：直接回答"你得了肝炎" → 越界诊断，应改为提示就医并给依据。""",
}


def build_default() -> PromptBuilder:
    b = PromptBuilder(version="v1.0")
    for layer, text in BASE.items():
        b.add(layer, text)
    return b


def dump_prompts(builder: PromptBuilder, outdir: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    for layer in LAYERS:
        p = os.path.join(outdir, f"{layer}_{builder.version}.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write(builder.layers[layer] + "\n")
    with open(os.path.join(outdir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"version": builder.version, "layers": LAYERS}, f, ensure_ascii=False, indent=2)
    print(f"已导出 {len(LAYERS)} 层到 {outdir}")


def demo() -> None:
    b = build_default()
    budget = ContextBudget(total=1200)

    sections = {
        "system": b.render(),
        "fewshot": BASE["L4"],
        "retrieval": "段落A：ALT 参考区间 7-40 U/L。\n\n段落B：ALT 升高常见于肝细胞损伤。\n\n" + "段落C：无关内容。" * 60,
        "history": "用户：帮我看看化验单。\n助手：请提供指标。",
    }

    fitted, used = budget.fit(sections)
    print("预算上限：", budget.total, "tokens")
    for k, v in used.items():
        print(f"  {k:16s} {v:5d} / {budget.cap(k) if k != 'system' else '-'}")
    print("裁剪后是否在预算内：", budget.is_within(fitted))
    print("retrieval 保留段数：", len([p for p in fitted['retrieval'].split('\n\n') if p.strip()]))

    stats = badcase_stats(load_badcases(os.path.join(os.path.dirname(__file__), "badcases.jsonl")))
    print("badcase 统计：", json.dumps(stats, ensure_ascii=False))
    print("提示：改一版 Prompt 后用 badcase 集跑回归，记录通过率变化。")

    dump_prompts(b, os.path.join(os.path.dirname(__file__), "prompts"))


if __name__ == "__main__":
    if "--dump" in sys.argv:
        dump_prompts(build_default(), os.path.join(os.path.dirname(__file__), "prompts"))
    else:
        demo()
