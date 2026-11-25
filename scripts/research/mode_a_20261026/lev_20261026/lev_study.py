#!/usr/bin/env python3
"""PRAREG-34 — studi LEVERAGE (perp) untuk Mode A. RISET read-only: tanpa order, tanpa kredensial, tanpa mengubah parameter engine/live.
Pertanyaan: adakah leverage L>1 pada target arm A/B2 yang (i) mencapai M>=0,010 %/5j NETTO biaya+funding, (ii) selamat dari likuidasi (stres),
(iii) memenuhi plafon risiko, dan (iv) apakah KLAIM edge-nya sendiri terbukti (bootstrap + kontrol negatif)? Leverage menskala rata-rata DAN risiko;
ia tidak menambah edge. Gerbang (iv) membedakan 'layak diuji paper' dari 'terbukti'."""
from __future__ import annotations
import hashlib, json, math, os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); PARENT = os.path.dirname(HERE)
sys.path.insert(0, PARENT)
import mode_a_engine as eng
from bt_indep import load, simulate

# ===================== PLAN BEKU (PRAREG-34) =====================
PLAN = dict(
    arms=("A", "B2"),                       # B1 dikecualikan: 100% terinvestasi, OOS26 negatif tanpa leverage
    L_grid=(1.0, 1.5, 2.0, 3.0),
    L_fine=tuple(np.arange(0.5, 8.01, 0.5)),
    cost_primary=0.0010, cost_sens=(0.0007, 0.0015, 0.0025),
    start_fund="2020-01-01", start_main="2022-01-01", start_oos="2024-01-01", start_oos26="2026-05-24",
    today="2026-10-25", target_M=0.010, mdd_cap=-35.0,           # plafon MDD 2022+ = ASUMSI peneliti, wajib disetujui pengguna
    stress_mult=1.5, near_liq=0.20, xaut_adv=0.006, win_days=31, p_alpha=0.05,
    seed=34, n_boot=5000, block=10, n_ctrl=300, sodex_fund_bps_day=1.3,
)
MMR = {"btc": 0.0125, "eth": 0.02, "xaut": 0.02}    # maintenance = 1/2 initial; BTC 40x, ETH/XAUT 25x (sodex.com margin-tiers)
COLS = ["btc", "eth", "xaut"]


class StudyError(RuntimeError):
    pass


def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()


def load_all():
    P = lambda *a: os.path.join(PARENT, *a)
    closes = {"btc": load(P("data/btc.csv")), "eth": load(P("data/eth.csv")), "xaut": load(P("data/xaut_spliced.csv"))}
    o = {n: pd.read_csv(os.path.join(HERE, f"{n}_ohlc.csv"), index_col=0, parse_dates=True) for n in ("btc", "eth")}
    f = {n: pd.read_csv(os.path.join(HERE, f"{n}_funding_binance.csv"), index_col=0, parse_dates=True).iloc[:, 0] for n in ("btc", "eth")}
    return closes, o, f


def build_adv(closes, ohlc):
    px = pd.DataFrame(closes).sort_index(); adv = pd.DataFrame(0.0, index=px.index, columns=COLS)
    for n in ("btc", "eth"):
        low = ohlc[n]["low"].reindex(px.index); prev = px[n].shift(1)
        adv[n] = (low / prev - 1.0).clip(upper=0.0).fillna(0.0)
    r = px["xaut"].pct_change(fill_method=None).fillna(0.0)
    adv["xaut"] = np.minimum(r, 0.0) - PLAN["xaut_adv"]
    adv.loc[px["xaut"].isna(), "xaut"] = 0.0
    return adv


