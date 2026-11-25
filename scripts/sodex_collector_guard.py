#!/usr/bin/env python3
"""
ANANTARA SAKTI — Guard anti-jeda collector SoDEX (READ-ONLY).

Tugas: memastikan collector OBI/trades SoDEX TIDAK berhenti menulis data.
  * Restart=always pada unit sudah menangani proses yang MATI.
  * Guard ini menangani kasus yang TIDAK tercakup: proses HIDUP tapi MACET
    (tidak menulis baris baru) — penyebab jeda 2026-08-03..08-08.

Aturan:
  * Baris terbaru (OBI & trades) lebih tua dari STALE_MIN menit -> restart unit + notifikasi.
  * Restart dibatasi MAX_RESTART_PER_HOUR agar tidak jadi loop.
  * Toleransi pergantian hari (UTC): berkas hari ini belum ada tapi hari baru < GRACE_MIN.
Tidak menyentuh gate/leverage/sizing/target. Hanya membaca berkas + status unit.
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OBI = ROOT / "freqtrade_user_data/data/sodex/obi"
TRD = ROOT / "freqtrade_user_data/data/sodex/trades"
LOG = ROOT / "logs/sodex_collector_guard.log"
STATE = ROOT / "data/sodex_collector_guard_state.json"
UNIT = "anantara-obi.service"
STALE_MIN = float(os.environ.get("GUARD_STALE_MIN", "15"))
GRACE_MIN = float(os.environ.get("GUARD_GRACE_MIN", "20"))
MAX_RESTART_PER_HOUR = int(os.environ.get("GUARD_MAX_RESTART", "3"))
MIN_SYMBOLS = int(os.environ.get("GUARD_MIN_SYMBOLS", "20"))


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}"
    print(line)
    with open(LOG, "a") as fh:
        fh.write(line + "\n")


def env_get(key: str) -> str:
    p = ROOT / ".env"
    try:
        for line in open(p, encoding="utf-8", errors="ignore"):
            m = re.match(rf"^\s*{key}\s*=\s*(.*?)\s*$", line)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return ""


def telegram(text: str) -> None:
    tok, cid = env_get("TELEGRAM_BOT_TOKEN"), env_get("TELEGRAM_CHAT_ID")
    if not tok or not cid:
        log("  (notifikasi dilewati: kredensial Telegram tidak tersedia)")
        return
    try:
        data = urllib.parse.urlencode({"chat_id": cid, "text": text, "parse_mode": "HTML"}).encode()
        urllib.request.urlopen(
            urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=data), timeout=10)
    except Exception as e:                                    # noqa: BLE001
        log(f"  (notifikasi gagal: {type(e).__name__})")


def tail_last(path: Path) -> tuple[float | None, set[str]]:
    """(ts terbaru dalam detik, himpunan simbol pada ~2000 baris terakhir)"""
    if not path.exists():
        return None, set()
    size = path.stat().st_size
    with open(path, "rb") as fh:
        fh.seek(max(0, size - 262144))                        # 256 KB terakhir
        chunk = fh.read().decode("utf-8", errors="ignore")
    ts, syms = None, set()
    for line in chunk.splitlines()[-2000:]:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            r = json.loads(line)
        except Exception:                                     # noqa: BLE001
            continue
        try:
            t = float(r.get("ts") or 0) / 1000.0
        except (TypeError, ValueError):
            continue
        if t > 0:
            ts = t if ts is None else max(ts, t)
        s = r.get("sym") or r.get("symbol")
        if s:
            syms.add(s)
    return ts, syms


def unit_active() -> bool:
    r = subprocess.run(["systemctl", "--user", "is-active", UNIT],
                       capture_output=True, text=True)
    return r.stdout.strip() == "active"


def restarts_last_hour() -> list[float]:
    try:
        return [float(x) for x in json.load(open(STATE)).get("restarts", [])]
    except Exception:                                         # noqa: BLE001
        return []


def save_restarts(ts: list[float]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"restarts": ts[-50:]}, open(STATE, "w"))


def main() -> int:
    now = time.time()
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    o_ts, o_syms = tail_last(OBI / f"obi_{day}.jsonl")
    t_ts, t_syms = tail_last(TRD / f"trades_{day}.jsonl")
    syms = o_syms | t_syms
    ages = [(now - x) / 60 for x in (o_ts, t_ts) if x]
    age = max(ages) if ages else 1e9

    # toleransi pergantian hari (UTC)
    midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    if age > 1e8 and (now - midnight) / 60 < GRACE_MIN:
        log(f"OK (pergantian hari UTC, baru {(now-midnight)/60:.1f} menit; berkas belum ada)")
        return 0

    active = unit_active()
    problems = []
    if not active:
        problems.append("unit TIDAK aktif")
    if age > STALE_MIN:
        problems.append(f"baris terbaru {age:.1f} menit lalu (> {STALE_MIN:.0f})")
    if syms and len(syms) < MIN_SYMBOLS:
        problems.append(f"hanya {len(syms)} simbol (< {MIN_SYMBOLS})")

    if not problems:
        log(f"OK — {len(syms)} simbol, baris terbaru {age:.1f} menit lalu, unit aktif")
        return 0

    log("MASALAH: " + "; ".join(problems))
    hist = [t for t in restarts_last_hour() if now - t < 3600]
    if len(hist) >= MAX_RESTART_PER_HOUR:
        log(f"  restart DIBATASI ({len(hist)}/jam sudah dipakai) — hanya notifikasi")
        telegram("⚠️ <b>SoDEX collector</b>: " + "; ".join(problems)
                 + f"\nRestart dibatasi ({len(hist)}/jam). Perlu tindakan manual.")
        return 1
    r = subprocess.run(["systemctl", "--user", "restart", UNIT], capture_output=True, text=True)
    hist.append(now)
    save_restarts(hist)
    time.sleep(20)
    o_ts2, _ = tail_last(OBI / f"obi_{day}.jsonl")
    ok = bool(o_ts2) and (time.time() - o_ts2) / 60 < 5
    log(f"  restart dijalankan (rc={r.returncode}) — pemulihan: {'BERHASIL' if ok else 'BELUM terlihat'}")
    telegram(("✅" if ok else "⚠️") + " <b>SoDEX collector</b>: " + "; ".join(problems)
             + f"\nRestart {'berhasil memulihkan' if ok else 'dijalankan, pemulihan belum terlihat'}"
             + f" ({len(hist)} restart/jam).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
