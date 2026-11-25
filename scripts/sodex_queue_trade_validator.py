#!/usr/bin/env python3
"""Validate QIP candidates with public aggressive trades and displayed queue-ahead.

Read-only: consumes local L1 and public-trade SQLite databases. A simulated fill
requires cumulative opposite-side aggressive quantity to clear a configurable
fraction of displayed L1 queue plus our hypothetical order quantity.
"""
from __future__ import annotations

import argparse
import bisect
import json
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scripts.sodex_queue_fill_lab import (
    Episode, Tape, Variant, build_tape, estimate_tick, summarize,
)


L1_DB = PROJECT / "data" / "sodex_book_recorder.db"
TRADES_DB = PROJECT / "data" / "sodex_public_trades.db"
OUTPUT = PROJECT / "data" / "sodex_queue_trade_validation.json"
LEDGER = PROJECT / "data" / "sodex_queue_trade_decision_ledger.jsonl"
MIN_FORWARD_HOURS = 24.0
MIN_ROUND_TRIPS = 100
MIN_PAIRED_SHARE = 0.70
MIN_VOLUME_PER_HOUR_USD = 100.0
PILOT_MIN_FORWARD_HOURS = 8.0
PILOT_MIN_ROUND_TRIPS = 100
PILOT_MIN_PAIRED_SHARE = 0.90
PILOT_MIN_VOLUME_PER_HOUR_USD = 150.0
PILOT_MIN_NOTIONAL_USD = 10.0

CANDIDATES = {
    "HYPE-USD": Variant(30, 60, 4.0, 0.60, 8.0),
    "MRVL-USD": Variant(60, 120, 4.0, 0.35, 8.0, price_improve_ticks=1),
    "SNDK-USD": Variant(30, 120, 8.0, 0.60, 8.0, price_improve_ticks=1),
    "SKHX-USD": Variant(30, 120, 8.0, 0.60, 8.0, price_improve_ticks=1),
    "VIRTUAL-USD": Variant(30, 120, 3.0, 0.60, 8.0, price_improve_ticks=1),
    "LIT-USD": Variant(30, 120, 2.0, 0.60, 8.0, price_improve_ticks=1),
    "CRCL-USD": Variant(30, 120, 12.0, 0.60, 10.0, price_improve_ticks=1),
    "MSTR-USD": Variant(30, 120, 10.0, 0.60, 10.0, price_improve_ticks=1),
    "MU-USD": Variant(30, 120, 8.0, 0.60, 10.0, price_improve_ticks=1),
    "AMD-USD": Variant(30, 120, 8.0, 0.60, 10.0, price_improve_ticks=1),
    "HOOD-USD": Variant(30, 120, 8.0, 0.60, 10.0, price_improve_ticks=1),
    "INTC-USD": Variant(30, 120, 8.0, 0.60, 10.0, price_improve_ticks=1),
    "COIN-USD": Variant(30, 120, 8.0, 0.60, 10.0, price_improve_ticks=1),
    "SKHY-USD": Variant(30, 120, 8.0, 0.60, 10.0, price_improve_ticks=1),
    "PLTR-USD": Variant(30, 120, 4.0, 0.60, 8.0, price_improve_ticks=1),
    "SPCX-USD": Variant(30, 120, 4.0, 0.60, 8.0, price_improve_ticks=1),
    "ZEC-USD": Variant(30, 120, 4.0, 0.60, 8.0, price_improve_ticks=1),
    "XAUT-USD": Variant(30, 120, 3.0, 0.60, 8.0, price_improve_ticks=1),
}


@dataclass(frozen=True)
class PublicTrade:
    ts: float
    side: str
    price: float
    qty: float


def _l1_at(tape: Tape, ts: float) -> int:
    return max(0, min(bisect.bisect_right(tape.ts, ts) - 1, len(tape.ts) - 1))


def _trade_range(trades: list[PublicTrade], start: float, end: float) -> tuple[int, int]:
    timestamps = [trade.ts for trade in trades]
    return bisect.bisect_right(timestamps, start), bisect.bisect_right(timestamps, end)


