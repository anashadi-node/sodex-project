#!/usr/bin/env /usr/bin/python3
"""Tarik klines 1 MENIT untuk jendela tertentu (READ-ONLY, paginasi endTime).

Berbeda dari sodex_pull_klines_paged.py yang MAX_PAGES=12 (cukup untuk 1h, TIDAK
cukup untuk 1m), skrip ini memaginasi sampai `days` hari ke belakang.

Output: data/sodex_klines/1m/<SYM>.json  {symbol, interval, n, oldest, newest, bars}
Usage:  sodex_pull_1m_window.py [days] [symbols_csv|auto]
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
PAUSE = 0.45


def fetch(url: str, tries: int = 4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            time.sleep((5.0 if e.code == 429 else 1.5) * (i + 1))
        except Exception:  # noqa: BLE001
            time.sleep(1.5 * (i + 1))
    return None


def auto_symbols() -> list[str]:
    """Simbol yang paling sering diperdagangkan di ledger (dari snapshot terbaru)."""
    import glob
    snaps = sorted(glob.glob(os.path.join(ROOT, "data", "snapshots", "sodex_*")))
    if not snaps:
        return ["BTC-USD", "ETH-USD", "SOL-USD"]
    cnt: dict[str, int] = {}
    for f in glob.glob(os.path.join(snaps[-1], "paper_test_*_state.json")):
        try:
            d = json.load(open(f))
        except Exception:  # noqa: BLE001
            continue
        k = next((x for x in ("closed", "closed_trades", "trades")
                  if isinstance(d.get(x), list) and d[x]), None)
        if not k:
            continue
        for t in d[k]:
            p = t.get("pair") or t.get("symbol")
            if p:
                cnt[p] = cnt.get(p, 0) + 1
    out = [s for s, _ in sorted(cnt.items(), key=lambda kv: -kv[1])[:15]]
    norm, seen = [], set()
    for s in out:
        p = s if s.endswith("-USD") else f"{s}-USD"
        if p not in seen:
            seen.add(p)
            norm.append(p)
    return norm or ["BTC-USD", "ETH-USD", "SOL-USD"]


def pull(symbol: str, days: int, interval: str) -> dict:
    cutoff = int((time.time() - days * 86400) * 1000)
    end = int(time.time() * 1000)
    seen: dict[int, dict] = {}
    pages = 0
    while True:
        d = fetch(f"{B}/markets/{symbol}/klines?interval={interval}&limit=1000&endTime={end}")
        if not d or d.get("code") != 0:
            break
        data = d.get("data") or []
        if not data:
            break
        for b in data:
            seen[b["t"]] = b
        oldest = min(b["t"] for b in data)
        pages += 1
        if oldest <= cutoff:
            break
        end = oldest - 1
        time.sleep(PAUSE)
        if pages > 400:
            break
    bars = [seen[t] for t in sorted(seen) if t >= cutoff]
    return {"symbol": symbol, "interval": interval, "n": len(bars),
            "oldest": datetime.fromtimestamp(bars[0]["t"] / 1000, tz=timezone.utc).isoformat() if bars else None,
            "newest": datetime.fromtimestamp(bars[-1]["t"] / 1000, tz=timezone.utc).isoformat() if bars else None,
            "pulled_utc": datetime.now(timezone.utc).isoformat(), "bars": bars}


def main() -> int:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    sel = sys.argv[2] if len(sys.argv) > 2 else "auto"
    interval = sys.argv[3] if len(sys.argv) > 3 else "1m"
    OUT = os.path.join(OUTBASE, interval)
    syms = auto_symbols() if sel == "auto" else [s.strip() for s in sel.split(",") if s.strip()]
    os.makedirs(OUT, exist_ok=True)
    print(f"[{interval}] days={days} symbols={len(syms)} {syms}", flush=True)
    man = []
    for i, s in enumerate(syms, 1):
        try:
            r = pull(s, days, interval)
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(syms)}] {s} FAIL {str(e)[:70]}", flush=True)
            continue
        if r["n"]:
            tmp = os.path.join(OUT, f"{s}.json.tmp")
            with open(tmp, "w") as f:
                json.dump(r, f)
            os.replace(tmp, os.path.join(OUT, f"{s}.json"))
        man.append({k: r[k] for k in ("symbol", "n", "oldest", "newest")})
        print(f"[{i}/{len(syms)}] {s} n={r['n']} {r['oldest']} -> {r['newest']}", flush=True)
    mp = os.path.join(OUT, "MANIFEST.json")
    with open(mp + ".tmp", "w") as f:
        json.dump({"interval": interval, "days": days, "pulled_utc": datetime.now(timezone.utc).isoformat(),
                   "symbols": man}, f, indent=1)
    os.replace(mp + ".tmp", mp)
    ok = sum(1 for m in man if m["n"] > 0)
    print(f"[done] {ok}/{len(man)} simbol punya bar", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
