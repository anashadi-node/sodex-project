#!/usr/bin/env python3
"""Resolve unpriced SoDEX holdings: dump spot + perps market symbols (read-only)."""
import json
import urllib.request

BASE = "https://mainnet-gw.sodex.dev/api/v1"
TARGETS = ["aUNITREE", "vsMAG7.ssi", "vsMAG7ssi", "UNITREE", "MAG7"]


def get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "anantara-probe/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


for label, url in (("SPOT", f"{BASE}/spot/markets/tickers"),
                   ("PERPS", f"{BASE}/perps/markets/tickers")):
    try:
        raw = get(url)
    except Exception as exc:
        print(f"{label}: ERROR {type(exc).__name__}: {exc}")
        continue
    rows = raw.get("data") or []
    syms = [str(r.get("symbol")) for r in rows]
    print(f"\n=== {label}: {len(syms)} symbols ===")
    for t in TARGETS:
        hits = [s for s in syms if t.lower() in s.lower()]
        print(f"  match '{t}': {hits}")
    # show the spot symbols that look like index/leveraged tokens
    if label == "SPOT":
        odd = [s for s in syms if s.startswith("a") or ".ssi" in s or "ssi" in s.lower()]
        print("  candidate odd symbols:", odd[:40])
