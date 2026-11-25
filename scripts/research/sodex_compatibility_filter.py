#!/usr/bin/env python3
"""Filter Binance 36M signal candidates for SoDEX executable compatibility.

Combines:
- Binance proxy edge report (direction/regime).
- SoDEX native L1/trade liquidity, spread, and depth.

Read-only. No credentials. No orders.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from pathlib import Path
from statistics import median

PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_SIGNAL = PROJECT / "data" / "research" / "binance_36m_signal_report_target2.json"
DEFAULT_OUT = PROJECT / "data" / "research" / "sodex_compatibility_filter.json"
DEFAULT_BOOK_DB = PROJECT / "data" / "sodex_book_recorder.db"
DEFAULT_TRADES_DB = PROJECT / "data" / "sodex_public_trades.db"


def binance_to_sodex(symbol: str) -> str:
    s = symbol.upper().strip()
    if s.endswith("USDT"):
        return f"{s[:-4]}-USD"
    if s.endswith("USD"):
        return f"{s[:-3]}-USD"
    return s.replace("/", "-")


def quantile(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    xs = sorted(vals)
    idx = min(len(xs) - 1, max(0, int(round((len(xs) - 1) * q))))
    return xs[idx]


def _l1_stats(book_db: Path) -> dict[str, dict]:
    if not book_db.exists():
        return {}
    con = sqlite3.connect(book_db)
    symbols = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM l1 ORDER BY symbol")]
    out: dict[str, dict] = {}
    for sym in symbols:
        rows = con.execute(
            "SELECT bid, ask, bid_sz, ask_sz FROM l1 WHERE symbol=? AND bid>0 AND ask>0 LIMIT 50000",
            (sym,),
        ).fetchall()
        if not rows:
            continue
        spreads = [((ask - bid) / ((ask + bid) / 2.0)) * 10000.0 for bid, ask, _, _ in rows if ask >= bid]
        depths = [bid * bid_sz + ask * ask_sz for bid, ask, bid_sz, ask_sz in rows]
        out[sym] = {
            "l1_rows": len(rows),
            "median_spread_bps": round(median(spreads), 4) if spreads else None,
            "p90_spread_bps": round(quantile(spreads, 0.90) or 0.0, 4) if spreads else None,
            "median_depth_usd": round(median(depths), 2) if depths else 0.0,
            "p10_depth_usd": round(quantile(depths, 0.10) or 0.0, 2) if depths else 0.0,
        }
    con.close()
    return out


def _trade_stats(trades_db: Path) -> dict[str, dict]:
    if not trades_db.exists():
        return {}
    con = sqlite3.connect(trades_db)
    rows = con.execute(
        "SELECT symbol, COUNT(*), MIN(ts), MAX(ts), SUM(price*qty) FROM trades GROUP BY symbol"
    ).fetchall()
    con.close()
    return {
        sym: {
            "trade_rows": int(n),
            "first_ts": first,
            "last_ts": last,
            "notional_usd": round(float(notional or 0.0), 2),
        }
        for sym, n, first, last, notional in rows
    }


def sodex_metrics(book_db: Path = DEFAULT_BOOK_DB, trades_db: Path = DEFAULT_TRADES_DB) -> dict[str, dict]:
    l1 = _l1_stats(book_db)
    tr = _trade_stats(trades_db)
    syms = sorted(set(l1) | set(tr))
    return {s: (l1.get(s, {}) | tr.get(s, {})) for s in syms}


def compatibility_score(edge: dict, liq: dict) -> float:
    if not liq or liq.get("l1_rows", 0) <= 0:
        return -999.0
    ci = float(edge.get("ci95_lo_pct", -10.0))
    pf = float(edge.get("pf", 0.0))
    delta = float(edge.get("delta_vs_baseline_pct", 0.0))
    n = max(0, int(edge.get("n", 0)))
    spread = float(liq.get("median_spread_bps") or 999.0)
    depth = float(liq.get("median_depth_usd") or 0.0)
    l1_rows = int(liq.get("l1_rows", 0))
    trades = int(liq.get("trade_rows", 0))

    edge_score = ci * 25.0 + max(0.0, pf - 1.0) * 15.0 + delta * 10.0 + min(20.0, math.log10(max(1, n)) * 5.0)
    liquidity_score = min(25.0, math.log10(max(1.0, depth)) * 6.0) + min(15.0, math.log10(max(1, l1_rows)) * 3.0) + min(10.0, math.log10(max(1, trades)) * 2.0)
    spread_penalty = max(0.0, spread - 5.0) * 2.0
    return round(edge_score + liquidity_score - spread_penalty, 3)


def filter_candidates(signal_report: Path, out: Path, book_db: Path, trades_db: Path, min_n: int, min_ci: float) -> dict:
    report = json.loads(signal_report.read_text())
    liq = sodex_metrics(book_db, trades_db)
    candidates = []
    for edge in report.get("all_results", []):
        if int(edge.get("n", 0)) < min_n:
            continue
        if float(edge.get("ci95_lo_pct", -999)) < min_ci:
            continue
        sodex_symbol = binance_to_sodex(edge.get("symbol", ""))
        metrics = liq.get(sodex_symbol, {})
        row = {
            **edge,
            "sodex_symbol": sodex_symbol,
            "sodex_available": bool(metrics),
            "sodex_metrics": metrics,
        }
        row["compatibility_score"] = compatibility_score(edge, metrics)
        if row["sodex_available"]:
            candidates.append(row)
    candidates.sort(key=lambda r: r["compatibility_score"], reverse=True)
    result = {
        "method": "Binance 36M proxy edge filtered by SoDEX native L1/trade liquidity; read-only; not live approval",
        "source_signal_report": str(signal_report),
        "sodex_symbols_seen": len(liq),
        "filters": {"min_n": min_n, "min_ci95_lo_pct": min_ci},
        "top_compatible": candidates[:50],
        "all_compatible_count": len(candidates),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="SoDEX compatibility filter for Binance proxy candidates")
    ap.add_argument("--signal-report", type=Path, default=DEFAULT_SIGNAL)
    ap.add_argument("--book-db", type=Path, default=DEFAULT_BOOK_DB)
    ap.add_argument("--trades-db", type=Path, default=DEFAULT_TRADES_DB)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--min-n", type=int, default=30)
    ap.add_argument("--min-ci", type=float, default=0.0)
    args = ap.parse_args()
    result = filter_candidates(args.signal_report, args.out, args.book_db, args.trades_db, args.min_n, args.min_ci)
    print(json.dumps({
        "out": str(args.out),
        "sodex_symbols_seen": result["sodex_symbols_seen"],
        "all_compatible_count": result["all_compatible_count"],
        "top_compatible": result["top_compatible"][:10],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
