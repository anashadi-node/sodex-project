#!/usr/bin/env python3
"""Bangun research/trials.csv dari state paper yang benar-benar ada (bukan rekaan).

Setiap arm = satu percobaan yang pernah dijalankan -> wajib masuk registry
(V2 Kill 5: multiple-testing). Read-only terhadap state; menulis satu CSV.
"""
import csv
import json
import statistics as st
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/USER/anantara-sakti")
OUT = ROOT / "research" / "trials.csv"


def unit_for(state_name: str) -> str:
    """Cari unit systemd yang memakai state ini lewat Environment."""
    try:
        units = subprocess.run(
            ["systemctl", "--user", "list-units", "anantara-paper-*", "--all",
             "--no-legend", "--plain"], capture_output=True, text=True, timeout=20
        ).stdout.splitlines()
    except Exception:
        return ""
    for line in units:
        u = line.split()[0]
        env = subprocess.run(["systemctl", "--user", "show", u, "-p", "Environment", "--value"],
                             capture_output=True, text=True, timeout=15).stdout
        if state_name in env:
            return u
    return ""


def main():
    rows = []
    now = datetime.now(timezone.utc)
    for p in sorted((ROOT / "data").glob("paper_test_*_state.json")):
        if ".bak." in p.name:
            continue
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        closed = d.get("closed_trades") or d.get("closed") or []
        if not isinstance(closed, list):
            closed = []
        pcts = [t.get("pnl_pct") for t in closed if isinstance(t.get("pnl_pct"), (int, float))]
        n = d.get("n_trades") if isinstance(d.get("n_trades"), int) else len(closed)
        w = d.get("n_wins") if isinstance(d.get("n_wins"), int) else None
        wr = round(100 * w / n, 1) if (w is not None and n) else ""
        tot = d.get("total_pnl") if isinstance(d.get("total_pnl"), (int, float)) else ""
        exits = [t.get("exit_time") for t in closed if t.get("exit_time")]
        span = ""
        if exits:
            try:
                a = datetime.fromisoformat(min(exits).replace("Z", "+00:00"))
                b = datetime.fromisoformat(max(exits).replace("Z", "+00:00"))
                span = round((b - a).total_seconds() / 86400, 1)
            except Exception:
                pass
        age_d = round((now.timestamp() - p.stat().st_mtime) / 86400, 1)
        rows.append({
            "arm": p.name.replace("paper_test_", "").replace("_state.json", ""),
            "state_file": str(p.relative_to(ROOT)),
            "unit": unit_for(p.name),
            "n_trades": n,
            "win_rate_pct": wr,
            "total_pnl_usd": round(tot, 2) if tot != "" else "",
            "median_pnl_pct": round(st.median(pcts), 4) if pcts else "",
            "first_exit_utc": min(exits) if exits else "",
            "last_exit_utc": max(exits) if exits else "",
            "span_days": span,
            "state_age_days": age_d,
            "status": "running" if age_d < 0.25 else "stopped",
        })
    rows.sort(key=lambda r: (r["n_trades"] or 0), reverse=True)
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="") as f:
        wtr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wtr.writeheader()
        wtr.writerows(rows)
    print(f"ditulis {OUT} — {len(rows)} arm")
    for r in rows[:8]:
        print(f"  {r['arm'][:28]:28s} n={r['n_trades']:>5} wr={r['win_rate_pct']!s:>5} "
              f"pnl={r['total_pnl_usd']!s:>10} status={r['status']}")


if __name__ == "__main__":
    main()
