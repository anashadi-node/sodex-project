"""Regresi: kredensial sodex harus terbaca dari secrets/sodex.env ATAU fallback .env root.

Latar: equity snapshot 5 jam sempat "sukses" tanpa menulis ledger karena hanya menerima
secrets/sodex.env, sementara kredensial ada di .env root -> deadman buta ekuitas.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MOD = REPO / "scripts/research/mode_a_20261026/mode_a_live.py"

KEYS = {
    "SODEX_PRIVATE_KEY": "0x" + "ab" * 32,
    "SODEX_ACCOUNT_ID": "12345",
    "SODEX_ADDRESS": "0x" + "cd" * 20,
}


def _load():
    import sys
    d = str(MOD.parent)
    if d not in sys.path:  # mode_a_live mengimpor mode_a_engine/spot_exec dari direktorinya
        sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location("mode_a_live_envtest", MOD)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _write(path: Path, extra: dict | None = None) -> None:
    body = {**KEYS, **(extra or {})}
    path.write_text("".join(f"{k}={v}\n" for k, v in body.items()))
    os.chmod(path, 0o600)


def test_fallback_root_env(tmp_path, monkeypatch):
    """secrets/sodex.env tidak ada -> pakai .env root (mode 600)."""
    m = _load()
    root_env = tmp_path / ".env"
    _write(root_env)
    monkeypatch.setattr(m, "ENV_FILE", str(tmp_path / "secrets" / "sodex.env"))
    monkeypatch.setattr(m, "ENV_FALLBACK", str(root_env))
    env = m.load_env()
    assert env["SODEX_ADDRESS"] == KEYS["SODEX_ADDRESS"]
    assert env["SODEX_ACCOUNT_ID"] == KEYS["SODEX_ACCOUNT_ID"]


def test_primary_wins(tmp_path, monkeypatch):
    """Kedua file ada -> secrets/sodex.env yang dipakai."""
    m = _load()
    sec = tmp_path / "secrets" / "sodex.env"
    sec.parent.mkdir(parents=True)
    _write(sec, {"SODEX_ACCOUNT_ID": "999"})
    root_env = tmp_path / ".env"
    _write(root_env)
    monkeypatch.setattr(m, "ENV_FILE", str(sec))
    monkeypatch.setattr(m, "ENV_FALLBACK", str(root_env))
    assert m.load_env()["SODEX_ACCOUNT_ID"] == "999"


def test_mode_600_enforced(tmp_path, monkeypatch):
    """File longgar (0644) tidak boleh dipakai."""
    m = _load()
    root_env = tmp_path / ".env"
    _write(root_env)
    os.chmod(root_env, 0o644)
    monkeypatch.setattr(m, "ENV_FILE", str(tmp_path / "secrets" / "sodex.env"))
    monkeypatch.setattr(m, "ENV_FALLBACK", str(root_env))
    with pytest.raises(m.Block):
        m.load_env()


def test_missing_file_fails_closed(tmp_path, monkeypatch):
    """Tidak ada file kredensial -> Block (bukan dict kosong)."""
    m = _load()
    monkeypatch.setattr(m, "ENV_FILE", str(tmp_path / "a.env"))
    monkeypatch.setattr(m, "ENV_FALLBACK", str(tmp_path / "b.env"))
    with pytest.raises(m.Block):
        m.load_env()
