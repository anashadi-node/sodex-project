"""Test guard jalur-kritis T1 SoDEX (scripts/sodex_forward_loop_guard.py).

KONTEKS
-------
Jalur kritis T1 = jendela forward 30 hari dengan margin deadline hanya ~2 hari.
Hari yang hilang TIDAK DAPAT DIGANTI. Guard ini harus:
  - membedakan "loop mati" dari "track memang tak menghasilkan sinyal",
  - TIDAK berbunyi palsu hanya karena skema berkas state antar-track berbeda
    (regresi nyata: `realwide` memakai exit_iso/exit_ts, bukan exit_time),
  - tidak menenggelamkan sinyal dengan spam (cooldown + hanya saat level naik).

Loop normal 3-6 jam (gap maksimum teramati 6,01 jam) -> WARNING di 12 jam,
CRITICAL di 48 jam.
"""
import datetime as dt
import importlib
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

g = importlib.import_module("sodex_forward_loop_guard")

NOW = dt.datetime(2026, 10, 4, 18, 0, tzinfo=dt.timezone.utc)


def jam(n):
    return (NOW - dt.timedelta(hours=n)).isoformat()


class TestParseUtc(unittest.TestCase):
    def test_iso_dengan_z(self):
        self.assertEqual(g.parse_utc("2026-10-04T18:00:00Z"), NOW)

    def test_iso_dengan_offset(self):
        self.assertEqual(g.parse_utc("2026-10-04T18:00:00+00:00"), NOW)

    def test_iso_tanpa_zona_dianggap_utc(self):
        self.assertEqual(g.parse_utc("2026-10-04T18:00:00"), NOW)

    def test_epoch_float(self):
        """realwide menyimpan entry_ts/exit_ts sebagai epoch float."""
        self.assertEqual(g.parse_utc(NOW.timestamp()), NOW)

    def test_epoch_string(self):
        self.assertEqual(g.parse_utc(str(NOW.timestamp())), NOW)

    def test_kosong_dan_sampah(self):
        for v in (None, "", "bukan-waktu", "n/a"):
            self.assertIsNone(g.parse_utc(v), f"{v!r} harus None")


class TestCekLoop(unittest.TestCase):
    def _rows(self, jam_lalu, verdict="T1_FAIL_FORWARD_MONITOR"):
        return [{"generated_utc": jam(jam_lalu), "verdict": verdict}]

    def test_registry_kosong_critical(self):
        self.assertEqual(g.cek_loop([], NOW)["level"], g.LEVEL_CRIT)

    def test_segar_ok(self):
        self.assertEqual(g.cek_loop(self._rows(1.0), NOW)["level"], g.LEVEL_OK)

    def test_ambang_warning_15_jam(self):
        # tepat di bawah ambang -> masih OK
        self.assertEqual(g.cek_loop(self._rows(14.9), NOW)["level"], g.LEVEL_OK)
        self.assertEqual(g.cek_loop(self._rows(15.1), NOW)["level"], g.LEVEL_WARN)

    def test_ambang_critical_48_jam(self):
        self.assertEqual(g.cek_loop(self._rows(47.9), NOW)["level"], g.LEVEL_WARN)
        self.assertEqual(g.cek_loop(self._rows(48.1), NOW)["level"], g.LEVEL_CRIT)

    def test_gap_terpanjang_di_luar_ambang_warning(self):
        """Regresi: gap normal 6,01 jam tidak boleh memicu WARNING."""
        self.assertEqual(g.cek_loop(self._rows(6.01), NOW)["level"], g.LEVEL_OK)

    def test_menghitung_kegagalan_harness_dalam_jendela(self):
        rows = self._rows(1.0) + [
            {"generated_utc": jam(2), "verdict": "FAIL_CLOSED_HARNESS_ERROR"},
            {"generated_utc": jam(3), "verdict": "FAIL_CLOSED_HARNESS_ERROR"},
            {"generated_utc": jam(40), "verdict": "FAIL_CLOSED_HARNESS_ERROR"},  # di luar jendela
        ]
        hasil = g.cek_loop(rows, NOW)
        self.assertEqual(hasil["fails"], 2, "hanya 2 kegagalan dalam 12 jam terakhir")
        self.assertEqual(hasil["level"], g.LEVEL_WARN)

    def test_satu_kegagalan_belum_memicu(self):
        rows = self._rows(1.0) + [
            {"generated_utc": jam(2), "verdict": "FAIL_CLOSED_HARNESS_ERROR"}]
        self.assertEqual(g.cek_loop(rows, NOW)["level"], g.LEVEL_OK)

    def test_kegagalan_tidak_menurunkan_level_critical(self):
        rows = self._rows(60.0) + [
            {"generated_utc": jam(61), "verdict": "FAIL_CLOSED_HARNESS_ERROR"},
            {"generated_utc": jam(62), "verdict": "FAIL_CLOSED_HARNESS_ERROR"}]
        self.assertEqual(g.cek_loop(rows, NOW)["level"], g.LEVEL_CRIT)


