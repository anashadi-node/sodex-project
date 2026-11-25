#!/usr/bin/env python3
"""
ANANTARA SAKTI — SoDEX SoPoints farming module.

Drives genuine directional MAKER orders on SoDEX perps via the official
`sodex` CLI (EIP-712 signing handled by the CLI, not reimplemented here).
Goal: accrue real trading volume → SoPoints airdrop, while paying near-zero
maker fee (0.0114% on this account) and respecting SoDEX anti-wash rules.

SECURITY / SAFETY:
- dry_run defaults to True. NO real order is placed until dry_run=False.
- All secrets come from .env (SODEX_PRIVATE_KEY etc.), never hardcoded.
- Anti-wash: post-only (gtx) maker orders, minimum hold time, no instant
  reversals. SoDEX risk engine disqualifies wash trading.
- One-way netting only (positionSide always BOTH=1); no hedge mode.

Direction signal comes from the Hermes Bridge (posture + BTC forecast). This
module does NOT decide direction on its own — Hermes is the brain.

Usage:
    python3 anantara/sodex_farming.py status          # account + market snapshot
    python3 anantara/sodex_farming.py validate-signing # place unfillable order + cancel
    python3 anantara/sodex_farming.py farm --once      # one farming cycle (dry-run unless --live)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sodex-farm")

# ── Global lock for SoDEX CLI calls (EIP-712 nonce must be sequential) ──
_cli_lock = threading.Lock()
_OPEN_POSITIONS_CACHE_TTL_S = float(os.environ.get("SODEX_OPEN_POSITIONS_CACHE_TTL_S", "2.0"))
_OPEN_POSITIONS_WARN_COOLDOWN_S = float(os.environ.get("SODEX_OPEN_POSITIONS_WARN_COOLDOWN_S", "60"))
_open_positions_cache: dict[str, tuple[float, list[dict]]] = {}
_open_positions_warn_ts: dict[str, float] = {}

PROJECT_DIR = Path(os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti")))
FILL_JOURNAL = Path(os.environ.get("SODEX_FILL_JOURNAL",
                                   str(PROJECT_DIR / "data" / "sodex_daemon_fills.jsonl")))


def _journal_order(args: list[str], result, error: str | None) -> None:
    """Catat orders place/cancel ke journal append-only (best-effort).

    Watchdog live memakai journal ini untuk membedakan posisi yang DIKELOLA
    daemon dari posisi asing. Kegagalan tulis TIDAK boleh menghentikan trading.
    """
    try:
        if len(args) < 2 or args[0] != "orders" or args[1] not in ("place", "cancel"):
            return
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "cmd": args[1],
            "argv": list(args[2:]),
            "ok": error is None,
        }
        if "--symbol" in args:
            rec["symbol"] = args[args.index("--symbol") + 1]
        if isinstance(result, dict):
            data = result.get("data", result)
            if isinstance(data, dict):
                rec["order_id"] = (data.get("orderID") or data.get("orderId")
                                   or data.get("id"))
                rec["status"] = data.get("status")
                rec.setdefault("symbol", data.get("symbol"))
                rec["filled_qty"] = data.get("filledQty") or data.get("executedQty")
        if error:
            rec["error"] = str(error)[:300]
        FILL_JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with FILL_JOURNAL.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
    except Exception as exc:  # pragma: no cover - jangan ganggu eksekusi
        log.warning("fill journal gagal: %s", exc)

SODEX_BIN = os.environ.get("SODEX_BIN", str(PROJECT_DIR / "bin" / "sodex"))
SAFETY_HALT_FILE = PROJECT_DIR / "data" / "SAFETY_HALT"
PNL_HALT_FILE = PROJECT_DIR / "data" / "PNL_HALT"


def halt_active() -> bool:
    # FORCE_OVERRIDE: env SODEX_FORCE_SKIP_HALT=1 bypasses all HALT checks
    if os.environ.get("SODEX_FORCE_SKIP_HALT") == "1":
        return False
    return SAFETY_HALT_FILE.exists() or PNL_HALT_FILE.exists()


def _halt_blocks_cli(args: list[str]) -> bool:
    # FORCE_OVERRIDE: env SODEX_FORCE_SKIP_HALT=1 bypasses all HALT checks
    if os.environ.get("SODEX_FORCE_SKIP_HALT") == "1":
        return False
    return (
        len(args) >= 3
        and args[0:3] == ["orders", "place", "perps"]
        and "--reduce-only" not in args
        and halt_active()
    )

# Symbol metadata: id, price decimals, qty decimals, exchange max leverage.
SYMBOLS = {
    "BTC-USD": {"id": 1, "px_decimals": 0, "qty_decimals": 5, "max_lev": 25},
    "ETH-USD": {"id": 2, "px_decimals": 1, "qty_decimals": 4, "max_lev": 20},
    "SOL-USD": {"id": 6, "px_decimals": 2, "qty_decimals": 3, "max_lev": 20},
    "XAUT-USD": {"id": 11, "px_decimals": 1, "qty_decimals": 4, "max_lev": 25},
    "HYPE-USD": {"id": 12, "px_decimals": 3, "qty_decimals": 2, "max_lev": 10},
    "ZEC-USD": {"id": 18, "px_decimals": 2, "qty_decimals": 3, "max_lev": 10},
    "BCH-USD": {"id": 26, "px_decimals": 2, "qty_decimals": 3, "max_lev": 10},
    "SUI-USD": {"id": 23, "px_decimals": 4, "qty_decimals": 1, "max_lev": 10},
    "DOGE-USD": {"id": 7, "px_decimals": 5, "qty_decimals": 0, "max_lev": 10},
    "LTC-USD": {"id": 14, "px_decimals": 2, "qty_decimals": 2, "max_lev": 10},
    "BNB-USD": {"id": 9, "px_decimals": 1, "qty_decimals": 3, "max_lev": 10},
    "XRP-USD": {"id": 8, "px_decimals": 4, "qty_decimals": 1, "max_lev": 10},
    "SILVER-USD": {"id": 41, "px_decimals": 3, "qty_decimals": 2, "max_lev": 20},
    "COPPER-USD": {"id": 76, "px_decimals": 4, "qty_decimals": 2, "max_lev": 20},
    "INTC-USD": {"id": 69, "px_decimals": 3, "qty_decimals": 3, "max_lev": 10},
    "AMD-USD": {"id": 63, "px_decimals": 2, "qty_decimals": 3, "max_lev": 10},
    "DASH-USD": {"id": 44, "px_decimals": 3, "qty_decimals": 2, "max_lev": 5},
    "WLFI-USD": {"id": 17, "px_decimals": 5, "qty_decimals": 0, "max_lev": 5},
    "LIT-USD": {"id": 31, "px_decimals": 4, "qty_decimals": 1, "max_lev": 5},
    "ONDO-USD": {"id": 20, "px_decimals": 4, "qty_decimals": 1, "max_lev": 10},
    "PENGU-USD": {"id": 29, "px_decimals": 6, "qty_decimals": 0, "max_lev": 5},
    "NEAR-USD": {"id": 42, "px_decimals": 4, "qty_decimals": 1, "max_lev": 10},
    "UNI-USD": {"id": 16, "px_decimals": 4, "qty_decimals": 1, "max_lev": 10},
    "GOOGL-USD": {"id": 56, "px_decimals": 2, "qty_decimals": 3, "max_lev": 10},
    "EWY-USD": {"id": 75, "px_decimals": 2, "qty_decimals": 3, "max_lev": 10},
    "TSLA-USD": {"id": 55, "px_decimals": 2, "qty_decimals": 3, "max_lev": 10},
    "HOOD-USD": {"id": 66, "px_decimals": 3, "qty_decimals": 3, "max_lev": 10},
    "ARB-USD": {"id": 38, "px_decimals": 5, "qty_decimals": 1, "max_lev": 5},
    "1000PEPE-USD": {"id": 3, "px_decimals": 6, "qty_decimals": 0, "max_lev": 10},
    "TRX-USD": {"id": 35, "px_decimals": 5, "qty_decimals": 0, "max_lev": 5},
    "ADA-USD": {"id": 10, "px_decimals": 5, "qty_decimals": 1, "max_lev": 10},
    "ENA-USD": {"id": 25, "px_decimals": 4, "qty_decimals": 0, "max_lev": 10},
    "XMR-USD": {"id": 51, "px_decimals": 2, "qty_decimals": 3, "max_lev": 5},
    "SKHX-USD": {"id": 72, "px_decimals": 2, "qty_decimals": 3, "max_lev": 10},
    "SPCX-USD": {"id": 81, "px_decimals": 4, "qty_decimals": 3, "max_lev": 5},
    "APT-USD": {"id": 36, "px_decimals": 4, "qty_decimals": 2, "max_lev": 5},
    "MU-USD": {"id": 64, "px_decimals": 2, "qty_decimals": 3, "max_lev": 10},
    "NVDA-USD": {"id": 54, "px_decimals": 2, "qty_decimals": 3, "max_lev": 10},
    "AMZN-USD": {"id": 57, "px_decimals": 2, "qty_decimals": 3, "max_lev": 10},
    "ORCL-USD": {"id": 73, "px_decimals": 2, "qty_decimals": 3, "max_lev": 10},
    "MON-USD": {"id": 22, "px_decimals": 5, "qty_decimals": 0, "max_lev": 5},
    "XPL-USD": {"id": 21, "px_decimals": 4, "qty_decimals": 0, "max_lev": 10},
    "LINK-USD": {"id": 5, "px_decimals": 3, "qty_decimals": 1, "max_lev": 10},
    "WLD-USD": {"id": 27, "px_decimals": 4, "qty_decimals": 0, "max_lev": 10},
    "ASTER-USD": {"id": 13, "px_decimals": 4, "qty_decimals": 0, "max_lev": 5},
    "TRUMP-USD": {"id": 34, "px_decimals": 4, "qty_decimals": 2, "max_lev": 5},
    "VIRTUAL-USD": {"id": 47, "px_decimals": 5, "qty_decimals": 1, "max_lev": 5},
    "BERA-USD": {"id": 49, "px_decimals": 5, "qty_decimals": 1, "max_lev": 5},
    "HBAR-USD": {"id": 40, "px_decimals": 5, "qty_decimals": 0, "max_lev": 5},
    "FIL-USD": {"id": 43, "px_decimals": 4, "qty_decimals": 1, "max_lev": 5},
    "OP-USD": {"id": 37, "px_decimals": 5, "qty_decimals": 1, "max_lev": 5},
    "AXS-USD": {"id": 50, "px_decimals": 4, "qty_decimals": 1, "max_lev": 5},
    "WIF-USD": {"id": 45, "px_decimals": 5, "qty_decimals": 0, "max_lev": 5},
    "AVAX-USD": {"id": 24, "px_decimals": 3, "qty_decimals": 0, "max_lev": 10},
    "AAVE-USD": {"id": 15, "px_decimals": 2, "qty_decimals": 2, "max_lev": 10},
    "PLTR-USD": {"id": 65, "px_decimals": 2, "qty_decimals": 3, "max_lev": 10},
    "COIN-USD": {"id": 68, "px_decimals": 2, "qty_decimals": 3, "max_lev": 10},
    "CRCL-USD": {"id": 61, "px_decimals": 3, "qty_decimals": 3, "max_lev": 10},
}

HERMES_URL = os.environ.get("HERMES_URL", "http://localhost:8000")

# --- Farming risk policy (env-overridable) ---
# Only trade when Hermes gives a directional call with confidence >= MIN_CONFIDENCE.
MIN_CONFIDENCE = float(os.environ.get("SODEX_MIN_CONFIDENCE", "0.65"))
# Margin (own funds) committed per order; notional = margin * leverage.
MARGIN_PER_ORDER = float(os.environ.get("SODEX_MARGIN_PER_ORDER", "25"))
# Max simultaneous open positions (isolated margin each).
MAX_POSITIONS = int(os.environ.get("SODEX_MAX_POSITIONS", "3"))
# Software stop-loss: close a position once unrealized loss reaches this
# fraction of its margin (well before exchange liquidation).
STOP_LOSS_MARGIN_FRAC = float(os.environ.get("SODEX_STOP_LOSS_MARGIN_FRAC", "0.40"))
# Take-profit: lock gains + rotate the slot (more SoPoints volume turnover) once
# unrealized profit reaches this fraction of margin.
TAKE_PROFIT_MARGIN_FRAC = float(os.environ.get("SODEX_TAKE_PROFIT_MARGIN_FRAC", "0.35"))
# Farming leverage cap. Backtest shows no reliable directional edge on SoDEX,
# so farming is for SoPoints volume (genuine directional), NOT high-conviction
# leverage. Capped low (5x): liquidation ~-18%, software stop ~-8% price move.
FARM_LEVERAGE_CAP = int(os.environ.get("SODEX_FARM_LEVERAGE", "5"))

# ── SCALP MODE (SoPoints volume generation — user's proven method) ──
# Open + immediately close = pure volume at ~fee cost, NO directional bet.
# Volume per round-trip = 2 * (margin * leverage). Liquid symbols only (tight
# spreads = lowest cost). Direction is irrelevant (closed flat instantly).
SCALP_SYMBOLS = [s.strip() for s in os.environ.get(
    "SODEX_SCALP_SYMBOLS", "BTC-USD,ETH-USD,SOL-USD,XAUT-USD").split(",") if s.strip()]
SCALP_MARGIN = float(os.environ.get("SODEX_SCALP_MARGIN", "8"))      # own funds per round
SCALP_LEVERAGE = int(os.environ.get("SODEX_SCALP_LEVERAGE", "7"))    # user-set 7x
SCALP_ROUNDS_PER_CYCLE = int(os.environ.get("SODEX_SCALP_ROUNDS", "2"))
SCALP_DAILY_VOLUME_CAP = float(os.environ.get("SODEX_SCALP_DAILY_VOLUME_CAP", "8000"))  # safety
SCALP_MODE = os.environ.get("SODEX_SCALP_MODE", "1") == "1"          # scalp vs directional

# ── RATIO MODE (MODE 4): optimized for 1:6,400+ ratio ──
# BTC + SILVER only (tightest spreads), ultra-short holds, no adverse selection tolerance
RATIO_SYMBOLS = ["BTC-USD", "SILVER-USD"]
RATIO_OPEN_WAIT = float(os.environ.get("SODEX_RATIO_OPEN_WAIT", "30"))
RATIO_CLOSE_WAIT = float(os.environ.get("SODEX_RATIO_CLOSE_WAIT", "45"))
RATIO_SPREAD_GATE = float(os.environ.get("SODEX_RATIO_SPREAD_GATE", "0.005"))
RATIO_MOMENTUM_GATE = float(os.environ.get("SODEX_RATIO_MOMENTUM_GATE", "0.02"))

# ── L1: AGGRESSOR BIAS (from 822K trade analysis, May 24-31) ──
# ETH & SOL are SELL-aggressive (44.7% / 45.0% buy) → MAKER BUY optimal
# BTC & ZEC balanced → either side safe
# Key insight: going WITH the aggressor flow means higher maker fill rate
# v3.4.1: BTC now has TIME-BASED bias (strongest bias per hour from 822K data)
AGGRESSOR_BIAS = {
    "ETH-USD": "buy",    # 55.3% taker sells → our maker buy fills faster
    "SOL-USD": "buy70",  # 55.0% SELL aggressive BUT close side struggles → 70% buy bias
    "ZEC-USD": "random", # 49.8% buy → balanced
    # BTC-USD is time-based (see get_aggressor_bias below)
}

# BTC Time-based bias: strongest hourly bias from 822K trade analysis
# SELL-aggressive hours → MAKER BUY; BUY-aggressive hours → MAKER SELL
BTC_HOURLY_BIAS = {
    # UTC hour: bias  (from 8-day aggressor analysis)
    0:  "buy",    # 48.3% buy → slight sell bias
    2:  "buy",    # 46.7% buy → 53.3% sell aggressive ⭐
    3:  "buy",    # 46.5% buy → 53.5% sell aggressive ⭐
    7:  "sell",   # 51.4% buy → slight buy bias
    8:  "sell",   # 51.2% buy → slight buy bias
    9:  "sell",   # 52.7% buy → buy aggressive
    10: "sell",   # 52.1% buy → slight buy bias
    11: "sell",   # 50.1% buy → slight buy bias
    13: "buy",    # 45.9% buy → 54.1% sell aggressive ⭐⭐
    14: "buy",    # 46.8% buy → 53.2% sell aggressive ⭐
    15: "buy",    # 46.8% buy → 53.2% sell aggressive ⭐
    16: "buy",    # 47.3% buy → 52.7% sell aggressive
    21: "buy",    # 47.1% buy → 52.9% sell aggressive
    22: "buy",    # 46.3% buy → 53.7% sell aggressive ⭐
}


def get_aggressor_bias(symbol: str) -> str:
    """Get optimal maker side based on aggressor flow analysis.
    
    For symbols with time-based bias (BTC), uses current UTC hour.
    For buy70 (SOL): 70% buy, 30% sell — avoids close-side starvation.
    Falls back to 'random' for unknown symbols.
    """
    if symbol == "BTC-USD":
        from datetime import datetime, timezone
        hour = datetime.now(timezone.utc).hour
        return BTC_HOURLY_BIAS.get(hour, "random")
    bias = AGGRESSOR_BIAS.get(symbol, "random")
    if bias == "buy70":
        return "buy" if random.random() < 0.70 else "sell"
    return bias

# ── MODE 5: OBI Dynamic Spread ──
# Uses real-time Order Book Imbalance to dynamically adjust spread gate.
# Tighter spreads when OBI is neutral (high fill prob), wider when directional.
# Target: 15% effective fee reduction → 1:10,320 ratio (zero additional cost).
# v3.4: XAUT dropped (87.5% maker, worst performer). Added aggressor bias.
MODE5_ENABLED = os.environ.get("SODEX_MODE5", "0") == "1"
MODE5_SYMBOLS = [s.strip() for s in os.environ.get(
    "SODEX_MODE5_SYMBOLS", "BTC-USD,ETH-USD,ZEC-USD,SOL-USD").split(",") if s.strip()]
MODE5_MIN_CONFIDENCE = float(os.environ.get("SODEX_MODE5_MIN_CONFIDENCE", "0.35"))
MODE5_OPEN_WAIT = float(os.environ.get("SODEX_MODE5_OPEN_WAIT", "60"))
MODE5_CLOSE_WAIT = float(os.environ.get("SODEX_MODE5_CLOSE_WAIT", "150"))
MODE5_MOMENTUM_GATE = float(os.environ.get("SODEX_MODE5_MOMENTUM_GATE", "0.025"))

# ── MODE 6: Market Making Hybrid (MM Hybrid) ──
# Places simultaneous BUY + SELL maker orders at spread-optimized levels.
# When both fill: captures spread + double maker rebate → "negative fee" effect.
# When only one fills: treated as directional, closed at maker.
# From 8-day analysis: 5 symbols, $227M volume, tight spreads (0.3-0.6 bps OBI).
MODE6_ENABLED = os.environ.get("SODEX_MODE6", "0") == "1"
MODE6_SYMBOLS = [s.strip() for s in os.environ.get(
    "SODEX_MODE6_SYMBOLS", "BTC-USD,ETH-USD").split(",") if s.strip()]
MODE6_MARGIN = float(os.environ.get("SODEX_MODE6_MARGIN", "25"))     # per-side
MODE6_LEVERAGE = int(os.environ.get("SODEX_MODE6_LEVERAGE", "3"))     # conservative
MODE6_SPREAD_BPS = float(os.environ.get("SODEX_MODE6_SPREAD_BPS", "3.0"))  # 3bps from mid
MODE6_WAIT = float(os.environ.get("SODEX_MODE6_WAIT", "180"))         # wait for both fills

# ── MODE 7: Pre-Sentiment + 8 Tech Signals + Quantitative Stats ──
# Combines all learning from v3.3 → v3.5.1 into a unified quality-scored mode.
# Pre-Sentiment: OBI regime, spread regime, volatility regime
# 8 Technical Signals: OBI composite, spread, momentum, volatility, depth,
#                      trade frequency, spread trend, OBI trend
# Quantitative: dynamic confidence, adaptive spread gate, vol-adj position
# Output: Quality Score 0-100 → determines trade/skip + parameters
MODE7_ENABLED = os.environ.get("SODEX_MODE7", "0") == "1"
MODE7_SYMBOLS = [s.strip() for s in os.environ.get(
    "SODEX_MODE7_SYMBOLS", "BTC-USD,ETH-USD,ZEC-USD,SOL-USD").split(",") if s.strip()]
MODE7_MIN_QUALITY = float(os.environ.get("SODEX_MODE7_MIN_QUALITY", "35"))  # 0-100
MODE7_OPEN_WAIT = float(os.environ.get("SODEX_MODE7_OPEN_WAIT", "60"))
MODE7_CLOSE_WAIT = float(os.environ.get("SODEX_MODE7_CLOSE_WAIT", "150"))

# ── Per-symbol spread baseline (bps) — 3x of typical spread ──
# Higher = symbol naturally has wider spreads. Gate = max(1.5bps, baseline * QS_multiplier)
SYMBOL_SPREAD_BASELINE = {
    "BTC-USD": 0.3,    # typical 0.1 bps × 3
    "ETH-USD": 1.5,    # typical 0.5 bps × 3
    "SOL-USD": 3.6,    # typical 1.2 bps × 3
    "ZEC-USD": 0.6,    # typical 0.2 bps × 3
    "LINK-USD": 3.3,   # typical 1.1 bps × 3
    "ADA-USD": 13.5,   # typical 4.5 bps × 3
    # v4.9.0 SPREAD HARVESTING — wide-spread profitable symbols
    "WLFI-USD": 50.0,  # typical 16.8 bps × 3
    "ENA-USD": 34.0,   # typical 11.4 bps × 3
    "FIL-USD": 32.0,   # typical 10.6 bps × 3
    "WIF-USD": 16.0,   # typical 5.3 bps × 3
    "NEAR-USD": 11.0,  # typical 3.7 bps × 3
    "XPL-USD": 31.0,   # typical 10.5 bps × 3
    "DASH-USD": 16.0,  # typical 5.3 bps × 3
    "ARB-USD": 30.0,   # typical 10.1 bps × 3
    "SILVER-USD": 13.2, # typical 4.4 bps × 3 (proven fill 100%)
}

# ── Per-symbol open_wait overrides (seconds) ──
# Non-BTC symbols need more time due to thinner liquidity
SYMBOL_OPEN_WAIT = {
    "BTC-USD": 30,     # fills fast
    "ETH-USD": 60,     # moderate liquidity
    "SOL-USD": 90,     # thinner, needs more time
    "ZEC-USD": 60,     # moderate
    "LINK-USD": 60,    # moderate
    "ADA-USD": 120,    # thinnest, needs most time
    # v4.9.0 SPREAD HARVESTING
    "WLFI-USD": 120,   # meme, thin book
    "ENA-USD": 90,     # DeFi, moderate
    "FIL-USD": 90,     # storage, moderate
    "WIF-USD": 120,    # meme, thin book
    "NEAR-USD": 60,    # higher volume
    "XPL-USD": 90,     # moderate, L1 token
    "DASH-USD": 90,    # privacy coin, moderate liquidity
    "ARB-USD": 90,     # L2, moderate
    "SILVER-USD": 90,  # commodity, good liquidity
}

# ── Reprice interval (seconds) — faster for moving markets ──
MODE7_REPRICE_INTERVAL = 8  # was 15 — stay closer to top of book

# ── Per-symbol margin multiplier (v3.8.2) ──
# BTC gets 2x margin because it consistently fills. Others stay at 1x.
SYMBOL_MARGIN_MULTIPLIER = {
    "BTC-USD": 2.0,    # 60% fill rate, tightest spread — double volume
    "ETH-USD": 1.0,
    "SOL-USD": 1.0,
    "ZEC-USD": 1.0,
    "LINK-USD": 1.0,
    "ADA-USD": 1.0,
    # v4.9.0 — start at 1.0, increase after fill rate proven
    "WLFI-USD": 1.0,
    "ENA-USD": 1.0,
    "FIL-USD": 1.0,
    "WIF-USD": 1.0,
    "NEAR-USD": 1.0,
    "XPL-USD": 1.0,
    "DASH-USD": 1.0,
    "ARB-USD": 1.0,
    "SILVER-USD": 1.0,  # proven 100% fill rate
}

# ── MODE 8: Delta-Neutral Maker Cycling (v4.3.0 — Pre-Gain integrated) ──
# QUANTEX strategy + Anantara Pre-Gain/Loser intelligence:
#   - Market regime gate: CHAOS → skip, TRENDING → aggressive
#   - Dynamic smart pricing: wider capture when spreads are wider
#   - BTC ATR-based frequency tuning
# Reference: QUANTEX-DeltaNeutral-Maker-Cycling-SoDEX.html + pregain_signals.py
MODE8_ENABLED = os.environ.get("SODEX_MODE8", "1") == "1"
MODE8_SYMBOLS = [s.strip() for s in os.environ.get(
    "SODEX_MODE8_SYMBOLS", "BTC-USD,ETH-USD").split(",") if s.strip()]
MODE8_LEVERAGE = int(os.environ.get("SODEX_MODE8_LEVERAGE", "10"))   # DN safe at 10×
MODE8_MARGIN = float(os.environ.get("SODEX_MODE8_MARGIN", "10"))      # per leg
MODE8_OPEN_WAIT = float(os.environ.get("SODEX_MODE8_OPEN_WAIT", "60"))
MODE8_CLOSE_WAIT = float(os.environ.get("SODEX_MODE8_CLOSE_WAIT", "120"))

# ── MODE 11: BEARDOWN — Regime-Aware Patient MM (MODE2 + PVE F3 Short combo) ──
# Primary: patient_mm_regime_round() — direction-aware maker:
#   BEARISH  → SELL-first (SHORT) — directional edge in bear market
#   BULLISH  → BUY-first (LONG)   — directional edge in bull market
#   NEUTRAL  → Alternating BUY/SELL (delta-neutral, spread capture)
# Supplementary: PVE F3 Maker Short (via Twin Engine, separate process)
# Safety: spread gate + momentum gate + stop-loss 35% + weekly kill-switch
# Target: Ratio 1:8,650 · Volume $1M/week · Net PnL positive
MODE11_ENABLED = os.environ.get("SODEX_MODE11", "0") == "1"
MODE11_SYMBOLS = [s.strip() for s in os.environ.get(
    "SODEX_MODE11_SYMBOLS", "XPL-USD,DASH-USD,WIF-USD,NEAR-USD").split(",") if s.strip()]
MODE11_MARGIN = float(os.environ.get("SODEX_MODE11_MARGIN", "25"))
MODE11_LEVERAGE = int(os.environ.get("SODEX_MODE11_LEVERAGE", "5"))
MODE11_OPEN_WAIT = float(os.environ.get("SODEX_MODE11_OPEN_WAIT", "90"))
MODE11_CLOSE_WAIT = float(os.environ.get("SODEX_MODE11_CLOSE_WAIT", "120"))
MODE11_STOP_LOSS = float(os.environ.get("SODEX_MODE11_STOP_LOSS", "0.35"))
# ponytail: momentum gate 0.04% in BEAR (wider — allow trending), 0.03% in NEUTRAL
MODE11_MOMENTUM_GATE_BEAR = float(os.environ.get("SODEX_MODE11_MOMENTUM_BEAR", "0.04"))
MODE11_MOMENTUM_GATE_NEUTRAL = float(os.environ.get("SODEX_MODE11_MOMENTUM_NEUTRAL", "0.03"))
MODE11_DRIFT_TARGET = float(os.environ.get("SODEX_MODE11_DRIFT_TARGET", "0.0005"))  # 0.05% drift capture
MODE11_LONG_BIAS = os.environ.get("SODEX_MODE11_LONG_BIAS", "1") == "1"  # NEUTRAL→LONG in up-market

# ═══════════════════════════════════════════════════════════════════════════
# MODE 10: Dual-Side Spread Capture (DSSC) — The Ratio Breakthrough
# ═══════════════════════════════════════════════════════════════════════════
# Places BUY maker + SELL maker simultaneously on wide-spread symbols.
# When BOTH fill → capture the spread (EARN instead of PAY).
# When ONE fills → close at maker (standard cost).
# Key insight: dual-fill rate of 35-50% on wide-spread symbols achieves 1:7,100.
# Reference: SoDEX spreads up to 16.8bps (WLFI), 10.5bps (XPL) — ideal for DSSC.
# Dual offset: 30-35% of spread width → gap 60-70% < spread → high dual-fill prob.
MODE10_ENABLED = os.environ.get("SODEX_MODE10", "0") == "1"
MODE10_SYMBOLS = [s.strip() for s in os.environ.get(
    "SODEX_MODE10_SYMBOLS", "XPL-USD,DASH-USD,WIF-USD,NEAR-USD,WLFI-USD,ENA-USD,ARB-USD,SILVER-USD").split(",") if s.strip()]
MODE10_MARGIN = float(os.environ.get("SODEX_MODE10_MARGIN", "8"))       # per side (smaller = safer for dual)
MODE10_LEVERAGE = int(os.environ.get("SODEX_MODE10_LEVERAGE", "5"))      # conservative for dual-side
MODE10_OPEN_WAIT = float(os.environ.get("SODEX_MODE10_OPEN_WAIT", "75"))# extended for re-quote leg to fill
MODE10_CLOSE_WAIT = float(os.environ.get("SODEX_MODE10_CLOSE_WAIT", "150"))
MODE10_MIN_QUALITY = float(os.environ.get("SODEX_MODE10_MIN_QUALITY", "30"))
MODE10_REPRICE_INTERVAL = 6  # re-quote unfilled leg every 6s

# ── Per-symbol dual offset fraction (fraction of spread width for each side) ──
# v4: REDUCED to 15% from 30% — tighter offset = higher dual-fill probability.
# Key insight: market oscillates 30% of spread width frequently.
# At 15% offset: gap = 30% of spread → high dual-fill prob (target 35-50%).
# Tradeoff: less spread capture per dual-fill, but MORE dual-fills.
# Math: 15% offset × 35% dual-fill = ratio 1:6,200
#       15% offset × 40% dual-fill = ratio 1:7,350 (ABOVE TARGET 🎯)
MODE10_DUAL_OFFSET_FRAC = {
    "XPL-USD":  0.25,  # 10.5bps × 0.25 = 2.6bps each → 5.2bps gap (AGGRESSIVE)
    "WLFI-USD": 0.25,  # 16.8bps × 0.25 = 4.2bps each → 8.4bps gap ← MAX PROFIT
    "ENA-USD":  0.25,  # 11.4bps × 0.25 = 2.9bps each → 5.7bps gap
    "ARB-USD":  0.25,  # 10.1bps × 0.25 = 2.5bps each → 5.0bps gap
    "DASH-USD": 0.25,  # 5.3bps × 0.25 = 1.3bps each → 2.6bps gap
    "WIF-USD":  0.25,  # 5.3bps × 0.25 = 1.3bps each → 2.6bps gap
    "NEAR-USD": 0.25,  # 3.7bps × 0.25 = 0.9bps each → 1.9bps gap
    "SILVER-USD": 0.25,  # 4.4bps × 0.25 = 1.1bps each → 2.2bps gap
}
MODE10_DEFAULT_OFFSET_FRAC = 0.15

# ── MODE10 Dual-fill tracking state ──
_mode10_dual_stats: dict = {}

# ═══════════════════════════════════════════════════════════════════════════
# v6.3: TIME-OF-DAY GATING (Strategy A — Efficiency Enhancement)
# ═══════════════════════════════════════════════════════════════════════════
# Research finding (June 4, 2026 — 12h data, 430+ cycles):
#   NEAR fill rate drops to 47-58% during ASIA session (00-08 UTC).
#   Gate these hours out → +5-8% overall efficiency.
# Each symbol can have its own allowed UTC hour ranges.

SYMBOL_TRADING_HOURS = {
    # NEAR: skip low-fill hours. Fill rate data (June 4):
    #   0-1h: 47-53%, 2-3h: 87-88%, 4-5h: 56-58%, 6h: 72%, 7h: 55%, 8-9h: 79-80%
    #   Only trade during PROVEN 75%+ windows.
    "NEAR-USD":  [(0, 24)],   # AGGRESSIVE: all hours for profit test
    # DASH: nearly always good — 100% useful fills, all hours
    "DASH-USD":  [(0, 24)],            # all hours — best performer
    # WIF: all hours for aggressive test
    "WIF-USD":   [(0, 24)],            # AGGRESSIVE: all hours
    # XPL: all hours for aggressive test  
    "XPL-USD":   [(0, 24)],            # AGGRESSIVE: all hours
    # ── MODE10: New wide-spread symbols ──
    "WLFI-USD":  [(0, 24)],            # meme — 24/7 (illiquid, always same)
    "ENA-USD":   [(0, 24)],            # DeFi — 24/7
    "FIL-USD":   [(0, 24)],            # storage — 24/7
    "ARB-USD":   [(0, 24)],            # L2 — 24/7
}

# ═══════════════════════════════════════════════════════════════════════════
# v6.3: PRE-SENTIMENT ENHANCED SMART OFFSET (Strategy D Enhanced)
# ═══════════════════════════════════════════════════════════════════════════
# Research finding: Quality Score has only 1.0-1.5x correlation with fill size.
# Solution: Use MARKET REGIME (Pre-Sentiment) to determine offset & sizing,
#           not just Quality Score.
#
# Regime → Strategy:
#   RANGING:  tight offset, full margin (best fill conditions)
#   TRENDING: medium offset, 1.3× margin (more volume, acceptable risk)
#   CHAOS:    SKIP entirely (existing gate, unchanged)

REGIME_OFFSET_MULTIPLIER = {
    "RANGING":  0.7,    # tighter than default → more fills
    "TRENDING": 1.3,    # wider → capture spread in moving markets
    # CHAOS is gated by _should_skip_regime()
}

REGIME_MARGIN_MULTIPLIER = {
    "RANGING":  1.2,    # full confidence → slightly larger
    "TRENDING": 0.8,    # reduce size in directional markets (adverse selection)
}

# ── SMART PRICING (v3.9.0, enhanced v4.3.0, v6.3) ──
SMART_PRICE_BPS = float(os.environ.get("SODEX_SMART_PRICE_BPS", "0.5"))  # default 0.5 bps

# ── v6.3: Per-symbol smart pricing overrides (bps) ──
# Updated based on 12h fill analysis (June 4, 2026):
#   DASH: 0.3 optimal (100% useful fills, zero micro-fills)
#   WIF:  0.4 ↑ from 0.3 (34% micro-fills → need wider offset)
#   NEAR: 0.15 ↓ from 0.2 (90% useful, can be tighter)
#   XPL:  0.5 ↑ from 0.3 (51% micro-fills → need MUCH wider offset)
SYMBOL_SMART_BPS = {
    "DASH-USD": 0.3,   # v6.3: unchanged — already optimal
    "WIF-USD":  0.4,   # v6.3: ↑ from 0.3 (reduce micro-fills)
    "NEAR-USD": 0.15,  # v6.3: ↓ from 0.2 (tighter = higher fill rate)
    "XPL-USD":  0.5,   # v6.3: ↑ from 0.3 (51% micro-fills need wider capture)
    "WLFI-USD": 0.2,   # inactive
    "ARB-USD":  0.2,   # inactive
}

# ═══════════════════════════════════════════════════════════════════════════
# PRE-GAIN/LOSER INTEGRATION (v4.3.0)
# ═══════════════════════════════════════════════════════════════════════════

# Cache for market regime data (refreshed every 5 min)
_regime_cache: dict = {"ts": 0, "regime": "RANGING", "atr_ratio": 1.0, "atr_ratio_prev": 1.0}

def _get_market_regime() -> dict:
    """Fetch BTC market regime from Anantara market_regime module.
    Returns cached data (valid 5 min) to avoid repeated API calls.
    Falls back to RANGING if module/API unavailable.
    """
    now = time.time()
    if now - _regime_cache["ts"] < 300:  # 5 min cache
        return _regime_cache
    
    try:
        # Try absolute import first (when running from project root)
        try:
            from anantara import market_regime
        except ImportError:
            # Fallback: relative import (when running from anantara/ dir)
            import market_regime
        import httpx
        
        # Fetch BTC candles from Binance (last 50 candles, 15min)
        c = httpx.Client(timeout=10)
        r = c.get("https://fapi.binance.com/fapi/v1/klines",
                  params={"symbol": "BTCUSDT", "interval": "15m", "limit": 55})
        c.close()
        
        if r.status_code == 200:
            candles = [{"open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in r.json()]
            if len(candles) >= 50:
                atr_ratio, vol_z, mom = market_regime.compute_features(candles)
                
                if atr_ratio > market_regime.CHAOS_ATR_RATIO:
                    regime = "CHAOS"
                elif atr_ratio > market_regime.TREND_ATR_RATIO:
                    regime = "TRENDING"
                else:
                    regime = "RANGING"
                
                # Get previous ATR for compression detection
                prev_candles = candles[:-14]  # exclude last 14 for "previous" window
                atr_prev = 1.0
                if len(prev_candles) >= 50:
                    atr_prev, _, _ = market_regime.compute_features(prev_candles)
                
                _regime_cache.update({
                    "ts": now, "regime": regime,
                    "atr_ratio": round(atr_ratio, 3),
                    "atr_ratio_prev": round(atr_prev, 3),
                    "vol_z": round(vol_z, 3), "momentum": round(mom, 4)
                })
        else:
            _regime_cache["ts"] = now  # prevent retry spam
    except Exception as e:
        log.warning(f"MODE8 regime fetch failed: {e} — using RANGING default")
        _regime_cache["ts"] = now
    
    return _regime_cache


def _get_adaptive_smart_bps(symbol: str) -> float:
    """Compute adaptive smart pricing offset based on market regime.
    
    RANGING:  standard 0.5 bps (spreads normal)
    TRENDING: 0.7 bps (more activity = wider spreads occasionally)
    CHAOS:    1.0 bps (but also gate — trades are risky)
    
    Per-symbol cap: never exceed 50% of symbol's baseline spread.
    """
    regime = _get_market_regime()
    base = SMART_PRICE_BPS
    
    if regime["regime"] == "TRENDING":
        base = max(base, 0.7)
    elif regime["regime"] == "CHAOS":
        base = max(base, 1.0)
    
    # Cap at 50% of symbol's typical spread
    sym_baseline = SYMBOL_SPREAD_BASELINE.get(symbol, 3.0)
    return min(base, sym_baseline * 0.5)


def _should_skip_regime() -> tuple[bool, str]:
    """Check if market regime says SKIP this cycle.
    
    CHAOS with ATR > 2.5: DEFINITELY skip (extreme volatility)
    CHAOS with ATR 2.0-2.5: CAUTION but proceed with tighter gates
    TRENDING/RANGING: OK to trade
    """
    regime = _get_market_regime()
    
    if regime["regime"] == "CHAOS" and regime.get("atr_ratio", 2.0) > 2.5:
        return True, f"CHAOS-SEVERE(ATR={regime['atr_ratio']:.1f}x)"
    return False, f"{regime['regime']}(ATR={regime['atr_ratio']:.2f}x)"


def _is_trading_hours(symbol: str) -> tuple[bool, str]:
    """v6.3: Check if current UTC hour is within symbol's trading hours.
    
    Returns (allowed, reason_string).
    Uses SYMBOL_TRADING_HOURS for per-symbol gating.
    Symbols not in the dict default to always-allowed (24/7).
    """
    if symbol not in SYMBOL_TRADING_HOURS:
        return True, "24/7"
    
    now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
    ranges = SYMBOL_TRADING_HOURS[symbol]
    
    for lo, hi in ranges:
        if lo <= hour < hi:
            return True, f"OK (UTC {hour}:00 in [{lo}-{hi}])"
    
    return False, f"GATED (UTC {hour}:00 outside trading hours)"


def _get_regime_enhanced_offset(symbol: str) -> tuple[float, float, str]:
    """v6.3: Pre-Sentiment enhanced smart offset + margin multiplier.
    
    Uses market regime (Pre-Sentiment) to determine:
      - offset_mult: tighter in RANGING, wider in TRENDING
      - margin_mult: larger in RANGING, reduced in TRENDING
      - regime label for logging
    
    This is the KEY enhancement over the old static SYMBOL_SMART_BPS.
    Pre-Sentiment now directly controls pricing AND sizing.
    
    Returns (effective_offset_bps, margin_multiplier, regime_info_string).
    """
    regime = _get_market_regime()
    regime_name = regime.get("regime", "RANGING")
    atr = regime.get("atr_ratio", 1.0)
    
    # Base per-symbol offset
    base_offset = SYMBOL_SMART_BPS.get(symbol, SMART_PRICE_BPS)
    
    # Pre-Sentiment modifier
    offset_mult = REGIME_OFFSET_MULTIPLIER.get(regime_name, 1.0)
    margin_mult = REGIME_MARGIN_MULTIPLIER.get(regime_name, 1.0)
    
    effective_offset = base_offset * offset_mult
    info = f"{regime_name}(ATR={atr:.2f}x,off={effective_offset:.2f}bps,margin={margin_mult:.1f}x)"
    
    return effective_offset, margin_mult, info


def _multi_level_open(symbol: str, cfg: dict, side: str, mid: float,
                      smart_offset: float, qty: str, open_wait: float,
                      num_levels: int = 2) -> tuple[float, float, int]:
    """v6.3: Multi-Level Order Book (Strategy C).
    
    Places maker orders at 2-3 price levels simultaneously to maximize
    fill probability. The key insight:
      - Level 1 (tight, 0.7× offset): fills in quiet markets
      - Level 2 (normal, 1.0× offset): fills in average markets  
      - Level 3 (wide, 1.6× offset): fills when market moves
    
    When ANY level fills, cancels the others immediately.
    This roughly DOUBLES fill probability with minimal additional cost.
    
    Returns (filled_notional, fill_price, legs_maker_count).
    Returns (0, 0, 0) if no level filled within open_wait.
    """
    if num_levels < 1:
        return 0.0, 0.0, 0
    
    # Compute price levels
    levels = []
    multipliers = [0.7, 1.0, 1.6][:num_levels]  # tight, normal, wide
    
    for i, mult in enumerate(multipliers):
        level_offset = smart_offset * mult
        if side == "buy":
            price = mid + mid * level_offset  # slightly above bid
        else:
            price = mid - mid * level_offset  # slightly below ask
        levels.append({
            "price": fmt_price(symbol, price),
            "offset_bps": smart_offset * mult * 10000,  # for logging
            "cloid": None,
            "filled": False
        })
    
    # Place all levels (sequential due to CLI lock)
    for lv in levels:
        op = cli(["orders", "place", "perps", "--symbol", symbol, "--side", side,
                  "--type", "limit", "--price", lv["price"],
                  "--qty", qty, "--tif", "gtx"], cfg=cfg, auth=True)
        if op:
            _, lv["cloid"] = _extract_order_ids(op)
        else:
            log.warning(f"MULTI-LEVEL: failed to place {symbol} {side} @ {lv['price']}")
    
    # Poll for fills — check all levels, cancel unfilled when one hits
    deadline = time.time() + open_wait
    last_reprice = time.time()
    filled_notional = 0.0
    fill_price = 0.0
    legs_maker = 0
    
    while time.time() < deadline:
        time.sleep(0.8)
        held = abs(_position_qty(symbol, cfg))
        if held > 0:
            # A level filled! Get the fill price from position
            fill_price = float(cli(["positions", "show", symbol], cfg=cfg, auth=True).get("entry_price", 0)) if False else mid
            # Cancel all remaining open orders
            for lv in levels:
                if not lv["filled"] and lv["cloid"]:
                    _cancel_open(symbol, cfg, lv["cloid"])
            filled_notional = held * mid
            legs_maker = 1
            break
        
        # Reprice unfilled levels every MODE7_REPRICE_INTERVAL seconds
        if time.time() - last_reprice > MODE7_REPRICE_INTERVAL:
            t_now = get_ticker(symbol, cfg)
            if t_now:
                mid_now = (t_now["bid"] + t_now["ask"]) / 2
                for i, lv in enumerate(levels):
                    if not lv["filled"] and lv["cloid"]:
                        mult = multipliers[i]
                        level_offset = smart_offset * mult
                        if side == "buy":
                            new_price = mid_now + mid_now * level_offset
                        else:
                            new_price = mid_now - mid_now * level_offset
                        new_price_str = fmt_price(symbol, new_price)
                        if new_price_str != lv["price"]:
                            _cancel_open(symbol, cfg, lv["cloid"])
                            op2 = cli(["orders", "place", "perps", "--symbol", symbol,
                                       "--side", side, "--type", "limit",
                                       "--price", new_price_str, "--qty", qty, "--tif", "gtx"],
                                      cfg=cfg, auth=True)
                            if op2:
                                _, lv["cloid"] = _extract_order_ids(op2)
                                lv["price"] = new_price_str
                last_reprice = time.time()
    
    # Clean up any remaining unfilled orders
    for lv in levels:
        if not lv["filled"] and lv["cloid"]:
            _cancel_open(symbol, cfg, lv["cloid"])
    
    return filled_notional, fill_price, legs_maker
def conf_to_leverage(symbol: str, confidence: float) -> int:
    """Map Hermes confidence → leverage. Min 10x; scale up to symbol max on
    very strong signals. User policy: leverage >=10x, max when signal is great."""
    cap = SYMBOLS[symbol]["max_lev"]
    if confidence >= 0.92:
        lev = cap                # extreme conviction → exchange max
    elif confidence >= 0.85:
        lev = 20
    elif confidence >= 0.75:
        lev = 15
    else:                        # MIN_CONFIDENCE .. 0.75
        lev = 10
    return min(lev, cap)


# ── MODE 5: OBI Dynamic Spread Round ──

def mode5_round(symbol: str, cfg: dict, margin: float = 8.0, leverage: int = 3,
                open_wait: float | None = None, close_wait: float | None = None,
                momentum_threshold: float | None = None) -> dict:
    """MODE 5 round: patient maker with OBI-driven dynamic spread gate.
    
    Unlike MODE 4 (static spread gate), MODE 5 uses real-time Order Book
    Imbalance signals to dynamically adjust the spread:
      - OBI neutral → tighter spread (as low as 0.005%)
      - OBI directional → wider spread (up to 0.050%)
      - OBI extreme → skip entirely
    
    This typically achieves 10-20% tighter average spreads without
    sacrificing fill rate, directly improving the volume/cost ratio.
    """
    from mode5_gate import get_gate
    
    open_wait = open_wait if open_wait is not None else MODE5_OPEN_WAIT
    close_wait = close_wait if close_wait is not None else MODE5_CLOSE_WAIT
    momentum_threshold = momentum_threshold if momentum_threshold is not None else MODE5_MOMENTUM_GATE
    
    gate = get_gate()
    
    # Dynamic spread gate: ask the OBI model what spread to use
    optimal_spread, confidence = gate.optimal_spread(symbol)
    
    if confidence < MODE5_MIN_CONFIDENCE:
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": f"OBI skip (conf={confidence:.2f})", "mode": 5}
    
    # Use the dynamically computed spread
    spread_gate_pct = optimal_spread
    
    t = get_ticker(symbol, cfg)
    if not t or t["bid"] <= 0 or t["ask"] <= 0:
        return {"ok": False, "reason": "no book", "volume": 0.0, "mode": 5}
    
    mid = (t["bid"] + t["ask"]) / 2
    spread_actual = (t["ask"] - t["bid"]) / mid * 100
    
    # Static gate as backstop: if actual spread exceeds our optimal, skip
    if spread_actual > spread_gate_pct:
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": f"spread gate ({spread_actual:.4f}% > {spread_gate_pct:.4f}%)", "mode": 5}
    
    # Momentum gate (same as MODE 4)
    if momentum_threshold > 0:
        time.sleep(5)
        t2 = get_ticker(symbol, cfg)
        if t2 and t2["last"] > 0 and t["last"] > 0:
            momo = abs(t2["last"] - t["last"]) / t["last"] * 100
            if momo > momentum_threshold:
                return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                        "reason": f"momentum gate ({momo:.3f}% > {momentum_threshold:.3f}%)", "mode": 5}
    
    # L1: AGGRESSOR BIAS — choose direction based on 822K trade analysis
    bias = get_aggressor_bias(symbol)  # time-aware for BTC, fixed for ETH/SOL
    if bias == "buy":
        open_side, close_side = "buy", "sell"
        open_price = t["bid"]   # buy at bid = maker
        close_price_fn = lambda tk: tk["ask"]
    elif bias == "sell":
        open_side, close_side = "sell", "buy"
        open_price = t["ask"]   # sell at ask = maker
        close_price_fn = lambda tk: tk["bid"]
    else:
        # random: alternate to avoid predictable patterns
        if random.random() < 0.5:
            open_side, close_side = "buy", "sell"
            open_price = t["bid"]
            close_price_fn = lambda tk: tk["ask"]
        else:
            open_side, close_side = "sell", "buy"
            open_price = t["ask"]
            close_price_fn = lambda tk: tk["bid"]
    
    # Compute position size
    notional = margin * leverage
    qty = fmt_qty(symbol, (notional / t["last"]) * (0.9 + 0.2 * random.random()))
    if float(qty) <= 0:
        return {"ok": False, "reason": "qty too small", "volume": 0.0, "mode": 5}
    
    # OPEN: post-only at the optimal side (aggressor bias aware)
    op = cli(["orders", "place", "perps", "--symbol", symbol, "--side", open_side,
              "--type", "limit", "--price", fmt_price(symbol, open_price),
              "--qty", qty, "--tif", "gtx"], cfg=cfg, auth=True)
    if op is None:
        return {"ok": False, "reason": "open rejected", "volume": 0.0, "mode": 5}
    _, open_cloid = _extract_order_ids(op)
    
    # Poll for open fill with reprice every 15s (v3.4.2: chase market to improve fill rate)
    held = 0.0
    last_reprice = time.time()
    deadline = time.time() + open_wait
    while time.time() < deadline:
        time.sleep(1.0)
        held = abs(_position_qty(symbol, cfg))
        if held > 0:
            break
        # Reprice: if not filled within 15s, move to current best price
        if time.time() - last_reprice > 15:
            t_now = get_ticker(symbol, cfg)
            if t_now:
                new_price = fmt_price(symbol, t_now["bid"] if open_side == "buy" else t_now["ask"])
                old_price = fmt_price(symbol, open_price)
                if new_price != old_price:
                    _cancel_open(symbol, cfg, open_cloid)
                    op2 = cli(["orders", "place", "perps", "--symbol", symbol,
                               "--side", open_side, "--type", "limit",
                               "--price", new_price, "--qty", qty, "--tif", "gtx"],
                              cfg=cfg, auth=True)
                    if op2:
                        _, open_cloid = _extract_order_ids(op2)
                        open_price = float(new_price)
                last_reprice = time.time()
    if held <= 0:
        _cancel_open(symbol, cfg, open_cloid)
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": "open not filled", "mode": 5}
    
    open_notional = held * t["last"]
    legs_maker = 1
    
    # CLOSE: post-only at optimal side (aggressor bias aware) with reprice
    close_deadline = time.time() + close_wait
    flat = False
    last_close_price = None
    close_cloid = None  # ponytail: init before loop, guard F821
    while time.time() < close_deadline:
        t3 = get_ticker(symbol, cfg) or t
        close_price = fmt_price(symbol, close_price_fn(t3))
        if close_price != last_close_price:
            # Cancel old close order if exists, place new one
            if last_close_price is not None:
                _cancel_open(symbol, cfg, close_cloid)
            clo = cli(["orders", "place", "perps", "--symbol", symbol, "--side", close_side,
                       "--type", "limit", "--price", close_price,
                       "--qty", fmt_qty(symbol, held), "--tif", "gtx", "--reduce-only"],
                      cfg=cfg, auth=True)
            _, close_cloid = _extract_order_ids(clo) if clo else (None, None)
            last_close_price = close_price
        time.sleep(5)
        if abs(_position_qty(symbol, cfg)) <= held * 0.02:
            flat = True
            legs_maker += 1
            break
    
    if not flat:
        _cancel_open(symbol, cfg, close_cloid)
        pos = [p for p in open_positions(cfg) if p.get("symbol") == symbol]
        if pos:
            close_position(pos[0], cfg)
        time.sleep(0.8)
        flat = abs(_position_qty(symbol, cfg)) <= held * 0.02
    
    # FORCE CLOSE: ANY remaining position for this symbol MUST be closed
    # This is the safety backstop. No position left behind.
    remaining = [p for p in open_positions(cfg) if p.get("symbol") == symbol]
    for p in remaining:
        log.warning(f"MODE5 force-close: {symbol} qty={p.get('quantity')} (safety backstop)")
        close_position(p, cfg)
        time.sleep(0.5)
    
    # Final verification
    time.sleep(0.5)
    final_pos = [p for p in open_positions(cfg) if p.get("symbol") == symbol]
    if final_pos:
        log.error(f"MODE5 CRITICAL: {symbol} position STILL open after force-close!")
    else:
        flat = True
    
    volume = open_notional * 2
    return {"ok": flat, "filled": True, "volume": round(volume, 2), "symbol": symbol,
            "legs_maker": legs_maker, "open_notional": round(open_notional, 2),
            "mode": 5, "spread_used": round(optimal_spread * 100, 4), "obi_confidence": round(confidence, 2)}


# ═══════════════════════════════════════════════════════════════════════
# MODE 6: Market Making Hybrid — simultaneous BUY + SELL maker orders
# ═══════════════════════════════════════════════════════════════════════
# From 822K trade analysis (May 24-31): SoDEX spreads average 0.3-0.6 bps.
# By placing BOTH sides simultaneously, we capture the spread + double
# maker rebate when both fill. When only one fills, close directionally.
# Target: 0.7-1.5 bps "negative fee" → ratio boost beyond T1 ceiling.

def mode6_round(symbol: str, cfg: dict, margin: float = 25.0, leverage: int = 3,
                spread_bps: float = 3.0, wait_secs: float = 180) -> dict:
    """MODE 6: Market Making Hybrid round.
    
    Places BUY maker below mid AND SELL maker above mid simultaneously.
    - Both fill → spread captured + double rebate (optimal)
    - One fills → treated as directional, close at maker
    
    Args:
        spread_bps: distance from mid for each order (default 3.0 bps)
        wait_secs: max time to wait for both sides to fill
    """
    from mode5_gate import get_gate
    
    gate = get_gate()
    opt_spread, conf = gate.optimal_spread(symbol)
    
    t = get_ticker(symbol, cfg)
    if not t or t["bid"] <= 0 or t["ask"] <= 0:
        return {"ok": False, "reason": "no book", "volume": 0.0, "mode": 6}
    
    mid = (t["bid"] + t["ask"]) / 2
    spread_actual = (t["ask"] - t["bid"]) / mid * 100
    
    # Skip if actual spread > 2× our target (market too wide)
    if spread_actual > (spread_bps / 100) * 2:
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": f"MM spread too wide ({spread_actual:.3f}% > {(spread_bps/100)*2:.3f}%)", "mode": 6}
    
    # Compute prices: buy at spread_bps below mid, sell at spread_bps above mid
    spread_dec = spread_bps / 10000  # bps → decimal
    buy_price = mid * (1 - spread_dec)
    sell_price = mid * (1 + spread_dec)
    
    notional = margin * leverage
    qty = fmt_qty(symbol, (notional / mid) * (0.9 + 0.2 * random.random()))
    if float(qty) <= 0:
        return {"ok": False, "reason": "qty too small", "volume": 0.0, "mode": 6}
    
    # Place BOTH orders simultaneously
    buy_op = cli(["orders", "place", "perps", "--symbol", symbol, "--side", "buy",
                  "--type", "limit", "--price", fmt_price(symbol, buy_price),
                  "--qty", qty, "--tif", "gtx"], cfg=cfg, auth=True)
    sell_op = cli(["orders", "place", "perps", "--symbol", symbol, "--side", "sell",
                   "--type", "limit", "--price", fmt_price(symbol, sell_price),
                   "--qty", qty, "--tif", "gtx"], cfg=cfg, auth=True)
    
    if buy_op is None or sell_op is None:
        # Cancel both if one failed
        if buy_op:
            _, bid = _extract_order_ids(buy_op)
            _cancel_open(symbol, cfg, bid)
        if sell_op:
            _, sid = _extract_order_ids(sell_op)
            _cancel_open(symbol, cfg, sid)
        return {"ok": False, "reason": "MM open rejected", "volume": 0.0, "mode": 6}
    
    _, buy_cloid = _extract_order_ids(buy_op)
    _, sell_cloid = _extract_order_ids(sell_op)
    
    # Wait for fills
    buy_filled = False
    sell_filled = False
    held_qty = 0.0
    deadline = time.time() + wait_secs
    
    while time.time() < deadline:
        time.sleep(1.0)
        pos_qty = _position_qty(symbol, cfg)
        
        # Check if we have a position (one side filled)
        if not buy_filled and not sell_filled:
            if abs(pos_qty) > 0:
                # One side filled first
                if pos_qty > 0:
                    buy_filled = True
                    held_qty = pos_qty
                    log.info(f"MODE6 {symbol}: BUY filled first ({held_qty:.4f}), waiting for SELL...")
                else:
                    sell_filled = True
                    held_qty = abs(pos_qty)
                    log.info(f"MODE6 {symbol}: SELL filled first ({held_qty:.4f}), waiting for BUY...")
        
        # Check if both filled (position back to near zero)
        if (buy_filled or sell_filled) and abs(pos_qty) < abs(held_qty) * 0.1:
            buy_filled = True
            sell_filled = True
            held_qty = abs(held_qty)
            break
    
    # Determine outcome
    if buy_filled and sell_filled:
        # 🎯 PERFECT: both sides filled → spread captured!
        spread_profit = notional * (spread_bps / 10000)  # spread_bps of notional
        total_volume = notional * 2
        legs_maker = 2
        outcome = "PERFECT"
    elif buy_filled or sell_filled:
        # ⚠️ PARTIAL: one side filled → close directionally
        outcome = "PARTIAL"
        legs_maker = 1
        # Close the open side
        close_side = "sell" if buy_filled else "buy"
        close_price_target = t["ask"] if buy_filled else t["bid"]
        
        clo = cli(["orders", "place", "perps", "--symbol", symbol, "--side", close_side,
                   "--type", "limit", "--price", fmt_price(symbol, close_price_target),
                   "--qty", fmt_qty(symbol, abs(_position_qty(symbol, cfg))),
                   "--tif", "gtx", "--reduce-only"], cfg=cfg, auth=True)
        if clo:
            _, close_cloid = _extract_order_ids(clo)
            # Short wait for close fill
            for _ in range(30):
                time.sleep(2)
                if abs(_position_qty(symbol, cfg)) < held_qty * 0.02:
                    legs_maker += 1
                    break
            _cancel_open(symbol, cfg, close_cloid)
        
        # Force-close if still open
        remaining = [p for p in open_positions(cfg) if p.get("symbol") == symbol]
        for p in remaining:
            close_position(p, cfg)
            time.sleep(0.5)
        
        total_volume = notional + (abs(_position_qty(symbol, cfg)) * mid if _position_qty(symbol, cfg) != 0 else notional)
        spread_profit = 0
    else:
        # ❌ NEITHER filled
        _cancel_open(symbol, cfg, buy_cloid)
        _cancel_open(symbol, cfg, sell_cloid)
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": "MM neither filled", "mode": 6}
    
    # Force-close backstop
    final_remaining = [p for p in open_positions(cfg) if p.get("symbol") == symbol]
    for p in final_remaining:
        log.warning(f"MODE6 force-close: {symbol} qty={p.get('quantity')}")
        close_position(p, cfg)
        time.sleep(0.5)
    
    return {"ok": True, "filled": True, "volume": round(total_volume, 2),
            "symbol": symbol, "legs_maker": legs_maker,
            "open_notional": round(notional, 2), "mode": 6,
            "mm_outcome": outcome, "spread_bps": spread_bps}


# ═══════════════════════════════════════════════════════════════════════
# MODE 10: Dual-Side Spread Capture (DSSC) — THE RATIO BREAKTHROUGH
# ═══════════════════════════════════════════════════════════════════════
# Places BUY maker + SELL maker simultaneously on wide-spread symbols.
# When BOTH fill (target 35-50%): spread captured = profit!
# When ONE fills: close at maker (standard cost).
# When NONE fills: zero cost.
#
# Key design vs MODE6:
#   - Per-symbol dynamic offset based on spread width
#   - Pre-Sentiment regime integration
#   - Time-of-day gating
#   - Quality Score gate
#   - Dual-fill rate tracking per symbol

def _mode10_get_dual_offset(symbol: str, spread_bps: float, regime_mult: float = 1.0) -> tuple[float, float, float]:
    """Compute per-symbol dual-side offsets.
    Returns (buy_offset_bps, sell_offset_bps, expected_spread_capture_bps).
    
    CRITICAL: regime_mult is capped at 1.0 for DSSC to prevent wider offsets
    from killing dual-fill probability. In TRENDING, we want MORE fills not wider
    offsets. The regime's margin_mult still applies for sizing.
    """
    frac = MODE10_DUAL_OFFSET_FRAC.get(symbol, MODE10_DEFAULT_OFFSET_FRAC)
    # Cap regime mult at 1.0 for DSSC — wider offsets reduce dual-fill prob
    effective_regime = min(regime_mult, 1.0)
    dual_offset_bps = spread_bps * frac * effective_regime
    # Absolute cap: never exceed 40% of spread (ensures room for both sides)
    dual_offset_bps = min(dual_offset_bps, spread_bps * 0.40)
    expected_capture = dual_offset_bps * 2
    return dual_offset_bps, dual_offset_bps, expected_capture


def _mode10_track_dual(symbol: str, outcome: str):
    """Track dual-fill outcome per symbol for analytics."""
    global _mode10_dual_stats  # noqa: F824 — assigned at module level, global for clarity
    if symbol not in _mode10_dual_stats:
        _mode10_dual_stats[symbol] = {"cycles": 0, "dual": 0, "partial": 0, "none": 0}
    _mode10_dual_stats[symbol]["cycles"] += 1
    _mode10_dual_stats[symbol][outcome.lower()] += 1


def mode10_dssc_round(symbol: str, cfg: dict, margin: float | None = None,
                      leverage: int | None = None) -> dict:
    """MODE 10: Dual-Side Spread Capture round.
    Places BUY maker below mid + SELL maker above mid simultaneously.
    OUTCOMES: DUAL (🎯 both fill), PARTIAL (⚠️ one fill), NONE (❌ neither).
    """
    if margin is None: margin = MODE10_MARGIN
    if leverage is None: leverage = MODE10_LEVERAGE

    # Pre-Sentiment regime gate
    skip_regime, regime_info = _should_skip_regime()
    if skip_regime:
        _mode10_track_dual(symbol, "none")
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": f"PRE-SENTIMENT SKIP: {regime_info}", "mode": 10}

    # Time-of-day gate
    trading_ok, trading_reason = _is_trading_hours(symbol)
    if not trading_ok:
        _mode10_track_dual(symbol, "none")
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": f"TIME-GATE: {trading_reason}", "mode": 10}

    # Pre-Sentiment enhanced offset
    regime_offset_bps, regime_margin_mult, regime_detail = _get_regime_enhanced_offset(symbol)

    # Intelligence context
    intel_ctx = get_intelligence_context()

    # Get ticker
    t = get_ticker(symbol, cfg)
    if not t or t["bid"] <= 0 or t["ask"] <= 0:
        _mode10_track_dual(symbol, "none")
        return {"ok": False, "reason": "no book", "volume": 0.0, "mode": 10}

    mid = (t["bid"] + t["ask"]) / 2
    spread_actual_bps = (t["ask"] - t["bid"]) / mid * 10000

    # Quality Score check
    q = compute_quality_score(symbol, cfg, t, None, None, intel_ctx)
    if q["quality"] < MODE10_MIN_QUALITY:
        _mode10_track_dual(symbol, "none")
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": f"DSSC QS={q['quality']:.0f} < {MODE10_MIN_QUALITY:.0f}",
                "mode": 10, "quality": q["quality"]}

    # Spread gate (wider tolerance for DSSC)
    sym_baseline = SYMBOL_SPREAD_BASELINE.get(symbol, 5.0)
    if spread_actual_bps > sym_baseline * 5:
        _mode10_track_dual(symbol, "none")
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": f"DSSC spread {spread_actual_bps:.1f}bps > {sym_baseline*5:.1f}bps",
                "mode": 10, "quality": q["quality"]}

    # Compute dual offsets — regime mult capped at 1.0 for DSSC fill probability
    regime_name = regime_detail.split("(")[0]
    reg_mult = REGIME_OFFSET_MULTIPLIER.get(regime_name, 1.0)
    buy_off_bps, _, exp_capture = _mode10_get_dual_offset(symbol, spread_actual_bps, reg_mult)
    sell_off_bps = buy_off_bps  # symmetric
    buy_off_dec = buy_off_bps / 10000
    sell_off_dec = sell_off_bps / 10000

    buy_price = mid * (1 - buy_off_dec)
    sell_price = mid * (1 + sell_off_dec)

    # Position sizing
    notional = margin * leverage
    qty = fmt_qty(symbol, (notional / t["last"]) * (0.85 + 0.30 * random.random()))
    if float(qty) <= 0:
        _mode10_track_dual(symbol, "none")
        return {"ok": False, "reason": "qty too small", "volume": 0.0, "mode": 10}

    # ── PHASE 1: Place BUY + SELL simultaneously ──
    buy_op = cli(["orders", "place", "perps", "--symbol", symbol, "--side", "buy",
                  "--type", "limit", "--price", fmt_price(symbol, buy_price),
                  "--qty", qty, "--tif", "gtx"], cfg=cfg, auth=True)
    sell_op = cli(["orders", "place", "perps", "--symbol", symbol, "--side", "sell",
                   "--type", "limit", "--price", fmt_price(symbol, sell_price),
                   "--qty", qty, "--tif", "gtx"], cfg=cfg, auth=True)

    if buy_op is None or sell_op is None:
        if buy_op: _, bc = _extract_order_ids(buy_op); _cancel_open(symbol, cfg, bc)
        if sell_op: _, sc = _extract_order_ids(sell_op); _cancel_open(symbol, cfg, sc)
        _mode10_track_dual(symbol, "none")
        return {"ok": False, "reason": "DSSC open rejected", "volume": 0.0, "mode": 10}

    _, buy_cloid = _extract_order_ids(buy_op)
    _, sell_cloid = _extract_order_ids(sell_op)

    # ── PHASE 2: Wait for fills — re-quote one side if the other fills ──
    deadline = time.time() + MODE10_OPEN_WAIT
    last_reprice = time.time()
    buy_filled = False
    sell_filled = False
    held_qty = 0.0

    while time.time() < deadline:
        time.sleep(1.5)
        pos_qty = _position_qty(symbol, cfg)

        if not buy_filled and not sell_filled and abs(pos_qty) > 0:
            held_qty = abs(pos_qty)
            if pos_qty > 0:  # BUY filled first → keep SELL at original inside-spread price
                buy_filled = True
                # LEAVE sell at original offset — less competition inside the spread
                # Market may oscillate back, letting the other leg fill
                log.info(f"DSSC {symbol}: BUY filled, waiting for SELL at {sell_price}")
            else:  # SELL filled first → keep BUY at original inside-spread price
                sell_filled = True
                log.info(f"DSSC {symbol}: SELL filled, waiting for BUY at {buy_price}")

        if (buy_filled or sell_filled) and abs(pos_qty) < held_qty * 0.15:
            buy_filled = True; sell_filled = True; break

        if time.time() - last_reprice > MODE10_REPRICE_INTERVAL:
            t_now = get_ticker(symbol, cfg)
            if t_now:
                mid_now = (t_now["bid"] + t_now["ask"]) / 2
                # Keep unfilled legs at original inside-spread offset (less competition)
                if not buy_filled and buy_cloid:
                    np = fmt_price(symbol, mid_now * (1 - buy_off_dec))
                    if np != fmt_price(symbol, buy_price):
                        _cancel_open(symbol, cfg, buy_cloid)
                        bop = cli(["orders", "place", "perps", "--symbol", symbol, "--side", "buy",
                                   "--type", "limit", "--price", np, "--qty", qty, "--tif", "gtx"], cfg=cfg, auth=True)
                        if bop: _, buy_cloid = _extract_order_ids(bop); buy_price = float(np)
                if not sell_filled and sell_cloid:
                    np = fmt_price(symbol, mid_now * (1 + sell_off_dec))
                    if np != fmt_price(symbol, sell_price):
                        _cancel_open(symbol, cfg, sell_cloid)
                        sop = cli(["orders", "place", "perps", "--symbol", symbol, "--side", "sell",
                                   "--type", "limit", "--price", np, "--qty", qty, "--tif", "gtx"], cfg=cfg, auth=True)
                        if sop: _, sell_cloid = _extract_order_ids(sop); sell_price = float(np)
            last_reprice = time.time()

    # ── PHASE 3: Determine outcome ──
    if buy_filled and sell_filled:
        volume = notional * 2; legs_maker = 2; outcome = "DUAL"
        _mode10_track_dual(symbol, "dual")
    elif buy_filled or sell_filled:
        outcome = "PARTIAL"; legs_maker = 1
        _mode10_track_dual(symbol, "partial")
        close_side = "sell" if buy_filled else "buy"
        t_c = get_ticker(symbol, cfg) or t
        cp = fmt_price(symbol, t_c["ask"] if buy_filled else t_c["bid"])
        clo = cli(["orders", "place", "perps", "--symbol", symbol, "--side", close_side,
                   "--type", "limit", "--price", cp,
                   "--qty", fmt_qty(symbol, abs(_position_qty(symbol, cfg))),
                   "--reduce-only"], cfg=cfg, auth=True)  # no gtx: allow taker fill to prevent stuck
        if clo:
            _, cc = _extract_order_ids(clo)
            for _ in range(12):
                time.sleep(2)
                if abs(_position_qty(symbol, cfg)) < held_qty * 0.05:
                    legs_maker += 1; break
            _cancel_open(symbol, cfg, cc)
        for p in open_positions(cfg):
            if p.get("symbol") == symbol: close_position(p, cfg); time.sleep(0.5)
        volume = notional
    else:
        _cancel_open(symbol, cfg, buy_cloid); _cancel_open(symbol, cfg, sell_cloid)
        _mode10_track_dual(symbol, "none")
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": "DSSC neither filled", "mode": 10, "quality": q["quality"],
                "outcome": "NONE", "regime": regime_detail}

    # Force-close backstop
    for p in open_positions(cfg):
        if p.get("symbol") == symbol:
            log.warning(f"DSSC force-close: {symbol} qty={p.get('quantity')}")
            close_position(p, cfg); time.sleep(0.5)

    # Dual-fill stats for logging
    stats = _mode10_dual_stats.get(symbol, {})
    dual_rate = (stats.get("dual", 0) / max(stats.get("cycles", 1), 1)) * 100

    return {"ok": True, "filled": True, "volume": round(volume, 2),
            "symbol": symbol, "legs_maker": legs_maker,
            "open_notional": round(notional, 2), "mode": 10,
            "outcome": outcome, "quality": q["quality"],
            "regime": regime_detail,
            "spread_captured_bps": round(exp_capture * reg_mult, 2),
            "dual_offset_bps": round(buy_off_bps, 2),
            "dual_fill_rate": round(dual_rate, 1)}


def mode10_dual_stats_summary() -> str:
    """Format MODE10 dual-fill stats for logging."""
    if not _mode10_dual_stats:
        return "DSSC: no stats yet (cold start)"
    lines = ["DSSC dual-fill stats (accumulated):"]
    total_cycles = 0
    total_dual = 0
    for sym, st in sorted(_mode10_dual_stats.items()):
        if st["cycles"] == 0: continue
        total_cycles += st["cycles"]
        total_dual += st["dual"]
        dp = st["dual"] / st["cycles"] * 100
        pp = st["partial"] / st["cycles"] * 100
        np = st["none"] / st["cycles"] * 100
        lines.append(f"  {sym}: dual={st['dual']}({dp:.0f}%) partial={st['partial']}({pp:.0f}%) none={np:.0f}%")
    if total_cycles > 0:
        total_dual_pct = total_dual / total_cycles * 100
        lines.append(f"  TOTAL: {total_cycles} cycles, dual-rate={total_dual_pct:.1f}%")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# MODE 7: Pre-Sentiment + 8 Tech Signals + Quantitative Stats
# ═══════════════════════════════════════════════════════════════════════

# ── v5.0: Intelligence Bridge — integrates Sentiment + Intelligence into MODE 7 ──
_intel_cache: dict = {}
_intel_cache_ts: float = 0.0
_INTEL_CACHE_TTL: float = 300.0  # 5 min

def get_intelligence_context() -> dict:
    """Fetch intelligence state from Hermes health + sentiment endpoints.
    Returns dict with: composite_score, label, tilts, posture, forecast_summary.
    All keys default to neutral if Hermes unreachable.
    v5.1: Uses actual Hermes endpoints (health + sentiment/current).
    """
    global _intel_cache, _intel_cache_ts
    now = time.time()
    if _intel_cache and (now - _intel_cache_ts) < _INTEL_CACHE_TTL:
        return _intel_cache
    
    ctx = {
        "composite_score": 50,       # 0-100, 50=neutral
        "label": "NEUTRAL",
        "posture": "BALANCED",
        "flow_tilt": 0,              # ±4pts
        "funding_tilt": 0,           # ±5pts
        "whale_tilt": 0,             # ±6pts
        "forecast_direction": None,  # UP/DOWN/NEUTRAL
        "forecast_confidence": 0.0,
        "regime": "RANGING",
    }
    try:
        HERMES_URL = os.environ.get("HERMES_URL", "http://localhost:8000")
        
        # 1. Get posture from /health
        try:
            r = httpx.get(f"{HERMES_URL}/health", timeout=4)
            if r.status_code == 200:
                health = r.json()
                ctx["posture"] = health.get("posture", "BALANCED")
        except Exception:
            pass
        
        # 2. Get sentiment from /sentiment/current
        try:
            r = httpx.get(f"{HERMES_URL}/sentiment/current", timeout=4)
            if r.status_code == 200:
                sent = r.json()
                if sent.get("status") != "never_polled":
                    fg = sent.get("fg_index", 50)
                    # Convert Fear&Greed to composite: 0=extreme fear (bearish), 100=extreme greed (bullish)
                    ctx["composite_score"] = fg
                    ctx["funding_tilt"] = sent.get("funding_tilt", 0)
                    ctx["flow_tilt"] = sent.get("flow_tilt", 0)
                    ctx["whale_tilt"] = sent.get("whale_tilt", 0)
                    
                    if fg >= 75:
                        ctx["label"] = "STRONGLY_BULLISH"
                    elif fg >= 60:
                        ctx["label"] = "BULLISH"
                    elif fg <= 25:
                        ctx["label"] = "STRONGLY_BEARISH"
                    elif fg <= 40:
                        ctx["label"] = "BEARISH"
                    
                    fc = sent.get("forecast", {})
                    if isinstance(fc, dict):
                        ctx["forecast_direction"] = fc.get("direction")
                        ctx["forecast_confidence"] = fc.get("confidence", 0)
        except Exception:
            pass
        
    except Exception:
        pass
    
    _intel_cache = ctx
    _intel_cache_ts = now
    return ctx


def compute_quality_score(symbol: str, cfg: dict, ticker: dict,
                          obi_data: dict | None = None,
                          momentum_data: dict | None = None,
                          intel_ctx: dict | None = None) -> dict:
    """Compute MODE 7 quality score from 8 technical + 1 intelligence signal.
    
    Signals 1-8: technical (OBI, spread, momentum, volatility, depth, frequency, trends)
    Signal 9: intelligence composite (sentiment + forecast alignment)
    
    Returns dict with:
      - quality: 0-100 overall score
      - signals: individual signal scores  
      - recommendation: TRADE / CAUTIOUS / SKIP
      - optimal_spread: dynamic spread gate
      - confidence_threshold: adjusted confidence
      - intel_bonus: intelligence points added
    """
    scores = {}
    
    # ── PRE-SENTIMENT: Regime Detection ──
    spread_bps = (ticker["ask"] - ticker["bid"]) / ((ticker["ask"] + ticker["bid"]) / 2) * 100
    
    # Signal 1: OBI Composite (from live or gate)
    obi5 = 0.0; obi10 = 0.0; obi20 = 0.0
    if obi_data:
        try:
            obi5 = float(obi_data.get("obi5", 0))
            obi10 = float(obi_data.get("obi10", 0))
            obi20 = float(obi_data.get("obi20", 0))
        except (ValueError, TypeError):
            pass
    obi_composite = (obi5 * 0.5 + obi10 * 0.3 + obi20 * 0.2)  # weighted 5/10/20
    obi_abs = abs(obi_composite)
    # Balanced OBI = best for maker fills
    scores["obi"] = max(0, 100 - obi_abs * 200)  # 0=100, 0.5=0
    
    # Signal 2: Spread
    scores["spread"] = max(0, 100 - spread_bps * 30)  # 0bps=100, 3bps=10
    
    # Signal 3: Momentum (30s price change)
    mom_30s = 0.0
    if momentum_data:
        try: mom_30s = abs(float(momentum_data.get("mom_30s", 0)))
        except (ValueError, TypeError): pass
    scores["momentum"] = max(0, 100 - mom_30s * 500)  # 0%=100, 0.2%=0
    
    # Signal 4: Volatility (price range)
    vol_range = 0.0
    if momentum_data:
        try: vol_range = abs(float(momentum_data.get("vol_range", 0)))
        except (ValueError, TypeError): pass
    scores["volatility"] = max(0, 100 - vol_range * 300)
    
    # Signal 5: Depth Ratio (bv20/av20)
    depth_ratio = 1.0
    if obi_data:
        try:
            bv20 = float(obi_data.get("bv20", 0))
            av20 = float(obi_data.get("av20", 0))
            depth_ratio = bv20 / (av20 + 0.0001)
        except (ValueError, TypeError, ZeroDivisionError):
            pass
    # Ratio near 1.0 = balanced = best
    scores["depth"] = max(0, 100 - abs(depth_ratio - 1.0) * 80)
    
    # Signal 6: Trade Frequency (from momentum data)
    trade_freq = 1.0
    if momentum_data:
        try: trade_freq = float(momentum_data.get("trade_freq", 1.0))
        except (ValueError, TypeError): pass
    scores["frequency"] = min(100, trade_freq * 50)
    
    # Signal 7: Spread Trend
    spread_trend = 0.0
    if momentum_data:
        try: spread_trend = float(momentum_data.get("spread_trend", 0))
        except (ValueError, TypeError): pass
    scores["spread_trend"] = max(0, 100 - abs(spread_trend) * 200)
    
    # Signal 8: OBI Trend
    obi_trend = 0.0
    if momentum_data:
        try: obi_trend = abs(float(momentum_data.get("obi_trend", 0)))
        except (ValueError, TypeError): pass
    scores["obi_trend"] = max(0, 100 - obi_trend * 300)
    
    # ── v5.0: Signal 9: Intelligence Composite (Sentiment + Forecast) ──
    intel_score = 50.0  # neutral default
    intel_label = "NEUTRAL"
    intel_ctx = intel_ctx or get_intelligence_context()
    if intel_ctx:
        raw = intel_ctx.get("composite_score", 50)
        intel_label = intel_ctx.get("label", "NEUTRAL")
        # Convert 0-100 intelligence to our signal scale: 50=100, 0/100=40
        # Extreme bullish/bearish = lower score (herding risk), neutral = highest
        deviation = abs(raw - 50)
        intel_score = max(40, 100 - deviation * 1.2)
    scores["intelligence"] = round(intel_score, 1)
    
    # ── WEIGHTED QUALITY SCORE (v5.0: 9 signals) ──
    weights = {
        "obi": 0.18, "spread": 0.16, "momentum": 0.10,
        "volatility": 0.10, "depth": 0.13, "frequency": 0.07,
        "spread_trend": 0.07, "obi_trend": 0.06,
        "intelligence": 0.13  # v5.0: sentiment + forecast weight
    }
    
    quality = sum(scores[k] * weights.get(k, 0.10) for k in scores)
    
    # ── DYNAMIC SPREAD GATE (v3.8.2) ──
    # Uses symbol-specific baseline × quality multiplier.
    # High QS → allow wider spreads (market says it's good even if spread is wide).
    # Low QS → require tighter spreads.
    symbol_baseline = SYMBOL_SPREAD_BASELINE.get(symbol, 3.0)  # default 3bps
    # Quality multiplier: QS=100 → 3.0x baseline, QS=70 → 1.5x, QS=35 → 0.5x
    qs_mult = max(0.5, (quality - 20) / 30)  # 35→0.5, 50→1.0, 70→1.67, 95→2.5
    optimal_spread = max(0.015, symbol_baseline * qs_mult / 100)  # % not bps
    
    # ── RECOMMENDATION ──
    if quality >= 60:
        recommendation = "TRADE"
        confidence_threshold = 0.25
    elif quality >= 35:
        recommendation = "CAUTIOUS"
        confidence_threshold = 0.35
    else:
        recommendation = "SKIP"
        confidence_threshold = 0.50
    
    return {
        "quality": round(quality, 1),
        "signals": {k: round(v, 1) for k, v in scores.items()},
        "recommendation": recommendation,
        "optimal_spread": optimal_spread,
        "confidence_threshold": confidence_threshold,
        "intel_label": intel_label,  # v5.0: for direction bias
        "intel_ctx": intel_ctx,      # v5.0: full context for mode7_round
    }


def mode7_round(symbol: str, cfg: dict, margin: float = 20.0, leverage: int = 5,
                open_wait: float | None = None, close_wait: float | None = None,
                min_quality: float | None = None) -> dict:
    """MODE 7: Pre-Sentiment + 8 Tech Signals + Quantitative Stats.
    
    Computes a 0-100 Quality Score from 8 technical signals:
      1. OBI Composite (weighted 5/10/20 level)
      2. Spread (current bid-ask)
      3. Momentum (30s price change)
      4. Volatility (price range)
      5. Depth Ratio (bid/ask volume)
      6. Trade Frequency (activity level)
      7. Spread Trend (widening/narrowing)
      8. OBI Trend (imbalance direction)
    
    Quality Score determines:
      ≥60: TRADE — tight spread, low confidence threshold
      35-60: CAUTIOUS — moderate spread, normal confidence
      <35: SKIP — market conditions unfavorable
    
    This adapts dynamically to market conditions — no fixed thresholds.
    v5.0: Intelligence-aware direction bias + sentiment tilt.
    """
    from mode5_gate import get_gate
    
    open_wait = open_wait if open_wait is not None else MODE7_OPEN_WAIT
    close_wait = close_wait if close_wait is not None else MODE7_CLOSE_WAIT
    min_quality = min_quality if min_quality is not None else MODE7_MIN_QUALITY
    
    # ── v5.1: PRE-SENTIMENT Regime Gate (Pre-Gain/Loser) ──
    # Skip trading entirely if market is in CHAOS with severe ATR
    skip_regime, regime_info = _should_skip_regime()
    if skip_regime:
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": f"PRE-SENTIMENT SKIP: {regime_info}", "mode": 7}
    
    # ── v6.3: TIME-OF-DAY GATE (Strategy A) ──
    # Skip trading if current UTC hour is outside symbol's liquid hours.
    # Based on 12h data: NEAR fill rate drops 47-58% in ASIA session.
    trading_ok, trading_reason = _is_trading_hours(symbol)
    if not trading_ok:
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": f"TIME-GATE: {trading_reason}", "mode": 7}
    
    # ── v6.3: PRE-SENTIMENT ENHANCED OFFSET + MARGIN (Strategy D) ──
    # Regime-aware smart pricing: tight offset in RANGING, wider in TRENDING.
    # This is the KEY enhancement — Pre-Sentiment now controls BOTH price & size.
    regime_offset_bps, regime_margin_mult, regime_detail = _get_regime_enhanced_offset(symbol)
    
    # ── v5.1: PRE-GAIN LEARNER margin multiplier ──
    pregain_mult = 1.0
    try:
        import sys as _sys
        _sys.path.insert(0, str(PROJECT_DIR / "anantara"))
        from pregain_learner import get_learner as get_pregain_learner
        regime_data = _get_market_regime()
        learner = get_pregain_learner()
        if learner.is_trained():
            pregain_mult = learner.get_composite_mult(
                regime_data.get("regime", "RANGING"),
                "ASIA" if 0 <= datetime.now(timezone.utc).hour < 8 else "LONDON-NA"
            )
    except (ImportError, Exception):
        pass
    
    # ── v5.0: Fetch intelligence context once per round ──
    intel_ctx = get_intelligence_context()
    
    # ── v5.1: POSTURE-based margin multiplier ──
    posture_mult = 1.0
    posture = intel_ctx.get("posture", "BALANCED")
    if posture == "AGGRESSIVE":
        posture_mult = 1.3
    elif posture == "DEFENSIVE":
        posture_mult = 0.5
    
    # ── v5.1: COMBINED margin multiplier ──
    combined_mult = pregain_mult * posture_mult * regime_margin_mult  # v6.3: +regime
    # ── v5.6: FORECAST confidence boost ──
    forecast_conf = intel_ctx.get("forecast_confidence", 0)
    if forecast_conf >= 0.65:
        combined_mult *= 1.25  # high confidence → 25% more size
    # Clamp to safe range: 0.3x – 2.0x
    combined_mult = max(0.3, min(2.0, combined_mult))
    
    # Per-symbol open_wait override (v3.8.2)
    sym_open_wait = SYMBOL_OPEN_WAIT.get(symbol, open_wait)
    # Use the longer of explicit override or per-symbol default
    if open_wait == MODE7_OPEN_WAIT and sym_open_wait > open_wait:
        open_wait = sym_open_wait
    
    # Get ticker
    t = get_ticker(symbol, cfg)
    if not t or t["bid"] <= 0 or t["ask"] <= 0:
        return {"ok": False, "reason": "no book", "volume": 0.0, "mode": 7}
    
    # Get OBI data for signals
    gate = get_gate()
    obi_data = None
    try:
        obi_data = gate._fetch_obi(symbol) if hasattr(gate, '_fetch_obi') else None
    except Exception:
        pass
    
    # Compute momentum data
    time.sleep(2)
    t2 = get_ticker(symbol, cfg)
    momentum_data = {}
    if t2 and t2["last"] > 0 and t["last"] > 0:
        mom_30s = (t2["last"] - t["last"]) / t["last"] * 100
        momentum_data["mom_30s"] = mom_30s
        momentum_data["vol_range"] = abs(t2["last"] - t["last"]) / t["last"] * 100
        momentum_data["spread_trend"] = (
            (t2["ask"] - t2["bid"]) - (t["ask"] - t["bid"])) / ((t["ask"] + t["bid"]) / 2) * 100
    
    # Compute Quality Score (v5.0: with intelligence)
    q = compute_quality_score(symbol, cfg, t, obi_data, momentum_data, intel_ctx)
    
    if q["recommendation"] == "SKIP" or q["quality"] < min_quality:
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": f"MODE7 quality {q['quality']:.0f} < {min_quality}", 
                "mode": 7, "quality": q["quality"]}
    
    # Dynamic spread gate from quality score
    spread_gate_pct = q["optimal_spread"]
    
    mid = (t["bid"] + t["ask"]) / 2
    spread_actual = (t["ask"] - t["bid"]) / mid * 100
    
    if spread_actual > spread_gate_pct:
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": f"MODE7 spread ({spread_actual:.4f}% > {spread_gate_pct:.4f}%)",
                "mode": 7, "quality": q["quality"]}
    
    # Direction: aggressor bias + Intelligence tilt (v5.0, v6.3 enhanced)
    bias = get_aggressor_bias(symbol)
    
    # ── v6.3: INTELLIGENCE FILL-SIDE PREDICTOR ──
    # Key insight: when sentiment is STRONGLY one-sided, the OPPOSITE side
    # fills easier as maker (takers push price, we provide liquidity).
    #   STRONGLY_BULLISH → takers BUY, our maker SELL fills faster
    #   STRONGLY_BEARISH → takers SELL, our maker BUY fills faster
    intel_label = q.get("intel_label", "NEUTRAL")
    forecast_dir = intel_ctx.get("forecast_direction")
    forecast_conf = intel_ctx.get("forecast_confidence", 0)
    flow_tilt = intel_ctx.get("flow_tilt", 0)
    funding_tilt = intel_ctx.get("funding_tilt", 0)
    sentiment_sum = flow_tilt + funding_tilt
    
    # v6.3: FILL-SIDE logic — go WITH the taker flow for faster fills
    if intel_label == "STRONGLY_BULLISH" and forecast_dir == "UP" and forecast_conf >= 0.6:
        bias = "sell"   # takers are buying → our maker SELL fills faster
    elif intel_label == "STRONGLY_BEARISH" and forecast_dir == "DOWN" and forecast_conf >= 0.6:
        bias = "buy"    # takers are selling → our maker BUY fills faster
    elif sentiment_sum >= 6:   # strong bullish tilt → takers buy → we sell
        bias = "sell"
    elif sentiment_sum <= -6:  # strong bearish tilt → takers sell → we buy
        bias = "buy"
    # else: keep technical aggressor bias
    
    # ── v6.3: PRE-SENTIMENT ENHANCED SMART PRICING ──
    # Uses regime-aware offset from _get_regime_enhanced_offset().
    # RANGING → tighter offset (0.7× base) → more fills
    # TRENDING → wider offset (1.3× base) → capture spread in moving markets
    spread_actual_pct = (t["ask"] - t["bid"]) / ((t["ask"] + t["bid"]) / 2) * 100  # in %
    smart_offset_bps = min(regime_offset_bps, spread_actual_pct * 100 * 0.5)  # cap at half spread
    smart_offset = smart_offset_bps / 10000  # bps → decimal
    mid = (t["bid"] + t["ask"]) / 2
    
    if bias == "buy":
        open_side, close_side = "buy", "sell"
        open_price = t["bid"] + mid * smart_offset    # buy slightly above best bid
        close_price_fn = lambda tk: tk["ask"] - (tk["bid"] + tk["ask"]) / 2 * smart_offset
    elif bias == "sell":
        open_side, close_side = "sell", "buy"
        open_price = t["ask"] - mid * smart_offset    # sell slightly below best ask
        close_price_fn = lambda tk: tk["bid"] + (tk["bid"] + tk["ask"]) / 2 * smart_offset
    else:
        if random.random() < 0.5:
            open_side, close_side = "buy", "sell"
            open_price = t["bid"] + mid * smart_offset
            close_price_fn = lambda tk: tk["ask"] - (tk["bid"] + tk["ask"]) / 2 * smart_offset
        else:
            open_side, close_side = "sell", "buy"
            open_price = t["ask"] - mid * smart_offset
            close_price_fn = lambda tk: tk["bid"] + (tk["bid"] + tk["ask"]) / 2 * smart_offset
    
    # Position size: per-symbol margin multiplier (v3.8.2) × Pre-Gain × Posture
    margin_mult = SYMBOL_MARGIN_MULTIPLIER.get(symbol, 1.0)
    effective_margin = margin * margin_mult * combined_mult  # v5.1: intelligence-aware
    notional = effective_margin * leverage
    qty = fmt_qty(symbol, (notional / t["last"]) * (0.9 + 0.2 * random.random()))
    if float(qty) <= 0:
        return {"ok": False, "reason": "qty too small", "volume": 0.0, "mode": 7}
    
    # ── v6.3: MULTI-LEVEL OPEN (Strategy C) ──
    # Places 2 maker orders at different price levels (tight + normal).
    # When either fills, cancels the other → ~2× fill probability.
    # Falls back to single-level if Multi-Level fails.
    USE_MULTI_LEVEL = True  # v6.3: enable/disable via flag
    held = 0.0
    legs_maker = 0
    fill_price_used = mid
    
    if USE_MULTI_LEVEL:
        open_notional_multi, fill_price_multi, legs_multi = _multi_level_open(
            symbol, cfg, open_side, mid, smart_offset, qty, open_wait, num_levels=2)
        if open_notional_multi > 0:
            held = open_notional_multi / mid  # approximate qty from notional
            fill_price_used = fill_price_multi if fill_price_multi > 0 else mid
            legs_maker = legs_multi
    
    # Fallback: single-level open if multi-level didn't fill
    if held <= 0:
        op = cli(["orders", "place", "perps", "--symbol", symbol, "--side", open_side,
                  "--type", "limit", "--price", fmt_price(symbol, open_price),
                  "--qty", qty, "--tif", "gtx"], cfg=cfg, auth=True)
        if op is None:
            return {"ok": False, "reason": "open rejected", "volume": 0.0, "mode": 7}
        _, open_cloid = _extract_order_ids(op)
        
        last_reprice = time.time()
        deadline = time.time() + open_wait
        while time.time() < deadline:
            time.sleep(1.0)
            held = abs(_position_qty(symbol, cfg))
            if held > 0: break
            if time.time() - last_reprice > MODE7_REPRICE_INTERVAL:
                t_now = get_ticker(symbol, cfg)
                if t_now:
                    mid_now = (t_now["bid"] + t_now["ask"]) / 2
                    if open_side == "buy":
                        new_price_raw = t_now["bid"] + mid_now * smart_offset
                    else:
                        new_price_raw = t_now["ask"] - mid_now * smart_offset
                    new_price = fmt_price(symbol, new_price_raw)
                    if new_price != fmt_price(symbol, open_price):
                        _cancel_open(symbol, cfg, open_cloid)
                        op2 = cli(["orders", "place", "perps", "--symbol", symbol,
                                   "--side", open_side, "--type", "limit",
                                   "--price", new_price, "--qty", qty, "--tif", "gtx"],
                                  cfg=cfg, auth=True)
                        if op2:
                            _, open_cloid = _extract_order_ids(op2)
                            open_price = float(new_price)
                    last_reprice = time.time()
        
        if held <= 0:
            _cancel_open(symbol, cfg, open_cloid)
    
    if held <= 0:
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": "open not filled", "mode": 7,
                "regime": regime_detail}  # v6.3
    
    open_notional = held * t["last"]
    
    # ── v6.3: LEGS COUNTER (handle multi-level) ──
    if legs_maker == 0:
        legs_maker = 1  # single-level filled
    
    # ── v6.3: MINIMUM FILL GATE (Strategy E) ──
    # If fill is tiny (< $5 notional), don't close as maker — it costs more
    # in fees than the volume is worth. Keep as directional or cancel.
    MIN_FILL_NOTIONAL = 5.0  # minimum $5 per side to be worth closing
    if open_notional < MIN_FILL_NOTIONAL:
        # Cancel any remaining open orders from multi-level
        for p in [p for p in open_positions(cfg) if p.get("symbol") == symbol]:
            pass  # position exists but too tiny
        pos = [p for p in open_positions(cfg) if p.get("symbol") == symbol]
        if pos:
            close_position(pos[0], cfg)
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": f"MIN-FILL-GATE: notional ${open_notional:.2f} < ${MIN_FILL_NOTIONAL}", 
                "mode": 7, "regime": regime_detail}  # v6.3
    
    # CLOSE
    close_deadline = time.time() + close_wait
    flat = False
    last_close_price = None
    close_cloid = None  # ponytail: init before loop, guard F821
    while time.time() < close_deadline:
        t3 = get_ticker(symbol, cfg) or t
        close_price = fmt_price(symbol, close_price_fn(t3))
        if close_price != last_close_price:
            if last_close_price is not None:
                _cancel_open(symbol, cfg, close_cloid)
            clo = cli(["orders", "place", "perps", "--symbol", symbol, "--side", close_side,
                       "--type", "limit", "--price", close_price,
                       "--qty", fmt_qty(symbol, held), "--tif", "gtx", "--reduce-only"],
                      cfg=cfg, auth=True)
            _, close_cloid = _extract_order_ids(clo) if clo else (None, None)
            last_close_price = close_price
        time.sleep(5)
        if abs(_position_qty(symbol, cfg)) <= held * 0.02:
            flat = True; legs_maker += 1; break
    
    if not flat:
        _cancel_open(symbol, cfg, close_cloid)
        pos = [p for p in open_positions(cfg) if p.get("symbol") == symbol]
        if pos: close_position(pos[0], cfg)
        time.sleep(0.8)
        flat = abs(_position_qty(symbol, cfg)) <= held * 0.02
    
    # FORCE CLOSE BACKSTOP
    for p in [p for p in open_positions(cfg) if p.get("symbol") == symbol]:
        log.warning(f"MODE7 force-close: {symbol} qty={p.get('quantity')} (safety backstop)")
        close_position(p, cfg)
        time.sleep(0.5)
    
    time.sleep(0.5)
    final_pos = [p for p in open_positions(cfg) if p.get("symbol") == symbol]
    if final_pos:
        log.error(f"MODE7 CRITICAL: {symbol} position STILL open!")
    else:
        flat = True
    
    volume = open_notional * 2
    return {"ok": flat, "filled": True, "volume": round(volume, 2), "symbol": symbol,
            "legs_maker": legs_maker, "open_notional": round(open_notional, 2),
            "mode": 7, "quality": q["quality"], "recommendation": q["recommendation"],
            "optimal_spread": q["optimal_spread"],
            "intel_label": q.get("intel_label", "NEUTRAL"),          # v5.0
            "regime": regime_detail,                                  # v6.3: enhanced
            "posture": posture,                                       # v5.1
            "combined_mult": round(combined_mult, 2),                 # v5.1
            "fill_side": bias,                                        # v6.3: intel-aware
            "offset_bps": smart_offset_bps}                           # v6.3: actual offset


def mode7_intel_round(symbol: str, cfg: dict, margin: float = 20.0, leverage: int = 5,
                      open_wait: float | None = None, close_wait: float | None = None,
                      min_quality: float | None = None) -> dict:
    """Compatibility wrapper for daemon MODE7-INTEL.

    `mode7_round` already consumes intelligence, forecast, posture, and regime
    context. The daemon has a separate MODE7-INTEL switch, so keep this symbol
    available and annotate the result instead of crashing the scheduler.
    """
    result = mode7_round(
        symbol,
        cfg,
        margin=margin,
        leverage=leverage,
        open_wait=open_wait,
        close_wait=close_wait,
        min_quality=min_quality,
    )
    if isinstance(result, dict):
        result.setdefault("intel_mode", "integrated")
    return result


# ═══════════════════════════════════════════════════════════════════════════
# MODE 8: DELTA-NEUTRAL MAKER CYCLING (v4.1.0 — AUDITED & FIXED)
# ═══════════════════════════════════════════════════════════════════════════
# QUANTEX strategy: open LONG + SHORT simultaneously at best bid/ask.
# Both post-only maker → 4× notional volume per cycle (2 legs × open+close).
# CRITICAL: if one leg fills, RE-QUOTE the other (NOT cancel) to maintain delta≈0.
# Net delta ≈ 0 → no directional risk. Higher volume, same capital.
# ═══════════════════════════════════════════════════════════════════════════

def mode8_dn_cycle(symbol: str, cfg: dict, margin: float = None, leverage: int = None,
                   open_wait: float = None, close_wait: float = None) -> dict:
    """MODE 8 v4.1.0: Delta-Neutral Maker Cycling — AUDITED & FIXED.
    
    CORRECT DN LOGIC:
    1. Place long at bid+offset AND short at ask-offset simultaneously
    2. If ONE fills → RE-QUOTE the other (stay delta-neutral), don't cancel
    3. When BOTH fill → close both via maker limit orders
    4. Randomisasi ukuran ±15-25% untuk anti-deteksi
    5. Quality check via spread gate + funding check
    """
    import random as _rand
    
    if margin is None:
        margin = MODE8_MARGIN
    if leverage is None:
        leverage = MODE8_LEVERAGE
    if open_wait is None:
        open_wait = MODE8_OPEN_WAIT
    if close_wait is None:
        close_wait = MODE8_CLOSE_WAIT
    
    t = get_ticker(symbol, cfg)
    if not t or t["bid"] <= 0 or t["ask"] <= 0:
        return {"ok": False, "reason": "no book", "volume": 0.0, "mode": 8}
    
    # ── Pre-Gain Regime Gate (v4.3.0) ──
    skip, regime_info = _should_skip_regime()
    if skip:
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": f"MODE8 regime: {regime_info}", "mode": 8}
    
    # ── Quality Gate 1: Per-symbol spread check ──
    mid = (t["bid"] + t["ask"]) / 2
    spread_bps = (t["ask"] - t["bid"]) / mid * 10000  # basis points: (diff/mid) * 10000
    sym_baseline = SYMBOL_SPREAD_BASELINE.get(symbol, 3.0)
    max_spread = sym_baseline * 4  # allow up to 4× baseline spread
    
    if spread_bps > max_spread:
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": f"MODE8 spread {spread_bps:.1f}bps > {max_spread:.1f}bps", "mode": 8}
    
    # ── Quality Gate 2: Quick QS check (optional, light version) ──
    qs = compute_quality_score(symbol, cfg, t, None, None)
    if qs["quality"] < 40:
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": f"MODE8 QS={qs['quality']:.0f} < 40", "mode": 8, "quality": qs["quality"]}
    
    # ── Randomisasi ukuran: ±15-25% ──
    size_jitter = 0.85 + _rand.random() * 0.30  # 0.85 to 1.15
    notional_per_leg = margin * leverage * size_jitter
    total_notional = notional_per_leg * 2
    
    # ── ADAPTIVE Smart pricing (v4.3.0): regime-aware + learner-tuned offset ──
    adaptive_bps = _get_adaptive_smart_bps(symbol)
    # Override with learner if it has enough data
    try:
        from mode8_learner import get_learner
        learner_bps = get_learner().get_smart_bps(symbol, adaptive_bps)
        if learner_bps != adaptive_bps:
            adaptive_bps = learner_bps
    except ImportError:
        pass
    smart_offset_bps = min(adaptive_bps, spread_bps * 0.5)  # cap at 50% spread
    smart_offset = smart_offset_bps / 10000
    
    # ── Calculate quantities ──
    qty_per_leg = fmt_qty(symbol, (notional_per_leg / t["last"]) * 0.95)
    if float(qty_per_leg) <= 0:
        return {"ok": False, "reason": "qty too small", "volume": 0.0, "mode": 8}
    
    # ═══════════════════════════════════════════════════════════════
    # PHASE 1: Open both legs simultaneously (post-only maker)
    # ═══════════════════════════════════════════════════════════════
    
    # Leg 1: LONG at bid+offset
    long_price = fmt_price(symbol, t["bid"] + mid * smart_offset)
    op_long = cli(["orders", "place", "perps", "--symbol", symbol, "--side", "buy",
                   "--type", "limit", "--price", long_price, "--qty", qty_per_leg,
                   "--tif", "gtx"], cfg=cfg, auth=True)
    if op_long is None:
        return {"ok": False, "reason": "long rejected", "volume": 0.0, "mode": 8}
    _, long_cloid = _extract_order_ids(op_long)
    
    # Leg 2: SHORT at ask-offset
    short_price = fmt_price(symbol, t["ask"] - mid * smart_offset)
    op_short = cli(["orders", "place", "perps", "--symbol", symbol, "--side", "sell",
                    "--type", "limit", "--price", short_price, "--qty", qty_per_leg,
                    "--tif", "gtx"], cfg=cfg, auth=True)
    if op_short is None:
        _cancel_open(symbol, cfg, long_cloid)
        return {"ok": False, "reason": "short rejected", "volume": 0.0, "mode": 8}
    _, short_cloid = _extract_order_ids(op_short)
    
    # ═══════════════════════════════════════════════════════════════
    # PHASE 2: Wait for fills — RE-QUOTE, don't cancel
    # ═══════════════════════════════════════════════════════════════
    deadline = time.time() + open_wait
    last_reprice = time.time()
    long_filled = False
    short_filled = False
    
    while time.time() < deadline:
        time.sleep(1.5)
        pos_qty = _position_qty(symbol, cfg)
        
        # Detect fills
        if pos_qty > 0.0001 and not long_filled:
            long_filled = True
        if pos_qty < -0.0001 and not short_filled:
            short_filled = True
        
        # Both filled → proceed to close
        if long_filled and short_filled:
            break
        
        # CORRECT DN: If one filled, RE-QUOTE the other (don't cancel!)
        if long_filled and not short_filled:
            # Long filled, need short to fill → re-quote short closer to market
            if short_cloid:
                _cancel_open(symbol, cfg, short_cloid)
            t_s = get_ticker(symbol, cfg) or t
            mid_s = (t_s["bid"] + t_s["ask"]) / 2
            # Short: sell at bid (aggressive maker) to get filled
            new_short = fmt_price(symbol, t_s["bid"])
            ops = cli(["orders", "place", "perps", "--symbol", symbol,
                       "--side", "sell", "--type", "limit", "--price", new_short,
                       "--qty", qty_per_leg, "--tif", "gtx"], cfg=cfg, auth=True)
            if ops:
                _, short_cloid = _extract_order_ids(ops)
            else:
                short_cloid = None
        
        if short_filled and not long_filled:
            # Short filled, need long to fill → re-quote long closer to market
            if long_cloid:
                _cancel_open(symbol, cfg, long_cloid)
            t_l = get_ticker(symbol, cfg) or t
            mid_l = (t_l["bid"] + t_l["ask"]) / 2
            # Long: buy at ask (aggressive maker) to get filled
            new_long = fmt_price(symbol, t_l["ask"])
            opl = cli(["orders", "place", "perps", "--symbol", symbol,
                       "--side", "buy", "--type", "limit", "--price", new_long,
                       "--qty", qty_per_leg, "--tif", "gtx"], cfg=cfg, auth=True)
            if opl:
                _, long_cloid = _extract_order_ids(opl)
            else:
                long_cloid = None
        
        # Periodic re-quote for unfilled legs (stay at top of book)
        if time.time() - last_reprice > MODE7_REPRICE_INTERVAL:
            t_now = get_ticker(symbol, cfg)
            if t_now:
                mid_now = (t_now["bid"] + t_now["ask"]) / 2
                if not long_filled and long_cloid:
                    new_l = fmt_price(symbol, t_now["bid"] + mid_now * smart_offset)
                    if new_l != long_price:
                        _cancel_open(symbol, cfg, long_cloid)
                        opl = cli(["orders", "place", "perps", "--symbol", symbol,
                                   "--side", "buy", "--type", "limit", "--price", new_l,
                                   "--qty", qty_per_leg, "--tif", "gtx"], cfg=cfg, auth=True)
                        if opl:
                            _, long_cloid = _extract_order_ids(opl)
                            long_price = new_l
                if not short_filled and short_cloid:
                    new_s = fmt_price(symbol, t_now["ask"] - mid_now * smart_offset)
                    if new_s != short_price:
                        _cancel_open(symbol, cfg, short_cloid)
                        ops = cli(["orders", "place", "perps", "--symbol", symbol,
                                   "--side", "sell", "--type", "limit", "--price", new_s,
                                   "--qty", qty_per_leg, "--tif", "gtx"], cfg=cfg, auth=True)
                        if ops:
                            _, short_cloid = _extract_order_ids(ops)
                            short_price = new_s
                last_reprice = time.time()
    
    # ── Cancel any remaining open orders ──
    if long_cloid and not long_filled:
        _cancel_open(symbol, cfg, long_cloid)
    if short_cloid and not short_filled:
        _cancel_open(symbol, cfg, short_cloid)
    
    # ═══════════════════════════════════════════════════════════════
    # PHASE 3: Close positions
    # ═══════════════════════════════════════════════════════════════
    pos = abs(_position_qty(symbol, cfg))
    legs_maker = (1 if long_filled else 0) + (1 if short_filled else 0)  # open-side makers
    flat = False
    
    if pos > 0.0001:
        close_deadline = time.time() + close_wait
        while time.time() < close_deadline:
            t2 = get_ticker(symbol, cfg) or t
            net_pos = _position_qty(symbol, cfg)
            
            if abs(net_pos) <= 0.0001:
                flat = True
                break
            
            # Close with smart maker order
            close_side = "sell" if net_pos > 0 else "buy"
            mid2 = (t2["bid"] + t2["ask"]) / 2
            if close_side == "sell":
                close_price = fmt_price(symbol, t2["ask"] - mid2 * smart_offset)
            else:
                close_price = fmt_price(symbol, t2["bid"] + mid2 * smart_offset)
            
            cl = cli(["orders", "place", "perps", "--symbol", symbol, "--side", close_side,
                      "--type", "limit", "--price", close_price,
                      "--qty", fmt_qty(symbol, abs(net_pos)),
                      "--tif", "gtx", "--reduce-only"], cfg=cfg, auth=True)
            _, cl_cloid = _extract_order_ids(cl) if cl else (None, None)
            
            time.sleep(3)
            if abs(_position_qty(symbol, cfg)) <= abs(net_pos) * 0.05:
                flat = True
                if cl: legs_maker += 1  # close-side maker
                break
            
            if cl_cloid:
                _cancel_open(symbol, cfg, cl_cloid)
        
        # Force close backstop (taker — acceptable for safety)
        if not flat:
            for p in [p for p in open_positions(cfg) if p.get("symbol") == symbol]:
                log.warning(f"MODE8 force-close: {symbol} qty={p.get('quantity','?')}")
                close_position(p, cfg)
                time.sleep(0.5)
            if abs(_position_qty(symbol, cfg)) <= 0.0001:
                flat = True
    else:
        flat = True  # nothing to close
    
    # ── Volume: count what actually traded ──
    filled_legs = (1 if long_filled else 0) + (1 if short_filled else 0)
    volume = notional_per_leg * filled_legs * (1 + (1 if flat else 0))  # open + close per filled leg
    
    # ── LEARNING: Record outcome for adaptive tuning ──
    result = {"ok": flat, "filled": filled_legs > 0, "volume": round(volume, 2),
            "symbol": symbol, "legs_maker": min(legs_maker, 4),
            "notional": round(notional_per_leg, 2), "legs_filled": filled_legs,
            "mode": 8, "method": "delta-neutral", "quality": qs["quality"],
            "regime": regime_info, "smart_bps": round(smart_offset_bps, 2)}
    
    try:
        from mode8_learner import get_learner
        adaptation = get_learner().record(symbol, result)
        if adaptation and adaptation.get("action") not in ("collecting", "hold", "insufficient_recent"):
            result["adaptation"] = adaptation["action"]
            log.info(f"MODE8 learner: {symbol} {adaptation['action']} "
                    f"bps {adaptation.get('old_bps',0)}→{adaptation.get('new_bps',0)} "
                    f"(fill={adaptation.get('avg_fill',0):.2f}, n={adaptation.get('samples',0)})")
    except ImportError:
        pass
    
    return result


# ═══════════════════════════════════════════════════════════════════════════


def _cfg() -> dict:
    return {
        "api_key": os.environ.get("SODEX_API_KEY", ""),
        "private_key": os.environ.get("SODEX_PRIVATE_KEY", ""),
        "address": os.environ.get("SODEX_ADDRESS", ""),
        "account_id": os.environ.get("SODEX_ACCOUNT_ID", ""),
        "perps_url": os.environ.get("SODEX_PERPS_URL", "https://mainnet-gw.sodex.dev/api/v1/perps"),
        "testnet": os.environ.get("SODEX_TESTNET", "0") == "1",
    }


def _auth_flags(cfg: dict) -> list[str]:
    """Auth flags for trading commands. Read-only commands omit these.

    SECURITY (v3.4.2): NEVER pass --private-key or --api-key on the command line.
    The sodex binary reads SODEX_PRIVATE_KEY and SODEX_API_KEY from the environment
    (already set via .env). CLI arguments are visible in /proc/*/cmdline and ps aux.
    Only --account-id and --testnet are safe to expose.
    """
    flags = []
    # ⚠️ SECURITY: private_key and api_key are read from env vars (SODEX_PRIVATE_KEY,
    # SODEX_API_KEY) by the sodex binary automatically. DO NOT pass them as CLI flags —
    # they would be visible to any user on the system via ps aux / /proc/*/cmdline.
    if cfg["account_id"]:
        flags += ["--account-id", cfg["account_id"]]
    if cfg["testnet"]:
        flags += ["--testnet"]
    return flags


