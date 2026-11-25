#!/usr/bin/env python3
"""Record public SoDEX trades for queue/fill research; no auth and no order path."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT / "data" / "sodex_public_trades.db"
BASE_URL = "https://mainnet-gw.sodex.dev/api/v1/perps"
DEFAULT_PAIRS = (
    "CRCL-USD,MSTR-USD,MU-USD,AMD-USD,HOOD-USD,INTC-USD,"
    "COIN-USD,SKHY-USD,PLTR-USD,SPCX-USD,ZEC-USD,XAUT-USD"
)


def normalize_trade(symbol: str, row: dict) -> tuple | None:
    try:
        trade_id = str(row.get("t") or row.get("id") or row.get("tradeId") or "")
        ts_ms = float(row.get("T") or row.get("ts") or row.get("timestamp") or 0)
        price = float(row.get("p") or row.get("price") or 0)
        qty = float(row.get("q") or row.get("v") or row.get("qty") or 0)
        side = str(row.get("S") or row.get("side") or "").upper()
    except (TypeError, ValueError):
        return None
    if not trade_id or ts_ms <= 0 or price <= 0 or qty <= 0 or side not in {"BUY", "SELL"}:
        return None
    ts = ts_ms / 1000 if ts_ms > 10_000_000_000 else ts_ms
    return symbol, trade_id, ts, side, price, qty


def fetch_trades(symbol: str, limit: int = 100, timeout: float = 8.0) -> list[dict]:
    path = f"/markets/{urllib.parse.quote(symbol, safe='-')}/trades?limit={limit}"
    request = urllib.request.Request(
        BASE_URL + path,
        headers={"Accept": "application/json", "User-Agent": "anantara-queue-research/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    rows = payload.get("data", []) if isinstance(payload, dict) else payload
    return rows if isinstance(rows, list) else []


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS trades("
               "symbol TEXT, trade_id TEXT, ts REAL, side TEXT, price REAL, qty REAL, "
               "PRIMARY KEY(symbol,trade_id))")
    db.execute("CREATE INDEX IF NOT EXISTS ix_public_trades_ts ON trades(symbol,ts)")
    return db


def record_once(db_path: Path, symbols: list[str], retention_h: float = 72) -> dict:
    db = connect(db_path)
    inserted = 0
    errors: dict[str, str] = {}
    per_symbol: dict[str, int] = {}
    for symbol in symbols:
        before = db.total_changes
        try:
            for row in fetch_trades(symbol):
                normalized = normalize_trade(symbol, row)
                if normalized:
                    db.execute("INSERT OR IGNORE INTO trades VALUES (?,?,?,?,?,?)", normalized)
            per_symbol[symbol] = db.total_changes - before
            inserted += per_symbol[symbol]
        except Exception as exc:
            errors[symbol] = f"{type(exc).__name__}: {exc}"[:200]
    db.execute("DELETE FROM trades WHERE ts<?", (time.time() - retention_h * 3600,))
    db.commit()
    total = db.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    db.close()
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "mode": "PUBLIC_READ_ONLY_NO_AUTH_NO_ORDER_PATH",
        "inserted": inserted,
        "per_symbol": per_symbol,
        "errors": errors,
        "total": total,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--pairs", default=DEFAULT_PAIRS)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--interval", type=float, default=20.0)
    parser.add_argument("--retention-h", type=float, default=72.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbols = [value.strip().upper() for value in args.pairs.split(",") if value.strip()]
    if not symbols:
        raise SystemExit("no pairs configured")
    while True:
        result = record_once(args.db, symbols, args.retention_h)
        print(json.dumps(result, separators=(",", ":")), flush=True)
        if args.once or not args.record:
            return 0 if not result["errors"] else 1
        time.sleep(max(args.interval, 0.5))


if __name__ == "__main__":
    raise SystemExit(main())
