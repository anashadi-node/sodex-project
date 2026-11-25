#!/usr/bin/env python3
"""
ANANTARA SAKTI — MODE 8 Learning System (v4.3.0)

Self-improving feedback loop for Delta-Neutral Maker Cycling.
Learns from every trade to optimize:
  - Smart pricing offset (adaptive per symbol per regime)
  - Fill rate vs spread capture trade-off
  - Position sizing based on recent success rate
  - Regime-specific parameter tuning

Follows the proven Anantara pattern:
  signal_tracker.py (honest measurement → validated hit-rates)
  calibration.py (probability calibration)
  model_registry.py (champion/challenger governance)

ARCHITECTURE:
  ┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
  │ MODE 8 trade │ ──▶ │ mode8_learner    │ ──▶ │ adaptive params │
  │  (outcome)   │     │ (running stats)  │     │ (smart_bps,     │
  └─────────────┘     │ (per-symbol)     │     │  notional, wait) │
                      │ (per-regime)     │     └─────────────────┘
                      └──────────────────┘
"""
from __future__ import annotations

import json
import os
import statistics
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import logging as _logging

log = _logging.getLogger("mode8_learner")

# ── Persistence ────────────────────────────────────────────────────────────────
LEARNER_PATH = Path(os.environ.get(
    "MODE8_LEARNER_PATH",
    str(Path.home() / ".local/share/anantara/mode8_learner.json")
))

# ── Learning config ────────────────────────────────────────────────────────────
MIN_SAMPLES = 10          # minimum trades before adapting parameters
WINDOW_RECENT = 50        # most recent trades for adaptive tuning
LEARNER_SAVE_INTERVAL = 300  # save state every 5 min

# Smart pricing adaptation bounds
SMART_BPS_MIN = 0.1        # never go below 0.1 bps
SMART_BPS_MAX = 1.5        # never go above 1.5 bps
TARGET_FILL_RATE = 0.40    # target at least 40% fill rate (both legs)
TARGET_MAKER_RATIO = 0.85  # target 85%+ maker fills

# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class SymbolStats:
    """Per-symbol rolling statistics."""
    trades: int = 0
    fills: int = 0           # trades with at least 1 leg filled
    both_legs: int = 0       # trades with both legs filled
    maker_legs: int = 0      # total maker legs across all trades
    total_legs: int = 0      # total legs attempted
    total_volume: float = 0.0
    total_cost: float = 0.0  # estimated cost (fees)
    recent_smart_bps: list[float] = field(default_factory=list)
    recent_fill_rates: list[float] = field(default_factory=list)
    current_smart_bps: float = 0.5
    current_confidence: float = 0.5  # 0-1, how confident we are in current params
    
    def update(self, result: dict) -> None:
        """Update statistics from a MODE 8 trade result."""
        self.trades += 1
        
        legs = result.get("legs_filled", 0)
        maker = result.get("legs_maker", 0)
        filled = result.get("filled", False)
        
        if filled:
            self.fills += 1
            if legs >= 2:
                self.both_legs += 1
        
        self.maker_legs += maker
        self.total_legs += max(legs, 1)  # at least 1 leg attempted
        self.total_volume += result.get("volume", 0)
        
        # Estimate cost: volume × fee rate
        vol = result.get("volume", 0)
        fee_rate = 0.00012  # 0.012% maker base
        self.total_cost += vol * fee_rate
        
        # Track recent smart_bps
        bps = result.get("smart_bps", 0)
        self.recent_smart_bps.append(bps)
        if len(self.recent_smart_bps) > WINDOW_RECENT:
            self.recent_smart_bps.pop(0)
        
        # Track recent fill rate (legs filled / legs attempted)
        fill_rate = legs / 2.0  # 2 legs attempted per DN cycle
        self.recent_fill_rates.append(fill_rate)
        if len(self.recent_fill_rates) > WINDOW_RECENT:
            self.recent_fill_rates.pop(0)
    
    def adapt(self) -> dict:
        """Compute adaptive parameter adjustments. Returns recommended changes."""
        if self.trades < MIN_SAMPLES:
            return {"action": "collecting", "samples": self.trades}
        
        recent_n = min(len(self.recent_fill_rates), WINDOW_RECENT)
        if recent_n < 5:
            return {"action": "insufficient_recent", "samples": recent_n}
        
        avg_fill = statistics.mean(self.recent_fill_rates[-recent_n:])
        maker_ratio = self.maker_legs / max(self.total_legs, 1)
        avg_bps = statistics.mean(self.recent_smart_bps[-recent_n:]) if self.recent_smart_bps else self.current_smart_bps
        
        new_bps = self.current_smart_bps
        action = "hold"
        
        # ADAPTIVE LOGIC:
        # If fill rate is too low → REDUCE smart_bps (less aggressive pricing = easier fills)
        # If fill rate is good and maker ratio high → INCREASE smart_bps (capture more spread)
        # If maker ratio dropping → REDUCE smart_bps (too aggressive)
        
        if avg_fill < TARGET_FILL_RATE * 0.5:
            # Very low fill rate — back off aggressively
            new_bps = max(SMART_BPS_MIN, self.current_smart_bps - 0.15)
            action = "reduce_aggressive"
        elif avg_fill < TARGET_FILL_RATE:
            # Below target fill — slightly reduce
            new_bps = max(SMART_BPS_MIN, self.current_smart_bps - 0.05)
            action = "reduce"
        elif avg_fill > TARGET_FILL_RATE * 1.5 and maker_ratio > TARGET_MAKER_RATIO:
            # Well above target fill + high maker ratio → can capture more
            new_bps = min(SMART_BPS_MAX, self.current_smart_bps + 0.05)
            action = "increase"
        elif avg_fill > TARGET_FILL_RATE:
            # Above target → slight increase
            new_bps = min(SMART_BPS_MAX, self.current_smart_bps + 0.02)
            action = "increase_cautious"
        
        # Clamp
        new_bps = max(SMART_BPS_MIN, min(SMART_BPS_MAX, new_bps))
        
        # Update current
        old_bps = self.current_smart_bps
        self.current_smart_bps = round(new_bps, 3)
        self.current_confidence = min(1.0, recent_n / MIN_SAMPLES)
        
        return {
            "action": action,
            "old_bps": round(old_bps, 3),
            "new_bps": round(new_bps, 3),
            "avg_fill": round(avg_fill, 3),
            "maker_ratio": round(maker_ratio, 3),
            "samples": recent_n,
            "confidence": round(self.current_confidence, 3),
        }


