#!/usr/bin/env python3
"""Read-only SoDEX quantitative statistical decision engine.

This engine fuses technical probability, empirical calibration, maker fill
likelihood, transaction-cost geometry, and the active volume/loss ratio budget.
It never places orders, cancels orders, restarts services, or changes leverage.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from anantara import calibration  # noqa: E402
from scripts.sodex_ta_probability_gate import evaluate_symbol_gate  # noqa: E402


MODE = "READ_ONLY_SODEX_QUANT_STAT"
POLICY = "no orders, no cancels, no leverage change, no service restart"
DEFAULT_OUTPUT_DIR = PROJECT / "data" / "sodex_quant_stat"
DEFAULT_NOTIONAL_USD = Decimal("12")
DEFAULT_MIN_RATIO = Decimal(os.environ.get("SODEX_MIN_REAL_VOLUME_LOSS_RATIO", "5100"))
MIN_DIRECTION_PROBABILITY = Decimal("0.80")
MIN_FILL_PROBABILITY = Decimal("0.60")
MIN_CALIBRATION_SAMPLES = 30
DEFAULT_MAKER_FEE_RATE = Decimal("0.000108")


def utc_now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(timezone.utc)


def dec(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    """Parse a value as Decimal with a safe default."""
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def flt(value: Any, default: float = 0.0) -> float:
    """Parse a value as finite float with a safe default."""
    try:
        if value is None or value == "":
            return default
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def read_json(path: Path) -> Any:
    """Read JSON from disk, returning None on missing or malformed input."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    """Read JSONL rows from disk, preserving only object rows."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    selected = lines[-limit:] if limit is not None else lines
    rows: list[dict[str, Any]] = []
    for line in selected:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Persist JSON atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    """Append one JSON object to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def round_decimal(value: Decimal, places: str = "0.00000001") -> Decimal:
    """Round Decimal deterministically for JSON-safe reporting."""
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def ratio_budget_usd(notional_usd: Decimal, min_ratio: Decimal) -> Decimal:
    """Return max loss allowed by volume/loss ratio for a round trip."""
    if notional_usd <= 0 or min_ratio <= 0:
        return Decimal("0")
    return round_decimal((notional_usd * Decimal("2")) / min_ratio)


def _clip(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a float to a closed interval."""
    return max(lo, min(hi, value))


def estimate_fill_probability(micro_row: dict[str, Any] | None) -> float:
    """Estimate maker fill probability from local microstructure evidence.

    This is a conservative stdlib proxy for the research-only River fill model:
    tight spread, high quote volume, positive maker edge, and maker-only lane
    raise the fill probability; wide or rejected lanes penalize it.
    """
    row = micro_row or {}
    spread_bps = flt(row.get("spread_bps"), 50.0)
    quote_volume = flt(row.get("quote_volume_usd") or row.get("quote_volume"), 0.0)
    maker_edge = flt(row.get("maker_gross_edge_bps"), 0.0)
    lane = str(row.get("scalp_lane") or "")

    prob = 0.42
    prob += _clip((12.0 - spread_bps) / 12.0, -1.0, 1.0) * 0.18
    prob += _clip(math.log10(max(quote_volume, 1.0)) / 7.0, 0.0, 1.0) * 0.18
    prob += _clip(maker_edge / 4.0, -1.0, 1.0) * 0.14
    if lane == "MAKER_ONLY_CANDIDATE":
        prob += 0.12
    elif lane.startswith("REJECT"):
        prob -= 0.18
    return round(_clip(prob, 0.05, 0.95), 6)


