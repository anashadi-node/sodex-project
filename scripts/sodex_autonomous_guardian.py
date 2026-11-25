#!/usr/bin/env python3
"""SoDEX Autonomous Guardian v3 — Ratio + Drift + Health Monitor + Auto-Repair (24/7)

GAP-FILL untuk sodex_e1_autopilot.py:
  1. REAL RASIO monitoring (volume / net_cost, target 1:9,100)
  2. INVENTORY DRIFT detection (DB vs exchange balance)
  3. ORDERID=0 pattern detection (consecutive failures → alert)
  4. PER-PAIR PROFITABILITY gate (auto-pause suggestion via log)
  5. CONFIG AUDIT (detect pairs trading yg seharusnya disabled)
  6. DAEMON STUCK detection (fills tapi 0 RT → auto-restart via signal file)
  7. ZERO-FILL detection (daemon alive tapi tidak ada fill sama sekali)

Run via systemd timer setiap 5 menit. Independen dari daemon.
Hanya READ + ALERT + SIGNAL RESTART (via touch file).
TIDAK PERNAH kill daemon langsung — watchdog yang handle restart.

EXIT CODE: SELALU 0 (systemd Type=oneshot compatibility).
Severity dikomunikasikan via log + Telegram, bukan exit code.
"""

import json, os, sqlite3, subprocess, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal as D

PROJECT = Path(os.environ.get("ANANTARA_DIR", str(Path(__file__).resolve().parent.parent)))
DB = PROJECT / "twin_engine.db"
LOG = PROJECT / "logs" / "autonomous_guardian.log"
STATE = PROJECT / "data" / "guardian_state.json"
MONITOR_EVAL_LATEST = PROJECT / "data" / "sodex_monitor_eval" / "latest.json"

# Thresholds
RATIO_TARGET = 9100
RATIO_WARN = 8000
RATIO_CRIT = 7000
DRIFT_WARN_USD = 5.0        # $5 inventory drift → alert
DRIFT_CRIT_USD = 20.0       # $20 drift → critical
OID0_CONSEC_THRESH = 10     # 10 consecutive orderID=0 → alert
PAIR_LOSS_THRESH = -1.0     # RT PnL < -$1 over 30min → warning
PAIR_N_MIN = 10             # minimum RTs before judging pair
DEAD_PAIR_MINUTES = 60      # no fills for 60 min → dead pair alert
DAEMON_STUCK_MINUTES = 20   # fills happening tapi 0 RT for N min → stuck
ZERO_FILL_MINUTES = 15      # daemon alive tapi 0 fills for N min → critical
AUTO_RESTART_ENABLED = True # set False to disable auto-restart signal
MAX_ALERTS_PER_HOUR = 8     # rate limit

# Signal file untuk watchdog — guardian tidak kill daemon langsung
RESTART_SIGNAL = PROJECT / "data" / "GUARDIAN_RESTART_SIGNAL"

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")

_alert_count = 0
_alert_hour_start = 0.0


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}Z] {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def tg(msg: str) -> bool:
    """Send Telegram. Returns True if sent. Rate-limited."""
    global _alert_count, _alert_hour_start
    if not (TG_TOKEN and TG_CHAT):
        return False
    now = time.time()
    if now - _alert_hour_start > 3600:
        _alert_count = 0
        _alert_hour_start = now
    if _alert_count >= MAX_ALERTS_PER_HOUR:
        return False
    _alert_count += 1
    try:
        data = json.dumps({"chat_id": TG_CHAT, "text": ("🛡️ GUARDIAN\n" + msg)[:4000]}).encode()
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        urllib.request.urlopen(
            urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}),
            timeout=10)
        return True
    except Exception:
        return False


def _q(sql: str, args=()):
    """DB query helper."""
    db = sqlite3.connect(str(DB))
    cur = db.cursor()
    cur.execute(sql, args)
    rows = cur.fetchall()
    db.close()
    return rows


def _dotenv_value(path: Path, key: str) -> str:
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == key:
                    return v.strip().strip("'\"")
    except OSError:
        return ""
    return ""


