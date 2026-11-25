#!/usr/bin/env python3
"""Uji alternatif Top-4 FINAL pada data SoDEX sendiri (READ-ONLY).

Pra-registrasi: docs/sodex/SODEX_ALT_TOP4_PRAREG_2026-10-07.md  (ambang BEKU).
Acuan: ANANTARA_SoDEX_Swing_Strategies_FINAL_V1.html (5 Okt 2026) Top-4.

Hipotesis yang diuji di sini:
  H1 = #1 External-Regime Adaptive Trend/Breakout
  H2 = #2 Global Order Flow + SoDEX Confirmation (ladder M1: arus lokal SoDEX)
  H4 = #4 Risk-Managed Regime Momentum
(#3 ProSP dan varian global #2 M2/M3 TIDAK diuji di sini -- lihat pra-registrasi §1.)

Kontrol negatif: RANDOM-ENTRY. Untuk setiap (simbol, hari) dengan k sinyal, ambil k bar acak di
hari yang sama -> distribusi nol. Ini menguji apakah TIMING sinyal menambah nilai, atau hasilnya
sekadar drift pasar (long bias) yang bisa didapat entry acak kapan saja.

READ-ONLY: hanya membaca cache bar-menit. Tidak menyentuh gate/ambang/posisi/konfigurasi.
Pakai: python3 scripts/sodex_alt_top4_study.py [--hyp H1|H2|H4] [--nperm 1000]
"""
from __future__ import annotations
import argparse
import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "scratch/sodex_minutes"
OUT = ROOT / "reports/sodex"

# --- ambang BEKU (pra-registrasi) -------------------------------------------------
IS_END, OOS_START = "20260825", "20260826"
FEE_RT = 0.0008          # taker 4bp/leg -> round trip 8bp
FEE_STRESS = 1.5         # uji ketahanan 1,5x biaya
LIQ_MIN_USD = 50_000.0   # median notional harian 30 hari (point-in-time)
LIQ_LOOKBACK = 30
BARS_PER_DAY = {"4H": 6, "1D": 1}
PASS = {"n_min": 100, "p_max": 0.05, "single_sym_share": 0.30}


def load_minutes() -> pd.DataFrame:
    fs = sorted(glob.glob(str(CACHE / "*.parquet")))
    if not fs:
        raise SystemExit(f"cache kosong: {CACHE}. Jalankan scripts/sodex_build_minutes.py dulu.")
    cols = ["sym", "minute", "open", "high", "low", "close", "notional", "buy_qty", "sell_qty"]
    df = pd.concat((pd.read_parquet(f, columns=cols) for f in fs), ignore_index=True)
    df["bar4h"] = df["minute"] // 240
    df["day"] = (df["minute"] // 1440).astype("int64")
    return df


def to_bars(df: pd.DataFrame, key: str) -> pd.DataFrame:
    """Agregasi bar dari menit. key = 'bar4h' atau 'day'."""
    g = df.groupby(["sym", key], sort=True)
    b = g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
              close=("close", "last"), notional=("notional", "sum"),
              bq=("buy_qty", "sum"), sq=("sell_qty", "sum")).reset_index()
    b["vol"] = b["bq"] + b["sq"]
    b["ofi"] = np.where(b["vol"] > 0, (b["bq"] - b["sq"]) / b["vol"], 0.0)
    b["date"] = b[key].astype("int64")
    mins = 240 if key == "bar4h" else 1440
    b["ymd"] = pd.to_datetime(b["date"] * mins, unit="m").dt.strftime("%Y%m%d")
    b["day"] = (b["date"] * mins) // 1440
    return b.sort_values(["sym", "date"]).reset_index(drop=True)


def liquidity_mask(bars4h: pd.DataFrame) -> pd.DataFrame:
    """Point-in-time: simbol layak pada hari d bila median notional harian 30 hari terakhir >= ambang."""
    dl = (bars4h.groupby(["sym", "day"], sort=True)["notional"].sum().reset_index())
    dl = dl.sort_values(["sym", "day"])
    dl["med30"] = (dl.groupby("sym")["notional"]
                     .transform(lambda s: s.rolling(LIQ_LOOKBACK, min_periods=10).median()))
    dl["ok"] = dl["med30"] >= LIQ_MIN_USD
    return dl[["sym", "day", "ok"]]


def add_forward(b: pd.DataFrame, h: int) -> pd.DataFrame:
    """Entry = open bar t+1; exit = close bar t+1+h-1. Return LONG (SHORT = kebalikannya)."""
    b = b.sort_values(["sym", "date"]).copy()
    g = b.groupby("sym", sort=False)
    b["entry"] = g["open"].shift(-1)
    b["exit"] = g["close"].shift(-h)
    b["fwd"] = b["exit"] / b["entry"] - 1.0
    return b


