"""簡易偏好：使用者一行寫一句，例如「我想看遊戲內容」「不要爭議文章」。

每句偏好轉成一題 Noul，貼文分數由程式組合：
    want  = 想看項目中最高的機率（符合任一項即可；沒有想看項目時為 1）
    avoid = 不想看項目中最高的機率
    overall = 100 × want × (1 − avoid)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .models import ModelResult

Polarity = Literal["want", "avoid"]

# 較長的前綴放前面，避免「不想看」被「不想」先吃掉後留下「看」
AVOID_PREFIXES = ["我不想看到", "我不想看", "不想看到", "不想看", "我不要", "不要看", "不要", "不想", "少看", "少一點", "避免", "排除", "別給我", "別"]
WANT_PREFIXES = ["我想多看", "我想看", "想多看", "想看", "多看", "多一點", "我要看", "我要", "我喜歡", "喜歡", "給我"]
# 不含「和」「跟」：會誤刪「跟風文」這類主題
CONNECTORS = ["但是", "但", "而且", "還有"]

# 與偏好無關、固定加入的系統問題
NEEDS_CONTEXT_ID = "_needs_context"
NEEDS_CONTEXT_QUESTION = {
    "type": "noul",
    "instructions": "只讀這段文字，讀者是否無法理解貼文在說什麼（例如內容依賴圖片、影片、連結或被引用的另一篇貼文）？",
}
INSUFFICIENT_THRESHOLD = 0.5


@dataclass
class Preference:
    source: str  # 使用者原句
    topic: str  # 去掉「我想看」「不要」後的主題
    polarity: Polarity

    @property
    def question_id(self) -> str:
        return f"{self.polarity}:{self.topic}"

    def question(self) -> dict:
        return {"type": "noul", "instructions": f"這篇貼文是否屬於「{self.topic}」？"}


def _strip_prefix(text: str, prefixes: list[str]) -> str | None:
    for p in prefixes:
        if text.startswith(p):
            return text[len(p) :].strip()
    return None


def parse_line(line: str) -> list[Preference]:
    prefs: list[Preference] = []
    polarity: Polarity = "want"
    for fragment in re.split(r"[，,；;]", line):
        text = fragment.strip()
        for c in CONNECTORS:
            if text.startswith(c):
                text = text[len(c) :].strip()
                break
        if not text:
            continue
        if (topic := _strip_prefix(text, AVOID_PREFIXES)) is not None:
            polarity = "avoid"
        elif (topic := _strip_prefix(text, WANT_PREFIXES)) is not None:
            polarity = "want"
        else:
            topic = text  # 沒有前綴：沿用同一行前一段的方向
        topic = topic.removesuffix("的").strip()
        if topic:
            prefs.append(Preference(source=fragment.strip(), topic=topic, polarity=polarity))
    return prefs


def load_preferences(path: str | Path = "config/preferences.txt") -> list[Preference]:
    prefs: list[Preference] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            prefs.extend(parse_line(line))
    return prefs


def to_questions(prefs: list[Preference]) -> dict[str, dict]:
    questions = {p.question_id: p.question() for p in prefs}
    questions[NEEDS_CONTEXT_ID] = NEEDS_CONTEXT_QUESTION
    return questions


@dataclass
class Verdict:
    overall: int | None  # None 表示資訊不足
    matches: list[tuple[Preference, float]]  # (偏好, 機率)，依機率排序


def judge(prefs: list[Preference], result: ModelResult) -> Verdict:
    matches = sorted(
        ((p, float(result.answers[p.question_id].value)) for p in prefs if p.question_id in result.answers),
        key=lambda m: m[1],
        reverse=True,
    )
    needs_context = result.answers.get(NEEDS_CONTEXT_ID)
    if needs_context is not None and float(needs_context.value) >= INSUFFICIENT_THRESHOLD:
        return Verdict(overall=None, matches=matches)

    want = [prob for p, prob in matches if p.polarity == "want"]
    avoid = [prob for p, prob in matches if p.polarity == "avoid"]
    want_score = max(want) if want else 1.0
    avoid_score = max(avoid) if avoid else 0.0
    return Verdict(overall=round(100 * want_score * (1 - avoid_score)), matches=matches)
