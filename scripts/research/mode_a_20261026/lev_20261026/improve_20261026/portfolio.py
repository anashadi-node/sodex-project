#!/usr/bin/env python3
"""PRAREG-37 (studi portofolio) — sleeve carry delta-neutral + B2 vol-target, alokasi risiko.
Tujuan: menaikkan peluang 30-hari mencapai 0,010%/5j TANPA melanggar MDD -35%.
Basis diasumsikan konstan (perp mengikuti spot) — keterbatasan dicatat."""
from __future__ import annotations
import json, math, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); PARENT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, PARENT); sys.path.insert(0, os.path.dirname(PARENT))
import lev_study as ls, mode_a_engine as eng
from simlib import sim, stat, COLS, TARGET

MARGIN = 0.33          # margin perp 33% notional (tier konservatif; SoDEX belum dimodelkan)
COST = 0.0010

closes_d, ohlc, f = ls.load_all()
closes = pd.DataFrame({k: closes_d[k] for k in COLS}).loc["2021-01-01":]
fund = ls.build_fund(closes, f)
idx = closes.index

# ---------- sleeve CARRY: long spot + short perp, delta-neutral ----------
w = pd.DataFrame(0.0, index=idx, columns=COLS); w["btc"], w["eth"] = 0.5, 0.5
N = 1.0                                              # notional per unit modal (spot 1x)
cap = N * (1 + MARGIN)                               # modal = spot + margin
F = fund[COLS].fillna(0.0)
turn = w.diff().abs().sum(axis=1).fillna(w.abs().sum(axis=1))
r_carry = ((w * F / 1e4).sum(axis=1) - turn * COST) / cap
r_carry = r_carry.loc["2022-01-01":]

# ---------- sleeve B2 vol-target 25% ----------
T_B2 = eng.target_history({k: closes[k] for k in COLS}, mode="B2", validate=False)
voln = closes.pct_change(fill_method=None).rolling(eng.VOL_WIN).std() * math.sqrt(365)
r1 = (T_B2.shift(1) * closes.pct_change(fill_method=None)).sum(axis=1)
volp = r1.rolling(20).std() * math.sqrt(365)
Lb2 = (0.25 / volp).clip(1.0, 3.0)
df_b2, mdd_b2 = sim(closes, T_B2, Lb2, fund)
r_b2 = df_b2["net"].loc["2022-01-01":]

print("CARRY :", stat(r_carry))
print("B2 vt:", stat(r_b2))

rows = []
for a in (0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0):
    p = a * r_carry + (1 - a) * r_b2
    s = stat(p); s["a_carry"] = a
    s["train_hit"] = stat(p.loc["2022-01-01":"2024-12-31"])["hit30"]
    s["oos_hit"] = stat(p.loc["2025-01-01":])["hit30"]
    s["train_M"] = stat(p.loc["2022-01-01":"2024-12-31"])["M_per5h_pct"]
    s["oos_M"] = stat(p.loc["2025-01-01":])["M_per5h_pct"]
    rows.append(s)
    print(f"a={a:3.1f} M={s['M_per5h_pct']:.5f} vol={s['sd_harian_pct']:.3f}% sharpe={s['sharpe']:.2f} mdd={s['mdd_pct']:.1f} hit30={s['hit30']:.3f} | train {s['train_M']:.5f}/{s['train_hit']:.3f} | oos {s['oos_M']:.5f}/{s['oos_hit']:.3f}")

# leverage pada portofolio (skala konstan) agar M mendekati target, batas MDD
best = max((r for r in rows if r["mdd_pct"] >= -35), key=lambda r: r["hit30"])
print("pilihan (MDD>=-35, hit30 maks):", best["a_carry"], best["hit30"], best["mdd_pct"])
json.dump({"carry": stat(r_carry), "b2_vt": stat(r_b2), "alokasi": rows, "pilihan": best,
           "margin_perp": MARGIN, "catatan": "basis konstan; funding Binance sebagai proksi SoDEX"},
          open(os.path.join(HERE, "portfolio_results.json"), "w"), indent=1)
