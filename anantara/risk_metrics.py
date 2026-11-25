#!/usr/bin/env python3
"""
ANANTARA SAKTI — Institutional risk & performance metrics (pure, stdlib-only, tested).

The biggest institutional-grade gap was a reusable risk/performance core. This
adds the standard quant-fund toolkit so position sizing and performance reporting
move from ad-hoc to disciplined:

  • sharpe / sortino / calmar      — risk-adjusted performance
  • max_drawdown                   — worst peak-to-trough (capital preservation)
  • annualized_return / _vol       — scaling per-period stats to annual
  • vol_target_size                — VOLATILITY TARGETING: scale exposure so realized
                                     vol ≈ target (caps risk in choppy regimes)
  • fractional_kelly               — FRACTIONAL KELLY sizing (half-Kelly default:
                                     ~75% of full-Kelly growth, far lower drawdown;
                                     recompute every 50-100 trades as regimes drift)

Stdlib only (no numpy) to match the project's testable pure cores. All functions
degrade gracefully on tiny/degenerate input (return 0.0, never raise).
"""
from __future__ import annotations

import math
from typing import Sequence


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: Sequence[float], ddof: int = 1) -> float:
    n = len(xs)
    if n <= ddof:
        return 0.0
    m = _mean(xs)
    return (sum((x - m) ** 2 for x in xs) / (n - ddof)) ** 0.5


def annualized_return(returns: Sequence[float], periods_per_year: int = 365) -> float:
    """Geometric annualized return from a series of per-period simple returns."""
    if not returns:
        return 0.0
    growth = 1.0
    for r in returns:
        growth *= (1.0 + r)
    if growth <= 0:
        return -1.0
    return growth ** (periods_per_year / len(returns)) - 1.0


def annualized_vol(returns: Sequence[float], periods_per_year: int = 365) -> float:
    return _std(returns) * (periods_per_year ** 0.5)


def sharpe(returns: Sequence[float], rf: float = 0.0, periods_per_year: int = 365) -> float:
    """Annualized Sharpe ratio (rf = per-period risk-free)."""
    if len(returns) < 2:
        return 0.0
    excess = [r - rf for r in returns]
    sd = _std(excess)
    if sd == 0:
        return 0.0
    return (_mean(excess) / sd) * (periods_per_year ** 0.5)


def sharpe_log(returns: Sequence[float], rf: float = 0.0, periods_per_year: int = 365) -> float:
    """Sharpe dari rata-rata LOG (geometrik) — bentuk yang BENAR untuk kurva ekuitas.

    `sharpe()` memakai rata-rata ARITMETIKA. Pada deret return yang berasal dari
    KURVA EKUITAS yang menyusut, rata-rata aritmetika bisa POSITIF padahal level
    jatuh: kerugian besar terjadi saat basis masih besar, lalu keuntungan kecil
    menyusul saat basis sudah kecil sehingga persentasenya membesar.

    Terukur 2026-10-04 (wallet SoDEX, -67% nilainya): Sharpe aritmetika +3,03
    tetapi Sharpe log -0,27; pada jendela rolling 90 hari +2,71 vs -0,42. Validasi
    silang: exp(sum(log)) = 0,3272 = persis rasio ekuitas akhir/awal.

    Untuk return PER-TRADE dengan ukuran tetap, `sharpe()` tetap konvensi yang
    benar — bedanya basis tidak menyusut. Pakai `sharpe_log()` bila deretnya
    berasal dari kurva ekuitas/kumulatif, dan bandingkan keduanya dengan
    `sharpe_divergence()`.
    """
    if len(returns) < 2:
        return 0.0
    logs = []
    for r in returns:
        growth = 1.0 + r - rf
        if growth > 0:
            logs.append(math.log(growth))
    if len(logs) < 2:
        return 0.0
    sd = _std(logs)
    if sd == 0:
        return 0.0
    return (_mean(logs) / sd) * (periods_per_year ** 0.5)


def sharpe_divergence(arith: float, log: float) -> dict:
    """Bandingkan Sharpe aritmetika vs log untuk mendeteksi artefak basis-menyusut.

    Aturan praktis: **selisih TANDA = artefak**, bukan edge. Jarak besar (> nilai
    absolut aritmetika, minimal 1,0) juga menandai hasil yang tidak stabil.
    """
    sign_flip = (arith > 0) != (log > 0)
    gap = abs(arith - log)
    suspect = bool(sign_flip or gap > max(1.0, abs(arith)))
    return {
        "arith": arith,
        "log": log,
        "sign_flip": bool(sign_flip),
        "gap": gap,
        "artifact_suspect": suspect,
        "recommended": "log (geometrik)" if suspect else "arith (return per-periode)",
    }


