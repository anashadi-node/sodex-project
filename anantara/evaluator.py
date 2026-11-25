#!/usr/bin/env python3
"""
ANANTARA SAKTI — Paper-trading evaluator (pure, stdlib-only, testable).

Extracted from anantara_daemon.py so the Day-21/31 GO/NO-GO grading logic can be
unit-tested without the daemon's I/O (httpx, freqtrade API, scheduler). The
daemon's _grade_instance() fetches /profit then calls grade_profit() here.

Grades a freqtrade /profit payload against GO/NO-GO criteria, robust to version
differences (drawdown as fraction vs percent; winrate as fraction vs percent).
"""
from __future__ import annotations
from typing import Any

# Default GO/NO-GO gate (mirrors daemon EVAL_CRITERIA).
DEFAULT_CRITERIA = {
    "profit_factor_min": 1.2,
    "max_drawdown_max": 0.20,
    "winrate_min": 0.45,
    "min_trades": 20,        # statistical-significance floor
}


def _norm_fraction(x: float) -> float:
    """Normalize a value that may be a fraction (0-1) or a percent (>1) to 0-1."""
    x = abs(x or 0)
    return x if x <= 1 else x / 100.0


def grade_profit(p: dict[str, Any], criteria: dict | None = None) -> dict[str, Any]:
    """Grade a freqtrade /profit dict against criteria. Pure — no I/O."""
    c = criteria or DEFAULT_CRITERIA
    closed = p.get("closed_trade_count", p.get("trade_count", 0)) or 0
    pf = p.get("profit_factor", 0) or 0
    dd = _norm_fraction(p.get("max_drawdown", p.get("max_drawdown_account", 0)))
    wr = _norm_fraction(p.get("winrate", 0))
    checks = {
        "profit_factor": (pf, pf >= c["profit_factor_min"]),
        "max_drawdown": (dd, dd <= c["max_drawdown_max"]),
        "winrate": (wr, wr >= c["winrate_min"]),
        "trades": (closed, closed >= c["min_trades"]),
    }
    return {
        "profit_abs": p.get("profit_closed_coin", p.get("profit_all_coin", 0)) or 0,
        "profit_pct": p.get("profit_closed_percent", p.get("profit_all_percent", 0)) or 0,
        "expectancy": p.get("expectancy", 0) or 0,
        "checks": checks,
        "passed": all(ok for _, ok in checks.values()),
        "significant": closed >= c["min_trades"],
    }
