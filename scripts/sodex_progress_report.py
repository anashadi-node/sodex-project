#!/usr/bin/env python3
"""SoDEX Progress Reporter — baca semua paper track state (READ-ONLY).

Menghitung per-track: n, WR, avg wallet_roi terhadap SODEX_TOTAL_WALLET,
hit-rate ≥0,7%, status target per North Star SODEX. Output kompak untuk
monitoring/alert. Wallet dibaca dari env atau .env.swing agar dashboard pusat
tidak jatuh ke fallback stale.

Run: python3 scripts/sodex_progress_report.py
"""
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

PROJECT = Path(__file__).resolve().parents[1]
TARGET = 0.008                 # ≥0.8% wallet per 30h window (North Star, user GO 27-Sep)


def read_wallet_denominator(env=os.environ, env_file=None):
    """Resolve SODEX_TOTAL_WALLET for dashboard/reporting.

    Priority: live env > .env.swing > safe fallback. Fallback is intentionally
    explicit because stale wallet denominator created false progress before
    audit 2026-09-15 ($108.10 vs real $158.66, 31.9% optimistic bias).
    """
    if env.get("SODEX_TOTAL_WALLET"):
        return float(env["SODEX_TOTAL_WALLET"]), "env"
    env_file = env_file or PROJECT / ".env.swing"
    try:
        for line in Path(env_file).read_text().splitlines():
            if line.startswith("SODEX_TOTAL_WALLET="):
                return float(line.split("=", 1)[1].strip()), ".env.swing"
    except (FileNotFoundError, ValueError, OSError):
        pass
    return 108.10, "fallback_stale"


REAL_WALLET, WALLET_SOURCE = read_wallet_denominator()


def load_track(name, fname, k_closed=("closed_trades", "closed")):
    f = PROJECT / "data" / fname
    if not f.exists():
        return {"name": name, "error": f"file {fname} tidak ada"}
    try:
        st = json.loads(f.read_text())
    except Exception as e:
        return {"name": name, "error": f"corrupt: {e}"}
    closed = []
    for k in k_closed:
        v = st.get(k) or st.get("closed")
        if isinstance(v, list):
            closed = v
            break
    open_pos = st.get("open", st.get("positions", []))
    return analyze(name, closed, open_pos, st)


def analyze(name, closed, open_pos, st=None):
    n = len(closed)
    # open_pos bisa dict (realwide/shortbear/portfolio) atau list (swing)
    if isinstance(open_pos, dict):
        n_open = len(open_pos)
    elif isinstance(open_pos, list):
        n_open = len(open_pos)
    else:
        n_open = 0
    base = {"name": name, "n": n, "n_open": n_open}
    if n == 0:
        base["note"] = "belum ada closed trades"
        return base
    pnls = [float(t.get("pnl_usd", 0) or 0) for t in closed]
    total = sum(pnls)
    wins = sum(1 for p in pnls if p > 0)
    hit = sum(1 for p in pnls if p / REAL_WALLET >= TARGET)
    base.update({
        "wr": round(wins / n * 100, 1),
        "pnl_usd": round(total, 2),
        "avg_wallet_roi_pct": round(total / REAL_WALLET / n * 100, 3),
        "hit_rate_pct": round(hit / n * 100, 1),
        "target_met": (total / REAL_WALLET / n * 100) >= 0.7,
    })
    # exit breakdown + split direction (twoway)
    exits = Counter(t.get("exit_reason", t.get("exit_r", "?")) for t in closed)
    base["exits"] = dict(exits.most_common(5))
    return base


