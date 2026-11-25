#!/usr/bin/env python3
"""
ANANTARA SAKTI — Unified Pre-Sentiment data layer (pure, stdlib-only, testable).

Goal: ONE canonical market-data feed for BOTH "pre-sentiment" systems
(crypto LLM forecast + crypto intelligence) with per-symbol source routing and
graceful degradation.

A symbol is resolved through an ordered list of (source, venue_symbol) candidates:
    1. SoDEX perps        (BTC-USD / ETH-USD / SOL-USD only)
    2. Hyperliquid        (perp candleSnapshot — wide coin coverage)
    3. Binance spot       (klines — covers tokenized gold PAXG / XAUT)
If no candidate yields >= MIN_CANDLES candles, the symbol is marked "advisory"
(no live data) and reported as such instead of silently failing.

Design rules (copilot-instructions §7.3):
    - Pure functions (no I/O) are separated from thin async fetchers so the
      decision logic is unit-testable offline with `python3 -m unittest`.
    - No external dependencies beyond httpx (already used project-wide).
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import os

try:
    import httpx  # type: ignore
except ImportError:  # pragma: no cover - tests run pure functions only
    httpx = None  # type: ignore

# ──────────────────────────────────────────────────────────────────────
# WATCHLIST — the canonical 24-asset universe (user-specified, 2026-08-24)
# ──────────────────────────────────────────────────────────────────────
WATCHLIST: list[str] = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "HYPE", "DOGE", "BCH", "ZEC",
    "PENDLE", "ONDO", "TAO", "LINK", "AAVE", "SUI", "TRX", "UNI", "ENA",
    "ADA", "PAXG", "XAUT", "SILVER", "PEPE", "JUP",
]

# Minimum candles required before we trust a source's klines.
MIN_CANDLES = 24

# Candle history to fetch (1h bars). Research: MTF composite needs 1h+4h+1d
# alignment (reduces false signals ~40%), and 1d needs >= 24 bars → 24 days
# → 576 bars minimum; 960 (40 days) gives headroom for gaps/latency.
# Well under Binance's 1000-bar klines cap; single HTTP call either way.
KLINE_LIMIT = 960

# ──────────────────────────────────────────────────────────────────────
# SOURCE ROUTING — per-symbol ordered candidate list.
# SILVER has no known listing on the three venues → advisory-only (empty list).
# ──────────────────────────────────────────────────────────────────────
SOURCE_ROUTING: dict[str, list[tuple[str, str]]] = {
    "BTC":    [("sodex", "BTC-USD"), ("hyperliquid", "BTC"), ("binance_spot", "BTCUSDT")],
    "ETH":    [("sodex", "ETH-USD"), ("hyperliquid", "ETH"), ("binance_spot", "ETHUSDT")],
    "SOL":    [("sodex", "SOL-USD"), ("hyperliquid", "SOL"), ("binance_spot", "SOLUSDT")],
    "BNB":    [("hyperliquid", "BNB"), ("binance_spot", "BNBUSDT")],
    "XRP":    [("hyperliquid", "XRP"), ("binance_spot", "XRPUSDT")],
    "HYPE":   [("hyperliquid", "HYPE")],
    "DOGE":   [("hyperliquid", "DOGE"), ("binance_spot", "DOGEUSDT")],
    "BCH":    [("hyperliquid", "BCH"), ("binance_spot", "BCHUSDT")],
    "ZEC":    [("hyperliquid", "ZEC"), ("binance_spot", "ZECUSDT")],
    "PENDLE": [("hyperliquid", "PENDLE"), ("binance_spot", "PENDLEUSDT")],
    "ONDO":   [("hyperliquid", "ONDO"), ("binance_spot", "ONDOUSDT")],
    "TAO":    [("hyperliquid", "TAO"), ("binance_spot", "TAOUSDT")],
    "LINK":   [("hyperliquid", "LINK"), ("binance_spot", "LINKUSDT")],
    "AAVE":   [("hyperliquid", "AAVE"), ("binance_spot", "AAVEUSDT")],
    "SUI":    [("hyperliquid", "SUI"), ("binance_spot", "SUIUSDT")],
    "TRX":    [("hyperliquid", "TRX"), ("binance_spot", "TRXUSDT")],
    "UNI":    [("hyperliquid", "UNI"), ("binance_spot", "UNIUSDT")],
    "ENA":    [("hyperliquid", "ENA"), ("binance_spot", "ENAUSDT")],
    "ADA":    [("hyperliquid", "ADA"), ("binance_spot", "ADAUSDT")],
    "PAXG":   [("binance_spot", "PAXGUSDT"), ("hyperliquid", "PAXG")],
    "XAUT":   [("binance_spot", "XAUTUSDT")],
    "SILVER": [],
    "PEPE":   [("binance_spot", "PEPEUSDT")],
    "JUP":    [("hyperliquid", "JUP"), ("binance_spot", "JUPUSDT")],
}

# Sources that support a given symbol (for reporting / diagnostics).
ADVISORY_ONLY = {s for s, routes in SOURCE_ROUTING.items() if not routes}

SODEX_SYMBOL_MAP = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD"}

SODEX_PERPS_URL = os.environ.get(
    "SODEX_PERPS_URL", "https://mainnet-gw.sodex.dev/api/v1/perps")
HYPERLIQUID_INFO_URL = os.environ.get(
    "HYPERLIQUID_INFO_URL", "https://api.hyperliquid.xyz/info")
BINANCE_API_BASE = os.environ.get(
    "BINANCE_API_BASE", "https://api.binance.com")

DEFAULT_DATA_DIR = Path(os.environ.get(
    "ANANTARA_DIR", str(Path.home() / "anantara-sakti"))) / "data" / "presentiment"


# ──────────────────────────────────────────────────────────────────────
# PURE HELPERS (unit-testable, no I/O)
# ──────────────────────────────────────────────────────────────────────
@dataclass
class Candle:
    t: float          # epoch seconds (UTC)
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0


@dataclass
class Snapshot:
    symbol: str
    ts: float
    source: str
    venue_symbol: str
    last: float
    chg_1h: float
    chg_6h: float
    chg_24h: float
    ema12: float
    ema48: float
    rsi: float
    macd_hist: float
    adx: float
    plus_di: float
    minus_di: float
    vol_ratio: float
    momentum_score: float
    trend: str
    candles: int
    atr: float = 0.0
    advisory: bool = False
    note: str = ""
    # Multi-timeframe alignment (per-asset). None = not computed (legacy data).
    mtf_composite_v: float | None = None
    mtf_aligned: bool | None = None
    mtf_by_timeframe: dict[str, float] | None = None
    # Fast 1h direction (-1/0/+1) + whether reversal overrule fired (audit 09-04).
    fast_1h: float | None = None
    reversal_override: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_candles(rows: list[dict[str, Any]], *, t_key: str = "t",
                      keys: dict[str, str] | None = None) -> list[Candle]:
    """Normalize heterogeneous candle rows (SoDEX / HL / Binance) → [Candle].

    `keys` maps canonical field → source field name. Defaults assume SoDEX shape.
    """
    m = keys or {"t": "t", "o": "o", "h": "h", "l": "l", "c": "c", "v": "v"}

    def g(row: dict, name: str) -> float:
        return float(row.get(m.get(name, name), 0.0) or 0.0)

    out = [Candle(t=g(r, "t"), o=g(r, "o"), h=g(r, "h"),
                  l=g(r, "l"), c=g(r, "c"), v=g(r, "v")) for r in rows]
    return sorted(out, key=lambda c: c.t)


def ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 50.0 if avg_gain == 0 else 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def macd(closes: list[float]) -> tuple[float, float, float]:
    """Return (macd_line, signal, histogram) — last values."""
    if len(closes) < 26:
        return (0.0, 0.0, 0.0)
    e12 = ema_series(closes, 12)
    e26 = ema_series(closes, 26)
    line = [a - b for a, b in zip(e12, e26)]
    sig = ema_series(line, 9)
    return (line[-1], sig[-1], line[-1] - sig[-1])


def adx(highs: list[float], lows: list[float], closes: list[float],
        period: int = 14) -> tuple[float, float, float]:
    """Wilder ADX → (adx, +DI, -DI)."""
    n = len(closes)
    if n < period * 2 + 1:
        return (0.0, 0.0, 0.0)
    trs, pdms, mdms = [], [], []
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        pdms.append(up if (up > dn and up > 0) else 0.0)
        mdms.append(dn if (dn > up and dn > 0) else 0.0)
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))

    def wilder(vals: list[float], p: int) -> list[float]:
        if len(vals) < p:
            return []
        sm = [sum(vals[:p])]
        for i in range(p, len(vals)):
            sm.append(sm[-1] - sm[-1] / p + vals[i])
        return sm

    atr, pdm_s, mdm_s = wilder(trs, period), wilder(pdms, period), wilder(mdms, period)
    if not atr:
        return (0.0, 0.0, 0.0)
    pdi = mdi = 0.0
    dx = []
    for i in range(len(atr)):
        a = atr[i] or 1e-9
        pdi = 100 * pdm_s[i] / a
        mdi = 100 * mdm_s[i] / a
        s = (pdi + mdi) or 1e-9
        dx.append(100 * abs(pdi - mdi) / s)
    return (sum(dx[-period:]) / min(period, len(dx)), pdi, mdi)


def atr_value(highs: list[float], lows: list[float], closes: list[float],
              period: int = 14) -> float:
    """Wilder ATR (last value) in price units — volatility anchor for TP/SL."""
    n = len(closes)
    if n < period + 1:
        return 0.0
    trs = []
    for i in range(1, n):
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
    if len(trs) < period:
        return 0.0
    atr = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
    return atr


# Reversal overrule thresholds (momentum_composite) — audit 2026-09-04.
REVERSAL_CHG_PCT = 0.30   # 1h move (% of price) large enough to matter
REVERSAL_CAP = 0.25       # cap output magnitude when a live reversal contradicts trend


_REVERSAL_FAST_PCT = 0.15   # ±% chg_1h to call fast_1h = +1/-1


def momentum_composite(candles: list[Candle],
                       _detail: dict | None = None) -> float:
    """Weighted momentum score in [-1, +1] — same concept as _sodex_technicals.

    ADX-gated directional strength + EMA trend + MACD + RSI zone + price momentum.
    Returns 0.0 for insufficient data (→ NEUTRAL downstream).
    """
    if len(candles) < MIN_CANDLES:
        return 0.0
    closes = [k.c for k in candles]
    highs = [k.h for k in candles]
    lows = [k.l for k in candles]
    last = closes[-1]
    c1 = closes[-2] if len(closes) >= 2 else closes[0]
    c24 = closes[-25] if len(closes) >= 25 else closes[0]
    c6 = closes[-7] if len(closes) >= 7 else closes[0]
    chg_1h = (last - c1) / c1 * 100 if c1 else 0.0
    chg_6h = (last - c6) / c6 * 100 if c6 else 0.0
    chg_24h = (last - c24) / c24 * 100 if c24 else 0.0
    e12 = ema(closes, 12)
    e48 = ema(closes, min(48, len(closes)))
    r = rsi(closes, 14)
    _l, _s, hist = macd(closes)
    a, pdi, mdi = adx(highs, lows, closes, 14)

    ch = 0.0
    ch += 0.5 if chg_6h > 0.3 else (-0.5 if chg_6h < -0.3 else 0.0)
    ch += 0.5 if chg_24h > 0.5 else (-0.5 if chg_24h < -0.5 else 0.0)
    adx_val = (1.0 if pdi > mdi else -1.0) if a >= 20 else 0.0
    # Fast 1h momentum: catches direction flips sooner than EMA48/MACD lag.
    # Low weight so it aids reversal detection without dominating slow trend.
    fast_1h = 1.0 if chg_1h > _REVERSAL_FAST_PCT\
        else (-1.0 if chg_1h < -_REVERSAL_FAST_PCT else 0.0)
    comps = [
        (1.0 if e12 > e48 else -1.0, 1.0),          # EMA trend
        (1.0 if _l > _s else -1.0, 1.5),            # MACD
        (adx_val, 1.5),                             # ADX-gated direction
        (1.0 if r > 55 else (-1.0 if r < 45 else 0.0), 1.0),  # RSI zone
        (max(-1.0, min(1.0, ch * 2)), 1.0),         # price momentum
        (fast_1h, 0.75),                            # fast 1h flip detector
    ]
    num = sum(v * w for v, w in comps)
    den = sum(w for _, w in comps)
    raw = num / den if den else 0.0

    # ── Reversal overrule (audit 2026-09-04, user Q: ZEC long lost) ───────
    # A slow-trend composite (EMA48/MACD/ADX riding a long 24h move) can stay
    # strongly LONG/SHORT while the asset has ALREADY reversed this hour.
    # Measured case: ZEC composite +0.78 (LONG, conf 0.79) while chg_1h was
    # -0.998% — slow trend (24h +19%) overwhelmed the 0.75-weight fast_1h.
    # Goal: refuse HIGH confidence against a live fee-scale reversal. General
    # rule (not ZEC-specific): if the fresh 1h move is a real move AND opposes
    # the composite direction, CAP magnitude below the LONG/SHORT threshold so
    # the report goes TUNGGU instead of a confident call the wrong way. We do
    # NOT flip the sign (a false SHORT is itself risky — SHORT has measured
    # anti-edge per falsification history).
    fast_dir = 1 if fast_1h > 0 else (-1 if fast_1h < 0 else 0)
    comp_dir = 1 if raw > 0 else (-1 if raw < 0 else 0)
    overridden = (fast_dir != 0 and comp_dir != 0 and fast_dir != comp_dir
                  and abs(chg_1h) >= REVERSAL_CHG_PCT and abs(raw) >= 0.15)
    if overridden:
        raw = max(-REVERSAL_CAP, min(REVERSAL_CAP, raw * 0.35))
    if _detail is not None and isinstance(_detail, dict):
        _detail.update({"fast_1h": fast_1h, "chg_1h": chg_1h,
                        "reversal_override": bool(overridden),
                        "raw": round(raw, 4)})
    return round(max(-1.0, min(1.0, raw)), 2)


# ──────────────────────────────────────────────────────────────────────
# MULTI-TIMEFRAME AGGREGATION — per-asset MTF alignment.
# Research basis: multi-TF alignment reduces false signals ~40% vs single TF
# (same principle as the BTC-level MTF feed in intelligence.py W_MTF=0.28).
# Longer timeframes carry more weight; full alignment boosts, conflict dampens.
# ──────────────────────────────────────────────────────────────────────
MTF_WEIGHTS: dict[str, float] = {"1h": 0.20, "4h": 0.35, "1d": 0.45}


def mtf_composite(scores_by_tf: dict[str, float]) -> dict[str, Any]:
    """Aggregate per-timeframe momentum scores into one aligned composite.

    Args:
        scores_by_tf: {"1h": s, "4h": s, "1d": s} each in [-1, +1].

    Returns {composite, by_timeframe, aligned, n_tfs}:
        composite ∈ [-1, +1] weighted mean;
        aligned=True only when ALL present TFs share one strict sign.
    """
    present = {tf: max(-1.0, min(1.0, float(s))) for tf, s in scores_by_tf.items()
               if tf in MTF_WEIGHTS and s is not None}
    if not present:
        return {"composite": 0.0, "by_timeframe": {}, "aligned": False, "n_tfs": 0}
    total_w = sum(MTF_WEIGHTS[tf] for tf in present)
    comp = sum(s * MTF_WEIGHTS[tf] for tf, s in present.items()) / total_w
    signs = {(1 if s > 0 else (-1 if s < 0 else 0)) for s in present.values()}
    return {
        "composite": round(comp, 3),
        "by_timeframe": {tf: round(s, 3) for tf, s in present.items()},
        # aligned requires >= 2 timeframes: a single TF trivially shares its
        # own sign — claiming "aligned" there is a false confidence signal
        # (v3.1 audit: with 72-bar history only 1h evaluated → ✅MTF lied).
        "aligned": len(present) >= 2 and len(signs) == 1 and 0 not in signs,
        "n_tfs": len(present),
    }


def resample_candles(candles: list[Candle], factor: int) -> list[Candle]:
    """Resample 1h candles to a higher timeframe (factor = hours per bar).

    factor=4 → 4h bars; factor=24 → 1d bars. Keeps the LAST close of each
    bucket, MAX high, MIN low, SUM volume. Pure & deterministic.
    """
    if factor <= 1 or not candles:
        return candles
    out: list[Candle] = []
    for i in range(0, len(candles), factor):
        chunk = candles[i:i + factor]
        if not chunk:
            continue
        out.append(Candle(
            t=chunk[0].t,
            o=chunk[0].o,
            h=max(k.h for k in chunk),
            l=min(k.l for k in chunk),
            c=chunk[-1].c,
            v=sum(k.v for k in chunk),
        ))
    return out


def mtf_scores_from_candles(candles_1h: list[Candle]) -> dict[str, float]:
    """Compute per-TF momentum scores from a single 1h candle series.

    Uses resampling (no extra HTTP calls → faster than per-TF fetches):
      1h → raw series · 4h → factor 4 · 1d → factor 24.
    Returns {} when even the 1h series is too thin.
    """
    if len(candles_1h) < MIN_CANDLES:
        return {}
    scores: dict[str, float] = {}
    for tf, factor in (("1h", 1), ("4h", 4), ("1d", 24)):
        series = resample_candles(candles_1h, factor)
        if len(series) >= MIN_CANDLES:
            scores[tf] = momentum_composite(series)
    return scores


def compute_snapshot(symbol: str, candles: list[Candle], source: str,
                     venue_symbol: str) -> Snapshot:
    """Build a Snapshot from normalized candles (pure)."""
    n = len(candles)
    if n < MIN_CANDLES:
        return Snapshot(symbol=symbol, ts=datetime.now(timezone.utc).timestamp(),
                        source=source, venue_symbol=venue_symbol,
                        last=0.0, chg_1h=0.0, chg_6h=0.0, chg_24h=0.0,
                        ema12=0.0, ema48=0.0, rsi=50.0, macd_hist=0.0,
                        adx=0.0, plus_di=0.0, minus_di=0.0, vol_ratio=1.0,
                        momentum_score=0.0, trend="flat", candles=n,
                        advisory=True, note="insufficient candles")
    closes = [k.c for k in candles]
    vols = [k.v for k in candles]
    last = closes[-1]
    c1 = closes[-2] if n >= 2 else closes[0]
    c6 = closes[-7] if n >= 7 else closes[0]
    c24 = closes[-25] if n >= 25 else closes[0]
    _det = {}
    score = momentum_composite(candles, _detail=_det)
    vol_recent = sum(vols[-6:]) / 6
    vol_avg = sum(vols) / n
    _l, _s, hist = macd(closes)
    a, pdi, mdi = adx([k.h for k in candles], [k.l for k in candles], closes, 14)
    atr = atr_value([k.h for k in candles], [k.l for k in candles], closes, 14)
    mtf = mtf_composite(mtf_scores_from_candles(candles))
    return Snapshot(
        symbol=symbol, ts=datetime.now(timezone.utc).timestamp(),
        source=source, venue_symbol=venue_symbol, last=round(last, 8),
        chg_1h=round((last - c1) / c1 * 100, 3) if c1 else 0.0,
        chg_6h=round((last - c6) / c6 * 100, 3) if c6 else 0.0,
        chg_24h=round((last - c24) / c24 * 100, 3) if c24 else 0.0,
        ema12=round(ema(closes, 12), 8), ema48=round(ema(closes, min(48, n)), 8),
        rsi=round(rsi(closes, 14), 2), macd_hist=round(hist, 8),
        adx=round(a, 2), plus_di=round(pdi, 2), minus_di=round(mdi, 2),
        vol_ratio=round(vol_recent / vol_avg, 3) if vol_avg > 0 else 1.0,
        momentum_score=score, trend="bull" if score > 0 else ("bear" if score < 0 else "flat"),
        candles=n,
        atr=round(atr, 8),
        fast_1h=_det.get("fast_1h"), reversal_override=bool(_det.get("reversal_override")),
        mtf_composite_v=mtf["composite"], mtf_aligned=mtf["aligned"],
        mtf_by_timeframe=mtf["by_timeframe"],
    )


def routing_for(symbol: str) -> list[tuple[str, str]]:
    return SOURCE_ROUTING.get(symbol.upper(), [])


# ──────────────────────────────────────────────────────────────────────
# MARKET REGIME CLASSIFICATION (pure) — feeds intelligence + forecast
# guards (CHAOS penalty / TRENDING bonus / regime conf-caps).
#
# Method (regime-switching practice):
#   ratio = mean TR(last 14 bars) / mean TR(all earlier bars)
#         → recent-vol vs prior-baseline (no Wilder smoothing artifacts:
#           a sustained vol shift converges the smoothed ATR toward the
#           baseline and hides the shock; raw means expose it)
#   ADX(14)                              → directional-strength confirmator
#   CHAOS    : ratio >= 2.0  (docstring contract: "ATR 2x+ baseline")
#   TRENDING : ratio >= 1.3 AND ADX >= 25 ("elevated vol, price > SMA"
#              in intelligence.py — ADX is the robust directional form)
#   RANGING  : everything else
# Fail-safe direction: unflagged CHAOS costs a late guard, false CHAOS
# nukes good signals → thresholds deliberately conservative.
# ──────────────────────────────────────────────────────────────────────
REGIME_CHAOS_ATR_MULT = 2.0
REGIME_TREND_ATR_MULT = 1.3
REGIME_TREND_ADX_MIN  = 25.0


def market_regime(candles: list[Candle]) -> str:
    """Classify TRENDING / RANGING / CHAOS from 1h candles (pure).

    Returns "RANGING" on insufficient/degenerate data (fail-neutral).
    """
    n = len(candles)
    if n < MIN_CANDLES * 2:
        return "RANGING"
    closes = [k.c for k in candles]
    highs = [k.h for k in candles]
    lows = [k.l for k in candles]
    trs: list[float] = []
    for i in range(1, n):
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
    if len(trs) < MIN_CANDLES:
        return "RANGING"
    recent, prior = trs[-14:], trs[:-14]
    baseline = sum(prior) / len(prior)
    if baseline <= 0:
        return "RANGING"
    ratio = (sum(recent) / len(recent)) / baseline
    if ratio >= REGIME_CHAOS_ATR_MULT:
        return "CHAOS"
    if ratio >= REGIME_TREND_ATR_MULT:
        a, _pdi, _mdi = adx(highs, lows, closes, 14)
        if a >= REGIME_TREND_ADX_MIN:
            return "TRENDING"
    return "RANGING"


def retention(rows: list[dict[str, Any]], max_rows: int = 5000) -> list[dict[str, Any]]:
    """Keep only the most recent `max_rows` rows (append-only JSONL pruning)."""
    return rows[-max_rows:]


# ──────────────────────────────────────────────────────────────────────
# ASYNC I/O (thin fetchers — not exercised by offline unit tests)
# ──────────────────────────────────────────────────────────────────────
async def fetch_sodex_klines(symbol: str, limit: int = 72) -> list[dict[str, Any]]:
    if not httpx:
        return []
    venue = SODEX_SYMBOL_MAP.get(symbol.upper())
    if not venue:
        return []
    try:
        async with httpx.AsyncClient(timeout=12,
                                     headers={"Accept": "application/json"}) as c:
            r = await c.get(f"{SODEX_PERPS_URL}/markets/{venue}/klines",
                            params={"interval": "1h", "limit": limit})
            raw = (r.json() or {}).get("data", []) or []
            return sorted(raw, key=lambda k: k.get("t", 0))
    except Exception:
        return []


async def fetch_hyperliquid_klines(symbol: str, limit: int = 72) -> list[dict[str, Any]]:
    if not httpx:
        return []
    import time as _t
    step_ms = 3600_000
    end_ms = int(_t.time() * 1000)
    start_ms = end_ms - limit * step_ms
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(HYPERLIQUID_INFO_URL, json={
                "type": "candleSnapshot",
                "req": {"coin": symbol.upper(), "interval": "1h",
                        "startTime": start_ms, "endTime": end_ms},
            })
            rows = r.json()
        return [{"t": row["t"] / 1000, "o": row["o"], "h": row["h"],
                 "l": row["l"], "c": row["c"], "v": row["v"]}
                for row in sorted(rows, key=lambda x: x["t"])]
    except Exception:
        return []


async def fetch_binance_klines(symbol: str, limit: int = 72) -> list[dict[str, Any]]:
    if not httpx:
        return []
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{BINANCE_API_BASE}/api/v3/klines",
                            params={"symbol": symbol.upper(), "interval": "1h",
                                    "limit": limit})
            rows = r.json()
        return [{"t": row[0] / 1000, "o": row[1], "h": row[2],
                 "l": row[3], "c": row[4], "v": row[5]} for row in rows]
    except Exception:
        return []


_FETCHERS = {
    "sodex": fetch_sodex_klines,
    "hyperliquid": fetch_hyperliquid_klines,
    "binance_spot": fetch_binance_klines,
}


async def fetch_unified_klines(symbol: str, limit: int = 72) -> tuple[list[Candle], str, str]:
    """Resolve a symbol through SOURCE_ROUTING → (candles, source, venue_symbol).

    Returns ([], "", "") when no source yields >= MIN_CANDLES candles.
    """
    for source, venue_symbol in routing_for(symbol):
        fetcher = _FETCHERS.get(source)
        if not fetcher:
            continue
        rows = await fetcher(venue_symbol, limit=limit)
        candles = normalize_candles(rows)
        if len(candles) >= MIN_CANDLES:
            return candles, source, venue_symbol
    return [], "", ""


# ──────────────────────────────────────────────────────────────────────
# SNAPSHOT STORAGE (atomic writes, retention)
# ──────────────────────────────────────────────────────────────────────
def write_snapshot_latest(snaps: list[Snapshot], data_dir: Path | None = None) -> Path:
    data_dir = data_dir or DEFAULT_DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    fp = data_dir / "snapshot_latest.json"
    payload = {s.symbol: s.to_dict() for s in snaps}
    tmp = fp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(fp)
    return fp


def append_snapshot_history(snaps: list[Snapshot], data_dir: Path | None = None,
                            max_rows: int = 5000) -> Path:
    data_dir = data_dir or DEFAULT_DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    fp = data_dir / "snapshots.jsonl"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    day_fp = data_dir / f"snapshots_{ts}.jsonl"
    line = json.dumps({"ts_epoch": datetime.now(timezone.utc).timestamp(),
                       "snapshots": [s.to_dict() for s in snaps]}) + "\n"
    day_fp.open("a").write(line)
    # Prune daily file in memory only when it exists and is oversized.
    try:
        lines = day_fp.read_text().splitlines()
        if len(lines) > max_rows:
            day_fp.write_text("\n".join(lines[-max_rows:]) + "\n")
    except Exception:
        pass
    return day_fp
