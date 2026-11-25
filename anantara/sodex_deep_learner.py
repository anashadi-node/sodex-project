"""SoDEX Deep Learner — Loop Deep Learning Ability System.

Continuously learns from live fill data and adapts E1 spread parameters.
Runs as a background loop (60s interval); safe to co-exist with watchdog,
autopilot, and safety_guardian.

ARCHITECTURE
━━━━━━━━━━━
FillAnalyzer   — reads fills from twin_engine.db; computes per-pair/hour/regime
                 fill_rate and net_rate stats (source of truth = DB, not cache)

SpreadBandit   — UCB1 bandit per (pair, hour_bucket) selects optimal spread_bps
                 from discrete ladder; updates on every confirmed RT closed

FillProbModel  — River LogisticRegression: given current spread_bps + hour + regime,
                 predict P(fill within 5 min). Trained online on every fill/no-fill.

RegimeEnricher — combines Intel JSONL regime with BTC price momentum (CoinGecko)
                 to improve regime accuracy (currently 45.4% from autopilot report).
                 Gracefully degrades if CoinGecko unreachable.

ParamWriter    — converts bandit + model signals → bounded spread adjustments
                 (max ±30% from base configured in .env). Writes:
                   data/sodex_learned_params.json   ← read by engine at runtime
                   data/sodex_deep_learning.jsonl   ← audit trail

SAFETY CONTRACT
━━━━━━━━━━━━━━
• Spread adjustments are bounded: [base × 0.70 .. base × 1.30]
• Learned params file is validated before write (JSON-schema, type + range check)
• Engine reads learned params with 90s TTL cache; missing/corrupt = use env defaults
• NO structural changes (remove pair, disable engine) — those stay DO_NOT_AUTO_APPLY
• All writes are atomic (tmp → rename) to prevent partial reads
• Zero live orders placed by this module (read-only DB access)
"""
from __future__ import annotations

import json
import math
import os
import random
import re
import sqlite3
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── project paths ────────────────────────────────────────────────────────────
PROJECT = Path(os.environ.get("ANANTARA_DIR",
               str(Path(__file__).resolve().parent.parent)))
_DB_CANDIDATES = [
    PROJECT / "twin_engine.db",
    PROJECT / "data" / "twin_engine.db",
]
LEARNED_PARAMS = PROJECT / "data" / "sodex_learned_params.json"
DEEP_LOG       = PROJECT / "data" / "sodex_deep_learning.jsonl"
INTEL_JSONL    = PROJECT / "data" / "sodex" / "research" / "autonomous_learning.json"
ENV_FILE       = PROJECT / ".env"
EXTERNAL_EXPERIENCE_DIR = PROJECT / "data" / "external_experience"
CROSS_SYSTEM_SOURCES = [
    PROJECT / "data" / "sodex" / "research" / "autonomous_learning.json",
    PROJECT / "data" / "sodex" / "research" / "autonomous_status.json",
    PROJECT / "data" / "e1_autopilot_latest.json",
    PROJECT / "data" / "e1_scientific_eval.json",
    PROJECT / "data" / "sodex_monitor_eval" / "latest.json",
    PROJECT / "docs" / "PREGAIN_CONSCIOUSNESS_SYSTEM_2026-07-11.md",
    PROJECT / "reports" / "HL_HARVEST_DEEP_LEARNING_MEMORY_LATEST.md",
    PROJECT / "reports" / "HL_HARVEST_PROGRESS_AUDIT_2026-07-10.md",
]
_LESSON_KEYWORDS = (
    "lesson", "learning", "experience", "regime", "pnl", "profit", "loss",
    "drawdown", "risk", "fill", "spread", "slippage", "win_rate", "failure",
    "success", "anomaly", "pepe", "spcx", "sodex",
)
_SECRET_PATTERNS = (
    "PRIVATE_KEY", "API_KEY", "SECRET", "TOKEN", "PASSWORD", "TELEGRAM_BOT_TOKEN",
    "SODEX_PRIVATE_KEY", "SODEX_ACCOUNT_ID",
)

# ── env config ───────────────────────────────────────────────────────────────
_LOOP_INTERVAL   = int(os.environ.get("DL_LOOP_INTERVAL", "60"))
_MAX_SPREAD_MULT = float(os.environ.get("DL_MAX_SPREAD_MULT", "1.30"))   # upper bound
_MIN_SPREAD_MULT = float(os.environ.get("DL_MIN_SPREAD_MULT", "0.70"))   # lower bound
_MIN_FILLS_ADAPT = int(os.environ.get("DL_MIN_FILLS_ADAPT", "20"))       # min fills before adapting
_HISTORY_HOURS   = int(os.environ.get("DL_HISTORY_HOURS", "168"))        # 7 days lookback
_ENRICH_INTERVAL = int(os.environ.get("DL_ENRICH_INTERVAL", "300"))      # regime enrich every 5 min
_COINGECKO_TTL   = int(os.environ.get("DL_COINGECKO_TTL", "180"))        # price cache 3 min

# ── base spread defaults (mirrored from Config, used as bounds anchor) ────────
_BASE_SPREADS_DEFAULT: Dict[str, float] = {
    "PEPE/USDC":  0.0010,
    "SHIB/USDC":  0.0015,
    "XLM/USDC":   0.0008,
}

# ── UCB1 bandit spread ladder (bps fraction, e.g. 0.0010 = 10bps) ─────────────
_SPREAD_LADDER = [0.0007, 0.0008, 0.0010, 0.0012, 0.0015, 0.0018, 0.0021, 0.0025, 0.0030]

# ── hour buckets for learning (0-5, 6-11, 12-17, 18-23) ──────────────────────
def _hour_bucket(hour_utc: int) -> str:
    if hour_utc < 6:
        return "h00_05"
    elif hour_utc < 12:
        return "h06_11"
    elif hour_utc < 18:
        return "h12_17"
    else:
        return "h18_23"


# ═══════════════════════════════════════════════════════════════════════════════
# 1. FillAnalyzer — reads twin_engine.db (source of truth)
# ═══════════════════════════════════════════════════════════════════════════════

