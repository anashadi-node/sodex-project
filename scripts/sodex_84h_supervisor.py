#!/usr/bin/env python3
"""Read-only 84h autonomous supervisor for SoDEX farming.

This loop coordinates monitor, reconciliation, and radical gate outputs. It
never places orders, transfers funds, changes leverage, edits credentials, or
authorizes live trading by itself.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from scripts import sodex_radical_gate as gate  # noqa: E402
from scripts import sodex_reconciliation_audit as reconcile  # noqa: E402


DEFAULT_LATEST = PROJECT_DIR / "data" / "sodex_monitor_eval" / "latest.json"
DATA_DIR = PROJECT_DIR / "data" / "sodex" / "mission_supervisor"
STATUS_FILE = DATA_DIR / "latest.json"
HISTORY_FILE = DATA_DIR / "history.jsonl"
DEFAULT_INTERVAL_S = 900
PERP_UNREALIZED_LOSS_ALERT_USD = -5.0
PERP_UNREALIZED_LOSS_ALERT_EQUITY_PCT = -0.02


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _official_weekly_label(report: dict[str, Any]) -> str:
    window = report.get("window") or {}
    label = str(window.get("weekly_label") or "")
    return label.replace(" ", "_") if label else "current_week"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _next_actions(
    report: dict[str, Any],
    gate_result: dict[str, Any],
    reconcile_result: dict[str, Any],
) -> list[str]:
    blockers = set(gate_result.get("blockers") or []) | set(reconcile_result.get("blockers") or [])
    actions: list[str] = []
    if "official_dashboard_not_canonical" in blockers:
        actions.append(f"refresh_official_dashboard_{_official_weekly_label(report)}")
    if "official_total_credit_rate_low" in blockers or "official_ledger_reconciliation_gap" in blockers:
        actions.append("reconcile_official_vs_ledger_before_scale")
    if "open_perp_positions_present" in blockers:
        actions.append("inspect_open_perp_positions_read_only")
    if "weekly_win_rate_below_target" in blockers:
        actions.append("pause_e2_and_collect_more_e1_quality")
    if "e1_profit_coverage_short" in blockers or "e1_no_loss_coverage_short" in blockers:
        actions.append("increase_e1_profit_subsidy")
    if "volume_below_weekly_target" in blockers or "official_weekly_volume_short" in blockers:
        actions.append("model_capped_volume_catchup_only_after_gates_clear")
    if gate_result.get("decision") == "READY_FOR_FULL_REAL":
        actions.append("await_explicit_user_live_approval")
    if not actions:
        actions.append("continue_read_only_monitoring")
    return _dedupe(actions)


def _perps_risk(report: dict[str, Any]) -> dict[str, Any]:
    account = report.get("account") or {}
    account_value = account.get("account_value") or {}
    assets = account.get("assets") or {}
    positions = [p for p in assets.get("perps_positions") or [] if isinstance(p, dict)]
    total_equity = _num(account_value.get("total_equity_usd"))
    unrealized = _num(account_value.get("perps_unrealized_pnl_calc_usd"))
    if unrealized == 0.0 and positions:
        unrealized = sum(_num(p.get("unrealized_pnl_calc_usd")) for p in positions)
    largest_loss = None
    if positions:
        largest_loss = min(positions, key=lambda p: _num(p.get("unrealized_pnl_calc_usd")))
    loss_pct_equity = (unrealized / total_equity) if total_equity > 0 else None
    alerts: list[str] = []
    if unrealized <= PERP_UNREALIZED_LOSS_ALERT_USD:
        alerts.append("perp_unrealized_loss_alert")
    if loss_pct_equity is not None and loss_pct_equity <= PERP_UNREALIZED_LOSS_ALERT_EQUITY_PCT:
        alerts.append("perp_loss_pct_equity_alert")
    if positions:
        alerts.append("open_perp_positions_present")
    return {
        "open_positions": len(positions),
        "unrealized_pnl_usd": unrealized,
        "loss_pct_equity": loss_pct_equity,
        "largest_loss_symbol": largest_loss.get("symbol") if largest_loss else None,
        "largest_loss_side": largest_loss.get("side") if largest_loss else None,
        "largest_loss_unrealized_pnl_usd": _num(largest_loss.get("unrealized_pnl_calc_usd")) if largest_loss else 0.0,
        "largest_loss_initial_margin_usd": _num(largest_loss.get("initial_margin_usd")) if largest_loss else 0.0,
        "largest_loss_leverage": largest_loss.get("leverage") if largest_loss else None,
        "alerts": _dedupe(alerts),
    }


def _open_orders_risk(open_orders: dict[str, list[dict[str, Any]]] | None) -> dict[str, Any]:
    open_orders = open_orders or {}
    spot_orders = [o for o in open_orders.get("spot", []) if isinstance(o, dict)]
    perps_orders = [o for o in open_orders.get("perps", []) if isinstance(o, dict)]
    spot_buy_frozen = sum(
        _num(o.get("marginFrozen"))
        for o in spot_orders
        if str(o.get("side", "")).upper() == "BUY"
    )
    alerts: list[str] = []
    if spot_orders:
        alerts.append("open_spot_orders_present")
    if perps_orders:
        alerts.append("open_perps_orders_present")
    if spot_buy_frozen > 0:
        alerts.append("spot_buy_capital_frozen")
    return {
        "spot_count": len(spot_orders),
        "perps_count": len(perps_orders),
        "total_count": len(spot_orders) + len(perps_orders),
        "spot_buy_frozen_usd": spot_buy_frozen,
        "spot_symbols": sorted({str(o.get("symbol") or "") for o in spot_orders if o.get("symbol")}),
        "perps_symbols": sorted({str(o.get("symbol") or "") for o in perps_orders if o.get("symbol")}),
        "alerts": alerts,
    }


def _env_address() -> str:
    env_path = PROJECT_DIR / ".env"
    try:
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "SODEX_ADDRESS":
                return value.strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def fetch_open_orders(address: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Read-only open-order list via bin/sodex using public address only."""
    address = address or _env_address()
    if not address:
        return {"spot": [], "perps": []}
    result: dict[str, list[dict[str, Any]]] = {}
    for market in ("spot", "perps"):
        cmd = [
            str(PROJECT_DIR / "bin" / "sodex"),
            "orders",
            "list",
            market,
            "--address",
            address,
            "--format",
            "json",
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(PROJECT_DIR),
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
                env={**os.environ, "SODEX_PRIVATE_KEY": ""},
            )
            payload = json.loads(proc.stdout) if proc.returncode == 0 and proc.stdout.strip() else []
            result[market] = [o for o in payload if isinstance(o, dict)] if isinstance(payload, list) else []
        except Exception:
            result[market] = []
    return result


