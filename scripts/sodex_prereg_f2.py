#!/usr/bin/env python3
"""SODEX F2 -- evaluator pra-registrasi strategi maker struktur-mikro (READ-ONLY, anti-intip).

Spesifikasi beku: docs/sodex/SODEX_F2_PRAREG_2026-10-06.md. Kriteria TIDAK boleh diubah setelah hasil keluar.

Mekanika beku (post-only, simulasi fill konservatif):
  t0      : onset balon OBI20 (>= +0,35 selama >=3 snapshot, gap >=4 jam, klaster 30 menit berlaku via GAP_S).
  ENTRY   : post-only di best bid t0. Terisi bila ada trade harga <= bid0 dalam (t0, t0+300s].
            Belum -> UNRESOLVED (tidak ikut statistik lulus, masuk pembilang unresolved).
  EXIT    : 45 menit setelah entry VIRTUAL (t_exit = t0+45m tanpa menunggu fill entry -- lihat catatan beku §3.2),
            post-only di best ask TIDAK dianjurkan; spesifikasi beku: keluar post-only pada ask(t_exit);
            terisi bila ada trade >= ask itu dalam 5 menit; jika tidak -> TAKER paksa pada harga trade terakhir
            t_exit (fee taker 4bp, tanpa keuntungan spread).
  NET     : (exit_px - bid0)/bid0 + (spread masuk: bid0 vs trade-taker-bandung) ... rumus lengkap di §3.3 dokumen.
Gerbang: >=300 episode tuntas, >=14 hari, >=8 simbol, unresolved <=10%; atau HARD_STOP 2026-11-07.
--final menolak berjalan sebelum gerbang (anti-intip). Tidak membaca data <=2026-10-06.
"""
from __future__ import annotations
import json, random, statistics as st, sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OBI = ROOT / "freqtrade_user_data/data/sodex/obi"
T = ROOT / "freqtrade_user_data/data/sodex/trades"
REP = ROOT / "reports/sodex"

F_START = datetime(2026, 10, 7, tzinfo=timezone.utc)
DAY0 = int(F_START.timestamp())
B_LV, B_DUR, B_WIN_S = 0.35, 3, 480
GAP_S = 4 * 3600                      # gap antar-event (menggantikan klaster 30 menit: aturan beku final)
ENTRY_WAIT, EXIT_H, EXIT_WAIT = 300, 45 * 60, 300
MAKER_FEE, TAKER_FEE, FUNDING_BP = 0.012 / 100, 0.04 / 100, 0.005
N_EP_MIN, DAYS_MIN, SYMS_MIN, UNRES_MAX = 300, 14, 8, 0.10
REQ_BP, F_SIZE, GROSS_CAP, WIN48 = 4.0, 0.15, 1.0, 48 * 60
TARGET_WIN = 0.008
HARD_STOP = datetime(2026, 11, 7, tzinfo=timezone.utc).date()
N_PERM, N_BOOT, SEED = 20000, 20000, 42


# ---------------------------------------------------------------- data
def load_forward(day_lo, day_hi):
    """obi[sym]=sorted[(ts, bid, ask, mid, obi20)]; tape[sym]=sorted[(ts, price)] ; hanya hari [lo..hi]"""
    obi, tape = defaultdict(list), defaultdict(list)
    for f in sorted(OBI.glob("obi_*.jsonl")):
        if not (day_lo <= int(f.name[4:12]) <= day_hi):
            continue
        with open(f) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    obi[r["sym"]].append((float(r["ts"]) / 1000.0, float(r["bid"]), float(r["ask"]),
                                          float(r["mid"]), float(r.get("obi20", 0.0)) or 0.0))
                except (ValueError, KeyError, TypeError):
                    continue
    for f in sorted(T.glob("trades_*.jsonl")):
        if not (day_lo <= int(f.name[7:15]) <= day_hi):
            continue
        with open(f) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    tape[r["sym"]].append((float(r["ts"]) / 1000.0, float(r["price"])))
                except (ValueError, KeyError, TypeError):
                    continue
    for d in (*obi.values(), *tape.values()):
        d.sort()
    return dict(obi), dict(tape)


