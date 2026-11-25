#!/usr/bin/env python3
"""BATERAI STABILITAS (falsifikasi) untuk semua kandidat PRAREG-18.

Saringan (dideklarasikan sekarang, sifat POST-HOC, hanya dipakai untuk MEMBUNUH kandidat,
tidak pernah untuk mempromosikan):
  S1 tanda net KONSISTEN di 4 potongan sampel (penuh, 6000, 4000, 3000 bar)
  S2 |t| penuh >= 2,0
  S3 kontribusi 5 window terbaik < 35% dari total net (bukan outlier-driven)
  S4 lolos di setengah nama paling LIKUID (kausal: median volume trailing, di-shift 1 bar)
Lulus keempat = "TAHAN-SEMBABIL"; gagal salah satu = MATI (dicatat sebabnya).

Jalankan: /usr/bin/python3 scripts/research/sodex_stability_battery.py
"""
from __future__ import annotations

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
from sodex_mom_l21_venue_test import KRIPTO, load_panel  # noqa: E402
from klines_snapshot import fingerprint  # noqa: E402

OUT = os.path.join(ROOT, "reports", "sodex", "STABILITY_BATTERY.json")
TAILS = (None, 6000, 4000, 3000)


def net_stream(px, sig, ret, hold, fee=xs.FEE_ONEWAY, names=None):
    if names is not None:
        px, sig, ret = px[names], sig[names], ret[names]
    idx = px.index
    out, prev = [], None
    for i in range(0, len(idx) - max(hold, 1), hold):
        s = sig.iloc[i].dropna()
        if s.size < xs.MIN_NAMES:
            continue
        fwd = ret.iloc[i + 1:i + 1 + hold].sum(skipna=False).reindex(s.index)
        ok = fwd.notna() & s.notna()
        s, fwd = s[ok], fwd[ok]
        if s.size < xs.MIN_NAMES:
            continue
        ex = fwd - fwd.mean()
        w = xs.rank_w(s)
        g = float((w * ex).sum())
        if prev is None:
            to = float(w.abs().sum())
        else:
            u = w.index.union(prev.index)
            to = float((w.reindex(u, fill_value=0.0) - prev.reindex(u, fill_value=0.0)).abs().sum())
        prev = w
        out.append(g - to * fee)
    return np.array(out) * 1e4


def stats(n):
    if n.size < 8:
        return None
    sd = float(n.std(ddof=1))
    return {"n": int(n.size), "net": float(n.mean()), "sd": sd,
            "t": float(xs.nw_t(n, lag=1)), "mean_med": float(np.median(n))}


def main() -> int:
    px, vol = load_panel("1h")
    ret = px.pct_change()
    sigs, _ = xs.build_signals(px)
    xs.add_maxfx(sigs, px)
    vmed = vol.rolling(720, min_periods=200).median().shift(1)
    liq_now = vmed.iloc[-1].reindex(px.columns).dropna()
    liq_hi = liq_now[liq_now >= liq_now.median()].index.tolist()
    res = {"sifat": "POST-HOC, hanya untuk falsifikasi", "n_sel": 0, "tahan_sembabil": [],
           "fingerprint_data": fingerprint("1h"), "detail": {}}
    print(f"panel {px.shape} | nama likuid-tinggi: {len(liq_hi)}")
    print(f"{'sel':34}{'net':>8}{'t':>7}{'tanda-4':>9}{'top5%':>7}{'likuid':>8}  vonis")
    for mech in xs.MECH_ORDER:
        if mech not in sigs:
            continue
        for hold in (24, 48):
            for arah, sg in (("as_is", 1.0), ("dibalik", -1.0)):
                sig = sigs[mech] * sg
                base = net_stream(px, sig, ret, hold)
                if base.size < 40:
                    continue
                st = stats(base)
                subs = [net_stream(px.iloc[-t:], sig.iloc[-t:], ret.iloc[-t:], hold)
                        for t in TAILS[1:]]
                subs = [s for s in subs if s.size >= 20]
                signs = {np.sign(round(float(s.mean()), 6)) for s in subs} | {np.sign(round(st["net"], 6))}
                tanda_konsisten = len(signs) == 1
                top5 = float(np.sort(base)[::-1][:5].sum() / base.sum()) if base.sum() != 0 else 9.9
                liq = net_stream(px, sig, ret, hold, names=liq_hi)
                sl = stats(liq)
                key = f"{mech}|H{hold}|{arah}"
                ok = (tanda_konsisten and abs(st["t"]) >= 2.0 and abs(top5) < 0.35
                      and sl is not None and sl["net"] > 0 and sl["t"] >= 1.5)
                vonis = "TAHAN-SEMBABIL" if ok else "MATI"
                if not tanda_konsisten:
                    vonis += " (tanda tidak konsisten)"
                elif abs(top5) >= 0.35:
                    vonis += " (outlier-driven)"
                elif sl is None or sl["net"] <= 0:
                    vonis += " (gagal di nama likuid)"
                elif abs(st["t"]) < 2.0:
                    vonis += " (t<2)"
                res["detail"][key] = {"net": st["net"], "t": st["t"], "sd": st["sd"],
                                      "sub_net": [float(s.mean()) for s in subs],
                                      "tanda_konsisten": tanda_konsisten,
                                      "top5_kontribusi": top5,
                                      "likuid": sl, "vonis": vonis}
                if ok:
                    res["tahan_sembabil"].append(key)
                sl_txt = f"{sl['net']:.1f}" if sl else "n/a"
                print(f"{key:34}{st['net']:>8.2f}{st['t']:>7.2f}{str(tanda_konsisten):>9}"
                      f"{top5 * 100:>6.0f}%{sl_txt:>8}  {vonis}")
    res["n_sel"] = len(res["detail"])
    print(f"\n[{res['n_sel']} sel diuji] TAHAAN-SEMBABIL: "
          f"{res['tahan_sembabil'] if res['tahan_sembabil'] else 'TIDAK ADA'}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(res, f, indent=1, default=str)
    print(f"[ditulis] {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
