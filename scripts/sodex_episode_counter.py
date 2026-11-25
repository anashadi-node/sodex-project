#!/usr/bin/env python3
"""
ANANTARA SAKTI — Penghitung episode forward SoDEX (READ-ONLY) untuk memicu re-uji.

Menghitung jumlah episode independen pada theta=2,0% (spesifikasi beku
docs/sodex/SODEX_FORWARD_MOMENTUM_PRAREG_2026-10-05.md) dan melaporkan kapan
ambang ~150 episode tercapai -> pemicu re-uji DEV dengan PRA-REGISTRASI BARU.

PENTING — SEGEL LOCKBOX DIHORMATI:
  BTC/ETH/SOL pada 2026-09-01..2026-10-05 adalah LOCKBOX dan TIDAK PERNAH dibaca.
  Simbol baru (perluasan 2026-10-05) tidak punya lockbox -> dihitung sejak 2026-10-05.
Hanya membaca berkas JSONL + menulis laporan. Tidak menyentuh lane uang.
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sodex_forward_momentum import minute_series, events, SYMS, THETA, DEV_LO, DEV_HI  # noqa: E402
from sodex_collector_guard import telegram  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
T = ROOT / "freqtrade_user_data/data/sodex/trades"
REP = ROOT / "reports/sodex"
NEW_FROM = "20261005"                      # tanggal perluasan simbol
NEW_SYMS = ["ZEC-USD", "DOGE-USD", "SUI-USD", "XAUT-USD", "QNT-USD", "PONS-USD",
            "LIT-USD", "HYPE-USD", "AAVE-USD", "XRP-USD", "US500-USD", "UNI-USD", "ARB-USD",
            "SNDK-USD", "AVAX-USD", "SPCX-USD", "BNB-USD"]
NEW_SYMS = sorted(set(NEW_SYMS) - set(SYMS))
TARGET_EP = 150
THETA_USE = THETA[-1]                      # 2,0% — ambang dengan magnitudo terbaik


def days_between(lo: str, hi: str) -> list[str]:
    out, seen = [], set()
    for f in sorted(os.listdir(T)):
        if not (f.startswith("trades_") and f.endswith(".jsonl")):
            continue
        d = f[7:15]
        if lo <= d <= hi:
            seen.add(d)
    return sorted(seen)


def count_for(sym: str, days: list[str]) -> int:
    pts: list[tuple[int, float]] = []
    for d in days:
        pts.extend(sorted(minute_series(d, sym).items()))
    if len(pts) < 100:
        return 0
    return len(events(pts, THETA_USE))


def main() -> int:
    # 1) BTC/ETH/SOL — HANYA rentang DEV (LOCKBOX 2026-09-01..10-05 tidak disentuh)
    dev_days = days_between(DEV_LO, DEV_HI)
    base = {s: count_for(s, dev_days) for s in SYMS}
    # 2) simbol BARU — sejak 2026-10-05 (tidak ada lockbox)
    new_days = [d for d in days_between(NEW_FROM, "20991231")]
    new = {s: count_for(s, new_days) for s in NEW_SYMS}
    n_base, n_new = sum(base.values()), sum(new.values())
    total = n_base + n_new

    # laju episode/simbol/hari dari basis DEV (94 hari) sbg proyeksi
    rate = (n_base / len(SYMS) / len(dev_days)) if dev_days else 0.0
    rate_all = rate * (len(SYMS) + len(NEW_SYMS))
    sisa = max(0, TARGET_EP - total)
    hari_perlu = (sisa / rate_all) if rate_all > 0 else None
    etd = (datetime.now(timezone.utc).date().__class__.fromordinal(
        datetime.now(timezone.utc).date().toordinal() + int(hari_perlu + 0.999))
        if hari_perlu else None)

    out = {"theta_pct": THETA_USE * 100, "lockbox_read": False,
           "base_symbols": base, "base_episodes": n_base,
           "new_symbols": new, "new_episodes": n_new, "total": total,
           "target": TARGET_EP, "rate_ep_per_day_all": round(rate_all, 3),
           "etd": str(etd) if etd else None,
           "days_base": len(dev_days), "days_new": len(new_days),
           "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    REP.mkdir(parents=True, exist_ok=True)
    (REP / "SODEX_FORWARD_EPISODE_COUNT.json").write_text(json.dumps(out, indent=1))

    print(f"[episode θ={THETA_USE*100:.1f}%] basis DEV (BTC/ETH/SOL, {len(dev_days)} hari): {n_base}")
    print(f"                       simbol baru ({len(NEW_SYMS)} simbol, {len(new_days)} hari): {n_new}")
    print(f"                       TOTAL: {total} / target {TARGET_EP}"
          f"{'  ✅ SIAP RE-UJI' if total >= TARGET_EP else ''}")
    print(f"                       laju ~{rate_all:.2f} episode/hari → perkiraan capai target: {etd}")
    if total >= TARGET_EP:
        msg = (f"✅ <b>SoDEX siap re-uji</b>\nEpisode θ={THETA_USE*100:.1f}%: <b>{total}</b> / target {TARGET_EP}\n"
               f"(basis DEV {n_base} + simbol baru {n_new})\n"
               "AKSI: tulis PRA-REGISTRASI BARU, lalu jalankan re-uji DEV. LOCKBOX lama tetap tersegel.")
        print(">>> AKSI: jalankan re-uji DEV dengan PRA-REGISTRASI BARU (lockbox baru terpisah).")
        telegram(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
