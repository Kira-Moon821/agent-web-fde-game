"""第 05 章 L2 代码闸门：6 条断言。运行：python ch05_finetune_data/check.py"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)

from build_dataset import MAX_CLASS_SHARE, build, scan_pii  # noqa: E402
from lora_math import estimate_transformer_lora, lora_params, memory_gb  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []
SAMPLES, REP = build()


def check(name, fn):
    try:
        ok, msg = fn()
    except Exception as e:  # noqa: BLE001
        ok, msg = False, f"{type(e).__name__}: {e}"
    RESULTS.append((name, ok, msg))


def e1_fields_complete():
    ok = REP.fields_complete and all(s["instruction"] and s["input"] and s["output"] for s in SAMPLES)
    return ok, f"kept={REP.kept} complete={REP.fields_complete}"


def e2_dedup():
    ok = REP.duplicates_removed >= 1 and REP.dedup_rate < 0.10
    return ok, f"removed={REP.duplicates_removed} rate={REP.dedup_rate:.2%}"


def e3_no_leakage():
    return REP.leakage == 0, f"leakage={REP.leakage} train={REP.train} eval={REP.eval}"


def e4_pii_masked():
    rows = []
    with open(os.path.join(HERE, "data", "built", "train.jsonl"), encoding="utf-8") as f:
        rows += [l for l in f if l.strip()]
    bad = [r for r in rows if scan_pii(r)]
    return (not bad) and REP.pii_masked >= 1, f"pii_masked={REP.pii_masked} residual={len(bad)}"


def e5_distribution():
    ok = REP.max_class_share < MAX_CLASS_SHARE and len(REP.distribution) >= 4
    return ok, f"dist={REP.distribution} max={REP.max_class_share:.2%}"


def e6_lora_math():
    p = estimate_transformer_lora(8, 4096, 32, ("q", "v"))
    formula = 4 * 8 * 4096 * 32
    p2 = lora_params(16, [(1024, 1024), (1024, 2048)])
    manual2 = 16 * (1024 + 1024) + 16 * (1024 + 2048)
    mem = memory_gb(p)
    ok = p == formula and p2 == manual2 and 0 < mem < 10
    return ok, f"params={p:,}(期望 {formula:,}) p2={p2} mem={mem}GB"


def main() -> int:
    for name, fn in [
        ("E1 字段完整", e1_fields_complete),
        ("E2 去重有效", e2_dedup),
        ("E3 无数据泄漏", e3_no_leakage),
        ("E4 PII 已脱敏", e4_pii_masked),
        ("E5 分布不畸形", e5_distribution),
        ("E6 LoRA 估算正确", e6_lora_math),
    ]:
        check(name, fn)

    passed = 0
    for name, ok, msg in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  |  {msg}")
        passed += ok
    print(f"[CH05] {'PASS' if passed == len(RESULTS) else 'FAIL'} {passed}/{len(RESULTS)}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
