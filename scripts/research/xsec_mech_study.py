#!/usr/bin/env python3
"""PRAREG_PANEL_PANJANG — 12 mekanisme lintas-seksi x 2 hold (24 trial), BH-FDR.

Protokol dibekukan: docs/sodex/PRAREG_PANEL_PANJANG_2026-10-07.md
JANGAN ubah ambang sebelum membaca dokumen itu. Setiap trial dilaporkan,
lulus maupun gagal.

Jalankan:
  /usr/bin/python3 scripts/research/xsec_mech_study.py binance 1d 2,5
  /usr/bin/python3 scripts/research/xsec_mech_study.py sodex 1d 2,5
"""
from __future__ import annotations

import glob
import json
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

ROOT = os.path.expanduser("~/anantara-sakti")
FEE_ONEWAY = 0.0004          # SoDEX taker 4 bps/sisi (Binance fapi 5 bps -> dilaporkan juga)
FEE_ONEWAY_BN = 0.0005
MIN_NAMES = 20
Q_FDR = 0.10
SHARPE_MIN = 2.3
SEG_MIN = 30

# Annualisasi WAJIB ikut durasi BAR: loop backtest melangkah `hold` BAR, bukan hari.
# 1d -> 365 periode/tahun, 1h -> 8760 periode/tahun.
# BUG lama (per_year = 365/hold) men-understate panel 1h sebesar sqrt(24)=4,90x.
PPY = 365.0
BAR_HOURS = {"1d": 24.0, "1h": 1.0}

# nama mekanisme -> (fungsi pembentuk sinyal dari fitur, tanda)
MECH_ORDER = ["REV_L1", "REV_L3", "REV_VOL", "REV_IDIO", "MOM_L21", "MOM_L63",
              "LTREV_L180", "RANGEPOS", "VOLSHOCK", "MAXFX", "CARRY_FR", "BASIS"]


# ─────────────────────────── panel ───────────────────────────
def _sodex_panel(interval: str) -> pd.DataFrame:
    cols = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "sodex_klines", interval, "*.json"))):
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
        idx = pd.to_datetime([b["t"] for b in bars], unit="ms", utc=True).normalize() \
            if interval == "1d" else pd.to_datetime([b["t"] for b in bars], unit="ms", utc=True)
        cols[sym] = pd.Series([float(b["c"]) for b in bars], index=idx)
    return pd.DataFrame(cols).sort_index()


def _binance_panel(interval: str) -> pd.DataFrame:
    cols = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "binance_klines", interval, "*.json"))):
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
        idx = pd.to_datetime([int(b[0]) for b in bars], unit="ms", utc=True)
        if interval == "1d":
            idx = idx.normalize()
        cols[sym] = pd.Series([float(b[4]) for b in bars], index=idx)
    return pd.DataFrame(cols).sort_index()


def load_funding(syms) -> pd.DataFrame:
    """Funding harian (jumlah 3 settlement) dari data/binance_funding/."""
    cols = {}
    for s in syms:
        p = os.path.join(ROOT, "data", "binance_funding", f"{s}.json")
        if not os.path.exists(p):
            continue
        try:
            rows = json.load(open(p))
        except Exception:
            continue
        if not rows:
            continue
        idx = pd.to_datetime([int(r["fundingTime"]) for r in rows], unit="ms", utc=True).normalize()
        col = pd.Series([float(r["fundingRate"]) for r in rows], index=idx)
        cols[s] = col.groupby(level=0).sum()
    return pd.DataFrame(cols).sort_index() if cols else pd.DataFrame()


def load_basis(syms) -> pd.DataFrame:
    """Premium indeks harian (close premiumIndexKlines) dari data/binance_basis/1d/."""
    cols = {}
    for s in syms:
        p = os.path.join(ROOT, "data", "binance_basis", "1d", f"{s}.json")
        if not os.path.exists(p):
            continue
        try:
            rows = json.load(open(p))
        except Exception:
            continue
        if not rows:
            continue
        idx = pd.to_datetime([int(r[0]) for r in rows], unit="ms", utc=True).normalize()
        cols[s] = pd.Series([float(r[4]) for r in rows], index=idx)
    return pd.DataFrame(cols).sort_index() if cols else pd.DataFrame()


