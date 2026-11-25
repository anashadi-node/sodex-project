"""Test gate promosi target SoDEX (REV2 KUMULATIF, docs/sodex/KEPUTUSAN_TARGET_20261102.md §1a).

Kontrak yang diuji:
- Window = 30 hari kalender UTC berturut-turut (144 bucket 5 jam); hari hilang = window tidak sah.
- Gate A: M_kum >= 0,010%/5j. Gate B: MDD window >= -15%.
- Data < 30 hari -> DATA_KURANG (bukan PASS/FAIL).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import TestCase

from scripts import sodex_target_promotion_gate as gate

UTC = timezone.utc
T0 = datetime(2026, 12, 1, 0, 0, tzinfo=UTC)


def _buckets(returns: list[float], start_equity: float = 100.0, t0: datetime = T0):
    """Bangun deret equity per bucket 5 jam dari daftar return fraksi per bucket."""
    rows = []
    equity = start_equity
    for i, ret in enumerate(returns):
        rows.append({"ts": (t0 + timedelta(hours=5 * i)).isoformat(), "equity": equity})
        equity *= 1.0 + ret
    rows.append({"ts": (t0 + timedelta(hours=5 * len(returns))).isoformat(), "equity": equity})
    return rows


class PromotionGateTests(TestCase):
    def test_data_kurang_bila_hari_less_than_30(self):
        # 29 hari = 139 bucket (bukan 144) -> belum cukup
        rows = _buckets([0.000105] * 139)
        res = gate.evaluate_equity(rows)
        self.assertEqual(res["status"], "DATA_KURANG")
        self.assertIn("n_hari", " ".join(res["reasons"]))
        self.assertIsNone(res["m_kum_pct"])

    def test_pass_bila_m_kum_dan_mdd_memenuhi(self):
        rows = _buckets([0.000115] * 144)  # 0,0115%/5j > 0,010%
        res = gate.evaluate_equity(rows)
        self.assertEqual(res["status"], "PASS", res)
        self.assertGreaterEqual(res["m_kum_pct"], 0.010)
        self.assertGreater(res["mdd_pct"], -15.0)

    def test_fail_bila_mdd_breach(self):
        # turun 20% di tengah window (bucket 20-29), lalu pulih sehingga M_kum tetap di atas ambang
        returns = [0.0022] * 20 + [-0.0221] * 10 + [0.0022] * 114
        rows = _buckets(returns)
        res = gate.evaluate_equity(rows)
        self.assertGreaterEqual(res["m_kum_pct"], 0.010, res)
        self.assertLessEqual(res["mdd_pct"], -15.0, res)
        self.assertEqual(res["status"], "FAIL")
        self.assertTrue(any("MDD" in r for r in res["reasons"]))

    def test_data_kurang_bila_ada_hari_hilang(self):
        rows = _buckets([0.000115] * 144)
        # buang seluruh bucket pada hari ke-10 -> window tidak sah
        day10 = T0 + timedelta(days=10)
        rows = [
            r
            for r in rows
            if not (day10 <= datetime.fromisoformat(r["ts"]) < day10 + timedelta(days=1))
        ]
        res = gate.evaluate_equity(rows)
        self.assertEqual(res["status"], "DATA_KURANG", res)

    def test_first_qualifying_window_dilaporkan(self):
        # window pertama lulus, window kedua gagal (drawdown besar di ekor)
        first = [0.000115] * 144
        second = [-0.0300] * 10 + [-0.0001] * 134
        rows = _buckets(first + second)
        res = gate.evaluate_equity(rows)
        self.assertIsNotNone(res["first_qualifying_window"], res)
        self.assertEqual(res["status"], "FAIL")
        self.assertTrue(res["first_qualifying_window"]["start"].startswith("2026-12-01"))

    def test_trade_rows_dipakai_bila_tidak_ada_equity(self):
        rows = []
        for i in range(144):
            rows.append(
                {
                    "ts": (T0 + timedelta(hours=5 * i)).isoformat(),
                    "net_pct": 0.000120,
                }
            )
        res = gate.evaluate_trades(rows)
        self.assertEqual(res["status"], "PASS", res)
        self.assertAlmostEqual(res["m_kum_pct"], 0.0120, places=4)

    def test_tanpa_data_mengembalikan_data_kurang(self):
        self.assertEqual(gate.evaluate_equity([])["status"], "DATA_KURANG")
        self.assertEqual(gate.evaluate_trades([])["status"], "DATA_KURANG")

    def test_cli_menolak_file_tidak_ada(self):
        self.assertEqual(gate.main(["--equity-file", "/tmp/tidak-ada-xyz.jsonl"]), 2)
