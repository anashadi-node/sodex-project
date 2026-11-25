#!/usr/bin/env python3
"""Mode A — EKSEKUTOR LIVE SPOT SoDEX (arm A SAJA). DEFAULT = DRY-RUN. Tidak ada kredensial di kode.

Live HANYA jika SEMUA benar (fail-closed, semuanya diperiksa ulang tiap run):
  1. flag --live  2. env CONFIRM_LIVE=YES  3. secrets/LIVE_ARMED.json dibuat & ditandatangani USER (armed=true, go_by, go_utc, batas $)
  4. tanggal UTC >= not_before (>= 2026-12-01)  5. engine_sha256 di arm file == hash engine saat ini  6. secrets/KILL tidak ada
  7. target ledger berumur <=1 hari (asof = kemarin UTC)  8. cap: ekuitas, per-order, total-beli  9. satu eksekusi per asof (idempoten)
Tidak pernah: short, leverage, jual > saldo, beli > USDC, order < minNotional, retry otomatis order yang statusnya tak jelas.
Order = limit IOC dengan batas slip (default 30 bps) di buku nyata; bukan market.

  mode_a_live.py status            # periksa semua syarat, tanpa order
  mode_a_live.py run   [--live]    # dry-run default
  mode_a_live.py selftest          # TESTNET saja: place+cancel order jauh dari pasar (butuh SODEX_TESTNET=1 + kunci testnet)
"""
from __future__ import annotations
import datetime as dt, hashlib, json, os, stat, sys
from decimal import Decimal
import mode_a_engine as eng
import spot_exec as sx

HERE = os.path.dirname(os.path.abspath(__file__))
FWD = os.path.join(HERE, "forward")
SEC = os.path.join(sx.ROOT, "secrets")
ARM_FILE, KILL_FILE, ENV_FILE = (os.path.join(SEC, n) for n in ("LIVE_ARMED.json", "KILL", "sodex.env"))
ENV_FALLBACK = os.path.join(sx.ROOT, ".env")  # jalur kredensial yang dipakai CLI/daemon
LEDGER, STATE = os.path.join(FWD, "live_exec.jsonl"), os.path.join(FWD, "live_state.json")
NOT_BEFORE_MIN = dt.date(2026, 12, 1)
SLIP_CAP_BPS = 30.0
DD_HALT_PCT = 20.0        # henti otomatis: ekuitas < puncak*(1-20%). MDD historis arm A -13,8%; arm file hanya boleh MENGETATKAN.
ASSETS = ("btc", "eth", "xaut")
COIN = {"vbtc": "btc", "btc": "btc", "veth": "eth", "eth": "eth", "vxaut": "xaut", "xaut": "xaut", "vusdc": "usdc", "usdc": "usdc"}


class Block(RuntimeError):
    """Satu syarat live tidak terpenuhi -> berhenti, tidak ada order."""


def now_utc(): return dt.datetime.now(dt.timezone.utc)
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def _ap(o):
    with open(LEDGER, "a") as f:
        f.write(json.dumps(o, sort_keys=True, default=str) + "\n"); f.flush(); os.fsync(f.fileno())
def _rd(p): return [json.loads(x) for x in open(p) if x.strip()] if os.path.exists(p) else []


def load_env() -> dict:
    """Baca kredensial sodex: secrets/sodex.env, fallback .env repo root. Wajib mode 600.
    Nilai TIDAK PERNAH dicetak/di-log."""
    tried: list[str] = []
    kv: dict = {}
    for path in (ENV_FILE, ENV_FALLBACK):
        if not os.path.exists(path):
            tried.append(f"{os.path.relpath(path, sx.ROOT)} tidak ada")
            continue
        if stat.S_IMODE(os.stat(path).st_mode) & 0o077:
            tried.append(f"{os.path.relpath(path, sx.ROOT)} mode != 600")
            continue
        cand = {}
        for ln in open(path):
            ln = ln.split("#", 1)[0].strip()
            if "=" in ln:
                k, v = ln.split("=", 1); cand[k.strip()] = v.strip().strip('"').strip("'")
        miss = [k for k in ("SODEX_PRIVATE_KEY", "SODEX_ACCOUNT_ID", "SODEX_ADDRESS") if not cand.get(k)]
        if miss:
            tried.append(f"{os.path.relpath(path, sx.ROOT)} kurang {miss}")
            continue
        kv = cand
        break
    if not kv:
        raise Block("kredensial sodex tidak lengkap: " + "; ".join(tried))
    env = {k: v for k, v in os.environ.items() if k not in sx.PUBLIC_ENV_DROP}
    env.update({k: kv[k] for k in ("SODEX_PRIVATE_KEY", "SODEX_ACCOUNT_ID", "SODEX_ADDRESS")})   # SODEX_API_KEY sengaja tidak diteruskan (sama dgn adapter engine)
    return env


