"""Test lane spot live-test (scripts/sodex_spot_live_test.py).

BUG NYATA 29-Sep-2026 (uang nyata): verifikasi fill mencari nama coin 'LINK' di
/balance yang berisi 'vLINK' → selalu 0.0 → 7.407 baris "NO_FILL" palsu padahal
order NYATA terisi di venue. Akibat lanjutan: tidak ada posisi yang tercatat →
TP/SL/time-stop tidak pernah mengelola inventori nyata (aset menumpuk diam-diam).

Test ini memaku kontrak mapping nama coin supaya regresi itu tidak kembali.
"""
from __future__ import annotations

import contextlib
import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "sodex_spot_live_test", ROOT / "scripts" / "sodex_spot_live_test.py")
lane = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lane)

# --- ISOLASI ARTEFAK (audit 30-Sep-2026) -------------------------------------
# TANPA ini, tiap tes yang memanggil lane.cycle() menulis ke artefak PRODUKSI
# uang nyata: data/spot_live_test.jsonl + data/spot_live_test_state.json.
# Terukur: 50 dari 65 baris di log live adalah fixture pytest (entry_p=100.0,
# clOrdID=x/y, orderID=123/456) ≈ $1,35 PnL palsu + 9 TP palsu di log lane nyata.
_TMP_DIR = None
_PATCHERS: list = []


def setUpModule():
    global _TMP_DIR
    _TMP_DIR = tempfile.TemporaryDirectory(prefix="spot-lane-test-")
    for name, fname in (("STATE", "state.json"), ("LOG", "log.jsonl"),
                        ("KILL", "KILL")):
        p = mock.patch.object(lane, name, Path(_TMP_DIR.name) / fname)
        p.start()
        _PATCHERS.append(p)


def tearDownModule():
    for p in reversed(_PATCHERS):
        p.stop()
    _PATCHERS.clear()
    if _TMP_DIR:
        _TMP_DIR.cleanup()


class CoinMappingTests(unittest.TestCase):
    def test_vcoin_keeps_venue_prefix(self):
        """Saldo venue memakai prefix 'v' — inilah yang harus dicek di /balance."""
        self.assertEqual(lane.vcoin_of("vLINK_vUSDC"), "vLINK")
        self.assertEqual(lane.vcoin_of("vBTC_vUSDC"), "vBTC")

    def test_coin_is_logical_name_without_prefix(self):
        self.assertEqual(lane.coin_from_vsym("vLINK_vUSDC"), "LINK")
        self.assertEqual(lane.coin_from_vsym("vETH_vUSDC"), "ETH")

    def test_spot_holdings_finds_prefixed_balance_row(self):
        """Kontrak inti: cari 'vLINK' → ketemu; cari 'LINK' → 0.0 (bug lama)."""
        payload = ('[{"id":1,"coin":"vLINK","total":"0.0993825","locked":"0"},'
                   '{"id":2,"coin":"vUSDC","total":"23.1","locked":"0"}]')

        class R:
            returncode = 0
            stdout = payload
            stderr = ""

        with mock.patch.object(lane, "sodex", return_value=R()):
            self.assertAlmostEqual(lane.spot_holdings("vLINK"), 0.0993825)
            self.assertEqual(lane.spot_holdings("LINK"), 0.0,
                             "nama tanpa prefix TIDAK ada di saldo venue (bug lama)")

    def test_spot_holdings_returns_none_when_api_fails(self):
        """None HARUS berarti gagal verifikasi, bukan 'tidak dipegang'."""
        class R:
            returncode = 1
            stdout = ""
            stderr = "error"

        with mock.patch.object(lane, "sodex", return_value=R()):
            self.assertIsNone(lane.spot_holdings("vLINK"))


