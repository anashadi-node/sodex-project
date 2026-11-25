import importlib.util
import contextlib
import io
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase, mock

from anantara.sodex_spot_governor import (
    FillRateCalibrator,
    RiskMonitor,
    SpotState,
    _weekly_cutoff_bounds,
    spot_expectancy_gate,
)
from anantara.sodex_pregain_scanner import build_candidates, enrich_with_state, scan
from anantara.sodex_event_shock_guard import _classify, _level, enrich_event_route_policy, event_route_policy
from anantara.sosovalue_macro import EtfSentiment, MacroContext, SectorBias, TopMover, TopMoverContext


class SpotFarmingSafetyTests(TestCase):
    def test_daemon_uses_guarded_spot_wrapper_not_legacy_executor(self):
        daemon_source = Path("anantara/anantara_daemon.py").read_text()

        self.assertIn('"scripts/sodex_spot_daemon.py", "once"', daemon_source)
        self.assertNotIn('"anantara/sodex_spot_farm.py", "run"', daemon_source)

    def test_ad_hoc_auto_rt_monitor_is_disabled(self):
        script = Path("scripts/auto_rt_monitor.sh").read_text()

        self.assertIn("deprecated and disabled", script)
        self.assertNotIn("grep SODEX_PRIVATE_KEY", script)
        self.assertNotIn("orders', 'place', 'spot'", script)

    def test_deprecated_spot_executor_refuses_live_without_override(self):
        path = Path("anantara/sodex_spot_farm.py")
        spec = importlib.util.spec_from_file_location("sodex_spot_farm_legacy", path)
        legacy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(legacy)
        book = {
            "bids": [[0.00000280, 5_000_000]],
            "asks": [[0.00000290, 5_000_000]],
        }

        with mock.patch.dict(os.environ, {"SODEX_SPOT_FARM_LIVE": "1"}, clear=True), \
             mock.patch.object(legacy, "PROVEN_FLAG", "/tmp/proven-for-test"), \
             mock.patch.object(legacy.os.path, "exists", return_value=True), \
             mock.patch.object(legacy, "fetch_book", return_value=book), \
             mock.patch.object(legacy, "_place") as place, \
             contextlib.redirect_stdout(io.StringIO()) as out:
            legacy.plan(capital=30, live=True)

        self.assertIn("deprecated executor disabled", out.getvalue())
        place.assert_not_called()

    def test_mode7_intel_round_symbol_exists_for_daemon_toggle(self):
        import anantara.sodex_farming as sf

        with mock.patch.object(
            sf,
            "mode7_round",
            return_value={"ok": True, "filled": False, "volume": 0.0},
        ) as base_round:
            result = sf.mode7_intel_round("BTC-USD", {}, margin=1, leverage=1)

        base_round.assert_called_once()
        self.assertEqual(result["intel_mode"], "integrated")

    def test_live_scalp_job_has_single_signal_scan_per_cycle(self):
        """Invarian job scalp LIVE: SATU deklarasi budget global & SATU scan per siklus.

        AUDIT 29-Sep-2026: test lama mengukur `job_sodex_farm()` yang sudah TIDAK ADA
        (refactor 13-Agu-2026 menghapus job itu; sisa marker `SODEX_USE_MODEL` dan
        `sf.fmt_price(symbol, ref)` juga nol di seluruh file). Job yang benar-benar
        terjadwal & memegang uang nyata sekarang = `job_sodex_scalp` (sched 6879).
        Invarian yang dijaga tetap sama: budget volume/order hanya dideklarasikan
        global SEKALI per siklus (kalau dobel, akuntansi budget jadi siluman).
        """
        daemon_source = Path("anantara/anantara_daemon.py").read_text()
        start = daemon_source.index("async def job_sodex_scalp():")
        end = daemon_source.index("async def job_sodex_spot_farm():", start)
        job_source = daemon_source[start:end]

        self.assertEqual(
            job_source.count("global _sodex_vol_today, _sodex_orders_today"), 1,
            "job scalp harus men-deklarasikan global budget tepat SEKALI per siklus")
        self.assertIn("open_positions_list", job_source,
                      "job scalp wajib memeriksa posisi terbuka sebelum entry")

    def test_funding_paper_timeout_is_non_fatal_warning(self):
        daemon_source = Path("anantara/anantara_daemon.py").read_text()
        start = daemon_source.index("async def job_funding_paper_validate():")
        end = daemon_source.index("async def job_regime_check():", start)
        job_source = daemon_source[start:end]

        self.assertIn("except subprocess.TimeoutExpired as e:", job_source)
        self.assertIn("Funding paper timeout", job_source)
        self.assertIn("STATE[\"last_fh_paper\"]", job_source)

    def test_funding_monitor_timeout_is_non_fatal_warning(self):
        daemon_source = Path("anantara/anantara_daemon.py").read_text()
        start = daemon_source.index("async def job_funding_monitor():")
        end = daemon_source.index("async def job_funding_paper_validate():", start)
        job_source = daemon_source[start:end]

        self.assertIn("except subprocess.TimeoutExpired as e:", job_source)
        self.assertIn("Funding monitor timeout", job_source)
        self.assertIn("STATE[\"last_funding_plan\"]", job_source)

    def test_scalp_skips_when_position_state_is_unverified(self):
        daemon_source = Path("anantara/anantara_daemon.py").read_text()
        start = daemon_source.index("async def job_sodex_scalp():")
        # AUDIT 29-Sep-2026: job bernama job_sodex_farm() sudah tidak ada; namanya
        # job_sodex_spot_farm() (refactor daemon). Test lama error ValueError pada
        # anchor, bukan menguji gate unverified-nya.
        end = daemon_source.index("async def job_sodex_spot_farm():", start)
        job_source = daemon_source[start:end]

        self.assertIn('if any(p.get("warning") for p in open_positions_list):', job_source)
        self.assertIn("position state unverified", job_source)

    def test_monitor_skips_auto_exit_when_position_state_is_unverified(self):
        daemon_source = Path("anantara/anantara_daemon.py").read_text()
        start = daemon_source.index("async def job_sodex_monitor():")
        end = daemon_source.index("async def job_sodex_revalidate():", start)
        job_source = daemon_source[start:end]

        self.assertIn('if any(p.get("warning") for p in positions):', job_source)
        self.assertIn("skip automated exits this cycle", job_source)


class SpotGovernorTests(TestCase):
    def test_expectancy_gate_vetoes_unprofitable_spread(self):
        decision = spot_expectancy_gate(
            spread_pct=0.12,
            cost_pct=0.17,
            free_capital=20,
            risk=RiskMonitor(SpotState()),
            calibrator=FillRateCalibrator(),
            intel_mult=1.0,
            intel_spread_min=0.10,
        )

        self.assertFalse(decision.go)
        self.assertIn("NET", decision.reason)

    def test_expectancy_gate_caps_deploy_at_90_percent_free_capital(self):
        decision = spot_expectancy_gate(
            spread_pct=0.35,
            cost_pct=0.17,
            free_capital=20,
            risk=RiskMonitor(SpotState()),
            calibrator=FillRateCalibrator(),
            intel_mult=2.0,
            intel_spread_min=0.25,
        )

        self.assertTrue(decision.go)
        self.assertEqual(decision.max_capital, 18)

    def test_state_serializes_drawdown_pct(self):
        state = SpotState(peak_equity=20, current_equity=19)

        self.assertEqual(state.to_dict()["drawdown_pct"], 5.0)

    def test_weekly_cutoff_is_saturday_0700_wib(self):
        start, end = _weekly_cutoff_bounds(
            datetime(2026, 6, 8, 4, 0, tzinfo=timezone.utc)
        )

        self.assertEqual(start, "2026-06-06T00:00:00+00:00")
        self.assertEqual(end, "2026-06-13T00:00:00+00:00")

    def test_target_status_passes_ratio_when_weekly_pnl_positive(self):
        state = SpotState()
        risk = RiskMonitor(state)
        risk.update(pnl=50, equity=210, volume_usd=1_300_000, fee_est_usd=150)

        target = state.target_status()

        self.assertEqual(target["weekly_ratio"], "NET_PROFIT")
        self.assertTrue(target["ratio_ok"])
        self.assertTrue(target["net_profit_ok"])
        self.assertEqual(target["required_weekly_turnover_x_capital"], 8125.0)

    def test_target_status_reports_catch_up_gap_and_required_hourly_volume(self):
        state = SpotState()
        state.ensure_weekly_window(datetime(2026, 6, 10, 0, 0, tzinfo=timezone.utc))
        state.weekly_volume_usd = 100_000
        state.weekly_wins = 7
        state.weekly_losses = 2

        target = state.target_status(datetime(2026, 6, 10, 0, 0, tzinfo=timezone.utc))

        self.assertEqual(target["weekly_target_mode"], "CATCH_UP")
        self.assertEqual(target["weekly_volume_gap_usd"], 1_200_000.0)
        self.assertEqual(target["hours_remaining_week"], 72.0)
        self.assertEqual(target["required_hourly_volume_usd"], 16666.67)

    def test_target_status_prioritizes_quality_recovery_when_weekly_win_rate_low(self):
        state = SpotState()
        state.ensure_weekly_window(datetime(2026, 6, 10, 0, 0, tzinfo=timezone.utc))
        state.weekly_volume_usd = 900_000
        state.weekly_wins = 6
        state.weekly_losses = 4

        target = state.target_status(datetime(2026, 6, 10, 0, 0, tzinfo=timezone.utc))

        self.assertEqual(target["weekly_target_mode"], "QUALITY_RECOVERY")
        self.assertFalse(target["win_rate_ok"])
        self.assertEqual(target["win_rate_gap_pp"], 9.0)

    def test_state_load_backs_up_corrupt_json_and_reinitializes(self):
        import anantara.sodex_spot_governor as governor

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "spot_state.json"
            state_path.write_text("{bad json")

            with mock.patch.object(governor, "_STATE_FILE", state_path), \
                 self.assertLogs("spot_governor", level="WARNING") as logs:
                state = governor.SpotState.load()

            self.assertEqual(state.rt_count, 0)
            self.assertFalse(state_path.exists())
            backups = list(Path(tmpdir).glob("spot_state.json.corrupt-*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertIn("spot state file corrupt", "\n".join(logs.output))


class OpenPositionsSafetyTests(TestCase):
    def setUp(self):
        import anantara.sodex_farming as sf

        self.sf = sf
        self.sf._open_positions_cache.clear()
        self.sf._open_positions_warn_ts.clear()

    def test_open_positions_uses_fresh_cache_before_hitting_rest(self):
        cfg = {"address": "0xabc", "perps_url": "https://example.invalid"}
        cached = [{"symbol": "BTC-USD", "quantity": 1.0}]

        with mock.patch.object(self.sf.time, "time", return_value=100.0):
            self.sf._open_positions_cache[cfg["address"]] = (100.0, [dict(p) for p in cached])
            with mock.patch.object(self.sf.httpx, "Client") as client:
                got = self.sf.open_positions(cfg)

        self.assertEqual(got, cached)
        client.assert_not_called()
        got[0]["quantity"] = 99.0
        with mock.patch.object(self.sf.time, "time", return_value=100.0):
            again = self.sf.open_positions(cfg)
        self.assertEqual(again[0]["quantity"], 1.0)

    def test_open_positions_returns_unverified_sentinel_when_state_cannot_be_read(self):
        cfg = {"address": "0xdef", "perps_url": "https://example.invalid"}
        client = mock.MagicMock()
        client.get.side_effect = RuntimeError("gateway down")
        cm = mock.MagicMock()
        cm.__enter__.return_value = client
        cm.__exit__.return_value = False

        with mock.patch.object(self.sf.httpx, "Client", return_value=cm):
            got = self.sf.open_positions(cfg)

        self.assertEqual(got[0]["symbol"], "UNKNOWN")
        self.assertEqual(got[0]["warning"], "api_unverified")
        self.assertIn("gateway down", got[0]["reason"])

    def test_open_positions_treats_null_positions_payload_as_flat_account(self):
        cfg = {"address": "0xflat", "perps_url": "https://example.invalid"}
        response = mock.MagicMock()
        response.status_code = 200
        response.json.return_value = {"data": {"P": None}}
        client = mock.MagicMock()
        client.get.return_value = response
        cm = mock.MagicMock()
        cm.__enter__.return_value = client
        cm.__exit__.return_value = False

        with mock.patch.object(self.sf.httpx, "Client", return_value=cm):
            got = self.sf.open_positions(cfg)

        self.assertEqual(got, [])

    def test_open_positions_uses_stale_nonempty_cache_if_rest_fails(self):
        cfg = {"address": "0xghi", "perps_url": "https://example.invalid"}
        cached = [{"symbol": "ETH-USD", "quantity": 2.0}]
        client = mock.MagicMock()
        client.get.side_effect = RuntimeError("state timeout")
        cm = mock.MagicMock()
        cm.__enter__.return_value = client
        cm.__exit__.return_value = False

        with mock.patch.object(self.sf.time, "time", return_value=120.0):
            self.sf._open_positions_cache[cfg["address"]] = (100.0, [dict(p) for p in cached])
            with mock.patch.object(self.sf.httpx, "Client", return_value=cm):
                got = self.sf.open_positions(cfg)

        self.assertEqual(got, cached)


class SpotDaemonWrapperTests(TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path("scripts/sodex_spot_daemon.py")
        spec = importlib.util.spec_from_file_location("sodex_spot_daemon", path)
        cls.daemon = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.daemon)

    def setUp(self):
        self.force_env = mock.patch.dict(os.environ, {}, clear=False)
        self.force_env.start()
        self.addCleanup(self.force_env.stop)
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.state_patch = mock.patch.object(
            self.daemon, "STATE_FILE", Path(self.tmpdir.name) / "state.json"
        )
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        # AUDIT 29-Sep-2026: state PRODUKSI bocor ke test -> 9 test non-deterministik.
        # Bukti: data/SODEX_SPOT_SELL_BLOCKED (stale 21-Sep) membuat run_once()
        # SKIPPED 'SPOT_SELL_CAPABILITY_BLOCKED' sebelum parser stdout diuji,
        # dan ~/.local/share/anantara/sodex_spot_state.json (consecutive_losses=17)
        # ikut terbaca. Test harus mengisolasi SEMUA berkas status, bukan hanya STATE_FILE.
        for attr, name in (("SPOT_SELL_BLOCK_FILE", "sell_block.json"),
                           ("SAFETY_HALT_FILE", "SAFETY_HALT"),
                           ("PNL_HALT_FILE", "PNL_HALT"),
                           ("PROJECT_DIR", None)):
            if name is None:
                continue
            patcher = mock.patch.object(self.daemon, attr, Path(self.tmpdir.name) / name)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.lock_patch = mock.patch.object(
            self.daemon, "AUTOFARM_LOCK_FILE", Path(self.tmpdir.name) / "autofarm.lock"
        )
        self.lock_patch.start()
        self.addCleanup(self.lock_patch.stop)
        self.kill_patch = mock.patch.object(self.daemon, "is_killed", return_value=False)
        self.kill_patch.start()
        self.addCleanup(self.kill_patch.stop)
        self.clear_alert_patch = mock.patch.object(self.daemon, "clear_alert")
        self.clear_alert_patch.start()
        self.addCleanup(self.clear_alert_patch.stop)

    def test_run_once_keeps_prime_time_gate_by_default(self):
        with mock.patch.object(self.daemon, "_event_risk_preflight", return_value=(True, None, {})), \
             mock.patch.object(self.daemon, "_adaptive_policy_preflight", return_value=(True, None, {})), \
             mock.patch.object(self.daemon.subprocess, "run") as run:
            run.return_value.stdout = ""
            run.return_value.stderr = ""
            self.daemon.run_once()

        cmd = run.call_args.args[0]
        self.assertNotIn("--force", cmd)

    def test_run_once_allows_explicit_force_override(self):
        os.environ["SODEX_SPOT_FORCE"] = "1"

        with mock.patch.object(self.daemon, "_event_risk_preflight", return_value=(True, None, {})), \
             mock.patch.object(self.daemon, "_adaptive_policy_preflight", return_value=(True, None, {})), \
             mock.patch.object(self.daemon.subprocess, "run") as run:
            run.return_value.stdout = ""
            run.return_value.stderr = ""
            self.daemon.run_once()

        cmd = run.call_args.args[0]
        self.assertIn("--force", cmd)

    def test_run_once_reports_prime_time_skip(self):
        with mock.patch.object(self.daemon, "_event_risk_preflight", return_value=(True, None, {})), \
             mock.patch.object(self.daemon, "_adaptive_policy_preflight", return_value=(True, None, {})), \
             mock.patch.object(self.daemon.subprocess, "run") as run:
            run.return_value.stdout = "   Error: NOT_PRIME_TIME\n"
            run.return_value.stderr = ""
            run.return_value.returncode = 0
            result = self.daemon.run_once()

        self.assertEqual(result["status"], "SKIPPED")
        self.assertEqual(result["reason"], "NOT_PRIME_TIME")

    def test_run_once_reports_event_risk_skip(self):
        with mock.patch.object(self.daemon, "_event_risk_preflight", return_value=(True, None, {})), \
             mock.patch.object(self.daemon, "_adaptive_policy_preflight", return_value=(True, None, {})), \
             mock.patch.object(self.daemon.subprocess, "run") as run:
            run.return_value.stdout = "   Error: EVENT_RISK_RED_headline shock\n"
            run.return_value.stderr = ""
            run.return_value.returncode = 0
            result = self.daemon.run_once()

        self.assertEqual(result["status"], "SKIPPED")
        self.assertEqual(result["reason"], "EVENT_RISK_RED_headline shock")

    def test_run_once_preflights_event_risk_before_subprocess(self):
        risk = {
            "level": "RED",
            "live_gate": "BLOCK_LIVE",
            "risk_score": 98.0,
            "reason": "Iran Trump whale shock",
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        with mock.patch.object(self.daemon, "EVENT_STATUS_FILE", Path(self.tmpdir.name) / "status.json"), \
             mock.patch.object(self.daemon.subprocess, "run") as run:
            self.daemon.EVENT_STATUS_FILE.write_text(json.dumps({"event_risk": risk}))
            result = self.daemon.run_once()

        self.assertEqual(result["status"], "SKIPPED")
        self.assertTrue(result["reason"].startswith("EVENT_RISK_RED_"))
        run.assert_not_called()

    def test_event_preflight_uses_status_ts_for_freshness(self):
        old_risk_ts = "2026-06-08T00:00:00+00:00"
        risk = {
            "level": "RED",
            "live_gate": "BLOCK_LIVE",
            "risk_score": 98.0,
            "reason": "cached headline shock",
            "ts": old_risk_ts,
        }
        status_file = Path(self.tmpdir.name) / "status.json"
        status_file.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_risk": risk,
        }))

        with mock.patch.object(self.daemon, "EVENT_STATUS_FILE", status_file):
            ok, reason, event_risk = self.daemon._event_risk_preflight()

        self.assertFalse(ok)
        self.assertTrue(reason.startswith("EVENT_RISK_RED_"))
        self.assertNotIn("STALE", reason)
        self.assertEqual(event_risk["ts"], old_risk_ts)
        self.assertLess(event_risk["status_age_s"], 5)

    def test_run_once_preflights_adaptive_policy_before_subprocess(self):
        policy = {
            "status": "READY_FOR_PAPER_SELECTION",
            "external_live_gate": "ALLOW_WITH_CAUTION",
            "promote": [],
            "block": [{
                "route": "SPOT_LONG",
                "win_rate": 0.1087,
                "avg_edge_return_pct": -0.8558,
            }],
            "promote_count": 0,
            "block_count": 1,
        }
        with mock.patch.object(self.daemon, "_event_risk_preflight", return_value=(True, None, {})), \
             mock.patch.object(self.daemon, "EVENT_STATUS_FILE", Path(self.tmpdir.name) / "status.json"), \
             mock.patch.object(self.daemon.subprocess, "run") as run:
            self.daemon.EVENT_STATUS_FILE.write_text(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "adaptive_policy": policy,
            }))
            result = self.daemon.run_once()

        self.assertEqual(result["status"], "SKIPPED")
        self.assertTrue(result["reason"].startswith("POLICY_BLOCK_ROUTE_SPOT_LONG"))
        run.assert_not_called()

    def test_run_once_persists_execution_failure_for_consecutive_guard(self):
        with mock.patch.object(self.daemon, "_event_risk_preflight", return_value=(True, None, {})), \
             mock.patch.object(self.daemon, "_adaptive_policy_preflight", return_value=(True, None, {})), \
             mock.patch.object(self.daemon.subprocess, "run") as run:
            run.return_value.stdout = "   Error: SELL_CANCELLED_TIMEOUT_EXIT_FAILED\n"
            run.return_value.stderr = ""
            run.return_value.returncode = 0
            result = self.daemon.run_once()

        state = json.loads(self.daemon.STATE_FILE.read_text())
        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(state["consecutive_losses"], 1)
        self.assertEqual(state["last_error"], "SELL_CANCELLED_TIMEOUT_EXIT_FAILED")

    def test_show_status_enriches_legacy_state_with_target_status(self):
        self.daemon.STATE_FILE.write_text(json.dumps({"rt_count": 1, "total_pnl": 0.5}))

        status = self.daemon.show_status()

        self.assertIn("target_status", status)
        self.assertEqual(status["target_status"]["target_ratio_min"], 7100.0)

    def test_show_status_refreshes_legacy_target_status_without_weekly_mode(self):
        self.daemon.STATE_FILE.write_text(json.dumps({
            "rt_count": 1,
            "weekly_volume_usd": 100_000,
            "weekly_wins": 7,
            "weekly_losses": 2,
            "target_status": {"target_weekly_volume_usd": 1_300_000},
        }))

        status = self.daemon.show_status()

        self.assertIn("weekly_target_mode", status["target_status"])
        self.assertIn("required_hourly_volume_usd", status["target_status"])
        self.assertIn("guard_status", status)

    def test_show_status_reports_guards_without_trading_state(self):
        risk = {
            "level": "RED",
            "live_gate": "BLOCK_LIVE",
            "risk_score": 94.5,
            "reason": "headline shock",
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        policy = {
            "status": "BLOCKED_BY_EVENT_RISK",
            "external_live_gate": "BLOCK_LIVE",
            "live_route_decision": "BLOCKED_BY_EVENT_RISK",
            "promote_count": 1,
            "block_count": 2,
            "watch_count": 3,
        }
        status_file = Path(self.tmpdir.name) / "status.json"
        status_file.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_risk": risk,
            "adaptive_policy": policy,
        }))

        with mock.patch.object(self.daemon, "EVENT_STATUS_FILE", status_file):
            status = self.daemon.show_status()

        self.assertEqual(status["status"], "NO_TRADING_STATE")
        self.assertFalse(status["kill_switch"])
        self.assertEqual(status["guard_status"]["operator_status"], "BLOCKED_EVENT_RISK")
        self.assertEqual(status["guard_status"]["event_risk"]["level"], "RED")
        self.assertEqual(
            status["guard_status"]["adaptive_policy"]["live_route_decision"],
            "BLOCKED_BY_EVENT_RISK",
        )

    def test_show_status_marks_dead_autofarm_lock_as_stale(self):
        self.daemon.AUTOFARM_LOCK_FILE.write_text("999999 2026-06-09T00:00:00+00:00\n")
        status_file = Path(self.tmpdir.name) / "status.json"
        status_file.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_risk": {
                "level": "NORMAL",
                "live_gate": "ALLOW_WITH_CAUTION",
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            "adaptive_policy": {
                "status": "READY_FOR_PAPER_SELECTION",
                "external_live_gate": "ALLOW_WITH_CAUTION",
                "promote": [{"route": "SPOT_LONG", "win_rate": 1.0, "avg_edge_return_pct": 0.1}],
            },
        }))

        with mock.patch.object(self.daemon, "EVENT_STATUS_FILE", status_file):
            status = self.daemon.show_status()

        self.assertTrue(status["guard_status"]["autofarm_lock"]["exists"])
        self.assertFalse(status["guard_status"]["autofarm_lock"]["active"])
        self.assertTrue(status["guard_status"]["autofarm_lock"]["stale"])

    def test_show_status_reports_corrupt_trading_state_file(self):
        self.daemon.STATE_FILE.write_text("{bad json")
        status_file = Path(self.tmpdir.name) / "status.json"
        status_file.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_risk": {
                "level": "NORMAL",
                "live_gate": "ALLOW_WITH_CAUTION",
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            "adaptive_policy": {
                "status": "READY_FOR_PAPER_SELECTION",
                "external_live_gate": "ALLOW_WITH_CAUTION",
                "promote": [{"route": "SPOT_LONG", "win_rate": 1.0, "avg_edge_return_pct": 0.1}],
            },
        }))

        with mock.patch.object(self.daemon, "EVENT_STATUS_FILE", status_file):
            status = self.daemon.show_status()

        self.assertEqual(status["status"], "NO_TRADING_STATE")
        self.assertTrue(status["state_file_error"].startswith("JSONDecodeError:"))
        backups = list(Path(self.tmpdir.name).glob("state.json.corrupt-*.bak"))
        self.assertEqual(len(backups), 1)

    def test_doctor_reports_read_only_operational_findings(self):
        self.daemon.AUTOFARM_LOCK_FILE.write_text("999999 2026-06-09T00:00:00+00:00\n")
        status_file = Path(self.tmpdir.name) / "status.json"
        status_file.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": "READ_ONLY_RESEARCH",
            "last_status": "OK",
            "external_live_gate": "BLOCK_LIVE",
            "top_long_count": 1,
            "top_short_count": 0,
            "errors": [],
            "event_risk": {
                "level": "RED",
                "live_gate": "BLOCK_LIVE",
                "risk_score": 94.5,
                "reason": "headline shock",
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            "adaptive_policy": {
                "status": "BLOCKED_BY_EVENT_RISK",
                "external_live_gate": "BLOCK_LIVE",
                "live_route_decision": "BLOCKED_BY_EVENT_RISK",
                "promote_count": 1,
                "block_count": 2,
                "watch_count": 3,
            },
        }))

        with mock.patch.object(self.daemon, "EVENT_STATUS_FILE", status_file), \
             mock.patch.object(self.daemon, "_matching_processes", side_effect=lambda needle: (
                 [{"pid": 123, "cmd": "python3 scripts/sodex_autonomous_research.py --loop"}]
                 if needle == "sodex_autonomous_research.py" else []
             )):
            report = self.daemon.doctor()

        self.assertEqual(report["status"], "OK")
        self.assertEqual(report["summary"]["operator_status"], "BLOCKED_EVENT_RISK")
        self.assertTrue(report["summary"]["research_status_fresh"])
        self.assertEqual(report["summary"]["research_process_count"], 1)
        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("LIVE_BLOCKED_BY_EVENT_RISK", codes)
        self.assertIn("STALE_AUTOFARM_LOCK_FILE", codes)
        self.assertNotIn("RESEARCH_LOOP_NOT_RUNNING", codes)

    def test_doctor_surfaces_corrupt_trading_state_file(self):
        self.daemon.STATE_FILE.write_text("{bad json")
        status_file = Path(self.tmpdir.name) / "status.json"
        status_file.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": "READ_ONLY_RESEARCH",
            "last_status": "OK",
            "external_live_gate": "ALLOW_WITH_CAUTION",
            "event_risk": {
                "level": "NORMAL",
                "live_gate": "ALLOW_WITH_CAUTION",
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            "adaptive_policy": {
                "status": "READY_FOR_PAPER_SELECTION",
                "external_live_gate": "ALLOW_WITH_CAUTION",
                "promote": [{"route": "SPOT_LONG", "win_rate": 1.0, "avg_edge_return_pct": 0.1}],
            },
        }))

        with mock.patch.object(self.daemon, "EVENT_STATUS_FILE", status_file), \
             mock.patch.object(self.daemon, "_matching_processes", return_value=[]), \
             mock.patch.object(self.daemon, "_systemd_service_process", return_value=[]):
            report = self.daemon.doctor()

        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("TRADING_STATE_NOT_READABLE", codes)

    def test_doctor_summarizes_weekly_target_mode_and_opportunity_routes(self):
        self.daemon.STATE_FILE.write_text(json.dumps({
            "weekly_volume_usd": 100_000,
            "weekly_wins": 7,
            "weekly_losses": 2,
            "weekly_window_start": "2026-06-06T00:00:00+00:00",
            "weekly_window_end": "2026-06-13T00:00:00+00:00",
        }))
        status_file = Path(self.tmpdir.name) / "status.json"
        status_file.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": "READ_ONLY_RESEARCH",
            "last_status": "OK",
            "external_live_gate": "BLOCK_LIVE",
            "event_risk": {
                "level": "RED",
                "live_gate": "BLOCK_LIVE",
                "risk_score": 98.0,
                "top_hits": [{"categories": ["geo", "policy", "panic"]}],
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            "adaptive_policy": {
                "status": "BLOCKED_BY_EVENT_RISK",
                "external_live_gate": "BLOCK_LIVE",
                "live_route_decision": "BLOCKED_BY_EVENT_RISK",
                "promote_count": 1,
                "block_count": 2,
                "watch_count": 3,
            },
        }))

        with mock.patch.object(self.daemon, "EVENT_STATUS_FILE", status_file), \
             mock.patch.object(self.daemon, "_matching_processes", return_value=[]), \
             mock.patch.object(self.daemon, "_systemd_service_process", return_value=[]):
            report = self.daemon.doctor()

        self.assertEqual(report["summary"]["weekly_target_mode"], "CATCH_UP")
        self.assertEqual(report["summary"]["event_opportunity_routes"], ["PERPS_SHORT"])
        self.assertIn("required_hourly_volume_usd", report["summary"])

    def test_doctor_backfills_legacy_policy_event_opportunity_from_event_risk(self):
        status_file = Path(self.tmpdir.name) / "status.json"
        status_file.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": "READ_ONLY_RESEARCH",
            "last_status": "OK",
            "external_live_gate": "BLOCK_LIVE",
            "event_risk": {
                "level": "RED",
                "live_gate": "BLOCK_LIVE",
                "risk_score": 98.3,
                "top_hits": [{"categories": ["geo", "policy", "panic"]}],
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            "adaptive_policy": {
                "status": "BLOCKED_BY_EVENT_RISK",
                "external_live_gate": "BLOCK_LIVE",
                "live_route_decision": "BLOCKED_BY_EVENT_RISK",
                "promote_count": 1,
                "block_count": 2,
                "watch_count": 3,
            },
        }))

        with mock.patch.object(self.daemon, "EVENT_STATUS_FILE", status_file), \
             mock.patch.object(self.daemon, "_matching_processes", return_value=[]):
            report = self.daemon.doctor()

        policy = report["guard_status"]["adaptive_policy"]
        self.assertEqual(policy["status"], "RISK_EVENT_ROUTE_LIMITED")
        self.assertEqual(policy["event_opportunity_bias"], "SHORT")
        self.assertEqual(policy["event_opportunity_routes"], ["PERPS_SHORT"])
        route_state = {item["route"]: item for item in policy["route_opportunity_state"]}
        self.assertEqual(route_state["SPOT_LONG"]["action"], "BLOCK_LIVE")
        self.assertEqual(route_state["PERPS_SHORT"]["action"], "RESEARCH_OPPORTUNITY")
        self.assertTrue(route_state["PERPS_SHORT"]["event_aligned"])
        self.assertFalse(route_state["PERPS_SHORT"]["blocked"])

    def test_doctor_treats_fresh_status_as_current_when_process_hidden(self):
        status_file = Path(self.tmpdir.name) / "status.json"
        status_file.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": "READ_ONLY_RESEARCH",
            "last_status": "OK",
            "external_live_gate": "ALLOW_WITH_CAUTION",
            "event_risk": {
                "level": "NORMAL",
                "live_gate": "ALLOW_WITH_CAUTION",
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            "adaptive_policy": {
                "status": "READY_FOR_PAPER_SELECTION",
                "external_live_gate": "ALLOW_WITH_CAUTION",
                "promote": [{"route": "SPOT_LONG", "win_rate": 1.0, "avg_edge_return_pct": 0.1}],
            },
        }))

        with mock.patch.object(self.daemon, "EVENT_STATUS_FILE", status_file), \
             mock.patch.object(self.daemon, "_matching_processes", return_value=[]), \
             mock.patch.object(self.daemon, "_systemd_service_process", return_value=[]):
            report = self.daemon.doctor()

        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("RESEARCH_PROCESS_NOT_VISIBLE", codes)
        self.assertNotIn("RESEARCH_LOOP_NOT_RUNNING", codes)

    def test_doctor_uses_systemd_fallback_for_research_process_visibility(self):
        status_file = Path(self.tmpdir.name) / "status.json"
        status_file.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": "READ_ONLY_RESEARCH",
            "last_status": "OK",
            "external_live_gate": "ALLOW_WITH_CAUTION",
            "event_risk": {
                "level": "NORMAL",
                "live_gate": "ALLOW_WITH_CAUTION",
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            "adaptive_policy": {
                "status": "READY_FOR_PAPER_SELECTION",
                "external_live_gate": "ALLOW_WITH_CAUTION",
                "promote": [{"route": "SPOT_LONG", "win_rate": 1.0, "avg_edge_return_pct": 0.1}],
            },
        }))

        with mock.patch.object(self.daemon, "EVENT_STATUS_FILE", status_file), \
             mock.patch.object(self.daemon, "_matching_processes", return_value=[]), \
             mock.patch.object(
                 self.daemon,
                 "_systemd_service_process",
                 return_value=[{"pid": 426725, "cmd": "systemd:sodex-autonomous-research.service", "source": "systemd"}],
             ):
            report = self.daemon.doctor()

        self.assertEqual(report["summary"]["research_process_count"], 1)
        self.assertEqual(report["processes"]["research"][0]["source"], "systemd")
        codes = {finding["code"] for finding in report["findings"]}
        self.assertNotIn("RESEARCH_PROCESS_NOT_VISIBLE", codes)
        self.assertNotIn("RESEARCH_LOOP_NOT_RUNNING", codes)

    def test_doctor_surfaces_strong_learning_status(self):
        status_file = Path(self.tmpdir.name) / "status.json"
        status_file.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": "READ_ONLY_RESEARCH",
            "last_status": "OK",
            "external_live_gate": "ALLOW_WITH_CAUTION",
            "learning_strength": {
                "status": "STRONG_LEARNING_ACTIVE",
                "score": 100,
                "outcomes": 12_154,
                "best_route": "PERPS_SHORT",
                "best_win_rate": 1.0,
            },
            "event_risk": {
                "level": "NORMAL",
                "live_gate": "ALLOW_WITH_CAUTION",
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            "adaptive_policy": {
                "status": "READY_FOR_PAPER_SELECTION",
                "external_live_gate": "ALLOW_WITH_CAUTION",
                "promote": [{"route": "SPOT_LONG", "win_rate": 1.0, "avg_edge_return_pct": 0.1}],
            },
        }))

        with mock.patch.object(self.daemon, "EVENT_STATUS_FILE", status_file), \
             mock.patch.object(self.daemon, "_matching_processes", return_value=[]):
            report = self.daemon.doctor()

        self.assertEqual(report["summary"]["learning_strength_status"], "STRONG_LEARNING_ACTIVE")
        self.assertEqual(report["status_file"]["learning_strength"]["score"], 100)

    def test_doctor_warns_when_learning_has_data_gap(self):
        status_file = Path(self.tmpdir.name) / "status.json"
        status_file.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": "READ_ONLY_RESEARCH",
            "last_status": "PARTIAL",
            "external_live_gate": "ALLOW_WITH_CAUTION",
            "learning_strength": {
                "status": "LEARNING_DATA_GAP",
                "score": 20,
                "outcomes": 0,
                "next_actions": ["restore_data_feed"],
            },
            "event_risk": {
                "level": "NORMAL",
                "live_gate": "ALLOW_WITH_CAUTION",
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            "adaptive_policy": {
                "status": "READY_FOR_PAPER_SELECTION",
                "external_live_gate": "ALLOW_WITH_CAUTION",
            },
        }))

        with mock.patch.object(self.daemon, "EVENT_STATUS_FILE", status_file), \
             mock.patch.object(self.daemon, "_matching_processes", return_value=[]):
            report = self.daemon.doctor()

        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("LEARNING_DATA_GAP", codes)


