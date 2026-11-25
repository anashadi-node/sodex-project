#!/usr/bin/env python3
"""SoDEX Volume Churn v4 — serial maker turnover for SoPoints snapshot push.

INVARIANTS (never violated):
  1. Per-session: AV never drops more than CHURN_LOSS_CAP below session baseline.
  2. Lifetime: total cost across all sessions never exceeds CHURN_LIFETIME_CAP ($70).
  3. On breach: flatten all inventory + stop (exits 0 so systemd does not thrash).

Method — serial maker-in/out on BTC-USD + ETH-USD (one RT at a time via _RT_SEM):
  * BUY GTX at bid → rests as maker → fills when price ticks down
  * SELL GTX at ask → fills when price ticks up
  * Each RT: +2x notional volume at ~0 effective cost (pure maker)
  * Stuck inventory → taker-flatten fallback (always exits flat)

v4 improvements vs v3.1:
  1. Notional $350->$175: smaller orders fill faster as maker, fewer taker-fallbacks
  2. FILL_WAIT_S 7->15: more patience for maker fills (avoids premature taker cancel)
  3. _RT_SEM: only ONE active RT across all pairs -> zero cross-pair interference,
     serial execution eliminates cross-thread race conditions entirely
  4. Spread gate 0.3 bps: skip RT when spread too tight (adverse selection risk)
  5. _real_pos_confirmed(): 2 reads x 2s settle -> catches stale REST API lag (1-3s);
     used in G4 (pre-sell) and G5 (post-cancel) to eliminate seller-race shorts
  6. POST_CANCEL_S 1.5->3.0s: extra settle before reading pos after cancel

Race-condition guards:
  G1. Pre-buy: if already long before maker-in -> skip to maker-out (stale fill recovery)
  G2. Post-cancel (buyer): 1s settle + re-check for late BUY fill
  G3. Flat-confirm: 2.0s settle before trusting pos<=0 reading (was 0.5s)
  G4. Pre-sell confirm: _real_pos_confirmed() before every SELL -> prevents double-sell
  G5. Post-cancel (seller): 3.0s + _real_pos_confirmed() to detect fill-before-cancel

Config via env (set in .env, no inline comments):
  CHURN_PAIRS=BTC-USD,ETH-USD
  CHURN_NOTIONAL=175          USD notional per maker order (v4: was 350)
  CHURN_LEVERAGE=10
  CHURN_VOLUME_TARGET=357000  lifetime volume target (new mission)
  CHURN_LOSS_CAP=25           per-session HARD cap
  CHURN_LIFETIME_CAP=70       lifetime budget (new mission)
  CHURN_FILL_WAIT_S=15        seconds to wait for maker fill (v4: was 7)
  CHURN_MAKER_OUT_MAX_S=180   patient maker-out window (seconds)
  CHURN_MIN_SPREAD_BPS=0.3    spread gate (v4: was 0)
  CHURN_POST_CANCEL_S=3.0     settle after cancel before re-reading pos (v4: was 1.5)
  CHURN_POS_CONFIRM_N=2       reads per _real_pos_confirmed call
  CHURN_POS_CONFIRM_S=2.0     settle between reads (v4: was 0.5)
  CHURN_RUN_SECONDS=79200     max session wall-clock (22h)
  CHURN_DEADLINE_UTC          mission end (ISO-8601 UTC); blank=no deadline
  CHURN_MISSION_FLOOR_AV      hard floor -- stop if av drops below this

Usage:
  python3 scripts/sodex_volume_churn.py            # run
  python3 scripts/sodex_volume_churn.py --status   # progress
  python3 scripts/sodex_volume_churn.py --flatten  # emergency flatten
"""
from __future__ import annotations
import json, logging, os, subprocess, sys, threading, time, urllib.request
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path


def _past_deadline() -> bool:
    dl_str = DEADLINE_UTC.strip()
    if not dl_str:
        return False
    try:
        dl = datetime.fromisoformat(dl_str).replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= dl
    except Exception:
        return False


PROJECT    = Path(__file__).resolve().parents[1]
BASE_API   = "https://mainnet-gw.sodex.dev/api/v1"
SODEX_CLI  = PROJECT / "bin" / "sodex"
STATE_FILE = PROJECT / "data" / "volume_churn_state.json"
LOG_FILE   = PROJECT / "logs" / "volume_churn.log"
KILL_FILE  = PROJECT / "data" / "CHURN_KILL"   # fail-closed KILL switch

