"""日誌：終端機顯示 INFO，檔案記錄 DEBUG。

- logs/feed_trainer.log：所有執行累積（輪替，5MB × 5 份），即時監看：
      Get-Content logs\\feed_trainer.log -Wait -Tail 50
- 每次執行另外寫一份到該次結果資料夾的 run.log
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path("logs")
FORMAT = "%(asctime)s %(levelname)-5s %(name)s | %(message)s"
NOISY = ["httpx", "httpcore", "urllib3", "huggingface_hub", "transformers", "filelock", "asyncio"]


def setup_logging(run_log: Path | None = None, console_level: int = logging.INFO) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    formatter = logging.Formatter(FORMAT, datefmt="%Y-%m-%d %H:%M:%S")

    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(console_level)
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s | %(message)s", datefmt="%H:%M:%S"))
    root.addHandler(console)

    shared = RotatingFileHandler(LOG_DIR / "feed_trainer.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    shared.setLevel(logging.DEBUG)
    shared.setFormatter(formatter)
    root.addHandler(shared)

    if run_log is not None:
        run_log.parent.mkdir(parents=True, exist_ok=True)
        per_run = logging.FileHandler(run_log, encoding="utf-8")
        per_run.setLevel(logging.DEBUG)
        per_run.setFormatter(formatter)
        root.addHandler(per_run)

    for name in NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)