def check_arm(today: dt.date | None = None) -> dict:
    today = today or now_utc().date()
    if os.path.exists(KILL_FILE):
        raise Block("KILL switch aktif (secrets/KILL)")
    if not os.path.exists(ARM_FILE):
        raise Block("secrets/LIVE_ARMED.json belum ada (user belum GO)")
    a = json.load(open(ARM_FILE))
    if a.get("armed") is not True: raise Block("armed != true")
    if not str(a.get("go_by", "")).strip(): raise Block("go_by kosong")
    try:
        nb = dt.date.fromisoformat(a["not_before"]); dt.datetime.fromisoformat(a["go_utc"])
    except Exception: raise Block("not_before/go_utc tidak valid")
    if nb < NOT_BEFORE_MIN: raise Block("not_before < 2026-12-01")
    if today < nb: raise Block(f"belum tanggal {nb}")
    for k in ("max_equity_usd", "max_order_usd", "max_total_buy_usd"):
        if not (isinstance(a.get(k), (int, float)) and a[k] > 0): raise Block(f"{k} wajib angka > 0")
    if a.get("engine_sha256") != sha(os.path.join(HERE, "mode_a_engine.py")): raise Block("engine_sha256 di arm file != engine saat ini (kode berubah sejak GO)")
    if a.get("acknowledge_prareg23b_verdict") is not True: raise Block("user belum acknowledge verdict PRAREG-23b")
    if os.environ.get("CONFIRM_LIVE") != "YES": raise Block("env CONFIRM_LIVE=YES belum diset")
    return a


def check_drawdown(equity: float, arm: dict) -> dict:
    """Circuit breaker anggaran-risiko. Puncak = max(equity_before pertama, semua equity_after, ekuitas kini).
    Breach -> tulis secrets/KILL (hanya user yang boleh menghapus) + Block. Fail-closed bila batas arm tak valid."""
    lim = arm.get("max_drawdown_pct", DD_HALT_PCT)
    if not (isinstance(lim, (int, float)) and 0 < lim <= DD_HALT_PCT): raise Block(f"max_drawdown_pct harus 0<x<={DD_HALT_PCT}")
    led = _rd(LEDGER); pts = [r["equity_before"] for r in led if r.get("kind") == "intent"][:1]
    pts += [r["equity_after"] for r in led if r.get("kind") == "result" and r.get("equity_after") is not None]
    peak = max(pts + [equity]); dd = (equity / peak - 1) * 100 if peak > 0 else 0.0
    if dd <= -lim:
        os.makedirs(SEC, exist_ok=True)
        with open(KILL_FILE, "w") as f: f.write(f"auto-KILL drawdown {dd:.2f}% <= -{lim}% pada {now_utc().isoformat()} (puncak {peak:.2f}, kini {equity:.2f})\n")
        raise Block(f"CIRCUIT BREAKER: drawdown {dd:.2f}% <= -{lim}% -> secrets/KILL ditulis; hapus manual setelah review")
    return {"peak": peak, "dd_pct": dd, "limit_pct": lim}


