#!/usr/bin/env python3
"""Read-only SoDEX project structure index and cleanup map."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
MODE = "READ_ONLY_SODEX_PROJECT_STRUCTURE"
POLICY = "no moves, no deletes, no live actions; canonical structure only"

CANONICAL_DOMAINS = [
    {
        "domain": "core_decision",
        "purpose": "Read-only decision, target, probability, policy, and volume planning layer.",
        "canonical_paths": ["scripts/sodex_quant_stat_engine.py", "scripts/sodex_system_map.py", "scripts/sodex_target_policy.py"],
    },
    {
        "domain": "safety",
        "purpose": "Safety halt, guardian, deadman, reconciliation, and order-surface controls.",
        "canonical_paths": ["scripts/sodex_safety_guardian.py", "scripts/sodex_deadman_switch.py", "scripts/sodex_order_surface_audit.py"],
    },
    {
        "domain": "execution",
        "purpose": "Order-capable or historically order-capable engines; must stay behind operator approval and guards.",
        "canonical_paths": ["anantara/sodex_twin_engine.py", "scripts/sodex_micro_pilot.py", "anantara/sodex_farming.py"],
    },
    {
        "domain": "market_data",
        "purpose": "Collectors, ticker scans, OBI, funding, and monitor evaluation inputs.",
        "canonical_paths": ["scripts/sodex_market_ticker_scanner.py", "scripts/sodex_monitor_eval.py", "scripts/sodex_funding_collector.py"],
    },
    {
        "domain": "research",
        "purpose": "Backtests, paper tests, autonomous research, and academic/quant experiments.",
        "canonical_paths": ["scripts/research", "scripts/sodex_autonomous_research.py", "docs/SODEX_QUANT_STAT_ANALYTIC_TRADING_RESEARCH_2026-07-16.md"],
    },
    {
        "domain": "services",
        "purpose": "Systemd unit files and operator service/timer entry points.",
        "canonical_paths": ["systemd/sodex-monitor-eval.timer", "systemd/sodex-market-ticker-scanner.service"],
    },
    {
        "domain": "docs",
        "purpose": "Human-readable operating doctrine, system map, status, audit, and handover material.",
        "canonical_paths": ["docs/SODEX_SYSTEM_MAP.md", "docs/SODEX_PROJECT_STRUCTURE.md"],
    },
    {
        "domain": "data",
        "purpose": "Generated local state, latest reports, JSONL histories, halt flags, and ledgers.",
        "canonical_paths": ["data/sodex_quant_stat/latest.json", "data/sodex_system_map/latest.json", "data/SAFETY_HALT"],
    },
    {
        "domain": "tests",
        "purpose": "Unit and regression tests for SoDEX safety, decision, monitoring, and execution helpers.",
        "canonical_paths": ["tests/test_sodex_quant_stat_engine.py", "tests/test_sodex_project_structure.py"],
    },
    {
        "domain": "legacy_or_archive",
        "purpose": "Historical reports, old drafts, and compatibility artifacts. Keep read-only unless explicitly migrated.",
        "canonical_paths": ["docs/archive", "docs/*STATUS*", "reports/*SODEX*"],
    },
]


def utc_now() -> str:
    """Return ISO UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def classify_path(path: Path) -> dict[str, str]:
    """Classify a SoDEX-related repo path into a canonical operational domain."""
    text = path.as_posix()
    name = path.name.lower()
    lower = text.lower()

    if lower.startswith("tests/"):
        return {"domain": "tests", "status": "present"}
    if lower.startswith("data/"):
        return {"domain": "data", "status": "generated"}
    if lower.startswith("systemd/") or "/systemd/" in lower or lower.endswith((".service", ".timer")):
        return {"domain": "services", "status": "present"}
    if lower.startswith("docs/") or lower.startswith("reports/"):
        domain = "legacy_or_archive" if any(token in lower for token in ("archive", "status_", "status-")) else "docs"
        return {"domain": domain, "status": "present"}
    if lower.startswith("scripts/research/") or "research" in lower or "paper" in lower or "backtest" in lower:
        return {"domain": "research", "status": "present"}
    if any(token in name for token in ("guardian", "deadman", "safety", "reconciliation", "order_surface", "watchdog")):
        return {"domain": "safety", "status": "present"}
    if any(token in name for token in ("twin_engine", "micro_pilot", "farming", "autofarm", "spot_daemon", "measure")):
        return {"domain": "execution", "status": "present"}
    if any(token in name for token in ("market", "monitor", "collector", "funding", "obi", "ticker")):
        return {"domain": "market_data", "status": "present"}
    if any(token in name for token in ("quant_stat", "project_structure", "system_map", "target_policy", "volume_planner", "mode_audit", "event_barbell", "e2dir", "ta_probability", "scalp_microstructure")):
        return {"domain": "core_decision", "status": "present"}
    return {"domain": "legacy_or_archive", "status": "present"}