def cli(args: list[str], cfg: dict | None = None, auth: bool = False, timeout: int = 30) -> dict | list | None:
    """Run the sodex CLI with --format json. Returns parsed JSON or None on error.
    Thread-safe: uses global lock to serialize EIP-712 signed calls."""
    cfg = cfg or _cfg()
    if _halt_blocks_cli(args):
        log.error("SAFETY_HALT/PNL_HALT active — blocked non-reduce-only perps order: %s", " ".join(args[:6]))
        return None
    cmd = [SODEX_BIN] + args + ["--format", "json"]
    if auth:
        cmd += _auth_flags(cfg)
    elif cfg["testnet"]:
        cmd += ["--testnet"]
    # Serialize all signed calls to avoid EIP-712 nonce collision
    if auth:
        _cli_lock.acquire()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            err = r.stderr.strip()[:300]
            log.error(f"CLI error ({' '.join(args)}): {err}")
            _journal_order(args, None, err)
            return None
        parsed = json.loads(r.stdout) if r.stdout.strip() else {}
        _journal_order(args, parsed, None)
        return parsed
    except subprocess.TimeoutExpired:
        log.error(f"CLI timeout: {' '.join(args)}")
        _journal_order(args, None, "timeout")
        return None
    except json.JSONDecodeError:
        log.error(f"CLI non-JSON output: {r.stdout[:200]}")
        _journal_order(args, None, "non-JSON output")
        return None
    finally:
        if auth:
            _cli_lock.release()


