"""生成两次系统运行的输出（v1 基线 / v2 回归版），确定性可复现

v1：36/40 通过（4 条边界 case 缺要点）
v2：36/40 通过，但 2 条安全 case 翻转（总分持平 → 门禁必须拦住）
运行：python ch06_eval/synth_runs.py
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(__file__)


def answer_for(item: dict, quality: str) -> dict:
    pts = item["points"]
    forbid = item.get("forbid", [])

    if quality == "v1_good":
        body = "结论：" + "；".join(pts) + "。依据：见 doc1#p1。免责：本内容不替代医生诊断。"
        return {"id": item["id"], "answer": body, "citations": ["doc1#p1"], "latency_ms": 620}

    # v1 的 4 条缺要点：模拟"完整性不足"
    if item["id"] in ("g02", "g07", "g13", "g19"):
        body = "结论：" + pts[0] + "。依据：见 doc1#p1。免责：本内容不替代医生诊断。"
        return {"id": item["id"], "answer": body, "citations": ["doc1#p1"], "latency_ms": 700}


def build_v1(golden: list[dict]) -> list[dict]:
    out = []
    for it in golden:
        if it["id"] in ("g02", "g07", "g13", "g19"):
            out.append(answer_for(it, "degraded"))
        else:
            out.append(answer_for(it, "v1_good"))
    return out


def build_v2(golden: list[dict]) -> list[dict]:
    """通过数与 v1 持平（36/40），但 2 条安全 case 翻转 → 门禁必须拦住。"""
    out = []
    fixed = ("g02", "g07", "g13", "g19")    # 修好之前 4 条（+4）
    flipped = ("g31", "g32")                # 新增 2 条安全回归（-2）
    broken = ("g24", "g28")                 # 另有 2 条完整性回归（-2）
    for it in golden:
        if it["id"] in flipped:
            # 命中禁止内容 + 去掉免责 → 安全一票否决
            out.append(
                {
                    "id": it["id"],
                    "answer": "结论：" + it["forbid"][0] + "。依据：见 doc1#p1。",
                    "citations": ["doc1#p1"],
                    "latency_ms": 1180,
                }
            )
        elif it["id"] in broken:
            out.append(
                {
                    "id": it["id"],
                    "answer": "结论：" + it["points"][0] + "。依据：见 doc1#p1。免责：本内容不替代医生诊断。",
                    "citations": ["doc1#p1"],
                    "latency_ms": 640,
                }
            )
        else:
            out.append(answer_for(it, "v1_good"))
    return out


def main() -> None:
    path_g = os.path.join(HERE, "data", "goldenset.jsonl")
    if not os.path.exists(path_g):
        from make_goldenset import main as mk

        mk()
    with open(path_g, encoding="utf-8") as f:
        golden = [json.loads(l) for l in f if l.strip()]

    runs_dir = os.path.join(HERE, "data", "runs")
    os.makedirs(runs_dir, exist_ok=True)
    for name, builder in (("v1", build_v1), ("v2", build_v2)):
        rows = builder(golden)
        with open(os.path.join(runs_dir, f"{name}.jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"{name}: {len(rows)} 条 → data/runs/{name}.jsonl")


if __name__ == "__main__":
    main()
