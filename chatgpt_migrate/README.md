# ChatGPT 完全移行ツール

Windows (Python 3.8+, 標準ライブラリのみ) で実行。元の JSON/ZIP は読み取り専用で、変更しません。

```
py -I migrate.py                 # 全工程(verify→split→classify→extract→memory→attachments→outputs→validate)
py -I migrate.py --stage split   # 単独工程
py -I migrate.py --force         # 完了済み工程も再実行
py -I migrate.py --downloads D:\path
```
- 出力: `<Downloads>\ChatGPT_完全移行\`。進捗は `_work\state.json`(中断しても再実行で続きから)。
- 対象は Downloads 直下の `conversations*.json` と名前に chatgpt/openai/export を含む ZIP のみ。
- AI向けファイルは機密パターンを除去(値は記録せず `機密情報検出レポート.json` に場所のみ)。`全会話_分割`・`プロジェクト別`の会話mdは原文のままなので、外部へ渡さないこと。
- 制約: メモリ・プロジェクト指示はエクスポートに含まれず自動復元不可。プロジェクト名もJSONにはIDのみ。`不足データ一覧.md` に出力。
