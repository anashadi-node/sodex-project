"""Kalibrasi harness SODEX-ALT3 (cross-sectional). Tanpa ini, hasil "GAGAL" tak bermakna.

Yang dibuktikan di sini:
 1. Panel NULL (tak ada edge) -> harness TIDAK boleh menghasilkan p kecil.
 2. Panel dengan edge DISUNTIKKAN (drift per-simbol) -> harness WAJIB mendeteksi.
 3. Kontrol sadar-arah: pada panel ber-edge, arah fade harus RUGI.
 4. Bobot desil ternormalisasi.
 5. Tidak ada look-ahead pada forward return.
 6. Strategi RUGI dengan p kecil TIDAK boleh dinyatakan layak (regresi bug lama).
"""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sodex_alt3_xsec_study as st  # noqa: E402


def make_panel(n_sym=40, n_bar=800, drift_sd=0.0, seed=0, noise_sd=0.003):
    """Panel sintetis. drift_sd > 0 => tiap simbol punya drift tetap (edge momentum nyata)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n_bar, freq="1h", tz="UTC")
    cols = [f"S{i:02d}" for i in range(n_sym)]
    mu = rng.normal(0.0, drift_sd, n_sym) if drift_sd else np.zeros(n_sym)
    logp = np.cumsum(rng.normal(mu, noise_sd, size=(n_bar, n_sym)), axis=0)
    C = pd.DataFrame(np.exp(logp), index=idx, columns=cols)
    return C, C.copy()                     # O = C (open = close) demi kejelasan uji


class TestAlt3Harness(unittest.TestCase):

    def test_null_tidak_false_positive(self):
        """Tanpa edge, tak boleh ada p kecil. Kalau gagal: harness melaporkan edge palsu."""
        for seed in (1, 2, 3):
            C, O = make_panel(drift_sd=0.0, seed=seed)
            sig = st.signal(C, 24, "momentum")
            s, _ = st.port_returns(C, O, sig, 24, +1)
            p = st.rand_rank_p(C, O, sig, 24, +1, s.mean(), 200,
                               C.index[0], C.index[-1], np.random.default_rng(seed))
            self.assertGreater(p, 0.05, f"seed={seed}: p={p:.3f} -> false positive")

    def test_mendeteksi_edge_tersuntik(self):
        """Panel ber-drift HARUS terdeteksi: net > 0 dan p < 0,05."""
        C, O = make_panel(drift_sd=0.0002, seed=11)
        sig = st.signal(C, 24, "momentum")
        s, _ = st.port_returns(C, O, sig, 24, +1)
        p = st.rand_rank_p(C, O, sig, 24, +1, s.mean(), 200,
                           C.index[0], C.index[-1], np.random.default_rng(5))
        self.assertGreater(s.mean(), 0, "harness gagal mendeteksi edge tersuntik")
        self.assertLess(p, 0.05, f"p={p:.3f} -> harness tidak peka")

    def test_kontrol_sadar_arah(self):
        """Pada panel ber-edge, fade (dirn=-1) harus RUGI -- kontrol tahu arah."""
        C, O = make_panel(drift_sd=0.0002, seed=11)
        sig = st.signal(C, 24, "momentum")
        s_long, _ = st.port_returns(C, O, sig, 24, +1)
        s_fade, _ = st.port_returns(C, O, sig, 24, -1)
        self.assertGreater(s_long.mean(), 0)
        self.assertLess(s_fade.mean(), 0, "fade pada panel ber-edge malah untung -> arah terbalik")

    def test_bobot_desil_ternormalisasi(self):
        C, O = make_panel(drift_sd=0.0, seed=3)
        Wl, Ws, nn = st.weights(st.signal(C, 24, "momentum"), +1)
        live = nn > 0                      # baris warm-up memang belum punya posisi
        self.assertTrue(live.any(), "tidak ada baris berposisi sama sekali")
        for W in (Wl, Ws):
            sums = W.sum(axis=1)[live].dropna()
            self.assertTrue(len(sums) > 0 and np.allclose(sums, 1.0),
                            "bobot desil tidak berjumlah 1 pada baris berposisi")

    def test_tanpa_lookahead(self):
        C, O = make_panel(drift_sd=0.0, seed=4, n_bar=100)
        F = st.fwd(C, O, 24)
        self.assertTrue(F.iloc[-24:].isna().all().all(), "forward return bocor dari masa depan")
        self.assertFalse(F.iloc[-25].isna().all(), "baris -25 seharusnya masih punya target")

    def test_strategi_rugi_dengan_p_kecil_tidak_layak(self):
        """Regresi bug lama: net negatif + p kecil TIDAK boleh dianggap lulus."""
        v = st.verdict("X", net_bp=-12.0, stress_bp=-18.0, p=0.001, n_rebal=500,
                       top_share=0.10, oos_ex_bp=-9.0)
        self.assertFalse(v["c2_net"], "net negatif lolos c2")
        self.assertFalse(v["c3_stress"], "stress negatif lolos c3")
        self.assertFalse(all(v.values()), "strategi rugi dinyatakan layak")

    def test_mitigasi_independensi_arah_berlawanan_gagal(self):
        """§3: hasil penuh vs subset tanpa BTC/ETH/SOL berlawanan arah -> c6 gagal."""
        v = st.verdict("Y", net_bp=30.0, stress_bp=22.0, p=0.01, n_rebal=300,
                       top_share=0.12, oos_ex_bp=-5.0)
        self.assertFalse(v["c6_indep"], "arah berlawanan lolos c6 -> mitigasi bocor")


if __name__ == "__main__":
    unittest.main()
