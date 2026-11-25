#!/usr/bin/env python3
"""PRAREG-23b — SUITE PAPER TEST KOMPREHENSIF (historis + stres + eksekusi diskret + kontrol negatif + status forward).
Sepenuhnya read-only/dry-run. Seed tetap -> deterministik. Keluaran: reports/sodex/PRAREG23B_PAPER_SUITE_<tgl>.{json,md}
Target dinyatakan sebagai M = rata-rata return harian bersih x 5/24 x 100 (% per 5 jam); target M >= 0,010."""
from __future__ import annotations
import datetime as dt, json, math, os, sys, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
import mode_a_engine as eng
import paper_exec, paper_forward
from bt_indep import load, simulate, stats

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
BN = {"btc": load("data/btc.csv"), "eth": load("data/eth.csv"), "xaut": load("data/xaut_spliced.csv")}
TODAY = pd.Timestamp("2026-10-25")
ARMS = ("A", "B1", "B2")
COSTS = {"realistis_7bps": 0.0007, "primer_10bps": 0.0010, "konservatif_15bps": 0.0015, "stres_25bps": 0.0025}
PERIODS = {"2019+": "2019-01-01", "2022+": "2022-01-01", "2024+": "2024-01-01", "OOS26(24Mei+)": "2026-05-24"}
TGT = 0.010
rng = np.random.default_rng(20261026)
M5 = lambda r: float(r.mean() * 5 / 24 * 100)


def sh(r): return float(r.mean() / r.std() * math.sqrt(365)) if r.std() > 0 else 0.0
def mdd(r): e = (1 + r).cumprod(); return float((e / e.cummax() - 1).min() * 100)
def cum(r): return float(((1 + r).prod() - 1) * 100)


def s1_matrix(T):
    out, R = {}, {}
    for a in ARMS:
        for cn, c in COSTS.items():
            r, tv = simulate(BN, T[a], start="2019-01-01", cost=c); R[(a, cn)] = r
            for pn, p0 in PERIODS.items():
                x = r.loc[p0:]
                out[f"{a}|{cn}|{pn}"] = {"M": round(M5(x), 5), "sharpe": round(sh(x), 2), "mdd": round(mdd(x), 1), "cum_pct": round(cum(x), 1),
                                         "n": len(x), "turnover_thn": round(float(tv.loc[p0:].sum() / len(x) * 365), 2), "capai_target": bool(M5(x) >= TGT)}
    return out, R


def s2_sens(T):
    out = {}
    base = T["A"]
    for lag in (0, 1, 2, 3):
        r, _ = simulate(BN, base, start="2022-01-01", cost=0.0010, lag=lag); out[f"lag={lag}"] = round(M5(r), 5)
    for band in (0.05, 0.10, 0.20, 0.30, 0.50):
        r, _ = simulate(BN, base, start="2022-01-01", cost=0.0010, band=band); out[f"band={band}"] = round(M5(r), 5)
    for vt in (0.25, 0.35, 0.50, 0.70, 1.00):
        t = eng.target_history(BN, vt=vt, today=TODAY); r, _ = simulate(BN, t, start="2022-01-01", cost=0.0010); out[f"VT={vt}"] = round(M5(r), 5)
    return out


def s3_rolling(R):
    out = {}
    for a in ARMS:
        for cn in ("realistis_7bps", "primer_10bps"):
            r = R[(a, cn)].loc["2022-01-01":]; v = r.values; n = len(v); W = 31
            M, C, D = [], [], []
            for i in range(n - W + 1):
                w = v[i:i + W]; e = np.cumprod(1 + w)
                M.append(w.mean() * 5 / 24 * 100); C.append((e[-1] - 1) * 100); D.append(((e / np.maximum.accumulate(e)) - 1).min() * 100)
            M, C, D = map(np.array, (M, C, D))
            out[f"{a}|{cn}"] = {"n_win": len(M), "M_p10_p50_p90": [round(float(np.percentile(M, q)), 4) for q in (10, 50, 90)],
                                "P(M31>=0.010)": round(float((M >= TGT).mean()), 3), "P(cum<0)": round(float((C < 0).mean()), 3),
                                "P(G3 mdd>=-10)": round(float((D >= -10).mean()), 3), "P(G4 cum>=-5)": round(float((C >= -5).mean()), 3),
                                "P(G3&G4)": round(float(((D >= -10) & (C >= -5)).mean()), 3), "cum_p05": round(float(np.percentile(C, 5)), 2),
                                "mdd_p05": round(float(np.percentile(D, 5)), 2)}
    return out


