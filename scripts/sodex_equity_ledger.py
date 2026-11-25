#!/usr/bin/env python3
"""Ledger ekuitas SoDEX (append-only) — bahan bakar gate promosi REV2.

Gate `scripts/sodex_target_promotion_gate.py --equity-file` membaca JSONL
`{ts, equity}` lalu menghitung return per bucket 5 jam. Tanpa ledger ini,
"30 hari data live" tidak bisa diukur dan target live awal tidak pernah bisa
dievaluasi. Default: 1 baris per tanggal UTC (idempoten). Dengan --force
(scheduler 30 menit) baris intraday tetap ditulis supaya deadman tidak
menembak BUTA_EKUITAS karena ledger basi >6 jam; baseline harian tetap
memakai baris PERTAMA hari itu.

Sumber ekuitas (pilih satu, fail-closed bila kosong):
  --from-mode-a        ledger mode_a_live (equity_after terakhir)
  --from-file PATH     JSON/JSONL dengan kunci equity/equity_usd/account_value
  --from-json '{"equity": 243.7}'

Perintah:
  snapshot [--source ...] [--force]
  check                cakupan hari, celah, umur baris terakhir

Exit: 0 ok, 2 sumber tidak valid / ledger rusak, 3 cakupan <30 hari (check).
Tidak menyentuh order, kredensial, atau state trading.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "reports/sodex/EQUITY_LEDGER.jsonl"
MODE_A_LEDGER = ROOT / "scripts/research/mode_a_20261026/mode_a_live_ledger.jsonl"
EQUITY_KEYS = ("equity", "equity_usd", "account_value", "total_equity_usd")


def _utc(ts: str | None = None) -> datetime:
    if ts:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _day(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%d")


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        line = line.replace("\x00", "").strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"baris {i} rusak di {path}: {e}") from e
    return out


def append_record(path: Path, equity: float, source: str, ts: str | None = None,
                  force: bool = False, note: str = "") -> dict:
    if not isinstance(equity, (int, float)) or not (equity > 0):
        raise ValueError(f"ekuitas tidak valid: {equity!r} (harus > 0)")
    when = _utc(ts)
    rows = read_rows(path)
    if not force:
        for r in rows:
            try:
                if _day(_utc(r.get("ts"))) == _day(when):
                    return {"written": False, "alasan": "hari sudah tercatat",
                            "baris_lama": r, "tanggal": _day(when)}
            except Exception:
                continue
    rec = {"ts": when.isoformat(timespec="seconds"), "equity": float(equity),
           "source": source, "note": note}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
    return {"written": True, "record": rec}


def equity_from_mode_a(path: Path = MODE_A_LEDGER) -> float | None:
    rows = read_rows(path)
    for r in reversed(rows):
        if r.get("kind") == "result" and r.get("equity_after") is not None:
            return float(r["equity_after"])
        if r.get("equity") is not None:
            return float(r["equity"])
    return None


def equity_from_file(path: Path) -> float | None:
    txt = path.read_text().strip()
    if not txt:
        return None
    try:
        payload = json.loads(txt)
        seq = [payload] if isinstance(payload, dict) else list(payload)
    except json.JSONDecodeError:
        seq = read_rows(path)
    for obj in reversed(seq):
        if not isinstance(obj, dict):
            continue
        for k in EQUITY_KEYS:
            if obj.get(k) is not None:
                return float(obj[k])
    return None


def perps_equity_from_venue(root: Path = ROOT) -> float:
    """Ekuitas perps (vUSDC total) lewat CLI read-only `balance perps`.
    Gagal (ValueError) bila CLI/kredensial tidak tersedia — tidak pernah mengarang angka."""
    import subprocess  # noqa: PLC0415
    d = str(root / "scripts/research/mode_a_20261026")
    if d not in sys.path:
        sys.path.insert(0, d)
    try:
        import mode_a_live as live  # noqa: PLC0415
        env = live.load_env()
        r = subprocess.run([str(root / "bin/sodex"), "balance", "perps", "--format", "json"],
                           capture_output=True, text=True, timeout=90, env=env, cwd=str(root))
        if r.returncode != 0:
            raise RuntimeError(f"CLI exit {r.returncode}: {r.stderr.strip()[:120]}")
        rows = json.loads(r.stdout)
        return float(sum(float(x.get("total") or 0) for x in rows if x.get("coin") == "vUSDC"))
    except Exception as e:  # Block/ExecError/ImportError/JSON -> fail closed
        raise ValueError(f"sumber perps tidak tersedia: {str(e)[:160]}") from e


def equity_from_venue(root: Path = ROOT) -> float:
    """Ekuitas TOTAL wallet (spot + perps) dari venue (read-only): USDC + nilai aset di mid.
    Gagal (ValueError) bila kredensial/CLI tidak tersedia — tidak pernah mengarang angka.
    Deadman memakai angka ini sebagai baseline: tanpa perps, 79% modal tidak terpantau."""
    d = str(root / "scripts/research/mode_a_20261026")
    if d not in sys.path:
        sys.path.insert(0, d)
    try:
        import mode_a_live as live  # noqa: PLC0415
        import spot_exec as sx  # noqa: PLC0415
        env = live.load_env()
        bal = live.get_balances(env)
        books = {a: sx.fetch_book(a) for a in live.ASSETS}
        spot = float(bal["usdc"] + sum(bal[a] * books[a]["mid"] for a in live.ASSETS))
        return spot + perps_equity_from_venue(root)
    except ValueError:
        raise
    except Exception as e:  # Block/ExecError/ImportError -> fail closed
        raise ValueError(f"sumber venue tidak tersedia: {str(e)[:160]}") from e


def append_point(path: Path, equity: float, source: str, ts: str | None = None,
                 min_gap_h: float = 0.0, note: str = "") -> dict:
    """Titik ekuitas dengan jeda minimum (untuk sampling 5 jam yang idempoten)."""
    if min_gap_h > 0:
        rows = read_rows(path)
        if rows:
            last = max(_utc(r["ts"]) for r in rows if r.get("ts"))
            gap = (_utc(ts) - last).total_seconds() / 3600
            if gap < min_gap_h:
                return {"written": False, "alasan": f"jeda {gap:.2f}j < {min_gap_h}j"}
    return append_record(path, equity, source, ts=ts, force=True, note=note)


def coverage(rows: list[dict], need_days: int = 30) -> dict:
    days = sorted({_day(_utc(r["ts"])) for r in rows if r.get("ts")})
    if not days:
        return {"hari": 0, "celah": [], "hari_hilang_dalam_span": None,
                "cukup_30": False, "pertama": None, "terakhir": None}
    dts = [datetime.fromisoformat(d).date() for d in days]
    span = (dts[-1] - dts[0]).days + 1
    missing = []
    cur = dts[0]
    from datetime import timedelta
    have = set(dts)
    while cur <= dts[-1]:
        if cur not in have:
            missing.append(cur.isoformat())
        cur += timedelta(days=1)
    return {"hari": len(days), "celah": missing, "hari_hilang_dalam_span": len(missing),
            "cukup_30": len(days) >= need_days and not missing,
            "pertama": days[0], "terakhir": days[-1], "span_hari": span}


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "check"
    try:
        if cmd == "snapshot":
            src = "unknown"
            val = None
            if "--from-mode-a" in argv:
                val, src = equity_from_mode_a(), "mode_a_ledger"
            elif "--from-file" in argv:
                p = Path(argv[argv.index("--from-file") + 1])
                if not p.exists():
                    print(f"ERROR: file tidak ada: {p}", file=sys.stderr)
                    return 2
                val, src = equity_from_file(p), f"file:{p.name}"
            elif "--from-json" in argv:
                raw = argv[argv.index("--from-json") + 1]
                obj = json.loads(raw)
                val = next((float(obj[k]) for k in EQUITY_KEYS if obj.get(k) is not None), None)
                src = "inline-json"
            elif "--from-venue" in argv:
                val, src = equity_from_venue(ROOT), "venue_spot+perps"
            else:
                print("ERROR: pilih --from-mode-a | --from-file | --from-json | --from-venue",
                      file=sys.stderr)
                return 2
            if val is None:
                print(f"ERROR: sumber '{src}' tidak memuat ekuitas; TIDAK menulis apa pun", file=sys.stderr)
                return 2
            gap = float(argv[argv.index("--min-gap-h") + 1]) if "--min-gap-h" in argv else 0.0
            r = append_point(LEDGER, val, src, min_gap_h=gap) if gap > 0 else \
                append_record(LEDGER, val, src, force="--force" in argv)
            print(json.dumps(r, sort_keys=True))
            return 0
        if cmd == "check":
            rows = read_rows(LEDGER)
            c = coverage(rows)
            last_age = None
            if rows:
                last = max(_utc(r["ts"]) for r in rows if r.get("ts"))
                last_age = round((datetime.now(timezone.utc) - last).total_seconds() / 3600, 1)
            print(json.dumps({**c, "baris": len(rows), "umur_terakhir_jam": last_age,
                              "ledger": str(LEDGER.relative_to(ROOT))}, sort_keys=True))
            return 0 if c["cukup_30"] else 3
        print(f"ERROR: perintah tidak dikenal: {cmd}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"ERROR tak terduga: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
