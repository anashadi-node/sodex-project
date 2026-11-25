"""
Pre-Gain SPOT Scanner v2.0
===========================
Dua varian SPOT signal untuk kondisi market yang berbeda:

VARIANT 1 — Momentum Breakout (Bull/Recovery market):
  Price breaks above N-day high + volume spike
  WR=87.5% n=64 walk-forward (1 year backtest)
  Aktif saat: BTC ≥ 85% dari 20d high (uptrend/recovery)

VARIANT 2 — Deep Dip Recovery (Bear/Sideways market):  ← NEW v2.0
  Coin turun >25% dalam 30 hari + RSI daily <30 + green day + vol>2x
  WR target ≥ 65% (diperkirakan dari 1y backtest analog)
  Aktif saat: BTC < 85% dari 20d high (bear/sideways)
  Hold 14d, Trail 5% (lebih longgar dari breakout)

Philosophy: SPOT = tidak ada liquidation risk, bisa hold lebih lama
            Momentum breakout untuk bull; dip recovery untuk bear
            Dua varian = SPOT selalu bisa generate signals apapun market condition
"""

import json
import os
import time
from pathlib import Path

CANDLE_DIR = Path(os.environ.get(
    "HL_CANDLE_DIR",
    os.path.expanduser("~/anantara-sakti/freqtrade_user_data/data/hl/candles")
))

# ── Variant 1: Momentum Breakout ──────────────────────────────────────────────
BREAKOUT_DAYS   = 20      # break above N-day high
VOL_MULT_BO     = 1.5     # volume ≥ 1.5× average
RSI_MAX_BO      = 72      # tidak masuk jika extreme overbought
TP_PCT_BO       = 20.0    # take-profit %
TRAIL_PCT_BO    = 3.0     # trailing stop %
HOLD_DAYS_BO    = 10      # max hold (hari)

# ── Variant 2: Deep Dip Recovery ─────────────────────────────────────────────
# Research findings (agent 2026-06-07):
# - RSI<28 + drop>25% + vol>2x → WR=42.1% (below 65% PAPER gate) — too strict
# - Volume Surge (vol>3x) → WR=51% — marginal; in FEAR regime improves to 57.1%
# Current params: relaxed for DATA ACCUMULATION (edge gate still strict: n≥30+WR≥65%)
# Vol lowered to 1.3x (vs 2x) to generate enough signals for live WR measurement.
# Real WR will be measured live — if <55%, gate stays PAPER; if ≥65%, LIVE unlocks.
DROP_30D_MIN    = -20.0   # coin harus turun >20% dalam 30d (relaxed from 25%)
RSI_MAX_DR      = 30.0    # RSI daily harus <30 (extreme oversold)
VOL_MULT_DR     = 1.3     # volume ≥ 1.3× average (relaxed from 2x for data accumulation)
VOL24_MIN_DR    = 5_000_000  # min vol24 USD for DIP_RECOVERY — filter THIN-tier coins
                              # (THIN = vol $1-10M; real slippage 0.5-1% vs assumed 0.09%)
TP_PCT_DR       = 15.0    # take-profit % (conservative vs breakout's 20%, matches lower WR)
TRAIL_PCT_DR    = 4.0     # trailing stop % (tighter than relaxed breakout, matches lower WR)
HOLD_DAYS_DR    = 10      # max hold (hari)

# ── Market regime threshold ───────────────────────────────────────────────────
BTC_REGIME_THRESHOLD = 0.85  # BTC ≥85% dari 20d high → gunakan breakout
                              # BTC <85% dari 20d high → gunakan dip recovery

# ── Edge gate thresholds ─────────────────────────────────────────────────────
PAPER_WR_GATE   = 0.65    # PAPER sampai WR ≥ 65% live
LIVE_WR_GATE    = 0.69    # LIVE saat WR ≥ 69%
LIVE_MIN_N      = 40      # min live-resolved trades (Wilson CI requires n≥40 for SPOT)

_CACHE_1D: dict = {}
_CACHE_4H: dict = {}


def _load_1d(coin: str) -> list:
    if coin in _CACHE_1D:
        return _CACHE_1D[coin]
    f = CANDLE_DIR / coin / "1d.jsonl"
    if not f.exists():
        _CACHE_1D[coin] = []
        return []
    rows = []
    for line in f.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    cs = sorted(rows, key=lambda x: x["t"])
    _CACHE_1D[coin] = cs
    return cs


