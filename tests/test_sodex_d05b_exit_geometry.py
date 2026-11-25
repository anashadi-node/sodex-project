import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sodex_d05b_exit_geometry as G


def trade(reason, excess, block=1, hold=10.0, tp=0.035, sl=0.02):
    return {
        "pair": "X", "side": "LONG", "exit_reason": reason, "hold_hours": hold,
        "realized_dist": abs(excess), "excess": excess, "block": block,
        "tp_dist": tp, "sl_dist": sl, "rr": tp / sl if sl else None,
    }


class TestPlanned(unittest.TestCase):
    def test_planned_rr_from_prices(self):
        r = {"entry_price": 100.0, "tp_price": 104.0, "sl_price": 98.0}
        p = G._planned(r)
        self.assertAlmostEqual(p["tp_dist"], 0.04, places=10)
        self.assertAlmostEqual(p["sl_dist"], 0.02, places=10)
        self.assertAlmostEqual(p["rr"], 2.0, places=10)

    def test_planned_returns_none_on_bad_input(self):
        self.assertIsNone(G._planned({"entry_price": 0, "tp_price": 1, "sl_price": 1}))
        self.assertIsNone(G._planned({"entry_price": 100, "tp_price": None, "sl_price": 98}))
        self.assertIsNone(G._planned({"entry_price": 100, "tp_price": 100, "sl_price": 98}))


class TestAccounting(unittest.TestCase):
    def test_outcome_determined_flag(self):
        self.assertTrue(G.reasontype("TP"))
        self.assertTrue(G.reasontype("SL"))
        self.assertFalse(G.reasontype("TIME_30H"))
        self.assertFalse(G.reasontype("UNKNOWN"))

    def test_contribution_sums_to_mean(self):
        trades = [trade("TP", 0.02), trade("TP", 0.01), trade("SL", -0.01), trade("TIME_30H", -0.001)]
        acc = G.exit_accounting(trades)
        total = sum(r["contrib_to_mean_bps"] for r in acc)
        self.assertAlmostEqual(total, 47.5, places=1)

    def test_time_bucket_marked_actionable(self):
        acc = G.exit_accounting([trade("TP", 0.02), trade("TIME_30H", -0.001)])
        time_row = next(r for r in acc if r["exit_reason"] == "TIME_30H")
        self.assertFalse(time_row["outcome_determined"])


class TestGeometry(unittest.TestCase):
    def test_breakeven_wr_from_observed_tp_sl(self):
        trades = [trade("TP", 0.035), trade("TP", 0.035), trade("SL", -0.02), trade("SL", -0.02)]
        g = G.geometry(trades)
        # l/(g+l) with g=0.035, l=0.02 -> 0.3636
        self.assertAlmostEqual(g["breakeven_wr_no_fee"], 0.02 / 0.055, places=4)
        self.assertGreater(g["breakeven_wr_fee_2x"], g["breakeven_wr_no_fee"])
        self.assertAlmostEqual(g["mean_planned_rr"], 1.75, places=4)

    def test_wr_counts_positive_excess(self):
        trades = [trade("TP", 0.01), trade("SL", -0.02), trade("TIME_30H", 0.001)]
        self.assertAlmostEqual(G.geometry(trades)["wr"], 2 / 3, places=6)


class TestBootstrapAndControl(unittest.TestCase):
    def test_cluster_bootstrap_deterministic(self):
        t = [trade("TP", 0.01, 1), trade("SL", -0.005, 1), trade("TP", 0.02, 2), trade("SL", -0.01, 3)]
        a = G.cluster_bootstrap(t, n_iter=300, seed=5)
        b = G.cluster_bootstrap(t, n_iter=300, seed=5)
        self.assertEqual(a["ci95"], b["ci95"])
        self.assertLessEqual(a["ci95"][0], a["ci95"][1])

    def test_time_counterfactual_zero_when_no_time_trades(self):
        cf = G.time_stop_counterfactual([trade("TP", 0.01), trade("SL", -0.01)])
        self.assertEqual(cf.get("note"), "no time-stop exits")

    def test_time_counterfactual_positive_leak_for_losing_time_trades(self):
        trades = [trade("TP", 0.02)] * 3 + [trade("TIME_30H", -0.004)] * 2
        cf = G.time_stop_counterfactual(trades, n_iter=200, seed=1)
        self.assertEqual(cf["n_time"], 2)
        self.assertGreater(cf["leak_bps"], 0)

    def test_time_null_deterministic_and_ordered(self):
        t = [trade("TIME_30H" if i % 4 == 0 else "TP", 0.01 * ((i % 5) - 2), block=i) for i in range(40)]
        a = G.time_stop_null(t, n_iter=100, seed=9)
        b = G.time_stop_null(t, n_iter=100, seed=9)
        self.assertEqual(a, b)
        self.assertGreaterEqual(a["p95_bps"], a["p50_bps"])
        self.assertGreaterEqual(a["p99_bps"], a["p95_bps"])

    def test_time_null_degenerate_when_all_or_none(self):
        self.assertEqual(G.time_stop_null([trade("TP", 0.01)])["note"], "degenerate label")
        self.assertEqual(G.time_stop_null([trade("TIME_30H", 0.01)])["note"], "degenerate label")


