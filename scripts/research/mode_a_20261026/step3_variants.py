import warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np, math
from bt_indep import *
import mode_a_engine_orig as eng
BN = {"btc": load("data/btc.csv"), "eth": load("data/eth.csv"), "xaut": load("data/xaut_spliced.csv")}
tA = eng.target_history(BN)
px = pd.DataFrame(BN).sort_index(); elig_x = (px["xaut"].notna().cumsum() >= 360) & px["xaut"].notna()
sig_x = pd.Series(eng.donchian_signal(BN["xaut"]), index=BN["xaut"].index).reindex(px.index).fillna(0)
def mk(kind):
    t = tA.copy(); rem = (1 - t["btc"] - t["eth"]).clip(lower=0)
    if kind == "B1": t["xaut"] = rem.where(elig_x, 0.0)
    if kind == "B2": t["xaut"] = (rem * sig_x).where(elig_x, 0.0)
    return t
T = {"A": tA, "B1": mk("B1"), "B2": mk("B2")}
START = "2021-02-01"
def span(r, a, b=None): return r.loc[a:b] if b else r.loc[a:]
def line(lab, r):
    o = []
    for nm, rr in (("2021+", r), ("2022+", span(r, "2022-01-01")), ("2024+", span(r, "2024-01-01")), ("OOS26", span(r, "2026-05-24"))):
        s = stats(rr); o.append(f"{nm} {s['per5h']:.4f}/Sh{s['sharpe']:.2f}/DD{s['mdd']:.0f}")
    print(f"{lab:14s} " + " | ".join(o))
res = {}
for cost in (0.0010, 0.0025):
    print(f"\n=== biaya {cost*100:.2f}%/sisi (BTC,ETH,XAUT; sim mulai {START}) ===")
    for k, t in T.items():
        r, tv = simulate(BN, t, start=START, cost=cost); res[(k, cost)] = r; line(k, r)
        if cost == 0.0010: print(f"{'':14s} turnover/thn {tv.sum()/len(tv)*365:.1f} | avg bobot XAUT {t['xaut'].loc[START:].mean():.2f} BTC {t['btc'].loc[START:].mean():.3f} ETH {t['eth'].loc[START:].mean():.3f}")
rets = pd.DataFrame(BN).pct_change().loc[START:]
for lab, r in (("BTC B&H", rets["btc"]), ("XAUT B&H", rets["xaut"]), ("EW3 B&H", rets.mean(axis=1))): line(lab, r)
print("\nPer tahun (biaya 0.10%):")
for k in T:
    r = res[(k, 0.0010)]; print(f"  {k:3s}", {y: round(((1 + r[r.index.year == y]).prod() - 1) * 100, 1) for y in range(2021, 2027)})
for lab, r in (("XAUT", rets["xaut"]), ("BTC", rets["btc"])): print(f"  {lab:3s}", {y: round(((1 + r[r.index.year == y]).prod() - 1) * 100, 1) for y in range(2021, 2027)})
# bootstrap blok stasioner 30 hari dari 2022+, tahun 365 hari
rng = np.random.default_rng(7)
def boot(r, n=10000, blk=30):
    v = r.values; N = len(v); out = []
    for _ in range(n):
        s = []; 
        while len(s) < 365:
            i = rng.integers(0, N - blk); s += list(v[i:i + blk])
        s = np.array(s[:365]); out.append(s.mean() * 5 / 24 * 100)
    out = np.array(out); return out
print("\nBootstrap 365 hari dari data 2022+ (biaya 0.10%): P(>=0.010)  P(<0)  median  P10  P90")
for k in T:
    b = boot(span(res[(k, 0.0010)], "2022-01-01")); print(f"  {k:3s} {np.mean(b>=0.010)*100:5.1f}%  {np.mean(b<0)*100:5.1f}%  {np.median(b):.4f}  {np.percentile(b,10):.4f}  {np.percentile(b,90):.4f}")
pd.DataFrame({f"{k}_{c}": v for (k, c), v in res.items()}).to_csv("data/variants_daily.csv")