class EntryVerificationTests(unittest.TestCase):
    """Verifikasi entry memakai saldo venue + mencatat oid, bukan NO_FILL buta."""

    def _state(self):
        return {"created": "2026-09-23T00:00:00+00:00", "open": {}, "closed": [],
                "last_entry": {}, "session_pnl": 0.0, "day": "", "trades_today": 0}

    def test_entry_records_position_when_balance_shows_fill(self):
        st = self._state()
        with mock.patch.object(lane.PT, "get_liquid_pairs", return_value={"vLINK_vUSDC": 1e6}), \
             mock.patch.object(lane.PT, "btc_regime_ok", return_value=True), \
             mock.patch.object(lane.PT, "SPOT_TO_BN", {"vLINK_vUSDC": "LINKUSDT"}), \
             mock.patch.object(lane.PT, "fetch_klines", return_value=([1.0] * 50, [1.0] * 50, [1.0] * 50)), \
             mock.patch.object(lane.PT, "check_signal_combined", return_value=True), \
             mock.patch.object(lane, "spot_top", return_value=(25.4, 25.5)), \
             mock.patch.object(lane, "place_buy", return_value={"rc": 0, "out": "placed orderID=123"}), \
             mock.patch.object(lane, "spot_holdings", side_effect=[0.0, 0.2]), \
             mock.patch.object(lane, "live_entry_reconciled", return_value=(True, "match")), \
             mock.patch.object(lane.time, "sleep", return_value=None), \
             mock.patch.object(lane, "SIZE_USD", 5.0):
            out = lane.cycle(st, live=True)
        self.assertIn("LINK", st["open"], f"posisi harus tercatat; out={out}")
        self.assertEqual(st["open"]["LINK"]["qty"], 0.2)

    def test_entry_not_recorded_when_balance_unchanged(self):
        st = self._state()
        with mock.patch.object(lane.PT, "get_liquid_pairs", return_value={"vLINK_vUSDC": 1e6}), \
             mock.patch.object(lane.PT, "btc_regime_ok", return_value=True), \
             mock.patch.object(lane.PT, "SPOT_TO_BN", {"vLINK_vUSDC": "LINKUSDT"}), \
             mock.patch.object(lane.PT, "fetch_klines", return_value=([1.0] * 50, [1.0] * 50, [1.0] * 50)), \
             mock.patch.object(lane.PT, "check_signal_combined", return_value=True), \
             mock.patch.object(lane, "spot_top", return_value=(25.4, 25.5)), \
             mock.patch.object(lane, "place_buy", return_value={"rc": 0, "out": "placed orderID=0"}), \
             mock.patch.object(lane, "spot_holdings", return_value=0.0), \
             mock.patch.object(lane, "live_entry_reconciled", return_value=(True, "match")), \
             mock.patch.object(lane.time, "sleep", return_value=None), \
             mock.patch.object(lane, "SIZE_USD", 5.0):
            out = lane.cycle(st, live=True)
        self.assertEqual(st["open"], {}, f"tanpa fill riil jangan catat posisi; out={out}")
        self.assertTrue(any("oid0=True" in str(x) for x in out),
                        f"orderID=0 wajib terlihat di log; out={out}")


