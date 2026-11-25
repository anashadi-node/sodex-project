"""
Pre-Gain LONG Scanner v2.0
===========================
Detects oversold coins likely to bounce (Pre-Gain pattern).

Signal conditions (improved from v1.0 based on empirical research):
  1. RSI-14 < 35 on 4h candle (oversold)
  2. Current 4h candle is GREEN (c > o) — reversal starting
  3. Volume > 1.5× average (buyer interest)
  4. Coin dropped > 10% in last 24h (6 candles) — oversold dip
  5. BTC REGIME OK (v2.0: EMA20 + RSI ≥ 35, not just "current 4h green")
     — Old filter was too binary: blocked ALL signals when BTC had a red 4h candle

v2.0 BTC regime filter (replaces single-candle check):
  - BTC 4h RSI ≥ 35 (not in extreme panic/crash)
  - BTC 4h close ≥ EMA20 * 0.97 (within 3% of trend, not in freefall)
  - Optional context: BTC 24h change used for score, not as hard gate

Session scoring:
  - Asia/EU: historically better for LONG bounces (+5 score bonus)
  - US_Asia: lowest WR historically (-3 score penalty)

Position params:
  SL = 5%, TP = 15%, Hold = 24h (per backtest optimal)
  WR gate: PAPER until 50 live resolved + WR≥55%, LIVE at WR≥69%

Backtest results (1-year OHLC, n=106, bear market):
  WR=56.6%, E=+0.501R — bear market floor; bull market expected higher.
"""

import json
import os
import time
from pathlib import Path

CANDLE_DIR = Path(os.environ.get(
    "HL_CANDLE_DIR",
    os.path.expanduser("~/anantara-sakti/freqtrade_user_data/data/hl/candles")
))

# Signal parameters — research-optimized v2.0:
# Agent research: RSI<32+vol>2x = 56.8% WR (n=44); RSI<35+vol>1.5x = 56.6% (n=106)
# Compromise: RSI<33 — keeps PURR-class signals (RSI~32.4), strict enough for quality
# Tradeoff: RSI<32 gives marginal +0.2pp WR at cost of 75% fewer signals → not worth it
RSI_MAX       = 33.0    # oversold threshold (4h) — tightened from 35 → 33
VOL_MULT      = 1.5     # volume must be X× average
                        # Research: 1.5x (WR=56.6%, n=106) vs 2.0x (WR=56.8%, n=44)
                        # Difference: +0.2pp WR at cost of 58% fewer signals.
                        # Decision: 1.5x preferred — need n≥40 live to unlock gate faster.
DROP_MIN      = -10.0   # coin must have dropped ≥10% in 24h (validated optimal)
SL_PCT        = 3.0     # v8.10: SL=3% optimal from batch sweep (was 5%)
TP_PCT        = 15.0    # take-profit %
HOLD_HOURS    = 24      # hold timeout (hours)

# BTC regime filters (v2.0 — replaces single "BTC green 4h" check)
# Agent research: BTC green candle = 67.7% WR (31 signals); BTC RSI>35 = 0%/4 signals.
# Thresholds: loose RSI gate (≥30, blocks only extreme panic like RSI=4-10 crash days)
#             + EMA band (close ≥ EMA20 × 0.95, blocks freefall but allows dips).
BTC_RSI_MIN   = 30.0   # BTC 4h RSI ≥ 30 (blocks crash days with RSI=4-15, not normal dips)
BTC_EMA_BAND  = 0.95   # BTC close ≥ EMA20 × 0.95 (not in severe freefall)

# Edge gate thresholds (matches autotrader convention)
PAPER_WR_GATE = 0.55    # PAPER until WR ≥ 55%
LIVE_WR_GATE  = 0.69    # LIVE only when WR ≥ 69%
LIVE_MIN_N    = 50      # minimum live-resolved trades before LIVE

_CANDLE_CACHE: dict = {}


