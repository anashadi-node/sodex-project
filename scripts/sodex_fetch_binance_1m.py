#!/usr/bin/env python3
"""Unduh klines Binance USDT-perp 1 menit untuk padanan simbol SoDEX. READ-ONLY.

SPEC4 pra-reg: docs/sodex/SODEX_SPEC4_PRAREG_2026-10-07.md
Sumber: API publik Binance Futures (fapi). Tanpa auth, tanpa order.
Output: scratch/binance_1m/{SYM}_1m.parquet  (SYM = simbol Binance, mis. BTCUSDT)
"""
import argparse
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

BASE = "https://fapi.binance.com/fapi/v1/klines"
OUTDIR = "scratch/binance_1m"
COLS = ["ts", "o", "h", "l", "c", "v", "close_ts", "q", "n", "taker_buy_v", "taker_buy_q", "ig"]


def fetch_page(sym, start_ms, end_ms, retries=4):
    url = f"{BASE}?symbol={sym}&interval=1m&startTime={start_ms}&endTime={end_ms}&limit=1000"
    for a in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception:
            if a == retries - 1:
                raise
            time.sleep(1.5 * (a + 1))


def fetch_symbol(sym, start_ms, end_ms):
    out = os.path.join(OUTDIR, f"{sym}_1m.parquet")
    if os.path.exists(out):
        try:
            d = pd.read_parquet(out, columns=["ts"])
            if len(d) and int(d["ts"].iloc[-1]) >= end_ms - 2 * 86400_000:
                return sym, "SKIP (ada)", int(len(d))
        except Exception:
            pass
    rows, t = [], start_ms
    while t < end_ms:
        batch = fetch_page(sym, t, end_ms)
        if not batch:
            break
        rows.extend(batch)
        last = int(batch[-1][0])
        if last <= t:
            break
        t = last + 60_000
        if len(batch) < 1000:
            break
        time.sleep(0.12)
    if not rows:
        return sym, "KOSONG (simbol tidak ada?)", 0
    df = pd.DataFrame(rows, columns=COLS)
    df["ts"] = df["ts"].astype("int64")
    for c in ("o", "h", "l", "c", "v", "q"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[["ts", "o", "h", "l", "c", "v", "q"]].drop_duplicates("ts").sort_values("ts")
    os.makedirs(OUTDIR, exist_ok=True)
    df.to_parquet(out, index=False)
    return sym, "OK", int(len(df))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-05-20")
    ap.add_argument("--end", default="2026-10-08")
    ap.add_argument("--symbols", required=True,
                    help="daftar simbol Binance, koma. mis: BTCUSDT,ETHUSDT")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    start_ms = int(pd.Timestamp(a.start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(a.end, tz="UTC").timestamp() * 1000)
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    os.makedirs(OUTDIR, exist_ok=True)
    print(f"unduh {len(syms)} simbol | {a.start} -> {a.end} | worker={a.workers}", flush=True)
    t0 = time.time()
    ok = err = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(fetch_symbol, s, start_ms, end_ms): s for s in syms}
        for f in as_completed(futs):
            s = futs[f]
            try:
                sym, st, n = f.result()
                print(f"  {sym:<16} {st:<28} {n:>7} bar  ({(time.time()-t0)/60:.1f} mnt)", flush=True)
                ok += 1
            except Exception as e:
                print(f"  {s:<16} GAGAL: {type(e).__name__} {e}", flush=True)
                err += 1
    print(f"SELESAI: {ok} ok, {err} gagal, {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
