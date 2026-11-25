#!/usr/bin/env python3
"""SoDEX Trend-Rider Scanner (read-only).

Answers one question every run: WHICH asset is ALREADY trending NOW with enough
volume and acceptable spread, and WHICH direction — so a with-trend entry has
the best conditional odds today. Replicates the leaderboard winners' selection
step (they trade the movers: SKHY/SNDK/CL up-days, SPCX down-days).

Scoring (all measurable, no prediction):
  trend      = |chg24h|                (is it moving?)
  continuity = position of last in [low,high] aligned with direction
               (up-trend: last near high = trend intact, not faded)
  liquidity  = vol24h (fills + our size irrelevant to book)
  cost       = spread bps (taker entry+exit pays spread+fee)
  session    = stock perps move in US hours; crypto 24/7
Output: ranked JSON + table. No orders. No keys.
"""
from __future__ import annotations
import json, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://mainnet-gw.sodex.dev/api/v1"
OUT = Path(__file__).resolve().parents[1] / "data" / "sodex_trend_scan.json"
TAKER_RT_BPS = 7.2   # our taker 3.6 × 2 sides
MIN_VOL24 = 300_000
MIN_TREND = 2.0      # % — below this it's chop, stay out


def fetch_tickers():
    req = urllib.request.Request(BASE + "/perps/markets/tickers",
                                 headers={"User-Agent": "trend-scan/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode()).get("data") or []


def scan():
    rows = []
    for t in fetch_tickers():
        if not isinstance(t, dict):
            continue
        try:
            sym = t["symbol"]
            last = float(t.get("lastPx", 0) or 0)
            op = float(t.get("openPx", 0) or 0)
            hi = float(t.get("highPx", 0) or 0)
            lo = float(t.get("lowPx", 0) or 0)
            bid = float(t.get("bidPx", 0) or 0)
            ask = float(t.get("askPx", 0) or 0)
            qv = float(t.get("quoteVolume", 0) or 0)
            if min(last, op, hi, lo, bid) <= 0 or ask <= bid:
                continue
            chg = (last - op) / op * 100
            rng = (hi - lo) / lo * 100
            spread = (ask - bid) / ((ask + bid) / 2) * 1e4
            # continuity: 1.0 = closing at the extreme in trend direction
            pos_in_range = (last - lo) / (hi - lo) if hi > lo else 0.5
            continuity = pos_in_range if chg > 0 else (1 - pos_in_range)
            if qv < MIN_VOL24 or abs(chg) < MIN_TREND:
                continue
            # expected edge proxy: remaining trend room vs cost
            score = abs(chg) * continuity * min(qv / 1e6, 3.0) / max(spread, 0.3)
            rows.append({
                "symbol": sym, "dir": "LONG" if chg > 0 else "SHORT",
                "chg24h_pct": round(chg, 2), "range_pct": round(rng, 2),
                "continuity": round(continuity, 2), "spread_bps": round(spread, 2),
                "vol24h_usd": round(qv), "last": last,
                "score": round(score, 2),
            })
        except (KeyError, ValueError, ZeroDivisionError):
            continue
    rows.sort(key=lambda r: -r["score"])
    return rows


def main():
    rows = scan()
    now = datetime.now(timezone.utc)
    out = {"ts": now.isoformat(), "utc_hour": now.hour,
           "us_session": 13 <= now.hour < 21, "candidates": rows[:10]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=2))
    tmp.replace(OUT)
    print(f"UTC {now.strftime('%H:%M')} | US session: {out['us_session']}")
    print(f"{'symbol':13} {'dir':5} {'chg24h':>7} {'cont':>5} {'range':>6} "
          f"{'spread':>7} {'vol24h':>12} {'score':>6}")
    for r in rows[:10]:
        print(f"{r['symbol']:13} {r['dir']:5} {r['chg24h_pct']:>+6.2f}% "
              f"{r['continuity']:>5.2f} {r['range_pct']:>5.1f}% "
              f"{r['spread_bps']:>6.2f}b {r['vol24h_usd']:>12,} {r['score']:>6.2f}")
    if not rows:
        print("NO qualifying trend today (all chop) — correct action: DON'T trade.")


if __name__ == "__main__":
    main()
