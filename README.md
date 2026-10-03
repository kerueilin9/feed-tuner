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

## 冒煙測試

```bash
uv run python scripts/smoke_test.py laya jev
```