def get_exchange_balance() -> dict:
    """Query SoDEX spot balance via CLI. Returns {coin: total}."""
    try:
        env = os.environ.copy()
        for key in ["SODEX_PRIVATE_KEY", "SODEX_ACCOUNT_ID", "SODEX_ADDRESS"]:
            if key not in env:
                val = _dotenv_value(PROJECT / ".env", key)
                if val:
                    env[key] = val
        r = subprocess.run(
            ["timeout", "10", str(PROJECT / "bin" / "sodex"), "balance", "--format", "json"],
            capture_output=True, text=True, timeout=12, env=env)
        if r.returncode != 0:
            return {}
        data = json.loads(r.stdout)
        return {b.get("coin", ""): float(b.get("total", 0)) for b in data if b.get("coin")}
    except Exception as e:
        log(f"BALANCE QUERY FAILED: {e}")
        return {}


def check_ratio() -> dict:
    """Calculate Real Rasio for last 24h. Returns metrics dict."""
    rows = _q("""SELECT 
        SUM(CAST(notional AS REAL)) as vol,
        SUM(CAST(fee AS REAL)) as fee
    FROM fills WHERE ts > datetime('now', '-24 hours')""")
    vol, fee = rows[0]
    vol = vol or 0; fee = fee or 0

    rows = _q("""SELECT SUM(CAST(net_pnl AS REAL)) FROM rts 
    WHERE ts_close > datetime('now', '-24 hours')""")
    pnl = rows[0][0] or 0

    net_cost = fee - pnl
    ratio = vol / net_cost if net_cost > 0 else (99999 if net_cost <= 0 else 0)
    
    # Per-pair breakdown
    pair_rows = _q("""SELECT pair, COUNT(*), SUM(CAST(net_pnl AS REAL))
    FROM rts WHERE ts_close > datetime('now', '-24 hours')
    GROUP BY pair ORDER BY SUM(CAST(net_pnl AS REAL))""")
    pairs = {r[0]: {"rts": r[1], "pnl": r[2] or 0} for r in pair_rows}

    return {
        "vol": vol, "fee": fee, "pnl": pnl, "net_cost": net_cost,
        "ratio": ratio, "pairs": pairs,
        "ok": ratio >= RATIO_TARGET,
        "warn": ratio < RATIO_WARN,
        "crit": ratio < RATIO_CRIT
    }


def check_inventory_drift() -> list:
    """Compare DB fill-derived inventory vs exchange balance. Returns drift alerts."""
    ex_bal = get_exchange_balance()
    if not ex_bal:
        return [{"alert": "Cannot query exchange balance"}]

    # Map: pair → DB net qty
    rows = _q("""SELECT pair, 
        SUM(CASE WHEN side='buy' THEN CAST(qty AS REAL) ELSE -CAST(qty AS REAL) END) as net_qty,
        MAX(ts) as last_fill
    FROM fills WHERE pair LIKE '%/%'
    GROUP BY pair""")
    
    # Coin map from SodexLiveAdapter._SYMBOL_MAP (hardcoded mirror) + dynamic fallback
    coin_of = {"PEPE/USDC": "vPEPE", "SHIB/USDC": "vSHIB",
               "AVAX/USDC": "vAVAX", "XLM/USDC": "vXLM", "SOL/USDC": "vSOL",
               "ARB/USDC": "vARB"}
    
    alerts = []
    for pair, db_qty, last_fill in rows:
        coin = coin_of.get(pair)
        if not coin:
            continue
        ex_qty = ex_bal.get(coin, 0)
        db_qty = db_qty or 0
        diff = abs(db_qty - ex_qty)
        diff_pct = (diff / ex_qty * 100) if ex_qty > 0.01 else 0
        
        # Use approximate price
        px_est = {"PEPE/USDC": 0.0000027, "SHIB/USDC": 0.0000045, 
                  "AVAX/USDC": 6.3, "XLM/USDC": 0.09, "SOL/USDC": 140,
                  "ARB/USDC": 0.35}
        px = px_est.get(pair, 1)
        diff_usd = diff * px
        
        if diff_usd > DRIFT_WARN_USD:
            alerts.append({
                "pair": pair, "db_qty": db_qty, "ex_qty": ex_qty,
                "diff_usd": diff_usd, "diff_pct": diff_pct,
                "crit": diff_usd > DRIFT_CRIT_USD,
                "last_fill": last_fill
            })
    
    return alerts


