#!/usr/bin/env python3
"""SoDEX public-API history probe (READ-ONLY).

Menjawab: interval apa yang didukung, dan seberapa jauh ke belakang tiap interval
bisa dipaginasi (endTime). Output: JSON ringkas ke stdout + /tmp/sodex_probe.json.

Endpoint: GET {B}/markets/{symbol}/klines?interval=&limit=&startTime=&endTime=
Envelope: {"code":0,"timestamp":ms,"data":[{t,o,h,l,c,v,q,n}, ...]}  (data DESC = terbaru dulu)
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

B = "https://mainnet-gw.sodex.dev/api/v1/perps"
UA = {"User-Agent": "anantara-research/1.0 (read-only)"}
DAY_MS = 86_400_000


def get(url: str, tries: int = 3, pause: float = 1.0):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                return {"_err": str(e)[:120]}
            time.sleep(pause * (i + 1))
    return {"_err": "unreachable"}


def bars(url: str):
    """Return list of dicts ([] on error) from the klines envelope."""
    d = get(url)
    if not isinstance(d, dict):
        return []
    data = d.get("data")
    return data if isinstance(data, list) else []


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def probe_intervals(symbol: str = "BTC-USD"):
    out = {}
    for iv in ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"):
        b = bars(f"{B}/markets/{symbol}/klines?interval={iv}&limit=5")
        out[iv] = {"n": len(b), "newest": iso(b[0]["t"]) if b else None,
                   "oldest_in_page": iso(b[-1]["t"]) if b else None}
        time.sleep(0.15)
    return out


def probe_paging(symbol: str = "BTC-USD", interval: str = "1h", days=(45, 60, 100, 150, 200, 250, 300, 360, 400)):
    now = int(time.time() * 1000)
    out = []
    for d in days:
        e = now - d * DAY_MS
        b = bars(f"{B}/markets/{symbol}/klines?interval={interval}&limit=1000&endTime={e}")
        out.append({"endTime_days_ago": d, "n": len(b),
                    "oldest": iso(b[-1]["t"]) if b else None,
                    "newest": iso(b[0]["t"]) if b else None})
        time.sleep(0.15)
    return out


def probe_earliest(symbol: str = "BTC-USD", interval: str = "1h"):
    """Binary-search oldest bar reachable at this interval."""
    now = int(time.time() * 1000)
    lo, hi = 0, 420  # days ago
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        b = bars(f"{B}/markets/{symbol}/klines?interval={interval}&limit=1000&endTime={now - mid * DAY_MS}")
        if b:
            best = min(b[-1]["t"], best) if best else b[-1]["t"]
            lo = mid + 1  # data exists this far back -> try older
        else:
            hi = mid - 1
        time.sleep(0.12)
    return {"interval": interval, "days_back_with_data": hi if not best else None,
            "oldest_reachable": iso(best) if best else None, "oldest_ms": best}


if __name__ == "__main__":
    res = {
        "probed_utc": datetime.now(timezone.utc).isoformat(),
        "intervals_btc": probe_intervals("BTC-USD"),
        "paging_1h_btc": probe_paging("BTC-USD", "1h"),
        "earliest_1h_btc": probe_earliest("BTC-USD", "1h"),
        "earliest_5m_btc": probe_earliest("BTC-USD", "5m"),
    }
    print(json.dumps(res, indent=1))
    with open("/tmp/sodex_probe.json", "w") as f:
        json.dump(res, f, indent=1)
