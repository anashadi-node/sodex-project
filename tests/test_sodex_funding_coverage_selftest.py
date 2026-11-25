"""A2 self-test: buktikan pipeline funding mapper mencapai coverage>0 ketika
data NYATA tersedia, dan TETAP fail-closed ketika tidak.

Latar (2026-10-04): build_mapping() melaporkan coverage 0,0% untuk 42 SHORT trade
twoway. Akar = MISMATCH TEMPORAL, bukan bug: trade berada di Agu/Sep, sedangkan
arsip rate venue SoDEX baru mulai 2-Okt (collector tiap 5 menit). Proxy
Hyperliquid/Binance sudah DIUJI dan DITOLAK (median r=0,193) sehingga tidak dipakai.

Test ini memakai arsip rate NYATA (`funding_rates_history.jsonl`) dan trade
SYNTHETIC yang jendelanya sengaja dibuat berada di dalam cakupan arsip.
Trade synthetic TIDAK pernah masuk ke verdict produksi.
"""
import datetime as dt
import importlib.util
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location(
    "sodex_funding_mapper", ROOT / "scripts" / "sodex_funding_mapper.py")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

RATE_HISTORY = ROOT / "data/sodex_funding/funding_rates_history.jsonl"
TWOWAY = ROOT / "data/paper_test_twoway_state.json"


def usable_rows(rate_history):
    """Baris arsip yang lolos penjaga look-ahead (collected <= ts)."""
    return [r for r in rate_history if r.get("collected") and r["collected"] <= r["ts"]]


class TestCoverageSelfTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not RATE_HISTORY.exists():
            raise unittest.SkipTest("arsip rate tidak ada")
        cls.rate_history = m.load_rate_history(RATE_HISTORY)
        cls.usable = usable_rows(cls.rate_history)
        if len(cls.usable) < 5:
            raise unittest.SkipTest("arsip rate belum cukup baris")
        # simbol dengan baris usable terbanyak
        counts = {}
        for r in cls.usable:
            counts[r["symbol"]] = counts.get(r["symbol"], 0) + 1
        cls.symbol, cls.n = max(counts.items(), key=lambda kv: kv[1])
        rs = sorted(r["ts"] for r in cls.usable if r["symbol"] == cls.symbol)
        cls.t0, cls.t1 = rs[0], rs[-1]
        # basis trade dari baris NYATA agar skema pasti kompatibel
        rows = m.closed_rows(TWOWAY)
        cls.base = next((r for r in rows if m.trade_side(r) == "SHORT"), None)
        if cls.base is None:
            raise unittest.SkipTest("tidak ada baris SHORT nyata sebagai basis")

    def _trade(self, pair, entry, exit_, notional=1000.0):
        row = dict(self.base)
        row["pair"] = pair
        row["direction"] = "SHORT"
        row["entry_time"] = entry
        row["exit_time"] = exit_
        row["notional"] = notional
        row.pop("funding", None)
        row.pop("borrow", None)
        return row

    def test_pipeline_mencapai_coverage_positif_dgn_rate_nyata(self):
        """INTI A2: bila jendela trade berada di cakupan arsip -> coverage > 0."""
        row = self._trade(self.symbol + "-USD", self.t0.isoformat(), self.t1.isoformat())
        out = m.map_trade(row, [], rates={}, rate_history=self.rate_history)
        self.assertEqual(out["status"], "OK_RATE_ARCHIVE_ESTIMATED",
                         "pipeline gagal memetakan walau arsip mencakup jendelanya")
        self.assertGreater(out["rate_records"], 0)
        self.assertIsNotNone(out["funding_usd"])
        self.assertTrue(abs(out["funding_usd"]) < 1e6, "nilai funding tidak wajar")

    def test_shorth_membayar_bila_rate_positif(self):
        """Tanda ekonomi: SHORT membayar funding saat rate positif."""
        row = self._trade(self.symbol + "-USD", self.t0.isoformat(), self.t1.isoformat())
        out = m.map_trade(row, [], rates={}, rate_history=self.rate_history)
        pos = [r for r in self.usable
               if r["symbol"] == self.symbol and self.t0 <= r["ts"] <= self.t1 and r["funding_rate"] > 0]
        if pos and out["funding_usd"] is not None:
            self.assertGreater(out["funding_usd"], 0)

    def test_fail_closed_di_luar_cakupan_arsip(self):
        """KONTROL: jendela Agu (di luar arsip) HARUS MISSING, bukan ditebak."""
        row = self._trade(self.symbol + "-USD",
                          "2026-08-06T14:00:00+00:00", "2026-08-07T13:52:00+00:00")
        out = m.map_trade(row, [], rates={}, rate_history=self.rate_history)
        self.assertEqual(out["status"], "MISSING_FUNDING_EVIDENCE")
        self.assertIsNone(out["funding_usd"])

    def test_fail_closed_tanpa_notional(self):
        """KONTROL: tanpa notional, estimasi tidak boleh dikarang."""
        row = self._trade(self.symbol + "-USD", self.t0.isoformat(), self.t1.isoformat())
        for k in ("notional", "position_notional", "stake_amount", "trade_notional",
                  "qty", "quantity", "size", "position_size"):
            row.pop(k, None)
        row["pnl_pct"] = 0
        out = m.map_trade(row, [], rates={}, rate_history=self.rate_history)
        self.assertEqual(out["status"], "MISSING_FUNDING_EVIDENCE")
        self.assertIsNone(out["funding_usd"])

    def test_penjaga_lookahead_menolak_rate_belum_terkumpul(self):
        """Penjaga look-ahead: data identik, hanya `collected` digeser ke masa depan
        -> hasil HARUS berbalik dari OK_RATE_ARCHIVE_ESTIMATED ke MISSING.

        Ini uji falsifikasi: kalau hasilnya tetap OK, penjaga look-ahead bocor dan
        estimasi funding memakai informasi yang belum ada saat trade berjalan.
        """
        rows = [r for r in self.rate_history if r["symbol"] == self.symbol]
        if not rows:
            self.skipTest("tidak ada baris untuk simbol ini")
        row = self._trade(self.symbol + "-USD", self.t0.isoformat(), self.t1.isoformat())

        bersih = [dict(r) for r in rows if r["collected"] <= r["ts"]]
        self.assertTrue(bersih, "prasyarat: harus ada baris yang lolos penjaga")
        self.assertEqual(
            m.map_trade(row, [], rates={}, rate_history=bersih)["status"],
            "OK_RATE_ARCHIVE_ESTIMATED")

        # data SAMA, hanya collected digeser ke setelah funding_time-nya
        teracuni = [dict(r, collected=r["ts"] + dt.timedelta(hours=1)) for r in rows]
        out = m.map_trade(row, [], rates={}, rate_history=teracuni)
        self.assertEqual(out["status"], "MISSING_FUNDING_EVIDENCE",
                         "penjaga look-ahead BOCOR: estimasi memakai data masa depan")
        self.assertIsNone(out["funding_usd"])


if __name__ == "__main__":
    unittest.main()
