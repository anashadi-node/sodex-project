#!/usr/bin/env python3
"""DEADMAN SoDEX — rem otomatis di LUAR mesin.

Dua pemicu:
  1. RUGI_HARIAN   : ekuitas turun >= 8,0% dari baseline 00:00 UTC
                     (default 8,0%; override SODEX_DEADMAN_HALT_PCT).
  2. BUTA_EKUITAS  : fase LIVE dan ledger ekuitas tidak diperbarui > 6 jam
                     (pengawasan buta = bahaya, bukan aman).

Aksi saat terpicu (sekali per hari per alasan):
  * tulis `secrets/KILL`            -> semua pintu order memblokir (sudah dibaca engine)
  * tulis `data/PNL_HALT`           -> farm/scanner memblokir order non-reduce-only
  * tulis `data/FLATTEN_REQUEST.json` -> perintah likuidasi penuh (dieksekusi mode_a_flatten)
  * append `reports/sodex/DEADMAN_EVENTS.jsonl`
  * bila armed dan tidak dry-run: jalankan `mode_a_flatten.py --live`

Denyut: `data/DEADMAN_HEARTBEAT.json` tiap siklus (120 dtk). Preflight memeriksa umurnya;
denyut hilang >30 menit berarti deadman sendiri mati -> ARM ditolak.

Sebelum live (belum ada LIVE_ARMED.json) deadman hanya MEMANTAU: tidak pernah menulis KILL,
supaya lane paper tidak ikut terhenti.

  sodex_deadman.py --once [--dry-run] [--root DIR] [--simulate-loss 3.1]
  sodex_deadman.py --loop [--cycle 120]
  sodex_deadman.py --status
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Batas kerugian harian (persen dari baseline 00:00 UTC). Owner 2026-11-06: 8%.
# Bisa di-override tanpa edit kode: SODEX_DEADMAN_HALT_PCT=8.0
HALT_PCT = float(os.environ.get("SODEX_DEADMAN_HALT_PCT", "8.0"))
BLIND_HOURS = 6.0
CYCLE_SEC = 120
LIVE_DATE = date(2026, 12, 1)


class Paths:
    def __init__(self, root: Path | str = ROOT):
        self.root = Path(root)
        self.ledger = self.root / "reports/sodex/EQUITY_LEDGER.jsonl"
        self.arm = self.root / "secrets/LIVE_ARMED.json"
        self.kill = self.root / "secrets/KILL"
        self.pnl_halt = self.root / "data/PNL_HALT"
        self.flatten = self.root / "data/FLATTEN_REQUEST.json"
        self.heartbeat = self.root / "data/DEADMAN_HEARTBEAT.json"
        self.events = self.root / "reports/sodex/DEADMAN_EVENTS.jsonl"
        self.flatten_cli = self.root / "scripts/research/mode_a_20261026/mode_a_flatten.py"


def now() -> datetime:
    return datetime.now(timezone.utc)


def phase(today: date) -> str:
    if today >= LIVE_DATE:
        return "LIVE"
    if today >= date(2026, 11, 25):
        return "BEKU"
    return "PERSIAPAN"


def read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.replace("\x00", "").strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return sorted((r for r in out if r.get("ts") and r.get("equity") is not None), key=lambda r: r["ts"])


def ledger_age_h(rows: list[dict]) -> float | None:
    if not rows:
        return None
    last = datetime.fromisoformat(str(rows[-1]["ts"]).replace("Z", "+00:00"))
    return (now() - last.astimezone(timezone.utc)).total_seconds() / 3600


def daily_baseline(rows: list[dict], today: date) -> tuple[float | None, str]:
    """Ekuitas acuan hari ini: baris pertama hari ini; bila belum ada, baris terakhir sebelumnya."""
    key = today.isoformat()
    same = [r for r in rows if str(r["ts"])[:10] == key]
    if same:
        return float(same[0]["equity"]), "awal_hari"
    before = [r for r in rows if str(r["ts"])[:10] < key]
    if before:
        return float(before[-1]["equity"]), "penutupan_kemarin"
    return None, "tidak_ada"


def loss_pct(baseline: float | None, current: float | None) -> float | None:
    if not baseline or current is None or baseline <= 0:
        return None
    return round((current - baseline) / baseline * 100.0, 4)


def is_armed(paths: Paths) -> tuple[bool, dict]:
    if not paths.arm.exists():
        return False, {}
    try:
        d = json.loads(paths.arm.read_text())
    except Exception:
        return False, {}
    return bool(d.get("armed") is True), d


def decide(baseline, current, ph: str, age_h, armed: bool,
           halt_pct: float = HALT_PCT, blind_h: float = BLIND_HOURS) -> dict:
    """Keputusan murni. Tanpa arm -> selalu aman (monitor saja)."""
    lp = loss_pct(baseline, current)
    base = {"loss_pct": lp, "fase": ph, "armed": armed, "umur_ledger_jam": None if age_h is None else round(age_h, 2)}
    if not armed:
        return {**base, "halt": False, "alasan": None, "detail": "belum armed — monitor"}
    if ph == "LIVE" and (age_h is None or age_h > blind_h):
        return {**base, "halt": True, "alasan": "BUTA_EKUITAS",
                "detail": "ledger ekuitas tidak diperbarui > %.1f jam" % blind_h}
    if lp is not None and lp <= -abs(halt_pct):
        return {**base, "halt": True, "alasan": "RUGI_HARIAN",
                "detail": f"rugi harian {lp:.2f}% <= -{abs(halt_pct):.1f}% dari baseline {baseline:.2f}"}
    return {**base, "halt": False, "alasan": None, "detail": "normal"}


def _append_event(paths: Paths, payload: dict) -> bool:
    """Satu event per (tanggal UTC, alasan) — supaya tidak membanjiri log tiap 2 menit."""
    day = str(payload.get("utc", ""))[:10]
    key = (day, payload.get("alasan"))
    if paths.events.exists():
        for line in paths.events.read_text().splitlines():
            line = line.replace("\x00", "").strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (str(e.get("utc", ""))[:10], e.get("alasan")) == key:
                return False
    paths.events.parent.mkdir(parents=True, exist_ok=True)
    with paths.events.open("a") as f:
        f.write(json.dumps(payload, sort_keys=True) + "\n")
    return True


def write_halt(paths: Paths, decision: dict, equity: float | None) -> dict:
    """Tulis KILL/PNL_HALT/FLATTEN_REQUEST. Tidak pernah menimpa KILL yang sudah ada."""
    ts = now().isoformat(timespec="seconds")
    isi = (f"DEADMAN {decision['alasan']} pada {ts}\n"
           f"{decision['detail']}\n"
           f"equity={equity} loss_pct={decision['loss_pct']}\n"
           "hapus file ini HANYA setelah review manual.\n")
    dibuat = []
    if not paths.kill.exists():
        paths.kill.parent.mkdir(parents=True, exist_ok=True)
        paths.kill.write_text(isi)
        dibuat.append("KILL")
    if not paths.pnl_halt.exists():
        paths.pnl_halt.parent.mkdir(parents=True, exist_ok=True)
        paths.pnl_halt.write_text(isi)
        dibuat.append("PNL_HALT")
    req = {"ts": ts, "alasan": decision["alasan"], "detail": decision["detail"],
           "equity": equity, "loss_pct": decision["loss_pct"], "status": "PENDING"}
    if not paths.flatten.exists():
        paths.flatten.parent.mkdir(parents=True, exist_ok=True)
        paths.flatten.write_text(json.dumps(req, indent=1))
        dibuat.append("FLATTEN_REQUEST")
    ev = _append_event(paths, {"utc": ts, "alasan": decision["alasan"], "detail": decision["detail"],
                               "equity": equity, "loss_pct": decision["loss_pct"], "dibuat": dibuat})
    return {"dibuat": dibuat, "event_baru": ev}


def write_heartbeat(paths: Paths, payload: dict) -> None:
    paths.heartbeat.parent.mkdir(parents=True, exist_ok=True)
    tmp = paths.heartbeat.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=True))
    os.replace(tmp, paths.heartbeat)


def run_cycle(paths: Paths, dry_run: bool = False, simulate_loss: float | None = None,
              exec_fn=None) -> dict:
    rows = read_ledger(paths.ledger)
    ph = phase(now().date())
    armed, _arm = is_armed(paths)
    baseline, src = daily_baseline(rows, now().date())
    current = float(rows[-1]["equity"]) if rows else None
    if simulate_loss is not None and baseline:
        current = round(baseline * (1 + simulate_loss / 100.0), 4)
    age = ledger_age_h(rows)
    d = decide(baseline, current, ph, age, armed)
    res = {**d, "baseline": baseline, "baseline_sumber": src, "equity": current,
           "ledger_baris": len(rows), "dry_run": dry_run, "utc": now().isoformat(timespec="seconds")}
    if d["halt"] and not dry_run:
        res.update(write_halt(paths, d, current))
        res["flatten"] = _maybe_flatten(paths, d, exec_fn)
    write_heartbeat(paths, res)
    return res


def _maybe_flatten(paths: Paths, decision: dict, exec_fn=None) -> dict:
    cmd = [sys.executable, str(paths.flatten_cli), "--live", "--reason", decision["alasan"]]
    if exec_fn is not None:          # hook uji: tidak pernah memanggil CLI nyata
        return exec_fn(cmd)
    if not paths.flatten_cli.exists():
        return {"status": "TIDAK_ADA_CLI"}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                           cwd=str(paths.root / "scripts/research/mode_a_20261026"))
        return {"rc": r.returncode, "out": (r.stdout or "").strip()[:400],
                "err": (r.stderr or "").strip()[:200]}
    except Exception as e:
        return {"rc": None, "err": str(e)[:200]}


def status(paths: Paths) -> dict:
    rows = read_ledger(paths.ledger)
    armed, _ = is_armed(paths)
    baseline, src = daily_baseline(rows, now().date())
    hb = None
    if paths.heartbeat.exists():
        try:
            hb = json.loads(paths.heartbeat.read_text())
        except Exception:
            hb = {"rusak": True}
    return {"fase": phase(now().date()), "armed": armed, "baris_ledger": len(rows),
            "baseline": baseline, "baseline_sumber": src,
            "equity_terakhir": float(rows[-1]["equity"]) if rows else None,
            "umur_ledger_jam": None if (a := ledger_age_h(rows)) is None else round(a, 2),
            "kill_ada": paths.kill.exists(), "pnl_halt_ada": paths.pnl_halt.exists(),
            "flatten_ada": paths.flatten.exists(),
            "heartbeat": hb}


def main(argv: list[str]) -> int:
    root = Path(argv[argv.index("--root") + 1]) if "--root" in argv else ROOT
    paths = Paths(root)
    dry = "--dry-run" in argv
    sim = float(argv[argv.index("--simulate-loss") + 1]) if "--simulate-loss" in argv else None
    try:
        if "--status" in argv:
            print(json.dumps(status(paths), indent=1, default=str))
            return 0
        if "--loop" in argv:
            cyc = int(argv[argv.index("--cycle") + 1]) if "--cycle" in argv else CYCLE_SEC
            while True:
                r = run_cycle(paths, dry_run=dry)
                print(json.dumps({k: r[k] for k in ("utc", "halt", "alasan", "loss_pct", "armed")}), flush=True)
                time.sleep(max(15, cyc))
        r = run_cycle(paths, dry_run=dry, simulate_loss=sim)
        print(json.dumps(r, indent=1, default=str))
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        print(json.dumps({"status": "ERROR", "detail": str(e)[:400]}))
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