def check_orderid0() -> dict:
    """Check recent orderID=0 patterns from daemon log."""
    log_file = PROJECT / "logs" / "twin_live.log"
    if not log_file.exists():
        return {"consecutive": 0, "alert": False}
    
    try:
        # Count consecutive "oid kosong" in last 2 minutes of log
        r = subprocess.run(
            ["grep", "-a", "oid kosong", str(log_file)],
            capture_output=True, text=True, timeout=5)
        lines = r.stdout.strip().split("\n")
        recent = [l for l in lines[-50:] if "oid kosong" in l]
        
        # Count unique pairs affected
        pairs_affected = set()
        for l in recent:
            for p in ["PEPE/USDC", "SHIB/USDC", "AVAX/USDC", "XLM/USDC"]:
                if p in l:
                    pairs_affected.add(p)
        
        return {
            "recent_count": len(recent),
            "pairs_affected": list(pairs_affected),
            "alert": len(recent) >= OID0_CONSEC_THRESH
        }
    except Exception:
        return {"consecutive": 0, "alert": False}


def check_per_pair_health() -> list:
    """Check each pair's profitability and liveness."""
    rows = _q("""SELECT pair, 
        COUNT(*) as rts, 
        SUM(CAST(net_pnl AS REAL)) as pnl,
        MAX(ts_close) as last_rt
    FROM rts WHERE ts_close > datetime('now', '-30 minutes')
    GROUP BY pair""")
    
    # Also check fills for pairs that have no RTs
    fill_rows = _q("""SELECT pair, COUNT(*), MAX(ts) 
    FROM fills WHERE ts > datetime('now', '-30 minutes')
    AND pair LIKE '%/%'
    GROUP BY pair""")
    
    fill_map = {r[0]: {"fills": r[1], "last": r[2]} for r in fill_rows}
    rt_map = {r[0]: {"rts": r[1], "pnl": r[2] or 0, "last": r[3]} for r in rows}
    
    alerts = []
    all_pairs = set(list(fill_map.keys()) + list(rt_map.keys()))
    
    for pair in all_pairs:
        rt = rt_map.get(pair, {"rts": 0, "pnl": 0, "last": None})
        fl = fill_map.get(pair, {"fills": 0, "last": None})
        
        issues = []
        
        # Profitability check
        if rt["rts"] >= PAIR_N_MIN and rt["pnl"] < PAIR_LOSS_THRESH:
            issues.append(f"LOSING: {rt['rts']} RTs, PnL=${rt['pnl']:.2f}")
        
        # Dead pair check (no fills for a while but daemon might be configured)
        if fl["fills"] == 0 and fl["last"]:
            try:
                last_dt = datetime.fromisoformat(fl["last"])
                minutes_since = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
                if minutes_since > DEAD_PAIR_MINUTES:
                    issues.append(f"DEAD: no fills for {minutes_since:.0f}min")
            except Exception:
                pass
        
        if issues:
            alerts.append({"pair": pair, "issues": issues, "rt": rt, "fill": fl})
    
    return alerts