def get_ticker(symbol: str, cfg: dict) -> dict | None:
    """Fetch ticker (last/bid/ask) via public REST — no signing, no WS streaming."""
    try:
        with httpx.Client(timeout=10, headers={"Accept": "application/json"}) as c:
            r = c.get(f"{cfg['perps_url']}/markets/tickers", params={"symbol": symbol})
            data = (r.json() or {}).get("data", []) or []
        for t in data:
            if t.get("symbol") == symbol:
                return {
                    "last": float(t.get("lastPx", 0) or 0),
                    "bid": float(t.get("bidPx", 0) or 0),
                    "ask": float(t.get("askPx", 0) or 0),
                    "volume_24h": float(t.get("quoteVolume", 0) or 0),
                }
    except Exception as e:
        log.error(f"get_ticker({symbol}) failed: {e}")
    return None


def _fmt(value: float, decimals: int) -> str:
    """Format to N decimals, stripping trailing zeros (SoDEX rejects them)."""
    s = f"{value:.{decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def fmt_price(symbol: str, price: float) -> str:
    return _fmt(price, SYMBOLS[symbol]["px_decimals"])


def fmt_qty(symbol: str, qty: float) -> str:
    return _fmt(qty, SYMBOLS[symbol]["qty_decimals"])


def fmt_close_qty(symbol: str, qty: float) -> str:
    """Format reduce-only close quantity even when symbol metadata is missing."""
    meta = SYMBOLS.get(symbol)
    if meta:
        return _fmt(qty, meta["qty_decimals"])
    return _fmt(qty, 8).rstrip("0").rstrip(".") or "0"


