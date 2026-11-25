"""Regresi: planner tidak boleh MATI karena 429 dari venue.

Kejadian nyata 2026-11-07 03:46 WIB: `sodex-window-planner.service` exit 1 hanya
karena satu HTTP 429. 429 = "pelan sedikit", bukan kegagalan permanen. Yang WAJIB
tetap fail-closed: error non-retryable (mis. 401/404) harus langsung raise, dan
kalau semua percobaan habis, exception tetap naik (jangan mengembalikan kosong
seolah sukses — itu akan membuat plan palsu).
"""
from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sodex_window_planner as wp  # noqa: E402


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ok(payload):
    return _Resp(json.dumps(payload).encode())


def _err(code):
    return urllib.error.HTTPError("https://x", code, "boom", {}, None)


def test_retries_through_429(monkeypatch):
    calls = {"n": 0, "slept": []}

    def fake(req, timeout=20):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise _err(429)
        return _ok({"data": [{"symbol": "vAVAX_vUSDC"}]})

    monkeypatch.setattr(wp.urllib.request, "urlopen", fake)
    out = wp.api("/spot/markets/tickers", _sleep=lambda s: calls["slept"].append(s))
    assert out["data"][0]["symbol"] == "vAVAX_vUSDC"
    assert calls["n"] == 3
    assert len(calls["slept"]) == 2
    assert calls["slept"][1] > calls["slept"][0]          # backoff naik


def test_fail_closed_after_all_attempts(monkeypatch):
    def fake(req, timeout=20):
        raise _err(429)

    monkeypatch.setattr(wp.urllib.request, "urlopen", fake)
    with pytest.raises(urllib.error.HTTPError):
        wp.api("/spot/markets/tickers", attempts=3, _sleep=lambda s: None)


def test_non_retryable_raises_immediately(monkeypatch):
    calls = {"n": 0}

    def fake(req, timeout=20):
        calls["n"] += 1
        raise _err(404)

    monkeypatch.setattr(wp.urllib.request, "urlopen", fake)
    with pytest.raises(urllib.error.HTTPError):
        wp.api("/spot/markets/tickers", _sleep=lambda s: None)
    assert calls["n"] == 1                                 # tidak mengulang 404
