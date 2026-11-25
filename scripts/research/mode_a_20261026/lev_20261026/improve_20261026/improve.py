#!/usr/bin/env python3
"""PRAREG-37 (studi) — menaikkan RELIABILITAS B2: sisi SHORT, ensemble lookback, vol-target portofolio.
Train 2022-2024, OOS 2025-2026, BH atas seluruh sel. Tidak mengubah PRAREG-36 (beku)."""
from __future__ import annotations
import json, math, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); PARENT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, PARENT); sys.path.insert(0, os.path.dirname(PARENT))
import lev_study as ls, mode_a_engine as eng

COLS = ["btc", "eth", "xaut"]; COST = 0.0010; TARGET = 0.0001      # 0,010%/5j


def donchian_signed(close: pd.Series, lookbacks=eng.LOOKBACKS) -> pd.Series:
    """Simetris dari donchian_signal: +1 break high, −1 break low, keluar di mid (trailing)."""
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
    """Eksposur bertanda E = w×L. spot = clip(E,0,1); perp = E − spot (funding dibayar/diterima sesuai tanda)."""
    idx = closes.index
    Ls = pd.Series(L, index=idx).astype(float).clip(lower=0.0)
    R = closes.pct_change(fill_method=None).fillna(0.0)[COLS].values
    W = tgt.reindex(idx).fillna(0.0)[COLS].values
    E = W * Ls.values[:, None]
    Ep = np.vstack([np.zeros((1, E.shape[1])), E[:-1]])
    gross = (Ep * R).sum(axis=1)
    turn = np.abs(E - Ep * (1 + R)).sum(axis=1)
    c = turn * cost
    perp_signed = E - np.clip(E, 0, 1)                             # >0 long perp, <0 short perp
    F = fund.reindex(idx).fillna(0.0)[COLS].values
    drag = (perp_signed * F / 1e4).sum(axis=1)                     # funding positif: long bayar, short terima
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


closes_d, ohlc, f = ls.load_all()
closes = pd.DataFrame({k: closes_d[k] for k in COLS}).loc["2021-01-01":]
fund = ls.build_fund(closes, f)
T_B2 = eng.target_history({k: closes[k] for k in COLS}, mode="B2", validate=False)

sig_sym = pd.DataFrame({k: donchian_signed(closes[k]) for k in COLS})
voln = closes.pct_change(fill_method=None).rolling(eng.VOL_WIN).std() * math.sqrt(365)
elig = (closes.notna().cumsum() >= eng.MIN_HIST) & closes.notna()
W_sym = (sig_sym * np.minimum(1.0, eng.VT / voln)).where(elig, 0.0).fillna(0.0)
gross_w = W_sym.abs().sum(axis=1)
W_sym = W_sym.div(np.maximum(gross_w, 1.0), axis=0)                     # gross ≤ 1

# vol-target portofolio (eks-ante): vol 20d dari return strategi 1x
r1 = (W_sym.shift(1) * closes.pct_change(fill_method=None)).sum(axis=1)
volp = r1.rolling(20).std() * math.sqrt(365)
def vt(v): return (v / volp).clip(1.0, 3.0)          # untuk varian simetris
r1b = (T_B2.shift(1) * closes.pct_change(fill_method=None)).sum(axis=1)
volpb = r1b.rolling(20).std() * math.sqrt(365)
def vtb(v, cap=2.5): return (v / volpb).clip(1.0, cap)   # untuk B2 — vol dari sinyal yang benar

FIX = pd.Series(1.5, index=closes.index)
V = {
    "V0_B2_long_1.5": sim(closes, T_B2, FIX, fund),
    "V6_sym_1.5": sim(closes, W_sym, FIX, fund),
    "V7_sym_2.0": sim(closes, W_sym, pd.Series(2.0, index=closes.index), fund),
    "V8_sym_vt25": sim(closes, W_sym, vt(0.25), fund),
    "V9_sym_vt30": sim(closes, W_sym, vt(0.30), fund),
    "V10_B2_vt25": sim(closes, T_B2, vtb(0.25), fund),
}
res = {}
for k, (df, mdd) in V.items():
    res[k] = {"train": stat(df["net"].loc["2022-01-01":"2024-12-31"]), "oos": stat(df["net"].loc["2025-01-01":"2026-10-25"]),
              "full": stat(df["net"].loc["2022-01-01":]), "mdd_full": round(mdd, 2),
              "L_mean": round(float(pd.Series(vt(0.25), index=closes.index).loc["2022-01-01":].mean()) if "vt" in k else (2.0 if "2.0" in k else 1.5), 2)}

cmp = {}
for k in V:
    if k == "V0_B2_long_1.5": continue
    a, b = V[k][0]["net"].loc["2022-01-01":], V["V0_B2_long_1.5"][0]["net"].loc["2022-01-01":]
    cmp[k] = {"dM": round(res[k]["full"]["M_per5h_pct"] - res["V0_B2_long_1.5"]["full"]["M_per5h_pct"], 5),
              "dhit30": round((res[k]["full"]["hit30"] or 0) - (res["V0_B2_long_1.5"]["full"]["hit30"] or 0), 3),
              "p_boot": boot_p(a, b)}
m = len(cmp); rank = sorted(cmp, key=lambda k: cmp[k]["p_boot"])
for i, k in enumerate(rank, 1):
    cmp[k]["bh_lolos"] = bool(cmp[k]["p_boot"] <= 0.05 * i / m)

# alpha/beta V0 (bersih dari NaN)
r0 = V["V0_B2_long_1.5"][0]["net"].loc["2022-01-01":]
x = closes["btc"].pct_change().reindex(r0.index)
d = pd.concat([r0.rename("r"), x.rename("x")], axis=1).dropna()
X = np.column_stack([np.ones(len(d)), d["x"].values]); alpha, beta = np.linalg.lstsq(X, d["r"].values, rcond=None)[0]
resid = d["r"].values - X @ [alpha, beta]; se = np.std(resid, ddof=2) / np.sqrt(len(d))
ab = {"beta_btc": round(float(beta), 3), "alpha_per5h_pct": round(alpha * 5 / 24 * 100, 5),
      "t_alpha": round(float(alpha / se), 2), "korelasi": round(float(d["r"].corr(d["x"])), 3)}

out = {"utc": pd.Timestamp.utcnow().isoformat(), "hasil": res, "vs_baseline": cmp, "alpha_beta": ab,
       "target_per5h_pct": 0.010, "catatan": "Adopsi hanya bila hit30 naik di TRAIN dan OOS, MDD >= -35%, dan BH lolos."}
json.dump(out, open(os.path.join(HERE, "improve_results.json"), "w"), indent=1)
print(f"{'varian':18s} {'L':>4s} {'FULL M':>8s} {'mdd':>7s} {'sharpe':>6s} {'hit30':>6s} | {'TRAIN M':>8s} {'hit':>5s} | {'OOS M':>8s} {'hit':>5s} | BH")
for k, v in res.items():
    print(f"{k:18s} {v['L_mean']:4.2f} {v['full']['M_per5h_pct']:8.5f} {v['full']['mdd_pct']:7.1f} {v['full']['sharpe']:6.2f} {v['full']['hit30']:6.3f} | "
          f"{v['train']['M_per5h_pct']:8.5f} {v['train']['hit30']:5.3f} | {v['oos']['M_per5h_pct']:8.5f} {v['oos']['hit30']:5.3f} | {cmp.get(k,{}).get('bh_lolos','-')}")
print("alpha/beta:", ab)
