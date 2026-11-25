#!/usr/bin/env python3
"""Read-only SoDEX market ticker scanner.

Continuously snapshots SoDEX spot/perps tickers so operators can see current
liquidity, spreads, movers, and zero-book markets without granting order power.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT / "data" / "sodex_market_scan"
LATEST = OUT_DIR / "latest.json"
HISTORY = OUT_DIR / "history.jsonl"


def dec(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def run_json(args: list[str], timeout: int = 45) -> Any:
    proc = subprocess.run(
        args,
        cwd=PROJECT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"command_failed:{args[:4]}:rc={proc.returncode}:{proc.stderr[-300:]}")
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "result", "tickers"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def normalize(row: dict[str, Any], market: str) -> dict[str, Any] | None:
    symbol = str(row.get("symbol") or "")
    bid = dec(row.get("bidPx"))
    ask = dec(row.get("askPx"))
    last = dec(row.get("lastPx"))
    quote_volume = dec(row.get("quoteVolume"))
    change_pct = dec(row.get("changePct"))
    funding = dec(row.get("fundingRate")) if market == "perps" else Decimal("0")
    zero_book = bid <= 0 or ask <= 0
    mid = (bid + ask) / Decimal("2") if bid > 0 and ask > 0 else last
    spread_bps = ((ask - bid) / mid * Decimal("10000")) if mid > 0 and ask > bid else Decimal("0")
    if not symbol:
        return None
    return {
        "market": market,
        "symbol": symbol,
        "last": float(last),
        "bid": float(bid),
        "ask": float(ask),
        "mid": float(mid),
        "spread_bps": float(spread_bps),
        "quote_volume_usd": float(quote_volume),
        "change_pct": float(change_pct),
        "funding_rate": float(funding),
        "zero_book": zero_book,
    }


def rank(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    live = [item for item in items if not item["zero_book"]]
    liquid = sorted(live, key=lambda x: x["quote_volume_usd"], reverse=True)
    losers = sorted(live, key=lambda x: x["change_pct"])
    gainers = sorted(live, key=lambda x: x["change_pct"], reverse=True)
    tight = sorted(
        [item for item in live if item["quote_volume_usd"] >= 75_000],
        key=lambda x: (x["spread_bps"], -x["quote_volume_usd"]),
    )
    short_watch = sorted(
        [
            item for item in live
            if item["market"] == "perps"
            and item["change_pct"] <= -1.0
            and item["quote_volume_usd"] >= 75_000
            and item["spread_bps"] <= 12.0
        ],
        key=lambda x: (abs(x["change_pct"]), x["quote_volume_usd"], -x["spread_bps"]),
        reverse=True,
    )
    return {
        "top_liquid": liquid[:20],
        "top_losers": losers[:20],
        "top_gainers": gainers[:20],
        "tight_liquid": tight[:20],
        "short_watch": short_watch[:20],
        "zero_book": [item for item in items if item["zero_book"]][:50],
    }


def snapshot() -> dict[str, Any]:
    perps = [normalize(row, "perps") for row in rows(run_json(["bin/sodex", "tickers", "perps", "--format", "json"]))]
    spot = [normalize(row, "spot") for row in rows(run_json(["bin/sodex", "tickers", "spot", "--format", "json"]))]
    items = [item for item in perps + spot if item]
    perps_items = [item for item in items if item["market"] == "perps"]
    spot_items = [item for item in items if item["market"] == "spot"]
    now = datetime.now(timezone.utc).isoformat()
    return {
        "ts": now,
        "mode": "READ_ONLY_SODEX_MARKET_TICKER_SCAN",
        "policy": "no orders, no cancels, no signed trade endpoint",
        "counts": {
            "total": len(items),
            "perps": len(perps_items),
            "spot": len(spot_items),
            "zero_book": sum(1 for item in items if item["zero_book"]),
        },
        "rankings": rank(items),
        "items": items,
    }


def persist(payload: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LATEST.with_name(f".{LATEST.name}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(LATEST)
    summary = {
        "ts": payload["ts"],
        "counts": payload["counts"],
        "top_losers": payload["rankings"]["top_losers"][:5],
        "top_gainers": payload["rankings"]["top_gainers"][:5],
        "short_watch": payload["rankings"]["short_watch"][:8],
    }
    with HISTORY.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only SoDEX market ticker scanner")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=float, default=15.0)
    args = parser.parse_args(argv)
    while True:
        try:
            payload = snapshot()
            persist(payload)
            print(json.dumps({"ts": payload["ts"], "counts": payload["counts"], "short_watch": payload["rankings"]["short_watch"][:3]}, sort_keys=True))
        except Exception as exc:
            print(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "error": str(exc)[:300]}, sort_keys=True))
        if not args.loop:
            return 0
        time.sleep(max(5.0, float(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
