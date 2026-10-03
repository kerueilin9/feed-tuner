"""互動試玩：貼上一篇貼文，看模型怎麼判斷。

    uv run python scripts/try_post.py                # Laya + config/preferences.txt（一句話偏好）
    uv run python scripts/try_post.py --model jev    # 改用 Jev（需 .env 中的 TYPESAFE_API_KEY）
    uv run python scripts/try_post.py --advanced     # 改用 config/profile.yaml（進階問題設定）

貼上貼文後，單獨輸入一行 "." 送出（貼文可以多行）。輸入 "q" 離開，輸入 "r" 重新讀取設定檔。
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from feed_trainer.models import Answer, ModelResult, load_model
from feed_trainer.preferences import judge, load_preferences, to_questions
from feed_trainer.profile import load_profile


def read_post() -> str | None:
    print("\n貼上貼文（單獨一行 . 送出；q 離開；r 重新讀取設定）：")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            return None
        if not lines and line.strip() in {"q", "r"}:
            return line.strip()
        if line.strip() == ".":
            return "\n".join(lines).strip()
        lines.append(line)


def bar(p: float) -> str:
    n = round(p * 10)
    return "█" * n + "·" * (10 - n)


class SimpleMode:
    """config/preferences.txt：一句話偏好。"""

    def load(self) -> None:
        self.prefs = load_preferences()
        self.questions = to_questions(self.prefs)
        print("偏好：")
        for p in self.prefs:
            print(f"  {'想看  ' if p.polarity == 'want' else '不想看'}　{p.topic}")

    def show(self, result: ModelResult) -> None:
        verdict = judge(self.prefs, result)
        score = "資訊不足（內容可能依賴圖片、連結或引用）" if verdict.overall is None else f"{verdict.overall} / 100"
        print(f"\n── 分數：{score}　（{result.model}，{result.latency_ms:.0f}ms）──")
        for p, prob in verdict.matches:
            mark = "✓" if p.polarity == "want" else "✗"
            print(f"  {mark} {bar(prob)} {prob:4.0%}  {p.topic}")


class AdvancedMode:
    """config/profile.yaml：進階問題設定。"""

    def load(self) -> None:
        self.profile = load_profile()
        self.questions = self.profile.model_questions()
        print(f"進階設定：共 {len(self.questions)} 題")

    @staticmethod
    def describe(answer: Answer, question: dict) -> str:
        if answer.type == "noul":
            return f"{bar(answer.value)} 是 {answer.value:.0%}"
        conf = f"（信心 {answer.confidence:.0%}）" if answer.confidence is not None else ""
        if answer.type == "score":
            levels = question["criteria"]
            nearest = levels[min(len(levels) - 1, round(answer.value))]
            return f"{answer.value:.2f} / {len(levels) - 1} ≈ {nearest}{conf}"
        label = question["criteria"].get(answer.value, answer.value)
        return f"{answer.value}：{label}{conf}"

    def show(self, result: ModelResult) -> None:
        print(f"\n── {result.model}　{result.latency_ms:.0f}ms　{result.input_tokens} tokens ──")
        for qid, q in self.profile.questions.items():
            if (a := result.answers.get(qid)) is not None:
                print(f"・{q['instructions']}")
                print(f"    {self.describe(a, q)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="laya", help="laya、jev 或指定版本，例如 jev-1.13.0")
    parser.add_argument("--advanced", action="store_true", help="使用 config/profile.yaml")
    args = parser.parse_args()

    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    mode = AdvancedMode() if args.advanced else SimpleMode()
    mode.load()
    print(f"\n載入 {args.model}……（Laya 第一篇約需十幾秒）")
    model = load_model(args.model)

    while True:
        post = read_post()
        if post is None or post == "q":
            break
        if post == "r":
            mode.load()
            continue
        if post:
            mode.show(model.answer({"post": post}, mode.questions))


if __name__ == "__main__":
    main()
