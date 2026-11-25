"""Discovery: format & cakupan sumber data untuk prediktor REZIM ex-ante (Opsi 2).

MENGAPA BERKAS INI ADA
----------------------
D07 membuktikan: edge `twoway` LONG bukan alpha, melainkan eksposur faktor
"alt mengalahkan BTC". Edge itu HIDUP di satu jendela (04-19 Sep) dan MATI di
periode terkini. Filter entry tidak menolong (12 diuji, 0 layak).

Opsi 2 = jangan saring ENTRY-nya; saring REZIM-nya. Cari pengukur yang tersedia
SEBELUM trade dibuka (ex-ante) yang bisa membedakan "rezim alt-menang" dari
"rezim alt-kalah". Kalau ada, strategi ini bisa DI-GATE (bukan di-filter) dan
kita berhenti trading saat rezim tidak mendukung.

Berkas ini hanya DISCOVERY -- memastikan format/cakupan data benar sebelum
studi prediktor ditulis. Read-only.
"""
from __future__ import annotations

import collections
import datetime as dt
import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fmt(ms: int) -> str:
    # trail_lab menyimpan epoch MILIDETIK
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


def main() -> int:
    os.chdir(ROOT)

    print("=" * 74)
    print("1. trail_lab_klines -- kline ALT 15m")
    print("=" * 74)
    fs = glob.glob("data/trail_lab_klines/*.json")
    sym: dict[str, list[str]] = collections.defaultdict(list)
    for f in fs:
        m = re.match(r"([A-Z0-9]+USDT)_15m_(\d+)_(\d+)\.json", os.path.basename(f))
        if m:
            sym[m.group(1)].append(os.path.basename(f))
    print(f"   simbol: {len(sym)}  berkas: {len(fs)}")
    untuk = sorted(sym)
    print(f"   daftar: {untuk}")

    # ambil rentang waktu gabungan dari semua berkas
    lo: int | None = None
    hi: int | None = None
    n_bar_total = 0
    for f in fs:
        try:
            d = json.load(open(f))
            t = d.get("t") or []
            if not t:
                continue
            n_bar_total += len(t)
            lo = t[0] if lo is None else min(lo, t[0])
            hi = t[-1] if hi is None else max(hi, t[-1])
        except Exception:
            pass
    print(f"   bar 15m total: {n_bar_total}")
    print(f"   rentang      : {fmt(lo)}  ->  {fmt(hi)}  (UTC)")

    # struktur satu berkas
    contoh = max(fs, key=os.path.getsize)
    d = json.load(open(contoh))
    print(f"   contoh       : {os.path.basename(contoh)}")
    print(f"     kunci={list(d.keys())}  panjang t={len(d['t'])}")
    print(f"     t[0]={d['t'][0]} = {fmt(d['t'][0])}   c[0]={d['c'][0]}")

    print()
    print("=" * 74)
    print("2. sodex_market_scan/history.jsonl -- scan pasar periodik")
    print("=" * 74)
    p = "data/sodex_market_scan/history.jsonl"
    n = 0
    ts_awal = ts_akhir = None
    kunci_short = None
    contoh_gain = None
    with open(p) as fh:
        for line in fh:
            n += 1
            try:
                r = json.loads(line)
            except Exception:
                continue
            ts = r.get("ts")
            if ts is not None:
                if ts_awal is None:
                    ts_awal = ts
                ts_akhir = ts
            if kunci_short is None and r.get("short_watch"):
                kunci_short = list(r["short_watch"][0].keys())
            if contoh_gain is None and r.get("top_gainers"):
                contoh_gain = r["top_gainers"][0]
    print(f"   baris        : {n}")
    print(f"   kunci/baris  : counts, short_watch, top_gainers, top_losers, ts")
    print(f"   ts awal      : {ts_awal}")
    print(f"   ts akhir     : {ts_akhir}")
    print(f"   kunci market : {kunci_short}")
    print(f"   contoh gainer: {json.dumps(contoh_gain, ensure_ascii=False)[:220]}")

    print()
    print("=" * 74)
    print("3. Kesiapan prediktor EX-ANTE")
    print("=" * 74)
    print("   Yang tersedia SEBELUM trade dibuka (syarat ex-ante):")
    print("     a. Kline alt 15m        -> kekuatan relatif alt vs BTC (trailing)")
    print("     b. BTC 1h (cache)       -> tren & volatilitas BTC")
    print("     c. market_scan top_gainers/losers -> BREADTH pasar")
    print("     d. funding_rate per pasar          -> posisi kerumunan")
    print("     e. conviction (0,60-0,80) pada trade itu sendiri")
    print("   Yang TIDAK bisa dipakai:")
    print("     - atr_pct  : 0.000 di SEMUA baris (field rusak)")
    print("     - regime   : 'MOMENTUM' di SEMUA baris (konstan, bukan filter)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
