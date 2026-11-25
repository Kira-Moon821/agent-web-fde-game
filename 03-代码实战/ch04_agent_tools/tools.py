"""第 04 章 · 工具注册表：schema / 权限级 / 超时 / 返回截断 / 审计

设计三原则：
1. 一个工具只做一件事，名字即语义
2. schema 里写清"何时不要用"
3. 返回必须截断 + 摘要，避免上下文爆掉
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any, Callable


class AgentError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    permission: str            # "read" | "write"
    func: Callable[..., Any]
    timeout_s: float = 3.0
    max_observation_chars: int = 240

    def preview(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "schema": self.schema,
            "permission": self.permission,
            "timeout_s": self.timeout_s,
        }


WRITE_PERMISSION = "write"
READ_PERMISSION = "read"


class ToolRegistry:
    def __init__(self):
        self.tools: dict[str, Tool] = {}
        self.audit: list[dict] = []

    def register(self, tool: Tool) -> None:
        if tool.name in self.tools:
            raise AgentError("DUPLICATE_TOOL", tool.name)
        self.tools[tool.name] = tool

    def catalog(self) -> list[dict]:
        return [t.preview() for t in self.tools.values()]

    def call(self, name: str, args: dict, confirmed: bool = False, step: int = 0) -> str:
        t0 = time.time()
        if name not in self.tools:
            raise AgentError("TOOL_NOT_FOUND", f"未注册工具：{name}")
        tool = self.tools[name]

        # schema 必填校验（模型给错参数是常态）
        required = tool.schema.get("required", [])
        missing = [k for k in required if k not in args]
        if missing:
            raise AgentError("BAD_ARGS", f"{name} 缺少参数：{missing}")

        # 写操作必须人在回路确认
        if tool.permission == WRITE_PERMISSION and not confirmed:
            raise AgentError("NEED_CONFIRM", f"{name} 是写操作，需要人工确认")

        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(tool.func, **args)
            try:
                raw = fut.result(timeout=tool.timeout_s)
            except FutureTimeout:
                self._log(step, name, t0, "timeout", 0)
                raise AgentError("TOOL_TIMEOUT", f"{name} 超过 {tool.timeout_s}s")
            except AgentError:
                self._log(step, name, t0, "error", 0)
                raise
            except Exception as e:  # noqa: BLE001
                self._log(step, name, t0, "error", 0)
                raise AgentError("TOOL_FAILED", f"{name}: {e}")

        raw = str(raw)
        truncated = len(raw) > tool.max_observation_chars
        obs = raw[: tool.max_observation_chars] + ("…[已截断]" if truncated else "")
        self._log(step, name, t0, "ok", len(raw), truncated)
        return obs

    def _log(self, step: int, tool: str, t0: float, status: str, raw_len: int, truncated: bool = False) -> None:
        self.audit.append(
            {
                "step": step,
                "tool": tool,
                "elapsed_ms": int((time.time() - t0) * 1000),
                "status": status,
                "raw_len": raw_len,
                "truncated": truncated,
            }
        )


# ---------------- 模拟工具实现 ----------------
def _search_patient_labs(patient_id: str) -> str:
    return (
        f"患者 {patient_id} 最近化验：ALT 68 U/L（参考 7-40，↑1.7x）；"
        "AST 42 U/L（参考 13-35，↑1.2x）；肌酐 78 μmol/L（参考 57-97，正常）；"
        "血钾 4.2 mmol/L（参考 3.5-5.5，正常）。"
        + "\n附加说明：本次为门诊复查，采样时间 08:15，空腹 10 小时。" * 6
    )


def _get_drug_info(name: str) -> str:
    db = {
        "布洛芬": "非甾体抗炎药；常见不良反应：胃肠道不适、头晕、皮疹；妊娠晚期禁用；不提供剂量建议。",
        "对乙酰氨基酚": "过量可致肝损伤；成人单日总量一般不超过 2 克；服药期间避免饮酒。",
    }
    return db.get(name, f"未收录药物：{name}")


def _search_kb(query: str) -> str:
    if "ALT" in query or "转氨酶" in query:
        return "doc1#p1：ALT 主要存在于肝细胞中，参考区间 7-40 U/L；单次轻度升高不等于肝炎，需结合其他指标。"
    return "未命中：知识库无相关片段。"


def _calc_bmi(height_cm: float, weight_kg: float) -> str:
    if height_cm <= 0:
        raise AgentError("BAD_INPUT", "身高必须大于 0")
    return f"BMI = {round(weight_kg / (height_cm / 100) ** 2, 1)}"


def _submit_ticket(title: str, detail: str) -> str:
    return f"工单已创建：{title} | {detail[:60]}"


def _slow_tool(delay: float = 2.0) -> str:
    time.sleep(delay)
    return "slow done"


def build_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(
        Tool(
            name="search_patient_labs",
            description="按患者ID查询最近一次化验结果。只读。不要用来查药品说明。",
            schema={"type": "object", "required": ["patient_id"], "properties": {"patient_id": {"type": "string"}}},
            permission=READ_PERMISSION,
            func=_search_patient_labs,
        )
    )
    r.register(
        Tool(
            name="get_drug_info",
            description="查询药品说明书摘要。只读。不含剂量建议，不要用它回答剂量问题。",
            schema={"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}},
            permission=READ_PERMISSION,
            func=_get_drug_info,
        )
    )
    r.register(
        Tool(
            name="search_kb",
            description="检索医学知识库，返回带来源ID的片段。只读。",
            schema={"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}},
            permission=READ_PERMISSION,
            func=_search_kb,
        )
    )
    r.register(
        Tool(
            name="calc_bmi",
            description="计算 BMI。只读，纯计算，无副作用。",
            schema={
                "type": "object",
                "required": ["height_cm", "weight_kg"],
                "properties": {"height_cm": {"type": "number"}, "weight_kg": {"type": "number"}},
            },
            permission=READ_PERMISSION,
            func=_calc_bmi,
        )
    )
    r.register(
        Tool(
            name="submit_ticket",
            description="提交人工复核工单。写操作，会通知医生，必须人工确认后才能调用。",
            schema={
                "type": "object",
                "required": ["title", "detail"],
                "properties": {"title": {"type": "string"}, "detail": {"type": "string"}},
            },
            permission=WRITE_PERMISSION,
            func=_submit_ticket,
        )
    )
    r.register(
        Tool(
            name="slow_lookup",
            description="用于演示超时兜底的慢工具。只读。",
            schema={"type": "object", "required": ["delay"], "properties": {"delay": {"type": "number"}}},
            permission=READ_PERMISSION,
            func=_slow_tool,
            timeout_s=0.3,
        )
    )
    return r