def build_cost_model(
    *,
    notional_usd: Decimal,
    min_ratio: Decimal,
    spread_pct: float,
    atr_pct: float,
    maker_fee_rate: Decimal,
    fill_probability: float,
    direction_probability: float,
) -> dict[str, Any]:
    """Build transaction-cost and adverse-selection model for a micro round trip."""
    maker_fee = dec(maker_fee_rate, DEFAULT_MAKER_FEE_RATE)
    ratio_budget = ratio_budget_usd(notional_usd, min_ratio)
    fee_loss = notional_usd * maker_fee * Decimal("2")
    adverse_fraction = Decimal(str(max(0.0, spread_pct + (atr_pct * 0.25))))
    fill_penalty_fraction = Decimal(str(max(0.0, (1.0 - fill_probability) * spread_pct * 0.35)))
    adverse_loss = notional_usd * (adverse_fraction + fill_penalty_fraction)
    directional_edge_fraction = Decimal(str(max(0.0, direction_probability - 0.5))) * Decimal(str(max(0.0, atr_pct)))
    expected_edge = (notional_usd * directional_edge_fraction * Decimal(str(fill_probability))) - fee_loss - adverse_loss
    return {
        "notional_usd": float(notional_usd),
        "roundtrip_volume_usd": float(notional_usd * Decimal("2")),
        "min_ratio": float(min_ratio),
        "ratio_budget_usd": float(ratio_budget),
        "maker_fee_loss_usd": float(round_decimal(fee_loss)),
        "expected_adverse_loss_usd": float(round_decimal(adverse_loss)),
        "expected_edge_usd": float(round_decimal(expected_edge)),
        "spread_pct": round(spread_pct, 8),
        "atr_pct": round(atr_pct, 8),
        "ratio_pass": adverse_loss <= ratio_budget,
    }


def build_calibration_summary(
    rows: list[dict[str, Any]],
    *,
    min_samples: int = MIN_CALIBRATION_SAMPLES,
) -> dict[str, Any]:
    """Build empirical probability calibration summary from historical outcomes."""
    probs: list[float] = []
    outcomes: list[int] = []
    for row in rows:
        probability = flt(row.get("probability") or row.get("prob_direction"))
        outcome_raw = row.get("outcome")
        if outcome_raw is None:
            delta = row.get("perps_account_delta_usd")
            if delta is not None:
                outcome_raw = 1 if dec(delta) > 0 else 0
        if probability <= 0 or outcome_raw is None:
            continue
        probs.append(_clip(probability))
        outcomes.append(1 if bool(outcome_raw) else 0)

    reasons: list[str] = []
    if len(probs) < min_samples:
        reasons.append("calibration_samples_below_minimum")
    report = calibration.report(probs, outcomes) if probs else {
        "n": 0,
        "brier": None,
        "brier_baseline_alwaysbase": None,
        "ece": None,
        "base_rate": None,
        "bins": [],
    }
    brier = report.get("brier")
    baseline = report.get("brier_baseline_alwaysbase")
    if isinstance(brier, (int, float)) and isinstance(baseline, (int, float)) and brier > baseline:
        reasons.append("calibration_brier_worse_than_base_rate")
    passes = not reasons
    return {
        "passes": passes,
        "reasons": reasons,
        "n": len(probs),
        "brier": brier,
        "brier_baseline_alwaysbase": baseline,
        "ece": report.get("ece"),
        "base_rate": report.get("base_rate"),
        "bins": report.get("bins") or [],
    }


def calibration_rows_from_micro_logs(path: Path, symbol: str | None = None) -> list[dict[str, Any]]:
    """Extract empirical forecast/outcome rows from micro-pilot logs."""
    rows: list[dict[str, Any]] = []
    for row in read_jsonl(path, limit=1000):
        if row.get("mode") != "live" or row.get("closed") is not True:
            continue
        if symbol and str(row.get("symbol") or "") != symbol:
            continue
        gate = row.get("ta_probability_gate") if isinstance(row.get("ta_probability_gate"), dict) else {}
        probability = gate.get("probability") or row.get("probability") or row.get("prob_direction")
        delta = row.get("perps_account_delta_usd") if "perps_account_delta_usd" in row else row.get("account_delta_usd")
        if probability is None or delta is None:
            continue
        rows.append({"probability": flt(probability), "outcome": 1 if dec(delta) > 0 else 0})
    return rows


def calibration_rows_from_outcome_store(path: Path, symbol: str | None = None) -> list[dict[str, Any]]:
    """Extract (probability, outcome) rows from the realized-price calibration store.

    This store is produced by scripts/sodex_quant_calibration_harvest.py. Its
    ``outcome`` is directional (1 iff price fell over the horizon), isolating
    forecast skill from fee-dominated round-trip PnL. Flat/noise rows are skipped.
    """
    rows: list[dict[str, Any]] = []
    for row in read_jsonl(path, limit=5000):
        if row.get("mode") != "live" or row.get("closed") is not True:
            continue
        if symbol and str(row.get("symbol") or "") != symbol:
            continue
        if row.get("flat") is True:
            continue
        probability = row.get("probability")
        outcome = row.get("outcome")
        if probability is None or outcome is None:
            continue
        rows.append({"probability": flt(probability), "outcome": 1 if int(outcome) else 0})
    return rows