def _mission_state(gate_result: dict[str, Any], reconcile_result: dict[str, Any], perps_risk: dict[str, Any]) -> str:
    blockers = set(gate_result.get("blockers") or []) | set(reconcile_result.get("blockers") or [])
    if (
        "perp_unrealized_loss_alert" in (perps_risk.get("alerts") or [])
        or "perp_loss_pct_equity_alert" in (perps_risk.get("alerts") or [])
    ):
        return "PERP_LOSS_CONTAINMENT"
    if "official_dashboard_not_canonical" in blockers or "official_total_credit_rate_low" in blockers:
        return "RECON_FIRST"
    if "open_perp_positions_present" in blockers:
        return "POSITION_RISK_FIRST"
    if "weekly_win_rate_below_target" in blockers:
        return "QUALITY_FIRST"
    if "e1_profit_coverage_short" in blockers or "e1_no_loss_coverage_short" in blockers:
        return "E1_PROFIT_FIRST"
    if gate_result.get("decision") == "RESEARCH_AND_CAPPED_CATCHUP":
        return "CAPPED_CATCHUP_READY"
    if gate_result.get("decision") == "READY_FOR_FULL_REAL":
        return "FULL_REAL_CANDIDATE_AWAITING_APPROVAL"
    return "RESEARCH_ONLY"


