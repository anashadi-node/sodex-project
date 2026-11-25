#!/usr/bin/env python3
"""Regime-first ensemble entry gate — the fix for the 0/4 paper loss.

ROOT CAUSE (verified 2026-07-30): 4 correlated crypto SHORTs opened into a
RANGING/mild-bull regime. Aggregate -20.94% lev. Intraday multi-TF bearishness
is NOT the multi-day trend. We shorted assets drifting flat-to-up.

This gate enforces the #1 lever from all Anantara research (memory): REGIME.
Every prior audit says the same thing:
  - SoDEX has NO directional edge (4+ backtests: OFI/MOM/REV/maker all rejected).
  - Swing 1-48h = coin-flip, negative-EV after cost.
  - Directional WR > 50% ONLY when regime confirms (bear→SHORT, bull→LONG).
  - The ONLY proven +EV in our experience = delta-neutral funding harvest.

So this gate does NOT invent edge. It stops the bleed by REFUSING directional
bets that fight regime or stack correlation, and routes to market-neutral
(funding harvest) when no directional edge exists — which is most of the time.

profit-first doctrine: no capital deployed without proven OOS edge. Gate is
paper-only advisory until a directional method clears the 30-trade / WR>=60% bar.
"""
from __future__ import annotations
import json, urllib.request, time
from dataclasses import dataclass, asdict

# ── config (single source of truth) ─────────────────────────────────────────
BULL_7D = 3.0          # % 7d drift to call BULL
BEAR_7D = -3.0         # % 7d drift to call BEAR
OBI_CONFIRM = 5.0      # |OBI%| needed to confirm order-flow direction
MAX_SPREAD_BPS = 5.0   # cost ceiling
MAX_CORRELATED = 1     # max simultaneous same-direction crypto-major directional bets
CRYPTO_MAJORS = {"BTC-USD", "ETH-USD", "SOL-USD", "DOGE-USD", "XRP-USD",
                 "HYPE-USD", "BNB-USD", "AVAX-USD", "LINK-USD", "ADA-USD"}


@dataclass
class Regime:
    symbol: str
    price: float
    chg7d: float
    above_ma7: bool
    label: str          # BULL | BEAR | RANGING
    atr_pct: float = 0.02   # daily volatility as fraction of price (for stop sizing)


@dataclass
class GateResult:
    symbol: str
    direction: str
    decision: str       # ALLOW | REFUSE | NEUTRAL_ONLY
    score: int          # 0-100 (only meaningful when ALLOW)
    reasons: list


ATR_PCT_FLOOR = 0.015   # never size a stop tighter than 1.5% (anti microstructure-noise)
ATR_PCT_CEIL = 0.10     # never wider than 10%


def classify(symbol: str, price: float, chg7d: float, above_ma7: bool,
             atr_pct: float = 0.02) -> Regime:
    if chg7d >= BULL_7D and above_ma7:
        label = "BULL"
    elif chg7d <= BEAR_7D and not above_ma7:
        label = "BEAR"
    else:
        label = "RANGING"
    atr_pct = min(ATR_PCT_CEIL, max(ATR_PCT_FLOOR, atr_pct))
    return Regime(symbol, price, chg7d, above_ma7, label, atr_pct)


def gate(direction: str, regime: Regime, obi_pct: float, spread_bps: float,
         tf_score: int, open_correlated: int) -> GateResult:
    """Decide if a directional entry is allowed. Hard gates first, then score.

    direction: SHORT | LONG
    tf_score:  net multi-TF bias, negative=bearish (e.g. -4 of 5)
    open_correlated: count of existing same-direction crypto-major positions
    """
    r = []
    direction = direction.upper()

    # HARD GATE 1 — regime must confirm direction. RANGING => no directional.
    if regime.label == "RANGING":
        r.append(f"regime RANGING (7d {regime.chg7d:+.1f}%) → directional edge≈0")
        return GateResult(regime.symbol, direction, "NEUTRAL_ONLY", 0, r)
    if direction == "SHORT" and regime.label != "BEAR":
        r.append(f"SHORT blocked: regime {regime.label} not BEAR")
        return GateResult(regime.symbol, direction, "REFUSE", 0, r)
    if direction == "LONG" and regime.label != "BULL":
        r.append(f"LONG blocked: regime {regime.label} not BULL")
        return GateResult(regime.symbol, direction, "REFUSE", 0, r)

    # HARD GATE 2 — correlation cap (don't stack the same bet)
    if regime.symbol in CRYPTO_MAJORS and open_correlated >= MAX_CORRELATED:
        r.append(f"correlation cap: {open_correlated} same-dir majors already open")
        return GateResult(regime.symbol, direction, "REFUSE", 0, r)

    # HARD GATE 3 — cost ceiling
    if spread_bps > MAX_SPREAD_BPS:
        r.append(f"spread {spread_bps:.2f}bps > {MAX_SPREAD_BPS}bps cost ceiling")
        return GateResult(regime.symbol, direction, "REFUSE", 0, r)

    # HARD GATE 4 — order flow must confirm
    obi_ok = (direction == "SHORT" and obi_pct <= -OBI_CONFIRM) or \
             (direction == "LONG" and obi_pct >= OBI_CONFIRM)
    if not obi_ok:
        r.append(f"OBI {obi_pct:+.1f}% does not confirm {direction}")
        return GateResult(regime.symbol, direction, "REFUSE", 0, r)

    # SCORE (all hard gates passed) — quality, not permission
    score = 40                                    # regime-confirmed base
    score += min(30, abs(obi_pct))                # order-flow strength
    score += min(20, abs(tf_score) * 5)           # multi-TF conviction
    score += 10 if spread_bps < 2.0 else 0        # cheap execution
    r.append(f"regime {regime.label} confirms {direction}; OBI {obi_pct:+.1f}%; "
             f"TF {tf_score}; spread {spread_bps:.2f}bps")
    return GateResult(regime.symbol, direction, "ALLOW", int(min(100, score)), r)


