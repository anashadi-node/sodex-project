#!/usr/bin/env python3
"""PRAREG-4 — RANGEPOS rank-proporsional di panel SoDEX 1h. Implementasi BEKU.

Protokol: docs/sodex/SODEX_PRAREG4_RANGEPOS_SODEX_1H_2026-10-07.md  (commit 2a8fcdf)

PENTING — BACA SEBELUM MENAFSIRKAN KELUARAN:
  Jendela SoDEX 1h SUDAH TERPAKAI (PRAREG-2 memakai 63 dari nama yang sama, jendela sama).
  Karena itu angka dari skrip ini adalah **DESKRIPTIF** — sah dilaporkan, TIDAK sah dipakai
  sebagai verdict lulus/gagal. Verdict yang sah hanya dari data FORWARD.
  Skrip ini mencetak penanda itu sendiri supaya tidak bisa dilupakan.

Amendemen pra-reg hanya boleh MEMPERKETAT. Tidak ada parameter di berkas ini yang boleh
diubah setelah melihat hasil.

Jalankan: .venv-research/bin/python3 scripts/research/rangepos_sodex_1h_prereg4.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xsec_mech_study as xms  # noqa: E402
from xsec_mech_study import (  # noqa: E402
    ROOT, _sodex_panel, run_mech, bh_fdr, FEE_ONEWAY, MIN_NAMES,
)

# ─────────── SPESIFIKASI BEKU (§3 pra-reg) ───────────
LOOKBACK = 20                     # range_position(px, 20) — verbatim PRAREG-2
HOLDS = (1, 2, 4, 8, 12, 24, 48)  # 7 sel, dibekukan
PPY_HOURLY = 365.0 * 24.0         # bar 1 jam
FEE_MULT_STRESS = 2.0
FEE_MULT_REAL = 9.71 / 8.0        # ≈1,215 → 9,71 bps round-trip
Q_FDR = 0.10                      # BH-FDR atas 7 sel
SEED = 20261007
T_MIN = 2.0                       # ambang t_NW
SEG_MIN_OK = 2                    # seg+ >= 2 dari 3


def range_position(px: pd.DataFrame, n: int) -> pd.DataFrame:
    """+(close − lo_n)/(hi_n − lo_n) : dekat 1 = dekat puncak. Verbatim PRAREG-2."""
    hi, lo = px.rolling(n).max(), px.rolling(n).min()
    rng = (hi - lo).replace(0, np.nan)
    return (px - lo) / rng


def evaluate(px: pd.DataFrame, sig: pd.DataFrame, hold: int) -> dict:
    ret = px.pct_change()
    r1 = run_mech(px, ret, sig, hold, FEE_ONEWAY, 1.0)
    if not r1.get("n"):
        return {"n": 0}
    r2 = run_mech(px, ret, sig, hold, FEE_ONEWAY, FEE_MULT_STRESS)
    rr = run_mech(px, ret, sig, hold, FEE_ONEWAY, FEE_MULT_REAL)
    # C-a: acak-dalam-baris (kontrol bawaan harness)
    ca = run_mech(px, ret, sig, hold, FEE_ONEWAY, 1.0, control=True)
    # C-b: sinyal acak penuh (mengukur artefak konstruksi portofolio)
    rng = np.random.default_rng(SEED)
    sig_rand = pd.DataFrame(rng.random(sig.shape), index=sig.index, columns=sig.columns)
    sig_rand = sig_rand.where(sig.notna())
    cb = run_mech(px, ret, sig_rand, hold, FEE_ONEWAY, 1.0)
    gross = r1["mean_bps_per_period"] + r1["fee_bps"]
    ca_gross = ca["mean_bps_per_period"] + ca["fee_bps"] if ca.get("n") else float("nan")
    cb_gross = cb["mean_bps_per_period"] + cb["fee_bps"] if cb.get("n") else float("nan")
    return {
        "hold": hold, "n": r1["n"], "names_med": r1["names_med"],
        "gross_bps": gross, "net_bps": r1["mean_bps_per_period"],
        "sd_bps": r1["sd_bps_per_period"], "sharpe": r1["sharpe_annual"],
        "t_nw": r1["t_nw"], "p": r1["p"], "ic": r1["ic_mean"],
        "turnover": r1["turnover"], "fee_bps": r1["fee_bps"],
        "seg+": r1["segments_positive"], "segments": r1["segments"],
        "winrate": r1["winrate"],
        "net_bps_2x": r2["mean_bps_per_period"], "sharpe_2x": r2["sharpe_annual"],
        "net_bps_real": rr["mean_bps_per_period"], "sharpe_real": rr["sharpe_annual"],
        "ctrl_shuffle_gross": ca_gross, "ctrl_random_gross": cb_gross,
    }


def synthetic_panel(n_rows: int, n_cols: int, seed: int) -> pd.DataFrame:
    """Random walk berukuran sama — kontrol C-c. Wajib TIDAK lulus."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0, 0.01, size=(n_rows, n_cols))
    return pd.DataFrame(100.0 * np.exp(np.cumsum(steps, axis=0)))


