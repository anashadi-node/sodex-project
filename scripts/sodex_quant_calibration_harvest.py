#!/usr/bin/env python3
"""Read-only calibration harvester for the SoDEX Quant Engine.

This tool answers ONE scientific question honestly: when the seven-signal TA
gate says P(SHORT)=x, does price actually fall x-fraction of the time over the
forecast horizon?

It is a TRUTH-TELLER, not an edge-maker. It never trades, never touches the
exchange, never reads secrets. It only pairs each historical Quant-Engine
forecast (data/sodex_quant_stat/history.jsonl) with the *realized* mid-price
move measured from the public market scan (data/sodex_market_scan/history.jsonl),
then writes clean (probability, outcome) rows to a calibration store that the
engine consumes to grow calibration_n from empirical evidence.

Why realized PRICE and not round-trip PnL: a maker round trip is dominated by
fees (Jul-17 post-mortem: 87% of loss was fee, gross price move ~flat). PnL is
therefore the WRONG outcome variable for calibrating a *directional* probability
— it would calibrate execution cost, not the signal. Realized price direction
isolates the actual forecast skill.

Semantics: run_engine() always evaluates the gate with side="sell", so the
stored prob_direction == short_probability == P(price falls). Hence:
    outcome = 1  iff  realized_return < 0   (SHORT was correct)
    outcome = 0  iff  realized_return > 0   (SHORT was wrong)
Near-flat moves (|return| <= deadband) are microstructure coin-flips and are
excluded from the primary set (reported separately as robustness).

Policy: READ_ONLY. No orders, no cancels, no service restart, no .env read.
"""
from __future__ import annotations

import argparse
import bisect
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from anantara import calibration  # noqa: E402
from scripts.sodex_quant_stat_engine import read_jsonl  # noqa: E402


MODE = "READ_ONLY_SODEX_QUANT_CALIBRATION_HARVEST"
POLICY = "no orders, no cancels, no leverage change, no service restart, no secrets"
DEFAULT_QUANT_HISTORY = PROJECT / "data" / "sodex_quant_stat" / "history.jsonl"
DEFAULT_MARKET_HISTORY = PROJECT / "data" / "sodex_market_scan" / "history.jsonl"
DEFAULT_OUTCOME_STORE = PROJECT / "data" / "sodex_quant_calibration.jsonl"
DEFAULT_SUMMARY = PROJECT / "data" / "sodex_quant_calibration_summary.json"

# Pre-registered analysis parameters (fixed before looking at results).
PRIMARY_HORIZON_MIN = 30
ROBUSTNESS_HORIZONS_MIN = (15, 60)
MATCH_TOLERANCE_SEC = 180      # nearest price snapshot must be within this window
DEADBAND_BPS = 5.0             # |return| <= 5bps treated as flat/noise (excluded from primary)


def _parse_ts(value: Any) -> float | None:
    """Parse an ISO-8601 timestamp to epoch seconds (UTC)."""
    if not value:
        return None
    text = str(value)
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _mid_of(row: dict[str, Any]) -> float | None:
    """Extract a usable mid price from a market-scan ticker row."""
    for key in ("mid", "last"):
        v = row.get(key)
        try:
            if v is not None:
                f = float(v)
                if f > 0:
                    return f
        except (TypeError, ValueError):
            continue
    bid = row.get("bid")
    ask = row.get("ask")
    try:
        if bid is not None and ask is not None:
            m = (float(bid) + float(ask)) / 2.0
            if m > 0:
                return m
    except (TypeError, ValueError):
        pass
    return None


def build_price_index(
    market_history: Path,
    *,
    limit: int | None = None,
) -> dict[str, tuple[list[float], list[float]]]:
    """Build per-symbol (sorted epochs, mids) timelines from public market scans."""
    tmp: dict[str, dict[float, float]] = {}
    for scan in read_jsonl(market_history, limit=limit):
        ts = _parse_ts(scan.get("ts"))
        if ts is None:
            continue
        for section in ("short_watch", "top_gainers", "top_losers"):
            rows = scan.get(section)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                symbol = row.get("symbol")
                mid = _mid_of(row)
                if not symbol or mid is None:
                    continue
                tmp.setdefault(str(symbol), {})[ts] = mid
    index: dict[str, tuple[list[float], list[float]]] = {}
    for symbol, series in tmp.items():
        epochs = sorted(series)
        index[symbol] = (epochs, [series[e] for e in epochs])
    return index


