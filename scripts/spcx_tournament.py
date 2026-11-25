#!/usr/bin/env python3
"""
SPCX RWA Tournament Trader — Round 1: SpaceX
Target: $5,000 volume → Pool 2 ($10) + Pool 3 (lucky draw)
Strategy: Maker buy & sell di SPCX-USD, rotasi order, akumulasi volume
Fee: 0.012% maker | Spread: ~0.006% | Net loss: ~0.018%/RT
Runs until June 19 17:00 UTC or $5,000 volume reached
"""

import subprocess, json, os, sys, time, logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from decimal import Decimal, getcontext
from secrets import SystemRandom

getcontext().prec = 28
RNG = SystemRandom()
UTC = timezone.utc
D = Decimal

# ── Config ──
PAIR = "SPCX-USD"
ORDER_SIZE_USD = D("80")      # per order (depth ~$775 safe)
MIN_SPREAD = D("0.05")       # skip kalau spread > 5% (naik dari 0.02% — SPCX bisa 0.02-0.03%)
TARGET_VOLUME = D("5000")    # stop setelah $5K
MAX_POSITION = D("200")      # max notional open per side
DEADLINE = datetime(2026, 6, 19, 17, 0, 0, tzinfo=UTC)
LOG_FILE = "logs/spcx_tournament.log"
PROJECT = Path(__file__).resolve().parent.parent
SAFETY_HALT_FILE = PROJECT / "data" / "SAFETY_HALT"
PNL_HALT_FILE = PROJECT / "data" / "PNL_HALT"

# ── Setup ──
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)sZ %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)]
)
logging.Formatter.converter = time.gmtime


def live_order_blocked() -> str | None:
    if datetime.now(UTC) >= DEADLINE:
        return "TOURNAMENT_DEADLINE_PASSED"
    if SAFETY_HALT_FILE.exists():
        return "SAFETY_HALT"
    if PNL_HALT_FILE.exists():
        return "PNL_HALT"
    return None


def load_env_file(env: dict[str, str], path: Path = PROJECT / ".env") -> dict[str, str]:
    if not path.exists():
        return env
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env

def sodex(args: list[str], timeout: int = 30) -> dict:
    """Call bin/sodex CLI, return parsed JSON."""
    env = load_env_file(os.environ.copy())
    cmd = [str(PROJECT / "bin" / "sodex")] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        if r.returncode != 0:
            logging.warning("sodex error: %s", r.stderr.strip()[:150])
            return {}
        out = r.stdout.strip()
        if not out:
            return {}
        data = json.loads(out)
        return data[0] if isinstance(data, list) and data else data
    except Exception as e:
        logging.warning("sodex exception: %s", e)
        return {}

def place_order(side: str, price: str, qty: str) -> dict:
    """Place limit order on SPCX-USD perps."""
    blocked = live_order_blocked()
    if blocked:
        logging.error("SPCX live order blocked: %s", blocked)
        return {}
    return sodex([
        "orders", "place", "perps",
        "--symbol", "SPCX-USD",
        "--side", side,
        "--price", price,
        "--qty", qty,
        "--type", "limit",
        "--tif", "gtc",
        "--format", "json"
    ], timeout=20)

def cancel_order(oid: str):
    """Cancel order by ID."""
    sodex([
        "orders", "cancel", "perps",
        "--symbol-id", "81",  # SPCX-USD
        "--order-id", oid,
        "--cl-ord-id", f"spcx-t-{int(time.time())}"
    ], timeout=15)

def list_orders() -> list[dict]:
    """List open perps orders."""
    j = sodex(["orders", "list", "perps", "--format", "json"], timeout=15)
    if isinstance(j, list):
        return j
    return [j] if j else []

def get_book() -> dict | None:
    """Get SPCX-USD orderbook."""
    j = sodex(["orderbook", "perps", "SPCX-USD", "--depth", "3", "--format", "json"], timeout=15)
    if j and "bids" in j and j["bids"] and j["asks"]:
        return j
    return None