def build_fund(closes, f, start=PLAN["start_fund"], flat=None):
    """bps/hari per aset (jumlah 8 jam dalam tanggal UTC). xaut memakai seri BTC (proksi, dicatat). Cakupan < 99% => StudyError (fail-closed)."""
    px = pd.DataFrame(closes).sort_index(); idx = px.loc[start:].index
    if flat is not None:
        return pd.DataFrame(float(flat), index=px.index, columns=COLS)
    d = {n: f[n].groupby(f[n].index.normalize()).sum() for n in f}
    out = pd.DataFrame(index=px.index, columns=COLS, dtype=float)
    for n in ("btc", "eth"):
        out[n] = d[n].reindex(px.index)
    out["xaut"] = out["btc"]
    miss = out.loc[idx].isna().mean().max()
    if miss > 0.01:
        raise StudyError(f"cakupan funding kurang: {miss:.3f} hari kosong")
    return out.fillna(out.rolling(30, min_periods=5).mean()).fillna(0.0)


def band_orders(w, t, band):
    o = {}
    for k in t:
        d = t[k] - w.get(k, 0.0)
        if (t[k] == 0 and w.get(k, 0.0) > 0) or abs(d) > band * max(t[k], 0.05):
            o[k] = d
    return o


def _prep(closes, tgt, start, fund, adv, lag=1):
    """Matriks numpy: ret, target(shift lag), funding bps/hari, gerak merugikan. Sekali per (data, arm)."""
    px = pd.DataFrame(closes).sort_index(); ret = px.pct_change(fill_method=None)
    idx = px.loc[start:].index
    R = ret.loc[idx].fillna(0.0)[COLS].values.astype(float)
    T = (tgt.reindex(px.index).shift(lag).fillna(0.0)).loc[idx][COLS].values.astype(float)
    Z = pd.DataFrame(0.0, index=px.index, columns=COLS)
    F = (fund.reindex(px.index)[COLS].fillna(0.0) if fund is not None else Z).loc[idx].values.astype(float)
    A = (adv.reindex(px.index)[COLS].fillna(0.0) if adv is not None else Z).loc[idx].values.astype(float)
    return idx, R, T, F, A


MMRV = np.array([MMR[c] for c in COLS])


def _core(R, T, F, A, L, cost, band=0.20, stress=PLAN["stress_mult"]):
    n = len(R); w = np.zeros(len(COLS)); net = np.empty(n); turn = np.empty(n); gross = np.empty(n)
    liq = np.zeros(n, bool); liqs = np.zeros(n, bool); eqmin = np.ones(n)
    for i in range(n):
        gr = w.sum(); drag = float((w * F[i]).sum()) / 1e4
        if gr > 0:
            a = A[i]; eq = 1.0 + float((w * a).sum()); mm = float((MMRV * w * (1 + a)).sum())
            liq[i] = eq <= mm; eqmin[i] = eq
            a2 = a * stress; eq2 = 1.0 + float((w * a2).sum()); mm2 = float((MMRV * w * (1 + a2)).sum())
            liqs[i] = eq2 <= mm2; eqmin[i] = min(eqmin[i], eq2)
        r = R[i]; g = float((w * r).sum())
        w = w * (1 + r) / (1 + g) if g != -1.0 else w * 0.0
        t = T[i] * L; d = t - w
        hit = np.where((t == 0.0) & (w > 0.0), True, np.abs(d) > band * np.maximum(t, 0.05))
        tv = float(np.abs(d[hit]).sum()); w = w + np.where(hit, d, 0.0)
        net[i] = (1 + g) * (1 - tv * cost) - 1 - drag; turn[i] = tv; gross[i] = gr
    return pd.DataFrame({"net": net, "turn": turn, "gross": gross, "liq": liq, "liq_stress": liqs, "eq_stress": eqmin}, index=T.index if False else None)


def lev_sim(closes, tgt, L, start, cost, fund=None, adv=None, lag=1, band=0.20):
    """Skala L + funding + cek likuidasi. Kontrol: L=1, fund=None, adv=None == bt_indep.simulate()."""
    idx, R, T, F, A = _prep(closes, tgt, start, fund, adv, lag)
    res = _core(R, T, F, A, L, cost, band); res.index = idx
    return res


