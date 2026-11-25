"""Tests for U8 SPRT capital-scaling gate (pure Wald SPRT — no DB/network)."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.sodex_ratio_sprt import sprt_binomial


class TestSprtBinomial(unittest.TestCase):
    def test_wald_bounds_symmetric_at_equal_error(self):
        r = sprt_binomial(0, 0, alpha=0.05, beta=0.05)
        self.assertAlmostEqual(r["accept_h1_at"], math.log(0.95 / 0.05), places=4)
        self.assertAlmostEqual(r["accept_h0_at"], math.log(0.05 / 0.95), places=4)
        self.assertAlmostEqual(r["accept_h1_at"], -r["accept_h0_at"], places=6)

    def test_empty_sample_continues(self):
        r = sprt_binomial(0, 0)
        self.assertEqual(r["llr"], 0.0)
        self.assertEqual(r["decision"], "CONTINUE_COLLECT")

    def test_pilot_small_sample_continues(self):
        # 11/15 = 73% looks good but is underpowered → must NOT scale yet
        r = sprt_binomial(11, 15, p0=0.55, p1=0.69)
        self.assertEqual(r["decision"], "CONTINUE_COLLECT")
        self.assertLess(r["llr"], r["accept_h1_at"])

    def test_strong_positive_evidence_scales(self):
        r = sprt_binomial(30, 35, p0=0.55, p1=0.69)
        self.assertEqual(r["decision"], "SCALE_OK")
        self.assertGreaterEqual(r["llr"], r["accept_h1_at"])

    def test_strong_negative_evidence_stops(self):
        # 43% profitable over a real sample → below target → stop & audit
        r = sprt_binomial(15, 35, p0=0.55, p1=0.69)
        self.assertEqual(r["decision"], "STOP_AUDIT")
        self.assertLessEqual(r["llr"], r["accept_h0_at"])

    def test_all_time_like_56pct_stops(self):
        # 655/1166 ≈ 56% (all-time PVE) — below the 69% target → STOP_AUDIT
        r = sprt_binomial(655, 1166, p0=0.55, p1=0.69)
        self.assertEqual(r["decision"], "STOP_AUDIT")

    def test_degenerate_probs_no_crash(self):
        r = sprt_binomial(5, 10, p0=0.0, p1=1.0)  # clamped internally
        self.assertIn(r["decision"], ("SCALE_OK", "STOP_AUDIT", "CONTINUE_COLLECT"))
        self.assertFalse(math.isnan(r["llr"]))

    def test_wr_reported(self):
        r = sprt_binomial(7, 10)
        self.assertAlmostEqual(r["wr"], 0.7, places=4)

    def test_monotonic_more_wins_higher_llr(self):
        low = sprt_binomial(20, 40)["llr"]
        high = sprt_binomial(35, 40)["llr"]
        self.assertGreater(high, low)


if __name__ == "__main__":
    unittest.main()
