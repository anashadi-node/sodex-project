#!/usr/bin/env python3
"""SoDEX Paper Trade Logger — READ-ONLY, zero capital, zero orders.

Tracks manual directional calls (paper trades) to build a validated track
record BEFORE committing real money. Profit-first doctrine: prove accuracy
on paper first, then scale with real capital if P(win) ≥ 60% over ≥30 trades.

Usage:
  python3 scripts/sodex_paper_trader.py --open  BTC-USD SHORT 63800 sl=64700 tp=61500 lev=5 note="BTC bearish 4/5 TF, bounce short"
  python3 scripts/sodex_paper_trader.py --close BTC-USD 62100
  python3 scripts/sodex_paper_trader.py --status
  python3 scripts/sodex_paper_trader.py --live   # fetch current prices and mark open trades
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT = Path(__file__).resolve().parents[1]
DB = PROJECT / "data" / "paper_trades.json"


# ─── helpers ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load() -> dict:
    if DB.exists():
        return json.loads(DB.read_text())
    return {"trades": [], "stats": {}}


def _save(d: dict) -> None:
    DB.parent.mkdir(exist_ok=True)
    DB.write_text(json.dumps(d, indent=2))


def _fetch_price(symbol: str) -> Optional[float]:
    """Live mark price from SoDEX public tickers (no auth)."""
    try:
        url = "https://api.sodo.exchange/v1/perps/markets/tickers"
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.loads(r.read())
        rows = data if isinstance(data, list) else data.get("data", [])
        for row in rows:
            if row.get("symbol") == symbol:
                px = float(row.get("markPx") or row.get("lastPx") or 0)
                if px > 0:
                    return px
    except Exception:
        pass
    return None


def _compute_pnl(trade: dict, exit_price: Optional[float] = None) -> dict:
    """Compute unrealised or realised P&L in bps and %."""
    entry = trade["entry_price"]
    direction = trade["direction"]
    lev = trade.get("leverage", 1)
    px = exit_price or trade.get("exit_price") or trade.get("mark_price") or entry

    if direction == "LONG":
        raw_pct = (px - entry) / entry * 100
    else:
        raw_pct = (entry - px) / entry * 100

    leveraged_pct = raw_pct * lev
    sl = trade["sl"]
    tp = trade["tp"]

    # distance to SL / TP
    if direction == "LONG":
        sl_dist = (entry - sl) / entry * 100
        tp_dist = (tp - entry) / entry * 100
    else:
        sl_dist = (sl - entry) / entry * 100
        tp_dist = (entry - tp) / entry * 100

    return {
        "raw_pct": round(raw_pct, 3),
        "lev_pct": round(leveraged_pct, 3),
        "sl_dist_pct": round(sl_dist, 3),
        "tp_dist_pct": round(tp_dist, 3),
        "sl_hit": (direction == "LONG" and px <= sl) or (direction == "SHORT" and px >= sl),
        "tp_hit": (direction == "LONG" and px >= tp) or (direction == "SHORT" and px <= tp),
    }


def _recompute_stats(trades: list) -> dict:
    closed = [t for t in trades if t["status"] == "closed"]
    if not closed:
        return {"n": 0, "wins": 0, "losses": 0, "wr": 0.0, "avg_lev_pct": 0.0,
                "total_lev_pct": 0.0, "expectancy_pct": 0.0}
    wins = [t for t in closed if t.get("outcome") == "WIN"]
    losses = [t for t in closed if t.get("outcome") == "LOSS"]
    avg = sum(t.get("lev_pct", 0) for t in closed) / len(closed)
    avg_win = sum(t.get("lev_pct", 0) for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.get("lev_pct", 0) for t in losses) / len(losses) if losses else 0
    wr = len(wins) / len(closed)
    expectancy = wr * avg_win + (1 - wr) * avg_loss
    return {
        "n": len(closed), "wins": len(wins), "losses": len(losses),
        "wr": round(wr, 3), "avg_lev_pct": round(avg, 3),
        "total_lev_pct": round(sum(t.get("lev_pct", 0) for t in closed), 3),
        "avg_win_pct": round(avg_win, 3), "avg_loss_pct": round(avg_loss, 3),
        "expectancy_pct": round(expectancy, 3),
    }


# ─── commands ─────────────────────────────────────────────────────────────────

def cmd_open(args: list[str]) -> None:
    """--open SYMBOL DIRECTION ENTRY sl=X tp=Y [lev=N] [note=...]"""
    symbol = args[0].upper()
    direction = args[1].upper()
    entry = float(args[2])
    kw: dict[str, str] = {}
    for a in args[3:]:
        if "=" in a:
            k, v = a.split("=", 1)
            kw[k.lower()] = v

    sl = float(kw["sl"])
    tp = float(kw["tp"])
    lev = float(kw.get("lev", "1"))
    note = kw.get("note", "")

    pnl = _compute_pnl({"direction": direction, "entry_price": entry,
                         "sl": sl, "tp": tp, "leverage": lev})

    trade = {
        "id": int(time.time()),
        "symbol": symbol, "direction": direction,
        "entry_price": entry, "sl": sl, "tp": tp, "leverage": lev,
        "sl_dist_pct": pnl["sl_dist_pct"], "tp_dist_pct": pnl["tp_dist_pct"],
        "rr": round(pnl["tp_dist_pct"] / pnl["sl_dist_pct"], 2) if pnl["sl_dist_pct"] else 0,
        "note": note, "open_ts": _now(), "status": "open",
        "mark_price": None, "mark_ts": None,
        "exit_price": None, "exit_ts": None,
        "outcome": None, "lev_pct": None,
    }

    d = _load()
    d["trades"].append(trade)
    _save(d)
    print(f"✅ Paper trade #{trade['id']} OPENED")
    print(f"   {symbol} {direction} @ {entry:,.4f}")
    print(f"   SL={sl:,.4f} ({pnl['sl_dist_pct']:.2f}%)  TP={tp:,.4f} ({pnl['tp_dist_pct']:.2f}%)")
    print(f"   R:R = 1:{trade['rr']}  Leverage={lev}x")
    if note:
        print(f"   Note: {note}")


def cmd_close(args: list[str]) -> None:
    """--close SYMBOL EXIT_PRICE [reason=...]"""
    symbol = args[0].upper()
    exit_price = float(args[1])
    reason = args[2] if len(args) > 2 else "manual"

    d = _load()
    found = False
    for t in d["trades"]:
        if t["symbol"] == symbol and t["status"] == "open":
            pnl = _compute_pnl(t, exit_price)
            t["exit_price"] = exit_price
            t["exit_ts"] = _now()
            t["status"] = "closed"
            t["lev_pct"] = pnl["lev_pct"]
            t["outcome"] = "WIN" if pnl["raw_pct"] > 0 else "LOSS"
            t["close_reason"] = reason
            found = True
            print(f"{'✅ WIN' if t['outcome']=='WIN' else '❌ LOSS'}  #{t['id']} {symbol} closed @ {exit_price:,.4f}")
            print(f"   Raw {pnl['raw_pct']:+.3f}%  Leveraged {pnl['lev_pct']:+.3f}%")
            break

    if not found:
        print(f"No open trade found for {symbol}")
        return

    d["stats"] = _recompute_stats(d["trades"])
    _save(d)
    s = d["stats"]
    print(f"\n📊 Track record: {s['wins']}W/{s['losses']}L  WR={s['wr']:.1%}  "
          f"Avg={s['avg_lev_pct']:+.2f}%  E={s['expectancy_pct']:+.2f}%")


def cmd_live(args: list[str]) -> None:
    """--live: fetch current mark prices, update open trades, flag SL/TP hits."""
    d = _load()
    open_trades = [t for t in d["trades"] if t["status"] == "open"]
    if not open_trades:
        print("No open paper trades.")
        return

    now = _now()
    for t in open_trades:
        px = _fetch_price(t["symbol"])
        if px:
            t["mark_price"] = px
            t["mark_ts"] = now
        pnl = _compute_pnl(t)
        flag = ""
        if pnl["sl_hit"]:
            flag = "  ⚠️  SL HIT — consider closing"
        elif pnl["tp_hit"]:
            flag = "  🎯  TP HIT — consider closing"
        elif pnl["lev_pct"] > 0:
            flag = "  🟢"
        else:
            flag = "  🔴"
        mark_str = f"{px:,.4f}" if px else "N/A"
        print(f"#{t['id']} {t['symbol']} {t['direction']}  entry={t['entry_price']:,.4f}  "
              f"mark={mark_str}  pnl={pnl['lev_pct']:+.2f}%{flag}")

    _save(d)


def cmd_status(args: list[str]) -> None:
    """--status: full table of all trades + overall stats."""
    d = _load()
    trades = d["trades"]
    if not trades:
        print("No paper trades yet.")
        return

    print(f"\n{'='*72}")
    print(f"{'#':>12}  {'Symbol':10} {'Dir':5} {'Entry':>10} {'Exit':>10} "
          f"{'Lev%':>7} {'Status':8} {'Outcome':7}")
    print(f"{'─'*72}")
    for t in trades:
        ep = f"{t['exit_price']:,.2f}" if t.get("exit_price") else "open"
        lp = f"{t['lev_pct']:+.2f}%" if t.get("lev_pct") is not None else "—"
        out = t.get("outcome") or "—"
        print(f"#{t['id']:>11}  {t['symbol']:10} {t['direction']:5} "
              f"{t['entry_price']:>10,.4f} {ep:>10} {lp:>7} {t['status']:8} {out:7}")
        if t.get("note"):
            print(f"{'':>14}  note: {t['note'][:60]}")

    s = d.get("stats", {})
    if s.get("n", 0) > 0:
        print(f"\n{'─'*72}")
        print(f"📊 CLOSED: {s['n']} trades | WR={s['wr']:.1%} | "
              f"AvgWin={s.get('avg_win_pct',0):+.2f}% | AvgLoss={s.get('avg_loss_pct',0):+.2f}% | "
              f"E={s['expectancy_pct']:+.2f}%")
        if s["n"] >= 10:
            gate = "🟢 GATE APPROACHING" if s["wr"] >= 0.55 else "🔴 BELOW TARGET"
            print(f"   Live gate: need WR≥60% over 30 trades. {gate} ({s['n']}/30)")
    print()


# ─── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description="SoDEX paper trade logger")
    p.add_argument("--open", nargs="+", metavar="ARG")
    p.add_argument("--close", nargs="+", metavar="ARG")
    p.add_argument("--live", action="store_true")
    p.add_argument("--status", action="store_true")
    a = p.parse_args()

    if a.open:
        cmd_open(a.open)
    elif a.close:
        cmd_close(a.close)
    elif a.live:
        cmd_live([])
    elif a.status:
        cmd_status([])
    else:
        p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
