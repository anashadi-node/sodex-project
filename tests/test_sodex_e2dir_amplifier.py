from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch


class SodexE2DirAmplifierTests(TestCase):
    def test_short_candidate_prefers_positive_funding_tight_spread_and_volume(self):
        from scripts import sodex_e2dir_amplifier as amp

        good = amp.score_short_candidate(
            {"symbol": "CHZ-USD", "changePct": "-6.0", "quoteVolume": "150000", "fundingRate": "0.0000125"},
            {"bids": [{"price": "0.01840"}], "asks": [{"price": "0.01841"}]},
        )
        bad_funding = amp.score_short_candidate(
            {"symbol": "PUMP-USD", "changePct": "-6.0", "quoteVolume": "150000", "fundingRate": "-0.0000125"},
            {"bids": [{"price": "0.01840"}], "asks": [{"price": "0.01841"}]},
        )

        self.assertIsNotNone(good)
        self.assertIsNotNone(bad_funding)
        assert good and bad_funding
        self.assertGreater(good.score, bad_funding.score)
        self.assertGreater(good.expected_edge_bps, Decimal("0"))

    def test_rejects_low_volume_wide_spread_or_non_loser(self):
        from scripts import sodex_e2dir_amplifier as amp

        tight = {"bids": [{"price": "1.0000"}], "asks": [{"price": "1.0005"}]}
        wide = {"bids": [{"price": "1.0000"}], "asks": [{"price": "1.0200"}]}

        self.assertIsNone(amp.score_short_candidate(
            {"symbol": "LOW-USD", "changePct": "-5", "quoteVolume": "1000", "fundingRate": "0.0001"},
            tight,
        ))
        self.assertIsNone(amp.score_short_candidate(
            {"symbol": "WIDE-USD", "changePct": "-5", "quoteVolume": "200000", "fundingRate": "0.0001"},
            wide,
        ))
        self.assertIsNone(amp.score_short_candidate(
            {"symbol": "UP-USD", "changePct": "3", "quoteVolume": "200000", "fundingRate": "0.0001"},
            tight,
        ))

    def test_select_candidates_orders_by_score(self):
        from scripts import sodex_e2dir_amplifier as amp

        rows = [
            {"symbol": "A-USD", "changePct": "-3", "quoteVolume": "100000", "fundingRate": "0.00001"},
            {"symbol": "B-USD", "changePct": "-8", "quoteVolume": "200000", "fundingRate": "0.00002"},
        ]
        books = {
            "A-USD": {"bids": [{"price": "1.0000"}], "asks": [{"price": "1.0005"}]},
            "B-USD": {"bids": [{"price": "1.0000"}], "asks": [{"price": "1.0005"}]},
        }

        with patch.object(amp, "orderbook", side_effect=lambda symbol: books[symbol]):
            picked = amp.select_short_candidates(rows, limit=2)

        self.assertEqual([x.symbol for x in picked], ["B-USD", "A-USD"])

    def test_promotion_gate_blocks_live_when_policy_has_blockers(self):
        from scripts import sodex_e2dir_amplifier as amp

        decision = amp.promotion_decision(
            policy={"decision": "BLOCK_E2_E1_RESEARCH_ONLY", "blockers": ["weekly_win_rate_below_target"]},
            candidates=[{"symbol": "B-USD", "score": 12.0, "expected_edge_bps": 20.0}],
        )

        self.assertEqual(decision["phase"], "PAPER_AMPLIFIER_ONLY")
        self.assertFalse(decision["live_allowed"])

    def test_promotion_gate_allows_micro_candidate_only_when_policy_clear_and_edge_high(self):
        from scripts import sodex_e2dir_amplifier as amp

        decision = amp.promotion_decision(
            policy={"decision": "CAPPED_CATCH_UP_ALLOWED", "blockers": []},
            candidates=[{"symbol": "B-USD", "score": 12.0, "expected_edge_bps": 20.0}],
        )

        self.assertEqual(decision["phase"], "LIVE_E2DIR_MICRO_CANDIDATE")
        self.assertTrue(decision["live_allowed"])

    def test_promotion_gate_allows_deadline_candidate_with_soft_blockers_and_thin_edge(self):
        from scripts import sodex_e2dir_amplifier as amp

        decision = amp.promotion_decision(
            policy={
                "decision": "DEADLINE_MICRO_CATCHUP_ONLY",
                "blockers": ["official_dashboard_not_canonical", "weekly_win_rate_below_target"],
                "opportunity_lanes": [{"lane": "DEADLINE_MICRO_CATCHUP"}],
            },
            candidates=[{"symbol": "CHZ-USD", "score": 7.5, "expected_edge_bps": 3.2}],
        )

        self.assertEqual(decision["phase"], "DEADLINE_E2DIR_MICRO_CANDIDATE")
        self.assertTrue(decision["deadline_flex"])
        self.assertTrue(decision["live_allowed"])

    def test_promotion_gate_allows_safety_halt_short_candidate_when_policy_exposes_lane(self):
        from scripts import sodex_e2dir_amplifier as amp

        decision = amp.promotion_decision(
            policy={
                "decision": "SAFETY_HALT_SHORT_PILOT_CANDIDATE",
                "blockers": [
                    "safety_halt_active",
                    "official_dashboard_not_canonical",
                    "weekly_win_rate_below_target",
                ],
                "opportunity_lanes": [{"lane": "SAFETY_HALT_SHORT_PILOT"}],
            },
            candidates=[{"symbol": "XPL-USD", "score": 18.0, "expected_edge_bps": 12.5}],
        )

        self.assertEqual(decision["phase"], "SAFETY_HALT_E2DIR_SHORT_PILOT_CANDIDATE")
        self.assertTrue(decision["safety_halt_short_flex"])
        self.assertTrue(decision["live_allowed"])

    def test_promotion_gate_allows_ratio_recovery_maker_lane(self):
        from scripts import sodex_e2dir_amplifier as amp

        decision = amp.promotion_decision(
            policy={
                "decision": "BLOCK_E2_E1_RESEARCH_ONLY",
                "blockers": ["official_dashboard_not_canonical", "combined_pnl_negative"],
                "opportunity_lanes": [{"lane": "RATIO_RECOVERY_MAKER_ONLY"}],
            },
            candidates=[{"symbol": "SKHX-USD", "score": 3.0, "expected_edge_bps": 0.5}],
        )

        self.assertEqual(decision["phase"], "RATIO_RECOVERY_MAKER_ONLY_CANDIDATE")
        self.assertTrue(decision["ratio_recovery"])
        self.assertTrue(decision["live_allowed"])

    def test_promotion_gate_rejects_deadline_candidate_when_signal_blocker_remains(self):
        from scripts import sodex_e2dir_amplifier as amp

        decision = amp.promotion_decision(
            policy={
                "decision": "DEADLINE_MICRO_CATCHUP_ONLY",
                "blockers": ["market_direction_signal_stale"],
                "opportunity_lanes": [{"lane": "DEADLINE_MICRO_CATCHUP"}],
            },
            candidates=[{"symbol": "CHZ-USD", "score": 7.5, "expected_edge_bps": 3.2}],
        )

        self.assertEqual(decision["phase"], "PAPER_AMPLIFIER_ONLY")
        self.assertFalse(decision["live_allowed"])
