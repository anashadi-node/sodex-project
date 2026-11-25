#!/usr/bin/env python3
"""PRAREG-35 — HYBRID spot+perp untuk arm A dan B2 (uji utama) + pembanding lengkap.
Konstruksi: lapisan dasar 1x ditahan di SPOT (tanpa funding); kelebihan eksposur (L-1)x lewat PERP (funding hanya pada notional perp).
RISET read-only: tanpa order, tanpa kredensial, tanpa mengubah parameter engine/live."""
from __future__ import annotations
import json, os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import lev_study as ls
import mode_a_engine as eng

# ===================== PLAN BEKU (PRAREG-35) =====================
PLAN35 = dict(
    arms=("A", "B2"),
    L_grid=(1.0, 1.25, 1.5, 2.0, 2.5, 3.0),
    L_fine=tuple(np.arange(1.0, 4.01, 0.25)),
    cost_primary=0.0010,                     # sama dengan PRAREG-34 (apple-to-apple)
    cost_spot_real=0.00065, cost_perp_real=0.00045,
    start_fund="2020-01-01", start_main="2022-01-01", start_oos="2024-01-01", start_oos26="2026-05-24",
    today="2026-10-25", target_M=0.010, mdd_cap=-35.0,
    stress_mult=1.5, near_liq=0.20, win_days=31, p_alpha=0.05,
    seed=35, n_boot=5000, block=10, n_ctrl=300, sodex_fund_bps_day=1.3,
)
PLAN = ls.PLAN          # parameter data/gerbang dipakai bersama


def hybrid_core(R, T, F, A, L, c_spot, c_perp, band=0.20, stress=None):
    """Dua lapisan: spot = w (1x), perp = w*(L-1). PnL total L*(w.R); funding hanya (L-1); fee terpisah per lapisan.
    Likuidasi: hanya lapisan perp. equity_setelah = 1 + L*g*a ; maintenance = MMR*(L-1)*g*(1+a)."""
    stress = PLAN["stress_mult"] if stress is None else stress
    n = len(R); w = np.zeros(len(R[0])); net = np.empty(n); turn_s = np.empty(n); turn_p = np.empty(n); gross = np.empty(n)
    liq = np.zeros(n, bool); liqs = np.zeros(n, bool); eqmin = np.ones(n); dragv = np.empty(n)
    Lp = L - 1.0
    for i in range(n):
        g = float(w.sum()); drag = Lp * float((w * F[i]).sum()) / 1e4 if g > 0 else 0.0
        if g > 0 and Lp > 0:
            notional = g * Lp
            for mult, arr in ((1.0, liq), (stress, liqs)):
                a = A[i] * mult; eq = 1.0 + L * float((w * a).sum()); mm = float((ls.MMRV * w * Lp * (1 + a)).sum())
                arr[i] = eq <= mm; eqmin[i] = min(eqmin[i], eq)
        r = R[i]; gr = float((w * r).sum())
        w = w * (1 + r) / (1 + gr) if gr != -1.0 else w * 0.0
        t = T[i]; d = t - w
        hit = np.where((t == 0.0) & (w > 0.0), True, np.abs(d) > band * np.maximum(t, 0.05))
        ds = float(np.abs(d[hit]).sum()); w = w + np.where(hit, d, 0.0)
        tv_s = ds                                     # turnover lapisan spot (1x)
        tv_p = ds * Lp                                # turnover lapisan perp ((L-1)x)
        cst = tv_s * c_spot + tv_p * c_perp
        net[i] = (1 + L * gr) * (1 - cst) - 1 - drag; turn_s[i] = tv_s; turn_p[i] = tv_p; gross[i] = g; dragv[i] = drag
    return pd.DataFrame({"net": net, "turn_s": turn_s, "turn_p": turn_p, "gross": gross, "drag": dragv,
                         "liq": liq, "liq_stress": liqs, "eq_stress": eqmin})


def hybrid_sim(closes, tgt, L, start, c_spot, c_perp, fund=None, adv=None):
    idx, R, T, F, A = ls._prep(closes, tgt, start, fund, adv, 1)
    res = hybrid_core(R, T, F, A, L, c_spot, c_perp); res.index = idx
    return res


def allperp_sim(closes, tgt, L, start, cost, fund, adv):
    return ls.lev_sim(closes, tgt, L, start, cost, fund, adv)


