#!/usr/bin/env python3
"""D0.3 SoDEX forward evidence re-evaluation loop.

Read-only loop: collect current forward evidence, re-run the RISET harness, append
an auditable loop registry, and keep T1 fail-closed until empirical gates pass.
No orders, no live flag changes, no leverage/exit/gate changes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports/sodex"
FUNDING_ARCHIVE = ROOT / "data/sodex_funding/funding_rates_history.jsonl"
HARNESS_JSON = REPORT_DIR / "sodex_harness_reeval_20261002.json"
LOOP_REGISTRY = REPORT_DIR / "sodex_forward_reeval_loop.jsonl"
LOOP_LATEST = REPORT_DIR / "sodex_forward_reeval_latest.json"
HARNESS_SCRIPT = ROOT / "scripts/sodex_harness_reeval.py"
COLLECTOR_SCRIPT = ROOT / "scripts/sodex_funding_rate_collector.py"
LIVE_READINESS_SCRIPT = ROOT / "scripts/sodex_live_readiness_report.py"
D04_RCA_SCRIPT = ROOT / "scripts/sodex_d04_blocker_rca.py"
D05_AUDIT_SCRIPT = ROOT / "scripts/sodex_d05_edge_leak_audit.py"
D05B_SCRIPT = ROOT / "scripts/sodex_d05b_exit_geometry.py"
LANE_PROJECTION_SCRIPT = ROOT / "scripts/sodex_lane_target_projection.py"
LANE_PROJECTION_REPORT = ROOT / "reports/sodex/sodex_lane_target_projection.json"


def parse_dt(value: str) -> dt.datetime:
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def funding_archive_summary(path: Path = FUNDING_ARCHIVE, min_span_hours: float = 24.0) -> dict[str, Any]:
    if not path.exists():
        return {
            "path": str(path),
            "verdict": "FAIL_CLOSED",
            "reason": "funding archive missing",
            "n_rows": 0,
            "unique_symbols": 0,
            "span_hours": 0.0,
        }
    timestamps: list[dt.datetime] = []
    symbols: set[str] = set()
    bad_rows = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            ts_raw = row.get("collected_utc") or row.get("funding_time_utc")
            if ts_raw:
                timestamps.append(parse_dt(ts_raw))
            if row.get("symbol"):
                symbols.add(str(row["symbol"]).upper())
        except Exception:
            bad_rows += 1
    if not timestamps:
        return {
            "path": str(path),
            "verdict": "FAIL_CLOSED",
            "reason": "funding archive has no parseable timestamps",
            "n_rows": 0,
            "unique_symbols": len(symbols),
            "span_hours": 0.0,
            "bad_rows": bad_rows,
        }
    first, last = min(timestamps), max(timestamps)
    span_hours = max(0.0, (last - first).total_seconds() / 3600.0)
    verdict = "READY" if span_hours >= min_span_hours else "WARMING_UP"
    return {
        "path": str(path),
        "verdict": verdict,
        "reason": "OK" if verdict == "READY" else f"need >= {min_span_hours:.0f}h forward funding archive",
        "n_rows": len(timestamps),
        "unique_symbols": len(symbols),
        "first_collected_utc": first.isoformat(),
        "last_collected_utc": last.isoformat(),
        "span_hours": span_hours,
        "bad_rows": bad_rows,
    }


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
        return out if math.isfinite(out) else None
    except Exception:
        return None


def track_snapshot(harness: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in harness.get("tracks") or []:
        result = item.get("result") or {}
        grade = item.get("grade") or {}
        rows.append({
            "track": item.get("track"),
            "n": item.get("n"),
            "passed": bool(grade.get("passed")),
            "excess_mean": _safe_float(result.get("excess_mean")),
            "cost_1x_mean": _safe_float((result.get("cost_stress") or {}).get("1.0", {}).get("mean")),
            "cost_2x_mean": _safe_float((result.get("cost_stress") or {}).get("2.0", {}).get("mean")),
            "ci95": result.get("ci95"),
            "reasons": grade.get("reasons") or [],
        })
    return rows


def build_loop_record(
    harness: dict[str, Any],
    archive: dict[str, Any],
    harness_exit_code: int,
    harness_stdout: str = "",
    harness_stderr: str = "",
    collector_exit_code: int | None = None,
    collector_stdout: str = "",
    collector_stderr: str = "",
) -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc)
    tracks = track_snapshot(harness)
    any_track_passed = any(t["passed"] for t in tracks)
    if harness_exit_code != 0:
        verdict = "FAIL_CLOSED_HARNESS_ERROR"
    elif archive.get("verdict") != "READY":
        verdict = "FORWARD_EVIDENCE_WARMUP"
    elif any_track_passed and str((harness.get("decision") or {}).get("t1_status", "")).upper().startswith("PASS"):
        verdict = "T1_CANDIDATE_NEEDS_RISET_CONFIRMATION"
    else:
        verdict = "T1_FAIL_FORWARD_MONITOR"

    nd = harness.get("canonical_normalized_target_distance") or {}
    fm = harness.get("funding_map") or {}
    return {
        "run_id": now.strftime("%Y%m%dT%H%M%SZ"),
        "generated_utc": now.isoformat(),
        "verdict": verdict,
        "harness_exit_code": harness_exit_code,
        "collector_exit_code": collector_exit_code,
        "harness_generated_utc": harness.get("generated_utc"),
        "funding_archive": archive,
        "canonical_normalized_target_distance": {
            "valid": bool(nd.get("valid")),
            "distance_to_target_pct": _safe_float(nd.get("distance_to_target_pct")),
            "normalized_delta_usd": _safe_float(nd.get("normalized_delta_usd")),
            "target_48h_usd": _safe_float(nd.get("target_48h_usd")),
            "series_role": nd.get("series_role"),
        },
        "funding_map": {
            "verdict": fm.get("verdict"),
            "n_exact": fm.get("n_exact"),
            "n_rate_estimated": fm.get("n_rate_estimated"),
            "n_missing": fm.get("n_missing"),
            "coverage_pct": _safe_float(fm.get("coverage_pct")),
        },
        "tracks": tracks,
        "registry_count_this_run": harness.get("registry_count"),
        "safety": {
            "unfreeze_real_money": "NO",
            "build_new_strategy_machine_now": "NO",
            "change_leverage_exit_gate_or_position_sizing": "NO",
            "reason": "D0.3 is read-only evidence loop until T1 passes and RISET confirms.",
        },
        "next_action": "keep collecting forward evidence; re-run this loop on timer",
        "harness_stdout_tail": harness_stdout[-1200:],
        "harness_stderr_tail": harness_stderr[-1200:],
        "collector_stdout_tail": collector_stdout[-1200:],
        "collector_stderr_tail": collector_stderr[-1200:],
    }


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def run_script(script: Path, timeout_s: int) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_collector(timeout_s: int = 120) -> tuple[int, str, str]:
    return run_script(COLLECTOR_SCRIPT, timeout_s)


def run_harness(timeout_s: int = 420) -> tuple[int, str, str]:
    return run_script(HARNESS_SCRIPT, timeout_s)


def run_loop(run_harness_first: bool = True) -> dict[str, Any]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    collector_exit_code, collector_stdout, collector_stderr = None, "", ""
    exit_code, stdout, stderr = 0, "", ""
    if run_harness_first:
        try:
            collector_exit_code, collector_stdout, collector_stderr = run_collector()
        except subprocess.TimeoutExpired as exc:
            collector_exit_code = 124
            raw_stdout = exc.stdout or ""
            raw_stderr = exc.stderr or ""
            collector_stdout = raw_stdout.decode() if isinstance(raw_stdout, bytes) else raw_stdout
            collector_stderr = raw_stderr.decode() if isinstance(raw_stderr, bytes) else raw_stderr
            collector_stderr += "\nCOLLECTOR_TIMEOUT"
        try:
            exit_code, stdout, stderr = run_harness()
        except subprocess.TimeoutExpired as exc:
            exit_code = 124
            raw_stdout = exc.stdout or ""
            raw_stderr = exc.stderr or ""
            stdout = raw_stdout.decode() if isinstance(raw_stdout, bytes) else raw_stdout
            stderr = raw_stderr.decode() if isinstance(raw_stderr, bytes) else raw_stderr
            stderr += "\nHARNESS_TIMEOUT"
    harness = read_json(HARNESS_JSON) if exit_code == 0 else {}
    archive = funding_archive_summary()
    record = build_loop_record(
        harness,
        archive,
        exit_code,
        stdout,
        stderr,
        collector_exit_code,
        collector_stdout,
        collector_stderr,
    )
    if LIVE_READINESS_SCRIPT.exists():
        subprocess.run([sys.executable, str(LIVE_READINESS_SCRIPT)], cwd=str(ROOT), text=True, capture_output=True, timeout=60, check=False)
    if D04_RCA_SCRIPT.exists():
        subprocess.run([sys.executable, str(D04_RCA_SCRIPT)], cwd=str(ROOT), text=True, capture_output=True, timeout=60, check=False)
    if D05_AUDIT_SCRIPT.exists():
        subprocess.run([sys.executable, str(D05_AUDIT_SCRIPT)], cwd=str(ROOT), text=True, capture_output=True, timeout=300, check=False)
    if D05B_SCRIPT.exists():
        subprocess.run([sys.executable, str(D05B_SCRIPT)], cwd=str(ROOT), text=True, capture_output=True, timeout=300, check=False)
    # D0.6 bridge: paper-lane realised PnL -> distance to the 0,8%/48h wallet target.
    # Disjoint 48h buckets only -- a per-trade rolling window inflated the median to
    # +2,48% (3,1x target) versus +1,41% disjoint, by re-counting the same trades.
    if LANE_PROJECTION_SCRIPT.exists():
        proc = subprocess.run([sys.executable, str(LANE_PROJECTION_SCRIPT)], cwd=str(ROOT), text=True,
                              capture_output=True, timeout=300, check=False)
        # Reference the report file; a stdout tail truncates and becomes unparseable JSON.
        record["lane_target_projection"] = {
            "returncode": proc.returncode,
            "report": str(LANE_PROJECTION_REPORT),
            "report_exists": LANE_PROJECTION_REPORT.exists(),
        }
    # Persist AFTER the downstream steps so their results are actually in the record.
    append_jsonl(LOOP_REGISTRY, record)
    LOOP_LATEST.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str))
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run SoDEX D0.3 forward evidence re-evaluation loop")
    parser.add_argument("--no-run-harness", action="store_true", help="Summarize latest harness JSON without rerunning it")
    args = parser.parse_args(argv)
    record = run_loop(run_harness_first=not args.no_run_harness)
    print(json.dumps({
        "latest": str(LOOP_LATEST),
        "registry": str(LOOP_REGISTRY),
        "verdict": record["verdict"],
        "funding_archive": record["funding_archive"],
        "safety": record["safety"],
    }, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
