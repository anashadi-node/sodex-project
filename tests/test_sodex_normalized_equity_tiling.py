"""Test sodex_normalized_equity — deret trading-only TILING + jebakan Sharpe.

Latar (2026-10-04): versi lama membangun "trading-only equity" dari `stats.net_6h`
(rolling 6 jam, sampel ~4,8 jam -> tumpang-tindih) sehingga over-count 0,91x dan
kurva melayang di bawah nol -> MaxDD -115,473% (mustahil). RCA: yang tiling adalah
`observed_delta_usd` (selisih snapshot berurutan). Test ini mengunci perbaikan itu
DAN mengunci jebakan rata-rata aritmetika-vs-geometrik.
"""
import datetime as dt
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location(
    "sodex_normalized_equity", ROOT / "scripts" / "sodex_normalized_equity.py")
ne = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ne)

T0 = dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc)


def rows_from_deltas(deltas, start_eq=1000.0, step_h=5.0):
    """Bangun capital_rows dari daftar delta dolar."""
    out, eq, t = [], start_eq, T0
    out.append({"ts": t, "equity": eq, "stats": {}})
    for d in deltas:
        eq += d
        t = t + dt.timedelta(hours=step_h)
        out.append({"ts": t, "equity": eq, "stats": {}})
    return out


class TestTilingDanMetrik(unittest.TestCase):
    def test_jumlah_delta_sama_dgn_perubahan_observed(self):
        """INTI RCA: delta non-overlapping menjumlah TEPAT ke perubahan equity."""
        deltas = [10.0, -4.0, 7.0, -2.0, 5.0]
        r = ne.build_series(rows_from_deltas(deltas), [])
        self.assertTrue(r["valid"])
        self.assertAlmostEqual(sum(float(x["observed_delta_usd"]) for x in r["rows"]),
                               sum(deltas), places=9)
        self.assertAlmostEqual(r["observed_total_delta_usd"], sum(deltas), places=9)

    def test_maxdd_diketahui(self):
        """1000 -> 500 -> 750: drawdown puncak-ke-palung = -50%."""
        r = ne.build_series(rows_from_deltas([-500.0, 250.0]), [])
        self.assertAlmostEqual(r["maxdd_trading_only"], -0.5, places=9)

    def test_maxdd_tidak_pernah_lebih_buruk_dari_minus_100persen(self):
        """Batas keras: equity tidak bisa rugi >100%."""
        r = ne.build_series(rows_from_deltas([-500.0, -400.0, 300.0]), [])
        self.assertGreaterEqual(r["maxdd_trading_only"], -1.0)

    def test_compounding_factor_sama_dgn_rasio_nyata(self):
        deltas = [100.0, -250.0, 80.0]
        r = ne.build_series(rows_from_deltas(deltas), [])
        self.assertAlmostEqual(r["compounding_factor"],
                               r["end_equity_usd"] / r["start_equity_usd"], places=9)

    def test_snapshot_equity_nol_atau_negatif_dibuang(self):
        rows = rows_from_deltas([100.0, 50.0])
        rows.append({"ts": T0 + dt.timedelta(hours=99), "equity": 0.0, "stats": {}})
        r = ne.build_series(rows, [])
        self.assertEqual(r["zero_or_negative_snapshot_count"], 1)
        self.assertGreater(r["end_equity_usd"], 0)

    def test_fail_closed_bila_snapshot_kurang_dari_dua(self):
        r = ne.build_series([{"ts": T0, "equity": 100.0, "stats": {}}], [])
        self.assertFalse(r["valid"])
        self.assertIn("FAIL_CLOSED", r["reason"])


class TestJebakanSharpeAritmetika(unittest.TestCase):
    """Kurva yang RUGI bisa memberi Sharpe aritmetika POSITIF. Harus tidak dipakai."""

    def _kurva_rugi_dgn_mean_positif(self):
        # rugi besar di awal saat ekuitas besar, lalu banyak kenaikan kecil di
        # ekuitas yang sudah menyusut -> tiap kenaikan menjadi % yang lebih besar.
        deltas = [-560.0] + [10.0] * 55
        return ne.build_series(rows_from_deltas(deltas, start_eq=1000.0), [])

    def test_kurva_memang_rugi(self):
        r = self._kurva_rugi_dgn_mean_positif()
        self.assertLess(r["observed_total_delta_usd"], 0)
        self.assertLess(r["compounding_factor"], 1.0)

    def test_aritmetika_berbanding_terbalik_dgn_log(self):
        r = self._kurva_rugi_dgn_mean_positif()
        self.assertGreater(r["mean_return_arithmetic"], 0.0, "prasyarat jebakan")
        self.assertLess(r["mean_return_log"], 0.0)
        self.assertGreater(r["sharpe_ann_trading_only_arithmetic"], 0.0)
        self.assertLess(r["sharpe_ann_trading_only"], 0.0)

    def test_bendera_tidak_interpretabel_menyala(self):
        r = self._kurva_rugi_dgn_mean_positif()
        self.assertFalse(r["sharpe_arithmetic_interpretable"])

    def test_net6h_tidak_dipakai_untuk_metrik(self):
        """`sharpe_ann_6h_trading_only` harus tetap NaN (sumber tidak sah)."""
        r = ne.build_series(rows_from_deltas([10.0, -5.0, 3.0]), [])
        self.assertNotEqual(r["sharpe_ann_6h_trading_only"], r["sharpe_ann_6h_trading_only"])

    def test_periode_disetahunkan_dari_interval_nyata(self):
        r = ne.build_series(rows_from_deltas([10.0] * 10, step_h=5.0), [])
        self.assertAlmostEqual(r["median_interval_hours"], 5.0, places=9)
        self.assertAlmostEqual(r["periods_per_year"], 8760.0 / 5.0, places=6)


if __name__ == "__main__":
    unittest.main()
