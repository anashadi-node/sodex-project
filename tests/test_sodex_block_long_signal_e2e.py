"""E2E (bukan cuma parsing env): jalankan `run_cycle()` sungguhan dengan sinyal LONG aktif.

Kenapa perlu: env `SW_BLOCK_LONG_SIGNAL` bisa terbaca benar sementara blokirnya tidak
efektif (mis. dipasang di tempat yang salah, atau membunuh track RANDOM juga). Test ini
memanggil jalur entry yang asli dan memeriksa hasilnya:

  - blok ON  → TIDAK ada posisi track SIGNAL, TAPI track RANDOM tetap masuk (kontrol hidup)
  - blok OFF → posisi track SIGNAL muncul seperti biasa (tidak ada regresi)
  - lane riset (TW_INVERT_SIGNAL=1) dengan blok ON → tetap masuk sebagai SHORT
"""
from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))


def _ohlc(n: int = 120, px: float = 100.0) -> dict:
    close = np.array([px + i * 0.01 for i in range(n)])
    return {"close": close, "high": close * 1.01, "low": close * 0.99,
            "volume": np.ones(n)}


SIG = {"active": True, "direction": "LONG", "conviction": 0.8, "reasons": ["test"],
       "atr_pct": 0.01, "regime": "MOMENTUM"}


def _base_state(sw) -> dict:
    st = copy.deepcopy(sw.load_state())
    st["positions"] = []
    st["last_entry"] = {}
    return st


def _prep_swing(monkeypatch, block: bool, tmp_path=None):
    for v in ("SW_BLOCK_LONG_SIGNAL",):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("SW_BLOCK_LONG_SIGNAL", "1" if block else "0")
    import paper_test_swing as sw
    sw = importlib.reload(sw)
    st = _base_state(sw)
    monkeypatch.setattr(sw, "PAIRS", ["BTC"])
    # MAX_POSITIONS=2: supaya cabang SIGNAL dan RANDOM bisa masuk di siklus yang SAMA
    # (di produksi RANDOM dievaluasi lebih dulu dan bisa memakai satu-satunya slot pair).
    monkeypatch.setattr(sw, "MAX_POSITIONS", 2)
    monkeypatch.setattr(sw, "fetch_prices", lambda: {"BTC": 100.0})
    monkeypatch.setattr(sw, "fetch_ohlcv", lambda sym, limit=300: _ohlc())
    monkeypatch.setattr(sw, "check_signal", lambda d, p: dict(SIG))
    monkeypatch.setattr(sw, "direction_gate_blocks", lambda label, d: False)
    monkeypatch.setattr(sw, "_confirm_15m", lambda p, direction="LONG": True)
    monkeypatch.setattr(sw, "btc_regime_ok", lambda *a, **k: True)
    monkeypatch.setattr(sw, "_read_wallet_capital", lambda: 10000.0)
    saved: list = []
    monkeypatch.setattr(sw, "load_state", lambda: copy.deepcopy(st))
    monkeypatch.setattr(sw, "save_state", saved.append)     # state HASIL siklus asli
    # jangan tulis monitor produksi dari test
    from pathlib import Path as _P
    monkeypatch.setattr(sw, "MONITOR_JSON", _P("/tmp/_sodex_test_monitor_swing.json"))
    monkeypatch.setattr(sw, "_RNG", type("R", (), {"random": staticmethod(lambda: 0.0)})())
    sw.run_cycle()
    assert saved, "run_cycle tidak menyimpan state — harness salah"
    return saved[-1]


def test_block_on_no_signal_entry_but_random_still_enters(monkeypatch):
    st = _prep_swing(monkeypatch, block=True)
    tracks = [p["track"] for p in st["positions"]]
    assert "SIGNAL" not in tracks, f"LONG-sinyal masih masuk: {tracks}"
    assert "RANDOM" in tracks, f"kontrol RANDOM ikut mati: {tracks}"


def test_block_off_signal_entry_still_works(monkeypatch):
    st = _prep_swing(monkeypatch, block=False)
    tracks = [p["track"] for p in st["positions"]]
    assert "SIGNAL" in tracks, f"regresi: entry SIGNAL hilang saat blok OFF: {tracks}"


def _prep_twoway(monkeypatch, block: bool, invert: bool):
    monkeypatch.setenv("TW_BLOCK_LONG_SIGNAL", "1" if block else "0")
    monkeypatch.setenv("TW_INVERT_SIGNAL", "1" if invert else "0")
    import paper_test_twoway as tw
    tw = importlib.reload(tw)
    st = copy.deepcopy(tw.load_state())
    st["positions"] = []
    monkeypatch.setattr(tw, "PAIRS", ["BTC"])
    monkeypatch.setattr(tw, "MAX_POSITIONS", 2)
    monkeypatch.setattr(tw, "fetch_prices", lambda: {"BTC": 100.0})
    monkeypatch.setattr(tw, "fetch_ohlcv", lambda sym, limit=300: _ohlc())
    monkeypatch.setattr(tw, "check_signal", lambda d, p="": dict(SIG))
    monkeypatch.setattr(tw, "direction_gate_blocks", lambda label, d: False)
    monkeypatch.setattr(tw, "pair_gate_blocks", lambda label, p: False)
    monkeypatch.setattr(tw, "_confirm_15m", lambda p, direction="LONG": True)
    monkeypatch.setattr(tw, "btc_daily_regime", lambda *a, **k: True)
    monkeypatch.setattr(tw, "btc_momentum_ok", lambda *a, **k: True)
    monkeypatch.setattr(tw, "pre24_pct", lambda p, *a, **k: 99.0)
    monkeypatch.setattr(tw, "_read_wallet_capital", lambda: 10000.0)
    saved: list = []
    monkeypatch.setattr(tw, "load_state", lambda: copy.deepcopy(st))
    monkeypatch.setattr(tw, "save_state", saved.append)
    from pathlib import Path as _P
    for _attr in ("MONITOR_JSON", "LATEST_JSON"):
        if hasattr(tw, _attr):
            monkeypatch.setattr(tw, _attr, _P("/tmp/_sodex_test_monitor_twoway.json"))
    monkeypatch.setattr(tw, "_RNG", type("R", (), {"random": staticmethod(lambda: 0.0)})())
    tw.run_cycle()
    assert saved, "run_cycle tidak menyimpan state — harness salah"
    return saved[-1]


def test_twoway_block_on_no_long_entry(monkeypatch):
    st = _prep_twoway(monkeypatch, block=True, invert=False)
    dirs = [p["direction"] for p in st["positions"] if p.get("track") == "SIGNAL"]
    assert dirs == [], f"masih ada entry LONG-sinyal: {dirs}"


def test_twoway_research_lane_unaffected_when_inverted(monkeypatch):
    """Arah akhir SHORT → blokir tidak boleh menyentuh lane riset 9a/9b/9c."""
    st = _prep_twoway(monkeypatch, block=True, invert=True)
    dirs = [p["direction"] for p in st["positions"] if p.get("track") == "SIGNAL"]
    assert dirs and all(d == "SHORT" for d in dirs), f"lane riset jadi korban: {dirs}"


def test_twoway_block_off_entry_long_as_before(monkeypatch):
    st = _prep_twoway(monkeypatch, block=False, invert=False)
    dirs = [p["direction"] for p in st["positions"] if p.get("track") == "SIGNAL"]
    assert dirs == ["LONG"], f"regresi saat blok OFF: {dirs}"


@pytest.fixture(autouse=True)
def _restore_modules():
    yield
    import paper_test_swing as sw
    import paper_test_twoway as tw
    importlib.reload(sw)
    importlib.reload(tw)
