"""決策模型的統一介面。

Jev 與 Laya 使用相同的請求／回應格式（Laya 宣稱相容 Jev wire format），
因此兩者的原始回應都由 `parse_answers` 轉成同一種 `Answer`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

QuestionType = Literal["choice", "score", "noul"]


@dataclass
class Answer:
    question_id: str
    type: QuestionType
    # choice：選中的選項；score：0..(層級數-1) 的期望值；noul：「是」的機率
    value: str | float
    # noul 沒有 confidence；choice／score 為 0..1
    confidence: float | None
    probabilities: dict[str, float] = field(default_factory=dict)


@dataclass
class ModelResult:
    model: str  # 實際回答的模型 ID，例如 jev-1.13.0、laya-multilingual
    answers: dict[str, Answer]
    latency_ms: float
    input_tokens: int | None = None
    cost_usd: float | None = None
    raw: dict[str, Any] | None = None


class DecisionModel(Protocol):
    name: str

    def answer(self, state: str | dict[str, Any], questions: dict[str, dict[str, Any]]) -> ModelResult: ...


def parse_answers(raw_answers: dict[str, Any]) -> dict[str, Answer]:
    answers: dict[str, Answer] = {}
    for qid, a in raw_answers.items():
        qtype = a["type"]
        if qtype == "choice":
            value = a["choice"]
        elif qtype == "score":
            value = float(a["score"])
        elif qtype == "noul":
            value = float(a["noul"])
        else:
            continue
        answers[qid] = Answer(
            question_id=qid,
            type=qtype,
            value=value,
            confidence=a.get("confidence"),
            probabilities={str(k): float(v) for k, v in (a.get("probabilities") or {}).items()},
        )
    return answers
