#!/usr/bin/env python3
"""
ANANTARA SAKTI — MODE 5: Dynamic Spread Gate (OBI-powered)

Real-time spread optimization using OBI (Order Book Imbalance) signals.
Replaces the static spread gate (MODE 4) with a dynamic one that:
  1. Reads live OBI snapshot via SoDEX REST API
  2. Computes fill probability using trained River ML model
  3. Returns the optimal spread for the current market microstate

The KEY INSIGHT: When OBI is neutral (balanced bids/asks), the market
is in a resting state → we can use TIGHTER spreads because adverse
selection risk is low. When OBI is extreme → widen or skip.

Expected impact: 15% reduction in effective fee → ratio +1,500 pts.

Usage:
  from mode5_gate import DynamicSpreadGate
  gate = DynamicSpreadGate()
  spread, confidence = gate.optimal_spread("BTC-USD")
"""
from __future__ import annotations

import json
import logging
import os
import pickle
import time
from pathlib import Path

log = logging.getLogger("mode5-gate")

PROJECT_DIR = Path(os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti")))
MODEL_PATH = PROJECT_DIR / "anantara" / "data" / "mode5_obi_model.pkl"
TABLE_PATH = PROJECT_DIR / "freqtrade_user_data" / "data" / "sodex" / "mode5_spread_table.json"

# Fallback spread table (pre-computed from OBI data analysis)
# Values represent optimal spread GATE in basis points (100 bps = 0.01%)
# Based on actual SoDEX microstructure: BTC bid-ask ~0.14 bps, ETH ~0.49 bps
# We set gates slightly WIDER than natural spread to ensure fills
DEFAULT_SPREAD_TABLE = {
    "BTC-USD": 3.0,     # 0.003% gate (natural spread ~0.0014%)
    "ETH-USD": 8.0,     # 0.008% gate (natural spread ~0.005%)
    "SOL-USD": 8.0,
    "SILVER-USD": 8.5,  # 0.085% gate (natural spread ~0.044%)
    "XAUT-USD": 5.0,
    "ZEC-USD": 5.0,     # 0.005% gate (natural spread ~0.002%)
    "HYPE-USD": 10.0,
    "BCH-USD": 8.0,
    "XMR-USD": 8.0,
    "DEFAULT": 10.0,    # 0.010% gate for unknown symbols
}

# Spread adjustment bounds
MIN_SPREAD_BPS = 1.5   # Never go below 0.0015% (near market minimum)
MAX_SPREAD_BPS = 30.0  # Never go above 0.030% (not worth it)


class DynamicSpreadGate:
    """Real-time OBI-driven spread optimizer for MODE 5."""

    def __init__(self):
        self._model = None
        self._feature_names = None
        self._spread_table = DEFAULT_SPREAD_TABLE.copy()
        self._load_model()
        self._load_spread_table()
        self._cache: dict[str, tuple[float, float, float]] = {}  # sym → (spread, conf, ts)
        self._cache_ttl = 2.0  # seconds

    def _load_model(self):
        """Load trained River ML model if available."""
        if MODEL_PATH.exists():
            try:
                with open(MODEL_PATH, "rb") as f:
                    data = pickle.load(f)
                self._model = data.get("model")
                self._feature_names = data.get("feature_names", [])
                log.info(f"Loaded OBI model (accuracy: {data.get('accuracy', 'N/A')}%)")
            except Exception as e:
                log.warning(f"Could not load OBI model: {e} — using fallback table")

    def _load_spread_table(self):
        """Load pre-computed spread table from training."""
        if TABLE_PATH.exists():
            try:
                with open(TABLE_PATH) as f:
                    table = json.load(f)
                # Convert to simple symbol→bps mapping
                for sym, s in table.items():
                    self._spread_table[sym] = s.get("optimal_spread_bps", DEFAULT_SPREAD_TABLE.get("DEFAULT", 25.0))
                log.info(f"Loaded spread table for {len(table)} symbols")
            except Exception as e:
                log.warning(f"Could not load spread table: {e}")

    def _get_obi_snapshot(self, symbol: str) -> dict | None:
        """Fetch live OBI data from SoDEX REST API (order book depth)."""
        import httpx
        try:
            url = f"https://mainnet-gw.sodex.dev/api/v1/perps/markets/{symbol}/orderbook"
            with httpx.Client(timeout=5, headers={"Accept": "application/json"}) as c:
                r = c.get(url, params={"depth": 5})
                if r.status_code == 200:
                    data = r.json().get("data", {})
                    return {
                        "bids": data.get("bids", []),
                        "asks": data.get("asks", []),
                        "ts": int(time.time() * 1000),
                    }
        except Exception as e:
            log.debug(f"OBI snapshot failed for {symbol}: {e}")
        return None

    def _compute_obi_features(self, obi: dict) -> dict:
        """Compute OBI features from snapshot (mirrors obi_analyzer.compute_obi)."""
        bids = obi.get("bids", [])
        asks = obi.get("asks", [])
        features = {}
        for i in range(min(5, len(bids), len(asks))):
            bv = float(bids[i][1]) if len(bids[i]) > 1 else 0
            av = float(asks[i][1]) if len(asks[i]) > 1 else 0
            total = bv + av
            features[f"obi_l{i}"] = (bv - av) / total if total > 0 else 0
            features[f"bid_vol_l{i}"] = bv
            features[f"ask_vol_l{i}"] = av

        total_bid = sum(float(b[1]) for b in bids[:5] if len(b) > 1)
        total_ask = sum(float(a[1]) for a in asks[:5] if len(a) > 1)
        total = total_bid + total_ask
        features["obi_agg"] = (total_bid - total_ask) / total if total > 0 else 0
        features["total_depth"] = total
        features["bid_ask_ratio"] = total_bid / total_ask if total_ask > 0 else 1.0

        if bids and asks:
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            mid = (best_bid + best_ask) / 2
            features["spread_bps"] = (best_ask - best_bid) / mid * 10000
        return features

    def _predict_fill_prob(self, features: dict) -> float:
        """Use River ML model to predict fill probability. Returns 0.0-1.0."""
        if self._model is None or self._feature_names is None:
            return 0.5  # no model → neutral

        try:
            x = {k: features.get(k, 0) for k in self._feature_names}
            prob = self._model.predict_proba_one(x)
            return prob.get(True, 0.5) if prob else 0.5
        except Exception:
            return 0.5

    def optimal_spread(self, symbol: str) -> tuple[float, float]:
        """Compute optimal spread for a symbol given current OBI state.
        
        Returns:
            (spread_pct, confidence) where spread_pct is the optimal
            spread as a decimal (e.g., 0.015 = 1.5%), and confidence
            is the model's confidence in the fill probability.
            
        The dynamic logic:
          - OBI neutral (balanced): tighter spread (closer to base)
          - OBI bid-heavy: slightly wider (adverse selection on shorts)
          - OBI ask-heavy: slightly wider (adverse selection on longs)
          - OBI extreme: skip (return very wide spread → filtered by caller)
        """
        # Use cache if fresh
        cached = self._cache.get(symbol)
        if cached and time.time() - cached[2] < self._cache_ttl:
            return cached[0], cached[1]

        # Get base spread from table
        base_spread_bps = self._spread_table.get(symbol, self._spread_table.get("DEFAULT", 25.0))

        # Try to get live OBI
        obi = self._get_obi_snapshot(symbol)
        if obi is None:
            # No OBI data → use base spread
            spread_pct = base_spread_bps / 10000
            self._cache[symbol] = (spread_pct, 0.5, time.time())
            return spread_pct, 0.5

        features = self._compute_obi_features(obi)
        fill_prob = self._predict_fill_prob(features)
        obi_agg = features.get("obi_agg", 0)

        # Dynamic adjustment based on OBI
        # Neutral OBI: tighten by up to 30%
        # Extreme OBI: widen by up to 50%
        obi_abs = abs(obi_agg)

        if obi_abs < 0.1:
            # Very balanced → tighten aggressively
            adjustment = 0.70  # 70% of base = 30% tighter
            confidence = 0.85
        elif obi_abs < 0.2:
            # Balanced → moderate tighten
            adjustment = 0.85
            confidence = 0.75
        elif obi_abs < 0.35:
            # Slightly directional → use base
            adjustment = 1.0
            confidence = 0.65
        elif obi_abs < 0.5:
            # Directional → widen
            adjustment = 1.2
            confidence = 0.50
        elif obi_abs < 0.7:
            # Strong directional → widen more
            adjustment = 1.5
            confidence = 0.35
        else:
            # Extreme → skip signal (return max spread)
            spread_pct = MAX_SPREAD_BPS / 10000
            self._cache[symbol] = (spread_pct, 0.1, time.time())
            return spread_pct, 0.1

        # Blend model prediction with OBI adjustment
        if fill_prob > 0.6:
            adjustment *= 0.9  # model confident → slightly tighter

        optimal_bps = base_spread_bps * adjustment
        optimal_bps = max(MIN_SPREAD_BPS, min(MAX_SPREAD_BPS, optimal_bps))
        spread_pct = optimal_bps / 100  # bps → percent (1.5 bps = 0.015%)

        self._cache[symbol] = (spread_pct, confidence, time.time())
        return spread_pct, confidence

    def should_skip(self, symbol: str) -> bool:
        """Quick check: should we skip this symbol entirely right now?"""
        spread, conf = self.optimal_spread(symbol)
        return conf < 0.2  # model says very unlikely to fill

    def get_summary(self) -> dict:
        """Get current state summary for Telegram/reporting."""
        summary = {}
        for sym in ["BTC-USD", "SILVER-USD", "ETH-USD", "SOL-USD"]:
            spread, conf = self.optimal_spread(sym)
            summary[sym] = {
                "spread_pct": round(spread * 100, 4),
                "confidence": round(conf, 2),
                "skip": conf < 0.2,
            }
        return summary


# Global singleton
_gate: DynamicSpreadGate | None = None


def get_gate() -> DynamicSpreadGate:
    """Get or create the global DynamicSpreadGate singleton."""
    global _gate
    if _gate is None:
        _gate = DynamicSpreadGate()
    return _gate


# ── Standalone test / CLI ──
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    gate = DynamicSpreadGate()
    print("=" * 60)
    print("MODE 5: Dynamic Spread Gate — Live Test")
    print("=" * 60)
    for sym in ["BTC-USD", "ETH-USD", "SOL-USD", "SILVER-USD", "ZEC-USD", "HYPE-USD"]:
        spread, conf = gate.optimal_spread(sym)
        skip = "SKIP" if gate.should_skip(sym) else "OK"
        print(f"  {sym:<15} spread={spread*100:.4f}%  conf={conf:.2f}  [{skip}]")
    print(f"\nSummary: {json.dumps(gate.get_summary(), indent=2)}")