def check_daemon_stuck() -> dict:
    """Check if daemon is alive but producing no fills OR fills with no RTs (stuck).
    
    DUA POLA STUCK:
      1. ZERO-FILL: daemon process alive tapi tidak ada fill sama sekali > ZERO_FILL_MINUTES
         → kemungkinan daemon hang / loop error tanpa quote
      2. STUCK-RT: fill terus masuk tapi RT tidak selesai (orderID=0 / inventory drift)
         → daemon "sibuk" tapi tidak menyelesaikan satu pun round-trip
    
    Returns action taken.
    """
    # Check if daemon process exists
    r = subprocess.run(["pgrep", "-f", "sodex_twin_engine.py"], capture_output=True, text=True)
    daemon_alive = bool(r.stdout.strip())
    
    if not daemon_alive:
        return {"stuck": False, "action": "daemon dead — watchdog should restart"}
    
    # Check last fill time
    rows = _q("SELECT MAX(ts) FROM fills")
    last_fill = rows[0][0]
    
    # Check last RT close time
    rt_rows = _q("SELECT MAX(ts_close) FROM rts")
    last_rt = rt_rows[0][0]
    
    now_utc = datetime.now(timezone.utc)
    
    # Parse timestamps
    try:
        fill_dt = datetime.fromisoformat(last_fill) if last_fill else None
        fill_age = (now_utc - fill_dt).total_seconds() / 60 if fill_dt else 999
    except Exception:
        fill_age = 999
    
    try:
        rt_dt = datetime.fromisoformat(last_rt) if last_rt else None
        rt_age = (now_utc - rt_dt).total_seconds() / 60 if rt_dt else 999
    except Exception:
        rt_age = 999
    
    # PATTERN 1: ZERO-FILL — daemon alive tapi tidak ada fill sama sekali
    if fill_age > ZERO_FILL_MINUTES:
        fill_count = _q("SELECT COUNT(*) FROM fills WHERE ts > datetime('now', '-30 minutes')")[0][0]
        if fill_count == 0:
            msg = (f"🔴 ZERO-FILL: daemon alive tapi 0 fill selama {fill_age:.0f} menit. "
                   f"Daemon kemungkinan HANG / loop error tanpa quote.")
            log(msg)
            return _handle_stuck_restart(msg, "zero-fill", fill_age)
    
    # PATTERN 2: STUCK-RT — fills happening tapi 0 RT completed
    fill_count_recent = _q("SELECT COUNT(*) FROM fills WHERE ts > datetime('now', '-20 minutes')")[0][0]
    rt_count_recent = _q("SELECT COUNT(*) FROM rts WHERE ts_close > datetime('now', '-20 minutes')")[0][0]
    
    if fill_count_recent >= 5 and rt_count_recent == 0 and fill_age < 10:
        msg = (f"🔴 STUCK-RT: {fill_count_recent} fills dalam 20 menit tapi 0 RT selesai. "
               f"Kemungkinan orderID=0 / inventory drift parah / SELL gagal semua.")
        log(msg)
        return _handle_stuck_restart(msg, "stuck-rt", rt_age if rt_age < 999 else fill_age)
    
    # PATTERN 3: Classic — no fills for a long time (was the original check)
    if fill_age > DAEMON_STUCK_MINUTES and fill_count_recent == 0:
        msg = f"🔴 DAEMON STUCK: no fills for {fill_age:.0f} min (alive but completely idle)"
        log(msg)
        return _handle_stuck_restart(msg, "stuck-idle", fill_age)
    
    return {"stuck": False, "minutes_since_fill": fill_age, "minutes_since_rt": rt_age}


def _handle_stuck_restart(msg: str, stuck_type: str, age_min: float) -> dict:
    """Signal restart via touch file — watchdog reads & acts. NEVER kill daemon directly."""
    if AUTO_RESTART_ENABLED:
        try:
            RESTART_SIGNAL.parent.mkdir(parents=True, exist_ok=True)
            RESTART_SIGNAL.write_text(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "type": stuck_type,
                "age_minutes": round(age_min, 1),
                "message": msg
            }))
            log(f"AUTO-RESTART SIGNAL: {RESTART_SIGNAL} written → watchdog should restart daemon")
            tg(msg + f"\n⚡ RESTART SIGNAL dikirim ke watchdog ({stuck_type}, {age_min:.0f} menit)")
            return {"stuck": True, "action": f"restart-signal:{stuck_type}", "minutes": age_min}
        except Exception as e:
            log(f"GAGAL tulis restart signal: {e}")
            tg(msg + "\n⚠️ GAGAL kirim restart signal — butuh intervensi manual!")
            return {"stuck": True, "action": "signal-failed", "minutes": age_min}
    else:
        tg(msg + "\n⚠️ Auto-restart DISABLED — manual intervention needed")
        return {"stuck": True, "action": "alert only", "minutes": age_min}


def _restart_signal_fresh(max_age_s: int = 300) -> bool:
    """Return True when a recent restart signal already exists."""
    try:
        return RESTART_SIGNAL.exists() and (time.time() - RESTART_SIGNAL.stat().st_mtime) < max_age_s
    except OSError:
        return False


