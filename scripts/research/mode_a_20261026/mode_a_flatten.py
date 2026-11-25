#!/usr/bin/env python3
"""LIKUIDASI PENUH spot Mode A — eksekusi "kill penuh" saat deadman memicu.

Aturan (fail-closed):
  * HANYA jalan bila `secrets/KILL` ada. Tanpa KILL -> Block, tidak ada order.
  * Hanya MENJUAL (sell) aset yang benar-benar dipegang; tidak pernah membuka posisi.
  * Order limit IOC dengan batas slip 30 bps (bukan market), sama seperti eksekutor live.
  * Satu eksekusi per tanggal UTC (marker di forward/live_state.json), idempoten.
  * ExecError -> berhenti, dicatat; tidak ada retry otomatis (status order tak pasti).

  mode_a_flatten.py --live [--reason "..."]
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from decimal import Decimal

import mode_a_live as live
import spot_exec as sx

ASSETS = live.ASSETS
MARKER = os.path.join(live.FWD, "live_state.json")
SLIP_CAP_BPS = live.SLIP_CAP_BPS


def sells_from_balances(bal: dict) -> list[dict]:
    """Saldo -> daftar jual yang terkuantisasi. Aset di bawah 1 step diabaikan (dust)."""
    out = []
    for a in ASSETS:
        raw = bal.get(a) or 0.0
        if raw <= 0:
            continue
        q = Decimal(str(raw)).quantize(sx.STEP[a], rounding="ROUND_DOWN")
        if q <= 0:
            continue
        notional_min = (sx.TICK[a] * q)
        if notional_min <= 0:
            continue
        out.append({"asset": a, "qty": float(q)})
    return out


def _mark_done(day: str, payload: dict) -> None:
    st: dict = json.load(open(MARKER)) if os.path.exists(MARKER) else {"done": []}
    st.setdefault("flatten_done", {})
    st["flatten_done"][day] = payload
    tmp = MARKER + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, MARKER)


def flatten(reason: str = "") -> dict:
    if not os.path.exists(live.KILL_FILE):
        raise live.Block("KILL tidak ada; likuidasi penuh hanya boleh setelah deadman memicu KILL")
    env = live.load_env()
    day = live.now_utc().date().isoformat()
    st = json.load(open(MARKER)) if os.path.exists(MARKER) else {}
    if day in (st.get("flatten_done") or {}):
        return {"status": "SUDAH", "tanggal": day, "detail": st["flatten_done"][day]}

    bal = live.get_balances(env)
    targets = sells_from_balances(bal)
    if not targets:
        out = {"status": "KOSONG", "tanggal": day, "alasan": reason or "KILL", "bal_before": bal}
        _mark_done(day, out)
        live._ap({"kind": "flatten", "utc": live.now_utc().isoformat(), **out})
        return out

    res = []
    for t in targets:
        a = t["asset"]
        book = sx.fetch_book(a)
        px = sx.limit_price(book, "sell", SLIP_CAP_BPS)
        try:
            r = live.place_ioc(env, a, "sell", Decimal(str(t["qty"])), px)
            r.update(asset=a, side="sell", qty=t["qty"], limit=float(px), ok=True)
        except sx.ExecError as e:
            r = {"asset": a, "side": "sell", "qty": t["qty"], "limit": float(px),
                 "ok": False, "error": str(e)[:200]}
            res.append(r)
            break
        res.append(r)

    aft = live.get_balances(env)
    out = {"status": "DIEKSEKUSI", "tanggal": day, "alasan": reason or "KILL",
           "orders": res, "bal_before": bal, "bal_after": aft,
           "utc": live.now_utc().isoformat()}
    live._ap({"kind": "flatten", **out})
    _mark_done(day, out)
    return out


def main(argv: list[str]) -> int:
    if "--live" not in argv:
        print(json.dumps({"status": "DRY-RUN", "catatan": "tambahkan --live untuk mengeksekusi"}))
        return 0
    reason = argv[argv.index("--reason") + 1] if "--reason" in argv else ""
    try:
        print(json.dumps(flatten(reason), default=str))
        return 0
    except live.Block as e:
        print(json.dumps({"status": "BLOK", "alasan": str(e)}))
        return 3
    except Exception as e:
        print(json.dumps({"status": "ERROR", "alasan": str(e)[:300]}))
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