@dataclass
class RegimeStats:
    """Per-regime statistics for regime-specific adaptation."""
    regime: str = "RANGING"
    trades: int = 0
    fills: int = 0
    both_legs: int = 0
    total_volume: float = 0.0
    optimal_bps: float = 0.5  # learned optimal smart_bps for this regime
    
    def update(self, result: dict) -> None:
        self.trades += 1
        if result.get("filled"):
            self.fills += 1
            if result.get("legs_filled", 0) >= 2:
                self.both_legs += 1
        self.total_volume += result.get("volume", 0)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN LEARNER
# ═══════════════════════════════════════════════════════════════════════════

class Mode8Learner:
    """Self-improving feedback loop for MODE 8 Delta-Neutral Maker Cycling.
    
    Tracks every trade outcome → adapts parameters per symbol & regime.
    Persists state to disk for crash recovery.
    Thread-safe for parallel MODE 8 execution.
    """
    
    def __init__(self):
        self._lock = threading.Lock()
        self.symbols: dict[str, SymbolStats] = {}
        self.regimes: dict[str, RegimeStats] = {
            "RANGING": RegimeStats("RANGING"),
            "TRENDING": RegimeStats("TRENDING"),
            "CHAOS": RegimeStats("CHAOS"),
        }
        self.total_trades: int = 0
        self.total_volume: float = 0.0
        self.last_save: float = 0.0
        self._load()
    
    def _load(self) -> None:
        """Load persisted learner state."""
        try:
            if LEARNER_PATH.exists():
                data = json.loads(LEARNER_PATH.read_text())
                for sym, sd in data.get("symbols", {}).items():
                    ss = SymbolStats()
                    ss.trades = sd.get("trades", 0)
                    ss.fills = sd.get("fills", 0)
                    ss.both_legs = sd.get("both_legs", 0)
                    ss.maker_legs = sd.get("maker_legs", 0)
                    ss.total_legs = sd.get("total_legs", 0)
                    ss.total_volume = sd.get("total_volume", 0)
                    ss.total_cost = sd.get("total_cost", 0)
                    ss.current_smart_bps = sd.get("current_smart_bps", 0.5)
                    ss.current_confidence = sd.get("current_confidence", 0.5)
                    self.symbols[sym] = ss
                self.total_trades = data.get("total_trades", 0)
                self.total_volume = data.get("total_volume", 0)
                log.info(f"MODE8 learner loaded: {len(self.symbols)} symbols, {self.total_trades} trades, ${self.total_volume:,.0f} vol")
        except Exception as e:
            log.warning(f"MODE8 learner load failed: {e} — starting fresh")
    
    def _save(self) -> None:
        """Persist learner state (crash-safe atomic write)."""
        try:
            LEARNER_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "symbols": {},
                "total_trades": self.total_trades,
                "total_volume": self.total_volume,
                "updated": datetime.now(timezone.utc).isoformat(),
            }
            for sym, ss in self.symbols.items():
                data["symbols"][sym] = {
                    "trades": ss.trades,
                    "fills": ss.fills,
                    "both_legs": ss.both_legs,
                    "maker_legs": ss.maker_legs,
                    "total_legs": ss.total_legs,
                    "total_volume": ss.total_volume,
                    "total_cost": ss.total_cost,
                    "current_smart_bps": ss.current_smart_bps,
                    "current_confidence": ss.current_confidence,
                }
            tmp = str(LEARNER_PATH) + ".tmp"
            Path(tmp).write_text(json.dumps(data, indent=2))
            os.replace(tmp, str(LEARNER_PATH))
            self.last_save = time.time()
        except Exception as e:
            log.warning(f"MODE8 learner save failed: {e}")
    
    def record(self, symbol: str, result: dict) -> Optional[dict]:
        """Record a MODE 8 trade outcome and return adaptive recommendation.
        
        Args:
            symbol: Trading symbol (e.g., 'ADA-USD')
            result: Full mode8_dn_cycle() return dict
        
        Returns:
            Adaptation recommendation dict or None if insufficient data
        """
        with self._lock:
            # Get or create symbol stats
            if symbol not in self.symbols:
                self.symbols[symbol] = SymbolStats()
                self.symbols[symbol].current_smart_bps = result.get("smart_bps", 0.5)
            
            ss = self.symbols[symbol]
            ss.update(result)
            self.total_trades += 1
            self.total_volume += result.get("volume", 0)
            
            # Also track regime
            regime = result.get("regime", "RANGING")
            # Parse regime string like "TRENDING(ATR=1.4x)" → "TRENDING"
            regime_key = regime.split("(")[0] if "(" in regime else regime
            if regime_key in self.regimes:
                self.regimes[regime_key].update(result)
            
            # Adapt if enough data
            adaptation = ss.adapt()
            
            # Periodic save
            if time.time() - self.last_save > LEARNER_SAVE_INTERVAL:
                self._save()
            
            return adaptation
    
    def get_smart_bps(self, symbol: str, default: float = 0.5) -> float:
        """Get learned optimal smart_bps for a symbol.
        
        Falls back to default if insufficient data.
        """
        with self._lock:
            if symbol in self.symbols:
                ss = self.symbols[symbol]
                if ss.trades >= MIN_SAMPLES and ss.current_confidence > 0.3:
                    return ss.current_smart_bps
            return default
    
    def get_regime_bps(self, regime: str, default: float = 0.5) -> float:
        """Get learned optimal smart_bps for a regime."""
        regime_key = regime.split("(")[0] if "(" in regime else regime
        with self._lock:
            if regime_key in self.regimes:
                rs = self.regimes[regime_key]
                if rs.trades >= MIN_SAMPLES:
                    return rs.optimal_bps
            return default
    
    def stats_summary(self) -> dict:
        """Return summary statistics for monitoring."""
        with self._lock:
            summary = {
                "total_trades": self.total_trades,
                "total_volume": round(self.total_volume, 2),
                "symbols": {},
            }
            for sym, ss in self.symbols.items():
                fill_rate = ss.fills / max(ss.trades, 1)
                maker_ratio = ss.maker_legs / max(ss.total_legs, 1)
                summary["symbols"][sym] = {
                    "trades": ss.trades,
                    "fill_rate": round(fill_rate, 3),
                    "maker_ratio": round(maker_ratio, 3),
                    "current_bps": ss.current_smart_bps,
                    "confidence": round(ss.current_confidence, 3),
                    "volume": round(ss.total_volume, 2),
                }
            return summary
    
    def force_save(self) -> None:
        """Force immediate state persistence."""
        with self._lock:
            self._save()


# ── Global singleton ──────────────────────────────────────────────────────────
_learner: Optional[Mode8Learner] = None
_learner_lock = threading.Lock()


def get_learner() -> Mode8Learner:
    """Get or create the global MODE 8 learner singleton."""
    global _learner
    with _learner_lock:
        if _learner is None:
            _learner = Mode8Learner()
        return _learner
