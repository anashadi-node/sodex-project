#!/usr/bin/env python3
"""
ANANTARA SAKTI — Pre-Sentiment multi-horizon ensemble (pure, stdlib-only).

Combines three independent signals into ONE honest forecast:
    1. LLM forecast          (Hermes — T+24h reasoning)
    2. Deterministic rules   (momentum composite from presentiment_data)
    3. Empirical base-rate   (measured drift / reliability from forecast_accuracy)

Horizons: T+4h, T+12h, T+24h (Swing band 1-30h → per-horizon resolution).

Principles:
    - FAIL-CLOSED: disagreement between confident signals → NEUTRAL, not a coin flip.
    - SHRINK-TO-REALITY: measured reliability (skill/base-rate) scales confidence.
    - REGIME-AWARE: CHAOS regime caps confidence (cannot trust momentum in noise).
    - PURE: no I/O → unit-testable offline.

Backward-compatible output superset of anantara/forecast.blend_forecast keys
(direction, confidence, reasoning, suggested_action, trade_eligible, quality,
 signal_agreement, confidence_range, horizon_hint).
"""
from __future__ import annotations
from typing import Any

try:  # package context (repo tests: anantara.presentiment_forecast)
    from .presentiment_data import momentum_composite  # reuse pure indicator math
except ImportError:  # pragma: no cover - flat /app container context
    from presentiment_data import momentum_composite

HORIZONS_H: tuple[int, ...] = (4, 12, 24)

# Shorter horizons are noisier → require STRONGER momentum to commit, and are
# trusted LESS even when committed (confidence multiplier).
NEUTRAL_THRESHOLD: dict[int, float] = {4: 0.30, 12: 0.35, 24: 0.40}
HORIZON_CONF_MULT: dict[int, float] = {4: 0.80, 12: 0.95, 24: 1.00}

# Regime confidence caps.
REGIME_CONF_CAP: dict[str, float] = {"TRENDING": 0.92, "RANGING": 0.75, "CHAOS": 0.45}

# ── v3.1 accuracy upgrades ────────────────────────────────────────────────────
# MTF alignment (per-asset multi-timeframe agreement).
MTF_ALIGNED_BOOST   = 0.05   # all TFs agree → confidence boost (bounded)
MTF_CONFLICT_DISCOUNT = 0.85 # TFs disagree → dampen committed signal
# Volume confirmation: momentum without volume is noise-prone.
LOW_VOL_RATIO       = 0.70   # vol_ratio below this → thin participation
LOW_VOL_CONF_CAP    = 0.65   # cap confidence when volume doesn't confirm
VOL_CONFIRM_BOOST   = 0.02   # vol_ratio >= 1.2 with directional momentum → small boost
HIGH_VOL_RATIO      = 1.20
# Horizon decay: T+24h forecasts verified over longer spans are less certain
# than fresh T+4h reads; scale the anchor confidence per horizon for display.
HORIZON_DECAY: dict[int, float] = {4: 1.00, 12: 0.97, 24: 0.94}


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def deterministic_direction(momentum_score: float, horizon_h: int) -> str:
    thr = NEUTRAL_THRESHOLD.get(horizon_h, 0.40)
    if momentum_score >= thr:
        return "UP"
    if momentum_score <= -thr:
        return "DOWN"
    return "NEUTRAL"


def deterministic_confidence(momentum_score: float, horizon_h: int) -> float:
    """Confidence for a committed deterministic call. NEUTRAL → low baseline."""
    direction = deterministic_direction(momentum_score, horizon_h)
    if direction == "NEUTRAL":
        return round(clamp(0.30 + abs(momentum_score)), 3)
    base = 0.62 + 0.22 * abs(momentum_score)
    return round(clamp(base, 0.55, 0.86) * HORIZON_CONF_MULT.get(horizon_h, 1.0), 3)


