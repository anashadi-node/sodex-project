#!/usr/bin/env python3
"""D0.4 — forward-funded T1 re-evaluation + blocker RCA per track.

Read-only. It never changes strategy, gates, exit policy, leverage, or live flags.
It explains, per RISET track, WHY the T1 decision gate still fails:
  - which decision checks fail and by how many bps
  - fee drag between cost 1x and 2x
  - worst per-symbol contributors
  - the binding (closest-to-pass) constraint
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports/sodex"
HARNESS_JSON = REPORT_DIR / "sodex_harness_reeval_20261002.json"
FUNDING_MAP_JSON = REPORT_DIR / "sodex_funding_map_20261002.json"
FORWARD_ARCHIVE = ROOT / "data/sodex_funding/funding_rates_history.jsonl"
OUT_MD = REPORT_DIR / "SODEX_D04_BLOCKER_RCA.md"
OUT_JSON = REPORT_DIR / "SODEX_D04_BLOCKER_RCA.json"

SODEX_FEE_BPS = 8.0
DSR_MIN = 0.95
BPS = 10000.0


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def bps(value: float | None) -> float | None:
    return None if value is None else float(value) * BPS


def failing_checks(result: dict[str, Any], fee_bps: float = SODEX_FEE_BPS) -> list[dict[str, Any]]:
    """List only the decision checks that FAIL, with the bps gap to pass."""
    checks = result.get("checks") or {}
    cs = result.get("cost_stress") or {}
    ci = result.get("ci95") or [None, None]
    dsr = ((result.get("dsr") or {}).get("dsr"))
    excess = result.get("excess_mean")
    excess_bps = bps(excess) if excess is not None else None
    out: list[dict[str, Any]] = []
    if not checks.get("net_pos_1x", False):
        need = fee_bps * 1.0
        gap = None if excess_bps is None else max(0.0, need - excess_bps)
        out.append({"check": "net_pos_1x", "need": f"> {need:.1f} bps gross", "gap_bps": None if gap is None else round(gap, 2)})
    if not checks.get("net_pos_2x", False):
        need = fee_bps * 2.0
        gap = None if excess_bps is None else max(0.0, need - excess_bps)
        out.append({"check": "net_pos_2x", "need": f"> {need:.1f} bps gross", "gap_bps": None if gap is None else round(gap, 2)})
    if not checks.get("ci95_lower_positive", False):
        lo = ci[0]
        gap = None if lo is None else max(0.0, -float(bps(lo) or 0.0))
        out.append({"check": "ci95_lower_positive", "need": "CI95 low > 0", "gap_bps": None if gap is None else round(gap, 2)})
    if not checks.get("dsr_passed", False):
        gap_d = None if dsr is None else max(0.0, DSR_MIN - float(dsr))
        out.append({"check": "dsr_passed", "need": f"DSR >= {DSR_MIN}", "gap_bps": None if gap_d is None else round(gap_d, 4)})
    if not checks.get("beta_neutral", True):
        out.append({"check": "beta_neutral", "need": "beta neutral", "gap_bps": None})
    return out


def fee_drag_bps(result: dict[str, Any]) -> float | None:
    cs = result.get("cost_stress") or {}
    a = (cs.get("1.0") or {}).get("mean")
    b = (cs.get("2.0") or {}).get("mean")
    if a is None or b is None:
        return None
    return round((b - a) * BPS, 2)


def symbol_drag(result: dict[str, Any], top_n: int = 5) -> list[dict[str, Any]]:
    """Worst per-symbol contributors ranked by total contribution (n * mean)."""
    groups = result.get("per_group_t") or {}
    rows = []
    for sym, g in groups.items():
        n = g.get("n") or 0
        mean = g.get("mean")
        if mean is None:
            continue
        rows.append({"symbol": sym, "n": n, "mean_bps": round(mean * BPS, 2), "contrib_bps": round(n * mean * BPS, 2)})
    rows.sort(key=lambda r: r["contrib_bps"])
    return rows[:top_n]


def track_blocker(track: dict[str, Any]) -> dict[str, Any]:
    result = track.get("result") or {}
    failing = failing_checks(result)
    res = {
        "track": track.get("track"),
        "n": track.get("n"),
        "passed": bool((track.get("grade") or {}).get("passed", False)),
        "wr_pct": round((result.get("wr") or 0.0) * 100.0, 2),
        "excess_mean_bps": bps(result.get("excess_mean")),
        "cost_1x_bps": bps(((result.get("cost_stress") or {}).get("1.0") or {}).get("mean")),
        "cost_2x_bps": bps(((result.get("cost_stress") or {}).get("2.0") or {}).get("mean")),
        "fee_drag_bps": fee_drag_bps(result),
        "dsr": (result.get("dsr") or {}).get("dsr"),
        "n_failing_checks": len(failing),
        "failing_checks": failing,
        "worst_symbols": symbol_drag(result),
    }
    for k in ("excess_mean_bps", "cost_1x_bps", "cost_2x_bps"):
        if res[k] is not None:
            res[k] = round(res[k], 2)
    return res


def nearest_track(blockers: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Track closest to passing: fewest failing checks, then smallest gross gap to 2x."""
    cands = [b for b in blockers if b.get("n_failing_checks") is not None]
    if not cands:
        return None

    def key(b: dict[str, Any]) -> tuple[int, float]:
        gap2x = next((c["gap_bps"] for c in b["failing_checks"] if c["check"] == "net_pos_2x" and c["gap_bps"] is not None), 0.0)
        return (b["n_failing_checks"], gap2x)

    return dict(sorted(cands, key=key)[0])


