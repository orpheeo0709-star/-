#!/usr/bin/env python3
"""ZIP 切り分け監査(読み取り専用。元ZIP・既存の変換結果は変更しない)。

    py -I audit_zip.py --zip <ZIPのパス> [--out <ChatGPT_完全移行のパス>]

1. 方法A: zipfile で全エントリをCRC検証(壊れたエントリ名を全件列挙)
2. 方法B: zipfile非依存の順次読み(zipsalvage)。中央ディレクトリが無くても動く
3. 方法C: 外部ツール tar / 7z があれば一覧と終了コード
4. 既存の「添付と会話の対応表.json」があれば、未回収を ZIP内にある/ない に分類
結果は <out>\\検証結果\\ZIP監査_*.json に新規保存(既存ファイルは上書きしない)。
"""
import argparse, importlib.util, json, re, shutil, subprocess, sys, zipfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_salvage():
    spec = importlib.util.spec_from_file_location("zipsalvage", HERE / "zipsalvage.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def norm_id(s):
    return re.sub(r"^[\w\-]+://", "", s or "")


def core(s):
    return re.sub(r"^file[-_]", "", norm_id(s))


def method_a(p):
    r = {"ok_open": False, "entries": 0, "bad": [], "error": None, "names": []}
    try:
        with zipfile.ZipFile(p) as z:
            r["ok_open"] = True
            infos = z.infolist(); r["entries"] = len(infos); r["names"] = [i.filename for i in infos]
            for i in infos:
                if i.is_dir(): continue
                try:
                    with z.open(i) as fh:
                        while fh.read(1 << 20): pass
                except Exception as e:
                    r["bad"].append({"name": i.filename, "error": f"{type(e).__name__}: {e}"})
    except Exception as e:
        r["error"] = f"{type(e).__name__}: {e}"
    return r


def method_b(p):
    sv = load_salvage()
    ents, end = sv.walk(p)
    return {"end_reason": end, "entries_read": len(ents), "ok": sum(1 for e in ents if e["ok"]),
            "bad": [{"name": e["name"], "error": e["error"]} for e in ents if not e["ok"]],
            "last_entry": ents[-1]["name"] if ents else None, "names": [e["name"] for e in ents]}


def method_c(p):
    out = {}
    for tool, cmd in (("tar", ["tar", "-tf", str(p)]), ("7z", ["7z", "l", "-slt", str(p)])):
        if shutil.which(tool):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
                out[tool] = {"exit": r.returncode, "stdout_lines": len(r.stdout.splitlines()), "stderr": r.stderr[-500:]}
            except Exception as e:
                out[tool] = {"error": str(e)}
        else:
            out[tool] = "未インストール"
    return out


def classify(out_dir, names_all, bad_names):
    mp = out_dir / "添付ファイル回収分" / "添付と会話の対応表.json"
    if not mp.exists():
        return {"note": "対応表なし(未回収の分類は省略)"}
    refs = json.loads(mp.read_text("utf-8"))
    uniq = {}
    for r in refs:
        uniq.setdefault((r.get("file_id"), r.get("conversation_id")), r)
    base = {Path(n).name: n for n in names_all}
    res = {"参照(重複除去後)": len(uniq), "回収済み(既存結果)": 0, "ZIP内に存在(抽出失敗/照合失敗)": [], "ZIP内に存在しない": [], "ID不明": []}
    for (fid, cid), r in uniq.items():
        if r.get("recovered"): res["回収済み(既存結果)"] += 1; continue
        c = core(fid)
        if not fid or len(c) < 8: res["ID不明"].append({"name": r.get("name"), "conversation_id": cid}); continue
        hit = next((n for b, n in base.items() if c in b), None)
        if hit:
            res["ZIP内に存在(抽出失敗/照合失敗)"].append({"file_id": fid, "zip_entry": hit, "conversation_id": cid, "壊れたエントリ": hit in bad_names})
        else:
            res["ZIP内に存在しない"].append({"file_id": fid, "name": r.get("name"), "conversation_id": cid})
    res["件数"] = {k: (len(v) if isinstance(v, list) else v) for k, v in res.items()}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    p = Path(a.zip)
    A, B, C = method_a(p), method_b(p), method_c(p)
    names = set(A["names"]) | set(B["names"])
    bad = {b["name"] for b in A["bad"]} | {b["name"] for b in B["bad"]}
    rep = {"zip": str(p), "bytes": p.stat().st_size, "実行時刻": datetime.now().isoformat(),
           "A_zipfile": {k: v for k, v in A.items() if k != "names"},
           "B_順次読み": {k: v for k, v in B.items() if k != "names"}, "C_外部ツール": C}
    if A["ok_open"] and not A["bad"] and B["end_reason"] == "central_directory_reached" and not B["bad"]:
        rep["判定"] = "ZIPは正常(全エントリCRC一致・中央ディレクトリあり)"
    elif not A["ok_open"] and B["end_reason"] == "truncated":
        rep["判定"] = f"ZIP末尾が欠損(中央ディレクトリなし)。順次読みで {B['ok']} 件は正常、最後に読めたのは {B['last_entry']}"
    elif A["bad"] or B["bad"]:
        rep["判定"] = "一部エントリが破損(壊れたエントリ名は bad に列挙)"
    else:
        rep["判定"] = "判定保留(AとBの結果が食い違う。両方の詳細を確認)"
    if a.out:
        od = Path(a.out)
        rep["未回収の分類"] = classify(od, names, bad)
        d = od / "検証結果"; d.mkdir(parents=True, exist_ok=True)
        f = d / f"ZIP監査_{datetime.now():%Y%m%d_%H%M%S}.json"
        f.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print("保存:", f)
    print(json.dumps({k: v for k, v in rep.items() if k != "未回収の分類"}, ensure_ascii=False, indent=2))
    if "未回収の分類" in rep:
        print(json.dumps(rep["未回収の分類"].get("件数", rep["未回収の分類"]), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
