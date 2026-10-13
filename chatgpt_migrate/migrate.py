#!/usr/bin/env python3
"""ChatGPT エクスポート完全移行ツール(標準ライブラリのみ / 再開可能)

使い方 (Windows):
    py -I migrate.py            # Downloads を自動探索して全工程を実行
    py -I migrate.py --stage verify
    py -I migrate.py --downloads D:\\path --force   # 完了済み工程も再実行

原則: 元の JSON/ZIP は読み取り専用。出力は <Downloads>/ChatGPT_完全移行 のみ。
表示ラベル: [原文]=エクスポートそのまま / [要約]=機械的抽出 / [推測]=ヒューリスティック
"""
import argparse, hashlib, json, re, shutil, sys, zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

STAGES = ["verify", "split", "classify", "extract", "memory", "attachments", "outputs", "validate"]
OUT_NAME = "ChatGPT_完全移行"
SECRET_PATTERNS = [
    ("APIキー(sk-)", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")),
    ("AWSアクセスキー", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHubトークン", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("Googleキー", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("秘密鍵", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("パスワード記述", re.compile(r"(?i)(password|passwd|パスワード|暗証番号|pin)\s*[:=:は]\s*\S+")),
    ("カード番号様", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("口座番号記述", re.compile(r"(口座番号|account\s*(no|number))\s*[:=:は]?\s*\d{6,}")),
]
TODO_RE = re.compile(r"(TODO|未完|未対応|次回|宿題|やること|タスク|期限|締切|〆|要確認|確認事項|決定|決まっ|方針)")
DECISION_RE = re.compile(r"(決定|決まり|決めた|確定|合意|方針)")


def ts(x):
    try:
        return datetime.fromtimestamp(float(x), tz=timezone.utc).isoformat()
    except Exception:
        return None


def safe_name(s, n=60):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", (s or "無題").strip())
    return s[:n].rstrip(". ") or "無題"


def jdump(p, o):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


class Ctx:
    def __init__(self, dl, out):
        self.dl, self.out = Path(dl), Path(out)
        self.state_p = self.out / "_work" / "state.json"
        self.state = json.loads(self.state_p.read_text("utf-8")) if self.state_p.exists() else {"done": {}}
        self.missing = []  # 不足データ一覧

    def save(self):
        jdump(self.state_p, self.state)

    def miss(self, kind, detail):
        self.missing.append({"種別": kind, "内容": detail})

    def sources(self):
        return self.state.get("sources", {})


# ---------- 1. verify ----------
def stage_verify(c):
    """Downloads 直下の conversations*.json と エクスポートZIP だけを対象にする(他は読まない)。"""
    cands = [p for p in c.dl.glob("*") if p.is_file() and (
        re.fullmatch(r"conversations.*\.json", p.name, re.I) or
        (p.suffix.lower() == ".zip" and re.search(r"chatgpt|openai|conversations|export", p.name, re.I)))]
    rep = {"files": [], "json": None, "zips": []}
    for p in sorted(cands):
        rep["files"].append({"path": str(p), "bytes": p.stat().st_size, "sha256": sha256(p)})
    jsons = [Path(f["path"]) for f in rep["files"] if f["path"].lower().endswith(".json")]
    zips = [Path(f["path"]) for f in rep["files"] if f["path"].lower().endswith(".zip")]
    src = {"json": None, "zips": [str(z) for z in zips]}
    for z in zips:
        info = {"path": str(z), "ok": False}
        try:
            with zipfile.ZipFile(z) as zf:
                bad = zf.testzip()
                info.update(ok=bad is None, first_bad=bad, entries=len(zf.namelist()),
                            has_conversations=any(n.endswith("conversations.json") for n in zf.namelist()))
        except Exception as e:
            info["error"] = f"{type(e).__name__}: {e}"
            c.miss("ZIP破損", f"{z.name}: {info['error']}(添付ファイル回収に影響)")
        rep["zips"].append(info)
    best = None
    for j in jsons:
        try:
            data = json.loads(j.read_text("utf-8"))
            ok = isinstance(data, list)
            rep["json"] = {"path": str(j), "valid": ok, "conversations": len(data) if ok else None}
            if ok and (best is None or len(data) > best[1]):
                best = (j, len(data))
        except Exception as e:
            rep["json"] = {"path": str(j), "valid": False, "error": f"{type(e).__name__}: {e}"}
            c.miss("JSON破損", f"{j.name}: {e}")
    if best is None:  # ZIP 内から救出(ZIP自体は変更しない)
        for z in zips:
            try:
                with zipfile.ZipFile(z) as zf:
                    for n in zf.namelist():
                        if n.endswith("conversations.json"):
                            dst = c.out / "_work" / "conversations_from_zip.json"
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            with zf.open(n) as a, open(dst, "wb") as b:
                                shutil.copyfileobj(a, b)
                            json.loads(dst.read_text("utf-8"))
                            best = (dst, 0)
            except Exception as e:
                c.miss("ZIP内JSON救出失敗", f"{z.name}: {e}")
    if best is None:
        jdump(c.out / "検証結果" / "00_元ファイル検証.json", rep)
        raise SystemExit("有効な conversations.json が見つかりません。検証結果を確認してください。")
    src["json"] = str(best[0])
    c.state["sources"] = src
    jdump(c.out / "検証結果" / "00_元ファイル検証.json", rep)


# ---------- 2. split ----------
def linearize(conv):
    """mapping を current_node から親を辿って時系列メッセージ列にする。分岐の別枝は branches に記録。"""
    mp = conv.get("mapping") or {}
    node, chain = conv.get("current_node"), []
    seen = set()
    while node and node in mp and node not in seen:
        seen.add(node); chain.append(mp[node]); node = mp[node].get("parent")
    chain.reverse()
    msgs = []
    for n in chain:
        m = n.get("message")
        if not m:
            continue
        msgs.append(m)
    unused = len([k for k, v in mp.items() if k not in seen and v.get("message")])
    return msgs, unused


def msg_text(m):
    cont = m.get("content") or {}
    t = cont.get("content_type")
    parts = cont.get("parts")
    out = []
    if parts:
        for p in parts:
            if isinstance(p, str):
                out.append(p)
            elif isinstance(p, dict):
                out.append(p.get("text") or f"[{p.get('content_type', 'object')}:{(p.get('asset_pointer') or '')}]")
    elif cont.get("text"):
        out.append(cont["text"])
    elif t == "user_editable_context":
        out.append(f"[カスタム指示] about_user={cont.get('user_profile','')}\nabout_model={cont.get('user_instructions','')}")
    return "\n".join(x for x in out if x), t


def stage_split(c):
    data = json.loads(Path(c.sources()["json"]).read_text("utf-8"))
    d = c.out / "全会話_分割"
    ids, dup, empty, rows = Counter(), [], [], []
    for i, conv in enumerate(data):
        cid = conv.get("conversation_id") or conv.get("id") or f"noid_{i}"
        ids[cid] += 1
        if ids[cid] > 1:
            dup.append(cid)
        msgs, unused = linearize(conv)
        lines, nmsg = [], 0
        for m in msgs:
            role = (m.get("author") or {}).get("role")
            txt, ctype = msg_text(m)
            if role == "system" and not txt:
                continue
            nmsg += 1
            lines.append(f"### {role} ({ts(m.get('create_time')) or '時刻不明'}) [原文]\n\n{txt}\n")
        if nmsg == 0:
            empty.append(cid)
        base = f"{ts(conv.get('create_time'))[:10] if conv.get('create_time') else '日付不明'}_{safe_name(conv.get('title'))}_{cid[:8]}"
        meta = {"conversation_id": cid, "title": conv.get("title"), "create_time": ts(conv.get("create_time")),
                "update_time": ts(conv.get("update_time")), "gizmo_id": conv.get("gizmo_id"),
                "project_id": conv.get("project_id") or conv.get("conversation_template_id"),
                "message_count": nmsg, "unlinearized_branch_messages": unused, "file": base}
        jdump(d / "json" / f"{base}.json", {"meta": meta, "raw": conv})
        (d / "md").mkdir(parents=True, exist_ok=True)
        (d / "md" / f"{base}.md").write_text(f"# {conv.get('title') or '無題'}\n\n- ID: {cid}\n- 作成: {meta['create_time']}\n\n" + "\n".join(lines), encoding="utf-8")
        rows.append(meta)
    times = [r["create_time"] for r in rows if r["create_time"]]
    jdump(d / "index.json", rows)
    jdump(c.out / "検証結果" / "01_分割統計.json", {
        "総会話数": len(data), "出力ファイル数": len(rows), "期間": [min(times), max(times)] if times else None,
        "重複ID": dup, "メッセージ0件の会話": empty,
        "分岐で本線外になったメッセージ総数": sum(r["unlinearized_branch_messages"] for r in rows)})
    if empty: c.miss("空会話", f"{len(empty)}件(メッセージ本文なし)")
    if dup: c.miss("重複会話ID", f"{len(dup)}件")


# ---------- 3. classify ----------
def stage_classify(c):
    """project_id/gizmo_id で分類。名前の自動統合はしない。不明は『未分類』。"""
    idx = json.loads((c.out / "全会話_分割" / "index.json").read_text("utf-8"))
    groups = defaultdict(list)
    for r in idx:
        key = r["project_id"] or r["gizmo_id"]
        groups[("ID:" + key) if key else "未分類"].append(r)
    d = c.out / "プロジェクト別"
    listing = []
    for k, rows in groups.items():
        pn = safe_name(k, 50)
        for r in rows:
            (d / pn).mkdir(parents=True, exist_ok=True)
            src = c.out / "全会話_分割" / "md" / f"{r['file']}.md"
            shutil.copyfile(src, d / pn / src.name)
        listing.append({"プロジェクト": k, "会話数": len(rows), "フォルダ": pn,
                        "根拠": "[原文] エクスポート内のID" if k != "未分類" else "[推測不可] IDなし"})
    jdump(c.out / "全プロジェクト一覧.json", listing)
    md = ["# 全プロジェクト一覧\n", "| プロジェクト(ID) | 会話数 | 根拠 |", "|---|---|---|"]
    md += [f"| {x['プロジェクト']} | {x['会話数']} | {x['根拠']} |" for x in sorted(listing, key=lambda x: -x["会話数"])]
    md.append("\n注意: プロジェクト名はconversations.jsonに含まれません。IDと実名の対応は手動確認が必要です。")
    (c.out / "全プロジェクト一覧.md").write_text("\n".join(md), encoding="utf-8")
    c.miss("プロジェクト名", "エクスポートにはプロジェクト名が含まれない。ID↔名称の対応表を手動で作成してください")
    if set(groups) == {"未分類"}:
        c.miss("プロジェクト分類", "全会話が未分類(project_id/gizmo_idなし)。タイトルのキーワードによる分類は手動で。")


# ---------- 4. extract ----------
def stage_extract(c):
    """プロジェクトごとに抽出メモを作成。[原文]=該当行そのまま、[推測]=パターン一致のみ。"""
    idx = json.loads((c.out / "全会話_分割" / "index.json").read_text("utf-8"))
    by = defaultdict(list)
    for r in idx:
        by[r["project_id"] or r["gizmo_id"] or "未分類"].append(r)
    people = Counter()
    for k, rows in by.items():
        todos, decisions, first_user = [], [], []
        for r in rows:
            raw = json.loads((c.out / "全会話_分割" / "json" / f"{r['file']}.json").read_text("utf-8"))["raw"]
            msgs, _ = linearize(raw)
            for m in msgs:
                role = (m.get("author") or {}).get("role")
                txt, _ = msg_text(m)
                for ln in txt.splitlines():
                    ln = ln.strip()
                    if 6 < len(ln) < 200 and TODO_RE.search(ln):
                        (decisions if DECISION_RE.search(ln) else todos).append(f"{r['title']}: {ln}")
                    if role == "user":
                        for nm in re.findall(r"([^\s、。「」()()]{1,6}(?:さん|様|氏|社長|部長))", ln):
                            people[nm] += 1
            first_user.append(f"- {r['title']} ({r['create_time']})")
        out = [f"# プロジェクト抽出メモ: {k}\n", f"会話数: {len(rows)}\n",
               "## 会話一覧 [要約:機械的]", *first_user[:200],
               "\n## 決定事項候補 [推測:キーワード一致の原文行]", *[f"- {x}" for x in decisions[:100]],
               "\n## 未完了/要確認候補 [推測:キーワード一致の原文行]", *[f"- {x}" for x in todos[:100]],
               "\n※目的・経緯・担当・進捗の確定的な整理は機械抽出できません。このメモを元にAIへ小分けで渡して整理してください。"]
        p = c.out / "プロジェクト別" / safe_name("ID:" + k if k != "未分類" else k, 50)
        p.mkdir(parents=True, exist_ok=True)
        (p / "_抽出メモ.md").write_text(redact("\n".join(out), [], "抽出メモ"), encoding="utf-8")
    pl = [{"表記": n, "出現回数": v, "種別": "[推測] 敬称パターン一致。同一人物の統合は未実施"} for n, v in people.most_common()]
    jdump(c.out / "人物・会社・関係者" / "人物候補.json", pl)
    (c.out / "人物・会社・関係者" / "README.md").write_text(
        "敬称(さん/様/氏/社長/部長)から機械抽出した候補のみ。会社名・関係性は未抽出。表記ゆれは統合していません。\n", encoding="utf-8")
    c.miss("会社名・関係者の関係性", "自動抽出対象外。人物候補を元に手動/AI補助で整理が必要")


# ---------- 5. memory ----------
def stage_memory(c):
    idx = json.loads((c.out / "全会話_分割" / "index.json").read_text("utf-8"))
    found, mem = [], []
    for r in idx:
        raw = json.loads((c.out / "全会話_分割" / "json" / f"{r['file']}.json").read_text("utf-8"))["raw"]
        for n in (raw.get("mapping") or {}).values():
            m = n.get("message")
            if not m: continue
            cont = m.get("content") or {}
            if cont.get("content_type") == "user_editable_context":
                found.append({"conversation": r["conversation_id"], "about_user": cont.get("user_profile"),
                              "about_model": cont.get("user_instructions")})
            txt, _ = msg_text(m)
            if (m.get("author") or {}).get("role") == "tool" and "memory" in str((m.get("author") or {}).get("name", "")).lower():
                mem.append({"conversation": r["conversation_id"], "text": txt})
    uniq = {json.dumps((f["about_user"], f["about_model"]), ensure_ascii=False): f for f in found}
    d = c.out / "メモリ・カスタム指示"
    jdump(d / "custom_instructions.json", list(uniq.values()))
    jdump(d / "memory_tool_traces.json", mem)
    lines = ["# カスタム指示 [原文: 会話内に記録されたもの]\n"]
    for f in uniq.values():
        lines += ["## 自分について", f["about_user"] or "(空)", "## 回答のしかた", f["about_model"] or "(空)", ""]
    (d / "custom_instructions.md").write_text("\n".join(lines), encoding="utf-8")
    if not uniq: c.miss("カスタム指示", "会話内に記録なし。ChatGPT設定画面から手動コピーが必要")
    c.miss("メモリ(保存された記憶)", "エクスポートに含まれない。設定>パーソナライズ>メモリ>管理 から手動コピー、またはChatGPTに『記憶している内容を全て列挙して』と依頼")
    c.miss("プロジェクト指示・プロジェクトファイル", "エクスポートに含まれない。ChatGPT各プロジェクトの設定画面から手動回収")


# ---------- 6. attachments ----------
def stage_attachments(c):
    idx = json.loads((c.out / "全会話_分割" / "index.json").read_text("utf-8"))
    refs = []  # (file_id, name, conversation_id)
    for r in idx:
        raw = json.loads((c.out / "全会話_分割" / "json" / f"{r['file']}.json").read_text("utf-8"))["raw"]
        for n in (raw.get("mapping") or {}).values():
            m = n.get("message")
            if not m: continue
            for a in (m.get("metadata") or {}).get("attachments", []) or []:
                refs.append((a.get("id"), a.get("name"), r["conversation_id"]))
            for p in (m.get("content") or {}).get("parts") or []:
                if isinstance(p, dict) and p.get("asset_pointer"):
                    refs.append((re.sub(r"^\w+://", "", p["asset_pointer"]), None, r["conversation_id"]))
    d = c.out / "添付ファイル回収分"
    d.mkdir(parents=True, exist_ok=True)
    recovered = {}
    for zp in c.sources().get("zips", []):
        try:
            with zipfile.ZipFile(zp) as zf:
                for info in zf.infolist():
                    if info.is_dir() or info.filename.endswith("conversations.json"): continue
                    target = (d / "files" / Path(info.filename).name)
                    if ".." in info.filename.split("/"): continue  # zip slip 対策
                    try:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as a, open(target, "wb") as b:
                            shutil.copyfileobj(a, b)
                        recovered[Path(info.filename).name] = str(target.relative_to(c.out))
                    except Exception as e:
                        c.miss("添付ファイル読出失敗", f"{info.filename}: {e}")
        except Exception as e:
            c.miss("ZIP読出失敗", f"{Path(zp).name}: {e}(破損箇所以降の添付は未回収)")
    mapping = []
    for fid, name, cid in refs:
        hit = next((v for k, v in recovered.items() if fid and fid in k), None)
        mapping.append({"file_id": fid, "name": name, "conversation_id": cid, "recovered": hit})
        if not hit: c.miss("添付ファイル未回収", f"{name or fid} (会話 {cid})")
    jdump(d / "添付と会話の対応表.json", mapping)
    jdump(d / "回収済みファイル一覧.json", recovered)


# ---------- 7. outputs ----------
def redact(text, hits, where):
    for label, rx in SECRET_PATTERNS:
        def sub(m):
            hits.append({"場所": where, "種別": label})  # 値は記録しない
            return f"[機密情報除去:{label}]"
        text = rx.sub(sub, text)
    return text


def stage_outputs(c):
    """AI向けファイルは機密パターンを除去。原本(全会話_分割)は無加工のまま。"""
    idx = json.loads((c.out / "全会話_分割" / "index.json").read_text("utf-8"))
    hits = []
    bundles = defaultdict(list)
    for r in idx:
        raw_md = (c.out / "全会話_分割" / "md" / f"{r['file']}.md").read_text("utf-8")
        key = r["project_id"] or r["gizmo_id"] or "未分類"
        bundles[key].append(redact(raw_md, hits, r["file"]))
    ci = (c.out / "メモリ・カスタム指示" / "custom_instructions.md").read_text("utf-8")
    ci = redact(ci, hits, "custom_instructions")

    def write_bundles(root, limit):
        for k, docs in bundles.items():
            part, size, n = [], 0, 1
            def flush():
                nonlocal part, size, n
                if part:
                    p = root / f"{safe_name(k, 40)}_{n:02d}.md"
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text("\n\n---\n\n".join(part), encoding="utf-8")
                    n += 1; part, size = [], 0
            for dmd in docs:
                if size + len(dmd) > limit: flush()
                part.append(dmd); size += len(dmd)
            flush()

    o = c.out
    # ChatGPT: 会話の自動インポート機能は無い。カスタム指示+過去会話アーカイブを新アカウントのプロジェクトファイルとして使う
    write_bundles(o / "ChatGPT移行用" / "プロジェクトファイル用", 400_000)
    (o / "ChatGPT移行用" / "カスタム指示_貼付用.md").write_text(ci, encoding="utf-8")
    (o / "ChatGPT移行用" / "README.md").write_text("会話の直接インポートはできません。プロジェクトを手動作成し、上記mdをプロジェクトファイルとして追加、カスタム指示は設定へ貼付。メモリは自動復元不可(新アカウントで手動入力)。\n", encoding="utf-8")
    # Claude: Projectの知識ファイル(分割)+ メモリ取り込み文
    write_bundles(o / "Claude移行用" / "プロジェクト知識ファイル", 300_000)
    (o / "Claude移行用" / "プロジェクト指示_貼付用.md").write_text(ci, encoding="utf-8")
    (o / "Claude移行用" / "メモリ取込用.md").write_text("# メモリ取込用 [原文: カスタム指示のみ]\n\n" + ci + "\n\n※ChatGPTのメモリは別途手動回収後に追記。", encoding="utf-8")
    # Gemini: Gem指示(長さ制限が小さい)+ 知識ファイル
    write_bundles(o / "Gemini移行用" / "Gem知識ファイル", 250_000)
    (o / "Gemini移行用" / "Gem指示_貼付用.md").write_text(ci[:8000], encoding="utf-8")
    jdump(o / "機密情報検出レポート.json", {"注意": "値は記録していません。原本側で該当箇所を確認してください", "検出": hits, "件数": len(hits)})
    (o / "移行手順書.md").write_text(MANUAL, encoding="utf-8")
    if hits: c.miss("機密情報", f"{len(hits)}箇所を移行用ファイルから除去(原本は保持)。移行方法は別途ご判断ください")


MANUAL = """# 移行手順書
注意: 外部サービスへのアップロードは自動では行っていません。以下は全て手動です。

## 共通
1. `機密情報検出レポート.json` を確認(AI向けファイルでは該当部分を除去済み)。
2. `不足データ一覧.md` の項目(メモリ・プロジェクト指示等)を ChatGPT の設定画面から手動回収。

## 別のChatGPTアカウント
- 会話の自動インポート機能はありません(できると断言しません)。
- プロジェクトを手動作成 → `ChatGPT移行用/プロジェクトファイル用` を追加 → カスタム指示を貼付。

## Claude
- Projectを作成 → `Claude移行用/プロジェクト知識ファイル` を知識に追加 → 指示を貼付。
- 容量超過時はプロジェクト別に必要分のみ追加。

## Gemini
- Gemを作成 → `Gem指示_貼付用.md`(文字数制限で切り詰め済)→ 知識ファイルを追加(上限に注意)。
"""


# ---------- 8. validate ----------
def stage_validate(c):
    idx = json.loads((c.out / "全会話_分割" / "index.json").read_text("utf-8"))
    n_json = len(list((c.out / "全会話_分割" / "json").glob("*.json")))
    n_md = len(list((c.out / "全会話_分割" / "md").glob("*.md")))
    classified = sum(1 for r in idx if r["project_id"] or r["gizmo_id"])
    pf = sum(len(list(p.glob("*.md"))) for p in [c.out / "プロジェクト別"] for p in p.glob("*")) if (c.out / "プロジェクト別").exists() else 0
    total_in = json.loads((c.out / "検証結果" / "01_分割統計.json").read_text("utf-8"))["総会話数"]
    # 内容照合: 各AI向けmdに全会話IDが含まれるか(機密除去前提でIDは残る)
    ids = {r["conversation_id"] for r in idx}
    for name in ["ChatGPT移行用", "Claude移行用", "Gemini移行用"]:
        txt = "".join(p.read_text("utf-8") for p in (c.out / name).rglob("*.md"))
        absent = [i for i in ids if i not in txt]
        c.state.setdefault("recon", {})[name] = {"欠落会話ID": len(absent)}
        if absent: c.miss(f"{name} 移行漏れ", f"{len(absent)}件")
    ok = total_in == len(idx) == n_json == n_md
    rep = ["# 検証結果報告書\n",
           f"- 元の会話数: {total_in}", f"- 分割JSON: {n_json} / 分割MD: {n_md}",
           f"- ID根拠で分類できた会話: {classified} / 未分類: {len(idx)-classified}",
           f"- 件数照合: {'一致' if ok else '不一致'}", "", "## AI別 移行漏れ照合", json.dumps(c.state["recon"], ensure_ascii=False, indent=2),
           "", "## ラベル凡例", "[原文]エクスポートそのまま / [要約]機械的抽出 / [推測]パターン一致", "",
           "## できないこと", "- メモリ・プロジェクト指示の自動復元 / 会話のワンクリックインポート / 名前の自動統合"]
    (c.out / "検証結果" / "検証結果報告書.md").write_text("\n".join(rep), encoding="utf-8")
    # 不足一覧(前回分とマージして重複排除)
    allm = c.state.get("missing", []) + c.missing
    seen, uniq = set(), []
    for m in allm:
        k = json.dumps(m, ensure_ascii=False)
        if k not in seen: seen.add(k); uniq.append(m)
    c.state["missing"] = uniq
    md = ["# 不足データ一覧\n"] + [f"- **{m['種別']}**: {m['内容']}" for m in uniq]
    (c.out / "不足データ一覧.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(rep))


FUNCS = dict(verify=stage_verify, split=stage_split, classify=stage_classify, extract=stage_extract,
             memory=stage_memory, attachments=stage_attachments, outputs=stage_outputs, validate=stage_validate)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--downloads", default=str(Path.home() / "Downloads"))
    ap.add_argument("--stage", choices=STAGES)
    ap.add_argument("--force", action="store_true", help="完了済み工程も再実行")
    a = ap.parse_args()
    dl = Path(a.downloads)
    out = dl / OUT_NAME
    out.mkdir(parents=True, exist_ok=True)
    c = Ctx(dl, out)
    todo = [a.stage] if a.stage else STAGES
    for s in todo:
        if c.state["done"].get(s) and not a.force and not a.stage:
            print(f"[skip] {s} (完了済み)"); continue
        print(f"[run ] {s}")
        n0 = len(c.missing)
        FUNCS[s](c)
        c.state["missing"] = c.state.get("missing", []) + c.missing[n0:] if s != "validate" else c.state.get("missing", [])
        c.state["done"][s] = datetime.now().isoformat()
        c.save()  # 工程ごとにチェックポイント
    print("完了:", out)


if __name__ == "__main__":
    main()
