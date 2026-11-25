#!/usr/bin/env python3
"""
ANANTARA SAKTI — SUPERVISED directional conviction farming (the GABUNGAN booster).

Opens positions in the OOS-model's direction at the governor's conviction-scaled
leverage, then ACTIVELY monitors price (the process is the stop-loss, since the
SoDEX CLI has no exchange stop orders) and closes on take-profit / stop-loss /
timeout. Bounded loss per position ≈ SL% × leverage × margin (~$1).

This is the directional PROFIT-SUBSIDY leg of the combined strategy: neutral
volume farming (sodex_measure) is the volume engine; this adds directional bets
when a VALIDATED signal is confident, to lift the blended volume/cost ratio.

SAFETY (real money): DRY-RUN default; live needs --live AND env MEASURE_FARM_LIVE=1.
Leverage from governor (≤25x, vol-capped). Tight SL, fast poll (process-side stop).
Always flattens on exit. Honest note: the model's edge is at the 48h horizon — a
short supervised hold captures only part of it; treat results as a real but
short-horizon read, not the full edge.

Usage:
  python3 anantara/sodex_directional.py plan
  MEASURE_FARM_LIVE=1 python3 anantara/sodex_directional.py run --live --timeout 5400
"""
from __future__ import annotations
import argparse, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti")))
LOG_DIR = PROJECT_DIR / "freqtrade_user_data" / "data" / "sodex" / "directional"
SYMBOLS = ["BTC-USD", "SOL-USD", "ETH-USD"]
MARGIN = float(os.environ.get("DIR_MARGIN", "8"))
TP_PCT = float(os.environ.get("DIR_TP_PCT", "1.2"))     # take-profit %
SL_PCT = float(os.environ.get("DIR_SL_PCT", "0.8"))     # stop-loss % (bounds loss)
POLL_S = float(os.environ.get("DIR_POLL_S", "12"))      # fast poll = process-side stop
LEV_HARD_MAX = int(os.environ.get("DIR_LEV_MAX", "20")) # extra cap on supervised dir bets


def _log(row: dict):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    with open(LOG_DIR / f"directional_{day}.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")


def plan(sf, cfg):
    print("=== DIRECTIONAL PLAN (governor conviction, no orders) ===")
    for s in SYMBOLS:
        g = sf.governor_leverage_for(s, cfg)
        lev = min(g["leverage"], LEV_HARD_MAX)
        act = g.get("ok") and g["direction"] != "NEUTRAL"
        print(f"  {s}: {g['direction']} prob {g.get('prob',0):.2f} OOS {(g.get('oos_acc') or 0):.0f}% "
              f"-> {'BET ' + str(lev) + 'x' if act else 'skip (no conviction)'} "
              f"| margin ${MARGIN} TP +{TP_PCT}% SL -{SL_PCT}% (max loss ~${MARGIN*lev*SL_PCT/100:.2f})")


