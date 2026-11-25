#!/usr/bin/env python3
"""
ANANTARA — AUDIT CONTINUOUS IMPROVEMENT SoDEX + CEX (DETERMINISTIK, NOL LLM)

Menggantikan cron job berbasis-LLM `dcdcace8` yang berulang kali gagal 429.
Membaca sumber nyata, menghitung capaian vs target, dan — hanya bila ada
perubahan bermakna — mencetak ringkasan. Stdout kosong = tidak ada laporan.

READ-ONLY total. Tidak menulis apa pun kecuali state pembanding kecil.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti")))
TARGET_PCT = 0.8          # Target North Star: >=0,8% total wallet per window 30 jam
STATE = PROJ / "data" / "rutin_divisi" / "audit_sodex_cex_state.json"


def _load(p: Path) -> dict:
    try:
        d = json.loads(p.read_text())
    except Exception:
        return {}
    return d if isinstance(d, dict) else {}


def _gate_sodex() -> dict:
    d = _load(PROJ / "data" / "sodex_maturation_status.json")
    out = {}
    for name, g in (d.get("gates") or {}).items():
        if not isinstance(g, dict):
            continue
        out[name] = {
            "n": g.get("n"),
            "wr": g.get("wr"),
            "pf": g.get("pf"),
            "window_mean_pct": g.get("window_mean_pct"),
            "window_median_pct": g.get("window_median_pct"),
            "window_hit_rate": g.get("window_hit_rate"),
            "window_worst_pct": g.get("window_worst_pct"),
            "verdict": g.get("verdict"),
        }
    return out


def _cex_stats() -> dict:
    """Trade CEX dari PostgreSQL (read-only). Gagal → NO-DATA, bukan nol."""
    try:
        env = {}
        for line in (PROJ / ".env").read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
        pw = env.get("POSTGRES_PASSWORD", "")
        import psycopg2  # noqa
        conn = psycopg2.connect(
            f"postgresql://anantara:{pw}@localhost:5432/anantara", connect_timeout=5)
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*),
                   COALESCE(SUM(close_profit_abs),0),
                   COALESCE(AVG(close_profit),0),
                   COALESCE(SUM(CASE WHEN close_profit>0 THEN 1 ELSE 0 END),0)
            FROM trades WHERE is_open=false AND close_date >= NOW() - INTERVAL '30 days'
        """)
        n, pnl, avg, wins = cur.fetchone()
        conn.close()
        n = int(n or 0)
        return {"n_30d": n, "pnl_30d": round(float(pnl), 4),
                "avg_30d_pct": round(float(avg) * 100, 4),
                "wr_30d": round(float(wins) / n, 4) if n else None}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"[:120], "n_30d": None}


def _prev() -> dict:
    return _load(STATE)


def _save(d: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(d, indent=1, sort_keys=True))


def _differs_significantly(new: dict, old: dict) -> bool:
    """Kirim laporan hanya bila ada perubahan bermakna (anti-noise)."""
    if not old:
        return True
    for gate in ("REAL-WIDE", "TWO-WAY"):
        n_new = (new.get("sodex", {}).get(gate) or {}).get("n")
        n_old = (old.get("sodex", {}).get(gate) or {}).get("n")
        if n_new != n_old:
            return True
        v_new = (new.get("sodex", {}).get(gate) or {}).get("verdict")
        v_old = (old.get("sodex", {}).get(gate) or {}).get("verdict")
        if v_new != v_old:
            return True
    if (new.get("cex", {}).get("n_30d") != old.get("cex", {}).get("n_30d")):
        return True
    return False


def main() -> int:
    sodex = _gate_sodex()
    cex = _cex_stats()
    now = datetime.now(timezone.utc).isoformat()

    state = {"ts": now, "sodex": sodex, "cex": cex}
    old = _prev()
    if not _differs_significantly(state, old):
        return 0                      # stdout kosong = tidak ada laporan (sesuai no_agent)

    L = [f"📊 AUDIT SoDEX+CEX (deterministik, nol LLM) — {now[:16]}Z", ""]
    for gate in ("REAL-WIDE", "TWO-WAY"):
        g = sodex.get(gate)
        if not g:
            L.append(f"• {gate}: NO-DATA")
            continue
        mean = g.get("window_mean_pct")
        lulus = (mean is not None and mean >= TARGET_PCT)
        L.append(f"• {gate}: n={g.get('n')} WR={g.get('wr')} PF={g.get('pf')} "
                 f"mean/window={mean}% (target {TARGET_PCT}%) → "
                 f"{'LULUS' if lulus else 'BELUM'} | verdict: {g.get('verdict')}")
        if g.get("window_worst_pct") is not None:
            L.append(f"    window terburuk {g['window_worst_pct']}% · "
                     f"hit-rate window {g.get('window_hit_rate')}")

    if cex.get("n_30d") is not None:
        L.append(f"• CEX 30d: n={cex['n_30d']} PnL=${cex['pnl_30d']} "
                 f"avg={cex['avg_30d_pct']}% WR={cex['wr_30d']}")
    else:
        L.append(f"• CEX 30d: NO-DATA ({cex.get('error')})")

    # kesimpulan deterministik (tanpa LLM) — perhatikan SEMUA komponen gate,
    # bukan hanya mean/window (TWO-WAY bisa lulus mean tapi gagal WR/PF).
    real = sodex.get("REAL-WIDE") or {}
    two = sodex.get("TWO-WAY") or {}
    kurang = []
    for nama, g in (("REAL-WIDE", real), ("TWO-WAY", two)):
        if not g:
            continue
        if (g.get("window_mean_pct") or 0) < TARGET_PCT:
            kurang.append(f"{nama} mean/window < {TARGET_PCT}%")
        v = str(g.get("verdict") or "")
        if v.upper().startswith("NO-GO"):
            kurang.append(f"{nama} verdict NO-GO ({v.split('—')[-1].strip()[:60]})")
    L.append("")
    L.append("Kesimpulan: " + ("semua gate capai target." if not kurang
                                else "GAP → " + "; ".join(kurang)))

    _save(state)
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
