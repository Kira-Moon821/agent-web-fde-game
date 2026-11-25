"""第 04 章 L2 代码闸门：9 条断言。运行：python ch04_agent_tools/check.py"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)

from agent import ReactAgent, make_lab_policy, policy_always_tool  # noqa: E402
from tools import AgentError, build_registry  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name, fn):
    try:
        ok, msg = fn()
    except Exception as e:  # noqa: BLE001
        ok, msg = False, f"{type(e).__name__}: {e}"
    RESULTS.append((name, ok, msg))


def d1_unknown_tool():
    r = build_registry()
    try:
        r.call("no_such_tool", {})
        return False, "未拦截未知工具"
    except AgentError as e:
        return e.code == "TOOL_NOT_FOUND", f"code={e.code}"


def d2_bad_args():
    r = build_registry()
    try:
        r.call("calc_bmi", {"height_cm": 170})
        return False, "未拦截缺参"
    except AgentError as e:
        return e.code == "BAD_ARGS", f"code={e.code}"


def d3_max_steps():
    agent = ReactAgent(max_steps=2, max_tool_calls=10)
    res = agent.run(policy_always_tool("search_kb", {"query": "ALT"}), "无限查询")
    return res.degraded and res.reason == "MAX_STEPS", f"degraded={res.degraded} reason={res.reason}"


def d4_tool_timeout():
    r = build_registry()
    try:
        r.call("slow_lookup", {"delay": 2})
        return False, "慢工具未超时"
    except AgentError as e:
        return e.code == "TOOL_TIMEOUT", f"code={e.code}"


def d5_budget_exhausted():
    agent = ReactAgent(max_steps=5, max_tool_calls=1)
    res = agent.run(policy_always_tool("search_kb", {"query": "ALT"}), "预算测试")
    return res.degraded and res.reason == "BUDGET_EXHAUSTED", f"reason={res.reason}"


def d6_write_needs_confirm():
    r = build_registry()
    try:
        r.call("submit_ticket", {"title": "t", "detail": "d"})
        return False, "写操作未拦截"
    except AgentError as e:
        return e.code == "NEED_CONFIRM", f"code={e.code}"


def d7_audit_fields():
    agent = ReactAgent()
    res = agent.run(make_lab_policy("P-1"), "解读化验")
    ok = bool(res.audit) and all(
        {"step", "tool", "elapsed_ms", "status"} <= set(a) and isinstance(a["elapsed_ms"], int)
        for a in res.audit
    )
    return ok, f"audit={len(res.audit)} entries"


def d8_truncation():
    r = build_registry()
    obs = r.call("search_patient_labs", {"patient_id": "P-1"})
    return obs.endswith("…[已截断]") and len(obs) <= 246, f"len={len(obs)} tail={obs[-8:]}"


def d9_mcp_manifest():
    with open(os.path.join(HERE, "mcp_manifest.json"), encoding="utf-8") as f:
        m = json.load(f)
    counts = {"tools": len(m.get("tools", [])), "resources": len(m.get("resources", [])), "prompts": len(m.get("prompts", []))}
    ok = all(v > 0 for v in counts.values())
    return ok, f"counts={counts}"


def d10_normal_task():
    agent = ReactAgent()
    res = agent.run(make_lab_policy("P-1024"), "解读化验并决定是否复核")
    ok = (not res.degraded) and res.steps >= 3 and "结论" in res.answer
    return ok, f"steps={res.steps} degraded={res.degraded}"


def main() -> int:
    for name, fn in [
        ("D1 未知工具拦截", d1_unknown_tool),
        ("D2 缺参拦截", d2_bad_args),
        ("D3 最大步数降级", d3_max_steps),
        ("D4 单步超时", d4_tool_timeout),
        ("D5 预算耗尽停止", d5_budget_exhausted),
        ("D6 写操作需确认", d6_write_needs_confirm),
        ("D7 审计字段完整", d7_audit_fields),
        ("D8 长返回截断", d8_truncation),
        ("D9 MCP 三类能力", d9_mcp_manifest),
    ]:
        check(name, fn)

    passed = 0
    for name, ok, msg in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  |  {msg}")
        passed += ok
    print(f"[CH04] {'PASS' if passed == len(RESULTS) else 'FAIL'} {passed}/{len(RESULTS)}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
