#!/usr/bin/env python3
"""Bridge: paper-lane realised PnL -> distance to the 0,8%/48h wallet target.

PERINTAH_1_SoDEX.md line 120 defines

    jarak_ke_target = (net PnL aktual 48 jam) / (0,8% x wallet saat itu)

where "wallet" is TOTAL wallet. The paper lanes (swing / twoway / realwide) were
never wired into any wallet-normalised series, so the doc-mandated weekly number
could not be produced for the engines actually under test. This script is that
bridge.

TWO MEASUREMENT TRAPS THIS SCRIPT EXISTS TO AVOID

1. OVERLAPPING WINDOWS. A rolling 48 h window stepped per trade yields 374 windows
   from 376 trades -- they share almost every trade, so the spread across them is
   not evidence. Measured that way twoway showed "median +2,48%/48h", 3,1x the
   target. Partitioning the timeline into DISJOINT 48 h buckets gives +1,41%. The
   overlapping number is the same trades counted ~12x, weighted to the early
   high-equity period. Only disjoint buckets are reported here.

2. WRONG DENOMINATOR. `wallet_roi` in the lane state files divides by a FIXED
   $174,55 lane paper wallet, not by the real wallet, and the lanes run ~$300
   notional on it (1,72x). Scaling the lane to the real wallet at the same
   leverage ratio makes the return-on-backing-capital identical to `wallet_roi`,
   so that is the quantity projected. The alternative denominator
   (pnl_usd / real_wallet_now, i.e. keeping the absolute notional fixed) is
   reported beside it, because the two differ and the choice is a policy call.

Read-only. No order, no gate, no exit, no leverage, no sizing change.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import random
import statistics as st
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TARGET_PCT = 0.008  # 0,8% of total wallet per 48 h
LANES = ("twoway", "swing", "realwide")
REPORT_JSON = ROOT / "reports/sodex/sodex_lane_target_projection.json"


def parse_dt(value: str) -> dt.datetime:
    text = str(value)
    return dt.datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text).astimezone(dt.timezone.utc)


def load_trades(lane: str, root: Path = ROOT) -> list[dict[str, Any]]:
    path = root / f"data/paper_test_{lane}_state.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    # Schema drift: swing/twoway menulis `closed_trades`, realwide menulis `closed`.
    # Tanpa fallback ini lane realwide dilaporkan FAIL_CLOSED "no closed trades"
    # padahal state-nya berisi 368 trade tertutup.
    raw = data.get("closed_trades")
    if raw is None:
        raw = data.get("closed") or []
    trades = []
    for t in raw:
        ts_raw = t.get("exit_time") or t.get("exit_iso")
        if ts_raw is None and isinstance(t.get("exit_ts"), (int, float)):
            ts_raw = dt.datetime.fromtimestamp(float(t["exit_ts"]), dt.timezone.utc).isoformat()
        if ts_raw and t.get("pnl_usd") is not None:
            t = dict(t)
            t["_ts"] = parse_dt(ts_raw)
            trades.append(t)
    return sorted(trades, key=lambda t: t["_ts"])


def disjoint_buckets(trades: list[dict[str, Any]], hours: int = 48) -> list[list[dict[str, Any]]]:
    """Partition the trade timeline into NON-overlapping `hours` buckets."""
    if not trades:
        return []
    origin = trades[0]["_ts"]
    groups: dict[int, list[dict[str, Any]]] = {}
    for t in trades:
        key = int((t["_ts"] - origin).total_seconds() // (hours * 3600))
        groups.setdefault(key, []).append(t)
    return [groups[k] for k in sorted(groups)]


def bootstrap_mean_ci(values: list[float], n_iter: int = 10000, seed: int = 20261004) -> tuple[float, float]:
    if len(values) < 3:
        return (math.nan, math.nan)
    rnd = random.Random(seed)
    means = sorted(st.mean(rnd.choices(values, k=len(values))) for _ in range(n_iter))
    return means[int(0.025 * n_iter)], means[int(0.975 * n_iter)]


def project_lane(lane: str, real_wallet: float, hours: int = 48, *, root: Path = ROOT) -> dict[str, Any]:
    trades = load_trades(lane, root)
    if not trades:
        return {"lane": lane, "valid": False, "reason": f"FAIL_CLOSED: no closed trades for lane '{lane}'"}

    buckets = disjoint_buckets(trades, hours)
    if len(buckets) < 2:
        return {"lane": lane, "valid": False, "reason": f"FAIL_CLOSED: {len(buckets)} disjoint {hours}h bucket(s); need >=2"}

    roi_on_backing = [sum(float(t.get("wallet_roi") or 0.0) for t in b) for b in buckets]
    pnl_usd = [sum(float(t["pnl_usd"]) for t in b) for b in buckets]
    roi_on_real_fixed = [u / real_wallet for u in pnl_usd]
    target_usd = TARGET_PCT * real_wallet
    lo, hi = bootstrap_mean_ci(roi_on_backing)
    n = len(buckets)
    hit = sum(1 for r in roi_on_backing if r >= TARGET_PCT)

    return {
        "lane": lane,
        "valid": True,
        "reason": "OK_DISJOINT_BUCKETS",
        "bucket_hours": hours,
        "n_disjoint_buckets": n,
        "n_trades": len(trades),
        "real_wallet_usd": real_wallet,
        "target_48h_pct": TARGET_PCT,
        "target_48h_usd": target_usd,
        "roi_on_backing_capital": {
            "median": st.median(roi_on_backing),
            "mean": st.mean(roi_on_backing),
            "stdev": st.pstdev(roi_on_backing),
            "ci95_mean": [lo, hi],
            "ci95_contains_zero": bool(lo <= 0.0 <= hi),
            "ci95_contains_target": bool(lo <= TARGET_PCT <= hi),
        },
        "roi_on_real_wallet_fixed_notional": {
            "median": st.median(roi_on_real_fixed),
            "mean": st.mean(roi_on_real_fixed),
        },
        "hit_rate_vs_target": hit / n,
        "n_buckets_meeting_target": hit,
        "n_buckets_positive": sum(1 for r in roi_on_backing if r > 0),
        "distance_to_target_median": st.median(roi_on_backing) / TARGET_PCT,
        "worst_bucket": min(roi_on_backing),
        "best_bucket": max(roi_on_backing),
        "signal_to_noise": (st.mean(roi_on_backing) / st.pstdev(roi_on_backing)) if st.pstdev(roi_on_backing) else math.nan,
    }


def project_all(real_wallet: float, hours: int = 48, *, root: Path = ROOT) -> dict[str, Any]:
    return {
        "method": "DISJOINT_BUCKETS_ON_BACKING_CAPITAL",
        "overlapping_window_warning": (
            "Never step a 48h window per trade: that produced 374 windows from 376 trades and a "
            "median of +2,48%/48h (3,1x the target) against +1,41% on disjoint buckets."
        ),
        "lanes": [project_lane(lane, real_wallet, hours, root=root) for lane in LANES],
    }


def main() -> int:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from sodex_target_distance import target_distance

    td = target_distance()
    wallet = td.get("wallet_now_usd") or 0.0
    out = project_all(wallet)
    out["wallet_source"] = td.get("source")
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps(out, indent=2, default=str))
    return 0 if any(l.get("valid") for l in out["lanes"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