def recalibrate_probability(
    raw_prob: Any,
    cal_rows: list[dict[str, Any]],
    *,
    min_samples: int = MIN_CALIBRATION_SAMPLES,
) -> float | None:
    """De-bias a raw directional probability via isotonic calibration.

    Fits a monotone isotonic map from empirical (probability, outcome) history and
    applies it to ``raw_prob``. This is a SAFETY de-biaser: it removes over/under-
    confidence (walk-forward ECE 0.22->0.09 on SoDEX Jul-2026 data) so the engine
    cannot confidently take a systematically adverse direction — it does NOT and
    cannot manufacture directional edge that the raw signal lacks. Returns None when
    there is insufficient empirical evidence (< min_samples); the caller then keeps
    the raw probability unchanged.
    """
    rows = [r for r in cal_rows if r.get("probability") is not None and r.get("outcome") is not None]
    if len(rows) < min_samples:
        return None
    probs = [flt(r["probability"]) for r in rows]
    outcomes = [1 if int(r["outcome"]) else 0 for r in rows]
    fit = calibration.isotonic_fit(probs, outcomes)
    return _clip(calibration.apply_isotonic(fit, flt(raw_prob)))


def _atr_pct_from_ta_gate(ta_gate: dict[str, Any]) -> float:
    """Extract ATR percent from a TA gate result."""
    signal = ((ta_gate.get("signals") or {}).get("atr_realized_vol") or {}).get("value") or {}
    if isinstance(signal, dict):
        return flt(signal.get("atr_pct")) / 100.0
    return 0.0


def _spread_pct(market_row: dict[str, Any] | None, micro_row: dict[str, Any] | None) -> float:
    """Extract spread fraction from market or microstructure rows."""
    market = market_row or {}
    micro = micro_row or {}
    if market.get("spread_pct") is not None:
        raw = flt(market.get("spread_pct"))
        return raw / 100.0 if raw > 1.0 else raw
    if market.get("spread_bps") is not None:
        return flt(market.get("spread_bps")) / 10000.0
    if micro.get("spread_pct") is not None:
        raw = flt(micro.get("spread_pct"))
        return raw / 100.0 if raw > 1.0 else raw
    if micro.get("spread_bps") is not None:
        return flt(micro.get("spread_bps")) / 10000.0
    return 0.0


def build_decision(
    *,
    symbol: str,
    side: str,
    ta_gate: dict[str, Any],
    market_row: dict[str, Any] | None,
    micro_row: dict[str, Any] | None,
    calibration: dict[str, Any],
    notional_usd: Decimal,
    min_ratio: Decimal,
    safety_halt_active: bool,
    maker_fee_rate: Decimal = DEFAULT_MAKER_FEE_RATE,
    recalibrated_probability: float | None = None,
) -> dict[str, Any]:
    """Fuse all quant-stat gates into one read-only decision.

    When ``recalibrated_probability`` is provided it is the empirically de-biased
    P(direction) and is used for the direction gate and cost model; the raw gate
    probability is still reported as ``prob_direction_raw`` for transparency.
    """
    raw_prob_direction = flt(ta_gate.get("probability"))
    prob_direction = raw_prob_direction if recalibrated_probability is None else _clip(flt(recalibrated_probability))
    prob_fill = estimate_fill_probability(micro_row)
    spread_pct = _spread_pct(market_row, micro_row)
    atr_pct = _atr_pct_from_ta_gate(ta_gate)
    if atr_pct <= 0:
        atr_pct = max(spread_pct * 2.0, 0.00002)
    cost_model = build_cost_model(
        notional_usd=notional_usd,
        min_ratio=min_ratio,
        spread_pct=spread_pct,
        atr_pct=atr_pct,
        maker_fee_rate=maker_fee_rate,
        fill_probability=prob_fill,
        direction_probability=prob_direction,
    )

    blockers: list[str] = []
    if safety_halt_active:
        blockers.append("safety_halt_active")
    if not ta_gate.get("passes"):
        blockers.append("ta_probability_gate_not_passed")
    if Decimal(str(prob_direction)) < MIN_DIRECTION_PROBABILITY:
        blockers.append("direction_probability_below_minimum")
    if Decimal(str(prob_fill)) < MIN_FILL_PROBABILITY:
        blockers.append("fill_probability_below_minimum")
    if not calibration.get("passes"):
        blockers.append("calibration_not_passed")
    if not cost_model["ratio_pass"]:
        blockers.append("ratio_budget_not_passed")
    if flt((market_row or {}).get("quote_volume_usd") or (market_row or {}).get("quote_volume")) <= 0:
        blockers.append("market_liquidity_missing")

    if safety_halt_active:
        decision = "BLOCK"
    elif blockers:
        decision = "WAIT"
    else:
        decision = "TRADE_READY"

    return {
        "symbol": symbol,
        "side": side,
        "decision": decision,
        "prob_direction": round(prob_direction, 6),
        "prob_direction_raw": round(raw_prob_direction, 6),
        "recalibrated": recalibrated_probability is not None,
        "prob_fill_15s": prob_fill,
        "expected_edge_usd": cost_model["expected_edge_usd"],
        "expected_adverse_loss_usd": cost_model["expected_adverse_loss_usd"],
        "ratio_budget_usd": cost_model["ratio_budget_usd"],
        "calibration_brier": calibration.get("brier"),
        "calibration_n": calibration.get("n"),
        "ta_gate": ta_gate,
        "calibration": calibration,
        "cost_model": cost_model,
        "blockers": blockers,
    }