def empirical_prior(stats: dict[str, Any] | None, horizon_h: int = 24) -> dict[str, Any] | None:
    """Derive an empirical drift prior from measured base-rate + reliability.

    stats is the per-symbol entry of forecast_accuracy.summarize()["per_symbol"]:
        {hits, total, hit_rate, base_rate, skill, skill_sig_margin, reliable}

    Returns None when the sample is too small or shows no directional drift.
    """
    if not stats:
        return None
    total = int(stats.get("total", 0) or 0)
    if total < 8:
        return None
    base_rate = float(stats.get("base_rate", 0.5) or 0.5)
    skill = float(stats.get("skill", 0.0) or 0.0)
    reliable = bool(stats.get("reliable", False))
    if abs(base_rate - 0.5) < 0.08:
        return None  # no drift edge
    direction = "UP" if base_rate > 0.5 else "DOWN"
    conf = clamp(0.45 + abs(skill), 0.40, 0.72)
    if not reliable:
        conf = min(conf, 0.50)  # weak tiebreaker only
    return {"direction": direction, "confidence": round(conf, 3),
            "reliable": reliable, "base_rate": base_rate, "source": "empirical"}


def _blend_llm_rule(llm: dict[str, Any] | None, det_dir: str,
                    det_conf: float) -> tuple[str, float, str]:
    """Blend LLM + deterministic into (direction, confidence, reason)."""
    llm_dir = "NEUTRAL"
    llm_conf = 0.0
    if llm:
        llm_dir = str(llm.get("direction", "NEUTRAL")).upper()
        try:
            llm_conf = clamp(float(llm.get("confidence", 0) or 0))
        except (TypeError, ValueError):
            llm_conf = 0.0

    if det_dir == "NEUTRAL":
        if llm_dir == "NEUTRAL" or llm_conf < 0.55:
            return "NEUTRAL", round(min(0.45, det_conf, llm_conf), 3), "no_trend"
        return llm_dir, round(llm_conf, 3), "llm_only"

    if llm_dir == "NEUTRAL" or llm_conf < 0.55:
        # Deterministic leads (LLM indecisive/absent).
        return det_dir, round(min(0.72, det_conf * 0.95), 3), "rule_override"

    if llm_dir == det_dir:
        # Agreement → boost (bounded).
        boost = 0.05 * min(llm_conf, det_conf)
        conf = min(0.92, max(llm_conf, det_conf) + boost)
        return llm_dir, round(conf, 3), "agreement"

    # Confident disagreement → fail closed.
    conf = min(0.40, max(llm_conf, det_conf) * 0.5)
    return "NEUTRAL", round(conf, 3), "conflict"


def _apply_prior(direction: str, conf: float,
                 prior: dict[str, Any] | None) -> tuple[str, float]:
    if not prior or direction == "NEUTRAL":
        return direction, conf
    if prior["direction"] == direction:
        return direction, round(min(0.90, conf + 0.03), 3)
    # Prior disagrees → discount, but don't override a committed signal.
    return direction, round(min(conf, 0.55), 3)


def _suggested_action(direction: str, trade_eligible: bool) -> str:
    if not trade_eligible:
        return "WAIT"
    return {"UP": "BUY", "DOWN": "SELL"}.get(direction, "WAIT")


def compute_signal_agreement(llm_dir: str, rule_dir: str,
                             prior_dir: str | None) -> float:
    """Agreement in [-1, +1] across the directional signals."""
    dirs = [d for d in (llm_dir, rule_dir, prior_dir) if d in ("UP", "DOWN")]
    if not dirs:
        return 0.0
    ups = sum(1 for d in dirs if d == "UP")
    downs = sum(1 for d in dirs if d == "DOWN")
    return round((ups - downs) / len(dirs), 3)