def stats(net: np.ndarray) -> dict:
    if len(net) == 0:
        return {"n": 0}
    return {"n": int(len(net)), "mean_net": float(net.mean()),
            "median_net": float(np.median(net)), "wr": float((net > 0).mean()),
            "mean_gross": float(net.mean() + FEE_RT), "sum_net": float(net.sum())}


def random_entry_p(sel: pd.DataFrame, pool: pd.DataFrame, nperm: int, seed=42) -> float:
    """Kontrol negatif: timing sinyal vs entry acak di (simbol, hari) yang sama."""
    if sel.empty:
        return float("nan")
    keys = sel.groupby(["sym", "day"]).size().rename("k").reset_index()
    pool_idx = {k: v["fwd"].to_numpy() for k, v in pool.groupby(["sym", "day"])}
    valid = [(r.sym, r.day, int(r.k)) for r in keys.itertuples()
             if (r.sym, r.day) in pool_idx and len(pool_idx[(r.sym, r.day)]) > 0]
    if not valid:
        return float("nan")
    obs = sel["fwd"].mean()
    rng = np.random.default_rng(seed)
    cnt = 0
    for _ in range(nperm):
        tot, nn = 0.0, 0
        for s, d, k in valid:
            arr = pool_idx[(s, d)]
            pick = rng.choice(arr, size=min(k, len(arr)), replace=False)
            tot += pick.sum()
            nn += len(pick)
        if nn and tot / nn >= obs:
            cnt += 1
    return (cnt + 1) / (nperm + 1)


# ----------------------------------------------------------------------------- H1
def h1(b4: pd.DataFrame, liq: pd.DataFrame, horizons=(1, 2, 6, 12)) -> dict:
    """#1 Breakout: global regime BTC 4H + new 30-bar high + relvol>=1.5."""
    b = b4.copy()
    g = b.groupby("sym", sort=False)
    b["hi30"] = g["high"].transform(lambda s: s.rolling(30, min_periods=10).max().shift(1))
    b["lo30"] = g["low"].transform(lambda s: s.rolling(30, min_periods=10).min().shift(1))
    b["vmed"] = g["vol"].transform(lambda s: s.rolling(30, min_periods=10).median().shift(1))
    b["relvol"] = np.where(b["vmed"] > 0, b["vol"] / b["vmed"], 0.0)
    b = b.merge(liq, on=["sym", "day"], how="left")
    b["ok"] = b["ok"].fillna(False)
    # regime global dari BTC
    btc = b[b["sym"] == "BTC-USD"].sort_values("date")[["date", "close"]].copy()
    btc["slope6"] = btc["close"] / btc["close"].shift(6) - 1.0
    b = b.merge(btc[["date", "slope6"]], on="date", how="left")
    b["up"] = b["slope6"] > 0
    b["dn"] = b["slope6"] < 0
    res = {}
    for h in horizons:
        b = add_forward(b.drop(columns=[c for c in ("entry", "exit", "fwd") if c in b]), h)
        lg = b["ok"] & b["up"] & (b["close"] > b["hi30"]) & (b["relvol"] >= 1.5)
        sh = b["ok"] & b["dn"] & (b["close"] < b["lo30"]) & (b["relvol"] >= 1.5)
        rows = []
        pool_all = b[b["ok"] & b["fwd"].notna()]          # semua bar layak -> basis entry acak
        for tag, m in (("LONG", lg), ("SHORT", sh)):
            sub = b[m & b["fwd"].notna()].copy()
            sub["net"] = np.where(tag == "LONG", sub["fwd"] - FEE_RT, -sub["fwd"] - FEE_RT)
            sub["seg"] = np.where(sub["ymd"] <= IS_END, "IS", "OOS")
            for seg in ("IS", "OOS"):
                s = sub[sub["seg"] == seg]
                res[f"h{h}_{tag}_{seg}"] = stats(s["net"].to_numpy())
                if seg == "OOS" and len(s):
                    res[f"h{h}_{tag}_{seg}"]["p_random"] = random_entry_p(
                        s, pool_all, nperm=RES["nperm"])
                    stress = (np.where(tag == "LONG", s["fwd"] - FEE_RT * FEE_STRESS,
                                       -s["fwd"] - FEE_RT * FEE_STRESS))
                    res[f"h{h}_{tag}_{seg}"]["mean_net_stress"] = float(stress.mean())
                    top = s.groupby("sym")["net"].sum().sort_values(ascending=False)
                    res[f"h{h}_{tag}_{seg}"]["top_sym"] = (top.index[0] if len(top) else None)
                    res[f"h{h}_{tag}_{seg}"]["top_sym_share"] = (
                        float(top.iloc[0] / top.sum()) if len(top) and top.sum() != 0 else None)
        res[f"h{h}"] = "ok"
    return res


