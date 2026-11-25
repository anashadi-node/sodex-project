import json
import tempfile
from pathlib import Path
from unittest import TestCase


class SodexVolumePlannerTests(TestCase):
    def test_default_target_matches_farming_doctrine(self):
        from scripts import sodex_volume_planner as planner

        self.assertEqual(planner.TARGET_WEEKLY_VOLUME_USD, 1_300_000)
        self.assertEqual(planner.TARGET_VOLUME_FEE_RATIO, 7_000)  # post-emergency base ratio
        self.assertIsNone(planner.TARGET_REAL_RATIO_MAX)
        self.assertEqual(planner.DEFAULT_ADDITIONAL_SPOT_CAPITAL_USD, 100)
        self.assertEqual(planner.DEFAULT_ADDITIONAL_PERP_CAPITAL_USD, 150)

    def test_monitor_context_reads_official_volume_and_equity(self):
        from scripts import sodex_volume_planner as planner

        payload = {
            "account": {"account_value": {"total_equity_usd": 399.78}},
            "official_dashboard": {
                "quality": "OK",
                "canonical": True,
                "volume": {
                    "spot_usd": 132_732.25,
                    "perps_usd": 15_520.46,
                    "total_usd": 148_252.71,
                },
                "reconciliation": {"total_delta_usd": 487_965.58},
            },
            "ledger": {
                "volume": {"raw_total_usd": 636_218.29, "weighted_total_usd": 843_039.55},
                "costs": {"fees_usd": 110.38},
                "pnl": {"realized_net_usd": 31.35},
                "rts": {"win_rate": 0.9111},
                "ratios": {"cost_coverage_realized_pnl_over_fee": 0.284},
            },
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "latest.json"
            path.write_text(json.dumps(payload))

            ctx = planner.load_monitor_context(path)

        self.assertEqual(ctx.capital_usd, 399.78)
        self.assertEqual(ctx.official_spot_usd, 132_732.25)
        self.assertEqual(ctx.official_futures_usd, 15_520.46)
        self.assertEqual(ctx.official_volume_usd, 148_252.71)
        self.assertEqual(ctx.canonical_volume_usd, 148_252.71)
        self.assertEqual(ctx.ledger_weighted_usd, 843_039.55)
        self.assertTrue(ctx.official_lagging_ledger)

    def test_catchup_plan_uses_four_day_horizon_and_pnl_guard(self):
        from scripts import sodex_volume_planner as planner

        ctx = planner.MonitorContext(
            capital_usd=399.78,
            official_volume_usd=148_252.71,
            canonical_volume_usd=148_252.71,
            ledger_raw_usd=636_218.29,
            ledger_weighted_usd=843_039.55,
            fees_usd=110.38,
            realized_pnl_usd=31.35,
            win_rate=0.9111,
            cost_coverage=0.284,
            official_lagging_ledger=True,
        )

        plan = planner.build_catchup_plan(ctx, target_volume=1_300_000, max_days=4)

        self.assertAlmostEqual(plan["remaining_volume_usd"], 1_151_747.29, places=2)
        self.assertAlmostEqual(plan["required_volume_per_day_usd"], 287_936.8225, places=4)
        self.assertEqual(plan["horizon_hours"], 96)
        self.assertEqual(plan["risk_mode"], "CAPPED_CATCH_UP_RECON_FIRST")
        self.assertIn("official_dashboard_lower_than_internal_ledger", plan["guards"])

    def test_real_ratios_separate_sodex_official_and_internal_ledger(self):
        from scripts import sodex_volume_planner as planner

        ctx = planner.MonitorContext(
            official_spot_usd=132_732.25,
            official_futures_usd=15_520.46,
            official_volume_usd=148_252.71,
            canonical_volume_usd=148_252.71,
            ledger_raw_usd=649_986.16,
            ledger_weighted_usd=870_575.29,
            fees_usd=110.3755323221065,
            realized_pnl_usd=28.576291,
        )

        ratios = planner.compute_real_ratios(ctx, target_volume=1_300_000)

        self.assertAlmostEqual(ratios["official_weighted_volume_usd"], 280_984.96, places=2)
        self.assertAlmostEqual(ratios["official_raw_volume_fee_ratio"], 1343.17, places=2)
        self.assertAlmostEqual(ratios["official_weighted_volume_fee_ratio"], 2545.72, places=2)
        self.assertAlmostEqual(ratios["ledger_raw_volume_fee_ratio"], 5888.86, places=2)
        self.assertAlmostEqual(ratios["ledger_weighted_volume_fee_ratio"], 7887.39, places=2)
        self.assertAlmostEqual(ratios["official_raw_net_cost_ratio"], 1812.40, places=2)
        self.assertAlmostEqual(ratios["official_weighted_net_cost_ratio"], 3435.06, places=2)
        # profit_needed = fees - (official_volume / 7000) = 110.3755 - (148252.71 / 7000) = 89.20
        self.assertAlmostEqual(ratios["profit_needed_for_official_raw_target_ratio"], 89.20, places=2)
        self.assertAlmostEqual(ratios["extra_profit_needed_for_official_raw_target_ratio"], 60.62, places=2)
        self.assertAlmostEqual(ratios["profit_needed_for_no_loss"], 110.38, places=2)
        self.assertAlmostEqual(ratios["extra_profit_needed_for_no_loss"], 81.80, places=2)

    def test_capital_topup_model_keeps_spot_and_perp_separate(self):
        from scripts import sodex_volume_planner as planner

        ctx = planner.MonitorContext(capital_usd=382.48)

        topup = planner.build_capital_topup_model(ctx)

        self.assertAlmostEqual(topup["current_capital_usd"], 382.48)
        self.assertAlmostEqual(topup["additional_spot_usd"], 100.0)
        self.assertAlmostEqual(topup["additional_perp_usd"], 150.0)
        self.assertAlmostEqual(topup["projected_total_capital_usd"], 632.48)
        self.assertAlmostEqual(topup["max_loss_budget_25pct_usd"], 158.12)

    def test_stale_official_dashboard_is_not_counted_as_current_official_volume(self):
        from scripts import sodex_volume_planner as planner

        payload = {
            "account": {"account_value": {"total_equity_usd": 382.54}},
            "official_dashboard": {
                "quality": "STALE_OR_EMPTY",
                "canonical": False,
                "volume": {
                    "spot_usd": 132_732.25,
                    "perps_usd": 15_520.46,
                    "total_usd": 148_252.71,
                },
            },
            "ledger": {
                "volume": {"raw_total_usd": 307.87, "weighted_total_usd": 615.73},
                "costs": {"fees_usd": 0.0},
                "pnl": {"realized_net_usd": 0.289576},
            },
            "verdict": {
                "progress": {
                    "canonical_volume_usd": 307.87,
                    "canonical_volume_source": "internal_ledger",
                }
            },
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "latest.json"
            path.write_text(json.dumps(payload))

            ctx = planner.load_monitor_context(path)
            ratios = planner.compute_real_ratios(ctx)

        self.assertEqual(ctx.official_volume_usd, 0.0)
        self.assertEqual(ctx.canonical_volume_usd, 307.87)
        self.assertFalse(ctx.official_lagging_ledger)
        self.assertIsNone(ratios["official_raw_volume_fee_ratio"])
        self.assertEqual(planner.fmt_ratio(None), "n/a")

    def test_e1_subsidy_math_shows_pure_maker_still_needs_profit_for_9000_ratio(self):
        from scripts import sodex_volume_planner as planner

        subsidy = planner.required_e1_subsidy_for_ratio(
            volume_usd=1_300_000.0,
            gross_cost_usd=156.0,
            target_ratio=9_000.0,
        )

        self.assertAlmostEqual(subsidy["max_net_cost_usd"], 144.444444, places=6)
        self.assertAlmostEqual(subsidy["required_e1_profit_usd"], 11.555556, places=6)
        self.assertAlmostEqual(subsidy["gross_ratio"], 8333.333333, places=6)
        self.assertAlmostEqual(subsidy["subsidized_ratio"], 9000.0, places=6)
