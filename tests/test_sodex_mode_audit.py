from unittest import TestCase


class SodexModeAuditTests(TestCase):
    def test_catalog_contains_current_major_modes_and_rejects_legacy_churn(self):
        from scripts import sodex_mode_audit as audit

        names = {mode.name: mode for mode in audit.MODE_CATALOG}

        self.assertIn("E1_SPOT_FLYWHEEL", names)
        self.assertIn("E2DIR_FUNDING_OBI", names)
        self.assertIn("PREGain_TOP_LOSER_BRIDGE", names)
        self.assertIn("MICRO_PRE_LOSER_SHORT", names)
        self.assertEqual(names["E2_CHURN_MAKER"].verdict, "REJECT")

    def test_combination_uses_micro_now_and_e2dir_after_gate(self):
        from scripts import sodex_mode_audit as audit

        combo = audit.select_combination(
            {
                "blockers": [
                    "e1_no_loss_coverage_short",
                    "official_dashboard_not_canonical",
                    "weekly_win_rate_below_target",
                ]
            },
            {
                "phase": "PHASE_1_MICRO_ONLY",
                "needed_daily_volume_usd": 35_000,
                "micro": {
                    "lane_active": True,
                    "estimated_daily_volume_capacity_usd": 2_777,
                    "required_cycles_daily_for_target": 700,
                },
                "verdict": "MICRO_ONLY_INSUFFICIENT_FOR_EVENT_TARGET",
            },
        )

        self.assertEqual(combo["name"], "EVENT_BARBELL_V1")
        self.assertIn("MICRO_PRE_LOSER_SHORT", combo["live_now"])
        self.assertEqual(combo["promotion_target"], "E2DIR_FUNDING_OBI + PREGain_TOP_LOSER_BRIDGE")
        self.assertIn("E2_CHURN_MAKER", combo["rejected_now"])
