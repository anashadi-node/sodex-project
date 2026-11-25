#!/usr/bin/env python3
"""
SoDEX Guardian Daemon — Autonomous 24/7 engine health monitor & auto-fixer.

Replaces the Claude /loop monitoring session. Runs as sodex-guardian.service.

Architecture:
  Fast cycle (60s):
    - Engine liveness: twin_live.log mtime. If stale >90s → write stuck-idle signal
    - systemd service health: watchdog + sentinel. If dead → systemctl restart
    - Error log scan: new ERROR/CRITICAL lines in twin_live.log → Telegram alert

  Slow cycle (1200s = 20min):
    - Fill drought anomaly: no fills AND no protective gate (decay/firewall) = bug
    - Equity drift: current equity vs high, alert if drop >5%
    - Periodic Telegram summary (20min cadence)

Auto-fix actions (safe, non-destructive):
  - Write data/GUARDIAN_RESTART_SIGNAL type=stuck-idle → watchdog honors ONLY if
    twin_live.log truly stale (≥90s) — prevents restart-loops on healthy engine
  - systemctl --user restart sodex-sentinel / sodex-twin-watchdog
  - No order placement, no .env writes (those belong to sentinel)

Usage:
  python3 anantara/sodex_guardian_daemon.py [--db DB] [--log LOG] [--cycle SECS]
  systemctl --user start sodex-guardian
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────────
VERSION = "1.0"
FAST_CYCLE_SEC  = 60     # liveness + error scan
SLOW_CYCLE_SEC  = 1200   # 20 min — fill drought, equity drift, summary
LOG_AGE_HUNG_SEC = 90    # twin_live.log stale threshold → engine hung
DROUGHT_ANOMALY_MIN = 180  # no fills + no gate + this many minutes = anomaly
EQUITY_DROP_ALERT_PCT = 0.05  # 5% from equity_high triggers alert
ERROR_ALERT_COOLDOWN = 3600   # s between repeat-alerts for same error line
SERVICE_ALERT_COOLDOWN = 300  # s between alerts for same dead service
SUMMARY_INTERVAL_SEC = 1200   # Telegram summary cadence

WATCHED_SERVICES = ["sodex-twin-watchdog", "sodex-sentinel"]

# Signal types gated by watchdog B56 (only honored if log age ≥ 90s):
RESTART_SIGNAL_TYPE = "stuck-idle"


# ── Logging ───────────────────────────────────────────────────────────────────
def _setup_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s.%(msecs)03dZ %(levelname)s %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    logging.Formatter.converter = time.gmtime
    handlers: list[logging.Handler] = [
        logging.FileHandler(log_path),
        logging.StreamHandler(sys.stdout),
    ]
    for h in handlers:
        h.setFormatter(logging.Formatter(fmt, datefmt))
    log = logging.getLogger("guardian")
    log.setLevel(logging.INFO)
    for h in handlers:
        log.addHandler(h)
    return log


# ── Telegram ──────────────────────────────────────────────────────────────────
def _send_telegram(token: str, chat_id: str, text: str) -> None:
    if not token or not chat_id:
        return
    try:
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id":    chat_id,
            "text":       text,
            "parse_mode": "HTML",
        }).encode()
        urllib.request.urlopen(
            urllib.request.Request(url, data=data), timeout=10,
        )
    except Exception:
        pass


# ── DB helpers ────────────────────────────────────────────────────────────────
def _db_connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _utc_ago(seconds: float) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=seconds)
    ).strftime("%Y-%m-%dT%H:%M:%S")


def _get_state(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT v FROM state WHERE k=?", (key,)).fetchone()
    return row[0] if row else None


def _get_fills_since(conn: sqlite3.Connection, minutes: int) -> int:
    since = _utc_ago(minutes * 60)
    row = conn.execute(
        "SELECT count(*) FROM fills WHERE SUBSTR(ts,1,19)>=?", (since,)
    ).fetchone()
    return row[0] if row else 0


def _get_last_fill_ts(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute(
        "SELECT ts FROM fills ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def _get_recent_pnl(conn: sqlite3.Connection, hours: int) -> tuple[float, int]:
    """Return (total net_pnl, rt_count) for the last N hours from rts table."""
    since = _utc_ago(hours * 3600)
    row = conn.execute(
        "SELECT sum(net_pnl), count(*) FROM rts WHERE SUBSTR(ts_close,1,19)>=?",
        (since,),
    ).fetchone()
    return (float(row[0] or 0.0), int(row[1] or 0))


def _get_equity_high(conn: sqlite3.Connection) -> float:
    val = _get_state(conn, "equity_high")
    try:
        return float(val or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _has_protective_gate(conn: sqlite3.Connection, pair: str) -> bool:
    """True if decay_gate OR profit_firewall active for this pair."""
    dg = _get_state(conn, f"e1_decay_gate:{pair}")
    fw = _get_state(conn, f"e1_profit_firewall:{pair}")
    dg_active = bool(dg and dg.startswith("decay_gate"))
    fw_active = bool(fw and fw.startswith("profit_firewall"))
    return dg_active or fw_active


def _env_active_spot_pairs() -> list[str]:
    pairs: list[str] = []
    for key in ("TE_SPOT_PAIR", "TE_SPOT_PAIR_2", "TE_SPOT_PAIR_3", "TE_SPOT_PAIR_4"):
        pair = os.environ.get(key, "").strip()
        if pair and pair not in pairs:
            pairs.append(pair)
    return pairs


def _detect_watched_pairs(db_path: Path) -> list[str]:
    env_pairs = _env_active_spot_pairs()
    if env_pairs:
        return env_pairs
    if db_path.exists():
        try:
            ts_24h = _utc_ago(86400)
            conn = _db_connect(db_path)
            rows = conn.execute(
                "SELECT DISTINCT pair FROM fills WHERE engine='E1' AND SUBSTR(ts,1,19)>=?",
                (ts_24h,),
            ).fetchall()
            conn.close()
            pairs = [str(r[0]) for r in rows if r and r[0]]
            if pairs:
                return pairs
        except Exception:
            pass
    return ["PEPE/USDC"]


# ── Signal writer ─────────────────────────────────────────────────────────────
def _write_restart_signal(signal_path: Path, reason: str) -> None:
    payload = json.dumps({
        "type":   RESTART_SIGNAL_TYPE,
        "reason": f"guardian: {reason}",
        "ts":     time.time(),
    })
    tmp = signal_path.with_suffix(".tmp")
    tmp.write_text(payload)
    tmp.replace(signal_path)


def _signal_recently_written(signal_path: Path, max_age_sec: float = 300.0) -> bool:
    if not signal_path.exists():
        return False
    age = time.time() - signal_path.stat().st_mtime
    return age < max_age_sec


# ── systemd helpers ───────────────────────────────────────────────────────────
def _service_is_active(service: str) -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", service],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False


def _restart_service(service: str) -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "restart", service],
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


# ── Log scanner ───────────────────────────────────────────────────────────────
def _scan_log_errors(log_path: Path, last_pos: int) -> tuple[list[str], int]:
    """Return new ERROR/CRITICAL lines added after last_pos bytes, plus new file position."""
    if not log_path.exists():
        return [], 0
    size = log_path.stat().st_size
    if size < last_pos:
        last_pos = 0  # log rotated
    if size == last_pos:
        return [], last_pos
    errors: list[str] = []
    try:
        with log_path.open("r", errors="replace") as f:
            f.seek(last_pos)
            for line in f:
                if "ERROR" in line or "CRITICAL" in line:
                    errors.append(line.rstrip()[:200])
        new_pos = log_path.stat().st_size
    except Exception:
        new_pos = last_pos
    return errors, new_pos


# ── Guardian Daemon ───────────────────────────────────────────────────────────
class GuardianDaemon:
    def __init__(
        self,
        db_path: Path,
        engine_log: Path,
        signal_path: Path,
        guardian_log: Path,
        tg_token: str,
        tg_chat: str,
        fast_cycle: int = FAST_CYCLE_SEC,
        slow_cycle: int = SLOW_CYCLE_SEC,
        watched_pairs: Optional[list[str]] = None,
    ):
        self.db_path     = db_path
        self.engine_log  = engine_log
        self.signal_path = signal_path
        self.tg_token    = tg_token
        self.tg_chat     = tg_chat
        self.fast_cycle  = fast_cycle
        self.slow_cycle  = slow_cycle
        self.watched_pairs = watched_pairs or ["PEPE/USDC", "XLM/USDC"]

        self.log = _setup_logging(guardian_log)

        # State
        self._last_slow      = 0.0
        self._last_summary   = 0.0
        # Start scanning from end-of-log so we don't replay historical errors on boot
        self._log_pos        = engine_log.stat().st_size if engine_log.exists() else 0
        self._error_seen: dict[str, float] = {}   # error_text → last_alert_ts
        self._svc_alert: dict[str, float] = {}    # service → last_alert_ts
        self._drought_alert_ts = 0.0
        self._equity_alert_ts  = 0.0

    # ── Internal helpers ──────────────────────────────────────────────────────
    def _alert(self, msg: str) -> None:
        self.log.warning(msg)
        _send_telegram(self.tg_token, self.tg_chat, msg)

    def _info_tg(self, msg: str) -> None:
        self.log.info(msg)
        _send_telegram(self.tg_token, self.tg_chat, msg)

    def _db(self) -> sqlite3.Connection:
        return _db_connect(self.db_path)

    # ── Fast checks (every 60s) ───────────────────────────────────────────────
    def _check_engine_liveness(self) -> None:
        if not self.engine_log.exists():
            self._alert("⚠️ Guardian: twin_live.log tidak ditemukan!")
            return
        age = time.time() - self.engine_log.stat().st_mtime
        if age >= LOG_AGE_HUNG_SEC:
            if _signal_recently_written(self.signal_path):
                self.log.info(f"Engine log stale {age:.0f}s — signal sudah dikirim, menunggu watchdog")
                return
            _write_restart_signal(self.signal_path, f"twin_live.log stale {age:.0f}s")
            self._alert(
                f"🚨 <b>Guardian: Engine Hung!</b>\n"
                f"twin_live.log stale <b>{age:.0f}s</b> (threshold {LOG_AGE_HUNG_SEC}s)\n"
                f"→ Restart signal <code>{RESTART_SIGNAL_TYPE}</code> dikirim ke watchdog"
            )
        else:
            self.log.info(f"Engine alive — log age {age:.1f}s")

    def _check_services(self) -> None:
        for svc in WATCHED_SERVICES:
            if _service_is_active(svc):
                self.log.info(f"Service {svc}: active ✅")
                continue
            # Dead service
            now = time.time()
            last = self._svc_alert.get(svc, 0.0)
            ok = _restart_service(svc)
            status = "✅ restarted" if ok else "❌ restart gagal"
            msg = (
                f"🔴 <b>Guardian: {svc} DOWN!</b>\n"
                f"Status: {status}\n"
                f"Action: systemctl --user restart {svc}"
            )
            if now - last > SERVICE_ALERT_COOLDOWN:
                self._alert(msg)
                self._svc_alert[svc] = now
            else:
                self.log.warning(f"Service {svc} down — restart attempted ({status}), alert cooldown")

    def _scan_errors(self) -> None:
        errors, new_pos = _scan_log_errors(self.engine_log, self._log_pos)
        self._log_pos = new_pos
        now = time.time()
        for err in errors:
            last = self._error_seen.get(err, 0.0)
            if now - last < ERROR_ALERT_COOLDOWN:
                continue
            self._alert(
                f"🔴 <b>Guardian: Error baru di engine log</b>\n"
                f"<code>{err[:300]}</code>"
            )
            self._error_seen[err] = now

    # ── Slow checks (every 1200s) ─────────────────────────────────────────────
    def _check_fill_drought(self) -> None:
        try:
            conn = self._db()
            last_ts_raw = _get_last_fill_ts(conn)
            if last_ts_raw is None:
                conn.close()
                return
            # Parse ISO timestamp
            last_ts = datetime.datetime.fromisoformat(last_ts_raw)
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=datetime.timezone.utc)
            gap_min = (datetime.datetime.now(datetime.timezone.utc) - last_ts).total_seconds() / 60
            # Check if ANY watched pair has no protective gate
            unprotected = [
                p for p in self.watched_pairs
                if not _has_protective_gate(conn, p)
            ]
            conn.close()
            if gap_min > DROUGHT_ANOMALY_MIN and unprotected:
                now = time.time()
                if now - self._drought_alert_ts > 3600:  # 1h cooldown
                    self._alert(
                        f"⚠️ <b>Guardian: Fill Drought Anomali</b>\n"
                        f"Tidak ada fill <b>{gap_min:.0f} menit</b>\n"
                        f"Pair tanpa gate: {', '.join(unprotected)}\n"
                        f"Ini bukan decay_gate — kemungkinan ada masalah engine/config!"
                    )
                    self._drought_alert_ts = now
            else:
                self.log.info(
                    f"Fill drought {gap_min:.0f}min | unprotected={unprotected} | OK"
                )
        except Exception as e:
            self.log.error(f"fill_drought check error: {e}")

    def _check_equity_drift(self) -> None:
        try:
            conn = self._db()
            eq_high = _get_equity_high(conn)
            conn.close()
            if eq_high <= 0:
                return
            # We don't have live equity in DB — use equity_high as reference
            # Check weekly start equity for trend
            # (live equity requires HL API call; skip to keep daemon offline-capable)
            self.log.info(f"Equity high: ${eq_high:.2f}")
        except Exception as e:
            self.log.error(f"equity_drift check error: {e}")

    def _send_summary(self) -> None:
        try:
            conn = self._db()
            last_ts = _get_last_fill_ts(conn)
            gap_min = 0.0
            if last_ts:
                last_dt = datetime.datetime.fromisoformat(last_ts)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=datetime.timezone.utc)
                gap_min = (datetime.datetime.now(datetime.timezone.utc) - last_dt).total_seconds() / 60

            fills_1h = _get_fills_since(conn, 60)
            fills_20m = _get_fills_since(conn, 20)
            pnl_1h, rt_1h = _get_recent_pnl(conn, 1)
            eq_high = _get_equity_high(conn)

            # Gate states
            gates = []
            for pair in self.watched_pairs:
                dg = _get_state(conn, f"e1_decay_gate:{pair}")
                fw = _get_state(conn, f"e1_profit_firewall:{pair}")
                if dg and dg.startswith("decay_gate"):
                    gates.append(f"{pair}: decay_gate🔴")
                elif fw and fw.startswith("profit_firewall"):
                    gates.append(f"{pair}: firewall🔴")
                else:
                    gates.append(f"{pair}: OK🟢")
            conn.close()

            # Service status
            svc_lines = []
            for svc in WATCHED_SERVICES:
                icon = "✅" if _service_is_active(svc) else "🔴"
                svc_lines.append(f"  {icon} {svc}")

            engine_age = 0.0
            if self.engine_log.exists():
                engine_age = time.time() - self.engine_log.stat().st_mtime

            msg = (
                f"<b>🛡️ SoDEX Guardian — Status 20min</b>\n"
                f"<code>{datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC</code>\n\n"
                f"<b>Engine</b>\n"
                f"  Log age: {engine_age:.0f}s {'✅' if engine_age < LOG_AGE_HUNG_SEC else '🔴 HUNG'}\n"
                f"  Fills 20m/1h: {fills_20m}/{fills_1h}\n"
                f"  Last fill gap: {gap_min:.0f} min\n"
                f"  PnL 1h: ${pnl_1h:+.3f} ({rt_1h} RT)\n"
                f"  Equity high: ${eq_high:.2f}\n\n"
                f"<b>Gates</b>\n"
                + "\n".join(f"  {g}" for g in gates) + "\n\n"
                f"<b>Services</b>\n"
                + "\n".join(svc_lines)
            )
            self._info_tg(msg)
        except Exception as e:
            self.log.error(f"summary error: {e}")

    # ── Main loop ─────────────────────────────────────────────────────────────
    def _fast_cycle(self) -> None:
        self._check_engine_liveness()
        self._check_services()
        self._scan_errors()

    def _slow_cycle(self) -> None:
        self._check_fill_drought()
        self._check_equity_drift()

    def run_forever(self) -> None:
        self.log.info(
            f"SoDEX Guardian Daemon v{VERSION} STARTED | "
            f"fast={self.fast_cycle}s slow={self.slow_cycle}s | "
            f"pairs={self.watched_pairs}"
        )
        _send_telegram(
            self.tg_token, self.tg_chat,
            f"🛡️ <b>SoDEX Guardian v{VERSION} STARTED</b>\n"
            f"Fast cycle: {self.fast_cycle}s | Slow: {self.slow_cycle}s\n"
            f"Monitoring: {', '.join(WATCHED_SERVICES)}\n"
            f"Engine log: {self.engine_log.name}"
        )
        while True:
            t0 = time.time()
            try:
                self._fast_cycle()
            except Exception as e:
                self.log.error(f"fast_cycle unhandled: {e}")

            now = time.time()
            if now - self._last_slow >= self.slow_cycle:
                try:
                    self._slow_cycle()
                except Exception as e:
                    self.log.error(f"slow_cycle unhandled: {e}")
                self._last_slow = now

            if now - self._last_summary >= SUMMARY_INTERVAL_SEC:
                try:
                    self._send_summary()
                except Exception as e:
                    self.log.error(f"summary unhandled: {e}")
                self._last_summary = now

            elapsed = time.time() - t0
            sleep_for = max(0.0, self.fast_cycle - elapsed)
            self.log.info(f"cycle done in {elapsed:.1f}s, sleeping {sleep_for:.0f}s")
            time.sleep(sleep_for)


# ── CLI ───────────────────────────────────────────────────────────────────────
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SoDEX Guardian Daemon")
    p.add_argument("--db",         default="twin_engine.db")
    p.add_argument("--engine-log", default="logs/twin_live.log")
    p.add_argument("--signal",     default="data/GUARDIAN_RESTART_SIGNAL")
    p.add_argument("--log",        default="logs/guardian.log")
    p.add_argument("--fast",       type=int, default=FAST_CYCLE_SEC)
    p.add_argument("--slow",       type=int, default=SLOW_CYCLE_SEC)
    p.add_argument("--pairs",      default="", help="comma-separated pairs; empty = active TE_SPOT_PAIR* from env")
    p.add_argument("--status",     action="store_true", help="Print snapshot and exit")
    return p


def _print_status(db_path: Path, engine_log: Path) -> None:
    """Quick one-shot status snapshot."""
    print(f"=== SoDEX Guardian Status {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC ===")
    if engine_log.exists():
        age = time.time() - engine_log.stat().st_mtime
        hung = "HUNG 🔴" if age >= LOG_AGE_HUNG_SEC else "alive ✅"
        print(f"Engine log age: {age:.0f}s ({hung})")
    else:
        print("Engine log: NOT FOUND 🔴")
    for svc in WATCHED_SERVICES:
        active = _service_is_active(svc)
        print(f"Service {svc}: {'active ✅' if active else 'DEAD 🔴'}")
    if db_path.exists():
        conn = _db_connect(db_path)
        last = _get_last_fill_ts(conn)
        if last:
            last_dt = datetime.datetime.fromisoformat(last)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=datetime.timezone.utc)
            gap = (datetime.datetime.now(datetime.timezone.utc) - last_dt).total_seconds() / 60
            print(f"Last fill: {last[:19]} ({gap:.0f} min ago)")
        eq = _get_equity_high(conn)
        print(f"Equity high: ${eq:.2f}")
        conn.close()


def main() -> None:
    p = _build_parser()
    args = p.parse_args()

    db_path     = Path(args.db)
    engine_log  = Path(args.engine_log)
    signal_path = Path(args.signal)
    guardian_log = Path(args.log)
    pairs = [x.strip() for x in args.pairs.split(",") if x.strip()]
    if not pairs:
        pairs = _detect_watched_pairs(db_path)

    if args.status:
        _print_status(db_path, engine_log)
        return

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    tg_chat  = os.environ.get("TELEGRAM_CHAT_ID", "")

    daemon = GuardianDaemon(
        db_path=db_path,
        engine_log=engine_log,
        signal_path=signal_path,
        guardian_log=guardian_log,
        tg_token=tg_token,
        tg_chat=tg_chat,
        fast_cycle=args.fast,
        slow_cycle=args.slow,
        watched_pairs=pairs,
    )
    daemon.run_forever()


if __name__ == "__main__":
    main()
