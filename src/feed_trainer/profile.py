"""讀取 config/profile.yaml，分出要送給模型的問題與程式使用的設定。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# 只在本專案使用、不送給模型的欄位
LOCAL_KEYS = {"group", "effect"}


@dataclass
class Profile:
    mode: str
    version: int
    questions: dict[str, dict[str, Any]]  # 原始設定（含 group／effect）
    weights: dict[str, float]

    def model_questions(self) -> dict[str, dict[str, Any]]:
        return {qid: {k: v for k, v in q.items() if k not in LOCAL_KEYS} for qid, q in self.questions.items()}


def load_profile(path: str | Path = "config/profile.yaml") -> Profile:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Profile(
        mode=data["mode"],
        version=data["version"],
        questions=data["questions"],
        weights=data["weights"],
    )
