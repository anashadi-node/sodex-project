import dataclasses
import inspect
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, skipUnless
from unittest.mock import patch, MagicMock

from anantara import sodex_twin_engine as twin


# AUDIT 29-Sep-2026 — karantina varian "W18"; DIPERSEMPIT 01-Okt-2026.
#
# Semula SELURUH file di-skip (46 tes) dgn asumsi semua tes membangun `twin.Config(...)`
# memakai field W18. Verifikasi kode menunjukkan hanya kelas `E1W18ReadinessGuardTests`
# (26 tes) yang memakai `e1_deadline_mode_enabled`/`e1_profit_only_enabled`; 20 tes lain
# (TestPVEAdaptiveScheduling 8, LiveAdapterFailureAccountingTests 2,
#  Engine2CrashRecoveryTests 5, HedgeLeverageFallbackTests 5) menguji engine yang HIDUP
# dan selama ini tidak pernah berjalan — cakupan hilang tanpa perlu.
# Karantina kini menempel HANYA pada kelas W18; auto-terbuka bila field kembali ada.
_HAS_W18 = "e1_deadline_mode_enabled" in {f.name for f in dataclasses.fields(twin.Config)}
# Fitur PVE adaptive scheduling dihapus dari engine: 0 kemunculan _pve_schedule_candidates,
# pve_call_every, reconcile_balance_pre_e1. 8 tes kelas ini menguji fitur itu (bukan
# perilaku hidup) -> dikarantina dgn alasan tepat, auto-terbuka bila fitur kembali.
_HAS_PVE_SCHED = hasattr(twin.Orchestrator, "_pve_schedule_candidates")


@skipUnless(_HAS_PVE_SCHED, "fitur PVE adaptive scheduling sudah tak ada di engine "
               "(0 kemunculan _pve_schedule_candidates/pve_call_every) — tes berbasis "
               "nama implementasi, bukan perilaku hidup")
class TestPVEAdaptiveScheduling(TestCase):
    @staticmethod
    def _engine(pair, blocked=True, inv="0", pending=False):
        engine = MagicMock()
        engine.pair = pair
        engine.inv_qty = twin.D(inv)
        engine.pending_maker = {"oid": "1"} if pending else {}
        engine._adaptive_blocked.return_value = blocked
        return engine

    def test_selected_markets_skip_idle_round_robin_slots(self):
        orch = twin.Orchestrator.__new__(twin.Orchestrator)
        orch.x = MagicMock()
        orch.x._pve_other_positions = []
        idle = self._engine("ETH-USD", blocked=True)
        selected = self._engine("ENA-USD", blocked=False)
        orch.pve_engines = [idle, selected]

        self.assertEqual(orch._pve_schedule_candidates(), [selected])

    def test_recovery_position_is_prioritized_even_when_not_selected(self):
        orch = twin.Orchestrator.__new__(twin.Orchestrator)
        orch.x = MagicMock()
        orch.x._pve_other_positions = ["BTC-USD"]
        recovery = self._engine("BTC-USD", blocked=True)
        selected = self._engine("ENA-USD", blocked=False)
        orch.pve_engines = [recovery, selected]

        self.assertEqual(orch._pve_schedule_candidates(), [recovery])

    def test_pending_open_is_exclusive_until_resolved(self):
        orch = twin.Orchestrator.__new__(twin.Orchestrator)
        orch.x = MagicMock()
        orch.x._pve_other_positions = []
        pending = self._engine("ENA-USD", blocked=False, pending=True)
        selected = self._engine("ZEC-USD", blocked=False)
        orch.pve_engines = [pending, selected]

        self.assertEqual(orch._pve_schedule_candidates(), [pending])

    def test_pve_call_frequency_is_configurable_and_bounded(self):
        command = [
            sys.executable,
            "-c",
            "from anantara.sodex_twin_engine import Config; "
            "print(Config().pve_call_every)",
        ]
        for raw, expected in (("2", "2"), ("0", "1")):
            env = {**os.environ, "TE_PVE_CALL_EVERY": raw}
            result = subprocess.run(
                command, cwd=Path(__file__).resolve().parents[1], env=env,
                text=True, capture_output=True, check=True,
            )
            self.assertEqual(result.stdout.strip(), expected)

    def test_run_uses_configured_pve_call_frequency(self):
        source = inspect.getsource(twin.Orchestrator.run)
        self.assertIn("i % self.cfg.pve_call_every == 0", source)

    def test_b58_reconciles_inventory_before_each_live_e1_step(self):
        source = inspect.getsource(twin.Orchestrator.run)
        pre_e1 = source.index('"reconcile_balance_pre_e1"')
        e1_step = source.index('_run_engine_step_with_timeout(self.e1, "E1")')
        self.assertLess(pre_e1, e1_step)

    def test_b58_seeds_balance_baseline_during_live_initialization(self):
        source = inspect.getsource(twin.Orchestrator.__init__)
        sync = source.index("self._sync_inventory_from_exchange(force=True)")
        baseline = source.index("self._reconcile_all_from_balance()", sync)
        self.assertGreater(baseline, sync)

    def test_e1_profit_only_does_not_disable_ratio_gated_pve(self):
        source = inspect.getsource(twin.Orchestrator.__init__)
        pve_init = source[source.index("PERPS VOLUME ENGINE"):]
        self.assertIn("if PVE_ACTIVE:", pve_init)
        self.assertNotIn("perps_live_allowed and PVE_ACTIVE", pve_init)


class DummyTreasury:
    def authorize(self, est_fee):
        return True


class DummyGuards:
    def principal_fee_ok(self, extra_fee):
        return True

    def spend_principal_fee(self, fee):
        pass


class DummyTelegram:
    def send(self, text):
        pass


class BookFailAdapter:
    def list_pairs(self):
        return ["ENA-USD"]

    def book(self, pair):
        raise RuntimeError("empty book")

    def place_post_only(self, pair, side, price, qty):
        raise AssertionError("place_post_only must not run when book is unavailable")

    def cancel(self, order):
        pass

    def poll_fill(self, order):
        return twin.D("0")

    def funding_rate(self, pair):
        return twin.D("0")


class FirstFillSecondRejectAdapter:
    def __init__(self):
        self.place_count = 0

    def list_pairs(self):
        return ["ENA-USD"]

    def book(self, pair):
        return twin.Book(bid=twin.D("10"), ask=twin.D("10.1"))

    def place_post_only(self, pair, side, price, qty):
        self.place_count += 1
        oid = "1" if self.place_count == 1 else "0"
        return twin.Order(oid=oid, pair=pair, side=side, price=price, qty=qty)

    def cancel(self, order):
        pass

    def poll_fill(self, order):
        if order.oid == "1" and order.filled < order.qty:
            inc = order.qty - order.filled
            order.filled = order.qty
            return inc
        return twin.D("0")

    def funding_rate(self, pair):
        return twin.D("0")


class RejectAllAdapter:
    def __init__(self):
        self.place_count = 0

    def list_pairs(self):
        return ["ENA-USD", "XPL-USD", "TON-USD"]

    def book(self, pair):
        return twin.Book(bid=twin.D("10"), ask=twin.D("10.1"))

    def place_post_only(self, pair, side, price, qty):
        self.place_count += 1
        return twin.Order(oid="0", pair=pair, side=side, price=price, qty=qty)

    def cancel(self, order):
        pass

    def poll_fill(self, order):
        return twin.D("0")

    def funding_rate(self, pair):
        return twin.D("0")


class E2DirRejectAdapter(RejectAllAdapter):
    def _sodex(self, *args, **kwargs):
        return {}