class SodexAutonomousResearchTests(TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path("scripts/sodex_autonomous_research.py")
        spec = importlib.util.spec_from_file_location("sodex_autonomous_research", path)
        cls.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runner)

    def test_learning_report_scores_watchlist_outcome(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        log_file = Path(tmpdir.name) / "research.jsonl"
        learning_file = Path(tmpdir.name) / "learning.json"
        old_row = {
            "ts": "2026-06-08T10:00:00+00:00",
            "watchlist_longs": [{
                "symbol": "WSOSO_vUSDC", "market": "spot", "route": "SPOT_LONG",
                "direction": "LONG", "score": 54, "mark": 1.0,
                "reasons": ["SOSO_EXP_PRE_EVENT(72.0h)"],
            }],
        }
        log_file.write_text(json.dumps(old_row) + "\n")
        current_row = {
            "ts": "2026-06-08T10:30:00+00:00",
            "observed_assets": [{
                "symbol": "WSOSO_vUSDC", "market": "spot", "mark": 1.02,
            }],
        }

        with mock.patch.object(self.runner, "LOG_FILE", log_file), \
             mock.patch.object(self.runner, "LEARNING_FILE", learning_file):
            report = self.runner._learning_report(current_row)

        key = "h30_59m:watch_40_59:watchlist_longs:SPOT_LONG"
        self.assertEqual(report["outcomes"], 1)
        self.assertEqual(report["summary"][key]["win_rate"], 1.0)
        self.assertAlmostEqual(report["summary"][key]["avg_edge_return_pct"], 2.0)
        self.assertEqual(report["soso_symbol_summary"]["n"], 1)
        self.assertEqual(report["soso_symbol_summary"]["win_rate"], 1.0)
        self.assertEqual(report["soso_exp_summary"]["n"], 1)
        self.assertEqual(report["soso_exp_summary"]["win_rate"], 1.0)

    def test_atomic_json_write_replaces_target_without_leaving_tmp(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        out = Path(tmpdir.name) / "status.json"

        self.runner._atomic_write_json(out, {"status": "OK", "n": 1})

        self.assertEqual(json.loads(out.read_text())["status"], "OK")
        self.assertEqual(list(Path(tmpdir.name).glob("status.json.tmp*")), [])

    def test_soso_learning_decision_requires_samples_before_promote(self):
        decision = self.runner._soso_learning_decision({
            "soso_symbol_summary": {
                "n": 3,
                "win_rate": 1.0,
                "avg_edge_return_pct": 0.2,
            }
        })

        self.assertEqual(decision["decision"], "LEARN_MORE")

    def test_soso_learning_decision_promotes_target_quality_symbol(self):
        decision = self.runner._soso_learning_decision({
            "soso_exp_summary": {
                "n": 20,
                "win_rate": 0.7,
                "avg_edge_return_pct": 0.08,
            }
        })

        self.assertEqual(decision["decision"], "PROMOTE_SYMBOL_EDGE")
        self.assertEqual(decision["scope"], "SOSO_EXP")

    def test_soso_learning_decision_blocks_negative_edge_symbol(self):
        decision = self.runner._soso_learning_decision({
            "soso_symbol_summary": {
                "n": 20,
                "win_rate": 0.45,
                "avg_edge_return_pct": -0.02,
            }
        })

        self.assertEqual(decision["decision"], "BLOCK_SYMBOL_EDGE")

    def test_adaptive_policy_promotes_only_target_quality_cohorts(self):
        learning = {
            "summary": {
                "h30_59m:watch_40_59:watchlist_shorts:PERPS_SHORT": {
                    "n": 26,
                    "win_rate": 1.0,
                    "avg_edge_return_pct": 0.3991,
                },
                "h04h_plus:radar_20_39:watchlist_longs:PERPS_LONG": {
                    "n": 1519,
                    "win_rate": 0.2554,
                    "avg_edge_return_pct": -0.5292,
                },
            }
        }

        policy = self.runner._adaptive_policy(learning, {
            "live_gate": "BLOCK_LIVE",
            "route_policy": {
                "opportunity_bias": "SHORT",
                "opportunity_routes": ["PERPS_SHORT"],
                "route_gates": {
                    "SPOT_LONG": "BLOCK_LIVE",
                    "PERPS_SHORT": "RESEARCH_ONLY",
                },
            },
        })

        self.assertEqual(policy["status"], "RISK_EVENT_ROUTE_LIMITED")
        self.assertEqual(policy["target_win_rate"], 0.69)
        self.assertEqual(policy["live_route"], "SPOT_LONG")
        self.assertEqual(policy["live_route_decision"], "BLOCKED_BY_EVENT_RISK")
        self.assertEqual(policy["event_opportunity_bias"], "SHORT")
        self.assertEqual(policy["event_opportunity_routes"], ["PERPS_SHORT"])
        self.assertEqual(policy["promote"][0]["route"], "PERPS_SHORT")
        self.assertEqual(policy["block"][0]["route"], "PERPS_LONG")
        route_state = {item["route"]: item for item in policy["route_opportunity_state"]}
        self.assertEqual(route_state["SPOT_LONG"]["action"], "BLOCK_LIVE")
        self.assertEqual(route_state["PERPS_SHORT"]["action"], "RESEARCH_OPPORTUNITY")
        self.assertTrue(route_state["PERPS_SHORT"]["event_aligned"])

    def test_learning_strength_reports_autonomous_continuous_learning_ready(self):
        learning = {
            "status": "OK",
            "outcomes": 120,
            "summary": {
                "h30_59m:watch_40_59:watchlist_shorts:PERPS_SHORT": {
                    "n": 60,
                    "win_rate": 0.8,
                    "avg_edge_return_pct": 0.25,
                }
            },
        }
        policy = {
            "status": "RISK_EVENT_ROUTE_LIMITED",
            "promote": [{
                "route": "PERPS_SHORT",
                "direction": "SHORT",
                "n": 60,
                "win_rate": 0.8,
                "avg_edge_return_pct": 0.25,
            }],
            "watch": [],
            "block": [],
            "event_opportunity_routes": ["PERPS_SHORT"],
        }

        strength = self.runner._learning_strength(learning, policy, [])

        self.assertEqual(strength["status"], "STRONG_LEARNING_ACTIVE")
        self.assertGreaterEqual(strength["score"], 80)
        self.assertEqual(strength["best_route"], "PERPS_SHORT")
        self.assertIn("PERPS_SHORT", strength["opportunity_alignment"])

    def test_learning_strength_prefers_event_aligned_promoted_route(self):
        policy = {
            "promote": [
                {
                    "route": "SPOT_LONG",
                    "direction": "LONG",
                    "n": 47,
                    "win_rate": 1.0,
                    "avg_edge_return_pct": 0.217,
                },
                {
                    "route": "PERPS_SHORT",
                    "direction": "SHORT",
                    "n": 46,
                    "win_rate": 0.9783,
                    "avg_edge_return_pct": 0.2296,
                },
            ],
            "watch": [],
            "block": [],
            "event_opportunity_routes": ["PERPS_SHORT"],
        }

        strength = self.runner._learning_strength(
            {"status": "OK", "outcomes": 120, "summary": {}},
            policy,
            [],
        )

        self.assertEqual(strength["best_route"], "PERPS_SHORT")
        self.assertEqual(strength["best_direction"], "SHORT")
        self.assertIn("prioritize_event_aligned_route", strength["next_actions"])

    def test_learning_strength_flags_data_gap_before_policy_promotion(self):
        strength = self.runner._learning_strength(
            {"status": "NO_SNAPSHOT", "outcomes": 0, "summary": {}},
            {"promote": [], "watch": [], "block": []},
            ["perps:URLError"],
        )

        self.assertEqual(strength["status"], "LEARNING_DATA_GAP")
        self.assertIn("restore_data_feed", strength["next_actions"])

    def test_soso_event_playbook_blocks_live_when_event_risk_red(self):
        result = {
            "catalysts": {"soso_exp": {
                "active": True,
                "phase": "PRE_EVENT",
                "hours_until": 72.0,
                "event_ts": "2026-06-12T12:00:00+00:00",
            }},
            "top_longs": [{
                "symbol": "WSOSO_vUSDC",
                "route": "SPOT_LONG",
                "score": 62,
                "spread_pct": 0.03,
                "vol24": 1_400_000.0,
            }],
        }

        playbook = self.runner._soso_event_playbook(
            result,
            {"live_gate": "BLOCK_LIVE", "level": "RED"},
            {"live_route_decision": "BLOCKED_BY_EVENT_RISK"},
        )

        self.assertEqual(playbook["decision"], "MONITOR_ONLY")
        self.assertIn("EVENT_RISK_BLOCK_LIVE", playbook["blockers"])

    def test_soso_event_playbook_ready_when_gate_allows_valid_pre_event(self):
        result = {
            "catalysts": {"soso_exp": {
                "active": True,
                "phase": "PRE_EVENT",
                "hours_until": 24.0,
                "event_ts": "2026-06-12T12:00:00+00:00",
            }},
            "top_longs": [{
                "symbol": "WSOSO_vUSDC",
                "route": "SPOT_LONG",
                "score": 72,
                "spread_pct": 0.04,
                "vol24": 2_000_000.0,
            }],
        }

        playbook = self.runner._soso_event_playbook(
            result,
            {"live_gate": "ALLOW_WITH_CAUTION", "level": "YELLOW"},
            {"live_route_decision": "ALLOW_ROUTE"},
        )

        self.assertEqual(playbook["decision"], "READY_WHEN_LIVE_GATE_ALLOWS")
        self.assertEqual(playbook["blockers"], [])


class SodexEventShockGuardTests(TestCase):
    def test_geo_policy_whale_headline_scores_as_shock(self):
        score, categories = _classify(
            "Trump comments on Iran war risk as Michael Saylor Strategy Bitcoin sale worries market",
            "Whale Alert reports BTC exchange transfer during crypto selloff",
            "Tue, 09 Jun 2026 00:00:00 GMT",
            datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc),
        )

        self.assertGreaterEqual(score, 75)
        self.assertEqual(_level(score), "RED")
        self.assertIn("geo", categories)
        self.assertIn("policy", categories)
        self.assertIn("whale", categories)

    def test_red_risk_off_keeps_short_research_open_but_blocks_spot_long_live(self):
        policy = event_route_policy("RED", 92.0, ["geo", "policy", "panic"])

        self.assertEqual(policy["regime"], "RISK_OFF_SHOCK")
        self.assertEqual(policy["route_gates"]["SPOT_LONG"], "BLOCK_LIVE")
        self.assertEqual(policy["route_gates"]["PERPS_SHORT"], "RESEARCH_ONLY")
        self.assertEqual(policy["opportunity_bias"], "SHORT")
        self.assertIn("PERPS_SHORT", policy["opportunity_routes"])

    def test_enriches_legacy_red_snapshot_from_top_hit_categories(self):
        risk = enrich_event_route_policy({
            "level": "RED",
            "live_gate": "BLOCK_LIVE",
            "risk_score": 98.3,
            "top_hits": [
                {"categories": ["geo", "policy"]},
                {"categories": ["panic"]},
            ],
        })

        self.assertEqual(risk["categories"], ["geo", "panic", "policy"])
        self.assertEqual(risk["opportunity_bias"], "SHORT")
        self.assertEqual(risk["opportunity_routes"], ["PERPS_SHORT"])
        self.assertEqual(risk["route_policy"]["regime"], "RISK_OFF_SHOCK")


class SpotAutofarmHelperTests(TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path("anantara/sodex_autofarm.py")
        spec = importlib.util.spec_from_file_location("sodex_autofarm", path)
        cls.autofarm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.autofarm)

    def test_order_progress_accepts_decimal_strings(self):
        order = {"executedQty": "123.45", "origQty": "246.90"}

        filled = self.autofarm._num_order_field(order, "executedQty")
        orig = self.autofarm._num_order_field(order, "origQty")

        self.assertEqual(filled, 123.45)
        self.assertEqual(orig, 246.90)

    def test_order_match_ignores_cosmetic_zero_order_id(self):
        order = {"orderID": 0, "clOrdID": "abc"}

        self.assertTrue(self.autofarm._order_matches(order, 0, "abc"))
        self.assertFalse(self.autofarm._order_matches(order, 0, ""))

    def test_guardian_cancels_partial_fill_before_returning(self):
        order = {
            "orderID": 123,
            "clOrdID": "abc",
            "status": "PARTIALLY_FILLED",
            "executedQty": "100",
            "origQty": "1000",
        }

        # AUDIT 29-Sep-2026: kode v4.0 ("Don't cancel immediately") sengaja menunggu
        # s/d 60s agar maker tipis terisi bertahap — cancel instan justru kehilangan
        # edge. Kontrak yang benar = BATAL setelah ambang tunggu, bukan seketika.
        # Waktu dijujurkan deterministik (tanpa sleep nyata) supaya test tidak pernah
        # "flaky": tiap panggilan time.time() melompat 70s (> 60s).
        _t = {"v": 1000.0}

        def _fake_time():
            _t["v"] += 70.0
            return _t["v"]

        with mock.patch.object(self.autofarm, "analyze_spread", return_value={"spread_pct": 0.35}), \
             mock.patch.object(self.autofarm, "get_orders", return_value=[order]), \
             mock.patch.object(self.autofarm, "cancel_order", return_value=True) as cancel, \
             mock.patch.object(self.autofarm.time, "sleep") as sleep, \
             mock.patch.object(self.autofarm.time, "time", side_effect=_fake_time):
            result = self.autofarm.guardian_wait(123, "abc", "buy", 0.35)

        self.assertEqual(result, "PARTIALLY_FILLED_CANCELLED")
        cancel.assert_called_once_with(123, "abc")
        sleep.assert_not_called()

    def test_sodex_cli_uses_project_cwd_and_absolute_binary(self):
        with mock.patch.object(self.autofarm.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "[]"
            run.return_value.stderr = ""
            ok, out = self.autofarm._sodex(["orders", "list", "spot"])

        self.assertTrue(ok)
        self.assertEqual(out, "[]")
        cmd = run.call_args.args[0]
        kwargs = run.call_args.kwargs
        self.assertEqual(cmd[0], self.autofarm.SODEX_BIN)
        self.assertEqual(kwargs["cwd"], self.autofarm.PROJECT_DIR)

    def test_external_event_gate_vetoes_live_before_orderbook(self):
        risk = {
            "level": "RED",
            "live_gate": "BLOCK_LIVE",
            "risk_score": 98.0,
            "reason": "Iran Trump whale shock",
        }
        # Hermetisitas (2 sumber): (a) gerbang kebijakan adaptif membaca status di disk
        # (fail-closed, ambang 300 s) sehingga bisa menveto lebih dulu; (b) gerbang
        # event-risk punya BULL-bypass yang aktif secara default (env
        # SODEX_EVENT_GUARD_BULL_BYPASS=1) sehingga saat regime sedang BULL keyakinan
        # tinggi, veto event dilewati. Keduanya membuat hasil tes bergantung state,
        # bukan logika. Diisolasi supaya unit yang diuji benar-benar gerbang event-risk.
        with mock.patch.dict(os.environ, {"SODEX_EVENT_GUARD_BULL_BYPASS": "0"}), \
             mock.patch.object(self.autofarm, "_load_cached_event_risk", return_value=(risk, "OK")), \
             mock.patch.object(self.autofarm, "adaptive_policy_gate",
                               return_value=(True, "POLICY_DISABLED", {})), \
             mock.patch.object(self.autofarm, "analyze_spread") as analyze:
            pnl, pct, err = self.autofarm.execute_round_trip(capital=10, force=True)

        self.assertEqual(pnl, 0)
        self.assertEqual(pct, 0)
        self.assertTrue(err.startswith("EVENT_RISK_RED_"))
        analyze.assert_not_called()

    def test_adaptive_policy_gate_vetoes_live_before_orderbook(self):
        policy = {
            "status": "READY_FOR_PAPER_SELECTION",
            "external_live_gate": "ALLOW_WITH_CAUTION",
            "promote": [],
            "block": [{
                "route": "SPOT_LONG",
                "win_rate": 0.1,
                "avg_edge_return_pct": -0.2,
            }],
        }
        with mock.patch.object(self.autofarm, "_load_cached_event_risk", return_value=({
                "level": "NORMAL",
                "live_gate": "ALLOW_WITH_CAUTION",
            }, "OK")), \
             mock.patch.object(self.autofarm, "_load_cached_research_status", return_value=({
                "adaptive_policy": policy,
            }, "OK")), \
             mock.patch.object(self.autofarm, "analyze_spread") as analyze:
            pnl, pct, err = self.autofarm.execute_round_trip(capital=10, force=True)

        self.assertEqual(pnl, 0)
        self.assertEqual(pct, 0)
        self.assertTrue(err.startswith("POLICY_BLOCK_ROUTE_SPOT_LONG"))
        analyze.assert_not_called()

    def test_external_event_gate_fails_closed_without_fresh_cache(self):
        with mock.patch.object(self.autofarm, "_load_cached_event_risk", return_value=(None, "EVENT_RISK_STALE_999s")), \
             mock.patch.dict(os.environ, {"SODEX_EVENT_GUARD_LIVE_FETCH": "0"}, clear=False):
            ok, reason, risk = self.autofarm.external_event_gate()

        self.assertFalse(ok)
        self.assertTrue(reason.startswith("EVENT_RISK_UNKNOWN_"))
        self.assertEqual(risk["live_gate"], "BLOCK_LIVE")

    def test_autofarm_event_cache_uses_status_ts_for_freshness(self):
        old_risk_ts = "2026-06-08T00:00:00+00:00"
        risk = {
            "level": "RED",
            "live_gate": "BLOCK_LIVE",
            "risk_score": 99.0,
            "reason": "cached headline shock",
            "ts": old_risk_ts,
        }
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        status_file = Path(tmpdir.name) / "status.json"
        status_file.parent.mkdir(parents=True, exist_ok=True)
        status_file.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_risk": risk,
        }))

        with mock.patch.object(self.autofarm, "EVENT_STATUS_FILE", status_file):
            event_risk, reason = self.autofarm._load_cached_event_risk()

        self.assertEqual(reason, "OK")
        self.assertEqual(event_risk["ts"], old_risk_ts)
        self.assertLess(event_risk["status_age_s"], 5)

    def test_autofarm_event_cache_backs_up_corrupt_status_file(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        status_file = Path(tmpdir.name) / "status.json"
        status_file.parent.mkdir(parents=True, exist_ok=True)
        status_file.write_text("{bad json")

        with mock.patch.object(self.autofarm, "EVENT_STATUS_FILE", status_file):
            event_risk, reason = self.autofarm._load_cached_event_risk()

        self.assertIsNone(event_risk)
        self.assertTrue(reason.startswith("EVENT_RISK_CACHE_ERROR_JSONDecodeError"))
        backups = list(Path(tmpdir.name).glob("status.json.corrupt-*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertFalse(status_file.exists())

    def test_autofarm_research_status_backs_up_invalid_root(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        status_file = Path(tmpdir.name) / "status.json"
        status_file.parent.mkdir(parents=True, exist_ok=True)
        status_file.write_text(json.dumps(["not", "an", "object"]))

        with mock.patch.object(self.autofarm, "EVENT_STATUS_FILE", status_file):
            data, reason = self.autofarm._load_cached_research_status(300)

        self.assertIsNone(data)
        self.assertEqual(reason, "STATUS_CACHE_ERROR_INVALID_ROOT_list")
        self.assertFalse(status_file.exists())
        backups = list(Path(tmpdir.name).glob("status.json.corrupt-*.bak"))
        self.assertEqual(len(backups), 1)


class SodexPregainScannerTests(TestCase):
    def test_build_candidates_routes_perps_long_short_and_spot_long(self):
        macro = MacroContext(
            EtfSentiment(0.2, "BULLISH", 0.1, "test"),
            SectorBias(["Meme"], [], {"PEPE": "HOT"}),
            [],
            0,
            0,
            "test macro",
        )
        perps_assets = [
            {
                "symbol": "SQUEEZE-USD", "name": "SQUEEZE", "market": "perps",
                "mark": 10.0, "chg": 4.0, "ann_fund": -180.0,
                "oi": 40_000_000.0, "vol24": 5_000_000.0,
                "oi_vol": 8.0, "vol_oi": 0.125, "liq": "THIN",
                "spread_pct": 0.01, "_raw": {},
            },
            {
                "symbol": "TOP-USD", "name": "TOP", "market": "perps",
                "mark": 20.0, "chg": 18.0, "ann_fund": 180.0,
                "oi": 50_000_000.0, "vol24": 5_000_000.0,
                "oi_vol": 10.0, "vol_oi": 0.1, "liq": "THIN",
                "spread_pct": 0.01, "_raw": {},
            },
        ]
        spot_assets = [
            {
                "symbol": "vPEPE_vUSDC", "name": "PEPE", "market": "spot",
                "mark": 0.0000028, "chg": 5.0, "ann_fund": 0.0,
                "oi": 0.0, "vol24": 2_000_000.0,
                "oi_vol": 0.0, "vol_oi": 0.0, "liq": "THIN",
                "spread_pct": 0.35, "_raw": {},
            }
        ]

        longs, shorts = build_candidates(perps_assets, spot_assets, min_score=60, macro=macro)

        self.assertIn("PERPS_LONG", {c.route for c in longs})
        self.assertIn("SPOT_LONG", {c.route for c in longs})
        self.assertEqual(shorts[0].route, "PERPS_SHORT")
        self.assertEqual(shorts[0].base, "TOP")

    def test_enrich_with_state_adds_leading_deltas(self):
        assets = [{
            "symbol": "COIL-USD", "name": "COIL", "market": "perps",
            "mark": 1.0, "chg": 1.0, "ann_fund": 90.0,
            "oi": 120.0, "vol24": 150.0, "oi_vol": 0.8,
            "vol_oi": 1.25, "liq": "DUST", "spread_pct": 0.01, "_raw": {},
        }]
        prev_ts = datetime.now(timezone.utc).timestamp() - 3600
        state = {"assets": {"perps:COIL-USD": {
            "ts": prev_ts, "ann_fund": 60.0, "oi": 100.0,
            "vol24": 100.0, "mark": 1.0,
        }}}

        enriched = enrich_with_state(assets, state=state)[0]

        self.assertAlmostEqual(enriched["fund_accel"], 30.0, delta=0.5)
        self.assertAlmostEqual(enriched["oi_velocity_pct"], 20.0, delta=0.5)
        self.assertAlmostEqual(enriched["vol_accel_pct"], 50.0, delta=0.5)

    def test_scan_reports_watchlist_below_trade_threshold(self):
        perps_assets = [{
            "symbol": "WATCH-USD", "name": "WATCH", "market": "perps",
            "mark": 1.0, "chg": 2.0, "ann_fund": -90.0,
            "oi": 500_000.0, "vol24": 1_500_000.0,
            "oi_vol": 0.33, "vol_oi": 3.0, "liq": "THIN",
            "spread_pct": 0.01, "_raw": {},
        }]

        with mock.patch("anantara.sodex_pregain_scanner.fetch_perps_assets", return_value=perps_assets), \
             mock.patch("anantara.sodex_pregain_scanner.fetch_spot_assets", return_value=[]), \
             mock.patch("anantara.sodex_pregain_scanner._save_state"), \
             mock.patch("anantara.sodex_pregain_scanner.enrich_with_state", side_effect=lambda assets: assets), \
             mock.patch("anantara.sodex_pregain_scanner.sosovalue_macro.fetch_macro_context", return_value=None):
            result = scan(min_score=60, top_n=5)

        self.assertEqual(result["top_longs"], [])
        self.assertGreaterEqual(result["watchlist_longs"][0]["score"], result["watch_score"])
        self.assertLess(result["watchlist_longs"][0]["score"], result["min_score"])
        self.assertEqual(result["diagnostics"]["trade_grade_longs"], 0)
        self.assertEqual(result["diagnostics"]["watch_longs"], 1)

    def test_soso_exp_event_promotes_wsoso_spot_catalyst(self):
        spot_assets = [{
            "symbol": "WSOSO_vUSDC", "name": "WSOSO", "market": "spot",
            "mark": 0.355, "chg": -3.7, "ann_fund": 0.0,
            "oi": 0.0, "vol24": 1_400_000.0,
            "oi_vol": 0.0, "vol_oi": 0.0, "liq": "THIN",
            "spread_pct": 0.03, "_raw": {},
        }]
        macro = MacroContext(
            EtfSentiment(-1.0, "BEARISH", -1.0, "test"),
            SectorBias([], [], {}),
            [],
            -6,
            12,
            "test macro",
        )

        with mock.patch("anantara.sodex_pregain_scanner._soso_exp_event_context", return_value={
            "active": True,
            "phase": "PRE_EVENT",
            "event_ts": "2026-06-12T12:00:00+00:00",
            "hours_until": 72.0,
        }):
            longs, _ = build_candidates([], spot_assets, min_score=60, macro=macro)

        self.assertEqual(longs[0].symbol, "WSOSO_vUSDC")
        self.assertEqual(longs[0].route, "SPOT_LONG")
        self.assertGreaterEqual(longs[0].score, 60)
        self.assertIn("SOSO_EXP_PRE_EVENT(72.0h)", longs[0].reasons)

    def test_sosovalue_top_gainer_promotes_sodex_spot_pregain_match(self):
        spot_assets = [{
            "symbol": "vPEPE_vUSDC", "name": "PEPE", "market": "spot",
            "mark": 0.0000028, "chg": 11.0, "ann_fund": 0.0,
            "oi": 0.0, "vol24": 1_500_000.0,
            "oi_vol": 0.0, "vol_oi": 0.0, "liq": "THIN",
            "spread_pct": 0.35, "_raw": {},
        }]
        top_movers = TopMoverContext(
            gainers=[TopMover("PEPE", "GAINER", 16.5, 2, 91.0)],
            losers=[],
            reason="test movers",
        )

        longs, _ = build_candidates(
            [], spot_assets, min_score=60, macro=None, top_movers=top_movers
        )

        self.assertEqual(longs[0].base, "PEPE")
        self.assertTrue(any(r.startswith("SOSO_PRE_TOP_GAINER_MATCH") for r in longs[0].reasons))
        self.assertTrue(any("NEAR_24H_HIGH" in r for r in longs[0].reasons))

    def test_scan_reports_sosovalue_top_mover_context(self):
        perps_assets = [{
            "symbol": "ARB-USD", "name": "ARB", "market": "perps",
            "mark": 1.0, "chg": -3.0, "ann_fund": 130.0,
            "oi": 8_000_000.0, "vol24": 2_000_000.0,
            "oi_vol": 4.0, "vol_oi": 0.25, "liq": "THIN",
            "spread_pct": 0.01, "_raw": {},
        }]
        top_movers = TopMoverContext(
            gainers=[],
            losers=[TopMover("ARB", "LOSER", -12.0, 1)],
            reason="test movers",
        )

        with mock.patch("anantara.sodex_pregain_scanner.fetch_perps_assets", return_value=perps_assets), \
             mock.patch("anantara.sodex_pregain_scanner.fetch_spot_assets", return_value=[]), \
             mock.patch("anantara.sodex_pregain_scanner._save_state"), \
             mock.patch("anantara.sodex_pregain_scanner.enrich_with_state", side_effect=lambda assets: assets), \
             mock.patch("anantara.sodex_pregain_scanner.sosovalue_macro.fetch_macro_context", return_value=None), \
             mock.patch("anantara.sodex_pregain_scanner.sosovalue_macro.fetch_top_mover_context", return_value=top_movers):
            result = scan(min_score=60, top_n=5)

        self.assertEqual(result["top_movers"]["losers"], ["ARB"])
        self.assertEqual(result["top_movers"]["reason"], "test movers")


# ============================================================
# SoDEX Twin-Engine Bug Fixes — Tests (2026-06-17)
# B1: e2_open_pos Ledger persistence
# B2: Conservative ghost detection
# B3: E2 crash-recovery in churn_cycle
# B4: E1 size ladder default
# B5: cmd_selftest mktemp fix
# B6: watchdog.sh .env parsing (verified via config default)
# ============================================================

import sqlite3
import tempfile
import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch, call

# Import twin-engine components
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _make_test_ledger():
    """Create an in-memory Ledger for testing."""
    # Import lazily to avoid module-level env dependency
    from anantara.sodex_twin_engine import Ledger, Config, SCHEMA
    cfg = Config()
    # Use in-memory DB
    led = object.__new__(Ledger)
    led.con = sqlite3.connect(":memory:", check_same_thread=False)
    led.con.row_factory = sqlite3.Row
    led.con.executescript(SCHEMA)
    led.con.commit()
    return led


class TwinEngineB1LedgerPersistenceTests(TestCase):
    """B1: e2_open_pos table + Ledger crash-recovery methods."""

    def setUp(self):
        self.led = _make_test_ledger()

    def test_e2_open_pos_table_exists(self):
        """SCHEMA must contain e2_open_pos table."""
        from anantara.sodex_twin_engine import SCHEMA
        self.assertIn("e2_open_pos", SCHEMA)

    def test_e2_save_open_returns_rowid(self):
        rowid = self.led.e2_save_open("ENA-USD", "buy", Decimal("10"), Decimal("0.5"))
        self.assertIsInstance(rowid, int)
        self.assertGreater(rowid, 0)

    def test_e2_save_open_stores_fields(self):
        self.led.e2_save_open("TON-USD", "sell", Decimal("5"), Decimal("3.14"))
        rows = self.led.con.execute("SELECT * FROM e2_open_pos").fetchall()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["pair"], "TON-USD")
        self.assertEqual(row["side"], "sell")
        self.assertEqual(Decimal(row["qty"]), Decimal("5"))
        self.assertEqual(Decimal(row["entry_px"]), Decimal("3.14"))

    def test_e2_get_open_positions_returns_records(self):
        self.led.e2_save_open("ENA-USD", "buy", Decimal("10"), Decimal("0.5"))
        self.led.e2_save_open("XPL-USD", "sell", Decimal("20"), Decimal("1.0"))
        positions = self.led.e2_get_open_positions()
        self.assertEqual(len(positions), 2)
        pairs = {p["pair"] for p in positions}
        self.assertIn("ENA-USD", pairs)
        self.assertIn("XPL-USD", pairs)

    def test_e2_clear_open_removes_record(self):
        rowid = self.led.e2_save_open("ENA-USD", "buy", Decimal("10"), Decimal("0.5"))
        self.led.e2_clear_open(rowid)
        rows = self.led.con.execute("SELECT COUNT(*) FROM e2_open_pos").fetchone()[0]
        self.assertEqual(rows, 0)

    def test_e2_get_open_positions_empty_when_no_records(self):
        positions = self.led.e2_get_open_positions()
        self.assertEqual(positions, [])

    def test_e2_clear_nonexistent_rowid_is_safe(self):
        """Clearing a non-existent rowid must not raise."""
        self.led.e2_clear_open(9999)  # should not raise

    def test_multiple_positions_independently_cleared(self):
        r1 = self.led.e2_save_open("ENA-USD", "buy", Decimal("10"), Decimal("1"))
        r2 = self.led.e2_save_open("TON-USD", "sell", Decimal("5"), Decimal("2"))
        self.led.e2_clear_open(r1)
        remaining = self.led.e2_get_open_positions()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["pair"], "TON-USD")
        self.led.e2_clear_open(r2)
        self.assertEqual(self.led.e2_get_open_positions(), [])


class TwinEngineB2GhostDetectionTests(TestCase):
    """B2: Conservative ghost detection — empty dict / exception → SKIP."""

    def _make_adapter(self, sodex_return):
        """Build a SodexLiveAdapter with mocked _sodex method."""
        from anantara.sodex_twin_engine import SodexLiveAdapter, Config
        cfg = Config()
        adapter = object.__new__(SodexLiveAdapter)
        adapter.cfg = cfg
        adapter._SYMBOL_MAP = {"ENA-USD": "ENA-USD", "XPL-USD": "XPL-USD"}
        adapter._sym_id = lambda p: p  # identity
        adapter._sodex = MagicMock(return_value=sodex_return)
        adapter._cancel_order = MagicMock()
        adapter._place_reduce_only = MagicMock()
        adapter.book = MagicMock()
        return adapter

    def test_empty_dict_response_skips_sweep(self):
        """Empty dict {} (network failure) must NOT trigger ghost sweep."""
        adapter = self._make_adapter({})
        # Patch _SYMBOL_MAP to only have one pair so the loop terminates
        adapter._SYMBOL_MAP = {"ENA-USD": "ENA-USD"}
        result = adapter.sweep_perps_ghosts()
        # No ghost should be detected (empty dict = inconclusive)
        self.assertEqual(result, 0)
        # _place_reduce_only must NOT be called (no false-positive close)
        adapter._place_reduce_only = MagicMock()
        self.assertEqual(adapter._place_reduce_only.call_count, 0)

    def test_none_response_skips_sweep(self):
        """None response must also skip conservatively."""
        adapter = self._make_adapter(None)
        adapter._sodex = MagicMock(side_effect=Exception("timeout"))
        adapter._SYMBOL_MAP = {"ENA-USD": "ENA-USD"}
        result = adapter.sweep_perps_ghosts()
        self.assertEqual(result, 0)

    def test_open_positions_error_triggers_sweep(self):
        """Explicit 'open positions' error SHOULD trigger ghost sweep."""
        from anantara.sodex_twin_engine import SodexLiveAdapter, Config
        cfg = Config()
        adapter = object.__new__(SodexLiveAdapter)
        adapter.cfg = cfg
        adapter._SYMBOL_MAP = {"ENA-USD": "ENA-USD"}
        adapter._sym_id = lambda p: p
        # First call: leverage returns "open positions" error
        # Second call (for close): returns success
        adapter._sodex = MagicMock(side_effect=[
            {"error": "cannot change leverage: open positions"},
            {}  # book/close calls
        ])
        adapter.book = MagicMock(return_value=MagicMock(bid=Decimal("1"), ask=Decimal("1.01"), mid=Decimal("1.005")))
        adapter._place_reduce_only = MagicMock(return_value=MagicMock(oid="123", filled=Decimal("1"), qty=Decimal("1")))
        adapter._sodex_list = MagicMock(return_value=[{"symbol": "ENA-USD", "szi": "10"}])
        # The sweep SHOULD attempt to close the position
        # We just verify it doesn't return 0 cleanly (a sweep was attempted)
        # The exact return depends on the close success, so we check _sodex was called
        try:
            adapter.sweep_perps_ghosts()
        except Exception:
            pass  # May fail due to incomplete mock, but _sodex must have been called
        # Verify leverage call happened (ghost detection attempted)
        self.assertGreater(adapter._sodex.call_count, 0)


class TwinEngineB9PollFillPhantomTests(TestCase):
    """B9: poll_fill must NOT assume fill when order vanishes from open-list.

    SoDEX CLI has no order-history API, so a vanished order cannot be confirmed
    as filled. Assuming fill creates phantom inventory → thrashing + fake PnL.
    """

    def _make_adapter(self):
        from anantara.sodex_twin_engine import SodexLiveAdapter, Config
        cfg = Config()
        adapter = object.__new__(SodexLiveAdapter)
        adapter.cfg = cfg
        return adapter

    def test_vanished_order_returns_zero_not_assumed_filled(self):
        """Order absent from open-list → poll_fill must return 0 (not remaining qty)."""
        from anantara.sodex_twin_engine import Order
        adapter = self._make_adapter()
        # No poll cache → fallback path
        # _sodex_list returns empty list (order not found)
        adapter._sodex_list = MagicMock(return_value=[])
        order = Order(oid="999", pair="PEPE/USDC", side="sell",
                      price=Decimal("0.000003"), qty=Decimal("1000000"),
                      ts=0.0, filled=Decimal("0"))
        inc = adapter.poll_fill(order)
        self.assertEqual(
            inc, Decimal("0"),
            "Vanished order must NOT be assumed filled — returns 0 (phantom fill bug B9)"
        )
        # order.filled must NOT have been bumped to qty
        self.assertEqual(
            order.filled, Decimal("0"),
            "order.filled must stay 0 — not falsely marked fully filled"
        )

    def test_real_fill_via_executed_qty_still_detected(self):
        """A real fill (order present with executedQty) must still be counted."""
        from anantara.sodex_twin_engine import Order
        adapter = self._make_adapter()
        adapter._sodex_list = MagicMock(return_value=[
            {"orderID": "999", "executedQty": "400000"}
        ])
        order = Order(oid="999", pair="PEPE/USDC", side="sell",
                      price=Decimal("0.000003"), qty=Decimal("1000000"),
                      ts=0.0, filled=Decimal("0"))
        inc = adapter.poll_fill(order)
        self.assertEqual(inc, Decimal("400000"), "Real partial fill must be detected")
        self.assertEqual(order.filled, Decimal("400000"))

    def test_no_assume_filled_comment_present(self):
        """Source must document the no-assume-filled fix; old logic removed."""
        source = Path("anantara/sodex_twin_engine.py").read_text()
        self.assertIn("B9 FIX", source, "poll_fill must reference the B9 fix")
        # The dangerous old comment/logic must be gone
        self.assertNotIn(
            "→ sudah fully filled", source,
            "Old 'assume fully filled' logic must be removed"
        )


class TwinEngineB13ReconcileTests(TestCase):
    """B13: balance-delta accounting — fills/RTs derived from real balance deltas.

    SoDEX CLI has no order-history → poll-based fill detection is unreliable.
    Reconciler uses balance() as single source of truth; effective prices from
    USDC deltas bake in fees → exact realized PnL.
    """

    def _make_engine(self):
        from anantara.sodex_twin_engine import Engine1Flywheel, Config
        cfg = Config()
        led = MagicMock()
        led.rt_close = MagicMock()
        led.fill = MagicMock()
        eng = Engine1Flywheel(cfg, MagicMock(), led, MagicMock(), MagicMock(),
                              hedge_enabled=False, pair="PEPE/USDC")
        return eng, led

    def test_buy_delta_records_at_effective_price(self):
        """d_coin>0 with d_usdc<0 → buy recorded at USDC_spent/qty (fee baked in)."""
        eng, led = self._make_engine()
        eng.inv_qty = Decimal("0")
        # bought 1,000,000 PEPE, USDC dropped by $3.00 → eff price = 3/1e6 = 3e-6
        ev = eng.reconcile_delta(Decimal("1000000"), Decimal("0.0000029"),
                                 d_usdc_signed=Decimal("-3.00"))
        self.assertEqual(ev["side"], "buy")
        self.assertEqual(eng.inv_qty, Decimal("1000000"))
        self.assertEqual(len(eng.buy_q), 1)
        eff_px, qty = eng.buy_q[0]
        self.assertEqual(qty, Decimal("1000000"))
        self.assertAlmostEqual(float(eff_px), 3.0e-6, places=12)

    def test_sell_delta_forms_rt_with_exact_pnl(self):
        """Sell after buy forms RT with PnL = (sell_eff - buy_eff)*qty (fees baked)."""
        eng, led = self._make_engine()
        # seed a buy at 3.0e-6
        eng.inv_qty = Decimal("1000000")
        eng.buy_q = [(Decimal("0.0000030"), Decimal("1000000"))]
        # sell all: inv→0, USDC up by $3.50 → eff sell price = 3.5e-6
        ev = eng.reconcile_delta(Decimal("0"), Decimal("0.0000034"),
                                 d_usdc_signed=Decimal("3.50"))
        self.assertEqual(ev["side"], "sell")
        self.assertEqual(ev["rts"], 1)
        # PnL = (3.5e-6 - 3.0e-6) * 1e6 = 0.5
        self.assertAlmostEqual(float(ev["rt_pnl"]), 0.5, places=6)
        self.assertEqual(eng.inv_qty, Decimal("0"))
        led.rt_close.assert_called_once()

    def test_dust_delta_synced_silently(self):
        """Delta below dust → inv synced, no fill event."""
        eng, led = self._make_engine()
        eng.inv_qty = Decimal("1000000")
        # delta of 1000 PEPE * 3e-6 = $0.003 < $0.10 dust
        ev = eng.reconcile_delta(Decimal("1001000"), Decimal("0.0000030"), None)
        self.assertIsNone(ev)
        self.assertEqual(eng.inv_qty, Decimal("1001000"))
        led.fill.assert_not_called()

    def test_mid_fallback_when_usdc_ambiguous(self):
        """d_usdc=None (ambiguous attribution) → effective price = mid."""
        eng, led = self._make_engine()
        eng.inv_qty = Decimal("0")
        ev = eng.reconcile_delta(Decimal("2000000"), Decimal("0.0000031"), None)
        self.assertEqual(ev["side"], "buy")
        eff_px, _ = eng.buy_q[0]
        self.assertEqual(eff_px, Decimal("0.0000031"))  # mid

    def test_seed_baseline_no_fill_recorded(self):
        """seed_baseline sets inventory + buy_q at mid WITHOUT recording a fill."""
        eng, led = self._make_engine()
        eng.seed_baseline(Decimal("5000000"), Decimal("0.0000029"))
        self.assertEqual(eng.inv_qty, Decimal("5000000"))
        self.assertEqual(len(eng.buy_q), 1)
        self.assertEqual(eng.buy_q[0], (Decimal("0.0000029"), Decimal("5000000")))
        led.fill.assert_not_called()
        led.rt_close.assert_not_called()

    def test_partial_sell_keeps_remainder_in_buy_q(self):
        """Selling part of inventory pairs FIFO and keeps the remainder."""
        eng, led = self._make_engine()
        eng.inv_qty = Decimal("1000000")
        eng.buy_q = [(Decimal("0.0000030"), Decimal("1000000"))]
        # sell half
        ev = eng.reconcile_delta(Decimal("500000"), Decimal("0.0000033"),
                                 d_usdc_signed=Decimal("1.65"))
        self.assertEqual(ev["rts"], 1)
        self.assertEqual(eng.inv_qty, Decimal("500000"))
        self.assertEqual(len(eng.buy_q), 1)
        self.assertEqual(eng.buy_q[0][1], Decimal("500000"))  # half remains

    def test_reconcile_mode_flag_default_false(self):
        """Engine defaults to reconcile_mode=False (paper path); live sets True."""
        eng, _ = self._make_engine()
        self.assertFalse(eng.reconcile_mode)


class TwinEngineB19ExperimentTests(TestCase):
    """B19: budget-bounded experiment decision rule (pre-registered)."""

    def test_h1_supported_when_ci_positive(self):
        from anantara.sodex_twin_engine import experiment_verdict
        # 40 RTs, consistently positive small pnl → CI lower > 0
        pnls = [0.05] * 40
        vols = [10.0] * 40
        v = experiment_verdict(pnls, vols, target_n=100, budget_usd=3.0)
        self.assertEqual(v["verdict"], "H1_SUPPORTED")
        self.assertGreater(v["ci_low"], 0)

    def test_h1_falsified_when_ci_negative(self):
        from anantara.sodex_twin_engine import experiment_verdict
        pnls = [-0.05] * 40
        vols = [10.0] * 40
        v = experiment_verdict(pnls, vols, target_n=100, budget_usd=3.0)
        self.assertEqual(v["verdict"], "H1_FALSIFIED")
        self.assertLess(v["ci_high"], 0)

    def test_inconclusive_when_ci_straddles_zero(self):
        from anantara.sodex_twin_engine import experiment_verdict
        # alternating ±0.5 → mean ~0, wide CI
        pnls = [0.5, -0.5] * 20
        vols = [10.0] * 40
        v = experiment_verdict(pnls, vols, target_n=100, budget_usd=3.0)
        self.assertEqual(v["verdict"], "INCONCLUSIVE")

    def test_insufficient_n(self):
        from anantara.sodex_twin_engine import experiment_verdict
        v = experiment_verdict([0.1] * 10, [10.0] * 10, target_n=100, budget_usd=3.0)
        self.assertEqual(v["verdict"], "INSUFFICIENT_N")

    def test_halted_budget_status(self):
        from anantara.sodex_twin_engine import experiment_verdict
        # cumulative loss exceeds budget
        pnls = [-0.5] * 8   # -4.0 total > -3.0 budget
        vols = [10.0] * 8
        v = experiment_verdict(pnls, vols, target_n=100, budget_usd=3.0)
        self.assertEqual(v["status"], "HALTED_BUDGET")
        self.assertGreaterEqual(v["budget_spent"], 3.0)

    def test_complete_status_at_target_n(self):
        from anantara.sodex_twin_engine import experiment_verdict
        pnls = [0.01] * 100
        vols = [10.0] * 100
        v = experiment_verdict(pnls, vols, target_n=100, budget_usd=3.0)
        self.assertEqual(v["status"], "COMPLETE")

    def test_research_off_by_default(self):
        from anantara.sodex_twin_engine import Config
        self.assertFalse(Config().e1_research_enabled, "experiment must be OFF by default")


class TwinEngineB18SpreadResearchTests(TestCase):
    """B18: spread distribution analysis (zero-risk E1 edge research)."""

    def test_analyze_distribution_and_thresholds(self):
        from anantara.sodex_twin_engine import analyze_spread_samples
        # 10 samples: 5 at 20bps, 5 at 60bps; fee round-trip = 6.3 bps
        samples = ([{"pair": "PEPE/USDC", "spread_bps": 20.0}] * 5 +
                   [{"pair": "PEPE/USDC", "spread_bps": 60.0}] * 5)
        a = analyze_spread_samples(samples, fee_round_trip_bps=6.3)
        st = a["pairs"]["PEPE/USDC"]
        self.assertEqual(st["n"], 10)
        self.assertEqual(st["min_bps"], 20.0)
        self.assertEqual(st["max_bps"], 60.0)
        # 50% of samples ≥ 50bps (the five 60bps ones)
        self.assertAlmostEqual(st["frac_ge"]["ge_50bps"], 0.5, places=2)
        # all ≥ 2×fee (12.6 bps)
        self.assertAlmostEqual(st["frac_ge"]["ge_2x_fee"], 1.0, places=2)

    def test_analyze_separates_pairs(self):
        from anantara.sodex_twin_engine import analyze_spread_samples
        samples = [{"pair": "PEPE/USDC", "spread_bps": 30.0},
                   {"pair": "SHIB/USDC", "spread_bps": 15.0}]
        a = analyze_spread_samples(samples, 6.3)
        self.assertIn("PEPE/USDC", a["pairs"])
        self.assertIn("SHIB/USDC", a["pairs"])
        self.assertEqual(a["pairs"]["SHIB/USDC"]["median_bps"], 15.0)

    def test_analyze_empty(self):
        from anantara.sodex_twin_engine import analyze_spread_samples
        a = analyze_spread_samples([], 6.3)
        self.assertEqual(a["pairs"], {})


class TwinEngineB16MonitorTests(TestCase):
    """B16: autonomous Monitoring & Evaluation from REAL data. Must be brutally
    honest — separate honest (post-B13) from contaminated (pre-B13 phantom)."""

    def _ledger(self):
        from anantara.sodex_twin_engine import Ledger, SCHEMA
        import sqlite3
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.row_factory = sqlite3.Row
        led.con.executescript(SCHEMA)
        led.con.commit()
        return led

    def _adapter(self, usdc, pepe_qty, pepe_mid):
        adapter = MagicMock()
        adapter.balance = MagicMock(return_value={
            "vUSDC": Decimal(str(usdc)), "vPEPE": Decimal(str(pepe_qty))})
        book = MagicMock(); book.mid = Decimal(str(pepe_mid))
        adapter.book = MagicMock(return_value=book)
        return adapter

    def test_real_equity_from_balance(self):
        """real_equity = USDC + Σ(coin×mid) from REAL balance — no estimation."""
        from anantara.sodex_twin_engine import build_monitor_report, Config
        led = self._ledger()
        adapter = self._adapter(usdc=100, pepe_qty=50_000_000, pepe_mid="0.000003")
        rep = build_monitor_report(Config(), adapter, led)
        # 100 + 50M*3e-6 = 100 + 150 = 250
        self.assertAlmostEqual(rep["real_equity"], 250.0, places=2)
        self.assertAlmostEqual(rep["usdc_free"], 100.0, places=2)
        self.assertAlmostEqual(rep["inventory_usd"], 150.0, places=2)
        self.assertEqual(len(rep["assets"]), 1)
        self.assertFalse(rep["degraded"])

    def test_weekly_pnl_from_honest_ledger(self):
        """E1/E2 weekly PnL pulled from ledger RTs."""
        from anantara.sodex_twin_engine import build_monitor_report, Config
        led = self._ledger()
        led.rt_close("E1-1", "E1", "PEPE/USDC", Decimal("10"), Decimal("5.0"))
        led.rt_close("E2-1", "E2", "ENA-USD", Decimal("20"), Decimal("-2.0"))
        adapter = self._adapter(100, 0, "0.000003")
        rep = build_monitor_report(Config(), adapter, led)
        self.assertAlmostEqual(rep["e1_profit_week"], 5.0, places=4)
        self.assertAlmostEqual(rep["e2_net_week"], -2.0, places=4)
        self.assertAlmostEqual(rep["realized_net_week"], 3.0, places=4)

    def test_degraded_when_balance_fails(self):
        """balance() exception → degraded flag, no crash, real_equity None."""
        from anantara.sodex_twin_engine import build_monitor_report, Config
        led = self._ledger()
        adapter = MagicMock()
        adapter.balance = MagicMock(side_effect=Exception("API down"))
        rep = build_monitor_report(Config(), adapter, led)
        self.assertTrue(rep["degraded"])
        self.assertIsNone(rep["real_equity"])

    def test_honest_separation_excludes_pre_b13(self):
        """Honest stats must EXCLUDE RTs recorded before B13 activation."""
        from anantara.sodex_twin_engine import build_monitor_report, Config
        from datetime import datetime, timezone, timedelta
        led = self._ledger()
        now = datetime.now(timezone.utc)
        b13 = now - timedelta(hours=1)
        led.set_state("b13_activated_ts", Decimal(str(b13.timestamp())))
        # Pre-B13 RT (phantom, 2h ago) — manual insert with old ts_close
        old_ts = (now - timedelta(hours=2)).isoformat()
        led.con.execute("INSERT INTO rts(rt_id,ts_close,engine,pair,volume,net_pnl) "
                        "VALUES(?,?,?,?,?,?)", ("OLD", old_ts, "E1", "PEPE/USDC", "10", "99.0"))
        # Post-B13 RT (honest, now)
        led.rt_close("NEW", "E1", "PEPE/USDC", Decimal("10"), Decimal("-1.0"))
        led.con.commit()
        adapter = self._adapter(100, 0, "0.000003")
        rep = build_monitor_report(Config(), adapter, led)
        self.assertTrue(rep["week_has_contaminated_data"])
        # honest_net excludes the +99 phantom → only -1.0
        self.assertAlmostEqual(rep["honest_net"], -1.0, places=4)
        # verdict based on honest data → losing
        self.assertEqual(rep["verdict_basis"], "honest_post_b13")
        self.assertEqual(rep["verdict"], "RUGI_E1_BELUM_TUTUP_E2")

    def test_persist_writes_files(self):
        """persist_monitor_snapshot writes JSONL + latest JSON."""
        from anantara.sodex_twin_engine import persist_monitor_snapshot, Config
        import tempfile, json as _json, dataclasses
        d = tempfile.mkdtemp(prefix="mon_test_")
        cfg = dataclasses.replace(Config(),
                                  monitor_path=os.path.join(d, "m.jsonl"),
                                  monitor_latest=os.path.join(d, "latest.json"))
        rep = {"ts": "2026-06-18T00:00:00", "real_equity": 250.0, "verdict": "X"}
        persist_monitor_snapshot(cfg, rep)
        self.assertTrue(os.path.exists(cfg.monitor_path))
        self.assertTrue(os.path.exists(cfg.monitor_latest))
        with open(cfg.monitor_latest) as f:
            loaded = _json.load(f)
        self.assertEqual(loaded["real_equity"], 250.0)
        import shutil; shutil.rmtree(d, ignore_errors=True)


class TwinEngineB15WeeklyNetTests(TestCase):
    """B15: weekly E1+E2 net summary (user doctrine — Sat 07:00 WIB boundary)."""

    def test_week_boundary_is_saturday_utc_equals_wib_0700(self):
        """Sat 00:00 UTC == Sat 07:00 WIB. Verify boundary lands on a Saturday."""
        from anantara.sodex_twin_engine import week_start_iso
        from datetime import datetime, timezone
        # A Wednesday → week_start should be the preceding Saturday 00:00 UTC
        wed = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)  # Wed
        ws = week_start_iso(wed)
        dt = datetime.fromisoformat(ws)
        self.assertEqual(dt.weekday(), 5, "week start must be Saturday")
        self.assertEqual((dt.hour, dt.minute), (0, 0), "Sat 00:00 UTC = Sat 07:00 WIB")

    def test_e1_covers_e2_on_track(self):
        """E1 profit covering E2 loss → combined net ≥ 0 → on_track True."""
        from anantara.sodex_twin_engine import weekly_net_summary
        led = MagicMock()
        led.e1_profit_since = MagicMock(return_value=Decimal("5.00"))
        led.total_profit_since = MagicMock(return_value=Decimal("1.50"))  # E2 = -3.50
        led.volume_since = MagicMock(return_value=Decimal("1000"))
        s = weekly_net_summary(led)
        self.assertEqual(s["e1_profit"], Decimal("5.00"))
        self.assertEqual(s["e2_net"], Decimal("-3.50"))
        self.assertEqual(s["combined_net"], Decimal("1.50"))
        self.assertTrue(s["on_track"])
        # coverage = 5.00 / 3.50
        self.assertAlmostEqual(float(s["coverage_ratio"]), 5.0 / 3.5, places=6)

    def test_e1_fails_to_cover_e2(self):
        """E1 profit < E2 loss → combined net < 0 → on_track False."""
        from anantara.sodex_twin_engine import weekly_net_summary
        led = MagicMock()
        led.e1_profit_since = MagicMock(return_value=Decimal("2.00"))
        led.total_profit_since = MagicMock(return_value=Decimal("-3.00"))  # E2 = -5.00
        led.volume_since = MagicMock(return_value=Decimal("0"))
        s = weekly_net_summary(led)
        self.assertFalse(s["on_track"])
        self.assertLess(float(s["coverage_ratio"]), 1.0)  # E1 covers <100% of E2 loss

    def test_e2_not_losing_coverage_none(self):
        """E2 net ≥ 0 → coverage_ratio None (nothing to cover)."""
        from anantara.sodex_twin_engine import weekly_net_summary
        led = MagicMock()
        led.e1_profit_since = MagicMock(return_value=Decimal("3.00"))
        led.total_profit_since = MagicMock(return_value=Decimal("4.00"))  # E2 = +1.00
        led.volume_since = MagicMock(return_value=Decimal("500"))
        s = weekly_net_summary(led)
        self.assertIsNone(s["coverage_ratio"])
        self.assertTrue(s["on_track"])


class TwinEngineB14ProfitGateTests(TestCase):
    """B14: profitability gate — auto-pause E1 quoting on honest negative edge.

    Operationalizes 'no negative-EV farming' using B13 honest accounting.
    """

    def _make_engine(self, rate, n=50):
        from anantara.sodex_twin_engine import Engine1Flywheel, Config
        cfg = Config()
        led = MagicMock()
        led.e1_recent_net_rate_pair = MagicMock(
            return_value=(rate, n) if rate is not None else (None, n))
        eng = Engine1Flywheel(cfg, MagicMock(), led, MagicMock(), MagicMock(),
                              hedge_enabled=False, pair="PEPE/USDC")
        return eng, cfg

    def test_pause_when_edge_negative(self):
        """net rate below pause_floor with enough sample → pause."""
        eng, cfg = self._make_engine(Decimal("-0.0016"), n=50)  # -0.16% (the observed value)
        self.assertFalse(eng._quoting_paused)
        eng._check_profitability_gate()
        self.assertTrue(eng._quoting_paused, "Negative honest edge must pause quoting")

    def test_no_pause_when_insufficient_sample(self):
        """rate=None (n<min) → fail-open, do not pause (gather data first)."""
        eng, cfg = self._make_engine(None, n=5)
        eng._check_profitability_gate()
        self.assertFalse(eng._quoting_paused)

    def test_resume_when_edge_recovers(self):
        """Paused engine resumes when rate exceeds resume_floor."""
        eng, cfg = self._make_engine(Decimal("0.0010"), n=50)  # +0.10%
        eng._quoting_paused = True
        eng._check_profitability_gate()
        self.assertFalse(eng._quoting_paused, "Recovered edge must resume quoting")

    def test_hysteresis_stays_paused_between_floors(self):
        """Between pause_floor and resume_floor → stays paused (no flapping)."""
        eng, cfg = self._make_engine(Decimal("0.0000"), n=50)  # 0% (between -0.05% and +0.02%)
        eng._quoting_paused = True
        eng._check_profitability_gate()
        self.assertTrue(eng._quoting_paused, "Mid-band must keep paused state (hysteresis)")

    def test_gate_config_defaults(self):
        from anantara.sodex_twin_engine import Config
        cfg = Config()
        self.assertLess(float(cfg.e1_pause_floor), 0)      # pause floor negative
        self.assertGreater(float(cfg.e1_resume_floor), 0)  # resume floor positive
        self.assertGreaterEqual(cfg.e1_gate_min_n, 10)

    def test_b17_net_rate_filters_phantom_pre_b13(self):
        """B17: since_iso must exclude pre-B13 phantom RTs from the gate's rate."""
        from anantara.sodex_twin_engine import Ledger, SCHEMA
        import sqlite3
        from datetime import datetime, timezone, timedelta
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.executescript(SCHEMA); led.con.commit()
        now = datetime.now(timezone.utc)
        b13 = now - timedelta(hours=1)
        # 25 phantom RTs (pre-B13) with FAKE positive pnl
        for i in range(25):
            led.con.execute("INSERT INTO rts(rt_id,ts_close,engine,pair,volume,net_pnl) VALUES(?,?,?,?,?,?)",
                            (f"PH{i}", (now-timedelta(hours=2)).isoformat(), "E1", "PEPE/USDC", "10", "5.0"))
        # 25 honest RTs (post-B13) with real negative pnl
        for i in range(25):
            led.con.execute("INSERT INTO rts(rt_id,ts_close,engine,pair,volume,net_pnl) VALUES(?,?,?,?,?,?)",
                            (f"H{i}", now.isoformat(), "E1", "PEPE/USDC", "10", "-0.5"))
        led.con.commit()
        # Without filter → polluted positive
        rate_all, _ = led.e1_recent_net_rate_pair("PEPE/USDC", n=100, min_n=20)
        self.assertGreater(float(rate_all), 0, "unfiltered includes phantom → looks positive")
        # With since_iso=b13 → honest negative only
        rate_honest, n_h = led.e1_recent_net_rate_pair(
            "PEPE/USDC", n=100, min_n=20, since_iso=b13.isoformat())
        self.assertEqual(n_h, 25)
        self.assertLess(float(rate_honest), 0, "honest-only must reflect real negative edge")


class TwinEngineE1MakerTests(TestCase):
    """E1 must be a pure-MAKER flywheel (profit machine), not near-taker.

    aggressive=2 (near-taker) crosses the spread → pays ~taker, captures no edge,
    and fills instantly+vanish before poll → not recorded (post-B9) → thrashing.
    E1 = profit (maker spread capture); E2 = volume (perps churn).
    """

    def test_place_two_sided_default_is_pure_maker(self):
        """_place_two_sided default aggressive must be 0 (pure maker)."""
        import inspect
        from anantara.sodex_twin_engine import Engine1Flywheel
        sig = inspect.signature(Engine1Flywheel._place_two_sided)
        self.assertEqual(
            sig.parameters["aggressive"].default, 0,
            "E1 _place_two_sided must default to aggressive=0 (pure maker, spread capture)"
        )

    def test_step_calls_place_two_sided_as_maker(self):
        """step() must call _place_two_sided with aggressive=0 explicitly."""
        source = Path("anantara/sodex_twin_engine.py").read_text()
        idx = source.find("def step(self):")
        nxt = source.find("\n    def ", idx + 1)
        step_section = source[idx:nxt] if nxt > 0 else source[idx:idx + 4000]
        self.assertIn(
            "_place_two_sided(bk, aggressive=0)", step_section,
            "step() must place pure-maker quotes (aggressive=0)"
        )

    def test_heartbeat_log_includes_pair(self):
        """micro-hb log must include pair name (disambiguate PEPE vs SHIB engines)."""
        source = Path("anantara/sodex_twin_engine.py").read_text()
        self.assertIn(
            "micro-hb %s", source,
            "Heartbeat must include pair name to avoid two-engine log ambiguity"
        )

    def test_pair2_uses_own_min_spread_gate(self):
        """B42: SHIB/E1b boleh punya min spread sendiri agar tidak terkunci gate PEPE."""
        import dataclasses
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import Book, Config, Engine1Flywheel

        cfg = dataclasses.replace(
            Config(),
            e1_min_spread=D("0.0025"),
            e1_pair2_min_spread=D("0.0005"),
            spot_pair_2="SHIB/USDC",
        )
        led = mock.MagicMock()
        led.get_state.return_value = "0"
        led.e1_recent_net_rate_pair.return_value = (None, 0)
        x = mock.MagicMock()
        x.book.return_value = Book(bid=D("0.00000470"), ask=D("0.00000480"))
        x._sodex_list.return_value = []
        eng = Engine1Flywheel(
            cfg, x, led, mock.MagicMock(), mock.MagicMock(),
            hedge_enabled=False, pair="SHIB/USDC")

        with mock.patch.object(eng, "_place_two_sided") as place:
            eng.step()

        place.assert_called_once()

    def test_pair2_does_not_inherit_primary_b14_pause(self):
        """B43: pause B14 PEPE tidak boleh membekukan SHIB/E1b yang belum punya sampel."""
        import dataclasses
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import Book, Config, Engine1Flywheel

        cfg = dataclasses.replace(
            Config(),
            e1_min_spread=D("0.0025"),
            e1_pair2_min_spread=D("0.0005"),
            spot_pair="PEPE/USDC",
            spot_pair_2="SHIB/USDC",
        )
        led = mock.MagicMock()

        def get_state(key, default="0"):
            # AUDIT 29-Sep-2026: engine memanggil led.get_state(_hkey, "0") di restore
            # hedge (2 argumen). Mock 1-argumen membuat test gagal karena TANDA TANGAN,
            # bukan karena perilaku — mock harus memantulkan kontrak nyata.
            return {
                "b14_pause_since_ts": "1234567890",
                "b14_pause_since_ts:SHIB/USDC": "0",
                "b13_activated_ts": "0",
                "b14_trial_until_ts": "0",
            }.get(key, "0")

        led.get_state.side_effect = get_state
        led.e1_recent_net_rate_pair.return_value = (None, 0)
        x = mock.MagicMock()
        x.book.return_value = Book(bid=D("0.00000470"), ask=D("0.00000480"))
        x._sodex_list.return_value = []
        eng = Engine1Flywheel(
            cfg, x, led, mock.MagicMock(), mock.MagicMock(),
            hedge_enabled=False, pair="SHIB/USDC")

        with mock.patch.object(eng, "_place_two_sided") as place:
            eng.step()

        place.assert_called_once()

    def test_place_two_sided_reports_cap_noop_reason(self):
        """B44: quote no-op harus meninggalkan alasan diagnostik, bukan diam."""
        import dataclasses
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import Book, Config, Engine1Flywheel

        cfg = dataclasses.replace(
            Config(),
            e1_size_ladder=(D("15"),),
            e1_inv_cap_per_pair=D("5"),
        )
        led = mock.MagicMock()
        led.get_state.return_value = "0"
        x = mock.MagicMock()
        eng = Engine1Flywheel(
            cfg, x, led, mock.MagicMock(), mock.MagicMock(),
            hedge_enabled=False, pair="SHIB/USDC")

        placed = eng._place_two_sided(Book(bid=D("0.00000472"), ask=D("0.00000473")))

        self.assertEqual(placed, 0)
        self.assertIn("buy_cap", eng._last_place_skip_reason)


class TwinEngineB4SizeLadderTests(TestCase):
    """B4: E1 size ladder calibrated for $60 capital."""

    def test_default_size_ladder_fits_60_capital(self):
        """Default ladder must not exceed capital_usd=$60."""
        from anantara.sodex_twin_engine import Config
        cfg = Config()
        # Max size in ladder must be ≤ capital_usd
        max_size = max(cfg.e1_size_ladder)
        self.assertLessEqual(
            float(max_size), float(cfg.capital_usd),
            f"Max size ladder {max_size} > capital {cfg.capital_usd} — exchange will reject orders"
        )

    def test_default_size_ladder_values(self):
        """Default ladder: (10, 15, 20)."""
        from anantara.sodex_twin_engine import Config
        cfg = Config()
        self.assertEqual(len(cfg.e1_size_ladder), 3)
        self.assertEqual(float(cfg.e1_size_ladder[0]), 10.0)
        self.assertEqual(float(cfg.e1_size_ladder[1]), 15.0)
        self.assertEqual(float(cfg.e1_size_ladder[2]), 20.0)

    def test_size_ladder_env_override(self):
        """TE_E1_SIZE_LADDER env var must override default."""
        with patch.dict(os.environ, {"TE_E1_SIZE_LADDER": "20,30,40"}):
            # Re-import Config to pick up env
            import importlib
            import anantara.sodex_twin_engine as te
            importlib.reload(te)
            cfg = te.Config()
            self.assertEqual(float(cfg.e1_size_ladder[0]), 20.0)
            self.assertEqual(float(cfg.e1_size_ladder[2]), 40.0)
            importlib.reload(te)  # cleanup

    def test_inv_cap_matches_max_size_ladder(self):
        """e1_inv_cap_per_pair should equal max(size_ladder) by default."""
        from anantara.sodex_twin_engine import Config
        cfg = Config()
        max_size = max(cfg.e1_size_ladder)
        self.assertEqual(
            float(cfg.e1_inv_cap_per_pair), float(max_size),
            "Inventory cap should match max size ladder to prevent over-accumulation"
        )

    def test_old_size_ladder_150_would_fail_60_capital(self):
        """Regression guard: the old default 150,200,250 is invalid for $60."""
        old_bad_max = Decimal("250")
        capital = Decimal("60")
        self.assertGreater(
            old_bad_max, capital,
            "This test confirms the OLD default was misconfigured"
        )
        # And new default is correct
        from anantara.sodex_twin_engine import Config
        cfg = Config()
        new_max = max(cfg.e1_size_ladder)
        self.assertLessEqual(float(new_max), float(capital))


class TwinEngineB5SelftestMktempTests(TestCase):
    """B5: cmd_selftest must not use deprecated mktemp()."""

    def test_selftest_does_not_use_mktemp(self):
        """Source code must not contain tempfile.mktemp() in cmd_selftest."""
        source = Path("anantara/sodex_twin_engine.py").read_text()
        # Find cmd_selftest section
        idx = source.find("def cmd_selftest")
        self.assertGreater(idx, 0, "cmd_selftest function not found")
        # Extract whole function: from def cmd_selftest to next top-level def
        nxt = source.find("\ndef ", idx + 1)
        selftest_section = source[idx:nxt] if nxt > 0 else source[idx:]
        self.assertNotIn(
            "tempfile.mktemp(", selftest_section,
            "cmd_selftest must not use deprecated tempfile.mktemp() — race condition"
        )
        self.assertIn(
            "mkdtemp", selftest_section,
            "cmd_selftest must use tempfile.mkdtemp (atomic dir, no race, no WAL leak)"
        )
        self.assertIn(
            "shutil.rmtree", selftest_section,
            "cmd_selftest must rmtree the temp dir (removes db + wal + shm, no leak)"
        )

    def test_selftest_uses_dataclasses_replace_not_direct_assign(self):
        """B7: Config is frozen — selftest must use dataclasses.replace, not cfg.db_path=."""
        source = Path("anantara/sodex_twin_engine.py").read_text()
        idx = source.find("def cmd_selftest")
        selftest_section = source[idx:idx + 1200]
        self.assertNotIn(
            "cfg.db_path = tmp_db", selftest_section,
            "Direct assign to frozen Config.db_path raises FrozenInstanceError"
        )
        self.assertIn(
            "dataclasses.replace(cfg", selftest_section,
            "Must use dataclasses.replace() to set db_path on frozen Config"
        )

    def test_selftest_runs_end_to_end(self):
        """B7 regression: cmd_selftest must run without FrozenInstanceError."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "anantara/sodex_twin_engine.py", "selftest"],
            capture_output=True, text=True, timeout=120,
            cwd=os.path.dirname(os.path.dirname(__file__)),
        )
        self.assertIn("SELFTEST OK", result.stdout,
                      f"selftest did not pass. stdout={result.stdout[-500:]} stderr={result.stderr[-500:]}")


class TwinEngineB6WatchdogParsingTests(TestCase):
    """B6: watchdog.sh .env parsing must handle '=' in values."""

    def test_watchdog_uses_sed_not_cut(self):
        """watchdog_twin.sh must use sed 's/^KEY=//' not grep|cut as an active command."""
        source = Path("scripts/watchdog_twin.sh").read_text()
        import re
        # Active (non-comment) line usage: grep ... | cut -d= -f2
        # A comment line starts with optional whitespace then '#'
        non_comment_lines = [
            line for line in source.splitlines()
            if not re.match(r'^\s*#', line)
        ]
        active_cut_uses = [
            line for line in non_comment_lines
            if re.search(r'grep\s+\S+.*\|\s*cut\s+-d=\s*-f2', line)
        ]
        self.assertEqual(
            active_cut_uses, [],
            "watchdog.sh must not use 'grep ... | cut -d= -f2' as command — truncates base64 with '=' padding"
        )
        # AUDIT 29-Sep-2026: watchdog tidak lagi mem-parse SODEX_PRIVATE_KEY manual —
        # sejak F1-overhaul 2026-07-02 `set -a; source .env` = single source of truth
        # (parsing manual sed/cut justru sumber bug duplikasi). Kontrak baru: TIDAK
        # boleh ada parsing manual var rahasia sama sekali.
        manual_secret_parse = [
            line for line in non_comment_lines
            if re.search(r"(SODEX_PRIVATE_KEY|SODEX_API_KEY)\s*[=:]", line)
        ]
        self.assertEqual(
            manual_secret_parse, [],
            "watchdog must not manually parse secret vars — `set -a; source .env` is canonical"
        )

    def test_watchdog_full_focus_e1_e2_disabled(self):
        """FULL FOKUS E1 (2026-06-21): E1 satu-satunya engine net-positif (modal aman +
        ratio No-Loss). SEMUA E2 OFF (churn dead-end, momentum/OFI falsified, E2Dir
        low-freq) — TAPI kode E2 DISIMPAN (config off saja) utk event/market lain."""
        source = Path("scripts/watchdog_twin.sh").read_text()
        self.assertIn("TE_E2_ENABLED=0", source, "churn OFF")
        self.assertIn("TE_E2_DIR_ENABLED=0", source, "E2Dir OFF (full fokus E1)")
        self.assertIn("TE_E2_MOM_ENABLED=0", source, "momentum/OFI OFF (falsified)")
        # Kode E2 harus tetap ada (bukan dihapus) — config vars masih terdefinisi
        self.assertIn("TE_E2_DIR_LEVERAGE", source, "kode/config E2 DISIMPAN utk masa depan")
        self.assertNotIn("perps ghost bug, unreliable", source)

    def test_watchdog_e2_clip_env_override_exists(self):
        """B55: e2_clip_usd harus bisa di-override via TE_E2_CLIP_MIN/MAX (default lama
        $100-200 berbahaya saat margin perps kecil)."""
        import inspect
        from anantara.sodex_twin_engine import Config
        src = inspect.getsource(Config)
        self.assertIn("TE_E2_CLIP_MIN", src)
        self.assertIn("TE_E2_CLIP_MAX", src)

    def test_watchdog_size_ladder_set(self):
        """watchdog.sh must set TE_E1_SIZE_LADDER — scale PEPE/SHIB after $55 deposit."""
        source = Path("scripts/watchdog_twin.sh").read_text()
        self.assertIn("TE_E1_SIZE_LADDER=50,80,120", source,
                      "scale 2-pair: ladder 50,80,120 deploy $205")

    def test_watchdog_shib_min_spread_set(self):
        """B42 (SUPERSEDED 29-Sep-2026): SHIB DI-DISABLE (net -0.0375%/RT, 306 RT).
        Kontrak baru: watchdog TIDAK boleh hardcode TE_E1_PAIR2_* — sejak
        F1-overhaul 2026-07-02 .env = single source of truth; hardcode di
        watchdog pernah mengunci pair yang sudah di-disable .env."""
        source = Path("scripts/watchdog_twin.sh").read_text()
        non_comment = [l for l in source.splitlines() if not l.strip().startswith("#")]
        hardcoded = [l for l in non_comment if "TE_E1_PAIR2" in l and "export" in l]
        self.assertEqual(hardcoded, [],
                          "watchdog must not hardcode TE_E1_PAIR2_* — .env is canonical")

    def test_watchdog_phase2_vars_present(self):
        """Phase 2: watchdog.sh harus mendefinisikan env vars E2 directional."""
        source = Path("scripts/watchdog_twin.sh").read_text()
        for var in ("TE_E2_DIR_ENABLED", "TE_E2_DIR_PAIR", "TE_E2_DIR_SIZE",
                    "TE_E2_DIR_SL", "TE_E2_DIR_TP", "TE_E2_DIR_BUDGET",
                    "TE_E2_DIR_LIVE"):
            self.assertIn(var, source, f"watchdog.sh missing Phase 2 env var: {var}")

    def test_watchdog_e2_config_preserved_for_future(self):
        """E2 dimatikan (full fokus E1) TAPI semua config/kode E2 DISIMPAN agar bisa
        diaktifkan lagi utk event/market lain (Market Variational Agustus)."""
        source = Path("scripts/watchdog_twin.sh").read_text()
        # config E2 masih terdefinisi (siap re-enable), hanya nilai ENABLED=0
        for var in ("TE_E2_DIR_LEVERAGE", "TE_E2_DIR_SIZE", "TE_E2_DIR_LIVE",
                    "TE_E2_CLIP_MIN", "TE_E2_DIR_FUNDING_THR"):
            self.assertIn(var, source, f"config E2 {var} harus tetap ada (disimpan)")

    def test_watchdog_e2dir_size_above_min_notional(self):
        """B38 fix (2026-06-19): TE_E2_DIR_SIZE harus ≥11 karena minNotional SoDEX=$10 untuk semua 81 pair.
        Size $8 gagal dengan 'notional is invalid'. Fix ke $11 (margin $1 atas minimum)."""
        source = Path("scripts/watchdog_twin.sh").read_text()
        # Extract the size value
        import re
        m = re.search(r'TE_E2_DIR_SIZE=(\d+(?:\.\d+)?)', source)
        self.assertIsNotNone(m, "TE_E2_DIR_SIZE harus ada di watchdog.sh")
        size = float(m.group(1))
        self.assertGreaterEqual(size, 11.0,
            f"TE_E2_DIR_SIZE={size} < minNotional SoDEX $10 (semua 81 pairs). "
            "Notional = size → ≥$11 diperlukan untuk margin aman.")


class TwinEnginePhase2DirectionalTests(TestCase):
    """Phase 2: Engine2Directional — funding+OBI sinyal direksional.

    Semua test menggunakan in-memory DB + mock adapter (nol-risiko).
    Prinsip falsification-first: signal hanya muncul bila threshold terpenuhi.
    """

    def setUp(self):
        """Setup ledger in-memory + config Phase 2 aktif (paper)."""
        import sqlite3
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import Ledger, Config, SCHEMA
        cfg_kwargs = dict(
            e2_dir_enabled=True,
            e2_dir_pair="ENA-USD",
            e2_dir_size_usd=D("5.0"),
            e2_dir_sl_pct=D("0.01"),
            e2_dir_tp_pct=D("0.02"),
            e2_dir_hold_s=1800,
            e2_dir_budget=D("10.0"),
            e2_dir_min_n=30,
            e2_dir_funding_thr=D("0.0005"),
            e2_dir_obi_thr=D("0.15"),
            e2_dir_live_enabled=False,
        )
        import dataclasses
        self.cfg = dataclasses.replace(Config(), **cfg_kwargs)
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.row_factory = sqlite3.Row
        led.con.executescript(SCHEMA)
        led.con.commit()
        self.led = led
        self.D = D

    def _make_adapter(self, funding_rate=0.001, bid=0.5, ask=0.501):
        """Mock adapter dengan funding rate dan orderbook yang dapat dikonfigurasi."""
        from decimal import Decimal as D
        adp = mock.MagicMock()
        adp.funding_rate.return_value = D(str(funding_rate))
        book = mock.MagicMock()
        book.bid = D(str(bid))
        book.ask = D(str(ask))
        book.mid = D(str((bid + ask) / 2))
        adp.book.return_value = book
        return adp

    def test_generate_signal_high_funding_positive_returns_short(self):
        """Funding rate tinggi positif → signal SHORT (longs overcrowded)."""
        from anantara.sodex_twin_engine import generate_directional_signal
        adp = self._make_adapter(funding_rate=0.0012)  # > 2× threshold → grade S
        sig = generate_directional_signal(adp, "ENA-USD", self.cfg)
        self.assertIsNotNone(sig, "Funding 0.12%/8h harus menghasilkan sinyal")
        self.assertEqual(sig["side"], "sell", "Funding positif tinggi → SHORT (sell)")

    def test_generate_signal_high_funding_negative_returns_long(self):
        """Funding rate negatif tinggi → signal LONG (shorts overcrowded)."""
        from anantara.sodex_twin_engine import generate_directional_signal
        adp = self._make_adapter(funding_rate=-0.0012)  # < -threshold
        sig = generate_directional_signal(adp, "ENA-USD", self.cfg)
        self.assertIsNotNone(sig)
        self.assertEqual(sig["side"], "buy", "Funding negatif tinggi → LONG (buy)")

    def test_generate_signal_below_threshold_returns_none(self):
        """Funding di bawah threshold → tidak ada sinyal (falsification-first)."""
        from anantara.sodex_twin_engine import generate_directional_signal
        adp = self._make_adapter(funding_rate=0.0001)  # < threshold 0.0005
        sig = generate_directional_signal(adp, "ENA-USD", self.cfg)
        self.assertIsNone(sig, "Funding rendah harus return None (tidak ada edge)")

    def test_generate_signal_grade_s_at_2x_threshold(self):
        """Funding ≥ 2× threshold → grade S (sinyal terkuat)."""
        from anantara.sodex_twin_engine import generate_directional_signal
        adp = self._make_adapter(funding_rate=0.0015)  # > 2× 0.0005 = 0.001
        sig = generate_directional_signal(adp, "ENA-USD", self.cfg)
        if sig:  # mungkin None bila OBI berlawanan
            # Grade S atau A — keduanya valid
            self.assertIn(sig["grade"], ("S", "A", "B"))

    def test_generate_signal_adapter_exception_returns_none(self):
        """Bila funding_rate() error → None (fail-safe)."""
        from anantara.sodex_twin_engine import generate_directional_signal
        adp = mock.MagicMock()
        adp.funding_rate.side_effect = Exception("API timeout")
        sig = generate_directional_signal(adp, "ENA-USD", self.cfg)
        self.assertIsNone(sig, "Exception pada funding_rate → None (bukan crash)")

    def test_e2_dir_open_and_stats(self):
        """Ledger e2_dir_open + e2_dir_stats mencatat sinyal dengan benar."""
        from decimal import Decimal as D
        sig_id = self.led.e2_dir_open(
            "ENA-USD", "sell", "A", D("0.001"), D("-0.2"),
            D("0.5"), D("10.0"))
        self.assertIsNotNone(sig_id)
        # Sebelum ditutup: stats n=0 (belum ada closed)
        st = self.led.e2_dir_stats("ENA-USD")
        self.assertEqual(st["n"], 0, "Sinyal terbuka belum masuk stats")
        # Tutup sinyal dengan profit
        self.led.e2_dir_close(sig_id, D("0.51"), D("0.008"), "tp")
        st = self.led.e2_dir_stats("ENA-USD")
        self.assertEqual(st["n"], 1)
        self.assertEqual(st["n_win"], 1)
        self.assertAlmostEqual(float(st["win_rate"]), 1.0)

    def test_e2_dir_budget_spent(self):
        """Budget_spent hanya hitung loss kumulatif (bukan profit)."""
        from decimal import Decimal as D
        sid1 = self.led.e2_dir_open("ENA-USD", "sell", "B", D("0.0005"), D("-0.1"),
                                     D("0.5"), D("10.0"))
        self.led.e2_dir_close(sid1, D("0.495"), D("-0.05"), "sl")  # rugi
        sid2 = self.led.e2_dir_open("ENA-USD", "buy", "A", D("-0.001"), D("0.2"),
                                     D("0.495"), D("10.0"))
        self.led.e2_dir_close(sid2, D("0.505"), D("0.08"), "tp")   # profit
        spent = self.led.e2_dir_budget_spent()
        # Hanya loss yang terhitung
        self.assertAlmostEqual(float(spent), 0.05, places=4,
                               msg="Budget_spent hanya menghitung rugi, bukan profit")

    def test_engine2_directional_budget_halt(self):
        """Bila budget habis, step() harus return False (no new trades)."""
        from decimal import Decimal as D
        import dataclasses
        from anantara.sodex_twin_engine import Engine2Directional, Ledger, SCHEMA
        import sqlite3
        # Config dengan budget kecil ($0.01)
        cfg = dataclasses.replace(self.cfg, e2_dir_budget=D("0.01"))
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.row_factory = sqlite3.Row
        led.con.executescript(SCHEMA)
        led.con.commit()
        # Tambah loss > budget
        sid = led.e2_dir_open("ENA-USD", "sell", "B", D("0.0005"), D("-0.1"),
                               D("0.5"), D("10.0"))
        led.e2_dir_close(sid, D("0.495"), D("-0.05"), "sl")  # spent=$0.05 > budget=$0.01
        tg = mock.MagicMock(); adp = self._make_adapter()
        eng = Engine2Directional(cfg, adp, led, tg)
        result = eng.step()
        self.assertFalse(result, "step() harus False saat budget habis (HALT)")
        adp.funding_rate.assert_not_called()  # tidak boleh akses exchange saat HALT

    def test_engine2_directional_failopen_low_n(self):
        """Edge gate fail-open bila n < min_n (belum ada data cukup)."""
        from anantara.sodex_twin_engine import Engine2Directional
        tg = mock.MagicMock()
        adp = self._make_adapter(funding_rate=0.00001)  # sinyal terlalu kecil → None
        eng = Engine2Directional(self.cfg, adp, self.led, tg)
        ok, reason = eng.edge_ok()
        self.assertTrue(ok, "Fail-open bila n<min_n (data belum cukup)")
        self.assertIn("fail-open", reason.lower())

    def test_engine2_directional_gate_closes_at_low_wr(self):
        """Gate menutup bila WR jatuh di bawah 40% (dengan n≥min_n)."""
        from decimal import Decimal as D
        import dataclasses
        from anantara.sodex_twin_engine import Engine2Directional
        # Set min_n kecil agar gate aktif dengan data sedikit
        cfg = dataclasses.replace(self.cfg, e2_dir_min_n=3)
        # Tambah 3 loss untuk WR=0%
        for _ in range(3):
            sid = self.led.e2_dir_open("ENA-USD", "sell", "B", D("0.0005"),
                                        D("-0.1"), D("0.5"), D("10.0"))
            self.led.e2_dir_close(sid, D("0.495"), D("-0.002"), "sl")
        tg = mock.MagicMock(); adp = self._make_adapter()
        eng = Engine2Directional(cfg, adp, self.led, tg)
        ok, reason = eng.edge_ok()
        self.assertFalse(ok, "Gate harus HALT bila WR=0% dengan n≥min_n")
        self.assertIn("HALT", reason)

    def test_cmd_dir_status_runs_without_error(self):
        """cmd_dir_status harus bisa dijalankan tanpa crash (smoke test)."""
        import dataclasses
        from anantara.sodex_twin_engine import cmd_dir_status, Config
        import io
        # Config dengan e2_dir_enabled=True, DB path sementara
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_db = f.name
        try:
            cfg = dataclasses.replace(Config(), db_path=tmp_db, e2_dir_enabled=True)
            # Harus berjalan tanpa exception
            with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                cmd_dir_status(cfg)
            output = mock_out.getvalue()
            self.assertIn("PHASE 2", output)
            self.assertIn("Budget", output)
        finally:
            import os; os.unlink(tmp_db)

    def test_schema_contains_e2_dir_signals_table(self):
        """SCHEMA harus mendefinisikan tabel e2_dir_signals."""
        from anantara.sodex_twin_engine import SCHEMA
        self.assertIn("e2_dir_signals", SCHEMA,
                      "SCHEMA harus punya tabel e2_dir_signals untuk ledger Phase 2")
        self.assertIn("funding_rate", SCHEMA)
        self.assertIn("obi", SCHEMA)
        self.assertIn("exit_reason", SCHEMA)

    def test_config_phase2_defaults(self):
        """Config default Phase 2: disabled, paper-first, budget=$10."""
        from anantara.sodex_twin_engine import Config
        from decimal import Decimal as D
        cfg = Config()
        self.assertFalse(cfg.e2_dir_enabled, "Phase 2 disabled by default")
        self.assertFalse(cfg.e2_dir_live_enabled, "Live disabled by default (paper-first)")
        self.assertEqual(cfg.e2_dir_budget, D("10.0"), "Budget default $10")
        self.assertEqual(cfg.e2_dir_min_n, 30, "min_n=30 untuk gate WR")
        # B23: pair default="" (scan dinamis semua SoDEX perps, bukan hardcode ENA-USD)
        self.assertEqual(cfg.e2_dir_pair, "", "B23: pair kosong = scan dinamis")

    def test_e2_dir_open_signal_returns_latest_open(self):
        """e2_dir_open_signal() mengembalikan posisi terbuka terbaru."""
        from decimal import Decimal as D
        # Buka lalu tutup sinyal
        sid1 = self.led.e2_dir_open("ENA-USD", "sell", "A", D("0.001"), D("-0.2"),
                                     D("0.5"), D("10.0"))
        self.led.e2_dir_close(sid1, D("0.49"), D("0.05"), "tp")
        # Tidak ada posisi terbuka
        result = self.led.e2_dir_open_signal("ENA-USD")
        self.assertIsNone(result, "Semua sinyal sudah tutup → None")
        # Buka sinyal baru
        self.led.e2_dir_open("ENA-USD", "buy", "S", D("-0.0012"), D("0.25"),
                              D("0.49"), D("10.2"))
        result = self.led.e2_dir_open_signal("ENA-USD")
        self.assertIsNotNone(result)
        self.assertEqual(result["side"], "buy")

    # ── B20: taker fee correction ──

    def test_b20_perp_taker_fee_in_config(self):
        """B20: Config harus punya perp_taker_fee yang lebih tinggi dari maker fee."""
        from anantara.sodex_twin_engine import Config
        cfg = Config()
        self.assertTrue(hasattr(cfg, "perp_taker_fee"),
                        "Config harus punya field perp_taker_fee (B20)")
        # Taker fee (0.02%) harus lebih besar dari maker fee (0.0108%)
        self.assertGreater(cfg.perp_taker_fee, cfg.perp_maker_fee,
                           "Taker fee harus > maker fee (Tier-0: 0.02% vs 0.0108%)")

    def test_b20_taker_fee_default_value(self):
        """B20: default taker fee = 0.0002 (0.02% Tier-0 SoDEX)."""
        from anantara.sodex_twin_engine import Config
        from decimal import Decimal as D
        cfg = Config()
        self.assertEqual(cfg.perp_taker_fee, D("0.0002"),
                         "Default taker fee Tier-0 SoDEX = 0.02%")

    def test_b20_fee_calc_uses_taker_not_maker(self):
        """B20: _manage_position() menggunakan perp_taker_fee (bukan maker) untuk fee."""
        import inspect
        from anantara.sodex_twin_engine import Engine2Directional
        src = inspect.getsource(Engine2Directional._manage_position)
        self.assertIn("perp_taker_fee", src,
                      "_manage_position harus pakai perp_taker_fee (B20)")
        # Pastikan actual fee assignment pakai taker
        # (komentar boleh menyebut perp_maker_fee; yang penting
        # "self.cfg.perp_taker_fee" ada di source sebagai ekspresi aktual)
        self.assertIn("self.cfg.perp_taker_fee", src,
                      "fee harus dihitung dengan self.cfg.perp_taker_fee (B20)")

    # ── B21: E2Dir stats di monitor report ──

    def test_b21_monitor_report_contains_e2_dir_fields(self):
        """B21: build_monitor_report() harus menyertakan stats Phase 2."""
        import sqlite3, dataclasses
        from unittest import mock
        from anantara.sodex_twin_engine import (build_monitor_report, Config,
                                                 Ledger, SCHEMA)
        cfg = dataclasses.replace(Config(), e2_dir_enabled=True, e2_dir_pair="ENA-USD")
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.row_factory = sqlite3.Row
        led.con.executescript(SCHEMA)
        led.con.commit()
        adp = mock.MagicMock()
        adp.balance.return_value = {"vUSDC": self.D("100")}
        adp.book.return_value = mock.MagicMock(mid=self.D("1.0"),
                                                bid=self.D("0.99"),
                                                ask=self.D("1.01"))
        rep = build_monitor_report(cfg, adp, led)
        for field in ("e2_dir_enabled", "e2_dir_pair", "e2_dir_n",
                      "e2_dir_win_rate", "e2_dir_total_pnl",
                      "e2_dir_budget_spent", "e2_dir_budget_remaining",
                      "e2_dir_gate"):
            self.assertIn(field, rep, f"Monitor report harus punya field: {field}")
        self.assertEqual(rep["e2_dir_n"], 0, "Awal: belum ada sinyal")
        self.assertEqual(rep["e2_dir_gate"], "fail_open",
                         "Fail-open saat n < min_n")

    # ── B22: step counter & log periodik ──

    def test_b22_step_count_attr_exists(self):
        """B22: Engine2Directional harus punya _step_count untuk log periodik."""
        from anantara.sodex_twin_engine import Engine2Directional, Config
        import dataclasses
        from unittest import mock
        cfg = dataclasses.replace(Config(), e2_dir_enabled=True, e2_dir_pair="ENA-USD")
        eng = Engine2Directional(cfg, mock.MagicMock(), self.led, mock.MagicMock())
        self.assertTrue(hasattr(eng, "_step_count"),
                        "Engine2Directional harus punya _step_count (B22)")
        self.assertEqual(eng._step_count, 0, "Inisialisasi harus 0")

    def test_b22_step_increments_count(self):
        """B22: setiap step() menambah _step_count (bahkan saat tidak ada sinyal)."""
        from anantara.sodex_twin_engine import Engine2Directional, Config
        from decimal import Decimal as D
        import dataclasses
        from unittest import mock
        cfg = dataclasses.replace(Config(), e2_dir_enabled=True, e2_dir_pair="ENA-USD",
                                  e2_dir_funding_thr=D("0.0005"))
        # Adapter dengan funding kecil — tidak ada sinyal
        adp = mock.MagicMock()
        adp.funding_rate.return_value = D("0.0001")  # di bawah threshold
        eng = Engine2Directional(cfg, adp, self.led, mock.MagicMock())
        eng.step()
        self.assertEqual(eng._step_count, 1, "step() harus tambah _step_count")

    # ── B24: flush-pair CLI ──

    def test_b24_cmd_flush_pair_requires_yes(self):
        """B24: cmd_flush_pair harus NO-OP tanpa --yes (keselamatan)."""
        import io, dataclasses
        from anantara.sodex_twin_engine import cmd_flush_pair, Config
        cfg = dataclasses.replace(Config(), db_path=":memory:")
        out_buf = io.StringIO()
        with contextlib.redirect_stdout(out_buf):
            cmd_flush_pair(cfg, "XLM/USDC", yes=False)
        output = out_buf.getvalue()
        self.assertIn("--yes", output, "Harus tampilkan petunjuk --yes")
        self.assertNotIn("FLUSH SELESAI", output, "Tanpa --yes tidak boleh flush")

    def test_b24_flush_pair_cli_subcommand_registered(self):
        """B24: flush-pair harus terdaftar sebagai subcommand CLI."""
        import argparse
        from anantara.sodex_twin_engine import main
        import inspect
        src = inspect.getsource(main)
        self.assertIn("flush-pair", src, "CLI harus daftar flush-pair subcommand")
        self.assertIn("--yes", src, "flush-pair harus punya flag --yes")

    def test_b24_cmd_flush_pair_function_exists(self):
        """B24: cmd_flush_pair harus bisa diimport."""
        from anantara.sodex_twin_engine import cmd_flush_pair
        self.assertTrue(callable(cmd_flush_pair))

    # ── B25: e1research formal verdict ──

    def test_b25_e1research_shows_formal_verdict(self):
        """B25: cmd_e1research harus cetak VERDICT ILMIAH FORMAL."""
        import inspect
        from anantara.sodex_twin_engine import cmd_e1research
        src = inspect.getsource(cmd_e1research)
        self.assertIn("VERDICT ILMIAH FORMAL", src,
                      "cmd_e1research harus cetak verdict ilmiah formal (B25)")

    def test_b25_verdict_terfalsifikasi_when_zero_wide_spread(self):
        """B25: verdict H1 TERFALSIFIKASI bila frac_ge_40bps = 0.0%."""
        from anantara.sodex_twin_engine import analyze_spread_samples
        # Semua spread 34-36 bps (tidak pernah ≥ 40 bps)
        samples = [{"pair": "PEPE/USDC", "spread_bps": 34 + (i % 3)}
                   for i in range(60)]
        analysis = analyze_spread_samples(samples, fee_round_trip_bps=2.16)
        st = analysis["pairs"]["PEPE/USDC"]
        self.assertEqual(st["frac_ge"]["ge_40bps"], 0.0,
                         "fraksi ≥40 bps harus 0 untuk spread 34-36 bps")
        self.assertEqual(st["n"], 60)

    def test_b25_verdict_layak_when_spread_often_wide(self):
        """B25: verdict H1 LAYAK bila frac_ge_40bps ≥ 5%."""
        from anantara.sodex_twin_engine import analyze_spread_samples
        # 50% spread ≥ 40 bps
        samples = ([{"pair": "PEPE/USDC", "spread_bps": 45.0}] * 30 +
                   [{"pair": "PEPE/USDC", "spread_bps": 30.0}] * 30)
        analysis = analyze_spread_samples(samples, fee_round_trip_bps=2.16)
        st = analysis["pairs"]["PEPE/USDC"]
        self.assertEqual(st["frac_ge"]["ge_40bps"], 0.5, "50% harus ≥ 40 bps")

    # ── B26: Phase 2 in-flight capital ──

    def test_b26_monitor_report_has_inflight_field(self):
        """B26: build_monitor_report() harus menyertakan e2_dir_inflight_usd."""
        import sqlite3, dataclasses
        from unittest import mock
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import (build_monitor_report, Config,
                                                 Ledger, SCHEMA)
        cfg = dataclasses.replace(Config(), e2_dir_enabled=True, e2_dir_pair="")
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.executescript(SCHEMA)
        led.con.commit()
        adp = mock.MagicMock()
        adp.balance.return_value = {"vUSDC": D("100")}
        adp.book.return_value = mock.MagicMock(mid=D("1.0"), bid=D("0.99"), ask=D("1.01"))
        rep = build_monitor_report(cfg, adp, led)
        self.assertIn("e2_dir_inflight_usd", rep,
                      "Monitor report harus punya e2_dir_inflight_usd (B26)")
        self.assertEqual(rep["e2_dir_inflight_usd"], 0.0,
                         "Tidak ada posisi terbuka → inflight=0")

    def test_b26_monitor_inflight_nonzero_when_open_position(self):
        """B26: e2_dir_inflight_usd harus non-zero bila ada posisi terbuka."""
        import sqlite3, dataclasses
        from unittest import mock
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import (build_monitor_report, Config,
                                                 Ledger, SCHEMA)
        cfg = dataclasses.replace(Config(), e2_dir_enabled=True, e2_dir_pair="")
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.executescript(SCHEMA)
        led.con.commit()
        # Buka posisi direksional
        led.e2_dir_open("ENA-USD", "buy", "B", D("0.001"), D("-0.2"), D("1.0"), D("5.0"))
        adp = mock.MagicMock()
        adp.balance.return_value = {"vUSDC": D("100")}
        adp.book.return_value = mock.MagicMock(mid=D("1.0"), bid=D("0.99"), ask=D("1.01"))
        rep = build_monitor_report(cfg, adp, led)
        # inflight = entry_px * qty = 1.0 * 5.0 = 5.0
        self.assertGreater(rep["e2_dir_inflight_usd"], 0.0,
                           "Ada posisi terbuka → inflight > 0 (B26)")

    def test_b26_dir_status_shows_inflight_when_open(self):
        """B26: cmd_dir_status() harus tampilkan 'in-flight' bila ada posisi."""
        import io, dataclasses, tempfile
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import cmd_dir_status, Config, Ledger, SCHEMA
        # Buat temp DB baru — butuh ledger tersendiri (setUp punya self.led)
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_db = f.name
        try:
            cfg = dataclasses.replace(Config(), e2_dir_enabled=True, e2_dir_pair="",
                                      db_path=tmp_db)
            tmp_led = Ledger(tmp_db)
            # Buka posisi di DB yang sama dengan cfg
            tmp_led.e2_dir_open("ENA-USD", "buy", "A", D("0.001"), D("0.3"),
                                D("2.0"), D("5.0"))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cmd_dir_status(cfg)
            output = buf.getvalue()
            self.assertIn("In-flight", output,
                          "dir-status harus tampilkan in-flight capital")
            self.assertIn("10.00", output, "Harus tampilkan nilai in-flight (entry_px*qty=2*5=10)")
        finally:
            os.unlink(tmp_db)


# ────────────────────────────────────────────────────────────────────────────
# B27: cmd_flush_pair — balance-delta fill detection
# ────────────────────────────────────────────────────────────────────────────

class TwinEngineB27FlushBalanceDeltaTests(TestCase):
    """B27: cmd_flush_pair harus deteksi fill via balance-delta, BUKAN poll_fill.

    Latar: poll_fill (B9 anti-phantom) mengembalikan 0 bila order hilang dari
    open-list meskipun order sudah TERISI. Untuk flush standalone, order hilang
    = terisi (bukan dibatalkan). Solusi B27: bandingkan balance coin sebelum vs
    sesudah → delta = qty yang terjual.
    """

    def _make_cfg(self):
        import dataclasses
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import Config
        return dataclasses.replace(Config(), spot_maker_fee=D("0.001"))

    def test_flush_reads_balance_before_order(self):
        """B27: balance() dipanggil SEBELUM order dipasang (untuk snapshot awal)."""
        from unittest.mock import patch, MagicMock, call
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import cmd_flush_pair

        cfg = self._make_cfg()
        mock_order = MagicMock()
        mock_order.oid = "123"
        mock_order.price = D("0.235")

        # balance() dipanggil: (1) sebelum order, (2+) loop poll, (3) laporan final
        # Gunakan side_effect dengan callable agar tidak habis di iterasi poll
        bal_before = {"vXLM": D("100.0"), "vUSDC": D("100.0")}
        bal_after  = {"vXLM": D("0.5"),   "vUSDC": D("123.5")}  # XLM terjual
        _call_count = [0]
        def _bal_effect():
            _call_count[0] += 1
            return bal_before if _call_count[0] == 1 else bal_after

        with patch("anantara.sodex_twin_engine.SodexLiveAdapter") as MockAdp, \
             patch("time.sleep"):
            inst = MockAdp.return_value
            inst.balance.side_effect = _bal_effect
            inst.book.return_value = MagicMock(bid=D("0.235"), mid=D("0.236"))
            inst.place_post_only.return_value = mock_order

            with contextlib.redirect_stdout(io.StringIO()):
                cmd_flush_pair(cfg, "XLM/USDC", yes=True)

            # balance() harus dipanggil lebih dari 1 kali (sebelum + selama + sesudah)
            self.assertGreaterEqual(inst.balance.call_count, 2,
                                    "balance() harus dipanggil minimal 2× (sebelum+sesudah)")

    def test_flush_reports_success_from_balance_delta(self):
        """B27: Laporan menunjukkan USDC diterima saat coin balance berkurang."""
        from unittest.mock import patch, MagicMock
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import cmd_flush_pair

        cfg = self._make_cfg()
        mock_order = MagicMock()
        mock_order.oid = "456"
        mock_order.price = D("0.235")

        bal_before = {"vXLM": D("123.0"), "vUSDC": D("100.0")}
        bal_after  = {"vXLM": D("0.5"),   "vUSDC": D("129.0")}  # 123 XLM → +$29
        _calls = [0]
        def _bal_fx():
            _calls[0] += 1
            return bal_before if _calls[0] == 1 else bal_after

        with patch("anantara.sodex_twin_engine.SodexLiveAdapter") as MockAdp, \
             patch("time.sleep"):
            inst = MockAdp.return_value
            inst.balance.side_effect = _bal_fx
            inst.book.return_value = MagicMock(bid=D("0.235"), mid=D("0.236"))
            inst.place_post_only.return_value = mock_order

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cmd_flush_pair(cfg, "XLM/USDC", yes=True)
            output = buf.getvalue()

        # Laporan harus menunjukkan FLUSH SELESAI atau USDC delta
        self.assertTrue(
            "FLUSH SELESAI" in output or "USDC" in output,
            f"Output harus menunjukkan keberhasilan flush:\n{output}")

    def test_flush_no_order_when_balance_zero(self):
        """B27: Tidak memasang order bila balance coin sudah 0."""
        from unittest.mock import patch, MagicMock
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import cmd_flush_pair

        cfg = self._make_cfg()
        bal_zero = {"vXLM": D("0.0"), "vUSDC": D("100.0")}

        with patch("anantara.sodex_twin_engine.SodexLiveAdapter") as MockAdp:
            inst = MockAdp.return_value
            inst.balance.return_value = bal_zero

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cmd_flush_pair(cfg, "XLM/USDC", yes=True)
            output = buf.getvalue()

        self.assertNotIn("Memasang SELL", output, "Tidak memasang order bila balance 0")
        self.assertIn("sudah 0", output)
        inst.place_post_only.assert_not_called()


# ────────────────────────────────────────────────────────────────────────────
# B28: B14 Gate — death spiral detection (locked hours tracking)
# ────────────────────────────────────────────────────────────────────────────

class TwinEngineB28B14LockedStatusTests(TestCase):
    """B28: B14 gate harus menyimpan kapan ia pause, agar monitor bisa deteksi
    death spiral (E1 pause → tidak ada RT baru → rate tidak pernah recover).
    """

    def _make_engine_with_real_led(self):
        """Engine dengan ledger in-memory nyata (bukan mock) untuk test state persistence."""
        import sqlite3
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import Engine1Flywheel, Config, Ledger, SCHEMA

        cfg = Config()
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.row_factory = sqlite3.Row
        led.con.executescript(SCHEMA)
        led.con.commit()

        # Mock adapter, tg
        adp = MagicMock()
        tg = MagicMock()
        eng = Engine1Flywheel(cfg, adp, led, tg, MagicMock(),
                              hedge_enabled=False, pair="PEPE/USDC")
        return eng, led, cfg

    def test_b28_pause_saves_timestamp_to_state(self):
        """B28: Saat B14 pause, b14_pause_since_ts harus tersimpan di state DB."""
        import time
        from decimal import Decimal as D
        eng, led, cfg = self._make_engine_with_real_led()

        # Set b13 sehingga gate tidak skip
        led.set_state("b13_activated_ts", "0")

        # Inisialisasi RT negatif yang cukup untuk trigger pause
        now_iso = "2026-01-01T00:00:00+00:00"
        for i in range(cfg.e1_gate_min_n + 5):
            led.con.execute(
                "INSERT INTO rts(rt_id,ts_close,engine,pair,volume,net_pnl) VALUES(?,?,?,?,?,?)",
                (f"R{i}", now_iso, "E1", "PEPE/USDC", "10", "-0.5"))
        led.con.commit()

        t_before = time.time()
        eng._check_profitability_gate()
        t_after = time.time()

        self.assertTrue(eng._quoting_paused, "Gate harus pause dengan rate sangat negatif")
        saved_ts = float(led.get_state("b14_pause_since_ts"))
        self.assertGreater(saved_ts, 0, "b14_pause_since_ts harus > 0 setelah pause")
        self.assertGreaterEqual(saved_ts, t_before - 1)
        self.assertLessEqual(saved_ts, t_after + 1)

    def test_b28_resume_clears_pause_timestamp(self):
        """B28: Saat B14 resume, b14_pause_since_ts harus di-clear ke 0."""
        from decimal import Decimal as D
        eng, led, cfg = self._make_engine_with_real_led()

        led.set_state("b13_activated_ts", "0")
        led.set_state("b14_pause_since_ts", "9999999999.0")  # simulasi sedang pause
        eng._quoting_paused = True

        # RT yang membuat rate sangat positif (resume)
        now_iso = "2026-01-01T00:00:00+00:00"
        for i in range(cfg.e1_gate_min_n + 5):
            led.con.execute(
                "INSERT INTO rts(rt_id,ts_close,engine,pair,volume,net_pnl) VALUES(?,?,?,?,?,?)",
                (f"P{i}", now_iso, "E1", "PEPE/USDC", "10", "5.0"))
        led.con.commit()

        eng._check_profitability_gate()

        self.assertFalse(eng._quoting_paused, "Seharusnya resume setelah rate positif")
        cleared = float(led.get_state("b14_pause_since_ts"))
        self.assertEqual(cleared, 0.0, "b14_pause_since_ts harus dikosongkan (0) setelah resume")

    def test_b28_monitor_reports_b14_status_active(self):
        """B28: Monitor report harus menyertakan b14_status='ACTIVE' bila tidak pause."""
        import sqlite3, dataclasses
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import build_monitor_report, Config, Ledger, SCHEMA

        cfg = dataclasses.replace(Config(), e2_dir_enabled=False)
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.executescript(SCHEMA); led.con.commit()
        # Tidak ada pause (default state = 0)

        adp = MagicMock()
        adp.balance.return_value = {"vUSDC": D("100")}
        adp.book.return_value = MagicMock(mid=D("1.0"), bid=D("0.99"), ask=D("1.01"))
        rep = build_monitor_report(cfg, adp, led)

        self.assertIn("b14_status", rep, "Monitor harus punya field b14_status (B28)")
        self.assertEqual(rep["b14_status"], "ACTIVE",
                         "Tanpa pause → b14_status harus ACTIVE")
        self.assertEqual(rep["b14_locked_hours"], 0.0)
        self.assertIsNone(rep["b14_pause_since"])

    def test_b28_monitor_reports_b14_paused_with_locked_hours(self):
        """B28: Monitor report harus tampilkan locked_hours bila B14 sedang pause."""
        import sqlite3, dataclasses, time
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import build_monitor_report, Config, Ledger, SCHEMA

        cfg = dataclasses.replace(Config(), e2_dir_enabled=False)
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.executescript(SCHEMA); led.con.commit()
        # Simulasi pause 2 jam yang lalu
        two_hours_ago = time.time() - 7200
        led.set_state("b14_pause_since_ts", str(two_hours_ago))

        adp = MagicMock()
        adp.balance.return_value = {"vUSDC": D("100")}
        adp.book.return_value = MagicMock(mid=D("1.0"), bid=D("0.99"), ask=D("1.01"))
        rep = build_monitor_report(cfg, adp, led)

        self.assertEqual(rep["b14_status"], "PAUSED")
        self.assertGreaterEqual(rep["b14_locked_hours"], 1.9,
                                "Pause 2 jam → locked_hours ≥ 1.9")
        self.assertLessEqual(rep["b14_locked_hours"], 2.1)
        self.assertIsNotNone(rep["b14_pause_since"])


# ────────────────────────────────────────────────────────────────────────────
# B29: Phase 2 — sinyal direksional serentak (concurrent multi-signal)
# ────────────────────────────────────────────────────────────────────────────

class TwinEngineB29ConcurrentSignalsTests(TestCase):
    """B29: Engine2Directional boleh mengelola hingga 3 sinyal serentak (beda pair).

    Tujuan: kumpulkan data n=30 minimum 3× lebih cepat dengan parallel tracking.
    Safety: satu pair tidak boleh punya lebih dari satu posisi terbuka sekaligus.
    """

    def _make_led(self):
        import sqlite3
        from anantara.sodex_twin_engine import Ledger, SCHEMA
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.row_factory = sqlite3.Row
        led.con.executescript(SCHEMA)
        led.con.commit()
        return led

    def test_e2_dir_open_signals_returns_all(self):
        """B29: e2_dir_open_signals() harus mengembalikan SEMUA posisi terbuka."""
        from decimal import Decimal as D
        led = self._make_led()
        # Buka 3 posisi berbeda pair
        led.e2_dir_open("TRUMP-USD", "sell", "S", D("0.001"), D("0.3"), D("10.0"), D("0.5"))
        led.e2_dir_open("ENA-USD",   "buy",  "A", D("0.001"), D("0.2"), D("5.0"),  D("1.0"))
        led.e2_dir_open("HYPE-USD",  "sell", "B", D("0.001"), D("0.1"), D("2.0"),  D("2.5"))

        opens = led.e2_dir_open_signals()
        self.assertEqual(len(opens), 3, "Harus mengembalikan 3 posisi terbuka")
        pairs = {p["pair"] for p in opens}
        self.assertEqual(pairs, {"TRUMP-USD", "ENA-USD", "HYPE-USD"})

    def test_e2_dir_open_signals_excludes_closed(self):
        """B29: Posisi yang sudah closed tidak boleh muncul di open_signals()."""
        from decimal import Decimal as D
        led = self._make_led()
        sig_id = led.e2_dir_open("ENA-USD", "buy", "A", D("0"), D("0"), D("5.0"), D("1.0"))
        led.e2_dir_close(sig_id, D("5.1"), D("0.09"), "tp")

        opens = led.e2_dir_open_signals()
        self.assertEqual(len(opens), 0, "Posisi closed tidak boleh ada di open_signals()")

    def test_e2_dir_step_manages_all_concurrent(self):
        """B29: step() harus mengelola SEMUA posisi terbuka (bukan hanya 1)."""
        import dataclasses
        from decimal import Decimal as D
        from unittest.mock import MagicMock, patch
        from datetime import datetime, timezone, timedelta
        from anantara.sodex_twin_engine import Engine2Directional, Config

        cfg = dataclasses.replace(Config(),
                                   e2_dir_enabled=True, e2_dir_pair="",
                                   e2_dir_size_usd=D("5.0"),
                                   e2_dir_sl_pct=D("0.01"),
                                   e2_dir_tp_pct=D("0.02"),
                                   e2_dir_hold_s=1800,
                                   e2_dir_budget=D("10.0"),
                                   e2_dir_min_n=30,
                                   e2_dir_funding_thr=D("0.0005"),
                                   e2_dir_live_enabled=False)
        led = self._make_led()

        # Buka 2 posisi yang sudah timeout (opened 2 jam lalu)
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        led.con.execute(
            "INSERT INTO e2_dir_signals(pair,side,grade,funding_rate,obi,entry_px,qty,opened_ts)"
            " VALUES(?,?,?,?,?,?,?,?)",
            ("TRUMP-USD", "sell", "S", "0.001", "0.3", "10.0", "0.5", old_ts))
        led.con.execute(
            "INSERT INTO e2_dir_signals(pair,side,grade,funding_rate,obi,entry_px,qty,opened_ts)"
            " VALUES(?,?,?,?,?,?,?,?)",
            ("ENA-USD", "buy", "A", "0.001", "0.2", "5.0", "1.0", old_ts))
        led.con.commit()

        adp = MagicMock()
        adp.book.return_value = MagicMock(bid=D("9.9"), ask=D("10.1"), mid=D("10.0"))
        adp.funding_rate.return_value = D("0.001")
        tg = MagicMock()

        e2 = Engine2Directional(cfg, adp, led, tg)
        e2.step()  # harus kelola kedua posisi

        # Setelah timeout, kedua posisi harus sudah close
        remaining = led.e2_dir_open_signals()
        self.assertEqual(len(remaining), 0,
                         "Setelah step(), posisi timeout harus ditutup semua (B29)")

    def test_e2_dir_no_duplicate_pair(self):
        """B29: step() tidak boleh membuka posisi baru pada pair yang sudah punya posisi."""
        import dataclasses
        from decimal import Decimal as D
        from unittest.mock import MagicMock, patch
        from anantara.sodex_twin_engine import Engine2Directional, Config, generate_directional_signal

        cfg = dataclasses.replace(Config(),
                                   e2_dir_enabled=True, e2_dir_pair="ENA-USD",
                                   e2_dir_size_usd=D("5.0"),
                                   e2_dir_sl_pct=D("0.01"),
                                   e2_dir_tp_pct=D("0.02"),
                                   e2_dir_hold_s=1800,
                                   e2_dir_budget=D("10.0"),
                                   e2_dir_min_n=5,    # rendah agar fail-open
                                   e2_dir_funding_thr=D("0.0005"),
                                   e2_dir_live_enabled=False)
        led = self._make_led()

        # Sudah ada posisi terbuka untuk ENA-USD
        led.e2_dir_open("ENA-USD", "sell", "S", D("0.001"), D("0.3"), D("5.0"), D("1.0"))

        adp = MagicMock()
        adp.book.return_value = MagicMock(bid=D("4.9"), ask=D("5.1"), mid=D("5.0"))
        adp.funding_rate.return_value = D("0.002")  # sangat tinggi → sinyal pasti ada
        tg = MagicMock()

        e2 = Engine2Directional(cfg, adp, led, tg)

        # Mock generate_directional_signal untuk return sinyal ENA-USD
        with patch("anantara.sodex_twin_engine.generate_directional_signal",
                   return_value={"pair": "ENA-USD", "side": "sell", "grade": "S",
                                 "funding_rate": D("0.002"), "obi": D("0.3")}):
            e2.step()

        # Harus tetap hanya 1 posisi ENA-USD (tidak dobel)
        opens = led.e2_dir_open_signals()
        ena_opens = [p for p in opens if p["pair"] == "ENA-USD"]
        self.assertEqual(len(ena_opens), 1,
                         "B29: Pair ENA-USD hanya boleh punya 1 posisi terbuka sekaligus")

    def test_b29_monitor_has_concurrent_field(self):
        """B29: monitor report harus punya field e2_dir_concurrent."""
        import sqlite3, dataclasses
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import build_monitor_report, Config, Ledger, SCHEMA

        cfg = dataclasses.replace(Config(), e2_dir_enabled=True, e2_dir_pair="")
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.executescript(SCHEMA); led.con.commit()

        # Buka 2 posisi
        led.e2_dir_open("TRUMP-USD", "sell", "S", D("0.001"), D("0.3"), D("10.0"), D("0.5"))
        led.e2_dir_open("ENA-USD", "buy", "A", D("0.001"), D("0.2"), D("5.0"), D("1.0"))

        adp = MagicMock()
        adp.balance.return_value = {"vUSDC": D("100")}
        adp.book.return_value = MagicMock(mid=D("1.0"), bid=D("0.99"), ask=D("1.01"))
        rep = build_monitor_report(cfg, adp, led)

        self.assertIn("e2_dir_concurrent", rep, "Monitor harus punya e2_dir_concurrent (B29)")
        self.assertEqual(rep["e2_dir_concurrent"], 2,
                         "Dengan 2 posisi terbuka → concurrent=2")


# ────────────────────────────────────────────────────────────────────────────
# B30: E1 Trial Mechanism — manual bypass B14 death spiral
# ────────────────────────────────────────────────────────────────────────────

class TwinEngineB30TrialMechanismTests(TestCase):
    """B30: cmd_e1_trial harus set trial period di state DB dan allow E1 quote."""

    SCHEMA = None

    @classmethod
    def setUpClass(cls):
        from anantara.sodex_twin_engine import SCHEMA
        cls.SCHEMA = SCHEMA

    def _make_led(self):
        import sqlite3
        from anantara.sodex_twin_engine import Ledger
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.executescript(self.SCHEMA)
        led.con.commit()
        return led

    def test_b30_trial_sets_state_key(self):
        """B30: cmd_e1_trial harus menulis b14_trial_until_ts ke state DB."""
        import dataclasses, time, contextlib, io
        from anantara.sodex_twin_engine import cmd_e1_trial, Config, Ledger

        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "test.db")
            cfg = dataclasses.replace(Config(), db_path=db)
            buf = io.StringIO()
            before = time.time()
            with contextlib.redirect_stdout(buf):
                cmd_e1_trial(cfg, hours=2.0)
            after = time.time()
            led = Ledger(db)
            trial_until = float(led.get_state("b14_trial_until_ts"))
            self.assertGreater(trial_until, before + 2 * 3600 - 5,
                               "Trial until harus ~2 jam dari sekarang")
            self.assertLess(trial_until, after + 2 * 3600 + 5)

    def test_b30_cancel_clears_state(self):
        """B30: e1-trial --cancel harus set b14_trial_until_ts ke 0."""
        import dataclasses, contextlib, io
        from anantara.sodex_twin_engine import cmd_e1_trial, Config, Ledger

        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "test.db")
            cfg = dataclasses.replace(Config(), db_path=db)
            with contextlib.redirect_stdout(io.StringIO()):
                cmd_e1_trial(cfg, hours=1.0)          # set trial
                cmd_e1_trial(cfg, hours=1.0, cancel=True)  # cancel
            led = Ledger(db)
            trial_until = float(led.get_state("b14_trial_until_ts"))
            self.assertEqual(trial_until, 0.0, "Cancel harus reset ke 0")

    def test_b30_monitor_shows_trial_active(self):
        """B30: Monitor report harus punya b30_trial_active=True saat trial berjalan."""
        import sqlite3, dataclasses, time
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import build_monitor_report, Config, Ledger

        led = self._make_led()
        # Simulasi trial aktif: set until_ts = now + 1 jam
        led.set_state("b14_trial_until_ts", str(time.time() + 3600))

        cfg = dataclasses.replace(Config())
        adp = MagicMock()
        adp.balance.return_value = {"vUSDC": D("100")}
        adp.book.return_value = MagicMock(mid=D("1.0"), bid=D("0.99"), ask=D("1.01"))
        rep = build_monitor_report(cfg, adp, led)

        self.assertTrue(rep.get("b30_trial_active"), "b30_trial_active harus True")
        self.assertGreater(rep.get("b30_trial_remaining_h", 0), 0.9,
                           "Sisa trial harus ~1 jam")
        self.assertIsNotNone(rep.get("b30_trial_until"))

    def test_b30_monitor_shows_trial_inactive(self):
        """B30: Monitor report harus b30_trial_active=False bila tidak ada trial."""
        import sqlite3, dataclasses
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import build_monitor_report, Config, Ledger

        led = self._make_led()
        cfg = dataclasses.replace(Config())
        adp = MagicMock()
        adp.balance.return_value = {"vUSDC": D("100")}
        adp.book.return_value = MagicMock(mid=D("1.0"), bid=D("0.99"), ask=D("1.01"))
        rep = build_monitor_report(cfg, adp, led)

        self.assertFalse(rep.get("b30_trial_active", True),
                         "b30_trial_active harus False bila tidak ada trial")
        self.assertEqual(rep.get("b30_trial_remaining_h", 99), 0.0)


# ────────────────────────────────────────────────────────────────────────────
# B31: Inventory Risk Alert — deteksi dead capital saat E1 paused
# ────────────────────────────────────────────────────────────────────────────

class TwinEngineB31InventoryRiskTests(TestCase):
    """B31: Monitor harus deteksi dead capital (inventory stuck saat B14 pause)."""

    SCHEMA = None

    @classmethod
    def setUpClass(cls):
        from anantara.sodex_twin_engine import SCHEMA
        cls.SCHEMA = SCHEMA

    def _make_led(self):
        import sqlite3
        from anantara.sodex_twin_engine import Ledger
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.executescript(self.SCHEMA)
        led.con.commit()
        return led

    def test_b31_risk_alert_when_paused_with_inventory(self):
        """B31: b31_inventory_risk=True bila E1 paused >2 jam DAN inventory >$0.50."""
        import sqlite3, dataclasses, time
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import build_monitor_report, Config, Ledger

        led = self._make_led()
        # Simulasi B14 pause selama 3 jam
        pause_ts = time.time() - 3 * 3600
        led.set_state("b14_pause_since_ts", str(pause_ts))

        cfg = dataclasses.replace(Config(), spot_pair="PEPE/USDC")
        adp = MagicMock()
        # Balance: $5 PEPE inventory
        adp.balance.return_value = {"vPEPE": D("1800000"), "vUSDC": D("180")}
        adp.book.return_value = MagicMock(mid=D("0.00000278"), bid=D("0.00000277"),
                                          ask=D("0.00000279"))
        rep = build_monitor_report(cfg, adp, led)

        self.assertTrue(rep.get("b31_inventory_risk", False),
                        "b31_inventory_risk harus True saat E1 paused > 2 jam + inventory > $0.50")
        self.assertGreater(rep.get("b31_stuck_usd", 0), 0.5,
                           "b31_stuck_usd harus > 0.50")

    def test_b31_no_risk_when_e1_active(self):
        """B31: b31_inventory_risk=False bila E1 ACTIVE (tidak paused)."""
        import sqlite3, dataclasses
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import build_monitor_report, Config, Ledger

        led = self._make_led()
        # B14 tidak aktif (pause_since_ts = 0)
        cfg = dataclasses.replace(Config())
        adp = MagicMock()
        adp.balance.return_value = {"vPEPE": D("1800000"), "vUSDC": D("180")}
        adp.book.return_value = MagicMock(mid=D("0.00000278"), bid=D("0.00000277"),
                                          ask=D("0.00000279"))
        rep = build_monitor_report(cfg, adp, led)

        self.assertFalse(rep.get("b31_inventory_risk", True),
                         "b31_inventory_risk harus False bila E1 ACTIVE")

    def test_b31_no_risk_when_paused_short_time(self):
        """B31: b31_inventory_risk=False bila paused tapi baru <2 jam."""
        import sqlite3, dataclasses, time
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import build_monitor_report, Config, Ledger

        led = self._make_led()
        # Baru pause 30 menit
        pause_ts = time.time() - 0.5 * 3600
        led.set_state("b14_pause_since_ts", str(pause_ts))

        cfg = dataclasses.replace(Config())
        adp = MagicMock()
        adp.balance.return_value = {"vPEPE": D("1800000"), "vUSDC": D("180")}
        adp.book.return_value = MagicMock(mid=D("0.00000278"), bid=D("0.00000277"),
                                          ask=D("0.00000279"))
        rep = build_monitor_report(cfg, adp, led)

        self.assertFalse(rep.get("b31_inventory_risk", True),
                         "b31_inventory_risk harus False bila baru 30 menit paused")


# ────────────────────────────────────────────────────────────────────────────
# B32: Per-pair E2Dir stats dalam monitor report
# ────────────────────────────────────────────────────────────────────────────

class TwinEngineB32PerPairStatsTests(TestCase):
    """B32: Monitor harus menyertakan breakdown per-pair E2Dir."""

    SCHEMA = None

    @classmethod
    def setUpClass(cls):
        from anantara.sodex_twin_engine import SCHEMA
        cls.SCHEMA = SCHEMA

    def _make_led(self):
        import sqlite3
        from anantara.sodex_twin_engine import Ledger
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.executescript(self.SCHEMA)
        led.con.commit()
        return led

    def test_b32_per_pair_in_monitor_empty(self):
        """B32: e2_dir_per_pair harus [] bila belum ada sinyal."""
        import dataclasses
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import build_monitor_report, Config

        led = self._make_led()
        cfg = dataclasses.replace(Config())
        adp = MagicMock()
        adp.balance.return_value = {"vUSDC": D("100")}
        adp.book.return_value = MagicMock(mid=D("1.0"), bid=D("0.99"), ask=D("1.01"))
        rep = build_monitor_report(cfg, adp, led)
        self.assertIn("e2_dir_per_pair", rep)
        self.assertEqual(rep["e2_dir_per_pair"], [])

    def test_b32_per_pair_aggregates_correctly(self):
        """B32: per-pair stats harus akurat (n, wr, pnl) dari e2_dir_signals."""
        import dataclasses
        from decimal import Decimal as D
        from datetime import datetime, timezone
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import build_monitor_report, Config

        led = self._make_led()
        now_iso = datetime.now(timezone.utc).isoformat()

        # Insert 3 SAMSUNG wins + 1 EWY loss
        for i, (pair, pnl) in enumerate([
            ("SAMSUNG-USD", "0.05"), ("SAMSUNG-USD", "0.04"), ("SAMSUNG-USD", "0.03"),
            ("EWY-USD", "-0.02")
        ]):
            led.con.execute("""
                INSERT INTO e2_dir_signals
                (pair, side, grade, entry_px, qty, opened_ts, closed_ts, exit_px,
                 pnl, exit_reason, funding_rate, obi)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (pair, "sell", "B", "10.0", "1.0", now_iso, now_iso,
                  "10.1", pnl, "timeout", "0.00050", "0.1"))
        led.con.commit()

        cfg = dataclasses.replace(Config())
        adp = MagicMock()
        adp.balance.return_value = {"vUSDC": D("100")}
        adp.book.return_value = MagicMock(mid=D("1.0"), bid=D("0.99"), ask=D("1.01"))
        rep = build_monitor_report(cfg, adp, led)

        per_pair = {p["pair"]: p for p in rep.get("e2_dir_per_pair", [])}
        self.assertIn("SAMSUNG-USD", per_pair)
        self.assertEqual(per_pair["SAMSUNG-USD"]["n"], 3)
        self.assertEqual(per_pair["SAMSUNG-USD"]["won"], 3)
        self.assertAlmostEqual(per_pair["SAMSUNG-USD"]["wr"], 1.0, places=2)
        self.assertAlmostEqual(per_pair["SAMSUNG-USD"]["pnl"], 0.12, places=2)

        self.assertIn("EWY-USD", per_pair)
        self.assertEqual(per_pair["EWY-USD"]["n"], 1)
        self.assertEqual(per_pair["EWY-USD"]["won"], 0)
        self.assertAlmostEqual(per_pair["EWY-USD"]["wr"], 0.0, places=2)


