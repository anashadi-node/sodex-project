#!/usr/bin/env python3
"""
ANANTARA SAKTI — SoDEX Farming Governor (Mesin 1-4 + Expectancy gate).

Implements the quantitative governor from the agent-orchestrator SKILL.md.
ALL parameters are COMPUTED per-trade from live market data — never hardcoded:
  Mesin 1: dynamic leverage (inverse to volatility, hard cap 25x)
  Mesin 2: dynamic stop-loss (verified strictly inside liquidation zone)
  Mesin 3: asset scoring (spread/depth/ATR/liquidity/funding → rank, not whitelist)
  Mesin 4: dynamic probability threshold (break-even win-rate from R:R + margin)
  Expectancy gate: farming only runs when expected value per roundtrip > 0.

Core principle (SKILL.md): "volume is a RESULT of profitability". A roundtrip is
only executed if it is expected to be profitable after fees. No breakeven farming.

Pure functions (deterministic, testable). Decisions consume market inputs the
caller supplies (ATR%, spread, depth, fee, R:R, model probability).
"""
from __future__ import annotations
from dataclasses import dataclass

# ---- Calibratable constants (starting points; tune from backtest/live) ----
LEV_CAP = 25                 # hard leverage ceiling (SoDEX/user)
LEV_FLOOR = 3                # baseline leverage at zero directional conviction (volume farming)
SAFETY_BUFFER = 2.5          # liquidation distance must be >= buffer * ATR%
SL_LIQ_FACTOR = 0.35         # SL placed at this fraction of liq distance
SL_ATR_K = 1.2               # SL not tighter than k*ATR% (avoid noise stop-out)
SL_FLOOR = 0.004             # absolute min SL (0.4%)
# Loosened 2026-05-24 (user: "jangan ketat, longgarkan tetapi terukur") — trade
# more often / scale leverage sooner, while the HARD math safety (expectancy gate,
# liquidation buffer, vol-capped leverage) is untouched.
PROB_SAFETY_MARGIN = 0.02    # margin above break-even win-rate (was 0.05)
PROB_ABS_FLOOR = 0.52        # never trade below this prob — still > coin-flip (was 0.55)
CONVICTION_REF = 0.50        # conviction measured as edge above a coin-flip (looser scaling)
ASSET_SCORE_MIN = 55         # min Mesin-3 score to farm an asset (was 60)


# ---------- Mesin 1: dynamic leverage ----------
def mesin1_leverage(atr_pct: float) -> dict:
    """Leverage inverse to volatility; liq distance must clear safety buffer.
    atr_pct: ATR as % of price on the execution timeframe."""
    if atr_pct <= 0:
        return {"leverage": 0, "ok": False, "reason": "no ATR"}
    # liq distance ~ 100/L must be >= SAFETY_BUFFER * atr_pct
    l_max_safe = 100.0 / (SAFETY_BUFFER * atr_pct)
    lev = int(max(1, min(l_max_safe, LEV_CAP)))
    liq_dist = 100.0 / lev
    ok = lev >= 3 and liq_dist >= SAFETY_BUFFER * atr_pct
    return {"leverage": lev, "liq_dist_pct": round(liq_dist, 3),
            "l_max_safe": round(l_max_safe, 1), "ok": ok,
            "reason": "" if ok else "too volatile for safe leverage"}


