# Threads Feed Trainer｜MVP 階段 A：離線評分原型

版本：v0.2  
日期：2026-10-03  
對應企劃：[Threads_Feed_Trainer_企劃.md](Threads_Feed_Trainer_企劃.md) v0.2 第 6 節階段 A

> v0.2：已對照 TypeSafe 官方文件（docs.typesafe.ai）與 Laya GitHub README，補上安裝方式、API 格式與限制（第 3、9 節）。

## 1. 目標

回答一個問題：**Jev 或 Laya 能否依照使用者偏好，正確挑出值得閱讀的中文 Threads 貼文？**

完成標準：

- 同一批人工標註貼文，可以分別用 Laya、Jev 和關鍵字基準評分並排序。
- 產出比較報告，包含 Precision@10、漏失比例、不確定比例、延遲與成本。
- 能據此決定階段 B 使用哪個方案（只用 Laya／只用 Jev／Laya → Jev），或判定兩者中文能力不足。

## 2. 範圍

| 包含 | 不包含 |
| --- | --- |
| 手動整理的貼文樣本（純文字） | Threads 自動抓取、登入、滑動 |
| 偏好設定與評分問題（設定檔） | 瀏覽器擴充功能、圖形介面 |
| Laya 本機推論、Jev API 呼叫 | GPT／Claude 等生成式模型 |
| 關鍵字基準評分器 | 圖片理解、OCR |
| 評估腳本與比較報告 | 自動按讚或任何互動 |

## 3. 技術選擇

| 項目 | 選擇 | 理由 |
| --- | --- | --- |
| 語言 | Python 3.12 | Laya 需 PyTorch；資料分析方便；階段 B 可沿用為本機推論服務 |
| 環境管理 | uv | 已安裝；可獨立管理 Python 版本與相依套件，不動到系統 Python 3.9 |
| 硬體 | 本機 RTX 3080 10GB | 足以執行約 421M 參數的 Laya |
| Laya 執行 | `laya` 套件 + CUDA 版 PyTorch，使用 `laya-multilingual` checkpoint | 多語言版（mmBERT-base，322M），英文版無法處理中文 |
| Jev 呼叫 | `typesafe-sdk`（Python），釘選 `jev-1.13.0` | 避免 `jev-latest` 更新後前後結果無法比較 |
| 設定檔 | YAML | 偏好與問題要方便手動修改 |
| 資料格式 | JSONL | 一行一篇貼文，易於增修與版本控制 |
| 版本控制 | git | 專案目前尚未初始化 |

API key 放在 `.env`，不進版本控制。

### 3.1 兩個模型的實際規格

| 項目 | Jev（jev-1.13.0） | Laya（laya-multilingual） |
| --- | --- | --- |
| 介面 | `POST https://api.typesafe.ai/v1/systemone` | 本機 `Router.predict()`；另有 `laya-serve` 提供相容 Jev 的 HTTP 端點 |
| 問題類型 | Choice／Score／Noul | 同左，格式相容 |
| 價格 | 輸入 $0.042／百萬 token，輸出免費 | 免費（本機） |
| 長度上限 | state 加最長問題 32k token；整個請求 64k | 預設 1,024 token，可設 `max_len` 到 8,192 |
| 速率限制 | 80 請求／秒、10 萬 token／秒（官方註明會動態調整） | 受本機 GPU 限制 |
| 中文 | 官方：英文最好，CJK 可用但較弱，需自行測試 | 支援 100+ 語言；README 提到有中文可靠度評估 |
| 版本 | 0.7.2 SDK，需 Python ≥ 3.10 | 0.3.24，需 Python ≥ 3.10 |

兩者的請求與回應格式相同，因此同一份問題設定可以直接送給兩個模型。

### 3.2 官方提醒的限制（jev-1.13）

- 照字面理解問題：條件要寫清楚，邊界情況寫進 criteria。
- 不擅長計數、數字比較、日期比較：這些放在程式裡做。
- state 中不相關的內容越多，準確度越低：只送貼文本身。
- 可能被貼文中的對抗性內容影響：即企劃中「貼文不能當指令」的風險，需要測試。
- Choice 偏好排在前面的選項：需調換順序驗證。
- Noul 回傳 0.5 表示「是／否機率相近」，不是「中等程度」。