# ─────────────────────────── sinyal ───────────────────────────
def build_signals(px: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    ret = px.pct_change()
    mkt = ret.mean(axis=1)
    vol20 = ret.rolling(20).std()
    hi20, lo20 = px.rolling(20).max(), px.rolling(20).min()
    sigs: dict[str, pd.DataFrame] = {}
    sigs["REV_L1"] = -ret
    sigs["REV_L3"] = -px.pct_change(3)
    sigs["REV_VOL"] = -(ret / vol20.replace(0, np.nan))
    var_m = mkt.rolling(60).var()
    cov = ret.rolling(60).cov(mkt)
    beta = cov.div(var_m, axis=0)
    sigs["REV_IDIO"] = -(ret - beta.mul(mkt, axis=0))
    sigs["MOM_L21"] = px.pct_change(21)
    sigs["MOM_L63"] = px.pct_change(63)
    sigs["LTREV_L180"] = -px.pct_change(180)
    rng = (hi20 - lo20).replace(0, np.nan)
    sigs["RANGEPOS"] = -((px - lo20) / rng)
    return sigs, ret


def add_vol_shock(sigs: dict, px: pd.DataFrame, vol: pd.DataFrame):
    if vol.empty:
        return
    vr = vol / vol.rolling(20).mean()
    z = (vr - vr.rolling(20).mean()) / vr.rolling(20).std()
    sigs["VOLSHOCK"] = -np.sign(px.pct_change()).mul(z)


def add_maxfx(sigs: dict, px: pd.DataFrame):
    ret = px.pct_change()
    top5 = ret.rolling(20).apply(lambda x: np.mean(np.sort(x)[-5:]) if np.isfinite(x).all() else np.nan,
                                 raw=True)
    sigs["MAXFX"] = -top5


# ─────────────────────────── statistik ───────────────────────────
HARNESS_VERSION = "v2-2026-10-25-nwlag"


def safe_lag(hold: int, n: int) -> int:
    """Bandwidth Newey-West yang SAH: lag <= n//4.

    FIX 2026-10-25: sebelumnya run_mech memakai lag=hold dan nw_t meng-clamp ke n-1,
    sehingga untuk hold=72 dengan n=44 bandwidth ~= n -> estimasi varian bias turun
    dan t INFLASI (tervalidasi: RANGEPOS_H72 t=5,42 dengan lag=hold vs t=1,61 dengan
    lag=1; CI95 bootstrap memuat 0). Dengan lag <= n//4, sampel harus >= 4*lag.
    """
    if n < 8:
        return 1
    return max(1, min(int(hold), int(n) // 4))


def nw_t(x: np.ndarray, lag: int) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = x.size
    if n < 8:
        return float("nan")
    mu = x.mean()
    d = x - mu
    s = float(d @ d) / n
    for k in range(1, min(lag, n - 1) + 1):
        s += 2.0 * (1.0 - k / (lag + 1.0)) * float(d[k:] @ d[:-k]) / n
    if s <= 0:
        return float("nan")
    return mu / math.sqrt(s / n)


def two_sided_p(t: float) -> float:
    if not np.isfinite(t):
        return float("nan")
    return math.erfc(abs(t) / math.sqrt(2.0))


def rank_w(sig: pd.Series) -> pd.Series:
    r = sig.rank() - sig.rank().mean()
    s = r.abs().sum()
    return r / s if s > 0 else r * 0.0


def spearman_ic(sig: pd.Series, fwd: pd.Series) -> float:
    if sig.size < 5:
        return float("nan")
    return float(sig.rank().corr(fwd.rank()))


# ─────────────────────────── backtest ───────────────────────────
def run_mech(px: pd.DataFrame, ret: pd.DataFrame, sig_raw: pd.DataFrame, hold: int,
             fee_oneway: float, fee_mult: float = 1.0,
             control: bool = False, seed: int = 20261007) -> dict:
    if control:
        rng = np.random.default_rng(seed)
        vals = sig_raw.to_numpy(copy=True)
        mask = np.isfinite(vals)
        for i in range(vals.shape[0]):
            m = mask[i]
            k = int(m.sum())
            if k > 1:
                v = vals[i, m].copy()
                rng.shuffle(v)
                vals[i, m] = v
        sig_raw = pd.DataFrame(vals, index=sig_raw.index, columns=sig_raw.columns)

    need = max(hold, 1)
    idx = px.index
    recs = []
    prev_w = None
    for i in range(0, len(idx) - need, hold):
        sig = sig_raw.iloc[i].dropna()
        if sig.size < MIN_NAMES:
            continue
        fwd = ret.iloc[i + 1:i + 1 + hold].sum(skipna=False).reindex(sig.index)
        ok = fwd.notna() & sig.notna()
        sig, fwd = sig[ok], fwd[ok]
        if sig.size < MIN_NAMES:
            continue
        excess = fwd - fwd.mean()                      # market-neutral
        w = rank_w(sig)
        gross = float((w * excess).sum())
        if prev_w is None:
            to = float(w.abs().sum())
        else:
            allk = w.index.union(prev_w.index)
            to = float((w.reindex(allk, fill_value=0.0)
                        - prev_w.reindex(allk, fill_value=0.0)).abs().sum())
        recs.append({"t": idx[i], "gross": gross,
                     "net": gross - to * fee_oneway * fee_mult,
                     "to": to, "n": int(sig.size),
                     "ic": spearman_ic(sig, excess)})
        prev_w = w

    if not recs:
        return {"n": 0}
    df = pd.DataFrame(recs)
    net = df["net"].to_numpy()
    sd = float(net.std(ddof=1)) if len(net) > 2 else float("nan")
    mean = float(net.mean())
    per_year = PPY / hold
    sharpe = (mean / sd) * math.sqrt(per_year) if sd and sd > 0 else float("nan")
    lag = safe_lag(hold, len(net))     # FIX 2026-10-25: lag=hold -> t inflasi saat n kecil
    t = nw_t(net, lag=lag)
    p = two_sided_p(t)
    # 3 segmen waktu
    seg = [float(g["net"].mean()) for _, g in df.groupby(np.arange(len(df)) * 3 // len(df))] \
        if len(df) >= 3 * SEG_MIN else []
    return {
        "n": len(df),
        "names_med": int(df["n"].median()),
        "mean_bps_per_period": mean * 1e4,
        "sd_bps_per_period": sd * 1e4,
        "sharpe_annual": sharpe,
        "t_nw": t, "p": p,
        "t_lag": int(lag),
        "segments_untested": bool(len(df) < 3 * SEG_MIN),
        "harness": HARNESS_VERSION,
        "ic_mean": float(df["ic"].mean()),
        "turnover": float(df["to"].mean()),
        "fee_bps": float(df["to"].mean() * fee_oneway * fee_mult * 1e4),
        "winrate": float((net > 0).mean()),
        "total_pct": float((1 + pd.Series(net)).prod() - 1) * 100,
        "segments": [float(x * 1e4) for x in seg],
        "segments_positive": int(sum(1 for x in seg if x > 0)) if seg else None,
    }


def bh_fdr(pvals: dict[str, float], q: float = Q_FDR) -> dict[str, bool]:
    items = [(k, v) for k, v in pvals.items() if np.isfinite(v)]
    items.sort(key=lambda kv: kv[1])
    m = len(items)
    out = {k: False for k in pvals}
    kmax = 0
    for i, (_, p) in enumerate(items, 1):
        if p <= i / m * q:
            kmax = i
    for i, (k, _) in enumerate(items, 1):
        out[k] = i <= kmax
    return out


# ─────────────────────────── main ───────────────────────────
def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else "binance"
    interval = sys.argv[2] if len(sys.argv) > 2 else "1d"
    holds = [int(x) for x in (sys.argv[3] if len(sys.argv) > 3 else "2,5").split(",")]
    global PPY
    PPY = 365.0 * 24.0 / BAR_HOURS.get(interval, 24.0)

    if src == "binance":
        px = _binance_panel(interval)
        fee = FEE_ONEWAY_BN
        vol = pd.DataFrame()
        for f in sorted(glob.glob(os.path.join(ROOT, "data", "binance_klines", interval, "*.json"))):
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
            idx = pd.to_datetime([int(b[0]) for b in bars], unit="ms", utc=True)
            if interval == "1d":
                idx = idx.normalize()
            vol[sym] = pd.Series([float(b[5]) for b in bars], index=idx)
        vol = vol.sort_index()
    else:
        px = _sodex_panel(interval)
        fee = FEE_ONEWAY
        vol = pd.DataFrame()

    if px.empty:
        print(f"panel {src}/{interval} kosong")
        return 1
    print(f"[{src}/{interval}] panel {px.shape[1]} simbol x {len(px)} bar "
          f"| {px.index[0].date()} -> {px.index[-1].date()}", flush=True)

    sigs, ret = build_signals(px)
    add_vol_shock(sigs, px, vol)
    add_maxfx(sigs, px)

    fund = load_funding(list(px.columns)) if src == "binance" else pd.DataFrame()
    if not fund.empty:
        sigs["CARRY_FR"] = -fund.reindex(px.index).reindex(columns=px.columns)
    bas = load_basis(list(px.columns)) if src == "binance" else pd.DataFrame()
    if not bas.empty:
        sigs["BASIS"] = -bas.reindex(px.index).reindex(columns=px.columns)

    trials, pvals, results = [], {}, {}
    for mech in MECH_ORDER:
        if mech not in sigs:
            print(f"  {mech:11} DATA-TIDAK-ADA (dilewati, dicatat)")
            results[mech] = {"skip": True}
            continue
        for h in holds:
            key = f"{mech}_H{h}"
            r1 = run_mech(px, ret, sigs[mech], h, fee, 1.0)
            if not r1.get("n"):
                results[key] = {"skip": True}
                continue
            r2 = run_mech(px, ret, sigs[mech], h, fee, 2.0)
            # sensitivitas realistis: fee 4 bps + slippage 0,86 bps (setengah spread
            # median SoDEX 1,71 bp, AUDIT_BIAYA_AKUN_2026-10-05) = 4,86 bps/sisi
            rslip = run_mech(px, ret, sigs[mech], h, fee, 1.215)
            ctrl = run_mech(px, ret, sigs[mech], h, fee, 1.0, control=True)
            results[key] = {"mech": mech, "hold": h, "fee1x": r1, "fee2x": r2,
                            "fee_slip": rslip, "ctrl": ctrl}
            trials.append(key)
            pvals[key] = r1["p"]

    print(f"\n[trial dijalankan: {len(trials)} dari {len(MECH_ORDER)*len(holds)} prarreg]")
    bh = bh_fdr(pvals)
    print(f"\n{'trial':16}{'n':>5}{'nm':>4}{'net_bps':>9}{'sd_bps':>8}{'S_ann':>7}"
          f"{'t_NW':>7}{'p':>8}{'BH':>4}{'seg+':>6}{'ctrl_t':>8}{'ic':>8}{'S_slip':>7}{'pass':>6}")
    n_pass = 0
    for key in trials:
        r = results[key]
        r1, c = r["fee1x"], r["ctrl"]
        ok = (r1["sharpe_annual"] >= SHARPE_MIN and r["fee2x"]["sharpe_annual"] >= 1.8
              and bh.get(key, False) and (r1["segments_positive"] or 0) >= 3
              and abs(c.get("t_nw", 9)) < 2.0)
        r["pass"] = bool(ok)
        n_pass += int(ok)
        print(f"{key:16}{r1['n']:>5}{r1['names_med']:>4}{r1['mean_bps_per_period']:>9.2f}"
              f"{r1['sd_bps_per_period']:>8.0f}{r1['sharpe_annual']:>7.2f}{r1['t_nw']:>7.2f}"
              f"{r1['p']:>8.3f}{str(bh.get(key))[:1]:>4}{str(r1['segments_positive']):>6}"
              f"{c.get('t_nw', float('nan')):>8.2f}{r1['ic_mean']:>8.4f}"
              f"{r['fee_slip']['sharpe_annual']:>7.2f}{str(bool(ok))[:5]:>6}")

    outdir = os.path.join(ROOT, "reports", "sodex")
    os.makedirs(outdir, exist_ok=True)
    out = {"source": src, "interval": interval, "generated_utc": datetime.now(timezone.utc).isoformat(),
           "protocol": "docs/sodex/PRAREG_PANEL_PANJANG_2026-10-07.md",
           "family_declared": len(MECH_ORDER) * len(holds), "family_run": len(trials),
           "n_pass": n_pass, "fee_oneway": fee, "results": results,
           "bh_pass": bh, "pvals": pvals}
    path = os.path.join(outdir, f"PRAREG_PANEL_PANJANG_{src}_{interval}.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(f"\nverdict: {n_pass} lulus | berkas: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
