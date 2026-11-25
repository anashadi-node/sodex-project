"""Test eksekusi maker-first (scripts/sodex_maker_order.py).

Mengapa penting: modul ini memegang JALUR UANG NYATA. Regresi di sini bisa
(a) menjadikan order taker tanpa disadari (biaya 2x) atau
(b) meninggalkan posisi tak terkelola saat exit gagal.

Semua test memakai sodex_fn tiruan — tidak menyentuh venue.
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

import sys as _sys
_spec = importlib.util.spec_from_file_location(
    "sodex_maker_order", Path(__file__).resolve().parents[1] / "scripts" / "sodex_maker_order.py")
m = importlib.util.module_from_spec(_spec)
# WAJIB: @dataclass mencari cls.__module__ di sys.modules saat dekorasi.
_sys.modules["sodex_maker_order"] = m
_spec.loader.exec_module(m)


class PassivePriceTests(unittest.TestCase):
    def test_prices_are_outside_the_touch(self):
        """Bukti venue 30-Sep: GTX tepat di touch bisa hilang -> wajib 1 tick menjauh."""
        buys = m._passive_prices("buy", 83653, 83654)
        sells = m._passive_prices("sell", 83653, 83654)
        for q in buys:
            self.assertLess(q, 83653, "buy wajib DI BAWAH best bid")
        for q in sells:
            self.assertGreater(q, 83654, "sell wajib DI ATAS best ask")

    def test_ladder_is_progressive_outwards(self):
        buys = m._passive_prices("buy", 2711.8, 2712.0)
        self.assertEqual(len(set(buys)), len(buys), "harga wajib unik")
        for a, b in zip(buys, buys[1:]):
            self.assertLess(b, a, "buy: makin ke belakang makin rendah (passif)")

    def test_never_returns_invalid_price(self):
        for side in ("buy", "sell"):
            for q in m._passive_prices(side, 0.0, 0.0):
                self.assertGreater(q, 0)

    def test_price_format_follows_tick(self):
        """Harga WAJIB dibulatkan ke tick venue, kalau tidak venue menolak
        ("price is invalid" — terbukti saat uji GTX 79470,3 pada 30-Sep)."""
        self.assertEqual(m._fmt_price(83653.0), "83653")     # BTC tick=1 -> bulat
        self.assertEqual(m._fmt_price(83653.7), "83654")     # dibulatkan ke tick 1
        self.assertEqual(m._fmt_price(2711.83), "2711.8")    # ETH tick=0,1
        self.assertNotIn(".", m._fmt_price(83653.7))


class _FakeRun:
    def __init__(self, rc=0, out=""):
        self.returncode, self.stdout, self.stderr = rc, out, ""


class MakerFirstTests(unittest.TestCase):
    def _fn_factory(self, place_oid="", executed=0.0, reject_all=False):
        """sodex tiruan: markets -> meta; place -> oid; list -> qty terisi.

        CATATAN: fake ini WAJIB menjawab `markets` karena `place_maker_first`
        memakai symbol-id venue untuk cancel (fail-closed sejak insiden UNI).
        """
        calls = []

        def fn(args):
            calls.append(list(args))
            if "markets" in args:
                return _FakeRun(0, json.dumps([
                    {"name": "BTC-USD", "id": 1, "tickSize": "1",
                     "quantityPrecision": 3}]))
            if "positions" in args:
                # Posisi neto venue = sumber kedua untuk membedakan order yang
                # "hilang karena TERISI" vs "hilang karena batal".
                return _FakeRun(0, json.dumps(
                    [{"symbol": "BTC-USD", "size": str(executed)}] if executed else []))
            if "place" in args:
                if reject_all:
                    return _FakeRun(0, json.dumps({"orderID": 0, "status": ""}))
                return _FakeRun(0, json.dumps({"orderID": place_oid, "status": "NEW"}))
            if "cancel" in args:
                return _FakeRun(0, "canceled")
            if "list" in args:
                if executed > 0 and place_oid:
                    return _FakeRun(0, json.dumps([
                        {"orderID": place_oid, "executedQty": str(executed)}]))
                return _FakeRun(0, json.dumps([]))
            return _FakeRun(0, "")
        fn.calls = calls
        return fn

    def test_uses_gtx_limit_not_market(self):
        """Order PERTAMA yang dikirim WAJIB limit+gtx (maker) — belum market.

        Catatan: `fn.calls[0]` kini pembacaan baseline posisi (sumber kedua),
        jadi yang diperiksa adalah panggilan `place` pertama.
        """
        fn = self._fn_factory(place_oid="111")
        m.place_maker_first(fn, symbol="BTC-USD", side="buy", qty=0.001,
                            best_bid=83653, best_ask=83654,
                            max_wait_s=0.1, poll_s=0.01)
        first = next(c for c in fn.calls if "place" in c)
        self.assertIn("limit", first)
        self.assertIn("gtx", first)
        self.assertNotIn("market", first)

    def test_maker_fill_detected(self):
        fn = self._fn_factory(place_oid="222", executed=0.01)
        r = m.place_maker_first(fn, symbol="BTC-USD", side="buy", qty=0.01,
                                best_bid=83653, best_ask=83654,
                                max_wait_s=0.2, poll_s=0.05)
        self.assertTrue(r.filled)
        self.assertEqual(r.via, "maker")

    def test_falls_back_to_market_when_never_filled(self):
        """GTX tak terisi -> fallback market (taker) supaya posisi tidak nyangkut."""
        fn = self._fn_factory(place_oid="333", executed=0.0)
        r = m.place_maker_first(fn, symbol="BTC-USD", side="buy", qty=0.001,
                                best_bid=83653, best_ask=83654,
                                max_wait_s=0.05, poll_s=0.01)
        self.assertTrue(r.filled)
        self.assertEqual(r.via, "taker_fallback")
        self.assertTrue(any("market" in c for c in fn.calls), "harus ada order market")

    def test_no_fallback_when_disabled(self):
        fn = self._fn_factory(place_oid="444", executed=0.0)
        r = m.place_maker_first(fn, symbol="BTC-USD", side="buy", qty=0.001,
                                best_bid=83653, best_ask=83654,
                                max_wait_s=0.05, poll_s=0.01,
                                allow_taker_fallback=False)
        self.assertFalse(r.filled)
        self.assertEqual(r.via, "skipped")
        self.assertFalse(any("market" in c for c in fn.calls))

    def test_fallback_skipped_when_price_ran_away(self):
        """Jangan mengejar harga: pasar bergerak > toleransi -> entry dibatalkan."""
        fn = self._fn_factory(place_oid="555", executed=0.0)
        r = m.place_maker_first(fn, symbol="BTC-USD", side="buy", qty=0.001,
                                best_bid=83653, best_ask=83654,
                                entry_ref_px=80000.0,        # pasar sudah +4,5%
                                max_slip_pct=0.0015,
                                max_wait_s=0.05, poll_s=0.01)
        self.assertFalse(r.filled)
        self.assertIn("bergerak", r.detail)

    def test_gtx_reject_tries_next_rung_then_skips_cleanly(self):
        """Semua GTX ditolak (mis. reduce-only tak didukung) -> tidak phantom."""
        fn = self._fn_factory(reject_all=True)
        r = m.place_maker_first(fn, symbol="BTC-USD", side="sell", qty=0.001,
                                best_bid=83653, best_ask=83654,
                                max_wait_s=0.05, poll_s=0.01,
                                allow_taker_fallback=False)
        self.assertFalse(r.filled)
        self.assertEqual(r.via, "skipped")

    def test_list_failure_does_not_assume_fill(self):
        """Kalau status tak bisa diverifikasi, JANGAN anggap terisi (pelajaran B9)."""
        def fn(args):
            if "place" in args:
                return _FakeRun(0, json.dumps({"orderID": "777", "status": "NEW"}))
            return _FakeRun(1, "")               # list gagal
        r = m.place_maker_first(fn, symbol="BTC-USD", side="buy", qty=0.001,
                                best_bid=83653, best_ask=83654,
                                max_wait_s=0.05, poll_s=0.01,
                                allow_taker_fallback=False)
        self.assertFalse(r.filled, "verifikasi gagal tidak boleh dianggap terisi")


class VenueMetaTickTests(unittest.TestCase):
    """Tick & presisi qty WAJIB dari venue, bukan tebakan magnitudo.

    Audit 30-Sep-2026: `_tick_of()` menebak tick dari magnitudo harga. Untuk pair
    yang tick resminya berbeda dari tebakan (mis. BNB-USD tick=0,1 sementara
    tebakan memberi 0,01) harga yang dikirim ber-2 desimal → venue menolak
    "price is invalid" dan order HILANG SENYAP (tak ada fill, tak ada error).
    """

    def setUp(self):
        m._VENUE_META_CACHE.clear()

    def _fn(self, rows):
        class R:
            returncode = 0
            stderr = ""
            stdout = json.dumps(rows)

        return lambda args: R()

    def test_tick_taken_from_venue_metadata(self):
        fn = self._fn([{"name": "BNB-USD", "tickSize": "0.1", "pricePrecision": 1,
                        "quantityPrecision": 1}])
        meta = m.fetch_venue_meta("BNB-USD", fn)
        self.assertEqual(meta["tick"], 0.1, "tebakan lama memberi 0.01 -> harga ditolak")
        self.assertEqual(meta["qty_prec"], 1)

    def test_tick_derived_from_price_precision_when_tick_missing(self):
        fn = self._fn([{"name": "ENA-USD", "pricePrecision": 4, "quantityPrecision": 0}])
        meta = m.fetch_venue_meta("ENA-USD", fn)
        self.assertAlmostEqual(meta["tick"], 0.0001)
        self.assertEqual(meta["qty_prec"], 0)

    def test_price_formatted_with_venue_tick_not_guess(self):
        self.assertEqual(m._fmt_price(600.0, 0.1), "600.0")
        self.assertEqual(m._fmt_price(600.0), "600.00", "cadangan: tebakan 0,01")

    def test_passive_prices_use_venue_tick(self):
        self.assertEqual(m._passive_prices("buy", 600.0, 600.1, tick=0.1),
                         [599.9, 599.8, 599.7])

    def test_qty_never_scientific_notation(self):
        self.assertEqual(m._fmt_qty(0.00007, 5), "0.00007")
        self.assertNotIn("e", m._fmt_qty(0.00007, 5).lower())
        self.assertEqual(m._fmt_qty(0.00007), "7e-05", "tanpa metadata: apa adanya")

    def test_meta_empty_and_safe_when_market_list_unreadable(self):
        def boom(args):
            raise RuntimeError("cli down")

        self.assertEqual(m.fetch_venue_meta("BTC-USD", boom), {})
        self.assertIsNone(m.fetch_venue_meta("BTC-USD", boom).get("tick"))

    def test_meta_cached_per_process(self):
        calls = []

        class R:
            returncode = 0
            stderr = ""
            stdout = json.dumps([{"name": "BTC-USD", "tickSize": "1", "quantityPrecision": 5}])

        def fn(args):
            calls.append(args)
            return R()

        m.fetch_venue_meta("BTC-USD", fn)
        m.fetch_venue_meta("BTC-USD", fn)
        self.assertEqual(len(calls), 1, "metadata venue wajib di-cache")


class LadderSafetyTests(unittest.TestCase):
    """INSIDEN UNI 30-Sep-2026 (rugi -$19,055): maker-ladder menggandakan order.

    Akar masalah terverifikasi dari fills venue (4 fill unik dalam 19 detik,
    total 69,2 UNI vs rencana 20,4 = 3,39x):
      1. cancel memakai `--symbol-id 1` HARDCODE (benar hanya untuk BTC-USD;
         UNI-USD id=16) -> cancel GAGAL SENYAP untuk semua simbol lain.
      2. ladder lanjut pasang order baru TANPA verifikasi order lama benar-benar
         hilang -> order lama masih hidup di buku dan ikut terisi.
      3. fallback market mengirim qty PENUH, mengabaikan partial fill maker.
    Kontrak baru: cancel pakai symbol-id venue + konfirmasi hilang; partial fill
    diakumulasi; fallback hanya sisa; cancel tak terkonfirmasi -> ladder berhenti.
    """

    def setUp(self):
        m._VENUE_META_CACHE.clear()

    def _fn(self, *, meta_id=16, executed_by_oid=None, cancel_ok=True,
            order_stays_after_cancel=False):
        """sodex tiruan dengan state orders list + posisi venue yang bisa berubah."""
        executed_by_oid = executed_by_oid or {}
        calls = []
        live = {}          # oid -> order row
        next_oid = [900]
        canceled = set()
        pos = {"size": 0.0}

        def fn(args):
            calls.append(list(args))
            a = list(args)
            if "markets" in a:
                return _FakeRun(0, json.dumps([
                    {"name": "UNI-USD", "id": meta_id, "tickSize": "0.0001",
                     "quantityPrecision": 1}]))
            if "positions" in a:
                return _FakeRun(0, json.dumps(
                    [{"symbol": "UNI-USD", "size": str(pos["size"])}]
                    if pos["size"] else []))
            if "place" in a:
                oid = str(next_oid[0]); next_oid[0] += 1
                ex = float(executed_by_oid.get(oid, 0.0))
                if ex and "market" not in a:
                    pos["size"] += ex            # order ini terisi sebagian/penuh
                live[oid] = {"orderID": oid, "executedQty": str(ex)}
                return _FakeRun(0, json.dumps({"orderID": oid, "status": "NEW"}))
            if "cancel" in a:
                # ambil --order-id dari args
                oid = a[a.index("--order-id") + 1] if "--order-id" in a else ""
                if cancel_ok and not order_stays_after_cancel:
                    live.pop(oid, None)
                    canceled.add(oid)
                    return _FakeRun(0, "canceled")
                return _FakeRun(1, "") if not cancel_ok else _FakeRun(0, "canceled")
            if "list" in a:
                return _FakeRun(0, json.dumps(list(live.values())))
            return _FakeRun(0, "")
        fn.calls = calls
        fn.live = live
        return fn

    def _cancel_calls(self, fn):
        return [c for c in fn.calls if "cancel" in c]

    def _market_calls(self, fn):
        return [c for c in fn.calls if "place" in c and "market" in c]

    def test_cancel_uses_venue_symbol_id_not_hardcode(self):
        """REGRESI AKAR #1: cancel UNI wajib --symbol-id 16, bukan 1."""
        fn = self._fn(meta_id=16)
        m.place_maker_first(fn, symbol="UNI-USD", side="short", qty=20.4,
                            best_bid=8.83, best_ask=8.84,
                            max_wait_s=0.03, poll_s=0.01,
                            allow_taker_fallback=False)
        cancels = self._cancel_calls(fn)
        self.assertTrue(cancels, "ladder harus mencoba cancel tiap rung")
        for c in cancels:
            self.assertEqual(c[c.index("--symbol-id") + 1], "16",
                             f"symbol-id hardcode = akar insiden UNI; calls={c}")

    def test_partial_fill_accumulated_and_fallback_sends_remaining(self):
        """REGRESI AKAR #3: fallback market = qty - filled, bukan qty penuh."""
        fn = self._fn(executed_by_oid={"900": 6.0})   # rung-1 terisi 6 dari 20.4
        r = m.place_maker_first(fn, symbol="UNI-USD", side="short", qty=20.4,
                                best_bid=8.83, best_ask=8.84,
                                max_wait_s=0.03, poll_s=0.01)
        mkts = self._market_calls(fn)
        self.assertTrue(mkts, "harus ada fallback market")
        sent = float(mkts[0][mkts[0].index("--qty") + 1])
        self.assertAlmostEqual(sent, 14.4, places=1,
                               msg=f"fallback wajib SISA (20.4-6.0); terkirim {sent}")

    def test_unconfirmed_cancel_stops_ladder(self):
        """REGRESI AKAR #2: cancel tak terkonfirmasi -> JANGAN pasang rung baru."""
        fn = self._fn(order_stays_after_cancel=True)
        r = m.place_maker_first(fn, symbol="UNI-USD", side="short", qty=20.4,
                                best_bid=8.83, best_ask=8.84,
                                max_wait_s=0.03, poll_s=0.01,
                                allow_taker_fallback=False)
        places = [c for c in fn.calls if "place" in c and "limit" in c]
        self.assertEqual(len(places), 1,
                         f"order lama masih hidup -> rung baru = duplikasi; {len(places)} placed")
        self.assertFalse(r.filled)
        self.assertIn("cancel", r.detail.lower())

    def test_cancel_error_stops_ladder(self):
        fn = self._fn(cancel_ok=False)
        r = m.place_maker_first(fn, symbol="UNI-USD", side="short", qty=20.4,
                                best_bid=8.83, best_ask=8.84,
                                max_wait_s=0.03, poll_s=0.01,
                                allow_taker_fallback=False)
        places = [c for c in fn.calls if "place" in c and "limit" in c]
        self.assertEqual(len(places), 1, "cancel rc!=0 -> ladder wajib berhenti")
        self.assertFalse(r.filled)

    def test_full_maker_fill_no_market_order(self):
        """Kontrak lama tetap: terisi penuh di maker -> tanpa order market."""
        fn = self._fn(executed_by_oid={"900": 20.4})
        r = m.place_maker_first(fn, symbol="UNI-USD", side="short", qty=20.4,
                                best_bid=8.83, best_ask=8.84,
                                max_wait_s=0.03, poll_s=0.01)
        self.assertTrue(r.filled)
        self.assertEqual(r.via, "maker")
        self.assertEqual(self._market_calls(fn), [])


