#!/usr/bin/env python3
"""Queue-aware, read-only SoDEX maker replay with chronological OOS selection.

Unlike the touch-based shadow, this lab only infers a passive fill when a newly
observed trade and the best price both move through the simulated quote. After
the first fill it models the real PIN behavior: cancel the sibling, place an
exact reduce-only maker close, then use a taker fallback after a separate TTL.
There is deliberately no exchange client and no order path in this module.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
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
DEFAULT_OUT = PROJECT / "data" / "sodex_queue_fill_lab"


@dataclass(frozen=True)
class Variant:
    quote_ttl_s: int
    close_ttl_s: int
    min_spread_bps: float
    max_abs_obi: float
    max_abs_momentum_bps: float
    close_mode: str = "adaptive_zero_gross"
    price_improve_ticks: int = 0


@dataclass
class Tape:
    ts: list[float]
    bid: list[float]
    ask: list[float]
    bid_sz: list[float]
    ask_sz: list[float]
    last: list[float]
    mid: list[float]
    spread_bps: list[float]
    obi: list[float]
    momentum_bps: list[float]


@dataclass(frozen=True)
class Episode:
    opened_ts: float
    closed_ts: float
    kind: str
    net_bps: float
    first_fill_s: float
    close_s: float


def build_tape(rows: list[tuple], momentum_window_s: int = 30) -> Tape:
    ts: list[float] = []
    bid: list[float] = []
    ask: list[float] = []
    bid_sz: list[float] = []
    ask_sz: list[float] = []
    last: list[float] = []
    for raw in rows:
        try:
            t, b, a, bs, ass, trade = map(float, raw)
        except (TypeError, ValueError):
            continue
        if t <= 0 or b <= 0 or a <= b or (ts and t <= ts[-1]):
            continue
        ts.append(t)
        bid.append(b)
        ask.append(a)
        bid_sz.append(max(bs, 0.0))
        ask_sz.append(max(ass, 0.0))
        last.append(trade if trade > 0 else (b + a) / 2)
    mid = [(b + a) / 2 for b, a in zip(bid, ask)]
    spread = [(a - b) / m * 10_000 for b, a, m in zip(bid, ask, mid)]
    obi = [((bs - ass) / (bs + ass) if bs + ass > 0 else 0.0)
           for bs, ass in zip(bid_sz, ask_sz)]
    momentum: list[float] = []
    for i, current in enumerate(ts):
        p = bisect.bisect_left(ts, current - momentum_window_s, 0, i + 1)
        momentum.append((mid[i] / mid[p] - 1) * 10_000 if p < i else 0.0)
    return Tape(ts, bid, ask, bid_sz, ask_sz, last, mid, spread, obi, momentum)


def _new_trade(tape: Tape, i: int) -> bool:
    return i > 0 and tape.last[i] != tape.last[i - 1]


def _bid_through(tape: Tape, i: int, price: float) -> bool:
    return _new_trade(tape, i) and tape.last[i] <= price and tape.bid[i] < price


def _ask_through(tape: Tape, i: int, price: float) -> bool:
    return _new_trade(tape, i) and tape.last[i] >= price and tape.ask[i] > price


def estimate_tick(tape: Tape, i: int, lookback: int = 300) -> float:
    values = tape.bid[max(0, i - lookback):i + 1] + tape.ask[max(0, i - lookback):i + 1]
    unique = sorted(set(values))
    deltas = [b - a for a, b in zip(unique, unique[1:]) if b - a > 1e-12]
    return min(deltas) if deltas else 0.0


def simulate_episode(
    tape: Tape,
    start_i: int,
    quote_ttl_s: int,
    close_ttl_s: int,
    maker_fee_bps: float,
    taker_fee_bps: float,
    close_mode: str = "fixed",
    price_improve_ticks: int = 0,
) -> Episode | None:
    """Conservative first-fill -> maker-close -> taker-fallback simulation."""
    opened = tape.ts[start_i]
    quote_deadline = opened + quote_ttl_s
    tick = estimate_tick(tape, start_i)
    improve = tick * price_improve_ticks
    entry_bid = tape.bid[start_i] + improve
    entry_ask = tape.ask[start_i] - improve
    if entry_bid >= entry_ask:
        return None
    mid = tape.mid[start_i]
    first_i: int | None = None
    sign = 0
    i = start_i + 1
    while i < len(tape.ts) and tape.ts[i] <= quote_deadline:
        bid_fill = _bid_through(tape, i, entry_bid)
        ask_fill = _ask_through(tape, i, entry_ask)
        if bid_fill != ask_fill:
            first_i = i
            sign = 1 if bid_fill else -1
            break
        i += 1
    if first_i is None:
        return None

    close_deadline = tape.ts[first_i] + close_ttl_s
    close_price = entry_ask if sign > 0 else entry_bid
    last_reprice = tape.ts[first_i]
    i = first_i + 1
    while i < len(tape.ts) and tape.ts[i] <= close_deadline:
        maker_closed = (_ask_through(tape, i, close_price) if sign > 0
                        else _bid_through(tape, i, close_price))
        if maker_closed:
            gross_bps = ((close_price - entry_bid) if sign > 0
                         else (entry_ask - close_price)) / mid * 10_000
            return Episode(opened, tape.ts[i], "paired", gross_bps - 2 * maker_fee_bps,
                           tape.ts[first_i] - opened, tape.ts[i] - tape.ts[first_i])
        if close_mode == "adaptive_zero_gross" and tape.ts[i] - last_reprice >= 6:
            close_price = (max(entry_bid, tape.ask[i] - improve) if sign > 0
                           else min(entry_ask, tape.bid[i] + improve))
            last_reprice = tape.ts[i]
        i += 1

    exit_i = min(max(i - 1, first_i), len(tape.ts) - 1)
    if sign > 0:
        gross_bps = (tape.bid[exit_i] - entry_bid) / mid * 10_000
        kind = "orphan_bid"
    else:
        gross_bps = (entry_ask - tape.ask[exit_i]) / mid * 10_000
        kind = "orphan_ask"
    return Episode(opened, tape.ts[exit_i], kind,
                   gross_bps - maker_fee_bps - taker_fee_bps,
                   tape.ts[first_i] - opened, tape.ts[exit_i] - tape.ts[first_i])


def variant_grid() -> list[Variant]:
    return [
        Variant(q, c, spread, obi, momentum, "adaptive_zero_gross", improve)
        for q in (30, 60)
        for c in (60, 120, 180, 300)
        for spread in (4.0, 8.0, 12.0, 20.0)
        for obi in (0.15, 0.35, 0.60)
        for momentum in (3.0, 8.0)
        for improve in (0, 1)
    ]


def _sample_indices(tape: Tape, start: float, end: float, sample_s: int) -> list[int]:
    out: list[int] = []
    i = bisect.bisect_left(tape.ts, start)
    next_ts = start
    while i < len(tape.ts) and tape.ts[i] < end:
        if tape.ts[i] >= next_ts:
            out.append(i)
            next_ts = tape.ts[i] + sample_s
        i += 1
    return out


def summarize(episodes: list[Episode], hours: float, ratio_floor: float) -> dict:
    values = [e.net_bps for e in episodes]
    n = len(values)
    total = sum(values)
    avg = total / n if n else 0.0
    sd = statistics.stdev(values) if n >= 2 else 0.0
    lcb = avg - 1.645 * sd / math.sqrt(n) if n else float("-inf")
    ratio = 20_000 * n / -total if n and total < 0 else None
    allowed_avg_loss_bps = 20_000 / ratio_floor
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    paired = sum(e.kind == "paired" for e in episodes)
    return {
        "round_trips": n,
        "paired": paired,
        "orphans": n - paired,
        "paired_share": round(paired / n, 6) if n else 0.0,
        "avg_net_bps": round(avg, 6),
        "net_bps_lcb95": round(lcb, 6) if n else None,
        "sum_net_bps": round(total, 6),
        "max_drawdown_bps": round(drawdown, 6),
        "max_loss_bps": round(min(values), 6) if values else None,
        "round_trips_per_hour": round(n / max(hours, 1e-9), 6),
        "volume_per_hour_usd_at_20": round(40 * n / max(hours, 1e-9), 2),
        "honest_ratio_proxy": round(ratio, 2) if ratio is not None else None,
        "honest_ratio_proxy_infinite": bool(n and ratio is None),
        "ratio_lcb_pass": bool(n and lcb >= -allowed_avg_loss_bps),
        "meets_ratio_floor": bool(n and (ratio is None or ratio >= ratio_floor)),
        "median_first_fill_s": round(statistics.median(
            [e.first_fill_s for e in episodes]), 3) if episodes else None,
        "median_close_s": round(statistics.median(
            [e.close_s for e in episodes]), 3) if episodes else None,
    }


def evaluate_variant(
    tape: Tape,
    variant: Variant,
    start: float,
    end: float,
    *,
    sample_s: int,
    maker_fee_bps: float,
    taker_fee_bps: float,
    ratio_floor: float,
    cache: dict[tuple[int, int, int, str, int], Episode | None],
) -> tuple[dict, list[Episode]]:
    episodes: list[Episode] = []
    blocked_until = start
    for i in _sample_indices(tape, start, end, sample_s):
        if tape.ts[i] < blocked_until:
            continue
        if (tape.spread_bps[i] < variant.min_spread_bps
                or abs(tape.obi[i]) > variant.max_abs_obi
                or abs(tape.momentum_bps[i]) > variant.max_abs_momentum_bps):
            continue
        key = (i, variant.quote_ttl_s, variant.close_ttl_s,
               variant.close_mode, variant.price_improve_ticks)
        if key not in cache:
            cache[key] = simulate_episode(
                tape, i, variant.quote_ttl_s, variant.close_ttl_s,
                maker_fee_bps, taker_fee_bps, variant.close_mode,
                variant.price_improve_ticks)
        episode = cache[key]
        if episode and episode.closed_ts < end:
            episodes.append(episode)
            blocked_until = episode.closed_ts
        else:
            blocked_until = tape.ts[i] + variant.quote_ttl_s
    hours = max((end - start) / 3600, 1e-9)
    return summarize(episodes, hours, ratio_floor), episodes


def _eligible(metrics: dict, min_rt: int) -> bool:
    return bool(metrics["round_trips"] >= min_rt
                and metrics["ratio_lcb_pass"]
                and metrics["meets_ratio_floor"])


def _load_symbols(db: sqlite3.Connection, start: float, end: float,
                  max_symbols: int) -> list[str]:
    rows = db.execute(
        "SELECT symbol,COUNT(*),AVG((ask-bid)/((ask+bid)/2)*10000),"
        "AVG(MIN(bid_sz*bid,ask_sz*ask)) FROM l1 "
        "WHERE ts>=? AND ts<=? AND bid>0 AND ask>bid GROUP BY symbol",
        (start, end)).fetchall()
    structural = []
    for symbol, n, spread, depth in rows:
        if n >= 1000 and spread >= 3.0 and depth >= 100.0:
            score = float(spread) * math.log1p(float(depth))
            structural.append((score, symbol, spread, depth))
    structural.sort(reverse=True)
    return [row[1] for row in structural[:max_symbols]]


def run(args: argparse.Namespace) -> dict:
    db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    min_ts, max_ts = db.execute("SELECT MIN(ts),MAX(ts) FROM l1").fetchone()
    if not min_ts or not max_ts or max_ts - min_ts < 4 * 3600:
        raise SystemExit("insufficient L1 history")
    train_end = min_ts + (max_ts - min_ts) * 0.50
    val_end = min_ts + (max_ts - min_ts) * 0.75
    symbols = _load_symbols(db, min_ts, train_end, args.max_symbols)
    variants = variant_grid()
    candidates: list[dict] = []
    baseline_rows: list[dict] = []
    for symbol in symbols:
        rows = db.execute(
            "SELECT ts,bid,ask,bid_sz,ask_sz,last FROM l1 "
            "WHERE symbol=? AND ts>=? AND ts<=? ORDER BY ts",
            (symbol, min_ts, max_ts)).fetchall()
        tape = build_tape(rows)
        cache: dict[tuple[int, int, int, str, int], Episode | None] = {}
        baseline = Variant(30, 30, 4.0, 1.0, 1e9, "fixed")
        base_metrics, _ = evaluate_variant(
            tape, baseline, val_end, max_ts, sample_s=args.sample_s,
            maker_fee_bps=args.maker_fee_bps, taker_fee_bps=args.taker_fee_bps,
            ratio_floor=args.ratio_floor, cache=cache)
        baseline_rows.append({"symbol": symbol, "variant": asdict(baseline),
                              "oos": base_metrics})
        accepted: list[tuple[float, Variant, dict, dict]] = []
        for variant in variants:
            train, _ = evaluate_variant(
                tape, variant, min_ts, train_end, sample_s=args.sample_s,
                maker_fee_bps=args.maker_fee_bps, taker_fee_bps=args.taker_fee_bps,
                ratio_floor=args.ratio_floor, cache=cache)
            if not _eligible(train, args.min_train_rt):
                continue
            validation, _ = evaluate_variant(
                tape, variant, train_end, val_end, sample_s=args.sample_s,
                maker_fee_bps=args.maker_fee_bps, taker_fee_bps=args.taker_fee_bps,
                ratio_floor=args.ratio_floor, cache=cache)
            if not _eligible(validation, args.min_validation_rt):
                continue
            robust_volume = min(train["volume_per_hour_usd_at_20"],
                                validation["volume_per_hour_usd_at_20"])
            accepted.append((robust_volume, variant, train, validation))
        if not accepted:
            continue
        accepted.sort(key=lambda row: (row[0], row[3]["net_bps_lcb95"]), reverse=True)
        _, winner, train, validation = accepted[0]
        oos, episodes = evaluate_variant(
            tape, winner, val_end, max_ts, sample_s=args.sample_s,
            maker_fee_bps=args.maker_fee_bps, taker_fee_bps=args.taker_fee_bps,
            ratio_floor=args.ratio_floor, cache=cache)
        candidates.append({
            "symbol": symbol,
            "variant": asdict(winner),
            "train": train,
            "validation": validation,
            "oos": oos,
            "oos_pass": _eligible(oos, args.min_validation_rt),
            "oos_sample": [asdict(e) for e in episodes[:10]],
        })
    db.close()
    candidates.sort(key=lambda row: (
        bool(row["oos_pass"]), row["oos"]["volume_per_hour_usd_at_20"],
        row["oos"]["net_bps_lcb95"] or -1e9), reverse=True)
    dataset_id = hashlib.sha256(
        f"{args.db}:{min_ts:.3f}:{max_ts:.3f}".encode()).hexdigest()[:16]
    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY_QUEUE_AWARE_PRICE_THROUGH_REPLAY_NO_ORDER_PATH",
        "dataset": {"id": dataset_id, "start_ts": min_ts, "end_ts": max_ts,
                    "hours": round((max_ts - min_ts) / 3600, 3),
                    "symbols_screened": symbols},
        "split": {"train_end": train_end, "validation_end": val_end,
                  "train_pct": 50, "validation_pct": 25, "oos_pct": 25},
        "search": {"variants_per_symbol": len(variants), "sample_s": args.sample_s,
                   "max_symbols": args.max_symbols},
        "cost_model": {"maker_fee_bps_per_leg": args.maker_fee_bps,
                       "taker_fee_bps": args.taker_fee_bps,
                       "ratio_floor": args.ratio_floor},
        "fill_model": {
            "entry": "new trade plus best-price through quote",
            "close": "fresh phase TTL; maker price-through else taker fallback",
            "known_limit": "polling L1 cannot observe exact queue position or cancellations",
        },
        "baseline_oos": baseline_rows,
        "candidates": candidates,
        "promotion_allowed": False,
        "next_gate": "public trade/depth queue replay and forward shadow; no live orders",
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    latest = args.out_dir / "latest.json"
    tmp = latest.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2) + "\n")
    tmp.replace(latest)
    ledger = args.out_dir / "decision_ledger.jsonl"
    mark = {
        "ts": report["created_at"], "dataset_id": dataset_id,
        "candidate_count": len(candidates),
        "top": ({k: candidates[0][k] for k in ("symbol", "variant", "oos", "oos_pass")}
                if candidates else None),
        "mark": "needs_public_trade_replay" if candidates else "reject_all",
        "live_promotion_allowed": False,
    }
    with ledger.open("a") as handle:
        handle.write(json.dumps(mark) + "\n")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--max-symbols", type=int, default=16)
    parser.add_argument("--sample-s", type=int, default=6)
    parser.add_argument("--maker-fee-bps", type=float, default=1.08)
    parser.add_argument("--taker-fee-bps", type=float, default=3.6)
    parser.add_argument("--ratio-floor", type=float, default=4500.0)
    parser.add_argument("--min-train-rt", type=int, default=12)
    parser.add_argument("--min-validation-rt", type=int, default=6)
    return parser.parse_args()


def main() -> int:
    started = time.time()
    report = run(parse_args())
    top = report["candidates"][:5]
    print(json.dumps({
        "mode": report["mode"], "dataset": report["dataset"],
        "top_candidates": [{"symbol": row["symbol"], "variant": row["variant"],
                            "oos": row["oos"], "oos_pass": row["oos_pass"]}
                           for row in top],
        "runtime_seconds": round(time.time() - started, 3),
        "promotion_allowed": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
