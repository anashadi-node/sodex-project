#!/usr/bin/env python3
"""PRAREG-39 — perp-only SoDEX (S=0), karena modal nyata terkonsentrasi di akun perp.

Kondisi akun 27-Okt-2026 (mainnet, read-only):
  perp av $186,88 (0 posisi, im 0) · spot vUSDC $49,28
  -> sel hybrid P1 (butuh spot 75%) TIDAK feasible sekarang; perp-only feasible.
"""
from __future__ import annotations
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perp38 as p38

PLAN39 = {
    "sel": {"Q1": {"S": 0.0, "M": 1.0, "Lp": 1.5},
            "Q2": {"S": 0.0, "M": 1.0, "Lp": 2.0},
            "Q3": {"S": 0.0, "M": 1.0, "Lp": 3.0},
            "Q4": {"S": 0.0, "M": 1.0, "Lp": 2.0, "voltarget": 0.25}},
    "utama": "Q2", "fee": "taker", "funding_bps": p38.FUND_SODEX,
    "gerbang": {"G1_M": 0.010, "G2_mdd": -35.0, "G3_likuidasi": 0, "G5_stress_M": 0.008},
}


def main():
    P, lo = p38._frames()
    import mode_a_engine as eng
    T = eng.target_history({k: P[k] for k in p38.COLS}, mode="B2", validate=False)
    out = {}
    for nm, c in PLAN39["sel"].items():
        df, mdd, nl = p38.sim38(P, lo, T, c["S"], c["M"], c["Lp"], "taker", p38.FUND_SODEX, c.get("voltarget"))
        r = df["net"].loc["2022-01-01":]; s = p38.stat(r)
        out[nm] = {"M": s["M_per5h_pct"], "mdd": mdd, "liq": nl, "hit30": s["hit30"],
                   "sharpe": s["sharpe"], "oos": p38.stat(r.loc["2025-01-01":])["M_per5h_pct"],
                   "train": p38.stat(r.loc[:"2024-12-31"])["M_per5h_pct"]}
        print(f"{nm} Lp={c['Lp']:.1f} vt={c.get('voltarget')} M={s['M_per5h_pct']:.5f} mdd={mdd:6.1f} "
              f"liq={nl:3d} shr={s['sharpe']:.2f} tr={out[nm]['train']:.5f} oos={out[nm]['oos']:.5f}")
    st = {}
    for nm, fu, fe in (("funding_binance", p38.FUND_BINANCE, "taker"), ("funding_stress", p38.FUND_STRESS, "taker")):
        c = PLAN39["sel"]["Q2"]; df, mdd, nl = p38.sim38(P, lo, T, c["S"], c["M"], c["Lp"], fe, fu)
        st[nm] = p38.stat(df["net"].loc["2022-01-01":])["M_per5h_pct"]
        print(f"SENS {nm} M={st[nm]:.5f} mdd={mdd:.1f} liq={nl}")
    json.dump({"plan": PLAN39, "hasil": out, "sens": st}, open(os.path.join(os.path.dirname(__file__), "perp39_results.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
