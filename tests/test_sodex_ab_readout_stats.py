"""Regresi statistik readout A/B: BH-FDR, Welch, dan aturan verdict.

Alasan ada: readout menjalankan 5 arm sekaligus. Tanpa koreksi BH, satu arm
"signifikan" dari 5 uji pada alpha 0,05 mentah punya peluang ~23% muncul karena
kebetulan semata — cukup untuk mengirim lane ke uang nyata atas dasar hoki.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sodex_ab_flip_readout as ab  # noqa: E402


class TestBhFdr:
    def test_q_monotone_and_dampened(self):
        q = ab.bh_fdr({"a": 0.001, "b": 0.02, "c": 0.4, "d": 0.9})
        assert q["a"] <= q["b"] <= q["c"] <= q["d"]
        assert q["a"] == 0.004          # 0.001 * 4 / 1
        assert q["d"] == 0.9            # terbesar tidak boleh naik di atas 1

    def test_single_test_unchanged(self):
        assert ab.bh_fdr({"only": 0.03})["only"] == 0.03

    def test_borderline_p_becomes_insignificant(self):
        # p terkecil 0,02 "signifikan" mentah; setelah BH (5 uji) q naik jadi 0,06
        # karena di-clamp langkah-di-atas oleh p=0,06 -> tidak lagi < 0,05.
        q = ab.bh_fdr({"a": 0.02, "b": 0.03, "c": 0.04, "d": 0.05, "e": 0.06})
        assert abs(q["a"] - 0.06) < 1e-9
        assert q["a"] > 0.05                       # mentah signifikan, terkoreksi tidak
        assert q["a"] <= q["b"] <= q["c"] <= q["d"] <= q["e"]


class TestWelch:
    def test_needs_min_samples(self):
        assert ab.welch_p([1.0, 2.0], [3.0, 4.0]) is None

    def test_detects_large_shift(self):
        p = ab.welch_p([-1.0] * 30, [0.0] * 30)
        assert p is not None and p < 0.05

    def test_identical_distributions_not_significant(self):
        a = [(-1) ** i * 0.5 for i in range(30)]
        p = ab.welch_p(a, a)
        assert p is not None and p > 0.5

    def test_unsupported_nonfinite_p_fails_closed(self):
        a = [1.0] * 8 + [0.0] * 8
        p = ab.welch_p(a, [2.0] * 16)
        assert p is None or 0 <= p <= 1


class TestVerdict:
    def test_monitor_below_min_n(self):
        assert ab.verdict_for(5, 0.9, (0.5, 1.3)) == "MONITOR (n<20)"

    def test_lolos_requires_both_ci_and_threshold(self):
        assert "LOLOS" in ab.verdict_for(120, 0.30, (0.05, 0.55))
        # CI95 > 0 tapi mean di bawah 0,205pp -> tidak lolos
        assert "LOLOS" not in ab.verdict_for(120, 0.10, (0.01, 0.19))

    def test_negative_edge_flagged(self):
        assert "NEGATIF" in ab.verdict_for(120, -0.30, (-0.55, -0.05))

    def test_better_than_reference_with_q(self):
        v = ab.verdict_for(50, 0.10, (-0.01, 0.21), q=0.004, mean_ref_pp=-0.20)
        assert v.startswith("LEBIH BAIK")

    def test_worse_than_reference_with_q(self):
        v = ab.verdict_for(50, -0.40, (-0.6, -0.2), q=0.02, mean_ref_pp=-0.10)
        assert v.startswith("LEBIH BURUK")
