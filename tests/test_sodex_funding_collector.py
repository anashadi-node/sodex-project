"""Tests for SoDEX funding collector (F2, 2026-06-29).

SoDEX exposes funding only via per-account /fundings history (not public per-pair).
The collector polls that endpoint, computes the realized funding rate per pair per
1h interval, and ranks pairs by funding magnitude to surface funding-squeeze signals
(short the over-funded pair = receive funding; long the under-funded = pay funding).
This is the data layer F2 (signal + paper execution come after).
"""
import os
import sys
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestFundingParse(unittest.TestCase):
    def test_parse_funding_history(self):
        """Parse the /fundings REST response into (pair, side, rate, ts) tuples."""
        from anantara.sodex_funding_collector import parse_funding_history
        sample = {
            "code": 0, "timestamp": 1782748013161,
            "data": [
                {"symbol": "SPCX-USD", "positionSide": "SHORT",
                 "fundingFee": "0.002787666875", "feeCoin": "vUSDC",
                 "timestamp": 1782745200032, "positionID": 8143775},
                {"symbol": "CHZ-USD", "positionSide": "SHORT",
                 "fundingFee": "0.00000611625", "feeCoin": "vUSDC",
                 "timestamp": 1782745200032, "positionID": 8150597},
                {"symbol": "BTC-USD", "positionSide": "LONG",
                 "fundingFee": "-0.00012", "feeCoin": "vUSDC",
                 "timestamp": 1782745200032, "positionID": 8143776},
            ]
        }
        rows = parse_funding_history(sample)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["pair"], "SPCX-USD")
        self.assertEqual(rows[0]["side"], "SHORT")
        self.assertEqual(rows[0]["fee"], D("0.002787666875"))
        # LONG with negative fee = LONG PAYS funding (over-funded pair)
        self.assertEqual(rows[2]["side"], "LONG")
        self.assertEqual(rows[2]["fee"], D("-0.00012"))

    def test_parse_empty_or_null(self):
        from anantara.sodex_funding_collector import parse_funding_history
        self.assertEqual(parse_funding_history(None), [])
        self.assertEqual(parse_funding_history({}), [])
        self.assertEqual(parse_funding_history({"data": None}), [])


class TestFundingSignal(unittest.TestCase):
    def test_overfunded_pair_signals_short(self):
        """When LONG holders PAY funding (fee negative for LONG), the pair is
        over-funded → SHORT receives funding → funding-squeeze SHORT signal."""
        from anantara.sodex_funding_collector import funding_signal
        # SPCX: LONG pays 0.00279 (over-funded) → SHORT signal
        sig = funding_signal("SPCX-USD", [("LONG", D("-0.00279")), ("SHORT", D("0.00279"))])
        self.assertEqual(sig["direction"], "short")
        self.assertGreater(sig["strength"], 0)

    def test_underfunded_pair_signals_long(self):
        """When SHORT holders PAY funding (fee negative for SHORT), pair under-funded
        → LONG receives funding → LONG signal."""
        from anantara.sodex_funding_collector import funding_signal
        sig = funding_signal("BTC-USD", [("SHORT", D("-0.0005")), ("LONG", D("0.0005"))])
        self.assertEqual(sig["direction"], "long")

    def test_neutral_pair_no_signal(self):
        from anantara.sodex_funding_collector import funding_signal
        sig = funding_signal("CHZ-USD", [("SHORT", D("0.000006"))])
        # Below threshold → no actionable signal
        self.assertIsNone(sig["direction"] if "direction" in sig else None) or \
            self.assertLess(sig["strength"], 0.0001)

    def test_signal_ranking(self):
        """Rank multiple pairs by funding magnitude (strongest squeeze first)."""
        from anantara.sodex_funding_collector import rank_signals
        signals = [
            {"pair": "SPCX-USD", "direction": "short", "strength": 0.00279},
            {"pair": "CHZ-USD", "direction": None, "strength": 0.000006},
            {"pair": "TRUMP-USD", "direction": "short", "strength": 0.0078},
        ]
        ranked = rank_signals(signals, top_n=2)
        self.assertEqual(ranked[0]["pair"], "TRUMP-USD")  # strongest
        self.assertEqual(ranked[1]["pair"], "SPCX-USD")
        self.assertEqual(len(ranked), 2)  # top_n respected


class TestCollectorFetch(unittest.TestCase):
    @patch("anantara.sodex_funding_collector.requests")
    def test_fetch_funding_history_api(self, mock_req):
        """Collector hits /fundings REST and returns parsed rows."""
        from anantara import sodex_funding_collector as fc
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0, "data": [
            {"symbol": "SPCX-USD", "positionSide": "SHORT",
             "fundingFee": "0.00278", "timestamp": 1782745200032, "positionID": 1}]}
        mock_resp.status_code = 200
        mock_req.get.return_value = mock_resp
        rows = fc.fetch_funding_history("0xABC", base="https://gw.test")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pair"], "SPCX-USD")
        mock_req.get.assert_called_once()

    @patch("anantara.sodex_funding_collector.requests")
    def test_fetch_handles_api_error(self, mock_req):
        from anantara import sodex_funding_collector as fc
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.side_effect = ValueError
        mock_req.get.return_value = mock_resp
        rows = fc.fetch_funding_history("0xABC", base="https://gw.test")
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
