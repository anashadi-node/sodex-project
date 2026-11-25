#!/usr/bin/env python3
"""
ANANTARA EVALUATION HARNESS v1 — fondasi pengukuran bersama
Dibangun Divisi RISET untuk dipakai SEMUA divisi (SoDEX / CEX-Binance / HL-Harvest).

TUJUAN: memastikan setiap divisi mengukur dengan cara IDENTIK sehingga hasil
        bisa dibandingkan. Tanpa ini, setiap divisi akan menghasilkan angka yang
        tidak sebanding (dasar C1/C2: evaluasi naif menggelembungkan Sharpe 3,6x).

PRINSIP (dari skill riset-penelitian + ANANTARA Master Evidence V1/V2):
  1. FAIL-CLOSED     — penilai yang melempar => SEMUA tingkat False, tidak pernah PASS
  2. KONTROL NEGATIF — wajib ikut jalan; kalau lolos, set uji terlalu mudah
  3. BETA-NETRAL     — excess terhadap pasar pada horizon yang sama
  4. BIAYA STRESS    — 1x / 1.5x / 2x
  5. CLUSTERED SE    — t per simbol & per hari, bukan pooled mentah
  6. DSR             — Deflated Sharpe atas JUMLAH TRIAL yang jujur
  7. REGISTRY        — trial gagal tetap tercatat

Pemakaian cepat:
  from anantara_harness import evaluate, beta_neutralize, cost_stress, deflated_sharpe
  res = evaluate(returns=..., market=..., sides=..., risk=..., fee_bps=8, n_trials=12)
"""
from __future__ import annotations
import json, math, os, statistics as st
from dataclasses import dataclass, field, asdict

try:
    import numpy as np
    _HAS_NP = True
except Exception:
    _HAS_NP = False

EULER = 0.5772156649015329


# ─────────────────────────── 1. FAIL-CLOSED CORE ───────────────────────────
class EvaluationError(RuntimeError):
    """Dilempar saat input tidak memenuhi syarat. TIDAK boleh ditelan."""


@dataclass
class Grade:
    """Hasil penilaian. `passed` HANYA True bila SEMUA tingkat lulus."""
    level_data: bool = False
    level_metric: bool = False
    level_decision: bool = False
    reasons: list = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.level_data and self.level_metric and self.level_decision)

    def to_dict(self):
        d = asdict(self)
        d['passed'] = self.passed
        return d


def _require(cond, msg):
    if not cond:
        raise EvaluationError(msg)


# ─────────────────────────── 2. METRIK DASAR ───────────────────────────
def _arr(x):
    if _HAS_NP:
        return np.asarray(x, dtype=float)
    return [float(v) for v in x]


def bootstrap_ci(x, it=3000, seed=11, alpha=0.05):
    """CI bootstrap untuk mean. Mengembalikan (lo, hi). NaN bila n terlalu kecil."""
    a = _arr(x)
    if _HAS_NP:
        a = a[~np.isnan(a)]
        if len(a) < 8:
            return float('nan'), float('nan')
        rng = np.random.default_rng(seed)
        bs = [float(np.mean(rng.choice(a, len(a), replace=True))) for _ in range(it)]
        return float(np.percentile(bs, 100 * alpha / 2)), float(np.percentile(bs, 100 * (1 - alpha / 2)))
    if len(a) < 8:
        return float('nan'), float('nan')
    import random
    random.seed(seed)
    bs = [st.mean(random.choices(a, k=len(a))) for _ in range(it)]
    bs.sort()
    return bs[int(it * alpha / 2)], bs[int(it * (1 - alpha / 2))]


def sharpe(returns, periods_per_year=365):
    a = _arr(returns)
    if _HAS_NP:
        a = a[~np.isnan(a)]
        if len(a) < 5:
            return float('nan')
        sd = float(a.std(ddof=1))
        return float(a.mean() / sd * math.sqrt(periods_per_year)) if sd > 0 else float('nan')
    a = [v for v in a if v == v]
    if len(a) < 5:
        return float('nan')
    sd = st.stdev(a)
    return st.mean(a) / sd * math.sqrt(periods_per_year) if sd > 0 else float('nan')