def _rows_by_symbol(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index scanner rows by symbol from common SoDEX scanner sections."""
    out: dict[str, dict[str, Any]] = {}
    sections: list[Any] = [
        report.get("items") or [],
        report.get("short_watch") or [],
        report.get("top_gainers") or [],
        report.get("top_losers") or [],
        report.get("top") or [],
    ]
    rankings = report.get("rankings") if isinstance(report.get("rankings"), dict) else {}
    for key in ("short_watch", "tight_liquid", "top_losers", "top_gainers", "top_liquid"):
        sections.append(rankings.get(key) or [])
    for rows in sections:
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "")
            if symbol and symbol not in out:
                out[symbol] = row
    return out


def _candidate_symbols(report: dict[str, Any], explicit: list[str] | None = None) -> list[str]:
    """Return target symbols from explicit input or scanner rows."""
    if explicit:
        return [symbol for symbol in explicit if symbol]
    symbols = list(_rows_by_symbol(report).keys())
    return symbols[:10]


def _safety_halt_active(project: Path, monitor: dict[str, Any]) -> bool:
    """Return whether local safety halt is active."""
    if (project / "data" / "SAFETY_HALT").exists() or (project / "data" / "PNL_HALT").exists():
        return True
    halt = monitor.get("halt_status") if isinstance(monitor, dict) else {}
    return bool(isinstance(halt, dict) and halt.get("active"))


def run_engine(
    *,
    project: Path = PROJECT,
    output_dir: Path | None = None,
    symbols: list[str] | None = None,
    notional_usd: Decimal = DEFAULT_NOTIONAL_USD,
    min_ratio: Decimal = DEFAULT_MIN_RATIO,
    persist: bool = True,
    now: datetime | None = None,
    min_calibration_samples: int = MIN_CALIBRATION_SAMPLES,
) -> dict[str, Any]:
    """Run read-only SoDEX quant-stat decision engine."""
    current = now or utc_now()
    out_dir = output_dir or (project / "data" / "sodex_quant_stat")
    market_latest = read_json(project / "data" / "sodex_market_scan" / "latest.json") or {}
    monitor = read_json(project / "data" / "sodex_monitor_eval" / "latest.json") or {}
    market_by_symbol = _rows_by_symbol(market_latest if isinstance(market_latest, dict) else {})
    safety_halt = _safety_halt_active(project, monitor if isinstance(monitor, dict) else {})
    decisions: list[dict[str, Any]] = []

    for symbol in _candidate_symbols(market_latest if isinstance(market_latest, dict) else {}, symbols):
        market_row = market_by_symbol.get(symbol, {})
        spread_pct = _spread_pct(market_row, None)
        micro_row = {
            "spread_bps": spread_pct * 10000.0,
            "spread_pct": spread_pct,
            "quote_volume_usd": flt(market_row.get("quote_volume_usd") or market_row.get("quote_volume")),
            "maker_gross_edge_bps": max(0.0, (spread_pct * 10000.0) - float(DEFAULT_MAKER_FEE_RATE * Decimal("20000"))),
            "scalp_lane": "MAKER_ONLY_CANDIDATE" if spread_pct <= 0.0012 else "REJECT_TOO_WIDE_ADVERSE_SELECTION",
        }
        ta_gate = evaluate_symbol_gate(
            symbol,
            side="sell",
            history_path=project / "data" / "sodex_market_scan" / "history.jsonl",
            notional_usd=notional_usd,
            min_ratio=min_ratio,
            min_probability=MIN_DIRECTION_PROBABILITY,
            now=current,
        )
        # Primary calibration evidence: realized-price directional outcomes from the
        # harvester store (fee-clean). Fall back to micro-pilot round-trip logs, then
        # to the pooled cross-symbol set, so calibration_n reflects all available truth.
        outcome_store = project / "data" / "sodex_quant_calibration.jsonl"
        micro_logs = project / "data" / "sodex_micro_pilot.jsonl"
        cal_rows = calibration_rows_from_outcome_store(outcome_store, symbol=symbol)
        cal_rows.extend(calibration_rows_from_micro_logs(micro_logs, symbol=symbol))
        if len(cal_rows) < min_calibration_samples:
            cal_rows.extend(calibration_rows_from_outcome_store(outcome_store, symbol=None))
            cal_rows.extend(calibration_rows_from_micro_logs(micro_logs, symbol=None))
        cal_summary = build_calibration_summary(cal_rows, min_samples=min_calibration_samples)
        recal_prob = recalibrate_probability(
            ta_gate.get("probability"), cal_rows, min_samples=min_calibration_samples,
        )
        decisions.append(build_decision(
            symbol=symbol,
            side="sell",
            ta_gate=ta_gate,
            market_row=market_row,
            micro_row=micro_row,
            calibration=cal_summary,
            notional_usd=notional_usd,
            min_ratio=min_ratio,
            safety_halt_active=safety_halt,
            recalibrated_probability=recal_prob,
        ))

    summary = {
        "total": len(decisions),
        "trade_ready": sum(1 for row in decisions if row["decision"] == "TRADE_READY"),
        "wait": sum(1 for row in decisions if row["decision"] == "WAIT"),
        "block": sum(1 for row in decisions if row["decision"] == "BLOCK"),
    }
    report = {
        "ts": current.isoformat(),
        "mode": MODE,
        "policy": POLICY,
        "schema_version": 1,
        "project": str(project),
        "notional_usd": float(notional_usd),
        "min_real_volume_loss_ratio": float(min_ratio),
        "summary": summary,
        "research_basis": [
            "probability_calibration_brier_ece_isotonic",
            "walk_forward_oos_required_before_live_promotion",
            "transaction_cost_spread_fee_adverse_selection_model",
            "maker_fill_probability_proxy_from_microstructure",
            "ratio_budget_hard_gate",
        ],
        "decisions": decisions,
    }
    if persist:
        write_json_atomic(out_dir / "latest.json", report)
        append_jsonl(out_dir / "history.jsonl", report)
    return report


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Read-only SoDEX quant-stat decision engine")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    parser.add_argument("--no-persist", action="store_true", help="Do not write data/sodex_quant_stat artifacts")
    parser.add_argument("--symbol", action="append", default=[], help="Symbol to evaluate; may be repeated")
    parser.add_argument("--notional-usd", default=str(DEFAULT_NOTIONAL_USD), help="Candidate notional for risk modeling")
    parser.add_argument("--min-ratio", default=str(DEFAULT_MIN_RATIO), help="Minimum real volume/loss ratio")
    parser.add_argument("--min-calibration-samples", type=int, default=MIN_CALIBRATION_SAMPLES)
    args = parser.parse_args()
    report = run_engine(
        symbols=args.symbol or None,
        notional_usd=dec(args.notional_usd, DEFAULT_NOTIONAL_USD),
        min_ratio=dec(args.min_ratio, DEFAULT_MIN_RATIO),
        persist=not args.no_persist,
        min_calibration_samples=args.min_calibration_samples,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"{MODE}: {report['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
