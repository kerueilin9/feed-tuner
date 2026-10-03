from __future__ import annotations

import json

import pytest
from conftest import make_row

from feed_trainer.actions import ActionLog, Plan, Policy, load_action_config


@pytest.fixture
def policy(action_config, tmp_path):
    return Policy(action_config, ActionLog("dry_run", tmp_path / "actions.jsonl"))


def actions(plans):
    return sorted(p.action for p in plans)


def test_high_score_gets_like_open_dwell(policy):
    assert actions(policy.decide(make_row(90, want=0.9, avoid=0.1))) == ["dwell", "like", "open_post"]


def test_no_like_when_avoid_too_high(policy):
    assert actions(policy.decide(make_row(90, want=0.95, avoid=0.4))) == ["dwell", "open_post"]


def test_mid_score_only_dwell(policy):
    assert actions(policy.decide(make_row(65, want=0.7))) == ["dwell"]


def test_low_score_not_interested(policy):
    assert actions(policy.decide(make_row(5, want=0.1, avoid=0.9))) == ["not_interested"]


def test_not_interested_blocked_when_want_matches(policy):
    # 例如「AI 加遊戲開發」：不能給負面訊號，以免壓低遊戲開發
    assert policy.decide(make_row(9, want=0.9, avoid=0.9)) == []


@pytest.mark.parametrize("row", [make_row(None, want=0.9), make_row(90, want=0.9, is_reply=True), make_row(90, error="boom")])
def test_skipped_rows(policy, row):
    assert policy.decide(row) == []


def test_daily_limit_counts_records(policy, tmp_path):
    for _ in range(2):  # like 上限 2
        for plan in policy.decide(make_row(90, want=0.9)):
            policy.log.record(plan, make_row(90, want=0.9), executed=False, run_dir=tmp_path)
    assert "like" not in actions(policy.decide(make_row(90, want=0.9)))


def test_action_log_reloads_today_counts_per_mode(tmp_path):
    path = tmp_path / "actions.jsonl"
    log = ActionLog("dry_run", path)
    log.record(Plan("like", "r"), make_row(90), executed=False, run_dir=tmp_path)
    assert ActionLog("dry_run", path).counts == {"like": 1}
    assert ActionLog("live", path).counts == {}  # 預演不佔實際互動的額度
    entry = json.loads(path.read_text(encoding="utf-8"))
    assert entry["source"] == "system" and entry["executed"] is False


def test_load_action_config_validates(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text("mode: dry_run\nmodel: gpt\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_action_config(path)
    path.write_text("mode: dry_run\n", encoding="utf-8")
    assert load_action_config(path)["model"] == "laya"


def test_repo_config_is_valid():
    config = load_action_config("config/actions.yaml")
    assert config["mode"] == "dry_run"  # live 尚未實作，不應提交 live 設定
