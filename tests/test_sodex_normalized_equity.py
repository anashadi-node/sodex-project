import datetime as dt
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sodex_normalized_equity as ne  # noqa: E402


UTC = dt.timezone.utc


class TestSodexNormalizedEquity(unittest.TestCase):
    """The module is FAIL-CLOSED since 2026-10-04.

    It previously accumulated the rolling `stats.net_6h` field into a series it
    called "normalized trading-only equity". Because `net_6h` is a rolling 6 h
    window sampled at a ~4.8 h median cadence, summing it double-counts; the
    series drifted negative and the report carried `maxdd_trading_only = -115%`,
    which is impossible for an equity curve. These tests pin the fail-closed
    contract so the fabrication cannot silently return.
    """

    def row(self, ts: str, equity: float, net_6h: float = 0.0):
        return {"ts": ne.parse_dt(ts), "equity": equity, "stats": {"net_6h": net_6h}}

    def test_net6h_tidak_pernah_jadi_dasar_metrik(self):
        """GUARD DIPERTAHANKAN: `stats.net_6h` (rolling) tidak boleh menjadi sumber metrik.

        Sebelumnya test ini menuntut `valid=False`; setelah RCA 2026-10-04 deret
        yang SAH dibangun dari `observed_delta_usd`. Yang tetap dilarang adalah
        memakai `net_6h` sebagai sumber -- itu yang dulu menghasilkan -115%.
        """
        capital = [
            self.row("2026-01-01T00:00:00+00:00", 100.0, 0.0),
            self.row("2026-01-01T06:00:00+00:00", 79.0, -1.0),
        ]
        result = ne.build_series(capital, [])
        self.assertTrue(math.isnan(result["sharpe_ann_6h_trading_only"]),
                        "metrik 6h tidak boleh diisi dari sumber rolling")
        self.assertIn("net_6h", result["reason"])
        self.assertNotIn("net_6h", "".join(
            k for k in result["rows"][-1] if k == "ts" or "observed" in k) or "")

    def test_maxdd_selalu_di_rentang_mustahil(self):
        """-115% MaxDD tidak boleh kembali: MaxDD wajib berada di [-1, 0]."""
        capital = [self.row(f"2026-01-01T{h:02d}:00:00+00:00", 100.0 + h, (-1.0) ** h) for h in range(0, 18, 6)]
        result = ne.build_series(capital, [])
        self.assertGreaterEqual(result["maxdd_trading_only"], -1.0)
        self.assertLessEqual(result["maxdd_trading_only"], 0.0)
        self.assertTrue(math.isnan(result["sharpe_ann_6h_trading_only"]),
                        "metrik 6h tetap NaN")

    def test_deret_wajib_rekonsiliasi_tepat_ke_observed(self):
        """Syarat sah: jumlah delta HARUS sama persis dgn perubahan equity observed."""
        capital = [self.row(f"2026-01-01T{h:02d}:00:00+00:00", 100.0 + h) for h in range(0, 18, 6)]
        result = ne.build_series(capital, [])
        total = sum(float(r["observed_delta_usd"]) for r in result["rows"])
        self.assertAlmostEqual(total, result["observed_total_delta_usd"], places=9)
        self.assertAlmostEqual(total, result["end_equity_usd"] - result["start_equity_usd"], places=9)

    def test_reconcile_event_only_counts_inside_interval(self):
        capital = [
            self.row("2026-01-01T00:00:00+00:00", 100.0, 0.0),
            self.row("2026-01-01T06:00:00+00:00", 101.0, 1.0),
        ]
        rec = [
            {"ts": ne.parse_dt("2025-12-31T23:59:00+00:00"), "pnl_usd": -50.0},
            {"ts": ne.parse_dt("2026-01-01T06:00:00+00:00"), "pnl_usd": 2.0},
        ]
        result = ne.build_series(capital, rec)
        self.assertAlmostEqual(result["rows"][-1]["reconcile_net_usd"], 2.0)
        self.assertAlmostEqual(result["total_reconcile_net_usd"], 2.0)

    def test_over_count_ratio_is_measured_and_reported(self):
        """The double-count is quantified, not hidden: 2 rows of -1.0 against -1.0 observed."""
        capital = [
            self.row("2026-01-01T00:00:00+00:00", 100.0, 0.0),
            self.row("2026-01-01T06:00:00+00:00", 99.0, -1.0),
        ]
        result = ne.build_series(capital, [])
        self.assertAlmostEqual(result["observed_total_delta_usd"], -1.0)
        self.assertAlmostEqual(result["total_local_net_6h_usd"], -1.0)
        self.assertAlmostEqual(result["net6h_over_count_ratio"], 1.0)

    def test_zero_equity_snapshots_are_excluded_and_counted(self):
        capital = [
            self.row("2026-01-01T00:00:00+00:00", 100.0),
            self.row("2026-01-01T04:00:00+00:00", 0.0),
            self.row("2026-01-01T06:00:00+00:00", 99.0),
        ]
        result = ne.build_series(capital, [])
        self.assertEqual(result["zero_or_negative_snapshot_count"], 1)
        self.assertEqual(result["n_rows"], 1)

    def test_fails_closed_when_too_few_positive_snapshots(self):
        capital = [self.row("2026-01-01T00:00:00+00:00", 0.0), self.row("2026-01-01T06:00:00+00:00", 0.0)]
        result = ne.build_series(capital, [])
        self.assertFalse(result["valid"])
        self.assertIn("fewer than 2", result["reason"])

    def test_jump_detection_still_works_on_observed_equity(self):
        capital = [
            self.row("2026-01-01T00:00:00+00:00", 100.0),
            self.row("2026-01-01T06:00:00+00:00", 10.0),
        ]
        result = ne.build_series(capital, [])
        self.assertEqual(result["large_observed_jump_count"], 1)


if __name__ == "__main__":
    unittest.main()
