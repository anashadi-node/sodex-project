#!/usr/bin/env python3
"""SENSUS DIVERSIFIKASI SoDEX — plafon korelasi venue.

MENGAPA (Divisi Riset, 07-Okt-2026):
  Target resmi PnL 0,8%/48 jam, dicapai lewat 6-8 mesin dengan korelasi
  portofolio rho <= 0,10, dan tiap mesin Sharpe_ann >= 2,3.
  Aritmetika itu mengasumsikan rho ANTAR-MESIN kecil. Tapi mesin SoDEX
  TRADING ASET di venue yang sama. Kalau aset venue saling berkorelasi
  tinggi, maka PnL antar-mesin akan berkorelasi pula — plafon diversifikasi
  ditentukan oleh VENUE, bukan oleh keragaman ide.

Yang dihitung (read-only, panel 1d 99 simbol):
  · distribusi korelasi berpasangan (median, p75, p90)
  · blok crypto vs EQ/RWA: dalam-blok dan antar-blok
  · spektrum eigen -> N_eff = (sum L)^2 / sum L^2  (jumlah taruhan independen)
  · porsi varians PC1 (faktor pasar venue)
  · berapa mesin independen yang mungkin bila tiap mesin = 1 taruhan acak

Jalankan: /usr/bin/python3 scripts/research/sodex_diversification_census.py
"""
from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

ROOT = os.path.expanduser("~/anantara-sakti")
KL = os.path.join(ROOT, "data", "sodex_klines", "1d")
EQ_HINT = ("AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOG", "META", "SPY", "QQQ", "XAU",
           "XAUT", "PAXG", "GOLD", "SILVER", "SPX", "NDX", "COIN", "MSTR", "AMD", "AVGO",
           "NFLX", "ORCL", "PLTR", "GME", "AMC", "INTC", "MU", "SMCI", "CRCL", "HOOD")


def load() -> pd.DataFrame:
    cols = {}
    for f in sorted(glob.glob(os.path.join(KL, "*.json"))):
        s = os.path.basename(f)[:-5]
        if s == "MANIFEST":
            continue
        try:
            d = json.load(open(f))
        except Exception:
            continue
        bars = d.get("bars") or []
        if len(bars) < 120:
            continue
        idx = pd.to_datetime([b["t"] for b in bars], unit="ms", utc=True).normalize()
        cols[s] = pd.Series([float(b["c"]) for b in bars], index=idx)
    return pd.DataFrame(cols).sort_index()


def main() -> int:
    px = load()
    ret = np.log(px / px.shift()).replace([np.inf, -np.inf], np.nan)
    ret = ret.dropna(how="all")
    print(f"panel: {px.shape[1]} simbol x {len(px)} hari "
          f"| {px.index[0].date()} -> {px.index[-1].date()}")

    # jendela bersama agar korelasi tidak bias oleh ketersediaan berbeda
    common = ret.dropna(axis=1, thresh=int(0.9 * len(ret))).dropna()
    print(f"jendela bersama (>=90% ketersediaan): {common.shape[1]} simbol x {len(common)} hari")

    C = common.corr()
    iu = np.triu_indices_from(C, k=1)
    pair = C.to_numpy()[iu]
    pair = pair[np.isfinite(pair)]

    eq = [c for c in common.columns if any(h in c.upper() for h in EQ_HINT)]
    cr = [c for c in common.columns if c not in eq]
    def block(a, b):
        if len(a) < 2 or len(b) < 2:
            return float("nan")
        sub = C.loc[a, b].to_numpy()
        m = ~np.eye(len(a), len(b), dtype=bool) if set(a) == set(b) else np.ones_like(sub, bool)
        v = sub[m]
        v = v[np.isfinite(v)]
        return float(v.mean()) if v.size else float("nan")

    ev = np.linalg.eigvalsh(C.to_numpy())
    ev = np.clip(ev, 0, None)
    n_eff = float((ev.sum() ** 2) / (ev ** 2).sum())
    pc1 = float(ev[-1] / ev.sum())

    # berapa mesin independen yang mungkin? Mesin = long-short acak atas k simbol.
    # rho_PnL antar dua mesin ~ rho_aset rata-rata x (tumpang tindih)
    avg_pair = float(np.nanmean(pair))
    floor_inf = float(common.shape[1]) / (1.0 + (common.shape[1] - 1.0) * avg_pair) if avg_pair > -1 else float("nan")

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "n_symbols": int(px.shape[1]),
        "n_symbols_common": int(common.shape[1]),
        "n_days_common": int(len(common)),
        "n_eq_rwa": len(eq), "n_crypto": len(cr),
        "pair_corr": {"mean": avg_pair,
                      "median": float(np.nanmedian(pair)),
                      "p75": float(np.nanpercentile(pair, 75)),
                      "p90": float(np.nanpercentile(pair, 90)),
                      "p10": float(np.nanpercentile(pair, 10))},
        "block_crypto_crypto": block(cr, cr),
        "block_eqrwa_eqrwa": block(eq, eq),
        "block_cross": block(cr, eq),
        "n_effective_bets": n_eff,
        "pc1_variance_share": pc1,
        "rho_inf_theoretical_equicorr": floor_inf,
        "sharpe_multiplier_if_6_engines_rho_median":
            6.0 / (1.0 + 5.0 * max(0.0, float(np.nanmedian(pair)))),
    }
    print(json.dumps(out, indent=1, default=str))

    # implikasi langsung ke target
    print("\n=== IMPLIKASI KE TARGET ===")
    print(f"  rho aset rata-rata antar simbol SoDEX   = {avg_pair:.3f}")
    print(f"  rho median                              = {out['pair_corr']['median']:.3f}")
    print(f"  N_eff (taruhan independen di venue)     = {n_eff:.1f} dari {common.shape[1]} simbol")
    print(f"  porsi varians PC1 (faktor pasar venue)  = {pc1*100:.1f}%")
    print(f"  -> 6 mesin dengan rho_PnL = rho_aset median:")
    print(f"     pengali Sharpe = sqrt(6/(1+5*rho)) = "
          f"{np.sqrt(6.0/(1.0+5.0*max(0.0,out['pair_corr']['median']))):.2f} "
          f"(butuh 4,6 untuk target pada sigma portofolio 2,35%)")

    d = os.path.join(ROOT, "reports", "sodex")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "SENSUS_DIVERSIFIKASI_SODEX.json")
    with open(p, "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(f"\nberkas: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
