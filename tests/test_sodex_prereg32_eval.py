"""Test fail-closed evaluator PRAREG-32 (maker-donchian Binance USDM).

Yang dijaga: (1) protokol & pool immutability, (2) verdict GAGAL_DATA selama forward
belum berjalan, (3) mesin benar-benar menghasilkan trade+window (bukan pemindai mati),
(4) invarian agregasi equal-weight (cap-weighted tidak boleh dipakai untuk A).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root, portabel
EVAL = os.path.join(ROOT, "scripts/research/prereg32_maker_eval.py")
POOL = os.path.join(ROOT, "reports/sodex/PRAREG32_POOL.json")
PROTO = os.path.join(ROOT, "reports/sodex/PRAREG32_MAKER_PROTOCOL.json")
REG = os.path.join(ROOT, "reports/sodex/PRAREG31_REGISTRY.jsonl")
PROTO_SHA = "3d44c04df2ffd17ee26bd50237add1465703bddc44e3b79508d5539eec99dc24"
# Uji yang memanggil evaluate() butuh data klines lokal; data/* tidak dibundel di repo publik.
KLINES = os.path.join(ROOT, "data/binance_klines/1h/BTCUSDT.json")
needs_klines = pytest.mark.skipif(not os.path.exists(KLINES), reason="butuh data klines lokal (data/* tidak dibundel)")


def _mod():
    spec = importlib.util.spec_from_file_location("p32_eval", EVAL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def test_protokol_beku_hash_cocok_registry():
    assert _sha(PROTO) == PROTO_SHA
    reg = [json.loads(l) for l in open(REG) if l.strip()]
    f = [r for r in reg if r.get("prereg") == "PRAREG-32" and r.get("event") == "FROZEN"]
    assert f and f[-1]["sha256"] == PROTO_SHA
    assert f[-1]["forward_start"] == "2026-10-27T00:00:00Z"
    assert f[-1]["min_windows"] == 24


def test_pool_immutable_dan_20_simbol():
    rec = json.load(open(POOL))
    syms = rec["symbols"]
    assert len(syms) == 20 and len(set(syms)) == 20
    assert hashlib.sha256(json.dumps(syms).encode()).hexdigest() == rec["sha256_symbols"]
    assert _mod().load_or_freeze_pool() == syms


@needs_klines
def test_verdict_gagal_data_sebelum_forward(monkeypatch):
    m = _mod()
    out = m.evaluate()
    assert out["status"] == "GAGAL_DATA"          # fail-closed: data kurang != lolos
    assert out["n_usable"] < m.MIN_WINDOWS


@needs_klines
def test_mesin_menghasilkan_trade_dan_window_in_sample():
    m = _mod()
    m.FREEZE = datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()
    m.FWD_START = datetime(2026, 8, 3, tzinfo=timezone.utc).timestamp()
    m.FWD_END = datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp()
    out = m.evaluate()
    assert out["n_signal_total"] > 0
    assert out["fill"]["n_fill"] > 0, "pemindai mati: tidak ada fill"
    assert out["n_usable"] > 0 and out["n_window_total"] >= out["n_usable"]
    # window pertama persis di jangkar grid 30 jam
    w0 = min(out["windows"], key=lambda w: w["k"])
    assert w0["start_utc"] == "2026-08-03T00:00:00+00:00"
    # A = equal-weight: rata-rata 20 simbol (simbol tanpa trade = 0,0%)
    assert len(w0["per_simbol"]) == 20
    ew = sum(w0["per_simbol"].values()) / 20
    assert abs(ew - w0["pct_EW"]) < 1e-3          # toleransi pembulatan 4 desimal
    # cap-weighted dilaporkan terpisah dan HARUS berbeda dari EW pada window ini
    assert w0["pct_capweighted_terlarang"] != w0["pct_EW"]
    json.dumps(out)                                # serialisasi penuh tanpa error


@needs_klines
def test_fill_rate_fail_closed_konsisten():
    m = _mod()
    m.FREEZE = datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()
    m.FWD_START = datetime(2026, 8, 3, tzinfo=timezone.utc).timestamp()
    m.FWD_END = datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp()
    out = m.evaluate()
    f = out["fill"]
    assert f["n_fill"] + f["n_unfilled"] == f["n_req"]
    if f["n_req"]:
        assert abs(f["fill_rate"] - f["n_fill"] / f["n_req"]) < 1e-3


def test_gate_D_ketat_dan_tidak_vacuous():
    m = _mod()
    assert m.AS_GATE_BPS == 13.4 and m.FILL_OK == 0.60          # ambang tidak dilonggarkan
    assert m.gate_D(0.99, -20.0, -20.0) is True                  # fill baik, AS rendah
    assert m.gate_D(0.99, 13.5, -20.0) is False                  # AS touch di atas ambang
    assert m.gate_D(0.99, -20.0, 13.5) is False                  # AS literal di atas ambang
    assert m.gate_D(0.59, -20.0, -20.0) is False                 # fill di bawah 60%
    assert m.gate_D(0.99, None, -20.0) is False                  # AS tak terukur -> gagal (fail-closed)


@needs_klines
def test_as_dilaporkan_per_simbol_dan_dua_definisi():
    m = _mod()
    m.FREEZE = datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()
    m.FWD_START = datetime(2026, 8, 3, tzinfo=timezone.utc).timestamp()
    m.FWD_END = datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp()
    out = m.evaluate()
    asd = out["adverse_selection_bps"]
    assert set(asd["per_simbol"]) == set(out["pool"]["symbols"])
    for s, v in asd["per_simbol"].items():
        assert set(v) == {"n", "median_fill_minus_signal_bps", "median_touch_bps"}
    for t in out["trades"]:
        # as_touch>0 = adverse (bar penuhi limit TUTUP di bawah fill); <0 = tidak adverse
        assert (t["as_touch_close_bps"] > 0) == (t["close_bar_fill"] < t["limit"])
        # limit MAKER selalu di bawah harga sinyal (LONG) -> AS-literal selalu negatif
        assert t["limit"] < t["p_sig"] and t["as_protocol_bps"] < 0
    # status fail-closed & alasan selalu ada
    assert out["status"] in ("GAGAL_DATA", "GAGAL (kriteria gagal)", "GAGAL (kill-switch DD)", "TIDAK LOLOS", "LOLOS")
    assert out["alasan_verdict"]
