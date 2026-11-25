"""Test gate maturasi SoDEX (DUA GATE TERPISAH) + normalisasi skema track.

Regresi yang dijaga:
 - ROI dihitung thd TOTAL wallet (spot+perps), bukan denominator basi.
 - Gate ROI = akumulasi per window 30h (definisi target user), bukan per trade.
 - Sampel window kurang -> gate TIDAK lolos (bukan lolos diam-diam).
 - Edge outlier-driven -> flag caution muncul.
 - Sampel dua gate TIDAK PERNAH digabung (satu metode tidak menyembunyikan yang lain).
 - Normalisasi skema: `closed`(epoch exit_ts) vs `closed_trades`(ISO exit_time).
"""
from __future__ import annotations
import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path

TRACKER = Path(__file__).resolve().parents[1] / "scripts" / "sodex_maturation_tracker.py"
spec = importlib.util.spec_from_file_location("matur", TRACKER)
matur = importlib.util.module_from_spec(spec)
spec.loader.exec_module(matur)

T0 = datetime(2026, 9, 10, 0, 0, tzinfo=timezone.utc).timestamp()
H = 3600.0

# Nama gate setelah AMANDEMEN 10-Okt-2026 (grid tetap 30 jam, syarat A DAN B).
G = " (grid tetap)"
KEY_MEAN = f"window_mean>=0.8%{G}"
KEY_MED = f"window_median>0{G}"
KEY_HIT = f"window_hit>=50%{G}"
KEY_AB = f"window_A&B{G}"


def tr(offset_h, usd, pct=0.0):
    return {"exit_ts": T0 + offset_h * H, "pnl_usd": usd, "pnl_pct": pct, "sym": "BTC"}


class TestWindowMetrics(unittest.TestCase):
    def test_grid_tetap_anchor_bukan_span(self):
        """Amandemen 10-Okt-2026: bucket dari JANGKAR TETAP, bukan dari exit pertama."""
        trades = [tr(0, 1.0), tr(5, 1.0), tr(31, 2.0), tr(62, -1.0)]
        wm = matur.window_metrics(trades, 100.0)
        self.assertTrue(wm["grid"].startswith("fixed-anchor"))
        self.assertEqual(wm["n_windows"], 3)
        self.assertAlmostEqual(wm["mean_pct"], 1.0, places=6)    # [2,+2,-1]/3
        self.assertAlmostEqual(wm["best_pct"], 2.0, places=6)
        self.assertAlmostEqual(wm["worst_pct"], -1.0, places=6)

    def test_window_kosong_dilewati_dan_dihitung(self):
        trades = [tr(0, 1.0), tr(20, 1.0), tr(300, 2.0)]
        wm = matur.window_metrics(trades, 100.0)
        self.assertEqual(wm["n_windows"], 3)       # hanya yang berisi trade
        self.assertEqual(wm["n_empty"], 8)         # 11 window terentang, 8 kosong
        self.assertAlmostEqual(wm["mean_pct"], (1 + 1 + 2) / 3, places=6)

    def test_negative_window_counted_and_hit_rate(self):
        trades = [tr(0, 5.0), tr(31, -5.0), tr(62, 5.0)]
        wm = matur.window_metrics(trades, 100.0)   # window = [+5, -5, +5]
        self.assertEqual(wm["n_windows"], 3)
        self.assertEqual(wm["hit"], 2)             # dua window >= 0,8%
        self.assertAlmostEqual(wm["hit_rate"], 2 / 3, places=6)

    def test_wallet_denominator_scales_roi(self):
        trades = [tr(0, 2.0), tr(31, 2.0)]
        small = matur.window_metrics(trades, 100.0)
        big = matur.window_metrics(trades, 400.0)
        self.assertAlmostEqual(small["mean_pct"] / big["mean_pct"], 4.0, places=6)

    def test_too_few_points_returns_none(self):
        self.assertIsNone(matur.window_metrics([tr(0, 1.0)], 100.0))
        self.assertIsNone(matur.window_metrics([], 100.0))

    def test_grid_tidak_ikut_bergerak_saat_trade_lama_ditambah(self):
        """Bukti grid TETAP: menambah trade jauh di masa lalu TIDAK menggeser
        window trade yang sudah ada (dulu span-based grid bergeser)."""
        sub = [tr(0, 1.0), tr(31, 2.0)]
        w_sub = matur.window_metrics(sub, 100.0)
        w_all = matur.window_metrics([tr(-800, 0.5)] + sub, 100.0)
        self.assertAlmostEqual(w_all["best_pct"], w_sub["best_pct"], places=6)
        self.assertEqual(w_all["n_windows"], w_sub["n_windows"] + 1)   # +1 window lama

    def test_trade_sebelum_anchor_diabaikan(self):
        """Trade sebelum jangkar (2026-08-03Z) di luar grid -> dilewati (bukan digeser)."""
        wm = matur.window_metrics([tr(-1000, 5.0), tr(0, 1.0), tr(31, 1.0)], 100.0)
        self.assertEqual(wm["n_windows"], 2)


