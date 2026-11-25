#!/usr/bin/env python3
"""
SODEX F1 -- evaluator PRA-REGISTRASI forward momentum, 20 simbol (READ-ONLY).
Spesifikasi beku: docs/sodex/SODEX_F1_PRAREG_2026-10-06.md. Kriteria TIDAK boleh diubah setelah hasil keluar.

Mode:
  --count-only : hanya menghitung episode LENGKAP (tidak membaca harga keluar -> tidak ada intip PnL)
  --final      : hitung PnL + putusan. Ditolak bila gerbang pemicu belum terpenuhi dan belum HARD_STOP.
Tidak ada jalur order/sign/withdraw. LOCKBOX lama (<=2026-10-05) tidak dibaca.
"""
from __future__ import annotations
import json, random, sys, statistics as st
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sodex_forward_momentum as fm  # noqa: E402  (hanya half_spread_bp)

ROOT = Path(__file__).resolve().parents[1]
T = ROOT / "freqtrade_user_data/data/sodex/trades"
REP = ROOT / "reports/sodex"

# ---- PARAMETER BEKU (lihat dokumen pra-registrasi) ----
F_START = datetime(2026, 10, 7, tzinfo=timezone.utc)
F_START_MIN = int(F_START.timestamp() // 60)
THETA, WIN_MIN, CLUSTER_MIN, HOLD_MIN = 0.020, 15, 60, 24 * 60
# AMENDEMEN 07-Okt-2026 (sebelum PnL apa pun dihitung): FEE_TAKER 0,0002 -> 0,0004.
# Taker resmi SoDEX 0,040%/leg = 4 bp (FACT_SHEET_EKONOMI_VENUE, F2_CLOSED, whitepaper);
# nilai lama 2 bp = setengah biaya nyata (fatal: membalik C1 pada edge bruto 0,50%/episode).
FEE_TAKER, EXTRA_SLIP_BP = 0.0004, 10.0
# AMENDEMEN 07-Okt-2026: biaya funding 24 jam sebelumnya NOL. Konservatif & simetris:
# funding nyata ~0,024%/24 jam (AUDIT_BIAYA_AKUN_2026-10-05, 24.123 titik, 11 simbol).
FUNDING_BP_24H = 2.4
LOOK_P0, LOOK_EXIT, DELAY_MIN = 5, 10, 2
F_SIZE, GROSS_CAP, WIN48 = 0.15, 1.0, 48 * 60
TARGET_WIN = 0.008
N_MIN, DAYS_MIN, SYMS_MIN, UNRESOLVED_MAX = 150, 14, 10, 0.05
MEAN_MIN, P_MAX, TOP_DAY_MAX = 0.0040, 0.05, 0.35
# PERPANJANGAN 07-Okt-2026 (approval user, opsi A): 7-Nov -> 20-Nov (+13 hari, MAKSIMAL).
# Tidak ada perpanjangan lagi setelah ini; sesudahnya wajib full live real trading.
HARD_STOP = datetime(2026, 11, 20, tzinfo=timezone.utc).date()
N_PERM, N_BOOT, SEED = 20000, 20000, 42


def load_minutes(path_dir: Path = T, start_min: int = F_START_MIN) -> dict[str, dict[int, tuple[float, float]]]:
    """sym -> {menit: (ts_detik, harga)}; harga = trade dengan ts TERBESAR di menit itu (tahan duplikat & disorder)."""
    out: dict[str, dict[int, tuple[float, float]]] = {}
    for f in sorted(path_dir.glob("trades_*.jsonl")):
        if f.name[7:15] < F_START.strftime("%Y%m%d"):
            continue
        with open(f) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    ts, px, s = float(r["ts"]) / 1000.0, float(r["price"]), r["sym"]
                except (ValueError, KeyError, TypeError):
                    continue
                m = int(ts // 60)
                if px <= 0 or m < start_min:
                    continue
                d = out.setdefault(s, {})
                if m not in d or ts >= d[m][0]:
                    d[m] = (ts, px)
    return out


def px_back(d, m, look):
    for k in range(look + 1):
        if m - k in d:
            return d[m - k][1]
    return None


def px_fwd(d, m, look):
    for k in range(look + 1):
        if m + k in d:
            return d[m + k][1], m + k
    return None, None


def find_events(d, theta=THETA):
    """-> [(menit, arah)] ; event = |r_15m|>=theta (p0 = harga terakhir <=5 mnt sebelum t-15) ; klaster 60 mnt, ambil pertama."""
    ev, last = [], None
    for t in sorted(d):
        p0 = px_back(d, t - WIN_MIN, LOOK_P0)
        if p0 is None:
            continue
        r = d[t][1] / p0 - 1.0
        if abs(r) >= theta:
            if last is None or t - last >= CLUSTER_MIN:
                ev.append((t, 1 if r > 0 else -1))
            last = t
    return ev


def count_complete(minutes) -> dict:
    """hitung episode lengkap TANPA membaca harga keluar."""
    n, days, syms = 0, set(), set()
    for s, d in minutes.items():
        end = max(d) if d else 0
        for t, _ in find_events(d):
            if t + HOLD_MIN <= end:
                n += 1
                days.add(datetime.fromtimestamp(t * 60, timezone.utc).strftime("%Y%m%d"))
                syms.add(s)
    return {"n": n, "days": len(days), "symbols": len(syms)}


def build_episodes(minutes, hs, fallback_hs):
    """-> (episode_list, jumlah_event_lengkap). item: dict(sym,t_in,t_out,day,net,fade,net_d2)"""
    eps, n_complete = [], 0
    for s, d in minutes.items():
        if not d:
            continue
        end = max(d)
        cost = 2 * (hs.get(s, fallback_hs) / 1e4 + FEE_TAKER) + EXTRA_SLIP_BP / 1e4 + FUNDING_BP_24H / 1e4
        for t, dr in find_events(d):
            if t + HOLD_MIN > end:
                continue
            n_complete += 1
            p_out = px_back(d, t + HOLD_MIN, LOOK_EXIT)
            if p_out is None:
                continue
            p_in = d[t][1]
            g = dr * (p_out / p_in - 1.0)
            p_in2, t_in2 = px_fwd(d, t + DELAY_MIN, 3)
            net_d2 = None
            if p_in2 is not None:
                p_out2 = px_back(d, t_in2 + HOLD_MIN, LOOK_EXIT)
                if p_out2 is not None:
                    net_d2 = dr * (p_out2 / p_in2 - 1.0) - cost
            eps.append({"sym": s, "t_in": t, "t_out": t + HOLD_MIN, "net": g - cost, "fade": -g - cost, "net_d2": net_d2,
                        "day": datetime.fromtimestamp(t * 60, timezone.utc).strftime("%Y%m%d")})
    eps.sort(key=lambda e: e["t_in"])
    return eps, n_complete


def day_signflip_p(by_day: dict[str, list[float]], n=N_PERM, seed=SEED) -> float:
    """sign-flip level HARI (kluster), satu sisi: p = P(rata-rata acak >= teramati). BENAR (nol-terpusat)."""
    gs = [(sum(v), len(v)) for v in by_day.values() if v]
    tot = sum(b for _, b in gs)
    obs = sum(a for a, _ in gs) / tot
    rng, ge = random.Random(seed), 0
    for _ in range(n):
        s = sum(a if rng.random() < 0.5 else -a for a, _ in gs)
        if s / tot >= obs:
            ge += 1
    return (ge + 1) / (n + 1)


def window_pnls(eps, data_end_min, f=F_SIZE, cap=GROSS_CAP):
    nw = (data_end_min - F_START_MIN) // WIN48
    w, open_pos, taken = [0.0] * max(nw, 0), [], 0
    for e in sorted(eps, key=lambda x: x["t_in"]):
        open_pos = [(te, ff) for te, ff in open_pos if te > e["t_in"]]
        if sum(ff for _, ff in open_pos) + f > cap + 1e-12:
            continue
        open_pos.append((e["t_out"], f))
        i = (e["t_out"] - F_START_MIN) // WIN48
        if 0 <= i < nw:
            w[i] += f * e["net"]
            taken += 1
    return w, taken


def boot_ci_low(w, n=N_BOOT, seed=SEED):
    rng = random.Random(seed)
    ms = sorted(st.mean([w[rng.randrange(len(w))] for _ in w]) for _ in range(n))
    return ms[int(0.025 * n)], ms[int(0.975 * n)]


def judge(eps, n_complete, data_end_min) -> dict:
    """kriteria beku C0..C8 -> dict; verdict PASS / FAIL / INCONCLUSIVE"""
    n = len(eps)
    c = {}
    days = {e["day"] for e in eps}
    syms = {e["sym"] for e in eps}
    unresolved = 1 - n / n_complete if n_complete else 1.0
    c["C0_n>=150"] = n >= N_MIN
    c["C0_hari>=14"] = len(days) >= DAYS_MIN
    c["C0_simbol>=10"] = len(syms) >= SYMS_MIN
    c["C0_tak-terselesaikan<=5%"] = unresolved <= UNRESOLVED_MAX
    if n < 3:
        return {"verdict": "INCONCLUSIVE", "criteria": c, "n": n, "unresolved": unresolved}
    r = [e["net"] for e in eps]
    mean = st.mean(r)
    by_day: dict[str, list[float]] = {}
    for e in eps:
        by_day.setdefault(e["day"], []).append(e["net"])
    p_day = day_signflip_p(by_day)
    c["C1_mean>=0,40%"] = mean >= MEAN_MIN
    c["C2_p_hari<0,05"] = p_day < P_MAX
    c["C3_kalahkan_kontrol_fade"] = mean > st.mean(e["fade"] for e in eps)
    c["C4_buang3terbaik>0"] = st.mean(sorted(r)[:-3]) > 0 if n > 3 else False
    d2 = [e["net_d2"] for e in eps if e["net_d2"] is not None]
    c["C5_delay2m>0"] = bool(d2) and st.mean(d2) > 0
    thirds = [r[i * n // 3:(i + 1) * n // 3] for i in range(3)]
    c["C6_segmen>=2/3"] = sum(1 for x in thirds if x and st.mean(x) > 0) >= 2
    tot = sum(r)
    day_sum = {d: sum(v) for d, v in by_day.items()}
    c["C7_hari-teratas<=35%"] = tot > 0 and max(day_sum.values()) / tot <= TOP_DAY_MAX
    w, taken = window_pnls(eps, data_end_min)
    if len(w) >= 3:
        lo, hi = boot_ci_low(w)
        wm = st.mean(w)
        c["C8_jendela48j_mean>=0,8%_dan_CI95_bawah>0"] = wm >= TARGET_WIN and lo > 0
    else:
        lo = hi = wm = float("nan")
        c["C8_jendela48j_mean>=0,8%_dan_CI95_bawah>0"] = False
    ok_c0 = all(v for k, v in c.items() if k.startswith("C0"))
    ok_all = all(c.values())
    verdict = "PASS" if ok_all else ("INCONCLUSIVE" if not ok_c0 else "FAIL")
    return {"verdict": verdict, "criteria": c, "n": n, "days": len(days), "symbols": len(syms),
            "unresolved": round(unresolved, 4), "mean_net_pct": round(mean * 100, 4),
            "median_net_pct": round(st.median(r) * 100, 4), "p_hari": round(p_day, 4),
            "fade_mean_pct": round(st.mean(e["fade"] for e in eps) * 100, 4),
            "delay2m_mean_pct": round(st.mean(d2) * 100, 4) if d2 else None,
            "top_day_share": round(max(day_sum.values()) / tot, 3) if tot > 0 else None,
            "windows": len(w), "windows_taken_positions": taken,
            "window_mean_pct": round(wm * 100, 4), "window_ci95_pct": [round(lo * 100, 4), round(hi * 100, 4)],
            "window_hit_pct": round(100 * sum(1 for x in w if x >= TARGET_WIN) / len(w), 1) if w else None}


def gate_open(cnt: dict, today) -> tuple[bool, str]:
    if cnt["n"] >= N_MIN and cnt["days"] >= DAYS_MIN and cnt["symbols"] >= SYMS_MIN:
        return True, "pemicu terpenuhi"
    if today >= HARD_STOP:
        return True, "HARD_STOP tercapai"
    return False, "belum"


def main(argv) -> int:
    minutes = load_minutes()
    cnt = count_complete(minutes)
    open_, why = gate_open(cnt, datetime.now(timezone.utc).date())
    print(f"[F1] mulai {F_START.date()}  episode lengkap={cnt['n']}/{N_MIN}  hari={cnt['days']}/{DAYS_MIN}  simbol={cnt['symbols']}/{SYMS_MIN}  gerbang={why}")
    if "--final" not in argv:
        return 0
    if not open_:
        print("DITOLAK: gerbang belum terbuka. Tidak ada PnL yang dihitung (anti-intip).")
        return 2
    days = sorted({f.name[7:15] for f in T.glob("trades_*.jsonl") if f.name[7:15] >= F_START.strftime("%Y%m%d")})
    hs = fm.half_spread_bp(days)
    fb = sorted(hs.values())[int(0.95 * (len(hs) - 1))] if hs else 5.0
    end = max((max(d) for d in minutes.values() if d), default=F_START_MIN)
    eps, n_complete = build_episodes(minutes, hs, fb)
    res = judge(eps, n_complete, end)
    res.update({"prereg": "docs/sodex/SODEX_F1_PRAREG_2026-10-06.md", "gate": why, "lockbox_old_read": False,
                "evaluated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    REP.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    # AMENDEMEN 07-Okt-2026 (anti-optional-stopping): nama ber-timestamp (tak menimpa) +
    # log append-only semua 'look' + kunci FIRST-LOOK. Keputusan pra-reg = look PERTAMA.
    out = REP / f"SODEX_F1_RESULT_{now.strftime('%Y%m%dT%H%M%S')}.json"
    out.write_text(json.dumps(res, indent=1))
    with open(REP / "SODEX_F1_LOOKS.jsonl", "a") as fh:
        fh.write(json.dumps({"evaluated_utc": res["evaluated_utc"], "verdict": res["verdict"],
                             "n": res.get("n"), "gate": why}) + "\n")
    first = REP / "SODEX_F1_FIRSTLOOK.json"
    if not first.exists():
        first.write_text(json.dumps(res, indent=1))
        print("FIRST-LOOK terkunci -> keputusan pra-registrasi = look ini.")
    else:
        print("PERINGATAN: FIRST-LOOK sudah ada; ini look TAMBAHAN. Keputusan pra-reg = FIRSTLOOK.")
    print(json.dumps(res, indent=1, ensure_ascii=False))
    print(f"==> PUTUSAN F1: {res['verdict']}  (tersimpan {out.name}; TIDAK boleh diubah/disetel)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
