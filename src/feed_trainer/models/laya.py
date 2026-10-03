"""Laya：本機推論（https://github.com/NandhaKishorM/laya）。"""

from __future__ import annotations

import time
from typing import Any

from .base import ModelResult, parse_answers


class LayaModel:
    def __init__(self, checkpoint: str = "multilingual", max_len: int | None = None, device: str | None = None):
        from laya import Router

        # 中文貼文固定使用 multilingual checkpoint，避免夾雜英文時被路由到英文版
        self.checkpoint = checkpoint
        self.max_len = max_len
        self.name = f"laya-{checkpoint}"
        self._router = Router(device=device) if device else Router()

    def answer(self, state: str | dict[str, Any], questions: dict[str, dict[str, Any]]) -> ModelResult:
        kwargs: dict[str, Any] = {"model": self.checkpoint}
        if self.max_len:
            kwargs["max_len"] = self.max_len

        start = time.perf_counter()
        result = self._router.predict(state, questions, **kwargs)
        latency_ms = (time.perf_counter() - start) * 1000

        usage = result.get("usage") or {}
        routed = (result.get("routing") or {}).get("model", self.checkpoint)
        return ModelResult(
            model=f"laya-{routed}",
            answers=parse_answers(result["answers"]),
            latency_ms=latency_ms,
            input_tokens=usage.get("input_tokens"),
            cost_usd=0.0,
            raw=result,
        )
