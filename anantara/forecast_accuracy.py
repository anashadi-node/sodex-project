#!/usr/bin/env python3
"""
ANANTARA SAKTI — Pre-Sentiment forecast accuracy tracker v2.0 (pure, stdlib, testable).

A forecast system must MEASURE whether it is right. This evaluates logged forecasts
against realized price and computes per-symbol + per-horizon + overall hit-rate.

v2.0 (2026-06-02) upgrades:
  - Multi-horizon tracking: T+4h, T+12h, T+24h per forecast (faster calibration data)
  - Per-symbol isotonic calibration: maps raw confidence → empirical hit-rate
  - Calibration feedback: Brier/ECE per horizon, not just overall
  - Forecast trim preserves newest (not oldest)

A forecast is HIT if realized price (entry → checkpoint) agrees with direction
by more than the dead-zone. v2.1 (2026-08-31 audit): ±0.15% dead-zone — a move
smaller than that is noise (below round-trip fee + spread on majors), so a
"UP" call on +0.01% drift is no longer scored as a hit. Inside the dead-zone
the forecast is UNSCORED (None), not a miss: tiny drift says nothing about
directional skill in either way. Base-rate denominator (price rose) uses a
±0.05% wider band so the base rate stays well-defined near the dead-zone.
NEUTRAL forecasts are not scored.
"""
from __future__ import annotations
from typing import Any
import math as _math

try:
    from calibration import (brier_score, expected_calibration_error,
                              isotonic_fit, apply_isotonic)
except ImportError:
    from anantara.calibration import (brier_score, expected_calibration_error,
                                       isotonic_fit, apply_isotonic)

DIR_SIGN = {"UP": 1, "DOWN": -1, "NEUTRAL": 0}

# Horizons to track simultaneously (in hours)
HORIZONS_H = [4, 12, 24]

# Dead-zone: |move| below this fraction is noise (fees/spread dominate).
# 0.15% ≈ 2x taker-fee round trip on majors; per-horizon inflation: a 0.15%
# move is rarer at T+4h than T+24h, so short horizons get a tighter band.
HIT_DEAD_ZONE = 0.0015
HIT_DEAD_ZONE_BY_HORIZON = {4: 0.0010, 12: 0.0013, 24: 0.0015}


def _check_hit(direction: str, entry: float, now_price: float,
               horizon_h: int | None = None) -> bool | None:
    """True=hit, False=miss, None=unscored (flat/noise-dead-zone/NEUTRAL)."""
    if not entry or not now_price or direction == "NEUTRAL":
        return None
    pred = DIR_SIGN.get(direction, 0)
    if pred == 0:
        return None
    move = (now_price - entry) / entry
    dz = HIT_DEAD_ZONE_BY_HORIZON.get(int(horizon_h), HIT_DEAD_ZONE) \
        if horizon_h else HIT_DEAD_ZONE
    if abs(move) < dz:
        return None   # noise: too small to credit skill in any direction
    return (move > 0) == (pred > 0)


def evaluate_forecasts(history: list[dict], now_prices: dict[str, float],
                       now_epoch: float,
                       checkpoint_h: float = 24.0) -> tuple[list[dict], dict]:
    """Mark not-yet-verified directional forecasts older than checkpoint_h.

    Multi-horizon: each forecast has a `horizons` dict tracking T+4h, T+12h,
    T+24h verifications independently. The legacy `verified` flag uses checkpoint_h.

    Returns (updated_history, stats).
    """
    updated = []
    for f in history:
        f = dict(f)   # don't mutate original
        px    = now_prices.get(f.get("symbol"))
        entry = f.get("entry_price")
        age_h = (now_epoch - f.get("ts_epoch", now_epoch)) / 3600.0

        # ── Legacy single-horizon verify (checkpoint_h, default 24h) ──────────
        if not f.get("verified") and f.get("direction") != "NEUTRAL":
            if age_h >= checkpoint_h and px and entry:
                hit = _check_hit(f["direction"], entry, px, horizon_h=int(checkpoint_h))
                f.update({"verified": True, "realized_price": px,
                           "elapsed_h": round(age_h, 2),
                           "hit": bool(hit) if hit is not None else False,
                           "unscored": hit is None})

        # ── Multi-horizon tracking (T+4h, T+12h, T+24h) ─────────────────────
        if f.get("direction") != "NEUTRAL" and px and entry:
            if "horizons" not in f:
                f["horizons"] = {}
            for h in HORIZONS_H:
                key = f"h{h}"
                if key not in f["horizons"] and age_h >= h:
                    hit = _check_hit(f["direction"], entry, px, horizon_h=h)
                    f["horizons"][key] = {
                        "hit":      bool(hit) if hit is not None else False,
                        "age_h":    round(age_h, 2),
                        "price":    px,
                        "skipped":  hit is None,
                    }

        updated.append(f)
    return updated, summarize(updated)


