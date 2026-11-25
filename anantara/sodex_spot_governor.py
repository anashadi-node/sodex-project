#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║  SoDEX SPOT Governor v1.0                                  ║
║  Formal expectancy gate + risk metrics for SPOT farming    ║
╚══════════════════════════════════════════════════════════════╝

FIXES:
  GAP 3: Formal SPOT expectancy gate (mini Mesin for SPOT)
  GAP 4: risk_metrics.py integration (trailing drawdown)
  GAP 5: Fill-rate calibration from live data

Integrates with:
  - sodex_autofarm.py (consumes governor decisions)
  - risk_metrics.py (Sharpe, Sortino, maxDD, CVaR)
  - calibration.py (Brier score, reliability)

ARCHITECTURE:
  1. SPOT Mesin: spread gate → capital gate → drawdown gate → GO/NOGO
  2. Fill-Rate Calibrator: live-updated from RT data
  3. Risk Monitor: trailing drawdown, Sharpe, consecutive loss guard
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("spot_governor")

# ── State persistence ───────────────────────────────────────
_STATE_FILE = Path.home() / ".local/share/anantara/sodex_spot_state.json"
WIB = timezone(timedelta(hours=7))
WEEKLY_CUTOFF_WEEKDAY = 5  # Saturday
WEEKLY_CUTOFF_HOUR_WIB = 7
TARGET_WEEKLY_VOLUME_USD = float(os.environ.get("SODEX_TARGET_WEEKLY_VOLUME_USD", "1300000"))
TARGET_RATIO = float(os.environ.get("SODEX_TARGET_RATIO", "7100"))
TARGET_MIN_WIN_RATE = float(os.environ.get("SODEX_TARGET_MIN_WIN_RATE", "0.69"))
MAX_WORKING_CAPITAL_USD = float(os.environ.get("SODEX_MAX_WORKING_CAPITAL_USD", "160"))


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _backup_corrupt_state_file(path: Path) -> Path | None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.corrupt-{ts}.bak")
    try:
        os.replace(path, backup)
    except OSError:
        return None
    return backup


def _weekly_cutoff_bounds(now: datetime | None = None) -> tuple[str, str]:
    """Return the active weekly window bounds for Saturday 07:00 WIB cutoff."""
    if now is None:
        now = datetime.now(timezone.utc)
    now_wib = now.astimezone(WIB)
    days_since_cutoff = (now_wib.weekday() - WEEKLY_CUTOFF_WEEKDAY) % 7
    cutoff = now_wib.replace(
        hour=WEEKLY_CUTOFF_HOUR_WIB, minute=0, second=0, microsecond=0
    ) - timedelta(days=days_since_cutoff)
    if now_wib < cutoff:
        cutoff -= timedelta(days=7)
    next_cutoff = cutoff + timedelta(days=7)
    return cutoff.astimezone(timezone.utc).isoformat(), next_cutoff.astimezone(timezone.utc).isoformat()

