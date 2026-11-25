#!/usr/bin/env python3
"""Gate promosi target SoDEX — REV2 KUMULATIF.

Aturan mengikat (docs/sodex/KEPUTUSAN_TARGET_20261102.md §1a):
- Window = 30 hari kalender UTC berturut-turut = 144 bucket 5 jam.
- Hari hilang di dalam window -> window TIDAK SAH (tidak diinterpolasi).
- Gate A: M_kum (mean return per bucket 5 jam, net) >= 0,010%.
- Gate B: MDD kurva ekuitas window >= -15%.
- PROMOTE hanya bila A dan B; selain itu status Target Utama TIDAK berubah.

Mode input:
- equity  : JSONL {ts, equity}  -> return bucket dihitung dari kurva ekuitas.
- trades  : JSONL {ts, net_pct} -> return dianggap fraksi wallet; M_kum = sum/144.

Read-only: tidak menulis state, tidak menyentuh order.
"""

from __future__ import annotations

import argparse
import bisect
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

UTC = timezone.utc

WINDOW_DAYS = 30
BUCKET_HOURS = 5
BUCKETS_PER_WINDOW = WINDOW_DAYS * 24 // BUCKET_HOURS  # 144
TARGET_PER_5H_PCT = 0.010
MAX_DD_PCT = -15.0
EQUITY_KEYS = ("equity", "equity_usd", "account_value", "total_equity_usd")


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # tolak NaN


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip().lstrip("\x00")
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _equity_series(rows: Iterable[dict[str, Any]]) -> list[tuple[datetime, float]]:
    series: list[tuple[datetime, float]] = []
    for row in rows:
        ts = _parse_ts(row.get("ts") or row.get("timestamp") or row.get("time"))
        if ts is None:
            continue
        value = None
        for key in EQUITY_KEYS:
            if key in row:
                value = _num(row.get(key))
                if value is not None:
                    break
        if value is None or value <= 0:
            continue
        series.append((ts, value))
    series.sort(key=lambda item: item[0])
    return series


def _step_lookup(series: list[tuple[datetime, float]]):
    stamps = [ts for ts, _ in series]

    def at(moment: datetime) -> float | None:
        idx = bisect.bisect_right(stamps, moment) - 1
        if idx < 0:
            return None
        return series[idx][1]

    return at