class Fast:
    """Pembungkus matriks ter-cache untuk kontrol geser (hindari rebuild tiap shift)."""
    def __init__(self, closes, tgt, fund, adv):
        self.closes, self.tgt, self.fund, self.adv = closes, tgt, fund, adv
        self.idx, self.R, self.T, self.F, self.A = _prep(closes, tgt, PLAN["start_fund"], fund, adv, 1)
        self.pos = self.idx.get_indexer([PLAN["start_main"]])[0]
    def run(self, tgtmat, L, cost):
        res = _core(self.R, tgtmat, self.F, self.A, L, cost); res.index = self.idx; return res


def M5(r): return float(r.mean() * 5 / 24 * 100)


def mdd(r):
    eq = (1 + r.clip(lower=-1)).cumprod(); return float((eq / eq.cummax() - 1).min() * 100)


def block_boot(r, seed=PLAN["seed"], nb=PLAN["n_boot"], bl=PLAN["block"]):
    x = r.values; n = len(x); rng = np.random.default_rng(seed); k = math.ceil(n / bl)
    st = rng.integers(0, n - bl + 1, size=(nb, k)); ix = (st[:, :, None] + np.arange(bl)[None, None, :]).reshape(nb, -1)[:, :n]
    m = x[ix].mean(axis=1) * 5 / 24 * 100
    return {"ci95": [round(float(np.percentile(m, 2.5)), 5), round(float(np.percentile(m, 97.5)), 5)], "p_M_le_0": round(float((m <= 0).mean()), 4)}


def summarize(res: pd.DataFrame, boot=False):
    out = {}
    for tag, s in (("2022+", PLAN["start_main"]), ("2024+", PLAN["start_oos"]), ("OOS26", PLAN["start_oos26"])):
        r = res["net"].loc[s:]; out[f"M_{tag}"] = round(M5(r), 5)
    r = res["net"].loc[PLAN["start_main"]:]; rc = r.clip(lower=-0.999999)
    out["G5j_geom_2022+"] = round(float(np.log1p(rc).mean() * 5 / 24 * 100), 5)
    out["MDD_2022+"] = round(mdd(r), 1)
    w = PLAN["win_days"]; rm = r.rolling(w).mean().dropna() * 5 / 24 * 100; rr = (1 + rc).rolling(w).apply(np.prod, raw=True).dropna() - 1
    out["P_win31_M>=target"] = round(float((rm >= PLAN["target_M"]).mean()), 3); out["P_win31_rugi"] = round(float((rr < 0).mean()), 3)
    out["win31_terburuk_%"] = round(float(rr.min() * 100), 1)
    ann = r.groupby(r.index.year).apply(M5); out["tahun_M>=target"] = f"{int((ann >= PLAN['target_M']).sum())}/{len(ann)}"
    full = res.loc[PLAN["start_fund"]:]
    out["hari_likuidasi_dasar"] = int(full["liq"].sum()); out["hari_likuidasi_stres"] = int(full["liq_stress"].sum())
    out["eq_stres_min"] = round(float(full["eq_stress"].min()), 3); out["hari_eq_stres<=0.2"] = int((full["eq_stress"] <= PLAN["near_liq"]).sum())
    out["gross_rata2"] = round(float(res["gross"].loc[PLAN["start_main"]:].mean()), 3); out["gross_maks"] = round(float(res["gross"].max()), 2)
    out["biaya_turnover_tahunan"] = round(float(res["turn"].loc[PLAN["start_main"]:].mean() * 365), 2)
    if boot:
        out.update(block_boot(r))
    return out


