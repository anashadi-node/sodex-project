#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Macro gate untuk lane paper — DEFENSIF, fail-open, default OFF.

Dasar empiris (2026-11-06, n=3734 trade tertutup dari 6 lane swing):
  - skip entry saat VIX>=20 atau HY spread>=4.2% → gross +22,1pp → +50,2pp
  - skip entry saat window event makro (FOMC/CPI/NFP/GDP, -2h/+1h) → +33,5pp
  Efeknya KECIL (~+0,0075pp/trade) dibanding biaya round-trip 0,12%/trade,
  jadi gate ini bukan penyembuh utama — hanya pengurang kerugian ekor.

Kontrak:
  - `SW_MACRO_GUARD=1` mengaktifkan; default 0 (tidak mengubah lane kontrol).
  - Gagal ambil data macro → FAIL-OPEN (trading lanjut) + alasan dicatat.
  - Cache 30 menit di data/macro_gate_cache.json agar FRED tidak dipanggil
    tiap siklus (lane loop 300s).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "macro_gate_cache.json"
TTL_S = 1800
VIX_BLOCK = 20.0
HY_BLOCK = 4.2


def enabled() -> bool:
    return os.environ.get("SW_MACRO_GUARD", "0").strip().lower() in ("1", "true", "yes", "on")


def _read_cache() -> dict | None:
    try:
        d = json.loads(CACHE.read_text())
        if time.time() - d.get("_ts", 0) <= TTL_S:
            return d
    except Exception:
        pass
    return None


def _hy_spread() -> float | None:
    """HY OAS (%) dari FRED — indikator kredit, pelengkap VIX. Fail-open."""
    try:
        import urllib.request

        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2"
        raw = urllib.request.urlopen(url, timeout=20).read().decode().splitlines()
        for ln in reversed(raw[1:]):
            p = ln.split(",")
            if len(p) == 2 and p[1] not in ("", "."):
                return float(p[1])
    except Exception:
        return None
    return None


def _snapshot() -> dict | None:
    c = _read_cache()
    if c is not None:
        return c
    try:
        from anantara.macro_data import fetch_macro_snapshot_sync

        snap = fetch_macro_snapshot_sync()
        out = dict(snap)
        out["hy_spread"] = _hy_spread()
        out["_ts"] = time.time()
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(out, default=str))
        return out
    except Exception as exc:  # fail-open
        return {"_error": f"{type(exc).__name__}: {exc}", "_ts": time.time()}


def block_reason(direction: str = "LONG", now=None) -> str | None:
    """Return alasan blokir entry baru, atau None bila boleh entry.

    Fail-open: tanpa data → None (boleh entry) + warning di log pemanggil.
    Hanya memblokir LONG saat risk-off; SHORT tidak diblokir (risk-off justru
    lingkungan yang lebih ramah short) supaya gate tidak simetris-buta.
    """
    if not enabled():
        return None
    try:
        from anantara.macro_data import compute_macro_tilt, event_guard_status
    except Exception:
        return None

    ev = event_guard_status(now)
    if ev.get("active"):
        return f"MACRO_EVENT:{ev.get('event')}"

    snap = _snapshot() or {}
    if snap.get("_error"):
        return None
    vix = snap.get("vix_level")
    hy = snap.get("hy_spread")
    try:
        vix = float(vix) if vix is not None else None
    except (TypeError, ValueError):
        vix = None
    try:
        hy = float(hy) if hy is not None else None
    except (TypeError, ValueError):
        hy = None

    tilt = compute_macro_tilt(snap).get("macro_tilt", 0.0)
    is_long = str(direction).upper().startswith("L")
    if is_long and ((vix is not None and vix >= VIX_BLOCK) or (hy is not None and hy >= HY_BLOCK) or tilt <= -0.4):
        return f"MACRO_RISK_OFF:vix={vix},hy={hy},tilt={tilt}"
    return None


if __name__ == "__main__":
    print("enabled:", enabled())
    print("block_reason(LONG):", block_reason("LONG"))
    print("block_reason(SHORT):", block_reason("SHORT"))
