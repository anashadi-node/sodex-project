import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sodex_funding_mapper as fm


class TestSodexFundingMapper(unittest.TestCase):
    def test_explicit_funding_field_wins(self):
        row = {
            "pair": "BTC", "direction": "SHORT", "entry_time": "2026-01-01T00:00:00+00:00",
            "exit_time": "2026-01-01T02:00:00+00:00", "funding_value": "0.25",
        }
        mapped = fm.map_trade(row, [], {})
        self.assertEqual(mapped["status"], "OK_EXPLICIT_FIELD")
        self.assertEqual(mapped["funding_usd"], 0.25)

    def test_history_maps_only_same_symbol_side_inside_window(self):
        row = {
            "pair": "BTC", "direction": "SHORT", "entry_time": "2026-01-01T00:00:00+00:00",
            "exit_time": "2026-01-01T03:00:00+00:00",
        }
        history = [
            {"symbol": "BTC", "side": "SHORT", "ts": fm.parse_dt("2026-01-01T01:00:00+00:00"), "fee_usd": 0.10},
            {"symbol": "BTC", "side": "LONG", "ts": fm.parse_dt("2026-01-01T01:00:00+00:00"), "fee_usd": 9.99},
            {"symbol": "ETH", "side": "SHORT", "ts": fm.parse_dt("2026-01-01T01:00:00+00:00"), "fee_usd": 9.99},
            {"symbol": "BTC", "side": "SHORT", "ts": fm.parse_dt("2026-01-01T04:00:00+00:00"), "fee_usd": 9.99},
        ]
        mapped = fm.map_trade(row, history, {})
        self.assertEqual(mapped["status"], "OK_HISTORY_EXACT_WINDOW")
        self.assertEqual(mapped["history_records"], 1)
        self.assertAlmostEqual(mapped["funding_usd"], 0.10)

    def test_missing_evidence_fail_closed(self):
        row = {
            "pair": "DOGE", "direction": "SHORT", "entry_time": "2026-01-01T00:00:00+00:00",
            "exit_time": "2026-01-01T03:00:00+00:00",
        }
        mapped = fm.map_trade(row, [], {"DOGE": 0.0001})
        self.assertEqual(mapped["status"], "MISSING_FUNDING_EVIDENCE")
        self.assertIsNone(mapped["funding_usd"])
        self.assertEqual(mapped["current_rate_reference"], 0.0001)

    def test_rate_history_estimates_forward_short_funding(self):
        row = {
            "pair": "BTC", "direction": "SHORT", "entry_time": "2026-01-01T00:00:00+00:00",
            "exit_time": "2026-01-01T03:00:00+00:00", "notional": 1000.0,
        }
        rate_history = [
            {"symbol": "BTC", "ts": fm.parse_dt("2026-01-01T01:00:00+00:00"),
             "collected": fm.parse_dt("2026-01-01T00:55:00+00:00"), "funding_rate": 0.0001},
            {"symbol": "BTC", "ts": fm.parse_dt("2026-01-01T04:00:00+00:00"),
             "collected": fm.parse_dt("2026-01-01T03:55:00+00:00"), "funding_rate": 0.9999},
        ]
        mapped = fm.map_trade(row, [], {}, rate_history)
        self.assertEqual(mapped["status"], "OK_RATE_ARCHIVE_ESTIMATED")
        self.assertEqual(mapped["rate_records"], 1)
        self.assertAlmostEqual(mapped["funding_usd"], 0.10)
        self.assertEqual(mapped["estimated_notional_usd"], 1000.0)

    def test_rate_history_collected_after_funding_time_is_rejected(self):
        row = {
            "pair": "BTC", "direction": "SHORT", "entry_time": "2026-01-01T00:00:00+00:00",
            "exit_time": "2026-01-01T03:00:00+00:00", "notional": 1000.0,
        }
        rate_history = [{"symbol": "BTC", "ts": fm.parse_dt("2026-01-01T01:00:00+00:00"),
                         "collected": fm.parse_dt("2026-01-01T01:05:00+00:00"), "funding_rate": 0.0001}]
        mapped = fm.map_trade(row, [], {}, rate_history)
        self.assertEqual(mapped["status"], "MISSING_FUNDING_EVIDENCE")
        self.assertIsNone(mapped["funding_usd"])

    def test_rate_history_long_side_sign_is_opposite_short(self):
        row = {
            "pair": "BTC", "direction": "LONG", "entry_time": "2026-01-01T00:00:00+00:00",
            "exit_time": "2026-01-01T03:00:00+00:00", "notional": 1000.0,
        }
        rate_history = [{"symbol": "BTC", "ts": fm.parse_dt("2026-01-01T01:00:00+00:00"),
                         "collected": fm.parse_dt("2026-01-01T00:55:00+00:00"), "funding_rate": 0.0001}]
        mapped = fm.map_trade(row, [], {}, rate_history)
        self.assertEqual(mapped["status"], "OK_RATE_ARCHIVE_ESTIMATED")
        self.assertAlmostEqual(mapped["funding_usd"], -0.10)

    def test_build_mapping_reports_fail_closed_when_any_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trades = root / "trades.json"
            hist = root / "funding.jsonl"
            snap = root / "snap.json"
            rates = root / "rates.jsonl"
            trades.write_text(json.dumps({"closed_trades": [
                {"pair": "BTC", "direction": "SHORT", "entry_time": "2026-01-01T00:00:00+00:00", "exit_time": "2026-01-01T03:00:00+00:00"},
                {"pair": "ETH", "direction": "SHORT", "entry_time": "2026-01-01T00:00:00+00:00", "exit_time": "2026-01-01T03:00:00+00:00"},
            ]}))
            hist.write_text(json.dumps({"pair": "BTC-USD", "side": "SHORT", "fee": "0.1", "ts": 1767229200000}) + "\n")
            snap.write_text(json.dumps({"perps_marks": {}}))
            # hermetic: empty archive -> no trade is classified pre-archive
            rates.write_text("")
            result = fm.build_mapping(trades, hist, snap, rates)
            self.assertEqual(result["n_ok"], 1)
            self.assertEqual(result["n_missing"], 1)
            self.assertEqual(result["n_in_window"], 2)
            self.assertEqual(result["n_pre_archive"], 0)
            self.assertEqual(result["verdict"], "FAIL_CLOSED")

    def test_pre_archive_shorts_excluded_from_coverage_but_still_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trades = root / "trades.json"
            hist = root / "funding.jsonl"
            snap = root / "snap.json"
            rates = root / "rates.jsonl"
            trades.write_text(json.dumps({"closed_trades": [
                {"pair": "BTC", "direction": "SHORT", "entry_time": "2026-08-06T14:00:00+00:00", "exit_time": "2026-08-07T13:52:00+00:00"},
                {"pair": "ETH", "direction": "SHORT", "entry_time": "2026-08-06T14:00:00+00:00", "exit_time": "2026-08-07T13:52:00+00:00"},
            ]}))
            hist.write_text("")
            snap.write_text(json.dumps({"perps_marks": {}}))
            start = fm.parse_dt("2026-10-02T10:08:25+00:00")
            rates.write_text(json.dumps({
                "venue_symbol": "BTC-USD", "funding_rate": 0.0001,
                "funding_time_ms": int(start.timestamp() * 1000),
                "collected_utc": start.isoformat(),
            }) + "\n")
            result = fm.build_mapping(trades, hist, snap, rates)
            self.assertEqual(result["n_short_trades"], 2)
            self.assertEqual(result["n_pre_archive"], 2)
            self.assertEqual(result["n_in_window"], 0)
            self.assertEqual(result["n_missing"], 0)
            self.assertEqual(result["coverage_pct"], 0.0)
            self.assertEqual(result["verdict"], "FAIL_CLOSED")
            self.assertIn("n_pre_archive=2", result["reason"])

    def test_build_mapping_passes_when_all_in_window_shorts_covered(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trades = root / "trades.json"
            hist = root / "funding.jsonl"
            snap = root / "snap.json"
            rates = root / "rates.jsonl"
            trades.write_text(json.dumps({"closed_trades": [
                {"pair": "BTC", "direction": "SHORT", "entry_time": "2026-01-01T00:00:00+00:00",
                 "exit_time": "2026-01-01T03:00:00+00:00", "notional": 1000.0},
            ]}))
            hist.write_text("")
            snap.write_text(json.dumps({"perps_marks": {}}))
            rates.write_text(json.dumps({
                "venue_symbol": "BTC-USD", "funding_rate": 0.0001,
                "funding_time_ms": int(fm.parse_dt("2026-01-01T01:00:00+00:00").timestamp() * 1000),
                "collected_utc": "2026-01-01T00:55:00+00:00",
            }) + "\n")
            result = fm.build_mapping(trades, hist, snap, rates)
            self.assertEqual(result["n_in_window"], 1)
            self.assertEqual(result["n_missing"], 0)
            self.assertEqual(result["n_ok"], 1)
            self.assertEqual(result["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
