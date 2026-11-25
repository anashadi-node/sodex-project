#!/usr/bin/env python3
"""Backfill klines SoDEX (READ-ONLY, GET publik) -- perluas riwayat riset.

Temuan 2026-10-07: endpoint klines menyediakan 1h & 1d sampai ~2025-10-12 (~12 bulan),
sementara hasil tape collector lama hanya mulai 2026-05-22 (3 simbol). Backfill ini menutup
lubang 7 bulan itu untuk SELURUH 92 pasar -- di VENUE ASLINYA, bukan proksi Binance.

Endpoint: GET {BASE}/markets/{sym}/klines?interval=&startTime=&endTime=&limit=
Respons  : {code, timestamp, data:[{t,o,h,l,c,v,q}, ...]}  -- URUT MENURUN (terbaru dulu)
Interval : 1h dan 1d (1m hanya beberapa hari terakhir; 5m/15m/30m lebih pendek dari 1h)

Keluar  : scratch/sodex_klines/{SYM}_{interval}.parquet   (ts, o,h,l,c,v,q)

JAMINAN KEAMANAN (READ-ONLY):
- Hanya GET endpoint publik. TANPA auth, TANPA jalur order, TANPA kredensial.
- Tidak menyentuh file produksi, tidak mengubah ambang, tidak commit apa pun.
- Fail-closed per simbol: bila satu chunk gagal, simbol itu dilewati & dicatat.

Pakai: python3 scripts/sodex_backfill_klines.py [--interval 1h] [--days 380]
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "scratch/sodex_klines"
BASE = "https://mainnet-gw.sodex.dev/api/v1/perps"
HDRS = {"User-Agent": "anantara-research/1.0"}
DATA_START = "2025-10-12"      # titik awal data venue (hasil probing)
PAUSE = 0.25                   # jeda antar-request (sopan, hindari rate-limit)
SCHEMA_COLS = ["t", "o", "h", "l", "c", "v", "q"]


def _get(url: str, tries: int = 3):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HDRS), timeout=30) as f:
                return json.loads(f.read())
        except Exception as e:                      # noqa: BLE001 - fail-closed
            last = e
            time.sleep(1.0 * (i + 1))
    raise last


def ms(datestr: str) -> int:
    return int(datetime.fromisoformat(datestr).replace(tzinfo=timezone.utc).timestamp() * 1000)


def symbols() -> list[str]:
    d = _get(f"{BASE}/markets/tickers")
    return sorted(m["symbol"] for m in (d.get("data") or []))


def fetch(sym: str, interval: str, t0: int, t1: int) -> list[dict]:
    url = (f"{BASE}/markets/{sym}/klines?interval={interval}"
           f"&startTime={t0}&endTime={t1}&limit=1500")
    d = _get(url)
    return d.get("data") or []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1h", choices=["1h", "1d", "30m", "15m", "5m"])
    ap.add_argument("--days", type=int, default=380)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    # Langkah paging HARUS <= jendela yang ditutup limit=1500 pada interval itu.
    # (Bug historis: 60*24*60*1000 = 1 HARI, bukan 60 hari -> 360 request/simbol.)
    STEP_DAYS = {"1h": 60, "30m": 30, "15m": 15, "5m": 5, "1d": 1500}
    step_ms = STEP_DAYS[a.interval] * 24 * 60 * 60 * 1000
    t_end = int(time.time() * 1000)
    t_start = ms(DATA_START)

    syms = symbols()
    print(f"{len(syms)} simbol | interval={a.interval} | {DATA_START} -> hari ini | "
          f"step={STEP_DAYS[a.interval]}h | 4 worker", flush=True)

    empty = 0
    rows: list[dict] = []

    def one(sym: str) -> dict:
        dest = OUT / f"{sym}_{a.interval}.parquet"
        if dest.exists():
            return {"sym": sym, "n": -1, "first": "skip", "last": "skip"}
        parts, t = [], t_start
        while t < t_end:
            try:
                parts.extend(fetch(sym, a.interval, t, min(t + step_ms, t_end)))
            except Exception as e:                                  # noqa: BLE001 - fail-closed
                print(f"  {sym}: chunk gagal {type(e).__name__} -> lewati simbol", flush=True)
                return {"sym": sym, "n": 0, "first": None, "last": None}
            t += step_ms
            time.sleep(PAUSE)
        if not parts:
            return {"sym": sym, "n": 0, "first": None, "last": None}
        df = pd.DataFrame(parts)[SCHEMA_COLS]
        # API mengembalikan harga sebagai STRING -> wajib dikonversi, kalau tidak semua
        # perhitungan return akan salah (atau meledak). Jangan dihapus.
        for col in ("o", "h", "l", "c", "v", "q"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["t"] = pd.to_numeric(df["t"], errors="coerce")
        df = df.dropna(subset=["t", "o", "h", "l", "c"])
        df["t"] = df["t"].astype("int64")
        df = df.drop_duplicates("t").sort_values("t")
        df["ts"] = (df["t"] // 1000).astype("int64")
        df = df[["ts", "o", "h", "l", "c", "v", "q"]]
        df.to_parquet(dest, compression="zstd", index=False)
        return {"sym": sym, "n": len(df),
                "first": str(pd.to_datetime(df.ts.iloc[0], unit="s").date()),
                "last": str(pd.to_datetime(df.ts.iloc[-1], unit="s").date())}

    from concurrent.futures import ThreadPoolExecutor, as_completed
    done = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(one, s): s for s in syms}
        for f in as_completed(futs):
            r = f.result()
            rows.append(r)
            done += 1
            if r["n"] == 0:
                empty += 1
            if done % 10 == 0:
                print(f"  [{done}/{len(syms)}] terakhir {r['sym']:16s} n={r['n']:6d} "
                      f"{r['first']}..{r['last']}", flush=True)

    ok = [r for r in rows if r["n"]]
    print(f"\nSELESAI: {len(ok)} simbol berisi, {empty} kosong")
    if ok:
        starts = sorted(r["first"] for r in ok)
        print(f"  awal data paling tua: {starts[0]} | paling baru: {starts[-1]}")
        print(f"  total bar: {sum(r['n'] for r in ok):,}")
    (OUT / f"_summary_{a.interval}.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
