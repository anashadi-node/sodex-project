#!/usr/bin/env python3
"""JARAK KE TARGET SoDEX — konsolidasi aritmetika, semua angka diverifikasi hitung.

Target resmi (HARGA MATI): PnL bersih rata-rata 0,8% dari TOTAL dana wallet per
48 jam, lewat 6-8 mesin dengan rho antar-mesin <= 0,10, tiap mesin Sharpe_ann >= 2,3.
Bukan dengan leverage.

Skrip ini menjawab: BERAPA JARAKNYA, di empat dimensi berbeda, dengan angka.

Jalankan: /usr/bin/python3 scripts/research/sodex_distance_to_target.py
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone

ROOT = os.path.expanduser("~/anantara-sakti")

# ── parameter target (JANGAN diubah tanpa approval Mas Anas) ──
TARGET_48H = 0.008          # 0,8% dari total wallet per 48 jam
SIGMA_P_48H = 0.0235        # sigma portofolio realistis (D14)
N_MACHINE = 6               # mesin (target 6-8)
RHO = 0.10                  # korelasi antar-mesin yang disyaratkan
SHARPE_MACHINE_MIN = 2.3
H_DAYS = 2.0                # 48 jam
PERIODS_YEAR = 365.0 / H_DAYS

# ── biaya venue (terverifikasi) ──
FEE_BPS_SIDE = 4.0          # scripts/sodex_harness_reeval.py SODEX_FEE_BPS=8.0 RT
SPREAD_BPS_MED = 1.71       # AUDIT_BIAYA_AKUN_2026-10-05, 77 simbol
SLIP_BPS_SIDE = SPREAD_BPS_MED / 2.0

# ── observasi venue (terukur hari ini) ──
N_EFF_VENUE = 6.1           # reports/sodex/ANGGARAN_BREADTH_SODEX.json
N_SYMBOLS = 84
RHO_ASSET = 0.33
PC1 = 0.385
IC_OBSERVED = 0.036         # IC lintas-seksi terbaik (eksploratori)
SODEX_HISTORY_DAYS = 361


def main() -> int:
    out: dict = {"generated_utc": datetime.now(timezone.utc).isoformat()}

    # ── DIMENSI 1: Sharpe portofolio yang dibutuhkan ──
    sharpe_p = (TARGET_48H / SIGMA_P_48H) * math.sqrt(PERIODS_YEAR)
    mult = math.sqrt(N_MACHINE / (1.0 + (N_MACHINE - 1) * RHO))
    sharpe_m = sharpe_p / mult
    s48_m = sharpe_m / math.sqrt(PERIODS_YEAR)
    mean_m = s48_m * SIGMA_P_48H
    print("=== DIMENSI 1 · SHARPE YANG DIBUTUHKAN ===")
    print(f"  target bersih              : {TARGET_48H*100:.2f}% per 48 jam")
    print(f"  sigma portofolio diasumsikan: {SIGMA_P_48H*100:.2f}% per 48 jam")
    print(f"  -> Sharpe portofolio wajib : {sharpe_p:.2f} /tahun")
    print(f"  pengali diversifikasi      : {mult:.2f}x  (n={N_MACHINE}, rho={RHO})")
    print(f"  -> Sharpe tiap mesin wajib : {sharpe_m:.2f} /tahun "
          f"({s48_m:.4f} per 48 jam)")
    print(f"  -> rata-rata tiap mesin    : {mean_m*100:.3f}% bersih per 48 jam")
    out["dim1_sharpe"] = {"sharpe_portfolio_required": sharpe_p, "multiplier": mult,
                          "sharpe_machine_required": sharpe_m,
                          "mean_net_pct_48h_per_machine": mean_m * 100}

    # ── DIMENSI 2: panjang bukti ──
    print("\n=== DIMENSI 2 · PANJANG BUKTI YANG DIBUTUHKAN ===")
    rows = []
    for label, tcrit in (("1 mesin tanpa koreksi", 1.96),
                         ("keluarga 5 BH q=0,10", 2.33),
                         ("keluarga 10 BH q=0,10", 2.58),
                         ("keluarga 21 BH q=0,10 (D14)", 2.82)):
        n = (tcrit / s48_m) ** 2
        rows.append((label, tcrit, n, n * H_DAYS))
        print(f"  {label:30} t>{tcrit:.2f} -> n_window {n:7.0f} = {n*H_DAYS:7.0f} hari")
    avail = SODEX_HISTORY_DAYS / H_DAYS
    print(f"  TERSEDIA di SoDEX             : {avail:.0f} window ({SODEX_HISTORY_DAYS} hari)")
    print(f"  -> Keluarga 21 (seperti D14)  : TERKUNCI "
          f"(butuh {rows[-1][2]:.0f}, ada {avail:.0f})")
    out["dim2_evidence"] = {"available_windows": avail, "required": {
        r[0]: {"t_crit": r[1], "n_windows": r[2], "days": r[3]} for r in rows}}

    # ── DIMENSI 3: anggaran IC (Hukum Fundamental) ──
    print("\n=== DIMENSI 3 · IC YANG DIBUTUHKAN (Hukum Fundamental) ===")
    freq = PERIODS_YEAR
    breadth = N_EFF_VENUE * freq
    ic_req = sharpe_m / math.sqrt(breadth)
    print(f"  N_eff venue (terukur)      : {N_EFF_VENUE} dari {N_SYMBOLS} simbol")
    print(f"  frekuensi                  : {freq:.1f} rebalance/tahun (H=48 jam)")
    print(f"  breadth = N_eff x freq     : {breadth:,.0f} taruhan independen/tahun")
    print(f"  -> IC wajib                : {ic_req:.4f}")
    print(f"  IC terukur terbaik         : {IC_OBSERVED:.4f}")
    print(f"  -> RASIO                   : {IC_OBSERVED/ic_req:.2f}x  "
          f"(butuh {ic_req/IC_OBSERVED:.2f}x lebih tinggi)")
    # setelah biaya
    ic_after = ic_req * 1.0
    print(f"  Catatan: IC wajib di atas SUDAH harus menghasilkan bruto yang menutup:")
    rt = 2 * FEE_BPS_SIDE
    print(f"    round-trip fee {rt:.2f} bps + slippage 2x{SLIP_BPS_SIDE:.2f} bps "
          f"= {rt + 2*SLIP_BPS_SIDE:.2f} bps per rebalance")
    out["dim3_ic"] = {"n_eff": N_EFF_VENUE, "breadth_per_year": breadth,
                      "ic_required": ic_req, "ic_observed": IC_OBSERVED,
                      "ratio_observed_over_required": IC_OBSERVED / ic_req}

    # ── DIMENSI 4: lantai biaya ──
    print("\n=== DIMENSI 4 · LANTAI BIAYA ===")
    rt_fee = 2 * FEE_BPS_SIDE
    rt_all = rt_fee + 2 * SLIP_BPS_SIDE
    print(f"  fee taker 2x{FEE_BPS_SIDE:.1f} bps        : {rt_fee:.2f} bps round-trip")
    print(f"  slippage 2x{SLIP_BPS_SIDE:.2f} bps       : {2*SLIP_BPS_SIDE:.2f} bps round-trip")
    print(f"  -> biaya realistis         : {rt_all:.2f} bps per round-trip")
    print(f"  sebagai % target 48 jam    : {rt_all/ (TARGET_48H*1e4) *100:.1f}%")
    print(f"  sebagai % mean mesin       : {rt_all/(mean_m*1e4)*100:.1f}%")
    out["dim4_cost"] = {"round_trip_fee_bps": rt_fee, "round_trip_total_bps": rt_all,
                        "pct_of_target": rt_all / (TARGET_48H * 1e4) * 100,
                        "pct_of_required_machine_mean": rt_all / (mean_m * 1e4) * 100}

    # ── ringkasan ──
    print("\n=== RINGKASAN JARAK KE TARGET ===")
    print(f"  1. Sharpe mesin wajib {sharpe_m:.2f}; mesin venue-SoDEX terbaik "
          f"yang terukur ~0,75 (REV_L1_H2) -> jarak {sharpe_m/0.75:.1f}x")
    print(f"  2. Window wajib {rows[-1][2]:.0f}; tersedia {avail:.0f} -> TERKUNCI")
    print(f"  3. IC wajib {ic_req:.4f}; terukur {IC_OBSERVED:.4f} -> "
          f"{ic_req/IC_OBSERVED:.2f}x kurang")
    print(f"  4. Biaya {rt_all:.1f} bps = {out['dim4_cost']['pct_of_required_machine_mean']:.0f}% "
          f"dari rata-rata mesin yang dibutuhkan")
    out["summary"] = {"best_sodex_machine_sharpe_observed": 0.75,
                      "gap_sharpe": sharpe_m / 0.75,
                      "ic_gap": ic_req / IC_OBSERVED}

    d = os.path.join(ROOT, "reports", "sodex")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "JARAK_KE_TARGET_SODEX.json")
    with open(p, "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(f"\nberkas: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
