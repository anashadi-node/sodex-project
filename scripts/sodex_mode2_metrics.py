#!/usr/bin/env python3
"""
ANANTARA SAKTI — SoDEX MODE 2 Live Metrics Collector

Parses daemon logs in real-time to compute:
- Volume per hour/day/week (by symbol + total)
- Maker fill rate (% legs filled as maker)
- Cost estimation (from balance changes)
- Ratio (volume / cost)
- Uptime & cycle success rate

Run: python3 scripts/sodex_mode2_metrics.py
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path(os.environ.get("ANANTARA_DIR",
                    str(Path.home() / "anantara-sakti")))
STATE_FILE = PROJECT_DIR / "data" / "mode2_metrics.json"

# ── Log Parser ───────────────────────────────────────────────────────
def parse_scalp_logs(since: str = "1 hour ago") -> list[dict]:
    """Extract MODE 2 scalp entries from daemon journal."""
    try:
        r = subprocess.run(
            ["journalctl", "--user", "-u", "anantara-daemon",
             "--since", since, "--no-pager", "-o", "cat"],
            capture_output=True, text=True, timeout=10)
    except Exception:
        return []

    entries = []
    pattern = re.compile(
        r"(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}).*?"
        r"scalp\s(\S+):\svol\s\+?\$?([\d.]+)\s*·\s*maker\s(\d+)/(\d+)"
    )

    for line in r.stdout.splitlines():
        m = pattern.search(line)
        if m:
            entries.append({
                "ts": m.group(1),
                "symbol": m.group(2),
                "volume": float(m.group(3)),
                "maker_legs": int(m.group(4)),
                "total_legs": int(m.group(5)),
            })

    return entries


def parse_mode2_cycles(since: str = "1 hour ago") -> list[dict]:
    """Extract MODE 2 cycle starts."""
    try:
        r = subprocess.run(
            ["journalctl", "--user", "-u", "anantara-daemon",
             "--since", since, "--no-pager", "-o", "cat"],
            capture_output=True, text=True, timeout=10)
    except Exception:
        return []

    cycles = []
    for line in r.stdout.splitlines():
        if "scalp cycle: maker mode" in line:
            parts = line.split("·")
            rounds = 0
            for p in parts:
                if "rounds" in p:
                    try:
                        rounds = int(p.strip().split()[0])
                    except ValueError:
                        pass
            cycles.append({
                "ts": line[:19] if len(line) > 19 else "",
                "rounds": rounds,
            })
        elif "scalp cycle: taker mode" in line:
            cycles.append({"ts": line[:19] if len(line) > 19 else "",
                          "rounds": 0, "mode": "taker"})

    return cycles


# ── Metrics Computer ─────────────────────────────────────────────────
def compute_metrics(since: str = "1 hour ago") -> dict:
    """Compute all MODE 2 metrics from logs."""
    entries = parse_scalp_logs(since)
    cycles = parse_mode2_cycles(since)

    if not entries:
        return {"status": "no_data", "since": since}

    # Volume by symbol
    by_symbol = defaultdict(lambda: {"volume": 0.0, "maker_legs": 0, "total_legs": 0})
    total_vol = 0.0
    total_maker = 0
    total_legs = 0

    for e in entries:
        sym = e["symbol"]
        by_symbol[sym]["volume"] += e["volume"]
        by_symbol[sym]["maker_legs"] += e["maker_legs"]
        by_symbol[sym]["total_legs"] += e["total_legs"]
        total_vol += e["volume"]
        total_maker += e["maker_legs"]
        total_legs += e["total_legs"]

    # Rates
    maker_rate = (total_maker / total_legs * 100) if total_legs > 0 else 0
    cycles_count = len(cycles)
    avg_vol_per_cycle = total_vol / cycles_count if cycles_count > 0 else 0

    # Estimate cost (maker: 0.012%, taker: 0.024%)
    maker_vol = total_vol * (total_maker / total_legs) if total_legs > 0 else 0
    taker_vol = total_vol - maker_vol
    est_cost = maker_vol * 0.00012 + taker_vol * 0.00024
    ratio = total_vol / est_cost if est_cost > 0 else float("inf")

    return {
        "since": since,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "cycles": cycles_count,
        "total_volume": round(total_vol, 2),
        "total_cost_est": round(est_cost, 4),
        "ratio": round(ratio, 0),
        "maker_fill_rate": round(maker_rate, 1),
        "total_legs": total_legs,
        "maker_legs": total_maker,
        "by_symbol": {s: {"volume": round(d["volume"], 2),
                          "maker_rate": round(d["maker_legs"]/max(d["total_legs"],1)*100, 1)}
                      for s, d in sorted(by_symbol.items())},
    }


# ── Display ──────────────────────────────────────────────────────────
def display(metrics: dict):
    """Pretty-print metrics."""
    if metrics.get("status") == "no_data":
        print("No MODE 2 data found for this period.")
        return

    print("=" * 55)
    print(f"  MODE 2 LIVE METRICS — {metrics['since']}")
    print("=" * 55)
    print(f"  Cycles        : {metrics['cycles']}")
    print(f"  Total Volume  : ${metrics['total_volume']:,.0f}")
    print(f"  Est. Cost     : ${metrics['total_cost_est']:.4f}")
    print(f"  Ratio         : 1:{metrics['ratio']:,.0f}")
    print(f"  Maker Fill    : {metrics['maker_fill_rate']:.0f}% "
          f"({metrics['maker_legs']}/{metrics['total_legs']})")
    print()
    print(f"  {'Symbol':<12} {'Volume':>10} {'Maker%':>8}")
    print(f"  {'-'*30}")
    for sym, data in metrics.get("by_symbol", {}).items():
        print(f"  {sym:<12} ${data['volume']:>9,.0f} {data['maker_rate']:>7.0f}%")

    # Projection
    hours = 1
    if "hour" in metrics.get("since", ""):
        try:
            hours = int(metrics["since"].split()[0])
        except ValueError:
            pass

    daily_proj = metrics['total_volume'] * 24 / max(hours, 1)
    weekly_proj = daily_proj * 5  # 5 trading days

    print(f"\n  Projections (from {hours}h data):")
    print(f"    Daily  : ${daily_proj:,.0f}")
    print(f"    Weekly : ${weekly_proj:,.0f}")

    # State save
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(metrics, indent=2, default=str))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="MODE 2 Live Metrics")
    ap.add_argument("--since", default="1 hour ago",
                    help="Time window (default: '1 hour ago')")
    ap.add_argument("--watch", action="store_true",
                    help="Continuous monitoring (refresh every 60s)")
    args = ap.parse_args()

    if args.watch:
        print("Watching MODE 2 metrics (Ctrl+C to stop)...")
        try:
            while True:
                os.system("clear")
                metrics = compute_metrics(args.since)
                display(metrics)
                time.sleep(60)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        metrics = compute_metrics(args.since)
        display(metrics)
