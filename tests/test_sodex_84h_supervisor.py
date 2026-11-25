from datetime import datetime, timezone
from unittest import TestCase


class Sodex84hSupervisorTests(TestCase):
    def test_supervisor_blocks_live_when_official_dashboard_is_stale(self):
        from scripts import sodex_84h_supervisor as supervisor

        report = {
            "official_dashboard": {
                "quality": "STALE_OR_EMPTY",
                "canonical": False,
                "volume": {"spot_usd": 132_732.25, "perps_usd": 15_520.46, "total_usd": 148_252.71},
            },
            "ledger": {
                "volume": {"spot_usd": 447.14, "perps_usd": 0.0, "raw_total_usd": 447.14, "weighted_total_usd": 894.28},
                "costs": {"fees_usd": 0.0},
                "pnl": {"realized_net_usd": 0.235017},
                "rts": {"win_rate": 0.50},
            },
            "account": {"account_value": {"total_equity_usd": 322.05}, "assets": {"perps_positions": [{}, {}, {}]}},
            "window": {"weekly_label": "weekly 27"},
            "verdict": {"warnings": ["official_dashboard_window_mismatch"]},
        }

        result = supervisor.evaluate_mission(report, now=datetime(2026, 6, 20, 0, 10, tzinfo=timezone.utc))

        self.assertEqual(result["mode"], "READ_ONLY_AUTONOMOUS_SUPERVISION")
        self.assertEqual(result["mission_state"], "RECON_FIRST")
        self.assertFalse(result["live_trade_allowed"])
        self.assertIn("refresh_official_dashboard_weekly_27", result["next_actions"])
        self.assertIn("do_not_scale_e2", result["constraints"])
        self.assertEqual(result["radical_experiments"][0]["id"], "official_credit_reconciliation")

    def test_supervisor_treats_clean_gate_as_approval_required_not_auto_live(self):
        from scripts import sodex_84h_supervisor as supervisor

        report = {
            "official_dashboard": {
                "quality": "OK",
                "canonical": True,
                "volume": {"spot_usd": 700_000.0, "perps_usd": 650_000.0, "total_usd": 1_350_000.0},
            },
            "ledger": {
                "volume": {
                    "spot_usd": 700_000.0,
                    "perps_usd": 650_000.0,
                    "raw_total_usd": 1_350_000.0,
                    "weighted_total_usd": 2_050_000.0,
                },
                "costs": {"fees_usd": 150.0},
                "pnl": {"realized_net_usd": 160.0},
                "rts": {"win_rate": 0.75},
            },
            "account": {"account_value": {"total_equity_usd": 650.0}, "assets": {"perps_positions": []}},
            "verdict": {"warnings": []},
        }

        result = supervisor.evaluate_mission(report, now=datetime(2026, 6, 20, 0, 10, tzinfo=timezone.utc))

        self.assertEqual(result["mission_state"], "FULL_REAL_CANDIDATE_AWAITING_APPROVAL")
        self.assertFalse(result["live_trade_allowed"])
        self.assertIn("await_explicit_user_live_approval", result["next_actions"])
        self.assertEqual(result["execution_authority"], "NO_ORDER_NO_TRANSFER_NO_LEVERAGE_CHANGE")
        self.assertEqual(result["radical_experiments"][0]["id"], "approval_locked_full_real_candidate")

    def test_supervisor_identifies_e1_first_when_ratio_is_short_but_dashboard_is_canonical(self):
        from scripts import sodex_84h_supervisor as supervisor

        report = {
            "official_dashboard": {
                "quality": "OK",
                "canonical": True,
                "volume": {"spot_usd": 132_732.25, "perps_usd": 15_520.46, "total_usd": 148_252.71},
            },
            "ledger": {
                "volume": {
                    "spot_usd": 132_732.25,
                    "perps_usd": 15_520.46,
                    "raw_total_usd": 148_252.71,
                    "weighted_total_usd": 280_984.96,
                },
                "costs": {"fees_usd": 110.375532},
                "pnl": {"realized_net_usd": 27.731779},
                "rts": {"win_rate": 0.89},
            },
            "account": {"account_value": {"total_equity_usd": 382.54}, "assets": {"perps_positions": []}},
            "verdict": {"warnings": []},
        }

        result = supervisor.evaluate_mission(report, now=datetime(2026, 6, 20, 0, 10, tzinfo=timezone.utc))

        self.assertEqual(result["mission_state"], "E1_PROFIT_FIRST")
        self.assertFalse(result["live_trade_allowed"])
        self.assertIn("increase_e1_profit_subsidy", result["next_actions"])
        self.assertGreater(result["e1"]["extra_profit_needed_no_loss"], 80.0)
        self.assertEqual(result["radical_experiments"][0]["id"], "e1_no_loss_subsidy")

    def test_supervisor_promotes_open_position_loss_to_containment_state(self):
        from scripts import sodex_84h_supervisor as supervisor

        report = {
            "official_dashboard": {
                "quality": "STALE_OR_EMPTY",
                "canonical": False,
                "volume": {"spot_usd": 0.0, "perps_usd": 0.0, "total_usd": 0.0},
            },
            "ledger": {
                "volume": {"spot_usd": 1_575.70, "perps_usd": 0.0, "raw_total_usd": 1_575.70},
                "costs": {"fees_usd": 0.0},
                "pnl": {"realized_net_usd": 0.118123},
                "rts": {"win_rate": 0.50},
            },
            "account": {
                "account_value": {
                    "total_equity_usd": 313.986885,
                    "perps_unrealized_pnl_calc_usd": -12.75167,
                },
                "assets": {
                    "perps_positions": [
                        {
                            "symbol": "SAMSUNG-USD",
                            "side": "SHORT",
                            "unrealized_pnl_calc_usd": -12.3407,
                            "initial_margin_usd": 70.397553,
                            "leverage": 10,
                        },
                        {
                            "symbol": "MSTR-USD",
                            "side": "SHORT",
                            "unrealized_pnl_calc_usd": -0.39912,
                            "initial_margin_usd": 4.283715,
                            "leverage": 10,
                        },
                    ]
                },
            },
            "verdict": {"warnings": ["official_dashboard_window_mismatch"]},
        }

        result = supervisor.evaluate_mission(report, now=datetime(2026, 6, 20, 0, 40, tzinfo=timezone.utc))

        self.assertEqual(result["mission_state"], "PERP_LOSS_CONTAINMENT")
        self.assertFalse(result["live_trade_allowed"])
        self.assertIn("perp_unrealized_loss_alert", result["risk_alerts"])
        self.assertEqual(result["perps_risk"]["largest_loss_symbol"], "SAMSUNG-USD")
        self.assertLess(result["perps_risk"]["unrealized_pnl_usd"], -12.0)
        self.assertEqual(result["radical_experiments"][0]["id"], "perp_loss_containment_audit")

    def test_supervisor_flags_open_spot_orders_as_inventory_risk(self):
        from scripts import sodex_84h_supervisor as supervisor

        report = {
            "official_dashboard": {"quality": "STALE_OR_EMPTY", "canonical": False, "volume": {}},
            "ledger": {
                "volume": {"raw_total_usd": 1_857.06},
                "costs": {"fees_usd": 0.0},
                "pnl": {"realized_net_usd": -0.079066},
                "rts": {"win_rate": 0.4605},
            },
            "account": {
                "account_value": {"total_equity_usd": 323.01},
                "assets": {"perps_positions": []},
            },
            "verdict": {"warnings": ["official_dashboard_window_mismatch"]},
        }
        open_orders = {
            "spot": [
                {"symbol": "vSHIB_vUSDC", "side": "BUY", "marginFrozen": "10.38", "status": "NEW"},
                {"symbol": "vPEPE_vUSDC", "side": "BUY", "marginFrozen": "15.48", "status": "NEW"},
            ],
            "perps": [],
        }

        result = supervisor.evaluate_mission(
            report,
            now=datetime(2026, 6, 20, 0, 44, tzinfo=timezone.utc),
            open_orders=open_orders,
        )

        self.assertIn("open_spot_orders_present", result["risk_alerts"])
        self.assertEqual(result["open_orders_risk"]["spot_count"], 2)
        self.assertGreater(result["open_orders_risk"]["spot_buy_frozen_usd"], 25.0)
        self.assertIn("inspect_open_orders_read_only", result["next_actions"])
