#!/usr/bin/env python3
"""
# ⚠️  DEPRECATED (2026-06-08) — Superseded by sodex_autofarm.py v3.1. Remove after 2026-06-22.
ANANTARA SAKTI — SoDEX WIDE-SPREAD maker-farm (RESEARCH-VALIDATED v1.0)

LIVE-TEST CALIBRATED v2.0 (2026-06-07 — 19 cycles, 1 live RT):
  → T+1/T+2 capture 4-7× more profit per fill (CONFIRMED).
  → GTX (post-only) FAILS — use GTC with careful pricing.
  → Min notional ~$10 USD per order.
  → Fill time: 1.5-2× slower than theoretical (queue dynamic).
  → Adverse selection: REAL — buffer raised to 0.10%.
  → PEPE↔SHIB r=0.98 — prioritize SOSO for diversification.
  → Cancel needs BOTH --order-id AND --cl-ord-id.
  → 7 pairs: PEPE, SHIB, AVAX, XLM, ARB, TON, SOSO.

SAFETY (inherits project rules):
  • DRY-RUN by default — prints CLI orders, places nothing.
  • LIVE gated: --live + SODEX_SPOT_FARM_LIVE=1 + PROVEN flag.
  • GTC orders (GTX cancelled immediately in live test).
  • Per-order cap via SPOT_FARM_MAX_ORDER_USD (default $20).
  • Fill rate calibration: 50% of theoretical.
"""
from __future__ import annotations
import argparse, json, os, subprocess, urllib.request, time
from dataclasses import dataclass

SPOT_REST = "https://mainnet-gw.sodex.dev/api/v1/spot"
SODEX_BIN = os.environ.get("SODEX_BIN", "./bin/sodex")
PROVEN_FLAG = "freqtrade_user_data/data/sodex/spot/PROVEN"
SPOT_MAKER_FEE = 0.035
ADVERSE_BUFFER = 0.10  # raised from 0.05 after live adverse selection confirmed
MIN_HOLD_S = 900
FILL_RATE_FACTOR = 0.50  # calibrated from live SHIB test (actual ≈ 0.5× theoretical)
MIN_ORDER_USD = 10.0   # min notional from live test
_HDRS = {"Accept": "application/json", "User-Agent": "anantara-widefarm/1.0"}

# Pair config: (internal_name, daily_vol_usd, sell_vel_per_min, buy_vel_per_min)
PAIR_CONFIG = {
    "PEPE/USDC": ("vPEPE_vUSDC", 26000, 25.0, 23.7),
    "SHIB/USDC": ("vSHIB_vUSDC", 27700, 27.0, 29.6),
    "AVAX/USDC": ("vAVAX_vUSDC", 70500, 20.0, 20.0),
    "XLM/USDC":  ("vXLM_vUSDC",  23900, 15.0, 15.0),
    "ARB/USDC":  ("vARB_vUSDC",  26500, 20.0, 20.0),
    "TON/USDC":  ("vTON_vUSDC",  20800, 36.0, 37.0),
    "SOSO/USDC": ("WSOSO_vUSDC", 828000, 385.0, 272.0),
}

MAX_ORDER_USD = float(os.environ.get("SPOT_FARM_MAX_ORDER_USD", "20"))


@dataclass
class LevelInfo:
    offset: int
    bid: float
    ask: float
    spread_pct: float
    net_pct: float
    queue_buy: float
    queue_sell: float
    est_rt_min: float
    est_rt_day: float
    est_daily_profit: float


def fetch_book(name: str) -> dict | None:
    try:
        req = urllib.request.Request(f"{SPOT_REST}/markets/{name}/orderbook?limit=5", headers=_HDRS)
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.load(r).get("data", {})
    except Exception:
        return None


def _num(x: float) -> str:
    s = f"{x:.12f}".rstrip("0").rstrip(".") if abs(x) < 1 else f"{x:.6f}".rstrip("0").rstrip(".")
    return s or "0"


def analyze_pair(disp: str, name: str, vol_24h: float, sv: float, bv: float,
                 order_usd: float) -> LevelInfo | None:
    """Find optimal spread level for a pair given order size."""
    ob = fetch_book(name)
    if not ob or not ob.get("bids") or not ob.get("asks"):
        return None

    bids = ob["bids"]
    asks = ob["asks"]
    if len(bids) < 4 or len(asks) < 4:
        return None

    best: LevelInfo | None = None

    for off in range(min(4, len(bids), len(asks))):
        bid = float(bids[off][0])
        ask = float(asks[off][0])
        spr = (ask - bid) / ((ask + bid) / 2) * 100
        net = spr - 2 * SPOT_MAKER_FEE - ADVERSE_BUFFER
        if net <= 0:
            continue

        qb = sum(float(bids[i][0]) * float(bids[i][1]) for i in range(off))
        qa = sum(float(asks[i][0]) * float(asks[i][1]) for i in range(off))

        # Sequential fill time estimation (CALIBRATED: 2× slower than theoretical)
        buy_min = (qb / sv + order_usd / sv) / FILL_RATE_FACTOR if sv > 0 else 999
        sell_min = (qa / bv + order_usd / bv) / FILL_RATE_FACTOR if bv > 0 else 999
        rt_min = buy_min + sell_min

        # Volume cap: 15% market share
        max_rt = vol_24h * 0.15 / order_usd if order_usd > 0 else 0
        rt_day = min(1440 / rt_min if rt_min > 0 else 0, max_rt)
        daily = order_usd * (net / 100) * rt_day

        info = LevelInfo(
            offset=off, bid=bid, ask=ask,
            spread_pct=round(spr, 4), net_pct=round(net, 4),
            queue_buy=round(qb, 2), queue_sell=round(qa, 2),
            est_rt_min=round(rt_min, 1), est_rt_day=round(rt_day, 1),
            est_daily_profit=round(daily, 2),
        )

        if best is None or daily > best.est_daily_profit:
            best = info

    return best


