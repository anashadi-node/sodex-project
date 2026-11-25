#!/usr/bin/env python3
"""SODEX-ALT3 -- uji cross-sectional pada venue asli (92 simbol x ~12 bulan, 1h). READ-ONLY.

Pra-registrasi BEKU: docs/sodex/SODEX_ALT3_PRAREG_2026-10-07.md
Jangan ubah ambang/varian setelah melihat hasil.

8 varian: H6 momentum (24/72/168j), H7 reversal (4/8j), H8 risk-managed trend (3 varian).

DUA KEPUTUSAN OPERASIONAL (lebih KETAT dari pra-registrasi -- dijelaskan terbuka):
 1. BIAYA: spread long-short = 8 bp/leg x 2 leg = 16 bp (pra-reg menulis "8 bp"; pembacaan
    konservatif). Stress 1,5x = 24 bp.
 2. n: dilaporkan DUA angka -- n_obs (simbol x waktu, sesuai pra-reg) DAN n_rebal (portofolio
    non-overlapping, stride = H). Verdict memakai n_rebal karena n_obs menipu (jendela
    tumpang-tindih). n_rebal lebih kecil = lebih ketat.

Pakai: python3 scripts/sodex_alt3_xsec_study.py [--nperm 1000]
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
SRC = ROOT / "scratch/sodex_klines"
OUT = ROOT / "reports/sodex"
CORE3 = {"BTC-USD", "ETH-USD", "SOL-USD"}          # §3 mitigasi independensi
FEE_LEG, STRESS = 0.0008, 1.5                       # 4bp/leg/sisi -> 8bp; spread = 16bp
DECILE = 0.10
# GERBANG KUALITAS (bukan ambang hasil): cross-section dengan sedikit nama -> desil 1-2 nama
# = derau, bukan sinyal. Didokumentasikan sebagai DEVİASI di dokumen HASIL.
MIN_BREADTH = 20
IS_END = pd.Timestamp("2026-05-31 23:59:59", tz="UTC")
OOS_START = pd.Timestamp("2026-06-01", tz="UTC")
PASS = {"n_min": 100, "p_max": 0.05, "single_sym_share": 0.30, "q_fdr": 0.10}

VARIANTS = [
    ("H6a", "momentum", 24, 24, +1), ("H6b", "momentum", 72, 72, +1),
    ("H6c", "momentum", 168, 168, +1),
    ("H7a", "reversal", 4, 4, -1), ("H7b", "reversal", 8, 8, -1),
    ("H8a", "riskadj", 72, 72, +1), ("H8b", "riskadj_vol", 168, 168, +1),
    ("H8c", "riskadj_gate", 168, 168, +1),
]


def load_panel():
    fs = sorted(p for p in glob.glob(str(SRC / "*_1h.parquet")))
    if not fs:
        raise SystemExit(f"tidak ada klines di {SRC}. Jalankan scripts/sodex_backfill_klines.py.")
    frames, dropped = [], []
    for f in fs:
        sym = Path(f).name[:-len("_1h.parquet")]
        d = pd.read_parquet(f)
        d["sym"] = sym
        d["dt"] = pd.to_datetime(d["ts"], unit="s", utc=True)
        # --- kualitas §2 (fail-closed) ---
        ok = (len(d) > 500 and d["ts"].is_monotonic_increasing and d["ts"].is_unique
              and (d[["o", "h", "l", "c"]] > 0).all().all()
              and (d["v"] >= 0).all()
              and (d["h"] >= d[["o", "c"]].max(axis=1) - 1e-9).mean() >= 0.99
              and (d["l"] <= d[["o", "c"]].min(axis=1) + 1e-9).mean() >= 0.99)
        if ok:
            frames.append(d[["sym", "dt", "o", "h", "l", "c", "v"]])
        else:
            dropped.append(sym)
    if not frames:
        raise SystemExit("SEMUA simbol gagal pemeriksaan kualitas -> fail-closed, berhenti.")
    p = pd.concat(frames, ignore_index=True)
    C = p.pivot(index="dt", columns="sym", values="c").sort_index()
    O = p.pivot(index="dt", columns="sym", values="o").sort_index()
    V = p.pivot(index="dt", columns="sym", values="v").sort_index()
    return C, O, V, dropped


def signal(C, form: int, kind: str):
    ret = C / C.shift(form) - 1.0
    if kind.startswith("riskadj"):
        vol = ret.rolling(min(form, 168), min_periods=max(4, min(form, 168) // 4)).std()
        sig = ret / vol.replace(0, np.nan)
    else:
        sig = ret
    return sig


def fwd(C, O, hold: int):
    return C.shift(-hold) / O.shift(-1) - 1.0     # entry: open t+1 ; exit: close t+hold


def weights(sig, dirn: int):
    """Bobot long-short dari peringkat desil. Baris dengan breadth < MIN_BREADTH -> tanpa posisi."""
    live = sig.notna()
    enough = live.sum(axis=1) >= MIN_BREADTH
    r = sig.rank(axis=1, pct=True)
    if dirn < 0:
        r = 1.0 - r
    L = (r >= 1 - DECILE)
    S = (r <= DECILE)
    nl, ns = L.sum(axis=1), S.sum(axis=1)
    Wl = L.div(nl.replace(0, np.nan), axis=0).where(enough, np.nan)
    Ws = S.div(ns.replace(0, np.nan), axis=0).where(enough, np.nan)
    return Wl, Ws, (nl.where(enough, 0) + ns.where(enough, 0))


def port_returns(C, O, sig, hold, dirn, vol_scale=None, stride=None):
    """Return portofolio long-short, diambil pada bar non-overlapping (stride=hold)."""
    F = fwd(C, O, hold)
    Wl, Ws, nn = weights(sig, dirn)
    gross = (Wl * F).sum(axis=1, min_count=1) - (Ws * F).sum(axis=1, min_count=1)
    # Baris warm-up (sinyal belum tersedia -> 0 nama) HARUS di-NaN-kan: tanpa posisi,
    # tidak ada return DAN tidak ada biaya. Jangan bergantung pada kuirk pandas.
    gross = gross.where(nn > 0, np.nan)
    if vol_scale is not None:
        gross = gross * vol_scale
    cost = (2 * FEE_LEG) * (1.0 if vol_scale is None else vol_scale)
    net = gross - cost
    st = stride or hold
    idx = np.arange(0, len(net), st)
    s = net.iloc[idx].dropna()
    return s, nn.iloc[idx].dropna()


def vol_scaled(C):
    ret = np.log(C).diff()
    vol_ann = ret.rolling(168, min_periods=48).std() * np.sqrt(24 * 365)
    return (0.40 / vol_ann.replace(0, np.nan)).clip(upper=1.0)


def seg(s: pd.Series, a, b):
    return s[(s.index >= a) & (s.index <= b)]


def rand_rank_p(C, O, sig, hold, dirn, obs, nperm, a, b, rng):
    """Kontrol §7: peringkat ACAK pada tiap bar (uji apakah URUTAN membawa informasi).

    Wajib memakai mask & breadth-floor yang SAMA dengan uji asli -- kalau tidak, kontrol
    menguji populasi yang berbeda dan p-value tidak sah.
    """
    F = fwd(C, O, hold)
    m = seg(sig.notna(), a, b)
    enough = m.sum(axis=1) >= MIN_BREADTH
    Fsg = seg(F, a, b).where(m)
    n = len(Fsg)
    if n == 0:
        return float("nan")
    idx = np.arange(0, n, hold)
    hits = 0
    for _ in range(nperm):
        R = pd.DataFrame(rng.random(Fsg.shape), index=Fsg.index,
                         columns=Fsg.columns).where(m)
        r = R.rank(axis=1, pct=True)
        if dirn < 0:
            r = 1.0 - r
        L, S = (r >= 1 - DECILE), (r <= DECILE)
        g = ((L * Fsg).sum(axis=1) / L.sum(axis=1).replace(0, np.nan)
             - (S * Fsg).sum(axis=1) / S.sum(axis=1).replace(0, np.nan))
        g = (g.where(enough) - 2 * FEE_LEG).iloc[idx].dropna()
        if len(g) and g.mean() >= obs:
            hits += 1
    return (hits + 1) / (nperm + 1)


def bh_fdr(pairs, q=PASS["q_fdr"]):
    ps = sorted([(n, p) for n, p in pairs if p == p], key=lambda x: x[1])
    m, kmax = len(ps), 0
    for i, (_, p) in enumerate(ps, 1):
        if p <= q * i / m:
            kmax = i
    return [{"name": n, "p": p, "pass_bh": i <= kmax} for i, (n, p) in enumerate(ps, 1)]


def verdict(code, net_bp, stress_bp, p, n_rebal, top_share, oos_ex_bp):
    c1 = n_rebal >= PASS["n_min"]
    c2 = net_bp > 0
    c3 = stress_bp > 0
    c4 = p is not None and p == p and p < PASS["p_max"]
    c5 = top_share is not None and top_share == top_share and abs(top_share) <= PASS["single_sym_share"]
    c6 = (oos_ex_bp is None or oos_ex_bp != oos_ex_bp) or (np.sign(net_bp) == np.sign(oos_ex_bp))
    return {"c1_n": bool(c1), "c2_net": bool(c2), "c3_stress": bool(c3), "c4_p": bool(c4),
            "c5_conc": bool(c5), "c6_indep": bool(c6)}


def main():
    global MIN_BREADTH
    ap = argparse.ArgumentParser()
    ap.add_argument("--nperm", type=int, default=1000)
    ap.add_argument("--min-notional", type=float, default=0.0,
                    help="saring simbol: median notional/jam pada IS >= nilai ini (USD)")
    ap.add_argument("--min-breadth", type=int, default=MIN_BREADTH)
    a = ap.parse_args()
    MIN_BREADTH = a.min_breadth
    rng = np.random.default_rng(7)
    C, O, V, dropped = load_panel()
    if a.min_notional > 0:
        med = (C * V)[C.index <= IS_END].median()
        keep = [s for s in C.columns if pd.notna(med.get(s)) and med[s] >= a.min_notional]
        print(f"filter likuiditas (median notional/jam IS >= ${a.min_notional:,.0f}): "
              f"{C.shape[1]} -> {len(keep)} simbol")
        C, O, V = C[keep], O[keep], V[keep]
    print(f"panel: {C.shape[1]} simbol x {len(C):,} bar 1h | {C.index[0]} .. {C.index[-1]}")
    print(f"simbol gagal kualitas (dikeluarkan): {len(dropped)} {dropped[:8]}")
    Cex = C.drop(columns=[c for c in CORE3 if c in C.columns])
    vsc = vol_scaled(C)

    out = {"meta": {"symbols": int(C.shape[1]), "dropped": dropped, "bars": int(len(C)),
                    "start": str(C.index[0]), "end": str(C.index[-1]),
                    "fee_spread_bp": 2 * FEE_LEG * 1e4, "stress_x": STRESS,
                    "is": ["2025-10-12", "2026-05-31"], "oos": ["2026-06-01", str(C.index[-1].date())],
                    "pass": PASS, "nperm": a.nperm, "min_breadth": MIN_BREADTH,
                    "deviasi_dari_prarreg": ["breadth-floor 20 (gerbang kualitas)",
                                             "biaya spread 16bp (pembacaan konservatif dari 8bp)",
                                             "n dilaporkan sebagai rebalance non-overlapping"]}}
    print(f"\n{'varian':6s} {'n_rebal':>7s} {'net(bp)':>9s} {'stress':>8s} {'WR':>6s} {'p':>7s} "
          f"{'tanpa3':>9s} {'simbol dom':>11s}")
    tests, rows = [], []
    for code, kind, form, hold, dirn in VARIANTS:
        sig = signal(C, form, kind)
        if code == "H8c":
            btc = C["BTC-USD"] / C["BTC-USD"].shift(168) - 1.0 if "BTC-USD" in C else None
            sig = sig.where(btc > 0, np.nan) if btc is not None else sig
        vs = vsc if code in ("H8b", "H8c") else None
        s, nn = port_returns(C, O, sig, hold, dirn, vol_scale=(vs if vs is None else vs.mean(axis=1)))
        s_ex, _ = port_returns(Cex, O[Cex.columns], sig[Cex.columns], hold, dirn, vol_scale=None)
        so, sx = seg(s, OOS_START, C.index[-1]), seg(s_ex, OOS_START, C.index[-1])
        if len(so) < 5:
            print(f"{code:6s}   (n terlalu kecil: {len(so)})")
            continue
        net = so.mean()
        stress = net - (2 * FEE_LEG) * (STRESS - 1)      # biaya 1,5x -> tambahan 8 bp
        p = rand_rank_p(C, O, sig, hold, dirn, so.mean(), a.nperm, OOS_START, C.index[-1], rng)
        # kontribusi simbol dominan (pakai bobot x forward pada OOS)
        F = fwd(C, O, hold)
        Wl, Ws, _ = weights(sig, dirn)
        contrib = (((Wl - Ws) * F).loc[(F.index >= OOS_START)].sum()).dropna()
        tot = contrib.sum()
        top_sym = contrib.abs().idxmax() if len(contrib) else None
        top_share = float(contrib[top_sym] / tot) if top_sym and tot else None
        # SENSITIVITAS SLIPPAGE: tiap rebalance = 2 leg x (masuk+keluar) = 4 sisi.
        # net(s) = net(0) - 4s. Titik impas s* = net(0)/4 bp per sisi.
        slip = {s: net * 1e4 - 4 * s for s in (0, 5, 10, 25, 50, 100)}
        be_slip = net * 1e4 / 4
        rows.append({"code": code, "n_rebal": int(len(so)), "net_bp": net * 1e4, "stress_bp": stress * 1e4,
                     "wr": float((so > 0).mean()), "p": p, "oos_ex3_bp": sx.mean() * 1e4 if len(sx) else None,
                     "top_sym": top_sym, "top_share": top_share,
                     "breakeven_slip_bp_per_side": be_slip, "net_at_slip_bp": slip})
        tests.append((code, p))
        print(f"{code:6s} {len(so):7d} {net*1e4:9.2f} {stress*1e4:8.2f} {(so>0).mean():6.1%} "
              f"{p:7.3f} {(sx.mean()*1e4 if len(sx) else float('nan')):9.2f} {str(top_sym):>11s} "
              f"| impas slippage {be_slip:6.1f} bp/sisi", flush=True)
        out[code] = rows[-1]

    out["BH_FDR"] = bh_fdr(tests)
    for r in rows:
        r.update(verdict(r["code"], r["net_bp"], r["stress_bp"], r["p"], r["n_rebal"],
                         r["top_share"], r.get("oos_ex3_bp")))
        r["LAYAK"] = all([r["c1_n"], r["c2_net"], r["c3_stress"], r["c4_p"], r["c5_conc"], r["c6_indep"]])
        bh = next((b["pass_bh"] for b in out["BH_FDR"] if b["name"] == r["code"]), False)
        r["pass_bh"] = bh
        r["LAYAK"] = bool(r["LAYAK"] and bh and r["net_bp"] > 0)
    lulus = [r["code"] for r in rows if r["LAYAK"]]
    out["VERDICT"] = {"hasil": "LULUS" if lulus else ("GAGAL" if rows else "BELUM CUKUP BUKTI"),
                      "lulus": lulus}
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"sodex_alt3_xsec_{pd.Timestamp.now():%Y%m%d}.json"
    dest.write_text(json.dumps(out, indent=1, default=str))
    print(f"\n═══ VERDICT: {out['VERDICT']['hasil']} ═══  (lulus: {lulus or 'TIDAK ADA'})")
    for r in rows:
        print(f"  {r['code']:6s} gagal={[k for k in ('c1_n','c2_net','c3_stress','c4_p','c5_conc','c6_indep') if not r[k]] or '-'} bh={r['pass_bh']}")
    print(f"\nhasil -> {dest}")


if __name__ == "__main__":
    main()
