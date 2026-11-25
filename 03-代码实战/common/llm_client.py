"""common/llm_client.py — LLM 客户端抽象层

职责（第 01 章的核心交付物）：
  1. 重试退避（带抖动，最多 3 次）
  2. 超时控制（不静默返回空串）
  3. 上下文超限裁剪（保留 system + 最近若干轮）
  4. 结构化输出校验 + 一次修复重试
  5. 成本记账

环境变量切换真实 provider：
  LLM_PROVIDER=openai_compatible
  LLM_BASE_URL=https://api.xxx.com/v1
  LLM_API_KEY=sk-xxx
  LLM_MODEL=your-model
"""
from __future__ import annotations

import json
import os
import random
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Callable

from mock_llm import (
    CostLedger,
    Completion,
    LLMError,
    MockLLM,
    cost_of,
    estimate_tokens,
)


@dataclass
class StructuredResult:
    data: dict
    repaired: bool
    completion: Completion


class LLMClient:
    def __init__(
        self,
        model: str | None = None,
        timeout_s: float = 8.0,
        max_attempts: int = 3,
        sleeper: Callable[[float], None] | None = None,
        mock: MockLLM | None = None,
    ):
        self.provider = os.environ.get("LLM_PROVIDER", "mock")
        self.model = model or os.environ.get("LLM_MODEL", "mock-llm-1")
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts
        self._sleep = sleeper or time.sleep
        self.mock = mock or MockLLM()
        self.ledger = CostLedger()
        self.events: list[dict] = []   # 审计/日志

    # ---------------- 底层单次调用 ----------------
    def _raw_call(self, prompt: str, temperature: float, max_tokens: int) -> Completion:
        if self.provider == "mock":
            return self.mock.complete(prompt, temperature=temperature, max_tokens=max_tokens, model=self.model)
        return self._http_call(prompt, temperature, max_tokens)

    def _http_call(self, prompt: str, temperature: float, max_tokens: int) -> Completion:
        base = os.environ.get("LLM_BASE_URL", "").rstrip("/")
        key = os.environ.get("LLM_API_KEY", "")
        if not base or not key:
            raise LLMError("BAD_CONFIG", "缺少 LLM_BASE_URL / LLM_API_KEY")
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        req = urllib.request.Request(
            f"{base}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
            code = {429: "RATE_LIMITED", 400: "BAD_INPUT", 401: "AUTH_FAILED"}.get(e.code, "UPSTREAM_5XX")
            raise LLMError(code, f"HTTP {e.code}")
        except Exception as e:  # 网络/超时
            raise LLMError("MODEL_TIMEOUT", str(e))
        text = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        return Completion(
            text=text,
            prompt_tokens=usage.get("prompt_tokens", estimate_tokens(prompt)),
            completion_tokens=usage.get("completion_tokens", estimate_tokens(text)),
            model=self.model,
        )

    # ---------------- 带重试/超时的调用 ----------------
    def complete(self, prompt: str, temperature: float = 0.0, max_tokens: int = 512) -> Completion:
        last_err: LLMError | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                c = self._call_with_timeout(prompt, temperature, max_tokens)
                self.ledger.add(c)
                self.events.append({"attempt": attempt, "status": "ok", "latency_ms": c.latency_ms})
                return c
            except LLMError as e:
                last_err = e
                self.events.append({"attempt": attempt, "status": "error", "code": e.code})
                if e.code in ("BAD_INPUT", "AUTH_FAILED", "BAD_CONFIG"):
                    break  # 不可重试
                if attempt < self.max_attempts:
                    backoff = min(2 ** (attempt - 1), 8) + random.uniform(0, 0.3)  # 指数退避 + 抖动
                    self._sleep(backoff)
        raise last_err or LLMError("UNKNOWN", "调用失败")

    def _call_with_timeout(self, prompt: str, temperature: float, max_tokens: int) -> Completion:
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(self._raw_call, prompt, temperature, max_tokens)
            try:
                return fut.result(timeout=self.timeout_s)
            except FutureTimeout:
                raise LLMError("MODEL_TIMEOUT", f"超过 {self.timeout_s}s 未返回")

    # ---------------- 上下文预算与裁剪 ----------------
    @staticmethod
    def trim_context(
        system: str,
        messages: list[dict],
        max_prompt_tokens: int = 1200,
        keep_recent: int = 4,
    ) -> tuple[str, list[dict]]:
        """超限时保留 system + 最近 keep_recent 轮，并把被裁掉的历史压成一条摘要。"""
        total = estimate_tokens(system) + sum(estimate_tokens(m["content"]) for m in messages)
        if total <= max_prompt_tokens:
            return system, messages

        kept = messages[-keep_recent:] if keep_recent < len(messages) else messages
        dropped = messages[: len(messages) - len(kept)] if keep_recent < len(messages) else []
        summary = {"role": "system", "content": f"[历史摘要] 已省略 {len(dropped)} 轮早期对话。"}
        out = ([summary] + kept) if dropped else kept

        # 仍超限则继续从最早的非 system 消息开始删
        while estimate_tokens(system) + sum(estimate_tokens(m["content"]) for m in out) > max_prompt_tokens and len(out) > 1:
            out.pop(0)
        return system, out

    # ---------------- 结构化输出 ----------------
    def complete_json(
        self,
        prompt: str,
        required_keys: list[str],
        max_attempts_repair: int = 1,
    ) -> StructuredResult:
        attempts = 0
        repaired = False
        while True:
            c = self.complete(prompt, temperature=0.0, max_tokens=400)
            try:
                data = json.loads(c.text)
            except json.JSONDecodeError:
                data = None
            if data is not None and all(k in data for k in required_keys):
                return StructuredResult(data=data, repaired=repaired, completion=c)
            attempts += 1
            if attempts > max_attempts_repair:
                raise LLMError("SCHEMA_INVALID", f"输出不满足 schema: {required_keys}")
            repaired = True
            prompt = prompt + "\n严格只输出合法 JSON，必须包含字段：" + ",".join(required_keys)


def build_prompt(system: str, messages: list[dict]) -> str:
    parts = [sys_text(system)]
    for m in messages:
        parts.append(f"{m['role']}: {m['content']}")
    return "\n".join(parts)


def sys_text(s: str) -> str:
    return f"system: {s}"
