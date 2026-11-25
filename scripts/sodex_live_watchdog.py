#!/usr/bin/env python3
"""SoDEX LIVE WATCHDOG — rekonsiliasi otonom state-lokal vs exchange nyata.

Dijalankan berkala (timer). Membandingkan:
1. Posisi yang dicatat state file (open) vs posisi REAL di exchange
   (endpoint benar) -> deteksi phantom / posisi hilang.
2. Balance REAL exchange vs balance snapshot sebelumnya -> deteksi
   pergerakan dana tak terjelaskan (anomali > threshold).
3. Kesehatan proses live (3 service systemd) -> deteksi crash/hang.

Report ke data/sodex_watchdog_alerts.jsonl (append-only, untuk audit trail).
Exit code != 0 jika ada ALERT level CRITICAL (untuk dipakai systemd OnFailure).
"""
from __future__ import annotations
import json, math, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sodex_realtime_sync import full_sync, PROJECT
import sodex_realtime_sync as s

ALERT_LOG = PROJECT / "data" / "sodex_watchdog_alerts.jsonl"
STATUS_FILE = PROJECT / "data" / "sodex_watchdog_status.json"
PREV_SNAP = PROJECT / "data" / "sodex_watchdog_prev.json"
SPOT_RESIDUAL_SNAP = PROJECT / "data" / "sodex_watchdog_spot_residuals.json"
MANUAL_PERPS_SNAP = PROJECT / "data" / "sodex_watchdog_manual_perps.json"
MANUAL_PERPS_RISK_SNAP = PROJECT / "data" / "sodex_watchdog_manual_perps_risk.json"
BALANCE_JUMP_THRESHOLD_USD = 1.0  # perubahan balance > ini tanpa closed trade baru = alert
MANUAL_PERP_WARN_LOSS_USD = float(os.environ.get("SODEX_MANUAL_PERP_WARN_LOSS_USD", "1.0"))
# Journal order/fill daemon live (ditulis anantara/sodex_farming.py:cli).
# Sumber kebenaran "posisi ini DIKELOLA daemon", bukan posisi asing.
DAEMON_FILL_JOURNAL = PROJECT / "data" / "sodex_daemon_fills.jsonl"
DAEMON_JOURNAL_DAYS = float(os.environ.get("SODEX_DAEMON_JOURNAL_DAYS", "7"))
DAEMON_JOURNAL_SNAP = PROJECT / "data" / "sodex_watchdog_daemon_managed.json"

# Owner-confirmed 2026-09-14: small SoDEX spot/vToken residuals from prior
# farm/venue activity. They must stay visible, but not keep the watchdog in
# CRITICAL every 3 minutes. Any new/unclassified spot coin remains CRITICAL.
CLASSIFIED_SPOT_RESIDUALS = {
    "WSOSO", "vARB", "vETH", "vPEPE", "vLINK", "vsMAG7.ssi", "vBTC",
    "vHYPE", "vUSSI", "aUNITREE", "vXLM", "vMAG7.ssi", "vSHIB", "vAVAX",
}

# Owner-confirmed 2026-09-14: manual/legacy perp position known to Owner.
# Keep visible as WARNING on size change; any other untracked perp stays CRITICAL.
CLASSIFIED_MANUAL_PERPS = {"AAVE-USD": 0.35}

LIVE_SERVICES = [
    "anantara-realwide-livetest.service",
    "anantara-spot-livetest.service",
    # perps-short DIMATIKAN PERMANEN 2026-09-04 (signal dari skrip riset tak
    # tervalidasi, 0 data backtest). Jangan alert - lihat
    # reports/SODEX_PERPS_SHORT_DISABLED_2026-09-04.md
]

STATE_FILES = {
    "realwide": PROJECT / "data" / "realwide_micro_live_state.json",
    "perps_short": PROJECT / "data" / "perps_short_live_state.json",
}

# Track SPOT dipisah: posisinya holding spot (balance coin), BUKAN perps
# position. Rekonsiliasi perps akan selalu false-positive PHANTOM kalau
# state spot ikut dibandingkan ke endpoint /positions (perps-only).
SPOT_STATE_FILE = PROJECT / "data" / "spot_live_test_state.json"


def now():
    return datetime.now(timezone.utc).isoformat()


