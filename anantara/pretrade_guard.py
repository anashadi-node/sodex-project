#!/usr/bin/env python3
"""Guard pra-order: cocokkan state lokal vs VENUE sebelum menambah risiko.

MENGAPA politik ASIMETRIS, bukan fail-closed seragam
----------------------------------------------------
Preseden `perps_volume_engine._verify_fill` memilih fail-closed karena yang
dipertaruhkan hanya "mencetak volume" — menahan diri selalu aman.

Untuk PENEMPATAN ORDER, fail-closed seragam justru berbahaya di arah lain:
menolak aksi yang MENGURANGI risiko (tutup posisi, kurangi size) saat API venue
sedang hiccup = membiarkan posisi rugi tetap terbuka. Itu kerugian nyata yang
disebabkan oleh guard-nya sendiri.

Maka politiknya dibedakan menurut arah risiko:

  MENAMBAH risiko (open / increase)  -> WAJIB cocok dengan venue.
                                        mismatch ATAU tak terverifikasi = BLOCK.
  MENGURANGI risiko (close / reduce) -> SELALU IZIN, apa pun keadaan venue.
                                        Menutup posisi tak perlu izin siapa pun.

Ini menutup kelas bug yang sudah memakan uang (A1 maker-ladder 3,39x; F-2
phantom `UNI 8` vs venue `0`) TANPA menciptakan kerugian baru akibat guard.

Status: TERSAMBUNG ke jalur uang nyata — `anantara/pregain_execution.py`,
langkah "7a" SEBELUM `_place_hl_order`, atas persetujuan user 2026-10-01.

BATAS PERAN (jangan dilebihkan):
Guard ini TIDAK memindahkan constraint sistem. Funnel lane SoDEX: 28.942
siklus / 18 hari hanya menghasilkan 21 entry (0,07%), dan 87,5% blokir datang
dari gerbang SINYAL (bear_stack / chk / r1_negative), bukan dari eksekusi.
Guard ini **ENABLER** — prasyarat unfreeze (FIXLOG 30-Sep §B.2 item 3,
arbiter eksekusi) — BUKAN akselerator menuju target 0,8%.
"""

from __future__ import annotations

from dataclasses import dataclass

RISK_INCREASING = frozenset({"open", "increase", "add", "scale_in"})
RISK_REDUCING = frozenset({"close", "reduce", "exit", "scale_out", "deleverage"})

TIER_REDUCE = "reduce_always_allowed"
TIER_VERIFIED = "verified_against_venue"
TIER_BLOCKED = "blocked_mismatch"
TIER_UNVERIFIABLE = "blocked_unverifiable"
TIER_ORDER_BLOCKED = "blocked_open_order_mismatch"


@dataclass(frozen=True)
class Verdict:
    allow: bool
    tier: str
    reason: str


def _norm(d):
    """Samakan nama koin (huruf besar/kecil, spasi) dan buang size nol."""
    out = {}
    for k, v in (d or {}).items():
        key = str(k).strip().upper()
        try:
            size = float(v)
        except (TypeError, ValueError):
            size = 0.0
        if abs(size) > 0:
            out[key] = size
    return out


def decide(local_positions, venue_positions, action: str, coin: str) -> Verdict:
    """Putuskan boleh/tidak menempatkan order.

    local_positions : {coin: size} menurut tracker lokal (bisa basi)
    venue_positions : {coin: size} dari API venue; None = gagal dibaca
    action          : salah satu RISK_INCREASING / RISK_REDUCING
    coin            : koin yang akan ditransaksikan
    """
    act = str(action).strip().lower()
    if act not in RISK_INCREASING and act not in RISK_REDUCING:
        return Verdict(False, TIER_UNVERIFIABLE,
                       f"aksi tak dikenal: {action!r} — menolak demi aman")

    # 1. Mengurangi risiko selalu boleh. Guard yang memblokir ini justru merugikan.
    if act in RISK_REDUCING:
        return Verdict(True, TIER_REDUCE,
                       f"{act}: mengurangi eksposur, tak perlu izin venue")

    # 2. Venue tak terbaca -> tak boleh menambah risiko atas dasar state basi.
    if venue_positions is None:
        return Verdict(False, TIER_UNVERIFIABLE,
                       "venue tak terbaca: menambah risiko tanpa verifikasi ditolak")

    loc, ven = _norm(local_positions), _norm(venue_positions)
    c = str(coin).strip().upper()

    # 3. Ghost: tracker mengklaim posisi yang TIDAK ADA di venue (kelas insiden UNI).
    if c in loc and c not in ven:
        return Verdict(False, TIER_BLOCKED,
                       f"GHOST: lokal klaim {c}={loc[c]} tapi venue kosong")

    # 4. Untracked: venue punya posisi yang tracker tidak tahu (kelas A2).
    if c in ven and c not in loc:
        return Verdict(False, TIER_BLOCKED,
                       f"UNTRACKED: venue punya {c}={ven[c]} tapi lokal tak mencatat")

    return Verdict(True, TIER_VERIFIED, f"{c}: lokal & venue cocok")


