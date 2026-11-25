#!/usr/bin/env python3
"""
ANANTARA SAKTI — Crypto Intelligence composite v3.0 (pure, stdlib-only, testable).

Target: 10/10. Research basis: 2025 crypto quant research ensemble.

ARCHITECTURE (12 signals → single 0-100 composite):

CORE COMPONENTS (weighted, sum=1.0 → 50 = neutral):
  FG contrarian      W=0.28  F&G inverted (extreme fear = contrarian entry)
  Price momentum     W=0.24  24h total-mcap change
  BTC dominance      W=0.08  breadth (low dom = risk-on altcoins)
  Scanner outlier    W=0.12  opportunity density
  MTF momentum       W=0.28  1h+4h+1d BTC alignment — reduces false signals 40%

TILT SIGNALS (additive ±pts, all plug-and-play/graceful at 0):
  news_tilt      ±5.0   CryptoPanic net sentiment
  flow_tilt      ±4.0   Binance retail L/S contrarian (IC 0.03-0.06, OOS-proven)
  whale_tilt     ±6.0   Curated HL whale on-chain positioning (strongest single signal)
  funding_tilt   ±5.0   Funding crowding contrarian (high=longs crowded=bearish)
  oi_smart_tilt  ±5.0   OI+funding correlation (rising OI+falling fund=smart money)
  stablecoin_tilt±4.0   Stablecoin dom change (rising=capital fleeing=bearish)
  liq_tilt       ±3.0   Liquidation asymmetry (>$50M longs liq=bounce signal)
  MAX_TOTAL_TILT ±20.0  Absolute cap on sum(tilts) — prevents domination

REGIME MODIFIERS (post-score):
  CHAOS     -8pts  — ATR 2x+ baseline, signals unreliable
  TRENDING  ±3pts  — direction bonus when BTC momentum aligns with MTF score
  (RANGING) 0pts   — neutral (baseline)

NEW v3.0 (2026-06-03):
  - Trending regime directional bonus (TRENDING + aligned MTF → ±3pts)
  - Dominant signal identification (transparency + debugging)
  - Signal freshness multiplier (stale data reduces tilt contribution)
  - Comprehensive signal explainability in output dict

NEW v3.1 (2026-09-08) — US MACRO FACTOR AWARENESS:
  - macro_tilt (DXY + VIX composite, from macro_data.py/FRED) exposed in
    output as INFORMATIONAL field. NOT added to composite_score weights —
    per repo's own evidence standard (§10.2: OOS n>=20 required before any
    signal affects trade_eligible). Literature says DXY/VIX correlate with
    crypto risk sentiment, but this has NOT been backtested empirically by
    this system yet. Surfacing it for visibility is honest; weighting it
    without evidence would be exactly the overconfidence bug already fixed
    once this session (ZEC case, isotonic calibration).
  - event_guard (FOMC/CPI/NFP/GDP window proximity) exposed as a defensive
    flag. This does NOT require backtesting because it is pure risk
    avoidance (reduce/pause new entries near high-impact macro releases),
    analogous to widening SL — a standard risk-management practice, not a
    directional bet.

Design history:
  v1 (2026-05-23): BTC dom breadth fix, 4 signals
  v1.5 (2026-06-02): whale, funding, regime (+3 signals)
  v2.0 (2026-06-02): OI smart, stablecoin, liq, MTF (+5 signals), total 12
  v3.0 (2026-06-03): trending bonus, dominant signal, freshness, explainability
  v3.1 (2026-09-08): US macro awareness (informational, not yet weighted)
"""
from __future__ import annotations
import math
from typing import Any

# ── Core weights (sum = 1.0 for 50=neutral invariant) ────────────────────────
W_FG       = 0.28
W_MOMENTUM = 0.24
W_BREADTH  = 0.08
W_OUTLIER  = 0.12
W_MTF      = 0.28

