#!/usr/bin/env python3
"""
ANANTARA SAKTI — River Fill-Probability Predictor (Maker Mode Accelerator)

THE KEY to achieving 1:6,400+ ratio: predict whether a maker (GTX) order posted
at bid/ask will fill within a time budget, BEFORE we commit capital to the leg.

Why this matters:
  • MODE 2 maker scalp posts post-only orders at bid/ask
  • If they don't fill → no volume, time wasted, opportunity cost
  • If we can predict fill probability → skip low-fill-prob snapshots
  • Result: higher fill rate → higher ratio → closer to 1:7,500 target

ARCHITECTURE:
  OBI snapshot (4s) ─► feature builder ─► River classifier ─► fill_prob (0-1)
                                              │
                                        Trained on: "did mid cross my price
                                        within N seconds after this snapshot?"

TRAINING LABELS (from trades data):
  For a BUY at bid: did a trade occur at ≤ bid within 7s?
  For a SELL at ask: did a trade occur at ≥ ask within 7s?

This is RIGOROUSLY CAUSAL: labels come from the FUTURE (next N seconds of trades),
features come from the PRESENT (current OBI snapshot). No look-ahead.

Run: python3 scripts/research/river_fill_predictor.py backtest --symbol BTC-USD
"""
from __future__ import annotations
import json
import os
import sys
import time
import bisect
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

try:
    from river import (
        linear_model, ensemble, tree, preprocessing,
        metrics, drift, compose, optim, stream, stats
    )
    HAS_RIVER = True
except ImportError:
    HAS_RIVER = False
    print("⚠️ River not installed. Run: pip install river")

# ── Paths ────────────────────────────────────────────────────────────
PROJECT_DIR = Path(os.environ.get("ANANTARA_DIR",
                    str(Path.home() / "anantara-sakti")))
OBI_DIR = PROJECT_DIR / "freqtrade_user_data" / "data" / "sodex" / "obi"
TRADES_DIR = PROJECT_DIR / "freqtrade_user_data" / "data" / "sodex" / "trades"

# Time horizons for fill prediction (seconds)
FILL_HORIZONS = [7, 15, 30]

# ── Feature Builder ──────────────────────────────────────────────────
class FillFeatures:
    """Build features from OBI snapshot that predict fill likelihood.
    
    Key insight: fill probability depends on:
    1. Book pressure (obi5/10/20) — which side has more resting orders
    2. Spread — wider spread = less likely to get filled at touch
    3. Recent trade rate — high activity = higher fill chance
    4. Volatility — high vol = more price movement to hit our level
    """
    
    def __init__(self):
        self._n = 0
        self._prev_mid = 0.0
        self._prev_bv20 = 0.0
        self._prev_av20 = 0.0
        
        # Running statistics
        self._spread_mean = stats.Mean()
        self._spread_var = stats.Var()
        self._trade_rate = stats.Mean()  # rolling estimate of trades/second
        
        # Recent trade timestamps for rate estimation
        self._trade_times: list[float] = []
        self._last_ts = 0.0
    
    def update_obi(self, snap: dict) -> dict:
        """Extract features from one OBI snapshot."""
        mid = float(snap.get("mid", 0) or 0)
        spread_raw = float(snap.get("spread", 0) or 0)
        obi5 = float(snap.get("obi5", 0) or 0)
        obi10 = float(snap.get("obi10", 0) or 0)
        obi20 = float(snap.get("obi20", 0) or 0)
        bv20 = float(snap.get("bv20", 0) or 0)
        av20 = float(snap.get("av20", 0) or 0)
        bbv = float(snap.get("bbv", 0) or 0)
        ts = float(snap.get("ts", 0) or 0) / 1000  # ms → s
        
        if mid <= 0:
            return {}
        
        spread_pct = spread_raw / mid if mid > 0 else 0
        
        # Book pressure features
        total_vol = bv20 + av20
        vol_imbalance = (bv20 - av20) / total_vol if total_vol > 0 else 0
        
        # Delta features (1-step changes)
        delta_mid = mid - self._prev_mid if self._prev_mid > 0 else 0
        delta_bv = bv20 - self._prev_bv20 if self._prev_bv20 > 0 else 0
        delta_av = av20 - self._prev_av20 if self._prev_av20 > 0 else 0
        
        # Volume delta (liquidity changing)
        vol_delta = delta_bv + delta_av  # positive = more liquidity arriving
        
        # Trade rate estimate (trades per second from recent window)
        if self._trade_times:
            now = ts
            # Count trades in last 30 seconds
            recent = [t for t in self._trade_times if now - t < 30]
            trade_rate = len(recent) / 30.0 if recent else 0
            self._trade_rate.update(trade_rate)
        else:
            trade_rate = 0
        
        # Update running stats
        self._spread_mean.update(spread_pct)
        self._spread_var.update(spread_pct)
        
        # Update prev
        self._prev_mid = mid
        self._prev_bv20 = bv20
        self._prev_av20 = av20
        self._last_ts = ts
        self._n += 1
        
        spread_volatility = self._spread_var.get() ** 0.5 if self._spread_var.get() > 0 else 0
        avg_spread = self._spread_mean.get()
        
        return {
            # Core OBI signals
            "obi5": obi5,
            "obi10": obi10,
            "obi20": obi20,
            "spread_pct": spread_pct,
            "spread_vs_avg": spread_pct - avg_spread if avg_spread > 0 else 0,
            "spread_vol": spread_volatility,
            
            # Volume/pressure
            "vol_imbalance": vol_imbalance,
            "bbv_ratio": bbv,
            "bv20": bv20,
            "av20": av20,
            "total_vol": total_vol,
            "vol_delta": vol_delta,
            
            # Price dynamics
            "delta_mid_pct": delta_mid / mid if mid > 0 else 0,
            
            # Activity
            "trade_rate": trade_rate,
            
            # Meta
            "n_samples": self._n,
        }
    
    def record_trade(self, trade_ts: float):
        """Record a trade timestamp for rate estimation."""
        self._trade_times.append(trade_ts / 1000 if trade_ts > 1e10 else trade_ts)
        if len(self._trade_times) > 200:
            self._trade_times = self._trade_times[-100:]


