#!/usr/bin/env python3
"""
ANANTARA SAKTI — Hyperliquid Historical Data Downloader

Downloads and caches 360-day historical data from HL public API:
  • OHLCV candles (4h + 1d) — 230 perp markets
  • Funding rates (hourly, paginated) — all perp markets
  • Spot OHLCV (1d) — top liquid spot markets

Data saved to: freqtrade_user_data/data/hl/
  hl/candles/{coin}/4h.jsonl    — {t,o,h,l,c,v} per candle
  hl/candles/{coin}/1d.jsonl
  hl/funding/{coin}.jsonl       — {time, fundingRate, premium}

Designed for:
  1. Offline analysis (no API dependency during research)
  2. Fast backtest (local read vs N API calls)
  3. Incremental update (only fetch what's missing)
  4. Signal validation (360d coverage >> current 90d default)

Usage:
  python3 scripts/download_hl_history.py                    # full 360d, 50 liquid coins
  python3 scripts/download_hl_history.py --coins BTC ETH SOL
  python3 scripts/download_hl_history.py --days 90 --update  # incremental update
  python3 scripts/download_hl_history.py --status            # show what's downloaded
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import httpx

# ── Config ──────────────────────────────────────────────────────────────────
HL_API     = "https://api.hyperliquid.xyz/info"
TIMEOUT    = 20
RATE_LIMIT = 0.15   # seconds between requests (respectful, avoids rate-limit)

PROJECT_DIR = Path(os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti")))
DATA_DIR    = PROJECT_DIR / "freqtrade_user_data" / "data" / "hl"

# 50 most liquid perp markets (by daily volume, curated from Pre-Gain scanner)
LIQUID_COINS = [
    # Large cap perp
    "BTC",  "ETH",  "SOL",  "BNB",  "XRP",   "DOGE",  "ADA",   "AVAX",  "LINK",  "DOT",
    "LTC",  "ARB",  "OP",   "SUI",  "APT",   "INJ",   "ATOM",  "NEAR",  "HBAR",  "WIF",
    "XMR",  "ZEC",  "HYPE", "AAVE", "UNI",   "AXS",   "ONDO",  "TRX",   "WLD",   "FIL",
    "FET",  "TAO",  "GRT",  "MKR",  "TRUMP", "BERA",  "TIA",   "SEI",   "BLUR",  "DYDX",
    # Meme (HL uses 'k' prefix for 1000x coins)
    "kPEPE","kBONK","kSHIB","FLOKI",
    # DeFi / infrastructure
    "COMP", "SAND", "GALA", "MANA",  "RENDER","VIRTUAL",
]
LIQUID_COINS = list(dict.fromkeys(LIQUID_COINS))  # deduplicate

INTERVALS  = ["4h", "1d"]    # primary research intervals (360d coverage)


# ── HL API helpers ───────────────────────────────────────────────────────────

def _post(body: dict) -> list | dict | None:
    for attempt in range(3):
        try:
            r = httpx.post(HL_API, json=body, timeout=TIMEOUT)
            if r.status_code == 200 and r.content:
                return r.json()
            time.sleep(1.0)
        except Exception as e:
            if attempt == 2:
                print(f"    ⚠ API error: {e}")
            time.sleep(2.0)
    return None


def fetch_candles(coin: str, interval: str, days: int) -> list[dict]:
    """Fetch OHLCV candles for `coin` × `interval` × `days` back."""
    end_ms   = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000
    data = _post({
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": interval, "startTime": start_ms, "endTime": end_ms},
    })
    if not isinstance(data, list):
        return []
    return [{"t": c["t"], "o": float(c["o"]), "h": float(c["h"]),
             "l": float(c["l"]), "c": float(c["c"]), "v": float(c["v"])}
            for c in data if "t" in c]


def fetch_funding(coin: str, days: int) -> list[dict]:
    """Fetch hourly funding rates via paginated API (500 records/call)."""
    end_ms   = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000
    all_records: list[dict] = []
    current_start = start_ms

    for _ in range(25):  # max 25 pages × 500 = 12500 records >> 360d×24=8640
        data = _post({"type": "fundingHistory", "coin": coin, "startTime": current_start})
        if not isinstance(data, list) or not data:
            break
        for r in data:
            all_records.append({
                "time": r["time"],
                "rate": float(r.get("fundingRate", 0) or 0),
                "premium": float(r.get("premium", 0) or 0),
            })
        last_ts = data[-1]["time"]
        if last_ts >= end_ms - 3600_000 or len(data) < 500:
            break
        current_start = last_ts + 1
        time.sleep(RATE_LIMIT)

    return all_records


# ── Storage ──────────────────────────────────────────────────────────────────

def _candle_path(coin: str, interval: str) -> Path:
    return DATA_DIR / "candles" / coin / f"{interval}.jsonl"

def _funding_path(coin: str) -> Path:
    return DATA_DIR / "funding" / f"{coin}.jsonl"

def _last_ts(path: Path) -> int:
    """Last timestamp in a JSONL file (0 if empty/missing)."""
    if not path.exists() or path.stat().st_size == 0:
        return 0
    try:
        last_line = ""
        with open(path, "rb") as f:
            f.seek(max(0, path.stat().st_size - 512))
            last_line = f.read().decode(errors="ignore").strip().split("\n")[-1]
        row = json.loads(last_line)
        return int(row.get("t") or row.get("time") or 0)
    except Exception:
        return 0


def save_jsonl(path: Path, records: list[dict], ts_key: str = "t") -> int:
    """Append new records (de-dup by ts_key). Returns count written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_last = _last_ts(path)
    new_recs = [r for r in records if r.get(ts_key, 0) > existing_last]
    if not new_recs:
        return 0
    with open(path, "a") as f:
        for r in new_recs:
            f.write(json.dumps(r) + "\n")
    return len(new_recs)


