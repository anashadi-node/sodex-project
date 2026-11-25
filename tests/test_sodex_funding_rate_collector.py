import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sodex_funding_rate_collector as rc


class TestSodexFundingRateCollector(unittest.TestCase):
    def test_extracts_public_rates_from_sync_snapshot(self):
        snapshot = {
            "generated_utc": "2026-10-02T00:00:00+00:00",
            "perps_marks": {
                "BTC-USD": {"fundingRate": 0.0000125, "nextFundingTime": 1790910000000, "markPrice": 84000},
                "ETH-USD": {"fundingRate": "-0.00000625", "nextFundingTime": "1790910000000", "markPrice": "2700"},
            },
        }
        rows = rc.extract_rate_rows(snapshot)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["symbol"], "BTC")
        self.assertEqual(rows[0]["venue_symbol"], "BTC-USD")
        self.assertAlmostEqual(rows[0]["funding_rate"], 0.0000125)
        self.assertEqual(rows[0]["funding_time_ms"], 1790910000000)

    def test_append_dedupes_by_symbol_and_funding_time(self):
        rows = [
            {"symbol": "BTC", "venue_symbol": "BTC-USD", "funding_time_ms": 10, "funding_rate": 0.1},
            {"symbol": "BTC", "venue_symbol": "BTC-USD", "funding_time_ms": 10, "funding_rate": 0.1},
            {"symbol": "ETH", "venue_symbol": "ETH-USD", "funding_time_ms": 10, "funding_rate": -0.1},
        ]
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "rates.jsonl"
            n1 = rc.append_new_rows(out, rows)
            n2 = rc.append_new_rows(out, rows)
            lines = [json.loads(x) for x in out.read_text().splitlines()]
        self.assertEqual(n1, 2)
        self.assertEqual(n2, 0)
        self.assertEqual(len(lines), 2)

    def test_summary_is_fail_closed_when_no_rows(self):
        summary = rc.summarize([])
        self.assertEqual(summary["verdict"], "FAIL_CLOSED")
        self.assertEqual(summary["n_rows"], 0)


if __name__ == "__main__":
    unittest.main()