def _experiment(
    *,
    experiment_id: str,
    priority: int,
    thesis: str,
    success_metric: str,
    guardrail: str,
) -> dict[str, Any]:
    return {
        "id": experiment_id,
        "priority": priority,
        "thesis": thesis,
        "success_metric": success_metric,
        "guardrail": guardrail,
        "mode": "READ_ONLY_OR_PAPER_UNTIL_APPROVED",
    }


def _radical_experiments(
    state: str,
    gate_result: dict[str, Any],
    reconcile_result: dict[str, Any],
    perps_risk: dict[str, Any],
) -> list[dict[str, Any]]:
    blockers = set(gate_result.get("blockers") or []) | set(reconcile_result.get("blockers") or [])
    experiments: list[dict[str, Any]] = []
    if state == "PERP_LOSS_CONTAINMENT":
        experiments.append(_experiment(
            experiment_id="perp_loss_containment_audit",
            priority=110,
            thesis="Open perp unrealized loss is the immediate PnL threat; contain exposure before any farming optimization.",
            success_metric="unrealized perp loss recovers above alert threshold or open perp positions become zero after explicit approved action",
            guardrail="supervisor may inspect and alert only; no autonomous close/open order",
        ))
    if "official_dashboard_not_canonical" in blockers or "official_total_credit_rate_low" in blockers:
        experiments.append(_experiment(
            experiment_id="official_credit_reconciliation",
            priority=100,
            thesis="A strategy is useless if ledger volume is not credited by SoDEX; first prove current-week official credit.",
            success_metric="official dashboard canonical for current weekly label and total credit-rate >= 75%",
            guardrail="do not scale E2 while official credit is stale or below threshold",
        ))
    if "e1_no_loss_coverage_short" in blockers or "e1_profit_coverage_short" in blockers:
        experiments.append(_experiment(
            experiment_id="e1_no_loss_subsidy",
            priority=95,
            thesis="Fee-only maker cannot satisfy the revised maximum target; E1 must create enough realized profit to drive net cost to zero.",
            success_metric="extra_profit_needed_no_loss reaches $0 while win-rate remains >= 69%",
            guardrail="no E2 scale-up if E1 subsidy deteriorates for two consecutive cycles",
        ))
    if "weekly_win_rate_below_target" in blockers:
        experiments.append(_experiment(
            experiment_id="quality_recovery_before_volume",
            priority=90,
            thesis="Volume acceleration with weak weekly win-rate creates hidden PnL risk; recover quality before catch-up.",
            success_metric="weekly win-rate >= 69% and realized PnL non-negative",
            guardrail="research-only until quality gate recovers",
        ))
    if "open_perp_positions_present" in blockers:
        experiments.append(_experiment(
            experiment_id="perp_exposure_cleanup_audit",
            priority=85,
            thesis="Open perp positions contaminate E2 volume experiments and no-loss accounting.",
            success_metric="open perp positions count is zero before E2 scaling",
            guardrail="inspect only; no close/open order from supervisor",
        ))
    if state == "CAPPED_CATCHUP_READY":
        experiments.append(_experiment(
            experiment_id="e2_capped_official_volume_amplifier",
            priority=80,
            thesis="After E1/no-loss and reconciliation gates clear, E2 can be used as a capped official-volume amplifier.",
            success_metric="official volume/hour rises while net_cost_usd stays at $0",
            guardrail="maker-only or paper validation unless separately approved",
        ))
    if state == "FULL_REAL_CANDIDATE_AWAITING_APPROVAL":
        experiments.append(_experiment(
            experiment_id="approval_locked_full_real_candidate",
            priority=100,
            thesis="All measured gates are clean, but supervisor must not self-authorize live trading.",
            success_metric="explicit user live approval plus unchanged clean gate immediately before transition",
            guardrail="no order, transfer, or leverage change from supervisor",
        ))
    if not experiments:
        experiments.append(_experiment(
            experiment_id="continue_shadow_search",
            priority=50,
            thesis="No hard blocker-specific experiment is active; continue collecting shadow evidence and drift checks.",
            success_metric="more validated cohorts with positive after-fee expectancy",
            guardrail="read-only monitoring remains active",
        ))
    return sorted(experiments, key=lambda item: int(item["priority"]), reverse=True)


