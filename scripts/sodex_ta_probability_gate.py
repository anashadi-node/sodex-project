#!/usr/bin/env python3
"""Seven-signal TA probability gate for SoDEX micro probes.

The SoDEX CLI currently exposes tickers/order books, not native OHLCV candles.
This gate therefore builds short-horizon pseudo-candles from the local market
scanner history and blocks live probes when evidence is stale or weak.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_HISTORY = PROJECT / "data" / "sodex_market_scan" / "history.jsonl"
SIGNAL_NAMES = (
    "ema_trend",
    "rsi",
    "macd",
    "bollinger",
    "vwap",
    "atr_realized_vol",
    "orderflow_microstructure",
)


@dataclass(frozen=True)
class Candle:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume_usd: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    change_pct: float = 0.0
    funding_rate: float = 0.0


def dec(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _flt(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        raw = str(value).replace("Z", "+00:00")
        ts = datetime.fromisoformat(raw)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    except ValueError:
        return None


def _clip(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [values[0]]
    for value in values[1:]:
        out.append((value * alpha) + (out[-1] * (1.0 - alpha)))
    return out


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for prev, cur in zip(values[-period - 1:-1], values[-period:]):
        delta = cur - prev
        gains.append(max(0.0, delta))
        losses.append(max(0.0, -delta))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((x - mean) ** 2 for x in values) / len(values))


def _atr_pct(candles: list[Candle], period: int = 14) -> float | None:
    if len(candles) <= period:
        return None
    trs: list[float] = []
    for prev, cur in zip(candles[-period - 1:-1], candles[-period:]):
        trs.append(max(
            cur.high - cur.low,
            abs(cur.high - prev.close),
            abs(cur.low - prev.close),
        ))
    close = candles[-1].close
    if close <= 0:
        return None
    return (sum(trs) / len(trs)) / close


def _history_points(path: Path, symbol: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    points: list[dict[str, Any]] = []
    sections = ("short_watch", "top_gainers", "top_losers")
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = _parse_ts(payload.get("ts"))
        if not ts:
            continue
        for section in sections:
            rows = payload.get(section) or []
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict) or str(row.get("symbol") or "") != symbol:
                    continue
                price = _flt(row.get("mid")) or _flt(row.get("last"))
                if price <= 0:
                    continue
                points.append({
                    "ts": ts,
                    "price": price,
                    "bid": _flt(row.get("bid")),
                    "ask": _flt(row.get("ask")),
                    "volume_usd": _flt(row.get("quote_volume_usd")),
                    "change_pct": _flt(row.get("change_pct")),
                    "funding_rate": _flt(row.get("funding_rate")),
                    "spread_bps": _flt(row.get("spread_bps")),
                })
    points.sort(key=lambda row: row["ts"])
    return points


def pseudo_candles_from_points(points: list[dict[str, Any]], bucket_seconds: int = 60) -> list[Candle]:
    buckets: dict[int, list[dict[str, Any]]] = {}
    for point in points:
        ts = point.get("ts")
        price = _flt(point.get("price"))
        if not isinstance(ts, datetime) or price <= 0:
            continue
        bucket = int(ts.timestamp()) // bucket_seconds * bucket_seconds
        buckets.setdefault(bucket, []).append(point)
    candles: list[Candle] = []
    for bucket in sorted(buckets):
        rows = buckets[bucket]
        prices = [_flt(row.get("price")) for row in rows if _flt(row.get("price")) > 0]
        if not prices:
            continue
        first = rows[0]
        last = rows[-1]
        volumes = [_flt(row.get("volume_usd")) for row in rows]
        volume_delta = max(0.0, max(volumes) - min(volumes)) if volumes else 0.0
        candles.append(Candle(
            ts=datetime.fromtimestamp(bucket, tz=timezone.utc),
            open=prices[0],
            high=max(prices),
            low=min(prices),
            close=prices[-1],
            volume_usd=volume_delta,
            bid=_flt(last.get("bid")),
            ask=_flt(last.get("ask")),
            change_pct=_flt(last.get("change_pct")),
            funding_rate=_flt(last.get("funding_rate")),
        ))
    return candles


def candles_from_history(symbol: str, path: Path = DEFAULT_HISTORY, *, bucket_seconds: int = 60) -> list[Candle]:
    return pseudo_candles_from_points(_history_points(path, symbol), bucket_seconds=bucket_seconds)


def _signal(name: str, score: float, value: Any = None, reason: str = "") -> dict[str, Any]:
    return {
        "score_short": round(_clip(score), 6),
        "value": value,
        "reason": reason,
    }


def evaluate_candles(
    symbol: str,
    candles: list[Candle],
    *,
    side: str = "sell",
    notional_usd: Decimal | None = None,
    min_ratio: Decimal = Decimal("5100"),
    min_probability: Decimal = Decimal("0.80"),
    max_age_seconds: int = 180,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    ordered = sorted(candles, key=lambda candle: candle.ts)
    closes = [c.close for c in ordered if c.close > 0]
    reasons: list[str] = []
    signals: dict[str, dict[str, Any]] = {}
    if len(ordered) < 30 or len(closes) < 30:
        reasons.append("ta_data_insufficient_min_30_candles")
    if ordered:
        age = max(0.0, (current - ordered[-1].ts.astimezone(timezone.utc)).total_seconds())
        if age > max_age_seconds:
            reasons.append("ta_data_stale")
    else:
        age = None
        reasons.append("ta_data_missing")

    if reasons:
        return {
            "symbol": symbol,
            "side": side,
            "direction": "WAIT",
            "probability": 0.0,
            "passes": False,
            "min_probability": float(min_probability),
            "coverage": 0.0,
            "candles": len(ordered),
            "latest_ts": ordered[-1].ts.isoformat() if ordered else None,
            "latest_age_seconds": age,
            "signals": signals,
            "reasons": reasons,
        }

    ema9 = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    ema_trend = ((ema9[-1] - ema21[-1]) / closes[-1]) if closes[-1] else 0.0
    ema_slope = ((ema21[-1] - ema21[-6]) / closes[-1]) if len(ema21) >= 6 and closes[-1] else 0.0
    signals["ema_trend"] = _signal(
        "ema_trend",
        _clip((-ema_trend * 650.0) + (-ema_slope * 900.0)),
        {"ema9": ema9[-1], "ema21": ema21[-1], "ema21_slope_pct": ema_slope * 100.0},
        "ema9_below_ema21_and_down_slope_supports_short",
    )

    rsi = _rsi(closes)
    if rsi is not None:
        rsi_score = _clip((50.0 - rsi) / 22.0)
        if rsi < 24.0:
            rsi_score *= 0.55
        signals["rsi"] = _signal("rsi", rsi_score, rsi, "rsi_below_50_supports_short_but_extreme_oversold_is_discounted")

    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = [a - b for a, b in zip(ema12[-len(ema26):], ema26)]
    macd_signal = _ema(macd_line, 9)
    if macd_line and macd_signal:
        hist = macd_line[-1] - macd_signal[-1]
        prev_hist = (macd_line[-2] - macd_signal[-2]) if len(macd_line) >= 2 and len(macd_signal) >= 2 else hist
        signals["macd"] = _signal(
            "macd",
            _clip((-hist / closes[-1] * 2200.0) + (-(hist - prev_hist) / closes[-1] * 1200.0)),
            {"hist": hist, "hist_delta": hist - prev_hist},
            "negative_or_falling_macd_histogram_supports_short",
        )

    window = closes[-20:]
    basis = sum(window) / len(window)
    sd = _stddev(window)
    upper = basis + (2.0 * sd)
    lower = basis - (2.0 * sd)
    bb_pos = (closes[-1] - lower) / (upper - lower) if upper > lower else 0.5
    bb_width = (upper - lower) / basis if basis > 0 else 0.0
    bb_score = _clip((0.5 - bb_pos) * 2.0)
    if bb_pos < 0.08:
        bb_score *= 0.65
    signals["bollinger"] = _signal(
        "bollinger",
        bb_score,
        {"position": bb_pos, "width_pct": bb_width * 100.0},
        "close_below_bollinger_midline_supports_short_extreme_lower_band_discounted",
    )

    recent = ordered[-30:]
    vol_sum = sum(max(0.0, candle.volume_usd) for candle in recent)
    if vol_sum > 0:
        vwap = sum(candle.close * max(0.0, candle.volume_usd) for candle in recent) / vol_sum
    else:
        vwap = sum(candle.close for candle in recent) / len(recent)
    vwap_dev = (closes[-1] - vwap) / closes[-1] if closes[-1] else 0.0
    signals["vwap"] = _signal(
        "vwap",
        _clip(-vwap_dev * 900.0),
        {"vwap": vwap, "deviation_pct": vwap_dev * 100.0},
        "price_below_vwap_supports_short",
    )

    atr_pct = _atr_pct(ordered) or 0.0
    returns = [
        (cur - prev) / prev
        for prev, cur in zip(closes[-21:-1], closes[-20:])
        if prev > 0
    ]
    realized_vol = _stddev(returns)
    drift = (closes[-1] - closes[-10]) / closes[-10] if len(closes) >= 10 and closes[-10] > 0 else 0.0
    vol_score = _clip((-drift * 250.0) + (0.45 if atr_pct <= 0.003 else -0.45))
    signals["atr_realized_vol"] = _signal(
        "atr_realized_vol",
        vol_score,
        {"atr_pct": atr_pct * 100.0, "realized_vol_pct": realized_vol * 100.0, "drift_10_pct": drift * 100.0},
        "negative_drift_with_contained_atr_supports_short",
    )

    latest = ordered[-1]
    spread_pct = ((latest.ask - latest.bid) / latest.close) if latest.ask > latest.bid > 0 and latest.close > 0 else 0.0
    micro_score = 0.0
    micro_score += _clip(-latest.change_pct / 4.0, -1.0, 1.0) * 0.45
    micro_score += 0.25 if spread_pct <= 0.0012 else -0.35
    micro_score += 0.20 if latest.funding_rate >= 0 else -0.20
    micro_score += 0.10 if latest.volume_usd >= 0 else 0.0
    signals["orderflow_microstructure"] = _signal(
        "orderflow_microstructure",
        micro_score,
        {"change_pct": latest.change_pct, "spread_pct": spread_pct * 100.0, "funding_rate": latest.funding_rate},
        "negative_24h_change_tight_spread_positive_funding_support_short_maker_probe",
    )

    valid_scores = [signals[name]["score_short"] for name in SIGNAL_NAMES if name in signals]
    coverage = len(valid_scores) / len(SIGNAL_NAMES)
    short_edge = sum(valid_scores) / len(valid_scores) if valid_scores else 0.0
    short_probability = _clip(0.5 + (short_edge * 0.5), 0.0, 1.0)
    desired_short = side.lower() in {"sell", "short"}
    probability = short_probability if desired_short else (1.0 - short_probability)
    direction = "SHORT" if short_probability >= 0.56 else "LONG" if short_probability <= 0.44 else "WAIT"

    ratio_budget = Decimal("0")
    estimated_adverse = Decimal("0")
    if notional_usd is not None and notional_usd > 0 and min_ratio > 0:
        ratio_budget = (notional_usd * Decimal("2")) / min_ratio
        adverse_fraction = Decimal(str(max(0.0, (atr_pct * 0.25) + spread_pct)))
        estimated_adverse = notional_usd * adverse_fraction
        if estimated_adverse > ratio_budget:
            reasons.append("estimated_atr_spread_adverse_loss_exceeds_ratio_budget")

    if coverage < 1.0:
        reasons.append("ta_signal_coverage_incomplete")
    if direction == "WAIT":
        reasons.append("direction_probability_neutral")
    expected_direction = "SHORT" if desired_short else "LONG"
    if direction != expected_direction:
        reasons.append("ta_direction_mismatch")
    if Decimal(str(probability)) < min_probability:
        reasons.append("ta_probability_below_minimum")

    return {
        "symbol": symbol,
        "side": side,
        "direction": direction,
        "probability": round(probability, 6),
        "short_probability": round(short_probability, 6),
        "passes": not reasons,
        "min_probability": float(min_probability),
        "coverage": round(coverage, 6),
        "candles": len(ordered),
        "latest_ts": latest.ts.isoformat(),
        "latest_age_seconds": age,
        "estimated_adverse_loss_usd": float(estimated_adverse),
        "ratio_budget_usd": float(ratio_budget),
        "signals": signals,
        "reasons": reasons,
    }


def evaluate_symbol_gate(
    symbol: str,
    *,
    side: str = "sell",
    history_path: Path = DEFAULT_HISTORY,
    notional_usd: Decimal | None = None,
    min_ratio: Decimal = Decimal("5100"),
    min_probability: Decimal = Decimal("0.80"),
    max_age_seconds: int = 180,
    now: datetime | None = None,
) -> dict[str, Any]:
    candles = candles_from_history(symbol, history_path)
    return evaluate_candles(
        symbol,
        candles,
        side=side,
        notional_usd=notional_usd,
        min_ratio=min_ratio,
        min_probability=min_probability,
        max_age_seconds=max_age_seconds,
        now=now,
    )
