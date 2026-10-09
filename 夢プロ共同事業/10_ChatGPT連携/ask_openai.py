#!/usr/bin/env python3
"""資料をOpenAI APIに渡して依頼を実行し、結果を ログ/ に引き継ぎメモ形式で保存する。

使い方:
  export OPENAI_API_KEY=sk-...
  python3 10_ChatGPT連携/ask_openai.py "料金案の弱点を指摘して" -f 07_アチーバー収益設計.md 01_事業設計書.md
  python3 10_ChatGPT連携/ask_openai.py "..." --dry-run   # 送信せず内容と文字数だけ確認

環境変数: OPENAI_API_KEY(必須) / OPENAI_MODEL(既定 gpt-4o)
"""
import argparse, json, os, sys, urllib.request, urllib.error
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

p = argparse.ArgumentParser()
p.add_argument("request", help="ChatGPTへの依頼内容")
p.add_argument("-f", "--files", nargs="*", help="渡す資料(省略時は00〜09全部)")
p.add_argument("-t", "--theme", default="openai", help="ログのファイル名に使うテーマ")
p.add_argument("--dry-run", action="store_true")
a = p.parse_args()

files = [ROOT / n for n in a.files] if a.files else sorted(ROOT.glob("[0-9][0-9]_*.md"))
context = "\n\n".join(f"===== {f.name} =====\n{f.read_text(encoding='utf-8')}" for f in files)
model = os.environ.get("OPENAI_MODEL", "gpt-4o")

messages = [
    {"role": "system", "content": "あなたは事業企画の共同検討者です。以下の資料を前提に、日本語で具体的に回答してください。"},
    {"role": "user", "content": f"# 資料\n{context}\n\n# 依頼\n{a.request}"},
]

if a.dry_run:
    print(f"model={model} files={len(files)} chars={len(context):,}")
    sys.exit(0)

key = os.environ.get("OPENAI_API_KEY")
if not key:
    sys.exit("OPENAI_API_KEY が未設定です")

req = urllib.request.Request(
    "https://api.openai.com/v1/chat/completions",
    data=json.dumps({"model": model, "messages": messages}).encode(),
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
)
try:
    with urllib.request.urlopen(req, timeout=300) as r:
        answer = json.load(r)["choices"][0]["message"]["content"]
except urllib.error.HTTPError as e:
    sys.exit(f"APIエラー {e.code}: {e.read().decode()}")

out = HERE / "ログ" / f"{date.today()}_{a.theme}.md"
out.write_text(
    f"# 引き継ぎメモ: {a.theme}\n\n- 日付: {date.today()}\n- 方向: ChatGPT → Claude\n- 状態: 未反映\n"
    f"- 対象ファイル: {', '.join(f.name for f in files)}\n- モデル: {model}\n\n## 依頼\n{a.request}\n\n## 結論\n{answer}\n",
    encoding="utf-8",
)
print(f"保存: {out}")