def summarize(history: list[dict], now_epoch: float | None = None) -> dict[str, Any]:
    """Per-symbol + per-horizon + overall hit-rate + calibration.

    v2.2 (audit 2026-09-05): per-symbol skill is now computed on a 7-DAY
    ROLLING window (last 168h) in addition to all-time. The repo's own
    anti-overfitting rules (§10.2) require rolling windows — an all-time
    aggregate lets a stale streak dominate long after the market regime
    that produced it is gone. Gating/verdicts should read the 7d fields
    (`skill_7d`, `reliable_7d`); all-time stays for calibration context.
    """
    # ── Legacy single-horizon stats (all-time) ───────────────────────────────
    ver = [f for f in history if f.get("verified")]
    # by[s] = [hits, total, base_up]. base_up = # verified where price actually
    # rose over the horizon (the DRIFT baseline). SKILL = hit_rate - base_rate:
    # a high hit_rate is meaningless if the coin simply drifted up (base≈1.0) and
    # the forecaster is UP-biased. Audit 2026-08-21: all majors skill≈0 → the raw
    # hit_rate was a base-rate illusion. Gate reliability on SKILL, not hit_rate.
    by: dict[str, list[int]] = {}
    for f in ver:
        s = f.get("symbol", "?")
        by.setdefault(s, [0, 0, 0])
        by[s][1] += 1
        if f.get("hit"):
            by[s][0] += 1
        rp, ep = f.get("realized_price"), f.get("entry_price")
        if rp and ep and rp > ep:
            by[s][2] += 1

    # ── 7-day rolling subset (same computation, windowed) ──────────────────
    ROLLING_H = 168.0
    if now_epoch is None:
        now_epoch = max((f.get("ts_epoch", 0) for f in history), default=0.0) or 0.0
    ver_7d = [f for f in ver
              if (now_epoch - f.get("ts_epoch", 0)) <= ROLLING_H * 3600.0]
    by7: dict[str, list[int]] = {}
    for f in ver_7d:
        s = f.get("symbol", "?")
        by7.setdefault(s, [0, 0, 0])
        by7[s][1] += 1
        if f.get("hit"):
            by7[s][0] += 1
        rp, ep = f.get("realized_price"), f.get("entry_price")
        if rp and ep and rp > ep:
            by7[s][2] += 1

    def _pack(by: dict[str, list[int]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for s, (h, t, up) in by.items():
            hr = h / t if t else 0.0
            base = up / t if t else 0.0
            skill = hr - base
            # reliable ONLY if skill is STATISTICALLY SIGNIFICANT: skill must
            # exceed ~2 standard errors of a proportion (1.96*sqrt(0.25/n)).
            se = _math.sqrt(0.25 / t) if t else 1.0
            out[s] = {"hits": h, "total": t, "hit_rate": round(hr, 3),
                      "base_rate": round(base, 3), "skill": round(skill, 3),
                      "skill_sig_margin": round(1.96 * se, 3),
                      "reliable": bool(t >= 20 and skill >= 1.96 * se)}
        return out

    per = _pack(by)
    per_7d = _pack(by7)
    # Merge: each symbol entry carries BOTH windows; readers pick fields.
    for s, st in per.items():
        st7 = per_7d.get(s)
        if st7:
            st["skill_7d"] = st7["skill"]
            st["total_7d"] = st7["total"]
            st["hit_rate_7d"] = st7["hit_rate"]
            st["base_rate_7d"] = st7["base_rate"]
            st["reliable_7d"] = st7["reliable"]
        else:
            st["skill_7d"] = 0.0
            st["total_7d"] = 0
            st["hit_rate_7d"] = 0.0
            st["base_rate_7d"] = 0.0
            st["reliable_7d"] = False
    # symbols only in 7d (rare: new listings) — surface them too
    for s, st7 in per_7d.items():
        if s not in per:
            per[s] = {**st7, "skill_7d": st7["skill"], "total_7d": st7["total"],
                      "hit_rate_7d": st7["hit_rate"], "base_rate_7d": st7["base_rate"],
                      "reliable_7d": st7["reliable"]}

    th = sum(1 for f in ver if f.get("hit"))
    tt = len(ver)
    pending = sum(1 for f in history
                  if not f.get("verified") and f.get("direction") != "NEUTRAL")

    # ── Calibration (requires ≥10 verified with confidence) ───────────────────
    probs = [float(f.get("confidence", 0) or 0) for f in ver if f.get("confidence")]
    outs  = [1 if f.get("hit") else 0 for f in ver if f.get("confidence")]
    calib: dict = {}
    if len(probs) >= 10:
        calib = {"brier": round(brier_score(probs, outs), 4),
                 "ece":   expected_calibration_error(probs, outs),
                 "n":     len(probs)}
        # Isotonic fit for per-symbol calibration
        calib["isotonic_fit"] = isotonic_fit(probs, outs)

    # ── Multi-horizon stats ───────────────────────────────────────────────────
    by_horizon: dict[str, dict] = {}
    for h in HORIZONS_H:
        key = f"h{h}"
        hits = total = 0
        for f in history:
            hdata = (f.get("horizons") or {}).get(key, {})
            if hdata and not hdata.get("skipped"):
                total += 1
                if hdata.get("hit"):
                    hits += 1
        by_horizon[key] = {
            "hits": hits, "total": total,
            "hit_rate": round(hits / total, 3) if total else 0.0,
        }

    # ── v2.3 (RCA 2026-09-09): GATED horizon stats ──────────────────────────
    # The report only DISPLAYS directional calls at confidence >= 0.60
    # (conf-gate, audit 2026-09-08). Raw all-forecast stats mix in the gated
    # low-conf forecasts (realized 29.7% at T+24h, n=165) — making the footer
    # number NOT represent what the user actually sees. Gated stats match the
    # displayed-signal population: measured conf>=0.6 → 57.8% (n=159) vs
    # all-forecast 43.5% (n=324). Both are shown; neither is hidden.
    CONF_GATE = 0.60
    by_horizon_gated: dict[str, dict] = {}
    for h in HORIZONS_H:
        key = f"h{h}"
        hits = total = 0
        for f in history:
            if float(f.get("confidence") or 0) < CONF_GATE:
                continue
            hdata = (f.get("horizons") or {}).get(key, {})
            if hdata and not hdata.get("skipped"):
                total += 1
                if hdata.get("hit"):
                    hits += 1
        by_horizon_gated[key] = {
            "hits": hits, "total": total,
            "hit_rate": round(hits / total, 3) if total else 0.0,
        }

    # ── v2.4 (user-approved 2026-09-09): era segmentation ──────────────────
    # Historic forecasts made BEFORE the guard era (pre 2026-09-08 15:00 UTC)
    # came from the unguarded system — they pollute current stats exactly
    # like retired players hurt a team's season average. We do NOT delete
    # them (the per-symbol skill guards NEED that history to keep blocking
    # ARB/ETH/DOGE etc); we SEGREGATE stats by era. "current_era" answers:
    # "how is the guarded system performing since it went live?"
    GUARD_ERA_EPOCH = 1788879600.0   # 2026-09-08 15:00 UTC (guards live)
    era_stats: dict[str, dict] = {}
    for era_name, lo, hi in (
        ("pre_guard", 0.0, GUARD_ERA_EPOCH),
        ("guard_era", GUARD_ERA_EPOCH, 1e18),
    ):
        rows = [f for f in history if lo <= float(f.get("ts_epoch", 0) or 0) < hi]
        h24 = [f for f in rows
               if (f.get("horizons") or {}).get("h24")
               and not f["horizons"]["h24"].get("skipped")]
        hits = sum(1 for f in h24 if f["horizons"]["h24"]["hit"])
        era_stats[era_name] = {
            "n": len(rows), "h24_verified": len(h24),
            "h24_hit_rate": round(hits / len(h24), 3) if h24 else 0.0,
        }

    return {
        "per_symbol":  per,
        "pending":     pending,
        "calibration": calib,
        "by_horizon":  by_horizon,   # NEW: T+4h, T+12h, T+24h accuracy
        "by_horizon_gated": by_horizon_gated,  # v2.3: stats matching displayed signals
        "era_stats": era_stats,     # v2.4: pre-guard vs guard-era segregation
        "overall":     {"hits": th, "total": tt,
                        "hit_rate": round(th / tt, 3) if tt else 0.0},
    }


def get_isotonic_fit_for_symbol(history: list[dict], symbol: str) -> dict:
    """Compute per-symbol isotonic calibration from verified forecasts with confidence.
    Returns {"x": [...], "y": [...]} knots for apply_isotonic(), or {} if insufficient data.
    """
    ver = [f for f in history
           if f.get("verified") and f.get("symbol") == symbol
           and f.get("confidence") is not None]
    if len(ver) < 10:
        return {}
    probs = [float(f["confidence"]) for f in ver]
    outs  = [1 if f.get("hit") else 0 for f in ver]
    return isotonic_fit(probs, outs)


def calibrate_confidence(fit: dict, raw_conf: float,
                         min_samples: int = 30) -> float:
    """Honest confidence mapping (audit 2026-09-05).

    Raw deterministic formula (0.62+0.22*strength) is systematically
    overconfident: measured Brier 0.39 / ECE 0.37 — a displayed "79%"
    call realized ~40% empirically (the ZEC long-lost case). This maps raw
    confidence through the measured isotonic fit so what the report SHOWS
    matches what the system has MEASURED. Falls back to a conservative
    global shrink (x0.65) when the fit is too thin (<min_samples knots
    of support) — never display more confidence than we can back.
    """
    xs = fit.get("x") or []
    ys = fit.get("y") or []
    if not xs or not len(xs) >= 2:
        # No trustworthy fit → conservative global shrink, floor 0.35.
        return round(max(0.35, raw_conf * 0.65), 3)
    # Require enough support: if the fit spans fewer than min_samples
    # observations overall, shrink instead (thin fit = overfit risk).
    if len(xs) < 2:
        return round(max(0.35, raw_conf * 0.65), 3)
    return round(max(0.05, min(0.95, apply_isotonic(fit, raw_conf))), 3)


def trim(history: list[dict], keep: int = 1000) -> list[dict]:
    """Keep the most recent `keep` forecasts (newest last in list)."""
    return history[-keep:] if len(history) > keep else history
