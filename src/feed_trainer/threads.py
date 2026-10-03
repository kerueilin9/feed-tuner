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
    # Threads 自己的 AI 生成偵測欄位（gen_ai_detection_method）；格式未知，先原樣記錄
    gen_ai_label: Any = None

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
        gen_ai_label=o.get("gen_ai_detection_method"),
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


class SafetyStopError(RuntimeError):
    """頁面出現驗證、帳號檢查等異常狀態，必須停止。"""


# 網址出現這些字樣代表 Threads／Instagram 要求驗證或帳號受限
STOP_URL_KEYWORDS = ("challenge", "checkpoint", "suspended", "/accounts/disabled")


class FeedSession:
    """開啟已登入的首頁，邊捲動邊交出新貼文。

        with FeedSession(headless=False) as feed:
            for post in feed.posts(count=100):
                ...           # feed.page 可用於之後的互動
    """

    def __init__(self, headless: bool = False, scroll_pause: tuple[float, float] = (1.5, 3.0)):
        self.headless = headless
        self.scroll_pause = scroll_pause
        self.page = None
        self.stats = {"graphql_responses": 0, "graphql_parse_errors": 0, "scrolls": 0}
        self._seen: set[str] = set()
        self._queue: list[Post] = []
        self._pw = None
        self._context = None

    def __enter__(self) -> FeedSession:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        try:
            self._context = open_context(self._pw, self.headless)
            if not is_logged_in(self._context):
                raise NotLoggedInError("尚未登入 Threads，請先執行：uv run python scripts/login.py")
            self.page = self._context.pages[0] if self._context.pages else self._context.new_page()
            self.page.on("response", self._on_response)
            log.info("開啟 Threads 首頁")
            self.page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
            self.page.wait_for_timeout(4000)
            if "/login" in self.page.url:
                raise NotLoggedInError("登入狀態已失效，請重新執行：uv run python scripts/login.py")
            self.check_safety()
            for text in self.page.locator('script[type="application/json"]').all_text_contents():
                if (data := _parse_json(text)) is not None:
                    self._add(find_posts(data), "首頁")
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None

    def check_safety(self) -> None:
        url = self.page.url
        if any(k in url for k in STOP_URL_KEYWORDS):
            raise SafetyStopError(f"頁面導向異常網址，立即停止：{url}")

    def _add(self, posts: list[Post], source: str) -> None:
        new = 0
        for p in posts:
            if p.post_id not in self._seen:
                self._seen.add(p.post_id)
                self._queue.append(p)
                new += 1
                log.debug("新貼文 %s @%s（%s）：%s", p.post_id, p.author, source, p.text[:40].replace("\n", " "))
                if p.gen_ai_label:
                    log.info("貼文 %s 帶有 Threads AI 標記：%r", p.post_id, p.gen_ai_label)
        if new:
            log.debug("從 %s 取得 %d 篇新貼文，累計 %d 篇", source, new, len(self._seen))

    def _on_response(self, response) -> None:
        if "graphql" not in response.url:
            return
        self.stats["graphql_responses"] += 1
        try:
            data = _parse_json(response.text())
        except Exception as e:  # 回應已關閉、非文字等
            log.debug("讀取 GraphQL 回應失敗：%s", e)
            return
        if data is None:
            self.stats["graphql_parse_errors"] += 1
            return
        self._add(find_posts(data), "捲動載入")

    def scroll(self) -> None:
        self.stats["scrolls"] += 1
        self.page.mouse.wheel(0, random.randint(1500, 2500))
        pause = random.uniform(*self.scroll_pause)
        log.debug("第 %d 次捲動，等待 %.1f 秒", self.stats["scrolls"], pause)
        self.page.wait_for_timeout(pause * 1000)
        self.check_safety()

    def posts(self, count: int, max_scrolls: int | None = None):
        """依出現順序交出新貼文，直到 count 篇；佇列空了就捲動。"""
        max_scrolls = max_scrolls or max(30, count)
        delivered = 0
        while delivered < count:
            if not self._queue:
                if self.stats["scrolls"] >= max_scrolls:
                    log.warning("捲動 %d 次後只取得 %d 篇（目標 %d）", self.stats["scrolls"], delivered, count)
                    return
                self.scroll()
                continue
            delivered += 1
            yield self._queue.pop(0)


def scrape_feed(count: int = 20, headless: bool = False) -> list[Post]:
    start = time.perf_counter()
    with FeedSession(headless=headless) as feed:
        posts = list(feed.posts(count))
        stats = feed.stats
    log.info(
        "爬取完成：%d 篇，%.1f 秒，捲動 %d 次，GraphQL 回應 %d 個（解析失敗 %d）",
        len(posts),
        time.perf_counter() - start,
        stats["scrolls"],
        stats["graphql_responses"],
        stats["graphql_parse_errors"],
    )
    return posts
