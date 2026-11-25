#!/usr/bin/env python3
"""Read-only SoDEX Farming system map and health synthesis.

The goal is to make every SoDEX subsystem visible in one place: what it does,
what it depends on, what data proves it is alive, and what should be fixed next.
This script does not call signed trade endpoints and never places/cancels orders.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT / "data" / "sodex_system_map"
LATEST = OUT_DIR / "latest.json"
DOC = PROJECT / "docs" / "SODEX_SYSTEM_MAP.md"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def read_jsonl_tail(path: Path, limit: int = 25) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def file_age_minutes(path: Path, now: datetime | None = None) -> float | None:
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return None
    return round(((now or utc_now()) - mtime).total_seconds() / 60, 2)


def service_state(name: str) -> str:
    proc = subprocess.run(
        ["systemctl", "--user", "is-active", name],
        cwd=PROJECT,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    state = (proc.stdout or proc.stderr).strip()
    if "Failed to connect to bus" in state or "Operation not permitted" in state:
        return "unknown_bus_denied"
    return state or f"rc={proc.returncode}"


def service_is_inactive(state: str) -> bool:
    return state in {"inactive", "failed", "deactivating"} or state.startswith("rc=")


def artifact(path: str, stale_after_min: float | None = None) -> dict[str, Any]:
    full = PROJECT / path
    age = file_age_minutes(full)
    exists = age is not None
    status = "missing"
    if exists:
        status = "fresh"
        if stale_after_min is not None and age is not None and age > stale_after_min:
            status = "stale"
    return {
        "path": path,
        "exists": exists,
        "age_min": age,
        "status": status,
        "stale_after_min": stale_after_min,
    }


def glob_artifact(pattern: str, stale_after_min: float | None = None) -> dict[str, Any]:
    files = [path for path in PROJECT.glob(pattern) if path.is_file()]
    if not files:
        return {
            "path": pattern,
            "exists": False,
            "age_min": None,
            "status": "missing",
            "stale_after_min": stale_after_min,
            "count": 0,
        }
    newest = max(files, key=lambda path: path.stat().st_mtime)
    age = file_age_minutes(newest)
    status = "fresh"
    if stale_after_min is not None and age is not None and age > stale_after_min:
        status = "stale"
    return {
        "path": pattern,
        "exists": True,
        "age_min": age,
        "status": status,
        "stale_after_min": stale_after_min,
        "count": len(files),
        "newest": str(newest.relative_to(PROJECT)),
    }


@dataclass
class Subsystem:
    name: str
    role: str
    status: str
    upstream: list[str]
    downstream: list[str]
    services: dict[str, str]
    artifacts: list[dict[str, Any]]
    findings: list[str]
    next_actions: list[str]


def status_from_services(services: dict[str, str], artifacts_: list[dict[str, Any]]) -> str:
    if any(value == "failed" for value in services.values()):
        return "failed"
    if any(item["status"] == "missing" for item in artifacts_):
        return "degraded"
    if any(item["status"] == "stale" for item in artifacts_):
        return "stale"
    readable = [value for value in services.values() if value != "unknown_bus_denied"]
    if readable and not any(value in {"active", "activating"} for value in readable):
        return "inactive"
    return "ok"


def micro_edge_summary(path: Path) -> dict[str, Any]:
    rows = read_jsonl_tail(path, 200)
    live_closed = [
        row for row in rows
        if row.get("mode") == "live" and row.get("closed") is True
    ]
    if not live_closed:
        return {"live_closed": 0, "net_delta_usd": 0.0, "wins": 0, "losses": 0, "win_rate": None}
    deltas = [float(row.get("perps_account_delta_usd") or 0.0) for row in live_closed]
    wins = sum(1 for value in deltas if value > 0)
    losses = sum(1 for value in deltas if value < 0)
    return {
        "live_closed": len(live_closed),
        "net_delta_usd": round(sum(deltas), 8),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(live_closed), 4),
    }


def build_report() -> dict[str, Any]:
    now = utc_now()
    monitor = read_json(PROJECT / "data" / "sodex_monitor_eval" / "latest.json") or {}
    market = read_json(PROJECT / "data" / "sodex_market_scan" / "latest.json") or {}
    telegram = read_json(PROJECT / "data" / "telegram_health.json") or {}
    learned = read_json(PROJECT / "data" / "sodex_learned_params.json") or {}
    autonomous = read_json(PROJECT / "data" / "sodex" / "research" / "autonomous_status.json") or {}
    micro = micro_edge_summary(PROJECT / "data" / "sodex_micro_pilot.jsonl")

    position_truth = monitor.get("account", {}).get("position_truth", {})
    account_value = monitor.get("account", {}).get("account_value", {})
    market_counts = market.get("counts", {})
    telegram_verdict = telegram.get("verdict") or "unknown"

    subsystems: list[Subsystem] = []

    collector_artifacts = [
        glob_artifact("freqtrade_user_data/data/sodex/obi/obi_*.jsonl", 5),
        artifact("data/pregain_monitor_state.json", 30),
    ]
    subsystems.append(Subsystem(
        name="data_collectors",
        role="Raw OBI, spot/perps observation, and pre-gain monitor inputs for all downstream decisions.",
        status=status_from_services({
            "anantara-obi.service": service_state("anantara-obi.service"),
            "anantara-spot.service": service_state("anantara-spot.service"),
        }, collector_artifacts),
        upstream=["SoDEX public/orderbook endpoints", "collector services"],
        downstream=["market_scan", "pregain", "microstructure_scan", "deep_learning_loop"],
        services={
            "anantara-obi.service": service_state("anantara-obi.service"),
            "anantara-spot.service": service_state("anantara-spot.service"),
        },
        artifacts=collector_artifacts,
        findings=[
            f"obi_files={collector_artifacts[0].get('count', 0)}",
            f"obi_newest={collector_artifacts[0].get('newest')}",
        ],
        next_actions=["Keep collectors fresh; stale OBI invalidates short-term microstructure decisions."],
    ))

    market_artifacts = [artifact("data/sodex_market_scan/latest.json", 2)]
    market_findings = [
        f"markets_seen={market_counts.get('total', 0)} perps={market_counts.get('perps', 0)} spot={market_counts.get('spot', 0)} zero_book={market_counts.get('zero_book', 0)}"
    ]
    subsystems.append(Subsystem(
        name="market_scan",
        role="Realtime read-only SoDEX ticker scan, liquidity ranking, movers, zero-book detection.",
        status=status_from_services({"sodex-market-ticker-scanner.service": service_state("sodex-market-ticker-scanner.service")}, market_artifacts),
        upstream=["bin/sodex tickers spot", "bin/sodex tickers perps"],
        downstream=["technical_probability_gate", "candidate_scoring", "micro_pilot", "operator_review"],
        services={"sodex-market-ticker-scanner.service": service_state("sodex-market-ticker-scanner.service")},
        artifacts=market_artifacts,
        findings=market_findings,
        next_actions=["Use short_watch only as candidate input; require policy and microstructure gates before live exposure."],
    ))

    ta_artifacts = [
        artifact("scripts/sodex_ta_probability_gate.py"),
        artifact("scripts/e2_signal_scanner.py"),
        artifact("data/e2_signal_latest.jsonl"),
        artifact("data/sodex_market_scan/history.jsonl", 5),
    ]
    subsystems.append(Subsystem(
        name="technical_probability_gate",
        role="Seven-signal TA and quantitative probability layer before any live micro-scalp entry.",
        status=status_from_services({}, ta_artifacts),
        upstream=["market_scan history", "E2 signal scanner", "SoDEX ticker/orderbook snapshots"],
        downstream=["quant_stat_decision_engine", "policy_and_gates", "live_short_accelerator", "micro_pilot"],
        services={},
        artifacts=ta_artifacts,
        findings=[
            "e2_signal_scanner exists but is Binance-limited and advisory",
            "sodex_ta_probability_gate converts local SoDEX scanner history into seven-signal probability evidence",
        ],
        next_actions=["Require probability >=0.80 and ratio-budget adverse-loss pass before any live short probe."],
    ))

    quant_artifacts = [
        artifact("scripts/sodex_quant_stat_engine.py"),
        artifact("data/sodex_quant_stat/latest.json", 10),
        artifact("data/sodex_quant_stat/history.jsonl"),
    ]
    subsystems.append(Subsystem(
        name="quant_stat_decision_engine",
        role="Read-only SoDEX quantitative statistical fusion layer: TA probability, calibration, fill probability, costs, and ratio budget.",
        status=status_from_services({}, quant_artifacts),
        upstream=["technical_probability_gate", "market_scan", "monitor_eval", "micro_pilot experience log"],
        downstream=["policy_and_gates", "operator_approval", "micro_pilot"],
        services={},
        artifacts=quant_artifacts,
        findings=[
            "sodex_quant_stat_engine is read-only and emits TRADE_READY/WAIT/BLOCK decisions",
            "live promotion still requires operator approval and existing execution guards",
        ],
        next_actions=["Run the quant-stat engine before any volume increase; treat calibration gaps as WAIT, not permission to trade."],
    ))

    monitor_artifacts = [artifact("data/sodex_monitor_eval/latest.json", 10)]
    monitor_findings = [
        f"total_equity_usd={account_value.get('total_equity_usd')}",
        f"perps_positions={position_truth.get('open_count')} quality={position_truth.get('quality')}",
        f"halt_active={monitor.get('halt_status', {}).get('active')}",
    ]
    subsystems.append(Subsystem(
        name="monitor_eval",
        role="Account truth, PnL/ledger, halt status, position truth, and risk summary.",
        status=status_from_services({"sodex-monitor-eval.timer": service_state("sodex-monitor-eval.timer")}, monitor_artifacts),
        upstream=["SoDEX account endpoints", "local ledger", "position state"],
        downstream=["target_policy", "event_barbell", "capital_report", "safety_gates"],
        services={"sodex-monitor-eval.timer": service_state("sodex-monitor-eval.timer")},
        artifacts=monitor_artifacts,
        findings=monitor_findings,
        next_actions=["Keep this as canonical account truth before approving any execution lane."],
    ))

    learning_artifacts = [
        artifact("data/sodex_learned_params.json", 10),
        artifact("data/sodex_deep_learning.jsonl", 10),
    ]
    learning_findings = [
        f"regime={learned.get('regime') or learned.get('market_regime') or 'unknown'}",
        f"awareness_experience_learning_present={all(key in json.dumps(learned).lower() for key in ['awareness', 'experience', 'learning'])}",
    ]
    subsystems.append(Subsystem(
        name="deep_learning_loop",
        role="Awareness + Experience + Learning parameter loop for spreads, confidence, and regime memory.",
        status=status_from_services({"sodex-deep-learner.service": service_state("sodex-deep-learner.service")}, learning_artifacts),
        upstream=["monitor_eval", "fills", "market_scan", "experience log"],
        downstream=["twin_engine", "scanner_thresholds", "operator_policy"],
        services={"sodex-deep-learner.service": service_state("sodex-deep-learner.service")},
        artifacts=learning_artifacts,
        findings=learning_findings,
        next_actions=["Continue validating learned params with out-of-sample gates before live promotion."],
    ))

    research_artifacts = [artifact("data/sodex/research/autonomous_status.json", 10)]
    research_status = status_from_services({"sodex-autonomous-research.service": service_state("sodex-autonomous-research.service")}, research_artifacts)
    subsystems.append(Subsystem(
        name="autonomous_research",
        role="External/local research loop, candidate discovery, and adaptive policy evidence.",
        status=research_status,
        upstream=["market data", "local research notebooks", "Hermes/intel snapshots"],
        downstream=["target_policy", "e2dir_amplifier", "mode_audit"],
        services={"sodex-autonomous-research.service": service_state("sodex-autonomous-research.service")},
        artifacts=research_artifacts,
        findings=[f"keys={len(autonomous.keys()) if isinstance(autonomous, dict) else 0}"],
        next_actions=["Treat research as advisory; require monitor_eval and execution guard agreement before live use."],
    ))

    policy_artifacts = [
        artifact("scripts/sodex_target_policy.py"),
        artifact("scripts/sodex_mode_audit.py"),
        artifact("scripts/sodex_event_barbell.py"),
        artifact("scripts/sodex_e2dir_amplifier.py"),
        artifact("scripts/sodex_scalp_microstructure.py"),
    ]
    subsystems.append(Subsystem(
        name="policy_and_gates",
        role="Scientific go/no-go layer: target policy, mode audit, event barbell, E2Dir amplifier, and fee/spread scanner.",
        status=status_from_services({}, policy_artifacts),
        upstream=["monitor_eval", "market_scan", "technical_probability_gate", "quant_stat_decision_engine", "autonomous_research", "deep_learning_loop"],
        downstream=["execution_guard", "operator_approval", "micro_pilot"],
        services={},
        artifacts=policy_artifacts,
        findings=["Current target policy blocks E1/E2 scale and allows only tightly capped micro short lane."],
        next_actions=["Promote only when realized edge, win-rate, fee ratio, and official reconciliation all pass."],
    ))

    micro_artifacts = [artifact("data/sodex_micro_pilot.jsonl", 60)]
    micro_status = "cooldown" if micro["live_closed"] and micro["net_delta_usd"] < 0 else status_from_services({}, micro_artifacts)
    subsystems.append(Subsystem(
        name="micro_pilot",
        role="Small controlled live/perps pilot lane for short-only experiments under loss budget.",
        status=micro_status,
        upstream=["target_policy", "market_scan", "technical_probability_gate", "microstructure_scan", "monitor_eval"],
        downstream=["experience_log", "deep_learning_loop", "event_barbell"],
        services={},
        artifacts=micro_artifacts,
        findings=[f"live_closed={micro['live_closed']} net_delta_usd={micro['net_delta_usd']} win_rate={micro['win_rate']}"],
        next_actions=["Keep live paused when net edge is negative; use paper/e2dir scans until edge recovers."],
    ))

    execution_artifacts = [artifact("scripts/sodex_order_surface_audit.py")]
    subsystems.append(Subsystem(
        name="execution_guard",
        role="Code surface audit for order-capable modules and guardrail discipline.",
        status="ok" if execution_artifacts[0]["exists"] else "missing",
        upstream=["order-capable scripts", "runtime safety templates"],
        downstream=["operator_approval", "live_readiness"],
        services={
            "sodex-guardian.service": service_state("sodex-guardian.service"),
            "sodex-safety-guardian.service": service_state("sodex-safety-guardian.service"),
            "sodex-deadman.timer": service_state("sodex-deadman.timer"),
        },
        artifacts=execution_artifacts,
        findings=["Order surface audit script exists; guardian/deadman service states are reported separately."],
        next_actions=["Review inactive guardian/deadman units before increasing notional or autonomy."],
    ))

    supervisor_artifacts = [
        artifact("data/sodex/mission_supervisor/latest.json", 240),
        artifact("data/sodex_system_map/latest.json", 30),
        artifact("data/sodex_project_structure/latest.json", 1440),
        artifact("docs/SODEX_PROJECT_STRUCTURE.md"),
    ]
    subsystems.append(Subsystem(
        name="supervisor_reporting",
        role="Mission supervisor, capital reporting, and integrated status documents for operator decisions.",
        status=status_from_services({
            "sodex-84h-supervisor.service": service_state("sodex-84h-supervisor.service"),
            "sodex-capital-report.timer": service_state("sodex-capital-report.timer"),
        }, supervisor_artifacts),
        upstream=["monitor_eval", "system_map", "capital_report"],
        downstream=["operator_review", "telegram_alerting", "manual_approval"],
        services={
            "sodex-84h-supervisor.service": service_state("sodex-84h-supervisor.service"),
            "sodex-capital-report.timer": service_state("sodex-capital-report.timer"),
        },
        artifacts=supervisor_artifacts,
        findings=["System map is now the primary local operator map; mission supervisor artifact is reported for freshness."],
        next_actions=["Refresh supervisor/reporting artifacts before any long autonomous run."],
    ))

    telegram_status = "ok" if telegram_verdict in {"ok", "healthy"} else "degraded"
    subsystems.append(Subsystem(
        name="telegram_alerting",
        role="Operator alerts and capital reports.",
        status=telegram_status,
        upstream=["capital_report", "monitor_eval", "telegram credentials"],
        downstream=["operator_response"],
        services={"sodex-capital-report.timer": service_state("sodex-capital-report.timer")},
        artifacts=[artifact("data/telegram_health.json", 360)],
        findings=[f"verdict={telegram_verdict}", f"http_status={telegram.get('getMe', {}).get('http_status')}"],
        next_actions=["Rotate TELEGRAM_BOT_TOKEN if verdict remains unauthorized; do not log the token value."],
    ))

    summary_status = "ok"
    degraded = [sub.name for sub in subsystems if sub.status not in {"ok"}]
    if degraded:
        summary_status = "degraded"

    blockers: list[str] = []
    if telegram_status != "ok":
        blockers.append("telegram_alerting_degraded")
    if micro_status == "cooldown":
        blockers.append("micro_pilot_negative_edge_cooldown")
    if position_truth.get("quality") not in {None, "OK"}:
        blockers.append("position_truth_not_ok")
    inactive_guards = [
        name for name in ("sodex-guardian.service", "sodex-safety-guardian.service", "sodex-deadman.timer")
        if service_is_inactive(service_state(name))
    ]
    if inactive_guards:
        blockers.append("guardian_deadman_units_inactive")

    return {
        "ts": now.isoformat(),
        "mode": "READ_ONLY_SODEX_SYSTEM_MAP",
        "policy": "no orders, no cancels, no leverage change, no credential change, no service restart",
        "summary_status": summary_status,
        "blockers": blockers,
        "canonical_flow": [
            "data_collectors",
            "market_scan",
            "technical_probability_gate",
            "quant_stat_decision_engine",
            "autonomous_research",
            "monitor_eval",
            "deep_learning_loop",
            "policy_and_gates",
            "execution_guard",
            "supervisor_reporting",
            "operator_approval",
            "micro_pilot_or_engine",
            "experience_log_back_to_learning",
        ],
        "account_snapshot": {
            "total_equity_usd": account_value.get("total_equity_usd"),
            "spot_equity_usd": account_value.get("spot_equity_usd"),
            "perps_account_value_usd": account_value.get("perps_account_value_usd"),
            "open_perps_positions": position_truth.get("open_count"),
        },
        "subsystems": [asdict(sub) for sub in subsystems],
    }


def build_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# SoDEX Farming System Map",
        "",
        f"Generated UTC: `{report['ts']}`",
        "",
        f"Mode: `{report['mode']}`",
        "",
        f"Policy: `{report['policy']}`",
        "",
        f"Summary status: `{report['summary_status']}`",
        "",
        "## Canonical Flow",
        "",
    ]
    for idx, item in enumerate(report["canonical_flow"], 1):
        lines.append(f"{idx}. `{item}`")
    lines.extend(["", "## Account Snapshot", ""])
    for key, value in report["account_snapshot"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Blockers", ""])
    if report["blockers"]:
        lines.extend(f"- `{item}`" for item in report["blockers"])
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Subsystems",
        "",
        "| Subsystem | Status | Role | Evidence | Next Action |",
        "|---|---:|---|---|---|",
    ])
    for sub in report["subsystems"]:
        evidence = "; ".join(
            f"{item['path']}={item['status']} age_min={item['age_min']}"
            for item in sub["artifacts"]
        )
        next_action = " ".join(sub["next_actions"])
        role = sub["role"].replace("|", "/")
        lines.append(f"| `{sub['name']}` | `{sub['status']}` | {role} | {evidence} | {next_action} |")
    lines.extend(["", "## Data Dependencies", ""])
    for sub in report["subsystems"]:
        lines.append(f"### {sub['name']}")
        lines.append(f"- Upstream: {', '.join(f'`{x}`' for x in sub['upstream'])}")
        lines.append(f"- Downstream: {', '.join(f'`{x}`' for x in sub['downstream'])}")
        if sub["services"]:
            services = ", ".join(f"`{name}`={state}" for name, state in sub["services"].items())
            lines.append(f"- Services: {services}")
        if sub["findings"]:
            lines.append(f"- Findings: {'; '.join(sub['findings'])}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def persist(report: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DOC.parent.mkdir(parents=True, exist_ok=True)
    tmp = LATEST.with_name(f".{LATEST.name}.tmp")
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(LATEST)
    DOC.write_text(build_markdown(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only SoDEX Farming system map")
    parser.add_argument("--json", action="store_true", help="print full JSON report")
    args = parser.parse_args(argv)
    report = build_report()
    persist(report)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(json.dumps({
            "ts": report["ts"],
            "summary_status": report["summary_status"],
            "blockers": report["blockers"],
            "subsystems": {sub["name"]: sub["status"] for sub in report["subsystems"]},
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