def compute_confidence_range(conf: float, agreement: float, n_verified: int) -> list[float]:
    """Honest [lo, hi] band. Widens with weak agreement and shrinks with data."""
    spread = 0.22 - 0.06 * min(abs(agreement), 1.0)
    if n_verified >= 20:
        spread *= 0.75
    lo = clamp(conf - spread, 0.0, 1.0)
    hi = clamp(conf + spread, 0.0, 1.0)
    return [round(lo, 3), round(hi, 3)]


def _apply_mtf(direction: str, conf: float,
               mtf_composite_v: float | None, mtf_aligned: bool | None) -> tuple[str, float]:
    """Per-asset multi-timeframe alignment adjustment.

    aligned + same direction → boost; conflicting TFs → dampen. NEUTRAL untouched.
    """
    if direction == "NEUTRAL" or mtf_composite_v is None:
        return direction, conf
    mtf_dir = "UP" if mtf_composite_v > 0 else ("DOWN" if mtf_composite_v < 0 else "NEUTRAL")
    if mtf_aligned and mtf_dir == direction:
        return direction, round(min(0.92, conf + MTF_ALIGNED_BOOST), 3)
    if not mtf_aligned and mtf_dir not in ("NEUTRAL", direction):
        # Higher-TF weight (1d=0.45) disagrees with the 1h read → dampen.
        return direction, round(conf * MTF_CONFLICT_DISCOUNT, 3)
    return direction, conf


def _apply_volume_filter(conf: float, vol_ratio: float | None,
                         momentum_score: float) -> float:
    """Volume confirmation filter.

    Thin volume (< LOW_VOL_RATIO) caps confidence — momentum without
    participation is noise-prone. Strong volume with directional momentum
    earns a small bounded boost.
    """
    if vol_ratio is None or momentum_score == 0:
        return conf
    if vol_ratio < LOW_VOL_RATIO:
        return round(min(conf, LOW_VOL_CONF_CAP), 3)
    if vol_ratio >= HIGH_VOL_RATIO:
        return round(min(0.92, conf + VOL_CONFIRM_BOOST), 3)
    return conf


