#!/usr/bin/env python3
"""PRAREG-23b — paper EKSEKUSI: akun virtual $243,02 per arm (A,B1,B2) yang berdagang di BUKU NYATA SoDEX spot (limit-IOC emulasi,
fee taker 0,065%, batas slip 30 bps). Mengukur apa yang backtest tidak bisa: slippage, minNotional, partial fill, selisih vs ideal.
DRY-RUN: tidak mengirim order apa pun, tidak butuh kredensial.

  paper_exec.py run <fwd_dir>      # eksekusi target ledger TERBARU yang belum dieksekusi (idempoten per asof)
  paper_exec.py report <fwd_dir>   # ringkasan akun virtual vs simulasi ideal
"""
from __future__ import annotations
import datetime as dt, json, os, sys
from decimal import Decimal
import mode_a_engine as eng
import spot_exec as sx

START_USD = 243.02
ASSETS = ("btc", "eth", "xaut")
SLIP_CAP = 30.0


def _rd(p):
    return [json.loads(x) for x in open(p) if x.strip()] if os.path.exists(p) else []


def _ap(p, o):
    with open(p, "a") as f:
        f.write(json.dumps(o, sort_keys=True) + "\n"); f.flush(); os.fsync(f.fileno())


def _state(fd):
    p = os.path.join(fd, "paper_exec_state.json")
    if os.path.exists(p):
        return json.load(open(p))
    return {"accounts": {m: {"cash": START_USD, "hold": {a: 0.0 for a in ASSETS}} for m in ("A", "B1", "B2")}, "done": []}


def _save(fd, st):
    p = os.path.join(fd, "paper_exec_state.json"); t = p + ".tmp"
    json.dump(st, open(t, "w"), indent=1); os.replace(t, p)


def execute_arm(acc: dict, targets: dict, books: dict) -> dict:
    mids = {a: books[a]["mid"] for a in ASSETS}
    eq0 = acc["cash"] + sum(acc["hold"][a] * mids[a] for a in ASSETS)
    plan = eng.plan_orders(targets, acc["hold"], mids, acc["cash"])
    fills, fees = [], 0.0
    for o in plan["orders"]:                      # plan_orders sudah mengurutkan jual dulu
        a, side = o["asset"], o["side"].lower()
        f = sx.sim_fill(books[a], side, Decimal(str(o["qty"])), SLIP_CAP)
        fills.append({"asset": a, **f})
        if f["filled"] <= 0:
            continue
        if f["notional"] < float(sx.MIN_NOTIONAL):       # fill parsial di bawah minNotional dianggap ditolak venue
            f["rejected_min_notional"] = True; f["filled"] = 0.0; continue
        if side == "buy":
            cost = f["notional"] + f["fee"]
            if cost > acc["cash"] + 1e-9:
                f["rejected_cash"] = True; f["filled"] = 0.0; continue
            acc["cash"] -= cost; acc["hold"][a] += f["filled"]
        else:
            acc["cash"] += f["notional"] - f["fee"]; acc["hold"][a] = max(0.0, acc["hold"][a] - f["filled"])
        fees += f["fee"]
    eq1 = acc["cash"] + sum(acc["hold"][a] * mids[a] for a in ASSETS)
    return {"equity_before": eq0, "equity_after": eq1, "fees": fees, "n_orders": len(plan["orders"]),
            "fills": fills, "skipped": plan["skipped"], "weights_after": {a: acc["hold"][a] * mids[a] / eq1 for a in ASSETS}}


def run(fd: str) -> dict:
    recs = [r for r in _rd(os.path.join(fd, "ledger.jsonl")) if r.get("kind") == "rec"]
    if not recs:
        return {"status": "TIDAK_ADA_TARGET"}
    last = max(recs, key=lambda r: r["asof"])
    st, led = _state(fd), os.path.join(fd, "paper_exec.jsonl")
    if last["asof"] in st["done"]:
        return {"status": "SUDAH", "asof": last["asof"]}
    try:
        books = {a: sx.fetch_book(a) for a in ASSETS}
    except sx.ExecError as e:
        _ap(led, {"kind": "event", "event": "GAGAL_BUKU", "asof": last["asof"], "pesan": str(e)[:200], "utc": dt.datetime.now(dt.timezone.utc).isoformat()})
        return {"status": "GAGAL_BUKU", "pesan": str(e)}
    row = {"kind": "exec", "asof": last["asof"], "utc": dt.datetime.now(dt.timezone.utc).isoformat(), "mids": {a: books[a]["mid"] for a in ASSETS},
           "spread_bps": {a: round(books[a]["spread_bps"], 2) for a in ASSETS}, "arms": {}}
    skipped_asof = [r["asof"] for r in recs if r["asof"] < last["asof"] and r["asof"] not in st["done"]]
    row["catatan_terlewat"] = skipped_asof            # tidak diisi ulang: harga lama tak bisa diperdagangkan; dicatat jujur
    for m in ("A", "B1", "B2"):
        row["arms"][m] = execute_arm(st["accounts"][m], last["targets"][m], books)
    _ap(led, row); st["done"].append(last["asof"]); _save(fd, st)
    return {"status": "OK", "asof": last["asof"], "equity": {m: round(row["arms"][m]["equity_after"], 4) for m in row["arms"]}}


def report(fd: str) -> dict:
    rows = [r for r in _rd(os.path.join(fd, "paper_exec.jsonl")) if r.get("kind") == "exec"]
    ev = [r for r in _rd(os.path.join(fd, "paper_exec.jsonl")) if r.get("kind") == "event"]
    out = {"n_exec": len(rows), "gagal_buku": len(ev), "arms": {}}
    for m in ("A", "B1", "B2"):
        if not rows:
            break
        eq = [r["arms"][m]["equity_after"] for r in rows]
        fees = sum(r["arms"][m]["fees"] for r in rows)
        slips = [f["slip_bps_vs_mid"] for r in rows for f in r["arms"][m]["fills"] if f["slip_bps_vs_mid"] is not None]
        part = sum(1 for r in rows for f in r["arms"][m]["fills"] if f.get("partial") or f.get("rejected_min_notional") or f.get("rejected_cash"))
        out["arms"][m] = {"equity_now": round(eq[-1], 4), "ret_pct": round((eq[-1] / START_USD - 1) * 100, 4), "fees_usd": round(fees, 4),
                          "n_fills": len(slips), "slip_bps_mean": round(sum(slips) / len(slips), 3) if slips else None,
                          "slip_bps_max": round(max(slips), 3) if slips else None, "bermasalah": part}
    return out


if __name__ == "__main__":
    cmd, fd = sys.argv[1], sys.argv[2]
    print(json.dumps(run(fd) if cmd == "run" else report(fd), indent=2))
