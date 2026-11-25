#!/usr/bin/env python3
"""SoDEX profit + repair report for Telegram (/sodexprofit, /sodexfix).

- report(): account value, realized E1/PVE PnL, engine health, restart-loop status.
- repair(): safe auto-fixes — clear stale restart signal, verify B56 watchdog + engine alive.

Read-only except repair() which only touches local signal files / reads state.
No trading. Run standalone: python3 scripts/sodex_profit_report.py [report|repair]
"""
import os, sys, subprocess, json, sqlite3, time
from pathlib import Path
from datetime import datetime, timezone, timedelta

PROJECT = Path(__file__).resolve().parent.parent
DB = PROJECT / "twin_engine.db"
RESTART_SIGNAL = PROJECT / "data" / "GUARDIAN_RESTART_SIGNAL"
BASELINE = PROJECT / "data" / "sodex_profit_baseline.json"  # ponytail: 1 file, remembers equity baseline

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

def _cli(env, *a, t=15):
    try:
        r = subprocess.run(["timeout", str(t), str(PROJECT / "bin" / "sodex"), *a],
                           capture_output=True, text=True, env=env, timeout=t + 3)
        return json.loads(r.stdout)
    except Exception:
        return []

def _g(rows, coin):
    for b in (rows or []):
        if b.get("coin") == coin:
            return float(b.get("total", 0))
    return 0.0

def _mid(env, sym):
    j = _cli(env, "orderbook", "spot", sym, "--depth", "1", "--format", "json")
    if isinstance(j, dict) and j.get("bids"):
        return (float(j["bids"][0]["price"]) + float(j["asks"][0]["price"])) / 2
    return 0.0

def _account_value(env):
    sp = _cli(env, "balance", "spot", "--format", "json")
    pp = _cli(env, "balance", "perps", "--format", "json")
    pepe = _mid(env, "vPEPE_vUSDC"); shib = _mid(env, "vSHIB_vUSDC"); wsoso = _mid(env, "WSOSO_vUSDC")
    usdc = _g(sp, "vUSDC") + _g(pp, "vUSDC")
    v = {
        "usdc": usdc,
        "shib": _g(sp, "vSHIB") * shib,
        "pepe": _g(sp, "vPEPE") * pepe,
        "wsoso": (_g(sp, "WSOSO") + _g(pp, "WSOSO")) * wsoso,
        "shib_qty": _g(sp, "vSHIB"),
    }
    v["total"] = v["usdc"] + v["shib"] + v["pepe"] + v["wsoso"]
    return v

def _e1_pnl():
    if not DB.exists():
        return {}
    c = sqlite3.connect(str(DB))
    life = c.execute("SELECT COUNT(*),COALESCE(SUM(CAST(net_pnl AS REAL)),0) FROM rts WHERE engine='E1'").fetchone()
    cut = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    d24 = c.execute(f"SELECT COUNT(*),COALESCE(SUM(CAST(net_pnl AS REAL)),0) FROM rts WHERE ts_close>='{cut}'").fetchone()
    fcut = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    fills = c.execute(f"SELECT COUNT(*) FROM fills WHERE ts>='{fcut}'").fetchone()[0]
    return {"e1_life_n": life[0], "e1_life": life[1], "d24_n": d24[0], "d24": d24[1], "fills_30m": fills}

def _engine_health():
    alive = bool(subprocess.run(["pgrep", "-f", "sodex_twin_engine.py run"],
                                capture_output=True).stdout.strip())
    # kills in last 15 min from watchdog log
    kills = 0
    try:
        wl = PROJECT / "logs" / "watchdog.log"
        cutoff = (datetime.now() - timedelta(minutes=15)).strftime("%H:%M:%S")
        for line in wl.read_text().splitlines()[-200:]:
            if "Daemon killed" in line and "] " in line:
                ts = line.split("]")[0].strip("[").split(" ")[-1]
                if ts >= cutoff:
                    kills += 1
    except Exception:
        kills = -1
    b56 = "B56" in (PROJECT / "scripts" / "watchdog_twin.sh").read_text()
    return {"alive": alive, "kills_15m": kills, "b56": b56}

