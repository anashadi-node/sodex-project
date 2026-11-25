#!/usr/bin/env python3
"""SoDEX Event Barbell gate.

Read-only promotion gate for the method combination:
E1 profit subsidy + micro Pre-Loser probe + E2Dir/Pregain amplifier candidate.
It never edits env files and never places orders.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

MONITOR_LATEST = PROJECT / "data" / "sodex_monitor_eval" / "latest.json"
MICRO_LOG = PROJECT / "data" / "sodex_micro_pilot.jsonl"
MIN_PROMOTION_CYCLES = 30
MIN_PROMOTION_WR = Decimal("0.69")
MIN_PROMOTION_NET_USD = Decimal("0.01")
LOSS_CAP_BUFFER = Decimal("0.90")
MIN_EARLY_EDGE_CYCLES = 4
EARLY_EDGE_WR_FLOOR = Decimal("0.50")


def dec(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text().splitlines():
            if line.strip():
                payload = json.loads(line)
                if isinstance(payload, dict):
                    rows.append(payload)
    except Exception:
        return rows
    return rows


def micro_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    live = [
        row for row in rows
        if row.get("mode") == "live" and row.get("reason") == "ok" and bool(row.get("closed", True))
    ]
    wins = 0
    net = Decimal("0")
    volume = Decimal("0")
    loss_used = Decimal("0")
    today = datetime.now(timezone.utc).date()
    for row in live:
        delta = dec(row.get("perps_account_delta_usd", row.get("account_delta_usd")))
        net += delta
        if delta > 0:
            wins += 1
        volume += dec(row.get("requested_notional_usd")) * Decimal("2")
        try:
            ts = datetime.fromisoformat(str(row.get("ts_utc"))).astimezone(timezone.utc)
        except Exception:
            ts = None
        if ts and ts.date() == today and delta < 0:
            loss_used += abs(delta)
    n = len(live)
    return {
        "live_cycles": n,
        "wins": wins,
        "losses": max(0, n - wins),
        "win_rate": float(Decimal(wins) / Decimal(n)) if n else 0.0,
        "net_perps_delta_usd": float(net),
        "round_trip_volume_usd": float(volume),
        "daily_loss_used_usd": float(loss_used),
    }


def decide_barbell(
    *,
    policy: dict[str, Any],
    runway: dict[str, Any],
    micro: dict[str, Any],
) -> dict[str, Any]:
    blockers = list(policy.get("blockers") or [])
    micro_lane = runway.get("micro") or {}
    max_daily_loss = dec(micro_lane.get("max_daily_loss_usd"), Decimal("1"))
    daily_loss = dec(micro.get("daily_loss_used_usd"))
    early_negative = (
        int(micro.get("live_cycles") or 0) >= MIN_EARLY_EDGE_CYCLES
        and dec(micro.get("net_perps_delta_usd")) < 0
        and dec(micro.get("win_rate")) < EARLY_EDGE_WR_FLOOR
    )
    if max_daily_loss > 0 and daily_loss >= max_daily_loss * LOSS_CAP_BUFFER:
        blockers.append("micro_daily_loss_near_cap")
        phase = "STOP_LIVE_RESEARCH_ONLY"
    elif early_negative:
        blockers.append("micro_edge_negative")
        phase = "MICRO_EDGE_NEGATIVE_COOLDOWN"
    elif blockers:
        phase = "MICRO_PROBE_ONLY" if micro_lane.get("lane_active") else "RESEARCH_ONLY"
    else:
        enough_micro = (
            int(micro.get("live_cycles") or 0) >= MIN_PROMOTION_CYCLES
            and dec(micro.get("win_rate")) >= MIN_PROMOTION_WR
            and dec(micro.get("net_perps_delta_usd")) >= MIN_PROMOTION_NET_USD
        )
        phase = "E2DIR_MICRO_AMPLIFIER_CANDIDATE" if enough_micro else "MICRO_PROBE_UNTIL_EDGE_PROVEN"

    live_now: list[str] = []
    paper_now = ["E2DIR_FUNDING_OBI", "PREGain_TOP_LOSER_BRIDGE", "MODE10_DSSC", "MODE7_INTEL_MAKER"]
    live_candidate: list[str] = []
    if phase == "MICRO_PROBE_ONLY":
        live_now.append("MICRO_PRE_LOSER_SHORT")
    if phase == "E2DIR_MICRO_AMPLIFIER_CANDIDATE":
        live_candidate.extend(["E2DIR_FUNDING_OBI", "PREGain_TOP_LOSER_BRIDGE"])

    return {
        "method": "EVENT_BARBELL_V1",
        "phase": phase,
        "policy_decision": policy.get("decision"),
        "regime": policy.get("regime"),
        "blockers": sorted(set(blockers)),
        "live_now": live_now,
        "paper_now": paper_now,
        "live_candidate": live_candidate,
        "requires_operator_approval": bool(live_candidate),
        "micro": micro,
        "runway_verdict": runway.get("verdict"),
        "next_actions": _next_actions(phase),
    }


def _next_actions(phase: str) -> list[str]:
    if phase == "STOP_LIVE_RESEARCH_ONLY":
        return ["stop_micro_live_until_next_day_or_manual_review", "continue_paper_e2dir_mode10"]
    if phase == "MICRO_EDGE_NEGATIVE_COOLDOWN":
        return ["pause_micro_live", "switch_to_paper_e2dir_pregain", "refresh_candidate_scoring_before_next_live"]
    if phase == "E2DIR_MICRO_AMPLIFIER_CANDIDATE":
        return ["operator_review", "run_e2dir_micro_dry_run", "promote_only_with_no_open_perps_and_fresh_signal"]
    if phase == "MICRO_PROBE_ONLY":
        return ["continue_capped_micro_probe", "fix_official_reconciliation", "improve_e1_profit_coverage"]
    return ["collect_more_micro_evidence", "keep_e2dir_and_mode10_paper"]


def evaluate_barbell(monitor: dict[str, Any], micro_rows: list[dict[str, Any]]) -> dict[str, Any]:
    from scripts.sodex_target_policy import evaluate_target_policy
    from scripts.sodex_event_runway import evaluate_runway

    policy = evaluate_target_policy(monitor)
    runway = evaluate_runway(monitor, policy)
    micro = micro_stats(micro_rows)
    return decide_barbell(policy=policy, runway=runway, micro=micro)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only SoDEX Event Barbell gate")
    parser.add_argument("--monitor-json", type=Path, default=MONITOR_LATEST)
    parser.add_argument("--micro-log", type=Path, default=MICRO_LOG)
    args = parser.parse_args(argv)
    monitor = json.loads(args.monitor_json.read_text())
    result = evaluate_barbell(monitor, read_jsonl(args.micro_log))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
