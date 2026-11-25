#!/usr/bin/env python3
"""SoDEX full-history klines puller (READ-ONLY, paginated).

Menarik SELURUH riwayat klines dari API publik SoDEX dengan memaginasi `endTime`
ke belakang (tiap halaman 1000 bar) sampai venue-birth atau halaman kosong.

Kenapa penting: venue lahir ~2025-10-12. API `limit=1000` tanpa paginasi hanya
memberi ~41 hari di interval 1h. Dengan paginasi endTime, seluruh ~360 hari 1h
tersedia -> memenuhi aturan riset "jendela < 6 bulan TIDAK SAH menilai alpha".

Output:
  data/sodex_klines/<interval>/<SYMBOL>.json   {"symbol","interval","n","oldest","newest","bars"}
  data/sodex_klines/<interval>/MANIFEST.json   ringkasan per simbol

Usage: python3 scripts/research/sodex_pull_klines_paged.py [interval] [symbols_csv|all]
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

B = "https://mainnet-gw.sodex.dev/api/v1/perps"
UA = {"User-Agent": "anantara-research/1.0 (read-only)"}
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
OUTBASE = os.path.join(ROOT, "data", "sodex_klines")

PAUSE = 0.45          # ~130 req/min; backoff on 429
MAX_PAGES = 12        # 12 x 1000 bar @1h = 500 hari (venue ~360 hari)


def fetch(url: str, tries: int = 4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(5.0 * (i + 1))
                continue
            time.sleep(1.5 * (i + 1))
        except Exception:  # noqa: BLE001
            time.sleep(1.5 * (i + 1))
    return None


SYMS_CACHE = os.path.join(OUTBASE, ".symbols.json")


def _symbols_from_api() -> list[str]:
    d = fetch(f"{B}/markets/symbols")
    if not d:
        return []
    syms: object = d.get("data")
    if not isinstance(syms, list):
        syms = d if isinstance(d, list) else []
    out = []
    for s in syms:
        if not isinstance(s, dict):
            continue
        nm = s.get("name") or s.get("symbol")  # API live memakai "name" (verifikasi 07-Okt-2026)
        st = s.get("status")
        if nm and (st is None or str(st).upper() == "TRADING"):
            out.append(nm)
    return sorted(out)


def trading_symbols() -> list[str]:
    """Universe simbol TRADING, dengan cache disk sebagai fallback.

    2026-11-01: unit menjalankan dua ExecStart berurutan (1h lalu 1d). Setelah
    tarikan 1h (~ribuan request), endpoint markets/symbols membalas kosong →
    tahap 1d gagal "no symbols" dan unit ditandai FAILED, padahal 1h sukses
    penuh 98/98. Universe tidak berubah dalam hitungan menit, jadi cache yang
    ditulis saat sukses adalah fallback yang jujur — bukan tebakan.
    Kalau API DAN cache sama-sama kosong, tetap return [] (gagal eksplisit).
    """
    out = _symbols_from_api()
    if out:
        try:
            os.makedirs(OUTBASE, exist_ok=True)
            tmp = SYMS_CACHE + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"utc": datetime.now(timezone.utc).isoformat(),
                           "symbols": out}, f)
            os.replace(tmp, SYMS_CACHE)
        except Exception as e:  # noqa: BLE001 — cache gagal tidak boleh hentikan pull
            print(f"[pull] PERINGATAN: cache simbol gagal ditulis ({e})", flush=True)
        return out
    try:
        with open(SYMS_CACHE) as f:
            cached = json.load(f).get("symbols") or []
    except Exception:  # noqa: BLE001
        cached = []
    if cached:
        print(f"[pull] FALLBACK: markets/symbols kosong — pakai cache "
              f"{len(cached)} simbol ({SYMS_CACHE})", flush=True)
        return sorted(cached)
    return []


def pull(symbol: str, interval: str) -> dict:
    end = int(time.time() * 1000)
    seen: dict[int, dict] = {}
    for _ in range(MAX_PAGES):
        d = fetch(f"{B}/markets/{symbol}/klines?interval={interval}&limit=1000&endTime={end}")
        if not d or d.get("code") != 0:
            break
        data = d.get("data") or []
        if not data:
            break
        for b in data:
            seen[b["t"]] = b
        oldest = min(b["t"] for b in data)
        end = oldest - 1
        time.sleep(PAUSE)
    bars = [seen[t] for t in sorted(seen)]
    return {
        "symbol": symbol,
        "interval": interval,
        "n": len(bars),
        "oldest": datetime.fromtimestamp(bars[0]["t"] / 1000, tz=timezone.utc).isoformat() if bars else None,
        "newest": datetime.fromtimestamp(bars[-1]["t"] / 1000, tz=timezone.utc).isoformat() if bars else None,
        "pulled_utc": datetime.now(timezone.utc).isoformat(),
        "bars": bars,
    }


def main() -> int:
    interval = sys.argv[1] if len(sys.argv) > 1 else "1h"
    sel = sys.argv[2] if len(sys.argv) > 2 else "all"
    outdir = os.path.join(OUTBASE, interval)
    os.makedirs(outdir, exist_ok=True)

    syms = trading_symbols() if sel == "all" else [s.strip() for s in sel.split(",") if s.strip()]
    if not syms:
        print("no symbols", flush=True)
        return 1
    print(f"[pull] interval={interval} symbols={len(syms)} out={outdir}", flush=True)

    manifest = []
    skipped = 0
    for i, s in enumerate(syms, 1):
        path = os.path.join(outdir, f"{s}.json")
        try:
            res = pull(s, interval)
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(syms)}] {s} FAIL {str(e)[:80]}", flush=True)
            continue
        if res["n"] <= 0:
            # JANGAN timpa data valid dengan hasil kosong: kegagalan upstream /
            # race pasca-boot (network belum siap) pernah mengosongkan 98/98 file.
            print(f"[{i}/{len(syms)}] {s} SKIP n=0 — file lama dipertahankan", flush=True)
            skipped += 1
            continue
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(res, f)
        os.replace(tmp, path)  # atomik: pembaca konkuren tak pernah lihat JSON terpotong
        manifest.append({k: res[k] for k in ("symbol", "n", "oldest", "newest")})
        if i % 5 == 0 or i == len(syms):
            print(f"[{i}/{len(syms)}] {s} n={res['n']} {res['oldest']} -> {res['newest']}", flush=True)

    mpath = os.path.join(outdir, "MANIFEST.json")
    with open(mpath + ".tmp", "w") as f:
        json.dump({"interval": interval, "pulled_utc": datetime.now(timezone.utc).isoformat(),
                   "n_symbols": len(manifest), "symbols": manifest}, f, indent=1)
    os.replace(mpath + ".tmp", mpath)  # atomik (idem)
    ok = [m for m in manifest if m["n"] > 0]
    print(f"[done] {len(ok)}/{len(manifest)} simbol punya bar "
          f"(skipped n=0: {skipped})", flush=True)
    if not ok:
        print(f"[ALERT] {interval}: 0 simbol dapat bar — dataset TIDAK disentuh, "
              f"cek koneksi/upstream", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