def run(sf, cfg, live: bool, timeout_s: float):
    mode = "🔴 LIVE" if live else "🟡 DRY-RUN"
    print(f"=== DIRECTIONAL {mode} | margin ${MARGIN} TP +{TP_PCT}% SL -{SL_PCT}% "
          f"poll {POLL_S}s timeout {timeout_s/60:.0f}m ===")
    # 1) pick conviction bets
    bets = []
    for s in SYMBOLS:
        g = sf.governor_leverage_for(s, cfg)
        if g.get("ok") and g["direction"] in ("UP", "DOWN"):
            bets.append({"sym": s, "dir": g["direction"], "lev": min(g["leverage"], LEV_HARD_MAX),
                         "prob": g.get("prob"), "conv": g.get("conviction")})
    if not bets:
        print("  no conviction bets right now (model neutral/unreliable). Nothing to do.")
        return 0
    for b in bets:
        print(f"  bet: {b['sym']} {b['dir']} {b['lev']}x (prob {b['prob']:.2f}, conv {b['conv']})")
    if not live:
        print("  DRY-RUN — no orders placed."); return 0

    if sf.open_positions(cfg):
        print("  ⚠️ account not flat — aborting (close positions first)."); return 1
    # 2) set leverage + OPEN (taker market for reliable entry)
    opened = []
    for b in bets:
        sf.set_leverage(b["sym"], b["lev"], cfg)
        t = sf.get_ticker(b["sym"], cfg)
        if not t or t["last"] <= 0:
            print(f"  {b['sym']}: no ticker, skip"); continue
        entry = t["last"]; side = "buy" if b["dir"] == "UP" else "sell"
        qty = sf.fmt_qty(b["sym"], (MARGIN * b["lev"]) / entry)
        r = sf.cli(["orders", "place", "perps", "--symbol", b["sym"], "--side", side,
                    "--type", "market", "--qty", qty, "--tif", "ioc"], cfg=cfg, auth=True)
        if r is None:
            print(f"  {b['sym']}: open rejected"); continue
        time.sleep(1.5)
        held = abs(sf._position_qty(b["sym"], cfg))
        if held <= 0:
            print(f"  {b['sym']}: not filled, skip"); continue
        b.update({"entry": entry, "side": side, "qty": held, "t0": time.time()})
        opened.append(b)
        print(f"  ▶ OPEN {b['sym']} {b['dir']} {b['lev']}x @ {entry} qty {held}")
        _log({"ts": datetime.now(timezone.utc).isoformat(), "event": "open", **{k: b[k] for k in ("sym","dir","lev","entry","qty","prob","conv")}})
    if not opened:
        print("  no positions opened."); return 0
    # 3) MONITOR — process-side stop. Close on TP / SL / timeout.
    deadline = time.time() + timeout_s
    while opened and time.time() < deadline:
        time.sleep(POLL_S)
        for b in list(opened):
            t = sf.get_ticker(b["sym"], cfg)
            if not t:
                continue
            sign = 1 if b["dir"] == "UP" else -1
            pnl = (t["last"] - b["entry"]) / b["entry"] * 100 * sign
            reason = ("TP" if pnl >= TP_PCT else "SL" if pnl <= -SL_PCT else None)
            if reason:
                _close(sf, cfg, b, t["last"], pnl, reason); opened.remove(b)
    # 4) timeout — close the rest at market
    for b in list(opened):
        t = sf.get_ticker(b["sym"], cfg) or {"last": b["entry"]}
        sign = 1 if b["dir"] == "UP" else -1
        pnl = (t["last"] - b["entry"]) / b["entry"] * 100 * sign
        _close(sf, cfg, b, t["last"], pnl, "timeout")
    # 5) safety: ensure flat
    for p in sf.open_positions(cfg):
        sf.close_position(p, cfg)
    print("  ✅ directional session done — flat.")
    return 0


def _close(sf, cfg, b, px, pnl, reason):
    pos = [p for p in sf.open_positions(cfg) if p.get("symbol") == b["sym"]]
    if pos:
        sf.close_position(pos[0], cfg)
    vol = b["entry"] * b["qty"] * 2
    print(f"  ◀ CLOSE {b['sym']} @ {px} | {reason} | PnL {pnl:+.2f}% (~${MARGIN*b['lev']*pnl/100:+.2f}) vol ~${vol:,.0f}")
    _log({"ts": datetime.now(timezone.utc).isoformat(), "event": "close", "sym": b["sym"],
          "reason": reason, "exit": px, "pnl_pct": round(pnl, 3),
          "pnl_usd": round(MARGIN * b["lev"] * pnl / 100, 3), "volume": round(vol, 2)})


def main():
    ap = argparse.ArgumentParser(description="Supervised directional conviction farming")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan")
    rp = sub.add_parser("run")
    rp.add_argument("--live", action="store_true")
    rp.add_argument("--timeout", type=float, default=5400)   # supervised window (s)
    args = ap.parse_args()
    sys.path.insert(0, os.path.dirname(__file__))
    import sodex_farming as sf
    cfg = sf._cfg(); cfg["address"] = os.environ.get("SODEX_ADDRESS", "")
    if args.cmd == "plan":
        return plan(sf, cfg)
    live = args.live and os.environ.get("MEASURE_FARM_LIVE") == "1"
    if args.live and not live:
        print("REFUSING live: set env MEASURE_FARM_LIVE=1 to confirm real-money trading.")
        return 2
    return run(sf, cfg, live, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
