#!/usr/bin/env python3
"""PROBE MIKRO mainnet — validasi jalur fill nyata, ukuran minimum venue.

Dasar approval: pengguna memilih opsi A ("Probe mikro mainnet ~$10 BTC-USD,
tutup < 60 detik, risiko < $0.10").

Pagar keras (semua wajib, fail-closed):
  * hanya mainnet; SODEX_TESTNET=1 -> tolak
  * secrets/LIVE_ARMED_PROBE.json wajib ada, armed=true, belum kedaluwarsa,
    simbol diizinkan, notional <= max_notional_usd (<= 15)
  * satu BUY + satu CLOSE reduce-only, tidak ada retry otomatis
  * fill sah hanya bila orderID>0, status FILLED/PARTIALLY_FILLED, filledQty>0
  * posisi wajib flat setelah close; kalau tidak -> PANIC (exit 4)
  * kunci hanya dari environment; tidak pernah dicetak

Pemakaian:
  python3 probe_live_micro.py --dry
  python3 probe_live_micro.py --execute
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
BIN = os.path.join(ROOT, "bin", "sodex")
ARMED = os.path.join(ROOT, "secrets", "LIVE_ARMED_PROBE.json")
LEDGER = os.path.join(os.path.dirname(__file__), "probe_ledger.jsonl")
SYMBOL = "BTC-USD"
HARD_CAP = 15.0


class Refuse(RuntimeError):
    pass


class NoFill(Refuse):
    pass


def _env():
    env = dict(os.environ)
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p, errors="ignore"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def cli(args, timeout=40):
    r = subprocess.run([BIN] + args, capture_output=True, text=True, timeout=timeout, env=_env())
    if r.returncode != 0:
        raise Refuse(f"CLI rc={r.returncode}: {(r.stderr or r.stdout)[:300]}")
    try:
        return json.loads(r.stdout)
    except Exception:
        raise Refuse(f"CLI bukan JSON: {r.stdout[:200]}")


def arm():
    if os.environ.get("SODEX_TESTNET") == "1":
        raise Refuse("SODEX_TESTNET=1 -> probe mainnet ditolak")
    if not os.path.exists(ARMED):
        raise Refuse("LIVE_ARMED_PROBE.json tidak ada")
    a = json.load(open(ARMED))
    if not a.get("armed"):
        raise Refuse("armed=false")
    exp = datetime.fromisoformat(a["expires_utc"])
    if datetime.now(timezone.utc) > exp:
        raise Refuse(f"arming kedaluwarsa {a['expires_utc']}")
    cap = float(a.get("max_notional_usd", 0))
    if not (0 < cap <= HARD_CAP):
        raise Refuse(f"max_notional_usd {cap} di luar batas keras {HARD_CAP}")
    if SYMBOL not in a.get("symbols", []):
        raise Refuse(f"{SYMBOL} tidak diizinkan arming")
    return a


def top():
    t = cli(["tickers", "perps", "--format", "json"])
    rows = t if isinstance(t, list) else t.get("data", [])
    for r in rows:
        if r.get("symbol") == SYMBOL:
            return float(r["bidPx"]), float(r["askPx"])
    raise Refuse("ticker BTC-USD tidak ditemukan")


def spec():
    m = cli(["markets", "perps", "--format", "json"])
    rows = m if isinstance(m, list) else m.get("data", [])
    for r in rows:
        if r.get("name") == SYMBOL:
            return float(r["stepSize"]), float(r["minNotional"])
    raise Refuse("spec BTC-USD tidak ditemukan")


def size(cap, ask):
    step, min_notional = spec()
    raw = (cap - 0.01) / ask
    qty = int(raw / step) * step
    qty = round(qty, 8)
    notional = qty * ask
    if qty <= 0 or notional < min_notional:
        raise Refuse(f"notional {notional:.2f} < minNotional {min_notional}")
    return qty, notional


def place(side, qty, price, reduce_only=False):
    args = ["orders", "place", "perps", "--symbol", SYMBOL, "--side", side,
            "--type", "limit", "--price", f"{price:.0f}", "--qty", f"{qty}",
            "--tif", "ioc", "--format", "json"]
    if reduce_only:
        args.append("--reduce-only")
    return cli(args)


def order_status(oid):
    addr = _env().get("SODEX_ADDRESS")
    url = f"https://mainnet-gw.sodex.dev/api/v1/perps/accounts/{addr}/orders/history"
    out = subprocess.run(["curl", "-s", "-m", "20", url], capture_output=True, text=True).stdout
    try:
        rows = json.loads(out)["data"]
    except Exception:
        raise Refuse(f"history bukan JSON: {out[:200]}")
    for r in rows:
        if str(r.get("orderID")) == str(oid):
            return r
    return None


def wait_fill(oid, tries=8, delay=0.5):
    import time
    last = None
    for _ in range(tries):
        r = order_status(oid)
        if r:
            last = r
            if (r.get("status") or "").upper() == "FILLED" and float(r.get("executedQty") or 0) > 0:
                return r
            if (r.get("status") or "").upper() in ("CANCELED", "REJECTED", "EXPIRED"):
                return r
        time.sleep(delay)
    return last


def verify(resp):
    rows = resp if isinstance(resp, list) else [resp]
    ok = []
    for r in rows:
        oid = r.get("orderID") or r.get("orderId")
        if not oid or int(oid) == 0:
            raise Refuse(f"orderID kosong/nol: {r}")
        st = wait_fill(oid)
        if not st:
            raise Refuse(f"order {oid} tidak ditemukan di history")
        status = (st.get("status") or "").upper()
        q = float(st.get("executedQty") or 0)
        if status != "FILLED" or q <= 0:
            raise NoFill(f"order {oid} {status} executedQty={q}")
        ok.append({"orderID": oid, "status": status, "filled": q,
                   "avgPrice": st.get("avgPrice") or st.get("price")})
    return ok


def positions():
    addr = _env().get("SODEX_ADDRESS")
    if not addr:
        raise Refuse("SODEX_ADDRESS tidak ada")
    url = f"https://mainnet-gw.sodex.dev/api/v1/perps/accounts/{addr}/positions"
    out = subprocess.run(["curl", "-s", "-m", "20", url], capture_output=True, text=True).stdout
    try:
        rows = json.loads(out)["data"]["positions"]
    except Exception:
        raise Refuse(f"positions bukan JSON: {out[:200]}")
    return [r for r in rows if float(r.get("size") or r.get("qty") or 0) != 0]


def trade_price(oid):
    addr = _env().get("SODEX_ADDRESS")
    url = f"https://mainnet-gw.sodex.dev/api/v1/perps/accounts/{addr}/trades"
    out = subprocess.run(["curl", "-s", "-m", "20", url], capture_output=True, text=True).stdout
    try:
        rows = json.loads(out)["data"]
    except Exception:
        return None
    for r in rows:
        if str(r.get("orderID")) == str(oid):
            return float(r.get("price"))
    return None


def log(rec):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    rec["utc"] = datetime.now(timezone.utc).isoformat()
    with open(LEDGER, "a") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--execute", action="store_true")
    a = ap.parse_args()
    if not (a.dry or a.execute):
        sys.exit(__doc__)
    try:
        cfg = arm()
        bid, ask = top()
        cap = min(float(cfg["max_notional_usd"]), HARD_CAP)
        qty, notional = size(cap, ask)
        fee = notional * 0.0004
        plan = {"symbol": SYMBOL, "qty": qty, "bid": bid, "ask": ask,
                "notional": round(notional, 2), "fee_est": round(fee, 4),
                "round_trip_cost_est": round(fee * 2 + (ask - bid) * qty, 4)}
        print(json.dumps(plan, indent=1))
        if a.dry:
            return
        before = positions()
        if before:
            raise Refuse(f"posisi sudah terbuka sebelum probe: {before}")

        buy = place("buy", qty, ask * 1.0005)
        try:
            bfill = verify(buy)
        except NoFill as e:
            left = positions()
            if left:
                place("sell", qty, bid * 0.999, reduce_only=True)
                log({"kind": "PANIC_PARTIAL", "positions": left, "detail": str(e)})
                print(f"PANIC: partial tanpa close otomatis: {left}", file=sys.stderr)
                sys.exit(4)
            log({"kind": "no_fill", "detail": str(e)})
            print(f"NO_FILL: {e}", file=sys.stderr)
            sys.exit(5)
        log({"kind": "open", "plan": plan, "fill": bfill, "raw": buy})

        sell = place("sell", qty, bid * 0.999, reduce_only=True)
        sfill = verify(sell)
        log({"kind": "close", "fill": sfill, "raw": sell})

        left = positions()
        if left:
            log({"kind": "PANIC", "positions": left})
            print(f"PANIC: posisi belum flat: {left}", file=sys.stderr)
            sys.exit(4)
        bp = trade_price(bfill[0]["orderID"]) or float(bfill[0]["avgPrice"] or 0)
        sp = trade_price(sfill[0]["orderID"]) or float(sfill[0]["avgPrice"] or 0)
        pnl = (sp - bp) * qty if bp and sp else None
        summary = {"opened": bfill, "closed": sfill, "flat": True,
                   "buy_price": bp, "sell_price": sp,
                   "gross_pnl": round(pnl, 6) if pnl is not None else None,
                   "notional": plan["notional"]}
        log({"kind": "summary", "summary": summary})
        print(json.dumps(summary, indent=1))
    except Refuse as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
