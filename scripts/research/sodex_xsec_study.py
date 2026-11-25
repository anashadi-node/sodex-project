#!/usr/bin/env python3
"""SoDEX XSEC — Studi edge LINTAS-SEKSI pada universe 99 simbol SoDEX.

Konteks (07-Okt-2026, Divisi Riset):
  Sensus D14 menemukan 0 mesin lulus dari 21. TOC: constraint bukan "ide",
  melainkan POWER (n_window 15-32) + biaya. Mesin berbasis trade-diskrit
  mengumpulkan sedikit window. Portofolio lintas-seksi SELALU di pasar ->
  ~365 window/tahun pada 1d, ~8.760 pada 1h.

Metode:
  - Panel harga (tanggal/jam x simbol) dari data/sodex_klines/{1d,1h}.
  - Sinyal: return masa lalu L periode (mode 'rev' = dibalik, 'mom' = searah),
    diringkas ke skor peringkat lintas-seksi (robust terhadap outlier).
  - Bobot: dollar-neutral (sum w = 0), skala sum|w| = 1 (tiap sisi 0,5).
  - Return portofolio: market-neutral -> fwd return juga di-demean lintas-seksi.
  - Biaya: turnover x fee satu-arah. Default 4 bps = taker SoDEX; uji 1x dan 2x.
  - Kontrol negatif: sinyal diacak (seed tetap) -> konstruksi identik.

Status: EKSPLORASI (pembentuk hipotesis). Angka di sini BUKAN bukti alpha
sampai pra-registrasi dibekukan dan dijalankan sekali (payung D14 / PERINTAH_1).
"""
from __future__ import annotations

import glob
import json
import math
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

ROOT = os.path.expanduser("~/anantara-sakti")
KLINE = os.path.join(ROOT, "data", "sodex_klines")
FEE_ONEWAY = 0.0004          # taker SoDEX 4 bps per sisi
MIN_NAMES = 20               # minimum simbol per lintas-seksi agar IC bermakna


def load_panel(interval: str) -> pd.DataFrame:
    """Panel harga close (index waktu UTC, kolom simbol)."""
    cols = {}
    for f in sorted(glob.glob(os.path.join(KLINE, interval, "*.json"))):
        sym = os.path.basename(f)[:-5]
        if sym == "MANIFEST":
            continue
        try:
            d = json.load(open(f))
        except Exception:
            continue
        bars = d.get("bars") or []
        if len(bars) < 60:
            continue
        idx = [datetime.fromtimestamp(b["t"] / 1000, tz=timezone.utc) for b in bars]
        cols[sym] = pd.Series([float(b["c"]) for b in bars], index=idx)
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols).sort_index()