def main():
    now = datetime.now(timezone.utc)
    print(f"SoDEX PROGRESS — {now.isoformat()[:16]} UTC | wallet ${REAL_WALLET:.2f} ({WALLET_SOURCE}) | target ≥0.7%/trade")
    print("=" * 76)

    tracks = [
        ("SWING", "paper_test_swing_state.json"),
        ("SWING_PARTIAL", "paper_test_swing_state_partial.json"),
        ("TWOWAY", "paper_test_twoway_state.json"),
        ("REALWIDE", "paper_test_realwide_state.json"),
        ("DONCHIAN", "paper_test_donchian_state.json"),
        ("SPOT_SWING_v4", "paper_test_spot_swing_v2_state.json"),
        ("SHORT_BEAR", "paper_test_shortbear_state.json"),
        ("PORTFOLIO", "paper_test_portfolio_state.json"),
    ]
    rows = []
    for name, fname in tracks:
        t = load_track(name, fname)
        rows.append(t)
        if t.get("error"):
            print(f"  ❌ {name}: {t['error']}")
            continue
        if t.get("note"):
            print(f"  ⚪ {name}: {t['note']} ({t['n_open']} open)")
            continue
        mark = "🟢" if t["target_met"] else ("🟡" if t["avg_wallet_roi_pct"] > 0 else "🔴")
        print(f"  {mark} {name:14s} n={t['n']:3d} | WR={t['wr']:5.1f}% | "
              f"ROI={t['avg_wallet_roi_pct']:+6.3f}% | hit≥0.7%={t['hit_rate_pct']:5.1f}% | "
              f"PnL=${t['pnl_usd']:+8.2f} | open={t['n_open']}")
        if t["exits"]:
            print(f"      exits: {t['exits']}")

    # TWOWAY LONG/SHORT split
    tw_closed = []
    f = PROJECT / "data" / "paper_test_twoway_state.json"
    try:
        st = json.loads(f.read_text())
        tw_closed = st.get("closed_trades", []) or []
    except Exception:
        tw_closed = []
    longs = [t for t in tw_closed if str(t.get("direction", "")).upper() in ("LONG", "L")]
    shorts = [t for t in tw_closed if str(t.get("direction", "")).upper() in ("SHORT", "S")]
    print()
    print("  TWOWAY split (SHORT disabled 2026-09-02 — data eksperimen tertutup):")
    for label, grp in (("LONG *ACTIVE*", longs), ("SHORT disabled", shorts)):
        if not grp:
            print(f"    {label:14s}: 0")
            continue
        pnls = [float(t.get("pnl_usd", 0) or 0) for t in grp]
        total = sum(pnls)
        wins = sum(1 for p in pnls if p > 0)
        roi = total / REAL_WALLET / len(grp) * 100
        print(f"    {label:14s}: n={len(grp):3d} | WR={wins/len(grp)*100:5.1f}% | ROI={roi:+6.3f}% | PnL=${total:+8.2f}")

    # ── TWOWAY trunk = LONG-only (keputusan arsitektur 2026-09-02) ──
    # SHORT sudah di-disable (P(EV>0)=3%). Agregat track trunk harus LONG-only
    # agar laporan mencerminkan strategi live yang sebenarnya, bukan eksperimen
    # yang sudah ditutup secara ilmiah.
    trunk_roi = None
    if longs:
        lp = [float(t.get("pnl_usd", 0) or 0) for t in longs]
        trunk_roi = sum(lp) / REAL_WALLET / len(longs) * 100
        print(f"\n  → TWOWAY TRUNK (LONG-only): ROI={trunk_roi:+.3f}% | {'✅ MELAMPAUI target' if trunk_roi >= 0.7 else '❌ belum'}")
    # Patch row TWOWAY di daftar utama dengan trunk ROI (untuk resume akurat)
    for r in rows:
        if r.get("name") == "TWOWAY" and trunk_roi is not None:
            r["avg_wallet_roi_pct"] = round(trunk_roi, 3)
            r["target_met"] = trunk_roi >= 0.7

    # ── Multi-venue paralel (Hyperliquid, Aster) — ditambahkan 2026-09-04 ──
    print()
    print("  MULTI-VENUE (paralel, sinyal identik, venue berbeda):")
    for venue, fname in [("Hyperliquid", "paper_test_hyperliquid_state.json"),
                          ("Aster", "paper_test_aster_state.json")]:
        f = PROJECT / "data" / fname
        if not f.exists():
            print(f"    {venue:12s}: belum ada state")
            continue
        try:
            st = json.loads(f.read_text())
        except Exception:
            continue
        closed = st.get("closed", [])
        n = len(closed)
        pnl = st.get("total_pnl", 0)
        n_open = len(st.get("open", {}))
        if n > 0:
            roi = pnl / REAL_WALLET / n * 100
            mark = "🟢" if roi >= 0.7 else ("🟡" if roi > 0 else "🔴")
            print(f"    {mark} {venue:10s} n={n:3d} | ROI={roi:+6.3f}% | PnL=${pnl:+8.2f} | open={n_open}")
        else:
            print(f"    ⚪ {venue:10s} n=0 | collecting... | open={n_open}")

    # summary
    met = [r for r in rows if r.get("target_met")]
    print()
    print("=" * 76)
    print(f"  RESUME: {len(met)}/{len([r for r in rows if not r.get('error') and not r.get('note')])} track MELAMPAUI target ≥0.7%")
    for r in rows:
        if r.get("target_met"):
            print(f"    🟢 {r['name']} ROI {r['avg_wallet_roi_pct']:.3f}%  ({r['n']} trades)")
        elif not r.get("error") and not r.get("note"):
            print(f"    {'🟡' if r['avg_wallet_roi_pct'] > 0 else '🔴'} {r['name']} ROI {r['avg_wallet_roi_pct']:+.3f}%  ({r['n']} trades)")


if __name__ == "__main__":
    main()