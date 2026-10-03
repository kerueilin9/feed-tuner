from __future__ import annotations

import pytest

from feed_trainer.models.base import Answer, ModelResult


def make_result(answers: dict[str, float]) -> ModelResult:
    """以 Noul 機率建立假的模型回應。"""
    return ModelResult(
        model="fake",
        answers={qid: Answer(qid, "noul", p, None) for qid, p in answers.items()},
        latency_ms=1.0,
    )


def make_row(overall: int | None, want: float = 0.0, avoid: float = 0.0, **extra) -> dict:
    """Policy.decide 需要的評分結果列。"""
    row = {
        "post_id": "p1",
        "author": "someone",
        "url": "https://example.com/p1",
        "overall": overall,
        "error": None,
        "is_reply": False,
        "matches": [
            {"topic": "遊戲開發", "polarity": "want", "p": want, "model_p": want, "keyword": None},
            {"topic": "業配", "polarity": "avoid", "p": avoid, "model_p": avoid, "keyword": None},
        ],
    }
    row.update(extra)
    return row


@pytest.fixture
def action_config() -> dict:
    return {
        "mode": "dry_run",
        "model": "laya",
        "actions": {
            "dwell": {"enabled": True, "min_score": 61, "seconds": [5, 10]},
            "open_post": {"enabled": True, "min_score": 75, "daily_limit": 15},
            "like": {"enabled": True, "min_score": 85, "max_avoid": 0.3, "daily_limit": 2},
            "not_interested": {"enabled": True, "max_score": 30, "min_avoid": 0.8, "max_want": 0.5, "daily_limit": 10},
        },
        "skip": {"replies": True, "insufficient": True},
    }
