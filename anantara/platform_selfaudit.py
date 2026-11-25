"""
ANANTARA SAKTI — Platform Self-Audit v1.0

RS-9 seed (Audit Fable 5/6): Sistem mengaudit DIRINYA SENDIRI secara periodik.

Setiap minggu (Senin 03:00 UTC), system menjalankan audit platform komprehensif:
  A. Constitution check — gate health, freeze violations, complexity budget
  B. Ground truth divergence — dokumen vs on-chain, stale sections
  C. Experiment registry — progres power, FDR corrections, auto-close candidates
  D. Platform health — daemon jobs active, guard uptime, backup recency
  E. Engineering quality — test count, syntax check, secret scan
  F. Complexity budget — parameter count per project vs anggaran

Output:
  - Telegram report ringkas
  - data/selfaudit_YYYYMMDD.json (audit trail)
  - data/selfaudit_latest.json (untuk dashboard)

Pure stdlib + optional deps (httpx untuk endpoint check).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("anantara.selfaudit")

_PROJECT_DIR   = Path(os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti")))
_DATA_DIR      = _PROJECT_DIR / "data"
_AUDIT_DIR     = _DATA_DIR / "selfaudits"

try:
    import httpx as _httpx
except ImportError:
    _httpx = None  # type: ignore[assignment]


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        tmp.rename(path)
    except Exception as e:
        log.error(f"selfaudit write {path.name}: {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _run(cmd: list, timeout: int = 30) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=str(_PROJECT_DIR),
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()[:500]
    except Exception as e:
        return -1, str(e)


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT SECTIONS
# ─────────────────────────────────────────────────────────────────────────────

def audit_constitution() -> dict:
    """A. Constitution: gates, freeze, complexity budget."""
    result = {"section": "constitution", "ok": True, "findings": []}
    try:
        import sys as _sys
        _sys.path.insert(0, str(_PROJECT_DIR / "anantara"))
        import constitution as c

        verdict = c.check_live_permission("pregain")
        result["live_permitted"]       = verdict.live_permitted
        result["gates_age_days"]       = verdict.gates_age_days
        result["freeze_ok"]            = verdict.freeze_ok
        result["freeze_violations"]    = verdict.freeze_violations
        result["bypass_active"]        = verdict.bypass_active

        if verdict.bypass_active:
            result["findings"].append("BYPASS_ACTIVE: CONSTITUTION_BYPASS diset!")
            result["ok"] = False
        if verdict.freeze_violations:
            result["findings"].append(
                f"FREEZE_VIOLATIONS: {len(verdict.freeze_violations)} — {verdict.freeze_violations}"
            )
        if verdict.gates_age_days > 7:
            result["findings"].append(
                f"GATES_STALE: {verdict.gates_age_days:.1f} hari > 7 hari max"
            )
            result["ok"] = False
        if not verdict.live_permitted:
            result["findings"].append(f"LIVE_BLOCKED: {verdict.reason[:100]}")

    except Exception as e:
        result["error"] = str(e)
        result["ok"] = False
    return result


def audit_ground_truth() -> dict:
    """B. Ground truth: balance oracle freshness, document divergence."""
    result = {"section": "ground_truth", "ok": True, "findings": []}
    try:
        gt = _read_json(_DATA_DIR / "ground_truth.json")
        if not gt:
            result["findings"].append("GT_MISSING: ground_truth.json tidak ada")
            result["ok"] = False
            return result

        # Age check
        try:
            ts = datetime.fromisoformat(gt["generated_utc"]).replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
            result["age_minutes"] = round(age_min, 1)
            if age_min > 60:
                result["findings"].append(f"GT_STALE: {age_min:.0f} menit > 60 menit max")
                result["ok"] = False
        except Exception:
            result["findings"].append("GT_TIMESTAMP_PARSE_ERROR")

        # Capital delta check
        delta = gt.get("capital_delta_usd", 0.0)
        result["capital_delta_usd"] = delta
        observed_delta = gt.get("capital_delta_observed_usd", 0.0)
        result["capital_delta_observed_usd"] = observed_delta
        if abs(delta) > 20:
            result["findings"].append(f"LARGE_DELTA: ${delta:+.2f} tanpa capital_log?")
        if abs(observed_delta) > 20:
            result["findings"].append(f"LARGE_OBSERVED_DELTA: ${observed_delta:+.2f} lintas akun HL")

        # STATUS.md stale check
        try:
            import sys as _sys
            _sys.path.insert(0, str(_PROJECT_DIR / "scripts"))
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "gss", _PROJECT_DIR / "scripts" / "generate_status_section.py")
            gss = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(gss)
            if gss.check_stale():
                result["findings"].append("STATUS_STALE: bagian kondisi STATUS.md perlu diperbarui")
        except Exception as e:
            result["findings"].append(f"STATUS_CHECK_ERROR: {e}")

        result["hl_balance_usdc"] = gt.get("hl_balance", {}).get("total_usdc", 0.0)
        result["n_open_hl"]       = gt.get("n_open_hl", 0)
        result["n_open_hl_total"] = gt.get("n_open_hl_total", gt.get("n_open_hl", 0))
        result["n_open_hl_harvest"] = gt.get("n_open_hl_harvest", 0)
        if result["n_open_hl_total"] > result["n_open_hl"]:
            result["findings"].append(
                f"HL_HARVEST_ACTIVE: total {result['n_open_hl_total']} posisi, "
                f"primary {result['n_open_hl']}, harvest {result['n_open_hl_harvest']}"
            )

    except Exception as e:
        result["error"] = str(e)
        result["ok"] = False
    return result


def audit_experiments() -> dict:
    """C. Experiment registry: progres, FDR, auto-close candidates."""
    result = {"section": "experiments", "ok": True, "findings": [], "experiments": []}
    try:
        import sys as _sys
        _sys.path.insert(0, str(_PROJECT_DIR / "anantara"))
        import experiment_registry as er

        active = er.list_active()
        result["n_active"]  = len(active)
        result["n_total"]   = len(er.list_all())

        for exp in active:
            exp_info = {
                "exp_id":    exp.exp_id,
                "engine":    exp.engine,
                "power_pct": exp.power_pct(),
                "n":         f"{exp.n_current}/{exp.n_target}",
                "days":      round(exp.days_since_register(), 1),
            }
            result["experiments"].append(exp_info)

            # Auto-close check
            verdict = er.check_auto_close(exp)
            if verdict:
                result["findings"].append(
                    f"AUTO_CLOSE: {exp.exp_id} siap ditutup → verdict={verdict}"
                )

            # Low power warning
            if exp.days_since_register() > 14 and exp.power_pct() < 20:
                result["findings"].append(
                    f"LOW_POWER: {exp.exp_id} {exp.power_pct():.0f}% setelah {exp.days_since_register():.0f} hari"
                )

        # FDR corrections
        fdr = er.compute_fdr_corrections()
        result["fdr_corrections"] = fdr

    except Exception as e:
        result["error"] = str(e)
        result["ok"] = False
    return result


def audit_platform_health() -> dict:
    """D. Platform health: daemon jobs, guard uptime, backup recency."""
    result = {"section": "platform_health", "ok": True, "findings": []}
    try:
        # Guard state
        guard = _read_json(_DATA_DIR / "guard_state.json")
        if guard:
            try:
                upd = datetime.fromisoformat(guard["updated_utc"]).replace(tzinfo=timezone.utc)
                age_min = (datetime.now(timezone.utc) - upd).total_seconds() / 60
                result["guard_age_min"] = round(age_min, 1)
                if age_min > 10:
                    result["findings"].append(f"GUARD_STALE: {age_min:.0f}m — guard mungkin mati?")
                    result["ok"] = False
            except Exception:
                pass
            result["guard_sha"]      = guard.get("startup_git_sha", "?")
            result["guard_n_alerts"] = guard.get("alert_count", 0)
        else:
            result["findings"].append("GUARD_OFFLINE: anantara-guard tidak berjalan")

        # Git SHA
        rc, sha = _run(["git", "rev-parse", "--short", "HEAD"])
        result["head_sha"] = sha.strip() if rc == 0 else "(unknown)"

        # Backup recency
        backups = sorted((_PROJECT_DIR / "backups").glob("manifest_*.json")) if (_PROJECT_DIR / "backups").exists() else []
        if backups:
            last_backup_ts = backups[-1].stat().st_mtime
            age_h = (time.time() - last_backup_ts) / 3600
            result["last_backup_age_h"] = round(age_h, 1)
            if age_h > 26:
                result["findings"].append(f"BACKUP_STALE: {age_h:.0f}h — backup lebih dari 26 jam")
                result["ok"] = False
        else:
            result["findings"].append("NO_BACKUP: tidak ada backup manifest ditemukan")

        # node_exporter port check
        rc2, ss_out = _run(["ss", "-tlnp"])
        if "*:9100" in ss_out or "0.0.0.0:9100" in ss_out:
            result["findings"].append("PORT_9100_OPEN: *:9100 masih terbuka — jalankan fix_node_exporter_port.sh")
            result["ok"] = False
        else:
            result["node_exporter_ok"] = True

    except Exception as e:
        result["error"] = str(e)
        result["ok"] = False
    return result


def audit_engineering_quality() -> dict:
    """E. Engineering quality: tests, syntax, secrets."""
    result = {"section": "engineering", "ok": True, "findings": []}
    try:
        # Test count
        rc, out = _run(["python3", "-m", "unittest", "discover", "-s", "tests", "-q"],
                       timeout=120)
        if rc == 0:
            # Parse "Ran X tests"
            import re
            m = re.search(r"Ran (\d+) test", out)
            result["test_count"] = int(m.group(1)) if m else "?"
        else:
            result["findings"].append(f"TESTS_FAILED: {out[:200]}")
            result["ok"] = False

        # Syntax check semua modul platform baru
        for fname in ["constitution.py", "ground_truth.py", "platform_guard.py",
                      "experiment_registry.py", "platform_selfaudit.py"]:
            fpath = _PROJECT_DIR / "anantara" / fname
            if fpath.exists():
                rc2, _ = _run(["python3", "-m", "py_compile", str(fpath)])
                if rc2 != 0:
                    result["findings"].append(f"SYNTAX_ERROR: {fname}")
                    result["ok"] = False

        # Secret scan (no hardcoded keys)
        rc3, secret_out = _run(["grep", "-r", "--include=*.py",
                                 "-l", r"sk_live_|whsec_|HL_API_SECRET.*=.*0x",
                                 str(_PROJECT_DIR / "anantara")])
        if rc3 == 0 and secret_out.strip():
            result["findings"].append(f"SECRET_SCAN: hardcoded secrets? {secret_out[:100]}")

    except Exception as e:
        result["error"] = str(e)
        result["ok"] = False
    return result


def audit_complexity_budget() -> dict:
    """F. Complexity budget: parameter count vs anggaran."""
    result = {"section": "complexity", "ok": True, "findings": [], "engines": {}}
    try:
        import sys as _sys
        _sys.path.insert(0, str(_PROJECT_DIR / "anantara"))
        import constitution as c

        # Hitung parameter ter-fit per engine dari experiment registry
        try:
            import experiment_registry as er
            for engine in ("cex", "pregain", "sodex", "platform"):
                active = [e for e in er.list_all() if e.engine == engine]
                # n_live_trades: proxy dari n_current eksperimen terbesar
                n_live = max((e.n_current for e in active), default=0)
                # n_fitted_params: jumlah eksperimen sebagai proxy (sangat konservatif)
                n_params = len(active)
                ok, msg = c.check_complexity_budget(engine, n_live, n_params)
                result["engines"][engine] = {
                    "n_live_trades": n_live,
                    "n_fitted_params": n_params,
                    "within_budget": ok,
                }
                if not ok:
                    result["findings"].append(f"OVERBUDGET_{engine.upper()}: {msg[:100]}")
        except Exception as e:
            result["findings"].append(f"COMPLEXITY_CHECK_ERROR: {e}")

    except Exception as e:
        result["error"] = str(e)
        result["ok"] = False
    return result


# ─────────────────────────────────────────────────────────────────────────────
# FULL AUDIT RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def run_full_audit() -> dict:
    """
    Jalankan audit platform lengkap.
    Returns: dict lengkap dengan semua section.
    """
    started = time.time()
    log.info("[SELFAUDIT] Memulai platform self-audit...")

    audit = {
        "timestamp_utc": _utc_now(),
        "sections": {},
        "overall_ok": True,
        "total_findings": 0,
        "duration_sec": 0.0,
    }

    sections = [
        ("A_constitution",    audit_constitution),
        ("B_ground_truth",    audit_ground_truth),
        ("C_experiments",     audit_experiments),
        ("D_platform_health", audit_platform_health),
        ("E_engineering",     audit_engineering_quality),
        ("F_complexity",      audit_complexity_budget),
    ]

    for sec_key, sec_fn in sections:
        try:
            sec_result = sec_fn()
            audit["sections"][sec_key] = sec_result
            if not sec_result.get("ok", True):
                audit["overall_ok"] = False
            audit["total_findings"] += len(sec_result.get("findings", []))
        except Exception as e:
            audit["sections"][sec_key] = {"ok": False, "error": str(e)}
            audit["overall_ok"] = False

    audit["duration_sec"] = round(time.time() - started, 2)

    # Simpan ke file
    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    _write_atomic(_AUDIT_DIR / f"selfaudit_{date_str}.json", audit)
    _write_atomic(_DATA_DIR / "selfaudit_latest.json", audit)

    log.info(
        f"[SELFAUDIT] Selesai: {'OK' if audit['overall_ok'] else 'ISSUES'} "
        f"findings={audit['total_findings']} dur={audit['duration_sec']}s"
    )
    return audit


def format_telegram_report(audit: dict) -> str:
    """Format audit result menjadi pesan Telegram ringkas."""
    ok = audit.get("overall_ok", False)
    findings = audit.get("total_findings", 0)
    dur = audit.get("duration_sec", 0)
    ts = audit.get("timestamp_utc", "?")[:10]

    icon = "✅" if ok else "🔴"
    lines = [
        f"{icon} *Platform Self-Audit* {ts}",
        f"Status: {'SEMUA OK' if ok else f'{findings} FINDING(S)'} | {dur:.1f}s",
        "",
    ]

    for sec_key, sec in audit.get("sections", {}).items():
        sec_ok     = sec.get("ok", True)
        sec_icon   = "✅" if sec_ok else "⚠️"
        sec_name   = sec_key.split("_", 1)[-1].replace("_", " ").title()
        sec_finds  = len(sec.get("findings", []))

        if sec_ok:
            lines.append(f"{sec_icon} {sec_name}: OK")
        else:
            lines.append(f"{sec_icon} *{sec_name}: {sec_finds} finding(s)*")
            for f in sec.get("findings", [])[:3]:
                lines.append(f"  • {f[:80]}")

    # Experiment progress ringkas
    exp_section = audit.get("sections", {}).get("C_experiments", {})
    if exp_section.get("experiments"):
        lines.append("")
        lines.append("*Experiments:*")
        for e in exp_section["experiments"][:4]:
            lines.append(
                f"  {e['exp_id'][:25]}: {e['power_pct']:.0f}% ({e['n']})"
            )

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    audit = run_full_audit()
    print(format_telegram_report(audit))
    print(f"\n--- JSON saved to {_DATA_DIR / 'selfaudit_latest.json'} ---")
    sys.exit(0 if audit["overall_ok"] else 1)
