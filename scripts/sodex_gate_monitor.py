#!/usr/bin/env python3
"""SoDEX GATE MONITOR — alert otomatis saat gate LONG realwide terbuka (Jalur A).

Live realwide sdh lulus target & siap entry. Penghalang satu-satunya =
macro-BTC gate (BTC<MA50 -> LONG blocked). Script ini cek tiap beberapa
menit; begitu gate terbuka (LONG boleh), tulis ALERT + simpan timestamp.

Dipakai: piggyback ke watchdog, ATAU timer mandiri.
Read-only. Tidak mengirim order.
"""
from __future__ import annotations
import json, sys, time
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
import realwide_micro_live as m

STATE_FILE = PROJECT / "data" / "sodex_gate_monitor_state.json"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def main():
    try:
        mb, mr = m.macro_btc_long_blocked()
    except Exception as e:
        print(f"[GATE-MON] ERR: {e}")
        return 2

    state = {"checked": now_iso(), "long_blocked": mb, "reason": mr}
    # Tambahkan regime-switch verdict (2026-09-05, riset bearish)
    try:
        sys.path.insert(0, str(PROJECT / "scripts"))
        import regime_switch_gate as rg
        reg = rg.classify()
        state["regime"] = reg.get("verdict")
        state["regime_score"] = reg.get("score")
    except Exception:
        pass
    state["market_mode"] = ("BEAR/sideways" if (mb or state.get("regime") in ("BEAR", "NEUTRAL"))
                            else "TREND")
    prev = {}
    if STATE_FILE.exists():
        try:
            prev = json.loads(STATE_FILE.read_text())
        except Exception:
            prev = {}

    # Deteksi transisi: tadinya blocked, sekarang terbuka
    was_blocked = prev.get("long_blocked", True)
    if not mb and was_blocked:
        state["gate_opened_at"] = now_iso()
        print(f"*** GATE LONG TERBUKA! *** {now_iso()} | {mr} | LIVE REALWIDE BISA ENTRY")
        with open(PROJECT / "data" / "sodex_gate_opened.log", "a") as f:
            f.write(f"{now_iso()} GATE_OPEN {mr}\n")
    elif not mb:
        print(f"[GATE-MON] LONG BUKA (sudah dari sblmnya) | {mr}")
    else:
        print(f"[GATE-MON] LONG TUTUP | {mr}")

    STATE_FILE.write_text(json.dumps(state, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())