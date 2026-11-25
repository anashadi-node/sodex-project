#!/usr/bin/env python3
"""
ANANTARA SAKTI v3.2 — SoDEX historical data downloader

SoDEX is a Sui-based DEX not in ccxt. This downloader uses its public
REST API to fetch historical OHLCV and save in Freqtrade-compatible
feather format.

API ref: https://docs.sodex.com (https://mainnet-gw.sodex.dev/api/v1)
Endpoint: GET /markets/{symbol}/klines?interval=X&startTime=ms&endTime=ms&limit=N
Response: {code, timestamp, data: [{t, o, h, l, c, v, q}, ...]}

Usage:
    python3 scripts/sodex_downloader.py

Output: freqtrade_user_data/data/sodex/spot/{BASE}_{QUOTE}-{TF}.feather
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("sodex-dl")

BASE_URL_SPOT = "https://mainnet-gw.sodex.dev/api/v1/spot"
BASE_URL_PERPS = "https://mainnet-gw.sodex.dev/api/v1/perps"

# (sodex_symbol, freqtrade_filename_base)
SPOT_PAIRS = [
    ("vBTC_vUSDC", "BTC_USDC"),
    ("vETH_vUSDC", "ETH_USDC"),
    ("vSOL_vUSDC", "SOL_USDC"),
    ("vSUI_vUSDC", "SUI_USDC"),
]

# Expanded perps universe (edge research). Includes commodities (XAUT gold) and
# alts. PAXG/TON excluded (no/insufficient klines).
PERPS_PAIRS = [
    ("BTC-USD", "BTC_USD"),
    ("ETH-USD", "ETH_USD"),
    ("SOL-USD", "SOL_USD"),
    ("XAUT-USD", "XAUT_USD"),
    ("HYPE-USD", "HYPE_USD"),
    ("ZEC-USD", "ZEC_USD"),
    ("BCH-USD", "BCH_USD"),
    ("SUI-USD", "SUI_USD"),
    ("DOGE-USD", "DOGE_USD"),
    ("LTC-USD", "LTC_USD"),
    ("BNB-USD", "BNB_USD"),
    ("XRP-USD", "XRP_USD"),
    # Commodities (24/7 perps) + tokenized US stocks (INTC/AMD: gaps off-hours).
    ("SILVER-USD", "SILVER_USD"),
    ("COPPER-USD", "COPPER_USD"),
    ("INTC-USD", "INTC_USD"),
    ("AMD-USD", "AMD_USD"),
    # Batch 3: more alts + tokenized stocks/ETF (GOOGL/TSLA/HOOD/EWY).
    ("DASH-USD", "DASH_USD"),
    ("WLFI-USD", "WLFI_USD"),
    ("LIT-USD", "LIT_USD"),
    ("ONDO-USD", "ONDO_USD"),
    ("PENGU-USD", "PENGU_USD"),
    ("NEAR-USD", "NEAR_USD"),
    ("UNI-USD", "UNI_USD"),
    ("GOOGL-USD", "GOOGL_USD"),
    ("EWY-USD", "EWY_USD"),
    ("TSLA-USD", "TSLA_USD"),
    ("HOOD-USD", "HOOD_USD"),
    # Batch 4: more alts + tokenized stocks (NVDA/AMZN/MU/ORCL).
    ("ARB-USD", "ARB_USD"),
    ("1000PEPE-USD", "1000PEPE_USD"),
    ("TRX-USD", "TRX_USD"),
    ("ADA-USD", "ADA_USD"),
    ("ENA-USD", "ENA_USD"),
    ("XMR-USD", "XMR_USD"),
    ("SKHX-USD", "SKHX_USD"),
    ("APT-USD", "APT_USD"),
    ("MU-USD", "MU_USD"),
    ("NVDA-USD", "NVDA_USD"),
    ("AMZN-USD", "AMZN_USD"),
    ("ORCL-USD", "ORCL_USD"),
    # Batch 5: more alts + stocks (PLTR/COIN/CRCL). SOSO excluded (no perps klines).
    ("MON-USD", "MON_USD"),
    ("XPL-USD", "XPL_USD"),
    ("LINK-USD", "LINK_USD"),
    ("WLD-USD", "WLD_USD"),
    ("ASTER-USD", "ASTER_USD"),
    ("TRUMP-USD", "TRUMP_USD"),
    ("VIRTUAL-USD", "VIRTUAL_USD"),
    ("BERA-USD", "BERA_USD"),
    ("HBAR-USD", "HBAR_USD"),
    ("FIL-USD", "FIL_USD"),
    ("OP-USD", "OP_USD"),
    ("AXS-USD", "AXS_USD"),
    ("WIF-USD", "WIF_USD"),
    ("AVAX-USD", "AVAX_USD"),
    ("AAVE-USD", "AAVE_USD"),
    ("PLTR-USD", "PLTR_USD"),
    ("COIN-USD", "COIN_USD"),
    ("CRCL-USD", "CRCL_USD"),
]

# Interval mapping: API string → seconds per candle
INTERVALS = {
    "1h": 3_600,
    "4h": 14_400,
    "1d": 86_400,
}

LOOKBACK_DAYS = 400
MAX_LIMIT = 1_000  # per API call
# Default: container path. Override with env var DATA_ROOT to run on host.
DATA_ROOT = Path(os.environ.get("DATA_ROOT", "/freqtrade/user_data/data/sodex"))


def fetch_klines(
    base_url: str, symbol: str, interval: str, start_ms: int, end_ms: int
) -> list[dict]:
    """Fetch ≤1000 klines for [start_ms, end_ms]. Returns raw list."""
    url = f"{base_url}/markets/{symbol}/klines"
    params = {
        "interval": interval,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": MAX_LIMIT,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        payload = r.json()
        if payload.get("code") != 0:
            log.warning(f"{symbol}/{interval}: API error code={payload.get('code')}")
            return []
        return payload.get("data", [])
    except requests.RequestException as e:
        log.warning(f"{symbol}/{interval}: HTTP error: {e}")
        return []


def download_pair(
    base_url: str, sodex_symbol: str, ft_name: str, interval: str, mode: str
) -> int:
    """Download full lookback for one pair+interval. Returns row count."""
    seconds_per_candle = INTERVALS[interval]
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=LOOKBACK_DAYS)
    end_ms = int(end_dt.timestamp() * 1000)
    start_ms = int(start_dt.timestamp() * 1000)

    all_rows: list[dict] = []
    cursor_end = end_ms
    page = 0
    seen_first_ts = set()

    while cursor_end > start_ms and page < 50:  # safety cap
        page += 1
        # Walk backwards: fetch up to limit ending at cursor_end
        window_start = max(start_ms, cursor_end - MAX_LIMIT * seconds_per_candle * 1000)
        batch = fetch_klines(base_url, sodex_symbol, interval, window_start, cursor_end)
        if not batch:
            break

        # Detect no-progress (API returned same first ts twice)
        first_ts = batch[0]["t"]
        if first_ts in seen_first_ts:
            break
        seen_first_ts.add(first_ts)

        all_rows.extend(batch)
        # Earliest candle ts in batch becomes next cursor (one candle before)
        earliest = min(r["t"] for r in batch)
        cursor_end = earliest - 1
        time.sleep(0.15)  # respect rate limit 10 req / 10s

    if not all_rows:
        log.warning(f"{ft_name}/{interval}: 0 rows")
        return 0

    # Dedupe + sort
    df = pd.DataFrame(all_rows).drop_duplicates(subset=["t"]).sort_values("t")
    df["date"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    for col in ("o", "h", "l", "c", "v"):
        df[col] = df[col].astype(float)
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df = df[["date", "open", "high", "low", "close", "volume"]].reset_index(drop=True)

    out_dir = DATA_ROOT / mode
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{ft_name}-{interval}.feather"
    df.to_feather(out_file)
    log.info(
        f"✅ {ft_name}/{interval} ({mode}): {len(df):>6} rows | "
        f"{df['date'].iloc[0]:%Y-%m-%d} → {df['date'].iloc[-1]:%Y-%m-%d} | "
        f"saved {out_file.relative_to(DATA_ROOT.parent.parent)}"
    )
    return len(df)


def main() -> int:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    log.info(f"SoDEX downloader starting | lookback={LOOKBACK_DAYS}d | output={DATA_ROOT}")

    total_rows = 0
    fail_count = 0

    # SPOT
    for sodex_sym, ft_name in SPOT_PAIRS:
        for tf in INTERVALS:
            n = download_pair(BASE_URL_SPOT, sodex_sym, ft_name, tf, mode="spot")
            total_rows += n
            if n == 0:
                fail_count += 1

    # PERPS (may not exist for all pairs — failures are OK, just logged)
    log.info("--- PERPS (skipping if endpoint returns 404) ---")
    for sodex_sym, ft_name in PERPS_PAIRS:
        for tf in INTERVALS:
            n = download_pair(BASE_URL_PERPS, sodex_sym, ft_name, tf, mode="perps")
            total_rows += n
            if n == 0:
                fail_count += 1

    log.info(
        f"Done. Total rows: {total_rows:,} | "
        f"Failures: {fail_count}/{len(SPOT_PAIRS) * len(INTERVALS) + len(PERPS_PAIRS) * len(INTERVALS)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
