"""Fungsi bersama simulasi & statistik (PRAREG-37). Tanpa efek samping saat diimpor."""
from __future__ import annotations
import math
import numpy as np, pandas as pd

COLS = ["btc", "eth", "xaut"]; TARGET = 0.0001; COST = 0.0010


def donchian_signed(close: pd.Series, lookbacks=(5, 10, 20, 30, 60, 90, 150, 250, 360)) -> pd.Series:
    p = close.values.astype(float); n = len(p); out = np.zeros(n)
    for L in lookbacks:
        pos = 0; stop = np.nan
        for t in range(L, n):
            hi = p[t - L:t].max(); lo = p[t - L:t].min()
            w2 = p[t - L + 1:t + 1]; mid = (w2.max() + w2.min()) / 2
            if pos == 0:
                if p[t] > hi: pos, stop = 1, mid
                elif p[t] < lo: pos, stop = -1, mid
            elif pos > 0:
                if p[t] < stop: pos = 0
                else: stop = max(stop, mid)
            else:
                if p[t] > stop: pos = 0
                else: stop = min(stop, mid)
            out[t] += pos
    return pd.Series(out / len(lookbacks), index=close.index)


def sim(closes: pd.DataFrame, tgt: pd.DataFrame, L, fund: pd.DataFrame, cost=COST):
    idx = closes.index
    Ls = pd.Series(L, index=idx).astype(float).clip(lower=0.0)
    R = closes.pct_change(fill_method=None).fillna(0.0)[COLS].values
    W = tgt.reindex(idx).fillna(0.0)[COLS].values
    E = W * Ls.values[:, None]
    Ep = np.vstack([np.zeros((1, E.shape[1])), E[:-1]])
    gross = (Ep * R).sum(axis=1)
    turn = np.abs(E - Ep * (1 + R)).sum(axis=1)
    c = turn * cost
    perp_signed = E - np.clip(E, 0, 1)
    F = fund.reindex(idx).fillna(0.0)[COLS].values
    drag = (perp_signed * F / 1e4).sum(axis=1)
    net = pd.Series(gross - c - drag, index=idx).iloc[1:]
    eq = (1 + net.clip(lower=-0.999999)).cumprod()
    return pd.DataFrame({"net": net, "gross": pd.Series(gross, index=idx).iloc[1:]}), float((eq / eq.cummax() - 1).min() * 100)


def stat(r: pd.Series):
    n = len(r); mu = float(r.mean()); sd = float(r.std())
    eq = (1 + r.clip(lower=-0.999999)).cumprod(); mdd = float((eq / eq.cummax() - 1).min() * 100)
    w = (1 + r).rolling(30).apply(np.prod, raw=True).dropna()
    hit = float((w ** (5 / (24 * 30)) - 1 >= TARGET).mean()) if len(w) else float("nan")
    return {"n": n, "M_per5h_pct": round(mu * 5 / 24 * 100, 5), "mdd_pct": round(mdd, 2), "sd_harian_pct": round(sd * 100, 3),
            "sharpe": round(mu / sd * math.sqrt(365), 2) if sd else None, "hit30": round(hit, 3) if hit == hit else None,
            "cum_pct": round(float(eq.iloc[-1] - 1) * 100, 1)}


def boot_p(a: pd.Series, b: pd.Series, seed=37, nb=4000, bl=20):
    d = (a - b).dropna().values; n = len(d)
    if n < 40: return 1.0
    rng = np.random.default_rng(seed); k = math.ceil(n / bl)
    st = rng.integers(0, n - bl + 1, size=(nb, k))
    ix = (st[:, :, None] + np.arange(bl)[None, None, :]).reshape(nb, -1)[:, :n]
    return round(float((d[ix].mean(axis=1) <= 0).mean()), 4)