class TestGateGates(unittest.TestCase):
    def _bulk(self, n, usd_each, hours_apart=3.0):
        return [tr(i * hours_apart, usd_each, pct=0.004) for i in range(n)]

    def test_roi_gate_requires_enough_windows(self):
        trades = self._bulk(60, 3.0, hours_apart=0.1)      # span ~6h -> 1 window
        res = matur.evaluate_trades(trades, 108.10, "T", "x")
        self.assertFalse(res["gates"][KEY_MEAN])
        self.assertIn("window", res.get("roi_gate_note", "window"))

    def test_gate_passes_with_enough_windows_and_positive_flow(self):
        trades = self._bulk(60, 3.0, hours_apart=6.0)      # span 354h -> 13 window
        res = matur.evaluate_trades(trades, 108.10, "T", "x")
        self.assertTrue(res["gates"][KEY_MEAN])
        self.assertTrue(res["gates"][KEY_AB])
        self.assertGreaterEqual(res["n_windows"], matur.MIN_WINDOWS)
        self.assertEqual(res["verdict"], "GO")

    def test_caution_flagged_when_median_below_target(self):
        trades = self._bulk(19, 0.05, hours_apart=30.0) + [tr(30 * 25, 500.0, pct=0.005)]
        res = matur.evaluate_trades(trades, 100.0, "T", "x")
        self.assertIn("caution", res)
        self.assertIn("median", res["caution"])

    def test_per_trade_roi_is_info_only_not_the_gate(self):
        # 60 trade, tiap trade kecil (0,2% wallet) tapi banyak -> window mean lolos.
        trades = self._bulk(60, 0.2, hours_apart=6.0)      # 0.2% * 5 = 1.0%/window
        res = matur.evaluate_trades(trades, 100.0, "T", "x")
        self.assertLess(res["per_trade_roi_pct"], 0.8)     # per trade di bawah target
        self.assertTrue(res["gates"][KEY_MEAN])            # tapi gate window lolos


