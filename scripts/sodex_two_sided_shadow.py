#!/usr/bin/env python3
"""Live-data, read-only shadow executor for paired SoDEX maker quotes.

This process reads the local L1 recorder and opportunity-lab watchlist. It has no
exchange client import and no order path. Results are append-only evidence for a
later, explicitly gated canary decision.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT / "data" / "sodex_book_recorder.db"
DEFAULT_LAB = PROJECT / "data" / "sodex_opportunity_lab" / "latest.json"
DEFAULT_DIR = PROJECT / "data" / "sodex_two_sided_shadow"


@dataclass
class Quote:
    symbol: str
    opened_ts: float
    deadline_ts: float
    bid: float
    ask: float
    bid_touched: bool = False
    ask_touched: bool = False


def advance_quote(
    quote: Quote,
    rows: list[tuple[float, float, float, float]],
    *,
    fee_bps: float,
    adverse_bps: float,
) -> tuple[Quote | None, dict | None]:
    """Advance one virtual quote using (ts,bid,ask,last) observations."""
    mid = (quote.bid + quote.ask) / 2.0
    for ts, bid, ask, last in rows:
        if ts <= quote.opened_ts:
            continue
        quote.bid_touched = quote.bid_touched or last <= quote.bid
        quote.ask_touched = quote.ask_touched or last >= quote.ask
        if quote.bid_touched and quote.ask_touched:
            gross = (quote.ask - quote.bid) / mid * 10_000.0
            return None, _outcome(quote, ts, "paired", gross, fee_bps, adverse_bps)
        if ts >= quote.deadline_ts:
            if quote.bid_touched:
                gross = (bid - quote.bid) / mid * 10_000.0
                return None, _outcome(quote, ts, "orphan_bid", gross, fee_bps, adverse_bps)
            if quote.ask_touched:
                gross = (quote.ask - ask) / mid * 10_000.0
                return None, _outcome(quote, ts, "orphan_ask", gross, fee_bps, adverse_bps)
            return None, _outcome(quote, ts, "no_fill", 0.0, 0.0, 0.0)
    return quote, None


def _outcome(
    quote: Quote,
    closed_ts: float,
    kind: str,
    gross_bps: float,
    fee_bps: float,
    adverse_bps: float,
) -> dict:
    filled = kind != "no_fill"
    return {
        "ts": datetime.fromtimestamp(closed_ts, timezone.utc).isoformat(),
        "symbol": quote.symbol,
        "kind": kind,
        "opened_ts": quote.opened_ts,
        "closed_ts": closed_ts,
        "gross_bps": round(gross_bps, 6),
        "net_bps": round(gross_bps - fee_bps - adverse_bps, 6) if filled else None,
        "bid_touched": quote.bid_touched,
        "ask_touched": quote.ask_touched,
    }


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n")
    tmp.replace(path)


def _load_json(path: Path, default: dict) -> dict:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else default
    except (OSError, ValueError):
        return default


def _watchlist(path: Path) -> list[dict]:
    report = _load_json(path, {})
    return [row for row in report.get("shadow_watchlist", [])
            if row.get("variant", {}).get("family") == "two_sided"]


def _stats(outcomes: list[dict], notional_usd: float, ratio_floor: float) -> dict:
    filled = [row for row in outcomes if row.get("net_bps") is not None]
    values = [float(row["net_bps"]) for row in filled]
    net_pnl = sum(values) / 10_000.0 * notional_usd
    volume = 2.0 * notional_usd * len(values)
    ratio = volume / -net_pnl if net_pnl < 0 else None
    avg = sum(values) / len(values) if values else 0.0
    sd = statistics.stdev(values) if len(values) >= 2 else 0.0
    lcb95 = avg - 1.645 * sd / math.sqrt(len(values)) if values else 0.0
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    paired = sum(row["kind"] == "paired" for row in filled)
    return {
        "completed_quotes": len(outcomes),
        "round_trips": len(values),
        "paired": paired,
        "orphans": sum(row["kind"].startswith("orphan") for row in filled),
        "no_fill": sum(row["kind"] == "no_fill" for row in outcomes),
        "paired_share": round(paired / len(values), 6) if values else 0.0,
        "avg_net_bps": round(avg, 6),
        "net_bps_lcb95": round(lcb95, 6),
        "max_drawdown_bps": round(max_drawdown, 6),
        "net_pnl_proxy_usd": round(net_pnl, 6),
        "volume_proxy_usd": round(volume, 2),
        "honest_ratio_proxy": round(ratio, 2) if ratio is not None else None,
        "honest_ratio_proxy_infinite": bool(values and ratio is None),
        "meets_ratio_floor": bool(values and (ratio is None or ratio >= ratio_floor)),
    }


def run_once(args: argparse.Namespace) -> dict:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    state_path = args.out_dir / "state.json"
    status_path = args.out_dir / "latest.json"
    ledger_path = args.out_dir / "outcomes.jsonl"
    state = _load_json(state_path, {"active": {}, "outcomes": []})
    active = state.setdefault("active", {})
    outcomes = state.setdefault("outcomes", [])
    watchlist = _watchlist(args.lab_report)
    allowed_symbols = {row["symbol"] for row in watchlist}
    for symbol in list(active):
        if symbol not in allowed_symbols:
            active.pop(symbol, None)
    now = time.time()

    db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    for candidate in watchlist:
        symbol = candidate["symbol"]
        variant = candidate["variant"]
        raw_quote = active.get(symbol)
        quote = Quote(**raw_quote) if raw_quote else None
        since = quote.opened_ts if quote else now - max(args.max_freshness_seconds, 10.0)
        rows = db.execute(
            "SELECT ts,bid,ask,last FROM l1 WHERE symbol=? AND ts>? ORDER BY ts",
            (symbol, since)).fetchall()
        if quote:
            quote, outcome = advance_quote(
                quote, rows, fee_bps=args.fee_bps, adverse_bps=args.adverse_bps)
            if outcome:
                outcomes.append(outcome)
                with ledger_path.open("a") as handle:
                    handle.write(json.dumps(outcome) + "\n")
        if quote is None and rows:
            ts, bid, ask, _ = rows[-1]
            mid = (bid + ask) / 2.0
            spread_bps = (ask - bid) / mid * 10_000.0 if mid > 0 else 0.0
            if now - ts <= args.max_freshness_seconds and spread_bps >= variant["threshold"]:
                quote = Quote(symbol, ts, ts + variant["horizon_s"], bid, ask)
        if quote:
            active[symbol] = asdict(quote)
        else:
            active.pop(symbol, None)
    db.close()

    state["outcomes"] = outcomes[-args.max_outcomes:]
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(state_path, state)
    current_outcomes = [row for row in state["outcomes"]
                        if row.get("symbol") in allowed_symbols]
    status = {
        "schema_version": 1,
        "updated_at": state["updated_at"],
        "mode": "READ_ONLY_L1_SHADOW_NO_ORDER_PATH",
        "watchlist": [row["symbol"] for row in watchlist],
        "active_quotes": active,
        "cost_model": {"fee_bps": args.fee_bps, "adverse_bps": args.adverse_bps},
        "stats": _stats(current_outcomes, args.notional_usd, args.ratio_floor),
        "stats_by_symbol": {},
    }
    for candidate in watchlist:
        symbol = candidate["symbol"]
        symbol_stats = _stats(
            [row for row in state["outcomes"] if row.get("symbol") == symbol],
            args.notional_usd, args.ratio_floor)
        symbol_stats["promotion_ready"] = bool(
            symbol_stats["round_trips"] >= args.min_promotion_round_trips
            and symbol_stats["net_bps_lcb95"] > 0
            and symbol_stats["meets_ratio_floor"])
        status["stats_by_symbol"][symbol] = symbol_stats
    _atomic_json(status_path, status)
    return status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--lab-report", type=Path, default=DEFAULT_LAB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--fee-bps", type=float, default=2.4)
    parser.add_argument("--adverse-bps", type=float, default=1.0)
    parser.add_argument("--notional-usd", type=float, default=60.0)
    parser.add_argument("--ratio-floor", type=float, default=6300.0)
    parser.add_argument("--max-freshness-seconds", type=float, default=10.0)
    parser.add_argument("--max-outcomes", type=int, default=5000)
    parser.add_argument("--min-promotion-round-trips", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    while True:
        status = run_once(args)
        print(json.dumps(status, separators=(",", ":")), flush=True)
        if not args.loop:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
