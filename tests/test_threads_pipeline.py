from __future__ import annotations

import json
from pathlib import Path

from feed_trainer.pipeline import feed_metrics, prefs_fingerprint, read_posts, readable
from feed_trainer.preferences import parse_line
from feed_trainer.threads import _parse_json, find_posts

SAMPLE = Path("data/samples/synthetic_posts.json")


def raw_post(code: str, text: str, **extra) -> dict:
    return {
        "code": code,
        "caption": {"text": text},
        "user": {"username": f"user_{code}"},
        "media_type": 19,
        "taken_at": 1790000000,
        "text_post_app_info": {"is_reply": False, "direct_reply_count": 3, "share_info": {}},
        **extra,
    }


def test_find_posts_walks_nested_and_skips_quoted():
    quoted = raw_post("Q1", "被引用的貼文")
    outer = raw_post("A1", "引用一下")
    outer["text_post_app_info"]["share_info"] = {"quoted_post": quoted}
    data = {"data": {"edges": [{"node": {"thread_items": [{"post": outer}]}}, {"node": {"thread_items": [{"post": raw_post("B2", "第二篇", media_type=1)}]}}]}}

    posts = find_posts(data)
    assert [p.post_id for p in posts] == ["A1", "B2"]  # Q1 不算動態中的貼文
    a, b = posts
    assert a.quoted_text == "被引用的貼文"
    assert a.state() == {"post": "引用一下", "quoted_post": "被引用的貼文"}
    assert a.url == "https://www.threads.com/@user_A1/post/A1"
    assert not a.has_media and b.has_media


def test_parse_json_strips_prefix():
    assert _parse_json('for (;;);{"a": 1}') == {"a": 1}
    assert _parse_json("not json") is None


def test_sample_posts_load():
    posts = read_posts(SAMPLE)
    assert len(posts) == 30
    assert len({p.post_id for p in posts}) == 30


def test_read_posts_accepts_legacy_jsonl(tmp_path):
    posts = read_posts(SAMPLE)[:2]
    path = tmp_path / "posts.jsonl"
    path.write_text("".join(json.dumps(p.to_dict(), ensure_ascii=False) + "\n" for p in posts), encoding="utf-8")
    assert read_posts(path) == posts


def test_prefs_fingerprint_detects_changes():
    a = parse_line("我想看遊戲開發（關鍵字：Godot、Unity）")
    same = parse_line("我想看遊戲開發（關鍵字：Unity、Godot）")  # 關鍵字順序不影響
    changed = parse_line("我想看遊戲開發（關鍵字：Godot）")
    assert prefs_fingerprint(a) == prefs_fingerprint(same)
    assert prefs_fingerprint(a) != prefs_fingerprint(changed)


def _row(overall, gamedev_p, **extra):
    post = read_posts(SAMPLE)[0].to_dict()
    return post | {
        "overall": overall,
        "error": None,
        "latency_ms": 1.0,
        "answers": {"want:遊戲開發": {"value": gamedev_p, "confidence": None}},
        "matches": [{"topic": "遊戲開發", "polarity": "want", "p": gamedev_p, "model_p": gamedev_p, "keyword": None}],
        **extra,
    }


def test_feed_metrics():
    rows = [_row(90, 0.9), _row(50, 0.6), _row(10, 0.1), _row(None, 0.0)]
    m = feed_metrics(rows)
    assert m["scored"] == 3  # 資訊不足不列入
    assert m["recommended_share"] == round(1 / 3, 4)
    assert m["skip_share"] == round(1 / 3, 4)
    assert m["topic_share"]["遊戲開發"] == round(2 / 3, 4)


def test_readable_formats_row():
    out = readable(_row(90, 0.9, actions=["按讚"]), rank=1)
    assert out["分數"] == 90
    assert out["偏好判斷"]["想看「遊戲開發」"].startswith("90%")
    assert out["動作"] == ["按讚"]
    assert readable(_row(None, 0.0, error="no_text"), rank=2)["分數"] == "資訊不足（沒有文字）"
