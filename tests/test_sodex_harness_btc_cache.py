"""Test self-healing cache BTC 1h pada sodex_harness_reeval.

KONTEKS (2026-10-03, terukur di registry loop forward)
------------------------------------------------------
Harness butuh harga BTC 1h untuk beta-netralisasi. Versi lama hanya membaca cache
TERBARU dan menuntut cache itu menutup SELURUH jendela; bila cache tertinggal
beberapa jam -> `FileNotFoundError: no BTC 1h cache covers requested window`.
Terjadi 2x dalam 26 run loop (plus 1x DNS URLError), = 11,5% kegagalan. Dengan
margin deadline ~2 hari, kegagalan berulang bisa melewati 03-Nov.

Lebih buruk: TIDAK ADA kode yang menulis cache itu -- hanya dibaca. Sekali
tertinggal, ia tertinggal selamanya.

PERBAIKAN
---------
1. `merge_cached_candles()` -- cakupan efektif = GABUNGAN semua cache, bukan irisan.
2. `persist_btc_cache()` -- cache rolling ditulis HANYA setelah fetch jaringan
   sukses, sehingga gangguan DNS berikutnya masih punya cadangan segar.
3. `fetch_btc_1h()` memanggil persist pada jalur sukses.

Fail-closed TIDAK dilemahkan: bila BTC benar-benar tak tersedia, harness tetap
gagal seperti sebelumnya.
"""
import datetime as dt
import json
import pathlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sodex_harness_reeval as reeval  # noqa: E402


def tulis_cache(folder: Path, nama: str, rows: list[list]) -> Path:
    p = folder / nama
    p.write_text(json.dumps({"rows": rows}))
    return p


class TestMergeCache(unittest.TestCase):
    def test_gabungan_union_dari_beberapa_cache(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            tulis_cache(d, "btc_1h_binance_spot_cache_a.json", [[1000, "", "", "", "10.0"]])
            tulis_cache(d, "btc_1h_binance_spot_cache_b.json", [[2000, "", "", "", "20.0"]])
            old = reeval.REPORT_DIR
            reeval.REPORT_DIR = d
            try:
                m = reeval.merge_cached_candles()
            finally:
                reeval.REPORT_DIR = old
        self.assertEqual(m, {1000: 10.0, 2000: 20.0})

    def test_baris_rusak_diabaikan_bukan_melempar(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "btc_1h_binance_spot_cache_x.json").write_text("{ rusak")
            tulis_cache(d, "btc_1h_binance_spot_cache_y.json",
                        [[1000, "", "", "", "10.0"], [7], [2000, "a", "b", "c", "bukan-angka"]])
            old = reeval.REPORT_DIR
            reeval.REPORT_DIR = d
            try:
                m = reeval.merge_cached_candles()
            finally:
                reeval.REPORT_DIR = old
        self.assertEqual(m, {1000: 10.0})


class TestCakupanGabungan(unittest.TestCase):
    """REGRESI INTI: gabungan menutup jendela walau tiap berkas TIDAK."""

    def test_gabungan_menutup_jendela_yang_tiap_berkas_tidak(self):
        start = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
        end = dt.datetime(2026, 10, 4, tzinfo=dt.timezone.utc)
        sms = int(start.timestamp() * 1000)
        ems = int(end.timestamp() * 1000)
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            # dua berkas, masing-masing setengah jendela -> tidak ada yg menutup penuh
            tulis_cache(d, "btc_1h_binance_spot_cache_1.json", [[sms, "", "", "", "100.0"]])
            tulis_cache(d, "btc_1h_binance_spot_cache_2.json", [[ems, "", "", "", "110.0"]])
            old = reeval.REPORT_DIR
            reeval.REPORT_DIR = d
            try:
                candles = reeval.load_btc_1h_cache(start, end)
            finally:
                reeval.REPORT_DIR = old
        self.assertEqual(candles, [(sms, 100.0), (ems, 110.0)],
                         "gabungan dua cache harus dianggap menutup jendela")

    def test_tetap_fail_closed_bila_gabungan_pun_tidak_menutup(self):
        start = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
        end = dt.datetime(2026, 10, 20, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            tulis_cache(d, "btc_1h_binance_spot_cache_1.json",
                        [[int(start.timestamp() * 1000), "", "", "", "100.0"]])
            old = reeval.REPORT_DIR
            reeval.REPORT_DIR = d
            try:
                with self.assertRaises(FileNotFoundError):
                    reeval.load_btc_1h_cache(start, end)
            finally:
                reeval.REPORT_DIR = old
        # fail-closed dipertahankan: data BTC yang benar-benar tak ada tetap gagal


class TestPersistRoundTrip(unittest.TestCase):
    def test_persist_lalu_muat_kembali(self):
        start = dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)
        end = dt.datetime(2026, 9, 2, tzinfo=dt.timezone.utc)
        sms, ems = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            old = reeval.REPORT_DIR
            reeval.REPORT_DIR = d
            try:
                p = reeval.persist_btc_cache([(sms, 50.0), (ems, 55.0)])
                self.assertIsNotNone(p)
                self.assertTrue(p.exists())
                self.assertEqual(p.name, reeval.ROLLING_CACHE_NAME)
                candles = reeval.load_btc_1h_cache(start, end)
            finally:
                reeval.REPORT_DIR = old
        self.assertEqual(candles, [(sms, 50.0), (ems, 55.0)])

    def test_persist_menggabung_dgn_cache_lama(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            tulis_cache(d, "btc_1h_binance_spot_cache_lama.json",
                        [[1000, "", "", "", "10.0"]])
            old = reeval.REPORT_DIR
            reeval.REPORT_DIR = d
            try:
                reeval.persist_btc_cache([(2000, 20.0)])
                m = reeval.merge_cached_candles()
            finally:
                reeval.REPORT_DIR = old
        self.assertEqual(m, {1000: 10.0, 2000: 20.0}, "cache lama harus ikut terbawa")

    def test_persist_daftar_kosong_tidak_menulis(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            old = reeval.REPORT_DIR
            reeval.REPORT_DIR = d
            try:
                self.assertIsNone(reeval.persist_btc_cache([]))
                self.assertFalse((d / reeval.ROLLING_CACHE_NAME).exists())
            finally:
                reeval.REPORT_DIR = old


class TestFetchMemperbaruiCache(unittest.TestCase):
    def test_fetch_sukses_menulis_cache_rolling(self):
        start = dt.datetime.fromtimestamp(1000, tz=dt.timezone.utc)
        end = dt.datetime.fromtimestamp(8200, tz=dt.timezone.utc)
        batch = [[1000_000, "", "", "", "100.0"], [8200_000, "", "", "", "102.0"]]

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(batch).encode()

        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            old_dir, old_url = reeval.REPORT_DIR, reeval.urllib.request.urlopen
            reeval.REPORT_DIR = d
            reeval.urllib.request.urlopen = lambda *a, **k: _Resp()
            try:
                candles = reeval.fetch_btc_1h(start, end)
                rolling = d / reeval.ROLLING_CACHE_NAME
                self.assertTrue(rolling.exists(), "fetch sukses harus menulis cache")
                tertulis = json.loads(rolling.read_text())
            finally:
                reeval.urllib.request.urlopen = old_url
                reeval.REPORT_DIR = old_dir
        self.assertIn(candles, ([], [(1000_000, 100.0), (8200_000, 102.0)]))
        self.assertTrue(tertulis.get("rows"))


if __name__ == "__main__":
    unittest.main()
