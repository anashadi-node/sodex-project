#!/usr/bin/env python3
"""Breakdown per-SISI (LONG vs SHORT) tiap track SoDEX pada harness beku.

KENAPA ADA
----------
Harness `sodex_harness_reeval.py` menilai TIAP TRACK secara agregat (LONG+SHORT
dicampur), kecuali satu blok khusus `twoway SHORT`. Akibatnya pertanyaan paling
menentukan tidak pernah terjawab dengan angka:

    "Kaki mana yang membawa edge -- LONG atau SHORT?"

Pada 2026-10-04 pertanyaan ini menjadi kritis. Track `twoway` punya dua kaki
dengan profil yang sama sekali berbeda, dan rezim saat ini (BULL/CHOP) mematikan
satu di antaranya. Tanpa breakdown, verdict T1 menyesatkan.

TEMUAN (2026-10-04, harness beku, fee RT 8 bps)
-----------------------------------------------
    track     sisi    n    WR      edge       cost1x    cost2x   fee-impas@2x
    twoway    LONG   325  45,23%  +8,04 bps  +0,04 bps  -7,96 bps   4,02 bps
    twoway    SHORT   42  33,33% +60,94 bps +52,94 bps +44,94 bps  30,47 bps
    swing     LONG   387  36,18% -12,26 bps -20,26 bps -28,26 bps  -6,13 bps
    realwide  LONG   235  48,51%  -3,68 bps -11,68 bps -19,68 bps  -1,84 bps

Interpretasi: constraint T1 adalah BIAYA, bukan ukuran sampel. Kaki LONG
`twoway` -- satu-satunya dengan n besar (325) -- punya edge yang PERSIS setara
fee (8,04 vs 8,00 bps), sehingga cost 1x = +0,04 bps (praktis nol) dan cost 2x
gagal tipis. Kaki SHORT punya edge 7,6x fee, tapi digerbangi death-cross
(SMA50<SMA200) sehingga nol trade sejak 2026-09-01.

Semua pengukuran di sini WAJIB masuk registry: menambah trial memperketat
penalti multiple-testing bagi semua orang -- itu memang tujuannya.

Pemakaian:
    python3 scripts/sodex_side_breakdown.py            # hitung + log registry
    python3 scripts/sodex_side_breakdown.py --no-log   # hanya tampilkan
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "docs/handover/RISET_TO_DIVISI_2026-10-01/harness"))

import sodex_harness_reeval as H  # noqa: E402
from anantara_harness import TrialRegistry  # noqa: E402

MIN_N = 30  # dokumen riset 10.1: n>=30 = evidence minimum sebelum klaim


def sisi_kaki(rows, sign):
    return [r for r in rows if H.side_sign(r) == sign]


def ukur(sub, candles, n_trials):
    returns = [H.trade_return(r) for r in sub]
    grade, res = H.evaluate(
        returns=returns,
        market=H.btc_market_returns(sub, candles),
        sides=[H.side_sign(r) for r in sub],
        fee_bps=H.SODEX_FEE_BPS,
        n_trials=n_trials,
        groups=[H.trade_symbol(r) for r in sub],
        periods_per_year=365,
        min_n=MIN_N,
    )
    cs = res.get("cost_stress", {})
    excess = res.get("excess_mean", math.nan)
    fee = H.SODEX_FEE_BPS / 10_000.0
    # fee di mana net = 0 pada 2x biaya: excess/2 (dua leg bayar fee masing-masing)
    impas = (excess / 2.0) * 10_000.0
    return {
        "n": len(sub),
        "wr": sum(1 for x in returns if x > 0) / len(returns),
        "excess_bps": excess * 10_000.0,
        "cost1x_bps": cs.get("1.0", {}).get("mean", math.nan) * 10_000.0,
        "cost2x_bps": cs.get("2.0", {}).get("mean", math.nan) * 10_000.0,
        "sharpe_ann": res.get("sharpe_ann", math.nan),
        "fee_impas_bps": impas,
        "passed": bool(grade.get("passed")),
        "reasons": list(grade.get("reasons") or []),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-log", action="store_true", help="jangan tulis ke registry")
    args = ap.parse_args()

    reg_path = ROOT / "reports/sodex/sodex_trial_registry.json"
    registry = TrialRegistry(reg_path)
    n_trials = registry.count() + 1

    start = dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc)
    end = dt.datetime.now(dt.timezone.utc)
    candles = H.fetch_btc_1h(start, end)
    print(f"candles BTC 1h : {len(candles)}")
    print(f"fee RT         : {H.SODEX_FEE_BPS:.1f} bps")
    print(f"n_trials masuk : {n_trials}\n")

    hdr = f"{'track':<10}{'sisi':<7}{'n':>5}{'WR':>8}{'edge bps':>10}{'1x bps':>9}{'2x bps':>9}{'fee-impas':>11}{'Sharpe':>8}  PASS"
    print(hdr)
    print("-" * len(hdr))

    hasil = []
    for name, path in H.TRACKS.items():
        rows = [r for r in H.closed_rows(path) if H.arm_of(r) == H.ARM_SIGNAL]
        for label, sign in (("LONG", 1), ("SHORT", -1)):
            sub = sisi_kaki(rows, sign)
            if len(sub) < MIN_N:
                print(f"{name:<10}{label:<7}{len(sub):>5}   (n<{MIN_N}, bukan evidence)")
                continue
            m = ukur(sub, candles, n_trials)
            hasil.append((name, label, m))
            print(
                f"{name:<10}{label:<7}{m['n']:>5}{m['wr']*100:>7.2f}%{m['excess_bps']:>10.2f}"
                f"{m['cost1x_bps']:>9.2f}{m['cost2x_bps']:>9.2f}{m['fee_impas_bps']:>11.2f}"
                f"{m['sharpe_ann']:>8.2f}  {m['passed']}"
            )

    if not args.no_log:
        print()
        for name, label, m in hasil:
            registry.log(
                strategy=f"{name}:{label}",
                passed=m["passed"],
                note="SoDEX breakdown per-sisi (LONG/SHORT) pada harness beku",
                n=m["n"],
                excess_bps=round(m["excess_bps"], 4),
                cost1x_bps=round(m["cost1x_bps"], 4),
                cost2x_bps=round(m["cost2x_bps"], 4),
                fee_impas_bps=round(m["fee_impas_bps"], 4),
                sharpe_ann=round(m["sharpe_ann"], 4),
                reasons=m["reasons"],
            )
        print(f"registry: {len(hasil)} trial dicatat -> n_trials_total={registry.count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
