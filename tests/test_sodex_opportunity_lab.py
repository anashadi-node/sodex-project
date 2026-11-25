import unittest

from scripts.sodex_opportunity_lab import (
    Variant,
    benjamini_hochberg,
    build_tape,
    chronological_windows,
    evaluate,
    ratio_proxy,
    signal_direction,
    variant_grid,
)


def tape_from_prices(prices, *, last=None, step=5):
    rows = []
    for i, price in enumerate(prices):
        rows.append((1000 + i * step, price - 0.05, price + 0.05,
                     10 + i, 10, (last or prices)[i]))
    return build_tape(rows)


class OpportunityLabTests(unittest.TestCase):
    def test_ratio_proxy_uses_two_legs_of_volume(self):
        self.assertEqual(ratio_proxy([-2.0, -2.0]), 10000.0)
        self.assertIsNone(ratio_proxy([2.0, -1.0]))

    def test_momentum_and_reversion_are_opposite(self):
        tape = tape_from_prices([100 + i * 0.1 for i in range(20)])
        momentum = Variant("momentum", 30, 15, 1.0)
        reversion = Variant("reversion", 30, 15, 1.0)
        self.assertEqual(signal_direction(tape, 15, momentum), 1)
        self.assertEqual(signal_direction(tape, 15, reversion), -1)

    def test_evaluate_requires_later_touch_for_maker_fill(self):
        prices = [100 + i * 0.02 for i in range(40)]
        no_touch = tape_from_prices(prices, last=[p + 0.04 for p in prices])
        variant = Variant("momentum", 30, 15, 1.0)
        result = evaluate(no_touch, variant, 1000, 1190, sample_s=5,
                          fill_window_s=10, fee_bps=2.4, adverse_bps=1.0,
                          ratio_floor=6300)
        self.assertEqual(result.metrics["round_trips"], 0)

    def test_evaluate_prices_exit_at_executable_side_and_costs(self):
        prices = [100 + i * 0.02 for i in range(50)]
        last = [p - 0.08 for p in prices]
        tape = tape_from_prices(prices, last=last)
        variant = Variant("momentum", 30, 15, 1.0)
        result = evaluate(tape, variant, 1000, 1240, sample_s=5,
                          fill_window_s=10, fee_bps=2.4, adverse_bps=1.0,
                          ratio_floor=6300)
        self.assertGreater(result.metrics["round_trips"], 0)
        self.assertLess(result.metrics["avg_net_bps"], 10.0)

    def test_two_sided_variant_captures_spread_only_after_both_touches(self):
        prices = [100.0] * 50
        last = [100.0, 99.94, 100.06] * 17
        tape = tape_from_prices(prices, last=last[:50])
        variant = Variant("two_sided", 0, 15, 4.0)
        result = evaluate(tape, variant, 1000, 1240, sample_s=5,
                          fill_window_s=10, fee_bps=2.4, adverse_bps=1.0,
                          ratio_floor=6300)
        self.assertGreater(result.metrics["paired_fills"], 0)
        self.assertGreater(result.metrics["avg_net_bps"], 0)
        self.assertEqual(result.metrics["orphan_fills"], 0)

    def test_chronological_windows_have_embargo_gaps(self):
        tape = tape_from_prices([100 + i * 0.01 for i in range(101)], step=10)
        windows = chronological_windows(tape, embargo_s=20)
        self.assertEqual(windows["validation"][0] - windows["train"][1], 40)
        self.assertEqual(windows["oos"][0] - windows["validation"][1], 40)

    def test_benjamini_hochberg_preserves_order_and_monotonicity(self):
        adjusted = benjamini_hochberg([0.01, 0.04, 0.03])
        self.assertAlmostEqual(adjusted[0], 0.03)
        self.assertAlmostEqual(adjusted[1], 0.04)
        self.assertAlmostEqual(adjusted[2], 0.04)

    def test_directional_grid_covers_one_to_fifteen_minutes(self):
        variants = variant_grid(directional_only=True)
        self.assertEqual({row.horizon_s for row in variants}, {60, 180, 300, 900})
        self.assertNotIn("two_sided", {row.family for row in variants})


if __name__ == "__main__":
    unittest.main()