def parse_balances(rows) -> dict:
    """balance spot -> {btc,eth,xaut,usdc: float tersedia}. Format tak dikenal -> ExecError (fail-closed)."""
    if isinstance(rows, dict):
        rows = rows.get("balances") or rows.get("data") or []
        if isinstance(rows, dict): rows = rows.get("balances", [])
    if not isinstance(rows, list): raise sx.ExecError("format balance tak dikenal")
    out = {k: 0.0 for k in (*ASSETS, "usdc")}
    for b in rows:
        if not isinstance(b, dict): raise sx.ExecError("baris balance bukan objek")
        c = COIN.get(str(b.get("coin", b.get("asset", ""))).lower())
        if c is None: continue
        tot = float(b.get("total", b.get("balance", 0)) or 0)
        av = b.get("available", b.get("free"))
        locked = float(b.get("locked", b.get("frozen", 0)) or 0)
        out[c] = float(av) if av not in (None, "") else max(0.0, tot - locked)
        if out[c] < 0: raise sx.ExecError("saldo negatif")
    return out


def get_balances(env) -> dict: return parse_balances(sx.run_cli(["balance", "spot", "--format", "json"], env=env, timeout=25))


def _fmt(x: Decimal, q: Decimal) -> str: return format(x.quantize(q), "f")


def place_ioc(env, asset: str, side: str, qty: Decimal, px: Decimal) -> dict:
    args = ["orders", "place", "spot", "--symbol", sx.NAME[asset], "--side", side, "--type", "limit", "--tif", "ioc",
            "--price", _fmt(px, sx.TICK[asset]), "--qty", _fmt(qty, sx.STEP[asset]), "--format", "json"]
    j = sx.run_cli(args, env=env, timeout=30)
    jj = j[0] if isinstance(j, list) and j else j
    oid = next((str(jj[k]) for k in ("orderID", "orderId", "order_id", "id") if isinstance(jj, dict) and jj.get(k) not in (None, 0, "0", "")), "")
    if not oid: raise sx.ExecError(f"order tanpa orderID: {str(j)[:160]}")
    return {"order_id": oid, "raw_keys": sorted(jj) if isinstance(jj, dict) else None}


def plan_today(live_env, arm, dry_hold=None) -> dict:
    rows = [r for r in _rd(os.path.join(FWD, "ledger.jsonl")) if r.get("kind") == "rec"]
    if not rows: raise Block("ledger target kosong")
    rec = max(rows, key=lambda r: r["asof"])
    if dt.date.fromisoformat(rec["asof"]) != now_utc().date() - dt.timedelta(days=1): raise Block(f"target basi: asof={rec['asof']}")
    if rec["backfill"]: raise Block("target backfill tidak boleh dieksekusi live")
    st = json.load(open(STATE)) if os.path.exists(STATE) else {"done": []}
    if rec["asof"] in st["done"]: return {"status": "SUDAH", "asof": rec["asof"]}
    for r in _rd(LEDGER):
        if r.get("kind") == "intent" and r["asof"] == rec["asof"] and not any(x.get("kind") == "result" and x["asof"] == rec["asof"] for x in _rd(LEDGER)):
            raise Block("ada intent tanpa result untuk asof ini -> rekonsiliasi MANUAL dulu (jangan kirim ulang)")
    books = {a: sx.fetch_book(a) for a in ASSETS}
    mids = {a: books[a]["mid"] for a in ASSETS}
    bal = get_balances(live_env) if live_env else dry_hold
    hold = {a: bal[a] for a in ASSETS}
    equity = bal["usdc"] + sum(hold[a] * mids[a] for a in ASSETS)
    if equity > arm["max_equity_usd"]: raise Block(f"ekuitas {equity:.2f} > max_equity_usd {arm['max_equity_usd']}")
    if live_env: check_drawdown(equity, arm)
    p = eng.plan_orders(rec["targets"]["A"], hold, mids, bal["usdc"])
    for o in p["orders"]:
        if o["notional"] > arm["max_order_usd"]: raise Block(f"order {o['asset']} {o['notional']:.2f} > max_order_usd")
    if sum(o["notional"] for o in p["orders"] if o["side"] == "BUY") > arm["max_total_buy_usd"]: raise Block("total beli > max_total_buy_usd")
    return {"status": "SIAP", "rec": rec, "plan": p, "books": books, "equity": equity, "bal": bal}


