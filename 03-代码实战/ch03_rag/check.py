"""第 03 章 L2 代码闸门：8 条断言。运行：python ch03_rag/check.py"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "common"))
sys.path.insert(0, HERE)

from main import (  # noqa: E402
    MAX_CHUNK_CHARS,
    MIN_BM25,
    REFUSAL,
    RAGPipeline,
    evaluate,
    load_goldenset,
)

RESULTS: list[tuple[str, bool, str]] = []
PIPE = RAGPipeline(os.path.join(HERE, "data", "docs"))
GOLD = load_goldenset()


def check(name, fn):
    try:
        ok, msg = fn()
    except Exception as e:  # noqa: BLE001
        ok, msg = False, f"{type(e).__name__}: {e}"
    RESULTS.append((name, ok, msg))


def c1_chunking():
    bad = [c for c in PIPE.chunks if c["len"] > MAX_CHUNK_CHARS or not c["id"] or not c["text"]]
    ids_unique = len({c["id"] for c in PIPE.chunks}) == len(PIPE.chunks)
    return (not bad and ids_unique), f"chunks={len(PIPE.chunks)} bad={len(bad)} unique={ids_unique}"


def c2_hybrid_hit():
    hits = PIPE.retriever.search("ALT 的参考区间是多少？")
    return hits[0][0]["id"] == "doc1#p1", f"top1={hits[0][0]['id']} score={hits[0][1]:.3f} bm25={hits[0][2]:.3f}"


def c3_refusal():
    r = PIPE.ask("医院食堂几点开饭？")
    return r["refused"] and r["citations"] == [] and REFUSAL in r["answer"], f"refused={r['refused']} cites={r['citations']}"


def c4_citations():
    missing = []
    for g in GOLD:
        if not g["answerable"]:
            continue
        r = PIPE.ask(g["question"])
        if not r["citations"] or "依据" not in r["answer"]:
            missing.append(g["id"])
    return not missing, f"缺引用用例={missing}"


def c5_goldenset():
    fields_ok = all(
        g.get("id") and g.get("question") and isinstance(g.get("answerable"), bool) for g in GOLD
    )
    has_both = any(g["answerable"] for g in GOLD) and any(not g["answerable"] for g in GOLD)
    return fields_ok and has_both and len(GOLD) >= 20, f"n={len(GOLD)} fields_ok={fields_ok} both_types={has_both}"


def c6_metric_recompute():
    rep = evaluate(PIPE, GOLD)
    manual_recall_hits = 0
    manual_correct = 0
    n_ans = 0
    for g in GOLD:
        r = PIPE.ask(g["question"])
        if g["answerable"]:
            n_ans += 1
            if g["expected_chunk"] in r["retrieved"][:4]:
                manual_recall_hits += 1
                if g["expected_fact"] in r["answer"]:
                    manual_correct += 1
        else:
            manual_correct += bool(r["refused"])
    manual = (round(manual_recall_hits / n_ans, 4), round(manual_correct / len(GOLD), 4))
    ok = manual == (rep["recall@4"], rep["accuracy"])
    return ok, f"report={rep['recall@4']}/{rep['accuracy']} manual={manual}"


def c7_stability():
    q = GOLD[3]["question"]
    return PIPE.ask(q) == PIPE.ask(q), f"q={q}"


def c8_thresholds():
    rep = evaluate(PIPE, GOLD)
    ok = rep["recall@4"] >= 0.70 and rep["accuracy"] >= 0.75
    return ok, f"recall@4={rep['recall@4']:.2%} acc={rep['accuracy']:.2%} threshold_bm25={MIN_BM25}"


def main() -> int:
    for name, fn in [
        ("C1 切分合规", c1_chunking),
        ("C2 混合召回命中", c2_hybrid_hit),
        ("C3 低相关拒答", c3_refusal),
        ("C4 答案带引用", c4_citations),
        ("C5 金标集完整", c5_goldenset),
        ("C6 指标可复算", c6_metric_recompute),
        ("C7 结果稳定", c7_stability),
        ("C8 指标达阈值", c8_thresholds),
    ]:
        check(name, fn)

    passed = 0
    for name, ok, msg in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  |  {msg}")
        passed += ok
    print(f"[CH03] {'PASS' if passed == len(RESULTS) else 'FAIL'} {passed}/{len(RESULTS)}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