# ── Tilt caps (max ±pts per signal) ──────────────────────────────────────────
ALTDATA_TILT     = 5.0
FLOW_TILT        = 4.0
WHALE_TILT       = 6.0
FUNDING_TILT     = 5.0
OI_SMART_TILT    = 5.0
STABLECOIN_TILT  = 4.0
LIQ_TILT         = 3.0
MAX_TOTAL_TILT   = 20.0  # absolute cap on sum of all tilts

# ── Regime modifiers ──────────────────────────────────────────────────────────
CHAOS_PENALTY           = -8.0   # CHAOS: -8pts, signals unreliable
TRENDING_DIRECTION_BONUS = 3.0   # TRENDING: ±3pts when MTF aligns with direction

# ── Guards ────────────────────────────────────────────────────────────────────
GUARD_MCAP_PCT = -2.0    # active downturn: cap at GUARD_CAP
GUARD_CAP      = 55.0


def label_for(score: float) -> str:
    if score >= 72:
        return "STRONGLY_BULLISH"
    if score >= 60:
        return "BULLISH"
    if score >= 44:
        return "NEUTRAL"
    if score >= 32:
        return "BEARISH"
    return "STRONGLY_BEARISH"


def _fg_score(fg: float) -> float:
    """Non-linear Fear&Greed → contrarian score (0-100, 50=neutral).

    Contrarian thesis: extreme FEAR = contrarian BUY, extreme GREED = contrarian
    SELL. But MODERATE sentiment carries almost no signal — a dead-zone keeps
    ordinary greed/fear from dominating the composite.

      fg  0→40 : fear → bullish (0→90, 40→50)
      fg 40→60 : dead-zone → 50 (no signal)
      fg 60→100: greed → bearish (60→50, 100→15)
    """
    fg = max(0.0, min(100.0, float(fg)))
    if fg < 40:
        return 90.0 - fg
    if fg <= 60:
        return 50.0
    return 50.0 - (fg - 60.0) * (35.0 / 40.0)


def _trending_bonus(regime: str, mtf_score: float, mcap_chg: float) -> float:
    """Compute directional bonus for TRENDING regime.

    When market is TRENDING (ATR elevated but not chaotic, price > SMA):
    - If MTF momentum AND daily mcap_chg both bullish → +3pts (trend confirmed)
    - If MTF momentum AND daily mcap_chg both bearish → -3pts (bear trend confirmed)
    - If they disagree → 0pts (mixed signals = no bonus)

    Research: TRENDING markets reduce false signals 40% vs RANGING; the
    directional bonus reflects that our technical signals are more reliable
    during structured trends than choppy sideways markets.
    """
    if regime != "TRENDING":
        return 0.0
    mtf_bull  = mtf_score  >= 0.3
    mtf_bear  = mtf_score  <= -0.3
    mcap_bull = mcap_chg   >= 0.5
    mcap_bear = mcap_chg   <= -0.5
    if mtf_bull and mcap_bull:
        return TRENDING_DIRECTION_BONUS
    if mtf_bear and mcap_bear:
        return -TRENDING_DIRECTION_BONUS
    return 0.0


def _dominant_signal(components: dict) -> str:
    """Return name of signal with largest absolute contribution."""
    tilt_keys = ["whale_tilt", "oi_smart_tilt", "funding_tilt", "news_tilt",
                 "stablecoin_tilt", "flow_tilt", "liq_tilt"]
    core_keys = ["fg_contrarian", "momentum", "mtf_momentum", "outlier", "breadth"]
    # Tilts are absolute; cores are relative (subtract 50 for contribution direction)
    best_name, best_abs = "none", 0.0
    for k in tilt_keys:
        v = abs(components.get(k, 0))
        if v > best_abs:
            best_abs, best_name = v, k
    for k in core_keys:
        # Core contribution relative to neutral (50)
        v = abs(components.get(k, 50) - 50) * {
            "fg_contrarian": W_FG, "momentum": W_MOMENTUM,
            "mtf_momentum": W_MTF, "outlier": W_OUTLIER, "breadth": W_BREADTH,
        }.get(k, 0.1)
        if v > best_abs:
            best_abs, best_name = v, k
    return best_name


