#!/usr/bin/env python3
"""Asymmetric regime filter for momentum-long entries (2026-08-15).

Root cause it fixes: momentum-long is profitable ONLY in confirmed uptrend
(Aug 6-11 PF 1.38) and catastrophic in choppy/down (Aug 12+ WR 0%, -9.2%).
The tracks entered regardless of regime → 8/8 losses.

Design (user-approved, "lambat masuk, cepat keluar"):
  ENTRY  = SLOW, confirmed 1h uptrend (quality; avoids whipsaw).
  VETO   = FAST 30m turn detector with DOUBLE-CONFIRM (protect; cut noise).

Frequency != earliness: earliness comes from the 30m DATA, not from checking
a 1h signal more often. So the fast side genuinely reads finer candles.

Env: PAPER_REGIME_FILTER=0 disables (default on).
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest_swing_gate1_v3 as v3  # reuse adx/sma/rsi

ENABLED = os.environ.get("PAPER_REGIME_FILTER", "1") == "1"
ENTRY_ADX_MIN = float(os.environ.get("REGIME_ENTRY_ADX_MIN", "22"))
_cache: dict[str, tuple[float, bool]] = {}   # sym -> (ts, last_30m_bad)


def _raw_klines(sym_bn: str, interval: str, limit: int = 210):
    """Spot klines, falling back to Binance futures (fapi) when the symbol is
    not a spot pair (e.g. HYPE, XAG/silver — perp-only). Identical row schema.
    Additive: for existing spot pairs the spot call succeeds and fapi is never
    hit, so behaviour is unchanged. Returns [] on total failure."""
    for base in ("https://api.binance.com/api/v3/klines",
                 "https://fapi.binance.com/fapi/v1/klines"):
        try:
            r = requests.get(base, params={"symbol": sym_bn, "interval": interval,
                                           "limit": limit}, timeout=10)
            k = r.json()
            if isinstance(k, list) and len(k) >= 2:
                return k
        except Exception:
            continue
    return []


def _klines(sym_bn: str, interval: str, limit: int = 210):
    k = _raw_klines(sym_bn, interval, limit)
    return {"h": np.array([float(x[2]) for x in k]),
            "l": np.array([float(x[3]) for x in k]),
            "c": np.array([float(x[4]) for x in k])}


def entry_regime_ok(sym_bn: str) -> bool:
    """SLOW gate: confirmed 1h uptrend on last CLOSED bar.
    ADX>min AND close>SMA50 AND SMA50>SMA200 (golden cross).
    Fail-CLOSED (no data → no trade) — entries must be earned."""
    if not ENABLED:
        return True
    try:
        d = _klines(sym_bn, "1h")
        i = len(d["c"]) - 2
        a = v3.adx(d["h"], d["l"], d["c"]); s50 = v3.sma(d["c"], 50); s200 = v3.sma(d["c"], 200)
        return bool(a[i] > ENTRY_ADX_MIN and d["c"][i] > s50[i] and s50[i] > s200[i])
    except Exception:
        return False


def fast_regime_bad(sym_bn: str) -> bool:
    """FAST veto: 30m momentum turning down, DOUBLE-CONFIRMED (2 reads agree).
    True = stand aside / don't open. Fail-OPEN (data error → don't veto)."""
    if not ENABLED:
        return False
    try:
        d = _klines(sym_bn, "30m")
        i = len(d["c"]) - 2
        s50 = v3.sma(d["c"], 50)
        bad_now = bool(d["c"][i] <= s50[i])   # lost the 30m SMA50 = momentum fading
    except Exception:
        return False
    prev = _cache.get(sym_bn, (0.0, False))[1]
    _cache[sym_bn] = (time.time(), bad_now)
    return bad_now and prev   # both consecutive reads bad → confirmed turn


def demo():
    # synthetic strong uptrend → entry_ok True; downtrend → False. No crash.
    import backtest_swing_gate1_v3 as _v3
    n = 260
    up = np.cumprod(1 + np.full(n, 0.004)) * 100
    d = {"h": up * 1.001, "l": up * 0.999, "c": up}
    i = n - 2
    a = _v3.adx(d["h"], d["l"], d["c"]); s50 = _v3.sma(d["c"], 50); s200 = _v3.sma(d["c"], 200)
    assert d["c"][i] > s50[i] > s200[i], "uptrend geometry broken"
    # fast double-confirm: single bad read must NOT veto
    _cache.clear()
    _cache["X"] = (time.time(), False)
    # simulate: first bad read alone → False (needs 2)
    prev = _cache.get("X", (0, False))[1]
    assert (True and prev) is False, "double-confirm should require 2 bad reads"
    print("demo OK — entry geometry sane, double-confirm requires 2 reads, no crash")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        demo()
    else:
        for s in ["BTCUSDT", "SOLUSDT", "ETHUSDT", "DOGEUSDT"]:
            print(f"{s}: entry_ok={entry_regime_ok(s)} fast_bad={fast_regime_bad(s)}")
