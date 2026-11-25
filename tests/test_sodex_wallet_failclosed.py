"""Test fix denominator fail-closed (2026-10-25).

Bug yang dicegah: snapshot on-chain tanpa `spot_equity_usd` (mark spot gagal, mis. HTTP 429)
sebelumnya membuat tracker memakai spot=0 -> wallet understated -> semua % ROI ter-inflasi
31,4%. Test ini mengunci perilaku: fallback ke spot_vusdc + label eksplisit SPOT_UNMARKED.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "scripts"))
import sodex_maturation_tracker as trk  # noqa: E402


class TestWalletFailClosed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_project = trk.PROJECT
        trk.PROJECT = Path(self.tmp.name)
        (trk.PROJECT / "data").mkdir(parents=True)

    def tearDown(self):
        trk.PROJECT = self.old_project
        self.tmp.cleanup()

    def _write(self, payload):
        (trk.PROJECT / "data" / "sodex_real_sync_snapshot.json").write_text(json.dumps(payload))

    def test_mark_spot_gagal_pakai_spot_vusdc_dan_label(self):
        self._write({
            "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "spot_mark_error": "HTTP 429 Too Many Requests",
            "spot_vusdc": {"total": 49.28},
            "perps_balance": {"total": 184.97},
        })
        wallet, src = trk._read_live_wallet()
        self.assertAlmostEqual(wallet, 234.25, places=2, msg="spot vUSDC wajib ikut dihitung")
        self.assertIn("SPOT_UNMARKED", src, "denominasi lower-bound wajib dilabeli")

    def test_mark_lengkap_pakai_spot_equity(self):
        self._write({
            "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "spot_equity_usd": 58.05,
            "spot_vusdc": {"total": 49.28},
            "perps_balance": {"total": 184.97},
        })
        wallet, src = trk._read_live_wallet()
        self.assertAlmostEqual(wallet, 243.02, places=2)
        self.assertNotIn("SPOT_UNMARKED", src)

    def test_snapshot_basi_ditolak(self):
        self._write({
            "generated_utc": "2026-10-20T00:00:00Z",
            "spot_equity_usd": 58.05,
            "perps_balance": {"total": 184.97},
        })
        wallet, src = trk._read_live_wallet()
        self.assertNotIn("onchain_snapshot", src, "snapshot basi tidak boleh dipakai")


if __name__ == "__main__":
    unittest.main(verbosity=2)