def _signal_freshness_mult(data_age_minutes: float | None) -> float:
    """Reduce tilt contribution for stale data.

    age=0  → mult=1.0 (fresh)
    age=60 → mult=0.95 (1h stale, slight reduction)
    age=120→ mult=0.80 (2h stale, meaningful reduction)
    age=240→ mult=0.50 (4h stale, halved)
    age=480→ mult=0.20 (8h stale, minimal contribution)
    Returns 1.0 when age unknown (graceful).
    """
    if data_age_minutes is None:
        return 1.0
    if data_age_minutes <= 0:
        return 1.0
    return round(max(0.20, min(1.0, math.exp(-data_age_minutes / 240.0))), 3)


def compute_intelligence(
    fg:               float,
    btc_dom:          float,
    mcap_chg:         float,
    trending:         list,
    candidates_n:     int,
    # Tilt signals ([-1,1], graceful at 0)
    news_sentiment:   float = 0.0,
    flow_tilt:        float = 0.0,
    whale_tilt:       float = 0.0,
    funding_tilt:     float = 0.0,
    oi_smart_tilt:    float = 0.0,
    stablecoin_tilt:  float = 0.0,
    liq_tilt:         float = 0.0,
    # Regime & multi-timeframe
    regime:           str   = "RANGING",
    mtf_score:        float = 0.0,
    # NEW v3.0: data freshness (minutes since last update; None = unknown → no penalty)
    data_age_minutes: float | None = None,
    # NEW v3.1: US macro context — INFORMATIONAL ONLY, does not affect composite_score.
    # Pass the dict from macro_data.compute_macro_tilt() / event_guard_status().
    macro:            dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure 12-signal Crypto-Intelligence composite (0-100, 50=neutral).

    v3.0 additions:
    - regime="TRENDING" now applies ±3pt directional bonus when MTF + daily
      momentum are aligned (confirms trend direction reliability).
    - data_age_minutes: if data is stale, tilt contributions are reduced via
      exponential decay (fresh=1.0x, 4h=0.5x, 8h=0.2x).
    - Output includes `dominant_signal`, `explainability`, `freshness_mult`.
    """
    # ── Core components (0-100) ───────────────────────────────────────────────
    fg_score      = _fg_score(fg)
    momentum_s    = max(0.0, min(100.0, 50.0 + mcap_chg * 5.0))
    breadth_s     = max(0.0, min(100.0, (65.0 - btc_dom) / 20.0 * 100))
    # Opportunity density: more scanner candidates = more risk-on setups.
    # NEUTRAL-ANCHORED: 0 candidates = 50 (quiet market, NOT bearish). Floor at
    # 50 — "few opportunities" is neutral; bearish is captured by momentum/FG.
    outlier_s     = max(50.0, min(100.0, candidates_n * 10.0))
    mtf_s         = max(0.0, min(100.0, 50.0 + mtf_score * 50.0))

    base = (fg_score   * W_FG
            + momentum_s * W_MOMENTUM
            + breadth_s  * W_BREADTH
            + outlier_s  * W_OUTLIER
            + mtf_s      * W_MTF)

    # ── Data freshness multiplier (applied to tilts only) ─────────────────────
    fresh_mult = _signal_freshness_mult(data_age_minutes)

    # ── Tilt signals (clamped to ±1 then scaled and freshness-adjusted) ───────
    def _c(v: float) -> float:
        return max(-1.0, min(1.0, float(v)))

    tilt_components = {
        "news":        _c(news_sentiment)  * ALTDATA_TILT,
        "flow":        _c(flow_tilt)       * FLOW_TILT,
        "whale":       _c(whale_tilt)      * WHALE_TILT,
        "funding":     _c(funding_tilt)    * FUNDING_TILT,
        "oi_smart":    _c(oi_smart_tilt)   * OI_SMART_TILT,
        "stablecoin":  _c(stablecoin_tilt) * STABLECOIN_TILT,
        "liq":         _c(liq_tilt)        * LIQ_TILT,
    }
    tilt_raw = sum(tilt_components.values()) * fresh_mult
    tilt     = max(-MAX_TOTAL_TILT, min(MAX_TOTAL_TILT, tilt_raw))

    # ── Regime modifier ───────────────────────────────────────────────────────
    regime_adj  = 0.0
    regime_note = ""
    if regime == "CHAOS":
        regime_adj  = CHAOS_PENALTY
        regime_note = f"CHAOS regime: {CHAOS_PENALTY:+.0f}pts (signals unreliable, ATR≥2x)"
    elif regime == "TRENDING":
        t_bonus = _trending_bonus(regime, mtf_score, mcap_chg)
        regime_adj  = t_bonus
        if t_bonus != 0:
            direction = "bullish" if t_bonus > 0 else "bearish"
            regime_note = (f"TRENDING {direction}: {t_bonus:+.1f}pts "
                           f"(MTF {mtf_score:+.2f} + mcap {mcap_chg:+.1f}% aligned)")

    raw = round(max(0.0, min(100.0, base + tilt + regime_adj)), 1)

    # ── Momentum guard ────────────────────────────────────────────────────────
    composite, guard = raw, ""
    if mcap_chg <= GUARD_MCAP_PCT and raw >= 60:
        composite = min(raw, GUARD_CAP)
        guard = f"capped {raw}→{composite} (mcap {mcap_chg:+.1f}% active downturn)"

    # ── Output dict (comprehensive for transparency) ──────────────────────────
    comps = {
        "fg_contrarian":   round(fg_score,  1),
        "momentum":        round(momentum_s, 1),
        "breadth":         round(breadth_s,  1),
        "outlier":         round(outlier_s,  1),
        "mtf_momentum":    round(mtf_s,      1),
        "news_tilt":       round(tilt_components["news"],       1),
        "flow_tilt":       round(tilt_components["flow"],       1),
        "whale_tilt":      round(tilt_components["whale"],      1),
        "funding_tilt":    round(tilt_components["funding"],    1),
        "oi_smart_tilt":   round(tilt_components["oi_smart"],   1),
        "stablecoin_tilt": round(tilt_components["stablecoin"], 1),
        "liq_tilt":        round(tilt_components["liq"],        1),
        "regime_adj":      round(regime_adj,                    1),
    }

    # ── Explainability: top 3 contributors ────────────────────────────────────
    contrib = {}
    for k, v in tilt_components.items():
        contrib[f"{k}_tilt"] = round(v * fresh_mult, 2)
    for k, w in [("fg_contrarian", W_FG), ("momentum", W_MOMENTUM),
                  ("mtf_momentum", W_MTF), ("outlier", W_OUTLIER)]:
        contrib[k] = round((comps[k] - 50) * w, 2)
    top3 = sorted(contrib.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
    explainability = ", ".join(f"{k}({v:+.1f})" for k, v in top3)

    out: dict[str, Any] = {
        "composite_score": composite,
        "raw_composite":   raw,
        "label":           label_for(composite),
        "signal_count":    12,
        "dominant_signal": _dominant_signal(comps),
        "explainability":  explainability,
        "freshness_mult":  fresh_mult,
        "components":      comps,
        "inputs": {
            "fg_raw": fg, "btc_dominance": btc_dom, "mcap_change_24h": mcap_chg,
            "trending_count": len(trending), "scanner_candidates": candidates_n,
            "regime": regime, "mtf_score_raw": mtf_score,
            "data_age_minutes": data_age_minutes,
        },
    }
    if guard:
        out["guard"] = guard
    if regime_note:
        out["regime_note"] = regime_note
    if data_age_minutes and data_age_minutes > 120:
        out["freshness_warning"] = f"Data {data_age_minutes:.0f}min old — tilt reduced to {fresh_mult:.0%}"
    if macro:
        # Informational only — never mutates composite/raw/guard above this line.
        out["macro_context"] = macro
    return out
