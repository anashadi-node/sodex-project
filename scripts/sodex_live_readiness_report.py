#!/usr/bin/env python3
"""Generate SoDEX live-readiness roadmap from D0.3 evidence.

Read-only: no orders, no strategy/gate/leverage changes.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "reports/sodex/sodex_forward_reeval_latest.json"
OUT = ROOT / "reports/sodex/SODEX_LIVE_READINESS.md"


def parse_dt(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        x = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return x if x.tzinfo else x.replace(tzinfo=dt.timezone.utc)


def pct(x: Any) -> str:
    return "n/a" if x is None else f"{float(x):+.3f}%"


def money(x: Any) -> str:
    return "n/a" if x is None else f"${float(x):,.3f}"


def readiness_state(data: dict[str, Any]) -> dict[str, Any]:
    archive = data.get("funding_archive") or {}
    tracks = data.get("tracks") or []
    funding = data.get("funding_map") or {}
    canonical = data.get("canonical_normalized_target_distance") or {}
    span = float(archive.get("span_hours") or 0.0)
    all_tracks_pass = bool(tracks) and all(bool(t.get("passed")) for t in tracks)
    funding_ready = span >= 24.0 and archive.get("bad_rows", 0) == 0
    funding_complete = funding.get("verdict") not in (None, "FAIL_CLOSED") and float(funding.get("coverage_pct") or 0.0) >= 95.0
    canonical_valid = bool(canonical.get("valid"))
    live_ready = all_tracks_pass and funding_ready and funding_complete and canonical_valid
    blockers = []
    if not funding_ready:
        blockers.append(f"funding archive warmup {span:.2f}/24h")
    if not all_tracks_pass:
        blockers.append("T1 RISET tracks not passed")
    if not funding_complete:
        blockers.append("funding/borrow evidence incomplete")
    if not canonical_valid:
        blockers.append("canonical normalized gate series invalid")
    return {
        "live_ready": live_ready,
        "funding_ready": funding_ready,
        "all_tracks_pass": all_tracks_pass,
        "funding_complete": funding_complete,
        "canonical_valid": canonical_valid,
        "blockers": blockers,
    }


def warmup_eta(data: dict[str, Any]) -> str:
    archive = data.get("funding_archive") or {}
    span = float(archive.get("span_hours") or 0.0)
    if span >= 24.0:
        return "ready"
    last = parse_dt(archive.get("last_collected_utc"))
    if not last:
        return "unknown"
    return (last + dt.timedelta(hours=24.0 - span)).isoformat()


def render(data: dict[str, Any]) -> str:
    state = readiness_state(data)
    archive = data.get("funding_archive") or {}
    canonical = data.get("canonical_normalized_target_distance") or {}
    funding = data.get("funding_map") or {}
    tracks = data.get("tracks") or []
    lines = [
        "# SoDEX Live Readiness — D0.3 Control Board",
        "",
        f"Generated UTC: {dt.datetime.now(dt.timezone.utc).isoformat()}",
        f"D0.3 run: `{data.get('run_id', 'n/a')}`",
        "",
        "## Verdict",
        f"- Live ready: **{'YES' if state['live_ready'] else 'NO'}**",
        "- Live order/unfreeze: **NO** until all gates pass + explicit user GO-LIVE approval.",
        f"- Current verdict: `{data.get('verdict', 'n/a')}`",
        "",
        "## Current blockers",
    ]
    lines += [f"- {b}" for b in state["blockers"]] or ["- none"]
    lines += [
        "",
        "## Target distance",
        f"- Canonical series: `{canonical.get('series_role')}`",
        f"- Normalized delta 48h: {money(canonical.get('normalized_delta_usd'))}",
        f"- Target 48h: {money(canonical.get('target_48h_usd'))}",
        f"- Distance to target: {pct(canonical.get('distance_to_target_pct'))}",
        "",
        "## Funding evidence",
        f"- Archive rows: `{archive.get('n_rows')}`",
        f"- Unique symbols: `{archive.get('unique_symbols')}`",
        f"- Span hours: `{archive.get('span_hours')}`",
        f"- 24h ETA UTC: `{warmup_eta(data)}`",
        f"- Bad rows: `{archive.get('bad_rows')}`",
        f"- Funding map verdict: `{funding.get('verdict')}`",
        f"- Exact/rate-estimated/missing: `{funding.get('n_exact')}/{funding.get('n_rate_estimated')}/{funding.get('n_missing')}`",
        f"- In-window shorts: `{funding.get('n_in_window', 'n/a')}` (ok `{funding.get('n_ok', 'n/a')}` / missing `{funding.get('n_missing', 'n/a')}`)",
        f"- Pre-archive shorts: `{funding.get('n_pre_archive', 'n/a')}` (archive start `{funding.get('archive_start_utc', 'n/a')}`)",
        "",
        "## RISET tracks",
        "| Track | n | Passed | Excess mean | Cost 2x mean |",
        "|---|---:|---:|---:|---:|",
    ]
    for t in tracks:
        lines.append(
            f"| {t.get('track')} | {t.get('n')} | {t.get('passed')} | {pct(100 * float(t.get('excess_mean') or 0.0))} | {pct(100 * float(t.get('cost_2x_mean') or 0.0))} |"
        )
    lines += [
        "",
        "## Timeline gate menuju real live",
        "1. D0.3 — 24h funding archive: collector + loop stabil, no bad rows.",
        "2. D1/T1 — 30d paper, beta-netral, biaya 1x/2x, funding complete, all tracks pass.",
        "3. D2/T2 — rolling 90d Sharpe >= 1,5; still net positive cost 2x.",
        "4. D3/T3 — mesin kedua terukur, korelasi antar-mesin <= 0,3.",
        "5. D4/T4 — implementation shortfall < 25% di paper/live-small rehearsal.",
        "6. GO-LIVE — hanya setelah human approval; start smallest safe size; monitor 30 menit pertama + daily kill-switch.",
        "",
        "## Safety locks",
        "- No leverage increase.",
        "- No exit/gate/position-sizing change without backtest/OOS evidence + approval.",
        "- No live order before GO-LIVE decision.",
        "- No target downgrade.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    data = json.loads(LATEST.read_text())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(data))
    print(json.dumps({"report": str(OUT), "live_ready": readiness_state(data)["live_ready"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
