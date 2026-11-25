#!/usr/bin/env python3
"""SODEX H5 -- uji mean-reversion pasca-breakout pada SoDEX (READ-ONLY).

Pra-registrasi BEKU: docs/sodex/SODEX_ALT2_H5_PRAREG_2026-10-07.md
Jangan ubah ambang/arah setelah melihat hasil.

Hipotesis: breakout ekstrem BALIK ARAH (fade), bukan ikut tren.
  FADE_BREAKDOWN (LONG) : close < min(low,30) & vol >= 1.5x median(vol,30)
  FADE_BREAKOUT  (SHORT): close > max(high,30) & vol >= 1.5x median(vol,30)
Arah dipilih pasca-hoc dari hasil Binance -> uji ini uji VENUE INDEPENDEN, bukan
uji prospektif murni (diakui di pra-registrasi §1).

Kontrol negatif memakai ulang rand_entry_p() dari binance_alt_top4_study (sudah divalidasi
6 tes, sign-aware). Harness itu WAJIB lulus sebelum hasil ini dipercaya.

Pakai: python3 scripts/sodex_h5_meanrev_study.py [--nperm 1000]
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from binance_alt_top4_study import agg_stats, rand_entry_p  # noqa: E402

MIN_DIR = ROOT / "scratch/sodex_minutes"
OUT = ROOT / "reports/sodex"
SYMS = ["BTC-USD", "ETH-USD", "SOL-USD"]
FEE_RT, FEE_STRESS = 0.0008, 1.5     # SoDEX taker 4bp/leg -> 8bp RT; uji 1,5x = 12bp
HORIZONS = (1, 2, 6, 12)
H_PRIMARY = 12
PASS = {"n_min": 100, "p_max": 0.05, "single_sym_share": 0.30, "q_fdr": 0.10}


def load_4h() -> pd.DataFrame:
    fs = sorted(glob.glob(str(MIN_DIR / "day=*.parquet")))
    if not fs:
        raise SystemExit(f"tidak ada bar-menit di {MIN_DIR}. Jalankan scripts/sodex_build_minutes.py.")
    d = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
    d = d[d["sym"].isin(SYMS)].copy()
    d = d.sort_values(["sym", "minute"])          # WAJIB: file urut menurun
    d["bar4"] = (d["minute"] // 240).astype("int64")
    b = d.groupby(["sym", "bar4"], sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("notional", "sum"), n=("n", "sum")).reset_index()
    b["day"] = (b["bar4"] // 6).astype("int64")
    return b.sort_values(["sym", "bar4"]).reset_index(drop=True)


def add_fwd(b: pd.DataFrame, h: int) -> pd.DataFrame:
    b = b.sort_values(["sym", "bar4"]).copy()
    g = b.groupby("sym", sort=False)
    b["entry"] = g["open"].shift(-1)
    b["exit"] = g["close"].shift(-h)
    b["fwd"] = b["exit"] / b["entry"] - 1.0
    return b


def run(b: pd.DataFrame, nperm: int) -> dict:
    out = {"meta": {"symbols": SYMS, "bars4h": int(len(b)),
                    "range": [int(b.bar4.min()), int(b.bar4.max())],
                    "nperm": nperm, "fee_rt": FEE_RT, "h_primary": H_PRIMARY, "pass": PASS}}
    tests = []
    for h in HORIZONS:
        x = add_fwd(b, h)
        g = x.groupby("sym", sort=False)
        x["hi30"] = g["high"].transform(lambda s: s.rolling(30, min_periods=10).max().shift(1))
        x["lo30"] = g["low"].transform(lambda s: s.rolling(30, min_periods=10).min().shift(1))
        x["vmed"] = g["volume"].transform(lambda s: s.rolling(30, min_periods=10).median().shift(1))
        x["relvol"] = np.where(x["vmed"] > 0, x["volume"] / x["vmed"], 0.0)
        pool = x[x["fwd"].notna()].copy()
        trig = x["relvol"] >= 1.5
        legs = (("FADE_BREAKDOWN", (x["close"] < x["lo30"]) & trig, 1),
                ("FADE_BREAKOUT", (x["close"] > x["hi30"]) & trig, -1))
        for name, m, sign in legs:
            s = x[m & x["fwd"].notna()].copy()
            if s.empty:
                out[f"h{h}_{name}"] = {"n": 0}
                continue
            s["net"] = sign * s["fwd"] - FEE_RT
            s["stress"] = sign * s["fwd"] - FEE_RT * FEE_STRESS
            v = agg_stats(s["net"].to_numpy())
            v["mean_stress_bp"] = float(s["stress"].mean() * 1e4)
            v["p_random"] = rand_entry_p(s, pool, nperm, sign=sign)
            tot = s.groupby("sym")["net"].sum()
            v["by_sym"] = {k: round(float(x2), 2) for k, x2 in tot.items()}
            v["top_sym"] = tot.idxmax() if len(tot) else None
            v["top_sym_share"] = float(tot.max() / tot.sum()) if len(tot) and tot.sum() else None
            v["days"] = int(s["day"].nunique())
            out[f"h{h}_{name}"] = v
            if h == H_PRIMARY:
                tests.append((f"h{h}_{name}", v["p_random"]))
    out["BH_FDR"] = bh_fdr(tests)
    out["VERDICT"] = verdict_h5(out)
    return out


def bh_fdr(pairs, q=PASS["q_fdr"]):
    ps = [(n, p) for n, p in pairs if p == p]
    ps.sort(key=lambda x: x[1])
    m, kmax = len(ps), 0
    for i, (_, p) in enumerate(ps, 1):
        if p <= q * i / m:
            kmax = i
    return [{"name": n, "p": p, "pass_bh": i <= kmax} for i, (n, p) in enumerate(ps, 1)]


def verdict_h5(out: dict) -> dict:
    """Terapkan §3 pra-registrasi. KEDUA sisi wajib lulus c1-c5 pada H=12."""
    legs = {}
    for name in ("FADE_BREAKDOWN", "FADE_BREAKOUT"):
        k = f"h{H_PRIMARY}_{name}"
        v = out.get(k, {})
        n = v.get("n") or 0
        net = v.get("mean_net_bp")
        stp = v.get("mean_stress_bp")
        p = v.get("p_random")
        share = v.get("top_sym_share")
        c1 = n >= PASS["n_min"]
        c2 = (net or 0) > 0
        c3 = (stp or 0) > 0
        c4 = p is not None and p == p and p < PASS["p_max"]
        c5 = share is not None and share == share and abs(share) <= PASS["single_sym_share"]
        legs[name] = {"n": n, "net_bp": net, "stress_bp": stp, "p": p,
                      "top_sym": v.get("top_sym"), "top_share": share, "days": v.get("days"),
                      "c1_n": c1, "c2_net": c2, "c3_stress": c3, "c4_p": c4, "c5_conc": c5,
                      "gagal": [k2 for k2, ok in (("c1_n", c1), ("c2_net", c2), ("c3_stress", c3),
                                                  ("c4_p", c4), ("c5_conc", c5)) if not ok]}
    if not all(v["c1_n"] for v in legs.values()):
        hasil = "BELUM CUKUP BUKTI"
    elif all(not v["gagal"] for v in legs.values()):
        hasil = "LULUS"
    else:
        hasil = "GAGAL"
    return {"hasil": hasil, "sisi": legs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nperm", type=int, default=1000)
    a = ap.parse_args()
    b = load_4h()
    print(f"bar 4H: {len(b):,} | simbol: {sorted(b.sym.unique())} | hari: {b.day.nunique()}")
    out = run(b, a.nperm)
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"sodex_h5_meanrev_{pd.Timestamp.now():%Y%m%d}.json"
    dest.write_text(json.dumps(out, indent=1, default=str))
    print(f"hasil -> {dest}\n")
    print(f"{'varian':26s} {'n':>6s} {'net(bp)':>9s} {'stress':>9s} {'WR':>6s} {'p':>7s} {'hari':>5s}  simbol dominan")
    for h in HORIZONS:
        for nm in ("FADE_BREAKDOWN", "FADE_BREAKOUT"):
            v = out.get(f"h{h}_{nm}", {})
            if not v.get("n"):
                print(f"h{h}_{nm:22s}   (nol episode)")
                continue
            print(f"h{h:<2d}_{nm:21s} {v['n']:6d} {v['mean_net_bp']:9.2f} "
                  f"{v.get('mean_stress_bp', float('nan')):9.2f} {v['wr']:6.1%} "
                  f"{v.get('p_random', float('nan')):7.3f} {v.get('days', 0):5d}  "
                  f"{v.get('top_sym')}({v.get('top_sym_share') or 0:.0%})")
    print("\n═══ VERDICT H5 (horizon primer 48 jam) ═══")
    vd = out["VERDICT"]
    print(f"HASIL: {vd['hasil']}")
    for nm, v in vd["sisi"].items():
        print(f"  {nm:16s} n={v['n']:4d} net={v['net_bp']} bp p={v['p']} "
              f"gagal={v['gagal'] or 'tidak ada'}")
    print("\n═══ BH-FDR q=0,10 (8 uji) ═══")
    for r in out["BH_FDR"]:
        print(f"  {'PASS' if r['pass_bh'] else '  - '} {r['name']:24s} p={r['p']:.4f}")


if __name__ == "__main__":
    main()
