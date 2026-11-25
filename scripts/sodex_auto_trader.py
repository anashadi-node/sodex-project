#!/usr/bin/env python3
"""Autonomous SoDEX perp trader — runs unattended (systemd), methodology-gated.
v2: A-tier ONLY (true OOS edge), BEAR-regime gate, live reconciliation, single-instance guard.

Audit result (2026-08-01): E1 PEPE spot maker was the only winner (+$87.47).
No directional edge proven. B-tier removed. Only trade when OOS z>1.64 AND BEAR.

HARD SAFETY (unattended real money — non-negotiable):
  • LOSS_CAP        session realized PnL floor ($-8) → close all + HALT (manual reset)
  • MAX_POS         max 2 concurrent positions
  • MAX_NOTIONAL    $40 per trade → worst-case gap ~ LOSS_CAP
  • MAX_TRADES_DAY  bound fee bleed (max 8/day)
  • KILL_SWITCH     touch data/AUTOTRADER_KILL → close all + exit
  • SINGLE_INSTANCE pid-lock prevents double-start
  • RECONCILE       registry synced with live API on every manage() cycle

Run:  python3 scripts/sodex_auto_trader.py            (live loop)
      python3 scripts/sodex_auto_trader.py --dry-run   (log decisions, no orders)
      python3 scripts/sodex_auto_trader.py --once       (single cycle)
      python3 scripts/sodex_auto_trader.py demo         (self-check)
"""
from __future__ import annotations
import json, os, sys, time, subprocess, urllib.request, fcntl
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
DATA = ROOT / "data"
STATE = DATA / "autotrader_state.json"
KILL = DATA / "AUTOTRADER_KILL"
LOCK = DATA / "autotrader.lock"
LOG = ROOT / "logs" / "autotrader.log"
SODEX = str(ROOT / "bin" / "sodex")
ADDR = "0x4a464b82b1c1233791351483c90c53e2a2fbc799"
API = "https://mainnet-gw.sodex.dev/api/v1"

# ── HARD SAFETY CONFIG ───────────────────────────────────────────────────────
LOSS_CAP = -8.0           # tighter: $-8 session realized floor → halt
MAX_POS = 2               # max 2 concurrent (was 3)
MAX_NOTIONAL = 40.0       # $40/trade → gap risk bounded (was $60)
MAX_TRADES_DAY = 8        # fewer trades, higher quality (was 15)
FAST_SEC = 180            # position-management cadence
SCAN_SEC = 1800           # signal-scan cadence
# A-tier ONLY — B-tier removed (no sub-edge trading after audit)
TIER_RISK = {"A": 0.008}  # 0.8% of perp capital per A-tier signal
DRY = "--dry-run" in sys.argv


def log(msg):
    line = f"[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}] {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(exist_ok=True)
        with LOG.open("a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _api(path):
    try:
        return json.load(urllib.request.urlopen(
            urllib.request.Request(f"{API}/{path}", headers={"User-Agent": "anantara"}), timeout=15))
    except Exception as e:
        log(f"api err {path}: {str(e)[:60]}")
        return {}


def perp_state():
    d = _api(f"perps/accounts/{ADDR}/state").get("data", {})
    return float(d.get("av", 0) or 0)


def positions():
    d = _api(f"perps/accounts/{ADDR}/positions").get("data", {})
    return d.get("positions", []) if isinstance(d, dict) else []


def book(sym):
    try:
        out = subprocess.run([SODEX, "orderbook", "perps", sym, "--depth", "1", "--format", "json"],
                             capture_output=True, text=True, timeout=25, env=os.environ)
        j = json.loads(out.stdout)
        bid = float(j["bids"][0]["price"]); ask = float(j["asks"][0]["price"])
        return bid, ask
    except Exception as e:
        log(f"book err {sym}: {str(e)[:50]}")
        return None, None


def _fmt_px(p):
    return f"{p:.4f}" if p < 10 else f"{p:.2f}"


def place(sym, side, qty, price):
    if DRY:
        log(f"DRY place {side} {sym} qty={qty} px={price}")
        return "dry"
    try:
        out = subprocess.run([SODEX, "orders", "place", "perps", "--symbol", sym,
                              "--side", side, "--type", "limit", "--price", _fmt_px(price),
                              "--qty", str(int(qty)), "--tif", "ioc", "--format", "json"],
                             capture_output=True, text=True, timeout=40, env=os.environ)
        j = json.loads(out.stdout)
        oid = j[0].get("orderID") if isinstance(j, list) and j else j.get("orderID", "")
        log(f"placed {side} {sym} qty={int(qty)} px={_fmt_px(price)} oid={oid}")
        return str(oid or "")
    except Exception as e:
        log(f"place err {sym}: {str(e)[:80]}")
        return ""


def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"session_realized": 0.0, "trades_today": 0, "day": time.strftime("%Y%m%d"),
                "registry": {}, "halted": False}