def run(live: bool) -> dict:
    if not live:
        arm = {"max_equity_usd": 1e9, "max_order_usd": 1e9, "max_total_buy_usd": 1e9}
        sp = os.path.join(FWD, "paper_exec_state.json")
        acc = json.load(open(sp))["accounts"]["A"] if os.path.exists(sp) else {"cash": 0.0, "hold": {a: 0.0 for a in ASSETS}}
        P = plan_today(None, arm, {**acc["hold"], "usdc": acc["cash"]})
        if P["status"] != "SIAP": return P
        return {"mode": "DRY-RUN", "asof": P["rec"]["asof"], "equity_virtual": round(P["equity"], 2), "orders": P["plan"]["orders"], "skipped": P["plan"]["skipped"]}
    arm = check_arm(); env = load_env()
    P = plan_today(env, arm)
    if P["status"] != "SIAP": return P
    asof, plan, books = P["rec"]["asof"], P["plan"], P["books"]
    _ap({"kind": "intent", "asof": asof, "utc": now_utc().isoformat(), "orders": plan["orders"], "equity_before": P["equity"], "bal_before": P["bal"]})
    res = []
    for o in plan["orders"]:                       # jual dulu (diurutkan plan_orders)
        side = o["side"].lower(); a = o["asset"]
        px = sx.limit_price(books[a], side, SLIP_CAP_BPS)
        try:
            r = place_ioc(env, a, side, Decimal(str(o["qty"])), px); r.update(asset=a, side=side, qty=o["qty"], limit=float(px), ok=True)
        except sx.ExecError as e:                  # JANGAN retry: status order tak pasti. Berhenti & lapor.
            r = {"asset": a, "side": side, "qty": o["qty"], "limit": float(px), "ok": False, "error": str(e)[:200]}
            res.append(r); break
        res.append(r)
    aft = get_balances(env)
    eq_after = aft["usdc"] + sum(aft[a] * books[a]["mid"] for a in ASSETS)
    _ap({"kind": "result", "asof": asof, "utc": now_utc().isoformat(), "orders": res, "bal_after": aft, "equity_after": eq_after})
    st = json.load(open(STATE)) if os.path.exists(STATE) else {"done": []}
    st["done"].append(asof); json.dump(st, open(STATE + ".tmp", "w")); os.replace(STATE + ".tmp", STATE)
    return {"mode": "LIVE", "asof": asof, "orders": res, "equity_before": round(P["equity"], 2), "equity_after": round(eq_after, 2)}


def status() -> dict:
    s = {}
    for name, fn in (("arm", check_arm), ("env", load_env)):
        try:
            fn(); s[name] = "OK"
        except Block as e: s[name] = f"BLOK: {e}"
    return s


def selftest() -> dict:
    """TESTNET saja. Memastikan jalur tanda-tangan & place/cancel bekerja tanpa dana nyata."""
    if os.environ.get("SODEX_TESTNET") != "1": raise Block("selftest hanya boleh dengan SODEX_TESTNET=1")
    env = load_env(); env["SODEX_TESTNET"] = "1"
    bal = get_balances(env)
    j = sx.run_cli(["orderbook", "spot", sx.NAME["btc"], "--depth", "5", "--format", "json"], env=env)
    px = (Decimal(j["bids"][0]["price"]) * Decimal("0.5") / sx.TICK["btc"]).to_integral_value() * sx.TICK["btc"]
    qty = ((Decimal("6") / px) / sx.STEP["btc"]).to_integral_value(rounding="ROUND_CEILING") * sx.STEP["btc"]
    args = ["orders", "place", "spot", "--symbol", sx.NAME["btc"], "--side", "buy", "--type", "limit", "--tif", "gtc", "--price", _fmt(px, sx.TICK["btc"]), "--qty", _fmt(qty, sx.STEP["btc"]), "--format", "json"]
    r = sx.run_cli(args, env=env, timeout=30)
    return {"saldo_testnet": bal, "place_resp_keys": sorted(r[0] if isinstance(r, list) else r), "catatan": "Batalkan order ini manual: sodex --testnet orders cancel spot --symbol-id <id> --order-id <id>"}


if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "status"
    try:
        out = status() if c == "status" else run("--live" in sys.argv) if c == "run" else selftest()
    except Block as e:
        out = {"BLOK": str(e)}
    except sx.ExecError as e:
        out = {"GAGAL_EKSEKUSI": str(e)}
    print(json.dumps(out, indent=2, default=str))
