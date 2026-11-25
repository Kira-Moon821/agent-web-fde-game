"""第 03 章 · RAG 全链路（离线可跑）

链路：解析 → 切分 → 向量化 → 向量+BM25 混合索引 → 召回+阈值 → 带引用抽取式作答/拒答

运行：python ch03_rag/main.py
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from mock_llm import MockLLM  # noqa: E402

HERE = os.path.dirname(__file__)
MAX_CHUNK_CHARS = 220
MIN_BM25 = 0.35          # 关键词覆盖下限：低于它视为"知识库没这块内容" → 拒答
TOP_K = 4
REFUSAL = "资料不足：知识库未覆盖该问题，建议咨询专业人员或补充资料后重试。"


# ---------------- ①解析 ----------------
def parse_docs(doc_dir: str) -> list[dict]:
    out = []
    for path in sorted(glob.glob(os.path.join(doc_dir, "*.md"))):
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        title = ""
        paras = []
        for block in re.split(r"\n\s*\n", text.strip()):
            block = block.strip()
            if not block:
                continue
            if block.startswith("#"):
                title = block.lstrip("# ").strip()
                continue
            paras.append(block.replace("\n", " "))
        out.append({"doc": name, "title": title, "paras": paras})
    return out


# ---------------- ②切分 ----------------
def chunk_docs(docs: list[dict], max_chars: int = MAX_CHUNK_CHARS) -> list[dict]:
    chunks = []
    for d in docs:
        doc_id = d["doc"].split("-")[0].replace("doc", "doc")  # doc1/doc2/doc3
        for i, p in enumerate(d["paras"], start=1):
            if len(p) <= max_chars:
                pieces = [p]
            else:
                pieces = [p[j : j + max_chars] for j in range(0, len(p), max_chars)]
            for k, piece in enumerate(pieces):
                cid = f"{doc_id}#p{i}" if len(pieces) == 1 else f"{doc_id}#p{i}-{k + 1}"
                chunks.append(
                    {
                        "id": cid,
                        "doc": d["doc"],
                        "title": d["title"],
                        "text": piece,
                        "len": len(piece),
                    }
                )
    return chunks


# ---------------- ③向量化 ----------------
def embed_all(chunks: list[dict], embedder: MockLLM) -> None:
    for c in chunks:
        c["vec"] = embedder.embed(c["title"] + " " + c["text"], dim=48)


# ---------------- 检索 ----------------
def tokens(text: str) -> list[str]:
    """中文二元组 + 英文/数字词，用于 BM25。"""
    text = re.sub(r"[，。？！、；：（）“”‘’\-\s]", " ", text)
    cjk = re.findall(r"[\u4e00-\u9fff]+", text)
    grams: list[str] = []
    for run in cjk:
        if len(run) == 1:
            grams.append(run)
        else:
            grams += [run[i : i + 2] for i in range(len(run) - 1)]
    grams += re.findall(r"[A-Za-z0-9]+", text)
    return grams


def bm25_scores(query: str, chunks: list[dict], k1: float = 1.5, b: float = 0.75) -> list[float]:
    q_terms = tokens(query)
    if not q_terms:
        return [0.0] * len(chunks)
    docs_tokens = [tokens(c["text"] + " " + c["title"]) for c in chunks]
    n = len(chunks)
    avgdl = sum(len(t) for t in docs_tokens) / max(n, 1)
    df = {t: sum(1 for dt in docs_tokens if t in dt) for t in set(q_terms)}
    scores = []
    for dt in docs_tokens:
        tf_map = {t: dt.count(t) for t in q_terms}
        s = 0.0
        for t in q_terms:
            if df.get(t, 0) == 0:
                continue
            idf = math.log((n - df[t] + 0.5) / (df[t] + 0.5) + 1)
            tf = tf_map[t]
            dl = len(dt)
            s += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
        scores.append(s)
    # 归一化到 0–1，便于与向量分融合
    mx = max(scores) or 1.0
    return [s / mx for s in scores]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class Retriever:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks

    def search(self, query: str, k: int = TOP_K, w_bm25: float = 0.75) -> list[tuple[dict, float, float]]:
        bm = bm25_scores(query, self.chunks)
        qv = MockLLM().embed(query, dim=48)
        cos = [cosine(qv, c["vec"]) for c in self.chunks]
        fusion = [w_bm25 * bm[i] + (1 - w_bm25) * (cos[i] + 1) / 2 for i in range(len(self.chunks))]
        order = sorted(range(len(self.chunks)), key=lambda i: fusion[i], reverse=True)[:k]
        return [(self.chunks[i], fusion[i], bm[i]) for i in order]

    @property
    def size(self) -> int:
        return len(self.chunks)


# ---------------- ④作答 ----------------
def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"。", text) if s.strip()]


def extract_answer(query: str, hits: list[tuple[dict, float, float]]) -> dict:
    best_chunk, best_score, best_bm = hits[0]
    if best_bm < MIN_BM25:
        return {"answer": REFUSAL, "citations": [], "refused": True, "reason": "LOW_RELEVANCE"}

    q_terms = set(tokens(query))
    sents = split_sentences(best_chunk["text"])
    scored = sorted(
        ((len(q_terms & set(tokens(s))), s) for s in sents), key=lambda x: x[0], reverse=True
    )
    picked = [s for _, s in scored[:2] if s] or [sents[0] if sents else best_chunk["text"]]
    citations = [h[0]["id"] for h in hits if h[2] >= MIN_BM25][:2] or [best_chunk["id"]]
    return {
        "answer": "结论：" + "；".join(picked) + "。\n依据：以上内容摘自 " + "、".join(citations) + "。",
        "citations": citations,
        "refused": False,
        "reason": "OK",
        "score": round(best_score, 4),
    }


@dataclass
class RAGPipeline:
    doc_dir: str

    def __post_init__(self):
        docs = parse_docs(self.doc_dir)
        self.chunks = chunk_docs(docs)
        embed_all(self.chunks, MockLLM())
        self.retriever = Retriever(self.chunks)

    def ask(self, query: str) -> dict:
        hits = self.retriever.search(query)
        res = extract_answer(query, hits)
        res["retrieved"] = [h[0]["id"] for h in hits]
        return res


# ---------------- 评测 ----------------
def load_goldenset(path: str | None = None) -> list[dict]:
    p = path or os.path.join(HERE, "data", "goldenset.jsonl")
    with open(p, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def evaluate(pipeline: RAGPipeline, goldenset: list[dict], k: int = TOP_K) -> dict:
    answerable = [g for g in goldenset if g["answerable"]]
    recall_hits = 0
    correct = 0
    details = []
    for g in goldenset:
        res = pipeline.ask(g["question"])
        if g["answerable"]:
            hit = g["expected_chunk"] in res["retrieved"][:k]
            recall_hits += hit
            ok = hit and (g["expected_fact"] in res["answer"])
        else:
            ok = res["refused"]
        correct += ok
        details.append({"id": g["id"], "answerable": g["answerable"], "recall": bool(hit) if g["answerable"] else None, "pass": bool(ok)})
    return {
        "n": len(goldenset),
        "answerable": len(answerable),
        f"recall@{k}": round(recall_hits / max(len(answerable), 1), 4),
        "accuracy": round(correct / max(len(goldenset), 1), 4),
        "correct": correct,
        "details": details,
    }


def main() -> None:
    pipe = RAGPipeline(os.path.join(HERE, "data", "docs"))
    print(f"索引完成：{pipe.retriever.size} 个 chunk")
    golden = load_goldenset()
    report = evaluate(pipe, golden)
    print(json.dumps({k: v for k, v in report.items() if k != "details"}, ensure_ascii=False, indent=2))
    print("\n示例：", golden[1]["question"])
    print(json.dumps(pipe.ask(golden[1]["question"]), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
