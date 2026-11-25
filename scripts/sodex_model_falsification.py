#!/usr/bin/env python3
"""ANANTARA SAKTI — Falsifikasi sodex_model_server (LightGBM 48h).

MENGUJI klaim "model punya edge": PF 1.13 / dir-acc 55-73% OOS.

Bukan mengukur ulang hal yang sama, melainkan menguji APAKAH ANGKA ITU BERARTI.
Lima cacat yang diuji, semuanya terlihat di sumber `anantara/sodex_model_server.py`:

  F1 SELEKSI. `dir_acc` hanya dihitung pada baris `|pred| >= THRESHOLD (0.4%)`
     (baris 132-134). Model MEMILIH sampel mana yang dinilai -> akurasi naik
     tanpa kemampuan naik. Uji: bandingkan dgn akurasi pada SEMUA baris OOS.
  F2 JENDELA TUMPANG-TINDIH. Label = return 48 jam ke depan pada bar 1 jam;
     label bersebelahan berbagi 47 dari 48 jam. n efektif ~ n/48, bukan n.
     Akurasi 55% pada n_efektif kecil TIDAK terbedakan dari 50%.
  F3 SELEKSI JUARA. `champion_best_acc = max(dir_acc, champ_acc)` (baris 154)
     -> monoton NAIK, tidak pernah turun. Ini statistik "terbaik sepanjang masa",
     bukan akurasi sekarang. Ditambah saringan atas ~58 simbol = multiple testing.
  F4 TANPA BIAYA. Akurasi arah != laba. Uji P&L bersih setelah fee RT 8 bps.
  F5 DATA BEKU. Data training berakhir 2026-05-21 (mount read-only). Model
     "retrain tiap 6 jam" tetapi pada dataset yang sama -> angka tak pernah
     berubah. Model melayani pasar Oktober dgn pengetahuan Mei.

Aturan besi: setiap angka harus berasal dari baris yang labelnya SUDAH diketahui
(`idx < len - LABEL_H`). Tidak ada look-ahead.

Jalankan di dalam container yang punya lightgbm+talib:
  docker exec -i anantara-sodex-model python3 - < scripts/sodex_model_falsification.py
"""
from __future__ import annotations
import argparse, glob, json, math, os, sys, time

import numpy as np
import pandas as pd

# ── Konstanta: HARUS sama dgn sodex_model_server.py ────────────────────
LABEL_H = 48
THRESHOLD = 0.004
PERIODS = [14, 50]
LGB = dict(n_estimators=600, learning_rate=0.03, num_leaves=31, min_child_samples=20,
           feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=5, verbosity=-1, n_jobs=2)
MAX_FEATS = 9          # jumlah fitur pasca-transformasi (lihat _features)
MAX_FEATURES = 48      # batas keras lebar array fitur

FEES = {"sodex_rt_bps": 8.0}   # fee pulang-pergi SoDEX, bps