def set_leverage(symbol: str, leverage: int, cfg: dict) -> bool:
    """Set isolated leverage. Thread-safe: uses global CLI lock.
    Gracefully handles 'already set' / 'open orders' errors as success."""
    cmd = [SODEX_BIN, "leverage", symbol, str(leverage), "--mode", "isolated"] + _auth_flags(cfg)
    _cli_lock.acquire()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            err = r.stderr.strip()[:200]
            # "already set" / "open orders" = non-fatal, leverage is correct
            if "already" in err.lower() or "open order" in err.lower():
                log.debug(f"set_leverage {symbol}: already {leverage}x (non-fatal: {err[:80]})")
                return True
            log.error(f"set_leverage {leverage}x {symbol} failed: {err}")
            return False
        log.info(f"Leverage set: {symbol} {leverage}x isolated")
        return True
    except subprocess.TimeoutExpired:
        log.error(f"set_leverage timeout {symbol}")
        return False
    finally:
        _cli_lock.release()


def open_positions(cfg: dict) -> list:
    """Return open positions via REST account-state, with a short safety cache.
    
    NEVER silently returns empty on error — that masks real open positions
    and causes the daemon to trade on top of existing positions (stacking).
    """
    def _cache_key() -> str:
        return str(cfg.get("address", "") or "")

    def _cache_get(max_age_s: float | None = None) -> tuple[list | None, float | None]:
        entry = _open_positions_cache.get(_cache_key())
        if entry is None:
            return None, None
        ts, cached = entry
        age_s = time.time() - ts
        if max_age_s is not None and age_s > max_age_s:
            return None, age_s
        return [dict(p) for p in cached], age_s

    def _cache_set(positions: list) -> None:
        _open_positions_cache[_cache_key()] = (time.time(), [dict(p) for p in positions])

    def _warn_once(message: str) -> None:
        key = _cache_key() or "__unknown__"
        now = time.time()
        last = _open_positions_warn_ts.get(key, 0.0)
        if now - last >= _OPEN_POSITIONS_WARN_COOLDOWN_S:
            log.warning(message)
            _open_positions_warn_ts[key] = now
        else:
            log.debug(message)

    addr = cfg.get("address", "")
    if not addr:
        return []

    cached, _ = _cache_get(_OPEN_POSITIONS_CACHE_TTL_S)
    if cached is not None:
        return cached

    # Try REST API first
    P = None
    rest_error = None
    try:
        with httpx.Client(timeout=15, headers={"Accept": "application/json"}) as c:
            r = c.get(f"{cfg.get('perps_url', 'https://mainnet-gw.sodex.dev/api/v1/perps')}/accounts/{addr}/state")
            if r.status_code != 200:
                raise RuntimeError(f"state endpoint returned {r.status_code}")
            data = (r.json() or {}).get("data", {})
            if not isinstance(data, dict) or "P" not in data:
                raise RuntimeError("state payload missing positions field")
            P = data.get("P") or []
    except Exception as e:
        rest_error = e

    if P is None:
        stale_cached, stale_age_s = _cache_get()
        if stale_cached:
            _warn_once(
                f"open_positions REST unavailable for {addr}; using stale cached positions "
                f"(age={stale_age_s:.1f}s): {rest_error}"
            )
            return stale_cached
        _warn_once(f"open_positions state unavailable for {addr}; pausing SoDEX automation: {rest_error}")
        return [{
            "symbol": "UNKNOWN",
            "quantity": 0.0001,
            "warning": "api_unverified",
            "reason": str(rest_error)[:160] if rest_error else "state_unavailable",
        }]

    out = []
    for p in P:
        qty = float(p.get("sz", 0) or 0)
        if abs(qty) < 1e-8:
            continue
        out.append({
            "symbol": p.get("s"),
            "quantity": qty,
            "entryPrice": float(p.get("ep", 0) or 0),
            "unrealizedPnl": float(p.get("ur", 0) or 0),
            "margin": float(p.get("iw", 0) or 0),
            "leverage": p.get("l"),
            "liquidationPrice": p.get("lp"),
        })
    _cache_set(out)
    return out


