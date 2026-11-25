#!/usr/bin/env python3
"""P9 RERUN — mv_funding (dijadwalkan 15-Okt-2026, lihat D15 §7 langkah 1).

Menjalankan ulang sensus edge (scripts/sodex_edge_census.py) lalu membandingkan
mv_funding terhadap baseline D15 yang DIBEKUKAN. Ambang P9 tidak diubah.

READ-ONLY terhadap lane: census hanya membaca; skrip ini menulis laporan + registry.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Baseline D15 (dibekukan 05-Okt-2026) — untuk PEMBANDING, bukan ambang.
BASE = {
    "n_windows": 15, "mean48_pct": 0.3975, "sharpe_annual": 8.06,
    "p_day_cluster": 0.0359, "segments_positive": 3, "segments_assessable": 3,
    "n": 96,
}
MIN_WINDOWS = 20   # ambang P9 asli (n_windows), tidak diubah


def load_tg():
    """Impor pengirim Telegram yang sudah ada (jangan duplikasi kode)."""
    try:
        spec = importlib.util.spec_from_file_location(
            "tg", ROOT / "scripts/pregain_telegram_report.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    except Exception:
        return None


def main() -> int:
    census = ROOT / "scripts/sodex_edge_census.py"
    print("[P9 rerun] menjalankan census ...")
    rc = subprocess.run([sys.executable, str(census)], cwd=str(ROOT),
                        capture_output=True, text=True, timeout=1800)
    print(f"[P9 rerun] census exit={rc.returncode}")

    try:
        data = json.loads((ROOT / "data/sodex_edge_census.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[P9 rerun] GAGAL baca hasil census: {exc}")
        return 1

    engines = data.get("engines", [])
    mv = next((e for e in engines if e.get("name") == "mv_funding"), None)
    if mv is None:
        print("[P9 rerun] mv_funding tidak ada di hasil census")
        return 1

    n = mv.get("n_windows", 0)
    enough = n >= MIN_WINDOWS
    seg_ok = mv.get("segments_assessable", 0) > 0 and \
        mv.get("segments_positive") == mv.get("segments_assessable")
    p_ok = mv.get("p_day_cluster", 1.0) < 0.05
    yes = bool(mv.get("pass"))
    verdict = "MV_FUNDING_LULUS_P9" if yes else (
        "BELUM_CUKUP_DATA" if not enough else "GAGAL_P9")

    lines = [
        "# P9 RERUN — mv_funding",
        "",
        f"Dijalankan: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"**Putusan: `{verdict}`**",
        "",
        "| Metrik | Baseline D15 (05-Okt) | Sekarang |",
        "|---|---|---|",
        f"| n trade | {BASE['n']} | {mv.get('n')} |",
        f"| n_windows (ambang {MIN_WINDOWS}) | {BASE['n_windows']} | **{n}** |",
        f"| mean48 | {BASE['mean48_pct']:+.4f}% | {mv.get('mean48_pct', float('nan')):+.4f}% |",
        f"| SR tahunan | {BASE['sharpe_annual']:.2f} | {mv.get('sharpe_annual', float('nan')):.2f} |",
        f"| p_day_cluster | {BASE['p_day_cluster']:.4f} | {mv.get('p_day_cluster', float('nan')):.4f} |",
        f"| segmen | {BASE['segments_positive']}/{BASE['segments_assessable']} "
        f"| {mv.get('segments_positive')}/{mv.get('segments_assessable')} |",
        f"| BH-FDR | {'ya' if mv.get('bh_pass') else 'tidak'} | "
        f"{'ya' if mv.get('bh_pass') else 'tidak'} |",
        "",
        f"Syarat: n_windows≥{MIN_WINDOWS} {'OK' if enough else 'BELUM'} · "
        f"seg 3/3 {'OK' if seg_ok else 'TIDAK'} · p<0,05 {'OK' if p_ok else 'TIDAK'}",
        "",
        "Ambang P9 TIDAK diubah. Target 0,8%/48j tidak diubah.",
    ]
    rep = ROOT / "reports/sodex" / f"P9_RERUN_{datetime.now(timezone.utc):%Y-%m-%d}.md"
    rep.write_text("\n".join(lines) + "\n")
    with (ROOT / "reports/sodex/P9_RERUN_registry.jsonl").open("a") as fh:
        fh.write(json.dumps({"utc": datetime.now(timezone.utc).isoformat(),
                             "verdict": verdict, "mv": mv}) + "\n")

    msg = (f"[SoDEX P9 RERUN] {verdict}\n"
           f"mv_funding: n_windows={n}/{MIN_WINDOWS} "
           f"mean48={mv.get('mean48_pct', float('nan')):+.3f}% "
           f"SR={mv.get('sharpe_annual', float('nan')):.2f} "
           f"p_day={mv.get('p_day_cluster', float('nan')):.4f} "
           f"seg={mv.get('segments_positive')}/{mv.get('segments_assessable')}\n"
           f"Laporan: {rep.name}\n— Hermes Anantara v3")
    tg = load_tg()
    if tg is not None:
        try:
            tg.load_telegram_env()
            ok = tg.send_telegram(msg)
            print(f"[P9 rerun] telegram: {'terkirim' if ok else 'tidak terkirim'}")
        except Exception as exc:  # best-effort, jangan gagalkan laporan
            print(f"[P9 rerun] telegram dilewati: {exc}")
    else:
        print("[P9 rerun] pengirim telegram tidak tersedia — laporan lokal saja")

    print(f"[P9 rerun] verdict={verdict} n_windows={n} report={rep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