# ── Status ───────────────────────────────────────────────────────────────────

def cmd_status():
    """Show what's already downloaded."""
    candle_dir  = DATA_DIR / "candles"
    funding_dir = DATA_DIR / "funding"

    print(f"\n{'='*60}")
    print(f"  HL HISTORICAL DATA — Status")
    print(f"  Direktori: {DATA_DIR}")
    print(f"{'='*60}")

    if not candle_dir.exists() and not funding_dir.exists():
        print("\n  ❌ Belum ada data. Jalankan: python3 scripts/download_hl_history.py")
        return

    # Candles
    print("\n  📊 OHLCV Candles:")
    total_kb = 0
    for coin_dir in sorted(candle_dir.iterdir()) if candle_dir.exists() else []:
        coin = coin_dir.name
        for iv_file in sorted(coin_dir.glob("*.jsonl")):
            size_kb = iv_file.stat().st_size / 1024
            total_kb += size_kb
            last_ts = _last_ts(iv_file)
            last_dt = time.strftime("%Y-%m-%d", time.gmtime(last_ts / 1000)) if last_ts else "?"
            # Count lines
            with open(iv_file) as f:
                n = sum(1 for _ in f)
            print(f"    {coin:<8} {iv_file.stem:4s}: {n:5d} candles | last: {last_dt} | {size_kb:.1f}KB")

    # Funding
    print("\n  💰 Funding History:")
    fnd_kb = 0
    funded_coins = sorted(funding_dir.glob("*.jsonl")) if funding_dir.exists() else []
    for fp in funded_coins:
        coin = fp.stem
        size_kb = fp.stat().st_size / 1024
        fnd_kb += size_kb
        last_ts = _last_ts(fp)
        last_dt = time.strftime("%Y-%m-%d", time.gmtime(last_ts / 1000)) if last_ts else "?"
        with open(fp) as f:
            n = sum(1 for _ in f)
        print(f"    {coin:<8}: {n:5d} records | last: {last_dt} | {size_kb:.1f}KB")

    total_mb = (total_kb + fnd_kb) / 1024
    print(f"\n  Total: {total_mb:.1f} MB")
    print(f"{'='*60}\n")


# ── Download ─────────────────────────────────────────────────────────────────

def download_coin(coin: str, days: int, intervals: list[str],
                  include_funding: bool = True, update: bool = False) -> dict:
    """Download all data for one coin. Returns summary dict."""
    result = {"coin": coin, "candles": {}, "funding": 0, "errors": []}

    # Candles
    for iv in intervals:
        path = _candle_path(coin, iv)
        try:
            if update and path.exists():
                # Incremental: only fetch since last stored candle
                last_ts = _last_ts(path)
                days_missing = (time.time() * 1000 - last_ts) / (1000 * 3600 * 24) + 1
                days_to_fetch = min(int(days_missing) + 1, days)
            else:
                days_to_fetch = days

            candles = fetch_candles(coin, iv, days_to_fetch)
            time.sleep(RATE_LIMIT)

            if candles:
                n = save_jsonl(path, candles, ts_key="t")
                result["candles"][iv] = n
            else:
                result["errors"].append(f"candle {iv}: empty response")
        except Exception as e:
            result["errors"].append(f"candle {iv}: {e}")

    # Funding
    if include_funding:
        path = _funding_path(coin)
        try:
            if update and path.exists():
                last_ts = _last_ts(path)
                days_missing = (time.time() * 1000 - last_ts) / (1000 * 3600 * 24) + 1
                days_to_fetch = min(int(days_missing) + 1, days)
            else:
                days_to_fetch = days

            records = fetch_funding(coin, days_to_fetch)
            time.sleep(RATE_LIMIT)

            if records:
                n = save_jsonl(path, records, ts_key="time")
                result["funding"] = n
        except Exception as e:
            result["errors"].append(f"funding: {e}")

    return result


