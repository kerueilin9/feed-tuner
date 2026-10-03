"""互動試玩：貼上一篇貼文，看模型對每個問題的回答。

    uv run python scripts/try_post.py              # Laya
    uv run python scripts/try_post.py --model jev  # Jev（需 .env 中的 TYPESAFE_API_KEY）

貼上貼文後，單獨輸入一行 "." 送出（貼文可以多行）。輸入 "q" 離開，輸入 "r" 重新讀取 profile.yaml。
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from feed_trainer.models import Answer, load_model
from feed_trainer.profile import Profile, load_profile


def read_post() -> str | None:
    print("\n貼上貼文（單獨一行 . 送出；q 離開；r 重新讀取問題設定）：")
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


def describe(answer: Answer, question: dict) -> str:
    if answer.type == "noul":
        bar = "█" * round(answer.value * 10) + "·" * (10 - round(answer.value * 10))
        return f"{bar} 是 {answer.value:.0%}"
    conf = f"（信心 {answer.confidence:.0%}）" if answer.confidence is not None else ""
    if answer.type == "score":
        levels = question["criteria"]
        nearest = levels[min(len(levels) - 1, round(answer.value))]
        return f"{answer.value:.2f} / {len(levels) - 1} ≈ {nearest}{conf}"
    label = question["criteria"].get(answer.value, answer.value)
    return f"{answer.value}：{label}{conf}"


def show(profile: Profile, result) -> None:
    print(f"\n── {result.model}　{result.latency_ms:.0f}ms　{result.input_tokens} tokens ──")
    for qid, q in profile.questions.items():
        a = result.answers.get(qid)
        if a is None:
            continue
        print(f"・{q['instructions']}")
        print(f"    {describe(a, q)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="laya", help="laya、jev 或指定版本，例如 jev-1.13.0")
    args = parser.parse_args()

    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    profile = load_profile()
    print(f"載入 {args.model}……（Laya 第一次約需一分鐘）")
    model = load_model(args.model)

    while True:
        post = read_post()
        if post is None or post == "q":
            break
        if post == "r":
            profile = load_profile()
            print(f"已重新讀取，共 {len(profile.questions)} 題")
            continue
        if not post:
            continue
        show(profile, model.answer({"post": post}, profile.model_questions()))


if __name__ == "__main__":
    main()
