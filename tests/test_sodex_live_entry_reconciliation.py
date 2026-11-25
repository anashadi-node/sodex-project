import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import realwide_micro_live as rw
import sodex_spot_live_test as sp


class TestLiveEntryReconciliation(unittest.TestCase):
    def test_perps_mismatch_blocks_entry(self):
        with patch.object(rw, "real_perps_positions", return_value=[
            {"symbol": "HYPE-USD", "size": "0.81"},
        ]):
            ok, detail = rw.live_entry_reconciled({"open": {}})
        self.assertFalse(ok)
        self.assertIn("HYPE-USD", detail)

    def test_perps_empty_match_allows_entry_check(self):
        with patch.object(rw, "real_perps_positions", return_value=[]):
            ok, detail = rw.live_entry_reconciled({"open": {}})
        self.assertTrue(ok)
        self.assertEqual(detail, "match")

    def test_perps_same_symbol_wrong_side_blocks_entry(self):
        st = {"open": {"BTC": {"side": "short", "qty": 0.01, "entry_price": 80000}}}
        with patch.object(rw, "SODEX_SYM", {"BTC": "BTC-USD"}), \
             patch.object(rw, "real_perps_positions", return_value=[
                 {"symbol": "BTC-USD", "size": "0.01", "avgEntryPrice": "80000", "leverage": rw.LEVERAGE},
             ]):
            ok, detail = rw.live_entry_reconciled(st)
        self.assertFalse(ok)
        self.assertIn("side", detail)

    def test_perps_same_symbol_wrong_qty_blocks_entry(self):
        st = {"open": {"BTC": {"side": "long", "qty": 0.01, "entry_price": 80000}}}
        with patch.object(rw, "SODEX_SYM", {"BTC": "BTC-USD"}), \
             patch.object(rw, "real_perps_positions", return_value=[
                 {"symbol": "BTC-USD", "size": "0.02", "avgEntryPrice": "80000", "leverage": rw.LEVERAGE},
             ]):
            ok, detail = rw.live_entry_reconciled(st)
        self.assertFalse(ok)
        self.assertIn("qty", detail)

    def test_perps_leverage_mismatch_resyncs_instead_of_blocking(self):
        """Audit 2026-09-27: leverage bukan identitas posisi — mismatch di-resync
        ke kebenaran exchange, entry TETAP dibuka (bukan HALT permanen)."""
        st = {"open": {"BTC": {"side": "long", "qty": 0.01, "entry_price": 80000,
                               "verified_leverage": rw.LEVERAGE}}}
        with patch.object(rw, "SODEX_SYM", {"BTC": "BTC-USD"}), \
             patch.object(rw, "real_perps_positions", return_value=[
                 {"symbol": "BTC-USD", "size": "0.01", "avgEntryPrice": "80000", "leverage": rw.LEVERAGE + 2},
             ]), \
             patch.object(rw, "save_state"):
            ok, detail = rw.live_entry_reconciled(st)
        self.assertTrue(ok, f"leverage mismatch harusnya tidak blokir: {detail}")
        self.assertEqual(st["open"]["BTC"]["verified_leverage"], rw.LEVERAGE + 2)

    def test_perps_qty_mismatch_still_blocks(self):
        """Field identitas (qty) TETAP fail-closed setelah fix leverage-resync."""
        st = {"open": {"BTC": {"side": "long", "qty": 0.01, "entry_price": 80000}}}
        with patch.object(rw, "SODEX_SYM", {"BTC": "BTC-USD"}), \
             patch.object(rw, "real_perps_positions", return_value=[
                 {"symbol": "BTC-USD", "size": "0.05", "avgEntryPrice": "80000", "leverage": rw.LEVERAGE},
             ]), \
             patch.object(rw, "save_state"):
            ok, detail = rw.live_entry_reconciled(st)
        self.assertFalse(ok)
        self.assertIn("qty", detail)

    def test_spot_untracked_blocks_entry(self):
        with patch.object(sp, "real_spot_balance", return_value=[
            {"coin": "vUSDC", "total": "8"},
            {"coin": "vBTC", "total": "0.01"},
        ]):
            ok, detail = sp.live_entry_reconciled({"open": {}})
        self.assertFalse(ok)
        self.assertIn("vBTC", detail)

    def test_spot_manual_allowlist_accepts_exact_and_base_symbols(self):
        balances = [
            {"coin": "vUSDC", "total": "8"},
            {"coin": "vBTC", "total": "0.01"},
            {"coin": "WSOSO", "total": "1"},
            {"coin": "aUNITREE", "total": "1"},
        ]
        with patch.dict(os.environ, {"SODEX_MANUAL_SPOT_ALLOWLIST": "BTC,WSOSO,aUNITREE"}, clear=False):
            with patch.object(sp, "real_spot_balance", return_value=balances):
                ok, detail = sp.live_entry_reconciled({"open": {}})
        self.assertTrue(ok)
        self.assertEqual(detail, "match")

    def test_spot_empty_match_allows_entry_check(self):
        with patch.object(sp, "real_spot_balance", return_value=[
            {"coin": "vUSDC", "total": "8"},
        ]):
            ok, detail = sp.live_entry_reconciled({"open": {}})
        self.assertTrue(ok)
        self.assertEqual(detail, "match")


if __name__ == "__main__":
    unittest.main()
