"""Backtest independen Mode A (tanpa bt3). Sinyal: rolling pandas (struktur beda dari engine).
Simulasi: replika test_engine.py (drift bobot, band, biaya = sum|order|*cost, lag 1 = target close d-1 dieksekusi close d)."""
import numpy as np, pandas as pd, math
LB = [5, 10, 20, 30, 60, 90, 150, 250, 360]
def load(p): return pd.read_csv(p, index_col=0, parse_dates=True)["close"].astype(float).sort_index()
def signal_indep(c: pd.Series) -> pd.Series:
    out = pd.Series(0.0, index=c.index); v = c.values
    for L in LB:
        hi_prev = c.shift(1).rolling(L).max().values
        mx = c.rolling(L).max().values; mn = c.rolling(L).min().values; mid = (mx + mn) / 2
        pos = False; stop = np.nan; flag = np.zeros(len(c))
        for t in range(len(c)):
            if np.isnan(hi_prev[t]): continue
            if not pos:
                if v[t] > hi_prev[t]: pos, stop = True, mid[t]
            elif v[t] < stop: pos, stop = False, np.nan
            else: stop = max(stop, mid[t])
            flag[t] = pos
        out += flag
    return out / len(LB)
def targets_indep(closes: dict, vt=0.5, vol_win=90, min_hist=360) -> pd.DataFrame:
    px = pd.DataFrame(closes).sort_index()
    sig = pd.DataFrame({k: signal_indep(closes[k].dropna()) for k in closes}).reindex(px.index).fillna(0.0)
    vol = px.pct_change(fill_method=None).rolling(vol_win).std() * math.sqrt(365)
    elig = (px.notna().cumsum() >= min_hist) & px.notna()
    n = elig.sum(axis=1).replace(0, np.nan)
    t = (sig * (vt / vol).clip(upper=1.0)).where(elig, 0.0).div(n, axis=0).fillna(0.0)
    return t.div(np.maximum(t.sum(axis=1), 1.0), axis=0)
def band_orders(w, t, band):
    o = {}
    for k in t:
        d = t[k] - w.get(k, 0.0)
        if (t[k] == 0 and w.get(k, 0.0) > 0) or abs(d) > band * max(t[k], 0.05): o[k] = d
    return o
def simulate(closes: dict, tgt: pd.DataFrame, start="2019-01-01", end=None, cost=0.0025, lag=1, band=0.20, extra_slip=0.0):
    px = pd.DataFrame(closes).sort_index()
    if end: px = px.loc[:end]
    ret = px.pct_change(fill_method=None); idx = px.loc[start:].index
    tl = tgt.reindex(px.index).shift(lag).fillna(0.0)
    cols = list(px.columns); w = {c: 0.0 for c in cols}; net = []; turn = []
    for d in idx:
        r = ret.loc[d].fillna(0.0); g = sum(w[c] * r[c] for c in cols)
        w = {c: w[c] * (1 + r[c]) / (1 + g) for c in cols}
        o = band_orders(w, {c: float(tl.loc[d, c]) for c in cols}, band)
        tv = sum(abs(v) for v in o.values()); cst = tv * (cost + extra_slip)
        for c, v in o.items(): w[c] += v
        net.append((1 + g) * (1 - cst) - 1); turn.append(tv)
    return pd.Series(net, index=idx), pd.Series(turn, index=idx)
def stats(r: pd.Series):
    eq = (1 + r).cumprod(); dd = eq / eq.cummax() - 1
    m, s = r.mean(), r.std()
    return dict(per5h=round(m * 5 / 24 * 100, 4), sharpe=round(m / s * math.sqrt(365), 2) if s > 0 else 0, mdd=round(dd.min() * 100, 1),
                cagr=round(((eq.iloc[-1]) ** (365 / len(r)) - 1) * 100, 1), t=round(m / s * math.sqrt(len(r)), 2) if s > 0 else 0, n=len(r))
def row(label, r):
    a = stats(r); b = stats(r.loc["2022-01-01":])
    print(f"{label:34s} full {a['per5h']:.4f} Sh {a['sharpe']:5.2f} MDD {a['mdd']:6.1f} t {a['t']:5.2f} | 2022+ {b['per5h']:.4f} Sh {b['sharpe']:5.2f} MDD {b['mdd']:6.1f} t {b['t']:5.2f}")