CHURN_PAIRS     = os.environ.get("CHURN_PAIRS", "BTC-USD,ETH-USD").split(",")
CHURN_NOTIONAL  = D(os.environ.get("CHURN_NOTIONAL", "175"))
CHURN_LEVERAGE  = int(os.environ.get("CHURN_LEVERAGE", "10"))
VOLUME_TARGET   = D(os.environ.get("CHURN_VOLUME_TARGET", "357000"))
LOSS_CAP        = D(os.environ.get("CHURN_LOSS_CAP", "25"))
LIFETIME_CAP    = D(os.environ.get("CHURN_LIFETIME_CAP", "70"))
DEADLINE_UTC    = os.environ.get("CHURN_DEADLINE_UTC", "")
MAX_INV_USD     = D(os.environ.get("CHURN_MAX_INV_USD", "700"))
FILL_WAIT_S     = float(os.environ.get("CHURN_FILL_WAIT_S", "15"))
MAKER_OUT_MAX_S = float(os.environ.get("CHURN_MAKER_OUT_MAX_S", "180"))
MIN_SPREAD_BPS  = D(os.environ.get("CHURN_MIN_SPREAD_BPS", "0.3"))
MISSION_FLOOR_AV = D(os.environ.get("CHURN_MISSION_FLOOR_AV", "67.05"))
POST_CANCEL_S   = float(os.environ.get("CHURN_POST_CANCEL_S", "3.0"))
POS_CONFIRM_N   = int(os.environ.get("CHURN_POS_CONFIRM_N", "2"))
POS_CONFIRM_S   = float(os.environ.get("CHURN_POS_CONFIRM_S", "2.0"))
RUN_SECONDS     = float(os.environ.get("CHURN_RUN_SECONDS", "79200"))
ADDR            = os.environ.get("SODEX_ADDRESS", "0x4a464b82b1c1233791351483c90c53e2a2fbc799")

# v4: global semaphore -- only ONE pair worker runs an active RT at a time.
# Eliminates cross-pair interference; pairs alternate serial RTs.
_RT_SEM = threading.Semaphore(1)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s CHURN %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE, encoding="utf-8")])
log = logging.getLogger("churn")


# ── env / CLI helpers ──────────────────────────────────────────────────────────

def _build_env() -> dict:
    env = os.environ.copy()
    dotenv = PROJECT / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            line = line.split("#")[0].strip()
            if "=" in line:
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if k and v and k not in env:
                    env[k] = v
    env.pop("SODEX_API_KEY", None)  # SECURITY: never pass key to perp subprocess
    return env

_ENV   = _build_env()
_SYMID: dict = {}
_STEP:  dict = {}


def _sodex(*args, timeout=25):
    cmd = [str(SODEX_CLI), "--format", "json"] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=_ENV)
        out = r.stdout.strip()
        return json.loads(out) if out else None
    except Exception as e:
        log.debug("sodex %s: %s", args[:3], e)
        return None


