#!/usr/bin/env python3
"""TES LIKUIDITAS/KLAS-ASET untuk −MOM_L21 (kandidat terkuat PRAREG-18).

Hipotesis yang diuji (hipotesis PEMBUNUH, bukan pendukung):
  Tokenized equity di SoDEX diperdagangkan 24/7 padahal underlying tutup -> harga basi/quote
  bounce -> "reversal" 21 jam yang terukur bisa jadi ARTEFAK yang tidak bisa diperdagangkan.
  Jika edge hanya hidup di (a) bucket equity atau (b) nama ber-volume kecil, maka edge itu
  TIDAK LAYAK.

Uji: jalankan −MOM_L21 pada hold {24,48} untuk subset: ALL, KRIPTO, EQUITY,
     LIKUID-TINGGI (median volume trailing >= median cross-section), LIKUID-RENDAH.
Likuiditas = median quote-volume hourly trailing 720 bar (kausal, di-shift 1 bar).

Jalankan: /usr/bin/python3 scripts/research/sodex_mom_l21_venue_test.py
"""
from __future__ import annotations

import glob
import json
import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import xsec_mech_study as xs  # noqa: E402
from klines_snapshot import fingerprint  # noqa: E402

OUT = os.path.join(ROOT, "reports", "sodex", "MOM_L21_LIKUIDITAS.json")
KRIPTO = set("""1000BONK 1000PEPE 1000SHIB AAVE ADA APT ARB ASTER AVAX AXS BASED BCH BERA BNB BREV
BTC CASHCAT CHZ DASH DOGE ENA FARTCOIN FIL HBAR HYPE LINK LIT LTC MINIMAX MON MORPHO NEAR
ONDO OP PENGU PONS PUMP QNT SOL SOSO SUI TAO TON TRUMP TRX UNI VIRTUAL WIF WLD WLFI XLM
XMR XPL XRP ZEC""".split())
HOLDS = (24, 48)


def load_panel(interval="1h"):
    px, vol = {}, {}
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "sodex_klines", interval, "*.json"))):
        if "MANIFEST" in f:
            continue
        sym = os.path.basename(f)[:-5].replace("-USD", "")
        try:
            d = json.load(open(f))
        except Exception:
            continue
        bars = d.get("bars") or []
        if len(bars) < 300:
            continue
        idx = pd.to_datetime([b["t"] for b in bars], unit="ms", utc=True)
        if interval == "1d":
            idx = idx.normalize()
        px[sym] = pd.Series([float(b["c"]) for b in bars], index=idx)
        vol[sym] = pd.Series([float(b.get("q") or 0.0) for b in bars], index=idx)
    return pd.DataFrame(px).sort_index(), pd.DataFrame(vol).sort_index()


def bt(px, ret, sig_raw, hold, fee, names=None):
    """Backtest rank_w dengan subset nama tetap (names) - turnover dihitung dalam subset."""
    if names is not None:
        px = px[names]
        ret = ret[names]
        sig_raw = sig_raw[names]
    idx = px.index
    recs, prev_w = [], None
    for i in range(0, len(idx) - max(hold, 1), hold):
        sig = sig_raw.iloc[i].dropna()
        if sig.size < xs.MIN_NAMES:
            continue
        fwd = ret.iloc[i + 1:i + 1 + hold].sum(skipna=False).reindex(sig.index)
        ok = fwd.notna() & sig.notna()
        sig, fwd = sig[ok], fwd[ok]
        if sig.size < xs.MIN_NAMES:
            continue
        excess = fwd - fwd.mean()
        w = xs.rank_w(sig)
        gross = float((w * excess).sum())
        if prev_w is None:
            to = float(w.abs().sum())
        else:
            allk = w.index.union(prev_w.index)
            to = float((w.reindex(allk, fill_value=0.0)
                        - prev_w.reindex(allk, fill_value=0.0)).abs().sum())
        recs.append({"t": idx[i], "net": gross - to * fee, "to": to, "n": int(sig.size)})
        prev_w = w
    if not recs:
        return None
    df = pd.DataFrame(recs).set_index("t")
    net = df["net"].to_numpy()
    sd = float(net.std(ddof=1))
    S = (net.mean() / sd) * math.sqrt(8760.0 / hold) if sd > 0 else float("nan")
    return {"n": len(df), "names_med": int(df["n"].median()),
            "net_bps": float(net.mean() * 1e4), "sd_bps": float(sd * 1e4),
            "S_ann": float(S), "t": float(xs.nw_t(net, lag=max(1, hold))),
            "to": float(df["to"].mean())}


