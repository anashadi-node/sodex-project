#!/usr/bin/env python3
"""
ANANTARA SAKTI — Whale positioning signal (Hyperliquid on-chain transparency).

HL is fully on-chain: any address's open positions are public via clearinghouseState.
This aggregates the NET directional positioning of a curated set of large/known
addresses into a per-coin bias signal — the strongest empirically-supported signal
found in research (following ≥$50M whales showed high win-rate, WITH heavy caveats:
only ~10% of short-sellers profit; never blind-copy → use as ONE confirming input).

Honest discipline (per blueprint): this is a SIGNAL, not gospel. Like every other
signal it must be logged and validated (hit-rate) before being trusted. The whale
ADDRESS LIST must be curated/maintained by the user (env ANANTARA_WHALE_ADDRS, comma
-separated) — a stale list = a stale signal. No addresses → graceful NEUTRAL.

Pure aggregation (tested); the network fetch is isolated.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

HL_API = "https://api.hyperliquid.xyz/info"

# Min net |notional| (USD) across whales for a coin to count as a directional bias.
MIN_NET_USD = 250_000
# Min share of gross positioning that must be one-sided for conviction.
MIN_ONESIDED = 0.60


@dataclass
class WhaleBias:
    coin: str
    net_usd: float        # signed: + = net long, - = net short
    gross_usd: float
    longs: int
    shorts: int
    bias: str             # LONG | SHORT | NEUTRAL
    conviction: float     # 0..1 (one-sided share, scaled)


def aggregate_bias(positions_by_addr: dict[str, list[dict]]) -> dict[str, WhaleBias]:
    """Aggregate per-coin net whale positioning (pure).

    positions_by_addr: {address: [{coin, szi(signed size), price}]}. Returns
    {coin: WhaleBias}. `szi`>0 long, <0 short; notional = |szi|*price.
    """
    acc: dict[str, dict] = {}
    for _addr, positions in positions_by_addr.items():
        for p in positions:
            coin = p.get("coin")
            # Use try/except for float conversion: p.get("szi") could return "" (empty
            # string from API), and float("") raises ValueError before `or 0` can apply.
            try:
                szi   = float(p.get("szi")   or 0)
                price = float(p.get("price") or 0)
            except (TypeError, ValueError):
                continue
            if not coin or szi == 0 or price <= 0:
                continue
            notional = abs(szi) * price
            a = acc.setdefault(coin, {"net": 0.0, "gross": 0.0, "longs": 0, "shorts": 0})
            if szi > 0:
                a["net"] += notional; a["longs"] += 1
            else:
                a["net"] -= notional; a["shorts"] += 1
            a["gross"] += notional

    out: dict[str, WhaleBias] = {}
    for coin, a in acc.items():
        net, gross = a["net"], a["gross"]
        onesided = abs(net) / gross if gross > 0 else 0.0
        if abs(net) >= MIN_NET_USD and onesided >= MIN_ONESIDED:
            bias = "LONG" if net > 0 else "SHORT"
        else:
            bias = "NEUTRAL"
        out[coin] = WhaleBias(coin, round(net, 2), round(gross, 2),
                              a["longs"], a["shorts"], bias, round(onesided, 3))
    return out


def confirms(bias_map: dict[str, WhaleBias], coin: str, direction: str) -> int:
    """+1 if whales confirm the signal direction, -1 if they oppose it, 0 if neutral/none."""
    wb = bias_map.get(coin)
    if not wb or wb.bias == "NEUTRAL":
        return 0
    return 1 if wb.bias == direction.upper() else -1


# ── IO boundary (not unit-tested) ─────────────────────────────────────────────
def whale_addresses() -> list[str]:
    """Curated whale address list from env ANANTARA_WHALE_ADDRS (comma-separated).
    Returns [] if unset — the signal then degrades gracefully to NEUTRAL."""
    raw = os.environ.get("ANANTARA_WHALE_ADDRS", "").strip()
    return [a.strip() for a in raw.split(",") if a.strip().startswith("0x")]


# ─────────────────────────────────────────────────────────────────────────────
# SMART-WHALE AUTO-DISCOVERY (audit 2026-09-07) — fixes whale_tilt dead signal
# when ANANTARA_WHALE_ADDRS is unset. Selection is PERFORMANCE-BASED, not
# fame-based: research showed famous whales (James Wynn) blew up while quiet
# consistent traders profited. From the public HL leaderboard we select
# accounts that are profitable in EVERY window (day+week+month+allTime PnL>0)
# with size (accountValue >= $10M) and real liquidity (month volume >= $100M).
# Pure selector — unit-testable; HTTP is in the caller (fetch_leaderboard).
# ─────────────────────────────────────────────────────────────────────────────
LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
MIN_ACCOUNT_VALUE_USD = 10_000_000
MIN_MONTH_VOLUME_USD   = 100_000_000
SMART_WHALE_CAP        = 25   # positions fetch cost: 1 API call per address/hour


def _window(r: dict, name: str) -> dict:
    for w in r.get("windowPerformances", []):
        if w and w[0] == name and isinstance(w[1], dict):
            return w[1]
    return {}


def select_smart_whales(rows: list[dict] | None,
                        min_value: float = MIN_ACCOUNT_VALUE_USD,
                        min_month_vlm: float = MIN_MONTH_VOLUME_USD,
                        cap: int = SMART_WHALE_CAP) -> list[dict]:
    """Pure: leaderboard rows → consistently-profitable smart-whale list.

    Criteria (anti one-shot-luck): PnL > 0 in day, week, month AND allTime;
    week ROI > 0 (recent edge, not only a stale month); accountValue >=
    min_value; month volume >= min_month_vlm. Sorted by month PnL desc.
    """
    out: list[dict] = []
    for r in rows or []:
        d_, w_, m_, a_ = (_window(r, k) for k in ("day", "week", "month", "allTime"))
        if not (d_ and w_ and m_ and a_):
            continue
        pnl = [float(x.get("pnl", 0) or 0) for x in (d_, w_, m_, a_)]
        if any(p <= 0 for p in pnl):
            continue
        if float(w_.get("roi", 0) or 0) <= 0:
            continue
        if float(r.get("accountValue", 0) or 0) < min_value:
            continue
        if float(m_.get("vlm", 0) or 0) < min_month_vlm:
            continue
        out.append({"eth": r.get("ethAddress", ""), "pnl_month": pnl[2],
                    "roi_week": float(w_.get("roi", 0) or 0),
                    "account_value": float(r.get("accountValue", 0) or 0)})
    out.sort(key=lambda c: -c["pnl_month"])
    return out[:cap]


def fetch_leaderboard_rows() -> list[dict]:
    """Fetch public HL leaderboard rows (IO boundary — not unit-tested)."""
    import httpx
    r = httpx.get(LEADERBOARD_URL, timeout=30)
    r.raise_for_status()
    return (r.json() or {}).get("leaderboardRows", []) or []


def smart_whale_addresses(rows: list[dict] | None = None) -> list[str]:
    """Resolved smart-whale address list (env ANANTARA_WHALE_ADDRS wins if set).

    Auto-discovers from the leaderboard when the env is unset — the fix for
    the dead whale_tilt signal. Falls back to [] on any fetch error.
    """
    env = whale_addresses()
    if env:
        return env
    try:
        rows = rows if rows is not None else fetch_leaderboard_rows()
        return [c["eth"] for c in select_smart_whales(rows)]
    except Exception:
        return []


def fetch_positions(addr: str) -> list[dict]:
    """Open positions for one address (public clearinghouseState)."""
    import httpx
    r = httpx.post(HL_API, json={"type": "clearinghouseState", "user": addr}, timeout=12).json()
    out = []
    for ap in (r.get("assetPositions") or []):
        p = ap.get("position", {})
        try:
            szi = float(p.get("szi") or 0)
            pv  = float(p.get("positionValue") or 0)
        except (TypeError, ValueError):
            continue
        if szi == 0:
            continue
        price = pv / abs(szi) if szi else 0.0
        out.append({"coin": p.get("coin"), "szi": szi, "price": price})
    return out


def fetch_whale_bias(addresses: list[str] | None = None) -> dict[str, WhaleBias]:
    """Live whale bias map from the curated address list (graceful empty → {})."""
    import time
    addrs = addresses if addresses is not None else whale_addresses()
    by_addr = {}
    for a in addrs:
        try:
            by_addr[a] = fetch_positions(a)
            time.sleep(0.1)
        except Exception:
            by_addr[a] = []
    return aggregate_bias(by_addr)


if __name__ == "__main__":
    addrs = whale_addresses()
    if not addrs:
        print("ANANTARA_WHALE_ADDRS belum di-set (env, comma-separated 0x...). "
              "Whale signal NEUTRAL sampai daftar whale dikurasi.")
    else:
        bm = fetch_whale_bias(addrs)
        print(f"Whale bias dari {len(addrs)} address:")
        for coin, wb in sorted(bm.items(), key=lambda x: -abs(x[1].net_usd))[:15]:
            if wb.bias != "NEUTRAL":
                print(f"  {coin:<8} {wb.bias:<5} net=${wb.net_usd:,.0f} "
                      f"conv={wb.conviction} (L{wb.longs}/S{wb.shorts})")