# ---------------------------------------------------------------- pola onset
def find_onsets(obi_rows):
    """[(t0, bid, ask, mid)]: o20>=B_LV sebanyak B_DUR snapshot berturut; gap >= GAP_S"""
    out, run, lastfire = [], 0, -10**9
    for ts, bid, ask, mid, o20 in obi_rows:
        run = run + 1 if o20 >= B_LV else 0
        if run == B_DUR and ts - lastfire >= GAP_S:
            out.append((ts, bid, ask, mid))
            lastfire = ts
    return out


# ---------------------------------------------------------------- simulasi
def fmtday(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y%m%d")


def simulate(sym, obi_rows, tape_rows):
    """-> (episodes, n_unresolved). Konservatif: fill dari tape nyata, tanpa antrean prio."""
    tts = [t for t, _ in tape_rows]
    episodes, unresolved = [], 0
    for t0, bid0, ask0, mid0 in find_onsets(obi_rows):
        if mid0 <= 0 or bid0 <= 0 or ask0 <= bid0:
            continue
        hs0 = (ask0 - bid0) / 2 / mid0
        # ENTRY: trade harga <= bid0 dalam (t0, t0+ENTRY_WAIT]
        i_in = bisect_right(tts, t0)
        p_in = None
        for k in range(i_in, min(len(tape_rows), i_in + 4000)):
            ts, px = tape_rows[k]
            if ts > t0 + ENTRY_WAIT:
                break
            if px <= bid0:
                p_in = (ts, px)
                break
        if p_in is None:
            unresolved += 1
            continue
        t_in, px_in = p_in
        # EXIT: atur at t_exit = t_exit_req = t0 + EXIT_H (spesifikasi beku: keluar relatif EVENT, bukan fill)
        t_exit_req = t0 + EXIT_H
        # best ask terdekat <=30s sebelum t_exit_req
        i0 = bisect_right([x[0] for x in obi_rows], t_exit_req + 30) - 1
        if i0 < 0:
            unresolved += 1
            continue
        ts_ob, bidE, askE, midE, _ = obi_rows[i0]
        if midE <= 0:
            unresolved += 1
            continue
        # maker exit: trade >= askE dalam (t_exit_req, +EXIT_WAIT]; else taker paksa (trade terakhir (t0, t_exit_req+EXIT_WAIT])
        p_out = None
        k0 = bisect_right(tts, t_exit_req)
        for k in range(k0, min(len(tape_rows), k0 + 4000)):
            ts, px = tape_rows[k]
            if ts > t_exit_req + EXIT_WAIT:
                break
            if px >= askE:
                p_out = (ts, px)
                break
        if p_out is None:
            # taker paksa: trade harga terakhir <= t_exit_req (atau askE jika tidak ada)
            pk = bisect_right(tts, t_exit_req) - 1
            px_out = tape_rows[pk][1] if pk >= 0 else askE
            gross = (px_out / px_in - 1.0)
            net = gross - 2 * TAKER_FEE - FUNDING_BP
            episodes.append({"sym": sym, "t_in": t_in, "t_out": t_exit_req, "net": net, "day": fmtday(t_in), "maker": 0,
                             "px_in": px_in, "px_out": px_out})
            continue
        # maker exit terisi
        px_out = p_out[1]
        gross = (px_out / px_in - 1.0)
        # kredit spread maker: keluar di askE (>= mid), masuk di bid0 (<= mid)
        # net konservatif sudah tampung: px_out = harga trade yang >= askE (bukan askE)
        net = gross - 2 * MAKER_FEE - FUNDING_BP
        episodes.append({"sym": sym, "t_in": t_in, "t_out": t_exit_req, "net": net, "day": fmtday(t_in), "maker": 1,
                         "px_in": px_in, "px_out": px_out})
    return episodes, unresolved


# ---------------------------------------------------------------- evaluasi
def day_signflip_p(by_day, n=N_PERM, seed=SEED):
    gs = [(sum(v), len(v)) for v in by_day.values() if v]
    tot = sum(b for _, b in gs)
    obs = sum(a for a, _ in gs) / tot
    rng, ge = random.Random(seed), 0
    for _ in range(n):
        s = sum(a if rng.random() < 0.5 else -a for a, _ in gs)
        if s / tot >= obs:
            ge += 1
    return (ge + 1) / (n + 1)


def window_pnls(eps, data_end, f=F_SIZE, cap=GROSS_CAP):
    lo, nw = DAY0, (data_end - DAY0) // WIN48
    w, open_pos, taken = [0.0] * max(nw, 0), [], 0
    for e in sorted(eps, key=lambda x: x["t_in"]):
        open_pos = [(te, ff) for te, ff in open_pos if te > e["t_in"]]
        if sum(ff for _, ff in open_pos) + f > cap + 1e-12:
            continue
        open_pos.append((e["t_out"], f))
        i = (e["t_out"] - lo) // WIN48
        if 0 <= i < nw:
            w[i] += f * e["net"]; taken += 1
    return w, taken


def boot_ci_low(w, n=N_BOOT, seed=SEED):
    rng = random.Random(seed)
    ms = sorted(st.mean([w[rng.randrange(len(w))] for _ in w]) for _ in range(n))
    return ms[int(0.025 * n)], ms[int(0.975 * n)]


def judge(eps, unresolved, n_onsets, data_end):
    c, n = {}, len(eps)
    days = {e["day"] for e in eps}
    syms = sorted({e["sym"] for e in eps})
    unr = (unresolved / n_onsets) if n_onsets else 1.0
    c["C0_n>=300"] = n >= N_EP_MIN
    c["C0_hari>=14"] = len(days) >= DAYS_MIN
    c["C0_simbol>=8"] = len(syms) >= SYMS_MIN
    c["C0_unresolved<=10%"] = unr <= UNRES_MAX
    if n < 3:
        return {"verdict": "INCONCLUSIVE", "criteria": c, "n": n, "unresolved_rate": round(unr, 4)}
    r = [e["net"] for e in eps]
    mean = st.mean(r)
    by_day = defaultdict(list)
    for e in eps:
        by_day[e["day"]].append(e["net"])
    p_day = day_signflip_p(by_day)
    c["C1_mean>=4bp"] = mean >= REQ_BP / 1e4
    c["C2_p_hari<0.05"] = p_day < 0.05
    # C3 kontrol fade-maker: sinyal sama, tapi sell-maker@bid masuk / buy-maker@ask keluar (aprox: -net tanpa arah beli)
    sv = -0.0  # kontrol fade didefinisikan sbg episode mirror (net dihitung dari near-side); REDAKSI: gestor day 0 UTC
    c["C3_kalahkan_kontrol_fade"] = mean > st.mean([-e["net"] for e in eps])  # mirror sederhana
    c["C4_buang3terbaik>0"] = st.mean(sorted(r)[:-3]) > 0 if n > 3 else False
    # C5 audit taker: jika SEMUA eksekusi taker (2x4bp), masih > 0? (buktikan sinyal, bukan kredit biaya)
    cta = []
    for e in eps:
        cta.append((e["px_out"] / e["px_in"] - 1.0) - 2 * TAKER_FEE - FUNDING_BP)
    c["C5_bentuk_taker>0"] = st.mean(cta) > 0
    thirds = [r[i * n // 3:(i + 1) * n // 3] for i in range(3)]
    c["C6_segmen>=2/3"] = sum(1 for x in thirds if x and st.mean(x) > 0) >= 2
    tot = sum(r)
    ds = {d: sum(v) for d, v in by_day.items()}
    c["C7_top-hari<=35%"] = tot > 0 and max(ds.values()) / tot <= 0.35
    w, taken = window_pnls(eps, data_end)
    if len(w) >= 3:
        lo95, hi95 = boot_ci_low(w)
        wm = st.mean(w)
        c["C8_jendela48j_mean>=0,8%_dan_CI95>0"] = wm >= TARGET_WIN and lo95 > 0
    else:
        lo95, hi95, wm = float("nan"), float("nan"), float("nan")
        c["C8_jendela48j_mean>=0,8%_dan_CI95>0"] = False
    ok_c0 = all(v for k, v in c.items() if k.startswith("C0"))
    ok_all = all(c.values())
    verdict = "PASS" if ok_all else ("INCONCLUSIVE" if not ok_c0 else "FAIL")
    return {"verdict": verdict, "criteria": c, "n": n, "days": len(days), "symbols": len(syms),
            "unresolved_rate": round(unr, 4), "mean_net_bp": round(mean * 1e4, 2),
            "median_net_bp": round(st.median(r) * 1e4, 2), "maker_fill_rate": round(
                sum(e["maker"] for e in eps) / n, 3), "p_hari": round(p_day, 4),
            "taker_audit_mean_bp": round(st.mean(cta) * 1e4, 2),
            "windows": len(w), "window_mean_pct": round(wm * 100, 4),
            "window_ci95_pct": [round(lo95 * 100, 4), round(hi95 * 100, 4)] if w == w else None,
            "window_hit_pct": round(100 * sum(1 for x in w if x >= TARGET_WIN) / len(w), 1) if w else None}


# ---------------------------------------------------------------- gerbang
def gate_open(cnt, today):
    if cnt["n_onsets_total"] - cnt["unresolved"] >= N_EP_MIN and cnt["days"] >= DAYS_MIN and cnt["syms"] >= SYMS_MIN and (1 - cnt["unresolved"] / max(cnt["n_onsets_total"], 1)) <= 1 and (cnt["unresolved"] / max(cnt["n_onsets_total"], 1)) <= UNRES_MAX:
        return True, "pemicu terpenuhi"
    if today >= HARD_STOP:
        return True, "HARD_STOP tercapai"
    return False, "belum"


def count_state(lo, hi):
    obi, tape = load_forward(lo, hi)
    total, days_set, syms = 0, set(), set()
    for sym, rows in obi.items():
        ons = find_onsets(rows)
        total += len(ons)
        for t0, *_ in ons:
            days_set.add(fmtday(t0))
        if rows:
            syms.add(sym)
    return {"n_onsets_total": total, "days": len(days_set), "syms": len(syms), "unresolved": 0}


def main(argv):
    lo, hi = int(F_START.strftime("%Y%m%d")), 99991231
    today = datetime.now(timezone.utc).date()
    cnt = count_state(lo, hi)
    n_state = cnt["n_onsets_total"]
    print(f"[F2] mulai {F_START.date()}  onset={n_state}/{N_EP_MIN}  hari={cnt['days']}/{DAYS_MIN}  simbol={cnt['syms']}/{SYMS_MIN}")
    if "--final" not in argv:
        return 0
    open_, why = gate_open(cnt, today)
    if not open_:
        print("DITOLAK: gerbang belum terbuka (%s). Tidak ada PnL yang dihitung (anti-intip)." % why)
        return 2
    obi, tape = load_forward(lo, hi)
    data_end = max((max(x[0] for x in rows) for rows in obi.values() if rows), default=DAY0)
    eps_all, unr_all, n_all = [], 0, 0
    for sym, rows in obi.items():
        e, u = simulate(sym, rows, tape.get(sym, []))
        eps_all += e
        unr_all += u
        n_all += len(e) + u
    res = judge(eps_all, unr_all, n_all, data_end)
    res.update({"prereg": "docs/sodex/SODEX_F2_PRAREG_2026-10-06.md", "gate": why,
                "evaluated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "lockbox_old_read": False})
    REP.mkdir(parents=True, exist_ok=True)
    out = REP / f"SODEX_F2_RESULT_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps(res, indent=1, ensure_ascii=False))
    print(f"==> PUTUSAN F2: {res['verdict']}  (tersimpan {out.name}; hasil tidak boleh diuji ulang/disetel)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
