#!/usr/bin/env python3
"""Read-only scientific opportunity search over recorded SoDEX L1 data.

The lab searches broadly but cannot place orders. It selects parameters on a
chronological train/validation window and opens the final OOS window only after
selection. Maker entry fills are inferred conservatively from a later trade
touch; exits use the executable side of the book and include fees plus an
adverse-selection buffer.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import random
import sqlite3
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT / "data" / "sodex_book_recorder.db"
DEFAULT_OUT = PROJECT / "data" / "sodex_opportunity_lab"


@dataclass(frozen=True)
class Variant:
    family: str
    lookback_s: int
    horizon_s: int
    threshold: float
    ofi_threshold: float = 0.0


@dataclass
class Tape:
    ts: list[float]
    bid: list[float]
    ask: list[float]
    last: list[float]
    mid: list[float]
    obi: list[float]
    ofi_prefix: list[float]
    path_prefix: list[float]


@dataclass
class EvalResult:
    metrics: dict
    net_bps: list[float]


def _finite_float(value: object, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def build_tape(rows: list[tuple]) -> Tape:
    ts: list[float] = []
    bid: list[float] = []
    ask: list[float] = []
    last: list[float] = []
    mid: list[float] = []
    obi: list[float] = []
    bid_sz: list[float] = []
    ask_sz: list[float] = []
    for raw_ts, raw_bid, raw_ask, raw_bid_sz, raw_ask_sz, raw_last in rows:
        t = _finite_float(raw_ts)
        b = _finite_float(raw_bid)
        a = _finite_float(raw_ask)
        if t <= 0 or b <= 0 or a <= b or (ts and t <= ts[-1]):
            continue
        ts.append(t)
        bid.append(b)
        ask.append(a)
        bid_sz.append(max(_finite_float(raw_bid_sz), 0.0))
        ask_sz.append(max(_finite_float(raw_ask_sz), 0.0))
        mid.append((b + a) / 2.0)
        depth_sum = bid_sz[-1] + ask_sz[-1]
        obi.append((bid_sz[-1] - ask_sz[-1]) / depth_sum if depth_sum else 0.0)
        last.append(_finite_float(raw_last, (b + a) / 2.0))

    ofi_prefix = [0.0]
    path_prefix = [0.0]
    for i in range(len(ts)):
        if i == 0:
            ofi = 0.0
            path = 0.0
        else:
            e_bid = (bid_sz[i] if bid[i] > bid[i - 1]
                     else bid_sz[i] - bid_sz[i - 1] if bid[i] == bid[i - 1]
                     else -bid_sz[i - 1])
            e_ask = (ask_sz[i - 1] if ask[i] > ask[i - 1]
                     else ask_sz[i] - ask_sz[i - 1] if ask[i] == ask[i - 1]
                     else -ask_sz[i])
            ofi = (e_bid - e_ask) / max(bid_sz[i] + ask_sz[i], 1e-12)
            path = abs((mid[i] - mid[i - 1]) / mid[i - 1] * 10_000.0)
        ofi_prefix.append(ofi_prefix[-1] + ofi)
        path_prefix.append(path_prefix[-1] + path)
    return Tape(ts, bid, ask, last, mid, obi, ofi_prefix, path_prefix)


def variant_grid(*, directional_only: bool = False) -> list[Variant]:
    variants: list[Variant] = []
    for lookback in (60, 180, 300, 900):
        for horizon in (60, 180, 300, 900):
            for threshold in (1.0, 2.0, 4.0, 8.0):
                variants.append(Variant("momentum", lookback, horizon, threshold))
                variants.append(Variant("reversion", lookback, horizon, threshold))
            for threshold in (0.02, 0.05, 0.10, 0.20):
                variants.append(Variant("ofi_obi", lookback, horizon, threshold))
            for threshold in (1.0, 2.0, 4.0):
                for ofi_threshold in (0.02, 0.08):
                    variants.append(Variant(
                        "hybrid", lookback, horizon, threshold, ofi_threshold))
            for threshold in (1.0, 2.0, 4.0, 8.0):
                variants.append(Variant("regime_switch", lookback, horizon, threshold))
    if not directional_only:
        for horizon in (60, 180, 300, 900):
            for spread_threshold in (4.0, 6.0, 8.0, 10.0, 15.0, 20.0):
                variants.append(Variant("two_sided", 0, horizon, spread_threshold))
    return variants


def _window_features(tape: Tape, i: int, lookback_s: int) -> tuple[float, float, float, float]:
    p = bisect.bisect_left(tape.ts, tape.ts[i] - lookback_s)
    if p >= i or tape.mid[p] <= 0:
        return 0.0, 0.0, 0.0, 0.0
    momentum_bps = (tape.mid[i] / tape.mid[p] - 1.0) * 10_000.0
    count = max(i - p, 1)
    ofi_mean = (tape.ofi_prefix[i + 1] - tape.ofi_prefix[p + 1]) / count
    obi = tape.obi[i]
    path = tape.path_prefix[i + 1] - tape.path_prefix[p + 1]
    efficiency = min(abs(momentum_bps) / path, 1.0) if path > 1e-12 else 0.0
    return momentum_bps, ofi_mean, obi, efficiency


def signal_direction(tape: Tape, i: int, variant: Variant) -> int:
    momentum_bps, ofi_mean, obi, efficiency = _window_features(
        tape, i, variant.lookback_s)
    if variant.family == "momentum":
        return _threshold_sign(momentum_bps, variant.threshold)
    if variant.family == "reversion":
        return -_threshold_sign(momentum_bps, variant.threshold)
    if variant.family == "ofi_obi":
        direction = _threshold_sign(ofi_mean, variant.threshold)
        return direction if direction and direction == _sign(obi) else 0
    if variant.family == "hybrid":
        direction = _threshold_sign(momentum_bps, variant.threshold)
        return direction if (direction and direction == _threshold_sign(
            ofi_mean, variant.ofi_threshold)) else 0
    if variant.family == "regime_switch":
        direction = _threshold_sign(momentum_bps, variant.threshold)
        return direction if efficiency >= 0.35 else -direction
    if variant.family == "two_sided":
        return 0
    raise ValueError(f"unknown family: {variant.family}")


def _threshold_sign(value: float, threshold: float) -> int:
    return _sign(value) if abs(value) >= threshold else 0


def _sign(value: float) -> int:
    return 1 if value > 0 else (-1 if value < 0 else 0)


def sample_indices(tape: Tape, start: float, end: float, interval_s: int) -> list[int]:
    indices: list[int] = []
    i = bisect.bisect_left(tape.ts, start)
    next_ts = start
    while i < len(tape.ts) and tape.ts[i] < end:
        if tape.ts[i] >= next_ts:
            indices.append(i)
            next_ts = tape.ts[i] + interval_s
        i += 1
    return indices


def _maker_fill_index(tape: Tape, i: int, direction: int, window_s: int) -> int | None:
    deadline = tape.ts[i] + window_s
    quote = tape.bid[i] if direction > 0 else tape.ask[i]
    k = i + 1
    while k < len(tape.ts) and tape.ts[k] <= deadline:
        if ((direction > 0 and tape.last[k] <= quote)
                or (direction < 0 and tape.last[k] >= quote)):
            return k
        k += 1
    return None


def ratio_proxy(net_bps: list[float]) -> float | None:
    total = sum(net_bps)
    if total >= 0 or not net_bps:
        return None
    return 20_000.0 * len(net_bps) / -total


def summarize(net_bps: list[float], signals: int, hours: float, ratio_floor: float) -> dict:
    n = len(net_bps)
    total = sum(net_bps)
    avg = total / n if n else 0.0
    sd = statistics.stdev(net_bps) if n >= 2 else 0.0
    se = sd / math.sqrt(n) if n else 0.0
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in net_bps:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    proxy = ratio_proxy(net_bps)
    return {
        "signals": signals,
        "round_trips": n,
        "fill_proxy_rate": round(n / signals, 6) if signals else 0.0,
        "opportunities_per_hour": round(n / max(hours, 1e-9), 6),
        "avg_net_bps": round(avg, 6),
        "sum_net_bps": round(total, 6),
        "win_rate": round(sum(value > 0 for value in net_bps) / n, 6) if n else 0.0,
        "net_bps_lcb95": round(avg - 1.645 * se, 6),
        "max_drawdown_bps": round(max_drawdown, 6),
        "honest_ratio_proxy": round(proxy, 2) if proxy is not None else None,
        "honest_ratio_proxy_infinite": bool(n and proxy is None),
        "meets_ratio_floor": bool(n and (proxy is None or proxy >= ratio_floor)),
    }


def evaluate(
    tape: Tape,
    variant: Variant,
    start: float,
    end: float,
    *,
    sample_s: int,
    fill_window_s: int,
    fee_bps: float,
    adverse_bps: float,
    ratio_floor: float,
) -> EvalResult:
    if variant.family == "two_sided":
        return _evaluate_two_sided(
            tape, variant, start, end, sample_s=sample_s, fee_bps=fee_bps,
            adverse_bps=adverse_bps, ratio_floor=ratio_floor)
    net_values: list[float] = []
    signals = 0
    blocked_until = start
    for i in sample_indices(tape, start, end, sample_s):
        if tape.ts[i] < blocked_until:
            continue
        direction = signal_direction(tape, i, variant)
        if not direction:
            continue
        signals += 1
        fill = _maker_fill_index(tape, i, direction, fill_window_s)
        if fill is None:
            continue
        exit_i = bisect.bisect_left(tape.ts, tape.ts[fill] + variant.horizon_s)
        if exit_i >= len(tape.ts) or tape.ts[exit_i] >= end:
            continue
        if direction > 0:
            gross = (tape.bid[exit_i] - tape.bid[i]) / tape.mid[i] * 10_000.0
        else:
            gross = (tape.ask[i] - tape.ask[exit_i]) / tape.mid[i] * 10_000.0
        net_values.append(gross - fee_bps - adverse_bps)
        blocked_until = tape.ts[exit_i]
    hours = max((end - start) / 3600.0, 1e-9)
    return EvalResult(summarize(net_values, signals, hours, ratio_floor), net_values)


def _evaluate_two_sided(
    tape: Tape,
    variant: Variant,
    start: float,
    end: float,
    *,
    sample_s: int,
    fee_bps: float,
    adverse_bps: float,
    ratio_floor: float,
) -> EvalResult:
    """Paired quote replay: both fills capture spread; orphan inventory is flattened."""
    net_values: list[float] = []
    signals = 0
    paired = 0
    orphan = 0
    blocked_until = start
    for i in sample_indices(tape, start, end, sample_s):
        if tape.ts[i] < blocked_until:
            continue
        spread_bps = (tape.ask[i] - tape.bid[i]) / tape.mid[i] * 10_000.0
        if spread_bps < variant.threshold:
            continue
        signals += 1
        close_at = tape.ts[i] + variant.horizon_s
        k = i + 1
        bid_touched = False
        ask_touched = False
        while k < len(tape.ts) and tape.ts[k] <= close_at:
            bid_touched = bid_touched or tape.last[k] <= tape.bid[i]
            ask_touched = ask_touched or tape.last[k] >= tape.ask[i]
            if bid_touched and ask_touched:
                break
            k += 1
        exit_i = bisect.bisect_left(tape.ts, close_at)
        if exit_i >= len(tape.ts) or tape.ts[exit_i] >= end:
            continue
        if bid_touched and ask_touched:
            gross = spread_bps
            paired += 1
        elif bid_touched:
            gross = (tape.bid[exit_i] - tape.bid[i]) / tape.mid[i] * 10_000.0
            orphan += 1
        elif ask_touched:
            gross = (tape.ask[i] - tape.ask[exit_i]) / tape.mid[i] * 10_000.0
            orphan += 1
        else:
            blocked_until = tape.ts[exit_i]
            continue
        net_values.append(gross - fee_bps - adverse_bps)
        blocked_until = tape.ts[exit_i]
    hours = max((end - start) / 3600.0, 1e-9)
    metrics = summarize(net_values, signals, hours, ratio_floor)
    metrics["paired_fills"] = paired
    metrics["orphan_fills"] = orphan
    metrics["paired_share"] = round(paired / len(net_values), 6) if net_values else 0.0
    return EvalResult(metrics, net_values)


def chronological_windows(tape: Tape, embargo_s: int = 60) -> dict[str, tuple[float, float]]:
    start, end = tape.ts[0], tape.ts[-1]
    span = end - start
    b1 = start + span * 0.50
    b2 = start + span * 0.75
    return {
        "train": (start, b1 - embargo_s),
        "validation": (b1 + embargo_s, b2 - embargo_s),
        "oos": (b2 + embargo_s, end),
    }


def selection_score(metrics: dict) -> float:
    if metrics["round_trips"] < 8 or not metrics["meets_ratio_floor"]:
        return -math.inf
    return metrics["net_bps_lcb95"] + 0.15 * math.log1p(
        metrics["opportunities_per_hour"])


def sign_flip_pvalue(values: list[float], seed: str, iterations: int = 999) -> float:
    if not values or statistics.fmean(values) <= 0:
        return 1.0
    # Flip contiguous blocks, not individual RTs, so serially correlated fills do
    # not create artificial significance. sqrt(n) is conservative for this 24h tape.
    block_size = max(1, round(math.sqrt(len(values))))
    blocks = [sum(values[i:i + block_size])
              for i in range(0, len(values), block_size)]
    observed = sum(blocks)
    rng = random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16))
    exceed = 0
    for _ in range(iterations):
        trial = sum(value if rng.random() < 0.5 else -value for value in blocks)
        exceed += trial >= observed
    return (exceed + 1) / (iterations + 1)


def benjamini_hochberg(pvalues: list[float]) -> list[float]:
    n = len(pvalues)
    order = sorted(range(n), key=lambda i: pvalues[i])
    adjusted = [1.0] * n
    running = 1.0
    for rank_index in range(n - 1, -1, -1):
        original_i = order[rank_index]
        rank = rank_index + 1
        running = min(running, pvalues[original_i] * n / rank)
        adjusted[original_i] = min(running, 1.0)
    return adjusted


def _eval_kwargs(args: argparse.Namespace) -> dict:
    return {
        "sample_s": args.sample_seconds,
        "fill_window_s": args.fill_window_seconds,
        "fee_bps": args.fee_bps,
        "adverse_bps": args.adverse_bps,
        "ratio_floor": args.ratio_floor,
    }


def search_symbol(symbol: str, tape: Tape, args: argparse.Namespace) -> dict | None:
    if len(tape.ts) < 100:
        return None
    windows = chronological_windows(tape, args.embargo_seconds)
    trained: list[tuple[float, Variant, EvalResult]] = []
    for variant in variant_grid(directional_only=args.directional_only):
        result = evaluate(tape, variant, *windows["train"], **_eval_kwargs(args))
        trained.append((selection_score(result.metrics), variant, result))
    trained.sort(key=lambda row: row[0], reverse=True)

    # Validation may select among a small, train-ranked shortlist; OOS remains sealed.
    shortlist = [row for row in trained[:args.validation_shortlist] if math.isfinite(row[0])]
    if not shortlist:
        return None
    validated: list[tuple[float, Variant, EvalResult, EvalResult]] = []
    for _, variant, train in shortlist:
        validation = evaluate(
            tape, variant, *windows["validation"], **_eval_kwargs(args))
        coherence = min(train.metrics["avg_net_bps"], validation.metrics["avg_net_bps"])
        score = coherence + 0.10 * math.log1p(
            validation.metrics["opportunities_per_hour"])
        if validation.metrics["round_trips"] < 4:
            score = -math.inf
        validated.append((score, variant, train, validation))
    validated.sort(key=lambda row: row[0], reverse=True)
    _, variant, train, validation = validated[0]
    oos = evaluate(tape, variant, *windows["oos"], **_eval_kwargs(args))
    pvalue = sign_flip_pvalue(oos.net_bps, f"{symbol}:{variant}")
    momentum_bps, ofi_mean, obi, efficiency = _window_features(
        tape, len(tape.ts) - 1, variant.lookback_s)
    current_direction = signal_direction(tape, len(tape.ts) - 1, variant)
    return {
        "symbol": symbol,
        "variant": asdict(variant),
        "train": train.metrics,
        "validation": validation.metrics,
        "oos": oos.metrics,
        "oos_pvalue": round(pvalue, 6),
        "current_signal": {
            "direction": "BUY" if current_direction > 0 else "SELL" if current_direction < 0 else "WAIT",
            "horizon_seconds": variant.horizon_s,
            "lookback_seconds": variant.lookback_s,
            "mid": round(tape.mid[-1], 10),
            "spread_bps": round((tape.ask[-1] - tape.bid[-1]) / tape.mid[-1] * 10_000.0, 6),
            "momentum_bps": round(momentum_bps, 6),
            "ofi_mean": round(ofi_mean, 6),
            "obi": round(obi, 6),
            "path_efficiency": round(efficiency, 6),
            "asof_ts": tape.ts[-1],
        },
        "selected_before_oos": True,
        "windows": {name: [start, end] for name, (start, end) in windows.items()},
    }


def _promotion_reasons(row: dict, args: argparse.Namespace) -> list[str]:
    reasons: list[str] = []
    for split, minimum in (("train", 8), ("validation", 4), ("oos", 4)):
        if row[split]["round_trips"] < minimum:
            reasons.append(f"{split}_sample")
    if row["validation"]["avg_net_bps"] <= 0:
        reasons.append("validation_expectancy")
    if row["validation"]["net_bps_lcb95"] <= 0:
        reasons.append("validation_lcb")
    if row["oos"]["avg_net_bps"] <= 0:
        reasons.append("oos_expectancy")
    if row["oos"]["net_bps_lcb95"] <= 0:
        reasons.append("oos_lcb")
    if not row["oos"]["meets_ratio_floor"]:
        reasons.append("ratio_floor")
    if row["oos"]["opportunities_per_hour"] < args.min_opportunities_per_hour:
        reasons.append("throughput")
    if row["oos"]["fill_proxy_rate"] < args.min_fill_proxy_rate:
        reasons.append("fill_proxy")
    if row["oos"]["max_drawdown_bps"] > _max_drawdown_gate(args):
        reasons.append("drawdown")
    if row.get("oos_fdr_qvalue", 1.0) > args.max_fdr:
        reasons.append("multiple_testing")
    return reasons


def _max_drawdown_gate(args: argparse.Namespace) -> float:
    if args.max_oos_drawdown_bps > 0:
        return args.max_oos_drawdown_bps
    return args.shadow_loss_cap_usd / args.shadow_notional_usd * 10_000.0


def run(args: argparse.Namespace) -> dict:
    started = time.monotonic()
    db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    symbols = [row[0] for row in db.execute(
        "SELECT symbol FROM l1 GROUP BY symbol ORDER BY symbol")]
    if args.max_symbols:
        symbols = symbols[:args.max_symbols]
    results: list[dict] = []
    for symbol in symbols:
        rows = db.execute(
            "SELECT ts,bid,ask,bid_sz,ask_sz,last FROM l1 "
            "WHERE symbol=? ORDER BY ts", (symbol,)).fetchall()
        result = search_symbol(symbol, build_tape(rows), args)
        if result:
            results.append(result)
    db.close()

    qvalues = benjamini_hochberg([row["oos_pvalue"] for row in results])
    for row, qvalue in zip(results, qvalues):
        row["oos_fdr_qvalue"] = round(qvalue, 6)
        reasons = _promotion_reasons(row, args)
        row["shadow_eligible"] = not reasons
        row["rejection_reasons"] = reasons
    results.sort(key=lambda row: (
        not row["shadow_eligible"],
        -row["oos"]["opportunities_per_hour"],
        -row["oos"]["avg_net_bps"],
    ))
    eligible = [row for row in results if row["shadow_eligible"]]
    now = datetime.now(timezone.utc).isoformat()
    report = {
        "schema_version": 1,
        "created_at": now,
        "mode": "READ_ONLY_REPLAY_NO_ORDER_PATH",
        "baseline": {"name": "active_selector_wait", "opportunities_per_hour": 0.0},
        "data": {"db": str(args.db), "symbols_scanned": len(symbols)},
        "search": {
            "variants_per_symbol": len(variant_grid(directional_only=args.directional_only)),
            "directional_only": args.directional_only,
            "horizons_seconds": [60, 180, 300, 900],
            "validation_shortlist": args.validation_shortlist,
            "oos_significance": "sqrt(n) contiguous-block sign-flip + BH FDR",
            "split": "50% train / 25% validation / 25% sealed OOS",
            "embargo_seconds": args.embargo_seconds,
            "sample_seconds": args.sample_seconds,
        },
        "cost_model": {
            "maker_entry_fill": "later last-price touch within fill window",
            "exit": "executable L1 side",
            "fee_bps_round_trip": args.fee_bps,
            "adverse_selection_bps": args.adverse_bps,
            "fill_window_seconds": args.fill_window_seconds,
        },
        "gates": {
            "honest_ratio_floor": args.ratio_floor,
            "min_opportunities_per_hour": args.min_opportunities_per_hour,
            "min_fill_proxy_rate": args.min_fill_proxy_rate,
            "max_oos_drawdown_bps": round(_max_drawdown_gate(args), 6),
            "shadow_notional_usd": args.shadow_notional_usd,
            "shadow_loss_cap_usd": args.shadow_loss_cap_usd,
            "max_fdr": args.max_fdr,
        },
        "scientific_limits": [
            "L1 last-price touch is a fill proxy; queue position is unknown.",
            "Only 24h of one market regime is available.",
            "Shadow evidence is mandatory before any live promotion.",
        ],
        "shadow_watchlist": [{
            "symbol": row["symbol"],
            "variant": row["variant"],
            "current_signal": row["current_signal"],
            "oos": row["oos"],
            "oos_fdr_qvalue": row["oos_fdr_qvalue"],
        } for row in eligible[:args.watchlist_size]],
        "eligible_count": len(eligible),
        "results": results,
        "runtime_seconds": round(time.monotonic() - started, 3),
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    latest = args.out_dir / "latest.json"
    tmp = latest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, indent=2) + "\n")
    tmp.replace(latest)
    ledger = args.out_dir / "decision_ledger.jsonl"
    with ledger.open("a") as handle:
        handle.write(json.dumps({
            "ts": now,
            "kind": "opportunity_search",
            "dataset": str(args.db),
            "symbols": len(symbols),
            "variants_per_symbol": len(variant_grid(directional_only=args.directional_only)),
            "directional_only": args.directional_only,
            "eligible_count": len(eligible),
            "watchlist": [row["symbol"] for row in eligible[:args.watchlist_size]],
            "runtime_seconds": report["runtime_seconds"],
        }) + "\n")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--max-symbols", type=int, default=0)
    parser.add_argument("--sample-seconds", type=int, default=15)
    parser.add_argument("--fill-window-seconds", type=int, default=15)
    parser.add_argument("--fee-bps", type=float, default=4.68,
                        help="Round-trip fee; default is maker entry 1.08 + taker exit 3.60 bps")
    parser.add_argument("--adverse-bps", type=float, default=1.0)
    parser.add_argument("--ratio-floor", type=float, default=6300.0)
    parser.add_argument("--embargo-seconds", type=int, default=60)
    parser.add_argument("--validation-shortlist", type=int, default=8)
    parser.add_argument("--min-opportunities-per-hour", type=float, default=0.5)
    parser.add_argument("--min-fill-proxy-rate", type=float, default=0.10)
    parser.add_argument("--max-oos-drawdown-bps", type=float, default=0.0,
                        help="0 derives the gate from shadow loss cap / notional")
    parser.add_argument("--shadow-notional-usd", type=float, default=60.0)
    parser.add_argument("--shadow-loss-cap-usd", type=float, default=4.0)
    parser.add_argument("--max-fdr", type=float, default=0.10)
    parser.add_argument("--watchlist-size", type=int, default=5)
    parser.add_argument("--directional-only", action="store_true",
                        help="Search BUY/SELL opportunity families only")
    return parser.parse_args()


if __name__ == "__main__":
    result = run(parse_args())
    print(json.dumps({
        "mode": result["mode"],
        "symbols_scanned": result["data"]["symbols_scanned"],
        "eligible_count": result["eligible_count"],
        "shadow_watchlist": result["shadow_watchlist"],
        "runtime_seconds": result["runtime_seconds"],
    }, indent=2))
