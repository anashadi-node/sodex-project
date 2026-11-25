#!/usr/bin/env python3
"""SoDEX profit-field scanner (READ-ONLY). Ranks spot markets by maker-profit
potential, flags transient opportunities, checks E1 health + WSOSO price.

Placed 2026-07-03 for the 6h profit-execution mission. No trading — analysis only.
Run: python3 scripts/sodex_profit_scan.py
"""
import os, subprocess, json, math, sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta

PROJECT = Path(__file__).resolve().parent.parent
BASELINE = PROJECT / "data" / "profit_scan_baseline.json"  # ponytail: 1 file, remembers last spreads

def _dv(p, k):
    try:
        for line in Path(p).read_text().splitlines():
            line = line.strip()
            if line.startswith(k + "="):
                return line.split("=", 1)[1].split(" #")[0].strip().strip('"').strip("'")
    except Exception:
        return None

def _env():
    e = os.environ.copy()
    for k in ["SODEX_PRIVATE_KEY", "SODEX_ACCOUNT_ID", "SODEX_ADDRESS"]:
        v = _dv(PROJECT / ".env", k)
        if v:
            e[k] = v
    return e

def _cli(env, *a, t=20):
    try:
        r = subprocess.run(["timeout", str(t), str(PROJECT / "bin" / "sodex"), *a],
                           capture_output=True, text=True, env=env, timeout=t + 3)
        return json.loads(r.stdout)
    except Exception:
        return []

# Fees: SoDEX taker ~0.045%/side. Maker roundtrip needs spread to clear ~2x taker as floor.
FEE_RT = 0.09  # % roundtrip floor a maker spread must beat to be worth quoting

def scan():
    env = _env()
    tk = _cli(env, "tickers", "spot", "--format", "json")
    rows = []
    for t in tk:
        try:
            bid = float(t["bidPx"]); ask = float(t["askPx"])
            if bid <= 0 or ask <= 0:
                continue
            mid = (bid + ask) / 2
            spread = (ask - bid) / mid * 100
            qv = float(t.get("quoteVolume", 0))
            hi = float(t.get("highPx", 0)); lo = float(t.get("lowPx", 0))
            rng = (hi - lo) / mid * 100 if mid else 0
            bidusd = float(t.get("bidSz", 0)) * bid
            askusd = float(t.get("askSz", 0)) * ask
            flow = math.log10(max(qv, 1) + 1)
            wall = min(bidusd, askusd)
            wf = 1.0 if wall < 2000 else (0.5 if wall < 10000 else 0.25)
            rows.append(dict(sym=t["symbol"], spread=spread, qv=qv, rng=rng,
                             bidusd=bidusd, askusd=askusd, mid=mid,
                             score=spread * flow * wf,
                             worth=spread > FEE_RT))
        except Exception:
            continue
    rows.sort(key=lambda x: -x["score"])

    # Baseline diff — flag transient spread spikes (opportunity)
    base = {}
    if BASELINE.exists():
        try:
            base = json.loads(BASELINE.read_text())
        except Exception:
            base = {}
    alerts = []
    for r in rows:
        prev = base.get(r["sym"], {}).get("spread")
        if prev and r["spread"] > prev * 1.8 and r["spread"] > FEE_RT:
            alerts.append(f"SPREAD SPIKE {r['sym']}: {prev:.3f}%→{r['spread']:.3f}%")
    try:
        BASELINE.write_text(json.dumps({r["sym"]: {"spread": r["spread"]} for r in rows}))
    except Exception:
        pass
    return rows, alerts

def e1_health():
    db = PROJECT / "twin_engine.db"
    if not db.exists():
        return {}
    c = sqlite3.connect(str(db))
    cut = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    rts = c.execute(f"SELECT COUNT(*),COALESCE(SUM(CAST(net_pnl AS REAL)),0) FROM rts WHERE ts_close>='{cut}'").fetchone()
    fills = c.execute(f"SELECT COUNT(*) FROM fills WHERE ts>='{cut}'").fetchone()[0]
    alive = bool(subprocess.run(["pgrep", "-f", "sodex_twin_engine.py run"],
                                capture_output=True).stdout.strip())
    return {"alive": alive, "rts_1h": rts[0], "pnl_1h": rts[1], "fills_1h": fills}

def main():
    rows, alerts = scan()
    env = _env()
    wsoso = _cli(env, "orderbook", "spot", "WSOSO_vUSDC", "--depth", "1", "--format", "json")
    wp = float(wsoso["bids"][0]["price"]) if isinstance(wsoso, dict) and wsoso.get("bids") else 0
    h = e1_health()
    print(f"═══ SoDEX PROFIT SCAN {datetime.now(timezone.utc).strftime('%H:%M:%SZ')} ═══")
    print(f"E1: {'ALIVE' if h.get('alive') else 'DOWN'} | 1h: {h.get('rts_1h',0)} RTs ${h.get('pnl_1h',0):.3f} | {h.get('fills_1h',0)} fills")
    print(f"WSOSO held ~307 → sell-value @ {wp:.4f} = ${307*wp:.2f}")
    worth = [r for r in rows if r["worth"]]
    print(f"Maker-worth fields (spread>{FEE_RT}%): {len(worth)}")
    print(f"{'SYMBOL':16}{'spread%':>8}{'range%':>7}{'qVol$':>10}{'score':>7}")
    for r in rows[:6]:
        flag = "✅" if r["worth"] else "  "
        print(f"{flag}{r['sym']:14}{r['spread']:>8.3f}{r['rng']:>7.2f}{r['qv']:>10,.0f}{r['score']:>7.2f}")
    if alerts:
        print("🔔 OPPORTUNITIES:")
        for a in alerts:
            print("  " + a)
    else:
        print("(no transient spikes vs last scan)")

if __name__ == "__main__":
    main()
