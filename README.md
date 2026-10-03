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

## 操作介面

```bash
uv run python scripts/ui.py
```

自動開啟 http://127.0.0.1:8080（只接受本機連線）。分頁：

- **執行**：登入 Threads、每日訓練（可停止）、評分測試貼文，日誌即時顯示；今日動作數
- **結果**：選擇執行紀錄，看摘要與依分數排序的貼文表格（可搜尋）
- **趨勢**：每次訓練的首頁內容組成折線圖
- **設定**：編輯偏好（即時預覽解析結果）、調整互動開關與門檻
- **試玩**：貼上一篇貼文立即評分

以下指令也可以直接在終端機執行。

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

## 階段 C：邊爬邊互動

設計見 [階段C_設計.md](階段C_設計.md)，設定在 [config/actions.yaml](config/actions.yaml)（預設 `dry_run`，只記錄不互動）。

```bash
uv run python scripts/train_feed.py   # 每天執行一次：爬 100 篇、評分、決定動作
uv run python scripts/feed_trend.py   # 查看每天的首頁內容組成變化
```

## 試玩

在 [config/preferences.txt](config/preferences.txt) 一行寫一句偏好，例如「我想看遊戲開發內容」「不要爭議文章」，然後：

```bash
uv run python scripts/try_post.py              # Laya
uv run python scripts/try_post.py --model jev  # Jev
uv run python scripts/try_post.py --advanced   # 改用 config/profile.yaml 的進階問題設定
```

貼上貼文後單獨輸入一行 `.` 送出；`r` 重新讀取設定檔；`q` 離開。

## 測試

```bash
uv run pytest
```

涵蓋偏好解析、關鍵字比對、分數組合、互動決策與每日上限、貼文解析；不需要模型、網路或登入。

## 冒煙測試

```bash
uv run python scripts/smoke_test.py laya jev
```
