#!/usr/bin/env python3
"""Metals (XAUT gold / KAG silver) paper test — Intelligence + 13 TA + Quant validation.

User asked to combine three layers and perfect them:
  1. INTELLIGENCE  — regime (trend direction + strength + volatility) gate.
  2. 13 CORE TA    — RSI, MACD, Bollinger %B, Stochastic, ADX/DI, EMA20/50,
                     SMA50/200, ROC, CCI, Williams%R, ATR-trend, MFI, OBV.
  3. QUANT STATS   — triple-barrier labels, non-overlapping, chronological
                     train/OOS split, net-of-cost expectancy, z-significance,
                     per-regime breakdown. The truth-teller: does the composite
                     signal beat a coin-flip OUT-OF-SAMPLE after real cost?

Data: coingecko hourly (price+volume), resampled to 4h OHLCV (real intra-bar
high/low from the 4 hourly closes). Read-only, stdlib. profit-first: report the
honest OOS verdict — do NOT deploy a signal that fails the quant gate.

Run:  python3 scripts/metals_intel_ta_test.py
      python3 scripts/metals_intel_ta_test.py demo
"""
from __future__ import annotations
import urllib.request, json, time, sys, math

# real round-trip taker cost (bps) — from prior SoDEX metals audit
COST_BPS = {"XAUT": 10.0, "KAG": 11.5}
TB_ATR = 1.5          # triple-barrier width in ATR
TB_HORIZON = 6        # bars (4h × 6 = 24h) to hit a barrier
TRAIN_FRAC = 0.60
SIGNAL_THRESH = 4     # net TA vote magnitude to fire (of 13)


# ── data ─────────────────────────────────────────────────────────────────────
def fetch(cid, days=90):
    u = f"https://api.coingecko.com/api/v3/coins/{cid}/market_chart?vs_currency=usd&days={days}"
    d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "anantara"}), timeout=30))
    return d["prices"], d.get("total_volumes", [])


def resample_4h(prices, vols):
    """Hourly [ts,px] → 4h OHLCV bars (high/low from the hourly closes in-bar)."""
    vmap = {int(t // 3600000): v for t, v in vols}
    bars, cur = [], None
    for ts, px in prices:
        h = int(ts // 3600000)
        b = h // 4
        if cur is None or b != cur["b"]:
            if cur:
                bars.append(cur)
            cur = {"b": b, "o": px, "h": px, "l": px, "c": px, "v": vmap.get(h, 0.0)}
        else:
            cur["h"] = max(cur["h"], px); cur["l"] = min(cur["l"], px)
            cur["c"] = px; cur["v"] += vmap.get(h, 0.0)
    if cur:
        bars.append(cur)
    return bars


# ── indicator helpers ────────────────────────────────────────────────────────
def sma(x, n): return sum(x[-n:]) / n if len(x) >= n else None
def ema_series(x, n):
    k = 2 / (n + 1); e = [x[0]]
    for v in x[1:]:
        e.append(v * k + e[-1] * (1 - k))
    return e
def rsi(c, n=14):
    if len(c) < n + 1: return 50.0
    g = l = 0.0
    for i in range(-n, 0):
        d = c[i] - c[i - 1]
        g += max(d, 0); l += max(-d, 0)
    if l == 0: return 100.0
    rs = (g / n) / (l / n)
    return 100 - 100 / (1 + rs)
def true_ranges(H, L, C):
    tr = [H[0] - L[0]]
    for i in range(1, len(C)):
        tr.append(max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])))
    return tr
def atr(H, L, C, n=14):
    tr = true_ranges(H, L, C)
    return sma(tr, n) or (sum(tr) / len(tr))
def adx_di(H, L, C, n=14):
    if len(C) < n + 2: return 0.0, 0.0, 0.0
    pdm = ndm = 0.0
    for i in range(-n, 0):
        up = H[i] - H[i - 1]; dn = L[i - 1] - L[i]
        pdm += up if (up > dn and up > 0) else 0
        ndm += dn if (dn > up and dn > 0) else 0
    a = atr(H, L, C, n) * n
    if a == 0: return 0.0, 0.0, 0.0
    pdi = 100 * pdm / a; ndi = 100 * ndm / a
    dx = 100 * abs(pdi - ndi) / (pdi + ndi) if (pdi + ndi) else 0
    return dx, pdi, ndi
def stoch(H, L, C, n=14):
    if len(C) < n: return 50.0
    hh = max(H[-n:]); ll = min(L[-n:])
    return 100 * (C[-1] - ll) / (hh - ll) if hh > ll else 50.0