def summarize(res, drag_col="drag"):
    out = {}
    for tag, s in (("2022+", PLAN["start_main"]), ("2024+", PLAN["start_oos"]), ("OOS26", PLAN["start_oos26"])):
        out[f"M_{tag}"] = round(ls.M5(res["net"].loc[s:]), 5)
    r = res["net"].loc[PLAN["start_main"]:]; rc = r.clip(lower=-0.999999)
    out["G5j_geom_2022+"] = round(float(np.log1p(rc).mean() * 5 / 24 * 100), 5)
    out["MDD_2022+"] = round(ls.mdd(r), 1)
    w = PLAN["win_days"]; rm = r.rolling(w).mean().dropna() * 5 / 24 * 100; rr = (1 + rc).rolling(w).apply(np.prod, raw=True).dropna() - 1
    out["P_win31_M>=target"] = round(float((rm >= PLAN["target_M"]).mean()), 3)
    out["P_win31_rugi"] = round(float((rr < 0).mean()), 3); out["win31_terburuk_%"] = round(float(rr.min() * 100), 1)
    ann = r.groupby(r.index.year).apply(ls.M5); out["tahun_M>=target"] = f"{int((ann >= PLAN['target_M']).sum())}/{len(ann)}"
    full = res.loc[PLAN["start_fund"]:]
    out["hari_likuidasi_dasar"] = int(full["liq"].sum()); out["hari_likuidasi_stres"] = int(full["liq_stress"].sum())
    out["eq_stres_min"] = round(float(full["eq_stress"].min()), 3); out["hari_eq_stres<=0.2"] = int((full["eq_stress"] <= PLAN["near_liq"]).sum())
    out["drag_funding_tahunan_%"] = round(float(res["drag"].loc[PLAN["start_main"]:].sum() / len(r) * 365 * 100), 2) if "drag" in res else None
    out["turnover_tahunan_spot"] = round(float(res["turn_s"].loc[PLAN["start_main"]:].mean() * 365), 2) if "turn_s" in res else None
    out["turnover_tahunan_perp"] = round(float(res["turn_p"].loc[PLAN["start_main"]:].mean() * 365), 2) if "turn_p" in res else None
    out.update(ls.block_boot(r))
    return out


def verdict(sm, ctrl_p):
    a = sm["M_2022+"] >= PLAN["target_M"]; b = sm["M_OOS26"] > 0 and sm["M_2024+"] > 0
    c = sm["hari_likuidasi_stres"] == 0 and sm["MDD_2022+"] >= PLAN["mdd_cap"]
    d = sm.get("p_M_le_0", 1.0) < PLAN["p_alpha"] and (ctrl_p if ctrl_p is not None else 1.0) < PLAN["p_alpha"]
    g = {"A_target": a, "B_oos_positif": b, "C_risiko": c, "D_bukti": d}
    return ("TIDAK_LAYAK" if not (a and b and c) else ("TERBUKTI" if d else "LAYAK_PAPER_BUKAN_BUKTI")), g


def control_p_hybrid(closes, tgt, L, fund, adv, actual_M):
    fast = ls.Fast(closes, tgt, fund, adv); rng = np.random.default_rng(PLAN["seed"] + 35)
    nz = np.where(np.abs(fast.T).sum(axis=1) > 0)[0]; a0 = int(nz[0]); vals = fast.T[a0:].copy(); ms = []
    for _ in range(PLAN["n_ctrl"]):
        k = int(rng.integers(180, len(vals) - 180)); sh = fast.T.copy(); sh[a0:] = np.roll(vals, k, axis=0)
        res = hybrid_core(fast.R, sh, fast.F, fast.A, L, PLAN["cost_primary"], PLAN["cost_primary"]); res.index = fast.idx
        ms.append(ls.M5(res["net"].iloc[fast.pos:]))
    ms = np.array(ms)
    return round(float((np.sum(ms >= actual_M) + 1) / (len(ms) + 1)), 4), round(float(np.median(ms)), 5)


