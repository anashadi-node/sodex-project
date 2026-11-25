#!/usr/bin/env python3
"""Satu sumber kebenaran PnL SoDEX.

Pelajaran yang dikodekan di sini:
- `rts.net_pnl` SUDAH net-of-fee (sodex_twin_engine.py: pnl = ... - vol*fee).
- `capital_report` menulis window 6 jam BERGULIR → jangan dijumlahkan mentah.
- SATU DB MENCAMPUR DUA MODE. `twin_engine.py` default DRY_RUN; mode live butuh
  `--live`. Bukti live hanya 26–29 Sep 2026: banner "Twin-Engine start [LIVE]"
  di `logs/twin_live.log` + `logs/e1_microlive.log`, dan harga fill berpresisi
  venue (0.000004447252125). Fill Jun–Jul berpresisi 25–30 desimal (simulator),
  tanpa banner live, sehingga DIKLASIFIKASIKAN SIMULASI — bukan bukti uang nyata.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict

# Satu-satunya jendela yang punya bukti eksekusi nyata (banner LIVE + harga venue).
LIVE_START = "2026-09-26"
LIVE_END = "2026-09-30"


def _agg(con: sqlite3.Connection, rts_where: str, fills_where: str,
         rts_params=(), fills_params=None) -> dict:
    if fills_params is None:
        fills_params = rts_params
    rt, vol, net = con.execute(
        "select count(*),coalesce(sum(cast(volume as real)),0),"
        f"coalesce(sum(cast(net_pnl as real)),0) from rts where {rts_where}", rts_params
    ).fetchone()
    fee = con.execute(
        f"select coalesce(sum(cast(fee as real)),0) from fills where {fills_where}", fills_params
    ).fetchone()[0]
    return dict(rt=rt, vol=vol, net=net, fee=fee, gross=net + fee)



def _has_col(con: sqlite3.Connection, table: str, col: str) -> bool:
    return any(r[1] == col for r in con.execute(f"PRAGMA table_info({table})"))


def summarize(db_path: str = "twin_engine.db") -> dict:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    months = {}
    for m in ("2026-06", "2026-07", "2026-08", "2026-09"):
        rt, vol, net = con.execute(
            "select count(*),coalesce(sum(cast(volume as real)),0),"
            "coalesce(sum(cast(net_pnl as real)),0) from rts where ts_close like ?", (m + "%",)
        ).fetchone()
        fee = con.execute("select coalesce(sum(cast(fee as real)),0) from fills where ts like ?",
                          (m + "%",)).fetchone()[0]
        months[m] = dict(rt=rt, vol=vol, net=net, fee=fee)
    engines = {}
    for e, rt, vol, net in con.execute(
            "select engine,count(*),coalesce(sum(cast(volume as real)),0),"
            "coalesce(sum(cast(net_pnl as real)),0) from rts group by engine"):
        fee = con.execute("select coalesce(sum(cast(fee as real)),0) from fills where engine=?",
                          (e,)).fetchone()[0]
        engines[e] = dict(rt=rt, vol=vol, net=net, fee=fee)
    total = dict(rt=sum(v["rt"] for v in months.values()),
                 vol=sum(v["vol"] for v in months.values()),
                 net=sum(v["net"] for v in months.values()),
                 fee=sum(v["fee"] for v in months.values()))
    total["gross"] = total["net"] + total["fee"]
    has_mode = _has_col(con, "rts", "mode") and _has_col(con, "fills", "mode")
    if has_mode:
        # Kolom mode adalah bukti primer; baris NULL (warisan lama) diklasifikasi
        # dengan jendela live yang sudah diverifikasi banner+presisi harga.
        live = _agg(con,
                    "mode='live' or (mode is null and ts_close>=? and ts_close<?)",
                    "mode='live' or (mode is null and ts>=? and ts<?)",
                    (LIVE_START, LIVE_END), (LIVE_START, LIVE_END))
    else:
        live = _agg(con, "ts_close>=? and ts_close<?", "ts>=? and ts<?", (LIVE_START, LIVE_END))
    sim = dict(rt=total["rt"] - live["rt"], vol=total["vol"] - live["vol"],
               net=total["net"] - live["net"], fee=total["fee"] - live["fee"])
    sim["gross"] = sim["net"] + sim["fee"]
    con.close()
    return dict(months=months, engines=engines, total=total, live=live, sim=sim,
                live_window=(LIVE_START, LIVE_END), mode_column=has_mode)


def buggy_window_sum(history_path: str = "data/capital_report.jsonl") -> dict:
    """Metode v2 yang salah — dipertahankan hanya untuk regresi/penjelasan."""
    m = defaultdict(lambda: dict(rt=0, gross=0.0, fee=0.0, vol=0.0))
    for line in open(history_path):
        r = __import__("json").loads(line)
        s = r.get("stats") or {}
        if not s.get("rt_6h"):
            continue
        d = m[r["ts"][:7]]
        d["rt"] += s["rt_6h"]; d["gross"] += s.get("pnl_6h", 0)
        d["fee"] += s.get("fee_6h", 0); d["vol"] += s.get("vol_6h", 0)
    t = dict(rt=0, gross=0.0, fee=0.0, vol=0.0)
    for v in m.values():
        for k in t:
            t[k] += v[k]
    t["net"] = t["gross"] - t["fee"]
    return dict(months=dict(m), total=t)


if __name__ == "__main__":
    s = summarize()
    print(f"RT={s['total']['rt']} vol=${s['total']['vol']:,.0f} "
          f"gross=${s['total']['gross']:,.2f} fee=${s['total']['fee']:,.2f} net=${s['total']['net']:,.2f}")
    for e, v in sorted(s["engines"].items(), key=lambda kv: -kv[1]["net"]):
        print(f"  {e}: rt={v['rt']} net=${v['net']:+.2f} fee=${v['fee']:.2f}")