def max_drawdown(returns):
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in _arr(returns):
        eq *= (1 + float(r))
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    return float(mdd)


# ─────────────────────────── 3. BETA-NETRALISASI (G6) ───────────────────────────
def beta_neutralize(trade_returns, market_returns, sides):
    """
    excess_i = side_i * r_trade_i - side_i * r_market_i
    trade_returns/market_returns: fraksi (mis. 0.004 = 0.4%)
    sides: +1 long, -1 short  (atau 'L'/'S')
    """
    _require(len(trade_returns) == len(market_returns) == len(sides),
             'beta_neutralize: panjang array tidak sama')
    out = []
    for tr, mr, sd in zip(trade_returns, market_returns, sides):
        s = 1.0 if sd in (1, 'L', 'LONG', 'long') else -1.0
        out.append(s * float(tr) - s * float(mr))
    return out


# ─────────────────────────── 4. BIAYA + STRESS (G2) ───────────────────────────
def cost_stress(returns, fee_bps, turnover_per_period=1.0, multipliers=(1.0, 1.5, 2.0)):
    """Kurangi biaya round-trip per periode untuk tiap tingkat stress."""
    out = {}
    for m in multipliers:
        cost = (fee_bps / 1e4) * m * turnover_per_period
        out[m] = [float(r) - cost for r in returns]
    return out


# ─────────────────────────── 5. CLUSTERED / PER-SIMBOL (aturan K6) ───────────────────────────
def t_stat_per_group(values, groups, min_n=8):
    """t-statistik mean per kelompok (per simbol / per hari). Mencegah ilusi pooled."""
    buckets = {}
    for v, g in zip(values, groups):
        buckets.setdefault(g, []).append(float(v))
    res = {}
    for g, vs in buckets.items():
        if len(vs) < min_n:
            res[g] = {'n': len(vs), 't': None, 'note': 'n terlalu kecil'}
            continue
        mu = st.mean(vs); sd = st.stdev(vs)
        res[g] = {'n': len(vs), 'mean': mu,
                  't': (mu / (sd / math.sqrt(len(vs)))) if sd > 0 else None}
    return res


def pooled_t_naive(values):
    """t gabungan naif — DISEDIAKAN HANYA untuk menunjukkan biasnya. Jangan dipakai menyimpulkan."""
    a = [float(v) for v in values if v == v]
    if len(a) < 8:
        return float('nan')
    sd = st.stdev(a)
    return st.mean(a) / (sd / math.sqrt(len(a))) if sd > 0 else float('nan')


