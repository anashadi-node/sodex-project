#!/usr/bin/env python3
"""
ASTRONACCI v1.0 — Feature Engineering (Layers 1-7)

Mengubah data astro mentah menjadi fitur numerik yang bisa diuji secara statistik.

DOKTRIN:
  Fitur astro paling masuk akal BUKAN sebagai penyebab harga, tetapi sebagai
  KALENDER PERHATIAN MANUSIA. Karena itu fitur terbaik bukan "Mars square Jupiter"
  melainkan "Mars square Jupiter × attention spike × volatility regime".

PRINSIP:
  • Semua fitur continuous, normalized — tidak ada encoding ordinal/one-hot
  • Sin/cos untuk semua data sirkular (longitude, lunar phase)
  • Fitur interaksi: astro × attention × regime
  • Lookahead-free: setiap fitur hanya menggunakan data yang tersedia saat itu
  • Semua fitur ditag dengan layer epistemik asalnya

Stdlib-only untuk komputasi fitur. Skyfield dibutuhkan untuk ephemeris input.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from astronacci_ephemeris import (
    EphemerisSnapshot,
    compute_astro_features,
    aspect_proximity,
    ASPECTS, ASPECT_ORB,
)


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE TAG SYSTEM
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FeatureTag:
    """Metadata for every feature: epistemological layer + evidence status."""
    name: str
    layer: int          # 1-7 (Astronomi=1, ..., Behavioral=7)
    layer_name: str
    evidence_score: int = 0       # 0-100
    evidence_status: str = "unvalidated"  # rejected/weak/moderate/strong/production
    description: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class AstronacciFeatureEngine:
    """Build feature vectors from ephemeris + market + attention data.

    Usage:
        engine = AstronacciFeatureEngine()
        features = engine.build(snapshot, market_data, attention_data)
    """

    @staticmethod
    def build_astro_layer(snap: EphemerisSnapshot) -> dict[str, float]:
        """Layer 1: Pure astronomical features.

        These are deterministic, verifiable, and independent of market data.
        Valid as input features regardless of predictive power.
        """
        return compute_astro_features(snap)

    @staticmethod
    def build_market_layer(
        ohlcv: dict[str, float],
    ) -> dict[str, float]:
        """Layer 5: Conventional technical analysis features.

        Input: single-bar OHLCV dict with keys:
            open, high, low, close, volume, atr, rsi, adx, vwap
        """
        f: dict[str, float] = {}

        # Momentum
        for field in ["rsi", "adx"]:
            f[field] = ohlcv.get(field, 0.0)

        # Volatility
        close = ohlcv.get("close", 0.0)
        atr = ohlcv.get("atr", 0.0)
        if close > 0:
            f["atr_pct"] = atr / close
            f["hl_range"] = (ohlcv.get("high", close) - ohlcv.get("low", close)) / close

        # Distance to VWAP
        vwap = ohlcv.get("vwap", 0.0)
        if vwap > 0 and close > 0:
            f["dist_to_vwap"] = (close - vwap) / vwap

        # Volume
        volume = ohlcv.get("volume", 0.0)
        avg_volume = ohlcv.get("avg_volume", volume)
        if avg_volume > 0:
            f["volume_ratio"] = volume / avg_volume

        # Distance to nearest Fibonacci level (if provided)
        for fib_key in ["fib_382", "fib_500", "fib_618", "fib_786"]:
            fib_val = ohlcv.get(fib_key, 0.0)
            if fib_val > 0 and close > 0:
                f[f"dist_{fib_key}"] = (close - fib_val) / close

        return f

    @staticmethod
    def build_regime_layer(
        regime: dict[str, float],
    ) -> dict[str, float]:
        """Layer 6: Macro & regime features.

        Input: dict with keys like:
            dxy, real_yield, nominal_yield, fed_rate_exp, vix, btc_dominance,
            funding_rate, stablecoin_liquidity, cpi_flag, fomc_flag, nfp_flag
        """
        f: dict[str, float] = {}
        for key in [
            "dxy", "real_yield", "nominal_yield", "fed_rate_exp",
            "vix", "btc_dominance", "funding_rate", "stablecoin_liquidity",
        ]:
            f[key] = regime.get(key, 0.0)

        # Event flags
        for flag in ["cpi_flag", "fomc_flag", "nfp_flag"]:
            f[flag] = float(regime.get(flag, 0))

        return f

    @staticmethod
    def build_attention_layer(
        attention: dict[str, float],
    ) -> dict[str, float]:
        """Layer 7: Behavioral attention features.

        Input: dict with keys like:
            google_trends_score, news_volume, social_velocity,
            sentiment_polarity, wikipedia_traffic, attention_shock
        """
        f: dict[str, float] = {}
        for key in [
            "google_trends_score", "news_volume", "social_velocity",
            "sentiment_polarity", "wikipedia_traffic", "attention_shock",
        ]:
            f[key] = attention.get(key, 0.0)
        return f

    @staticmethod
    def build_interaction_features(
        astro: dict[str, float],
        attention: dict[str, float],
        regime: dict[str, float],
    ) -> dict[str, float]:
        """Build astro × attention × regime interaction features.

        The most scientifically plausible feature class: astro events only
        matter when attention is high and regime is conducive.
        """
        f: dict[str, float] = {}

        attn_shock = attention.get("attention_shock", 0.0)
        attn_score = attention.get("google_trends_score", 0.0)
        funding = regime.get("funding_rate", 0.0)

        # Lunar × attention
        f["lunar_illum_x_attention"] = (
            astro.get("lunar_illumination", 0.0) * attn_score
        )
        f["days_to_full_x_attention"] = (
            astro.get("lunar_days_to_full", 0.0) * attn_shock
        )

        # Aspect × attention × volatility regime
        for asp_name in ["conjunction", "square", "opposition"]:
            asp_max = astro.get(f"aspect_{asp_name}_max", 0.0)
            f[f"aspect_{asp_name}_x_attention"] = asp_max * attn_score
            f[f"aspect_{asp_name}_x_attention_x_funding"] = (
                asp_max * attn_score * (1.0 + abs(funding))
            )

        # Retrograde × attention
        retro_count = astro.get("retrograde_count", 0.0)
        f["retrograde_x_attention"] = retro_count * attn_score

        # Cluster density × attention
        cluster = astro.get("planet_cluster_density", 0.0)
        f["cluster_density_x_attention"] = cluster * attn_score

        return f

    def build(
        self,
        snap: EphemerisSnapshot,
        ohlcv: Optional[dict[str, float]] = None,
        regime: Optional[dict[str, float]] = None,
        attention: Optional[dict[str, float]] = None,
    ) -> dict[str, float]:
        """Build complete feature vector.

        All inputs except snap are optional — missing layers produce zeros.
        """
        features: dict[str, float] = {}

        # Layer 1: Astro (always available)
        features.update(self.build_astro_layer(snap))

        # Layer 5: Technical
        if ohlcv:
            features.update(self.build_market_layer(ohlcv))

        # Layer 6: Regime
        if regime:
            features.update(self.build_regime_layer(regime))

        # Layer 7: Attention
        if attention:
            features.update(self.build_attention_layer(attention))

        # Interaction terms
        if attention and regime:
            astro = self.build_astro_layer(snap)
            features.update(
                self.build_interaction_features(astro, attention, regime)
            )

        return features

    @staticmethod
    def feature_tags() -> list[FeatureTag]:
        """Return metadata for all known features."""
        tags = []

        # Layer 1
        for name in [
            "lunar_phase_sin", "lunar_phase_cos", "lunar_illumination",
            "lunar_distance_km", "lunar_declination", "lunar_sun_moon_sep",
            "lunar_days_to_new", "lunar_days_to_full",
        ]:
            tags.append(FeatureTag(name, 1, "Astronomy", description="Lunar state"))

        for planet in ["Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune"]:
            for suffix in ["lon_sin", "lon_cos", "retrograde", "distance_au", "declination"]:
                tags.append(FeatureTag(
                    f"{planet}_{suffix}", 1, "Astronomy",
                    description=f"Planetary position: {planet}"
                ))

        for asp in ASPECTS:
            tags.append(FeatureTag(f"aspect_{asp}_max", 1, "Astronomy"))
            tags.append(FeatureTag(f"aspect_{asp}_count", 1, "Astronomy"))

        tags.append(FeatureTag("planet_cluster_density", 1, "Astronomy"))
        tags.append(FeatureTag("retrograde_count", 1, "Astronomy"))

        # Layer 5
        for name in ["rsi", "adx", "atr_pct", "hl_range", "dist_to_vwap",
                      "volume_ratio", "dist_fib_382", "dist_fib_500",
                      "dist_fib_618", "dist_fib_786"]:
            tags.append(FeatureTag(name, 5, "Technical Analysis"))

        # Layer 6
        for name in ["dxy", "real_yield", "nominal_yield", "fed_rate_exp",
                      "vix", "btc_dominance", "funding_rate",
                      "stablecoin_liquidity"]:
            tags.append(FeatureTag(name, 6, "Macro"))

        # Layer 7
        for name in ["google_trends_score", "news_volume", "social_velocity",
                      "sentiment_polarity", "wikipedia_traffic",
                      "attention_shock"]:
            tags.append(FeatureTag(name, 7, "Behavioral"))

        # Interaction
        for name in [
            "lunar_illum_x_attention", "days_to_full_x_attention",
            "aspect_conjunction_x_attention", "aspect_square_x_attention",
            "aspect_opposition_x_attention",
            "aspect_conjunction_x_attention_x_funding",
            "aspect_square_x_attention_x_funding",
            "aspect_opposition_x_attention_x_funding",
            "retrograde_x_attention", "cluster_density_x_attention",
        ]:
            tags.append(FeatureTag(name, 0, "Interaction"))

        return tags


# ─────────────────────────────────────────────────────────────────────────────
# FIBONACCI LEVELS (Layer 4)
# ─────────────────────────────────────────────────────────────────────────────

def compute_fibonacci_levels(
    swing_high: float, swing_low: float,
) -> dict[str, float]:
    """Compute Fibonacci retracement levels between swing high and low.

    Returns: 0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0 levels.
    """
    diff = swing_high - swing_low
    return {
        "fib_000": swing_low,
        "fib_236": swing_low + 0.236 * diff,
        "fib_382": swing_low + 0.382 * diff,
        "fib_500": swing_low + 0.500 * diff,
        "fib_618": swing_low + 0.618 * diff,
        "fib_786": swing_low + 0.786 * diff,
        "fib_1000": swing_high,
    }


def distance_to_fib(
    price: float, fib_levels: dict[str, float],
) -> dict[str, float]:
    """Compute normalized distance from price to each Fibonacci level."""
    result = {}
    for key, level in fib_levels.items():
        if level > 0:
            result[f"dist_{key}"] = (price - level) / price
    return result


# ─────────────────────────────────────────────────────────────────────────────
# SELF-TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from astronacci_ephemeris import EphemerisEngine

    engine = EphemerisEngine()
    now = datetime.now(timezone.utc)
    snap = engine.compute(now)

    fe = AstronacciFeatureEngine()
    features = fe.build(
        snap,
        ohlcv={
            "open": 90000, "high": 91000, "low": 89500, "close": 90500,
            "volume": 1_200_000, "avg_volume": 1_000_000,
            "atr": 800, "rsi": 55, "adx": 25, "vwap": 90100,
        },
        regime={
            "dxy": 104.5, "real_yield": 2.1, "funding_rate": 0.0001,
            "btc_dominance": 52.3, "fomc_flag": 0,
        },
        attention={
            "google_trends_score": 0.35,
            "news_volume": 0.5,
            "sentiment_polarity": 0.12,
            "attention_shock": 0.1,
        },
    )

    print(f"=== Astronacci Feature Vector ({len(features)} features) ===")
    for k, v in sorted(features.items()):
        print(f"  {k}: {v:.6f}")
