#!/usr/bin/env python3
"""Uji alternatif Top-4 pada Binance 1m (READ-ONLY). Venue uji primer per pra-registrasi §6.

Pra-registrasi: docs/sodex/SODEX_ALT_TOP4_PRAREG_2026-10-07.md (ambang BEKU, termasuk §6b).
Data: scratch/binance_bars/<SYM>_4h.parquet, <SYM>_1d.parquet (11 simbol, Okt2022-Sep2025).
IS  2022-10-01..2024-11-30 | OOS 2024-12-01..2025-09-30 (70/30).
Biaya: taker Binance 4,5 bp/leg -> round trip 9 bp; diuji juga 1,5x (13,5 bp).

Hipotesis: H1 (breakout regime-gated), H2 (order flow agresor, cross-sectional desil),
H4 (momentum 14h/7h risk-managed + gate UP->UP).

Kontrol negatif WAJIB: random-entry / random-ranking. Bila kontrol ikut lolos, uji TIDAK SAH.

READ-ONLY: hanya membaca scratch/ dan menulis laporan JSON+MD. Tidak menyentuh produksi.
Pakai: python3 scripts/binance_alt_top4_study.py [--nperm 1000]
"""
from __future__ import annotations
import argparse
import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BARS = ROOT / "scratch/binance_bars"
OUT = ROOT / "reports/sodex"

FEE_RT, FEE_STRESS = 0.0009, 1.5          # Binance taker 4,5bp/leg (konservatif vs SoDEX 4bp)
IS_END, OOS_START = "20241130", "20241201"
PASS = {"n_min": 100, "p_max": 0.05, "single_sym_share": 0.30, "q_fdr": 0.10}
TARGET_VOL, MAX_SCALE = 0.40, 1.0