def main() -> int:
    px, vol = load_panel("1h")
    sig = -px.pct_change(21)                       # −MOM_L21 (kandidat)
    ret = px.pct_change()
    syms = list(px.columns)
    krip = [s for s in syms if s in KRIPTO]
    ekui = [s for s in syms if s not in KRIPTO]
    vmed = vol.rolling(720, min_periods=200).median().shift(1)
    print(f"panel SoDEX 1h: {px.shape[1]} nama x {len(px)} bar | kripto={len(krip)} "
          f"equity/lain={len(ekui)}")
    out = {"prareg": "reports/sodex/PRAREG18_PROGRAM_EKSTREM_PROTOCOL.json",
           "fingerprint_data": fingerprint("1h"),
           "mekanisme": "-MOM_L21 (momentum 21 jam dibalik)",
           "hipotesis_pembunuh": "edge hanya hidup di equity/illikuid = artefak harga basi",
           "n_kripto": len(krip), "n_ekuitas": len(ekui), "hasil": {}}

    # subset likuiditas kausal per window
    liq_hi, liq_lo = [], []
    for i in range(0, len(px) - max(HOLDS), 24):
        v = vmed.iloc[i].reindex(px.columns).dropna()
        if v.size < 40:
            continue
        med = v.median()
        hi = v[v >= med].index.tolist()
        lo = v[v < med].index.tolist()
        liq_hi.append((px.index[i], hi))
        liq_lo.append((px.index[i], lo))

    for hold in HOLDS:
        linea = {"ALL": bt(px, ret, sig, hold, xs.FEE_ONEWAY)}
        linea["KRIPTO"] = bt(px, ret, sig, hold, xs.FEE_ONEWAY, krip)
        linea["EQUITY"] = bt(px, ret, sig, hold, xs.FEE_ONEWAY, ekui)
        # likuid: jalankan dgn mask per-window
        for lab, store in (("LIKUID_TINGGI", liq_hi), ("LIKUID_RENDAH", liq_lo)):
            recs, prev = [], {}
            for t, names in store:
                i = px.index.get_loc(t)
                if i is None or i + hold >= len(px):
                    continue
                s = sig.iloc[i].reindex(names).dropna()
                if s.size < xs.MIN_NAMES:
                    continue
                fwd = ret.iloc[i + 1:i + 1 + hold][s.index].sum(skipna=False)
                ok = fwd.notna() & s.notna()
                s, fwd = s[ok], fwd[ok]
                if s.size < xs.MIN_NAMES:
                    continue
                excess = fwd - fwd.mean()
                w = xs.rank_w(s)
                gross = float((w * excess).sum())
                pw = prev.get(lab)
                if pw is None:
                    to = float(w.abs().sum())
                else:
                    allk = w.index.union(pw.index)
                    to = float((w.reindex(allk, fill_value=0.0)
                                - pw.reindex(allk, fill_value=0.0)).abs().sum())
                prev[lab] = w
                recs.append({"t": t, "net": gross - to * xs.FEE_ONEWAY, "to": to, "n": s.size})
            if recs:
                df = pd.DataFrame(recs).set_index("t")
                net = df["net"].to_numpy()
                sd = float(net.std(ddof=1))
                linea[lab] = {"n": len(df), "names_med": int(df["n"].median()),
                              "net_bps": float(net.mean() * 1e4), "sd_bps": sd * 1e4,
                              "S_ann": float((net.mean() / sd) * math.sqrt(8760.0 / hold)),
                              "t": float(xs.nw_t(net, lag=hold)), "to": float(df["to"].mean())}
        out["hasil"][f"H{hold}"] = linea
        print(f"\n--- hold {hold} jam (net bps | t | S_ann | nama median) ---")
        for lab, v in linea.items():
            if v:
                print(f"  {lab:16} net={v['net_bps']:>8.2f} t={v['t']:>6.2f} "
                      f"S_ann={v['S_ann']:>6.2f} n={v['n']:>4} nama={v['names_med']:>3} "
                      f"to={v['to']:.2f}")

    # ── profil volume & kapasitas ──
    v90 = vol.tail(2160).median()          # median quote-volume/jam, 90 hari terakhir
    v90 = v90.sort_values(ascending=False)
    tot = float(v90.sum())
    share = {k: float(v / tot * 100) for k, v in v90.head(20).items()}
    out["volume_per_jam_usd"] = {
        "total_median_per_jam": tot,
        "top20": share,
        "top5_share_pct": float(v90.head(5).sum() / tot * 100),
        "top10_share_pct": float(v90.head(10).sum() / tot * 100),
        "top20_share_pct": float(v90.head(20).sum() / tot * 100),
        "n_nama_vol_ge_10k": int((v90 >= 1e4).sum()),
        "n_nama_vol_ge_100k": int((v90 >= 1e5).sum()),
        "n_nama_vol_ge_1m": int((v90 >= 1e6).sum()),
    }
    print(f"\n--- profil volume (median/jam, 90 hari) ---")
    print(f"  total={tot:,.0f} USD/jam | top5={v90.head(5).sum() / tot * 100:.1f}% "
          f"top10={v90.head(10).sum() / tot * 100:.1f}% top20={v90.head(20).sum() / tot * 100:.1f}%")
    print(f"  nama dgn vol>=10k/jam: {(v90 >= 1e4).sum()} | >=100k: {(v90 >= 1e5).sum()} "
          f"| >=1jt: {(v90 >= 1e6).sum()}")
    print("  top 8: " + ", ".join(f"{k}=${v:,.0f}" for k, v in v90.head(8).items()))

    # ── staleness: fraksi bar return nol per nama ──
    zf = (ret.abs() < 1e-12).mean().sort_values(ascending=False)
    out["staleness_frac_return_nol"] = {k: float(v) for k, v in zf.head(15).items()}
    print(f"\n--- staleness (fraksi bar return = 0) ---")
    print("  tertinggi: " + ", ".join(f"{k}={v:.2f}" for k, v in zf.head(10).items()))
    print(f"  median fraksi nol semua nama: {zf.median():.3f}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(f"\n[ditulis] {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
