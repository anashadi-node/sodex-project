import datetime as dt
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sodex_harness_reeval as reeval


class TestSodexHarnessReevalSafety(unittest.TestCase):
    def test_side_sign_handles_long_short_aliases(self):
        self.assertEqual(reeval.side_sign({"direction": "LONG"}), 1)
        self.assertEqual(reeval.side_sign({"side": "S"}), -1)
        with self.assertRaises(ValueError):
            reeval.side_sign({"direction": "FLAT"})

    def test_sharpe_report_fail_closed_on_equity_discontinuity(self):
        start = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        rows = [(start + dt.timedelta(days=i), 100.0 + i) for i in range(35)]
        rows.append((start + dt.timedelta(days=36), 200.0))  # >20% jump: deposit/denominator discontinuity
        result = reeval.daily_sharpe_from_rows(rows)
        self.assertFalse(result["valid"])
        self.assertGreaterEqual(result["large_jump_count"], 1)

    def test_wallet_distance_separates_wallet_delta_from_trading_only(self):
        current = 244.0
        result = reeval.wallet_distance_metrics(
            current_wallet=current,
            start_equity=250.0,
            local_engine_net=-0.2,
        )
        self.assertAlmostEqual(result["target_48h_usd"], 1.952)
        self.assertAlmostEqual(result["jarak_ke_target_wallet_delta"], -6.0 / 1.952)
        self.assertAlmostEqual(result["jarak_ke_target_local_engine_trading"], -0.2 / 1.952)

    def test_missing_short_funding_forces_fail_closed_reason(self):
        rows = [{"direction": "SHORT", "pnl_pct": 0.01}, {"direction": "SHORT", "pnl_pct": -0.01}]
        missing = reeval.count_missing_funding(rows)
        self.assertEqual(missing, 2)
        self.assertIn("funding_required_but_missing", reeval.funding_missing_reason(rows))

    def test_btc_fetch_falls_back_to_local_cache_on_network_outage(self):
        start = dt.datetime.fromtimestamp(1000, tz=dt.timezone.utc)
        end = dt.datetime.fromtimestamp(8200, tz=dt.timezone.utc)
        cache = {
            "rows": [
                [1000_000, "", "", "", "100.0"],
                [4600_000, "", "", "", "101.0"],
                [8200_000, "", "", "", "102.0"],
            ]
        }
        old_report_dir = reeval.REPORT_DIR
        with tempfile.TemporaryDirectory() as td:
            reeval.REPORT_DIR = Path(td)
            (Path(td) / "btc_1h_binance_spot_cache_test.json").write_text(json.dumps(cache))
            old_urlopen = reeval.urllib.request.urlopen
            reeval.urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(OSError("dns down"))
            try:
                candles = reeval.fetch_btc_1h(start, end)
            finally:
                reeval.urllib.request.urlopen = old_urlopen
                reeval.REPORT_DIR = old_report_dir
        self.assertEqual(candles, [(1000_000, 100.0), (4600_000, 101.0), (8200_000, 102.0)])

    def test_normalized_window_is_canonical_gate_series(self):
        rows = [
            {"ts": "2026-01-01T00:00:00+00:00", "normalized_equity": 100.0, "local_net_usd": 0.0, "reconcile_net_usd": 0.0},
            {"ts": "2026-01-02T00:00:00+00:00", "normalized_equity": 101.0, "local_net_usd": 1.0, "reconcile_net_usd": 0.0},
            {"ts": "2026-01-03T00:00:00+00:00", "normalized_equity": 103.0, "local_net_usd": 2.0, "reconcile_net_usd": 0.0},
        ]
        result = reeval.normalized_window_distance_metrics({"valid": True, "rows": rows}, current_wallet=250.0, hours=48)
        self.assertTrue(result["valid"])
        self.assertEqual(result["series_role"], "CANONICAL_D0_2_TRADING_ONLY_GATE_SERIES")
        self.assertEqual(result["raw_wallet_role"], "DIAGNOSTIC_RCA_ONLY_NOT_GATE_SERIES")
        self.assertAlmostEqual(result["target_48h_usd"], 2.0)
        self.assertAlmostEqual(result["normalized_delta_usd"], 3.0)
        self.assertAlmostEqual(result["distance_to_target_ratio"], 1.5)

    def test_normalized_window_fails_closed_without_valid_flag(self):
        """A missing `valid` flag must fail closed -- the builder no longer emits one."""
        rows = [
            {"ts": "2026-01-01T00:00:00+00:00", "normalized_equity": 100.0},
            {"ts": "2026-01-03T00:00:00+00:00", "normalized_equity": 103.0},
        ]
        result = reeval.normalized_window_distance_metrics({"rows": rows}, current_wallet=250.0, hours=48)
        self.assertFalse(result["valid"])
        self.assertIn("FAIL_CLOSED", result["reason"])


    def test_arm_of_splits_on_apriori_random_label(self):
        self.assertEqual(reeval.arm_of({"track": "RANDOM"}), reeval.ARM_CONTROL)
        self.assertEqual(reeval.arm_of({"track": "random"}), reeval.ARM_CONTROL)
        self.assertEqual(reeval.arm_of({"track": "SIGNAL"}), reeval.ARM_SIGNAL)
        self.assertEqual(reeval.arm_of({}), reeval.ARM_SIGNAL)
        self.assertEqual(reeval.arm_of({"track": None}), reeval.ARM_SIGNAL)

    def test_arm_of_fails_closed_on_unlabelled_control(self):
        with self.assertRaises(ValueError):
            reeval.arm_of({"regime": "RANDOM_CONTROL"})
        with self.assertRaises(ValueError):
            reeval.arm_of({"track": "", "regime": "random_control"})

    def test_assert_no_control_smuggling_counts_only_unlabelled(self):
        rows = [{"track": "RANDOM", "regime": "RANDOM_CONTROL"}, {"regime": "RANDOM_CONTROL"}, {"track": "SIGNAL"}]
        self.assertEqual(reeval.assert_no_control_smuggling(rows), 1)

    def test_cluster_ci95_widens_with_block_structure(self):
        # 40 trades inside ONE 30 h block -> cannot be resampled -> None (fail-visible)
        one = [(1000 + i, 0.01) for i in range(40)]
        self.assertIsNone(reeval.cluster_ci95(one))
        # spread over several blocks -> interval returned and deterministic
        many = [(1000 + i * 40 * 3600, 0.01 * ((i % 3) - 1)) for i in range(30)]
        a = reeval.cluster_ci95(many, n_iter=300, seed=7)
        b = reeval.cluster_ci95(many, n_iter=300, seed=7)
        self.assertEqual(a, b)
        self.assertLessEqual(a[0], a[1])

    def test_evaluate_track_excludes_control_arm_from_graded_n(self):
        base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        candles = [(int((base + dt.timedelta(hours=h)).timestamp() * 1000), 100.0 + h) for h in range(0, 60)]

        def row(i, track=None):
            r = {
                "pair": "ETH", "direction": "LONG", "pnl_pct": 0.01 * (1 if i % 2 else -1),
                "entry_time": (base + dt.timedelta(hours=i)).isoformat(),
                "exit_time": (base + dt.timedelta(hours=i + 2)).isoformat(),
            }
            if track:
                r["track"] = track
            return r

        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            state.write_text(json.dumps({"closed_trades": [row(i) for i in range(35)] + [row(100 + i, "RANDOM") for i in range(5)]}))
            registry = reeval.TrialRegistry(str(Path(td) / "registry.jsonl"))
            item = reeval.evaluate_track("probe", state, candles, registry)

        self.assertEqual(item["n_raw"], 40)
        self.assertEqual(item["n"], 35)
        self.assertEqual(item["arms"]["signal"]["n"], 35)
        self.assertEqual(item["arms"]["control"]["n"], 5)
        self.assertEqual(item["arms"]["legacy_all"]["n"], 40)
        self.assertEqual(registry.count(), 1)  # only the signal arm is a trial
        self.assertIsNotNone(item["arms"]["signal"]["excess_mean"])
        self.assertIsNotNone(item["arms"]["arm_split_bias_bps"])



if __name__ == "__main__":
    unittest.main()
