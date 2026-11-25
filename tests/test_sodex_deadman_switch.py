import importlib.util
import json
import tempfile
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


_SPEC = importlib.util.spec_from_file_location(
    "sodex_deadman_switch",
    str(Path(__file__).resolve().parent.parent / "scripts" / "sodex_deadman_switch.py"),
)
deadman = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(deadman)


class SodexDeadmanSwitchTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sodex_deadman_test_"))
        deadman.LOG = self.tmp / "deadman.log"
        deadman.RESTART_SIGNAL = self.tmp / "GUARDIAN_RESTART_SIGNAL"
        deadman.ENGINE_ALIVE_TS = self.tmp / "engine_last_alive.json"
        deadman.ENGINE_LOG = self.tmp / "twin_live.log"
        deadman.PNL_HALT = self.tmp / "PNL_HALT"
        deadman.SAFETY_HALT = self.tmp / "SAFETY_HALT"

    def test_no_fill_is_not_restart_when_policy_blocks_e2_and_heartbeat_is_fresh(self):
        deadman.ENGINE_ALIVE_TS.write_text(json.dumps({"ts": time.time()}))
        with patch.object(deadman, "daemon_alive", return_value=True), \
             patch.object(deadman, "get_last_fill_age_minutes", return_value=90.0), \
             patch.object(deadman, "load_target_policy", return_value={
                 "decision": "BLOCK_E2_E1_RESEARCH_ONLY",
                 "limits": {"max_e2_hourly_volume_usd": 0.0},
             }):
            result = deadman.evaluate_deadman()

        self.assertEqual(result["decision"], "NO_RESTART_POLICY_BLOCK")
        self.assertFalse(result["restart"])

    def test_stale_heartbeat_restarts_even_if_fill_age_is_unknown(self):
        deadman.ENGINE_ALIVE_TS.write_text(json.dumps({"ts": time.time() - 900}))
        with patch.object(deadman, "daemon_alive", return_value=True), \
             patch.object(deadman, "get_last_fill_age_minutes", return_value=999.0), \
             patch.object(deadman, "load_target_policy", return_value={
                 "decision": "CAPPED_CATCH_UP_ALLOWED",
                 "limits": {"max_e2_hourly_volume_usd": 1000.0},
             }):
            result = deadman.evaluate_deadman()

        self.assertEqual(result["decision"], "RESTART_HEARTBEAT_STALE")
        self.assertTrue(result["restart"])

    def test_fresh_live_log_prevents_restart_with_stale_heartbeat_file(self):
        deadman.ENGINE_ALIVE_TS.write_text(json.dumps({"ts": time.time() - 900}))
        deadman.ENGINE_LOG.write_text("engine iteration complete\n")
        with patch.object(deadman, "daemon_alive", return_value=True), \
             patch.object(deadman, "get_last_fill_age_minutes", return_value=2.0), \
             patch.object(deadman, "load_target_policy", return_value={
                 "decision": "CAPPED_CATCH_UP_ALLOWED",
                 "limits": {"max_e2_hourly_volume_usd": 1000.0},
             }):
            result = deadman.evaluate_deadman()

        self.assertEqual(result["decision"], "OK")
        self.assertFalse(result["restart"])

    def test_halt_file_never_restarts_daemon(self):
        deadman.PNL_HALT.write_text("halt")
        with patch.object(deadman, "daemon_alive", return_value=True), \
             patch.object(deadman, "get_last_fill_age_minutes", return_value=90.0), \
             patch.object(deadman, "load_target_policy", return_value={
                 "decision": "CAPPED_CATCH_UP_ALLOWED",
                 "limits": {"max_e2_hourly_volume_usd": 1000.0},
             }):
            result = deadman.evaluate_deadman()

        self.assertEqual(result["decision"], "NO_RESTART_HALT_ACTIVE")
        self.assertFalse(result["restart"])