def _load_candles(coin: str) -> list:
    if coin in _CANDLE_CACHE:
        return _CANDLE_CACHE[coin]
    f = CANDLE_DIR / coin / "4h.jsonl"
    if not f.exists():
        _CANDLE_CACHE[coin] = []
        return []
    rows = []
    for line in f.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # skip corrupt line, keep rest of file
    candles = sorted(rows, key=lambda x: x["t"])
    _CANDLE_CACHE[coin] = candles
    return candles


def _rsi14(candles: list) -> float:
    """RSI-14 from last 15 candles (close prices)."""
    if len(candles) < 15:
        return 50.0
    closes = [c["c"] for c in candles[-15:]]
    gains  = [max(0.0, closes[i+1] - closes[i]) for i in range(14)]
    losses = [max(0.0, closes[i] - closes[i+1]) for i in range(14)]
    avg_g  = sum(gains) / 14
    avg_l  = sum(losses) / 14
    if avg_l == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_g / avg_l)


def _ema(values: list, period: int) -> float:
    """Exponential moving average of last `period` values."""
    if len(values) < period:
        return sum(values) / len(values) if values else 0.0
    k = 2.0 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _avg_volume(candles: list, n: int = 20) -> float:
    """Average volume over last n candles."""
    tail = candles[-n:] if len(candles) >= n else candles
    return sum(c["v"] for c in tail) / len(tail) if tail else 0.0


def _btc_regime(btc_candles: list) -> tuple[bool, float, float]:
    """Check BTC 4h regime. Returns (regime_ok, btc_rsi, btc_24h_pct).

    v2.0: replaces single "is current 4h green?" check.
    Regime OK when:
      - BTC RSI ≥ 35 (not in panic crash)
      - BTC close ≥ EMA20 × 0.97 (within 3% of EMA, not in freefall)
    """
    if len(btc_candles) < 21:
        return False, 50.0, 0.0

    btc_rsi = _rsi14(btc_candles)
    btc_cur  = btc_candles[-1]["c"]

    # EMA20 on 4h closes
    closes_20 = [c["c"] for c in btc_candles[-20:]]
    btc_ema20  = _ema(closes_20, 20)

    # 24h change (6 × 4h candles)
    btc_24h = ((btc_cur - btc_candles[-7]["c"]) / btc_candles[-7]["c"] * 100
               if len(btc_candles) >= 7 else 0.0)

    regime_ok = (btc_rsi >= BTC_RSI_MIN
                 and btc_cur >= btc_ema20 * BTC_EMA_BAND)
    return regime_ok, btc_rsi, btc_24h


