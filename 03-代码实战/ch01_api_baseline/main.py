"""第 01 章 · 一个生产可用的 LLM 客户端

覆盖：重试退避 / 超时 / 上下文裁剪 / 结构化输出 / 成本记账。
运行：python ch01_api_baseline/main.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))

from llm_client import LLMClient, build_prompt  # noqa: E402
from mock_llm import LLMError, MockLLM, estimate_tokens  # noqa: E402

SYSTEM = """你是医疗知识库助手。
边界：仅基于给定资料回答；资料不足时明确说"资料不足"，不得编造剂量、诊断或预后。
输出：先结论，后依据，最后标注引用来源。"""


class ChatSession:
    """带上下文预算的会话：超过预算自动裁剪，保留 system 与最近若干轮。"""

    def __init__(self, client: LLMClient, budget: int = 900, keep_recent: int = 4):
        self.client = client
        self.budget = budget
        self.keep_recent = keep_recent
        self.messages: list[dict] = []

    def ask(self, question: str) -> str:
        self.messages.append({"role": "user", "content": question})
        system, msgs = LLMClient.trim_context(SYSTEM, self.messages, self.budget, self.keep_recent)
        c = self.client.complete(build_prompt(system, msgs), temperature=0.0, max_tokens=300)
        self.messages.append({"role": "assistant", "content": c.text})
        return c.text


def demo() -> None:
    mock = MockLLM()
    mock.register_fault("__FAIL_429__", 1)  # 模拟一次限流
    client = LLMClient(mock=mock, timeout_s=8)
    session = ChatSession(client)

    print("=== 1) 正常问答（含一次 429 后自动重试）===")
    print(session.ask("布洛芬的常见不良反应有哪些？__FAIL_429__"))

    print("\n=== 2) 结构化输出（JSON schema 校验）===")
    res = client.complete_json(
        "请把结论整理成 JSON，字段 answer/citations/confidence。问题：布洛芬不良反应。",
        required_keys=["answer", "citations", "confidence"],
    )
    print(json.dumps(res.data, ensure_ascii=False))

    print("\n=== 3) 成本记账 ===")
    print(json.dumps(client.ledger.report(), ensure_ascii=False, indent=2))

    print("\n=== 4) token 估算（中文 vs 英文）===")
    zh = "布洛芬的常见不良反应包括胃肠道不适、头晕和皮疹。"
    en = "Common adverse reactions of ibuprofen include GI upset, dizziness and rash."
    print(f"中文 {len(zh)} 字 → {estimate_tokens(zh)} tokens；英文 {len(en)} 字符 → {estimate_tokens(en)} tokens")


if __name__ == "__main__":
    try:
        demo()
    except LLMError as e:
        print(f"调用失败：{e.code} {e.message}")
        raise