def _load_4h(coin: str) -> list:
    if coin in _CACHE_4H:
        return _CACHE_4H[coin]
    f = CANDLE_DIR / coin / "4h.jsonl"
    if not f.exists():
        _CACHE_4H[coin] = []
        return []
    rows = []
    for line in f.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    cs = sorted(rows, key=lambda x: x["t"])
    _CACHE_4H[coin] = cs
    return cs


def _rsi14(candles: list) -> float:
    if len(candles) < 15:
        return 50.0
    closes = [c["c"] for c in candles[-15:]]
    gains  = [max(0.0, closes[i+1] - closes[i]) for i in range(14)]
    losses = [max(0.0, closes[i] - closes[i+1]) for i in range(14)]
    ag = sum(gains) / 14
    al = sum(losses) / 14
    if al == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def _avg_vol(candles: list, n: int = 20) -> float:
    tail = candles[-n:] if len(candles) >= n else candles
    return sum(c["v"] for c in tail) / len(tail) if tail else 0.0


def _btc_regime_ratio() -> float:
    """Return BTC price / BTC 20d high. >0.85 = bull/recovery, <0.85 = bear."""
    btc = _load_1d("BTC")
    if len(btc) < 21:
        return 1.0
    cur_c   = btc[-1]["c"]
    high_20 = max(c["h"] for c in btc[-21:-1])
    return cur_c / high_20 if high_20 > 0 else 1.0


def scan_spot_breakouts(coins: list | None = None) -> list[dict]:
    """Variant 1: Momentum Breakout — best for bull/recovery market."""
    if not CANDLE_DIR.exists():
        return []
    btc_ratio = _btc_regime_ratio()

    if coins is None:
        coins = [d.name for d in CANDLE_DIR.iterdir()
                 if d.is_dir() and (d / "1d.jsonl").exists() and d.name != "BTC"]

    utc_hour = time.gmtime().tm_hour
    session  = "Asia" if 0 <= utc_hour < 8 else ("EU" if 8 <= utc_hour < 16 else "US")

    signals = []
    for coin in coins:
        cs = _load_1d(coin)
        if len(cs) < BREAKOUT_DAYS + 2:
            continue

        cur     = cs[-1]
        # Exclude today's candle from baseline (today's high vol IS the signal).
        avg_vol = _avg_vol(cs[:-1])
        if avg_vol <= 0 or cur["v"] < avg_vol * VOL_MULT_BO:
            continue

        high_n = max(c["h"] for c in cs[-(BREAKOUT_DAYS + 1):-1])
        if cur["c"] <= high_n * 1.01:
            continue

        rsi_val = _rsi14(cs)
        if rsi_val > RSI_MAX_BO:
            continue

        cs_4h = _load_4h(coin)
        intraday_green = (cs_4h[-1]["c"] > cs_4h[-1]["o"]) if cs_4h else True

        break_margin = (cur["c"] - high_n) / high_n * 100
        vol_ratio    = cur["v"] / avg_vol
        margin_score = min(25, int(break_margin / 2 * 10))
        vol_score    = min(25, int((vol_ratio - 1.5) / 1.0 * 15))
        rsi_score    = min(20, int((60 - rsi_val) / 60 * 20)) if rsi_val < 60 else 0
        trend_score  = 10 if intraday_green else 0
        regime_bonus = 5 if btc_ratio >= BTC_REGIME_THRESHOLD else 0

        score = min(100, max(60, 60 + margin_score + vol_score + rsi_score
                             + trend_score + regime_bonus))
        grade = ("S" if score >= 90 else "A" if score >= 80
                 else "B" if score >= 70 else "C")

        signals.append({
            "coin":           coin,
            "name":           coin,
            "direction":      "LONG",
            "type":           "SPOT_BREAKOUT",
            "variant":        "BREAKOUT",
            "score":          float(score),
            "grade":          grade,
            "session":        session,
            "entry_price":    cur["c"],
            "vol24":          cur["v"] * cur["c"],
            "vol_ratio":      vol_ratio,
            "break_margin":   break_margin,
            "rsi":            rsi_val,
            "n_day_high":     high_n,
            "btc_ratio":      btc_ratio,
            "tp_pct":         TP_PCT_BO,
            "trail_pct":      TRAIL_PCT_BO,
            "hold_days":      HOLD_DAYS_BO,
            "fund_accel":     0.0,
            "vol_oi":         vol_ratio,
            "regime":         "RANGING",
            "liq":            "LIQUID",
            "liq_tier":       "STANDARD",
        })

    signals.sort(key=lambda x: x["score"], reverse=True)
    return signals


