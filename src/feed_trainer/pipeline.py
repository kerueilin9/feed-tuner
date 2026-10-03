"""評分與輸出：run_feed.py（只評分）與 train_feed.py（邊爬邊互動）共用。"""

from __future__ import annotations

import json
import logging
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import load_model
from .preferences import Preference, judge, load_preferences, to_questions
from .threads import Post

log = logging.getLogger(__name__)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_posts(path: Path) -> list[Post]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":  # 舊版輸出
        return [Post(**json.loads(line)) for line in text.splitlines() if line.strip()]
    return [Post(**d) for d in json.loads(text)]


def md_cell(text: str, limit: int = 80) -> str:
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit] + "…"
    return text.replace("|", "\\|")


def pct(p: float) -> str:
    return f"{p:.0%}"


def polarity_label(p: Preference) -> str:
    return f"{'想看' if p.polarity == 'want' else '不想看'}「{p.topic}」"


def max_avoid(row: dict) -> float:
    return max((m["p"] for m in row["matches"] if m["polarity"] == "avoid"), default=0.0)


def rank_key(row: dict) -> float:
    return -1 if row["overall"] is None else row["overall"]


class Scorer:
    """載入偏好與模型，對單篇貼文評分並累積統計。"""

    def __init__(self, model_name: str = "laya"):
        self.prefs = load_preferences()
        self.questions = to_questions(self.prefs)
        log.info("偏好 %d 項：%s", len(self.prefs), "、".join(polarity_label(p) for p in self.prefs))
        log.info("載入模型 %s", model_name)
        t0 = time.perf_counter()
        self.model = load_model(model_name)
        log.info("模型載入完成，%.1f 秒", time.perf_counter() - t0)
        self.model_id = model_name
        self.latencies: list[float] = []
        self.errors = 0

    def score(self, post: Post) -> dict:
        row = post.to_dict() | {"overall": None, "matches": [], "answers": {}, "latency_ms": None, "error": None}
        if not post.text and not post.quoted_text:
            row["error"] = "no_text"
            return row
        try:
            result = self.model.answer(post.state(), self.questions)
        except Exception as e:
            self.errors += 1
            row["error"] = repr(e)
            log.exception("@%s %s 評分失敗", post.author, post.post_id)
            return row
        self.model_id = result.model
        self.latencies.append(result.latency_ms)
        verdict = judge(self.prefs, result, "\n".join(filter(None, [post.text, post.quoted_text])))
        row |= {
            "overall": verdict.overall,
            "matches": [
                {
                    "topic": m.preference.topic,
                    "polarity": m.preference.polarity,
                    "p": round(m.probability, 4),
                    "model_p": round(m.model_probability, 4),
                    "keyword": m.keyword,
                }
                for m in verdict.matches
            ],
            "answers": {qid: {"value": a.value, "confidence": a.confidence} for qid, a in result.answers.items()},
            "latency_ms": round(result.latency_ms, 1),
            "model": result.model,
        }
        log.debug("%s answers=%s latency=%.0fms", post.post_id, row["answers"], result.latency_ms)
        return row


def score_label(row: dict) -> str:
    if row["error"] == "no_text":
        return "資訊不足（沒有文字）"
    if row["error"]:
        return "評分失敗"
    if row["overall"] is None:
        return "資訊不足（內容可能依賴圖片、連結或引用）"
    return str(row["overall"])


def readable(row: dict, rank: int) -> dict:
    """給人閱讀的單篇結果；原始數值放在「除錯」。"""
    out: dict = {
        "排名": rank,
        "分數": row["overall"] if row["overall"] is not None and not row["error"] else score_label(row),
        "作者": f"@{row['author']}",
        "發文時間": datetime.fromtimestamp(row["taken_at"]).strftime("%Y-%m-%d %H:%M") if row["taken_at"] else None,
        "內容": row["text"] or "（無文字）",
    }
    if row["quoted_text"]:
        out["引用貼文"] = row["quoted_text"]
    out["連結"] = row["url"]
    out["互動"] = f"讚 {row['like_count'] or 0}・回覆 {row['reply_count'] or 0}"
    flags = [
        name
        for name, on in [
            ("有圖片或影片", row["has_media"]),
            ("有連結", row["has_link"]),
            ("回覆貼文", row["is_reply"]),
            ("Threads 標示付費合作", row["is_paid_partnership"]),
            ("Threads AI 標記", row.get("gen_ai_label")),
        ]
        if on
    ]
    if flags:
        out["標記"] = flags

    judgments = {}
    for m in row["matches"]:
        label = f"{'想看' if m['polarity'] == 'want' else '不想看'}「{m['topic']}」"
        value = pct(m["p"]) + ("　符合" if m["p"] >= 0.5 else "")
        if m["keyword"]:
            value += f"（關鍵字「{m['keyword']}」，模型 {pct(m['model_p'])}）"
        judgments[label] = value
    if judgments:
        out["偏好判斷"] = judgments
    if "actions" in row:
        out["動作"] = row["actions"] or ["無"]
    if row["error"] and row["error"] != "no_text":
        out["錯誤"] = row["error"]

    out["除錯"] = {
        "post_id": row["post_id"],
        "model": row.get("model"),
        "latency_ms": row["latency_ms"],
        "answers": {qid: round(a["value"], 4) if isinstance(a["value"], float) else a["value"] for qid, a in row["answers"].items()},
    }
    return out


