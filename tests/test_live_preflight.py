"""Test preflight live: verdict fail-closed, ekskalasi level menurut fase,
dan tidak pernah membaca isi rahasia."""
from __future__ import annotations

import json
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from scripts import sodex_live_preflight as pf


def chk(name, ok, level="BLOCKER", detail=""):
    return {"nama": name, "ok": ok, "level": level, "detail": detail}


class PhaseTests(TestCase):
    def test_fase_persiapan_sebelum_25_nov(self):
        self.assertEqual(pf.phase(date(2026, 11, 2)), "PERSIAPAN")

    def test_fase_beku_25_sampai_30_nov(self):
        self.assertEqual(pf.phase(date(2026, 11, 25)), "BEKU")
        self.assertEqual(pf.phase(date(2026, 11, 30)), "BEKU")

    def test_fase_live_mulai_1_des(self):
        self.assertEqual(pf.phase(date(2026, 12, 1)), "LIVE")


class VerdictTests(TestCase):
    def test_semua_hijau_siap(self):
        v = pf.verdict([chk("a", True), chk("b", True, "WARN")])
        self.assertEqual(v["status"], "SIAP")
        self.assertEqual(v["blocker"], 0)

    def test_satu_blocker_belum_siap_dan_namanya_disebut(self):
        v = pf.verdict([chk("arm", True), chk("env", False, detail="hilang")])
        self.assertEqual(v["status"], "BELUM_SIAP")
        self.assertEqual(v["blocker"], 1)
        self.assertIn("env", v["blocker_nama"])

    def test_warn_saja_tetap_siap(self):
        v = pf.verdict([chk("klines", False, "WARN")])
        self.assertEqual(v["status"], "SIAP")
        self.assertEqual(v["warn"], 1)


class ReconciliationTests(TestCase):
    def _write(self, path, status="OK", age=0, critical=None):
        path.write_text(json.dumps({
            "ts": (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat(),
            "status": status,
            "critical": critical or [],
            "max_age_sec": 600,
        }))

    def test_missing_is_blocker(self):
        with patch.object(pf, "WATCHDOG_STATUS", Path("/sodex-test-no-status")):
            self.assertFalse(pf.check_reconciliation()["ok"])

    def test_fresh_ok_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            self._write(path)
            with patch.object(pf, "WATCHDOG_STATUS", path):
                self.assertTrue(pf.check_reconciliation()["ok"])

    def test_stale_ok_is_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            self._write(path, age=601)
            with patch.object(pf, "WATCHDOG_STATUS", path):
                self.assertFalse(pf.check_reconciliation()["ok"])

    def test_critical_is_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            self._write(path, status="CRITICAL", critical=[{"msg": "posisi tak terlacak"}])
            with patch.object(pf, "WATCHDOG_STATUS", path):
                self.assertFalse(pf.check_reconciliation()["ok"])


class PromotionGateTests(TestCase):
    def test_no_promotion_gate_blocks_live(self):
        result = Mock(returncode=3, stdout="")
        with patch.object(pf.subprocess, "run", return_value=result):
            check = pf.check_promo_gate()
        self.assertFalse(check["ok"])
        self.assertEqual(check["level"], "BLOCKER")


class EscalationTests(TestCase):
    def test_deadman_warn_saat_persiapan_naik_jadi_blocker_saat_beku(self):
        self.assertEqual(pf.escalate("WARN", "PERSIAPAN", "BEKU"), "WARN")
        self.assertEqual(pf.escalate("WARN", "BEKU", "BEKU"), "BLOCKER")
        self.assertEqual(pf.escalate("BLOCKER", "BEKU", "PERSIAPAN"), "BLOCKER")


class EnvGateTests(TestCase):
    """Gerbang kredensial harus selaras dengan loader engine dan TIDAK bisa
    ditipu file kosong."""

    def _tulis(self, isi: str, mode: int = 0o600) -> Path:
        d = Path(self.enterContext(tempfile.TemporaryDirectory()))
        p = d / ".env"
        p.write_text(isi)
        p.chmod(mode)
        return p

    def _cek(self, *paths: Path) -> dict:
        with patch.object(pf, "ENV_CANDIDATES", tuple(paths)):
            return pf.check_env()

    def test_fallback_dotenv_dengan_tiga_kunci_lulus(self):
        p = self._tulis("SODEX_PRIVATE_KEY=x\nSODEX_ACCOUNT_ID=1\nSODEX_ADDRESS=0xabc\n")
        c = self._cek(Path("/nonexistent/secrets/sodex.env"), p)
        self.assertTrue(c["ok"], c["detail"])
        self.assertNotIn("0xabc", c["detail"])            # nilai tidak boleh bocor

    def test_file_kosong_tidak_lulus(self):
        p = self._tulis("")
        self.assertFalse(self._cek(p)["ok"])

    def test_kunci_kurang_satu_tidak_lulus_dan_disebut(self):
        p = self._tulis("SODEX_PRIVATE_KEY=x\nSODEX_ACCOUNT_ID=1\n")
        c = self._cek(p)
        self.assertFalse(c["ok"])
        self.assertIn("SODEX_ADDRESS", c["detail"])

    def test_mode_terbuka_tidak_lulus(self):
        p = self._tulis("SODEX_PRIVATE_KEY=x\nSODEX_ACCOUNT_ID=1\nSODEX_ADDRESS=0xabc\n", mode=0o644)
        self.assertFalse(self._cek(p)["ok"])

    def test_tanpa_berkas_sama_sekali_tetap_blocker(self):
        c = self._cek(Path("/nonexistent/a"), Path("/nonexistent/b"))
        self.assertFalse(c["ok"])
        self.assertEqual(c["level"], "BLOCKER")