def control_p(fast, L, actual_M, cost=PLAN["cost_primary"]):
    rng = np.random.default_rng(PLAN["seed"] + 1)
    nz = np.where(np.abs(fast.T).sum(axis=1) > 0)[0]; a0 = int(nz[0]); vals = fast.T[a0:].copy(); ms = []
    for _ in range(PLAN["n_ctrl"]):
        k = int(rng.integers(180, len(vals) - 180)); sh = fast.T.copy(); sh[a0:] = np.roll(vals, k, axis=0)
        ms.append(M5(fast.run(sh, L, cost)["net"].iloc[fast.pos:]))
    ms = np.array(ms)
    return {"p_kontrol": round(float((np.sum(ms >= actual_M) + 1) / (len(ms) + 1)), 4), "kontrol_M_median": round(float(np.median(ms)), 5),
            "kontrol_M_p95": round(float(np.percentile(ms, 95)), 5)}


def verdict(sm, ctrl):
    a = sm["M_2022+"] >= PLAN["target_M"]
    b = sm["M_OOS26"] > 0 and sm["M_2024+"] > 0
    c = sm["hari_likuidasi_stres"] == 0 and sm["MDD_2022+"] >= PLAN["mdd_cap"]
    d = sm.get("p_M_le_0", 1.0) < PLAN["p_alpha"] and (ctrl or {}).get("p_kontrol", 1.0) < PLAN["p_alpha"]
    g = {"A_target": a, "B_oos_positif": b, "C_risiko_likuidasi": c, "D_bukti_edge": d}
    if not (a and b and c):
        v = "TIDAK_LAYAK"
    else:
        v = "TERBUKTI" if d else "LAYAK_PAPER_BUKAN_BUKTI"
    return v, g