def dynamic_leverage(atr_pct: float, model_prob: float, prob_min: float) -> dict:
    """Conviction-AND-volatility-scaled leverage (Mesin 1, full form).

    Two independent constraints, both mathematical — never a hardcoded number:
      1. VOLATILITY ceiling (mesin1_leverage): liquidation distance must clear the
         safety buffer × ATR%. This is the hard safety cap (≤ LEV_CAP 25x).
      2. CONVICTION scaling: leverage rises from LEV_FLOOR toward that ceiling as
         the model's directional probability exceeds its break-even threshold.
         conviction = (model_prob − prob_min) / (1 − prob_min), clamped [0,1].

    So: weak/neutral signal (prob≈prob_min) → LEV_FLOOR (small, pure volume farming);
    strong validated conviction (prob→1) AND calm market → up to 25x (bigger
    directional bet = more profit AND more SoPoints volume). The 25x ceiling is
    only reachable when volatility is low enough to keep it liquidation-safe.

    HONEST CAVEAT: high leverage is only as good as the probability feeding it.
    Use an OOS-VALIDATED prob (e.g. the sodex-model server). The short-horizon
    microstructure scalp has ~no proven edge → its prob≈0.5≈prob_min → LEV_FLOOR.
    The expectancy gate remains the master backstop downstream.
    """
    base = mesin1_leverage(atr_pct)
    if not base["ok"]:
        return {"leverage": 0, "ok": False, "conviction": 0.0, "reason": base["reason"]}
    vol_ceiling = base["leverage"]                       # already ≤ LEV_CAP, liq-safe
    # conviction = edge above a coin-flip (looser than vs prob_min), clamped [0,1]
    conviction = max(0.0, min(1.0, (model_prob - CONVICTION_REF) / (1.0 - CONVICTION_REF)))
    lev = int(round(LEV_FLOOR + (vol_ceiling - LEV_FLOOR) * conviction))
    lev = max(LEV_FLOOR, min(lev, vol_ceiling, LEV_CAP))
    return {"leverage": lev, "vol_ceiling": vol_ceiling, "conviction": round(conviction, 3),
            "liq_dist_pct": round(100.0 / lev, 3), "ok": True,
            "reason": f"conviction {conviction:.2f} → {lev}x (vol ceiling {vol_ceiling}x)"}


# ---------- Mesin 2: dynamic stop-loss ----------
def mesin2_stop_loss(liq_dist_pct: float, atr_pct: float) -> dict:
    """SL inside the liq zone, not tighter than market noise. Verified < liq."""
    sl_liq_aware = liq_dist_pct * SL_LIQ_FACTOR
    sl_vol = SL_ATR_K * atr_pct
    sl = max(sl_vol, SL_FLOOR)
    sl = min(sl, sl_liq_aware)                 # never beyond liq-aware bound
    verified = sl < liq_dist_pct and sl > 0
    return {"sl_pct": round(sl, 4), "sl_liq_aware": round(sl_liq_aware, 4),
            "verified": verified,
            "reason": "" if verified else "SL not safely inside liq zone"}


# ---------- Mesin 3: asset scoring ----------
def mesin3_asset_score(spread_pct: float, depth_usd: float, atr_pct: float,
                       volume_24h_usd: float, funding_rate: float = 0.0) -> dict:
    """Score 0-100. Tight spread + deep book + healthy (not extreme) ATR +
    high liquidity + neutral funding = high score. Universe is ALL assets; the
    score (not a manual whitelist) decides which are farmable."""
    # spread: tighter is better (0.01% -> ~full, 0.1% -> low)
    s_spread = max(0.0, 1 - min(spread_pct / 0.05, 1)) * 30          # weight 30
    s_depth = min(depth_usd / 500_000, 1) * 20                       # weight 20
    # ATR sweet spot ~0.3%-1.5% (too low=no moves, too high=risk)
    if atr_pct <= 0:
        s_atr = 0
    elif atr_pct < 0.3:
        s_atr = (atr_pct / 0.3) * 15
    elif atr_pct <= 1.5:
        s_atr = 20
    else:
        s_atr = max(0, 20 - (atr_pct - 1.5) * 10)                    # weight 20
    s_liq = min(volume_24h_usd / 5_000_000, 1) * 20                  # weight 20
    s_fund = max(0.0, 1 - min(abs(funding_rate) / 0.0004, 1)) * 10   # weight 10
    score = round(s_spread + s_depth + s_atr + s_liq + s_fund, 1)
    return {"score": score, "farmable": score >= ASSET_SCORE_MIN,
            "components": {"spread": round(s_spread, 1), "depth": round(s_depth, 1),
                           "atr": round(s_atr, 1), "liq": round(s_liq, 1),
                           "funding": round(s_fund, 1)}}


# ---------- Mesin 4: dynamic probability threshold ----------
def mesin4_prob_threshold(rr: float, fee_pct_of_target: float = 0.0) -> dict:
    """Min probability to execute, derived from R:R (break-even win-rate + margin).
    rr = reward/risk. Better R:R → lower required probability."""
    if rr <= 0:
        return {"prob_min": 1.0, "reason": "invalid R:R"}
    # break-even win-rate, nudged up by fee drag
    wr_be = (1 + fee_pct_of_target) / (1 + rr)
    prob_min = max(wr_be + PROB_SAFETY_MARGIN, PROB_ABS_FLOOR)
    return {"prob_min": round(min(prob_min, 0.99), 3), "wr_breakeven": round(wr_be, 3)}


