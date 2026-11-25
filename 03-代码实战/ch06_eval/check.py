"""第 06 章 L2 代码闸门：7 条断言。运行：python ch06_eval/check.py"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "common"))
sys.path.insert(0, HERE)

from judge import RUBRIC, judge  # noqa: E402
from run_eval import evaluate_run, gate_check, load_jsonl, p95  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []

GOLDEN = load_jsonl(os.path.join(HERE, "data", "goldenset.jsonl"))
V1 = evaluate_run(GOLDEN, load_jsonl(os.path.join(HERE, "data", "runs", "v1.jsonl")))
V2 = evaluate_run(GOLDEN, load_jsonl(os.path.join(HERE, "data", "runs", "v2.jsonl")))
GATE = gate_check(V1, V2)


def check(name, fn):
    try:
        ok, msg = fn()
    except Exception as e:  # noqa: BLE001
        ok, msg = False, f"{type(e).__name__}: {e}"
    RESULTS.append((name, ok, msg))


def f1_goldenset():
    tags = {}
    for g in GOLDEN:
        tags[g["tag"]] = tags.get(g["tag"], 0) + 1
    ok = (
        len(GOLDEN) == 40
        and tags.get("常见") == 20
        and tags.get("边界") == 10
        and tags.get("应拒答") == 6
        and tags.get("对抗") == 4
        and all(g.get("points") is not None and "safety" in g and "forbid" in g for g in GOLDEN)
    )
    return ok, f"n={len(GOLDEN)} tags={tags}"


def f2_rubric_weights():
    s = round(sum(RUBRIC.values()), 6)
    return s == 1.0, f"sum={s} rubric={RUBRIC}"


def f3_v1_manual():
    fails = [r["id"] for r in V1["results"] if not r["passed"]]
    manual_pass = sum(1 for r in V1["results"] if r["passed"] and r["total"] >= 80 and not r["safety_veto"])
    ok = V1["passed"] == manual_pass and len(fails) == 4 and V1["pass_rate"] == 90.0
    return ok, f"passed={V1['passed']} fails={fails} rate={V1['pass_rate']}"


def f4_v2_blocked():
    ok = (
        (not GATE["passed"])
        and (not GATE["checks"]["safety"]["ok"])
        and GATE["checks"]["pass_rate"]["ok"]           # 通过率没掉 → 说明不是靠掉分拦住的
        and GATE["diff"]["new_failures"] == ["g24", "g28", "g31", "g32"]
    )
    return ok, f"blocked={not GATE['passed']} safety_ok={GATE['checks']['safety']['ok']} diff={GATE['diff']}"


def f5_p95():
    data = list(range(1, 101))
    manual = sorted(data)[int(round(0.95 * (len(data) - 1)))]
    ok = p95(data) == manual and p95([]) == 0 and p95([5]) == 5
    return ok, f"p95={p95(data)} manual={manual}"


def f6_judge_structure():
    item = GOLDEN[0]
    out = {"id": item["id"], "answer": "结论：" + "；".join(item["points"]) + "。依据：见 doc1#p1。免责：不替代医生诊断。", "citations": ["doc1#p1"]}
    r = judge(item, out)
    ok = {"id", "scores", "total", "passed", "reasons", "safety_veto"} <= set(r) and 0 <= r["total"] <= 100
    json.dumps(r, ensure_ascii=False)
    return ok, f"total={r['total']} passed={r['passed']}"


def f7_safety_veto_logic():
    item = next(g for g in GOLDEN if g["safety"] and g["forbid"])
    good = {"id": item["id"], "answer": "结论：不提供剂量，请咨询医生。依据：见 doc1。", "citations": []}
    bad = {"id": item["id"], "answer": f"结论：{item['forbid'][0]}。", "citations": []}
    rg = judge(item, good)
    rb = judge(item, bad)
    ok = (not rb["passed"]) and rb["safety_veto"] and rg["scores"]["safety"] == 4
    return ok, f"good_safety={rg['scores']['safety']} bad_veto={rb['safety_veto']}"


def main() -> int:
    for name, fn in [
        ("F1 金标集构成", f1_goldenset),
        ("F2 rubric 权重", f2_rubric_weights),
        ("F3 v1 通过数可复算", f3_v1_manual),
        ("F4 v2 被安全门禁阻断", f4_v2_blocked),
        ("F5 P95 计算", f5_p95),
        ("F6 判分器结构", f6_judge_structure),
        ("F7 安全一票否决", f7_safety_veto_logic),
    ]:
        check(name, fn)

    passed = 0
    for name, ok, msg in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  |  {msg}")
        passed += ok
    print(f"[CH06] {'PASS' if passed == len(RESULTS) else 'FAIL'} {passed}/{len(RESULTS)}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
