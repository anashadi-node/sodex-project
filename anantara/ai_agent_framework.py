#!/usr/bin/env python3
"""
ANANTARA SAKTI — AI Agent Trading Framework v4.0

Multi-layer autonomous trading intelligence integrating:
  Layer 1: River (online ML regime detection + fill probability)
  Layer 2: XGBoost (signal veto) + scikit-learn (anomaly detection)
  Layer 3: Stable-Baselines3 (RL tactical executor, future)
  Layer 4: ChromaDB (trade pattern memory)
  Layer 5: Governor gate → Execution

All components are optional — graceful degradation if dependencies missing.
Core governor + expectancy gate remain the master safety backstop.

Design principle: each component adds a FILTER, never bypasses safety.
"""
from __future__ import annotations
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("anantara.ai_agent")

# ── Optional imports (graceful degradation) ─────────────────────────
# Inject venv-research site-packages into path so system Python (daemon)
# can find numpy, xgboost, etc. installed there — same pattern as eth_account.
def _ensure_venv_packages() -> None:
    """Add .venv-research site-packages to sys.path if not already present.

    Only adds a path whose Python version exactly matches the current interpreter
    to prevent injecting Python 3.10-compiled C-extensions into a 3.12 process.
    """
    import sys
    current_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    venv_site = Path(__file__).parent.parent / ".venv-research" / "lib"
    sp = venv_site / current_ver / "site-packages"
    if sp.exists() and str(sp) not in sys.path:
        sys.path.insert(0, str(sp))

_ensure_venv_packages()

# numpy: guarded so CI (stdlib-only) can import this module without numpy installed.
HAS_NUMPY = False
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore  — only used inside HAS_XGBOOST-gated methods
HAS_XGBOOST = False
try:
    import xgboost as xgb
    HAS_XGBOOST = True
except ImportError:
    log.info("XGBoost not installed — veto system disabled")

HAS_CHROMA = False
try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    HAS_CHROMA = True
except ImportError:
    log.info("ChromaDB not installed — pattern memory disabled")

HAS_SB3 = False
try:
    import gymnasium as gym
    from stable_baselines3 import PPO
    HAS_SB3 = True
except ImportError:
    log.info("Stable-Baselines3 not installed — RL executor deferred")

HAS_RIVER = False
try:
    from river import drift, linear_model, preprocessing, metrics, stats
    HAS_RIVER = True
except ImportError:
    log.info("River not installed — online regime detection disabled")

# ── Project paths ────────────────────────────────────────────────────
PROJECT_DIR = Path(os.environ.get("ANANTARA_DIR",
                    str(Path.home() / "anantara-sakti")))
CHROMA_PATH = PROJECT_DIR / "data" / "chroma"
MEMORY_PATH = PROJECT_DIR / "data" / "agent_memory.json"


# ══════════════════════════════════════════════════════════════════════
# LAYER 1: PERCEPTION — River Online Regime Detector
# ══════════════════════════════════════════════════════════════════════

@dataclass
class RegimeState:
    """Current market regime assessment."""
    volatility_regime: str = "normal"     # low / normal / high / chaos
    trend_regime: str = "ranging"         # trending_up / trending_down / ranging
    liquidity_regime: str = "normal"      # thin / normal / deep
    spread_regime: str = "normal"         # tight / normal / wide
    drift_detected: bool = False
    confidence: float = 0.5
    timestamp: str = ""