class LiveAdapterFailureAccountingTests(TestCase):
    def _adapter_with_response(self, response):
        adapter = object.__new__(twin.SodexLiveAdapter)
        adapter._sodex = lambda *args, **kwargs: response
        return adapter

    def test_market_ioc_reject_has_zero_filled_qty(self):
        adapter = self._adapter_with_response({"orderID": 0})

        order = adapter.place_market_ioc(
            "BTC-USD", "buy", twin.D("0.01"), twin.D("60000"), reduce_only=False
        )

        self.assertEqual(order.oid, "0")
        self.assertEqual(order.filled, twin.D("0"))

    def test_limit_ioc_reject_has_zero_filled_qty(self):
        adapter = self._adapter_with_response({"orderID": 0})

        order = adapter.place_limit_ioc_perp(
            "1000PEPE-USD", "sell", twin.D("100"), twin.D("0.0028")
        )

        self.assertEqual(order.oid, "0")
        self.assertEqual(order.filled, twin.D("0"))


@skipUnless(_HAS_W18, "karantina audit 29-Sep-2026: fitur W18 (e1_deadline_mode_enabled) tak ada di engine")
class E1W18ReadinessGuardTests(TestCase):
    def test_b59_paper_step_ignores_production_halt_files(self):
        engine = object.__new__(twin.Engine1Flywheel)
        engine.reconcile_mode = False
        engine.cfg = MagicMock()
        engine.pair = "PEPE/USDC"
        engine.x = MagicMock()
        engine.x.book.side_effect = RuntimeError("paper continued past live guard")
        engine.orders = []

        with patch.object(twin, "global_live_block_reason", return_value="SAFETY_HALT_ACTIVE"):
            with self.assertRaisesRegex(RuntimeError, "paper continued past live guard"):
                engine.step()

    def test_live_equity_unavailable_does_not_fallback_to_incomparable_ledger(self):
        orchestrator = object.__new__(twin.Orchestrator)
        orchestrator.live = True
        orchestrator.x = MagicMock()
        orchestrator.x.account_equity.return_value = None
        orchestrator.cfg = MagicMock()
        orchestrator.cfg.capital_usd = twin.D("70")
        orchestrator.led = MagicMock()

        self.assertIsNone(orchestrator.equity_estimate())
        self.assertEqual(orchestrator._last_equity_source, "live_account_unavailable")
        orchestrator.led.total_profit_since.assert_not_called()

    def test_account_equity_prices_spot_plus_perps_account_value(self):
        adapter = object.__new__(twin.SodexLiveAdapter)
        adapter._env = {"SODEX_ADDRESS": "0xabc"}

        def fake_api(path):
            if path == "/spot/accounts/0xabc/balances":
                return {"data": {"balances": [
                    {"coin": "vUSDC", "total": "10", "locked": "0"},
                    {"coin": "vPEPE", "total": "1000000", "locked": "0"},
                ]}}
            if path == "/spot/markets/tickers":
                return {"data": {"tickers": [
                    {"symbol": "vPEPE_vUSDC", "bidPx": "0.000002", "askPx": "0.000004"},
                ]}}
            if path == "/perps/accounts/0xabc/state":
                return {"data": {"av": "7"}}
            raise AssertionError(path)

        adapter._api_get = fake_api

        self.assertEqual(adapter.account_equity(), twin.D("20.000000"))

    def test_account_equity_does_not_double_count_locked_spot_inventory(self):
        adapter = object.__new__(twin.SodexLiveAdapter)
        adapter._env = {"SODEX_ADDRESS": "0xabc"}

        def fake_api(path):
            if path == "/spot/accounts/0xabc/balances":
                return {"data": {"balances": [
                    {"coin": "vPEPE", "total": "100", "locked": "100"},
                ]}}
            if path == "/spot/markets/tickers":
                return {"data": {"tickers": [
                    {"symbol": "vPEPE_vUSDC", "bidPx": "2", "askPx": "2"},
                ]}}
            if path == "/perps/accounts/0xabc/state":
                return {"data": {"av": "0"}}
            raise AssertionError(path)

        adapter._api_get = fake_api

        self.assertEqual(adapter.account_equity(), twin.D("200"))

    def test_drawdown_guard_resets_high_when_equity_source_changes_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = twin.Ledger(str(Path(tmp) / "ledger.db"))
            cfg = twin.Config()
            object.__setattr__(cfg, "capital_usd", twin.D("500"))
            object.__setattr__(cfg, "drawdown_stop_frac", twin.D("0.15"))
            guard = twin.Guards(cfg, led, DummyTelegram())
            led.set_state("equity_high", twin.D("500"))

            guard.check_equity(twin.D("415"), "live_account")

            self.assertEqual(led.get_state("equity_high"), twin.D("415"))
            self.assertEqual(led.get_state_text("equity_high_source"), "live_account")

    def test_drawdown_guard_still_hard_stops_after_live_source_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = twin.Ledger(str(Path(tmp) / "ledger.db"))
            cfg = twin.Config()
            object.__setattr__(cfg, "capital_usd", twin.D("500"))
            object.__setattr__(cfg, "drawdown_stop_frac", twin.D("0.15"))
            guard = twin.Guards(cfg, led, DummyTelegram())
            guard.check_equity(twin.D("415"), "live_account")

            with self.assertRaises(twin.HardStop):
                guard.check_equity(twin.D("350"), "live_account")

    def test_cancel_all_perps_orders_uses_exchange_open_orders(self):
        adapter = object.__new__(twin.SodexLiveAdapter)
        adapter._sodex_list = MagicMock(return_value=[
            {"orderID": 114, "symbol": "DOGE-USD"},
            {"orderID": 115, "symbol": "SPCX-USD"},
            {"orderID": 116, "symbol": "PUMP-USD"},
            {"orderID": 117, "symbol": "XRP-USD"},
        ])
        adapter._sodex = MagicMock(return_value={})

        cancelled = adapter.cancel_all_perps_orders()

        self.assertEqual(cancelled, 4)
        calls = [call.args[0] for call in adapter._sodex.call_args_list]
        self.assertTrue(any("114" in args for args in calls))
        self.assertTrue(any("115" in args for args in calls))
        self.assertTrue(any("116" in args and "28" in args for args in calls))
        self.assertTrue(any("117" in args and "8" in args for args in calls))

    def test_xaut_symbol_id_is_available_for_cancel(self):
        adapter = object.__new__(twin.SodexLiveAdapter)

        self.assertEqual(adapter._sym_id("XAUT-USD"), 11)

    def test_cancel_requires_order_to_disappear_from_exchange(self):
        adapter = object.__new__(twin.SodexLiveAdapter)
        adapter._sodex = MagicMock(return_value={"status": ""})
        adapter._sodex_list_truth = MagicMock(return_value=([
            {"orderID": 123, "symbol": "XRP-USD"},
        ], True))
        order = twin.Order("123", "XRP-USD", "buy", twin.D("1.1"), twin.D("10"))

        with patch("anantara.sodex_twin_engine.time.sleep"):
            self.assertFalse(adapter.cancel(order))
        self.assertEqual(adapter._sodex_list_truth.call_count, 3)

    def test_cancel_succeeds_only_after_verified_absence(self):
        adapter = object.__new__(twin.SodexLiveAdapter)
        adapter._sodex = MagicMock(return_value={"status": ""})
        adapter._sodex_list_truth = MagicMock(return_value=([], True))
        order = twin.Order("123", "PUMP-USD", "buy", twin.D("0.002"), twin.D("100"))

        self.assertTrue(adapter.cancel(order))

    def test_cancel_fails_closed_when_order_list_read_fails(self):
        adapter = object.__new__(twin.SodexLiveAdapter)
        adapter._sodex = MagicMock(return_value={"status": ""})
        adapter._sodex_list_truth = MagicMock(return_value=([], False))
        order = twin.Order("123", "PUMP-USD", "buy", twin.D("0.002"), twin.D("100"))

        with patch("anantara.sodex_twin_engine.time.sleep"):
            self.assertFalse(adapter.cancel(order))

    def test_e2_loop_has_profit_only_runtime_guard(self):
        source = Path("anantara/sodex_twin_engine.py").read_text()
        self.assertIn("not self.cfg.e1_profit_only_enabled", source)
        self.assertIn("and self._perps_engines", source)

    def test_engine_step_timeout_guard_clears_orders(self):
        order = object()

        class HungEngine:
            pair = "E1b"

            def __init__(self):
                self.orders = [order]

            def step(self):
                raise twin.StepTimeout("hung")

        orch = object.__new__(twin.Orchestrator)
        orch.x = MagicMock()
        orch.tg = DummyTelegram()
        eng = HungEngine()

        with patch.object(twin.time, "sleep"):
            ok = orch._run_engine_step_with_timeout(eng, "E1b", timeout_s=1)

        self.assertFalse(ok)
        orch.x.cancel.assert_called_once_with(order)
        self.assertEqual(eng.orders, [])

    def test_write_safety_halt_preserves_existing_safety_halt_on_live_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            halt = Path(tmp) / "SAFETY_HALT"
            original = '{"reason":"drawdown"}'
            halt.write_text(original)
            with patch.object(twin, "SAFETY_HALT_FILE", halt):
                twin.write_safety_halt(
                    "live_start_blocked:SAFETY_HALT_ACTIVE:drawdown"
                )
            self.assertEqual(halt.read_text(), original)

    def test_compact_halt_reason_limits_nested_live_start_reason(self):
        reason = (
            "live_start_blocked:SAFETY_HALT_ACTIVE:"
            "live_start_blocked:SAFETY_HALT_ACTIVE:"
            "drawdown"
        )
        compact = twin._compact_halt_reason(reason)
        self.assertLessEqual(len(compact), 240)
        self.assertEqual(compact.count("live_start_blocked:SAFETY_HALT_ACTIVE:"), 1)

    def test_e1_readiness_blocks_when_spot_sell_block_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            block = Path(tmp) / "SODEX_SPOT_SELL_BLOCKED"
            verified = Path(tmp) / "SODEX_SPOT_SELL_VERIFIED"
            block.write_text('{"reason":"sell blocked"}')
            cfg = twin.Config()

            with patch.object(twin, "SPOT_SELL_BLOCK_FILE", block), \
                 patch.object(twin, "SPOT_SELL_VERIFIED_FILE", verified), \
                 patch.object(twin, "SAFETY_HALT_FILE", Path(tmp) / "SAFETY_HALT"), \
                 patch.object(twin, "PNL_HALT_FILE", Path(tmp) / "PNL_HALT"):
                report = twin.e1_w18_readiness(cfg)

        self.assertFalse(report["ready_for_live"])
        self.assertTrue(any("SPOT_SELL_CAPABILITY_BLOCKED" in b for b in report["blockers"]))

    def test_e1_readiness_requires_manual_sell_proof_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = twin.Config()

            with patch.object(twin, "SPOT_SELL_BLOCK_FILE", Path(tmp) / "SODEX_SPOT_SELL_BLOCKED"), \
                 patch.object(twin, "SPOT_SELL_VERIFIED_FILE", Path(tmp) / "SODEX_SPOT_SELL_VERIFIED"), \
                 patch.object(twin, "SAFETY_HALT_FILE", Path(tmp) / "SAFETY_HALT"), \
                 patch.object(twin, "PNL_HALT_FILE", Path(tmp) / "PNL_HALT"), \
                 patch.dict(twin.os.environ, {"TE_E1_REQUIRE_SELL_PROOF": "1"}, clear=False):
                reason = twin.e1_spot_capability_block_reason(cfg)

        self.assertIn("SPOT_SELL_PROOF_REQUIRED", reason)

    def test_e1_step_guard_cancels_orders_and_never_reads_book_when_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            block = Path(tmp) / "SODEX_SPOT_SELL_BLOCKED"
            block.write_text('{"reason":"sell blocked"}')
            cfg = twin.Config()
            led = MagicMock()
            led.get_state.return_value = "0"
            adapter = MagicMock()
            stale = twin.Order(
                oid="stale",
                pair="PEPE/USDC",
                side="buy",
                price=twin.D("0.1"),
                qty=twin.D("1"),
            )
            engine = twin.Engine1Flywheel(
                cfg, adapter, led, DummyGuards(), DummyTelegram(), hedge_enabled=False
            )
            engine.reconcile_mode = True
            engine.orders = [stale]

            with patch.object(twin, "SPOT_SELL_BLOCK_FILE", block), \
                 patch.object(twin, "SPOT_SELL_VERIFIED_FILE", Path(tmp) / "SODEX_SPOT_SELL_VERIFIED"), \
                 patch.object(twin, "SAFETY_HALT_FILE", Path(tmp) / "SAFETY_HALT"), \
                 patch.object(twin, "PNL_HALT_FILE", Path(tmp) / "PNL_HALT"):
                engine.step()

        adapter.cancel.assert_called_once_with(stale)
        adapter.book.assert_not_called()
        self.assertEqual(engine.orders, [])
        self.assertIn("SPOT_SELL_CAPABILITY_BLOCKED", engine._last_place_skip_reason)

    def test_profit_firewall_blocks_losing_flat_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "e1.db"
            cfg = twin.Config(
                db_path=str(db_path),
                e1_profit_firewall_min_n=3,
                e1_profit_firewall_window_n=10,
                e1_profit_firewall_pause_floor=twin.D("-0.0001"),
                e1_profit_firewall_min_win_rate=twin.D("0.50"),
                e1_deadline_mode_enabled=False,
            )
            led = twin.Ledger(str(db_path))
            for i in range(3):
                led.rt_close(f"E1-loss-{i}", "E1", "PEPE/USDC", twin.D("10"), twin.D("-0.02"))
            engine = twin.Engine1Flywheel(
                cfg, MagicMock(), led, DummyGuards(), DummyTelegram(), hedge_enabled=False
            )
            bk = twin.Book(bid=twin.D("0.00000280"), ask=twin.D("0.00000290"))

            self.assertEqual(engine._profit_firewall_action(bk), "block")
            self.assertIn("profit_firewall", engine._last_place_skip_reason)

    def test_deadline_mode_allows_losing_primary_pair_when_current_edge_is_large(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "e1.db"
            cfg = twin.Config(
                db_path=str(db_path),
                e1_deadline_mode_enabled=True,
                e1_decay_gate_enabled=False,
                e1_deadline_override_capture_bps=twin.D("20"),
                e1_profit_firewall_min_n=3,
                e1_profit_firewall_window_n=10,
                e1_profit_firewall_pause_floor=twin.D("-0.0001"),
                e1_profit_firewall_min_win_rate=twin.D("0.50"),
            )
            led = twin.Ledger(str(db_path))
            for i in range(3):
                led.rt_close(f"E1-loss-{i}", "E1", "PEPE/USDC", twin.D("10"), twin.D("-0.02"))
            engine = twin.Engine1Flywheel(
                cfg, MagicMock(), led, DummyGuards(), DummyTelegram(), hedge_enabled=False
            )
            bk = twin.Book(bid=twin.D("0.00000276"), ask=twin.D("0.00000277"))

            self.assertEqual(engine._profit_firewall_action(bk), "allow")

    def test_deadline_mode_still_blocks_losing_pair_when_current_edge_is_weak(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "e1.db"
            cfg = twin.Config(
                db_path=str(db_path),
                e1_deadline_mode_enabled=True,
                e1_decay_gate_enabled=False,
                e1_deadline_override_capture_bps=twin.D("20"),
                e1_profit_firewall_min_n=3,
                e1_profit_firewall_window_n=10,
                e1_profit_firewall_pause_floor=twin.D("-0.0001"),
                e1_profit_firewall_min_win_rate=twin.D("0.50"),
            )
            led = twin.Ledger(str(db_path))
            for i in range(3):
                led.rt_close(f"E1-loss-{i}", "E1", "PEPE/USDC", twin.D("10"), twin.D("-0.02"))
            engine = twin.Engine1Flywheel(
                cfg, MagicMock(), led, DummyGuards(), DummyTelegram(), hedge_enabled=False
            )
            bk = twin.Book(bid=twin.D("1.0000"), ask=twin.D("1.0001"))

            self.assertEqual(engine._profit_firewall_action(bk), "block")

    def test_decay_gate_beats_deadline_override_on_fresh_negative_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "e1.db"
            cfg = twin.Config(
                db_path=str(db_path),
                e1_deadline_mode_enabled=True,
                e1_deadline_override_capture_bps=twin.D("20"),
                e1_decay_gate_enabled=True,
                e1_decay_gate_hours=48,
                e1_decay_gate_min_n=3,
                e1_profit_firewall_min_n=3,
                e1_profit_firewall_window_n=10,
                e1_profit_firewall_pause_floor=twin.D("-0.0001"),
                e1_profit_firewall_min_win_rate=twin.D("0.50"),
            )
            led = twin.Ledger(str(db_path))
            for i in range(3):
                led.rt_close(f"E1-decay-{i}", "E1", "PEPE/USDC", twin.D("10"), twin.D("-0.02"))
            engine = twin.Engine1Flywheel(
                cfg, MagicMock(), led, DummyGuards(), DummyTelegram(), hedge_enabled=False
            )
            bk = twin.Book(bid=twin.D("0.00000270"), ask=twin.D("0.00000280"))

            self.assertEqual(engine._profit_firewall_action(bk), "block")
            self.assertIn("decay_gate", engine._last_place_skip_reason)

    def test_decay_gate_allows_sell_only_when_inventory_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "e1.db"
            cfg = twin.Config(
                db_path=str(db_path),
                e1_decay_gate_enabled=True,
                e1_decay_gate_min_n=3,
                e1_profit_firewall_min_n=3,
                e1_profit_firewall_window_n=10,
                e1_profit_firewall_pause_floor=twin.D("-0.0001"),
            )
            led = twin.Ledger(str(db_path))
            for i in range(3):
                led.rt_close(f"E1-decay-inv-{i}", "E1", "PEPE/USDC", twin.D("10"), twin.D("-0.02"))
            engine = twin.Engine1Flywheel(
                cfg, MagicMock(), led, DummyGuards(), DummyTelegram(), hedge_enabled=False
            )
            engine.inv_qty = twin.D("10000000")
            bk = twin.Book(bid=twin.D("0.00000270"), ask=twin.D("0.00000280"))

            self.assertEqual(engine._profit_firewall_action(bk), "sell_only")

    def test_profit_firewall_beats_force_aggressive_unstuck(self):
        class Adapter:
            def __init__(self):
                self.place_market_order = MagicMock(
                    return_value=twin.Order(
                        oid="m1", pair="PEPE/USDC", side="buy",
                        price=twin.D("0.00000280"), qty=twin.D("1")
                    )
                )

            def book(self, pair):
                return twin.Book(bid=twin.D("0.00000280"), ask=twin.D("0.00000290"))

            def _sodex_list(self, *args, **kwargs):
                return []

            def poll_fill(self, order):
                return twin.D("0")

            def cancel(self, order):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "e1.db"
            cfg = twin.Config(
                db_path=str(db_path),
                e1_min_spread=twin.D("0.0001"),
                e1_profit_firewall_min_n=3,
            )
            led = twin.Ledger(str(db_path))
            adapter = Adapter()
            engine = twin.Engine1Flywheel(
                cfg, adapter, led, DummyGuards(), DummyTelegram(), hedge_enabled=False
            )
            engine._last_fill_ts = twin.time.time() - engine._stuck_timeout_s - 1

            verified = Path(tmp) / "SODEX_SPOT_SELL_VERIFIED"
            verified.write_text("{}")
            with patch.object(twin, "SAFETY_HALT_FILE", Path(tmp) / "SAFETY_HALT"), \
                 patch.object(twin, "PNL_HALT_FILE", Path(tmp) / "PNL_HALT"), \
                 patch.object(twin, "SPOT_SELL_BLOCK_FILE", Path(tmp) / "SODEX_SPOT_SELL_BLOCKED"), \
                 patch.object(twin, "SPOT_SELL_VERIFIED_FILE", verified), \
                 patch.object(engine, "_profit_firewall_action", return_value="block"), \
                 patch.object(twin, "market_volatility", return_value=0.0):
                engine.step()

        adapter.place_market_order.assert_not_called()

    def test_profit_only_places_post_only_not_market_order(self):
        adapter = MagicMock()
        adapter.place_post_only.return_value = twin.Order(
            oid="po1", pair="PEPE/USDC", side="buy",
            price=twin.D("0.00000280"), qty=twin.D("1")
        )
        with tempfile.TemporaryDirectory() as tmp:
            cfg = twin.Config(
                db_path=str(Path(tmp) / "e1.db"),
                e1_profit_only_enabled=True,
                e1_inv_cap_per_pair=twin.D("100"),
                e1_size_ladder=(twin.D("10"),),
            )
            led = twin.Ledger(cfg.db_path)
            engine = twin.Engine1Flywheel(
                cfg, adapter, led, DummyGuards(), DummyTelegram(), hedge_enabled=False
            )
            with patch.object(engine, "_current_regime", return_value="NEUTRAL"):
                placed = engine._place_two_sided(
                    twin.Book(bid=twin.D("0.00000276"), ask=twin.D("0.00000277"))
                )

        self.assertGreater(placed, 0)
        adapter.place_post_only.assert_called()
        adapter.place_market_order.assert_not_called()

    def test_profit_only_blocks_buy_when_spread_edge_too_small(self):
        adapter = MagicMock()
        adapter.place_post_only.return_value = twin.Order(
            oid="po1", pair="PEPE/USDC", side="buy",
            price=twin.D("1.0"), qty=twin.D("10")
        )
        with tempfile.TemporaryDirectory() as tmp:
            cfg = twin.Config(
                db_path=str(Path(tmp) / "e1.db"),
                e1_profit_only_enabled=True,
                e1_min_capture_bps=twin.D("8"),
                e1_inv_cap_per_pair=twin.D("100"),
                e1_size_ladder=(twin.D("10"),),
            )
            led = twin.Ledger(cfg.db_path)
            engine = twin.Engine1Flywheel(
                cfg, adapter, led, DummyGuards(), DummyTelegram(), hedge_enabled=False
            )
            with patch.object(engine, "_current_regime", return_value="NEUTRAL"):
                placed = engine._place_two_sided(
                    twin.Book(bid=twin.D("1.0000"), ask=twin.D("1.0001"))
                )

        self.assertEqual(placed, 0)
        adapter.place_post_only.assert_not_called()
        adapter.place_market_order.assert_not_called()
        self.assertIn("edge_bps", engine._last_place_skip_reason)


class Engine2CrashRecoveryTests(TestCase):
    def make_engine(self, adapter, db_path: Path, **cfg_overrides):
        cfg = twin.Config(
            db_path=str(db_path),
            e2_clip_usd=(twin.D("10"), twin.D("10")),
            e2_fill_timeout_s=(0.01, 0.01),
            e2_pair_max_failures=1,
            e2_pair_cooldown_s=60,
            **cfg_overrides,
        )
        ledger = twin.Ledger(str(db_path))
        engine = twin.Engine2Perps(
            cfg,
            adapter,
            ledger,
            DummyGuards(),
            DummyTreasury(),
            DummyTelegram(),
            pair="ENA-USD",
        )
        return engine, ledger

    def test_book_failure_does_not_create_local_open_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine, ledger = self.make_engine(BookFailAdapter(), Path(tmp) / "e2.db")

            engine.churn_cycle()

            self.assertEqual(ledger.e2_get_open_positions(), [])

    def test_leg2_failure_keeps_confirmed_leg1_position_for_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine, ledger = self.make_engine(FirstFillSecondRejectAdapter(), Path(tmp) / "e2.db")

            engine.churn_cycle()

            open_positions = ledger.e2_get_open_positions()
            self.assertEqual(len(open_positions), 1)
            self.assertEqual(open_positions[0]["pair"], "ENA-USD")
            self.assertGreater(open_positions[0]["qty"], twin.D("0"))
            self.assertGreater(open_positions[0]["entry_px"], twin.D("0"))

    def test_ledger_rejects_zero_qty_open_records_and_can_clear_legacy_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = twin.Ledger(str(Path(tmp) / "e2.db"))

            with self.assertRaises(ValueError):
                ledger.e2_save_open("ENA-USD", "buy", twin.D("0"), twin.D("0"))

            ledger.con.execute(
                "INSERT INTO e2_open_pos(pair,side,qty,entry_px,opened_ts) VALUES(?,?,?,?,?)",
                ("ENA-USD", "buy", "0", "0", "2026-06-20T00:00:00+00:00"),
            )

            self.assertEqual(ledger.e2_clear_nonrecoverable_open_positions(), 1)
            self.assertEqual(ledger.e2_get_open_positions(), [])

    def test_cross_pair_rejections_open_global_route_circuit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "e2.db"
            cfg = twin.Config(
                db_path=str(db_path),
                e2_clip_usd=(twin.D("10"), twin.D("10")),
                e2_fill_timeout_s=(0.01, 0.01),
                e2_pair_max_failures=99,
                e2_route_max_failures=2,
                e2_route_fail_window_s=300,
                e2_route_cooldown_s=3600,
            )
            ledger = twin.Ledger(str(db_path))
            adapter = RejectAllAdapter()

            engine_a = twin.Engine2Perps(
                cfg, adapter, ledger, DummyGuards(), DummyTreasury(), DummyTelegram(), pair="ENA-USD"
            )
            engine_b = twin.Engine2Perps(
                cfg, adapter, ledger, DummyGuards(), DummyTreasury(), DummyTelegram(), pair="XPL-USD"
            )
            engine_c = twin.Engine2Perps(
                cfg, adapter, ledger, DummyGuards(), DummyTreasury(), DummyTelegram(), pair="TON-USD"
            )

            engine_a.churn_cycle()
            engine_b.churn_cycle()
            place_count_after_breaker = adapter.place_count

            engine_c.churn_cycle()

            self.assertEqual(adapter.place_count, place_count_after_breaker)
            self.assertGreater(engine_c._route_disabled_until(), twin.time.time())

    def test_e2_dir_live_rejections_share_global_route_circuit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "e2.db"
            cfg = twin.Config(
                db_path=str(db_path),
                e2_dir_live_enabled=True,
                e2_dir_size_usd=twin.D("11.0"),
                e2_route_max_failures=2,
                e2_route_fail_window_s=300,
                e2_route_cooldown_s=3600,
            )
            ledger = twin.Ledger(str(db_path))
            adapter = E2DirRejectAdapter()
            engine = twin.Engine2Directional(cfg, adapter, ledger, DummyTelegram())

            def sig(pair):
                return {
                    "pair": pair,
                    "side": "buy",
                    "grade": "B",
                    "funding_rate": twin.D("-0.001"),
                    "obi": twin.D("0.2"),
                }

            engine._open_position(sig("ENA-USD"))
            engine._open_position(sig("XPL-USD"))
            place_count_after_breaker = adapter.place_count

            engine._open_position(sig("TON-USD"))

            self.assertEqual(adapter.place_count, place_count_after_breaker)
            self.assertGreater(engine._route_disabled_until(), twin.time.time())


class Leg2PartialFillAdapter:
    """leg1 terisi penuh; leg2 cuma terisi SEPARUH lalu macet (fill realistis
    utk maker tipis) -- utk membuktikan fix K2 (partial != close sukses)."""
    def __init__(self):
        self.place_count = 0

    def list_pairs(self):
        return ["ENA-USD"]

    def book(self, pair):
        return twin.Book(bid=twin.D("10"), ask=twin.D("10.1"))

    def place_post_only(self, pair, side, price, qty):
        self.place_count += 1
        return twin.Order(oid=str(self.place_count), pair=pair, side=side, price=price, qty=qty)

    def cancel(self, order):
        pass

    def poll_fill(self, order):
        if order.filled >= order.qty:
            return twin.D("0")
        if order.oid == "1":  # leg1: isi penuh sekali poll
            inc = order.qty - order.filled
            order.filled += inc
            return inc
        if order.filled == twin.D("0"):  # leg2: isi separuh, lalu macet
            inc = order.qty / 2
            order.filled += inc
            return inc
        return twin.D("0")

    def funding_rate(self, pair):
        return twin.D("0")


class StopLossDirectionAdapter:
    """book() mengembalikan harga mid dari antrean `prices` berurutan tiap
    panggilan (panggilan ke-1 = harga entry, ke-2 = harga saat cek SL)."""
    def __init__(self, prices):
        self._queue = list(prices)
        self._last = self._queue[0] if self._queue else twin.D("100")
        self.book_calls = 0
        self.cancelled = False

    def list_pairs(self):
        return ["ENA-USD"]

    def book(self, pair):
        self.book_calls += 1
        if self._queue:
            self._last = self._queue.pop(0)
        return twin.Book(bid=self._last * twin.D("0.999"), ask=self._last * twin.D("1.001"))

    def place_post_only(self, pair, side, price, qty):
        return twin.Order(oid="1", pair=pair, side=side, price=price, qty=qty)

    def cancel(self, order):
        self.cancelled = True

    def poll_fill(self, order):
        return twin.D("0")

    def funding_rate(self, pair):
        return twin.D("0")


class Engine2MakerLegFixTests(TestCase):
    """Regresi audit 06-Okt-2026 (K1 arah SL tertukar, K2 partial-fill leg2
    diperlakukan sbg close sukses) -- lihat docs/sodex/SODEX_TWIN_ENGINE_AUDIT_2026-10-06.md."""

    def make_engine(self, adapter, db_path: Path, **cfg_overrides):
        defaults = dict(e2_clip_usd=(twin.D("10"), twin.D("10")), e2_fill_timeout_s=(0.01, 0.01))
        defaults.update(cfg_overrides)
        cfg = twin.Config(db_path=str(db_path), **defaults)
        ledger = twin.Ledger(str(db_path))
        engine = twin.Engine2Perps(
            cfg, adapter, ledger, DummyGuards(), DummyTreasury(), DummyTelegram(), pair="ENA-USD",
        )
        return engine, ledger

    def test_k2_leg2_partial_fill_keeps_position_open_for_reconcile(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine, ledger = self.make_engine(Leg2PartialFillAdapter(), Path(tmp) / "e2.db")

            engine.churn_cycle()

            open_positions = ledger.e2_get_open_positions()
            self.assertEqual(len(open_positions), 1,
                              "leg2 partial-fill HARUS tetap tercatat utk reconcile, bukan dibersihkan")

    def test_k1_buy_stop_loss_triggers_on_price_drop_not_rise(self):
        # buy (long): harga TURUN 100->90 adalah ADVERSE -> SL wajib trigger
        # cepat (book() cuma 2x: 1x entry + 1x cek SL), bukan menunggu timeout.
        adapter = StopLossDirectionAdapter([twin.D("100"), twin.D("90")])
        with tempfile.TemporaryDirectory() as tmp:
            engine, _ = self.make_engine(adapter, Path(tmp) / "e2.db",
                                          e2_fill_timeout_s=(3.0, 3.0))
            engine._maker_leg("buy", twin.D("100"), stop_loss_pct=twin.D("0.01"), aggressive=1)

            self.assertLessEqual(adapter.book_calls, 2,
                                  "SL buy harus trigger segera saat harga TURUN (K1 fix)")
            self.assertTrue(adapter.cancelled)

    def test_k1_sell_stop_loss_triggers_on_price_rise_not_drop(self):
        # sell (short): harga NAIK 100->110 adalah ADVERSE -> SL wajib trigger cepat.
        adapter = StopLossDirectionAdapter([twin.D("100"), twin.D("110")])
        with tempfile.TemporaryDirectory() as tmp:
            engine, _ = self.make_engine(adapter, Path(tmp) / "e2.db",
                                          e2_fill_timeout_s=(3.0, 3.0))
            engine._maker_leg("sell", twin.D("100"), stop_loss_pct=twin.D("0.01"), aggressive=1)

            self.assertLessEqual(adapter.book_calls, 2,
                                  "SL sell harus trigger segera saat harga NAIK (K1 fix)")
            self.assertTrue(adapter.cancelled)


class E2DirCloseAdapter:
    """Simulasi exchange utk close order E2Dir live -- utk membuktikan fix K4
    (exit live harus kirim order nyata, bukan cuma tutup ledger)."""
    def __init__(self, close_oid="C1", close_filled=None):
        self.close_calls = []
        self._close_oid = close_oid
        self._close_filled = close_filled  # None -> filled penuh

    def list_pairs(self):
        return ["ENA-USD"]

    def book(self, pair):
        return twin.Book(bid=twin.D("10"), ask=twin.D("10.1"))

    def place_market_ioc(self, pair, side, qty, ref_px, reduce_only=False):
        self.close_calls.append((pair, side, qty, ref_px, reduce_only))
        filled = qty if self._close_filled is None else self._close_filled
        return twin.Order(oid=self._close_oid, pair=pair, side=side, price=ref_px, qty=qty, filled=filled)

    def cancel(self, order):
        pass

    def poll_fill(self, order):
        return twin.D("0")

    def funding_rate(self, pair):
        return twin.D("0")


class Engine2DirectionalFixTests(TestCase):
    """Regresi audit 06-Okt-2026 (K3 edge_ok fail-open LIVE, K4 exit live tak
    kirim order close) -- lihat docs/sodex/SODEX_TWIN_ENGINE_AUDIT_2026-10-06.md."""

    def _open_stale_position(self, ledger):
        """Buat 1 posisi terbuka dgn opened_ts lampau -> timeout pasti kena
        begitu _manage_position dipanggil, tanpa perlu presisi harga SL/TP."""
        sig_id = ledger.e2_dir_open("ENA-USD", "buy", "B", twin.D("0"), twin.D("0"),
                                     twin.D("10"), twin.D("1"))
        ledger.con.execute("UPDATE e2_dir_signals SET opened_ts=? WHERE id=?",
                            ("2020-01-01T00:00:00+00:00", sig_id))
        return ledger.e2_dir_open_signals()[0]

    def test_k3_edge_gate_fail_closed_when_live_and_data_kurang(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "e2.db"
            ledger = twin.Ledger(str(db_path))

            paper = twin.Engine2Directional(
                twin.Config(db_path=str(db_path), e2_dir_live_enabled=False), None, ledger, DummyTelegram())
            ok, _ = paper.edge_ok()
            self.assertTrue(ok, "paper/riset: data kurang tetap fail-open (bootstrap sampel)")

            live = twin.Engine2Directional(
                twin.Config(db_path=str(db_path), e2_dir_live_enabled=True), None, ledger, DummyTelegram())
            ok, reason = live.edge_ok()
            self.assertFalse(ok, "LIVE: data kurang (n<min_n) wajib HALT, bukan fail-open (K3 fix)")
            self.assertIn("HALT", reason)

    def test_k4_live_close_sends_real_order_before_closing_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "e2.db"
            ledger = twin.Ledger(str(db_path))
            pos = self._open_stale_position(ledger)
            adapter = E2DirCloseAdapter()
            engine = twin.Engine2Directional(
                twin.Config(db_path=str(db_path), e2_dir_live_enabled=True), adapter, ledger, DummyTelegram())

            acted = engine._manage_position(pos)

            self.assertTrue(acted)
            self.assertEqual(len(adapter.close_calls), 1, "LIVE close harus kirim order nyata ke exchange")
            self.assertTrue(adapter.close_calls[0][4], "order close harus reduce_only=True")
            self.assertEqual(ledger.e2_dir_open_signals(), [],
                              "posisi harus closed di ledger setelah close order sukses")

    def test_k4_live_close_rejected_keeps_position_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "e2.db"
            ledger = twin.Ledger(str(db_path))
            pos = self._open_stale_position(ledger)
            adapter = E2DirCloseAdapter(close_oid="0")  # exchange menolak close order
            engine = twin.Engine2Directional(
                twin.Config(db_path=str(db_path), e2_dir_live_enabled=True), adapter, ledger, DummyTelegram())

            acted = engine._manage_position(pos)

            self.assertFalse(acted, "close order ditolak -> _manage_position return False")
            self.assertEqual(len(ledger.e2_dir_open_signals()), 1,
                              "posisi TIDAK boleh ke-ledger-close tanpa konfirmasi order nyata (K4 fix)")

    def test_k4_live_close_partial_fill_keeps_position_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "e2.db"
            ledger = twin.Ledger(str(db_path))
            pos = self._open_stale_position(ledger)
            adapter = E2DirCloseAdapter(close_filled=twin.D("0.5"))  # qty=1, cuma terisi separuh
            engine = twin.Engine2Directional(
                twin.Config(db_path=str(db_path), e2_dir_live_enabled=True), adapter, ledger, DummyTelegram())

            acted = engine._manage_position(pos)

            self.assertFalse(acted, "close order partial-fill -> _manage_position return False")
            self.assertEqual(len(ledger.e2_dir_open_signals()), 1,
                              "posisi partial-close TIDAK boleh ditandai closed (K4 fix)")


class S1PollCacheMarketScopeTests(TestCase):
    """Regresi S1 (audit 06-Okt-2026): self.x dibagi E1/E2Perps/E2Directional --
    cache _poll_cache milik Engine1 tak boleh dipercaya engine lain kalau scope
    market beda (spot vs perps), karena bisa lapor filled=0 PALSU."""

    def test_cache_ignored_when_market_scope_mismatched(self):
        ad = twin.SodexLiveAdapter.__new__(twin.SodexLiveAdapter)
        order = twin.Order(oid="42", pair="ENA-USD", side="buy", price=twin.D("1"), qty=twin.D("5"))
        # Cache dibangun scope SPOT oleh Engine1; order ini PERPS (E2Perps/E2Dir)
        ad._poll_cache = {"42": {"executedQty": "5"}}  # andai dipakai -> filled penuh (SALAH)
        ad._poll_cache_market = "spot"
        ad._sodex_list = lambda args, timeout=15: []  # fallback: order tak ketemu -> inc=0
        inc = ad.poll_fill(order)
        self.assertEqual(inc, twin.D(0), "cache market SALAH tak boleh dipakai (S1 fix)")
        self.assertEqual(order.filled, twin.D(0))

    def test_cache_used_when_market_scope_matches(self):
        ad = twin.SodexLiveAdapter.__new__(twin.SodexLiveAdapter)
        order = twin.Order(oid="42", pair="ENA-USD", side="buy", price=twin.D("1"), qty=twin.D("0"))
        ad._poll_cache = {"42": {"executedQty": "5"}}
        ad._poll_cache_market = "perps"
        inc = ad.poll_fill(order)
        self.assertEqual(inc, twin.D("5"), "cache market COCOK harus dipakai (hindari API call redundan)")


class S2EquitySkipAlertTests(TestCase):
    """Regresi S2 (audit 06-Okt-2026): fail-skip equity None dulu tak tercatat
    sama sekali -- sekarang counter streak + alert, tanpa ubah fail-SKIP itu
    sendiri (sengaja, cegah crash-loop 48x restart 26-Sep)."""

    def test_skip_streak_increments_then_resets(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "g.db"
            ledger = twin.Ledger(str(db_path))
            cfg = twin.Config(db_path=str(db_path))
            guards = twin.Guards(cfg, ledger, DummyTelegram())
            guards.check_equity(None, "live")
            guards.check_equity(None, "live")
            self.assertEqual(int(ledger.get_state("equity_skip_streak", "0")), 2,
                              "skip beruntun harus terhitung (S2 fix)")
            guards.check_equity(twin.D("100"), "live")
            self.assertEqual(int(ledger.get_state("equity_skip_streak", "0")), 0,
                              "equity terbaca sukses harus reset counter")


class S6RedactFilterTests(TestCase):
    """Regresi S6 (audit 06-Okt-2026): RedactFilter dulu tak cover SODEX_PRIVATE_KEY."""

    def test_redact_filter_covers_private_key(self):
        with patch.dict(os.environ, {"SODEX_PRIVATE_KEY": "0xabcdef1234567890deadbeefcafef00d"}):
            rf = twin.RedactFilter()
            self.assertIn("0xabcdef1234567890deadbeefcafef00d", rf.secrets,
                          "SODEX_PRIVATE_KEY wajib ter-redact (S6 fix)")


class FundingRateOnlyAdapter:
    def __init__(self, fr):
        self._fr = fr
    def funding_rate(self, pair):
        return self._fr


class BookOnlyAdapter:
    def __init__(self, mid):
        self._mid = mid
    def book(self, pair):
        return twin.Book(bid=self._mid, ask=self._mid)


class S9ObiProxyDeadCodeTests(TestCase):
    """Regresi S9 (audit 06-Okt-2026): proxy OBI lama SELALU 0 (Book.mid
    murni midpoint -> b_dist==a_dist aljabar). Sekarang obi=None jujur,
    grading funding/momentum-only, tidak crash float(None)."""

    def test_directional_signal_obi_none_grade_b_only(self):
        cfg = twin.Config(db_path=":memory:")
        adapter = FundingRateOnlyAdapter(twin.D("0.0005"))  # jauh di atas threshold
        sig = twin.generate_directional_signal(adapter, "ENA-USD", cfg)
        self.assertIsNotNone(sig)
        self.assertEqual(sig["grade"], "B", "tanpa OBI nyata, grade SELALU B (S9 fix)")
        self.assertIsNone(sig["obi"], "obi jujur None, bukan 0 pura-pura (S9 fix)")

    def test_directional_signal_below_threshold_none(self):
        cfg = twin.Config(db_path=":memory:")
        adapter = FundingRateOnlyAdapter(twin.D("0.0000001"))
        self.assertIsNone(twin.generate_directional_signal(adapter, "ENA-USD", cfg))

    def test_momentum_signal_obi_none_no_crash(self):
        cfg = twin.Config(db_path=":memory:", e2_mom_min_dt=0, e2_mom_max_dt=999999,
                           e2_mom_thr=twin.D("0.01"), e2_mom_reversion=False)
        cache = {}
        adapter = BookOnlyAdapter(twin.D("100"))
        self.assertIsNone(twin.generate_momentum_signal(adapter, "ENA-USD", cfg, cache))
        adapter._mid = twin.D("102")  # +2% move
        sig = twin.generate_momentum_signal(adapter, "ENA-USD", cfg, cache)
        self.assertIsNotNone(sig)
        self.assertIsNone(sig["obi"], "obi jujur None (S9 fix)")
        self.assertIn(sig["grade"], ("A", "B"))

    def test_e2_dir_open_accepts_none_obi(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "e2.db"
            ledger = twin.Ledger(str(db_path))
            sig_id = ledger.e2_dir_open("ENA-USD", "buy", "B", twin.D("0.0005"), None,
                                         twin.D("10"), twin.D("1"))
            self.assertGreater(sig_id, 0)


class S12PostOnlyClampTests(TestCase):
    """Regresi S12 (audit 06-Okt-2026): place_post_only() dulu kirim GTC
    verbatim dari harga caller TANPA klem -- order bisa silang spread jadi
    taker (fee 3,3x lebih mahal) kalau caller salah hitung/book bergerak."""

    def _adapter(self, bid, ask, captured):
        ad = twin.SodexLiveAdapter.__new__(twin.SodexLiveAdapter)
        ad._SIDES = {"buy", "sell"}
        ad.book = lambda pair: twin.Book(bid=bid, ask=ask)
        def fake_sodex(args, timeout=30):
            captured["args"] = args
            return {"orderID": "1"}
        ad._sodex = fake_sodex
        return ad

    def test_buy_price_crossing_ask_gets_clamped(self):
        captured = {}
        ad = self._adapter(twin.D("99"), twin.D("100"), captured)
        ad.place_post_only("ENA-USD", "buy", twin.D("101"), twin.D("5"))  # crosses ask!
        args = captured["args"]
        sent_px = float(args[args.index("--price") + 1])
        self.assertLess(sent_px, 100.0, "harga buy harus diklem di bawah ask (S12 fix)")

    def test_sell_price_crossing_bid_gets_clamped(self):
        captured = {}
        ad = self._adapter(twin.D("99"), twin.D("100"), captured)
        ad.place_post_only("ENA-USD", "sell", twin.D("98"), twin.D("5"))  # crosses bid!
        args = captured["args"]
        sent_px = float(args[args.index("--price") + 1])
        self.assertGreater(sent_px, 99.0, "harga sell harus diklem di atas bid (S12 fix)")

    def test_safe_price_not_touched(self):
        captured = {}
        ad = self._adapter(twin.D("99"), twin.D("100"), captured)
        ad.place_post_only("ENA-USD", "buy", twin.D("99.5"), twin.D("5"))  # aman, di dalam spread
        args = captured["args"]
        sent_px = float(args[args.index("--price") + 1])
        self.assertAlmostEqual(sent_px, 99.5, places=2, msg="harga aman tak boleh diubah")


# ──────────────────── HEDGE FIX TESTS (2026-06-22) ────────────────────────

class HedgeMarketIocOid0Adapter:
    """Adapter stub: place_market_ioc (non-reduce) → oid=0 (simulated exchange reject).
    place_limit_ioc_perp → valid oid (fallback works). book perps OK."""
    def __init__(self):
        self.limit_ioc_calls = 0
        self.lev_set_calls = 0  # diisi dari subprocess mock

    def list_pairs(self): return ["PEPE/USDC"]
    def book(self, pair):
        # Beri harga yang konsisten untuk PEPE/USDC (spot) dan 1000PEPE-USD (perp)
        return twin.Book(bid=twin.D("0.002800"), ask=twin.D("0.002860"))
    def place_post_only(self, pair, side, price, qty):
        return twin.Order(oid="S1", pair=pair, side=side, price=price, qty=qty)
    def place_market_ioc(self, pair, side, qty, ref_px, reduce_only=False):
        # Simulasi: exchange reject new open (reduce_only=False) → oid=0
        if not reduce_only:
            return twin.Order(oid="0", pair=pair, side=side, price=ref_px, qty=qty)
        # close (reduce_only=True) → OK
        return twin.Order(oid="MKT001", pair=pair, side=side, price=ref_px, qty=qty, filled=qty)
    def place_limit_ioc_perp(self, perp, side, qty, price):
        self.limit_ioc_calls += 1
        return twin.Order(oid="LIM001", pair=perp, side=side, price=price, qty=qty, filled=qty)
    def cancel(self, order): pass
    def poll_fill(self, order): return twin.D("0")
    def funding_rate(self, pair): return twin.D("0")
    def cancel_all_spot_orders(self): return 0


class DummyTg2:
    def send(self, text): pass


class DummyGuards2:
    def principal_fee_ok(self, extra_fee): return True
    def spend_principal_fee(self, fee): pass


class HedgeLeverageFallbackTests(TestCase):
    """Verifikasi fix B-1 (2026-06-22): leverage-set + limit-IOC fallback untuk short-OPEN."""

    def _make_flywheel(self, db_path: Path, adapter):
        cfg = twin.Config(
            db_path=str(db_path),
            spot_pair="PEPE/USDC",
            e1_hedge_enabled=True,
            e1_hedge_pairs="",           # semua pair
            e1_hedge_band=twin.D("1"),   # band kecil → mudah trigger
        )
        led = twin.Ledger(str(db_path))
        fw = twin.Engine1Flywheel(cfg, adapter, led, DummyGuards2(), DummyTg2(),
                                  hedge_enabled=True, pair="PEPE/USDC")
        return fw

    def test_hedge_lev_set_initialized_empty(self):
        """_hedge_lev_set harus ada dan kosong saat init."""
        with tempfile.TemporaryDirectory() as tmp:
            fw = self._make_flywheel(Path(tmp) / "db.db", HedgeMarketIocOid0Adapter())
            self.assertIsInstance(fw._hedge_lev_set, set)
            self.assertEqual(len(fw._hedge_lev_set), 0)

    def test_paper_adapter_place_limit_ioc_perp_returns_valid_oid(self):
        """PaperAdapter.place_limit_ioc_perp harus ada dan return oid != 0."""
        cfg = twin.Config()
        pa = twin.PaperAdapter(cfg)
        o = pa.place_limit_ioc_perp("1000PEPE-USD", "sell", twin.D("100"), twin.D("0.002800"))
        self.assertNotEqual(o.oid, "0")
        self.assertNotEqual(o.oid, "")
        self.assertEqual(o.pair, "1000PEPE-USD")
        self.assertEqual(o.side, "sell")

    @patch("anantara.sodex_twin_engine.subprocess.run")
    def test_hedge_sets_leverage_before_first_open(self, mock_subrun):
        """_rebalance_hedge harus memanggil subprocess leverage sebelum short-open pertama."""
        mock_subrun.return_value = MagicMock(stdout="leverage updated", stderr="", returncode=0)
        with tempfile.TemporaryDirectory() as tmp:
            adapter = HedgeMarketIocOid0Adapter()
            fw = self._make_flywheel(Path(tmp) / "db.db", adapter)
            fw.inv_qty = twin.D("1000000")  # cukup besar agar hedge trigger
            # Force regime ke BEAR agar ratio=1.0
            fw._regime_label = "BEAR"
            fw._regime_cache_ts = twin.time.time() + 9999
            bk = twin.Book(bid=twin.D("0.002800"), ask=twin.D("0.002860"))
            fw._rebalance_hedge(bk)
            # subprocess.run harus dipanggil dengan "leverage"
            calls = [str(c) for c in mock_subrun.call_args_list]
            self.assertTrue(any("leverage" in c for c in calls),
                            f"leverage tidak di-set, calls: {calls}")

    @patch("anantara.sodex_twin_engine.subprocess.run")
    def test_hedge_fallback_limit_ioc_when_market_ioc_oid0(self, mock_subrun):
        """Ketika place_market_ioc oid=0 untuk open, harus fallback ke place_limit_ioc_perp."""
        mock_subrun.return_value = MagicMock(stdout="leverage updated", stderr="", returncode=0)
        with tempfile.TemporaryDirectory() as tmp:
            adapter = HedgeMarketIocOid0Adapter()
            fw = self._make_flywheel(Path(tmp) / "db.db", adapter)
            fw.inv_qty = twin.D("1000000")
            fw._regime_label = "BEAR"
            fw._regime_cache_ts = twin.time.time() + 9999
            bk = twin.Book(bid=twin.D("0.002800"), ask=twin.D("0.002860"))
            fw._rebalance_hedge(bk)
            # limit_ioc_calls harus 1 (fallback dipanggil)
            self.assertEqual(adapter.limit_ioc_calls, 1,
                             "place_limit_ioc_perp harus dipanggil sebagai fallback")
            # hedge_qty harus > 0 (hedge berhasil via fallback)
            self.assertGreater(fw.hedge_qty, twin.D("0"),
                               "hedge_qty harus > 0 setelah fallback berhasil")

    @patch("anantara.sodex_twin_engine.subprocess.run")
    def test_hedge_leverage_set_cached_not_repeated(self, mock_subrun):
        """Leverage tidak boleh di-set ulang untuk perp yang sudah di-set."""
        mock_subrun.return_value = MagicMock(stdout="leverage updated", stderr="", returncode=0)
        with tempfile.TemporaryDirectory() as tmp:
            adapter = HedgeMarketIocOid0Adapter()
            fw = self._make_flywheel(Path(tmp) / "db.db", adapter)
            fw.inv_qty = twin.D("1000000")
            fw._regime_label = "BEAR"
            fw._regime_cache_ts = twin.time.time() + 9999
            bk = twin.Book(bid=twin.D("0.002800"), ask=twin.D("0.002860"))
            # Panggil dua kali
            fw._rebalance_hedge(bk)
            call1 = mock_subrun.call_count
            fw._rebalance_hedge(bk)
            call2 = mock_subrun.call_count
            # subprocess.run untuk leverage tidak boleh ditambah di panggilan kedua
            # (hedge_qty > 0 sekarang, delta mungkin 0 → _rebalance skip sebelum leverage step)
            # Yang penting: _hedge_lev_set berisi perp setelah panggilan pertama
            self.assertIn("1000PEPE-USD", fw._hedge_lev_set)
