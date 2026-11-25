#!/usr/bin/env python3
"""Read-only multi-timeframe directional scalp research for SoDEX.

Builds one-minute bars from recorded L1 snapshots, fits pooled chronological
models for 1/3/5/15-minute forward returns, and evaluates executable BUY/SELL
PnL after bid/ask spread plus two taker fees. It has no exchange or order path.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

try:
    from sklearn.ensemble import HistGradientBoostingRegressor as _HGBR
except ImportError:  # sklearn not installed in system Python; only needed in run()
    _HGBR = None  # type: ignore[assignment,misc]


PROJECT = Path(__file__).resolve().parents[1]
DB = PROJECT / "data" / "sodex_book_recorder.db"
OUTPUT = PROJECT / "data" / "sodex_mtf_scalp_lab" / "latest.json"
HORIZONS = (1, 3, 5, 15)
FEATURE_NAMES = (
    "return_1m_bps", "return_3m_bps", "return_5m_bps", "return_15m_bps",
    "realized_vol_5m_bps", "realized_vol_15m_bps", "path_efficiency_15m",
    "obi", "obi_mean_5m", "obi_delta_5m", "spread_bps",
    "spread_mean_5m_bps", "log_depth_usd", "minute_range_bps",
)


@dataclass(frozen=True)
class Bar:
    ts: int
    bid: float
    ask: float
    mid: float
    obi: float
    spread_bps: float
    depth_usd: float
    range_bps: float


@dataclass(frozen=True)
class Sample:
    symbol: str
    ts: int
    features: tuple[float, ...]
    future_return_bps: float
    long_net_bps: float
    short_net_bps: float
    estimated_cost_bps: float


def bars_from_rows(rows: list[tuple[Any, ...]]) -> list[Bar]:
    buckets: dict[int, list[tuple[float, float, float, float]]] = {}
    for raw_ts, raw_bid, raw_ask, raw_bid_sz, raw_ask_sz in rows:
        ts, bid, ask = float(raw_ts), float(raw_bid), float(raw_ask)
        if ts <= 0 or bid <= 0 or ask <= bid:
            continue
        mid = (bid + ask) / 2.0
        total_sz = max(float(raw_bid_sz), 0.0) + max(float(raw_ask_sz), 0.0)
        obi = ((max(float(raw_bid_sz), 0.0) - max(float(raw_ask_sz), 0.0)) /
               total_sz if total_sz else 0.0)
        depth = min(max(float(raw_bid_sz), 0.0) * bid,
                    max(float(raw_ask_sz), 0.0) * ask)
        buckets.setdefault(int(ts) // 60 * 60, []).append((bid, ask, obi, depth))
    bars: list[Bar] = []
    for minute in sorted(buckets):
        values = buckets[minute]
        bid, ask, _, _ = values[-1]
        mid = (bid + ask) / 2.0
        mids = [(row[0] + row[1]) / 2.0 for row in values]
        bars.append(Bar(
            ts=minute,
            bid=bid,
            ask=ask,
            mid=mid,
            obi=statistics.fmean(row[2] for row in values),
            spread_bps=(ask - bid) / mid * 10_000.0,
            depth_usd=statistics.fmean(row[3] for row in values),
            range_bps=(max(mids) - min(mids)) / mid * 10_000.0,
        ))
    return bars


def _return_bps(bars: list[Bar], i: int, lookback: int) -> float:
    return (bars[i].mid / bars[i - lookback].mid - 1.0) * 10_000.0


def feature_vector(bars: list[Bar], i: int) -> tuple[float, ...]:
    returns_1m = [_return_bps(bars, j, 1) for j in range(i - 14, i + 1)]
    path = sum(abs(value) for value in returns_1m)
    ret15 = _return_bps(bars, i, 15)
    obi5 = [bars[j].obi for j in range(i - 4, i + 1)]
    spreads5 = [bars[j].spread_bps for j in range(i - 4, i + 1)]
    return (
        _return_bps(bars, i, 1),
        _return_bps(bars, i, 3),
        _return_bps(bars, i, 5),
        ret15,
        statistics.pstdev(returns_1m[-5:]),
        statistics.pstdev(returns_1m),
        min(abs(ret15) / path, 1.0) if path else 0.0,
        bars[i].obi,
        statistics.fmean(obi5),
        bars[i].obi - obi5[0],
        bars[i].spread_bps,
        statistics.fmean(spreads5),
        math.log1p(max(bars[i].depth_usd, 0.0)),
        bars[i].range_bps,
    )


def executable_net_bps(entry: Bar, exit_bar: Bar, taker_fee_bps: float) -> tuple[float, float]:
    fee = 2.0 * taker_fee_bps
    long_net = (exit_bar.bid / entry.ask - 1.0) * 10_000.0 - fee
    short_net = (entry.bid - exit_bar.ask) / entry.bid * 10_000.0 - fee
    return long_net, short_net


def samples_for_horizon(symbol: str, bars: list[Bar], horizon: int,
                        taker_fee_bps: float) -> list[Sample]:
    out: list[Sample] = []
    for i in range(15, len(bars) - horizon):
        if bars[i + horizon].ts - bars[i].ts > (horizon + 1) * 60:
            continue
        long_net, short_net = executable_net_bps(bars[i], bars[i + horizon], taker_fee_bps)
        out.append(Sample(
            symbol=symbol,
            ts=bars[i].ts,
            features=feature_vector(bars, i),
            future_return_bps=(bars[i + horizon].mid / bars[i].mid - 1.0) * 10_000.0,
            long_net_bps=long_net,
            short_net_bps=short_net,
            estimated_cost_bps=bars[i].spread_bps + 2.0 * taker_fee_bps,
        ))
    return out


def summarize(values: list[float], hours: float, ratio_floor: float,
              notional_usd: float) -> dict[str, Any]:
    n = len(values)
    avg = statistics.fmean(values) if values else 0.0
    sd = statistics.stdev(values) if n >= 2 else 0.0
    lcb = avg - 1.645 * sd / math.sqrt(n) if n else float("-inf")
    total = sum(values)
    ratio = 20_000.0 * n / -total if n and total < 0 else None
    return {
        "round_trips": n,
        "avg_net_bps": round(avg, 6),
        "net_bps_lcb95": round(lcb, 6) if n else None,
        "sum_net_bps": round(total, 6),
        "win_rate": round(sum(value > 0 for value in values) / n, 6) if n else 0.0,
        "honest_ratio_proxy": round(ratio, 2) if ratio is not None else None,
        "honest_ratio_proxy_infinite": bool(n and ratio is None),
        "meets_ratio_floor": bool(n and (ratio is None or ratio >= ratio_floor)),
        "round_trips_per_hour": round(n / max(hours, 1e-9), 6),
        "volume_per_hour_usd": round(2 * notional_usd * n / max(hours, 1e-9), 2),
    }


def non_overlapping_values(samples: list[Sample], predictions: np.ndarray,
                           threshold: float, horizon: int) -> tuple[list[float], list[tuple[Sample, float, float]]]:
    chosen: list[float] = []
    details: list[tuple[Sample, float, float]] = []
    blocked: dict[str, int] = {}
    ordered = sorted(zip(samples, predictions), key=lambda row: (row[0].ts, row[0].symbol))
    for sample, prediction in ordered:
        predicted_edge = abs(float(prediction)) - sample.estimated_cost_bps
        if predicted_edge < threshold or sample.ts < blocked.get(sample.symbol, 0):
            continue
        net = sample.long_net_bps if prediction > 0 else sample.short_net_bps
        chosen.append(net)
        details.append((sample, float(prediction), net))
        blocked[sample.symbol] = sample.ts + horizon * 60
    return chosen, details


def select_threshold(samples: list[Sample], predictions: np.ndarray, horizon: int,
                     ratio_floor: float, notional_usd: float, hours: float) -> tuple[float, dict]:
    margins = np.asarray([
        abs(float(prediction)) - sample.estimated_cost_bps
        for sample, prediction in zip(samples, predictions)
    ])
    candidates = sorted(set(max(0.0, float(np.quantile(margins, q)))
                            for q in (0.70, 0.80, 0.85, 0.90, 0.95, 0.975, 0.99)))
    ranked: list[tuple[float, float, dict]] = []
    for threshold in candidates:
        values, _ = non_overlapping_values(samples, predictions, threshold, horizon)
        metrics = summarize(values, hours, ratio_floor, notional_usd)
        score = (-math.inf if metrics["round_trips"] < 30 else
                 metrics["net_bps_lcb95"] + 0.05 * math.log1p(metrics["round_trips_per_hour"]))
        ranked.append((score, threshold, metrics))
    ranked.sort(reverse=True)
    _, threshold, metrics = ranked[0]
    return threshold, metrics


def _split(samples: list[Sample], train_end: int, validation_end: int,
           horizon: int) -> tuple[list[Sample], list[Sample], list[Sample]]:
    embargo = horizon * 60
    train = [row for row in samples if row.ts + embargo < train_end]
    validation = [row for row in samples if train_end + embargo <= row.ts
                  and row.ts + embargo < validation_end]
    oos = [row for row in samples if row.ts >= validation_end + embargo]
    return train, validation, oos


def _matrix(samples: list[Sample]) -> tuple[np.ndarray, np.ndarray]:
    return (np.asarray([row.features for row in samples], dtype=float),
            np.clip(np.asarray([row.future_return_bps for row in samples], dtype=float), -200.0, 200.0))


def run(args: argparse.Namespace) -> dict[str, Any]:
    if _HGBR is None:
        raise ImportError(
            "scikit-learn is required for run(). "
            "Install it in the research venv: pip install scikit-learn"
        )
    started = time.monotonic()
    db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    bounds = db.execute("SELECT MIN(ts),MAX(ts) FROM l1").fetchone()
    start_ts, end_ts = int(bounds[0]), int(bounds[1])
    train_end = int(start_ts + (end_ts - start_ts) * 0.50)
    validation_end = int(start_ts + (end_ts - start_ts) * 0.75)
    bars_by_symbol: dict[str, list[Bar]] = {}
    for (symbol,) in db.execute("SELECT DISTINCT symbol FROM l1 ORDER BY symbol"):
        rows = db.execute(
            "SELECT ts,bid,ask,bid_sz,ask_sz FROM l1 WHERE symbol=? ORDER BY ts", (symbol,)
        ).fetchall()
        bars = bars_from_rows(rows)
        if len(bars) >= args.min_bars:
            bars_by_symbol[str(symbol)] = bars
    db.close()

    horizon_reports: list[dict[str, Any]] = []
    current_candidates: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        samples = [sample for symbol, bars in bars_by_symbol.items()
                   for sample in samples_for_horizon(symbol, bars, horizon, args.taker_fee_bps)]
        train, validation, oos = _split(samples, train_end, validation_end, horizon)
        x_train, y_train = _matrix(train)
        model = _HGBR(
            max_iter=args.max_iter, max_leaf_nodes=15, learning_rate=0.06,
            min_samples_leaf=100, l2_regularization=2.0, random_state=42,
        )
        model.fit(x_train, y_train)
        validation_pred = model.predict(_matrix(validation)[0])
        validation_hours = max((validation_end - train_end) / 3600.0, 1e-9)
        threshold, validation_metrics = select_threshold(
            validation, validation_pred, horizon, args.ratio_floor,
            args.notional_usd, validation_hours)
        oos_pred = model.predict(_matrix(oos)[0])
        oos_hours = max((end_ts - validation_end) / 3600.0, 1e-9)
        oos_values, oos_details = non_overlapping_values(oos, oos_pred, threshold, horizon)
        oos_metrics = summarize(oos_values, oos_hours, args.ratio_floor, args.notional_usd)

        asset_metrics: list[dict[str, Any]] = []
        for symbol in bars_by_symbol:
            values = [net for sample, _, net in oos_details if sample.symbol == symbol]
            metrics = summarize(values, oos_hours, args.ratio_floor, args.notional_usd)
            if values:
                asset_metrics.append({"symbol": symbol, **metrics})
        asset_metrics.sort(key=lambda row: (row["net_bps_lcb95"] or -math.inf), reverse=True)

        model_gate = bool(
            validation_metrics["round_trips"] >= 30
            and validation_metrics["net_bps_lcb95"] > 0
            and oos_metrics["round_trips"] >= 30
            and oos_metrics["net_bps_lcb95"] > 0
            and oos_metrics["meets_ratio_floor"]
        )
        for symbol, bars in bars_by_symbol.items():
            prediction = float(model.predict(np.asarray([feature_vector(bars, len(bars) - 1)]))[0])
            estimated_cost = bars[-1].spread_bps + 2 * args.taker_fee_bps
            asset = next((row for row in asset_metrics if row["symbol"] == symbol), None)
            asset_gate = bool(asset and asset["round_trips"] >= 8
                              and asset["net_bps_lcb95"] > 0
                              and asset["meets_ratio_floor"])
            predicted_margin = abs(prediction) - estimated_cost
            research_direction = (("BUY" if prediction > 0 else "SELL")
                                  if predicted_margin >= threshold else "WAIT")
            trade_ready = bool(research_direction != "WAIT" and model_gate and asset_gate
                               and predicted_margin >= threshold)
            current_candidates.append({
                "symbol": symbol,
                "horizon_minutes": horizon,
                "decision": research_direction if trade_ready else "WAIT",
                "research_direction": research_direction,
                "predicted_mid_move_bps": round(prediction, 6),
                "minimum_predicted_edge_margin_bps": round(threshold, 6),
                "estimated_taker_roundtrip_cost_bps": round(estimated_cost, 6),
                "expected_margin_over_current_cost_bps": round(predicted_margin, 6),
                "model_gate_pass": model_gate,
                "asset_oos_gate_pass": asset_gate,
                "trade_ready": trade_ready,
                "asset_oos": asset,
                "asof_ts": bars[-1].ts,
            })
        horizon_reports.append({
            "horizon_minutes": horizon,
            "train_samples": len(train),
            "validation_samples": len(validation),
            "oos_samples": len(oos),
            "selected_minimum_predicted_edge_margin_bps": round(threshold, 6),
            "validation": validation_metrics,
            "oos": oos_metrics,
            "model_gate_pass": model_gate,
            "top_assets_oos": asset_metrics[:10],
        })

    current_candidates.sort(key=lambda row: (
        not row["trade_ready"], not row["model_gate_pass"],
        -row["expected_margin_over_current_cost_bps"]),
    )
    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY_MTF_DIRECTIONAL_SCALP_NO_ORDER_PATH",
        "method": "CAMEO_SCALP_COST_AWARE_MTF_EDGE_AND_OPPORTUNITY",
        "data": {
            "db": str(args.db), "symbols": len(bars_by_symbol),
            "start_ts": start_ts, "end_ts": end_ts,
            "split": "50% train / 25% validation / 25% sealed OOS",
        },
        "execution_stress": {
            "entry": "taker at executable bid/ask",
            "exit": "taker at executable bid/ask",
            "taker_fee_bps_per_leg": args.taker_fee_bps,
            "ratio_floor": args.ratio_floor,
            "notional_usd": args.notional_usd,
        },
        "features": list(FEATURE_NAMES),
        "horizons": horizon_reports,
        "trade_ready_count": sum(row["trade_ready"] for row in current_candidates),
        "current_ranked": current_candidates[:40],
        "promotion_allowed": False,
        "scientific_limits": [
            "Only about 24 hours and one market regime are available.",
            "Asset gates are descriptive OOS screens and require fresh forward validation.",
            "A positive model prediction is not an order authorization.",
        ],
        "runtime_seconds": round(time.monotonic() - started, 3),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2) + "\n")
    tmp.replace(args.output)
    ledger = args.output.parent / "decision_ledger.jsonl"
    with ledger.open("a") as handle:
        handle.write(json.dumps({
            "created_at": report["created_at"],
            "method": report["method"],
            "symbols": report["data"]["symbols"],
            "trade_ready_count": report["trade_ready_count"],
            "horizons": [{
                "minutes": row["horizon_minutes"],
                "model_gate_pass": row["model_gate_pass"],
                "validation_lcb95": row["validation"]["net_bps_lcb95"],
                "oos_lcb95": row["oos"]["net_bps_lcb95"],
            } for row in horizon_reports],
        }, sort_keys=True) + "\n")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--taker-fee-bps", type=float, default=3.6)
    parser.add_argument("--ratio-floor", type=float, default=4500.0)
    parser.add_argument("--notional-usd", type=float, default=20.0)
    parser.add_argument("--min-bars", type=int, default=1000)
    parser.add_argument("--max-iter", type=int, default=150)
    return parser.parse_args()


def main() -> int:
    report = run(parse_args())
    print(json.dumps({
        "mode": report["mode"],
        "symbols": report["data"]["symbols"],
        "trade_ready_count": report["trade_ready_count"],
        "horizons": [{
            "minutes": row["horizon_minutes"],
            "model_gate_pass": row["model_gate_pass"],
            "validation_lcb95": row["validation"]["net_bps_lcb95"],
            "oos_lcb95": row["oos"]["net_bps_lcb95"],
        } for row in report["horizons"]],
        "top_current": report["current_ranked"][:10],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