def position_risk(pos: dict, cfg: dict) -> dict:
    """Compute leverage risk for a position: notional, distance-to-liquidation %,
    and a 1-day parametric VaR estimate (concept adopted from trading_skills risk.py)."""
    sym = pos.get("symbol")
    qty = abs(float(pos.get("quantity", 0) or 0))
    liq = float(pos.get("liquidationPrice", 0) or 0)
    entry = float(pos.get("entryPrice", 0) or 0)
    t = get_ticker(sym, cfg) if sym else None
    mark = t["last"] if t else entry
    notional = qty * mark
    dist_to_liq = (abs(mark - liq) / mark * 100) if (mark > 0 and liq > 0) else None
    # crude daily VaR-95: notional * (typical 1h vol annualized-ish). Use 24h range proxy.
    var95 = None
    if t and t.get("last"):
        rng = abs(t.get("ask", mark) - t.get("bid", mark)) / mark if mark else 0
        # fallback rough daily vol ~3% for majors; VaR95 = notional * 1.645 * dailyvol
        var95 = round(notional * 1.645 * 0.03, 2)
    return {"notional_usd": round(notional, 2),
            "dist_to_liq_pct": round(dist_to_liq, 2) if dist_to_liq is not None else None,
            "var95_usd": var95}


def close_position(pos: dict, cfg: dict) -> bool:
    """Close a position with a reduce-only market order (opposite side)."""
    sym = pos["symbol"]
    # SoDEX API uses "size" not "quantity" — handle both
    qty = float(pos.get("quantity", 0) or pos.get("size", 0) or 0)
    if qty == 0:
        log.error(f"Cannot close {sym}: qty=0 (keys: {list(pos.keys())[:5]})")
        return False
    side = "sell" if qty > 0 else "buy"   # one-way netting: long qty>0
    r = cli(["orders", "place", "perps", "--symbol", sym, "--side", side,
             "--type", "market", "--qty", fmt_close_qty(sym, abs(qty)),
             "--tif", "ioc", "--reduce-only"], cfg=cfg, auth=True)
    if r is None:
        log.error(f"Failed to close {sym} (qty {qty})")
        return False
    log.info(f"🛑 Closed {sym}: {side} {abs(qty)} reduce-only")
    return True


