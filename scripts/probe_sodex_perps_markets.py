#!/usr/bin/env python3
"""Read-only probe of SoDEX perps public market endpoints (no auth, no orders).

Determines whether venue-native perps mark prices are available so the SHORT-BEAR
venue_native_guard variant can use real SoDEX confirmation instead of Binance spot.
"""
import json
import urllib.request

BASE = "https://mainnet-gw.sodex.dev/api/v1/perps"
CANDIDATES = [
    f"{BASE}/markets/tickers",
    f"{BASE}/markets",
    f"{BASE}/tickers",
    f"{BASE}/markets/mark-prices",
]


def probe(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "anantara-probe/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode()
        data = json.loads(body)
        if isinstance(data, dict):
            keys = sorted(data.keys())
            inner = data.get("data")
            shape = type(inner).__name__
            sample = None
            if isinstance(inner, list) and inner:
                sample = inner[0]
            elif isinstance(inner, dict):
                sample = {k: inner[k] for k in list(inner)[:5]}
            return {"ok": True, "keys": keys, "data_type": shape, "sample": sample,
                    "bytes": len(body)}
        return {"ok": True, "type": type(data).__name__, "bytes": len(body)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


for url in CANDIDATES:
    result = probe(url)
    print(f"\n=== {url} ===")
    print(json.dumps(result, indent=1, default=str)[:1200])
