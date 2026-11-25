#!/usr/bin/env python3
"""SoDEX spot SELL recovery helper.

This script is deliberately read-only toward SoDEX. It does not place, cancel,
or modify orders. It helps the operator resolve account-level spot SELL blocks
faster by producing a support packet and by recording manual UI SELL evidence.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
DATA = PROJECT / "data"
BLOCK_FILE = DATA / "SODEX_SPOT_SELL_BLOCKED"
VERIFIED_FILE = DATA / "SODEX_SPOT_SELL_VERIFIED"
SUPPORT_PACKET = DATA / "sodex_spot_sell_support_packet.json"
MONITOR_LATEST = DATA / "sodex_monitor_eval" / "latest.json"
MIN_SELL_NOTIONAL_USD = float(os.environ.get("SODEX_SPOT_SELL_MIN_NOTIONAL_USD", "5.0"))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {"raw": data}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        return {"read_error": type(exc).__name__}


def _account_snapshot_valid(monitor: dict[str, Any]) -> bool:
    account = monitor.get("account") if isinstance(monitor.get("account"), dict) else {}
    value = account.get("account_value") if isinstance(account.get("account_value"), dict) else {}
    truth = account.get("position_truth") if isinstance(account.get("position_truth"), dict) else {}
    assets = account.get("assets") if isinstance(account.get("assets"), dict) else {}
    return bool(
        account.get("address")
        and account.get("quality") == "OK"
        and value.get("total_equity_usd") is not None
        and truth.get("verified_flat") is not None
        and isinstance(assets.get("spot"), list)
    )


def _fresh_monitor_snapshot() -> dict[str, Any]:
    """Build a read-only monitor snapshot when latest.json is stale/bad."""
    try:
        from scripts import sodex_monitor_eval

        return sodex_monitor_eval.build_report(no_api=False)
    except Exception as exc:
        return {"fresh_snapshot_error": type(exc).__name__}


def _load_monitor_snapshot() -> dict[str, Any]:
    monitor = _read_json(MONITOR_LATEST)
    if _account_snapshot_valid(monitor):
        return monitor
    fresh = _fresh_monitor_snapshot()
    if _account_snapshot_valid(fresh):
        return fresh
    if fresh.get("fresh_snapshot_error"):
        monitor["fresh_snapshot_error"] = fresh["fresh_snapshot_error"]
    return monitor


def _redact_address(addr: str) -> str:
    if not addr or len(addr) < 16:
        return addr
    return f"{addr[:10]}...{addr[-6:]}"


def _spot_inventory(spot_assets: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for item in spot_assets:
        if not isinstance(item, dict):
            continue
        try:
            value_usd = float(item.get("value_usd") or 0)
        except (TypeError, ValueError):
            value_usd = 0.0
        if value_usd <= 0:
            continue
        rows.append({
            "coin": item.get("coin"),
            "symbol": item.get("symbol"),
            "total": item.get("total"),
            "value_usd": item.get("value_usd"),
        })
    return rows


def _sell_test_plan(inventory: list[dict[str, Any]]) -> dict[str, Any]:
    non_usdc = [
        item for item in inventory
        if str(item.get("coin") or "").upper() not in {"VUSDC", "USDC"}
    ]
    sellable = [
        item for item in non_usdc
        if float(item.get("value_usd") or 0) >= MIN_SELL_NOTIONAL_USD
    ]
    top = max(non_usdc, key=lambda item: float(item.get("value_usd") or 0), default=None)
    if sellable:
        action = "TEST_EXISTING_INVENTORY_SELL"
        reason = "existing non-USDC inventory is above estimated minimum notional"
        steps = [
            f"Use the largest listed candidate in SoDEX UI and submit a SELL >= ${MIN_SELL_NOTIONAL_USD:.2f}.",
            "Capture timestamp, pair, qty, received USDC, order/tx id or screenshot.",
            "Run mark-verified with the captured evidence.",
        ]
    else:
        action = "NO_EXISTING_INVENTORY_ABOVE_MIN_NOTIONAL"
        top_value = float(top.get("value_usd") or 0) if top else 0.0
        reason = (
            f"largest non-USDC inventory is ${top_value:.4f}, below estimated "
            f"${MIN_SELL_NOTIONAL_USD:.2f} spot SELL minimum"
        )
        steps = [
            "Existing dust is likely too small to prove spot SELL capability.",
            "Operator-only fastest path: in SoDEX UI, create a small >=$5.50 spot inventory on the intended pair, then immediately SELL >=$5.00 from UI.",
            "If the BUY succeeds but the SELL fails, send the support packet because that proves account-level spot SELL restriction.",
            "If the SELL succeeds, run mark-verified and keep E1 closed until readiness is green.",
        ]
    return {
        "estimated_min_sell_notional_usd": MIN_SELL_NOTIONAL_USD,
        "action": action,
        "reason": reason,
        "sell_test_candidates": sellable,
        "largest_non_usdc_inventory": top,
        "estimated_manual_proof_minutes": "3-10 if UI SELL is allowed; hours-days if SoDEX account support must remove a restriction",
        "operator_steps": steps,
    }


def build_status() -> dict[str, Any]:
    monitor = _load_monitor_snapshot()
    account = monitor.get("account", {}) if isinstance(monitor.get("account"), dict) else {}
    value = account.get("account_value", {}) if isinstance(account.get("account_value"), dict) else {}
    assets = account.get("assets", {}) if isinstance(account.get("assets"), dict) else {}
    spot_assets = assets.get("spot", []) if isinstance(assets.get("spot"), list) else []
    open_truth = account.get("position_truth", {}) if isinstance(account.get("position_truth"), dict) else {}
    inventory = _spot_inventory(spot_assets)
    sell_test_plan = _sell_test_plan(inventory)

    return {
        "status": "BLOCKED" if BLOCK_FILE.exists() else "VERIFIED" if VERIFIED_FILE.exists() else "UNKNOWN",
        "ts": datetime.now(timezone.utc).isoformat(),
        "event_deadline": "2026-07-25",
        "block_file": {
            "exists": BLOCK_FILE.exists(),
            "path": str(BLOCK_FILE),
            "detail": _read_json(BLOCK_FILE),
        },
        "verified_file": {
            "exists": VERIFIED_FILE.exists(),
            "path": str(VERIFIED_FILE),
            "detail": _read_json(VERIFIED_FILE),
        },
        "account": {
            "address_redacted": _redact_address(str(account.get("address", ""))),
            "total_equity_usd": value.get("total_equity_usd"),
            "spot_vusdc_usd": value.get("spot_vusdc_usd"),
            "open_perps_count": open_truth.get("open_count"),
            "verified_flat": open_truth.get("verified_flat"),
        },
        "spot_inventory": inventory,
        "sell_test_plan": sell_test_plan,
        "manual_recovery_steps": [
            "Open SoDEX UI with the same account.",
            "Follow sell_test_plan; do not use dust if it is below estimated minimum notional.",
            "Capture evidence: timestamp, pair, side=SELL, qty, received USDC, order/tx id or screenshot path.",
            "If SELL succeeds, run this script with mark-verified and the evidence fields.",
            "After verification, remove data/SODEX_SPOT_SELL_BLOCKED only as part of the E1 re-enable checklist.",
        ],
    }


def write_support_packet() -> dict[str, Any]:
    status = build_status()
    packet = {
        "type": "SODEX_SPOT_SELL_ACCOUNT_BLOCK_SUPPORT_PACKET",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "problem": "Spot BUY works but spot SELL appears blocked/rejected for this account; perps can be closed separately.",
        "request": "Please check account-level restrictions, no-withdraw/no-sell flags, KYC/permission state, and spot SELL eligibility.",
        "event_deadline": "2026-07-25",
        "status": status,
        "secrets_policy": "No private key, API key, seed phrase, or token is included.",
    }
    SUPPORT_PACKET.parent.mkdir(parents=True, exist_ok=True)
    SUPPORT_PACKET.write_text(json.dumps(packet, indent=2, sort_keys=True))
    return {"status": "OK", "path": str(SUPPORT_PACKET), "packet": packet}


def mark_verified(args: argparse.Namespace) -> dict[str, Any]:
    evidence = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": "manual_ui_sell_evidence",
        "pair": args.pair,
        "qty": args.qty,
        "received_usdc": args.received_usdc,
        "evidence": args.evidence,
        "operator_note": args.note or "",
        "event_deadline": "2026-07-25",
    }
    missing = [k for k in ("pair", "qty", "received_usdc", "evidence") if not evidence.get(k)]
    if missing:
        return {"status": "ERROR", "reason": f"missing evidence fields: {','.join(missing)}"}
    VERIFIED_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERIFIED_FILE.write_text(json.dumps(evidence, indent=2, sort_keys=True))
    return {
        "status": "OK",
        "verified_file": str(VERIFIED_FILE),
        "next_step": (
            "Review evidence, then remove data/SODEX_SPOT_SELL_BLOCKED and run "
            "`python3 anantara/sodex_twin_engine.py e1-readiness`."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SoDEX spot SELL recovery helper")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("support-packet")
    mark = sub.add_parser("mark-verified")
    mark.add_argument("--pair", required=True)
    mark.add_argument("--qty", required=True)
    mark.add_argument("--received-usdc", required=True)
    mark.add_argument("--evidence", required=True, help="Order/tx id or screenshot path")
    mark.add_argument("--note", default="")
    args = parser.parse_args(argv)

    if args.cmd == "status":
        result = build_status()
    elif args.cmd == "support-packet":
        result = write_support_packet()
    elif args.cmd == "mark-verified":
        result = mark_verified(args)
    else:
        raise AssertionError(args.cmd)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") != "ERROR" else 1


if __name__ == "__main__":
    raise SystemExit(main())
