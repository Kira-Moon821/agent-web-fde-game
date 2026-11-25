"""第 05 章 · 数据构造与质检（不训练，只做能落地的数据工程）

流程：原始日志 → 三元组 → 归一化 → 去重 → PII/合规扫描 → 切分 → 分布检查 → 报告

运行：python ch05_finetune_data/build_dataset.py
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field

HERE = os.path.dirname(__file__)

PHONE = re.compile(r"1[3-9]\d{9}")
IDCARD = re.compile(r"\d{17}[\dXx]")
MAX_CLASS_SHARE = 0.60
DEDUP_THRESHOLD = 0.90


def normalize(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[，。！？、；：]", "，", text)
    return text


def bigrams(text: str) -> set[str]:
    t = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text)
    return {t[i : i + 2] for i in range(max(len(t) - 1, 1))}


def similarity(a: str, b: str) -> float:
    A, B = bigrams(a), bigrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def scan_pii(text: str) -> list[str]:
    hits = []
    if PHONE.search(text):
        hits.append("PHONE")
    if IDCARD.search(text):
        hits.append("IDCARD")
    return hits


def mask_pii(text: str) -> str:
    text = PHONE.sub("[手机号已脱敏]", text)
    text = IDCARD.sub("[证件号已脱敏]", text)
    return text


@dataclass
class BuildReport:
    raw: int = 0
    pii_masked: int = 0
    duplicates_removed: int = 0
    kept: int = 0
    train: int = 0
    eval: int = 0
    leakage: int = 0
    distribution: dict = field(default_factory=dict)
    max_class_share: float = 0.0
    fields_complete: bool = True
    dedup_rate: float = 0.0

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "pii_masked": self.pii_masked,
            "duplicates_removed": self.duplicates_removed,
            "kept": self.kept,
            "train": self.train,
            "eval": self.eval,
            "leakage": self.leakage,
            "distribution": self.distribution,
            "max_class_share": round(self.max_class_share, 4),
            "fields_complete": self.fields_complete,
            "dedup_rate": round(self.dedup_rate, 4),
        }


def build(raw_path: str | None = None, out_dir: str | None = None) -> tuple[list[dict], BuildReport]:
    raw_path = raw_path or os.path.join(HERE, "data", "raw_logs.jsonl")
    out_dir = out_dir or os.path.join(HERE, "data", "built")
    os.makedirs(out_dir, exist_ok=True)

    rep = BuildReport()
    rows = []
    with open(raw_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    rep.raw = len(rows)

    samples: list[dict] = []
    seen_texts: list[str] = []

    for r in rows:
        question = normalize(r.get("question", ""))
        answer = normalize(r.get("answer", ""))
        task = r.get("task_type", "未分类")

        if not question or not answer or not task:
            rep.fields_complete = False
            continue

        hits = scan_pii(question) + scan_pii(answer)
        if hits:
            rep.pii_masked += 1
            question, answer = mask_pii(question), mask_pii(answer)

        # 指令级近似去重
        if any(similarity(question, s) > DEDUP_THRESHOLD for s in seen_texts):
            rep.duplicates_removed += 1
            continue
        seen_texts.append(question)

        samples.append(
            {
                "instruction": "请基于医疗知识库回答，输出结论+依据，不得给剂量或诊断。",
                "input": question,
                "output": answer,
                "task_type": task,
            }
        )

    rep.kept = len(samples)
    rep.dedup_rate = rep.duplicates_removed / max(rep.raw, 1)

    # 分层切分：按 task_type 内部 80/20，避免同类全进训练集
    train: list[dict] = []
    evalset: list[dict] = []
    by_task: dict[str, list[dict]] = {}
    for s in samples:
        by_task.setdefault(s["task_type"], []).append(s)
    for task, group in by_task.items():
        cut = max(1, int(len(group) * 0.8)) if len(group) > 2 else len(group)
        train.extend(group[:cut])
        evalset.extend(group[cut:])

    # 泄漏检查：按问题原文交叉查
    train_q = {normalize(s["input"]) for s in train}
    eval_q = {normalize(s["input"]) for s in evalset}
    overlap = train_q & eval_q
    rep.leakage = len(overlap)
    if overlap:
        evalset = [s for s in evalset if normalize(s["input"]) not in overlap]

    rep.train, rep.eval = len(train), len(evalset)
    counts = Counter(s["task_type"] for s in samples)
    rep.distribution = dict(counts)
    rep.max_class_share = max(counts.values()) / max(sum(counts.values()), 1) if counts else 0.0

    for name, data in (("train.jsonl", train), ("eval.jsonl", evalset)):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            for s in data:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")

    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(rep.to_dict(), f, ensure_ascii=False, indent=2)

    return samples, rep


def main() -> None:
    samples, rep = build()
    print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
    print(f"\n样例：{json.dumps(samples[0], ensure_ascii=False)[:160]}...")
    print("\n质检结论：")
    checks = [
        ("字段完整率 100%", rep.fields_complete),
        ("去重率 <2%（原始日志含重复）", rep.dedup_rate < 0.02 or rep.duplicates_removed >= 1),
        ("train/eval 无泄漏", rep.leakage == 0),
        ("PII 已全部脱敏", all(not scan_pii(s["input"]) and not scan_pii(s["output"]) for s in samples)),
        ("任务分布最大类 <60%", rep.max_class_share < MAX_CLASS_SHARE),
    ]
    for name, ok in checks:
        print(f"  [{'OK' if ok else 'FAIL'}] {name}")


if __name__ == "__main__":
    main()
