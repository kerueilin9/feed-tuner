"""讀取 Threads 首頁動態（唯讀，不做任何互動）。

使用本機 Chrome 與獨立的瀏覽器資料夾 `.threads_profile/`；登入由使用者在
`scripts/login.py` 開啟的視窗中手動完成，程式不經手帳號密碼。

貼文資料取自頁面內嵌的 JSON 與捲動時的 GraphQL 回應，而非解析畫面：
凡是同時有 code、caption、user 欄位的物件都視為一篇貼文。
"""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PROFILE_DIR = Path(".threads_profile")
HOME_URL = "https://www.threads.com/"
LOGIN_URL = "https://www.threads.com/login"
SESSION_COOKIE = "sessionid"

# media_type：19 純文字、1 圖片、2 影片、8 多圖（觀察值，非官方文件）
TEXT_ONLY_MEDIA = {19}


class NotLoggedInError(RuntimeError):
    pass


@dataclass
class Post:
    post_id: str  # Threads 貼文代碼，即網址中 /post/<code>
    author: str
    text: str
    url: str
    taken_at: int | None
    like_count: int | None
    reply_count: int | None
    media_type: int | None
    has_media: bool
    has_link: bool
    is_reply: bool
    quoted_text: str | None
    is_paid_partnership: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def state(self) -> dict[str, str]:
        """送給模型的內容：只放貼文文字與被引用的貼文。"""
        state = {"post": self.text}
        if self.quoted_text:
            state["quoted_post"] = self.quoted_text
        return state


def _caption(o: dict[str, Any]) -> str:
    return ((o.get("caption") or {}).get("text") or "").strip()


def parse_post(o: dict[str, Any]) -> Post | None:
    code = o.get("code")
    username = (o.get("user") or {}).get("username")
    if not code or not username:
        return None
    info = o.get("text_post_app_info") or {}
    share = info.get("share_info") or {}
    quoted = share.get("quoted_post") or share.get("quoted_attachment_post")
    media_type = o.get("media_type")
    return Post(
        post_id=code,
        author=username,
        text=_caption(o),
        url=f"https://www.threads.com/@{username}/post/{code}",
        taken_at=o.get("taken_at"),
        like_count=o.get("like_count"),
        reply_count=info.get("direct_reply_count"),
        media_type=media_type,
        has_media=media_type not in TEXT_ONLY_MEDIA,
        has_link=bool(info.get("link_preview_attachment")),
        is_reply=bool(info.get("is_reply")),
        quoted_text=_caption(quoted) if isinstance(quoted, dict) else None,
        is_paid_partnership=bool(o.get("is_paid_partnership")),
    )


def find_posts(data: Any) -> list[Post]:
    """遞迴找出貼文；不深入 share_info，避免把被引用的貼文當成動態中的貼文。"""
    posts: list[Post] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if "code" in o and "caption" in o and "user" in o:
                if (post := parse_post(o)) is not None:
                    posts.append(post)
            for k, v in o.items():
                if k != "share_info":
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    return posts


def _parse_json(text: str) -> Any | None:
    text = text.removeprefix("for (;;);")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def open_context(playwright, headless: bool):
    PROFILE_DIR.mkdir(exist_ok=True)
    return playwright.chromium.launch_persistent_context(
        str(PROFILE_DIR),
        channel="chrome",
        headless=headless,
        viewport={"width": 1280, "height": 900},
    )


def is_logged_in(context) -> bool:
    return any(c["name"] == SESSION_COOKIE and "threads" in c["domain"] for c in context.cookies())


def scrape_feed(count: int = 20, headless: bool = False, max_scrolls: int = 30) -> list[Post]:
    from playwright.sync_api import sync_playwright

    collected: dict[str, Post] = {}
    stats = {"graphql_responses": 0, "graphql_parse_errors": 0}

    def add(posts: list[Post], source: str) -> None:
        new = 0
        for p in posts:
            if p.post_id not in collected:
                collected[p.post_id] = p
                new += 1
                log.debug("新貼文 %s @%s（%s）：%s", p.post_id, p.author, source, p.text[:40].replace("\n", " "))
        if new:
            log.info("從 %s 取得 %d 篇新貼文，累計 %d 篇", source, new, len(collected))

    def on_response(response) -> None:
        if "graphql" not in response.url:
            return
        stats["graphql_responses"] += 1
        try:
            data = _parse_json(response.text())
        except Exception as e:  # 回應已關閉、非文字等
            log.debug("讀取 GraphQL 回應失敗：%s", e)
            return
        if data is None:
            stats["graphql_parse_errors"] += 1
            return
        add(find_posts(data), "捲動載入")

    start = time.perf_counter()
    with sync_playwright() as pw:
        context = open_context(pw, headless)
        try:
            if not is_logged_in(context):
                raise NotLoggedInError("尚未登入 Threads，請先執行：uv run python scripts/login.py")
            page = context.pages[0] if context.pages else context.new_page()
            page.on("response", on_response)
            log.info("開啟 Threads 首頁")
            page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(4000)
            if "/login" in page.url:
                raise NotLoggedInError("登入狀態已失效，請重新執行：uv run python scripts/login.py")

            for text in page.locator('script[type="application/json"]').all_text_contents():
                if (data := _parse_json(text)) is not None:
                    add(find_posts(data), "首頁")

            scrolls = 0
            while len(collected) < count and scrolls < max_scrolls:
                scrolls += 1
                page.mouse.wheel(0, random.randint(1500, 2500))
                pause = random.uniform(1.5, 3.0)
                log.debug("第 %d 次捲動，等待 %.1f 秒", scrolls, pause)
                page.wait_for_timeout(pause * 1000)
            if len(collected) < count:
                log.warning("捲動 %d 次後只取得 %d 篇（目標 %d）", scrolls, len(collected), count)
        finally:
            context.close()

    log.info(
        "爬取完成：%d 篇，%.1f 秒，GraphQL 回應 %d 個（解析失敗 %d）",
        min(len(collected), count),
        time.perf_counter() - start,
        stats["graphql_responses"],
        stats["graphql_parse_errors"],
    )
    return list(collected.values())[:count]
