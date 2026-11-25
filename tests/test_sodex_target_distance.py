#!/usr/bin/env python3
"""Tests for the fail-closed jarak_ke_target measurement."""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sodex_target_distance as td  # noqa: E402

UTC = dt.timezone.utc


def snap(iso: str, equity: float, rt: int = 0, net: float = 0.0) -> dict:
    return {"ts": td.parse_dt(iso), "equity": equity, "stats": {"rt_6h": rt, "net_6h": net}}


class TestTargetDistance(unittest.TestCase):
    def test_zero_snapshot_on_boundary_is_not_used_as_anchor(self):
        """The 12500% artifact: boundary lands on a $0.00 heartbeat row."""
        rows = [
            snap("2026-10-01T00:00:00Z", 244.45),
            snap("2026-10-01T12:00:00Z", 0.00),          # exactly at the 48h boundary
            snap("2026-10-03T12:00:00Z", 244.34),
        ]
        out = td.target_distance(rows, hours=48)
        self.assertTrue(out["valid"])
        self.assertGreater(out["anchor_equity_usd"], 0)
        self.assertEqual(out["anchor_ts"], "2026-10-01T00:00:00+00:00")
        # naive pick is the zero row -> delta equals the whole wallet
        self.assertEqual(out["anchor_naive_equity_usd"], 0.0)
        self.assertAlmostEqual(out["jarak_ke_target_naive"], 244.34 / (0.008 * 244.34), places=6)
        self.assertAlmostEqual(out["jarak_ke_target"], -0.11 / (0.008 * 244.34), places=6)

    def test_formula_matches_spec(self):
        """jarak_ke_target = net_pnl_48h / (0.008 * wallet_now)."""
        rows = [snap("2026-10-01T00:00:00Z", 1000.0), snap("2026-10-03T00:00:00Z", 1008.0)]
        out = td.target_distance(rows, hours=48)
        self.assertAlmostEqual(out["target_usd"], 8.064, places=6)
        self.assertAlmostEqual(out["net_pnl_usd"], 8.0, places=6)
        self.assertAlmostEqual(out["jarak_ke_target"], 8.0 / 8.064, places=9)

    def test_fails_closed_when_all_snapshots_are_zero(self):
        rows = [snap("2026-10-01T00:00:00Z", 0.0), snap("2026-10-03T00:00:00Z", 0.0)]
        out = td.target_distance(rows, hours=48)
        self.assertFalse(out["valid"])
        self.assertIn("FAIL_CLOSED", out["reason"])

    def test_fails_closed_when_latest_snapshot_is_zero(self):
        rows = [snap("2026-10-01T00:00:00Z", 244.0), snap("2026-10-03T00:00:00Z", 0.0)]
        out = td.target_distance(rows, hours=48)
        self.assertFalse(out["valid"])
        self.assertIn("not positive", out["reason"])

    def test_fails_closed_when_no_valid_snapshot_reaches_the_boundary(self):
        """All snapshots before the boundary are $0.00 -> only the latest is valid."""
        rows = [
            snap("2026-10-01T00:00:00Z", 0.0),
            snap("2026-10-03T00:00:00Z", 244.0),
        ]
        out = td.target_distance(rows, hours=48)
        self.assertFalse(out["valid"])
        self.assertIn("fewer than 2 valid snapshots inside the window", out["reason"])

    def test_round_trips_and_net_are_summed_over_the_window(self):
        rows = [
            snap("2026-10-01T00:00:00Z", 100.0, rt=3, net=1.0),
            snap("2026-10-01T06:00:00Z", 101.0, rt=4, net=1.0),
            snap("2026-10-03T00:00:00Z", 102.0, rt=5, net=1.0),
        ]
        out = td.target_distance(rows, hours=48)
        self.assertEqual(out["engine_round_trips_in_window"], 12)
        self.assertAlmostEqual(out["engine_net_6h_sum_usd"], 3.0, places=9)

    def test_anchor_before_boundary_never_truncates_window(self):
        rows = [
            snap("2026-09-20T00:00:00Z", 250.0),
            snap("2026-10-03T00:00:00Z", 260.0),
        ]
        out = td.target_distance(rows, hours=48)
        self.assertGreater(out["window_hours_actual"], 48.0)
        self.assertEqual(out["anchor_ts"], "2026-09-20T00:00:00+00:00")

    def test_deterministic(self):
        rows = [snap("2026-10-01T00:00:00Z", 244.0), snap("2026-10-03T00:00:00Z", 244.5)]
        self.assertEqual(td.target_distance(rows, hours=48), td.target_distance(rows, hours=48))


class TestNumeratorDistinction(unittest.TestCase):
    """D0.6b: wallet-delta and engine-trading are different questions, not a disagreement."""

    def _rows(self):
        base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        return [
            {"ts": base, "equity": 240.0, "stats": {"net_6h": 0.0, "rt_6h": 0}},
            {"ts": base + dt.timedelta(hours=48), "equity": 232.0, "stats": {"net_6h": -1.0, "rt_6h": 3}},
        ]

    def test_both_numerators_are_reported_with_labels(self):
        import sodex_target_distance as tdm
        out = tdm.target_distance(self._rows(), hours=48)
        self.assertTrue(out["valid"])
        self.assertEqual(out["numerator_used"], "WALLET_EQUITY_DELTA")
        self.assertEqual(out["boundary_basis"], "latest_snapshot_ts")
        self.assertIn("jarak_ke_target_wallet_delta", out)
        self.assertIn("jarak_ke_target_engine_trading", out)

    def test_wallet_and_engine_numerators_can_differ(self):
        import sodex_target_distance as tdm
        out = tdm.target_distance(self._rows(), hours=48)
        # wallet delta = -8.00, engine net = -1.00 -> must not be the same number
        self.assertAlmostEqual(out["net_pnl_usd"], -8.0)
        self.assertAlmostEqual(out["engine_net_usd"], -1.0)
        self.assertNotAlmostEqual(out["jarak_ke_target_wallet_delta"],
                                  out["jarak_ke_target_engine_trading"])

    def test_legacy_key_still_present_for_backcompat(self):
        import sodex_target_distance as tdm
        out = tdm.target_distance(self._rows(), hours=48)
        self.assertEqual(out["jarak_ke_target"], out["jarak_ke_target_wallet_delta"])


if __name__ == "__main__":
    unittest.main()
