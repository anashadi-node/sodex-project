#!/usr/bin/env python3
"""
ANANTARA SAKTI — Market Regime Detector

Classifies the *overall* market state (proxied by BTC) into TRENDING / RANGING /
CHAOS, so the Pre-Gain/Loser scanner can adapt: raise the bar (and shrink size)
when the whole market is in a liquidation-cascade panic, rather than firing
LONG signals into a market-wide dump.

Why this exists (honest framing):
  This is a RISK GATE, not an edge. It does not predict direction. It only
  recognises "the tape is violent right now → demand stronger confirmation".
  Inspired by adaptive-scanner designs (classify state, change thresholds), but
  kept deliberately simple and rule-based — no fitted parameters to overfit.

Pure functions (deterministic, unit-tested). The only stateful/IO part is
`fetch_btc_candles`, which is isolated so the logic can be tested offline.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

# ── Calibratable thresholds (starting points; not fitted) ──
CHAOS_ATR_RATIO = 2.0     # recent vol >= 2x baseline …
CHAOS_VOL_Z     = 2.5     # … and volume z-score very high → CHAOS
TREND_MOMENTUM  = 0.03    # |price vs SMA20| > 3% …
TREND_ATR_RATIO = 1.2     # … with elevated vol → TRENDING
CHAOS_MULTIPLIER = 0.70   # penalise scores when market is chaotic
CHAOS_MIN_SCORE  = 70     # in CHAOS, only act on very strong signals

ATR_FAST = 14             # candles for "recent" ATR
ATR_BASE = 50             # candles for baseline ATR
SMA_LEN  = 20             # candles for momentum SMA / volume baseline


@dataclass
class RegimeResult:
    regime: str            # "TRENDING" | "RANGING" | "CHAOS"
    multiplier: float      # overall score multiplier (applied to both directions)
    min_score_floor: int   # minimum score to emit an actionable signal
    atr_ratio: float
    vol_z: float
    momentum: float
    reason: str
    atr_ratio_prev: float = 1.0   # ATR ratio 1h earlier (ATR compression detection)
    long_multiplier: float  = 1.0  # applied to LONG scores only (bear phase = <1.0)
    short_multiplier: float = 1.0  # applied to SHORT scores only (bear phase = >1.0)
    # Empirical basis (360d HL data, Jun 2025–May 2026):
    #   BULL phase (BTC mom >+3%): altcoin daily up-rate 62–72%
    #   BEAR phase (BTC mom <-3%): altcoin daily up-rate 27–44%  ← ~50% drop
    # → LONG signals significantly less reliable in bear phase; SHORT more reliable.


def _true_ranges(candles: list[dict]) -> list[float]:
    """Wilder true range series from OHLC candles (oldest→newest)."""
    trs = []
    for i in range(1, len(candles)):
        h, l = candles[i]["high"], candles[i]["low"]
        pc = candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return trs


def compute_features(candles: list[dict]) -> tuple[float, float, float]:
    """Return (atr_ratio, vol_z, momentum) from BTC candles (oldest→newest).

    Each candle: {open, high, low, close, volume}. Returns neutral features
    (1.0, 0.0, 0.0) if there is not enough data to judge.
    """
    if len(candles) < ATR_BASE + 1:
        return 1.0, 0.0, 0.0

    trs = _true_ranges(candles)
    atr_now  = statistics.fmean(trs[-ATR_FAST:])
    atr_base = statistics.fmean(trs[-ATR_BASE:])
    atr_ratio = atr_now / atr_base if atr_base > 0 else 1.0
    # Cap atr_ratio at 10× to prevent extreme values (e.g., near-zero baseline from
    # a dead-price period) from triggering spurious CHAOS classification.
    atr_ratio = min(atr_ratio, 10.0)

    vols  = [c["volume"] for c in candles[-ATR_BASE:]]
    vmean = statistics.fmean(vols)
    vstd  = statistics.pstdev(vols) if len(vols) > 1 else 0.0
    # Minimum std = 0.1% of mean to prevent near-division-by-zero when volume is
    # extremely stable — without this, any tiny deviation yields an enormous z-score.
    if vmean > 0:
        vstd = max(vstd, vmean * 0.001)
    vol_z = (vols[-1] - vmean) / vstd if vstd > 0 else 0.0

    closes = [c["close"] for c in candles]
    sma = statistics.fmean(closes[-SMA_LEN:])
    momentum = (closes[-1] - sma) / sma if sma > 0 else 0.0

    return atr_ratio, vol_z, momentum


def _directional_multipliers(
    momentum: float, base_mult: float, btc_bounce: float = 0.0
) -> tuple[float, float]:
    """Compute long/short multipliers based on BTC momentum direction.

    Empirical basis (360d HL data Jun 2025–May 2026):
      BEAR (mom < -3%): altcoin long win-rate 27–44% vs 62–72% in BULL.
      Apply 25% penalty to longs in bear, 25% penalty to shorts in bull.
      CHAOS already penalises both — use its multiplier as base.

    btc_bounce: short-term BTC return (last 6h vs 6h earlier).
      Research (Jun 2026): Asia session WR=16.6% on Jun-06 because BTC bounced +2%.
      When btc_bounce > +1.5%, penalise SHORT scores by additional 15% (total: -30%).
    """
    # SMA20 long-term momentum
    if momentum <= -TREND_MOMENTUM:     # bear tilt: punish longs, reward shorts
        lm, sm = round(base_mult * 0.75, 3), round(base_mult * 1.10, 3)
    elif momentum >= TREND_MOMENTUM:    # bull tilt: reward longs, punish shorts
        lm, sm = round(base_mult * 1.10, 3), round(base_mult * 0.85, 3)
    else:
        lm, sm = base_mult, base_mult

    # Short-term bounce gate: SHORT penalty when BTC bouncing
    # Data (Jun 2026 OHLC backtest):
    #   BTC bounce > +3%: Asia WR dropped 80%→16.6% → use strong penalty 40%
    #   BTC bounce +1.5%–3%: moderate risk   → 25% penalty
    #   BTC bounce <-1.5%: BTC falling → slight SHORT bonus +5%
    if btc_bounce >= 0.03:              # strong bounce +3%+: most SHORTs will lose
        sm = round(sm * 0.60, 3)        # 40% penalty: score 75→45 (filtered), 80→48 (filtered)
    elif btc_bounce >= 0.015:           # moderate bounce +1.5%–3%
        sm = round(sm * 0.75, 3)        # 25% penalty: score 75→56 (filtered), 83→62 (borderline)
    elif btc_bounce <= -0.015:          # BTC falling → reward SHORTs
        sm = round(sm * 1.05, 3)

    return lm, sm


def classify_regime(
    atr_ratio: float, vol_z: float, momentum: float, btc_bounce: float = 0.0
) -> RegimeResult:
    """Map features → regime + scanner adjustments (pure)."""
    bounce_tag = (f" bounce={btc_bounce*100:+.1f}%" if abs(btc_bounce) >= 0.01 else "")
    if atr_ratio >= CHAOS_ATR_RATIO and vol_z >= CHAOS_VOL_Z:
        lm, sm = _directional_multipliers(momentum, CHAOS_MULTIPLIER, btc_bounce)
        return RegimeResult(
            "CHAOS", CHAOS_MULTIPLIER, CHAOS_MIN_SCORE,
            atr_ratio, vol_z, momentum,
            f"vol {atr_ratio:.1f}x baseline + volume z {vol_z:.1f} → market-wide "
            f"violence; demand ≥{CHAOS_MIN_SCORE} & shrink size{bounce_tag}",
            long_multiplier=lm, short_multiplier=sm,
        )
    if abs(momentum) > TREND_MOMENTUM and atr_ratio >= TREND_ATR_RATIO:
        dirn = "up" if momentum > 0 else "down"
        lm, sm = _directional_multipliers(momentum, 1.0, btc_bounce)
        return RegimeResult(
            "TRENDING", 1.0, 0, atr_ratio, vol_z, momentum,
            f"BTC trending {dirn} ({momentum*100:+.1f}% vs SMA{SMA_LEN}){bounce_tag}; "
            f"long_x{lm} short_x{sm}",
            long_multiplier=lm, short_multiplier=sm,
        )
    lm, sm = _directional_multipliers(momentum, 1.0, btc_bounce)
    return RegimeResult(
        "RANGING", 1.0, 0, atr_ratio, vol_z, momentum,
        f"BTC range-bound ({momentum*100:+.1f}% vs SMA{SMA_LEN}){bounce_tag}; "
        f"long_x{lm} short_x{sm}",
        long_multiplier=lm, short_multiplier=sm,
    )


def detect_from_candles(candles: list[dict]) -> RegimeResult:
    """Convenience: features → regime in one call, with atr_ratio_prev and btc_bounce."""
    # Short-term bounce: last 6 candles (≈6h for 1h, 24h for 4h interval)
    btc_bounce = 0.0
    if len(candles) >= 7:
        close_now  = candles[-1]["close"]
        close_6ago = candles[-7]["close"]
        btc_bounce = (close_now - close_6ago) / close_6ago if close_6ago > 0 else 0.0

    result = classify_regime(*compute_features(candles), btc_bounce=btc_bounce)
    # Compute prev ATR ratio using candles minus last 4 (≈4h ago) for ATR-compression detection
    if len(candles) > ATR_BASE + 5:
        prev_atr, _, _ = compute_features(candles[:-4])
        result.atr_ratio_prev = prev_atr
    return result


# ── IO boundary (not unit-tested; mirrors scanner's fetch style) ──

def fetch_btc_candles(hl_api: str = "https://api.hyperliquid.xyz",
                      interval: str = "1h", lookback: int = 120) -> list[dict]:
    """Fetch recent BTC candles from Hyperliquid for regime detection."""
    import time
    import httpx
    end = int(time.time() * 1000)
    start = end - lookback * 3600 * 1000
    r = httpx.post(f"{hl_api}/info", timeout=12, json={
        "type": "candleSnapshot",
        "req": {"coin": "BTC", "interval": interval, "startTime": start, "endTime": end},
    })
    rows = r.json()
    return [{
        "open": float(c["o"]), "high": float(c["h"]), "low": float(c["l"]),
        "close": float(c["c"]), "volume": float(c["v"]),
    } for c in rows]


def fetch_regime() -> RegimeResult:
    """Live regime from Hyperliquid BTC candles (falls back to RANGING)."""
    try:
        return detect_from_candles(fetch_btc_candles())
    except Exception:
        return RegimeResult("RANGING", 1.0, 0, 1.0, 0.0, 0.0,
                            "regime fetch failed → neutral default")


_RET24_CACHE: tuple[float, "float | None"] = (0.0, None)


def btc_return_24h(ttl: float = 300.0) -> "float | None":
    """Return BTC 24 jam dalam persen (close terakhir vs 24 candle 1h lalu).

    Dipakai gate arah SHORT Pre-Gain: arm SHORT hanya punya edge saat BTC
    naik > +1% (mean-reversion setelah over-extended). Cache 5 menit supaya
    decide() bisa memanggil per-sinyal tanpa request berulang.
    None = data tak tersedia → pemanggil wajib fail-closed.
    """
    global _RET24_CACHE
    import time as _t
    now = _t.time()
    if now - _RET24_CACHE[0] < ttl:
        return _RET24_CACHE[1]
    val = None
    try:
        candles = fetch_btc_candles(interval="1h", lookback=30)
        if len(candles) >= 25:
            ref, last = candles[-25]["close"], candles[-1]["close"]
            if ref > 0:
                val = (last - ref) / ref * 100.0
    except Exception:
        val = None
    _RET24_CACHE = (now, val)
    return val


if __name__ == "__main__":
    res = fetch_regime()
    print(f"Market regime: {res.regime}")
    print(f"  atr_ratio={res.atr_ratio:.2f}  vol_z={res.vol_z:.2f}  "
          f"momentum={res.momentum*100:+.2f}%")
    print(f"  multiplier={res.multiplier}  min_score_floor={res.min_score_floor}")
    print(f"  {res.reason}")
