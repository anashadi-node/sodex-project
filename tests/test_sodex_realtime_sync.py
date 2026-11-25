"""Test sodex_realtime_sync — endpoint benar vs CLI yang cacat.

Regression guard: pastikan endpoint /accounts/{addr}/positions tetap dipakai
(bukan endpoint lama yang selalu null). Mock HTTP, tidak panggil API nyata.
"""
import json
import unittest
from unittest.mock import patch, MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import sodex_realtime_sync as sync


class TestSodexRealtimeSync(unittest.TestCase):

    def _mock_response(self, payload):
        m = MagicMock()
        m.read.return_value = json.dumps(payload).encode()
        m.__enter__.return_value = m
        return m

    def test_positions_endpoint_url_correct(self):
        """URL harus /accounts/{addr}/positions - endpoint yang TERBUKTI benar."""
        addr = "0xabc123"
        captured = {}

        def fake_get(url, timeout=15):
            captured["url"] = url
            return {"code": 0, "data": {"positions": []}}

        with patch.object(sync, "_get", side_effect=fake_get):
            sync.real_perps_positions(addr)
        self.assertIn(f"/accounts/{addr}/positions", captured["url"])

    def test_positions_filters_inactive(self):
        """Posisi yang sudah closed (active=False) tidak boleh dilaporkan sebagai open."""
        payload = {"code": 0, "data": {"positions": [
            {"symbol": "ETH-USD", "active": True, "size": "0.0066"},
            {"symbol": "BTC-USD", "active": False, "size": "0"},
        ]}}
        with patch.object(sync, "_get", return_value=payload):
            result = sync.real_perps_positions("0xabc")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["symbol"], "ETH-USD")

    def test_positions_api_error_raises(self):
        """code != 0 harus raise, bukan diam-diam return [] (itulah cara CLI lama gagal)."""
        payload = {"code": -1, "error": "invalid parameter"}
        with patch.object(sync, "_get", return_value=payload):
            with self.assertRaises(RuntimeError):
                sync.real_perps_positions("0xabc")

    def test_no_address_raises(self):
        old = sync.ADDRESS
        sync.ADDRESS = ""
        try:
            with self.assertRaises(ValueError):
                sync._addr(None)
        finally:
            sync.ADDRESS = old

    def test_full_sync_writes_snapshot(self):
        """full_sync harus menulis file snapshot atomic (tmp->rename)."""
        import tempfile, os
        payload_pos = {"code": 0, "data": {"positions": []}}
        payload_bal = {"code": 0, "data": {"balances": [
            {"coin": "vUSDC", "total": "100"},
            {"coin": "vBTC", "total": "0.0001"},
        ]}}
        payload_orders = {"code": 0, "data": {"orders": []}}
        payload_tickers = {"code": 0, "data": {"tickers": [
            {"symbol": "vBTC_vUSDC", "bidPx": "10000"},
            {"symbol": "BTC-USD", "markPrice": "10010"},
        ]}}

        def fake_get(url, timeout=15):
            if "positions" in url:
                return payload_pos
            if "orders" in url:
                return payload_orders
            if "markets/tickers" in url:
                return payload_tickers
            return payload_bal

        with tempfile.TemporaryDirectory() as td:
            old_snap = sync.SNAP_FILE
            sync.SNAP_FILE = Path(td) / "snap.json"
            try:
                with patch.object(sync, "_get", side_effect=fake_get):
                    out = sync.full_sync(address="0xabc", verbose=False)
                self.assertTrue(sync.SNAP_FILE.exists())
                self.assertEqual(out["address"], "0xabc")
                self.assertEqual(out["perps_positions"], [])
                self.assertEqual(out["spot_balances"], payload_bal["data"]["balances"])
                self.assertIn("BTC-USD", out["perps_marks"])
                self.assertEqual(out["spot_unpriced"], [])
                self.assertFalse((Path(td) / "snap.tmp").exists())
                self.assertEqual(list(Path(td).glob("snap.json.*.tmp")), [])
            finally:
                sync.SNAP_FILE = old_snap

    def test_spot_base_derived_correctly(self):
        """SPOT_BASE harus /spot bukan /perps."""
        self.assertIn("/spot", sync.SPOT_BASE)
        self.assertNotIn("/perps", sync.SPOT_BASE)


if __name__ == "__main__":
    unittest.main()
