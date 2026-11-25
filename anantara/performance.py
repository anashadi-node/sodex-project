#!/usr/bin/env python3
"""
ANANTARA SAKTI — live performance / PnL feedback loop (pure + tested).

Closes the autonomy loop: the system measures its OWN realized risk-adjusted
performance from an equity time-series, instead of only forecasting. Feeds
risk_metrics so sizing (vol-target / fractional-Kelly) can adapt to what is
ACTUALLY happening, not just backtests.

  • returns_from_equity(series)   — equity snapshots → per-period simple returns
  • report(series, ppy)           — full risk_metrics summary on the live curve
  • append_snapshot / load_series — thin JSONL persistence (one equity point/day)

Stdlib only. Decision/maths are pure (tested); persistence is thin I/O.
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone

try:
    from risk_metrics import summary as _summary          # same-dir (daemon runtime)
except ImportError:
    from anantara.risk_metrics import summary as _summary  # package (tests)

PERF_PATH = "freqtrade_user_data/data/perf/equity.jsonl"


def returns_from_equity(series: list[float]) -> list[float]:
    """Per-period simple returns from consecutive equity snapshots."""
    out = []
    for i in range(1, len(series)):
        prev = series[i - 1]
        if prev and prev > 0:
            out.append((series[i] - prev) / prev)
    return out


def report(series: list[float], periods_per_year: int = 365) -> dict:
    """Risk-adjusted performance report from an equity series (≥3 points for stats)."""
    rets = returns_from_equity(series)
    if len(rets) < 2:
        return {"n_points": len(series), "status": "accumulating (need ≥3 snapshots)"}
    s = _summary(rets, periods_per_year)
    s["n_points"] = len(series)
    s["equity_start"], s["equity_now"] = round(series[0], 2), round(series[-1], 2)
    return s


def append_snapshot(path: str, equity: float, ts: str | None = None,
                    extra: dict | None = None) -> None:
    """Append one equity snapshot (append-only JSONL — survives restarts)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    row = {"ts": ts or datetime.now(timezone.utc).isoformat(), "equity": float(equity)}
    if extra:
        row.update(extra)
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")


def load_series(path: str) -> list[float]:
    """Equity values in chronological order (skips malformed lines)."""
    out = []
    try:
        with open(path) as f:
            for ln in f:
                try:
                    out.append(float(json.loads(ln)["equity"]))
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    return out