# ── Label Builder (CAUSAL — uses future trades) ──────────────────────
def build_labels(obi_snapshot: dict, future_trades: list[dict],
                 horizons: list[int] = FILL_HORIZONS) -> dict:
    """Build fill labels from future trades AFTER this snapshot.
    
    CAUSAL: only uses trades with timestamp > obi snapshot timestamp.
    
    Returns: {f"fill_{h}s_bid": bool, f"fill_{h}s_ask": bool, ...}
    """
    obi_ts = float(obi_snapshot.get("ts", 0)) / 1000  # ms → s
    bid = float(obi_snapshot.get("bid", 0) or 0)
    ask = float(obi_snapshot.get("ask", 0) or 0)
    
    labels = {}
    
    for h in horizons:
        cutoff = obi_ts + h
        bid_filled = False
        ask_filled = False
        
        for trade in future_trades:
            trade_ts = float(trade.get("ts", 0)) / 1000
            if trade_ts < obi_ts:
                continue  # past trade (shouldn't happen)
            if trade_ts > cutoff:
                break  # beyond horizon
            
            trade_px = float(trade.get("price", 0) or 0)
            trade_side = trade.get("side", "")
            
            if trade_px <= 0:
                continue
            
            # A buy at bid fills if a SELL trade occurs at ≤ bid price
            # (someone sold into our bid)
            if trade_px <= bid and not bid_filled:
                bid_filled = True
            
            # A sell at ask fills if a BUY trade occurs at ≥ ask price
            # (someone bought from our ask)
            if trade_px >= ask and not ask_filled:
                ask_filled = True
            
            if bid_filled and ask_filled:
                break
        
        labels[f"fill_{h}s_bid"] = bid_filled
        labels[f"fill_{h}s_ask"] = ask_filled
    
    return labels