def log_alert(level, msg, **extra):
    rec = {"ts": now(), "level": level, "msg": msg, **extra}
    with open(ALERT_LOG, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    print(f"[{level}] {msg}")
    return rec


def _snapshot_changed(path, current):
    """Return True only when a classified snapshot changes."""
    compact = {k: round(float(v), 12) for k, v in sorted(current.items())}
    try:
        prev = json.loads(path.read_text())
    except Exception:
        prev = None
    if prev == compact:
        return False
    path.write_text(json.dumps(compact, sort_keys=True))
    return True


def _classified_spot_residuals_changed(current):
    """Return True only when classified residual set/amount changes."""
    return _snapshot_changed(SPOT_RESIDUAL_SNAP, current)


def _classified_manual_perps_changed(current):
    """Return True only when classified manual perp set/size changes."""
    return _snapshot_changed(MANUAL_PERPS_SNAP, current)


def _position_float(pos, *keys):
    for key in keys:
        try:
            value = pos.get(key)
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _manual_perp_unrealized_pnl(pos):
    """Best-effort unrealized PnL for classified manual perps; never orders."""
    direct = _position_float(
        pos, "unrealized_pnl_calc_usd", "unrealizedPnl", "unrealized_pnl",
        "unrealized_pnl_usd", "unrealizedPnlUsd", "pnl_usd")
    if direct is not None:
        return direct
    entry = _position_float(pos, "entry_price", "entryPrice", "avgEntryPrice")
    mark = _position_float(pos, "mark_price", "markPrice", "lastPrice", "indexPrice")
    size = _position_float(pos, "size", "szi", "qty")
    if entry is None or mark is None or size is None:
        return None
    side = str(pos.get("side") or ("SHORT" if size < 0 else "LONG")).upper()
    qty = abs(size)
    return (entry - mark) * qty if side == "SHORT" else (mark - entry) * qty


def _classified_manual_perp_risk_changed(current):
    rounded = {k: round(float(v), 1) for k, v in sorted(current.items())}
    return _snapshot_changed(MANUAL_PERPS_RISK_SNAP, rounded)


# Status systemd yang dianggap sehat (termasuk transisi singkat — jangan alarm
# palsu saat unit sedang reload/activating).
SVC_OK_STATES = {"active", "activating", "reloading"}


def classify_service(svc, state, enabled):
    """Klasifikasi satu unit systemd → (level, pesan) atau (None, None).

    PERBAIKAN 1-Okt-2026: lane yang SENGAJA dibekukan (unit `disabled` +
    berhenti bersih, mis. realwide-livetest & spot-livetest saat uang nyata
    dibekukan) dulu dilaporkan CRITICAL setiap 3 menit. Alarm palsu seperti itu
    melatih operator mengabaikan alarm ASLI — jadi unit disabled+inactive kini
    INFO (tetap tampil di log, tapi tidak membunyikan CRITICAL), sementara unit
    yang ENABLED tapi mati/gagal tetap CRITICAL.
    """
    state = (state or "").strip()
    enabled = (enabled or "").strip()
    if state in SVC_OK_STATES:
        return None, None
    if state == "failed":
        return "CRITICAL", f"Service {svc} GAGAL (state=failed)"
    if state == "inactive" and enabled == "disabled":
        return "INFO", (f"Service {svc} dibekukan sengaja (disabled+inactive) "
                        "— bukan alarm; aktifkan unitnya bila mau dipantau lagi")
    return "CRITICAL", (f"Service {svc} tidak aktif: {state or 'unknown'} "
                        f"(enabled={enabled or 'unknown'})")


def check_services():
    alerts = []
    for svc in LIVE_SERVICES:
        st = subprocess.run(["systemctl", "--user", "is-active", svc],
                            capture_output=True, text=True).stdout
        en = subprocess.run(["systemctl", "--user", "is-enabled", svc],
                            capture_output=True, text=True).stdout
        level, msg = classify_service(svc, st, en)
        if level:
            alerts.append(log_alert(level, msg))
    return alerts


def load_local_open_positions():
    """Kumpulkan semua posisi 'open' menurut state file lokal (perps only,
    spot dicek terpisah via holdings)."""
    out = {}
    for track, path in STATE_FILES.items():
        if not path.exists():
            continue
        try:
            d = json.loads(path.read_text())
        except Exception as e:
            log_alert("WARNING", f"Gagal parse state {track}: {e}")
            continue
        for k, v in d.get("open", {}).items():
            out[f"{track}:{k}"] = v
    return out


def load_daemon_journal_symbols(max_age_days: float = DAEMON_JOURNAL_DAYS):
    """Symbol posisi yang dibuka/ditutup oleh daemon live menurut fill journal.

    Entri place non-reduce-only yang ok=True menandai symbol sebagai milik
    daemon (fill bisa datang belakangan dengan status NEW). Entri reduce-only
    yang TERISI menghapus symbol. Journal hilang/rusak -> set kosong (fail-open
    ke deteksi CRITICAL, bukan diam-diam menganggap aman).
    """
    syms: set[str] = set()
    if not DAEMON_FILL_JOURNAL.exists():
        return syms
    cutoff = datetime.now(timezone.utc).timestamp() - max_age_days * 86400
    try:
        lines = DAEMON_FILL_JOURNAL.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return syms
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        sym = str(rec.get("symbol") or "").upper()
        if not sym or not rec.get("ok"):
            continue
        try:
            ts = datetime.fromisoformat(str(rec.get("ts"))).timestamp()
        except (TypeError, ValueError):
            ts = 0.0
        if ts < cutoff:
            continue
        argv = [str(a).lower() for a in (rec.get("argv") or [])]
        reduce_only = "--reduce-only" in argv or "reduce-only" in argv
        try:
            filled = float(rec.get("filled_qty") or 0)
        except (TypeError, ValueError):
            filled = 0.0
        status = str(rec.get("status") or "").upper()
        is_fill = filled > 0 or status in ("FILLED", "PARTIALLY_FILLED")
        if not reduce_only:
            # Order entry yang DITERIMA venue sudah cukup: fill bisa terjadi
            # setelah respons place (status NEW), dan posisi hasil fill itu
            # tetap milik daemon. Tanpa ini watchdog memberi CRITICAL palsu.
            syms.add(sym)
        elif is_fill:
            # reduce-only TERISI = posisi ditutup -> lepas dari daftar.
            syms.discard(sym)
    return syms


def _daemon_managed_changed(new: set[str]) -> bool:
    try:
        prev = set(json.loads(DAEMON_JOURNAL_SNAP.read_text()).get("symbols", []))
    except Exception:
        prev = set()
    if prev == new:
        return False
    DAEMON_JOURNAL_SNAP.parent.mkdir(parents=True, exist_ok=True)
    DAEMON_JOURNAL_SNAP.write_text(json.dumps({
        "symbols": sorted(new),
        "updated": datetime.now(timezone.utc).isoformat(),
    }, indent=2))
    return True


def expected_address():
    """Akun target dari environment yang sama dengan fetch; tidak boleh dari cache."""
    return str(os.environ.get("SODEX_ADDRESS") or "")


def balances_are_valid(snap: dict) -> bool:
    """Identity serta denominator trading wajib valid; error API = tidak sehat."""
    try:
        target = s.ADDRESS
    except RuntimeError:
        target = expected_address()
    if not target or snap.get("address") != target:
        return False
    if any(str(key).endswith("_error") for key in snap):
        return False
    try:
        positions = snap["perps_positions"]
        if not isinstance(positions, list):
            return False
    except KeyError:
        return False
    for key in ("perps_balance", "spot_vusdc"):
        total = (snap.get(key) or {}).get("total")
        if total is None:
            return False
        try:
            value = float(total)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(value) or value <= 0:
            return False
    return True


def snapshot_validity(snap):
    alerts = []
    if not balances_are_valid(snap):
        try:
            target = s.ADDRESS
        except RuntimeError:
            target = expected_address()
        if not target or snap.get("address") != target:
            alerts.append(log_alert(
                "CRITICAL",
                "RECONCILIATION_ACCOUNT: snapshot bukan akun target atau alamat tidak tersedia",
            ))
        else:
            alerts.append(log_alert(
                "CRITICAL",
                "RECONCILIATION_INCOMPLETE: balance/order/spot tidak terkonfirmasi valid",
            ))
    return alerts


def refresh_interval_seconds() -> float:
    """Toleransi timer aktual + margin; systemd hanya dievaluasi saat test."""
    import re
    try:
        out = subprocess.check_output([
            "systemctl", "--user", "show", "anantara-sodex-watchdog.timer",
            "--property=TimersMonotonic", "--value",
        ], text=True, timeout=10)
        pair = re.search(r"OnUnitActiveUSec=([0-9]+)us", out)
        if pair:
            seconds = int(pair.group(1)) / 1_000_000
            if 60 <= seconds <= 900:
                return seconds + 90
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return 600.0


def check_reconciliation():
    """Bandingkan posisi lokal vs REAL exchange (perps only).

    `full_sync` gagal total mengembalikan None: itu bukan akun kosong. Fail-closed
    agar outage API tidak menghasilkan VERIFY_OK palsu / alarm PHANTOM palsu.
    """
    alerts = []
    snap = full_sync(verbose=False)
    if not isinstance(snap, dict):
        alerts.append(log_alert(
            "CRITICAL",
            "RECONCILIATION_UNAVAILABLE: sinkronisasi venue tidak menghasilkan snapshot",
        ))
        return alerts, snap
    raw_positions = snap.get("perps_positions")
    if not isinstance(raw_positions, list):
        alerts.append(log_alert(
            "CRITICAL",
            "RECONCILIATION_UNAVAILABLE: daftar posisi venue tidak valid",
        ))
        return alerts, snap
    real_positions = raw_positions
    real_syms = {p["symbol"] for p in real_positions}

    missing = [key for key in (
        "perps_balance", "spot_balances", "perps_open_orders", "spot_vusdc",
    ) if key not in snap]
    if missing or not balances_are_valid(snap):
        alerts.append(log_alert(
            "CRITICAL",
            "RECONCILIATION_INCOMPLETE: balance/order/spot tidak terkonfirmasi valid "
            f"(missing={missing})",
            missing=missing,
        ))

    local = load_local_open_positions()
    daemon_syms = load_daemon_journal_symbols()
    local_syms = set()
    for key, pos in local.items():
        sym = pos.get("sym") or pos.get("pair") or pos.get("coin", "")
        local_syms.add(str(sym).upper())

    if daemon_syms and _daemon_managed_changed(daemon_syms):
        alerts.append(log_alert(
            "WARNING",
            "DAEMON-MANAGED: fill journal mencatat posisi dikelola daemon "
            f"({sorted(daemon_syms)}) — bukan UNTRACKED, tetap dipantau",
            daemon_managed=sorted(daemon_syms)))

    # Phantom: state lokal bilang ada posisi, exchange bilang tidak.
    for key, pos in local.items():
        sym = str(pos.get("sym") or pos.get("pair") or pos.get("coin", "")).upper()
        matched = any(sym in s.upper() or s.upper() in sym for s in real_syms)
        if not matched and real_syms is not None:
            alerts.append(log_alert(
                "CRITICAL",
                f"PHANTOM: state lokal '{key}' klaim posisi {sym} tapi TIDAK ADA di exchange nyata",
                local_position=pos, real_positions=real_positions))

    # UNTRACKED: exchange punya posisi yang state lokal TIDAK tahu.
    classified_manual_perps = {}
    classified_manual_perp_risk = {}
    for p in real_positions:
        sym = p["symbol"].upper()
        # ASTER-USD = posisi TESTING MANUAL USER (approved 2026-09-06) —
        # sistem otomatis TIDAK membukanya; jangan alert sebagai phantom.
        # ETH-USD juga posisi manual user (04:01 UTC, lev5) — skip juga.
        if sym.startswith("ASTER") or sym.startswith("ETH"):
            continue
        matched = any(sym in s or s in sym for s in local_syms)
        if matched:
            continue
        if any(sym in s or s in sym for s in daemon_syms):
            continue
        expected_size = CLASSIFIED_MANUAL_PERPS.get(sym)
        try:
            real_size = abs(float(p.get("size") or 0))
        except (TypeError, ValueError):
            real_size = 0.0
        if expected_size is not None and abs(real_size - expected_size) <= 1e-9:
            classified_manual_perps[sym] = real_size
            pos_for_risk = dict(p)
            mark = (snap.get("perps_marks") or {}).get(sym, {}).get("markPrice")
            if mark is not None:
                pos_for_risk.setdefault("markPrice", mark)
            pnl = _manual_perp_unrealized_pnl(pos_for_risk)
            if pnl is not None and pnl <= -MANUAL_PERP_WARN_LOSS_USD:
                classified_manual_perp_risk[sym] = pnl
            continue
        alerts.append(log_alert(
            "CRITICAL",
            f"UNTRACKED: exchange punya posisi REAL {sym} size={p['size']} "
            f"yang TIDAK tercatat di state manapun — cek dashboard SEGERA",
            real_position=p))

    if classified_manual_perps and _classified_manual_perps_changed(classified_manual_perps):
        alerts.append(log_alert(
            "WARNING",
            "CLASSIFIED MANUAL PERP: owner-confirmed SoDEX manual/legacy perp "
            f"terdeteksi ({len(classified_manual_perps)} posisi); tidak dianggap CRITICAL, "
            "akan alert lagi hanya jika symbol/size berubah",
            manual_perps=classified_manual_perps))

    if classified_manual_perp_risk and _classified_manual_perp_risk_changed(classified_manual_perp_risk):
        alerts.append(log_alert(
            "WARNING",
            "CLASSIFIED MANUAL PERP LOSS: posisi manual/legacy SoDEX sedang rugi; "
            "watchdog tidak menutup order otomatis — operator harus putuskan close/hold",
            unrealized_pnl_usd=classified_manual_perp_risk,
            threshold_usd=-MANUAL_PERP_WARN_LOSS_USD))

    if not alerts:
        log_alert("OK", f"Rekonsiliasi bersih: {len(local)} posisi lokal, "
                         f"{len(real_positions)} posisi real, match 100%")
    return alerts, snap


def check_spot_reconciliation():
    """Reconcile local spot state against every non-zero spot holding."""
    alerts = []
    if not SPOT_STATE_FILE.exists():
        return alerts
    try:
        st = json.loads(SPOT_STATE_FILE.read_text())
    except Exception as e:
        alerts.append(log_alert("WARNING", f"Gagal parse state spot: {e}"))
        return alerts

    try:
        from sodex_realtime_sync import real_spot_balance
        bal = {b["coin"]: float(b.get("total") or 0) for b in real_spot_balance()}
    except Exception as e:
        alerts.append(log_alert("WARNING", f"Gagal ambil spot balance: {e}"))
        return alerts

    open_pos = st.get("open", {})
    expected = set()
    for key, pos in open_pos.items():
        raw_coin = str(pos.get("spot_sym") or pos.get("pair") or key)
        expected.add(raw_coin if raw_coin.startswith("v") else "v" + raw_coin.upper())
    allow = {
        "v" + coin.strip().upper()
        for coin in os.environ.get("SODEX_MANUAL_SPOT_ALLOWLIST", "").split(",")
        if coin.strip()
    }
    classified_residuals = {}
    for coin, qty in bal.items():
        if coin == "vUSDC" or qty <= 0:
            continue
        if coin in expected or coin in allow:
            continue
        if coin in CLASSIFIED_SPOT_RESIDUALS:
            classified_residuals[coin] = qty
            continue
        alerts.append(log_alert(
            "CRITICAL",
            f"UNTRACKED SPOT: exchange memiliki {coin}={qty}, "
            "tetapi tidak ada di state lokal/open position",
            exchange_coin=coin, held=qty))

    if classified_residuals and _classified_spot_residuals_changed(classified_residuals):
        alerts.append(log_alert(
            "WARNING",
            "CLASSIFIED SPOT RESIDUAL: owner-confirmed SoDEX spot residue "
            f"terdeteksi ({len(classified_residuals)} coin); tidak dianggap CRITICAL, "
            "akan alert lagi hanya jika daftar/jumlah berubah",
            residuals=classified_residuals))

    for key, pos in open_pos.items():
        raw_coin = str(pos.get("spot_sym") or pos.get("pair") or key)
        coin = raw_coin[1:] if raw_coin.startswith("v") else raw_coin.upper()
        vcoin = raw_coin if raw_coin.startswith("v") else "v" + raw_coin.upper()
        held = bal.get(vcoin, 0.0)
        want = float(pos.get("qty") or 0)
        if held < want * 0.5:
            alerts.append(log_alert(
                "CRITICAL",
                f"PHANTOM SPOT: state klaim {coin} qty={want} tapi balance "
                f"{vcoin}={held} di exchange", local_position=pos, held=held))
        else:
            log_alert("OK", f"Spot {coin}: state qty={want} vs exchange {vcoin}={held} — match")
    return alerts


def check_balance_anomaly(snap):
    alerts = []
    perps_bal = snap.get("perps_balance") if isinstance(snap, dict) else None
    spot_bal = snap.get("spot_vusdc") if isinstance(snap, dict) else None
    if not perps_bal or not spot_bal:
        alerts.append(log_alert("WARNING", "Gagal ambil balance real utk cek anomali"))
        return alerts

    cur = {"perps": float(perps_bal["total"]), "spot": float(spot_bal["total"])}
    if PREV_SNAP.exists():
        try:
            prev = json.loads(PREV_SNAP.read_text())
            for k in ("perps", "spot"):
                d = abs(cur[k] - prev.get(k, cur[k]))
                if d > BALANCE_JUMP_THRESHOLD_USD:
                    alerts.append(log_alert(
                        "WARNING",
                        f"Balance {k} berubah ${d:.4f} sejak cek terakhir "
                        f"(${prev.get(k)} -> ${cur[k]}) — verifikasi wajar (trade normal) atau anomali",
                    ))
        except Exception as e:
            log_alert("WARNING", f"Gagal baca prev snapshot: {e}")
    PREV_SNAP.write_text(json.dumps(cur))
    return alerts


def status_timestamp(status: dict) -> str:
    """Timestamp status valid, format ISO-8601 UTC."""
    return str(status["ts"] if status.get("ts") else status["checked_utc"])


def write_status(status: dict, path=STATUS_FILE):
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(status, ensure_ascii=True, indent=2))
    tmp.replace(path)


