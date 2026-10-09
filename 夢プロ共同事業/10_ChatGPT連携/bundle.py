#!/usr/bin/env python3
"""資料Markdownを1つのテキストに結合し、ChatGPTに貼り付けやすくする。"""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
names = sys.argv[1:]
files = [root / n for n in names] if names else sorted(root.glob("[0-9][0-9]_*.md"))

parts = []
for f in files:
    parts.append(f"===== {f.name} =====\n{f.read_text(encoding='utf-8')}")

out = Path(__file__).resolve().parent / "context_bundle.txt"
out.write_text("\n\n".join(parts), encoding="utf-8")
print(f"{len(files)}ファイル / {out.stat().st_size:,}バイト -> {out}")