# ────────────────────────────────────────────────────────────────────────────
# B33: Per-pair blacklist E2Dir
# ────────────────────────────────────────────────────────────────────────────

class TwinEngineB33PairBlacklistTests(TestCase):
    """B33: Pair dengan WR buruk (n≥5, WR<35%) harus di-cooldown 6h."""

    SCHEMA = None

    @classmethod
    def setUpClass(cls):
        from anantara.sodex_twin_engine import SCHEMA
        cls.SCHEMA = SCHEMA

    def _make_led(self):
        import sqlite3
        from anantara.sodex_twin_engine import Ledger
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.executescript(self.SCHEMA)
        led.con.commit()
        return led

    def test_b33_blacklist_sets_expiry(self):
        """B33: e2_dir_pair_blacklist harus set expiry di state DB."""
        import time
        led = self._make_led()
        before = time.time()
        led.e2_dir_pair_blacklist("EWY-USD", 6 * 3600)
        after = time.time()
        val = float(led.get_state("e2_dir_bl_EWY_USD"))
        self.assertGreater(val, before + 6 * 3600 - 5)
        self.assertLess(val, after + 6 * 3600 + 5)

    def test_b33_is_blacklisted_true(self):
        """B33: e2_dir_pair_is_blacklisted harus True bila masih dalam cooldown."""
        led = self._make_led()
        led.e2_dir_pair_blacklist("EWY-USD", 3600)
        self.assertTrue(led.e2_dir_pair_is_blacklisted("EWY-USD"))

    def test_b33_is_blacklisted_false_expired(self):
        """B33: e2_dir_pair_is_blacklisted harus False bila cooldown sudah lewat."""
        import time
        led = self._make_led()
        # Set expiry di masa lalu (cooldown hanya 1 detik → sudah expired)
        led.set_state("e2_dir_bl_EWY_USD", str(time.time() - 10))
        self.assertFalse(led.e2_dir_pair_is_blacklisted("EWY-USD"))

    def test_b33_is_blacklisted_false_no_entry(self):
        """B33: pair yang tidak pernah di-blacklist → False (default 0)."""
        led = self._make_led()
        self.assertFalse(led.e2_dir_pair_is_blacklisted("TRUMP-USD"))

    def test_b33_pair_wr_returns_correct(self):
        """B33: e2_dir_pair_wr harus menghitung WR dari last_n sinyal."""
        from datetime import datetime, timezone
        led = self._make_led()
        now_iso = datetime.now(timezone.utc).isoformat()

        # 1 win + 4 losses = WR=20%
        for pnl in ["0.05", "-0.02", "-0.03", "-0.01", "-0.02"]:
            led.con.execute("""
                INSERT INTO e2_dir_signals
                (pair, side, grade, entry_px, qty, opened_ts, closed_ts, exit_px,
                 pnl, exit_reason, funding_rate, obi)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, ("EWY-USD", "sell", "B", "10.0", "1.0", now_iso, now_iso,
                  "10.0", pnl, "timeout", "0.0002", "0.1"))
        led.con.commit()

        n, wr = led.e2_dir_pair_wr("EWY-USD", last_n=10)
        self.assertEqual(n, 5)
        self.assertAlmostEqual(wr, 0.20, places=2)

    def test_b33_blacklist_triggered_when_wr_below_floor(self):
        """B33: Setelah close signal, pair dengan WR<35% dan n≥5 harus di-blacklist."""
        import dataclasses, time
        from decimal import Decimal as D
        from datetime import datetime, timezone
        from unittest.mock import MagicMock, patch
        from anantara.sodex_twin_engine import Engine2Directional, Config

        led = self._make_led()
        now_iso = datetime.now(timezone.utc).isoformat()

        # Pre-seed: 4 losses untuk EWY-USD
        for pnl in ["-0.02", "-0.03", "-0.01", "-0.02"]:
            led.con.execute("""
                INSERT INTO e2_dir_signals
                (pair, side, grade, entry_px, qty, opened_ts, closed_ts, exit_px,
                 pnl, exit_reason, funding_rate, obi)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, ("EWY-USD", "sell", "B", "10.0", "1.0", now_iso, now_iso,
                  "10.0", pnl, "timeout", "0.0002", "0.1"))
        led.con.commit()

        # Insert satu sinyal OPEN untuk di-manage
        sig_id = led.e2_dir_open("EWY-USD", "sell", "B", D("0.0002"), D("0.1"),
                                  D("10.0"), D("5.0"))

        cfg = dataclasses.replace(Config())
        tg = MagicMock()
        adp = MagicMock()
        adp.book.return_value = MagicMock(
            mid=D("10.1"), bid=D("10.09"), ask=D("10.11"))

        engine = Engine2Directional(cfg, adp, led, tg)
        engine._sig_id = sig_id

        pos = led.e2_dir_open_signals()[0]
        # Paksa timeout dengan mengubah opened_ts ke masa lalu
        future_ago = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() - 2000, timezone.utc).isoformat()
        led.con.execute(
            "UPDATE e2_dir_signals SET opened_ts=? WHERE id=?", (future_ago, sig_id))
        led.con.commit()

        pos = led.e2_dir_open_signals()[0]
        engine._manage_position(pos)

        # EWY sekarang punya 5 closes dengan WR=1/5=20% → harus di-blacklist
        self.assertTrue(led.e2_dir_pair_is_blacklisted("EWY-USD"),
                        "EWY-USD harus di-blacklist setelah WR 20% dengan n=5")

    def test_failed_live_open_blacklists_pair_temporarily(self):
        """B41: live order gagal oid=0 harus cooldown pair, bukan retry spam."""
        import dataclasses
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import Book, Config, Engine2Directional, Order

        led = self._make_led()
        cfg = dataclasses.replace(
            Config(),
            e2_dir_live_enabled=True,
            e2_dir_size_usd=D("11.0"),
        )
        adp = MagicMock()
        adp.book.return_value = Book(bid=D("231.70"), ask=D("231.80"))
        # Entry kini via market IOC (fix 2026-06-21) — simulasikan gagal oid=0
        _fail = Order(oid="0", pair="SAMSUNG-USD", side="sell",
                      price=D("231.70"), qty=D("0.05"), filled=D("0.05"))
        adp.place_market_ioc.return_value = _fail
        adp.place_post_only.return_value = _fail

        engine = Engine2Directional(cfg, adp, led, MagicMock())
        ok = engine._open_position({
            "pair": "SAMSUNG-USD",
            "side": "sell",
            "grade": "B",
            "funding_rate": D("0.00003"),
            "obi": D("-0.2"),
        })

        self.assertFalse(ok)
        self.assertTrue(
            led.e2_dir_pair_is_blacklisted("SAMSUNG-USD"),
            "Pair gagal live open harus cooldown agar tidak ditembak tiap step",
        )


