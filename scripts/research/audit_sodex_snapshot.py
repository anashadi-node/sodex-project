#!/usr/bin/env /usr/bin/python3
"""AUDIT FINAL SoDEX — dijalankan HANYA pada snapshot beku.
Menghasilkan satu tabel fakta untuk laporan RCA. Read-only.
"""
import glob, json, os, statistics as st, sys
from collections import defaultdict
from datetime import datetime, timezone

SNAP = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob("/home/USER/anantara-sakti/data/snapshots/sodex_*"))[-1]
CUT = datetime(2026, 9, 30, 23, 59, 59, tzinfo=timezone.utc).timestamp()
WALLET = 242.79


def ep(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


rows = []
for f in sorted(glob.glob(SNAP + "/paper_test_*_state.json")):
    tk = os.path.basename(f)[len("paper_test_"):-len("_state.json")]
    d = json.load(open(f))
    key = next((k for k in ("closed", "closed_trades", "trades") if isinstance(d.get(k), list) and d[k]), None)
    if not key:
        continue
    for x in d[key]:
        ts = ep(x.get("entry_ts") or x.get("entry_time"))
        if ts is None:
            continue
        rows.append(dict(tk=tk, ts=ts, usd=float(x.get("pnl_usd") or 0),
                         side=str(x.get("direction", "")).upper()[:1],
                         rnd=str(x.get("track", "")).upper() == "RANDOM",
                         pct=(float(x["pnl_pct"]) if isinstance(x.get("pnl_pct"), (int, float)) else None),
                         hr=datetime.fromtimestamp(ts, timezone.utc).hour,
                         why=str(x.get("exit_reason", "?"))))

print(f"SNAPSHOT: {SNAP}")
print(f"total trade {len(rows)} | sum ${sum(r['usd'] for r in rows):+.2f} | wallet ${WALLET}")


def tbl(rs, lab):
    if not rs:
        print(f"{lab}: kosong")
        return
    w = sum(1 for r in rs if r["usd"] > 0)
    print(f"{lab:24s} n={len(rs):4d} WR={w/len(rs):5.1%} sum=${sum(r['usd'] for r in rs):+9.2f} "
          f"mean=${st.mean([r['usd'] for r in rs]):+6.2f} "
          f"per-window={100*sum(r['usd'] for r in rs)/(WALLET*max(1,(max(q['ts'] for q in rs)-min(q['ts'] for q in rs))/108000)):+.2f}%")


print("\n=== PER BUKU (semua, REAL saja) ===")
for tk in sorted({r['tk'] for r in rows}):
    tbl([r for r in rows if r["tk"] == tk and not r["rnd"]], f"  {tk}")

print("\n=== PER PERIODE (REAL) ===")
tr = [r for r in rows if r["ts"] <= CUT and not r["rnd"]]
sn = [r for r in rows if r["ts"] > CUT and not r["rnd"]]
tbl(tr, "  train 06-Agu..30-Sep")
tbl(sn, "  seen  01-Okt..22-Okt")

print("\n=== KONTROL TERBENAM (RANDOM) ===")
tbl([r for r in rows if r["rnd"] and r["ts"] <= CUT], "  train RANDOM")
tbl([r for r in rows if r["rnd"] and r["ts"] > CUT], "  seen  RANDOM")

print("\n=== SISI & JAM (semua REAL) ===")
tbl([r for r in rows if not r["rnd"] and r["side"] == "L"], "  LONG")
tbl([r for r in rows if not r["rnd"] and r["side"] == "S"], "  SHORT")
tbl([r for r in rows if not r["rnd"] and r["hr"] == 0], "  jam 00Z")
tbl([r for r in rows if not r["rnd"] and r["hr"] != 0], "  jam != 00Z")

print("\n=== EXIT REASON (REAL) ===")
g = defaultdict(list)
for r in rows:
    if not r["rnd"]:
        g[r["why"]].append(r["usd"])
for k, v in sorted(g.items(), key=lambda kv: -len(kv[1])):
    print(f"  {k:14s} n={len(v):4d} ({len(v)/max(1,sum(len(z) for z in g.values())):4.0%}) "
          f"sum=${sum(v):+9.2f} mean=${st.mean(v):+6.2f}")

print("\n=== KONSISTENSI WINDOW 30h (REAL, grid tetap 03-Agu) ===")
A = datetime(2026, 8, 3, tzinfo=timezone.utc).timestamp()
for lab, rs in (("train", tr), ("seen", sn)):
    b = defaultdict(float)
    for r in rs:
        k = int((r["ts"] - A) // (30 * 3600))
        if k >= 0:
            b[k] += r["usd"]
    if not b:
        continue
    v = [100 * x / WALLET for x in b.values()]
    print(f"  {lab}: n_win={len(v)} mean={st.mean(v):+.2f}% median={st.median(v):+.2f}% "
          f"hit>=0.8%={sum(1 for x in v if x>=0.8)}/{len(v)} ({sum(1 for x in v if x>=0.8)/len(v):.0%})")
