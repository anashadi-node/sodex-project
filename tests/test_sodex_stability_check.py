import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import sodex_stability_check as chk


class TestWalletDenominator(unittest.TestCase):
    def test_env_takes_precedence(self):
        with patch.dict(os.environ, {"SODEX_TOTAL_WALLET": "200.50"}, clear=False):
            self.assertEqual(chk.read_wallet_denominator(), 200.50)

    def test_reads_canonical_monitor_equity(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {}, clear=True):
            data = Path(td)
            (data / "sodex_monitor_eval").mkdir(parents=True)
            (data / "sodex_monitor_eval" / "latest.json").write_text(json.dumps({
                "account": {"account_value": {"total_equity_usd": 172.938743}}
            }))
            with patch.object(chk, "DATA", data):
                self.assertAlmostEqual(chk.read_wallet_denominator(), 172.938743)

    def test_fallback_is_positive(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {}, clear=True), \
             patch.object(chk, "DATA", Path(td)):
            self.assertGreater(chk.read_wallet_denominator(), 0)


if __name__ == "__main__":
    unittest.main()