class TestCekTrackTrade(unittest.TestCase):
    def test_skema_swing_twoway_exit_time(self):
        rows = [{"exit_time": jam(2)}]
        self.assertEqual(g.cek_track_trade(rows, NOW)["level"], g.LEVEL_OK)

    def test_skema_realwide_exit_iso(self):
        """Regresi: realwide memakai exit_iso -> dulu salah dianggap 'belum ada trade'."""
        rows = [{"exit_iso": jam(2), "exit_ts": NOW.timestamp() - 7200}]
        hasil = g.cek_track_trade(rows, NOW)
        self.assertEqual(hasil["level"], g.LEVEL_OK)
        self.assertNotIn("belum ada", hasil["msg"])

    def test_skema_realwide_epoch_saja(self):
        rows = [{"exit_ts": NOW.timestamp() - 3600}]
        self.assertEqual(g.cek_track_trade(rows, NOW)["level"], g.LEVEL_OK)

    def test_tanpa_stempel_warning_bukan_critical(self):
        """Tak ada trade != loop mati; jangan langsung CRITICAL."""
        hasil = g.cek_track_trade([], NOW)
        self.assertEqual(hasil["level"], g.LEVEL_WARN)
        self.assertIn("belum ada", hasil["msg"])

    def test_mandek_24_jam_warning(self):
        self.assertEqual(g.cek_track_trade([{"exit_time": jam(25)}], NOW)["level"], g.LEVEL_WARN)

    def test_mandek_48_jam_critical(self):
        self.assertEqual(g.cek_track_trade([{"exit_time": jam(50)}], NOW)["level"], g.LEVEL_CRIT)

    def test_memakai_trade_terbaru(self):
        rows = [{"exit_time": jam(100)}, {"exit_time": jam(1)}]
        self.assertEqual(g.cek_track_trade(rows, NOW)["level"], g.LEVEL_OK)


class TestGabungDanAlert(unittest.TestCase):
    def test_gabung_mengambil_level_tertinggi(self):
        self.assertEqual(g.gabung(g.LEVEL_OK, g.LEVEL_CRIT), g.LEVEL_CRIT)
        self.assertEqual(g.gabung(g.LEVEL_WARN, g.LEVEL_OK), g.LEVEL_WARN)
        self.assertEqual(g.gabung(g.LEVEL_OK, g.LEVEL_WARN), g.LEVEL_WARN)

    def test_level_ok_tidak_pernah_alert(self):
        self.assertFalse(g.perlu_alert(g.LEVEL_OK, {}, NOW))

    def test_alert_saat_level_naik(self):
        self.assertTrue(g.perlu_alert(g.LEVEL_WARN, {"last_level": g.LEVEL_OK}, NOW))
        self.assertTrue(g.perlu_alert(g.LEVEL_CRIT,
                                      {"last_level": g.LEVEL_WARN,
                                       "last_alert_utc": jam(1)}, NOW))

    def test_cooldown_menahan_pengulangan(self):
        state = {"last_level": g.LEVEL_WARN, "last_alert_utc": jam(2)}
        self.assertFalse(g.perlu_alert(g.LEVEL_WARN, state, NOW),
                         "level sama & masih dalam cooldown -> jangan spam")

    def test_cooldown_lewat_mengirim_ulang(self):
        state = {"last_level": g.LEVEL_WARN, "last_alert_utc": jam(13)}
        self.assertTrue(g.perlu_alert(g.LEVEL_WARN, state, NOW))


class TestKonfigurasi(unittest.TestCase):
    def test_ambang_sesuai_keputusan(self):
        self.assertEqual(g.WARN_LOOP_HOURS, 15.0)
        self.assertEqual(g.CRIT_LOOP_HOURS, 48.0)
        self.assertLess(g.WARN_LOOP_HOURS, g.CRIT_LOOP_HOURS)

    def test_interval_normal_loop_di_bawah_ambang(self):
        """Loop nyata 3-6 jam; ambang WARNING harus > 2x gap maksimum teramati."""
        self.assertGreater(g.WARN_LOOP_HOURS, 2 * 6.01)

    def test_warning_sisakan_waktu_reaksi_cukup(self):
        """WARNING harus datang jauh sebelum CRITICAL agar ada waktu bertindak."""
        self.assertGreaterEqual(
            g.CRIT_LOOP_HOURS - g.WARN_LOOP_HOURS, 24.0,
            "harus ada >= 24 jam antara WARNING dan CRITICAL")

    def test_pesan_tidak_membocorkan_kredensial(self):
        hasil = {"level": g.LEVEL_WARN,
                 "loop": {"msg": "x", "n": 1, "fails": 0},
                 "funding": {"msg": "y"},
                 "track": {"swing": {"level": g.LEVEL_OK, "msg": "ok"}}}
        pesan = g.susun_pesan(hasil, NOW).lower()
        for kata in ("token", "secret", "api_key", "private"):
            self.assertNotIn(kata, pesan)



