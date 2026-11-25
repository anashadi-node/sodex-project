#!/usr/bin/env python3
"""Read-only radical go/no-go gate for SoDEX farming.

This script does not place, cancel, sign, or recommend a specific live order.
It converts the user's 84h build deadline and 2026-07-25 event deadline into
measurable gates for full-real readiness.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_LATEST = PROJECT_DIR / "data" / "sodex_monitor_eval" / "latest.json"
WIB = timezone(timedelta(hours=7))
TARGET_WEEKLY_VOLUME_USD = 1_300_000.0
TARGET_REAL_RATIO_MIN = 9_100.0
TARGET_REAL_RATIO_MAX = None
TARGET_WIN_RATE_MIN = 0.69
DEFAULT_EVENT_DEADLINE_WIB = datetime(2026, 7, 25, 0, 0, tzinfo=WIB)
BUILD_WINDOW_HOURS = 84
DEFAULT_SPOT_TOPUP_USD = 100.0
DEFAULT_PERP_TOPUP_USD = 150.0


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _ratio(volume: float, cost: float) -> float | None:
    if cost <= 0:
        return None
    return volume / cost


def _profit_needed(volume: float, fees: float, ratio: float) -> float:
    if ratio <= 0:
        return fees
    return max(0.0, fees - (volume / ratio))


def _open_perp_count(account: dict[str, Any]) -> int:
    truth = account.get("position_truth") or {}
    if isinstance(truth, dict) and "open_count" in truth:
        return int(_num(truth.get("open_count")))
    assets = account.get("assets") or {}
    return len(assets.get("perps_positions") or [])


def _position_truth_unverified(account: dict[str, Any]) -> bool:
    if "position_truth" not in account:
        return False
    truth = account.get("position_truth") or {}
    if not isinstance(truth, dict):
        return True
    return str(truth.get("quality") or "") != "OK"


def _time_model(now: datetime, event_deadline_wib: datetime) -> dict[str, float | str]:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_utc = now.astimezone(timezone.utc)
    event_utc = event_deadline_wib.astimezone(timezone.utc)
    seconds_to_event = max(0.0, (event_utc - now_utc).total_seconds())
    build_deadline = now_utc + timedelta(hours=BUILD_WINDOW_HOURS)
    return {
        "now_utc": now_utc.isoformat(),
        "event_deadline_wib": event_deadline_wib.isoformat(),
        "build_deadline_utc": build_deadline.isoformat(),
        "hours_to_build_deadline": BUILD_WINDOW_HOURS,
        "days_to_event_deadline": seconds_to_event / 86400.0,
        "weeks_to_event_deadline": seconds_to_event / (86400.0 * 7.0),
    }


def evaluate_radical_gate(
    report: dict[str, Any],
    *,
    now: datetime | None = None,
    event_deadline_wib: datetime = DEFAULT_EVENT_DEADLINE_WIB,
    spot_topup_usd: float = DEFAULT_SPOT_TOPUP_USD,
    perp_topup_usd: float = DEFAULT_PERP_TOPUP_USD,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    official_dashboard = report.get("official_dashboard") or {}
    official = official_dashboard.get("volume") or {}
    ledger = report.get("ledger") or {}
    ledger_volume = ledger.get("volume") or {}
    account = report.get("account") or {}
    account_value = account.get("account_value") or {}
    verdict = report.get("verdict") or {}

    official_is_canonical = (
        official_dashboard.get("quality") == "OK"
        and bool(official_dashboard.get("canonical"))
    )
    if official_is_canonical:
        official_spot = _num(official.get("spot_usd"))
        official_perps = _num(official.get("perps_usd"))
        official_raw = _num(official.get("total_usd"), official_spot + official_perps)
    else:
        official_spot = 0.0
        official_perps = 0.0
        official_raw = 0.0
    official_weighted = official_perps + (official_spot * 2)
    ledger_raw = _num(ledger_volume.get("raw_total_usd"))
    ledger_weighted = _num(ledger_volume.get("weighted_total_usd"))
    fees = _num((ledger.get("costs") or {}).get("fees_usd"))
    pnl = _num((ledger.get("pnl") or {}).get("realized_net_usd"))
    win_rate = _num((ledger.get("rts") or {}).get("win_rate"), -1.0)
    total_equity = _num(account_value.get("total_equity_usd"))
    projected_capital = total_equity + max(0.0, spot_topup_usd) + max(0.0, perp_topup_usd)
    open_positions = _open_perp_count(account)
    net_cost = max(0.0, fees - max(0.0, pnl))

    raw_net_ratio = _ratio(official_raw, net_cost)
    weighted_net_ratio = _ratio(official_weighted, net_cost)
    raw_profit_needed_9000 = _profit_needed(official_raw, fees, TARGET_REAL_RATIO_MIN)
    weighted_profit_needed_9000 = _profit_needed(official_weighted, fees, TARGET_REAL_RATIO_MIN)
    no_loss_profit_needed = max(0.0, fees)

    blockers: list[str] = []
    if not official_is_canonical:
        blockers.append("official_dashboard_not_canonical")
    if official_raw < TARGET_WEEKLY_VOLUME_USD:
        blockers.append("volume_below_weekly_target")
    if net_cost > 0 and (raw_net_ratio is None or raw_net_ratio < TARGET_REAL_RATIO_MIN):
        blockers.append("ratio_below_target")
    if pnl < raw_profit_needed_9000:
        blockers.append("e1_profit_coverage_short")
    if pnl < no_loss_profit_needed:
        blockers.append("e1_no_loss_coverage_short")
    if win_rate >= 0 and win_rate < TARGET_WIN_RATE_MIN:
        blockers.append("weekly_win_rate_below_target")
    if "official_dashboard_lower_than_internal_ledger" in (verdict.get("warnings") or []):
        blockers.append("official_ledger_reconciliation_gap")
    if open_positions > 0:
        blockers.append("open_perp_positions_present")
    if _position_truth_unverified(account):
        blockers.append("position_truth_unverified")

    hard_blockers = {
        "official_dashboard_not_canonical",
        "ratio_below_target",
        "e1_profit_coverage_short",
        "e1_no_loss_coverage_short",
        "weekly_win_rate_below_target",
        "official_ledger_reconciliation_gap",
        "open_perp_positions_present",
        "position_truth_unverified",
    }
    decision = "BLOCK_FULL_REAL" if any(b in hard_blockers for b in blockers) else "READY_FOR_FULL_REAL"
    if decision == "READY_FOR_FULL_REAL" and "volume_below_weekly_target" in blockers:
        decision = "RESEARCH_AND_CAPPED_CATCHUP"

    return {
        "decision": decision,
        "blockers": blockers,
        "time": _time_model(now, event_deadline_wib),
        "targets": {
            "weekly_volume_usd": TARGET_WEEKLY_VOLUME_USD,
            "real_ratio_min": TARGET_REAL_RATIO_MIN,
            "real_ratio_max": "NO_LOSS",
            "win_rate_min": TARGET_WIN_RATE_MIN,
            "official_dashboard_canonical_required": True,
        },
        "volumes": {
            "official_raw_usd": official_raw,
            "official_weighted_usd": official_weighted,
            "ledger_raw_usd": ledger_raw,
            "ledger_weighted_usd": ledger_weighted,
            "official_remaining_raw_usd": max(0.0, TARGET_WEEKLY_VOLUME_USD - official_raw),
            "official_remaining_weighted_usd": max(0.0, TARGET_WEEKLY_VOLUME_USD - official_weighted),
        },
        "ratios": {
            "official_raw_gross_ratio": _ratio(official_raw, fees),
            "official_weighted_gross_ratio": _ratio(official_weighted, fees),
            "official_raw_net_ratio": raw_net_ratio,
            "official_weighted_net_ratio": weighted_net_ratio,
            "ledger_raw_gross_ratio": _ratio(ledger_raw, fees),
            "ledger_weighted_gross_ratio": _ratio(ledger_weighted, fees),
        },
        "profit": {
            "fees_usd": fees,
            "realized_pnl_usd": pnl,
            "net_cost_usd": net_cost,
            "profit_needed_raw_9000": raw_profit_needed_9000,
            "profit_needed_weighted_9000": weighted_profit_needed_9000,
            "profit_needed_no_loss": no_loss_profit_needed,
            "extra_profit_needed_raw_9000": max(0.0, raw_profit_needed_9000 - pnl),
            "extra_profit_needed_weighted_9000": max(0.0, weighted_profit_needed_9000 - pnl),
            "extra_profit_needed_no_loss": max(0.0, no_loss_profit_needed - pnl),
        },
        "capital": {
            "current_equity_usd": total_equity,
            "spot_topup_usd": max(0.0, spot_topup_usd),
            "perp_topup_usd": max(0.0, perp_topup_usd),
            "projected_capital_usd": projected_capital,
            "max_loss_budget_25pct_usd": projected_capital * 0.25,
        },
        "radical_plan": [
            "E1-first: do not scale E2 until extra E1 profit coverage closes the ratio gap.",
            "Official-credit reconciliation: treat SoDEX dashboard as canonical; ledger is audit-only.",
            "Spot top-up lane: allocate extra spot capital to wide-spread maker capture with inventory caps.",
            "Perp top-up lane: keep E2 maker-only/hedged until ratio and open-position gates clear.",
            "Every 30-60 min: recompute official raw/weighted net ratio and pause if ratio deteriorates.",
        ],
    }


def _fmt_ratio(value: float | None) -> str:
    return "n/a" if value is None else f"1:{value:,.2f}"


def format_text(result: dict[str, Any]) -> str:
    ratios = result["ratios"]
    profit = result["profit"]
    capital = result["capital"]
    time = result["time"]
    lines = [
        f"decision: {result['decision']}",
        f"blockers: {', '.join(result['blockers']) if result['blockers'] else '-'}",
        f"event_deadline_wib: {time['event_deadline_wib']}",
        f"days_to_event: {time['days_to_event_deadline']:.2f}",
        f"official_raw_net_ratio: {_fmt_ratio(ratios['official_raw_net_ratio'])}",
        f"official_weighted_net_ratio: {_fmt_ratio(ratios['official_weighted_net_ratio'])}",
        f"extra_profit_needed_raw_9000: ${profit['extra_profit_needed_raw_9000']:,.2f}",
        f"extra_profit_needed_no_loss: ${profit['extra_profit_needed_no_loss']:,.2f}",
        f"projected_capital_after_topup: ${capital['projected_capital_usd']:,.2f}",
    ]
    lines.append("radical_plan:")
    lines.extend(f"- {item}" for item in result["radical_plan"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only SoDEX radical full-real gate")
    ap.add_argument("--latest", type=Path, default=DEFAULT_LATEST)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    report = json.loads(args.latest.read_text())
    result = evaluate_radical_gate(report)
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else format_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
