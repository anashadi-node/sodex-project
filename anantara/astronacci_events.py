#!/usr/bin/env python3
"""
ASTRONACCI v1.0 — Event Study Engine

Jembatan antara klaim naratif dan bukti statistik. Menjawab pertanyaan:
"Sebelum dan sesudah event astronomis, apakah return, volatility, drawdown,
skew, atau reversal probability berubah secara signifikan dibanding baseline?"

DOKTRIN:
  Setiap event harus diuji sebelum menjadi sinyal trading. Tidak ada klaim
  yang diterima tanpa event-study yang terdokumentasi.

METODOLOGI (López de Prado / Fama):
  • Cumulative Abnormal Return (CAR) over event windows
  • Volatility ratio: post-event / pre-event
  • Turning-point hit rate vs matched random dates
  • Bootstrap confidence intervals (block bootstrap for time-series)
  • Multi-asset, multi-timeframe, multi-regime robustness

Stdlib-only (no numpy/scipy for core computation — uses pure Python math).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Callable, Sequence


# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EventWindow:
    """Result for a single event window analysis."""
    asset: str
    event_type: str         # new_moon, full_moon, mercury_retrograde, etc.
    event_date: str         # ISO date
    direction: str          # pre / post
    window_bars: int        # ±N bars from event
    n_samples: int

    # Return metrics
    mean_return: float
    median_return: float
    std_return: float
    skew_return: float
    cum_return: float       # CAR over window

    # Volatility
    realized_vol: float

    # Extreme moves
    max_adverse: float      # worst drawdown in window
    max_favorable: float    # best gain in window

    # vs Baseline
    vs_random_mean_diff: float
    vs_random_pvalue: float  # bootstrap p-value

    # Regime
    regime_tag: str = "all"


@dataclass
class EventStudyResult:
    """Aggregate result for an event type × asset × timeframe combination."""
    event_type: str
    asset: str
    timeframe: str
    n_events: int
    n_random_controls: int

    # Aggregate metrics
    car_mean: float         # mean CAR across all events
    volatility_ratio: float  # mean post/pre volatility ratio
    turning_point_hit_rate: float  # % events near swing high/low
    hit_rate_lift: float     # lift over random baseline
    directional_accuracy: float  # % correct direction prediction

    # Statistical significance
    bootstrap_ci_low: float
    bootstrap_ci_high: float
    p_value: float

    # Cost-adjusted
    car_after_cost: float
    sharpe_after_cost: float

    # Verdict
    passes_threshold: bool
    evidence_score: int      # 0-100


@dataclass
class StudyConfig:
    """Configuration for an event study run."""
    assets: list[str] = field(default_factory=lambda: ["BTC", "ETH", "SOL"])
    timeframes: list[str] = field(default_factory=lambda: ["Daily", "4H", "1H"])
    event_types: list[str] = field(default_factory=lambda: [
        "new_moon", "full_moon", "mercury_retrograde",
        "aspect_conjunction", "aspect_square", "aspect_opposition",
    ])
    pre_windows: list[int] = field(default_factory=lambda: [1, 3, 5, 10, 20])
    post_windows: list[int] = field(default_factory=lambda: [1, 3, 5, 10, 20])
    n_bootstrap: int = 1000
    confidence_level: float = 0.95
    min_n_events: int = 10     # minimum events needed for valid study
    cost_per_trade_bps: float = 5.0  # 5 bps (taker fee estimate)
    slippage_bps: float = 2.0  # 2 bps additional slippage


# ─────────────────────────────────────────────────────────────────────────────
# STATISTICAL HELPERS — use stdlib statistics module
# ponytail: was custom _mean/_std/_median/_skew, now stdlib statistics
# ─────────────────────────────────────────────────────────────────────────────
from statistics import mean as _mean, stdev as _std, pstdev as _pstdev, median as _median

def _skew(xs: Sequence[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    m = _mean(xs)
    s = _pstdev(xs)  # population std (ddof=0)
    if s == 0:
        return 0.0
    return sum(((x - m) / s) ** 3 for x in xs) / n


def _percentile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = (len(s) - 1) * p / 100.0
    f = int(k)
    c = k - f
    if f + 1 >= len(s):
        return s[-1]
    return s[f] + c * (s[f + 1] - s[f])


def _bootstrap_pvalue(
    observed: float, baseline_samples: list[float], alternative: str = "greater"
) -> float:
    """Bootstrap p-value: fraction of baseline samples more extreme than observed.

    alternative='greater': p = fraction where baseline >= observed (positive edge test)
    alternative='two-sided': p = fraction where |baseline| >= |observed|
    """
    n = len(baseline_samples)
    if n == 0:
        return 1.0
    if alternative == "greater":
        count = sum(1 for b in baseline_samples if b >= observed)
    elif alternative == "less":
        count = sum(1 for b in baseline_samples if b <= observed)
    else:  # two-sided
        abs_obs = abs(observed)
        count = sum(1 for b in baseline_samples if abs(b) >= abs_obs)
    return count / n


def _block_bootstrap(
    returns: list[float], n_samples: int, block_size: int = 5,
    seed: int | None = 42,
) -> list[float]:
    """Block bootstrap preserving temporal dependency structure.

    Args:
        returns: time series of returns
        n_samples: number of bootstrap samples to draw
        block_size: stationary-bootstrap block length
        seed: RNG seed for reproducibility (default 42 → deterministic). Uses
            a dedicated `random.Random` instance so the GLOBAL random state is
            never perturbed. Pass None for OS entropy (non-deterministic).

    Returns: list of n_samples bootstrapped mean returns.
    """
    n = len(returns)
    if n < block_size:
        return [_mean(returns)] * n_samples

    rng = random.Random(seed)
    n_blocks = n // block_size
    boot_means = []
    for _ in range(n_samples):
        # Sample blocks with replacement
        sampled = []
        while len(sampled) < n:
            block_start = rng.randint(0, n - block_size)
            sampled.extend(returns[block_start:block_start + block_size])
        boot_means.append(_mean(sampled[:n]))
    return boot_means


# ─────────────────────────────────────────────────────────────────────────────
# EVENT STUDY ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class EventStudyEngine:
    """Compute event studies for astronomical events on price data.

    Usage:
        engine = EventStudyEngine(config)
        result = engine.study_event(
            "new_moon", "BTC", "Daily",
            price_series, event_dates, random_dates,
        )
    """

    def __init__(self, config: StudyConfig | None = None):
        self.cfg = config or StudyConfig()

    def compute_window_metrics(
        self,
        price_series: list[float],
        event_idx: int,
        window_bars: int,
        is_post: bool = True,
    ) -> dict[str, float]:
        """Compute metrics for a single window around an event index.

        Returns dict with: mean_return, median_return, std_return, skew_return,
        cum_return, realized_vol, max_adverse, max_favorable.
        """
        n = len(price_series)
        if is_post:
            start = event_idx + 1
            end = min(event_idx + 1 + window_bars, n)
        else:
            start = max(0, event_idx - window_bars)
            end = event_idx

        if end <= start:
            return {
                "mean_return": 0.0, "median_return": 0.0, "std_return": 0.0,
                "skew_return": 0.0, "cum_return": 0.0, "realized_vol": 0.0,
                "max_adverse": 0.0, "max_favorable": 0.0,
            }

        window_prices = price_series[start:end]
        # Compute log returns
        returns = []
        for i in range(1, len(window_prices)):
            if window_prices[i - 1] > 0:
                returns.append(
                    math.log(window_prices[i] / window_prices[i - 1])
                )

        if not returns:
            return {
                "mean_return": 0.0, "median_return": 0.0, "std_return": 0.0,
                "skew_return": 0.0, "cum_return": 0.0, "realized_vol": 0.0,
                "max_adverse": 0.0, "max_favorable": 0.0,
            }

        # A single return has no measurable sample dispersion yet.
        std_return = _std(returns) if len(returns) > 1 else 0.0

        # CAR = cumulative log return over window
        car = sum(returns)
        # Realized vol = std of returns × sqrt(n_bars) annualized factor
        rvol = std_return * math.sqrt(len(returns))

        # Max adverse/favorable excursion
        cum = 0.0
        max_adv = 0.0
        max_fav = 0.0
        peak = 0.0
        trough = 0.0
        for r in returns:
            cum += r
            if cum > peak:
                peak = cum
            if cum < trough:
                trough = cum
            drawdown = peak - cum
            if drawdown > max_adv:
                max_adv = drawdown
            if cum - trough > max_fav:
                max_fav = cum - trough

        return {
            "mean_return": _mean(returns),
            "median_return": _median(returns),
            "std_return": std_return,
            "skew_return": _skew(returns),
            "cum_return": car,
            "realized_vol": rvol,
            "max_adverse": max_adv,
            "max_favorable": max_fav,
        }

    def study_single_event(
        self,
        event_type: str,
        asset: str,
        price_series: list[float],
        event_dates: list[int],    # indices into price_series
        random_dates: list[list[int]],  # n_bootstrap × [indices]
        regime_tags: list[str] | None = None,
    ) -> list[EventStudyResult]:
        """Run full event study for one event type × asset combination.

        Returns one result per timeframe (for daily, the timeframe is implicit
        in the price series).
        """
        results = []
        n_events = len(event_dates)
        n_random = len(random_dates) * len(random_dates[0]) if random_dates else 0

        if n_events < self.cfg.min_n_events:
            # Not enough events — return placeholder
            return [EventStudyResult(
                event_type=event_type, asset=asset, timeframe="N/A",
                n_events=n_events, n_random_controls=n_random,
                car_mean=0.0, volatility_ratio=1.0,
                turning_point_hit_rate=0.0, hit_rate_lift=0.0,
                directional_accuracy=0.0,
                bootstrap_ci_low=0.0, bootstrap_ci_high=0.0,
                p_value=1.0, car_after_cost=0.0, sharpe_after_cost=0.0,
                passes_threshold=False, evidence_score=0,
            )]

        # Compute event-window metrics
        event_cars: list[float] = []
        event_vol_ratios: list[float] = []
        event_hits: list[int] = []
        event_directions: list[int] = []

        for idx in event_dates:
            if idx <= 0 or idx >= len(price_series) - 1:
                continue

            # Post-event metrics
            post = self.compute_window_metrics(price_series, idx, 3, is_post=True)
            pre = self.compute_window_metrics(price_series, idx, 3, is_post=False)

            event_cars.append(post["cum_return"])

            # Volatility ratio
            if pre["realized_vol"] > 0:
                event_vol_ratios.append(
                    post["realized_vol"] / pre["realized_vol"]
                )
            else:
                event_vol_ratios.append(1.0)

            # Turning point hit: price at event is local max/min within ±3 bars
            event_price = price_series[idx]
            window_start = max(0, idx - 3)
            window_end = min(len(price_series), idx + 4)
            window = price_series[window_start:window_end]
            is_high = event_price >= max(window)
            is_low = event_price <= min(window)
            event_hits.append(1 if (is_high or is_low) else 0)

            # Directional: did price move in predicted direction post-event?
            # For lunar: full moon → expect reversal (opposite of pre-event trend)
            pre_trend = pre["cum_return"]
            post_trend = post["cum_return"]
            if abs(pre_trend) > 0.0001:
                event_directions.append(
                    1 if (pre_trend * post_trend < 0) else 0  # reversal
                )
            else:
                event_directions.append(0)

        # Compute random baseline metrics
        random_cars: list[float] = []
        random_hits: list[float] = []

        for boot_idx_list in random_dates:
            for ridx in boot_idx_list:
                if ridx <= 0 or ridx >= len(price_series) - 1:
                    continue
                post_r = self.compute_window_metrics(price_series, ridx, 3, is_post=True)
                random_cars.append(post_r["cum_return"])

                rprice = price_series[ridx]
                r_start = max(0, ridx - 3)
                r_end = min(len(price_series), ridx + 4)
                r_window = price_series[r_start:r_end]
                is_high_r = rprice >= max(r_window)
                is_low_r = rprice <= min(r_window)
                random_hits.append(1.0 if (is_high_r or is_low_r) else 0.0)

        # Aggregate metrics
        car_mean = _mean(event_cars)
        vol_ratio_mean = _mean(event_vol_ratios) if event_vol_ratios else 1.0
        tp_hit_rate = _mean([float(h) for h in event_hits]) if event_hits else 0.0
        random_hit_rate = _mean(random_hits) if random_hits else 0.0
        hit_rate_lift = (
            (tp_hit_rate - random_hit_rate) / random_hit_rate
            if random_hit_rate > 0 else 0.0
        )
        dir_acc = _mean([float(d) for d in event_directions]) if event_directions else 0.0

        # ── BASE-RATE AWARENESS (Dossier §11.2) ──
        # "~66% of ALL bars are already 'near a turning point' when using
        #  loose windows. Any date 'hits' — including random ones."
        base_rate = _compute_base_rate(price_series, window_bars=3, swing_order=5)
        base_rate_adjusted_lift = (
            (tp_hit_rate - base_rate) / base_rate if base_rate > 0 else 0.0
        )

        # Bootstrap p-value for CAR
        p_value = _bootstrap_pvalue(car_mean, random_cars, alternative="greater")

        # Bootstrap CI
        if len(event_cars) >= 10:
            boot_means = _block_bootstrap(event_cars, self.cfg.n_bootstrap)
            ci_low = _percentile(boot_means, (1 - self.cfg.confidence_level) * 100 / 2)
            ci_high = _percentile(boot_means, 100 - (1 - self.cfg.confidence_level) * 100 / 2)
        else:
            ci_low = car_mean
            ci_high = car_mean

        # Cost-adjusted
        cost_per_event = (self.cfg.cost_per_trade_bps + self.cfg.slippage_bps) / 10000.0
        car_after_cost = car_mean - cost_per_event

        # Sharpe (approximate)
        car_std = _std(event_cars) if len(event_cars) >= 2 else 0.01
        sharpe_after_cost = (
            car_after_cost / car_std * math.sqrt(n_events)
            if car_std > 0 else 0.0
        )

        # Evidence score (0-100)
        evidence = 0
        if p_value < 0.05:
            evidence += 30
        if car_after_cost > 0:
            evidence += 20
        if hit_rate_lift > 0.15:
            evidence += 15
        if dir_acc > 0.50:  # better than coin flip
            evidence += 10
        if sharpe_after_cost > 0:
            evidence += 10
        if n_events >= 20:
            evidence += 10
        if ci_low * ci_high >= 0:  # CI doesn't cross zero
            evidence += 5

        passes = evidence >= 50 and car_after_cost > 0 and p_value < 0.10

        return [EventStudyResult(
            event_type=event_type,
            asset=asset,
            timeframe="Daily",
            n_events=n_events,
            n_random_controls=n_random,
            car_mean=round(car_mean, 6),
            volatility_ratio=round(vol_ratio_mean, 4),
            turning_point_hit_rate=round(tp_hit_rate, 4),
            hit_rate_lift=round(hit_rate_lift, 4),
            directional_accuracy=round(dir_acc, 4),
            bootstrap_ci_low=round(ci_low, 6),
            bootstrap_ci_high=round(ci_high, 6),
            p_value=round(p_value, 4),
            car_after_cost=round(car_after_cost, 6),
            sharpe_after_cost=round(sharpe_after_cost, 4),
            passes_threshold=passes,
            evidence_score=min(100, evidence),
        )]

    def generate_random_dates(
        self, n_events: int, series_length: int, n_samples: int = 1000,
        seed: int | None = 42,
    ) -> list[list[int]]:
        """Generate matched random date indices for baseline comparison.

        Args:
            n_events: number of event indices per sample
            series_length: length of the price series (indices stay in-bounds)
            n_samples: number of baseline samples to generate
            seed: RNG seed for reproducibility (default 42 → deterministic).
                Uses a dedicated `random.Random` so the global state is never
                perturbed. The previous implementation used the global
                `random.randint` with no seed, making every event-study
                baseline (and thus every p-value/CI) non-reproducible.

        Returns n_samples lists, each with n_events random indices.
        """
        rng = random.Random(seed)
        result = []
        for _ in range(n_samples):
            indices = [
                rng.randint(5, series_length - 6)
                for _ in range(n_events)
            ]
            result.append(indices)
        return result

    def compute_turning_point_proximity(
        self,
        price_series: list[float],
        event_indices: list[int],
    ) -> list[float]:
        """For each event, compute how close it is to the nearest swing high/low.

        Returns list of distances in bars (0 = exactly at turning point).
        Lower = closer to actual turning point.
        """
        distances = []
        for idx in event_indices:
            if idx < 5 or idx >= len(price_series) - 5:
                continue

            event_price = price_series[idx]
            min_dist = float("inf")

            # Search ±10 bars for local extrema
            for offset in range(-10, 11):
                check_idx = idx + offset
                if check_idx < 2 or check_idx >= len(price_series) - 2:
                    continue
                p = price_series[check_idx]
                prev_p = price_series[check_idx - 1]
                next_p = price_series[check_idx + 1]
                # Local max
                if p >= prev_p and p >= next_p:
                    dist = abs(offset)
                    if dist < min_dist:
                        min_dist = dist
                # Local min
                if p <= prev_p and p <= next_p:
                    dist = abs(offset)
                    if dist < min_dist:
                        min_dist = dist

            if min_dist < float("inf"):
                distances.append(min_dist)

        return distances


# ─────────────────────────────────────────────────────────────────────────────
# BASE-RATE ANALYSIS (Dossier §11.2 — "Masalah base-rate")
# ─────────────────────────────────────────────────────────────────────────────

def _compute_base_rate(
    price_series: list[float],
    window_bars: int = 3,
    swing_order: int = 5,
) -> float:
    """Compute what fraction of ALL bars are 'near a turning point'.

    This is the critical base-rate insight from Astronacci Dossier §11.2:
    with loose windows (~66% of bars are near a swing point), ANY date
    'hits' — including random dates. This creates an illusion of accuracy.

    Returns: 0.0-1.0 fraction of bars within window_bars of a swing point.
    """
    n = len(price_series)
    if n < 2 * swing_order + 2:
        return 0.0

    # Find all swing points
    swing_indices = set()
    for i in range(swing_order, n - swing_order):
        window = price_series[i - swing_order:i + swing_order + 1]
        if price_series[i] == max(window) or price_series[i] == min(window):
            swing_indices.add(i)

    if not swing_indices:
        return 0.0

    # Count bars within window_bars of any swing point
    near_swing = 0
    for i in range(n):
        for sw in swing_indices:
            if abs(i - sw) <= window_bars:
                near_swing += 1
                break

    return near_swing / n


def base_rate_warning(
    hit_rate: float,
    base_rate: float,
    threshold: float = 0.60,
) -> dict:
    """Generate base-rate awareness warning.

    If base_rate > threshold, the hit_rate metric is unreliable because
    the target definition is too loose — almost any date 'hits'.

    Returns dict with warning level and explanation.
    """
    if base_rate > threshold:
        level = "CRITICAL"
        explanation = (
            f"Base rate ({base_rate:.1%}) is above {threshold:.0%}. "
            f"This means {base_rate*100:.0f}% of ALL bars are 'near a turning point'. "
            f"The hit_rate metric is UNRELIABLE — tighten your swing_order or window."
        )
    elif base_rate > 0.45:
        level = "WARNING"
        explanation = (
            f"Base rate ({base_rate:.1%}) is above 45%. "
            f"Hit rate should be interpreted with caution."
        )
    else:
        level = "OK"
        explanation = f"Base rate ({base_rate:.1%}) is acceptable."

    return {
        "base_rate": round(base_rate, 4),
        "hit_rate": round(hit_rate, 4),
        "lift_over_base_rate": round((hit_rate - base_rate) / base_rate if base_rate > 0 else 0.0, 4),
        "warning_level": level,
        "explanation": explanation,
    }


# ─────────────────────────────────────────────────────────────────────────────
# NEGATIVE CONTROL: SYNTHETIC RANDOM WALK (audit.py methodology)
# ─────────────────────────────────────────────────────────────────────────────

def generate_synthetic_prices(
    n_bars: int = 500,
    start_price: float = 100.0,
    mu: float = 0.0003,
    sigma: float = 0.012,
    seed: int = 42,
) -> list[float]:
    """Generate synthetic price series (geometric Brownian motion).

    This is the NEGATIVE CONTROL from audit.py: a random walk with NO
    relationship to any planet. If your system 'finds' an astro edge here,
    it's noise/overfit — not a real signal.

    Usage:
        synthetic = generate_synthetic_prices(500)
        study = engine.study_single_event("new_moon", "BTC", synthetic, ...)
        # If evidence_score > 0 on synthetic, your methodology is broken
    """
    random.seed(seed)
    prices = [start_price]
    for _ in range(n_bars - 1):
        r = random.gauss(mu, sigma)
        prices.append(prices[-1] * (1.0 + r))
    return prices


def negative_control_check(
    event_type: str,
    asset: str,
    event_dates: list[int],
    n_bars: int = 500,
    n_bootstrap: int = 500,
    seed: int = 7,
) -> dict:
    """Run event study on synthetic random-walk data.

    This SHOULD find NO edge. If it does, the methodology is overfitting.

    Returns dict with synthetic study results and verdict.
    """
    from astronacci_events import EventStudyEngine, StudyConfig

    synthetic = generate_synthetic_prices(n_bars, seed=seed)

    # Filter event dates to fit synthetic series
    valid_events = [i for i in event_dates if 10 <= i < n_bars - 10]

    if len(valid_events) < 10:
        return {
            "verdict": "INSUFFICIENT_DATA",
            "explanation": f"Only {len(valid_events)} valid events for synthetic test",
            "evidence_on_synthetic": 0,
        }

    config = StudyConfig(n_bootstrap=n_bootstrap, min_n_events=5)
    engine = EventStudyEngine(config)
    random_dates = engine.generate_random_dates(
        len(valid_events), n_bars, n_bootstrap,
    )
    results = engine.study_single_event(
        event_type, asset, synthetic, valid_events, random_dates,
    )

    evidence = results[0].evidence_score if results else 0

    if evidence > 20:
        verdict = "FAIL — Methodology overfitting"
        explanation = (
            f"Found evidence={evidence}/100 on RANDOM WALK data. "
            f"This means your event detection or statistical tests are "
            f"too loose. Tighten parameters before testing on real data."
        )
    elif evidence > 5:
        verdict = "WEAK — Marginal noise"
        explanation = (
            f"Marginal evidence ({evidence}/100) on synthetic. "
            f"Likely noise but worth monitoring."
        )
    else:
        verdict = "PASS — No false edge on noise"
        explanation = (
            f"No evidence ({evidence}/100) on random walk. "
            f"Methodology passes negative control."
        )

    return {
        "verdict": verdict,
        "explanation": explanation,
        "evidence_on_synthetic": evidence,
        "synthetic_n_bars": n_bars,
        "synthetic_n_events": len(valid_events),
    }

def run_full_study(
    event_dates_map: dict[str, dict[str, list[int]]],
    price_data: dict[str, list[float]],
    config: StudyConfig | None = None,
) -> dict[str, list[EventStudyResult]]:
    """Run event study across all event types × assets.

    Args:
        event_dates_map: {event_type: {asset: [indices]}}
        price_data: {asset: [prices]}
        config: StudyConfig or defaults

    Returns:
        {event_type: [EventStudyResult, ...]}
    """
    cfg = config or StudyConfig()
    engine = EventStudyEngine(cfg)
    all_results: dict[str, list[EventStudyResult]] = {}

    for event_type in cfg.event_types:
        all_results[event_type] = []
        for asset in cfg.assets:
            prices = price_data.get(asset, [])
            event_indices = event_dates_map.get(event_type, {}).get(asset, [])

            if len(prices) < 50 or len(event_indices) < cfg.min_n_events:
                continue

            random_dates = engine.generate_random_dates(
                len(event_indices), len(prices), cfg.n_bootstrap,
            )

            results = engine.study_single_event(
                event_type, asset, prices, event_indices, random_dates,
            )
            all_results[event_type].extend(results)

    return all_results


# ─────────────────────────────────────────────────────────────────────────────
# SELF-TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import random as _random
    _random.seed(42)

    # Generate synthetic price data
    n = 500
    prices = [100.0]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1.0 + _random.gauss(0.0, 0.02)))

    # Generate synthetic event dates
    event_dates = [_random.randint(20, n - 21) for _ in range(30)]

    config = StudyConfig(
        assets=["BTC"], timeframes=["Daily"],
        event_types=["new_moon"], n_bootstrap=200,
    )
    engine = EventStudyEngine(config)
    random_dates = engine.generate_random_dates(30, n, 200)
    results = engine.study_single_event(
        "new_moon", "BTC", prices, event_dates, random_dates,
    )

    for r in results:
        print(f"=== Event Study: {r.event_type} × {r.asset} ===")
        print(f"  N events: {r.n_events}")
        print(f"  CAR mean: {r.car_mean:.6f}")
        print(f"  Vol ratio: {r.volatility_ratio:.4f}")
        print(f"  TP hit rate: {r.turning_point_hit_rate:.4f} "
              f"(lift: {r.hit_rate_lift:+.4f})")
        print(f"  Directional acc: {r.directional_accuracy:.4f}")
        print(f"  Bootstrap CI: [{r.bootstrap_ci_low:.6f}, {r.bootstrap_ci_high:.6f}]")
        print(f"  p-value: {r.p_value:.4f}")
        print(f"  CAR after cost: {r.car_after_cost:.6f}")
        print(f"  Sharpe after cost: {r.sharpe_after_cost:.4f}")
        print(f"  Evidence score: {r.evidence_score}/100")
        print(f"  PASSES: {r.passes_threshold}")