def main() -> int:
    print("=" * 112)
    print("PRAREG-4 — RANGEPOS RANK-PROPORSIONAL, panel SoDEX 1h (100 nama)")
    print(">>> ANGKA DI BAWAH = DESKRIPTIF. BUKAN VERDICT. Jendela sudah terpakai.")
    print(">>> Verdict yang sah hanya dari data FORWARD (pra-reg §6).")
    print("=" * 112)

    xms.PPY = PPY_HOURLY
    px = _sodex_panel("1h")
    if px.empty or len(px) < 120:
        print(f"panel terlalu kecil ({len(px)}) — berhenti")
        return 1
    print(f"\npanel: {px.shape[1]} nama x {len(px)} bar | "
          f"{px.index[0]} -> {px.index[-1]} | PPY={PPY_HOURLY:.0f} | lookback={LOOKBACK}")
    sig = range_position(px, LOOKBACK)

    out = {
        "disclaimer": "DESKRIPTIF — jendela historis sudah terpakai; bukan verdict.",
        "protocol": "docs/sodex/SODEX_PRAREG4_RANGEPOS_SODEX_1H_2026-10-07.md",
        "prereg_commit": "2a8fcdf",
        "panel": {"names": int(px.shape[1]), "bars": int(len(px)),
                  "start": str(px.index[0]), "end": str(px.index[-1])},
        "frozen": {"lookback": LOOKBACK, "holds": list(HOLDS), "ppy": PPY_HOURLY,
                   "fee_oneway": FEE_ONEWAY, "q_fdr": Q_FDR, "seed": SEED,
                   "min_names": MIN_NAMES, "t_min": T_MIN, "seg_min": SEG_MIN_OK},
        "cells": [], "controls": {},
    }

    print(f"\n  {'hold':>5}{'n':>6}{'nama':>6}{'bruto':>9}{'net1x':>9}{'netreal':>9}"
          f"{'net2x':>9}{'to':>7}{'fee':>7}{'S_ann':>8}{'t_NW':>7}{'p':>8}{'seg+':>5}{'WR':>7}")
    cells = []
    for h in HOLDS:
        r = evaluate(px, sig, h)
        if not r.get("n"):
            print(f"  {h:>5}  (n=0 — dilewati)")
            continue
        cells.append(r)
        print(f"  {h:>5}{r['n']:>6}{r['names_med']:>6}{r['gross_bps']:>9.2f}"
              f"{r['net_bps']:>9.2f}{r['net_bps_real']:>9.2f}{r['net_bps_2x']:>9.2f}"
              f"{r['turnover']:>7.2f}{r['fee_bps']:>7.2f}{r['sharpe']:>8.2f}"
              f"{r['t_nw']:>7.2f}{r['p']:>8.4f}{str(r['seg+']):>5}{r['winrate']:>7.3f}")

    # BH-FDR atas seluruh sel grid
    pv = {f"H{c['hold']}": c["p"] for c in cells}
    passed = bh_fdr(pv, Q_FDR)
    for c in cells:
        c["bh_pass"] = bool(passed.get(f"H{c['hold']}", False))
    print(f"\n  BH-FDR q={Q_FDR} ({len(pv)} sel): " +
          ", ".join(f"H{k[1:]}={'PASS' if v else 'gagal'}" for k, v in passed.items()))

    # gerbang
    print(f"\n  -- gerbang LULUS (semua wajib) --")
    winners = []
    for c in cells:
        g = (c["bh_pass"] and c["t_nw"] >= T_MIN and (c["seg+"] or 0) >= SEG_MIN_OK
             and c["gross_bps"] > (c["ctrl_random_gross"] if np.isfinite(c["ctrl_random_gross"]) else -9e9)
             and c["gross_bps"] > 0)
        c["gate_pass"] = bool(g)
        if g:
            winners.append(c["hold"])
    if winners:
        print(f"     sel lulus: H{winners}  -> hipotesis H4 DIDUKUNG (deskriptif)")
    else:
        print("     TIDAK ADA sel lulus semua gerbang -> hipotesis H4 TIDAK DIDUKUNG (deskriptif)")
    print(f"     gerbang: BH PASS · t_NW>={T_MIN} · seg+>={SEG_MIN_OK} · bruto > kontrol-acak · bruto > 0")

    # kontrol C-c: panel sintetis
    print(f"\n  -- C-c: panel SINTETIS (random walk, ukuran sama) — wajib TIDAK lulus --")
    spx = synthetic_panel(len(px), px.shape[1], SEED)
    ssig = range_position(spx, LOOKBACK)
    syn = []
    for h in HOLDS:
        r = evaluate(spx, ssig, h)
        if r.get("n"):
            syn.append({"hold": h, "n": r["n"], "gross_bps": r["gross_bps"],
                        "t_nw": r["t_nw"], "p": r["p"], "seg+": r["seg+"]})
            print(f"     H={h:<3} n={r['n']:>5} bruto={r['gross_bps']:>8.2f} bps "
                  f"t={r['t_nw']:>6.2f} p={r['p']:>6.3f} seg+={r['seg+']}")
    spv = {f"H{s['hold']}": s["p"] for s in syn}
    spass = bh_fdr(spv, Q_FDR) if spv else {}
    n_syn_pass = sum(1 for v in spass.values() if v)
    print(f"     sel sintetis lolos BH: {n_syn_pass}/{len(spass)} "
          f"-> {'BENAR (0)' if n_syn_pass == 0 else 'PERINGATAN: kontrol bocor'}")
    out["controls"]["C_c_synthetic"] = syn

    for c in cells:
        out["cells"].append(c)
        out["controls"][f"C_a_shuffle_H{c['hold']}"] = c["ctrl_shuffle_gross"]
        out["controls"][f"C_b_random_H{c['hold']}"] = c["ctrl_random_gross"]
    out["bh_fdr"] = {k: bool(v) for k, v in passed.items()}
    out["winners"] = winners

    d = os.path.join(ROOT, "reports", "sodex")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "PRAREG4_RANGEPOS_SODEX_1H.json")
    with open(p, "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(f"\nberkas: {p}")
    print("\n>>> INGAT: DESKRIPTIF. Verdict sah hanya dari data FORWARD.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
