#!/usr/bin/env python3
"""Audit integritas SAMPEL gate SoDEX (read-only).

Masalah yang dijaga: daftar pair-pause dibaca dari `data/paper_test_edge_gate.json`
yang di-regenerasi harian dan **diterapkan surut ke seluruh histori**. Artinya mean
gate hari ini tidak harus sama dengan mean gate kemarin untuk trade yang sama
(seleksi tidak reprodusibel). Alat ini:

1. menghitung versi TERFILTER (aturan resmi tracker) dan TANPA filter (kontrol),
2. merekam daftar pause + sha256 ke `reports/sodex/GATE_SAMPLE_AUDIT.jsonl` (append-only),
3. membandingkan dengan rekaman terakhir -> melaporkan drift daftar pause.

Exit: 0 normal, 1 drift terdeteksi, 2 error input.
Tidak menulis state trading, tidak menyentuh gate, tidak mengubah parameter.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDGE_GATE = ROOT / "data/paper_test_edge_gate.json"
AUDIT = ROOT / "reports/sodex/GATE_SAMPLE_AUDIT.jsonl"
ANCHOR = datetime(2026, 8, 3, tzinfo=timezone.utc).timestamp()
WINDOW_S = 30 * 3600
WALLET = 243.74
PAUSED_FALLBACK = {"SUI", "ADA", "HYPE", "ONDO"}
GATES = [
    {"id": "REAL-WIDE", "state": "data/paper_test_realwide_state.json",
     "cutover": datetime(2026, 9, 5, 2, 20, tzinfo=timezone.utc).timestamp(),
     "exclude_paused": True, "edge_key": "REAL-wide"},
    {"id": "TWO-WAY", "state": "data/paper_test_twoway_state.json",
     "cutover": None, "exclude_paused": False, "edge_key": None},
]


def sample_digest(syms) -> str:
    return hashlib.sha256(",".join(sorted(set(syms))).encode()).hexdigest()[:16]


def diff_lists(prev, cur) -> dict:
    p, c = set(prev), set(cur)
    return {"ditambah": sorted(c - p), "dihapus": sorted(p - c), "berubah": p != c}


def _ts(v):
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def load_trades(path: Path, cutover=None, exclude=()) -> tuple[list, Counter]:
    d = json.loads(path.read_text())
    rows = next((d[k] for k in ("closed", "closed_trades", "trades")
                 if isinstance(d.get(k), list) and d[k]), [])
    out, sk = [], Counter()
    for t in rows:
        if t.get("stale_exit"):
            sk["stale_exit"] += 1
            continue
        e = t.get("exit_ts")
        if e is None:
            for f in ("exit_iso", "exit_time"):
                if t.get(f):
                    e = _ts(t[f])
                    break
        e = _ts(e)
        usd = t.get("pnl_usd")
        if e is None or usd is None:
            sk["tanpa_ts_usd"] += 1
            continue
        sym = str(t.get("sym") or t.get("pair") or "").split("/")[0]
        if sym in set(exclude):
            sk["pause"] += 1
            continue
        if cutover and e <= cutover:
            sk["pra_cutover"] += 1
            continue
        out.append({"exit_ts": e, "usd": float(usd), "sym": sym,
                    "dir": t.get("direction") or t.get("side") or "?",
                    "pct": t.get("pnl_pct")})
    return out, sk


def window_stats(trades, wallet: float = WALLET) -> dict:
    b = defaultdict(float)
    for t in trades:
        k = int((t["exit_ts"] - ANCHOR) // WINDOW_S)
        if k >= 0:
            b[k] += t["usd"]
    vals = [100.0 * b[k] / wallet for k in sorted(b)]
    if not vals:
        return {"n": 0}
    m = st.mean(vals)
    sd = st.stdev(vals) if len(vals) > 1 else 0.0
    se = sd / math.sqrt(len(vals)) if len(vals) > 1 else float("inf")
    return {"n": len(vals), "mean": round(m, 4), "median": round(st.median(vals), 4),
            "sd": round(sd, 4), "t": round(m / se, 2) if se not in (0, float("inf")) else None,
            "hit_0_8": sum(1 for v in vals if v >= 0.8),
            "worst": round(min(vals), 3),
            "sum_pct": round(sum(vals), 3),
            "span_windows": (max(b) - min(b) + 1) if b else 0,
            "empty_dalam_span": (max(b) - min(b) + 1 - len(vals)) if b else 0}


def paused_pairs() -> list[str]:
    try:
        d = json.loads(EDGE_GATE.read_text())
        lst = d.get("pairs_pause", {}).get("REAL-wide")
        if isinstance(lst, list):
            return sorted(set(PAUSED_FALLBACK) | {str(x).upper() for x in lst})
    except Exception:
        pass
    return sorted(PAUSED_FALLBACK)


def main() -> int:
    try:
        pause = paused_pairs()
        rec = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "wallet_usd": WALLET, "pause_list": pause, "pause_digest": sample_digest(pause),
               "gates": {}}
        drift_any = False
        prev = {}
        if AUDIT.exists():
            for line in AUDIT.read_text().splitlines():
                if line.strip():
                    try:
                        prev = json.loads(line)
                    except Exception:
                        pass
        for g in GATES:
            p = ROOT / g["state"]
            if not p.exists():
                rec["gates"][g["id"]] = {"error": f"state tidak ada: {p}"}
                continue
            ex = pause if g["exclude_paused"] else ()
            tr, sk = load_trades(p, g["cutover"], ex)
            tr_all, sk_all = load_trades(p)
            filt = window_stats(tr)
            full = window_stats(tr_all)
            rec["gates"][g["id"]] = {"resmi": filt, "tanpa_filter": full,
                                     "skip": dict(sk), "skip_tanpa_filter": dict(sk_all),
                                     "n_trades": len(tr)}
            print(f"\n{g['id']}")
            print(f"  RESMI      n_win={filt.get('n')} mean={filt.get('mean')}% "
                  f"med={filt.get('median')}% t={filt.get('t')} hit0.8={filt.get('hit_0_8')} "
                  f"worst={filt.get('worst')}% skip={dict(sk)}")
            print(f"  TANPA FILT n_win={full.get('n')} mean={full.get('mean')}% "
                  f"med={full.get('median')}% t={full.get('t')} "
                  f"selisih_mean={round((filt.get('mean') or 0) - (full.get('mean') or 0), 4)}pp")
        if prev:
            d = diff_lists(prev.get("pause_list", []), pause)
            rec["drift_vs_sebelum"] = d
            rec["sebelum_generated_utc"] = prev.get("generated_utc")
            if d["berubah"]:
                drift_any = True
                print(f"\n!! DRIFT DAFTAR PAUSE (vs {prev.get('generated_utc')}): +{d['ditambah']} -{d['dihapus']}")
                print("   Sampel gate berubah surut; angka historis tidak sebanding antar hari.")
            else:
                print(f"\nDaftar pause stabil (digest {rec['pause_digest']}).")
        else:
            print(f"\nRekaman pertama; digest {rec['pause_digest']}.")
        AUDIT.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT.open("a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        print(f"Rekaman ditambahkan: {AUDIT.relative_to(ROOT)}")
        return 1 if drift_any else 0
    except Exception as e:  # fail loud
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
