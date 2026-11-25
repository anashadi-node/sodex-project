#!/usr/bin/env python3
"""HYPE-USD perp maker — post GTX BUY+SELL at best bid/ask, capture spread + maker rebate.

Economics (HYPE-USD, 16.6bps spread, $40 notional):
  TP per RT : spread($0.066) + 2×rebate($0.010) = +$0.076
  SL (33bps): -$0.132 gross - $0.016 taker fee  = -$0.148
  Break-even fill rate: 66% (mean-reverting assumption)
  Expected: ~27 RT/day → ~$2/day on $40 notional.

State machine (no position or resting order confusion):
  IDLE     → post GTX BUY@bid + SELL@ask              → QUOTING
  QUOTING  → SELL filled                               → SHORT  (BUY is now the close order)
  QUOTING  → BUY  filled                               → LONG   (SELL is now the close order)
  QUOTING  → mid drift > REPRICE_BPS                  → IDLE   (cancel both, reprice)
  SHORT    → BUY close fills                           → IDLE   (RT complete ✓)
  SHORT    → mark ≥ entry×(1+SL_BPS)                  → IDLE   (taker close, log loss)
  LONG     → SELL close fills                          → IDLE   (RT complete ✓)
  LONG     → mark ≤ entry×(1−SL_BPS)                  → IDLE   (taker close, log loss)
  ANY      → session_pnl + upnl ≤ LOSS_CAP            → HALTED (cancel all, close pos)

Restart is safe: on startup we reconcile position + open orders from exchange.

Run:  python3 scripts/sodex_hype_maker.py            (live)
      python3 scripts/sodex_hype_maker.py --dry       (no orders, log decisions)
      python3 scripts/sodex_hype_maker.py demo        (self-check, no network)
"""
from __future__ import annotations
import json, os, sys, time, subprocess, urllib.request, fcntl
from pathlib import Path

ROOT  = Path(__file__).resolve().parent.parent
DATA  = ROOT / "data"
LOG   = ROOT / "logs" / "hype_maker.log"
LOCK  = DATA / "hype_maker.lock"
KILL  = DATA / "HYPEMAKER_KILL"
SODEX = str(ROOT / "bin" / "sodex")
ADDR  = "0x4a464b82b1c1233791351483c90c53e2a2fbc799"
API   = "https://mainnet-gw.sodex.dev/api/v1"

# ── MARKET SPEC (HYPE-USD, id=12) ────────────────────────────────────────────
SYMBOL   = "HYPE-USD"
SYM_ID   = 12      # required for cancel
PX_PREC  = 3       # tickSize=0.001
QTY_PREC = 2       # stepSize=0.01
MIN_QTY  = 0.01

# ── RISK / STRATEGY CONFIG ────────────────────────────────────────────────────
NOTIONAL    = 40.0    # USD per side
LOSS_CAP    = -12.0   # session halt floor (realized + unrealized)
SL_BPS      = 33.0    # adverse move before taker-close (≈ 2× spread)
REPRICE_BPS = 8.0     # reprice threshold (mid drift since last quote)
POLL_SEC    = 30      # loop cadence

DRY = "--dry" in sys.argv


