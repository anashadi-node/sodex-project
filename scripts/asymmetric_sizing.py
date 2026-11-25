#!/usr/bin/env python3
"""Asymmetric sizing + trend-rider planner — profit WITHOUT predicting direction.

The math the 0/4 loss ignored: you do NOT need to be right often. You need
winners bigger than losers. Win 40% at +3R vs -1R = +0.6R expectancy = PROFIT.
This is lever #3 (risk asymmetry) + lever #1 (ride confirmed trends) from the
honesty synthesis — the two levers that pay without accurate prediction.

Two things this enforces:
  1. RISK-BASED SIZE: every trade risks a FIXED small % of account (default 1%).
     Size = risk_$ / stop_distance. A wrong trade costs the same small amount;
     you never blow up on one bet (the SOL -9% lesson).
  2. ASYMMETRIC EXITS: SL tight (1×ATR), TP far (>=3×ATR) + ATR trailing stop so
     winners run. R:R >= 3:1 → breakeven WR only 25%.

Gated by regime: a trade plan is only produced when regime CONFIRMS the trend
(BEAR→SHORT, BULL→LONG). RANGING → None (no ride, no bet). Paper-only; deploys
no capital. profit-first: this raises expectancy structurally, not by guessing.
"""
from __future__ import annotations
from dataclasses import dataclass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from regime_gate import Regime  # noqa: E402

RISK_PCT = 0.01        # risk 1% of account per trade (hard cap)
SL_ATR = 1.0           # stop = 1×ATR (tight — cut losers fast)
TP_ATR = 3.0           # target = 3×ATR (let winners run → R:R 3:1)
TRAIL_ATR = 1.5        # trailing stop distance once in profit
MAX_LEVERAGE = 5.0     # notional never exceeds 5× account (perp leverage cap)


@dataclass
class TradePlan:
    symbol: str
    direction: str
    entry: float
    sl: float
    tp: float
    size_units: float
    notional: float
    risk_usd: float
    rr: float
    trail_atr: float
    note: str


def plan(symbol: str, direction: str, entry: float, atr: float,
         account_usd: float, regime: Regime,
         risk_pct: float = RISK_PCT) -> TradePlan | None:
    """Return an asymmetric, risk-sized plan — or None if regime doesn't confirm.

    atr: recent average true range in price units (volatility unit for stops).
    """
    direction = direction.upper()
    # trend-rider gate: only ride a CONFIRMED trend.
    if regime.label == "RANGING":
        return None
    if direction == "SHORT" and regime.label != "BEAR":
        return None
    if direction == "LONG" and regime.label != "BULL":
        return None
    if atr <= 0 or entry <= 0 or account_usd <= 0:
        return None

    # anti-tight-stop guard: stop distance clamped to [1.5%, 10%] of entry so a
    # microstructure-noise ATR can't produce a 0.1% stop (the BTC "SL_too_close" loss).
    stop_dist = min(0.10 * entry, max(0.015 * entry, SL_ATR * atr))
    tp_dist = TP_ATR * stop_dist                   # TP scales off the clamped stop → R:R fixed
    if direction == "SHORT":
        sl, tp = entry + stop_dist, entry - tp_dist
    else:
        sl, tp = entry - stop_dist, entry + tp_dist

    risk_usd = account_usd * risk_pct
    size = risk_usd / stop_dist                    # risk-based sizing
    notional = size * entry
    cap = account_usd * MAX_LEVERAGE               # perp leverage sanity
    if notional > cap:                             # clamp (only if stop very tight)
        size = cap / entry
        notional = cap
        risk_usd = size * stop_dist                # actual risk after clamp
    rr = tp_dist / stop_dist
    return TradePlan(symbol, direction, entry, round(sl, 6), round(tp, 6),
                     round(size, 6), round(notional, 2), round(risk_usd, 2),
                     round(rr, 2), TRAIL_ATR,
                     f"risk {risk_pct*100:.1f}% acct, SL {SL_ATR}×ATR, TP {TP_ATR}×ATR, "
                     f"trail {TRAIL_ATR}×ATR — winners run")


def expectancy(win_rate: float, rr: float) -> float:
    """R-multiple expectancy: WR×rr - (1-WR)×1. Shows profit w/o high accuracy."""
    return win_rate * rr - (1 - win_rate)


def demo():
    bear = Regime("SOL-USD", 74.0, -12.0, False, "BEAR")
    bull = Regime("SOL-USD", 74.0, +12.0, True, "BULL")
    rang = Regime("SOL-USD", 74.0, 0.5, True, "RANGING")

    # ranging / wrong-regime → no plan
    assert plan("SOL-USD", "SHORT", 74.0, 1.5, 1000, rang) is None
    assert plan("SOL-USD", "SHORT", 74.0, 1.5, 1000, bull) is None

    # confirmed bear short: risk exactly 1%, R:R = 3, size = risk/stop
    p = plan("SOL-USD", "SHORT", 74.0, 1.5, 1000, bear)
    assert p is not None and abs(p.risk_usd - 10.0) < 0.01, p.risk_usd
    assert abs(p.rr - 3.0) < 0.01
    assert abs(p.size_units - (10.0 / 1.5)) < 1e-6
    assert p.sl > 74.0 and p.tp < 74.0            # short: SL above, TP below

    # asymmetry pays at low win-rate: 40% WR × 3R still positive
    assert expectancy(0.40, 3.0) > 0
    assert expectancy(0.25, 3.0) == 0.0           # 25% = breakeven at 3:1

    # leverage clamp: very tight stop must not blow past 5× notional cap
    pc = plan("BTC-USD", "SHORT", 60000, 30, 1000, Regime("BTC-USD", 60000, -12, False, "BEAR"))
    assert pc.notional <= 1000 * MAX_LEVERAGE + 1e-6

    print("demo OK — risk capped 1%, R:R 3:1, 40%WR profitable, ranging→no plan, lev clamped")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        demo()
    else:
        # show the expectancy table: profit without prediction accuracy
        print("Expectancy by WR × R:R (breakeven line shows accuracy NOT needed):")
        print(f"{'WR':>6} | {'2:1':>7} {'3:1':>7} {'4:1':>7}")
        for wr in (0.30, 0.35, 0.40, 0.45, 0.50):
            print(f"{wr*100:5.0f}% | {expectancy(wr,2):+7.2f} {expectancy(wr,3):+7.2f} {expectancy(wr,4):+7.2f}")
        print("\n→ At 3:1, even 40% win-rate = +0.60R per trade. Direction accuracy NOT required.")
