#!/usr/bin/env python3
"""
ANANTARA SAKTI — SoDEX Order Book Imbalance (OBI) collector.

Polls the SoDEX perps order book for liquid symbols and records OBI snapshots
(stdlib only, no deps). OBI is the documented microstructure scalp edge
(bid/ask depth imbalance ~0.94 corr with mid-price moves). We collect a time
series here, then backtest whether OBI predicts forward mid-price moves
(scripts/research/backtest_obi.py) — BEFORE risking any capital.

Output: freqtrade_user_data/data/sodex/obi/obi_YYYYMMDD.jsonl (one row per
symbol per poll). Append-only; survives restarts. Run in background:
  python3 scripts/sodex_obi_collector.py
"""
from __future__ import annotations
import json, os, time, urllib.request
from datetime import datetime, timezone

B = "https://mainnet-gw.sodex.dev/api/v1/perps"
SYMBOLS = os.environ.get("OBI_SYMBOLS", "BTC-USD,ETH-USD,SOL-USD").split(",")
POLL = float(os.environ.get("OBI_POLL", "4.0"))   # seconds between full sweeps
# Raw depth levels to persist per side. The venue returns 20; we keep OBI_LEVELS.
# Needed for execution-realism research (hftbacktest): fill/queue models require
# multi-level L2, which the derived aggregates (obi5/10/20) alone cannot provide.
LEVELS = int(os.environ.get("OBI_LEVELS", "10"))
OUT_DIR = "freqtrade_user_data/data/sodex/obi"
TRADES_DIR = "freqtrade_user_data/data/sodex/trades"   # for maker-fill/adverse modeling
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(TRADES_DIR, exist_ok=True)


_HDRS = {"Accept": "application/json", "User-Agent": "anantara-obi/1.0"}
_seen_trades: dict[str, set] = {}   # sym -> recent trade ids (bounded, dedupe)


def fetch_ob(sym: str) -> dict | None:
    try:
        req = urllib.request.Request(f"{B}/markets/{sym}/orderbook?limit=20", headers=_HDRS)
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.load(r).get("data", {})
    except Exception:
        return None


def fetch_trades(sym: str) -> list:
    """Recent trades (for fill/adverse-selection modeling). Defensive: [] on error."""
    try:
        req = urllib.request.Request(f"{B}/markets/{sym}/trades?limit=50", headers=_HDRS)
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.load(r).get("data", []) or []
    except Exception:
        return []


def record_trades(sym: str, f) -> None:
    """Write NEW trades (deduped by id) — taker side + price + qty + ts."""
    seen = _seen_trades.setdefault(sym, set())
    for t in fetch_trades(sym):
        tid = t.get("t")
        if tid is None or tid in seen:
            continue
        seen.add(tid)
        f.write(json.dumps({"id": tid, "ts": t.get("T"), "sym": sym,
                            "side": t.get("S"), "price": float(t.get("p", 0) or 0),
                            "qty": float(t.get("q", t.get("v", 0)) or 0)}) + "\n")
    if len(seen) > 4000:                      # bound memory
        _seen_trades[sym] = set(list(seen)[-2000:])


def imbalance(levels_b, levels_a, n):
    bv = sum(float(q) for _, q in levels_b[:n])
    av = sum(float(q) for _, q in levels_a[:n])
    tot = bv + av
    return (round((bv - av) / tot, 5) if tot > 0 else 0.0), round(bv, 4), round(av, 4)


def raw_levels(levels, n):
    """Normalize venue levels to [price, qty] float pairs (top n levels).

    Kept separate from the I/O loop so the persisted-book contract is testable
    without live venue data. Floats are used because JSON's repr round-trips
    exactly, so no precision is lost versus the venue's string form.
    """
    return [[float(px), float(q)] for px, q in levels[:n]]


def main():
    print(f"OBI+trades collector: {SYMBOLS} every {POLL}s -> {OUT_DIR} + {TRADES_DIR}")
    while True:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        path = os.path.join(OUT_DIR, f"obi_{day}.jsonl")
        tpath = os.path.join(TRADES_DIR, f"trades_{day}.jsonl")
        sweep_start = time.time()
        with open(path, "a") as f, open(tpath, "a") as tf:
            for sym in SYMBOLS:
                record_trades(sym, tf)        # capture taker trades (fill/adverse model)
                ob = fetch_ob(sym)
                if not ob or not ob.get("bids") or not ob.get("asks"):
                    continue
                bids, asks = ob["bids"], ob["asks"]
                best_bid, best_ask = float(bids[0][0]), float(asks[0][0])
                bbv, bav = float(bids[0][1]), float(asks[0][1])   # L1 volumes (for clean OFI)
                mid = (best_bid + best_ask) / 2
                obi5, bv5, av5 = imbalance(bids, asks, 5)
                obi10, _, _ = imbalance(bids, asks, 10)
                obi20, bv20, av20 = imbalance(bids, asks, 20)
                row = {"ts": ob.get("blockTime", int(time.time() * 1000)),
                       "sym": sym, "mid": mid, "bid": best_bid, "ask": best_ask,
                       "spread": round(best_ask - best_bid, 6),
                       "obi5": obi5, "obi10": obi10, "obi20": obi20,
                       "bbv": round(bbv, 4), "bav": round(bav, 4),
                       "bv20": bv20, "av20": av20,
                       # Raw book (needed by hftbacktest fill/queue simulation).
                       # JSON float repr round-trips exactly; no precision loss.
                       "b": raw_levels(bids, LEVELS),
                       "a": raw_levels(asks, LEVELS)}
                f.write(json.dumps(row) + "\n")
        # pace to ~POLL between sweeps
        elapsed = time.time() - sweep_start
        time.sleep(max(0.5, POLL - elapsed))


if __name__ == "__main__":
    main()
