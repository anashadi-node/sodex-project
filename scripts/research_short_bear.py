#!/usr/bin/env python3
"""Answer the bear-market gap: does SHORT-in-bear add tradeable edge? (READ-ONLY)

The current strategy is LONG-only (blocks when BTC<MA200). In bear that = zero
trades for months. This tests the symmetric mirror: SHORT when bear-momentum,
same REAL-wide geometry, intrabar fills. Measures BOTH edge AND trade frequency
(the "we never trade" concern).

Configs on BTC/ETH/SOL, 17 months:
  LONG-bull   : v3 long momentum (baseline)
  SHORT-bear  : mirror — ADX>25, c<SMA50<SMA200, RSI40-60, vol>1.1, 24h down, bounce
  COMBINED    : long in bull + short in bear (always-on regime switch)

REAL-wide: TP 4% / SL 2% (price), stop from t=0, 3×, intrabar.

Run:  python3 scripts/research_short_bear.py
      python3 scripts/research_short_bear.py demo
"""
from __future__ import annotations
import sys
import numpy as np
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
import backtest_swing_gate1_v3 as v3

SYMS = ["BTC", "ETH", "SOL"]
TP, SL = 0.04, 0.02
LEV = 3
COOLDOWN = 24
WARM = 200
MAKER_FEE = 0.00024
SPREAD = {"BTC": 0.00013, "ETH": 0.00020, "SOL": 0.00035}
MONTHS = 17.0


def short_signal(d, i):
    """Mirror of v3 long momentum, for bear regime."""
    if i < WARM:
        return False
    c, h, l, v = d["c"], d["h"], d["l"], d["v"]
    a = v3.adx(h, l, c); s50 = v3.sma(c, 50); s200 = v3.sma(c, 200)
    # bear regime: strong trend, downward stack
    if not (a[i] > 25 and c[i] < s50[i] and s50[i] < s200[i]):
        return False
    rv = v3.rsi(c); s24 = v3.sma(c, 24); va = v3.sma(v, 24)
    r24 = v3.rr(c, 24); r1 = v3.rr(c, 1)
    vr = v[i] / va[i] if va[i] > 0 else 1.0
    chk = 0
    if c[i] < s24[i]: chk += 1
    if 40 < rv[i] < 60: chk += 1
    if vr > 1.1: chk += 1
    if i >= 24 and not np.isnan(r24[i]) and r24[i] < -0.012: chk += 1   # 24h downtrend
    if i >= 1 and not np.isnan(r1[i]) and r1[i] > -0.003: chk += 1      # small bounce to sell
    return chk >= 4


def long_signal(d, i):
    reg = v3.regime(d, i)
    return bool(v3.signal(d, i, reg).get("active")) and reg == "MOMENTUM"


def sim(sym, d, mode):
    c, h, l = d["c"], d["h"], d["l"]
    n = len(c)
    cost = MAKER_FEE + SPREAD.get(sym, 0.0035)
    trades = []
    last = -COOLDOWN
    for i in range(WARM, n):
        if i - last < COOLDOWN:
            continue
        go_long = mode in ("LONG", "COMBINED") and long_signal(d, i)
        go_short = mode in ("SHORT", "COMBINED") and short_signal(d, i)
        if not (go_long or go_short):
            continue
        side = 1 if go_long else -1
        ep = c[i]
        tp_p = ep * (1 + TP) if side > 0 else ep * (1 - TP)
        sl_p = ep * (1 - SL) if side > 0 else ep * (1 + SL)
        reason, xp, xi = "TIME", c[min(i + 48, n - 1)], min(i + 48, n - 1)
        for j in range(i + 1, min(i + 49, n)):
            if side > 0:
                if l[j] <= sl_p: reason, xp, xi = "SL", sl_p, j; break
                if h[j] >= tp_p: reason, xp, xi = "TP", tp_p, j; break
            else:
                if h[j] >= sl_p: reason, xp, xi = "SL", sl_p, j; break
                if l[j] <= tp_p: reason, xp, xi = "TP", tp_p, j; break
        g = side * (xp - ep) / ep - cost
        trades.append({"pnl": g, "hold": xi - i, "reason": reason, "side": "L" if side > 0 else "S"})
        last = xi
    return trades


def metrics(ts):
    if not ts:
        return {"n": 0}
    r = np.array([t["pnl"] for t in ts])
    wins = int((r > 0).sum())
    gp = r[r > 0].sum(); gl = -r[r <= 0].sum()
    eq = np.cumprod(1 + r * LEV * 0.10)
    peak = np.maximum.accumulate(eq); mdd = float((1 - eq / peak).max())
    return {"n": len(ts), "wr": wins / len(ts), "pf": (gp / gl) if gl > 0 else float("inf"),
            "avg": float(r.mean()), "maxdd": mdd, "ret": float(eq[-1] - 1),
            "permonth": len(ts) / MONTHS}


def run():
    data = {s: v3.load(s) for s in SYMS}
    print(f"{'mode':10}{'n':>5}{'trd/mo':>8}{'WR%':>6}{'PF':>6}{'avg%':>7}{'maxDD%':>8}{'ret%':>8}")
    print("─" * 60)
    for mode in ["LONG", "SHORT", "COMBINED"]:
        allt = []
        for s in SYMS:
            allt += sim(s, data[s], mode)
        m = metrics(allt)
        if m["n"] == 0:
            print(f"{mode:10}{'0':>5}  no trades"); continue
        print(f"{mode:10}{m['n']:>5}{m['permonth']:>8.1f}{100*m['wr']:>6.1f}"
              f"{m['pf']:>6.2f}{100*m['avg']:>7.2f}{100*m['maxdd']:>8.1f}{100*m['ret']:>8.1f}")
    print("─" * 60)
    print("trd/mo across BTC+ETH+SOL. LONG blocks in bear → SHORT fills that gap.")
    print("Verdict: SHORT-bear worth adding ONLY if PF≥1.2 AND it lifts trd/mo materially.")


def demo():
    # noisy downtrend (drift + noise) so RSI oscillates into 40-60 on bounces.
    rng = np.random.default_rng(1)
    n = 600
    ret = rng.normal(-0.002, 0.012, n)   # net down, with bounces
    c = 100 * np.cumprod(1 + ret)
    d = {"o": c, "h": c * (1 + np.abs(rng.normal(0, 0.003, n))),
         "l": c * (1 - np.abs(rng.normal(0, 0.003, n))),
         "c": c, "v": np.full(n, 2.0), "dates": np.arange(n)}
    ts = sim("BTC", d, "SHORT")
    assert len(ts) > 0, "short never fired in noisy downtrend — signal too strict"
    assert all(t["side"] == "S" for t in ts), "long trade in short mode — bug"
    tl = sim("BTC", d, "LONG")
    assert len(tl) == 0, "long fired in downtrend — regime filter broken"
    print(f"demo OK — noisy downtrend: short fired n={len(ts)}, long correctly blocked")


if __name__ == "__main__":
    (demo if len(sys.argv) > 1 and sys.argv[1] == "demo" else run)()