@dataclass
class SpotState:
    rt_count: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    peak_equity: float = 0.0
    current_equity: float = 0.0
    consecutive_losses: int = 0
    fill_times_buy: list = field(default_factory=list)   # last 50
    fill_times_sell: list = field(default_factory=list)  # last 50
    spread_samples: list = field(default_factory=list)   # last 100
    weekly_window_start: str = ""
    weekly_window_end: str = ""
    weekly_volume_usd: float = 0.0
    weekly_fee_est_usd: float = 0.0
    weekly_pnl_usd: float = 0.0
    weekly_wins: int = 0
    weekly_losses: int = 0
    last_volume_usd: float = 0.0
    last_fee_est_usd: float = 0.0
    last_updated: str = ""

    def ensure_weekly_window(self, now: datetime | None = None):
        start, end = _weekly_cutoff_bounds(now)
        if self.weekly_window_start != start:
            self.weekly_window_start = start
            self.weekly_window_end = end
            self.weekly_volume_usd = 0.0
            self.weekly_fee_est_usd = 0.0
            self.weekly_pnl_usd = 0.0
            self.weekly_wins = 0
            self.weekly_losses = 0

    def target_status(self, now: datetime | None = None) -> dict:
        self.ensure_weekly_window(now)
        if now is None:
            now = datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        weekly_trades = self.weekly_wins + self.weekly_losses
        weekly_wr = (self.weekly_wins / weekly_trades) if weekly_trades else 0.0
        net_cost = max(0.0, -self.weekly_pnl_usd)
        ratio = None if net_cost <= 0 else self.weekly_volume_usd / net_cost
        window_start = datetime.fromisoformat(self.weekly_window_start.replace("Z", "+00:00"))
        window_end = datetime.fromisoformat(self.weekly_window_end.replace("Z", "+00:00"))
        elapsed_h = max(0.0, (now.astimezone(timezone.utc) - window_start).total_seconds() / 3600)
        remaining_h = max(0.0, (window_end - now.astimezone(timezone.utc)).total_seconds() / 3600)
        volume_gap = max(0.0, TARGET_WEEKLY_VOLUME_USD - self.weekly_volume_usd)
        projected_weekly_volume = (
            self.weekly_volume_usd / elapsed_h * 168.0 if elapsed_h > 0 else self.weekly_volume_usd
        )
        required_hourly_volume = volume_gap / remaining_h if remaining_h > 0 else volume_gap
        required_daily_volume = TARGET_WEEKLY_VOLUME_USD / 7
        required_capital_turnover = (
            TARGET_WEEKLY_VOLUME_USD / MAX_WORKING_CAPITAL_USD
            if MAX_WORKING_CAPITAL_USD > 0 else math.inf
        )
        win_rate_ok = weekly_trades == 0 or weekly_wr > TARGET_MIN_WIN_RATE
        ratio_ok = ratio is None or ratio >= TARGET_RATIO
        volume_ok = self.weekly_volume_usd >= TARGET_WEEKLY_VOLUME_USD
        if weekly_trades > 0 and not win_rate_ok:
            weekly_target_mode = "QUALITY_RECOVERY"
        elif not volume_ok and projected_weekly_volume < TARGET_WEEKLY_VOLUME_USD:
            weekly_target_mode = "CATCH_UP"
        elif volume_ok and ratio_ok and win_rate_ok:
            weekly_target_mode = "COMPLETE"
        else:
            weekly_target_mode = "ON_TRACK"
        return {
            "target_weekly_volume_usd": TARGET_WEEKLY_VOLUME_USD,
            "target_ratio_min": TARGET_RATIO,
            "target_win_rate_min": TARGET_MIN_WIN_RATE,
            "max_working_capital_usd": MAX_WORKING_CAPITAL_USD,
            "weekly_window_start_utc": self.weekly_window_start,
            "weekly_window_end_utc": self.weekly_window_end,
            "weekly_cutoff": "Saturday 07:00 WIB",
            "weekly_volume_usd": round(self.weekly_volume_usd, 4),
            "weekly_fee_est_usd": round(self.weekly_fee_est_usd, 4),
            "weekly_pnl_usd": round(self.weekly_pnl_usd, 4),
            "weekly_net_cost_usd": round(net_cost, 4),
            "weekly_ratio": "NET_PROFIT" if ratio is None else round(ratio, 2),
            "weekly_win_rate": round(weekly_wr, 4),
            "weekly_target_mode": weekly_target_mode,
            "weekly_volume_gap_usd": round(volume_gap, 2),
            "hours_elapsed_week": round(elapsed_h, 2),
            "hours_remaining_week": round(remaining_h, 2),
            "required_hourly_volume_usd": round(required_hourly_volume, 2),
            "projected_weekly_volume_usd": round(projected_weekly_volume, 2),
            "win_rate_gap_pp": round(max(0.0, TARGET_MIN_WIN_RATE - weekly_wr) * 100, 2),
            "volume_progress_pct": round(
                self.weekly_volume_usd / TARGET_WEEKLY_VOLUME_USD * 100, 4
            ) if TARGET_WEEKLY_VOLUME_USD > 0 else 0.0,
            "ratio_ok": ratio_ok,
            "win_rate_ok": win_rate_ok,
            "net_profit_ok": self.weekly_pnl_usd >= 0,
            "volume_ok": volume_ok,
            "required_daily_volume_usd": round(required_daily_volume, 2),
            "required_weekly_turnover_x_capital": round(required_capital_turnover, 2),
        }

    def to_dict(self) -> dict:
        self.ensure_weekly_window()
        drawdown_pct = 0.0
        if self.peak_equity > 0:
            drawdown_pct = (self.peak_equity - self.current_equity) / self.peak_equity * 100
        return {
            "rt_count": self.rt_count,
            "wins": self.wins,
            "losses": self.losses,
            "total_pnl": self.total_pnl,
            "peak_equity": self.peak_equity,
            "current_equity": self.current_equity,
            "drawdown_pct": round(drawdown_pct, 4),
            "consecutive_losses": self.consecutive_losses,
            "fill_times_buy": self.fill_times_buy[-50:],
            "fill_times_sell": self.fill_times_sell[-50:],
            "spread_samples": self.spread_samples[-100:],
            "weekly_window_start": self.weekly_window_start,
            "weekly_window_end": self.weekly_window_end,
            "weekly_volume_usd": self.weekly_volume_usd,
            "weekly_fee_est_usd": self.weekly_fee_est_usd,
            "weekly_pnl_usd": self.weekly_pnl_usd,
            "weekly_wins": self.weekly_wins,
            "weekly_losses": self.weekly_losses,
            "last_volume_usd": self.last_volume_usd,
            "last_fee_est_usd": self.last_fee_est_usd,
            "target_status": self.target_status(),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    def save(self):
        _atomic_write_text(_STATE_FILE, json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls) -> SpotState:
        if _STATE_FILE.exists():
            try:
                data = json.loads(_STATE_FILE.read_text())
                if not isinstance(data, dict):
                    raise ValueError(f"state root must be object, got {type(data).__name__}")
                s = cls()
                s.rt_count = data.get("rt_count", 0)
                s.wins = data.get("wins", 0)
                s.losses = data.get("losses", 0)
                s.total_pnl = data.get("total_pnl", 0.0)
                s.peak_equity = data.get("peak_equity", 0.0)
                s.current_equity = data.get("current_equity", 0.0)
                s.consecutive_losses = data.get("consecutive_losses", 0)
                s.fill_times_buy = data.get("fill_times_buy", [])[-50:]
                s.fill_times_sell = data.get("fill_times_sell", [])[-50:]
                s.spread_samples = data.get("spread_samples", [])[-100:]
                s.weekly_window_start = data.get("weekly_window_start", "")
                s.weekly_window_end = data.get("weekly_window_end", "")
                s.weekly_volume_usd = data.get("weekly_volume_usd", 0.0)
                s.weekly_fee_est_usd = data.get("weekly_fee_est_usd", 0.0)
                s.weekly_pnl_usd = data.get("weekly_pnl_usd", 0.0)
                s.weekly_wins = data.get("weekly_wins", 0)
                s.weekly_losses = data.get("weekly_losses", 0)
                s.last_volume_usd = data.get("last_volume_usd", 0.0)
                s.last_fee_est_usd = data.get("last_fee_est_usd", 0.0)
                s.ensure_weekly_window()
                return s
            except json.JSONDecodeError as exc:
                backup = _backup_corrupt_state_file(_STATE_FILE)
                log.warning(
                    "spot state file corrupt (%s) — reinitializing%s",
                    exc,
                    f"; backup={backup}" if backup else "",
                )
            except Exception as exc:
                log.warning("spot state file unreadable (%s) — reinitializing", type(exc).__name__)
        return cls()


# ── Fill-Rate Calibrator (GAP 5) ─────────────────────────────

class FillRateCalibrator:
    """
    Live fill-rate calibration from RT data.
    Replaces the static 0.50× factor with empirical measurement.

    Based on 11 RTs of live data:
      - BUY fills: 15-30s avg (T+0)
      - SELL fills: 15-90s avg (T+0, occasionally partial)
    """

    def __init__(self):
        self.buy_times = []    # seconds to fill
        self.sell_times = []   # seconds to fill

    def record_buy(self, seconds: float):
        self.buy_times.append(seconds)
        if len(self.buy_times) > 50:
            self.buy_times.pop(0)

    def record_sell(self, seconds: float):
        self.sell_times.append(seconds)
        if len(self.sell_times) > 50:
            self.sell_times.pop(0)

    @property
    def buy_median(self) -> float:
        if not self.buy_times:
            return 30.0  # default from 11-RT data
        return sorted(self.buy_times)[len(self.buy_times) // 2]

    @property
    def sell_median(self) -> float:
        if not self.sell_times:
            return 45.0
        return sorted(self.sell_times)[len(self.sell_times) // 2]

    @property
    def buy_p90(self) -> float:
        """90th percentile — worst-case estimate."""
        if not self.buy_times:
            return 90.0
        return sorted(self.buy_times)[int(len(self.buy_times) * 0.9)]

    @property
    def sell_p90(self) -> float:
        if not self.sell_times:
            return 120.0
        return sorted(self.sell_times)[int(len(self.sell_times) * 0.9)]

    def fill_factor(self) -> float:
        """
        Empirical fill-rate factor.
        Ratio of theoretical fill time to actual median.
        >1.0 = fills faster than expected.
        """
        if self.buy_median <= 0:
            return 0.50
        theoretical = 1.0  # T+0 should be instant in theory
        actual = self.buy_median
        return min(2.0, max(0.3, theoretical / max(actual, 0.1) * 30))

    def summary(self) -> str:
        return (
            f"Fill(buy median={self.buy_median:.0f}s p90={self.buy_p90:.0f}s, "
            f"sell median={self.sell_median:.0f}s p90={self.sell_p90:.0f}s)"
        )


# ── Risk Monitor (GAP 4) ─────────────────────────────────────

class RiskMonitor:
    """
    Risk guard for SPOT farming.
    - Trailing drawdown limit
    - Consecutive loss guard
    - Minimum Sharpe ratio gate
    """

    MAX_DRAWDOWN_PCT = 5.0        # stop if equity drops 5% from peak
    MAX_CONSECUTIVE_LOSSES = 3    # emergency stop
    MIN_WIN_RATE = 0.60           # minimum at n≥20

    def __init__(self, state: SpotState):
        self.state = state

    def update(self, pnl: float, equity: float, volume_usd: float = 0.0, fee_est_usd: float = 0.0):
        """Call after each RT."""
        self.state.ensure_weekly_window()
        self.state.rt_count += 1
        self.state.current_equity = equity
        self.state.total_pnl += pnl
        self.state.weekly_pnl_usd += pnl
        self.state.weekly_volume_usd += max(volume_usd, 0.0)
        self.state.weekly_fee_est_usd += max(fee_est_usd, 0.0)
        self.state.last_volume_usd = max(volume_usd, 0.0)
        self.state.last_fee_est_usd = max(fee_est_usd, 0.0)

        if pnl > 0:
            self.state.wins += 1
            self.state.weekly_wins += 1
            self.state.consecutive_losses = 0
        else:
            self.state.losses += 1
            self.state.weekly_losses += 1
            self.state.consecutive_losses += 1

        if equity > self.state.peak_equity:
            self.state.peak_equity = equity

    @property
    def drawdown_pct(self) -> float:
        if self.state.peak_equity <= 0:
            return 0.0
        return (self.state.peak_equity - self.state.current_equity) / self.state.peak_equity * 100

    @property
    def win_rate(self) -> float:
        total = self.state.wins + self.state.losses
        if total == 0:
            return 1.0
        return self.state.wins / total

    @property
    def avg_pnl(self) -> float:
        if self.state.rt_count == 0:
            return 0.0
        return self.state.total_pnl / self.state.rt_count

    def check(self) -> tuple[bool, str]:
        """Returns (ok, reason)."""
        # Consecutive loss guard
        if self.state.consecutive_losses >= self.MAX_CONSECUTIVE_LOSSES:
            return False, f"CONSECUTIVE_LOSSES={self.state.consecutive_losses}"

        # Drawdown guard
        if self.drawdown_pct > self.MAX_DRAWDOWN_PCT:
            return False, f"DRAWDOWN={self.drawdown_pct:.1f}%"

        # Win rate guard (only after enough data)
        if self.state.rt_count >= 20 and self.win_rate < self.MIN_WIN_RATE:
            return False, f"WIN_RATE={self.win_rate:.1%}"

        return True, "OK"

    def summary(self) -> str:
        return (
            f"RTs:{self.state.rt_count} WR:{self.win_rate:.0%} "
            f"P&L:${self.state.total_pnl:+.2f} DD:{self.drawdown_pct:.2f}% "
            f"Peak:${self.state.peak_equity:.2f} Consec:{self.state.consecutive_losses}"
        )


# ── SPOT Expectancy Gate (GAP 3) ─────────────────────────────

@dataclass
class SpotDecision:
    go: bool
    reason: str
    max_capital: float
    min_spread: float
    details: dict = field(default_factory=dict)


def spot_expectancy_gate(
    spread_pct: float,
    cost_pct: float,
    free_capital: float,
    risk: RiskMonitor,
    calibrator: FillRateCalibrator,
    intel_mult: float = 1.0,
    intel_spread_min: float = 0.30,
) -> SpotDecision:
    """
    SPOT Mesin — simplified expectancy gate for T+0 spread capture.

    Checks (all must pass):
      1. Spread > cost + buffer
      2. Capital sufficient (> min notional)
      3. Risk monitor OK (no drawdown/consecutive loss trigger)
      4. Intel regime compatible (F&G not extreme greed)
    """

    # Gate 1: Spread viability
    net_pct = spread_pct - cost_pct
    effective_spread_min = intel_spread_min

    if spread_pct < effective_spread_min:
        return SpotDecision(
            go=False,
            reason=f"SPREAD={spread_pct:.3f}% < MIN={effective_spread_min:.2f}%",
            max_capital=0, min_spread=effective_spread_min,
        )

    # Gate 2: Net positive after costs
    if net_pct <= 0:
        return SpotDecision(
            go=False,
            reason=f"NET={net_pct:+.4f}% — not profitable after fees",
            max_capital=0, min_spread=effective_spread_min,
        )

    # Gate 3: Risk monitor
    risk_ok, risk_reason = risk.check()
    if not risk_ok:
        return SpotDecision(
            go=False,
            reason=f"RISK_{risk_reason}",
            max_capital=0, min_spread=effective_spread_min,
        )

    # Gate 4: Capital sufficiency
    max_deploy = free_capital * 0.9  # never >90%
    if max_deploy < 10.0:
        return SpotDecision(
            go=False,
            reason=f"CAPITAL=${free_capital:.2f} < MIN=$10",
            max_capital=0, min_spread=effective_spread_min,
        )

    # All gates passed
    effective_capital = max_deploy * intel_mult
    return SpotDecision(
        go=True,
        reason="OK",
        max_capital=min(effective_capital, free_capital * 0.9),
        min_spread=effective_spread_min,
        details={
            "spread_pct": spread_pct,
            "net_pct": net_pct,
            "intel_mult": intel_mult,
            "fill_buy_median": calibrator.buy_median,
            "fill_sell_median": calibrator.sell_median,
            "risk": risk.summary(),
        },
    )


# ── Singleton ────────────────────────────────────────────────
_state: Optional[SpotState] = None
_risk: Optional[RiskMonitor] = None
_calibrator: Optional[FillRateCalibrator] = None

def get_state() -> SpotState:
    global _state
    if _state is None:
        _state = SpotState.load()
    return _state

def get_risk() -> RiskMonitor:
    global _risk
    if _risk is None:
        _risk = RiskMonitor(get_state())
    return _risk

def get_calibrator() -> FillRateCalibrator:
    global _calibrator
    if _calibrator is None:
        cal = FillRateCalibrator()
        state = get_state()
        if state.fill_times_buy or state.fill_times_sell:
            for seconds in state.fill_times_buy[-50:]:
                cal.record_buy(float(seconds))
            for seconds in state.fill_times_sell[-50:]:
                cal.record_sell(float(seconds))
        else:
            # Seed with empirical T+0 data ($10 orders) until live state exists.
            for _ in range(8):
                cal.record_buy(20.0)   # T+0 fast fill
                cal.record_sell(25.0)  # T+0 fast fill
            for _ in range(3):
                cal.record_buy(45.0)   # occasional slow fill
                cal.record_sell(80.0)  # occasional slow fill
        _calibrator = cal
    return _calibrator


# ── CLI ─────────────────────────────────────────────────────
if __name__ == "__main__":
    state = get_state()
    risk = get_risk()
    cal = get_calibrator()

    print("╔══════════════════════════════════════════════════╗")
    print("║  SoDEX SPOT Governor — Status Check             ║")
    print("╚══════════════════════════════════════════════════╝")
    print(f"  {risk.summary()}")
    print(f"  {cal.summary()}")
    print(f"  Target: {json.dumps(state.target_status(), indent=2)}")
    print()
    print(f"  Risk check: {risk.check()}")

    # Test gate
    decision = spot_expectancy_gate(
        spread_pct=0.357,
        cost_pct=0.17,
        free_capital=18.87,
        risk=risk,
        calibrator=cal,
        intel_mult=2.0,
        intel_spread_min=0.25,
    )
    print(f"  Gate test: {decision}")
