"""Tests for U1 microstructure recorder pure derivations (no DB/network)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.sodex_book_recorder import (
    compute_ofi, obi_series, spread_series, realized_vol)


def _s(bid, ask, bid_sz, ask_sz):
    return {"bid": bid, "ask": ask, "bid_sz": bid_sz, "ask_sz": ask_sz}


class TestComputeOFI(unittest.TestCase):
    def test_empty_or_single_is_zero(self):
        self.assertEqual(compute_ofi([]), 0.0)
        self.assertEqual(compute_ofi([_s(100, 101, 10, 10)]), 0.0)

    def test_bid_size_grows_positive_ofi(self):
        # same prices, bid depth grows → buy pressure
        ofi = compute_ofi([_s(100, 101, 10, 10), _s(100, 101, 15, 10)])
        self.assertEqual(ofi, 5.0)

    def test_bid_price_up_positive_ofi(self):
        ofi = compute_ofi([_s(100, 101, 10, 10), _s(100.5, 101, 8, 10)])
        self.assertEqual(ofi, 8.0)

    def test_ask_lifted_positive_ofi(self):
        # ask price rises (sellers retreat) → buy pressure
        ofi = compute_ofi([_s(100, 101, 10, 10), _s(100, 101.5, 10, 12)])
        self.assertEqual(ofi, 10.0)

    def test_bid_drops_negative_ofi(self):
        ofi = compute_ofi([_s(100, 101, 10, 10), _s(99.5, 101, 10, 10)])
        self.assertEqual(ofi, -10.0)

    def test_cumulative_over_multiple(self):
        snaps = [_s(100, 101, 10, 10), _s(100, 101, 15, 10), _s(100, 101, 20, 10)]
        # +5 then +5 = +10
        self.assertEqual(compute_ofi(snaps), 10.0)


class TestOtherDerivations(unittest.TestCase):
    def test_obi_series(self):
        obis = obi_series([_s(100, 101, 75, 25), _s(100, 101, 25, 75)])
        self.assertAlmostEqual(obis[0], 0.5, places=6)
        self.assertAlmostEqual(obis[1], -0.5, places=6)

    def test_obi_zero_depth_safe(self):
        self.assertEqual(obi_series([_s(100, 101, 0, 0)]), [0.0])

    def test_spread_series_bps(self):
        sp = spread_series([_s(100, 101, 10, 10)])
        # (1/100.5)*1e4 ≈ 99.50 bps
        self.assertAlmostEqual(sp[0], 99.50, places=1)

    def test_realized_vol_flat_is_zero(self):
        snaps = [_s(100, 101, 10, 10)] * 5  # constant mid → 0 vol
        self.assertEqual(realized_vol(snaps), 0.0)

    def test_realized_vol_positive_when_moving(self):
        snaps = [_s(100, 101, 10, 10), _s(101, 102, 10, 10),
                 _s(100, 101, 10, 10), _s(102, 103, 10, 10)]
        self.assertGreater(realized_vol(snaps), 0.0)

    def test_realized_vol_too_few_points(self):
        self.assertEqual(realized_vol([_s(100, 101, 10, 10)]), 0.0)


if __name__ == "__main__":
    unittest.main()
