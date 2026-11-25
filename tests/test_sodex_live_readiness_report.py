import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sodex_live_readiness_report as report


class TestSodexLiveReadinessReport(unittest.TestCase):
    def test_warmup_blocks_live_until_24h(self):
        data = {
            "funding_archive": {"span_hours": 23.0, "bad_rows": 0, "last_collected_utc": "2026-10-03T00:00:00+00:00"},
            "tracks": [{"track": "x", "passed": True}],
            "funding_map": {"verdict": "READY", "coverage_pct": 100.0},
            "canonical_normalized_target_distance": {"valid": True},
        }
        state = report.readiness_state(data)
        self.assertFalse(state["live_ready"])
        self.assertIn("funding archive warmup 23.00/24h", state["blockers"])
        self.assertEqual(report.warmup_eta(data), "2026-10-03T01:00:00+00:00")

    def test_all_gates_pass_sets_live_ready_true(self):
        data = {
            "funding_archive": {"span_hours": 24.0, "bad_rows": 0},
            "tracks": [{"track": "x", "passed": True}],
            "funding_map": {"verdict": "READY", "coverage_pct": 100.0},
            "canonical_normalized_target_distance": {"valid": True},
        }
        self.assertTrue(report.readiness_state(data)["live_ready"])


if __name__ == "__main__":
    unittest.main()
