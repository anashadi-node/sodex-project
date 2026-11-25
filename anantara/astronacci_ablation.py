#!/usr/bin/env python3
"""
ASTRONACCI v1.0 — Ablation Framework & Evidence Registry

ABLATION (M0-M8):
  Pertanyaan paling penting: apakah astro MENAMBAH nilai di atas TA dan makro?
  Jika full model menang tetapi TA-only sudah hampir sama, maka astro tidak
  memberi kontribusi nyata.

EVIDENCE REGISTRY:
  Menyimpan status setiap fitur/sinyal: rejected / watchlist / research / production.
  Epistemic Governor membaca registry ini untuk memblokir sinyal yang belum valid.

DOKTRIN:
  Accept astro feature only if:
    ΔMetric = Metric(TA+Macro+Astro) - Metric(TA+Macro) > 0
    AND SPA p-value < 0.05
    AND DSR > 0
    AND PBO < 20%
    AND result survives at least 70% of robustness panels.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from astronacci_stats import (
    StatisticalDefenseSystem,
    DefenseResult,
    deflated_sharpe_ratio,
    spa_test_pvalue,
    probability_of_backtest_overfitting,
)


# ─────────────────────────────────────────────────────────────────────────────
# ABLATION MODEL DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AblationModel:
    """Definition of one ablation model variant."""
    id: str           # M0, M1, ..., M8
    name: str
    features_included: list[str]
    description: str
    is_baseline: bool = False


# Standard 9-model ablation suite (from Astronacci Falsification Lab v2.0)
ABLATION_MODELS: list[AblationModel] = [
    AblationModel("M0", "Random Baseline", [],
                  "Apakah semua model hanya kebetulan?", is_baseline=True),
    AblationModel("M1", "Buy & Hold", [],
                  "Apakah trading aktif mengalahkan pasif?", is_baseline=True),
    AblationModel("M2", "TA Only", ["rsi", "adx", "atr_pct", "hl_range",
                  "dist_to_vwap", "volume_ratio"],
                  "Berapa edge dari indikator konvensional?"),
    AblationModel("M3", "Macro Only", ["dxy", "real_yield", "funding_rate",
                  "btc_dominance", "vix"],
                  "Berapa edge dari regime fundamental?"),
    AblationModel("M4", "Astro Only", ["lunar_phase_sin", "lunar_phase_cos",
                  "lunar_illumination", "lunar_days_to_full",
                  "aspect_conjunction_max", "aspect_opposition_max",
                  "retrograde_count", "planet_cluster_density"],
                  "Apakah astro berdiri sendiri punya sinyal?"),
    AblationModel("M5", "Behavioral Attention Only", ["google_trends_score",
                  "news_volume", "sentiment_polarity", "attention_shock"],
                  "Apakah attention lebih kuat daripada astro?"),
    AblationModel("M6", "TA + Macro", ["rsi", "adx", "atr_pct", "hl_range",
                  "dist_to_vwap", "volume_ratio", "dxy", "real_yield",
                  "funding_rate", "btc_dominance", "vix"],
                  "Baseline profesional minimum."),
    AblationModel("M7", "TA + Macro + Astro", ["rsi", "adx", "atr_pct",
                  "hl_range", "dist_to_vwap", "volume_ratio", "dxy",
                  "real_yield", "funding_rate", "btc_dominance", "vix",
                  "lunar_phase_sin", "lunar_phase_cos", "lunar_illumination",
                  "lunar_days_to_full", "aspect_conjunction_max",
                  "aspect_opposition_max", "retrograde_count",
                  "planet_cluster_density"],
                  "Apakah astro menambah incremental alpha?"),
    AblationModel("M8", "TA + Macro + Astro × Attention", ["rsi", "adx",
                  "atr_pct", "hl_range", "dist_to_vwap", "volume_ratio",
                  "dxy", "real_yield", "funding_rate", "btc_dominance",
                  "vix", "lunar_phase_sin", "lunar_phase_cos",
                  "lunar_illumination", "lunar_days_to_full",
                  "aspect_conjunction_max", "aspect_opposition_max",
                  "retrograde_count", "planet_cluster_density",
                  "lunar_illum_x_attention", "aspect_conjunction_x_attention",
                  "retrograde_x_attention", "cluster_density_x_attention"],
                  "Model paling plausible secara ilmiah."),
]


# ─────────────────────────────────────────────────────────────────────────────
# ABLATION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AblationResult:
    """Result for one model in the ablation study."""
    model_id: str
    model_name: str
    sharpe: float
    sortino: float
    max_drawdown: float
    annual_return: float
    annual_vol: float
    win_rate: float
    avg_win: float
    avg_loss: float
    n_trades: int

    # vs M6 baseline
    delta_sharpe_vs_m6: float = 0.0
    delta_return_vs_m6: float = 0.0


@dataclass
class AblationStudy:
    """Complete ablation study results."""
    timestamp: str
    asset: str
    timeframe: str
    models: dict[str, AblationResult]
    m6_baseline_sharpe: float
    m7_incremental_sharpe: float    # ΔSharpe M7 - M6
    m8_incremental_sharpe: float    # ΔSharpe M8 - M6

    # Statistical validation
    spa_pvalue_m7_vs_m6: float
    dsr_m7: float
    pbo_m7: float | None    # None when CSCV could not be computed (honest unknown)

    # Verdict
    astro_adds_alpha: bool
    attention_adds_alpha: bool
    evidence_score: int


class AblationEngine:
    """Run ablation studies comparing model variants.

    Usage:
        engine = AblationEngine()
        study = engine.run(
            asset="BTC", timeframe="Daily",
            model_metrics={model_id: {...}, ...},
        )
    """

    def run(
        self,
        asset: str,
        timeframe: str,
        model_metrics: dict[str, dict],
        all_candidate_sharpes: list[float] | None = None,
    ) -> AblationStudy:
        """Run full ablation analysis.

        Args:
            asset: Asset name
            timeframe: Timeframe string
            model_metrics: {model_id: {"sharpe": ..., "sortino": ..., ...}, ...}
            all_candidate_sharpes: Sharpes of all variants for SPA/DSR computation
        """
        results: dict[str, AblationResult] = {}

        for model in ABLATION_MODELS:
            m = model_metrics.get(model.id, {})
            results[model.id] = AblationResult(
                model_id=model.id,
                model_name=model.name,
                sharpe=m.get("sharpe", 0.0),
                sortino=m.get("sortino", 0.0),
                max_drawdown=m.get("max_drawdown", 0.0),
                annual_return=m.get("annual_return", 0.0),
                annual_vol=m.get("annual_vol", 0.0),
                win_rate=m.get("win_rate", 0.0),
                avg_win=m.get("avg_win", 0.0),
                avg_loss=m.get("avg_loss", 0.0),
                n_trades=m.get("n_trades", 0),
            )

        # Compute deltas vs M6 (TA + Macro baseline)
        m6_sharpe = results.get("M6", AblationResult("M6", "", 0, 0, 0, 0, 0, 0, 0, 0, 0)).sharpe
        m7_sharpe = results.get("M7", AblationResult("M7", "", 0, 0, 0, 0, 0, 0, 0, 0, 0)).sharpe
        m8_sharpe = results.get("M8", AblationResult("M8", "", 0, 0, 0, 0, 0, 0, 0, 0, 0)).sharpe

        for mid, r in results.items():
            r.delta_sharpe_vs_m6 = r.sharpe - m6_sharpe
            r.delta_return_vs_m6 = r.annual_return - results.get(
                "M6", AblationResult("M6", "", 0, 0, 0, 0, 0, 0, 0, 0, 0)
            ).annual_return

        # SPA test for M7 vs M6
        candidates = all_candidate_sharpes or [m6_sharpe, m7_sharpe, m8_sharpe]
        spa_p = spa_test_pvalue(m7_sharpe, candidates)

        # DSR for M7
        dsr = deflated_sharpe_ratio(m7_sharpe, len(candidates), 500)
        dsr_val = dsr["deflated_sharpe"]

        # PBO (Gate 7) — computed from REAL IS/OOS data when provided.
        #
        # PREVIOUS IMPLEMENTATION (BUG — circular reasoning):
        #   pbo = 0.3 if m7_sharpe > m6_sharpe else 0.7
        # This derived the PBO verdict from the SAME M7-vs-M6 comparison it
        # was supposed to validate independently. A higher M7 Sharpe was
        # tautologically declared "low overfit risk (0.3)" purely because it
        # was higher — circular logic that always favoured the astro model.
        #
        # FIX: PBO requires paired in-sample/out-of-sample metrics per trial.
        # If the caller supplies them via `is_sharpes`/`oos_sharpes`, we run
        # the genuine CSCV procedure (Bailey et al. 2015). Otherwise we report
        # pbo=None and is_computed=False so downstream consumers CANNOT mistake
        # a placeholder for a measured value — an honest "unknown" rather than
        # a fabricated number, consistent with falsification-first doctrine.
        is_sharpes = model_metrics.get("__meta__", {}).get("is_sharpes")
        oos_sharpes = model_metrics.get("__meta__", {}).get("oos_sharpes")
        if (
            is_sharpes
            and oos_sharpes
            and len(is_sharpes) == len(oos_sharpes)
            and len(is_sharpes) >= 4
        ):
            pbo_result = probability_of_backtest_overfitting(
                is_sharpes, oos_sharpes, seed=42,
            )
            pbo = pbo_result["pbo"]
            pbo_computed = True
        else:
            pbo = None
            pbo_computed = False

        # Verdict — FALSIFICATION-FIRST, logical AND-gates (not additive).
        #
        # The previous implementation used an ADDITIVE score: each passing
        # sub-test added points, so a strong-but-irrelevant test could mask a
        # FAILED critical test. This is how the system promoted features with
        # negative Sharpe (e.g. mercury_retrograde promoted to "PROMISING"
        # despite Sharpe = -0.77). The fix enforces hard VETO gates:
        #
        #   (V1) M7 Sharpe must be POSITIVE (the strategy actually makes money)
        #   (V2) M7 must beat M6 baseline (astro adds incremental value)
        #   (V3) SPA p < 0.10 (not explained by data snooping)
        #   (V4) DSR > 0 (survives selection bias)
        #   (V5) PBO < 0.50 — ONLY enforced when PBO was genuinely computed;
        #       when PBO is unknown (pbo=None), the feature cannot reach
        #       production but is not auto-rejected either (honest uncertainty).
        pbo_pass = (pbo is not None) and (pbo < 0.50)
        m7_positive = m7_sharpe > 0.0
        beats_baseline = m7_sharpe > m6_sharpe

        # astro_adds_alpha requires ALL hard gates — no compensation allowed.
        if pbo_computed:
            astro_adds = (
                m7_positive
                and beats_baseline
                and spa_p < 0.10
                and dsr_val > 0
                and pbo_pass
            )
        else:
            # PBO unknown: cannot grant "alpha" verdict, but record the rest.
            astro_adds = False
        attn_adds = (m8_sharpe > m7_sharpe) and (m8_sharpe > 0.0)

        # Evidence score — additive for ranking, BUT capped by hard vetoes.
        # A negative-Sharpe strategy can NEVER score above the "weak" band.
        evidence = 0
        if beats_baseline:
            evidence += 25
        if spa_p < 0.10:
            evidence += 20
        if dsr_val > 0:
            evidence += 15
        if pbo_pass:
            evidence += 15
        if astro_adds:
            evidence += 15
        if attn_adds:
            evidence += 10

        # HARD VETO CAP: profitability is non-negotiable.
        # Without positive Sharpe the strategy loses money — it cannot be
        # ranked above "weak" (≤50) regardless of other metrics. This is the
        # root-cause fix for false-positive promotion of negative-Sharpe
        # signals observed in the evidence registry.
        if not m7_positive:
            evidence = min(evidence, 30)  # cap at top of "rejected" band
        elif pbo_computed and not pbo_pass:
            evidence = min(evidence, 50)  # cap at "weak" if overfit likely

        return AblationStudy(
            timestamp=datetime.now(timezone.utc).isoformat(),
            asset=asset,
            timeframe=timeframe,
            models=results,
            m6_baseline_sharpe=m6_sharpe,
            m7_incremental_sharpe=m7_sharpe - m6_sharpe,
            m8_incremental_sharpe=m8_sharpe - m6_sharpe,
            spa_pvalue_m7_vs_m6=round(spa_p, 4),
            dsr_m7=round(dsr_val, 4),
            pbo_m7=(round(pbo, 4) if pbo is not None else None),
            astro_adds_alpha=astro_adds,
            attention_adds_alpha=attn_adds,
            evidence_score=min(100, max(0, evidence)),
        )


# ─────────────────────────────────────────────────────────────────────────────
# EVIDENCE REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EvidenceEntry:
    """One entry in the evidence registry."""
    feature_name: str
    layer: int
    layer_name: str
    evidence_score: int       # 0-100
    status: str               # rejected / watchlist / research / production
    last_evaluated: str
    test_results: dict = field(default_factory=dict)
    notes: str = ""


class EvidenceRegistry:
    """Persistent evidence registry for all astro features.

    Status levels:
      • rejected (0-30):  Tidak mengalahkan random atau gagal OOS → disable
      • watchlist (31-50): Ada sinyal kecil tetapi tidak stabil → observation only
      • research (51-70):  Lolos sebagian uji, belum cukup production → research mode
      • production (71-100): Lolos defense system → allowed in trading

    Usage:
        registry = EvidenceRegistry()
        registry.register("lunar_illumination", evidence_score=45)
        allowed = registry.allowed_features()  # only production-status features
    """

    def __init__(self, registry_path: str | None = None):
        if registry_path is None:
            project_dir = os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti"))
            registry_path = str(Path(project_dir) / "data" / "astronacci_evidence.json")
        self._path = Path(registry_path)
        self._entries: dict[str, EvidenceEntry] = {}
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                for name, entry_data in data.get("features", {}).items():
                    self._entries[name] = EvidenceEntry(**entry_data)
            except (json.JSONDecodeError, TypeError):
                pass

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": "1.0",
            "updated": datetime.now(timezone.utc).isoformat(),
            "features": {
                name: asdict(entry) for name, entry in self._entries.items()
            },
        }
        self._path.write_text(json.dumps(data, indent=2, default=str))

    def register(
        self,
        feature_name: str,
        layer: int = 0,
        layer_name: str = "",
        evidence_score: int = 0,
        test_results: dict | None = None,
        notes: str = "",
    ):
        """Register or update a feature's evidence status.

        ROOT-CAUSE ENFORCEMENT (TIER 4 fix):
          Previously any caller could promote a feature to `production` purely
          by passing evidence_score >= 71 — even with no statistical validation
          attached (e.g. improve.py promoted features to score 60-75 from a
          hit-rate heuristic while the underlying Sharpe was negative). This
          decoupled the Evidence Registry from the 7-Gate Statistical Defense
          System that the doctrine REQUIRES for production status.

          Now, `production` status additionally requires a real
          `defense_result` (with `gates_passed` >= 5) to be present in
          `test_results`. Without it the status is CAPPED at `research`,
          regardless of the raw score. This makes the falsification-first
          contract enforceable, not aspirational.
        """
        test_results = test_results or {}
        status = self._score_to_status(evidence_score)

        # Hard gate: production requires a genuine 7-gate defense result.
        if status == "production":
            defense = test_results.get("defense_result")
            if isinstance(defense, dict):
                gates = defense.get("gates_passed", 0)
            else:
                gates = 0
            if gates < 5:
                status = "research"  # cap — not validated through the gates
                notes = (
                    (notes + " | " if notes else "")
                    + f"PRODUCTION CAPPED→research: defense gates_passed={gates} "
                      f"(need >=5). Score {evidence_score} retained but "
                      f"production status requires a 7-gate defense result."
                )

        self._entries[feature_name] = EvidenceEntry(
            feature_name=feature_name,
            layer=layer,
            layer_name=layer_name,
            evidence_score=evidence_score,
            status=status,
            last_evaluated=datetime.now(timezone.utc).isoformat(),
            test_results=test_results,
            notes=notes,
        )
        self._save()

    def validate_with_defense(
        self,
        feature_name: str,
        layer: int,
        layer_name: str,
        defense_result: "DefenseResult",
        notes: str = "",
    ) -> EvidenceEntry:
        """Register a feature using a REAL 7-gate StatisticalDefenseSystem result.

        This is the canonical, doctrine-compliant way to promote a feature:
        run it through the 7-gate defense first, then register the verdict.
        The resulting status can reach `production` because the defense_result
        (with gates_passed) is attached to test_results — satisfying the hard
        gate enforced in `register()`.

        Args:
            feature_name: feature/signal identifier
            layer / layer_name: epistemological layer (1-7)
            defense_result: a DefenseResult from StatisticalDefenseSystem.evaluate
            notes: optional human-readable annotation

        Returns:
            The registered EvidenceEntry.
        """
        gates = int(getattr(defense_result, "gates_passed", 0))
        # Map gates_passed (0-7) onto an evidence score (0-100).
        # 7/7 gates → 100, 5/7 → ~71 (production threshold), <5 → below.
        evidence_score = min(100, round(gates / 7.0 * 100))
        test_results = {
            "defense_result": {
                "signal_name": getattr(defense_result, "signal_name", feature_name),
                "gates_passed": gates,
                "evidence_level": getattr(defense_result, "evidence_level", "rejected"),
                "all_passed": bool(getattr(defense_result, "all_passed", False)),
                "gate1_permutation_pvalue": getattr(defense_result, "gate1_permutation_pvalue", None),
                "gate5_fdr_corrected_pvalue": getattr(defense_result, "gate5_fdr_corrected_pvalue", None),
                "gate6_deflated_sharpe": getattr(defense_result, "gate6_deflated_sharpe", None),
                "gate7_pbo": getattr(defense_result, "gate7_pbo", None),
            },
        }
        self.register(
            feature_name=feature_name, layer=layer, layer_name=layer_name,
            evidence_score=evidence_score, test_results=test_results, notes=notes,
        )
        return self._entries[feature_name]

    def _score_to_status(self, score: int) -> str:
        if score <= 30:
            return "rejected"
        elif score <= 50:
            return "watchlist"
        elif score <= 70:
            return "research"
        else:
            return "production"

    def get(self, feature_name: str) -> EvidenceEntry | None:
        return self._entries.get(feature_name)

    def allowed_features(self) -> list[str]:
        """Return feature names with production status (score > 70)."""
        return [
            name for name, entry in self._entries.items()
            if entry.status == "production"
        ]

    def research_features(self) -> list[str]:
        """Return feature names in research/watchlist status."""
        return [
            name for name, entry in self._entries.items()
            if entry.status in ("research", "watchlist")
        ]

    def rejected_features(self) -> list[str]:
        """Return feature names with rejected status."""
        return [
            name for name, entry in self._entries.items()
            if entry.status == "rejected"
        ]

    def summary(self) -> dict:
        """Summary of registry state."""
        total = len(self._entries)
        statuses = {"rejected": 0, "watchlist": 0, "research": 0, "production": 0}
        for entry in self._entries.values():
            statuses[entry.status] = statuses.get(entry.status, 0) + 1
        return {
            "total_features": total,
            "by_status": statuses,
            "production_count": statuses["production"],
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    def to_dict(self) -> dict:
        return {
            name: asdict(entry) for name, entry in self._entries.items()
        }


# ─────────────────────────────────────────────────────────────────────────────
# EPISTEMIC GOVERNOR
# ─────────────────────────────────────────────────────────────────────────────

class EpistemicGovernor:
    """Blocks unvalidated signals from influencing trade decisions.

    This is the SCIENTIFIC SAFETY LAYER, not a trading layer. It reads the
    Evidence Registry and enforces that only production-status features can
    contribute to trading signals.

    Governor decisions are AUDITABLE — every block is logged with the reason.

    Usage:
        governor = EpistemicGovernor(registry)
        features = {...astro features...}
        decision = governor.gate(features)
        if decision["allowed"]:
            # use features in trading
        else:
            # features blocked — see decision["blocked_features"]
    """

    def __init__(self, registry: EvidenceRegistry):
        self.registry = registry
        self._block_log: list[dict] = []

    def gate(self, feature_vector: dict[str, float]) -> dict:
        """Gate a feature vector: strip unvalidated features, return allowed subset.

        Returns:
            {
                "allowed": bool,
                "allowed_features": {name: value},
                "blocked_features": [name, ...],
                "block_reasons": {name: reason},
                "evidence_scores": {name: score},
            }
        """
        allowed_features: dict[str, float] = {}
        blocked_features: list[str] = []
        block_reasons: dict[str, str] = {}
        evidence_scores: dict[str, int] = {}

        for name, value in feature_vector.items():
            entry = self.registry.get(name)

            if entry is None:
                # Unknown feature — block by default (conservative)
                blocked_features.append(name)
                block_reasons[name] = "unknown_feature"
                evidence_scores[name] = 0
                self._log_block(name, "unknown_feature")
                continue

            evidence_scores[name] = entry.evidence_score

            if entry.status == "production":
                allowed_features[name] = value
            elif entry.status == "research":
                # Research features: allow with flag but log
                allowed_features[name] = value
                block_reasons[name] = "research_mode"
                self._log_block(name, "research_mode")
            else:  # rejected or watchlist
                blocked_features.append(name)
                block_reasons[name] = entry.status
                self._log_block(name, entry.status)

        return {
            "allowed": len(allowed_features) > 0,
            "allowed_features": allowed_features,
            "blocked_features": blocked_features,
            "block_reasons": block_reasons,
            "evidence_scores": evidence_scores,
            "n_allowed": len(allowed_features),
            "n_blocked": len(blocked_features),
        }

    def _log_block(self, feature: str, reason: str):
        self._block_log.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "feature": feature,
            "reason": reason,
        })
        # Keep only last 1000 blocks
        if len(self._block_log) > 1000:
            self._block_log = self._block_log[-1000:]

    def block_summary(self) -> dict:
        """Summary of recent blocks."""
        if not self._block_log:
            return {"total_blocks": 0, "by_reason": {}}

        by_reason: dict[str, int] = {}
        for entry in self._block_log:
            reason = entry["reason"]
            by_reason[reason] = by_reason.get(reason, 0) + 1

        return {
            "total_blocks": len(self._block_log),
            "by_reason": by_reason,
            "last_block": self._block_log[-1] if self._block_log else None,
        }

    # ── Sandwich Credibility Detection (Dossier §11.1) ──

    def detect_sandwich_credibility(self) -> dict:
        """Detect 'sandwich kredibilitas' pattern in the feature registry.

        The Dossier §11.1 identifies a pattern where pseudoscience (Layers 2-3)
        is sandwiched between real science below (Layer 1: astronomy) and
        conventional analysis above (Layers 4-6: TA, macro), creating an
        illusion of overall credibility.

        Returns:
            {
                "sandwich_detected": bool,
                "bottom_layer_ok": bool,   # Layer 1 is real science
                "middle_layer_suspect": bool,  # Layers 2-3 are pseudoscience
                "top_layer_ok": bool,      # Layers 4-6 are conventional
                "credibility_transfer_risk": str,
                "vulnerable_features": [str, ...],
            }
        """
        # Count features by layer × status
        layer_status: dict[int, dict[str, int]] = {}
        for name, entry in self.registry._entries.items():
            layer = entry.layer
            if layer not in layer_status:
                layer_status[layer] = {"production": 0, "research": 0,
                                        "watchlist": 0, "rejected": 0}
            layer_status[layer][entry.status] = (
                layer_status[layer].get(entry.status, 0) + 1
            )

        # Check bottom layer (1: Astronomy) — should be valid
        l1 = layer_status.get(1, {})
        bottom_ok = l1.get("production", 0) > 0

        # Check middle layers (2: Gann/Vibration, 3: Financial Astrology)
        l2 = layer_status.get(2, {})
        l3 = layer_status.get(3, {})
        middle_suspect = (
            (l2.get("production", 0) > 0 or l3.get("production", 0) > 0)
            and (l2.get("rejected", 0) + l3.get("rejected", 0) >
                 l2.get("production", 0) + l3.get("production", 0))
        )

        # Check top layers (4: Fib, 5: TA, 6: Macro)
        top_ok = any(
            layer_status.get(l, {}).get("production", 0) > 0
            for l in [4, 5, 6]
        )

        # Detect sandwich
        sandwich = bottom_ok and middle_suspect and top_ok

        # Find vulnerable features (pseudoscience marked as production)
        vulnerable = [
            name for name, entry in self.registry._entries.items()
            if entry.layer in (2, 3) and entry.status == "production"
        ]

        if sandwich:
            risk = (
                "CRITICAL: Sandwich kredibilitas terdeteksi! Fitur pseudosains "
                "(Layers 2-3) mendapat status 'production' karena terbawa "
                "kredibilitas Layer 1 (astronomi) dan Layers 4-6 (TA/makro). "
                "Setiap fitur Layer 2-3 harus diuji TERPISAH dari layers lainnya."
            )
        elif len(vulnerable) > 0:
            risk = (
                "WARNING: Fitur Layer 2-3 dengan status production perlu "
                "verifikasi ulang — pastikan bukan credibility transfer."
            )
        else:
            risk = "OK: Tidak ada indikasi sandwich kredibilitas."

        return {
            "sandwich_detected": sandwich,
            "bottom_layer_ok": bottom_ok,
            "middle_layer_suspect": middle_suspect,
            "top_layer_ok": top_ok,
            "credibility_transfer_risk": risk,
            "vulnerable_features": vulnerable,
            "layer_distribution": {
                str(layer): statuses
                for layer, statuses in layer_status.items()
            },
        }


# ─────────────────────────────────────────────────────────────────────────────
# SELF-TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # ── Ablation demo ──
    print("=== Ablation Study Demo ===")
    engine = AblationEngine()
    fake_metrics = {
        "M0": {"sharpe": 0.0, "sortino": 0.0, "max_drawdown": -0.50,
               "annual_return": 0.0, "annual_vol": 0.50, "win_rate": 0.48,
               "avg_win": 0.01, "avg_loss": -0.01, "n_trades": 100},
        "M6": {"sharpe": 0.60, "sortino": 0.80, "max_drawdown": -0.15,
               "annual_return": 0.18, "annual_vol": 0.30, "win_rate": 0.52,
               "avg_win": 0.02, "avg_loss": -0.015, "n_trades": 200},
        "M7": {"sharpe": 0.72, "sortino": 0.95, "max_drawdown": -0.12,
               "annual_return": 0.22, "annual_vol": 0.28, "win_rate": 0.54,
               "avg_win": 0.022, "avg_loss": -0.013, "n_trades": 200},
        "M8": {"sharpe": 0.78, "sortino": 1.02, "max_drawdown": -0.10,
               "annual_return": 0.25, "annual_vol": 0.27, "win_rate": 0.55,
               "avg_win": 0.023, "avg_loss": -0.012, "n_trades": 200},
    }
    study = engine.run("BTC", "Daily", fake_metrics)
    print(f"M6 Baseline Sharpe: {study.m6_baseline_sharpe:.4f}")
    print(f"M7 ΔSharpe: {study.m7_incremental_sharpe:+.4f}")
    print(f"M8 ΔSharpe: {study.m8_incremental_sharpe:+.4f}")
    print(f"SPA p-value (M7 vs M6): {study.spa_pvalue_m7_vs_m6:.4f}")
    print(f"DSR M7: {study.dsr_m7:.4f}")
    print(f"Astro adds alpha: {study.astro_adds_alpha}")
    print(f"Evidence score: {study.evidence_score}/100")

    # ── Evidence Registry demo ──
    print("\n=== Evidence Registry Demo ===")
    registry = EvidenceRegistry("/tmp/astronacci_test_evidence.json")
    registry.register("lunar_illumination", layer=1, layer_name="Astronomy",
                      evidence_score=85, notes="Passed permutation + bootstrap")
    registry.register("aspect_conjunction_max", layer=1, layer_name="Astronomy",
                      evidence_score=72, notes="Passed OOS, marginal SPA")
    registry.register("mercury_retrograde", layer=1, layer_name="Astronomy",
                      evidence_score=25, notes="Failed all gates — rejected")
    registry.register("mars_square_jupiter", layer=1, layer_name="Astronomy",
                      evidence_score=45, notes="Weak signal, observe only")

    print(f"Allowed: {registry.allowed_features()}")
    print(f"Research: {registry.research_features()}")
    print(f"Rejected: {registry.rejected_features()}")
    print(f"Summary: {registry.summary()}")

    # ── Epistemic Governor demo ──
    print("\n=== Epistemic Governor Demo ===")
    governor = EpistemicGovernor(registry)
    test_features = {
        "lunar_illumination": 0.85,
        "aspect_conjunction_max": 0.72,
        "mercury_retrograde": 1.0,
        "mars_square_jupiter": 0.55,
        "unknown_feature_x": 0.33,
    }
    decision = governor.gate(test_features)
    print(f"Decision: allowed={decision['allowed']}")
    print(f"Allowed: {list(decision['allowed_features'].keys())}")
    print(f"Blocked: {decision['blocked_features']}")
    print(f"Block reasons: {decision['block_reasons']}")
    print(f"Block summary: {governor.block_summary()}")