class VanishedOrderTests(unittest.TestCase):
    """CELAH SISA (belum tertutup oleh fix anti-duplikasi): order yang TERISI
    PENUH akan HILANG dari daftar order TERBUKA. Kode pembaca daftar lalu
    menyimpulkan `executedQty=0` = "tidak terisi" — padahal POSISI NYATA ADA.

    Dampak: lane melaporkan entry gagal, state lokal bilang "tanpa posisi"
    sementara venue memegang posisi → divergensi state-vs-venue, kelas yang sama
    dengan insiden UNI 30-Sep-2026 (state 8 vs venue 69,2). Sumber kedua = posisi
    neto venue (`positions --format json`), bukan asumsi.
    """

    def setUp(self):
        m._VENUE_META_CACHE.clear()

    def _fn(self, *, fill_qty=0.0, vanish_instantly=True):
        """Order hilang dari daftar terbuka; posisi venue dijadikan sumber kedua."""
        calls = []
        placed = {"n": 0}
        pos = {"size": 0.0}

        def fn(args):
            calls.append(list(args))
            a = list(args)
            if "markets" in a:
                return _FakeRun(0, json.dumps([
                    {"name": "UNI-USD", "id": 16, "tickSize": "0.0001",
                     "quantityPrecision": 1}]))
            if "positions" in a:
                return _FakeRun(0, json.dumps([
                    {"symbol": "UNI-USD", "size": str(pos["size"])}]))
            if "place" in a:
                placed["n"] += 1
                if "market" in a:
                    pos["size"] += float(a[a.index("--qty") + 1])
                    return _FakeRun(0, json.dumps({"orderID": "999", "status": "FILLED"}))
                if fill_qty:
                    pos["size"] += fill_qty          # pasar menyentuh harga passif kita
                return _FakeRun(0, json.dumps({"orderID": "900", "status": "NEW"}))
            if "list" in a:
                # order TERISI PENUH hilang dari daftar tereduka
                return _FakeRun(0, json.dumps([])) if vanish_instantly else _FakeRun(0, "[]")
            if "cancel" in a:
                return _FakeRun(1, "order not found")   # sudah terisi → tak ada yg dibatalkan
            return _FakeRun(0, "")
        fn.calls = calls
        fn.placed = placed
        return fn

    def _market_calls(self, fn):
        return [c for c in fn.calls if "place" in c and "market" in c]

    def test_vanished_order_confirmed_filled_by_venue_position(self):
        """Order menguap + posisi venue naik penuh -> WAJIB dilaporkan TERISI."""
        fn = self._fn(fill_qty=20.4)
        r = m.place_maker_first(fn, symbol="UNI-USD", side="short", qty=20.4,
                                best_bid=8.83, best_ask=8.84,
                                max_wait_s=0.05, poll_s=0.01)
        self.assertTrue(r.filled,
                        "posisi venue bertambah 20,4 → entry NYATA, bukan 'gagal'")
        self.assertEqual(r.via, "maker")
        self.assertAlmostEqual(r.qty, 20.4, places=2)
        self.assertEqual(self._market_calls(fn), [],
                         "sudah terisi penuh -> tidak boleh ada order market lagi")

    def test_vanished_without_position_move_is_not_a_fill(self):
        """Order menguap tapi posisi TIDAK berubah -> bukan fill; lanjut rung
        berikutnya (dan fallback market tetap hanya sisa)."""
        fn = self._fn(fill_qty=0.0)
        r = m.place_maker_first(fn, symbol="UNI-USD", side="short", qty=20.4,
                                best_bid=8.83, best_ask=8.84,
                                max_wait_s=0.05, poll_s=0.01)
        mkts = self._market_calls(fn)
        self.assertTrue(mkts, "tidak ada fill -> fallback market wajib jalan")
        sent = float(mkts[0][mkts[0].index("--qty") + 1])
        self.assertAlmostEqual(sent, 20.4, places=2,
                               msg=f"tidak ada fill -> kirim qty penuh; terkirim {sent}")


if __name__ == "__main__":
    unittest.main()