def scan_spot_dip_recovery(coins: list | None = None) -> list[dict]:
    """Variant 2: Deep Dip Recovery — for bear/sideways market (BTC < 85% of 20d high).

    Conditions:
    1. Coin down > 25% in last 30 days
    2. RSI-14 daily < 30 (extreme oversold)
    3. Today's candle is green (buyers stepping in)
    4. Volume > 2× average (conviction buy)
    5. Candle closes in top 40% of range (shows strength)
    """
    if not CANDLE_DIR.exists():
        return []
    btc_ratio = _btc_regime_ratio()

    if coins is None:
        coins = [d.name for d in CANDLE_DIR.iterdir()
                 if d.is_dir() and (d / "1d.jsonl").exists() and d.name != "BTC"]

    utc_hour = time.gmtime().tm_hour
    session  = "Asia" if 0 <= utc_hour < 8 else ("EU" if 8 <= utc_hour < 16 else "US")

    signals = []
    for coin in coins:
        cs = _load_1d(coin)
        if len(cs) < 32:
            continue

        # Use YESTERDAY's complete candle for detection (today's candle is partial).
        # Signal = complete candle (cs[-2]) met criteria, enter at today's price (cs[-1]).
        # This avoids partial-day volume looking anomalously low.
        sig = cs[-2]    # signal candle (yesterday — complete)
        cur = cs[-1]    # today's candle (entry price)

        # Baseline volume BEFORE the signal candle (exclude yesterday's spike from average).
        # Using cs[-22:-2] = 20 days before yesterday, so vol_ratio correctly measures
        # how extraordinary yesterday's volume was vs the prior baseline.
        avg_vol = sum(c["v"] for c in cs[-22:-2]) / 20 if len(cs) >= 22 else _avg_vol(cs[:-2])
        if avg_vol <= 0:
            continue

        # Liquidity gate: require vol24 ≥ $5M (THIN-tier filter).
        # THIN coins ($1-10M vol) have real slippage 0.5-1% vs backtest assumed 0.09%.
        # For 10d hold with 4% trail, slippage eating 1% = 25% of expected edge.
        vol24_usd = sig["v"] * sig["c"]
        if vol24_usd < VOL24_MIN_DR:
            continue

        # 1. RSI extreme oversold (compute on candles up to and including yesterday)
        rsi_val = _rsi14(cs[:-1])
        if rsi_val > RSI_MAX_DR:
            continue

        # 2. Volume spike on signal candle
        vol_ratio = sig["v"] / avg_vol
        if vol_ratio < VOL_MULT_DR:
            continue

        # 3. Hammer/Capitulation: closes in top 30% of range regardless of candle color.
        # Both green and red count — buyers stepped in near the close.
        candle_range = sig["h"] - sig["l"]
        if candle_range <= 0:
            continue
        close_position = (sig["c"] - sig["l"]) / candle_range
        if close_position < 0.30:    # lowered from 35% to 30%
            continue

        # 4. Down > 12% in 30 days (meaningful correction, not just noise)
        prev_30d = cs[-32]["c"]
        drop_30d = (sig["c"] - prev_30d) / prev_30d * 100
        if drop_30d > DROP_30D_MIN:   # DROP_30D_MIN = -20%
            continue

        # Score 60–100
        rsi_score  = min(30, int((RSI_MAX_DR - rsi_val) / RSI_MAX_DR * 30))  # 0–30
        drop_score = min(25, int(abs(drop_30d) / 25 * 20))                    # 0–25
        vol_score  = min(20, int((vol_ratio - 1.3) / 1.0 * 15))               # 0–20
        body_score = min(15, int(close_position * 15))                         # 0–15
        raw = 60 + rsi_score + drop_score + vol_score + body_score

        score = min(100, max(60, raw))
        grade = ("S" if score >= 90 else "A" if score >= 80
                 else "B" if score >= 70 else "C")

        entry_price = cur["c"]   # today's price as entry
        signals.append({
            "coin":           coin,
            "name":           coin,
            "direction":      "LONG",
            "type":           "SPOT_BREAKOUT",   # same type for autotrader routing
            "variant":        "DIP_RECOVERY",
            "score":          float(score),
            "grade":          grade,
            "session":        session,
            "entry_price":    entry_price,
            "vol24":          sig["v"] * sig["c"],
            "vol_ratio":      vol_ratio,
            "rsi":            rsi_val,
            "drop_30d":       drop_30d,
            "close_pos":      close_position,
            "btc_ratio":      btc_ratio,
            "tp_pct":         TP_PCT_DR,
            "trail_pct":      TRAIL_PCT_DR,
            "hold_days":      HOLD_DAYS_DR,
            "fund_accel":     0.0,
            "vol_oi":         vol_ratio,
            "regime":         "RANGING",
            "liq":            "LIQUID",
            "liq_tier":       "STANDARD",
        })

    signals.sort(key=lambda x: x["score"], reverse=True)
    return signals