def s4_boot(R, n=10000, blk=30):
    out = {}
    for a in ARMS:
        v = R[(a, "primer_10bps")].loc["2022-01-01":].values; N = len(v); res = []
        for _ in range(n):
            s = []
            while len(s) < 365:
                i = rng.integers(0, N - blk); s += list(v[i:i + blk])
            res.append(np.mean(s[:365]) * 5 / 24 * 100)
        res = np.array(res)
        out[a] = {"M_median": round(float(np.median(res)), 5), "CI95": [round(float(np.percentile(res, 2.5)), 5), round(float(np.percentile(res, 97.5)), 5)],
                  "P(M>=0.010)": round(float((res >= TGT).mean()), 3), "P(M<0)": round(float((res < 0).mean()), 3)}
    return out


def s5_null(T, nshift=400):
    """Kontrol negatif: geser sirkular target A (menjaga distribusi eksposur, merusak timing). p = P(null >= nyata)."""
    tg = T["A"].loc["2021-12-01":]; real, _ = simulate(BN, T["A"], start="2022-01-01", cost=0.0010); m_real = M5(real)
    N = len(tg); nulls = []
    for k in rng.choice(np.arange(60, N - 60), nshift, replace=False):
        t2 = pd.DataFrame(np.roll(tg.values, int(k), axis=0), index=tg.index, columns=tg.columns)
        r, _ = simulate(BN, t2, start="2022-01-01", cost=0.0010); nulls.append(M5(r))
    nulls = np.array(nulls)
    return {"M_nyata": round(m_real, 5), "null_mean": round(float(nulls.mean()), 5), "null_p95": round(float(np.percentile(nulls, 95)), 5),
            "p_empiris": round(float((np.sum(nulls >= m_real) + 1) / (len(nulls) + 1)), 4), "n_null": len(nulls)}


def s6_discrete(T, start="2021-02-01", usd=243.02):
    """Eksekusi diskret nyata: $243,02, step & minNotional SoDEX, fee taker 0,065% + spread 0,6 bps/sisi, jual dulu."""
    px = pd.DataFrame(BN).sort_index(); out = {}
    for a in ARMS:
        tl = T[a].reindex(px.index).shift(1).fillna(0.0); hold = {k: 0.0 for k in BN}; cash = usd; eq = []; fees = 0.0; skipped = 0; nord = 0
        for d in px.loc[start:].index:
            pr = {k: float(px.loc[d, k]) for k in BN}
            p = eng.plan_orders({k: float(tl.loc[d, k]) for k in BN}, hold, pr, cash)
            for o in p["orders"]:
                k = o["asset"]; sl = 0.00006
                if o["side"] == "BUY":
                    c = o["notional"] * (1 + 0.00065 + sl); cash -= c; hold[k] += o["qty"]; fees += c - o["notional"]
                else:
                    cash += o["notional"] * (1 - 0.00065 - sl); hold[k] -= o["qty"]; fees += o["notional"] * (0.00065 + sl)
            skipped += len(p["skipped"]); nord += len(p["orders"])
            eq.append(cash + sum(hold[k] * pr[k] for k in BN))
        e = pd.Series(eq, index=px.loc[start:].index); r = e.pct_change().fillna(0.0)
        ideal, _ = simulate(BN, T[a], start=start, cost=0.00071)
        out[a] = {"equity_akhir": round(float(e.iloc[-1]), 2), "M_diskret_2022+": round(M5(r.loc["2022-01-01":]), 5), "M_ideal_2022+": round(M5(ideal.loc["2022-01-01":]), 5),
                  "selisih_M": round(M5(r.loc["2022-01-01":]) - M5(ideal.loc["2022-01-01":]), 5), "n_order": nord, "n_dilewati": skipped, "fee_total_usd": round(fees, 2),
                  "mdd_diskret": round(mdd(r.loc["2022-01-01":]), 1)}
    return out