def queue_fill(
    trades: list[PublicTrade],
    start: float,
    end: float,
    *,
    passive_side: str,
    price: float,
    required_qty: float,
) -> tuple[float, float] | None:
    """Return fill time and consumed qty after aggressive flow clears the queue."""
    lo, hi = _trade_range(trades, start, end)
    consumed = 0.0
    aggressor = "SELL" if passive_side == "BUY" else "BUY"
    for trade in trades[lo:hi]:
        eligible = (trade.side == aggressor and
                    (trade.price <= price if passive_side == "BUY" else trade.price >= price))
        if eligible:
            consumed += trade.qty
            if consumed >= required_qty:
                return trade.ts, consumed
    return None


def simulate_queue_episode(
    tape: Tape,
    trades: list[PublicTrade],
    start_i: int,
    variant: Variant,
    *,
    notional_usd: float,
    queue_fraction: float,
    maker_fee_bps: float,
    taker_fee_bps: float,
    reprice_s: int = 6,
) -> Episode | None:
    opened = tape.ts[start_i]
    mid = tape.mid[start_i]
    qty = notional_usd / mid
    improve = estimate_tick(tape, start_i) * variant.price_improve_ticks
    entry_bid = tape.bid[start_i] + improve
    entry_ask = tape.ask[start_i] - improve
    if entry_bid >= entry_ask:
        return None
    queue_multiplier = 0.0 if variant.price_improve_ticks else queue_fraction
    bid_required = tape.bid_sz[start_i] * queue_multiplier + qty
    ask_required = tape.ask_sz[start_i] * queue_multiplier + qty
    deadline = opened + variant.quote_ttl_s
    bid_fill = queue_fill(trades, opened, deadline, passive_side="BUY",
                          price=entry_bid, required_qty=bid_required)
    ask_fill = queue_fill(trades, opened, deadline, passive_side="SELL",
                          price=entry_ask, required_qty=ask_required)
    fills = [(value[0], 1) for value in [bid_fill] if value]
    fills += [(value[0], -1) for value in [ask_fill] if value]
    if not fills:
        return None
    first_ts, sign = min(fills)
    close_deadline = first_ts + variant.close_ttl_s
    slot_start = first_ts
    while slot_start < close_deadline:
        l1_i = _l1_at(tape, slot_start)
        slot_end = min(slot_start + reprice_s, close_deadline)
        close_improve = estimate_tick(tape, l1_i) * variant.price_improve_ticks
        if sign > 0:
            close_price = max(entry_bid, tape.ask[l1_i] - close_improve)
            at_best = close_price >= tape.ask[l1_i]
            required = tape.ask_sz[l1_i] * queue_fraction + qty if at_best else qty
            close = queue_fill(trades, slot_start, slot_end, passive_side="SELL",
                               price=close_price, required_qty=required)
            gross_bps = (close_price - entry_bid) / mid * 10_000
        else:
            close_price = min(entry_ask, tape.bid[l1_i] + close_improve)
            at_best = close_price <= tape.bid[l1_i]
            required = tape.bid_sz[l1_i] * queue_fraction + qty if at_best else qty
            close = queue_fill(trades, slot_start, slot_end, passive_side="BUY",
                               price=close_price, required_qty=required)
            gross_bps = (entry_ask - close_price) / mid * 10_000
        if close:
            return Episode(opened, close[0], "paired", gross_bps - 2 * maker_fee_bps,
                           first_ts - opened, close[0] - first_ts)
        slot_start = slot_end
    exit_i = _l1_at(tape, close_deadline)
    if sign > 0:
        gross_bps = (tape.bid[exit_i] - entry_bid) / mid * 10_000
        kind = "orphan_bid"
    else:
        gross_bps = (entry_ask - tape.ask[exit_i]) / mid * 10_000
        kind = "orphan_ask"
    return Episode(opened, close_deadline, kind,
                   gross_bps - maker_fee_bps - taker_fee_bps,
                   first_ts - opened, close_deadline - first_ts)


