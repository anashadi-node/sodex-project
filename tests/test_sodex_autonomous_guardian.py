import importlib.util
import json
import tempfile
from pathlib import Path
from unittest import TestCase


_SPEC = importlib.util.spec_from_file_location(
    "sodex_autonomous_guardian",
    str(Path(__file__).resolve().parent.parent / "scripts" / "sodex_autonomous_guardian.py"),
)
guardian = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(guardian)


class SodexAutonomousGuardianTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sodex_guardian_test_"))
        guardian.LOG = self.tmp / "guardian.log"
        guardian.RESTART_SIGNAL = self.tmp / "GUARDIAN_RESTART_SIGNAL"
        guardian.MONITOR_EVAL_LATEST = self.tmp / "latest.json"
        guardian.TG_TOKEN = ""
        guardian.TG_CHAT = ""
        guardian.AUTO_RESTART_ENABLED = True

    def test_monitor_eval_repair_plan_writes_restart_signal(self):
        guardian.MONITOR_EVAL_LATEST.write_text(json.dumps({
            "monitor_risk": {"level": "RED", "score": 78},
            "repair_plan": {
                "watchdog_restart_signal": True,
                "actions": [{
                    "type": "WATCHDOG_RESTART_SIGNAL",
                    "reason": ["fills_without_closed_rt", "stale_last_fill"],
                }],
            },
        }))

        result = guardian.check_monitor_eval_repair()

        self.assertTrue(result["active"])
        self.assertEqual(result["action"], "restart-signal:monitor-eval-repair")
        payload = json.loads(guardian.RESTART_SIGNAL.read_text())
        self.assertEqual(payload["type"], "monitor-eval-repair")
        self.assertIn("fills_without_closed_rt", payload["message"])

    def test_monitor_eval_without_repair_signal_is_noop(self):
        guardian.MONITOR_EVAL_LATEST.write_text(json.dumps({
            "monitor_risk": {"level": "GREEN", "score": 0},
            "repair_plan": {"watchdog_restart_signal": False, "actions": []},
        }))

        result = guardian.check_monitor_eval_repair()

        self.assertFalse(result["active"])
        self.assertFalse(guardian.RESTART_SIGNAL.exists())
