#!/usr/bin/env python3
"""Preflight kesiapan live SoDEX 01-Des-2026 (read-only, tanpa order).

Memeriksa 12 gerbang yang menentukan boleh-tidaknya meng-arm. TIDAK membaca isi
rahasia: hanya `exists()`/`stat()` pada path kredensial. TIDAK memanggil API
ber-auth, TIDAK menulis state trading.

Level: BLOCKER menggagalkan arm, WARN hanya dicatat.
Fase (eskalasi otomatis): PERSIAPAN (<25-Nov) -> BEKU (25-30 Nov) -> LIVE (>=1-Des).
Contoh: deadman WARN di PERSIAPAN, menjadi BLOCKER di BEKU.

Exit: 0 SIAP, 3 BELUM_SIAP, 2 error.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARM = ROOT / "secrets/LIVE_ARMED.json"
KILL = ROOT / "secrets/KILL"
ENVFILE = ROOT / "secrets/sodex.env"
ENGINE = ROOT / "scripts/research/mode_a_20261026/mode_a_live.py"
EQUITY = ROOT / "reports/sodex/EQUITY_LEDGER.jsonl"
DEADMAN_HB = ROOT / "data/DEADMAN_HEARTBEAT.json"
WATCHDOG_STATUS = ROOT / "data/sodex_watchdog_status.json"
KLINES = ROOT / "data/sodex_klines/1h"
CAPS = ("max_equity_usd", "max_order_usd", "max_total_buy_usd")
LIVE_DATE = date(2026, 12, 1)
FREEZE_DATE = date(2026, 11, 25)


def phase(today: date) -> str:
    if today >= LIVE_DATE:
        return "LIVE"
    if today >= FREEZE_DATE:
        return "BEKU"
    return "PERSIAPAN"


PHASE_ORDER = {"PERSIAPAN": 0, "BEKU": 1, "LIVE": 2}


def escalate(level: str, cur_phase: str, at_phase: str) -> str:
    """WARN naik menjadi BLOCKER begitu fase mencapai titik eskalasi.
    BLOCKER tidak pernah turun; WARN sebelum titik eskalasi tetap WARN."""
    if level == "WARN" and PHASE_ORDER.get(cur_phase, 0) >= PHASE_ORDER.get(at_phase, 99):
        return "BLOCKER"
    return level


def verdict(checks: list[dict]) -> dict:
    bl = [c["nama"] for c in checks if not c["ok"] and c["level"] == "BLOCKER"]
    wn = [c["nama"] for c in checks if not c["ok"] and c["level"] == "WARN"]
    return {"status": "SIAP" if not bl else "BELUM_SIAP", "blocker": len(bl),
            "blocker_nama": bl, "warn": len(wn), "warn_nama": wn,
            "total": len(checks), "lulus": sum(1 for c in checks if c["ok"])}


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _age_h(path: Path) -> float | None:
    if not path.exists():
        return None
    return (datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)).total_seconds() / 3600


def check_arm() -> dict:
    if not ARM.exists():
        return {"nama": "arm_file", "ok": True, "level": "INFO",
                "detail": "LIVE_ARMED.json belum ada (normal sebelum arm oleh user)"}
    try:
        d = json.loads(ARM.read_text())
    except Exception as e:
        return {"nama": "arm_file", "ok": False, "level": "BLOCKER", "detail": f"JSON rusak: {e}"}
    masalah = []
    if d.get("armed") is not True:
        masalah.append("armed != true")
    if d.get("engine_sha256") != sha256(ENGINE):
        masalah.append("engine_sha256 tidak cocok dengan kode saat ini (kode berubah setelah GO)")
    go = str(d.get("not_before") or "")
    if not go.startswith("2026-12"):
        masalah.append(f"not_before={go!r} bukan Desember 2026")
    caps = {k: d.get(k) for k in CAPS}
    if any(not isinstance(v, (int, float)) or v <= 0 for v in caps.values()):
        masalah.append(f"cap tidak valid: {caps}")
    return {"nama": "arm_file", "ok": not masalah, "level": "BLOCKER",
            "detail": "sah" if not masalah else "; ".join(masalah)}


def check_kill() -> dict:
    return {"nama": "kill_file", "ok": not KILL.exists(), "level": "BLOCKER",
            "detail": "tidak ada KILL" if not KILL.exists() else f"KILL aktif: {KILL}"}


def check_env() -> dict:
    if not ENVFILE.exists():
        return {"nama": "secret_env", "ok": False, "level": "BLOCKER",
                "detail": "secrets/sodex.env TIDAK ADA (hanya .template) — kredensial venue belum tersedia"}
    mode = oct(ENVFILE.stat().st_mode & 0o777)
    if mode not in ("0o600", "0o400"):
        return {"nama": "secret_env", "ok": False, "level": "WARN",
                "detail": f"ada, tetapi permission {mode} (disarankan 600)"}
    return {"nama": "secret_env", "ok": True, "level": "BLOCKER", "detail": "ada, permission aman"}


def check_engine() -> dict:
    s = sha256(ENGINE)
    if not s:
        return {"nama": "engine_sha", "ok": False, "level": "BLOCKER", "detail": "mode_a_live.py tidak ditemukan"}
    return {"nama": "engine_sha", "ok": True, "level": "INFO", "detail": s[:16]}


def check_deadman() -> dict:
    age = _age_h(DEADMAN_HB)
    if age is None:
        return {"nama": "deadman", "ok": False, "level": "WARN",
                "detail": "heartbeat deadman tidak ada — belum terpasang"}
    return {"nama": "deadman", "ok": age <= 0.5, "level": "WARN",
            "detail": f"heartbeat {age:.2f}j lalu"}


def check_equity() -> dict:
    age = _age_h(EQUITY)
    if age is None:
        return {"nama": "equity_ledger", "ok": False, "level": "WARN",
                "detail": "EQUITY_LEDGER.jsonl belum ada (wajib ada sebelum arm; diisi sejak hari live)"}
    return {"nama": "equity_ledger", "ok": age <= 28, "level": "WARN",
            "detail": f"baris terakhir {age:.1f}j lalu"}


def check_klines() -> dict:
    if not KLINES.is_dir():
        return {"nama": "klines_1h", "ok": False, "level": "WARN", "detail": "direktori tidak ada"}
    files = sorted(KLINES.glob("*.json"))
    if not files:
        return {"nama": "klines_1h", "ok": False, "level": "WARN", "detail": "tidak ada file"}
    # Simbol yang sudah delisted (tidak ada di universe venue) tidak boleh
    # dihitung stale — file-nya memang tidak akan pernah segar lagi.
    # Bukti: API venue live 2026-11-20 -> BASED/BREV/KIOXIA/NATGAS/SNDK/SOSO/TAO/TON
    # tidak ada di 98 simbol aktif. Universe dibaca dari cache collector, tanpa network.
    universe: set[str] | None = None
    try:
        cache = json.loads((ROOT / "data/sodex_klines/.symbols.json").read_text())
        syms = cache if isinstance(cache, list) else cache.get("symbols", [])
        universe = {str(s).replace("-USD", "") for s in syms}
    except Exception:
        universe = None  # tanpa cache: fallback perilaku lama
    ages_all, ages_live, delisted = [], [], 0
    for f in files:
        sym = f.name.replace("-USD.json", "")
        a = _age_h(f) or 1e9
        ages_all.append(a)
        if universe is not None and sym not in universe:
            delisted += 1
        else:
            ages_live.append(a)
    series = ages_live if universe is not None else ages_all
    med = sorted(series)[len(series) // 2]
    stale = sum(1 for a in series if a > 6)
    detail = f"{len(files)} file, median {med:.1f}j, stale>6j: {stale}"
    if delisted:
        detail += f", delisted-diskip: {delisted}"
    return {"nama": "klines_1h", "ok": stale == 0, "level": "WARN", "detail": detail}


def check_fleet() -> dict:
    try:
        r = subprocess.run([sys.executable, str(ROOT / "scripts/paper_fleet_report.py"), "--json"],
                           capture_output=True, text=True, timeout=120)
        d = json.loads(r.stdout)
        down = d.get("summary", {}).get("DOWN", 0) + d.get("summary", {}).get("STALE", 0)
        return {"nama": "paper_fleet", "ok": down == 0, "level": "WARN",
                "detail": f"DOWN+STALE={down}"}
    except Exception as e:
        return {"nama": "paper_fleet", "ok": False, "level": "WARN", "detail": f"gagal: {e}"}


def check_promo_gate() -> dict:
    if not EQUITY.exists():
        return {"nama": "promo_gate", "ok": False, "level": "BLOCKER",
                "detail": "DATA_KURANG (EQUITY_LEDGER belum ada — gate tidak bisa dievaluasi)"}
    try:
        r = subprocess.run([sys.executable, str(ROOT / "scripts/sodex_target_promotion_gate.py"),
                            "--equity-file", str(EQUITY)], capture_output=True, text=True, timeout=120)
        return {"nama": "promo_gate", "ok": r.returncode == 0,
                "level": "WARN" if r.returncode == 0 else "BLOCKER",
                "detail": {0: "LOLOS", 3: "DATA_KURANG"}.get(r.returncode, f"exit {r.returncode}")}
    except Exception as e:
        return {"nama": "promo_gate", "ok": False, "level": "WARN", "detail": f"gagal: {e}"}


def check_reconciliation() -> dict:
    """Rekonsiliasi wajib segar; file hilang/rusak/basi adalah BLOCKER."""
    try:
        d = json.loads(WATCHDOG_STATUS.read_text())
        ts = datetime.fromisoformat(d.get("ts") or d.get("checked_utc"))
        max_age = float(d.get("max_age_sec", 0))
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        ok = d.get("status") == "OK" and 0 <= age <= max_age and not d.get("critical")
        detail = ("OK" if ok else
                  f"status={d.get('status')}, umur={age:.0f}s/batas={max_age:.0f}s, "
                  f"critical={len(d.get('critical') or [])}")
        return {"nama": "reconcile", "ok": ok, "level": "BLOCKER", "detail": detail}
    except Exception as e:
        return {"nama": "reconcile", "ok": False, "level": "BLOCKER",
                "detail": f"status segar tidak tersedia: {e}"}


def check_disk() -> dict:
    gb = shutil.disk_usage(ROOT).free / 1e9
    return {"nama": "disk", "ok": gb >= 5, "level": "WARN", "detail": f"{gb:.1f} GB bebas"}


def check_orders_blocked() -> dict:
    """Pastikan tidak ada artefak arm yang tertinggal dari percobaan."""
    probe = ROOT / "secrets/LIVE_ARMED_PROBE.json"
    return {"nama": "probe_sisa", "ok": True, "level": "INFO",
            "detail": "ada file probe (tidak dibaca oleh engine)" if probe.exists() else "bersih"}


CHECKS = (check_kill, check_env, check_arm, check_engine, check_equity,
          check_deadman, check_klines, check_fleet, check_reconciliation,
          check_promo_gate, check_disk, check_orders_blocked)


def run(today: date | None = None) -> dict:
    ph = phase(today or datetime.now(timezone.utc).date())
    checks = []
    for fn in CHECKS:
        c = fn()
        c["level"] = escalate(c["level"], ph, "BEKU")
        checks.append(c)
    v = verdict(checks)
    return {"fase": ph, "tanggal": (today or datetime.now(timezone.utc).date()).isoformat(),
            "verdict": v, "checks": checks}


def main() -> int:
    try:
        res = run()
        v = res["verdict"]
        print(f"PREFLIGHT LIVE SoDEX — {res['tanggal']} — fase {res['fase']}")
        print(f"Status: {v['status']} (lulus {v['lulus']}/{v['total']}, "
              f"blocker {v['blocker']}, warn {v['warn']})")
        for c in res["checks"]:
            mark = "OK  " if c["ok"] else ("BLOCK" if c["level"] == "BLOCKER" else "WARN ")
            print(f"  [{mark}] {c['nama']:<14} {c['detail']}")
        if v["blocker_nama"]:
            print(f"Blocker: {', '.join(v['blocker_nama'])}")
        return 0 if v["status"] == "SIAP" else 3
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
