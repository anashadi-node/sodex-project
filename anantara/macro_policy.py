"""Production-safe macro policy for SoDEX + CEX.

Converts macro context into conservative risk controls. DXY/VIX macro_tilt is
informational only until OOS evidence exists; automated controls are limited to
high-impact event proximity.
"""
from __future__ import annotations

from typing import Any

PRE_EVENT_HOURS = 24.0
RISK_OFF_TILT = -0.25
RISK_ON_TILT = 0.25


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def assess_macro_policy(ctx: dict[str, Any] | None) -> dict[str, Any]:
    """Return conservative macro controls from /macro/current-like context."""
    ctx = ctx or {}
    event_guard = ctx.get("event_guard") or {}
    next_event = event_guard.get("next_event") or {}
    tilt_ctx = ctx.get("macro_tilt") or {}
    tilt = _f(tilt_ctx.get("macro_tilt"), 0.0)
    confidence = str(tilt_ctx.get("confidence") or "no_data")

    active_event = bool(event_guard.get("active"))
    hours_until = _f(next_event.get("hours_until"), 999999.0)
    pre_event_24h = (not active_event) and 0.0 <= hours_until <= PRE_EVENT_HOURS

    directional_bias = "NEUTRAL"
    # macro_tilt is currently labeled *_n0_backtest in macro_data.py: useful
    # telemetry, but not validated enough to drive automated controls.
    tilt_validated = confidence.startswith(("validated", "oos_", "live_oos"))
    if tilt_validated and tilt <= RISK_OFF_TILT:
        directional_bias = "RISK_OFF"
    elif tilt_validated and tilt >= RISK_ON_TILT:
        directional_bias = "RISK_ON"

    policy = {
        "level": "NORMAL",
        "event": event_guard.get("event") or next_event.get("event"),
        "phase": event_guard.get("phase"),
        "hours_until": round(hours_until, 2) if hours_until < 999999.0 else None,
        "macro_tilt": round(tilt, 3),
        "directional_bias": directional_bias,
        "active_event_window": active_event,
        "pre_event_24h": pre_event_24h,
        "block_new_entries": False,
        "block_new_spot_long": False,
        "disable_fast_track": False,
        "cex_threshold_mult": 1.0,
        "sodex_capital_mult": 1.0,
        "sodex_spread_add_pct": 0.0,
        "reason": "macro normal",
    }

    if active_event:
        policy.update({
            "level": "ORANGE",
            "block_new_entries": True,
            "block_new_spot_long": True,
            "disable_fast_track": True,
            "cex_threshold_mult": 1.50,
            "sodex_capital_mult": 0.50,
            "sodex_spread_add_pct": 0.08,
            "reason": f"macro release window active: {policy['event'] or 'event'}",
        })
    elif pre_event_24h:
        policy.update({
            "level": "YELLOW",
            "disable_fast_track": True,
            "cex_threshold_mult": 1.20,
            "sodex_capital_mult": 0.75,
            "sodex_spread_add_pct": 0.04,
            "reason": f"macro pre-event T-24h: {policy['event']} in {hours_until:.1f}h",
        })

    if directional_bias != "NEUTRAL" and policy["level"] == "NORMAL":
        policy.update({
            "level": "YELLOW",
            "cex_threshold_mult": 1.10,
            "sodex_capital_mult": 0.85,
            "sodex_spread_add_pct": 0.03,
            "reason": f"macro tilt {directional_bias.lower()} {tilt:+.2f}",
        })
    return policy


def side_threshold_mult(policy: dict[str, Any], side: str) -> float:
    """Extra threshold only for side opposing macro tilt; never boosts side."""
    side_l = str(side).lower()
    bias = policy.get("directional_bias")
    if bias == "RISK_OFF" and side_l == "long":
        return 1.15
    if bias == "RISK_ON" and side_l == "short":
        return 1.15
    return 1.0