def discover_sodex_paths(project: Path) -> list[Path]:
    """Discover SoDEX-related paths without scanning heavy runtime logs."""
    roots = ["scripts", "anantara", "docs", "reports", "systemd", "tests", "data"]
    paths: list[Path] = []
    for root_name in roots:
        root = project / root_name
        if not root.exists():
            continue
        for item in root.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(project)
            text = rel.as_posix().lower()
            if "__pycache__" in text or text.endswith((".pyc", ".pyo")):
                continue
            if root_name == "data" and not any(token in text for token in ("sodex", "safety_halt", "pnl_halt")):
                continue
            if root_name != "data" and not any(token in text for token in ("sodex", "perps", "scalp", "measure", "guardian", "deadman", "watchdog")):
                continue
            if item.stat().st_size > 2_000_000 and root_name in {"data", "reports"}:
                continue
            paths.append(rel)
    return sorted(set(paths), key=lambda path: path.as_posix())


def build_report(project: Path = PROJECT) -> dict[str, Any]:
    """Build a read-only canonical structure report."""
    items: list[dict[str, Any]] = []
    for rel in discover_sodex_paths(project):
        classified = classify_path(rel)
        items.append({
            "path": rel.as_posix(),
            "domain": classified["domain"],
            "status": classified["status"],
        })

    counts = Counter(item["domain"] for item in items)
    recommendations = [
        "Keep runtime execution behind safety_halt, quant_stat_decision_engine, policy gates, and operator approval.",
        "Do not physically move legacy SoDEX files until import/service references are migrated and tested.",
        "Treat docs/status/reports as historical evidence; use docs/SODEX_SYSTEM_MAP.md and docs/SODEX_PROJECT_STRUCTURE.md as current entry points.",
        "Use data/sodex_quant_stat/latest.json and data/sodex_system_map/latest.json as current machine-readable control-plane outputs.",
    ]
    return {
        "ts": utc_now(),
        "mode": MODE,
        "policy": POLICY,
        "project": str(project),
        "summary": {
            "total": len(items),
            "by_domain": dict(sorted(counts.items())),
        },
        "canonical_domains": CANONICAL_DOMAINS,
        "items": items,
        "recommendations": recommendations,
    }


def build_markdown(report: dict[str, Any]) -> str:
    """Render a project structure report as Markdown."""
    lines = [
        "# SoDEX Project Structure",
        "",
        f"Generated UTC: `{report['ts']}`",
        "",
        f"Mode: `{report['mode']}`",
        "",
        f"Policy: `{report['policy']}`",
        "",
        "## Summary",
        "",
        f"- Total indexed files: `{report['summary']['total']}`",
    ]
    for domain, count in sorted((report["summary"].get("by_domain") or {}).items()):
        lines.append(f"- `{domain}`: `{count}`")

    lines.extend(["", "## Canonical Domains", ""])
    for domain in report["canonical_domains"]:
        lines.append(f"### `{domain['domain']}`")
        lines.append("")
        lines.append(domain["purpose"])
        lines.append("")
        lines.append("Canonical entry points:")
        for path in domain.get("canonical_paths") or []:
            lines.append(f"- `{path}`")
        lines.append("")

    lines.extend(["## Indexed Files", ""])
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for item in report.get("items") or []:
        by_domain.setdefault(item["domain"], []).append(item)
    for domain in sorted(by_domain):
        lines.append(f"### `{domain}`")
        lines.append("")
        for item in by_domain[domain][:80]:
            lines.append(f"- `{item['path']}` ({item['status']})")
        remaining = len(by_domain[domain]) - 80
        if remaining > 0:
            lines.append(f"- ... `{remaining}` more")
        lines.append("")

    lines.extend(["## Recommendations", ""])
    for recommendation in report.get("recommendations") or []:
        lines.append(f"- {recommendation}")
    lines.append("")
    return "\n".join(lines)


def persist_report(project: Path, report: dict[str, Any]) -> None:
    """Persist latest JSON and Markdown structure docs."""
    out_dir = project / "data" / "sodex_project_structure"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    docs_dir = project / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "SODEX_PROJECT_STRUCTURE.md").write_text(build_markdown(report), encoding="utf-8")


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Build read-only SoDEX project structure index")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    parser.add_argument("--no-persist", action="store_true", help="Do not write docs/data artifacts")
    args = parser.parse_args()
    report = build_report(PROJECT)
    if not args.no_persist:
        persist_report(PROJECT, report)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(build_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