class FillDeltaVerificationTests(unittest.TestCase):
    """AUDIT 30-Sep-2026: bukti fill = DELTA saldo venue, BUKAN LEVEL saldo.

    Bug lama: penjaga hanya membandingkan level (`held < qty*0.5`). Bila coin
    sudah dipegang (sisa fill lama / inventori manual), order yang GAGAL tetap
    lolos penjaga -> ENTRY palsu tercatat, counter cap tidak naik, loop
    mengulang tiap siklus. Terukur: 14 ENTRY palsu (LINK @25.5) sementara saldo
    venue tidak berubah sama sekali.
    """

    def _state(self, open_pos=None):
        return {"open": dict(open_pos or {}), "closed": [], "session_pnl": 0.0,
                "day": datetime.now(timezone.utc).strftime("%Y%m%d"), "trades_today": 0}

    def _entry_mocks(self):
        return [
            mock.patch.object(lane.PT, "get_liquid_pairs", return_value={"vLINK_vUSDC": 1e6}),
            mock.patch.object(lane.PT, "btc_regime_ok", return_value=True),
            mock.patch.object(lane.PT, "SPOT_TO_BN", {"vLINK_vUSDC": "LINKUSDT"}),
            mock.patch.object(lane.PT, "fetch_klines",
                              return_value=([1.0] * 50, [1.0] * 50, [1.0] * 50)),
            mock.patch.object(lane.PT, "check_signal_combined", return_value=True),
            mock.patch.object(lane, "spot_top", return_value=(25.4, 25.5)),
            mock.patch.object(lane, "place_buy",
                              return_value={"rc": 0, "out": "placed  clOrdID=x  orderID=123  status=filled"}),
            mock.patch.object(lane, "live_entry_reconciled", return_value=(True, "match")),
            mock.patch.object(lane.time, "sleep", return_value=None),
            mock.patch.object(lane, "SIZE_USD", 5.0),
        ]

    def test_entry_rejected_when_balance_already_held_no_delta(self):
        """REGRESI INTI: saldo sudah 0.2 dan TIDAK berubah -> jangan catat ENTRY."""
        st = self._state()
        with contextlib.ExitStack() as stack:
            for m in self._entry_mocks():
                stack.enter_context(m)
            stack.enter_context(mock.patch.object(lane, "spot_holdings",
                                                 side_effect=[0.2, 0.2]))
            out = lane.cycle(st, live=True)
        self.assertEqual(st["open"], {}, f"delta nol = tidak ada fill; out={out}")
        self.assertEqual(st["trades_today"], 0, "counter cap tidak boleh naik tanpa fill")
        self.assertTrue(any("delta=0.0" in str(x) for x in out),
                        f"delta wajib terlihat di log; out={out}")

    def test_entry_accepted_on_real_delta(self):
        """Kontrol positif: saldo NAIK 0.2 -> ENTRY dicatat + delta terekam."""
        st = self._state()
        with contextlib.ExitStack() as stack:
            for m in self._entry_mocks():
                stack.enter_context(m)
            stack.enter_context(mock.patch.object(lane, "spot_holdings",
                                                 side_effect=[0.0, 0.2]))
            out = lane.cycle(st, live=True)
        self.assertIn("LINK", st["open"], f"delta nyata wajib dicatat; out={out}")
        self.assertEqual(st["open"]["LINK"]["fill_delta"], 0.2)
        self.assertEqual(st["trades_today"], 1)

    def _sell_mocks(self):
        return [
            mock.patch.object(lane.PT, "get_liquid_pairs", return_value={}),
            mock.patch.object(lane, "spot_top", return_value=(103.0, 103.5)),
            mock.patch.object(lane, "place_sell",
                              return_value={"rc": 0, "out": "placed  clOrdID=y  orderID=456  status=filled"}),
            mock.patch.object(lane, "live_entry_reconciled", return_value=(True, "match")),
            mock.patch.object(lane.time, "sleep", return_value=None),
            mock.patch.object(lane, "SIZE_USD", 5.0),
        ]

    def _open_link(self):
        return {"LINK": {"coin": "LINK", "vsym": "vLINK_vUSDC", "entry_p": 100.0, "qty": 0.2,
                         "size_usd": 5.0,
                         "entry_iso": datetime.now(timezone.utc).isoformat(),
                         "regime_on": True, "buy": {"rc": 0, "out": "x"}}}

    def test_sell_rejected_when_balance_unchanged(self):
        """Exit tanpa bukti fill -> posisi DIPERTAHANKAN, PnL TIDAK dibukukan."""
        st = self._state(self._open_link())
        with contextlib.ExitStack() as stack:
            for m in self._sell_mocks():
                stack.enter_context(m)
            stack.enter_context(mock.patch.object(lane, "spot_holdings",
                                                 side_effect=[0.2, 0.2]))
            out = lane.cycle(st, live=True)
        self.assertIn("LINK", st["open"], f"posisi wajib dipertahankan; out={out}")
        self.assertEqual(st["closed"], [], "jangan catat close tanpa bukti fill")
        self.assertEqual(st["session_pnl"], 0.0, "jangan bukukan PnL tanpa bukti fill")
        self.assertTrue(any("SELL_NO_FILL" in str(x) for x in out), f"out={out}")

    def test_sell_accepted_on_real_delta(self):
        """Kontrol positif: saldo TURUN 0.2 -> posisi ditutup + PnL dibukukan."""
        st = self._state(self._open_link())
        with contextlib.ExitStack() as stack:
            for m in self._sell_mocks():
                stack.enter_context(m)
            stack.enter_context(mock.patch.object(lane, "spot_holdings",
                                                 side_effect=[0.2, 0.0]))
            out = lane.cycle(st, live=True)
        self.assertEqual(st["open"], {}, f"posisi wajib ditutup; out={out}")
        self.assertEqual(len(st["closed"]), 1)
        self.assertGreater(st["session_pnl"], 0.0)


