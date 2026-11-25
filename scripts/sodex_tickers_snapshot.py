#!/usr/bin/env python3
"""Snapshot likuiditas pasar SoDEX -> data/sodex_market_tickers.json (READ-ONLY).

Tujuan: memberi konteks likuiditas pada verdict F3 (lihat
docs/sodex/SODEX_F3_PRAREG_2026-10-06.md §9). Episode dari pasar tipis tidak boleh
dianggap tradeable; tanpa snapshot, evaluator F3 melaporkan status UNKNOWN (fail-closed).

READ-ONLY: hanya GET endpoint publik markets/tickers. Tanpa auth, tanpa jalur order,
tidak menyentuh gate/leverage/sizing/target.

Pakai: python3 scripts/sodex_tickers_snapshot.py
"""
from __future__ import annotations
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/sodex_market_tickers.json"
URL = "https://mainnet-gw.sodex.dev/api/v1/perps/markets/tickers"
HEADERS = {"Accept": "application/json", "User-Agent": "anantara-obi/1.0"}


def fetch(timeout=20):
    req = urllib.request.Request(URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def normalize(raw):
    """Terima beberapa bentuk respons; kembalikan {sym: quoteVolume}. Fail-closed bila kosong."""
    rows = raw.get("data") if isinstance(raw, dict) else raw
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, list):
        return {}
    out = {}
    for m in rows:
        if not isinstance(m, dict):
            continue
        sym = m.get("symbol") or m.get("name") or m.get("market")
        if not sym:
            continue
        vault = m.get("quoteVolume")
        if vault is None:
            vault = m.get("quote_volume")
        try:
            if vault is None:
                continue
            out[sym] = float(vault)
        except (TypeError, ValueError):
            continue
    return out


def main():
    try:
        raw = fetch()
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as e:
        print(f"GAGAL ambil tickers: {type(e).__name__}: {e}")
        print("Snapshot TIDAK ditulis (fail-closed) -> evaluator F3 akan lapor UNKNOWN.")
        return 1
    vols = normalize(raw)
    if not vols:
        print("GAGAL: respons tickers kosong/tidak dikenali -> snapshot TIDAK ditulis.")
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "source": URL, "n_markets": len(vols), "volumes": vols}, indent=1))
    pos = sorted(v for v in vols.values() if v > 0)
    thin = sum(1 for v in vols.values() if v < 10_000)
    print(f"OK: {len(vols)} pasar -> {OUT.relative_to(ROOT)}")
    print(f"  volume 24j < 10.000 USD (tipis): {thin} pasar")
    if pos:
        print(f"  median={pos[len(pos) // 2]:,.0f}  min={pos[0]:,.0f}  max={pos[-1]:,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
