"""階段 C：邊爬首頁邊評分，依 config/actions.yaml 決定互動動作。

    uv run python scripts/train_feed.py              # 依設定檔（預設 dry_run、100 篇）
    uv run python scripts/train_feed.py --count 30   # 臨時改篇數

dry_run：只記錄會做的動作，捲動節奏與一般瀏覽相同，不點擊、不刻意停留。
中途按 Ctrl+C 會停止並保存已處理的結果。

輸出 results/<時間>/：report.md、results.json、posts.json、actions.json、run.log
累積紀錄（不進 git）：
    data/actions.jsonl       每個動作（含 dry_run 預演）
    data/feed_history.jsonl  每次執行的首頁內容組成，用 scripts/feed_trend.py 查看
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

from feed_trainer.actions import ACTION_NAMES, ActionLog, Policy, load_action_config
from feed_trainer.log import setup_logging
from feed_trainer.pipeline import Scorer, feed_metrics, md_cell, score_label, write_json, write_outputs
from feed_trainer.threads import FeedSession, NotLoggedInError, SafetyStopError

log = logging.getLogger("train_feed")
HISTORY = Path("data/feed_history.jsonl")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, help="本次篇數（預設用設定檔的 posts_per_run）")
    parser.add_argument("--model", default="laya")
    parser.add_argument("--headless", action="store_true", help="不顯示瀏覽器視窗")
    parser.add_argument("--verbose", action="store_true", help="終端機也顯示 DEBUG")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    config = load_action_config()
    mode = config["mode"]
    count = args.count or config["posts_per_run"]
    run_dir = Path("results") / f"{datetime.now():%Y%m%d-%H%M%S}-{mode}"
    setup_logging(run_dir / "run.log", logging.DEBUG if args.verbose else logging.INFO)
    load_dotenv()

    if mode == "live":
        log.error("live 模式尚未實作：點擊需先在登入後的畫面上驗證。請將 config/actions.yaml 的 mode 設回 dry_run。")
        return 1

    log.info("開始執行（%s 模式，%d 篇），結果資料夾：%s", mode, count, run_dir)
    log.debug("設定：%s", config)
    scorer = Scorer(args.model)  # 先載入模型，避免瀏覽器開著空等
    action_log = ActionLog(mode)
    policy = Policy(config, action_log)

    rows: list[dict] = []
    posts = []
    planned: list[dict] = []
    stop_reason = "完成"
    consecutive_errors = 0
    max_errors = config["safety"]["max_consecutive_errors"]
    try:
        with FeedSession(headless=args.headless, scroll_pause=tuple(config["pacing"]["scroll_pause"])) as feed:
            for i, post in enumerate(feed.posts(count), 1):
                posts.append(post)
                row = scorer.score(post)
                consecutive_errors = consecutive_errors + 1 if row["error"] and row["error"] != "no_text" else 0
                if consecutive_errors >= max_errors:
                    stop_reason = f"連續 {consecutive_errors} 次評分失敗"
                    log.error("%s，停止執行", stop_reason)
                    rows.append(row)
                    break

                plans = policy.decide(row)
                for plan in plans:
                    action_log.record(plan, row, executed=False, run_dir=run_dir)
                    planned.append({"post_id": row["post_id"], "author": row["author"], "action": ACTION_NAMES[plan.action], "reason": plan.reason})
                row["actions"] = [ACTION_NAMES[p.action] for p in plans]
                rows.append(row)

                acts = f"　→ 預演：{'、'.join(row['actions'])}" if plans else ""
                log.info("[%d/%d] %s 分　@%s：%s%s", i, count, score_label(row), post.author, md_cell(post.text, 30), acts)
    except NotLoggedInError as e:
        log.error("%s", e)
        return 1
    except SafetyStopError as e:
        stop_reason = str(e)
        log.error("%s", e)
    except KeyboardInterrupt:
        stop_reason = "使用者中斷"
        log.warning("使用者中斷，保存已處理的 %d 篇", len(rows))

    if not rows:
        log.error("沒有處理任何貼文（%s）", stop_reason)
        return 1

    write_json(run_dir / "posts.json", [p.to_dict() for p in posts])
    write_json(run_dir / "actions.json", planned)
    action_counts = {name: sum(1 for p in planned if p["action"] == name) for name in ACTION_NAMES.values()}
    summary = write_outputs(
        run_dir,
        rows,
        scorer,
        {"模式": "預演（未實際互動）" if mode == "dry_run" else "實際互動", "結束原因": stop_reason, "動作統計": action_counts},
    )

    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as f:
        entry = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "date": date.today().isoformat(),
            "mode": mode,
            "run_dir": str(run_dir),
            "posts": len(rows),
            "stop_reason": stop_reason,
            "metrics": feed_metrics(rows),
            "actions": action_counts,
        }
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    log.info("完成：%s", json.dumps(summary, ensure_ascii=False))
    log.info("報告：%s", run_dir / "report.md")
    return 0 if stop_reason in {"完成", "使用者中斷"} else 1


if __name__ == "__main__":
    sys.exit(main())
