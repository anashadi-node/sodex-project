#!/usr/bin/env python3
"""MAKER-FIRST EXECUTION — pasang order LIMIT post-only (GTX) lalu fallback aman.

MENGAPA MODUL INI ADA (audit + approval user 30-Sep-2026):
Lane live memakai `--type market --tif ioc` = TAKER di kedua sisi → biaya round-trip
14,26 bps. Setelah pindah ke MAKER, biaya turun ke ~8,7 bps (hemat 5,6 bps/trade),
dan itulah satu-satunya jalur yang membuat proyeksi menembus target 0,8% (terhitung:
$1,47 → $2,34 dengan notional $175).

BUKTI VENUE (diuji langsung pada venue, 30-Sep-2026):
  • `--tif gtx` DIDUKUNG: order passif (buy 5% di bawah pasar) -> REST, tif=GTX.
    (Komentar lama "GTX tidak didukung" TERBUKTI SALAH.)
  • GTX yang akan MENYEBERANG (buy di atas ask) -> ditolak `orderID=0`.
    Jadi GTX = post-only sungguhan; order tak sengaja menyeberang tidak akan
    menjadi taker diam-diam.

DESAIN RISIKO (penting):
  • ENTRY       : maker-first; bila tak terisi dalam batas waktu -> fallback market
                  HANYA bila harga masih dalam toleransi (tak mengejar harga).
  • TP/TIME     : maker-first (tidak mendesak; biaya lebih penting).
  • SL/KILL     : LANGSUNG market (taker). Keselamatan > biaya; jangan menahan
                  posisi merugi demi menghemat bps.

CATATAN KEJUJURAN: kombinasi GTX + `--reduce-only` BELUM terverifikasi di venue
(tidak ada posisi saat pengujian). Karena itu setiap jalur exit maker WAJIB punya
fallback market; kalau GTX+reduce-only ditolak, eksekusi tetap terjadi (taker).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable, Sequence


@dataclass
class MakerResult:
    filled: bool
    via: str            # "maker" | "taker_fallback" | "skipped"
    oid: str = ""
    price: float = 0.0
    qty: float = 0.0
    detail: str = ""


_VENUE_META_CACHE: dict[str, dict] = {}


def fetch_venue_meta(symbol: str, sodex_fn) -> dict:
    """Metadata RESMI venue untuk 1 simbol: tick harga + presisi qty.

    BUG NYATA (audit 30-Sep-2026): `_tick_of()` MENEBAK tick dari magnitudo harga
    ("BTC tick=1, ETH 0,1, SOL 0,01"). Padahal venue menyediakannya di
    `markets perps` (tickSize/pricePrecision/quantityPrecision). Menebak = bug
    yang menunggu waktu: mis. BNB-USD tick venue 0,1 sementara tebakan memberi
    0,01 → harga 2 desimal dikirim → venue menolak "price is invalid" dan order
    hilang SENYAP (tak ada fill, tak ada error yang terbaca). qty kecil juga
    rawan terkirim sebagai notasi ilmiah Python ("7e-05") yang bukan angka valid
    bagi venue.
    """
    if symbol in _VENUE_META_CACHE:
        return _VENUE_META_CACHE[symbol]
    meta: dict = {}
    try:
        r = sodex_fn(["markets", "perps", "--format", "json"])
        rows = json.loads(getattr(r, "stdout", "") or "")
        rows = rows if isinstance(rows, list) else (rows.get("data") or [])
        for row in rows:
            if str(row.get("name")) != str(symbol):
                continue
            ts = row.get("tickSize")
            pp = row.get("pricePrecision")
            meta["tick"] = float(ts) if ts else (10.0 ** (-int(pp)) if pp is not None else None)
            qp = row.get("quantityPrecision")
            meta["qty_prec"] = int(qp) if qp is not None else None
            sid = row.get("id")
            meta["symbol_id"] = str(sid) if sid is not None else None
            break
    except Exception:  # noqa: BLE001
        meta = {}
    _VENUE_META_CACHE[symbol] = meta
    return meta


def _tick_of(px: float) -> float:
    """CADANGAN saja: tebak tick dari magnitudo harga.

    Hanya dipakai bila metadata venue tak terbaca (lihat fetch_venue_meta).
    """
    for lo, tick in ((10_000, 1.0), (1_000, 0.1), (100, 0.01), (1, 0.001)):
        if px >= lo:
            return tick
    return 0.0001


def _fmt_qty(qty: float, prec: int | None = None) -> str:
    """Format qty sesuai presisi venue — cegah notasi ilmiah ("7e-05")."""
    if prec is None:
        return str(qty)
    return f"{round(float(qty), int(prec)):.{int(prec)}f}"


def _passive_prices(side: str, best_bid: float, best_ask: float,
                    n_steps: int = 3, tick: float | None = None) -> list[float]:
    """Tangga harga passif, SEMUA di LUAR touch (aman dari reject/hilang).

    BUKTI VENUE (30-Sep-2026, perps GTX):
      • GTX yang MENYEBERANG (buy di atas ask) -> ditolak orderID=0 (post-only benar).
      • GTX BUY TEPAT di best bid -> dilaporkan rest, lalu HILANG dari daftar.
      • GTX SELL TEPAT di best ask -> bertahan (NEW).
    Karena itu harga dummy dipasang MINIMAL 1 tick menjauh dari touch:
      buy  : best_bid - k*tick   (k = 1,2,3)
      sell : best_ask + k*tick
    Trade-off yang disadari: antrean lebih belakang → fill bisa lebih lambat.
    Untuk lane SWING (1-30 jam) itu dapat diterima; yang WAJIB dihindari adalah
    terisi sebagai TAKER karena itu memakan seluruh keunggulan biaya.

    `tick`: tick RESMI venue bila tersedia (fetch_venue_meta); None = cadangan.
    """
    tick = float(tick) if tick else _tick_of(best_ask or best_bid)
    out: list[float] = []
    for k in (1, 2, 3)[:max(1, n_steps)]:
        px = (best_bid - k * tick) if side == "buy" else (best_ask + k * tick)
        if px > 0:
            out.append(round(px, 10))
    return out


def _fmt_price(px: float, tick: float | None = None) -> str:
    """Format harga sesuai tick venue.

    `tick` = tick RESMI venue (fetch_venue_meta); None → cadangan tebakan magnitudo.
    """
    tick = float(tick) if tick else _tick_of(px)
    if tick >= 1:
        return str(int(round(px)))
    dec = max(0, len(f"{tick:.10f}".rstrip("0").split(".")[-1]))
    return f"{px:.{dec}f}"


def place_maker_first(sodex_fn: Callable[[Sequence[str]], object], *,
                      symbol: str, side: str, qty: float,
                      best_bid: float, best_ask: float,
                      reduce_only: bool = False,
                      max_wait_s: float = 12.0, poll_s: float = 1.5,
                      entry_ref_px: float | None = None,
                      max_slip_pct: float = 0.0015,
                      allow_taker_fallback: bool = True) -> MakerResult:
    """Coba maker (GTX) dulu; fallback market bila perlu & aman.

    `sodex_fn(args)` harus mengembalikan objek dengan `.returncode`, `.stdout`.
    `entry_ref_px`: harga referensi saat keputusan (utk cek slippage fallback).
    """
    # Metadata RESMI venue (tick harga + presisi qty) — bukan tebakan magnitudo.
    _meta = fetch_venue_meta(symbol, sodex_fn)
    _tick = _meta.get("tick")
    prices = _passive_prices(side, best_bid, best_ask, tick=_tick)
    if not prices:
        return MakerResult(False, "skipped", detail="harga buku tidak valid")

    def _run(args):
        try:
            return sodex_fn(args)
        except Exception as e:  # noqa: BLE001
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": str(e)})()

    def _oid(out: str) -> str:
        try:
            d = json.loads(out) if out.strip().startswith("{") else None
        except Exception:
            d = None
        if isinstance(d, dict):
            v = d.get("orderID") or d.get("orderId") or d.get("id")
            return str(v) if v not in (None, 0, "0", "") else ""
        # CLI mode "pretty": orderID=<n>
        import re
        m = re.search(r"orderID[=:\s]+(\d+)", str(out))
        return m.group(1) if m and m.group(1) != "0" else ""

    def _orders_rows() -> list | None:
        """Daftar order hidup di venue, atau None bila TAK BISA diverifikasi.

        Fail-closed: None berarti "tidak tahu" — pemanggil wajib berhenti,
        bukan mengasumsikan order sudah hilang.
        """
        r = _run(["orders", "list", "perps", "--format", "json"])
        if getattr(r, "returncode", 1) != 0:
            return None
        try:
            rows = json.loads(r.stdout or "[]")
        except Exception:
            return None
        return rows if isinstance(rows, list) else None

    def _filled_qty(oid: str) -> float:
        rows = _orders_rows()
        if rows is None:
            return -1.0
        for row in rows:
            if str(row.get("orderID")) == str(oid):
                try:
                    return float(row.get("executedQty") or 0)
                except Exception:
                    return -1.0
        return 0.0      # order hilang dari list → anggap tak terisi (B9: jangan phantom)

    def _order_still_live(oid: str) -> bool | None:
        """True = masih hidup, False = hilang, None = tak bisa diverifikasi."""
        rows = _orders_rows()
        if rows is None:
            return None
        return any(str(row.get("orderID")) == str(oid) for row in rows)

    _symbol_id = _meta.get("symbol_id")
    _qty_prec = _meta.get("qty_prec")

    # ── Sumber kedua: POSISI NETO venue ──────────────────────────────────────
    # `orders list` HANYA memuat order TERBUKA: order yang terisi penuh HILANG
    # dari daftar. Membaca hilang = "executedQty 0" = "tak terisi" adalah
    # phantom-unfilled → rung berikutnya dipasang lagi (kelas insiden UNI).
    # Sumber kedua = posisi neto venue; field resmi `symbol` + `size` (sama
    # dengan scripts/sodex_realtime_sync.real_perps_positions()).
    def _pos_net() -> float | None:
        r = _run(["positions", "--format", "json"])
        if getattr(r, "returncode", 1) != 0:
            return None
        raw = getattr(r, "stdout", "") or ""
        if not raw.strip():
            return None                       # kosong = TAK TERBACA (bukan nol)
        try:
            rows = json.loads(raw)
        except Exception:  # noqa: BLE001
            return None
        if rows is None:                      # CLI mencetak null saat flat
            return 0.0
        if not isinstance(rows, list):
            return None
        for row in rows:
            if not isinstance(row, dict) or str(row.get("symbol")) != str(symbol):
                continue
            try:
                return float(row.get("size") or 0)
            except Exception:  # noqa: BLE001
                return None
        return 0.0

    def _pos_move() -> float | None:
        """Fill KUMULATIF sejak awal menurut posisi venue. None = tak terbaca.

        Memakai MAGNITUDO perubahan neto, tanpa berasumsi konvensi tanda `size`
        (venue bisa melaporkan short sebagai negatif atau positif+side). Yang
        dibutuhkan hanya "berapa besar eksposur berubah", bukan arahnya.
        """
        cur = _pos_net()
        if cur is None or _pos0 is None:
            return None
        return abs(cur - _pos0)

    _pos0 = _pos_net()

    # Tanpa symbol-id venue kita TIDAK bisa membatalkan order dengan aman
    # (insiden UNI: cancel gagal senyap → order ganda). Maka: bila metadata
    # venue tak terbaca, JANGAN pasang order maker sama sekali — langsung ke
    # jalur fallback taker. Dua hal terjaga sekaligus: (a) tidak ada order
    # yatim yang tak bisa dibatalkan, (b) lane yang butuh eksekusi tetap jalan
    # (entry tidak diblokir hanya karena CLI meta sedang tak terbaca).
    _can_use_maker = bool(_symbol_id)

    last_oid = ""
    filled_total = 0.0
    for i, px in enumerate(prices if _can_use_maker else []):
        remaining = qty - filled_total
        if remaining <= max(qty * 1e-9, 1e-12):
            break                            # sudah terisi penuh — jangan tambah
        args = ["orders", "place", "perps", "--symbol", symbol, "--side", side,
                "--price", _fmt_price(px, _tick),
                "--qty", _fmt_qty(remaining, _qty_prec),
                "--type", "limit", "--tif", "gtx", "--format", "json"]
        if reduce_only:
            args.append("--reduce-only")
        r = _run(args)
        oid = _oid(getattr(r, "stdout", "") or "")
        if not oid:
            # GTX ditolak (akan menyeberang, saldo kurang, reduce-only tak didukung)
            continue
        last_oid = oid
        waited = 0.0
        fq_last = 0.0
        gone_unfilled = False
        while waited < max_wait_s:
            fq = _filled_qty(oid)
            if fq < 0:
                fq_last = -1.0
                break                        # tak bisa verifikasi → jangan asumsi
            if fq == 0.0 and _order_still_live(oid) is False:
                # Order HILANG dari daftar order TERBUKA, padahal kita BELUM
                # pernah mengirim cancel untuk oid ini → sebab paling mungkin =
                # TERISI PENUH (order terisi keluar dari daftar terbuka).
                # Cek sumber kedua sebelum menyimpulkan apa pun.
                moved = _pos_move()
                if moved is None:
                    # Fail-closed ke arah EKSPOSUR: posisi nyata tak terlacak
                    # adalah kelas kerugian insiden UNI. Laporkan TERISI, jangan
                    # laporkan kosong; pemanggil tetap wajib verifikasi posisi.
                    return MakerResult(True, "maker", oid=oid, price=px, qty=qty,
                                       detail="order hilang dari daftar & posisi tak "
                                              "terverifikasi — dilaporkan TERISI "
                                              "(fail-closed terhadap eksposur)")
                if moved >= qty * 0.999:
                    return MakerResult(True, "maker", oid=oid, price=px, qty=moved)
                if moved > 0:
                    filled_total = max(filled_total, moved)   # kumulatif
                else:
                    gone_unfilled = True                      # benar-benar tak terisi
                break
            fq_last = fq
            if filled_total + fq >= qty * 0.999:
                return MakerResult(True, "maker", oid=oid, price=px,
                                   qty=filled_total + fq)
            time.sleep(poll_s); waited += poll_s
        if fq_last < 0:
            return MakerResult(False, "skipped", oid=last_oid,
                               detail="status order tak terverifikasi — ladder berhenti "
                                      "(cegah order ganda)")
        if gone_unfilled:
            # Order sudah tidak ada di venue → tidak ada yang perlu dibatalkan.
            # TIDAK boleh memanggil cancel (akan rc!=0 dan menghentikan ladder
            # untuk alasan yang salah); lanjut ke rung berikutnya dengan sisa qty.
            continue
        if fq_last > 0:
            filled_total += fq_last          # akumulasi partial fill antar-rung

        # ── batalkan SISA rung, LALU pastikan order benar-benar hilang ──────
        # INSIDEN UNI 30-Sep-2026 (rugi -$19,055): cancel memakai `--symbol-id 1`
        # HARDCODE (benar hanya BTC-USD; UNI-USD id=16) → cancel GAGAL SENYAP →
        # order lama tetap hidup sementara rung baru dipasang → 4 fill unik,
        # 69,2 UNI vs rencana 20,4 (3,39x). Cancel WAJIB pakai id venue, dan
        # ladder WAJIB berhenti bila cancel tak terkonfirmasi.
        if not _symbol_id:
            return MakerResult(False, "skipped", oid=last_oid,
                               detail="symbol-id venue tak tersedia — cancel tak aman, "
                                      "ladder berhenti (cegah order ganda)")
        cr = _run(["orders", "cancel", "perps", "--symbol-id", str(_symbol_id),
                   "--order-id", str(oid)])
        if getattr(cr, "returncode", 1) != 0:
            # Cancel gagal. Bisa berarti (a) order sudah terisi tepat sebelum
            # cancel landing, atau (b) order masih hidup. Sumber kedua menentukan.
            moved = _pos_move()
            if moved is not None:
                filled_total = max(filled_total, moved)
                if filled_total >= qty * 0.999:
                    return MakerResult(True, "maker", oid=oid, price=px,
                                       qty=filled_total)
            return MakerResult(False, "skipped", oid=last_oid, qty=filled_total,
                               detail=f"cancel rc!=0 — order {oid} mungkin masih hidup, "
                                      "ladder berhenti (cegah duplikasi)")
        still = _order_still_live(oid)
        if still is not False:               # True = masih hidup, None = tak terverifikasi
            return MakerResult(False, "skipped", oid=last_oid,
                               detail=f"cancel tak terkonfirmasi (order {oid} "
                                      f"{'masih hidup' if still else 'tak terverifikasi'}) — "
                                      "ladder berhenti (cegah duplikasi)")

    # ── fallback market (taker) — HANYA SISA yang belum terisi ───────────────
    # Bug #3 (insiden UNI): fallback mengirim qty PENUH dan mengabaikan partial
    # fill maker → total posisi melebihi rencana. Kirim sisa saja.
    remaining = qty - filled_total
    if remaining <= max(qty * 1e-9, 1e-12):
        return MakerResult(True, "maker", oid=last_oid, price=0.0, qty=filled_total,
                           detail="terisi penuh oleh maker")
    if not allow_taker_fallback:
        return MakerResult(False, "skipped", oid=last_oid,
                           detail="maker gagal & fallback dimatikan")
    if entry_ref_px and entry_ref_px > 0:
        # jangan mengejar harga: kalau pasar sudah lari melebihi toleransi → skip
        cur = best_ask if side == "buy" else best_bid
        drift = abs(cur - entry_ref_px) / entry_ref_px
        if drift > max_slip_pct:
            return MakerResult(False, "skipped", oid=last_oid,qty=filled_total,
                               detail=f"pasar bergerak {drift*100:.3f}% > toleransi "
                                      f"{max_slip_pct*100:.2f}% — entry dibatalkan")
    args = ["orders", "place", "perps", "--symbol", symbol, "--side", side,
            "--type", "market", "--tif", "ioc",
            "--qty", _fmt_qty(remaining, _qty_prec)]
    if reduce_only:
        args.append("--reduce-only")
    r = _run(args)
    oid = _oid(getattr(r, "stdout", "") or "")
    if not oid:
        return MakerResult(False, "skipped", oid=last_oid, qty=filled_total,
                           detail="market fallback ditolak (oid=0)")
    return MakerResult(True, "taker_fallback", oid=oid,
                       price=(best_ask if side == "buy" else best_bid),
                       qty=filled_total + remaining)


if __name__ == "__main__":
    print("tangga harga passif (contoh bid=83653 ask=83654, BTC):")
    for s in ("buy", "sell"):
        print(f"  {s}: {_passive_prices(s, 83653, 83654)}")
    print("tangga ETH (bid=2711.8 ask=2712.0):")
    for s in ("buy", "sell"):
        print(f"  {s}: {_passive_prices(s, 2711.8, 2712.0)}")