def evaluate_symbol(
    tape: Tape,
    trades: list[PublicTrade],
    variant: Variant,
    *,
    queue_fraction: float,
    notional_usd: float,
    maker_fee_bps: float,
    taker_fee_bps: float,
    ratio_floor: float,
    sample_s: int,
) -> dict:
    start = max(tape.ts[0], trades[0].ts)
    end = min(tape.ts[-1], trades[-1].ts)
    episodes: list[Episode] = []
    blocked_until = start
    next_sample = start
    i = bisect.bisect_left(tape.ts, start)
    while i < len(tape.ts) and tape.ts[i] < end:
        if tape.ts[i] < next_sample:
            i += 1
            continue
        next_sample = tape.ts[i] + sample_s
        if tape.ts[i] < blocked_until:
            i += 1
            continue
        if (tape.spread_bps[i] < variant.min_spread_bps
                or abs(tape.obi[i]) > variant.max_abs_obi
                or abs(tape.momentum_bps[i]) > variant.max_abs_momentum_bps):
            i += 1
            continue
        episode = simulate_queue_episode(
            tape, trades, i, variant, notional_usd=notional_usd,
            queue_fraction=queue_fraction, maker_fee_bps=maker_fee_bps,
            taker_fee_bps=taker_fee_bps)
        if episode and episode.closed_ts <= end:
            episodes.append(episode)
            blocked_until = episode.closed_ts
        else:
            blocked_until = tape.ts[i] + variant.quote_ttl_s
        i += 1
    metrics = summarize(episodes, max((end - start) / 3600, 1e-9), ratio_floor)
    metrics["volume_per_hour_usd"] = round(
        2 * notional_usd * len(episodes) / max((end - start) / 3600, 1e-9), 2)
    metrics.update({
        "start_ts": start, "end_ts": end,
        "hours": round((end - start) / 3600, 4),
        "notional_usd": notional_usd,
        "public_trades": len(trades),
        "queue_fraction": queue_fraction,
        "episodes": [asdict(episode) for episode in episodes[:20]],
    })
    metrics["research_gate_pass"] = research_gate_pass(metrics)
    metrics["micro_pilot_gate_pass"] = micro_pilot_gate_pass(metrics)
    return metrics


def research_gate_pass(metrics: dict) -> bool:
    """Return true only for enough forward evidence; this never authorizes live orders."""
    return bool(
        metrics.get("hours", 0) >= MIN_FORWARD_HOURS
        and metrics.get("round_trips", 0) >= MIN_ROUND_TRIPS
        and metrics.get("paired_share", 0) >= MIN_PAIRED_SHARE
        and metrics.get("volume_per_hour_usd", 0) >= MIN_VOLUME_PER_HOUR_USD
        and metrics.get("ratio_lcb_pass", False)
        and metrics.get("meets_ratio_floor", False)
    )


def micro_pilot_gate_pass(metrics: dict) -> bool:
    """Fast evidence gate for a separately capped pilot; never authorizes orders."""
    return bool(
        metrics.get("hours", 0) >= PILOT_MIN_FORWARD_HOURS
        and metrics.get("notional_usd", 0) >= PILOT_MIN_NOTIONAL_USD
        and metrics.get("round_trips", 0) >= PILOT_MIN_ROUND_TRIPS
        and metrics.get("paired_share", 0) >= PILOT_MIN_PAIRED_SHARE
        and metrics.get("volume_per_hour_usd", 0) >= PILOT_MIN_VOLUME_PER_HOUR_USD
        and metrics.get("net_bps_lcb95") is not None
        and metrics.get("net_bps_lcb95", 0) > 0
        and metrics.get("ratio_lcb_pass", False)
        and metrics.get("meets_ratio_floor", False)
    )


