#!/usr/bin/env python3
"""U1 (2026-07-18): SoDEX L1 microstructure recorder — READ-ONLY, no orders, no capital.

SoDEX exposes no WebSocket, so this POLLS /perps/markets/tickers (one call = all ~82
perps' L1 bid/ask/size) at a fixed cadence and stores the L1 series. From that series it
derives the microstructure signals the audits identified as the real short-horizon edge —
crucially cumulative OFI (Cont-Kukanov-Stoikov), which upgrades U4's weak static-OBI to a
genuine order-FLOW signal, plus a real spread series and realized volatility.

Honest scope: poll-based (~1-3s), not tick-level — a pragmatic recorder given no WS. Good
enough to build real 1-minute microstructure features; a true tick feed would refine it.

Pure derivations (compute_ofi / spread_series / realized_vol / obi_series) are separated
from IO so they are deterministically unit-tested with synthetic snapshots.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

DB = PROJECT / "data" / "sodex_book_recorder.db"
DEFAULT_INTERVAL_S = float(os.environ.get("BOOK_RECORDER_INTERVAL_S", "2"))
RETENTION_HOURS = float(os.environ.get("BOOK_RECORDER_RETENTION_H", "48"))


# ── PURE DERIVATIONS ─────────────────────────────────────────────────────────
def compute_ofi(snaps: list) -> float:
    """Cumulative L1 Order-Flow Imbalance (Cont-Kukanov-Stoikov 2014) over a series of
    snapshots. Each snap = dict(bid, ask, bid_sz, ask_sz). Positive OFI = net buy
    pressure (bid strengthening and/or ask weakening). Returns 0.0 for < 2 snaps.

        e_bid = +bid_sz_t          if bid_t > bid_{t-1}
                (bid_sz_t−bid_sz_{t-1}) if bid_t == bid_{t-1}
                −bid_sz_{t-1}      if bid_t < bid_{t-1}
        e_ask = +ask_sz_t          if ask_t < ask_{t-1}
                (ask_sz_t−ask_sz_{t-1}) if ask_t == ask_{t-1}
                −ask_sz_{t-1}      if ask_t > ask_{t-1}
        OFI  = Σ (e_bid − e_ask)
    """
    if len(snaps) < 2:
        return 0.0
    ofi = 0.0
    for a, b in zip(snaps[:-1], snaps[1:]):
        bp0, bp1 = a["bid"], b["bid"]
        ap0, ap1 = a["ask"], b["ask"]
        bs0, bs1 = a["bid_sz"], b["bid_sz"]
        as0, as1 = a["ask_sz"], b["ask_sz"]
        if bp1 > bp0:
            e_bid = bs1
        elif bp1 == bp0:
            e_bid = bs1 - bs0
        else:
            e_bid = -bs0
        if ap1 < ap0:
            e_ask = as1
        elif ap1 == ap0:
            e_ask = as1 - as0
        else:
            e_ask = -as0
        ofi += (e_bid - e_ask)
    return ofi


def obi_series(snaps: list) -> list:
    """L1 order-book imbalance per snapshot: (bid_sz−ask_sz)/(bid_sz+ask_sz)."""
    out = []
    for s in snaps:
        tot = s["bid_sz"] + s["ask_sz"]
        out.append((s["bid_sz"] - s["ask_sz"]) / tot if tot > 0 else 0.0)
    return out


def spread_series(snaps: list) -> list:
    """Spread in bps per snapshot."""
    out = []
    for s in snaps:
        mid = (s["bid"] + s["ask"]) / 2
        out.append((s["ask"] - s["bid"]) / mid * 1e4 if mid > 0 else 0.0)
    return out


def realized_vol(snaps: list) -> float:
    """Realized volatility = stdev of mid log-returns across the series (bps)."""
    mids = [(s["bid"] + s["ask"]) / 2 for s in snaps if (s["bid"] + s["ask"]) > 0]
    if len(mids) < 3:
        return 0.0
    rets = [math.log(mids[i] / mids[i - 1]) for i in range(1, len(mids)) if mids[i - 1] > 0]
    if len(rets) < 2:
        return 0.0
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * 1e4


# ── IO ───────────────────────────────────────────────────────────────────────
def _connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB), timeout=10)
    con.execute("CREATE TABLE IF NOT EXISTS l1("
                "ts REAL, symbol TEXT, bid REAL, ask REAL, bid_sz REAL, ask_sz REAL, last REAL)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_l1 ON l1(symbol, ts)")
    return con


def _fetch_tickers() -> list:
    try:
        import anantara.sodex_twin_engine as te
        from anantara.sodex_twin_engine import _data_list
        c = te.SodexLiveAdapter(te.Config())
        j = c._api_get("/perps/markets/tickers")
        rows = _data_list(j, "tickers") if isinstance(j, dict) else (j or [])
        return rows if isinstance(rows, list) else []
    except Exception as e:  # pragma: no cover
        print(f"fetch error: {e}", file=sys.stderr)
        return []


def poll_once(symbols: set | None = None) -> int:
    """One snapshot of all (or filtered) perps L1 → DB. Returns rows written."""
    rows = _fetch_tickers()
    ts = time.time()
    con = _connect()
    n = 0
    for r in rows:
        sym = r.get("symbol", "")
        if symbols and sym not in symbols:
            continue
        try:
            con.execute("INSERT INTO l1 VALUES (?,?,?,?,?,?,?)",
                        (ts, sym, float(r.get("bidPx") or 0), float(r.get("askPx") or 0),
                         float(r.get("bidSz") or 0), float(r.get("askSz") or 0),
                         float(r.get("lastPx") or 0)))
            n += 1
        except (TypeError, ValueError):
            continue
    # rolling retention
    con.execute("DELETE FROM l1 WHERE ts < ?", (ts - RETENTION_HOURS * 3600,))
    con.commit()
    con.close()
    return n


def load_snaps(symbol: str, window_min: float = 30) -> list:
    if not DB.exists():
        return []
    con = _connect()
    cut = time.time() - window_min * 60
    rows = con.execute(
        "SELECT bid, ask, bid_sz, ask_sz FROM l1 WHERE symbol=? AND ts>=? ORDER BY ts",
        (symbol, cut)).fetchall()
    con.close()
    return [{"bid": r[0], "ask": r[1], "bid_sz": r[2], "ask_sz": r[3]} for r in rows]


def derive(symbol: str, window_min: float = 30) -> dict:
    snaps = load_snaps(symbol, window_min)
    spreads = spread_series(snaps)
    obis = obi_series(snaps)
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol, "window_min": window_min, "n_snaps": len(snaps),
        "ofi": round(compute_ofi(snaps), 3),
        "spread_bps_last": round(spreads[-1], 2) if spreads else None,
        "spread_bps_mean": round(sum(spreads) / len(spreads), 2) if spreads else None,
        "obi_last": round(obis[-1], 3) if obis else None,
        "realized_vol_bps": round(realized_vol(snaps), 2),
    }


def record_loop(interval_s: float, symbols: set | None) -> None:  # pragma: no cover
    print(f"recording every {interval_s}s → {DB} (Ctrl-C to stop)")
    while True:
        try:
            n = poll_once(symbols)
            print(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} wrote {n} L1 rows")
        except Exception as e:
            print(f"poll error: {e}", file=sys.stderr)
        time.sleep(interval_s)


def main() -> int:
    ap = argparse.ArgumentParser(description="U1 SoDEX L1 microstructure recorder (read-only)")
    ap.add_argument("--once", action="store_true", help="single poll → DB")
    ap.add_argument("--record", action="store_true", help="continuous polling loop")
    ap.add_argument("--derive", metavar="PAIR", help="compute OFI/spread/vol for a pair")
    ap.add_argument("--pairs", help="comma-separated symbol filter (record/once)")
    ap.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_S)
    ap.add_argument("--window", type=float, default=30, help="derive window (min)")
    args = ap.parse_args()
    syms = {s.strip() for s in args.pairs.split(",")} if args.pairs else None
    if args.derive:
        print(json.dumps(derive(args.derive, args.window), indent=2))
    elif args.once:
        print(f"wrote {poll_once(syms)} L1 rows")
    elif args.record:
        record_loop(args.interval, syms)
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