def newey_west_t(x: np.ndarray, lag: int) -> float:
    """t-statistik Newey-West (HAC) untuk mean(x)."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = x.size
    if n < 8:
        return float("nan")
    mu = x.mean()
    d = x - mu
    g0 = float(d @ d) / n
    s = g0
    for k in range(1, min(lag, n - 1) + 1):
        gk = float(d[k:] @ d[:-k]) / n
        s += 2.0 * (1.0 - k / (lag + 1.0)) * gk
    if s <= 0:
        return float("nan")
    return mu / math.sqrt(s / n)


def rank_score(sig: pd.Series) -> pd.Series:
    """Peringkat lintas-seksi -> skor terpusat di nol, skala unit (robust)."""
    r = sig.rank()
    r = r - r.mean()
    s = r.abs().sum()
    return r / s if s > 0 else r * 0.0


def backtest(panel: pd.DataFrame, lookback: int, hold: int, mode: str,
             fee_mult: float = 1.0, control: bool = False, seed: int = 7,
             precomputed_sig: pd.DataFrame | None = None) -> dict:
    """Uji satu konfigurasi. Rebalance tiap `hold` periode, hold `hold` periode."""
    px = panel
    ret = px.pct_change()
    if precomputed_sig is not None:
        sig_raw = precomputed_sig
    else:
        sig_raw = -px.pct_change(lookback) if mode == "rev" else px.pct_change(lookback)
    if control:
        rng = np.random.default_rng(seed)
        vals = sig_raw.to_numpy(copy=True)
        flat = ~np.isnan(vals)
        # acak HANYA di dalam tiap baris (menjaga struktur ketersediaan)
        for i in range(vals.shape[0]):
            m = flat[i]
            k = int(m.sum())
            if k > 1:
                v = vals[i, m].copy()
                rng.shuffle(v)
                vals[i, m] = v
        sig_raw = pd.DataFrame(vals, index=sig_raw.index, columns=sig_raw.columns)

    idx = panel.index
    rows = []
    prev_w: pd.Series | None = None
    for i in range(lookback, len(idx) - hold, hold):
        t = idx[i]
        sig = sig_raw.loc[t].dropna()
        if sig.size < MIN_NAMES:
            continue
        fwd = ret.iloc[i + 1:i + 1 + hold].sum(skipna=False)
        fwd = fwd.reindex(sig.index)
        ok = fwd.notna() & sig.notna()
        sig, fwd = sig[ok], fwd[ok]
        if sig.size < MIN_NAMES:
            continue
        # market-neutral: buang komponen pasar dari return forward
        excess = fwd - fwd.mean()
        w = rank_score(sig)
        gross = float((w * excess).sum())
        if prev_w is None:
            turnover = float(w.abs().sum())
        else:
            allk = w.index.union(prev_w.index)
            turnover = float((w.reindex(allk, fill_value=0.0)
                              - prev_w.reindex(allk, fill_value=0.0)).abs().sum())
        net = gross - turnover * FEE_ONEWAY * fee_mult
        rows.append({"t": t, "gross": gross, "net": net, "turnover": turnover,
                     "n_names": int(sig.size)})
        prev_w = w

    if not rows:
        return {"n": 0}
    df = pd.DataFrame(rows)
    per_period = df["net"].to_numpy()
    ann = 365.0 * 24.0 / max(1, hold) if "H" not in str(hold) else 365.0
    sd = float(per_period.std(ddof=1))
    mean = float(per_period.mean())
    return {
        "n": len(df),
        "names_med": int(df["n_names"].median()),
        "gross_bps": float(df["gross"].mean() * 1e4),
        "net_bps": mean * 1e4,
        "sd_bps": sd * 1e4,
        "turnover": float(df["turnover"].mean()),
        "fee_bps": float(df["turnover"].mean() * FEE_ONEWAY * fee_mult * 1e4),
        "sharpe_per": mean / sd if sd > 0 else float("nan"),
        "t_nw": newey_west_t(per_period, lag=max(1, int(hold))),
        "winrate": float((per_period > 0).mean()),
        "total_pct": float((1 + pd.Series(per_period)).prod() - 1) * 100,
    }


def report(interval: str, hold: int, lookbacks=(1, 2, 3, 5, 10), modes=("rev", "mom")):
    panel = load_panel(interval)
    if panel.empty:
        print(f"[{interval}] panel kosong — data belum ada")
        return
    t0, t1 = panel.index[0].date(), panel.index[-1].date()
    span_days = (panel.index[-1] - panel.index[0]).total_seconds() / 86400
    print(f"\n{'='*100}\n[{interval}] panel: {panel.shape[1]} simbol x {len(panel)} bar "
          f"| {t0} -> {t1} ({span_days:.0f} hari)")
    print(f"{'mode':5}{'L':>4}{'H':>4}{'n':>6}{'nm':>4}{'gross_bps':>11}{'net1x':>9}{'net2x':>9}"
          f"{'fee1x':>8}{'sd_bps':>9}{'Sh/period':>10}{'t_NW':>8}{'WR%':>7}{'total%':>10}")
    out = []
    for mode in modes:
        for L in lookbacks:
            r1 = backtest(panel, L, hold, mode, fee_mult=1.0)
            if not r1.get("n"):
                continue
            r2 = backtest(panel, L, hold, mode, fee_mult=2.0)
            ctrl = backtest(panel, L, hold, mode, fee_mult=1.0, control=True)
            print(f"{mode:5}{L:>4}{hold:>4}{r1['n']:>6}{r1['names_med']:>4}"
                  f"{r1['gross_bps']:>11.2f}{r1['net_bps']:>9.2f}{r2['net_bps']:>9.2f}"
                  f"{r1['fee_bps']:>8.2f}{r1['sd_bps']:>9.1f}{r1['sharpe_per']:>10.3f}"
                  f"{r1['t_nw']:>8.2f}{r1['winrate']*100:>7.1f}{r1['total_pct']:>10.1f}")
            out.append({"interval": interval, "mode": mode, "L": L, "H": hold,
                        "net1x": r1, "net2x": r2, "ctrl": ctrl})
    # blok kontrol
    print("  -- kontrol negatif (sinyal diacak, konstruksi identik) --")
    for o in out:
        c = o["ctrl"]
        if c.get("n"):
            print(f"     {o['mode']} L={o['L']:<3} ctrl gross={c['gross_bps']:>7.2f}bps "
                  f"net={c['net_bps']:>7.2f}bps t_NW={c['t_nw']:>6.2f} Sh={c['sharpe_per']:>6.3f}")
    return out


if __name__ == "__main__":
    import sys
    itv = sys.argv[1] if len(sys.argv) > 1 else "1d"
    hold = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    res = report(itv, hold)
    if res:
        print(f"\n[jumlah konfigurasi diuji: {len(res)}]")