def run(args: argparse.Namespace) -> dict:
    l1 = sqlite3.connect(f"file:{args.l1_db}?mode=ro", uri=True)
    trade_db = sqlite3.connect(f"file:{args.trades_db}?mode=ro", uri=True)
    results: dict[str, dict] = {}
    for symbol, variant in CANDIDATES.items():
        rows = l1.execute(
            "SELECT ts,bid,ask,bid_sz,ask_sz,last FROM l1 WHERE symbol=? ORDER BY ts",
            (symbol,)).fetchall()
        raw_trades = trade_db.execute(
            "SELECT ts,side,price,qty FROM trades WHERE symbol=? ORDER BY ts", (symbol,)).fetchall()
        if not rows or not raw_trades:
            continue
        tape = build_tape(rows)
        trades = [PublicTrade(float(ts), str(side), float(price), float(qty))
                  for ts, side, price, qty in raw_trades]
        results[symbol] = {
            "variant": asdict(variant),
            "queue_scenarios": {
                str(fraction): evaluate_symbol(
                    tape, trades, variant, queue_fraction=fraction,
                    notional_usd=args.notional, maker_fee_bps=args.maker_fee_bps,
                    taker_fee_bps=args.taker_fee_bps, ratio_floor=args.ratio_floor,
                    sample_s=args.sample_s)
                for fraction in (0.0, 0.5, 1.0)
            },
        }
    l1.close()
    trade_db.close()
    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY_PUBLIC_TRADE_QUEUE_AHEAD_VALIDATION_NO_ORDER_PATH",
        "cost_model": {"maker_fee_bps": args.maker_fee_bps,
                       "taker_fee_bps": args.taker_fee_bps,
                       "ratio_floor": args.ratio_floor},
        "results": results,
        "promotion_allowed": False,
        "research_gate": {
            "minimum_forward_hours": MIN_FORWARD_HOURS,
            "minimum_round_trips": MIN_ROUND_TRIPS,
            "minimum_paired_share": MIN_PAIRED_SHARE,
            "minimum_volume_per_hour_usd": MIN_VOLUME_PER_HOUR_USD,
            "required_queue_fraction": 1.0,
            "note": "Passing this research gate does not authorize live orders.",
        },
        "micro_pilot_gate": {
            "minimum_forward_hours": PILOT_MIN_FORWARD_HOURS,
            "minimum_round_trips": PILOT_MIN_ROUND_TRIPS,
            "minimum_paired_share": PILOT_MIN_PAIRED_SHARE,
            "minimum_volume_per_hour_usd": PILOT_MIN_VOLUME_PER_HOUR_USD,
            "minimum_exchange_notional_usd": PILOT_MIN_NOTIONAL_USD,
            "required_queue_fraction": 1.0,
            "note": "Research eligibility only; separate capped implementation and authorization required.",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2) + "\n")
    tmp.replace(args.output)
    ledger_row = {
        "created_at": report["created_at"],
        "mode": report["mode"],
        "notional_usd": args.notional,
        "ratio_floor": args.ratio_floor,
        "decisions": {
            symbol: values["queue_scenarios"]["1.0"]["research_gate_pass"]
            for symbol, values in results.items()
        },
    }
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    with args.ledger.open("a") as handle:
        handle.write(json.dumps(ledger_row, sort_keys=True) + "\n")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--l1-db", type=Path, default=L1_DB)
    parser.add_argument("--trades-db", type=Path, default=TRADES_DB)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument("--notional", type=float, default=20.0)
    parser.add_argument("--maker-fee-bps", type=float, default=1.08)
    parser.add_argument("--taker-fee-bps", type=float, default=3.6)
    parser.add_argument("--ratio-floor", type=float, default=4500.0)
    parser.add_argument("--sample-s", type=int, default=6)
    return parser.parse_args()


def main() -> int:
    report = run(parse_args())
    compact = {
        symbol: {fraction: {key: values[key] for key in (
            "hours", "public_trades", "round_trips", "paired_share",
            "volume_per_hour_usd", "honest_ratio_proxy", "ratio_lcb_pass",
            "research_gate_pass", "micro_pilot_gate_pass")}
                 for fraction, values in result["queue_scenarios"].items()}
        for symbol, result in report["results"].items()
    }
    print(json.dumps(compact, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