## 4. 專案結構

```
Threads_Feed_Trainer/
├─ Threads_Feed_Trainer_企劃.md
├─ MVP_階段A.md
├─ pyproject.toml
├─ .env.example              # JEV_API_KEY=
├─ config/
│  └─ profile.yaml           # 偏好、評分問題、權重、門檻
├─ data/
│  ├─ posts.jsonl            # 貼文樣本（不進版本控制）
│  └─ labels.jsonl           # 人工標註
├─ src/feed_trainer/
│  ├─ models/
│  │  ├─ base.py             # 統一的決策模型介面
│  │  ├─ laya.py
│  │  ├─ jev.py
│  │  └─ keyword.py          # 關鍵字基準
│  ├─ profile.py             # 讀取 profile.yaml
│  ├─ scoring.py             # 問題答案 → 分數、理由標籤、不確定性
│  ├─ dedupe.py              # 去重與新穎性
│  └─ evaluate.py            # 指標計算
├─ scripts/
│  ├─ smoke_test.py          # 冒煙測試：確認模型能跑
│  ├─ score.py               # 對資料集評分，輸出結果
│  └─ report.py              # 產生比較報告
└─ results/                  # 各次執行的輸出（含模型、時間、設定版本）
```

## 5. 資料格式

### 5.1 貼文 `data/posts.jsonl`

```json
{"post_id": "p0001", "text": "貼文內容……", "source_url": "https://www.threads.net/...", "has_media": false, "is_quote": false, "collected_at": "2026-10-03"}
```

- 只收錄使用者有權使用的貼文，可用手動複製。
- `has_media`、`is_quote` 為真且文字不足以判斷時，預期答案為「資訊不足」。

### 5.2 標註 `data/labels.jsonl`

```json
{"post_id": "p0001", "label": "want", "split": "test", "note": "Godot 實作，有數據"}
```

- `label`：`want`／`not_want`／`neutral`／`insufficient`
- `split`：`calib`（調整問題與門檻用）／`test`（只在最終比較時使用）
- 重複或高度相似的貼文必須在同一個 split。

### 5.3 設定 `config/profile.yaml`

完整內容見 [config/profile.yaml](config/profile.yaml)。每題的 `type`／`instructions`／`criteria` 直接送給模型；`group`、`effect` 只給程式使用，送出前移除。

```yaml
questions:
  godot:
    group: relevance
    type: score
    instructions: "這篇貼文和 Godot 遊戲引擎有多相關？"
    criteria:
      - "沒有提到 Godot"
      - "順帶提到 Godot，但主要在講別的事"
      - "部分內容在討論 Godot"
      - "主要在討論 Godot 的使用、開發技巧或開發經驗"
  concrete:
    group: quality
    type: noul
    instructions: "這篇貼文是否包含具體的做法、程式碼、測試結果、數據或成品展示？"
  needs_context:
    effect: insufficient
    type: noul
    instructions: "只讀這段文字，讀者是否無法理解貼文在說什麼……？"
```

不確定性判定：

- Noul：機率接近 0.5 表示是／否難分。
- Choice／Score：看回傳的 `confidence`。
- 實際門檻用 calib 集決定，不預設數值。

問題文字可能需要中英文各試一版，作為中文能力測試的一部分。

## 6. 統一模型介面

三個評分器實作相同介面，讓評估腳本不需要知道背後是哪個模型：

實作見 [src/feed_trainer/models/base.py](src/feed_trainer/models/base.py)：

```python
class DecisionModel(Protocol):
    name: str
    def answer(self, state, questions: dict[str, dict]) -> ModelResult: ...

@dataclass
class Answer:
    question_id: str
    type: Literal["choice", "score", "noul"]
    value: str | float          # 選項／分數期望值／「是」的機率
    confidence: float | None    # Noul 沒有
    probabilities: dict[str, float]

@dataclass
class ModelResult:
    model: str                  # 實際回答的模型 ID
    answers: dict[str, Answer]
    latency_ms: float
    input_tokens: int | None
    cost_usd: float | None
```

