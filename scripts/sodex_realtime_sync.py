#!/usr/bin/env python3
"""SoDEX REAL-TIME SYNC v2 — sumber kebenaran definitif, menggantikan CLI cacat.

ROOT CAUSE (ditemukan 2026-09-04 via `strings bin/sodex`):
CLI `bin/sodex positions` (build Mei 2026) memanggil endpoint LAMA/salah yang
selalu return null pasca migrasi "SoDEX Layer 1" — meski posisi NYATA ada.
CLI `balance` ternyata AKURAT (endpoint sama dgn yang benar di bawah).

ENDPOINT BENAR (reverse-engineered dari binary CLI, diverifikasi manual match
100% dgn dashboard resmi sodex.com, 2026-09-04 20:15 WIB):
  GET {PERPS_BASE}/accounts/{address}/positions
  GET {PERPS_BASE}/accounts/{address}/balances
  GET {PERPS_BASE}/accounts/{address}/orders
  GET {SPOT_BASE}/accounts/{address}/balances

Read-only murni. TIDAK PERNAH mengirim order. Aman dijalankan kapan saja,
termasuk sebagai health-check berkala.
"""
from __future__ import annotations
import json, os, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
PERPS_BASE = os.environ.get("SODEX_PERPS_URL", "https://mainnet-gw.sodex.dev/api/v1/perps")
SPOT_BASE = PERPS_BASE.replace("/perps", "/spot")
SPOT_TICKERS = f"{SPOT_BASE}/markets/tickers"
PERPS_TICKERS = f"{PERPS_BASE}/markets/tickers"
PERPS_MARK_PRICES = f"{PERPS_BASE}/markets/mark-prices"
ADDRESS = os.environ.get("SODEX_ADDRESS", "").lower()
SNAP_FILE = PROJECT / "data" / "sodex_real_sync_snapshot.json"


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "anantara-sync/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _addr(address=None):
    a = (address or ADDRESS).lower()
    if not a:
        raise ValueError("SODEX_ADDRESS tidak diset (source .env dulu)")
    return a


def real_perps_positions(address=None):
    d = _get(f"{PERPS_BASE}/accounts/{_addr(address)}/positions")
    if d.get("code") != 0:
        raise RuntimeError(f"positions API error: {d}")
    return [p for p in d.get("data", {}).get("positions", []) if p.get("active", True)]


def real_perps_balance(address=None):
    d = _get(f"{PERPS_BASE}/accounts/{_addr(address)}/balances")
    if d.get("code") != 0:
        raise RuntimeError(f"balances API error: {d}")
    return d.get("data", {}).get("balances", [])


def real_perps_orders(address=None):
    d = _get(f"{PERPS_BASE}/accounts/{_addr(address)}/orders")
    if d.get("code") != 0:
        raise RuntimeError(f"orders API error: {d}")
    return d.get("data", {}).get("orders", [])


def real_spot_balance(address=None):
    d = _get(f"{SPOT_BASE}/accounts/{_addr(address)}/balances")
    if d.get("code") != 0:
        raise RuntimeError(f"spot balances API error: {d}")
    return d.get("data", {}).get("balances", [])


def _ticker_rows(url):
    raw = _get(url)
    data = raw.get("data", raw) if isinstance(raw, dict) else raw
    rows = data.get("tickers", data) if isinstance(data, dict) else data
    return rows or []


def real_perps_markets():
    """Venue-native perps market data: mark, index, bid/ask, funding.

    Endpoint /markets/tickers is public and read-only. It carries markPrice,
    indexPrice, fundingRate and top-of-book, which the SHORT-BEAR venue guard
    needs to stop relying on the Binance spot proxy.
    """
    marks = {}
    for t in _ticker_rows(PERPS_TICKERS):
        sym = str(t.get("symbol") or "")
        if not sym:
            continue
        marks[sym] = {
            "markPrice": _f(t.get("markPrice")),
            "indexPrice": _f(t.get("indexPrice")),
            "lastPx": _f(t.get("lastPx")),
            "bidPx": _f(t.get("bidPx")),
            "askPx": _f(t.get("askPx")),
            "fundingRate": _f(t.get("fundingRate")),
            "nextFundingTime": t.get("nextFundingTime"),
            "openInterest": _f(t.get("openInterest")),
            "quoteVolume": _f(t.get("quoteVolume")),
        }
    return marks


