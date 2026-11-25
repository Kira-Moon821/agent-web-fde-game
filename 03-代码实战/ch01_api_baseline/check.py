"""第 01 章 L2 代码闸门：6 条断言。运行：python ch01_api_baseline/check.py"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))

from llm_client import LLMClient, build_prompt  # noqa: E402
from mock_llm import LLMError, MockLLM, cost_of, estimate_tokens  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, fn) -> None:
    try:
        ok, msg = fn()
    except Exception as e:  # noqa: BLE001
        ok, msg = False, f"{type(e).__name__}: {e}"
    RESULTS.append((name, ok, msg))


def noop_sleep(_s: float) -> None:
    return None


def a1_retry_429() -> tuple[bool, str]:
    mock = MockLLM()
    mock.register_fault("__FAIL_429__", 1)
    c = LLMClient(mock=mock, sleeper=noop_sleep)
    c.complete("测试限流 __FAIL_429__", max_tokens=80)
    attempts = len(c.events)
    ok = attempts == 2 and c.events[0]["status"] == "error" and c.events[1]["status"] == "ok"
    return ok, f"attempts={attempts} events={c.events}"


def a2_timeout() -> tuple[bool, str]:
    mock = MockLLM(slow_seconds=0.6)
    c = LLMClient(mock=mock, timeout_s=0.2, sleeper=noop_sleep)
    try:
        c.complete("慢调用 __SLOW__", max_tokens=80)
        return False, "未抛出超时"
    except LLMError as e:
        return e.code == "MODEL_TIMEOUT", f"code={e.code}"


def a3_bad_json_repair() -> tuple[bool, str]:
    mock = MockLLM()
    mock.register_fault("__BADJSON__", 1)
    c = LLMClient(mock=mock, sleeper=noop_sleep)
    res = c.complete_json("输出 JSON __BADJSON__", required_keys=["answer"])
    return res.repaired and "answer" in res.data, f"repaired={res.repaired} data={res.data}"


def a4_cost_math() -> tuple[bool, str]:
    mock = MockLLM()
    c = LLMClient(mock=mock, sleeper=noop_sleep)
    text_in = "成本核算测试：" + "布洛芬" * 20
    c.complete(text_in, max_tokens=100)
    manual = cost_of(c.ledger.prompt_tokens, c.ledger.completion_tokens)
    ok = abs(manual - c.ledger.cost) < 1e-6
    return ok, f"ledger={c.ledger.cost} manual={manual}"


def a5_trim_context() -> tuple[bool, str]:
    system = "你是助手。" * 50           # 人为把 system 撑长
    msgs = [{"role": "user", "content": f"第{i}轮问题：" + "内容" * 30} for i in range(8)]
    s2, m2 = LLMClient.trim_context(system, msgs, max_prompt_tokens=400, keep_recent=3)
    ok = (
        s2 == system
        and len(m2) <= 4
        and any("历史摘要" in m["content"] for m in m2)
        and m2[-1]["content"].startswith("第7轮")
    )
    return ok, f"len={len(m2)} head={m2[0]['content'][:12]} tail={m2[-1]['content'][:8]}"


def a6_temp_zero_stable() -> tuple[bool, str]:
    mock = MockLLM()
    c = LLMClient(mock=mock, sleeper=noop_sleep)
    p = "同样输入应当同样输出。"
    r1 = c.complete(p, temperature=0.0).text
    r2 = c.complete(p, temperature=0.0).text
    return r1 == r2, f"same={r1 == r2} len={len(r1)}"


def main() -> int:
    for name, fn in [
        ("A1 429 重试", a1_retry_429),
        ("A2 超时抛出", a2_timeout),
        ("A3 非法JSON修复", a3_bad_json_repair),
        ("A4 成本核算", a4_cost_math),
        ("A5 上下文裁剪", a5_trim_context),
        ("A6 温度0稳定", a6_temp_zero_stable),
    ]:
        check(name, fn)

    passed = 0
    for name, ok, msg in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  |  {msg}")
        passed += ok
    print(f"[CH01] {'PASS' if passed == len(RESULTS) else 'FAIL'} {passed}/{len(RESULTS)}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
