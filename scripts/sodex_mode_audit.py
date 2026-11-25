#!/usr/bin/env python3
"""SoDEX mode audit and combination selector.

Read-only. Converts the many existing SoDEX modes into one repeatable decision
matrix, then selects the best current method combination for the 25 July event.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

MONITOR_LATEST = PROJECT / "data" / "sodex_monitor_eval" / "latest.json"


@dataclass(frozen=True)
class ModeSpec:
    name: str
    lane: str
    role: str
    source: str
    impact: str
    risk: str
    current_use: str
    verdict: str


MODE_CATALOG: tuple[ModeSpec, ...] = (
    ModeSpec(
        "E1_SPOT_FLYWHEEL",
        "spot",
        "profit subsidy",
        "anantara/sodex_twin_engine.py E1",
        "Can cover fees if spread capture is positive.",
        "Inventory depreciation and forced flush losses.",
        "blocked/degraded by low weekly win-rate and coverage gap",
        "KEEP_FOR_PROFIT_ONLY_NOT_VOLUME_CHURN",
    ),
    ModeSpec(
        "MODE4_STATIC_SPREAD_GATE",
        "perps",
        "simple maker baseline",
        "docs/MODE_4_5_SCIENTIFIC.md",
        "High volume/cost efficiency when spreads behave.",
        "Ceiling below target without E1 subsidy.",
        "research baseline",
        "BASELINE_ONLY",
    ),
    ModeSpec(
        "MODE5_OBI_DYNAMIC_GATE",
        "perps",
        "adaptive maker",
        "anantara/sodex_farming.py:mode5_round",
        "Tighter spread selection than static gates.",
        "Maker fill uncertainty and stale-book risk.",
        "research/paper unless route gates recover",
        "PAPER_OR_GATED",
    ),
    ModeSpec(
        "MODE6_HYBRID_MM",
        "perps",
        "dual-side maker",
        "anantara/sodex_farming.py:mode6_round",
        "Can capture both sides when market oscillates.",
        "One-sided fill creates directional exposure.",
        "not current live lane",
        "RESEARCH_ONLY",
    ),
    ModeSpec(
        "MODE7_INTEL_MAKER",
        "perps",
        "intelligence-aware maker",
        "anantara/sodex_farming.py:mode7_round",
        "Combines quality score, sentiment, time gate, and smart pricing.",
        "Complex path; needs fresh OBI/intel and fill-rate proof.",
        "candidate research lane",
        "PAPER_FIRST",
    ),
    ModeSpec(
        "MODE8_DELTA_NEUTRAL_MAKER",
        "perps",
        "delta-neutral volume",
        "anantara/sodex_farming.py:mode8_dn_cycle",
        "Potentially high volume with limited net delta.",
        "Dual-leg failure leaves exposure; needs robust re-quote and close.",
        "not allowed while open-position/coverage blockers exist",
        "AFTER_GATE_ONLY",
    ),
    ModeSpec(
        "MODE10_DSSC",
        "perps",
        "dual-side spread capture",
        "anantara/sodex_farming.py:mode10_dssc_round",
        "Best maker-combo research path for wide spreads.",
        "Partial fills and force-close cost.",
        "paper/liquidity research",
        "PAPER_FIRST",
    ),
    ModeSpec(
        "E2_CHURN_MAKER",
        "perps",
        "legacy volume churn",
        "anantara/sodex_twin_engine.py:E2",
        "Volume generation if fills work.",
        "Documented dead-end: stale book, oid=0, ghost risk.",
        "disabled",
        "REJECT",
    ),
    ModeSpec(
        "E2DIR_FUNDING_OBI",
        "perps",
        "directional amplifier",
        "anantara/sodex_twin_engine.py:Engine2Directional",
        "Only documented positive-edge seed: funding squeeze plus OBI.",
        "Needs WR/position recovery gates before scale.",
        "paper/live gated by TE_E2_DIR_* and policy",
        "BEST_AMPLIFIER_AFTER_GATE",
    ),
    ModeSpec(
        "E2_MOMENTUM_OFI_PAPER",
        "perps",
        "signal research",
        "anantara/sodex_twin_engine.py:scan_momentum_paper",
        "Fast signal discovery across liquid perps.",
        "Continuations were falsified; reversal must remain paper until proven.",
        "paper only",
        "PAPER_ONLY",
    ),
    ModeSpec(
        "PREGain_TOP_LOSER_BRIDGE",
        "perps",
        "bear-market directional discovery",
        "anantara/sodex_twin_engine.py:feed_pregain_signals",
        "Maps Pre-Loser candidates into SHORT queue during BEAR.",
        "Requires freshness and no-open-position gate.",
        "partly implemented via micro-pilot",
        "COMBINE_WITH_E2DIR",
    ),
    ModeSpec(
        "PVE_SPCX",
        "perps",
        "small volume experiment",
        "anantara/perps_volume_engine.py",
        "Had small positive PnL in status report.",
        "Single-pair concentration and limited capacity.",
        "not primary now",
        "SECONDARY_RESEARCH",
    ),
    ModeSpec(
        "MICRO_PRE_LOSER_SHORT",
        "perps",
        "live edge probe",
        "scripts/sodex_micro_pilot.py",
        "Safe tiny BEAR-market live probe with reduce-only close.",
        "Too small to meet event target alone.",
        "active under operator override and loss cap",
        "LIVE_MICRO_ONLY",
    ),
)


def _target_policy(report: dict[str, Any]) -> dict[str, Any]:
    from scripts.sodex_target_policy import evaluate_target_policy

    return evaluate_target_policy(report)


def _runway(report: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    from scripts.sodex_event_runway import evaluate_runway

    return evaluate_runway(report, policy)


def select_combination(policy: dict[str, Any], runway: dict[str, Any]) -> dict[str, Any]:
    blockers = set(policy.get("blockers") or [])
    micro = runway.get("micro") or {}
    phase = runway.get("phase")
    combo = {
        "name": "EVENT_BARBELL_V1",
        "thesis": (
            "Use E1 only for profit subsidy, use micro Pre-Loser SHORT as live edge probe, "
            "promote E2Dir funding+OBI+Pre-Loser as the volume amplifier only after gates clear."
        ),
        "live_now": [],
        "paper_now": ["MODE10_DSSC", "MODE7_INTEL_MAKER", "E2_MOMENTUM_OFI_PAPER"],
        "rejected_now": ["E2_CHURN_MAKER", "MODE8_DELTA_NEUTRAL_MAKER"],
        "promotion_target": "E2DIR_FUNDING_OBI + PREGain_TOP_LOSER_BRIDGE",
        "why": [],
    }
    if phase == "PHASE_1_MICRO_ONLY" and micro.get("lane_active"):
        combo["live_now"].append("MICRO_PRE_LOSER_SHORT")
        combo["why"].append("Bear regime has a fresh signal and no open perps; micro lane is capped.")
    if {"e1_no_loss_coverage_short", "weekly_win_rate_below_target"}.intersection(blockers):
        combo["why"].append("E2 scale is blocked until E1 coverage/win-rate improves.")
    if "official_dashboard_not_canonical" in blockers:
        combo["why"].append("Official dashboard reconciliation must be solved before volume amplification.")
    combo["impact_assessment"] = {
        "needed_daily_volume_usd": runway.get("needed_daily_volume_usd"),
        "micro_daily_capacity_usd": micro.get("estimated_daily_volume_capacity_usd"),
        "micro_required_cycles_daily": micro.get("required_cycles_daily_for_target"),
        "conclusion": runway.get("verdict"),
    }
    return combo


def evaluate_mode_audit(report: dict[str, Any]) -> dict[str, Any]:
    policy = _target_policy(report)
    runway = _runway(report, policy)
    return {
        "mode_count": len(MODE_CATALOG),
        "modes": [asdict(mode) for mode in MODE_CATALOG],
        "policy": {
            "decision": policy.get("decision"),
            "regime": policy.get("regime"),
            "blockers": policy.get("blockers") or [],
            "opportunity_lanes": policy.get("opportunity_lanes") or [],
        },
        "runway": runway,
        "recommended_combination": select_combination(policy, runway),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only SoDEX mode audit")
    parser.add_argument("--monitor-json", type=Path, default=MONITOR_LATEST)
    args = parser.parse_args(argv)
    report = json.loads(args.monitor_json.read_text())
    print(json.dumps(evaluate_mode_audit(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