def s7_tail(R):
    out = {}
    for a in ARMS:
        r = R[(a, "primer_10bps")].loc["2022-01-01":]
        out[a] = {"hari_terburuk_pct": round(float(r.min() * 100), 2), "5hari_terburuk_pct": round(float(((1 + r).rolling(5).apply(np.prod, raw=True) - 1).min() * 100), 2),
                  "31hari_terburuk_pct": round(float(((1 + r).rolling(31).apply(np.prod, raw=True) - 1).min() * 100), 2), "mdd_total": round(mdd(r), 1)}
    return out


def s8_forward():
    fd = os.path.join(HERE, "forward"); o = {"eval": paper_forward.evaluate(fd), "paper_exec": paper_exec.report(fd)}
    p = os.path.join(fd, "spot_book.jsonl")
    if os.path.exists(p):
        rows = [json.loads(x) for x in open(p) if x.strip()]; st = {}
        for a in ("btc", "eth", "xaut"):
            sp = [r["a"][a]["spread_bps"] for r in rows if "spread_bps" in r["a"].get(a, {})]
            c60 = [r["a"][a]["cost"]["60"]["buy"] for r in rows if "cost" in r["a"].get(a, {}) and r["a"][a]["cost"]["60"]["buy"] is not None]
            st[a] = {"n": len(sp), "spread_bps_med": round(float(np.median(sp)), 3) if sp else None, "spread_bps_max": round(max(sp), 3) if sp else None,
                     "biaya60usd_bps_med": round(float(np.median(c60)), 3) if c60 else None, "n_error": sum(1 for r in rows if "error" in r["a"].get(a, {}))}
        o["buku_spot"] = st
    return o


def run():
    T = {m: eng.target_history(BN, mode=m, today=TODAY) for m in ARMS}
    res = {"dibuat_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "target": "M>=0.010 %/5j", "data_bar_terakhir": str(BN["btc"].index[-1].date()),
           "engine_sha256": paper_forward.sha(os.path.join(HERE, "mode_a_engine.py"))}
    res["S1_matriks"], R = s1_matrix(T); print("S1 ok", flush=True)
    res["S2_sensitivitas_A"] = s2_sens(T); print("S2 ok", flush=True)
    res["S3_jendela31"] = s3_rolling(R); print("S3 ok", flush=True)
    res["S4_bootstrap_tahunan"] = s4_boot(R); print("S4 ok", flush=True)
    res["S5_kontrol_negatif_A"] = s5_null(T); print("S5 ok", flush=True)
    res["S6_eksekusi_diskret_243usd"] = s6_discrete(T); print("S6 ok", flush=True)
    res["S7_ekor_risiko"] = s7_tail(R)
    res["S8_forward"] = s8_forward()
    p = res["S1_matriks"]
    res["ringkasan"] = {a: {"M_2022+_primer": p[f"{a}|primer_10bps|2022+"]["M"], "M_2022+_realistis": p[f"{a}|realistis_7bps|2022+"]["M"],
                            "M_2024+_primer": p[f"{a}|primer_10bps|2024+"]["M"], "capai_target_2022+_primer": p[f"{a}|primer_10bps|2022+"]["capai_target"]} for a in ARMS}
    day = dt.date.today().isoformat()
    jp = os.path.join(ROOT, "reports", "sodex", f"PRAREG23B_PAPER_SUITE_{day}.json")
    json.dump(res, open(jp, "w"), indent=1, default=str)
    return res, jp


if __name__ == "__main__":
    res, jp = run(); print(jp)
    print(json.dumps(res["ringkasan"], indent=1)); print(json.dumps(res["S5_kontrol_negatif_A"])); print(json.dumps(res["S6_eksekusi_diskret_243usd"]))
