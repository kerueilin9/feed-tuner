"""冒煙測試：用企劃 3.1 的虛構貼文確認模型能跑、輸出格式正確。

    uv run python scripts/smoke_test.py            # Laya
    uv run python scripts/smoke_test.py jev        # Jev（需 .env 中的 TYPESAFE_API_KEY）
    uv run python scripts/smoke_test.py laya jev   # 兩者都跑

這不是評估：四篇貼文看不出準確度，只用來確認環境與介面。
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

from feed_trainer.models import load_model
from feed_trainer.profile import load_profile

# 企劃 3.1 的虛構示例（非實際 Threads 貼文）
POSTS = {
    "godot_dungeon": "用 Godot 4 做了程序生成地下城，從 BSP 換成 WFC 之後生成時間從 120ms 降到 35ms，附上 GDScript 與效能測試圖表，歡迎參考。",
    "node2d_intro": "Godot 新手教學第一集：什麼是 Node2D？今天教大家怎麼在場景裡新增第一個節點。",
    "daily_rant": "今天捷運又誤點了，早餐也沒買到，整天心情都很差。",
    "level_design": "分享在 Unreal 裡做關卡時學到的引導技巧：用光線和顏色帶玩家走向出口，而不是靠箭頭提示。",
}


def main(model_names: list[str]) -> None:
    load_dotenv()
    profile = load_profile()
    questions = profile.model_questions()

    for name in model_names:
        model = load_model(name)
        print(f"\n===== {model.name} =====")
        for post_id, text in POSTS.items():
            result = model.answer({"post": text}, questions)
            print(f"\n[{post_id}] model={result.model} latency={result.latency_ms:.0f}ms tokens={result.input_tokens}")
            for qid, a in result.answers.items():
                value = a.value if isinstance(a.value, str) else f"{a.value:.2f}"
                conf = f" conf={a.confidence:.2f}" if a.confidence is not None else ""
                print(f"  {qid:16} {a.type:6} {value}{conf}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["laya"])
