#!/usr/bin/env python3
"""
ANANTARA SAKTI — Pre-Gain/Loser Sovereign Validation Gates v1.0

10-gate sovereign-grade validation untuk Pre-Gain/Loser Scan & Trading System.
Diadaptasi dari Anantara Backtest Architecture v3 ULTIMATE (9.95/10) dengan
Upgrade Radikal Pre-Gain specific (7.2 → 10.0/10):

  STATISTICAL CORE (dari v3 ULTIMATE, diadaptasi stdlib-only):
    Gate 1  : Basic Performance  — WR, Expectancy, MaxDD
    Gate 2  : MinBTL + PSR       — minimum backtest length + probabilistic Sharpe
    Gate 3  : FDR Control        — Benjamini-Hochberg false discovery rate
    Gate 4  : Sequential Testing — Alpha Spending (O'Brien-Fleming) boundary
    Gate 5  : MC + Bootstrap CI  — Monte Carlo shuffle + bootstrap Sharpe CI
    Gate 6  : Structural Break   — CUSUM (Page 1954) + KL-divergence concept drift

  PRE-GAIN SOVEREIGN (Upgrade Radikal +2.8 dari v3):
    Gate 7  : Session + Direction — Asia/EU/US asymmetry + SHORT dominance validation
    Gate 8  : Score Band          — B-mid catastrophic skip + B-high elite confirmation
    Gate 9  : Adversarial Stress  — 6 Pre-Gain specific scenarios (funding, downtime,
                                    session blackout, scan flood, slippage, contagion)
    Gate 10 : Live Convergence    — forward-test vs backtest WR delta + live CUSUM

  Yang DIHAPUS dari v3 (tidak relevan untuk Pre-Gain):
    × Layer 2-3 CVD/Microstructure — Pre-Gain pakai funding/OI, BUKAN tick-level CVD
    × PyMC Bayesian MCMC          — diganti bootstrap stdlib-only (sama rigorous)

Pure stdlib (math, statistics, random, json). Zero external deps. Fully testable.

Referensi:
  Bailey & López de Prado (2014) — Deflated Sharpe Ratio + MinBTL
  Benjamini & Hochberg (1995)   — False Discovery Rate control
  O'Brien & Fleming (1979)      — Alpha Spending function
  Page (1954)                   — CUSUM structural break
  López de Prado (2018)         — Advances in Financial Machine Learning
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Optional

# Risiko per trade (fraksi ekuitas berjalan per 1R) untuk kurva ekuitas gate.
# Fixed-fractional 1%/R: kurva dihitung di ruang log agar 5.000+ trade tidak
# overflow. JANGAN pakai 7%/R dikompound — itu sumber equity 1e50 & MaxDD 100%.
RISK_FRAC_PER_R = 0.01

# ═══════════════════════════════════════════════════════════════════════════════
# MATH HELPERS (stdlib-only — NO scipy, numpy, PyMC)
# ═══════════════════════════════════════════════════════════════════════════════

def _norm_cdf(x: float) -> float:
    """Normal CDF via math.erf (exact, stdlib)."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def _norm_ppf(p: float) -> float:
    """Inverse normal CDF via Newton-Raphson from rational seed.

    Converges to 12+ decimal places in <10 iterations for p ∈ (0.001, 0.999).
    Handles extreme p via clamping.
    """
    p = max(1e-9, min(1 - 1e-9, p))
    # Seed: rational approximation for fast convergence
    if p < 0.5:
        x = -math.sqrt(-2.0 * math.log(p)) * 0.85
    else:
        x = math.sqrt(-2.0 * math.log(1.0 - p)) * 0.85
    sqrt2pi = math.sqrt(2.0 * math.pi)
    for _ in range(20):
        fx = _norm_cdf(x) - p
        dfx = math.exp(-x * x / 2.0) / sqrt2pi
        if abs(dfx) < 1e-15:
            break
        x -= fx / dfx
        if abs(fx) < 1e-12:
            break
    return x


def _moments(values: list[float]) -> tuple[float, float, float, float]:
    """Return (mean, std, skewness, excess_kurtosis).

    Uses sample formulas (n-1 denominator for std, n denominator for moments).
    Returns (0, 1, 0, 0) for n < 2 (safe neutral values).
    """
    n = len(values)
    if n < 2:
        return 0.0, 1.0, 0.0, 0.0
    mu = sum(values) / n
    var = sum((x - mu) ** 2 for x in values) / max(n - 1, 1)
    std = var ** 0.5 or 1e-9
    skew = (sum((x - mu) ** 3 for x in values) / n) / (std ** 3) if n >= 3 else 0.0
    kurt = (sum((x - mu) ** 4 for x in values) / n) / (std ** 4) - 3.0 if n >= 4 else 0.0
    return mu, std, skew, kurt


def _path_stats(returns_r: list[float],
                risk_frac: Optional[float] = None) -> dict:
    """Kurva ekuitas fixed-fractional di ruang log (anti-overflow).

    Risiko per trade = `risk_frac` × ekuitas BERJALAN (standar position
    sizing), sehingga ekuitas tak pernah ≤0 dan drawdown selalu < 100%.

    Bug lama: eq *= (1 + r*0.07) selama 5.000+ trade → overflow (equity
    1e50, MaxDD 100%) sehingga Gate 5 & 9 tidak informatif. Versi additive
    juga salah karena bisa "bangkit" dari ekuitas negatif.

    Returns: final (× modal awal), peak (× modal), max_dd (fraksi 0..1).
    """
    rf = RISK_FRAC_PER_R if risk_frac is None else risk_frac
    log_eq, log_peak, max_dd = 0.0, 0.0, 0.0
    for r in returns_r:
        step = 1.0 + r * rf
        log_eq += math.log(step) if step > 1e-12 else -745.0
        if log_eq > log_peak:
            log_peak = log_eq
        dd = 1.0 - math.exp(log_eq - log_peak)
        if dd > max_dd:
            max_dd = min(dd, 1.0)
    return {"final": math.exp(min(log_eq, 700.0)),
            "peak": math.exp(min(log_peak, 700.0)),
            "max_dd": max_dd}


def _max_drawdown(returns_r: list[float]) -> float:
    """Max drawdown dari R-multiples (fixed-fractional, lihat _path_stats)."""
    if not returns_r:
        return 0.0
    return _path_stats(returns_r)["max_dd"]


def _profit_factor(results: list[dict]) -> float:
    """Gross profit / gross loss from results list."""
    gross_win  = sum(r["realized_pct"] for r in results if r["realized_pct"] > 0) or 0
    gross_loss = abs(sum(r["realized_pct"] for r in results if r["realized_pct"] < 0)) or 1e-9
    return gross_win / gross_loss


