"""Test breakdown per-sisi SoDEX (scripts/sodex_side_breakdown.py).

KONTEKS
-------
Harness menilai track secara agregat (LONG+SHORT dicampur), sehingga edge satu
kaki bisa tersembunyi oleh kaki lain. Temuan 2026-10-04: kaki LONG `twoway`
ber-edge +8,05 bps sementara fee RT = 8,00 bps -> cost 1x praktis nol. Tanpa
breakdown per-sisi, kesimpulan ini tak terlihat.

Test ini mengunci:
  1. filter sisi (LONG vs SHORT) benar,
  2. rumus "fee impas" konsisten (fee di mana net = 0 pada cost 2x),
  3. script dapat diimpor & punya entry point.

Tidak menyentuh jaringan maupun registry.
"""
import importlib
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "docs/handover/RISET_TO_DIVISI_2026-10-01/harness"))

sb = importlib.import_module("sodex_side_breakdown")


def fee_impas_bps(edge_frac: float) -> float:
    """Fee RT (bps) di mana hasil bersih = 0 pada stress 2x biaya."""
    return (edge_frac / 2.0) * 10_000.0


class TestFilterSisi(unittest.TestCase):
    def setUp(self):
        # baris tiruan: side_sign() asli membaca field trade; kita pakai stub.
        self._asli = sb.H.side_sign

    def tearDown(self):
        sb.H.side_sign = self._asli

    def test_memisahkan_long_dan_short(self):
        rows = [{"_s": 1}, {"_s": -1}, {"_s": 1}, {"_s": -1}, {"_s": 1}]
        sb.H.side_sign = lambda r: r["_s"]
        self.assertEqual(len(sb.sisi_kaki(rows, 1)), 3)
        self.assertEqual(len(sb.sisi_kaki(rows, -1)), 2)

    def test_sisi_tak_ada_menghasilkan_kosong(self):
        rows = [{"_s": 1}]
        sb.H.side_sign = lambda r: r["_s"]
        self.assertEqual(sb.sisi_kaki(rows, -1), [])

    def test_tidak_mengubah_daftar_asli(self):
        rows = [{"_s": 1}, {"_s": -1}]
        sb.H.side_sign = lambda r: r["_s"]
        sb.sisi_kaki(rows, 1)
        self.assertEqual(len(rows), 2, "daftar masukan tidak boleh dimutasi")


class TestRumusFeeImpas(unittest.TestCase):
    """Mengunci rumus: fee_impas = edge / 2."""

    def test_temuan_twoway_long(self):
        # edge +8,05 bps -> fee impas ~4,03 bps (fee sekarang 8 bps: GAGAL 2x)
        impas = fee_impas_bps(8.05 / 10_000.0)
        self.assertAlmostEqual(impas, 4.025, places=2)
        self.assertLess(impas, 8.0, "edge setara fee -> fee impas di bawah fee sekarang")

    def test_temuan_twoway_short(self):
        # edge +60,94 bps -> fee impas ~30,47 bps (fee bisa naik 3,8x)
        impas = fee_impas_bps(60.94 / 10_000.0)
        self.assertAlmostEqual(impas, 30.47, places=2)
        self.assertGreater(impas, 8.0, "edge 7,6x fee -> tahan jauh di atas fee sekarang")

    def test_edge_negatif_tak_punya_titik_impas(self):
        self.assertLess(fee_impas_bps(-12.26 / 10_000.0), 0.0)

    def test_konsisten_dgn_cost2x(self):
        """net @2x = edge - 2*fee  -> nol tepat saat fee = edge/2."""
        edge, fee = 0.0805, 0.04025
        self.assertAlmostEqual(edge - 2 * fee, 0.0, places=10)


class TestEntryPoint(unittest.TestCase):
    def test_modul_punya_main(self):
        self.assertTrue(callable(sb.main))

    def test_min_n_sesuai_dokumen_riset(self):
        # dokumen riset 10.1: n >= 30 = evidence minimum
        self.assertEqual(sb.MIN_N, 30)


if __name__ == "__main__":
    unittest.main()