# ----------------------------------------------------------------------------- H2
def h2(b4: pd.DataFrame, liq: pd.DataFrame, horizons=(2, 3, 6)) -> dict:
    """#2 M1: OFI 4H desil ekstrem lintas-simbol -> long top / short bottom."""
    b = b4.merge(liq, on=["sym", "day"], how="left")
    b["ok"] = b["ok"].fillna(False)
    b["ofi_prev"] = b.groupby("sym", sort=False)["ofi"].shift(1)          # pakai bar t-1 (tutup)
    res = {}
    for h in horizons:
        b = add_forward(b.drop(columns=[c for c in ("entry", "exit", "fwd") if c in b]), h)
        pool = b[b["ok"] & b["fwd"].notna() & b["ofi_prev"].notna()].copy()
        if pool.empty:
            res[f"h{h}"] = {"n": 0}
            continue
        g = pool.groupby("date", sort=False)["ofi_prev"]
        pool["dec_hi"] = g.transform(lambda s: s >= s.quantile(0.90))
        pool["dec_lo"] = g.transform(lambda s: s <= s.quantile(0.10))
        rows = []
        for tag, m in (("LONG", pool["dec_hi"]), ("SHORT", pool["dec_lo"])):
            sub = pool[m].copy()
            sub["net"] = np.where(tag == "LONG", sub["fwd"] - FEE_RT, -sub["fwd"] - FEE_RT)
            sub["seg"] = np.where(sub["ymd"] <= IS_END, "IS", "OOS")
            for seg in ("IS", "OOS"):
                s = sub[sub["seg"] == seg]
                res[f"h{h}_{tag}_{seg}"] = stats(s["net"].to_numpy())
                if seg == "OOS" and len(s):
                    res[f"h{h}_{tag}_{seg}"]["p_random"] = random_entry_p(s, pool, RES["nperm"])
                    stress = np.where(tag == "LONG", s["fwd"] - FEE_RT * FEE_STRESS,
                                      -s["fwd"] - FEE_RT * FEE_STRESS)
                    res[f"h{h}_{tag}_{seg}"]["mean_net_stress"] = float(stress.mean())
                    top = s.groupby("sym")["net"].sum().sort_values(ascending=False)
                    res[f"h{h}_{tag}_{seg}"]["top_sym"] = (top.index[0] if len(top) else None)
                    res[f"h{h}_{tag}_{seg}"]["top_sym_share"] = (
                        float(top.iloc[0] / top.sum()) if len(top) and top.sum() != 0 else None)
                if seg == "IS" and len(s):
                    top = s.groupby("sym")["net"].sum().sort_values(ascending=False)
                    res[f"h{h}_{tag}_{seg}"]["top_sym"] = (top.index[0] if len(top) else None)
        res[f"h{h}"] = "ok"
    return res


RES = {"nperm": 500}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hyp", default="ALL")
    ap.add_argument("--nperm", type=int, default=500)
    args = ap.parse_args()
    RES["nperm"] = args.nperm
    if not CACHE.exists():
        raise SystemExit(f"cache kosong: {CACHE}")
    df = load_minutes()
    print(f"bar-menit dimuat: {len(df):,} baris, {df.sym.nunique()} simbol")
    b4 = to_bars(df, "bar4h")
    print(f"bar 4H: {len(b4):,} | rentang {b4.ymd.min()}..{b4.ymd.max()}")
    liq = liquidity_mask(b4)
    print(f"eligibilitas likuid: {liq.ok.mean():.1%} baris-simbol OK "
          f"({liq[liq.ok].sym.nunique()} simbol pernah layak)")
    out = {"meta": {"cache_rows": int(len(df)), "bars4h": int(len(b4)),
                    "nperm": args.nperm, "fee_rt": FEE_RT, "pass": PASS}}
    if args.hyp in ("ALL", "H1"):
        out["H1"] = h1(b4, liq)
    if args.hyp in ("ALL", "H2"):
        out["H2"] = h2(b4, liq)
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"sodex_alt_top4_{pd.Timestamp.now():%Y%m%d}.json"
    dest.write_text(json.dumps(out, indent=1, default=str))
    print(f"\nhasil -> {dest}")
    for hyp in ("H1", "H2"):
        if hyp not in out:
            continue
        print(f"\n═══ {hyp} ═══")
        for k in sorted(out[hyp]):
            v = out[hyp][k]
            if not isinstance(v, dict) or "n" not in v or not v["n"]:
                continue
            if not k.endswith("OOS"):
                continue
            print(f"{k:14s} n={v['n']:5d} mean_net={v['mean_net']*1e4:8.2f}bp "
                  f"WR={v['wr']:.1%} stress={v.get('mean_net_stress', float('nan'))*1e4:8.2f}bp "
                  f"p_rand={v.get('p_random', float('nan')):.3f} topsym={v.get('top_sym')}")
    print(f"\nhasil lengkap: {dest}")


if __name__ == "__main__":
    main()