# ── UTILS ─────────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    ts   = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(exist_ok=True)
        with LOG.open("a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _api(path: str) -> dict:
    try:
        req = urllib.request.Request(f"{API}/{path}", headers={"User-Agent": "anantara"})
        return json.load(urllib.request.urlopen(req, timeout=15))
    except Exception as e:
        log(f"api err {path}: {str(e)[:60]}")
        return {}


def _cmd(*args: str) -> tuple[str, str]:
    try:
        r = subprocess.run(list(args), capture_output=True, text=True, timeout=30, env=os.environ)
        return r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return "", str(e)


# ── EXCHANGE QUERIES ──────────────────────────────────────────────────────────

def book() -> tuple[float | None, float | None]:
    out, _ = _cmd(SODEX, "orderbook", "perps", SYMBOL, "--depth", "1", "--format", "json")
    try:
        j = json.loads(out)
        return float(j["bids"][0]["price"]), float(j["asks"][0]["price"])
    except Exception:
        return None, None


def open_orders_hype() -> dict[str, dict]:
    """Return {str(orderID): order} for open HYPE-USD orders only."""
    d = _api(f"perps/accounts/{ADDR}/orders").get("data", {})
    return {str(o.get("orderID", "")): o
            for o in (d.get("orders") or []) if o.get("symbol") == SYMBOL}


def position() -> dict | None:
    """Live HYPE-USD position dict or None if flat."""
    d = _api(f"perps/accounts/{ADDR}/positions").get("data", {})
    for p in d.get("positions", []):
        if p.get("symbol") == SYMBOL:
            sz = float(p.get("size", 0) or 0)
            if sz != 0:
                return {
                    "size":  sz,
                    "entry": float(p.get("avgEntryPrice", 0) or 0),
                    "upnl":  float(p.get("unrealizedPnl", 0) or 0),
                    "mark":  float(p.get("markPrice", 0) or 0),
                }
    return None


def perp_avail() -> float:
    d = _api(f"perps/accounts/{ADDR}/state").get("data", {})
    return float(d.get("av", 0) or 0)


# ── ORDER ACTIONS ─────────────────────────────────────────────────────────────

def place_gtx(side: str, price: float, qty: float) -> str:
    """Post GTX limit order. Returns oid string or ''."""
    px_s = f"{price:.{PX_PREC}f}"
    q_s  = f"{qty:.{QTY_PREC}f}"
    if DRY:
        log(f"DRY gtx-{side} qty={q_s} px={px_s}")
        return "dry"
    out, err = _cmd(SODEX, "orders", "place", "perps",
                    "--symbol", SYMBOL, "--side", side,
                    "--type", "limit", "--price", px_s, "--qty", q_s,
                    "--tif", "gtx", "--format", "json")
    try:
        j   = json.loads(out)
        oid = str(j[0].get("orderID") if isinstance(j, list) and j else j.get("orderID", ""))
        log(f"gtx-{side} qty={q_s} px={px_s} oid={oid}")
        return oid
    except Exception as e:
        log(f"place err {side}: {e!s:.60} | out={out[:80]} | err={err[:60]}")
        return ""


def cancel_order(oid: str) -> None:
    if DRY or not oid or oid == "dry":
        log(f"DRY cancel oid={oid}"); return
    out, _ = _cmd(SODEX, "orders", "cancel", "perps",
                  "--symbol-id", str(SYM_ID), "--order-id", oid, "--format", "json")
    log(f"cancel oid={oid} | {out[:60]}")


def taker_close(size: float, mark: float) -> None:
    """Close position immediately via IOC taker."""
    side = "buy" if size < 0 else "sell"
    qty  = abs(size)
    px   = mark * (1.005 if side == "buy" else 0.995)
    px_s = f"{px:.{PX_PREC}f}"
    q_s  = f"{qty:.{QTY_PREC}f}"
    if DRY:
        log(f"DRY taker-close {side} qty={q_s} px={px_s}"); return
    out, _ = _cmd(SODEX, "orders", "place", "perps",
                  "--symbol", SYMBOL, "--side", side,
                  "--type", "limit", "--price", px_s, "--qty", q_s,
                  "--tif", "ioc", "--format", "json")
    log(f"taker-close {side} qty={q_s} px={px_s} | {out[:80]}")


# ── STATE ─────────────────────────────────────────────────────────────────────

def make_state() -> dict:
    return {
        "phase":       "IDLE",   # IDLE | QUOTING | SHORT | LONG
        "buy_oid":     "",
        "sell_oid":    "",
        "entry":       0.0,
        "qty":         0.0,
        "mid0":        0.0,      # mid when quotes posted (for reprice check)
        "session_pnl": 0.0,
        "rt_count":    0,
        "sl_count":    0,
        "halted":      False,
    }


# ── MAIN LOOP ─────────────────────────────────────────────────────────────────

def loop(st: dict) -> None:
    # kill switch
    if KILL.exists():
        log("🛑 KILL switch → close + exit")
        p = position()
        if p:
            taker_close(p["size"], p["mark"])
        sys.exit(0)

    if st["halted"]:
        log("HALTED — rm data/HYPEMAKER_KILL is not needed here; "
            "edit hype_maker.lock or restart with clean state to resume"); return

    # ── Market snapshot ───────────────────────────────────────────────────────
    bid, ask = book()
    if bid is None:
        log("book unavailable — skip"); return
    mid          = (bid + ask) / 2
    spread_bps   = (ask - bid) / mid * 10000

    # ── Live position (needed for halt check and SHORT/LONG handlers) ─────────
    pos = position()
    upnl = pos["upnl"] if pos else 0.0

    # ── Halt check (every cycle) ──────────────────────────────────────────────
    if st["session_pnl"] + upnl <= LOSS_CAP:
        log(f"🔴 LOSS_CAP: session={st['session_pnl']:+.4f} upnl={upnl:+.4f} "
            f"total={st['session_pnl']+upnl:+.4f} ≤ {LOSS_CAP} → close all + HALT")
        for oid in (st["buy_oid"], st["sell_oid"]):
            cancel_order(oid)
        if pos:
            taker_close(pos["size"], pos["mark"])
        st["halted"] = True
        return

    # ── IDLE: post fresh maker quotes ─────────────────────────────────────────
    if st["phase"] == "IDLE":
        qty = round(NOTIONAL / mid, QTY_PREC)
        if qty < MIN_QTY:
            log(f"qty {qty} < min {MIN_QTY} — price too high"); return
        log(f"IDLE→QUOTING spread={spread_bps:.1f}bps "
            f"bid={bid:.3f} ask={ask:.3f} qty={qty}")
        b_oid = place_gtx("buy",  bid, qty)
        s_oid = place_gtx("sell", ask, qty)
        if b_oid and s_oid:
            st.update(phase="QUOTING", buy_oid=b_oid, sell_oid=s_oid,
                      qty=qty, mid0=mid)
        else:
            # partial — cancel survivor, stay IDLE
            if b_oid and b_oid != "dry": cancel_order(b_oid)
            if s_oid and s_oid != "dry": cancel_order(s_oid)
        return

    # ── QUOTING: monitor fills + reprice ─────────────────────────────────────
    if st["phase"] == "QUOTING":
        # reprice if mid has drifted
        drift_bps = abs(mid - st["mid0"]) / st["mid0"] * 10000
        if drift_bps > REPRICE_BPS:
            log(f"REPRICE: mid drift {drift_bps:.1f}bps > {REPRICE_BPS} — cancel + repost")
            cancel_order(st["buy_oid"])
            cancel_order(st["sell_oid"])
            st["phase"] = "IDLE"
            return

        live = open_orders_hype()  # oid → order
        buy_live  = st["buy_oid"]  in live or DRY
        sell_live = st["sell_oid"] in live or DRY

        if not sell_live and buy_live:
            # SELL filled → SHORT; BUY is now the close order
            entry_px = pos["entry"] if pos else ask
            log(f"SELL FILLED → SHORT  entry≈{entry_px:.3f}  BUY close oid={st['buy_oid']}")
            st.update(phase="SHORT", entry=entry_px)
        elif not buy_live and sell_live:
            # BUY filled → LONG; SELL is now the close order
            entry_px = pos["entry"] if pos else bid
            log(f"BUY FILLED → LONG  entry≈{entry_px:.3f}  SELL close oid={st['sell_oid']}")
            st.update(phase="LONG", entry=entry_px)
        elif not buy_live and not sell_live:
            # both filled simultaneously (rare) — flat, count as RT
            gross = (ask - bid) * st["qty"]
            st["session_pnl"] += gross
            st["rt_count"] += 1
            log(f"BOTH FILLED (simultaneous RT) est_gross=+${gross:.4f} "
                f"rt={st['rt_count']} session={st['session_pnl']:+.4f}")
            st["phase"] = "IDLE"; st["buy_oid"] = ""; st["sell_oid"] = ""
        # else: both still resting — nothing to do
        return

    # ── SHORT: wait for BUY close, or SL ─────────────────────────────────────
    if st["phase"] == "SHORT":
        sl_px = st["entry"] * (1 + SL_BPS / 10000)
        if pos is None:
            # BUY close filled → RT complete
            pnl = (st["entry"] - mid) * st["qty"]
            st["session_pnl"] += pnl
            st["rt_count"] += 1
            log(f"RT DONE (SHORT) entry={st['entry']:.3f} close≈{mid:.3f} "
                f"pnl_est=${pnl:+.4f}  session=${st['session_pnl']:+.4f}  rt={st['rt_count']}")
            st["phase"] = "IDLE"; st["buy_oid"] = ""; st["sell_oid"] = ""
        elif mid >= sl_px:
            log(f"🔴 SL SHORT: mark {mid:.3f} ≥ sl {sl_px:.3f}")
            cancel_order(st["buy_oid"])
            taker_close(pos["size"], mid)
            fee_est = (4 / 10000) * abs(pos["size"]) * mid
            pnl = (st["entry"] - mid) * abs(pos["size"]) - fee_est
            st["session_pnl"] += pnl; st["sl_count"] += 1
            log(f"SL CLOSED  pnl_est=${pnl:+.4f}  session=${st['session_pnl']:+.4f}  sl={st['sl_count']}")
            st["phase"] = "IDLE"; st["buy_oid"] = ""; st["sell_oid"] = ""
        return

    # ── LONG: wait for SELL close, or SL ─────────────────────────────────────
    if st["phase"] == "LONG":
        sl_px = st["entry"] * (1 - SL_BPS / 10000)
        if pos is None:
            # SELL close filled → RT complete
            pnl = (mid - st["entry"]) * st["qty"]
            st["session_pnl"] += pnl
            st["rt_count"] += 1
            log(f"RT DONE (LONG) entry={st['entry']:.3f} close≈{mid:.3f} "
                f"pnl_est=${pnl:+.4f}  session=${st['session_pnl']:+.4f}  rt={st['rt_count']}")
            st["phase"] = "IDLE"; st["buy_oid"] = ""; st["sell_oid"] = ""
        elif mid <= sl_px:
            log(f"🔴 SL LONG: mark {mid:.3f} ≤ sl {sl_px:.3f}")
            cancel_order(st["sell_oid"])
            taker_close(pos["size"], mid)
            fee_est = (4 / 10000) * abs(pos["size"]) * mid
            pnl = (mid - st["entry"]) * abs(pos["size"]) - fee_est
            st["session_pnl"] += pnl; st["sl_count"] += 1
            log(f"SL CLOSED  pnl_est=${pnl:+.4f}  session=${st['session_pnl']:+.4f}  sl={st['sl_count']}")
            st["phase"] = "IDLE"; st["buy_oid"] = ""; st["sell_oid"] = ""
        return

    log(f"unknown phase {st['phase']!r} — reset to IDLE")
    st["phase"] = "IDLE"


def _acquire_lock() -> object:
    LOCK.parent.mkdir(exist_ok=True)
    fh = LOCK.open("w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.write(str(os.getpid())); fh.flush()
        return fh
    except BlockingIOError:
        print(f"Already running (lock: {LOCK}). Exit."); sys.exit(1)


def main() -> None:
    fh = _acquire_lock()  # noqa: F841  (keep open for flock duration)
    st = make_state()

    # ── Startup reconciliation ────────────────────────────────────────────────
    pos = position()
    if pos:
        phase = "SHORT" if pos["size"] < 0 else "LONG"
        st.update(phase=phase, entry=pos["entry"], qty=abs(pos["size"]))
        log(f"startup: resume {phase} sz={pos['size']} entry={pos['entry']:.3f}")
        # adopt any resting orders
        for o in open_orders_hype().values():
            oid = str(o.get("orderID", ""))
            if o.get("side") == "buy":
                st["buy_oid"] = oid
            else:
                st["sell_oid"] = oid
        log(f"  adopted buy_oid={st['buy_oid']}  sell_oid={st['sell_oid']}")

    log(f"=== HYPE MAKER START (dry={DRY}) avail=${perp_avail():.2f} "
        f"NOTIONAL=${NOTIONAL} SL={SL_BPS}bps REPRICE={REPRICE_BPS}bps "
        f"LOSS_CAP=${LOSS_CAP} ===")

    while True:
        try:
            loop(st)
        except Exception as e:
            log(f"loop err: {str(e)[:120]}")
        time.sleep(POLL_SEC)


def demo() -> None:
    """Self-check: geometry, state, config — no network."""
    st = make_state()
    # state defaults
    assert st["phase"] == "IDLE"
    assert st["session_pnl"] == 0.0
    assert st["halted"] is False
    # SL geometry SHORT
    entry = 52.49
    sl = entry * (1 + SL_BPS / 10000)
    assert abs(sl - entry * 1.0033) < 0.001, f"SHORT sl wrong: {sl}"
    # SL geometry LONG
    entry = 52.58
    sl = entry * (1 - SL_BPS / 10000)
    assert abs(sl - entry * 0.9967) < 0.001, f"LONG sl wrong: {sl}"
    # qty calc
    qty = round(NOTIONAL / 52.50, QTY_PREC)
    assert qty >= MIN_QTY
    assert qty <= 2.0, f"qty {qty} unexpectedly large"
    # price format
    assert f"{52.49:.{PX_PREC}f}" == "52.490"
    assert f"{1.234:.{PX_PREC}f}" == "1.234"
    # risk config
    assert LOSS_CAP == -12.0
    assert NOTIONAL == 40.0
    assert SL_BPS   == 33.0
    assert REPRICE_BPS == 8.0
    assert SYM_ID == 12, "symbol-id needed for cancel"
    # RT estimate (sanity)
    spread = 0.087   # $  (16.6bps on $52.5)
    rt_val = spread * qty + 2 * (1.2 / 10000) * qty * 52.50
    assert rt_val > 0.05, f"RT value too low: {rt_val:.4f}"
    print(f"demo OK — HYPE maker: qty≈{qty} RT_val≈${rt_val:.4f} "
          f"SL={SL_BPS}bps REPRICE={REPRICE_BPS}bps NOTIONAL=${NOTIONAL} "
          f"LOSS_CAP=${LOSS_CAP} SYM_ID={SYM_ID}")


if __name__ == "__main__":
    if "demo" in sys.argv:
        demo()
    else:
        main()