def ensemble_forecast(llm: dict[str, Any] | None,
                      tech: dict[str, Any] | None,
                      symbol_stats: dict[str, Any] | None = None,
                      regime: str = "RANGING",
                      horizons: tuple[int, ...] = HORIZONS_H,
                      calib_fit: dict | None = None) -> dict[str, Any]:
    """Produce the final multi-horizon ensemble forecast.

    Args:
        llm: Hermes LLM forecast dict (direction/confidence/reasoning/...).
        tech: presentiment_data.Snapshot.to_dict() or _sodex_technicals() dict.
        symbol_stats: per-symbol accuracy stats from forecast_accuracy.
        regime: market regime (TRENDING / RANGING / CHAOS).
        calib_fit: global isotonic fit (forecast_accuracy calibration) —
            when present, the anchor deterministic confidence is mapped
            through it so displayed confidence ≈ measured hit-rate
            (audit 2026-09-05, was systematically overconfident: ECE 0.37).

    Returns a forecast dict with direction, confidence, confidence_range,
    signal_agreement, trade_eligible, quality, horizons (per-horizon detail),
    and an ensemble provenance block.
    """
    score = float((tech or {}).get("momentum_score", 0.0) or 0.0)
    adx = float((tech or {}).get("adx", 0.0) or 0.0)
    vol_ratio = (tech or {}).get("vol_ratio")
    try:
        vol_ratio = float(vol_ratio) if vol_ratio is not None else None
    except (TypeError, ValueError):
        vol_ratio = None
    mtf_composite_v = (tech or {}).get("mtf_composite_v")
    mtf_aligned = (tech or {}).get("mtf_aligned")
    llm_dir = str((llm or {}).get("direction", "NEUTRAL")).upper()
    prior = empirical_prior(symbol_stats, 24)

    # Per-horizon deterministic detail.
    horizons_out: dict[str, Any] = {}
    for h in horizons:
        d = deterministic_direction(score, h)
        horizons_out[f"h{h}"] = {
            "direction": d,
            "confidence": deterministic_confidence(score, h),
            "horizon_h": h,
        }

    # Anchor blend at T+24h (project's primary swing horizon).
    det_dir = horizons_out["h24"]["direction"]
    det_conf = horizons_out["h24"]["confidence"]
    # Honest calibration: map raw deterministic confidence through the
    # measured global fit (audit 2026-09-05). Falls back to raw when absent.
    if calib_fit:
        try:
            from forecast_accuracy import calibrate_confidence
            det_conf = calibrate_confidence(calib_fit, det_conf)
        except Exception:
            pass   # keep raw confident if calibration unavailable
        horizons_out["h24"]["confidence"] = det_conf
    direction, conf, reason = _blend_llm_rule(llm, det_dir, det_conf)
    direction, conf = _apply_prior(direction, conf, prior)

    # v3.1 accuracy upgrades: per-asset MTF alignment + volume confirmation.
    direction, conf = _apply_mtf(direction, conf, mtf_composite_v, mtf_aligned)
    conf = _apply_volume_filter(conf, vol_ratio, score)

    # Regime cap (CHAOS can't be trusted; RANGING moderately).
    cap = REGIME_CONF_CAP.get(str(regime).upper(), 0.75)
    if direction != "NEUTRAL":
        conf = round(min(conf, cap), 3)
    else:
        conf = round(min(conf, 0.45), 3)

    agreement = compute_signal_agreement(llm_dir, det_dir,
                                         prior["direction"] if prior else None)
    n_verified = int((symbol_stats or {}).get("total", 0) or 0)
    trade_eligible = (
        direction in {"UP", "DOWN"}
        and conf >= 0.55
        and abs(agreement) >= 0.40
    )
    quality = "OK" if trade_eligible else "WEAK_SIGNAL"

    # Reasoning (max ~2 sentences, deterministic provenance).
    reasons = {
        "agreement": "technical momentum and LLM agree",
        "rule_override": "deterministic momentum overrides indecisive LLM",
        "llm_only": "LLM leads with no confirming momentum",
        "conflict": "confident signals disagree — fail-closed to NEUTRAL",
        "no_trend": "no directional trend — NEUTRAL",
    }
    reasoning = reasons.get(reason, "blended signal")
    if prior:
        reasoning += (f"; empirical prior {prior['direction']} "
                      f"(base_rate {prior.get('base_rate', 0)}) "
                      f"{'supports' if prior['direction'] == direction else 'opposes'}")
    if adx < 20 and direction != "NEUTRAL":
        reasoning += "; weak ADX"
    if mtf_aligned and direction != "NEUTRAL":
        reasoning += "; MTF aligned"
    elif direction != "NEUTRAL" and mtf_composite_v is not None \
            and abs(mtf_composite_v) > 0.05:
        reasoning += "; MTF conflict"
    if vol_ratio is not None and vol_ratio < LOW_VOL_RATIO and direction != "NEUTRAL":
        reasoning += "; thin volume"

    return {
        "direction": direction,
        "confidence": round(conf, 3),
        "confidence_range": compute_confidence_range(conf, agreement, n_verified),
        "signal_agreement": agreement,
        "trade_eligible": trade_eligible,
        "quality": quality,
        "suggested_action": _suggested_action(direction, trade_eligible),
        "reasoning": reasoning,
        "horizon_hint": "T+24h",
        "momentum_score": score,
        "horizons": horizons_out,
        "ensemble": {
            "llm": {"direction": llm_dir,
                    "confidence": (llm or {}).get("confidence", 0)},
            "deterministic": {"direction": det_dir, "confidence": det_conf},
            "empirical": prior,
            "regime": str(regime).upper(),
            "adx": adx,
            "mtf_composite": mtf_composite_v,
            "mtf_aligned": mtf_aligned,
            "vol_ratio": vol_ratio,
        },
    }
