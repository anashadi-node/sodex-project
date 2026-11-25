"""Tests for sodex_e1_autopilot — per-minute Monitor+Evaluate+Repair."""
import importlib.util
import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

_SPEC = importlib.util.spec_from_file_location(
    "sodex_e1_autopilot",
    str(Path(__file__).resolve().parent.parent / "scripts" / "sodex_e1_autopilot.py"))
ap = importlib.util.module_from_spec(_SPEC)
import sys as _s; _s.argv = ["test"]
_SPEC.loader.exec_module(ap)


class EvaluateTests(TestCase):
    def test_no_loss_ok_when_net_positive(self):
        m = {"e1_net_rate": 0.0004, "volume_target_pct": 80.0}
        ev = ap.evaluate(m)
        self.assertTrue(ev["no_loss_ok"])

    def test_no_loss_fail_when_net_negative(self):
        m = {"e1_net_rate": -0.0003, "volume_target_pct": 80.0}
        ev = ap.evaluate(m)
        self.assertFalse(ev["no_loss_ok"])

    def test_on_track_volume_at_100pct(self):
        m = {"e1_net_rate": 0.0001, "volume_target_pct": 105.0}
        ev = ap.evaluate(m)
        self.assertTrue(ev["on_track_volume"])

    def test_target_constant_is_1_15M(self):
        self.assertEqual(ap.WEEKLY_VOLUME_TARGET, 550_000)  # user revised 2026-07-22

    def test_per_minute_interval(self):
        self.assertLessEqual(ap.CHECK_INTERVAL, 60, "harus per-menit")

    def test_read_intel_regime_uses_down_forecast_before_score(self):
        old_project = ap.PROJECT
        try:
            with tempfile.TemporaryDirectory() as tmp:
                ap.PROJECT = Path(tmp)
                intel_dir = ap.PROJECT / "freqtrade_user_data" / "data" / "binance" / "intelligence"
                intel_dir.mkdir(parents=True)
                today = datetime.now(timezone.utc).strftime("%Y%m%d")
                (intel_dir / f"intel_{today}.jsonl").write_text(json.dumps({
                    "ts": time.time(),
                    "composite_score": 62.0,
                    "fc_BTC_dir_enc": -1,
                    "fc_BTC_conf": 0.77,
                    "fc_BTC_agreement": 0.88,
                    "event_risk_level": "",
                }) + "\n")

                self.assertEqual(ap._read_intel_regime(), "BEAR")
        finally:
            ap.PROJECT = old_project

    def test_zero_fill_does_not_restart_when_target_policy_blocks_e2(self):
        with patch.object(ap, "_q") as q, \
             patch.object(ap, "_target_policy_expects_fills", return_value=False), \
             patch.object(ap, "_write_restart_signal") as wr:
            q.side_effect = [
                [(0,)],  # fills_20m
                [(0,)],  # rts_20m
                [("2026-06-24T00:00:00+00:00",)],  # last fill old
                [(0,)],  # fills_30m
            ]

            action = ap._check_daemon_stuck({"engine_alive": True})

        self.assertEqual(action, "zero_fill_policy_blocked")
        wr.assert_not_called()
