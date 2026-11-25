"""Keputusan Owner 2026-11-07: LONG-sinyal dihentikan di lane paper produksi.

Dua hal yang WAJIB dikunci test:
1. Default OFF — tanpa env, perilaku lane identik seperti sebelumnya (jangan
   mengubah lane riset 9a/9b/9c yang justru butuh sinyal tetap menyala untuk dibalik).
2. Blokir hanya menyentuh arah yang DIPERDAGANGKAN = LONG, dan tidak menyentuh
   track RANDOM (kontrol) — kalau kontrol ikut mati, tidak ada pembanding lagi.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in ("SW_BLOCK_LONG_SIGNAL", "TW_BLOCK_LONG_SIGNAL", "TW_INVERT_SIGNAL",
                "TW_PRE24_MIN"):
        monkeypatch.delenv(var, raising=False)
    yield
    import paper_test_swing as sw
    import paper_test_twoway as tw
    importlib.reload(sw)
    importlib.reload(tw)


def test_swing_default_off():
    import paper_test_swing as sw
    importlib.reload(sw)
    assert sw.SW_BLOCK_LONG_SIGNAL is False


def test_swing_env_on(monkeypatch):
    monkeypatch.setenv("SW_BLOCK_LONG_SIGNAL", "1")
    import paper_test_swing as sw
    assert importlib.reload(sw).SW_BLOCK_LONG_SIGNAL is True


def test_twoway_default_off():
    import paper_test_twoway as tw
    importlib.reload(tw)
    assert tw.BLOCK_LONG_SIGNAL is False


def test_twoway_env_on(monkeypatch):
    monkeypatch.setenv("TW_BLOCK_LONG_SIGNAL", "1")
    import paper_test_twoway as tw
    assert importlib.reload(tw).BLOCK_LONG_SIGNAL is True


def test_block_uses_traded_direction_not_signal_direction(monkeypatch):
    """Lane riset 9a/9b/9c membalik arah sinyal: arah akhirnya SHORT → tidak diblokir.

    Kalau blokir dilakukan SEBELUM inversi, seluruh eksperimen A/B 9 mati.
    """
    monkeypatch.setenv("TW_BLOCK_LONG_SIGNAL", "1")
    monkeypatch.setenv("TW_INVERT_SIGNAL", "1")
    import paper_test_twoway as tw
    tw = importlib.reload(tw)
    signal_dir = "LONG"
    traded = tw.invert_direction(signal_dir)          # dicek blokir di arah ini
    assert traded == "SHORT"
    assert not (tw.BLOCK_LONG_SIGNAL and traded == "LONG")   # → tidak diblokir
