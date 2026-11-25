#!/usr/bin/env python3
"""Read-only E2Dir + Pre-Loser amplifier scanner for SoDEX.

Ranks BEAR-market SHORT candidates using funding, 24h loser status, liquidity,
spread, and estimated taker round-trip cost. It never places orders.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

MONITOR_LATEST = PROJECT / "data" / "sodex_monitor_eval" / "latest.json"
MIN_QUOTE_VOLUME_USD = Decimal("75000")
MIN_NEGATIVE_CHANGE_PCT = Decimal("-1.0")
MAX_SPREAD_PCT = Decimal("0.0012")
TAKER_ROUNDTRIP_COST_BPS = Decimal("7.2")
MIN_LIVE_EDGE_BPS = Decimal("12.0")
MIN_LIVE_SCORE = Decimal("10.0")
MIN_SAFETY_HALT_SHORT_EDGE_BPS = Decimal("8.0")
MIN_SAFETY_HALT_SHORT_SCORE = Decimal("10.0")
MIN_DEADLINE_EDGE_BPS = Decimal("3.0")
MIN_DEADLINE_SCORE = Decimal("7.0")
DEADLINE_ALLOWED_BLOCKERS = {
    "official_dashboard_not_canonical",
    "weekly_win_rate_below_target",
    "e1_no_loss_coverage_short",
    "volume_fee_ratio_below_target",
}


def dec(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def extract_data(payload: Any) -> Any:
    if isinstance(payload, dict):
        for key in ("data", "result", "tickers"):
            if key in payload:
                return payload[key]
    return payload


def as_list(payload: Any, key: str) -> list[dict[str, Any]]:
    data = extract_data(payload)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict) and isinstance(data.get(key), list):
        return [x for x in data[key] if isinstance(x, dict)]
    return []


def run_json(args: list[str], timeout: int = 45) -> Any:
    proc = subprocess.run(
        args,
        cwd=PROJECT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"command_failed:{args[:4]}:rc={proc.returncode}:{proc.stderr[-400:]}")
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def tickers() -> list[dict[str, Any]]:
    return as_list(run_json(["bin/sodex", "tickers", "perps", "--format", "json"]), "tickers")


def orderbook(symbol: str) -> dict[str, Any]:
    payload = run_json(["bin/sodex", "orderbook", "perps", symbol, "--depth", "3", "--format", "json"])
    data = extract_data(payload)
    return data if isinstance(data, dict) else {}


def _book_price(book: dict[str, Any], side: str) -> Decimal:
    levels = book.get(side) or []
    if not isinstance(levels, list) or not levels:
        return Decimal("0")
    first = levels[0]
    if isinstance(first, dict):
        return dec(first.get("price") or first.get("px"))
    if isinstance(first, list) and first:
        return dec(first[0])
    return Decimal("0")


@dataclass(frozen=True)
class AmplifierCandidate:
    symbol: str
    side: str
    score: Decimal
    expected_edge_bps: Decimal
    change_pct: Decimal
    funding_rate: Decimal
    spread_pct: Decimal
    quote_volume: Decimal
    mid: Decimal


def score_short_candidate(ticker: dict[str, Any], book: dict[str, Any]) -> AmplifierCandidate | None:
    symbol = str(ticker.get("symbol") or "")
    bid = _book_price(book, "bids") or dec(ticker.get("bidPx"))
    ask = _book_price(book, "asks") or dec(ticker.get("askPx"))
    if not symbol or bid <= 0 or ask <= bid:
        return None
    mid = (bid + ask) / Decimal("2")
    spread_pct = (ask - bid) / mid
    change_pct = dec(ticker.get("changePct") or ticker.get("priceChangePercent"))
    quote_volume = dec(ticker.get("quoteVolume") or ticker.get("volumeUsd") or ticker.get("volume"))
    funding_rate = dec(ticker.get("fundingRate"))
    if change_pct > MIN_NEGATIVE_CHANGE_PCT:
        return None
    if quote_volume < MIN_QUOTE_VOLUME_USD:
        return None
    if spread_pct > MAX_SPREAD_PCT:
        return None

    spread_bps = spread_pct * Decimal("10000")
    funding_bps = funding_rate * Decimal("10000")
    loser_bps = min(abs(change_pct) * Decimal("2.5"), Decimal("30"))
    liquidity_bonus = min(quote_volume / Decimal("1000000"), Decimal("5"))
    expected_edge_bps = loser_bps + max(Decimal("0"), funding_bps * Decimal("2")) - spread_bps - TAKER_ROUNDTRIP_COST_BPS
    score = (expected_edge_bps / Decimal("2")) + liquidity_bonus + abs(change_pct)
    return AmplifierCandidate(
        symbol=symbol,
        side="sell",
        score=score,
        expected_edge_bps=expected_edge_bps,
        change_pct=change_pct,
        funding_rate=funding_rate,
        spread_pct=spread_pct,
        quote_volume=quote_volume,
        mid=mid,
    )


def _prefilter(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prelim = [
        row for row in rows
        if dec(row.get("changePct") or row.get("priceChangePercent")) <= MIN_NEGATIVE_CHANGE_PCT
        and dec(row.get("quoteVolume") or row.get("volumeUsd") or row.get("volume")) >= MIN_QUOTE_VOLUME_USD
    ]
    return sorted(
        prelim,
        key=lambda row: (
            dec(row.get("fundingRate")),
            abs(dec(row.get("changePct") or row.get("priceChangePercent"))),
            dec(row.get("quoteVolume") or row.get("volumeUsd") or row.get("volume")),
        ),
        reverse=True,
    )[:20]


def select_short_candidates(rows: list[dict[str, Any]], limit: int = 5) -> list[AmplifierCandidate]:
    candidates: list[AmplifierCandidate] = []
    for row in _prefilter(rows):
        symbol = str(row.get("symbol") or "")
        try:
            candidate = score_short_candidate(row, orderbook(symbol))
        except Exception:
            candidate = None
        if candidate:
            candidates.append(candidate)
    return sorted(candidates, key=lambda item: item.score, reverse=True)[:limit]


def promotion_decision(policy: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    blockers = list(policy.get("blockers") or [])
    best = candidates[0] if candidates else {}
    edge = dec(best.get("expected_edge_bps"))
    score = dec(best.get("score"))
    policy_clear = not blockers and str(policy.get("decision")) in {"CAPPED_CATCH_UP_ALLOWED", "TARGET_MAINTENANCE_ALLOWED"}
    deadline_lane = any((lane or {}).get("lane") == "DEADLINE_MICRO_CATCHUP" for lane in policy.get("opportunity_lanes") or [])
    safety_halt_short_lane = any((lane or {}).get("lane") == "SAFETY_HALT_SHORT_PILOT" for lane in policy.get("opportunity_lanes") or [])
    ratio_recovery_lane = any((lane or {}).get("lane") == "RATIO_RECOVERY_MAKER_ONLY" for lane in policy.get("opportunity_lanes") or [])
    deadline_blockers_ok = set(blockers).issubset(DEADLINE_ALLOWED_BLOCKERS)
    edge_ok = edge >= MIN_LIVE_EDGE_BPS and score >= MIN_LIVE_SCORE
    safety_halt_short_edge_ok = edge >= MIN_SAFETY_HALT_SHORT_EDGE_BPS and score >= MIN_SAFETY_HALT_SHORT_SCORE
    deadline_edge_ok = edge >= MIN_DEADLINE_EDGE_BPS and score >= MIN_DEADLINE_SCORE
    deadline_allowed = bool(deadline_lane and deadline_blockers_ok and deadline_edge_ok)
    safety_halt_short_allowed = bool(
        safety_halt_short_lane
        and str(policy.get("decision")) == "SAFETY_HALT_SHORT_PILOT_CANDIDATE"
        and safety_halt_short_edge_ok
    )
    ratio_recovery_allowed = bool(ratio_recovery_lane and best)
    live_allowed = bool((policy_clear and edge_ok) or deadline_allowed or safety_halt_short_allowed or ratio_recovery_allowed)
    phase = "PAPER_AMPLIFIER_ONLY"
    if policy_clear and edge_ok:
        phase = "LIVE_E2DIR_MICRO_CANDIDATE"
    elif deadline_allowed:
        phase = "DEADLINE_E2DIR_MICRO_CANDIDATE"
    elif safety_halt_short_allowed:
        phase = "SAFETY_HALT_E2DIR_SHORT_PILOT_CANDIDATE"
    elif ratio_recovery_allowed:
        phase = "RATIO_RECOVERY_MAKER_ONLY_CANDIDATE"
    return {
        "phase": phase,
        "live_allowed": live_allowed,
        "deadline_flex": deadline_allowed,
        "safety_halt_short_flex": safety_halt_short_allowed,
        "ratio_recovery": ratio_recovery_allowed,
        "policy_decision": policy.get("decision"),
        "blockers": blockers,
        "best_symbol": best.get("symbol"),
        "best_score": float(score),
        "best_expected_edge_bps": float(edge),
        "requires": [
            "no_open_perps",
            "fresh_signal",
            "operator_approval",
            "explicit_safety_halt_override" if safety_halt_short_allowed else "policy_clear_or_deadline_lane",
            "reduce_only_exit_plan",
            "positive_paper_or_policy_clear",
            "real_volume_loss_ratio_gte_5100",
        ],
    }


def _target_policy(report: dict[str, Any]) -> dict[str, Any]:
    from scripts.sodex_target_policy import evaluate_target_policy

    return evaluate_target_policy(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only SoDEX E2Dir amplifier scanner")
    parser.add_argument("--monitor-json", type=Path, default=MONITOR_LATEST)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args(argv)
    report = json.loads(args.monitor_json.read_text()) if args.monitor_json.exists() else {}
    policy = _target_policy(report)
    candidates = select_short_candidates(tickers(), limit=max(1, int(args.limit)))
    rows = [
        {key: float(value) if isinstance(value, Decimal) else value for key, value in asdict(candidate).items()}
        for candidate in candidates
    ]
    result = {
        "mode": "READ_ONLY_E2DIR_AMPLIFIER_SCAN",
        "policy": {
            "decision": policy.get("decision"),
            "regime": policy.get("regime"),
            "blockers": policy.get("blockers") or [],
        },
        "candidates": rows,
        "decision": promotion_decision(policy, rows),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