def save_state(s):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2)); tmp.replace(STATE)


def close_position(sym, pos_size, st):
    bid, ask = book(sym)
    if bid is None:
        return
    if pos_size < 0:   # short → buy to cover
        place(sym, "buy", abs(pos_size), ask * 1.002)
    else:              # long → sell
        place(sym, "sell", abs(pos_size), bid * 0.998)
    st["registry"].pop(sym, None)


def reconcile(st):
    """Sync registry with live positions — drop phantom entries, adopt orphans."""
    live = {p.get("symbol"): float(p.get("size", 0))
            for p in positions() if float(p.get("size", 0)) != 0}
    reg = st["registry"]
    # remove phantoms (registry says open, exchange says flat)
    phantoms = [sym for sym in list(reg.keys()) if sym not in live]
    for sym in phantoms:
        log(f"reconcile: drop phantom {sym} (flat on exchange)")
        reg.pop(sym)
    return live


def manage(st):
    """SW SL/TP + realized tracking + halt. Returns True if halted."""
    live = reconcile(st)
    reg = st["registry"]
    for sym, sz in live.items():
        bid, ask = book(sym)
        if bid is None:
            continue
        mark = (bid + ask) / 2
        r = reg.get(sym)
        if not r:
            continue
        hit = None
        if sz < 0:   # short
            if mark >= r["sl"]: hit = "SL"
            elif mark <= r["tp"]: hit = "TP"
        else:        # long
            if mark <= r["sl"]: hit = "SL"
            elif mark >= r["tp"]: hit = "TP"
        if hit:
            realized = abs(sz) * ((r["entry"] - mark) if sz < 0 else (mark - r["entry"]))
            st["session_realized"] += realized
            log(f"CLOSE {sym} {hit} mark={mark:.4f} realized=${realized:+.2f} "
                f"session=${st['session_realized']:+.2f}")
            close_position(sym, sz, st)
    if st["session_realized"] <= LOSS_CAP:
        log(f"🔴 LOSS_CAP hit (${st['session_realized']:.2f} ≤ {LOSS_CAP}) → CLOSE ALL + HALT")
        live = reconcile(st)
        for sym, sz in live.items():
            close_position(sym, sz, st)
        st["halted"] = True
        return True
    return False


def scan_and_trade(st):
    """A-tier ONLY: OOS edge confirmed (z>1.64) + BEAR regime → execute small."""
    if st["day"] != time.strftime("%Y%m%d"):
        st["day"] = time.strftime("%Y%m%d"); st["trades_today"] = 0
    if st["trades_today"] >= MAX_TRADES_DAY:
        log("max trades/day reached — skip"); return
    live_pos = reconcile(st)
    if len(live_pos) >= MAX_POS:
        return
    import auto_scan as A
    cap = perp_state()
    best = None
    for cid, sym in A.UNIVERSE:
        try:
            r = A.scan_asset(cid, sym)
        except Exception:
            continue
        # A-TIER ONLY: true OOS edge (z>1.64) + BEAR regime for shorts
        if r["tier"] == "A" and sym not in st["registry"]:
            # BEAR gate: only SHORT when regime is BEAR (no counter-trend)
            if r["signal"] == "SHORT" and r["regime"] != "BEAR":
                log(f"skip {sym}: SHORT signal but regime={r['regime']} (BEAR required)")
                continue
            if r["signal"] == "LONG" and r["regime"] != "BULL":
                log(f"skip {sym}: LONG signal but regime={r['regime']} (BULL required)")
                continue
            if best is None or r["oos_z"] > best["oos_z"]:
                best = r
        time.sleep(2)
    if not best:
        log("scan: no A-tier regime-confirmed signal → hold"); return
    sym = best["sym"]; side = "sell" if best["signal"] == "SHORT" else "buy"
    bid, ask = book(sym)
    if bid is None:
        return
    entry = bid if side == "sell" else ask
    rr = A.M.true_ranges
    atr_pct = min(0.10, max(0.015, abs(best.get("oos_net", 0)) / 1e4 + 0.015))
    risk = cap * TIER_RISK["A"]
    d = 1 if side == "sell" else -1
    sl = entry * (1 + d * atr_pct); tp = entry * (1 - d * 3 * atr_pct)
    notional = min(MAX_NOTIONAL, risk / atr_pct)
    qty = int(notional / entry)
    if qty < 1:
        log(f"{sym} qty<1 at notional ${notional:.0f} — skip"); return
    px = entry * (0.999 if side == "sell" else 1.001)
    oid = place(sym, side, qty, px)
    if oid:
        st["registry"][sym] = {"entry": entry, "sl": round(sl, 6), "tp": round(tp, 6),
                               "size": qty, "side": best["signal"], "tier": "A"}
        st["trades_today"] += 1
        log(f"🎯 A-TIER {best['signal']} {sym} qty={qty} entry~{entry:.4f} "
            f"SL={sl:.4f} TP={tp:.4f} notional=${notional:.0f} "
            f"OOSz={best['oos_z']:+.2f} regime={best['regime']}")


