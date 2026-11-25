"""第 02 章 L2 代码闸门：7 条断言。运行：python ch02_prompt_harness/check.py"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "common"))

from llm_client import LLMClient  # noqa: E402
from mock_llm import LLMError, MockLLM, estimate_tokens  # noqa: E402

sys.path.insert(0, HERE)
from main import BAD_LABELS, LAYERS, ContextBudget, PromptBuilder, badcase_stats, build_default, load_badcases  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name, fn):
    try:
        ok, msg = fn()
    except Exception as e:  # noqa: BLE001
        ok, msg = False, f"{type(e).__name__}: {e}"
    RESULTS.append((name, ok, msg))


def b1_five_layers():
    b = build_default()
    rendered = b.render()
    ok = all(f"<{l}>" in rendered and f"</{l}>" in rendered for l in LAYERS)
    return ok, f"missing={[l for l in LAYERS if b.layers.get(l) is None]} tokens={estimate_tokens(rendered)}"


def _big_sections(retrieval_tokens=1500):
    return {
        "system": build_default().render(),
        "fewshot": "正例：A。\n\n反例：B。",
        "retrieval": "\n\n".join(f"段落{i}：" + "医疗资料内容" * 40 for i in range(12)),
        "history": "用户：问题1\n助手：回答1",
    }


def b2_budget_respected():
    budget = ContextBudget(total=1200)
    fitted, used = budget.fit(_big_sections())
    ok = budget.is_within(fitted) and used["retrieval"] <= budget.cap("retrieval") + 20
    return ok, f"within={budget.is_within(fitted)} retrieval={used['retrieval']}/{budget.cap('retrieval')}"


def b3_trim_keeps_system():
    sections = _big_sections()
    sys_text = sections["system"]
    budget = ContextBudget(total=800)
    fitted, _ = budget.fit(sections)
    ok = fitted["system"] == sys_text and len(fitted["retrieval"]) < len(sections["retrieval"])
    return ok, f"system_intact={fitted['system'] == sys_text} retrieval {len(sections['retrieval'])}→{len(fitted['retrieval'])}"


def b4_schema_blocks():
    mock = MockLLM()
    mock.register_fault("__BADJSON__", 1)
    client = LLMClient(mock=mock, sleeper=lambda s: None)
    try:
        client.complete_json("输出 JSON __BADJSON__", ["answer"], max_attempts_repair=0)
        return False, "未拦截非法输出"
    except LLMError as e:
        ok = e.code == "SCHEMA_INVALID"
        return ok, f"code={e.code}"


def b5_badcase_set():
    cases = load_badcases(os.path.join(HERE, "badcases.jsonl"))
    stats = badcase_stats(cases)
    ok = (
        stats["count"] >= 12
        and stats["fields_complete"]
        and all(label in stats["labels"] for label in BAD_LABELS)
    )
    return ok, f"count={stats['count']} labels={stats['labels']} complete={stats['fields_complete']}"


def b6_rollback():
    b = build_default()
    b.bump("v1.1").add("L3", "输出格式：只输出 JSON。")
    old_text = b.layers["L3"]
    b.rollback()
    ok = b.version == "v1.0" and b.layers["L3"] != old_text
    return ok, f"version={b.version} restored={b.layers['L3'] != old_text}"


def b7_deterministic():
    ok = build_default().render() == build_default().render()
    return ok, f"same={ok}"


def main() -> int:
    for name, fn in [
        ("B1 五层齐全", b1_five_layers),
        ("B2 预算不超限", b2_budget_respected),
        ("B3 裁剪保留system", b3_trim_keeps_system),
        ("B4 schema拦截", b4_schema_blocks),
        ("B5 badcase集完整", b5_badcase_set),
        ("B6 版本可回滚", b6_rollback),
        ("B7 装配确定性", b7_deterministic),
    ]:
        check(name, fn)

    passed = 0
    for name, ok, msg in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  |  {msg}")
        passed += ok
    print(f"[CH02] {'PASS' if passed == len(RESULTS) else 'FAIL'} {passed}/{len(RESULTS)}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
