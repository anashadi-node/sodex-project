#!/usr/bin/env python3
"""SoDEX stock/commodity live paper-test — READ-ONLY, no orders, no capital.

Runs during US market hours to test the ONE open hypothesis: are live US-session
spreads tight enough that the small OFI directional tilt net-beats cost? Off-hours
the 24h-median spread is wide (15-80 bps) and swamps OFI; when the underlying US
market is actively trading, stock-perp spreads may tighten enough to flip it.

For each symbol it (1) snapshots the LIVE L1 spread now, (2) replays OFI + momentum
on the freshly-recorded public trades using that live spread as the cost, and
(3) logs net-of-cost bps. No exchange client, no order path — pure paper evidence.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import scripts.sodex_directional_backtest as bt  # noqa: E402

LOG = PROJECT / "logs" / "stock_paper_test.log"
OUT = PROJECT / "data" / "sodex_stock_paper_test.json"

STOCKS = ["CRCL-USD", "MSTR-USD", "MU-USD", "AMD-USD", "HOOD-USD", "INTC-USD",
          "COIN-USD", "SKHY-USD", "PLTR-USD", "SPCX-USD", "NVDA-USD", "TSLA-USD"]
METALS = ["XAUT-USD", "SILVER-USD", "COPPER-USD", "CL-USD"]


MIN_DEPTH_USD = 500.0  # a live spread with < this L1 depth is a thin-book mirage


def live_spreads() -> dict[str, dict]:
    """Live L1 {spread_bps, depth_usd} per symbol from /perps/markets/tickers.

    Depth = min(bid_notional, ask_notional). A tight spread with tiny depth is a
    thin-book trap (can't fill), common off-hours — the depth guard rejects it."""
    out: dict[str, dict] = {}
    try:
        rows = __import__("scripts.sodex_farmable_scanner", fromlist=["fetch_perps_tickers"]).fetch_perps_tickers()
        for r in rows:
            bid = float(r.get("bidPx") or 0)
            ask = float(r.get("askPx") or 0)
            bsz = float(r.get("bidSz") or 0)
            asz = float(r.get("askSz") or 0)
            mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else 0
            if mid > 0:
                out[r.get("symbol", "")] = {
                    "spread_bps": (ask - bid) / mid * 1e4,
                    "depth_usd": min(bid * bsz, ask * asz),
                }
    except Exception as e:  # pragma: no cover
        print(f"live_spreads error: {e}", file=sys.stderr)
    return out


def paper_test(symbols: list[str], live_sp: dict[str, dict]) -> list[dict]:
    """For each symbol, OFI + best-momentum net-of-cost using the LIVE spread."""
    results = []
    for s in symbols:
        info = live_sp.get(s)
        if info is None:
            continue
        sp = info["spread_bps"]
        depth = info["depth_usd"]
        thin = depth < MIN_DEPTH_USD
        cost_note = f"live_spread={sp:.1f}bps depth=${depth:.0f} cost/RT={sp + 4:.1f}bps{' THIN' if thin else ''}"
        if thin:
            results.append({"symbol": s, "note": cost_note, "verdict": "thin_book_skip"})
            continue
        bars = bt.load_bars_from_trades(s, spread_bps=sp)
        if len(bars) < 60:
            results.append({"symbol": s, "note": cost_note, "n": 0, "verdict": "insufficient_data"})
            continue
        ofi = bt.load_ofi_bars(s)
        # OOS DISCIPLINE: select best variant on TRAIN net-bps, report on OOS.
        # In-sample best-of-N selection fakes an edge — this rejects that.
        best = None  # by train net
        for fam in ("OFI", "MOM", "REV"):
            thrs = [1000, 5000, 20000] if fam == "OFI" else [2, 3, 5, 10]
            for k in (3, 5, 10, 15):
                for h in (5, 15, 30, 60):
                    for thr in thrs:
                        trs = bt.gen_trades(bars, ofi, fam, k, h, thr)
                        tr, oo = bt.split_trades(trs, bars)
                        st_tr = bt.stats(tr, with_cost=True)
                        if st_tr["n"] >= 20 and (best is None or st_tr["mean_bps"] > best["_trnet"]):
                            st_oo = bt.stats(oo, with_cost=True)
                            st_oog = bt.stats(oo, with_cost=False)
                            best = {"variant": f"{fam}_k{k}_h{h}_t{thr:g}",
                                    "_trnet": st_tr["mean_bps"], "train_net_bps": round(st_tr["mean_bps"], 2),
                                    "n": st_oo["n"], "gross_bps": round(st_oog["mean_bps"], 2),
                                    "net_bps": round(st_oo["mean_bps"], 2), "wr": round(st_oo["wr"], 3)}
        rec = {"symbol": s, "note": cost_note}
        if best and best["n"] >= 15:
            best.pop("_trnet", None)
            rec.update(best)
            rec["verdict"] = "POSITIVE" if best["net_bps"] > 0 else "negative"
        else:
            rec["verdict"] = "insufficient_oos"
        results.append(rec)
    return results


def main() -> int:
    ts = datetime.now(timezone.utc)
    hour = ts.hour
    us_open = 13 <= hour < 20  # US regular session in UTC (EDT)
    live_sp = live_spreads()
    stock_res = paper_test(STOCKS, live_sp)
    metal_res = paper_test(METALS, live_sp)
    pos = [r for r in (stock_res + metal_res) if r.get("verdict") == "POSITIVE"]
    payload = {"ts": ts.isoformat(), "us_session": us_open,
               "n_positive": len(pos), "positive": pos,
               "stocks": stock_res, "metals": metal_res}
    OUT.write_text(json.dumps(payload, indent=2))
    line = (f"{ts.isoformat()} us_session={us_open} positive={len(pos)}/"
            f"{len(stock_res) + len(metal_res)} "
            + (", ".join(f"{r['symbol']}:{r['net_bps']}bps" for r in pos) if pos else "none"))
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")
    print(line)
    for r in stock_res + metal_res:
        print(f"  {r['symbol']:12} {r.get('verdict',''):10} "
              f"{r.get('variant',''):16} net={r.get('net_bps','—')} "
              f"gross={r.get('gross_bps','—')} WR={r.get('wr','—')} | {r.get('note','')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
