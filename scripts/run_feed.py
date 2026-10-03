"""爬取 Threads 首頁貼文 → 依 config/preferences.txt 評分 → 輸出到 results/<時間>/。只讀，不互動。

    uv run python scripts/run_feed.py                      # 爬 20 篇，用設定檔的模型評分
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
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from feed_trainer.actions import load_action_config
from feed_trainer.log import setup_logging
from feed_trainer.pipeline import Scorer, md_cell, read_posts, score_label, write_json, write_outputs
from feed_trainer.threads import NotLoggedInError, SafetyStopError, scrape_feed

log = logging.getLogger("run_feed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--model", help="laya 或 jev（預設用 config/actions.yaml 的 model）")
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

    try:
        posts = read_posts(args.from_file) if args.from_file else scrape_feed(args.count, headless=args.headless)
    except (NotLoggedInError, SafetyStopError) as e:
        log.error("%s", e)
        return 1
    if args.from_file:
        log.info("從 %s 讀入 %d 篇貼文", args.from_file, len(posts))
    if not posts:
        log.error("沒有取得任何貼文")
        return 1
    write_json(run_dir / "posts.json", [p.to_dict() for p in posts])

    scorer = Scorer(args.model or load_action_config()["model"])
    rows = []
    for i, post in enumerate(posts, 1):
        row = scorer.score(post)
        rows.append(row)
        log.info("[%d/%d] %s 分　@%s：%s", i, len(posts), score_label(row), post.author, md_cell(post.text, 30))

    summary = write_outputs(run_dir, rows, scorer)
    log.info("完成：%s", json.dumps(summary, ensure_ascii=False))
    log.info("報告：%s", run_dir / "report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
