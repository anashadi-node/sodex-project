#!/usr/bin/env python3
"""ANGGARAN BREADTH SoDEX — Hukum Fundamental diterapkan ke venue.

Sharpe_ann = IC x sqrt(breadth),  breadth = N_eff x (periode/tahun).

Pertanyaan yang dijawab:
  Berapa IC yang DIBUTUHKAN agar satu mesin Sharpe_ann = 2,3 di venue ini,
  mengingat N_eff (taruhan independen) yang tersedia?
  Bandingkan dengan IC yang BENAR-BENAR terukur dari data.

Jalankan: /usr/bin/python3 scripts/research/sodex_breadth_budget.py
"""
from __future__ import annotations

import glob
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.expanduser("~/anantara-sakti")
KL = os.path.join(ROOT, "data", "sodex_klines", "1d")


def load() -> pd.DataFrame:
    cols = {}
    for f in sorted(glob.glob(os.path.join(KL, "*.json"))):
        s = os.path.basename(f)[:-5]
        if s == "MANIFEST":
            continue
        try:
            d = json.load(open(f))
        except Exception:
            continue
        bars = d.get("bars") or []
        if len(bars) < 60:
            continue
        idx = pd.to_datetime([b["t"] for b in bars], unit="ms", utc=True).normalize()
        cols[s] = pd.Series([float(b["c"]) for b in bars], index=idx)
    return pd.DataFrame(cols).sort_index()


def stats(ret: pd.DataFrame, min_avail: float) -> dict:
    sub = ret.dropna(axis=1, thresh=int(min_avail * len(ret))).dropna()
    if sub.shape[1] < 5 or len(sub) < 20:
        return {}
    C = sub.corr().to_numpy()
    iu = np.triu_indices_from(C, k=1)
    p = C[iu]
    p = p[np.isfinite(p)]
    ev = np.clip(np.linalg.eigvalsh(np.nan_to_num(C, nan=0.0)), 0, None)
    n_eff = float((ev.sum() ** 2) / (ev ** 2).sum()) if (ev ** 2).sum() > 0 else float("nan")
    return {"n_sym": int(sub.shape[1]), "n_days": int(len(sub)),
            "rho_mean": float(np.nanmean(p)), "rho_median": float(np.nanmedian(p)),
            "pc1": float(ev[-1] / ev.sum()), "n_eff": n_eff,
            "idiosyncratic_share": 1.0 - float(np.nanmean(p))}


def main() -> int:
    px = load()
    ret = np.log(px / px.shift()).replace([np.inf, -np.inf], np.nan).dropna(how="all")
    print(f"panel SoDEX 1d: {px.shape[1]} simbol x {len(px)} hari")
    rows = []
    for win in (90, 180, 365):
        r = ret.tail(win)
        for avail in (0.95, 0.8, 0.6):
            s = stats(r, avail)
            if s:
                s["window"] = win
                s["min_avail"] = avail
                rows.append(s)
    df = pd.DataFrame(rows).drop_duplicates(subset=["window", "min_avail"])
    print(f"\n{'win':>5}{'avail':>7}{'n_sym':>7}{'n_day':>7}{'rho_mean':>10}{'rho_med':>9}"
          f"{'pc1':>7}{'N_eff':>7}{'idio':>7}")
    for _, r in df.iterrows():
        print(f"{int(r['window']):>5}{r['min_avail']:>7.2f}{int(r['n_sym']):>7}{int(r['n_days']):>7}"
              f"{r['rho_mean']:>10.3f}{r['rho_median']:>9.3f}{r['pc1']:>7.3f}"
              f"{r['n_eff']:>7.2f}{r['idiosyncratic_share']:>7.3f}")

    # ── anggaran IC: Sharpe = IC * sqrt(N_eff * (365/H)) ──
    print("\n=== ANGGARAN IC: IC yang DIBUTUHKAN untuk Sharpe_ann = 2,3 ===")
    print(f"{'N_eff':>7}{'H=2h(182/th)':>15}{'H=5h(73/th)':>15}{'IC terukur':>13}{'rasio':>9}")
    # IC terukur terbaik dari uji lintas-seksi 1d (eksploratori): |IC| ~ 0,036
    IC_OBS = 0.036
    for ne in (2.32, 5, 10, 20, 40, 76):
        for label, freq in (("H=2h(182/th)", 182.0), ("H=5h(73/th)", 73.0)):
            pass
        b2 = ne * 182.0
        b5 = ne * 73.0
        ic2 = 2.3 / np.sqrt(b2)
        ic5 = 2.3 / np.sqrt(b5)
        print(f"{ne:>7.2f}{ic2:>15.4f}{ic5:>15.4f}{IC_OBS:>13.4f}{IC_OBS/ic2:>9.2f}x")

    # ── plafon diversifikasi antar mesin ──
    print("\n=== PLAFON DIVERSIFIKASI (batas atas pengali Sharpe) ===")
    for rho in (0.10, 0.30, 0.605):
        best = 1.0 / np.sqrt(rho) if rho > 0 else float("inf")
        six = np.sqrt(6.0 / (1.0 + 5.0 * rho))
        print(f"  rho_PnL={rho:.3f}: n=6 -> {six:.2f}x | n->inf -> {best:.2f}x "
              f"| Sharpe mesin yang dibutuhkan utk portofolio 4,60: {4.60/six:.2f}")
    print("\n  Catatan: untuk mesin dollar-neutral, rho_PnL ditentukan TUMPANG TINDIH BOBOT,")
    print("  bukan korelasi aset. Korelasi aset 0,60 menghapus dirinya sendiri di selisih")
    print("  long-short — tetapi ia juga memangkas kolam dispersi (hanya bagian idiosinkratik).")

    out = {"panel": {"n_symbols": int(px.shape[1]), "n_days": int(len(px))},
           "windows": rows, "ic_observed_exploratory": IC_OBS,
           "ic_needed_sharpe23": {f"n_eff_{ne}": {"H2": 2.3 / np.sqrt(ne * 182.0),
                                                  "H5": 2.3 / np.sqrt(ne * 73.0)}
                                  for ne in (2.32, 5, 10, 20, 40, 76)}}
    d = os.path.join(ROOT, "reports", "sodex")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "ANGGARAN_BREADTH_SODEX.json")
    with open(p, "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(f"\nberkas: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