# ── River Fill Predictor ─────────────────────────────────────────────
class FillPredictor:
    """Online classifier: given OBI features, predict P(fill within horizon).
    
    Uses ALMA classifier (robust to noisy microstructure labels) with
    ADWIN drift detection to adapt to changing market conditions.
    """
    
    def __init__(self, horizon: int, side: str = "bid"):
        self.horizon = horizon
        self.side = side  # "bid" or "ask"
        self.label_key = f"fill_{horizon}s_{side}"
        
        if not HAS_RIVER:
            return
        
        self._scaler = preprocessing.StandardScaler()
        self._model = linear_model.ALMAClassifier(
            p=2, alpha=0.85, B=1.0, C=1.0)
        
        # Performance tracking
        self._accuracy = metrics.Accuracy()
        self._precision = metrics.Precision()
        self._recall = metrics.Recall()
        self._f1 = metrics.F1()
        self._auc = metrics.ROCAUC()
        
        # Drift detection
        self._error_drift = drift.ADWIN(delta=0.002)
        
        # Calibration tracking
        self._brier = 0.0
        self._brier_n = 0
        
        self._n = 0
        self._n_filled = 0
        self._drifts = 0
    
    def predict_proba(self, features: dict) -> float:
        """Return P(fill) ∈ [0, 1]."""
        if not HAS_RIVER or self._n < 10:
            return 0.5
        
        x = {k: v for k, v in features.items() 
             if isinstance(v, (int, float)) and k != "n_samples"}
        
        self._scaler.learn_one(x)
        x_scaled = self._scaler.transform_one(x)
        
        try:
            proba = self._model.predict_proba_one(x_scaled)
            return proba.get(True, 0.5)
        except Exception:
            return 0.5
    
    def learn(self, features: dict, filled: bool):
        """Online update."""
        if not HAS_RIVER:
            return
        
        x = {k: v for k, v in features.items()
             if isinstance(v, (int, float)) and k != "n_samples"}
        
        self._scaler.learn_one(x)
        x_scaled = self._scaler.transform_one(x)
        
        try:
            self._model.learn_one(x_scaled, filled)
        except Exception:
            pass
        
        # Track metrics
        try:
            prob = self._model.predict_proba_one(x_scaled).get(True, 0.5)
            pred = prob > 0.5
            self._accuracy.update(filled, pred)
            self._precision.update(filled, pred)
            self._recall.update(filled, pred)
            self._f1.update(filled, pred)
            self._auc.update(filled, prob)
        except Exception:
            pass
        
        # Brier score (calibration)
        try:
            prob = self.predict_proba(features)
            self._brier = (self._brier * self._brier_n + (prob - float(filled))**2) / (self._brier_n + 1)
            self._brier_n += 1
        except Exception:
            pass
        
        # Drift detection
        try:
            prob = self.predict_proba(features)
            pred_correct = (prob > 0.5) == filled
            self._error_drift.update(int(not pred_correct))
            if self._error_drift.drift_detected and self._n > 100:
                self._drifts += 1
                self._model = linear_model.ALMAClassifier(p=2, alpha=0.85, B=1.0, C=1.0)
                self._scaler = preprocessing.StandardScaler()
        except Exception:
            pass
        
        self._n += 1
        if filled:
            self._n_filled += 1
    
    def summary(self) -> dict:
        base_fill_rate = self._n_filled / max(self._n, 1)
        return {
            "horizon": f"{self.horizon}s",
            "side": self.side,
            "n_samples": self._n,
            "n_filled": self._n_filled,
            "base_rate": round(base_fill_rate, 4),
            "accuracy": self._accuracy.get() if HAS_RIVER else 0,
            "precision": self._precision.get() if HAS_RIVER else 0,
            "recall": self._recall.get() if HAS_RIVER else 0,
            "f1": self._f1.get() if HAS_RIVER else 0,
            "auc": self._auc.get() if HAS_RIVER else 0,
            "brier": round(self._brier, 4),
            "drifts": self._drifts,
        }