def report():
    env = _env()
    v = _account_value(env)
    p = _e1_pnl()
    h = _engine_health()
    # equity baseline delta
    base = {}
    if BASELINE.exists():
        try: base = json.loads(BASELINE.read_text())
        except Exception: base = {}
    prev = base.get("total")
    delta_line = f" (Δ {v['total']-prev:+.2f} vs last check)" if prev else ""
    try:
        BASELINE.write_text(json.dumps({"total": v["total"], "ts": datetime.now(timezone.utc).isoformat()}))
    except Exception:
        pass
    # Valuation reconciliation: system equity oracle-values illiquid vPEPE ~3x spot (bug).
    # Show REALIZABLE (spot-mid, what you'd actually get) vs system, flag the gap.
    sys_eq = None
    try:
        mon = json.loads((PROJECT / "data" / "sodex_monitor_eval" / "latest.json").read_text())
        sys_eq = float(((mon.get("account") or {}).get("account_value") or {}).get("total_equity_usd") or 0) or None
    except Exception:
        sys_eq = None
    val_line = ""
    if sys_eq and sys_eq > v["total"] + 5:
        val_line = f"  ⚠️ system equity ${sys_eq:.0f} INFLATED +${sys_eq-v['total']:.0f} (vPEPE oracle~3x spot) — REALIZABLE is ${v['total']:.2f}"
    lines = [
        "💰 SoDEX PROFIT (realizable / spot-mid)",
        f"Total ≈ ${v['total']:.2f}{delta_line}",
        f"  USDC(safe) ${v['usdc']:.2f} | SHIB ${v['shib']:.2f} | PEPE ${v['pepe']:.2f} | WSOSO ${v['wsoso']:.2f}",
        f"E1 realized: life ${p.get('e1_life',0):+.2f} ({p.get('e1_life_n',0)} RT) | 24h ${p.get('d24',0):+.2f} ({p.get('d24_n',0)} RT)",
        f"Engine: {'🟢 alive' if h['alive'] else '🔴 DOWN'} | fills30m {p.get('fills_30m',0)} | kills15m {h['kills_15m']} | B56 {'✓' if h['b56'] else '✗'}",
    ]
    if val_line:
        lines.append(val_line)
    return "\n".join(lines)

def repair():
    fixes = []
    # 1. Clear stale restart signal (>300s) so it can't cause a spurious kill
    try:
        if RESTART_SIGNAL.exists():
            age = time.time() - RESTART_SIGNAL.stat().st_mtime
            if age > 300:
                RESTART_SIGNAL.unlink()
                fixes.append(f"cleared stale restart signal (age {age:.0f}s)")
    except Exception as e:
        fixes.append(f"signal check err: {e}")
    # 2. Verify engine alive (watchdog auto-restarts if not — just report)
    alive = bool(subprocess.run(["pgrep", "-f", "sodex_twin_engine.py run"],
                                capture_output=True).stdout.strip())
    if not alive:
        fixes.append("⚠️ engine DOWN — watchdog should restart within 60s")
    # 3. Verify B56 watchdog present
    b56 = "B56" in (PROJECT / "scripts" / "watchdog_twin.sh").read_text()
    if not b56:
        fixes.append("⚠️ B56 heartbeat-gate NOT in watchdog")
    # 4. Verify watchdog process alive
    wd = bool(subprocess.run(["pgrep", "-f", "watchdog_twin.sh"], capture_output=True).stdout.strip())
    if not wd:
        fixes.append("⚠️ watchdog DOWN — start sodex-twin-watchdog.service")
    status = "🔧 SoDEX REPAIR\n" + ("\n".join("• " + f for f in fixes) if fixes else "• all healthy, nothing to fix")
    return status

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "report"
    print(repair() if mode == "repair" else report())
