#!/usr/bin/env python3
"""SODEX F3 -- evaluator pra-registrasi funding-squeeze + OBI nyata (READ-ONLY, anti-intip).

Spesifikasi beku: docs/sodex/SODEX_F3_PRAREG_2026-10-06.md (evaluasi #44). Kriteria TIDAK
boleh diubah setelah hasil keluar. Konstanta = produksi verbatim (twin_engine E2Dir), TIDAK
direkalibrasi (menghindari p-hacking yang mencemari riset Juni 2026, lihat §0 dokumen).

Data: funding_rates_history.jsonl (mark/predicted funding per simbol, collector aktif sejak
2026-10-02) x OBI20 nyata (freqtrade_user_data/data/sodex/obi, collector aktif) x tape (harga).
Onset funding+OBI selaras -> taker entry -> hold 1800s -> taker exit. Gap independensi 1 jam/simbol.
Gerbang: >=100 episode, >=10 hari, >=5 simbol; atau HARD_STOP 2026-11-20 (diperpanjang dari
2026-11-07, approval user 07-Okt-2026, +13 hari maksimal). --final menolak
sebelum gerbang (anti-intip).
"""
from __future__ import annotations
import json, random, statistics as st, sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUND = ROOT / "data/sodex_funding/funding_rates_history.jsonl"
OBI = ROOT / "freqtrade_user_data/data/sodex/obi"
T = ROOT / "freqtrade_user_data/data/sodex/trades"
REP = ROOT / "reports/sodex"

FUNDING_THR = 0.00003      # TE_E2_DIR_FUNDING_THR produksi, verbatim
OBI_THR = 0.15             # TE_E2_DIR_OBI_THR produksi, verbatim
HOLD_S = 1800              # TE_E2_DIR_HOLD_S produksi, verbatim
TAKER_FEE = 0.04 / 100     # whitepaper SoDEX, per leg
GAP_S = 3600               # independensi: funding settle per jam
N_EP_MIN, DAYS_MIN, SYMS_MIN = 100, 10, 5
# PERPANJANGAN 07-Okt-2026 (approval user, opsi A): 7-Nov -> 20-Nov (+13 hari, MAKSIMAL).
# Tidak ada perpanjangan lagi setelah ini; sesudahnya wajib full live real trading.
HARD_STOP = datetime(2026, 11, 20, tzinfo=timezone.utc).date()
WIN48, TARGET_WIN, F_SIZE, GROSS_CAP = 48 * 60, 0.008, 0.15, 1.0
N_PERM, N_BOOT, SEED = 20000, 20000, 42

# --- Likuiditas (NON-GATING): stratifikasi verdict menurut volume 24 jam pasar -----
# Ambang objektif; lihat docs/sodex/SODEX_F3_PRAREG_2026-10-06.md §9 (perluasan 20->92).
# TIDAK masuk `criteria` C0-C8 dan TIDAK mengubah verdict apa pun.
LIQ_SNAP = ROOT / "data/sodex_market_tickers.json"
LIQ_THIN, LIQ_MID, LIQ_DEEP = 10_000.0, 50_000.0, 1_000_000.0
LIQ_BUCKETS = ("thin_<10k", "mid_10k-50k", "deep_50k-1M", "verydeep_>=1M", "unknown")