def decide_open_orders(local_open, venue_open, action: str, coin: str) -> Verdict:
    """Cocokkan ORDER TERBUKA lokal vs venue sebelum menambah risiko.

    Ini kelas bug yang SUDAH memakan uang: A1 (maker-ladder 3,39x, UNI -$19,06).
    `orders list` venue = daftar order TERBUKA — order yang terisi PENUH
    **hilang** dari daftar. Versi lama membaca "hilang" sebagai `executedQty 0`
    = "tak terisi" (phantom-unfilled) -> rung berikutnya dipasang lagi DI ATAS
    order yang sebenarnya sudah jadi. Itu asal 3,39x.

    Maka bila venue menunjukkan order terbuka yang tracker TIDAK tahu,
    menambah risiko = menumpuk di atas order tak dikenal -> BLOCK.
    """
    act = str(action).strip().lower()
    if act not in RISK_INCREASING and act not in RISK_REDUCING:
        return Verdict(False, TIER_UNVERIFIABLE,
                       f"aksi tak dikenal: {action!r} — menolak demi aman")
    if act in RISK_REDUCING:
        return Verdict(True, TIER_REDUCE,
                       f"{act}: mengurangi eksposur, tak perlu izin venue")
    if venue_open is None:
        return Verdict(False, TIER_UNVERIFIABLE,
                       "daftar order venue tak terbaca: menambah risiko ditolak")

    c = str(coin).strip().upper()
    loc = {str(k).strip().upper() for k in (local_open or {})}
    ven = {str(k).strip().upper() for k in (venue_open or {})}

    # Order venue yang tracker tidak catat -> menambah = menumpuk (kelas A1).
    if c in ven and c not in loc:
        return Verdict(False, TIER_ORDER_BLOCKED,
                       f"ORDER TAK DIKENAL: venue punya order terbuka {c} "
                       f"yang tracker tak catat — menumpuk ditolak")
    # Order yang "menguap": ambigu antara TERISI dan batal -> fail-closed ke
    # arah eksposur (persis keputusan fix A1).
    if c in loc and c not in ven:
        return Verdict(False, TIER_ORDER_BLOCKED,
                       f"ORDER MENGUAP: lokal klaim order {c}, venue tak punya "
                       f"— ambigu terisi/batal, anggap TERISI")

    return Verdict(True, TIER_VERIFIED, f"{c}: order terbuka lokal & venue cocok")


def main() -> int:
    import json

    kasus = [
        ("open", {"BTC": 0.1}, {"BTC": 0.1}, True, "cocok"),
        ("open", {"BTC": 0.1}, {"BTC": 0.0}, False, "ghost (kelas UNI)"),
        ("open", {}, {"BTC": 0.1}, False, "untracked (kelas A2)"),
        ("open", {"BTC": 0.1}, None, False, "venue tak terbaca"),
        ("close", {"BTC": 0.1}, None, True, "tutup saat venue mati"),
        ("reduce", {"BTC": 0.1}, {"ETH": 0.2}, True, "kurangi risiko saat mismatch"),
    ]
    print("=" * 72)
    print("GUARD PRA-ORDER — SELFCHECK (politik asimetris)")
    print("=" * 72)
    gagal = 0
    for action, loc, ven, mau, ket in kasus:
        v = decide(loc, ven, action, "BTC")
        tanda = "OK " if v.allow == mau else "!!!"
        if v.allow != mau:
            gagal += 1
        print(f"  {tanda} {action:<7} {ket:<28} -> "
              f"{'IZIN ' if v.allow else 'BLOCK'} [{v.tier}]")
    print("-" * 72)
    print(json.dumps({"kasus": len(kasus), "gagal": gagal}, ensure_ascii=False))
    return 1 if gagal else 0


if __name__ == "__main__":
    raise SystemExit(main())
