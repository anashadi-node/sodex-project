#!/usr/bin/env python3
"""
ANANTARA SAKTI — SoDEX SPOT Autofarm Daemon Wrapper
====================================================
Dipanggil oleh anantara_daemon.py via subprocess setiap 10 menit.
Handles: Telegram alerts, state sync, kill-switch check.

GAP 8 FIX: Integrates autofarm into daemon ecosystem.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ALERT_FILE = Path.home() / ".local/share/anantara/sodex_spot_alert.json"
STATE_FILE = Path.home() / ".local/share/anantara/sodex_spot_state.json"
KILL_FILE = Path.home() / ".local/share/anantara/sodex_spot_kill"
AUTOFARM_LOCK_FILE = Path.home() / ".local/share/anantara/sodex_autofarm.lock"
PROJECT_DIR = Path(__file__).resolve().parent.parent
EVENT_STATUS_FILE = PROJECT_DIR / "data" / "sodex" / "research" / "autonomous_status.json"
SAFETY_HALT_FILE = PROJECT_DIR / "data" / "SAFETY_HALT"
PNL_HALT_FILE = PROJECT_DIR / "data" / "PNL_HALT"
SPOT_SELL_BLOCK_FILE = PROJECT_DIR / "data" / "SODEX_SPOT_SELL_BLOCKED"
SPOT_SELL_VERIFIED_FILE = PROJECT_DIR / "data" / "SODEX_SPOT_SELL_VERIFIED"
EVENT_STATUS_MAX_AGE_S = int(os.environ.get("SODEX_EVENT_STATUS_MAX_AGE_S", "180"))
POLICY_STATUS_MAX_AGE_S = int(os.environ.get("SODEX_POLICY_STATUS_MAX_AGE_S", "300"))
DEFAULT_CAPITAL = os.environ.get("SODEX_SPOT_DAEMON_CAPITAL", "10")
RUN_TIMEOUT_S = int(os.environ.get("SODEX_SPOT_DAEMON_TIMEOUT", "720"))
LIVE_ROUTE = "SPOT_LONG"

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from anantara.sodex_event_shock_guard import enrich_event_route_policy  # noqa: E402


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
        return
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _backup_corrupt_json_file(path: Path) -> Path | None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.corrupt-{ts}.bak")
    try:
        os.replace(path, backup)
    except OSError:
        return None
    return backup


def _read_json_file(path: Path, *, backup_corrupt: bool = False) -> tuple[dict | None, str | None]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return None, "MISSING"
    except json.JSONDecodeError as exc:
        backup = _backup_corrupt_json_file(path) if backup_corrupt else None
        detail = f"JSONDecodeError:{exc.msg}"
        if backup is not None:
            detail += f":backup={backup.name}"
        return None, detail
    except Exception as exc:
        return None, type(exc).__name__
    if not isinstance(data, dict):
        return None, f"INVALID_ROOT_{type(data).__name__}"
    return data, None


def is_killed() -> bool:
    return KILL_FILE.exists()


def send_alert(message: str):
    """Write alert to file for daemon to pick up and send via Telegram."""
    _atomic_write_text(ALERT_FILE, json.dumps({
        "message": message,
        "ts": datetime.now(timezone.utc).isoformat(),
    }))


def clear_alert():
    if ALERT_FILE.exists():
        ALERT_FILE.unlink()


def _write_state(state: dict):
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    _atomic_write_text(STATE_FILE, json.dumps(state, indent=2))


def _record_wrapper_failure(state: dict, reason: str | None) -> dict:
    """Persist execution failures that happen before autofarm can update governor."""
    state = dict(state)
    state["consecutive_losses"] = int(state.get("consecutive_losses", 0) or 0) + 1
    state["last_error"] = reason or "UNKNOWN"
    _write_state(state)
    return state


def _global_halt_preflight() -> tuple[bool, str | None, dict]:
    active = [p for p in (SAFETY_HALT_FILE, PNL_HALT_FILE) if p.exists()]
    if not active:
        return True, None, {}
    detail = {}
    try:
        detail = json.loads(active[0].read_text())
    except Exception:
        detail = {"path": str(active[0])}
    return False, f"GLOBAL_HALT_{active[0].name}", detail


def _spot_sell_capability_preflight() -> tuple[bool, str | None, dict]:
    if os.environ.get("SODEX_SPOT_SELL_FORCE_ALLOW") == "1":
        return True, None, {"status": "FORCE_ALLOW"}
    if SPOT_SELL_BLOCK_FILE.exists():
        data, read_error = _read_json_file(SPOT_SELL_BLOCK_FILE)
        return False, "SPOT_SELL_CAPABILITY_BLOCKED", data or {"read_error": read_error}
    state, _ = _read_json_file(STATE_FILE)
    last_error = str((state or {}).get("last_error") or "")
    consecutive = int((state or {}).get("consecutive_losses", 0) or 0)
    if consecutive >= 2 and last_error.startswith("SELL_"):
        return False, f"SPOT_SELL_CAPABILITY_SUSPECT_{last_error}", state or {}
    return True, None, {}


def _mark_spot_sell_blocked(reason: str) -> None:
    _atomic_write_text(SPOT_SELL_BLOCK_FILE, json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": "sodex_spot_daemon",
        "reason": reason,
        "operator_action": "Verify a tiny spot SELL manually in SoDEX UI, then remove this file if the account can sell.",
    }, indent=2))


def _pid_matches(pid: int, needle: str) -> bool:
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_text(errors="ignore")
    except Exception:
        return False
    return needle in cmdline.replace("\x00", " ")


def _matching_processes(needle: str) -> list[dict]:
    matches = []
    proc = Path("/proc")
    try:
        entries = list(proc.iterdir())
    except Exception:
        return matches
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_text(errors="ignore").replace("\x00", " ").strip()
        except Exception:
            continue
        if needle in cmdline:
            matches.append({"pid": int(entry.name), "cmd": cmdline})
    return sorted(matches, key=lambda item: item["pid"])


def _systemd_service_process(service: str, needle: str) -> list[dict]:
    """Fallback process visibility for services hidden from /proc scan."""
    try:
        result = subprocess.run(
            [
                "systemctl",
                "--user",
                "show",
                service,
                "--property=ActiveState",
                "--property=SubState",
                "--property=MainPID",
                "--property=ExecMainPID",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []

    props = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        props[key] = value.strip()

    if props.get("ActiveState") != "active":
        return []

    pid = 0
    for field in ("ExecMainPID", "MainPID"):
        raw = props.get(field, "")
        if raw.isdigit() and int(raw) > 0:
            pid = int(raw)
            break
    if pid <= 0:
        return [{"pid": 0, "cmd": f"systemd:{service}", "source": "systemd"}]

    if _pid_matches(pid, needle):
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_text(errors="ignore").replace("\x00", " ").strip()
        except Exception:
            cmdline = f"systemd:{service}"
        return [{"pid": pid, "cmd": cmdline or f"systemd:{service}", "source": "systemd"}]

    return [{"pid": pid, "cmd": f"systemd:{service}", "source": "systemd"}]


def _autofarm_lock_status() -> dict:
    """Report the advisory lock file without treating stale files as blockers."""
    if not AUTOFARM_LOCK_FILE.exists():
        return {"exists": False, "active": False, "stale": False}
    try:
        parts = AUTOFARM_LOCK_FILE.read_text().strip().split()
        pid = int(parts[0]) if parts else None
    except Exception:
        pid = None
    active = bool(pid and _pid_matches(pid, "sodex_autofarm.py"))
    try:
        age_s = round(datetime.now(timezone.utc).timestamp() - AUTOFARM_LOCK_FILE.stat().st_mtime, 1)
    except OSError:
        age_s = None
    return {
        "exists": True,
        "active": active,
        "stale": not active,
        "pid": pid,
        "age_s": age_s,
        "path": str(AUTOFARM_LOCK_FILE),
    }


def _event_risk_preflight() -> tuple[bool, str | None, dict]:
    """Fast fail-closed event-risk gate before launching live autofarm."""
    if os.environ.get("SODEX_EVENT_GUARD_DISABLE") == "1":
        return True, None, {"level": "DISABLED"}
    if os.environ.get("SODEX_EVENT_GUARD_FORCE_ALLOW") == "1":
        return True, None, {"level": "FORCE_ALLOW", "live_gate": "ALLOW_WITH_CAUTION",
                            "reason": "BULL market bypass — event risk overridden"}
    try:
        data = json.loads(EVENT_STATUS_FILE.read_text())
        risk = data.get("event_risk")
        if not isinstance(risk, dict):
            return False, "EVENT_RISK_UNKNOWN_NO_EVENT_RISK_IN_STATUS", {}
        ts_raw = str(data.get("ts") or risk.get("ts") or "")
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_s = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
        if age_s > EVENT_STATUS_MAX_AGE_S:
            return False, f"EVENT_RISK_UNKNOWN_STALE_{int(age_s)}s", risk
        risk = enrich_event_route_policy(dict(risk))
        risk["status_age_s"] = round(age_s, 1)
        level = str(risk.get("level", "NORMAL"))
        live_gate = str(risk.get("live_gate", "ALLOW_WITH_CAUTION"))
        if level in {"ORANGE", "RED"} or live_gate == "BLOCK_LIVE":
            reason = str(risk.get("reason", "external event shock"))[:160]
            return False, f"EVENT_RISK_{level}_{reason}", risk
        return True, None, risk
    except Exception as exc:
        return False, f"EVENT_RISK_UNKNOWN_CACHE_ERROR_{type(exc).__name__}", {}


def _load_research_status(max_age_s: int) -> tuple[dict | None, str | None]:
    data, read_error = _read_json_file(EVENT_STATUS_FILE)
    if data is None:
        return None, f"CACHE_ERROR_{read_error}"
    try:
        ts = datetime.fromisoformat(str(data.get("ts", "")).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_s = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
        if age_s > max_age_s:
            return None, f"STALE_{int(age_s)}s"
        return data, None
    except Exception as exc:
        return None, f"CACHE_ERROR_{type(exc).__name__}"


def _adaptive_policy_preflight(expected_route: str = LIVE_ROUTE) -> tuple[bool, str | None, dict]:
    """Require learned policy evidence before launching a live route."""
    if os.environ.get("SODEX_ADAPTIVE_POLICY_DISABLE") == "1":
        return True, None, {"status": "DISABLED"}
    if os.environ.get("SODEX_EVENT_GUARD_FORCE_ALLOW") == "1":
        return True, None, {"status": "FORCE_ALLOW", "live_gate": "ALLOW_WITH_CAUTION",
                            "reason": "BULL market bypass — adaptive policy overridden, all routes open"}
    data, load_error = _load_research_status(POLICY_STATUS_MAX_AGE_S)
    if data is None:
        return False, f"POLICY_UNKNOWN_{load_error}", {}
    policy = data.get("adaptive_policy")
    if not isinstance(policy, dict):
        return False, "POLICY_UNKNOWN_NO_ADAPTIVE_POLICY", {}
    policy = dict(policy)
    event_risk = data.get("event_risk")
    if isinstance(event_risk, dict):
        event_risk = enrich_event_route_policy(event_risk)
        route_policy = event_risk.get("route_policy", {})
        opportunity_routes = route_policy.get("opportunity_routes", []) if isinstance(route_policy, dict) else []
        if not policy.get("event_opportunity_bias"):
            policy["event_opportunity_bias"] = event_risk.get("opportunity_bias")
        if not policy.get("event_opportunity_routes"):
            policy["event_opportunity_routes"] = opportunity_routes
        if not policy.get("event_route_policy"):
            policy["event_route_policy"] = route_policy
        if not policy.get("route_opportunity_state") and isinstance(route_policy, dict):
            route_gates = route_policy.get("route_gates", {}) or {}
            policy["route_opportunity_state"] = [
                {
                    "route": route,
                    "gate": gate,
                    "action": (
                        "RESEARCH_OPPORTUNITY"
                        if route in opportunity_routes and gate == "RESEARCH_ONLY"
                        else gate
                    ),
                    "blocked": gate == "BLOCK_LIVE",
                    "promoted": False,
                    "watch": False,
                    "promoted_cohort_count": 0,
                    "watch_cohort_count": 0,
                    "blocked_cohort_count": 0,
                    "event_aligned": route in opportunity_routes,
                }
                for route, gate in sorted(route_gates.items())
            ]
        if policy.get("external_live_gate") == "BLOCK_LIVE" and opportunity_routes:
            policy["status"] = "RISK_EVENT_ROUTE_LIMITED"
    if policy.get("external_live_gate") == "BLOCK_LIVE":
        return False, "POLICY_BLOCKED_BY_EVENT_RISK", policy

    promoted = [
        item for item in policy.get("promote", []) or []
        if isinstance(item, dict) and item.get("route") == expected_route
    ]
    if promoted:
        return True, None, {"status": "PROMOTED", "evidence": promoted[0]}

    blocked = [
        item for item in policy.get("block", []) or []
        if isinstance(item, dict) and item.get("route") == expected_route
    ]
    if blocked:
        evidence = blocked[0]
        return False, (
            f"POLICY_BLOCK_ROUTE_{expected_route}_"
            f"wr={evidence.get('win_rate')}_edge={evidence.get('avg_edge_return_pct')}"
        ), policy
    return False, f"POLICY_NO_PROMOTE_{expected_route}", policy


def _guard_status_snapshot() -> dict:
    """Summarize live-route gates without launching autofarm."""
    halt_ok, halt_reason, halt_detail = _global_halt_preflight()
    sell_ok, sell_reason, sell_detail = _spot_sell_capability_preflight()
    event_ok, event_reason, event_risk = _event_risk_preflight()
    policy_ok, policy_reason, policy = _adaptive_policy_preflight()
    if is_killed():
        operator_status = "KILLED"
        reason = "kill switch active"
    elif not halt_ok:
        operator_status = "BLOCKED_GLOBAL_HALT"
        reason = halt_reason
    elif not sell_ok:
        operator_status = "BLOCKED_SPOT_SELL_CAPABILITY"
        reason = sell_reason
    elif not event_ok:
        operator_status = "BLOCKED_EVENT_RISK"
        reason = event_reason
    elif not policy_ok:
        operator_status = "BLOCKED_POLICY"
        reason = policy_reason
    else:
        operator_status = "READY"
        reason = None

    return {
        "operator_status": operator_status,
        "reason": reason,
        "live_route": LIVE_ROUTE,
        "autofarm_lock": _autofarm_lock_status(),
        "global_halt": {
            "ok": halt_ok,
            "reason": halt_reason,
            "detail": halt_detail,
        },
        "spot_sell_capability": {
            "ok": sell_ok,
            "reason": sell_reason,
            "detail": sell_detail,
        },
        "event_risk": {
            "ok": event_ok,
            "reason": event_reason,
            "level": event_risk.get("level"),
            "live_gate": event_risk.get("live_gate"),
            "risk_score": event_risk.get("risk_score"),
            "opportunity_bias": event_risk.get("opportunity_bias"),
            "opportunity_routes": event_risk.get("opportunity_routes", []),
            "route_policy": event_risk.get("route_policy", {}),
            "ts": event_risk.get("ts"),
            "status_age_s": event_risk.get("status_age_s"),
        },
        "adaptive_policy": {
            "ok": policy_ok,
            "reason": policy_reason,
            "status": policy.get("status"),
            "external_live_gate": policy.get("external_live_gate"),
            "event_opportunity_bias": policy.get("event_opportunity_bias"),
            "event_opportunity_routes": policy.get("event_opportunity_routes", []),
            "route_opportunity_state": policy.get("route_opportunity_state", []),
            "live_route_decision": policy.get("live_route_decision"),
            "promote_count": policy.get("promote_count"),
            "block_count": policy.get("block_count"),
            "watch_count": policy.get("watch_count"),
        },
    }


def _status_file_snapshot() -> dict:
    if not EVENT_STATUS_FILE.exists():
        return {"exists": False, "fresh": False, "reason": "MISSING"}
    data, read_error = _read_json_file(EVENT_STATUS_FILE)
    if data is None:
        return {
            "exists": True,
            "fresh": False,
            "reason": f"READ_ERROR_{read_error}",
        }
    try:
        ts = datetime.fromisoformat(str(data.get("ts", "")).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_s = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
        return {
            "exists": True,
            "fresh": age_s <= POLICY_STATUS_MAX_AGE_S,
            "age_s": round(age_s, 1),
            "ts": data.get("ts"),
            "last_status": data.get("last_status"),
            "mode": data.get("mode"),
            "external_live_gate": data.get("external_live_gate"),
            "top_long_count": data.get("top_long_count"),
            "top_short_count": data.get("top_short_count"),
            "learning_strength": data.get("learning_strength", {}),
            "errors": data.get("errors", []),
        }
    except Exception as exc:
        return {
            "exists": True,
            "fresh": False,
            "reason": f"READ_ERROR_{type(exc).__name__}",
        }


def _order_surface_audit_snapshot() -> dict:
    try:
        from scripts import sodex_order_surface_audit
        return sodex_order_surface_audit.build_report()
    except Exception as exc:
        return {
            "status": "ERROR",
            "bad_count": 1,
            "surface_count": 0,
            "surfaces": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def _e1_w18_readiness_snapshot() -> dict:
    try:
        from anantara import sodex_twin_engine as twin
        old_paths = (
            twin.SAFETY_HALT_FILE,
            twin.PNL_HALT_FILE,
            twin.SPOT_SELL_BLOCK_FILE,
            twin.SPOT_SELL_VERIFIED_FILE,
        )
        try:
            twin.SAFETY_HALT_FILE = SAFETY_HALT_FILE
            twin.PNL_HALT_FILE = PNL_HALT_FILE
            twin.SPOT_SELL_BLOCK_FILE = SPOT_SELL_BLOCK_FILE
            twin.SPOT_SELL_VERIFIED_FILE = SPOT_SELL_VERIFIED_FILE
            return twin.e1_w18_readiness(twin.Config())
        finally:
            (
                twin.SAFETY_HALT_FILE,
                twin.PNL_HALT_FILE,
                twin.SPOT_SELL_BLOCK_FILE,
                twin.SPOT_SELL_VERIFIED_FILE,
            ) = old_paths
    except Exception as exc:
        return {
            "mode": "E1_W18_DYNAMIC_TWO_SIDED_QUOTE",
            "ready_for_live": False,
            "blockers": [f"READINESS_ERROR:{type(exc).__name__}: {exc}"],
        }


def _spot_sell_recovery_snapshot() -> dict:
    try:
        from scripts import sodex_spot_sell_recovery as recovery
        old_paths = (
            recovery.BLOCK_FILE,
            recovery.VERIFIED_FILE,
        )
        try:
            recovery.BLOCK_FILE = SPOT_SELL_BLOCK_FILE
            recovery.VERIFIED_FILE = SPOT_SELL_VERIFIED_FILE
            return recovery.build_status()
        finally:
            recovery.BLOCK_FILE, recovery.VERIFIED_FILE = old_paths
    except Exception as exc:
        return {
            "status": "ERROR",
            "reason": f"{type(exc).__name__}: {exc}",
        }


def _e1_recovery_gate_snapshot() -> dict:
    try:
        from scripts import sodex_e1_recovery_gate as gate
        old_paths = (
            gate.SELL_BLOCK,
            gate.SELL_VERIFIED,
            gate.SAFETY_HALT,
            gate.PNL_HALT,
        )
        try:
            gate.SELL_BLOCK = SPOT_SELL_BLOCK_FILE
            gate.SELL_VERIFIED = SPOT_SELL_VERIFIED_FILE
            gate.SAFETY_HALT = SAFETY_HALT_FILE
            gate.PNL_HALT = PNL_HALT_FILE
            return gate.build_status()
        finally:
            gate.SELL_BLOCK, gate.SELL_VERIFIED, gate.SAFETY_HALT, gate.PNL_HALT = old_paths
    except Exception as exc:
        return {
            "status": "ERROR",
            "phase": "PHASE_ERROR",
            "reason": f"{type(exc).__name__}: {exc}",
        }


def doctor() -> dict:
    """Read-only operational diagnosis for SPOT farming."""
    status = show_status()
    guard = status.get("guard_status", {})
    target_status = status.get("target_status", {}) if isinstance(status.get("target_status"), dict) else {}
    research_file = _status_file_snapshot()
    order_surface_audit = _order_surface_audit_snapshot()
    e1_w18_readiness = _e1_w18_readiness_snapshot()
    spot_sell_recovery = _spot_sell_recovery_snapshot()
    e1_recovery_gate = _e1_recovery_gate_snapshot()
    research_processes = _matching_processes("sodex_autonomous_research.py")
    if not research_processes:
        research_processes = _systemd_service_process(
            "sodex-autonomous-research.service",
            "sodex_autonomous_research.py",
        )
    autofarm_processes = _matching_processes("sodex_autofarm.py")

    findings = []
    if research_file.get("fresh") is False:
        findings.append({
            "severity": "HIGH",
            "code": "RESEARCH_STATUS_NOT_FRESH",
            "detail": research_file.get("reason") or f"age_s={research_file.get('age_s')}",
        })
    if not research_processes and research_file.get("fresh") is not True:
        findings.append({
            "severity": "MEDIUM",
            "code": "RESEARCH_LOOP_NOT_RUNNING",
            "detail": "No sodex_autonomous_research.py process found.",
        })
    elif not research_processes:
        findings.append({
            "severity": "INFO",
            "code": "RESEARCH_PROCESS_NOT_VISIBLE",
            "detail": "Status file is fresh, so research output is current even though no process is visible here.",
        })
    if autofarm_processes and guard.get("operator_status") != "READY":
        findings.append({
            "severity": "HIGH",
            "code": "AUTOFARM_RUNNING_WHILE_GUARD_BLOCKED",
            "detail": f"operator_status={guard.get('operator_status')}",
        })
    if order_surface_audit.get("status") != "OK":
        findings.append({
            "severity": "HIGH",
            "code": "ORDER_SURFACE_AUDIT_FAILED",
            "detail": (
                f"bad={order_surface_audit.get('bad_count')} "
                f"surfaces={order_surface_audit.get('surface_count')} "
                f"error={order_surface_audit.get('error') or ''}".strip()
            ),
        })
    if e1_w18_readiness.get("e1_enabled") and not e1_w18_readiness.get("ready_for_live"):
        blockers = e1_w18_readiness.get("blockers", []) or []
        findings.append({
            "severity": "HIGH",
            "code": "E1_W18_NOT_READY",
            "detail": "; ".join(str(b) for b in blockers[:3]),
        })
    if spot_sell_recovery.get("status") == "BLOCKED":
        findings.append({
            "severity": "HIGH",
            "code": "SPOT_SELL_RECOVERY_REQUIRED",
            "detail": "manual/UI tiny spot SELL proof is required before E1 W18 re-enable",
        })
    learning_strength = research_file.get("learning_strength", {})
    learning_status = learning_strength.get("status") if isinstance(learning_strength, dict) else None
    state_file_error = status.get("state_file_error")
    if state_file_error:
        findings.append({
            "severity": "MEDIUM",
            "code": "TRADING_STATE_NOT_READABLE",
            "detail": state_file_error,
        })
    if learning_status == "LEARNING_DATA_GAP":
        findings.append({
            "severity": "HIGH",
            "code": "LEARNING_DATA_GAP",
            "detail": ",".join(learning_strength.get("next_actions", [])) if isinstance(learning_strength, dict) else "",
        })
    elif learning_status in {"LEARNING_WARMUP", "LEARNING_ACTIVE"}:
        findings.append({
            "severity": "INFO",
            "code": learning_status,
            "detail": f"score={learning_strength.get('score')} outcomes={learning_strength.get('outcomes')}",
        })
    lock = guard.get("autofarm_lock", {})
    if lock.get("stale"):
        findings.append({
            "severity": "LOW",
            "code": "STALE_AUTOFARM_LOCK_FILE",
            "detail": f"pid={lock.get('pid')} age_s={lock.get('age_s')}",
        })
    if guard.get("operator_status") == "BLOCKED_GLOBAL_HALT":
        findings.append({
            "severity": "HIGH",
            "code": "LIVE_BLOCKED_BY_GLOBAL_HALT",
            "detail": guard.get("reason"),
        })
    elif guard.get("operator_status") == "BLOCKED_SPOT_SELL_CAPABILITY":
        findings.append({
            "severity": "HIGH",
            "code": "LIVE_BLOCKED_BY_SPOT_SELL_CAPABILITY",
            "detail": guard.get("reason"),
        })
    elif guard.get("operator_status") == "BLOCKED_EVENT_RISK":
        findings.append({
            "severity": "INFO",
            "code": "LIVE_BLOCKED_BY_EVENT_RISK",
            "detail": guard.get("reason"),
        })
    elif guard.get("operator_status") == "BLOCKED_POLICY":
        findings.append({
            "severity": "INFO",
            "code": "LIVE_BLOCKED_BY_POLICY",
            "detail": guard.get("reason"),
        })
    elif guard.get("operator_status") == "READY":
        findings.append({
            "severity": "INFO",
            "code": "LIVE_ROUTE_READY",
            "detail": f"route={guard.get('live_route')}",
        })

    return {
        "status": "OK",
        "ts": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "operator_status": guard.get("operator_status"),
            "live_route": guard.get("live_route"),
            "kill_switch": status.get("kill_switch"),
            "research_status_fresh": research_file.get("fresh"),
            "research_process_count": len(research_processes),
            "autofarm_process_count": len(autofarm_processes),
            "learning_strength_status": learning_status,
            "learning_strength_score": learning_strength.get("score") if isinstance(learning_strength, dict) else None,
            "weekly_target_mode": target_status.get("weekly_target_mode"),
            "weekly_volume_progress_pct": target_status.get("volume_progress_pct"),
            "required_hourly_volume_usd": target_status.get("required_hourly_volume_usd"),
            "event_opportunity_routes": guard.get("event_risk", {}).get("opportunity_routes", []),
            "order_surface_audit_status": order_surface_audit.get("status"),
            "order_surface_bad_count": order_surface_audit.get("bad_count"),
            "e1_w18_ready": e1_w18_readiness.get("ready_for_live"),
            "e1_w18_blocker_count": len(e1_w18_readiness.get("blockers", []) or []),
            "spot_sell_recovery_status": spot_sell_recovery.get("status"),
            "e1_recovery_phase": e1_recovery_gate.get("phase"),
            "finding_count": len(findings),
        },
        "findings": findings,
        "order_surface_audit": order_surface_audit,
        "e1_w18_readiness": e1_w18_readiness,
        "spot_sell_recovery": spot_sell_recovery,
        "e1_recovery_gate": e1_recovery_gate,
        "status_file": research_file,
        "guard_status": guard,
        "processes": {
            "research": research_processes,
            "autofarm": autofarm_processes,
        },
    }


def run_once() -> dict:
    """Run one autofarm cycle and return result."""
    if is_killed():
        return {"status": "KILLED", "reason": "kill switch active"}

    halt_ok, halt_reason, halt_detail = _global_halt_preflight()
    if not halt_ok:
        return {
            "status": "SKIPPED",
            "reason": halt_reason,
            "pnl": 0.0,
            "drawdown": 0.0,
            "consecutive_losses": 0,
            "rt_count": 0,
            "global_halt": halt_detail,
        }

    sell_ok, sell_reason, sell_detail = _spot_sell_capability_preflight()
    if not sell_ok:
        return {
            "status": "SKIPPED",
            "reason": sell_reason,
            "pnl": 0.0,
            "drawdown": 0.0,
            "consecutive_losses": 0,
            "rt_count": 0,
            "spot_sell_capability": sell_detail,
        }

    event_ok, event_reason, event_risk = _event_risk_preflight()
    if not event_ok:
        return {
            "status": "SKIPPED",
            "reason": event_reason,
            "pnl": 0.0,
            "drawdown": 0.0,
            "consecutive_losses": 0,
            "rt_count": 0,
            "event_risk": {
                "level": event_risk.get("level"),
                "live_gate": event_risk.get("live_gate", "BLOCK_LIVE"),
                "risk_score": event_risk.get("risk_score"),
            },
        }

    policy_ok, policy_reason, policy = _adaptive_policy_preflight()
    if not policy_ok:
        return {
            "status": "SKIPPED",
            "reason": policy_reason,
            "pnl": 0.0,
            "drawdown": 0.0,
            "consecutive_losses": 0,
            "rt_count": 0,
            "adaptive_policy": {
                "status": policy.get("status"),
                "promote_count": policy.get("promote_count"),
                "block_count": policy.get("block_count"),
                "external_live_gate": policy.get("external_live_gate"),
            },
        }

    cmd = [
        sys.executable,
        "anantara/sodex_autofarm.py",
        "--capital",
        DEFAULT_CAPITAL,
    ]
    if os.environ.get("SODEX_SPOT_FORCE") == "1":
        cmd.append("--force")

    result = subprocess.run(
        cmd,
        capture_output=True, text=True,
        timeout=RUN_TIMEOUT_S,
        cwd=PROJECT_DIR,
    )

    output = result.stdout + result.stderr
    pnl = 0.0
    error = None

    for line in output.split("\n"):
        if "P&L: $" in line:
            try:
                pnl = float(line.split("$")[1].split()[0].replace("+", ""))
            except (ValueError, IndexError):
                pass
        if "Error:" in line:
            error = line.split("Error:", 1)[1].strip()

    # Check state for risk alerts
    state = {}
    state_read_error = None
    if STATE_FILE.exists():
        state, state_read_error = _read_json_file(STATE_FILE, backup_corrupt=True)
        if state is None:
            state = {}

    drawdown = state.get("drawdown_pct", 0.0) if "drawdown_pct" in state else (
        (state.get("peak_equity", 0) - state.get("current_equity", 0)) / max(state.get("peak_equity", 1), 1) * 100
        if state.get("peak_equity", 0) > 0 else 0.0
    )

    consecutive = state.get("consecutive_losses", 0)

    alerts = []
    if consecutive >= 2:
        alerts.append(f"⚠️ {consecutive} consecutive losses on SPOT!")
    if drawdown > 3.0:
        alerts.append(f"🔴 SPOT drawdown {drawdown:.1f}%!")

    if alerts:
        send_alert("\n".join(alerts))
    else:
        clear_alert()

    if result.returncode != 0:
        status = "ERROR"
    elif error:
        status = "SKIPPED" if error in {
            "NOT_PRIME_TIME",
            "SPREAD_TOO_THIN",
            "ORDERBOOK_FAILED",
        } or error.startswith(("INTEL_SKIP_", "GOVERNOR_", "EVENT_RISK_", "POLICY_")) else "ERROR"
    else:
        status = "OK"

    if status == "ERROR":
        if state_read_error and not error:
            error = f"STATE_READ_ERROR_{state_read_error}"
        state = _record_wrapper_failure(state, error or f"returncode={result.returncode}")
        consecutive = state.get("consecutive_losses", consecutive)
        if str(error or "").startswith("SELL_"):
            _mark_spot_sell_blocked(str(error))

    return {
        "status": status,
        "reason": error,
        "pnl": pnl,
        "drawdown": round(drawdown, 2),
        "consecutive_losses": consecutive,
        "rt_count": state.get("rt_count", 0),
    }


def show_status() -> dict:
    """Show current SPOT farming status."""
    guard_status = _guard_status_snapshot()
    if STATE_FILE.exists():
        state, state_read_error = _read_json_file(STATE_FILE, backup_corrupt=True)
        if state is not None:
            target_status = state.get("target_status")
            if not isinstance(target_status, dict) or "weekly_target_mode" not in target_status:
                try:
                    from anantara.sodex_spot_governor import SpotState
                    s = SpotState()
                    for key, value in state.items():
                        if key == "target_status":
                            continue
                        if hasattr(s, key):
                            setattr(s, key, value)
                    state["target_status"] = s.target_status()
                except Exception as exc:
                    state["target_status_error"] = str(exc)[:120]
            state["kill_switch"] = is_killed()
            state["guard_status"] = guard_status
            return state
        return {
            "status": "NO_TRADING_STATE",
            "rt_count": 0,
            "kill_switch": is_killed(),
            "guard_status": guard_status,
            "state_file_error": state_read_error,
        }
    return {
        "status": "NO_TRADING_STATE",
        "rt_count": 0,
        "kill_switch": is_killed(),
        "guard_status": guard_status,
    }


def kill():
    """Activate kill switch."""
    _atomic_write_text(KILL_FILE, datetime.now(timezone.utc).isoformat())


def unkill():
    """Deactivate kill switch."""
    if KILL_FILE.exists():
        KILL_FILE.unlink()


def pregain_scan() -> dict:
    """Read-only SoDEX top pre-gain/loser scan. Does not place orders."""
    try:
        from anantara.sodex_pregain_scanner import scan
        return scan()
    except Exception as exc:
        return {"status": "ERROR", "reason": str(exc)[:200]}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SoDEX SPOT Daemon Wrapper")
    parser.add_argument("action", choices=["once", "status", "doctor", "kill", "unkill", "pregain-scan"],
                        default="status", nargs="?")
    args = parser.parse_args()

    if args.action == "once":
        result = run_once()
        print(json.dumps(result, indent=2))
    elif args.action == "status":
        print(json.dumps(show_status(), indent=2))
    elif args.action == "doctor":
        print(json.dumps(doctor(), indent=2))
    elif args.action == "kill":
        kill()
        print(json.dumps({"status": "KILLED"}))
    elif args.action == "unkill":
        unkill()
        print(json.dumps({"status": "UNKILLED"}))
    elif args.action == "pregain-scan":
        print(json.dumps(pregain_scan(), indent=2))
