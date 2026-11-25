#!/usr/bin/env python3
"""
ANANTARA SAKTI — CEX Trade Learning Analyzer
v1.0 (2026-08-11) — Extract patterns, configurations & settings from paper trades.

Purpose: turn accumulated R4 paper trades into actionable learning so that when
live trading with real money starts, the patterns/config/settings are already
calibrated. Pure stdlib (psycopg2 + httpx available in daemon env).

Produces:
  1. Per-pair performance (WR, avg win/loss, expectancy, PF) → keep/drop decision
  2. Per-exit-reason analysis (which exits are profitable)
  3. Per-regime analysis (which market regimes generate winners)
  4. Hold-time analysis (optimal hold window)
  5. Signal-strength vs outcome correlation
  6. Config recommendations for live calibration

Runs standalone or via daemon job_cex_learning_report (daily).
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

# v8.7 epoch — strategy upgraded to r8_* paths. Aligned with cex_deep_loop.py.
_DEPLOY_DATE = "2026-08-22 23:00:00"
_MIN_N_DECISION = 5  # min trades per segment before making keep/drop decision
_MIN_N_REPORT = 3    # min trades per segment before reporting


def _get_pg_conn(dbname: str = "anantara"):
    import psycopg2, os
    env_path = Path(os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti"))) / ".env"
    env_vars: dict = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env_vars[k.strip()] = v.strip()
    return psycopg2.connect(
        host=env_vars.get("POSTGRES_HOST", "localhost"),
        port=env_vars.get("POSTGRES_PORT", "5432"),
        dbname=dbname,
        user=env_vars.get("POSTGRES_USER", "anantara"),
        password=env_vars.get("POSTGRES_PASSWORD", ""),
    )


def _fetch_trades() -> list[dict]:
    """Fetch all closed R4 trades since effective start."""
    conn = _get_pg_conn("anantara")
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT pair, is_short, open_date, close_date, close_profit, exit_reason,
                   enter_tag, open_rate, close_rate, stop_loss_pct, leverage
            FROM trades
            WHERE is_open = false
              AND strategy LIKE '%%AnantaraTrendFocused%%'
              AND open_date >= %s
            ORDER BY open_date
        """, (_DEPLOY_DATE,))
        rows = cur.fetchall()
    finally:
        conn.close()
    trades = []
    for r in rows:
        trades.append({
            "pair": r[0], "coin": r[0].split("/")[0],
            "is_short": bool(r[1]),
            "open_date": r[2], "close_date": r[3],
            "pnl": float(r[4]) if r[4] else 0.0,
            "exit_reason": r[5] or "?",
            "enter_tag": r[6] or "?",
            "open_rate": r[7], "close_rate": r[8],
            "sl_pct": r[9], "leverage": r[10],
        })
    return trades


def _compute_stats(trades: list[dict]) -> dict:
    """Compute WR, avg win/loss, expectancy, profit factor, net."""
    if not trades:
        return {"n": 0, "wr": 0, "avg_win": 0, "avg_loss": 0,
                "expectancy": 0, "pf": 0, "net_pct": 0}
    n = len(trades)
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    return {
        "n": n,
        "wr": len(wins) / n,
        "avg_win": avg_win * 100,
        "avg_loss": avg_loss * 100,
        "expectancy": sum(t["pnl"] for t in trades) / n * 100,
        "pf": pf,
        "net_pct": sum(t["pnl"] for t in trades) * 100,
    }


def _hold_hours(t) -> float:
    return (t["close_date"] - t["open_date"]).total_seconds() / 3600


def _load_deep_loop_learning() -> dict:
    """Read current deep-loop guard state; fail open for report generation."""
    import os

    rel = Path("freqtrade_user_data/data/binance/cex_deep_loop.json")
    candidates = []
    if os.environ.get("ANANTARA_DIR"):
        candidates.append(Path(os.environ["ANANTARA_DIR"]) / rel)
    candidates.append(Path.home() / "anantara-sakti" / rel)
    for path in candidates:
        try:
            if path.exists():
                data = json.loads(path.read_text())
                return data if isinstance(data, dict) else {}
        except Exception as exc:
            log.warning(f"load deep-loop learning failed: {exc}")
            return {}
    return {}


# ── Report builders ─────────────────────────────────────────────────────

def _per_pair(trades: list[dict]) -> list[tuple]:
    by_pair = defaultdict(list)
    for t in trades:
        by_pair[t["coin"]].append(t)
    results = []
    for coin, ts in by_pair.items():
        s = _compute_stats(ts)
        results.append((coin, s, ts))
    results.sort(key=lambda x: -x[1]["expectancy"])
    return results


def _per_exit(trades: list[dict]) -> list[tuple]:
    by_exit = defaultdict(list)
    for t in trades:
        by_exit[t["exit_reason"]].append(t)
    results = []
    for reason, ts in by_exit.items():
        results.append((reason, _compute_stats(ts), ts))
    results.sort(key=lambda x: -x[1]["expectancy"])
    return results


def _per_hold_bucket(trades: list[dict]) -> list[tuple]:
    """Bucket by hold time: 0-6h, 6-12h, 12-24h, 24h+."""
    buckets = {"<6h": [], "6-12h": [], "12-24h": [], "24h+": []}
    for t in trades:
        h = _hold_hours(t)
        if h < 6: buckets["<6h"].append(t)
        elif h < 12: buckets["6-12h"].append(t)
        elif h < 24: buckets["12-24h"].append(t)
        else: buckets["24h+"].append(t)
    results = []
    for label, ts in buckets.items():
        results.append((label, _compute_stats(ts), ts))
    return results


