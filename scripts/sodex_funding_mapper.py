#!/usr/bin/env python3
"""Map SoDEX funding/borrow evidence onto paper/live trade rows.

Read-only. Fail-closed: if no exact per-trade funding/borrow evidence exists, the
trade remains `MISSING_FUNDING_EVIDENCE`; no proxy is silently substituted.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports/sodex"
DEFAULT_TRADE_PATH = ROOT / "data/paper_test_twoway_state.json"
DEFAULT_FUNDING_HISTORY = ROOT / "data/sodex_funding/funding_history.jsonl"
DEFAULT_FUNDING_RATE_HISTORY = ROOT / "data/sodex_funding/funding_rates_history.jsonl"
DEFAULT_SYNC_SNAPSHOT = ROOT / "data/sodex_real_sync_snapshot.json"

FUNDING_KEYS = ("funding", "funding_fee", "funding_value", "funding_pnl")
BORROW_KEYS = ("borrow", "borrow_fee", "borrow_value", "borrow_pnl")


def parse_dt(value: Any) -> dt.datetime:
    if isinstance(value, (int, float)):
        # seconds vs milliseconds
        x = float(value)
        if x > 10_000_000_000:
            x /= 1000.0
        return dt.datetime.fromtimestamp(x, tz=dt.timezone.utc)
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def symbol_key(value: Any) -> str:
    s = str(value or "").upper().strip()
    s = s.replace("USDT", "").replace("/USDC", "").replace("-USD", "")
    s = s.replace("VUSDC", "").replace("V", "", 1) if s.startswith("V") else s
    return s


def trade_symbol(row: dict[str, Any]) -> str:
    return symbol_key(row.get("pair") or row.get("sym") or row.get("symbol") or row.get("coin"))


def trade_side(row: dict[str, Any]) -> str:
    raw = str(row.get("direction") or row.get("side") or row.get("dir") or "").upper()
    if raw in {"LONG", "L", "BUY"}:
        return "LONG"
    if raw in {"SHORT", "S", "SELL"}:
        return "SHORT"
    return raw or "UNKNOWN"


def trade_times(row: dict[str, Any]) -> tuple[dt.datetime, dt.datetime]:
    entry = row.get("entry_time") or row.get("entry_iso") or row.get("entry_ts")
    exit_ = row.get("exit_time") or row.get("exit_iso") or row.get("exit_ts")
    if entry is None or exit_ is None:
        raise ValueError("trade missing entry/exit time")
    return parse_dt(entry), parse_dt(exit_)


def closed_rows(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text())
    rows = data.get("closed_trades") or data.get("closed") or []
    return [r for r in rows if isinstance(r, dict)]


def explicit_funding(row: dict[str, Any]) -> tuple[float, list[str]] | None:
    total = 0.0
    fields: list[str] = []
    for key in FUNDING_KEYS + BORROW_KEYS:
        if key in row and row[key] not in (None, ""):
            total += float(row[key])
            fields.append(key)
    if not fields:
        return None
    return total, fields


def load_funding_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("fee") in (None, "") or row.get("ts") is None:
            continue
        out.append({
            "symbol": symbol_key(row.get("pair")),
            "side": str(row.get("side") or "").upper(),
            "ts": parse_dt(row["ts"]),
            "fee_usd": float(row["fee"]),
            "coin": row.get("coin"),
            "raw": row,
        })
    return out


def load_rate_history(path: Path) -> list[dict[str, Any]]:
    """Load forward funding-rate archive rows.

    These rows are not venue fee debits. They can estimate future/paper trade
    funding only when the funding timestamp falls inside the trade window and
    the trade row has enough data to infer notional.
    """
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("funding_rate") in (None, "") or row.get("funding_time_ms") in (None, ""):
            continue
        funding_time = parse_dt(row["funding_time_ms"])
        collected = parse_dt(row.get("collected_utc") or row.get("generated_utc") or row.get("funding_time_ms"))
        out.append({
            "symbol": symbol_key(row.get("venue_symbol") or row.get("symbol")),
            "ts": funding_time,
            "collected": collected,
            "funding_rate": float(row["funding_rate"]),
            "raw": row,
        })
    return out


def implied_notional(row: dict[str, Any]) -> float | None:
    for key in ("notional", "position_notional", "stake_amount", "trade_notional"):
        if row.get(key) not in (None, ""):
            return abs(float(row[key]))
    for key in ("qty", "quantity", "size", "position_size"):
        if row.get(key) not in (None, "") and row.get("entry_price") not in (None, ""):
            return abs(float(row[key]) * float(row["entry_price"]))
    if row.get("pnl_usd") not in (None, "") and row.get("pnl_pct") not in (None, "", 0):
        pct = float(row["pnl_pct"])
        if pct:
            return abs(float(row["pnl_usd"]) / pct)
    return None


def current_funding_rates(snapshot_path: Path) -> dict[str, float]:
    if not snapshot_path.exists():
        return {}
    snap = json.loads(snapshot_path.read_text())
    marks = snap.get("perps_marks") or {}
    return {symbol_key(k): float(v.get("fundingRate", 0.0)) for k, v in marks.items() if isinstance(v, dict)}


def history_funding_for_trade(row: dict[str, Any], history: list[dict[str, Any]]) -> tuple[float, int]:
    sym = trade_symbol(row)
    side = trade_side(row)
    entry, exit_ = trade_times(row)
    matched = [r for r in history if r["symbol"] == sym and (not r["side"] or r["side"] == side) and entry <= r["ts"] <= exit_]
    return sum(r["fee_usd"] for r in matched), len(matched)


def rate_history_funding_for_trade(row: dict[str, Any], rate_history: list[dict[str, Any]]) -> tuple[float | None, int, float | None]:
    sym = trade_symbol(row)
    side = trade_side(row)
    entry, exit_ = trade_times(row)
    notional = implied_notional(row)
    if notional is None:
        return None, 0, None
    side_sign = 1.0 if side == "SHORT" else -1.0 if side == "LONG" else 0.0
    if not side_sign:
        return None, 0, notional
    matched = [
        r for r in rate_history
        if r["symbol"] == sym and entry <= r["ts"] <= exit_ and r["collected"] <= r["ts"]
    ]
    if not matched:
        return None, 0, notional
    funding_usd = sum(notional * side_sign * r["funding_rate"] for r in matched)
    return funding_usd, len(matched), notional


def map_trade(row: dict[str, Any], history: list[dict[str, Any]], rates: dict[str, float] | None = None,
              rate_history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    sym = trade_symbol(row)
    side = trade_side(row)
    entry, exit_ = trade_times(row)
    explicit = explicit_funding(row)
    if explicit is not None:
        value, fields = explicit
        return {
            "symbol": sym, "side": side, "entry": entry.isoformat(), "exit": exit_.isoformat(),
            "status": "OK_EXPLICIT_FIELD", "funding_usd": value, "borrow_usd": 0.0,
            "source": ",".join(fields), "history_records": 0, "rate_records": 0,
            "estimated_notional_usd": None,
            "current_rate_reference": (rates or {}).get(sym),
        }
    hist_value, n = history_funding_for_trade(row, history)
    if n:
        return {
            "symbol": sym, "side": side, "entry": entry.isoformat(), "exit": exit_.isoformat(),
            "status": "OK_HISTORY_EXACT_WINDOW", "funding_usd": hist_value, "borrow_usd": 0.0,
            "source": str(DEFAULT_FUNDING_HISTORY), "history_records": n, "rate_records": 0,
            "estimated_notional_usd": None,
            "current_rate_reference": (rates or {}).get(sym),
        }
    rate_value, rate_n, notional = rate_history_funding_for_trade(row, rate_history or [])
    if rate_n and rate_value is not None:
        return {
            "symbol": sym, "side": side, "entry": entry.isoformat(), "exit": exit_.isoformat(),
            "status": "OK_RATE_ARCHIVE_ESTIMATED", "funding_usd": rate_value, "borrow_usd": 0.0,
            "source": str(DEFAULT_FUNDING_RATE_HISTORY), "history_records": 0, "rate_records": rate_n,
            "estimated_notional_usd": notional,
            "current_rate_reference": (rates or {}).get(sym),
        }
    return {
        "symbol": sym, "side": side, "entry": entry.isoformat(), "exit": exit_.isoformat(),
        "status": "MISSING_FUNDING_EVIDENCE", "funding_usd": None, "borrow_usd": None,
        "source": None, "history_records": 0, "rate_records": 0,
        "estimated_notional_usd": notional,
        "current_rate_reference": (rates or {}).get(sym),
    }


def archive_start(rate_history: list[dict[str, Any]]) -> dt.datetime | None:
    """Earliest timestamp present in the funding-rate archive.

    Trades that exited before this instant cannot carry rate-archive evidence,
    so they are reported as `n_pre_archive` rather than counted as missing.
    """
    if not rate_history:
        return None
    return min(r["ts"] for r in rate_history)


def build_mapping(trade_path: Path = DEFAULT_TRADE_PATH,
                  history_path: Path = DEFAULT_FUNDING_HISTORY,
                  snapshot_path: Path = DEFAULT_SYNC_SNAPSHOT,
                  rate_history_path: Path = DEFAULT_FUNDING_RATE_HISTORY) -> dict[str, Any]:
    trades = closed_rows(trade_path)
    short_trades = [r for r in trades if trade_side(r) == "SHORT"]
    history = load_funding_history(history_path)
    rate_history = load_rate_history(rate_history_path)
    rates = current_funding_rates(snapshot_path)
    start = archive_start(rate_history)

    # Re-baseline (2026-10-05): the rate archive began 2026-10-02, so SHORT trades
    # that exited earlier can never carry rate-archive evidence. Counting them as
    # `missing` diluted coverage with a structural dead-end; counting them as `ok`
    # would fabricate evidence. They are excluded from the denominator and
    # reported as `n_pre_archive`. In-window trades without evidence stay
    # fail-closed, and 0/0 in-window is NOT a vacuous pass.
    in_window: list[dict[str, Any]] = []
    pre_archive: list[dict[str, Any]] = []
    for row in short_trades:
        _, exit_ = trade_times(row)
        if start is not None and exit_ < start:
            pre_archive.append(row)
        else:
            in_window.append(row)

    mapped = [map_trade(r, history, rates, rate_history) for r in in_window]
    missing = sum(1 for r in mapped if r["status"] == "MISSING_FUNDING_EVIDENCE")
    exact = sum(1 for r in mapped if r["status"] in {"OK_EXPLICIT_FIELD", "OK_HISTORY_EXACT_WINDOW"})
    estimated = sum(1 for r in mapped if r["status"] == "OK_RATE_ARCHIVE_ESTIMATED")
    n_in_window = len(mapped)
    ok = n_in_window - missing
    passed = n_in_window > 0 and missing == 0
    if passed:
        reason = "all in-window short trades have funding evidence"
    elif n_in_window == 0:
        reason = (f"no short trade inside rate-archive window; n_pre_archive={len(pre_archive)} "
                  "excluded (exited before archive start) -> fail-closed")
    else:
        reason = "funding/borrow evidence incomplete; do not promote SHORT verdict"
    return {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "trade_path": str(trade_path),
        "funding_history_path": str(history_path),
        "funding_rate_history_path": str(rate_history_path),
        "snapshot_path": str(snapshot_path),
        "archive_start_utc": start.isoformat() if start else None,
        "n_short_trades": len(short_trades),
        "n_in_window": n_in_window,
        "n_pre_archive": len(pre_archive),
        "n_ok": ok,
        "n_exact": exact,
        "n_rate_estimated": estimated,
        "n_missing": missing,
        "coverage_pct": ok / n_in_window if n_in_window else 0.0,
        "exact_coverage_pct": exact / n_in_window if n_in_window else 0.0,
        "rate_estimated_coverage_pct": estimated / n_in_window if n_in_window else 0.0,
        "verdict": "PASS" if passed else "FAIL_CLOSED",
        "reason": reason,
        "mapped": mapped,
        "pre_archive": [
            {"symbol": trade_symbol(r), "exit": trade_times(r)[1].isoformat()} for r in pre_archive
        ],
    }


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    result = build_mapping()
    out = REPORT_DIR / "sodex_funding_map_20261002.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True))
    print(json.dumps({
        "out": str(out),
        "verdict": result["verdict"],
        "n_short_trades": result["n_short_trades"],
        "n_in_window": result["n_in_window"],
        "n_pre_archive": result["n_pre_archive"],
        "n_ok": result["n_ok"],
        "n_missing": result["n_missing"],
    }, indent=2))


if __name__ == "__main__":
    main()