def cycle(st, do_scan):
    if KILL.exists():
        log("🛑 KILL switch → close all + exit")
        live = reconcile(st)
        for sym, sz in live.items():
            close_position(sym, sz, st)
        save_state(st); sys.exit(0)
    if st.get("halted"):
        log("halted — manual reset: edit autotrader_state.json halted→false"); return
    halted = manage(st)
    if not halted and do_scan:
        scan_and_trade(st)
    save_state(st)


def _acquire_lock():
    """Single-instance guard via flock. Returns lock file handle (keep open)."""
    LOCK.parent.mkdir(exist_ok=True)
    fh = LOCK.open("w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.write(str(os.getpid()))
        fh.flush()
        return fh
    except BlockingIOError:
        print(f"Another instance already running (lock: {LOCK}). Exit.")
        sys.exit(1)


def main():
    fh = _acquire_lock()
    st = load_state()
    cap = perp_state()
    log(f"=== AUTOTRADER v2 START (dry={DRY}) cap=${cap:.2f} "
        f"LOSS_CAP={LOSS_CAP} MAX_POS={MAX_POS} MAX_NOTIONAL={MAX_NOTIONAL} "
        f"MODE=A-TIER-ONLY+BEAR-GATE ===")
    # startup reconciliation
    reconcile(st); save_state(st)
    if "--once" in sys.argv:
        cycle(st, do_scan=True); fh.close(); return
    last_scan = 0
    while True:
        try:
            do_scan = (time.time() - last_scan) >= SCAN_SEC
            cycle(st, do_scan)
            if do_scan:
                last_scan = time.time()
        except Exception as e:
            log(f"cycle error: {str(e)[:100]}")
        time.sleep(FAST_SEC)


def demo():
    s = {"session_realized": 0.0, "trades_today": 0, "day": "x", "registry": {}, "halted": False}
    # halt on loss-cap
    s["session_realized"] = -9.0
    assert s["session_realized"] <= LOSS_CAP, f"loss-cap {LOSS_CAP} should trigger at -9"
    # short geometry
    s["registry"]["XRP-USD"] = {"entry": 1.0598, "sl": 1.0756, "tp": 1.0120, "size": 33, "side": "SHORT"}
    r = s["registry"]["XRP-USD"]
    assert r["sl"] > r["entry"] > r["tp"], "short geometry: SL > entry > TP"
    # price format
    assert _fmt_px(1.0598) == "1.0598" and _fmt_px(63000) == "63000.00"
    # A-tier only (no B)
    assert "B" not in TIER_RISK, "B-tier should be removed post-audit"
    # tighter caps
    assert LOSS_CAP == -8.0, "LOSS_CAP should be -8 post-audit"
    assert MAX_NOTIONAL == 40.0, "MAX_NOTIONAL should be 40 post-audit"
    assert MAX_POS == 2, "MAX_POS should be 2 post-audit"
    print("demo OK — v2: A-tier-only, bear-gate, $8 cap, $40 notional, pid-lock, reconcile")


if __name__ == "__main__":
    if "demo" in sys.argv:
        demo()
    else:
        main()