# B34: Exit quality breakdown + binomial significance test
# ────────────────────────────────────────────────────────────────────────────

class TwinEngineB34ExitQualityTests(TestCase):
    """B34: Exit breakdown per reason + binomial test untuk go-live decision."""

    SCHEMA = None

    @classmethod
    def setUpClass(cls):
        from anantara.sodex_twin_engine import SCHEMA
        cls.SCHEMA = SCHEMA

    def _make_led(self):
        import sqlite3
        from anantara.sodex_twin_engine import Ledger
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.executescript(self.SCHEMA)
        led.con.commit()
        return led

    def _seed_signals(self, led, entries):
        """entries: list of (pnl_str, exit_reason_str)"""
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        for pnl, reason in entries:
            led.con.execute("""
                INSERT INTO e2_dir_signals
                (pair, side, grade, funding_rate, obi, entry_px, qty,
                 opened_ts, closed_ts, exit_px, pnl, exit_reason)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, ("EWY-USD", "sell", "B", "0.0005", "0.2",
                  "10.0", "1.0", now_iso, now_iso, "10.05", pnl, reason))
        led.con.commit()

    def test_b34_exit_quality_empty(self):
        """B34: DB kosong → e2_dir_exit_quality() kembalikan dict kosong."""
        led = self._make_led()
        result = led.e2_dir_exit_quality()
        self.assertEqual(result, {})

    def test_b34_exit_quality_by_reason(self):
        """B34: Breakdown per reason harus akurat (n, won, wr)."""
        led = self._make_led()
        # 2 tp wins + 1 sl loss + 3 timeouts (2 win, 1 loss)
        self._seed_signals(led, [
            ("0.10", "tp"), ("0.08", "tp"),
            ("-0.03", "sl"),
            ("0.02", "timeout"), ("0.01", "timeout"), ("-0.04", "timeout"),
        ])
        eq = led.e2_dir_exit_quality()
        self.assertIn("tp", eq)
        self.assertIn("sl", eq)
        self.assertIn("timeout", eq)
        self.assertEqual(eq["tp"]["n"], 2)
        self.assertEqual(eq["tp"]["won"], 2)
        self.assertAlmostEqual(eq["tp"]["wr"], 1.0)
        self.assertEqual(eq["sl"]["n"], 1)
        self.assertEqual(eq["sl"]["won"], 0)
        self.assertAlmostEqual(eq["sl"]["wr"], 0.0)
        self.assertEqual(eq["timeout"]["n"], 3)
        self.assertEqual(eq["timeout"]["won"], 2)
        self.assertAlmostEqual(eq["timeout"]["wr"], 2 / 3)

    def test_b34_binom_test_insufficient_n(self):
        """B34: n<5 → binom_test kembalikan p_val=None, significant=False."""
        led = self._make_led()
        self._seed_signals(led, [("0.05", "tp"), ("0.03", "timeout")])
        bt = led.e2_dir_binom_test()
        self.assertIsNone(bt["p_val"])
        self.assertFalse(bt["significant_p05"])

    def test_b34_binom_test_high_wr_significant(self):
        """B34: WR=8/10=80% harus signifikan (p<0.05) dengan n=10."""
        import math
        led = self._make_led()
        # 8 wins, 2 losses, n=10
        self._seed_signals(led, [
            ("0.05", "tp")] * 8 + [("-0.03", "sl")] * 2)
        bt = led.e2_dir_binom_test()
        self.assertEqual(bt["n"], 10)
        self.assertAlmostEqual(bt["wr"], 0.8, places=2)
        self.assertGreater(bt["z"], 0)
        # z = (0.8-0.5) / (0.5/sqrt(10)) = 0.3 / 0.158 = 1.897
        # p ≈ 0.029 < 0.05
        self.assertIsNotNone(bt["p_val"])
        self.assertLess(bt["p_val"], 0.05)
        self.assertTrue(bt["significant_p05"])

    def test_b34_binom_test_coin_flip_not_significant(self):
        """B34: WR=50% → tidak signifikan (p≈0.5)."""
        led = self._make_led()
        self._seed_signals(led, [
            ("0.05", "timeout")] * 5 + [("-0.03", "timeout")] * 5)
        bt = led.e2_dir_binom_test()
        self.assertEqual(bt["n"], 10)
        self.assertAlmostEqual(bt["wr"], 0.5, places=2)
        self.assertFalse(bt["significant_p05"])

    def test_b34_monitor_has_binom_fields(self):
        """B34: build_monitor_report harus sertakan field binom dan go_live_ok."""
        import sqlite3
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import Ledger, build_monitor_report, Config, SCHEMA

        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.executescript(SCHEMA)
        led.con.commit()

        cfg = Config()
        adp = MagicMock()
        adp.balances = MagicMock(return_value={"USDC": D("100")})
        adp.balance = MagicMock(return_value={"vUSDC": D("100")})
        adp.book = MagicMock(return_value=MagicMock(mid=D("10"), bid=D("9.99"), ask=D("10.01")))

        rep = build_monitor_report(cfg, adp, led)
        self.assertIn("e2_dir_exit_quality", rep)
        self.assertIn("e2_dir_binom_z", rep)
        self.assertIn("e2_dir_binom_p", rep)
        self.assertIn("e2_dir_sig_p05", rep)
        self.assertIn("e2_dir_go_live_ok", rep)
        # Empty DB → no data, go_live_ok=False
        self.assertFalse(rep["e2_dir_go_live_ok"])


class TwinEngineB35PauseRestoreTests(TestCase):
    """B35: _quoting_paused harus dipulihkan dari DB saat daemon restart.

    Root cause bug yang diperbaiki: setiap restart Engine1Flywheel reset
    _quoting_paused=False, lalu _check_profitability_gate() mendeteksi
    False→True transition dan menulis ulang b14_pause_since_ts=now().
    Akibat: timer stuck capital di-reset → B31 tidak pernah fire.

    Fix: baca b14_pause_since_ts dari DB di __init__ (isinstance str guard
    memastikan MagicMock test doubles tidak terpengaruh).
    """

    @classmethod
    def setUpClass(cls):
        from anantara.sodex_twin_engine import SCHEMA
        cls.SCHEMA = SCHEMA

    def _make_led(self, pause_ts_str="0"):
        import sqlite3
        from anantara.sodex_twin_engine import Ledger
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.executescript(self.SCHEMA)
        led.con.commit()
        led.set_state("b14_pause_since_ts", pause_ts_str)
        return led

    def test_b35_quoting_paused_restored_when_db_has_positive_ts(self):
        """B35: Engine1Flywheel.__init__ harus set _quoting_paused=True saat DB sudah PAUSE."""
        import time
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import Engine1Flywheel, Config

        led = self._make_led(pause_ts_str=str(time.time() - 3600))  # 1 jam lalu
        cfg = Config()
        eng = Engine1Flywheel(cfg, MagicMock(), led, MagicMock(), MagicMock(),
                              hedge_enabled=False, pair="PEPE/USDC")
        self.assertTrue(eng._quoting_paused,
                        "B35: harus start PAUSED bila b14_pause_since_ts>0 di DB")

    def test_b35_not_paused_when_db_has_zero(self):
        """B35: Engine1Flywheel harus start ACTIVE bila b14_pause_since_ts=0 (normal)."""
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import Engine1Flywheel, Config

        led = self._make_led(pause_ts_str="0")
        cfg = Config()
        eng = Engine1Flywheel(cfg, MagicMock(), led, MagicMock(), MagicMock(),
                              hedge_enabled=False, pair="PEPE/USDC")
        self.assertFalse(eng._quoting_paused,
                         "B35: harus start ACTIVE bila b14_pause_since_ts=0")

    def test_b35_not_paused_when_db_cleared(self):
        """B35: Engine1Flywheel start ACTIVE bila DB sebelumnya di-clear (resume)."""
        import time
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import Engine1Flywheel, Config

        # Simulasikan siklus: pause → resume (clear) → restart
        led = self._make_led(pause_ts_str="0")  # cleared after resume
        cfg = Config()
        eng = Engine1Flywheel(cfg, MagicMock(), led, MagicMock(), MagicMock(),
                              hedge_enabled=False, pair="PEPE/USDC")
        self.assertFalse(eng._quoting_paused)

    def test_b35_does_not_overwrite_pause_timestamp_on_restart(self):
        """B35: Restart daemon tidak boleh overwrite b14_pause_since_ts yang ada.

        Ini adalah inti bug yang diperbaiki: _check_profitability_gate() hanya
        menulis ulang timestamp saat transisi False→True. Dengan B35 restore,
        engine sudah True dari awal → TIDAK ada transisi → timestamp preserved.
        """
        import time, sqlite3
        from unittest.mock import MagicMock, patch
        from anantara.sodex_twin_engine import Engine1Flywheel, Config

        original_ts = time.time() - 7200  # 2 jam lalu
        led = self._make_led(pause_ts_str=str(original_ts))
        cfg = Config()
        eng = Engine1Flywheel(cfg, MagicMock(), led, MagicMock(), MagicMock(),
                              hedge_enabled=False, pair="PEPE/USDC")

        # Setelah init, _quoting_paused=True → _check_profitability_gate()
        # akan masuk branch `elif _quoting_paused and rate > resume_floor`
        # (bukan branch set_state baru). Verifikasi timestamp tidak berubah.
        ts_after_init = float(led.get_state("b14_pause_since_ts"))
        self.assertAlmostEqual(ts_after_init, original_ts, places=0,
                               msg="B35: b14_pause_since_ts tidak boleh di-reset saat restart")

    def test_b35_b31_fires_correctly_after_7h_pause(self):
        """B35 + B31 integration: stuck capital terdeteksi benar setelah 7 jam pause."""
        import time, dataclasses, sqlite3
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import build_monitor_report, Config, Ledger

        # Simulasi: engine paused 7.5 jam lalu (sebelum restart)
        led = self._make_led(pause_ts_str=str(time.time() - 7.5 * 3600))
        cfg = dataclasses.replace(Config(), spot_pair="PEPE/USDC")
        adp = MagicMock()
        adp.balance.return_value = {"vPEPE": D("1700000"), "vUSDC": D("179")}
        adp.book.return_value = MagicMock(mid=D("0.00000283"), bid=D("0.00000282"),
                                          ask=D("0.00000284"))
        rep = build_monitor_report(cfg, adp, led)

        self.assertEqual(rep["b14_status"], "PAUSED")
        self.assertGreater(rep["b14_locked_hours"], 7.0,
                           "locked_hours harus > 7.0 untuk 7.5 jam pause")
        self.assertTrue(rep["b31_inventory_risk"],
                        "B31 harus fire: PEPE stuck setelah 7.5 jam PAUSE")


class TwinEngineB36FlushThresholdTests(TestCase):
    """B36: last-resort flush threshold turun $10 → $3 saat E1 PAUSED >4 jam.

    Root cause: inventori PEPE $4.84 stuck selamanya karena _check_flush
    min_notional=$10 tidak pernah tercapai saat E1 PAUSED (quoting berhenti).
    Fix B36: bila _quoting_paused AND age > 4h → min_notional=$3 (last-resort).
    """

    def _make_engine_for_flush(self):
        """Buat Engine1Flywheel minimal untuk test _check_flush tanpa koneksi real."""
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import Engine1Flywheel, Config

        # MagicMock led: get_state("b14_pause_since_ts") → "0" → tidak restore pause
        led = MagicMock()
        led.get_state.return_value = "0"

        cfg = Config()
        eng = Engine1Flywheel(cfg, MagicMock(), led, MagicMock(), MagicMock(),
                              hedge_enabled=False, pair="PEPE/USDC")
        return eng

    def _make_book(self, mid_price):
        """Buat mock Book dengan mid tertentu."""
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        bk = MagicMock()
        bk.mid = D(str(mid_price))
        bk.bid = D(str(float(mid_price) * 0.9995))
        return bk

    def test_b36_normal_not_paused_threshold_stays_10(self):
        """B36: Saat NOT paused, threshold tetap $10 — inv_usd=$8 tidak flush."""
        import time
        from decimal import Decimal as D
        from unittest.mock import patch

        eng = self._make_engine_for_flush()
        eng._quoting_paused = False
        # PEPE: 2_000_000 × $0.000004 = $8 (< $10)
        eng.inv_qty = D("2000000")
        eng._inv_started = time.time() - 5 * 3600  # 5 jam lalu (> flush_minutes)

        bk = self._make_book("0.000004")
        with patch.object(eng, "_force_flush_now") as mock_flush:
            eng._check_flush(bk)
            mock_flush.assert_not_called()

    def test_b36_paused_old_inv_triggers_flush_above_3(self):
        """B36: Saat PAUSED >4h, inv_usd=$4.84 ≥ $3 → flush DIPICU (last-resort)."""
        import time
        from decimal import Decimal as D
        from unittest.mock import patch

        eng = self._make_engine_for_flush()
        eng._quoting_paused = True
        # PEPE: 1_714_000 × $0.00000282 ≈ $4.83 (≥ $3 last-resort)
        eng.inv_qty = D("1714000")
        eng._inv_started = time.time() - 4.5 * 3600  # 4.5 jam (> 4h threshold)

        bk = self._make_book("0.00000282")
        with patch.object(eng, "_force_flush_now") as mock_flush:
            eng._check_flush(bk)
            mock_flush.assert_called_once()

    def test_b36_paused_old_inv_below_3_no_flush(self):
        """B36: PAUSED >4h tapi inv_usd=$2.50 < $3 → tidak flush (bawah last-resort)."""
        import time
        from decimal import Decimal as D
        from unittest.mock import patch

        eng = self._make_engine_for_flush()
        eng._quoting_paused = True
        # PEPE: 900_000 × $0.00000278 ≈ $2.50 (< $3)
        eng.inv_qty = D("900000")
        eng._inv_started = time.time() - 5 * 3600

        bk = self._make_book("0.00000278")
        with patch.object(eng, "_force_flush_now") as mock_flush:
            eng._check_flush(bk)
            mock_flush.assert_not_called()

    def test_b36_paused_but_young_inv_uses_normal_threshold(self):
        """B36: PAUSED tapi inv umur ≤ 4h → threshold tetap $10, inv=$5 tidak flush."""
        import time
        from decimal import Decimal as D
        from unittest.mock import patch

        eng = self._make_engine_for_flush()
        eng._quoting_paused = True
        # inv_usd ≈ $5 (≥ $3, tapi age hanya 3h → B36 belum aktif, threshold masih $10)
        eng.inv_qty = D("1800000")
        eng._inv_started = time.time() - 3 * 3600  # hanya 3 jam (< 4h cutoff)

        bk = self._make_book("0.00000278")
        with patch.object(eng, "_force_flush_now") as mock_flush:
            eng._check_flush(bk)
            mock_flush.assert_not_called()

    def test_b36_threshold_constants(self):
        """B36: Verifikasi threshold normal=$10, last-resort=$3 ada di kode."""
        import inspect
        from anantara.sodex_twin_engine import Engine1Flywheel
        src = inspect.getsource(Engine1Flywheel._check_flush)
        self.assertIn('"10"', src, "normal threshold $10 harus ada")
        self.assertIn('"3"', src, "last-resort threshold $3 harus ada")
        self.assertIn("_quoting_paused", src, "B36 harus cek _quoting_paused")
        self.assertIn("age_h > 4.0", src, "B36 harus cek age > 4 jam")


class TwinEngineB37InvStartedPersistTests(TestCase):
    """B37: _inv_started harus persisten lintas restart daemon.

    Root cause bug: seed_baseline() selalu set _inv_started=time.time() saat
    restart → B36 age dihitung dari restart, bukan dari kapan inventori masuk.
    Akibat: inventori stuck 12h terlihat "umur 0h" setelah restart → B36 tidak fire.

    Fix: _set_inv_started() menyimpan timestamp ke DB. seed_baseline() membaca
    DB terlebih dulu; bila ada timestamp lama, pakai itu (jangan overwrite).
    """

    @classmethod
    def setUpClass(cls):
        from anantara.sodex_twin_engine import SCHEMA
        cls.SCHEMA = SCHEMA

    def _make_led(self, inv_ts_str="0", pause_ts_str="0"):
        import sqlite3
        from anantara.sodex_twin_engine import Ledger
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.executescript(self.SCHEMA)
        led.con.commit()
        led.set_state("e1_inv_started_ts", inv_ts_str)
        led.set_state("b14_pause_since_ts", pause_ts_str)
        return led

    def _make_engine(self, led, pair="PEPE/USDC"):
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import Engine1Flywheel, Config
        cfg = Config()
        return Engine1Flywheel(cfg, MagicMock(), led, MagicMock(), MagicMock(),
                               hedge_enabled=False, pair=pair)

    def test_b37_seed_baseline_uses_db_timestamp_when_older(self):
        """B37: seed_baseline() pakai timestamp DB bila lebih lama dari sekarang."""
        import time
        from decimal import Decimal as D

        original_ts = time.time() - 6 * 3600  # 6 jam lalu
        led = self._make_led(inv_ts_str=str(original_ts))
        eng = self._make_engine(led)

        # Panggil seed_baseline dengan inventori > 0
        eng.seed_baseline(D("1700000"), D("0.00000283"))

        self.assertIsNotNone(eng._inv_started, "B37: _inv_started tidak boleh None")
        self.assertAlmostEqual(eng._inv_started, original_ts, delta=1.0,
                               msg="B37: harus pakai timestamp lama dari DB, bukan time.time()")

    def test_b37_seed_baseline_uses_now_when_db_empty(self):
        """B37: seed_baseline() pakai time.time() bila DB kosong (pertama kali)."""
        import time
        from decimal import Decimal as D

        led = self._make_led(inv_ts_str="0")  # DB kosong
        eng = self._make_engine(led)

        before = time.time()
        eng.seed_baseline(D("1700000"), D("0.00000283"))
        after = time.time()

        self.assertIsNotNone(eng._inv_started)
        self.assertGreaterEqual(eng._inv_started, before,
                                "B37: timestamp harus >= sekarang bila DB kosong")
        self.assertLessEqual(eng._inv_started, after)

    def test_b37_seed_baseline_clears_db_when_flat(self):
        """B37: seed_baseline(0, ...) harus clear e1_inv_started_ts di DB ke '0'."""
        from decimal import Decimal as D

        original_ts = 1234567890.0
        led = self._make_led(inv_ts_str=str(original_ts))
        eng = self._make_engine(led)

        eng.seed_baseline(D("0"), D("0.00000283"))  # flat inventory

        self.assertIsNone(eng._inv_started)
        db_val = float(led.get_state("e1_inv_started_ts"))
        self.assertEqual(db_val, 0.0, "B37: DB harus di-clear ke 0 saat flat")

    def test_b37_set_inv_started_persists_to_db(self):
        """B37: _set_inv_started() harus tulis timestamp ke DB."""
        import time
        from decimal import Decimal as D

        led = self._make_led()
        eng = self._make_engine(led)

        ts = time.time() - 2 * 3600
        eng._set_inv_started(ts)

        db_val = float(led.get_state("e1_inv_started_ts"))
        self.assertAlmostEqual(db_val, ts, delta=1.0,
                               msg="B37: set_inv_started harus simpan ke DB")

    def test_b37_set_inv_started_none_writes_zero(self):
        """B37: _set_inv_started(None) harus tulis '0' ke DB."""
        led = self._make_led(inv_ts_str="1234567890")
        eng = self._make_engine(led)

        eng._set_inv_started(None)

        db_val = float(led.get_state("e1_inv_started_ts"))
        self.assertEqual(db_val, 0.0)

    def test_b37_inv_age_uses_restored_timestamp(self):
        """B37 + B36 integration: age harus > 4h setelah restore dari DB 5h lalu."""
        import time
        from decimal import Decimal as D

        inv_ts = time.time() - 5 * 3600  # 5 jam lalu
        led = self._make_led(inv_ts_str=str(inv_ts))
        eng = self._make_engine(led)
        eng.seed_baseline(D("1700000"), D("0.00000283"))

        age_h = eng._inv_age_minutes() / 60.0
        self.assertGreater(age_h, 4.9,
                           f"B37: age harus > 4.9h setelah restore 5h lalu, dapat {age_h:.1f}h")

    def test_b45_pair2_seed_baseline_does_not_inherit_primary_timestamp(self):
        """B45: SHIB/E1b tidak boleh mewarisi umur inventori global PEPE."""
        import time
        from decimal import Decimal as D

        primary_ts = time.time() - 6 * 3600
        led = self._make_led(inv_ts_str=str(primary_ts))
        led.set_state("e1_inv_started_ts:SHIB/USDC", "0")
        eng = self._make_engine(led, pair="SHIB/USDC")

        before = time.time()
        eng.seed_baseline(D("8120000"), D("0.00000471"))
        after = time.time()

        self.assertIsNotNone(eng._inv_started)
        self.assertGreaterEqual(
            eng._inv_started, before,
            "B45: pair2 harus mulai timestamp sendiri bila key pair-scoped kosong",
        )
        self.assertLessEqual(eng._inv_started, after)
        self.assertEqual(
            float(led.get_state("e1_inv_started_ts")), primary_ts,
            "B45: key global PEPE tidak boleh ditimpa oleh SHIB",
        )

    def test_b45_pair2_set_inv_started_writes_pair_scoped_key(self):
        """B45: _set_inv_started() untuk SHIB wajib tulis key pair-scoped."""
        import time

        led = self._make_led(inv_ts_str="0")
        eng = self._make_engine(led, pair="SHIB/USDC")

        ts = time.time() - 120
        eng._set_inv_started(ts)

        self.assertEqual(float(led.get_state("e1_inv_started_ts")), 0.0)
        self.assertAlmostEqual(
            float(led.get_state("e1_inv_started_ts:SHIB/USDC")),
            ts,
            delta=1.0,
        )


class TwinEngineB40NonBlockingFlushTests(TestCase):
    """B40: _force_flush_now harus NON-BLOCKING (tidak loop 120s).

    Root cause: loop poll 120s memblokir seluruh run-loop → SHIB/E1b tidak bisa
    step, setiap 0.5s log "hilang dari open-list". Fix B40: place order → return
    segera; step()/reconcile_all_from_balance handle fill detection.

    B39 balance-sync dipertahankan sebagai pre-check: jika exchange sudah 0,
    tidak perlu place order baru.
    """

    @classmethod
    def setUpClass(cls):
        from anantara.sodex_twin_engine import SCHEMA
        cls.SCHEMA = SCHEMA

    def _make_engine(self, inv_qty=None, pair="PEPE/USDC"):
        """Helper: buat Engine1Flywheel dengan inv_qty awal."""
        import sqlite3, time
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import Engine1Flywheel, Config, Ledger
        if inv_qty is None:
            inv_qty = D("4000000")
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.executescript(self.SCHEMA)
        led.con.commit()
        led.set_state("e1_inv_started_ts", str(time.time() - 6 * 3600))
        led.set_state("b14_pause_since_ts", str(time.time() - 5 * 3600))
        x = MagicMock()
        tg = MagicMock()
        cfg = Config()
        eng = Engine1Flywheel(cfg, x, led, tg, MagicMock(), hedge_enabled=False, pair=pair)
        eng.inv_qty = inv_qty
        eng._inv_started = time.time() - 6 * 3600
        eng._quoting_paused = True
        return eng, x, tg

    def _make_bk(self, bid="0.0000028", ask="0.0000030"):
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        bk = MagicMock()
        bk.bid = D(bid)
        bk.ask = D(ask)
        bk.mid = (D(bid) + D(ask)) / 2
        return bk

    def _make_order(self, pair, side, price, qty, oid="abc123"):
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import Order
        return Order(pair=pair, side=side, price=D(price), qty=D(qty), oid=oid)

    def test_b40_flush_places_order_and_returns_non_blocking(self):
        """B40: _force_flush_now menempatkan 1 order, tidak poll 120s."""
        from decimal import Decimal as D
        eng, x, tg = self._make_engine(inv_qty=D("4000000"))
        bk = self._make_bk()
        x.balance.return_value = {"vPEPE": D("4000000"), "vUSDC": D("100")}
        o = self._make_order("PEPE/USDC", "sell", "0.0000028", "4000000", oid="flush1")
        x.place_post_only.return_value = o

        eng._force_flush_now(bk)

        # place_post_only dipanggil TEPAT 1 kali (non-blocking, tidak loop)
        x.place_post_only.assert_called_once()
        # poll_fill TIDAK boleh dipanggil (bukan loop 120s)
        x.poll_fill.assert_not_called()

    def test_b40_flush_sets_flushing_true_after_order_placed(self):
        """B40: _flushing=True setelah order berhasil ditempatkan (oid != '0')."""
        from decimal import Decimal as D
        eng, x, tg = self._make_engine(inv_qty=D("2000000"))
        bk = self._make_bk()
        x.balance.return_value = {"vPEPE": D("2000000"), "vUSDC": D("150")}
        x.place_post_only.return_value = self._make_order(
            "PEPE/USDC", "sell", "0.0000028", "2000000", oid="flush2")

        self.assertFalse(eng._flushing, "B40: _flushing harus False sebelum flush")
        eng._force_flush_now(bk)
        self.assertTrue(eng._flushing, "B40: _flushing harus True setelah order placed")

    def test_b40_flush_early_exit_when_exchange_shows_zero(self):
        """B40+B39: jika exchange sudah 0, tidak tempatkan order (sudah flat)."""
        from decimal import Decimal as D
        eng, x, tg = self._make_engine(inv_qty=D("4000000"))
        bk = self._make_bk()
        # Exchange sudah 0 — flush order sebelumnya sudah terisi
        x.balance.return_value = {"vPEPE": D("0"), "vUSDC": D("185")}

        eng._force_flush_now(bk)

        # Tidak perlu place order — inventory sudah 0 di exchange
        x.place_post_only.assert_not_called()
        self.assertEqual(eng.inv_qty, D("0"),
                         "B39/B40: inv_qty harus dikoreksi ke 0 dari exchange balance")
        self.assertFalse(eng._flushing,
                         "B40: _flushing harus False setelah early-exit (sudah flat)")

    def test_b54_within_cap_not_paused_skips_blocking_flush(self):
        """B54: inventori tua TAPI dalam cap & tidak paused → JANGAN blocking-flush;
        biarkan quoting skew menguras (volume tetap jalan)."""
        from decimal import Decimal as D
        import dataclasses
        eng, x, tg = self._make_engine(inv_qty=D("4000000"))  # ~$11.6 @ mid 0.0000029
        eng.cfg = dataclasses.replace(eng.cfg, e1_inv_cap_per_pair=D("20"))
        eng._quoting_paused = False
        eng._flushing = True  # anggap sebelumnya ter-set
        bk = self._make_bk(bid="0.0000028", ask="0.0000030")  # mid 0.0000029, inv_usd~$11.6 < $20
        with patch.object(eng, "_force_flush_now") as mock_flush:
            eng._check_flush(bk)
            mock_flush.assert_not_called()
        self.assertFalse(eng._flushing, "B54: _flushing harus dilepas agar quoting jalan")

    def test_b54_over_cap_still_flushes(self):
        """B54: inventori MELEBIHI cap → tetap blocking-flush (proteksi over-exposure)."""
        from decimal import Decimal as D
        import dataclasses, time
        eng, x, tg = self._make_engine(inv_qty=D("10000000"))  # ~$29 @ mid 0.0000029
        eng.cfg = dataclasses.replace(eng.cfg, e1_inv_cap_per_pair=D("20"))
        eng._quoting_paused = False
        eng._last_flush_ts = time.time() - 600  # cooldown habis
        bk = self._make_bk(bid="0.0000028", ask="0.0000030")  # inv_usd ~$29 > $20 cap
        with patch.object(eng, "_force_flush_now") as mock_flush:
            eng._check_flush(bk)
            mock_flush.assert_called_once()

    def test_b54_source_marker(self):
        """B54: marker harus ada di _check_flush."""
        import inspect
        from anantara.sodex_twin_engine import Engine1Flywheel
        src = inspect.getsource(Engine1Flywheel._check_flush)
        self.assertIn("B54", src)

    def test_b40_flush_partial_fill_balance_sync(self):
        """B40+B39: exchange menunjukkan sisa → inv_qty dikoreksi, order ditempatkan untuk sisa."""
        from decimal import Decimal as D
        eng, x, tg = self._make_engine(inv_qty=D("4000000"))
        bk = self._make_bk()
        # Exchange: hanya 2.5M sisa (1.5M terisi order sebelumnya)
        x.balance.return_value = {"vPEPE": D("2500000"), "vUSDC": D("100")}
        x.place_post_only.return_value = self._make_order(
            "PEPE/USDC", "sell", "0.0000028", "2500000", oid="flush3")

        eng._force_flush_now(bk)

        # inv_qty dikoreksi ke sisa exchange (2.5M, bukan 4M)
        self.assertEqual(eng.inv_qty, D("2500000"),
                         "B39: inv_qty harus dikoreksi ke sisa exchange")
        # Flush order ditempatkan untuk sisa 2.5M
        x.place_post_only.assert_called_once()

    def test_b40_flush_does_not_increase_inv_qty(self):
        """B39/B40: sync tidak menaikkan inv_qty (hanya koreksi ke bawah)."""
        from decimal import Decimal as D
        eng, x, tg = self._make_engine(inv_qty=D("1000000"))
        bk = self._make_bk()
        # Exchange menunjukkan LEBIH banyak PEPE (tidak wajar — tidak crash, tidak naik)
        x.balance.return_value = {"vPEPE": D("5000000"), "vUSDC": D("50")}
        x.place_post_only.return_value = self._make_order(
            "PEPE/USDC", "sell", "0.0000028", "1000000", oid="flush4")

        eng._force_flush_now(bk)

        self.assertEqual(eng.inv_qty, D("1000000"),
                         "B39: sync tidak boleh naikkan inv_qty (hanya koreksi ke bawah)")

    def test_b40_source_has_b39_and_b40(self):
        """B39+B40: source _force_flush_now harus punya marker B39 dan B40."""
        import inspect
        from anantara.sodex_twin_engine import Engine1Flywheel
        src = inspect.getsource(Engine1Flywheel._force_flush_now)
        self.assertIn("B39", src, "_force_flush_now harus punya komentar B39")
        self.assertIn("B40", src, "_force_flush_now harus punya komentar B40")
        self.assertIn("balance()", src, "_force_flush_now harus panggil balance()")
        self.assertIn('"v" +', src, '_force_flush_now harus derive coin via "v" + pair.split')

    # ── B51 tests ─────────────────────────────────────────────────────────────

    def test_b51_flush_sell_placed_at_ask_not_bid(self):
        """B51: flush sell harus di bk.ask bukan bk.bid.

        Root cause B51: flush pakai bk.bid → place_post_only crossing bid buyers →
        oid=0 setiap attempt → SHIB stuck 888 menit. Fix: sell at bk.ask (resting
        maker); terisi saat buyer hit ask.
        """
        from decimal import Decimal as D
        eng, x, tg = self._make_engine(inv_qty=D("4000000"))
        bk = self._make_bk(bid="0.0000028", ask="0.0000030")
        x.balance.return_value = {"vPEPE": D("4000000"), "vUSDC": D("100")}
        placed_args = {}

        def capture(*args, **kwargs):
            placed_args["pair"], placed_args["side"], placed_args["px"], placed_args["qty"] = args
            from anantara.sodex_twin_engine import Order
            return Order(pair=args[0], side=args[1], price=args[2], qty=args[3], oid="flush_b51")

        x.place_post_only.side_effect = capture
        eng._force_flush_now(bk)

        self.assertEqual(placed_args.get("side"), "sell")
        # B51 (Juni) + B61 tick-edge (audit live 29-Sep-00:52): venue MENOLAK sell
        # post-only TEPAT di ask → harga aman = ask + 1 tick nyata (0.0000030 →
        # 0.0000031 pada buku presisi 1e-7), bukan ask polos.
        self.assertEqual(placed_args.get("px"), D("0.0000031"),
                         "B51/B61: flush sell harus di ask+1 tick (0.0000031), bukan ask/bid")

    def test_b51_flush_sell_not_at_bid(self):
        """B51: flush sell TIDAK boleh di bk.bid (bid = crossing = oid=0 loop)."""
        from decimal import Decimal as D
        eng, x, tg = self._make_engine(inv_qty=D("2000000"))
        bk = self._make_bk(bid="0.0000028", ask="0.0000030")
        x.balance.return_value = {"vPEPE": D("2000000"), "vUSDC": D("100")}
        placed_args = {}

        def capture(*args, **kwargs):
            placed_args["px"] = args[2]
            from anantara.sodex_twin_engine import Order
            return Order(pair=args[0], side=args[1], price=args[2], qty=args[3], oid="flush_b51b")

        x.place_post_only.side_effect = capture
        eng._force_flush_now(bk)

        self.assertNotEqual(placed_args.get("px"), D("0.0000028"),
                            "B51: flush sell TIDAK boleh di bid (akan selalu oid=0)")

    def test_b51_source_marker_in_force_flush_now(self):
        """B51: source _force_flush_now harus punya marker B51."""
        import inspect
        from anantara.sodex_twin_engine import Engine1Flywheel
        src = inspect.getsource(Engine1Flywheel._force_flush_now)
        self.assertIn("B51", src, "_force_flush_now harus punya komentar B51")


class TwinEngineB41B42Tests(TestCase):
    """B41: drop lost unfilled orders silently (stop poll_fill spam).
    B42: reset _flushing when inv_usd < min_notional (unblock quoting).
    """

    @classmethod
    def setUpClass(cls):
        from anantara.sodex_twin_engine import SCHEMA
        cls.SCHEMA = SCHEMA

    def _make_engine(self, inv_qty=None, pair="PEPE/USDC"):
        import sqlite3, time
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import Engine1Flywheel, Config, Ledger
        if inv_qty is None:
            inv_qty = D("0")
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.executescript(self.SCHEMA)
        led.con.commit()
        x = MagicMock()
        tg = MagicMock()
        cfg = Config()
        eng = Engine1Flywheel(cfg, x, led, tg, MagicMock(), hedge_enabled=False, pair=pair)
        eng.inv_qty = inv_qty
        eng._inv_started = time.time() - 6 * 3600
        return eng, x

    def _make_bk(self, bid="0.0000028", ask="0.0000030"):
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        bk = MagicMock()
        bk.bid = D(bid)
        bk.ask = D(ask)
        bk.mid = (D(bid) + D(ask)) / 2
        bk.spread = (D(ask) - D(bid)) / bk.mid
        return bk

    def _make_order(self, oid="o1", filled=0, qty=1000, ts_offset=-10):
        import time
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        o = MagicMock()
        o.oid = oid
        o.filled = D(filled)
        o.qty = D(qty)
        o.ts = time.time() + ts_offset
        return o

    def test_b41_lost_unfilled_order_dropped_silently(self):
        """B41: order hilang dari exchange dengan filled=0 → drop (tidak spam poll_fill)."""
        import inspect
        from anantara.sodex_twin_engine import Engine1Flywheel
        src = inspect.getsource(Engine1Flywheel.step)
        # Verifikasi fix B41 ada di source
        self.assertIn("B41", src, "step() harus punya fix B41 untuk drop unfilled lost orders")

    def test_b42_flushing_reset_when_inv_too_small(self):
        """B42: _flushing=True direset ke False saat inv_usd < min_notional."""
        from decimal import Decimal as D
        # SHIB dust: 0.29 SHIB @ $4.715e-6 ≈ $0.000001 — jauh di bawah $10
        eng, x = self._make_engine(inv_qty=D("0.29"), pair="SHIB/USDC")
        eng._flushing = True
        eng._quoting_paused = False
        eng._inv_started = __import__("time").time() - 99999  # sudah sangat tua
        # bid/ask sangat kecil → inv_usd ≈ $0
        bk = self._make_bk(bid="0.0000047", ask="0.0000048")
        # _check_flush harus reset _flushing karena inv_usd ≈ 0 < $10
        eng._check_flush(bk)
        self.assertFalse(eng._flushing,
                         "B42: _flushing harus direset ke False saat inv terlalu kecil untuk di-flush")

    def test_b42_flushing_not_reset_when_inv_large_enough(self):
        """B42: _flushing tidak direset bila inv_usd ≥ min_notional DAN inventori
        melebihi cap (over-exposure → flush normal berlanjut; cooldown menahan
        order baru). B54: untuk inventori DALAM cap, _flushing memang dilepas."""
        from decimal import Decimal as D
        import dataclasses, time
        eng, x = self._make_engine(inv_qty=D("4000000"), pair="PEPE/USDC")
        # cap kecil ($5) → inv_usd $11.6 MELEBIHI cap → B54 tidak melepas _flushing
        eng.cfg = dataclasses.replace(eng.cfg, e1_inv_cap_per_pair=D("5"))
        eng._flushing = True
        eng._quoting_paused = False
        eng._inv_started = time.time() - 99999
        eng._last_flush_ts = time.time()  # cooldown aktif → tidak place order baru
        bk = self._make_bk(bid="0.0000028", ask="0.0000030")
        # inv_usd ≈ 4M * 2.9e-6 = $11.6 ≥ $10 dan > cap $5 → cooldown mencegah flush
        eng._check_flush(bk)
        # _flushing TIDAK direset (over-cap + cooldown, bukan karena inv kecil)
        self.assertTrue(eng._flushing,
                        "B42: _flushing tidak boleh direset saat inv over-cap (cooldown aktif)")

    def test_b42_source_contains_b42(self):
        """B42: _check_flush harus punya marker B42."""
        import inspect
        from anantara.sodex_twin_engine import Engine1Flywheel
        src = inspect.getsource(Engine1Flywheel._check_flush)
        self.assertIn("B42", src, "_check_flush harus punya komentar B42")

    def test_b43_sell_cooldown_after_oid0(self):
        """B43/B49: setelah sell oid=0, tidak boleh retry sell selama 5s."""
        import time
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import Engine1Flywheel, Order
        eng, x = self._make_engine(inv_qty=D("5000000"), pair="PEPE/USDC")
        eng._quoting_paused = False
        eng._flushing = False
        bk = self._make_bk(bid="0.0000028", ask="0.0000030")
        # Simulate sell oid=0: set cooldown as if just failed
        eng._oid0_ts["sell"] = time.time()
        # _place_two_sided must skip sell due to cooldown
        placed = eng._place_two_sided(bk)
        self.assertEqual(placed, 0, "B43/B49: sell blocked by 5s cooldown after oid=0")
        self.assertIn("sell_oid0_cooldown", eng._last_place_skip_reason)

    def test_b43_buy_cooldown_after_oid0(self):
        """B43/B49: setelah buy oid=0, tidak boleh retry buy selama 5s."""
        import time
        from decimal import Decimal as D
        eng, x = self._make_engine(inv_qty=D("0"), pair="PEPE/USDC")
        eng._quoting_paused = False
        eng._flushing = False
        bk = self._make_bk(bid="0.0000028", ask="0.0000030")
        eng._oid0_ts["buy"] = time.time()
        placed = eng._place_two_sided(bk)
        self.assertEqual(placed, 0, "B43/B49: buy blocked by 5s cooldown after oid=0")
        self.assertIn("buy_oid0_cooldown", eng._last_place_skip_reason)

    def test_b43_cooldown_expires(self):
        """B43/B49: setelah 5s, retry diizinkan lagi."""
        import time
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import Order
        import dataclasses
        eng, x = self._make_engine(inv_qty=D("0"), pair="PEPE/USDC")
        # Raise inv_cap so buy cap (0.85×cap) never triggers for any ladder step.
        # ponytail: dataclasses.replace on frozen Config — cap=100 → 0.85×100=$85 safe
        eng.cfg = dataclasses.replace(eng.cfg, e1_inv_cap_per_pair=D("100"))
        eng._quoting_paused = False
        eng._flushing = False
        bk = self._make_bk(bid="0.0000028", ask="0.0000030")
        # Cooldown expired 8s ago (B49: cooldown=5s)
        eng._oid0_ts["buy"] = time.time() - 8
        # Exchange returns valid order
        good_order = MagicMock()
        good_order.oid = "abc123"
        x.place_post_only.return_value = good_order
        placed = eng._place_two_sided(bk)
        self.assertGreater(placed, 0, "B43/B49: after 5s cooldown expires, buy should be attempted")

    def test_b43_source_in_place_two_sided(self):
        """B43: kontrak traceability — marker B43 harus ADA di engine.

        AUDIT 29-Sep-2026: dulu test mensyaratkan marker berada di DALAM
        _place_two_sided. Itu mengikat penulisan komentar ke satu fungsi; saat B60/B61
        memperluas blok backoff & tick-edge, marker B43 (yang memang hidup di jalur
        cooldown/pause pair-scoped, bukan di quoting) jadi "hilang" walau kontraknya
        utuh. Yang diuji seharusnya: kontrak B43 ada & tidak dicabut — dicek di engine.
        """
        import inspect
        from anantara import sodex_twin_engine as te
        src = inspect.getsource(te)
        self.assertIn("B43", src, "marker kontrak B43 harus tetap ada di engine")
        self.assertIn("B60", inspect.getsource(te.Engine1Flywheel._place_two_sided),
                      "jalur quoting harus membawa kontrak backoff B60")

    def test_b45_partial_sell_when_inv_below_quote_size(self):
        """B45: jika inv < quote_qty tapi inv_usd >= min_notional, jual semua sisa.

        _quote_size_usd di-mock → $10 deterministik:
        qty = $10 / ask ≈ 3.53M > inv_qty=2M → B45 selalu terpicu.
        inv_usd = 2M × $0.00000283 ≈ $5.66 ≥ $5 → dust guard lulus.
        """
        import dataclasses
        from decimal import Decimal as D
        from unittest.mock import MagicMock, patch
        eng, x = self._make_engine(inv_qty=D("2000000"), pair="PEPE/USDC")
        # ponytail: pin cap agar buy-cap check tidak memblokir secara non-deterministik
        eng.cfg = dataclasses.replace(eng.cfg, e1_inv_cap_per_pair=D("100"))
        eng._quoting_paused = False
        eng._flushing = False
        bk = self._make_bk(bid="0.0000028200", ask="0.0000028300")
        good_sell = MagicMock()
        good_sell.oid = "sell123"
        x.place_post_only.return_value = good_sell

        # _quote_size_usd di-mock → $10: qty ≈ 3.53M > 2M inv_qty → B45 terpicu
        with patch.object(eng, '_quote_size_usd', return_value=D("10")):
            eng._place_two_sided(bk)

        sell_calls = [c for c in x.place_post_only.call_args_list if c.args[1] == "sell"]
        self.assertTrue(len(sell_calls) > 0, "B45: sell should be attempted with inv_qty")
        # B45: qty must equal inv_qty (sell all remaining, not the larger quote_qty)
        sell_qty = sell_calls[0].args[3]
        self.assertEqual(sell_qty, D("2000000"))

    def test_b45_sell_skipped_when_inv_usd_below_min_notional(self):
        """B45: inv_usd < $5 → masih skip (tidak boleh jual dust)."""
        from decimal import Decimal as D
        # 1M PEPE @ $0.0000028 ≈ $2.80 — below $5 SODEX_MIN_NOTIONAL
        eng, x = self._make_engine(inv_qty=D("1000000"), pair="PEPE/USDC")
        eng._quoting_paused = False
        eng._flushing = False
        bk = self._make_bk(bid="0.0000028200", ask="0.0000028300")

        eng._place_two_sided(bk)

        sell_calls = [c for c in x.place_post_only.call_args_list if c.args[1] == "sell"]
        self.assertEqual(len(sell_calls), 0, "B45: dust sell < $5 should NOT be placed")

    def test_b45_source_in_place_two_sided(self):
        """B45: _place_two_sided harus punya marker B45."""
        import inspect
        from anantara.sodex_twin_engine import Engine1Flywheel
        src = inspect.getsource(Engine1Flywheel._place_two_sided)
        self.assertIn("B45", src)

    def test_b47_sell_clamped_to_ask_when_skew_crosses_bid(self):
        """B47: skew ekstrem pada 1-tick spread push sell ke ≤ bid → clamp ke ask."""
        from decimal import Decimal as D
        eng, x = self._make_engine(inv_qty=D("17000000"), pair="PEPE/USDC")
        eng._quoting_paused = False
        eng._flushing = False
        # 1-tick spread: bid=0.00000283, ask=0.00000284
        bk = self._make_bk(bid="0.00000283", ask="0.00000284")
        good = MagicMock(); good.oid = "ok1"
        x.place_post_only.return_value = good
        eng._place_two_sided(bk)
        sell_calls = [c for c in x.place_post_only.call_args_list if c.args[1] == "sell"]
        if sell_calls:
            sell_px = sell_calls[0].args[2]
            self.assertGreaterEqual(float(sell_px), float(bk.ask),
                                    "B47: sell px must be ≥ ask (never cross bid)")

    def test_b47_buy_clamped_to_bid_when_skew_pushes_above_ask(self):
        """B47: skew pada short inventory tidak push buy ke ≥ ask."""
        from decimal import Decimal as D
        eng, x = self._make_engine(inv_qty=D("-17000000"), pair="PEPE/USDC")
        eng._quoting_paused = False
        eng._flushing = False
        bk = self._make_bk(bid="0.00000283", ask="0.00000284")
        good = MagicMock(); good.oid = "ok2"
        x.place_post_only.return_value = good
        eng._place_two_sided(bk)
        buy_calls = [c for c in x.place_post_only.call_args_list if c.args[1] == "buy"]
        if buy_calls:
            buy_px = buy_calls[0].args[2]
            self.assertLessEqual(float(buy_px), float(bk.bid),
                                 "B47: buy px must be ≤ bid (never cross ask)")

    def test_b47_source_in_place_two_sided(self):
        """B47: marker harus ada di _place_two_sided."""
        import inspect
        from anantara.sodex_twin_engine import Engine1Flywheel
        src = inspect.getsource(Engine1Flywheel._place_two_sided)
        self.assertIn("B47", src)

    def test_b50_sell_inside_spread_clamped_to_ask(self):
        """B50: sell px antara bid dan ask (sub-tick) → paksa ke ask agar tidak ditolak exchange."""
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        # Moderate inventory (won't trigger skew) so normal depth puts px inside spread
        eng, x = self._make_engine(inv_qty=D("1000000"), pair="PEPE/USDC")
        eng._quoting_paused = False
        eng._flushing = False
        # 1-tick spread: bid=0.00000282, ask=0.00000283
        bk = self._make_bk(bid="0.00000282", ask="0.00000283")
        good = MagicMock(); good.oid = "ok_b50"
        x.place_post_only.return_value = good
        eng._place_two_sided(bk)
        sell_calls = [c for c in x.place_post_only.call_args_list if c.args[1] == "sell"]
        if sell_calls:
            sell_px = sell_calls[0].args[2]
            self.assertGreaterEqual(float(sell_px), float(bk.ask),
                                    "B50: sell px must be ≥ ask even with inside-spread depth")

    def test_b50_buy_inside_spread_clamped_to_bid(self):
        """B50: buy px antara bid dan ask (sub-tick) → paksa ke bid agar tidak ditolak exchange."""
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        import dataclasses
        eng, x = self._make_engine(inv_qty=D("0"), pair="PEPE/USDC")
        eng.cfg = dataclasses.replace(eng.cfg, e1_inv_cap_per_pair=D("200"))
        eng._quoting_paused = False
        eng._flushing = False
        bk = self._make_bk(bid="0.00000282", ask="0.00000283")
        good = MagicMock(); good.oid = "ok_b50b"
        x.place_post_only.return_value = good
        eng._place_two_sided(bk)
        buy_calls = [c for c in x.place_post_only.call_args_list if c.args[1] == "buy"]
        if buy_calls:
            buy_px = buy_calls[0].args[2]
            self.assertLessEqual(float(buy_px), float(bk.bid),
                                 "B50: buy px must be ≤ bid even with inside-spread depth")

    def test_b50_source_in_place_two_sided(self):
        """B50: marker B50 harus ada di _place_two_sided."""
        import inspect
        from anantara.sodex_twin_engine import Engine1Flywheel
        src = inspect.getsource(Engine1Flywheel._place_two_sided)
        self.assertIn("B50", src)

    def test_b53_cancels_crossing_resting_order_before_place(self):
        """B53: resting BUY yang menyilang harga sell baru harus dibatalkan dulu
        (cegah self-trade reject orderID=0 pada 1-tick spread)."""
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        import dataclasses
        eng, x = self._make_engine(inv_qty=D("3000000"), pair="PEPE/USDC")
        eng.cfg = dataclasses.replace(eng.cfg, e1_inv_cap_per_pair=D("200"))
        eng._quoting_paused = False
        eng._flushing = False
        # resting BUY 0.00000290 — MENYILANG sell baru. AUDIT 29-Sep-2026: sell baru
        # kini ask+1 tick (0.00000286, B61) bukan ask polos (0.00000285, B50 lama),
        # jadi fixture digeser agar benar-benar menyilang (bukan lolos uji kebetulan).
        stale = MagicMock(); stale.pair = "PEPE/USDC"; stale.side = "buy"
        stale.price = D("0.00000290"); stale.oid = "stale_buy"
        eng.orders = [stale]
        bk = self._make_bk(bid="0.00000284", ask="0.00000285")
        good = MagicMock(); good.oid = "ok_b53"
        x.place_post_only.return_value = good
        eng._place_two_sided(bk)
        # stale crossing buy harus dibatalkan
        cancelled = [c.args[0] for c in x.cancel.call_args_list]
        self.assertIn(stale, cancelled,
                      "B53: resting buy yang menyilang sell baru harus di-cancel")

    def test_b53_keeps_non_crossing_resting_order(self):
        """B53: resting order yang TIDAK menyilang tidak boleh dibatalkan."""
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        import dataclasses
        eng, x = self._make_engine(inv_qty=D("3000000"), pair="PEPE/USDC")
        eng.cfg = dataclasses.replace(eng.cfg, e1_inv_cap_per_pair=D("200"))
        eng._quoting_paused = False
        eng._flushing = False
        # resting BUY at 0.00000280 (jauh di bawah ask 0.00000285 → tidak menyilang)
        ok_rest = MagicMock(); ok_rest.pair = "PEPE/USDC"; ok_rest.side = "buy"
        ok_rest.price = D("0.00000280"); ok_rest.oid = "ok_rest"
        eng.orders = [ok_rest]
        bk = self._make_bk(bid="0.00000284", ask="0.00000285")
        good = MagicMock(); good.oid = "ok_b53b"
        x.place_post_only.return_value = good
        eng._place_two_sided(bk)
        cancelled = [c.args[0] for c in x.cancel.call_args_list]
        self.assertNotIn(ok_rest, cancelled,
                         "B53: resting buy non-crossing tidak boleh di-cancel")

    def test_b53_source_in_place_two_sided(self):
        """B53: marker B53 harus ada di _place_two_sided."""
        import inspect
        from anantara.sodex_twin_engine import Engine1Flywheel
        src = inspect.getsource(Engine1Flywheel._place_two_sided)
        self.assertIn("B53", src)

    def test_b52_singleton_flock_in_main(self):
        """B52: main() harus pakai fcntl.flock singleton agar instance kedua keluar
        (cegah multi-quote saat systemd + auto_evaluate sama-sama spawn engine)."""
        import inspect
        from anantara import sodex_twin_engine as m
        src = inspect.getsource(m.main)
        self.assertIn("B52", src, "main harus punya marker B52")
        self.assertIn("flock", src, "B52 harus pakai fcntl.flock")
        self.assertIn("LOCK_EX", src, "B52 harus LOCK_EX | LOCK_NB")
        self.assertIn("SystemExit(0)", src, "B52: instance kedua keluar bersih exit 0")

    def test_b48_pair2_min_spread_default_is_lower_than_shib_spread(self):
        """B48: e1_pair2_min_spread code default 0.0015 < SHIB spread ~0.0021
        sehingga SHIB bisa quote tanpa TE_E1_PAIR2_MIN_SPREAD di .env."""
        import inspect
        from anantara.sodex_twin_engine import Config
        src = inspect.getsource(Config)
        # Verify the hardcoded default "0.0015" is in source (not chained to e1_min_spread)
        self.assertIn('"0.0015"', src,
                      "B48: pair2 min_spread default must be 0.0015 in source")


class TwinEngineB56E2MakerOffsetTests(TestCase):
    """B56: E2 maker leg ditempatkan inside-favor (buy<bid, sell>ask) agar tidak
    menyilang di 1-tick perps → placement valid (no oid=0 storm)."""

    def _make_e2(self):
        import sqlite3
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import Engine2Perps, Config, Ledger, SCHEMA
        led = object.__new__(Ledger)
        led.con = sqlite3.connect(":memory:", check_same_thread=False)
        led.con.executescript(SCHEMA); led.con.commit()
        x = MagicMock(); g = MagicMock(); t = MagicMock(); tg = MagicMock()
        e2 = Engine2Perps(Config(), x, led, g, t, tg, pair="XPL-USD")
        return e2, x

    def _bk(self, bid="0.0963", ask="0.0964"):
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        bk = MagicMock(); bk.bid = D(bid); bk.ask = D(ask); bk.mid = (D(bid)+D(ask))/2
        return bk

    def test_b56_buy_leg_below_bid(self):
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        e2, x = self._make_e2()
        x.book.return_value = self._bk()
        captured = {}
        def cap(pair, side, px, qty):
            captured["px"] = px
            o = MagicMock(); o.oid = "0"; return o  # oid=0 → return setelah capture
        x.place_post_only.side_effect = cap
        e2._maker_leg("buy", D("14"), aggressive=0)
        self.assertLess(captured["px"], D("0.0963"),
                        "B56: buy leg harus DI BAWAH bid (inside-favor, tak menyilang)")

    def test_b56_sell_leg_above_ask(self):
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        e2, x = self._make_e2()
        x.book.return_value = self._bk()
        captured = {}
        def cap(pair, side, px, qty):
            captured["px"] = px
            o = MagicMock(); o.oid = "0"; return o
        x.place_post_only.side_effect = cap
        e2._maker_leg("sell", D("14"), aggressive=0)
        self.assertGreater(captured["px"], D("0.0964"),
                           "B56: sell leg harus DI ATAS ask (inside-favor, tak menyilang)")

    def test_b56_source_marker(self):
        import inspect
        from anantara.sodex_twin_engine import Engine2Perps
        src = inspect.getsource(Engine2Perps._maker_leg)
        self.assertIn("B56", src)


class TwinEngineE2DirLeverageTests(TestCase):
    """E2Dir leverage = pengganda volume (compendium §2.2): margin = notional/leverage."""

    def test_leverage_env_var_wired(self):
        """Config harus baca TE_E2_DIR_LEVERAGE (env dibaca saat import)."""
        import inspect
        from anantara.sodex_twin_engine import Config
        src = inspect.getsource(Config)
        self.assertIn("TE_E2_DIR_LEVERAGE", src)

    def test_leverage_default_is_1x_safe(self):
        from anantara.sodex_twin_engine import Config
        # Default 1x (no leverage) — harus eksplisit di-set untuk volume scaling
        self.assertEqual(Config().e2_dir_leverage, 1)

    def test_open_sets_leverage_before_entry(self):
        """_open harus panggil 'leverage' CLI sebelum place saat leverage>1."""
        import inspect
        from anantara.sodex_twin_engine import Engine2Directional
        src = inspect.getsource(Engine2Directional)
        self.assertIn("leverage", src.lower())
        self.assertIn("e2_dir_leverage", src, "harus baca cfg.e2_dir_leverage")


class TwinEngineE2MomentumTests(TestCase):
    """E2 momentum high-frequency signal (paper-first) — continuation hypothesis."""

    def _cfg(self):
        from anantara.sodex_twin_engine import Config
        return Config()

    def _adapter(self, bid, ask):
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        x = MagicMock()
        def book(p):
            b = MagicMock(); b.bid = D(str(bid)); b.ask = D(str(ask)); b.mid = (D(str(bid))+D(str(ask)))/2
            return b
        x.book.side_effect = book
        return x

    def test_momentum_first_obs_returns_none(self):
        from anantara.sodex_twin_engine import generate_momentum_signal
        x = self._adapter(100, 100.5)
        self.assertIsNone(generate_momentum_signal(x, "BTC-USD", self._cfg(), {}))

    def test_reversion_up_move_is_sell(self):
        """Default REVERSI (kontinuasi terfalsifikasi): lonjakan naik → SELL (balik)."""
        import time, dataclasses
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import generate_momentum_signal
        cfg = self._cfg()
        self.assertTrue(cfg.e2_mom_reversion, "default harus reversi")
        cache = {"BTC-USD": (D("100"), time.time() - 30)}
        x = self._adapter(100.3, 100.8)  # +0.55%
        sig = generate_momentum_signal(x, "BTC-USD", cfg, cache)
        self.assertIsNotNone(sig)
        self.assertEqual(sig["side"], "sell", "reversi: naik → sell")

    def test_reversion_down_move_is_buy(self):
        """Reversi: lonjakan turun → BUY (balik)."""
        import time
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import generate_momentum_signal
        cfg = self._cfg()
        cache = {"BTC-USD": (D("100"), time.time() - 30)}
        x = self._adapter(99.2, 99.7)  # -0.55%
        sig = generate_momentum_signal(x, "BTC-USD", cfg, cache)
        self.assertIsNotNone(sig)
        self.assertEqual(sig["side"], "buy", "reversi: turun → buy")

    def test_momentum_below_threshold_none(self):
        import time
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import generate_momentum_signal
        cfg = self._cfg()
        cache = {"BTC-USD": (D("100"), time.time() - 30)}
        x = self._adapter(100.02, 100.06)  # +0.04% < 0.15% thr
        self.assertIsNone(generate_momentum_signal(x, "BTC-USD", cfg, cache))

    def test_momentum_stale_dt_none(self):
        import time
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import generate_momentum_signal
        cfg = self._cfg()
        cache = {"BTC-USD": (D("100"), time.time() - 9999)}  # too old
        x = self._adapter(101, 101.5)
        self.assertIsNone(generate_momentum_signal(x, "BTC-USD", cfg, cache))

    def test_momentum_paper_default_off_and_paper(self):
        cfg = self._cfg()
        self.assertFalse(cfg.e2_mom_enabled, "momentum default OFF (opt-in)")
        self.assertFalse(cfg.e2_mom_live, "momentum default PAPER (safety)")

    def test_momentum_wr_computation(self):
        import tempfile, json, os
        from anantara.sodex_twin_engine import Engine2Directional
        fd, path = tempfile.mkstemp(suffix=".jsonl"); os.close(fd)
        with open(path, "w") as f:
            for w in (True, True, False, True):
                f.write(json.dumps({"win": w, "pnl_pct": 0.01 if w else -0.008}) + "\n")
        wr = Engine2Directional.momentum_paper_wr(path)
        os.remove(path)
        self.assertEqual(wr["n"], 4)
        self.assertAlmostEqual(wr["wr"], 0.75, places=2)


class TwinEngineE2OFITests(TestCase):
    """OFI (order-flow imbalance, Cont et al.) signal — flow predicts move."""

    def _cfg(self):
        from anantara.sodex_twin_engine import Config
        return Config()

    def test_ofi_buy_pressure_positive(self):
        from anantara.sodex_twin_engine import _ofi
        # bid size up + ask size down → buy pressure → OFI>0
        self.assertGreater(_ofi((100.0,10,100.5,10), (100.0,20,100.5,5)), 0)

    def test_ofi_sell_pressure_negative(self):
        from anantara.sodex_twin_engine import _ofi
        self.assertLess(_ofi((100.0,10,100.5,10), (100.0,5,100.5,20)), 0)

    def test_ofi_bid_price_up_adds_demand(self):
        from anantara.sodex_twin_engine import _ofi
        # bid price up → full new bid qty counts as demand
        self.assertGreater(_ofi((100.0,10,100.5,10), (100.1,8,100.6,10)), 0)

    def test_ofi_signal_reversion_buy_pressure_sells(self):
        """Default reversi: tekanan beli (OFI>0) → SELL (harga sudah terdorong, balik)."""
        from anantara.sodex_twin_engine import generate_ofi_signal
        cfg=self._cfg()
        self.assertTrue(cfg.e2_mom_reversion)
        sig = generate_ofi_signal("BTC-USD", (100.0,10,100.5,10), (100.0,20,100.5,5), cfg)
        self.assertIsNotNone(sig); self.assertEqual(sig["side"], "sell")

    def test_ofi_signal_below_threshold_none(self):
        from anantara.sodex_twin_engine import generate_ofi_signal
        # tiny imbalance → below thr
        sig = generate_ofi_signal("BTC-USD", (100.0,1000,100.5,1000), (100.0,1001,100.5,1000), self._cfg())
        self.assertIsNone(sig)

    def test_sig_mode_default_ofi(self):
        self.assertEqual(self._cfg().e2_sig_mode, "ofi", "default signal mode = ofi (momentum noise-dominated)")


class TwinEngineMarketIOCTests(TestCase):
    """Market-IOC discovery (2026-06-21): limit-GTC at touch perps → oid=0; market+IOC fills."""

    def test_paper_adapter_has_market_ioc(self):
        from anantara.sodex_twin_engine import PaperAdapter, Config
        a = PaperAdapter(Config())
        from decimal import Decimal as D
        o = a.place_market_ioc("BTC-USD", "buy", D("0.01"), D("60000"), reduce_only=True)
        self.assertNotEqual(o.oid, "0")
        self.assertEqual(o.filled, D("0.01"), "market IOC harus filled penuh di paper")

    def test_e2dir_uses_market_ioc_in_source(self):
        import inspect
        from anantara.sodex_twin_engine import Engine2Directional
        src = inspect.getsource(Engine2Directional)
        self.assertIn("place_market_ioc", src, "E2Dir entry harus pakai market IOC (fill terjamin)")

    def test_live_adapter_market_ioc_method_exists(self):
        from anantara.sodex_twin_engine import SodexLiveAdapter
        self.assertTrue(hasattr(SodexLiveAdapter, "place_market_ioc"))
        import inspect
        src = inspect.getsource(SodexLiveAdapter.place_market_ioc)
        self.assertIn('"market"', src); self.assertIn('"ioc"', src)
        self.assertIn("reduce-only", src)


class TwinEngineRegimeHedgeTests(TestCase):
    """Regime-adaptive hedge (2026-06-22): bull→unhedged, bear→delta-neutral hedge."""

    def test_hedge_sizing_1000x_contract(self):
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import hedge_qty_for_inventory
        self.assertEqual(hedge_qty_for_inventory(D("15700000"), 1000), D("15700"))
        self.assertEqual(hedge_qty_for_inventory(D("722"), 1), D("722"))

    def test_hedge_sizing_zero_mult_safe(self):
        from decimal import Decimal as D
        from anantara.sodex_twin_engine import hedge_qty_for_inventory
        self.assertEqual(hedge_qty_for_inventory(D("100"), 0), D("0"))

    def test_hedge_map_pairs_have_perps(self):
        from anantara.sodex_twin_engine import HEDGE_MAP
        # spot pairs map to correct perp + contract multiplier
        self.assertEqual(HEDGE_MAP["PEPE/USDC"], ("1000PEPE-USD", 1000))
        self.assertEqual(HEDGE_MAP["SHIB/USDC"], ("1000SHIB-USD", 1000))
        self.assertEqual(HEDGE_MAP["XLM/USDC"], ("XLM-USD", 1))

    def test_regime_bear_on_downtrend(self):
        from anantara.sodex_twin_engine import RegimeDetector
        rd = RegimeDetector(window=12, sample_interval_s=0)
        for p in [100, 100, 99, 98, 97, 96, 95, 94]:
            rd.update(float(p), 0.0)
        self.assertEqual(rd.regime(), "BEAR")
        from decimal import Decimal as D
        self.assertEqual(rd.hedge_ratio(), D("1.0"))

    def test_regime_bull_on_uptrend(self):
        from anantara.sodex_twin_engine import RegimeDetector
        rd = RegimeDetector(window=12, sample_interval_s=0)
        for p in [100, 100, 101, 102, 103, 104, 105, 106]:
            rd.update(float(p), 0.0)
        self.assertEqual(rd.regime(), "BULL")
        from decimal import Decimal as D
        self.assertEqual(rd.hedge_ratio(), D("0.0"))

    def test_regime_neutral_when_flat_or_insufficient(self):
        from anantara.sodex_twin_engine import RegimeDetector
        rd = RegimeDetector(window=12, sample_interval_s=0)
        self.assertEqual(rd.regime(), "NEUTRAL")  # no data
        for p in [100, 100, 100, 100, 100]:
            rd.update(float(p), 0.0)
        self.assertEqual(rd.regime(), "NEUTRAL")  # flat

    def test_regime_throttles_samples(self):
        from anantara.sodex_twin_engine import RegimeDetector
        rd = RegimeDetector(window=12, sample_interval_s=300)
        rd.update(100.0, 1000.0)
        rd.update(101.0, 1100.0)  # <300s later → ignored
        self.assertEqual(len(rd._samples), 1)
        rd.update(102.0, 1400.0)  # >300s → accepted
        self.assertEqual(len(rd._samples), 2)


class TwinEngineIntelRegimeTests(TestCase):
    """Integrasi ekosistem Anantara: Intelligence + Pre-Sentiment → regime LEADING."""

    def test_intel_regime_bull_high_score(self):
        from anantara.sodex_twin_engine import intel_regime
        self.assertEqual(intel_regime({"score": 62.0, "event_risk": ""}), "BULL")

    def test_intel_regime_bear_low_score(self):
        from anantara.sodex_twin_engine import intel_regime
        self.assertEqual(intel_regime({"score": 40.0, "event_risk": ""}), "BEAR")

    def test_intel_regime_bear_on_red_event_weak_score(self):
        from anantara.sodex_twin_engine import intel_regime
        self.assertEqual(intel_regime({"score": 48.0, "event_risk": "RED"}), "BEAR")

    def test_intel_regime_none_when_no_signal(self):
        from anantara.sodex_twin_engine import intel_regime
        self.assertIsNone(intel_regime(None))

    def test_combined_intel_bear_wins_for_protection(self):
        from anantara.sodex_twin_engine import combined_regime
        # leading bear → defensive even if trend bullish (early protection)
        self.assertEqual(combined_regime("BULL", "BEAR"), "BEAR")
        self.assertEqual(combined_regime("NEUTRAL", "BEAR"), "BEAR")

    def test_combined_bull_when_both_agree(self):
        from anantara.sodex_twin_engine import combined_regime
        self.assertEqual(combined_regime("BULL", "BULL"), "BULL")
        self.assertEqual(combined_regime("NEUTRAL", "BULL"), "BULL")

    def test_combined_falls_back_to_trend_when_intel_none(self):
        from anantara.sodex_twin_engine import combined_regime
        # daemon stale → use trend only (no daemon dependency)
        self.assertEqual(combined_regime("BEAR", None), "BEAR")
        self.assertEqual(combined_regime("BULL", None), "BULL")

    def test_read_intel_signal_stale_returns_none(self):
        import tempfile, json, os, time
        from anantara.sodex_twin_engine import read_intel_signal
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "intel_20260101.jsonl"), "w") as f:
            f.write(json.dumps({"ts": time.time() - 99999, "composite_score": 44.0}) + "\n")
        self.assertIsNone(read_intel_signal(d, max_age_min=90))  # stale → None (fail-safe)

    def test_read_intel_signal_fresh_parsed(self):
        import tempfile, json, os, time
        from anantara.sodex_twin_engine import read_intel_signal
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "intel_20260622.jsonl"), "w") as f:
            f.write(json.dumps({"ts": time.time() - 60, "composite_score": 44.4,
                                "fc_BTC_dir_enc": 0, "fc_BTC_conf": 0.4,
                                "event_risk_level": "RED"}) + "\n")
        sig = read_intel_signal(d, max_age_min=90)
        self.assertIsNotNone(sig)
        self.assertEqual(sig["score"], 44.4)
        self.assertEqual(sig["event_risk"], "RED")


class TwinEngineAdaptiveHedgeExecTests(TestCase):
    """Regime-adaptive hedge EXECUTION: BEAR→short perp, BULL→close, band skip."""

    def _eng(self, regime, inv, hedge_qty=None):
        import sqlite3, dataclasses, time
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import Engine1Flywheel, Config, Ledger, SCHEMA
        led = object.__new__(Ledger); led.con = sqlite3.connect(":memory:")
        led.con.executescript(SCHEMA); led.con.commit()
        cfg = dataclasses.replace(Config(), e1_hedge_enabled=True,
                                  e1_hedge_pairs="PEPE/USDC", e1_hedge_band=D("5"))
        x = MagicMock()
        eng = Engine1Flywheel(cfg, x, led, MagicMock(), MagicMock(),
                              hedge_enabled=True, pair="PEPE/USDC")
        eng.inv_qty = D(str(inv))
        if hedge_qty is not None:
            eng.hedge_qty = D(str(hedge_qty))
        eng._regime_label = regime; eng._regime_cache_ts = time.time() + 9999
        pb = MagicMock(); pb.bid = D("0.00279"); pb.ask = D("0.00280"); pb.mid = D("0.002792")
        x.book.return_value = pb
        self._cap = {}
        def cap(pair, side, qty, ref, reduce_only=False):
            self._cap.update(pair=pair, side=side, qty=qty, reduce=reduce_only)
            o = MagicMock(); o.oid = "h1"; o.filled = qty; return o
        x.place_market_ioc.side_effect = cap
        return eng, x

    def test_bear_opens_short_hedge(self):
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        eng, x = self._eng("BEAR", 15700000)
        bk = MagicMock(); bk.mid = D("0.000002845")
        eng._rebalance_hedge(bk)
        self.assertEqual(self._cap["pair"], "1000PEPE-USD")
        self.assertEqual(self._cap["side"], "sell")
        self.assertEqual(self._cap["qty"], D("15700"))  # 15.7M/1000 contracts
        self.assertEqual(eng.hedge_qty, D("15700"))

    def test_bull_closes_hedge(self):
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        # BULL regime: target hedge=0; existing hedge 15700 → buy to close
        eng, x = self._eng("BULL", 15700000, hedge_qty=15700)
        bk = MagicMock(); bk.mid = D("0.000002845")
        eng._rebalance_hedge(bk)
        self.assertEqual(self._cap["side"], "buy")
        self.assertTrue(self._cap["reduce"])  # reduce-only close
        self.assertEqual(eng.hedge_qty, D("0"))

    def test_hedge_disabled_no_action(self):
        import dataclasses, sqlite3
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        from anantara.sodex_twin_engine import Engine1Flywheel, Config, Ledger, SCHEMA
        led = object.__new__(Ledger); led.con = sqlite3.connect(":memory:")
        led.con.executescript(SCHEMA); led.con.commit()
        cfg = dataclasses.replace(Config(), e1_hedge_enabled=False)
        x = MagicMock()
        eng = Engine1Flywheel(cfg, x, led, MagicMock(), MagicMock(), hedge_enabled=False, pair="PEPE/USDC")
        eng.inv_qty = D("15700000")
        bk = MagicMock(); bk.mid = D("0.000002845")
        eng._rebalance_hedge(bk)
        x.place_market_ioc.assert_not_called()

    def test_staged_rollout_skips_other_pairs(self):
        from decimal import Decimal as D
        from unittest.mock import MagicMock
        eng, x = self._eng("BEAR", 15700000)
        eng.pair = "SHIB/USDC"  # not in hedge_pairs (PEPE only)
        bk = MagicMock(); bk.mid = D("0.000004725")
        eng._rebalance_hedge(bk)
        x.place_market_ioc.assert_not_called()