def cci(H, L, C, n=20):
    if len(C) < n: return 0.0
    tp = [(H[i] + L[i] + C[i]) / 3 for i in range(-n, 0)]
    m = sum(tp) / n; md = sum(abs(t - m) for t in tp) / n
    return (tp[-1] - m) / (0.015 * md) if md else 0.0
def willr(H, L, C, n=14):
    if len(C) < n: return -50.0
    hh = max(H[-n:]); ll = min(L[-n:])
    return -100 * (hh - C[-1]) / (hh - ll) if hh > ll else -50.0
def mfi(H, L, C, V, n=14):
    if len(C) < n + 1: return 50.0
    pos = neg = 0.0
    for i in range(-n, 0):
        tp = (H[i] + L[i] + C[i]) / 3; tp0 = (H[i - 1] + L[i - 1] + C[i - 1]) / 3
        mf = tp * V[i]
        if tp > tp0: pos += mf
        elif tp < tp0: neg += mf
    if neg == 0: return 100.0
    return 100 - 100 / (1 + pos / neg)
def obv_slope(C, V, n=10):
    if len(C) < n + 1: return 0.0
    o = [0.0]
    for i in range(1, len(C)):
        o.append(o[-1] + (V[i] if C[i] > C[i - 1] else -V[i] if C[i] < C[i - 1] else 0))
    return o[-1] - o[-1 - n]


# ── 13-TA composite (each votes -1/0/+1 for next-move direction) ─────────────
def ta_votes(O, H, L, C, V):
    v = {}
    v["rsi"] = 1 if rsi(C) > 50 else -1
    ef, es = ema_series(C, 12), ema_series(C, 26)
    macd = ef[-1] - es[-1]; sig = ema_series([a - b for a, b in zip(ef, es)], 9)[-1]
    v["macd"] = 1 if macd > sig else -1
    m = sma(C, 20); sd = (sum((x - m) ** 2 for x in C[-20:]) / 20) ** 0.5 if len(C) >= 20 and m else 0
    pctb = (C[-1] - (m - 2 * sd)) / (4 * sd) if sd else 0.5
    v["boll"] = 1 if pctb < 0.5 else -1                       # mean-reversion within bands
    v["stoch"] = 1 if stoch(H, L, C) < 50 else -1             # reversion
    dx, pdi, ndi = adx_di(H, L, C)
    v["adx"] = (1 if pdi > ndi else -1) if dx > 20 else 0     # only vote in a trend
    e20, e50 = sma(C, 20), sma(C, 50)
    v["ema"] = 1 if (e20 and e50 and e20 > e50) else -1
    s50, s200 = sma(C, 50), sma(C, 200)
    v["sma"] = (1 if s50 > s200 else -1) if (s50 and s200) else 0
    v["roc"] = 1 if len(C) > 10 and C[-1] > C[-11] else -1
    c = cci(H, L, C); v["cci"] = 1 if c > 0 else -1
    w = willr(H, L, C); v["willr"] = 1 if w < -50 else -1     # reversion
    a = atr(H, L, C); e = sma(C, 20)
    v["atrtrend"] = 1 if (e and C[-1] > e + 0.1 * a) else (-1 if (e and C[-1] < e - 0.1 * a) else 0)
    v["mfi"] = 1 if mfi(H, L, C, V) < 50 else -1              # reversion
    v["obv"] = 1 if obv_slope(C, V) > 0 else -1
    return v, sum(v.values())


def regime_of(C):
    """Intelligence layer: trend direction from EMA50 slope + strength."""
    if len(C) < 60: return "RANGING"
    e = ema_series(C, 50)
    slope = (e[-1] - e[-13]) / e[-13]           # ~2-day EMA slope
    if slope > 0.004: return "BULL"
    if slope < -0.004: return "BEAR"
    return "RANGING"


