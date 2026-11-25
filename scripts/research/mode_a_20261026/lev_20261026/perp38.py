#!/usr/bin/env python3
"""PRAREG-38 — perps SoDEX + leverage, akuntansi modal konsisten.

Fakta venue (dokumen resmi, 26-Okt-2026):
  fee perp taker 4 bps / maker 1,2 bps; spot taker 6,5 / maker 3,5
  funding DIBAYAR TIAP JAM; komponen bunga 0,03%/hari (= 3,0 bps/hari)
  MMR = 50% margin awal pada leverage maksimum -> BTC/ETH 1,25%, XAUT 2,0%
  minNotional $10; BTC step 0,00001; ETH/XAUT step 0,0001

Model modal (bukan "leverage di atas kertas"): E = spot S + margin perp M,
notional perp = M*Lp. Gross = S + M*Lp. Return dihitung terhadap E.
Liquidasi isolated: |pergerakan| >= 1/Lp - MMR (pakai LOW intraday, bukan close).
"""
from __future__ import annotations
import json, math, os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); PARENT = os.path.dirname(HERE)
sys.path.insert(0, PARENT); sys.path.insert(0, os.path.dirname(PARENT)); sys.path.insert(0, HERE)
import lev_study as ls, mode_a_engine as eng
from improve_20261026.simlib import stat

COLS = ["btc", "eth", "xaut"]
MMR = {"btc": 0.0125, "eth": 0.0125, "xaut": 0.02}
FEE_SPOT_T, FEE_PERP_T = 0.00065, 0.00040
FEE_SPOT_M, FEE_PERP_M = 0.00035, 0.00012
FUND_SODEX, FUND_BINANCE, FUND_STRESS = 3.0, 1.79, 4.5     # bps/hari
TARGET = 0.0001                                            # 0,010%/5j

PLAN38 = {
    "sel": {"P1": {"S": 0.75, "M": 0.25, "Lp": 3.0},
            "P2": {"S": 0.60, "M": 0.40, "Lp": 3.0},
            "P3": {"S": 0.85, "M": 0.15, "Lp": 2.0},
            "P4": {"S": 0.75, "M": 0.25, "Lp": 3.0, "voltarget": 0.25}},
    "utama": "P1", "fee": "taker", "funding_bps": FUND_SODEX,
    "alpha_bh": 0.05, "m_sel": 4, "p_bh": 0.0125,
    "train": ["2022-01-01", "2024-12-31"], "oos": ["2025-01-01", None],
    "gerbang": {"G1_M_utama": 0.010, "G2_mdd": -35.0, "G3_likuidasi": 0,
                "G4_lebih_baik_spot": 0.00606, "G5_funding_stress_M": 0.008},
}


