#!/usr/bin/env python3
"""Collect public SoDEX perps funding rates from local sync snapshots.

Read-only D0.1 collector. It does not infer historical funding for old trades;
it only starts a clean hourly-rate archive going forward from `data/sodex_real_sync_snapshot.json`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data/sodex_real_sync_snapshot.json"
OUT = ROOT / "data/sodex_funding/funding_rates_history.jsonl"
SUMMARY = ROOT / "reports/sodex/sodex_funding_rate_collector_latest.json"


def parse_dt(value: str | None) -> dt.datetime:
    if not value:
        return dt.datetime.now(dt.timezone.utc)
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def base_symbol(venue_symbol: str) -> str:
    return venue_symbol.split("-", 1)[0].upper()


def extract_rate_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    generated = parse_dt(snapshot.get("generated_utc"))
    marks = snapshot.get("perps_marks") or {}
    rows: list[dict[str, Any]] = []
    for venue_symbol, mark in sorted(marks.items()):
        if not isinstance(mark, dict) or "fundingRate" not in mark:
            continue
        try:
            next_time = int(mark.get("nextFundingTime") or 0)
            rate = float(mark.get("fundingRate"))
            row = {
                "collected_utc": generated.isoformat(),
                "symbol": base_symbol(str(venue_symbol)),
                "venue_symbol": str(venue_symbol),
                "funding_time_ms": next_time,
                "funding_time_utc": dt.datetime.fromtimestamp(next_time / 1000, dt.timezone.utc).isoformat() if next_time else None,
                "funding_rate": rate,
                "funding_rate_bps": rate * 10000.0,
                "mark_price": float(mark.get("markPrice")) if mark.get("markPrice") is not None else None,
                "source": str(SNAPSHOT),
            }
        except (TypeError, ValueError):
            continue
        rows.append(row)
    return rows


def row_key(row: dict[str, Any]) -> tuple[str, int]:
    return str(row.get("venue_symbol") or row.get("symbol")), int(row.get("funding_time_ms") or 0)


def existing_keys(path: Path) -> set[tuple[str, int]]:
    keys: set[tuple[str, int]] = set()
    if not path.exists():
        return keys
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            keys.add(row_key(json.loads(line)))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return keys


def append_new_rows(path: Path, rows: list[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = existing_keys(path)
    new_rows = []
    for row in rows:
        key = row_key(row)
        if key in seen:
            continue
        seen.add(key)
        new_rows.append(row)
    if new_rows:
        with path.open("a") as f:
            for row in new_rows:
                f.write(json.dumps(row, sort_keys=True) + "\n")
    return len(new_rows)


def summarize(rows: list[dict[str, Any]], appended: int = 0, out_path: Path = OUT) -> dict[str, Any]:
    if not rows:
        return {
            "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "verdict": "FAIL_CLOSED",
            "reason": "no funding rows extracted from snapshot",
            "n_rows": 0,
            "appended": 0,
            "out": str(out_path),
        }
    rates = [float(r["funding_rate"]) for r in rows]
    return {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "verdict": "OK",
        "n_rows": len(rows),
        "appended": appended,
        "out": str(out_path),
        "min_rate_bps": min(rates) * 10000.0,
        "max_rate_bps": max(rates) * 10000.0,
        "top_abs": sorted(
            [{"symbol": r["symbol"], "venue_symbol": r["venue_symbol"], "funding_rate_bps": r["funding_rate_bps"], "funding_time_utc": r["funding_time_utc"]} for r in rows],
            key=lambda x: abs(float(x["funding_rate_bps"])),
            reverse=True,
        )[:10],
    }


def collect(snapshot_path: Path = SNAPSHOT, out_path: Path = OUT, summary_path: Path = SUMMARY) -> dict[str, Any]:
    if not snapshot_path.exists():
        result = summarize([], 0, out_path)
        result["reason"] = f"snapshot missing: {snapshot_path}"
    else:
        rows = extract_rate_rows(json.loads(snapshot_path.read_text()))
        appended = append_new_rows(out_path, rows)
        result = summarize(rows, appended, out_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main() -> None:
    p = argparse.ArgumentParser(description="Collect SoDEX funding rates from local sync snapshot")
    p.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--summary", type=Path, default=SUMMARY)
    args = p.parse_args()
    print(json.dumps(collect(args.snapshot, args.out, args.summary), indent=2))


if __name__ == "__main__":
    main()
