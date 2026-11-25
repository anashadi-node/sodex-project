"""Test sodex_live_watchdog — deteksi phantom & untracked position."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sodex_live_watchdog as wd  # noqa: E402


class TestWatchdogReconciliation(unittest.TestCase):
    def setUp(self):
        # Isolasi total dari file produksi — test TIDAK BOLEH menulis ke
        # data/sodex_watchdog_alerts.jsonl asli (ditemukan mencemari log
        # real 2026-09-04, alert CRITICAL palsu dari test run).
        self._tmpdir = tempfile.TemporaryDirectory()
        self._addr_patch = patch.object(wd.s, "ADDRESS", "0xtest")
        self._addr_patch.start()
        self._orig_alert_log = wd.ALERT_LOG
        self._orig_prev_snap = wd.PREV_SNAP
        self._orig_spot_residual_snap = wd.SPOT_RESIDUAL_SNAP
        self._orig_manual_perps_snap = wd.MANUAL_PERPS_SNAP
        self._orig_manual_perps_risk_snap = wd.MANUAL_PERPS_RISK_SNAP
        self._orig_spot_state = wd.SPOT_STATE_FILE
        wd.ALERT_LOG = Path(self._tmpdir.name) / "alerts.jsonl"
        wd.PREV_SNAP = Path(self._tmpdir.name) / "prev.json"
        wd.SPOT_RESIDUAL_SNAP = Path(self._tmpdir.name) / "spot_residuals.json"
        wd.MANUAL_PERPS_SNAP = Path(self._tmpdir.name) / "manual_perps.json"
        wd.MANUAL_PERPS_RISK_SNAP = Path(self._tmpdir.name) / "manual_perps_risk.json"

    def tearDown(self):
        wd.ALERT_LOG = self._orig_alert_log
        wd.PREV_SNAP = self._orig_prev_snap
        wd.SPOT_RESIDUAL_SNAP = self._orig_spot_residual_snap
        wd.MANUAL_PERPS_SNAP = self._orig_manual_perps_snap
        wd.MANUAL_PERPS_RISK_SNAP = self._orig_manual_perps_risk_snap
        wd.SPOT_STATE_FILE = self._orig_spot_state
        self._addr_patch.stop()
        self._tmpdir.cleanup()
    def test_untracked_spot_detected_when_local_state_empty(self):
        wd.SPOT_STATE_FILE = Path(self._tmpdir.name) / "spot.json"
        wd.SPOT_STATE_FILE.write_text(json.dumps({"open": {}}))
        with patch("sodex_realtime_sync.real_spot_balance", return_value=[
            {"coin": "vUSDC", "total": "8"},
            {"coin": "vDOGWIF", "total": "0.01"},
        ]):
            alerts = wd.check_spot_reconciliation()
        self.assertTrue(any("UNTRACKED SPOT" in a["msg"] for a in alerts))

    def test_classified_spot_residual_warns_once_then_quiet(self):
        wd.SPOT_STATE_FILE = Path(self._tmpdir.name) / "spot.json"
        wd.SPOT_STATE_FILE.write_text(json.dumps({"open": {}}))
        balances = [{"coin": "vUSDC", "total": "8"}, {"coin": "vBTC", "total": "0.01"}]
        with patch("sodex_realtime_sync.real_spot_balance", return_value=balances):
            first = wd.check_spot_reconciliation()
        with patch("sodex_realtime_sync.real_spot_balance", return_value=balances):
            second = wd.check_spot_reconciliation()
        self.assertFalse(any(a["level"] == "CRITICAL" for a in first + second))
        self.assertTrue(any("CLASSIFIED SPOT RESIDUAL" in a["msg"] for a in first))
        self.assertFalse(any("CLASSIFIED SPOT RESIDUAL" in a["msg"] for a in second))

    def test_clean_empty_spot_has_no_untracked_alert(self):
        wd.SPOT_STATE_FILE = Path(self._tmpdir.name) / "spot.json"
        wd.SPOT_STATE_FILE.write_text(json.dumps({"open": {}}))
        with patch("sodex_realtime_sync.real_spot_balance", return_value=[
            {"coin": "vUSDC", "total": "50"},
        ]):
            alerts = wd.check_spot_reconciliation()
        self.assertFalse(any("UNTRACKED SPOT" in a["msg"] for a in alerts))

    def test_phantom_detected_when_local_has_no_exchange_match(self):
        """State lokal klaim posisi ETH, tapi exchange 0 posisi -> CRITICAL."""
        with patch.object(wd, "full_sync", return_value={
            "perps_positions": [], "perps_balance": {"total": "100"},
            "spot_vusdc": {"total": "50"}, "address": "0xtest"}):
            with patch.object(wd, "load_local_open_positions", return_value={
                "realwide:ETH": {"pair": "ETH", "qty": 0.01}}):
                alerts, snap = wd.check_reconciliation()
        levels = [a["level"] for a in alerts]
        self.assertIn("CRITICAL", levels)
        self.assertTrue(any("PHANTOM" in a["msg"] for a in alerts))

    def test_unavailable_sync_is_critical_not_empty_account(self):
        with patch.object(wd, "full_sync", return_value=None), \
             patch.object(wd, "check_balance_anomaly", return_value=[]):
            alerts, snap = wd.check_reconciliation()
        self.assertIsNone(snap)
        self.assertEqual([a["level"] for a in alerts], ["CRITICAL"])
        self.assertIn("RECONCILIATION_UNAVAILABLE", alerts[0]["msg"])
        self.assertTrue(wd.check_balance_anomaly(None))

    def test_different_account_is_critical(self):
        with patch.dict(wd.os.environ, {"SODEX_ADDRESS": "0xtarget"}):
            status = wd.snapshot_validity({"address": "0xother"})
        self.assertTrue(any("RECONCILIATION_ACCOUNT" in a["msg"] for a in status))

    def test_account_is_required(self):
        with patch.dict(wd.os.environ, {"SODEX_ADDRESS": ""}):
            self.assertFalse(wd.balances_are_valid({"address": "0xother"}))

    def test_untracked_detected_when_exchange_has_unknown_position(self):
        """Exchange punya posisi real, state lokal kosong -> CRITICAL."""
        with patch.object(wd, "full_sync", return_value={
            "perps_positions": [{"symbol": "SOL-USD", "size": "0.01"}],
            "perps_balance": {"total": "100"}, "spot_vusdc": {"total": "50"},
            "address": "0xtest"}):
            with patch.object(wd, "load_local_open_positions", return_value={}):
                alerts, snap = wd.check_reconciliation()
        self.assertTrue(any("UNTRACKED" in a["msg"] for a in alerts))

    def test_clean_state_no_alerts(self):
        """State lokal dan exchange match (keduanya kosong) -> OK, no CRITICAL."""
        with patch.object(wd, "full_sync", return_value={
            "perps_positions": [], "perps_balance": {"total": "100"},
            "spot_vusdc": {"total": "50"}, "spot_balances": [],
            "perps_open_orders": [], "address": "0xtest"}):
            with patch.object(wd, "load_local_open_positions", return_value={}):
                alerts, snap = wd.check_reconciliation()
        self.assertFalse(any(a["level"] == "CRITICAL" for a in alerts))

        with patch.object(wd, "full_sync", return_value={
            "perps_positions": [], "perps_balance": {"total": "100"},
            "spot_vusdc": {"total": "50"}, "spot_balances": [],
            "perps_open_orders_error": "timeout", "address": "0xtest"}):
            with patch.object(wd, "load_local_open_positions", return_value={}):
                alerts, _ = wd.check_reconciliation()
        self.assertTrue(any("RECONCILIATION_INCOMPLETE" in a["msg"] for a in alerts))

    def test_matched_position_no_phantom_alert(self):
        """State lokal & exchange sama-sama punya ETH -> tidak phantom/untracked."""
        with patch.object(wd, "full_sync", return_value={
            "perps_positions": [{"symbol": "ETH-USD", "size": "0.01"}],
            "perps_balance": {"total": "100"}, "spot_vusdc": {"total": "50"},
            "spot_balances": [], "perps_open_orders": [], "address": "0xtest"}):
            with patch.object(wd, "load_local_open_positions", return_value={
                "realwide:ETH": {"pair": "ETH", "qty": 0.01}}):
                alerts, snap = wd.check_reconciliation()
        self.assertFalse(any(a["level"] == "CRITICAL" for a in alerts))

    def test_classified_manual_perp_warns_once_then_quiet(self):
        payload = {
            "perps_positions": [{"symbol": "AAVE-USD", "size": "0.35"}],
            "perps_balance": {"total": "100"}, "spot_vusdc": {"total": "50"},
            "spot_balances": [], "perps_open_orders": [], "address": "0xtest"}
        with patch.object(wd, "full_sync", return_value=payload):
            with patch.object(wd, "load_local_open_positions", return_value={}):
                first, _ = wd.check_reconciliation()
        with patch.object(wd, "full_sync", return_value=payload):
            with patch.object(wd, "load_local_open_positions", return_value={}):
                second, _ = wd.check_reconciliation()
        self.assertFalse(any(a["level"] == "CRITICAL" for a in first + second))
        self.assertTrue(any("CLASSIFIED MANUAL PERP" in a["msg"] for a in first))
        self.assertFalse(any("CLASSIFIED MANUAL PERP" in a["msg"] for a in second))

    def test_classified_manual_perp_loss_warning_when_pnl_breaches_floor(self):
        payload = {
            "perps_positions": [{
                "symbol": "AAVE-USD", "size": "0.35", "side": "LONG",
                "entry_price": "128.43", "mark_price": "120.35",
            }],
            "perps_balance": {"total": "100"}, "spot_vusdc": {"total": "50"},
            "spot_balances": [], "perps_open_orders": [], "address": "0xtest"}
        with patch.object(wd, "full_sync", return_value=payload):
            with patch.object(wd, "load_local_open_positions", return_value={}):
                alerts, _ = wd.check_reconciliation()
        self.assertFalse(any(a["level"] == "CRITICAL" for a in alerts))
        self.assertTrue(any("CLASSIFIED MANUAL PERP LOSS" in a["msg"] for a in alerts))

    def test_classified_manual_perp_loss_warning_uses_perps_mark_snapshot(self):
        payload = {
            "perps_positions": [{"symbol": "AAVE-USD", "size": "0.35", "avgEntryPrice": "128.43"}],
            "perps_marks": {"AAVE-USD": {"markPrice": 120.35}},
            "perps_balance": {"total": "100"}, "spot_vusdc": {"total": "50"},
            "spot_balances": [], "perps_open_orders": [], "address": "0xtest"}
        with patch.object(wd, "full_sync", return_value=payload):
            with patch.object(wd, "load_local_open_positions", return_value={}):
                alerts, _ = wd.check_reconciliation()
        self.assertTrue(any("CLASSIFIED MANUAL PERP LOSS" in a["msg"] for a in alerts))

    def test_classified_manual_perp_size_change_stays_critical(self):
        with patch.object(wd, "full_sync", return_value={
            "perps_positions": [{"symbol": "AAVE-USD", "size": "0.5"}],
            "perps_balance": {"total": "100"}, "spot_vusdc": {"total": "50"},
            "spot_balances": [], "perps_open_orders": [], "address": "0xtest"}):
            with patch.object(wd, "load_local_open_positions", return_value={}):
                alerts, _ = wd.check_reconciliation()
        self.assertTrue(any(a["level"] == "CRITICAL" and "UNTRACKED" in a["msg"] for a in alerts))


class TestBalanceAnomaly(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_prev_snap = wd.PREV_SNAP
        self._orig_alert_log = wd.ALERT_LOG
        wd.PREV_SNAP = Path(self._tmpdir.name) / "prev.json"
        wd.ALERT_LOG = Path(self._tmpdir.name) / "alerts.jsonl"

    def tearDown(self):
        wd.PREV_SNAP = self._orig_prev_snap
        wd.ALERT_LOG = self._orig_alert_log
        self._tmpdir.cleanup()

    def test_large_jump_triggers_warning(self):
        wd.PREV_SNAP.write_text(json.dumps({"perps": 100.0, "spot": 50.0}))
        alerts = wd.check_balance_anomaly({
            "perps_balance": {"total": "105.0"}, "spot_vusdc": {"total": "50.0"}})
        self.assertTrue(any(a["level"] == "WARNING" for a in alerts))

    def test_small_change_no_warning(self):
        wd.PREV_SNAP.write_text(json.dumps({"perps": 100.0, "spot": 50.0}))
        alerts = wd.check_balance_anomaly({
            "perps_balance": {"total": "100.05"}, "spot_vusdc": {"total": "50.0"}})
        self.assertFalse(any(a["level"] == "WARNING" for a in alerts))


if __name__ == "__main__":
    unittest.main()
