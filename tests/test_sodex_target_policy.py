import json
import tempfile
import time
from pathlib import Path
from unittest import TestCase


class SodexTargetPolicyTests(TestCase):
    def test_current_bad_week_blocks_e2_and_keeps_e1_research_only(self):
        from scripts import sodex_target_policy as policy

        report = {
            "official_dashboard": {
                "quality": "STALE_OR_EMPTY",
                "canonical": False,
                "volume": {"total_usd": 0.0, "spot_usd": 0.0, "perps_usd": 0.0},
            },
            "ledger": {
                "volume": {"raw_total_usd": 256_627.77, "weighted_total_usd": 464_945.66},
                "costs": {"fees_usd": 69.3992},
                "pnl": {"realized_net_usd": 2.3444},
                "rts": {"win_rate": 0.4097},
                "coverage": {"e1_covers_all_fees": False, "combined_no_loss": False},
            },
            "account": {"account_value": {"total_equity_usd": 870.44}, "assets": {"perps_positions": [{}, {}]}},
            "market": {"regime": "BEAR"},
        }

        with tempfile.TemporaryDirectory() as td:
            result = policy.evaluate_target_policy(report, horizon_hours=96, intel_dir=Path(td))

        self.assertEqual(result["decision"], "BLOCK_E2_E1_RESEARCH_ONLY")
        self.assertEqual(result["limits"]["max_e2_hourly_volume_usd"], 0.0)
        self.assertIn("official_dashboard_not_canonical", result["blockers"])
        self.assertIn("weekly_win_rate_below_target", result["blockers"])
        self.assertIn("e1_no_loss_coverage_short", result["blockers"])
        self.assertIn("open_perp_positions_present", result["blockers"])
        self.assertIn("PRE_LOSER_SHORT_RESEARCH", result["methods"])
        self.assertIn("OFFICIAL_RECONCILIATION_FIRST", result["methods"])
        self.assertNotIn("RATIO_RECOVERY_MAKER_ONLY", [lane["lane"] for lane in result["opportunity_lanes"]])

    def test_healthy_week_allows_capped_catchup_volume(self):
        from scripts import sodex_target_policy as policy

        report = {
            "official_dashboard": {
                "quality": "OK",
                "canonical": True,
                "volume": {"total_usd": 1_000_000.0, "spot_usd": 250_000.0, "perps_usd": 750_000.0},
            },
            "ledger": {
                "volume": {"raw_total_usd": 1_000_000.0, "weighted_total_usd": 1_250_000.0},
                "costs": {"fees_usd": 100.0},
                "pnl": {"realized_net_usd": 140.0},
                "rts": {"win_rate": 0.75},
                "coverage": {"e1_covers_all_fees": True, "combined_no_loss": True},
            },
            "account": {"account_value": {"total_equity_usd": 1_100.0}, "assets": {"perps_positions": []}},
            "market": {"regime": "SIDEWAYS"},
        }

        with tempfile.TemporaryDirectory() as td:
            result = policy.evaluate_target_policy(report, horizon_hours=96, intel_dir=Path(td))

        self.assertEqual(result["decision"], "CAPPED_CATCH_UP_ALLOWED")
        self.assertAlmostEqual(result["limits"]["max_e2_hourly_volume_usd"], 3_125.0)
        self.assertLessEqual(result["limits"]["max_daily_loss_usd"], 11.0)
        self.assertIn("E2_MAKER_VOLUME_CATCHUP", result["methods"])
        self.assertIn("SIDEWAYS_DUAL_SIDED_MARKET_MAKING", result["methods"])
        self.assertEqual(result["blockers"], [])

    def test_safety_halt_blocks_all_live_lanes_even_when_metrics_are_healthy(self):
        from scripts import sodex_target_policy as policy

        report = {
            "halt_status": {"active": True, "kind": "SAFETY_HALT"},
            "official_dashboard": {
                "quality": "OK",
                "canonical": True,
                "volume": {"total_usd": 1_000_000.0, "spot_usd": 250_000.0, "perps_usd": 750_000.0},
            },
            "ledger": {
                "costs": {"fees_usd": 100.0},
                "pnl": {"realized_net_usd": 140.0},
                "rts": {"win_rate": 0.75},
                "coverage": {"e1_covers_all_fees": True, "combined_no_loss": True},
            },
            "account": {"account_value": {"total_equity_usd": 1_100.0}, "assets": {"perps_positions": []}},
            "market": {"regime": "BEAR"},
        }

        with tempfile.TemporaryDirectory() as td:
            result = policy.evaluate_target_policy(report, horizon_hours=96, intel_dir=Path(td))

        self.assertEqual(result["decision"], "SAFETY_HALT_ACTIVE")
        self.assertIn("safety_halt_active", result["blockers"])
        self.assertIn("HALT_FILE_GUARD", result["methods"])
        self.assertIn("MICRO_PRE_LOSER_SHORT_ONLY", result["blocked_lanes"])
        self.assertEqual(result["opportunity_lanes"], [])
        self.assertEqual(result["limits"]["max_daily_loss_usd"], 0.0)
        self.assertEqual(result["limits"]["max_inventory_usd"], 0.0)

    def test_safety_halt_red_bear_flat_exposes_short_pilot_candidate(self):
        from scripts import sodex_target_policy as policy

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "intel_20260709.jsonl"
            path.write_text(json.dumps({
                "ts": time.time(),
                "composite_score": 50.0,
                "fc_BTC_dir_enc": 0,
                "fc_BTC_conf": 0.0,
                "fc_BTC_agreement": 0.0,
                "event_risk_level": "RED",
                "event_risk_score": 82.0,
            }) + "\n")

            result = policy.evaluate_target_policy(
                {
                    "halt_status": {"active": True, "kind": "SAFETY_HALT"},
                    "official_dashboard": {
                        "quality": "STALE_OR_EMPTY",
                        "canonical": False,
                        "volume": {"total_usd": 0.0, "spot_usd": 0.0, "perps_usd": 0.0},
                    },
                    "ledger": {
                        "costs": {"fees_usd": 1.0},
                        "pnl": {"realized_net_usd": -0.2},
                        "rts": {"win_rate": 0.22},
                        "coverage": {"e1_covers_all_fees": False, "combined_no_loss": False},
                    },
                    "account": {
                        "account_value": {"total_equity_usd": 538.0},
                        "assets": {"perps_positions": []},
                        "position_truth": {"quality": "OK", "open_count": 0},
                    },
                },
                intel_dir=Path(td),
            )

        self.assertEqual(result["decision"], "SAFETY_HALT_SHORT_PILOT_CANDIDATE")
        self.assertIn("safety_halt_active", result["blockers"])
        self.assertIn("SAFETY_HALT_BEAR_SHORT_RELAXATION", result["methods"])
        lanes = {lane["lane"]: lane for lane in result["opportunity_lanes"]}
        self.assertIn("SAFETY_HALT_SHORT_PILOT", lanes)
        self.assertLessEqual(lanes["SAFETY_HALT_SHORT_PILOT"]["max_notional_usd"], 15.0)
        expected_ratio = 7000.0  # post-emergency base ratio
        self.assertEqual(lanes["SAFETY_HALT_SHORT_PILOT"]["min_volume_loss_ratio"], expected_ratio)
        self.assertAlmostEqual(
            lanes["SAFETY_HALT_SHORT_PILOT"]["max_loss_for_min_ratio_usd"],
            lanes["SAFETY_HALT_SHORT_PILOT"]["projected_roundtrip_volume_usd"] / expected_ratio,
        )
        self.assertLess(lanes["SAFETY_HALT_SHORT_PILOT"]["max_daily_loss_usd"], 0.01)
        self.assertNotIn("MICRO_PRE_LOSER_SHORT_ONLY", result["blocked_lanes"])
        self.assertIn("LONG_SPOT_INVENTORY", result["blocked_lanes"])

    def test_position_truth_overrides_false_flat_assets(self):
        from scripts import sodex_target_policy as policy

        report = {
            "official_dashboard": {
                "quality": "OK",
                "canonical": True,
                "volume": {"total_usd": 1_300_000.0, "spot_usd": 300_000.0, "perps_usd": 1_000_000.0},
            },
            "ledger": {
                "costs": {"fees_usd": 100.0},
                "pnl": {"realized_net_usd": 140.0},
                "rts": {"win_rate": 0.75},
                "coverage": {"e1_covers_all_fees": True, "combined_no_loss": True},
            },
            "account": {
                "account_value": {"total_equity_usd": 1_100.0},
                "assets": {"perps_positions": []},
                "position_truth": {
                    "quality": "DISAGREE",
                    "open_count": 1,
                    "positions_endpoint_count": 0,
                    "state_P_count": 1,
                },
            },
            "market": {"regime": "SIDEWAYS"},
        }

        result = policy.evaluate_target_policy(report, horizon_hours=96)

        self.assertEqual(result["decision"], "BLOCK_E2_E1_RESEARCH_ONLY")
        self.assertIn("open_perp_positions_present", result["blockers"])
        self.assertIn("position_truth_unverified", result["blockers"])
        self.assertEqual(result["metrics"]["open_perp_positions"], 1)

    def test_bear_regime_forbids_long_inventory_and_prefers_pre_loser_short(self):
        from scripts import sodex_target_policy as policy

        result = policy.evaluate_target_policy(
            {
                "official_dashboard": {
                    "quality": "OK",
                    "canonical": True,
                    "volume": {"total_usd": 1_300_000.0, "spot_usd": 400_000.0, "perps_usd": 900_000.0},
                },
                "ledger": {
                    "costs": {"fees_usd": 120.0},
                    "pnl": {"realized_net_usd": 150.0},
                    "rts": {"win_rate": 0.78},
                    "coverage": {"e1_covers_all_fees": True, "combined_no_loss": True},
                },
                "account": {"account_value": {"total_equity_usd": 1_200.0}, "assets": {"perps_positions": []}},
                "market": {"regime": "BEAR"},
            }
        )

        self.assertIn("PRE_LOSER_SHORT_RESEARCH", result["methods"])
        self.assertIn("ASK_BIASED_MARKET_MAKING", result["methods"])
        self.assertIn("LONG_SPOT_INVENTORY", result["blocked_lanes"])
        self.assertNotIn("PRE_GAIN_LONG_INVENTORY_SCALE", result["methods"])
        lanes = {lane["lane"]: lane for lane in result["opportunity_lanes"]}
        self.assertIn("MICRO_PRE_LOSER_SHORT_ONLY", lanes)
        self.assertEqual(lanes["MICRO_PRE_LOSER_SHORT_ONLY"]["max_notional_usd"], 25.0)

    def test_micro_pilot_is_not_allowed_with_open_perps(self):
        from scripts import sodex_target_policy as policy

        result = policy.evaluate_target_policy(
            {
                "official_dashboard": {
                    "quality": "OK",
                    "canonical": True,
                    "volume": {"total_usd": 1_300_000.0},
                },
                "ledger": {
                    "costs": {"fees_usd": 120.0},
                    "pnl": {"realized_net_usd": 150.0},
                    "rts": {"win_rate": 0.78},
                    "coverage": {"e1_covers_all_fees": True, "combined_no_loss": True},
                },
                "account": {
                    "account_value": {"total_equity_usd": 1_200.0},
                    "assets": {"perps_positions": [{"symbol": "BTC-USD"}]},
                },
                "market": {"regime": "BEAR"},
            }
        )

        self.assertEqual(result["opportunity_lanes"], [])

    def test_chaos_regime_pauses_real_volume_even_when_metrics_are_good(self):
        from scripts import sodex_target_policy as policy

        result = policy.evaluate_target_policy(
            {
                "official_dashboard": {
                    "quality": "OK",
                    "canonical": True,
                    "volume": {"total_usd": 1_000_000.0},
                },
                "ledger": {
                    "costs": {"fees_usd": 80.0},
                    "pnl": {"realized_net_usd": 120.0},
                    "rts": {"win_rate": 0.8},
                    "coverage": {"e1_covers_all_fees": True, "combined_no_loss": True},
                },
                "account": {"account_value": {"total_equity_usd": 900.0}, "assets": {"perps_positions": []}},
                "market": {"regime": "CHAOS"},
            }
        )

        self.assertEqual(result["decision"], "PAUSE_REAL_VOLUME_CHAOS")
        self.assertEqual(result["limits"]["max_e2_hourly_volume_usd"], 0.0)
        self.assertIn("PAPER_PRE_GAIN_PRE_LOSER_ONLY", result["methods"])

    def test_policy_uses_latest_intel_when_report_regime_is_missing(self):
        from scripts import sodex_target_policy as policy

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "intel_20260625.jsonl"
            path.write_text(json.dumps({
                "ts": time.time(),
                "composite_score": 51.0,
                "fc_BTC_dir_enc": -1,
                "fc_BTC_conf": 0.77,
                "fc_BTC_agreement": 0.72,
                "event_risk_level": "RED",
                "event_risk_score": 94.0,
            }) + "\n")

            result = policy.evaluate_target_policy(
                {
                    "official_dashboard": {
                        "quality": "OK",
                        "canonical": True,
                        "volume": {"total_usd": 1_300_000.0},
                    },
                    "ledger": {
                        "costs": {"fees_usd": 100.0},
                        "pnl": {"realized_net_usd": 130.0},
                        "rts": {"win_rate": 0.72},
                        "coverage": {"e1_covers_all_fees": True, "combined_no_loss": True},
                    },
                    "account": {"account_value": {"total_equity_usd": 1_000.0}, "assets": {"perps_positions": []}},
                },
                intel_dir=Path(td),
            )

        self.assertEqual(result["regime"], "BEAR")
        self.assertEqual(result["signal"]["regime_source"], "intel")
        self.assertTrue(result["signal"]["fresh"])
        self.assertLessEqual(result["signal"]["intel_age_min"], 1.0)
        self.assertEqual(result["signal"]["btc_dir"], -1)
        self.assertAlmostEqual(result["signal"]["btc_conf"], 0.77)
        self.assertEqual(result["signal"]["event_risk"], "RED")
        self.assertIn("PRE_LOSER_SHORT_RESEARCH", result["methods"])
        self.assertIn("LONG_SPOT_INVENTORY", result["blocked_lanes"])

    def test_policy_treats_positive_one_direction_as_bullish(self):
        from scripts import sodex_target_policy as policy

        self.assertEqual(policy.intel_regime({
            "score": 58.0,
            "btc_dir": 1,
            "btc_conf": 0.72,
            "btc_agreement": 0.70,
            "event_risk": "NORMAL",
            "event_risk_score": 0.0,
        }), "BULL")

    def test_policy_neutralizes_ineligible_forecast_direction(self):
        from scripts import sodex_target_policy as policy

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "intel_20260625.jsonl"
            path.write_text(json.dumps({
                "ts": time.time(),
                "composite_score": 62.0,
                "fc_BTC_dir_enc": -1,
                "fc_BTC_conf": 0.91,
                "fc_BTC_agreement": 0.88,
                "fc_BTC_eligible": False,
                "fc_BTC_quality": "DEGRADED_LLM_FALLBACK",
            }) + "\n")

            sig = policy.read_intel_signal(Path(td))

        self.assertIsNotNone(sig)
        self.assertEqual(sig["btc_dir"], 0)
        self.assertEqual(sig["btc_conf"], 0.0)
        self.assertEqual(sig["btc_agreement"], 0.0)
        self.assertFalse(sig["btc_eligible"])

    def test_missing_market_direction_blocks_real_volume_and_refreshes_intel(self):
        from scripts import sodex_target_policy as policy

        with tempfile.TemporaryDirectory() as td:
            result = policy.evaluate_target_policy(
                {
                    "official_dashboard": {
                        "quality": "OK",
                        "canonical": True,
                        "volume": {"total_usd": 1_300_000.0},
                    },
                    "ledger": {
                        "costs": {"fees_usd": 100.0},
                        "pnl": {"realized_net_usd": 130.0},
                        "rts": {"win_rate": 0.72},
                        "coverage": {"e1_covers_all_fees": True, "combined_no_loss": True},
                    },
                    "account": {"account_value": {"total_equity_usd": 1_000.0}, "assets": {"perps_positions": []}},
                },
                intel_dir=Path(td),
            )

        self.assertEqual(result["decision"], "BLOCK_E2_E1_RESEARCH_ONLY")
        self.assertEqual(result["regime"], "UNKNOWN")
        self.assertEqual(result["signal"]["regime_source"], "unknown")
        self.assertFalse(result["signal"]["fresh"])
        self.assertIn("market_direction_signal_missing", result["blockers"])
        self.assertIn("REFRESH_INTELLIGENCE_FEEDS", result["methods"])
        self.assertEqual(result["limits"]["max_e2_hourly_volume_usd"], 0.0)

    def test_stale_market_direction_blocks_real_volume(self):
        from scripts import sodex_target_policy as policy

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "intel_20260625.jsonl"
            path.write_text(json.dumps({
                "ts": time.time() - 4 * 3600,
                "composite_score": 66.0,
                "fc_BTC_dir_enc": 2,
                "fc_BTC_conf": 0.82,
                "fc_BTC_agreement": 0.81,
                "event_risk_level": "GREEN",
                "event_risk_score": 10.0,
            }) + "\n")

            result = policy.evaluate_target_policy(
                {
                    "official_dashboard": {
                        "quality": "OK",
                        "canonical": True,
                        "volume": {"total_usd": 1_300_000.0},
                    },
                    "ledger": {
                        "costs": {"fees_usd": 100.0},
                        "pnl": {"realized_net_usd": 130.0},
                        "rts": {"win_rate": 0.72},
                        "coverage": {"e1_covers_all_fees": True, "combined_no_loss": True},
                    },
                    "account": {"account_value": {"total_equity_usd": 1_000.0}, "assets": {"perps_positions": []}},
                },
                intel_dir=Path(td),
            )

        self.assertEqual(result["decision"], "BLOCK_E2_E1_RESEARCH_ONLY")
        self.assertEqual(result["signal"]["regime_source"], "intel")
        self.assertFalse(result["signal"]["fresh"])
        self.assertGreater(result["signal"]["intel_age_min"], 90.0)
        self.assertIn("market_direction_signal_stale", result["blockers"])
        self.assertIn("REFRESH_INTELLIGENCE_FEEDS", result["methods"])

    def test_deadline_micro_catchup_allows_small_lane_when_only_soft_blockers_remain(self):
        from scripts import sodex_target_policy as policy

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "intel_20260625.jsonl"
            path.write_text(json.dumps({
                "ts": time.time(),
                "composite_score": 47.0,
                "fc_BTC_dir_enc": 0,
                "fc_BTC_conf": 0.5,
                "fc_BTC_agreement": 0.0,
                "event_risk_level": "RED",
                "event_risk_score": 82.0,
            }) + "\n")

            result = policy.evaluate_target_policy(
                {
                    "official_dashboard": {
                        "quality": "STALE_OR_EMPTY",
                        "canonical": False,
                        "volume": {"total_usd": 0.0},
                    },
                    "ledger": {
                        "costs": {"fees_usd": 70.0},
                        "pnl": {"realized_net_usd": 2.0},
                        "rts": {"win_rate": 0.42},
                        "coverage": {"e1_covers_all_fees": False, "combined_no_loss": True},
                    },
                    "account": {"account_value": {"total_equity_usd": 900.0}, "assets": {"perps_positions": []}},
                },
                intel_dir=Path(td),
            )

        self.assertEqual(result["decision"], "DEADLINE_MICRO_CATCHUP_ONLY")
        self.assertIn("DEADLINE_FLEX_MICRO_CATCHUP", result["methods"])
        lanes = {lane["lane"]: lane for lane in result["opportunity_lanes"]}
        self.assertIn("DEADLINE_MICRO_CATCHUP", lanes)
        self.assertEqual(lanes["DEADLINE_MICRO_CATCHUP"]["max_notional_usd"], 36.0)
        self.assertEqual(lanes["DEADLINE_MICRO_CATCHUP"]["max_daily_loss_usd"], 1.75)

    def test_ratio_recovery_maker_lane_opens_when_flat_and_signal_fresh(self):
        from scripts import sodex_target_policy as policy

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "intel_20260715.jsonl"
            path.write_text(json.dumps({
                "ts": time.time(),
                "composite_score": 50.0,
                "fc_BTC_dir_enc": 1,
                "fc_BTC_conf": 0.7,
                "fc_BTC_agreement": 0.7,
                "event_risk_level": "RED",
                "event_risk_score": 100.0,
            }) + "\n")

            result = policy.evaluate_target_policy(
                {
                    "official_dashboard": {"quality": "STALE_OR_EMPTY", "canonical": False, "volume": {"total_usd": 0.0}},
                    "ledger": {
                        "costs": {"fees_usd": 1.8},
                        "pnl": {"realized_net_usd": -4.5},
                        "rts": {"win_rate": 0.26},
                        "coverage": {"e1_covers_all_fees": False, "combined_no_loss": False},
                    },
                    "account": {
                        "account_value": {"total_equity_usd": 371.0},
                        "assets": {"perps_positions": []},
                        "position_truth": {"quality": "OK", "open_count": 0},
                    },
                },
                intel_dir=Path(td),
            )

        self.assertEqual(result["decision"], "BLOCK_E2_E1_RESEARCH_ONLY")
        lanes = {lane["lane"]: lane for lane in result["opportunity_lanes"]}
        self.assertIn("RATIO_RECOVERY_MAKER_ONLY", lanes)
        lane = lanes["RATIO_RECOVERY_MAKER_ONLY"]
        expected_ratio = 7000.0  # post-emergency base ratio (emergency expired 2026-07-18)
        self.assertEqual(lanes["RATIO_RECOVERY_MAKER_ONLY"]["min_volume_loss_ratio"], expected_ratio)
        self.assertEqual(lane["mode"], "OPERATOR_APPROVED_DAILY_RATIO_RECOVERY")
        self.assertEqual(lane["max_cycles_daily"], 288)
        self.assertEqual(lane["cycle_interval_seconds"], 300)
        self.assertAlmostEqual(lane["max_notional_usd"], 111.3)
        self.assertAlmostEqual(lane["target_daily_volume_usd"], 64108.8)
        self.assertAlmostEqual(lane["capacity_limited_daily_volume_usd"], 64108.8)
        self.assertEqual(lane["operator_budget_daily_loss_usd"], 100.0)
        self.assertEqual(lane["operator_budget_daily_volume_usd"], expected_ratio * 100.0)
        self.assertTrue(lane["capacity_limited"])
        self.assertAlmostEqual(
            lane["max_loss_for_min_ratio_usd"],
            lane["target_daily_volume_usd"] / expected_ratio,
        )
        self.assertAlmostEqual(lane["max_daily_loss_usd"], lane["target_daily_volume_usd"] / expected_ratio)
        self.assertIn("RATIO_RECOVERY_MAKER_ONLY", result["methods"])

    def test_ratio_recovery_operator_budget_caps_large_account_volume(self):
        from scripts import sodex_target_policy as policy

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "intel_20260715.jsonl"
            path.write_text(json.dumps({
                "ts": time.time(),
                "composite_score": 50.0,
                "fc_BTC_dir_enc": 1,
                "fc_BTC_conf": 0.7,
                "fc_BTC_agreement": 0.7,
                "event_risk_level": "RED",
                "event_risk_score": 100.0,
            }) + "\n")

            result = policy.evaluate_target_policy(
                {
                    "official_dashboard": {"quality": "STALE_OR_EMPTY", "canonical": False, "volume": {"total_usd": 0.0}},
                    "ledger": {
                        "costs": {"fees_usd": 1.8},
                        "pnl": {"realized_net_usd": -4.5},
                        "rts": {"win_rate": 0.26},
                        "coverage": {"e1_covers_all_fees": False, "combined_no_loss": False},
                    },
                    "account": {
                        "account_value": {"total_equity_usd": 20000.0},
                        "assets": {"perps_positions": []},
                        "position_truth": {"quality": "OK", "open_count": 0},
                    },
                },
                intel_dir=Path(td),
            )

        lanes = {lane["lane"]: lane for lane in result["opportunity_lanes"]}
        lane = lanes["RATIO_RECOVERY_MAKER_ONLY"]
        expected_ratio = 7000.0  # post-emergency base ratio
        self.assertEqual(lane["operator_budget_daily_loss_usd"], 100.0)
        self.assertEqual(lane["operator_budget_daily_volume_usd"], expected_ratio * 100.0)
        self.assertEqual(lane["target_daily_volume_usd"], expected_ratio * 100.0)
        self.assertEqual(lane["max_daily_loss_usd"], 100.0)
        # max_cycles_daily = ceil(daily_volume / (max_notional * 2)) = ceil(700000 / (2500 * 2)) = 140
        self.assertEqual(lane["max_cycles_daily"], 140)
        self.assertEqual(lane["cycle_interval_seconds"], 300)
        self.assertFalse(lane["capacity_limited"])

    def test_deadline_micro_catchup_stays_closed_when_market_signal_stale(self):
        from scripts import sodex_target_policy as policy

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "intel_20260625.jsonl"
            path.write_text(json.dumps({
                "ts": time.time() - 7200,
                "composite_score": 47.0,
                "fc_BTC_dir_enc": 0,
                "fc_BTC_conf": 0.5,
                "event_risk_level": "RED",
                "event_risk_score": 82.0,
            }) + "\n")

            result = policy.evaluate_target_policy(
                {
                    "official_dashboard": {"quality": "STALE_OR_EMPTY", "canonical": False, "volume": {"total_usd": 0.0}},
                    "ledger": {
                        "costs": {"fees_usd": 70.0},
                        "pnl": {"realized_net_usd": 2.0},
                        "rts": {"win_rate": 0.42},
                        "coverage": {"e1_covers_all_fees": False, "combined_no_loss": True},
                    },
                    "account": {"account_value": {"total_equity_usd": 900.0}, "assets": {"perps_positions": []}},
                },
                intel_dir=Path(td),
            )

        self.assertEqual(result["decision"], "BLOCK_E2_E1_RESEARCH_ONLY")
        self.assertNotIn("DEADLINE_MICRO_CATCHUP", [lane["lane"] for lane in result["opportunity_lanes"]])

    def test_watchdog_pve_activated_env_sourced_f1(self):
        # F1 OVERHAUL (2026-06-29): the watchdog now `source .env` (set -a) so every
        # TE_* (incl. TE_PVE_MAKER_PATH) propagates to the daemon child — previously
        # they didn't, so the maker path never activated. Pair/spread config moved OUT
        # of the watchdog INTO .env (single source of truth).
        #
        # BUG-B fix (2026-07-06): TE_PVE_ENABLED=1 REMOVED from watchdog. Previously
        # the hardcoded =1 overrode .env, making guardian PVE_PAUSE signals illusory.
        # Now: PVE activation is read from .env (via `source .env`). Only the PAUSE
        # gate preserves engine lifecycle so pause can drain existing exposure.
        wd = Path("scripts/watchdog_twin.sh").read_text()

        # F1 fix: env is sourced + auto-exported so TE_* reach the child process.
        self.assertIn("set -a", wd)
        self.assertIn("source .env", wd)
        # BUG-B fix: NO hardcoded TE_PVE_ENABLED=1 — deferred to .env
        self.assertNotIn("TE_PVE_ENABLED=1", wd,
                         "BUG-B fix: TE_PVE_ENABLED=1 must not be hardcoded; "
                         "value comes from .env via `source .env`")
        # Guardian's PVE_PAUSE gate must be honoured in close-only mode. The watchdog
        # must not disable the engine entirely because that strands open exposure.
        self.assertIn("data/PVE_PAUSE", wd,
                      "BUG-B fix: watchdog must check PVE_PAUSE file to disable PVE")
        self.assertNotIn("TE_PVE_ENABLED=0", wd,
                         "PVE pause must preserve close-only position management")
        # Pair config is delegated to .env: no ACTIVE (uncommented) export in the
        # watchdog. A commented rollback line (`# export TE_PVE_PAIRS=`) is allowed.
        self.assertNotRegex(wd, r"(?m)^\s*export TE_PVE_PAIRS=")