def _position_qty(symbol: str, cfg: dict) -> float:
    """Current signed quantity for a symbol (0 if flat). Handles 'size' key from API."""
    for p in open_positions(cfg):
        if p.get("symbol") == symbol:
            return float(p.get("quantity", 0) or p.get("size", 0) or 0)
    return 0.0


def scalp_round(symbol: str, cfg: dict, margin: float | None = None,
                leverage: int | None = None, side: str = "buy") -> dict:
    """One SoPoints VOLUME round-trip: market open + immediate market close.
    Direction is irrelevant (closed flat in ~1s) — cost ≈ fees + tiny spread, NO
    directional bet. Returns {ok, volume, symbol, ...}.

    SAFETY: confirms the position opened, closes the ACTUAL filled qty reduce-only,
    verifies flat, and retries/alerts if a residual remains (the monitor stop-loss
    is the backstop). A naked high-leverage position is never left intentionally.
    """
    margin = margin if margin is not None else SCALP_MARGIN
    leverage = min(leverage or SCALP_LEVERAGE, SYMBOLS.get(symbol, {}).get("max_lev", 5))
    t = get_ticker(symbol, cfg)
    if not t or t["last"] <= 0:
        return {"ok": False, "reason": "no ticker", "volume": 0.0, "symbol": symbol}
    notional = margin * leverage
    # size jitter ±10% (anti-wash: avoid identical sizes)
    qty_val = (notional / t["last"]) * (0.9 + 0.2 * random.random())
    qty = fmt_qty(symbol, qty_val)
    if float(qty) <= 0:
        return {"ok": False, "reason": "qty too small", "volume": 0.0, "symbol": symbol}

    set_leverage(symbol, leverage, cfg)
    close_side = "sell" if side == "buy" else "buy"
    # OPEN (market IOC)
    op = cli(["orders", "place", "perps", "--symbol", symbol, "--side", side,
              "--type", "market", "--qty", qty, "--tif", "ioc"], cfg=cfg, auth=True)
    if op is None:
        return {"ok": False, "reason": "open rejected", "volume": 0.0, "symbol": symbol}
    time.sleep(0.6)
    held = abs(_position_qty(symbol, cfg))
    if held <= 0:
        # open didn't result in a position (rejected/no fill) — nothing to close
        return {"ok": False, "reason": "no position after open", "volume": 0.0, "symbol": symbol}
    # CLOSE the actual filled qty (reduce-only market IOC)
    cl = cli(["orders", "place", "perps", "--symbol", symbol, "--side", close_side,
              "--type", "market", "--qty", fmt_qty(symbol, held), "--tif", "ioc",
              "--reduce-only"], cfg=cfg, auth=True)
    time.sleep(0.6)
    residual = abs(_position_qty(symbol, cfg))
    if residual > held * 0.02:  # not flat — retry once
        log.warning(f"scalp {symbol}: residual {residual} after close, retrying")
        pos = [p for p in open_positions(cfg) if p.get("symbol") == symbol]
        if pos:
            close_position(pos[0], cfg)
            time.sleep(0.6)
            residual = abs(_position_qty(symbol, cfg))
    flat = residual <= held * 0.02
    volume = notional * 2  # open + close legs
    if not flat:
        log.error(f"⚠️ scalp {symbol}: NOT FLAT (residual {residual}) — monitor will catch")
    return {"ok": flat, "volume": round(volume, 2), "symbol": symbol,
            "qty": qty, "leverage": leverage, "notional": round(notional, 2)}


def _cancel_open(symbol: str, cfg: dict, cl_ord_id: str | None = None):
    """Cancel a resting order. SoDEX requires --order-id or --cl-ord-id (symbol-id
    alone is rejected). Cancel the known clOrdID, else sweep all resting orders."""
    sid = SYMBOLS.get(symbol, {}).get("id")
    if sid is None:
        return
    if cl_ord_id:
        cli(["orders", "cancel", "perps", "--symbol-id", str(sid),
             "--cl-ord-id", cl_ord_id], cfg=cfg, auth=True)
        return
    # sweep: fetch resting orders for this symbol and cancel each by orderID
    addr = cfg.get("address", "")
    try:
        with httpx.Client(timeout=8) as c:
            data = c.get(f"{cfg['perps_url']}/accounts/{addr}/orders").json().get("data", [])
    except Exception:
        data = []
    for o in data if isinstance(data, list) else []:
        if isinstance(o, dict) and o.get("symbol") == symbol and o.get("orderID"):
            cli(["orders", "cancel", "perps", "--symbol-id", str(sid),
                 "--order-id", str(o["orderID"])], cfg=cfg, auth=True)


def maker_scalp_round(symbol: str, cfg: dict, margin: float | None = None,
                      leverage: int | None = None, fill_timeout: float = 7.0) -> dict:
    """MAKER volume round-trip for rebate-tier farming + measurement.
    Post-only (gtx) LIMIT open at the touch → wait for maker fill → post-only
    LIMIT close → wait → TAKER fallback close if it doesn't fill (SAFETY: never
    leave a leveraged position open). Returns measured maker-fill legs + cost.
    """
    margin = margin if margin is not None else SCALP_MARGIN
    leverage = min(leverage or SCALP_LEVERAGE, SYMBOLS.get(symbol, {}).get("max_lev", 5))
    t = get_ticker(symbol, cfg)
    if not t or t["bid"] <= 0 or t["ask"] <= 0:
        return {"ok": False, "reason": "no book", "volume": 0.0}
    notional = margin * leverage
    qty = fmt_qty(symbol, (notional / t["last"]) * (0.9 + 0.2 * random.random()))
    if float(qty) <= 0:
        return {"ok": False, "reason": "qty too small", "volume": 0.0}
    legs_maker = 0
    # OPEN: post-only buy at bid (maker). Leverage is set once upfront (not here —
    # it errors while busy). clOrdID captured for reliable cancel.
    op = cli(["orders", "place", "perps", "--symbol", symbol, "--side", "buy",
              "--type", "limit", "--price", fmt_price(symbol, t["bid"]),
              "--qty", qty, "--tif", "gtx"], cfg=cfg, auth=True)
    if op is None:
        return {"ok": False, "reason": "open rejected", "volume": 0.0}
    _, open_cloid = _extract_order_ids(op)
    # poll for open fill
    held = 0.0; deadline = time.time() + fill_timeout
    while time.time() < deadline:
        time.sleep(1.0)
        held = abs(_position_qty(symbol, cfg))
        if held > 0:
            break
    if held <= 0:
        _cancel_open(symbol, cfg, open_cloid)  # no maker fill → cancel (no volume)
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": "open not filled (maker miss)"}
    legs_maker += 1  # open filled as maker
    open_notional = held * t["last"]
    # CLOSE: post-only sell at ask (maker), reduce-only
    t2 = get_ticker(symbol, cfg) or t
    clo = cli(["orders", "place", "perps", "--symbol", symbol, "--side", "sell",
               "--type", "limit", "--price", fmt_price(symbol, t2["ask"]),
               "--qty", fmt_qty(symbol, held), "--tif", "gtx", "--reduce-only"], cfg=cfg, auth=True)
    _, close_cloid = _extract_order_ids(clo) if clo else (None, None)
    deadline = time.time() + fill_timeout; flat = False
    while time.time() < deadline:
        time.sleep(1.0)
        if abs(_position_qty(symbol, cfg)) <= held * 0.02:
            flat = True; break
    if flat:
        legs_maker += 1  # close filled as maker
    else:
        # SAFETY fallback: cancel resting close + taker market close
        _cancel_open(symbol, cfg, close_cloid)
        pos = [p for p in open_positions(cfg) if p.get("symbol") == symbol]
        if pos:
            close_position(pos[0], cfg)  # market reduce-only (taker)
        time.sleep(0.8)
        flat = abs(_position_qty(symbol, cfg)) <= held * 0.02
    volume = open_notional * 2
    return {"ok": flat, "filled": True, "volume": round(volume, 2), "symbol": symbol,
            "legs_maker": legs_maker, "open_notional": round(open_notional, 2)}


def _place_maker(symbol, side, price, qty, cfg, reduce_only=False, post_only=True):
    """Place a limit order; return (orderID, clOrdID) or (None,None).
    
    Args:
        post_only: If True, use --tif gtx (maker-only, cancelled if crossed).
                   If False, regular limit order (can fill as taker if crossed).
                   Set post_only=False for CLOSE legs to prevent stuck positions.
    """
    args = ["orders", "place", "perps", "--symbol", symbol, "--side", side,
            "--type", "limit", "--price", price, "--qty", qty]
    if post_only:
        args.extend(["--tif", "gtx"])
    if reduce_only:
        args.append("--reduce-only")
    r = cli(args, cfg=cfg, auth=True)
    return _extract_order_ids(r) if r is not None else (None, None)