# ── live data helper (coingecko, read-only, no auth) ─────────────────────────
def fetch_regime(coingecko_id: str, symbol: str) -> Regime | None:
    url = f"https://api.coingecko.com/api/v3/coins/{coingecko_id}/market_chart?vs_currency=usd&days=8"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "anantara"})
        d = json.load(urllib.request.urlopen(req, timeout=20))
        p = [x[1] for x in d["prices"]]
        if len(p) < 25:
            return None
        now = p[-1]
        d7 = p[-7 * 24] if len(p) > 7 * 24 else p[0]
        ma7 = sum(p[-7 * 24:]) / len(p[-7 * 24:]) if len(p) >= 7 * 24 else sum(p) / len(p)
        # daily volatility = stdev(hourly returns) × √24, from last 24 hourly bars
        rets = [(p[i] - p[i - 1]) / p[i - 1] for i in range(max(1, len(p) - 24), len(p))]
        mean = sum(rets) / len(rets)
        sd = (sum((r - mean) ** 2 for r in rets) / len(rets)) ** 0.5
        atr_pct = sd * (24 ** 0.5)
        return classify(symbol, now, (now - d7) / d7 * 100, now > ma7, atr_pct)
    except Exception:
        return None


def demo():
    """Self-check: the 4 real losing shorts must all be REFUSED/NEUTRAL_ONLY."""
    # Real regimes measured 2026-07-30: all RANGING, 3/4 above MA7.
    cases = [
        ("SHORT", classify("BTC-USD", 64854, -0.3, True), -17.7, 0.52, -4, 0),
        ("SHORT", classify("ETH-USD", 1923, 2.2, True), -17.7, 0.52, -4, 0),
        ("SHORT", classify("SOL-USD", 74.6, -1.5, True), -36.0, 1.35, -4, 1),
        ("SHORT", classify("DOGE-USD", 0.07, 1.6, False), -4.3, 1.43, -4, 2),
    ]
    for direction, reg, obi, spr, tf, corr in cases:
        g = gate(direction, reg, obi, spr, tf, corr)
        assert g.decision in ("REFUSE", "NEUTRAL_ONLY"), f"{reg.symbol} should be blocked, got {g.decision}"
    # A genuine BEAR + confirmed flow + no stack MUST pass.
    bear = classify("BTC-USD", 55000, -12.0, False)
    ok = gate("SHORT", bear, -25.0, 0.4, -5, 0)
    assert ok.decision == "ALLOW" and ok.score >= 70, f"valid bear short should ALLOW high, got {ok}"
    # Correlation cap blocks the 2nd same-dir major even in a real bear.
    stacked = gate("SHORT", bear, -25.0, 0.4, -5, 1)
    assert stacked.decision == "REFUSE", "correlation cap must block stack"
    print("demo OK — 4 real losers blocked; valid bear short allowed; stack capped")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        demo()
    else:
        # live: classify majors, show what the gate says right now
        for cid, sym in [("bitcoin", "BTC-USD"), ("ethereum", "ETH-USD"),
                         ("solana", "SOL-USD"), ("dogecoin", "DOGE-USD")]:
            reg = fetch_regime(cid, sym)
            if reg:
                print(f"{sym:<9} regime={reg.label:<8} 7d={reg.chg7d:+.1f}% "
                      f"aboveMA7={reg.above_ma7}")
            time.sleep(2)
