from unittest import TestCase


class SodexWatchlistGateAcceleratorTests(TestCase):
    def test_adverse_selection_blocks_weak_short_momentum(self):
        from scripts import sodex_watchlist_gate_accelerator as gate

        score, ok, blockers = gate.adverse_selection_score({
            "spread_bps": 2.0,
            "quote_volume_usd": 200000,
            "change_pct": 0.2,
            "funding_rate": "0.00001",
        })

        self.assertFalse(ok)
        self.assertIn("short_momentum_weak", blockers)
        self.assertLess(score, 100)

    def test_evaluate_item_requires_all_core_gates(self):
        from scripts import sodex_watchlist_gate_accelerator as gate

        row = gate.evaluate_item(
            {
                "symbol": "AVAX-USD",
                "spread_bps": 2.0,
                "quote_volume_usd": 200000,
                "change_pct": -3.0,
                "funding_rate": "0.00001",
            },
            fees={"maker_roundtrip_bps": 2.16, "taker_roundtrip_bps": 7.2},
            pos={"pass": True},
            policy={
                "lane_present": True,
                "max_daily_loss_usd": 0.5,
                "max_notional_usd": 12.0,
                "blockers": [],
            },
            sys_blockers=[],
            max_spread_bps=12.0,
            min_liquidity_usd=75000.0,
        )

        self.assertEqual(row.status, "BLOCKED")
        self.assertIn("fee_edge", row.blockers)

    def test_micro_cooldown_downgrades_otherwise_ready_asset(self):
        from scripts import sodex_watchlist_gate_accelerator as gate

        row = gate.evaluate_item(
            {
                "symbol": "MON-USD",
                "spread_bps": 5.0,
                "quote_volume_usd": 200000,
                "change_pct": -3.0,
                "funding_rate": "0.00001",
            },
            fees={"maker_roundtrip_bps": 2.16, "taker_roundtrip_bps": 7.2},
            pos={"pass": True},
            policy={
                "lane_present": True,
                "max_daily_loss_usd": 0.5,
                "max_notional_usd": 12.0,
                "blockers": [],
            },
            sys_blockers=["micro_pilot_negative_edge_cooldown"],
            max_spread_bps=12.0,
            min_liquidity_usd=75000.0,
        )

        self.assertEqual(row.status, "PAPER_READY_LIVE_COOLDOWN")
        self.assertEqual(row.blockers, ["micro_pilot_cooldown"])
