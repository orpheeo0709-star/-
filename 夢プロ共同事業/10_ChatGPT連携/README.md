# Claude ⇄ ChatGPT 橋渡し運用

ClaudeとChatGPTは直接会話できないため、このリポジトリを「共通のメモ置き場」にして引き継ぎます。

## Claude → ChatGPT
1. `python3 10_ChatGPT連携/bundle.py` を実行 → `10_ChatGPT連携/context_bundle.txt` が生成される
   （`00`〜`09`のMarkdownを1ファイルに結合。特定ファイルだけなら引数で指定: `python3 10_ChatGPT連携/bundle.py 01_事業設計書.md 04_90日実行計画.md`）
2. 中身をChatGPTに貼り付け（または添付）し、`handoff_template.md` の「依頼」を添えて質問する

## ChatGPT → Claude
1. ChatGPTでの結論・修正案を `ログ/YYYY-MM-DD_テーマ.md` にコピーして保存（`handoff_template.md` の形式）
2. コミットしてClaudeに「`ログ/〜` を反映して」と依頼 → Claudeが本体資料へ反映

## 運用ルール
- 本体資料（`00`〜`09`）が正。ChatGPTの出力は必ず`ログ/`経由で取り込む
- 料金・個人名など機密性のある内容は、ChatGPTに渡す前に確認する
- 取り込み後はログ冒頭の「状態」を `反映済み` に更新する