def _frames():
    closes_d, ohlc, f = ls.load_all()
    P = pd.DataFrame({k: closes_d[k] for k in COLS}).loc["2021-06-01":]
    lo = pd.DataFrame({k: ohlc[k]["low"] for k in ("btc", "eth")}).reindex(P.index)
    # XAUT tanpa OHLC: pakai rasio low/prev-close PAXG (Binance) sebagai proxy intraday.
    cache = os.path.join(HERE, "paxg_low.csv")
    if os.path.exists(cache):
        pax = pd.read_csv(cache, index_col=0, parse_dates=True).iloc[:, 0].to_frame("ratio")
    else:
        import urllib.request as u
        rows, t = [], 1640995200000
        while True:
            url = f"https://data-api.binance.vision/api/v3/klines?symbol=PAXGUSDT&interval=1d&limit=1000&startTime={t}"
            raw = json.loads(u.urlopen(u.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read())
            rows += raw
            if len(raw) < 1000: break
            t = int(raw[-1][0]) + 86400000
        d = pd.DataFrame([(pd.Timestamp(r[0], unit="ms", tz="UTC").tz_localize(None).normalize(), float(r[3]), float(r[4])) for r in rows],
                         columns=["date", "low", "close"]).set_index("date")
        pax = (d["low"] / d["close"].shift(1)).to_frame("ratio")
        pax.to_csv(cache)
    lo["xaut"] = P["xaut"].shift(1) * pax["ratio"].reindex(P.index).ffill()
    return P, lo.fillna(P.shift(1))


def sim38(P: pd.DataFrame, lo: pd.DataFrame, T: pd.DataFrame, S: float, M: float, Lp: float,
          fee=("taker"), funding=FUND_SODEX, vt=None):
    R = P.pct_change(fill_method=None).fillna(0.0)
    lo_r = (lo / P.shift(1) - 1).fillna(0.0)
    w = T.reindex(P.index).fillna(0.0)[COLS]
    if vt is not None:
        r1 = (w.shift(1) * R).sum(axis=1); volp = r1.rolling(20).std() * math.sqrt(365)
        w = w.mul((vt / volp).clip(1.0, 2.5).fillna(1.0), axis=0)
    fs, fp = (FEE_SPOT_T, FEE_PERP_T) if fee == "taker" else (FEE_SPOT_M, FEE_PERP_M)
    ws, wp = w * S, w * M * Lp
    gross = (ws.shift(1).fillna(0) * R).sum(axis=1) + (wp.shift(1).fillna(0) * R).sum(axis=1)
    turn_s = (ws - ws.shift(1).fillna(0) * (1 + R)).abs().sum(axis=1)
    turn_p = (wp - wp.shift(1).fillna(0) * (1 + R)).abs().sum(axis=1)
    c = turn_s * fs + turn_p * fp
    drag = wp.shift(1).fillna(0).mul(funding / 1e4, axis=0).sum(axis=1)
    # likuidasi per aset pada low intraday; kerugian = margin aset itu (isolated)
    margin = (M / len(COLS)) if M else 0.0
    liq_loss = pd.Series(0.0, index=P.index); n_liq = 0
    thr = 1.0 / Lp - MMR["btc"]
    for k in COLS:
        hit = (lo_r[k] <= -(1.0 / Lp - MMR[k])) & (wp[k].shift(1).fillna(0) > 0)
        # kerugian riil = margin per aset (bukan notional penuh)
        liq_loss += hit * (wp[k].shift(1).fillna(0) / Lp)
        n_liq += int(hit.sum())
    net = (gross - c - drag - liq_loss).iloc[1:]
    eq = (1 + net.clip(lower=-0.999999)).cumprod()
    return pd.DataFrame({"net": net}), float((eq / eq.cummax() - 1).min() * 100), n_liq


def main():
    P, lo = _frames()
    T = eng.target_history({k: P[k] for k in COLS}, mode="B2", validate=False)
    out = {}
    for nm, c in PLAN38["sel"].items():
        df, mdd, nliq = sim38(P, lo, T, c["S"], c["M"], c["Lp"], PLAN38["fee"], PLAN38["funding_bps"], c.get("voltarget"))
        r = df["net"].loc["2022-01-01":]
        s = stat(r); out[nm] = {"full": s, "mdd_sim": round(mdd, 2), "likuidasi": nliq,
                                "train": stat(r.loc[:PLAN38["train"][1]]), "oos": stat(r.loc["2025-01-01":])}
        print(f"{nm:3s} S={c['S']:.2f} M={c['M']:.2f} Lp={c['Lp']:.1f} gross={c['S']+c['M']*c['Lp']:.2f} "
              f"M={s['M_per5h_pct']:.5f} mdd={mdd:6.1f} liq={nliq:3d} hit30={s['hit30']:.3f} "
              f"shr={s['sharpe']:.2f} | tr {out[nm]['train']['M_per5h_pct']:.5f} oos {out[nm]['oos']['M_per5h_pct']:.5f}")
    sens = {}
    for nm, fu, fe in [("funding_binance", FUND_BINANCE, "taker"), ("funding_stress", FUND_STRESS, "taker"),
                       ("maker", FUND_SODEX, "maker")]:
        c = PLAN38["sel"]["P1"]; df, mdd, nl = sim38(P, lo, T, c["S"], c["M"], c["Lp"], fe, fu)
        sens[nm] = stat(df["net"].loc["2022-01-01":])
        print(f"SENS {nm:16s} M={sens[nm]['M_per5h_pct']:.5f} mdd={mdd:.1f} liq={nl}")
    json.dump({"plan": PLAN38, "hasil": out, "sensitivitas": sens},
              open(os.path.join(HERE, "perp38_results.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
