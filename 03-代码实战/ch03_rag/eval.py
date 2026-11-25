"""第 03 章 · 指标报告：Recall@k 与 Answer Accuracy

运行：python ch03_rag/eval.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from main import RAGPipeline, evaluate, load_goldenset  # noqa: E402

HERE = os.path.dirname(__file__)


def main() -> int:
    pipe = RAGPipeline(os.path.join(HERE, "data", "docs"))
    golden = load_goldenset()
    rep = evaluate(pipe, golden)

    print("=" * 46)
    print("RAG 评测报告")
    print("=" * 46)
    print(f"样本数            : {rep['n']}（可回答 {rep['answerable']} / 应拒答 {rep['n'] - rep['answerable']}）")
    print(f"Recall@4          : {rep['recall@4']:.2%}")
    print(f"Answer Accuracy   : {rep['accuracy']:.2%}  ({rep['correct']}/{rep['n']})")
    print("-" * 46)

    fails = [d for d in rep["details"] if not d["pass"]]
    print(f"未通过用例 {len(fails)} 条：")
    for d in fails:
        print(f"  - {d['id']} recall={d['recall']}")

    with open(os.path.join(HERE, "reports", "eval_latest.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print("\n报告已保存到 reports/eval_latest.json")

    ok = rep["recall@4"] >= 0.70 and rep["accuracy"] >= 0.75
    print(f"[EVAL] {'PASS' if ok else 'FAIL'}（阈值 Recall@4 ≥ 70%，Accuracy ≥ 75%）")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