class TestVerdict(unittest.TestCase):
    def test_inside_null_band(self):
        self.assertEqual(
            G._verdict({}, {"ci95": [-0.01, 0.01]}, {"leak_bps": 1.0}, {"verdict": "INSIDE_NULL_BAND"}),
            "TIME_STOP_LEAK_INSIDE_NULL_BAND",
        )

    def test_leak_beyond_null(self):
        self.assertEqual(
            G._verdict({}, {"ci95": [-0.01, 0.01]}, {"leak_bps": 9.0}, {"verdict": "LEAK_BEYOND_NULL"}),
            "TIME_STOP_LEAK_REAL_PENDING_RISET",
        )

    def test_positive_significant_edge(self):
        self.assertEqual(
            G._verdict({}, {"ci95": [0.001, 0.02]}, {"leak_bps": 0.0}, {}),
            "EDGE_POSITIVE_SIGNIFICANT",
        )


class TestRender(unittest.TestCase):
    def test_sections_and_caveat_present(self):
        a = {
            "generated_utc": "x", "track": "twoway", "n_signal": 3, "fee_bps": 8.0, "cluster_hours": 30.0,
            "duplication": {"n_rows": 3, "n_unique": 3, "ratio": 1.0},
            "exit_accounting": [{"exit_reason": "TP", "n": 1, "share": 1.0, "mean_excess_bps": 1.0,
                                 "contrib_to_mean_bps": 1.0, "mean_hold_hours": 1.0, "outcome_determined": True}],
            "binding": {"tp_contrib_bps": 1.0, "sl_contrib_bps": -0.5, "time_contrib_bps": -0.1,
                        "gross_bps": 0.4, "fee_2x_bps": 16.0, "margin_over_fee_2x_bps": -15.6,
                        "time_share_of_gross_pct": 25.0},
            "geometry": {"n": 3, "wr": 0.5, "n_planned": 3, "mean_planned_tp_dist_pct": 3.0,
                         "mean_planned_sl_dist_pct": 2.0, "mean_planned_rr": 1.5, "mean_realized_tp_pct": 3.0,
                         "mean_realized_sl_pct": 2.0, "n_tp": 1, "n_sl": 1, "mean_realized_rr": 1.5,
                         "breakeven_wr_no_fee": 0.4, "breakeven_wr_fee_1x": 0.41,
                         "breakeven_wr_fee_2x": 0.42, "fee_share_of_tp_pct": 2.0,
                         "breakeven_wr_gap_pp": -8.0},
            "cluster_bootstrap": {"mean_bps": 0.4, "ci95_bps": [-1.0, 2.0], "p_pos": 0.6, "n_blocks": 1},
            "time_stop_counterfactual": {"n_time": 1, "leak_bps": 1.0, "paired_ci95_bps": [-1.0, 3.0], "n_blocks": 1},
            "time_stop_null": {"n": 200, "p50_bps": -1.0, "p95_bps": 5.0, "p99_bps": 7.0,
                               "observed_bps": 1.0, "verdict": "INSIDE_NULL_BAND"},
            "verdict": "TIME_STOP_LEAK_INSIDE_NULL_BAND",
        }
        md = G.render_md(a)
        for token in ("Exit-reason accounting", "Binding constraint", "Designed vs realized",
                      "Time-stop leak", "Negative control", "raw realized price move"):
            self.assertIn(token, md)


if __name__ == "__main__":
    unittest.main()
