#!/usr/bin/env python3
"""Auto-update SODEX_TOTAL_WALLET di .env.swing dari wallet REAL.

MASALAH (audit 2026-09-05): denominator target (0,7% saat itu) hardcoded $94,57 di
.env.swing, sedangkan wallet real sudah $139,37 -> ROI dilaporkan ~47%
terlalu OPTIMIS (pembagi kekecilan). Target jadi tidak jujur.

FIX: baca snapshot sync (endpoint terverifikasi), hitung total wallet
(perps + spot vUSDC), tulis ke .env.swing hanya jika beda > threshold.

Read-only terhadap exchange. Menulis HANYA baris SODEX_TOTAL_WALLET.
Run: python3 scripts/sodex_wallet_denominator.py [--apply]
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SNAP = PROJECT / "data" / "sodex_real_sync_snapshot.json"
ENV_SWING = PROJECT / ".env.swing"
KEY = "SODEX_TOTAL_WALLET"
MIN_DELTA_PCT = 0.05  # update hanya jika beda >5% (hindari churn tiap sen)
# Dust policy (audit 2026-09-15): holding yang nilainya < 0.1% priced-total
# DAN < $0.10 adalah immaterial terhadap target 0,8% — memblokir denominator
# final karenanya = false blocker. vsMAG7.ssi qty 6.1e-07 senilai ±$0.0000003
# telah memblokir denominator FINAL selama 4 hari tanpa dampak material.
# Holding material tetap fail-closed. Keduanya harus terpenuhi (AND).
DUST_ABS_USD = float(os.environ.get("SODEX_DUST_ABS_USD", "0.10"))
DUST_REL_PCT = float(os.environ.get("SODEX_DUST_REL_PCT", "0.001"))


def _split_unpriced(unpriced, priced_total):
    """Pisahkan (material, dust) dari daftar unpriced.

    Crypto 1 unit bisa bernilai ribuan dolar, jadi qty saja TIDAK cukup untuk
    bound nilai. Dust pasti hanya jika qty < 1e-4 unit — pada aset crypto
    apapun, qty sekecil itu tetap <$1 pada harga < $10.000/unit (BTC hari ini
    ±$76k). vsMAG7.ssi 6.1e-07 lolos; vBTC 0.01 (=±$760) TIDAK lolos.
    Holding lain tetap material → fail-closed.
    """
    material, dust = [], []
    for b in unpriced or []:
        qty = float(b.get("total", 0) or 0)
        upper = qty * 100_000.0  # harga konservatif maksimum $100k/unit
        if upper < DUST_ABS_USD and (priced_total <= 0 or upper < DUST_REL_PCT * priced_total):
            dust.append({**b, "upper_bound_usd": upper})
        else:
            material.append(b)
    return material, dust


def read_priced_wallet():
    """(perps, spot, priced_total, unpriced) — TIDAK fail-closed.

    Dipakai untuk MENGUKUR PROGRES paper terhadap target. Angka ini WAJIB
    dilabeli "priced_total" karena mengecualikan holding tanpa harga venue.
    Untuk keputusan final/GO-LIVE gunakan read_real_wallet() yang fail-closed.
    """
    if not SNAP.exists():
        raise FileNotFoundError(f"snapshot tidak ada: {SNAP} (jalankan sodex_realtime_sync.py)")
    d = json.loads(SNAP.read_text())
    if "spot_mark_error" in d:
        raise ValueError(f"spot mark-to-market gagal: {d['spot_mark_error']}")
    perps = float((d.get("perps_balance") or {}).get("total") or 0)
    spot = float(d.get("spot_equity_usd")
                 or (d.get("spot_vusdc") or {}).get("total") or 0)
    if perps <= 0 and spot <= 0:
        raise ValueError("snapshot tidak punya balance valid")
    unpriced = d.get("spot_unpriced")
    if unpriced is None:
        unpriced = [
            b for b in (d.get("spot_balances") or [])
            if b.get("coin") != "vUSDC" and float(b.get("total") or 0) > 0
        ]
    return perps, spot, perps + spot, list(unpriced or [])


def read_real_wallet():
    """Total wallet FINAL — fail-closed hanya untuk holding MATERIAL.

    Dust policy 2026-09-15: unpriced holding mikro (upper-bound < $0.10 DAN
    < 0.1% priced-total) tidak lagi memblokir denominator final — dilaporkan
    sebagai dust_negelectable dengan bound atas eksplisit. Holding material
    tetap menolak denominator final (fail-closed).
    """
    perps, spot, priced_total, unpriced = read_priced_wallet()
    material, dust = _split_unpriced(unpriced, priced_total)
    if material:
        coins = ", ".join(str(b.get("coin")) for b in material)
        raise ValueError(
            f"spot holdings non-vUSDC belum punya mark-to-market: {coins}; "
            f"denominator FINAL ditolak (priced lower bound = ${priced_total:.2f})"
        )
    return perps, spot, priced_total, dust




def read_current_env():
    if not ENV_SWING.exists():
        return None
    for line in ENV_SWING.read_text().splitlines():
        if line.startswith(f"{KEY}="):
            try:
                return float(line.split("=", 1)[1].strip())
            except ValueError:
                return None
    return None


def write_env(value):
    """Tulis/replace HANYA baris SODEX_TOTAL_WALLET, sisanya tidak disentuh."""
    lines = ENV_SWING.read_text().splitlines() if ENV_SWING.exists() else []
    out, found = [], False
    for line in lines:
        if line.startswith(f"{KEY}="):
            out.append(f"{KEY}={value:.2f}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{KEY}={value:.2f}")
    tmp = ENV_SWING.with_suffix(".swing.tmp")
    # 2026-10-04: tmp.write_text() membuat file dengan UMASK (0664) dan
    # tmp.replace() membuat .env.swing MEWARISI mode tmp itu -> file kredensial
    # kehilangan 0600 setiap kali --apply dijalankan. Terbukti: 2 test keamanan
    # gagal dengan ".env.swing = 0o664". Tulis dengan 0600 eksplisit dan
    # pastikan sekali lagi pada file final (fail-closed).
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("\n".join(out) + "\n")
    tmp.replace(ENV_SWING)
    os.chmod(ENV_SWING, 0o600)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="tulis perubahan (default: dry-run)")
    ap.add_argument("--min-delta", type=float, default=MIN_DELTA_PCT,
                    help="ambang update relatif (default 0.05). Turunkan untuk "
                         "menyelaraskan denominator yang basi <5%% — mis. 0.001. "
                         "2026-11-13: .env.swing $243.39 vs venue $234.17 (delta 3.8%%) "
                         "diam-diam membuat target/window 3.8%% terlalu besar.")
    a = ap.parse_args()
    min_delta = max(0.0, a.min_delta)

    perps, spot, priced, unpriced = read_priced_wallet()
    material, dust = _split_unpriced(unpriced, priced)
    try:
        _p, _s, _t, dust = read_real_wallet()
        final_ok, final_note = True, "lengkap"
    except ValueError as exc:
        final_ok, final_note = False, str(exc)
    cur = read_current_env()
    print(f"wallet PRICED: perps=${perps:.2f} + spot=${spot:.2f} = ${priced:.2f}")
    if material:
        print(f"  MATERIAL belum tervaluasi (fail-closed): {material}")
    if dust:
        dust_str = ", ".join(f"{d['coin']}=${d['upper_bound_usd']:.6f}" for d in dust)
        print(f"  dust (immaterial, upper-bound): {dust_str}")
    print(f"denominator FINAL: {'OK' if final_ok else 'DITOLAK — ' + final_note}")
    print(f"denominator .env.swing sekarang: ${cur if cur is not None else 0:.2f}")
    print(f"target 0,8% pada priced lower bound: ${0.008 * priced:.3f}")

    if not final_ok:
        print("-> TIDAK menulis .env.swing: total wallet belum bisa dinyatakan lengkap.")
        print(f"-> Untuk mengukur progres paper, priced lower bound ${priced:.2f} "
              "dipakai dengan label eksplisit (bukan angka final).")
        return

    if cur is None:
        print("-> belum ada, akan diset")
    else:
        delta = abs(priced - cur) / cur
        print(f"delta: {delta*100:.1f}% (threshold update {min_delta*100:.1f}%)")
        if delta < min_delta:
            print("-> tidak perlu update")
            return
        bias = (cur - priced) / priced * 100
        print(f"-> ROI selama ini terlalu {'OPTIMIS' if cur < priced else 'PESIMIS'} "
              f"{abs(bias):.1f}% krn denominator {'kekecilan' if cur < priced else 'kebesaran'}")

    print(f"target 0,8%/window: ${0.008 * (cur or priced):.3f} -> ${0.008 * priced:.3f}")

    if a.apply:
        write_env(priced)
        print(f"APPLIED: {KEY}={priced:.2f}")
    else:
        print("(dry-run — pakai --apply untuk menulis)")



if __name__ == "__main__":
    main()
