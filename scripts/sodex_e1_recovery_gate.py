#!/usr/bin/env python3
"""E1 W18 recovery gate.

No exchange orders are placed here. The script turns the SoDEX SELL proof,
global halt, and E1 readiness state into a concrete recovery phase.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))
DATA = PROJECT / "data"
SELL_BLOCK = DATA / "SODEX_SPOT_SELL_BLOCKED"
SELL_VERIFIED = DATA / "SODEX_SPOT_SELL_VERIFIED"
SAFETY_HALT = DATA / "SAFETY_HALT"
PNL_HALT = DATA / "PNL_HALT"
OPERATOR_CARD = DATA / "sodex_e1_recovery_operator_card.md"
ARCHIVE_DIR = DATA / "recovery_archive"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {"raw": data}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        return {"read_error": type(exc).__name__}


def _e1_readiness() -> dict[str, Any]:
    from anantara import sodex_twin_engine as twin

    old_paths = (
        twin.SAFETY_HALT_FILE,
        twin.PNL_HALT_FILE,
        twin.SPOT_SELL_BLOCK_FILE,
        twin.SPOT_SELL_VERIFIED_FILE,
    )
    try:
        twin.SAFETY_HALT_FILE = SAFETY_HALT
        twin.PNL_HALT_FILE = PNL_HALT
        twin.SPOT_SELL_BLOCK_FILE = SELL_BLOCK
        twin.SPOT_SELL_VERIFIED_FILE = SELL_VERIFIED
        return twin.e1_w18_readiness(twin.Config())
    finally:
        (
            twin.SAFETY_HALT_FILE,
            twin.PNL_HALT_FILE,
            twin.SPOT_SELL_BLOCK_FILE,
            twin.SPOT_SELL_VERIFIED_FILE,
        ) = old_paths


def _sell_status() -> dict[str, Any]:
    from scripts import sodex_spot_sell_recovery as recovery

    old_paths = (
        recovery.BLOCK_FILE,
        recovery.VERIFIED_FILE,
    )
    try:
        recovery.BLOCK_FILE = SELL_BLOCK
        recovery.VERIFIED_FILE = SELL_VERIFIED
        return recovery.build_status()
    finally:
        recovery.BLOCK_FILE, recovery.VERIFIED_FILE = old_paths


def build_status() -> dict[str, Any]:
    sell = _sell_status()
    readiness = _e1_readiness()
    sell_plan = sell.get("sell_test_plan", {}) if isinstance(sell.get("sell_test_plan"), dict) else {}
    blockers = readiness.get("blockers", []) or []

    if not SELL_VERIFIED.exists():
        if sell_plan.get("action") == "NO_EXISTING_INVENTORY_ABOVE_MIN_NOTIONAL":
            phase = "PHASE_0_NEEDS_SELL_TEST_INVENTORY"
            next_action = "Operator must create >=$5.50 spot inventory in UI, then immediately SELL >=$5.00 in UI."
        else:
            phase = "PHASE_1_NEEDS_MANUAL_SELL_PROOF"
            next_action = "Operator must perform tiny manual/UI spot SELL and record evidence with mark-verified."
    elif SELL_BLOCK.exists():
        phase = "PHASE_2_READY_TO_CLEAR_SELL_BLOCK"
        next_action = "Run clear-sell-block --yes, then re-run e1-readiness."
    elif SAFETY_HALT.exists() or PNL_HALT.exists():
        phase = "PHASE_3_SELL_VERIFIED_WAITING_GLOBAL_HALT_REVIEW"
        next_action = "Review halt reason and clear only after runtime is flat and no unmanaged opener remains."
    elif readiness.get("ready_for_live"):
        phase = "PHASE_4_E1_W18_READY_FOR_STAGED_REENABLE"
        next_action = "Start staged E1 W18 re-enable checklist with tiny caps, not full-size immediately."
    else:
        phase = "PHASE_BLOCKED_OTHER"
        next_action = "Review readiness blockers."

    return {
        "status": "OK",
        "ts": datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "next_action": next_action,
        "event_deadline": "2026-07-25",
        "sell_verified": SELL_VERIFIED.exists(),
        "sell_block_exists": SELL_BLOCK.exists(),
        "global_halt_exists": SAFETY_HALT.exists() or PNL_HALT.exists(),
        "readiness_blockers": blockers,
        "sell_test_plan": sell_plan,
        "e1_w18_readiness": readiness,
    }


def write_operator_card() -> dict[str, Any]:
    status = build_status()
    sell_plan = status.get("sell_test_plan", {})
    lines = [
        "# SoDEX E1 W18 Recovery Operator Card",
        "",
        f"Generated: {status['ts']}",
        f"Event deadline: {status['event_deadline']}",
        f"Current phase: {status['phase']}",
        "",
        "## Next Action",
        "",
        str(status["next_action"]),
        "",
        "## SELL Proof Plan",
        "",
        f"- Estimated min sell notional: ${sell_plan.get('estimated_min_sell_notional_usd', 5.0)}",
        f"- Current action: {sell_plan.get('action')}",
        f"- Reason: {sell_plan.get('reason')}",
        "",
        "## Operator UI Steps",
        "",
    ]
    for step in sell_plan.get("operator_steps", []) or []:
        lines.append(f"- {step}")
    lines.extend([
        "",
        "## After Successful UI SELL",
        "",
        "Run:",
        "",
        "```bash",
        "python3 scripts/sodex_spot_sell_recovery.py mark-verified \\",
        "  --pair \"PAIR/USDC\" \\",
        "  --qty \"QTY\" \\",
        "  --received-usdc \"USDC_RECEIVED\" \\",
        "  --evidence \"screenshot-or-order-id\"",
        "```",
        "",
        "Then run:",
        "",
        "```bash",
        "python3 scripts/sodex_e1_recovery_gate.py status",
        "```",
    ])
    OPERATOR_CARD.parent.mkdir(parents=True, exist_ok=True)
    OPERATOR_CARD.write_text("\n".join(lines) + "\n")
    return {"status": "OK", "path": str(OPERATOR_CARD), "phase": status["phase"]}


def clear_sell_block(confirm: bool) -> dict[str, Any]:
    if not confirm:
        return {"status": "ERROR", "reason": "missing --yes"}
    if not SELL_VERIFIED.exists():
        return {"status": "ERROR", "reason": "cannot clear block without SODEX_SPOT_SELL_VERIFIED"}
    if not SELL_BLOCK.exists():
        return {"status": "OK", "reason": "sell block already absent"}
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archived = ARCHIVE_DIR / f"SODEX_SPOT_SELL_BLOCKED.{ts}.json"
    os.replace(SELL_BLOCK, archived)
    return {
        "status": "OK",
        "archived_to": str(archived),
        "next_step": "Run python3 anantara/sodex_twin_engine.py e1-readiness",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SoDEX E1 W18 recovery gate")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("operator-card")
    clear = sub.add_parser("clear-sell-block")
    clear.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd == "status":
        result = build_status()
    elif args.cmd == "operator-card":
        result = write_operator_card()
    elif args.cmd == "clear-sell-block":
        result = clear_sell_block(args.yes)
    else:
        raise AssertionError(args.cmd)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") != "ERROR" else 1


if __name__ == "__main__":
    raise SystemExit(main())