def _day_floor(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _coverage_days(series: list[tuple[datetime, float]], start: datetime, end: datetime) -> int:
    days = {_day_floor(ts) for ts, _ in series if start <= ts < end}
    return len(days)


def _result(status: str, reasons: list[str], **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "status": status,
        "m_kum_pct": None,
        "mdd_pct": None,
        "n_days": 0,
        "n_buckets": 0,
        "window_start": None,
        "window_end": None,
        "first_qualifying_window": None,
        "reasons": reasons,
        "thresholds": {
            "m_kum_pct_min": TARGET_PER_5H_PCT,
            "mdd_pct_min": MAX_DD_PCT,
            "window_days": WINDOW_DAYS,
            "buckets": BUCKETS_PER_WINDOW,
        },
    }
    out.update(extra)
    return out


def _window_metrics_equity(series: list[tuple[datetime, float]], start: datetime, end: datetime):
    at = _step_lookup(series)
    edges: list[float | None] = []
    for k in range(BUCKETS_PER_WINDOW + 1):
        edges.append(at(start + timedelta(hours=BUCKET_HOURS * k)))
    if any(value is None or value <= 0 for value in edges):
        return None
    returns = [edges[k + 1] / edges[k] - 1.0 for k in range(BUCKETS_PER_WINDOW)]  # type: ignore[operator]
    m_kum_pct = (sum(returns) / BUCKETS_PER_WINDOW) * 100.0
    peak = edges[0]
    worst = 0.0
    for value in edges:
        if value > peak:  # type: ignore[operator]
            peak = value
        dd = (value / peak - 1.0) * 100.0  # type: ignore[operator]
        if dd < worst:
            worst = dd
    return m_kum_pct, worst


def _window_metrics_trades(rows: list[tuple[datetime, float]], start: datetime, end: datetime):
    inside = [value for ts, value in rows if start <= ts < end]
    if not inside:
        return None
    total = sum(inside)
    m_kum_pct = (total / BUCKETS_PER_WINDOW) * 100.0
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in inside:
        equity *= 1.0 + value
        if equity > peak:
            peak = equity
        dd = (equity / peak - 1.0) * 100.0
        if dd < worst:
            worst = dd
    return m_kum_pct, worst


def _scan(
    series_rows: list[tuple[datetime, Any]],
    coverage_rows: list[tuple[datetime, Any]],
    metrics,
) -> dict[str, Any]:
    if not series_rows:
        return _result("DATA_KURANG", ["n_hari=0 — tidak ada baris valid"])

    first_day = _day_floor(series_rows[0][0])
    last_ts = series_rows[-1][0]
    span_days = (_day_floor(last_ts) - first_day).days + 1
    if span_days < WINDOW_DAYS:
        return _result(
            "DATA_KURANG",
            [f"n_hari={span_days} < {WINDOW_DAYS} — window belum lengkap"],
            n_days=span_days,
        )

    windows: list[dict[str, Any]] = []
    invalid_reasons: list[str] = []
    for offset in range(0, span_days - WINDOW_DAYS + 1):
        start = first_day + timedelta(days=offset)
        end = start + timedelta(days=WINDOW_DAYS)
        if _coverage_days(coverage_rows, start, end) < WINDOW_DAYS:
            invalid_reasons.append(f"window {start.date()} hari hilang")
            continue
        measured = metrics(series_rows, start, end)
        if measured is None:
            invalid_reasons.append(f"window {start.date()} data tidak lengkap")
            continue
        m_kum_pct, mdd_pct = measured
        verdict = (
            "PASS"
            if m_kum_pct >= TARGET_PER_5H_PCT and mdd_pct >= MAX_DD_PCT
            else "FAIL"
        )
        windows.append(
            {
                "start": start.date().isoformat(),
                "end": end.date().isoformat(),
                "m_kum_pct": round(m_kum_pct, 6),
                "mdd_pct": round(mdd_pct, 4),
                "verdict": verdict,
            }
        )

    if not windows:
        reasons = ["tidak ada window 30 hari yang sah"]
        if invalid_reasons:
            reasons.append(invalid_reasons[-1])
        return _result("DATA_KURANG", reasons, n_days=span_days)

    latest = windows[-1]
    qualifying = next((w for w in windows if w["verdict"] == "PASS"), None)
    reasons: list[str] = []
    if latest["m_kum_pct"] < TARGET_PER_5H_PCT:
        reasons.append(
            f"Gate A gagal: M_kum {latest['m_kum_pct']:.6f}% < {TARGET_PER_5H_PCT:.3f}%"
        )
    if latest["mdd_pct"] < MAX_DD_PCT:
        reasons.append(f"Gate B gagal: MDD {latest['mdd_pct']:.2f}% < {MAX_DD_PCT:.0f}%")
    if latest["verdict"] == "PASS":
        reasons.append("Gate A dan B terpenuhi — promosi Target Utama sah")

    return _result(
        latest["verdict"],
        reasons,
        m_kum_pct=latest["m_kum_pct"],
        mdd_pct=latest["mdd_pct"],
        n_days=span_days,
        n_buckets=BUCKETS_PER_WINDOW,
        window_start=latest["start"],
        window_end=latest["end"],
        first_qualifying_window=qualifying,
        windows_evaluated=len(windows),
    )


def evaluate_equity(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    series = _equity_series(rows)
    return _scan(series, series, _window_metrics_equity)


def evaluate_trades(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    series: list[tuple[datetime, float]] = []
    for row in rows:
        ts = _parse_ts(row.get("ts") or row.get("timestamp") or row.get("time"))
        if ts is None:
            continue
        value = None
        for key in ("net_pct", "ret_pct", "pnl_pct", "net_ret"):
            if key in row:
                value = _num(row.get(key))
                if value is not None:
                    break
        if value is None:
            continue
        series.append((ts, value))
    series.sort(key=lambda item: item[0])
    return _scan(series, series, _window_metrics_trades)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate promosi target SoDEX (kumulatif 30 hari)")
    parser.add_argument("--equity-file", type=Path)
    parser.add_argument("--ledger-file", type=Path)
    parser.add_argument("--json", action="store_true", help="cetak JSON penuh")
    args = parser.parse_args(argv)

    source = args.equity_file or args.ledger_file
    if source is None:
        print("ERROR: beri --equity-file atau --ledger-file", file=sys.stderr)
        return 2
    if not source.exists():
        print(f"ERROR: file tidak ada: {source}", file=sys.stderr)
        return 2

    try:
        rows = _load_jsonl(source)
    except OSError as exc:
        print(f"ERROR: gagal baca {source}: {exc}", file=sys.stderr)
        return 2

    result = evaluate_equity(rows) if args.equity_file else evaluate_trades(rows)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"status        : {result['status']}")
        print(f"window        : {result['window_start']} -> {result['window_end']}")
        print(f"M_kum         : {result['m_kum_pct']}% / 5j (ambang {TARGET_PER_5H_PCT}%)")
        print(f"MDD           : {result['mdd_pct']}% (ambang {MAX_DD_PCT}%)")
        print(f"n_hari        : {result['n_days']}")
        for reason in result["reasons"]:
            print(f"- {reason}")

    return {"PASS": 0, "FAIL": 1}.get(result["status"], 3)


if __name__ == "__main__":
    raise SystemExit(main())
