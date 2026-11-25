#!/usr/bin/env python3
"""Unit test: mesin R3 (reliabilitas REAL-wide) — R3, 2026-10-05.

Uji ini mengunci bagian-bagian yang MENENTUKAN putusan, supaya hasil R3 tidak
bisa "diperbaiki" tanpa jejak:
  * himpunan sinyal dibersihkan dari kontrol RANDOM (kalau tidak, uji alpha
    membandingkan sinyal dengan dirinya sendiri);
  * koreksi BH-FDR benar (0 lolos pada data ini);
  * null max-of-k reproducible & tidak bias ke atas;
  * uji seleksi memakai himpunan yang SAH (n>=20) -- membandingkan fluke n=3
    dengan simbol ber-n besar adalah kesalahan kategori, bukan bukti.
"""
import json
import importlib
import random
import statistics as st
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import sodex_r3_reliability as R3  # noqa: E402


class SignalSetTests(unittest.TestCase):
    def _write(self, rows):
        p = Path(tempfile.mkdtemp()) / "state.json"
        p.write_text(json.dumps({"closed": rows}))
        return p

    def test_control_rows_are_excluded(self):
        p = self._write([
            {"sym": "SOL", "pnl_pct": 0.01, "track": "SIGNAL"},
            {"sym": "SOL", "pnl_pct": -0.02, "track": "RANDOM"},
            {"sym": "ETH", "pnl_pct": 0.03},                    # tanpa label
            {"sym": "ETH", "pnl_pct": 0.04, "track": "random"},  # huruf kecil
        ])
        got = R3.load_signal_rows(p)
        self.assertEqual(len(got), 2, "baris RANDOM harus dibuang")
        self.assertEqual({t["sym"] for t in got}, {"SOL", "ETH"})

    def test_unlabelled_rows_count_as_signal(self):
        """Baris lama tanpa `track` = sinyal (jangan dibuang diam-diam)."""
        p = self._write([{"sym": "BTC", "pnl_pct": 0.02}])
        self.assertEqual(len(R3.load_signal_rows(p)), 1)


class BhFdrTests(unittest.TestCase):
    def test_no_pass_when_all_p_are_marginal(self):
        """22 nilai p ~0,1-0,9 (seperti data ini) -> tidak ada yang lolos."""
        pv = {f"S{i}": 0.02 + i * 0.04 for i in range(22)}
        self.assertEqual(sum(R3.bh_fdr(pv, q=0.10).values()), 0)

    def test_pass_when_one_p_is_tiny(self):
        pv = {f"S{i}": 0.5 for i in range(21)}
        pv["STAR"] = 1e-6
        out = R3.bh_fdr(pv, q=0.10)
        self.assertTrue(out["STAR"])
        self.assertEqual(sum(out.values()), 1)

    def test_nan_handled(self):
        out = R3.bh_fdr({"A": float("nan"), "B": 1e-8}, q=0.10)
        self.assertFalse(out["A"])
        self.assertTrue(out["B"])


class MaxOfKNullTests(unittest.TestCase):
    def test_null_is_reproducible(self):
        by = {"A": [0.01, -0.01, 0.02, -0.02] * 5,
              "B": [0.005, -0.005] * 10}
        a = R3.max_of_k_null(by, n_sim=300, seed=7)
        b = R3.max_of_k_null(by, n_sim=300, seed=7)
        self.assertEqual(a["maxes"], b["maxes"])

    def test_centered_null_has_expected_max_near_zero(self):
        """Pool terpusat -> E[max] harus dekat 0 (kebetulan, bukan edge)."""
        by = {"A": [0.01, -0.01, 0.02, -0.02] * 10,
              "B": [0.03, -0.03, 0.01, -0.01] * 10}
        null = R3.max_of_k_null(by, n_sim=1000, seed=11)
        self.assertLess(abs(null["mean"]), 0.02)
        self.assertGreaterEqual(null["p95"], null["p50"])

    def test_more_symbols_raises_the_null_bar(self):
        """makin banyak simbol diuji, makin tinggi mean-terbaik yang muncul
        dari kebetulan -- inilah alasan uji seleksi wajib."""
        base = {"A": [0.01, -0.01, 0.02, -0.02] * 10}
        few = R3.max_of_k_null(base, n_sim=800, seed=3)
        many = R3.max_of_k_null({**base, **{f"X{i}": [0.01, -0.01] * 10 for i in range(20)}},
                                n_sim=800, seed=3)
        self.assertGreater(many["mean"], few["mean"])


class EmpiricalPTests(unittest.TestCase):
    def test_p_is_bounded_and_monotone(self):
        null = sorted([0.001 * i for i in range(1, 101)])
        lo = R3.empirical_p(0.0, null)
        hi = R3.empirical_p(1.0, null)
        self.assertGreater(lo, hi)
        self.assertGreater(lo, 0.0)
        self.assertLessEqual(hi, 1.0)

    def test_observation_at_median_gives_about_half(self):
        rng = random.Random(1)
        null = sorted(rng.gauss(0, 1) for _ in range(2001))
        p = R3.empirical_p(0.0, null)
        self.assertAlmostEqual(p, 0.5, delta=0.06)


class GiniAndSegmentTests(unittest.TestCase):
    def test_gini_zero_for_uniform(self):
        self.assertAlmostEqual(R3.gini([1.0, 1.0, 1.0, 1.0]), 0.0, places=6)

    def test_gini_rises_with_concentration(self):
        self.assertGreater(R3.gini([0.0, 0.0, 0.0, 10.0]), R3.gini([2.5] * 4))

    def test_segments_are_chronological(self):
        pts = [(float(i), float(i)) for i in range(12)]
        segs = R3.segments(pts, k=3)
        self.assertEqual([len(s) for s in segs], [4, 4, 4])

    def test_segments_return_empty_when_underpowered(self):
        segs = R3.segments([(0.1, 1.0), (0.2, 2.0)], k=3)
        self.assertTrue(all(len(s) == 0 for s in segs),
                        "kurang data -> '-' bukan segmen palsu")


class CandidateGateTests(unittest.TestCase):
    """Kandidat WAJIB dari himpunan dapat-dinilai: aturan yang menyelamatkan R3."""

    def test_best_overall_is_not_a_valid_candidate_when_n_small(self):
        rows = [
            {"sym": "PUMP", "pnl_pct": 0.0473, "track": "SIGNAL"},   # n=1 fluke
            {"sym": "SOL", "pnl_pct": 0.0105, "track": "SIGNAL"},
        ]
        by = R3.per_symbol(rows)
        tabs = [(s, len(v), st.mean(v) * 100) for s, v in by.items()]
        tabs.sort(key=lambda r: -r[2])
        self.assertEqual(tabs[0][0], "PUMP")                    # fluke memimpin
        assess = [r for r in tabs if r[1] >= 20]
        self.assertEqual(assess, [])                            # ...tetapi TIDAK sah


if __name__ == "__main__":
    unittest.main()