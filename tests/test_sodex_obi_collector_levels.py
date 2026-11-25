"""Test kontrak persisted-book collector OBI (L2 mentah).

Konteks: level mentah dibutuhkan untuk riset realisme eksekusi (hftbacktest).
Kalau kontrak ini rusak diam-diam, data L2 hilang tanpa error — jadi harus diuji.
"""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "sodex_obi_collector", ROOT / "scripts" / "sodex_obi_collector.py")
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
sys.modules["sodex_obi_collector"] = mod
spec.loader.exec_module(mod)


class TestRawLevels(unittest.TestCase):
    """raw_levels() = satu-satunya jalur level mentah ke file."""

    # Bentuk asli dari venue: string price/qty, best-first
    VENUE = [["83440", "1.08071"], ["83439", "0.33163"], ["83438", "0.63967"]]

    def test_returns_float_pairs(self):
        """Venue kirim string; kita harus simpan float."""
        out = mod.raw_levels(self.VENUE, 3)
        self.assertEqual(len(out), 3)
        for px, q in out:
            self.assertIsInstance(px, float)
            self.assertIsInstance(q, float)
        self.assertEqual(out[0], [83440.0, 1.08071])

    def test_truncates_to_n(self):
        """n lebih kecil dari jumlah level -> ambil n teratas saja."""
        self.assertEqual(len(mod.raw_levels(self.VENUE, 2)), 2)

    def test_fewer_levels_than_n(self):
        """Venue kirim lebih sedikit dari n -> jangan error, ambil semua."""
        self.assertEqual(len(mod.raw_levels(self.VENUE, 10)), 3)

    def test_order_preserved(self):
        """Best bid harus tetap di indeks 0 (urutan pasar)."""
        out = mod.raw_levels(self.VENUE, 3)
        self.assertEqual([p for p, _ in out], [83440.0, 83439.0, 83438.0])

    def test_empty_input(self):
        """Book kosong -> list kosong, bukan exception."""
        self.assertEqual(mod.raw_levels([], 10), [])

    def test_json_roundtrip_exact(self):
        """Float harus round-trip PERSIS lewat JSON (tidak boleh ada distorsi harga)."""
        out = mod.raw_levels([["0.1739", "1000.5"], ["0.1738", "0.000001"]], 2)
        back = json.loads(json.dumps(out))
        self.assertEqual(back, out)
        self.assertEqual(back[0][0], 0.1739)      # harga tick halus tetap utuh
        self.assertEqual(back[1][1], 0.000001)

    def test_levels_default_positive(self):
        """Konfigurasi LEVELS harus > 0 — kalau 0, L2 tidak pernah terekam."""
        self.assertGreater(mod.LEVELS, 0)


if __name__ == "__main__":
    unittest.main()
