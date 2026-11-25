from datetime import datetime, timezone, timedelta
from unittest import TestCase


class SodexEventRunwayTests(TestCase):
    def test_micro_only_reports_insufficient_capacity_for_large_gap(self):
        from scripts import sodex_event_runway as runway

        monitor = {"verdict": {"progress": {"canonical_volume_usd": 257_911.53}}}
        policy = {
            "decision": "BLOCK_E2_E1_RESEARCH_ONLY",
            "regime": "BEAR",
            "blockers": ["weekly_win_rate_below_target"],
            "opportunity_lanes": [{
                "lane": "MICRO_PRE_LOSER_SHORT_ONLY",
                "max_notional_usd": 25.0,
                "max_daily_loss_usd": 1.0,
            }],
        }

        result = runway.evaluate_runway(
            monitor,
            policy,
            now=datetime(2026, 6, 25, tzinfo=timezone(timedelta(hours=7))),
        )

        self.assertEqual(result["phase"], "PHASE_1_MICRO_ONLY")
        self.assertEqual(result["verdict"], "MICRO_ONLY_INSUFFICIENT_FOR_EVENT_TARGET")
        self.assertGreater(result["needed_daily_volume_usd"], 30_000)
        self.assertGreater(result["micro"]["required_cycles_daily_for_target"], 600)

    def test_catchup_ready_phase_when_policy_allows_capped_volume(self):
        from scripts import sodex_event_runway as runway

        result = runway.evaluate_runway(
            {"verdict": {"progress": {"canonical_volume_usd": 1_000_000}}},
            {
                "decision": "CAPPED_CATCH_UP_ALLOWED",
                "regime": "SIDEWAYS",
                "opportunity_lanes": [],
            },
            now=datetime(2026, 7, 1, tzinfo=timezone(timedelta(hours=7))),
        )

        self.assertEqual(result["phase"], "PHASE_2_CATCHUP_READY")
        self.assertEqual(result["verdict"], "CATCHUP_CAPACITY_DEPENDS_ON_POLICY_LIMIT")
