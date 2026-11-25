"""Test lane PERPS SHORT LIVE (scripts/sodex_perps_short_live_test.py).

Audit 30-Sep-2026. Dua kelas bug pada jalur uang nyata:
  1. Harga dikirim 6 desimal (`round(bid*0.999, 6)`) padahal venue perps memakai
     tick tetap -> "price is invalid" -> order hilang SENYAP. Terukur pada pair
     nyata: BTC-USD 83013.123456, ETH-USD 2712.345, SOL-USD 205.678 — SEMUA
     bukan kelipatan tick venue.
  2. Bukti fill memakai LEVEL posisi (`abs(held) < qty*0.5`) bukan DELTA ->
     order yang GAGAL tetap lolos bila sudah ada posisi sisa -> ENTRY palsu,
     counter cap tidak naik, order dikirim ulang tiap siklus.

Catatan: lane ini DISABLED secara permanen (sinyal short belum tervalidasi),
jadi test ini menjaga kode tetap benar bila suatu saat dihidupkan kembali.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_spec = importlib.util.spec_from_file_location(
    "psl", Path(__file__).resolve().parents[1] / "scripts" / "sodex_perps_short_live_test.py")
m = importlib.util.module_from_spec(_spec)
sys.modules["psl"] = m
_spec.loader.exec_module(m)


class VenueFmtTests(unittest.TestCase):
    """Harga/qty wajib mengikuti presisi RESMI venue, bukan 6 desimal asal."""

    def _meta(self, tick, qp):
        import sodex_maker_order
        return mock.patch.object(sodex_maker_order, "fetch_venue_meta",
                                 return_value={"tick": tick, "qty_prec": qp})

    def test_btc_price_becomes_integer_per_venue_tick(self):
        with self._meta(1.0, 5):
            p, q = m.venue_fmt("BTC-USD", 83013.123456, 0.00169)
        self.assertEqual(p, "83013", "tick BTC=1 -> bilangan bulat")
        self.assertEqual(q, "0.00169")

    def test_eth_price_rounded_to_venue_tick(self):
        with self._meta(0.1, 4):
            p, _ = m.venue_fmt("ETH-USD", 2712.345, 0.0022)
        self.assertEqual(p, "2712.3", "6 desimal = bukan kelipatan tick 0,1")

    def test_sol_price_rounded_to_venue_tick(self):
        with self._meta(0.01, 3):
            p, _ = m.venue_fmt("SOL-USD", 205.678, 0.05)
        self.assertEqual(p, "205.68")

    def test_qty_never_scientific_notation(self):
        with self._meta(1.0, 5):
            _, q = m.venue_fmt("BTC-USD", 83013.0, 0.00007)
        self.assertEqual(q, "0.00007")
        self.assertNotIn("e", q.lower(), "'7e-05' bukan angka valid bagi venue")

    def test_fallback_when_venue_meta_unavailable(self):
        with self._meta(None, None):
            p, q = m.venue_fmt("BTC-USD", 83013.123456, 0.00169)
        self.assertEqual(p, "83013.123456", "tanpa metadata: apa adanya, jangan crash")
        self.assertEqual(q, "0.00169")

    def test_order_records_rc_and_stderr(self):
        class R:
            returncode = 1
            stdout = ""
            stderr = "price is invalid"

        with self._meta(0.1, 4), mock.patch.object(m, "sodex", return_value=R()):
            res = m.order("ETH-USD", "sell", 0.0022, 2712.345, live=True)
        self.assertEqual(res["rc"], 1, "rc venue wajib terekam")
        self.assertIn("price is invalid", res["err"], "sebab kegagalan wajib terbaca")


class EntryFillDeltaTests(unittest.TestCase):
    """Bukti fill = DELTA posisi, BUKAN LEVEL."""

    def setUp(self):
        import sodex_maker_order
        p = mock.patch.object(sodex_maker_order, "fetch_venue_meta",
                              return_value={"tick": 0.01, "qty_prec": 3})
        p.start()
        self.addCleanup(p.stop)
        self.tmp = Path(tempfile.mkdtemp()) / "perps_short_test.jsonl"

    def _run(self, positions):
        st = {"open": {}, "closed": [], "session_pnl": 0.0, "day": "", "trades_today": 0}
        with mock.patch.object(m, "KILL", Path("/nonexistent/PERPS_SHORT_KILL")), \
             mock.patch.object(m, "LOG", self.tmp), \
             mock.patch.object(m, "perps_margin", return_value=50.0), \
             mock.patch.object(m, "get_intel", return_value=(40.0, "risk_off")), \
             mock.patch.object(m, "get_reliable_coins", return_value=set()), \
             mock.patch.object(m, "perp_top", return_value=(8.83, 8.84)), \
             mock.patch.object(m, "fetch_ohlcv", return_value={"c": [1.0] * 60}), \
             mock.patch.object(m, "short_signal", return_value=True), \
             mock.patch.object(m, "get_forecast", return_value={"dir": "down"}), \
             mock.patch.object(m, "gate", return_value=(True, "ok")), \
             mock.patch.object(m, "perps_position_qty", side_effect=positions), \
             mock.patch.object(m, "sodex",
                               return_value=mock.Mock(returncode=0, stdout="", stderr="")):
            out = m.cycle(st, live=True)
        return st, out

    def test_entry_rejected_when_position_level_unchanged(self):
        """REGRESI INTI: sudah ada posisi (-1.0) & tidak berubah -> JANGAN catat ENTRY."""
        st, out = self._run([-1.0, -1.0] * 6)
        self.assertEqual(st["open"], {}, f"delta nol = tidak ada fill; out={out}")
        self.assertEqual(st["trades_today"], 0, "counter cap tidak boleh naik tanpa fill")
        self.assertTrue(any("NO_FILL" in str(x) for x in out), f"out={out}")

    def test_entry_accepted_on_real_delta(self):
        """Kontrol positif: posisi short bertambah -> ENTRY dicatat."""
        st, out = self._run([0.0, -1.05] * 6)
        self.assertIn("SOL", st["open"], f"delta nyata wajib dicatat; out={out}")
        self.assertEqual(st["trades_today"], 1)


if __name__ == "__main__":
    unittest.main()
