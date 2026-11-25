#!/usr/bin/env python3
"""Pre-Gain → SoDEX Bridge — Bearish Directional Signal Feeder.

Maps Hyperliquid assets scanned by Pre-Gain system to SoDEX tradable perps pairs.
Only activates in BEAR market regime (Intel + Pre-Sentiment + trend confirmation).
Feeds SHORT signals to E2Dir for directional volume generation.

Architecture:
  Pre-Gain scan → filter BEAR regime → Top Loser rank → SoDEX mapping → E2Dir SHORT

Safety: read-only scan, paper-first, signal tracker audit, max 3 concurrent.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

# ── HL → SoDEX perps mapping (verified 2026-06-22, 78 SoDEX pairs) ──
HL_TO_SODEX: dict[str, str] = {
    # Crypto (13 pairs)
    'BTC': 'BTC-USD', 'ETH': 'ETH-USD', 'SOL': 'SOL-USD',
    'BNB': 'BNB-USD', 'BCH': 'BCH-USD', 'ZEC': 'ZEC-USD', 'XMR': 'XMR-USD',
    'HYPE': 'HYPE-USD', 'ENA': 'ENA-USD', 'TON': 'TON-USD', 'XPL': 'XPL-USD',
    'DOGE': 'DOGE-USD', 'ADA': 'ADA-USD',
    # Tech Stocks (22 pairs)
    'AAPL': 'AAPL-USD', 'AMZN': 'AMZN-USD', 'MSFT': 'MSFT-USD',
    'GOOGL': 'GOOGL-USD', 'META': 'META-USD', 'NVDA': 'NVDA-USD',
    'AMD': 'AMD-USD', 'INTC': 'INTC-USD', 'MU': 'MU-USD',
    'TSLA': 'TSLA-USD', 'PLTR': 'PLTR-USD', 'ORCL': 'ORCL-USD',
    'HOOD': 'HOOD-USD', 'COIN': 'COIN-USD', 'MSTR': 'MSTR-USD',
    'SAMSUNG': 'SAMSUNG-USD', 'TSM': 'TSM-USD', 'SKHX': 'SKHX-USD',
    'SNDK': 'SNDK-USD', 'SPCX': 'SPCX-USD', 'EWY': 'EWY-USD',
    'CRCL': 'CRCL-USD',
    # Indices/Commodities (3 pairs)
    'USTECH100': 'USTECH100-USD', 'US500': 'US500-USD', 'XAUT': 'XAUT-USD',
}
REVERSE_MAP: dict[str, str] = {v: k for k, v in HL_TO_SODEX.items()}

# ── Configurable thresholds ──
DEFAULT_MIN_SCORE = 65       # Pre-Gain score minimum for SHORT signal
DEFAULT_MAX_SIGNALS = 3      # Max concurrent E2Dir positions
DEFAULT_SCAN_MAX_AGE_MIN = 120  # Max age of Pre-Gain scan data (minutes)


def get_bearish_signals(
    min_score: int = DEFAULT_MIN_SCORE,
    max_signals: int = DEFAULT_MAX_SIGNALS,
    max_age_min: float = DEFAULT_SCAN_MAX_AGE_MIN,
) -> list[dict]:
    """Fetch Pre-Gain Top Loser signals for BEAR market SoDEX SHORT.

    Returns list of dicts: {pair, base, score, chg_pct, vol24, mark, regime}
    Empty list jika: BULL/NEUTRAL regime, scan stale, no signals above threshold.
    """
    try:
        from anantara import pregain_scan as _ps
    except ImportError:
        logging.warning("pregain_bridge: pregain_scan not importable")
        return []

    # 1. Run Pre-Gain scan (uses 5-min cache)
    try:
        longs, shorts, regime = _ps.run_scan(
            min_score=min_score, show_long=False, show_short=True,
            log=False, verbose=False,
        )
    except Exception as e:
        logging.warning("pregain_bridge: scan failed: %s", e)
        return []

    # 2. Gate: Intel + Pre-Sentiment regime check (BEAR only)
    intel_regime = _get_intel_regime()
    trend_regime = str(regime.regime) if hasattr(regime, 'regime') else 'NEUTRAL'

    # BULL/NEUTRAL → E1 handles it, E2 stays off
    if intel_regime not in ('BEAR', None) and trend_regime != 'BEAR':
        logging.debug("pregain_bridge: regime=%s intel=%s — E2 off (BULL/NEUTRAL)",
                      trend_regime, intel_regime)
        return []

    # 3. Map Top Losers → SoDEX pairs, rank by score
    signals: list[dict] = []
    for asset in shorts:
        name = str(asset.get('name', '')).upper()
        sodex_pair = HL_TO_SODEX.get(name)
        if not sodex_pair:
            continue

        signals.append({
            'pair': sodex_pair,
            'base': name,
            'score': int(asset.get('score', 0)),
            'chg_pct': float(asset.get('chg', 0)),
            'vol24': float(asset.get('vol24', 0)),
            'mark': float(asset.get('mark', 0)),
            'regime': trend_regime,
            'intel': intel_regime or 'N/A',
            'ts': time.time(),
        })

    # Sort by score descending, take top N
    signals.sort(key=lambda s: s['score'], reverse=True)
    return signals[:max_signals]


def get_bullish_signals(
    min_score: int = DEFAULT_MIN_SCORE,
    max_signals: int = DEFAULT_MAX_SIGNALS,
    max_age_min: float = DEFAULT_SCAN_MAX_AGE_MIN,
) -> list[dict]:
    """Fetch Pre-Gain Top GAINER signals for BULL market SoDEX LONG (riser).

    Simetris dengan get_bearish_signals: Top Loser→SHORT (dropper) di BEAR,
    Top Gainer→LONG (riser) di BULL. Memenuhi permintaan: deteksi dini aset yang
    akan NAIK tinggi → perps LONG. Empty list jika BEAR/NEUTRAL atau no signal.
    Returns: [{pair, base, score, chg_pct, vol24, mark, regime, intel, ts, side='long'}]
    """
    try:
        from anantara import pregain_scan as _ps
    except ImportError:
        logging.warning("pregain_bridge: pregain_scan not importable")
        return []
    try:
        longs, shorts, regime = _ps.run_scan(
            min_score=min_score, show_long=True, show_short=False,
            log=False, verbose=False,
        )
    except Exception as e:
        logging.warning("pregain_bridge: long scan failed: %s", e)
        return []
    intel = _get_intel_regime()
    trend_regime = str(regime.regime) if hasattr(regime, 'regime') else 'NEUTRAL'
    # BEAR/NEUTRAL → no LONG (riser butuh BULL konfirmasi, hindari long di pasar turun)
    if intel not in ('BULL', None) and trend_regime != 'BULL':
        logging.debug("pregain_bridge: regime=%s intel=%s — no LONG (bukan BULL)",
                      trend_regime, intel)
        return []
    signals: list[dict] = []
    for asset in longs:
        name = str(asset.get('name', '')).upper()
        sodex_pair = HL_TO_SODEX.get(name)
        if not sodex_pair:
            continue
        signals.append({
            'pair': sodex_pair, 'base': name, 'side': 'long',
            'score': int(asset.get('score', 0)),
            'chg_pct': float(asset.get('chg', 0)),
            'vol24': float(asset.get('vol24', 0)),
            'mark': float(asset.get('mark', 0)),
            'regime': trend_regime, 'intel': intel or 'N/A', 'ts': time.time(),
        })
    signals.sort(key=lambda s: s['score'], reverse=True)
    return signals[:max_signals]


def get_directional_signals(min_score: int = DEFAULT_MIN_SCORE,
                            max_signals: int = DEFAULT_MAX_SIGNALS) -> list[dict]:
    """Gabungan regime-aware: BEAR→Top Loser SHORT, BULL→Top Gainer LONG, NEUTRAL→[].
    Satu pintu untuk perps directional (long riser / short dropper) dari Pre-Gain."""
    bear = get_bearish_signals(min_score, max_signals)
    if bear:
        for s in bear:
            s.setdefault('side', 'short')
        return bear
    return get_bullish_signals(min_score, max_signals)


def _get_intel_regime() -> Optional[str]:
    """Read Intel + Pre-Sentiment regime (LEADING). None = stale/unavailable."""
    try:
        from anantara.sodex_twin_engine import read_intel_signal, intel_regime
        sig = read_intel_signal()
        return intel_regime(sig)
    except Exception:
        return None


def get_sodex_pair(hl_asset: str) -> Optional[str]:
    """Convert HL asset name to SoDEX pair. Returns None if not mapped."""
    return HL_TO_SODEX.get(hl_asset.upper())


def get_hl_asset(sodex_pair: str) -> Optional[str]:
    """Convert SoDEX pair to HL asset name. Returns None if not mapped."""
    return REVERSE_MAP.get(sodex_pair)


# ── Self-test ──
if __name__ == "__main__":
    print("=== Pre-Gain Bridge Self-Test ===\n")
    print(f"Mapped pairs: {len(HL_TO_SODEX)}")
    print(f"  Crypto:  {sum(1 for v in HL_TO_SODEX.values() if v.split('-')[0] in ('BTC','ETH','SOL','BNB','BCH','ZEC','XMR','HYPE','ENA','TON','XPL','DOGE','ADA'))}")
    print(f"  Stocks:  {sum(1 for v in HL_TO_SODEX.values() if v.split('-')[0] in ('AAPL','AMZN','MSFT','GOOGL','META','NVDA','AMD','INTC','MU','TSLA','PLTR','ORCL','HOOD','COIN','MSTR','SAMSUNG','TSM','SKHX','SNDK','SPCX','EWY','CRCL'))}")
    print(f"  Indices: {sum(1 for v in HL_TO_SODEX.values() if v.split('-')[0] in ('USTECH100','US500','XAUT'))}")

    print("\n=== Signal fetch (dry-run) ===")
    signals = get_bearish_signals(min_score=50, max_signals=3)
    if signals:
        for s in signals:
            print(f"  {s['pair']:<18s} score={s['score']} chg={s['chg_pct']:+.1f}% regime={s['regime']}")
    else:
        print("  No signals (regime not BEAR, or scan unavailable)")
