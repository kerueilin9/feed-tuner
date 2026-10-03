"""操作介面（NiceGUI）。

    uv run python scripts/ui.py      # 自動開啟 http://localhost:8080

分頁：執行／結果／趨勢／設定／試玩。執行類工作以子程序呼叫既有腳本，日誌即時顯示在頁面上。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections import Counter
from datetime import date
from pathlib import Path

from nicegui import run, ui
from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)  # 各腳本與設定檔都使用相對路徑

from feed_trainer.actions import ACTION_LOG, load_action_config  # noqa: E402
from feed_trainer.preferences import parse_line  # noqa: E402
from feed_trainer.threads import LOGIN_MARKER  # noqa: E402

PREFS_FILE = Path("config/preferences.txt")
ACTIONS_FILE = Path("config/actions.yaml")
HISTORY_FILE = Path("data/feed_history.jsonl")
STOP_FILE = Path("data/stop.flag")
SAMPLE_POSTS = Path("data/samples/synthetic_posts.json")
NOISE = ("Fetching", "HF_TOKEN", "unauthenticated requests")

yaml = YAML()  # round-trip：保留設定檔中的註解


# ───────────────────────── 背景工作 ─────────────────────────


class Job:
    """同一時間只執行一個腳本（登入、爬取都會開同一個瀏覽器資料夾）。"""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.name = ""
        self.lines: list[str] = []
        self.finished: list[str] = []  # 已結束工作的名稱，供頁面顯示通知
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self.proc is not None

    def start(self, name: str, script: str, *args: str) -> None:
        if self.running:
            ui.notify(f"「{self.name}」執行中，請先等它結束或停止", type="warning")
            return
        self.name = name
        self._emit(f"──── 開始：{name} ────")
        env = os.environ | {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        self.proc = subprocess.Popen(
            [sys.executable, "-u", script, *args],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        proc = self.proc
        assert proc is not None and proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line and not any(n in line for n in NOISE):
                self._emit(line)
        code = proc.wait()
        self._emit(f"──── 結束：{self.name}（{'成功' if code == 0 else f'代碼 {code}'}）────")
        with self._lock:
            self.finished.append(self.name)
        self.proc = None

    def _emit(self, line: str) -> None:
        with self._lock:
            self.lines.append(line)

    def stop(self) -> None:
        if not self.running:
            return
        if self.name.startswith("訓練"):
            STOP_FILE.parent.mkdir(exist_ok=True)
            STOP_FILE.touch()  # train_feed 會在處理完當前貼文後保存並結束
            self._emit("已送出停止要求，處理完目前這篇後會保存結果並結束……")
        else:
            self.proc.terminate()
            self._emit("已終止")


job = Job()


# ───────────────────────── 資料讀取 ─────────────────────────


def run_dirs() -> list[Path]:
    return sorted((d for d in Path("results").glob("*") if (d / "results.json").exists()), reverse=True)


def load_history() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    return [json.loads(line) for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]


def today_action_counts() -> Counter:
    counts: Counter = Counter()
    if ACTION_LOG.exists():
        today = date.today().isoformat()
        for line in ACTION_LOG.read_text(encoding="utf-8").splitlines():
            if line.strip():
                e = json.loads(line)
                if e["date"] == today:
                    counts[(e["mode"], e["action"])] += 1
    return counts


# ───────────────────────── 分頁 ─────────────────────────


def run_tab(on_finished) -> None:
    config = load_action_config()
    with ui.row().classes("w-full items-start gap-4"):
        with ui.card().classes("w-80"):
            ui.label("Threads 登入").classes("text-lg font-medium")
            login_status = ui.label()
            ui.label("在開啟的 Chrome 視窗中手動登入，程式不經手帳號密碼。").classes("text-sm text-gray-500")
            login_btn = ui.button("登入 Threads", icon="login", on_click=lambda: job.start("登入", "scripts/login.py"))

        with ui.card().classes("w-96"):
            ui.label("每日訓練").classes("text-lg font-medium")
            mode_text = "預演（只記錄，不互動）" if config["mode"] == "dry_run" else "實際互動"
            ui.label(f"模式：{mode_text}").classes("text-sm")
            count = ui.number("篇數", value=config["posts_per_run"], min=1, max=300, step=10).classes("w-32")
            headless = ui.switch("不顯示瀏覽器視窗")

            def start_train() -> None:
                args = ["--count", str(int(count.value))] + (["--headless"] if headless.value else [])
                job.start("訓練", "scripts/train_feed.py", *args)

            train_btn = ui.button("開始", icon="play_arrow", on_click=start_train)

        with ui.card().classes("w-80"):
            ui.label("測試貼文").classes("text-lg font-medium")
            ui.label("用 30 篇自編貼文跑一次評分，不需登入。").classes("text-sm text-gray-500")
            sample_btn = ui.button(
                "評分測試貼文",
                icon="science",
                on_click=lambda: job.start("評分測試貼文", "scripts/run_feed.py", "--from", str(SAMPLE_POSTS)),
            )

        with ui.card().classes("w-72"):
            ui.label("今日動作").classes("text-lg font-medium")
            counts_box = ui.column().classes("gap-0")

    with ui.row().classes("w-full items-center"):
        status = ui.label()
        stop_btn = ui.button("停止", icon="stop", color="red", on_click=job.stop)
        ui.button("清除畫面", icon="clear_all", on_click=lambda: log_view.clear()).props("flat")
    log_view = ui.log(max_lines=2000).classes("w-full h-96 font-mono text-xs")
    for line in job.lines[-300:]:
        log_view.push(line)
    seen = {"lines": len(job.lines), "finished": len(job.finished)}

    def refresh_counts() -> None:
        counts = today_action_counts()
        counts_box.clear()
        limits = {name: (cfg or {}).get("daily_limit") for name, cfg in config["actions"].items()}
        with counts_box:
            for key, label in [("like", "按讚"), ("not_interested", "不感興趣"), ("open_post", "點開"), ("dwell", "停留")]:
                planned, done = counts[("dry_run", key)], counts[("live", key)]
                limit = f" / {limits.get(key)}" if limits.get(key) else ""
                ui.label(f"{label}：預演 {planned}，實際 {done}{limit}").classes("text-sm")

    def refresh_login() -> None:
        # 登入、訓練（偵測到被登出時會刪除標記）都會改變狀態，每次更新都重新讀取
        if LOGIN_MARKER.exists():
            text, color = f"已登入（{LOGIN_MARKER.read_text(encoding='utf-8').strip()}）", "text-green-700"
        else:
            text, color = "尚未登入", "text-orange-700"
        if login_status.text != text:
            login_status.text = text
            login_status.classes(replace=color)

    def tick() -> None:
        new = job.lines[seen["lines"] :]
        seen["lines"] = len(job.lines)
        for line in new:
            log_view.push(line)
        refresh_login()
        busy = job.running
        status.text = f"執行中：{job.name}" if busy else "閒置"
        for b in (login_btn, train_btn, sample_btn):
            b.set_enabled(not busy)
        stop_btn.set_enabled(busy)
        if len(job.finished) > seen["finished"]:
            seen["finished"] = len(job.finished)
            ui.notify(f"「{job.finished[-1]}」已結束", type="positive")
            refresh_counts()
            on_finished()

    refresh_counts()
    ui.timer(0.5, tick)


def results_tab() -> callable:
    container = ui.column().classes("w-full")

    def show(run_dir: str | None) -> None:
        body.clear()
        if not run_dir:
            return
        data = json.loads((Path(run_dir) / "results.json").read_text(encoding="utf-8"))
        s = data["摘要"]
        with body:
            with ui.row().classes("gap-4"):
                for label, value in [
                    ("貼文", s["貼文數"]),
                    ("推薦（61+）", s["分數分布"]["61–100 推薦"]),
                    ("可能相關", s["分數分布"]["31–60 可能相關"]),
                    ("可略過（≤30）", s["分數分布"]["0–30 可略過"]),
                    ("資訊不足", s["資訊不足"]),
                ]:
                    with ui.card().classes("items-center w-32"):
                        ui.label(str(value)).classes("text-2xl font-bold")
                        ui.label(label).classes("text-xs text-gray-500")
            extra = [f"模型：{s['模型']}", f"偏好：{'、'.join(s['偏好'])}"]
            if "動作統計" in s:
                extra.append("動作：" + "、".join(f"{k} {v}" for k, v in s["動作統計"].items()))
            if "結束原因" in s:
                extra.append(f"結束原因：{s['結束原因']}")
            for line in extra:
                ui.label(line).classes("text-sm")

            rows = []
            for p in data["貼文"]:
                hits = [f"{'✓' if k.startswith('想看') else '✗'}{k.split('「')[1].rstrip('」')} {v.split('　')[0].split('（')[0]}"
                        for k, v in p.get("偏好判斷", {}).items() if "符合" in v]
                rows.append({
                    "rank": p["排名"],
                    "score": str(p["分數"]),
                    "author": p["作者"],
                    "text": p["內容"],
                    "hits": "、".join(hits),
                    "actions": "、".join(a for a in p.get("動作", []) if a != "無"),
                    "flags": "、".join(p.get("標記", [])),
                    "url": p["連結"],
                })
            columns = [
                {"name": "rank", "label": "#", "field": "rank", "sortable": True, "align": "right"},
                {"name": "score", "label": "分數", "field": "score", "align": "right"},
                {"name": "author", "label": "作者", "field": "author", "align": "left"},
                {"name": "text", "label": "內容", "field": "text", "align": "left",
                 "style": "white-space: normal; min-width: 360px; max-width: 560px"},
                {"name": "hits", "label": "命中", "field": "hits", "align": "left"},
                {"name": "actions", "label": "動作", "field": "actions", "align": "left"},
                {"name": "flags", "label": "標記", "field": "flags", "align": "left"},
                {"name": "url", "label": "", "field": "url"},
            ]
            table = ui.table(columns=columns, rows=rows, row_key="rank", pagination=20).classes("w-full")
            table.add_slot("body-cell-url", '<q-td :props="props"><a :href="props.value" target="_blank">開啟</a></q-td>')
            ui.input("搜尋").bind_value(table, "filter").classes("w-64")

    with container:
        with ui.row().classes("items-center"):
            selector = ui.select({}, label="執行紀錄", on_change=lambda e: show(e.value)).classes("w-80")
            ui.button(icon="refresh", on_click=lambda: refresh()).props("flat")
        body = ui.column().classes("w-full")

    def refresh() -> None:
        dirs = run_dirs()
        selector.options = {str(d): d.name for d in dirs}
        selector.update()
        selector.value = str(dirs[0]) if dirs else None

    refresh()
    return refresh


def trend_tab() -> callable:
    container = ui.column().classes("w-full")

    def refresh() -> None:
        container.clear()
        history = load_history()
        with container:
            ui.button("重新整理", icon="refresh", on_click=refresh).props("flat")
            if not history:
                ui.label("還沒有紀錄。每天執行一次「每日訓練」後，這裡會顯示首頁內容組成的變化。")
                return
            x = [f"{e['time'][5:16].replace('T', ' ')}{'*' if e['mode'] == 'live' else ''}" for e in history]
            topics = sorted({t for e in history for t in e["metrics"]["topic_share"]})

            def series(name: str, values: list) -> dict:
                return {"name": name, "type": "line", "data": [None if v is None else round(v * 100, 1) for v in values]}

            ui.echart({
                "tooltip": {"trigger": "axis", "valueFormatter": "(v) => v + '%'"},
                "legend": {"top": 0},
                "grid": {"top": 50, "left": 50, "right": 20, "bottom": 40},
                "xAxis": {"type": "category", "data": x},
                "yAxis": {"type": "value", "max": 100, "axisLabel": {"formatter": "{value}%"}},
                "series": [
                    series("推薦（61+）", [e["metrics"]["recommended_share"] for e in history]),
                    series("可略過（≤30）", [e["metrics"]["skip_share"] for e in history]),
                    *[series(t, [e["metrics"]["topic_share"].get(t) for e in history]) for t in topics],
                ],
            }).classes("w-full h-96")
            ui.label("＊ 表示實際互動（live）的執行；其餘為預演。主題比例＝該偏好機率 ≥ 50% 的貼文占比。").classes("text-xs text-gray-500")

    refresh()
    return refresh


def settings_tab() -> None:
    with ui.row().classes("w-full items-start gap-6"):
        # 偏好
        with ui.card().classes("w-[480px]"):
            ui.label("偏好（config/preferences.txt）").classes("text-lg font-medium")
            ui.label("一行一句；「不要／不想看／少看」開頭為不想看。句尾可加（關鍵字：A、B）。").classes("text-sm text-gray-500")
            ui.label("實驗期間修改偏好，前後的趨勢就無法比較。").classes("text-sm text-orange-700")
            editor = ui.textarea(value=PREFS_FILE.read_text(encoding="utf-8")).props("outlined autogrow").classes("w-full font-mono text-sm")
            preview = ui.column().classes("gap-0")

            def update_preview() -> None:
                preview.clear()
                with preview:
                    for line in editor.value.splitlines():
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        for p in parse_line(line):
                            kw = f"　🔑 {'、'.join(p.keywords)}" if p.keywords else ""
                            color = "text-green-700" if p.polarity == "want" else "text-red-700"
                            ui.label(f"{'想看' if p.polarity == 'want' else '不想看'}：{p.topic}{kw}").classes(f"text-sm {color}")

            def save_prefs() -> None:
                PREFS_FILE.write_text(editor.value.rstrip() + "\n", encoding="utf-8")
                ui.notify("偏好已儲存，下次執行生效", type="positive")

            editor.on_value_change(update_preview)
            update_preview()
            ui.button("儲存偏好", icon="save", on_click=save_prefs)

        # 互動設定
        with ui.card().classes("w-[560px]"):
            ui.label("互動設定（config/actions.yaml）").classes("text-lg font-medium")
            cfg = yaml.load(ACTIONS_FILE.read_text(encoding="utf-8"))
            ui.select({"dry_run": "預演（只記錄，不互動）"}, value="dry_run", label="模式").classes("w-64").bind_value(cfg, "mode")
            ui.label("實際互動（live）要先在登入後的畫面驗證點擊，尚未開放。").classes("text-xs text-gray-500")
            ui.number("每次篇數", min=1, max=300, step=10).bind_value(
                cfg, "posts_per_run", forward=lambda v: int(v) if v else 100
            ).classes("w-32")

            def action_block(key: str, title: str, fields: list[tuple[str, str, float, float, float]]) -> None:
                a = cfg["actions"][key]
                with ui.expansion(title, value=True).classes("w-full"):
                    ui.switch("啟用").bind_value(a, "enabled")
                    with ui.row().classes("gap-3"):
                        for field, label, lo, hi, step in fields:
                            cast = int if step >= 1 else float
                            ui.number(label, min=lo, max=hi, step=step).bind_value(
                                a, field, forward=lambda v, cast=cast: cast(v) if v is not None else 0
                            ).classes("w-36")
                        if "seconds" in a:
                            secs = a["seconds"]
                            for i, label in enumerate(["最短秒數", "最長秒數"]):
                                ui.number(
                                    label, value=secs[i], min=1, max=60, step=1,
                                    on_change=lambda e, i=i: e.value is not None and secs.__setitem__(i, int(e.value)),
                                ).classes("w-28")

            action_block("like", "按讚", [("min_score", "最低分數", 0, 100, 1), ("max_avoid", "不想看上限", 0, 1, 0.05), ("daily_limit", "每日上限", 0, 100, 1)])
            action_block("not_interested", "不感興趣", [("max_score", "最高分數", 0, 100, 1), ("min_avoid", "不想看下限", 0, 1, 0.05), ("max_want", "想看上限", 0, 1, 0.05), ("daily_limit", "每日上限", 0, 100, 1)])
            action_block("open_post", "點開貼文", [("min_score", "最低分數", 0, 100, 1), ("daily_limit", "每日上限", 0, 100, 1)])
            action_block("dwell", "停留", [("min_score", "最低分數", 0, 100, 1)])

            def save_actions() -> None:
                with ACTIONS_FILE.open("w", encoding="utf-8") as f:
                    yaml.dump(cfg, f)
                try:
                    load_action_config()
                except Exception as e:  # 寫入後驗證
                    ui.notify(f"設定有誤：{e}", type="negative")
                    return
                ui.notify("互動設定已儲存，下次執行生效", type="positive")

            ui.button("儲存互動設定", icon="save", on_click=save_actions)


def try_tab() -> None:
    state: dict = {}
    ui.label("貼上一篇貼文，看目前偏好下的評分（第一次需載入模型，約十幾秒）。").classes("text-sm text-gray-500")
    text = ui.textarea("貼文內容").props("outlined autogrow").classes("w-[640px]")
    result = ui.column()

    def score(post: str):
        from feed_trainer.models import load_model
        from feed_trainer.preferences import judge, load_preferences, to_questions

        if "model" not in state:
            state["model"] = load_model("laya")
        prefs = load_preferences()
        r = state["model"].answer({"post": post}, to_questions(prefs))
        return judge(prefs, r, post), r

    async def go() -> None:
        if not text.value.strip():
            return
        btn.props("loading")
        try:
            verdict, r = await run.io_bound(score, text.value)
        finally:
            btn.props(remove="loading")
        result.clear()
        with result:
            ui.label(f"分數：{'資訊不足' if verdict.overall is None else verdict.overall} / 100").classes("text-xl font-bold")
            for m in verdict.matches:
                mark = "✓" if m.preference.polarity == "want" else "✗"
                with ui.row().classes("items-center gap-2"):
                    ui.label(f"{mark} {m.preference.topic}").classes("w-40")
                    ui.linear_progress(m.probability, show_value=False).classes("w-60")
                    hint = f"（關鍵字「{m.keyword}」）" if m.keyword else ""
                    ui.label(f"{m.probability:.0%}{hint}").classes("text-sm")
            ui.label(f"{r.model}，{r.latency_ms:.0f} ms").classes("text-xs text-gray-500")

    btn = ui.button("評分", icon="bolt", on_click=go)


# ───────────────────────── 頁面 ─────────────────────────


@ui.page("/")
def index() -> None:
    ui.page_title("Feed Trainer")
    with ui.header().classes("items-center"):
        ui.label("Threads Feed Trainer").classes("text-lg font-medium")
    with ui.tabs().classes("w-full") as tabs:
        t_run = ui.tab("執行", icon="play_circle")
        t_results = ui.tab("結果", icon="table_chart")
        t_trend = ui.tab("趨勢", icon="show_chart")
        t_settings = ui.tab("設定", icon="tune")
        t_try = ui.tab("試玩", icon="bolt")
    refreshers: list = []
    with ui.tab_panels(tabs, value=t_run).classes("w-full"):
        with ui.tab_panel(t_run):
            run_tab(lambda: [f() for f in refreshers])
        with ui.tab_panel(t_results):
            refreshers.append(results_tab())
        with ui.tab_panel(t_trend):
            refreshers.append(trend_tab())
        with ui.tab_panel(t_settings):
            settings_tab()
        with ui.tab_panel(t_try):
            try_tab()


if __name__ in {"__main__", "__mp_main__"}:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-show", action="store_true", help="不自動開啟瀏覽器")
    args, _ = parser.parse_known_args()
    # 只接受本機連線：這個介面能操作 Threads 帳號
    ui.run(title="Feed Trainer", host="127.0.0.1", port=args.port, reload=False, show=not args.no_show)
