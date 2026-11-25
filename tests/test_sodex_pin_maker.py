import json
import sys
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

from anantara.sodex_twin_engine import Book, Order
from scripts.sodex_pin_maker import (
    PinConfig,
    PinMaker,
    _normalize_systemd_environment,
    parse_args,
    research_gate_allows,
)


class FakeLedger:
    def __init__(self):
        self.fills = []
        self.rts = []

    def fill(self, *args):
        self.fills.append(args)

    def rt_close(self, *args):
        self.rts.append(args)


class FakeAdapter:
    def __init__(self):
        self.cfg = SimpleNamespace(perp_maker_fee=D("0.000108"),
                                   perp_taker_fee=D("0.00036"))
        self._perps_positions_read_ok = True
        self.positions = {}
        self.orders = {}
        self.n = 0
        self.bid = D("0.0857")
        self.ask = D("0.0858")
        self.reject_sell_with_position = False

    def perps_account_value(self):
        return D("257")

    def perps_positions(self):
        return self.positions.copy()

    def book(self, _pair):
        return Book(self.bid, self.ask)

    def _sodex_list_truth(self, _args, timeout=15):
        return list(self.orders.values()), True

    def place_limit_gtx_perp(self, pair, side, qty, price, reduce_only=False):
        if side == "sell" and not reduce_only and self.reject_sell_with_position:
            self.positions[pair] = qty / 2
            return None
        self.n += 1
        oid = str(self.n)
        self.orders[oid] = {"orderID": oid, "symbol": pair, "side": side}
        return Order(oid, pair, side, price, qty)

    def cancel(self, order):
        self.orders.pop(str(order.oid), None)
        return True

    def place_market_ioc(self, pair, side, qty, ref_px, reduce_only=False):
        self.positions.pop(pair, None)
        self.n += 1
        return Order(str(self.n), pair, side, ref_px, qty, filled=qty)


