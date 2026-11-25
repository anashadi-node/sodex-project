#!/usr/bin/env python3
"""
ANANTARA SAKTI — CEX Target Framework (v1.0, 2026-08-21)
=======================================================
The PROJECT TARGET IS FIXED and unchanged: >=0.7% per swing cycle (1-30h) of
TOTAL wallet capital, with 24/7 deep-loop learning (North Star). This module is
NOT a target replacement — it is the professional-grade scientific machinery to
PURSUE that ambitious target honestly: measure real progress toward it, and get
there without the two failure modes a hard target invites — (a) an optimizer
overfitting parameters until a backtest merely LOOKS like it hits the number, and
(b) leverage-chasing that blows up capital. (Risk-science distilled from the
0.8%-audit learning doc + López de Prado + Kelly literature.)

  Rule 1 — Expectancy gate (not raw probability): trade only if net E clears a
           floor AND >=80% of the bootstrap expectancy distribution is above zero.
  Rule 2 — Track progress on a per-MONTH cadence too, so the system can WAIT for
           good setups instead of forcing bad trades when signals are sparse —
           while still driving toward the fixed per-cycle North Star.
  Rule 3 — Size in R (vol units), translate to dollars last.  [see cex_har_rv]
  Rule 4 — Leverage capped + half-Kelly (an over-estimated edge is assumed, so
           the safe fraction is halved before the cap).
  Rule 5 — Drawdown declared upfront HALTS the system; no code path raises
           leverage to chase losses.
  Rule 6 — Wald SPRT decides GO/NO-GO on real edge, not a lucky win streak.

Pure stdlib + math. Deterministic. Unit-tested. Used by the deep-loop to turn
raw beta-inflated WR into a principled, overfitting-resistant read on progress
toward the fixed North Star.
"""
from __future__ import annotations

import math
import random

# ── Rule 1: expectancy gate ───────────────────────────────────────────────────
# F6 FIX (audit 2026-09-01): single source of truth for the North Star target.
# Masterplan §1: PROFIT MINIMAL 0,7% dari MODAL per swing cycle (1-30h).
# Imported by cex_profitability_tracker.py so every module grades against the
# SAME number (was 0.5% in the tracker with a wrong "Astronacci CEX" label).
NORTH_STAR_TARGET = 0.008  # ≥0.8% of total wallet per 30h cycle (canonical, user GO 27-Sep-2026)
ROUNDTRIP_COST = 0.001     # M1 FIX: 0.05%/side futures taker × 2 (was 0.002 spot)
MIN_NET_E = 0.0008         # +0.08% net expectancy floor (audit rule 1)
BOOT_FRAC = 0.80              # 80% of bootstrap means must be > 0
_BOOT_B = 2000


def net_expectancy(p: float, win: float, loss: float,
                   cost: float = ROUNDTRIP_COST) -> float:
    """E = p·W − (1−p)·L − cost. win/loss/cost as positive fractions."""
    return p * win - (1.0 - p) * loss - cost


def _boot_frac_above_zero(xs: list[float], b: int = _BOOT_B,
                          seed: int = 20260821) -> float:
    if not xs:
        return 0.0
    rng = random.Random(seed)
    n = len(xs)
    hits = 0
    for _ in range(b):
        s = sum(xs[rng.randrange(n)] for _ in range(n))
        if s > 0:
            hits += 1
    return hits / b


def expectancy_gate(pnls: list[float], min_e: float = MIN_NET_E,
                    boot_frac: float = BOOT_FRAC) -> dict:
    """Rule 1. pnls already net of cost (fractions). Gate passes only if the
    mean clears the floor AND the bootstrap is >=boot_frac above zero."""
    n = len(pnls)
    if n == 0:
        return {"pass": False, "mean_e": 0.0, "frac_above_0": 0.0, "n": 0}
    mean_e = sum(pnls) / n
    frac = _boot_frac_above_zero(pnls)
    return {"pass": bool(mean_e > min_e and frac >= boot_frac),
            "mean_e": round(mean_e, 6), "frac_above_0": round(frac, 3), "n": n}


# ── Rule 4: Kelly / leverage cap ──────────────────────────────────────────────
LEV_CAP = 1.5                 # hard leverage ceiling (audit rule 4)
KELLY_SAFETY = 0.5            # half-Kelly, then the cap


def kelly_fraction(mu: float, sigma: float) -> float:
    """Full-Kelly leverage f* = μ/σ² for log-growth (per-cycle μ, σ)."""
    if sigma <= 0:
        return 0.0
    return mu / (sigma * sigma)


def capped_leverage(mu: float, sigma: float, cap: float = LEV_CAP,
                    safety: float = KELLY_SAFETY) -> float:
    """Rule 4: min(cap, safety·Kelly), never negative. Edge is assumed
    over-estimated, so safety halves it before the hard cap applies."""
    return max(0.0, min(cap, safety * kelly_fraction(mu, sigma)))


def log_growth_rate(f: float, mu: float, sigma: float) -> float:
    """g(f) = f·μ − (f·σ)²/2 — the quantity leverage actually maximizes.
    Demonstrates why over-leverage destroys growth (g falls past Kelly)."""
    return f * mu - (f * sigma) ** 2 / 2.0


