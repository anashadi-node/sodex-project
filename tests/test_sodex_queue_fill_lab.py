import unittest

from scripts.sodex_queue_fill_lab import (
    Episode,
    build_tape,
    estimate_tick,
    simulate_episode,
    summarize,
)


def row(ts, bid, ask, last, bid_sz=100, ask_sz=100):
    return (ts, bid, ask, bid_sz, ask_sz, last)


class QueueFillLabTests(unittest.TestCase):
    def test_touch_without_price_through_is_not_a_fill(self):
        tape = build_tape([
            row(0, 99, 101, 100),
            row(1, 99, 101, 99),
            row(2, 99, 101, 100),
        ])
        self.assertIsNone(simulate_episode(tape, 0, 5, 5, 1.08, 2.0))

    def test_price_through_then_opposite_through_is_paired(self):
        tape = build_tape([
            row(1, 99, 101, 100),
            row(2, 98, 100, 98),
            row(3, 100, 102, 102),
        ])
        episode = simulate_episode(tape, 0, 5, 5, 1.08, 2.0)
        self.assertIsNotNone(episode)
        self.assertEqual(episode.kind, "paired")
        self.assertGreater(episode.net_bps, 0)

    def test_unclosed_first_fill_uses_taker_fallback(self):
        tape = build_tape([
            row(1, 99, 101, 100),
            row(2, 98, 100, 98),
            row(4, 97, 99, 97),
            row(8, 96, 98, 96),
        ])
        episode = simulate_episode(tape, 0, 3, 4, 1.08, 2.0)
        self.assertEqual(episode.kind, "orphan_bid")
        self.assertLess(episode.net_bps, 0)

    def test_adaptive_close_reprices_without_crossing_entry(self):
        tape = build_tape([
            row(1, 99, 101, 100),
            row(2, 98, 100, 98),
            row(8, 98, 100, 99),
            row(9, 100, 101, 100),
        ])
        episode = simulate_episode(
            tape, 0, 5, 10, 1.08, 3.6, close_mode="adaptive_zero_gross")
        self.assertEqual(episode.kind, "paired")
        self.assertGreater(episode.net_bps, -3)

    def test_ratio_lcb_gate_rejects_unstable_positive_average(self):
        episodes = [Episode(0, 1, "paired", 20, 1, 1)] * 9
        episodes.append(Episode(0, 1, "orphan_bid", -170, 1, 1))
        metrics = summarize(episodes, 1, 6300)
        self.assertGreater(metrics["avg_net_bps"], 0)
        self.assertFalse(metrics["ratio_lcb_pass"])

    def test_profitable_stable_series_passes_ratio_gate(self):
        episodes = [Episode(0, 1, "paired", 8, 1, 1) for _ in range(20)]
        metrics = summarize(episodes, 1, 6300)
        self.assertTrue(metrics["ratio_lcb_pass"])
        self.assertTrue(metrics["meets_ratio_floor"])

    def test_tick_is_inferred_from_observed_price_grid(self):
        tape = build_tape([
            row(1, 99.00, 99.03, 99.01),
            row(2, 99.01, 99.04, 99.02),
            row(3, 99.02, 99.05, 99.03),
        ])
        self.assertAlmostEqual(estimate_tick(tape, 2), 0.01)


if __name__ == "__main__":
    unittest.main()