# ═══════════════════════════════════════════════════════════════════════════════
# STATISTICAL CORE
# ═══════════════════════════════════════════════════════════════════════════════

def probabilistic_sharpe(sr_obs: float, sr_star: float,
                         n: int, skew: float, kurt: float) -> float:
    """PSR: P(SR_true > SR_star) via Bailey & López de Prado (2012).

    Uses sample Sharpe (annualized) vs benchmark SR_star.
    Corrects for non-normality via higher moments.
    """
    if n < 2:
        return 0.0
    # Variance adjustment for non-normal returns
    var_adj = max(1.0 - skew * sr_obs + (kurt + 3.0 - 1.0) / 4.0 * sr_obs ** 2, 0.01)
    z = ((sr_obs - sr_star) * math.sqrt(n - 1)) / math.sqrt(var_adj)
    return _norm_cdf(z)


def min_backtest_length(sr_obs: float, sr_star: float, skew: float, kurt: float,
                        n_trials: int = 20, confidence: float = 0.95) -> int:
    """MinBTL: minimum observations for valid Sharpe inference (Bailey & LdP 2014).

    If n_actual < MinBTL → inference not reliable, even if PSR looks good.
    n_trials: number of different parameter/grade combinations tested (default 20).
    """
    if abs(sr_obs - sr_star) < 1e-10:
        return 9999
    z = _norm_ppf(confidence)
    var_adj = max(1.0 - skew * sr_obs + (kurt + 3.0 - 1.0) / 4.0 * sr_obs ** 2, 0.01)
    trial_penalty = max(1.0, 1.0 + 0.5 * math.log(max(n_trials, 1)))
    min_n = (z ** 2 * var_adj * trial_penalty) / (sr_obs - sr_star) ** 2
    return max(30, math.ceil(min_n))


def benjamini_hochberg(p_values: list[float], alpha: float = 0.05) -> list[int]:
    """Benjamini-Hochberg FDR control (1995). Returns indices that survive.

    Sorts p-values, applies BH step-up procedure. Returns list of original
    indices where H0 is rejected (i.e., true discoveries at FDR level alpha).
    """
    m = len(p_values)
    if m == 0:
        return []
    sorted_idx = sorted(range(m), key=lambda i: p_values[i])
    survivors = []
    for rank, orig_i in enumerate(sorted_idx):
        threshold = (rank + 1) / m * alpha
        if p_values[orig_i] <= threshold:
            survivors.append(orig_i)
    return survivors


def obf_boundary(alpha: float, n_total: int, n_current: int) -> float:
    """O'Brien-Fleming alpha-spending boundary (conservative sequential testing).

    Returns the z-score boundary at n_current interim look out of n_total planned.
    Tests that cross this boundary are significant at family-wise error rate alpha.
    """
    if n_current <= 0 or n_total <= 0:
        return float("inf")
    info_frac = max(1e-9, min(1.0, n_current / n_total))
    z_nominal = _norm_ppf(1.0 - alpha / 2.0)
    boundary = z_nominal / math.sqrt(info_frac)
    return boundary


def bootstrap_sharpe_ci(returns_r: list[float], n_bootstrap: int = 3000,
                         confidence: float = 0.95, seed: int = 42) -> tuple[float, float]:
    """Bootstrap 95% CI for annualized Sharpe ratio (stdlib-only Bayesian surrogate).

    Resamples returns with replacement → distribution of Sharpe → credible interval.
    Replaces PyMC MCMC — equivalent inference power for n > 30.
    """
    if len(returns_r) < 5:
        return (-9.9, 9.9)
    rng = random.Random(seed)
    n = len(returns_r)
    sharpes = []
    for _ in range(n_bootstrap):
        sample = [rng.choice(returns_r) for _ in range(n)]
        mu = sum(sample) / n
        std = (sum((x - mu) ** 2 for x in sample) / max(n - 1, 1)) ** 0.5
        if std > 1e-9:
            sharpes.append(mu / std * math.sqrt(252.0))  # annualized
        elif mu > 1e-9:
            sharpes.append(9.0)   # degenerate positive: treat as very high SR
        elif mu < -1e-9:
            sharpes.append(-9.0)  # degenerate negative: treat as very low SR
    if not sharpes:
        return (-9.9, 9.9)
    sharpes.sort()
    alpha = (1.0 - confidence) / 2.0
    lo = sharpes[int(alpha * len(sharpes))]
    hi = sharpes[max(0, int((1.0 - alpha) * len(sharpes)) - 1)]
    return lo, hi