def plan(capital: float, live: bool):
    proven = os.path.exists(PROVEN_FLAG)
    allow_deprecated = os.environ.get("SODEX_ALLOW_DEPRECATED_SPOT_EXECUTOR") == "1"
    live_ok = live and allow_deprecated and os.environ.get("SODEX_SPOT_FARM_LIVE") == "1" and proven

    if live and not live_ok:
        if not allow_deprecated:
            why = "deprecated executor disabled; use scripts/sodex_spot_daemon.py once"
        elif os.environ.get("SODEX_SPOT_FARM_LIVE") != "1":
            why = "SODEX_SPOT_FARM_LIVE!=1"
        else:
            why = f"edge NOT proven (missing {PROVEN_FLAG})"
        mode = f"🟡 DRY-RUN (live refused: {why})"
    else:
        mode = "🔴 LIVE (WIDE-SPREAD)" if live_ok else "🟡 DRY-RUN (wide-spread research)"

    per_order = min(MAX_ORDER_USD, capital / max(1, len(PAIR_CONFIG)))
    print(f"=== SoDEX WIDE-SPREAD farm {mode} | ${per_order:.0f}/order | "
          f"hold ≥{MIN_HOLD_S // 60}min | maker {SPOT_MAKER_FEE}%/side ===")
    print(f"  Strategy: auto-select optimal level (T+0 to T+3) per pair")
    print(f"  Gate: net > 0 after 2×{SPOT_MAKER_FEE}% fee + {ADVERSE_BUFFER}% buffer\n")

    total_daily = 0.0
    n_pass = 0
    orders_to_place: list[list[str]] = []

    for disp, (name, vol_24h, sv, bv) in PAIR_CONFIG.items():
        best = analyze_pair(disp, name, vol_24h, sv, bv, per_order)
        if best is None:
            print(f"  {disp:<12} ❌ no profitable level found")
            continue

        mid = (best.bid + best.ask) / 2
        qty = per_order / mid if mid > 0 else 0
        n_pass += 1
        total_daily += best.est_daily_profit

        t0_spr = 0.0
        ob = fetch_book(name)
        if ob and ob.get("bids") and ob.get("asks"):
            b0 = float(ob["bids"][0][0])
            a0 = float(ob["asks"][0][0])
            t0_spr = (a0 - b0) / ((a0 + b0) / 2) * 100

        print(f"  {disp:<12} T+{best.offset} | spread {best.spread_pct:.4f}% "
              f"(T+0={t0_spr:.4f}%) | net {best.net_pct:+.4f}% | "
              f"est ${best.est_daily_profit:.2f}/day")

        buy_cmd = [SODEX_BIN, "orders", "place", "spot", "--symbol", disp,
                   "--side", "buy", "--type", "limit", "--price", _num(best.bid),
                   "--qty", _num(qty), "--tif", "gtc"]
        sell_cmd = [SODEX_BIN, "orders", "place", "spot", "--symbol", disp,
                    "--side", "sell", "--type", "limit", "--price", _num(best.ask),
                    "--qty", _num(qty), "--tif", "gtc"]

        if live_ok:
            print(f"    [LIVE] buy @{_num(best.bid)} …")
            _place(buy_cmd)
            time.sleep(0.5)
            print(f"    [LIVE] sell @{_num(best.ask)} …")
            _place(sell_cmd)
        else:
            print(f"    would: {' '.join(buy_cmd)}")
            print(f"    would: {' '.join(sell_cmd)}")

        orders_to_place.extend([buy_cmd, sell_cmd])

    print(f"\n  {n_pass}/{len(PAIR_CONFIG)} pairs profitable")
    print(f"  Est. total: ${total_daily:.2f}/day = ${total_daily * 7:.2f}/week")
    print(f"  Capital deployed: ${per_order * n_pass:.0f} (sequential, ${per_order}/order)")
    if not proven and live:
        print(f"  ⚠️  Live blocked: edge not yet PROVEN → run analyze_spot_maker.py first")
    print(f"  ⚠️  WIDE-SPREAD strategy — RESEARCH VALIDATED (15+ cycles)")
    print(f"  ⚠️  Fill rates are ESTIMATES — live test needed for confirmation")


def _place(cmd: list[str]):
    try:
        r = subprocess.run(cmd + ["--format", "json"], capture_output=True, text=True, timeout=30)
        print(f"      -> {(r.stdout or r.stderr).strip()[:160]}")
    except Exception as e:
        print(f"      -> error {str(e)[:120]}")


def main():
    ap = argparse.ArgumentParser(description="SoDEX WIDE-SPREAD spot maker-farm (research-validated)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("plan", "run"):
        p = sub.add_parser(c)
        p.add_argument("--capital", type=float, default=270)
        p.add_argument("--live", action="store_true")
    args = ap.parse_args()
    plan(args.capital, live=(args.cmd == "run" and args.live))


if __name__ == "__main__":
    main()
