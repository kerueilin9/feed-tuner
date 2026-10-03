from __future__ import annotations

import pytest
from conftest import make_result

from feed_trainer.preferences import NEEDS_CONTEXT_ID, Preference, judge, parse_line, to_questions


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("我想看遊戲開發", [("want", "遊戲開發")]),
        ("不要爭議文章", [("avoid", "爭議文章")]),
        ("少看業配的", [("avoid", "業配")]),
        ("跟風文", [("want", "跟風文")]),  # 「跟」不能被當成連接詞刪掉
        ("不想看政治，八卦", [("avoid", "政治"), ("avoid", "八卦")]),  # 沒有前綴時沿用前一段方向
        ("我想看 Godot 教學，但不要初學者入門", [("want", "Godot 教學"), ("avoid", "初學者入門")]),
    ],
)
def test_parse_line(line, expected):
    assert [(p.polarity, p.topic) for p in parse_line(line)] == expected


def test_parse_line_keywords_apply_to_line():
    (p,) = parse_line("我想看遊戲開發（關鍵字：Godot、Unity, RPG Maker）")
    assert p.topic == "遊戲開發"
    assert p.keywords == ["Godot", "Unity", "RPG Maker"]


@pytest.mark.parametrize(
    ("text", "hit"),
    [
        ("Unity 教學", "Unity"),
        ("用unity做的", "Unity"),  # 中英混寫
        ("our community is great", None),  # 英文要完整單字
        ("rpg maker mz", "RPG Maker"),
        ("獨立遊戲開發日誌", "獨立遊戲"),
        ("LLMs are", None),
    ],
)
def test_keyword_hit(text, hit):
    p = Preference("", "t", "want", ["Unity", "RPG Maker", "獨立遊戲", "LLM"])
    assert p.keyword_hit(text) == hit


def test_to_questions_adds_needs_context():
    prefs = parse_line("我想看遊戲開發")
    questions = to_questions(prefs)
    assert set(questions) == {"want:遊戲開發", NEEDS_CONTEXT_ID}
    assert questions["want:遊戲開發"]["type"] == "noul"


def _prefs():
    return parse_line("我想看遊戲開發（關鍵字：Godot）") + parse_line("不要業配")


def test_judge_combines_want_and_avoid():
    verdict = judge(_prefs(), make_result({"want:遊戲開發": 0.8, "avoid:業配": 0.5, NEEDS_CONTEXT_ID: 0.1}), "text")
    assert verdict.overall == 40  # 100 × 0.8 × (1 − 0.5)


def test_judge_keyword_raises_probability():
    verdict = judge(_prefs(), make_result({"want:遊戲開發": 0.1, "avoid:業配": 0.0, NEEDS_CONTEXT_ID: 0.0}), "Godot 教學")
    match = next(m for m in verdict.matches if m.preference.topic == "遊戲開發")
    assert match.keyword == "Godot"
    assert match.probability == pytest.approx(0.9)
    assert match.model_probability == pytest.approx(0.1)
    assert verdict.overall == 90


def test_judge_insufficient():
    verdict = judge(_prefs(), make_result({"want:遊戲開發": 0.9, "avoid:業配": 0.0, NEEDS_CONTEXT_ID: 0.7}), "看圖")
    assert verdict.overall is None


def test_judge_without_want_items_uses_one():
    prefs = parse_line("不要業配")
    verdict = judge(prefs, make_result({"avoid:業配": 0.25, NEEDS_CONTEXT_ID: 0.0}), "text")
    assert verdict.overall == 75
