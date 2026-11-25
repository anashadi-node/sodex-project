#!/usr/bin/env python3
"""Tarik klines publik SoDEX (unsigned market-data API) untuk SEMUA market perp.

Tujuan RISET: menembus kendala "bukti/data" yang selama ini dianggap binding.
Endpoint publik: https://mainnet-gw.sodex.dev/api/v1  (weight budget 1200/menit/IP)

Output: data/sodex_klines/<interval>/<SYMBOL>.json
Read-only terhadap sistem produksi: hanya HTTP GET + tulis file data baru.
"""
import json, os, sys, time, urllib.request, urllib.error

API = "https://mainnet-gw.sodex.dev/api/v1"
OUT = os.path.expanduser("~/anantara-sakti/data/sodex_klines")
UA = {"Accept": "application/json", "User-Agent": "anantara-riset/1.0"}


def get(path, tries=4):
    for a in range(tries):
        try:
            req = urllib.request.Request(API + path, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if a == tries - 1:
                raise
            time.sleep(1.5 * (a + 1))


def klines(sym, interval, limit=1000, end=None):
    p = f"/perps/markets/{sym}/klines?interval={interval}&limit={limit}"
    if end:
        p += f"&endTime={end}"
    return get(p).get("data") or []


def main():
    interval = sys.argv[1] if len(sys.argv) > 1 else "1d"
    max_bars = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    only = sys.argv[3].split(",") if len(sys.argv) > 3 else None
    d = os.path.join(OUT, interval)
    os.makedirs(d, exist_ok=True)

    syms = [s["name"] for s in get("/perps/markets/symbols")["data"]]
    if only:
        syms = [s for s in syms if s in only]
    print(f"interval={interval} symbols={len(syms)} max_bars={max_bars}", flush=True)

    for i, s in enumerate(syms):
        fp = os.path.join(d, s + ".json")
        if os.path.exists(fp):
            print(f"[{i+1}/{len(syms)}] {s} SKIP (ada)", flush=True)
            continue
        try:
            bars, end = [], None
            while len(bars) < max_bars:
                chunk = klines(s, interval, 1000, end)
                if not chunk:
                    break
                bars += chunk
                if len(chunk) < 1000:
                    break
                end = min(int(b["t"]) for b in chunk) - 1
                time.sleep(0.35)
            # dedupe + sort asc
            uniq = {int(b["t"]): b for b in bars}
            bars = [uniq[k] for k in sorted(uniq)]
            json.dump({"symbol": s, "interval": interval, "n": len(bars), "bars": bars},
                      open(fp, "w"))
            span = ""
            if bars:
                import datetime as dt
                f = lambda t: dt.datetime.fromtimestamp(t/1000, dt.UTC).strftime("%Y-%m-%d")
                span = f"{f(bars[0]['t'])}->{f(bars[-1]['t'])}"
            print(f"[{i+1}/{len(syms)}] {s} n={len(bars)} {span}", flush=True)
        except Exception as e:
            print(f"[{i+1}/{len(syms)}] {s} ERR {e}", flush=True)
        time.sleep(0.55)  # ~20 weight/req -> aman di budget 1200/menit


if __name__ == "__main__":
    main()