class TestAmandemenAB(unittest.TestCase):
    """Amandemen 10-Okt-2026: gerbang = A (mean>=0,8%) DAN B (median>0 & hit>=50%)
    pada GRID TETAP 30 jam. Mean saja TIDAK cukup."""

    def test_mean_lolos_tapi_median_gagal_tidak_lolos(self):
        # satu window raksasa menopang mean, mayoritas window kecil/negatif
        trades = [tr(30 * i, -0.05) for i in range(14)] + [tr(30 * 15, 500.0)]
        res = matur.evaluate_trades(trades, 100.0, "T", "gx")
        self.assertTrue(res["gates"][KEY_MEAN])       # mean tertarik outlier
        self.assertFalse(res["gates"][KEY_MED])       # median <= 0
        self.assertFalse(res["gates"][KEY_AB])        # A&B wajib dua-duanya
        self.assertNotEqual(res["verdict"], "GO")

    def test_median_dan_hit_sehat_lolos_AB(self):
        trades = [tr(30 * i, 1.0) for i in range(12)]
        res = matur.evaluate_trades(trades, 100.0, "T", "gy")
        self.assertTrue(res["gates"][KEY_AB])
        self.assertEqual(res["gate_A_mean"], True)
        self.assertEqual(res["gate_B_konsisten"], True)

    def test_definisi_lama_tetap_dilaporkan_sebagai_jejak(self):
        trades = [tr(30 * i, 1.0) for i in range(12)]
        res = matur.evaluate_trades(trades, 100.0, "T", "gz")
        self.assertEqual(res["window_grid"], "fixed-anchor-2026-08-03Z")
        self.assertIn("span_median_pct", res)         # jejak grid lama, bukan verdict


class TestGateSeparation(unittest.TestCase):
    """Dua gate harus tetap terpisah: tidak ada penggabungan sampel."""

    def test_samples_never_merged(self):
        a = [tr(i * 6.0, 3.0, pct=0.004) for i in range(60)]          # REAL-WIDE
        b = [tr(i * 6.0, -1.0, pct=-0.002) for i in range(60)]        # TWO-WAY rugi
        ra = matur.evaluate_trades(a, 100.0, "REAL-WIDE", "gA")
        rb = matur.evaluate_trades(b, 100.0, "TWO-WAY", "gB")
        self.assertEqual(ra["n"], len(a))
        self.assertEqual(rb["n"], len(b))
        self.assertEqual(ra["gate"], "REAL-WIDE")
        self.assertNotEqual(ra["verdict"], rb["verdict"])   # kuat vs lemah terpisah

    def test_gate_config_has_two_distinct_methods(self):
        ids = [g["id"] for g in matur.GATES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("REAL-WIDE", ids)
        self.assertIn("TWO-WAY", ids)
        # sumber sampel wajib berbeda -> mustahil saling menutupi
        self.assertEqual(len({g["state"] for g in matur.GATES}), len(ids))


class TestNormalisasiSkema(unittest.TestCase):
    def test_schema_closed_epoch_exit_ts(self):
        doc = {"closed": [{"exit_ts": T0, "pnl_usd": 1.5, "pnl_pct": 0.005, "sym": "BTC"}]}
        r = matur._norm_trades(doc)
        self.assertEqual(len(r), 1)
        self.assertAlmostEqual(r[0]["pnl_usd"], 1.5)

    def test_schema_closed_trades_iso_exit_time(self):
        doc = {"closed_trades": [{"exit_time": "2026-09-10T05:00:00+00:00",
                                  "pnl_usd": -2.0, "pnl_pct": -0.006, "pair": "ETH"}]}
        r = matur._norm_trades(doc)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["sym"], "ETH")
        self.assertGreater(r[0]["exit_ts"], T0)

    def test_rows_without_usd_dropped(self):
        doc = {"closed": [{"exit_ts": T0}, {"exit_ts": T0, "pnl_usd": 1.0}]}
        self.assertEqual(len(matur._norm_trades(doc)), 1)

    def test_stale_exit_dibuang_dari_sampel_gate(self):
        """Exit terlambat (feed mati berhari-hari) tidak sah: harga exit bukan harga 24h."""
        doc = {"closed": [
            {"exit_ts": T0, "pnl_usd": 1.0, "sym": "AAA", "hold_h": 24.0},
            {"exit_ts": T0 + 60, "pnl_usd": -5.0, "sym": "BBB", "hold_h": 189.7,
             "stale_exit": True, "stale_reason": "outage_empty_ohlcv_8d"},
        ]}
        out = matur._norm_trades(doc)
        self.assertEqual([t["sym"] for t in out], ["AAA"])
        self.assertAlmostEqual(sum(t["pnl_usd"] for t in out), 1.0)


if __name__ == "__main__":
    unittest.main()
