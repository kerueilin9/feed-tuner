"""爬取 Threads 首頁貼文 → 依 config/preferences.txt 評分 → 輸出到 results/<時間>/。

    uv run python scripts/run_feed.py                      # 爬 20 篇，用 Laya 評分
    uv run python scripts/run_feed.py --count 10 --headless
    uv run python scripts/run_feed.py --from results/20261003-150000/posts.json   # 不重爬，只重新評分

輸出：
    report.md     依分數排序的表格
    results.json  整理過的完整結果：摘要＋每篇貼文的分數與各偏好判斷（依分數排序）
    posts.json    爬到的原始貼文（供 --from 重新評分）
    run.log       本次執行的完整日誌
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from feed_trainer.log import setup_logging
from feed_trainer.models import load_model
from feed_trainer.preferences import judge, load_preferences, to_questions
from feed_trainer.threads import NotLoggedInError, Post, scrape_feed

log = logging.getLogger("run_feed")


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_posts(path: Path) -> list[Post]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":  # 舊版輸出
        return [Post(**json.loads(line)) for line in text.splitlines() if line.strip()]
    return [Post(**d) for d in json.loads(text)]


def rank_key(row: dict) -> float:
    return -1 if row["overall"] is None else row["overall"]


def pct(p: float) -> str:
    return f"{p:.0%}"


def readable(row: dict, rank: int) -> dict:
    """給人閱讀的單篇結果；原始數值放在「除錯」。"""
    if row["error"] == "no_text":
        score = "資訊不足（沒有文字）"
    elif row["error"]:
        score = "評分失敗"
    elif row["overall"] is None:
        score = "資訊不足（內容可能依賴圖片、連結或引用）"
    else:
        score = row["overall"]

    out: dict = {
        "排名": rank,
        "分數": score,
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
    if row["error"] and row["error"] != "no_text":
        out["錯誤"] = row["error"]

    out["除錯"] = {
        "post_id": row["post_id"],
        "model": row.get("model"),
        "latency_ms": row["latency_ms"],
        "answers": {qid: round(a["value"], 4) if isinstance(a["value"], float) else a["value"] for qid, a in row["answers"].items()},
    }
    return out


def md_cell(text: str, limit: int = 80) -> str:
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit] + "…"
    return text.replace("|", "\\|")


def write_report(path: Path, rows: list[dict], model_name: str, prefs) -> None:
    ranked = sorted(rows, key=rank_key, reverse=True)
    lines = [
        f"# Threads 首頁評分報告",
        "",
        f"- 時間：{datetime.now():%Y-%m-%d %H:%M}",
        f"- 模型：{model_name}",
        f"- 偏好：" + "、".join(f"{'想看' if p.polarity == 'want' else '不想看'}「{p.topic}」" for p in prefs),
        "",
        "| # | 分數 | 作者 | 內容 | 命中（🔑 關鍵字） | 標記 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for i, r in enumerate(ranked, 1):
        score = "資訊不足" if r["overall"] is None else str(r["overall"])
        hits = "、".join(
            f"{'✓' if m['polarity'] == 'want' else '✗'}{m['topic']} {m['p']:.0%}{'🔑' if m['keyword'] else ''}"
            for m in r["matches"]
            if m["p"] >= 0.5
        )
        flags = "、".join(f for f, on in [("媒體", r["has_media"]), ("Threads AI 標記", r.get("gen_ai_label"))] if on)
        lines.append(f"| {i} | {score} | [@{r['author']}]({r['url']}) | {md_cell(r['text']) or '（無文字）'} | {hits} | {flags} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--model", default="laya")
    parser.add_argument("--headless", action="store_true", help="不顯示瀏覽器視窗")
    parser.add_argument("--from", dest="from_file", type=Path, help="改從既有的 posts.json 讀取，不重新爬取")
    parser.add_argument("--verbose", action="store_true", help="終端機也顯示 DEBUG")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    run_dir = Path("results") / datetime.now().strftime("%Y%m%d-%H%M%S")
    setup_logging(run_dir / "run.log", logging.DEBUG if args.verbose else logging.INFO)
    load_dotenv()
    log.info("開始執行，結果資料夾：%s", run_dir)
    log.debug("參數：%s", vars(args))

    # 1. 取得貼文
    try:
        posts = read_posts(args.from_file) if args.from_file else scrape_feed(args.count, headless=args.headless)
    except NotLoggedInError as e:
        log.error("%s", e)
        return 1
    if args.from_file:
        log.info("從 %s 讀入 %d 篇貼文", args.from_file, len(posts))
    if not posts:
        log.error("沒有取得任何貼文")
        return 1
    write_json(run_dir / "posts.json", [p.to_dict() for p in posts])

    # 2. 評分
    prefs = load_preferences()
    questions = to_questions(prefs)
    log.info("偏好 %d 項：%s", len(prefs), "、".join(f"{p.polarity}:{p.topic}" for p in prefs))
    log.info("載入模型 %s", args.model)
    t0 = time.perf_counter()
    model = load_model(args.model)
    log.info("模型載入完成，%.1f 秒", time.perf_counter() - t0)

    rows: list[dict] = []
    latencies: list[float] = []
    errors = 0
    model_id = args.model
    for i, post in enumerate(posts, 1):
        row = post.to_dict() | {"overall": None, "matches": [], "answers": {}, "latency_ms": None, "error": None}
        if not post.text and not post.quoted_text:
            row["error"] = "no_text"
            log.info("[%d/%d] @%s 沒有文字，標記為資訊不足", i, len(posts), post.author)
            rows.append(row)
            continue
        try:
            result = model.answer(post.state(), questions)
        except Exception as e:
            errors += 1
            row["error"] = repr(e)
            log.exception("[%d/%d] @%s 評分失敗", i, len(posts), post.author)
            rows.append(row)
            continue
        model_id = result.model
        verdict = judge(prefs, result, "\n".join(filter(None, [post.text, post.quoted_text])))
        latencies.append(result.latency_ms)
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
        rows.append(row)
        score = "資訊不足" if verdict.overall is None else verdict.overall
        log.info("[%d/%d] %s 分　@%s：%s", i, len(posts), score, post.author, md_cell(post.text, 30))
        log.debug("[%d/%d] %s answers=%s latency=%.0fms", i, len(posts), post.post_id, row["answers"], result.latency_ms)

    # 3. 輸出
    write_report(run_dir / "report.md", rows, model_id, prefs)
    # 第一篇包含模型熱機時間，統計延遲時排除
    steady = latencies[1:] or latencies
    scored = [r["overall"] for r in rows if r["overall"] is not None]
    summary = {
        "執行時間": f"{datetime.now():%Y-%m-%d %H:%M}",
        "模型": model_id,
        "偏好": [f"{'想看' if p.polarity == 'want' else '不想看'}「{p.topic}」" for p in prefs],
        "貼文數": len(posts),
        "完成評分": len(scored),
        "資訊不足": sum(1 for r in rows if r["overall"] is None and not (r["error"] and r["error"] != "no_text")),
        "評分失敗": errors,
        "分數分布": {
            "61–100 推薦": sum(1 for s in scored if s > 60),
            "31–60 可能相關": sum(1 for s in scored if 30 < s <= 60),
            "0–30 可略過": sum(1 for s in scored if s <= 30),
        },
        "每篇延遲（中位數）": f"{statistics.median(steady):.0f} ms" if steady else None,
        "第一篇延遲（含模型熱機）": f"{latencies[0]:.0f} ms" if latencies else None,
    }
    ranked = sorted(rows, key=rank_key, reverse=True)
    write_json(run_dir / "results.json", {"摘要": summary, "貼文": [readable(r, i) for i, r in enumerate(ranked, 1)]})
    log.info("完成：%s", json.dumps(summary, ensure_ascii=False))
    log.info("報告：%s", run_dir / "report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
