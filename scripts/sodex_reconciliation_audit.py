#!/usr/bin/env python3
"""Read-only SoDEX official-vs-ledger reconciliation audit.

This script does not place, cancel, sign, or suggest a concrete order. It
quantifies whether local ledger volume is actually becoming official SoDEX
credited volume, then derives the E1 profit gap needed for the user's real
ratio target.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_LATEST = PROJECT_DIR / "data" / "sodex_monitor_eval" / "latest.json"

TARGET_WEEKLY_VOLUME_USD = 550_000.0  # REVISI 2026-07-22 (was 1.3M)
TARGET_REAL_RATIO_MIN = 5_000.0
TARGET_REAL_RATIO_MAX = None
MIN_TOTAL_CREDIT_RATE = 0.75
MIN_PERPS_CREDIT_RATE = 0.75
CRITICAL_PERPS_CREDIT_RATE = 0.25


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _rate(official: float, ledger: float) -> float | None:
    if ledger <= 0:
        return None
    return official / ledger


def _ratio(volume: float, cost: float) -> float | None:
    if cost <= 0:
        return None
    return volume / cost


def _profit_needed(volume: float, fees: float, target_ratio: float) -> float:
    if target_ratio <= 0:
        return fees
    return max(0.0, fees - (volume / target_ratio))


def _volume_needed(net_cost: float, target_ratio: float) -> float:
    return max(0.0, net_cost * target_ratio)


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


def analyze_report(report: dict[str, Any]) -> dict[str, Any]:
    official_dashboard = report.get("official_dashboard") or {}
    official = official_dashboard.get("volume") or {}
    ledger = report.get("ledger") or {}
    ledger_volume = ledger.get("volume") or {}
    costs = ledger.get("costs") or {}
    pnl_data = ledger.get("pnl") or {}
    account = report.get("account") or {}

    official_is_canonical = (
        official_dashboard.get("quality") == "OK"
        and bool(official_dashboard.get("canonical"))
    )
    if official_is_canonical:
        official_spot = _num(official.get("spot_usd"))
        official_perps = _num(official.get("perps_usd"))
        official_total = _num(official.get("total_usd"), official_spot + official_perps)
    else:
        official_spot = 0.0
        official_perps = 0.0
        official_total = 0.0

    ledger_spot = _num(ledger_volume.get("spot_usd"))
    ledger_perps = _num(ledger_volume.get("perps_usd"))
    ledger_total = _num(ledger_volume.get("raw_total_usd"), ledger_spot + ledger_perps)

    fees = _num(costs.get("fees_usd"))
    pnl = _num(pnl_data.get("realized_net_usd"))
    net_cost = max(0.0, fees - max(0.0, pnl))
    open_positions = _open_perp_count(account)

    spot_credit_rate = _rate(official_spot, ledger_spot)
    perps_credit_rate = _rate(official_perps, ledger_perps)
    total_credit_rate = _rate(official_total, ledger_total)
    raw_net_ratio = _ratio(official_total, net_cost)

    profit_needed_target_ratio = _profit_needed(official_total, fees, TARGET_REAL_RATIO_MIN)
    volume_needed_target_ratio = _volume_needed(net_cost, TARGET_REAL_RATIO_MIN)
    no_loss_profit_needed = max(0.0, fees)

    blockers: list[str] = []
    if not official_is_canonical:
        blockers.append("official_dashboard_not_canonical")
    if official_total < TARGET_WEEKLY_VOLUME_USD:
        blockers.append("official_weekly_volume_short")
    if total_credit_rate is not None and total_credit_rate < MIN_TOTAL_CREDIT_RATE:
        blockers.append("official_total_credit_rate_low")
    if perps_credit_rate is not None and perps_credit_rate < CRITICAL_PERPS_CREDIT_RATE:
        blockers.append("perps_credit_rate_critical")
    elif perps_credit_rate is not None and perps_credit_rate < MIN_PERPS_CREDIT_RATE:
        blockers.append("perps_credit_rate_low")
    if net_cost > 0 and (raw_net_ratio is None or raw_net_ratio < TARGET_REAL_RATIO_MIN):
        blockers.append("official_raw_net_ratio_low")
    if pnl < profit_needed_target_ratio:
        blockers.append("e1_profit_coverage_short")
    if pnl < no_loss_profit_needed:
        blockers.append("e1_no_loss_coverage_short")
    if open_positions > 0:
        blockers.append("open_perp_positions_present")
    if _position_truth_unverified(account):
        blockers.append("position_truth_unverified")

    hard_recon = {
        "official_dashboard_not_canonical",
        "official_total_credit_rate_low",
        "perps_credit_rate_critical",
        "perps_credit_rate_low",
    }
    hard_profit = {
        "official_raw_net_ratio_low",
        "e1_profit_coverage_short",
        "e1_no_loss_coverage_short",
        "open_perp_positions_present",
        "position_truth_unverified",
    }
    if any(b in hard_recon for b in blockers) or any(b in hard_profit for b in blockers):
        decision = "RECON_FIRST_E1_PROFIT_FIRST"
    elif "official_weekly_volume_short" in blockers:
        decision = "E2_CAPPED_CATCHUP_ALLOWED"
    else:
        decision = "E2_CAPPED_SCALE_ALLOWED"

    return {
        "decision": decision,
        "blockers": blockers,
        "targets": {
            "weekly_volume_usd": TARGET_WEEKLY_VOLUME_USD,
            "real_ratio_min": TARGET_REAL_RATIO_MIN,
            "real_ratio_max": "NO_LOSS",
            "min_total_credit_rate": MIN_TOTAL_CREDIT_RATE,
            "min_perps_credit_rate": MIN_PERPS_CREDIT_RATE,
        },
        "official": {
            "spot_usd": official_spot,
            "perps_usd": official_perps,
            "total_usd": official_total,
        },
        "ledger": {
            "spot_usd": ledger_spot,
            "perps_usd": ledger_perps,
            "total_usd": ledger_total,
        },
        "deltas": {
            "spot_uncredited_usd": max(0.0, ledger_spot - official_spot),
            "perps_uncredited_usd": max(0.0, ledger_perps - official_perps),
            "total_uncredited_usd": max(0.0, ledger_total - official_total),
        },
        "credit_rates": {
            "spot": spot_credit_rate,
            "perps": perps_credit_rate,
            "total": total_credit_rate,
        },
        "ratios": {
            "official_raw_net_ratio": raw_net_ratio,
            "official_raw_gross_ratio": _ratio(official_total, fees),
        },
        "requirements": {
            "fees_usd": fees,
            "realized_pnl_usd": pnl,
            "net_cost_usd": net_cost,
            "profit_needed_for_raw_target_ratio": profit_needed_target_ratio,
            "profit_needed_for_no_loss": no_loss_profit_needed,
            "extra_profit_for_raw_target_ratio": max(0.0, profit_needed_target_ratio - pnl),
            "extra_profit_for_no_loss": max(0.0, no_loss_profit_needed - pnl),
            "official_volume_needed_for_raw_target_ratio": volume_needed_target_ratio,
            "official_extra_volume_for_raw_target_ratio": max(0.0, volume_needed_target_ratio - official_total),
            "official_remaining_to_weekly_target": max(0.0, TARGET_WEEKLY_VOLUME_USD - official_total),
        },
        "operator_rules": [
            "Treat official SoDEX credited volume as canonical for event progress.",
            "Do not scale E2 while perps credit rate is low or critical.",
            "Use E1 profit coverage to close the real-ratio gap before volume amplification.",
            "Refresh official dashboard evidence before trusting ledger-only growth.",
        ],
    }


def _fmt_money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.2f}"


def _fmt_rate(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


def _fmt_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"1:{value:,.2f}"


def format_text(result: dict[str, Any]) -> str:
    official = result["official"]
    ledger = result["ledger"]
    deltas = result["deltas"]
    rates = result["credit_rates"]
    ratios = result["ratios"]
    req = result["requirements"]
    lines = [
        f"decision: {result['decision']}",
        f"blockers: {', '.join(result['blockers']) if result['blockers'] else '-'}",
        "official_vs_ledger:",
        f"- official total: {_fmt_money(official['total_usd'])}",
        f"- ledger total: {_fmt_money(ledger['total_usd'])}",
        f"- uncredited total: {_fmt_money(deltas['total_uncredited_usd'])}",
        f"- credit rates spot/perps/total: {_fmt_rate(rates['spot'])} / {_fmt_rate(rates['perps'])} / {_fmt_rate(rates['total'])}",
        "ratio_and_profit:",
        f"- official raw net ratio: {_fmt_ratio(ratios['official_raw_net_ratio'])}",
        f"- net cost: {_fmt_money(req['net_cost_usd'])}",
        f"- extra E1 profit for 1:{TARGET_REAL_RATIO_MIN:,.0f}: {_fmt_money(req['extra_profit_for_raw_target_ratio'])}",
        f"- extra E1 profit for NO-LOSS: {_fmt_money(req['extra_profit_for_no_loss'])}",
        f"- official remaining to weekly target: {_fmt_money(req['official_remaining_to_weekly_target'])}",
        "operator_rules:",
    ]
    lines.extend(f"- {item}" for item in result["operator_rules"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only SoDEX official-vs-ledger reconciliation audit")
    parser.add_argument("--latest", type=Path, default=DEFAULT_LATEST)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = json.loads(args.latest.read_text())
    result = analyze_report(report)
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else format_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
