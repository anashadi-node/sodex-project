import sys, warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np
from bt_indep import *
import mode_a_engine_orig as eng
END = "2026-05-23"
cm = {k: load(f"data/cm_{k}.csv").loc[:END] for k in ("btc", "eth", "xaut")}
# 1) sinyal engine vs independen
worst = 0
for k, c in cm.items():
    a = eng.donchian_signal(c); b = signal_indep(c); worst = max(worst, float((a - b).abs().max()))
print("TEST sinyal engine vs independen, max|diff| =", worst)
te = eng.target_history(cm); ti = targets_indep(cm); print("TEST target engine vs independen, max|diff| =", float((te - ti).abs().max().max()))
r, tv = simulate(cm, te, end=END)
print("\n== REPLIKASI dokumen (data Coin Metrics s/d 23 Mei 2026). Klaim: full 0.0157 Sh1.33 MDD-21.1 | 2022+ 0.0055 Sh0.65 MDD-13.0")
row("Mode A dasar (VT50, c0.25, lag1)", r)
print("turnover/thn:", round(tv.sum() / len(tv) * 365, 1), "| bobot terakhir:", eng.latest_targets(cm)["weights"], eng.latest_targets(cm)["asof_close"])
for c in (0.001, 0.005, 0.01): row(f"biaya {c*100:.2f}%", simulate(cm, te, end=END, cost=c)[0])
for lag in (0, 2, 3): row(f"lag {lag}", simulate(cm, te, end=END, lag=lag)[0])
row("band 0", simulate(cm, te, end=END, band=0)[0]); row("band 0.4", simulate(cm, te, end=END, band=0.4)[0])
for vt in (0.25, 0.75): row(f"VT {vt}", simulate(cm, eng.target_history(cm, vt), end=END)[0])
px = pd.DataFrame(cm).loc["2018-01-01":END]; rb = px["btc"].pct_change().loc["2019-01-01":]; row("BTC B&H", rb)
by = {y: round(((1 + r[r.index.year == y]).prod() - 1) * 100, 1) for y in range(2019, 2027)}; print("per tahun:", by)
