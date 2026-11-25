#!/usr/bin/env python3
"""
ANANTARA SAKTI — SoDEX SPOT Risk & Alert Monitor v1.0
=====================================================
Scientific risk monitoring for SPOT farming.
Reads state files, computes Sharpe/Sortino/Calmar, sends alerts.

FASE 2: Risk metrics + Telegram notification integration.
Runs as companion to sodex_autofarm.py daemon.

USAGE:
  python3 scripts/sodex_spot_monitor.py          # One-shot status
  python3 scripts/sodex_spot_monitor.py --loop   # Continuous monitoring
  python3 scripts/sodex_spot_monitor.py --alert  # Send Telegram alert
"""

import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Config ──────────────────────────────────────────────────
STATE_FILE = Path.home() / ".local/share/anantara/sodex_spot_state.json"
ALERT_FILE = Path.home() / ".local/share/anantara/sodex_spot_alert.json"
CHECK_INTERVAL_S = 300  # 5 minutes
ALERT_COOLDOWN_S = 1800  # 30 min between repeated alerts

# Risk thresholds
MAX_DRAWDOWN_PCT = 5.0
MIN_SHARPE = 0.5
MIN_SORTINO = 0.8
MAX_CONSECUTIVE_LOSSES = 3
MIN_WIN_RATE_WARN = 0.55

# ── Risk Metrics (stdlib-only) ──────────────────────────────

def compute_returns(pnl_list: list[float]) -> list[float]:
    """Convert P&L to return series."""
    if not pnl_list:
        return []
    capital = 20.0  # approximate
    return [p / capital for p in pnl_list]

def sharpe_ratio(returns: list[float], risk_free: float = 0.02) -> float:
    """Annualized Sharpe ratio."""
    if len(returns) < 3:
        return 0.0
    mean_ret = sum(returns) / len(returns)
    if mean_ret == 0:
        return 0.0
    variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(variance) if variance > 0 else 1e-10
    # Annualize (assume ~100 RTs/day, 365 days)
    annual_factor = math.sqrt(36500)
    return (mean_ret * 36500 - risk_free) / (std * annual_factor) if std > 0 else 0.0

def sortino_ratio(returns: list[float], risk_free: float = 0.02) -> float:
    """Sortino ratio (only penalizes downside)."""
    if len(returns) < 3:
        return 0.0
    mean_ret = sum(returns) / len(returns)
    downside = [min(0, r - 0) for r in returns]  # below zero
    if not downside:
        return 999.0
    variance = sum(d ** 2 for d in downside) / (len(downside) - 1) if len(downside) > 1 else 0.0001
    std = math.sqrt(variance) if variance > 0 else 1e-10
    annual_factor = math.sqrt(36500)
    return (mean_ret * 36500 - risk_free) / (std * annual_factor) if std > 0 else 0.0

def max_drawdown(equity_curve: list[float]) -> float:
    """Maximum drawdown percentage."""
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    return max_dd

def calmar_ratio(returns: list[float], equity_curve: list[float]) -> float:
    """Calmar ratio (return / max drawdown)."""
    if len(returns) < 3:
        return 0.0
    mean_ret = sum(returns) / len(returns)
    dd = max_drawdown(equity_curve)
    if dd < 0.01:
        return 999.0
    return (mean_ret * 36500) / (dd / 100)

# ── State Reader ────────────────────────────────────────────

def read_state() -> dict:
    """Read current spot farming state."""
    if not STATE_FILE.exists():
        return {"status": "NO_DATA", "rt_count": 0}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"status": "PARSE_ERROR", "rt_count": 0}

def compute_equity_curve(pnl_total: float, peak: float) -> list[float]:
    """Reconstruct approximate equity curve."""
    # Simplified: just return [start, current]
    return [20.0, 20.0 + pnl_total]

# ── Alert System ────────────────────────────────────────────

_last_alert_ts = 0.0

def should_alert() -> bool:
    global _last_alert_ts
    now = time.time()
    if now - _last_alert_ts < ALERT_COOLDOWN_S:
        return False
    _last_alert_ts = now
    return True

def send_telegram(message: str) -> bool:
    """Send alert via daemon's Telegram or write to alert file."""
    alert_data = {
        "message": message,
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": "SPOT_RISK",
    }
    ALERT_FILE.parent.mkdir(parents=True, exist_ok=True)
    ALERT_FILE.write_text(json.dumps(alert_data))
    return True

# ── Main Monitor ────────────────────────────────────────────