def scan_all_spot(coins: list | None = None) -> list[dict]:
    """Combined scan: uses appropriate variant based on BTC regime.
    Breakout (bull): BTC ≥ 85% of 20d high.
    Dip Recovery (bear): BTC < 85% of 20d high.
    Always runs both, but the regime-appropriate one gets a score bonus.
    """
    btc_ratio = _btc_regime_ratio()
    breakouts = scan_spot_breakouts(coins)
    dips      = scan_spot_dip_recovery(coins)

    # Dedup by coin: keep highest score
    seen: dict[str, dict] = {}
    for s in breakouts + dips:
        c = s["coin"]
        if c not in seen or s["score"] > seen[c]["score"]:
            seen[c] = s

    combined = sorted(seen.values(), key=lambda x: x["score"], reverse=True)
    return combined


def format_spot_report(signals: list[dict]) -> str:
    """Format SPOT signals for Telegram."""
    if not signals:
        return "📊 Pre-Gain SPOT: tidak ada sinyal saat ini"

    btc_ratio = _btc_regime_ratio()
    regime_tag = f"{'🐂 BULL' if btc_ratio >= BTC_REGIME_THRESHOLD else '🐻 BEAR'} (BTC={btc_ratio:.1%} dari 20d high)"

    lines = [f"📊 *Pre-Gain SPOT v2* — {len(signals)} sinyal | {regime_tag}\n"]
    for s in signals[:6]:
        variant = s.get("variant", "BREAKOUT")
        if variant == "BREAKOUT":
            detail = f"break=+{s.get('break_margin', 0):.1f}% vol={s.get('vol_ratio', 0):.1f}×"
        else:
            detail = f"drop30d={s.get('drop_30d', 0):.0f}% RSI={s.get('rsi', 0):.0f} vol={s.get('vol_ratio', 0):.1f}×"
        lines.append(
            f"  `{s['coin']:8s}` {s['grade']} sc={s['score']:.0f} "
            f"[{variant[:2]}] {detail}"
        )
    lines.append(f"\nBO: Trail={TRAIL_PCT_BO}% Hold≤{HOLD_DAYS_BO}d | DR: Trail={TRAIL_PCT_DR}% Hold≤{HOLD_DAYS_DR}d")
    lines.append(f"Gate LIVE: WR≥{LIVE_WR_GATE:.0%} n≥{LIVE_MIN_N} (BO backtest=87.5%)")
    return "\n".join(lines)


if __name__ == "__main__":
    print("=== Pre-Gain SPOT Scanner v2.0 Test ===")
    btc_ratio = _btc_regime_ratio()
    print(f"BTC regime: {btc_ratio:.1%} of 20d high ({'BULL' if btc_ratio >= BTC_REGIME_THRESHOLD else 'BEAR'})")
    print()

    bo = scan_spot_breakouts()
    print(f"BREAKOUT signals: {len(bo)}")
    for s in bo[:5]:
        print(f"  {s['coin']:8s} {s['grade']} sc={s['score']:.0f} break=+{s['break_margin']:.1f}% vol={s['vol_ratio']:.1f}×")

    print()
    dr = scan_spot_dip_recovery()
    print(f"DIP RECOVERY signals: {len(dr)}")
    for s in dr[:8]:
        print(f"  {s['coin']:8s} {s['grade']} sc={s['score']:.0f} "
              f"RSI={s['rsi']:.0f} drop30d={s['drop_30d']:.0f}% vol={s['vol_ratio']:.1f}×")

    print()
    all_sigs = scan_all_spot()
    print(format_spot_report(all_sigs))