def evaluate_mission(
    report: dict[str, Any],
    *,
    now: datetime | None = None,
    open_orders: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    gate_result = gate.evaluate_radical_gate(report, now=now)
    reconcile_result = reconcile.analyze_report(report)
    perps_risk = _perps_risk(report)
    open_orders_risk = _open_orders_risk(open_orders)
    state = _mission_state(gate_result, reconcile_result, perps_risk)
    next_actions = _next_actions(report, gate_result, reconcile_result)
    if "perp_unrealized_loss_alert" in perps_risk["alerts"]:
        next_actions = _dedupe(["inspect_open_perp_positions_read_only", "escalate_perp_loss_to_user"] + next_actions)
    if open_orders_risk["alerts"]:
        next_actions = _dedupe(["inspect_open_orders_read_only"] + next_actions)
    radical_experiments = _radical_experiments(state, gate_result, reconcile_result, perps_risk)
    constraints = [
        "no_order",
        "no_transfer",
        "no_leverage_change",
        "do_not_scale_e2",
        "official_dashboard_is_canonical_for_event_progress",
    ]
    if state in {"CAPPED_CATCHUP_READY", "FULL_REAL_CANDIDATE_AWAITING_APPROVAL"}:
        constraints.remove("do_not_scale_e2")
        constraints.append("e2_scale_requires_separate_live_approval")

    profit = gate_result.get("profit") or {}
    volumes = gate_result.get("volumes") or {}
    ratios = gate_result.get("ratios") or {}

    return {
        "ts": now.astimezone(timezone.utc).isoformat(),
        "mode": "READ_ONLY_AUTONOMOUS_SUPERVISION",
        "mission_state": state,
        "live_trade_allowed": False,
        "execution_authority": "NO_ORDER_NO_TRANSFER_NO_LEVERAGE_CHANGE",
        "reason": "supervisor is read-only; live transition still requires clean gates and explicit user approval",
        "targets": gate_result.get("targets", {}),
        "gate_decision": gate_result.get("decision"),
        "gate_blockers": gate_result.get("blockers", []),
        "reconciliation_decision": reconcile_result.get("decision"),
        "reconciliation_blockers": reconcile_result.get("blockers", []),
        "risk_alerts": _dedupe(perps_risk["alerts"] + open_orders_risk["alerts"]),
        "perps_risk": perps_risk,
        "open_orders_risk": open_orders_risk,
        "official": reconcile_result.get("official", {}),
        "ledger": reconcile_result.get("ledger", {}),
        "ratios": {
            "official_raw_net_ratio": ratios.get("official_raw_net_ratio"),
            "official_weighted_net_ratio": ratios.get("official_weighted_net_ratio"),
        },
        "e1": {
            "fees_usd": _num(profit.get("fees_usd")),
            "realized_pnl_usd": _num(profit.get("realized_pnl_usd")),
            "net_cost_usd": _num(profit.get("net_cost_usd")),
            "extra_profit_needed_raw_9000": _num(profit.get("extra_profit_needed_raw_9000")),
            "extra_profit_needed_no_loss": _num(profit.get("extra_profit_needed_no_loss")),
        },
        "volume": {
            "official_raw_usd": _num(volumes.get("official_raw_usd")),
            "ledger_raw_usd": _num(volumes.get("ledger_raw_usd")),
            "official_remaining_raw_usd": _num(volumes.get("official_remaining_raw_usd")),
        },
        "capital": gate_result.get("capital", {}),
        "next_actions": next_actions,
        "radical_experiments": radical_experiments,
        "constraints": constraints,
        "data_sources": {
            "monitor_latest": str(DEFAULT_LATEST),
            "status_file": str(STATUS_FILE),
            "history_file": str(HISTORY_FILE),
        },
    }


def persist_status(status: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, indent=2, sort_keys=True))
    tmp.replace(STATUS_FILE)
    with HISTORY_FILE.open("a") as fh:
        fh.write(json.dumps(status, sort_keys=True) + "\n")