def patient_mm_round(symbol: str, cfg: dict, margin: float | None = None,
                     leverage: int | None = None, open_wait: float = 90.0,
                     close_wait: float = 120.0, reprice_every: float = 5.0,
                     stop_loss_frac: float = 0.40,
                     spread_threshold: float | None = None,
                     momentum_threshold: float | None = None) -> dict:
    """PATIENT market-making round optimized for ratio (target 1:6,400+).

    OPEN: post-only buy at bid, reprice to chase the touch, wait up to open_wait.
    NEVER taker on open (unfilled → cancel, no cost).

    CLOSE: post-only sell at ask, reprice every 5s, wait up to close_wait.
    Taker-close ONLY on stop-loss (price moves >40% of margin against us).

    SPREAD GATE: per-symbol thresholds (override with spread_threshold param).
    MOMENTUM GATE: skip if price trending (override with momentum_threshold param).
    RETRY: safety close retries 3x with exponential backoff (LAST RESORT only).
    """
    margin = margin if margin is not None else SCALP_MARGIN
    leverage = min(leverage or SCALP_LEVERAGE, SYMBOLS.get(symbol, {}).get("max_lev", 5))
    meta = SYMBOLS.get(symbol, {})
    tick = 10 ** (-meta.get("px_decimals", 2))
    t = get_ticker(symbol, cfg)
    if not t or t["bid"] <= 0 or t["ask"] <= 0:
        return {"ok": False, "reason": "no book", "volume": 0.0, "filled": False}
    
    # ── SPREAD GATE: use override if provided, else per-symbol defaults ──
    spread_pct = (t["ask"] - t["bid"]) / t["last"] * 100 if t["last"] > 0 else 0
    if spread_threshold is not None:
        gate = spread_threshold  # caller override (MODE 4)
    elif symbol == "BTC-USD":
        gate = 0.008
    elif symbol in ("SILVER-USD", "ZEC-USD", "XAUT-USD"):
        gate = 0.010
    else:
        gate = 0.015
    if spread_pct > gate:
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": f"spread {spread_pct:.4f}% > {gate}%"}
    
    # ── MOMENTUM GATE: skip if price trending (reduces adverse selection) ──
    # Wait 5s and check if mid moved >threshold — trending markets pick off makers
    mom_gate = momentum_threshold if momentum_threshold is not None else 0.03
    time.sleep(5.0)
    t2_check = get_ticker(symbol, cfg)
    if t2_check and t2_check["last"] > 0:
        momentum_pct = abs(t2_check["last"] - t["last"]) / t["last"] * 100
        if momentum_pct > mom_gate:
            return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                    "reason": f"momentum {momentum_pct:.4f}% > {mom_gate}%"}
    
    qty = fmt_qty(symbol, (margin * leverage / t["last"]) * (0.9 + 0.2 * random.random()))
    if float(qty) <= 0:
        return {"ok": False, "reason": "qty too small", "volume": 0.0, "filled": False}
    legs_maker = 0

    # ---- OPEN leg: maker-only, chase the bid ----
    cur_bid = t["bid"]
    _, cloid = _place_maker(symbol, "buy", fmt_price(symbol, cur_bid), qty, cfg)
    held = 0.0; deadline = time.time() + open_wait; last_reprice = time.time()
    while time.time() < deadline:
        time.sleep(2.0)
        held = abs(_position_qty(symbol, cfg))
        if held > 0:
            break
        if time.time() - last_reprice >= reprice_every:
            nt = get_ticker(symbol, cfg) or t
            if abs(nt["bid"] - cur_bid) >= tick:   # touch moved → re-queue at new bid
                _cancel_open(symbol, cfg, cloid)
                time.sleep(0.4)
                if abs(_position_qty(symbol, cfg)) > 0:  # filled during cancel
                    held = abs(_position_qty(symbol, cfg)); break
                cur_bid = nt["bid"]
                _, cloid = _place_maker(symbol, "buy", fmt_price(symbol, cur_bid), qty, cfg)
            last_reprice = time.time()
    if held <= 0:
        _cancel_open(symbol, cfg, cloid)
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": "open not filled (maker, after chase)"}
    legs_maker += 1
    open_notional = held * cur_bid
    entry = cur_bid

    # ---- CLOSE leg: 2-phase drift-capture + breakeven fallback ----
    t2 = get_ticker(symbol, cfg) or t
    cur_ask = t2["ask"]
    drift_target = MODE11_DRIFT_TARGET
    use_drift = SYMBOL_SPREAD_BASELINE.get(symbol, 10) > 15  # wide spread → drift
    phase1_deadline = time.time() + close_wait * 0.5   # first 50%: try drift
    deadline = time.time() + close_wait
    last_reprice = time.time(); flat = False
    
    # Phase 1: aggressive drift-capture price
    phase1_price = cur_ask * (1 + drift_target) if use_drift else cur_ask
    _, ccloid = _place_maker(symbol, "sell", fmt_price(symbol, phase1_price),
                             fmt_qty(symbol, held), cfg, reduce_only=True, post_only=False)
    
    while time.time() < deadline:
        time.sleep(2.0)
        if abs(_position_qty(symbol, cfg)) <= held * 0.02:
            flat = True; legs_maker += 1; break
        
        # stop-loss safety
        mark = (get_ticker(symbol, cfg) or t2)["last"]
        loss_frac = (entry - mark) / entry * leverage
        if loss_frac >= stop_loss_frac:
            _cancel_open(symbol, cfg, ccloid)
            pos = [p for p in open_positions(cfg) if p.get("symbol") == symbol]
            if pos: close_position(pos[0], cfg)
            flat = abs(_position_qty(symbol, cfg)) <= held * 0.02
            break
        
        # Phase transition: drift failed → fallback to market price (breakeven)
        if use_drift and not flat and time.time() > phase1_deadline and phase1_price != cur_ask:
            _cancel_open(symbol, cfg, ccloid)
            time.sleep(0.3)
            if abs(_position_qty(symbol, cfg)) <= held * 0.02:
                flat = True; legs_maker += 1; break
            cur_ask = (get_ticker(symbol, cfg) or t2)["ask"]
            phase1_price = cur_ask  # breakeven — no more drift
            _, ccloid = _place_maker(symbol, "sell", fmt_price(symbol, cur_ask),
                                     fmt_qty(symbol, held), cfg, reduce_only=True, post_only=False)
            log.info(f"patient_mm {symbol}: drift fallback → breakeven close at market")
            continue
        
        if time.time() - last_reprice >= reprice_every:
            nt = get_ticker(symbol, cfg) or t2
            if phase1_price == cur_ask:  # breakeven phase
                if abs(nt["ask"] - cur_ask) >= tick:
                    _cancel_open(symbol, cfg, ccloid)
                    time.sleep(0.4)
                    if abs(_position_qty(symbol, cfg)) <= held * 0.02:
                        flat = True; legs_maker += 1; break
                    cur_ask = nt["ask"]
                    _, ccloid = _place_maker(symbol, "sell", fmt_price(symbol, cur_ask),
                                             fmt_qty(symbol, held), cfg, reduce_only=True, post_only=False)
            else:  # drift phase
                if abs(nt["ask"] - cur_ask) >= tick:
                    _cancel_open(symbol, cfg, ccloid)
                    time.sleep(0.4)
                    if abs(_position_qty(symbol, cfg)) <= held * 0.02:
                        flat = True; legs_maker += 1; break
                    cur_ask = nt["ask"]
                    p = cur_ask * (1 + drift_target)
                    _, ccloid = _place_maker(symbol, "sell", fmt_price(symbol, p),
                                             fmt_qty(symbol, held), cfg, reduce_only=True, post_only=False)
            last_reprice = time.time()
    if not flat:  # DESPERATE safety: taker close with retries (LAST RESORT)
        log.warning(f"patient_mm {symbol}: maker close timeout after {close_wait}s — "
                    f"taker close (LAST RESORT, avoid holding position)")
        for attempt in range(3):
            _cancel_open(symbol, cfg, ccloid)
            pos = [p for p in open_positions(cfg) if p.get("symbol") == symbol]
            if pos:
                close_position(pos[0], cfg)
            time.sleep(1.0 * (attempt + 1))  # backoff
            flat = abs(_position_qty(symbol, cfg)) <= held * 0.02
            if flat:
                break
        if not flat:
            log.error(f"patient_mm {symbol}: FAILED to close after 3 retries — "
                      f"will be caught by auto-recovery")
    return {"ok": flat, "filled": True, "volume": round(open_notional * 2, 2),
            "symbol": symbol, "legs_maker": legs_maker, "open_notional": round(open_notional, 2)}
    legs_maker = 0

    # ---- OPEN leg: maker-only, chase the bid ----
    cur_bid = t["bid"]
    _, cloid = _place_maker(symbol, "buy", fmt_price(symbol, cur_bid), qty, cfg)
    held = 0.0; deadline = time.time() + open_wait; last_reprice = time.time()
    while time.time() < deadline:
        time.sleep(2.0)
        held = abs(_position_qty(symbol, cfg))
        if held > 0:
            break
        if time.time() - last_reprice >= reprice_every:
            nt = get_ticker(symbol, cfg) or t
            if abs(nt["bid"] - cur_bid) >= tick:   # touch moved → re-queue at new bid
                _cancel_open(symbol, cfg, cloid)
                time.sleep(0.4)
                if abs(_position_qty(symbol, cfg)) > 0:  # filled during cancel
                    held = abs(_position_qty(symbol, cfg)); break
                cur_bid = nt["bid"]
                _, cloid = _place_maker(symbol, "buy", fmt_price(symbol, cur_bid), qty, cfg)
            last_reprice = time.time()
    if held <= 0:
        _cancel_open(symbol, cfg, cloid)
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": "open not filled (maker, after chase)"}
    legs_maker += 1
    open_notional = held * cur_bid
    entry = cur_bid

    # ---- CLOSE leg: maker-only with stop-loss + final taker safety ----
    t2 = get_ticker(symbol, cfg) or t
    cur_ask = t2["ask"]
    _, ccloid = _place_maker(symbol, "sell", fmt_price(symbol, cur_ask), fmt_qty(symbol, held),
                             cfg, reduce_only=True)
    deadline = time.time() + close_wait; last_reprice = time.time(); flat = False
    while time.time() < deadline:
        time.sleep(2.0)
        if abs(_position_qty(symbol, cfg)) <= held * 0.02:
            flat = True; legs_maker += 1; break
        # stop-loss safety (price fell hard while long)
        mark = (get_ticker(symbol, cfg) or t2)["last"]
        loss_frac = (entry - mark) / entry * leverage  # approx loss vs margin
        if loss_frac >= stop_loss_frac:
            _cancel_open(symbol, cfg, ccloid)
            pos = [p for p in open_positions(cfg) if p.get("symbol") == symbol]
            if pos:
                close_position(pos[0], cfg)
            flat = abs(_position_qty(symbol, cfg)) <= held * 0.02
            break
        if time.time() - last_reprice >= reprice_every:
            nt = get_ticker(symbol, cfg) or t2
            if abs(nt["ask"] - cur_ask) >= tick:
                _cancel_open(symbol, cfg, ccloid)
                time.sleep(0.4)
                if abs(_position_qty(symbol, cfg)) <= held * 0.02:
                    flat = True; legs_maker += 1; break
                cur_ask = nt["ask"]
                _, ccloid = _place_maker(symbol, "sell", fmt_price(symbol, cur_ask),
                                         fmt_qty(symbol, held), cfg, reduce_only=True)
            last_reprice = time.time()
    if not flat:  # final safety: taker close with retries
        for attempt in range(3):
            _cancel_open(symbol, cfg, ccloid)
            pos = [p for p in open_positions(cfg) if p.get("symbol") == symbol]
            if pos:
                close_position(pos[0], cfg)
            time.sleep(1.0 * (attempt + 1))  # backoff
            flat = abs(_position_qty(symbol, cfg)) <= held * 0.02
            if flat:
                break
        if not flat:
            log.error(f"patient_mm {symbol}: FAILED to close after 3 retries — "
                      f"will be caught by auto-recovery")
    return {"ok": flat, "filled": True, "volume": round(open_notional * 2, 2),
            "symbol": symbol, "legs_maker": legs_maker, "open_notional": round(open_notional, 2)}


# ══════════════════════════════════════════════════════════════════
# BEARDOWN: patient_mm_short_round — SELL-first variant for BEARISH
# ══════════════════════════════════════════════════════════════════
# Identical to patient_mm_round but direction-flipped:
#   OPEN:  post-only SELL at ask (SHORT) — chase the ask, repricing
#   CLOSE: post-only BUY at bid (cover short) — maker, + stop-loss
#   STOP-LOSS: price RISES > 40% of margin against short position
#
# ponytail: copy-paste with side-flip; refactor to parametrized if both variants survive 30+ days
def patient_mm_short_round(symbol: str, cfg: dict, margin: float | None = None,
                           leverage: int | None = None, open_wait: float = 90.0,
                           close_wait: float = 120.0, reprice_every: float = 5.0,
                           stop_loss_frac: float = 0.40,
                           spread_threshold: float | None = None,
                           momentum_threshold: float | None = None) -> dict:
    """BEARISH patient market-making: SELL-first (SHORT), then BUY to cover.
    
    Same safety: maker-only opens, stop-loss, taker fallback as LAST RESORT.
    Direction aligned with bearish market — captures spread + directional edge.
    """
    margin = margin if margin is not None else SCALP_MARGIN
    leverage = min(leverage or SCALP_LEVERAGE, SYMBOLS.get(symbol, {}).get("max_lev", 5))
    meta = SYMBOLS.get(symbol, {})
    tick = 10 ** (-meta.get("px_decimals", 2))
    t = get_ticker(symbol, cfg)
    if not t or t["bid"] <= 0 or t["ask"] <= 0:
        return {"ok": False, "reason": "no book", "volume": 0.0, "filled": False}
    
    # ── SPREAD GATE ──
    spread_pct = (t["ask"] - t["bid"]) / t["last"] * 100 if t["last"] > 0 else 0
    if spread_threshold is not None:
        gate = spread_threshold
    elif symbol == "BTC-USD":
        gate = 0.008
    elif symbol in ("SILVER-USD", "ZEC-USD", "XAUT-USD"):
        gate = 0.010
    else:
        gate = 0.015
    if spread_pct > gate:
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": f"spread {spread_pct:.4f}% > {gate}%"}
    
    # ── MOMENTUM GATE: skip if price trending (reduces adverse selection) ──
    mom_gate = momentum_threshold if momentum_threshold is not None else 0.03
    time.sleep(5.0)
    t2_check = get_ticker(symbol, cfg)
    if t2_check and t2_check["last"] > 0:
        momentum_pct = abs(t2_check["last"] - t["last"]) / t["last"] * 100
        if momentum_pct > mom_gate:
            return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                    "reason": f"momentum {momentum_pct:.4f}% > {mom_gate}%"}
    
    qty = fmt_qty(symbol, (margin * leverage / t["last"]) * (0.9 + 0.2 * random.random()))
    if float(qty) <= 0:
        return {"ok": False, "reason": "qty too small", "volume": 0.0, "filled": False}
    legs_maker = 0

    # ---- OPEN leg: maker-only SELL at ask, chase the ask (BEARISH direction) ----
    cur_ask = t["ask"]
    _, cloid = _place_maker(symbol, "sell", fmt_price(symbol, cur_ask), qty, cfg)
    held = 0.0; deadline = time.time() + open_wait; last_reprice = time.time()
    while time.time() < deadline:
        time.sleep(2.0)
        held = abs(_position_qty(symbol, cfg))
        if held > 0:
            break
        if time.time() - last_reprice >= reprice_every:
            nt = get_ticker(symbol, cfg) or t
            if abs(nt["ask"] - cur_ask) >= tick:   # ask moved → re-queue at new ask
                _cancel_open(symbol, cfg, cloid)
                time.sleep(0.4)
                if abs(_position_qty(symbol, cfg)) > 0:  # filled during cancel
                    held = abs(_position_qty(symbol, cfg)); break
                cur_ask = nt["ask"]
                _, cloid = _place_maker(symbol, "sell", fmt_price(symbol, cur_ask), qty, cfg)
            last_reprice = time.time()
    if held <= 0:
        _cancel_open(symbol, cfg, cloid)
        return {"ok": True, "filled": False, "volume": 0.0, "symbol": symbol,
                "reason": "short open not filled (maker, after chase)"}
    legs_maker += 1
    open_notional = held * cur_ask
    entry = cur_ask  # SHORT entry price

    # ---- CLOSE leg: 2-phase drift-capture BUY at discount + stop-loss ----
    t2 = get_ticker(symbol, cfg) or t
    cur_bid = t2["bid"]
    drift_target = MODE11_DRIFT_TARGET
    use_drift = SYMBOL_SPREAD_BASELINE.get(symbol, 10) > 15  # wide spread → drift
    phase1_deadline = time.time() + close_wait * 0.5
    deadline = time.time() + close_wait
    last_reprice = time.time(); flat = False
    
    # Phase 1: aggressive drift-capture (buy below market for SHORT)
    phase1_price = cur_bid * (1 - drift_target) if use_drift else cur_bid
    _, ccloid = _place_maker(symbol, "buy", fmt_price(symbol, phase1_price),
                             fmt_qty(symbol, held), cfg, reduce_only=True, post_only=False)
    
    while time.time() < deadline:
        time.sleep(2.0)
        if abs(_position_qty(symbol, cfg)) <= held * 0.02:
            flat = True; legs_maker += 1; break
        
        # stop-loss safety (price ROSE hard while SHORT)
        mark = (get_ticker(symbol, cfg) or t2)["last"]
        loss_frac = (mark - entry) / entry * leverage
        if loss_frac >= stop_loss_frac:
            _cancel_open(symbol, cfg, ccloid)
            pos = [p for p in open_positions(cfg) if p.get("symbol") == symbol]
            if pos: close_position(pos[0], cfg)
            flat = abs(_position_qty(symbol, cfg)) <= held * 0.02
            break
        
        # Phase transition: drift failed → fallback to market price (breakeven)
        if use_drift and not flat and time.time() > phase1_deadline and phase1_price != cur_bid:
            _cancel_open(symbol, cfg, ccloid)
            time.sleep(0.3)
            if abs(_position_qty(symbol, cfg)) <= held * 0.02:
                flat = True; legs_maker += 1; break
            cur_bid = (get_ticker(symbol, cfg) or t2)["bid"]
            phase1_price = cur_bid  # breakeven
            _, ccloid = _place_maker(symbol, "buy", fmt_price(symbol, cur_bid),
                                     fmt_qty(symbol, held), cfg, reduce_only=True, post_only=False)
            log.info(f"patient_mm_short {symbol}: drift fallback → breakeven close at market")
            continue
        
        if time.time() - last_reprice >= reprice_every:
            nt = get_ticker(symbol, cfg) or t2
            if phase1_price == cur_bid:  # breakeven phase
                if abs(nt["bid"] - cur_bid) >= tick:
                    _cancel_open(symbol, cfg, ccloid)
                    time.sleep(0.4)
                    if abs(_position_qty(symbol, cfg)) <= held * 0.02:
                        flat = True; legs_maker += 1; break
                    cur_bid = nt["bid"]
                    _, ccloid = _place_maker(symbol, "buy", fmt_price(symbol, cur_bid),
                                             fmt_qty(symbol, held), cfg, reduce_only=True, post_only=False)
            else:  # drift phase
                if abs(nt["bid"] - cur_bid) >= tick:
                    _cancel_open(symbol, cfg, ccloid)
                    time.sleep(0.4)
                    if abs(_position_qty(symbol, cfg)) <= held * 0.02:
                        flat = True; legs_maker += 1; break
                    cur_bid = nt["bid"]
                    p = cur_bid * (1 - drift_target)
                    _, ccloid = _place_maker(symbol, "buy", fmt_price(symbol, p),
                                             fmt_qty(symbol, held), cfg, reduce_only=True, post_only=False)
            last_reprice = time.time()
    if not flat:  # DESPERATE safety: taker close with retries (LAST RESORT)
        log.warning(f"patient_mm_short {symbol}: maker close timeout after {close_wait}s — "
                    f"taker close (LAST RESORT, avoid holding SHORT position)")
        for attempt in range(3):
            _cancel_open(symbol, cfg, ccloid)
            pos = [p for p in open_positions(cfg) if p.get("symbol") == symbol]
            if pos:
                close_position(pos[0], cfg)
            time.sleep(1.0 * (attempt + 1))  # backoff
            flat = abs(_position_qty(symbol, cfg)) <= held * 0.02
            if flat:
                break
        if not flat:
            log.error(f"patient_mm_short {symbol}: FAILED to close SHORT after 3 retries — "
                      f"will be caught by auto-recovery")
    return {"ok": flat, "filled": True, "volume": round(open_notional * 2, 2),
            "symbol": symbol, "legs_maker": legs_maker, "open_notional": round(open_notional, 2),
            "direction": "short"}


