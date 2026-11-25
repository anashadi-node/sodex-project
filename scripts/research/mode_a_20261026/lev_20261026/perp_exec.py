#!/usr/bin/env python3
"""PRAREG-38 — eksekutor perp SoDEX (paper default; live terkunci).

Aturan keras:
  * default paper: tidak pernah memanggil perintah order venue.
  * live butuh: LIVE_ARMED.json (armed, hash engine cocok), CONFIRM_LIVE=YES,
    receipt selftest testnet < 7 hari, drawdown < batas, dan flag eksplisit --live.
  * fill dianggap sah HANYA bila orderID != 0/None, status FILLED/PARTIALLY_FILLED,
    dan filledQuantity > 0. Selain itu -> AmbiguousFill (reconcile via positions), bukan sukses.
  * kunci privat hanya dari environment; tidak pernah dicetak/ditulis.
"""
from __future__ import annotations
import argparse, fcntl, hashlib, json, os, re, subprocess, sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
BIN = os.path.join(ROOT, "bin", "sodex")
SEC = os.path.join(ROOT, "secrets")
LEDGER = os.path.join(os.path.dirname(__file__), "perp_ledger.jsonl")
S, M, LP = 0.0, 1.0, 1.5           # PRAREG-39 Q1 (perp-only, Lp 1,5)
MIN_NOTIONAL = 10.0
FEE_TAKER = 0.0004
DRIFT_CAP = 0.02                     # 2% dari target -> tidak perlu order
DD_LIMIT = 15.0


class Block(RuntimeError): pass
class AmbiguousFill(RuntimeError): pass


def _rd(p):
    return [json.loads(x) for x in open(p) if x.strip()] if os.path.exists(p) else []


def network():
    return "testnet" if os.environ.get("SODEX_TESTNET") == "1" else "mainnet"


def account_id(address=None):
    """Oracle: tanya venue, jangan hardcode. mainnet 180570 != testnet 57462."""
    a = address or os.environ.get("SODEX_ADDRESS") or load_env().get("SODEX_ADDRESS")
    j = cli(["account-id", a, "--format", "json"])
    return int(j["aid"])


