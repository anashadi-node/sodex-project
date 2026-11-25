#!/usr/bin/env python3
"""Fast read-only SoDEX watchlist gate accelerator.

Evaluates every watchlist asset across spread, liquidity, fees, adverse
selection, position truth, loss budget, and policy gate.  It never places,
cancels, signs, or modifies orders.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

MARKET_LATEST = PROJECT / "data" / "sodex_market_scan" / "latest.json"
MONITOR_LATEST = PROJECT / "data" / "sodex_monitor_eval" / "latest.json"
SYSTEM_MAP_LATEST = PROJECT / "data" / "sodex_system_map" / "latest.json"
OUT_DIR = PROJECT / "data" / "sodex_watchlist_gate"
LATEST = OUT_DIR / "latest.json"
DOC = PROJECT / "docs" / "SODEX_WATCHLIST_GATE.md"


def dec(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def age_seconds(path: Path) -> float | None:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def fee_rates_bps(monitor: dict[str, Any]) -> dict[str, float]:
    rate = ((monitor.get("account") or {}).get("fee_rate") or {})
    maker = float(dec(rate.get("makerFeeRate"))) * 10_000.0
    taker = float(dec(rate.get("takerFeeRate"))) * 10_000.0
    return {
        "maker_one_way_bps": maker,
        "taker_one_way_bps": taker,
        "maker_roundtrip_bps": maker * 2.0,
        "taker_roundtrip_bps": taker * 2.0,
    }


def position_truth(monitor: dict[str, Any]) -> dict[str, Any]:
    truth = (((monitor.get("account") or {}).get("position_truth")) or {})
    open_count = int(float(truth.get("open_count") or 0))
    quality = truth.get("quality")
    positions = truth.get("positions") if isinstance(truth.get("positions"), list) else []
    open_symbols = sorted({
        str(p.get("symbol") or "")
        for p in positions
        if isinstance(p, dict) and p.get("symbol")
    })
    blockers: list[str] = []
    if quality != "OK":
        blockers.append("position_truth_unverified")
    if open_count > 0:
        blockers.append("open_perp_positions_present")
    return {
        "quality": quality,
        "open_count": open_count,
        "verified_flat": bool(truth.get("verified_flat", open_count == 0)),
        "open_symbols": open_symbols,
        "blockers": blockers,
        "pass": quality == "OK" and open_count == 0,
    }


def policy_context(monitor: dict[str, Any]) -> dict[str, Any]:
    from scripts.sodex_target_policy import evaluate_target_policy

    policy = evaluate_target_policy(monitor)
    lanes = policy.get("opportunity_lanes") or []
    lane = next((item for item in lanes if item.get("lane") == "MICRO_PRE_LOSER_SHORT_ONLY"), None)
    if lane is None:
        lane = next((item for item in lanes if "SHORT" in str(item.get("lane") or "")), None)
    return {
        "decision": policy.get("decision"),
        "regime": policy.get("regime"),
        "blockers": policy.get("blockers") or [],
        "lane": lane,
        "lane_present": lane is not None,
        "max_notional_usd": float(dec((lane or {}).get("max_notional_usd"))),
        "max_daily_loss_usd": float(dec((lane or {}).get("max_daily_loss_usd"))),
        "raw": policy,
    }


def system_blockers(system_map: dict[str, Any]) -> list[str]:
    blockers = list(system_map.get("blockers") or [])
    subsystems = system_map.get("subsystems") or []
    for sub in subsystems:
        if not isinstance(sub, dict):
            continue
        name = str(sub.get("name") or "")
        status = str(sub.get("status") or "")
        if name in {"market_scan", "monitor_eval", "deep_learning_loop", "policy_and_gates"} and status != "ok":
            blockers.append(f"{name}_{status}")
    return sorted(set(blockers))


def watchlist_items(market: dict[str, Any], *, all_perps: bool = False) -> list[dict[str, Any]]:
    items = [item for item in market.get("items") or [] if isinstance(item, dict)]
    if all_perps:
        return [item for item in items if item.get("market") == "perps"]

    rankings = market.get("rankings") or {}
    by_symbol: dict[str, dict[str, Any]] = {}
    for bucket in ("short_watch", "tight_liquid", "top_losers"):
        for item in rankings.get(bucket) or []:
            if isinstance(item, dict) and item.get("market") == "perps" and item.get("symbol"):
                by_symbol[str(item["symbol"])] = item
    return list(by_symbol.values())


@dataclass(frozen=True)
class GateRow:
    symbol: str
    status: str
    score: float
    spread_bps: float
    liquidity_usd: float
    change_pct: float
    funding_bps: float
    maker_fee_rt_bps: float
    taker_fee_rt_bps: float
    maker_edge_bps: float
    spread_pass: bool
    liquidity_pass: bool
    fee_pass: bool
    adverse_selection_pass: bool
    position_truth_pass: bool
    loss_budget_pass: bool
    policy_gate_pass: bool
    blockers: list[str]


def adverse_selection_score(item: dict[str, Any]) -> tuple[float, bool, list[str]]:
    spread = float(dec(item.get("spread_bps")))
    volume = float(dec(item.get("quote_volume_usd")))
    change = float(dec(item.get("change_pct")))
    funding_bps = float(dec(item.get("funding_rate"))) * 10_000.0
    blockers: list[str] = []

    score = 100.0
    score -= max(0.0, spread - 3.0) * 3.0
    score += min(20.0, math.log10(max(volume, 1.0) / 75_000.0) * 20.0)
    if funding_bps >= 0:
        score += min(10.0, funding_bps * 2.0)
    else:
        score += max(-20.0, funding_bps * 6.0)
    if change > -0.5:
        blockers.append("short_momentum_weak")
        score -= 20.0
    if change < -8.0:
        blockers.append("move_too_extended_reversal_risk")
        score -= 25.0
    if spread > 12.0:
        blockers.append("spread_wide")
    if volume < 75_000.0:
        blockers.append("liquidity_thin")
    return round(clamp(score), 2), not blockers, blockers


def evaluate_item(
    item: dict[str, Any],
    *,
    fees: dict[str, float],
    pos: dict[str, Any],
    policy: dict[str, Any],
    sys_blockers: list[str],
    max_spread_bps: float,
    min_liquidity_usd: float,
) -> GateRow:
    spread = float(dec(item.get("spread_bps")))
    volume = float(dec(item.get("quote_volume_usd")))
    change = float(dec(item.get("change_pct")))
    funding_bps = float(dec(item.get("funding_rate"))) * 10_000.0
    maker_edge = spread - fees["maker_roundtrip_bps"]
    adverse_score, adverse_pass, adverse_blockers = adverse_selection_score(item)

    spread_pass = spread <= max_spread_bps
    liquidity_pass = volume >= min_liquidity_usd
    fee_pass = maker_edge >= 1.0
    position_pass = bool(pos.get("pass"))
    loss_pass = float(policy.get("max_daily_loss_usd") or 0.0) > 0 and float(policy.get("max_notional_usd") or 0.0) > 0
    hard_policy_blockers = {
        "position_truth_unverified",
        "open_perp_positions_present",
        "market_direction_signal_missing",
        "market_direction_signal_stale",
        "safety_halt_active",
    }
    policy_pass = bool(policy.get("lane_present")) and not hard_policy_blockers.intersection(policy.get("blockers") or [])

    blockers: list[str] = []
    if not spread_pass:
        blockers.append("spread")
    if not liquidity_pass:
        blockers.append("liquidity")
    if not fee_pass:
        blockers.append("fee_edge")
    if not adverse_pass:
        blockers.extend(adverse_blockers)
    if not position_pass:
        blockers.extend(pos.get("blockers") or ["position_truth"])
    if not loss_pass:
        blockers.append("loss_budget")
    if not policy_pass:
        blockers.append("policy_gate")
    if "micro_pilot_negative_edge_cooldown" in sys_blockers:
        blockers.append("micro_pilot_cooldown")

    score = (
        (100.0 - min(100.0, spread / max(max_spread_bps, 0.01) * 100.0)) * 0.16
        + min(100.0, volume / max(min_liquidity_usd, 1.0) * 60.0) * 0.18
        + clamp((maker_edge + 10.0) * 5.0) * 0.18
        + adverse_score * 0.18
        + (100.0 if position_pass else 0.0) * 0.10
        + (100.0 if loss_pass else 0.0) * 0.10
        + (100.0 if policy_pass else 0.0) * 0.10
    )

    status = "READY_REVIEW"
    if blockers:
        status = "BLOCKED"
    if blockers == ["micro_pilot_cooldown"] or (set(blockers) == {"micro_pilot_cooldown"}):
        status = "PAPER_READY_LIVE_COOLDOWN"
    elif "micro_pilot_cooldown" in blockers and len(blockers) <= 2:
        status = "NEAR_READY_COOLDOWN"

    return GateRow(
        symbol=str(item.get("symbol") or ""),
        status=status,
        score=round(score, 2),
        spread_bps=round(spread, 6),
        liquidity_usd=round(volume, 2),
        change_pct=round(change, 6),
        funding_bps=round(funding_bps, 6),
        maker_fee_rt_bps=round(fees["maker_roundtrip_bps"], 6),
        taker_fee_rt_bps=round(fees["taker_roundtrip_bps"], 6),
        maker_edge_bps=round(maker_edge, 6),
        spread_pass=spread_pass,
        liquidity_pass=liquidity_pass,
        fee_pass=fee_pass,
        adverse_selection_pass=adverse_pass,
        position_truth_pass=position_pass,
        loss_budget_pass=loss_pass,
        policy_gate_pass=policy_pass,
        blockers=sorted(set(blockers)),
    )


def build_report(
    *,
    market_path: Path = MARKET_LATEST,
    monitor_path: Path = MONITOR_LATEST,
    system_map_path: Path = SYSTEM_MAP_LATEST,
    all_perps: bool = False,
    max_spread_bps: float = 12.0,
    min_liquidity_usd: float = 75_000.0,
) -> dict[str, Any]:
    start = time.perf_counter()
    market = read_json(market_path)
    monitor = read_json(monitor_path)
    system_map = read_json(system_map_path)
    fees = fee_rates_bps(monitor)
    pos = position_truth(monitor)
    policy = policy_context(monitor)
    sys_blockers = system_blockers(system_map)
    items = watchlist_items(market, all_perps=all_perps)
    rows = [
        evaluate_item(
            item,
            fees=fees,
            pos=pos,
            policy=policy,
            sys_blockers=sys_blockers,
            max_spread_bps=max_spread_bps,
            min_liquidity_usd=min_liquidity_usd,
        )
        for item in items
    ]
    status_rank = {
        "READY_REVIEW": 3,
        "PAPER_READY_LIVE_COOLDOWN": 2,
        "NEAR_READY_COOLDOWN": 1,
        "BLOCKED": 0,
    }
    rows = sorted(
        rows,
        key=lambda row: (status_rank.get(row.status, 0), row.score, row.liquidity_usd),
        reverse=True,
    )
    elapsed_ms = round((time.perf_counter() - start) * 1000.0, 3)
    return {
        "ts": iso_now(),
        "mode": "READ_ONLY_SODEX_WATCHLIST_GATE_ACCELERATOR",
        "policy": "no orders, no cancels, no leverage change, no credential change",
        "latency_ms": elapsed_ms,
        "freshness": {
            "market_scan_age_s": age_seconds(market_path),
            "monitor_age_s": age_seconds(monitor_path),
            "system_map_age_s": age_seconds(system_map_path),
        },
        "thresholds": {
            "max_spread_bps": max_spread_bps,
            "min_liquidity_usd": min_liquidity_usd,
            "maker_edge_min_bps": 1.0,
        },
        "global": {
            "fees": fees,
            "position_truth": pos,
            "policy_decision": policy.get("decision"),
            "policy_regime": policy.get("regime"),
            "policy_blockers": policy.get("blockers"),
            "lane": policy.get("lane"),
            "system_blockers": sys_blockers,
        },
        "counts": {
            "watchlist": len(rows),
            "ready_review": sum(1 for row in rows if row.status == "READY_REVIEW"),
            "near_ready_cooldown": sum(1 for row in rows if "COOLDOWN" in row.status),
            "blocked": sum(1 for row in rows if row.status == "BLOCKED"),
        },
        "top": [asdict(row) for row in rows[:25]],
        "rows": [asdict(row) for row in rows],
    }


def build_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# SoDEX Watchlist Gate Accelerator",
        "",
        f"Generated UTC: `{report['ts']}`",
        "",
        f"Mode: `{report['mode']}`",
        "",
        f"Policy: `{report['policy']}`",
        "",
        f"Latency: `{report['latency_ms']} ms`",
        "",
        "## Global State",
        "",
        f"- Policy decision: `{report['global']['policy_decision']}`",
        f"- Regime: `{report['global']['policy_regime']}`",
        f"- Position truth: `{report['global']['position_truth']}`",
        f"- System blockers: `{report['global']['system_blockers']}`",
        "",
        "## Counts",
        "",
    ]
    for key, value in report["counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend([
        "",
        "## Top Watchlist Gates",
        "",
        "| Symbol | Status | Score | Spread bps | Liquidity | Maker edge bps | Funding bps | Blockers |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ])
    for row in report["top"][:20]:
        blockers = ", ".join(row["blockers"]) if row["blockers"] else "none"
        lines.append(
            f"| `{row['symbol']}` | `{row['status']}` | {row['score']} | "
            f"{row['spread_bps']} | {row['liquidity_usd']} | {row['maker_edge_bps']} | "
            f"{row['funding_bps']} | {blockers} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def persist(report: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DOC.parent.mkdir(parents=True, exist_ok=True)
    tmp = LATEST.with_name(f".{LATEST.name}.tmp")
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(LATEST)
    DOC.write_text(build_markdown(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only SoDEX watchlist gate accelerator")
    parser.add_argument("--all-perps", action="store_true", help="evaluate all perps, not only watchlist buckets")
    parser.add_argument("--max-spread-bps", type=float, default=12.0)
    parser.add_argument("--min-liquidity-usd", type=float, default=75_000.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = build_report(
        all_perps=args.all_perps,
        max_spread_bps=args.max_spread_bps,
        min_liquidity_usd=args.min_liquidity_usd,
    )
    persist(report)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(json.dumps({
            "ts": report["ts"],
            "latency_ms": report["latency_ms"],
            "counts": report["counts"],
            "policy_decision": report["global"]["policy_decision"],
            "top": report["top"][:8],
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