def funding_blocker(funding_map: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict": funding_map.get("verdict"),
        "n_exact": funding_map.get("n_exact", funding_map.get("n_ok")),
        "n_rate_estimated": funding_map.get("n_rate_estimated", 0),
        "n_missing": funding_map.get("n_missing"),
        "coverage_pct": funding_map.get("coverage_pct"),
    }


def forward_archive_state(path: Path = FORWARD_ARCHIVE) -> dict[str, Any]:
    if not path.exists():
        return {"verdict": "MISSING", "n_rows": 0}
    times = []
    symbols = set()
    bad = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if row.get("collected_utc"):
            times.append(str(row["collected_utc"]))
        if row.get("venue_symbol"):
            symbols.add(str(row["venue_symbol"]))
    ready = False
    span = 0.0
    if times:
        a = dt.datetime.fromisoformat(min(times))
        b = dt.datetime.fromisoformat(max(times))
        span = (b - a).total_seconds() / 3600.0
        ready = span >= 24.0
    return {
        "verdict": "READY" if ready else "WARMING_UP",
        "n_rows": len(times),
        "unique_symbols": len(symbols),
        "span_hours": round(span, 3),
        "bad_rows": bad,
    }


def build_rca(harness: dict[str, Any], funding_map: dict[str, Any], archive: dict[str, Any]) -> dict[str, Any]:
    tracks = harness.get("tracks") or []
    blockers = [track_blocker(t) for t in tracks]
    nearest = nearest_track(blockers)
    all_passed = bool(blockers) and all(b["passed"] for b in blockers)
    t1_status = "PASS" if all_passed else "FAIL"
    if t1_status == "FAIL":
        verdict = "T1_FAIL_BLOCKER_RCA_READY" if archive.get("verdict") == "READY" else "T1_FAIL_FORWARD_WARMUP"
    else:
        verdict = "T1_PASS_PENDING_HUMAN_REVIEW"
    return {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "verdict": verdict,
        "t1_status": t1_status,
        "harness_generated_utc": harness.get("generated_utc"),
        "fee_bps": SODEX_FEE_BPS,
        "forward_archive": archive,
        "funding_blocker": funding_blocker(funding_map),
        "tracks": blockers,
        "nearest_to_pass": nearest,
        "safety": {
            "unfreeze_real_money": "NO",
            "build_new_strategy_machine_now": "NO",
            "change_leverage_exit_gate_or_position_sizing": "NO",
            "reason": "D0.4 is read-only RCA; T1 must pass and RISET must confirm before any build.",
        },
    }