# ── Backtest Runner ──────────────────────────────────────────────────
def backtest_fill_prediction(symbol: str, horizon: int = 7,
                             max_snapshots: int = 20000) -> dict:
    """Run fill-prediction backtest on historical OBI + trades data.
    
    For each OBI snapshot:
    1. Extract features (current state)
    2. Look at future trades to build labels (causal)
    3. Predict fill probability
    4. Learn from actual outcome
    """
    # Load OBI data — match trades date range for valid labels
    obi_files = sorted(OBI_DIR.glob("obi_*.jsonl"))
    trades_files = sorted(TRADES_DIR.glob("trades_*.jsonl"))
    
    # Determine date range from trades files
    trade_dates = set()
    for f in trades_files:
        # Extract YYYYMMDD from trades_YYYYMMDD.jsonl
        stem = f.stem  # trades_20260524
        date_part = stem.replace("trades_", "")
        if date_part.isdigit() and len(date_part) == 8:
            trade_dates.add(date_part)
    
    # Only load OBI from dates we have trades for
    obi_files_filtered = [f for f in obi_files 
                          if f.stem.replace("obi_", "") in trade_dates]
    
    if not obi_files_filtered:
        print(f"No OBI files matching trade dates: {trade_dates}")
        return {}
    
    print(f"=== River Fill Predictor: {symbol} {horizon}s ===\n")
    print(f"  OBI files (matching trades): {len(obi_files_filtered)}")
    print(f"  Trade files: {len(trades_files)}")
    
    # Load all snapshots + trades
    obi_snaps = []
    for f in obi_files_filtered:
        with open(f) as fh:
            for line in fh:
                snap = json.loads(line)
                if snap.get("sym") == symbol:
                    obi_snaps.append(snap)
        if len(obi_snaps) >= max_snapshots:
            break
    
    all_trades = []
    for f in trades_files:
        with open(f) as fh:
            for line in fh:
                trade = json.loads(line)
                if trade.get("sym") == symbol:
                    all_trades.append(trade)
    
    obi_snaps = obi_snaps[:max_snapshots]
    print(f"  OBI snapshots : {len(obi_snaps):,}")
    print(f"  Trades        : {len(all_trades):,}")
    
    if len(obi_snaps) < 100:
        return {}
    
    # Build predictors for bid + ask
    features = FillFeatures()
    bid_model = FillPredictor(horizon, "bid")
    ask_model = FillPredictor(horizon, "ask")
    
    # Pre-sort trades by timestamp for efficient lookup
    all_trades.sort(key=lambda t: float(t.get("ts", 0)))
    trade_timestamps = [float(t.get("ts", 0)) for t in all_trades]
    
    if not trade_timestamps:
        print("  No trades data!")
        return {}
    
    min_trade_ms = trade_timestamps[0]
    max_trade_ms = trade_timestamps[-1]
    skipped_no_trades = 0
    
    # Binary search helper
    def trades_in_window(start_ms: float, end_ms: float) -> list[dict]:
        """Return trades with ts in [start_ms, end_ms) using binary search."""
        lo = bisect.bisect_left(trade_timestamps, start_ms)
        hi = bisect.bisect_left(trade_timestamps, end_ms)
        return all_trades[lo:hi]
    
    results = []
    t0 = time.time()
    
    for i in range(len(obi_snaps) - 5):
        snap = obi_snaps[i]
        snap_ts_ms = float(snap.get("ts", 0))
        snap_ts = snap_ts_ms / 1000
        
        # Skip snapshots before first trade data is available
        if snap_ts_ms < min_trade_ms - 5000:
            skipped_no_trades += 1
            continue
        if snap_ts_ms > max_trade_ms - (horizon + 5) * 1000:
            continue  # no future trades possible
        
        # Record trades up to this snapshot for feature building
        recent_trades = trades_in_window(snap_ts_ms - 30000, snap_ts_ms)
        for t in recent_trades[-50:]:  # last 50 trades for rate
            features.record_trade(float(t.get("ts", 0)))
        
        # Build features from current snapshot
        feats = features.update_obi(snap)
        if not feats or feats.get("n_samples", 0) < 50:
            continue
        
        # Build labels from FUTURE trades (causal) — binary search
        future_trades = trades_in_window(
            snap_ts_ms + 1,  # strictly after snapshot
            snap_ts_ms + (horizon + 2) * 1000  # horizon + buffer
        )
        
        labels = build_labels(snap, future_trades, [horizon])
        label_key = f"fill_{horizon}s"
        
        # Predict + learn for bid
        bid_prob = bid_model.predict_proba(feats)
        bid_filled = labels.get(f"fill_{horizon}s_bid", False)
        bid_model.learn(feats, bid_filled)
        
        # Predict + learn for ask
        ask_prob = ask_model.predict_proba(feats)
        ask_filled = labels.get(f"fill_{horizon}s_ask", False)
        ask_model.learn(feats, ask_filled)
        
        results.append({
            "i": i,
            "bid_prob": round(bid_prob, 3),
            "ask_prob": round(ask_prob, 3),
            "bid_filled": bid_filled,
            "ask_filled": ask_filled,
        })
        
        if (i + 1) % 5000 == 0:
            elapsed = time.time() - t0
            bs = bid_model.summary()
            print(f"  ... {i+1}/{len(obi_snaps)} ({elapsed:.1f}s)")
            print(f"      bid: acc={bs['accuracy']:.3f} auc={bs['auc']:.3f} "
                  f"base_rate={bs['base_rate']:.3f} drifts={bs['drifts']}")
    
    elapsed = time.time() - t0
    
    # ── Results ──
    bid_s = bid_model.summary()
    ask_s = ask_model.summary()
    
    print(f"\n  ═══ FILL PREDICTOR RESULTS ({elapsed:.1f}s) ═══")
    print(f"\n  ── BID (buy at bid) {horizon}s ──")
    _print_model_summary(bid_s)
    print(f"\n  ── ASK (sell at ask) {horizon}s ──")
    _print_model_summary(ask_s)
    
    # Utility assessment
    print(f"\n  ── MAKER MODE UTILITY ──")
    for model_s, name in [(bid_s, "BID"), (ask_s, "ASK")]:
        if model_s['auc'] > 0.60:
            print(f"  ✅ {name}: AUC {model_s['auc']:.3f} > 0.60 — "
                  f"USEFUL for filtering (skip when prob < threshold)")
        elif model_s['auc'] > 0.55:
            print(f"  ⚠️ {name}: AUC {model_s['auc']:.3f} — marginal, "
                  f"may help at extremes")
        else:
            print(f"  ❌ {name}: AUC {model_s['auc']:.3f} ≤ 0.55 — "
                  f"not reliably better than base rate")
    
    # Calibration check
    for model_s, name in [(bid_s, "BID"), (ask_s, "ASK")]:
        brier = model_s['brier']
        base = model_s['base_rate']
        brier_base = base * (1 - base)  # Brier of always predicting base rate
        if brier < brier_base * 0.9:
            print(f"  ✅ {name} calibrated: Brier {brier:.4f} < baseline {brier_base:.4f}")
        else:
            print(f"  ⚠️ {name} poorly calibrated: Brier {brier:.4f} vs baseline {brier_base:.4f}")
    
    return {"bid": bid_s, "ask": ask_s, "results": results}