def check_monitor_eval_repair() -> dict:
    """Consume monitor-eval repair plan and signal safe auto-repair if needed."""
    if not MONITOR_EVAL_LATEST.exists():
        return {"active": False, "reason": "monitor_eval_missing"}
    try:
        report = json.loads(MONITOR_EVAL_LATEST.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"active": False, "reason": f"monitor_eval_unreadable:{type(exc).__name__}"}
    repair = report.get("repair_plan") or {}
    risk = report.get("monitor_risk") or {}
    if not repair.get("watchdog_restart_signal"):
        return {"active": False, "reason": "no_repair_signal", "risk": risk.get("level")}
    if _restart_signal_fresh():
        return {"active": True, "action": "restart-signal-already-fresh", "risk": risk.get("level")}
    reasons = []
    for action in repair.get("actions") or []:
        if action.get("type") == "WATCHDOG_RESTART_SIGNAL":
            reasons.extend(action.get("reason") or [])
    msg = (
        f"MONITOR-EVAL REPAIR: risk={risk.get('level')} score={risk.get('score')} "
        f"reasons={','.join(map(str, reasons)) or 'monitor_risk'}"
    )
    result = _handle_stuck_restart(msg, "monitor-eval-repair", 0.0)
    return {"active": True, "action": result.get("action"), "risk": risk.get("level"), "score": risk.get("score")}


def check_config_audit() -> list:
    """Detect pairs trading that should be disabled based on config."""
    # Read watchdog config for expected pairs
    wd = PROJECT / "scripts" / "watchdog_twin.sh"
    expected_pairs = set()
    if wd.exists():
        wd_text = wd.read_text()
        for line in wd_text.split("\n"):
            if "TE_SPOT_PAIR_2=" in line:
                val = line.split("=", 1)[1].strip().strip('"')
                if val: expected_pairs.add(val)
            if "TE_SPOT_PAIR_3=" in line:
                val = line.split("=", 1)[1].strip().strip('"')
                if val: expected_pairs.add(val)
            if "TE_SPOT_PAIR_4=" in line:
                val = line.split("=", 1)[1].strip().strip('"')
                if val: expected_pairs.add(val)
    
    # Always expect PEPE (pair 1)
    expected_pairs.add("PEPE/USDC")
    if "SHIB/USDC" not in expected_pairs:
        expected_pairs.add("SHIB/USDC")  # default pair2
    
    # Find actual pairs trading in last 6 hours
    rows = _q("""SELECT DISTINCT pair FROM fills 
    WHERE ts > datetime('now', '-6 hours') AND pair LIKE '%/%'""")
    actual_pairs = {r[0] for r in rows}
    
    # Ghost pairs: trading but not in config
    ghost = actual_pairs - expected_pairs
    # Missing pairs: in config but not trading
    missing = expected_pairs - actual_pairs
    
    alerts = []
    for p in ghost:
        alerts.append({"pair": p, "issue": "GHOST: trading but NOT in watchdog config"})
    for p in missing:
        alerts.append({"pair": p, "issue": "MISSING: in config but no fills for 6h"})
    
    return alerts


def save_state(metrics: dict) -> None:
    """Persist last state for trend detection."""
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        existing = {}
        if STATE.exists():
            existing = json.loads(STATE.read_text())
        existing["last"] = metrics
        existing["history"] = (existing.get("history", []) + [metrics])[-288:]  # 24h at 5min
        STATE.write_text(json.dumps(existing, indent=2, default=str))
    except Exception:
        pass


