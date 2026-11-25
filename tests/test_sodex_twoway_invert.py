"""A/B 9 — regresi fitur "balik arah sinyal" di lane twoway.

Kenapa ada: lane twoway adalah lane produksi pembelajaran. Fitur pembalik arah
harus (a) DEFAULT OFF, (b) hanya membalik arah yang diperdagangkan — filter/gate
tetap dinilai dari arah sinyal asli, dan (c) geometri TP/SL tidak boleh berubah
kecuali diminta lewat env. Kalau salah satu jebol, lane produksi ikut berubah dan
data A/B jadi tidak bisa diatribusikan.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture()
def tw(monkeypatch):
    for var in ("TW_INVERT_SIGNAL", "TW_TP_PCT", "TW_SL_PCT", "TW_PRE24_MIN"):
        monkeypatch.delenv(var, raising=False)
    import paper_test_twoway as _tw
    return importlib.reload(_tw)


class TestDefaultOff:
    def test_flag_default_off(self, tw):
        assert tw.INVERT_SIGNAL is False

    def test_direction_unchanged_when_off(self, tw):
        assert tw.invert_direction("LONG") == "LONG"
        assert tw.invert_direction("SHORT") == "SHORT"

    def test_geometry_defaults_identical_to_before(self, tw):
        assert tw.TP_PCT == 0.040
        assert tw.SL_PCT == 0.020


class TestPre24Filter:
    """A/B 9c: filter "hanya setup sudah naik". Default OFF + audit nilai tersimpan."""

    def test_default_off(self, tw):
        assert tw.PRE24_MIN is None

    def test_env_sets_threshold(self, monkeypatch):
        monkeypatch.setenv("TW_PRE24_MIN", "3.0")
        import paper_test_twoway as _tw
        assert importlib.reload(_tw).PRE24_MIN == 3.0

    def test_empty_env_is_off(self, monkeypatch):
        monkeypatch.setenv("TW_PRE24_MIN", "")
        import paper_test_twoway as _tw
        assert importlib.reload(_tw).PRE24_MIN is None


class TestPre24Fetch:
    def test_returns_none_when_data_missing(self, tw, monkeypatch):
        monkeypatch.setattr(tw, "_raw_klines", lambda *a, **k: [])
        assert tw.pre24_pct("SOL") is None

    def test_computes_pct_from_klines(self, tw, monkeypatch):
        # 26 bar 1h: bar terakhir 125, 24 jam sebelumnya (indeks -25) = 101
        rows = [[0, 0, 0, 0, str(100.0 + i), 0] for i in range(26)]   # close 100..125
        monkeypatch.setattr(tw, "_raw_klines", lambda *a, **k: rows)
        monkeypatch.setattr(tw, "_PRE24_CACHE", {})
        val = tw.pre24_pct("SOL")
        assert val is not None and 23.0 < val < 24.5      # 125/101 - 1 = 23,76%

    def test_cached_second_call_no_refetch(self, tw, monkeypatch):
        calls = {"n": 0}

        def fake(*a, **k):
            calls["n"] += 1
            return [[0, 0, 0, 0, str(100.0 + i), 0] for i in range(26)]

        monkeypatch.setattr(tw, "_raw_klines", fake)
        monkeypatch.setattr(tw, "_PRE24_CACHE", {})
        tw.pre24_pct("SOL")
        tw.pre24_pct("SOL")
        assert calls["n"] == 1


class TestInversion:
    def test_mirrors_both_ways(self, tw):
        assert tw.invert_direction("LONG", True) == "SHORT"
        assert tw.invert_direction("SHORT", True) == "LONG"

    def test_env_turns_it_on(self, monkeypatch):
        monkeypatch.setenv("TW_INVERT_SIGNAL", "1")
        import paper_test_twoway as _tw
        tw2 = importlib.reload(_tw)
        assert tw2.INVERT_SIGNAL is True
        assert tw2.invert_direction("LONG") == "SHORT"

    def test_geometry_override_only_when_asked(self, monkeypatch):
        monkeypatch.setenv("TW_TP_PCT", "0.015")
        monkeypatch.setenv("TW_SL_PCT", "0.06")
        import paper_test_twoway as _tw
        tw2 = importlib.reload(_tw)
        assert tw2.TP_PCT == 0.015
        assert tw2.SL_PCT == 0.06


@pytest.fixture(autouse=True)
def _restore_module():
    """Reload bersih setelah tiap test supaya env test tidak bocor ke lane lain."""
    yield
    import paper_test_twoway as _tw
    importlib.reload(_tw)