def _print_model_summary(s: dict):
    print(f"  Samples      : {s['n_samples']:,}")
    print(f"  Fill rate    : {s['base_rate']:.1%} (base rate)")
    print(f"  Accuracy     : {s['accuracy']:.3f}")
    print(f"  Precision    : {s['precision']:.3f}")
    print(f"  Recall       : {s['recall']:.3f}")
    print(f"  F1           : {s['f1']:.3f}")
    print(f"  ROC AUC      : {s['auc']:.3f}")
    print(f"  Brier        : {s['brier']:.4f} (0=perfect)")
    print(f"  Drifts       : {s['drifts']}")


# ── CLI ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="River Fill-Probability Predictor")
    ap.add_argument("command", nargs="?", default="backtest",
                    choices=["backtest", "info"])
    ap.add_argument("--symbol", default="BTC-USD")
    ap.add_argument("--horizon", type=int, default=7,
                    help="Fill time horizon in seconds (7/15/30)")
    ap.add_argument("--max-snapshots", type=int, default=20000)
    args = ap.parse_args()
    
    if args.command == "info":
        print("=== River Fill-Probability Predictor ===")
        print("Purpose: predict P(maker order fills within N seconds)")
        print("Use case: filter OBI snapshots before posting maker orders")
        print("Impact: higher fill rate → higher ratio → closer to 1:7,500 target")
        print()
        print("Features used:")
        print("  • obi5/10/20 — order book imbalance")
        print("  • spread_pct, spread_vol — current spread & stability")
        print("  • vol_imbalance, bbv_ratio — book pressure")
        print("  • bv20, av20, vol_delta — liquidity depth & flow")
        print("  • delta_mid_pct — recent price movement")
        print("  • trade_rate — recent trade frequency")
        print()
        print("Horizons: 7s (scalp), 15s (patient), 30s (patient+)")
        
    elif args.command == "backtest":
        if not HAS_RIVER:
            print("❌ River not installed. Run: pip install river")
            sys.exit(1)
        backtest_fill_prediction(
            args.symbol, horizon=args.horizon,
            max_snapshots=args.max_snapshots)
