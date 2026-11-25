#!/usr/bin/env python3
"""
ANANTARA SAKTI — SoDEX SPOT (Spark) order-book + trades collector for low-cap pairs.

Why this exists: perps (Bolt) spreads are razor-thin (0.001-0.012%) — below the
maker fee floor — so perps maker-farming can never be net-profitable (proven:
scripts/research/research_fill_rate.py). But SoDEX SPOT low-cap pairs have WIDE spreads
that EXCEED the spot round-trip maker fee (0.07%): measured PEPE 0.28%, SHIB
0.18%. That means maker spread-capture can be NET PROFITABLE on spot low-caps —
the first SoDEX avenue where "volume is a result of profitability" actually holds.

This collects the data to test that hypothesis with the same rigor as perps
(fill rate + adverse selection + triple-barrier), BEFORE risking capital.

Output: freqtrade_user_data/data/sodex/spot/{obi,trades}/*_YYYYMMDD.jsonl
Pure stdlib. Run via systemd-user (anantara-spot.service) or:
  python3 scripts/sodex_spot_collector.py
"""
from __future__ import annotations
import json, os, time, urllib.request
from datetime import datetime, timezone

B = "https://mainnet-gw.sodex.dev/api/v1/spot"
# internal Spark names for the wide-spread low-caps (displayName → name):
# PEPE 0.28%, SHIB 0.18%, SUI 0.059% spreads (vs 0.07% RT maker fee)
SYMBOLS = os.environ.get("SPOT_SYMBOLS",
                         "vPEPE_vUSDC,vSHIB_vUSDC,vSUI_vUSDC").split(",")
POLL = float(os.environ.get("SPOT_POLL", "4.0"))
SPOT_MAKER_FEE = 0.035            # % per side (spot Spark); RT = 0.07%
OBI_DIR = "freqtrade_user_data/data/sodex/spot/obi"
TRADES_DIR = "freqtrade_user_data/data/sodex/spot/trades"
os.makedirs(OBI_DIR, exist_ok=True)
os.makedirs(TRADES_DIR, exist_ok=True)

_HDRS = {"Accept": "application/json", "User-Agent": "anantara-spot/1.0"}
_seen_trades: dict[str, set] = {}


def fetch_ob(sym: str) -> dict | None:
    try:
        req = urllib.request.Request(f"{B}/markets/{sym}/orderbook?limit=20", headers=_HDRS)
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.load(r).get("data", {})
    except Exception:
        return None


def fetch_trades(sym: str) -> list:
    try:
        req = urllib.request.Request(f"{B}/markets/{sym}/trades?limit=50", headers=_HDRS)
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.load(r).get("data", []) or []
    except Exception:
        return []


def record_trades(sym: str, f) -> None:
    seen = _seen_trades.setdefault(sym, set())
    for t in fetch_trades(sym):
        tid = t.get("t")
        if tid is None or tid in seen:
            continue
        seen.add(tid)
        f.write(json.dumps({"id": tid, "ts": t.get("T"), "sym": sym,
                            "side": t.get("S"), "price": float(t.get("p", 0) or 0),
                            "qty": float(t.get("q", t.get("v", 0)) or 0)}) + "\n")
    if len(seen) > 4000:
        _seen_trades[sym] = set(list(seen)[-2000:])


def imbalance(levels_b, levels_a, n):
    bv = sum(float(q) for _, q in levels_b[:n])
    av = sum(float(q) for _, q in levels_a[:n])
    tot = bv + av
    return (round((bv - av) / tot, 5) if tot > 0 else 0.0), round(bv, 4), round(av, 4)


def main():
    print(f"SPOT collector: {SYMBOLS} every {POLL}s -> {OBI_DIR} + {TRADES_DIR} "
          f"(maker fee {SPOT_MAKER_FEE}%/side)")
    while True:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        path = os.path.join(OBI_DIR, f"obi_{day}.jsonl")
        tpath = os.path.join(TRADES_DIR, f"trades_{day}.jsonl")
        sweep_start = time.time()
        with open(path, "a") as f, open(tpath, "a") as tf:
            for sym in SYMBOLS:
                record_trades(sym, tf)
                ob = fetch_ob(sym)
                if not ob or not ob.get("bids") or not ob.get("asks"):
                    continue
                bids, asks = ob["bids"], ob["asks"]
                best_bid, best_ask = float(bids[0][0]), float(asks[0][0])
                bbv, bav = float(bids[0][1]), float(asks[0][1])
                mid = (best_bid + best_ask) / 2
                spread_pct = (best_ask - best_bid) / mid * 100 if mid > 0 else 0
                obi5, bv5, av5 = imbalance(bids, asks, 5)
                obi20, bv20, av20 = imbalance(bids, asks, 20)
                row = {"ts": ob.get("blockTime", int(time.time() * 1000)),
                       "sym": sym, "mid": mid, "bid": best_bid, "ask": best_ask,
                       "spread": round(best_ask - best_bid, 10),
                       "spread_pct": round(spread_pct, 5),
                       "obi5": obi5, "obi20": obi20,
                       "bbv": round(bbv, 4), "bav": round(bav, 4),
                       "bv20": bv20, "av20": av20}
                f.write(json.dumps(row) + "\n")
        elapsed = time.time() - sweep_start
        time.sleep(max(0.5, POLL - elapsed))


if __name__ == "__main__":
    main()
