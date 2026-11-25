from datetime import datetime, timezone
from unittest import TestCase


class SodexRadicalGateTests(TestCase):
    def test_gate_blocks_full_real_when_ratio_and_profit_coverage_are_short(self):
        from scripts import sodex_radical_gate as gate

        report = {
            "ts": "2026-06-19T23:51:34+00:00",
            "official_dashboard": {
                "quality": "OK",
                "canonical": True,
                "volume": {"spot_usd": 132_732.25, "perps_usd": 15_520.46, "total_usd": 148_252.71},
            },
            "ledger": {
                "volume": {"raw_total_usd": 650_906.94, "weighted_total_usd": 872_416.84},
                "costs": {"fees_usd": 110.3755323221065},
                "pnl": {"realized_net_usd": 27.873073},
                "rts": {"win_rate": 0.8933},
            },
            "account": {"account_value": {"total_equity_usd": 348.750801}, "assets": {"perps_positions": [{}, {}]}},
            "verdict": {"warnings": ["official_dashboard_lower_than_internal_ledger"]},
        }

        result = gate.evaluate_radical_gate(
            report,
            now=datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(result["decision"], "BLOCK_FULL_REAL")
        self.assertIn("ratio_below_target", result["blockers"])
        self.assertIn("e1_profit_coverage_short", result["blockers"])
        self.assertIn("official_ledger_reconciliation_gap", result["blockers"])
        self.assertAlmostEqual(result["ratios"]["official_raw_net_ratio"], 1796.95, places=2)
        self.assertAlmostEqual(result["profit"]["extra_profit_needed_raw_9000"], 66.21, places=2)
        self.assertIn("e1_no_loss_coverage_short", result["blockers"])
        self.assertAlmostEqual(result["profit"]["extra_profit_needed_no_loss"], 82.50, places=2)
        self.assertEqual(result["time"]["hours_to_build_deadline"], 84)
        self.assertGreater(result["time"]["days_to_event_deadline"], 34)

    def test_gate_allows_research_to_continue_when_services_are_healthy_but_target_unmet(self):
        from scripts import sodex_radical_gate as gate

        report = {
            "ts": "2026-06-20T00:00:00+00:00",
            "official_dashboard": {
                "quality": "OK",
                "canonical": True,
                "volume": {"spot_usd": 500_000.0, "perps_usd": 500_000.0, "total_usd": 1_000_000.0},
            },
            "ledger": {
                "volume": {"raw_total_usd": 1_000_000.0, "weighted_total_usd": 1_500_000.0},
                "costs": {"fees_usd": 130.0},
                "pnl": {"realized_net_usd": 130.0},
                "rts": {"win_rate": 0.75},
            },
            "account": {"account_value": {"total_equity_usd": 600.0}, "assets": {"perps_positions": []}},
            "verdict": {"warnings": []},
        }

        result = gate.evaluate_radical_gate(
            report,
            now=datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(result["decision"], "RESEARCH_AND_CAPPED_CATCHUP")
        self.assertIn("volume_below_weekly_target", result["blockers"])
        self.assertNotIn("ratio_below_target", result["blockers"])

    def test_gate_blocks_when_position_truth_disagrees_with_assets(self):
        from scripts import sodex_radical_gate as gate

        report = {
            "ts": "2026-07-08T00:00:00+00:00",
            "official_dashboard": {
                "quality": "OK",
                "canonical": True,
                "volume": {"spot_usd": 650_000.0, "perps_usd": 650_000.0, "total_usd": 1_300_000.0},
            },
            "ledger": {
                "volume": {"raw_total_usd": 1_300_000.0, "weighted_total_usd": 1_950_000.0},
                "costs": {"fees_usd": 100.0},
                "pnl": {"realized_net_usd": 120.0},
                "rts": {"win_rate": 0.75},
            },
            "account": {
                "account_value": {"total_equity_usd": 600.0},
                "assets": {"perps_positions": []},
                "position_truth": {"quality": "DISAGREE", "open_count": 1, "positions_endpoint_count": 0, "state_P_count": 1},
            },
            "verdict": {"warnings": []},
        }

        result = gate.evaluate_radical_gate(
            report,
            now=datetime(2026, 7, 8, 0, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(result["decision"], "BLOCK_FULL_REAL")
        self.assertIn("open_perp_positions_present", result["blockers"])
        self.assertIn("position_truth_unverified", result["blockers"])

    def test_gate_does_not_count_stale_official_dashboard_as_real_ratio(self):
        from scripts import sodex_radical_gate as gate

        report = {
            "ts": "2026-06-20T00:02:19+00:00",
            "official_dashboard": {
                "quality": "STALE_OR_EMPTY",
                "canonical": False,
                "volume": {"spot_usd": 132_732.25, "perps_usd": 15_520.46, "total_usd": 148_252.71},
            },
            "ledger": {
                "volume": {"raw_total_usd": 148.85, "weighted_total_usd": 297.70},
                "costs": {"fees_usd": 0.0},
                "pnl": {"realized_net_usd": 0.198944},
                "rts": {"win_rate": 0.6667},
            },
            "account": {"account_value": {"total_equity_usd": 347.325004}, "assets": {"perps_positions": [{}, {}, {}]}},
            "verdict": {"warnings": ["official_dashboard_window_mismatch"]},
        }

        result = gate.evaluate_radical_gate(
            report,
            now=datetime(2026, 6, 20, 0, 2, tzinfo=timezone.utc),
        )

        self.assertEqual(result["decision"], "BLOCK_FULL_REAL")
        self.assertIn("official_dashboard_not_canonical", result["blockers"])
        self.assertEqual(result["volumes"]["official_raw_usd"], 0.0)
        self.assertIsNone(result["ratios"]["official_raw_net_ratio"])
