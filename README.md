# feed-tuner

Threads Feed Trainer：以 Jev／Laya 決策模型依使用者偏好評分 Threads 貼文。

- 企劃：[Threads_Feed_Trainer_企劃.md](Threads_Feed_Trainer_企劃.md)
- 目前階段：[MVP 階段 A：離線評分原型](MVP_階段A.md)

## 環境

需要 [uv](https://docs.astral.sh/uv/)。預設安裝 CUDA 12.8 版 PyTorch。

```bash
uv sync
cp .env.example .env   # 使用 Jev 時填入 TYPESAFE_API_KEY
```

## 爬取首頁並評分

```bash
uv run python scripts/login.py     # 第一次：在開啟的 Chrome 視窗手動登入 Threads
uv run python scripts/run_feed.py  # 爬 20 篇首頁貼文，用 Laya 依 config/preferences.txt 評分
```

結果在 `results/<時間>/`：

- `report.md`：依分數排序的表格
- `results.json`：整理過的完整結果（摘要＋每篇的分數、偏好判斷，依分數排序）
- `posts.json`：爬到的原始貼文
- `run.log`：本次執行的日誌

只改偏好、不想重爬時：`uv run python scripts/run_feed.py --from results/<時間>/posts.json`。

日誌累積在 `logs/feed_trainer.log`，即時監看（PowerShell）：

```powershell
Get-Content logs\feed_trainer.log -Wait -Tail 50
```

登入狀態存在 `.threads_profile/`，結果與日誌含他人貼文，三者都不進 git。

## 試玩

在 [config/preferences.txt](config/preferences.txt) 一行寫一句偏好，例如「我想看遊戲開發內容」「不要爭議文章」，然後：

```bash
uv run python scripts/try_post.py              # Laya
uv run python scripts/try_post.py --model jev  # Jev
uv run python scripts/try_post.py --advanced   # 改用 config/profile.yaml 的進階問題設定
```

貼上貼文後單獨輸入一行 `.` 送出；`r` 重新讀取設定檔；`q` 離開。

## 冒煙測試

```bash
uv run python scripts/smoke_test.py laya jev
```