def write_report(path: Path, rows: list[dict], model_name: str, prefs: list[Preference]) -> None:
    ranked = sorted(rows, key=rank_key, reverse=True)
    with_actions = any("actions" in r for r in rows)
    lines = [
        "# Threads 首頁評分報告",
        "",
        f"- 時間：{datetime.now():%Y-%m-%d %H:%M}",
        f"- 模型：{model_name}",
        "- 偏好：" + "、".join(polarity_label(p) for p in prefs),
        "",
        "| # | 分數 | 作者 | 內容 | 命中（🔑 關鍵字） | 標記 |" + (" 動作 |" if with_actions else ""),
        "| --- | --- | --- | --- | --- | --- |" + (" --- |" if with_actions else ""),
    ]
    for i, r in enumerate(ranked, 1):
        score = "資訊不足" if r["overall"] is None else str(r["overall"])
        hits = "、".join(
            f"{'✓' if m['polarity'] == 'want' else '✗'}{m['topic']} {m['p']:.0%}{'🔑' if m['keyword'] else ''}"
            for m in r["matches"]
            if m["p"] >= 0.5
        )
        flags = "、".join(f for f, on in [("媒體", r["has_media"]), ("Threads AI 標記", r.get("gen_ai_label"))] if on)
        line = f"| {i} | {score} | [@{r['author']}]({r['url']}) | {md_cell(r['text']) or '（無文字）'} | {hits} | {flags} |"
        if with_actions:
            line += f" {'、'.join(r.get('actions') or [])} |"
        lines.append(line)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def feed_metrics(rows: list[dict]) -> dict:
    """首頁內容組成：用來比較基準期與互動期的變化。"""
    scored = [r for r in rows if r["overall"] is not None]
    n = len(scored)

    def share(pred) -> float | None:
        return round(sum(1 for r in scored if pred(r)) / n, 4) if n else None

    def topic_share(topic: str) -> float | None:
        return share(lambda r: any(m["topic"] == topic and m["p"] >= 0.5 for m in r["matches"]))

    topics = {m["topic"] for r in scored for m in r["matches"]}
    return {
        "scored": n,
        "recommended_share": share(lambda r: r["overall"] > 60),
        "skip_share": share(lambda r: r["overall"] <= 30),
        "mean_score": round(statistics.mean(r["overall"] for r in scored), 1) if n else None,
        "topic_share": {t: topic_share(t) for t in sorted(topics)},
    }


def build_summary(scorer: Scorer, rows: list[dict]) -> dict:
    # 第一篇包含模型熱機時間，統計延遲時排除
    steady = scorer.latencies[1:] or scorer.latencies
    scored = [r["overall"] for r in rows if r["overall"] is not None]
    metrics = feed_metrics(rows)
    return {
        "執行時間": f"{datetime.now():%Y-%m-%d %H:%M}",
        "模型": scorer.model_id,
        "偏好": [polarity_label(p) for p in scorer.prefs],
        "貼文數": len(rows),
        "完成評分": len(scored),
        "資訊不足": sum(1 for r in rows if r["overall"] is None and not (r["error"] and r["error"] != "no_text")),
        "評分失敗": scorer.errors,
        "分數分布": {
            "61–100 推薦": sum(1 for s in scored if s > 60),
            "31–60 可能相關": sum(1 for s in scored if 30 < s <= 60),
            "0–30 可略過": sum(1 for s in scored if s <= 30),
        },
        "各偏好命中比例": {t: (pct(v) if v is not None else None) for t, v in metrics["topic_share"].items()},
        "每篇延遲（中位數）": f"{statistics.median(steady):.0f} ms" if steady else None,
        "第一篇延遲（含模型熱機）": f"{scorer.latencies[0]:.0f} ms" if scorer.latencies else None,
    }


def write_outputs(run_dir: Path, rows: list[dict], scorer: Scorer, extra_summary: dict | None = None) -> dict:
    write_report(run_dir / "report.md", rows, scorer.model_id, scorer.prefs)
    summary = build_summary(scorer, rows) | (extra_summary or {})
    ranked = sorted(rows, key=rank_key, reverse=True)
    write_json(run_dir / "results.json", {"摘要": summary, "貼文": [readable(r, i) for i, r in enumerate(ranked, 1)]})
    return summary