def build_report() -> str:
    trades = _fetch_trades()
    total = _compute_stats(trades)
    now = datetime.now(timezone.utc).strftime("%d %b %Y")

    lines = [
        f"🧠 *CEX Learning Report* — {now}",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"*Total*: {total['n']}t | WR={total['wr']:.0%} | Net={total['net_pct']:+.2f}%",
        f"*Expectancy*: {total['expectancy']:+.2f}%/trade | PF={total['pf']:.2f}",
        f"*Avg win*: {total['avg_win']:+.2f}% | *Avg loss*: {total['avg_loss']:+.2f}%",
    ]

    # Per-pair
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("*Per Pair*:")
    for coin, s, ts in _per_pair(trades):
        flag = ""
        if s["n"] >= _MIN_N_DECISION:
            if s["expectancy"] < 0: flag = " ⚠️ CANDIDATE-DROP"
            elif s["expectancy"] > 0.5: flag = " ✅ KEEP"
        bar = "█" * int(s["wr"] * 10)
        lines.append(
            f"  {coin:5s}: {s['n']:2d}t WR={s['wr']:.0%} {bar} "
            f"E={s['expectancy']:+.2f}% PF={s['pf']:.2f}{flag}"
        )

    # Per-exit
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("*Per Exit Reason*:")
    for reason, s, ts in _per_exit(trades):
        lines.append(f"  {reason:18s}: {s['n']:2d}t WR={s['wr']:.0%} E={s['expectancy']:+.2f}%")

    # Per entry-path (v8.7 distinct tags)
    _by_path = defaultdict(list)
    for t in trades:
        _by_path[t.get("enter_tag", "?")].append(t)
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("*Per Entry Path (v8.7)*:")
    _path_sorted = []
    for tag, ts in _by_path.items():
        if tag == "?": continue
        _path_sorted.append((tag, _compute_stats(ts), ts))
    _path_sorted.sort(key=lambda x: -x[1]["expectancy"])
    for tag, s, ts in _path_sorted:
        lines.append(f"  {tag:12s}: {s['n']:2d}t WR={s['wr']:.0%} E={s['expectancy']:+.2f}%")
    if not _path_sorted:
        lines.append("  _Belum ada trade dengan tag r8_* (menunggu trade v8.7)_")

    guard = _load_deep_loop_learning()
    vetoed = guard.get("vetoed") or []
    boosted = guard.get("boosted") or []
    if vetoed or boosted:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("*Deep-loop guard*:")
        if vetoed:
            lines.append(f"  vetoed: {', '.join(vetoed)}")
        if boosted:
            lines.append(f"  boosted: {', '.join(boosted)}")

    # Hold buckets
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("*Per Hold Time*:")
    for label, s, ts in _per_hold_bucket(trades):
        lines.append(f"  {label:8s}: {s['n']:2d}t WR={s['wr']:.0%} E={s['expectancy']:+.2f}%")

    # ── Config recommendations (learning output) ────────────────────────
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("*🔧 Learning → Live Config*:")
    if total["n"] >= 10:
        # Pair keep/drop
        drop = [c for c, s, _ in _per_pair(trades) if s["n"] >= _MIN_N_DECISION and s["expectancy"] < 0]
        strong = [c for c, s, _ in _per_pair(trades) if s["n"] >= _MIN_N_DECISION and s["expectancy"] > 0.5]
        if drop:
            lines.append(f"  ⚠️ Candidate drop: {', '.join(drop)} (expectancy<0, n≥{_MIN_N_DECISION})")
        if strong:
            lines.append(f"  ✅ Strong pairs: {', '.join(strong)} (expectancy>0.5%)")

        # Exit analysis
        exit_sorted = _per_exit(trades)
        if exit_sorted and exit_sorted[0][1]["expectancy"] > 0:
            lines.append(f"  ✅ Best exit: {exit_sorted[0][0]} (E={exit_sorted[0][1]['expectancy']:+.2f}%)")
        worst_exit = exit_sorted[-1] if exit_sorted else None
        if worst_exit and worst_exit[1]["n"] >= 3 and worst_exit[1]["expectancy"] < 0:
            lines.append(f"  ⚠️ Weakest exit: {worst_exit[0]} (E={worst_exit[1]['expectancy']:+.2f}%)")

        # Hold optimization
        hold_sorted = sorted(_per_hold_bucket(trades), key=lambda x: -x[1]["expectancy"])
        if hold_sorted:
            lines.append(f"  ⏱️ Optimal hold: {hold_sorted[0][0]} (E={hold_sorted[0][1]['expectancy']:+.2f}%)")

    else:
        lines.append(f"  _n={total['n']}<10 — accumulating data for config calibration_")

    lines.append("")
    lines.append(f"_Need {max(0, 100-total['n'])} more trades for full bootstrap_")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.WARNING)
    report = build_report()
    print(report)
    # Save to file for record
    out = Path(__file__).parent.parent / "reports"
    out.mkdir(exist_ok=True)
    fname = out / f"cex_learning_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.txt"
    fname.write_text(report)
    print(f"\nSaved: {fname}")