class PinMakerTests(unittest.TestCase):
    def make_engine(self):
        td = tempfile.TemporaryDirectory()
        adapter = FakeAdapter()
        ledger = FakeLedger()
        cfg = PinConfig(settle_s=0, loss_cap_usd=D("0.25"))
        engine = PinMaker(adapter, ledger, cfg, Path(td.name) / "state.json")
        self.addCleanup(td.cleanup)
        return engine, adapter, ledger

    def test_both_orders_disappear_flat_records_paired_round_trip(self):
        engine, adapter, ledger = self.make_engine()
        self.assertEqual(engine.tick()["action"], "quote")
        qty = D(engine.state["active"]["qty"])
        adapter.orders.pop("1")
        adapter.positions[engine.cfg.pair] = qty
        self.assertEqual(engine.tick()["action"], "maker_close")
        adapter.orders.clear()
        adapter.positions.clear()
        result = engine.tick()
        self.assertEqual(result["kind"], "paired")
        self.assertGreater(result["net_pnl"], 0)
        self.assertEqual(engine.state["round_trips"], 1)
        self.assertEqual(len(ledger.rts), 1)

    def test_disappeared_orders_without_position_are_not_counted(self):
        engine, adapter, ledger = self.make_engine()
        engine.tick()
        adapter.orders.clear()
        result = engine.tick()
        self.assertEqual(result["reason"], "paired_fill_unverified")
        self.assertEqual(engine.state["round_trips"], 0)
        self.assertEqual(ledger.rts, [])

    def test_partial_fill_is_cancelled_and_flattened(self):
        engine, adapter, _ = self.make_engine()
        engine.tick()
        qty = D(engine.state["active"]["qty"])
        adapter.positions[engine.cfg.pair] = qty / 2
        result = engine.tick()
        self.assertEqual(result["action"], "maker_close")
        self.assertTrue(result["reduce_only"])
        self.assertEqual(len(adapter.orders), 1)
        adapter.orders.clear()
        adapter.positions.clear()
        result = engine.tick()
        self.assertEqual(result["kind"], "paired")
        self.assertEqual(engine.state["orphans"], 0)

    def test_maker_close_gets_a_fresh_phase_ttl(self):
        engine, adapter, _ = self.make_engine()
        engine.tick()
        qty = D(engine.state["active"]["qty"])
        adapter.positions[engine.cfg.pair] = qty
        self.assertEqual(engine.tick()["action"], "maker_close")
        engine.state["active"]["opened_ts"] = 0

        result = engine.tick()

        self.assertEqual(result["action"], "monitor")
        self.assertNotEqual(adapter.positions, {})

    def test_realized_loss_cap_halts_new_quotes(self):
        engine, _, _ = self.make_engine()
        engine.state["net_pnl_usd"] = -0.25
        result = engine.tick()
        self.assertEqual(result["action"], "halt")
        self.assertEqual(result["reason"], "pin_realized_loss_cap")

    def test_realized_ratio_floor_halts_after_minimum_sample(self):
        engine, _, _ = self.make_engine()
        engine.state.update({"round_trips": 5, "volume_usd": 100.0,
                             "net_pnl_usd": -0.03})

        allowed, reason = engine._risk_gate()

        self.assertFalse(allowed)
        self.assertEqual(reason, "pin_realized_ratio_floor")

    def test_realized_ratio_floor_waits_for_minimum_sample(self):
        engine, _, _ = self.make_engine()
        engine.state.update({"round_trips": 4, "volume_usd": 80.0,
                             "net_pnl_usd": -0.03})

        allowed, reason = engine._risk_gate()

        self.assertTrue(allowed)
        self.assertEqual(reason, "approved")

    def test_shutdown_cleanup_preserves_halted_state(self):
        engine, adapter, _ = self.make_engine()
        self.assertEqual(engine.tick()["action"], "quote")
        engine._halt("ttl_cancel_unconfirmed")

        engine.shutdown_cleanup()

        self.assertEqual(adapter.orders, {})
        self.assertIsNone(engine.state["active"])
        self.assertEqual(engine.state["status"], "HALTED")
        self.assertEqual(engine.state["halt_reason"], "ttl_cancel_unconfirmed")

    def test_resume_after_flat_preserves_cumulative_accounting(self):
        engine, _, _ = self.make_engine()
        engine.state.update({"status": "HALTED", "halt_reason": "transient",
                             "volume_usd": 105.23, "net_pnl_usd": -0.034})

        ok, reason = engine.resume_after_flat()

        self.assertTrue(ok)
        self.assertEqual(reason, "resumed_flat")
        self.assertEqual(engine.state["status"], "READY")
        self.assertEqual(engine.state["volume_usd"], 105.23)
        self.assertEqual(engine.state["net_pnl_usd"], -0.034)

    def test_resume_is_rejected_when_position_exists(self):
        engine, adapter, _ = self.make_engine()
        engine.state["status"] = "HALTED"
        adapter.positions[engine.cfg.pair] = D("1")

        ok, reason = engine.resume_after_flat()

        self.assertFalse(ok)
        self.assertEqual(reason, "resume_position_exists")
        self.assertEqual(engine.state["status"], "HALTED")

    def test_second_leg_reject_retains_state_until_partial_is_flattened(self):
        engine, adapter, ledger = self.make_engine()
        adapter.reject_sell_with_position = True

        result = engine.tick()

        self.assertEqual(result["action"], "complete")
        self.assertEqual(result["kind"], "orphan")
        self.assertEqual(adapter.positions, {})
        self.assertIsNone(engine.state["active"])
        self.assertEqual(engine.state["status"], "READY")
        self.assertEqual(len(ledger.rts), 1)

    def test_short_close_keeps_original_bid_when_market_rises(self):
        engine, adapter, _ = self.make_engine()
        engine.tick()
        qty = D(engine.state["active"]["qty"])
        adapter.positions[engine.cfg.pair] = -qty
        adapter.bid = D("0.0858")
        adapter.ask = D("0.0859")
        result = engine.tick()
        self.assertEqual(result["action"], "maker_close")
        self.assertEqual(result["side"], "buy")
        self.assertEqual(result["price"], 0.0858)

    def test_systemd_inline_comment_is_removed(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"TE_PVE_MAX_NOTIONAL": "60 # bounded"}):
            _normalize_systemd_environment()
            self.assertEqual(os.environ["TE_PVE_MAX_NOTIONAL"], "60")

    def test_min_net_capture_cli_is_explicit(self):
        from unittest.mock import patch
        with patch.object(sys, "argv", ["sodex_pin_maker.py",
                                        "--min-net-capture-bps", "1.5"]):
            args = parse_args()

        self.assertEqual(args.min_net_capture_bps, "1.5")

    def test_market_rules_round_up_xaut_and_quote_one_tick_inside(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        adapter = FakeAdapter()
        adapter.bid = D("4060.8")
        adapter.ask = D("4061.3")
        cfg = PinConfig(
            pair="XAUT-USD",
            notional_usd=D("10"),
            tick_size=D("0.1"),
            qty_step=D("0.0001"),
            min_notional_usd=D("10"),
            price_improve_ticks=1,
            min_net_capture_bps=D("-10"),
            settle_s=0,
        )
        engine = PinMaker(adapter, FakeLedger(), cfg, Path(td.name) / "state.json")

        result = engine.tick()

        self.assertEqual(result["action"], "quote")
        self.assertEqual(engine.state["active"]["qty"], "0.0025")
        self.assertEqual(engine.state["active"]["bid"], "4060.9")
        self.assertEqual(engine.state["active"]["ask"], "4061.2")

    def test_research_gate_requires_passing_executable_scenario(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / "gate.json"
        path.write_text(json.dumps({
            "cost_model": {"ratio_floor": 4500},
            "results": {"XAUT-USD": {"queue_scenarios": {"1.0": {
                "notional_usd": 10,
                "micro_pilot_gate_pass": False,
            }}}},
        }))

        allowed, reason = research_gate_allows(
            path, "XAUT-USD", D("10"), D("4500")
        )

        self.assertFalse(allowed)
        self.assertEqual(reason, "research_gate_not_passed")

    def test_research_gate_rejects_smaller_test_notional(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / "gate.json"
        path.write_text(json.dumps({
            "cost_model": {"ratio_floor": 4500},
            "results": {"XAUT-USD": {"queue_scenarios": {"1.0": {
                "notional_usd": 2,
                "micro_pilot_gate_pass": True,
            }}}},
        }))

        allowed, reason = research_gate_allows(
            path, "XAUT-USD", D("10"), D("4500")
        )

        self.assertFalse(allowed)
        self.assertEqual(reason, "research_gate_notional_too_low")

    def test_engine_halts_before_order_when_research_gate_fails(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        gate = Path(td.name) / "gate.json"
        gate.write_text(json.dumps({
            "cost_model": {"ratio_floor": 4500},
            "results": {"XAUT-USD": {"queue_scenarios": {"1.0": {
                "notional_usd": 10,
                "micro_pilot_gate_pass": False,
            }}}},
        }))
        adapter = FakeAdapter()
        cfg = PinConfig(
            pair="XAUT-USD",
            notional_usd=D("10"),
            research_gate_path=gate,
            settle_s=0,
        )
        engine = PinMaker(adapter, FakeLedger(), cfg, Path(td.name) / "state.json")

        result = engine.tick()

        self.assertEqual(result["action"], "halt")
        self.assertEqual(result["reason"], "research_gate_not_passed")
        self.assertEqual(adapter.orders, {})

    def test_engine_does_not_silently_raise_subminimum_notional(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        adapter = FakeAdapter()
        cfg = PinConfig(notional_usd=D("2"), min_notional_usd=D("10"), settle_s=0)
        engine = PinMaker(adapter, FakeLedger(), cfg, Path(td.name) / "state.json")

        result = engine.tick()

        self.assertEqual(result["action"], "halt")
        self.assertEqual(result["reason"], "configured_notional_below_market_minimum")
        self.assertEqual(adapter.orders, {})


if __name__ == "__main__":
    unittest.main()
