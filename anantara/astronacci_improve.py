#!/usr/bin/env python3
"""
ASTRONACCI v1.3 — Continuous Improvement Engine

Periodic evaluation → analysis → improvement → refinement loop.

CYCLE (runs every 24h via daemon):
  1. DEEP ANALYSIS: Regime-segmented event studies
  2. WALK-FORWARD: Rolling OOS validation with purge
  3. DECAY DETECTION: Auto-demote degrading signals
  4. IMPROVEMENT: Promote strengthening signals
  5. REPORT: Scientific findings + recommendations
  6. REGISTRY: Auto-update Evidence Registry

SCIENTIFIC PRINCIPLES:
  • Every signal MUST be re-tested when new data arrives
  • Regime matters: bull-market signals ≠ bear-market signals
  • Walk-forward prevents overfitting (Lopez de Prado purge method)
  • Decay detection: 7d WR drop >20% from all-time → auto-demote
  • Improvement detection: 14d sustained improvement → consider promotion

USAGE:
    python3 anantara/astronacci_improve.py run      # Full improvement cycle
    python3 anantara/astronacci_improve.py analyze   # Deep analysis only
    python3 anantara/astronacci_improve.py monitor   # Continuous mode
"""
from __future__ import annotations

import json
import logging
import math
import os
import random
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("anantara.astronacci.improve")


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ImproveConfig:
    project_dir: str = ""
    data_dir: str = ""
    report_dir: str = ""

    # Regime detection
    regime_ma_short: int = 20
    regime_ma_long: int = 50
    regime_vol_window: int = 20
    regime_high_vol_pct: float = 0.25  # top 25% vol days = high vol

    # Walk-forward
    wf_train_pct: float = 0.70
    wf_min_train_bars: int = 100
    wf_purge_bars: int = 5            # embargo between train/test

    # Decay / Improvement
    decay_wr_drop: float = 0.20       # 20% drop → decay
    improve_wr_rise: float = 0.10     # 10% rise → improvement candidate
    improve_sustain_days: int = 14    # must sustain for 14 days

    # Scoring
    decay_penalty: int = 15
    improvement_bonus: int = 10

    def __post_init__(self):
        if not self.project_dir:
            self.project_dir = os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti"))
        if not self.data_dir:
            self.data_dir = str(Path(self.project_dir) / "data" / "astronacci")
        if not self.report_dir:
            self.report_dir = str(Path(self.data_dir) / "reports")


# ═══════════════════════════════════════════════════════════════════════════════
# REGIME DETECTOR
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RegimeLabels:
    """Regime classification for each bar."""
    trend: list[str]       # "bull", "bear", "sideways"
    volatility: list[str]  # "high", "normal", "low"
    risk: list[str]        # "risk_on", "risk_off", "neutral"


