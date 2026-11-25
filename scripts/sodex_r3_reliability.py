#!/usr/bin/env python3
"""R3 — Reliabilitas REAL-wide: apakah 'edge' ini nyata atau seleksi?

MASALAH YANG DIJAWAB
--------------------
D12/R2 menemukan level rata-rata cukup sementara capaian jendela 48 jam hanya
~46%. Pertanyaan R3: dari mana kegagalan reliabilitas itu berasal?

DUA BAHAYA STATISTIK YANG HARUS DITUTUP (aturan anti-p-hacking proyek):
 1. SELEKSI (max-of-k). Memilih SOL karena mean-nya tertinggi dari 22 simbol
    adalah memilih maksimum 22 undian. E[max undian] SELALU > 0 walau tak ada
    edge. Wajib dibandingkan terhadap distribusi null max-of-k.
 2. MULTIPLE TESTING. Menguji 22 simbol sekaligus menuntut koreksi BH-FDR.

ATURAN BESI:
 - n>=20 = dapat dinilai; n<20 = '-' (belum dapat dinilai), BUKAN 'no'.
 - Klaim butuh n>=30.
 - Uji pada SAMPEL PENUH; segmen hanya untuk KETAHANAN (>=3 segmen).
"""
from __future__ import annotations

import json
import math
import random
import statistics as st
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
STATE = DATA / "paper_test_realwide_state.json"
SEED = 20261005          # tetap supaya reproducible
N_SIM = 20000


# ── pemuatan ────────────────────────────────────────────────────────────────
def load_signal_rows(path: Path = STATE) -> list[dict]:
    """Baris track SINYAL saja. Kontrol RANDOM dibuang (bukan sinyal alpha)."""
    d = json.loads(path.read_text())
    rows = d.get("closed", [])
    return [t for t in rows if str(t.get("track") or "").upper() != "RANDOM"]


def ret_of(t: dict) -> float:
    """Return per-trade pada notional (FRAKSI, bukan persen)."""
    return float(t["pnl_pct"])


def exit_ts(t: dict) -> float:
    return float(t.get("exit_ts") or t.get("entry_ts") or 0.0)


# ── statistik dasar ─────────────────────────────────────────────────────────
def per_symbol(rows: list[dict]) -> dict[str, list[float]]:
    by: dict[str, list[float]] = {}
    for t in rows:
        by.setdefault(t["sym"], []).append(ret_of(t))
    return by


def entry_day(t: dict) -> str:
    return datetime.fromtimestamp(float(t.get("entry_ts") or 0), tz=timezone.utc).strftime("%Y-%m-%d")


def cluster_bootstrap_p(vals_by_day: dict[str, list[float]],
                        n_sim: int = N_SIM, seed: int = SEED) -> float:
    """p dua-sisi dengan bootstrap CLUSTER per hari.

    Return trading berkorelasi di dalam hari (faktor pasar bersama: semua alt
    bergerak serempak). Bootstrap i.i.d. karena itu MENYEMPITKAN CI secara
    palsu. Di sini unit resample = HARI, bukan trade.
    """
    rng = random.Random(seed)
    groups = list(vals_by_day.values())
    if not groups or sum(len(g) for g in groups) < 5:
        return float("nan")
    pool = [v for g in groups for v in g]
    obs = st.mean(pool)
    hit = 0
    for _ in range(n_sim):
        pick = [groups[rng.randrange(len(groups))] for _ in range(len(groups))]
        flat = [v for g in pick for v in g]
        if abs(st.mean(flat)) >= abs(obs):
            hit += 1
    return (hit + 1) / (n_sim + 1)


def paired_day_test(sym: str, rows: list[dict], n_sim: int = N_SIM,
                    seed: int = SEED) -> tuple[float, int]:
    """Selisih rata-rata (sym - sisa) pada HARI yang sama.

    Mengendalikan faktor pasar bersama: hari yang buruk untuk semua alt tidak
    dihitung dua kali sebagai dua pengamatan independen. Return (p, n_hari).
    """
    rng = random.Random(seed)
    both: dict[str, list[list[float]]] = {}
    for t in rows:
        d = entry_day(t)
        pair = both.setdefault(d, [[], []])
        pair[0 if t["sym"] == sym else 1].append(ret_of(t))
    diffs = [st.mean(a) - st.mean(b) for a, b in both.values() if a and b]
    if len(diffs) < 5:
        return float("nan"), len(diffs)
    obs = st.mean(diffs)
    hit = 0
    for _ in range(n_sim):
        m = sum(v * (1.0 if rng.getrandbits(1) else -1.0) for v in diffs) / len(diffs)
        if abs(m) >= abs(obs):
            hit += 1
    return (hit + 1) / (n_sim + 1), len(diffs)