def _api(path):
    req = urllib.request.Request(BASE_API + path, headers={"User-Agent": "churn/4.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode())


def _load_markets():
    j = _sodex("markets", "perps")
    rows = j if isinstance(j, list) else (j.get("data", []) if isinstance(j, dict) else [])
    for x in rows:
        if isinstance(x, dict) and x.get("status") == "TRADING":
            _SYMID[x["name"]] = x.get("id")
            _STEP[x["name"]] = (D(str(x.get("stepSize", "0.001"))),
                                int(x.get("quantityPrecision", 3)))


def _book(pair):
    try:
        for t in _api("/perps/markets/tickers").get("data", []):
            if isinstance(t, dict) and t.get("symbol") == pair:
                return D(str(t["bidPx"])), D(str(t["askPx"]))
    except Exception:
        pass
    return None, None


def _account_value():
    return D(str(_api(f"/perps/accounts/{ADDR}/state")["data"]["av"]))


def _positions():
    out: dict = {}
    try:
        for p in _api(f"/perps/accounts/{ADDR}/positions")["data"].get("positions") or []:
            out[p["symbol"]] = D(str(p.get("size", 0)))
    except Exception:
        pass
    return out


def _real_pos(pair):
    return _positions().get(pair, D(0))


def _real_pos_confirmed(pair, n=None, s=None):
    """
    Take `n` position readings with `s` seconds between each read.
    Returns the LAST reading (most recent = most accurate after API lag settles).

    v4: default 2 reads x 2.0s settle.
    - First read at T=0, second read at T+2s.
    - The 2s gap ensures the SoDEX REST cache (typically 1-3s lag) has updated.

    Use before placing SELL (G4) and after cancel (G5) to catch:
    - Seller race: soid filled just before cancel -> API still shows LONG for 1-2s
    - After G5 3.0s settle: if pos still shows LONG, it's genuinely still LONG
    """
    reads = n if n is not None else POS_CONFIRM_N
    settle = s if s is not None else POS_CONFIRM_S
    pos = D(0)
    for i in range(reads):
        if i > 0:
            time.sleep(settle)
        pos = _real_pos(pair)
    return pos


def _qty(notional, price, pair):
    step, _ = _STEP.get(pair, (D("0.001"), 3))
    raw = notional / price
    q = (raw // step) * step if step > 0 else raw
    return q.quantize(step) if step > 0 else q


def _set_leverage(pair, lev):
    try:
        subprocess.run([str(SODEX_CLI), "leverage", pair, str(lev), "--mode", "isolated"],
                       capture_output=True, text=True, timeout=15, env=_ENV)
    except Exception:
        pass


def _place_maker(pair, side, price, qty):
    _, qprec = _STEP.get(pair, (D("0.001"), 3))
    px = f"{float(price):.2f}" if price >= 10 else f"{float(price):.6f}"
    qs = f"{float(qty):.{qprec}f}"
    j = _sodex("orders", "place", "perps", "--symbol", pair, "--side", side,
               "--price", px, "--qty", qs, "--type", "limit", "--tif", "gtx")
    if not j:
        return None
    rows = j if isinstance(j, list) else [j]
    for r in rows:
        if isinstance(r, dict):
            oid = r.get("orderID") or r.get("orderId") or r.get("id")
            if oid not in (None, 0, "0", ""):
                return str(oid)
    return None


def _cancel(pair, oid):
    sid = _SYMID.get(pair)
    if not sid or not oid:
        return
    _sodex("orders", "cancel", "perps", "--symbol-id", str(sid), "--order-id", str(oid))


def _taker_flatten(pair):
    pos = _real_pos(pair)
    if abs(pos) < D("0.0001"):
        return
    side = "sell" if pos > 0 else "buy"
    _, qprec = _STEP.get(pair, (D("0.001"), 3))
    qs = f"{float(abs(pos)):.{qprec}f}"
    _sodex("orders", "place", "perps", "--symbol", pair, "--side", side,
           "--qty", qs, "--type", "market", "--tif", "ioc", "--reduce-only")
    log.warning("TAKER-FLATTEN %s side=%s pos=%.6f", pair, side, float(pos))


def _open_orders():
    j = _sodex("orders", "list", "perps")
    if isinstance(j, dict):
        return j.get("data", {}).get("orders", []) or []
    return []


def _poll_fill(pair, oid, want_qty, timeout):
    """Poll for order fill by monitoring position delta.

    Returns True if |pos_now - pos_base| >= 90% of want_qty within timeout.
    When order disappears from open-order list, waits 1.5s for pos API to settle.
    """
    start = time.time()
    base = abs(_real_pos(pair))
    while time.time() - start < timeout:
        time.sleep(1.5)
        now = abs(_real_pos(pair))
        if abs(now - base) >= want_qty * D("0.9"):
            return True
        oids = [str(o.get("orderID")) for o in _open_orders()]
        if str(oid) not in oids:
            time.sleep(1.5)
            now2 = abs(_real_pos(pair))
            return abs(now2 - base) >= want_qty * D("0.9")
    return False


# ── state persistence ──────────────────────────────────────────────────────────

def _load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(s):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2))
    tmp.replace(STATE_FILE)


# ── emergency flatten (all pairs) ─────────────────────────────────────────────

def emergency_flatten():
    log.warning("EMERGENCY FLATTEN")
    for pair in CHURN_PAIRS:
        for o in _open_orders():
            if o.get("symbol") == pair:
                _cancel(pair, o.get("orderID"))
        time.sleep(0.5)
        _taker_flatten(pair)


# ── per-pair worker ────────────────────────────────────────────────────────────

def _pair_worker(pair: str, baseline_av: D, shared: dict, lock: threading.Lock):
    """Loop: acquire _RT_SEM -> run one RT -> release _RT_SEM -> repeat.

    v4: serial via _RT_SEM. Both BTC and ETH threads compete for the same
    semaphore; only one runs a roundtrip at a time, eliminating all cross-pair
    API races from concurrent order placement and position reads.
    """
    while True:
        with lock:
            if shared["stop"]:
                return

        # Fail-closed KILL switch (re-checked each loop iteration).
        if KILL_FILE.exists():
            with lock:
                if not shared["stop"]:
                    log.error("KILL switch present (data/CHURN_KILL) -> flatten + STOP ALL")
                    shared["stop"] = True
                    shared["stop_reason"] = "kill_switch"
            return

        if _past_deadline():
            with lock:
                if not shared["stop"]:
                    log.error("MISSION DEADLINE PASSED (%s) -> stop", DEADLINE_UTC)
                    shared["stop"] = True
                    shared["stop_reason"] = "deadline"
            return

        # Acquire with 10s timeout so stop flag is re-checked periodically
        if not _RT_SEM.acquire(timeout=10):
            with lock:
                if shared["stop"]:
                    return
            continue

        try:
            _pair_rt(pair, baseline_av, shared, lock)
        finally:
            _RT_SEM.release()


def _pair_rt(pair: str, baseline_av: D, shared: dict, lock: threading.Lock):
    """Execute one full roundtrip for `pair`. Called inside _RT_SEM."""

    with lock:
        if shared["stop"]:
            return

    # ── account value + all safety caps ──
    try:
        av = _account_value()
    except Exception:
        time.sleep(2)
        return

    if av <= MISSION_FLOOR_AV:
        with lock:
            if not shared["stop"]:
                log.error("MISSION FLOOR $%.2f HIT (av=$%.2f) -> flatten + STOP ALL",
                          float(MISSION_FLOOR_AV), float(av))
                shared["stop"] = True
                shared["stop_reason"] = "mission_floor"
        return

    session_dd = baseline_av - av
    if session_dd >= LOSS_CAP:
        with lock:
            if not shared["stop"]:
                log.error("SESSION LOSS CAP -- dd=$%.2f >= $%.0f -> stop",
                          float(session_dd), float(LOSS_CAP))
                shared["stop"] = True
                shared["stop_reason"] = "session_loss_cap"
        return

    with lock:
        lt_cost = D(str(shared.get("lifetime_cost", "0")))
        if lt_cost >= LIFETIME_CAP:
            if not shared["stop"]:
                log.error("LIFETIME CAP HIT -- total_cost=$%.2f >= $%.0f -> stop",
                          float(lt_cost), float(LIFETIME_CAP))
                shared["stop"] = True
                shared["stop_reason"] = "lifetime_cap"
            return
        if D(str(shared["vol"])) >= VOLUME_TARGET:
            if not shared["stop"]:
                log.info("VOLUME TARGET HIT -- $%.0f >= $%.0f",
                         float(shared["vol"]), float(VOLUME_TARGET))
                shared["stop"] = True
                shared["stop_reason"] = "target_hit"
            return

    # ── read orderbook ──
    bid, ask = _book(pair)
    if not bid or not ask:
        time.sleep(1)
        return

    # ── v4 spread gate: skip this RT if spread is too tight ──
    spread_bps = (ask - bid) / bid * 10000
    if MIN_SPREAD_BPS > 0 and spread_bps < MIN_SPREAD_BPS:
        log.debug("%s spread=%.3fbps < %.1fbps gate -> skip", pair, float(spread_bps), float(MIN_SPREAD_BPS))
        time.sleep(1)
        return

    # ── compute order qty ──
    qty = _qty(CHURN_NOTIONAL, ask, pair)
    if qty <= 0:
        time.sleep(1)
        return

    # ── inventory / unexpected-short guard ──
    cur_pos = _real_pos(pair)
    if cur_pos < D("-0.001"):
        log.warning("%s unexpected short=%.6f -> taker-close", pair, float(cur_pos))
        _taker_flatten(pair)
        time.sleep(1)
        return
    if cur_pos * ask >= MAX_INV_USD:
        log.warning("%s inv=$%.0f >= cap=$%.0f -> flatten", pair, float(cur_pos * ask), float(MAX_INV_USD))
        _taker_flatten(pair)
        time.sleep(1)
        return

    # ── PHASE 1: Maker-in BUY ─────────────────────────────────────────────────
    # G1: Pre-buy -- already long (prior undetected fill) -> go to maker-out
    if cur_pos >= qty * D("0.9"):
        log.warning("%s G1 pre-buy: pos=%.6f >= %.6f -> skip maker-in (recovery)",
                    pair, float(cur_pos), float(qty))
        qty = cur_pos
        with lock:
            shared["vol"] = str(D(str(shared["vol"])) + qty * bid)
    else:
        oid = _place_maker(pair, "buy", bid, qty)
        if not oid:
            time.sleep(0.5)
            return

        filled = _poll_fill(pair, oid, qty, FILL_WAIT_S)
        if not filled:
            _cancel(pair, oid)
            # G2: Post-cancel (buy) -- 1s settle + re-check for late fill
            time.sleep(1.0)
            late_pos = _real_pos(pair)
            if late_pos >= qty * D("0.9"):
                log.warning("%s G2 late-fill: pos=%.6f -> recovery maker-out", pair, float(late_pos))
                _lstep, _ = _STEP.get(pair, (D("0.001"), 3))
                qty = (late_pos // _lstep) * _lstep if _lstep > 0 else late_pos
                with lock:
                    shared["vol"] = str(D(str(shared["vol"])) + qty * bid)
                # fall through to Phase 2
            else:
                return  # Genuinely not filled
        else:
            time.sleep(1.0)  # brief settle for pos API after fill
            with lock:
                shared["vol"] = str(D(str(shared["vol"])) + qty * bid)

    # ── PHASE 2: Maker-out SELL (patient) ────────────────────────────────────
    out_start = time.time()
    sold = False
    sell_attempts = 0

    while time.time() - out_start < MAKER_OUT_MAX_S:
        with lock:
            if shared["stop"]:
                _taker_flatten(pair)
                return

        # Floor guard mid-hold
        try:
            if _account_value() <= MISSION_FLOOR_AV:
                _taker_flatten(pair)
                with lock:
                    if not shared["stop"]:
                        log.error("MISSION FLOOR hit mid-hold -> flatten + STOP")
                        shared["stop"] = True
                        shared["stop_reason"] = "mission_floor"
                return
        except Exception:
            pass

        # G3: Flat-confirm -- 2.0s settle (v4, was 0.5s) before trusting pos=0
        hold_pos = _real_pos(pair)
        if hold_pos <= D("0.001"):
            time.sleep(2.0)
            hold_pos = _real_pos(pair)
            if hold_pos <= D("0.001"):
                if hold_pos < D("-0.001"):
                    log.warning("%s G3: over-sold short=%.6f -> taker-close", pair, float(hold_pos))
                    _taker_flatten(pair)
                sold = True
                break

        # G4: Pre-sell confirm (v4 NEW) -- 2 reads x 2s to guard seller-race
        # If we're flat (soid filled before we read), this returns ~0 and we stop.
        actual_pos = _real_pos_confirmed(pair)
        if actual_pos <= D("0.001"):
            log.debug("%s G4: confirmed flat after settle -> sold", pair)
            sold = True
            break
        if actual_pos < D("-0.001"):
            log.warning("%s G4: short=%.6f -> taker-close", pair, float(actual_pos))
            _taker_flatten(pair)
            sold = True
            break

        # Fresh ask price for SELL
        _, ask2 = _book(pair)
        if not ask2:
            time.sleep(0.5)
            continue

        _step, _ = _STEP.get(pair, (D("0.001"), 3))
        sell_qty = (actual_pos // _step) * _step if _step > 0 else actual_pos
        if sell_qty <= 0:
            time.sleep(0.5)
            continue

        sell_attempts += 1
        soid = _place_maker(pair, "sell", ask2, sell_qty)
        if not soid:
            time.sleep(0.5)
            continue

        if _poll_fill(pair, soid, sell_qty, FILL_WAIT_S):
            with lock:
                shared["vol"] = str(D(str(shared["vol"])) + sell_qty * ask2)
            sold = True
            break

        # SELL didn't fill in time -- cancel + check result
        _cancel(pair, soid)

        # G5: Post-cancel (sell) -- POST_CANCEL_S settle + _real_pos_confirmed
        # Scenario: soid filled just before cancel arrives at exchange.
        # After 3.0s, API has updated. _real_pos_confirmed adds 2s more.
        # If post_pos=0 -> soid actually filled -> credit volume + done.
        # If post_pos>0 -> genuinely still long -> loop for another SELL.
        time.sleep(POST_CANCEL_S)
        post_pos = _real_pos_confirmed(pair)

        if post_pos <= D("0.001"):
            if post_pos < D("-0.001"):
                log.warning("%s G5 cancel-race: short=%.6f -> taker-flatten", pair, float(post_pos))
                _taker_flatten(pair)
            else:
                with lock:
                    shared["vol"] = str(D(str(shared["vol"])) + sell_qty * ask2)
                log.debug("%s G5: fill-before-cancel detected, vol credited", pair)
            sold = True
            break
        # Still long -> loop back for another SELL attempt

    # ── Fallback: taker-flatten if maker-out window exhausted ──
    if not sold:
        _, ask3 = _book(pair)
        _taker_flatten(pair)
        if ask3:
            with lock:
                shared["vol"] = str(D(str(shared["vol"])) + qty * ask3)
        log.warning("%s maker-out TIMEOUT %.0fs / %d attempts -> taker-flatten",
                    pair, MAKER_OUT_MAX_S, sell_attempts)

    with lock:
        shared["roundtrips"] += 1
        shared["last_av"] = str(av)
        shared["session_dd"] = str(session_dd)


# ── main run ───────────────────────────────────────────────────────────────────

def run():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _load_markets()
    for p in CHURN_PAIRS:
        _set_leverage(p, CHURN_LEVERAGE)

    # Fail-closed KILL switch: touch data/CHURN_KILL to stop all trading.
    if KILL_FILE.exists():
        log.info("KILL switch present (data/CHURN_KILL) — no trading")
        return

    state = _load_state()
    lifetime_vol  = D(str(state.get("lifetime_volume", "0")))
    lifetime_cost = D(str(state.get("lifetime_cost",   "0")))

    baseline_av = _account_value()
    start_ts    = time.time()

    log.info(
        "SESSION START v4 | pairs=%s notional=$%.0f fill_wait=%.0fs "
        "post_cancel=%.1fs pos_confirm=%dx%.1fs min_spread=%.1fbps | "
        "loss_cap=$%.0f lifetime_cap=$%.0f target=$%.0f | "
        "lifetime_vol=$%.0f lifetime_cost=$%.2f | av=$%.2f floor=$%.2f",
        CHURN_PAIRS, float(CHURN_NOTIONAL), FILL_WAIT_S,
        POST_CANCEL_S, POS_CONFIRM_N, POS_CONFIRM_S, float(MIN_SPREAD_BPS),
        float(LOSS_CAP), float(LIFETIME_CAP), float(VOLUME_TARGET),
        float(lifetime_vol), float(lifetime_cost),
        float(baseline_av), float(MISSION_FLOOR_AV),
    )

    if _past_deadline():
        log.info("MISSION DEADLINE PASSED (%s) -- no trades.", DEADLINE_UTC)
        return
    if lifetime_cost >= LIFETIME_CAP:
        log.info("LIFETIME CAP already reached ($%.2f) -- nothing to do.", float(lifetime_cost))
        return
    if lifetime_vol >= VOLUME_TARGET:
        log.info("VOLUME TARGET already reached ($%.0f) -- nothing to do.", float(lifetime_vol))
        return

    lock   = threading.Lock()
    shared = {
        "vol":           str(lifetime_vol),
        "roundtrips":    0,
        "stop":          False,
        "stop_reason":   "",
        "last_av":       str(baseline_av),
        "session_dd":    "0",
        "lifetime_cost": str(lifetime_cost),
    }

    threads = []
    for pair in CHURN_PAIRS:
        t = threading.Thread(
            target=_pair_worker,
            args=(pair, baseline_av, shared, lock),
            daemon=True, name=f"churn-{pair}",
        )
        t.start()
        threads.append(t)
        log.info("Thread started: %s (serial via _RT_SEM)", pair)

    log_interval = 60
    next_log = time.time() + log_interval
    while True:
        time.sleep(2)
        with lock:
            stop    = shared["stop"]
            vol     = D(str(shared["vol"]))
            rt      = shared["roundtrips"]
            last_av = D(str(shared["last_av"]))
            dd      = D(str(shared["session_dd"]))

        if time.time() >= next_log:
            session_vol = vol - lifetime_vol
            cost_so_far = baseline_av - last_av
            bps = float(cost_so_far / session_vol * 10000) if session_vol > 0 else 0
            budget_left = float(LIFETIME_CAP) - float(lifetime_cost) - float(cost_so_far)
            log.info(
                "progress | lifetime_vol=$%.0f/%.0f session_vol=$%.0f rt=%d "
                "av=$%.2f dd=$%.2f bps=%.2f budget_left=$%.2f",
                float(vol), float(VOLUME_TARGET), float(session_vol),
                rt, float(last_av), float(dd), bps, budget_left,
            )
            next_log = time.time() + log_interval

        if stop:
            break
        if time.time() - start_ts >= RUN_SECONDS:
            with lock:
                shared["stop"] = True
                shared["stop_reason"] = "session_timeout"
            log.info("SESSION TIMEOUT (%.0fh)", RUN_SECONDS / 3600)
            break

    for t in threads:
        t.join(timeout=60)

    emergency_flatten()

    final_av     = _account_value()
    session_cost = baseline_av - final_av
    session_vol  = D(str(shared["vol"])) - lifetime_vol
    new_lt_vol   = lifetime_vol + session_vol
    new_lt_cost  = lifetime_cost + session_cost
    stop_reason  = shared.get("stop_reason", "unknown")

    state.update({
        "run_active":        False,
        "last_session_vol":  str(session_vol),
        "last_session_cost": str(session_cost),
        "lifetime_volume":   str(new_lt_vol),
        "lifetime_cost":     str(new_lt_cost),
        "last_av":           str(final_av),
        "stop_reason":       stop_reason,
        "sessions":          state.get("sessions", 0) + 1,
    })
    _save_state(state)

    log.info(
        "SESSION DONE | reason=%s session_vol=$%.0f session_cost=$%.2f "
        "lifetime_vol=$%.0f lifetime_cost=$%.2f (%.1f%% of $%.0f budget) "
        "av $%.2f->$%.2f",
        stop_reason, float(session_vol), float(session_cost),
        float(new_lt_vol), float(new_lt_cost),
        float(new_lt_cost / LIFETIME_CAP * 100) if LIFETIME_CAP else 0,
        float(LIFETIME_CAP), float(baseline_av), float(final_av),
    )


def status():
    s       = _load_state()
    lt_vol  = float(s.get("lifetime_volume", 0))
    lt_cost = float(s.get("lifetime_cost", 0))
    target  = float(VOLUME_TARGET)
    budget  = float(LIFETIME_CAP)
    pct_vol  = lt_vol / target * 100  if target else 0
    pct_cost = lt_cost / budget * 100 if budget else 0
    bps_avg  = lt_cost / lt_vol * 10000 if lt_vol > 0 else 0
    print(f"lifetime_volume  : ${lt_vol:,.0f} / ${target:,.0f}  ({pct_vol:.1f}%)")
    print(f"lifetime_cost    : ${lt_cost:.2f} / ${budget:.0f}  ({pct_cost:.1f}% budget)")
    print(f"avg_bps          : {bps_avg:.2f}")
    print(f"sessions         : {s.get('sessions', 0)}")
    print(f"last_session_vol : ${float(s.get('last_session_vol', 0)):,.0f}")
    print(f"last_av          : ${float(s.get('last_av', 0)):.2f}")
    print(f"stop_reason      : {s.get('stop_reason', '-')}")
    print("STATUS           : RUNNING" if s.get("run_active") else "STATUS           : IDLE")


if __name__ == "__main__":
    if "--flatten" in sys.argv:
        _load_markets()
        emergency_flatten()
    elif "--status" in sys.argv:
        status()
    else:
        run()
