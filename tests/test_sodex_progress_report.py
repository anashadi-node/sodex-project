import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sodex_progress_report as report


class TestSodexProgressReportWallet(unittest.TestCase):
    def test_env_overrides_file(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / ".env.swing"
            f.write_text("SODEX_TOTAL_WALLET=158.66\n")
            value, source = report.read_wallet_denominator(
                env={"SODEX_TOTAL_WALLET": "200.50"}, env_file=f)
            self.assertEqual(value, 200.50)
            self.assertEqual(source, "env")

    def test_reads_env_swing_when_env_missing(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / ".env.swing"
            f.write_text("PAPER_RELAXED=1\nSODEX_TOTAL_WALLET=158.66\n")
            value, source = report.read_wallet_denominator(env={}, env_file=f)
            self.assertEqual(value, 158.66)
            self.assertEqual(source, ".env.swing")

    def test_labels_stale_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            value, source = report.read_wallet_denominator(env={}, env_file=Path(td) / "missing.env")
            self.assertEqual(value, 108.10)
            self.assertEqual(source, "fallback_stale")


if __name__ == "__main__":
    unittest.main()
