"""第 04 章 · 手写 ReAct Agent（四道约束闸：步数 / 超时 / 预算 / 权限）

运行：python ch04_agent_tools/agent.py
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable

from tools import AgentError, ToolRegistry, build_registry


@dataclass
class AgentResult:
    answer: str
    steps: int
    degraded: bool
    reason: str
    history: list[dict] = field(default_factory=list)
    audit: list[dict] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "answer": self.answer[:80],
            "steps": self.steps,
            "degraded": self.degraded,
            "reason": self.reason,
            "tool_calls": [a for a in self.audit if a["status"] == "ok"],
        }


class ReactAgent:
    """最小可交付 Agent：LLM 决策由 policy 替代（确定性、可复现）。"""

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        max_steps: int = 6,
        max_tool_calls: int = 5,
        max_cost_tokens: int = 2000,
    ):
        self.registry = registry or build_registry()
        self.max_steps = max_steps
        self.max_tool_calls = max_tool_calls
        self.max_cost_tokens = max_cost_tokens
        self.history: list[dict] = []

    def run(self, policy: Callable[[list[dict], list[dict]], dict], task: str) -> AgentResult:
        self.history = [{"role": "task", "content": task}]
        used_calls = 0
        used_tokens = 0

        for step in range(1, self.max_steps + 1):
            if used_calls >= self.max_tool_calls or used_tokens >= self.max_cost_tokens:
                return self._degrade(step, "BUDGET_EXHAUSTED", "预算耗尽，转人工复核")

            decision = policy(self.history, self.registry.catalog())

            if decision.get("action") == "final":
                return AgentResult(
                    answer=decision.get("answer", ""),
                    steps=step,
                    degraded=False,
                    reason="OK",
                    history=self.history,
                    audit=self.registry.audit,
                )

            tool = decision.get("tool", "")
            args = decision.get("args", {})
            confirmed = bool(decision.get("confirm", False))
            try:
                obs = self.registry.call(tool, args, confirmed=confirmed, step=step)
                used_calls += 1
                used_tokens += len(str(args)) + len(obs)
                self.history.append({"role": "observation", "tool": tool, "args": args, "content": obs})
            except AgentError as e:
                self.history.append(
                    {"role": "blocked", "tool": tool, "code": e.code, "content": e.message}
                )
                if e.code in ("BAD_ARGS", "BAD_INPUT"):
                    used_calls += 1

        return self._degrade(self.max_steps, "MAX_STEPS", "超过最大步数，转人工接手")

    def _degrade(self, step: int, code: str, msg: str) -> AgentResult:
        return AgentResult(
            answer=f"[降级] {msg}（原因：{code}）。已完成步骤：{len(self.registry.audit)}",
            steps=step,
            degraded=True,
            reason=code,
            history=self.history,
            audit=self.registry.audit,
        )


# ---------------- 确定性策略（模拟 LLM 的决策） ----------------
def make_lab_policy(patient_id: str) -> Callable[[list[dict], list[dict]], dict]:
    def policy(history: list[dict], catalog: list[dict]) -> dict:
        names = {c["name"] for c in catalog}
        obs_tools = [h.get("tool") for h in history if h["role"] == "observation"]

        if "search_patient_labs" not in obs_tools and "search_patient_labs" in names:
            return {"tool": "search_patient_labs", "args": {"patient_id": patient_id}}
        if "search_kb" not in obs_tools and "search_kb" in names:
            return {"tool": "search_kb", "args": {"query": "ALT 升高 含义"}}
        if "submit_ticket" not in obs_tools and "submit_ticket" in names:
            return {
                "tool": "submit_ticket",
                "args": {"title": "肝功能异常复核", "detail": "ALT 68 U/L，AST 42 U/L"},
                "confirm": True,   # 写操作必须显式确认
            }
        labs = next((h["content"] for h in history if h.get("tool") == "search_patient_labs"), "")
        kb = next((h["content"] for h in history if h.get("tool") == "search_kb"), "")
        return {
            "action": "final",
            "answer": (
                "结论：ALT 68 U/L（参考 7-40）升高约 1.7 倍，AST 略高，肌酐与血钾正常。"
                "依据：单次轻度升高不等于肝炎，需结合胆红素与临床表现。\n"
                f"数据：{labs[:120]}\n知识库：{kb[:120]}\n已提交人工复核工单。"
            ),
        }

    return policy


def policy_always_tool(tool: str, args: dict, confirm: bool = True) -> Callable[[list[dict], list[dict]], dict]:
    def policy(history: list[dict], catalog: list[dict]) -> dict:
        return {"tool": tool, "args": args, "confirm": confirm}

    return policy


def main() -> None:
    agent = ReactAgent()
    res = agent.run(make_lab_policy("P-1024"), "解读患者 P-1024 的肝功能化验并决定是否需要复核")
    print("=== 正常任务 ===")
    print(json.dumps(res.summary(), ensure_ascii=False, indent=2))
    print("\n审计日志：")
    for a in res.audit:
        print("  ", a)

    print("\n=== 写操作未确认（应被拦） ===")
    agent2 = ReactAgent()
    res2 = agent2.run(policy_always_tool("submit_ticket", {"title": "x", "detail": "y"}, confirm=False), "提交工单")
    print(json.dumps(res2.summary(), ensure_ascii=False, indent=2))

    print("\n=== 死循环（应触发步数降级） ===")
    agent3 = ReactAgent(max_steps=3)
    res3 = agent3.run(policy_always_tool("search_kb", {"query": "ALT"}), "无限查询")
    print(json.dumps(res3.summary(), ensure_ascii=False, indent=2))

    with open(os.path.join(os.path.dirname(__file__), "mcp_manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    print(f"\nMCP manifest 能力：{ {k: len(v) for k, v in manifest.items() if isinstance(v, list)} }")


if __name__ == "__main__":
    main()
