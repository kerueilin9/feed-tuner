"""爬取 Threads 首頁貼文 → 依 config/preferences.txt 評分 → 輸出到 results/<時間>/。

    uv run python scripts/run_feed.py                      # 爬 20 篇，用 Laya 評分
    uv run python scripts/run_feed.py --count 10 --headless
    uv run python scripts/run_feed.py --from results/20261003-150000/posts.jsonl   # 不重爬，只重新評分

輸出：
    posts.jsonl   爬到的原始貼文
    scores.jsonl  每篇的模型回答與分數
    report.md     依分數排序的報告
    summary.json  數量、延遲等統計
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


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def read_posts(path: Path) -> list[Post]:
    return [Post(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def md_cell(text: str, limit: int = 80) -> str:
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit] + "…"
    return text.replace("|", "\\|")


def write_report(path: Path, rows: list[dict], model_name: str, prefs) -> None:
    ranked = sorted(rows, key=lambda r: -1 if r["overall"] is None else r["overall"], reverse=True)
    lines = [
        f"# Threads 首頁評分報告",
        "",
        f"- 時間：{datetime.now():%Y-%m-%d %H:%M}",
        f"- 模型：{model_name}",
        f"- 偏好：" + "、".join(f"{'想看' if p.polarity == 'want' else '不想看'}「{p.topic}」" for p in prefs),
        "",
        "| # | 分數 | 作者 | 內容 | 命中 | 媒體 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for i, r in enumerate(ranked, 1):
        score = "資訊不足" if r["overall"] is None else str(r["overall"])
        hits = "、".join(
            f"{'✓' if m['polarity'] == 'want' else '✗'}{m['topic']} {m['p']:.0%}" for m in r["matches"] if m["p"] >= 0.5
        )
        media = "有" if r["has_media"] else ""
        lines.append(f"| {i} | {score} | [@{r['author']}]({r['url']}) | {md_cell(r['text']) or '（無文字）'} | {hits} | {media} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--model", default="laya")
    parser.add_argument("--headless", action="store_true", help="不顯示瀏覽器視窗")
    parser.add_argument("--from", dest="from_file", type=Path, help="改從既有的 posts.jsonl 讀取，不重新爬取")
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
    write_jsonl(run_dir / "posts.jsonl", [p.to_dict() for p in posts])

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
        verdict = judge(prefs, result)
        latencies.append(result.latency_ms)
        row |= {
            "overall": verdict.overall,
            "matches": [{"topic": p.topic, "polarity": p.polarity, "p": round(prob, 4)} for p, prob in verdict.matches],
            "answers": {qid: {"value": a.value, "confidence": a.confidence} for qid, a in result.answers.items()},
            "latency_ms": round(result.latency_ms, 1),
            "model": result.model,
        }
        rows.append(row)
        score = "資訊不足" if verdict.overall is None else verdict.overall
        log.info("[%d/%d] %s 分　@%s：%s", i, len(posts), score, post.author, md_cell(post.text, 30))
        log.debug("[%d/%d] %s answers=%s latency=%.0fms", i, len(posts), post.post_id, row["answers"], result.latency_ms)

    # 3. 輸出
    write_jsonl(run_dir / "scores.jsonl", rows)
    write_report(run_dir / "report.md", rows, model_id, prefs)
    # 第一篇包含模型熱機時間，統計延遲時排除
    steady = latencies[1:] or latencies
    summary = {
        "run_dir": str(run_dir),
        "model": model_id,
        "posts": len(posts),
        "scored": len(latencies),
        "insufficient": sum(1 for r in rows if r["overall"] is None),
        "errors": errors,
        "latency_ms_p50": round(statistics.median(steady), 1) if steady else None,
        "latency_ms_max": round(max(steady), 1) if steady else None,
        "first_call_ms": round(latencies[0], 1) if latencies else None,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("完成：%s", summary)
    log.info("報告：%s", run_dir / "report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
