#!/usr/bin/env python3
"""Read-only go-live accelerator for SoDEX short farming probes.

This is a cockpit, not an executor. It combines target policy, E2Dir candidate
ranking, and the active real-volume/loss rule, then prints the exact live command
only when the current state is ready for an explicit operator-approved probe.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

MONITOR_LATEST = PROJECT / "data" / "sodex_monitor_eval" / "latest.json"
MAX_MAKER_RECOVERY_SPREAD_BPS = Decimal("12")


def dec(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _read_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text())
    return payload if isinstance(payload, dict) else {}


def _refresh_monitor() -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, "scripts/sodex_monitor_eval.py", "--json", "--no-persist"],
        cwd=PROJECT,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        return {"refresh_error": proc.stderr[-500:]}
    payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
    return payload if isinstance(payload, dict) else {}


def _lane(policy: dict[str, Any]) -> dict[str, Any] | None:
    for lane in policy.get("opportunity_lanes") or []:
        if lane.get("lane") == "SAFETY_HALT_SHORT_PILOT":
            return lane
    for lane in policy.get("opportunity_lanes") or []:
        if lane.get("lane") in {"RATIO_RECOVERY_MAKER_ONLY", "DEADLINE_MICRO_CATCHUP", "MICRO_PRE_LOSER_SHORT_ONLY"}:
            return lane
    return None


def _rows_from_candidates(candidates: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        item = asdict(candidate)
        rows.append({
            key: float(value) if isinstance(value, Decimal) else value
            for key, value in item.items()
        })
    return rows


def _fmt_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _best_maker_recovery_candidate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [
        row for row in rows
        if isinstance(row, dict)
        and row.get("scalp_lane") == "MAKER_ONLY_CANDIDATE"
        and dec(row.get("mid")) > 0
        and dec(row.get("spread_bps")) <= MAX_MAKER_RECOVERY_SPREAD_BPS
    ]
    if not candidates:
        return {}
    best = max(
        candidates,
        key=lambda row: (
            dec(row.get("maker_gross_edge_bps")),
            dec(row.get("quote_volume_usd")),
        ),
    )
    return {
        "symbol": str(best.get("symbol") or ""),
        "side": "sell",
        "score": float(dec(best.get("maker_gross_edge_bps"))),
        "expected_edge_bps": float(dec(best.get("maker_gross_edge_bps"))),
        "change_pct": float(dec(best.get("change_pct"))),
        "funding_rate": float(dec(best.get("funding_bps")) / Decimal("10000")),
        "spread_pct": float(dec(best.get("spread_bps")) / Decimal("10000")),
        "quote_volume": float(dec(best.get("quote_volume_usd"))),
        "mid": float(dec(best.get("mid"))),
    }


def scan_short_candidates(limit: int) -> list[dict[str, Any]]:
    from scripts import sodex_e2dir_amplifier as amp

    return _rows_from_candidates(amp.select_short_candidates(amp.tickers(), limit=max(1, int(limit))))


def scan_microstructure_rows() -> list[dict[str, Any]]:
    from scripts import sodex_scalp_microstructure as scalp

    markets = scalp.run_json(["bin/sodex", "markets", "perps", "--format", "json"])
    tickers = scalp.run_json(["bin/sodex", "tickers", "perps", "--format", "json"])
    return [asdict(row) for row in scalp.build_rows(
        markets if isinstance(markets, list) else [],
        tickers if isinstance(tickers, list) else [],
    )]


def build_plan(
    report: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    microstructure_rows: list[dict[str, Any]] | None = None,
    requested_notional: Decimal | None = None,
    hold_seconds: float = 12.0,
    confirm_seconds: float = 3.0,
    max_pre_entry_rebound_pct: Decimal = Decimal("0.002"),
) -> dict[str, Any]:
    from scripts import sodex_e2dir_amplifier as amp
    from scripts import sodex_micro_pilot as pilot
    from scripts.sodex_target_policy import evaluate_target_policy

    policy = evaluate_target_policy(report)
    decision = amp.promotion_decision(policy, candidates)
    lane = _lane(policy)
    ratio_lane = bool(lane and lane.get("lane") == "RATIO_RECOVERY_MAKER_ONLY")
    best = candidates[0] if candidates else {}
    if ratio_lane and microstructure_rows:
        maker_best = _best_maker_recovery_candidate(microstructure_rows)
        if maker_best:
            current_micro = {
                str(row.get("symbol") or ""): row
                for row in microstructure_rows
                if isinstance(row, dict)
            }.get(str(best.get("symbol") or ""))
            if not current_micro or current_micro.get("scalp_lane") != "MAKER_ONLY_CANDIDATE":
                best = maker_best
    lane_cap = dec((lane or {}).get("max_notional_usd"))
    requested = requested_notional if requested_notional is not None else lane_cap
    notional = min(requested, lane_cap) if lane_cap > 0 else Decimal("0")
    daily_loss_used = pilot.micro_daily_loss_used_usd()
    daily_volume = pilot.micro_daily_volume_usd()
    projected_volume = pilot.projected_roundtrip_volume_usd(notional)
    lane_target_daily_volume = dec((lane or {}).get("target_daily_volume_usd"))
    lane_remaining_daily_volume = max(Decimal("0"), lane_target_daily_volume - daily_volume)
    safe_cycles_remaining_today = (
        int(lane_remaining_daily_volume // projected_volume)
        if projected_volume > 0 and lane_remaining_daily_volume > 0
        else 0
    )
    suggested_burst_cycles = max(1, min(12, safe_cycles_remaining_today)) if safe_cycles_remaining_today > 0 else 1
    ratio_budget = pilot.max_loss_for_ratio(notional)
    lane_ratio_budget = dec((lane or {}).get("max_loss_for_min_ratio_usd"))
    if lane_ratio_budget > 0:
        ratio_budget = min(ratio_budget, lane_ratio_budget)
    mid = dec(best.get("mid"))
    qty = pilot.qty_for_notional(notional, mid, str(best.get("symbol") or "")) if notional > 0 and mid > 0 else ""
    open_perps = int(((policy.get("metrics") or {}).get("open_perp_positions")) or 0)
    micro_by_symbol = {
        str(row.get("symbol") or ""): row
        for row in (microstructure_rows or [])
        if isinstance(row, dict)
    }
    micro = micro_by_symbol.get(str(best.get("symbol") or "")) if best else None
    micro_is_maker_candidate = bool(micro and micro.get("scalp_lane") == "MAKER_ONLY_CANDIDATE")
    ratio_recovery_mode = bool(
        lane
        and lane.get("lane") == "RATIO_RECOVERY_MAKER_ONLY"
        and micro_is_maker_candidate
    )
    cumulative_remaining = pilot.cumulative_ratio_loss_remaining_usd(
        notional,
        daily_loss_used_usd=daily_loss_used,
        daily_volume_usd=daily_volume,
    )
    ta_gate: dict[str, Any] = {}
    if best and notional > 0:
        ta_gate = pilot.ta_probability_gate(
            str(best.get("symbol") or ""),
            side="sell",
            notional=notional,
        )

    blockers: list[str] = []
    if not lane:
        blockers.append("short_pilot_lane_missing")
    if not decision.get("live_allowed"):
        blockers.append("e2dir_promotion_not_live_candidate")
    if not best:
        blockers.append("short_candidate_missing")
    if open_perps != 0:
        blockers.append("open_perps_present")
    if notional <= 0:
        blockers.append("notional_zero")
    if daily_loss_used >= ratio_budget and ratio_budget > 0 and not micro_is_maker_candidate:
        blockers.append("farming_ratio_loss_budget_reached")
    if qty == "":
        blockers.append("qty_unavailable")
    if not micro:
        blockers.append("microstructure_missing")
    elif micro.get("scalp_lane") != "MAKER_ONLY_CANDIDATE":
        blockers.append(f"microstructure_not_maker_candidate:{micro.get('scalp_lane')}")
    elif bool(micro.get("taker_ratio_pass")):
        blockers.append("unexpected_taker_ratio_pass_recheck_fees")
    if best and not ta_gate.get("passes"):
        blockers.append("ta_probability_gate_failed")

    ready = not blockers
    live_cmd = None
    if ready:
        live_cmd = (
            "python3 scripts/sodex_micro_pilot.py --live "
            "--operator-override-safety-halt "
            "--operator-override-barbell-cooldown "
            f"--notional {_fmt_decimal(notional)} "
            f"--symbol {best.get('symbol')} "
            f"--cycles {suggested_burst_cycles} "
            f"--hold-seconds {hold_seconds:g} "
            f"--confirm-seconds {confirm_seconds:g} "
            f"--max-pre-entry-rebound-pct {_fmt_decimal(max_pre_entry_rebound_pct)} "
            f"--min-ta-probability {_fmt_decimal(pilot.MIN_TA_PROBABILITY)} "
            "--entry-mode maker "
            "--exit-mode maker"
        )

    return {
        "status": "READY_FOR_EXPLICIT_OPERATOR_LIVE_MAKER_SHORT" if ready else "BLOCKED",
        "mode": "READ_ONLY_GO_LIVE_ACCELERATOR",
        "execution_route": {
            "entry": "maker_post_only_gtx",
            "exit": "maker_post_only_gtx_with_reduce_only_taker_fallback",
            "taker_scalp": "blocked_by_fee_spread_ratio",
        },
        "policy": {
            "decision": policy.get("decision"),
            "regime": policy.get("regime"),
            "blockers": policy.get("blockers") or [],
            "lane": lane,
        },
        "e2dir": decision,
        "best_candidate": best,
        "microstructure": micro,
        "ta_probability_gate": ta_gate,
        "probe": {
            "notional_usd": float(notional),
            "qty": qty,
            "side": "sell" if best else None,
            "projected_roundtrip_volume_usd": float(projected_volume),
            "lane_target_daily_volume_usd": float(lane_target_daily_volume),
            "lane_remaining_daily_volume_usd": float(lane_remaining_daily_volume),
            "safe_cycles_remaining_today": safe_cycles_remaining_today,
            "suggested_burst_cycles": suggested_burst_cycles,
            "suggested_cycle_interval_seconds": int(dec((lane or {}).get("cycle_interval_seconds"))),
            "min_real_volume_loss_ratio": float(pilot.MIN_REAL_VOLUME_LOSS_RATIO),
            "max_loss_for_min_ratio_usd": float(ratio_budget),
            "daily_loss_used_usd": float(daily_loss_used),
            "daily_volume_usd": float(daily_volume),
            "cumulative_ratio_loss_remaining_usd": float(cumulative_remaining),
            "ratio_recovery_mode": ratio_recovery_mode,
            "ratio_recovery_requires_zero_incremental_loss": ratio_recovery_mode,
            "hold_seconds": hold_seconds,
            "confirm_seconds": confirm_seconds,
            "max_pre_entry_rebound_pct": float(max_pre_entry_rebound_pct),
        },
        "blockers": blockers,
        "live_command": live_cmd,
        "operator_ack_required": bool(ready),
        "notes": [
            "read-only: this script never places orders",
            f"taker/IOC scalping is not recommended for 1:{int(pilot.MIN_REAL_VOLUME_LOSS_RATIO)} because taker fees alone exceed the loss budget",
            "live command uses a bounded maker-only micro-burst; micro-pilot re-checks policy and position state each cycle",
            f"farming target is real volume/loss >= 1:{int(pilot.MIN_REAL_VOLUME_LOSS_RATIO)}, not naked PnL chasing",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only SoDEX live short accelerator")
    parser.add_argument("--monitor-json", type=Path, default=MONITOR_LATEST)
    parser.add_argument("--refresh-monitor", action="store_true")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--notional", type=Decimal)
    parser.add_argument("--hold-seconds", type=float, default=12.0)
    parser.add_argument("--confirm-seconds", type=float, default=3.0)
    parser.add_argument("--max-pre-entry-rebound-pct", type=Decimal, default=Decimal("0.002"))
    args = parser.parse_args(argv)

    report = _refresh_monitor() if args.refresh_monitor else _read_report(args.monitor_json)
    candidates = scan_short_candidates(args.limit)
    microstructure_rows = scan_microstructure_rows()
    plan = build_plan(
        report,
        candidates,
        microstructure_rows=microstructure_rows,
        requested_notional=args.notional,
        hold_seconds=args.hold_seconds,
        confirm_seconds=args.confirm_seconds,
        max_pre_entry_rebound_pct=args.max_pre_entry_rebound_pct,
    )
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0 if plan["status"].startswith("READY") else 2


if __name__ == "__main__":
    raise SystemExit(main())
