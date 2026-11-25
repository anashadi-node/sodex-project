#!/usr/bin/env python3
"""Kalibrasi harness SPEC4 — memastikan harness TIDAK bisa mengarang edge.

Pra-registrasi: docs/sodex/SODEX_SPEC4_PRAREG_2026-10-07.md (§5, §8)

Yang diuji (semua cepat, deterministik):
  1. Bootstrap pada deret null  -> p TIDAK kecil
  2. Bootstrap pada deret positif kuat -> p kecil
  3. run_cell TIDAK memakai harga bar sinyal (tanpa look-ahead)
  4. run_cell mengurangi biaya round-trip sebesar yang diminta
  5. stride = H (observasi non-overlapping)
  6. Sinyal sadar-arah: fade meniadakan edge (net_fade ~= -net)
  7. Sinyal tanpa edge + biaya -> net <= 0 (tidak bisa "lulus" karena kebetulan)
  8. block_flip mengubah tanda per blok, bukan seluruh deret
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from sodex_spec4_micro import (  # noqa: E402
    block_flip, run_cell, stationary_bootstrap_p, day_spans,
)

SEED = 7


class TestSpec4Harness(unittest.TestCase):

    def test_bootstrap_null_tidak_kecil(self):
        """Deret tanpa edge -> p tidak boleh < 0.05 (kalau iya: false positive)."""
        rng = np.random.default_rng(SEED)
        net = rng.normal(0.0, 0.01, 2000)
        r = stationary_bootstrap_p(net, block=10, n_boot=400, rng=rng)
        self.assertGreater(r["p"], 0.05, f"null menghasilkan p={r['p']} (false positive)")
        self.assertEqual(r["n"], 2000)
        self.assertLess(r["ci_lo"], r["obs"])
        self.assertGreater(r["ci_hi"], r["obs"])

    def test_bootstrap_sinyal_kuat_kecil(self):
        """Deret dengan rata-rata besar vs derau -> p harus kecil."""
        rng = np.random.default_rng(SEED)
        net = 0.01 + rng.normal(0.0, 0.001, 2000)
        r = stationary_bootstrap_p(net, block=10, n_boot=400, rng=rng)
        self.assertLess(r["p"], 0.05, f"sinyal kuat tidak terdeteksi (p={r['p']})")
        self.assertGreater(r["ci_lo"], 0.0, "CI95 tidak memuat tanda yang benar")

    def test_run_cell_tanpa_lookahead(self):
        """Mengubah harga pada bar SINYAL tidak boleh mengubah hasil posisi."""
        close = np.array([1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        sig = np.ones(10)
        net_a, idx_a, _ = run_cell(close, sig, H=2, entry_delay=1, cost_rt=0.0)
        close_b = close.copy()
        close_b[0] = 999.0          # hanya bar sinyal pertama diubah
        net_b, _, _ = run_cell(close_b, sig, H=2, entry_delay=1, cost_rt=0.0)
        np.testing.assert_allclose(net_a, net_b)
        # masuk di close[t+1] -> observasi pertama memakai close[1] dan close[3]
        self.assertAlmostEqual(net_a[0], np.log(close[3] / close[1]), places=12)

    def test_run_cell_mengurangi_biaya(self):
        close = np.linspace(1.0, 2.0, 200)
        sig = np.ones(len(close))
        c = 2 * 0.0004
        n0, _, _ = run_cell(close, sig, H=5, cost_rt=0.0)
        n1, _, _ = run_cell(close, sig, H=5, cost_rt=c)
        self.assertAlmostEqual(float(np.nanmean(n0) - np.nanmean(n1)), c, places=12)

    def test_stride_non_overlapping(self):
        close = np.linspace(1.0, 2.0, 500)
        sig = np.ones(len(close))
        _, idx, mins = run_cell(close, sig, H=7, entry_delay=1, base_min=1000)
        d = np.diff(idx)
        self.assertTrue(np.all(d == 7), f"stride bukan H: {set(d.tolist())}")
        np.testing.assert_array_equal(mins, 1000 + idx)

    def test_fade_meniadakan_edge(self):
        """Kalau sinyal punya edge, fade harus kalah (sign-aware, bukan sekadar -net)."""
        rng = np.random.default_rng(SEED)
        n = 5000
        r = rng.normal(0.0, 0.002, n)
        sig = np.sign(rng.normal(0.0, 1.0, n))
        close = 100 * np.exp(np.cumsum(r * sig * 0.35))   # harga bergerak searah sinyal
        gross, _, _ = run_cell(close, sig, H=5, cost_rt=0.0)
        fade, _, _ = run_cell(close, -sig, H=5, cost_rt=0.0)
        g, f = float(np.nanmean(gross)), float(np.nanmean(fade))
        self.assertGreater(g, 0.0, "edge sintetis tidak terdeteksi")
        self.assertLess(f, 0.0, "fade tidak negatif -> kontrol tidak sadar arah")
        self.assertAlmostEqual(g + f, 0.0, places=12)

    def test_tanpa_edge_biaya_membuat_negatif(self):
        """Harga random walk + sinyal acak: net harus ~= -biaya (tidak bisa lulus)."""
        rng = np.random.default_rng(SEED + 3)
        n = 20000
        close = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.001, n)))
        sig = np.sign(rng.normal(0.0, 1.0, n))
        cost = 2 * 0.0004
        net, _, _ = run_cell(close, sig, H=5, cost_rt=cost)
        m = float(np.nanmean(net))
        self.assertLess(m, 0.0, "random walk menghasilkan net positif -> harness bocor")

    def test_block_flip_mengubah_tanda_per_blok(self):
        """blok 60: sebagian dibalik, bukan seluruh deret, dan panjang tetap."""
        sig = np.ones(600)
        spans = [(0, 600)]
        rng = np.random.default_rng(SEED)
        out = block_flip(sig, spans, block=60, rng=rng)
        self.assertEqual(len(out), len(sig))
        flipped = int((out < 0).sum())
        self.assertTrue(0 < flipped < 600, f"tidak ada blok yang dibalik (flipped={flipped})")
        self.assertTrue(set(np.unique(out).tolist()) <= {1.0, -1.0})

    def test_day_spans_memotong_per_hari(self):
        minutes = np.array([100, 101, 1439, 1440, 1441], dtype=np.int64)
        spans = day_spans(minutes)
        self.assertEqual(spans, [(0, 3), (3, 5)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
