#!/usr/bin/env python3
"""PAPER TEST MULTI-VENUE - Hyperliquid & Aster (paralel terisolasi).

Perbandingan apples-to-apples: SINYAL IDENTIK (Binance 1h, momentum LONG
regime, sama dengan realwide), dieksekusi SIMULASI di venue berbeda dengan
biaya & spread venue masing-masing. Jawaban ilmiah: venue mana yang paling
membantu mencapai target >=0.7% wallet.

Arsitektur:
  - Sinyal: Binance 1h OHLCV (close > SMA50 > SMA200, momentum 24h > 0)
  - Eksekusi: harga venue live (mark/last) + spread dari book nyata
  - Biaya: fee venue (HL taker 0.045% / Aster taker 0.04%)
  - Exit: TP 4% / SL 2% (t=0) / time-stop 30h / lev 3x - IDENTIK realwide
  - State: data/paper_test_{venue}_state.json - TERPISAH per venue
  - Service: anantara-paper-hyperliquid / anantara-paper-aster

Run: python3 scripts/paper_test_multivenue.py --venue hyperliquid --loop --interval 300
     python3 scripts/paper_test_multivenue.py --venue aster --loop --interval 300
PAPER ONLY - tidak ada order nyata, read-only API, spread dihitung dari book.
"""
from __future__ import annotations
import os
import argparse, json, os, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
# Denominator from verified exchange sync / service environment.
REAL_WALLET = float(os.environ.get("SODEX_TOTAL_WALLET", "108.10"))
TARGET = 0.008

# -- BINANCE SIGNAL SOURCE (sama untuk semua venue) --
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
PAIRS = ["BTC", "ETH", "SOL", "HYPE", "BNB", "XRP", "DOGE",
         "BCH", "ONDO", "LINK", "AAVE", "SUI", "UNI", "ADA", "TRX", "ENA",
         "ASTER", "PUMP", "LIT"]
BN_SYM = {p: p + "USDT" for p in PAIRS}

# -- GEOMETRY (identik realwide - long-only proven) --
TP_PCT = 0.040
SL_PCT = 0.020
TIME_STOP_H = 30
LEVERAGE = 3
NOTIONAL = 100.0
COOLDOWN_H = 12
MAX_TOTAL = 6
# Guard: harga eksekusi memakai MARK, spread di-charge terpisah (bukan di mark).
# Sanity cap: spread > 2% = data transient (book kosong / baru listing) -> pakai
# default 0.05% (5bps) agar tidak menghasilkan SL palsu (lesson: AAVE 5% spread
# transient 2026-09-02 -> 3 SL palsu -$35).
MAX_HALF_SPREAD = 0.02
FALLBACK_SPREAD = 0.0005

_TIMEOUT = 10
_CACHE = {}


