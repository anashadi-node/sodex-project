import unittest

from scripts.sodex_queue_trade_validator import (
    PublicTrade,
    micro_pilot_gate_pass,
    queue_fill,
    research_gate_pass,
)


class QueueTradeValidatorTests(unittest.TestCase):
    def test_wrong_aggressor_does_not_fill_bid(self):
        trades = [PublicTrade(2, "BUY", 99, 20)]
        self.assertIsNone(queue_fill(
            trades, 1, 3, passive_side="BUY", price=99, required_qty=10))

    def test_bid_fill_requires_queue_quantity(self):
        trades = [PublicTrade(2, "SELL", 99, 4), PublicTrade(3, "SELL", 98, 7)]
        fill = queue_fill(trades, 1, 4, passive_side="BUY", price=99, required_qty=10)
        self.assertEqual(fill, (3, 11.0))

    def test_price_outside_limit_does_not_consume_queue(self):
        trades = [PublicTrade(2, "SELL", 100, 50)]
        self.assertIsNone(queue_fill(
            trades, 1, 3, passive_side="BUY", price=99, required_qty=10))

    def test_research_gate_requires_full_forward_evidence(self):
        passing = {
            "hours": 24,
            "round_trips": 100,
            "paired_share": 0.70,
            "volume_per_hour_usd": 100,
            "ratio_lcb_pass": True,
            "meets_ratio_floor": True,
        }
        self.assertTrue(research_gate_pass(passing))
        for key, failing_value in (
            ("hours", 23.99),
            ("round_trips", 99),
            ("paired_share", 0.69),
            ("volume_per_hour_usd", 99.99),
            ("ratio_lcb_pass", False),
            ("meets_ratio_floor", False),
        ):
            metrics = dict(passing)
            metrics[key] = failing_value
            self.assertFalse(research_gate_pass(metrics), key)

    def test_micro_pilot_gate_is_faster_but_still_requires_positive_lcb(self):
        passing = {
            "hours": 8,
            "notional_usd": 10,
            "round_trips": 100,
            "paired_share": 0.90,
            "volume_per_hour_usd": 150,
            "net_bps_lcb95": 0.01,
            "ratio_lcb_pass": True,
            "meets_ratio_floor": True,
        }
        self.assertTrue(micro_pilot_gate_pass(passing))
        passing["net_bps_lcb95"] = 0
        self.assertFalse(micro_pilot_gate_pass(passing))
        passing["net_bps_lcb95"] = 0.01
        passing["notional_usd"] = 2
        self.assertFalse(micro_pilot_gate_pass(passing))


if __name__ == "__main__":
    unittest.main()