class TestCekFunding(unittest.TestCase):
    """Feeder jalur-kritis #2: arsip funding. Kolektor berjalan tiap jam."""

    def _jam_penuh(self, durasi_jam, mundur_dari=0.5):
        """Stempel per jam, lengkap, berakhir `mundur_dari` jam sebelum NOW."""
        akhir = NOW - dt.timedelta(hours=mundur_dari)
        return [akhir - dt.timedelta(hours=i) for i in range(durasi_jam)]

    def test_kosong_critical(self):
        hasil = g.cek_funding([], NOW)
        self.assertEqual(hasil["level"], g.LEVEL_CRIT)
        self.assertIn("KOSONG", hasil["msg"])

    def test_segar_dan_lengkap_ok(self):
        self.assertEqual(g.cek_funding(self._jam_penuh(24), NOW)["level"], g.LEVEL_OK)

    def test_ambang_statis_3_jam(self):
        self.assertEqual(g.cek_funding(self._jam_penuh(24, 2.9), NOW)["level"], g.LEVEL_OK)
        self.assertEqual(g.cek_funding(self._jam_penuh(24, 3.1), NOW)["level"], g.LEVEL_WARN)

    def test_diam_12_jam_critical(self):
        hasil = g.cek_funding(self._jam_penuh(24, 13), NOW)
        self.assertEqual(hasil["level"], g.LEVEL_CRIT)
        self.assertIn("tak terhitung", hasil["msg"])

    def test_bolong_diatas_10_persen_warning(self):
        """Arsip terlihat hidup tapi ada jam hilang -> T1 nanti tak dapat dihitung."""
        stempel = self._jam_penuh(24)
        # buang 5 dari 24 jam (~21%)
        rusak = [t for i, t in enumerate(sorted(stempel)) if i not in (2, 5, 8, 11, 14)]
        hasil = g.cek_funding(rusak, NOW)
        self.assertEqual(hasil["level"], g.LEVEL_WARN)
        self.assertIn("bolong", hasil["msg"])
        self.assertGreater(hasil["missing"], g.FUNDING_MAX_MISSING_RATIO)

    def test_bolong_kecil_masih_ok(self):
        """Toleransi: 1 jam hilang dari 24 (~4%) belum memicu."""
        stempel = sorted(self._jam_penuh(24))
        rusak = [t for i, t in enumerate(stempel) if i != 3]
        self.assertEqual(g.cek_funding(rusak, NOW)["level"], g.LEVEL_OK)

    def test_melaporkan_cakupan(self):
        hasil = g.cek_funding(self._jam_penuh(24), NOW)
        self.assertGreaterEqual(hasil["have"], 24)
        self.assertGreaterEqual(hasil["expected"], hasil["have"] - 1)

    def test_diam_lebih_penting_daripada_bolong(self):
        """Arsip diam lama = CRITICAL, meski cakupan historisnya rapi."""
        self.assertEqual(g.cek_funding(self._jam_penuh(24, 13), NOW)["level"], g.LEVEL_CRIT)


class TestBacaFunding(unittest.TestCase):
    def test_berkas_tidak_ada_mengembalikan_kosong(self):
        self.assertEqual(g.baca_funding(pathlib.Path("/tmp/tidak-ada-xyz.jsonl")), [])

    def test_melewati_baris_rusak(self):
        p = pathlib.Path("/tmp/_uji_funding_guard.jsonl")
        p.write_text(
            '{"collected_utc": "2026-10-04T17:00:00Z"}\n'
            'BUKAN JSON\n'
            '\n'
            '{"collected_utc": "2026-10-04T18:00:00Z"}\n'
            '{"symbol": "SOL"}\n')
        try:
            st = g.baca_funding(p)
            self.assertEqual(len(st), 2)
            self.assertEqual(max(st), NOW)
        finally:
            p.unlink()


class TestGabungDenganFunding(unittest.TestCase):
    def test_funding_critical_mengalahkan_loop_ok(self):
        self.assertEqual(g.gabung(g.LEVEL_OK, g.LEVEL_CRIT), g.LEVEL_CRIT)

    def test_pesan_menyertakan_funding(self):
        hasil = {"level": g.LEVEL_WARN,
                 "loop": {"msg": "loop ok", "n": 1, "fails": 0},
                 "funding": {"msg": "arsip funding diam 5.0 jam"},
                 "track": {"swing": {"level": g.LEVEL_OK, "msg": "ok"}}}
        self.assertIn("arsip funding diam", g.susun_pesan(hasil, NOW))

if __name__ == "__main__":
    unittest.main()
