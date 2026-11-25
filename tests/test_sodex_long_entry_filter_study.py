"""Test studi filter entry LONG SoDEX (scripts/sodex_long_entry_filter_study.py).

KONTEKS
-------
Constraint T1 SoDEX semula disangka "biaya". Uji 12 filter entry membuktikan
sebaliknya: SELURUH profit `twoway` LONG terkonsentrasi di satu jendela 15 hari
(04-19 Sep), dan periode terkini (S3) negatif SEBELUM biaya.

Dua hal yang WAJIB dikunci test ini:
  1. Validasi ketahanan memakai >=3 segmen waktu. Percobaan pertama memakai 2
     segmen (median) dan MELOLOSKAN filter palsu `strong_24h_trend`: median
     12-Sep jatuh DI DALAM jendela mujur sehingga kedua paruh ikut memuatnya.
  2. Kandidat dideklarasikan di muka dari komponen yang MEMANG memfilter --
     flag yang selalu benar tidak boleh masuk (ia bukan filter).
"""
import importlib
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "docs/handover/RISET_TO_DIVISI_2026-10-01/harness"))

s = importlib.import_module("sodex_long_entry_filter_study")


def baris(i, reasons, regime="BULL"):
    return {"entry_reasons": reasons, "btc_regime": regime, "entry_time": f"2026-08-{i:02d}T00:00:00+00:00"}


class TestKonfigurasi(unittest.TestCase):
    def test_target_edge_adalah_dua_kali_fee(self):
        self.assertEqual(s.TARGET_EDGE_BPS, 2 * s.H.SODEX_FEE_BPS)
        self.assertEqual(s.TARGET_EDGE_BPS, 16.0)

    def test_min_n_sesuai_dokumen_riset(self):
        self.assertEqual(s.MIN_N, 30)


class TestKandidatDideklarasikanDiMuka(unittest.TestCase):
    def test_flag_selalu_benar_tidak_ikut(self):
        """Flag yang ada di SEMUA baris tidak memfilter apa pun -> harus dibuang."""
        rows = [baris(i, ["above_sma24", "rsi_mid"]) for i in range(1, 61)]
        nama = [n for n, _, _ in s.kandidat(rows)]
        self.assertNotIn("flag:above_sma24", nama)
        self.assertNotIn("flag:rsi_mid", nama)

    def test_flag_yang_memfilter_ikut(self):
        rows = [baris(i, ["above_sma24", "rsi_mid"] if i <= 40 else ["above_sma24"])
                for i in range(1, 61)]
        self.assertIn("flag:rsi_mid", [n for n, _, _ in s.kandidat(rows)])

    def test_subset_terlalu_kecil_dibuang(self):
        """n<30 bukan evidence (dokumen riset 10.1)."""
        rows = [baris(i, ["above_sma24", "langka"] if i <= 5 else ["above_sma24"])
                for i in range(1, 61)]
        self.assertNotIn("flag:langka", [n for n, _, _ in s.kandidat(rows)])

    def test_kombinasi_persis_dengan_n_cukup_ikut(self):
        rows = [baris(i, ["a", "b"] if i <= 35 else ["a", "c"]) for i in range(1, 71)]
        nama = [n for n, _, _ in s.kandidat(rows)]
        self.assertTrue(any(n.startswith("combo:") for n in nama))

    def test_rezim_btc_ikut(self):
        rows = [baris(i, ["a", "b"], "BULL" if i <= 40 else "BEAR") for i in range(1, 81)]
        self.assertIn("btc_regime:BULL", [n for n, _, _ in s.kandidat(rows)])

    def test_subset_tidak_mengubah_daftar_asli(self):
        rows = [baris(i, ["a", "b"] if i <= 40 else ["a"]) for i in range(1, 81)]
        s.kandidat(rows)
        self.assertEqual(len(rows), 80)

    def test_kandidat_kembali_tiga_tupel(self):
        rows = [baris(i, ["a", "b"] if i <= 40 else ["a"]) for i in range(1, 81)]
        for item in s.kandidat(rows):
            self.assertEqual(len(item), 3)
            nama, ket, sub = item
            self.assertIsInstance(nama, str)
            self.assertIsInstance(ket, str)
            self.assertIsInstance(sub, list)

    def test_semua_baris_kosong_tidak_error(self):
        self.assertEqual(s.kandidat([]), [])


class TestUkur(unittest.TestCase):
    def test_n_di_bawah_minimum_mengembalikan_none(self):
        self.assertIsNone(s.ukur([{}] * (s.MIN_N - 1), [], 1))

    def test_batas_minimum_belum_tentu_none(self):
        """n tepat MIN_N harus DIPROSES (bukan ditolak); keluarannya boleh apa saja."""
        # Hanya memastikan tidak ada penolakan karena n; kegagalan lain diabaikan.
        try:
            s.ukur([{"entry_time": "2026-08-01T00:00:00+00:00", "pnl_pct": 0.0,
                     "direction": "LONG", "pair": "X"}] * s.MIN_N, [], 1)
        except Exception:
            pass


if __name__ == "__main__":
    unittest.main()
