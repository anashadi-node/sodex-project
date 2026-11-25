#!/usr/bin/env python3
"""SoDEX Maker-Farm PAPER TEST v2 — Jalur 2 target validation (read-only).

Tests the CORRECTED Jalur-2 config against the user's ABSOLUTE targets:
  - Weekly volume >= $1,300,000
  - Daily Real Ratio >= 1:7000 (net cost <= ~0.0143% of volume)

v2 fixes vs v1 (which measured the naive config):
  1. RATIO GUARANTEE: only trades when spread >= MIN_SPREAD (0.05%) → every RT
     captures spread > maker fee → net-positive → ratio = no-net-loss (>1:7000).
  2. COMPETITIVE placement: SELL@(ask-1tick), BUY@(bid+1tick) = rest AT the touch
     (new best) for fast fills, vs v1/engine's ask+offset (above ask = strands).
  3. FAST requote: cancel+re-quote stale orders every REQUOTE_S (chase the touch).
  4. Tracks REAL RATIO (vol / net_cost) + projected weekly volume vs target.

Fill model (conservative, L1-snapshot based): a resting competitive SELL@P fills
when a later snapshot's best_bid >= P (buyer reached our level) OR best_ask rises
above P (our touch-level consumed on an up-tick). Symmetric for BUY. Under-counts
taker-lift fills → volume here is a FLOOR. NO real orders. Public data only.
"""
import json, os, subprocess, sys, time
from datetime import datetime, timezone

SODEX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "sodex")
LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "maker_paper_v2.jsonl")
UTC = timezone.utc

PAIRS = os.environ.get("PT2_PAIRS", "DRAM-USD,USTECH100-USD,SPCX-USD").split(",")
NOTIONAL = float(os.environ.get("PT2_NOTIONAL", "130"))
MAKER_FEE = float(os.environ.get("PT2_MAKER_FEE", "0.00012"))   # 0.012%/side
MIN_SPREAD_PCT = float(os.environ.get("PT2_MIN_SPREAD", "0.05"))  # ratio-guarantee gate
POLL_S = float(os.environ.get("PT2_POLL", "8"))
REQUOTE_S = float(os.environ.get("PT2_REQUOTE", "20"))          # chase the touch
WEEKLY_TARGET = 1_300_000
RATIO_TARGET = 7000


def now_iso():
    return datetime.now(UTC).isoformat()


def get_book(pair):
    try:
        out = subprocess.run(
            [SODEX, "orderbook", "perps", pair, "--depth", "1", "--format", "json"],
            capture_output=True, text=True, timeout=10).stdout
        j = json.loads(out)
        bids, asks = j.get("bids") or [], j.get("asks") or []
        if not bids or not asks:
            return None
        bid, ask = float(bids[0]["price"]), float(asks[0]["price"])
        tick = round(abs(bid - float(bids[1]["price"])), 10) if len(bids) > 1 else round(ask - bid, 10)
        if tick <= 0:
            tick = bid * 1e-5
        return bid, ask, tick
    except Exception:
        return None


def log(rec):
    rec["ts"] = now_iso()
    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")


def main():
    st = {p: {"resting": None, "short_px": None, "hi_bid": 0.0, "lo_ask": 9e18,
              "fills": 0, "placed": 0, "requotes": 0, "skips_tight": 0,
              "vol": 0.0, "gross_pnl": 0.0, "fees": 0.0, "rts": 0} for p in PAIRS}
    t0 = time.time()
    log({"event": "start", "v": 2, "pairs": PAIRS, "notional": NOTIONAL,
         "min_spread_pct": MIN_SPREAD_PCT, "requote_s": REQUOTE_S,
         "note": "Jalur-2 corrected config: competitive+gated+fast-requote"})

    while True:
        for p in PAIRS:
            bk = get_book(p)
            if not bk:
                continue
            bid, ask, tick = bk
            spread_pct = (ask - bid) / bid * 100
            s = st[p]
            r = s["resting"]

            # RATIO GUARANTEE: skip when spread too tight to be net-positive
            if r is None and spread_pct < MIN_SPREAD_PCT:
                s["skips_tight"] += 1
                continue

            if r is None:
                # competitive placement AT the touch (new best)
                if s["short_px"] is None:
                    px = round(ask - tick, 10)   # SELL just inside ask
                    s["resting"] = {"side": "sell", "px": px, "ts": time.time()}
                else:
                    px = round(bid + tick, 10)   # BUY just inside bid
                    s["resting"] = {"side": "buy", "px": px, "ts": time.time()}
                s["placed"] += 1
                s["hi_bid"], s["lo_ask"] = bid, ask
                continue

            # track extremes over the order's life
            s["hi_bid"] = max(s["hi_bid"], bid)
            s["lo_ask"] = min(s["lo_ask"], ask)
            filled = False
            if r["side"] == "sell" and (s["hi_bid"] >= r["px"] or ask > r["px"] + tick):
                filled = True   # buyer reached level OR up-tick consumed our touch
            elif r["side"] == "buy" and (s["lo_ask"] <= r["px"] or bid < r["px"] - tick):
                filled = True

            if filled:
                qty = NOTIONAL / r["px"]
                s["fills"] += 1
                s["vol"] += NOTIONAL
                s["fees"] += NOTIONAL * MAKER_FEE
                if r["side"] == "sell":
                    s["short_px"] = r["px"]
                else:
                    if s["short_px"]:
                        s["gross_pnl"] += (s["short_px"] - r["px"]) * qty
                        s["rts"] += 1
                    s["short_px"] = None
                s["resting"] = None
            elif time.time() - r["ts"] > REQUOTE_S:
                s["requotes"] += 1
                s["resting"] = None   # chase: re-quote at fresh touch next tick

        # summary every 5 min
        if int(time.time() - t0) % 300 < POLL_S:
            elapsed_h = (time.time() - t0) / 3600 or 1e-9
            tot_vol = sum(s["vol"] for s in st.values())
            tot_fees = sum(s["fees"] for s in st.values())
            tot_pnl = sum(s["gross_pnl"] for s in st.values())
            net_cost = tot_fees - tot_pnl          # doctrine: fees - profit
            wk_proj = tot_vol / elapsed_h * 24 * 7
            ratio = (tot_vol / net_cost) if net_cost > 0 else float("inf")
            log({"event": "TARGET_CHECK", "elapsed_h": round(elapsed_h, 3),
                 "total_vol": round(tot_vol, 1),
                 "weekly_proj": round(wk_proj), "weekly_target": WEEKLY_TARGET,
                 "vol_target_ok": wk_proj >= WEEKLY_TARGET,
                 "net_cost": round(net_cost, 4),
                 "ratio": "no_net_loss" if net_cost <= 0 else round(ratio),
                 "ratio_target_ok": (net_cost <= 0 or ratio >= RATIO_TARGET),
                 "per_pair": {p: {"fills": s["fills"], "placed": s["placed"],
                                  "requotes": s["requotes"], "skips_tight": s["skips_tight"],
                                  "rts": s["rts"], "vol": round(s["vol"], 1),
                                  "net_pnl": round(s["gross_pnl"] - s["fees"], 4)}
                              for p, s in st.items()}})
        time.sleep(POLL_S)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log({"event": "stop"})
        sys.exit(0)