def run_once(latest: Path = DEFAULT_LATEST, *, refresh_monitor: bool = False) -> dict[str, Any]:
    if refresh_monitor:
        subprocess.run(
            [sys.executable, str(PROJECT_DIR / "scripts" / "sodex_monitor_eval.py")],
            cwd=str(PROJECT_DIR),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    report = json.loads(latest.read_text())
    address = ((report.get("account") or {}).get("address")) or ""
    if "..." in address or len(address) < 42:
        address = _env_address()
    status = evaluate_mission(report, open_orders=fetch_open_orders(address))
    persist_status(status)
    return status


def format_text(status: dict[str, Any]) -> str:
    e1 = status.get("e1") or {}
    volume = status.get("volume") or {}
    perps = status.get("perps_risk") or {}
    open_orders = status.get("open_orders_risk") or {}
    lines = [
        f"mission_state: {status['mission_state']}",
        f"live_trade_allowed: {status['live_trade_allowed']}",
        f"gate_decision: {status['gate_decision']}",
        f"gate_blockers: {', '.join(status['gate_blockers']) if status['gate_blockers'] else '-'}",
        f"reconciliation_blockers: {', '.join(status['reconciliation_blockers']) if status['reconciliation_blockers'] else '-'}",
        f"risk_alerts: {', '.join(status.get('risk_alerts', [])) if status.get('risk_alerts') else '-'}",
        f"perps_unrealized: ${perps.get('unrealized_pnl_usd', 0.0):,.2f}",
        f"largest_perp_loss: {perps.get('largest_loss_symbol') or '-'} ${perps.get('largest_loss_unrealized_pnl_usd', 0.0):,.2f}",
        f"open_orders: spot={open_orders.get('spot_count', 0)} perps={open_orders.get('perps_count', 0)} frozen_buy=${open_orders.get('spot_buy_frozen_usd', 0.0):,.2f}",
        f"official_volume: ${volume.get('official_raw_usd', 0.0):,.2f}",
        f"ledger_volume: ${volume.get('ledger_raw_usd', 0.0):,.2f}",
        f"remaining_volume: ${volume.get('official_remaining_raw_usd', 0.0):,.2f}",
        f"e1_extra_profit_9000: ${e1.get('extra_profit_needed_raw_9000', 0.0):,.2f}",
        f"e1_extra_profit_no_loss: ${e1.get('extra_profit_needed_no_loss', 0.0):,.2f}",
        "radical_experiments:",
    ]
    for experiment in status.get("radical_experiments", [])[:3]:
        lines.append(
            f"- P{experiment.get('priority')} {experiment.get('id')}: {experiment.get('success_metric')}"
        )
    lines.extend([
        "next_actions:",
    ])
    lines.extend(f"- {action}" for action in status.get("next_actions", []))
    lines.append("constraints:")
    lines.extend(f"- {constraint}" for constraint in status.get("constraints", []))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SoDEX 84h read-only mission supervisor")
    parser.add_argument("--latest", type=Path, default=DEFAULT_LATEST)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_S)
    parser.add_argument("--refresh-monitor", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    while True:
        status = run_once(args.latest, refresh_monitor=args.refresh_monitor)
        print(json.dumps(status, indent=2, sort_keys=True) if args.json else format_text(status), flush=True)
        if not args.loop:
            break
        time.sleep(max(60, args.interval))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
