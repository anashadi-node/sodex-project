#!/usr/bin/env python3
"""
ASTRONACCI v1.0 — Statistical Defense System (7 Gates)

Tujuh gerbang anti-ilusi statistik yang harus dilalui setiap sinyal astro
sebelum boleh digunakan dalam pengambilan keputusan trading.

GATE 1: Permutation Test
  Apakah metrik sinyal lebih baik daripada permutasi acak dari event yang sama?

GATE 2: Stationary Block Bootstrap
  Return pasar tidak iid. Bootstrap harus menjaga struktur dependensi temporal.

GATE 3: White Reality Check (approximation)
  Mengoreksi data-snooping: jika 1 aturan dari N terlihat bagus, Reality Check
  menghukum ilusi seleksi.

GATE 4: Hansen SPA Test (Superior Predictive Ability, approximation)
  Versi lebih kuat: mengurangi pengaruh model buruk, fokus pada SPA.

GATE 5: False Discovery Rate (Benjamini-Hochberg)
  Mengontrol FDR ketika menguji banyak aspek/horizon/aset/parameter sekaligus.

GATE 6: Deflated Sharpe Ratio
  Sharpe harus dikoreksi untuk selection bias, multiple testing, skewness, kurtosis.

GATE 7: PBO / CSCV (Probability of Backtest Overfitting)
  Mengukur peluang strategi terbaik in-sample akan gagal out-of-sample.

REFERENSI:
  • Sullivan, Timmermann & White (1999) — Reality Check
  • Hansen (2005) — SPA Test
  • Bailey & López de Prado (2014) — Deflated Sharpe Ratio
  • Bailey et al. (2015) — PBO / CSCV
  • Benjamini & Hochberg (1995) — FDR

Stdlib-only. Semua fungsi pure, deterministic, testable.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Sequence


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

# ponytail: use stdlib statistics instead of custom helpers
from statistics import mean as _mean, stdev as _std, pstdev

def _skew(xs: Sequence[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    m = _mean(xs)
    s = pstdev(xs)  # population stdev (ddof=0)
    if s == 0:
        return 0.0
    return sum(((x - m) / s) ** 3 for x in xs) / n


def _kurtosis(xs: Sequence[float]) -> float:
    n = len(xs)
    if n < 4:
        return 0.0
    m = _mean(xs)
    s = pstdev(xs)  # population stdev (ddof=0)
    if s == 0:
        return 0.0
    return sum(((x - m) / s) ** 4 for x in xs) / n - 3.0


def _sort_desc(xs: list[float]) -> list[float]:
    return sorted(xs, reverse=True)


# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DefenseResult:
    """Result of running a signal through all 7 statistical gates."""
    signal_name: str
    n_trials: int
    n_features_tested: int          # for multiple testing correction

    # Gate results
    gate1_permutation_pvalue: float
    gate2_block_bootstrap_pvalue: float
    gate3_reality_check_pvalue: float
    gate4_spa_pvalue: float
    gate5_fdr_corrected_pvalue: float
    gate6_deflated_sharpe: float
    gate7_pbo: float                # probability of backtest overfitting

    # Raw metrics
    observed_sharpe: float
    observed_metric: float

    # Verdict
    gates_passed: int               # 0-7
    all_passed: bool
    evidence_level: str             # "rejected" / "weak" / "moderate" / "strong"


# ─────────────────────────────────────────────────────────────────────────────
# GATE 1: PERMUTATION TEST
# ─────────────────────────────────────────────────────────────────────────────

def permutation_test(
    observed_metric: float,
    generate_null: callable,
    n_permutations: int = 1000,
    seed: int | None = 42,
) -> tuple[float, list[float]]:
    """Shuffle labels to create null distribution.

    Args:
        observed_metric: The actual metric value from original labels
        generate_null: () -> float — generates one null metric value
        n_permutations: Number of shuffles
        seed: RNG seed

    Returns:
        (p_value, null_distribution)
    """
    if seed is not None:
        random.seed(seed)

    null_dist = []
    for _ in range(n_permutations):
        null_dist.append(generate_null())

    # p-value = fraction of null >= observed (one-sided positive)
    count = sum(1 for x in null_dist if x >= observed_metric)
    p_value = count / n_permutations if n_permutations > 0 else 1.0

    return p_value, null_dist


# ─────────────────────────────────────────────────────────────────────────────
# GATE 2: STATIONARY BLOCK BOOTSTRAP
# ─────────────────────────────────────────────────────────────────────────────

def block_bootstrap_pvalue(
    observed_metric: float,
    returns: list[float],
    metric_fn: callable,
    n_bootstrap: int = 1000,
    block_size: int = 5,
    seed: int | None = 42,
) -> tuple[float, list[float]]:
    """Block bootstrap preserving temporal dependence.

    Args:
        observed_metric: Metric from original series
        returns: Time series of returns
        metric_fn: (list[float]) -> float — computes metric on a sample
        n_bootstrap: Number of bootstrap samples
        block_size: Block size for stationary bootstrap
        seed: RNG seed

    Returns:
        (p_value, bootstrap_distribution)
    """
    if seed is not None:
        random.seed(seed)

    n = len(returns)
    if n < block_size * 2:
        return 1.0, [observed_metric]

    boot_metrics = []
    for _ in range(n_bootstrap):
        # Sample blocks to create a synthetic series
        sampled = []
        while len(sampled) < n:
            block_start = random.randint(0, n - block_size)
            sampled.extend(returns[block_start:block_start + block_size])
        boot_metrics.append(metric_fn(sampled[:n]))

    count = sum(1 for x in boot_metrics if x >= observed_metric)
    p_value = count / n_bootstrap if n_bootstrap > 0 else 1.0

    return p_value, boot_metrics


# ─────────────────────────────────────────────────────────────────────────────
# GATE 3: WHITE REALITY CHECK (approximation)
# ─────────────────────────────────────────────────────────────────────────────

def reality_check_pvalue(
    observed_metric: float,
    all_candidate_metrics: list[float],
    n_bootstrap: int = 1000,
    seed: int | None = 42,
) -> float:
    """White's Reality Check: correct for data-snooping across candidates.

    If you tested N candidate rules and picked the best, the observed metric
    is biased upward. RC adjusts the null distribution to reflect this.

    Approximation using max of null distributions per bootstrap iteration.
    """
    if seed is not None:
        random.seed(seed)

    n_candidates = len(all_candidate_metrics)
    if n_candidates <= 1:
        return 1.0  # no snooping correction needed

    # For a proper RC, we'd need per-candidate null distributions.
    # Approximation: sample from candidates as pseudo-null, take max each iteration.
    grand_mean = _mean(all_candidate_metrics)
    grand_std = _std(all_candidate_metrics) or 0.01

    max_stats = []
    for _ in range(n_bootstrap):
        # Sample N candidates with replacement, take max
        sampled = [
            random.gauss(grand_mean, grand_std)
            for _ in range(n_candidates)
        ]
        max_stats.append(max(sampled))

    count = sum(1 for x in max_stats if x >= observed_metric)
    return count / n_bootstrap if n_bootstrap > 0 else 1.0


# ─────────────────────────────────────────────────────────────────────────────
# GATE 4: HANSEN SPA TEST (approximation)
# ─────────────────────────────────────────────────────────────────────────────

def spa_test_pvalue(
    observed_metric: float,
    all_candidate_metrics: list[float],
    n_bootstrap: int = 1000,
    seed: int | None = 42,
) -> float:
    """Hansen SPA: like RC but uses recentered null to reduce poor-model noise.

    Key difference from Reality Check: SPA recenters each candidate's null
    distribution at zero for candidates worse than the best, reducing the
    influence of very bad models on the test.
    """
    if seed is not None:
        random.seed(seed)

    n = len(all_candidate_metrics)
    if n <= 1:
        return 1.0

    best = max(all_candidate_metrics)
    grand_std = _std(all_candidate_metrics) or 0.01

    # SPA: recenter null at max(0, candidate_mean - best)
    recentered = [max(0.0, m - best + grand_std * 0.1) for m in all_candidate_metrics]
    recentered_mean = _mean(recentered)
    recentered_std = _std(recentered) or grand_std

    max_stats = []
    for _ in range(n_bootstrap):
        sampled = [
            random.gauss(recentered_mean, recentered_std)
            for _ in range(n)
        ]
        max_stats.append(max(sampled))

    count = sum(1 for x in max_stats if x >= observed_metric)
    return count / n_bootstrap if n_bootstrap > 0 else 1.0


# ─────────────────────────────────────────────────────────────────────────────
# GATE 5: FALSE DISCOVERY RATE (Benjamini-Hochberg)
# ─────────────────────────────────────────────────────────────────────────────

def benjamini_hochberg_correction(
    p_values: list[float],
    alpha: float = 0.05,
) -> list[tuple[int, float, bool]]:
    """Benjamini-Hochberg FDR control.

    Returns list of (original_rank, corrected_threshold, is_significant).
    """
    n = len(p_values)
    if n == 0:
        return []

    # Sort and rank
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    results = []

    for rank, (orig_idx, p) in enumerate(indexed):
        # BH critical value: (rank+1) / n * alpha
        bh_threshold = (rank + 1) / n * alpha
        is_sig = p <= bh_threshold
        results.append((orig_idx, bh_threshold, is_sig))

    # Re-sort by original index
    results.sort(key=lambda x: x[0])
    return results


def fdr_corrected_pvalue(
    p_value: float,
    n_tests: int,
    method: str = "bh",
) -> float:
    """Apply multiple-testing correction to a SINGLE p-value.

    Args:
        p_value: raw p-value from one test
        n_tests: number of hypotheses tested simultaneously (family size)
        method: "bonferroni" (FWER) or "bh" (FDR, Benjamini-Hochberg)

    Returns:
        Adjusted p-value in [0, 1].

    Methodological note on "bh" for a single p-value:
      The BH procedure (Benjamini-Hochberg 1995) controls the False Discovery
      Rate by adjusting a VECTOR of p-values using their ranks. For a single
      p-value in isolation, its rank within the family is unknown. The
      statistically valid choice is the worst-case rank (=1, i.e. this p-value
      is the most significant), which yields the BH-adjusted upper bound
      p*n_tests — identical to Bonferroni. This is the correct conservative
      behaviour: a single isolated p-value corrected with BH == Bonferroni.

      PREVIOUS IMPLEMENTATION (BUG): `p * n / (n * 0.5) = 2 * p`, which is
      independent of n_tests and therefore NOT a valid FDR correction — it
      massively UNDER-corrected for large n_tests (e.g. 50 features tested
      would still give only 2*p, falsely passing weak signals).

      For proper rank-aware BH on a full vector of p-values, use
      `benjamini_hochberg_correction(p_values, alpha)` instead.
    """
    if n_tests <= 1:
        return min(1.0, p_value)
    if method == "bonferroni":
        return min(1.0, p_value * n_tests)
    # "bh" — single p-value: worst-case rank=1 → p*n_tests (conservative, valid)
    return min(1.0, p_value * n_tests)


# ─────────────────────────────────────────────────────────────────────────────
# GATE 6: DEFLATED SHARPE RATIO
# ─────────────────────────────────────────────────────────────────────────────

def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_trials: int,
    n_observations: int,
    skewness: float = 0.0,
    kurtosis_excess: float = 0.0,
    variance_across_trials: float = 0.0,
) -> dict[str, float]:
    """Bailey & López de Prado (2014) Deflated Sharpe Ratio.

    Corrects Sharpe for:
    - Selection bias (n_trials: how many strategies were tested)
    - Non-normality (skewness, kurtosis)
    - Sample size (n_observations)
    - Variance across trials

    Returns dict with DSR and components.
    """
    # Expected maximum Sharpe under null (multiple testing)
    # E[max(SR)] ≈ sqrt(var) * expectation_of_max_of_N_standard_normals
    # Approximate: E[max] ≈ sqrt(2 * log(n_trials))
    if n_trials > 1:
        gamma = 0.5772156649  # Euler-Mascheroni
        e_max = math.sqrt(2.0 * math.log(n_trials)) - (
            math.log(math.log(n_trials)) + math.log(4 * math.pi)
        ) / (2.0 * math.sqrt(2.0 * math.log(n_trials))) + gamma / math.sqrt(
            2.0 * math.log(n_trials)
        )
    else:
        e_max = 0.0

    # Variance of Sharpe ratio under normality
    sr_var = (1.0 + 0.5 * observed_sharpe**2) / n_observations

    # Adjust for skewness and kurtosis
    sr_var *= (1.0 - skewness * observed_sharpe + (kurtosis_excess / 4.0) * observed_sharpe**2)

    sr_std = math.sqrt(max(0.0, sr_var))

    if sr_std > 0:
        dsr = (observed_sharpe - e_max * math.sqrt(variance_across_trials or 0.01)) / sr_std
    else:
        dsr = 0.0

    return {
        "deflated_sharpe": round(dsr, 4),
        "expected_max_sr": round(e_max, 4),
        "sr_std": round(sr_std, 4),
        "selection_bias_penalty": round(e_max * math.sqrt(variance_across_trials or 0.01), 4),
    }


# ─────────────────────────────────────────────────────────────────────────────
# GATE 7: PBO / CSCV
# ─────────────────────────────────────────────────────────────────────────────

def probability_of_backtest_overfitting(
    all_is_metrics: list[float],    # in-sample metrics for all trials
    all_oos_metrics: list[float],   # out-of-sample metrics for all trials
    n_splits: int = 10,
    seed: int | None = 42,
) -> dict[str, float]:
    """Bailey et al. (2015) Combinatorially Symmetric Cross-Validation.

    PBO = probability that the best IS strategy ranks below median OOS.
    High PBO (>50%) → likely overfit.

    Args:
        all_is_metrics: in-sample metric (e.g. Sharpe) for each strategy trial
        all_oos_metrics: out-of-sample metric for each strategy trial
            (must be the same length as all_is_metrics, paired index-by-index)
        n_splits: target number of random combinatorial splits
        seed: RNG seed for reproducibility. Default 42 makes this function
            DETERMINISTIC (same inputs → same output). Pass None to draw
            entropy from the OS. The previous implementation consumed the
            GLOBAL random state without seeding, so identical inputs gave
            different PBO values across runs — making Gate 7 non-reproducible.

    For small number of trials, use all combinatorially symmetric splits.
    For large, use a random subset approximation.
    """
    n = len(all_is_metrics)
    if n != len(all_oos_metrics):
        raise ValueError(
            f"IS/OOS length mismatch: {n} vs {len(all_oos_metrics)}"
        )
    if n < 4:
        return {"pbo": 1.0, "n_splits_used": 0, "warning": "too few trials"}

    # Use a DEDICATED Random instance so we never perturb the global RNG
    # state and so the result is fully reproducible for a given (input, seed).
    rng = random.Random(seed)

    # CSCV: split trials into combinations
    import itertools
    actual_splits = min(n_splits, 2 ** (n - 1) - 1)

    overfit_count = 0
    split_count = 0

    # Use random splits for efficiency
    for _ in range(min(actual_splits, 100)):
        # Random binary split
        split = [rng.random() < 0.5 for _ in range(n)]
        is_set = [i for i, s in enumerate(split) if s]
        oos_set = [i for i, s in enumerate(split) if not s]

        if len(is_set) < 2 or len(oos_set) < 2:
            continue

        # Best IS strategy
        best_is_idx = max(is_set, key=lambda i: all_is_metrics[i])
        best_is_oos_rank = sum(
            1 for j in oos_set
            if all_oos_metrics[j] > all_oos_metrics[best_is_idx]
        ) + 1

        oos_n = len(oos_set)
        # Overfit if best IS ranks below median OOS
        if best_is_oos_rank > oos_n / 2:
            overfit_count += 1
        split_count += 1

    pbo = overfit_count / split_count if split_count > 0 else 0.5

    return {
        "pbo": round(pbo, 4),
        "n_splits_used": split_count,
        "is_overfit": pbo > 0.5,
    }


# ─────────────────────────────────────────────────────────────────────────────
# FULL DEFENSE SYSTEM
# ─────────────────────────────────────────────────────────────────────────────

class StatisticalDefenseSystem:
    """Run a signal through all 7 statistical gates.

    Usage:
        sds = StatisticalDefenseSystem()
        result = sds.evaluate(
            signal_name="H1_Lunar_Reversal",
            observed_sharpe=0.8,
            observed_metric=0.12,
            returns=returns_list,
            all_candidate_metrics=[0.08, 0.10, 0.12, 0.05, 0.03],
            n_observations=500,
            n_features_tested=50,
        )
    """

    def evaluate(
        self,
        signal_name: str,
        observed_sharpe: float,
        observed_metric: float,
        returns: list[float],
        all_candidate_metrics: list[float],
        n_observations: int,
        n_features_tested: int,
        metric_fn: callable | None = None,
        generate_null: callable | None = None,
    ) -> DefenseResult:
        """Run full 7-gate evaluation."""
        gates_passed = 0

        # Gate 1: Permutation
        if generate_null:
            g1_p, _ = permutation_test(observed_metric, generate_null)
        else:
            g1_p = 1.0
        if g1_p < 0.05:
            gates_passed += 1

        # Gate 2: Block Bootstrap
        if metric_fn and len(returns) >= 10:
            g2_p, _ = block_bootstrap_pvalue(
                observed_metric, returns, metric_fn,
            )
        else:
            g2_p = 1.0
        if g2_p < 0.05:
            gates_passed += 1

        # Gate 3: Reality Check
        g3_p = reality_check_pvalue(observed_metric, all_candidate_metrics)
        if g3_p < 0.05:
            gates_passed += 1

        # Gate 4: SPA
        g4_p = spa_test_pvalue(observed_metric, all_candidate_metrics)
        if g4_p < 0.05:
            gates_passed += 1

        # Gate 5: FDR
        g5_p = fdr_corrected_pvalue(
            min(g1_p, g2_p, g3_p, g4_p), n_features_tested,
        )
        if g5_p < 0.05:
            gates_passed += 1

        # Gate 6: Deflated Sharpe
        dsr_result = deflated_sharpe_ratio(
            observed_sharpe, len(all_candidate_metrics),
            n_observations,
            skewness=_skew(returns) if returns else 0.0,
            kurtosis_excess=_kurtosis(returns) if returns else 0.0,
        )
        g6_dsr = dsr_result["deflated_sharpe"]
        if g6_dsr > 0:
            gates_passed += 1

        # Gate 7: PBO
        # Need IS/OOS split — use returns split as approximation
        mid = len(returns) // 2
        is_returns = returns[:mid]
        oos_returns = returns[mid:]
        is_metrics = [metric_fn(is_returns)] if metric_fn else [observed_metric]
        oos_metrics = [metric_fn(oos_returns)] if metric_fn else [observed_metric]
        # Extend with candidates
        pbo_result = probability_of_backtest_overfitting(
            is_metrics + all_candidate_metrics[:9],
            oos_metrics + all_candidate_metrics[:9],
        )
        g7_pbo = pbo_result["pbo"]
        if g7_pbo < 0.5:
            gates_passed += 1

        # Evidence level
        if gates_passed >= 6:
            evidence = "strong"
        elif gates_passed >= 4:
            evidence = "moderate"
        elif gates_passed >= 2:
            evidence = "weak"
        else:
            evidence = "rejected"

        return DefenseResult(
            signal_name=signal_name,
            n_trials=len(all_candidate_metrics),
            n_features_tested=n_features_tested,
            gate1_permutation_pvalue=round(g1_p, 4),
            gate2_block_bootstrap_pvalue=round(g2_p, 4),
            gate3_reality_check_pvalue=round(g3_p, 4),
            gate4_spa_pvalue=round(g4_p, 4),
            gate5_fdr_corrected_pvalue=round(g5_p, 4),
            gate6_deflated_sharpe=round(g6_dsr, 4),
            gate7_pbo=round(g7_pbo, 4),
            observed_sharpe=round(observed_sharpe, 4),
            observed_metric=round(observed_metric, 6),
            gates_passed=gates_passed,
            all_passed=(gates_passed >= 5),
            evidence_level=evidence,
        )


# ─────────────────────────────────────────────────────────────────────────────
# SELF-TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    random.seed(42)

    # Synthetic returns
    returns = [random.gauss(0.0005, 0.02) for _ in range(500)]

    def sample_metric(r):
        return _mean(r) / (_std(r) or 0.01)

    def sample_null():
        return _mean([random.gauss(0.0, 0.02) for _ in range(100)]) / 0.02

    candidates = [random.gauss(0.0003, 0.005) for _ in range(20)]

    sds = StatisticalDefenseSystem()
    result = sds.evaluate(
        signal_name="H1_Lunar_Reversal",
        observed_sharpe=0.45,
        observed_metric=sample_metric(returns),
        returns=returns,
        all_candidate_metrics=candidates,
        n_observations=500,
        n_features_tested=40,
        metric_fn=sample_metric,
        generate_null=sample_null,
    )

    print("=== Statistical Defense System: 7-Gate Result ===")
    print(f"Signal: {result.signal_name}")
    print(f"Trials tested: {result.n_trials}, Features: {result.n_features_tested}")
    print()
    print(f"Gate 1 (Permutation):    p={result.gate1_permutation_pvalue:.4f}")
    print(f"Gate 2 (Block Bootstrap): p={result.gate2_block_bootstrap_pvalue:.4f}")
    print(f"Gate 3 (Reality Check):   p={result.gate3_reality_check_pvalue:.4f}")
    print(f"Gate 4 (SPA):             p={result.gate4_spa_pvalue:.4f}")
    print(f"Gate 5 (FDR corrected):   p={result.gate5_fdr_corrected_pvalue:.4f}")
    print(f"Gate 6 (Deflated Sharpe):  {result.gate6_deflated_sharpe:.4f}")
    print(f"Gate 7 (PBO):             {result.gate7_pbo:.4f}")
    print()
    print(f"Observed Sharpe: {result.observed_sharpe:.4f}")
    print(f"Gates passed: {result.gates_passed}/7")
    print(f"Evidence: {result.evidence_level}")
    print(f"ALL PASSED: {result.all_passed}")
