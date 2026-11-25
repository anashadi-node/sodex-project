import warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np
from bt_indep import *
import mode_a_engine_orig as eng
cmx = load("data/cm_xaut.csv"); bx = load("data/xaut_binance.csv")
# sambung XAUT: CM s/d 2026-05-23, lalu return Binance dirantai (level kontinu)
aft = bx.loc["2026-05-24":]; xaut = pd.concat([cmx, (aft / bx.loc["2026-05-23"]) * cmx.iloc[-1]]).sort_index()
xaut = xaut[~xaut.index.duplicated()]
xaut.rename("close").to_csv("data/xaut_spliced.csv", index_label="date")
print("xaut spliced", xaut.index[0].date(), xaut.index[-1].date(), len(xaut), "gaps", len(pd.date_range(xaut.index[0], xaut.index[-1]).difference(xaut.index)))
BN = {"btc": load("data/btc.csv"), "eth": load("data/eth.csv"), "xaut": xaut}
CM = {"btc": load("data/cm_btc.csv"), "eth": load("data/cm_eth.csv"), "xaut": xaut}
for name, cl in (("A) Binance BTC/ETH + XAUT sambung", BN), ("B) Coin Metrics BTC/ETH + XAUT sambung", CM)):
    t = eng.target_history(cl); r, tv = simulate(cl, t, end=None)
    print("\n==", name, "| data s/d", r.index[-1].date())
    row("Mode A dasar", r)
    s = stats(r.loc["2026-05-24":]); print("OOS 24Mei-24Okt 2026:", s, "| hasil majemuk %:", round(((1+r.loc['2026-05-24':]).prod()-1)*100, 2))
    for y in range(2019, 2027): print(f"  {y}: {((1 + r[r.index.year == y]).prod() - 1)*100:7.1f}%", end="")
    print()
    print("bobot terakhir", eng.latest_targets(cl))
    print("turnover/thn", round(tv.sum() / len(tv) * 365, 1))
    if name.startswith("A"):
        a = stats(r); b = stats(r.loc["2022-01-01":]); print("gerbang replikasi +-20%: full", 0.0157*0.8 <= a['per5h'] <= 0.0157*1.2, "| 2022+", 0.0055*0.8 <= b['per5h'] <= 0.0055*1.2)
        rr = r.loc["2022-01-01":]; m180 = r.rolling(180).mean()*5/24*100; print("rolling180 terakhir:", round(m180.iloc[-1], 4), "%/5j")
        eq = (1+r).cumprod(); print("DD sekarang dari puncak:", round((eq.iloc[-1]/eq.cummax().iloc[-1]-1)*100, 1), "%")
BNr = simulate(BN, eng.target_history(BN))[0]
BNr.to_csv("data/modeA_daily_binance.csv")
print("\nBTC B&H 2026-05-24..:", round((BN['btc'].iloc[-1]/BN['btc'].loc['2026-05-23']-1)*100,1), "% | ETH", round((BN['eth'].iloc[-1]/BN['eth'].loc['2026-05-23']-1)*100,1), "% | XAUT", round((xaut.iloc[-1]/xaut.loc['2026-05-23']-1)*100,1), "%")
print({k: round(float(v.iloc[-1]), 2) for k, v in BN.items()})