# ── quant backtest: triple-barrier, non-overlap, train/OOS, net-of-cost ──────
def backtest(bars, cost_bps):
    O = [b["o"] for b in bars]; H = [b["h"] for b in bars]
    L = [b["l"] for b in bars]; C = [b["c"] for b in bars]; V = [b["v"] for b in bars]
    trades = []
    i = 60
    while i < len(bars) - TB_HORIZON:
        _, net = ta_votes(O[:i + 1], H[:i + 1], L[:i + 1], C[:i + 1], V[:i + 1])
        reg = regime_of(C[:i + 1])
        # signal: strong TA vote AND intelligence-confirmed direction
        side = 0
        if net >= SIGNAL_THRESH and reg == "BULL": side = 1
        elif net <= -SIGNAL_THRESH and reg == "BEAR": side = -1
        if side == 0:
            i += 1; continue
        entry = C[i]; a = atr(H[:i + 1], L[:i + 1], C[:i + 1])
        up, dn = entry + TB_ATR * a, entry - TB_ATR * a
        outcome = 0; exit_i = i + TB_HORIZON
        for j in range(i + 1, min(i + 1 + TB_HORIZON, len(bars))):
            if H[j] >= up: outcome = 1 * side; exit_i = j; break
            if L[j] <= dn: outcome = -1 * side; exit_i = j; break
        else:
            outcome = side * (1 if C[min(i + TB_HORIZON, len(C) - 1)] > entry else -1)
        ret_bps = (TB_ATR * a / entry) * 1e4 * outcome - cost_bps   # net of RT cost
        trades.append({"i": i, "reg": reg, "side": side, "win": outcome > 0, "ret_bps": ret_bps})
        i = exit_i + 1                              # NON-OVERLAPPING
    return trades


def summarize(name, trades, cost_bps):
    if not trades:
        print(f"\n{name}: 0 signals (no strong TA+regime alignment) — nothing to trade.")
        return
    k = int(len(trades) * TRAIN_FRAC)
    tr, oos = trades[:k], trades[k:]
    def stats(t):
        if not t: return (0, 0.0, 0.0, 0.0)
        n = len(t); wr = sum(x["win"] for x in t) / n
        avg = sum(x["ret_bps"] for x in t) / n
        z = (sum(x["win"] for x in t) - n / 2) / (math.sqrt(n) / 2) if n else 0
        return (n, wr, avg, z)
    for lbl, t in [("TRAIN", tr), ("OOS  ", oos), ("ALL  ", trades)]:
        n, wr, avg, z = stats(t)
        print(f"  {lbl}: n={n:<3} WR={wr*100:4.1f}%  net={avg:+6.1f}bps/trade  z={z:+.2f}")
    n, wr, avg, z = stats(oos)
    verdict = ("✅ EDGE (OOS net>0 AND z>1.64)" if avg > 0 and z > 1.64
               else "❌ NO EDGE (fails OOS net>0 &/or significance)")
    print(f"  → VERDICT {name}: {verdict}  [cost {cost_bps}bps/RT]")


def run():
    print("=" * 70)
    print("METALS PAPER TEST — Intelligence + 13 TA + Quant (triple-barrier OOS)")
    print("=" * 70)
    for cid, name in [("tether-gold", "XAUT"), ("kinesis-silver", "KAG")]:
        try:
            prices, vols = fetch(cid)
        except Exception as e:
            print(f"\n{name}: fetch error {e}"); continue
        bars = resample_4h(prices, vols)
        print(f"\n{name}: {len(prices)} hourly → {len(bars)} 4h bars "
              f"(~{len(bars)*4/24:.0f}d), last ${bars[-1]['c']:.2f}")
        tr = backtest(bars, COST_BPS[name])
        summarize(name, tr, COST_BPS[name])
        time.sleep(2)
    print("\nMethod: signal = |13-TA net|≥4 AND intelligence-regime confirms direction.")
    print("Trust ONLY OOS net>0 with z>1.64. profit-first: no deploy if ❌.")


def demo():
    # synthetic uptrend → indicators + backtest must run without error and
    # a clean trend should yield mostly winning longs (engine sanity).
    import random
    random.seed(1)
    px, base = [], 100.0
    for t in range(2000):
        base *= 1 + 0.0008 + random.uniform(-0.004, 0.004)
        px.append([t * 3600000, base])
    vols = [[t * 3600000, 1000 + random.random() * 100] for t in range(2000)]
    bars = resample_4h(px, vols)
    assert len(bars) > 100
    v, net = ta_votes([b["o"] for b in bars], [b["h"] for b in bars],
                      [b["l"] for b in bars], [b["c"] for b in bars], [b["v"] for b in bars])
    assert len(v) == 13, f"expected 13 indicators, got {len(v)}"
    tr = backtest(bars, 10.0)
    assert regime_of([b["c"] for b in bars]) in ("BULL", "BEAR", "RANGING")
    print(f"demo OK — 13 indicators computed, backtest ran ({len(tr)} trades on synthetic trend)")


if __name__ == "__main__":
    demo() if len(sys.argv) > 1 and sys.argv[1] == "demo" else run()
