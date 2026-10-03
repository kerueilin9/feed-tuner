"""Jev：TypeSafe 託管 API（https://docs.typesafe.ai）。

API key 由環境變數 TYPESAFE_API_KEY 提供；模型版本由 TYPESAFE_DEFAULT_MODEL 釘選。
"""

from __future__ import annotations

import time
from typing import Any

from .base import ModelResult, parse_answers

# jev-1.13：輸入每百萬 token $0.042，輸出免費（docs.typesafe.ai/models，2026-10-03）
USD_PER_INPUT_TOKEN = 0.042 / 1_000_000


class JevModel:
    def __init__(self, model: str | None = None):
        from typesafe_sdk import TypeSafeClient

        self._client = TypeSafeClient(model=model) if model else TypeSafeClient()
        self.name = model or "jev"

    def answer(self, state: str | dict[str, Any], questions: dict[str, dict[str, Any]]) -> ModelResult:
        start = time.perf_counter()
        response = self._client.system_one(state=state, questions=questions)
        latency_ms = (time.perf_counter() - start) * 1000

        raw = response.raw_http_response.json()
        input_tokens = (raw.get("usage") or {}).get("input_tokens")
        return ModelResult(
            model=raw.get("model", self.name),
            answers=parse_answers(raw["answers"]),
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            cost_usd=input_tokens * USD_PER_INPUT_TOKEN if input_tokens is not None else None,
            raw=raw,
        )
