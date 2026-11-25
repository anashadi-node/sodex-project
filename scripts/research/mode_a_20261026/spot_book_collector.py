#!/usr/bin/env python3
"""Kolektor buku spot SoDEX (BTC/ETH/XAUT) per jam — publik, read-only. Mengukur spread, kedalaman, dan biaya order $20/$60/$150.
Output: <fwd_dir>/spot_book.jsonl (append-only). Dipakai preflight & analisis biaya eksekusi live."""
import datetime as dt, json, os, sys
import spot_exec as sx

def snap(fd):
    row = {"utc": dt.datetime.now(dt.timezone.utc).isoformat(), "a": {}}
    for a in ("btc", "eth", "xaut"):
        try:
            b = sx.fetch_book(a, 20)
            row["a"][a] = {"bid": float(b["bids"][0][0]), "ask": float(b["asks"][0][0]), "spread_bps": round(b["spread_bps"], 3),
                           "cost": {str(u): sx.depth_cost(b, u) for u in (20, 60, 150)},
                           "depth_usd_10bps": round(sum(float(p * q) for p, q in b["asks"] if p <= b["asks"][0][0] * (1 + sx.Decimal("0.001"))), 1)}
        except sx.ExecError as e:
            row["a"][a] = {"error": str(e)[:120]}
    with open(os.path.join(fd, "spot_book.jsonl"), "a") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")
    return row

if __name__ == "__main__":
    print(json.dumps(snap(sys.argv[1]), indent=1)[:900])
