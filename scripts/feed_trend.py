"""列出每次 train_feed.py 執行時的首頁內容組成，比較基準期與互動期。

    uv run python scripts/feed_trend.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HISTORY = Path("data/feed_history.jsonl")


def fmt(v: float | None) -> str:
    return "  -  " if v is None else f"{v:5.0%}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if not HISTORY.exists():
        print("還沒有紀錄，先執行：uv run python scripts/train_feed.py")
        return 1
    entries = [json.loads(line) for line in HISTORY.read_text(encoding="utf-8").splitlines() if line.strip()]
    topics = sorted({t for e in entries for t in e["metrics"]["topic_share"]})

    header = f"{'時間':<17} {'模式':<8} {'篇數':>4} {'推薦':>6} {'可略過':>6} {'平均':>5} " + " ".join(f"{t:>8}" for t in topics) + "  動作"
    print(header)
    print("-" * len(header.encode("utf-8")))
    for e in entries:
        m = e["metrics"]
        acts = "、".join(f"{k}{v}" for k, v in e["actions"].items() if v)
        print(
            f"{e['time'][:16]:<17} {e['mode']:<8} {e['posts']:>4} {fmt(m['recommended_share']):>6} {fmt(m['skip_share']):>6} "
            f"{m['mean_score'] if m['mean_score'] is not None else '-':>5} "
            + " ".join(f"{fmt(m['topic_share'].get(t)):>8}" for t in topics)
            + f"  {acts}"
        )
    print("\n推薦＝61 分以上；可略過＝30 分以下；主題欄＝該偏好機率 ≥ 50% 的貼文比例。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
