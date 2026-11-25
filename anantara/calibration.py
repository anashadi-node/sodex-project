#!/usr/bin/env python3
"""
ANANTARA SAKTI — probability calibration + Brier score (pure, stdlib-only, tested).

Adopted from the best honest idea in the NEXUS PRIME TITAN blueprint: a model's
raw "probability" is meaningless until it is CALIBRATED and validated empirically.
This is a TRUTH-TELLER, not an edge-maker — if a model has no edge, calibration
reveals it (probabilities collapse toward the base rate); it cannot manufacture
accuracy that isn't there. That honesty is exactly why it's worth having.

  • brier_score(probs, outcomes)        — mean squared error of probabilistic forecasts
                                          (0 = perfect, 0.25 = always-50%; lower better)
  • expected_calibration_error(...)     — ECE across bins (how far stated ≠ actual)
  • reliability_bins(...)               — calibration curve (stated vs actual per bin)
  • isotonic_fit(probs, outcomes)       — PAVA isotonic calibrator (pure stdlib)
  • apply_isotonic(fit, p)              — map a raw prob through the fitted calibrator

Use as the promotion-gate metric (challenger must improve Brier) and to report
honest reliability of Pre-Sentiment / FreqAI / SoDEX-model probabilities. Stdlib
only (no sklearn/numpy) to stay in the testable pure-core family.
"""
from __future__ import annotations
from typing import Sequence


def brier_score(probs: Sequence[float], outcomes: Sequence[int]) -> float:
    """Mean squared error between predicted prob and binary outcome (0/1)."""
    n = len(probs)
    if n == 0 or n != len(outcomes):
        return 0.0
    return sum((p - o) ** 2 for p, o in zip(probs, outcomes)) / n


def reliability_bins(probs: Sequence[float], outcomes: Sequence[int],
                     n_bins: int = 10) -> list[dict]:
    """Calibration curve: per probability-bin, the mean predicted prob vs the actual
    hit-rate. A well-calibrated model has predicted ≈ actual in every bin."""
    bins = [{"lo": i / n_bins, "hi": (i + 1) / n_bins, "n": 0,
             "sum_p": 0.0, "sum_o": 0.0} for i in range(n_bins)]
    for p, o in zip(probs, outcomes):
        idx = min(n_bins - 1, max(0, int(p * n_bins)))
        b = bins[idx]
        b["n"] += 1; b["sum_p"] += p; b["sum_o"] += o
    out = []
    for b in bins:
        if b["n"] > 0:
            out.append({"bin": f"{b['lo']:.1f}-{b['hi']:.1f}", "n": b["n"],
                        "predicted": round(b["sum_p"] / b["n"], 3),
                        "actual": round(b["sum_o"] / b["n"], 3)})
    return out


def expected_calibration_error(probs: Sequence[float], outcomes: Sequence[int],
                               n_bins: int = 10) -> float:
    """ECE: sample-weighted average |predicted − actual| across bins (0 = perfect)."""
    n = len(probs)
    if n == 0:
        return 0.0
    ece = 0.0
    for b in reliability_bins(probs, outcomes, n_bins):
        ece += (b["n"] / n) * abs(b["predicted"] - b["actual"])
    return round(ece, 4)


def _pava_weighted(values: list[float], weights: list[float]) -> list[float]:
    """Weighted Pool-Adjacent-Violators: monotone non-decreasing least-squares fit.

    Returns one fitted value PER INPUT NODE (standard isotonic regression output),
    so callers can map each unique x to its fitted y. Adjacent violators are pooled
    into a common weighted mean, but the pooled value is then expanded back across
    every node in the block — otherwise len(y) < len(x) and interpolation breaks.
    """
    # each block: [weighted_sum, weight, node_count]
    blocks: list[list[float]] = []
    for v, w in zip(values, weights):
        blocks.append([v * w, w, 1])
        while len(blocks) >= 2 and (blocks[-2][0] / blocks[-2][1]) >= (blocks[-1][0] / blocks[-1][1]):
            s2, w2, c2 = blocks.pop()
            s1, w1, c1 = blocks.pop()
            blocks.append([s1 + s2, w1 + w2, c1 + c2])
    out: list[float] = []
    for s, w, c in blocks:
        mean = s / w
        out.extend([mean] * int(c))
    return out


def isotonic_fit(probs: Sequence[float], outcomes: Sequence[int]) -> dict:
    """Fit an isotonic (monotone non-decreasing) calibration map from raw probs to
    empirical hit-rate. Aggregates by UNIQUE x first (correct handling of ties), then
    weighted PAVA. Returns {x, y} knots (one per unique raw prob, sorted by x)."""
    if not probs:
        return {"x": [], "y": []}
    from collections import defaultdict
    agg: dict[float, list[float]] = defaultdict(lambda: [0.0, 0.0])   # x -> [sum_y, count]
    for p, o in zip(probs, outcomes):
        a = agg[float(p)]; a[0] += float(o); a[1] += 1.0
    xs = sorted(agg)
    means = [agg[x][0] / agg[x][1] for x in xs]
    weights = [agg[x][1] for x in xs]
    return {"x": xs, "y": _pava_weighted(means, weights)}


def apply_isotonic(fit: dict, p: float) -> float:
    """Map a raw probability through the fitted isotonic calibrator (clamped [0,1])."""
    xs, ys = fit.get("x", []), fit.get("y", [])
    if not xs:
        return max(0.0, min(1.0, p))
    if p <= xs[0]:
        return max(0.0, min(1.0, ys[0]))
    if p >= xs[-1]:
        return max(0.0, min(1.0, ys[-1]))
    # linear interpolation between surrounding knots
    lo = 0
    for i in range(1, len(xs)):
        if xs[i] >= p:
            lo = i - 1
            break
    x0, x1, y0, y1 = xs[lo], xs[lo + 1], ys[lo], ys[lo + 1]
    if x1 == x0:
        return max(0.0, min(1.0, y0))
    return max(0.0, min(1.0, y0 + (y1 - y0) * (p - x0) / (x1 - x0)))


def report(probs: Sequence[float], outcomes: Sequence[int], n_bins: int = 10) -> dict:
    """One-call honest reliability report for a set of probabilistic forecasts."""
    base = sum(outcomes) / len(outcomes) if outcomes else 0.0
    return {
        "n": len(probs),
        "brier": round(brier_score(probs, outcomes), 4),
        "brier_baseline_alwaysbase": round(base * (1 - base), 4),  # Brier of always-base-rate
        "ece": expected_calibration_error(probs, outcomes, n_bins),
        "base_rate": round(base, 3),
        "bins": reliability_bins(probs, outcomes, n_bins),
    }
