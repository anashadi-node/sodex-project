#!/usr/bin/env python3
"""Guard jalur-kritis T1 SoDEX: pastikan bukti forward TIDAK bolong.

KENAPA ADA (t1_1b)
------------------
Jalur kritis T1 = jendela forward 30 hari (mulai 2026-10-02, selesai ~2026-11-01)
dengan deadline 2026-11-03 -- MARGIN HANYA ~2 HARI. T1 TIDAK BOLEH dievaluasi
pada jendela historis karena SoDEX tidak menyediakan funding per-pair historis;
satu-satunya sumber sah adalah bukti forward yang terakumulasi sekarang.

Artinya: setiap hari yang hilang TIDAK DAPAT DIGANTI. Kalau loop forward diam
2 hari, margin habis seluruhnya.

Loop forward normalnya berjalan tiap 3-6 jam (terukur: 26 run / 47 jam, gap
maksimum 6,01 jam pada 2026-10-04). Karena itu:

    gap > 15 jam   -> WARNING   (2,5x gap maksimum yang pernah teramati, 6,01 jam)
    gap > 48 jam   -> CRITICAL  (2 hari -- margin deadline habis)

Yang diperiksa (semua read-only):
  0. arsip funding        -- feeder jalur-kritis #2: kalau diam/bolong, T1 tidak
                             dapat dihitung dan itu baru ketahuan di hari-30
  1. kesegaran loop       -- kapan registry forward terakhir bertambah?
  2. kegagalan harness    -- berapa FAIL_CLOSED_HARNESS_ERROR pada jendela N jam?
  3. produksi trade       -- track forward mana yang berhenti menutup trade?

CATATAN PENTING: loop hanya MENGEVALUASI. Bobot 30 hari datang dari trade yang
DITUTUP. Mesin paper bisa tetap hidup sementara nol trade ditutup (mis. kaki
SHORT `twoway` digerbangi death-cross: 0 SHORT sejak 2026-09-01). Karena itu
pemeriksaan #3 memisahkan "loop mati" dari "track memang tak menghasilkan
trade" -- keduanya punya tindakan berbeda.

Pemakaian:
    python3 scripts/sodex_forward_loop_guard.py --dry-run   # tampilkan saja
    python3 scripts/sodex_forward_loop_guard.py             # + alert bila berubah
Exit code: 0 sehat, 1 WARNING, 2 CRITICAL (agar systemd/journal mudah dibaca).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOOP_REGISTRY = ROOT / "reports/sodex/sodex_forward_reeval_loop.jsonl"
FUNDING_ARCHIVE = ROOT / "data/sodex_funding/funding_rates_history.jsonl"
GUARD_STATE = ROOT / "data/sodex_forward_loop_guard_state.json"

WARN_LOOP_HOURS = 15.0      # 2,5x gap maksimum teramati (6,01 jam); beri margin 1 siklus terlewat
CRIT_LOOP_HOURS = 48.0      # 2 hari -- margin deadline
WARN_TRACK_HOURS = 24.0
CRIT_TRACK_HOURS = 48.0
FAIL_WINDOW_HOURS = 12.0    # jendela hitung kegagalan harness
FAIL_WARN_COUNT = 2         # >=2 kegagalan dalam jendela -> WARNING
ALERT_COOLDOWN_HOURS = 12.0  # jangan spam: kirim ulang paling cepat tiap 12 jam

# Feeder jalur-kritis #2: arsip funding. Kolektor berjalan TIAP JAM (92 simbol).
# T1 menuntut funding/borrow lengkap sepanjang jendela forward; kalau arsip diam
# atau bolong, T1 menjadi TIDAK DAPAT DIHITUNG dan itu baru ketahuan di hari-30.
WARN_FUNDING_HOURS = 3.0    # 3x kadens (1 jam) -- 2 siklus terlewat
CRIT_FUNDING_HOURS = 12.0   # setengah hari tanpa funding baru
FUNDING_MAX_MISSING_RATIO = 0.10  # >10% jam koleksi hilang -> WARNING

# Track forward yang WAJIB terus menutup trade. `twoway` SHORT sengaja TIDAK
# masuk daftar cek "berhenti": ia digerbangi death-cross dan memang bisa nol
# berminggu-minggu tanpa ada yang rusak.
FORWARD_TRACK_STATES = {
    "swing": ROOT / "data/paper_test_swing_state.json",
    "twoway": ROOT / "data/paper_test_twoway_state.json",
    "realwide": ROOT / "data/paper_test_realwide_state.json",
}

LEVEL_OK, LEVEL_WARN, LEVEL_CRIT = "OK", "WARNING", "CRITICAL"
_ORDER = {LEVEL_OK: 0, LEVEL_WARN: 1, LEVEL_CRIT: 2}


def parse_utc(s) -> dt.datetime | None:
    if s is None or s == "":
        return None
    # epoch numerik (mis. realwide: entry_ts/exit_ts)
    if isinstance(s, (int, float)) or (isinstance(s, str) and s.replace(".", "", 1).isdigit()):
        try:
            return dt.datetime.fromtimestamp(float(s), tz=dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


# Skema berkas state berbeda antar-track: swing/twoway pakai entry_time/exit_time,
# realwide pakai entry_iso/exit_iso + entry_ts/exit_ts (epoch). Keduanya harus
# dikenali, kalau tidak guard akan terus berbunyi "belum ada trade" (alarm palsu).
_STAMP_KEYS = ("exit_iso", "exit_time", "exit_utc", "entry_iso", "entry_time", "entry_utc")
_STAMP_KEYS_NUM = ("exit_ts", "entry_ts")


def baca_loop(registry: Path) -> list[dict]:
    if not registry.exists():
        return []
    out = []
    for line in registry.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def cek_loop(rows: list[dict], now: dt.datetime) -> dict:
    """Kesegaran loop + laju kegagalan harness."""
    if not rows:
        return {"level": LEVEL_CRIT, "hu": None, "msg": "registry forward KOSONG",
                "fails": 0, "n": 0}

    stempel = [t for t in (parse_utc(r.get("generated_utc")) for r in rows) if t]
    if not stempel:
        return {"level": LEVEL_CRIT, "hu": None, "msg": "tak ada stempel waktu valid",
                "fails": 0, "n": len(rows)}
    terakhir = max(stempel)
    hu = (now - terakhir).total_seconds() / 3600.0

    if hu > CRIT_LOOP_HOURS:
        level, msg = LEVEL_CRIT, f"loop forward diam {hu:.1f} jam (> {CRIT_LOOP_HOURS:.0f} jam)"
    elif hu > WARN_LOOP_HOURS:
        level, msg = LEVEL_WARN, f"loop forward diam {hu:.1f} jam (> {WARN_LOOP_HOURS:.0f} jam)"
    else:
        level, msg = LEVEL_OK, f"loop segar ({hu:.1f} jam lalu)"

    batas = now - dt.timedelta(hours=FAIL_WINDOW_HOURS)
    fails = sum(
        1 for r in rows
        if (t := parse_utc(r.get("generated_utc"))) and t >= batas
        and "FAIL_CLOSED" in str(r.get("verdict", "")).upper()
    )
    if fails >= FAIL_WARN_COUNT and level == LEVEL_OK:
        level = LEVEL_WARN
        msg += f"; {fails} kegagalan harness dalam {FAIL_WINDOW_HOURS:.0f} jam"

    return {"level": level, "hu": hu, "msg": msg, "fails": fails, "n": len(rows)}


def baca_trade(path: Path) -> list[dict]:
    try:
        d = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    for k in ("closed_trades", "closed", "trades"):
        v = d.get(k) if isinstance(d, dict) else None
        if isinstance(v, list):
            return v
    return []


def cek_track_trade(rows: list[dict], now: dt.datetime,
                    warn_h: float = WARN_TRACK_HOURS,
                    crit_h: float = CRIT_TRACK_HOURS) -> dict:
    """Kapan trade terakhir DITUTUP? Memisahkan 'loop mati' dari 'tak ada sinyal'."""
    stempel = []
    for r in rows:
        t = None
        for k in _STAMP_KEYS + _STAMP_KEYS_NUM:
            t = parse_utc(r.get(k))
            if t:
                break
        if t:
            stempel.append(t)
    if not stempel:
        return {"level": LEVEL_WARN, "hu": None, "msg": "belum ada trade tertutup"}
    hu = (now - max(stempel)).total_seconds() / 3600.0
    if hu > crit_h:
        return {"level": LEVEL_CRIT, "hu": hu, "msg": f"terakhir tutup {hu:.1f} jam lalu"}
    if hu > warn_h:
        return {"level": LEVEL_WARN, "hu": hu, "msg": f"terakhir tutup {hu:.1f} jam lalu"}
    return {"level": LEVEL_OK, "hu": hu, "msg": f"terakhir tutup {hu:.1f} jam lalu"}


def baca_funding(path: Path) -> list[dt.datetime]:
    """Stempel collected_utc saja -- arsip funding bisa besar, jangan disimpan penuh."""
    out: list[dt.datetime] = []
    if not path.exists():
        return out
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = parse_utc(r.get("collected_utc"))
        if t:
            out.append(t)
    return out


def cek_funding(stamps: list[dt.datetime], now: dt.datetime,
                warn_h: float = WARN_FUNDING_HOURS,
                crit_h: float = CRIT_FUNDING_HOURS,
                max_missing: float = FUNDING_MAX_MISSING_RATIO) -> dict:
    """Kesegaran + KELENGKAPAN arsip funding (feeder jalur-kritis T1 #2).

    Dua mode kegagalan, keduanya fatal tapi berbeda:
      - arsip DIAM        -> tak ada funding baru (kolektor mati)
      - arsip BOLONG      -> ada jam yang terlewat tanpa disadari
    Yang kedua lebih berbahaya: arsip terlihat "hidup", tapi T1 nanti tidak
    dapat dihitung karena cakupan tidak lengkap.
    """
    kosong = {"hu": None, "missing": None, "have": 0, "expected": 0}
    if not stamps:
        return {"level": LEVEL_CRIT, "msg": "arsip funding KOSONG atau tak terbaca", **kosong}

    pertama, terakhir = min(stamps), max(stamps)
    hu = (now - terakhir).total_seconds() / 3600.0

    jam_unik = {t.replace(minute=0, second=0, microsecond=0) for t in stamps}
    expected = int((terakhir - pertama).total_seconds() // 3600) + 1
    have = len(jam_unik)
    missing = max(0.0, (expected - have) / expected) if expected else 0.0
    ekor = f"{have}/{expected} jam"

    if hu > crit_h:
        return {"level": LEVEL_CRIT, "hu": hu, "missing": missing, "have": have,
                "expected": expected,
                "msg": f"arsip funding diam {hu:.1f} jam -- T1 jadi tak terhitung"}
    if hu > warn_h:
        return {"level": LEVEL_WARN, "hu": hu, "missing": missing, "have": have,
                "expected": expected, "msg": f"arsip funding diam {hu:.1f} jam ({ekor})"}
    if missing > max_missing:
        return {"level": LEVEL_WARN, "hu": hu, "missing": missing, "have": have,
                "expected": expected,
                "msg": f"arsip funding bolong {missing*100:.0f}% ({ekor})"}
    return {"level": LEVEL_OK, "hu": hu, "missing": missing, "have": have,
            "expected": expected, "msg": f"segar {hu:.1f} jam, cakupan {ekor}"}


def gabung(level_a: str, level_b: str) -> str:
    return level_a if _ORDER[level_a] >= _ORDER[level_b] else level_b


def perlu_alert(level: str, state: dict, now: dt.datetime,
                cooldown_h: float = ALERT_COOLDOWN_HOURS) -> bool:
    """Kirim bila level naik (mis. OK->WARNING) atau cooldown sudah lewat."""
    if level == LEVEL_OK:
        return False
    level_lama = state.get("last_level")
    if level_lama != level:
        return True  # eskalasi / level berubah -> selalu kirim
    t_lama = parse_utc(state.get("last_alert_utc"))
    if t_lama is None:
        return True
    return (now - t_lama).total_seconds() / 3600.0 >= cooldown_h


def kirim_telegram(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "") or os.environ.get("TELEGRAM_HOME_CHANNEL", "")
    if not token or not chat:
        print("[alert dilewati: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID tidak diset]", file=sys.stderr)
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": text,
                                   "parse_mode": "HTML"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 300
    except Exception as e:  # noqa: BLE001
        print(f"[alert gagal: {type(e).__name__}]", file=sys.stderr)
        return False


def susun_pesan(hasil: dict, now: dt.datetime) -> str:
    baris = [
        f"<b>[SoDEX T1] {hasil['level']}</b> — {now.strftime('%Y-%m-%d %H:%M')} WIB",
        "",
        f"Loop   : {hasil.get('loop', {}).get('msg', 'n/a')}",
        f"Funding: {hasil.get('funding', {}).get('msg', 'n/a')}",
    ]
    for nama, t in hasil.get("track", {}).items():
        lambang = {"OK": "OK", "WARNING": "! ", "CRITICAL": "!!"}[t["level"]]
        baris.append(f"  {lambang} {nama:<9}: {t['msg']}")
    baris += [
        "",
        f"Jalur kritis: jendela forward 30 hari — margin deadline ~2 hari.",
        f"Registry: {hasil.get('loop', {}).get('n', 0)} run | "
        f"gagal {FAIL_WINDOW_HOURS:.0f}j: {hasil.get('loop', {}).get('fails', 0)}",
        "",
        "— Hermes Anantara v3",
    ]
    return "\n".join(baris)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="jangan kirim alert")
    ap.add_argument("--now", default=None, help="ISO UTC untuk uji (default: sekarang)")
    args = ap.parse_args()

    now = parse_utc(args.now) or dt.datetime.now(dt.timezone.utc)

    loop = cek_loop(baca_loop(LOOP_REGISTRY), now)
    funding = cek_funding(baca_funding(FUNDING_ARCHIVE), now)
    track = {n: cek_track_trade(baca_trade(p), now) for n, p in FORWARD_TRACK_STATES.items()}

    level = gabung(loop["level"], funding["level"])
    for t in track.values():
        level = gabung(level, t["level"])

    hasil = {"level": level, "loop": loop, "funding": funding, "track": track}

    print(f"LEVEL: {level}")
    print(f"  loop : {loop['msg']}  (registry n={loop['n']}, gagal={loop['fails']})")
    print(f"  fund : {funding['msg']}")
    for n, t in track.items():
        print(f"  {n:<9}: {t['msg']}")

    state = {}
    if GUARD_STATE.exists():
        try:
            state = json.loads(GUARD_STATE.read_text())
        except json.JSONDecodeError:
            state = {}

    if not args.dry_run and perlu_alert(level, state, now):
        if kirim_telegram(susun_pesan(hasil, now)):
            state["last_alert_utc"] = now.isoformat()
            print("alert terkirim")

    if not args.dry_run:
        state["last_level"] = level
        state["last_check_utc"] = now.isoformat()
        stamp = [t for t in (parse_utc(r.get("generated_utc"))
                             for r in baca_loop(LOOP_REGISTRY)) if t]
        state["last_seen_utc"] = (max(stamp) if stamp else now).isoformat()
        GUARD_STATE.parent.mkdir(parents=True, exist_ok=True)
        GUARD_STATE.write_text(json.dumps(state, indent=1))

    return {LEVEL_OK: 0, LEVEL_WARN: 1, LEVEL_CRIT: 2}[level]


if __name__ == "__main__":
    raise SystemExit(main())
