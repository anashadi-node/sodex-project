#!/usr/bin/env python3
"""Sidik-jari (fingerprint) + pembekuan snapshot data klines.

ALASAN: data/sodex_klines ditulis ulang berkala oleh armada service (realsync tiap ~2 menit,
puller per jam). Skrip riset yang membaca langsung mendapat panel BERGERAK -> angka tidak
reproducible (terbukti: -MOM_L21 H24 bergeser +18,9 -> +8,2 bps antar-run tanpa perubahan kode).

ATURAN: setiap skrip riset WAJIB memanggil fingerprint(interval) dan menuliskan hasilnya ke
JSON keluarannya. Untuk hasil yang harus dibekukan, pakai --freeze DIR lalu muat dari DIR itu.

Pakai:
  /usr/bin/python3 scripts/research/klines_snapshot.py 1h            # cetak + tulis sidik-jari
  /usr/bin/python3 scripts/research/klines_snapshot.py 1h --freeze   # + salin ke data/snapshots/
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "reports", "sodex", "PANEL_FINGERPRINT.json")


def fingerprint(interval: str = "1h") -> dict:
    """Sidik-jari ringkas & murah untuk satu direktori klines (aman dipanggil tiap run)."""
    d = os.path.join(ROOT, "data", "sodex_klines", interval)
    fp: dict = {"interval": interval, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if not os.path.isdir(d):
        return {**fp, "error": "direktori tidak ada"}
    files = sorted(f for f in os.listdir(d) if f.endswith(".json"))
    fp["n_files"] = len(files)
    blobs = []
    for f in files:
        st = os.stat(os.path.join(d, f))
        blobs.append((f, st.st_size, int(st.st_mtime)))
    fp["total_bytes"] = sum(b[1] for b in blobs)
    fp["mtime_max_u64"] = max(b[2] for b in blobs)
    fp["mtime_max"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(fp["mtime_max_u64"]))
    man = os.path.join(d, "MANIFEST.json")
    if os.path.exists(man):
        with open(man, "rb") as fh:
            raw = fh.read()
        fp["manifest_sha256_16"] = hashlib.sha256(raw).hexdigest()[:16]
        fp["manifest_bytes"] = len(raw)
        try:
            m = json.loads(raw)
            fp["manifest_pulled_utc"] = m.get("pulled_utc") or m.get("pulled")
            if isinstance(m.get("symbols"), list):
                fp["manifest_n_symbols"] = len(m["symbols"])
        except Exception as e:  # pragma: no cover
            fp["manifest_parse_error"] = str(e)[:80]
    # sampel 6 berkas terbesar -> rentang waktu & n bar
    top = sorted((b for b in blobs if b[1] > 20000), key=lambda b: -b[1])[:6]
    samp = []
    for f, _, _ in top:
        try:
            dd = json.load(open(os.path.join(d, f)))
            samp.append({"f": f[:-5], "n": dd.get("n"), "oldest": dd.get("oldest"),
                         "newest": dd.get("newest")})
        except Exception:
            pass
    fp["sampel"] = samp
    if samp:
        fp["newest_di_sampel"] = max((s["newest"] or "") for s in samp)
        fp["oldest_di_sampel"] = min((s["oldest"] or "9999") for s in samp)
    # hash isi 6 berkas terbesar (deteksi perubahan isi, bukan hanya mtime)
    h = hashlib.sha256()
    for f, sz, mtn in top:
        h.update(f.encode())
        h.update(str(sz).encode())
    fp["content_sha256_16"] = h.hexdigest()[:16]
    return fp


def freeze(interval: str, dest: str | None = None) -> str:
    """Salin seluruh direktori klines ke snapshot berstempel waktu (opt-in, untuk hasil beku)."""
    src = os.path.join(ROOT, "data", "sodex_klines", interval)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    dest = dest or os.path.join(ROOT, "data", "snapshots", f"sodex_klines_{interval}_{stamp}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copytree(src, dest, dirs_exist_ok=True)
    with open(os.path.join(dest, "_FINGERPRINT.json"), "w") as f:
        json.dump(fingerprint(interval), f, indent=1)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("interval", nargs="?", default="1h")
    ap.add_argument("--freeze", action="store_true")
    a = ap.parse_args()
    fp = fingerprint(a.interval)
    print(json.dumps(fp, indent=1))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    hist = []
    if os.path.exists(OUT):
        try:
            hist = json.load(open(OUT))
        except Exception:
            hist = []
    hist = (hist if isinstance(hist, list) else [hist])[-49:] + [fp]
    with open(OUT, "w") as f:
        json.dump(hist, f, indent=1)
    print(f"[ditulis] {OUT} (riwayat {len(hist)})")
    if a.freeze:
        print("[freeze] " + freeze(a.interval))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