def main():
    print(f"=== SODEX LIVE WATCHDOG — {now()} ===")
    all_alerts = []
    all_alerts += check_services()
    recon_alerts, snap = check_reconciliation()
    all_alerts += recon_alerts
    all_alerts += check_spot_reconciliation()
    all_alerts += check_balance_anomaly(snap)

    # Piggyback maturasi tracker (read-only, murah) — supaya progres geometri
    # baru termonitor tiap siklus watchdog tanpa service tambahan.
    try:
        import subprocess
        subprocess.run([sys.executable,
                        str(PROJECT / "scripts" / "sodex_maturation_tracker.py")],
                       capture_output=True, timeout=30)
    except Exception:
        pass  # non-kritis, jangan ganggu watchdog utama

    # Piggyback gate monitor (Jalur A): alert seketika saat gate LONG terbuka.
    try:
        subprocess.run([sys.executable,
                        str(PROJECT / "scripts" / "sodex_gate_monitor.py")],
                       capture_output=True, timeout=40)
    except Exception:
        pass  # non-kritis

    # Piggyback stability check (health + target berkelanjutan).
    try:
        subprocess.run([sys.executable,
                        str(PROJECT / "scripts" / "sodex_stability_check.py")],
                       capture_output=True, timeout=40)
    except Exception:
        pass  # non-kritis

    # Piggyback dashboard generator (self-contained HTML, selalu fresh).
    try:
        subprocess.run([sys.executable,
                        str(PROJECT / "scripts" / "sodex_dashboard_gen.py")],
                       capture_output=True, timeout=40)
    except Exception:
        pass  # non-kritis

    critical = [a for a in all_alerts if a["level"] == "CRITICAL"]
    status = {
        "ts": now(),
        "checked_utc": now(),
        "status": ("CRITICAL" if critical else "OK"),
        "critical": [{"level": a["level"], "msg": a["msg"]} for a in critical],
        "warning_count": sum(a["level"] == "WARNING" for a in all_alerts),
        "max_age_sec": refresh_interval_seconds(),
        "source": "sodex-live-watchdog",
    }
    write_status(status)
    print(f"Total alert: {len(all_alerts)} ({len(critical)} CRITICAL)")
    if critical:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        stamp = now()
        write_status({
            "ts": stamp, "checked_utc": stamp, "status": "ERROR",
            "critical": [{"level": "CRITICAL",
                          "msg": f"WATCHDOG_ERROR: {type(exc).__name__}: {exc}"}],
            "warning_count": 0, "max_age_sec": refresh_interval_seconds(),
            "source": "sodex-live-watchdog",
        })
        print(f"[CRITICAL] WATCHDOG_ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