def main():
    log("══════ GUARDIAN SCAN ══════")
    all_alerts = []
    
    # 0. Stuck daemon check (BEFORE other checks — jika stuck, signal restart)
    stuck = check_daemon_stuck()
    if stuck.get("stuck"):
        all_alerts.append(f"🔴 STUCK: {stuck.get('action', 'unknown')}")
        # Jika baru signal restart, skip further checks (daemon akan restart)
        if "restart-signal" in stuck.get("action", ""):
            save_state({"ts": datetime.now(timezone.utc).isoformat(), "action": stuck["action"]})
            log(f"DONE: restart signal sent — skipping further checks, watchdog will restart daemon")
            sys.exit(0)

    # 0b. Monitor-eval repair plan (sensitive composite score → safe restart signal)
    mon_repair = check_monitor_eval_repair()
    if mon_repair.get("active"):
        all_alerts.append(f"🧪 MONITOR-EVAL REPAIR: {mon_repair.get('action')} risk={mon_repair.get('risk')}")
        if "restart-signal" in str(mon_repair.get("action")):
            save_state({"ts": datetime.now(timezone.utc).isoformat(), "action": mon_repair["action"]})
            log("DONE: monitor-eval repair signal handled — skipping further checks")
            sys.exit(0)
    
    # 1. Ratio check
    ratio = check_ratio()
    log(f"RATIO: 1:{ratio['ratio']:,.0f} | vol=${ratio['vol']:,.0f} | net_cost=${ratio['net_cost']:.2f} | {'✅' if ratio['ok'] else '⚠️' if ratio['warn'] else '🔴'}")
    if ratio["crit"]:
        all_alerts.append(f"🔴 RASIO KRITIS 1:{ratio['ratio']:,.0f} (target 1:{RATIO_TARGET:,})")
    elif ratio["warn"]:
        all_alerts.append(f"⚠️ RASIO 1:{ratio['ratio']:,.0f} — di bawah 1:{RATIO_WARN:,}")
    
    # Log per-pair PnL
    for pair, data in sorted(ratio["pairs"].items()):
        emoji = "✅" if data["pnl"] > 0 else "🔴" if data["pnl"] < -1 else "🟡"
        log(f"  {pair}: {data['rts']} RTs, PnL=${data['pnl']:.2f} {emoji}")
    
    # 2. Inventory drift
    drifts = check_inventory_drift()
    for d in drifts:
        if "alert" in d:
            log(f"DRIFT: {d['alert']}")
            continue
        level = "🔴" if d.get("crit") else "🟡"
        log(f"DRIFT: {d['pair']} DB={d['db_qty']:,.0f} vs EX={d['ex_qty']:,.0f} (${d['diff_usd']:.2f}) {level}")
        if d.get("crit"):
            all_alerts.append(f"{level} DRIFT {d['pair']}: ${d['diff_usd']:.2f} — DB≠Exchange!")
    
    # 3. OrderID=0 pattern
    oid0 = check_orderid0()
    if oid0["alert"]:
        pairs_str = ", ".join(oid0["pairs_affected"])
        log(f"OID0: {oid0['recent_count']} recent failures on {pairs_str}")
        all_alerts.append(f"⚠️ ORDERID=0: {oid0['recent_count']} failures — pairs: {pairs_str}")
    
    # 4. Per-pair health
    health = check_per_pair_health()
    for h in health:
        for issue in h["issues"]:
            log(f"HEALTH: {h['pair']} — {issue}")
            all_alerts.append(f"🔍 {h['pair']}: {issue}")
    
    # 5. Config audit
    config_issues = check_config_audit()
    for c in config_issues:
        log(f"CONFIG: {c['pair']} — {c['issue']}")
        all_alerts.append(f"⚙️ CONFIG: {c['pair']} — {c['issue']}")
    
    # Send consolidated alert if critical
    if all_alerts:
        msg = "\n".join(all_alerts[:5])  # max 5 alerts per message
        if len(all_alerts) > 5:
            msg += f"\n... +{len(all_alerts)-5} more"
        tg(msg)
    
    # Save state
    save_state({
        "ts": datetime.now(timezone.utc).isoformat(),
        "ratio": {k: v for k, v in ratio.items() if k != "pairs"},
        "drifts": len([d for d in drifts if "pair" in d]),
        "oid0": oid0.get("recent_count", 0),
        "health_issues": len(health),
        "config_issues": len(config_issues),
        "alerts": len(all_alerts)
    })
    
    log(f"DONE: {len(all_alerts)} alerts | ratio=1:{ratio['ratio']:,.0f} | drifts={len(drifts)} | oid0={oid0.get('recent_count',0)}")
    
    # SELALU exit 0 — systemd Type=oneshot compatibility.
    # Severity dikomunikasikan via log + Telegram, BUKAN exit code.
    # Exit code non-zero = systemd anggap FAILED → timer retry tapi service dianggap mati.
    sys.exit(0)


if __name__ == "__main__":
    main()