# ── Statistik murni (tanpa dependensi ML — bisa diuji di host) ─────────


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Selang kepercayaan Wilson (dua sisi) untuk proporsi. Kembalikan (lo, hi) 0..1.

    Dipakai alih-alih normal approx karena n kecil dan p dekat 0/1.
    """
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    d = 1.0 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - h) / d), min(1.0, (c + h) / d))


def effective_n(n_rows: int, horizon_h: int, bar_h: int = 1) -> float:
    """Jumlah observasi INDEPENDEN bila jendela label tumpang-tindih.

    n baris dgn horizon h pada bar bar_h -> tiap observasi independen terpisah
    h/bar_h baris, jadi n_eff = n * bar_h / h. Dibatasi minimal 1.
    """
    if horizon_h <= 0:
        return float(n_rows)
    return max(1.0, n_rows * bar_h / horizon_h)


def binom_p_two_sided(k: int, n: int, p0: float = 0.5) -> float:
    """p-value binomial dua sisi (eksak) untuk H0: p = p0."""
    if n <= 0:
        return 1.0
    from math import comb
    obs = comb(n, k) * (p0 ** k) * ((1 - p0) ** (n - k))
    tol = obs * (1 + 1e-9)
    total = 0.0
    for i in range(n + 1):
        pr = comb(n, i) * (p0 ** i) * ((1 - p0) ** (n - i))
        if pr <= tol:
            total += pr
    return min(1.0, total)


def bh_fdr(pvals: list[float], q: float = 0.10) -> list[bool]:
    """Benjamini-Hochberg. Kembalikan daftar bool 'lolos' sejajar dgn input."""
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    keep = [False] * m
    kmax = -1
    for rank, i in enumerate(order, start=1):
        if pvals[i] <= q * rank / m:
            kmax = rank
    for rank, i in enumerate(order, start=1):
        if rank <= kmax:
            keep[i] = True
    return keep


def net_bps(direction: str, fwd_ret: float, fee_rt_bps: float) -> float:
    """P&L bersih (bps) satu sinyal. FLAT = 0; LONG/SHORT dikurangi fee RT."""
    if direction == "FLAT":
        return 0.0
    sign = 1.0 if direction == "LONG" else -1.0
    gross = sign * fwd_ret * 10_000.0
    return gross - fee_rt_bps


def mean_ci95(xs: list[float]) -> tuple[float, float, float]:
    """Rata-rata dan CI95 (normal) dari daftar angka. (-,-,-) bila n<2."""
    if len(xs) < 2:
        return (float("nan"), float("nan"), float("nan"))
    a = np.asarray(xs, dtype=float)
    m = float(a.mean())
    se = float(a.std(ddof=1) / math.sqrt(len(a)))
    return (m, m - 1.96 * se, m + 1.96 * se)


def split3(idx: list[int]) -> list[list[int]]:
    """Bagi urutan indeks menjadi 3 segmen kronologis (untuk uji ketahanan)."""
    n = len(idx)
    if n < 9:
        return []
    a, b = n // 3, 2 * (n // 3)
    return [idx[:a], idx[a:b], idx[b:]]


# ── Fitur: SALINAN PERSIS dari sodex_model_server._features ─────────────


def features(df: pd.DataFrame):
    """Identik dgn server: talib RSI/ADX/MFI/ATR/BBANDS/MACD/EMA/ROC/OBV."""
    import talib
    o, h, l, c, v = (df[x].values for x in ("open", "high", "low", "close", "volume"))
    f = pd.DataFrame(index=df.index)
    for p in PERIODS:
        f[f"rsi{p}"] = talib.RSI(c, p); f[f"adx{p}"] = talib.ADX(h, l, c, p)
        f[f"mfi{p}"] = talib.MFI(h, l, c, v, p); f[f"atr{p}"] = talib.ATR(h, l, c, p) / c
        up, mid, lo = talib.BBANDS(c, p)
        f[f"bbw{p}"] = (up - lo) / mid; f[f"bbp{p}"] = (c - lo) / (up - lo + 1e-9)
        _, _, hist = talib.MACD(c, p, p * 2, max(2, p // 2)); f[f"mh{p}"] = hist / c
        f[f"er{p}"] = c / talib.EMA(c, p) - 1; f[f"roc{p}"] = talib.ROC(c, p)
    f["p1"] = pd.Series(c).pct_change(1).values; f["p5"] = pd.Series(c).pct_change(5).values
    f["vs"] = v / (talib.SMA(v, 20) + 1e-9); f["hl"] = (h - l) / c
    obv = talib.OBV(c, v); f["obvr"] = obv / (talib.SMA(obv, 20) + 1e-9)
    return f


# ── Eksperimen satu simbol ─────────────────────────────────────────────


def split_rows(n: int) -> tuple[np.ndarray, np.ndarray, int]:
    """Bagi indeks persis seperti server: 85% train / 15% OOS, keduanya < n-LABEL_H."""
    end = n - LABEL_H
    cut = int(end * 0.85)
    idx = np.arange(n)
    return idx[idx < cut], idx[(idx >= cut) & (idx < end)], end


def run_symbol(sym: str, data_dir: str, shuffles: int = 0) -> dict | None:
    import lightgbm as lgb
    fname = sym.replace("-", "_")               # server: BTC-USD -> BTC_USD-1h.feather
    p = os.path.join(data_dir, f"{fname}-1h.feather")
    if not os.path.exists(p):
        return None
    df = pd.read_feather(p).sort_values("date").reset_index(drop=True)
    if len(df) < 400:
        return None
    close = df["close"].values.astype(float)
    feats = features(df)
    X = feats.values.astype(float)
    label = pd.Series(close).shift(-LABEL_H).values / close - 1

    tr, oos, end = split_rows(len(df))
    m = ~np.isnan(X).any(axis=1) & ~np.isnan(label)
    tr = tr[m[tr]]; oos = oos[m[oos]]
    if len(tr) < 300 or len(oos) < 20:
        return None

    rec: dict = {"symbol": sym, "n_rows": int(len(df)), "n_train": int(len(tr)),
                 "n_oos": int(len(oos)),
                 "data_start": str(df["date"].min())[:10], "data_end": str(df["date"].max())[:10]}

    # --- 1. REPRODUKSI: cara server menghitung dir_acc (dgn seleksi) ---
    model = lgb.LGBMRegressor(**LGB)
    model.fit(X[tr], label[tr])
    pred = model.predict(X[oos]); act = label[oos]
    sel = np.abs(pred) >= THRESHOLD
    n_sel = int(sel.sum())
    k_sel = int(((pred[sel] > 0) == (act[sel] > 0)).sum()) if n_sel else 0
    acc_sel = (100.0 * k_sel / n_sel) if n_sel else float("nan")
    rec["F1_acc_as_reported"] = round(acc_sel, 3) if n_sel else None
    rec["F1_n_selected"] = n_sel
    rec["F1_frac_selected"] = round(n_sel / len(oos), 4) if len(oos) else 0.0

    # --- 2. TANPA SELEKSI: akurasi pada SEMUA baris OOS ---
    k_all = int(((pred > 0) == (act > 0)).sum())
    acc_all = 100.0 * k_all / len(oos)
    lo, hi = wilson_ci(k_all, len(oos))
    rec["F1_acc_unselected"] = round(acc_all, 3)
    rec["F1_unsel_ci95"] = [round(lo * 100, 2), round(hi * 100, 2)]

    # --- 3. n EFEKTIF: koreksi jendela tumpang-tindih ---
    ne = effective_n(len(oos), LABEL_H, 1)
    rec["F2_n_oos"] = int(len(oos))
    rec["F2_n_effective"] = round(ne, 1)
    rec["F2_shrink_factor"] = round(len(oos) / ne, 1)
    # uji H0=50% pada n efektif (konservatif: pakai proporsi yg sama)
    k_eff, n_eff = int(round(acc_all / 100 * ne)), int(round(ne))
    rec["F2_p_binom_neff"] = round(binom_p_two_sided(k_eff, n_eff, 0.5), 4) if n_eff > 0 else 1.0
    lo_e, hi_e = wilson_ci(k_eff, n_eff)
    rec["F2_neff_ci95"] = [round(lo_e * 100, 2), round(hi_e * 100, 2)]
    rec["F2_ambiguous"] = bool(lo_e <= 0.5 <= hi_e)

    # --- 4. BIAYA: P&L bersih setelah fee ---
    direction = np.where(pred > THRESHOLD, "LONG", np.where(pred < -THRESHOLD, "FLAT", "FLAT"))
    direction = np.where(pred < -THRESHOLD, "SHORT", direction)
    nets, n_trade = [], 0
    for i in range(len(oos)):
        d = direction[i]
        if d == "FLAT":
            nets.append(0.0); continue
        nets.append(net_bps(d, float(act[i]), FEES["sodex_rt_bps"])); n_trade += 1
    traded = [x for x in nets if x != 0.0]
    mn, mlo, mhi = mean_ci95(traded)
    rec["F4_n_trades"] = n_trade
    rec["F4_frac_traded"] = round(n_trade / len(oos), 4) if len(oos) else 0.0
    rec["F4_net_bps_mean"] = round(mn, 2) if traded else None
    rec["F4_net_bps_ci95"] = [round(mlo, 2), round(mhi, 2)] if traded else None
    rec["F4_positive"] = bool(not math.isnan(mn) and mn > 0)

    # --- 5. KETAHANAN: 3 segmen kronologis ---
    segs = split3([int(i) for i in range(len(oos))])
    seg_rows = []
    for j, s in enumerate(segs, start=1):
        if not s:
            seg_rows.append({"seg": j, "n": 0, "net_bps": None, "verdict": "-"}); continue
        xs = [nets[i] for i in s if nets[i] != 0.0]
        if len(xs) < 5:
            seg_rows.append({"seg": j, "n": len(xs), "net_bps": None, "verdict": "-"}); continue
        sm, sl, sh = mean_ci95(xs)
        verdict = "OK" if sm > 0 else "no"
        if sl <= 0 <= sh:
            verdict = "-"      # CI memuat 0 -> belum dapat dinilai (daya kurang)
        seg_rows.append({"seg": j, "n": len(xs), "net_bps": round(sm, 2),
                         "ci95": [round(sl, 2), round(sh, 2)], "verdict": verdict})
    rec["F5_segments"] = seg_rows
    rec["F5_seg_verdicts"] = "".join(r["verdict"] for r in seg_rows)

    # --- 6. KONTROL NEGATIF: acak label, latih ulang ---
    if shuffles > 0:
        rng = np.random.default_rng(20261005)
        null_acc = []
        lab = label.copy()
        for _ in range(shuffles):
            lab_s = lab.copy()
            rng.shuffle(lab_s)                       # putus asosiasi fitur<->label
            lab_s[tr] = label[tr]                    # latih tetap pakai label asli
            mdl = lgb.LGBMRegressor(**LGB)
            mdl.fit(X[tr], label[tr])                # model sama
            pr = mdl.predict(X[oos])                 # tapi nilai pada OOS yg teracak
            # bandingkan dgn label OOS teracak (bukan asli)
            kk = int(((pr > 0) == (lab_s[oos] > 0)).sum())
            null_acc.append(100.0 * kk / len(oos))
        rec["NEG_null_acc_mean"] = round(float(np.mean(null_acc)), 3)
        rec["NEG_null_acc_sd"] = round(float(np.std(null_acc, ddof=1)), 3) if len(null_acc) > 1 else None
        rec["NEG_null_acc_min"] = round(float(np.min(null_acc)), 3)
        rec["NEG_null_acc_max"] = round(float(np.max(null_acc)), 3)
        rec["NEG_acc_above_null_by"] = round(acc_all - float(np.mean(null_acc)), 3)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description="Falsifikasi sodex_model_server")
    ap.add_argument("--data-dir", default=os.environ.get("SODEX_FALSIF_DATA", "/data/perps"))
    ap.add_argument("--symbols", default="", help="daftar dipisah koma; kosong = semua feather")
    ap.add_argument("--shuffles", type=int, default=0, help="kontrol negatif per simbol (0=mati)")
    ap.add_argument("--neg-symbols", default="BTC-USD,ETH-USD,SOL-USD,AMD-USD,SILVER-USD,LINK-USD")
    ap.add_argument("--out", default="")
    ap.add_argument("--quick", action="store_true", help="hanya 6 simbol uji cepat")
    a = ap.parse_args()

    if a.symbols:
        syms = [s.strip() for s in a.symbols.split(",") if s.strip()]
    else:
        syms = sorted(os.path.basename(p)[:-len("-1h.feather")].replace("_", "-")
                      for p in glob.glob(os.path.join(a.data_dir, "*-1h.feather")))
    if a.quick:
        syms = [s for s in syms if s in ("BTC-USD", "ETH-USD", "SOL-USD", "AMD-USD", "SILVER-USD", "LINK-USD")]

    negset = {s.strip() for s in a.neg_symbols.split(",")}
    print(f"# Falsifikasi sodex_model_server — {len(syms)} simbol, data_dir={a.data_dir}", flush=True)
    recs = []
    t0 = time.time()
    for i, s in enumerate(syms, 1):
        try:
            sh = a.shuffles if s in negset else 0
            r = run_symbol(s, a.data_dir, shuffles=sh)
            if r:
                recs.append(r)
                print(f"  [{i}/{len(syms)}] {s:14s} dilaporkan={r.get('F1_acc_as_reported')} "
                      f"jujur={r.get('F1_acc_unselected')} n_eff={r.get('F2_n_effective')} "
                      f"net={r.get('F4_net_bps_mean')} seg={r.get('F5_seg_verdicts')}", flush=True)
        except Exception as e:
            print(f"  [{i}/{len(syms)}] {s}: GAGAL {e}", flush=True)

    # ── Saringan lintas-simbol: BH-FDR atas p binomial n-efektif ──
    pv = [r["F2_p_binom_neff"] for r in recs if r.get("F2_p_binom_neff") is not None]
    keep = bh_fdr(pv, q=0.10)
    for r, k in zip([r for r in recs if r.get("F2_p_binom_neff") is not None], keep):
        r["BH_FDR_pass"] = bool(k)

    stale = sorted({r["data_end"] for r in recs})
    summary = {
        "generated_utc": pd.Timestamp.utcnow().isoformat(),
        "data_dir": a.data_dir,
        "n_symbols": len(recs),
        "data_end_dates": stale,
        "fees": FEES,
        "horizon_h": LABEL_H,
        "threshold": THRESHOLD,
    }
    print("\n=== RINGKASAN ===")
    if stale:
        print(f"  Tanggal akhir data: {stale}")
    if recs:
        n_fdr = sum(1 for r in recs if r.get("BH_FDR_pass"))
        n_netpos = sum(1 for r in recs if r.get("F4_positive"))
        n_sel_lt_unsel = sum(1 for r in recs
                             if r.get("F1_acc_as_reported") and r.get("F1_acc_unselected")
                             and r["F1_acc_as_reported"] > r["F1_acc_unselected"])
        print(f"  Lolos BH-FDR (pada n efektif): {n_fdr}/{len(recs)}")
        print(f"  P&L bersih > 0               : {n_netpos}/{len(recs)}")
        print(f"  Akurasi dilaporkan > jujur   : {n_sel_lt_unsel}/{len(recs)}   (bukti F1 seleksi)")
        print(f"  n_oos rata2={np.mean([r['F2_n_oos'] for r in recs]):.0f} "
              f"-> n_eff rata2={np.mean([r['F2_n_effective'] for r in recs]):.1f}")
    print(f"  Waktu: {time.time()-t0:.1f}s")

    if a.out:
        with open(a.out, "w") as fh:
            json.dump({"summary": summary, "symbols": recs}, fh, indent=1)
        print(f"  Ditulis: {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
