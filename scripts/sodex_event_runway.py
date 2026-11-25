#!/usr/bin/env python3
"""Deadline-aware SoDEX Farming runway planner.

Read-only. It quantifies the 25 July 2026 event gap and shows whether the
currently allowed lane can plausibly cover the daily volume pace.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

MONITOR_LATEST = PROJECT / "data" / "sodex_monitor_eval" / "latest.json"
WIB = timezone(timedelta(hours=7))
EVENT_END_WIB = datetime(2026, 7, 25, tzinfo=WIB)
TARGET_WEEKLY_VOLUME_USD = Decimal("1300000")
TAKER_FEE_RATE = Decimal("0.00036")


def dec(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def days_left(now: datetime | None = None) -> Decimal:
    current = now or datetime.now(WIB)
    if current.tzinfo is None:
        current = current.replace(tzinfo=WIB)
    seconds = max(0.0, (EVENT_END_WIB - current.astimezone(WIB)).total_seconds())
    return dec(seconds) / Decimal("86400")


def _target_policy(report: dict[str, Any]) -> dict[str, Any]:
    from scripts.sodex_target_policy import evaluate_target_policy

    return evaluate_target_policy(report)


def micro_lane(policy: dict[str, Any]) -> dict[str, Any] | None:
    for lane in policy.get("opportunity_lanes") or []:
        if lane.get("lane") == "DEADLINE_MICRO_CATCHUP":
            return lane
    for lane in policy.get("opportunity_lanes") or []:
        if lane.get("lane") == "MICRO_PRE_LOSER_SHORT_ONLY":
            return lane
    return None


def evaluate_runway(
    monitor: dict[str, Any],
    policy: dict[str, Any],
    *,
    now: datetime | None = None,
    target_volume_usd: Decimal = TARGET_WEEKLY_VOLUME_USD,
) -> dict[str, Any]:
    progress = ((monitor.get("verdict") or {}).get("progress") or {})
    current_volume = dec(progress.get("canonical_volume_usd"))
    remaining = max(Decimal("0"), target_volume_usd - current_volume)
    left = max(days_left(now), Decimal("0.0001"))
    needed_daily = remaining / left
    needed_hourly = needed_daily / Decimal("24")

    lane = micro_lane(policy)
    max_notional = dec((lane or {}).get("max_notional_usd"))
    max_daily_loss = dec((lane or {}).get("max_daily_loss_usd"))
    round_trip_volume = max_notional * Decimal("2")
    round_trip_cost = round_trip_volume * TAKER_FEE_RATE
    max_cycles_by_loss = (max_daily_loss / round_trip_cost) if round_trip_cost > 0 else Decimal("0")
    micro_daily_capacity = max_cycles_by_loss * round_trip_volume
    required_micro_cycles_daily = (needed_daily / round_trip_volume) if round_trip_volume > 0 else Decimal("0")

    if str(policy.get("decision") or "").startswith("CAPPED") or policy.get("decision") == "TARGET_MAINTENANCE_ALLOWED":
        phase = "PHASE_2_CATCHUP_READY"
    elif policy.get("decision") == "DEADLINE_MICRO_CATCHUP_ONLY":
        phase = "PHASE_1_DEADLINE_MICRO_CATCHUP"
    elif lane:
        phase = "PHASE_1_MICRO_ONLY"
    else:
        phase = "PHASE_0_RESEARCH_ONLY"

    if phase == "PHASE_1_MICRO_ONLY" and micro_daily_capacity < needed_daily:
        verdict = "MICRO_ONLY_INSUFFICIENT_FOR_EVENT_TARGET"
    elif phase == "PHASE_2_CATCHUP_READY":
        verdict = "CATCHUP_CAPACITY_DEPENDS_ON_POLICY_LIMIT"
    else:
        verdict = "NO_LIVE_CAPACITY"

    return {
        "event_end_wib": EVENT_END_WIB.date().isoformat(),
        "days_left": float(left),
        "phase": phase,
        "verdict": verdict,
        "target_volume_usd": float(target_volume_usd),
        "current_volume_usd": float(current_volume),
        "remaining_volume_usd": float(remaining),
        "needed_daily_volume_usd": float(needed_daily),
        "needed_hourly_volume_usd": float(needed_hourly),
        "policy_decision": policy.get("decision"),
        "regime": policy.get("regime"),
        "blockers": policy.get("blockers") or [],
        "micro": {
            "lane_active": bool(lane),
            "max_notional_usd": float(max_notional),
            "max_daily_loss_usd": float(max_daily_loss),
            "round_trip_volume_usd": float(round_trip_volume),
            "estimated_round_trip_taker_cost_usd": float(round_trip_cost),
            "estimated_max_cycles_by_loss_daily": float(max_cycles_by_loss),
            "estimated_daily_volume_capacity_usd": float(micro_daily_capacity),
            "required_cycles_daily_for_target": float(required_micro_cycles_daily),
        },
        "promotion_rules": [
            "official_dashboard_canonical_or_reconciled",
            "weekly_win_rate_above_target",
            "e1_covers_all_fees",
            "no_open_perps_before_each_cycle",
            "fresh_market_direction_signal",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only SoDEX event runway planner")
    parser.add_argument("--monitor-json", type=Path, default=MONITOR_LATEST)
    args = parser.parse_args(argv)
    monitor = json.loads(args.monitor_json.read_text())
    policy = _target_policy(monitor)
    print(json.dumps(evaluate_runway(monitor, policy), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
