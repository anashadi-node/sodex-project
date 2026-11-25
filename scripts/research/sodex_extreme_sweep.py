#!/usr/bin/env python3
"""PRAREG-18 — Sapuan ekstrem K1+K2+K3+K4 (jalankan SETELAH berkas prareg di-commit).

K1: 12 mekanisme x panel {sodex_1h, sodex_1d} x hold {24,48} JAM x arah {as-is, dibalik}.
    Arah dibalik diturunkan ANALITIS (rank_w(-s) = -rank_w(s) -> net/gross/t/S_ann berganti tanda,
    turnover & biaya identik) dan DIVERIFIKASI dengan run langsung pada 2 sel.
K2: sensitivitas biaya fee_oneway {1,14 ; 2,0 ; 2,80 ; 4,0 ; 4,86} bps/sisi utk 2 kandidat terkuat.
K3: pengondisian pra-perdagangan (dispersi cross-sectional, jumlah nama) pada kandidat terkuat.
K4: matriks korelasi aliran net per-window + estimasi S_ann portofolio N=6,8 (rumus
    S_port = S_rata2 * sqrt(N/(1+(N-1)rho))).

Jalankan: /usr/bin/python3 scripts/research/sodex_extreme_sweep.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import importlib.util

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import xsec_mech_study as xs  # noqa: E402

HOLDS_JAM = (24, 48)
FEE_LEVELS_BPS = (1.14, 2.0, 2.80, 4.0, 4.855)
Q_FDR = 0.10
OUT = os.path.join(ROOT, "reports", "sodex", "SWEEP_EKSTREM_K1K4.json")


def stream_mech(px, ret, sig_raw, hold, fee_oneway, fee_mult, control=False, seed=20261007):
    """Replikasi run_mech yang mengembalikan ALIRAN net per window (untuk K4).

    Diverifikasi terhadap agregat run_mech (mean & t harus identik).
    """
    if control:
        rng = np.random.default_rng(seed)
        vals = sig_raw.to_numpy(copy=True)
        mask = np.isfinite(vals)
        for i in range(vals.shape[0]):
            m = mask[i]
            k = int(m.sum())
            if k > 1:
                v = vals[i, m].copy()
                rng.shuffle(v)
                vals[i, m] = v
        sig_raw = pd.DataFrame(vals, index=sig_raw.index, columns=sig_raw.columns)
    idx = px.index
    recs, prev_w = [], None
    for i in range(0, len(idx) - max(hold, 1), hold):
        sig = sig_raw.iloc[i].dropna()
        if sig.size < xs.MIN_NAMES:
            continue
        fwd = ret.iloc[i + 1:i + 1 + hold].sum(skipna=False).reindex(sig.index)
        ok = fwd.notna() & sig.notna()
        sig, fwd = sig[ok], fwd[ok]
        if sig.size < xs.MIN_NAMES:
            continue
        excess = fwd - fwd.mean()
        w = xs.rank_w(sig)
        gross = float((w * excess).sum())
        if prev_w is None:
            to = float(w.abs().sum())
        else:
            allk = w.index.union(prev_w.index)
            to = float((w.reindex(allk, fill_value=0.0)
                        - prev_w.reindex(allk, fill_value=0.0)).abs().sum())
        recs.append({"t": idx[i], "gross": gross, "net": gross - to * fee_oneway * fee_mult,
                     "to": to, "n": int(sig.size),
                     "disp": float((sig - sig.median()).abs().median())})
        prev_w = w
    if not recs:
        return pd.Series(dtype=float), pd.DataFrame()
    df = pd.DataFrame(recs).set_index("t")
    return df["net"], df


def panel_mechs(px: pd.DataFrame) -> dict:
    vol = pd.DataFrame()          # panel volume SoDEX belum dibangun di modul -> VOLSHOCK di-skip
    sigs, ret = xs.build_signals(px)
    xs.add_vol_shock(sigs, px, vol)
    xs.add_maxfx(sigs, px)
    return {"sigs": sigs, "ret": ret}


def main() -> int:
    res = {"prareg": "reports/sodex/PRAREG18_PROGRAM_EKSTREM_PROTOCOL.json",
           "catatan": "SEMUA DESKRIPTIF (jendela historis terpakai). Verdict hanya dari forward.",
           "K1": {}, "K2": {}, "K3": {}, "K4": {}}
    cand_streams, cand_meta = {}, {}

    for label, loader, fee in (("sodex_1h", lambda: xs._sodex_panel("1h"), xs.FEE_ONEWAY),
                               ("sodex_1d", lambda: xs._sodex_panel("1d"), xs.FEE_ONEWAY),
                               ("binance_1h", lambda: xs._binance_panel("1h"), xs.FEE_ONEWAY_BN)):
        is_h = label.endswith("1h")
        xs.PPY = 365.0 * 24.0 if is_h else 365.0
        px = loader()
        if px is None or px.empty:
            continue
        d = panel_mechs(px)
        ret, sigs = d["ret"], d["sigs"]
        holds = HOLDS_JAM if is_h else (2, 5)
        print(f"\n=== K1 {label} | {px.shape[1]} nama x {len(px)} bar | PPY={xs.PPY:g} "
              f"| hold(bar)={holds}")
        print(f"  {'mekanisme':12}{'h':>4}{'n':>5}{'net':>9}{'S_ann':>7}{'t':>7}{'p':>8}"
              f"{'to':>6}{'ctrl_t':>8}{'seg+':>6}  arah-terbalik: net / t / S_ann")
        for mech in xs.MECH_ORDER:
            if mech not in sigs or sigs[mech].dropna(how="all").empty:
                res["K1"][f"{label}|{mech}"] = {"skip": True, "sebab": "DATA-TIDAK-ADA"}
                continue
            for h in holds:
                r = xs.run_mech(px, ret, sigs[mech], h, fee, 1.0)
                if not r.get("n"):
                    continue
                c = xs.run_mech(px, ret, sigs[mech], h, fee, 1.0, control=True)
                r2 = xs.run_mech(px, ret, sigs[mech], h, fee, 2.0)
                key = f"{label}|{mech}|H{h}"
                neg = {"net": -r["mean_bps_per_period"], "t": -r["t_nw"], "p": r["p"],
                       "S_ann": -r["sharpe_annual"], "S2x": -r2["sharpe_annual"],
                       "to": r["turnover"]}
                neg["seg_pos"] = sum(1 for x in (r.get("segments") or []) if x < 0)
                res["K1"][key] = {
                    "mech": mech, "hold_jam": h if is_h else h * 24, "n": r["n"],
                    "as_is": {"net": r["mean_bps_per_period"], "t": r["t_nw"], "p": r["p"],
                              "S_ann": r["sharpe_annual"], "to": r["turnover"],
                              "fee_bps": r["fee_bps"], "seg_pos": r.get("segments_positive"),
                              "ctrl_t": c.get("t_nw"), "S2x": r2["sharpe_annual"]},
                    "dibalik": {"net": neg["net"], "t": neg["t"], "p": neg["p"],
                                "S_ann": neg["S_ann"], "S2x": neg["S2x"], "to": neg["to"],
                                "seg_pos": neg["seg_pos"], "ctrl_t": c.get("t_nw")},
                }
                print(f"  {mech:12}{h:>4}{r['n']:>5}{r['mean_bps_per_period']:>9.2f}"
                      f"{r['sharpe_annual']:>7.2f}{r['t_nw']:>7.2f}{r['p']:>8.4f}"
                      f"{r['turnover']:>6.2f}{(c.get('t_nw') or 0):>8.2f}"
                      f"{str(r.get('segments_positive')):>6}   {neg['net']:>8.2f} / {neg['t']:>6.2f}"
                      f" / {neg['S_ann']:>6.2f}")
                # aliran untuk K4 (hanya sel 48 jam, venvenue primer)
                if is_h and h == 48 and label == "sodex_1h":
                    s, dfm = stream_mech(px, ret, sigs[mech], h, fee, 1.0)
                    sf, _ = stream_mech(px, ret, -sigs[mech], h, fee, 1.0)
                    chk = float(np.nanmax(np.abs(np.asarray(sf) + np.asarray(s))))
                    res["K1"][key]["verifikasi_replikasi"] = {
                        "mean_mine": float(s.mean() * 1e4), "mean_modul": r["mean_bps_per_period"],
                        "t_mine": xs.nw_t(np.asarray(s), lag=h), "t_modul": r["t_nw"],
                        "max_abs_dev_flip_vs_negasi": chk}
                    cand_streams[f"{mech}(as-is)"] = s
                    cand_streams[f"{mech}(dibalik)"] = sf
                    cand_meta[f"{mech}(as-is)"] = res["K1"][key]["as_is"]["net"]
                    cand_meta[f"{mech}(dibalik)"] = neg["net"]

    # ── gerbang beku atas semua sel (K1) ──
    rows = []
    for k, v in res["K1"].items():
        if v.get("skip"):
            continue
        for arah in ("as_is", "dibalik"):
            a = v[arah]
            rows.append({"key": f"{k}|{arah}", "venue": k.split("|")[0], "mech": v["mech"],
                         "hold_jam": v["hold_jam"], "arah": arah, "n": v["n"], **a})
    # BH-FDR atas KELUARGA PENUH (prareg K1: q=0,10). p dua-sisi -> sama utk kedua arah,
    # jadi m = jumlah sel (lebih konservatif, sesuai deklarasi).
    pvals = {r["key"]: r["p"] for r in rows}
    bh = xs.bh_fdr(pvals, Q_FDR)
    for r in rows:
        r["bh_pass"] = bool(bh.get(r["key"], False))
        r["lolos_gerbang"] = bool(
            r["net"] > 0 and r["to"] <= 1.5 and abs(r["ctrl_t"] or 9) < 2.0
            and r["t"] >= 1.96 and r["S_ann"] >= 2.3 and r["S2x"] >= 1.8 and r["bh_pass"])
    res["K1_bh_family"] = len(rows)
    res["K1_lolos_gerbang"] = sorted([r for r in rows if r["lolos_gerbang"]],
                                     key=lambda r: -r["net"])
    res["K1_sel_dijalankan"] = len(rows)
    print(f"\n[K1] {len(rows)} sel dijalankan | lolos gerbang beku: {len(res['K1_lolos_gerbang'])}")
    for r in res["K1_lolos_gerbang"]:
        print(f"   LULUS {r['key']:38} net={r['net']:>7.2f} S_ann={r['S_ann']:>5.2f} "
              f"t={r['t']:>5.2f} to={r['to']:.2f} S2x={r['S2x']:>5.2f}")

    # ── K2 sensitivitas biaya ──
    px = xs._sodex_panel("1h")
    xs.PPY = 365.0 * 24.0
    d = panel_mechs(px)
    for mech in ("MOM_L21", "RANGEPOS"):
        if mech not in d["sigs"]:
            continue
        for tick, fee in (("as_is", 1.0), ("dibalik", -1.0)):
            sig = d["sigs"][mech] * fee
            for lvl in FEE_LEVELS_BPS:
                r = xs.run_mech(px, d["ret"], sig, 48, lvl / 1e4, 1.0)
                if not r.get("n"):
                    continue
                res["K2"][f"{mech}|{tick}|fee{lvl}"] = {
                    "fee_oneway_bps": lvl, "n": r["n"],
                    "net": r["mean_bps_per_period"],
                    "gross": r["mean_bps_per_period"] + r["fee_bps"],
                    "S_ann": r["sharpe_annual"],
                    "t": r["t_nw"], "to": r["turnover"], "fee_bps_total": r["fee_bps"]}
        print(f"[K2] {mech}: selesai")
    # biaya yang dibutuhkan agar net = 0 dan net = 80 bps (dari slope to)
    for mech in ("MOM_L21", "RANGEPOS"):
        v = res["K2"].get(f"{mech}|dibalik|fee4.0")
        if not v:
            continue
        gross, to = v["gross"], v["to"]
        be = gross / to
        res["K2"][f"{mech}|BREAKEVEN"] = {
            "gross_bps": gross, "to": to,
            "fee_oneway_breakeven_bps": be,
            "fee_oneway_utk_net80_bps": (gross - 80) / to}
        print(f"[K2] {mech} bruto={gross:.2f} to={to:.2f} -> biaya impas {be:.2f} bps/sisi, "
              f"biaya utk net 80 bps: {(gross - 80) / to:.2f} bps/sisi")

    # ── K3 pengondisian ──
    for mech in ("MOM_L21", "RANGEPOS"):
        if mech not in d["sigs"]:
            continue
        for tick, sgn in (("as_is", 1.0), ("dibalik", -1.0)):
            net, dfm = stream_mech(px, d["ret"], d["sigs"][mech] * sgn, 48, xs.FEE_ONEWAY, 1.0)
            if dfm.empty:
                continue
            for var in ("disp", "n"):
                lo = dfm[dfm[var] <= dfm[var].median()]
                hi = dfm[dfm[var] > dfm[var].median()]
                res["K3"][f"{mech}|{tick}|{var}"] = {
                    "var": var, "median": float(dfm[var].median()),
                    "bawah": {"n": len(lo), "net": float(lo["net"].mean() * 1e4)},
                    "atas": {"n": len(hi), "net": float(hi["net"].mean() * 1e4)}}
                print(f"[K3] {mech}/{tick}/{var}: bawah n={len(lo)} "
                      f"net={lo['net'].mean() * 1e4:>7.2f} | atas n={len(hi)} "
                      f"net={hi['net'].mean() * 1e4:>7.2f}")

    # ── K4 korelasi & portofolio ──
    if cand_streams:
        best = {}
        for name, s in cand_streams.items():
            if cand_meta.get(name, -1) > 0 and len(s) >= 40:
                best[name] = s
        if best:
            M = pd.DataFrame(best).dropna()
            cm = M.corr()
            res["K4"]["kandidat"] = sorted(best, key=lambda k: -cand_meta[k])
            res["K4"]["matriks_korelasi"] = {a: {b: round(float(cm.loc[a, b]), 3)
                                                 for b in cm.columns} for a in cm.index}
            print(f"\n[K4] {len(best)} kandidat net>0 & n>=40 | korelasi rata2 "
                  f"(di luar diagonal) = "
                  f"{float((cm.values.sum() - len(cm)) / (len(cm) ** 2 - len(cm))):.3f}")
            for N in (6, 8):
                if len(best) < N:
                    continue
                sel = list(res["K4"]["kandidat"][:N])
                sub = cm.loc[sel, sel]
                off = (sub.values.sum() - N) / (N * N - N)
                s_avg = float(np.mean([cand_meta[k] for k in sel]))
                mult = math.sqrt(N / (1 + (N - 1) * off))
                res["K4"][f"portofolio_N{N}"] = {
                    "mesin": sel, "rho_rata2": float(off),
                    "S_ann_rata2": None, "multiplier": mult}
                print(f"[K4] N={N} rho_rata2={off:.3f} multiplier={mult:.2f} "
                      f"(S_avg dari S_ann tiap mesin di K1)")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(res, f, indent=1, default=str)
    print(f"\n[ditulis] {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
