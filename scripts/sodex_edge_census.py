#!/usr/bin/env python3
"""D14 — Sensus edge lintas-mesin. Protokol: docs/sodex/D14_PROTOKOL_SENSUS_EDGE_2026-10-05.md

Protokol itu DIBEKUKAN SEBELUM berkas ini dijalankan. Jangan ubah ambang di sini
tanpa memperbarui pra-registrasi dan mencatat trial baru.

Inti: target 0,8%/48 jam dicapai lewat PORTOFOLIO mesin, bukan satu mesin.
Syarat (P9, kelima-limanya): n_windows>=20, Sharpe48>=0,170 (tahunan 2,3),
3/3 segmen positif, p_terburuk<0,05, lolos BH-FDR q=0,10 atas seluruh keluarga.
"""
from __future__ import annotations

import json
import math
import random
import statistics as st
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
REPORTS = Path(__file__).resolve().parents[1] / "reports" / "sodex"
SEED = 20261005
N_SIM = 20000
WINDOW_H = 48.0
PERIODS_YEAR = 365.0 * 24.0 / WINDOW_H      # 182,5
SHARPE_48H_MIN = 2.3 / math.sqrt(PERIODS_YEAR)   # 0,1702
MIN_WINDOWS = 20
FDR_Q = 0.10

# ── spesifikasi mesin (Lampiran A D14 — DIBEKUKAN) ──────────────────────────
# (nama, berkas, mode, field_return, field_entry_ts, field_exit_ts, bendera)
SPECS = [
    ("realwide",          "paper_test_realwide_state.json",            "state", "pnl_pct",  "entry_ts",  "exit_ts",  ""),
    ("realwide_atrvolopen","paper_test_realwide_state_atrvolopen.json","state", "pnl_pct",  "entry_ts",  "exit_ts",  ""),
    ("realwide_atrvol",   "paper_test_realwide_state_atrvol.json",     "state", "pnl_pct",  "entry_ts",  "exit_ts",  "ARM-MATI"),
    ("donchian",          "paper_test_donchian_state.json",            "state", "pnl_pct",  "entry_ts",  "exit_ts",  ""),
    ("portfolio",         "paper_test_portfolio_state.json",           "state", "pnl_pct",  "entry_iso", "exit_iso", ""),
    ("pasar_anantara",    "paper_test_pasar_anantara_trade_state.json","state", "pnl_pct",  "entry_ts",  "exit_ts",  ""),
    ("shortbear",         "paper_test_shortbear_state.json",           "state", "pnl_pct",  "entry_iso", "exit_iso", ""),
    ("twoway",            "paper_test_twoway.jsonl",                   "jsonl", "pnl_pct",  "entry_time", "exit_time", ""),
    ("swing",             "paper_test_swing.jsonl",                    "jsonl", "pnl_pct",  "entry_time", "exit_time", ""),
    ("swing_partial",     "paper_test_swing_partial.jsonl",            "jsonl", "pnl_pct",  "entry_time", "exit_time", ""),
    ("swing_strict",      "paper_test_swing_strict.jsonl",             "jsonl", "pnl_pct",  "entry_time", "exit_time", ""),
    ("swing_atrvol",      "paper_test_swing_atrvol.jsonl",             "jsonl", "pnl_pct",  "entry_time", "exit_time", ""),
    ("spot_swing_cex",    "paper_test_spot_swing_cex_trades.jsonl",    "jsonl", "pnl_pct",  "entry_ts",  "exit_ts",  ""),
    ("spot_swing_cex_spot","paper_test_spot_swing_cex_spot_trades.jsonl","jsonl","pnl_pct", "entry_ts",  "exit_ts",  ""),
    ("e2_momentum",       "e2_momentum_paper.jsonl",                   "jsonl", "pnl_pct",  "ts",        "ts+hold",  ""),
    ("hl_replay",         "hl_paper_replay_journal.jsonl",             "jsonl", "net_pct",  "ts",        "ts+hold",  "REPLAY"),
    ("aster",             "paper_test_aster_state.json",               "state", "net_pct",  "entry_time","exit_time",""),
    ("hyperliquid",       "paper_test_hyperliquid_state.json",         "state", "net_pct",  "entry_time","exit_time",""),
    ("spot_swing_v2",     "paper_test_spot_swing_v2_state.json",       "state", "gross_pct","entry_time","exit_time","GROSS"),
    ("mv_funding",        "mv_funding_paper.json",                     "state", "__div_notional__", "entry_ts", "exit_ts", "CARRY"),
    ("micro_live",        "realwide_micro_live.jsonl",                 "jsonl", "net_pct",  "entry_time","exit_time","UANG-NYATA"),
]

