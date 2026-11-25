#!/usr/bin/env python3
"""Baterai PAPER TEST PRAREG-36 — verifikasi mekanisme, akuntansi, ketahanan, dan daya uji.
Read-only & offline (kecuali tes konkurensi yang memakai proses lokal). Tidak ada order/jaringan exchange."""
from __future__ import annotations
import json, os, shutil, subprocess, sys, tempfile
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); PARENT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, PARENT)
import hybrid36 as h36, hybrid_exec as hx, lev_hybrid as lh, lev_study as ls, mode_a_engine as eng

FWD = os.path.join(PARENT, "forward"); R = []


def rec(cid, nama, ok, bukti):
    R.append({"id": cid, "uji": nama, "lulus": bool(ok), "bukti": bukti}); print(f"{'PASS' if ok else 'FAIL'} {cid} {nama} :: {bukti}")


def synth(path, start="2025-03-01", n=40, scale=None):
    os.makedirs(path, exist_ok=True)
    for k in h36.SYMS: shutil.copy(os.path.join(FWD, f"{k}.csv"), os.path.join(path, f"{k}.csv"))
    px = {k: eng.load_csv(os.path.join(path, f"{k}.csv")) for k in h36.SYMS}
    if scale:
        for k in h36.SYMS: px[k] = scale(px[k])
        for k in h36.SYMS: px[k].rename("close").to_csv(os.path.join(path, f"{k}.csv"), index_label="date")
    th = {a: eng.target_history(px, mode=a, validate=False) for a in h36.PLAN36["cells"]}
    idx = pd.date_range(start, periods=n, freq="D"); rows = []
    for i, d in enumerate(idx):
        rows.append({"kind": "rec", "asof": str(d.date()), "backfill": False,
                     "closes": {k: float(px[k].loc[d]) for k in h36.SYMS},
                     "targets": {a: {k: float(th[a].loc[d, k]) for k in h36.SYMS} for a in h36.PLAN36["cells"]},
                     "funding_bps": {"btc": 1.8, "eth": 1.5, "xaut": 1.8}})
    with open(os.path.join(path, "ledger.jsonl"), "w") as f:
        for r in rows: f.write(json.dumps(r, sort_keys=True) + "\n")
    return path, rows, idx


WF, WL = "2025-03-01", "2025-03-30"
TMP = tempfile.mkdtemp(prefix="p36_")


# ---------- D: determinisme & deteksi manipulasi ----------
d, rows, idx = synth(f"{TMP}/d1")
o1 = h36.evaluate(d, WF, WL); o2 = h36.evaluate(d, WF, WL)
rec("D01", "evaluasi deterministik (dua run identik)", json.dumps(o1, sort_keys=True, default=str) == json.dumps(o2, sort_keys=True, default=str),
    f"M_B2={o1['hasil']['B2']['M_per5h_pct']}, n={o1['n_hari_window']}")

