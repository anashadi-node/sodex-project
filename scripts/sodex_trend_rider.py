#!/usr/bin/env python3
"""SoDEX Trend-Rider — WITH-trend directional hold on stock perps.

Replicates leaderboard winners' daily method: scan moving assets, enter
WITH the trend already established, hold until trailing-stop or 24h.

Entry criteria (all required):
  - US session (13:00-21:00 UTC, when stock perps have real liquidity)
  - Daily change >= TR_MIN_CHG_PCT (3%)
  - Trend continuity >= TR_MIN_CONTINUITY (0.75) — price still near day's extreme
  - Scanner score in top N candidates

Position management:
  - Size: TR_NOTIONAL_PER_POS notional at TR_LEVERAGE × (e.g., $100 @ 5× = $20 margin)
  - Hard SL: TR_SL_PCT adverse from entry (2%)
  - Trail stop: TR_TRAIL_PCT reversal from peak/trough (2%)
  - Time-stop: TR_MAX_HOLD_HOURS from entry (24h)
  - Daily loss cap: TR_DAILY_LOSS_LIMIT total across all positions today ($6)

Usage:
  python3 scripts/sodex_trend_rider.py             # scan → open → monitor (one loop)
  python3 scripts/sodex_trend_rider.py --status    # show state only
  python3 scripts/sodex_trend_rider.py --close-all # force close all open rider positions
  python3 scripts/sodex_trend_rider.py --dry-run   # print plan, no orders
"""
from __future__ import annotations
import json, logging, os, subprocess, sys, time
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

# ─── Config ───────────────────────────────────────────────────────────────────
TR_NOTIONAL    = D(os.environ.get("TR_NOTIONAL_PER_POS", "100"))   # notional per position
TR_LEVERAGE    = int(os.environ.get("TR_LEVERAGE", "5"))
TR_MAX_POS     = int(os.environ.get("TR_MAX_POSITIONS", "2"))
TR_SL_PCT      = D(os.environ.get("TR_SL_PCT", "2.0"))             # hard stop %
TR_TRAIL_PCT   = D(os.environ.get("TR_TRAIL_PCT", "2.0"))          # trailing stop %
TR_TRAIL_ARM   = D(os.environ.get("TR_TRAIL_ARM_PCT", "1.0"))       # arm trail once PEAK profit ≥ this (lock winners)
TR_BE_LOCK     = D(os.environ.get("TR_BREAKEVEN_LOCK_PCT", "0.15"))  # once armed, exit if pnl retraces to this floor (cover fees) → never let a winner become a loss
TR_HOLD_HOURS  = int(os.environ.get("TR_MAX_HOLD_HOURS", "24"))
TR_DAILY_LOSS  = D(os.environ.get("TR_DAILY_LOSS_LIMIT", "6"))
TR_MIN_CONT    = D(os.environ.get("TR_MIN_CONTINUITY", "0.75"))
TR_MIN_CHG     = D(os.environ.get("TR_MIN_CHG_PCT", "3.0"))
TR_MAX_SPREAD  = D(os.environ.get("TR_MAX_SPREAD_BPS", "3.0"))     # reject wide spreads
TR_REOPEN_CD_H = D(os.environ.get("TR_REOPEN_COOLDOWN_HOURS", "4"))  # anti-churn: no reopen for N h after a close
TR_GAP_SL_PCT  = D(os.environ.get("TR_GAP_SL_PCT", "3.0"))         # wide gap backstop (fast watcher) — NOT the primary 2% SL

SODEX_CLI  = PROJECT / "bin" / "sodex"
SCAN_FILE  = PROJECT / "data" / "sodex_trend_scan.json"
STATE_FILE = PROJECT / "data" / "trend_rider_state.json"
LOG_FILE   = PROJECT / "logs" / "trend_rider.log"
KILL_FILE  = PROJECT / "data" / "TREND_RIDER_KILL"   # fail-closed KILL switch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s TR %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("trend_rider")

# ─── env for CLI ──────────────────────────────────────────────────────────────
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
    # SODEX_API_KEY intentionally excluded (blocks perps orders)
    env.pop("SODEX_API_KEY", None)
    return env


_ENV = _build_env()


