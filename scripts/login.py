"""開啟 Chrome 視窗讓你手動登入 Threads；登入狀態存在 .threads_profile/（不進 git）。

    uv run python scripts/login.py

登入完成後視窗會自動關閉。程式不讀取也不儲存你的帳號密碼。
"""

from __future__ import annotations

import logging
import time

from playwright.sync_api import sync_playwright

from feed_trainer.log import setup_logging
from feed_trainer.threads import LOGIN_URL, is_logged_in, open_context

TIMEOUT_SECONDS = 600

log = logging.getLogger("login")


def main() -> None:
    setup_logging()
    with sync_playwright() as pw:
        context = open_context(pw, headless=False)
        try:
            if is_logged_in(context):
                log.info("已經是登入狀態，不需要重新登入")
                return
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(LOGIN_URL)
            log.info("請在開啟的 Chrome 視窗中登入 Threads（%d 分鐘內）", TIMEOUT_SECONDS // 60)
            deadline = time.time() + TIMEOUT_SECONDS
            while time.time() < deadline:
                if is_logged_in(context):
                    page.wait_for_timeout(3000)  # 讓登入流程寫完 cookie
                    log.info("登入成功，狀態已儲存到 .threads_profile/")
                    return
                page.wait_for_timeout(2000)
            log.error("等待逾時，未偵測到登入")
        finally:
            context.close()


if __name__ == "__main__":
    main()