def load(tag: str) -> pd.DataFrame:
    fs = sorted(glob.glob(str(BARS / f"*_{tag}.parquet")))
    if not fs:
        raise SystemExit(f"tidak ada bar di {BARS}. Jalankan scripts/binance_build_bars.py dulu.")
    parts = []
    for f in fs:
        d = pd.read_parquet(f)
        d["sym"] = Path(f).stem.rsplit("_", 1)[0]
        parts.append(d)
    b = pd.concat(parts, ignore_index=True)
    b["taker_sell_volume"] = b["volume"] - b["taker_buy_volume"]
    b["ofi"] = np.where(b["volume"] > 0, (b["taker_buy_volume"] - b["taker_sell_volume"]) / b["volume"], 0.0)
    b["dt"] = pd.to_datetime(b["ts"], unit="s", utc=True)
    b["ymd"] = b["dt"].dt.strftime("%Y%m%d")
    b["day"] = (b["ts"] // 86400).astype("int64")
    return b.sort_values(["sym", "ts"]).reset_index(drop=True)


def add_fwd(b: pd.DataFrame, h: int) -> pd.DataFrame:
    b = b.sort_values(["sym", "ts"]).copy()
    g = b.groupby("sym", sort=False)
    b["entry"] = g["open"].shift(-1)
    b["exit"] = g["close"].shift(-h)
    b["fwd"] = b["exit"] / b["entry"] - 1.0
    return b


def agg_stats(net: np.ndarray) -> dict:
    if len(net) == 0:
        return {"n": 0}
    return {"n": int(len(net)), "mean_net_bp": float(net.mean() * 1e4),
            "wr": float((net > 0).mean()), "median_bp": float(np.median(net) * 1e4),
            "sum_net_bp": float(net.sum() * 1e4)}


def rand_entry_p(sel: pd.DataFrame, pool: pd.DataFrame, nperm: int, seed=7,
                 sign: int = 1, fwd_col: str = "fwd") -> float:
    """Kontrol: timing sinyal vs entry acak di (simbol, hari) yang sama.

    WAJIB sign-aware: untuk SHORT, return dibalik (sign=-1) SEBELUM dibandingkan.
    Tanpa ini, pada pasar yang naik kontrol SHORT menjadi timpang dan p-value menyesatkan.
    """
    if sel.empty:
        return float("nan")
    obs = float((sign * sel[fwd_col] - FEE_RT).mean())
    keys = sel.groupby(["sym", "day"]).size().rename("k").reset_index()
    pidx = {k: (sign * v[fwd_col].to_numpy() - FEE_RT) for k, v in pool.groupby(["sym", "day"])}
    valid = [(r.sym, r.day, int(r.k)) for r in keys.itertuples()
             if (r.sym, r.day) in pidx and len(pidx[(r.sym, r.day)])]
    if not valid:
        return float("nan")
    rng = np.random.default_rng(seed)
    cnt = 0
    for _ in range(nperm):
        tot = nn = 0
        for s, d, k in valid:
            arr = pidx[(s, d)]
            pick = rng.choice(arr, size=min(k, len(arr)), replace=False)
            tot += pick.sum()
            nn += len(pick)
        if nn and tot / nn >= obs:
            cnt += 1
    return (cnt + 1) / (nperm + 1)


def rand_rank_p(sel: pd.DataFrame, pool: pd.DataFrame, nperm: int, seed=7,
                sign: int = 1, fwd_col: str = "fwd") -> float:
    """Kontrol #2/#4: ranking acak -- apakah URUTAN cross-sectional membawa informasi?"""
    if sel.empty:
        return float("nan")
    obs = float((sign * sel[fwd_col] - FEE_RT).mean())
    per_day = {d: (sign * v[fwd_col].to_numpy() - FEE_RT) for d, v in pool.groupby("day")}
    kk = sel.groupby("day").size().to_dict()
    rng = np.random.default_rng(seed)
    cnt = 0
    for _ in range(nperm):
        tot = nn = 0
        for d, k in kk.items():
            arr = per_day.get(d)
            if arr is None or not len(arr):
                continue
            pick = rng.choice(arr, size=min(k, len(arr)), replace=False)
            tot += pick.sum()
            nn += len(pick)
        if nn and tot / nn >= obs:
            cnt += 1
    return (cnt + 1) / (nperm + 1)


def seg_stats(sub: pd.DataFrame, tag: str, out: dict, pool: pd.DataFrame,
              nperm: int, col="net", rand="entry", fwd_col="fwd", sign=1):
    for seg in ("IS", "OOS"):
        s = sub[sub["seg"] == seg]
        out[f"{tag}_{seg}"] = agg_stats(s[col].to_numpy() if len(s) else np.array([]))
        if seg == "OOS" and len(s):
            if rand == "entry":
                p = rand_entry_p(s, pool, nperm, sign=sign, fwd_col=fwd_col)
            else:
                p = rand_rank_p(s, pool, nperm, sign=sign, fwd_col=fwd_col)
            out[f"{tag}_{seg}"]["p_random"] = p
            top = s.groupby("sym")[col].sum().sort_values(ascending=False)
            out[f"{tag}_{seg}"]["top_sym"] = top.index[0] if len(top) else None
            out[f"{tag}_{seg}"]["top_sym_share"] = (
                float(top.iloc[0] / top.sum()) if len(top) and top.sum() else None)


# ------------------------------------------------------------------ H1 breakout
def h1(b: pd.DataFrame, horizons=(1, 2, 6, 12)) -> dict:
    out = {}
    for h in horizons:
        x = add_fwd(b, h)
        g = x.groupby("sym", sort=False)
        x["hi30"] = g["high"].transform(lambda s: s.rolling(30, min_periods=10).max().shift(1))
        x["lo30"] = g["low"].transform(lambda s: s.rolling(30, min_periods=10).min().shift(1))
        x["vmed"] = g["volume"].transform(lambda s: s.rolling(30, min_periods=10).median().shift(1))
        x["relvol"] = np.where(x["vmed"] > 0, x["volume"] / x["vmed"], 0.0)
        btc = x[x["sym"] == "BTC"].set_index("ts")["close"].sort_index()
        slope = (btc / btc.shift(6) - 1.0).rename("slope6")
        x = x.merge(slope, left_on="ts", right_index=True, how="left")
        pool = x[x["fwd"].notna()]
        x["seg"] = np.where(x["ymd"] <= IS_END, "IS", "OOS")
        for name, m in (("LONG", (x["close"] > x["hi30"]) & (x["relvol"] >= 1.5) & (x["slope6"] > 0)),
                        ("SHORT", (x["close"] < x["lo30"]) & (x["relvol"] >= 1.5) & (x["slope6"] < 0))):
            s = x[m & x["fwd"].notna()].copy()
            s["net"] = (s["fwd"] - FEE_RT) if name == "LONG" else (-s["fwd"] - FEE_RT)
            s["stress"] = (s["fwd"] - FEE_RT * FEE_STRESS) if name == "LONG" else (-s["fwd"] - FEE_RT * FEE_STRESS)
            tag = f"h{h}_{name}"
            seg_stats(s, tag, out, pool, RES["nperm"], sign=(1 if name == "LONG" else -1))
            for seg in ("IS", "OOS"):
                q = s[s["seg"] == seg]
                if len(q):
                    out[f"{tag}_{seg}"]["mean_stress_bp"] = float(q["stress"].mean() * 1e4)
    return out


# ------------------------------------------------------- H2 order flow (cross-sec)
def h2(b: pd.DataFrame, horizons=(2, 3, 6)) -> dict:
    out = {}
    b = b.copy()
    b["ofi_prev"] = b.groupby("sym", sort=False)["ofi"].shift(1)
    for h in horizons:
        x = add_fwd(b, h)
        pool = x[x["fwd"].notna() & x["ofi_prev"].notna()].copy()
        if pool.empty:
            continue
        pool["seg"] = np.where(pool["ymd"] <= IS_END, "IS", "OOS")
        q = pool.groupby("ts")["ofi_prev"]
        pool["hi"] = q.transform(lambda s: s >= s.quantile(0.80))
        pool["lo"] = q.transform(lambda s: s <= s.quantile(0.20))
        for name, m in (("LONG", pool["hi"]), ("SHORT", pool["lo"])):
            s = pool[m].copy()
            s["net"] = (s["fwd"] - FEE_RT) if name == "LONG" else (-s["fwd"] - FEE_RT)
            s["signed_fwd"] = np.where(name == "LONG", s["fwd"], -s["fwd"])
            s["stress"] = (s["fwd"] - FEE_RT * FEE_STRESS) if name == "LONG" else (-s["fwd"] - FEE_RT * FEE_STRESS)
            tag = f"h{h}_{name}"
            seg_stats(s, tag, out, pool, RES["nperm"], rand="rank", sign=(1 if name == "LONG" else -1))
            for seg in ("IS", "OOS"):
                r = s[s["seg"] == seg]
                if len(r):
                    out[f"{tag}_{seg}"]["mean_stress_bp"] = float(r["stress"].mean() * 1e4)
    return out


# ------------------------------------------------- H4 momentum cross-sectional
def h4(b1d: pd.DataFrame, form=14, hold=7) -> dict:
    out = {}
    d = b1d.sort_values(["sym", "ts"]).copy()
    g = d.groupby("sym", sort=False)
    d["form_ret"] = g["close"].transform(lambda s: s / s.shift(form) - 1.0)
    d["fwd7"] = g["close"].transform(lambda s: s.shift(-hold) / s - 1.0)
    d["ret1"] = g["close"].transform(lambda s: np.log(s).diff())
    d["rv20"] = g["ret1"].transform(lambda s: s.rolling(20, min_periods=10).std() * np.sqrt(365))
    pool = d[d["form_ret"].notna() & d["fwd7"].notna()].copy()
    pool["seg"] = np.where(pool["ymd"] <= IS_END, "IS", "OOS")
    q = pool.groupby("day")["form_ret"]
    pool["hi"] = q.transform(lambda s: s >= s.quantile(0.70))
    pool["lo"] = q.transform(lambda s: s <= s.quantile(0.30))
    # gate UP->UP: form_ret hari ini >0 DAN form_ret hold-hari lalu >0
    up = (d.set_index(["sym", "ts"])["form_ret"] > 0)
    prev_up = up.groupby(level=0).shift(hold).rename("prev_up")
    pool = pool.merge(prev_up, left_on=["sym", "ts"], right_index=True, how="left")
    pool["upup"] = pool["hi"] & pool["prev_up"].fillna(False)
    pool["scale"] = np.clip(TARGET_VOL / pool["rv20"].replace(0, np.nan), 0, MAX_SCALE).fillna(1.0)
    for name, m in (("LONG", pool["hi"]), ("SHORT", pool["lo"]), ("LONG_upup", pool["upup"])):
        s = pool[m].copy()
        if name == "SHORT":
            s["net"] = -s["fwd7"] * s["scale"] - FEE_RT
        else:
            s["net"] = s["fwd7"] * s["scale"] - FEE_RT
        s["signed_fwd"] = np.where(name == "SHORT", -s["fwd7"], s["fwd7"])
        s["stress"] = s["net"] - FEE_RT * (FEE_STRESS - 1)
        seg_stats(s, f"h{hold}_{name}", out, pool, RES["nperm"], rand="rank",
                  fwd_col="fwd7", sign=(-1 if name.startswith("SHORT") else 1))
        for seg in ("IS", "OOS"):
            r = s[s["seg"] == seg]
            if len(r):
                out[f"h{hold}_{name}_{seg}"]["mean_stress_bp"] = float(r["stress"].mean() * 1e4)
    return out


def bh_fdr(pairs: list[tuple[str, float]], q=PASS["q_fdr"]) -> list[dict]:
    """Benjamini-Hochberg. Return nama -> lolos/tidak."""
    ps = [(n, p) for n, p in pairs if p == p]
    if not ps:
        return []
    ps.sort(key=lambda x: x[1])
    m = len(ps)
    out, kmax = [], 0
    for i, (n, p) in enumerate(ps, 1):
        if p <= q * i / m:
            kmax = i
    for i, (n, p) in enumerate(ps, 1):
        out.append({"name": n, "p": p, "pass_bh": i <= kmax})
    return out


def verdicts(out: dict) -> list:
    """Terapkan 5 syarat bar pass pra-registrasi §2. Tanpa ini, p-value kecil pada
    strategi yang RUGI akan salah terbaca sebagai 'lolos' (mis. SHORT yg signifikan negatif)."""
    rows = []
    for hyp in ("H1", "H2", "H4"):
        for k, v in out.get(hyp, {}).items():
            if not isinstance(v, dict) or not k.endswith("OOS") or "n" not in v or not v["n"]:
                continue
            p, net, st = v.get("p_random"), v.get("mean_net_bp"), v.get("mean_stress_bp")
            share = v.get("top_sym_share")
            c1 = v["n"] >= PASS["n_min"]
            c2 = (net or 0) > 0
            c3 = (st or 0) > 0
            c4 = p is not None and p == p and p < PASS["p_max"]
            c5 = share is not None and share == share and abs(share) <= PASS["single_sym_share"]
            rows.append({"name": k, "n": v["n"], "net_bp": net, "stress_bp": st, "p": p,
                         "top_sym": v.get("top_sym"), "top_share": share,
                         "c1_n": c1, "c2_net_pos": c2, "c3_stress": c3,
                         "c4_p": c4, "c5_conc": c5, "LAYAK": bool(all((c1, c2, c3, c4, c5)))})
    return rows


RES = {"nperm": 1000}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nperm", type=int, default=1000)
    args = ap.parse_args()
    RES["nperm"] = args.nperm
    b4, b1d = load("4h"), load("1d")
    print(f"4H: {len(b4):,} bar | 1D: {len(b1d):,} bar | simbol={b4.sym.nunique()}")
    print(f"rentang {b4.ymd.min()} .. {b4.ymd.max()} | IS<= {IS_END} | OOS>= {OOS_START}")
    out = {"meta": {"bars4h": int(len(b4)), "bars1d": int(len(b1d)),
                    "symbols": sorted(b4.sym.unique().tolist()), "nperm": args.nperm,
                    "fee_rt": FEE_RT, "is_end": IS_END, "oos_start": OOS_START, "pass": PASS}}
    out["H1"] = h1(b4)
    out["H2"] = h2(b4)
    out["H4"] = h4(b1d)
    out["VERDICT"] = verdicts(out)
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"binance_alt_top4_{pd.Timestamp.now():%Y%m%d}.json"
    dest.write_text(json.dumps(out, indent=1, default=str))
    print(f"\nhasil -> {dest}\n")
    for hyp in ("H1", "H2", "H4"):
        print(f"═══ {hyp} (OOS) ═══")
        for k in sorted(out[hyp]):
            v = out[hyp][k]
            if not isinstance(v, dict) or v.get("n") is None or not k.endswith("OOS"):
                continue
            print(f"{k:22s} n={v['n']:6d} net={v['mean_net_bp']:8.2f}bp "
                  f"stress={v.get('mean_stress_bp', float('nan')):8.2f}bp "
                  f"WR={v['wr']:.1%} p={v.get('p_random', float('nan')):.3f} "
                  f"top={v.get('top_sym')}({v.get('top_sym_share') or 0:.0%})")
    print("\n═══ VERDICT (5 syarat pra-registrasi §2) ═══")
    print(f"{'varian':24s} {'n>=100':>7s} {'net>0':>6s} {'strs>0':>7s} {'p<.05':>6s} {'|sym|<30%':>10s}  LAYAK")
    for r in out["VERDICT"]:
        print(f"{r['name']:24s} {str(r['c1_n']):>7s} {str(r['c2_net_pos']):>6s} "
              f"{str(r['c3_stress']):>7s} {str(r['c4_p']):>6s} {str(r['c5_conc']):>10s}  "
              f"{'YA' if r['LAYAK'] else 'TIDAK'}")
    n_layak = sum(1 for r in out["VERDICT"] if r["LAYAK"])
    print(f"\nTOTAL LAYAK: {n_layak} dari {len(out['VERDICT'])} varian")


if __name__ == "__main__":
    main()
