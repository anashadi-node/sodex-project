import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sodex_wallet_denominator as wd


class TestWalletDenominatorSafety(unittest.TestCase):
    def test_refuses_unpriced_spot_asset(self):
        """Holding MATERIAL tanpa mark tetap fail-closed."""
        with tempfile.TemporaryDirectory() as td:
            snap = Path(td) / "snapshot.json"
            snap.write_text(json.dumps({
                "perps_balance": {"total": "94"},
                "spot_vusdc": {"total": "8"},
                "spot_balances": [
                    {"coin": "vUSDC", "total": "8"},
                    {"coin": "vBTC", "total": "0.01"},
                ],
            }))
            with patch.object(wd, "SNAP", snap):
                self.assertEqual(wd.read_priced_wallet(),
                                 (94.0, 8.0, 102.0, [{"coin": "vBTC", "total": "0.01"}]))
                with self.assertRaisesRegex(ValueError, "mark-to-market"):
                    wd.read_real_wallet()

    def test_cash_only_snapshot_has_valid_total(self):
        with tempfile.TemporaryDirectory() as td:
            snap = Path(td) / "snapshot.json"
            snap.write_text(json.dumps({
                "perps_balance": {"total": "94"},
                "spot_vusdc": {"total": "8"},
                "spot_balances": [{"coin": "vUSDC", "total": "8"}],
            }))
            with patch.object(wd, "SNAP", snap):
                perps, spot, total, dust = wd.read_real_wallet()
                self.assertEqual((perps, spot, total), (94.0, 8.0, 102.0))
                self.assertEqual(dust, [])

    def test_dust_does_not_block_final_denominator(self):
        """Dust mikro (vsMAG7.ssi 6.1e-07) tidak memblokir FINAL — audit 2026-09-15."""
        with tempfile.TemporaryDirectory() as td:
            snap = Path(td) / "snapshot.json"
            snap.write_text(json.dumps({
                "perps_balance": {"total": "92.88"},
                "spot_vusdc": {"total": "65"},
                "spot_balances": [
                    {"coin": "vUSDC", "total": "65"},
                    {"coin": "vsMAG7.ssi", "total": "0.00000061"},
                ],
            }))
            with patch.object(wd, "SNAP", snap):
                perps, spot, total, dust = wd.read_real_wallet()
                self.assertAlmostEqual(total, 157.88, places=2)
                self.assertEqual(len(dust), 1)
                self.assertEqual(dust[0]["coin"], "vsMAG7.ssi")
                self.assertLess(dust[0]["upper_bound_usd"], 0.10)

    def test_material_qty_still_blocks(self):
        """Qty besar tanpa harga tetap menolak FINAL — bukan hanya dust yang dicek."""
        with tempfile.TemporaryDirectory() as td:
            snap = Path(td) / "snapshot.json"
            snap.write_text(json.dumps({
                "perps_balance": {"total": "94"},
                "spot_vusdc": {"total": "8"},
                "spot_balances": [
                    {"coin": "vUSDC", "total": "8"},
                    {"coin": "vNEWCHAIN", "total": "5000"},
                ],
            }))
            with patch.object(wd, "SNAP", snap):
                with self.assertRaisesRegex(ValueError, "mark-to-market"):
                    wd.read_real_wallet()


if __name__ == "__main__":
    unittest.main()