class RiverRegimeDetector:
    """Online regime detection using River's ADWIN drift detectors.

    Tracks multiple market dimensions simultaneously and detects
    when ANY of them undergo a statistically significant change.
    """

    def __init__(self):
        # Initialize all attributes with safe defaults first so they always
        # exist regardless of whether River is installed. This allows tests
        # (and CI stdlib-only runs) to call summary() without AttributeError.
        self._ready      = False
        self._n          = 0
        self._drift_count = 0
        self._last_regime = RegimeState()
        self._vol_drift  = None
        self._spread_drift = None
        self._obi_drift  = None
        self._price_drift = None
        self._vol_mean   = None
        self._spread_mean = None

        if not HAS_RIVER:
            return
        self._ready = True

        # Drift detectors per dimension
        self._vol_drift    = drift.ADWIN(delta=0.002)
        self._spread_drift = drift.ADWIN(delta=0.002)
        self._obi_drift    = drift.ADWIN(delta=0.002)
        self._price_drift  = drift.ADWIN(delta=0.002)

        # Running statistics (River 0.22: use stats.Mean, not RollingMean)
        self._vol_mean    = stats.Mean()
        self._spread_mean = stats.Mean()

    def update(self, mid: float, spread_pct: float, obi5: float,
               vol_20: float) -> RegimeState:
        """Process one market snapshot, return current regime."""
        self._n += 1   # always count, even when River unavailable
        if not self._ready:
            return RegimeState()

        # Update drift detectors
        self._vol_drift.update(vol_20)
        self._spread_drift.update(spread_pct)
        self._obi_drift.update(obi5)
        self._price_drift.update(mid)

        # Running stats
        self._vol_mean.update(vol_20)
        self._spread_mean.update(spread_pct)

        # Detect regime
        any_drift = False
        if self._n > 50:
            any_drift = (self._vol_drift.drift_detected or
                        self._spread_drift.drift_detected or
                        self._obi_drift.drift_detected)

        if any_drift:
            self._drift_count += 1

        # Classify volatility regime
        avg_vol = self._vol_mean.get() if self._n > 10 else vol_20
        if avg_vol <= 0:
            vol_regime = "normal"
        elif vol_20 > avg_vol * 3:
            vol_regime = "chaos"
        elif vol_20 > avg_vol * 1.5:
            vol_regime = "high"
        elif vol_20 < avg_vol * 0.5:
            vol_regime = "low"
        else:
            vol_regime = "normal"

        # Classify spread regime
        avg_spread = self._spread_mean.get() if self._n > 10 else spread_pct
        if avg_spread <= 0:
            spread_regime = "normal"
        elif spread_pct > avg_spread * 2:
            spread_regime = "wide"
        elif spread_pct < avg_spread * 0.5:
            spread_regime = "tight"
        else:
            spread_regime = "normal"

        regime = RegimeState(
            volatility_regime=vol_regime,
            spread_regime=spread_regime,
            drift_detected=any_drift,
            confidence=min(1.0, self._n / 200),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        self._last_regime = regime
        return regime

    def summary(self) -> dict:
        return {
            "n_samples": self._n,
            "drifts_detected": self._drift_count,
            "current_vol_regime": self._last_regime.volatility_regime,
            "current_spread_regime": self._last_regime.spread_regime,
            "drift_active": self._last_regime.drift_detected,
        }


# ══════════════════════════════════════════════════════════════════════
# LAYER 2: DECISION — XGBoost Signal Veto
# ══════════════════════════════════════════════════════════════════════

class XGBoostVeto:
    """Secondary classifier that vetos suspicious signals.

    Trained on historical trade outcomes: features → {profitable, not}.
    Only vetos when HIGH confidence of failure. Conservative: precision > recall.

    Different inductive bias than LightGBM → ensemble reduces overfit.
    """

    def __init__(self, model_path: Optional[Path] = None):
        self._ready = HAS_XGBOOST
        self._model: Any = None
        self._model_path = model_path or (PROJECT_DIR / "data" / "xgboost_veto.json")
        self._n_trained = 0
        self._features: list[dict] = []
        self._labels: list[bool] = []

        if self._ready and self._model_path.exists():
            try:
                self._model = xgb.XGBClassifier()
                self._model.load_model(str(self._model_path))
                log.info(f"XGBoost veto loaded: {self._model_path}")
            except Exception as e:
                log.warning(f"XGBoost load failed: {e}")

    def predict_veto(self, features: dict) -> dict:
        """Returns {veto: bool, confidence: float, reason: str}."""
        if not self._ready or self._model is None:
            return {"veto": False, "confidence": 0.0,
                    "reason": "model not ready"}

        try:
            # Build feature vector (must match training order)
            fv = np.array([[
                features.get("atr_pct", 0),
                features.get("spread_pct", 0),
                features.get("obi5", 0),
                features.get("vol_imbalance", 0),
                features.get("model_prob", 0.5),
                features.get("funding_rate", 0),
                features.get("hour", 0),
                features.get("dow", 0),  # day of week
            ]])

            prob_fail = self._model.predict_proba(fv)[0][0]  # P(class 0 = lose)
            veto = prob_fail > 0.75  # Only veto when >75% sure it loses
            return {
                "veto": veto,
                "confidence": round(1 - prob_fail, 3),
                "reason": f"xgboost p(fail)={prob_fail:.2f}" if veto else "pass",
            }
        except Exception as e:
            return {"veto": False, "confidence": 0.0, "reason": str(e)[:100]}

    def record_outcome(self, features: dict, profitable: bool):
        """Store trade outcome for future training."""
        self._features.append(features)
        self._labels.append(profitable)
        # Auto-train every 50 trades
        if len(self._labels) >= 50 and len(self._labels) % 50 == 0:
            self._train()

    def _train(self):
        """Retrain XGBoost on accumulated trade history."""
        if not self._ready or len(self._labels) < 20:
            return
        try:
            fv = np.array([[
                f.get("atr_pct", 0), f.get("spread_pct", 0),
                f.get("obi5", 0), f.get("vol_imbalance", 0),
                f.get("model_prob", 0.5), f.get("funding_rate", 0),
                f.get("hour", 0), f.get("dow", 0),
            ] for f in self._features])

            self._model = xgb.XGBClassifier(
                n_estimators=100, max_depth=3, learning_rate=0.1,
                objective="binary:logistic", verbosity=0,
            )
            self._model.fit(fv, np.array(self._labels))
            self._model.save_model(str(self._model_path))
            self._n_trained = len(self._labels)
            log.info(f"XGBoost veto trained: {self._n_trained} samples")
        except Exception as e:
            log.error(f"XGBoost train failed: {e}")

    def summary(self) -> dict:
        return {
            "ready": self._ready and self._model is not None,
            "n_trained": self._n_trained,
            "n_pending": len(self._labels),
            "model_path": str(self._model_path) if self._model_path else None,
        }


# ══════════════════════════════════════════════════════════════════════
# LAYER 3: MEMORY — ChromaDB Trade Pattern Store
# ══════════════════════════════════════════════════════════════════════

class TradePatternMemory:
    """Vector store for trade patterns — enables similarity-based retrieval.

    Each trade is embedded as a vector of its features. When evaluating
    a new signal, we retrieve the K most similar historical trades and
    check their outcomes as a validation signal.
    """

    def __init__(self):
        self._ready = HAS_CHROMA
        self._collection: Any = None
        self._n_stored = 0

        if self._ready:
            try:
                CHROMA_PATH.mkdir(parents=True, exist_ok=True)
                client = chromadb.PersistentClient(path=str(CHROMA_PATH))
                self._collection = client.get_or_create_collection(
                    name="trade_patterns",
                    metadata={"description": "Anantara Sakti trade memory"},
                )
                self._n_stored = self._collection.count()
                log.info(f"ChromaDB memory: {self._n_stored} patterns loaded")
            except Exception as e:
                log.warning(f"ChromaDB init failed: {e}")
                self._ready = False

    def store(self, trade_id: str, features: dict, outcome: str, pnl_pct: float):
        """Store one trade pattern."""
        if not self._ready:
            return

        try:
            # Build embedding vector from features
            embedding = [
                features.get("atr_pct", 0),
                features.get("spread_pct", 0),
                features.get("obi5", 0),
                features.get("vol_imbalance", 0),
                features.get("model_prob", 0.5),
                features.get("funding_rate", 0),
            ]

            metadata = {
                "trade_id": trade_id,
                "symbol": features.get("symbol", ""),
                "direction": features.get("direction", ""),
                "outcome": outcome,
                "pnl_pct": pnl_pct,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            self._collection.add(
                embeddings=[embedding],
                documents=[json.dumps(metadata)],
                metadatas=[metadata],
                ids=[trade_id],
            )
            self._n_stored += 1
        except Exception as e:
            log.debug(f"ChromaDB store failed: {e}")

    def query_similar(self, features: dict, k: int = 5) -> list[dict]:
        """Find K most similar historical trades."""
        if not self._ready or self._n_stored == 0:
            return []

        try:
            embedding = [
                features.get("atr_pct", 0),
                features.get("spread_pct", 0),
                features.get("obi5", 0),
                features.get("vol_imbalance", 0),
                features.get("model_prob", 0.5),
                features.get("funding_rate", 0),
            ]

            results = self._collection.query(
                query_embeddings=[embedding],
                n_results=min(k, self._n_stored),
            )

            out = []
            if results and results["metadatas"]:
                for meta in results["metadatas"][0]:
                    out.append({
                        "trade_id": meta.get("trade_id", ""),
                        "symbol": meta.get("symbol", ""),
                        "outcome": meta.get("outcome", ""),
                        "pnl_pct": meta.get("pnl_pct", 0),
                    })
            return out
        except Exception as e:
            log.debug(f"ChromaDB query failed: {e}")
            return []

    def similarity_veto(self, features: dict, k: int = 5,
                        min_win_rate: float = 0.4) -> dict:
        """Veto if K-nearest historical trades were mostly losers."""
        similar = self.query_similar(features, k)
        if len(similar) < 3:
            return {"veto": False, "reason": "insufficient memory",
                    "similar_count": len(similar)}

        wins = sum(1 for s in similar if s["outcome"] == "win")
        win_rate = wins / len(similar)

        veto = win_rate < min_win_rate
        return {
            "veto": veto,
            "win_rate": round(win_rate, 2),
            "similar_count": len(similar),
            "reason": f"similar win rate {win_rate:.0%} < {min_win_rate:.0%}" if veto else "pass",
        }

    def summary(self) -> dict:
        return {
            "ready": self._ready,
            "patterns_stored": self._n_stored,
            "path": str(CHROMA_PATH),
        }


# ══════════════════════════════════════════════════════════════════════
# LAYER 4: ENSEMBLE — Multi-Signal Aggregator
# ══════════════════════════════════════════════════════════════════════

@dataclass
class AgentDecision:
    """Final decision from the multi-agent ensemble."""
    approved: bool
    direction: str  # LONG / SHORT / NEUTRAL
    confidence: float
    leverage: int
    sl_pct: float
    veto_reasons: list[str] = field(default_factory=list)
    component_votes: dict = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class AIAgentEnsemble:
    """Orchestrates all AI layers into a single trading decision.

    Pipeline:
      1. Regime check (River) → pause if chaos
      2. Fill probability (River) → skip if too low
      3. Similarity check (ChromaDB) → veto if similar trades lost
      4. XGBoost veto → veto if high fail probability
      5. Governor gate → final approve/veto (MASTER backstop)
    """

    def __init__(self):
        self.regime = RiverRegimeDetector()
        self.veto = XGBoostVeto()
        self.memory = TradePatternMemory()

        # Fill predictor integration (import at runtime to avoid circular)
        self._fill_predictor = None
        self._fill_predictor_loaded = False

    def _load_fill_predictor(self):
        """Lazy-load River fill predictor."""
        if self._fill_predictor_loaded:
            return
        self._fill_predictor_loaded = True
        try:
            from scripts.research.river_fill_predictor import FillPredictor
            self._fill_predictor = {
                "bid": FillPredictor(7, "bid"),
                "ask": FillPredictor(7, "ask"),
            }
            log.info("Fill predictor loaded into AI ensemble")
        except Exception as e:
            log.debug(f"Fill predictor not available: {e}")

    def evaluate_signal(self, signal: dict, market_data: dict) -> AgentDecision:
        """Full pipeline evaluation.

        Args:
            signal: {direction, confidence, symbol, model_prob, ...}
            market_data: {obi_snapshot, regime_features, ...}

        Returns:
            AgentDecision with approved + veto reasons
        """
        veto_reasons = []
        votes = {}

        # ── Step 1: Regime check ──
        snap = market_data.get("obi_snapshot", {})
        regime_state = self.regime.update(
            mid=float(snap.get("mid", 0) or 0),
            spread_pct=float(snap.get("spread", 0) or 0) / max(float(snap.get("mid", 1)), 1),
            obi5=float(snap.get("obi5", 0) or 0),
            vol_20=float(snap.get("bv20", 0) or 0) + float(snap.get("av20", 0) or 0),
        )
        votes["regime"] = regime_state

        if regime_state.volatility_regime == "chaos":
            veto_reasons.append("chaos regime — pause trading")
        if regime_state.spread_regime == "wide":
            veto_reasons.append("wide spread — high cost")

        # ── Step 2: Fill probability check (for maker mode) ──
        if signal.get("maker_mode"):
            self._load_fill_predictor()
            if self._fill_predictor:
                side = "bid" if signal.get("direction") == "LONG" else "ask"
                fp = self._fill_predictor.get(side)
                if fp:
                    fill_features = market_data.get("fill_features", {})
                    fill_prob = fp.predict_proba(fill_features)
                    votes["fill_prob"] = fill_prob
                    if fill_prob < 0.35:  # too unlikely to fill
                        veto_reasons.append(f"fill prob {fill_prob:.2f} < 0.35")

        # ── Step 3: Memory similarity ──
        features = {
            "atr_pct": market_data.get("atr_pct", 0),
            "spread_pct": market_data.get("spread_pct", 0),
            "obi5": float(snap.get("obi5", 0) or 0),
            "vol_imbalance": market_data.get("vol_imbalance", 0),
            "model_prob": signal.get("model_prob", 0.5),
            "funding_rate": signal.get("funding_rate", 0),
        }
        sim_result = self.memory.similarity_veto(features)
        votes["similarity"] = sim_result
        if sim_result.get("veto"):
            veto_reasons.append(sim_result["reason"])

        # ── Step 4: XGBoost veto ──
        xgb_features = {**features, "hour": datetime.now().hour,
                        "dow": datetime.now().weekday()}
        xgb_result = self.veto.predict_veto(xgb_features)
        votes["xgboost"] = xgb_result
        if xgb_result.get("veto"):
            veto_reasons.append(f"xgboost: {xgb_result['reason']}")

        # ── Step 5: Decision ──
        approved = len(veto_reasons) == 0 and signal.get("direction") != "NEUTRAL"

        return AgentDecision(
            approved=approved,
            direction=signal.get("direction", "NEUTRAL"),
            confidence=signal.get("confidence", 0.5),
            leverage=signal.get("leverage", 3),
            sl_pct=signal.get("sl_pct", 0.01),
            veto_reasons=veto_reasons,
            component_votes=votes,
        )

    def record_trade(self, trade_id: str, features: dict, pnl_pct: float):
        """Record trade outcome for learning."""
        profitable = pnl_pct > 0
        outcome = "win" if profitable else "loss"

        # Store in ChromaDB
        self.memory.store(trade_id, features, outcome, pnl_pct)

        # Train XGBoost
        self.veto.record_outcome(features, profitable)

    def summary(self) -> dict:
        return {
            "regime": self.regime.summary(),
            "veto": self.veto.summary(),
            "memory": self.memory.summary(),
        }


# ── CLI ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== AI Agent Framework v4.0 ===")
    agent = AIAgentEnsemble()
    summary = agent.summary()
    print(f"  Regime detector : {'✅' if summary['regime'].get('n_samples', 0) > 0 else '⚠️'}")
    print(f"  XGBoost veto    : {'✅' if summary['veto']['ready'] else '⚠️'}")
    print(f"  ChromaDB memory : {'✅' if summary['memory']['ready'] else '⚠️'}")
    print(f"  Patterns stored : {summary['memory']['patterns_stored']}")
    print(f"\n  Architecture: docs/AI_ARCHITECTURE.md")
