"""Regresi trailing exit A/B 8b (SW_TRAIL_TRIGGER_R / SW_TRAIL_R).

Dasar: replay varian `trail1r` (exit geometry 2026-11-06) memberi +0,055..+0,074pp
tetapi p=0,14–0,43 → fitur ini WAJIB default OFF supaya lane produksi tidak berubah,
dan keputusan menyala/mati hanya lewat env di lane riset terisolasi.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))   # modul script (cost_model, dst.) tinggal di scripts/

import paper_test_swing as sw  # noqa: E402


class TestTrailDecision:
    def test_off_by_default(self):
        assert sw.SW_TRAIL_TRIGGER_R == 0.0
        assert sw.trail_decision(peak=0.03, gross=0.01, sl=0.01) is False

    def test_not_armed_before_trigger(self):
        # puncak +0,8R (< 1R) lalu mundur banyak → belum boleh keluar
        assert sw.trail_decision(peak=0.008, gross=-0.005, sl=0.01,
                                 trigger_r=1.0, trail_r=1.0) is False

    def test_fires_when_retraced_from_peak(self):
        # puncak +1,0% (1R) lalu mundur ke 0,0% (jarak 1R) → keluar
        assert sw.trail_decision(peak=0.010, gross=0.000, sl=0.01,
                                 trigger_r=1.0, trail_r=1.0) is True

    def test_held_while_still_near_peak(self):
        assert sw.trail_decision(peak=0.020, gross=0.018, sl=0.01,
                                 trigger_r=1.0, trail_r=1.0) is False

    def test_boundary_peak_exactly_trigger_is_armed(self):
        assert sw.trail_decision(peak=0.010, gross=0.000, sl=0.010,
                                 trigger_r=1.0, trail_r=1.0) is True

    def test_trail_distance_scales_with_sl(self):
        # sl=2% → 1R = 2%, puncak 2% dan mundur ke 1% (jarak 1%) belum kena trail 1R
        assert sw.trail_decision(peak=0.020, gross=0.010, sl=0.02,
                                 trigger_r=1.0, trail_r=1.0) is False
        assert sw.trail_decision(peak=0.020, gross=0.000, sl=0.02,
                                 trigger_r=1.0, trail_r=1.0) is True


class TestEnvWiring:
    def test_env_enables_feature(self, monkeypatch):
        monkeypatch.setenv("SW_TRAIL_TRIGGER_R", "1.0")
        monkeypatch.setenv("SW_TRAIL_R", "1.0")
        mod = importlib.reload(sw)
        try:
            assert mod.SW_TRAIL_TRIGGER_R == 1.0
            assert mod.trail_decision(peak=0.012, gross=0.001, sl=0.01) is True
        finally:
            monkeypatch.delenv("SW_TRAIL_TRIGGER_R", raising=False)
            monkeypatch.delenv("SW_TRAIL_R", raising=False)
            importlib.reload(sw)

    def test_trail_reason_uses_market_fill_not_level(self):
        # TRAIL = exit pasar (poll), bukan order level rest di venue
        px = sw.sw_fill_for("TRAIL", entry_p=100.0, tp=0.025, sl=0.01, px=101.5)
        assert px == 101.5
