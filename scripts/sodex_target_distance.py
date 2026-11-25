#!/usr/bin/env python3
"""Fail-closed `jarak_ke_target` measurement (RISET PERINTAH_1_SoDEX.md line 120).

    jarak_ke_target = (net PnL aktual 48 jam) / (0,8% x wallet saat itu)

WHY THIS MODULE EXISTS
The naive implementation picks the capital_report row nearest the 48 h boundary by
timestamp alone. capital_report.jsonl contains 25 zero-equity snapshots (heartbeat
rows written before the wallet was priced). When one of those lands on the boundary
the window opens at $0.00, so

    delta_48h = wallet_now - 0 = wallet_now

and the weekly report announced `jarak_ke_target = 12500%` -- a 2400x overstatement
of a number that was actually negative. A wrong sign with four digits of false
precision is worse than no number: it was the headline metric of the weekly report.

Rules enforced here:
1. Only snapshots with equity > 0 are usable as a window anchor.
2. The anchor is the LAST valid snapshot at or before the 48 h boundary -- opening
   the window early is safer than opening it late (it never truncates the window,
   and the extra span is reported as `window_hours_actual`).
3. Fewer than 2 valid snapshots in the window => FAIL_CLOSED, no number emitted.
4. The naive figure stays in the output as `*_naive` so the correction is auditable
   and reversible rather than silently overwritten.
5. THE NUMERATOR IS NAMED. PERINTAH_1 says "net PnL aktual 48 jam" without saying
   whose. This module reports BOTH and labels them, because they are different
   questions, not two estimates of one number:
     - `jarak_ke_target_wallet_delta`   -- wallet equity move. Includes deposits,
       withdrawals and venue reconciliation, so it is NOT trading performance.
     - `jarak_ke_target_engine_trading` -- the engine's own net PnL. Trading only.
   Once read as a contradiction (-5,20% vs -54,2%); it was not. `numerator_used`
   and `boundary_basis` are emitted so no reader has to infer which was used.

The window boundary is anchored on the LATEST SNAPSHOT timestamp, not wall clock.
The harness anchors on wall clock now. Both are legitimate; `boundary_basis` says
which. A stale snapshot makes this module's window lag the harness by that lag.

FIXED UPSTREAM (2026-10-04): scripts/capital_report.py no longer writes equity 0.0
when every fetch source fails -- it writes null plus `equity_valid: false`, so an
unfetchable wallet reads as UNKNOWN instead of $0.00. The 25 legacy zero rows stay
in history and remain rejected here by rule 1.

Read-only. Touches no order, no gate, no exit, no leverage.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CAPITAL_REPORT = ROOT / "data/capital_report.jsonl"
TARGET_PCT = 0.008  # 0,8% of total wallet per 48 h window


def parse_dt(value: Any) -> dt.datetime:
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def load_snapshots(path: Path = CAPITAL_REPORT) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("equity") is None:
            continue
        rows.append({
            "ts": parse_dt(row["ts"]),
            "equity": float(row["equity"]),
            "stats": row.get("stats") or {},
        })
    return sorted(rows, key=lambda r: r["ts"])


def pick_anchor(rows: list[dict[str, Any]], boundary: dt.datetime) -> dict[str, Any] | None:
    """Last VALID (equity > 0) snapshot at or before `boundary`; else the first valid after."""
    valid = [r for r in rows if r["equity"] > 0]
    if not valid:
        return None
    before = [r for r in valid if r["ts"] <= boundary]
    if before:
        return before[-1]
    return valid[0]


def naive_anchor(rows: list[dict[str, Any]], boundary: dt.datetime) -> dict[str, Any] | None:
    """The timestamp-only pick that produced the 12500% artifact -- kept for comparison."""
    usable = [r for r in rows if r["ts"] is not None]
    return min(usable, key=lambda r: abs((r["ts"] - boundary).total_seconds())) if usable else None


def target_distance(rows: list[dict[str, Any]] | None = None, hours: int = 48, *, path: Path = CAPITAL_REPORT) -> dict[str, Any]:
    rows = load_snapshots(path) if rows is None else rows
    if len(rows) < 2:
        return {"valid": False, "reason": "FAIL_CLOSED: fewer than 2 capital_report snapshots"}

    latest = rows[-1]
    wallet_now = float(latest["equity"])
    if wallet_now <= 0:
        return {"valid": False, "reason": f"FAIL_CLOSED: latest snapshot equity={wallet_now} is not positive"}

    boundary = latest["ts"] - dt.timedelta(hours=hours)
    anchor = pick_anchor(rows, boundary)
    if anchor is None:
        return {"valid": False, "reason": "FAIL_CLOSED: no snapshot with equity > 0"}

    window = [r for r in rows if r["ts"] >= anchor["ts"]]
    if len(window) < 2:
        return {"valid": False, "reason": "FAIL_CLOSED: fewer than 2 valid snapshots inside the window"}

    net_pnl = wallet_now - float(anchor["equity"])
    target_usd = TARGET_PCT * wallet_now
    window_hours = (latest["ts"] - anchor["ts"]).total_seconds() / 3600.0
    naive = naive_anchor(rows, boundary)
    naive_delta = wallet_now - float(naive["equity"]) if naive else math.nan

    return {
        "valid": True,
        "reason": "OK",
        "formula": "jarak_ke_target = net_pnl_48h / (0.008 * wallet_now)",
        # D0.6b: the module and the harness once appeared to disagree (-5,20% vs -54,2%).
        # They do NOT: they use different NUMERATORS. The wallet delta moves with deposits,
        # withdrawals and venue reconciliation; the engine net is trading-only. Both are
        # reported here so a reader can never mistake one question for the other.
        "numerator_used": "WALLET_EQUITY_DELTA",
        "boundary_basis": "latest_snapshot_ts",
        "boundary_ts": boundary.isoformat(),
        "source": str(path),
        "window_hours_requested": hours,
        "window_hours_actual": window_hours,
        "anchor_ts": anchor["ts"].isoformat(),
        "end_ts": latest["ts"].isoformat(),
        "anchor_equity_usd": float(anchor["equity"]),
        "wallet_now_usd": wallet_now,
        "net_pnl_usd": net_pnl,
        "target_usd": target_usd,
        "jarak_ke_target": net_pnl / target_usd,
        "jarak_ke_target_wallet_delta": net_pnl / target_usd,
        "engine_net_usd": sum(float(r["stats"].get("net_6h") or 0.0) for r in window),
        "jarak_ke_target_engine_trading": (
            sum(float(r["stats"].get("net_6h") or 0.0) for r in window) / target_usd
            if target_usd else math.nan),
        "n_snapshots_in_window": len(window),
        "engine_round_trips_in_window": sum(int((r["stats"].get("rt_6h") or 0)) for r in window),
        "engine_net_6h_sum_usd": sum(float(r["stats"].get("net_6h") or 0.0) for r in window),
        "anchor_naive_ts": naive["ts"].isoformat() if naive else None,
        "anchor_naive_equity_usd": float(naive["equity"]) if naive else None,
        "net_pnl_usd_naive": naive_delta,
        "jarak_ke_target_naive": (naive_delta / target_usd) if naive and target_usd else math.nan,
        "correction_ratio": (naive_delta / net_pnl) if net_pnl not in (0.0, math.nan) else None,
    }


def main() -> int:
    out = target_distance()
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
