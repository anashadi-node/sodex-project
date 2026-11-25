#!/usr/bin/env python3
"""Regression tests for SoDEX paper-state identity and wallet denominator."""
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import paper_test_spot_swing_v2 as spot  # noqa: E402
import paper_test_multivenue as multi  # noqa: E402
import paper_test_pasar_anantara_trade as pasar  # noqa: E402


class TestPaperStateIdentity(unittest.TestCase):
    def test_spot_symbol_guard_ignores_timestamp_key(self):
        state = {"open": {"vTON_vUSDC_123": {"spot_sym": "vTON_vUSDC"}}}
        self.assertTrue(spot.has_open_spot(state, "vTON_vUSDC"))
        self.assertFalse(spot.has_open_spot(state, "vETH_vUSDC"))

    def test_multivenue_pair_guard_ignores_timestamp_key(self):
        state = {"open": {"TRX_123": {"pair": "TRX"}}}
        self.assertTrue(multi.has_open_pair(state, "TRX"))
        self.assertFalse(multi.has_open_pair(state, "ETH"))

    def test_pasar_uses_futures_fallback_and_returns_plain_lists(self):
        import numpy as np
        fake = {"o": np.array([1.0]), "h": np.array([2.0]),
                "l": np.array([0.5]), "c": np.array([1.5])}
        with patch.object(pasar.RW, "fetch_ohlcv", return_value=fake):
            out = pasar.fetch_ohlcv("HYPEUSDT")
        self.assertEqual(out["c"], [1.5])
        self.assertIsInstance(out["c"], list)

    def test_active_paper_denominator_not_stale_literal(self):
        self.assertNotEqual(spot.REAL_WALLET, 94.5720)
        self.assertNotEqual(multi.REAL_WALLET, 94.5720)
        self.assertGreater(spot.REAL_WALLET, 0)
        self.assertGreater(multi.REAL_WALLET, 0)


if __name__ == "__main__":
    unittest.main()