def _sodex(*args: str, timeout: int = 30) -> dict | list | None:
    """Run bin/sodex command, return parsed JSON or None on failure."""
    cmd = [str(SODEX_CLI), "--format", "json"] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, env=_ENV)
        out = r.stdout.strip()
        if not out:
            if r.stderr:
                log.warning("sodex stderr: %s", r.stderr.strip()[:200])
            return None
        return json.loads(out)
    except subprocess.TimeoutExpired:
        log.warning("sodex timeout: %s", " ".join(args[:4]))
        return None
    except json.JSONDecodeError as e:
        log.warning("sodex json error %s: %.100s", e, r.stdout)
        return None
    except Exception as e:
        log.error("sodex exc: %s", e)
        return None


# ─── State ────────────────────────────────────────────────────────────────────
def _load_state() -> dict:
    try:
        if STATE_FILE.exists():
            s = json.loads(STATE_FILE.read_text())
            if isinstance(s, dict):
                return s
    except Exception:
        pass
    return {"positions": {}, "daily_loss": "0", "day": ""}


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _reset_daily_if_needed(state: dict) -> dict:
    today = _today_utc()
    if state.get("day") != today:
        state["daily_loss"] = "0"
        state["day"] = today
    return state


# ─── Market data ──────────────────────────────────────────────────────────────
def _get_ticker(symbol: str) -> dict | None:
    """Fetch live bid/ask/last for a single perp symbol via public API."""
    import urllib.request
    BASE = "https://mainnet-gw.sodex.dev/api/v1"
    try:
        req = urllib.request.Request(
            BASE + "/perps/markets/tickers",
            headers={"User-Agent": "trend-rider/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode()).get("data") or []
        for t in data:
            if isinstance(t, dict) and t.get("symbol") == symbol:
                return t
    except Exception as e:
        log.warning("ticker fetch error %s: %s", symbol, e)
    return None


_MARKET_INFO: dict[str, dict] = {}
_MARKET_INFO_TS: float = 0.0


def _market_info(symbol: str) -> dict:
    """Return {step, qprec, min_qty, min_notional, max_lev} for a perp symbol.

    Cached 1h from `bin/sodex markets perps`. Step/precision are REQUIRED to
    place valid orders — SoDEX rejects qty that doesn't match stepSize/qprec
    ("quantity is invalid"). Falls back to safe defaults if lookup fails.
    """
    global _MARKET_INFO, _MARKET_INFO_TS
    now = time.time()
    if not _MARKET_INFO or (now - _MARKET_INFO_TS) > 3600:
        j = _sodex("markets", "perps")
        rows = j if isinstance(j, list) else (j.get("data", []) if isinstance(j, dict) else [])
        info = {}
        for x in rows:
            if isinstance(x, dict) and x.get("status") == "TRADING":
                info[x.get("name")] = {
                    "step": D(str(x.get("stepSize", "0.001") or "0.001")),
                    "qprec": int(x.get("quantityPrecision", 3) or 3),
                    "min_qty": D(str(x.get("minQuantity", "0.001") or "0.001")),
                    "min_notional": D(str(x.get("minNotional", "10") or "10")),
                    "max_lev": int(x.get("maxLeverage", 5) or 5),
                }
        if info:
            _MARKET_INFO = info
            _MARKET_INFO_TS = now
    return _MARKET_INFO.get(symbol, {
        "step": D("0.001"), "qprec": 3, "min_qty": D("0.001"),
        "min_notional": D("10"), "max_lev": 5,
    })


def _extract_oid(j) -> str | None:
    """Extract a non-zero order id from a SoDEX response (dict OR list-of-dict).

    The perps place endpoint returns a LIST like
    [{"orderID": 12691839790, "clOrdID": "...", "status": ""}] on success — a
    real filled order. Earlier code only handled dict responses, which silently
    mis-flagged real fills as rejects. Handle both shapes.
    """
    rows = j if isinstance(j, list) else [j]
    for row in rows:
        if not isinstance(row, dict):
            continue
        for k in ("orderID", "orderId", "order_id", "id"):
            v = row.get(k)
            if v not in (None, 0, "0", ""):
                return str(v)
    return None


def _fetch_exchange_positions() -> dict[str, dict]:
    """Return {symbol: {size, entry_px, direction}} from the public positions API.

    size is signed (from exchange), entry from avgEntryPrice. This is exchange
    truth, used to reconcile local state so the monitor always protects real
    open positions even if they were opened outside a clean state write.
    """
    import urllib.request
    BASE = "https://mainnet-gw.sodex.dev/api/v1"
    ADDR = _ENV.get("SODEX_ADDRESS", "")
    out: dict[str, dict] = {}
    if not ADDR:
        return out
    try:
        req = urllib.request.Request(
            f"{BASE}/perps/accounts/{ADDR}/positions",
            headers={"User-Agent": "trend-rider/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        for p in (data.get("data", {}).get("positions") or []):
            sym = p.get("symbol")
            size = D(str(p.get("size", 0) or 0))
            if not sym or size == 0:
                continue
            out[sym] = {
                "size": size,
                "entry_px": D(str(p.get("avgEntryPrice", 0) or 0)),
                "direction": "long" if size > 0 else "short",
            }
    except Exception as e:
        log.warning("fetch exchange positions error: %s", e)
    return out


def _get_real_position(symbol: str) -> D:
    """Return signed real position qty from exchange (+ = long, - = short, 0 = flat)."""
    return _fetch_exchange_positions().get(symbol, {}).get("size", D(0))


def _reconcile_state(state: dict) -> dict:
    """Sync local state with exchange truth BEFORE monitoring/opening.

    - Adopt any exchange position missing from state (protect it: SL/trail/time).
    - Drop any state position no longer on the exchange (already closed).
    Adopted positions get entry_px from the exchange and entry_ts=now (a
    conservative time-stop clock; real age is unknown but bounded by 24h).
    """
    ex = _fetch_exchange_positions()

    # Drop stale local positions no longer on exchange
    for sym in list(state["positions"].keys()):
        if sym not in ex:
            log.info("Reconcile: %s in state but flat on exchange — drop", sym)
            state["positions"].pop(sym, None)

    # Adopt exchange positions missing from state
    for sym, info in ex.items():
        if sym in TR_RESERVED_PAIRS:
            continue  # churn owns these — don't adopt/manage
        if sym not in state["positions"]:
            entry = info["entry_px"]
            state["positions"][sym] = {
                "direction": info["direction"],
                "entry_px": str(entry),
                "peak_px": str(entry),
                "entry_ts": time.time(),
                "notional": str(abs(info["size"]) * entry),
                "leverage": TR_LEVERAGE,
                "adopted": True,
            }
            log.warning("Reconcile: ADOPTED unmanaged %s %s size=%s entry=%s "
                        "→ now protected by SL/trail",
                        info["direction"].upper(), sym, info["size"], entry)
    return state


# ─── Scan ─────────────────────────────────────────────────────────────────────
def _load_scan() -> list[dict]:
    """Load latest scanner output. Staleness check: must be < 30 min old."""
    if not SCAN_FILE.exists():
        return []
    try:
        data = json.loads(SCAN_FILE.read_text())
        ts = data.get("ts", "")
        if ts:
            age = (datetime.now(timezone.utc) -
                   datetime.fromisoformat(ts)).total_seconds()
            if age > 1800:
                log.warning("Scan stale (%.0f min) — run scanner first", age / 60)
                return []
        return data.get("candidates", [])
    except Exception as e:
        log.warning("scan load error: %s", e)
        return []


# Stock/commodity perps follow US market hours (illiquid off-hours). Everything
# else (crypto perps) trades 24/7. Misclassification is self-correcting: an
# off-hours stock perp that slips through still gets rejected by the spread filter.
STOCK_COMMODITY_BASES = {
    # US equities (err toward more: over-inclusion only costs off-hours volume;
    # under-inclusion risks trading an illiquid stock perp overnight)
    "TSLA", "GOOGL", "GOOG", "AAPL", "META", "NVDA", "MU", "HOOD", "MSTR",
    "COIN", "INTC", "ORCL", "SNDK", "CRCL", "SKHY", "SKHX", "SPCX", "MRVL",
    "AMD", "AMZN", "MSFT", "NFLX", "PLTR", "AVGO", "SMCI", "ARM", "DELL",
    "IBM", "CSCO", "QCOM", "TSM", "BABA", "NKE", "DIS", "BA", "JPM", "V",
    # indices
    "US500", "USTECH100", "US30", "US2000",
    # commodities / metals
    "CL", "WTI", "BRENT", "SILVER", "GOLD", "NATGAS", "XAUT", "XAG", "COPPER",
}


def _is_stock_commodity(symbol: str) -> bool:
    """True if symbol is a stock/commodity perp (needs US market hours)."""
    base = symbol.split("-")[0] if "-" in symbol else symbol
    return base in STOCK_COMMODITY_BASES


# Pairs reserved for the volume-churn engine — Trend-Rider must NOT trade these,
# else the two systems fight over the same position (churn taker-flatten would
# close a Trend-Rider hold). Keep them disjoint.
TR_RESERVED_PAIRS = set(
    p.strip() for p in os.environ.get("TR_RESERVED_PAIRS", "BTC-USD,ETH-USD").split(",") if p.strip())


def _filter_candidates(candidates: list[dict]) -> list[dict]:
    """Apply entry criteria filter to scanner candidates.

    24/7: crypto perps trade around the clock. Stock/commodity perps only during
    the US session (13-21 UTC) when they have real liquidity.
    """
    now = datetime.now(timezone.utc)
    us_session = 13 <= now.hour < 21

    out = []
    for c in candidates:
        sym = c.get("symbol", "")
        chg = abs(D(str(c.get("chg24h_pct", 0))))
        cont = D(str(c.get("continuity", 0)))
        spread = D(str(c.get("spread_bps", 99)))

        # Skip churn-reserved pairs (kept disjoint from the volume engine).
        if sym in TR_RESERVED_PAIRS:
            continue

        # Session gate: stocks/commodities need US hours; crypto is 24/7.
        if _is_stock_commodity(sym) and not us_session:
            continue

        if chg < TR_MIN_CHG:
            continue
        if cont < TR_MIN_CONT:
            continue
        if spread > TR_MAX_SPREAD:
            log.info("%s spread=%.2fbps > %.2f max — skip", sym, spread, TR_MAX_SPREAD)
            continue
        out.append(c)

    if not out and not us_session:
        log.info("No crypto candidates pass filter (UTC %02d:xx, stocks gated off-hours)", now.hour)
    return out


# ─── Execution ────────────────────────────────────────────────────────────────
def _set_leverage(symbol: str, lev: int) -> bool:
    """Set isolated leverage for a perp symbol.

    The `leverage` CLI command returns plain text ("leverage updated: ...") not
    JSON, and its echoed values are cosmetically buggy — so we judge success by
    exit code + text marker, NOT by JSON parse. Best-effort: a failure here is
    logged but does not block order placement (order uses existing/default lev).
    """
    cmd = [str(SODEX_CLI), "leverage", symbol, str(lev), "--mode", "isolated"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=20, env=_ENV)
        ok = (r.returncode == 0) or ("leverage updated" in (r.stdout or "").lower())
        if ok:
            log.info("Leverage set %s → %d×", symbol, lev)
        else:
            log.warning("Leverage set non-fatal fail %s %d× rc=%s: %s",
                        symbol, lev, r.returncode, (r.stderr or r.stdout).strip()[:120])
        return ok
    except Exception as e:
        log.warning("Leverage set exc %s %d×: %s (non-fatal, proceeding)", symbol, lev, e)
        return False


def _qty_for_notional(notional: D, price: D, symbol: str) -> D:
    """Compute order qty = notional / price, snapped DOWN to the symbol stepSize.

    Snapping down to stepSize (not just rounding to qprec) is what SoDEX requires
    — e.g. SPCX step=0.01 → 0.894 is invalid, 0.89 is valid. Also enforces
    minNotional: if the snapped qty is below the exchange minimum, bump to min_qty
    (only if that still fits notional intent), else return 0 (skip).
    """
    if price <= 0:
        return D(0)
    mi = _market_info(symbol)
    step = mi["step"]
    raw = notional / price
    # snap DOWN to nearest step multiple
    if step > 0:
        qty = (raw // step) * step
    else:
        qty = raw
    qty = qty.quantize(step) if step > 0 else qty
    # enforce minimums
    if qty < mi["min_qty"]:
        qty = mi["min_qty"]
    if qty * price < mi["min_notional"]:
        # too small even at min_qty vs our notional intent → skip
        need = mi["min_notional"] / price
        if need <= raw * D("1.5"):  # allow up to 1.5× intended to meet min
            qty = ((need // step) * step + step).quantize(step) if step > 0 else need
        else:
            return D(0)
    return qty


def _open_position(symbol: str, direction: str, dry_run: bool = False) -> bool:
    """Open a new Trend-Rider position. direction: 'long' or 'short'."""
    t = _get_ticker(symbol)
    if not t:
        log.warning("Cannot open %s — no ticker", symbol)
        return False

    bid = D(str(t.get("bidPx", 0) or 0))
    ask = D(str(t.get("askPx", 0) or 0))
    last = D(str(t.get("lastPx", 0) or 0))
    if min(bid, ask, last) <= 0:
        log.warning("Cannot open %s — invalid prices bid=%s ask=%s", symbol, bid, ask)
        return False

    # Taker price: BUY at ask, SELL at bid (crosses spread → guaranteed fill)
    side = "buy" if direction == "long" else "sell"
    exec_px = ask if side == "buy" else bid

    qty = _qty_for_notional(TR_NOTIONAL, exec_px, symbol)
    if qty <= 0:
        log.warning("Cannot open %s — qty=0 for notional=%s price=%s", symbol, TR_NOTIONAL, exec_px)
        return False

    actual_notional = qty * exec_px
    margin_est = actual_notional / TR_LEVERAGE
    spread_bps = (ask - bid) / ((ask + bid) / 2) * 10000

    log.info("OPEN %s %s | qty=%s notional=$%.2f margin≈$%.2f spread=%.2fbps",
             direction.upper(), symbol, qty, float(actual_notional), float(margin_est), float(spread_bps))

    if dry_run:
        log.info("[DRY-RUN] Would place: orders place perps --symbol %s --side %s "
                 "--qty %s --type market --tif ioc", symbol, side, qty)
        return True

    # 1. Set leverage (best-effort, non-blocking — order uses default lev if this fails)
    #    Clamp to the symbol's maxLeverage (e.g. LIT caps at 5×).
    lev = min(TR_LEVERAGE, _market_info(symbol)["max_lev"])
    _set_leverage(symbol, lev)

    # 2. Place market-IOC (guaranteed taker fill)
    j = _sodex("orders", "place", "perps",
                "--symbol", symbol,
                "--side", side,
                "--qty", str(qty),
                "--type", "market",
                "--tif", "ioc",
                timeout=30)

    if not j:
        log.warning("Order rejected for %s %s qty=%s", symbol, side, qty)
        return False

    oid = _extract_oid(j)
    if not oid:
        log.warning("Order oid=0/null for %s — rejected by exchange: %s", symbol, str(j)[:200])
        return False

    log.info("Order FILLED %s %s oid=%s qty=%s @ %s", direction.upper(), symbol, oid, qty, exec_px)
    return True


def _close_position(symbol: str, direction: str, reason: str) -> bool:
    """Close an open Trend-Rider position with market-IOC reduce-only."""
    t = _get_ticker(symbol)
    if not t:
        log.warning("Close %s — no ticker", symbol)
        return False

    bid = D(str(t.get("bidPx", 0) or 0))
    ask = D(str(t.get("askPx", 0) or 0))
    if min(bid, ask) <= 0:
        return False

    # Close side is opposite of open side
    close_side = "sell" if direction == "long" else "buy"
    ref_px = bid if close_side == "sell" else ask

    # Get real qty from exchange
    real = _get_real_position(symbol)
    qty = abs(real)
    if qty <= 0:
        log.info("Close %s — already flat", symbol)
        return True  # already closed

    log.info("CLOSE %s %s qty=%s ref=%s reason=%s", direction.upper(), symbol, qty, ref_px, reason)

    j = _sodex("orders", "place", "perps",
                "--symbol", symbol,
                "--side", close_side,
                "--qty", str(qty),
                "--type", "market",
                "--tif", "ioc",
                "--reduce-only",
                timeout=30)

    if not j:
        log.warning("Close order rejected %s", symbol)
        return False

    oid = _extract_oid(j)
    if oid:
        log.info("Close FILLED %s oid=%s reason=%s", symbol, oid, reason)
        return True
    else:
        log.warning("Close oid=0 for %s: %s", symbol, str(j)[:150])
        return False


# ─── Monitor ──────────────────────────────────────────────────────────────────
def _check_exits(state: dict) -> dict:
    """Check trailing stop / time-stop / hard stop for all open rider positions."""
    now_ts = time.time()
    daily_loss = D(state.get("daily_loss", "0"))
    to_remove = []

    for sym, pos in state["positions"].items():
        entry_px   = D(str(pos["entry_px"]))
        direction  = pos["direction"]
        entry_ts   = float(pos["entry_ts"])
        peak_px    = D(str(pos.get("peak_px", str(entry_px))))
        age_hours  = (now_ts - entry_ts) / 3600

        # Fetch current price
        t = _get_ticker(sym)
        if not t:
            log.warning("Monitor %s — no ticker, skip", sym)
            continue

        last = D(str(t.get("lastPx", 0) or 0))
        if last <= 0:
            continue

        # Update peak
        if direction == "long":
            if last > peak_px:
                peak_px = last
                pos["peak_px"] = str(peak_px)
        else:  # short
            if last < peak_px:
                peak_px = last
                pos["peak_px"] = str(peak_px)

        # Compute PnL% (current) + PEAK profit% (best reached) + adverse reversal from peak
        if direction == "long":
            pnl_pct = (last - entry_px) / entry_px * 100
            peak_profit_pct = (peak_px - entry_px) / entry_px * 100
            reversal_pct = (last - peak_px) / peak_px * 100  # negative = reversed down from peak
        else:
            pnl_pct = (entry_px - last) / entry_px * 100
            peak_profit_pct = (entry_px - peak_px) / entry_px * 100
            reversal_pct = (peak_px - last) / peak_px * 100  # negative = price rose back from trough

        # Arm the trail once PEAK profit crossed the arm threshold (sticky, persisted).
        armed = bool(pos.get("trail_armed")) or peak_profit_pct >= TR_TRAIL_ARM
        if armed:
            pos["trail_armed"] = True

        log.info("MONITOR %s %s entry=%s last=%s peak=%s pnl=%.2f%% peakP=%.2f%% "
                 "trail=%.2f%% armed=%s age=%.1fh",
                 direction.upper(), sym, entry_px, last, peak_px,
                 float(pnl_pct), float(peak_profit_pct), float(-reversal_pct), armed, age_hours)

        reason = None

        # 1. Time-stop
        if age_hours >= TR_HOLD_HOURS:
            reason = f"time_stop ({age_hours:.1f}h)"

        # 2. Hard stop-loss
        elif pnl_pct <= -TR_SL_PCT:
            reason = f"hard_sl ({float(pnl_pct):.2f}%)"

        # 3. Trailing stop — once ARMED (peak profit ≥ arm), fire on reversal from
        #    peak regardless of current pnl → locks in gains, prevents winner round-trip.
        elif armed and -reversal_pct >= TR_TRAIL_PCT:
            reason = f"trail_stop ({float(-reversal_pct):.2f}% from peak, pnl={float(pnl_pct):.2f}%)"

        # 3b. Breakeven-lock — once armed, an aggressive floor: if the winner
        #     retraces all the way down to ~breakeven, exit here instead of waiting
        #     for the full trail distance. Guarantees an armed winner never turns
        #     into a loss (aggressive profit protection).
        elif armed and pnl_pct <= TR_BE_LOCK:
            reason = f"breakeven_lock (pnl={float(pnl_pct):.2f}% after peak={float(peak_profit_pct):.2f}%)"

        # 4. Daily loss cap
        elif daily_loss >= TR_DAILY_LOSS and pnl_pct < 0:
            reason = f"daily_loss_cap (total=${float(daily_loss):.2f})"

        if reason:
            ok = _close_position(sym, direction, reason)
            if ok:
                loss = max(D(0), -pnl_pct / 100 * TR_NOTIONAL)
                daily_loss += loss
                state["daily_loss"] = str(daily_loss)
                state.setdefault("cooldowns", {})[sym] = time.time()
                to_remove.append(sym)
                log.info("Position closed %s %s pnl=%.2f%% loss+=$%.4f daily_loss=$%.4f "
                         "(reopen cooldown %sh)",
                         sym, reason, float(pnl_pct), float(loss), float(daily_loss), TR_REOPEN_CD_H)

    for sym in to_remove:
        state["positions"].pop(sym, None)

    return state


# ─── Fast gap-stop watcher ────────────────────────────────────────────────────
def _gap_stop_watch(state: dict) -> dict:
    """Fast GAP backstop — poll exchange truth, close any position whose adverse
    move already exceeds TR_GAP_SL_PCT (wider than the primary 2% SL).

    Purpose: SoDEX has no native trigger-stop orders (CLI exposes only
    limit/market), so a violent gap between the 120s main cycles could blow past
    the soft 2% SL. This runs on a tight interval (e.g. 30s) as a backstop. It is
    intentionally NOT tight — it only fires on a genuine gap (default 3%), so it
    never competes with the primary SL/trail in the main loop for normal moves.

    Race-safe with the main loop: closes with idempotent reduce-only market-IOC
    against the REAL exchange position (qty=0 → no-op), and reads exchange truth
    directly rather than trusting local state.
    """
    ex = _fetch_exchange_positions()
    if not ex:
        return state
    for sym, info in ex.items():
        entry = info["entry_px"]
        direction = info["direction"]
        if entry <= 0:
            continue
        t = _get_ticker(sym)
        if not t:
            continue
        last = D(str(t.get("lastPx", 0) or 0))
        if last <= 0:
            continue
        adverse = ((last - entry) / entry * 100) if direction == "short" else ((entry - last) / entry * 100)
        # adverse > 0 means moving against us
        if adverse >= TR_GAP_SL_PCT:
            log.warning("GAP-STOP %s %s adverse=%.2f%% ≥ %.1f%% → emergency close",
                        direction.upper(), sym, float(adverse), float(TR_GAP_SL_PCT))
            notional = D(str(state.get("positions", {}).get(sym, {}).get("notional", TR_NOTIONAL)))
            ok = _close_position(sym, direction, f"gap_stop ({float(adverse):.2f}%)")
            if ok:
                state.setdefault("cooldowns", {})[sym] = time.time()
                state["positions"].pop(sym, None)
                dl = D(state.get("daily_loss", "0")) + max(D(0), adverse / 100 * notional)
                state["daily_loss"] = str(dl)
    return state


# ─── Open new positions ───────────────────────────────────────────────────────
def _open_new_positions(state: dict, candidates: list[dict], dry_run: bool) -> dict:
    """Open Trend-Rider positions for top qualifying candidates not already held."""
    n_open = len(state["positions"])
    daily_loss = D(state.get("daily_loss", "0"))

    if daily_loss >= TR_DAILY_LOSS:
        log.info("Daily loss cap hit ($%.2f) — no new entries today", float(daily_loss))
        return state

    for c in candidates:
        if n_open >= TR_MAX_POS:
            break
        sym = c["symbol"]
        direction = c["dir"].lower()

        if sym in state["positions"]:
            log.info("%s already in rider state — skip open", sym)
            continue

        # Anti-churn: skip symbols still in reopen cooldown after a recent close
        cd_ts = state.get("cooldowns", {}).get(sym)
        if cd_ts:
            age_h = (time.time() - float(cd_ts)) / 3600
            if age_h < float(TR_REOPEN_CD_H):
                log.info("%s in reopen cooldown (%.1fh/%sh) — skip", sym, age_h, TR_REOPEN_CD_H)
                continue
            else:
                state.get("cooldowns", {}).pop(sym, None)  # cooldown expired

        ok = _open_position(sym, direction, dry_run=dry_run)
        if not ok:
            continue

        n_open += 1  # respect cap in both dry-run and live

        if not dry_run:
            # Record position entry
            t = _get_ticker(sym)
            entry_px = D(str(t.get("lastPx", 0))) if t else D("0")
            state["positions"][sym] = {
                "direction": direction,
                "entry_px": str(entry_px),
                "peak_px": str(entry_px),
                "entry_ts": time.time(),
                "notional": str(TR_NOTIONAL),
                "leverage": TR_LEVERAGE,
            }
            log.info("Recorded rider position %s %s entry=%s", direction.upper(), sym, entry_px)

    return state


# ─── Status ───────────────────────────────────────────────────────────────────
def print_status(state: dict):
    now_ts = time.time()
    positions = state.get("positions", {})
    daily_loss = D(state.get("daily_loss", "0"))

    print(f"\n{'='*60}")
    print(f"  TREND-RIDER STATUS  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")
    print(f"  Daily loss used: ${float(daily_loss):.2f} / ${float(TR_DAILY_LOSS):.2f}")
    print(f"  Open positions:  {len(positions)} / {TR_MAX_POS}")

    if positions:
        for sym, pos in positions.items():
            direction = pos["direction"]
            entry_px  = D(str(pos["entry_px"]))
            peak_px   = D(str(pos.get("peak_px", str(entry_px))))
            age_h     = (now_ts - float(pos["entry_ts"])) / 3600

            t = _get_ticker(sym)
            last = D(str(t.get("lastPx", 0))) if t else D("0")
            if last > 0 and entry_px > 0:
                if direction == "long":
                    pnl_pct = (last - entry_px) / entry_px * 100
                    rv_pct  = (last - peak_px) / peak_px * 100
                else:
                    pnl_pct = (entry_px - last) / entry_px * 100
                    rv_pct  = -(peak_px - last) / peak_px * 100
                sl_price = (entry_px * (1 - TR_SL_PCT / 100) if direction == "long"
                            else entry_px * (1 + TR_SL_PCT / 100))
                print(f"\n  {sym} {direction.upper()}")
                print(f"    Entry: {entry_px}  Last: {last}  Peak: {peak_px}")
                print(f"    PnL:  {pnl_pct:+.2f}%  Trail reversal: {rv_pct:.2f}%")
                print(f"    Hard SL: {sl_price:.3f}  Age: {age_h:.1f}h / {TR_HOLD_HOURS}h")
            else:
                print(f"\n  {sym} {direction.upper()} entry={entry_px} (no live price)")
    else:
        print("  No open positions.")

    # Show scan
    candidates = _load_scan()
    if candidates:
        print(f"\n  SCANNER (top 5):")
        for c in candidates[:5]:
            flag = "✓" if (abs(D(str(c.get("chg24h_pct",0)))) >= TR_MIN_CHG and
                           D(str(c.get("continuity",0))) >= TR_MIN_CONT and
                           D(str(c.get("spread_bps",99))) <= TR_MAX_SPREAD) else " "
            print(f"  {flag} {c['symbol']:13} {c['dir']:5} "
                  f"{c['chg24h_pct']:+.2f}% cont={c['continuity']:.2f} "
                  f"spread={c['spread_bps']:.2f}bps")
    print(f"{'='*60}\n")


# ─── Close all ────────────────────────────────────────────────────────────────
def close_all(state: dict):
    for sym, pos in list(state["positions"].items()):
        ok = _close_position(sym, pos["direction"], "manual_close_all")
        if ok:
            state["positions"].pop(sym, None)
    return state


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    args = sys.argv[1:]
    dry_run      = "--dry-run" in args
    status_only  = "--status" in args
    close_only   = "--close-all" in args
    monitor_only = "--monitor-only" in args   # reconcile + exits, never open
    sl_watch     = "--sl-watch" in args        # fast GAP backstop only (no scan/open/trail)

    # Fail-closed KILL switch: touch data/TREND_RIDER_KILL to stop all trading.
    if KILL_FILE.exists():
        log.info("KILL switch present (data/TREND_RIDER_KILL) — no trading")
        return

    state = _load_state()
    state = _reset_daily_if_needed(state)

    if status_only:
        state = _reconcile_state(state)
        _save_state(state)
        print_status(state)
        return

    if close_only:
        state = close_all(state)
        _save_state(state)
        log.info("All rider positions closed.")
        return

    # SL-watch: fast GAP backstop only — no scan, no trail, no open. Tight interval.
    if sl_watch:
        state = _gap_stop_watch(state)
        _save_state(state)
        return

    # Monitor-only: reconcile + check exits, never scan/open. Safe for scheduling.
    if monitor_only:
        state = _reconcile_state(state)
        _save_state(state)
        if state["positions"]:
            log.info("Monitor-only: %d open positions...", len(state["positions"]))
            state = _check_exits(state)
            _save_state(state)
        else:
            log.info("Monitor-only: no open positions")
        print_status(state)
        return

    # 1. Run scanner to refresh scan file
    log.info("Refreshing scan...")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "scanner", str(PROJECT / "scripts" / "sodex_trend_scanner.py"))
        scanner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scanner)
        scanner.main()
    except Exception as e:
        log.warning("Scanner refresh failed: %s — using cached data", e)

    # 2. Reconcile with exchange truth (adopt unmanaged, drop closed)
    state = _reconcile_state(state)
    _save_state(state)

    # 3. Monitor existing positions (check exits)
    if state["positions"]:
        log.info("Monitoring %d open positions...", len(state["positions"]))
        state = _check_exits(state)
        _save_state(state)

    # 4. Open new positions if room
    if len(state["positions"]) < TR_MAX_POS:
        candidates = _load_scan()
        filtered = _filter_candidates(candidates)
        if filtered:
            log.info("Candidates passing entry filter: %d", len(filtered))
            for c in filtered[:TR_MAX_POS]:
                log.info("  → %s %s chg=%.2f%% cont=%.2f spread=%.2fbps",
                         c["symbol"], c["dir"], c["chg24h_pct"],
                         c["continuity"], c["spread_bps"])
            state = _open_new_positions(state, filtered, dry_run=dry_run)
            _save_state(state)
        else:
            log.info("No candidates pass entry filter (US session / continuity / chg / spread)")
    else:
        log.info("Max positions (%d) held — skip open", TR_MAX_POS)

    print_status(state)


if __name__ == "__main__":
    main()