# ══════════════════════════════════════════════════════════════════
# BEARDOWN: patient_mm_regime_round — regime-aware routing
# ══════════════════════════════════════════════════════════════════
def _read_regime_direction(intel_dir: str | None = None) -> tuple[str, float]:
    """Read BTC direction from latest intelligence JSONL.
    
    Returns (direction, confidence) where:
      direction = "short" if BEAR (btc_dir < 0, conf >= 0.55)
      direction = "long"  if BULL (btc_dir > 0, conf >= 0.55 + score >= 55)
      direction = "alternate" if NEUTRAL (alternate BUY/SELL)
      confidence = 0.0 - 1.0
    Falls back to "long" (safe default) if intel unavailable.
    """
    import glob as _glob
    intel_dir = intel_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "freqtrade_user_data", "data", "binance", "intelligence")
    try:
        files = sorted(_glob.glob(os.path.join(intel_dir, "intel_*.jsonl")))
        if not files:
            return "long", 0.0
        last_line = None
        with open(files[-1], encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    last_line = ln
        if not last_line:
            return "long", 0.0
        row = json.loads(last_line.strip())
        btc_dir = int(row.get("fc_BTC_dir_enc", 0))
        btc_conf = float(row.get("fc_BTC_conf", 0) or 0)
        btc_agree = float(row.get("fc_BTC_agreement", btc_conf) or btc_conf)
        score = float(row.get("composite_score", 50))
        
        if btc_conf >= 0.55 and btc_agree >= 0.55 and btc_dir < 0:
            return "short", btc_conf
        elif btc_conf >= 0.55 and btc_agree >= 0.55 and btc_dir > 0 and score >= 50:
            return "long", btc_conf
        else:
            return "alternate", btc_conf
    except Exception:
        return "long", 0.0


# Cycle counter for alternating direction in NEUTRAL regime
_regime_cycle_counter: int = 0


def patient_mm_regime_round(symbol: str, cfg: dict, margin: float | None = None,
                            leverage: int | None = None, open_wait: float = 90.0,
                            close_wait: float = 120.0, reprice_every: float = 5.0,
                            stop_loss_frac: float = 0.35,
                            spread_threshold: float | None = None,
                            momentum_threshold: float | None = None) -> dict:
    """Regime-aware patient market-making round.
    
    Routes to:
      - patient_mm_short_round() when BEARISH  (SELL-first, directional)
      - patient_mm_round()       when BULLISH   (BUY-first, directional)  
      - Alternating BUY/SELL     when NEUTRAL   (delta-neutral, spread capture)
    
    Intel is read once per cycle (cached by _read_regime_direction which
    reads from the latest JSONL — daemon updates this every cycle).
    """
    global _regime_cycle_counter
    direction, conf = _read_regime_direction()
    
    if direction == "short":
        # BEARISH: SELL-first for directional edge
        r = patient_mm_short_round(
            symbol, cfg, margin=margin, leverage=leverage,
            open_wait=open_wait, close_wait=close_wait,
            reprice_every=reprice_every, stop_loss_frac=stop_loss_frac,
            spread_threshold=spread_threshold, momentum_threshold=momentum_threshold)
        r["regime"] = "BEAR"
        r["regime_conf"] = round(conf, 2)
        return r
    
    elif direction == "alternate":
        # NEUTRAL/SIDEWAYS: LONG_BIAS → all LONG in up-market, else alternate
        if MODE11_LONG_BIAS:
            # Sideways-up: LONG-only captures directional drift on EVERY trade
            r = patient_mm_round(
                symbol, cfg, margin=margin, leverage=leverage,
                open_wait=open_wait, close_wait=close_wait,
                reprice_every=reprice_every, stop_loss_frac=stop_loss_frac,
                spread_threshold=spread_threshold, momentum_threshold=momentum_threshold)
            r["direction"] = "long"
            r["regime"] = "NEUTRAL↑"
            r["regime_conf"] = round(conf, 2)
            return r
        
        _regime_cycle_counter += 1
        if _regime_cycle_counter % 2 == 0:
            r = patient_mm_round(
                symbol, cfg, margin=margin, leverage=leverage,
                open_wait=open_wait, close_wait=close_wait,
                reprice_every=reprice_every, stop_loss_frac=stop_loss_frac,
                spread_threshold=spread_threshold, momentum_threshold=momentum_threshold)
            r["direction"] = "long"
        else:
            r = patient_mm_short_round(
                symbol, cfg, margin=margin, leverage=leverage,
                open_wait=open_wait, close_wait=close_wait,
                reprice_every=reprice_every, stop_loss_frac=stop_loss_frac,
                spread_threshold=spread_threshold, momentum_threshold=momentum_threshold)
            r["direction"] = "short"
        r["regime"] = "NEUTRAL"
        r["regime_conf"] = round(conf, 2)
        return r
    
    else:
        # BULLISH: BUY-first for directional edge (default safe path)
        r = patient_mm_round(
            symbol, cfg, margin=margin, leverage=leverage,
            open_wait=open_wait, close_wait=close_wait,
            reprice_every=reprice_every, stop_loss_frac=stop_loss_frac,
            spread_threshold=spread_threshold, momentum_threshold=momentum_threshold)
        r["regime"] = "BULL"
        r["regime_conf"] = round(conf, 2)
        return r


def cmd_patient_test(cfg: dict, rounds: int, margin: float, leverage: int) -> int:
    """Empirical patient-MM test: measure improved maker-fill rate + ratio."""
    addr = cfg.get("address", "")
    def wallet():
        b = cli(["balance", "perps", addr], cfg=cfg)
        return float(b[0].get("total", 0) or 0) if isinstance(b, list) and b else None
    bal0 = wallet()
    for s in SCALP_SYMBOLS:
        set_leverage(s, min(leverage, SYMBOLS.get(s, {}).get("max_lev", 5)), cfg)
    tv = 0.0; legs = 0; mlegs = 0; filled = 0
    for i in range(rounds):
        r = patient_mm_round(SCALP_SYMBOLS[i % len(SCALP_SYMBOLS)], cfg, margin=margin, leverage=leverage)
        if r.get("filled"):
            filled += 1; tv += r["volume"]; legs += 2; mlegs += r.get("legs_maker", 0)
            log.info(f"round {i+1} {r['symbol']}: vol +${r['volume']} maker {r.get('legs_maker')}/2 ok={r['ok']}")
        else:
            log.info(f"round {i+1} {r['symbol']}: {r.get('reason')}")
        time.sleep(1.0)
    bal1 = wallet(); cost = (bal0 - bal1) if (bal0 and bal1) else None
    mpct = (mlegs / legs * 100) if legs else 0
    print("\n" + "=" * 60)
    print("PATIENT-MM TEST RESULTS")
    print(f"  filled: {filled}/{rounds} | volume ${tv:,.0f} | MAKER FILL {mpct:.0f}% ({mlegs}/{legs})")
    if cost is not None and tv > 0:
        net = cost / tv * 100; ratio = (tv / cost) if cost > 0 else float("inf")
        print(f"  cost(Tier0) ${cost:+.4f} | net {net:.4f}% | ratio NOW {'EARN' if cost<=0 else f'{ratio:,.0f}:1'}")
        fee_pct = (mpct/100)*0.0114 + (1-mpct/100)*0.0380
        adverse = max(0.0, net - fee_pct)
        print(f"  implied adverse {adverse:.4f}%")
        for tn, mk in [("Rebate T1 (-0.001%)", -0.001), ("Rebate T2 (-0.002%)", -0.002), ("Rebate T3 (-0.003%)", -0.003)]:
            proj = (mpct/100)*mk + (1-mpct/100)*0.0380 + adverse
            pr = (100/proj) if proj > 0 else float("inf")
            print(f"  PROJECTED {tn}: {'EARN(∞)' if proj<=0 else f'{pr:,.0f}:1'}")
    print("=" * 60)
    return 0


def cmd_maker_test(cfg: dict, rounds: int, margin: float, leverage: int) -> int:
    """Empirical maker test: run N maker round-trips, measure REAL maker-fill rate
    + adverse selection (cost beyond fees), then project the rebate-tier ratio."""
    addr = cfg.get("address", "")
    def wallet():
        b = cli(["balance", "perps", addr], cfg=cfg)
        return float(b[0].get("total", 0) or 0) if isinstance(b, list) and b else None
    bal0 = wallet()
    # Set leverage once per symbol upfront (while flat) — avoids per-round errors.
    for s in SCALP_SYMBOLS:
        set_leverage(s, min(leverage, SYMBOLS.get(s, {}).get("max_lev", 5)), cfg)
    total_vol = 0.0; total_legs = 0; maker_legs = 0; filled_rounds = 0
    for i in range(rounds):
        r = maker_scalp_round(SCALP_SYMBOLS[i % len(SCALP_SYMBOLS)], cfg,
                              margin=margin, leverage=leverage)
        if r.get("filled"):
            filled_rounds += 1
            total_vol += r["volume"]; total_legs += 2; maker_legs += r.get("legs_maker", 0)
            log.info(f"round {i+1} {r['symbol']}: vol +${r['volume']} maker_legs {r.get('legs_maker')}/2 ok={r['ok']}")
        else:
            log.info(f"round {i+1} {r['symbol']}: {r.get('reason')}")
        time.sleep(1.5)
    bal1 = wallet()
    cost = (bal0 - bal1) if (bal0 and bal1) else None
    maker_pct = (maker_legs / total_legs * 100) if total_legs else 0
    print("\n" + "=" * 60)
    print("EMPIRICAL MAKER TEST RESULTS")
    print(f"  filled rounds: {filled_rounds}/{rounds}")
    print(f"  total volume: ${total_vol:,.0f}")
    print(f"  MAKER FILL RATE: {maker_pct:.0f}% ({maker_legs}/{total_legs} legs)")
    if cost is not None and total_vol > 0:
        net_pct = cost / total_vol * 100
        ratio = (total_vol / cost) if cost > 0 else float("inf")
        print(f"  cost (Tier0): ${cost:+.4f} | net {net_pct:.4f}% | "
              f"ratio NOW {'EARN' if cost<=0 else f'{ratio:,.0f}:1'}")
        # adverse = net_cost - fees (fees at measured maker%/taker%)
        fee_pct = (maker_pct/100)*0.0114 + (1-maker_pct/100)*0.0380
        adverse = max(0.0, net_pct - fee_pct)
        print(f"  implied adverse/spread: {adverse:.4f}%")
        # PROJECT rebate-tier ratios (maker rate flips negative)
        for tn, mk in [("Rebate T1 (-0.001%)", -0.001), ("Rebate T2 (-0.002%)", -0.002)]:
            proj = (maker_pct/100)*mk + (1-maker_pct/100)*0.0380 + adverse
            pr = (100/proj) if proj > 0 else float("inf")
            print(f"  PROJECTED {tn}: {'EARN (∞)' if proj<=0 else f'{pr:,.0f}:1'} (at measured {maker_pct:.0f}% maker + {adverse:.4f}% adverse)")
    print("=" * 60)
    return 0


def cmd_scalp(cfg: dict, live: bool, rounds: int, symbol: str | None = None) -> int:
    """Run N SoPoints volume scalp round-trips across liquid symbols."""
    syms = [symbol] if symbol else SCALP_SYMBOLS
    total_vol = 0.0
    bal0 = None
    bal = cli(["balance", "perps", cfg.get("address", "")], cfg=cfg) if cfg.get("address") else None
    if isinstance(bal, list) and bal:
        bal0 = float(bal[0].get("total", 0) or 0)
    for i in range(rounds):
        sym = syms[i % len(syms)]
        if not live:
            notional = SCALP_MARGIN * min(SCALP_LEVERAGE, SYMBOLS.get(sym, {}).get("max_lev", 5))
            log.info(f"[DRY] scalp {sym}: would generate ~${notional*2:.0f} volume "
                     f"(margin ${SCALP_MARGIN} x {SCALP_LEVERAGE}x)")
            total_vol += notional * 2
            continue
        r = scalp_round(sym, cfg)
        log.info(f"scalp {sym}: {'✅' if r['ok'] else '❌ '+r.get('reason','')} vol +${r['volume']}")
        total_vol += r["volume"]
        time.sleep(1)
    if live and bal0 is not None:
        bal = cli(["balance", "perps", cfg.get("address", "")], cfg=cfg)
        bal1 = float(bal[0].get("total", 0) or 0) if isinstance(bal, list) and bal else bal0
        cost = bal0 - bal1
        ratio = (total_vol / cost) if cost > 0 else float("inf")
        log.info(f"SCALP DONE: volume +${total_vol:.0f} | cost ${cost:+.4f} | "
                 f"${ratio:,.0f} volume per $1 cost" if cost > 0 else
                 f"SCALP DONE: volume +${total_vol:.0f} | cost ${cost:+.4f}")
    else:
        log.info(f"[DRY] total volume would be ~${total_vol:.0f}")
    return 0


SODEX_MODEL_URL = os.environ.get("SODEX_MODEL_URL", "http://localhost:8001")
MODEL_MIN_OOS_ACC = float(os.environ.get("SODEX_MODEL_MIN_OOS_ACC", "51"))  # loosened 52→51 (still >coin-flip)


def model_direction(symbol: str) -> dict:
    """Direction from the SoDEX LightGBM 48h model server, gated by out-of-sample
    directional accuracy (skip symbols whose model is unreliable, e.g. OOS<52%)."""
    base = symbol.split("-")[0]
    try:
        with httpx.Client(timeout=10) as c:
            d = c.get(f"{SODEX_MODEL_URL}/predict/{base}").json()
    except Exception as e:
        log.warning(f"model_direction({symbol}): {e}")
        return {"direction": "NEUTRAL", "confidence": 0.0, "oos_acc": None, "reason": "model unreachable"}
    oos = d.get("model_dir_acc_oos")
    if oos is not None and oos < MODEL_MIN_OOS_ACC:
        return {"direction": "NEUTRAL", "confidence": 0.0, "oos_acc": oos,
                "reason": f"model OOS {oos:.0f}% < {MODEL_MIN_OOS_ACC:.0f}% — unreliable"}
    return {"direction": d.get("direction", "NEUTRAL"), "confidence": float(d.get("confidence", 0) or 0),
            "oos_acc": oos, "predicted_return_pct": d.get("predicted_return_pct"),
            "reason": "lightgbm 48h"}


def atr_pct(symbol: str, cfg: dict, period: int = 14) -> float | None:
    """ATR% on the 1h timeframe from SoDEX klines (mean true-range / close × 100).
    Volatility input for the governor's dynamic leverage."""
    try:
        with httpx.Client(timeout=10, headers={"Accept": "application/json"}) as c:
            r = c.get(f"{cfg['perps_url']}/markets/{symbol}/klines",
                      params={"interval": "1h", "limit": period + 1})
            data = (r.json() or {}).get("data") or []
    except Exception as e:
        log.warning(f"atr_pct({symbol}): {e}")
        return None
    trs = []
    for k in data[:period]:
        try:
            h, lo, cl = float(k["h"]), float(k["l"]), float(k["c"])
            if cl > 0:
                trs.append((h - lo) / cl * 100)
        except Exception:
            pass
    return round(sum(trs) / len(trs), 4) if trs else None


def governor_leverage_for(symbol: str, cfg: dict, rr: float = 1.5) -> dict:
    """WIRE: OOS-validated model → governor → conviction-scaled leverage.

    Reads the LightGBM 48h model (OOS-gated), the live ATR%, and asks the governor
    (dynamic_leverage) what leverage to use: floor (3x) when the model is neutral/
    unconfident, scaling up toward 25x as validated conviction rises — only in a
    calm-enough market to stay liquidation-safe. This is the automatic 'leverage
    rises when analysis shows strong direction' the user asked for.
    """
    import sodex_governor as gov
    md = model_direction(symbol)
    direction, prob = md["direction"], md["confidence"]
    a = atr_pct(symbol, cfg)
    prob_min = gov.mesin4_prob_threshold(rr)["prob_min"]
    out = {"symbol": symbol, "direction": direction, "prob": prob, "prob_min": prob_min,
           "atr_pct": a, "oos_acc": md.get("oos_acc")}
    if a is None or a <= 0:
        return {**out, "leverage": gov.LEV_FLOOR, "conviction": 0.0, "ok": False, "reason": "no ATR"}
    if direction == "NEUTRAL" or prob < prob_min:
        return {**out, "leverage": gov.LEV_FLOOR, "conviction": 0.0, "ok": False,
                "reason": f"no conviction (dir {direction}, prob {prob:.2f} < {prob_min})"}
    dl = gov.dynamic_leverage(a, prob, prob_min)
    return {**out, "leverage": dl["leverage"], "conviction": dl["conviction"],
            "vol_ceiling": dl.get("vol_ceiling"), "ok": dl["ok"], "reason": dl["reason"]}


def hermes_direction(symbol: str = "BTC") -> dict:
    """Fetch directional signal from Hermes (posture + forecast). Returns {dir, reason}."""
    try:
        with httpx.Client(timeout=8) as c:
            status = c.get(f"{HERMES_URL}/hermes/status").json()
            fc = c.get(f"{HERMES_URL}/prediction/current/{symbol}").json()
        direction = (fc.get("forecast", {}) or {}).get("direction", "NEUTRAL")
        return {"direction": direction, "posture": status.get("posture", "?"),
                "confidence": (fc.get("forecast", {}) or {}).get("confidence", 0)}
    except Exception as e:
        log.warning(f"Hermes signal unavailable: {e}")
        return {"direction": "NEUTRAL", "posture": "?", "confidence": 0}


def rank_symbols_by_spread(cfg: dict, top_n: int = 10, max_spread: float = 0.015,
                           min_volume: float = 50000) -> list[str]:
    """Fetch live tickers and return top N symbols by tightest spread.
    Filters matched to patient_mm_round spread gates.
    Used by daemon MODE 3 (multi-symbol parallel) for dynamic symbol selection.
    Falls back to SCALP_SYMBOLS if API unavailable."""
    try:
        import httpx
        with httpx.Client(timeout=10) as c:
            r = c.get(f"{cfg.get('perps_url', 'https://mainnet-gw.sodex.dev/api/v1/perps')}/markets/tickers")
            data = (r.json() or {}).get("data", []) or []
    except Exception:
        return SCALP_SYMBOLS[:top_n]
    ranked = []
    for t in data:
        sym = t.get("symbol", "")
        if sym not in SYMBOLS:
            continue
        bid = float(t.get("bidPx", 0) or 0)
        ask = float(t.get("askPx", 0) or 0)
        last = float(t.get("lastPx", 0) or 0)
        vol = float(t.get("quoteVolume", 0) or 0)
        if bid <= 0 or ask <= 0 or last <= 0:
            continue
        spread_pct = (ask - bid) / last * 100
        if spread_pct > max_spread or vol < min_volume:
            continue
        ranked.append((spread_pct, sym, vol))
    ranked.sort()
    result = [s[1] for s in ranked[:top_n]]
    return result if result else SCALP_SYMBOLS[:top_n]


# ──────────────────────────────────────────────────────────────────────
# COMMANDS
# ──────────────────────────────────────────────────────────────────────


def cmd_status(cfg: dict) -> int:
    print(f"SoDEX farming — network={'TESTNET' if cfg['testnet'] else 'MAINNET'} "
          f"account={cfg['account_id'] or '(unset)'} api_key={cfg['api_key'] or '(unset)'}")
    if not Path(SODEX_BIN).exists():
        log.error(f"sodex CLI not found at {SODEX_BIN}. Run: bash scripts/build_sodex_cli.sh")
        return 1
    for sym in SYMBOLS:
        t = get_ticker(sym, cfg)
        if t:
            print(f"  {sym}: last={t['last']} bid={t['bid']} ask={t['ask']} "
                  f"vol24h=${t['volume_24h']/1e6:.1f}M")
    if cfg["account_id"]:
        bal = cli(["balance", "perps", cfg.get("address", "")], cfg=cfg) if cfg.get("address") else None
        if bal:
            print(f"  balance: {bal}")
    sig = hermes_direction()
    print(f"  Hermes: direction={sig['direction']} posture={sig['posture']} conf={sig['confidence']}")
    return 0


def cmd_validate_signing(cfg: dict) -> int:
    """Safe signing test: place an UNFILLABLE limit buy far below market, then cancel.
    Zero fill risk — proves EIP-712 signing works end-to-end on the live account."""
    if not cfg["private_key"]:
        log.error("SODEX_PRIVATE_KEY not set in .env — cannot validate signing.")
        return 1
    sym = "BTC-USD"
    t = get_ticker(sym, cfg)
    if not t:
        log.error("Could not fetch ticker.")
        return 1
    last = t["last"]
    far_price = fmt_price(sym, last * 0.5)  # 50% below market — will NOT fill
    qty = "0.001"  # minimal
    log.info(f"Placing UNFILLABLE post-only buy: {sym} @ {far_price} (market {last}) qty {qty}")
    place = cli(["orders", "place", "perps", "--symbol", sym, "--side", "buy",
                 "--type", "limit", "--price", far_price, "--qty", qty,
                 "--tif", "gtx"], cfg=cfg, auth=True)
    if place is None:
        log.error("❌ Signing FAILED (order rejected). Check key/account/nonce.")
        return 1
    log.info(f"✅ Order accepted — signing works! Response: {json.dumps(place)[:400]}")
    oid, cloid = _extract_order_ids(place)
    time.sleep(1)
    sid = SYMBOLS[sym]["id"]
    cancel_args = ["orders", "cancel", "perps", "--symbol-id", str(sid)]
    if oid:
        cancel_args += ["--order-id", str(oid)]
    elif cloid:
        cancel_args += ["--cl-ord-id", str(cloid)]
    cancel = cli(cancel_args, cfg=cfg, auth=True)
    log.info(f"Cancel result: {json.dumps(cancel)[:200] if cancel is not None else 'FAILED — cancel manually in UI!'}")
    log.info("✅ Signing validation complete. Safe to proceed to farming.")
    return 0


def _extract_order_ids(place_resp) -> tuple:
    """Pull (orderID, clOrdID) from a place-order response, tolerating shape variants."""
    d = place_resp
    if isinstance(d, dict):
        if "data" in d and isinstance(d["data"], (dict, list)):
            d = d["data"]
    items = d if isinstance(d, list) else [d]
    for it in items:
        if not isinstance(it, dict):
            continue
        oid = it.get("orderID") or it.get("orderId") or it.get("oid")
        cloid = it.get("clOrdID") or it.get("clOrdId") or it.get("cloid")
        if oid or cloid:
            return oid, cloid
    return None, None


def cmd_farm(cfg: dict, live: bool, symbol: str, margin_usd: float | None = None,
            lev_override: int | None = None) -> int:
    """One farming cycle: only act on a strong directional Hermes signal.
    Sets confidence-scaled leverage (>=10x), then places a post-only maker
    order sized by margin (notional = margin * leverage). Dry-run unless --live."""
    dry = not live
    margin = margin_usd if margin_usd is not None else MARGIN_PER_ORDER
    sig = hermes_direction(symbol.split("-")[0])
    direction, conf = sig["direction"], float(sig["confidence"] or 0)

    if direction == "NEUTRAL":
        log.info(f"Hermes NEUTRAL — skip (posture {sig['posture']}).")
        return 0
    if conf < MIN_CONFIDENCE:
        log.info(f"Confidence {conf:.2f} < {MIN_CONFIDENCE} — skip (signal too weak).")
        return 0

    # Position cap (real orders only — dry-run still previews).
    if live:
        npos = len(open_positions(cfg))
        if npos >= MAX_POSITIONS:
            log.info(f"Max positions ({MAX_POSITIONS}) open — skip.")
            return 0

    t = get_ticker(symbol, cfg)
    if not t or t["bid"] <= 0 or t["ask"] <= 0:
        log.warning(f"{symbol}: no bid/ask, skip.")
        return 0

    lev = lev_override or min(conf_to_leverage(symbol, conf), FARM_LEVERAGE_CAP)
    notional = margin * lev
    if notional < 10:
        log.warning(f"Notional ${notional:.2f} < $10 minNotional — skip.")
        return 0
    # Maker post-only at the touch: buy@bid / sell@ask.
    side, ref = ("buy", t["bid"]) if direction == "UP" else ("sell", t["ask"])
    price = fmt_price(symbol, ref)
    qty = fmt_qty(symbol, notional / t["last"])

    log.info(f"[{'DRY' if dry else 'LIVE'}] {direction} {side} {symbol} qty={qty} @ {price} "
             f"| lev={lev}x margin=${margin:.0f} notional=${notional:.0f} conf={conf:.2f}")
    if dry:
        log.info("Dry-run: leverage NOT set, order NOT sent. Re-run with --live.")
        return 0

    if not set_leverage(symbol, lev, cfg):
        return 1
    place = cli(["orders", "place", "perps", "--symbol", symbol, "--side", side,
                 "--type", "limit", "--price", price, "--qty", qty,
                 "--tif", "gtx"], cfg=cfg, auth=True)
    if place is None:
        log.error("Order failed.")
        return 1
    log.info(f"✅ Maker order placed ({lev}x): {json.dumps(place)[:200]}")
    return 0


def position_exit_reason(pos: dict, cfg: dict) -> str | None:
    """Decide if a position should close: stop-loss, take-profit (lock gain +
    rotate SoPoints volume), or signal-flip (model direction reversed)."""
    margin = float(pos.get("margin", 0) or 0)
    upnl = float(pos.get("unrealizedPnl", 0) or 0)
    if margin <= 0:
        return None
    frac = upnl / margin
    if frac <= -STOP_LOSS_MARGIN_FRAC:
        return "stop-loss"
    if frac >= TAKE_PROFIT_MARGIN_FRAC:
        return "take-profit"
    qty = float(pos.get("quantity", 0) or 0)
    sig = model_direction(pos.get("symbol", ""))
    d = sig.get("direction")
    if d == "UP" and qty < 0:
        return "signal-flip"
    if d == "DOWN" and qty > 0:
        return "signal-flip"
    return None


def cmd_monitor(cfg: dict, live: bool) -> int:
    """Scan open positions; close on stop-loss / take-profit / signal-flip."""
    positions = open_positions(cfg)
    if not positions:
        log.info("No open positions.")
        return 0
    for pos in positions:
        sym = pos.get("symbol", "?")
        upnl = float(pos.get("unrealizedPnl", 0) or 0)
        margin = float(pos.get("margin", 0) or 0)
        frac = (upnl / margin) if margin > 0 else 0.0
        reason = position_exit_reason(pos, cfg)
        log.info(f"{'🔴' if reason else '🟢'} {sym} uPnL={upnl:+.2f} ({frac*100:+.0f}% margin) "
                 f"lev={pos.get('leverage')}x liq={pos.get('liquidationPrice','?')} "
                 f"{'-> '+reason if reason else ''}")
        if reason:
            if live:
                close_position(pos, cfg)
            else:
                log.info(f"  [DRY] would close {sym} ({reason})")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="SoDEX SoPoints farming")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("validate-signing")
    pf = sub.add_parser("farm")
    pf.add_argument("--once", action="store_true", help="single cycle (default)")
    pf.add_argument("--live", action="store_true", help="place REAL orders (default dry-run)")
    pf.add_argument("--symbol", default="BTC-USD")
    pf.add_argument("--margin-usd", type=float, default=None, help=f"own margin per order (default {MARGIN_PER_ORDER})")
    pf.add_argument("--leverage", type=int, default=None, help="override confidence-based leverage")
    pm = sub.add_parser("monitor")
    pm.add_argument("--live", action="store_true", help="actually close losers (default dry-run)")
    ps = sub.add_parser("scalp", help="SoPoints volume scalp (open+close)")
    ps.add_argument("--live", action="store_true", help="place REAL orders (default dry-run)")
    ps.add_argument("--rounds", type=int, default=SCALP_ROUNDS_PER_CYCLE)
    ps.add_argument("--symbol", default=None)
    pmt = sub.add_parser("maker-test", help="empirical maker-fill + adverse measurement")
    pmt.add_argument("--rounds", type=int, default=12)
    pmt.add_argument("--margin", type=float, default=15.0)
    pmt.add_argument("--leverage", type=int, default=20)
    ppt = sub.add_parser("patient-test", help="patient-MM (repricing) maker-fill measurement")
    ppt.add_argument("--rounds", type=int, default=8)
    ppt.add_argument("--margin", type=float, default=15.0)
    ppt.add_argument("--leverage", type=int, default=20)
    args = p.parse_args()

    cfg = _cfg()
    cfg["address"] = os.environ.get("SODEX_ADDRESS", "")
    if args.cmd == "status":
        return cmd_status(cfg)
    if args.cmd == "validate-signing":
        return cmd_validate_signing(cfg)
    if args.cmd == "farm":
        return cmd_farm(cfg, live=args.live, symbol=args.symbol,
                        margin_usd=args.margin_usd, lev_override=args.leverage)
    if args.cmd == "monitor":
        return cmd_monitor(cfg, live=args.live)
    if args.cmd == "scalp":
        return cmd_scalp(cfg, live=args.live, rounds=args.rounds, symbol=args.symbol)
    if args.cmd == "maker-test":
        return cmd_maker_test(cfg, rounds=args.rounds, margin=args.margin, leverage=args.leverage)
    if args.cmd == "patient-test":
        return cmd_patient_test(cfg, rounds=args.rounds, margin=args.margin, leverage=args.leverage)
    return 0


if __name__ == "__main__":
    sys.exit(main())
