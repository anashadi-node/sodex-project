#!/usr/bin/env python3
"""PRAREG-37 (studi) — momentum lintas-seksi 30 koin Binance, 2022-2026.
Cache parquet lokal. Biaya 10 bps/sisi. Train 2022-2024 / OOS 2025-2026.
Batas: universe = koin yang masih ada hari ini (survivorship bias, hasil = batas atas)."""
from __future__ import annotations
import json, math, os, sys, time, urllib.request
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); CACHE = os.path.join(HERE, "xs_data")
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import lev_study as ls
from simlib import stat, TARGET
os.makedirs(CACHE, exist_ok=True)

SYMS = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","AVAXUSDT","DOTUSDT","LINKUSDT","LTCUSDT",
        "BCHUSDT","TRXUSDT","ATOMUSDT","UNIUSDT","NEARUSDT","ETCUSDT","XLMUSDT","ALGOUSDT","FILUSDT","ICPUSDT",
        "HBARUSDT","APTUSDT","ARBUSDT","OPUSDT","SUIUSDT","INJUSDT","TIAUSDT","SEIUSDT","DOGEUSDT","MATICUSDT"]
START = 1640995200000      # 2022-01-01

def get(sym):
    p = os.path.join(CACHE, f"{sym}.csv")
    if os.path.exists(p) and (time.time() - os.path.getmtime(p)) < 86400:
        return pd.read_csv(p, index_col=0, parse_dates=True)["close"]
    out, t = [], START
    while True:
        u = f"https://data-api.binance.vision/api/v3/klines?symbol={sym}&interval=1d&limit=1000&startTime={t}"
        raw = None
        for k in range(4):
            try:
                raw = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read()); break
            except Exception:
                time.sleep(1.5 * (k + 1)); raw = None
        if not raw: break
        out += [(int(r[0]), float(r[4])) for r in raw]
        if len(raw) < 1000: break
        t = int(raw[-1][0]) + 86400000
    s = pd.Series({pd.Timestamp(x[0], unit="ms", tz="UTC").tz_localize(None).normalize(): x[1] for x in out}).sort_index()
    s.to_frame("close").to_csv(p)
    return s

px = {}
for s in SYMS:
    try:
        v = get(s); px[s.replace("USDT", "")] = v
        time.sleep(0.08)
    except Exception as e:
        print("skip", s, e)
P = pd.DataFrame(px).loc["2022-01-01":]
P = P.dropna(axis=1, thresh=int(0.6 * len(P)))
print("universe", P.shape, "dari", P.index[0].date(), "ke", P.index[-1].date())
R = P.pct_change(fill_method=None)
score = P.shift(7) / P.shift(97) - 1                       # momentum 90h, lewati 7 hari terakhir
score = score.where(P.notna())

def bt(score: pd.DataFrame, top=5, short=False, vol_target=0.25, cost=0.0010, reb="W-SUN"):
    W = pd.DataFrame(0.0, index=P.index, columns=P.columns)
    rebd = set(P.resample(reb).last().index)
    cur = pd.Series(0.0, index=P.columns)
    for t in P.index:
        if t in rebd:
            s = score.loc[t].dropna().sort_values(ascending=False)
            n = max(2, min(top, len(s) // 5))
            nw = pd.Series(0.0, index=P.columns)
            if len(s) >= n:
                nw[s.index[:n]] = 1.0 / n
                if short and len(s) >= 2 * n: nw[s.index[-n:]] = -1.0 / n
            cur = nw
        W.loc[t] = cur
    Wl = W.shift(1).fillna(0.0)
    vol = (Wl * R).sum(axis=1).rolling(20).std() * math.sqrt(365)
    lev = (vol_target / vol).clip(0.5, 3.0).fillna(1.0)
    E = Wl.mul(lev, axis=0)
    gross = (E.shift(1).fillna(0) * R).sum(axis=1)
    turn = (E - E.shift(1).fillna(0) * (1 + R)).abs().sum(axis=1)
    net = (gross - turn * cost).iloc[1:]
    return net

res = {}
for nm, kw in [("XS_long5", dict(top=5)), ("XS_long10", dict(top=10)), ("XS_ls5", dict(top=5, short=True)),
               ("XS_long5_raw", dict(top=5, vol_target=99.0))]:
    r = bt(score, **kw)
    res[nm] = {"train": stat(r.loc["2022-01-01":"2024-12-31"]), "oos": stat(r.loc["2025-01-01":]),
               "full": stat(r.loc["2022-01-01":])}
    f = res[nm]["full"]; t = res[nm]["train"]; o = res[nm]["oos"]
    print(f"{nm:14s} M={f['M_per5h_pct']:.5f} vol={f['sd_harian_pct']:.2f}% shr={f['sharpe']:.2f} mdd={f['mdd_pct']:.1f} hit30={f['hit30']:.3f} | train {t['M_per5h_pct']:.5f}/{t['hit30']:.3f} | oos {o['M_per5h_pct']:.5f}/{o['hit30']:.3f}")

json.dump({"universe": list(P.columns), "hasil": res, "n_hari": len(P),
           "catatan": "survivorship bias: universe koin yang masih ada; hasil = batas atas"},
          open(os.path.join(HERE, "xs_results.json"), "w"), indent=1)
