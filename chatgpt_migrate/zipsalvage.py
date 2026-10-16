"""ZIP を zipfile とは独立に先頭から順に読む(中央ディレクトリ不要)。
途中で切れたZIPでも、読めたところまでの名前・CRC検証・抽出ができる。元ZIPは読み取り専用で開く。
"""
import os, struct, zlib
from pathlib import Path


def _safe_rel(name):
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".", "..") and ":" not in p]
    return Path(*parts) if parts else None


def walk(path, out_dir=None, chunk=1 << 20):
    """戻り値: (entries, end_reason)
    entry: {name, method, offset, ok, error, bytes}
    end_reason: central_directory_reached / truncated / bad_signature / unsupported
    """
    entries, end = [], "truncated"
    with open(path, "rb") as f:
        pos = 0
        while True:
            f.seek(pos)
            h = f.read(30)
            if len(h) < 30:
                end = "truncated"; break
            if h[:4] in (b"PK\x01\x02", b"PK\x05\x06", b"PK\x06\x06"):
                end = "central_directory_reached"; break
            if h[:4] != b"PK\x03\x04":
                end = "bad_signature"; break
            _v, flags, method, _t, _d, crc, csz, usz, nl, el = struct.unpack("<HHHHHIIIHH", h[4:30])
            raw = f.read(nl)
            name = raw.decode("utf-8" if flags & 0x800 else "cp437", "replace")
            extra = f.read(el)
            z64 = False
            i = 0
            while i + 4 <= len(extra):
                tid, tsz = struct.unpack("<HH", extra[i:i + 4])
                if tid == 1:
                    body, j = extra[i + 4:i + 4 + tsz], 0
                    if usz == 0xFFFFFFFF and len(body) >= j + 8: usz = struct.unpack("<Q", body[j:j + 8])[0]; j += 8; z64 = True
                    if csz == 0xFFFFFFFF and len(body) >= j + 8: csz = struct.unpack("<Q", body[j:j + 8])[0]; z64 = True
                i += 4 + tsz
            ent = {"name": name, "method": method, "offset": pos, "ok": False, "error": None, "bytes": 0}
            entries.append(ent)
            isdir = name.endswith("/")
            out = None
            try:
                if out_dir and not isdir:
                    rel = _safe_rel(name)
                    if rel is not None:
                        target = Path(out_dir) / rel
                        target.parent.mkdir(parents=True, exist_ok=True)
                        out = open(target, "wb")
                c = 0
                if method == 8:
                    d = zlib.decompressobj(-15)
                    used = 0
                    while not d.eof:
                        n = chunk if flags & 8 else min(chunk, csz - used)
                        buf = f.read(n) if n > 0 else b""
                        if not buf:
                            raise EOFError("ZIPが途中で切れています(データ終端なし)")
                        used += len(buf)
                        data = d.decompress(buf)
                        c = zlib.crc32(data, c); ent["bytes"] += len(data)
                        if out: out.write(data)
                    endpos = f.tell() - len(d.unused_data)
                elif method == 0:
                    if flags & 8 and csz == 0:
                        end = "unsupported"; raise ValueError("未圧縮+データ記述子は順次読み不可")
                    left = csz
                    while left > 0:
                        buf = f.read(min(chunk, left))
                        if not buf: raise EOFError("ZIPが途中で切れています(データ不足)")
                        left -= len(buf); c = zlib.crc32(buf, c); ent["bytes"] += len(buf)
                        if out: out.write(buf)
                    endpos = f.tell()
                else:
                    end = "unsupported"; raise ValueError(f"未対応の圧縮方式 {method}")
                if flags & 8:
                    f.seek(endpos); d4 = f.read(4)
                    if d4 == b"PK\x07\x08": d4 = f.read(4)
                    want = struct.unpack("<I", d4)[0] if len(d4) == 4 else None
                    f.read(16 if z64 else 8)
                    endpos = f.tell()
                else:
                    want = crc
                if want is not None and want != c:
                    ent["error"] = f"CRC不一致(期待 {want:08x} / 実際 {c:08x})"
                else:
                    ent["ok"] = True
                pos = endpos
            except Exception as e:
                ent["error"] = f"{type(e).__name__}: {e}"
                if out: out.close(); out = None
                if out_dir and not isdir and _safe_rel(name) is not None:
                    try: (Path(out_dir) / _safe_rel(name)).unlink()
                    except OSError: pass
                if not isinstance(e, ValueError) or end != "unsupported":
                    end = end if end == "unsupported" else "truncated"
                break
            finally:
                if out: out.close()
            if ent["error"] and not ent["ok"] and out_dir:  # CRC不一致は不完全ファイルとして残さない
                rel = _safe_rel(name)
                if rel is not None:
                    try: (Path(out_dir) / rel).unlink()
                    except OSError: pass
    return entries, end