def main():
    closes, ohlc, f = ls.load_all(); adv = ls.build_adv(closes, ohlc); fund = ls.build_fund(closes, f)
    fund_sd = ls.build_fund(closes, f, flat=PLAN["sodex_fund_bps_day"]); fund0 = ls.build_fund(closes, f, flat=0.0)
    today = pd.Timestamp(PLAN["today"]); out = {"plan": {k: (list(v) if isinstance(v, tuple) else v) for k, v in PLAN35.items() if k != "L_fine"}, "arms": {}}
    for arm in PLAN35["arms"]:
        T = eng.target_history(closes, mode=arm, today=today); A = {}
        A["acuan_spot_1x"] = round(ls.M5(ls.simulate(closes, T, start=PLAN["start_main"], cost=PLAN["cost_primary"])[0]), 5)
        # --- UJI UTAMA: hybrid
        for L in PLAN35["L_grid"]:
            res = hybrid_sim(closes, T, L, PLAN["start_fund"], PLAN35["cost_primary"], PLAN35["cost_primary"], fund, adv)
            sm = summarize(res); cp = control_p_hybrid(closes, T, L, fund, adv, sm["M_2022+"]) if L in (1.5, 2.0) else (None, None)
            v, g = verdict(sm, cp[0]); A[f"hybrid_L={L}"] = {**sm, "p_kontrol": cp[0], "kontrol_M_median": cp[1], "vonis": v, "gerbang": g}
        # --- PEMBANDING: all-perp pada grid sama
        for L in PLAN35["L_grid"]:
            res = allperp_sim(closes, T, L, PLAN["start_fund"], PLAN35["cost_primary"], fund, adv); sm = summarize(res)
            v, g = verdict(sm, None); A[f"allperp_L={L}"] = {**sm, "vonis": v, "gerbang": g}
        # --- PEMBANDING: fee riil (spot 6,5 / perp 4,5 bps) dan sensitivitas funding
        S = {}
        for lab, (cs, cp_, fu) in {
            "fee_riil_spot6.5_perp4.5": (PLAN35["cost_spot_real"], PLAN35["cost_perp_real"], fund),
            "biaya_7bps": (0.0007, 0.0007, fund), "biaya_15bps": (0.0015, 0.0015, fund), "biaya_25bps": (0.0025, 0.0025, fund),
            "funding_SoDEX_1.3": (PLAN35["cost_primary"], PLAN35["cost_primary"], fund_sd), "funding_0": (PLAN35["cost_primary"], PLAN35["cost_primary"], fund0),
        }.items():
            S[lab] = {f"L={L}": round(ls.M5(hybrid_sim(closes, T, L, PLAN["start_main"], cs, cp_, fu, adv)["net"]), 5) for L in PLAN35["L_grid"]}
        out["arms"][arm] = {"hasil": A, "sensitivitas_hybrid": S}
        # kurva halus + titik kritis
        K, first_liq_s, mdd_cap_L = {}, None, None
        for L in PLAN35["L_fine"]:
            res = hybrid_sim(closes, T, float(L), PLAN["start_fund"], PLAN35["cost_primary"], PLAN35["cost_primary"], fund, adv); r = res["net"].loc[PLAN["start_main"]:]
            K[f"{L:.2f}"] = {"M": round(ls.M5(r), 5), "G": round(float(np.log1p(r.clip(lower=-0.999999)).mean() * 5 / 24 * 100), 5),
                             "MDD": round(ls.mdd(r), 1), "liq_s": int(res["liq_stress"].sum()), "drag_%": round(float(res["drag"].loc[PLAN["start_main"]:].sum() / len(r) * 365 * 100), 2)}
            if first_liq_s is None and K[f"{L:.2f}"]["liq_s"] > 0: first_liq_s = float(L)
            if mdd_cap_L is None and K[f"{L:.2f}"]["MDD"] < PLAN["mdd_cap"]: mdd_cap_L = float(L)
        Ls = [float(k) for k in K]; Gs = [K[f"{x:.2f}"]["G"] for x in Ls]; Ms = [K[f"{x:.2f}"]["M"] for x in Ls]
        out.setdefault("kelly_kurva", {})[arm] = K
        out.setdefault("L_kritis", {})[arm] = {"L_pertama_M>=target": next((x for x, m in zip(Ls, Ms) if m >= PLAN["target_M"]), None),
                                               "L_G_maks": Ls[int(np.argmax(Gs))], "L_pertama_MDD<cap": mdd_cap_L, "L_pertama_likuidasi_stres": first_liq_s}
    json.dump(out, open(os.path.join(HERE, "hybrid_results.json"), "w"), indent=1, default=str)
    return out


if __name__ == "__main__":
    o = main(); print(json.dumps({"L_kritis": o["L_kritis"]}, indent=1))
    for arm, d in o["arms"].items():
        print("\n==", arm, "acuan spot 1x:", d["hasil"]["acuan_spot_1x"])
        for k, v in d["hasil"].items():
            if k.startswith("hybrid_L=") or k.startswith("allperp_L="):
                print(k, {x: v[x] for x in ("M_2022+", "M_2024+", "M_OOS26", "MDD_2022+", "P_win31_M>=target", "win31_terburuk_%", "hari_likuidasi_stres", "eq_stres_min", "drag_funding_tahunan_%", "p_M_le_0", "vonis")}, "ctrl", v.get("p_kontrol"))
        print("sens:", json.dumps(d["sensitivitas_hybrid"], indent=0))