def _f(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and abs(out) != float("inf") else None


def _prev_snapshot():
    try:
        return json.loads(SNAP_FILE.read_text())
    except Exception:
        return {}


def _resolve_unpriced_fallback(coin, perps_marks, prev_marks):
    """Best-effort *reported* valuation for a holding with no spot ticker.

    Returns (price, source) or (None, reason). Never invents a price: the value
    must come from a venue-native perps mark or the previous priced snapshot.
    """
    for prefix in ("a", "v"):
        if coin.startswith(prefix):
            candidate = coin[len(prefix):]
            for sym in (f"{candidate}-USD", f"{candidate}USD"):
                row = (perps_marks or {}).get(sym)
                if row and row.get("markPrice"):
                    return row["markPrice"], f"perps_mark:{sym}"
    for row in prev_marks or []:
        if row.get("coin") == coin and row.get("price"):
            return row["price"], "carry_forward_prev_snapshot"
    return None, "no_native_market"



def _spot_marked_equity(spot_balances, perps_marks=None, prev_marks=None):
    """Value spot holdings conservatively at current bid; resolve dust via native marks.

    Fail-closed contract preserved: a holding is reported in `unpriced` unless a
    real venue price exists (spot bid, perps mark, or carried-forward snapshot).
    """
    raw = _get(SPOT_TICKERS)
    data = raw.get("data", raw) if isinstance(raw, dict) else raw
    tickers = data.get("tickers", data) if isinstance(data, dict) else data
    by_symbol = {str(t.get("symbol")): t for t in (tickers or [])}
    marks, unpriced = [], []
    total = 0.0
    for bal in spot_balances:
        coin = str(bal.get("coin", ""))
        qty = float(bal.get("total") or 0)
        if qty <= 0:
            continue
        if coin == "vUSDC":
            value = qty
            marks.append({"coin": coin, "qty": qty, "price": 1.0,
                          "usd_value": value, "source": "par"})
            total += value
            continue
        candidates = [f"{coin}_vUSDC", f"{coin.replace('.', '')}_vUSDC"]
        ticker = next((by_symbol.get(s) for s in candidates if by_symbol.get(s)), None)
        bid = float((ticker or {}).get("bidPx") or 0)
        if ticker and bid > 0:
            value = qty * bid
            marks.append({"coin": coin, "qty": qty, "symbol": str(ticker.get("symbol")),
                          "price": bid, "usd_value": value, "source": "bid"})
            total += value
            continue
        fallback_price, fallback_source = _resolve_unpriced_fallback(
            coin, perps_marks, prev_marks)
        if fallback_price:
            value = qty * fallback_price
            marks.append({"coin": coin, "qty": qty, "price": fallback_price,
                          "usd_value": value, "source": fallback_source})
            total += value
            continue
        unpriced.append({"coin": coin, "qty": qty, "reason": fallback_source})
    return total, marks, unpriced



def full_sync(address=None, verbose=True):
    """Snapshot lengkap dari SEMUA endpoint benar. Ini source of truth."""
    addr = _addr(address)
    out = {"generated_utc": datetime.now(timezone.utc).isoformat(), "address": addr}

    try:
        out["perps_positions"] = real_perps_positions(addr)
    except Exception as e:
        out["perps_positions_error"] = str(e)

    try:
        bal = real_perps_balance(addr)
        out["perps_balance"] = next((b for b in bal if b["coin"] == "vUSDC"), None)
    except Exception as e:
        out["perps_balance_error"] = str(e)

    try:
        orders = real_perps_orders(addr)
        out["perps_open_orders"] = orders
    except Exception as e:
        out["perps_orders_error"] = str(e)

    try:
        spot_bal = real_spot_balance(addr)
        out["spot_balances"] = spot_bal
        out["spot_vusdc"] = next((b for b in spot_bal if b["coin"] == "vUSDC"), None)
        try:
            perps_marks = real_perps_markets()
            out["perps_marks"] = perps_marks
        except Exception as e:
            perps_marks = {}
            out["perps_marks_error"] = str(e)
        try:
            prev = _prev_snapshot()
            equity, marks, unpriced = _spot_marked_equity(
                spot_bal, perps_marks, prev.get("spot_marks"))
            out["spot_equity_usd"] = equity
            out["spot_marks"] = marks
            out["spot_unpriced"] = unpriced
        except Exception as e:
            out["spot_mark_error"] = str(e)
    except Exception as e:
        out["spot_balance_error"] = str(e)

    # Timer overlap can run realsync/watchdog/monitor concurrently. A fixed
    # `snap.tmp` races: one process may replace it while another is about to.
    tmp = SNAP_FILE.with_name(f"{SNAP_FILE.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(out, indent=1))
    tmp.replace(SNAP_FILE)

    if verbose:
        print(f"=== SODEX REAL SYNC — {addr} — {out['generated_utc'][:19]} UTC ===")
        pp = out.get("perps_positions", [])
        if pp:
            print(f"Posisi perps TERBUKA: {len(pp)}")
            for p in pp:
                print(f"  {p['symbol']} size={p['size']} entry={p['avgEntryPrice']} "
                      f"lev={p['leverage']}x realizedPnL=${p.get('realizedPnL','?')}")
        else:
            print("Posisi perps TERBUKA: 0 (bersih)")
        pb = out.get("perps_balance")
        if pb:
            print(f"Balance perps vUSDC: ${float(pb['total']):.4f}")
        sv = out.get("spot_vusdc")
        if sv:
            print(f"Balance spot vUSDC:  ${float(sv['total']):.4f}")
        po = out.get("perps_open_orders", [])
        print(f"Order terbuka: {len(po)}")
    return out


def main():
    full_sync()
    print(f"\nSnapshot: {SNAP_FILE}")


if __name__ == "__main__":
    main()
