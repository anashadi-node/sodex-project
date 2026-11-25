import unittest

from scripts.sodex_two_sided_shadow import Quote, advance_quote


class TwoSidedShadowTests(unittest.TestCase):
    def test_both_touches_capture_posted_spread(self):
        quote = Quote("EWY-USD", 1000, 1060, 99.9, 100.1)
        rows = [(1010, 99.8, 100.0, 99.85), (1020, 100.0, 100.2, 100.15)]
        active, outcome = advance_quote(quote, rows, fee_bps=2.4, adverse_bps=1.0)
        self.assertIsNone(active)
        self.assertEqual(outcome["kind"], "paired")
        self.assertAlmostEqual(outcome["net_bps"], 16.6)

    def test_orphan_is_flattened_at_executable_side_after_deadline(self):
        quote = Quote("EWY-USD", 1000, 1060, 99.9, 100.1)
        rows = [(1010, 99.8, 100.0, 99.85), (1061, 99.7, 99.9, 99.8)]
        active, outcome = advance_quote(quote, rows, fee_bps=2.4, adverse_bps=1.0)
        self.assertIsNone(active)
        self.assertEqual(outcome["kind"], "orphan_bid")
        self.assertLess(outcome["net_bps"], 0)

    def test_no_touch_has_no_round_trip_cost(self):
        quote = Quote("EWY-USD", 1000, 1060, 99.9, 100.1)
        active, outcome = advance_quote(
            quote, [(1061, 99.9, 100.1, 100.0)], fee_bps=2.4, adverse_bps=1.0)
        self.assertIsNone(active)
        self.assertEqual(outcome["kind"], "no_fill")
        self.assertIsNone(outcome["net_bps"])


if __name__ == "__main__":
    unittest.main()
