"""Project-level live gate for Top Pre-Gain-Loser.

This is a hard safety layer above per-signal edge gates. It reads the scientific
evidence reports produced by the research pipeline and blocks live orders unless
the project-level granular and execution-cost checks explicitly confirm a tiny
manual pilot.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_PATH = ROOT / "data/pregain_evidence_hardening.json"
DEFAULT_SOVEREIGN_VERDICT_PATH = ROOT / "data/pregain_sovereign_verdict.json"
DEFAULT_AUDIT_CROSSWALK_PATH = ROOT / "data/pregain_audit_crosswalk.json"
DEFAULT_OOS_LOCKBOX_PATH = ROOT / "data/pregain_oos_lockbox.json"

LIVE_READY_DECISIONS = {"LIVE_PILOT_READY"}
LIVE_READY_SOVEREIGN_VERDICTS = {"GO_LIVE_MICRO"}
MANUAL_PILOT_POLICY = "MANUAL_APPROVED"
PRIMARY_ROUTE = "PERPS_SHORT h04h_plus"
SOVEREIGN_TTL_DAYS = 8.0


@dataclass(frozen=True)
class ProjectGateResult:
    allowed: bool
    verdict: str
    reason: str
    blockers: list[str]
    evidence_path: str | None = None
    sovereign_path: str | None = None
    audit_crosswalk_path: str | None = None
    oos_lockbox_path: str | None = None


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _sovereign_blockers(
    sovereign_path: Path,
    *,
    now_ts: float,
    ttl_days: float,
) -> list[str]:
    if not sovereign_path.exists():
        return ["SOVEREIGN_VERDICT_MISSING"]

    data = _load_json(sovereign_path)
    if not data:
        return ["SOVEREIGN_VERDICT_UNREADABLE"]

    blockers: list[str] = []
    saved_ts = data.get("saved_ts")
    try:
        age_days = (now_ts - float(saved_ts)) / 86400.0
    except (TypeError, ValueError):
        blockers.append("SOVEREIGN_VERDICT_MISSING_TIMESTAMP")
    else:
        if age_days < -0.01:
            blockers.append("SOVEREIGN_VERDICT_FUTURE_TIMESTAMP")
        if age_days > ttl_days:
            blockers.append("SOVEREIGN_VERDICT_STALE")

    if str(data.get("verdict") or "") not in LIVE_READY_SOVEREIGN_VERDICTS:
        blockers.append("SOVEREIGN_NOT_GO_LIVE_MICRO")

    try:
        passed_gates = int(data.get("passed_gates", 0) or 0)
        total_gates = int(data.get("total_gates", 0) or 0)
    except (TypeError, ValueError):
        passed_gates = 0
        total_gates = 0
    if passed_gates < 10 or total_gates < 10 or passed_gates < total_gates:
        blockers.append("SOVEREIGN_GATES_NOT_10_OF_10")

    return blockers


def _audit_crosswalk_blockers(path: Path) -> list[str]:
    if not path.exists():
        return ["AUDIT_CROSSWALK_MISSING"]
    data = _load_json(path)
    if not data:
        return ["AUDIT_CROSSWALK_UNREADABLE"]
    if data.get("live_ready_by_audit_crosswalk") is not True:
        return ["AUDIT_CROSSWALK_BLOCK"]
    if data.get("open_high_or_critical"):
        return ["AUDIT_CROSSWALK_OPEN_HIGH_OR_CRITICAL"]
    return []


def _oos_lockbox_blockers(path: Path) -> list[str]:
    if not path.exists():
        return ["OOS_LOCKBOX_MISSING"]
    data = _load_json(path)
    if not data:
        return ["OOS_LOCKBOX_UNREADABLE"]
    if data.get("live_ready_by_oos_lockbox") is not True:
        return ["OOS_LOCKBOX_BLOCK"]
    if data.get("decision") != "OOS_CANDIDATE":
        return ["OOS_LOCKBOX_NOT_CANDIDATE"]
    return []


def evaluate_project_live_gate(
    evidence_path: Path = DEFAULT_EVIDENCE_PATH,
    *,
    sovereign_path: Path = DEFAULT_SOVEREIGN_VERDICT_PATH,
    audit_crosswalk_path: Path = DEFAULT_AUDIT_CROSSWALK_PATH,
    oos_lockbox_path: Path = DEFAULT_OOS_LOCKBOX_PATH,
    now_ts: float | None = None,
    sovereign_ttl_days: float = SOVEREIGN_TTL_DAYS,
) -> ProjectGateResult:
    """Return whether any real Pre-Gain order may pass the project gate.

    The gate is intentionally fail-closed:
    - missing or malformed evidence blocks live;
    - aggregate-only positive edge is not enough;
    - both granular and execution simulation must confirm;
    - the latest sovereign verdict must be fresh GO_LIVE_MICRO with 10/10 gates;
    - audit crosswalk and out-of-sample lockbox must be live-ready;
    - a human/manual tiny-pilot policy marker must be present.
    """
    data = _load_json(evidence_path)
    if not data:
        return ProjectGateResult(
            allowed=False,
            verdict="BLOCK",
            reason="project evidence missing or unreadable",
            blockers=["MISSING_EVIDENCE"],
            evidence_path=str(evidence_path),
            sovereign_path=str(sovereign_path),
            audit_crosswalk_path=str(audit_crosswalk_path),
            oos_lockbox_path=str(oos_lockbox_path),
        )

    blockers: list[str] = []
    decision = str(data.get("decision") or "")
    if decision not in LIVE_READY_DECISIONS:
        blockers.append("DECISION_NOT_LIVE_READY")

    granular = data.get("granular_cross_check") or {}
    if granular.get("verdict") != "CONFIRMS":
        blockers.append("GRANULAR_NOT_CONFIRMED")

    execution = data.get("execution_simulation_cross_check") or {}
    if execution.get("verdict") != "CONFIRMS":
        blockers.append("EXECUTION_NOT_CONFIRMED")

    policy = data.get("hard_policy") or {}
    if policy.get("tiny_live_pilot") != MANUAL_PILOT_POLICY:
        blockers.append("MANUAL_PILOT_NOT_APPROVED")
    if policy.get("allowed_research_route") != PRIMARY_ROUTE:
        blockers.append("PRIMARY_ROUTE_NOT_LOCKED")

    blockers.extend(_sovereign_blockers(
        sovereign_path,
        now_ts=now_ts if now_ts is not None else time.time(),
        ttl_days=sovereign_ttl_days,
    ))
    blockers.extend(_audit_crosswalk_blockers(audit_crosswalk_path))
    blockers.extend(_oos_lockbox_blockers(oos_lockbox_path))

    if blockers:
        return ProjectGateResult(
            allowed=False,
            verdict="BLOCK",
            reason=f"project evidence gate blocks live: {', '.join(blockers)}",
            blockers=blockers,
            evidence_path=str(evidence_path),
            sovereign_path=str(sovereign_path),
            audit_crosswalk_path=str(audit_crosswalk_path),
            oos_lockbox_path=str(oos_lockbox_path),
        )

    return ProjectGateResult(
        allowed=True,
        verdict="ALLOW_TINY_PILOT",
        reason="project evidence confirms manually approved tiny pilot",
        blockers=[],
        evidence_path=str(evidence_path),
        sovereign_path=str(sovereign_path),
        audit_crosswalk_path=str(audit_crosswalk_path),
        oos_lockbox_path=str(oos_lockbox_path),
    )