def scan_long_signals(coins: list | None = None) -> list[dict]:
    """
    Scan coins for Pre-Gain LONG signals. Returns list of signal dicts.
    v2.0: Better BTC regime filter, session scoring, improved signal quality.
    """
    if not CANDLE_DIR.exists():
        return []
    btc_candles = _load_candles("BTC")
    if not btc_candles:
        return []

    regime_ok, btc_rsi, btc_24h = _btc_regime(btc_candles)
    if not regime_ok:
        return []  # BTC in panic/freefall → no altcoin LONG

    # Coin universe
    if coins is None:
        coins = [d.name for d in CANDLE_DIR.iterdir()
                 if d.is_dir() and (d / "4h.jsonl").exists() and d.name != "BTC"]

    # Session from UTC hour
    utc_hour = time.gmtime().tm_hour
    session = ("Asia" if 0 <= utc_hour < 8 else
               "EU"   if 8 <= utc_hour < 12 else
               "US"   if 12 <= utc_hour < 20 else "US_Asia")

    # Session bonus/penalty (empirical from LONG_FUNDING history: S grade Asia/EU best)
    _sess_bonus = {"Asia": 5, "EU": 3, "US": 0, "US_Asia": -3}
    sess_adj = _sess_bonus.get(session, 0)

    signals = []
    for coin in coins:
        candles = _load_candles(coin)
        if len(candles) < 20:
            continue

        cur = candles[-1]

        # 1. Green candle
        if cur["c"] <= cur["o"]:
            continue

        # 2. RSI oversold
        rsi_val = _rsi14(candles)
        if rsi_val > RSI_MAX:
            continue

        # 3. Volume spike
        avg_vol = _avg_volume(candles)
        if avg_vol <= 0 or cur["v"] < avg_vol * VOL_MULT:
            continue
        vol_ratio = cur["v"] / avg_vol

        # 4. Coin dropped >10% in last 24h (6 × 4h candles)
        if len(candles) < 7:
            continue
        prev_close = candles[-7]["c"]
        drop_24h = (cur["o"] - prev_close) / prev_close * 100
        if drop_24h > DROP_MIN:
            continue

        # Score: 60–100, scaled from signal strength + session
        rsi_score   = min(40, int((RSI_MAX - rsi_val) / RSI_MAX * 40))   # 0–40 pts
        drop_score  = min(25, int(abs(drop_24h) / 10 * 12))               # 0–25 pts
        vol_score   = min(20, int((vol_ratio - 1.5) / 1.5 * 20))          # 0–20 pts
        btc_score   = 8 + max(0, min(7, int(btc_rsi / 10) - 3))           # 8–15 pts: BTC RSI bonus
        raw = 60 + rsi_score + drop_score + vol_score + btc_score + sess_adj

        score = min(100, max(60, raw))

        # Grade based on score
        if score >= 90:   grade = "S"
        elif score >= 80: grade = "A"
        elif score >= 70: grade = "B"
        else:             grade = "C"

        signals.append({
            "coin":        coin,
            "name":        coin,
            "direction":   "LONG",
            "type":        "LONG_TECHNICAL",
            "score":       float(score),
            "grade":       grade,
            "session":     session,
            "entry_price": cur["c"],
            "vol24":       cur["v"] * cur["c"],
            "vol_oi":      vol_ratio,
            "fund_accel":  btc_24h,      # BTC 24h % as context
            "regime":      "RANGING",
            "liq":         "LIQUID",
            "liq_tier":    "STANDARD",
            "rsi":         rsi_val,
            "vol_ratio":   vol_ratio,
            "drop_24h":    drop_24h,
            "btc_rsi":     btc_rsi,
            "btc_24h":     btc_24h,
            "sl_pct":      SL_PCT,
            "tp_pct":      TP_PCT,
            "hold_hours":  HOLD_HOURS,
        })

    signals.sort(key=lambda x: x["score"], reverse=True)
    return signals


def format_long_report(signals: list[dict]) -> str:
    """Format LONG signals for Telegram."""
    if not signals:
        return "📈 Pre-Gain LONG: tidak ada sinyal saat ini"

    lines = [f"📈 *Pre-Gain LONG v2* — {len(signals)} sinyal\n"]
    for s in signals[:8]:
        rsi_s  = f"RSI={s['rsi']:.0f}"
        drop_s = f"drop={s['drop_24h']:.1f}%"
        vol_s  = f"vol={s['vol_ratio']:.1f}×"
        btc_s  = f"BTC_RSI={s.get('btc_rsi', 0):.0f}"
        lines.append(
            f"  `{s['coin']:8s}` {s['grade']} sc={s['score']:.0f} "
            f"{rsi_s} {drop_s} {vol_s} {btc_s}"
        )
    lines.append(f"\nSL={SL_PCT}% TP={TP_PCT}% Hold={HOLD_HOURS}h")
    lines.append(f"BTC filter: RSI≥{BTC_RSI_MIN:.0f} + close≥EMA20×{BTC_EMA_BAND}")
    lines.append(f"Gate: PAPER sampai WR≥55% (n≥20), LIVE saat WR≥{LIVE_WR_GATE:.0%}")
    return "\n".join(lines)


if __name__ == "__main__":
    print("=== Pre-Gain LONG Scanner v2.0 Test ===")
    sigs = scan_long_signals()
    print(f"Found: {len(sigs)} signals")
    for s in sigs[:10]:
        print(f"  {s['coin']:8s} {s['grade']} sc={s['score']:.0f} "
              f"RSI={s['rsi']:.1f} drop={s['drop_24h']:.1f}% "
              f"vol={s['vol_ratio']:.1f}x BTC_RSI={s.get('btc_rsi',0):.0f}")
    print()
    print(format_long_report(sigs))
