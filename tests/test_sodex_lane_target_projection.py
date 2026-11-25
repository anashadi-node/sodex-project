#!/usr/bin/env python3
"""Tests for the paper-lane -> wallet target projection bridge."""
from __future__ import annotations

import datetime as dt
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sodex_lane_target_projection as proj  # noqa: E402


def trade(iso: str, pnl_usd: float, wallet_roi: float) -> dict:
    return {"exit_time": iso, "pnl_usd": pnl_usd, "wallet_roi": wallet_roi, "pair": "BTC"}


class TestDisjointBuckets(unittest.TestCase):
    def test_buckets_do_not_overlap(self):
        """A rolling window stepped per trade gave 374 windows from 376 trades; disjoint must not."""
        trades = []
        base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        for i in range(20):
            ts = base + dt.timedelta(hours=i * 7)
            trades.append({**trade(ts.isoformat(), 1.0, 0.01), "_ts": ts})
        buckets = proj.disjoint_buckets(trades, 48)
        self.assertLess(len(buckets), len(trades))
        seen = [t["_ts"] for b in buckets for t in b]
        self.assertEqual(len(seen), len(trades))
        self.assertEqual(len(set(seen)), len(trades))

    def test_every_trade_lands_in_exactly_one_bucket(self):
        base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        trades = [{**trade((base + dt.timedelta(hours=h)).isoformat(), 1.0, 0.01), "_ts": base + dt.timedelta(hours=h)}
                  for h in range(0, 200, 5)]
        buckets = proj.disjoint_buckets(trades, 48)
        self.assertEqual(sum(len(b) for b in buckets), len(trades))

    def test_empty_input(self):
        self.assertEqual(proj.disjoint_buckets([], 48), [])


class TestProjection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_lane(self, lane: str, trades: list[dict]):
        clean = [{k: v for k, v in t.items() if k != "_ts"} for t in trades]
        (self.root / f"data/paper_test_{lane}_state.json").write_text(
            json.dumps({"closed_trades": clean}))

    def test_fails_closed_when_lane_has_no_closed_trades(self):
        self.write_lane("swing", [])
        out = proj.project_lane("swing", 243.39, root=self.root)
        self.assertFalse(out["valid"])
        self.assertIn("FAIL_CLOSED", out["reason"])

    def test_fails_closed_when_fewer_than_two_buckets(self):
        base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        self.write_lane("swing", [trade(base.isoformat(), 1.0, 0.01)])
        out = proj.project_lane("swing", 243.39, root=self.root)
        self.assertFalse(out["valid"])
        self.assertIn(">=2", out["reason"])

    def test_target_denominator_is_real_wallet(self):
        base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        trades = [{**trade((base + dt.timedelta(hours=h)).isoformat(), 1.0, 0.01), "_ts": base + dt.timedelta(hours=h)}
                  for h in range(0, 200, 24)]
        self.write_lane("twoway", trades)
        out = proj.project_lane("twoway", 250.0, root=self.root)
        self.assertAlmostEqual(out["target_48h_usd"], 2.0)

    def test_hit_rate_and_distance_are_consistent(self):
        base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        # four buckets, each trade 1% on backing capital -> bucket roi 0.01 >= 0.008
        trades = [{**trade((base + dt.timedelta(hours=h)).isoformat(), 1.0, 0.01), "_ts": base + dt.timedelta(hours=h)}
                  for h in range(0, 200, 12)]
        self.write_lane("twoway", trades)
        out = proj.project_lane("twoway", 250.0, root=self.root)
        self.assertTrue(out["valid"])
        self.assertGreaterEqual(out["hit_rate_vs_target"], 0.0)
        self.assertLessEqual(out["hit_rate_vs_target"], 1.0)
        self.assertAlmostEqual(out["distance_to_target_median"],
                               out["roi_on_backing_capital"]["median"] / 0.008)

    def test_ci95_reports_zero_containment(self):
        base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        trades = []
        for i in range(40):
            roi = 0.05 if i % 2 == 0 else -0.04
            ts = base + dt.timedelta(hours=i * 3)
            trades.append({**trade(ts.isoformat(), roi * 200.0, roi), "_ts": ts})
        self.write_lane("swing", trades)
        out = proj.project_lane("swing", 243.39, root=self.root)
        self.assertIn("ci95_contains_zero", out["roi_on_backing_capital"])

    def test_deterministic(self):
        base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        trades = [{**trade((base + dt.timedelta(hours=h)).isoformat(), 0.5, 0.003), "_ts": base + dt.timedelta(hours=h)}
                  for h in range(0, 300, 9)]
        self.write_lane("twoway", trades)
        a = proj.project_lane("twoway", 243.39, root=self.root)
        b = proj.project_lane("twoway", 243.39, root=self.root)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
