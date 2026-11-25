import json
import tempfile
import time
from decimal import Decimal
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


class SodexLiveShortAcceleratorTests(TestCase):
    def _report(self, *, halt_active: bool = False) -> dict:
        return {
            "halt_status": {"active": halt_active, "kind": "SAFETY_HALT"} if halt_active else {"active": False},
            "official_dashboard": {"quality": "STALE_OR_EMPTY", "canonical": False, "volume": {"total_usd": 0.0}},
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
        }

    def test_build_plan_ready_when_policy_e2dir_and_ratio_gate_pass(self):
        from scripts import sodex_live_short_accelerator as accel

        candidates = [{
            "symbol": "XPL-USD",
            "side": "sell",
            "score": 18.5,
            "expected_edge_bps": 12.2,
            "change_pct": -12.0,
            "funding_rate": 0.0000125,
            "spread_pct": 0.001,
            "quote_volume": 138000,
            "mid": 0.091,
        }]
        with tempfile.TemporaryDirectory() as td:
            intel = Path(td) / "intel_20260709.jsonl"
            intel.write_text(json.dumps({
                "ts": time.time(),
                "composite_score": 50.0,
                "fc_BTC_dir_enc": 0,
                "fc_BTC_conf": 0.0,
                "fc_BTC_agreement": 0.0,
                "event_risk_level": "RED",
                "event_risk_score": 82.0,
            }) + "\n")
            with patch("scripts.sodex_target_policy.DEFAULT_INTEL_DIR", Path(td)), \
                 patch("scripts.sodex_micro_pilot.micro_daily_loss_used_usd", return_value=Decimal("0")), \
                 patch("scripts.sodex_micro_pilot.micro_daily_volume_usd", return_value=Decimal("0")), \
                 patch("scripts.sodex_micro_pilot.ta_probability_gate", return_value={"passes": True, "probability": 0.88}):
                plan = accel.build_plan(
                    self._report(),
                    candidates,
                    microstructure_rows=[{
                        "symbol": "XPL-USD",
                        "scalp_lane": "MAKER_ONLY_CANDIDATE",
                        "taker_ratio_pass": False,
                        "maker_gross_edge_bps": 8.5,
                    }],
                    requested_notional=Decimal("10"),
                )

        self.assertEqual(plan["status"], "READY_FOR_EXPLICIT_OPERATOR_LIVE_MAKER_SHORT")
        self.assertEqual(plan["best_candidate"]["symbol"], "XPL-USD")
        self.assertIn("--operator-override-safety-halt", plan["live_command"])
        self.assertIn("--entry-mode maker", plan["live_command"])
        self.assertIn("--exit-mode maker", plan["live_command"])
        self.assertIn("--cycles 12", plan["live_command"])
        expected_ratio = 7000.0  # post-emergency base ratio
        self.assertAlmostEqual(plan["probe"]["max_loss_for_min_ratio_usd"], 20 / expected_ratio)
        self.assertGreater(plan["probe"]["lane_target_daily_volume_usd"], 90000)
        self.assertEqual(plan["probe"]["suggested_burst_cycles"], 12)
        self.assertEqual(plan["probe"]["suggested_cycle_interval_seconds"], 300)
        self.assertTrue(plan["probe"]["ratio_recovery_mode"])
        self.assertTrue(plan["probe"]["ratio_recovery_requires_zero_incremental_loss"])

    def test_build_plan_blocks_when_farming_ratio_budget_used(self):
        from scripts import sodex_live_short_accelerator as accel

        candidates = [{
            "symbol": "XPL-USD",
            "side": "sell",
            "score": 18.5,
            "expected_edge_bps": 12.2,
            "change_pct": -12.0,
            "funding_rate": 0.0000125,
            "spread_pct": 0.001,
            "quote_volume": 138000,
            "mid": 0.091,
        }]
        with tempfile.TemporaryDirectory() as td:
            intel = Path(td) / "intel_20260709.jsonl"
            intel.write_text(json.dumps({
                "ts": time.time(),
                "composite_score": 50.0,
                "event_risk_level": "RED",
                "event_risk_score": 82.0,
            }) + "\n")
            with patch("scripts.sodex_target_policy.DEFAULT_INTEL_DIR", Path(td)), \
                 patch("scripts.sodex_micro_pilot.micro_daily_loss_used_usd", return_value=Decimal("0.005")), \
                 patch("scripts.sodex_micro_pilot.micro_daily_volume_usd", return_value=Decimal("0")), \
                 patch("scripts.sodex_micro_pilot.ta_probability_gate", return_value={"passes": True, "probability": 0.88}):
                plan = accel.build_plan(
                    self._report(),
                    candidates,
                    microstructure_rows=[{
                        "symbol": "XPL-USD",
                        "scalp_lane": "REJECT_NEGATIVE_AFTER_MAKER_FEES",
                        "taker_ratio_pass": False,
                    }],
                    requested_notional=Decimal("10"),
                )

        self.assertEqual(plan["status"], "BLOCKED")
        self.assertIn("farming_ratio_loss_budget_reached", plan["blockers"])
        self.assertIsNone(plan["live_command"])

    def test_build_plan_allows_maker_recovery_when_ratio_budget_is_used(self):
        from scripts import sodex_live_short_accelerator as accel

        candidates = [{
            "symbol": "XPL-USD",
            "side": "sell",
            "score": 18.5,
            "expected_edge_bps": 12.2,
            "change_pct": -12.0,
            "funding_rate": 0.0000125,
            "spread_pct": 0.001,
            "quote_volume": 138000,
            "mid": 0.091,
        }]
        with tempfile.TemporaryDirectory() as td:
            intel = Path(td) / "intel_20260709.jsonl"
            intel.write_text(json.dumps({
                "ts": time.time(),
                "composite_score": 50.0,
                "event_risk_level": "RED",
                "event_risk_score": 82.0,
            }) + "\n")
            with patch("scripts.sodex_target_policy.DEFAULT_INTEL_DIR", Path(td)), \
                 patch("scripts.sodex_micro_pilot.micro_daily_loss_used_usd", return_value=Decimal("0.005")), \
                 patch("scripts.sodex_micro_pilot.micro_daily_volume_usd", return_value=Decimal("0")), \
                 patch("scripts.sodex_micro_pilot.ta_probability_gate", return_value={"passes": True, "probability": 0.88}):
                plan = accel.build_plan(
                    self._report(),
                    candidates,
                    microstructure_rows=[{
                        "symbol": "XPL-USD",
                        "scalp_lane": "MAKER_ONLY_CANDIDATE",
                        "taker_ratio_pass": False,
                    }],
                    requested_notional=Decimal("10"),
                )

        self.assertEqual(plan["status"], "READY_FOR_EXPLICIT_OPERATOR_LIVE_MAKER_SHORT")
        self.assertTrue(plan["probe"]["ratio_recovery_mode"])
        self.assertTrue(plan["probe"]["ratio_recovery_requires_zero_incremental_loss"])
        self.assertNotIn("farming_ratio_loss_budget_reached", plan["blockers"])

    def test_build_plan_blocks_when_microstructure_is_not_maker_candidate(self):
        from scripts import sodex_live_short_accelerator as accel

        candidates = [{
            "symbol": "XPL-USD",
            "side": "sell",
            "score": 18.5,
            "expected_edge_bps": 12.2,
            "change_pct": -12.0,
            "funding_rate": 0.0000125,
            "spread_pct": 0.001,
            "quote_volume": 138000,
            "mid": 0.091,
        }]
        with tempfile.TemporaryDirectory() as td:
            intel = Path(td) / "intel_20260709.jsonl"
            intel.write_text(json.dumps({
                "ts": time.time(),
                "composite_score": 50.0,
                "event_risk_level": "RED",
                "event_risk_score": 82.0,
            }) + "\n")
            with patch("scripts.sodex_target_policy.DEFAULT_INTEL_DIR", Path(td)), \
                 patch("scripts.sodex_micro_pilot.micro_daily_loss_used_usd", return_value=Decimal("0")), \
                 patch("scripts.sodex_micro_pilot.micro_daily_volume_usd", return_value=Decimal("0")), \
                 patch("scripts.sodex_micro_pilot.ta_probability_gate", return_value={"passes": True, "probability": 0.88}):
                plan = accel.build_plan(
                    self._report(),
                    candidates,
                    microstructure_rows=[{
                        "symbol": "XPL-USD",
                        "scalp_lane": "REJECT_NEGATIVE_AFTER_MAKER_FEES",
                        "taker_ratio_pass": False,
                    }],
                    requested_notional=Decimal("10"),
                )

        self.assertEqual(plan["status"], "BLOCKED")
        self.assertIn("microstructure_not_maker_candidate:REJECT_NEGATIVE_AFTER_MAKER_FEES", plan["blockers"])
        self.assertIsNone(plan["live_command"])

    def test_ratio_recovery_falls_back_to_best_maker_microstructure_candidate(self):
        from scripts import sodex_live_short_accelerator as accel

        candidates = [{
            "symbol": "SOL-USD",
            "side": "sell",
            "score": 18.5,
            "expected_edge_bps": -4.2,
            "change_pct": -1.6,
            "funding_rate": -0.000005,
            "spread_pct": 0.00013,
            "quote_volume": 7_000_000,
            "mid": 76.0,
        }]
        with tempfile.TemporaryDirectory() as td:
            intel = Path(td) / "intel_20260709.jsonl"
            intel.write_text(json.dumps({
                "ts": time.time(),
                "composite_score": 50.0,
                "event_risk_level": "RED",
                "event_risk_score": 82.0,
            }) + "\n")
            with patch("scripts.sodex_target_policy.DEFAULT_INTEL_DIR", Path(td)), \
                 patch("scripts.sodex_micro_pilot.micro_daily_loss_used_usd", return_value=Decimal("0")), \
                 patch("scripts.sodex_micro_pilot.micro_daily_volume_usd", return_value=Decimal("0")), \
                 patch("scripts.sodex_micro_pilot.ta_probability_gate", return_value={"passes": True, "probability": 0.88}):
                plan = accel.build_plan(
                    self._report(),
                    candidates,
                    microstructure_rows=[
                        {
                            "symbol": "SOL-USD",
                            "scalp_lane": "REJECT_NEGATIVE_AFTER_MAKER_FEES",
                            "taker_ratio_pass": False,
                            "mid": 76.0,
                        },
                        {
                            "symbol": "MRVL-USD",
                            "scalp_lane": "MAKER_ONLY_CANDIDATE",
                            "taker_ratio_pass": False,
                            "maker_gross_edge_bps": 25.0,
                            "spread_bps": 27.0,
                            "quote_volume_usd": 164000.0,
                            "mid": 197.0,
                            "change_pct": -11.0,
                            "funding_bps": 0.06,
                        },
                        {
                            "symbol": "NVDA-USD",
                            "scalp_lane": "MAKER_ONLY_CANDIDATE",
                            "taker_ratio_pass": False,
                            "maker_gross_edge_bps": 5.0,
                            "spread_bps": 7.0,
                            "quote_volume_usd": 184000.0,
                            "mid": 209.0,
                            "change_pct": -1.0,
                            "funding_bps": 0.06,
                        },
                    ],
                    requested_notional=Decimal("10"),
                )

        self.assertEqual(plan["status"], "READY_FOR_EXPLICIT_OPERATOR_LIVE_MAKER_SHORT")
        self.assertEqual(plan["best_candidate"]["symbol"], "NVDA-USD")
        self.assertIn("--symbol NVDA-USD", plan["live_command"])

    def test_build_plan_blocks_when_ta_probability_gate_fails(self):
        from scripts import sodex_live_short_accelerator as accel

        candidates = [{
            "symbol": "XPL-USD",
            "side": "sell",
            "score": 18.5,
            "expected_edge_bps": 12.2,
            "change_pct": -12.0,
            "funding_rate": 0.0000125,
            "spread_pct": 0.001,
            "quote_volume": 138000,
            "mid": 0.091,
        }]
        with tempfile.TemporaryDirectory() as td:
            intel = Path(td) / "intel_20260709.jsonl"
            intel.write_text(json.dumps({
                "ts": time.time(),
                "composite_score": 50.0,
                "event_risk_level": "RED",
                "event_risk_score": 82.0,
            }) + "\n")
            with patch("scripts.sodex_target_policy.DEFAULT_INTEL_DIR", Path(td)), \
                 patch("scripts.sodex_micro_pilot.micro_daily_loss_used_usd", return_value=Decimal("0")), \
                 patch("scripts.sodex_micro_pilot.micro_daily_volume_usd", return_value=Decimal("0")), \
                 patch("scripts.sodex_micro_pilot.ta_probability_gate", return_value={
                     "passes": False,
                     "probability": 0.44,
                     "reasons": ["ta_probability_below_minimum"],
                 }):
                plan = accel.build_plan(
                    self._report(),
                    candidates,
                    microstructure_rows=[{
                        "symbol": "XPL-USD",
                        "scalp_lane": "MAKER_ONLY_CANDIDATE",
                        "taker_ratio_pass": False,
                        "maker_gross_edge_bps": 8.5,
                    }],
                    requested_notional=Decimal("10"),
                )

        self.assertEqual(plan["status"], "BLOCKED")
        self.assertIn("ta_probability_gate_failed", plan["blockers"])
        self.assertIsNone(plan["live_command"])