def run_check() -> dict:
    """Run one health check cycle. Returns status dict."""
    state = read_state()
    rt_count = state.get("rt_count", 0)
    wins = state.get("wins", 0)
    losses = state.get("losses", 0)
    total_pnl = state.get("total_pnl", 0.0)
    peak_equity = state.get("peak_equity", 20.0)
    current_equity = state.get("current_equity", 20.0)
    consecutive = state.get("consecutive_losses", 0)
    fill_times_buy = state.get("fill_times_buy", [])
    fill_times_sell = state.get("fill_times_sell", [])

    wr = wins / (wins + losses) if (wins + losses) > 0 else 1.0
    dd_pct = (peak_equity - current_equity) / peak_equity * 100 if peak_equity > 0 else 0.0

    # P&L series (from state or approximate)
    pnl_list = state.get("pnl_history", [total_pnl]) if total_pnl else []
    returns = compute_returns(pnl_list) if len(pnl_list) >= 3 else [total_pnl / 20.0]
    equity = compute_equity_curve(total_pnl, peak_equity)

    metrics = {
        "rt_count": rt_count,
        "win_rate": round(wr, 3),
        "total_pnl": round(total_pnl, 4),
        "drawdown_pct": round(dd_pct, 2),
        "consecutive_losses": consecutive,
        "sharpe": round(sharpe_ratio(returns), 2),
        "sortino": round(sortino_ratio(returns), 2),
        "calmar": round(calmar_ratio(returns, equity), 2),
        "fill_buy_median": round(sorted(fill_times_buy)[len(fill_times_buy)//2], 1) if fill_times_buy else 0,
        "fill_sell_median": round(sorted(fill_times_sell)[len(fill_times_sell)//2], 1) if fill_times_sell else 0,
        "peak_equity": round(peak_equity, 2),
        "current_equity": round(current_equity, 2),
    }

    alerts = []
    status = "OK"

    if dd_pct > MAX_DRAWDOWN_PCT:
        alerts.append(f"🔴 DRAWDOWN {dd_pct:.1f}% > {MAX_DRAWDOWN_PCT}%!")
        status = "DRAWDOWN_ALERT"
    if consecutive >= MAX_CONSECUTIVE_LOSSES:
        alerts.append(f"🔴 {consecutive} CONSECUTIVE LOSSES!")
        status = "CONSECUTIVE_ALERT"
    if wr < MIN_WIN_RATE_WARN and rt_count >= 10:
        alerts.append(f"🟡 Win rate {wr:.0%} < {MIN_WIN_RATE_WARN:.0%}")
        if status == "OK":
            status = "WINRATE_WARN"
    if metrics["sharpe"] < MIN_SHARPE and rt_count >= 20:
        alerts.append(f"🟡 Sharpe {metrics['sharpe']:.2f} < {MIN_SHARPE}")

    if alerts and should_alert():
        msg = "📊 *SoDEX SPOT Monitor*\n" + "\n".join(alerts)
        msg += f"\nRTs:{rt_count} WR:{wr:.0%} P&L:${total_pnl:+.3f} DD:{dd_pct:.1f}%"
        send_telegram(msg)

    metrics["alerts"] = alerts
    metrics["status"] = status
    return metrics


def main():
    import argparse
    parser = argparse.ArgumentParser(description="SoDEX SPOT Risk Monitor")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--alert", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.loop:
        print("🟢 SPOT Monitor running (checks every 5min)...")
        try:
            while True:
                metrics = run_check()
                ts = datetime.now(timezone.utc).strftime("%H:%M")
                status_icon = "🟢" if metrics["status"] == "OK" else "🔴" if "ALERT" in metrics["status"] else "🟡"
                print(f"  [{ts}] {status_icon} RTs:{metrics['rt_count']} WR:{metrics['win_rate']:.0%} "
                      f"P&L:${metrics['total_pnl']:+.4f} DD:{metrics['drawdown_pct']:.1f}% "
                      f"Sharpe:{metrics['sharpe']:.2f}")
                time.sleep(CHECK_INTERVAL_S)
        except KeyboardInterrupt:
            print("\n⏹️  Stopped.")
    else:
        metrics = run_check()
        if args.json:
            print(json.dumps(metrics, indent=2))
        else:
            print("╔══════════════════════════════════════════════╗")
            print("║  SoDEX SPOT — Risk & Health Monitor         ║")
            print("╚══════════════════════════════════════════════╝")
            for k, v in metrics.items():
                if k != "alerts":
                    print(f"  {k:<20} {v}")
            if metrics["alerts"]:
                print(f"\n  ⚠️  ALERTS: {', '.join(metrics['alerts'])}")
            print(f"\n  Status: {metrics['status']}")


if __name__ == "__main__":
    main()
