from unittest import TestCase


class SodexReconciliationAuditTests(TestCase):
    def test_reconciliation_audit_quantifies_official_credit_gap_and_e1_need(self):
        from scripts import sodex_reconciliation_audit as audit

        report = {
            "official_dashboard": {
                "quality": "OK",
                "canonical": True,
                "volume": {
                    "spot_usd": 132_732.25,
                    "perps_usd": 15_520.46,
                    "total_usd": 148_252.71,
                },
            },
            "ledger": {
                "volume": {
                    "spot_usd": 221_967.01,
                    "perps_usd": 429_397.04,
                    "raw_total_usd": 651_364.05,
                    "weighted_total_usd": 873_331.06,
                },
                "costs": {"fees_usd": 110.375532},
                "pnl": {"realized_net_usd": 27.731779},
            },
            "account": {"assets": {"perps_positions": [{}, {}]}},
        }

        result = audit.analyze_report(report)

        self.assertEqual(result["decision"], "RECON_FIRST_E1_PROFIT_FIRST")
        self.assertIn("official_total_credit_rate_low", result["blockers"])
        self.assertIn("perps_credit_rate_critical", result["blockers"])
        self.assertIn("e1_profit_coverage_short", result["blockers"])
        self.assertIn("e1_no_loss_coverage_short", result["blockers"])
        self.assertAlmostEqual(result["credit_rates"]["spot"], 0.5980, places=4)
        self.assertAlmostEqual(result["credit_rates"]["perps"], 0.0361, places=4)
        self.assertAlmostEqual(result["credit_rates"]["total"], 0.2276, places=4)
        self.assertAlmostEqual(result["requirements"]["extra_profit_for_raw_target_ratio"], 52.99, places=2)
        self.assertAlmostEqual(result["requirements"]["extra_profit_for_no_loss"], 82.64, places=2)
        # TARGET_WEEKLY_VOLUME_USD = 550_000 (revised 2026-07-22); remaining = 550_000 - 148_252.71 = 401_747.29
        self.assertAlmostEqual(result["requirements"]["official_remaining_to_weekly_target"], 401_747.29, places=2)

    def test_reconciliation_audit_allows_e2_only_when_credit_and_profit_are_clear(self):
        from scripts import sodex_reconciliation_audit as audit

        report = {
            "official_dashboard": {
                "quality": "OK",
                "canonical": True,
                "volume": {"spot_usd": 650_000.0, "perps_usd": 650_000.0, "total_usd": 1_300_000.0},
            },
            "ledger": {
                "volume": {
                    "spot_usd": 700_000.0,
                    "perps_usd": 700_000.0,
                    "raw_total_usd": 1_400_000.0,
                    "weighted_total_usd": 2_100_000.0,
                },
                "costs": {"fees_usd": 160.0},
                "pnl": {"realized_net_usd": 160.0},
            },
            "account": {"assets": {"perps_positions": []}},
        }

        result = audit.analyze_report(report)

        self.assertEqual(result["decision"], "E2_CAPPED_SCALE_ALLOWED")
        self.assertEqual(result["blockers"], [])
        self.assertIsNone(result["ratios"]["official_raw_net_ratio"])
        self.assertEqual(result["requirements"]["net_cost_usd"], 0.0)

    def test_reconciliation_audit_blocks_false_flat_position_truth(self):
        from scripts import sodex_reconciliation_audit as audit

        report = {
            "official_dashboard": {
                "quality": "OK",
                "canonical": True,
                "volume": {"spot_usd": 650_000.0, "perps_usd": 650_000.0, "total_usd": 1_300_000.0},
            },
            "ledger": {
                "volume": {
                    "spot_usd": 650_000.0,
                    "perps_usd": 650_000.0,
                    "raw_total_usd": 1_300_000.0,
                    "weighted_total_usd": 1_950_000.0,
                },
                "costs": {"fees_usd": 100.0},
                "pnl": {"realized_net_usd": 100.0},
            },
            "account": {
                "assets": {"perps_positions": []},
                "position_truth": {"quality": "DISAGREE", "open_count": 1, "positions_endpoint_count": 0, "state_P_count": 1},
            },
        }

        result = audit.analyze_report(report)

        self.assertEqual(result["decision"], "RECON_FIRST_E1_PROFIT_FIRST")
        self.assertIn("open_perp_positions_present", result["blockers"])
        self.assertIn("position_truth_unverified", result["blockers"])

    def test_reconciliation_audit_rejects_stale_official_dashboard_after_weekly_reset(self):
        from scripts import sodex_reconciliation_audit as audit

        report = {
            "official_dashboard": {
                "quality": "STALE_OR_EMPTY",
                "canonical": False,
                "volume": {"spot_usd": 132_732.25, "perps_usd": 15_520.46, "total_usd": 148_252.71},
            },
            "ledger": {
                "volume": {
                    "spot_usd": 148.85,
                    "perps_usd": 0.0,
                    "raw_total_usd": 148.85,
                    "weighted_total_usd": 297.70,
                },
                "costs": {"fees_usd": 0.0},
                "pnl": {"realized_net_usd": 0.198944},
            },
            "account": {"assets": {"perps_positions": [{}, {}, {}]}},
        }

        result = audit.analyze_report(report)

        self.assertEqual(result["decision"], "RECON_FIRST_E1_PROFIT_FIRST")
        self.assertIn("official_dashboard_not_canonical", result["blockers"])
        self.assertEqual(result["official"]["total_usd"], 0.0)
        self.assertIsNone(result["ratios"]["official_raw_net_ratio"])
