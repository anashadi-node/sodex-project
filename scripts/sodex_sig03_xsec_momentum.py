#!/usr/bin/env python3
"""PRAREG-SIG-03 — Cross-sectional momentum 1-7 hari (Binance USDⓈ-M).

Dibekukan di docs/sodex/PRAREG_SIG_03_2026-10-23.md (sha256 6139fee7...).
L=7, H=7, universe top-50 qav30, dollar-neutral kuintil, taker 10 bps RT/leg.
Tidak ada grid search. Output JSON ke stdout.
"""
import glob
import json
import math
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "binance_klines", "1d")
L, H = 7, 7
TOP_Q, BOT_Q = 0.8, 0.2
MAX_UNIVERSE = 50
COST_BPS_RT = 10.0
OOS_START = "2024-01-01"
OOS_END = "2026-10-07"
SEED = 42


def load_panels():
    closes, qavs = {}, {}
    for f in sorted(glob.glob(os.path.join(DATA, "*.json"))):
        sym = os.path.basename(f).replace(".json", "")
        try:
            d = json.load(open(f))
            bars = d.get("bars") or []
        except Exception:
            continue
        if len(bars) < 90:
            continue
        idx = pd.to_datetime([b[0] for b in bars], unit="ms", utc=True).normalize()
        c = pd.Series([float(b[4]) for b in bars], index=idx)
        q = pd.Series([float(b[7]) for b in bars], index=idx)
        s = ~idx.duplicated(keep="last")
        closes[sym], qavs[sym] = c[s], q[s]
    return pd.DataFrame(closes).sort_index(), pd.DataFrame(qavs).sort_index()


def build_weights(close, qav, signal_shift=0):
    """Return DataFrame bobot harian (long +0.5, short -0.5) tanpa lookahead."""
    sig = close / close.shift(L) - 1.0
    if signal_shift:
        sig = sig.shift(signal_shift)
    liq = qav.rolling(30, min_periods=20).median()
    hist = close.notna().cumsum()
    ok = sig.notna() & close.notna() & hist.ge(60) & liq.notna()
    liq_rank = liq.where(ok).rank(axis=1, ascending=False, method="first")
    univ = ok & liq_rank.le(MAX_UNIVERSE)
    r = sig.where(univ).rank(axis=1, pct=True)
    n = univ.sum(axis=1)
    valid = (n >= 20).reindex(univ.index).fillna(False)
    univ = univ.mul(valid, axis=0)
    long_w = (r.gt(TOP_Q) & univ)
    short_w = (r.le(BOT_Q) & univ)
    nl, ns = long_w.sum(axis=1), short_w.sum(axis=1)
    w = long_w.div(nl.replace(0, np.nan), axis=0) * 0.5
    w = w.sub(short_w.div(ns.replace(0, np.nan), axis=0) * 0.5)
    return w.fillna(0.0)


def strat_returns(w, close, w_prev_lag=None):
    rets = close.pct_change(fill_method=None)
    gross = (w.shift(1) * rets).sum(axis=1)  # bobot t -> return t+1
    if w_prev_lag is None:
        turn = (w - w.shift(1)).abs().sum(axis=1)
    else:
        turn = (w - w.shift(L)).abs().sum(axis=1)
    cost = turn * (COST_BPS_RT / 1e4)
    return gross, cost, gross - cost


def hac_t(x, lag=7):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 10:
        return float("nan")
    mu = x.mean()
    e = x - mu
    g0 = (e @ e) / n
    s = g0
    for k in range(1, lag + 1):
        gk = (e[k:] @ e[:-k]) / n
        s += 2 * (1 - k / (lag + 1)) * gk
    se = math.sqrt(max(s, 0) / n)
    return float(mu / se) if se > 0 else float("nan")


