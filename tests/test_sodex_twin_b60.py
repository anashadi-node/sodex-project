"""Test B60 (29-Sep-2026) — perbaikan 3 bug engine churn yang menyebabkan −$15,04/24 jam.

Bug yang diuji:
  A. restart storm: watchdog menganggap "no-fill" (normal bagi maker) sebagai hang
     pada ambang 90s → kill → engine SIGTERM membatalkan semua order (138×/24 jam).
  B. FLUSH inventori memakai post-only pada harga stale → ditolak (oid=0) → inventori
     menumpuk satu sisi (kasus nyata: 1.108.000 vSHIB macet 631 menit).
  C. retry oid=0 memakai cooldown TETAP 5s → 12 retry/menit/sisi berjam-jam.

Jalankan: python -m pytest tests/test_sodex_twin_b60.py -q
"""
import json
import re
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock

from anantara import sodex_twin_engine as twin

REPO = Path(__file__).resolve().parents[1]


class TestOid0BackoffLadder(TestCase):
    """Bug C: backoff harus tumbuh (bukan tetap 5s) dan berujung karantina."""

    def test_ladder_naik_bertahap(self):
        self.assertEqual(twin.oid0_backoff_s(0), 5)      # normal
        self.assertEqual(twin.oid0_backoff_s(1), 5)
        self.assertEqual(twin.oid0_backoff_s(2), 30)     # 2 reject beruntun
        self.assertEqual(twin.oid0_backoff_s(3), 30)
        self.assertEqual(twin.oid0_backoff_s(4), 180)
        self.assertEqual(twin.oid0_backoff_s(5), 180)
        self.assertEqual(twin.oid0_backoff_s(6), 600)
        self.assertEqual(twin.oid0_backoff_s(9), 600)

    def test_karantina_pada_streak_10(self):
        self.assertEqual(twin.oid0_backoff_s(10), 1800)  # sisi dikarantina 30 menit
        self.assertEqual(twin.oid0_backoff_s(50), 1800)

    def test_monoton_dan_dibatasi(self):
        vals = [twin.oid0_backoff_s(s) for s in range(0, 40)]
        self.assertEqual(vals, sorted(vals), "backoff tidak boleh turun saat streak naik")
        self.assertLessEqual(max(vals), 1800, "backoff tidak boleh melebihi karantina")

    def test_bukan_lagi_cooldown_tetap_5s(self):
        """Regresi: streak ≥2 tidak boleh kembali ke 5s (akar 12 retry/menit)."""
        for s in range(2, 40):
            self.assertGreater(twin.oid0_backoff_s(s), 5)


class TestFlushEscalation(TestCase):
    """Bug B: flush yang ditolak post-only WAJIB dieskalasi, bukan ditinggal (inventori menginap)."""

    @staticmethod
    def _engine(post_only_oid, market_oid):
        e = object.__new__(twin.Engine1Flywheel)      # bypass __init__ (butuh cfg/adapter penuh)
        e.pair = "PEPE/USDC"
        e.inv_qty = twin.D("1000")
        e.buy_q = MagicMock()
        e._inv_started = 1
        e._flushing = False
        e.orders = []
        e.tg = MagicMock()
        e.x = MagicMock()
        e.x.balance.return_value = {"vPEPE": twin.D("1000")}
        e.x.place_post_only.return_value = MagicMock(oid=post_only_oid)
        e.x.place_market_ioc.return_value = MagicMock(oid=market_oid)
        bk = MagicMock()
        bk.ask, bk.bid, bk.mid = twin.D("0.00000567"), twin.D("0.00000566"), twin.D("0.000005665")
        return e, bk

    def test_post_only_ditolak_tidak_meninggalkan_inventori(self):
        e, bk = self._engine("0", "777")
        e._force_flush_now(bk)
        e.x.place_post_only.assert_called_once()
        e.x.place_market_ioc.assert_called_once()          # eskalasi terjadi
        self.assertTrue(e._flushing, "flush order harus ditandai aktif")
        self.assertEqual(len(e.orders), 1, "order eskalasi harus dilacak")
        self.assertEqual(e.orders[0].oid, "777")

    def test_kedua_jalur_gagal_tidak_crash_dan_alert(self):
        e, bk = self._engine("0", "0")
        e._force_flush_now(bk)                              # tidak boleh raise
        self.assertEqual(e.orders, [], "tidak ada order yang dilacak jika keduanya gagal")
        self.assertTrue(e.tg.send.called, "operator harus diberi tahu")
        msg = " ".join(str(c.args[0]) for c in e.tg.send.call_args_list)
        self.assertIn("GAGAL", msg.upper())

    def test_post_only_sukses_tidak_eskalasi(self):
        """Jalan bahagia: biaya maker tetap murah, jangan eskalasi tanpa alasan."""
        e, bk = self._engine("555", "777")
        e._force_flush_now(bk)
        e.x.place_market_ioc.assert_not_called()
        self.assertEqual(e.orders[0].oid, "555")