# ─────────────────────────── 6. DEFLATED SHARPE (Bailey & López de Prado) ───────────────────────────
def _norm_cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _norm_ppf(p):
    # aproksimasi Acklam
    if p <= 0 or p >= 1:
        raise EvaluationError('_norm_ppf: p di luar (0,1)')
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > ph:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5; r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def deflated_sharpe(returns, n_trials, sharpe_variance_across_trials=None, periods_per_year=365):
    """
    DSR: probabilitas bahwa Sharpe yang diamati BUKAN hasil seleksi dari n_trials.
    Mengembalikan dict {sr_obs, sr0_expected, dsr} atau {'error': ...} bila input tidak layak.
    n_trials WAJIB jujur (seluruh percobaan, termasuk yang gagal).
    """
    a = _arr(returns)
    if _HAS_NP:
        a = a[~np.isnan(a)]
        n, mu, sd = len(a), float(a.mean()), float(a.std(ddof=1))
        skew = float(((a - mu) ** 3).mean() / sd ** 3) if sd > 0 else 0.0
        kurt = float(((a - mu) ** 4).mean() / sd ** 4) if sd > 0 else 3.0
    else:
        a = [v for v in a if v == v]; n = len(a)
        if n < 8:
            return {'error': 'n terlalu kecil'}
        mu, sd = st.mean(a), st.stdev(a)
        skew = st.mean([((v - mu) / sd) ** 3 for v in a]) if sd > 0 else 0.0
        kurt = st.mean([((v - mu) / sd) ** 4 for v in a]) if sd > 0 else 3.0
    if n < 8 or sd <= 0:
        return {'error': 'input tidak layak (n<8 atau sd=0)'}
    sr_pp = mu / sd
    sr_ann = sr_pp * math.sqrt(periods_per_year)
    if n_trials is None or n_trials < 1:
        return {'error': 'n_trials wajib >= 1 (jumlah percobaan jujur)'}
    if n_trials <= 1:
        # Tidak ada seleksi yang bisa di-deflate: DSR = PSR (probabilistic Sharpe ratio)
        sr0 = 0.0
        note = 'n_trials=1 -> tanpa deflasi (DSR = PSR). Sertakan seluruh trial untuk deflasi nyata.'
    else:
        note = None
        if sharpe_variance_across_trials is None:
            var_sr = (1 + 0.5 * sr_pp ** 2) / (n - 1) if n > 1 else float('nan')
        else:
            var_sr = float(sharpe_variance_across_trials)
        if not var_sr or var_sr <= 0 or var_sr != var_sr:
            return {'error': 'varians Sharpe antar-trial tidak valid'}
        p1 = min(max(1 - 1.0 / n_trials, 1e-9), 1 - 1e-9)
        p2 = min(max(1 - 1.0 / (n_trials * math.e), 1e-9), 1 - 1e-9)
        sr0 = math.sqrt(var_sr) * ((1 - EULER) * _norm_ppf(p1) + EULER * _norm_ppf(p2))
    # PSR/DSR: Φ( (SR_hat − SR0) · sqrt(n−1) / sqrt(1 − γ3·SR_hat + ((γ4−1)/4)·SR_hat²) )
    denom = math.sqrt(max(1e-12, 1 - skew * sr_pp + ((kurt - 1) / 4.0) * sr_pp ** 2))
    dsr = _norm_cdf((sr_pp - sr0) * math.sqrt(max(n - 1, 1)) / denom)
    out = {'n': n, 'sr_per_period': sr_pp, 'sr_annualized': sr_ann,
           'sr0_expected_max': sr0, 'sr0_annualized': sr0 * math.sqrt(periods_per_year),
           'dsr': float(dsr), 'n_trials': int(n_trials)}
    if note:
        out['note'] = note
    return out


# ─────────────────────────── 7. KONTROL NEGATIF (aturan #9) ───────────────────────────
def negative_control_check(candidate_metric, random_metric, margin=0.02):
    """Kontrol negatif WAJIB kalah. Kalau lolos, set uji terlalu mudah."""
    ok = candidate_metric is not None and random_metric is not None and (candidate_metric > random_metric + margin)
    return {'candidate': candidate_metric, 'random_control': random_metric, 'margin': margin,
            'control_passed': bool(ok),
            'verdict': 'LULUS (kandidat mengalahkan kontrol)' if ok else
                       'GAGAL — kontrol negatif tidak kalah; set uji terlalu mudah'}


# ─────────────────────────── 8. REGISTRY TRIAL ───────────────────────────
class TrialRegistry:
    """Semua trial WAJIB tercatat, termasuk yang gagal. Anti-p-hacking."""

    def __init__(self, path):
        self.path = path
        self.rows = []
        if os.path.exists(path):
            try:
                self.rows = json.load(open(path))
            except Exception:
                self.rows = []

    def log(self, **kw):
        kw['n_trials_total'] = len(self.rows) + 1
        self.rows.append(kw)
        json.dump(self.rows, open(self.path, 'w'), indent=1, default=str)
        return kw['n_trials_total']

    def count(self):
        return len(self.rows)


