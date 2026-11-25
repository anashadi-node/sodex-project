#!/usr/bin/env python3
"""SUMBER TUNGGAL MODEL BIAYA — SoDEX (spot & perps).

MENGAPA MODUL INI ADA (audit 30-Sep-2026, temuan terverifikasi):
Model biaya sebelumnya TIDAK cocok dengan kenyataan live:
  • `paper_test_realwide.py` memakai fee MAKER (2,4 bps) padahal lane live
    (`realwide_micro_live.py:604,412`) mengirim `--type market --tif ioc` = TAKER.
  • Spread hanya dihitung SEKALI, padahal posisi membayar spread saat masuk DAN
    saat keluar (2×).
  • FUNDING tidak dimodelkan sama sekali (posisi swing ditahan lintas settlement 8 jam).

Akibatnya proyeksi terlalu optimis ~2× (8,6 bps vs 15,2–17,2 bps) dan target 0,8%
terlihat tercapai padahal tidak. Modul ini menjadikan biaya SATU sumber kebenaran
dan bisa diaudit.

ANGKA (dari API resmi venue `sodex markets spot|perps`, diverifikasi 30-Sep-2026):
    SPOT  : maker 3,5 bps/sisi | taker 6,5 bps/sisi
    PERPS : maker 1,2 bps/sisi | taker 4,0 bps/sisi
Bukti lapangan (likuidasi 3 aset spot, taker): biaya tersirat 62 bps — konsisten
dengan fee taker + spread saat menekan buku.

CATATAN KEJUJURAN: gas/jaringan/withdrawal TIDAK ada datanya di API venue, jadi
TIDAK dimodelkan di sini. Itu disebutkan, bukan disembunyikan.
"""
from __future__ import annotations

import os
from decimal import Decimal as D

BPS = D("0.0001")

# ── Fee venue (per SISI) ───────────────────────────────────────────────────────
SPOT_MAKER_BPS = D("3.5")
SPOT_TAKER_BPS = D("6.5")
PERP_MAKER_BPS = D("1.2")
PERP_TAKER_BPS = D("4.0")

# ── Spread top-of-book (bps, sisi=1). Sumber: pengukuran live 2026-08-29 + data
# pasar. Dipakai sebagai PROKSI biaya menyeberang spread per sisi.
DEFAULT_SPREAD_BPS = D("3.8")
SPREAD_BPS: dict[str, D] = {
    "BTC": D("1.3"), "ETH": D("2.0"), "SOL": D("3.5"), "XRP": D("2.0"),
    "DOGE": D("2.0"), "BCH": D("2.0"), "ONDO": D("2.85"), "LINK": D("2.0"),
    "AAVE": D("2.0"), "ADA": D("4.97"), "TRX": D("2.0"), "UNI": D("2.27"),
    "ENA": D("6.14"), "XAUT": D("6.05"), "ARB": D("2.0"), "AVAX": D("2.0"),
    "ASTER": D("4.0"), "PUMP": D("4.0"), "LIT": D("8.0"), "BNB": D("2.0"),
    "HYPE": D("8.0"), "SUI": D("8.0"), "SILVER": D("8.0"),
}

# ── Funding ────────────────────────────────────────────────────────────────────
# SoDEX perps: modus 0,0013%/8 jam; maksimum teramati 0,008%/8 jam (survey 78 pair).
FUNDING_PER_8H_BPS = D(os.environ.get("COST_FUNDING_BPS_8H", "0.13"))
FUNDING_SETTLE_HOURS = D("8")


def spread_bps(pair: str) -> D:
    """Spread per sisi (bps) untuk pair; fallback konservatif bila tak dikenal."""
    return SPREAD_BPS.get(str(pair).upper(), DEFAULT_SPREAD_BPS)


def funding_bps(pair: str, hold_hours: float) -> D:
    """Biaya funding (bps) untuk menahan posisi `hold_hours` jam.

    Tanda diabaikan (biaya absolut): arah bayar/terima tergantung sisi & tingkat
    funding saat itu; untuk KONSERVATIF selalu dihitung sebagai BIAYA.
    """
    n_settle = D(str(max(0.0, float(hold_hours)))) / FUNDING_SETTLE_HOURS
    return FUNDING_PER_8H_BPS * n_settle


def round_trip_bps(*, venue: str = "perps", order_type: str = "taker",
                   pair: str = "BTC", hold_hours: float = 0.0,
                   include_funding: bool = True) -> D:
    """Total biaya round-trip (bps) = fee 2 sisi + spread 2 sisi + funding.

    order_type: "taker" (market/IOC — dipakai lane live saat ini) atau "maker".
    """
    v = str(venue).lower()
    ot = str(order_type).lower()
    # Toleran alias: "perps", "sodex_perps", "PERP" semua dikenali perps.
    # BUG ditemukan 30-Sep-2026 saat audit: `v.startswith("perp")` membuat
    # "sodex_perps" jatuh ke cabang SPOT (fee 6,5 bps, bukan 4,0) — silent.
    is_perp = "perp" in v
    if is_perp:
        fee_side = PERP_TAKER_BPS if ot == "taker" else PERP_MAKER_BPS
    else:
        fee_side = SPOT_TAKER_BPS if ot == "taker" else SPOT_MAKER_BPS
    total = fee_side * 2 + spread_bps(pair) * 2
    if include_funding and is_perp:
        total += funding_bps(pair, hold_hours)
    return total


def round_trip_frac(**kw) -> D:
    """Sama seperti round_trip_bps tapi sebagai fraksi (0.0015 = 15 bps)."""
    return round_trip_bps(**kw) * BPS


def describe(*, venue: str = "perps", order_type: str = "taker",
             pair: str = "BTC", hold_hours: float = 24.0) -> str:
    """Ringkas satu skenario biaya (untuk laporan/verifikasi)."""
    v = str(venue).lower()
    fee_side = ((PERP_TAKER_BPS if order_type == "taker" else PERP_MAKER_BPS)
                if v.startswith("perp")
                else (SPOT_TAKER_BPS if order_type == "taker" else SPOT_MAKER_BPS))
    sp = spread_bps(pair)
    fu = funding_bps(pair, hold_hours) if v.startswith("perp") else D(0)
    tot = fee_side * 2 + sp * 2 + fu
    return (f"{v}/{order_type}/{pair} hold {hold_hours:.0f}j: "
            f"fee {fee_side*2:.1f} + spread {sp*2:.1f} + funding {fu:.2f} "
            f"= {tot:.2f} bps ({tot*BPS*100:.4f}%)")


# Alias kompatibilitas utk kode lama yang memakai "MAKER_FEE"
MAKER_FEE_FRAC = (PERP_MAKER_BPS * BPS)          # 0,00012 — fee VENUE per sisi
LEGACY_MAKER_FEE_FRAC = D("0.00024")             # nilai lama (lebih mahal dari venue)


if __name__ == "__main__":
    print("=== MODEL BIAYA (sumber tunggal) ===")
    for v in ("perps", "spot"):
        for ot in ("taker", "maker"):
            for pair in ("BTC", "ETH", "SOL"):
                print("  " + describe(venue=v, order_type=ot, pair=pair, hold_hours=24))
    print()
    rt_now = round_trip_bps(venue="perps", order_type="taker", pair="BTC", hold_hours=24)
    rt_old = D("0.00024") / BPS + spread_bps("BTC")
    print(f"  lane live SEKARANG (perps/taker/BTC/24j) : {rt_now:.2f} bps")
    print(f"  model paper LAMA (maker + 1x spread)     : {rt_old:.2f} bps")
    print(f"  rasio underestimate                      : {rt_now/rt_old:.2f}x")