# ---------- Expectancy gate (master) ----------
def expectancy(win_rate: float, avg_win_pct: float, avg_loss_pct: float,
               fee_per_roundtrip_pct: float) -> dict:
    """Expected value per roundtrip after fees. Farming runs ONLY if > 0."""
    ev = (win_rate * avg_win_pct) - ((1 - win_rate) * avg_loss_pct) - fee_per_roundtrip_pct
    return {"expectancy_pct": round(ev, 5), "positive": ev > 0,
            "reason": "" if ev > 0 else "non-positive expectancy — DO NOT farm"}


@dataclass
class TradeDecision:
    approved: bool
    leverage: int
    sl_pct: float
    asset_score: float
    prob_min: float
    reason: str


def evaluate_roundtrip(atr_pct: float, spread_pct: float, depth_usd: float,
                       volume_24h_usd: float, rr: float, model_prob: float,
                       win_rate: float, avg_win_pct: float, avg_loss_pct: float,
                       fee_pct: float, funding_rate: float = 0.0) -> TradeDecision:
    """Full governor decision: run Mesin 1-4 + expectancy gate. ALL must pass."""
    m3 = mesin3_asset_score(spread_pct, depth_usd, atr_pct, volume_24h_usd, funding_rate)
    if not m3["farmable"]:
        return TradeDecision(False, 0, 0, m3["score"], 0, f"asset score {m3['score']}<{ASSET_SCORE_MIN}")
    m1 = mesin1_leverage(atr_pct)
    if not m1["ok"]:
        return TradeDecision(False, 0, 0, m3["score"], 0, m1["reason"])
    m4 = mesin4_prob_threshold(rr, fee_pct / max(avg_win_pct, 1e-9))
    if model_prob < m4["prob_min"]:
        return TradeDecision(False, m1["leverage"], 0, m3["score"],
                             m4["prob_min"], f"prob {model_prob:.2f}<{m4['prob_min']}")
    # Mesin 1 full form: leverage scaled by directional conviction, vol-capped, ≤25x
    dl = dynamic_leverage(atr_pct, model_prob, m4["prob_min"])
    m2 = mesin2_stop_loss(dl["liq_dist_pct"], atr_pct)
    if not m2["verified"]:
        return TradeDecision(False, dl["leverage"], 0, m3["score"], m4["prob_min"], m2["reason"])
    ev = expectancy(win_rate, avg_win_pct, avg_loss_pct, fee_pct)
    if not ev["positive"]:
        return TradeDecision(False, dl["leverage"], m2["sl_pct"], m3["score"],
                             m4["prob_min"], ev["reason"])
    return TradeDecision(True, dl["leverage"], m2["sl_pct"], m3["score"],
                         m4["prob_min"], f"approved · {dl['reason']}")


if __name__ == "__main__":
    # Self-test with sample inputs (BTC-like liquid, ETH-like, volatile alt)
    print("=== Governor self-test (Mesin 1-4 + expectancy) ===")
    cases = [
        ("BTC liquid", dict(atr_pct=0.4, spread_pct=0.0013, depth_usd=600_000,
                            volume_24h_usd=18_000_000, rr=1.5, model_prob=0.62,
                            win_rate=0.58, avg_win_pct=0.15, avg_loss_pct=0.12, fee_pct=0.024)),
        ("Volatile alt", dict(atr_pct=3.0, spread_pct=0.08, depth_usd=40_000,
                              volume_24h_usd=200_000, rr=1.2, model_prob=0.7,
                              win_rate=0.55, avg_win_pct=0.4, avg_loss_pct=0.35, fee_pct=0.024)),
        ("Breakeven trap", dict(atr_pct=0.5, spread_pct=0.002, depth_usd=400_000,
                                volume_24h_usd=8_000_000, rr=1.0, model_prob=0.60,
                                win_rate=0.50, avg_win_pct=0.10, avg_loss_pct=0.10, fee_pct=0.024)),
        ("High-conviction trend", dict(atr_pct=0.3, spread_pct=0.0013, depth_usd=800_000,
                                volume_24h_usd=25_000_000, rr=2.0, model_prob=0.92,
                                win_rate=0.66, avg_win_pct=0.30, avg_loss_pct=0.15, fee_pct=0.024)),
    ]
    for name, kw in cases:
        d = evaluate_roundtrip(**kw)
        print(f"\n{name}: approved={d.approved} | lev={d.leverage}x SL={d.sl_pct}% "
              f"score={d.asset_score} prob_min={d.prob_min}")
        print(f"  -> {d.reason}")