# ─────────────────────────── 9. EVALUATOR UTAMA ───────────────────────────
def evaluate(returns, market=None, sides=None, risk=None, fee_bps=8.0,
             turnover_per_period=1.0, n_trials=None, groups=None,
             periods_per_year=365, min_n=30):
    """
    Evaluasi lengkap sesuai gate. FAIL-CLOSED: bila ada tahap gagal, grade.passed=False.
    returns: net-periode (fraksi). Bila `market` & `sides` diberikan -> beta-netral dulu.
    """
    g = Grade()
    # level 1: data
    try:
        r = [float(v) for v in returns if v is not None and float(v) == float(v)]
        _require(len(r) >= min_n, f'level_data: n={len(r)} < min_n={min_n} (FAIL-CLOSED)')
        if market is not None:
            _require(len(market) == len(returns) and sides is not None and len(sides) == len(returns),
                     'level_data: market/sides tidak sejajar dengan returns')
        g.level_data = True
    except EvaluationError as e:
        g.reasons.append(str(e)); return g.to_dict(), {}
    except Exception as e:
        g.reasons.append(f'level_data: penilai melempar {type(e).__name__}: {e}')
        return g.to_dict(), {}

    out = {'n': len(r)}

    # beta-netral
    if market is not None:
        excess = beta_neutralize(returns, market, sides)
        excess = [v for v in excess if v == v]
        out['beta_neutral'] = True
        out['excess_mean'] = st.mean(excess)
        out['excess_median'] = st.median(excess)
        r_eval = excess
    else:
        out['beta_neutral'] = False
        out['excess_mean'] = None
        g.reasons.append('PERINGATAN: tanpa market/sides -> tidak beta-netral (G6 belum dipenuhi)')
        r_eval = r

    # level 2: metrik
    try:
        lo, hi = bootstrap_ci(r_eval)
        out['ci95'] = [lo, hi]
        out['mean'] = st.mean(r_eval); out['median'] = st.median(r_eval)
        out['wr'] = sum(1 for v in r_eval if v > 0) / len(r_eval)
        out['sharpe_ann'] = sharpe(r_eval, periods_per_year)
        out['maxdd'] = max_drawdown(r_eval)
        out['cost_stress'] = {str(m): {'mean': st.mean(v), 'sharpe_ann': sharpe(v, periods_per_year)}
                              for m, v in cost_stress(r_eval, fee_bps, turnover_per_period).items()}
        if n_trials:
            out['dsr'] = deflated_sharpe(r_eval, n_trials, periods_per_year=periods_per_year)
        if groups is not None:
            out['per_group_t'] = t_stat_per_group(r_eval, groups)
            out['pooled_t_naive_WARNING'] = pooled_t_naive(r_eval)
        g.level_metric = all(v == v for v in (out['mean'], out['sharpe_ann']))
        if not g.level_metric:
            g.reasons.append('level_metric: metrik utama NaN')
    except Exception as e:
        g.reasons.append(f'level_metric: penilai melempar {type(e).__name__}: {e}')
        return g.to_dict(), out

    # level 3: keputusan
    try:
        net_pos_1x = out['cost_stress']['1.0']['mean'] > 0
        net_pos_2x = out['cost_stress']['2.0']['mean'] > 0
        ci_lo, ci_hi = out['ci95']
        ci_excludes_zero_pos = ci_lo == ci_lo and ci_lo > 0
        dsr_ok = True
        if 'dsr' in out and 'dsr' in out['dsr']:
            dsr_ok = out['dsr']['dsr'] >= 0.95
        checks = {
            'net_pos_1x': bool(net_pos_1x),
            'net_pos_2x': bool(net_pos_2x),          # G2
            'ci95_lower_positive': bool(ci_excludes_zero_pos),
            'dsr_passed': bool(dsr_ok),              # G1/DSR (policy >=0.95)
            'beta_neutral': bool(out['beta_neutral']),  # G6
        }
        out['checks'] = checks
        g.level_decision = all(checks.values())
        if not g.level_decision:
            g.reasons.append('level_decision: ' + ', '.join(k for k, v in checks.items() if not v))
    except Exception as e:
        g.reasons.append(f'level_decision: penilai melempar {type(e).__name__}: {e}')
        return g.to_dict(), out

    out['grade'] = g.to_dict()
    return g.to_dict(), out