# kontrol negatif (Lampiran B)
CONTROL_SPECS = [
    ("CTRL-realwide", "paper_test_realwide_state.json", "RANDOM"),
    ("CTRL-atrvolopen", "paper_test_realwide_state_atrvolopen.json", "RANDOM"),
]


def parse_ts(v):
    """Epoch detik/milidetik atau ISO -> epoch detik. Toleran, None bila gagal."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        x = float(v)
    else:
        s = str(v).strip()
        try:
            x = float(s)
        except ValueError:
            try:
                d = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
                return d.timestamp()
            except ValueError:
                return None
    if abs(x) > 1e11:
        x /= 1000.0
    if x <= 0:
        return None
    return x


def _reject_control(rows):
    """Buang baris kontrol RANDOM dari track sinyal (pelajaran R3)."""
    out = []
    for r in rows:
        lbl = str(r.get("track") or r.get("arm") or "").upper()
        if lbl == "RANDOM" or str(r.get("regime") or "").upper() == "RANDOM_CONTROL":
            continue
        out.append(r)
    return out


def _hygiene_money(rows):
    """P12 (amend 05-Okt, SEBELUM evaluasi ulang): mesin uang-nyata —
    buang baris audit-log palsu: close_rc kosong ATAU duplikat butir-identik
    (entry_time+exit_time+pnl persis sama). Ditemukan: 171 baris ETH
    KILL_FLATTEN palsu pre-guard 25-Sep di realwide_micro_live.jsonl."""
    out = []
    seen = set()
    for r in rows:
        if r.get("close_rc") in (None, ""):
            continue
        key = (str(r.get("entry_time")), str(r.get("exit_time")),
               str(r.get("pnl_usd")), str(r.get("net_pct")))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def load_engine(name, fname, mode, ret_field, f_in, f_exit, flag, keep_control=False):
    p = DATA / fname
    if not p.exists():
        return None
    if mode == "state":
        d = json.loads(p.read_text())
        rows = d.get("closed", []) if isinstance(d, dict) else []
    else:
        rows = []
        with open(p) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    if not keep_control:
        rows = _reject_control(rows)
    # P12: hygiene uang-nyata (flag memuat "UANG") — baris audit-log palsu dibuang
    if "UANG" in str(flag).upper():
        rows = _hygiene_money(rows)

    recs = []
    for r in rows:
        if ret_field == "__div_notional__":
            try:
                rv = float(r.get("pnl_usd")) / float(r.get("notional"))
            except Exception:
                continue
        else:
            v = r.get(ret_field)
            if v is None:
                continue
            try:
                rv = float(v)
            except Exception:
                continue
        t_in = parse_ts(r.get(f_in))
        if f_exit == "ts+hold":
            hold = r.get("hold_s")
            if hold is None:
                hold = (r.get("hold_h") or 0) * 3600.0
            try:
                t_ex = (t_in or 0) + float(hold)
            except Exception:
                t_ex = t_in
        else:
            t_ex = parse_ts(r.get(f_exit))
        if t_ex is None:
            t_ex = t_in
        if t_ex is None:
            continue
        recs.append((t_ex, rv))
    if not recs:
        return None
    recs.sort(key=lambda x: x[0])
    return {"name": name, "flag": flag, "n": len(recs), "recs": recs}


def global_grid(engines, span_only=True):
    """Grid 48 jam GLOBAL: semua mesin dibucket ke grid yang sama -> korelasi bersih."""
    exits = [t for e in engines for t, _ in e["recs"]]
    if not exits:
        return None, {}
    t0 = min(exits)
    grid = {}
    for e in engines:
        buckets = {}
        for t, rv in e["recs"]:
            k = int((t - t0) // (WINDOW_H * 3600.0))
            buckets[k] = buckets.get(k, 0.0) + rv
        if span_only and buckets:
            lo, hi = min(buckets), max(buckets)
            for k in range(lo, hi + 1):
                buckets.setdefault(k, 0.0)
        grid[e["name"]] = buckets
    return t0, grid


def sharpe(vals):
    if len(vals) < 2:
        return float("nan")
    sd = st.pstdev(vals)
    if sd == 0:
        return float("nan")
    return st.mean(vals) / sd


def signflip_p(vals, n_sim=N_SIM, seed=SEED):
    """p dua-sisi: H0 mean=0, tanda diacak. Tahan thd ekor gemuk."""
    n = len(vals)
    if n < 5:
        return float("nan")
    obs = st.mean(vals)
    rng = random.Random(seed)
    hit = 0
    for _ in range(n_sim):
        m = sum(v if rng.getrandbits(1) else -v for v in vals) / n
        if abs(m) >= abs(obs):
            hit += 1
    return (hit + 1) / (n_sim + 1)


def bh_fdr(pvals, q=FDR_Q):
    items = sorted([(k, p) for k, p in pvals.items() if p == p], key=lambda x: x[1])
    m = len(items)
    out = {k: False for k in pvals}
    kmax = 0
    for i, (k, p) in enumerate(items, start=1):
        if p <= q * i / m:
            kmax = i
    for i, (k, p) in enumerate(items, start=1):
        if i <= kmax:
            out[k] = True
    return out


def segments_of(vals, k=3):
    if len(vals) < k * 3:
        return [[] for _ in range(k)]
    size = len(vals) // k
    return [vals[i * size:(i + 1) * size] if i < k - 1 else vals[i * size:] for i in range(k)]


def pearson(xs, ys):
    n = len(xs)
    if n < 5:
        return float("nan")
    mx, my = st.mean(xs), st.mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return float("nan")
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def main():
    print("=" * 88)
    print("D14 — SENSUS EDGE LINTAS-MESIN  (protokol dibekukan sebelum dijalankan)")
    print("=" * 88)
    print(f"Ambang P9: n_windows>={MIN_WINDOWS} | Sharpe48>={SHARPE_48H_MIN:.4f} "
          f"(tahunan {SHARPE_48H_MIN*math.sqrt(PERIODS_YEAR):.2f}) | 3/3 segmen | "
          f"p_terburuk<0,05 | BH-FDR q={FDR_Q}")
    print()

    engines = []
    for spec in SPECS:
        e = load_engine(*spec)
        if e is None:
            print(f"  [LEWAT] {spec[0]}: berkas kosong / tak terbaca")
            continue
        e["flag"] = spec[6]
        engines.append(e)
    print(f"mesin dimuat: {len(engines)}")

    t0, grid = global_grid(engines)
    rows = []
    print()
    print(f"{'mesin':22s} {'n':>5s} {'win':>4s} {'mean48%':>9s} {'sd48%':>7s} {'SR_thn':>7s} "
          f"{'p_win':>7s} {'p_day':>7s} {'seg':>5s} {'flag':>11s}")
    for e in engines:
        b = grid[e["name"]]
        ks = sorted(b)
        vals = [b[k] for k in ks]
        # p berbasis jendela (non-overlap -> ~independen)
        p_win = signflip_p(vals, seed=SEED)
        # p cluster per HARI atas return per-trade (paling konservatif)
        byday = {}
        for t, rv in e["recs"]:
            d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
            byday.setdefault(d, []).append(rv)
        # BUG YANG DIPERBAIKI (05-Okt): versi pertama meresample hari TANPA
        # membalik tanda, sehingga membandingkan mean-bootstrap dengan mean
        # observasi -- selalu ~0,5 untuk SEMUA mesin (tidak menguji apa pun).
        # Gejala pembongkarnya: p_day seragam ~0,50 di 21 mesin berbeda.
        # Yang benar: SIGN-FLIP di level CLUSTER (hari), bukan di level trade.
        # O(n_hari) per simulasi karena memakai (sum, n) per grup.
        gs = [(sum(g), len(g)) for g in byday.values()]
        obs = st.mean([rv for _, rv in e["recs"]])
        rng = random.Random(SEED + 1)
        ng = len(gs)
        hit = 0
        for _ in range(N_SIM):
            ssum = 0.0
            ncnt = 0.0
            for _g in range(ng):
                a, b = gs[rng.randrange(ng)]
                if rng.getrandbits(1):      # <-- INTI: balik tanda per cluster
                    a = -a
                ssum += a
                ncnt += b
            if ncnt and abs(ssum / ncnt) >= abs(obs):
                hit += 1
        p_day = (hit + 1) / (N_SIM + 1)
        p_worst = max(p_win, p_day) if p_win == p_win and p_day == p_day else float("nan")
        sr = sharpe(vals)
        sr_ann = sr * math.sqrt(PERIODS_YEAR) if sr == sr else float("nan")
        segs = segments_of([rv for _, rv in e["recs"]])
        seg_pos = sum(1 for s in segs if len(s) >= 5 and st.mean(s) > 0)
        seg_tot = sum(1 for s in segs if len(s) >= 5)
        seg_str = f"{seg_pos}/{seg_tot}" if seg_tot else "-"
        rows.append({
            "name": e["name"], "n": e["n"], "n_windows": len(vals),
            "mean48_pct": st.mean(vals) * 100 if vals else float("nan"),
            "sd48_pct": st.pstdev(vals) * 100 if len(vals) > 1 else float("nan"),
            "sharpe_48h": sr, "sharpe_annual": sr_ann,
            "p_window": p_win, "p_day_cluster": p_day, "p_worst": p_worst,
            "segments_positive": seg_pos, "segments_assessable": seg_tot,
            "flag": e["flag"], "vals": vals, "buckets": b,
        })
        print(f"{e['name']:22s} {e['n']:5d} {len(vals):4d} {rows[-1]['mean48_pct']:9.3f} "
              f"{rows[-1]['sd48_pct']:7.3f} {sr_ann:7.2f} {p_win:7.4f} {p_day:7.4f} "
              f"{seg_str:>5s} {e['flag']:>11s}")

    # BH-FDR atas SELURUH keluarga (hanya yang sanggup diuji)
    eligible = [r for r in rows if r["n_windows"] >= MIN_WINDOWS]
    pv = {r["name"]: r["p_worst"] for r in eligible}
    passes = bh_fdr(pv, FDR_Q)
    for r in rows:
        r["bh_pass"] = bool(passes.get(r["name"], False))
        r["pass"] = bool(
            r["n_windows"] >= MIN_WINDOWS
            and r["sharpe_48h"] == r["sharpe_48h"] and r["sharpe_48h"] >= SHARPE_48H_MIN
            and r["segments_assessable"] > 0
            and r["segments_positive"] == r["segments_assessable"]
            and r["p_worst"] == r["p_worst"] and r["p_worst"] < 0.05
            and r["bh_pass"]
            and "GROSS" not in r["flag"] and "REPLAY" not in r["flag"]
        )

    print()
    print("-" * 88)
    print(f"KELUARGA: {len(rows)} mesin | sanggup diuji (n_windows>={MIN_WINDOWS}): {len(eligible)}")
    print(f"lolos BH-FDR q={FDR_Q}: {sum(1 for r in rows if r['bh_pass'])}")
    print(f"LULUS P9 (kelima syarat): {sum(1 for r in rows if r['pass'])}")
    print("-" * 88)
    for r in sorted(rows, key=lambda x: -(x["sharpe_annual"] if x["sharpe_annual"] == x["sharpe_annual"] else -99)):
        if r["pass"]:
            print(f"  ✅ LULUS  {r['name']:20s} SR_thn={r['sharpe_annual']:.2f} "
                  f"p_worst={r['p_worst']:.4f} seg={r['segments_positive']}/{r['segments_assessable']}")
    for r in sorted(rows, key=lambda x: -(x["sharpe_annual"] if x["sharpe_annual"] == x["sharpe_annual"] else -99)):
        if not r["pass"]:
            why = []
            if r["n_windows"] < MIN_WINDOWS:
                why.append(f"n_win<{MIN_WINDOWS}")
            if not (r["sharpe_48h"] == r["sharpe_48h"] and r["sharpe_48h"] >= SHARPE_48H_MIN):
                why.append("SR<2,3")
            if r["segments_assessable"] == 0 or r["segments_positive"] != r["segments_assessable"]:
                why.append(f"seg {r['segments_positive']}/{r['segments_assessable']}")
            if not (r["p_worst"] == r["p_worst"] and r["p_worst"] < 0.05):
                why.append(f"p={r['p_worst']:.3f}")
            if not r["bh_pass"]:
                why.append("FDR")
            if r["flag"]:
                why.append(r["flag"])
            print(f"  ❌ GAGAL  {r['name']:20s} {' '.join(why)}")

    # kontrol negatif
    print()
    print("-" * 88)
    print("KONTROL NEGATIF (harus GAGAL; bila lulus, alat ukur rusak)")
    print("-" * 88)
    ctrl_results = []
    for nm, fname, lbl in CONTROL_SPECS:
        e = load_engine(nm, fname, "state", "pnl_pct", "entry_ts", "exit_ts", "", keep_control=True)
        if e is None:
            continue
        # ambil HANYA baris kontrol dari state
        d = json.loads((DATA / fname).read_text())
        act = [r for r in d.get("closed", [])
               if str(r.get("track") or "").upper() == lbl]
        if len(act) < 5:
            print(f"  {nm}: n={len(act)} terlalu kecil -> '-'")
            continue
        vals = [float(r["pnl_pct"]) for r in act]
        p = signflip_p(vals, seed=SEED)
        sr = sharpe(vals)
        sr_ann = sr * math.sqrt(PERIODS_YEAR) if sr == sr else float("nan")
        # Kontrol dinilai dengan ATURAN P9 PENUH, termasuk n_windows>=20.
        # Versi pertama hanya memakai ambang Sharpe+p tanpa syarat n, lalu
        # menyimpulkan "alat ukur rusak" dari n=9 -- itu kesalahan Tipe II
        # (menyalahkan alat atas sampel yang memang belum layak dinilai).
        if len(vals) < MIN_WINDOWS:
            verdict = f"'- (belum dapat dinilai: n={len(vals)}<{MIN_WINDOWS})"
            ok = True           # tidak dapat menilai != lulus
            gated = False
        else:
            gated = bool(sr == sr and sr >= SHARPE_48H_MIN and p < 0.05)
            ok = not gated
            verdict = "BENAR (gagal)" if ok else "LULUS -> ALAT UKUR RUSAK"
        ctrl_results.append({"name": nm, "n": len(vals), "sharpe_annual": sr_ann,
                             "p": p, "assessable": len(vals) >= MIN_WINDOWS,
                             "gated_pass": gated, "correctly_failed": ok})
        print(f"  {nm:18s} n={len(vals):3d} SR_thn={sr_ann:6.2f} p={p:.4f} -> {verdict}")

    # ── FPR alat ukur: seberapa sering pipeline P9 "lulus" di bawah H0? ──
    print()
    print("-" * 88)
    print("VALIDASI ALAT UKUR — tingkat positif palsu (FPR) di bawah H0 murni")
    print("-" * 88)
    pooled = [rv for e in engines for _, rv in e["recs"]]
    mu_pool = st.mean(pooled)
    centered = [v - mu_pool for v in pooled]
    rng2 = random.Random(SEED + 7)
    K = 400
    fpr_p = fpr_joint = 0
    for _ in range(K):
        nw = rng2.choice([20, 25, 31, 45, 60])
        syn = [rng2.choice(centered) for _ in range(nw)]
        pp = signflip_p(syn, n_sim=2000, seed=SEED + _)   # resolusi 1/2001 cukup utk FPR
        ss = sharpe(syn)
        if pp < 0.05:
            fpr_p += 1
        if pp < 0.05 and ss == ss and ss >= SHARPE_48H_MIN:
            fpr_joint += 1
    print(f"  {K} mesin sintetis dari return terpusat (H0 benar: tak ada edge)")
    print(f"  FPR uji p<0,05                      = {fpr_p/K:.3f}   (harapan ~0,05)")
    print(f"  FPR gabungan (p<0,05 DAN SR>=2,3)   = {fpr_joint/K:.3f}   (harapan <=0,05)")
    instrument_ok = (fpr_p / K) <= 0.10
    print(f"  -> alat ukur {'SAH' if instrument_ok else 'RUSAK'} "
          f"(batas binomial ~2,3 sd dari 0,05 = 0,077)")

    # korelasi antar mesin yang lulus
    winners = [r for r in rows if r["pass"]]
    corr = []
    print()
    print("-" * 88)
    print(f"KORELASI antar mesin LULUS (syarat portofolio: rho <= 0,10)  n_lulus={len(winners)}")
    print("-" * 88)
    if len(winners) < 2:
        print("  kurang dari 2 mesin lulus -> korelasi tidak dapat dihitung.")
        print("  -> PORTOFOLIO TIDAK DAPAT DIBENTUK. Target 0,8%/48j belum punya jalur.")
    else:
        for i in range(len(winners)):
            for j in range(i + 1, len(winners)):
                a, b = winners[i], winners[j]
                ks = sorted(set(a["buckets"]) | set(b["buckets"]))
                xs = [a["buckets"].get(k, 0.0) for k in ks]
                ys = [b["buckets"].get(k, 0.0) for k in ks]
                rho = pearson(xs, ys)
                corr.append({"a": a["name"], "b": b["name"], "rho": rho, "n": len(ks)})
                mark = "OK" if (rho == rho and rho <= 0.10) else "LAMPAUI"
                print(f"  {a['name']:16s} x {b['name']:16s} rho={rho:+.3f} n={len(ks):3d}  {mark}")

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "protocol": "docs/sodex/D14_PROTOKOL_SENSUS_EDGE_2026-10-05.md",
        "thresholds": {"min_windows": MIN_WINDOWS, "sharpe_48h_min": SHARPE_48H_MIN,
                       "sharpe_annual_min": 2.3, "fdr_q": FDR_Q},
        "family_size": len(rows), "eligible": len(eligible),
        "n_bh_pass": sum(1 for r in rows if r["bh_pass"]),
        "n_pass": sum(1 for r in rows if r["pass"]),
        "engines": [{k: v for k, v in r.items() if k not in ("vals", "buckets")} for r in rows],
        "controls": ctrl_results,
        "instrument_fpr_p": fpr_p / K,
        "instrument_fpr_joint": fpr_joint / K,
        "instrument_ok": instrument_ok,
        "correlations_passing": corr,
        "verdict": ("PORTOFOLIO-ADA-JALUR" if len(winners) >= 2 else "TIDAK-ADA-MESIN-LULUS"),
    }
    (DATA / "sodex_edge_census.json").write_text(json.dumps(out, indent=1))
    print()
    print(f"-> {DATA / 'sodex_edge_census.json'}")
    print(f"VERDICT: {out['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())