def welch_or_boot_p(vals: list[float], n_sim: int = 4000, rng=None) -> float:
    """p dua-sisi via bootstrap tanda (H0: mean=0, distribusi simetris thd 0).

    Bootstrap tanda tidak mengasumsikan normalitas -- penting karena return
    trading berekor gemuk. p = proporsi |mean_boot| >= |mean_obs|.
    """
    rng = rng or random.Random(SEED)
    n = len(vals)
    if n < 5:
        return float("nan")
    obs = st.mean(vals)
    signs = (-1.0, 1.0)
    hit = 0
    for _ in range(n_sim):
        m = sum(v * signs[rng.getrandbits(1)] for v in vals) / n
        if abs(m) >= abs(obs):
            hit += 1
    return (hit + 1) / (n_sim + 1)


def bh_fdr(pvals: dict[str, float], q: float = 0.10) -> dict[str, bool]:
    """Benjamini-Hochberg. True = lolos FDR pada q."""
    items = [(k, p) for k, p in pvals.items() if p == p]  # buang NaN
    items.sort(key=lambda x: x[1])
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


# ── UJI 1: seleksi max-of-k ─────────────────────────────────────────────────
def max_of_k_null(by: dict[str, list[float]], n_sim: int = N_SIM,
                  seed: int = SEED) -> dict:
    """Distribusi null untuk 'mean terbaik dari k simbol'.

    Prosedur: gabungkan seluruh return menjadi satu kumpulan, PUSATKAN ke nol
    (menghapus edge agregat), lalu untuk setiap simbol tarik n_i return acak
    tanpa pengembalian dan hitung mean-nya; ambil maksimum. Ulangi n_sim kali.
    Ini mengukur berapa besar mean-terbaik yang MUNCUL DARI KEBETULAN semata.
    """
    rng = random.Random(seed)
    pool = [v for vals in by.values() for v in vals]
    mu = st.mean(pool)
    centered = [v - mu for v in pool]          # H0: tak ada edge sama sekali
    ns = [len(v) for v in by.values()]
    maxes = []
    for _ in range(n_sim):
        best = -1e9
        for n_i in ns:
            s = sum(rng.choice(centered) for _ in range(n_i)) / n_i
            if s > best:
                best = s
        maxes.append(best)
    maxes.sort()
    return {"maxes": maxes, "mean": st.mean(maxes),
            "p50": maxes[len(maxes) // 2],
            "p95": maxes[int(len(maxes) * 0.95)],
            "p99": maxes[int(len(maxes) * 0.99)]}


def empirical_p(obs: float, null_sorted: list[float]) -> float:
    """p = proporsi null >= obs."""
    lo, hi = 0, len(null_sorted)
    while lo < hi:
        mid = (lo + hi) // 2
        if null_sorted[mid] < obs:
            lo = mid + 1
        else:
            hi = mid
    return (len(null_sorted) - lo + 1) / (len(null_sorted) + 1)


# ── UJI 2: ketahanan segmen ─────────────────────────────────────────────────
def segments(vals_with_ts: list[tuple[float, float]], k: int = 3) -> list[list[float]]:
    """Bagi kronologis menjadi k segmen; segmen tanpa daya uji -> None."""
    s = sorted(vals_with_ts, key=lambda x: x[1])
    if len(s) < k * 3:
        return [[] for _ in range(k)]
    size = len(s) // k
    out = []
    for i in range(k):
        chunk = s[i * size:(i + 1) * size] if i < k - 1 else s[i * size:]
        out.append([v for v, _ in chunk])
    return out


# ── UJI 3: konsentrasi ──────────────────────────────────────────────────────
def gini(xs: list[float]) -> float:
    """Gini atas KONTRIBUSI ABSOLUT (seberapa terpusat hasilnya)."""
    a = sorted(abs(x) for x in xs)
    n = len(a)
    if n == 0 or sum(a) == 0:
        return float("nan")
    cum = sum((i + 1) * v for i, v in enumerate(a))
    return (2 * cum) / (n * sum(a)) - (n + 1) / n


def main() -> int:
    rows = load_signal_rows()
    by = per_symbol(rows)
    print("=" * 78)
    print("R3 — RELIABILITAS REAL-wide")
    print("=" * 78)
    print(f"sumber : {STATE}")
    print(f"baris  : {len(rows)} trade SINYAL (kontrol RANDOM dibuang)")
    print(f"simbol : {len(by)}")
    print()

    # ---------- tabel per-simbol ----------
    print("-" * 78)
    print("A. PER-SIMBOL  (n>=20 dapat dinilai; n<30 belum cukup untuk klaim)")
    print("-" * 78)
    print(f"{'sym':7s} {'n':>4s} {'mean%':>8s} {'med%':>8s} {'WR%':>6s} {'sd%':>7s} {'net$':>9s} {'p':>7s}  {'BHFDR':>6s}")
    pvals = {}
    tab = []
    for s, v in by.items():
        p = welch_or_boot_p(v)
        pvals[s] = p
        tab.append((s, len(v), st.mean(v) * 100, st.median(v) * 100,
                    sum(1 for x in v if x > 0) / len(v) * 100,
                    st.pstdev(v) * 100, sum(x * 100 for x in v), p))
    passes = bh_fdr(pvals, q=0.10)
    tab.sort(key=lambda r: -r[2])
    for s, n, m, md, wr, sd, net, p in tab:
        tag = "" if n >= 20 else "  -"
        fdr = "LOLOS" if passes.get(s) else "-"
        pp = f"{p:.4f}" if p == p else "  n/a"
        print(f"{s:7s} {n:4d} {m:+8.3f} {md:+8.3f} {wr:6.1f} {sd:7.2f} {net:+9.2f} {pp:>7s}  {fdr:>6s}{tag}")
    n_assess = sum(1 for r in tab if r[1] >= 20)
    n_claim = sum(1 for r in tab if r[1] >= 30)
    print()
    print(f"  dapat dinilai (n>=20) : {n_assess}/{len(tab)}")
    print(f"  layak klaim (n>=30)   : {n_claim}/{len(tab)}")
    print(f"  mean lintas-simbol    : {st.mean(r[2] for r in tab):+.3f}%")
    print(f"  median lintas-simbol  : {st.median(r[2] for r in tab):+.3f}%")
    print(f"  simbol mean<0         : {sum(1 for r in tab if r[2] < 0)}/{len(tab)}")
    print(f"  lolos BH-FDR q=0,10   : {sum(1 for s in passes if passes[s])}/{len(passes)}")

    # ---------- UJI 1: seleksi ----------
    print()
    print("-" * 78)
    print("B. UJI SELEKSI max-of-k  (kandidat dideklarasikan di muka)")
    print("-" * 78)
    # Kandidat SAH hanya dari himpunan yang dapat dinilai. Mengambil mean
    # tertinggi dari SELURUH 22 simbol berarti membandingkan fluke n=3 vs
    # simbol ber-n besar -- itu bukan uji, itu kesalahan kategori.
    assess = [r for r in tab if r[1] >= 20]
    print(f"  himpunan kandidat sah (n>=20): {[r[0] for r in assess] or '(kosong)'}")
    best_sym, best_n, best_mean_pct = assess[0][0], assess[0][1], assess[0][2]
    best_mean = best_mean_pct / 100.0
    print(f"  Kandidat (mean tertinggi DI DALAM himpunan sah): {best_sym} "
          f"mean={best_mean_pct:+.3f}%  n={best_n}")
    naive = tab[0]
    if naive[2] > best_mean_pct:
        print(f"  (pembanding -- TIDAK SAH dipakai sbg kandidat: {naive[0]} "
              f"mean={naive[2]:+.3f}% n={naive[1]} < 20)")
    print()
    assess_by = {r[0]: by[r[0]] for r in assess}
    null = max_of_k_null(assess_by, n_sim=N_SIM)
    p_sel = empirical_p(best_mean, null["maxes"])
    print(f"  Distribusi null mean-terbaik dari k={len(assess_by)} simbol sah "
          f"({N_SIM} simulasi):")
    print(f"    E[max]  = {null['mean']*100:+.3f}%   (kebetulan saja)")
    print(f"    p50     = {null['p50']*100:+.3f}%")
    print(f"    p95     = {null['p95']*100:+.3f}%")
    print(f"    p99     = {null['p99']*100:+.3f}%")
    print(f"  Observasi {best_sym}: {best_mean*100:+.3f}%")
    print(f"  p (seleksi) = {p_sel:.4f}  -> {'LOLOS' if p_sel < 0.05 else 'TIDAK lolos'} (alpha 0,05)")
    print(f"  Persentil observasi dlm null = "
          f"{sum(1 for m in null['maxes'] if m < best_mean)/len(null['maxes'])*100:.1f}%")
    # p tak-terkoreksi untuk kandidat, sebagai pembanding
    p_cand_raw = pvals.get(best_sym, float('nan'))
    print(f"  p mentah (tak terkoreksi, per-simbol) = {p_cand_raw:.4f}"
          f"{'  <- juga tidak lolos 0,05' if p_cand_raw >= 0.05 else ''}")

    # ---------- UJI 2: ketahanan segmen untuk kandidat ----------
    print()
    print("-" * 78)
    print(f"C. KETAHANAN SEGMEN — {best_sym} (sampel penuh utk uji, segmen utk ketahanan)")
    print("-" * 78)
    cand_ts = [(ret_of(t), exit_ts(t)) for t in rows if t["sym"] == best_sym]
    segs = segments(cand_ts, k=3)
    ok_seg = 0
    for i, s in enumerate(segs, start=1):
        if len(s) < 5:
            print(f"  S{i}: n={len(s):2d}  '-' (belum dapat dinilai)")
            continue
        m = st.mean(s) * 100
        if m > 0:
            ok_seg += 1
        print(f"  S{i}: n={len(s):2d}  mean={m:+7.3f}%  med={st.median(s)*100:+7.3f}%  WR={sum(1 for x in s if x>0)/len(s)*100:5.1f}%")
    print(f"  -> segmen positif: {ok_seg}/3  (butuh 3/3 untuk lulus ketahanan)")

    # ---------- UJI 2b: KORELASI (uji yang paling tak memihak) ----------
    print()
    print("-" * 78)
    print(f"D. KETAHANAN TERHADAP KORELASI — {best_sym} (bootstrap cluster per HARI)")
    print("-" * 78)
    cand_rows = [t for t in rows if t["sym"] == best_sym]
    byday: dict[str, list[float]] = {}
    for t in cand_rows:
        byday.setdefault(entry_day(t), []).append(ret_of(t))
    p_cluster = cluster_bootstrap_p(byday)
    p_paired, n_days = paired_day_test(best_sym, rows)
    print(f"  {best_sym}: n={len(cand_rows)} trade di {len(byday)} hari")
    print(f"  p bootstrap i.i.d. (asli)      = {p_cand_raw:.4f}")
    print(f"  p bootstrap CLUSTER per hari   = {p_cluster:.4f}  <- jujur thd korelasi")
    print(f"  hari dgn {best_sym} & non-{best_sym} keduanya = {n_days}")
    print(f"  p berpasangan (vs sisa, hari sama) = {p_paired:.4f}")
    for nm, pv2 in (("i.i.d.", p_cand_raw), ("cluster/hari", p_cluster), ("berpasangan", p_paired)):
        print(f"    {nm:14s} {'LOLOS 0,05' if pv2 < 0.05 else 'TIDAK lolos 0,05'}")
    print(f"  -> korelasi intra-hari {'MENAIKKAN' if p_cluster > p_cand_raw else 'menurunkan'} p: "
          f"bukti {'LEBIH LEMAH' if p_cluster > p_cand_raw else 'lebih kuat'} dari kelihatannya")

    # ---------- UJI 3: konsentrasi ----------
    print()
    print("-" * 78)
    print("E. KONSENTRASI HASIL  (apakah profit bergantung pada segelintir simbol?)")
    print("-" * 78)
    sym_net = {s: sum(v) for s, v in by.items()}
    tot = sum(sym_net.values())
    pos = sorted([v for v in sym_net.values() if v > 0], reverse=True)
    top1 = pos[0] / tot * 100 if tot else float("nan")
    top3 = sum(pos[:3]) / tot * 100 if tot else float("nan")
    top5 = sum(pos[:5]) / tot * 100 if tot else float("nan")
    print(f"  net total (sinyal)   : {tot*100:+.2f} (unit notionalx100)")
    print(f"  kontribusi simbol #1 : {top1:5.1f}%  ({max(sym_net, key=lambda k: sym_net[k])})")
    print(f"  kontribusi top-3     : {top3:5.1f}%")
    print(f"  kontribusi top-5     : {top5:5.1f}%")
    print(f"  Gini kontribusi      : {gini(list(sym_net.values())):.3f}")
    print(f"  simbol net<0         : {sum(1 for v in sym_net.values() if v < 0)}/{len(sym_net)}")
    print(f"  -> bila HANYA simbol net>0 yang diperdagangkan:")
    print(f"     net = {sum(v for v in sym_net.values() if v>0)*100:+.2f} "
          f"(vs {tot*100:+.2f} bila semua; SELISIH = laba dari simbol yang merugi = ILUSI)")

    # ---------- ringkas ----------
    print()
    print("=" * 78)
    print("RINGKASAN R3")
    print("=" * 78)
    verdict = []
    verdict.append(f"cakupan: hanya {n_assess}/{len(tab)} simbol dapat dinilai (n>=20); {n_claim} layak klaim (n>=30)")
    verdict.append(f"median lintas-simbol {st.median(r[2] for r in tab):+.3f}% -> 'edge' TIDAK merata")
    verdict.append(f"kandidat {best_sym}: p_seleksi={p_sel:.4f}, "
                   f"p_cluster/hari={p_cluster:.4f}, p_berpasangan={p_paired:.4f} -> "
                   f"{'dapat dipisahkan dari kebetulan' if max(p_sel, p_cluster, p_paired) < 0.05 else 'TIDAK dapat dipisahkan dari kebetulan'}"
                   " [aturan: p TERBURUK harus lolos -- uji paling lemah yang menentukan]")
    verdict.append(f"ketahanan segmen {best_sym}: {ok_seg}/3")
    verdict.append(f"konsentrasi: top-3 = {top3:.1f}% dari net; {sum(1 for v in sym_net.values() if v<0)} simbol merugi")
    for v in verdict:
        print("  •", v)

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "n_trades": len(rows),
        "n_symbols": len(by),
        "n_assessable_ge20": n_assess,
        "n_claimable_ge30": n_claim,
        "cross_symbol_mean_pct": st.mean(r[2] for r in tab),
        "cross_symbol_median_pct": st.median(r[2] for r in tab),
        "candidate": best_sym,
        "candidate_mean_pct": best_mean_pct,
        "candidate_n": best_n,
        "selection_null_E_max_pct": null["mean"] * 100,
        "selection_null_p95_pct": null["p95"] * 100,
        "selection_p": p_sel,
        "p_uncorrected": p_cand_raw,
        "p_cluster_by_day": p_cluster,
        "p_paired_same_day": p_paired,
        "segments_positive": ok_seg,
        "bh_fdr_pass": [s for s in passes if passes[s]],
        "top3_share_pct": top3,
        "gini": gini(list(sym_net.values())),
        "symbols_negative": sum(1 for v in sym_net.values() if v < 0),
        # Uji yang menentukan = yang paling LEMAH (p terbesar), bukan paling kuat.
        # Memakai min() = memilih uji paling longgar = anti-konservatif.
        "verdict": ("CANDIDATE-WORTH-FORWARD-TEST" if max(p_sel, p_cluster, p_paired) < 0.05
                    else "PROMISING-NOT-ESTABLISHED"),
    }
    (DATA / "sodex_r3_reliability.json").write_text(json.dumps(out, indent=1))
    print()
    print(f"-> {DATA / 'sodex_r3_reliability.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())