class TestWatchdogThreshold(TestCase):
    """Bug A: ambang 'hang' 90s → 900s (regresi akan mengembalikan restart storm)."""

    def test_ambang_900_dan_bukan_90(self):
        src = (REPO / "scripts" / "watchdog_twin.sh").read_text(encoding="utf-8")
        self.assertIn('-lt 900', src, "ambang heartbeat harus 900s")
        # '-lt 90' adalah substring '-lt 900' → cek ambang 90s sebagai token utuh (diikuti non-digit)
        self.assertIsNone(re.search(r"-lt 90(?![0-9])", src),
                          "ambang 90s = akar restart storm, tidak boleh kembali")

    def test_sinyal_proteksi_modal_tetap_selalu_dihormati(self):
        """pnl-emergency/deadman tidak boleh terkena penundaan 900s."""
        src = (REPO / "scripts" / "watchdog_twin.sh").read_text(encoding="utf-8")
        self.assertIn("pnl-emergency", src)
        self.assertIn("deadman", src)
        # blok case hanya membungkus tipe kondisi-pasar, bukan proteksi modal
        self.assertIsNotNone(re.search(r"monitor-eval-repair\|stuck-idle\|zero-fill\|stuck-rt\)", src))


class TestSafetyHaltHygiene(TestCase):
    """Fail-closed halt marker (audit 29-Sep-2026).

    Sebelum perbaikan: `write_safety_halt` hanya DIDEFINISIKAN tanpa pemanggil →
    hard-stop (drawdown/loss harian) tak pernah menghasilkan data/SAFETY_HALT =
    fail-OPEN di rantai safety (watchdog & komponen lain menggate pada file itu).
    """

    def test_hard_stop_menulis_penanda(self):
        src = (REPO / "anantara" / "sodex_twin_engine.py").read_text(encoding="utf-8")
        self.assertIn("write_safety_halt(str(e))", src,
                      "hard-stop harus menulis penanda SAFETY_HALT")
        self.assertIn('"source": "sodex_twin_engine"', src)

    def test_tidak_menimpa_penanda_yang_sudah_ada(self):
        """Alasan pertama (drawdown) harus utuh — penanda turunan tak boleh menimpanya."""
        with tempfile.TemporaryDirectory() as tmp:
            halt = Path(tmp) / "SAFETY_HALT"
            halt.write_text('{"reason":"drawdown"}', encoding="utf-8")
            orig = twin.SAFETY_HALT_FILE
            twin.SAFETY_HALT_FILE = halt
            try:
                twin.write_safety_halt("live_start_blocked:SAFETY_HALT_ACTIVE:drawdown")
                self.assertEqual(halt.read_text(encoding="utf-8"), '{"reason":"drawdown"}')
            finally:
                twin.SAFETY_HALT_FILE = orig

    def test_menulis_bila_belum_ada_tanpa_kredensial(self):
        with tempfile.TemporaryDirectory() as tmp:
            halt = Path(tmp) / "SAFETY_HALT"
            orig = twin.SAFETY_HALT_FILE
            twin.SAFETY_HALT_FILE = halt
            try:
                twin.write_safety_halt("g4_drawdown", drawdown_frac=0.16)
                payload = json.loads(halt.read_text(encoding="utf-8"))
                self.assertEqual(payload["reason"], "g4_drawdown")
                self.assertEqual(payload["source"], "sodex_twin_engine")
                self.assertAlmostEqual(payload["drawdown_frac"], 0.16)
                self.assertFalse([k for k in payload
                                  if "key" in k.lower() or "secret" in k.lower()
                                  or "token" in k.lower()],
                                 "penanda tidak boleh memuat kredensial")
            finally:
                twin.SAFETY_HALT_FILE = orig