def main():
    logging.info("🚀 SPCX Tournament Trader START — target $%s vol", TARGET_VOLUME)
    total_vol = D("0")
    iteration = 0
    orders_placed = 0
    orders_filled = 0
    
    try:
        while True:
            iteration += 1
            now = datetime.now(UTC)
            
            # Check deadline
            if now >= DEADLINE:
                logging.info("⏰ DEADLINE reached — stopping")
                break
            if total_vol >= TARGET_VOLUME:
                logging.info("🎯 TARGET $%s reached! Total vol: $%s", TARGET_VOLUME, total_vol)
                break
            
            # Get orderbook
            bk = get_book()
            if not bk:
                time.sleep(2)
                continue
            
            best_bid = D(bk["bids"][0]["price"])
            best_ask = D(bk["asks"][0]["price"])
            mid = (best_bid + best_ask) / D("2")
            spread_pct = (best_ask - best_bid) / mid * D("100")
            
            if spread_pct > MIN_SPREAD:
                logging.info("Spread %.4f%% > %.2f%% — skip", float(spread_pct), float(MIN_SPREAD))
                time.sleep(3)
                continue
            
            # Check open orders
            open_orders = list_orders()
            spcx_orders = [o for o in open_orders if "SPCX" in str(o.get("symbol", ""))]
            
            # Count fills
            for o in spcx_orders:
                exec_qty = D(str(o.get("executedQty", 0)))
                if exec_qty > 0:
                    px = D(str(o.get("price", 0)))
                    vol = px * exec_qty
                    total_vol += vol
                    orders_filled += 1
            
            # Cancel stale orders (>60s)
            now_ts = time.time()
            for o in spcx_orders:
                oid = str(o.get("orderID", ""))
                # Simple age tracking via order count — cancel if we have >4 orders
                if len(spcx_orders) > 4:
                    cancel_order(oid)
                    spcx_orders = [x for x in spcx_orders if str(x.get("orderID")) != oid]
            
            # Place new orders if < 4 open
            active_count = len([o for o in spcx_orders if float(o.get("executedQty", 0)) == 0])
            if active_count < 4:
                # Alternate buy/sell
                side = "buy" if iteration % 2 == 0 else "sell"
                
                # Price slightly inside spread for better fill
                if side == "buy":
                    px = best_bid + (best_ask - best_bid) * D("0.3")
                else:
                    px = best_ask - (best_ask - best_bid) * D("0.3")
                
                qty = ORDER_SIZE_USD / px
                px_str = f"{float(px):.2f}"
                qty_str = f"{float(qty):.2f}"
                
                result = place_order(side, px_str, qty_str)
                oid = result.get("orderID", 0)
                if oid and oid != 0 and oid != "0":
                    orders_placed += 1
            
            # Progress every 30 iterations
            if iteration % 30 == 0:
                remaining = TARGET_VOLUME - total_vol
                hours_left = max(0, (DEADLINE - now).total_seconds() / 3600)
                rate = float(total_vol) / max(1.0, (now - datetime(2026,6,15,0,0,0,tzinfo=UTC)).total_seconds() / 3600)
                logging.info("📊 Iter#%d | Vol: $%.2f/$%s | Rate: $%.0f/h | Left: $%.0f | Hours: %.1f",
                           iteration, float(total_vol), TARGET_VOLUME, float(rate), float(remaining), hours_left)
            
            time.sleep(RNG.uniform(3, 8))
    
    except KeyboardInterrupt:
        logging.info("⏹ Stopped by user")
    finally:
        # Cancel all open SPCX orders
        for o in list_orders():
            if "SPCX" in str(o.get("symbol", "")):
                cancel_order(str(o.get("orderID", "")))
        logging.info("🏁 SPCX Tournament Trader STOP | Vol: $%.2f | Orders: %d placed / %d filled",
                    float(total_vol), orders_placed, orders_filled)

if __name__ == "__main__":
    main()
