import unittest

try:
    from scripts.sodex_mtf_scalp_lab import (
        bars_from_rows,
        executable_net_bps,
        feature_vector,
        samples_for_horizon,
        summarize,
    )
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False

_skip_reason = "sklearn not installed in this env (install via .venv-research)"


@unittest.skipUnless(_SKLEARN_AVAILABLE, _skip_reason)
class SodexMtfScalpLabTests(unittest.TestCase):
    def _bars(self):
        rows = []
        for i in range(20):
            mid = 100 + i * 0.1
            rows.append((1000 + i * 60, mid - 0.05, mid + 0.05, 10 + i, 9))
        return bars_from_rows(rows)

    def test_feature_vector_has_finite_expected_shape(self):
        values = feature_vector(self._bars(), 19)
        self.assertEqual(len(values), 14)
        self.assertTrue(all(value == value for value in values))

    def test_executable_net_includes_spread_and_two_fees(self):
        bars = self._bars()
        long_net, short_net = executable_net_bps(bars[15], bars[17], 3.6)
        self.assertGreater(long_net, 0)
        self.assertLess(short_net, 0)
        self.assertLess(long_net, 10)

    def test_ratio_uses_two_legs_and_profit_covers_cost(self):
        profitable = summarize([2, 3], 1, 5500, 20)
        self.assertTrue(profitable["honest_ratio_proxy_infinite"])
        losing = summarize([-2, -2], 1, 5500, 20)
        self.assertEqual(losing["honest_ratio_proxy"], 10000)
        self.assertTrue(losing["meets_ratio_floor"])

    def test_sample_estimated_cost_includes_spread_and_two_taker_fees(self):
        sample = samples_for_horizon("TEST", self._bars(), 1, 3.6)[0]
        self.assertAlmostEqual(sample.estimated_cost_bps,
                               sample.features[10] + 7.2)


if __name__ == "__main__":
    unittest.main()