def price_at(
    timeline: tuple[list[float], list[float]] | None,
    target_epoch: float,
    *,
    tolerance_sec: float = MATCH_TOLERANCE_SEC,
) -> float | None:
    """Return the mid price nearest to target_epoch within tolerance, else None."""
    if not timeline:
        return None
    epochs, mids = timeline
    if not epochs:
        return None
    idx = bisect.bisect_left(epochs, target_epoch)
    best: tuple[float, float] | None = None  # (distance, mid)
    for j in (idx - 1, idx, idx + 1):
        if 0 <= j < len(epochs):
            dist = abs(epochs[j] - target_epoch)
            if best is None or dist < best[0]:
                best = (dist, mids[j])
    if best is None or best[0] > tolerance_sec:
        return None
    return best[1]


def iter_forecasts(quant_history: Path, *, limit: int | None = None):
    """Yield (ts_epoch, symbol, prob_short) for every logged Quant-Engine forecast."""
    for entry in read_jsonl(quant_history, limit=limit):
        ts = _parse_ts(entry.get("ts"))
        if ts is None:
            continue
        for dec in entry.get("decisions", []):
            if not isinstance(dec, dict):
                continue
            symbol = dec.get("symbol")
            prob = dec.get("prob_direction")
            side = dec.get("side")
            if not symbol or prob is None:
                continue
            try:
                p = float(prob)
            except (TypeError, ValueError):
                continue
            if not (0.0 < p < 1.0):
                continue
            # run_engine always uses side="sell"; prob is P(SHORT). Guard anyway.
            if side is not None and str(side).lower() not in ("sell", "short"):
                continue
            yield ts, str(symbol), p


def harvest_rows(
    *,
    quant_history: Path = DEFAULT_QUANT_HISTORY,
    market_history: Path = DEFAULT_MARKET_HISTORY,
    horizon_min: int = PRIMARY_HORIZON_MIN,
    tolerance_sec: float = MATCH_TOLERANCE_SEC,
    deadband_bps: float = DEADBAND_BPS,
    price_index: dict[str, tuple[list[float], list[float]]] | None = None,
) -> list[dict[str, Any]]:
    """Pair each forecast with its realized directional outcome at a horizon."""
    index = price_index if price_index is not None else build_price_index(market_history)
    horizon_sec = horizon_min * 60.0
    deadband = deadband_bps / 10000.0
    rows: list[dict[str, Any]] = []
    for ts, symbol, prob_short in iter_forecasts(quant_history):
        timeline = index.get(symbol)
        price_now = price_at(timeline, ts, tolerance_sec=tolerance_sec)
        price_future = price_at(timeline, ts + horizon_sec, tolerance_sec=tolerance_sec)
        if price_now is None or price_future is None or price_now <= 0:
            continue
        realized_return = (price_future - price_now) / price_now
        flat = abs(realized_return) <= deadband
        # SHORT correct when price falls.
        outcome = 1 if realized_return < 0 else 0
        rows.append({
            "ts": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
            "symbol": symbol,
            "probability": round(prob_short, 6),
            "outcome": outcome,
            "realized_return": round(realized_return, 8),
            "flat": flat,
            "horizon_min": horizon_min,
            "price_now": price_now,
            "price_future": price_future,
            "source": "realized_price_directional",
            "mode": "live",
            "closed": True,
        })
    return rows


def summarize(rows: list[dict[str, Any]], *, exclude_flat: bool = True) -> dict[str, Any]:
    """Compute pooled and per-symbol Brier/ECE reliability from harvested rows."""
    used = [r for r in rows if not (exclude_flat and r.get("flat"))]
    pooled_probs = [float(r["probability"]) for r in used]
    pooled_out = [int(r["outcome"]) for r in used]
    pooled = calibration.report(pooled_probs, pooled_out) if pooled_probs else {"n": 0}

    per_symbol: dict[str, dict[str, Any]] = {}
    by_sym: dict[str, list[dict[str, Any]]] = {}
    for r in used:
        by_sym.setdefault(r["symbol"], []).append(r)
    for symbol, srows in by_sym.items():
        probs = [float(r["probability"]) for r in srows]
        outs = [int(r["outcome"]) for r in srows]
        rep = calibration.report(probs, outs)
        per_symbol[symbol] = {
            "n": rep["n"],
            "brier": rep["brier"],
            "brier_baseline_alwaysbase": rep["brier_baseline_alwaysbase"],
            "ece": rep["ece"],
            "base_rate": rep["base_rate"],
            "beats_baseline": (
                isinstance(rep["brier"], (int, float))
                and isinstance(rep["brier_baseline_alwaysbase"], (int, float))
                and rep["brier"] < rep["brier_baseline_alwaysbase"]
            ),
        }
    return {
        "rows_total": len(rows),
        "rows_used": len(used),
        "rows_flat_excluded": len(rows) - len(used),
        "pooled": pooled,
        "per_symbol": per_symbol,
    }