def cmd_download(coins: list[str], days: int, intervals: list[str],
                 include_funding: bool = True, update: bool = False):
    """Main download command."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "candles").mkdir(exist_ok=True)
    (DATA_DIR / "funding").mkdir(exist_ok=True)

    mode = "UPDATE (incremental)" if update else f"FULL ({days} hari)"
    print(f"\n{'='*60}")
    print(f"  HL HISTORICAL DATA DOWNLOADER")
    print(f"  Mode: {mode}")
    print(f"  Koin: {len(coins)} | Intervals: {', '.join(intervals)}")
    print(f"  Funding: {'ya' if include_funding else 'tidak'}")
    print(f"  Estimasi waktu: ~{len(coins) * (len(intervals) + (1 if include_funding else 0)) * 0.5:.0f} detik")
    print(f"{'='*60}\n")

    t_start = time.time()
    errors_total = []

    for i, coin in enumerate(coins, 1):
        print(f"  [{i:2d}/{len(coins)}] {coin:<8}", end=" ", flush=True)
        res = download_coin(coin, days, intervals, include_funding, update)

        # Report per coin
        parts = []
        for iv, n in res["candles"].items():
            if n > 0:
                parts.append(f"{iv}+{n}")
            else:
                parts.append(f"{iv}=OK")
        if include_funding and res["funding"] > 0:
            parts.append(f"fund+{res['funding']}")
        elif include_funding:
            parts.append("fund=OK")

        if res["errors"]:
            print(f"⚠ {' '.join(parts)} | err: {res['errors'][0][:50]}")
            errors_total.extend(res["errors"])
        else:
            print(f"✓ {' '.join(parts)}")

    elapsed = time.time() - t_start
    print(f"\n{'='*60}")
    print(f"  Selesai dalam {elapsed:.0f} detik")
    if errors_total:
        print(f"  ⚠ {len(errors_total)} error (tidak kritis, data sebagian tersedia)")
    print(f"{'='*60}")
    cmd_status()


# ── Local data reader (untuk digunakan research scripts) ─────────────────────

def load_candles(coin: str, interval: str = "4h") -> list[dict]:
    """Load OHLCV candles dari lokal. Return [] jika tidak ada."""
    path = _candle_path(coin, interval)
    if not path.exists():
        return []
    rows = []
    with open(path) as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def load_funding(coin: str) -> list[dict]:
    """Load funding history dari lokal. Return [] jika tidak ada."""
    path = _funding_path(coin)
    if not path.exists():
        return []
    rows = []
    with open(path) as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def candles_available(coin: str, interval: str = "4h") -> int:
    """Berapa candle yang tersedia lokal untuk coin+interval."""
    path = _candle_path(coin, interval)
    if not path.exists():
        return 0
    with open(path) as f:
        return sum(1 for _ in f)


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Download HL historical data (OHLCV + funding)")
    ap.add_argument("--coins", nargs="+", default=None,
                    help="Daftar koin (default: 50 liquid coins)")
    ap.add_argument("--days", type=int, default=360,
                    help="Berapa hari kebelakang (default: 360)")
    ap.add_argument("--intervals", nargs="+", default=INTERVALS,
                    help="Interval candle (default: 4h 1d)")
    ap.add_argument("--no-funding", action="store_true",
                    help="Skip download funding rates")
    ap.add_argument("--update", action="store_true",
                    help="Mode update: hanya download data yang belum ada (incremental)")
    ap.add_argument("--status", action="store_true",
                    help="Tampilkan status data yang sudah didownload")
    args = ap.parse_args()

    if args.status:
        cmd_status()
    else:
        coins = args.coins if args.coins else LIQUID_COINS
        cmd_download(
            coins=coins,
            days=args.days,
            intervals=args.intervals,
            include_funding=not args.no_funding,
            update=args.update,
        )
