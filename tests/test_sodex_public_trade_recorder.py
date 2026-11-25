import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.sodex_public_trade_recorder import normalize_trade, record_once


class PublicTradeRecorderTests(unittest.TestCase):
    def test_normalizes_exchange_trade_shape(self):
        value = normalize_trade("HYPE-USD", {
            "t": 12, "T": 1_784_600_000_123, "S": "buy", "p": "42.5", "q": "3",
        })
        self.assertEqual(value, ("HYPE-USD", "12", 1_784_600_000.123, "BUY", 42.5, 3.0))

    def test_invalid_trade_is_rejected(self):
        self.assertIsNone(normalize_trade("X", {"t": 1, "T": 2, "S": "?", "p": 1, "q": 1}))

    def test_record_once_deduplicates(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "trades.db"
            rows = [{"t": 1, "T": 1_784_600_000_000, "S": "SELL", "p": 10, "q": 2}]
            with patch("scripts.sodex_public_trade_recorder.fetch_trades", return_value=rows):
                first = record_once(path, ["HYPE-USD"], retention_h=1_000_000)
                second = record_once(path, ["HYPE-USD"], retention_h=1_000_000)
            self.assertEqual(first["inserted"], 1)
            self.assertEqual(second["inserted"], 0)
            self.assertEqual(second["total"], 1)


if __name__ == "__main__":
    unittest.main()