class VenuePrecisionTests(unittest.TestCase):
    """AUDIT 30-Sep-2026: 'sodex API error (code -1): price is invalid'.

    Skrip mengirim `round(ask*1.001, 6)` (6 desimal) padahal venue memakai tick
    tetap (pricePrecision=2 / tickSize=0.01) → SEMUA order ditolak (rc=1) dan
    stdout kosong → 7.482 log NO_FILL tanpa sebab. Qty kecil juga terkirim
    sebagai notasi ilmiah Python ("7e-05") yang bukan angka valid venue.
    """

    def tearDown(self):
        lane._VENUE_META_CACHE.clear()

    def test_price_rounded_to_venue_precision(self):
        with mock.patch.object(lane, "venue_meta",
                               return_value={"pricePrecision": 2, "quantityPrecision": 3}):
            p, q = lane.venue_fmt("vLINK_vUSDC", 14.369, 0.196)
        self.assertEqual(p, "14.37", "harga 6 desimal DITOLAK venue (bug lama)")
        self.assertEqual(q, "0.196")

    def test_small_qty_never_scientific_notation(self):
        with mock.patch.object(lane, "venue_meta",
                               return_value={"pricePrecision": 2, "quantityPrecision": 5}):
            _p, q = lane.venue_fmt("vBTC_vUSDC", 100000.0, 0.00007)
        self.assertNotIn("e", q.lower(), f"notasi ilmiah bukan angka valid: {q}")
        self.assertEqual(q, "0.00007")

    def test_meta_defaults_when_market_list_unavailable(self):
        class R:
            returncode = 1
            stdout = ""
            stderr = "err"

        lane._VENUE_META_CACHE.clear()
        with mock.patch.object(lane, "sodex", return_value=R()):
            meta = lane.venue_meta("vXXX_vUSDC")
        self.assertEqual(meta, {}, "gagal ambil metadata -> fallback, jangan crash")

    def test_live_order_sends_venue_precision_price(self):
        """place_buy live WAJIB mengirim harga ber-presisi venue."""
        captured = {}

        class R:
            returncode = 0
            stdout = "placed  clOrdID=x  orderID=1  status=filled"
            stderr = ""

        def fake_sodex(args, timeout=25):
            captured["args"] = list(args)
            return R()

        with mock.patch.object(lane, "venue_meta",
                               return_value={"pricePrecision": 2, "quantityPrecision": 3}), \
             mock.patch.object(lane, "sodex", side_effect=fake_sodex):
            res = lane.place_buy("vLINK_vUSDC", 0.196, 14.369, True)
        args = captured["args"]
        self.assertEqual(args[args.index("--price") + 1], "14.37")
        self.assertEqual(args[args.index("--qty") + 1], "0.196")
        self.assertEqual(res["sent_price"], "14.37")


if __name__ == "__main__":
    unittest.main()