def fmtday(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y%m%d")


def load_funding():
    """sym -> sorted[(collected_ts_s, funding_rate_frac, funding_time_ts_s)]"""
    out = defaultdict(list)
    if not FUND.exists():
        return out
    with open(FUND) as f:
        for line in f:
            try:
                r = json.loads(line)
                ts = datetime.fromisoformat(r["collected_utc"]).timestamp()
                fts = datetime.fromisoformat(r["funding_time_utc"]).timestamp()
                sym = r["symbol"] if r["symbol"].endswith("-USD") else r["symbol"] + "-USD"
                out[sym].append((ts, float(r["funding_rate"]), fts))
            except (ValueError, KeyError, TypeError):
                continue
    for v in out.values():
        v.sort()
    return out


def load_obi_tape(day_lo):
    obi, tape = defaultdict(list), defaultdict(list)
    for f in sorted(OBI.glob("obi_*.jsonl")):
        if int(f.name[4:12]) < day_lo:
            continue
        with open(f) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    obi[r["sym"]].append((float(r["ts"]) / 1000.0, float(r.get("obi20", 0.0)) or 0.0, float(r["mid"])))
                except (ValueError, KeyError, TypeError):
                    continue
    for f in sorted(T.glob("trades_*.jsonl")):
        if int(f.name[7:15]) < day_lo:
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


def mid_at(obi_rows, ts):
    i = bisect_right([x[0] for x in obi_rows], ts) - 1
    return obi_rows[i][2] if 0 <= i < len(obi_rows) else None


def find_onsets(sym, fund_rows, obi_rows):
    out, lastfire = [], -10**9
    oti = [x[0] for x in obi_rows]
    for ts, fr, _ft in fund_rows:
        if abs(fr) < FUNDING_THR or ts - lastfire < GAP_S:
            continue
        i = bisect_right(oti, ts) - 1
        if i < 0:
            continue
        _, o20, mid0 = obi_rows[i]
        side = "sell" if fr > 0 else "buy"
        aligned = (side == "sell" and o20 < -OBI_THR) or (side == "buy" and o20 > OBI_THR)
        if not aligned or mid0 <= 0:
            continue
        out.append((ts, side, fr, o20, mid0))
        lastfire = ts
    return out


def settlements_in_window(fund_rows, t0, t1):
    """Jumlah rate settlement yang BENAR-BENAR terlewati dalam (t0, t1] -- dedup per funding_time."""
    seen, tot = set(), 0.0
    for _ts, rate, fts in fund_rows:
        if t0 < fts <= t1 and fts not in seen:
            seen.add(fts)
            tot += rate
    return tot


def simulate(sym, onsets, obi_rows, fund_rows):
    eps = []
    for t0, side, fr, o20, mid0 in onsets:
        mid1 = mid_at(obi_rows, t0 + HOLD_S)
        if mid1 is None or mid1 <= 0:
            continue
        move = (mid1 / mid0 - 1.0) * (1 if side == "buy" else -1)
        # fix 07-Okt-2026: funding HANYA untuk settlement yang benar-benar terlewati dalam
        # (t0, t0+HOLD_S], pakai rate settlement ITU (bukan baris berikutnya). Kode lama memakai
        # baris berikutnya x 0,5 -> KREDIT tak layak pada ~94% onset (bias net positif).
        rate_sum = settlements_in_window(fund_rows, t0, t0 + HOLD_S)
        funding_cost = rate_sum * (1 if side == "buy" else -1)  # long bayar bila rate>0
        net = move - 2 * TAKER_FEE - funding_cost
        eps.append({"sym": sym, "t_in": t0, "net": net, "day": fmtday(t0), "side": side})
    return eps


def day_signflip_p(by_day, n=N_PERM, seed=SEED):
    gs = [(sum(v), len(v)) for v in by_day.values() if v]
    tot = sum(b for _, b in gs)
    if tot == 0:
        return 1.0
    obs = sum(a for a, _ in gs) / tot
    rng, ge = random.Random(seed), 0
    for _ in range(n):
        s = sum(a if rng.random() < 0.5 else -a for a, _ in gs)
        if s / tot >= obs:
            ge += 1
    return (ge + 1) / (n + 1)


def window_pnls(eps, data_start, data_end, f=F_SIZE, cap=GROSS_CAP):
    nw = max((data_end - data_start) // WIN48, 0)
    w, open_pos = [0.0] * nw, []
    for e in sorted(eps, key=lambda x: x["t_in"]):
        t_out = e["t_in"] + HOLD_S
        open_pos = [(te, ff) for te, ff in open_pos if te > e["t_in"]]
        if sum(ff for _, ff in open_pos) + f > cap + 1e-12:
            continue
        open_pos.append((t_out, f))
        i = (t_out - data_start) // WIN48
        if 0 <= i < nw:
            w[int(i)] += f * e["net"]
    return w


def boot_ci_low(w, n=N_BOOT, seed=SEED):
    if not w:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    ms = sorted(st.mean([w[rng.randrange(len(w))] for _ in w]) for _ in range(n))
    return ms[int(0.025 * n)], ms[int(0.975 * n)]


def load_liquidity(path=LIQ_SNAP):
    """sym -> quoteVolume 24 jam (USD) dari snapshot cache.

    FAIL-CLOSED: bila snapshot tidak ada / rusak -> {} (bukan default optimistis).
    """
    try:
        d = json.loads(Path(path).read_text())
    except (FileNotFoundError, ValueError, OSError):
        return {}
    out = {}
    for sym, v in (d.get("volumes") or {}).items():
        try:
            out[sym] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def bucket_of(v):
    if v is None:
        return "unknown"
    if v < LIQ_THIN:
        return "thin_<10k"
    if v < LIQ_MID:
        return "mid_10k-50k"
    if v < LIQ_DEEP:
        return "deep_50k-1M"
    return "verydeep_>=1M"


def liquidity_view(eps, liq):
    """NON-GATING. Stratifikasi episode menurut likuiditas pasar.

    Sengaja TIDAK menyentuh `criteria`: verdict C0-C8 harus tetap dapat direproduksi
    tanpa data likuiditas. Bila snapshot tidak ada -> status UNKNOWN + peringatan
    (fail-closed), bukan diam-diam dianggap likuid.
    """
    if not liq:
        return {"status": "UNKNOWN",
                "warning": "snapshot likuiditas tidak ada -> verdict F3 TIDAK boleh dibaca "
                           "tanpa konteks likuiditas. Jalankan scripts/sodex_tickers_snapshot.py."}
    b = defaultdict(list)
    for e in eps:
        b[bucket_of(liq.get(e["sym"]))].append(e["net"])
    rows = {}
    for k in LIQ_BUCKETS:
        v = b.get(k) or []
        if not v:
            continue
        rows[k] = {"n": len(v), "wr": round(sum(1 for x in v if x > 0) / len(v), 4),
                   "mean_net_bp": round(st.mean(v) * 1e4, 2), "sum_bp": round(sum(v) * 1e4, 2)}
    trad = [e["net"] for e in eps if (liq.get(e["sym"]) or 0) >= LIQ_THIN]
    n_thin = sum(1 for e in eps if (liq.get(e["sym"]) or 0) < LIQ_THIN)
    return {"status": "OK",
            "thresholds": {"thin": LIQ_THIN, "mid": LIQ_MID, "deep": LIQ_DEEP},
            "by_bucket": rows,
            "n_thin_episodes": n_thin,
            "thin_share": round(n_thin / len(eps), 4) if eps else None,
            "tradable_only_secondary": {
                "n": len(trad),
                "wr": round(sum(1 for x in trad if x > 0) / len(trad), 4) if trad else None,
                "mean_net_bp": round(st.mean(trad) * 1e4, 2) if trad else None},
            "note": "NON-GATING (criteria C0-C8 tidak dipengaruhi). Pasar tipis (<$10k) TIDAK "
                    "boleh dianggap tradeable: bila PASS bergantung padanya, verdict harus DITOLAK."}


def judge(eps, data_start, data_end):
    n = len(eps)
    days = {e["day"] for e in eps}
    syms = {e["sym"] for e in eps}
    c = {"C0_n>=100": n >= N_EP_MIN, "C0_hari>=10": len(days) >= DAYS_MIN, "C0_simbol>=5": len(syms) >= SYMS_MIN}
    if n < 3:
        return {"verdict": "INCONCLUSIVE", "criteria": c, "n": n}
    r = [e["net"] for e in eps]
    wr = sum(1 for x in r if x > 0) / n
    # binomial one-sided p (WR>50%), tanpa koreksi
    import math
    def binom_p(k, n_, p0=0.5):
        return sum(math.comb(n_, i) * p0**i * (1 - p0)**(n_ - i) for i in range(k, n_ + 1))
    p_raw = binom_p(sum(1 for x in r if x > 0), n)
    by_day = defaultdict(list)
    for e in eps:
        by_day[e["day"]].append(e["net"])
    # AMENDEMEN 07-Okt-2026: C2 = uji sign-flip level HARI (kluster), persis seperti F1.
    # C2 lama "Bonferroni m=1" = identitas (p*1) -> NOL perlindungan terhadap klasterisasi
    # harian; laju false-pass terukur 20-38% pada data nol terklaster (nominal 5%).
    p_day = day_signflip_p(by_day)
    c["C1_WR>50%_p<0.05"] = (wr > 0.5) and (p_raw < 0.05)
    c["C2_p_hari_klaster<0,05"] = p_day < 0.05
    c["C3_mean_net>0"] = st.mean(r) > 0
    c["C4_buang3terbaik_WR>50%"] = (sum(1 for x in sorted(r)[:-3] if x > 0) / max(n - 3, 1) > 0.5) if n > 3 else False
    r_time = [e["net"] for e in sorted(eps, key=lambda x: x["t_in"])]  # fix: segmen WAKTU, bukan symbol-major
    thirds = [r_time[i * n // 3:(i + 1) * n // 3] for i in range(3)]
    c["C5_segmen>=2/3_konsisten"] = sum(1 for x in thirds if x and sum(1 for y in x if y > 0) / len(x) > 0.5) >= 2
    w = window_pnls(eps, data_start, data_end)
    if len(w) >= 3:
        lo95, hi95 = boot_ci_low(w)
        wm = st.mean(w)
        c["C8_jendela48j_mean>=0,8%_dan_CI95>0"] = wm >= TARGET_WIN and lo95 > 0
    else:
        lo95, hi95, wm = float("nan"), float("nan"), float("nan")
        c["C8_jendela48j_mean>=0,8%_dan_CI95>0"] = False
    ok_c0 = all(v for k, v in c.items() if k.startswith("C0"))
    verdict = "PASS" if all(c.values()) else ("INCONCLUSIVE" if not ok_c0 else "FAIL")
    return {"verdict": verdict, "criteria": c, "n": n, "days": len(days), "symbols": len(syms),
            "wr": round(wr, 4), "mean_net_bp": round(st.mean(r) * 1e4, 2), "p_raw": round(p_raw, 4),
            "p_day": round(p_day, 4),
            "windows": len(w), "window_mean_pct": round(wm * 100, 4),
            "window_ci95_pct": [round(lo95 * 100, 4), round(hi95 * 100, 4)] if w else None}


def state(day_lo):
    """Gerbang: hitung episode yang keluar-nya SUDAH teramati (t0+HOLD_S <= ts OBI terakhir),
    TANPA membaca harga keluar (anti-intip). Dulu memakai n_onsets -> gerbang bisa terbuka
    lebih awal dari yang bisa disimulasikan (fix 07-Okt-2026)."""
    fund = load_funding()
    obi, tape = load_obi_tape(day_lo)
    total, days_set, syms = 0, set(), set()
    for sym, frows in fund.items():
        if sym not in obi:
            continue
        sym_max = obi[sym][-1][0] if obi[sym] else 0
        ready = [t0 for t0, *_ in find_onsets(sym, frows, obi[sym]) if t0 + HOLD_S <= sym_max]
        total += len(ready)
        syms.update([sym] if ready else [])
        for t0 in ready:
            days_set.add(fmtday(t0))
    return {"n_ready": total, "days": len(days_set), "syms": len(syms)}


def main(argv):
    day_lo = 20261002  # mulai data funding collector; OBI riil 20-simbol baru stabil ~5 Okt
    today = datetime.now(timezone.utc).date()
    cnt = state(day_lo)
    print(f"[F3] siap={cnt['n_ready']}/{N_EP_MIN}  hari={cnt['days']}/{DAYS_MIN}  simbol={cnt['syms']}/{SYMS_MIN}")
    if "--final" not in argv:
        return 0
    gate = (cnt["n_ready"] >= N_EP_MIN and cnt["days"] >= DAYS_MIN and cnt["syms"] >= SYMS_MIN)
    why = "pemicu terpenuhi" if gate else "belum"
    if not gate and today < HARD_STOP:
        print(f"DITOLAK: gerbang belum terbuka ({why}). Tidak ada PnL dihitung (anti-intip).")
        return 2
    fund = load_funding()
    obi, tape = load_obi_tape(day_lo)
    eps_all = []
    for sym, frows in fund.items():
        if sym not in obi:
            continue
        ons = find_onsets(sym, frows, obi[sym])
        eps_all += simulate(sym, ons, obi[sym], frows)
    all_ts = [t for rows in obi.values() for t, *_ in rows]
    data_start = min(all_ts) if all_ts else 0
    data_end = max(all_ts) if all_ts else 0
    res = judge(eps_all, data_start, data_end)
    # NON-GATING: konteks likuiditas untuk membaca verdict (lihat §9 pra-reg).
    # Tidak menyentuh `criteria` -> verdict C0-C8 tetap dapat direproduksi tanpanya.
    res["liquidity"] = liquidity_view(eps_all, load_liquidity())
    res.update({"prereg": "docs/sodex/SODEX_F3_PRAREG_2026-10-06.md", "gate": why,
                "evaluated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    REP.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    # fix 07-Okt-2026 (anti-optional-stopping): nama ber-timestamp + log append-only + FIRST-LOOK.
    out = REP / f"SODEX_F3_RESULT_{now.strftime('%Y%m%dT%H%M%S')}.json"
    out.write_text(json.dumps(res, indent=1))
    with open(REP / "SODEX_F3_LOOKS.jsonl", "a") as fh:
        fh.write(json.dumps({"evaluated_utc": res["evaluated_utc"], "verdict": res["verdict"],
                             "n": res.get("n"), "gate": why}) + "\n")
    first = REP / "SODEX_F3_FIRSTLOOK.json"
    if not first.exists():
        first.write_text(json.dumps(res, indent=1))
        print("FIRST-LOOK terkunci -> keputusan pra-registrasi = look ini.")
    else:
        print("PERINGATAN: FIRST-LOOK sudah ada; ini look TAMBAHAN. Keputusan pra-reg = FIRSTLOOK.")
    print(json.dumps(res, indent=1, ensure_ascii=False))
    print(f"==> PUTUSAN F3: {res['verdict']} (tersimpan {out.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