state 使用 `{"post": 貼文文字}`，只放貼文本身。

`scoring.py` 把 `Answer` 轉成企劃 4.3 的輸出格式（scores、uncertainty、reason_tags、suggested_action）。

評分結果會快取，以 `(模型, 模型版本, 問題設定雜湊, post_id)` 作為鍵，避免修改報告時重複呼叫 Jev。

## 7. 執行步驟

| Step | 內容 | 產出 | 預估 |
| --- | --- | --- | --- |
| 1 ✅ | 查證 Jev／Laya 官方文件；申請 Jev early access | 第 3 節規格與限制；early access 已申請 | 0.5 天 |
| 2 ✅ | 建立專案：git、uv、目錄結構、`.env`、兩個模型的介面、冒煙測試 | `scripts/smoke_test.py` | 0.5 天 |
| 3 | 蒐集並標註 50–100 篇中文貼文 | `posts.jsonl`、`labels.jsonl` | 1–2 天 |
| 4 | 撰寫 `profile.yaml` 初版問題 | 5–8 個評分問題 | 0.5 天 |
| 5 | 實作關鍵字基準與 Laya 評分器 | 第一次完整評分 | 1 天 |
| 6 | 實作 Jev 評分器（取得權限後） | 同資料集 Jev 結果 | 0.5 天 |
| 7 | **中文能力檢查點**：三者比較 | 簡易報告，決定是否繼續 | 0.5 天 |
| 8 | 擴充樣本至 200–500 篇 | 完整資料集 | 視蒐集速度 |
| 9 | 四組方案完整比較（含 Laya → Jev） | 階段 A 比較報告 | 1 天 |

Jev 權限未取得前，Step 5 先以 Laya 跑通完整流程，Step 6 延後。

## 8. 評估

### 8.1 指標

| 指標 | 計算方式 |
| --- | --- |
| Precision@10 | 依 overall 排序前 10 篇中，`want` 的比例 |
| 漏失比例 | `want` 貼文中，被判為 0–30 分的比例 |
| 不確定比例 | 被判為不確定或資訊不足的比例 |
| 資訊不足命中率 | 標為 `insufficient` 的貼文中，系統也判為資訊不足的比例 |
| 機率校正 | 依機率分組，比較預測與實際正確率 |
| P50／P95 延遲 | 每篇評分耗時 |
| 每 100 篇成本 | Jev 依 token 計；Laya 記錄耗時即可 |

樣本少時 Precision@10 波動大，Step 7 另外看 Precision@20 與整體排序相關性作為參考。

### 8.2 決策門檻

| 結果 | 下一步 |
| --- | --- |
| 至少一個模型 Precision@10 ≥ 80% 且優於關鍵字基準 | 進入 Step 8–9，之後進入階段 B |
| 優於基準但未達 80% | 調整問題寫法與門檻（只用 calib 集）後重測 |
| 兩者皆不優於關鍵字基準 | 回到企劃，重新評估「只用 Jev／Laya」前提 |

## 9. 待確認事項

| 項目 | 狀態 |
| --- | --- |
| Laya 權重下載位置、載入方式、CUDA 需求 | ✅ 首次呼叫自動從 Hugging Face 下載；需 CUDA 版 PyTorch |
| Laya 支援的問題類型與輸入長度上限 | ✅ 見 3.1 |
| Jev early access | 已申請，等待開通 |
| Jev API 格式、速率限制、計費方式 | ✅ 見 3.1 |
| 兩者對繁體中文問題與貼文的支援 | Step 7 實測 |
| 問題用中文或英文寫效果較好 | Step 7 實測 |
| 貼文樣本來源與使用權限 | 使用者自行確認 |

### 9.1 參考來源

- TypeSafe 文件：https://docs.typesafe.ai （models、jev-1.13 jaggedness、Python SDK）
- Laya：https://github.com/NandhaKishorM/laya 、https://huggingface.co/convaiinnovations/laya-multilingual