def block_bootstrap_ci(x, n_boot=10000, block=28, seed=SEED):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    rng = np.random.default_rng(seed)
    nblocks = int(math.ceil(n / block))
    means = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.integers(0, n, nblocks)
        idx = np.concatenate([(np.arange(st, st + block) % n) for st in starts])[:n]
        means[i] = x[idx].mean()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def main():
    close, qav = load_panels()
    w = build_weights(close, qav)
    gross, cost, net = strat_returns(w, close, w_prev_lag=True)

    # holding H=7 via tranching 1/7 per hari
    gross_h = gross.rolling(H).mean()
    cost_h = (w - w.shift(L)).abs().sum(axis=1) * (COST_BPS_RT / 1e4) / H
    net_h = gross_h - cost_h

    mask = (net_h.index >= pd.Timestamp(OOS_START, tz="UTC")) & (
        net_h.index <= pd.Timestamp(OOS_END, tz="UTC")
    )
    oos = net_h[mask].dropna()
    oos_gross = gross_h[mask].reindex(oos.index)
    oos_cost = cost_h.reindex(oos.index).fillna(0.0)

    res = {
        "prereg": "SIG-03",
        "data_cutoff": str(close.index.max().date()),
        "symbols_loaded": int(close.shape[1]),
        "dates": int(close.shape[0]),
        "oos_days": int(len(oos)),
        "oos_start": str(oos.index.min().date()) if len(oos) else None,
        "oos_end": str(oos.index.max().date()) if len(oos) else None,
    }

    mean_bps = float(oos.mean() * 1e4)
    res["K1_mean_net_bps_day"] = round(mean_bps, 3)
    res["K1_mean_gross_bps_day"] = round(float(oos_gross.mean() * 1e4), 3)
    res["K1_mean_cost_bps_day"] = round(float(oos_cost.mean() * 1e4), 3)
    res["K2_t_hac7"] = round(hac_t(oos.values), 3)
    lo, hi = block_bootstrap_ci(oos.values)
    res["K3_ci95_bps_day"] = [round(lo * 1e4, 3), round(hi * 1e4, 3)]

    # K4 kontrol acak: permutasi peringkat per tanggal
    rng = np.random.default_rng(SEED)
    rnd_means = []
    sig = (close / close.shift(L) - 1.0)
    liq = qav.rolling(30, min_periods=20).median()
    univ = sig.notna() & liq.notna()
    rnd_close = close  # dipakai ulang untuk return
    rets = close.pct_change(fill_method=None)
    for _ in range(200):
        rr = pd.DataFrame(
            rng.random(univ.shape), index=univ.index, columns=univ.columns
        ).where(univ)
        rk = rr.rank(axis=1, pct=True)
        lw = (rk.gt(TOP_Q)).div((rk.gt(TOP_Q)).sum(axis=1).replace(0, np.nan), axis=0) * 0.5
        sw = (rk.le(BOT_Q)).div((rk.le(BOT_Q)).sum(axis=1).replace(0, np.nan), axis=0) * 0.5
        ww = (lw.fillna(0) - sw.fillna(0))
        g = (ww.shift(1) * rets).sum(axis=1).rolling(H).mean()
        rnd_means.append(float(g[mask].dropna().mean() * 1e4))
    rnd = np.array(rnd_means)
    res["K4_random_p95_bps_day"] = round(float(np.percentile(rnd, 95)), 3)
    res["K4_random_mean_bps_day"] = round(float(rnd.mean()), 3)

    # K5 benchmark long-only universe sama
    u_prev = univ.shift(1).astype(float).fillna(0.0)
    bench = (rets * u_prev).sum(axis=1) / u_prev.sum(axis=1).replace(0, np.nan)
    bench = bench.astype(float)
    bench_oos = bench[mask].reindex(oos.index).astype(float).fillna(0.0)
    ok5 = ~(np.isnan(oos.values) | np.isnan(bench_oos.values))
    b = np.cov(oos.values[ok5], bench_oos.values[ok5])[0, 1] / np.var(bench_oos.values[ok5])
    alpha_d = float(oos.mean() - b * bench_oos.mean())
    res["K5_bench_mean_bps_day"] = round(float(bench_oos.mean() * 1e4), 3)
    res["K5_beta"] = round(float(b), 3)
    res["K5_alpha_bps_day"] = round(alpha_d * 1e4, 3)

    # K6 kontrol delay (lag +1) dan sensitivitas lookahead
    w_lag = build_weights(close, qav, signal_shift=1)
    g_lag = (w_lag.shift(1) * rets).sum(axis=1).rolling(H).mean()
    res["K6_delay1_mean_bps_day"] = round(float(g_lag[mask].dropna().mean() * 1e4), 3)
    res["K6_delay1_t_hac7"] = round(hac_t(g_lag[mask].dropna().values), 3)

    # K7 konsistensi tahunan
    yr = {}
    for y in (2024, 2025, 2026):
        s = oos[oos.index.year == y]
        yr[str(y)] = round(float(s.mean() * 1e4), 3) if len(s) else None
    res["K7_year_bps_day"] = yr

    k1 = mean_bps > 0 and mean_bps >= 9.57
    k2 = res["K2_t_hac7"] >= 2.5
    k3 = lo > 0
    k4 = mean_bps > res["K4_random_p95_bps_day"]
    k5 = alpha_d > 0
    k7 = sum(1 for v in yr.values() if v and v > 0) >= 2
    res["pass"] = {"K1": k1, "K2": k2, "K3": k3, "K4": k4, "K5": k5, "K7": k7}
    res["verdict"] = "LULUS" if all(res["pass"].values()) else "DITOLAK"

    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
