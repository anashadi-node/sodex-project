#!/usr/bin/env python3
"""SoDEX deadman switch — context-aware last line of defense.

This script is intentionally narrow: it does not place orders and it does not
kill the daemon directly. It writes a restart signal only when the process is
actually stale. No-fill alone is not enough when target policy is blocking or
the system is deliberately in no-trade/flush mode.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT = Path(os.environ.get("ANANTARA_DIR", str(Path(__file__).resolve().parent.parent)))
DB = PROJECT / "twin_engine.db"
LOG = PROJECT / "logs" / "deadman_switch.log"
RESTART_SIGNAL = PROJECT / "data" / "GUARDIAN_RESTART_SIGNAL"
ENGINE_ALIVE_TS = PROJECT / "data" / "engine_last_alive.json"
ENGINE_LOG = PROJECT / "logs" / "twin_live.log"
PNL_HALT = PROJECT / "data" / "PNL_HALT"
SAFETY_HALT = PROJECT / "data" / "SAFETY_HALT"

MAX_FILL_AGE_MINUTES = 15
MAX_HEARTBEAT_AGE_MINUTES = 8

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}Z] DEADMAN: {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def tg(msg: str) -> None:
    if not (TG_TOKEN and TG_CHAT):
        return
    try:
        data = json.dumps({"chat_id": TG_CHAT, "text": ("DEADMAN\n" + msg)[:4000]}).encode()
        urllib.request.urlopen(
            urllib.request.Request(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                data=data,
                headers={"Content-Type": "application/json"},
            ),
            timeout=10,
        )
    except Exception:
        pass


def daemon_alive() -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-f", "sodex_twin_engine.py"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def get_last_fill_age_minutes() -> float:
    try:
        db = sqlite3.connect(str(DB), timeout=5)
        cur = db.cursor()
        cur.execute("SELECT MAX(ts) FROM fills")
        row = cur.fetchone()
        db.close()
        if not row or not row[0]:
            return 999.0
        last_dt = datetime.fromisoformat(row[0])
        return (datetime.now(timezone.utc) - last_dt).total_seconds() / 60.0
    except Exception:
        return 999.0


def engine_heartbeat_age_minutes() -> float:
    ages: list[float] = []
    try:
        payload = json.loads(ENGINE_ALIVE_TS.read_text())
        ts = float(payload.get("ts", 0) or 0)
        if ts > 0:
            ages.append(max(0.0, (time.time() - ts) / 60.0))
    except Exception:
        pass
    try:
        ages.append(max(0.0, (time.time() - ENGINE_LOG.stat().st_mtime) / 60.0))
    except Exception:
        pass
    return min(ages, default=999.0)


def load_target_policy() -> dict[str, Any]:
    try:
        path = PROJECT / "scripts" / "sodex_target_policy.py"
        spec = importlib.util.spec_from_file_location("sodex_target_policy", path)
        if spec is None or spec.loader is None:
            return {}
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        report_path = PROJECT / "data" / "sodex_monitor_eval" / "latest.json"
        report = json.loads(report_path.read_text()) if report_path.exists() else {}
        return mod.evaluate_target_policy(report)
    except Exception as exc:
        log(f"target policy unavailable: {type(exc).__name__}")
        return {}


def policy_expects_fills(policy: dict[str, Any]) -> bool:
    decision = str(policy.get("decision") or "")
    limits = policy.get("limits") or {}
    if decision.startswith("BLOCK") or decision.startswith("PAUSE"):
        return False
    return float(limits.get("max_e2_hourly_volume_usd") or 0.0) > 0.0


def halt_active() -> bool:
    return PNL_HALT.exists() or SAFETY_HALT.exists()


def evaluate_deadman() -> dict[str, Any]:
    alive = daemon_alive()
    fill_age = get_last_fill_age_minutes()
    hb_age = engine_heartbeat_age_minutes()
    policy = load_target_policy()

    base = {
        "fill_age_minutes": fill_age,
        "heartbeat_age_minutes": hb_age,
        "policy_decision": policy.get("decision"),
    }

    if halt_active():
        return {"decision": "NO_RESTART_HALT_ACTIVE", "restart": False, **base}
    if not alive:
        return {"decision": "NO_RESTART_DAEMON_DEAD", "restart": False, **base}
    if hb_age > MAX_HEARTBEAT_AGE_MINUTES:
        return {"decision": "RESTART_HEARTBEAT_STALE", "restart": True, "type": "heartbeat-stale", **base}
    if fill_age > MAX_FILL_AGE_MINUTES and not policy_expects_fills(policy):
        return {"decision": "NO_RESTART_POLICY_BLOCK", "restart": False, **base}
    if fill_age > MAX_FILL_AGE_MINUTES and policy_expects_fills(policy):
        return {
            "decision": "RESTART_EXPECTED_FILLS_MISSING",
            "restart": True,
            "type": "expected-fills-missing",
            **base,
        }
    return {"decision": "OK", "restart": False, **base}


def write_restart_signal(result: dict[str, Any]) -> None:
    try:
        RESTART_SIGNAL.parent.mkdir(parents=True, exist_ok=True)
        RESTART_SIGNAL.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "source": "deadman_switch",
            "type": result.get("type", "deadman"),
            "fill_age_minutes": round(float(result.get("fill_age_minutes") or 0), 1),
            "heartbeat_age_minutes": round(float(result.get("heartbeat_age_minutes") or 0), 1),
            "policy_decision": result.get("policy_decision"),
            "message": f"Deadman switch: {result.get('decision')}",
        }))
        log(f"RESTART SIGNAL written to {RESTART_SIGNAL}")
    except Exception as exc:
        log(f"FAILED to write restart signal: {exc}")
        tg(f"Deadman failed to write restart signal: {exc}")


def main() -> int:
    result = evaluate_deadman()
    log(
        f"{result['decision']}: fill_age={result['fill_age_minutes']:.0f}m "
        f"hb_age={result['heartbeat_age_minutes']:.1f}m policy={result.get('policy_decision')}"
    )
    if result["restart"]:
        tg(
            f"Deadman triggered: {result['decision']} "
            f"fill_age={result['fill_age_minutes']:.0f}m "
            f"hb_age={result['heartbeat_age_minutes']:.1f}m"
        )
        write_restart_signal(result)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