d2, rows2, _ = synth(f"{TMP}/d2")
rows2[5]["targets"]["B2"]["btc"] += 1e-6
open(f"{d2}/ledger.jsonl", "w").write("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows2))
o = h36.evaluate(d2, WF, WL)
rec("D02", "G2 mendeteksi target dimanipulasi 1e-6", (not o["gerbang"]["G2_target_deterministik"]) and o["vonis"] == "DATA_INVALID", f"selisih={o['g2_selisih']}")

d3, rows3, _ = synth(f"{TMP}/d3")
open(f"{d3}/ledger.jsonl", "w").write("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows3[:10] + rows3[11:]))
o = h36.evaluate(d3, WF, WL)
rec("D03", "G1 menolak ledger bolong", (not o["gerbang"]["G1_data_lengkap"]) and bool(o["gap_tanggal"]), f"gap={o['gap_tanggal']}")

d4, rows4, _ = synth(f"{TMP}/d4")
open(f"{d4}/ledger.jsonl", "w").write("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows4 + [rows4[3]]))
o = h36.evaluate(d4, WF, WL)
rec("D04", "baris duplikat tidak menggandakan hari", o["n_hari_window"] == o1["n_hari_window"], f"n={o['n_hari_window']}")

d5, rows5, _ = synth(f"{TMP}/d5")
for r in rows5[:4]: r["backfill"] = True
open(f"{d5}/ledger.jsonl", "w").write("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows5))
o = h36.evaluate(d5, WF, WL)
rec("D05", "G1 menolak backfill berlebih (>3)", (not o["gerbang"]["G1_data_lengkap"]) and o["backfill_n"] == 4, f"backfill={o['backfill_n']}")

d6, rows6, _ = synth(f"{TMP}/d6")
for r in rows6: r["funding_bps"] = None
open(f"{d6}/ledger.jsonl", "w").write("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows6))
o = h36.evaluate(d6, WF, WL)
rec("D06", "G1 menolak funding kosong di jendela", (not o["gerbang"]["G1_data_lengkap"]) and o["funding_hilang_di_jendela"] == 30, f"hilang={o['funding_hilang_di_jendela']} hari")

# ---------- A: akuntansi ----------
idx2 = pd.date_range("2024-01-01", periods=40, freq="D"); c = {k: pd.Series(100.0, index=idx2) for k in ls.COLS}
T = pd.DataFrame(0.0, index=idx2, columns=ls.COLS); T["btc"] = 0.5; T["eth"] = 0.5
F = pd.DataFrame(1.0, index=idx2, columns=ls.COLS)
res = lh.hybrid_sim(c, T, 2.0, "2024-01-03", 0.001, 0.001, F)
i_entry = int(np.argmax(res["turn_s"].values > 0))                    # hari entry sebenarnya (lag 1)
n1, n2 = float(res["net"].iloc[i_entry]), float(res["net"].iloc[i_entry + 3])   # hari entry, hari stabil
exp1 = -2.0 * 0.001                 # entry: spot 1,0 + perp 1,0 notional @10 bps; funding belum berjalan (buka di penutupan)
exp2 = -(1.0 * (0.5 * 1 + 0.5 * 1) / 1e4)   # hari stabil: hanya funding lapisan perp
rec("A01", "akuntansi biaya+funding eksak (hari entry & hari stabil)", abs(n1 - exp1) < 1e-12 and abs(n2 - exp2) < 1e-12,
    f"entry {n1:.8f} vs {exp1:.8f} | stabil {n2:.8f} vs {exp2:.8f}")

gross = float(res["gross"].iloc[10]); spot = float(T["btc"].iloc[10] + T["eth"].iloc[10])
rec("A02", "pemisahan lapisan: gross 1x, perp (L-1)x", abs(gross - spot) < 1e-12, f"gross={gross:.4f}, target total={spot:.4f}, perp={spot*(2.0-1):.4f}")

idx3 = pd.date_range("2024-01-01", periods=40, freq="D"); px = pd.Series(100.0, index=idx3); px.iloc[20] = 150.0; px.iloc[21:] = 150.0
c3 = {k: px.copy() for k in ls.COLS}; T3 = pd.DataFrame(0.0, index=idx3, columns=ls.COLS)
T3.loc[idx3[20], "btc"] = 1.0                                        # target muncul TEPAT di hari lompatan
r3 = lh.hybrid_sim(c3, T3, 1.5, "2024-01-03", 0.0, 0.0)["net"]
rec("A03", "anti-lookahead: target hari-H tidak dipakai hari-H", abs(float(r3.loc[idx3[20]])) < 1e-12, f"return hari lompatan={float(r3.loc[idx3[20]]):.2e}")

# ---------- R: ketahanan operasional ----------
d7, rows7, _ = synth(f"{TMP}/r1")
a = h36.record(d7, today=pd.Timestamp("2026-10-26"), update=False, fetch_funding=False)
n_before = len([1 for x in open(f"{d7}/ledger.jsonl") if '"rec"' in x])
b = h36.record(d7, today=pd.Timestamp("2026-10-26"), update=False, fetch_funding=False)
n_after = len([1 for x in open(f"{d7}/ledger.jsonl") if '"rec"' in x])
rec("R01", "record idempoten (run kedua tidak menambah baris)", n_before == n_after and b["ditulis"] == [], f"{n_before} -> {n_after}, ditulis={b['ditulis']}")

d8 = f"{TMP}/r2"; os.makedirs(d8, exist_ok=True)
for k in h36.SYMS: shutil.copy(os.path.join(FWD, f"{k}.csv"), os.path.join(d8, f"{k}.csv"))
code = ("import sys; sys.path[:0]=[%r,%r]; import hybrid36,pandas as pd; "
        "hybrid36.record(%r, today=pd.Timestamp('2026-10-26'), update=False, fetch_funding=False)") % (HERE, PARENT, d8)
ps = [subprocess.Popen([sys.executable, "-W", "ignore", "-c", code]) for _ in range(3)]
[p.wait() for p in ps]
nrow = len([1 for x in open(f"{d8}/ledger.jsonl") if '"rec"' in x])
rec("R02", "3 proses record bersamaan -> tetap 1 baris (flock)", nrow == 1, f"baris rec={nrow}")

d9, _, _ = synth(f"{TMP}/r3")
st = {"spot": {}, "perp": {}, "equity_usdc": 243.02}; rc = hx.latest_target(d9)
o_ = hx.intents(rc, st, "B2"); ap1 = hx.apply(d9, rc, st, o_)
o2_ = hx.intents(rc, ap1, "B2"); ap2 = hx.apply(d9, rc, ap1, o2_)
rec("R03", "apply dua kali: putaran kedua 0 order", len(o_) > 0 and len(o2_) == 0, f"order {len(o_)} -> {len(o2_)}")

d10 = f"{TMP}/r4"; os.makedirs(d10, exist_ok=True)
try:
    hx.latest_target(d10); ok = False
except SystemExit: ok = True
rec("R04", "eksekutor menolak direktori tanpa ledger", ok, "SystemExit bersih")

tiny = hx.intents(rc, {"spot": {}, "perp": {}, "equity_usdc": 1.0}, "B2")
rec("R05", "notional < 10 USDC dibuang", tiny == [], f"{len(tiny)} order")

refused = []
for flag in hx.LIVE_FLAGS:
    try:
        hx.guard_live({flag: "1"}); refused.append(flag)
    except hx.LiveRefused: pass
rec("R06", "5 penanda live semuanya ditolak", len(refused) == 0, f"lolos={refused or 'tidak ada'}")

# ---------- X: risiko & statistik ----------
mmr = ls.MMR["btc"]; L = 1.5; a_h = (mmr * (L - 1) - 1) / (L - mmr * (L - 1))
idx4 = pd.date_range("2023-01-01", periods=120, freq="D"); c4 = {k: pd.Series(100.0, index=idx4) for k in ls.COLS}
T4 = pd.DataFrame(0.0, index=idx4, columns=ls.COLS); T4["btc"] = 1.0
def adv_at(x):
    a_ = pd.DataFrame(0.0, index=idx4, columns=ls.COLS); a_.loc[idx4[60], "btc"] = x; return a_
safe = lh.hybrid_sim(c4, T4, L, "2023-01-01", 0.0, 0.0, None, adv_at(a_h + 0.01))["liq"].any()
hit = lh.hybrid_sim(c4, T4, L, "2023-01-01", 0.0, 0.0, None, adv_at(a_h - 0.01))["liq"].any()
rec("X01", "ambang likuidasi L=1,5 sesuai analitis", (not safe) and hit, f"a*={a_h:.4f} (-{abs(a_h)*100:.1f}%)")

n = 200; up = pd.Series([0.001] * n); dn = pd.Series([-0.001] * n)
p_up, p_dn = h36._boot(up), h36._boot(dn)
rec("X02", "bootstrap: seri naik -> p~0, turun -> p~1", p_up < 0.01 and p_dn > 0.99, f"p_naik={p_up}, p_turun={p_dn}")

rec("X03", "ambang BH 2 sel = 0,025", abs(h36.PLAN36["p_bh"] - 0.05 / 2) < 1e-12, f"p_bh={h36.PLAN36['p_bh']}")

# ---------- S: base rate & daya uji ----------
closes, ohlc, f = ls.load_all(); adv = ls.build_adv(closes, ohlc); fund = ls.build_fund(closes, f)
Tb = eng.target_history(closes, mode="B2", today=pd.Timestamp("2026-10-25"))
sim = lh.hybrid_sim(closes, Tb, 1.5, "2020-01-01", 0.001, 0.001, fund, adv)
r = sim["net"].loc["2022-01-01":]; rc_ = r.clip(lower=-0.999999)
M30 = (1 + rc_).rolling(30).apply(np.prod, raw=True).dropna() ** (5 / (24 * 30)) - 1
M30 *= 100
eq = (1 + rc_).cumprod(); dd = (eq / eq.cummax() - 1) * 100
MDD30 = dd.rolling(30).apply(lambda x: x.min(), raw=True).dropna()
nw = len(M30); pass_g3 = float((M30 >= 0.010).mean()); pass_g4 = float((MDD30 >= -35).mean())
both = float(((M30 >= 0.010).values & (MDD30 >= -35).values[:len(M30)]).mean())
rec("S01", "base rate 30-hari: peluang lolos G3 & G4 secara kebetulan", True,
    f"{nw} jendela | M>=0,010: {pass_g3:.1%} | MDD>=-35%: {pass_g4:.1%} | keduanya: {both:.1%}")

sd_d = float(r.std()); tcrit = 2.045
M_detect = tcrit * sd_d / np.sqrt(30) * 5 / 24 * 100
rec("S02", "daya uji: M terkecil yang bisa signifikan (p=0,025, n=30)", True,
    f"sd harian={sd_d*100:.2f}% -> M_min={M_detect:.4f} %/5j (target 0,010)")

rec("S03", "sebaran M 30-hari (p10/p50/p90)", True,
    f"{np.percentile(M30,10):.4f} / {np.percentile(M30,50):.4f} / {np.percentile(M30,90):.4f} %/5j")

out = {"utc": pd.Timestamp.utcnow().isoformat(), "n_uji": len(R), "lulus": sum(x["lulus"] for x in R),
       "gagal": [x["id"] for x in R if not x["lulus"]], "hasil": R,
       "base_rate": {"n_jendela": nw, "p_M_ge_target": pass_g3, "p_mdd_ok": pass_g4, "p_keduanya": both,
                     "p10_M": float(np.percentile(M30, 10)), "p50_M": float(np.percentile(M30, 50)), "p90_M": float(np.percentile(M30, 90)),
                     "M_detect_p025": float(M_detect), "sd_harian": sd_d}}
os.makedirs("/home/USER/anantara-sakti/reports/sodex", exist_ok=True)
json.dump(out, open("/home/USER/anantara-sakti/reports/sodex/PRAREG36_PAPER_TESTS.json", "w"), indent=1, default=str)
print(f"\nRINGKAS: {out['lulus']}/{out['n_uji']} lulus; gagal={out['gagal']}")
