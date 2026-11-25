#!/usr/bin/env python3
"""STABILITAS SODEX - health & target check berkelanjutan (2026-09-05)."""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
DATA = PROJECT / "data"
# Kanonik 2026-09-27 (user GO): >=0,8% dari TOTAL modal wallet per window 30 jam.
# Nilai 0,7 lama membuat monitor menyatakan LULUS untuk hasil yang sebenarnya
# BELUM mencapai target (monitor lebih longgar dari kontrak).
TARGET = 0.8
LIVE = ["anantara-realwide-livetest", "anantara-spot-livetest"]
ALERT_LOG = DATA / "sodex_stability_alerts.jsonl"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def log(level, msg, **extra):
    rec = {"ts": now_iso(), "level": level, "msg": msg, **extra}
    with open(ALERT_LOG, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    print(f"[{level}] {msg}")
    return rec


def _positive_float(value):
    try:
        out = float(value)
        return out if out > 0 else None
    except (TypeError, ValueError):
        return None


def read_wallet_denominator() -> float:
    """Target denominator = total SoDEX wallet; env override, then monitor snapshot."""
    env_wallet = _positive_float(os.environ.get("SODEX_TOTAL_WALLET"))
    if env_wallet is not None:
        return env_wallet
    latest = DATA / "sodex_monitor_eval" / "latest.json"
    try:
        payload = json.loads(latest.read_text())
        account_value = payload.get("account", {}).get("account_value", {})
        wallet = _positive_float(account_value.get("total_equity_usd"))
        if wallet is not None:
            return wallet
    except Exception:
        pass
    return 108.10


def check_services():
    """Cek lane uang nyata — tapi HORMATI freeze operator.

    AUDIT 30-Sep-2026: lane yang sengaja di-disable (fail-closed setelah insiden
    eksekusi) dilaporkan CRITICAL tiap 5 menit = alarm fatigue, sama seperti
    insiden 9.528 alarm palsu. Unit yang memang dinonaktifkan tidak boleh
    dianggap 'down': dilaporkan sekali sebagai INFO, bukan CRITICAL.
    """
    alerts = []
    for svc in LIVE:
        try:
            st = subprocess.run(["systemctl", "--user", "is-active", svc],
                                capture_output=True, text=True, timeout=15).stdout.strip()
            if st == "active":
                continue
            enabled = subprocess.run(["systemctl", "--user", "is-enabled", svc],
                                     capture_output=True, text=True, timeout=15).stdout.strip()
            if enabled == "disabled":
                log("INFO", f"service {svc} dinonaktifkan operator ({st}) — bukan DOWN")
                continue
            alerts.append(log("CRITICAL", f"service {svc} tidak aktif: {st}"))
        except Exception as e:
            alerts.append(log("WARNING", f"gagal cek {svc}: {e}"))
    return alerts


def _load_tracker():
    """Ambil definisi window kanonik dari tracker (satu sumber kebenaran)."""
    import importlib.util
    p = PROJECT / "scripts" / "sodex_maturation_tracker.py"
    spec = importlib.util.spec_from_file_location("sodex_maturation_tracker", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def check_targets():
    """Periksa track realwide (PAPER) terhadap target kanonik per-WINDOW 30 jam.

    AUDIT 30-Sep-2026: versi lama memakai `rsum / wallet / len(recent) * 100`
    = ROI rata-rata PER-TRADE, lalu membandingkannya dengan target PER-WINDOW
    30 jam — dua satuan berbeda. Angka itu tidak bisa dipakai sebagai bukti
    capaian target. Kini memakai `window_metrics()` dari tracker, definisi yang
    sama dengan gate; median + hit-rate ikut dilaporkan agar kelemahan
    mean-driven (mean lolos karena outlier) terlihat, bukan tersembunyi.
    """
    alerts = []
    try:
        tracker = _load_tracker()
        d = json.loads((DATA / "paper_test_realwide_state.json").read_text())
        closed = d.get("closed", [])
        wallet = read_wallet_denominator()
        wm = tracker.window_metrics(closed, wallet) if closed else None
        if wm:
            msg = (f"REALWIDE(paper) n={len(closed)} | window30h "
                   f"mean={wm['mean_pct']:+.2f}% median={wm['median_pct']:+.2f}% "
                   f"hit={wm['hit']}/{wm['n_windows']} ({wm['hit_rate']*100:.0f}%) "
                   f"| target {TARGET}%")
            if wm["mean_pct"] >= TARGET:
                alerts.append(log("GOAL", msg + " -> LULUS (mean)"))
            else:
                log("INFO", msg)
        else:
            log("INFO", f"REALWIDE(paper) n={len(closed)} — window 30h belum "
                        f"cukup untuk diukur (butuh >=2 trade ber-exit_ts)")
    except Exception as e:
        alerts.append(log("WARNING", f"cek realwide target gagal: {e}"))
    return alerts


def main():
    alerts = []
    alerts += check_services()
    alerts += check_targets()
    critical = [a for a in alerts if a["level"] == "CRITICAL"]
    if critical:
        sys.exit(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())