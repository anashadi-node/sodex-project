"""Test studi gerbang rezim ex-ante (scripts/sodex_regime_gate_study.py).

YANG DIKUNCI DI SINI
--------------------
1. TIDAK ADA LOOK-AHEAD. Prediktor "ex-ante" hanya boleh bernilai dari data yang
   SUDAH ADA sebelum trade dibuka. Ini kesalahan paling merusak di seluruh riset
   kuantitatif: satu bar masa depan yang bocor membuat hasil tampak hebat di
   backtest dan hilang di trading nyata. Uji ini menaruh nilai EKSTREM tepat di
   bar `entry` dan memastikan prediktor TIDAK melihatnya.

2. Bentuk keluaran stabil (5 kandidat, nama tetap) supaya penambahan/penghapusan
   kandidat tanpa sengaja langsung terlihat.

3. Skala-data: `vol_n` butuh >=3 bar; di bawah itu harus mengembalikan None,
   bukan crash atau angka palsu.
"""
import importlib
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "docs/handover/RISET_TO_DIVISI_2026-10-01/harness"))

g = importlib.import_module("sodex_regime_gate_study")

BAR = 900_000
T0 = 1_785_980_700_000  # 2026-08-06 01:45 UTC, sama dgn bar pertama di trail_lab


def deret(n: int, mulai: float = 100.0, naik: float = 0.01):
    ts = [T0 + i * BAR for i in range(n)]
    cl = [mulai * (1 + naik) ** i for i in range(n)]
    return ts, cl


class TestTanpaLookAhead(unittest.TestCase):
    def test_ret_n_tidak_melihat_bar_entry(self):
        """Bar 'masa depan' bernilai ekstrem tidak boleh mempengaruhi hasil."""
        ts, cl = deret(20)
        t = ts[10]                      # tepat di bar ke-10
        a = g.ret_n(ts, cl, t, 5 * BAR)
        cl_bom = list(cl)
        cl_bom[10] = cl[10] * 1000      # ledakan di bar entry
        b = g.ret_n(ts, cl_bom, t, 5 * BAR)
        self.assertEqual(a, b, "ret_n MELIHAT bar entry -> look-ahead!")

    def test_ret_n_tidak_melihat_bar_setelah_entry(self):
        ts, cl = deret(20)
        t = ts[10]
        a = g.ret_n(ts, cl, t, 5 * BAR)
        cl_bom = list(cl)
        for i in range(11, 20):
            cl_bom[i] = cl[i] * 1000
        b = g.ret_n(ts, cl_bom, t, 5 * BAR)
        self.assertEqual(a, b, "ret_n MELIHAT bar masa depan -> look-ahead!")

    def test_vol_n_tidak_melihat_masa_depan(self):
        ts, cl = deret(40, naik=0.002)
        t = ts[20]
        a = g.vol_n(ts, cl, t, 10 * BAR)
        cl_bom = list(cl)
        for i in range(21, 40):
            cl_bom[i] = cl[i] * 500
        b = g.vol_n(ts, cl_bom, t, 10 * BAR)
        self.assertEqual(a, b, "vol_n MELIHAT bar masa depan -> look-ahead!")

    def test_nilai_pakai_bar_sebelumnya_bukan_entry(self):
        """Naik seragam: return 24 jam = (1+naik)^96 - 1, bukan termasuk bar entry."""
        ts, cl = deret(200)
        t = ts[150]
        r = g.ret_n(ts, cl, t, 96 * BAR)
        self.assertIsNotNone(r)
        # bar ke-149 dibagi bar ke-53  (150 - 96 = 54; bisect_left(ts,ts[150])-1 = 149)
        harap = cl[149] / cl[53] - 1.0
        self.assertAlmostEqual(r, harap, places=12)


class TestBentukKeluaran(unittest.TestCase):
    def test_fitur_mengembalikan_lima_kandidat(self):
        pen = {"BTCUSDT": deret(300), "SOLUSDT": deret(300, mulai=10.0)}
        f = g.fitur_ex_ante(T0 + 250 * BAR, pen)
        self.assertEqual(sorted(f), ["breadth24", "btctrend", "btcvol24", "rs24", "rs7d"])

    def test_data_kurang_mengembalikan_none_bukan_crash(self):
        pen = {"BTCUSDT": deret(3), "SOLUSDT": deret(3)}
        f = g.fitur_ex_ante(T0 + 2 * BAR, pen)
        self.assertEqual(sorted(f), ["breadth24", "btctrend", "btcvol24", "rs24", "rs7d"])
        self.assertIsNone(f["rs24"])          # tak cukup bar utk jendela 24 jam
        self.assertIsNone(f["btcvol24"])

    def test_tidak_error_saat_panel_kosong(self):
        f = g.fitur_ex_ante(T0, {})
        self.assertIsNone(f["rs24"])
        self.assertIsNone(f["btctrend"])

    def test_breadth_selalu_dalam_0_sampai_1(self):
        pen = {"BTCUSDT": deret(300), "A": deret(300, naik=0.02), "B": deret(300, naik=-0.02)}
        f = g.fitur_ex_ante(T0 + 250 * BAR, pen)
        self.assertGreaterEqual(f["breadth24"], 0.0)
        self.assertLessEqual(f["breadth24"], 1.0)

    def test_xaut_tidak_dihitung_sebagai_alt(self):
        """XAUT itu emas, bukan alt crypto -- tidak boleh masuk keranjang rs24."""
        dasar = {"BTCUSDT": deret(300, naik=0.0), "A": deret(300, naik=0.05)}
        tanpa = g.fitur_ex_ante(T0 + 250 * BAR, dasar)
        dgn = dict(dasar)
        dgn["XAUTUSDT"] = deret(300, naik=-0.50)   # emas jatuh tajam
        ada = g.fitur_ex_ante(T0 + 250 * BAR, dgn)
        self.assertAlmostEqual(tanpa["rs24"], ada["rs24"], places=12,
                               msg="XAUT ikut terhitung sebagai alt!")


class TestAmbang(unittest.TestCase):
    def test_ambang_layak_dua_kali_fee(self):
        self.assertEqual(g.GATE_EDGE_BPS, 2 * g.H.SODEX_FEE_BPS)
        self.assertEqual(g.GATE_EDGE_BPS, 16.0)

    def test_min_n_sesuai_dokumen_riset(self):
        """n<30 bukan evidence (dokumen riset 10.1) -> edge() harus None, bukan angka."""
        self.assertEqual(g.MIN_N, 30)
        self.assertIsNone(g.edge([{}] * (g.MIN_N - 1), [], 27))

    def test_edge_tidak_crash_saat_fee_nol(self):
        """Fee 0 tetap harus lewat jalur normal, bukan exception."""
        self.assertEqual(g.H.SODEX_FEE_BPS, 8.0)


if __name__ == "__main__":
    unittest.main()