# ── Rule 2: per-month target ──────────────────────────────────────────────────
CYCLES_PER_DAY = 1.6          # 12-30h horizon ≈ 1.6 cycles/day (audit)
TARGET_MONTH_LO = 0.03
TARGET_MONTH_HI = 0.05


def monthly_projection(mean_e_per_cycle: float,
                       cycles_per_day: float = CYCLES_PER_DAY) -> dict:
    """Rule 2: project achieved per-cycle expectancy to a monthly figure — a
    progress diagnostic toward the fixed North Star (>=0.7%/cycle). The 3-5%/mo
    band flags healthy interim progress; it does not replace the target."""
    cycles_month = cycles_per_day * 30.0
    monthly = (1.0 + mean_e_per_cycle) ** cycles_month - 1.0
    if monthly >= TARGET_MONTH_LO:
        grade = "ON_TARGET" if monthly <= TARGET_MONTH_HI * 3 else "SUSPICIOUS_HIGH"
    elif monthly > 0:
        grade = "POSITIVE_BELOW_TARGET"
    else:
        grade = "NEGATIVE"
    return {"monthly_pct": round(monthly * 100, 3),
            "annual_pct": round(((1 + mean_e_per_cycle) ** (cycles_per_day * 365) - 1) * 100, 1),
            "grade": grade, "cycles_month": round(cycles_month, 1)}


# ── Rule 5: drawdown halt ─────────────────────────────────────────────────────
MAX_DD = 0.08                 # 8% max drawdown halts the system (audit rule 5)


def drawdown_halt(equity_curve: list[float], max_dd: float = MAX_DD) -> dict:
    """Rule 5: current drawdown from running peak; halt=True when it breaches."""
    if not equity_curve:
        return {"halt": False, "dd": 0.0, "peak": 0.0}
    peak = equity_curve[0]
    dd = 0.0
    for v in equity_curve:
        peak = max(peak, v)
        if peak > 0:
            dd = min(dd, v / peak - 1.0)
    return {"halt": bool(-dd >= max_dd), "dd": round(dd, 4), "peak": round(peak, 4)}


# ── Rule 6: Wald SPRT ─────────────────────────────────────────────────────────
def wald_sprt(successes: int, n: int, p0: float = 0.50, p1: float = 0.58,
              alpha: float = 0.05, beta: float = 0.05) -> dict:
    """Rule 6: sequential probability ratio test for a Bernoulli edge.
    H0: success prob = p0 (no edge)  vs  H1: = p1 (edge).
    Returns ACCEPT_EDGE / REJECT_EDGE / CONTINUE — decides when to stop with
    controlled error, instead of trusting an early win streak."""
    if n <= 0 or not (0 < p0 < 1 and 0 < p1 < 1):
        return {"decision": "CONTINUE", "llr": 0.0, "n": n}
    s = max(0, min(successes, n))
    llr = (s * math.log(p1 / p0)
           + (n - s) * math.log((1 - p1) / (1 - p0)))
    upper = math.log((1 - beta) / alpha)      # accept H1 (edge)
    lower = math.log(beta / (1 - alpha))      # accept H0 (no edge)
    if llr >= upper:
        decision = "ACCEPT_EDGE"
    elif llr <= lower:
        decision = "REJECT_EDGE"
    else:
        decision = "CONTINUE"
    return {"decision": decision, "llr": round(llr, 3),
            "upper": round(upper, 3), "lower": round(lower, 3), "n": n}


# ── self-check ────────────────────────────────────────────────────────────────
def demo() -> None:
    # Rule 1: a coin-flip after cost fails; a real edge passes.
    assert expectancy_gate([-0.002] * 10)["pass"] is False
    assert expectancy_gate([0.02] * 40)["pass"] is True
    # Rule 4: capped never exceeds cap; Kelly is the growth-max; over-leverage
    # past the zero point (2·Kelly≈6.17x here) is outright negative growth.
    _mu, _sig = 0.001, 0.018
    assert capped_leverage(_mu, _sig) <= LEV_CAP
    _k = kelly_fraction(_mu, _sig)                      # ≈ 3.09
    assert log_growth_rate(_k, _mu, _sig) >= log_growth_rate(1, _mu, _sig)
    assert log_growth_rate(_k, _mu, _sig) >= log_growth_rate(5, _mu, _sig)
    assert log_growth_rate(10, _mu, _sig) < 0          # over-leverage → ruin
    # Rule 5: 8%+ drop halts
    assert drawdown_halt([100, 108, 99])["halt"] is True
    assert drawdown_halt([100, 101, 100.5])["halt"] is False
    # Rule 6: overwhelming wins → ACCEPT_EDGE; overwhelming losses → REJECT_EDGE
    assert wald_sprt(60, 70)["decision"] == "ACCEPT_EDGE"
    assert wald_sprt(20, 70)["decision"] == "REJECT_EDGE"
    assert wald_sprt(3, 5)["decision"] == "CONTINUE"
    # Rule 2: tiny per-cycle edge projects to a sane monthly figure
    mp = monthly_projection(0.001)
    assert mp["monthly_pct"] > 0
    print("cex_target_framework demo OK:", mp)


if __name__ == "__main__":
    demo()
