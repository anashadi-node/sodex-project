#!/usr/bin/env python3
"""Bangun cache bar-menit dari tape trade SoDEX (READ-ONLY terhadap tape).

Sumber: freqtrade_user_data/data/sodex/trades/trades_YYYYMMDD.jsonl (136 hari, ~12,5 jt trade).
Keluaran: scratch/sodex_minutes/day=YYYYMMDD.parquet  (satu file per hari, semua simbol)

Kolom per (simbol, menit UTC):
  n, buy_n, sell_n, buy_qty, sell_qty, notional, vwap,
  open, high, low, close, first_ts, last_ts, big_n, big_qty

`big_*` = trade dengan notional >= BIG_USD (default 10.000) -> proksi aliran agresor besar.
CATATAN JUJUR: arti field `side` pada tape belum terverifikasi (agresor vs maker).
Karena itu signed-flow disimpan sebagai buy/sell TERPISAH, bukan satu angka bersih;
interpretasi ditentukan di tahap riset, bukan diasumsikan di sini.

READ-ONLY: tidak menyentuh gate, ambang, posisi, atau konfigurasi produksi.
Pakai: python3 scripts/sodex_build_minutes.py [--since YYYYMMDD] [--out DIR]
"""
from __future__ import annotations
import argparse
import json
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "freqtrade_user_data/data/sodex/trades"
BIG_USD = 10_000.0

SCHEMA = pa.schema([
    ("sym", pa.string()), ("minute", pa.int64()),
    ("n", pa.int32()), ("buy_n", pa.int32()), ("sell_n", pa.int32()),
    ("buy_qty", pa.float64()), ("sell_qty", pa.float64()),
    ("notional", pa.float64()), ("vwap", pa.float64()),
    ("open", pa.float64()), ("high", pa.float64()),
    ("low", pa.float64()), ("close", pa.float64()),
    ("first_ts", pa.int64()), ("last_ts", pa.int64()),
    ("big_n", pa.int32()), ("big_qty", pa.float64()),
])


def one_day(path: Path):
    """dict[(sym, minute)] -> agregat."""
    agg = defaultdict(lambda: [0, 0, 0, 0.0, 0.0, 0.0,
                               0.0, 0.0, 0.0, 0.0, 10**18, 0, 0, 0.0])
    for line in path.open():
        try:
            r = json.loads(line)
            sym, ts = r["sym"], r["ts"]
            px, qty = float(r["price"]), float(r["qty"])
        except (ValueError, KeyError, TypeError):
            continue
        a = agg[(sym, ts // 60_000)]
        nt = px * qty
        a[0] += 1
        if r.get("side") == "BUY":
            a[1] += 1
            a[3] += qty
        else:
            a[2] += 1
            a[4] += qty
        a[5] += nt
        a[10] = min(a[10], px)
        a[11] = max(a[11], px)
        if a[6] == 0.0:
            a[6], a[12] = px, ts
        a[9], a[13] = px, ts
        if nt >= BIG_USD:
            a[7] += 1
            a[8] += qty
    return agg


def flush(agg, out: Path):
    cols = {k: [] for k in SCHEMA.names}
    for (sym, mn), a in agg.items():
        n, bn, sn, bq, sq, nt = a[0], a[1], a[2], a[3], a[4], a[5]
        cols["sym"].append(sym)
        cols["minute"].append(mn)
        cols["n"].append(n)
        cols["buy_n"].append(bn)
        cols["sell_n"].append(sn)
        cols["buy_qty"].append(bq)
        cols["sell_qty"].append(sq)
        cols["notional"].append(nt)
        cols["vwap"].append(nt / (bq + sq) if (bq + sq) > 0 else 0.0)
        cols["open"].append(a[6])
        cols["high"].append(a[11])
        cols["low"].append(a[10] if a[10] < 10**17 else a[6])
        cols["close"].append(a[9])
        cols["first_ts"].append(a[12])
        cols["last_ts"].append(a[13])
        cols["big_n"].append(a[7])
        cols["big_qty"].append(a[8])
    pq.write_table(pa.table(cols, schema=SCHEMA), out, compression="zstd")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="20260524")
    ap.add_argument("--out", default=str(ROOT / "scratch/sodex_minutes"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in SRC.glob("trades_*.jsonl") if p.stem[-8:] >= args.since)
    print(f"{len(files)} hari diproses -> {out}")
    done = 0
    for i, p in enumerate(files, 1):
        dest = out / f"day={p.stem[-8:]}.parquet"
        if dest.exists():
            continue
        try:
            flush(one_day(p), dest)
            done += 1
        except (OSError, ValueError) as e:
            print(f"  GAGAL {p.name}: {type(e).__name__}: {e}")
            continue
        if i % 10 == 0 or i == len(files):
            print(f"  [{i}/{len(files)}] {p.stem[-8:]} ok={done}", flush=True)
    print(f"SELESAI: {done} hari baru ditulis, total file={len(list(out.glob('*.parquet')))}")


if __name__ == "__main__":
    main()
