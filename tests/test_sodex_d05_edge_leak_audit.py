import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sodex_d05_edge_leak_audit as A


def trades(blocks_and_vals):
    return [{"block": b, "excess": v, "pair": "X", "side": "LONG", "regime": "M", "exit_reason": "TP", "hold_hours": 10} for b, v in blocks_and_vals]


class TestArmSplit(unittest.TestCase):
    def test_random_label_maps_to_control(self):
        self.assertEqual(A.arm_of({"track": "RANDOM"}), A.ARM_CONTROL)
        self.assertEqual(A.arm_of({"track": "random"}), A.ARM_CONTROL)

    def test_missing_or_signal_label_maps_to_signal(self):
        self.assertEqual(A.arm_of({}), A.ARM_SIGNAL)
        self.assertEqual(A.arm_of({"track": None}), A.ARM_SIGNAL)
        self.assertEqual(A.arm_of({"track": "SIGNAL"}), A.ARM_SIGNAL)


class TestBhFdr(unittest.TestCase):
    def test_known_qvalues(self):
        qs = A.bh_fdr([0.001, 0.01, 0.02, 0.5], q=0.10)
        self.assertAlmostEqual(qs[0], 0.004, places=6)
        self.assertAlmostEqual(qs[1], 0.02, places=6)
        self.assertAlmostEqual(qs[2], 0.0266667, places=5)
        self.assertAlmostEqual(qs[3], 0.5, places=6)

    def test_empty(self):
        self.assertEqual(A.bh_fdr([]), [])

    def test_monotone_in_rank(self):
        qs = A.bh_fdr([0.0001, 0.2, 0.9])
        self.assertLessEqual(qs[0], qs[1])
        self.assertLessEqual(qs[1], qs[2])


class TestClusterBootstrap(unittest.TestCase):
    def test_deterministic_same_seed(self):
        t = trades([(1, 0.01), (1, 0.02), (2, -0.01), (3, 0.03), (3, 0.0)])
        a = A.cluster_bootstrap(t, n_iter=500, seed=7)
        b = A.cluster_bootstrap(t, n_iter=500, seed=7)
        self.assertEqual(a["ci95"], b["ci95"])

    def test_ci_ordered_and_point_is_row_mean(self):
        t = trades([(1, 0.01), (2, 0.02), (3, 0.03)])
        r = A.cluster_bootstrap(t, n_iter=1000, seed=1)
        self.assertLessEqual(r["ci95"][0], r["ci95"][1])
        self.assertAlmostEqual(r["mean"], 0.02, places=12)
        self.assertEqual(r["n_blocks"], 3)
        self.assertEqual(r["n"], 3)

    def test_empty_input(self):
        r = A.cluster_bootstrap([])
        self.assertIsNone(r["mean"])
        self.assertEqual(r["n_blocks"], 0)


class TestBucketTable(unittest.TestCase):
    def test_min_n_flag_and_sort_desc(self):
        t = trades([(1, 0.05), (2, 0.05), (3, -0.01)])
        for x in t[:2]:
            x["pair"] = "BIG"
        t[2]["pair"] = "SMALL"
        rows = A.bucket_table(t, lambda x: x["pair"], min_n=2)
        self.assertEqual(rows[0]["bucket"], "BIG")
        self.assertTrue(rows[0]["meets_min_n"])
        self.assertFalse(rows[1]["meets_min_n"])


class TestSelectionNull(unittest.TestCase):
    def test_deterministic(self):
        t = trades([(i, 0.01 * (i % 3) - 0.01) for i in range(60)])
        a = A.selection_null(t, min_n=5, n_iter=50, seed=3)
        b = A.selection_null(t, min_n=5, n_iter=50, seed=3)
        self.assertEqual(a, b)

    def test_p95_at_least_p50(self):
        t = trades([(i, 0.02 * ((i % 7) - 3)) for i in range(80)])
        r = A.selection_null(t, min_n=5, n_iter=200, seed=11)
        self.assertGreaterEqual(r["p95_bps"], r["p50_bps"])
        self.assertGreaterEqual(r["p99_bps"], r["p95_bps"])


class TestVerdict(unittest.TestCase):
    def test_no_data(self):
        self.assertEqual(A._verdict({"ci95": None}, 5.0), "FAIL_NO_DATA")

    def test_gate_met_when_ci_positive_and_no_gap(self):
        self.assertEqual(A._verdict({"ci95": [0.001, 0.01]}, 0.0), "T1_GATE_MET_PENDING_RISET_CONFIRMATION")

    def test_both_failures_reported(self):
        self.assertEqual(A._verdict({"ci95": [-0.01, 0.01]}, 3.0), "FAIL_CI95_SPANS_ZERO_AND_COST_2X_GAP")

    def test_ci_zero_only(self):
        self.assertEqual(A._verdict({"ci95": [-0.01, 0.02]}, -1.0), "FAIL_CI95_SPANS_ZERO")


class TestRender(unittest.TestCase):
    def test_sections_present(self):
        a = {
            "generated_utc": "x", "track": "twoway", "source": "s", "fee_bps": 8.0, "cluster_hours": 30.0,
            "duplication": {"all": {"n_rows": 2, "n_unique": 2, "ratio": 1.0}, "signal": {"n_rows": 1, "n_unique": 1, "ratio": 1.0}},
            "arms": {"n_signal": 1, "n_control": 1, "control_track_label": "RANDOM"},
            "contamination": {"excess_all_bps": 1.0, "excess_signal_only_bps": 2.0, "delta_bps": 1.0},
            "clustered": {"all": {"n": 1, "n_blocks": 1, "mean_bps": 1.0, "ci95_bps": [0.0, 2.0], "p_pos": 0.5},
                          "signal": {"n": 1, "n_blocks": 1, "mean_bps": 2.0, "ci95_bps": [1.0, 3.0], "p_pos": 0.6},
                          "control": {"n": 0}},
            "cost_gate": {"gross_signal_bps": 2.0, "cost_1x_bps": -6.0, "cost_2x_bps": -14.0, "gap_to_2x_bps": 14.0},
            "breakdown": {"symbol": [], "side": [], "regime": [], "exit_reason": []},
            "tests": {"symbol": [], "side": [], "regime": [], "exit_reason": []},
            "selection_null": {"n": 200, "p50_bps": 1.0, "p95_bps": 2.0, "p99_bps": 3.0},
            "verdict": "FAIL_COST_2X_GAP",
        }
        md = A.render_md(a)
        for token in ("Duplication", "Arm split", "Contamination", "Clustered inference", "Negative control", "Safety"):
            self.assertIn(token, md)


if __name__ == "__main__":
    unittest.main()
