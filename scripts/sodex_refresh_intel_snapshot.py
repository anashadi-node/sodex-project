#!/usr/bin/env python3
"""Persist Hermes intelligence + forecasts into the local SoDEX intel JSONL.

Target policy reads this JSONL, while Hermes keeps refreshed intelligence in
memory. This bridge prevents a fresh Hermes signal from looking stale locally.
No orders are placed.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_INTEL_DIR = PROJECT / "freqtrade_user_data" / "data" / "binance" / "intelligence"


def _http_json(url: str, *, method: str = "GET", payload: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    parsed = json.loads(body) if body else {}
    return parsed if isinstance(parsed, dict) else {}


def _forecast_dir_enc(forecast: dict[str, Any]) -> int:
    if not _forecast_trade_eligible(forecast):
        return 0
    direction = str((forecast.get("forecast") or {}).get("direction") or "").upper()
    if direction == "DOWN":
        return -1
    if direction == "UP":
        return 1
    return 0


def _forecast_conf(forecast: dict[str, Any]) -> float:
    if not _forecast_trade_eligible(forecast):
        return 0.0
    try:
        return float((forecast.get("forecast") or {}).get("confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _forecast_trade_eligible(forecast: dict[str, Any]) -> bool:
    inner = forecast.get("forecast") or {}
    if forecast.get("llm_degraded") or inner.get("fallback"):
        return False
    if forecast.get("tech_available") is False:
        return False
    if forecast.get("trade_eligible") is False or inner.get("trade_eligible") is False:
        return False
    if "trade_eligible" not in forecast and "trade_eligible" not in inner:
        return True
    return bool(forecast.get("trade_eligible") or inner.get("trade_eligible"))


def _forecast_agreement(forecast: dict[str, Any]) -> float:
    if not _forecast_trade_eligible(forecast):
        return 0.0
    try:
        return float((forecast.get("forecast") or {}).get("signal_agreement") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def event_risk_from_intel(intel: dict[str, Any]) -> tuple[str, float]:
    inputs = intel.get("inputs") or {}
    components = intel.get("components") or {}
    try:
        mcap_change = float(inputs.get("mcap_change_24h") or 0.0)
        fg_raw = float(inputs.get("fg_raw") or 50.0)
        flow_tilt = float(components.get("flow_tilt") or 0.0)
    except (TypeError, ValueError):
        return "YELLOW", 50.0
    risk = 0.0
    if mcap_change < 0:
        risk += min(45.0, abs(mcap_change) * 12.0)
    if fg_raw <= 20:
        risk += 30.0
    if flow_tilt < 0:
        risk += min(25.0, abs(flow_tilt) * 5.0)
    score = round(max(0.0, min(100.0, risk)), 1)
    if score >= 70:
        return "RED", score
    if score >= 35:
        return "YELLOW", score
    return "GREEN", score


def build_snapshot(intel: dict[str, Any], forecasts: dict[str, dict[str, Any]], *, ts: float | None = None) -> dict[str, Any]:
    risk_level, risk_score = event_risk_from_intel(intel)
    components = intel.get("components") or {}
    inputs = intel.get("inputs") or {}
    row: dict[str, Any] = {
        "ts": int(ts or time.time()),
        "composite_score": float(intel.get("composite_score") or 50.0),
        "label": intel.get("label"),
        "label_enc": 0,
        "dominant_signal": intel.get("dominant_signal"),
        "explainability": intel.get("explainability"),
        "event_risk_level": risk_level,
        "event_risk_score": risk_score,
        "market_regime": inputs.get("regime") or "RANGING",
        "market_regime_momentum": float(inputs.get("mcap_change_24h") or 0.0),
        "flow_tilt": float(components.get("flow_tilt") or 0.0),
        "funding_tilt": float(components.get("funding_tilt") or 0.0),
    }
    for symbol in ("BTC", "ETH", "SOL"):
        forecast = forecasts.get(symbol) or {}
        row[f"fc_{symbol}_dir_enc"] = _forecast_dir_enc(forecast)
        row[f"fc_{symbol}_conf"] = _forecast_conf(forecast)
        row[f"fc_{symbol}_agreement"] = _forecast_agreement(forecast)
        row[f"fc_{symbol}_eligible"] = _forecast_trade_eligible(forecast)
        row[f"fc_{symbol}_quality"] = str(forecast.get("quality") or (forecast.get("forecast") or {}).get("quality") or "")
    return row


def append_snapshot(row: dict[str, Any], intel_dir: Path = DEFAULT_INTEL_DIR) -> Path:
    intel_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.fromtimestamp(float(row["ts"]), timezone.utc).strftime("%Y%m%d")
    path = intel_dir / f"intel_{day}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh and persist local SoDEX intel snapshot")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--intel-dir", type=Path, default=DEFAULT_INTEL_DIR)
    parser.add_argument("--no-refresh", action="store_true", help="read current Hermes state without POST refresh")
    args = parser.parse_args(argv)

    base = args.base_url.rstrip("/")
    if not args.no_refresh:
        _http_json(f"{base}/sentiment/poll", method="POST")
        _http_json(f"{base}/scanner/scan", method="POST")
        _http_json(f"{base}/news/refresh", method="POST")
        intel = _http_json(f"{base}/intelligence/refresh", method="POST")
    else:
        intel = _http_json(f"{base}/intelligence/current")
    forecasts = {}
    for symbol in ("BTC", "ETH", "SOL"):
        try:
            forecasts[symbol] = _http_json(
                f"{base}/prediction/forecast",
                method="POST",
                payload={"symbol": symbol},
                timeout=45.0,
            )
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            forecasts[symbol] = {
                "symbol": symbol,
                "forecast": {"direction": "NEUTRAL", "confidence": 0.0, "trade_eligible": False},
                "llm_degraded": True,
                "tech_available": False,
                "trade_eligible": False,
                "quality": "FORECAST_HTTP_ERROR",
                "error": str(exc)[:200],
            }
    row = build_snapshot(intel, forecasts)
    path = append_snapshot(row, args.intel_dir)
    print(json.dumps({"path": str(path), "snapshot": row}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