def _http(method, url, data=None, headers=None):
    """HTTP dengan cache 15s utk data read-only."""
    cache_key = url + str(data)
    now = time.time()
    if cache_key in _CACHE and now - _CACHE[cache_key][0] < 15:
        return _CACHE[cache_key][1]
    req = urllib.request.Request(url, method=method, data=data,
                                 headers=headers or {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        body = json.loads(r.read().decode())
    _CACHE[cache_key] = (now, body)
    return body


def fetch_klines(symbol, interval="1h", limit=220):
    url = f"{BINANCE_KLINES}?symbol={symbol}&interval={interval}&limit={limit}"
    d = _http("GET", url, headers={'User-Agent': 'Mozilla/5.0'})
    c = np.array([float(x[4]) for x in d])
    return c


def sma(c, p):
    if len(c) < p:
        return np.full_like(c, np.nan)
    out = np.convolve(c, np.ones(p)/p, mode='valid')
    return np.concatenate([np.full(len(c)-len(out), np.nan), out])


def check_signal_hl(c):
    """Momentum LONG: close>SMA50>SMA200 & momentum 24h>0 (closed bar len-2)."""
    i = len(c) - 2
    if i < 200:
        return False
    s50 = sma(c, 50); s200 = sma(c, 200)
    if np.isnan(s50[i]) or np.isnan(s200[i]):
        return False
    mom24 = (c[i] - c[i-24]) / c[i-24] if i >= 24 else 0
    return bool(c[i] > s50[i] > s200[i] and mom24 > 0)


# =================== VENUE ADAPTERS ===================

def hl_price(coin):
    """Hyperliquid mark price via allMids, keyed langsung by coin name.
    FIX 2026-09-07 (bug kritis ditemukan triple-check): API HL berubah -
    allMids DULU pakai key index numerik ("0","1",...) hasil lookup di
    'meta' universe; SEKARANG key sudah nama coin langsung ("BTC","ETH",...).
    Kode lama selalu mids.get(str(idx)) -> None -> price=0.0 -> semua entry
    di-skip diam-diam (root cause HYPERLIQUID stuck 0 trade 5 hari sejak
    2026-09-02, walau 15/18 pair sinyal LONG aktif saat diverifikasi)."""
    mids = _http("POST", "https://api.hyperliquid.xyz/info",
                 data=json.dumps({"type": "allMids"}).encode())
    mid = float(mids.get(coin, 0) or 0)
    if mid <= 0:
        return None, None
    # spread dari l2Book (best bid/ask) -> half-spread cost
    book = _http("POST", "https://api.hyperliquid.xyz/info",
                 data=json.dumps({"type": "l2Book", "coin": coin}).encode())
    try:
        bids = book["levels"][0]; asks = book["levels"][1]
        best_bid = float(bids[0]["px"]); best_ask = float(asks[0]["px"])
        half_spread = (best_ask - best_bid) / 2
    except Exception:
        half_spread = FALLBACK_SPREAD
    # Sanity: spread transient jangan dihitung sebagai biaya eksekusi palsu.
    if half_spread > MAX_HALF_SPREAD:
        half_spread = FALLBACK_SPREAD
    return mid, half_spread


def aster_price(coin):
    """Aster (Binance-compatible fapi) mark price + best bid/ask."""
    base = "https://fapi.asterdex.com/fapi/v1"
    t = _http("GET", f"{base}/ticker/price?symbol={coin}USDT", headers={'User-Agent': 'Mozilla/5.0'})
    price = float(t.get("price", 0) or 0)
    try:
        bt = _http("GET", f"{base}/ticker/bookTicker?symbol={coin}USDT", headers={'User-Agent': 'Mozilla/5.0'})
        bid = float(bt.get("bidPrice", 0) or 0)
        ask = float(bt.get("askPrice", 0) or 0)
        half_spread = (ask - bid) / 2 if bid and ask else FALLBACK_SPREAD
    except Exception:
        half_spread = FALLBACK_SPREAD
    if half_spread > MAX_HALF_SPREAD:
        half_spread = FALLBACK_SPREAD
    return price, half_spread


FEES = {"hyperliquid": {"taker": 0.00045, "maker": 0.00015},
        "aster": {"taker": 0.0004, "maker": 0.0}}
PRICE_FN = {"hyperliquid": hl_price, "aster": aster_price}


def get_price(venue, coin):
    fn = PRICE_FN.get(venue)
    if not fn:
        return None, None
    try:
        return fn(coin)
    except Exception:
        return None, None


# =================== STATE ===================

def state_path(venue):
    return PROJECT / "data" / f"paper_test_{venue}_state.json"


def load_state(venue):
    f = state_path(venue)
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return {"created": datetime.now(timezone.utc).isoformat(),
            "open": {}, "closed": [], "last_entry": {}, "total_pnl": 0.0,
            "n_trades": 0, "n_wins": 0, "n_below": 0}


def save_state(venue, st):
    path = state_path(venue)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def has_open_pair(st, pair):
    """Open-state keys include timestamp; compare the stored pair value."""
    return any(pos.get("pair") == pair for pos in st.get("open", {}).values())


# =================== CYCLE ===================

def run_cycle(venue, st, do_entries=True):
    now = datetime.now(timezone.utc)
    fees = FEES[venue]
    prices = {}
    spreads = {}

    # harga semua pair (skip yang gagal)
    for p in PAIRS:
        px, half_spread = get_price(venue, p)
        if px:
            prices[p] = px
            spreads[p] = half_spread

    # -- exit management --
    for pid in list(st["open"].keys()):
        pos = st["open"][pid]
        coin = pos["pair"]
        cur = prices.get(coin)
        if not cur:
            continue
        hold_h = (now - datetime.fromisoformat(pos["entry_time"])).total_seconds() / 3600
        g = (cur - pos["entry_p"]) / pos["entry_p"]
        reason = None
        if g >= TP_PCT:
            reason = "TP"
        elif g <= -SL_PCT:
            reason = "SL"
        elif hold_h >= TIME_STOP_H:
            reason = "TIME_30h"
        if reason:
            # net PnL: gross - taker exit fee - half-spread cost (exit)
            net = g - fees["taker"] - spreads.get(coin, 0.0002)
            pnl_usd = net * NOTIONAL * LEVERAGE
            pnl_usd -= fees["taker"] * NOTIONAL * LEVERAGE  # + fee entry di bawah
            st["closed"].append({
                "venue": venue, "pair": coin, "direction": "LONG",
                "entry_p": pos["entry_p"], "exit_p": cur,
                "entry_time": pos["entry_time"],
                "exit_time": now.isoformat(), "exit_reason": reason,
                "gross_pct": g, "net_pct": net,
                "fee": fees["taker"], "half_spread": spreads.get(coin, 0.0002),
                "hold_h": round(hold_h, 1), "pnl_usd": round(pnl_usd, 2),
            })
            st["total_pnl"] += pnl_usd
            st["n_trades"] += 1
            if pnl_usd > 0:
                st["n_wins"] += 1
            st["n_below"] += 1 if pnl_usd / REAL_WALLET < TARGET else 0
            del st["open"][pid]

    # -- entries (per 5 cycle) --
    if do_entries and len(st["open"]) < MAX_TOTAL:
        for p in PAIRS:
            if has_open_pair(st, p):
                continue
            # cooldown
            last = st["last_entry"].get(p, 0)
            if now.timestamp() - last < COOLDOWN_H * 3600:
                continue
            # sinyal
            try:
                c = fetch_klines(BN_SYM[p])
            except Exception:
                continue
            if not check_signal_hl(c):
                continue
            px = prices.get(p)
            if not px:
                continue
            # entry: market + fee taker + half-spread
            net_entry = -fees["taker"] * NOTIONAL * LEVERAGE
            st["open"][f"{p}_{int(now.timestamp())}"] = {
                "pair": p, "entry_p": px,
                "entry_time": now.isoformat(),
                "entry_fee": fees["taker"], "half_spread": spreads.get(p, 0.0002),
            }
            # estimasi entry cost masuk ke PnL saat close (di atas) - di sini hanya state
            st["last_entry"][p] = now.timestamp()
            break  # max 1 entry per cycle (bounded)

    save_state(venue, st)
    return {"open": len(st["open"]), "closed_total": len(st["closed"]), "prices": len(prices)}


def report(venue, st):
    n = st["n_trades"]
    total = st["total_pnl"]
    if n == 0:
        print(f"\n[{venue.upper()}] n=0 | PnL=$0.00 | collecting data... | open={len(st['open'])}")
        return
    roi = total / REAL_WALLET / n * 100
    print(f"\n[{venue.upper()}] n={n} | PnL=${total:+.2f} | "
          f"ROI={roi:+.3f}% (target 0.7%) | open={len(st['open'])} "
          f"| {'at target' if roi >= 0.7 else 'collecting'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--venue", choices=["hyperliquid", "aster"], required=True)
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()

    if a.status:
        st = load_state(a.venue)
        report(a.venue, st)
        for t in st["closed"][-5:]:
            print(f"    {t['pair']:6s} {t['exit_reason']:9s} {t['net_pct']*100:+5.2f}% ${t['pnl_usd']:+6.2f}")
        return

    st = load_state(a.venue)
    if not a.loop:
        r = run_cycle(a.venue, st, do_entries=True)
        report(a.venue, st)
        return

    cycle = 0
    while True:
        try:
            do_entries = (cycle % 5 == 0)
            run_cycle(a.venue, st, do_entries=do_entries)
            report(a.venue, st)
        except Exception as e:
            print(f"[{a.venue}] cycle error: {e}", flush=True)
        time.sleep(a.interval)
        cycle += 1


if __name__ == "__main__":
    main()
