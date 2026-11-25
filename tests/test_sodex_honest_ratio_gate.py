import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import sodex_honest_ratio_gate as gate


class HonestRatioGateTests(unittest.TestCase):
    def test_systemd_inline_comments_are_removed_before_engine_import(self):
        with patch.dict(os.environ, {
            "TE_PVE_MAX_NOTIONAL": "60  # bounded clip",
            "UNRELATED_VALUE": "keep#literal",
        }, clear=False):
            gate._normalize_systemd_environment()
            self.assertEqual(os.environ["TE_PVE_MAX_NOTIONAL"], "60")
            self.assertEqual(os.environ["UNRELATED_VALUE"], "keep#literal")

    def test_env_float_accepts_systemd_inline_comment(self):
        with patch.dict(os.environ, {"TEST_RATIO": "8000  # operator floor"}):
            self.assertEqual(gate._env_float("TEST_RATIO", "1"), 8000.0)

    def test_unreadable_account_value_is_not_treated_as_zero_cost(self):
        result = gate.evaluate_ratio(260.0, None, 5000.0, 8000.0, 2000.0)
        self.assertFalse(result["evaluable"])
        self.assertIsNone(result["cost"])
        self.assertIsNone(result["ratio"])
        self.assertFalse(result["breached"])

    def test_ratio_below_floor_breaches_after_volume_gate(self):
        result = gate.evaluate_ratio(260.0, 259.0, 7000.0, 8000.0, 2000.0)
        self.assertTrue(result["evaluable"])
        self.assertEqual(result["ratio"], 7000.0)
        self.assertTrue(result["breached"])

    def test_incomplete_24h_window_does_not_breach(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            status_file = root / "status.json"
            state.write_text(json.dumps({
                "ts_start": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
                "av_start": 260.0,
                "floor": 4500,
                "min_vol": 3000,
                "ratio_policy": "fixed_24h_window",
                "window_hours": 24,
            }))
            with patch.object(gate, "STATE_FILE", state), \
                 patch.object(gate, "STATUS_FILE", status_file), \
                 patch.object(gate, "PVE_PAUSE_FILE", root / "pause"), \
                 patch.object(gate, "_perps_av_now", return_value=259.0), \
                 patch.object(gate, "_pve_cum_volume", return_value=3000.0), \
                 patch.object(gate, "_pve_rt_stats", return_value={
                     "n_rt": 1, "rt_net": -1.0, "fees": 0.1, "n_fill": 2,
                 }):
                result = gate.compute_status()

        self.assertFalse(result["window_complete"])
        self.assertFalse(result["breached"])
        self.assertEqual(result["ratio"], 3000.0)

    def test_completed_24h_window_keeps_breach(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            state.write_text(json.dumps({
                "ts_start": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
                "av_start": 260.0,
                "floor": 4500,
                "min_vol": 3000,
                "ratio_policy": "fixed_24h_window",
                "window_hours": 24,
            }))
            with patch.object(gate, "STATE_FILE", state), \
                 patch.object(gate, "STATUS_FILE", root / "status.json"), \
                 patch.object(gate, "PVE_PAUSE_FILE", root / "pause"), \
                 patch.object(gate, "_perps_av_now", return_value=259.0), \
                 patch.object(gate, "_pve_cum_volume", return_value=3000.0), \
                 patch.object(gate, "_pve_rt_stats", return_value={
                     "n_rt": 1, "rt_net": -1.0, "fees": 0.1, "n_fill": 2,
                 }):
                result = gate.compute_status()

        self.assertTrue(result["window_complete"])
        self.assertTrue(result["breached"])

    def test_completed_window_is_archived_and_next_baseline_is_created(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_path = root / "state.json"
            history_path = root / "history.jsonl"
            state_path.write_text(json.dumps({
                "capital_usd": 30,
                "loss_cap_usd": 4,
            }))
            status = {
                "ts": "2026-07-21T12:00:00+00:00",
                "window_complete": True,
                "evaluable": True,
                "av_now": 259.5,
                "floor": 4500,
                "min_vol": 3000,
                "window_hours": 24,
                "ratio": 5000,
            }
            with patch.object(gate, "STATE_FILE", state_path), \
                 patch.object(gate, "HISTORY_FILE", history_path), \
                 patch.object(gate, "_pve_cum_volume", return_value=12345.0):
                new_state = gate._archive_and_roll_window(status)

            self.assertEqual(json.loads(history_path.read_text())["ratio"], 5000)
            self.assertEqual(new_state["av_start"], 259.5)
            self.assertEqual(new_state["vol_start"], 12345.0)
            self.assertEqual(new_state["ratio_policy"], "fixed_24h_window")

    def test_activate_pause_writes_typed_restart_once(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pause = root / "PVE_PAUSE"
            restart = root / "GUARDIAN_RESTART_SIGNAL"
            with patch.object(gate, "PVE_PAUSE_FILE", pause), \
                 patch.object(gate, "RESTART_SIGNAL", restart):
                status = {"ts": "2026-07-20T00:00:00+00:00"}
                self.assertTrue(gate._activate_pause(status, "ratio unavailable"))
                self.assertFalse(gate._activate_pause(status, "duplicate"))
            self.assertEqual(json.loads(pause.read_text())["reason"], "ratio unavailable")
            self.assertEqual(json.loads(restart.read_text())["type"], "honest-ratio-gate")

    def test_enforce_status_reflects_pause_created_same_cycle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            status_file = root / "status.json"
            status = {
                "ts": "2026-07-20T00:00:00+00:00", "evaluable": True,
                "breached": True, "ratio": 7700.0, "floor": 8000.0,
                "vol": 6000.0, "cost": 0.78, "fees": 0.7,
                "rt_net": -0.2, "n_rt": 20, "elapsed_min": 60,
                "pve_pause_active": False,
            }
            with patch.object(gate, "compute_status", return_value=status), \
                 patch.object(gate, "PVE_PAUSE_FILE", root / "PVE_PAUSE"), \
                 patch.object(gate, "RESTART_SIGNAL", root / "restart.json"), \
                 patch.object(gate, "STATUS_FILE", status_file), \
                 patch.object(gate, "_tg_send", return_value=True):
                result = gate.enforce()

            self.assertTrue(result["pve_pause_active"])
            self.assertTrue(json.loads(status_file.read_text())["pve_pause_active"])

    def test_recovery_clears_only_owned_pause_with_headroom(self):
        with tempfile.TemporaryDirectory() as td:
            pause = Path(td) / "PVE_PAUSE"
            status = {
                "evaluable": True, "vol_gate_met": True, "breached": False,
                "ratio": 7460.0, "floor": 7100.0, "cost": 1.0,
            }
            pause.write_text(json.dumps({"source": "sodex_honest_ratio_gate"}))
            with patch.object(gate, "PVE_PAUSE_FILE", pause), \
                 patch.object(gate, "DEFAULT_RESUME_HEADROOM", 1.05):
                self.assertTrue(gate._clear_owned_pause_if_recovered(status))
            self.assertFalse(pause.exists())
            self.assertEqual(status["resume_floor"], 7455.0)

    def test_recovery_preserves_foreign_pause(self):
        with tempfile.TemporaryDirectory() as td:
            pause = Path(td) / "PVE_PAUSE"
            pause.write_text(json.dumps({"source": "sodex_safety_guardian"}))
            status = {
                "evaluable": True, "vol_gate_met": True, "breached": False,
                "ratio": 9000.0, "floor": 7100.0, "cost": 1.0,
            }
            with patch.object(gate, "PVE_PAUSE_FILE", pause):
                self.assertFalse(gate._clear_owned_pause_if_recovered(status))
            self.assertTrue(pause.exists())

    def test_recovery_requires_headroom(self):
        with tempfile.TemporaryDirectory() as td:
            pause = Path(td) / "PVE_PAUSE"
            pause.write_text(json.dumps({"source": "sodex_honest_ratio_gate"}))
            status = {
                "evaluable": True, "vol_gate_met": True, "breached": False,
                "ratio": 7200.0, "floor": 7100.0, "cost": 1.0,
            }
            with patch.object(gate, "PVE_PAUSE_FILE", pause), \
                 patch.object(gate, "DEFAULT_RESUME_HEADROOM", 1.05):
                self.assertFalse(gate._clear_owned_pause_if_recovered(status))
            self.assertTrue(pause.exists())


if __name__ == "__main__":
    unittest.main()
