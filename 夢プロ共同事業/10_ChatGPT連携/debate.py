#!/usr/bin/env python3
"""ChatGPT(OpenAI) と Claude(Anthropic API) を数ラウンド往復させ、議論全体を ログ/ に保存する。

使い方:
  export OPENAI_API_KEY=sk-... ANTHROPIC_API_KEY=sk-ant-...
  python3 10_ChatGPT連携/debate.py "料金案の弱点を洗い出し、改善案をまとめて" -f 07_アチーバー収益設計.md -r 3 -t 料金議論
  python3 10_ChatGPT連携/debate.py "..." --dry-run    # 送信せず構成だけ確認

環境変数: OPENAI_MODEL(既定 gpt-4o) / ANTHROPIC_MODEL(既定 claude-sonnet-5-5)
流れ: ChatGPTが案を出す → Claudeが批評・補強 → ChatGPTが反映…を指定ラウンド繰り返し、最後にClaudeが結論を整理。
"""
import argparse, json, os, sys, urllib.request, urllib.error
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")


def post(url, headers, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"APIエラー {e.code}: {e.read().decode()}")


def ask_chatgpt(system, user):
    res = post("https://api.openai.com/v1/chat/completions",
               {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
               {"model": OPENAI_MODEL,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    return res["choices"][0]["message"]["content"]


def ask_claude(system, user):
    res = post("https://api.anthropic.com/v1/messages",
               {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
               {"model": ANTHROPIC_MODEL, "max_tokens": 4096, "system": system,
                "messages": [{"role": "user", "content": user}]})
    return "".join(b.get("text", "") for b in res["content"])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("request")
    p.add_argument("-f", "--files", nargs="*")
    p.add_argument("-r", "--rounds", type=int, default=2, help="往復回数(既定2)")
    p.add_argument("-t", "--theme", default="debate")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    files = [ROOT / n for n in a.files] if a.files else sorted(ROOT.glob("[0-9][0-9]_*.md"))
    context = "\n\n".join(f"===== {f.name} =====\n{f.read_text(encoding='utf-8')}" for f in files)
    base = "あなたは事業企画の共同検討者です。日本語で具体的に簡潔に回答してください。\n\n# 資料\n" + context

    if a.dry_run:
        print(f"openai={OPENAI_MODEL} claude={ANTHROPIC_MODEL} files={len(files)} "
              f"chars={len(context):,} rounds={a.rounds} (API呼び出し約{a.rounds * 2 + 1}回)")
        return
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        if not os.environ.get(k):
            sys.exit(f"{k} が未設定です")

    log, draft, critique = [], "", ""
    for i in range(1, a.rounds + 1):
        gpt_in = f"# 依頼\n{a.request}" if i == 1 else (
            f"# 依頼\n{a.request}\n\n# あなたの前回案\n{draft}\n\n# Claudeの批評\n{critique}\n\n批評を踏まえて案を改訂してください。")
        draft = ask_chatgpt(base + "\nあなたはChatGPT。案を出す/改訂する役です。", gpt_in)
        log.append(f"### ラウンド{i} ChatGPT\n{draft}")
        critique = ask_claude(base + "\nあなたはClaude。ChatGPTの案の論理の穴・数字の無理・抜けを批評し、補強案を示す役です。",
                              f"# 依頼\n{a.request}\n\n# ChatGPTの案\n{draft}")
        log.append(f"### ラウンド{i} Claude\n{critique}")

    final = ask_claude(base + "\nあなたはClaude。議論の司会として結論を整理する役です。",
                       f"# 依頼\n{a.request}\n\n# 議論\n" + "\n\n".join(log) +
                       "\n\n決まったこと・未決事項・推奨アクションに整理してください。")
    out = HERE / "ログ" / f"{date.today()}_{a.theme}.md"
    out.write_text(
        f"# 引き継ぎメモ: {a.theme}\n\n- 日付: {date.today()}\n- 方向: ChatGPT ⇄ Claude 議論\n- 状態: 未反映\n"
        f"- 対象ファイル: {', '.join(f.name for f in files)}\n- モデル: {OPENAI_MODEL} / {ANTHROPIC_MODEL}\n"
        f"- ラウンド数: {a.rounds}\n\n## 依頼\n{a.request}\n\n## 結論(Claude整理)\n{final}\n\n## 議論ログ\n"
        + "\n\n".join(log) + "\n", encoding="utf-8")
    print(f"保存: {out}")


main()
