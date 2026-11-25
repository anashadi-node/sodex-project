#!/usr/bin/env python3
"""Read-only SoDEX weekly target policy.

This module converts the farming doctrine into a deterministic operating policy.
It never places, cancels, or signs orders; it only recommends the safest lane for
the current weekly state.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TARGET_WEEKLY_VOLUME_USD = 1_300_000.0
TARGET_WIN_RATE = 0.69
DEFAULT_HORIZON_HOURS = 96
RATIO_RECOVERY_MAX_CYCLES_DAILY = 288
RATIO_RECOVERY_MAX_NOTIONAL_USD = 2_500.0
RATIO_RECOVERY_EQUITY_FRACTION = 0.30
RATIO_RECOVERY_OPERATOR_DAILY_LOSS_BUDGET_USD = 100.0
DEFAULT_INTEL_DIR = Path(__file__).resolve().parents[1] / "freqtrade_user_data" / "data" / "binance" / "intelligence"
DEFAULT_INTEL_MAX_AGE_MINUTES = 90.0
WIB = timezone(timedelta(hours=7))
BASE_VOLUME_LOSS_RATIO = 7_000.0
EMERGENCY_VOLUME_LOSS_RATIO = 5_100.0
EMERGENCY_RATIO_UNTIL_WIB = datetime(2026, 7, 18, 9, 30, tzinfo=WIB)
TARGET_VOLUME_FEE_RATIO = (
    EMERGENCY_VOLUME_LOSS_RATIO
    if datetime.now(WIB) <= EMERGENCY_RATIO_UNTIL_WIB
    else BASE_VOLUME_LOSS_RATIO
)
MIN_REAL_VOLUME_LOSS_RATIO = TARGET_VOLUME_FEE_RATIO
EVENT_END_WIB = datetime(2026, 7, 25, tzinfo=WIB)
DEADLINE_FLEX_DAYS = 35.0


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return bool(value)


def _official_volume(report: dict[str, Any]) -> tuple[bool, float, float, float]:
    official = report.get("official_dashboard") or {}
    volume = official.get("volume") or {}
    ok = official.get("quality") == "OK" and bool(official.get("canonical"))
    if not ok:
        return False, 0.0, 0.0, 0.0
    spot = _num(volume.get("spot_usd"))
    perps = _num(volume.get("perps_usd"))
    total = _num(volume.get("total_usd"), spot + perps)
    return True, total, spot, perps


def _ledger_facts(report: dict[str, Any]) -> dict[str, float | bool | None]:
    ledger = report.get("ledger") or {}
    costs = ledger.get("costs") or {}
    pnl = ledger.get("pnl") or {}
    rts = ledger.get("rts") or {}
    coverage = ledger.get("coverage") or {}
    win_rate = rts.get("win_rate")
    return {
        "fees_usd": _num(costs.get("fees_usd")),
        "realized_pnl_usd": _num(pnl.get("realized_net_usd")),
        "win_rate": _num(win_rate) if win_rate is not None else None,
        "e1_covers_all_fees": _bool(coverage.get("e1_covers_all_fees")),
        "combined_no_loss": _bool(coverage.get("combined_no_loss"), True),
    }


def _open_perp_count(report: dict[str, Any]) -> int:
    account = report.get("account") or {}
    truth = account.get("position_truth") or {}
    if isinstance(truth, dict) and "open_count" in truth:
        return int(_num(truth.get("open_count")))
    assets = account.get("assets") or {}
    positions = assets.get("perps_positions") or []
    return len(positions) if isinstance(positions, list) else 0


def _position_truth_unverified(report: dict[str, Any]) -> bool:
    account = report.get("account") or {}
    if "position_truth" not in account:
        return False
    truth = account.get("position_truth") or {}
    if not isinstance(truth, dict):
        return True
    return str(truth.get("quality") or "") != "OK"


def _halt_active(report: dict[str, Any]) -> bool:
    halt = report.get("halt_status") or {}
    return bool(halt.get("active"))


def _equity(report: dict[str, Any]) -> float:
    account = report.get("account") or {}
    account_value = account.get("account_value") or {}
    return _num(account_value.get("total_equity_usd"))


def days_to_event_end(now: datetime | None = None) -> float:
    current = now or datetime.now(WIB)
    if current.tzinfo is None:
        current = current.replace(tzinfo=WIB)
    seconds = max(0.0, (EVENT_END_WIB - current.astimezone(WIB)).total_seconds())
    return seconds / 86400.0


def _read_latest_intel_signal(intel_dir: Path = DEFAULT_INTEL_DIR) -> dict[str, Any] | None:
    try:
        files = sorted(Path(intel_dir).glob("intel_*.jsonl"))
        if not files:
            return None
        last_line = ""
        with files[-1].open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last_line = line
        if not last_line:
            return None
        payload = json.loads(last_line)
        age_min = (time.time() - _num(payload.get("ts"))) / 60.0
        btc_eligible = bool(payload.get("fc_BTC_eligible", True))
        return {
            "score": _num(payload.get("composite_score"), 50.0),
            "btc_dir": int(_num(payload.get("fc_BTC_dir_enc"), 1.0)) if btc_eligible else 0,
            "btc_conf": _num(payload.get("fc_BTC_conf")) if btc_eligible else 0.0,
            "btc_agreement": _num(payload.get("fc_BTC_agreement"), _num(payload.get("fc_BTC_conf"))) if btc_eligible else 0.0,
            "btc_eligible": btc_eligible,
            "btc_quality": str(payload.get("fc_BTC_quality") or ""),
            "event_risk": str(payload.get("event_risk_level") or ""),
            "event_risk_score": _num(payload.get("event_risk_score")),
            "age_min": round(age_min, 1),
        }
    except Exception:
        return None


def read_intel_signal(
    intel_dir: Path = DEFAULT_INTEL_DIR,
    *,
    max_age_min: float = DEFAULT_INTEL_MAX_AGE_MINUTES,
) -> dict[str, Any] | None:
    signal = _read_latest_intel_signal(intel_dir)
    if not signal or _num(signal.get("age_min"), 999_999.0) > max_age_min:
        return None
    return dict(signal, fresh=True)


def intel_regime(sig: dict[str, Any] | None) -> str | None:
    if not sig:
        return None
    score = _num(sig.get("score"), 50.0)
    direction = int(_num(sig.get("btc_dir"), 1.0))
    confidence = _num(sig.get("btc_conf"))
    agreement = _num(sig.get("btc_agreement"), confidence)
    red = str(sig.get("event_risk") or "") == "RED"
    event_score = _num(sig.get("event_risk_score"))

    if confidence >= 0.55 and agreement >= 0.55:
        if direction < 0:
            return "BEAR"
        if direction > 0 and score >= 50:
            return "BULL"
    if red and (event_score >= 80 or score < 55):
        return "BEAR"
    if score >= 55:
        return "BULL"
    if score <= 45:
        return "BEAR"
    return "NEUTRAL"


def _signal_meta(
    source: str,
    *,
    report_regime: str | None = None,
    intel: dict[str, Any] | None = None,
    fresh: bool = False,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "regime_source": source,
        "fresh": bool(fresh),
    }
    if report_regime:
        meta["report_regime"] = report_regime
    if intel:
        meta.update({
            "intel_age_min": _num(intel.get("age_min")),
            "btc_dir": int(_num(intel.get("btc_dir"), 1.0)),
            "btc_conf": _num(intel.get("btc_conf")),
            "btc_agreement": _num(intel.get("btc_agreement"), _num(intel.get("btc_conf"))),
            "btc_eligible": bool(intel.get("btc_eligible", True)),
            "btc_quality": str(intel.get("btc_quality") or ""),
            "event_risk": str(intel.get("event_risk") or ""),
            "event_risk_score": _num(intel.get("event_risk_score")),
            "intel_score": _num(intel.get("score"), 50.0),
        })
    return meta


def _resolve_regime(report: dict[str, Any], intel_dir: Path | None = None) -> tuple[str, dict[str, Any]]:
    market = report.get("market") or {}
    reported = str(market.get("regime") or report.get("regime") or "").upper()
    if reported and reported != "UNKNOWN":
        intel = _read_latest_intel_signal(intel_dir or DEFAULT_INTEL_DIR)
        return reported, _signal_meta(
            "report",
            report_regime=reported,
            intel=intel,
            fresh=True,
        )

    intel = _read_latest_intel_signal(intel_dir or DEFAULT_INTEL_DIR)
    if not intel:
        return "UNKNOWN", _signal_meta("unknown", fresh=False)
    fresh = _num(intel.get("age_min"), 999_999.0) <= DEFAULT_INTEL_MAX_AGE_MINUTES
    if not fresh:
        return "UNKNOWN", _signal_meta("intel", intel=intel, fresh=False)
    return intel_regime(intel) or "UNKNOWN", _signal_meta("intel", intel=intel, fresh=True)


def _regime(report: dict[str, Any], intel_dir: Path | None = None) -> str:
    return _resolve_regime(report, intel_dir)[0]


def _regime_methods(regime: str) -> tuple[list[str], list[str]]:
    methods: list[str] = []
    blocked: list[str] = []
    if regime == "BEAR":
        methods.extend([
            "PRE_LOSER_SHORT_RESEARCH",
            "ASK_BIASED_MARKET_MAKING",
            "DELTA_NEUTRAL_OR_SHORT_ONLY",
        ])
        blocked.append("LONG_SPOT_INVENTORY")
    elif regime == "BULL":
        methods.extend([
            "PRE_GAIN_LONG_RESEARCH",
            "BID_BIASED_MARKET_MAKING",
            "E2_MAKER_VOLUME_ONLY_AFTER_E1_COVERAGE",
        ])
    elif regime == "SIDEWAYS":
        methods.extend([
            "SIDEWAYS_DUAL_SIDED_MARKET_MAKING",
            "MEAN_REVERSION_GRID_WITH_HARD_STOP",
            "INVENTORY_REBALANCE_EVERY_CYCLE",
        ])
    elif regime == "CHAOS":
        methods.extend([
            "PAPER_PRE_GAIN_PRE_LOSER_ONLY",
            "NO_REAL_CATCHUP_DURING_CHAOS",
        ])
        blocked.extend(["E2_PERPS_VOLUME_SCALE", "LONG_SPOT_INVENTORY"])
    else:
        methods.extend([
            "REGIME_UNKNOWN_RESEARCH_ONLY",
            "PAPER_PRE_GAIN_PRE_LOSER_ONLY",
        ])
        blocked.append("E2_PERPS_VOLUME_SCALE")
    return methods, blocked


def _append_deadline_micro_lane(
    lanes: list[dict[str, Any]],
    *,
    regime: str,
    blockers: list[str],
    signal: dict[str, Any],
    open_perps: int,
    equity: float,
    now: datetime | None = None,
) -> bool:
    """Open a small event catch-up lane without pretending full E2 is healthy."""
    market_blockers = {
        "market_direction_signal_missing",
        "market_direction_signal_stale",
        "open_perp_positions_present",
        "combined_pnl_negative",
    }
    if days_to_event_end(now) > DEADLINE_FLEX_DAYS:
        return False
    if regime not in {"BEAR", "NEUTRAL", "SIDEWAYS"}:
        return False
    if open_perps > 0 or not bool(signal.get("fresh", False)):
        return False
    if market_blockers.intersection(blockers):
        return False
    if equity <= 0:
        return False
    lanes.append({
        "lane": "DEADLINE_MICRO_CATCHUP",
        "mode": "OPERATOR_APPROVED_DEADLINE_MICRO_LIVE",
        "max_notional_usd": min(40.0, max(0.0, equity * 0.04)),
        "max_daily_loss_usd": min(1.75, max(0.0, equity * 0.002)),
        "max_cycles_daily": 6,
        "requires": [
            "fresh_intel",
            "no_open_perps",
            "edge_after_fees_positive",
            "reduce_only_exit_plan",
            "stop_after_daily_loss_cap",
        ],
    })
    return True


def _safety_halt_short_pilot_allowed(
    *,
    regime: str,
    signal: dict[str, Any],
    blockers: list[str],
    open_perps: int,
) -> bool:
    """Allow only a tiny operator-approved short candidate during safety halt.

    This does not authorize broad E2 volume catch-up or spot inventory. It only
    prevents a BEAR/RED market from being reduced to passive waiting when the
    account is flat and the direction feed is fresh.
    """
    if open_perps != 0:
        return False
    if "position_truth_unverified" in blockers:
        return False
    if {"market_direction_signal_missing", "market_direction_signal_stale"}.intersection(blockers):
        return False
    if not bool(signal.get("fresh", False)):
        return False
    event_red = str(signal.get("event_risk") or "") == "RED" and _num(signal.get("event_risk_score")) >= 70.0
    btc_short = int(_num(signal.get("btc_dir"), 0.0)) < 0 and _num(signal.get("btc_conf")) >= 0.55
    return regime == "BEAR" and (event_red or btc_short)


def _roundtrip_volume_loss_budget(notional_usd: float, ratio: float = MIN_REAL_VOLUME_LOSS_RATIO) -> float:
    if notional_usd <= 0 or ratio <= 0:
        return 0.0
    return (notional_usd * 2.0) / ratio


def _ratio_requirement_label() -> str:
    return f"real_volume_loss_ratio_gte_{int(MIN_REAL_VOLUME_LOSS_RATIO)}"


def _ratio_safe_volume_plan(
    *,
    equity: float,
    remaining_volume_usd: float,
    max_cycles_daily: int = RATIO_RECOVERY_MAX_CYCLES_DAILY,
) -> dict[str, Any]:
    if equity <= 0 or remaining_volume_usd <= 0 or max_cycles_daily <= 0:
        return {}
    max_notional = min(
        RATIO_RECOVERY_MAX_NOTIONAL_USD,
        max(0.0, equity * RATIO_RECOVERY_EQUITY_FRACTION),
    )
    if max_notional <= 0:
        return {}
    capacity_daily_volume = max_notional * 2.0 * max_cycles_daily
    operator_budget_daily_volume = (
        RATIO_RECOVERY_OPERATOR_DAILY_LOSS_BUDGET_USD * MIN_REAL_VOLUME_LOSS_RATIO
    )
    budget_or_remaining = min(remaining_volume_usd, operator_budget_daily_volume)
    daily_volume = min(budget_or_remaining, capacity_daily_volume)
    cycles = max(1, min(max_cycles_daily, math.ceil(daily_volume / (max_notional * 2.0))))
    cycle_interval_seconds = math.ceil(86400 / max_cycles_daily)
    max_loss = daily_volume / MIN_REAL_VOLUME_LOSS_RATIO
    required_notional_for_operator_budget = operator_budget_daily_volume / (2.0 * max_cycles_daily)
    volume_gap = max(0.0, budget_or_remaining - daily_volume)
    return {
        "max_notional_usd": max_notional,
        "max_cycles_daily": cycles,
        "cycle_interval_seconds": cycle_interval_seconds,
        "target_daily_volume_usd": daily_volume,
        "capacity_limited_daily_volume_usd": capacity_daily_volume,
        "operator_budget_daily_loss_usd": RATIO_RECOVERY_OPERATOR_DAILY_LOSS_BUDGET_USD,
        "operator_budget_daily_volume_usd": operator_budget_daily_volume,
        "required_notional_for_operator_budget_usd": required_notional_for_operator_budget,
        "capacity_volume_gap_usd": volume_gap,
        "capacity_limited": volume_gap > 0.0,
        "min_volume_loss_ratio": MIN_REAL_VOLUME_LOSS_RATIO,
        "max_daily_loss_usd": max_loss,
        "max_loss_for_min_ratio_usd": max_loss,
    }


def _append_ratio_recovery_lane(
    lanes: list[dict[str, Any]],
    *,
    blockers: list[str],
    signal: dict[str, Any],
    open_perps: int,
    equity: float,
    remaining_volume_usd: float,
    halt_active: bool,
) -> bool:
    """Open a tiny maker-only lane to repair ratio without broad E2 scale."""
    forbidden = {
        "open_perp_positions_present",
        "position_truth_unverified",
        "safety_halt_active",
        "market_direction_signal_missing",
        "market_direction_signal_stale",
    }
    if halt_active or open_perps != 0 or equity <= 0:
        return False
    if forbidden.intersection(blockers):
        return False
    if not bool(signal.get("fresh", False)):
        return False

    plan = _ratio_safe_volume_plan(equity=equity, remaining_volume_usd=remaining_volume_usd)
    if not plan:
        return False

    lanes.append({
        "lane": "RATIO_RECOVERY_MAKER_ONLY",
        "mode": "OPERATOR_APPROVED_DAILY_RATIO_RECOVERY",
        **plan,
        "requires": [
            "fresh_intel",
            "no_open_perps",
            "maker_entry_only",
            "maker_reduce_only_exit_first",
            "reduce_only_taker_exit_fallback_only_for_residual",
            "bounded_daily_cycles_then_re-evaluate",
            _ratio_requirement_label(),
            "no_pve_scale_until_policy_clear",
        ],
    })
    return True


def evaluate_target_policy(
    report: dict[str, Any],
    *,
    target_volume_usd: float = TARGET_WEEKLY_VOLUME_USD,
    target_win_rate: float = TARGET_WIN_RATE,
    target_ratio: float = TARGET_VOLUME_FEE_RATIO,
    horizon_hours: int = DEFAULT_HORIZON_HOURS,
    intel_dir: Path | None = None,
) -> dict[str, Any]:
    """Return the safest SoDEX operating mode for the current weekly state."""
    official_ok, official_total, official_spot, official_perps = _official_volume(report)
    ledger = _ledger_facts(report)
    fees = float(ledger["fees_usd"] or 0.0)
    pnl = float(ledger["realized_pnl_usd"] or 0.0)
    win_rate = ledger["win_rate"]
    regime, signal = _resolve_regime(report, intel_dir)
    open_perps = _open_perp_count(report)
    equity = _equity(report)
    blockers: list[str] = []

    if not official_ok:
        blockers.append("official_dashboard_not_canonical")
    if win_rate is not None and float(win_rate) < target_win_rate:
        blockers.append("weekly_win_rate_below_target")
    gross_ratio = (official_total / fees) if fees > 0 and official_total > 0 else None
    if gross_ratio is not None and gross_ratio < target_ratio:
        blockers.append("volume_fee_ratio_below_target")
    e1_covers_all = bool(ledger["e1_covers_all_fees"]) or (fees > 0 and pnl >= fees)
    if fees > 0 and not e1_covers_all:
        blockers.append("e1_no_loss_coverage_short")
    if ledger["combined_no_loss"] is False or pnl < 0:
        blockers.append("combined_pnl_negative")
    if open_perps > 0:
        blockers.append("open_perp_positions_present")
    if _position_truth_unverified(report):
        blockers.append("position_truth_unverified")
    halt_active = _halt_active(report)
    if halt_active:
        blockers.append("safety_halt_active")
    if signal.get("regime_source") == "unknown":
        blockers.append("market_direction_signal_missing")
    elif not bool(signal.get("fresh", False)) and signal.get("regime_source") == "intel":
        blockers.append("market_direction_signal_stale")

    methods = [
        "WEEKLY_TARGET_CONTROLLER",
        "FEE_AWARE_ROUTE_SELECTION",
        "ADVERSE_SELECTION_FILTER",
        "INVENTORY_RISK_CAP",
    ]
    if halt_active:
        methods.append("HALT_FILE_GUARD")
    if "market_direction_signal_missing" in blockers or "market_direction_signal_stale" in blockers:
        methods.append("REFRESH_INTELLIGENCE_FEEDS")
    blocked_lanes: list[str] = []
    if not official_ok:
        methods.append("OFFICIAL_RECONCILIATION_FIRST")
    regime_methods, regime_blocked = _regime_methods(regime)
    methods.extend(regime_methods)
    blocked_lanes.extend(regime_blocked)
    opportunity_lanes: list[dict[str, Any]] = []

    remaining = max(0.0, target_volume_usd - official_total)
    horizon = max(1, int(horizon_hours))
    max_e2_hourly = 0.0
    max_daily_loss = 0.0

    hard_blockers = {
        "official_dashboard_not_canonical",
        "weekly_win_rate_below_target",
        "e1_no_loss_coverage_short",
        "combined_pnl_negative",
        "open_perp_positions_present",
        "position_truth_unverified",
        "safety_halt_active",
        "market_direction_signal_missing",
        "market_direction_signal_stale",
    }
    halt_short_pilot = halt_active and _safety_halt_short_pilot_allowed(
        regime=regime,
        signal=signal,
        blockers=blockers,
        open_perps=open_perps,
    )
    if halt_active:
        decision = "SAFETY_HALT_SHORT_PILOT_CANDIDATE" if halt_short_pilot else "SAFETY_HALT_ACTIVE"
        blocked_lanes.extend(["REAL_VOLUME_CATCHUP", "E2_PERPS_VOLUME_SCALE"])
        if not halt_short_pilot:
            blocked_lanes.append("MICRO_PRE_LOSER_SHORT_ONLY")
    elif regime == "CHAOS":
        decision = "PAUSE_REAL_VOLUME_CHAOS"
        blocked_lanes.append("REAL_VOLUME_CATCHUP")
    elif hard_blockers.intersection(blockers):
        decision = "BLOCK_E2_E1_RESEARCH_ONLY"
        blocked_lanes.append("E2_PERPS_VOLUME_SCALE")
    elif remaining > 0:
        decision = "CAPPED_CATCH_UP_ALLOWED"
        methods.append("E2_MAKER_VOLUME_CATCHUP")
        max_e2_hourly = remaining / horizon
        max_daily_loss = equity * 0.01 if equity > 0 else 0.0
    else:
        decision = "TARGET_MAINTENANCE_ALLOWED"
        methods.append("MAINTAIN_RATIO_NOT_VOLUME_CHASING")
        max_e2_hourly = 0.0
        max_daily_loss = equity * 0.005 if equity > 0 else 0.0

    if decision.startswith("BLOCK") or decision.startswith("PAUSE"):
        max_daily_loss = 0.0

    if _append_ratio_recovery_lane(
        opportunity_lanes,
        blockers=blockers,
        signal=signal,
        open_perps=open_perps,
        equity=equity,
        remaining_volume_usd=remaining,
        halt_active=halt_active,
    ):
        methods.append("RATIO_RECOVERY_MAKER_ONLY")

    if (
        regime == "BEAR"
        and open_perps == 0
        and not halt_active
        and bool(signal.get("fresh", False))
        and not {"market_direction_signal_missing", "market_direction_signal_stale"}.intersection(blockers)
    ):
        opportunity_lanes.append({
            "lane": "MICRO_PRE_LOSER_SHORT_ONLY",
            "mode": "PAPER_OR_OPERATOR_APPROVED_MICRO_LIVE",
            "max_notional_usd": min(25.0, max(0.0, equity * 0.03)),
            "max_daily_loss_usd": min(1.0, max(0.0, equity * 0.0015)),
            "requires": [
                "fresh_intel",
                "no_open_perps",
                "reduce_only_exit_plan",
                "no_scale_until_weekly_policy_allows",
            ],
        })

    if halt_short_pilot:
        methods.append("SAFETY_HALT_BEAR_SHORT_RELAXATION")
        max_notional = min(15.0, max(0.0, equity * 0.02))
        max_loss_for_ratio = _roundtrip_volume_loss_budget(max_notional)
        opportunity_lanes.append({
            "lane": "SAFETY_HALT_SHORT_PILOT",
            "mode": "EXPLICIT_OPERATOR_APPROVED_SHORT_ONLY",
            "max_notional_usd": max_notional,
            "projected_roundtrip_volume_usd": max_notional * 2.0,
            "min_volume_loss_ratio": MIN_REAL_VOLUME_LOSS_RATIO,
            "max_loss_for_min_ratio_usd": max_loss_for_ratio,
            "max_daily_loss_usd": min(0.75, max(0.0, equity * 0.001), max_loss_for_ratio),
            "requires": [
                "fresh_bear_or_red_event_signal",
                "no_open_perps",
                "operator_explicit_safety_halt_override",
                "reduce_only_exit_plan",
                "single_probe_then_re-evaluate",
                "no_spot_long_inventory",
                _ratio_requirement_label(),
            ],
        })

    deadline_lane = False
    if not halt_active:
        deadline_lane = _append_deadline_micro_lane(
            opportunity_lanes,
            regime=regime,
            blockers=blockers,
            signal=signal,
            open_perps=open_perps,
            equity=equity,
        )
    if decision == "BLOCK_E2_E1_RESEARCH_ONLY" and deadline_lane and not halt_active:
        decision = "DEADLINE_MICRO_CATCHUP_ONLY"
        methods.append("DEADLINE_FLEX_MICRO_CATCHUP")

    return {
        "decision": decision,
        "regime": regime,
        "signal": signal,
        "opportunity_lanes": opportunity_lanes,
        "blockers": sorted(set(blockers)),
        "methods": list(dict.fromkeys(methods)),
        "blocked_lanes": sorted(set(blocked_lanes)),
        "metrics": {
            "official_volume_usd": official_total,
            "official_spot_usd": official_spot,
            "official_perps_usd": official_perps,
            "remaining_volume_usd": remaining,
            "fees_usd": fees,
            "realized_pnl_usd": pnl,
            "win_rate": win_rate,
            "gross_volume_fee_ratio": gross_ratio,
            "open_perp_positions": open_perps,
            "position_truth_quality": ((report.get("account") or {}).get("position_truth") or {}).get("quality"),
            "halt_active": halt_active,
        },
        "limits": {
            "max_e2_hourly_volume_usd": max_e2_hourly,
            "max_daily_loss_usd": max_daily_loss,
            "max_inventory_usd": 0.0 if halt_active or regime == "CHAOS" else equity * 0.05,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only SoDEX weekly target policy")
    parser.add_argument(
        "--monitor-json",
        type=Path,
        default=Path("data/sodex_monitor_eval/latest.json"),
        help="Path to sodex_monitor_eval latest JSON",
    )
    parser.add_argument("--horizon-hours", type=int, default=DEFAULT_HORIZON_HOURS)
    args = parser.parse_args()
    report = json.loads(args.monitor_json.read_text())
    result = evaluate_target_policy(report, horizon_hours=args.horizon_hours)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
