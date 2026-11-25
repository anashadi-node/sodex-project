#!/usr/bin/env python3
"""Audit SoDEX live-order surfaces.

Read-only static check: finds Python files that can call `bin/sodex orders place`
and verifies each known live surface has a fail-closed guard marker.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (PROJECT / "anantara", PROJECT / "scripts")
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache"}
# The auditor itself contains the detection patterns as literals; never self-audit.
EXCLUDE_FILES = {"scripts/sodex_order_surface_audit.py"}

GUARD_MARKERS: dict[str, list[str]] = {
    "anantara/anantara_daemon.py": [
        "sf.halt_active()",
        "SoDEX farm: SAFETY_HALT/PNL_HALT active",
        "SoDEX scalp: SAFETY_HALT/PNL_HALT active",
    ],
    "anantara/sodex_farming.py": [
        "_halt_blocks_cli",
        "SAFETY_HALT_FILE",
        "PNL_HALT_FILE",
    ],
    "anantara/sodex_directional.py": [
        "sf.cli(",
        "sf.open_positions",
    ],
    "scripts/sodex_spot_daemon.py": [
        "_global_halt_preflight",
        "_spot_sell_capability_preflight",
        "BLOCKED_GLOBAL_HALT",
    ],
    "anantara/sodex_autofarm.py": [
        "live_order_blocked",
        "SPOT_SELL_BLOCK_FILE",
        "LIVE_ORDER_BLOCKED_",
    ],
    "scripts/sodex_micro_pilot.py": [
        "halt_active()",
        "PNL_HALT",
        "safety_halt_active_order_block",
    ],
    "scripts/realwide_micro_live.py": [
        "KILL_FILE",
        "kill_check",
        "macro_btc_long_blocked",
    ],
    "anantara/radical_scanner.py": [
        "live_order_blocked",
        "deprecated executor disabled",
    ],
    "anantara/sodex_twin_engine.py": [
        "CONFIRM_LIVE",
        "write_safety_halt",
        "e1_spot_capability_block_reason",
        "SPOT_SELL_VERIFIED_FILE",
    ],
    "scripts/spcx_tournament.py": [
        "live_order_blocked",
        "TOURNAMENT_DEADLINE_PASSED",
        "SAFETY_HALT_FILE",
    ],
    "scripts/sodex_perps_short_live_test.py": [
        "PERPS_SHORT_KILL",
        "KILL.exists()",
        "DRY default",
        "--live",
    ],
    "scripts/sodex_spot_live_test.py": [
        "SPOT_LIVE_KILL",
        "KILL.exists()",
        "DRY by default",
        "--live",
    ],
    "scripts/sodex_auto_trader.py": [
        "AUTOTRADER_KILL",
        "KILL.exists()",
        "--dry-run",
        "halted",
    ],
    "scripts/sodex_hype_maker.py": [
        "HYPEMAKER_KILL",
        "KILL.exists()",
        "--dry",
        "halted",
    ],
    "scripts/sodex_trend_rider.py": [
        "TREND_RIDER_KILL",
        "KILL_FILE.exists()",
        "--dry-run",
        "TR_MAX_POS",
    ],
    "scripts/sodex_volume_churn.py": [
        "CHURN_KILL",
        "KILL_FILE.exists()",
        "LOSS_CAP",
        "LIFETIME_CAP",
    ],
    "scripts/spot_liquidator.py": [
        "LIQ_DRY",                    # dry-run default: menembak butuh keputusan GO
        "fail-closed",                # harga tak terbaca → tidak menjual buta
        "BTC_THRESHOLD",              # pemicu bersyarat (bukan jual sembarangan)
    ],
    "scripts/sodex_maker_order.py": [
        # Entry/exit maker-first: post-only (gtx) + fallback taker terkendali.
        # Tidak punya halt-check sendiri — ia HANYA dipanggil lane yang sudah
        # melewati guard (realwide_micro_live: portfolio_guard + fail_closed).
        "--tif", "gtx",
        "allow_taker_fallback",
        "max_slip_pct",
    ],
    "scripts/stop_guard.py": [
        "--reduce-only",
        "TIDAK PERNAH membuka posisi",
        "SG_DRY",
    ],
    # Skrip riset Mode A (jalur GO 01-Des): order surface terdaftar, guard fail-closed
    # di file arming yang harus dibuat user + CONFIRM_LIVE + kill switch + --live.
    "scripts/research/mode_a_20261026/mode_a_live.py": [
        "LIVE_ARMED.json",
        "CONFIRM_LIVE",
        "KILL switch aktif",
        "dry-run default",
        "--live",
    ],
    "scripts/research/mode_a_20261026/lev_20261026/perp_exec.py": [
        "LIVE_ARMED.json",
        "CONFIRM_LIVE",
        "receipt selftest",
        "--live",
    ],
    "scripts/research/mode_a_20261026/lev_20261026/probe_live_micro.py": [
        "LIVE_ARMED_PROBE.json",
        "Refuse(",
        "kedaluwarsa",
        "HARD_CAP",
    ],
}

DEPRECATED_DISABLED_MARKERS: dict[str, list[str]] = {
    "anantara/sodex_spot_farm.py": [
        "deprecated executor disabled",
        "SODEX_ALLOW_DEPRECATED_SPOT_EXECUTOR",
    ],
    "anantara/sodex_wide_farm.py": [
        "deprecated executor disabled",
        "SODEX_ALLOW_DEPRECATED_SPOT_EXECUTOR",
    ],
}


def _rel(path: Path) -> str:
    return str(path.relative_to(PROJECT))


def iter_python_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if EXCLUDE_PARTS.intersection(path.parts):
                continue
            files.append(path)
    return sorted(files)


def has_order_place_surface(source: str) -> bool:
    patterns = [
        r"\[\s*(?:SODEX_BIN|[^,\]]*bin/sodex[^,\]]*)\s*,\s*['\"]orders['\"]\s*,\s*['\"]place['\"]",
        r"\[\s*['\"]orders['\"]\s*,\s*['\"]place['\"]\s*,\s*['\"](?:spot|perps)['\"]",
        r"cli\(\s*\[\s*['\"]orders['\"]\s*,\s*['\"]place['\"]\s*,\s*['\"](?:spot|perps)['\"]",
        # call patterns used by other live surfaces, e.g.:
        #   _sodex("orders", "place", "perps", ...)
        #   _cmd(SODEX, "orders", "place", "perps", ...)
        #   subprocess.run([SODEX, "orders", "place", "perps", ...)
        r"['\"]orders['\"]\s*,\s*['\"]place['\"]\s*,\s*['\"](?:spot|perps)['\"]",
    ]
    # Ignore pure docstring/comment mentions ("... orders place perps ...").
    for m in re.finditer(patterns[-1], source):
        before = source[max(0, m.start() - 80):m.start()]
        # a real call has an opening paren or bracket (possibly with args) before it
        if ("(" in before or "[" in before) and "def " not in before.split("\n")[-1]:
            return True
    return any(re.search(pattern, source, re.DOTALL) for pattern in patterns[:-1])


def classify(path: Path) -> dict[str, Any] | None:
    source = path.read_text(encoding="utf-8", errors="ignore")
    rel = _rel(path)
    if rel in EXCLUDE_FILES:
        return None
    if not has_order_place_surface(source):
        return None
    if rel in GUARD_MARKERS:
        missing = [marker for marker in GUARD_MARKERS[rel] if marker not in source]
        return {
            "file": rel,
            "status": "GUARDED" if not missing else "BROKEN_GUARD",
            "missing_markers": missing,
        }
    if rel in DEPRECATED_DISABLED_MARKERS:
        missing = [marker for marker in DEPRECATED_DISABLED_MARKERS[rel] if marker not in source]
        return {
            "file": rel,
            "status": "DEPRECATED_DISABLED" if not missing else "BROKEN_DEPRECATED_GUARD",
            "missing_markers": missing,
        }
    return {
        "file": rel,
        "status": "UNREGISTERED_ORDER_SURFACE",
        "missing_markers": ["register guard markers or remove direct order placement"],
    }


def build_report() -> dict[str, Any]:
    rows = [row for path in iter_python_files() if (row := classify(path))]
    bad = [
        row for row in rows
        if row["status"] in {
            "BROKEN_GUARD",
            "BROKEN_DEPRECATED_GUARD",
            "UNREGISTERED_ORDER_SURFACE",
        }
    ]
    return {
        "status": "FAIL" if bad else "OK",
        "surface_count": len(rows),
        "bad_count": len(bad),
        "surfaces": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit SoDEX live-order surfaces")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = build_report()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"SoDEX order surface audit: {report['status']} ({report['bad_count']} bad / {report['surface_count']} surfaces)")
        for row in report["surfaces"]:
            print(f"- {row['status']}: {row['file']}")
            if row.get("missing_markers"):
                print(f"  missing: {', '.join(row['missing_markers'])}")
    return 0 if report["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
