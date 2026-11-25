"""第 06 章 · 评测执行与回归门禁

运行：
  python ch06_eval/run_eval.py --run v1            # 基线
  python ch06_eval/run_eval.py --run v2 --gate     # 与 v1 对比并判定门禁
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "common"))

from judge import PASS_LINE, RUBRIC, judge_all  # noqa: E402
from mock_llm import cost_of, estimate_tokens  # noqa: E402

GATE = {"pass_drop_pt": 2.0, "p95_ms": 1000, "avg_cost_yuan": 0.005}


def load_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def p95(values: list[int]) -> int:
    if not values:
        return 0
    s = sorted(values)
    idx = min(len(s) - 1, int(round(0.95 * (len(s) - 1))))
    return s[idx]


def cost_of_row(row: dict) -> float:
    return cost_of(estimate_tokens(row.get("answer", "")), estimate_tokens(row.get("answer", "")))


def evaluate_run(golden: list[dict], run: list[dict]) -> dict:
    results = judge_all(golden, run)
    passed = [r for r in results if r["passed"]]
    run_by_id = {r["id"]: r for r in run}
    lat = [run_by_id[r["id"]]["latency_ms"] for r in results if r["id"] in run_by_id]
    costs = [cost_of_row(run_by_id[r["id"]]) for r in results if r["id"] in run_by_id]
    return {
        "total": len(results),
        "passed": len(passed),
        "pass_rate": round(len(passed) / max(len(results), 1) * 100, 2),
        "p95_ms": p95(lat),
        "avg_cost_yuan": round(sum(costs) / max(len(costs), 1), 6),
        "safety_veto": [r["id"] for r in results if r["safety_veto"]],
        "results": results,
        "pass_ids": {r["id"] for r in results if r["passed"]},
    }


def gate_check(baseline: dict, current: dict) -> dict:
    checks = {
        "pass_rate": {
            "value": current["pass_rate"],
            "baseline": baseline["pass_rate"],
            "ok": current["pass_rate"] >= baseline["pass_rate"] - GATE["pass_drop_pt"],
            "rule": f"通过率 ≥ 基线 -{GATE['pass_drop_pt']}pt",
        },
        "safety": {
            "value": len(current["safety_veto"]),
            "baseline": len(baseline["safety_veto"]),
            "ok": len(current["safety_veto"]) == 0,
            "rule": "安全类回归必须为 0",
        },
        "p95": {"value": current["p95_ms"], "ok": current["p95_ms"] <= GATE["p95_ms"], "rule": f"P95 ≤ {GATE['p95_ms']}ms"},
        "cost": {
            "value": current["avg_cost_yuan"],
            "ok": current["avg_cost_yuan"] <= GATE["avg_cost_yuan"],
            "rule": f"单次成本 ≤ {GATE['avg_cost_yuan']} 元",
        },
    }
    ok = all(c["ok"] for c in checks.values())
    diff = {
        "new_failures": sorted(baseline["pass_ids"] - current["pass_ids"]),
        "new_passes": sorted(current["pass_ids"] - baseline["pass_ids"]),
    }
    return {"passed": ok, "checks": checks, "diff": diff}


def print_report(tag: str, rep: dict) -> None:
    print(f"\n[{tag}] 样本 {rep['total']} | 通过 {rep['passed']} | 通过率 {rep['pass_rate']}% | P95 {rep['p95_ms']}ms | 单次成本 {rep['avg_cost_yuan']} 元")
    if rep["safety_veto"]:
        print(f"      安全否决：{rep['safety_veto']}")
    fails = [r for r in rep["results"] if not r["passed"]]
    for r in fails:
        print(f"      FAIL {r['id']} total={r['total']} {'; '.join(r['reasons'])}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="v1")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--baseline", default="v1")
    args = ap.parse_args()

    golden_path = os.path.join(HERE, "data", "goldenset.jsonl")
    if not os.path.exists(golden_path):
        from make_goldenset import main as mk

        mk()
    golden = load_jsonl(golden_path)

    runs_dir = os.path.join(HERE, "data", "runs")
    if not os.path.exists(os.path.join(runs_dir, f"{args.run}.jsonl")):
        from synth_runs import main as sy

        sy()

    cur = evaluate_run(golden, load_jsonl(os.path.join(runs_dir, f"{args.run}.jsonl")))
    print_report(args.run, cur)

    if args.gate:
        base = evaluate_run(golden, load_jsonl(os.path.join(runs_dir, f"{args.baseline}.jsonl")))
        print_report(args.baseline + "(基线)", base)
        g = gate_check(base, cur)
        print("\n门禁判定：", "通过" if g["passed"] else "阻断")
        for name, c in g["checks"].items():
            print(f"  [{'OK' if c['ok'] else 'BLOCK'}] {name}: {c['value']}（{c['rule']}）")
        print(f"  新增失败：{g['diff']['new_failures']}")
        print(f"  新增通过：{g['diff']['new_passes']}")

        out = {"run": args.run, "baseline": args.baseline, "gate": g, "report": {k: v for k, v in cur.items() if k not in ("results", "pass_ids")}}
        with open(os.path.join(HERE, "reports", f"gate_{args.run}.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        return 0 if g["passed"] else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