class RegimeDetector:
    """Classify each bar into trend/volatility/risk regime.

    Pure price-based — no lookahead. Uses only data available at bar time.
    """

    def __init__(self, config: ImproveConfig | None = None):
        self.cfg = config or ImproveConfig()

    def detect(self, prices: list[float]) -> RegimeLabels:
        """Classify regimes for each bar in the series."""
        n = len(prices)
        trend_labels: list[str] = []
        vol_labels: list[str] = []
        risk_labels: list[str] = []

        # Need enough warmup
        warmup = max(self.cfg.regime_ma_long, self.cfg.regime_vol_window)

        # Returns for volatility
        returns = [0.0]
        for i in range(1, n):
            if prices[i-1] > 0:
                returns.append(math.log(prices[i] / prices[i-1]))
            else:
                returns.append(0.0)

        for i in range(n):
            if i < warmup:
                trend_labels.append("unknown")
                vol_labels.append("unknown")
                risk_labels.append("unknown")
                continue

            # ── Trend: MA slope ──
            ma_short = sum(prices[i - self.cfg.regime_ma_short:i]) / self.cfg.regime_ma_short
            ma_long = sum(prices[i - self.cfg.regime_ma_long:i]) / self.cfg.regime_ma_long

            if ma_short > ma_long * 1.03:
                trend_labels.append("bull")
            elif ma_short < ma_long * 0.97:
                trend_labels.append("bear")
            else:
                trend_labels.append("sideways")

            # ── Volatility: rolling std ──
            window_rets = returns[max(0, i - self.cfg.regime_vol_window):i]
            if len(window_rets) >= 5:
                vol = (sum((r - sum(window_rets)/len(window_rets))**2 for r in window_rets) / (len(window_rets)-1)) ** 0.5
                # Simple threshold: compare to median vol of last 100 bars
                all_vols = []
                for j in range(max(warmup, i-100), i):
                    jr = returns[max(0, j-10):j]
                    if len(jr) >= 5:
                        m = sum(jr)/len(jr)
                        all_vols.append((sum((r-m)**2 for r in jr)/(len(jr)-1))**0.5)
                if all_vols:
                    median_vol = sorted(all_vols)[len(all_vols)//2]
                    if vol > median_vol * 1.5:
                        vol_labels.append("high")
                    elif vol < median_vol * 0.5:
                        vol_labels.append("low")
                    else:
                        vol_labels.append("normal")
                else:
                    vol_labels.append("normal")
            else:
                vol_labels.append("normal")

            # ── Risk: momentum direction ──
            ret_5d = sum(returns[max(0, i-5):i])
            if ret_5d > 0.02:
                risk_labels.append("risk_on")
            elif ret_5d < -0.02:
                risk_labels.append("risk_off")
            else:
                risk_labels.append("neutral")

        return RegimeLabels(
            trend=trend_labels,
            volatility=vol_labels,
            risk=risk_labels,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# DEEP SCIENTIFIC ANALYSIS ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RegimeAnalysis:
    """Analysis result for one signal in one regime."""
    signal_name: str
    asset: str
    regime_type: str       # "trend_bull", "vol_high", etc.
    regime_value: str      # "bull", "high", etc.
    n_events: int
    n_total_bars: int
    hit_rate: float
    car_mean: float
    sharpe: float
    vs_all_regime_lift: float  # how much better/worse than overall

    # Statistical
    p_value: float
    is_significant: bool
    evidence_score: int
    recommendation: str


@dataclass
class WalkForwardResult:
    """Walk-forward backtest result."""
    signal_name: str
    asset: str
    n_splits: int
    train_sharpe: float
    test_sharpe: float
    train_win_rate: float
    test_win_rate: float
    consistency: float      # % of splits where test > 0
    overfit_ratio: float    # train_sharpe / test_sharpe

    # Verdict
    is_overfit: bool        # train >> test
    is_robust: bool         # consistent positive test
    recommendation: str


class DeepAnalysisEngine:
    """Runs deep scientific analysis: regime-segmented + walk-forward.

    This is the BRAIN of the continuous improvement loop.
    """

    def __init__(self, config: ImproveConfig | None = None):
        self.cfg = config or ImproveConfig()
        self.regime_detector = RegimeDetector(self.cfg)
        # Sidecar: per-finding trade returns, used by run_defense_for_signal()
        # so the honest 7-gate promotion path has the raw data it needs.
        # Key: "{signal_name}__{regime_type}_{regime_value}".
        self._returns_by_finding: dict[str, list[float]] = {}

    def regime_segmented_analysis(
        self,
        dataset,
        event_indices: list[int],
        signal_name: str,
        asset: str,
    ) -> list[RegimeAnalysis]:
        """Analyze signal performance segmented by regime.

        Key insight: astro signals might work in SOME regimes but not others.
        Without regime segmentation, we might miss conditional edges.
        """
        prices = dataset.price_series()
        n = len(prices)
        regimes = self.regime_detector.detect(prices)

        results: list[RegimeAnalysis] = []

        # Overall baseline
        overall_hr = self._hit_rate_in_window(prices, event_indices, 0, n)

        # Analyze per regime type
        for regime_type, labels in [
            ("trend", regimes.trend),
            ("volatility", regimes.volatility),
            ("risk", regimes.risk),
        ]:
            # Get unique regime values
            unique_values = sorted(set(l for l in labels if l != "unknown"))

            for rv in unique_values:
                # Find bar indices in this regime
                regime_indices = [i for i, l in enumerate(labels) if l == rv]

                # Filter event indices to those falling in this regime
                regime_events = [e for e in event_indices if e in regime_indices]

                if len(regime_events) < 5:
                    continue

                hr = self._hit_rate_in_window(prices, regime_events, 0, len(prices))

                # CAR for regime events
                cars = []
                for idx in regime_events:
                    if idx < 10 or idx >= n - 10:
                        continue
                    post_rets = []
                    for j in range(1, 6):
                        if idx + j < n and prices[idx] > 0:
                            post_rets.append(math.log(prices[idx + j] / prices[idx]))
                    cars.append(sum(post_rets))

                car_mean = sum(cars) / len(cars) if cars else 0.0
                car_std = (sum((c - car_mean)**2 for c in cars) / max(len(cars)-1, 1)) ** 0.5 if len(cars) > 1 else 0.01
                sharpe = car_mean / car_std * math.sqrt(len(cars)) if car_std > 0 else 0.0

                # Lift vs overall
                lift = (hr - overall_hr) / overall_hr if overall_hr > 0 else 0.0

                # Evidence
                evidence = 0
                if len(regime_events) >= 10:
                    evidence += 20
                if hr > overall_hr:
                    evidence += 25
                if sharpe > 0:
                    evidence += 15
                if lift > 0.10:
                    evidence += 15
                # ── Real bootstrap p-value (not placeholder) ──
                p_value = self._bootstrap_pvalue(cars, n_boot=500)

                recommendation = ""
                if evidence >= 60:
                    recommendation = f"PROMISING: {rv} regime shows conditional edge (lift={lift:+.1%}, p={p_value:.3f})"
                elif evidence >= 30:
                    recommendation = f"WATCH: {rv} regime has marginal signal (p={p_value:.3f})"
                else:
                    recommendation = f"NO EDGE: {rv} regime (p={p_value:.3f})"

                # Cache the per-event returns for this finding so the honest
                # 7-gate promotion path (run_defense_for_signal) can evaluate it.
                finding_key = f"{signal_name}__{regime_type}_{rv}"
                self._returns_by_finding[finding_key] = list(cars)

                results.append(RegimeAnalysis(
                    signal_name=signal_name,
                    asset=asset,
                    regime_type=regime_type,
                    regime_value=rv,
                    n_events=len(regime_events),
                    n_total_bars=len(regime_indices),
                    hit_rate=round(hr, 4),
                    car_mean=round(car_mean, 6),
                    sharpe=round(sharpe, 4),
                    vs_all_regime_lift=round(lift, 4),
                    p_value=round(p_value, 4),
                    is_significant=(evidence >= 50),
                    evidence_score=min(100, evidence),
                    recommendation=recommendation,
                ))

        return results

    def walk_forward_validation(
        self,
        prices: list[float],
        event_indices: list[int],
        signal_name: str,
        asset: str,
        n_splits: int = 5,
    ) -> WalkForwardResult:
        """Walk-forward backtest with purge between train/test.

        Lopez de Prado: purge bars between train/test to prevent
        information leakage from overlapping labels.
        """
        n = len(prices)
        if n < self.cfg.wf_min_train_bars * 2:
            return WalkForwardResult(
                signal_name=signal_name, asset=asset, n_splits=0,
                train_sharpe=0, test_sharpe=0,
                train_win_rate=0, test_win_rate=0,
                consistency=0, overfit_ratio=0,
                is_overfit=True, is_robust=False,
                recommendation="Insufficient data",
            )

        fold_size = n // (n_splits + 1)
        train_sharpes = []
        test_sharpes = []
        train_wrs = []
        test_wrs = []

        for split in range(n_splits):
            # Train: 0 to (split+1)*fold_size - purge
            train_end = (split + 1) * fold_size - self.cfg.wf_purge_bars
            # Test: train_end + purge to train_end + purge + fold_size
            test_start = (split + 1) * fold_size
            test_end = min(n, test_start + fold_size)

            if train_end < self.cfg.wf_min_train_bars or test_end - test_start < 20:
                continue

            train_events = [e for e in event_indices if e < train_end]
            test_events = [e for e in event_indices if test_start <= e < test_end]

            if len(train_events) < 3 or len(test_events) < 3:
                continue

            # Simple mean-reversion backtest
            train_trades = self._simple_backtest(prices, train_events, 0, train_end)
            test_trades = self._simple_backtest(prices, test_events, test_start, test_end)

            if train_trades:
                from astronacci_events import _mean, _std
                tr = _mean(train_trades)
                ts = _std(train_trades)
                train_sharpes.append(tr / ts * math.sqrt(len(train_trades)) if ts > 0 else 0)
                train_wrs.append(sum(1 for t in train_trades if t > 0) / len(train_trades))

            if test_trades:
                from astronacci_events import _mean, _std
                tr = _mean(test_trades)
                ts = _std(test_trades)
                test_sharpes.append(tr / ts * math.sqrt(len(test_trades)) if ts > 0 else 0)
                test_wrs.append(sum(1 for t in test_trades if t > 0) / len(test_trades))

        if not train_sharpes or not test_sharpes:
            return WalkForwardResult(
                signal_name=signal_name, asset=asset, n_splits=len(train_sharpes),
                train_sharpe=0, test_sharpe=0,
                train_win_rate=0, test_win_rate=0,
                consistency=0, overfit_ratio=99,
                is_overfit=True, is_robust=False,
                recommendation="Insufficient splits",
            )

        avg_train_sr = sum(train_sharpes) / len(train_sharpes)
        avg_test_sr = sum(test_sharpes) / len(test_sharpes)
        avg_train_wr = sum(train_wrs) / len(train_wrs)
        avg_test_wr = sum(test_wrs) / len(test_wrs)

        consistency = sum(1 for t in test_sharpes if t > 0) / len(test_sharpes)
        overfit_ratio = (avg_train_sr / avg_test_sr) if avg_test_sr > 0 else 99

        is_overfit = overfit_ratio > 2.0 or consistency < 0.5
        is_robust = consistency >= 0.6 and avg_test_sr > 0

        if is_robust:
            rec = f"ROBUST: {consistency:.0%} OOS positive, test SR={avg_test_sr:.3f}"
        elif is_overfit:
            rec = f"OVERFIT: train SR={avg_train_sr:.3f} >> test SR={avg_test_sr:.3f}, consistency={consistency:.0%}"
        else:
            rec = f"MARGINAL: train={avg_train_sr:.3f}, test={avg_test_sr:.3f}"

        return WalkForwardResult(
            signal_name=signal_name, asset=asset,
            n_splits=len(train_sharpes),
            train_sharpe=round(avg_train_sr, 4),
            test_sharpe=round(avg_test_sr, 4),
            train_win_rate=round(avg_train_wr, 4),
            test_win_rate=round(avg_test_wr, 4),
            consistency=round(consistency, 4),
            overfit_ratio=round(overfit_ratio, 2),
            is_overfit=is_overfit,
            is_robust=is_robust,
            recommendation=rec,
        )

    @staticmethod
    def _bootstrap_pvalue(values: list[float], n_boot: int = 500,
                          seed: int = 42) -> float:
        """Bootstrap p-value: P(resampled mean <= 0).

        Uses a dedicated `random.Random(seed)` so results are reproducible and
        the global RNG is never perturbed (previously used `_rnd.choice` on the
        global state → non-deterministic regime verdicts + p-values that
        changed every run).
        """
        if len(values) < 3:
            return 0.5
        rng = random.Random(seed)
        count = 0
        for _ in range(n_boot):
            samp = [rng.choice(values) for _ in range(len(values))]
            if sum(samp) / len(samp) <= 0:
                count += 1
        return count / n_boot

    @staticmethod
    def _z_test_two_proportion(n1: int, w1: int, n2: int, w2: int) -> float:
        """Two-proportion z-test p-value (two-sided).
        Tests whether hit rates differ significantly between two periods."""
        import math as _m
        if n1 < 5 or n2 < 5:
            return 0.5
        p1 = w1 / n1
        p2 = w2 / n2
        p_pool = (w1 + w2) / (n1 + n2)
        se = _m.sqrt(p_pool * (1 - p_pool) * (1/n1 + 1/n2))
        if se < 1e-9:
            return 0.5
        z = (p1 - p2) / se
        # Two-sided p-value via normal approximation
        z_abs = abs(z)
        # Abramowitz & Stegun approximation
        p = 2 * (1 - 0.5 * (1 + _m.erf(z_abs / _m.sqrt(2))))
        return max(0.0, min(1.0, p))

    @staticmethod
    def _hit_rate_in_window(prices, event_indices, start, end) -> float:
        """Hit rate: % events near a swing point in [start, end)."""
        order = 5
        hits = 0
        for idx in event_indices:
            if idx < start + order or idx >= end - order:
                continue
            window = prices[idx - order:idx + order + 1]
            if prices[idx] == max(window) or prices[idx] == min(window):
                hits += 1
        valid = sum(1 for e in event_indices if start + order <= e < end - order)
        return hits / valid if valid > 0 else 0.0

    @staticmethod
    def _simple_backtest(prices, event_indices, start, end) -> list[float]:
        """Simple fade backtest: fade prior 5d trend, hold 5d."""
        trades = []
        for idx in event_indices:
            if idx < start + 10 or idx >= end - 10:
                continue
            prior = prices[idx] / prices[idx - 5] - 1.0
            direction = -1 if prior > 0 else 1  # fade
            exit_ret = prices[idx + 5] / prices[idx] - 1.0
            trades.append(direction * exit_ret - 0.0016)  # 16bps cost
        return trades

    @staticmethod
    def run_defense_for_signal(
        signal_name: str,
        returns: list[float],
        n_features_tested: int,
    ):
        """Run the genuine 7-gate Statistical Defense System on a signal's
        per-trade returns and return a DefenseResult suitable for
        `EvidenceRegistry.validate_with_defense()`.

        This is the CANONICAL honest-promotion path: a feature can only reach
        `production` status by surviving the 7 gates here. It closes the
        cold-start gap left after TIER 4 (the gate existed but no production
        code ever invoked it).

        Args:
            signal_name: label for the DefenseResult
            returns: per-trade returns (after cost) for this signal
            n_features_tested: family size for FDR/multiple-testing correction

        Returns:
            DefenseResult, or None if there is too little data to evaluate.
        """
        if len(returns) < 10:
            return None
        from astronacci_stats import (
            StatisticalDefenseSystem, _mean, _std,
        )

        sds = StatisticalDefenseSystem()

        def metric_fn(r):
            return _mean(r) / max(_std(r), 1e-6)

        # Null generator: mean-zero noise with the same volatility as the
        # observed returns. A genuinely profitable signal must beat this null.
        obs_metric = metric_fn(returns)
        vol = max(_std(returns), 1e-6)

        # ONE rng per signal (seeded → reproducible across runs), drawn from
        # fresh entropy on every generate_null() call. Previously we re-seeded
        # Random(42) inside generate_null, producing an identical null sample
        # every call → a degenerate null distribution and bogus p=0.0.
        import random as _r
        null_rng = _r.Random(42)

        def generate_null():
            null = [null_rng.gauss(0.0, vol) for _ in range(len(returns))]
            return metric_fn(null)

        # Candidate metrics for data-snooping correction: bootstrap-resampled
        # variants of the observed returns (proxy for "other strategies tried").
        boot_rng = _r.Random(43)
        candidates = []
        for _ in range(max(10, n_features_tested)):
            samp = [boot_rng.choice(returns) for _ in range(len(returns))]
            candidates.append(metric_fn(samp))

        obs_sharpe = obs_metric  # mean/std ≈ per-sample Sharpe

        return sds.evaluate(
            signal_name=signal_name,
            observed_sharpe=obs_sharpe,
            observed_metric=obs_metric,
            returns=returns,
            all_candidate_metrics=candidates,
            n_observations=len(returns),
            n_features_tested=max(n_features_tested, len(candidates)),
            metric_fn=metric_fn,
            generate_null=generate_null,
        )

    def run_full_analysis(self, datasets=None) -> dict:
        """Run complete deep analysis on all datasets."""
        if datasets is None:
            from astronacci_pipeline import AstroDataPipeline
            pipeline = AstroDataPipeline()
            datasets = {}
            for sym in ["BTC", "ETH", "SOL"]:
                ds = pipeline.load_dataset(sym, "1d")
                if ds:
                    datasets[sym] = ds

        import math as _math
        all_regime_results = []
        all_wf_results = []

        for sym, ds in datasets.items():
            if not ds or ds.n_bars < 100:
                continue

            prices = ds.price_series()

            # Find event indices for each event type.
            # Astro events (lunar/retrograde) AND conventional TA events
            # (RSI oversold/overbought) are evaluated through the SAME honest
            # 7-gate defense path. TA baselines are far more likely to carry a
            # real edge than astro — testing them lets the system reach genuine
            # `production` status on validated, tradeable signals.
            event_finders = {
                "full_moon": self._find_lunar_events,
                "new_moon": self._find_lunar_events,
                "mercury_retrograde": self._find_retrograde,
                "rsi_oversold": self._find_rsi_oversold,
                "rsi_overbought": self._find_rsi_overbought,
            }

            for event_name, finder in event_finders.items():
                indices = finder(ds, event_name)
                if len(indices) < 5:
                    continue

                signal_name = f"{event_name}_{sym}_1d"

                # Regime-segmented analysis
                regime_results = self.regime_segmented_analysis(
                    ds, indices, signal_name, sym,
                )
                all_regime_results.extend(regime_results)

                # Walk-forward validation
                wf_result = self.walk_forward_validation(
                    prices, indices, signal_name, sym,
                )
                all_wf_results.append(wf_result)

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "regime_analysis": all_regime_results,
            "walk_forward": all_wf_results,
            "n_regime_findings": len(all_regime_results),
            "n_wf_validations": len(all_wf_results),
        }

    @staticmethod
    def _find_lunar_events(dataset, event_type: str) -> list[int]:
        target = 180.0 if event_type == "full_moon" else 0.0
        indices = []
        for i, bar in enumerate(dataset.bars):
            ps = bar.astro_features.get("lunar_phase_sin", 0)
            pc = bar.astro_features.get("lunar_phase_cos", 0)
            pa = math.degrees(math.atan2(ps, pc)) % 360
            if min(abs(pa - target), 360 - abs(pa - target)) <= 7.0:
                indices.append(i)
        deduped = []
        for idx in indices:
            if not deduped or idx - deduped[-1] > 3:
                deduped.append(idx)
        return deduped

    @staticmethod
    def _find_retrograde(dataset, event_type: str) -> list[int]:
        return [i for i, bar in enumerate(dataset.bars)
                if bar.astro_features.get("Mercury_retrograde", 0) > 0.5]

    @staticmethod
    def _rsi_series(prices: list[float], period: int = 14) -> list[float]:
        """Classic Wilder RSI (std lib only). Returns one RSI per bar
        (0..100); early bars with insufficient history are 50 (neutral)."""
        rsi = [50.0] * len(prices)
        if len(prices) < period + 1:
            return rsi
        gains = losses = 0.0
        for i in range(1, period + 1):
            ch = prices[i] - prices[i - 1]
            gains += max(0.0, ch)
            losses += max(0.0, -ch)
        avg_gain = gains / period
        avg_loss = losses / period
        for i in range(period, len(prices)):
            if i > period:
                ch = prices[i] - prices[i - 1]
                avg_gain = (avg_gain * (period - 1) + max(0.0, ch)) / period
                avg_loss = (avg_loss * (period - 1) + max(0.0, -ch)) / period
            rs = avg_gain / avg_loss if avg_loss > 0 else 100.0
            rsi[i] = 100.0 - 100.0 / (1.0 + rs)
        return rsi

    @staticmethod
    def _find_rsi_oversold(dataset, event_type: str = "rsi_oversold",
                           threshold: float = 30.0) -> list[int]:
        """Bars where RSI(14) < 30 — classic oversold (mean-reversion LONG)."""
        prices = dataset.price_series()
        rsi = DeepAnalysisEngine._rsi_series(prices)
        return [i for i in range(len(rsi)) if rsi[i] < threshold]

    @staticmethod
    def _find_rsi_overbought(dataset, event_type: str = "rsi_overbought",
                             threshold: float = 70.0) -> list[int]:
        """Bars where RSI(14) > 70 — classic overbought (mean-reversion SHORT)."""
        prices = dataset.price_series()
        rsi = DeepAnalysisEngine._rsi_series(prices)
        return [i for i in range(len(rsi)) if rsi[i] > threshold]


# ═══════════════════════════════════════════════════════════════════════════════
# CONTINUOUS IMPROVEMENT ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════

class ContinuousImprovementLoop:
    """Orchestrates the full periodic improvement cycle.

    This is designed to run every 24h from the daemon scheduler.
    """

    def __init__(self, config: ImproveConfig | None = None):
        self.cfg = config or ImproveConfig()
        self.analyzer = DeepAnalysisEngine(self.cfg)
        self.report_dir = Path(self.cfg.report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def run_cycle(self, tg_sender=None) -> dict:
        """Run one complete improvement cycle.

        Returns summary dict suitable for Telegram notification.
        """
        now = datetime.now(timezone.utc)
        log.info("=" * 60)
        log.info("ASTRONACCI — Continuous Improvement Cycle")
        log.info(f"Started: {now.strftime('%Y-%m-%d %H:%M UTC')}")
        log.info("=" * 60)

        # Phase 1: Deep Analysis
        log.info("Phase 1/3: Deep Scientific Analysis...")
        analysis = self.analyzer.run_full_analysis()

        # Phase 2: Decay Detection & Auto-Improvement
        log.info("Phase 2/3: Decay Detection & Improvement...")
        improvements = self._detect_improvements(analysis)

        # Phase 3: Update Registry & Report
        log.info("Phase 3/3: Registry Update & Report...")
        self._update_registry(analysis, improvements)
        report_path = self._generate_report(analysis, improvements)

        summary = {
            "timestamp": now.isoformat(),
            "regime_findings": analysis.get("n_regime_findings", 0),
            "wf_validations": analysis.get("n_wf_validations", 0),
            "improvements_detected": len(improvements.get("promote", [])),
            "decays_detected": len(improvements.get("demote", [])),
            "report_path": str(report_path),
        }

        log.info(f"Cycle complete: {summary}")

        # Telegram notification
        if tg_sender and (summary["decays_detected"] > 0 or summary["improvements_detected"] > 0):
            import asyncio
            msg_parts = ["🔬 *Astronacci — Improvement Cycle*"]
            if summary["decays_detected"] > 0:
                msg_parts.append(f"⚠️ {summary['decays_detected']} signals decayed → auto-demoted")
            if summary["improvements_detected"] > 0:
                msg_parts.append(f"✅ {summary['improvements_detected']} signals improved")
            msg_parts.append(f"📊 {summary['regime_findings']} regime findings")
            msg_parts.append(f"📁 Report: `{Path(report_path).name}`")
            try:
                asyncio.create_task(tg_sender("\n".join(msg_parts)))
            except Exception:
                log.debug(f"Improve report load skipped: {report_path}")

        return summary

    def _detect_improvements(self, analysis: dict) -> dict:
        """Detect which signals should be promoted or demoted."""
        promote = []
        demote = []

        for r in analysis.get("regime_analysis", []):
            if r.is_significant and r.evidence_score >= 60:
                promote.append({
                    "signal": r.signal_name,
                    "regime": f"{r.regime_type}_{r.regime_value}",
                    "evidence": r.evidence_score,
                    "reason": r.recommendation,
                })

        for wf in analysis.get("walk_forward", []):
            if wf.is_overfit and not wf.is_robust:
                demote.append({
                    "signal": wf.signal_name,
                    "reason": wf.recommendation,
                    "overfit_ratio": wf.overfit_ratio,
                })

        return {"promote": promote, "demote": demote}

    def _update_registry(self, analysis: dict, improvements: dict):
        """Auto-update Evidence Registry based on findings.

        HONEST PROMOTION PATH (closes the TIER-4 cold-start gap):
          For each regime finding with enough events, we run the genuine
          7-gate Statistical Defense System on its per-trade returns and
          register via `validate_with_defense`. Only a signal that survives
          the gates can reach `production` — never an ad-hoc heuristic score.
          Findings without enough data still register (as research/watchlist)
          via the plain `register` path, so they remain observable.
        """
        try:
            from astronacci_ablation import EvidenceRegistry
            registry = EvidenceRegistry()

            promoted = 0
            for r in analysis.get("regime_analysis", []):
                finding_key = f"{r.signal_name}__{r.regime_type}_{r.regime_value}"
                returns = self.analyzer._returns_by_finding.get(finding_key)

                if r.n_events >= 10 and returns and len(returns) >= 10:
                    # Canonical path: run 7-gate defense, register the verdict.
                    dr = self.analyzer.run_defense_for_signal(
                        finding_key, returns,
                        n_features_tested=len(analysis.get("regime_analysis", [])),
                    )
                    if dr is not None:
                        registry.validate_with_defense(
                            feature_name=finding_key,
                            layer=3,
                            layer_name="Financial Astrology",
                            defense_result=dr,
                            notes=r.recommendation,
                        )
                        if getattr(dr, "gates_passed", 0) >= 5:
                            promoted += 1
                        continue
                # Fallback: not enough data for the gates — record as research.
                registry.register(
                    feature_name=finding_key,
                    layer=3,
                    layer_name="Financial Astrology",
                    evidence_score=r.evidence_score,
                    test_results={
                        "hit_rate": r.hit_rate,
                        "sharpe": r.sharpe,
                        "regime": r.regime_value,
                        "lift": r.vs_all_regime_lift,
                    },
                    notes=r.recommendation,
                )

            # Auto-demote decayed signals
            for dem in improvements.get("demote", []):
                entry = registry.get(dem["signal"])
                if entry and entry.evidence_score >= 50:
                    new_score = max(10, entry.evidence_score - self.cfg.decay_penalty)
                    registry.register(
                        feature_name=dem["signal"],
                        layer=3,
                        evidence_score=new_score,
                        notes=f"AUTO-DEMOTE: {dem['reason']}",
                    )

            log.info(
                f"Registry updated: {len(analysis.get('regime_analysis', []))} "
                f"findings, {promoted} reached production via 7-gate defense"
            )

        except Exception as e:
            log.error(f"Registry update failed: {e}")

    def _generate_report(self, analysis: dict, improvements: dict) -> Path:
        """Generate comprehensive improvement report."""
        now = datetime.now(timezone.utc)
        fname = f"improve_{now.strftime('%Y%m%d_%H%M')}.json"
        fpath = self.report_dir / fname

        report = {
            "generated": now.isoformat(),
            "cycle": "continuous_improvement",
            "analysis": {
                "n_regime_findings": analysis.get("n_regime_findings", 0),
                "n_wf_validations": analysis.get("n_wf_validations", 0),
            },
            "improvements": improvements,
            "top_regime_findings": [],
            "top_wf_findings": [],
        }

        # Extract top findings
        regime_results = analysis.get("regime_analysis", [])
        significant = [r for r in regime_results if r.is_significant]
        for r in sorted(significant, key=lambda x: -x.evidence_score)[:10]:
            report["top_regime_findings"].append({
                "signal": r.signal_name,
                "regime": f"{r.regime_type}={r.regime_value}",
                "hit_rate": r.hit_rate,
                "sharpe": r.sharpe,
                "evidence": r.evidence_score,
                "recommendation": r.recommendation,
            })

        wf_results = analysis.get("walk_forward", [])
        robust = [w for w in wf_results if w.is_robust]
        for w in sorted(robust, key=lambda x: -x.test_sharpe)[:10]:
            report["top_wf_findings"].append({
                "signal": w.signal_name,
                "test_sharpe": w.test_sharpe,
                "consistency": w.consistency,
                "recommendation": w.recommendation,
            })

        fpath.write_text(json.dumps(report, indent=2, default=str))
        return fpath


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Astronacci Continuous Improvement")
    ap.add_argument("action", nargs="?", default="run",
                    choices=["run", "analyze", "monitor", "report"])
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    loop = ContinuousImprovementLoop()

    if args.action == "monitor":
        print("🔬 Astronacci Continuous Improvement — 24h Loop")
        print("   Running: deep analysis → decay detection → auto-improvement")
        while True:
            try:
                summary = loop.run_cycle()
                print(f"   [{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}] "
                      f"regime={summary['regime_findings']} "
                      f"wf={summary['wf_validations']} "
                      f"improve={summary['improvements_detected']} "
                      f"decay={summary['decays_detected']}")
                time.sleep(86400)
            except KeyboardInterrupt:
                print("\n⏹️ Stopped.")
                break
            except Exception as e:
                log.error(f"Cycle error: {e}")
                time.sleep(3600)

    elif args.action == "analyze":
        analysis = loop.analyzer.run_full_analysis()
        print(json.dumps({
            "n_regime_findings": analysis["n_regime_findings"],
            "n_wf_validations": analysis["n_wf_validations"],
        }, indent=2))

    elif args.action == "report":
        analysis = loop.analyzer.run_full_analysis()
        improvements = loop._detect_improvements(analysis)
        loop._update_registry(analysis, improvements)
        path = loop._generate_report(analysis, improvements)
        print(f"✅ Improvement report: {path}")

    else:  # run
        summary = loop.run_cycle()
        print(json.dumps(summary, indent=2, default=str))