def walk_forward_isotonic(
    rows: list[dict[str, Any]],
    *,
    split_frac: float = 0.6,
    exclude_flat: bool = True,
) -> dict[str, Any]:
    """Honest OOS test of isotonic recalibration.

    Fit the isotonic calibrator on the earliest ``split_frac`` of forecasts, then
    evaluate on the held-out tail. Compares three competitors on the SAME OOS set:
      - raw   : the gate's stated probability
      - recal : raw remapped through the train-fitted isotonic curve
      - base  : always predict the TRAIN base rate (the no-skill competitor)
    Isotonic fixes miscalibration (ECE) but cannot manufacture discrimination —
    if raw has no edge, recal collapses toward base and Brier approaches (not
    beats) the baseline. Lower ECE is still a genuine SAFETY gain (stops
    over-confident wrong-direction calls).
    """
    used = [r for r in rows if not (exclude_flat and r.get("flat"))]
    used = sorted(used, key=lambda r: str(r.get("ts") or ""))
    n = len(used)
    if n < 40:
        return {"n": n, "insufficient": True}
    cut = int(n * split_frac)
    train, test = used[:cut], used[cut:]
    tr_p = [float(r["probability"]) for r in train]
    tr_o = [int(r["outcome"]) for r in train]
    te_p = [float(r["probability"]) for r in test]
    te_o = [int(r["outcome"]) for r in test]
    fit = calibration.isotonic_fit(tr_p, tr_o)
    recal_p = [calibration.apply_isotonic(fit, p) for p in te_p]
    train_base = sum(tr_o) / len(tr_o) if tr_o else 0.0
    base_p = [train_base] * len(te_o)

    raw_rep = calibration.report(te_p, te_o)
    recal_rep = calibration.report(recal_p, te_o)
    return {
        "n_train": len(train),
        "n_test": len(test),
        "train_base_rate": round(train_base, 4),
        "raw_oos_brier": raw_rep["brier"],
        "recal_oos_brier": recal_rep["brier"],
        "base_oos_brier": round(calibration.brier_score(base_p, te_o), 4),
        "raw_oos_ece": raw_rep["ece"],
        "recal_oos_ece": recal_rep["ece"],
        "recal_beats_base": (
            isinstance(recal_rep["brier"], (int, float))
            and recal_rep["brier"] < calibration.brier_score(base_p, te_o)
        ),
        "recal_improves_over_raw": (
            isinstance(recal_rep["brier"], (int, float))
            and isinstance(raw_rep["brier"], (int, float))
            and recal_rep["brier"] < raw_rep["brier"]
        ),
    }


