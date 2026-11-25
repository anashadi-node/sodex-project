import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sodex_d04_blocker_rca as rca


def _result(**over):
    r = {
        "wr": 0.4278,
        "excess_mean": 0.001274,
        "ci95": [-0.00099, 0.00353],
        "cost_stress": {"1.0": {"mean": 0.000474}, "2.0": {"mean": -0.000326}},
        "dsr": {"dsr": 0.42},
        "checks": {"net_pos_1x": True, "net_pos_2x": False, "ci95_lower_positive": False, "dsr_passed": False, "beta_neutral": True},
        "per_group_t": {
            "DOGE": {"n": 43, "mean": 0.0026, "t": 0.84},
            "PUMP": {"n": 15, "mean": -0.0087, "t": -3.6},
            "BTC": {"n": 31, "mean": -0.0001, "t": -0.1},
        },
    }
    r.update(over)
    return r


class TestD04BlockerRca(unittest.TestCase):
    def test_only_failing_checks_listed_with_gap(self):
        fails = rca.failing_checks(_result())
        names = [c["check"] for c in fails]
        self.assertNotIn("net_pos_1x", names)
        self.assertIn("net_pos_2x", names)
        gap = next(c["gap_bps"] for c in fails if c["check"] == "net_pos_2x")
        self.assertAlmostEqual(gap, 16.0 - 12.74, places=1)

    def test_all_pass_result_has_no_failing_checks(self):
        ok = _result(
            excess_mean=0.005,
            ci95=[0.001, 0.009],
            cost_stress={"1.0": {"mean": 0.0042}, "2.0": {"mean": 0.0034}},
            dsr={"dsr": 0.97},
            checks={"net_pos_1x": True, "net_pos_2x": True, "ci95_lower_positive": True, "dsr_passed": True, "beta_neutral": True},
        )
        self.assertEqual(rca.failing_checks(ok), [])

    def test_fee_drag_is_eight_bps(self):
        self.assertAlmostEqual(rca.fee_drag_bps(_result()), -8.0, places=2)

    def test_symbol_drag_ranks_worst_total_first(self):
        worst = rca.symbol_drag(_result(), top_n=2)
        self.assertEqual(worst[0]["symbol"], "PUMP")
        self.assertLess(worst[0]["contrib_bps"], 0)

    def test_nearest_track_prefers_fewest_failing_checks(self):
        blockers = [
            rca.track_blocker({"track": "swing", "n": 443, "result": _result(checks={"net_pos_1x": False, "net_pos_2x": False, "ci95_lower_positive": False, "dsr_passed": False, "beta_neutral": True})}),
            rca.track_blocker({"track": "twoway", "n": 374, "result": _result()}),
        ]
        near = rca.nearest_track(blockers)
        self.assertEqual(near["track"], "twoway")

    def test_forward_archive_ready_threshold_is_24h(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "rates.jsonl"
            short = [{"collected_utc": f"2026-10-02T{h:02d}:00:00+00:00", "venue_symbol": "BTC-USD"} for h in range(0, 5)]
            p.write_text("\n".join(json.dumps(r) for r in short))
            self.assertEqual(rca.forward_archive_state(p)["verdict"], "WARMING_UP")
            long = [{"collected_utc": f"2026-10-0{2 + h // 24}T{h % 24:02d}:00:00+00:00", "venue_symbol": "BTC-USD"} for h in range(0, 30)]
            p.write_text("\n".join(json.dumps(r) for r in long))
            state = rca.forward_archive_state(p)
            self.assertEqual(state["verdict"], "READY")
            self.assertGreaterEqual(state["span_hours"], 24.0)

    def test_build_rca_fails_t1_when_any_track_fails(self):
        harness = {"generated_utc": "2026-10-03T00:00:00+00:00", "tracks": [{"track": "swing", "n": 1, "grade": {"passed": False}, "result": _result()}]}
        out = rca.build_rca(harness, {"verdict": "FAIL_CLOSED", "n_missing": 42}, {"verdict": "READY", "span_hours": 30.0})
        self.assertEqual(out["t1_status"], "FAIL")
        self.assertIn("BLOCKER_RCA", out["verdict"])

    def test_build_rca_passes_only_when_all_tracks_pass(self):
        ok = _result(
            excess_mean=0.005,
            ci95=[0.001, 0.009],
            cost_stress={"1.0": {"mean": 0.0042}, "2.0": {"mean": 0.0034}},
            dsr={"dsr": 0.97},
            checks={"net_pos_1x": True, "net_pos_2x": True, "ci95_lower_positive": True, "dsr_passed": True, "beta_neutral": True},
        )
        harness = {"tracks": [{"track": "twoway", "n": 10, "grade": {"passed": True}, "result": ok}]}
        out = rca.build_rca(harness, {}, {"verdict": "READY"})
        self.assertEqual(out["t1_status"], "PASS")
        self.assertIn("HUMAN", out["verdict"])

    def test_render_md_lists_every_track(self):
        harness = {"tracks": [
            {"track": "swing", "n": 443, "grade": {"passed": False}, "result": _result()},
            {"track": "twoway", "n": 374, "grade": {"passed": False}, "result": _result()},
        ]}
        out = rca.build_rca(harness, {}, {"verdict": "READY"})
        md = rca.render_md(out)
        self.assertIn("swing", md)
        self.assertIn("twoway", md)
        self.assertIn("Binding constraint", md)


if __name__ == "__main__":
    unittest.main()
