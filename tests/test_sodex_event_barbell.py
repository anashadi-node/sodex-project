from datetime import datetime, timezone
from unittest import TestCase


class SodexEventBarbellTests(TestCase):
    def test_micro_stats_uses_perps_delta_and_round_trip_volume(self):
        from scripts import sodex_event_barbell as barbell

        rows = [
            {
                "mode": "live",
                "reason": "ok",
                "closed": True,
                "ts_utc": datetime(2026, 6, 25, 10, tzinfo=timezone.utc).isoformat(),
                "requested_notional_usd": 12,
                "perps_account_delta_usd": 0.03,
            },
            {
                "mode": "live",
                "reason": "ok",
                "closed": True,
                "ts_utc": datetime(2026, 6, 25, 11, tzinfo=timezone.utc).isoformat(),
                "requested_notional_usd": 12,
                "account_delta_usd": -5,
                "perps_account_delta_usd": -0.02,
            },
            {"mode": "dry_run", "reason": "ok", "requested_notional_usd": 12},
        ]

        stats = barbell.micro_stats(rows)

        self.assertEqual(stats["live_cycles"], 2)
        self.assertEqual(stats["wins"], 1)
        self.assertAlmostEqual(stats["win_rate"], 0.5)
        self.assertAlmostEqual(stats["net_perps_delta_usd"], 0.01)
        self.assertAlmostEqual(stats["round_trip_volume_usd"], 48.0)

    def test_gate_keeps_micro_only_when_policy_blockers_remain(self):
        from scripts import sodex_event_barbell as barbell

        decision = barbell.decide_barbell(
            policy={
                "decision": "BLOCK_E2_E1_RESEARCH_ONLY",
                "regime": "BEAR",
                "blockers": ["weekly_win_rate_below_target"],
            },
            runway={
                "verdict": "MICRO_ONLY_INSUFFICIENT_FOR_EVENT_TARGET",
                "micro": {"lane_active": True},
            },
            micro={
                "live_cycles": 10,
                "win_rate": 0.8,
                "net_perps_delta_usd": 1.0,
                "daily_loss_used_usd": 0.0,
            },
        )

        self.assertEqual(decision["phase"], "MICRO_PROBE_ONLY")
        self.assertIn("weekly_win_rate_below_target", decision["blockers"])
        self.assertIn("E2DIR_FUNDING_OBI", decision["paper_now"])

    def test_gate_promotes_e2dir_micro_when_policy_and_micro_edge_pass(self):
        from scripts import sodex_event_barbell as barbell

        decision = barbell.decide_barbell(
            policy={
                "decision": "CAPPED_CATCH_UP_ALLOWED",
                "regime": "BEAR",
                "blockers": [],
            },
            runway={
                "verdict": "CATCHUP_CAPACITY_DEPENDS_ON_POLICY_LIMIT",
                "micro": {"lane_active": True},
            },
            micro={
                "live_cycles": 30,
                "win_rate": 0.72,
                "net_perps_delta_usd": 0.55,
                "daily_loss_used_usd": 0.0,
            },
        )

        self.assertEqual(decision["phase"], "E2DIR_MICRO_AMPLIFIER_CANDIDATE")
        self.assertIn("E2DIR_FUNDING_OBI", decision["live_candidate"])
        self.assertTrue(decision["requires_operator_approval"])

    def test_gate_stops_live_when_daily_loss_near_cap(self):
        from scripts import sodex_event_barbell as barbell

        decision = barbell.decide_barbell(
            policy={
                "decision": "CAPPED_CATCH_UP_ALLOWED",
                "regime": "BEAR",
                "blockers": [],
            },
            runway={"micro": {"lane_active": True, "max_daily_loss_usd": 1.0}},
            micro={
                "live_cycles": 30,
                "win_rate": 0.72,
                "net_perps_delta_usd": 0.55,
                "daily_loss_used_usd": 0.95,
            },
        )

        self.assertEqual(decision["phase"], "STOP_LIVE_RESEARCH_ONLY")
        self.assertIn("micro_daily_loss_near_cap", decision["blockers"])

    def test_gate_cools_down_micro_when_early_edge_is_negative(self):
        from scripts import sodex_event_barbell as barbell

        decision = barbell.decide_barbell(
            policy={
                "decision": "BLOCK_E2_E1_RESEARCH_ONLY",
                "regime": "BEAR",
                "blockers": ["weekly_win_rate_below_target"],
            },
            runway={"micro": {"lane_active": True, "max_daily_loss_usd": 1.0}},
            micro={
                "live_cycles": 4,
                "win_rate": 0.25,
                "net_perps_delta_usd": -0.49,
                "daily_loss_used_usd": 0.51,
            },
        )

        self.assertEqual(decision["phase"], "MICRO_EDGE_NEGATIVE_COOLDOWN")
        self.assertEqual(decision["live_now"], [])
        self.assertIn("micro_edge_negative", decision["blockers"])
