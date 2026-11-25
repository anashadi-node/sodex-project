#!/usr/bin/env python3
"""Test falsifikasi sodex_model_server — mengunci aritmetika & disiplin.

Fokus: bagian MURNI (statistik) yang menentukan kebenaran kesimpulan. Bagian
yang butuh lightgbm/talib diuji di container, bukan di sini.

Yang dijaga test ini:
  • Wilson CI tidak pernah keluar dari [0,1] dan benar pada kasus tepi.
  • Koreksi jendela tumpang-tindih benar (n_eff = n/48).
  • BH-FDR benar arah (tidak meloloskan lebih banyak daripada tanpa koreksi).
  • P&L bersih: FLAT = 0; LONG/SHORT dikurangi fee RT.
  • TIDAK ADA LOOK-AHEAD: semua indeks training/OOS < n - LABEL_H.
  • Konstanta TIDAK MELENCENG dari sodex_model_server.py (anti-drift).
"""
import math
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import sodex_model_falsification as F  # noqa: E402

HERE = os.path.dirname(__file__)
SERVER = os.path.join(HERE, "..", "anantara", "sodex_model_server.py")


class TestStatistikMurni(unittest.TestCase):
    """Aritmetika yang menentukan benar/salahnya kesimpulan."""

    def test_wilson_ci_dalam_rentang(self):
        for k, n in ((0, 10), (10, 10), (5, 10), (1, 1000), (999, 1000)):
            lo, hi = F.wilson_ci(k, n)
            self.assertGreaterEqual(lo, 0.0)
            self.assertLessEqual(hi, 1.0)
            self.assertLessEqual(lo, hi)

    def test_wilson_ci_tepi_nol(self):
        """n=0 -> selang penuh (jangan mengklaim apa pun dari data kosong)."""
        self.assertEqual(F.wilson_ci(0, 0), (0.0, 1.0))

    def test_wilson_ci_simetris_di_separuh(self):
        """k=n/2 -> selang memuat 0,5 pada kedua sisi."""
        lo, hi = F.wilson_ci(50, 100)
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)

    def test_effective_n_jendela_tumpang_tindih(self):
        """480 bar x horizon 48 -> 10 observasi independen, bukan 480."""
        self.assertAlmostEqual(F.effective_n(480, 48, 1), 10.0, places=6)

    def test_effective_n_minimal_satu(self):
        """Data lebih pendek dari horizon tetap dihitung 1, bukan 0."""
        self.assertEqual(F.effective_n(5, 48, 1), 1.0)

    def test_effective_n_tanpa_horizon(self):
        self.assertEqual(F.effective_n(100, 0, 1), 100.0)

    def test_binom_p_separuh_tidak_signifikan(self):
        """Tepat 50% tidak boleh signifikan."""
        self.assertGreater(F.binom_p_two_sided(50, 100, 0.5), 0.9)

    def test_binom_p_ekstrem_signifikan(self):
        """10/10 benar-benar ekstrem -> p < 0,01."""
        self.assertLess(F.binom_p_two_sided(10, 10, 0.5), 0.01)

    def test_bh_fdr_monoton_dan_tidak_lebih_lolos(self):
        """BH-FDR tidak boleh meloloskan lebih banyak dari tanpa koreksi."""
        pv = [0.001, 0.01, 0.02, 0.04, 0.2, 0.5]
        keep = F.bh_fdr(pv, q=0.10)
        self.assertEqual(len(keep), len(pv))
        self.assertLessEqual(sum(keep), sum(1 for p in pv if p <= 0.10))
        # yang terkecil harus lolos bila yang lebih besar lolos
        for i in range(len(pv)):
            for j in range(len(pv)):
                if pv[i] < pv[j] and keep[j]:
                    self.assertTrue(keep[i], "monotoni BH dilanggar")

    def test_bh_fdr_input_kosong(self):
        self.assertEqual(F.bh_fdr([]), [])

    def test_bh_fdr_semua_besar_tidak_lolos(self):
        self.assertEqual(sum(F.bh_fdr([0.5, 0.6, 0.9])), 0)


class TestPnLBersih(unittest.TestCase):
    """Akurasi arah bukan laba: uji konversinya."""

    def test_flat_tanpa_biaya(self):
        self.assertEqual(F.net_bps("FLAT", 0.9, 8.0), 0.0)

    def test_long_mengurangi_fee_rt(self):
        """+0,50% mentah - 8 bps = +42 bps bersih."""
        self.assertAlmostEqual(F.net_bps("LONG", 0.005, 8.0), 42.0, places=6)

    def test_short_membalik_tanda(self):
        """Pasar turun -0,50% -> SHORT untung +42 bps bersih."""
        self.assertAlmostEqual(F.net_bps("SHORT", -0.005, 8.0), 42.0, places=6)

    def test_short_saat_pasar_naik_rugi(self):
        self.assertAlmostEqual(F.net_bps("SHORT", 0.005, 8.0), -58.0, places=6)

    def test_keuntungan_kecil_dihabiskan_fee(self):
        """+0,05% (5 bps) < fee 8 bps -> bersih NEGATIF. Ini inti F4."""
        self.assertLess(F.net_bps("LONG", 0.0005, 8.0), 0)