def main():
    closes, ohlc, f = load_all(); adv = build_adv(closes, ohlc); fund = build_fund(closes, f); today = pd.Timestamp(PLAN["today"])
    # --- cek data: close csv vs OHLC Binance
    chk = {n: float((ohlc[n]["close"].reindex(closes[n].index) / closes[n] - 1).abs().dropna().gt(0.005).mean()) for n in ("btc", "eth")}
    if max(chk.values()) > 0.01:
        raise StudyError(f"close csv != OHLC Binance: {chk}")
    # --- triangulasi funding SoDEX vs Binance (jendela 2-25 Okt 2026)
    rows = [json.loads(x) for x in open(os.path.join(PARENT, "..", "..", "..", "data/sodex_funding/funding_rates_history.jsonl")) if x.strip()]
    sd = pd.DataFrame(rows); sd["t"] = pd.to_datetime(sd.funding_time_ms, unit="ms")
    sbtc = float(sd[sd.symbol == "BTC"].funding_rate_bps.mean() * 24); bwin = float(f["btc"].loc[sd.t.min():sd.t.max()].mean() * 3)
    out = {"plan": {k: (list(v) if isinstance(v, tuple) else v) for k, v in PLAN.items() if k != "L_fine"}, "cek_close_vs_ohlc_frac_beda>0.5%": chk,
           "triangulasi_funding_bps_hari": {"sodex_BTC_24hari": round(sbtc, 2), "binance_BTC_jendela_sama": round(bwin, 2), "binance_BTC_2022+_rata2": round(float(fund["btc"].loc[PLAN["start_main"]:].mean()), 2),
                                            "binance_ETH_2022+_rata2": round(float(fund["eth"].loc[PLAN["start_main"]:].mean()), 2)},
           "arms": {}, "sensitivitas": {}, "kelly_kurva": {}, "L_kritis": {}}
    for arm in PLAN["arms"]:
        T = eng.target_history(closes, mode=arm, today=today); A = {}; fast = Fast(closes, T, fund, adv)
        base = simulate(closes, T, start=PLAN["start_main"], cost=PLAN["cost_primary"])[0]
        A["spot_L1_tanpa_funding_M"] = round(M5(base), 5)                                  # acuan live saat ini (ekuivalen suite PRAREG-23b)
        for L in PLAN["L_grid"]:
            res = lev_sim(closes, T, L, PLAN["start_fund"], PLAN["cost_primary"], fund, adv)
            sm = summarize(res, boot=True); ctrl = control_p(fast, L, sm["M_2022+"]) if L in (1.0, 2.0) else None
            v, g = verdict(sm, ctrl); A[f"L={L}"] = {**sm, "kontrol": ctrl, "vonis": v, "gerbang": g}
        out["arms"][arm] = A
        # sensitivitas biaya & funding pada L grid (hanya M 2022+ dan likuidasi)
        S = {}
        for lab, kw in (("biaya7bps", dict(cost=0.0007, fund=fund)), ("biaya15bps", dict(cost=0.0015, fund=fund)), ("biaya25bps", dict(cost=0.0025, fund=fund)),
                        ("funding_SoDEX_1.3bps/hari", dict(cost=PLAN["cost_primary"], fund=build_fund(closes, f, flat=PLAN["sodex_fund_bps_day"]))),
                        ("funding_0", dict(cost=PLAN["cost_primary"], fund=build_fund(closes, f, flat=0.0)))):
            S[lab] = {f"L={L}": round(M5(lev_sim(closes, T, L, PLAN["start_main"], kw["cost"], kw["fund"], adv)["net"]), 5) for L in PLAN["L_grid"]}
        out["sensitivitas"][arm] = S
        # kurva fine: M, geometrik, MDD, likuidasi pertama
        K, first_liq, first_liq_s, mdd_cap_L = {}, None, None, None
        for L in PLAN["L_fine"]:
            res = lev_sim(closes, T, float(L), PLAN["start_fund"], PLAN["cost_primary"], fund, adv); r = res["net"].loc[PLAN["start_main"]:]
            K[f"{L:.1f}"] = {"M": round(M5(r), 5), "G": round(float(np.log1p(r.clip(lower=-0.999999)).mean() * 5 / 24 * 100), 5), "MDD": round(mdd(r), 1),
                              "liq": int(res["liq"].sum()), "liq_s": int(res["liq_stress"].sum())}
            if first_liq is None and K[f"{L:.1f}"]["liq"] > 0: first_liq = float(L)
            if first_liq_s is None and K[f"{L:.1f}"]["liq_s"] > 0: first_liq_s = float(L)
            if mdd_cap_L is None and K[f"{L:.1f}"]["MDD"] < PLAN["mdd_cap"]: mdd_cap_L = float(L)
        Ls = [float(k) for k in K]; Gs = [K[f"{x:.1f}"]["G"] for x in Ls]; Ms = [K[f"{x:.1f}"]["M"] for x in Ls]
        need = next((x for x, m in zip(Ls, Ms) if m >= PLAN["target_M"]), None)
        out["kelly_kurva"][arm] = K
        out["L_kritis"][arm] = {"L_pertama_M>=target(grid 0.5)": need, "L_G_maks(Kelly-geometrik)": Ls[int(np.argmax(Gs))], "L_pertama_MDD<cap": mdd_cap_L,
                                "L_pertama_likuidasi_dasar": first_liq, "L_pertama_likuidasi_stres": first_liq_s}
    json.dump(out, open(os.path.join(HERE, "lev_results.json"), "w"), indent=1, default=str)
    return out


if __name__ == "__main__":
    o = main(); print(json.dumps({"triang": o["triangulasi_funding_bps_hari"], "L_kritis": o["L_kritis"]}, indent=1))
    for arm, A in o["arms"].items():
        print("==", arm, "spot L1 (acuan):", A["spot_L1_tanpa_funding_M"])
        for k, v in A.items():
            if k.startswith("L="):
                print(k, {x: v[x] for x in ("M_2022+", "M_2024+", "M_OOS26", "MDD_2022+", "P_win31_M>=target", "P_win31_rugi", "win31_terburuk_%", "hari_likuidasi_dasar", "hari_likuidasi_stres", "eq_stres_min", "p_M_le_0", "ci95", "vonis")}, v["kontrol"])