def render_md(rca: dict[str, Any]) -> str:
    lines = [
        "# SoDEX D0.4 — Forward-Funded T1 Re-evaluation + Blocker RCA",
        "",
        f"Generated UTC: {rca['generated_utc']}",
        f"Harness run: {rca.get('harness_generated_utc')}",
        f"Fee assumption: {rca['fee_bps']} bps per leg-stress step",
        "",
        "## Verdict",
        f"- T1 status: **{rca['t1_status']}**",
        f"- RCA verdict: `{rca['verdict']}`",
        f"- Forward funding archive: `{rca['forward_archive'].get('verdict')}` "
        f"({rca['forward_archive'].get('span_hours')} h, {rca['forward_archive'].get('n_rows')} rows)",
        f"- Live order/unfreeze: **NO** until T1 passes + explicit GO-LIVE approval",
        "",
        "## Per-track blocker RCA",
        "",
        "| Track | n | WR% | Gross bps | 1x bps | 2x bps | Fee drag bps | DSR | Failing checks |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for b in rca["tracks"]:
        lines.append(
            f"| {b['track']} | {b['n']} | {b['wr_pct']} | "
            f"{_fmt(b['excess_mean_bps'])} | {_fmt(b['cost_1x_bps'])} | {_fmt(b['cost_2x_bps'])} | "
            f"{_fmt(b['fee_drag_bps'])} | {_fmt(b['dsr'], 4)} | {b['n_failing_checks']} |"
        )
    lines += ["", "### Failing checks detail", ""]
    for b in rca["tracks"]:
        lines.append(f"**{b['track']}** (n={b['n']}, passed={b['passed']})")
        if not b["failing_checks"]:
            lines.append("- no failing checks")
        for c in b["failing_checks"]:
            lines.append(f"- `{c['check']}` — need {c['need']}, gap {c['gap_bps']} bps")
        worst = b.get("worst_symbols") or []
        if worst:
            joined = ", ".join(f"{w['symbol']}({w['n']}×{w['mean_bps']}bps)" for w in worst)
            lines.append(f"- worst contributors: {joined}")
        lines.append("")
    near = rca.get("nearest_to_pass")
    lines += ["## Binding constraint", ""]
    if near:
        lines.append(
            f"**{near['track']}** is closest to passing: {near['n_failing_checks']} failing checks, "
            f"gross {_fmt(near['excess_mean_bps'])} bps vs 2× fee {SODEX_FEE_BPS*2:.0f} bps."
        )
        if near.get("failing_checks"):
            first = near["failing_checks"][0]
            lines.append(f"Binding gap: `{first['check']}` — {first['gap_bps']} bps short.")
    else:
        lines.append("No track data available.")
    fb = rca["funding_blocker"]
    lines += [
        "",
        "## Funding/borrow blocker",
        f"- Verdict: `{fb.get('verdict')}`",
        f"- exact/rate-estimated/missing: `{fb.get('n_exact')}/{fb.get('n_rate_estimated')}/{fb.get('n_missing')}`",
        f"- coverage: `{fb.get('coverage_pct')}%`",
        "- Historical 42 SHORT remain fail-closed (no look-ahead imputation from current rates).",
        "",
        "## Safety locks",
        "- No leverage increase.",
        "- No exit/gate/position-sizing change without backtest/OOS evidence + approval.",
        "- No live order before GO-LIVE decision.",
        "- No target downgrade.",
        "",
    ]
    return "\n".join(lines)


def _fmt(value: Any, nd: int = 2) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.{nd}f}"
    except (TypeError, ValueError):
        return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SoDEX D0.4 blocker RCA")
    parser.add_argument("--harness", type=Path, default=HARNESS_JSON)
    parser.add_argument("--funding-map", type=Path, default=FUNDING_MAP_JSON)
    parser.add_argument("--archive", type=Path, default=FORWARD_ARCHIVE)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    args = parser.parse_args(argv)
    harness = read_json(args.harness)
    funding_map = harness.get("funding_map") or read_json(args.funding_map)
    archive = forward_archive_state(args.archive)
    rca = build_rca(harness, funding_map or {}, archive)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(rca, indent=2, ensure_ascii=False, default=str))
    args.out_md.write_text(render_md(rca))
    print(json.dumps({"json": str(args.out_json), "md": str(args.out_md), "verdict": rca["verdict"], "t1_status": rca["t1_status"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