def run(
    *,
    quant_history: Path = DEFAULT_QUANT_HISTORY,
    market_history: Path = DEFAULT_MARKET_HISTORY,
    outcome_store: Path = DEFAULT_OUTCOME_STORE,
    summary_path: Path = DEFAULT_SUMMARY,
    primary_horizon_min: int = PRIMARY_HORIZON_MIN,
    robustness_horizons_min: tuple[int, ...] = ROBUSTNESS_HORIZONS_MIN,
    tolerance_sec: float = MATCH_TOLERANCE_SEC,
    deadband_bps: float = DEADBAND_BPS,
    persist: bool = True,
) -> dict[str, Any]:
    """Harvest calibration outcomes across horizons; persist store + summary."""
    index = build_price_index(market_history)

    primary_rows = harvest_rows(
        quant_history=quant_history,
        market_history=market_history,
        horizon_min=primary_horizon_min,
        tolerance_sec=tolerance_sec,
        deadband_bps=deadband_bps,
        price_index=index,
    )
    primary_summary = summarize(primary_rows, exclude_flat=True)

    robustness: dict[str, Any] = {}
    for h in robustness_horizons_min:
        rrows = harvest_rows(
            quant_history=quant_history,
            market_history=market_history,
            horizon_min=h,
            tolerance_sec=tolerance_sec,
            deadband_bps=deadband_bps,
            price_index=index,
        )
        robustness[f"horizon_{h}m"] = summarize(rrows, exclude_flat=True)["pooled"]

    isotonic_wf = walk_forward_isotonic(primary_rows, exclude_flat=True)

    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "mode": MODE,
        "policy": POLICY,
        "primary_horizon_min": primary_horizon_min,
        "match_tolerance_sec": tolerance_sec,
        "deadband_bps": deadband_bps,
        "outcome_definition": "outcome=1 iff realized_return<0 (SHORT correct); probability=P(SHORT)",
        "primary": primary_summary,
        "robustness": robustness,
        "isotonic_walk_forward": isotonic_wf,
    }

    if persist:
        # Deterministic full rewrite of the outcome store (primary horizon).
        outcome_store.parent.mkdir(parents=True, exist_ok=True)
        tmp = outcome_store.with_suffix(outcome_store.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            for row in primary_rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        tmp.replace(outcome_store)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        stmp = summary_path.with_suffix(summary_path.suffix + ".tmp")
        stmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        stmp.replace(summary_path)

    return report


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Read-only SoDEX Quant-Engine calibration harvester")
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    parser.add_argument("--no-persist", action="store_true", help="Do not write store/summary")
    parser.add_argument("--horizon-min", type=int, default=PRIMARY_HORIZON_MIN)
    parser.add_argument("--tolerance-sec", type=float, default=MATCH_TOLERANCE_SEC)
    parser.add_argument("--deadband-bps", type=float, default=DEADBAND_BPS)
    args = parser.parse_args()

    report = run(
        primary_horizon_min=args.horizon_min,
        tolerance_sec=args.tolerance_sec,
        deadband_bps=args.deadband_bps,
        persist=not args.no_persist,
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    p = report["primary"]
    pooled = p["pooled"]
    print(f"{MODE}")
    print(f"primary horizon: {report['primary_horizon_min']}m | tolerance {report['match_tolerance_sec']}s "
          f"| deadband {report['deadband_bps']}bps")
    print(f"rows: total={p['rows_total']} used={p['rows_used']} flat_excluded={p['rows_flat_excluded']}")
    print(f"POOLED: n={pooled.get('n')} brier={pooled.get('brier')} "
          f"baseline={pooled.get('brier_baseline_alwaysbase')} ece={pooled.get('ece')} "
          f"base_rate={pooled.get('base_rate')}")
    beats = (isinstance(pooled.get("brier"), (int, float))
             and isinstance(pooled.get("brier_baseline_alwaysbase"), (int, float))
             and pooled["brier"] < pooled["brier_baseline_alwaysbase"])
    print(f"POOLED beats always-base-rate: {'YES' if beats else 'NO'}")
    print()
    print("Per-symbol (n>=10, sorted by brier):")
    sym = {k: v for k, v in p["per_symbol"].items() if v["n"] >= 10}
    for symbol, s in sorted(sym.items(), key=lambda kv: (kv[1]["brier"] if kv[1]["brier"] is not None else 1.0)):
        flag = "beats-base" if s["beats_baseline"] else ""
        print(f"  {symbol:14} n={s['n']:4} brier={s['brier']} base={s['brier_baseline_alwaysbase']} "
              f"ece={s['ece']} base_rate={s['base_rate']} {flag}")
    print()
    print("Robustness (pooled brier vs baseline):")
    for label, rep in report["robustness"].items():
        rb = (isinstance(rep.get("brier"), (int, float))
              and isinstance(rep.get("brier_baseline_alwaysbase"), (int, float))
              and rep["brier"] < rep["brier_baseline_alwaysbase"])
        print(f"  {label}: n={rep.get('n')} brier={rep.get('brier')} "
              f"baseline={rep.get('brier_baseline_alwaysbase')} beats={'YES' if rb else 'NO'}")
    print()
    wf = report["isotonic_walk_forward"]
    if wf.get("insufficient"):
        print(f"Isotonic walk-forward: insufficient data (n={wf.get('n')})")
    else:
        print(f"Isotonic walk-forward (train {wf['n_train']} -> test {wf['n_test']}, "
              f"train_base_rate={wf['train_base_rate']}):")
        print(f"  OOS Brier   raw={wf['raw_oos_brier']}  recal={wf['recal_oos_brier']}  base={wf['base_oos_brier']}")
        print(f"  OOS ECE     raw={wf['raw_oos_ece']}  recal={wf['recal_oos_ece']}")
        print(f"  recal beats no-skill base: {'YES' if wf['recal_beats_base'] else 'NO'}  |  "
              f"recal improves over raw: {'YES' if wf['recal_improves_over_raw'] else 'NO'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
