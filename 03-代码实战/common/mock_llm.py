"""common/mock_llm.py — 确定性的本地 Mock 模型（离线可跑，无需 API Key）

设计目标：
1. 可复现：同样输入 → 同样输出、同样 token 数、同样成本。
2. 可注入故障：用 marker 触发 429 / 超时 / 非法 JSON，用来检验工程处理分支。
3. 可替换：真实 provider 在 common/llm_client.py 里切换，接口不变。
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from typing import Iterable


class LLMError(Exception):
    """带错误码的模型调用异常。"""

    def __init__(self, code: str, message: str = "", retry_after: int = 0):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.retry_after = retry_after


@dataclass
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int
    model: str = "mock-llm-1"
    latency_ms: int = 0


def _is_cjk(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：中文 1 字 ≈ 0.6 token，英文 1 词 ≈ 1.3 token。

    仅为工程量级估算，真实计数以 provider 返回的 usage 为准。
    """
    cjk = sum(1 for ch in text if _is_cjk(ch))
    ascii_words = len([w for w in text.replace("\n", " ").split(" ") if w and not _is_cjk(w[0])])
    other = max(len(text) - cjk, 0)
    return max(1, int(cjk * 0.6 + ascii_words * 1.3 + other * 0.3))


# 单价（元 / 1K tokens），用于成本核算练习
PRICING = {"input_per_1k": 0.002, "output_per_1k": 0.008}


def cost_of(prompt_tokens: int, completion_tokens: int) -> float:
    return round(
        prompt_tokens / 1000 * PRICING["input_per_1k"]
        + completion_tokens / 1000 * PRICING["output_per_1k"],
        6,
    )


@dataclass
class CostLedger:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0

    def add(self, c: Completion) -> None:
        self.calls += 1
        self.prompt_tokens += c.prompt_tokens
        self.completion_tokens += c.completion_tokens
        self.cost = round(self.cost + cost_of(c.prompt_tokens, c.completion_tokens), 6)

    def report(self) -> dict:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_yuan": self.cost,
            "cost_per_1k_calls_yuan": round(self.cost / max(self.calls, 1) * 1000, 4),
        }


FAULT_MARKERS = ("__FAIL_429__", "__SLOW__", "__BADJSON__")


class MockLLM:
    """确定性 Mock。

    故障注入：
      - prompt 含 "__FAIL_429__" → 前 N 次抛 429（N 由 register_fault 指定，默认 1）
      - prompt 含 "__SLOW__"     → sleep(slow_seconds)
      - prompt 含 "__BADJSON__"  → 第一次返回非法 JSON，第二次返回合法 JSON
    """

    def __init__(self, slow_seconds: float = 0.5):
        self.slow_seconds = slow_seconds
        self.faults: dict[str, int] = {}
        self._attempts: dict[str, int] = {}

    def register_fault(self, marker: str, times: int = 1) -> None:
        self.faults[marker] = times

    # ---- 内部：确定性伪随机 ----
    @staticmethod
    def _seed(prompt: str) -> int:
        return int(hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8], 16)

    def complete(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
        model: str = "mock-llm-1",
    ) -> Completion:
        t0 = time.time()

        for marker in FAULT_MARKERS:
            if marker in prompt:
                self._attempts[marker] = self._attempts.get(marker, 0) + 1

        if "__FAIL_429__" in prompt:
            remain = self.faults.get("__FAIL_429__", 1) - (self._attempts["__FAIL_429__"] - 1)
            if remain > 0:
                raise LLMError("RATE_LIMITED", "too many requests", retry_after=2)

        if "__SLOW__" in prompt:
            time.sleep(self.slow_seconds)

        need_json = ("JSON" in prompt) or ("json" in prompt) or ('"answer"' in prompt)

        if "__BADJSON__" in prompt and self._attempts["__BADJSON__"] == 1:
            body = '{"answer": "未闭合的 JSON'
        elif need_json:
            body = json.dumps(
                {"answer": "这是基于 Mock 模型的确定性回答。", "citations": ["doc-1#p2"], "confidence": 0.86},
                ensure_ascii=False,
            )
        else:
            seed = self._seed(prompt)
            body = (
                f"（Mock 回答 seed={seed % 1000}）已按指令处理该请求："
                f"结论基于给定上下文，未超出边界；温度={temperature}。"
            )

        # 截断到 max_tokens（按估算比例粗切）
        if estimate_tokens(body) > max_tokens:
            keep = max(1, int(len(body) * max_tokens / estimate_tokens(body)))
            body = body[:keep]

        latency = int((time.time() - t0) * 1000)
        return Completion(
            text=body,
            prompt_tokens=estimate_tokens(prompt),
            completion_tokens=estimate_tokens(body),
            model=model,
            latency_ms=latency,
        )

    # ---- 供第 03 章使用：确定性 embedding ----
    def embed(self, text: str, dim: int = 64) -> list[float]:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        raw = [b / 255.0 - 0.5 for b in h]  # 32 维
        vec = (raw * math.ceil(dim / len(raw)))[:dim]
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [round(v / norm, 6) for v in vec]

    # ---- 供第 07 章使用：流式 ----
    def stream(self, text: str, chunk: int = 8) -> Iterable[str]:
        for i in range(0, len(text), chunk):
            yield text[i : i + chunk]