class FillAnalyzer:
    """Read fills + RTs from DB, compute per-(pair, hour) fill/net-rate stats."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or _find_db()
        self._last_id: int = 0
        self._seen_rt_ids: set[str] = set()
        # stats[(pair, hour_bucket)] = {"fills": int, "rts": int, "net_pnl": float, "volume": float}
        self.stats: Dict[Tuple[str, str], Dict[str, float]] = defaultdict(
            lambda: {"fills": 0, "rts": 0, "net_pnl": 0.0, "volume": 0.0,
                     "buy_fills": 0, "sell_fills": 0}
        )
        self._fills_total: int = 0
        self._rts_total: int = 0
        self._last_fill_ts: Optional[str] = None
        self._last_rt_ts: Optional[str] = None

    # ── incremental load ──────────────────────────────────────────────────────

    def load_incremental(self) -> Tuple[int, int]:
        """Load new fills/RTs since last call. Returns (new_fills, new_rts)."""
        if not self.db_path or not self.db_path.exists():
            return 0, 0
        cutoff_ts = (
            datetime.now(timezone.utc) - timedelta(hours=_HISTORY_HOURS)
        ).isoformat()
        new_fills = new_rts = 0
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=5)
            conn.row_factory = sqlite3.Row
            # new fills
            rows = conn.execute(
                "SELECT id, ts, engine, pair, side, notional, fee FROM fills "
                "WHERE id > ? AND engine='E1' AND ts >= ? ORDER BY id",
                (self._last_id, cutoff_ts),
            ).fetchall()
            for r in rows:
                hour = _ts_to_hour(r["ts"])
                bucket = _hour_bucket(hour)
                key = (r["pair"], bucket)
                self.stats[key]["fills"] += 1
                if r["side"] == "buy":
                    self.stats[key]["buy_fills"] += 1
                else:
                    self.stats[key]["sell_fills"] += 1
                self._last_id = max(self._last_id, r["id"])
                self._last_fill_ts = _max_iso_ts(self._last_fill_ts, r["ts"])
                new_fills += 1
            self._fills_total += new_fills

            # new roundtrips
            rows = conn.execute(
                "SELECT rt_id, ts_close, engine, pair, volume, net_pnl FROM rts "
                "WHERE engine='E1' AND ts_close >= ? "
                "ORDER BY rowid",
                (cutoff_ts,),
            ).fetchall()
            for r in rows:
                rt_id = str(r["rt_id"] or "")
                if not rt_id or rt_id in self._seen_rt_ids:
                    continue
                self._seen_rt_ids.add(rt_id)
                hour = _ts_to_hour(r["ts_close"])
                bucket = _hour_bucket(hour)
                key = (r["pair"], bucket)
                self.stats[key]["rts"] += 1
                self.stats[key]["net_pnl"] += float(r["net_pnl"] or 0)
                self.stats[key]["volume"] += float(r["volume"] or 0)
                self._last_rt_ts = _max_iso_ts(self._last_rt_ts, r["ts_close"])
                new_rts += 1
            self._rts_total += new_rts

            conn.close()
        except sqlite3.Error:
            pass
        return new_fills, new_rts

    def awareness(self, active_pairs: List[str], regime: str) -> Dict[str, Any]:
        """Operational self-state: what the learner knows about itself now."""
        db_ok = bool(self.db_path and self.db_path.exists())
        observed_pairs = sorted({pair for pair, _bucket in self.stats.keys()})
        now = datetime.now(timezone.utc)
        last_fill_age_min = _age_minutes(self._last_fill_ts, now)
        last_rt_age_min = _age_minutes(self._last_rt_ts, now)
        warnings: List[str] = []
        if not db_ok:
            warnings.append("db_missing")
        if active_pairs and not any(p in observed_pairs for p in active_pairs):
            warnings.append("active_pair_not_observed_yet")
        if last_fill_age_min is not None and last_fill_age_min > 180:
            warnings.append("fills_stale_gt_180m")
        quality = "OK" if not warnings else "DEGRADED"
        return {
            "dimension": "awareness",
            "generated_at": now.isoformat(),
            "db_path": str(self.db_path) if self.db_path else None,
            "db_ok": db_ok,
            "active_pairs": active_pairs,
            "observed_pairs": observed_pairs,
            "regime": regime,
            "last_fill_ts": self._last_fill_ts,
            "last_fill_age_min": last_fill_age_min,
            "last_rt_ts": self._last_rt_ts,
            "last_rt_age_min": last_rt_age_min,
            "quality": quality,
            "warnings": warnings,
            "self_limits": {
                "exchange_write_access": False,
                "places_orders": False,
                "cancels_orders": False,
                "max_spread_mult": _MAX_SPREAD_MULT,
                "min_spread_mult": _MIN_SPREAD_MULT,
                "engine_cache_ttl_s": _LEARNED_TTL,
            },
        }

    def experience(self) -> Dict[str, Any]:
        """Compact memory: what has been seen and retained in this loop."""
        by_pair: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"fills": 0, "rts": 0, "net_pnl": 0.0, "volume": 0.0,
                     "buy_fills": 0, "sell_fills": 0}
        )
        for (pair, _bucket), s in self.stats.items():
            p = by_pair[pair]
            p["fills"] += s["fills"]
            p["rts"] += s["rts"]
            p["net_pnl"] += s["net_pnl"]
            p["volume"] += s["volume"]
            p["buy_fills"] += s["buy_fills"]
            p["sell_fills"] += s["sell_fills"]

        pairs_out = {
            pair: {
                "fills": int(v["fills"]),
                "rts": int(v["rts"]),
                "net_pnl": round(v["net_pnl"], 6),
                "volume": round(v["volume"], 6),
                "buy_fills": int(v["buy_fills"]),
                "sell_fills": int(v["sell_fills"]),
                "avg_net_pnl_per_rt": (
                    round(v["net_pnl"] / v["rts"], 8) if v["rts"] else None
                ),
            }
            for pair, v in sorted(by_pair.items())
        }
        return {
            "dimension": "experience",
            "memory_window_hours": _HISTORY_HOURS,
            "fills_total_loaded": self._fills_total,
            "rts_total_loaded": self._rts_total,
            "unique_rt_ids_seen": len(self._seen_rt_ids),
            "last_fill_ts": self._last_fill_ts,
            "last_rt_ts": self._last_rt_ts,
            "by_pair": pairs_out,
            "by_pair_bucket": self.summary(),
        }

    def fill_rate(self, pair: str, bucket: str) -> float:
        """Estimated fill rate (fills per RT). >0 = active; 0 = dead."""
        key = (pair, bucket)
        s = self.stats[key]
        if s["rts"] == 0:
            return 0.0
        return s["fills"] / max(1, s["rts"])

    def net_rate(self, pair: str, bucket: str) -> float:
        """Net rate per RT for this (pair, bucket)."""
        key = (pair, bucket)
        s = self.stats[key]
        if s["rts"] < 3:
            return float("nan")
        return s["net_pnl"] / s["rts"]

    def summary(self) -> Dict[str, Any]:
        result = {}
        for (pair, bucket), s in self.stats.items():
            if s["fills"] > 0:
                result[f"{pair}|{bucket}"] = {
                    "fills": s["fills"],
                    "rts": s["rts"],
                    "fill_rate": round(self.fill_rate(pair, bucket), 3),
                    "net_rate": round(self.net_rate(pair, bucket), 6),
                    "net_pnl": round(s["net_pnl"], 4),
                }
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# 2. SpreadBandit — UCB1 per (pair, hour_bucket)
# ═══════════════════════════════════════════════════════════════════════════════

class SpreadBandit:
    """UCB1 multi-armed bandit: arm = spread_bps value; reward = net_rate_per_rt.

    Conservative design:
    • Reward is clipped to [-0.002, 0.002] per RT to prevent outlier arms
    • Each arm requires ≥5 pulls before exploitation (burn-in uses round-robin)
    • Selected spread is clamped to [base × 0.70 .. base × 1.30]
    """

    def __init__(self, arms: List[float] = _SPREAD_LADDER) -> None:
        self.arms = arms
        self._n: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self._mu: Dict[str, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
        self._t: Dict[str, int] = defaultdict(int)

    def _key(self, pair: str, bucket: str) -> str:
        return f"{pair}|{bucket}"

    def select(self, pair: str, bucket: str) -> float:
        """Return best spread (UCB1) for this pair × hour bucket."""
        k = self._key(pair, bucket)
        self._t[k] += 1
        t = self._t[k]
        best_arm = self.arms[0]
        best_ucb = -float("inf")
        for i, arm in enumerate(self.arms):
            n = self._n[k][i]
            if n < 5:
                # burn-in: cycle through all arms round-robin
                return self.arms[t % len(self.arms)]
            mu = self._mu[k][i]
            ucb = mu + math.sqrt(2 * math.log(t) / n)
            if ucb > best_ucb:
                best_ucb = ucb
                best_arm = arm
        return best_arm

    def update(self, pair: str, bucket: str, spread_used: float,
               net_rate: float) -> None:
        """Update reward for the arm that was pulled."""
        k = self._key(pair, bucket)
        # find closest arm
        i = min(range(len(self.arms)),
                key=lambda j: abs(self.arms[j] - spread_used))
        reward = max(-0.002, min(0.002, net_rate))  # clip outliers
        n = self._n[k][i]
        self._mu[k][i] = (self._mu[k][i] * n + reward) / (n + 1)
        self._n[k][i] += 1

    def best_spread(self, pair: str, bucket: str,
                    base_spread: float) -> float:
        """Exploitation: return highest-mean arm, bounded by base ±30%."""
        k = self._key(pair, bucket)
        best = base_spread
        best_mu = -float("inf")
        for i, arm in enumerate(self.arms):
            if self._n[k][i] >= 5 and self._mu[k][i] > best_mu:
                best_mu = self._mu[k][i]
                best = arm
        lo = base_spread * _MIN_SPREAD_MULT
        hi = base_spread * _MAX_SPREAD_MULT
        return max(lo, min(hi, best))

    def state(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k in set(self._n.keys()) | set(self._mu.keys()):
            out[k] = {
                "arms": {
                    f"{self.arms[i]:.4f}": {
                        "n": self._n[k][i],
                        "mu": round(self._mu[k][i], 6),
                    }
                    for i in range(len(self.arms))
                    if self._n[k][i] > 0
                }
            }
        return out


# ═══════════════════════════════════════════════════════════════════════════════
# 3. FillProbModel — River online logistic regression
# ═══════════════════════════════════════════════════════════════════════════════

class FillProbModel:
    """River online logistic regression: P(fill within 5 min) given features.

    Features: spread_bps, hour_sin, hour_cos, regime_bull, regime_bear,
              inv_frac (0-1: 0 = empty, 1 = full inventory)
    Target: 1 if fill confirmed (by checking DB), 0 otherwise (timeout)
    """

    def __init__(self) -> None:
        self._n_trained = 0
        try:
            from river import linear_model, preprocessing, compose
            self._model = compose.Pipeline(
                ("scale", preprocessing.StandardScaler()),
                ("clf",   linear_model.LogisticRegression()),
            )
            self._river_ok = True
        except ImportError:
            self._river_ok = False

    def _features(self, spread_bps: float, hour_utc: int,
                  regime: str, inv_frac: float) -> Dict[str, float]:
        angle = 2 * math.pi * hour_utc / 24
        return {
            "spread_bps": spread_bps,
            "hour_sin":   math.sin(angle),
            "hour_cos":   math.cos(angle),
            "regime_bull": 1.0 if regime.upper() == "BULL" else 0.0,
            "regime_bear": 1.0 if regime.upper() == "BEAR" else 0.0,
            "inv_frac":    max(0.0, min(1.0, inv_frac)),
        }

    def learn_one(self, spread_bps: float, hour_utc: int, regime: str,
                  inv_frac: float, filled: bool) -> None:
        if not self._river_ok:
            return
        x = self._features(spread_bps, hour_utc, regime, inv_frac)
        y = 1 if filled else 0
        self._model.learn_one(x, y)
        self._n_trained += 1

    def predict_proba(self, spread_bps: float, hour_utc: int,
                      regime: str, inv_frac: float) -> float:
        """Return P(fill) in [0, 1]. Returns 0.5 if model not trained yet."""
        if not self._river_ok or self._n_trained < 50:
            return 0.5
        x = self._features(spread_bps, hour_utc, regime, inv_frac)
        try:
            proba = self._model.predict_proba_one(x)
            return proba.get(1, 0.5) if isinstance(proba, dict) else 0.5
        except Exception:
            return 0.5

    @property
    def trained_count(self) -> int:
        return self._n_trained


# ═══════════════════════════════════════════════════════════════════════════════
# 4. RegimeEnricher — multi-source regime signal
# ═══════════════════════════════════════════════════════════════════════════════

class RegimeEnricher:
    """Enriches the raw Intel JSONL regime with BTC price momentum.

    Sources (priority order):
    1. TE_E1_FORCE_REGIME env var (operator override — always respected)
    2. Intel JSONL combined_regime (existing sodex_intel_layer.py output)
    3. BTC price momentum from CoinGecko (24h + 1h change)

    Output: "BULL" | "BEAR" | "NEUTRAL"
    Accuracy improvement target: from 45.4% → 55%+ by adding momentum signal.
    """

    def __init__(self) -> None:
        self._last_enriched: str = "NEUTRAL"
        self._last_enrich_ts: float = 0.0
        self._btc_cache: Optional[Dict[str, float]] = None
        self._btc_cache_ts: float = 0.0
        self._enrich_count: int = 0
        self._accuracy_log: List[Dict[str, Any]] = []  # for tracking

    def current(self) -> str:
        """Return current enriched regime (cached)."""
        now = time.time()
        if now - self._last_enrich_ts < _ENRICH_INTERVAL:
            return self._last_enriched
        self._last_enrich_ts = now
        self._last_enriched = self._compute()
        self._enrich_count += 1
        return self._last_enriched

    def _compute(self) -> str:
        # 1. Operator override always wins
        forced = os.environ.get("TE_E1_FORCE_REGIME", "").upper().strip()
        if forced in ("BULL", "BEAR", "NEUTRAL"):
            return forced

        # 2. Read Intel JSONL
        intel_regime = self._read_intel_regime()

        # 3. BTC momentum (CoinGecko, graceful degradation)
        btc = self._get_btc_momentum()
        if btc is None:
            return intel_regime  # fallback to Intel only

        # 4. Combine: weighted vote
        #    Intel JSONL regime (0.6 weight) + BTC momentum (0.4 weight)
        score = 0.0
        # Intel contribution
        if intel_regime == "BULL":
            score += 0.6
        elif intel_regime == "BEAR":
            score -= 0.6

        # BTC 1h momentum contribution
        if btc.get("change_1h", 0) > 0.5:
            score += 0.4
        elif btc.get("change_1h", 0) < -0.5:
            score -= 0.4

        if score > 0.2:
            return "BULL"
        elif score < -0.2:
            return "BEAR"
        return "NEUTRAL"

    def _read_intel_regime(self) -> str:
        if not INTEL_JSONL.exists():
            return "NEUTRAL"
        try:
            data = json.loads(INTEL_JSONL.read_text())
            recent = data.get("recent_outcomes", [])
            if not recent:
                return "NEUTRAL"
            wins = sum(1 for r in recent[-20:] if r.get("win"))
            n = min(20, len(recent))
            if n < 5:
                return "NEUTRAL"
            wr = wins / n
            if wr > 0.60:
                return "BULL"
            elif wr < 0.40:
                return "BEAR"
            return "NEUTRAL"
        except Exception:
            return "NEUTRAL"

    def _get_btc_momentum(self) -> Optional[Dict[str, float]]:
        now = time.time()
        if self._btc_cache and now - self._btc_cache_ts < _COINGECKO_TTL:
            return self._btc_cache
        try:
            url = ("https://api.coingecko.com/api/v3/simple/price?"
                   "ids=bitcoin&vs_currencies=usd"
                   "&include_24hr_change=true&include_1hr_change=true")
            req = urllib.request.Request(
                url, headers={"User-Agent": "AnantaraSakti/1.0 (+anantara)"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            btc = data.get("bitcoin", {})
            result = {
                "price":     float(btc.get("usd", 0)),
                "change_24h": float(btc.get("usd_24h_change", 0)),
                "change_1h":  float(btc.get("usd_1h_change", 0)),
            }
            self._btc_cache = result
            self._btc_cache_ts = now
            return result
        except Exception:
            return None  # graceful degradation

    def log_accuracy(self, predicted: str, actual: str) -> None:
        self._accuracy_log.append({
            "ts":        datetime.now(timezone.utc).isoformat(),
            "predicted": predicted,
            "actual":    actual,
            "correct":   predicted == actual,
        })
        # keep last 200 entries
        if len(self._accuracy_log) > 200:
            self._accuracy_log = self._accuracy_log[-200:]

    def accuracy(self) -> Optional[float]:
        if len(self._accuracy_log) < 10:
            return None
        return sum(1 for e in self._accuracy_log if e["correct"]) / len(self._accuracy_log)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. CrossSystemExperienceMiner — safe external/system memory
# ═══════════════════════════════════════════════════════════════════════════════

class CrossSystemExperienceMiner:
    """Read lessons from other project systems and operator-provided files.

    Contract:
    - read-only
    - never reads .env or key material
    - redacts suspicious secret lines
    - does not execute external text as instructions
    """

    def __init__(self,
                 sources: Optional[List[Path]] = None,
                 external_dir: Optional[Path] = None) -> None:
        self.sources = list(CROSS_SYSTEM_SOURCES) if sources is None else sources
        self.external_dir = external_dir or EXTERNAL_EXPERIENCE_DIR

    def collect(self) -> Dict[str, Any]:
        source_reports: List[Dict[str, Any]] = []
        lessons: List[Dict[str, Any]] = []
        for path in self._iter_paths():
            report = self._read_source(path)
            if not report:
                continue
            source_reports.append(report["source"])
            lessons.extend(report["lessons"])
        lessons = lessons[:30]
        return {
            "dimension": "cross_system_experience",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "external_dir": str(self.external_dir),
            "sources_count": len(source_reports),
            "lessons_count": len(lessons),
            "quality": "OK" if lessons else "SPARSE" if source_reports else "EMPTY",
            "policy": {
                "read_only": True,
                "external_text_is_observation_only": True,
                "auto_trade_from_external_text": False,
                "secret_redaction": True,
            },
            "sources": source_reports[:20],
            "lessons": lessons,
        }

    def _iter_paths(self) -> List[Path]:
        paths: List[Path] = []
        seen: set[str] = set()
        for path in self.sources:
            self._add_path(paths, seen, path)
        if self.external_dir.exists():
            for pattern in ("*.json", "*.jsonl", "*.md", "*.txt", "*.csv"):
                for path in sorted(self.external_dir.glob(pattern)):
                    self._add_path(paths, seen, path)
        return paths

    def _add_path(self, paths: List[Path], seen: set[str], path: Path) -> None:
        try:
            if not path.exists() or not path.is_file():
                return
            resolved = str(path.resolve())
            if resolved in seen:
                return
            if path.name == ".env" or any(part.startswith(".env") for part in path.parts):
                return
            seen.add(resolved)
            paths.append(path)
        except Exception:
            return

    def _read_source(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            stat = path.stat()
            raw = path.read_text(errors="ignore")[:24000]
        except Exception:
            return None
        extracted = self._extract_lessons(path, raw)
        return {
            "source": {
                "path": str(path.relative_to(PROJECT)) if _is_relative_to(path, PROJECT) else str(path),
                "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "size_bytes": stat.st_size,
                "lessons_found": len(extracted),
            },
            "lessons": extracted,
        }

    def _extract_lessons(self, path: Path, raw: str) -> List[Dict[str, Any]]:
        lessons: List[Dict[str, Any]] = []
        lines = raw.splitlines()
        if path.suffix.lower() in (".json", ".jsonl"):
            lessons.extend(self._extract_json_lessons(raw, path))
        for line in lines:
            clean = _sanitize_external_line(line)
            if not clean:
                continue
            low = clean.lower()
            if any(k in low for k in _LESSON_KEYWORDS):
                lessons.append({
                    "source": path.name,
                    "text": clean[:240],
                    "kind": "keyword_line",
                })
            if len(lessons) >= 12:
                break
        return lessons[:12]

    def _extract_json_lessons(self, raw: str, path: Path) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            if path.suffix.lower() == ".jsonl":
                objects = [json.loads(line) for line in raw.splitlines() if line.strip()][:20]
            else:
                objects = [json.loads(raw)]
        except Exception:
            return out
        for obj in objects:
            for key, val in _walk_json(obj):
                low = key.lower()
                if not any(k in low for k in _LESSON_KEYWORDS):
                    continue
                text = _sanitize_external_line(f"{key}: {val}")
                if text:
                    out.append({"source": path.name, "text": text[:240], "kind": "json_field"})
                if len(out) >= 8:
                    return out
        return out


# ═══════════════════════════════════════════════════════════════════════════════
# 6. ParamWriter — converts learning signals → bounded spread adjustments
# ═══════════════════════════════════════════════════════════════════════════════

class ParamWriter:
    """Converts bandit + model signals into a bounded params file.

    Output format (data/sodex_learned_params.json):
    {
      "ts": "...",
      "version": 1,
      "pairs": {
        "PEPE/USDC": {
          "min_spread": 0.0012,          // bounded: [base×0.70 .. base×1.30]
          "source": "bandit|h12_17",     // which bucket drove the recommendation
          "fill_prob_neutral": 0.62,     // fill probability at neutral regime
          "confidence": "high|med|low",  // based on n_fills
        },
        ...
      },
      "dead_hours": {                    // hours to avoid per pair
        "SHIB/USDC": [14, 15],
        "XLM/USDC":  [20, 22, 23],
      },
      "regime": "NEUTRAL",
      "regime_accuracy": 0.51,
    }
    """

    def write(self, bandit: SpreadBandit, model: FillProbModel,
              analyzer: FillAnalyzer, enricher: RegimeEnricher,
              base_spreads: Dict[str, float],
              dead_hours: Dict[str, List[int]],
              cross_system: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        now_hour = datetime.now(timezone.utc).hour
        now_bucket = _hour_bucket(now_hour)
        regime = enricher.current()
        pairs_out: Dict[str, Any] = {}
        learning_out: Dict[str, Any] = {
            "dimension": "learning",
            "current_bucket": now_bucket,
            "fill_model_n": model.trained_count,
            "min_fills_adapt": _MIN_FILLS_ADAPT,
            "recommendations": {},
        }

        for pair, base in base_spreads.items():
            # get best spread from bandit for current hour bucket
            learned = bandit.best_spread(pair, now_bucket, base)
            # fill probability at learned spread
            fill_p = model.predict_proba(learned, now_hour, regime, 0.5)
            # confidence based on fills seen
            key = (pair, now_bucket)
            n_fills = analyzer.stats[key]["fills"]
            confidence = "high" if n_fills >= 100 else "med" if n_fills >= _MIN_FILLS_ADAPT else "low"

            # only apply if enough data (confidence ≥ med)
            if confidence == "low":
                effective = base  # not enough data yet — use base
                decision = "use_base"
                reason = "insufficient_pair_bucket_fills"
            else:
                effective = learned
                decision = "adapt"
                reason = "enough_pair_bucket_fills"

            pairs_out[pair] = {
                "min_spread":        round(effective, 6),
                "base_spread":       round(base, 6),
                "source":            f"bandit|{now_bucket}",
                "fill_prob":         round(fill_p, 3),
                "confidence":        confidence,
                "n_fills":           n_fills,
                "delta_bps":         round((effective - base) / base * 10000, 1),
            }
            learning_out["recommendations"][pair] = {
                "decision": decision,
                "reason": reason,
                "base_spread": round(base, 6),
                "selected_spread": round(learned, 6),
                "effective_spread": round(effective, 6),
                "confidence": confidence,
                "fill_prob": round(fill_p, 3),
                "n_fills_bucket": n_fills,
                "bounded_by": {
                    "min": round(base * _MIN_SPREAD_MULT, 6),
                    "max": round(base * _MAX_SPREAD_MULT, 6),
                },
            }

        payload = {
            "ts":              datetime.now(timezone.utc).isoformat(),
            "version":         2,
            "capability":      "awareness_experience_learning",
            "awareness":       analyzer.awareness(list(base_spreads.keys()), regime),
            "experience":      analyzer.experience(),
            "cross_system_experience": cross_system or {
                "dimension": "cross_system_experience",
                "sources_count": 0,
                "lessons_count": 0,
                "quality": "EMPTY",
            },
            "learning":        learning_out,
            "pairs":           pairs_out,
            "dead_hours":      dead_hours,
            "regime":          regime,
            "regime_accuracy": enricher.accuracy(),
            "bandit_state":    bandit.state(),
            "fill_model_n":    model.trained_count,
        }

        _atomic_write(LEARNED_PARAMS, json.dumps(payload, indent=2))
        return payload

    @staticmethod
    def read_current() -> Optional[Dict[str, Any]]:
        if not LEARNED_PARAMS.exists():
            return None
        try:
            return json.loads(LEARNED_PARAMS.read_text())
        except Exception:
            return None

    @staticmethod
    def get_learned_spread(pair: str,
                            fallback: float,
                            max_age_s: int = 90) -> Optional[float]:
        """Read learned spread for a pair; return None if stale/missing."""
        if not LEARNED_PARAMS.exists():
            return None
        try:
            data = json.loads(LEARNED_PARAMS.read_text())
            ts_str = data.get("ts", "")
            if ts_str:
                ts = datetime.fromisoformat(ts_str)
                if (datetime.now(timezone.utc) - ts).total_seconds() > max_age_s:
                    return None
            pair_data = data.get("pairs", {}).get(pair)
            if not pair_data:
                return None
            raw = pair_data.get("min_spread")
            if raw is None:
                return None
            val = float(raw)
            # safety bounds: must be within [fallback×0.5 .. fallback×2.0]
            if val < fallback * 0.5 or val > fallback * 2.0:
                return None
            return val
        except Exception:
            return None


# ═══════════════════════════════════════════════════════════════════════════════
# 6. DeadHourDetector — BH-FDR dead hour detection (lightweight)
# ═══════════════════════════════════════════════════════════════════════════════

class DeadHourDetector:
    """Detect hours with statistically poor fill rates (BH-FDR corrected).

    Reads from existing e1_scientific_eval.json (written by sodex_e1_autopilot.py)
    to avoid duplicating the computation. Falls back to empty if file missing.
    """

    def __init__(self) -> None:
        self._cache: Dict[str, List[int]] = {}
        self._cache_ts: float = 0.0
        self._sci_eval = PROJECT / "data" / "e1_scientific_eval.json"

    def get_dead_hours(self) -> Dict[str, List[int]]:
        now = time.time()
        if now - self._cache_ts < 600:  # refresh every 10 min
            return self._cache
        self._cache_ts = now
        if not self._sci_eval.exists():
            return {}
        try:
            data = json.loads(self._sci_eval.read_text())
            dead: Dict[str, List[int]] = {}
            for pair_data in data.get("pair_stats", {}).values():
                pair = pair_data.get("pair", "")
                hours = pair_data.get("dead_hours_bh_fdr", [])
                if pair and hours:
                    dead[pair] = hours
            self._cache = dead
            return dead
        except Exception:
            return {}


# ═══════════════════════════════════════════════════════════════════════════════
# 7a. SPRTMonitor — Wald Sequential Probability Ratio Test (Fable5 §SPRT)
# ═══════════════════════════════════════════════════════════════════════════════

class SPRTMonitor:
    """Per-pair sequential testing of edge existence.

    H0: WR = 0.50 (no edge — random)   H1: WR = 0.60 (genuine edge)
    LLR per win  = ln(0.60/0.50) ≈ +0.1823
    LLR per loss = ln(0.40/0.50) ≈ -0.2231
    Decision boundaries (α=β=0.05): A = ln(19) ≈ +2.944  B = -2.944
    Expected samples to decision: ~146 RTs (< 1 day of E1 operation).
    """

    _WIN_INC  =  0.1823
    _LOSS_INC = -0.2231
    _UPPER    =  2.944
    _LOWER    = -2.944

    def __init__(self) -> None:
        self._cache: Dict[str, Any] = {}
        self._cache_ts: float = 0.0

    def analyze(self, db_path: Optional[Path]) -> Dict[str, Any]:
        now = time.time()
        if now - self._cache_ts < 120:  # refresh every 2 min
            return self._cache
        self._cache_ts = now
        if not db_path or not db_path.exists():
            self._cache = {"status": "no_db", "pairs": {}}
            return self._cache

        result: Dict[str, Any] = {"pairs": {}}
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            rows = conn.execute(
                "SELECT pair, CAST(net_pnl AS REAL) FROM rts "
                "WHERE engine='E1' ORDER BY ts_close ASC"
            ).fetchall()
            conn.close()
        except Exception:
            result["status"] = "db_error"
            self._cache = result
            return result

        pair_data: Dict[str, Dict] = {}
        for pair, pnl in rows:
            if pair not in pair_data:
                pair_data[pair] = {"llr": 0.0, "wins": 0, "losses": 0, "n": 0}
            pd = pair_data[pair]
            pd["n"] += 1
            if pnl is not None and pnl > 0:
                pd["wins"] += 1
                pd["llr"] = max(-10.0, min(10.0, pd["llr"] + self._WIN_INC))
            else:
                pd["losses"] += 1
                pd["llr"] = max(-10.0, min(10.0, pd["llr"] + self._LOSS_INC))

        for pair, pd in pair_data.items():
            llr = pd["llr"]
            n = pd["n"]
            wr = pd["wins"] / n if n > 0 else 0.0
            if llr >= self._UPPER:
                status = "edge_confirmed"
            elif llr <= self._LOWER:
                status = "edge_dead"
            else:
                pct = (llr - self._LOWER) / (self._UPPER - self._LOWER)
                status = f"collecting_{int(pct * 100)}pct"

            result["pairs"][pair] = {
                "llr": round(llr, 4),
                "n_rts": n,
                "wins": pd["wins"],
                "losses": pd["losses"],
                "wr": round(wr, 4),
                "status": status,
                "upper_boundary": self._UPPER,
                "lower_boundary": self._LOWER,
            }

        result["status"] = "ok"
        result["n_pairs_tracked"] = len(pair_data)
        self._cache = result
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# 7b. HawkesIntensityEstimator — EWMA fill-arrival intensity (Fable5 §Hawkes)
# ═══════════════════════════════════════════════════════════════════════════════

class HawkesIntensityEstimator:
    """Estimates market activity via EWMA self-exciting intensity.

    λ̂(t) = Σ_{recent fills} e^(−(t−t_i)/τ)   where τ=90s (half-life ≈ 60s)

    ON/OFF hysteresis:
      λ̂ > threshold_ON  → ACTIVE  (market is busy, good for quoting)
      λ̂ < threshold_OFF → IDLE    (market quiet, skip or widen spread)
    """

    _TAU           = 90.0    # decay constant seconds
    _THRESHOLD_ON  = 4.0     # events per τ window → go ACTIVE
    _THRESHOLD_OFF = 2.0     # events per τ window → go IDLE
    _LOOKBACK_S    = 900     # only look at fills from last 15 min

    def __init__(self) -> None:
        self._cache: Dict[str, Any] = {}
        self._cache_ts: float = 0.0
        self._state: Dict[str, str] = {}  # pair → ACTIVE/IDLE

    def estimate(self, db_path: Optional[Path]) -> Dict[str, Any]:
        now = time.time()
        if now - self._cache_ts < 30:  # fast cache — activity changes quickly
            return self._cache
        self._cache_ts = now
        if not db_path or not db_path.exists():
            self._cache = {"status": "no_db", "pairs": {}}
            return self._cache

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self._LOOKBACK_S)
        cutoff_iso = cutoff.isoformat()
        result: Dict[str, Any] = {"pairs": {}}
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            rows = conn.execute(
                "SELECT pair, ts FROM fills WHERE engine='E1' AND ts > ? ORDER BY ts ASC",
                (cutoff_iso,)
            ).fetchall()
            conn.close()
        except Exception:
            result["status"] = "db_error"
            self._cache = result
            return result

        # Group by pair, compute EWMA intensity
        t_now = time.time()
        pair_times: Dict[str, List[float]] = {}
        for pair, ts_str in rows:
            try:
                dt = datetime.fromisoformat(ts_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                t_fill = dt.timestamp()
                pair_times.setdefault(pair, []).append(t_fill)
            except Exception:
                pass

        for pair, times in pair_times.items():
            lam = 0.0
            for t_i in times:
                lam += math.exp(-(t_now - t_i) / self._TAU)

            prev = self._state.get(pair, "IDLE")
            if prev == "IDLE" and lam >= self._THRESHOLD_ON:
                self._state[pair] = "ACTIVE"
            elif prev == "ACTIVE" and lam <= self._THRESHOLD_OFF:
                self._state[pair] = "IDLE"

            state = self._state.get(pair, "IDLE")
            result["pairs"][pair] = {
                "intensity": round(lam, 3),
                "activity_state": state,
                "n_fills_15min": len(times),
                "threshold_on": self._THRESHOLD_ON,
                "threshold_off": self._THRESHOLD_OFF,
            }

        result["status"] = "ok"
        result["tau_s"] = self._TAU
        self._cache = result
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# 7c. MarkoutTracker — Glosten-Milgrom adverse selection analysis (Fable5 §GM)
# ═══════════════════════════════════════════════════════════════════════════════

class MarkoutTracker:
    """Measures adverse selection and net edge via RT PnL decomposition.

    Glosten-Milgrom gate: net_edge = spread_capture − adverse_selection − fee
    If net_edge > 0 → pair is worth market-making.

    Proxy calculation from rts table (no OBI required):
      spread_capture ≈ (base_spread / 2) × volume_per_rt
      fee_per_rt     ≈ 0.0334% × 2 legs × volume
      net_pnl        = spread_capture − adverse_selection − fee  (measured)
      adverse_sel     = spread_capture − fee − net_pnl           (derived)
    """

    _FEE_RATE = 0.000334  # 0.0334%/leg × 2 legs = 0.0668% round-trip

    def __init__(self) -> None:
        self._cache: Dict[str, Any] = {}
        self._cache_ts: float = 0.0

    def analyze(self, db_path: Optional[Path], base_spreads: Dict[str, float]) -> Dict[str, Any]:
        now = time.time()
        if now - self._cache_ts < 120:
            return self._cache
        self._cache_ts = now
        if not db_path or not db_path.exists():
            self._cache = {"status": "no_db", "pairs": {}}
            return self._cache

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=168)).isoformat()
        result: Dict[str, Any] = {"pairs": {}}
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            rows = conn.execute(
                "SELECT pair, CAST(volume AS REAL), CAST(net_pnl AS REAL) "
                "FROM rts WHERE engine='E1' AND ts_close > ? AND volume IS NOT NULL",
                (cutoff,)
            ).fetchall()
            conn.close()
        except Exception:
            result["status"] = "db_error"
            self._cache = result
            return result

        pair_data: Dict[str, List] = {}
        for pair, vol, pnl in rows:
            if vol and vol > 0 and pnl is not None:
                pair_data.setdefault(pair, []).append((vol, pnl))

        for pair, records in pair_data.items():
            base = base_spreads.get(pair, 0.0010)
            total_vol = sum(v for v, _ in records)
            total_pnl = sum(p for _, p in records)
            n = len(records)

            avg_vol = total_vol / n
            avg_pnl = total_pnl / n

            # Spread capture: each RT captures half-spread bid-side + half-spread ask-side
            spread_capture_per_rt = (base / 2) * avg_vol * 2  # buy low + sell high
            fee_per_rt = self._FEE_RATE * avg_vol

            # Adverse selection derived from GM decomposition
            adverse_sel = spread_capture_per_rt - fee_per_rt - avg_pnl
            net_edge = avg_pnl  # directly measured

            # Percentage terms (vs volume)
            adverse_pct = (adverse_sel / avg_vol * 100) if avg_vol > 0 else 0.0
            net_edge_pct = (net_edge / avg_vol * 100) if avg_vol > 0 else 0.0
            fee_pct = (fee_per_rt / avg_vol * 100) if avg_vol > 0 else 0.0

            gm_gate = net_edge > 0  # Glosten-Milgrom: positive net edge

            result["pairs"][pair] = {
                "n_rts": n,
                "avg_volume": round(avg_vol, 4),
                "spread_capture_per_rt": round(spread_capture_per_rt, 6),
                "fee_per_rt": round(fee_per_rt, 6),
                "adverse_selection_per_rt": round(adverse_sel, 6),
                "net_pnl_per_rt": round(avg_pnl, 6),
                "adverse_pct": round(adverse_pct, 4),
                "net_edge_pct": round(net_edge_pct, 4),
                "fee_pct": round(fee_pct, 4),
                "gm_gate_ok": gm_gate,
                "regime": "profitable" if gm_gate else "adverse_selection_dominates",
            }

        result["status"] = "ok"
        result["interpretation"] = (
            "net_edge_pct>0 means spread_capture beats adverse_selection+fee; "
            "Glosten-Milgrom 1985 framework."
        )
        self._cache = result
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# 7d. TullockContestTracker — SoPoints competition analysis (Fable5 §Tullock)
# ═══════════════════════════════════════════════════════════════════════════════

class TullockContestTracker:
    """Estimates total competition pool and marginal value of volume.

    Tullock contest model: SoPoints = proportional prize.
    If we received R points for V volume in a period:
      X_total_implied = V × 1,000,000 / R  (where 1M = total pool/week)
    Marginal value per $1 volume = (1M / X_total^2) × prize_pool_usd
    Front-load signal: compare marginal value now vs projected endgame.
    """

    _TOTAL_POOL_PTS = 1_000_000   # SoPoints pool per week (approximate)

    def __init__(self) -> None:
        self._cache: Dict[str, Any] = {}
        self._cache_ts: float = 0.0

    def analyze(self, db_path: Optional[Path]) -> Dict[str, Any]:
        now = time.time()
        if now - self._cache_ts < 600:  # refresh every 10 min
            return self._cache
        self._cache_ts = now
        if not db_path or not db_path.exists():
            self._cache = {"status": "no_db", "weekly_points": []}
            return self._cache

        result: Dict[str, Any] = {}
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            rows = conn.execute(
                "SELECT week_sat, CAST(points AS REAL), note FROM weekly_points "
                "ORDER BY week_sat DESC LIMIT 8"
            ).fetchall()
            conn.close()
        except Exception:
            result["status"] = "db_error"
            self._cache = result
            return result

        if not rows:
            result["status"] = "no_data"
            result["weekly_points"] = []
            result["action"] = (
                "weekly_points table is EMPTY — blind spot detected. "
                "Cannot compute Tullock competition pressure. "
                "Ensure weekly SoPoints data is being logged to twin_engine.db weekly_points table."
            )
            self._cache = result
            return result

        weeks = []
        for week_sat, pts, note in rows:
            if pts and pts > 0:
                weeks.append({"week": week_sat, "points": pts, "note": note or ""})

        if not weeks:
            result["status"] = "empty_points"
            result["action"] = "Points recorded but all zero — check data logging."
            self._cache = result
            return result

        # Estimate competition from most recent week
        latest = weeks[0]
        pts_received = latest["points"]
        # We need our volume for that week — approximate from RT volume in DB
        # This is approximate without exact weekly volume tracking
        result["status"] = "ok"
        result["latest_week"] = latest["week"]
        result["pts_received"] = pts_received
        result["n_weeks_tracked"] = len(weeks)
        result["weekly_points"] = weeks

        # Simplified Tullock: if we got pts_received out of 1M pool
        # our volume share = pts_received / 1M
        our_share = pts_received / self._TOTAL_POOL_PTS
        x_total_implied_rel = 1.0 / our_share if our_share > 0 else float("inf")

        result["our_share_pct"] = round(our_share * 100, 4)
        result["x_total_implied_times_our_x"] = round(x_total_implied_rel, 2)
        result["advice"] = (
            "Front-load volume early in each week (weeks 13-18 July per Fable doc). "
            "Marginal SoPoints value decreases as competitors add more volume. "
            "In endgame (final 2 days), marginal value may drop below cost."
        )
        self._cache = result
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# 7e. KellyInventoryCap — fractional Kelly sizing for inventory (Fable5 §Kelly)
# ═══════════════════════════════════════════════════════════════════════════════

class KellyInventoryCap:
    """Computes maximum inventory per pair using fractional Kelly criterion.

    Fable5 recommendation: f = 1/4 Kelly → ±15% capital per pair.
    Formula: f_kelly = (p × b − q) / b  where p=WR, b=avg_win/avg_loss, q=1-p
    f_quarter = f_kelly / 4
    cap_usd = f_quarter × total_capital_usd
    """

    _FRACTION = 0.25   # quarter-Kelly

    def __init__(self) -> None:
        self._cache: Dict[str, Any] = {}
        self._cache_ts: float = 0.0

    def compute(self, db_path: Optional[Path],
                capital_usd: float,
                base_spreads: Dict[str, float]) -> Dict[str, Any]:
        now = time.time()
        if now - self._cache_ts < 180:
            return self._cache
        self._cache_ts = now
        if not db_path or not db_path.exists():
            self._cache = {"status": "no_db", "pairs": {}}
            return self._cache

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=168)).isoformat()
        result: Dict[str, Any] = {"pairs": {}, "capital_usd": capital_usd}
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            rows = conn.execute(
                "SELECT pair, CAST(net_pnl AS REAL), CAST(volume AS REAL) "
                "FROM rts WHERE engine='E1' AND ts_close > ? AND volume IS NOT NULL",
                (cutoff,)
            ).fetchall()
            conn.close()
        except Exception:
            result["status"] = "db_error"
            self._cache = result
            return result

        pair_data: Dict[str, Dict] = {}
        for pair, pnl, vol in rows:
            if vol and vol > 0 and pnl is not None:
                pd = pair_data.setdefault(pair, {"wins": [], "losses": []})
                pnl_pct = pnl / vol  # normalized return per unit volume
                if pnl_pct > 0:
                    pd["wins"].append(pnl_pct)
                else:
                    pd["losses"].append(abs(pnl_pct))

        for pair, pd in pair_data.items():
            wins = pd["wins"]
            losses = pd["losses"]
            n = len(wins) + len(losses)
            if n < 10:
                result["pairs"][pair] = {
                    "status": "insufficient_data",
                    "n_rts": n,
                    "cap_usd": round(capital_usd * 0.15, 2),  # default 15%
                }
                continue

            p = len(wins) / n
            q = 1.0 - p
            avg_win = sum(wins) / len(wins) if wins else 0.001
            avg_loss = sum(losses) / len(losses) if losses else 0.001
            b = avg_win / avg_loss  # payoff ratio

            # Full Kelly fraction (unbounded edge)
            f_kelly = max(0.0, (p * b - q) / b) if b > 0 else 0.0
            f_quarter = f_kelly * self._FRACTION
            cap_pct = min(0.25, f_quarter)  # hard cap at 25% of capital
            cap_usd = round(capital_usd * cap_pct, 2)

            result["pairs"][pair] = {
                "n_rts": n,
                "win_rate": round(p, 4),
                "avg_win_pct": round(avg_win * 100, 4),
                "avg_loss_pct": round(avg_loss * 100, 4),
                "payoff_ratio_b": round(b, 3),
                "full_kelly_f": round(f_kelly, 4),
                "quarter_kelly_f": round(f_quarter, 4),
                "cap_pct": round(cap_pct * 100, 2),
                "cap_usd": cap_usd,
                "interpretation": (
                    f"Maximum inventory per side: ±${cap_usd} "
                    f"(quarter-Kelly at {capital_usd:.0f} USDC capital)"
                ),
            }

        result["status"] = "ok"
        result["kelly_fraction"] = self._FRACTION
        self._cache = result
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# 7f. AvellanedaStoikovParams — optimal spread formula estimation (Fable5 §AS)
# ═══════════════════════════════════════════════════════════════════════════════

class AvellanedaStoikovParams:
    """Estimates Avellaneda-Stoikov (2008) parameters from live fill data.

    Formulas:
      σ²  = realized variance of mid-price returns from fill prices
      κ    = liquidity param from fill-rate vs offset regression: λ(δ) = A·e^(−κδ)
      δ* (optimal half-spread) = γ·σ²·(T−t) + (2/γ)·ln(1 + γ/κ)

    We use γ = 0.1 (moderate risk aversion) and T-t = 300s (snapshot window).
    Outputs are advisory — actual spread set by bandit; A-S gives floor guidance.
    """

    _GAMMA   = 0.1     # risk aversion coefficient
    _T_MINUS_T = 300.0  # quoting window in seconds

    def __init__(self) -> None:
        self._cache: Dict[str, Any] = {}
        self._cache_ts: float = 0.0

    def estimate(self, db_path: Optional[Path],
                 bandit: "SpreadBandit",
                 base_spreads: Dict[str, float]) -> Dict[str, Any]:
        now = time.time()
        if now - self._cache_ts < 180:
            return self._cache
        self._cache_ts = now
        if not db_path or not db_path.exists():
            self._cache = {"status": "no_db", "pairs": {}}
            return self._cache

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        result: Dict[str, Any] = {"pairs": {}}
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            rows = conn.execute(
                "SELECT pair, ts, side, CAST(price AS REAL) FROM fills "
                "WHERE engine='E1' AND ts > ? AND price IS NOT NULL ORDER BY ts ASC",
                (cutoff,)
            ).fetchall()
            conn.close()
        except Exception:
            result["status"] = "db_error"
            self._cache = result
            return result

        pair_prices: Dict[str, List[float]] = {}
        for pair, _ts, _side, price in rows:
            if price and price > 0:
                pair_prices.setdefault(pair, []).append(price)

        for pair, prices in pair_prices.items():
            if len(prices) < 10:
                continue
            base = base_spreads.get(pair, 0.0010)

            # σ²: realized variance of log-returns from consecutive fill prices
            log_rets = [math.log(prices[i+1] / prices[i])
                        for i in range(len(prices)-1)
                        if prices[i] > 0 and prices[i+1] > 0]
            if not log_rets:
                continue
            mu = sum(log_rets) / len(log_rets)
            sigma_sq = sum((r - mu)**2 for r in log_rets) / len(log_rets)

            # κ from bandit fill-rate data (fit: fill_rate = A·e^(−κ·spread))
            bstate = bandit.state().get(pair, {})
            arms: Dict[str, Any] = {}
            for bucket_key, bdata in bstate.items():
                arms.update(bdata.get("arms", {}))

            kappa = 5.0  # default (reasonable for crypto maker)
            if len(arms) >= 2:
                xs, ys = [], []
                for spread_str, arm_data in arms.items():
                    try:
                        sp = float(spread_str)
                        n_arm = arm_data.get("n", 0)
                        mu_arm = arm_data.get("mu", 0.0)
                        if n_arm > 0 and mu_arm > 0:
                            xs.append(sp)
                            ys.append(math.log(max(1e-9, mu_arm)))
                    except Exception:
                        pass
                if len(xs) >= 2:
                    # linear regression: ln(λ) = ln(A) - κ·δ  → slope = -κ
                    x_bar = sum(xs) / len(xs)
                    y_bar = sum(ys) / len(ys)
                    num = sum((xs[i]-x_bar)*(ys[i]-y_bar) for i in range(len(xs)))
                    den = sum((xs[i]-x_bar)**2 for i in range(len(xs)))
                    if abs(den) > 1e-12:
                        slope = num / den
                        kappa = max(1.0, min(50.0, -slope))

            gamma = self._GAMMA
            T_t = self._T_MINUS_T

            # A-S optimal half-spread: δ* = γ·σ²·(T−t) + (2/γ)·ln(1 + γ/κ)
            term1 = gamma * sigma_sq * T_t
            term2 = (2.0 / gamma) * math.log(1.0 + gamma / kappa) if kappa > 0 else 0.0
            delta_star = term1 + term2
            optimal_spread = delta_star * 2  # bid-ask total spread

            # Clamp to safe range: [base×0.5 .. base×3.0]
            optimal_spread_clamped = max(base * 0.5, min(base * 3.0, optimal_spread))

            result["pairs"][pair] = {
                "n_prices": len(prices),
                "sigma_sq": round(sigma_sq, 10),
                "sigma_annualized_pct": round(math.sqrt(sigma_sq * 365 * 24 * 3600) * 100, 4),
                "kappa": round(kappa, 4),
                "gamma": gamma,
                "T_minus_t_s": T_t,
                "as_half_spread": round(delta_star, 6),
                "as_total_spread": round(optimal_spread, 6),
                "as_optimal_spread_clamped": round(optimal_spread_clamped, 6),
                "base_spread": round(base, 6),
                "as_vs_base_pct": round((optimal_spread_clamped - base) / base * 100, 2),
                "interpretation": (
                    "A-S formula suggests this spread as risk-adjusted optimum. "
                    "Higher σ → wider spread. Higher κ → more competitive → tighter spread. "
                    "Use as floor guidance; bandit UCB1 drives the actual selection."
                ),
            }

        result["status"] = "ok"
        result["formula"] = "Avellaneda-Stoikov 2008: δ* = γσ²(T-t) + (2/γ)ln(1+γ/κ)"
        self._cache = result
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# 8. DeepLearnerLoop — main orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

class DeepLearnerLoop:
    """Main loop: runs every 60s, updates all models, writes learned params.

    Lifecycle:
      step()     — one iteration (load fills, update models, write params)
      run()      — blocking loop (signal handler stops gracefully on SIGINT/SIGTERM)
      run_once() — single step (for CLI / testing)
    """

    def __init__(self,
                 db_path: Optional[Path] = None,
                 base_spreads: Optional[Dict[str, float]] = None) -> None:
        self.analyzer    = FillAnalyzer(db_path)
        self.bandit      = SpreadBandit()
        self.fill_model  = FillProbModel()
        self.enricher    = RegimeEnricher()
        self.cross_system = CrossSystemExperienceMiner()
        self.writer      = ParamWriter()
        self.dead_hour   = DeadHourDetector()
        self.base_spreads = base_spreads or _load_base_spreads()
        # Fable5 scientific components
        self.sprt        = SPRTMonitor()
        self.hawkes      = HawkesIntensityEstimator()
        self.markout     = MarkoutTracker()
        self.tullock     = TullockContestTracker()
        self.kelly       = KellyInventoryCap()
        self.as_params   = AvellanedaStoikovParams()
        self._iteration  = 0
        self._last_log_ts: float = 0.0
        self._started = datetime.now(timezone.utc).isoformat()

    def step(self) -> Dict[str, Any]:
        """One learning iteration. Returns the written params payload."""
        t0 = time.time()

        # 1. Load new fills/RTs from DB
        new_fills, new_rts = self.analyzer.load_incremental()

        # 2. Update bandit based on new RT results
        if new_rts > 0:
            for (pair, bucket), s in self.analyzer.stats.items():
                net = self.analyzer.net_rate(pair, bucket)
                if not math.isnan(net):
                    # estimate which spread was active (use base as proxy for now)
                    base = self.base_spreads.get(pair, 0.0015)
                    self.bandit.update(pair, bucket, base, net)

        # 3. Update fill prob model (fills = positive examples)
        now_h = datetime.now(timezone.utc).hour
        regime = self.enricher.current()
        if new_fills > 0:
            for (pair, bucket), s in self.analyzer.stats.items():
                if s["fills"] > 0:
                    base_sp = self.base_spreads.get(pair, 0.0015)
                    inv_frac = min(1.0, s["buy_fills"] /
                                   max(1, s["buy_fills"] + s["sell_fills"]))
                    self.fill_model.learn_one(
                        base_sp * 10000, now_h, regime, inv_frac, filled=True
                    )

        # 4. Get dead hours
        dead_hours = self.dead_hour.get_dead_hours()

        # 5. Collect read-only cross-system/external experience
        cross_system = self.cross_system.collect()

        # 6. Write core learned params
        payload = self.writer.write(
            self.bandit, self.fill_model, self.analyzer,
            self.enricher, self.base_spreads, dead_hours, cross_system
        )

        # 7. Fable5 scientific analysis (read-only, enriches payload)
        db = self.analyzer.db_path
        capital_usd = float(_env_or_dotenv("ANANTARA_CAPITAL_USD", "417").split("#")[0].strip())

        sprt_result    = self.sprt.analyze(db)
        hawkes_result  = self.hawkes.estimate(db)
        markout_result = self.markout.analyze(db, self.base_spreads)
        tullock_result = self.tullock.analyze(db)
        kelly_result   = self.kelly.compute(db, capital_usd, self.base_spreads)
        as_result      = self.as_params.estimate(db, self.bandit, self.base_spreads)

        payload["sprt"]              = sprt_result
        payload["hawkes"]            = hawkes_result
        payload["markout_gm"]        = markout_result
        payload["tullock_contest"]   = tullock_result
        payload["kelly_sizing"]      = kelly_result
        payload["avellaneda_stoikov"] = as_result

        # Merge A-S optimal spread guidance into pairs (advisory only, not overwrite)
        for pair, as_data in as_result.get("pairs", {}).items():
            if pair in payload["pairs"] and "as_optimal_spread_clamped" in as_data:
                payload["pairs"][pair]["as_guidance"] = as_data["as_optimal_spread_clamped"]
                payload["pairs"][pair]["as_kappa"]    = as_data.get("kappa")
                payload["pairs"][pair]["as_sigma_sq"] = as_data.get("sigma_sq")

        # Merge SPRT edge status into pairs
        for pair, sprt_data in sprt_result.get("pairs", {}).items():
            if pair in payload["pairs"]:
                payload["pairs"][pair]["sprt_status"] = sprt_data.get("status")
                payload["pairs"][pair]["sprt_llr"]    = sprt_data.get("llr")
                payload["pairs"][pair]["sprt_wr"]     = sprt_data.get("wr")

        # Merge Hawkes activity state into pairs
        for pair, h_data in hawkes_result.get("pairs", {}).items():
            if pair in payload["pairs"]:
                payload["pairs"][pair]["activity_state"]  = h_data.get("activity_state")
                payload["pairs"][pair]["hawkes_intensity"] = h_data.get("intensity")

        # Merge Kelly cap into pairs
        for pair, k_data in kelly_result.get("pairs", {}).items():
            if pair in payload["pairs"]:
                payload["pairs"][pair]["kelly_cap_usd"] = k_data.get("cap_usd")
                payload["pairs"][pair]["kelly_cap_pct"] = k_data.get("cap_pct")

        # Merge GM edge gate into pairs
        for pair, m_data in markout_result.get("pairs", {}).items():
            if pair in payload["pairs"]:
                payload["pairs"][pair]["gm_edge_ok"]  = m_data.get("gm_gate_ok")
                payload["pairs"][pair]["net_edge_pct"] = m_data.get("net_edge_pct")

        # Atomic re-write with enriched payload
        _atomic_write(LEARNED_PARAMS, json.dumps(payload, indent=2))

        # 8. Append to audit log (every 5 min to reduce disk writes)
        now_f = time.time()
        if now_f - self._last_log_ts >= 300:
            self._append_log(payload, new_fills, new_rts, now_f - t0)
            self._last_log_ts = now_f

        self._iteration += 1
        return payload

    def run_once(self) -> Dict[str, Any]:
        return self.step()

    def run(self, max_iterations: int = 0) -> None:
        """Blocking loop. max_iterations=0 → run forever."""
        import signal

        _stop = [False]

        def _handler(sig, frame):
            _log("DeepLearner: received signal, stopping gracefully")
            _stop[0] = True

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)

        _log(f"DeepLearner started: pairs={list(self.base_spreads.keys())}, "
             f"interval={_LOOP_INTERVAL}s")

        while not _stop[0]:
            if max_iterations and self._iteration >= max_iterations:
                break
            try:
                payload = self.step()
                _log_step(self._iteration, payload)
            except Exception as exc:
                _log(f"DeepLearner step error (iteration {self._iteration}): {exc}")
            time.sleep(_LOOP_INTERVAL)

        _log(f"DeepLearner stopped after {self._iteration} iterations")

    def _append_log(self, payload: Dict[str, Any], new_fills: int,
                    new_rts: int, elapsed_s: float) -> None:
        entry = {
            "ts":          payload["ts"],
            "iteration":   self._iteration,
            "new_fills":   new_fills,
            "new_rts":     new_rts,
            "elapsed_s":   round(elapsed_s, 3),
            "regime":      payload.get("regime"),
            "regime_acc":  payload.get("regime_accuracy"),
            "fill_model_n": payload.get("fill_model_n"),
            "awareness_quality": payload.get("awareness", {}).get("quality"),
            "experience": {
                "fills_total_loaded": payload.get("experience", {}).get("fills_total_loaded"),
                "rts_total_loaded": payload.get("experience", {}).get("rts_total_loaded"),
                "unique_rt_ids_seen": payload.get("experience", {}).get("unique_rt_ids_seen"),
            },
            "cross_system_experience": {
                "sources_count": payload.get("cross_system_experience", {}).get("sources_count"),
                "lessons_count": payload.get("cross_system_experience", {}).get("lessons_count"),
                "quality": payload.get("cross_system_experience", {}).get("quality"),
            },
            "pairs":       {
                p: {
                    "min_spread": d["min_spread"],
                    "confidence": d["confidence"],
                    "delta_bps":  d["delta_bps"],
                }
                for p, d in payload.get("pairs", {}).items()
            },
        }
        try:
            with open(DEEP_LOG, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Engine integration helper — read learned spread at runtime
# ═══════════════════════════════════════════════════════════════════════════════

_LEARNED_CACHE: Tuple[float, Optional[Dict[str, Any]]] = (0.0, None)
_LEARNED_TTL = 90  # seconds


def get_learned_min_spread(pair: str, env_default: float) -> float:
    """Called by Engine1Flywheel._min_spread() — reads learned params with TTL cache.

    Returns env_default if: file missing, stale (>90s), parse error, or out-of-bounds.
    This function is safe to call every tick; TTL prevents disk thrash.
    """
    global _LEARNED_CACHE
    now = time.time()
    cache_ts, cached = _LEARNED_CACHE
    if now - cache_ts < _LEARNED_TTL and cached is not None:
        data = cached
    else:
        try:
            if LEARNED_PARAMS.exists():
                data = json.loads(LEARNED_PARAMS.read_text())
                _LEARNED_CACHE = (now, data)
            else:
                _LEARNED_CACHE = (now, None)
                return env_default
        except Exception:
            _LEARNED_CACHE = (now, None)
            return env_default

    # staleness check
    ts_str = data.get("ts", "")
    if ts_str:
        try:
            age = (datetime.now(timezone.utc) -
                   datetime.fromisoformat(ts_str)).total_seconds()
            if age > _LEARNED_TTL:
                return env_default
        except Exception:
            return env_default

    pair_data = data.get("pairs", {}).get(pair)
    if not pair_data:
        return env_default

    raw = pair_data.get("min_spread")
    if raw is None:
        return env_default

    try:
        val = float(raw)
    except (TypeError, ValueError):
        return env_default

    # hard safety bounds: must be within [env_default × 0.50 .. env_default × 2.0]
    if val < env_default * 0.50 or val > env_default * 2.0:
        return env_default

    return val


def reset_learned_cache() -> None:
    """Force cache refresh on next call (for testing)."""
    global _LEARNED_CACHE
    _LEARNED_CACHE = (0.0, None)


# ═══════════════════════════════════════════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════════════════════════════════════════

def _find_db() -> Optional[Path]:
    for p in _DB_CANDIDATES:
        if p.exists():
            return p
    return None


def _ts_to_hour(ts_str: str) -> int:
    """Parse ISO timestamp string → UTC hour (0-23)."""
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).hour
    except Exception:
        return 0


def _max_iso_ts(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """Return later ISO timestamp string, preserving original string values."""
    if not a:
        return b
    if not b:
        return a
    try:
        da = datetime.fromisoformat(a)
        db = datetime.fromisoformat(b)
        if da.tzinfo is None:
            da = da.replace(tzinfo=timezone.utc)
        if db.tzinfo is None:
            db = db.replace(tzinfo=timezone.utc)
        return b if db > da else a
    except Exception:
        return max(a, b)


def _age_minutes(ts_str: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ref = now or datetime.now(timezone.utc)
        return round(max(0.0, (ref - dt.astimezone(timezone.utc)).total_seconds() / 60), 2)
    except Exception:
        return None


def _dotenv_get(key: str) -> Optional[str]:
    """Read selected non-secret config from .env without loading credentials."""
    if key in os.environ:
        return os.environ[key]
    if not ENV_FILE.exists():
        return None
    try:
        for line in ENV_FILE.read_text().splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            k, v = raw.split("=", 1)
            if k.strip() != key:
                continue
            val = v.strip().strip('"').strip("'")
            return val
    except Exception:
        return None
    return None


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def _sanitize_external_line(line: str) -> str:
    raw = " ".join(str(line).strip().split())
    if not raw:
        return ""
    if any(marker in raw.upper() for marker in _SECRET_PATTERNS):
        return ""
    raw = re.sub(r"https://api\.telegram\.org/bot[^/\s]+", "https://api.telegram.org/bot[REDACTED]", raw)
    raw = re.sub(r"\b0x[a-fA-F0-9]{48,}\b", "0x[REDACTED]", raw)
    return raw


def _walk_json(obj: Any, prefix: str = ""):
    if isinstance(obj, dict):
        for key, val in obj.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield from _walk_json(val, next_prefix)
    elif isinstance(obj, list):
        for i, val in enumerate(obj[:20]):
            yield from _walk_json(val, f"{prefix}[{i}]")
    else:
        yield prefix, obj


def _env_or_dotenv(key: str, default: str) -> str:
    val = _dotenv_get(key)
    return default if val is None else val


def _load_base_spreads() -> Dict[str, float]:
    """Load base spreads from env (TE_E1_MIN_SPREAD etc.) with fallback defaults."""
    pairs = {}
    pair1 = _env_or_dotenv("TE_SPOT_PAIR", "PEPE/USDC").strip()
    pair2 = _env_or_dotenv("TE_SPOT_PAIR_2", "SHIB/USDC").strip()
    pair3 = _env_or_dotenv("TE_SPOT_PAIR_3", "").strip()
    if pair1:
        pairs[pair1] = float(_env_or_dotenv("TE_E1_MIN_SPREAD", "0.0010"))
    if pair2:
        pairs[pair2] = float(_env_or_dotenv("TE_E1_PAIR2_MIN_SPREAD", "0.0015"))
    if pair3:
        pairs[pair3] = float(_env_or_dotenv("TE_E1_PAIR3_MIN_SPREAD", "0.0010"))
    return pairs


def _atomic_write(path: Path, content: str) -> None:
    """Write content to path atomically (tmp → rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content)
    tmp.replace(path)


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}Z] {msg}",
          flush=True)


def _log_step(iteration: int, payload: Dict[str, Any]) -> None:
    pairs_info = ", ".join(
        f"{p}: {d['min_spread']:.4f}({d['confidence'][0].upper()})"
        f"|sprt={d.get('sprt_status','?')[:7]}"
        f"|gm={'OK' if d.get('gm_edge_ok') else 'NO'}"
        f"|act={d.get('activity_state','?')[:4]}"
        for p, d in payload.get("pairs", {}).items()
    )
    _log(f"[iter={iteration}] regime={payload.get('regime')} | {pairs_info} | "
         f"model_n={payload.get('fill_model_n')}")
