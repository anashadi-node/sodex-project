#!/usr/bin/env python3
"""SoDEX Maker-Farm PAPER TEST (read-only, zero capital, zero real orders).

Purpose: BEFORE risking any real USDC, empirically measure whether the W9/W3
maker-farm pattern (post-only maker + SHORT-bias on wide-spread perps) actually:
  (1) FILLS — do our simulated maker orders get taken? (the key unknown)
  (2) generates VOLUME — how much, at our small size?
  (3) is PROFITABLE — spread capture minus maker fees?

Method: poll live perp orderbooks (bin/sodex, READ-ONLY). Simulate a SHORT-first
maker roundtrip per pair: SELL@(ask-1tick) to open → BUY@(bid+1tick) to close.
Fill model is CONSERVATIVE (lower-bound): a resting order fills only when a later
snapshot shows the opposite side crossing our resting price. Real maker fills at
the touch (without full cross) would be HIGHER — so measured volume/fills here are
a floor, and measured PnL uses actual observed prices. Requote on timeout.

NO orders are placed. NO private key is used for trading. Public market data only.
"""
import json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
SODEX = str(PROJECT / "bin" / "sodex")
LOG = PROJECT / "logs" / "maker_paper_test.jsonl"
STATE = PROJECT / "data" / "maker_paper_state.json"

PAIRS = os.environ.get("PT_PAIRS", "SPCX-USD,DRAM-USD,USTECH100-USD").split(",")
NOTIONAL = float(os.environ.get("PT_NOTIONAL", "30"))      # $ per order
MAKER_FEE = float(os.environ.get("PT_MAKER_FEE", "0.00012"))  # 0.012%/side Tier-0
POLL_S = float(os.environ.get("PT_POLL", "20"))
TIMEOUT_POLLS = int(os.environ.get("PT_TIMEOUT_POLLS", "6"))  # requote after N unfilled
UTC = timezone.utc


def now_iso():
    return datetime.now(UTC).isoformat()


def get_book(pair):
    """Return (best_bid, best_ask, tick) or None. READ-ONLY public data."""
    try:
        out = subprocess.run(
            [SODEX, "orderbook", "perps", pair, "--depth", "1", "--format", "json"],
            capture_output=True, text=True, timeout=12,
        ).stdout
        j = json.loads(out)
        bids = j.get("bids") or []
        asks = j.get("asks") or []
        if not bids or not asks:
            return None
        bid = float(bids[0]["price"])
        ask = float(asks[0]["price"])
        # infer tick from 2nd level
        tick = 0.0
        if len(bids) > 1:
            tick = round(abs(bid - float(bids[1]["price"])), 10)
        if tick <= 0:
            tick = round(ask - bid, 10) or bid * 1e-5
        return (bid, ask, tick)
    except Exception:
        return None


def log(rec):
    rec["ts"] = now_iso()
    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")


def main():
    # per-pair sim state: resting order + open short + accumulators
    st = {p: {
        "resting": None,        # dict(side, price, age) or None
        "short_px": None,       # entry price if currently short
        "n_fills": 0, "n_placed": 0, "n_timeout": 0,
        "vol": 0.0, "gross_pnl": 0.0, "fees": 0.0, "rts": 0,
    } for p in PAIRS}
    t0 = time.time()
    log({"event": "start", "pairs": PAIRS, "notional": NOTIONAL,
         "maker_fee": MAKER_FEE, "note": "READ-ONLY paper test, conservative fills"})

    while True:
        for p in PAIRS:
            bk = get_book(p)
            if not bk:
                continue
            bid, ask, tick = bk
            s = st[p]
            r = s["resting"]

            if r is None:
                # place a new resting maker order (SHORT-first pattern)
                if s["short_px"] is None:
                    # open SHORT: SELL just inside the ask (maker)
                    px = round(ask - tick, 10)
                    s["resting"] = {"side": "sell", "price": px, "age": 0}
                else:
                    # close SHORT: BUY just inside the bid (maker)
                    px = round(bid + tick, 10)
                    s["resting"] = {"side": "buy", "price": px, "age": 0}
                s["n_placed"] += 1
                continue

            # check conservative fill of resting order
            filled = False
            if r["side"] == "sell" and bid >= r["price"]:
                filled = True   # a buyer crossed up to our resting sell
            elif r["side"] == "buy" and ask <= r["price"]:
                filled = True   # a seller crossed down to our resting buy

            if filled:
                qty = NOTIONAL / r["price"]
                s["n_fills"] += 1
                s["vol"] += NOTIONAL
                s["fees"] += NOTIONAL * MAKER_FEE
                if r["side"] == "sell":
                    s["short_px"] = r["price"]     # now short
                else:
                    # closing short: pnl = (entry_short - buy_close) * qty
                    if s["short_px"]:
                        s["gross_pnl"] += (s["short_px"] - r["price"]) * qty
                        s["rts"] += 1
                    s["short_px"] = None
                s["resting"] = None
            else:
                r["age"] += 1
                if r["age"] >= TIMEOUT_POLLS:
                    s["n_timeout"] += 1
                    s["resting"] = None   # cancel + requote next poll

        # periodic summary every ~5 min
        if int(time.time() - t0) % 300 < POLL_S:
            for p in PAIRS:
                s = st[p]
                net = s["gross_pnl"] - s["fees"]
                fr = (s["n_fills"] / s["n_placed"] * 100) if s["n_placed"] else 0
                log({"event": "summary", "pair": p, "placed": s["n_placed"],
                     "fills": s["n_fills"], "fill_rate_pct": round(fr, 1),
                     "timeouts": s["n_timeout"], "rts": s["rts"],
                     "sim_volume_usd": round(s["vol"], 2),
                     "gross_pnl_usd": round(s["gross_pnl"], 4),
                     "fees_usd": round(s["fees"], 4),
                     "net_pnl_usd": round(net, 4)})
            try:
                STATE.write_text(json.dumps(st, indent=2))
            except Exception:
                pass
        time.sleep(POLL_S)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log({"event": "stop"})
        sys.exit(0)
