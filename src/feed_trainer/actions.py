"""階段 C：依評分結果決定互動動作，並記錄每個動作。

動作紀錄 data/actions.jsonl（累積、不進 git）同時用於：
    - 每日上限：當天、同一模式下已記錄的次數
    - 之後撤銷系統按過的讚
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from .pipeline import max_avoid

log = logging.getLogger(__name__)

ACTION_LOG = Path("data/actions.jsonl")
ACTION_NAMES = {"like": "按讚", "not_interested": "不感興趣", "open_post": "點開", "dwell": "停留"}


@dataclass
class Plan:
    action: str
    reason: str


def load_action_config(path: str | Path = "config/actions.yaml") -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if config["mode"] not in {"dry_run", "live"}:
        raise ValueError(f"mode 必須是 dry_run 或 live：{config['mode']}")
    return config


class ActionLog:
    def __init__(self, mode: str, path: Path = ACTION_LOG):
        self.mode = mode
        self.path = path
        self.today = date.today().isoformat()
        self.counts: dict[str, int] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                e = json.loads(line)
                if e["date"] == self.today and e["mode"] == mode:
                    self.counts[e["action"]] = self.counts.get(e["action"], 0) + 1
        if self.counts:
            log.info("今天（%s 模式）已記錄的動作：%s", mode, self.counts)

    def record(self, plan: Plan, row: dict, executed: bool, run_dir: Path) -> None:
        self.counts[plan.action] = self.counts.get(plan.action, 0) + 1
        entry = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "date": self.today,
            "mode": self.mode,
            "source": "system",
            "action": plan.action,
            "executed": executed,
            "post_id": row["post_id"],
            "author": row["author"],
            "url": row["url"],
            "score": row["overall"],
            "reason": plan.reason,
            "run_dir": str(run_dir),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


class Policy:
    def __init__(self, config: dict[str, Any], action_log: ActionLog):
        self.actions = config["actions"]
        self.skip = config.get("skip", {})
        self.log = action_log

    def _enabled(self, name: str) -> dict | None:
        cfg = self.actions.get(name) or {}
        return cfg if cfg.get("enabled") else None

    def _under_limit(self, name: str, cfg: dict) -> bool:
        limit = cfg.get("daily_limit")
        if limit is not None and self.log.counts.get(name, 0) >= limit:
            log.debug("%s 已達今日上限 %d", ACTION_NAMES[name], limit)
            return False
        return True

    def decide(self, row: dict) -> list[Plan]:
        score = row["overall"]
        if row["error"] or (score is None and self.skip.get("insufficient", True)):
            return []
        if row["is_reply"] and self.skip.get("replies", True):
            return []
        if score is None:
            return []
        avoid = max_avoid(row)
        plans: list[Plan] = []

        if (cfg := self._enabled("like")) and score >= cfg["min_score"] and avoid <= cfg["max_avoid"]:
            if self._under_limit("like", cfg):
                plans.append(Plan("like", f"分數 {score} ≥ {cfg['min_score']}，不想看最高 {avoid:.0%}"))
        if (cfg := self._enabled("open_post")) and score >= cfg["min_score"] and self._under_limit("open_post", cfg):
            plans.append(Plan("open_post", f"分數 {score} ≥ {cfg['min_score']}"))
        if (cfg := self._enabled("dwell")) and score >= cfg["min_score"]:
            plans.append(Plan("dwell", f"分數 {score} ≥ {cfg['min_score']}"))
        # 同時命中「想看」的貼文不標記，避免負面訊號連帶壓低想看的主題
        want = max((m["p"] for m in row["matches"] if m["polarity"] == "want"), default=0.0)
        if (
            (cfg := self._enabled("not_interested"))
            and score <= cfg["max_score"]
            and avoid >= cfg["min_avoid"]
            and want < cfg.get("max_want", 0.5)
        ):
            if self._under_limit("not_interested", cfg):
                topic = max((m for m in row["matches"] if m["polarity"] == "avoid"), key=lambda m: m["p"])["topic"]
                plans.append(Plan("not_interested", f"分數 {score}，命中不想看「{topic}」{avoid:.0%}"))
        return plans
