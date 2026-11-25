#!/usr/bin/env python3
"""
SoDEX autonomous research runner.

Read-only 24/7 loop for data collection, Pre-Gain/Pre-Loser scanning, and
target-readiness monitoring. This script never places live orders.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from anantara.sodex_event_shock_guard import enrich_event_route_policy, fetch_event_risk  # noqa: E402
from anantara.sodex_pregain_scanner import scan  # noqa: E402
from anantara.sodex_state_io import atomic_write_json  # noqa: E402


DATA_DIR = PROJECT_DIR / "data" / "sodex" / "research"
LOG_FILE = DATA_DIR / "autonomous_research.jsonl"
STATUS_FILE = DATA_DIR / "autonomous_status.json"
LEARNING_FILE = DATA_DIR / "autonomous_learning.json"
DEFAULT_INTERVAL_S = int(os.environ.get("SODEX_RESEARCH_INTERVAL_S", "1800"))
MIN_OUTCOME_AGE_S = int(os.environ.get("SODEX_RESEARCH_MIN_OUTCOME_AGE_S", "1500"))
MAX_LEARNING_ROWS = int(os.environ.get("SODEX_RESEARCH_MAX_LEARNING_ROWS", "1000"))
STATUS_CANDIDATE_LIMIT = int(os.environ.get("SODEX_RESEARCH_STATUS_CANDIDATES", "10"))
POLICY_MIN_SAMPLES = int(os.environ.get("SODEX_POLICY_MIN_SAMPLES", "20"))
POLICY_TARGET_WIN_RATE = float(os.environ.get("SODEX_POLICY_TARGET_WIN_RATE", "0.69"))
POLICY_MIN_EDGE_PCT = float(os.environ.get("SODEX_POLICY_MIN_EDGE_PCT", "0.05"))
LIVE_ROUTE = os.environ.get("SODEX_LIVE_ROUTE", "SPOT_LONG")
SOSO_SYMBOL = os.environ.get("SODEX_SOSO_SYMBOL", "WSOSO_vUSDC")
SOSO_MIN_EVENT_SCORE = int(os.environ.get("SODEX_SOSO_EVENT_MIN_SCORE", "60"))
SOSO_MAX_EVENT_SPREAD_PCT = float(os.environ.get("SODEX_SOSO_EVENT_MAX_SPREAD_PCT", "0.12"))
SOSO_MIN_EVENT_VOL_USD = float(os.environ.get("SODEX_SOSO_EVENT_MIN_VOL_USD", "1000000"))


def _score_band(score: int | float | None) -> str:
    try:
        s = int(score or 0)
    except (TypeError, ValueError):
        s = 0
    if s >= 60:
        return "trade_60_plus"
    if s >= 40:
        return "watch_40_59"
    if s >= 20:
        return "radar_20_39"
    return "radar_01_19"


def _horizon_bucket(age_s: float) -> str:
    if age_s < 5 * 60:
        return "h01_04m"
    if age_s < 15 * 60:
        return "h05_14m"
    if age_s < 30 * 60:
        return "h15_29m"
    if age_s < 60 * 60:
        return "h30_59m"
    if age_s < 4 * 60 * 60:
        return "h01_04h"
    return "h04h_plus"


def _write_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def _atomic_write_json(path: Path, payload: dict) -> None:
    atomic_write_json(path, payload)


def _write_status(status: dict) -> None:
    _atomic_write_json(STATUS_FILE, status)


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _recent_rows(path: Path, limit: int = MAX_LEARNING_ROWS) -> list[dict]:
    if not path.exists():
        return []
    rows: deque[dict] = deque(maxlen=limit)
    try:
        with path.open() as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        rows.append(row)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return list(rows)


def _iter_candidates(row: dict):
    for bucket in (
        "top_longs", "top_shorts",
        "watchlist_longs", "watchlist_shorts",
        "radar_longs", "radar_shorts",
    ):
        for candidate in row.get(bucket, []) or []:
            if isinstance(candidate, dict):
                yield bucket, candidate


def _learning_report(current_row: dict) -> dict:
    """Evaluate earlier signals against the current price snapshot."""
    now_ts = _parse_ts(str(current_row.get("ts", "")))
    current_prices = {
        (a.get("market"), a.get("symbol")): float(a.get("mark") or 0.0)
        for a in current_row.get("observed_assets", []) or []
        if isinstance(a, dict) and a.get("market") and a.get("symbol")
    }
    if not now_ts or not current_prices:
        return {"status": "NO_SNAPSHOT", "outcomes": 0}

    outcomes = []
    for old in _recent_rows(LOG_FILE):
        old_ts = _parse_ts(str(old.get("ts", "")))
        if not old_ts:
            continue
        age_s = (now_ts - old_ts).total_seconds()
        if age_s < MIN_OUTCOME_AGE_S:
            continue
        for bucket, candidate in _iter_candidates(old):
            key = (candidate.get("market"), candidate.get("symbol"))
            old_mark = float(candidate.get("mark") or 0.0)
            now_mark = current_prices.get(key, 0.0)
            if old_mark <= 0 or now_mark <= 0:
                continue
            direction = candidate.get("direction", "LONG")
            reasons = candidate.get("reasons", []) or []
            catalyst_tags = []
            if any(str(r).startswith("SOSO_EXP_") for r in reasons):
                catalyst_tags.append("SOSO_EXP")
            raw_ret = (now_mark - old_mark) / old_mark * 100.0
            edge_ret = raw_ret if direction == "LONG" else -raw_ret
            outcomes.append({
                "age_min": round(age_s / 60.0, 1),
                "horizon": _horizon_bucket(age_s),
                "bucket": bucket,
                "symbol": candidate.get("symbol"),
                "market": candidate.get("market"),
                "route": candidate.get("route"),
                "direction": direction,
                "score": candidate.get("score"),
                "score_band": _score_band(candidate.get("score")),
                "reasons": reasons,
                "catalyst_tags": catalyst_tags,
                "entry_mark": old_mark,
                "now_mark": now_mark,
                "edge_return_pct": round(edge_ret, 4),
                "raw_return_pct": round(raw_ret, 4),
                "win": edge_ret > 0,
            })

    groups: dict[str, list[dict]] = defaultdict(list)
    for outcome in outcomes:
        groups[
            f"{outcome['horizon']}:{outcome['score_band']}:{outcome['bucket']}:{outcome['route']}"
        ].append(outcome)

    summary = {}
    for key, items in sorted(groups.items()):
        wins = sum(1 for x in items if x["win"])
        avg_ret = sum(x["edge_return_pct"] for x in items) / len(items)
        summary[key] = {
            "n": len(items),
            "win_rate": round(wins / len(items), 4),
            "avg_edge_return_pct": round(avg_ret, 4),
        }

    symbol_groups: dict[str, list[dict]] = defaultdict(list)
    for outcome in outcomes:
        symbol_groups[str(outcome.get("symbol") or "UNKNOWN")].append(outcome)
    symbol_summary = {}
    for symbol, items in sorted(symbol_groups.items()):
        wins = sum(1 for x in items if x["win"])
        avg_ret = sum(x["edge_return_pct"] for x in items) / len(items)
        symbol_summary[symbol] = {
            "n": len(items),
            "win_rate": round(wins / len(items), 4),
            "avg_edge_return_pct": round(avg_ret, 4),
            "best_edge_return_pct": round(max(x["edge_return_pct"] for x in items), 4),
            "worst_edge_return_pct": round(min(x["edge_return_pct"] for x in items), 4),
            "horizons": sorted({x["horizon"] for x in items}),
        }

    catalyst_groups: dict[str, list[dict]] = defaultdict(list)
    for outcome in outcomes:
        for tag in outcome.get("catalyst_tags", []) or []:
            catalyst_groups[f"{outcome.get('symbol')}:{tag}"].append(outcome)
    catalyst_summary = {}
    for key, items in sorted(catalyst_groups.items()):
        wins = sum(1 for x in items if x["win"])
        avg_ret = sum(x["edge_return_pct"] for x in items) / len(items)
        catalyst_summary[key] = {
            "n": len(items),
            "win_rate": round(wins / len(items), 4),
            "avg_edge_return_pct": round(avg_ret, 4),
            "best_edge_return_pct": round(max(x["edge_return_pct"] for x in items), 4),
            "worst_edge_return_pct": round(min(x["edge_return_pct"] for x in items), 4),
            "horizons": sorted({x["horizon"] for x in items}),
        }
    soso_exp_key = f"{SOSO_SYMBOL}:SOSO_EXP"

    report = {
        "status": "OK",
        "ts": current_row.get("ts"),
        "min_outcome_age_s": MIN_OUTCOME_AGE_S,
        "outcomes": len(outcomes),
        "summary": summary,
        "symbol_summary": symbol_summary,
        "soso_symbol_summary": symbol_summary.get(SOSO_SYMBOL, {"n": 0}),
        "catalyst_summary": catalyst_summary,
        "soso_exp_summary": catalyst_summary.get(soso_exp_key, {"n": 0}),
        "recent_outcomes": outcomes[-50:],
    }
    _atomic_write_json(LEARNING_FILE, report)
    return report


def _adaptive_policy(learning: dict, event_risk: dict) -> dict:
    """Convert shadow outcomes into read-only route guidance."""
    summary = learning.get("summary", {}) if isinstance(learning, dict) else {}
    promote = []
    watch = []
    block = []
    for key, stats in summary.items():
        if not isinstance(stats, dict):
            continue
        parts = key.split(":")
        route = parts[-1] if parts else "UNKNOWN"
        direction = "SHORT" if "short" in key.lower() or route.endswith("SHORT") else "LONG"
        n = int(stats.get("n") or 0)
        win_rate = float(stats.get("win_rate") or 0.0)
        avg_edge = float(stats.get("avg_edge_return_pct") or 0.0)
        item = {
            "cohort": key,
            "route": route,
            "direction": direction,
            "n": n,
            "win_rate": round(win_rate, 4),
            "avg_edge_return_pct": round(avg_edge, 4),
        }
        if n >= POLICY_MIN_SAMPLES and win_rate >= POLICY_TARGET_WIN_RATE and avg_edge >= POLICY_MIN_EDGE_PCT:
            promote.append(item)
        elif n >= POLICY_MIN_SAMPLES and (win_rate < 0.5 or avg_edge <= 0):
            block.append(item)
        elif avg_edge > 0 and win_rate >= 0.55:
            watch.append(item)

    promote.sort(key=lambda x: (x["win_rate"], x["avg_edge_return_pct"], x["n"]), reverse=True)
    watch.sort(key=lambda x: (x["win_rate"], x["avg_edge_return_pct"], x["n"]), reverse=True)
    block.sort(key=lambda x: (x["n"], -x["win_rate"], -x["avg_edge_return_pct"]), reverse=True)
    live_gate = event_risk.get("live_gate")
    route_policy = event_risk.get("route_policy", {}) if isinstance(event_risk, dict) else {}
    event_opportunity_routes = route_policy.get("opportunity_routes", []) if isinstance(route_policy, dict) else []
    event_opportunity_bias = route_policy.get("opportunity_bias", "UNKNOWN") if isinstance(route_policy, dict) else "UNKNOWN"
    route_gates = route_policy.get("route_gates", {}) if isinstance(route_policy, dict) else {}
    route_opportunity_state = []
    for route, gate in sorted(route_gates.items()):
        aligned_promote = [item for item in promote if item["route"] == route]
        aligned_watch = [item for item in watch if item["route"] == route]
        aligned_block = [item for item in block if item["route"] == route]
        if gate in {"ALLOW_LIVE", "ALLOW_REDUCED_LIVE"} and aligned_promote:
            action = "LIVE_CANDIDATE"
            reason = f"gate={gate}; promoted edge"
        elif gate == "RESEARCH_ONLY" and route in event_opportunity_routes:
            action = "RESEARCH_OPPORTUNITY"
            reason = "event-aligned opportunity; keep measuring before live"
        elif gate == "PAPER_ONLY":
            action = "PAPER_ONLY"
            reason = "uncertain event direction; paper route only"
        elif gate == "BLOCK_LIVE":
            action = "BLOCK_LIVE"
            reason = "route unsafe under current event policy"
        elif aligned_watch:
            action = "WATCH"
            reason = "positive early edge; needs more evidence"
        elif aligned_block:
            action = "BLOCK_ROUTE"
            reason = "negative observed edge"
        else:
            action = "MONITOR"
            reason = f"gate={gate or 'UNKNOWN'}; no promoted cohort"
        route_opportunity_state.append({
            "route": route,
            "gate": gate,
            "action": action,
            "event_aligned": route in event_opportunity_routes,
            "promoted": bool(aligned_promote),
            "watch": bool(aligned_watch),
            "blocked": action in {"BLOCK_LIVE", "BLOCK_ROUTE"},
            "promoted_cohort_count": len(aligned_promote),
            "watch_cohort_count": len(aligned_watch),
            "blocked_cohort_count": len(aligned_block),
            "reason": reason,
        })
    live_promote = [item for item in promote if item["route"] == LIVE_ROUTE]
    live_block = [item for item in block if item["route"] == LIVE_ROUTE]
    if live_gate == "BLOCK_LIVE":
        live_route_decision = "BLOCKED_BY_EVENT_RISK"
        live_route_reason = "external_live_gate=BLOCK_LIVE"
    elif live_promote:
        live_route_decision = "ALLOW_ROUTE"
        live_route_reason = (
            f"promoted wr={live_promote[0]['win_rate']} "
            f"edge={live_promote[0]['avg_edge_return_pct']}"
        )
    elif live_block:
        live_route_decision = "BLOCK_ROUTE"
        live_route_reason = (
            f"blocked wr={live_block[0]['win_rate']} "
            f"edge={live_block[0]['avg_edge_return_pct']}"
        )
    else:
        live_route_decision = "NO_ROUTE_PROMOTION"
        live_route_reason = "no promoted cohort for live route"
    if live_gate == "BLOCK_LIVE" and event_opportunity_routes:
        status = "RISK_EVENT_ROUTE_LIMITED"
    elif live_gate == "BLOCK_LIVE":
        status = "BLOCKED_BY_EVENT_RISK"
    else:
        status = "READY_FOR_PAPER_SELECTION"

    return {
        "status": status,
        "target_win_rate": POLICY_TARGET_WIN_RATE,
        "min_samples": POLICY_MIN_SAMPLES,
        "min_edge_pct": POLICY_MIN_EDGE_PCT,
        "external_live_gate": live_gate,
        "event_opportunity_bias": event_opportunity_bias,
        "event_opportunity_routes": event_opportunity_routes,
        "event_route_policy": route_policy,
        "route_opportunity_state": route_opportunity_state,
        "live_route": LIVE_ROUTE,
        "live_route_decision": live_route_decision,
        "live_route_reason": live_route_reason,
        "promote_count": len(promote),
        "watch_count": len(watch),
        "block_count": len(block),
        "promote": promote[:STATUS_CANDIDATE_LIMIT],
        "watch": watch[:STATUS_CANDIDATE_LIMIT],
        "block": block[:STATUS_CANDIDATE_LIMIT],
    }


def _learning_strength(learning: dict, policy: dict, errors: list[str]) -> dict:
    """Summarize autonomous continuous learning health and next action."""
    learning = learning if isinstance(learning, dict) else {}
    policy = policy if isinstance(policy, dict) else {}
    errors = errors or []
    outcomes = int(learning.get("outcomes") or 0)
    promote = [x for x in policy.get("promote", []) or [] if isinstance(x, dict)]
    watch = [x for x in policy.get("watch", []) or [] if isinstance(x, dict)]
    block = [x for x in policy.get("block", []) or [] if isinstance(x, dict)]
    event_routes = set(policy.get("event_opportunity_routes", []) or [])
    opportunity_alignment = sorted({
        item.get("route") for item in promote + watch
        if item.get("route") in event_routes
    })
    aligned_candidates = [
        item for item in promote + watch
        if item.get("route") in event_routes
    ]
    best = aligned_candidates[0] if aligned_candidates else (promote[0] if promote else (watch[0] if watch else {}))
    best_route = best.get("route")
    best_win_rate = float(best.get("win_rate") or 0.0)
    best_edge = float(best.get("avg_edge_return_pct") or 0.0)

    score = 0
    next_actions: list[str] = []
    if not errors and learning.get("status") == "OK":
        score += 20
    else:
        next_actions.append("restore_data_feed")
    if outcomes >= POLICY_MIN_SAMPLES:
        score += min(25, int(outcomes / max(POLICY_MIN_SAMPLES, 1) * 5))
    else:
        next_actions.append("collect_more_shadow_outcomes")
    if promote:
        score += 25
    elif watch:
        score += 12
        next_actions.append("continue_watchlist_validation")
    else:
        next_actions.append("search_new_cohorts")
    if best_win_rate >= POLICY_TARGET_WIN_RATE and best_edge >= POLICY_MIN_EDGE_PCT:
        score += 20
    if opportunity_alignment:
        score += 10
        if aligned_candidates:
            next_actions.append("prioritize_event_aligned_route")
    elif event_routes:
        next_actions.append("align_promoted_routes_with_event_opportunity")
    if block:
        score += 5

    score = min(100, score)
    if errors or learning.get("status") in {"NO_SNAPSHOT", "PARTIAL"}:
        status = "LEARNING_DATA_GAP"
    elif score >= 80 and promote:
        status = "STRONG_LEARNING_ACTIVE"
    elif score >= 55:
        status = "LEARNING_ACTIVE"
    else:
        status = "LEARNING_WARMUP"

    if not next_actions:
        next_actions = ["continue_shadow_learning", "protect_promoted_cohorts", "monitor_drift"]

    return {
        "status": status,
        "score": score,
        "outcomes": outcomes,
        "promote_count": len(promote),
        "watch_count": len(watch),
        "block_count": len(block),
        "best_route": best_route,
        "best_direction": best.get("direction"),
        "best_win_rate": round(best_win_rate, 4),
        "best_edge_return_pct": round(best_edge, 4),
        "opportunity_alignment": opportunity_alignment,
        "next_actions": next_actions,
    }


def _soso_event_playbook(result: dict, event_risk: dict, policy: dict) -> dict:
    """Read-only execution readiness for the SoSoValue EXP catalyst."""
    catalyst = (result.get("catalysts", {}) or {}).get("soso_exp", {}) or {}
    candidates = []
    for bucket in ("top_longs", "watchlist_longs", "radar_longs"):
        for candidate in result.get(bucket, []) or []:
            if isinstance(candidate, dict) and candidate.get("symbol") == SOSO_SYMBOL:
                item = dict(candidate)
                item["bucket"] = bucket
                candidates.append(item)
    candidate = candidates[0] if candidates else {}
    spread = float(candidate.get("spread_pct") or 999.0)
    score = int(candidate.get("score") or 0)
    vol24 = float(candidate.get("vol24") or 0.0)
    phase = catalyst.get("phase", "INACTIVE")
    gate = event_risk.get("live_gate")
    risk_level = event_risk.get("level")

    blockers = []
    if not catalyst.get("active"):
        blockers.append("CATALYST_INACTIVE")
    if not candidate:
        blockers.append("SOSO_NOT_IN_SCAN")
    if score < SOSO_MIN_EVENT_SCORE:
        blockers.append(f"SCORE_BELOW_{SOSO_MIN_EVENT_SCORE}")
    if spread > SOSO_MAX_EVENT_SPREAD_PCT:
        blockers.append(f"SPREAD_ABOVE_{SOSO_MAX_EVENT_SPREAD_PCT}")
    if vol24 < SOSO_MIN_EVENT_VOL_USD:
        blockers.append(f"VOL_BELOW_{int(SOSO_MIN_EVENT_VOL_USD)}")
    if gate == "BLOCK_LIVE":
        blockers.append("EVENT_RISK_BLOCK_LIVE")
    if phase == "POST_EVENT_DISTRIBUTION":
        blockers.append("POST_EVENT_SELL_THE_NEWS_RISK")
    if policy.get("live_route_decision") in {"BLOCK_ROUTE", "NO_ROUTE_PROMOTION"}:
        blockers.append(f"POLICY_{policy.get('live_route_decision')}")

    if blockers:
        decision = "MONITOR_ONLY"
    elif phase == "PRE_EVENT":
        decision = "READY_WHEN_LIVE_GATE_ALLOWS"
    else:
        decision = "NO_ACTION"

    return {
        "symbol": SOSO_SYMBOL,
        "decision": decision,
        "phase": phase,
        "hours_until": catalyst.get("hours_until"),
        "event_ts": catalyst.get("event_ts"),
        "candidate": candidate,
        "score_min": SOSO_MIN_EVENT_SCORE,
        "max_spread_pct": SOSO_MAX_EVENT_SPREAD_PCT,
        "min_vol24_usd": SOSO_MIN_EVENT_VOL_USD,
        "event_risk_level": risk_level,
        "external_live_gate": gate,
        "blockers": blockers,
        "playbook": [
            "pre_event: monitor WSOSO spot long momentum and liquidity",
            "live_allowed: only small spot directional entry, not spread farming",
            "post_event: treat as distribution/sell-the-news risk unless price confirms",
        ],
    }


def _soso_learning_decision(learning: dict) -> dict:
    """Small-sample aware SOSO learning state for the active event."""
    exp_stats = (learning or {}).get("soso_exp_summary", {}) or {}
    symbol_stats = (learning or {}).get("soso_symbol_summary", {}) or {}
    stats = exp_stats if int(exp_stats.get("n") or 0) > 0 else symbol_stats
    scope = "SOSO_EXP" if int(exp_stats.get("n") or 0) > 0 else "SYMBOL_ALL"
    n = int(stats.get("n") or 0)
    win_rate = float(stats.get("win_rate") or 0.0)
    avg_edge = float(stats.get("avg_edge_return_pct") or 0.0)
    if n < POLICY_MIN_SAMPLES:
        decision = "LEARN_MORE"
        reason = f"soso_samples={n}<{POLICY_MIN_SAMPLES}"
    elif win_rate >= POLICY_TARGET_WIN_RATE and avg_edge >= POLICY_MIN_EDGE_PCT:
        decision = "PROMOTE_SYMBOL_EDGE"
        reason = f"wr={win_rate} edge={avg_edge}"
    elif win_rate < 0.5 or avg_edge <= 0:
        decision = "BLOCK_SYMBOL_EDGE"
        reason = f"wr={win_rate} edge={avg_edge}"
    else:
        decision = "WATCH_SYMBOL_EDGE"
        reason = f"wr={win_rate} edge={avg_edge}"
    return {
        "symbol": SOSO_SYMBOL,
        "scope": scope,
        "decision": decision,
        "reason": reason,
        "stats": stats,
    }


def run_once(min_score: int, top_n: int) -> dict:
    started = time.time()
    result = scan(min_score=min_score, top_n=top_n, include_assets=True)
    event_risk = enrich_event_route_policy(fetch_event_risk())
    now = datetime.now(timezone.utc).isoformat()
    top_longs = result.get("top_longs", [])
    top_shorts = result.get("top_shorts", [])
    watch_longs = result.get("watchlist_longs", [])
    watch_shorts = result.get("watchlist_shorts", [])
    radar_longs = result.get("radar_longs", [])
    radar_shorts = result.get("radar_shorts", [])
    parallel_candidates = sorted(
        top_longs + top_shorts + watch_longs + watch_shorts + radar_longs + radar_shorts,
        key=lambda c: (int(c.get("score") or 0), float(c.get("vol24") or 0.0)),
        reverse=True,
    )
    row = {
        "ts": now,
        "status": result.get("status"),
        "duration_s": round(time.time() - started, 3),
        "universe": result.get("universe", {}),
        "macro": result.get("macro", {}),
        "event_risk": event_risk,
        "top_longs": top_longs,
        "top_shorts": top_shorts,
        "watchlist_longs": watch_longs,
        "watchlist_shorts": watch_shorts,
        "radar_longs": radar_longs,
        "radar_shorts": radar_shorts,
        "diagnostics": result.get("diagnostics", {}),
        "catalysts": result.get("catalysts", {}),
        "observed_assets": result.get("observed_assets", []),
        "errors": result.get("errors", []),
    }
    learning = _learning_report(row)
    policy = _adaptive_policy(learning, event_risk)
    learning_strength = _learning_strength(learning, policy, result.get("errors", []))
    soso_playbook = _soso_event_playbook(result, event_risk, policy)
    soso_learning = _soso_learning_decision(learning)
    row["learning"] = {
        "status": learning.get("status"),
        "outcomes": learning.get("outcomes", 0),
        "summary": learning.get("summary", {}),
        "symbol_summary": learning.get("symbol_summary", {}),
        "soso_symbol_summary": learning.get("soso_symbol_summary", {}),
        "catalyst_summary": learning.get("catalyst_summary", {}),
        "soso_exp_summary": learning.get("soso_exp_summary", {}),
    }
    row["adaptive_policy"] = policy
    row["learning_strength"] = learning_strength
    row["soso_event_playbook"] = soso_playbook
    row["soso_learning_decision"] = soso_learning
    _write_jsonl(LOG_FILE, row)
    _write_status({
        "ts": now,
        "mode": "READ_ONLY_RESEARCH",
        "last_status": result.get("status"),
        "last_duration_s": row["duration_s"],
        "research_interval_s": DEFAULT_INTERVAL_S,
        "min_outcome_age_s": MIN_OUTCOME_AGE_S,
        "research_mode": "ACCELERATED_SHADOW_MONITORING",
        "universe": result.get("universe", {}),
        "top_long_count": len(top_longs),
        "top_short_count": len(top_shorts),
        "watch_long_count": len(watch_longs),
        "watch_short_count": len(watch_shorts),
        "radar_long_count": len(radar_longs),
        "radar_short_count": len(radar_shorts),
        "parallel_candidate_count": min(STATUS_CANDIDATE_LIMIT, len(parallel_candidates)),
        "parallel_candidates": parallel_candidates[:STATUS_CANDIDATE_LIMIT],
        "top_longs": top_longs[:STATUS_CANDIDATE_LIMIT],
        "top_shorts": top_shorts[:STATUS_CANDIDATE_LIMIT],
        "watchlist_longs": watch_longs[:STATUS_CANDIDATE_LIMIT],
        "watchlist_shorts": watch_shorts[:STATUS_CANDIDATE_LIMIT],
        "radar_longs": radar_longs[:STATUS_CANDIDATE_LIMIT],
        "radar_shorts": radar_shorts[:STATUS_CANDIDATE_LIMIT],
        "diagnostics": result.get("diagnostics", {}),
        "catalysts": result.get("catalysts", {}),
        "learning": row["learning"],
        "adaptive_policy": policy,
        "learning_strength": learning_strength,
        "soso_event_playbook": soso_playbook,
        "soso_learning_decision": soso_learning,
        "learning_file": str(LEARNING_FILE),
        "macro": result.get("macro", {}),
        "event_risk": event_risk,
        "external_live_gate": event_risk.get("live_gate"),
        "errors": result.get("errors", []),
        "log_file": str(LOG_FILE),
    })
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="SoDEX autonomous read-only research")
    parser.add_argument("--loop", action="store_true", help="Run forever")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_S)
    parser.add_argument("--min-score", type=int, default=60)
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    print("SoDEX autonomous research — READ ONLY")
    print(f"data={DATA_DIR} interval={args.interval}s min_score={args.min_score}")

    while True:
        try:
            row = run_once(args.min_score, args.top)
            print(json.dumps({
                "ts": row["ts"],
                "status": row["status"],
                "universe": row["universe"],
                "longs": len(row["top_longs"]),
                "shorts": len(row["top_shorts"]),
                "watch_longs": len(row["watchlist_longs"]),
                "watch_shorts": len(row["watchlist_shorts"]),
                "radar_longs": len(row["radar_longs"]),
                "radar_shorts": len(row["radar_shorts"]),
                "learning_strength": row.get("learning_strength", {}).get("status"),
                "errors": row["errors"],
            }, sort_keys=True))
        except Exception as exc:
            err = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "status": "ERROR",
                "error": str(exc)[:300],
            }
            _write_jsonl(LOG_FILE, err)
            _write_status(err)
            print(json.dumps(err, sort_keys=True), file=sys.stderr)

        if not args.loop:
            break
        time.sleep(max(60, args.interval))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