def sortino(returns: Sequence[float], rf: float = 0.0, periods_per_year: int = 365) -> float:
    """Annualized Sortino (downside-deviation only — penalizes losses, not upside vol)."""
    if len(returns) < 2:
        return 0.0
    excess = [r - rf for r in returns]
    downside = [min(0.0, e) for e in excess]
    dd = (sum(d ** 2 for d in downside) / len(downside)) ** 0.5
    if dd == 0:
        return 0.0
    return (_mean(excess) / dd) * (periods_per_year ** 0.5)


def max_drawdown(equity: Sequence[float]) -> float:
    """Worst peak-to-trough decline as a positive fraction (0.20 = -20%)."""
    if not equity:
        return 0.0
    peak = equity[0]
    mdd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return mdd


def equity_curve(returns: Sequence[float], start: float = 1.0) -> list[float]:
    """Compound a returns series into an equity curve (for max_drawdown)."""
    eq, v = [], start
    for r in returns:
        v *= (1.0 + r)
        eq.append(v)
    return eq


def calmar(returns: Sequence[float], periods_per_year: int = 365) -> float:
    """Annualized return / max drawdown (reward per unit of worst loss)."""
    mdd = max_drawdown(equity_curve(returns))
    if mdd == 0:
        return 0.0
    return annualized_return(returns, periods_per_year) / mdd


def cvar(returns: Sequence[float], alpha: float = 0.95) -> float:
    """Conditional VaR (Expected Shortfall): mean of the worst (1−alpha) tail losses,
    returned as a POSITIVE fraction (0.08 = expect ~8% loss in the worst tail). The
    tail-risk measure institutions size against (beyond plain VaR). 0 if too few obs."""
    n = len(returns)
    if n < 5:
        return 0.0
    k = max(1, int(round((1 - alpha) * n)))
    worst = sorted(returns)[:k]                 # most negative returns
    tail = sum(worst) / len(worst)
    return max(0.0, -tail)                       # report loss as positive


def vol_target_size(capital: float, target_ann_vol: float, realized_ann_vol: float,
                    max_leverage: float = 1.0) -> float:
    """VOLATILITY TARGETING: notional to deploy so realized vol ≈ target. Scales DOWN
    in volatile regimes, UP in calm ones; capped at max_leverage × capital."""
    if realized_ann_vol <= 0 or capital <= 0:
        return 0.0
    lev = min(max_leverage, target_ann_vol / realized_ann_vol)
    return max(0.0, capital * lev)


def fractional_kelly(win_rate: float, avg_win: float, avg_loss: float,
                     fraction: float = 0.5) -> float:
    """FRACTIONAL KELLY bet fraction of capital. avg_loss as a POSITIVE number.
    full Kelly f* = p/|loss| - (1-p)/win  (per-unit payoff form); we return
    fraction×f*, clamped to [0,1]. Half-Kelly (0.5) is the practitioner standard
    (~75% of full-Kelly growth, far smaller drawdown). 0 if edge is non-positive."""
    if avg_win <= 0 or avg_loss <= 0 or not (0.0 <= win_rate <= 1.0):
        return 0.0
    b = avg_win / avg_loss                       # payoff ratio
    f_star = (win_rate * b - (1.0 - win_rate)) / b   # = p - (1-p)/b
    return max(0.0, min(1.0, fraction * f_star))


def summary(returns: Sequence[float], periods_per_year: int = 365) -> dict:
    """One-call performance/risk report for a per-period returns series."""
    eq = equity_curve(returns)
    return {
        "n": len(returns),
        "ann_return_pct": round(annualized_return(returns, periods_per_year) * 100, 2),
        "ann_vol_pct": round(annualized_vol(returns, periods_per_year) * 100, 2),
        "sharpe": round(sharpe(returns, 0.0, periods_per_year), 2),
        "sortino": round(sortino(returns, 0.0, periods_per_year), 2),
        "max_drawdown_pct": round(max_drawdown(eq) * 100, 2),
        "calmar": round(calmar(returns, periods_per_year), 2),
    }