def cli(args, timeout=25, testnet=None):
    pre = ["--testnet"] if (testnet if testnet is not None else network() == "testnet") else []
    r = subprocess.run([BIN] + pre + args, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise Block(f"CLI gagal rc={r.returncode}: {(r.stderr or r.stdout)[:300]}")
    try:
        return json.loads(r.stdout)
    except Exception:
        raise Block(f"CLI bukan JSON: {r.stdout[:200]}")


def specs():
    m = cli(["markets", "perps", "--format", "json"])
    return {x["name"]: x for x in m if x.get("status") == "TRADING"}


def marks(syms):
    t = cli(["tickers", "perps", "--format", "json"])
    out = {}
    for r in t:
        if r["symbol"] in syms:
            px = r.get("markPrice") or r.get("indexPrice")
            if px: out[r["symbol"]] = float(px)
    return out


def qty_for(notional, price, spec):
    step = float(spec["stepSize"]); q = int(notional / price / step) * step
    return round(q, 8)


def plan(equity, syms=("BTC-USD", "ETH-USD", "XAUT-USD"), weights=None, lp=None):
    lp = float(lp or LP)
    sp = specs(); px = marks(syms)
    gross_cap = equity * lp
    w = weights or {s: 1.0 / len(syms) for s in syms}
    out, used = [], 0.0
    for s in syms:
        if s not in sp or s not in px: continue
        target = gross_cap * w[s]
        n = min(target, gross_cap - used)
        if n < MIN_NOTIONAL: continue
        q = qty_for(n, px[s], sp[s])
        notional = q * px[s]
        if notional < MIN_NOTIONAL or q <= 0: continue
        used += notional
        out.append({"symbol": s, "symbol_id": sp[s]["id"], "qty": q, "price": px[s],
                    "notional": round(notional, 2), "step": sp[s]["stepSize"],
                    "min_notional": float(sp[s]["minNotional"]), "leverage": lp})
    return {"equity": equity, "gross_cap": round(gross_cap, 2), "orders": out,
            "used": round(used, 2), "margin": round(used / lp, 2), "lp": lp}


def load_env():
    kv = {}
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p, errors="ignore"):
            m = re.match(r"^([A-Z0-9_]+)\s*=\s*(.*)$", line.strip())
            if m: kv[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return kv


def guard_live():
    armed = os.path.join(SEC, "LIVE_ARMED.json")
    if not os.path.exists(armed): raise Block("LIVE_ARMED.json tidak ada")
    a = json.load(open(armed))
    if not a.get("armed"): raise Block("armed=false")
    if a.get("not_before") and datetime.now(timezone.utc).date().isoformat() < a["not_before"]:
        raise Block(f"belum waktunya (not_before {a['not_before']})")
    if os.environ.get("CONFIRM_LIVE", "") != "YES": raise Block("CONFIRM_LIVE != YES")
    rc = os.path.join(SEC, "SELFTEST_OK.json")
    if not os.path.exists(rc): raise Block("belum ada receipt selftest testnet")
    r = json.load(open(rc))
    if r.get("testnet") is not True or r.get("ok") is not True: raise Block("receipt selftest tidak valid")
    ts = datetime.fromisoformat(r["utc"])
    if datetime.now(timezone.utc) - ts > timedelta(days=7): raise Block("receipt selftest > 7 hari")
    led = _rd(LEDGER)
    eqs = [x["equity_after"] for x in led if x.get("kind") == "fill" and x.get("equity_after")]
    if eqs:
        peak = max(eqs); dd = (eqs[-1] / peak - 1) * 100
        if dd <= -DD_LIMIT: raise Block(f"drawdown {dd:.2f}% <= -{DD_LIMIT}%")
    return a


HISTORY_LOOKUP = None   # diisi tes; None -> pakai jaringan


def order_history(oid):
    """Status order sebenarnya. Respons `orders place` TIDAK memuat status/fill."""
    env = load_env()
    addr = os.environ.get("SODEX_ADDRESS") or env.get("SODEX_ADDRESS")
    base = "https://testnet-gw.sodex.dev" if network() == "testnet" else "https://mainnet-gw.sodex.dev"
    out = subprocess.run(["curl", "-s", "-m", "20", f"{base}/api/v1/perps/accounts/{addr}/orders/history"],
                         capture_output=True, text=True).stdout
    try:
        rows = json.loads(out)["data"]
    except Exception:
        return None
    for r in rows:
        if str(r.get("orderID")) == str(oid):
            return r
    return None


def verify_fill(resp, lookup=None):
    """Fill phantom: rc=0 + orderID 0 adalah kelas bug paling berbahaya. Fail-closed.

    Respons place venue hanya berisi orderID + status kosong; status/fill WAJIB
    dibaca dari order history. Menganggap status kosong sebagai sukses = bug.
    """
    lookup = lookup or HISTORY_LOOKUP or order_history
    rows = resp if isinstance(resp, list) else [resp]
    ok = []
    for r in rows:
        if not isinstance(r, dict):
            raise AmbiguousFill(f"baris bukan objek: {r!r}")
        oid = r.get("orderID") or r.get("orderId")
        if not oid or int(oid) == 0:
            raise AmbiguousFill(f"orderID kosong/nol: {r}")
        st = lookup(oid)
        if not st:
            raise AmbiguousFill(f"order {oid} tidak ada di history")
        status = (st.get("status") or "").upper()
        fq = float(st.get("executedQty") or st.get("filledQuantity") or 0)
        if status not in ("FILLED", "PARTIALLY_FILLED"):
            raise AmbiguousFill(f"status {status!r}: {st}")
        if fq <= 0:
            raise AmbiguousFill(f"executedQty 0: {st}")
        ok.append(st)
    if not ok:
        raise AmbiguousFill("respons kosong")
    return ok


def apply(p, live=False, testnet=False):
    if live and testnet: raise Block("live+testnet tidak sah: testnet tidak pernah live")
    if live and network() == "testnet": raise Block("SODEX_TESTNET=1 -> tolak mode live mainnet")
    if live: guard_live()
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(os.path.join(os.path.dirname(LEDGER), ".perp.lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        done = [(x.get("symbol"), round(float(x.get("qty", 0)), 8)) for x in _rd(LEDGER) if x.get("kind") == "fill"]
        written = []
        for o in p["orders"]:
            if (o["symbol"], round(o["qty"], 8)) in done: continue
            if live or testnet:
                resp = cli(["orders", "place", "perps", "--symbol", o["symbol"], "--side", "buy",
                            "--type", "limit", "--price", str(o["price"]), "--qty", str(o["qty"]),
                            "--tif", "ioc", "--format", "json"], timeout=40, testnet=testnet)
                fills = verify_fill(resp)
                rec = {"kind": "fill", "mode": "TESTNET" if testnet else "LIVE", "utc": datetime.now(timezone.utc).isoformat(),
                       "symbol": o["symbol"], "qty": float(fills[0].get("filledQuantity", o["qty"])),
                       "price": o["price"], "orderID": fills[0]["orderID"], "fee_bps": FEE_TAKER * 1e4}
            else:
                rec = {"kind": "fill", "mode": "PAPER", "utc": datetime.now(timezone.utc).isoformat(),
                       "symbol": o["symbol"], "qty": o["qty"], "price": o["price"],
                       "notional": o["notional"], "fee": round(o["notional"] * FEE_TAKER, 6),
                       "orderID": None, "note": "SIMULASI lokal — bukan order venue"}
            rec["equity_after"] = round(p["equity"] - sum(x.get("fee", 0) for x in written), 2)
            open(LEDGER, "a").write(json.dumps(rec, sort_keys=True) + "\n"); written.append(rec)
    return {"ditulis": written, "n": len(written)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "apply", "status"])
    ap.add_argument("--equity", type=float, default=60.0, help="ekuitas akun PERP (bukan total wallet)")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--lp", type=float, default=LP, help="leverage perp (Q1=1.5)")
    ap.add_argument("--testnet", action="store_true", help="order nyata di TESTNET (bukan simulasi)")
    a = ap.parse_args()
    try:
        if a.cmd == "plan":
            print(json.dumps(plan(a.equity, lp=a.lp), indent=1))
        elif a.cmd == "apply":
            p = plan(a.equity, lp=a.lp); r = apply(p, a.live, a.testnet)
            print(json.dumps({"orders": len(p["orders"]), "ditulis": r["n"],
                              "mode": "TESTNET" if a.testnet else ("LIVE" if a.live else "PAPER")}, indent=1))
        else:
            led = _rd(LEDGER)
            print(json.dumps({"n": len(led), "paper": sum(1 for x in led if x.get("mode") == "PAPER"),
                              "live": sum(1 for x in led if x.get("mode") == "LIVE")}, indent=1))
    except (Block, AmbiguousFill) as e:
        print(f"REFUSED: {e}", file=sys.stderr); sys.exit(3)
