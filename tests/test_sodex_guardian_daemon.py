"""Tests for sodex_guardian_daemon.py — autonomous 24/7 health monitor."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anantara.sodex_guardian_daemon as gd


# ── Helpers ───────────────────────────────────────────────────────────────────
def _make_db(tmp: str) -> Path:
    db = Path(tmp) / "twin_engine.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS fills (id INTEGER PRIMARY KEY, ts TEXT, engine TEXT, "
        "bucket TEXT, pair TEXT, side TEXT, price REAL, qty REAL, "
        "notional REAL, fee REAL, maker INTEGER, rt_id TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS rts (rt_id TEXT, ts_close TEXT, engine TEXT, "
        "pair TEXT, volume REAL, net_pnl REAL)"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, v TEXT)")
    conn.commit()
    conn.close()
    return db


def _insert_fill(db: Path, ts: str, pair: str = "PEPE/USDC") -> None:
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO fills (ts, engine, bucket, pair, side, price, qty, notional, fee, maker)"
        " VALUES (?, 'E1', 'b1', ?, 'sell', 0.00001, 100, 1.0, 0.001, 1)",
        (ts, pair),
    )
    conn.commit()
    conn.close()


def _set_state(db: Path, k: str, v: str) -> None:
    conn = sqlite3.connect(str(db))
    conn.execute("INSERT OR REPLACE INTO state (k,v) VALUES (?,?)", (k, v))
    conn.commit()
    conn.close()


def _make_daemon(tmp: str, **kw) -> gd.GuardianDaemon:
    db     = _make_db(tmp)
    eng_log = Path(tmp) / "twin_live.log"
    sig    = Path(tmp) / "GUARDIAN_RESTART_SIGNAL"
    glog   = Path(tmp) / "guardian.log"
    return gd.GuardianDaemon(
        db_path=db,
        engine_log=eng_log,
        signal_path=sig,
        guardian_log=glog,
        tg_token="",
        tg_chat="",
        fast_cycle=60,
        slow_cycle=1200,
        watched_pairs=kw.get("pairs", ["PEPE/USDC"]),
    )


# ── Unit tests ─────────────────────────────────────────────────────────────────
class TestUtcAgo(unittest.TestCase):
    def test_returns_iso_prefix(self):
        s = gd._utc_ago(3600)
        self.assertRegex(s, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

    def test_is_in_the_past(self):
        import datetime
        s = gd._utc_ago(60)
        dt = datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
        diff = (datetime.datetime.utcnow() - dt).total_seconds()
        self.assertGreater(diff, 55)
        self.assertLess(diff, 70)


class TestSendTelegram(unittest.TestCase):
    def test_empty_token_does_not_raise(self):
        gd._send_telegram("", "", "hello")  # no token → silent no-op

    def test_empty_chat_id_does_not_raise(self):
        gd._send_telegram("fake-token", "", "hello")


class TestWriteRestartSignal(unittest.TestCase):
    def test_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            sig = Path(tmp) / "signal"
            gd._write_restart_signal(sig, "test reason")
            data = json.loads(sig.read_text())
            self.assertEqual(data["type"], gd.RESTART_SIGNAL_TYPE)
            self.assertIn("guardian", data["reason"])
            self.assertIn("test reason", data["reason"])
            self.assertIsInstance(data["ts"], float)

    def test_atomic_write_tmp_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            sig = Path(tmp) / "signal"
            gd._write_restart_signal(sig, "x")
            self.assertTrue(sig.exists())
            self.assertFalse((sig.with_suffix(".tmp")).exists())


class TestSignalRecentlyWritten(unittest.TestCase):
    def test_returns_false_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(gd._signal_recently_written(Path(tmp) / "absent"))

    def test_returns_true_for_fresh_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            sig = Path(tmp) / "signal"
            sig.write_text("x")
            self.assertTrue(gd._signal_recently_written(sig, max_age_sec=300))

    def test_returns_false_for_stale_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            sig = Path(tmp) / "signal"
            sig.write_text("x")
            old = time.time() - 10
            os.utime(sig, (old, old))
            self.assertFalse(gd._signal_recently_written(sig, max_age_sec=1))


class TestScanLogErrors(unittest.TestCase):
    def test_picks_up_error_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "twin_live.log"
            log.write_text("2026-07-13 INFO ok\n2026-07-13 ERROR boom\n2026-07-13 INFO ok2\n")
            errors, pos = gd._scan_log_errors(log, 0)
            self.assertEqual(len(errors), 1)
            self.assertIn("boom", errors[0])
            self.assertGreater(pos, 0)

    def test_returns_empty_for_clean_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "twin_live.log"
            log.write_text("INFO all good\nINFO still good\n")
            errors, pos = gd._scan_log_errors(log, 0)
            self.assertEqual(errors, [])

    def test_incremental_scan_skips_old_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "twin_live.log"
            log.write_text("2026-07-13 ERROR old error\n")
            _, pos = gd._scan_log_errors(log, 0)
            # Append new content
            with log.open("a") as f:
                f.write("2026-07-13 ERROR new error\n")
            errors, _ = gd._scan_log_errors(log, pos)
            self.assertEqual(len(errors), 1)
            self.assertIn("new error", errors[0])

    def test_missing_log_returns_empty(self):
        errors, pos = gd._scan_log_errors(Path("/nonexistent/log"), 0)
        self.assertEqual(errors, [])
        self.assertEqual(pos, 0)

    def test_truncated_log_resets_pos(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "twin_live.log"
            log.write_text("original")
            _, pos = gd._scan_log_errors(log, 0)
            # Simulate log rotation (smaller file)
            log.write_text("new")
            errors, new_pos = gd._scan_log_errors(log, pos)
            # Should reset and scan from 0
            self.assertLessEqual(new_pos, len("new"))


class TestDbHelpers(unittest.TestCase):
    def test_get_fills_since_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(tmp)
            conn = gd._db_connect(db)
            count = gd._get_fills_since(conn, 60)
            conn.close()
            self.assertEqual(count, 0)

    def test_get_fills_since_recent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(tmp)
            import datetime
            ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"
            _insert_fill(db, ts)
            conn = gd._db_connect(db)
            count = gd._get_fills_since(conn, 60)
            conn.close()
            self.assertEqual(count, 1)

    def test_get_last_fill_ts_none_when_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(tmp)
            conn = gd._db_connect(db)
            ts = gd._get_last_fill_ts(conn)
            conn.close()
            self.assertIsNone(ts)

    def test_get_last_fill_ts_returns_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(tmp)
            _insert_fill(db, "2026-07-13T01:00:00+00:00")
            _insert_fill(db, "2026-07-13T02:00:00+00:00")
            conn = gd._db_connect(db)
            ts = gd._get_last_fill_ts(conn)
            conn.close()
            self.assertIn("02:00:00", ts)

    def test_get_equity_high_zero_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(tmp)
            conn = gd._db_connect(db)
            val = gd._get_equity_high(conn)
            conn.close()
            self.assertEqual(val, 0.0)

    def test_get_equity_high_parses_float(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(tmp)
            _set_state(db, "equity_high", "416.9788")
            conn = gd._db_connect(db)
            val = gd._get_equity_high(conn)
            conn.close()
            self.assertAlmostEqual(val, 416.9788, places=2)

    def test_has_protective_gate_false_when_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(tmp)
            conn = gd._db_connect(db)
            result = gd._has_protective_gate(conn, "PEPE/USDC")
            conn.close()
            self.assertFalse(result)

    def test_has_protective_gate_true_decay(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(tmp)
            _set_state(db, "e1_decay_gate:PEPE/USDC", "decay_gate pair=PEPE/USDC hours=48 n=11")
            conn = gd._db_connect(db)
            result = gd._has_protective_gate(conn, "PEPE/USDC")
            conn.close()
            self.assertTrue(result)

    def test_has_protective_gate_true_firewall(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(tmp)
            _set_state(db, "e1_profit_firewall:XLM/USDC", "profit_firewall pair=XLM/USDC n=40")
            conn = gd._db_connect(db)
            result = gd._has_protective_gate(conn, "XLM/USDC")
            conn.close()
            self.assertTrue(result)


class TestWatchedPairDetection(unittest.TestCase):
    def test_env_active_pairs_are_used_without_dead_pair_defaults(self):
        env = {
            "TE_SPOT_PAIR": "PEPE/USDC",
            "TE_SPOT_PAIR_2": "",
            "TE_SPOT_PAIR_3": "",
            "TE_SPOT_PAIR_4": "",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(gd._env_active_spot_pairs(), ["PEPE/USDC"])

    def test_detect_watched_pairs_falls_back_to_recent_e1_db_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(tmp)
            import datetime
            ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"
            _insert_fill(db, ts, pair="SHIB/USDC")
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(gd._detect_watched_pairs(db), ["SHIB/USDC"])

    def test_detect_watched_pairs_final_fallback_is_primary_pair_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "missing.db"
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(gd._detect_watched_pairs(db), ["PEPE/USDC"])


class TestEngineLinenessCheck(unittest.TestCase):
    def test_alive_log_no_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_daemon(tmp)
            d.engine_log.write_text("alive")  # fresh log
            with patch.object(d, "_alert") as mock_alert:
                d._check_engine_liveness()
                mock_alert.assert_not_called()

    def test_stale_log_writes_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_daemon(tmp)
            d.engine_log.write_text("stale")
            # Make it look old by manipulating mtime
            old_mtime = time.time() - (gd.LOG_AGE_HUNG_SEC + 10)
            os.utime(d.engine_log, (old_mtime, old_mtime))
            with patch.object(d, "_alert") as mock_alert:
                d._check_engine_liveness()
                mock_alert.assert_called_once()
                self.assertTrue(d.signal_path.exists())
                data = json.loads(d.signal_path.read_text())
                self.assertEqual(data["type"], gd.RESTART_SIGNAL_TYPE)

    def test_stale_but_signal_recently_written_no_alert(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_daemon(tmp)
            d.engine_log.write_text("stale")
            old_mtime = time.time() - (gd.LOG_AGE_HUNG_SEC + 10)
            os.utime(d.engine_log, (old_mtime, old_mtime))
            # Pre-write a fresh signal
            gd._write_restart_signal(d.signal_path, "already sent")
            with patch.object(d, "_alert") as mock_alert:
                d._check_engine_liveness()
                mock_alert.assert_not_called()

    def test_missing_log_raises_alert(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_daemon(tmp)
            # Don't create engine_log
            with patch.object(d, "_alert") as mock_alert:
                d._check_engine_liveness()
                mock_alert.assert_called_once()
                self.assertIn("tidak ditemukan", mock_alert.call_args[0][0])


class TestErrorScan(unittest.TestCase):
    def test_new_error_triggers_alert(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_daemon(tmp)
            d.engine_log.write_text("INFO all good\nERROR something broke\n")
            with patch.object(d, "_alert") as mock_alert:
                d._scan_errors()
                mock_alert.assert_called_once()

    def test_repeated_error_respects_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_daemon(tmp)
            d.engine_log.write_text("ERROR same error line\n")
            with patch.object(d, "_alert") as mock_alert:
                d._scan_errors()
                d._scan_errors()  # second scan — cooldown not expired
                self.assertEqual(mock_alert.call_count, 1)

    def test_clean_log_no_alert(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_daemon(tmp)
            d.engine_log.write_text("INFO ok\nDEBUG verbose\n")
            with patch.object(d, "_alert") as mock_alert:
                d._scan_errors()
                mock_alert.assert_not_called()


class TestFillDroughtCheck(unittest.TestCase):
    def test_no_alert_when_fills_recent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(tmp)
            import datetime
            ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"
            _insert_fill(db, ts)
            d = _make_daemon(tmp)
            d.db_path = db
            with patch.object(d, "_alert") as mock_alert:
                d._check_fill_drought()
                mock_alert.assert_not_called()

    def test_no_alert_when_gap_but_gate_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(tmp)
            _insert_fill(db, "2026-07-01T00:00:00+00:00")  # very old
            _set_state(db, "e1_decay_gate:PEPE/USDC", "decay_gate pair=PEPE/USDC")
            d = _make_daemon(tmp, pairs=["PEPE/USDC"])
            d.db_path = db
            with patch.object(d, "_alert") as mock_alert:
                d._check_fill_drought()
                mock_alert.assert_not_called()

    def test_alert_when_gap_and_no_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(tmp)
            _insert_fill(db, "2026-07-01T00:00:00+00:00")  # very old
            # No gate set
            d = _make_daemon(tmp, pairs=["PEPE/USDC"])
            d.db_path = db
            with patch.object(d, "_alert") as mock_alert:
                d._check_fill_drought()
                mock_alert.assert_called_once()
                self.assertIn("Drought", mock_alert.call_args[0][0])

    def test_alert_respects_1h_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(tmp)
            _insert_fill(db, "2026-07-01T00:00:00+00:00")
            d = _make_daemon(tmp, pairs=["PEPE/USDC"])
            d.db_path = db
            d._drought_alert_ts = time.time()  # cooldown active
            with patch.object(d, "_alert") as mock_alert:
                d._check_fill_drought()
                mock_alert.assert_not_called()


class TestServiceCheck(unittest.TestCase):
    @patch("anantara.sodex_guardian_daemon._service_is_active", return_value=True)
    def test_active_services_no_alert(self, _):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_daemon(tmp)
            with patch.object(d, "_alert") as mock_alert:
                d._check_services()
                mock_alert.assert_not_called()

    @patch("anantara.sodex_guardian_daemon._restart_service", return_value=True)
    @patch("anantara.sodex_guardian_daemon._service_is_active", return_value=False)
    def test_dead_service_triggers_restart_and_alert(self, _active, _restart):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_daemon(tmp)
            with patch.object(d, "_alert") as mock_alert:
                d._check_services()
                self.assertTrue(_restart.called)
                self.assertGreater(mock_alert.call_count, 0)

    @patch("anantara.sodex_guardian_daemon._restart_service", return_value=False)
    @patch("anantara.sodex_guardian_daemon._service_is_active", return_value=False)
    def test_dead_service_cooldown_suppresses_repeat_alert(self, _active, _restart):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_daemon(tmp)
            # Pre-set alert time for all services
            for svc in gd.WATCHED_SERVICES:
                d._svc_alert[svc] = time.time()
            with patch.object(d, "_alert") as mock_alert:
                d._check_services()
                mock_alert.assert_not_called()


class TestSignalConstants(unittest.TestCase):
    def test_restart_signal_type_is_stuck_idle(self):
        self.assertEqual(gd.RESTART_SIGNAL_TYPE, "stuck-idle")

    def test_log_age_hung_is_90s(self):
        self.assertEqual(gd.LOG_AGE_HUNG_SEC, 90)

    def test_watched_services_includes_watchdog_and_sentinel(self):
        self.assertIn("sodex-twin-watchdog", gd.WATCHED_SERVICES)
        self.assertIn("sodex-sentinel", gd.WATCHED_SERVICES)

    def test_drought_anomaly_min_is_180(self):
        self.assertEqual(gd.DROUGHT_ANOMALY_MIN, 180)

    def test_fast_cycle_60s(self):
        self.assertEqual(gd.FAST_CYCLE_SEC, 60)

    def test_slow_cycle_1200s(self):
        self.assertEqual(gd.SLOW_CYCLE_SEC, 1200)


class TestPrintStatus(unittest.TestCase):
    """Smoke test for --status mode."""
    @patch("anantara.sodex_guardian_daemon._service_is_active", return_value=True)
    def test_status_runs_without_error(self, _):
        with tempfile.TemporaryDirectory() as tmp:
            db = _make_db(tmp)
            eng = Path(tmp) / "twin_live.log"
            eng.write_text("alive")
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                gd._print_status(db, eng)
            out = buf.getvalue()
            self.assertIn("Guardian Status", out)
            self.assertIn("alive", out)


if __name__ == "__main__":
    unittest.main()
