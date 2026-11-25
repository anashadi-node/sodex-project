#!/usr/bin/env python3
"""
ASTRONACCI v1.1 — Data Pipeline (OHLCV + Ephemeris Ingestion)

Fetches market data from Binance public API (no auth needed) or Hyperliquid
info endpoint, aligns it with ephemeris snapshots, and builds the combined
astro-market dataset ready for the Event Study Engine and Statistical Defense.

DATA HYGIENE (from Falsification Lab §05):
  • Lookahead-free: ephemeris computed BEFORE market data is known
  • UTC-aligned: all timestamps in UTC, consistent across venues
  • Point-in-time: ephemeris at bar OPEN, not close
  • Survivorship-free: uses current universe, no historical selection bias
  • Reproducible: same dates always give same ephemeris (deterministic)

PIPELINE:
  1. Fetch OHLCV from Binance public klines (no API key needed)
  2. Compute ephemeris at each bar's timestamp
  3. Compute astro features for each bar
  4. Save combined dataset to data/astronacci/
  5. Ready for EventStudyEngine.run_full_study()

Stdlib + httpx + skyfield. No API key needed for public endpoints.
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

from astronacci_ephemeris import (
    EphemerisEngine, EphemerisSnapshot, compute_astro_features,
)
from astronacci_features import AstronacciFeatureEngine

log = logging.getLogger("anantara.astronacci.pipeline")


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

BINANCE_KLINE_URL = "https://api.binance.com/api/v3/klines"
BINANCE_FAPI_KLINE_URL = "https://fapi.binance.com/fapi/v1/klines"  # v3.3: perp-only fallback (HYPE/LIT etc.)
HL_INFO_URL = "https://api.hyperliquid.xyz/info"

# Binance symbol mapping (Anantara format -> Binance format)
# v3.3 (audit 2026-09-04, operator approved): expanded to the SoDEX radar
# 18-asset focus (scripts/paper_test_swing.py PAIRS) + CEX-Binance whitelist
# core. All verified present on Binance USDT-M perp (fapi exchangeInfo, read).
SYMBOL_MAP = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT",
    "HYPE": "HYPEUSDT", "BNB": "BNBUSDT", "XRP": "XRPUSDT",
    "DOGE": "DOGEUSDT", "BCH": "BCHUSDT", "ONDO": "ONDOUSDT",
    "LINK": "LINKUSDT", "AAVE": "AAVEUSDT", "SUI": "SUIUSDT",
    "UNI": "UNIUSDT", "TRX": "TRXUSDT", "ENA": "ENAUSDT",
    "ASTER": "ASTERUSDT", "PUMP": "PUMPUSDT", "LIT": "LITUSDT",
    "ARB": "ARBUSDT", "LTC": "LTCUSDT",
}

# Interval mapping
INTERVAL_MAP = {
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "15m": "15m",
}


# ─────────────────────────────────────────────────────────────────────────────
# DATA PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MarketBar:
    """One OHLCV bar aligned with ephemeris features."""
    timestamp: str          # ISO UTC
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trades: int

    # Astro features (computed after fetch)
    astro_features: dict[str, float] = field(default_factory=dict)


@dataclass
class AstroMarketDataset:
    """Complete astro-market dataset for one symbol + timeframe."""
    symbol: str
    timeframe: str
    bars: list[MarketBar]
    feature_names: list[str]
    n_bars: int
    date_range: str

    def to_dicts(self) -> list[dict]:
        """Convert to list of dicts for JSON/CSV export."""
        result = []
        for bar in self.bars:
            d = {
                "timestamp": bar.timestamp,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "quote_volume": bar.quote_volume,
                "trades": bar.trades,
            }
            d.update(bar.astro_features)
            result.append(d)
        return result

    def price_series(self) -> list[float]:
        """Return close prices for event study input."""
        return [b.close for b in self.bars]

    def returns_series(self) -> list[float]:
        """Return log returns for statistical testing."""
        prices = self.price_series()
        rets = []
        for i in range(1, len(prices)):
            if prices[i - 1] > 0:
                rets.append(math.log(prices[i] / prices[i - 1]))
        return rets


class AstroDataPipeline:
    """Fetch OHLCV + compute ephemeris features.

    Usage:
        pipeline = AstroDataPipeline()
        dataset = pipeline.fetch("BTC", "1d", days=365)
        dataset.bars[0].astro_features  # {lunar_phase_sin: ..., ...}
    """

    def __init__(
        self,
        output_dir: str | None = None,
        ephemeris_dir: str = "/tmp/skyfield",
    ):
        if output_dir is None:
            project_dir = os.environ.get(
                "ANANTARA_DIR", str(Path.home() / "anantara-sakti")
            )
            output_dir = str(Path(project_dir) / "data" / "astronacci")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ephemeris = EphemerisEngine(ephemeris_dir=ephemeris_dir)
        self.feature_engine = AstronacciFeatureEngine()

    def fetch_ohlcv_binance(
        self,
        symbol: str,
        interval: str,
        days: int = 365,
        end_time: datetime | None = None,
    ) -> list[MarketBar]:
        """Fetch OHLCV klines from Binance public API.

        Args:
            symbol: "BTC", "ETH", "SOL" (Anantara format)
            interval: "1h", "4h", "1d", "15m"
            days: Number of days of history
            end_time: End datetime (default: now)

        Returns:
            List of MarketBar without astro features (fill later).
        """
        if httpx is None:
            raise ImportError("httpx required for data pipeline: pip install httpx")

        binance_symbol = SYMBOL_MAP.get(symbol, symbol)
        binance_interval = INTERVAL_MAP.get(interval, interval)

        if end_time is None:
            end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=days)

        # Binance API: max 1000 klines per request
        all_klines = []
        limit = 1000
        current_end = int(end_time.timestamp() * 1000)

        while current_end > int(start_time.timestamp() * 1000):
            params = {
                "symbol": binance_symbol,
                "interval": binance_interval,
                "limit": limit,
                "endTime": current_end,
            }
            try:
                with httpx.Client(timeout=15) as client:
                    resp = client.get(BINANCE_KLINE_URL, params=params)
                    resp.raise_for_status()
                    klines = resp.json()
            except Exception as e:
                # v3.3: perp-only symbols (HYPE, LIT) are absent on the spot
                # klines endpoint (400). Retry the same params on the USDT-M
                # futures klines endpoint — the study universe is perp anyway.
                try:
                    with httpx.Client(timeout=15) as client:
                        resp = client.get(BINANCE_FAPI_KLINE_URL, params=params)
                        resp.raise_for_status()
                        klines = resp.json()
                except Exception as e2:
                    log.error(f"Binance fetch failed for {binance_symbol}: {e} / fapi: {e2}")
                    break

            if not klines:
                break

            all_klines = klines + all_klines
            # Next batch: end before the earliest bar in this batch
            current_end = klines[0][0] - 1

            if len(klines) < limit:
                break

            time.sleep(0.1)  # rate limit courtesy

        # Parse klines
        bars = []
        for k in all_klines:
            ts = datetime.fromtimestamp(k[0] / 1000.0, tz=timezone.utc)
            bars.append(MarketBar(
                timestamp=ts.isoformat(),
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
                quote_volume=float(k[7]),
                trades=int(k[8]),
            ))

        # Filter to requested date range
        bars = [b for b in bars if b.timestamp >= start_time.isoformat()]

        log.info(f"Fetched {len(bars)} bars for {symbol} {interval}")
        return bars

    def compute_astro_features_for_bars(
        self, bars: list[MarketBar],
    ) -> list[MarketBar]:
        """Compute ephemeris features for each bar's timestamp.

        Memoizes ephemeris snapshots for efficiency (same timestamp = same features).
        """
        cache: dict[str, dict[str, float]] = {}

        for bar in bars:
            # Normalize timestamp to start of bar
            dt = datetime.fromisoformat(bar.timestamp)
            cache_key = dt.strftime("%Y-%m-%dT%H")  # coarse cache by hour

            if cache_key in cache:
                bar.astro_features = cache[cache_key].copy()
            else:
                try:
                    snap = self.ephemeris.compute(dt)
                    features = compute_astro_features(snap)
                    cache[cache_key] = features
                    bar.astro_features = features.copy()
                except Exception as e:
                    log.warning(f"Ephemeris failed for {dt}: {e}")
                    bar.astro_features = {}

        return bars

    def fetch(
        self,
        symbol: str,
        interval: str,
        days: int = 365,
        end_time: datetime | None = None,
        save: bool = True,
    ) -> AstroMarketDataset:
        """Full pipeline: fetch OHLCV → compute ephemeris → save.

        Args:
            symbol: "BTC", "ETH", "SOL"
            interval: "1h", "4h", "1d", "15m"
            days: History length
            end_time: End datetime
            save: Save to data/astronacci/

        Returns:
            AstroMarketDataset with astro features attached.
        """
        # Step 1: Fetch OHLCV
        bars = self.fetch_ohlcv_binance(symbol, interval, days, end_time)
        if not bars:
            return AstroMarketDataset(
                symbol=symbol, timeframe=interval, bars=[],
                feature_names=[], n_bars=0, date_range="",
            )

        # Step 2: Compute astro features
        bars = self.compute_astro_features_for_bars(bars)

        # Step 3: Collect feature names
        feature_names = sorted(bars[0].astro_features.keys()) if bars else []

        # Step 4: Build dataset
        dataset = AstroMarketDataset(
            symbol=symbol,
            timeframe=interval,
            bars=bars,
            feature_names=feature_names,
            n_bars=len(bars),
            date_range=f"{bars[0].timestamp} → {bars[-1].timestamp}",
        )

        # Step 5: Save
        if save:
            self.save_dataset(dataset)

        return dataset

    def fetch_multi(
        self,
        symbols: list[str] | None = None,
        intervals: list[str] | None = None,
        days: int = 365,
    ) -> dict[str, dict[str, AstroMarketDataset]]:
        """Fetch multiple symbols × intervals.

        Returns: {symbol: {interval: AstroMarketDataset}}
        """
        if symbols is None:
            symbols = ["BTC", "ETH", "SOL", "ARB", "LTC"]
        if intervals is None:
            intervals = ["1d", "4h", "1h"]

        results: dict[str, dict[str, AstroMarketDataset]] = {}
        for sym in symbols:
            results[sym] = {}
            for interval in intervals:
                log.info(f"Fetching {sym} {interval}...")
                results[sym][interval] = self.fetch(
                    sym, interval, days=days, save=True,
                )
        return results

    def save_dataset(self, dataset: AstroMarketDataset):
        """Save dataset to JSONL file."""
        filename = f"{dataset.symbol}_{dataset.timeframe}.jsonl"
        filepath = self.output_dir / filename

        with open(filepath, "w") as f:
            for d in dataset.to_dicts():
                f.write(json.dumps(d) + "\n")

        log.info(f"Saved {dataset.n_bars} bars → {filepath}")

    def load_dataset(
        self, symbol: str, interval: str,
    ) -> AstroMarketDataset | None:
        """Load previously saved dataset."""
        filename = f"{symbol}_{interval}.jsonl"
        filepath = self.output_dir / filename

        if not filepath.exists():
            return None

        bars = []
        with open(filepath) as f:
            for line in f:
                if line.strip():
                    d = json.loads(line)
                    astro = {
                        k: v for k, v in d.items()
                        if k not in ("timestamp", "open", "high", "low",
                                      "close", "volume", "quote_volume", "trades")
                    }
                    bars.append(MarketBar(
                        timestamp=d["timestamp"],
                        open=d["open"],
                        high=d["high"],
                        low=d["low"],
                        close=d["close"],
                        volume=d["volume"],
                        quote_volume=d.get("quote_volume", 0),
                        trades=d.get("trades", 0),
                        astro_features=astro,
                    ))

        feature_names = sorted(bars[0].astro_features.keys()) if bars else []

        return AstroMarketDataset(
            symbol=symbol,
            timeframe=interval,
            bars=bars,
            feature_names=feature_names,
            n_bars=len(bars),
            date_range=f"{bars[0].timestamp} → {bars[-1].timestamp}" if bars else "",
        )

    def list_datasets(self) -> list[str]:
        """List all saved datasets."""
        return sorted(
            f.stem for f in self.output_dir.glob("*.jsonl")
        )

    # ── Hyperliquid metadata (no auth needed) ──

    @staticmethod
    def fetch_hl_meta() -> dict:
        """Fetch Hyperliquid market metadata (public endpoint).

        Returns universe info: perpetual names, funding rates, open interest.
        """
        if httpx is None:
            return {}
        try:
            payload = {"type": "meta"}
            with httpx.Client(timeout=10) as client:
                resp = client.post(HL_INFO_URL, json=payload)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            log.warning(f"HL meta fetch failed: {e}")
            return {}

    @staticmethod
    def fetch_hl_funding() -> dict:
        """Fetch Hyperliquid current funding rates (public).

        Returns {symbol: funding_rate} dict.
        """
        if httpx is None:
            return {}
        try:
            payload = {"type": "predictedFundings"}
            with httpx.Client(timeout=10) as client:
                resp = client.post(HL_INFO_URL, json=payload)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            log.warning(f"HL funding fetch failed: {e}")
            return {}


# ─────────────────────────────────────────────────────────────────────────────
# SELF-TEST (CLI)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)

    ap = argparse.ArgumentParser(description="Astronacci Data Pipeline")
    ap.add_argument("--symbol", default="BTC", help="Symbol: BTC, ETH, SOL")
    ap.add_argument("--interval", default="1d", help="Interval: 1h, 4h, 1d, 15m")
    ap.add_argument("--days", type=int, default=90, help="Days of history")
    ap.add_argument("--list", action="store_true", help="List saved datasets")
    ap.add_argument("--hl-meta", action="store_true", help="Fetch HL metadata")
    args = ap.parse_args()

    pipeline = AstroDataPipeline()

    if args.list:
        datasets = pipeline.list_datasets()
        print(f"Saved datasets ({len(datasets)}):")
        for ds in datasets:
            print(f"  {ds}")
    elif args.hl_meta:
        meta = pipeline.fetch_hl_meta()
        funding = pipeline.fetch_hl_funding()
        print(f"HL meta: {len(str(meta))} chars")
        print(f"HL funding: {len(funding)} assets")
    else:
        print(f"Fetching {args.symbol} {args.interval} ({args.days}d)...")
        dataset = pipeline.fetch(args.symbol, args.interval, days=args.days)

        if dataset.n_bars == 0:
            print("No data fetched.")
        else:
            print(f"✓ {dataset.n_bars} bars | {dataset.date_range}")
            print(f"✓ {len(dataset.feature_names)} astro features")
            print(f"  Sample features: {dataset.feature_names[:8]}...")

            # Quick stats
            closes = dataset.price_series()
            rets = dataset.returns_series()
            if rets:
                from astronacci_events import _mean, _std
                print(f"  Mean return: {_mean(rets):.6f}")
                print(f"  Volatility:  {_std(rets):.6f}")

            # Show first bar
            bar = dataset.bars[0]
            print(f"\n  First bar: {bar.timestamp}")
            print(f"  O={bar.open} H={bar.high} L={bar.low} C={bar.close}")
            print(f"  Lunar phase sin: {bar.astro_features.get('lunar_phase_sin', 'N/A'):.4f}")
            print(f"  Lunar illum:    {bar.astro_features.get('lunar_illumination', 'N/A'):.4f}")
