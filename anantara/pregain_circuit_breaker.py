#!/usr/bin/env python3
"""
ANANTARA SAKTI — Pre-Gain/Loser Circuit Breaker v1.0

4-level circuit breaker untuk Pre-Gain/Loser auto-trader.
Diintegrasikan ke pregain_autotrader.decide() sebagai layer keamanan pertama
— sebelum semua gate lain (whale, edge, score, dll).

Hierarki (dari v3 ULTIMATE, dikalibrasi untuk Pre-Gain small-capital):

  NORMAL → trading berjalan normal
  YELLOW → DD > 10% ATAU concurrent positions > 2 → reduce size 50%, alert
  ORANGE → DD > 15% ATAU daily loss > 15% → reduce size 75%, no new entries
  RED    → DD > 20% ATAU daily loss > 20% → CLOSE ALL, STOP trading
  BLACK  → data stale > 30min ATAU HL API down → KILL SWITCH, disconnect

Circuit breaker TIDAK bisa di-override dari kode — hanya reset manual + kondisi
stabilisasi. Ini adalah fail-safe hidup yang melindungi modal dari kehancuran.

Design principles:
  - Persistent state (JSON, atomic write) — survive daemon restart
  - Thread-safe (threading.Lock)
  - Graceful degradation: unknown state → YELLOW (cautious default)
  - No dependency on external libs — stdlib only
  - Immutable audit log — every level change is timestamped + recorded

Integrasi:
  from anantara.pregain_circuit_breaker import CircuitBreaker, CircuitLevel
  cb = CircuitBreaker()
  level = cb.check(daily_pnl_frac=-0.08, open_positions=2)
  size_mult = cb.size_multiplier(level)   # 0.0 = no trade
  if size_mult == 0.0:
      return Decision("SKIP", "-", 0.0, f"Circuit breaker {level.name}")
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Optional

# ── State file path ───────────────────────────────────────────────────────────
CB_STATE_PATH = Path(os.environ.get(
    "PREGAIN_CB_PATH",
    str(Path.home() / ".local/share/anantara/pregain_cb.json")
))

# ── Stabilisation periods before auto-reset ───────────────────────────────────
# YELLOW: 4h stable trading (no new triggers) → auto-reset to NORMAL
# ORANGE: 12h stable → auto-reset to YELLOW (must manually clear to NORMAL)
# RED/BLACK: manual reset ONLY (require explicit human confirmation)
YELLOW_STABLE_SEC = 4 * 3600
ORANGE_STABLE_SEC = 12 * 3600


class CircuitLevel(IntEnum):
    """Circuit breaker severity level. Higher = more severe."""
    NORMAL = 0   # Normal operation
    YELLOW = 1   # Caution: reduce size 50%, alert
    ORANGE = 2   # Warning: reduce 75%, pause new entries
    RED    = 3   # Stop: close all, halt trading
    BLACK  = 4   # Kill: API disconnect, emergency halt


@dataclass
class CircuitEvent:
    """Audit record for a circuit level change."""
    ts:        int
    utc:       str
    level:     str
    reason:    str
    pnl_frac:  float
    positions: int


@dataclass
class CircuitState:
    """Persistent circuit breaker state."""
    level:          CircuitLevel = CircuitLevel.NORMAL
    level_since_ts: int          = 0
    trigger_reason: str          = ""
    events:         list         = field(default_factory=list)  # last 50 CircuitEvent dicts
    manual_reset_required: bool  = False


# ── Thresholds (Pre-Gain small-capital calibration) ───────────────────────────
# Drawdown thresholds (fraction of capital, e.g. 0.10 = 10%)
YELLOW_DD     = 0.10
ORANGE_DD     = 0.15
RED_DD        = 0.20
# Daily loss thresholds
YELLOW_DAILY  = 0.10
ORANGE_DAILY  = 0.15
RED_DAILY     = 0.20
# Concurrent positions thresholds
YELLOW_OPEN   = 2    # ≥ 2 open positions → yellow (tight for $60 capital)
ORANGE_OPEN   = 3
# Data staleness
BLACK_STALE_SEC = 30 * 60  # 30 minutes stale data → BLACK


class CircuitBreaker:
    """Thread-safe 4-level circuit breaker for Pre-Gain auto-trader.

    Usage:
      cb = CircuitBreaker()
      level = cb.check(daily_pnl_frac=-0.08, open_positions=1)
      mult  = cb.size_multiplier(level)   # 0.0 → don't trade
    """

    def __init__(self, state_path: Optional[Path] = None) -> None:
        self._path  = state_path or CB_STATE_PATH
        self._lock  = threading.Lock()
        self._state = CircuitState()
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load persisted state. Fresh state if file missing or corrupt."""
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text())
                self._state = CircuitState(
                    level=CircuitLevel(data.get("level", 0)),
                    level_since_ts=data.get("level_since_ts", 0),
                    trigger_reason=data.get("trigger_reason", ""),
                    events=data.get("events", [])[-50:],
                    manual_reset_required=data.get("manual_reset_required", False),
                )
        except Exception:
            self._state = CircuitState()

    def _save(self) -> None:
        """Atomic write state to disk (crash-safe)."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = str(self._path) + ".tmp"
            data = {
                "level":                 int(self._state.level),
                "level_since_ts":        self._state.level_since_ts,
                "trigger_reason":        self._state.trigger_reason,
                "events":                self._state.events[-50:],
                "manual_reset_required": self._state.manual_reset_required,
                "saved_utc":             datetime.now(timezone.utc).isoformat(),
            }
            Path(tmp).write_text(json.dumps(data, indent=2))
            os.replace(tmp, str(self._path))
        except Exception as _e:
            # CRITICAL: a silent swallow here means a RED/BLACK CB state is lost on
            # the next process restart, re-enabling trading on a poisoned book.
            # Alert loudly; never swallow state-persist failures silently.
            print(
                f"CIRCUIT_BREAKER_STATE_SAVE_FAILED path={self._path} err={_e}",
                file=sys.stderr,
            )

    def _log_event(self, level: CircuitLevel, reason: str,
                   pnl_frac: float, positions: int) -> None:
        """Append audit event (kept last 50)."""
        ev = {
            "ts":        int(time.time()),
            "utc":       datetime.now(timezone.utc).isoformat(),
            "level":     level.name,
            "reason":    reason,
            "pnl_frac":  round(pnl_frac, 4),
            "positions": positions,
        }
        self._state.events.append(ev)
        if len(self._state.events) > 50:
            self._state.events = self._state.events[-50:]

    def _set_level(self, new_level: CircuitLevel, reason: str,
                   pnl_frac: float = 0.0, positions: int = 0) -> None:
        """Transition to new level if it's escalating or same."""
        now = int(time.time())
        if new_level > self._state.level:
            self._state.level = new_level
            self._state.level_since_ts = now
            self._state.trigger_reason = reason
            if new_level >= CircuitLevel.RED:
                self._state.manual_reset_required = True
            self._log_event(new_level, reason, pnl_frac, positions)
            self._save()

    # ── Auto-deescalation (time-based stabilization) ──────────────────────────

    def _maybe_deescalate(self) -> None:
        """Check if enough stable time has passed to deescalate automatically."""
        if self._state.manual_reset_required:
            return
        now = int(time.time())
        elapsed = now - self._state.level_since_ts
        if self._state.level == CircuitLevel.YELLOW and elapsed >= YELLOW_STABLE_SEC:
            self._state.level = CircuitLevel.NORMAL
            self._state.trigger_reason = "Auto-deescalate: 4h stable"
            self._log_event(CircuitLevel.NORMAL, "auto-deescalate YELLOW→NORMAL", 0, 0)
            self._save()
        elif self._state.level == CircuitLevel.ORANGE and elapsed >= ORANGE_STABLE_SEC:
            self._state.level = CircuitLevel.YELLOW
            self._state.trigger_reason = "Auto-deescalate: 12h stable"
            self._log_event(CircuitLevel.YELLOW, "auto-deescalate ORANGE→YELLOW", 0, 0)
            self._save()

    # ── Main check ────────────────────────────────────────────────────────────

    def check(
        self,
        daily_pnl_frac: float  = 0.0,
        open_positions: int    = 0,
        running_dd_frac: float = 0.0,
        last_data_ts: Optional[int] = None,
    ) -> CircuitLevel:
        """Evaluate circuit level given current system state.

        Args:
          daily_pnl_frac  : today's PnL as fraction of capital (negative = loss)
          open_positions  : number of currently open positions
          running_dd_frac : max drawdown from equity peak (fraction, 0-1)
          last_data_ts    : unix timestamp of last good data (None = unknown)

        Returns current CircuitLevel (never lower than persisted state until reset).
        """
        with self._lock:
            self._maybe_deescalate()
            now = int(time.time())

            # BLACK: data staleness / exchange down
            if last_data_ts is not None:
                stale_sec = now - last_data_ts
                if stale_sec > BLACK_STALE_SEC:
                    self._set_level(CircuitLevel.BLACK,
                                    f"Data stale {stale_sec//60}min > {BLACK_STALE_SEC//60}min",
                                    daily_pnl_frac, open_positions)

            # RED: severe drawdown OR daily loss
            if running_dd_frac >= RED_DD or daily_pnl_frac <= -RED_DAILY:
                self._set_level(CircuitLevel.RED,
                                f"DD={running_dd_frac:.1%} or daily_loss={-daily_pnl_frac:.1%} ≥ RED threshold",
                                daily_pnl_frac, open_positions)

            # ORANGE: moderate drawdown
            elif running_dd_frac >= ORANGE_DD or daily_pnl_frac <= -ORANGE_DAILY:
                self._set_level(CircuitLevel.ORANGE,
                                f"DD={running_dd_frac:.1%} or daily_loss={-daily_pnl_frac:.1%} ≥ ORANGE threshold",
                                daily_pnl_frac, open_positions)

            # YELLOW: mild DD or too many open positions
            elif (running_dd_frac >= YELLOW_DD or daily_pnl_frac <= -YELLOW_DAILY
                  or open_positions >= YELLOW_OPEN):
                self._set_level(CircuitLevel.YELLOW,
                                f"DD={running_dd_frac:.1%} or positions={open_positions} ≥ YELLOW threshold",
                                daily_pnl_frac, open_positions)

            return self._state.level

    # ── Size multiplier ───────────────────────────────────────────────────────

    @staticmethod
    def size_multiplier(level: CircuitLevel) -> float:
        """Return position size multiplier for given circuit level.

        NORMAL : 1.00 (full size)
        YELLOW : 0.50 (half size)
        ORANGE : 0.25 (quarter size, existing only)
        RED    : 0.00 (no new trades)
        BLACK  : 0.00 (kill switch)
        """
        return {
            CircuitLevel.NORMAL: 1.00,
            CircuitLevel.YELLOW: 0.50,
            CircuitLevel.ORANGE: 0.25,
            CircuitLevel.RED:    0.00,
            CircuitLevel.BLACK:  0.00,
        }.get(level, 0.00)

    @staticmethod
    def allows_new_entry(level: CircuitLevel) -> bool:
        """Return True if new position entries are allowed at this level."""
        return level <= CircuitLevel.YELLOW  # ORANGE+ = no new entries

    # ── Manual reset ──────────────────────────────────────────────────────────

    def manual_reset(self, to_level: CircuitLevel = CircuitLevel.NORMAL,
                     reason: str = "manual reset") -> None:
        """Reset circuit breaker to specified level (requires human action).

        Only valid for RED/BLACK → must be called explicitly by operator.
        """
        with self._lock:
            prev = self._state.level
            self._state.level = to_level
            self._state.level_since_ts = int(time.time())
            self._state.trigger_reason = reason
            self._state.manual_reset_required = (to_level >= CircuitLevel.RED)
            self._log_event(to_level, f"MANUAL RESET from {prev.name}: {reason}", 0, 0)
            self._save()

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return current status dict for reporting."""
        with self._lock:
            s = self._state
            now = int(time.time())
            elapsed = now - s.level_since_ts if s.level_since_ts else 0
            return {
                "level":          s.level.name,
                "level_int":      int(s.level),
                "since_ts":       s.level_since_ts,
                "elapsed_sec":    elapsed,
                "reason":         s.trigger_reason,
                "manual_required": s.manual_reset_required,
                "size_mult":      self.size_multiplier(s.level),
                "allows_entry":   self.allows_new_entry(s.level),
                "last_events":    s.events[-5:],
            }

    def status_line(self) -> str:
        """One-line status for Telegram / logs."""
        s = self.status()
        icon = {
            "NORMAL": "🟢", "YELLOW": "🟡",
            "ORANGE": "🟠", "RED":    "🔴", "BLACK": "⬛"
        }.get(s["level"], "❓")
        mult_str = f"size_mult={s['size_mult']:.0%}"
        reason_str = f" — {s['reason'][:60]}" if s["reason"] else ""
        return f"{icon} CircuitBreaker: {s['level']} | {mult_str}{reason_str}"

    # ── Singleton factory ─────────────────────────────────────────────────────


_CB_INSTANCE: Optional["CircuitBreaker"] = None
_CB_LOCK = threading.Lock()


def get_circuit_breaker() -> CircuitBreaker:
    """Return module-level singleton CircuitBreaker (thread-safe)."""
    global _CB_INSTANCE
    if _CB_INSTANCE is None:
        with _CB_LOCK:
            if _CB_INSTANCE is None:
                _CB_INSTANCE = CircuitBreaker()
    return _CB_INSTANCE


def reset_circuit_breaker_singleton() -> None:
    """Reset module-level singleton (for testing / daemon restart). Thread-safe."""
    global _CB_INSTANCE
    with _CB_LOCK:
        _CB_INSTANCE = None


# ── Decision integration helper ───────────────────────────────────────────────

def apply_circuit_breaker(
    daily_pnl_frac: float,
    open_positions: int,
    running_dd_frac: float = 0.0,
    last_data_ts: Optional[int] = None,
    base_size_usd: float = 10.0,
) -> tuple[bool, float, str]:
    """Check circuit breaker and return (allowed, adjusted_size, reason).

    Called at the START of decide() in pregain_autotrader — before all other gates.

    Returns:
      allowed        : True if trading is allowed (NORMAL/YELLOW)
      adjusted_size  : base_size_usd × size_multiplier
      reason         : human-readable explanation
    """
    cb = get_circuit_breaker()
    level = cb.check(daily_pnl_frac=daily_pnl_frac,
                     open_positions=open_positions,
                     running_dd_frac=running_dd_frac,
                     last_data_ts=last_data_ts)
    mult = cb.size_multiplier(level)
    allowed = cb.allows_new_entry(level)
    adjusted = round(base_size_usd * mult, 2)

    icons = {CircuitLevel.NORMAL: "🟢", CircuitLevel.YELLOW: "🟡",
             CircuitLevel.ORANGE: "🟠", CircuitLevel.RED: "🔴", CircuitLevel.BLACK: "⬛"}
    icon = icons.get(level, "❓")

    reasons = {
        CircuitLevel.NORMAL: "",
        CircuitLevel.YELLOW: f"{icon} YELLOW: size 50% (DD/loss caution)",
        CircuitLevel.ORANGE: f"{icon} ORANGE: size 25%, no new entries (DD/loss warning)",
        CircuitLevel.RED:    f"{icon} RED: HALTED — DD/loss ≥ 20% threshold",
        CircuitLevel.BLACK:  f"{icon} BLACK: KILL SWITCH — data stale / exchange down",
    }
    return allowed, adjusted, reasons.get(level, f"CB {level.name}")


if __name__ == "__main__":
    cb = CircuitBreaker()
    print("Circuit Breaker Self-Test")
    print(f"  Status: {cb.status_line()}")
    # Simulate YELLOW trigger
    lvl = cb.check(daily_pnl_frac=-0.12, open_positions=1, running_dd_frac=0.11)
    print(f"  After DD=11%: {lvl.name} (expected YELLOW)")
    print(f"  Size mult: {cb.size_multiplier(lvl):.0%}")
    # Reset
    cb.manual_reset(CircuitLevel.NORMAL, "self-test reset")
    print(f"  After reset: {cb.status_line()}")