class TestCILaba(unittest.TestCase):
    def test_n_kurang_dua_mengembalikan_nan(self):
        m, lo, hi = F.mean_ci95([1.0])
        self.assertTrue(math.isnan(m))

    def test_ci_memuat_mean(self):
        m, lo, hi = F.mean_ci95([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertLess(lo, m)
        self.assertGreater(hi, m)

    def test_sebaran_nol_ci_menyempit_di_nol(self):
        """Data konstan -> CI lebar nol (bukan crash)."""
        m, lo, hi = F.mean_ci95([0.0] * 10)
        self.assertEqual(m, 0.0)
        self.assertAlmostEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.0)


class TestTanpaLookAhead(unittest.TestCase):
    """Aturan besi: jangan pernah melatih/menilai baris yang labelnya belum ada."""

    def test_semua_indeks_di_bawah_n_minus_horizon(self):
        n = 1000
        tr, oos, end = F.split_rows(n)
        self.assertEqual(end, n - F.LABEL_H)
        for i in list(tr) + list(oos):
            self.assertLess(int(i), n - F.LABEL_H,
                            "ada baris dengan label masa depan yang bocor")

    def test_train_dan_oos_tidak_tumpang_tindih(self):
        tr, oos, _ = F.split_rows(1000)
        self.assertFalse(set(tr) & set(oos), "train dan OOS tidak boleh beririsan")

    def test_oos_berada_setelah_train(self):
        tr, oos, _ = F.split_rows(1000)
        self.assertLess(int(tr.max()), int(oos.min()))

    def test_pembagian_sesuai_server_85_15(self):
        """Server memakai cut = int(0.85 * end), end = n - LABEL_H. Jangan menyimpang."""
        n = 1000
        tr, _, end = F.split_rows(n)
        self.assertEqual(end, n - F.LABEL_H)          # 952, bukan 1000
        self.assertEqual(len(tr), int((n - F.LABEL_H) * 0.85))   # 809


class TestSegmen(unittest.TestCase):
    def test_tiga_segmen_kronologis_dan_terpisah(self):
        segs = F.split3(list(range(99)))
        self.assertEqual(len(segs), 3)
        self.assertEqual([len(s) for s in segs], [33, 33, 33])
        self.assertLess(segs[0][-1], segs[1][0])
        self.assertLess(segs[1][-1], segs[2][0])

    def test_data_terlalu_kecil_tidak_dipaksa(self):
        """n kecil -> tidak ada segmen (dilaporkan '-'), bukan segmen palsu."""
        self.assertEqual(F.split3(list(range(8))), [])


class TestAntiDriftDariServer(unittest.TestCase):
    """Konstanta di sini HARUS sama dengan server. Kalau server berubah, ini gagal."""

    @classmethod
    def setUpClass(cls):
        with open(SERVER, encoding="utf-8") as fh:
            cls.src = fh.read()

    def _const(self, name):
        m = re.search(rf"^{name}\s*=\s*([0-9.]+)", self.src, re.M)
        self.assertIsNotNone(m, f"konstanta {name} tidak ditemukan di server")
        return float(m.group(1))

    def test_label_horizon_sama(self):
        self.assertEqual(F.LABEL_H, int(self._const("LABEL_H")))

    def test_threshold_sama(self):
        self.assertAlmostEqual(F.THRESHOLD, self._const("THRESHOLD"), places=9)

    def test_periodes_sama(self):
        m = re.search(r"^PERIODS\s*=\s*\[([0-9,\s]+)\]", self.src, re.M)
        self.assertIsNotNone(m)
        self.assertEqual(F.PERIODS, [int(x) for x in m.group(1).split(",")])

    def test_pembagian_oos_sama(self):
        self.assertIn("int(end * 0.85)", self.src,
                      "server mengubah rasio train/OOS — test 85/15 harus ditinjau")

    def test_server_masih_memakai_seleksi_threshold(self):
        """F1 hanya sah selama server memfilter |pred| >= THRESHOLD saat menilai."""
        self.assertIn("np.abs(pred) >= THRESHOLD", self.src,
                      "seleksi hilang: cacat F1 sudah diperbaiki, temuan perlu direvisi")


if __name__ == "__main__":
    unittest.main()