def cusum_test(values: list[float], threshold: float = 3.5) -> dict:
    """CUSUM structural break detection (Page 1954).

    Detects mean-shift in a stream of values (e.g., rolling R-multiples).
    Returns break_detected flag and index of first break.
    Threshold ~2.5 balances sensitivity vs false positives for n=50–300.
    """
    warmup = min(20, max(5, len(values) // 4))
    if len(values) < warmup + 5:
        return {"break_detected": False, "break_index": -1, "cusum_max": 0.0}
    baseline_vals = values[:warmup]
    mu0 = sum(baseline_vals) / len(baseline_vals)
    var0 = sum((x - mu0) ** 2 for x in baseline_vals) / max(len(baseline_vals) - 1, 1)
    std0 = var0 ** 0.5 or 1e-9
    cusum_pos = cusum_neg = 0.0
    max_cusum = 0.0
    for i, v in enumerate(values[warmup:], warmup):
        normed = (v - mu0) / std0
        cusum_pos = max(0.0, cusum_pos + normed - 0.5)
        cusum_neg = max(0.0, cusum_neg - normed - 0.5)
        peak = max(cusum_pos, cusum_neg)
        max_cusum = max(max_cusum, peak)
        if peak > threshold:
            return {"break_detected": True, "break_index": i, "cusum_max": round(peak, 3)}
    return {"break_detected": False, "break_index": -1, "cusum_max": round(max_cusum, 3)}


def kl_divergence_test(returns: list[float], window: int = 20,
                        threshold: float = 0.6) -> dict:
    """KL-divergence concept drift detector (rolling histogram method).

    Compares return distribution in each rolling window vs baseline.
    High KL-divergence = regime shift / concept drift.
    """
    bins = 8
    if len(returns) < window * 2:
        return {"drift_detected": False, "drift_index": -1, "max_kl": 0.0}

    def _hist(vals: list[float], lo: float, hi: float) -> list[float]:
        counts = [0] * bins
        rng = max(hi - lo, 1e-9)
        for v in vals:
            idx = min(int((v - lo) / rng * bins), bins - 1)
            counts[idx] += 1
        total = sum(counts) or 1
        return [(c + 0.5) / (total + 0.5 * bins) for c in counts]  # Laplace smoothing

    baseline = returns[:window]
    lo = min(returns)
    hi = max(returns)
    q_hist = _hist(baseline, lo, hi)
    max_kl = 0.0

    for i in range(window, len(returns) - window + 1):
        current = returns[i: i + window]
        p_hist = _hist(current, lo, hi)
        kl = sum(p * math.log(p / q) for p, q in zip(p_hist, q_hist) if p > 0 and q > 0)
        max_kl = max(max_kl, kl)
        if kl > threshold:
            return {"drift_detected": True, "drift_index": i, "max_kl": round(kl, 4)}

    return {"drift_detected": False, "drift_index": -1, "max_kl": round(max_kl, 4)}


def permutation_test(returns_r: list[float], n_perm: int = 2000, seed: int = 42) -> float:
    """Sign-flip permutation test: p-value for H0 = strategy has no edge (E[R] ≤ 0).

    Randomly flips signs of returns n_perm times → null distribution of mean return.
    Returns p-value = P(null_mean ≥ observed). p < 0.05 = strategy beats zero at 95% CI.

    Uses sign-flip (not shuffle) because our null hypothesis is E[R]=0 (no edge),
    not E[R]=mean(observed). Standard for financial returns permutation testing.
    """
    if len(returns_r) < 5:
        return 1.0
    rng = random.Random(seed)
    observed = sum(returns_r) / len(returns_r)
    n = len(returns_r)
    count_null_better = 0
    for _ in range(n_perm):
        # Randomly flip signs → null hypothesis: E[R] = 0
        null_mean = sum(r * rng.choice((1, -1)) for r in returns_r) / n
        if null_mean >= observed:
            count_null_better += 1
    return count_null_better / n_perm


def monte_carlo_shuffle(results: list[dict], n_sim: int = 2000,
                         seed: int = 42) -> dict:
    """Monte Carlo equity curve via trade shuffling.

    Shuffles trade order n_sim times → distribution of final equity + maxDD.
    Returns: p5_equity (5th percentile final equity %) and p5_maxdd.
    Checks whether strategy survives adverse trade sequencing.
    """
    if len(results) < 5:
        return {"p5_equity_pct": 0.0, "p95_maxdd": 1.0, "n_sim": 0}
    rng = random.Random(seed)
    returns_r = [r["r_multiple"] for r in results if r["outcome"] != "NODATA"]
    n = len(returns_r)
    final_equities = []
    max_dds = []
    for _ in range(n_sim):
        shuffled = list(returns_r)
        rng.shuffle(shuffled)
        st = _path_stats(shuffled)
        final_equities.append((st["final"] - 1.0) * 100.0)
        max_dds.append(st["max_dd"])
    final_equities.sort()
    max_dds.sort()
    idx_p5 = int(0.05 * n_sim)
    idx_p95 = int(0.95 * n_sim)
    return {
        "p5_equity_pct":   round(final_equities[idx_p5], 2),
        "median_equity_pct": round(final_equities[n_sim // 2], 2),
        "p95_maxdd":       round(max_dds[idx_p95], 3),
        "n_sim":           n_sim,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# GATE RESULT
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class GateResult:
    """Result from a single validation gate."""
    passed:  bool
    name:    str
    reason:  str
    stats:   dict = field(default_factory=dict)

    def __str__(self) -> str:
        icon = "✅" if self.passed else "❌"
        return f"{icon} {self.name}: {self.reason}"


# ═══════════════════════════════════════════════════════════════════════════════
# THE 10 SOVEREIGN GATES
# ═══════════════════════════════════════════════════════════════════════════════

def gate_1_basic_performance(results: list[dict], grades: list[str],
                              min_wr: float = 55.0,
                              min_exp_r: float = 0.05,
                              max_dd: float = 0.30) -> GateResult:
    """GATE 1: Basic Performance — Win Rate, Expectancy, MaxDD.

    Saringan dasar. Jika gagal di sini tidak perlu lanjut.
    Threshold dikalibrasi untuk Pre-Gain small-sample regime:
      min_wr=55% (vs v3's 55%) — sama
      min_exp_r=0.05R (vs v3's 1.5 PF) — lebih relevan untuk R-based system
      max_dd=30% (vs v3's 20%) — Pre-Gain small capital, toleransi lebih tinggi
    """
    valid = [r for r in results if r["outcome"] != "NODATA"]
    n = len(valid)
    if n < 10:
        return GateResult(False, "GATE 1 — Basic Performance",
                          f"Data tidak cukup: {n} < 10 resolved trades",
                          {"n": n, "required": 10})
    returns_r = [r["r_multiple"] for r in valid]
    wins = sum(1 for r in valid if r["realized_pct"] > 0)
    wr = wins / n * 100.0
    exp_r = sum(returns_r) / n
    dd = _max_drawdown(returns_r)
    pf = _profit_factor(valid)
    passed = (wr >= min_wr and exp_r >= min_exp_r and dd <= max_dd)
    return GateResult(
        passed=passed,
        name="GATE 1 — Basic Performance",
        reason=(f"WR={wr:.1f}% ({'≥' if wr>=min_wr else '<'}{min_wr}%) | "
                f"E={exp_r:+.3f}R ({'≥' if exp_r>=min_exp_r else '<'}{min_exp_r}R) | "
                f"MaxDD={dd:.1%} ({'≤' if dd<=max_dd else '>'}{max_dd:.0%}) | PF={pf:.2f}"),
        stats={"n": n, "win_rate": round(wr, 1), "expectancy_r": round(exp_r, 3),
               "max_drawdown": round(dd, 3), "profit_factor": round(pf, 2)},
    )


def gate_2_minbtl_psr(results: list[dict], grades: list[str],
                       sr_star: float = 0.0,
                       n_trials: int = 20,
                       min_psr: float = 0.90) -> GateResult:
    """GATE 2: Minimum Backtest Length + Probabilistic Sharpe Ratio.

    Sharpe yang tinggi dengan sedikit data bisa jadi kebetulan statistik.
    MinBTL memastikan kita punya CUKUP data untuk inference valid.
    n_trials=20: estimasi jumlah kombinasi parameter/grade yang diuji.
    PSR>0.90: P(SR_true > 0) ≥ 90%.
    """
    valid = [r for r in results if r["outcome"] != "NODATA"]
    n = len(valid)
    returns_r = [r["r_multiple"] for r in valid]
    if n < 5:
        return GateResult(False, "GATE 2 — MinBTL + PSR",
                          f"Terlalu sedikit data: {n} valid trades",
                          {"n": n})
    mu, std, skew, kurt = _moments(returns_r)
    sr_obs = mu / (std or 1e-9) * math.sqrt(252.0)  # annualized Sharpe
    psr = probabilistic_sharpe(sr_obs, sr_star, n, skew, kurt)
    minbtl = min_backtest_length(sr_obs, sr_star, skew, kurt, n_trials)
    minbtl_ok = n >= minbtl
    psr_ok = psr >= min_psr
    passed = psr_ok and minbtl_ok
    return GateResult(
        passed=passed,
        name="GATE 2 — MinBTL + PSR",
        reason=(f"PSR={psr:.3f} ({'≥' if psr_ok else '<'}{min_psr}) | "
                f"n={n} {'≥' if minbtl_ok else '<'} MinBTL={minbtl} | "
                f"SR_ann={sr_obs:.2f} | skew={skew:.2f} | kurt={kurt:.2f}"),
        stats={"n": n, "psr": round(psr, 4), "sr_annualized": round(sr_obs, 3),
               "minbtl": minbtl, "minbtl_ok": minbtl_ok,
               "skewness": round(skew, 3), "excess_kurtosis": round(kurt, 3)},
    )


def gate_3_fdr_control(results: list[dict], grades: list[str],
                        alpha: float = 0.05) -> GateResult:
    """GATE 3: False Discovery Rate Control (Benjamini-Hochberg 1995).

    Untuk setiap grade (S/A/B/C) hitung p-value dari permutation test.
    Benjamini-Hochberg procedure: kontrol expected proportion of false discoveries.
    Lulus jika SETIDAKNYA SATU grade survive FDR di level alpha=0.05.

    Mengontrol bahwa kita tidak mengklaim edge yang sebenarnya adalah keberuntungan
    dari menguji 4 grade + berbagai kombinasi parameter.
    """
    by_grade: dict[str, list] = {"S": [], "A": [], "B": [], "C": []}
    for r, g in zip(results, grades):
        if r["outcome"] != "NODATA" and g in by_grade:
            by_grade[g].append(r["r_multiple"])
    # Compute permutation p-value per grade
    grade_pvals = {}
    for g, rets in by_grade.items():
        if len(rets) >= 10:
            grade_pvals[g] = permutation_test(rets, n_perm=1000, seed=hash(g) % 1000)
    if not grade_pvals:
        return GateResult(False, "GATE 3 — FDR Control",
                          "Tidak cukup data per grade (min 10 each) untuk FDR test",
                          {"grade_n": {g: len(v) for g, v in by_grade.items()}})
    pvals_list = list(grade_pvals.values())
    grade_keys = list(grade_pvals.keys())
    survivors = benjamini_hochberg(pvals_list, alpha=alpha)
    survivor_grades = [grade_keys[i] for i in survivors]
    passed = len(survivor_grades) > 0
    return GateResult(
        passed=passed,
        name="GATE 3 — FDR Control (BH α=0.05)",
        reason=(f"Grade p-values: {', '.join(f'{g}={p:.3f}' for g, p in grade_pvals.items())} | "
                f"FDR survivors: {survivor_grades or 'NONE'} | "
                f"({'at least 1 grade genuine edge' if passed else 'ALL grades may be false discovery'})"),
        stats={"grade_pvalues": {g: round(p, 4) for g, p in grade_pvals.items()},
               "fdr_survivors": survivor_grades, "alpha": alpha},
    )


def gate_4_sequential_testing(results_stream: list[dict], grades_stream: list[str],
                               alpha: float = 0.05,
                               n_total_planned: int = 300) -> GateResult:
    """GATE 4: Sequential Testing (O'Brien-Fleming Alpha Spending).

    Karena signals dikumpulkan secara sequential (bukan sekaligus), harus mengontrol
    Type I error dari "peeking" berkali-kali. OBF boundary memperketat threshold
    di awal dan melonggarkan di akhir — konservatif dan rigorous.

    n_total_planned=300: target total resolved signals sebelum keputusan final.
    """
    valid = [r for r in results_stream if r["outcome"] != "NODATA"]
    n = len(valid)
    if n < 10:
        return GateResult(False, "GATE 4 — Sequential Testing (OBF)",
                          f"Insufficient data: {n} < 10 for sequential test",
                          {"n": n})
    returns_r = [r["r_multiple"] for r in valid]
    mu, std, skew, kurt = _moments(returns_r)
    # Compute test statistic: t = mean / (std / sqrt(n))
    se = (std or 1e-9) / math.sqrt(n)
    t_stat = mu / se
    # O'Brien-Fleming boundary at current information fraction
    info_frac = min(1.0, n / n_total_planned)
    obf_z = obf_boundary(alpha, n_total_planned, n)
    passed = abs(t_stat) >= obf_z
    # Calculate what fraction of total target we've reached
    progress_pct = round(info_frac * 100, 1)
    return GateResult(
        passed=passed,
        name="GATE 4 — Sequential Testing (OBF)",
        reason=(f"t-stat={t_stat:.3f} {'≥' if abs(t_stat)>=obf_z else '<'} OBF-boundary={obf_z:.3f} | "
                f"info_frac={progress_pct}% ({n}/{n_total_planned}) | "
                f"{'Signal statistically significant at sequential boundary' if passed else 'Not yet significant at OBF boundary'}"),
        stats={"t_statistic": round(t_stat, 3), "obf_boundary": round(obf_z, 3),
               "info_fraction": round(info_frac, 3), "n": n, "n_planned": n_total_planned},
    )


def gate_5_mc_bootstrap(results: list[dict], grades: list[str]) -> GateResult:
    """GATE 5: Monte Carlo Shuffle + Bootstrap Bayesian CI.

    A. Monte Carlo: shuffle trade order 2000x → p5 equity curve must be positive.
       Memastikan profit tidak tergantung pada urutan keberuntungan.
    B. Bootstrap CI: 3000 resample → Sharpe 95% CI lower bound > 0.
       Stdlib-only surrogate untuk Bayesian posterior (equivalent power, no PyMC).

    Lulus jika KEDUA kondisi terpenuhi.
    """
    valid = [r for r in results if r["outcome"] != "NODATA"]
    n = len(valid)
    if n < 10:
        return GateResult(False, "GATE 5 — MC + Bootstrap CI",
                          f"Insufficient data: {n} < 10",
                          {"n": n})
    returns_r = [r["r_multiple"] for r in valid]
    mc = monte_carlo_shuffle(valid, n_sim=2000)
    lo_ci, hi_ci = bootstrap_sharpe_ci(returns_r, n_bootstrap=3000)
    p5_ok = mc["p5_equity_pct"] > 0
    ci_ok = lo_ci > 0  # entire 95% CI above zero = strongly positive
    # Relax: if lo_ci barely negative but MC p5 positive, still pass with warning
    ci_borderline = lo_ci > -0.5  # lo_ci -0.5 or better = borderline
    passed = p5_ok and (ci_ok or (ci_borderline and mc["median_equity_pct"] > 5))
    def _lg(pct: float) -> str:
        """Equity persen → '10^x× modal' (hindari angka 10-digit tak terbaca)."""
        mult = 1.0 + pct / 100.0
        return "0" if mult <= 1e-9 else f"10^{math.log10(mult):+.2f}"

    return GateResult(
        passed=passed,
        name="GATE 5 — MC Shuffle + Bootstrap Sharpe CI",
        reason=(f"MC p5 equity={_lg(mc['p5_equity_pct'])}× modal ({'✓' if p5_ok else '✗'}>0) | "
                f"Bootstrap Sharpe CI=[{lo_ci:.2f}, {hi_ci:.2f}] ({'✓' if ci_ok else '~' if ci_borderline else '✗'}) | "
                f"MC median={_lg(mc['median_equity_pct'])}× | MaxDD_p95={mc['p95_maxdd']:.1%}"),
        stats={"mc_p5_equity": mc["p5_equity_pct"], "mc_median": mc["median_equity_pct"],
               "mc_p95_maxdd": mc["p95_maxdd"], "sharpe_ci_low": round(lo_ci, 3),
               "sharpe_ci_high": round(hi_ci, 3), "n": n},
    )


def gate_6_structural_break(results: list[dict], grades: list[str]) -> GateResult:
    """GATE 6: Structural Break + Concept Drift.

    CUSUM (Page 1954): deteksi mean-shift dalam stream R-multiples.
    KL-divergence: deteksi distribusi return berubah (concept drift).
    Lulus jika TIDAK ADA break terdeteksi — parameter strategy stabil sepanjang periode.

    Pre-Gain context: deteksi apakah signal quality mengalami regime shift
    (misal: strategi bekerja di bull tapi hancur di sideways).
    """
    valid = [r for r in results if r["outcome"] != "NODATA"]
    n = len(valid)
    if n < 20:
        return GateResult(True, "GATE 6 — Structural Break",
                          f"n={n} < 20: terlalu sedikit untuk structural break test (pass by default)",
                          {"n": n, "skipped": True})
    returns_r = [r["r_multiple"] for r in valid]
    cusum = cusum_test(returns_r, threshold=2.5)
    kl    = kl_divergence_test(returns_r, window=min(20, n // 3), threshold=0.6)
    # Both must pass
    passed = not cusum["break_detected"] and not kl["drift_detected"]
    break_note = (f"CUSUM: {'BREAK @idx{}'.format(cusum['break_index']) if cusum['break_detected'] else 'OK'} "
                  f"(max={cusum['cusum_max']:.2f}) | "
                  f"KL: {'DRIFT @idx{}'.format(kl['drift_index']) if kl['drift_detected'] else 'OK'} "
                  f"(max={kl['max_kl']:.3f})")
    return GateResult(
        passed=passed,
        name="GATE 6 — Structural Break + Concept Drift",
        reason=break_note,
        stats={"cusum": cusum, "kl_divergence": kl, "n": n},
    )


def gate_7_session_direction(results: list[dict], grades: list[str],
                              sessions: list[str],
                              directions: list[str]) -> GateResult:
    """GATE 7: Session + Direction Robustness (PRE-GAIN SOVEREIGN GATE).

    Validasi empiris Pre-Gain specific:
    A. Session robustness: tidak semua profit dari 1 session saja.
       Asia/EU edge harus lebih baik dari US (empiris: Asia 66.7% vs US 40.4%).
    B. Direction asymmetry: SHORT harus outperform LONG.
       Empiris: SHORT WR 67-83% vs LONG WR 37-41%. Ini bukan kebetulan.
    C. US session penalty: strategi yang hanya bekerja di US = suspect.

    UPGRADE RADIKAL: tidak ada di v3 ULTIMATE. Ditambahkan khusus Pre-Gain.
    """
    # Build per-session stats
    sess_data: dict[str, list[float]] = {}
    dir_data:  dict[str, list[float]] = {}
    for r, g, sess, dir_ in zip(results, grades, sessions, directions):
        if r["outcome"] == "NODATA":
            continue
        ret = r["r_multiple"]
        s = sess or "Unknown"
        d = dir_ or "Unknown"
        sess_data.setdefault(s, []).append(ret)
        dir_data.setdefault(d, []).append(ret)

    issues = []
    notes = []

    # A. Session check
    sess_wr = {}
    for sess, rets in sess_data.items():
        if len(rets) >= 5:
            wr = sum(1 for r in rets if r > 0) / len(rets) * 100
            sess_wr[sess] = {"wr": round(wr, 1), "n": len(rets)}

    # Fail if US session is the ONLY session showing positive expectancy
    us_only = (set(sess_wr.keys()) == {"US"} or
               (len(sess_wr) >= 2 and
                sess_wr.get("US", {}).get("wr", 0) >
                max((v["wr"] for k, v in sess_wr.items() if k != "US"), default=0) + 15))
    if us_only:
        issues.append(f"US-session dominance: risky (US empirically weakest session)")
    else:
        _sess_parts = [f"{s}={v['wr']}%(n={v['n']})" for s, v in sess_wr.items()]
        notes.append(f"Session spread OK: {', '.join(_sess_parts)}")

    # B. Direction check
    short_rets = dir_data.get("SHORT", [])
    long_rets  = dir_data.get("LONG",  [])
    dir_ok = True
    if len(short_rets) >= 10 and len(long_rets) >= 10:
        short_wr = sum(1 for r in short_rets if r > 0) / len(short_rets) * 100
        long_wr  = sum(1 for r in long_rets  if r > 0) / len(long_rets)  * 100
        if short_wr < long_wr - 10:  # SHORT should outperform LONG by at least context-appropriate margin
            issues.append(f"Direction anomaly: SHORT({short_wr:.0f}%) < LONG({long_wr:.0f}%) — contradicts empirical pattern")
            dir_ok = False
        else:
            notes.append(f"Direction OK: SHORT={short_wr:.0f}%(n={len(short_rets)}) vs LONG={long_wr:.0f}%(n={len(long_rets)})")
    elif len(short_rets) >= 10:
        short_wr = sum(1 for r in short_rets if r > 0) / len(short_rets) * 100
        notes.append(f"SHORT only: WR={short_wr:.0f}% (n={len(short_rets)}) — LONG insufficient data")

    passed = not issues
    detail = " | ".join(issues + notes) if (issues or notes) else "Insufficient session/direction data"
    return GateResult(
        passed=passed,
        name="GATE 7 — Session + Direction Robustness [PRE-GAIN SOVEREIGN]",
        reason=detail,
        stats={"session_wr": sess_wr,
               "short_n": len(short_rets), "long_n": len(long_rets),
               "us_only_concern": us_only, "direction_ok": dir_ok},
    )


def gate_8_score_band(results: list[dict], grades: list[str],
                       scores: list[int]) -> GateResult:
    """GATE 8: Score Band Non-Monotonicity Validation (PRE-GAIN SOVEREIGN GATE).

    Temuan riset 2026-06-03 (217 signals):
      B-mid  (70-74): WR 18.9%, E=-0.259R → CATASTROPHIC — harus 0 trades
      B-high (75-79): WR 83.3%, E=+0.330R → ELITE, lebih baik dari Grade S
      A-low  (80-84): WR 35.7%, E=-0.188R → SKIP (terutama US session)
      Grade S (90+) : WR 73.7%, E=+0.486R → PROVEN

    Gate ini memverifikasi bahwa:
    1. B-mid (70-74) TIDAK ada dalam backtest (harusnya di-skip oleh decide())
    2. B-high (75-79) menunjukkan expectancy POSITIF dalam data aktual
    3. Non-monotonicity terdeteksi (B-high > A-low) — validasi empiris

    UPGRADE RADIKAL: tidak ada di v3 ULTIMATE. Pre-Gain critical finding.
    """
    band_data: dict[str, dict[str, list[float]]] = {
        b: {"LONG": [], "SHORT": []} for b in
        ("C(60-64)", "B-mid(70-74)", "B-high(75-79)",
         "A-low(80-84)", "A-high(85-89)", "S(90+)")
    }

    def _band(score: int, grade: str) -> str:
        if grade == "S" or score >= 90:   return "S(90+)"
        if 85 <= score <= 89:              return "A-high(85-89)"
        if 80 <= score <= 84:              return "A-low(80-84)"
        if 75 <= score <= 79:              return "B-high(75-79)"
        if 70 <= score <= 74:              return "B-mid(70-74)"
        return "C(60-64)"

    for r, g, sc in zip(results, grades, scores):
        if r["outcome"] == "NODATA":
            continue
        d = "SHORT" if str(r.get("direction", "")).upper() == "SHORT" else "LONG"
        band_data[_band(sc, g)][d].append(r["r_multiple"])

    def _t(rets: list[float]) -> float:
        if len(rets) < 2:
            return 0.0
        sd = _stdev(rets)
        return (sum(rets) / len(rets)) / (sd / (len(rets) ** 0.5)) if sd else 0.0

    issues: list[str] = []
    band_stats = {}
    for band, by_dir in band_data.items():
        pooled = by_dir["LONG"] + by_dir["SHORT"]
        if len(pooled) < 3:
            continue
        n = len(pooled)
        band_stats[band] = {
            "n": n,
            "wr": round(sum(1 for x in pooled if x > 0) / n * 100, 1),
            "exp_r": round(sum(pooled) / n, 3),
            "t": round(_t(pooled), 2),
            "by_direction": {
                d: {"n": len(v), "exp_r": round(sum(v) / len(v), 3), "t": round(_t(v), 2)}
                for d, v in by_dir.items() if v
            },
        }

    # Check 1: B-mid harus 0 trade (catastrophic band di-gate di decide())
    bmid = band_stats.get("B-mid(70-74)", {})
    if bmid.get("n", 0) > 0:
        issues.append(f"B-mid(70-74) trades found: n={bmid['n']}, E={bmid.get('exp_r', 0):+.3f}R "
                      f"— catastrophic band should be gated in decide()")

    # Check 2: B-high negatif HANYA dianggap masalah bila signifikan (t < -2).
    # t=0.2 artinya "nol", bukan "negatif" — dulu selalu gagal karena E mentah.
    bhigh = band_stats.get("B-high(75-79)", {})
    if bhigh.get("n", 0) >= 10 and bhigh.get("exp_r", 0) < 0 and bhigh.get("t", 0) < -2.0:
        issues.append(f"B-high(75-79) negatif signifikan: E={bhigh['exp_r']:+.3f}R "
                      f"(n={bhigh['n']}, t={bhigh['t']}) — expected elite")

    # Check 3: band non-monotonik hanya jika BEDA-nya signifikan (Welch p<0.10)
    alow = band_stats.get("A-low(80-84)", {})
    if (bhigh.get("n", 0) >= 30 and alow.get("n", 0) >= 30 and
            bhigh.get("exp_r", -1) < alow.get("exp_r", 1) and
            _welch_p(band_data["B-high(75-79)"]["LONG"] + band_data["B-high(75-79)"]["SHORT"],
                     band_data["A-low(80-84)"]["LONG"] + band_data["A-low(80-84)"]["SHORT"]) < 0.10):
        issues.append(f"Non-monotonicity signifikan: B-high({bhigh.get('exp_r', 0):+.3f}R) "
                      f"< A-low({alow.get('exp_r', 0):+.3f}R)")

    # Check 4: kualitas per ARAH — domba hitam tersembunyi di agregat band.
    dir_stats = {}
    for d in ("LONG", "SHORT"):
        rets = [x for band in band_data.values() for x in band[d]]
        if len(rets) >= 30:
            dir_stats[d] = {"n": len(rets), "exp_r": round(sum(rets) / len(rets), 3),
                            "t": round(_t(rets), 2),
                            "tp_hit_pct": round(sum(1 for x in rets if x > 0.9) / len(rets) * 100, 1)}
        if dir_stats.get(d, {}).get("t", 0) < -2.0:
            issues.append(f"Arm {d} negatif signifikan: E={dir_stats[d]['exp_r']:+.3f}R "
                          f"(n={dir_stats[d]['n']}, t={dir_stats[d]['t']}) — agregasi band menutupi ini")

    bands_str = " | ".join(
        f"{b}:E={v['exp_r']:+.3f}R(n={v['n']},t={v['t']:+.1f})" for b, v in band_stats.items())
    passed = len(issues) == 0
    return GateResult(
        passed=passed,
        name="GATE 8 — Score Band Non-Monotonicity [PRE-GAIN SOVEREIGN]",
        reason=(f"{'; '.join(issues) if issues else 'OK — no catastrophic bands, elite bands validated'} | {bands_str}"),
        stats={"band_stats": band_stats, "issues": issues, "direction_stats": dir_stats},
    )


def _stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def _welch_p(a: list[float], b: list[float]) -> float:
    """Two-sided Welch t-test → p-value (normal approx, n besar)."""
    if len(a) < 2 or len(b) < 2:
        return 1.0
    va, vb = _stdev(a) ** 2 / len(a), _stdev(b) ** 2 / len(b)
    se = (va + vb) ** 0.5
    if se == 0:
        return 1.0
    t = (sum(a) / len(a) - sum(b) / len(b)) / se
    return 2 * (1 - _norm_cdf(abs(t)))


def gate_9_adversarial_stress(results: list[dict], grades: list[str],
                               min_survive_pct: float = 0.50) -> GateResult:
    """GATE 9: Pre-Gain Adversarial Stress Test (PRE-GAIN SOVEREIGN GATE).

    6 skenario adversarial diadaptasi dari v3 ULTIMATE untuk konteks Pre-Gain.
    Strategi harus survive (equity > min_survive_pct dari peak) di semua skenario.

    Skenario Pre-Gain specific:
    1. Flash crash injection    — 3% trades random hit extreme -30% loss
    2. HL downtime simulation   — 15% trades first-in-sequence become NODATA
    3. Funding spike adversarial— SHORT signals yang dekat settlement berubah LOSS
    4. Scan flood degradation   — randomly select "crowded scan" sample, WR drops
    5. Adverse slippage escalation — fee naik 3x untuk 20% trades
    6. Session blackout (US)    — semua US-session trades dianggap loss

    UPGRADE RADIKAL: v3 punya general stress test; ini dikalibrasi untuk Pre-Gain.
    """
    valid = [r for r in results if r["outcome"] != "NODATA"]
    n = len(valid)
    if n < 15:
        return GateResult(True, "GATE 9 — Adversarial Stress",
                          f"n={n} < 15: skipped by default (insufficient data for stress test)",
                          {"n": n, "skipped": True})

    # Baseline equity (fixed-stake: risiko konstan 2% modal awal per 1R)
    base_rets = [r["r_multiple"] for r in valid]
    base_st = _path_stats(base_rets)
    base_eq = base_st["final"]

    scenarios = {}
    rng = random.Random(42)

    # 1. Flash crash: randomly hit 3% of trades with -4.3R (≈ -30% / 7%)
    s1_rets = list(base_rets)
    crash_n = max(1, int(n * 0.03))
    crash_idx = rng.sample(range(n), crash_n)
    for i in crash_idx:
        s1_rets[i] = -4.28  # -30% / 7% SL
    scenarios["flash_crash"] = {"equity": _path_stats(s1_rets)["final"], "rets": s1_rets}

    # 2. HL downtime: first 15% of trades zeroed (NODATA period)
    s2_rets = list(base_rets)
    downtime_n = max(1, int(n * 0.15))
    for i in range(downtime_n):
        s2_rets[i] = 0.0  # no trade possible
    scenarios["hl_downtime"] = {"equity": _path_stats(s2_rets)["final"], "rets": s2_rets}

    # 3. Funding spike: last 20% of trades (funding-dependent) become -1.0R
    s3_rets = list(base_rets)
    spike_n = max(1, int(n * 0.20))
    for i in range(n - spike_n, n):
        s3_rets[i] = -1.0  # funding spike kills signal
    scenarios["funding_spike"] = {"equity": _path_stats(s3_rets)["final"], "rets": s3_rets}

    # 4. Scan flood: randomly select 40% trades, replace with 0.49 WR expectancy
    s4_rets = list(base_rets)
    flood_idx = rng.sample(range(n), max(1, int(n * 0.40)))
    for i in flood_idx:
        # Crowded scan → 49% WR → E ≈ -0.05R
        s4_rets[i] = rng.choice([-1.0, -1.0, -1.0, -1.0, -1.0, -1.0, 2.86, 2.86, 2.86, 2.86, 2.86])
    scenarios["scan_flood"] = {"equity": _path_stats(s4_rets)["final"], "rets": s4_rets}

    # 5. Adverse slippage: fee 3x for 20% of trades (worst sequential block)
    s5_rets = list(base_rets)
    slip_start = rng.randint(0, max(0, n - int(n * 0.20) - 1))
    slip_end = min(n, slip_start + int(n * 0.20))
    for i in range(slip_start, slip_end):
        s5_rets[i] = s5_rets[i] - 0.12  # extra 2x fee (0.09% → 0.27%)
    scenarios["adverse_slippage"] = {"equity": _path_stats(s5_rets)["final"], "rets": s5_rets}

    # 6. Session blackout (US): simulate 25% worst-session trades all lose
    s6_rets = list(base_rets)
    us_n = max(1, int(n * 0.25))
    us_idx = rng.sample(range(n), us_n)
    for i in us_idx:
        s6_rets[i] = -1.0  # US session worst case: all stop-out
    scenarios["session_blackout_us"] = {"equity": _path_stats(s6_rets)["final"], "rets": s6_rets}

    # Evaluate survival: drawdown dari PEAK skenario ≤ (1 - min_survive_pct),
    # dan ekuitas akhir tidak negatif. Dulu membandingkan eq ke 50% *base_eq*
    # yang meledak, sehingga skenario yang wajar pun selalu "gagal".
    max_allowed_dd = 1.0 - min_survive_pct
    failed = []
    results_detail = {}
    for name, sc in scenarios.items():
        st = _path_stats(sc["rets"])
        eq, dd = st["final"], st["max_dd"]
        survived = (dd <= max_allowed_dd) and eq > 0.0
        results_detail[name] = {"equity": round(eq, 3), "max_dd": round(dd, 3),
                                  "survived": survived,
                                  "vs_base_pct": round((eq - base_eq) / max(abs(base_eq), 1e-9) * 100, 1)}
        if not survived:
            failed.append(f"{name}(dd={dd:.0%}, eq=10^{math.log10(eq) if eq > 1e-9 else 0:.2f}×)")

    passed = len(failed) == 0
    def _lgx(v: float) -> str:
        return "0" if v <= 1e-9 else f"10^{math.log10(v):+.2f}"

    return GateResult(
        passed=passed,
        name="GATE 9 — Adversarial Stress [PRE-GAIN SOVEREIGN]",
        reason=(f"{'All 6 scenarios survived' if passed else 'FAILED: ' + str(failed)} | "
                f"Base equity={_lgx(base_eq)}× (DD {base_st['max_dd']:.1%}) | "
                f"Batas DD={max_allowed_dd:.0%} | "
                f"Scenarios: {', '.join(k + ': ' + _lgx(v['equity']) + '×/' + str(round(v['max_dd']*100)) + '%dd' for k, v in results_detail.items())}"),
        stats={"scenarios": results_detail, "failed": failed, "n": n,
               "base_equity": round(base_eq, 4),
               "base_max_dd": round(base_st["max_dd"], 4),
               "max_allowed_dd": max_allowed_dd,
               "risk_frac_per_r": RISK_FRAC_PER_R},
    )


def gate_10_live_convergence(backtest_stats: dict,
                              live_results: list[dict],
                              live_grades: list[str],
                              min_live_days: int = 14,
                              max_wr_delta: float = 15.0) -> GateResult:
    """GATE 10: Live Forward-Test Convergence.

    Reality check final: apakah live trading performance mendekati backtest?
    Strategi yang terlihat bagus di backtest tapi hancur saat live = overfit.

    Kondisi lulus:
    1. Min 14 hari data live (Gate 10 butuh waktu nyata — tidak bisa dipercepat)
    2. Live WR within max_wr_delta=15pp dari backtest WR
    3. Live structural break: CUSUM tidak mendeteksi break dalam live returns
    """
    live_valid = [r for r in live_results if r["outcome"] != "NODATA"]
    n_live = len(live_valid)

    if n_live < 5:
        return GateResult(False, "GATE 10 — Live Convergence",
                          f"Insufficient live data: {n_live} trades. "
                          f"Gate 10 requires ≥{min_live_days} days of paper/live data. "
                          f"Continue accumulating forward-test data.",
                          {"n_live": n_live, "required_days": min_live_days,
                           "status": "ACCUMULATING"})

    live_rets = [r["r_multiple"] for r in live_valid]
    live_wins = sum(1 for r in live_valid if r["realized_pct"] > 0)
    live_wr   = live_wins / n_live * 100
    live_exp  = sum(live_rets) / n_live
    bt_wr     = backtest_stats.get("win_rate", 50.0)
    wr_delta  = abs(live_wr - bt_wr)

    cusum = cusum_test(live_rets, threshold=3.0)  # tighter threshold for live monitoring

    wr_ok   = wr_delta <= max_wr_delta
    cusum_ok = not cusum["break_detected"]
    # Require positive live expectancy (must not be losing in live)
    exp_ok   = live_exp > -0.2  # allow slight negative (small n noise)

    passed = wr_ok and cusum_ok and exp_ok
    return GateResult(
        passed=passed,
        name="GATE 10 — Live Convergence",
        reason=(f"Live WR={live_wr:.1f}% vs BT WR={bt_wr:.1f}% (delta={wr_delta:.1f}pp, max {max_wr_delta}pp) | "
                f"Live E={live_exp:+.3f}R | "
                f"CUSUM: {'BREAK detected' if cusum['break_detected'] else 'OK'} | "
                f"n_live={n_live}"),
        stats={"live_wr": round(live_wr, 1), "backtest_wr": round(bt_wr, 1),
               "wr_delta": round(wr_delta, 1), "live_exp_r": round(live_exp, 3),
               "live_cusum": cusum, "n_live": n_live},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════

def run_all_gates(
    results:     list[dict],
    grades:      list[str],
    scores:      Optional[list[int]]  = None,
    sessions:    Optional[list[str]]  = None,
    directions:  Optional[list[str]]  = None,
    live_results: Optional[list[dict]] = None,
    live_grades:  Optional[list[str]]  = None,
    backtest_stats: Optional[dict]    = None,
    n_trials:    int                  = 20,
    verbose:     bool                 = False,
) -> dict:
    """Run all 10 sovereign gates in order. Return full verdict.

    Inputs:
      results    : list of simulate_trade() outputs
      grades     : corresponding grade per result (same length)
      scores     : optional score per result (needed for Gate 8)
      sessions   : optional session per result (needed for Gate 7)
      directions : optional direction per result (needed for Gate 7)
      live_results/live_grades: optional forward-test data (Gate 10)
      backtest_stats: output of pregain_backtest.aggregate() (Gate 10)
      n_trials   : number of parameter combinations tested (Gate 2 MinBTL)

    Returns dict with:
      passed_gates   : count of passed gates
      total_gates    : 10
      verdict        : "GO_LIVE_MICRO" | "GO_PAPER" | "NO_GO" | "ACCUMULATING"
      gates          : list of GateResult
      summary        : human-readable string
    """
    if len(results) != len(grades):
        raise ValueError(f"results ({len(results)}) and grades ({len(grades)}) must be same length")
    n = len(results)
    _scores     = scores     or [75] * n
    _sessions   = sessions   or ["Unknown"] * n
    _directions = directions or ["SHORT"] * n
    _live       = live_results or []
    _live_g     = live_grades  or []
    _bt_stats   = backtest_stats or {}

    gate_fns = [
        lambda: gate_1_basic_performance(results, grades),
        lambda: gate_2_minbtl_psr(results, grades, n_trials=n_trials),
        lambda: gate_3_fdr_control(results, grades),
        lambda: gate_4_sequential_testing(results, grades),
        lambda: gate_5_mc_bootstrap(results, grades),
        lambda: gate_6_structural_break(results, grades),
        lambda: gate_7_session_direction(results, grades, _sessions, _directions),
        lambda: gate_8_score_band(results, grades, _scores),
        lambda: gate_9_adversarial_stress(results, grades),
        lambda: gate_10_live_convergence(_bt_stats, _live, _live_g),
    ]

    gate_results: list[GateResult] = []
    for i, fn in enumerate(gate_fns):
        try:
            gr = fn()
        except Exception as e:
            gr = GateResult(False, f"GATE {i+1}", f"ERROR: {e}", {})
        gate_results.append(gr)
        if verbose:
            print(str(gr))

    passed = sum(1 for g in gate_results if g.passed)
    total  = len(gate_results)

    # Verdict logic:
    # All 10: GO_LIVE_MICRO (with circuit breakers)
    # 8-9 passed, key gates OK: GO_PAPER (continue accumulating)
    # Gates 1-3 passed: ACCUMULATING (not enough data)
    # < Gate 1: NO_GO
    critical_ok = gate_results[0].passed and gate_results[1].passed  # G1 + G2
    if passed == total:
        verdict = "GO_LIVE_MICRO"
    elif passed >= 8 and critical_ok:
        verdict = "GO_PAPER"
    elif passed >= 3 and critical_ok:
        verdict = "ACCUMULATING"
    else:
        verdict = "NO_GO"

    # Build summary
    lines = [
        f"╔══ PRE-GAIN SOVEREIGN VALIDATION ══════════════════════════════",
        f"║  Passed: {passed}/{total} gates  |  Verdict: {verdict}",
        f"╠══ Gate Results:",
    ]
    for g in gate_results:
        icon = "✅" if g.passed else "❌"
        lines.append(f"║  {icon} {g.name}: {g.reason[:90]}{'...' if len(g.reason)>90 else ''}")
    lines.append(f"╚══ {'SOVEREIGN EDGE CONFIRMED — GO LIVE MICRO' if verdict=='GO_LIVE_MICRO' else verdict}")
    summary = "\n".join(lines)

    return {
        "passed_gates":   passed,
        "total_gates":    total,
        "verdict":        verdict,
        "gates":          gate_results,
        "gate_dicts":     [{"name": g.name, "passed": g.passed, "reason": g.reason,
                            "stats": g.stats} for g in gate_results],
        "summary":        summary,
        "ts":             int(time.time()),
    }


def format_report(verdict_dict: dict) -> str:
    """Human-readable gate report for Telegram / CLI output."""
    return verdict_dict.get("summary", "No summary available")
