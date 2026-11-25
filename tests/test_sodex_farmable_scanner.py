"""Tests for U7 farmable-pair scanner (pure ranking logic — no network)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.sodex_farmable_scanner import (
    evaluate_pair, rank_farmable, recommend_pairs)


def _row(sym, bid, ask, bid_sz, ask_sz, qvol, funding=0.0):
    return {"symbol": sym, "bidPx": str(bid), "askPx": str(ask),
            "bidSz": str(bid_sz), "askSz": str(ask_sz),
            "quoteVolume": str(qvol), "fundingRate": str(funding)}


class TestEvaluatePair(unittest.TestCase):
    def test_wide_spread_liquid_is_farmable(self):
        # CRCL-like: ~27 bps spread, deep book, big volume
        e = evaluate_pair(_row("CRCL-USD", 100.00, 100.27, 50, 50, 120000))
        self.assertTrue(e["farmable"])
        self.assertGreater(e["net_capture_bps"], 20)
        self.assertGreater(e["score"], 0)

    def test_tight_spread_not_farmable(self):
        # SOL-like: ~1.3 bps < 2.4 fee → net negative
        e = evaluate_pair(_row("SOL-USD", 74.83, 74.84, 100, 100, 500000))
        self.assertFalse(e["farmable"])
        self.assertLess(e["net_capture_bps"], 0)

    def test_wide_spread_illiquid_is_trap(self):
        # MINIMAX-like: 200 bps spread but only $3k volume → rejected by volume floor
        e = evaluate_pair(_row("MINIMAX-USD", 100.0, 102.0, 5, 5, 3000))
        self.assertFalse(e["farmable"])
        self.assertEqual(e["score"], 0.0)

    def test_wide_spread_thin_l1_depth_rejected(self):
        # wide spread + big 24h volume but micro L1 book → adverse trap
        e = evaluate_pair(_row("THIN-USD", 100.0, 100.5, 0.1, 0.1, 50000),
                          min_l1_depth=500)
        # L1 depth = 100 × 0.1 = $10 < $500 floor
        self.assertFalse(e["farmable"])

    def test_obi_computation(self):
        e = evaluate_pair(_row("X-USD", 100.0, 100.5, 75, 25, 50000))
        # (75-25)/(75+25) = 0.5
        self.assertAlmostEqual(e["obi"], 0.5, places=3)

    def test_bad_fields_no_crash(self):
        e = evaluate_pair({"symbol": "BAD-USD"})  # no prices
        self.assertFalse(e["farmable"])
        self.assertEqual(e["spread_bps"], 0.0)


class TestRankAndRecommend(unittest.TestCase):
    def _universe(self):
        return [
            _row("CRCL-USD", 100.00, 100.27, 60, 60, 120000),   # net ~24.7, big vol
            _row("MRVL-USD", 100.00, 100.29, 40, 40, 23000),    # net ~26.6, mid vol
            _row("SOL-USD", 74.83, 74.84, 100, 100, 500000),    # tight → not farmable
            _row("MINIMAX-USD", 100.0, 102.0, 5, 5, 3000),      # trap → not farmable
        ]

    def test_rank_excludes_non_farmable(self):
        ranked = rank_farmable(self._universe())
        syms = [e["symbol"] for e in ranked]
        self.assertIn("CRCL-USD", syms)
        self.assertIn("MRVL-USD", syms)
        self.assertNotIn("SOL-USD", syms)
        self.assertNotIn("MINIMAX-USD", syms)

    def test_rank_sorted_by_score_desc(self):
        ranked = rank_farmable(self._universe())
        scores = [e["score"] for e in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_recommend_top_k(self):
        ranked = rank_farmable(self._universe())
        rec = recommend_pairs(ranked, 2)
        self.assertEqual(len(rec.split(",")), 2)
        self.assertTrue(all("-USD" in s for s in rec.split(",")))

    def test_empty_universe(self):
        self.assertEqual(rank_farmable([]), [])
        self.assertEqual(recommend_pairs([], 3), "")


if __name__ == "__main__":
    unittest.main()
