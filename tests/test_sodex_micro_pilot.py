from decimal import Decimal
import json
import tempfile
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


class SodexMicroPilotTests(TestCase):
    def test_score_candidate_prefers_liquid_negative_tight_spread(self):
        from scripts import sodex_micro_pilot as pilot

        candidate = pilot.score_candidate(
            {
                "symbol": "VIRTUAL-USD",
                "changePct": "-3.4",
                "quoteVolume": "188000",
                "fundingRate": "-0.0001",
            },
            {"bids": [{"price": "1.0000"}], "asks": [{"price": "1.0008"}]},
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.symbol, "VIRTUAL-USD")
        self.assertGreater(candidate.score, Decimal("3.4"))

    def test_short_score_prefers_positive_funding_over_negative_funding(self):
        from scripts import sodex_micro_pilot as pilot

        book = {"bids": [{"price": "1.0000"}], "asks": [{"price": "1.0008"}]}
        positive = pilot.score_candidate(
            {"symbol": "POS-USD", "changePct": "-3.0", "quoteVolume": "200000", "fundingRate": "0.0002"},
            book,
        )
        negative = pilot.score_candidate(
            {"symbol": "NEG-USD", "changePct": "-3.0", "quoteVolume": "200000", "fundingRate": "-0.0002"},
            book,
        )

        assert positive is not None and negative is not None
        self.assertGreater(positive.score, negative.score)

    def test_short_continuation_rejects_rebound_before_entry(self):
        from scripts import sodex_micro_pilot as pilot

        self.assertTrue(pilot.short_continuation_ok(Decimal("1.0000"), Decimal("0.9995")))
        self.assertFalse(pilot.short_continuation_ok(Decimal("1.0000"), Decimal("1.0010")))

    def test_score_candidate_rejects_positive_or_wide_spread(self):
        from scripts import sodex_micro_pilot as pilot

        self.assertIsNone(pilot.score_candidate(
            {"symbol": "BTC-USD", "changePct": "2.0", "quoteVolume": "1000000"},
            {"bids": [{"price": "65000"}], "asks": [{"price": "65001"}]},
        ))
        self.assertIsNone(pilot.score_candidate(
            {"symbol": "BAD-USD", "changePct": "-5.0", "quoteVolume": "1000000"},
            {"bids": [{"price": "1"}], "asks": [{"price": "1.02"}]},
        ))

    def test_ratio_recovery_score_allows_liquid_positive_tight_spread(self):
        from scripts import sodex_micro_pilot as pilot

        candidate = pilot.score_candidate(
            {"symbol": "BTC-USD", "changePct": "0.4", "quoteVolume": "2000000", "fundingRate": "0.0001"},
            {"bids": [{"price": "65000"}], "asks": [{"price": "65020"}]},
            ratio_recovery=True,
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.symbol, "BTC-USD")

    def test_policy_allows_only_micro_lane_no_open_positions(self):
        from scripts import sodex_micro_pilot as pilot

        policy = {
            "signal": {"fresh": True},
            "opportunity_lanes": [{"lane": "MICRO_PRE_LOSER_SHORT_ONLY", "max_notional_usd": 25.0}],
        }
        report = {"account": {"assets": {"perps_positions": []}}}

        ok, reason, _ = pilot.policy_allows_micro(policy, report, Decimal("12"))
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

        blocked_report = {"account": {"assets": {"perps_positions": [{"symbol": "BTC-USD"}]}}}
        ok, reason, _ = pilot.policy_allows_micro(policy, blocked_report, Decimal("12"))
        self.assertFalse(ok)
        self.assertEqual(reason, "open_perps_present")

    def test_policy_accepts_ratio_recovery_maker_lane(self):
        from scripts import sodex_micro_pilot as pilot

        policy = {
            "signal": {"fresh": True},
            "opportunity_lanes": [{
                "lane": "RATIO_RECOVERY_MAKER_ONLY",
                "max_notional_usd": 10.0,
                "max_loss_for_min_ratio_usd": 20 / 5100,
            }],
        }
        report = {"account": {"assets": {"perps_positions": []}}}

        ok, reason, lane = pilot.policy_allows_micro(policy, report, Decimal("10"))

        self.assertTrue(ok)
        self.assertEqual(reason, "ok")
        self.assertEqual(lane["lane"], "RATIO_RECOVERY_MAKER_ONLY")
        self.assertTrue(pilot.is_ratio_recovery_lane(lane))
        self.assertFalse(pilot.is_ratio_recovery_lane({"lane": "MICRO_PRE_LOSER_SHORT_ONLY"}))

    def test_policy_accepts_safety_halt_short_pilot_lane_for_dry_run_override(self):
        from scripts import sodex_micro_pilot as pilot

        policy = {
            "signal": {"fresh": True},
            "opportunity_lanes": [{
                "lane": "SAFETY_HALT_SHORT_PILOT",
                "max_notional_usd": 10.8,
                "max_loss_for_min_ratio_usd": 20 / 5100,
            }],
        }
        report = {"account": {"assets": {"perps_positions": []}}}

        ok, reason, lane = pilot.policy_allows_micro(
            policy,
            report,
            Decimal("10"),
            halt_exists=True,
            override_halt=True,
        )

        self.assertTrue(ok)
        self.assertEqual(reason, "ok")
        self.assertEqual(lane["lane"], "SAFETY_HALT_SHORT_PILOT")

    def test_farming_ratio_budget_scales_from_roundtrip_volume(self):
        from scripts import sodex_micro_pilot as pilot

        self.assertEqual(pilot.projected_roundtrip_volume_usd(Decimal("10")), Decimal("20"))
        expected_ratio = 7000.0  # post-emergency base ratio (emergency expired 2026-07-18)
        self.assertAlmostEqual(float(pilot.max_loss_for_ratio(Decimal("10"))), 20 / expected_ratio)

    def test_policy_blocks_when_farming_ratio_loss_budget_reached(self):
        from scripts import sodex_micro_pilot as pilot

        policy = {
            "signal": {"fresh": True},
            "opportunity_lanes": [{
                "lane": "SAFETY_HALT_SHORT_PILOT",
                "max_notional_usd": 10.8,
                "max_loss_for_min_ratio_usd": 20 / 5100,
            }],
        }
        report = {"account": {"assets": {"perps_positions": []}}}

        ok, reason, _ = pilot.policy_allows_micro(
            policy,
            report,
            Decimal("10"),
            halt_exists=True,
            override_halt=True,
            daily_loss_used_usd=Decimal("0.004"),
        )

        self.assertFalse(ok)
        self.assertEqual(reason, "farming_ratio_loss_budget_reached")

    def test_policy_allows_maker_ratio_recovery_even_when_single_trade_budget_used(self):
        from scripts import sodex_micro_pilot as pilot

        policy = {
            "signal": {"fresh": True},
            "opportunity_lanes": [{
                "lane": "SAFETY_HALT_SHORT_PILOT",
                "max_notional_usd": 10.8,
                "max_loss_for_min_ratio_usd": 20 / 5100,
            }],
        }
        report = {"account": {"assets": {"perps_positions": []}}}

        ok, reason, _ = pilot.policy_allows_micro(
            policy,
            report,
            Decimal("10"),
            halt_exists=True,
            override_halt=True,
            daily_loss_used_usd=Decimal("0.01"),
            daily_volume_usd=Decimal("20"),
            allow_ratio_recovery=True,
        )

        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_micro_daily_volume_counts_only_live_filled_records(self):
        from scripts import sodex_micro_pilot as pilot

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "micro.jsonl"
            ts = datetime(2026, 7, 8, 21, tzinfo=timezone.utc).isoformat()
            path.write_text("\n".join([
                json.dumps({
                    "mode": "live",
                    "closed": True,
                    "ts_utc": ts,
                    "projected_roundtrip_volume_usd": 21.4,
                }),
                json.dumps({
                    "mode": "live",
                    "closed": False,
                    "opened_size": 0,
                    "ts_utc": ts,
                    "projected_roundtrip_volume_usd": 99,
                }),
                json.dumps({
                    "mode": "dry_run",
                    "closed": True,
                    "ts_utc": ts,
                    "projected_roundtrip_volume_usd": 99,
                }),
            ]))

            volume = pilot.micro_daily_volume_usd(
                datetime(2026, 7, 8, 22, tzinfo=timezone.utc),
                path,
            )

        self.assertEqual(volume, Decimal("21.4"))

    def test_policy_requires_explicit_halt_override(self):
        from scripts import sodex_micro_pilot as pilot

        policy = {
            "signal": {"fresh": True},
            "opportunity_lanes": [{"lane": "MICRO_PRE_LOSER_SHORT_ONLY", "max_notional_usd": 25.0}],
        }
        report = {"account": {"assets": {"perps_positions": []}}}

        ok, reason, _ = pilot.policy_allows_micro(policy, report, Decimal("12"), halt_exists=True)
        self.assertFalse(ok)
        self.assertEqual(reason, "safety_halt_active")

        ok, reason, _ = pilot.policy_allows_micro(
            policy,
            report,
            Decimal("12"),
            halt_exists=True,
            override_halt=True,
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_place_order_requires_explicit_halt_entry_override(self):
        from scripts import sodex_micro_pilot as pilot

        with tempfile.TemporaryDirectory() as td:
            halt = Path(td) / "SAFETY_HALT"
            halt.write_text("halt")
            with patch.object(pilot, "SAFETY_HALT", halt), \
                 patch.object(pilot, "PNL_HALT", Path(td) / "PNL_HALT"), \
                 patch.object(pilot, "venue_state_readable", return_value=True), \
                 patch.object(pilot, "run_json", return_value={"ok": True}) as run_json:
                with self.assertRaises(RuntimeError):
                    pilot.place_order("XPL-USD", "sell", "109")

                result = pilot.place_order(
                    "XPL-USD",
                    "sell",
                    "109",
                    allow_safety_halt_entry=True,
                )

        self.assertEqual(result, {"ok": True})
        self.assertTrue(run_json.called)

    def test_place_order_supports_post_only_limit_entry(self):
        from scripts import sodex_micro_pilot as pilot

        with patch.object(pilot, "halt_active", return_value=False), \
             patch.object(pilot, "venue_state_readable", return_value=True), \
             patch.object(pilot, "run_json", return_value={"ok": True}) as run_json:
            result = pilot.place_order(
                "XPL-USD",
                "sell",
                "117",
                order_type="limit",
                tif="gtx",
                price=Decimal("0.0911"),
            )

        self.assertEqual(result, {"ok": True})
        cmd = run_json.call_args.args[0]
        self.assertIn("--type", cmd)
        self.assertIn("limit", cmd)
        self.assertIn("--tif", cmd)
        self.assertIn("gtx", cmd)
        self.assertIn("--price", cmd)
        self.assertIn("0.0911", cmd)

    def test_place_order_refuses_open_when_venue_unreadable(self):
        """Guard fail-closed: venue tak terbaca → TOLAK menambah risiko.

        Kalau "venue tak terbaca" dianggap "venue kosong", order baru bisa ditumpuk
        di atas posisi yang sebenarnya ada (kelas cacat maker-ladder 3,39x → UNI -$19,06).
        """
        from scripts import sodex_micro_pilot as pilot

        with patch.object(pilot, "halt_active", return_value=False), \
             patch.object(pilot, "venue_state_readable", return_value=False), \
             patch.object(pilot, "run_json", return_value={"ok": True}) as run_json:
            with self.assertRaises(RuntimeError) as ctx:
                pilot.place_order("XPL-USD", "sell", "109")
        self.assertIn("venue_state_unreadable_refuse_open", str(ctx.exception))
        self.assertFalse(run_json.called, "order tak boleh dikirim saat venue tak terbaca")

    def test_place_order_selalu_izinkan_menutup_saat_venue_unreadable(self):
        """Menutup/mengurangi posisi TIDAK boleh diblokir guard venue.

        Guard yang memblokir exit saat API hiccup menjadi sumber kerugian baru.
        """
        from scripts import sodex_micro_pilot as pilot

        with patch.object(pilot, "halt_active", return_value=False), \
             patch.object(pilot, "venue_state_readable", return_value=False), \
             patch.object(pilot, "run_json", return_value={"ok": True}) as run_json:
            result = pilot.place_order("XPL-USD", "buy", "109", reduce_only=True)
        self.assertEqual(result, {"ok": True})
        self.assertTrue(run_json.called)

    def test_override_halt_tidak_membatalkan_guard_venue(self):
        """allow_safety_halt_entry hanya membuka halt; guard venue tetap berlaku."""
        from scripts import sodex_micro_pilot as pilot

        with patch.object(pilot, "halt_active", return_value=True), \
             patch.object(pilot, "venue_state_readable", return_value=False), \
             patch.object(pilot, "run_json", return_value={"ok": True}) as run_json:
            with self.assertRaises(RuntimeError) as ctx:
                pilot.place_order("XPL-USD", "sell", "109", allow_safety_halt_entry=True)
        self.assertIn("venue_state_unreadable_refuse_open", str(ctx.exception))
        self.assertFalse(run_json.called)

    def test_cancel_order_uses_symbol_id_and_client_id_fallback(self):
        from scripts import sodex_micro_pilot as pilot

        with patch.object(pilot, "markets", return_value=[{"id": 21, "name": "XPL-USD"}]), \
             patch.object(pilot, "run_json", return_value={"cancelled": True}) as run_json:
            result = pilot.cancel_order("XPL-USD", [{"orderID": 0, "clOrdID": "abc"}])

        self.assertEqual(result, {"cancelled": True})
        cmd = run_json.call_args.args[0]
        self.assertIn("--symbol-id", cmd)
        self.assertIn("21", cmd)
        self.assertIn("--cl-ord-id", cmd)
        self.assertIn("abc", cmd)

    def test_maker_entry_and_exit_prices_improve_inside_spread_when_possible(self):
        from argparse import Namespace
        from scripts import sodex_micro_pilot as pilot

        candidate = pilot.Candidate(
            symbol="XPL-USD",
            bid=Decimal("0.0910"),
            ask=Decimal("0.0913"),
            mid=Decimal("0.09115"),
            spread_pct=Decimal("0.001"),
            change_pct=Decimal("-12"),
            quote_volume=Decimal("100000"),
            funding_rate=Decimal("0.0001"),
            score=Decimal("14"),
        )

        entry = pilot.entry_order_args(Namespace(entry_mode="maker"), candidate)
        self.assertEqual(entry, ("limit", "gtx", Decimal("0.0912")))

        with patch.object(pilot, "orderbook", return_value={
            "bids": [{"price": "0.0910"}],
            "asks": [{"price": "0.0913"}],
        }):
            exit_args = pilot.reduce_exit_order_args(Namespace(exit_mode="maker"), "XPL-USD")

        self.assertEqual(exit_args, ("limit", "gtx", Decimal("0.0911")))

    def test_maker_prices_do_not_cross_when_spread_is_one_tick(self):
        from scripts import sodex_micro_pilot as pilot

        self.assertEqual(pilot.maker_sell_price(Decimal("1.00"), Decimal("1.01")), Decimal("1.01"))
        self.assertEqual(pilot.maker_buy_price(Decimal("1.00"), Decimal("1.01")), Decimal("1.00"))

    def test_policy_blocks_when_micro_daily_loss_cap_is_reached(self):
        from scripts import sodex_micro_pilot as pilot

        policy = {
            "signal": {"fresh": True},
            "opportunity_lanes": [{
                "lane": "MICRO_PRE_LOSER_SHORT_ONLY",
                "max_notional_usd": 25.0,
                "max_daily_loss_usd": 1.0,
            }],
        }
        report = {"account": {"assets": {"perps_positions": []}}}

        ok, reason, _ = pilot.policy_allows_micro(
            policy,
            report,
            Decimal("12"),
            daily_loss_used_usd=Decimal("1.0"),
        )

        self.assertFalse(ok)
        self.assertEqual(reason, "micro_daily_loss_cap_reached")

    def test_policy_allows_maker_ratio_recovery_when_daily_loss_cap_is_reached(self):
        from scripts import sodex_micro_pilot as pilot

        policy = {
            "signal": {"fresh": True},
            "opportunity_lanes": [{
                "lane": "SAFETY_HALT_SHORT_PILOT",
                "max_notional_usd": 10.8,
                "max_daily_loss_usd": 0.003,
                "max_loss_for_min_ratio_usd": 20 / 5100,
            }],
        }
        report = {"account": {"assets": {"perps_positions": []}}}

        ok, reason, _ = pilot.policy_allows_micro(
            policy,
            report,
            Decimal("10"),
            daily_loss_used_usd=Decimal("0.019"),
            allow_ratio_recovery=True,
            halt_exists=True,
            override_halt=True,
        )

        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_barbell_cooldown_blocks_live_micro_without_explicit_override(self):
        from scripts import sodex_micro_pilot as pilot

        self.assertFalse(pilot.barbell_allows_micro_live(
            {"phase": "MICRO_EDGE_NEGATIVE_COOLDOWN"},
            override=False,
        ))
        self.assertFalse(pilot.barbell_allows_micro_live(
            {"phase": "STOP_LIVE_RESEARCH_ONLY"},
            override=False,
        ))
        self.assertTrue(pilot.barbell_allows_micro_live(
            {"phase": "MICRO_EDGE_NEGATIVE_COOLDOWN"},
            override=True,
        ))

    def test_micro_daily_loss_uses_today_live_ok_account_delta(self):
        from scripts import sodex_micro_pilot as pilot

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "micro.jsonl"
            path.write_text("\n".join([
                json.dumps({
                    "mode": "live",
                    "reason": "ok",
                    "ts_utc": datetime(2026, 6, 25, 10, tzinfo=timezone.utc).isoformat(),
                    "account_delta_usd": -0.25,
                }),
                json.dumps({
                    "mode": "live",
                    "reason": "ok",
                    "ts_utc": datetime(2026, 6, 25, 11, tzinfo=timezone.utc).isoformat(),
                    "account_delta_usd": 0.10,
                }),
            ]))

            loss = pilot.micro_daily_loss_used_usd(
                datetime(2026, 6, 25, 12, tzinfo=timezone.utc),
                path,
            )

        self.assertEqual(loss, Decimal("0.15"))

    def test_micro_daily_loss_prefers_perps_delta_over_total_equity_noise(self):
        from scripts import sodex_micro_pilot as pilot

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "micro.jsonl"
            path.write_text(json.dumps({
                "mode": "live",
                "reason": "ok",
                "ts_utc": datetime(2026, 6, 25, 10, tzinfo=timezone.utc).isoformat(),
                "account_delta_usd": -9.0,
                "perps_account_delta_usd": -0.04,
            }) + "\n")

            loss = pilot.micro_daily_loss_used_usd(
                datetime(2026, 6, 25, 12, tzinfo=timezone.utc),
                path,
            )

        self.assertEqual(loss, Decimal("0.04"))

    def test_micro_daily_loss_counts_ratio_breach_live_records(self):
        from scripts import sodex_micro_pilot as pilot

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "micro.jsonl"
            path.write_text(json.dumps({
                "mode": "live",
                "reason": "farming_ratio_breach_after_close",
                "ts_utc": datetime(2026, 7, 8, 21, tzinfo=timezone.utc).isoformat(),
                "perps_account_delta_usd": -0.01934478,
            }) + "\n")

            loss = pilot.micro_daily_loss_used_usd(
                datetime(2026, 7, 8, 22, tzinfo=timezone.utc),
                path,
            )

        self.assertEqual(loss, Decimal("0.01934478"))

    def test_days_to_event_end_uses_25_july_deadline(self):
        from scripts import sodex_micro_pilot as pilot

        days = pilot.days_to_event_end(datetime(2026, 6, 25, tzinfo=pilot.WIB))

        self.assertEqual(days, Decimal("30"))

    def test_dry_run_style_halt_override_is_explicitly_allowed_by_caller(self):
        from scripts import sodex_micro_pilot as pilot

        policy = {
            "signal": {"fresh": True},
            "opportunity_lanes": [{"lane": "MICRO_PRE_LOSER_SHORT_ONLY", "max_notional_usd": 25.0}],
        }
        report = {"account": {"assets": {"perps_positions": []}}}

        ok, reason, _ = pilot.policy_allows_micro(
            policy,
            report,
            Decimal("12"),
            halt_exists=True,
            override_halt=True,
        )

        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_select_candidate_returns_highest_scored_valid_symbol(self):
        from scripts import sodex_micro_pilot as pilot

        books = {
            "AAA-USD": {"bids": [{"price": "1.0000"}], "asks": [{"price": "1.0008"}]},
            "BBB-USD": {"bids": [{"price": "2.0000"}], "asks": [{"price": "2.0010"}]},
        }
        rows = [
            {"symbol": "AAA-USD", "changePct": "-2.0", "quoteVolume": "100000", "fundingRate": "0"},
            {"symbol": "BBB-USD", "changePct": "-6.0", "quoteVolume": "200000", "fundingRate": "-0.0001"},
        ]

        with patch.object(pilot, "orderbook", side_effect=lambda symbol: books[symbol]):
            candidate = pilot.select_candidate(rows)

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.symbol, "BBB-USD")

    def test_prefilter_limits_negative_liquid_candidates(self):
        from scripts import sodex_micro_pilot as pilot

        rows = [
            {"symbol": f"S{i}-USD", "changePct": str(-i), "quoteVolume": "100000"}
            for i in range(1, 20)
        ]
        rows.append({"symbol": "UP-USD", "changePct": "5", "quoteVolume": "10000000"})

        picked = pilot._prefilter_tickers(rows, None)

        self.assertEqual(len(picked), 12)
        self.assertEqual(picked[0]["symbol"], "S19-USD")
        self.assertNotIn("UP-USD", {row["symbol"] for row in picked})

    def test_ratio_recovery_prefilter_keeps_liquid_non_losers(self):
        from scripts import sodex_micro_pilot as pilot

        rows = [
            {"symbol": "UP-USD", "changePct": "2", "quoteVolume": "2000000"},
            {"symbol": "LOW-USD", "changePct": "1", "quoteVolume": "1000"},
        ]

        picked = pilot._prefilter_tickers(rows, None, ratio_recovery=True)

        self.assertEqual([row["symbol"] for row in picked], ["UP-USD"])

    def test_prefilter_forced_symbol_keeps_only_requested_symbol(self):
        from scripts import sodex_micro_pilot as pilot

        rows = [
            {"symbol": "AAA-USD", "changePct": "-9", "quoteVolume": "100000"},
            {"symbol": "BBB-USD", "changePct": "5", "quoteVolume": "1"},
        ]

        self.assertEqual(pilot._prefilter_tickers(rows, "BBB-USD"), [rows[1]])

    def test_run_cycles_continues_after_maker_no_fill_without_cooldown_sleep(self):
        from scripts import sodex_micro_pilot as pilot

        args = Namespace(
            live=True,
            entry_mode="maker",
            cycles=3,
            cooldown_seconds=300,
        )
        rows = [
            {"reason": "no_maker_short_fill_detected", "opened_size": 0.0},
            {"reason": "no_maker_short_fill_detected", "opened_size": 0.0},
            {"reason": "no_maker_short_fill_detected", "opened_size": 0.0},
        ]

        with patch.object(pilot, "build_record", side_effect=rows), \
             patch.object(pilot, "append_log"), \
             patch.object(pilot.time, "sleep") as sleep:
            records = pilot.run_cycles(args)

        self.assertEqual(len(records), 3)
        sleep.assert_not_called()

    def test_build_record_blocks_live_before_order_when_ta_gate_fails(self):
        from scripts import sodex_micro_pilot as pilot

        args = Namespace(
            live=True,
            notional="10",
            operator_override_safety_halt=False,
            operator_override_barbell_cooldown=True,
            entry_mode="maker",
            exit_mode="maker",
            symbol="XPL-USD",
            confirm_seconds=0,
            hold_seconds=0,
            max_pre_entry_rebound_pct="0.0005",
            exit_maker_attempts=1,
            exit_maker_attempt_seconds=0,
            min_ta_probability="0.80",
        )
        policy = {
            "decision": "MICRO",
            "signal": {"fresh": True},
            "opportunity_lanes": [{"lane": "RATIO_RECOVERY_MAKER_ONLY", "max_notional_usd": 20.0}],
        }
        report = {
            "account": {
                "assets": {"perps_positions": []},
                "account_value": {"total_equity_usd": 100.0, "perps_account_value_usd": 50.0},
            }
        }
        candidate = pilot.Candidate(
            "XPL-USD",
            Decimal("0.0910"),
            Decimal("0.0913"),
            Decimal("0.09115"),
            Decimal("0.001"),
            Decimal("-12"),
            Decimal("100000"),
            Decimal("0.0001"),
            Decimal("14"),
        )

        with patch.object(pilot, "monitor_report", return_value=report), \
             patch.object(pilot, "target_policy", return_value=policy), \
             patch.object(pilot, "micro_daily_loss_used_usd", return_value=Decimal("0")), \
             patch.object(pilot, "micro_daily_volume_usd", return_value=Decimal("0")), \
             patch.object(pilot, "halt_active", return_value=False), \
             patch.object(pilot, "current_barbell_gate", return_value={}), \
             patch.object(pilot, "tickers", return_value=[]), \
             patch.object(pilot, "select_candidate", return_value=candidate), \
             patch.object(pilot, "market_specs", return_value={}), \
             patch.object(pilot, "ta_probability_gate", return_value={
                 "passes": False,
                 "probability": 0.44,
                 "reasons": ["ta_probability_below_minimum"],
             }), \
             patch.object(pilot, "place_order") as place_order:
            record = pilot.build_record(args)

        self.assertFalse(record["allowed"])
        self.assertEqual(record["reason"], "ta_probability_gate_failed")
        self.assertEqual(record["ta_probability_gate"]["probability"], 0.44)
        place_order.assert_not_called()

    def test_qty_for_notional_rounds_down(self):
        from scripts import sodex_micro_pilot as pilot

        self.assertEqual(pilot.qty_for_notional(Decimal("12"), Decimal("2")), "6")
        self.assertEqual(pilot.qty_for_notional(Decimal("12"), Decimal("0.018425")), "651")
        self.assertEqual(pilot.qty_for_notional(Decimal("12"), Decimal("0.0006")), "20000")

    def test_qty_for_notional_respects_exchange_step_and_min_notional(self):
        from scripts import sodex_micro_pilot as pilot

        with patch.object(
            pilot,
            "market_specs",
            return_value={
                "step_size": Decimal("0.001"),
                "min_quantity": Decimal("0.001"),
                "min_notional": Decimal("10"),
            },
        ):
            self.assertEqual(pilot.qty_for_notional(Decimal("10"), Decimal("1314.5"), "SKHX-USD"), "0.008")
