#!/usr/bin/env python3
"""Edge per lane dari closed trade 24 jam terakhir — dasar keputusan matikan lane.

Output: tabel per lane (n, WR, mean/median/sum pnl_pct, wallet_roi) + split
SIGNAL vs RANDOM (delta = diagnostik signal-vs-random), sortir by sum desc.
Tanpa dedup/statistik ini keputusan matikan-lane = tebakan.
"""
from __future__ import annotations

import glob
import json
import statistics as st
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = ("telemetry", "orderflow", "book", "l2", "watchdog", "fills", "decisions",
        "archive", "funding", "learning", "capital_report", "replay", "stability", "probe")


def ts_of(rec: dict):
    for k in ("exit_time", "exit_ts", "ts", "time", "timestamp"):
        v = rec.get(k)
        if not v:
            continue
        try:
            s = str(v).replace("Z", "+00:00")
            d = datetime.fromisoformat(s)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def collect(hours: float):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    lanes: dict[str, list[dict]] = {}
    files = sorted(set(glob.glob(str(ROOT / "data" / "*.jsonl"))
                       + glob.glob(str(ROOT / "data" / "**" / "*trades*.jsonl"), recursive=True)))
    for path in files:
        p = Path(path)
        if any(tok in p.name for tok in SKIP):
            continue
        try:
            if p.stat().st_size > 400 * 1024 * 1024:
                continue
            lines = p.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines[-40000:]:
            line = line.strip()
            if not line or '"pnl_pct"' not in line:
                continue
            line = line[line.find("{"):] if line.find("{") > 0 else line
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(rec.get("status", "")).upper() != "CLOSED":
                continue
            if not isinstance(rec.get("pnl_pct"), (int, float)):
                continue
            t = ts_of(rec)
            if t is None or t < cutoff:
                continue
            rec["_lane"] = p.stem
            rec["_file"] = p.name
            lanes.setdefault(p.stem, []).append(rec)
    return lanes


def summarize(rows: list[dict]) -> dict:
    pnl = [float(r["pnl_pct"]) for r in rows]
    roi = [float(r["wallet_roi"]) for r in rows if isinstance(r.get("wallet_roi"), (int, float))]
    wins = [x for x in pnl if x > 0]
    return {
        "n": len(pnl),
        "wr": 100.0 * len(wins) / len(pnl),
        "mean_pp": 100.0 * st.mean(pnl),
        "median_pp": 100.0 * st.median(pnl),
        "sum_pp": 100.0 * sum(pnl),
        "roi_n": len(roi),
        "roi_mean_pp": 100.0 * st.mean(roi) if roi else float("nan"),
        "roi_sum_pp": 100.0 * sum(roi) if roi else float("nan"),
    }


def fmt(label: str, s: dict) -> str:
    return (f"{label:<38} n={s['n']:<4} WR={s['wr']:5.1f}%  "
            f"mean={s['mean_pp']:+6.3f}pp  med={s['median_pp']:+6.3f}pp  "
            f"SUM={s['sum_pp']:+7.2f}pp  roi_mean={s['roi_mean_pp']:+6.3f}pp")


def stats_block(lanes: dict, hours: float) -> None:
    """Uji satu-sisi per lane: apakah mean pnl_pct < 0 secara statistik (BH-FDR).

    Bootstrap CI95 (10k resample) + t-test satu sisi + koreksi Benjamini-Hochberg.
    Lane dengan CI95 sepenuhnya < 0 = bukti cukup untuk dimatikan, bukan tebakan.
    """
    import numpy as np
    from scipy import stats as sps

    rows = []
    for name, recs in lanes.items():
        for track in ("SIGNAL", "RANDOM", ""):
            sub = recs if not track else [r for r in recs
                                          if str(r.get("track", "")).upper() == track]
            if len(sub) < 15:
                continue
            x = np.array([float(r["pnl_pct"]) for r in sub]) * 100.0
            t, p2 = sps.ttest_1samp(x, 0.0)
            p1 = p2 / 2 if t < 0 else 1 - p2 / 2
            rng = np.random.default_rng(7)
            boot = x[rng.integers(0, len(x), size=(10000, len(x)))].mean(axis=1)
            lo, hi = np.percentile(boot, [2.5, 97.5])
            rows.append({"lane": name, "track": track or "ALL", "n": len(x),
                         "mean_pp": x.mean(), "ci_lo": lo, "ci_hi": hi, "p": p1})
    if not rows:
        print("(n<15 di semua lane — tidak ada uji)")
        return
    rows.sort(key=lambda r: r["p"])
    m = len(rows)
    prev = 1.0
    for i in range(m - 1, -1, -1):
        q = rows[i]["p"] * m / (i + 1)
        rows[i]["q"] = min(prev, q)
        prev = rows[i]["q"]
    print(f"\n--- uji statistik window {hours:g} jam (BH-FDR, satu sisi) ---")
    print(f"{'lane/track':<44}{'n':>4}{'mean_pp':>10}{'CI95':>22}{'p':>9}{'q':>9}  verdict")
    for r in rows:
        if r["q"] < 0.05 and r["ci_hi"] < 0:
            v = "EDGE NEGATIF (kill kandidat)"
        elif r["q"] < 0.05:
            v = "beda dari nol (arah lain)"
        else:
            v = "belum cukup data"
        print(f"{r['lane'] + '/' + r['track']:<44}{r['n']:>4}{r['mean_pp']:>+10.3f}"
              f"{r['ci_lo']:>+11.3f}..{r['ci_hi']:>+9.3f}{r['p']:>9.4f}{r['q']:>9.4f}  {v}")


def main():
    for hours in (24.0, 24.0 * 7):
        lanes = collect(hours)
        print(f"\n=== window {hours:g} jam — {len(lanes)} lane, "
              f"{sum(len(v) for v in lanes.values())} trade CLOSED ===")
        order = sorted(lanes.items(), key=lambda kv: summarize(kv[1])["sum_pp"], reverse=True)
        for name, rows in order:
            print(fmt(name, summarize(rows)))
            for track in ("SIGNAL", "RANDOM"):
                sub = [r for r in rows if str(r.get("track", "")).upper() == track]
                if sub:
                    print("   " + fmt(f"  └ {track}", summarize(sub)))
        # agregat lintas lane
        allrows = [r for rows in lanes.values() for r in rows]
        if allrows:
            print(fmt("TOTAL", summarize(allrows)))
            sig = [r for r in allrows if str(r.get("track", "")).upper() == "SIGNAL"]
            rnd = [r for r in allrows if str(r.get("track", "")).upper() == "RANDOM"]
            stats_block(lanes, hours)
            if sig and rnd:
                a, b = summarize(sig), summarize(rnd)
                print(f"DELTA signal-random: mean {a['mean_pp'] - b['mean_pp']:+.3f}pp, "
                      f"WR {a['wr'] - b['wr']:+.1f}pp  (n={a['n']} vs {b['n']})")


if __name__ == "__main__":
    main()
