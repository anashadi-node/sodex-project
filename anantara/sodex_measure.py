#!/usr/bin/env python3
"""
ANANTARA SAKTI — SoDEX MEASURE-FARM controller (empirical SoPoints calibration).

WHY: directional scalping has no proven edge (any horizon, OOS). The airdrop ROI
model says a bounded farming budget is plausibly +EV, but the SoPoint→$ ratio is
undisclosed. The only way to resolve it is to MEASURE: farm a tiny, strictly
bounded amount for ~3 days, then read how many SoPoints were actually credited.
This controller does that with hard safety rails — it is NOT a profit strategy.

SAFETY (security-first — this touches real money):
  • DRY-RUN by default. Live requires BOTH `--live` AND env MEASURE_FARM_LIVE=1.
  • HARD budget kill-switch: stop when realized cost (equity drawdown) ≥ budget.
  • LOW leverage (default 3x, hard max 5x) — volume is the goal, not P&L; high
    leverage only adds liquidation risk with no benefit here.
  • Tiny margin/round, max rounds, max wall-clock per session.
  • Always flatten on exit (never leave a leveraged position open).
  • Every round logged to data/sodex/measure/measure_*.jsonl for calibration.

Subcommands:
  plan   --budget 34 --margin 8 --leverage 3        # show plan, NO network
  run    [--live] --budget 34 --margin 8 --leverage 3 --max-rounds 40
  report --sopoints 350                              # points-per-$ from the log

The governor's expectancy gate is intentionally BYPASSED here (we know EV≈0/neg);
the loss-budget kill-switch is the safety contract instead. Use only as a
deliberate, bounded calibration spend.
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti")))
MEASURE_DIR = PROJECT_DIR / "freqtrade_user_data" / "data" / "sodex" / "measure"
COST_RATE_MAKER = 0.00024     # ~0.024%/volume realistic maker-biased (4,100:1)
HARD_LEVERAGE_MAX = 5         # never exceed, whatever is passed
DEFAULT_SYMBOLS = ["BTC-USD", "SOL-USD", "ETH-USD"]


# ---------------- pure, testable planning ----------------
def measure_plan(budget_usd: float, margin: float, leverage: int,
                 cost_rate: float = COST_RATE_MAKER) -> dict:
    """How much volume a loss-budget buys, and how many maker rounds it implies.
    Pure — no network. cost_per_round ≈ round_volume * cost_rate."""
    lev = max(1, min(int(leverage), HARD_LEVERAGE_MAX))
    notional = margin * lev
    round_volume = notional * 2                 # open + close
    cost_per_round = round_volume * cost_rate
    rounds = int(budget_usd / cost_per_round) if cost_per_round > 0 else 0
    total_volume = rounds * round_volume
    return {"leverage": lev, "notional_per_round": round(notional, 2),
            "round_volume": round(round_volume, 2),
            "cost_per_round": round(cost_per_round, 4),
            "rounds_within_budget": rounds,
            "total_volume": round(total_volume, 2),
            "budget_usd": budget_usd}


def _log_path() -> Path:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return MEASURE_DIR / f"measure_{day}.jsonl"


MEASURE_STATE = MEASURE_DIR / "measure_state.json"


def load_state() -> dict:
    try:
        return json.loads(MEASURE_STATE.read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    MEASURE_DIR.mkdir(parents=True, exist_ok=True)
    MEASURE_STATE.write_text(json.dumps(state, indent=2))


def establish_baseline(current_equity: float, budget: float, reset: bool) -> dict:
    """Persist the budget baseline so cumulative cost survives restarts. If a
    matching session exists (same budget) and not reset, keep its baseline."""
    st = {} if reset else load_state()
    if st.get("budget") == budget and "baseline_equity" in st and not reset:
        return st
    st = {"baseline_equity": current_equity, "budget": budget,
          "started": datetime.now(timezone.utc).isoformat()}
    save_state(st)
    return st


# ---------------- live equity read (lazy deps) ----------------
def read_equity(cfg: dict) -> float | None:
    """Account value (vUSDC) from REST state field `av`. None on failure."""
    import httpx
    addr = cfg.get("address", "")
    if not addr:
        return None
    try:
        with httpx.Client(timeout=10, headers={"Accept": "application/json",
                                               "User-Agent": "anantara-measure/1.0"}) as c:
            r = c.get(f"{cfg['perps_url']}/accounts/{addr}/state")
            return float((r.json() or {}).get("data", {}).get("av", 0) or 0)
    except Exception:
        return None


def cmd_plan(args) -> int:
    p = measure_plan(args.budget, args.margin, args.leverage)
    print("=== MEASURE-FARM PLAN (no orders) ===")
    print(f"  budget ${p['budget_usd']:.0f} | {p['leverage']}x | margin ${args.margin:.0f}")
    print(f"  per round: notional ${p['notional_per_round']} -> volume ${p['round_volume']} "
          f"(cost ~${p['cost_per_round']})")
    print(f"  within budget: ~{p['rounds_within_budget']} rounds -> "
          f"~${p['total_volume']:,.0f} total volume")
    print("  NOTE cost-rate assumes ~0.024% maker-biased; real fill quality varies.")
    print("  After ~3 days, run: python3 anantara/sodex_measure.py report --sopoints <credited>")
    return 0


def cmd_run(args) -> int:
    live = args.live and os.environ.get("MEASURE_FARM_LIVE") == "1"
    mode = "🔴 LIVE" if live else "🟡 DRY-RUN (no orders)"
    if args.live and not live:
        print("REFUSING live: set env MEASURE_FARM_LIVE=1 to confirm real-money farming.")
        return 2
    lev = max(1, min(args.leverage, HARD_LEVERAGE_MAX))
    MEASURE_DIR.mkdir(parents=True, exist_ok=True)
    cfg, maker_scalp_round, open_positions, close_position, start_eq = None, None, None, None, None
    if live:   # only the live path needs execution primitives (httpx + CLI)
        sys.path.insert(0, os.path.dirname(__file__))
        from sodex_farming import (_cfg, maker_scalp_round, set_leverage,  # noqa
                                    open_positions, close_position)
        cfg = _cfg()
        cfg["address"] = os.environ.get("SODEX_ADDRESS", "")  # main() sets this; we call _cfg directly
        start_eq = read_equity(cfg)
    print(f"=== MEASURE-FARM {mode} | budget ${args.budget:.0f} | {lev}x | "
          f"margin ${args.margin:.0f} | max {args.max_rounds} rounds ===")
    baseline = None
    if live:
        if start_eq is None:
            print("Cannot read equity — aborting (safety)."); return 1
        st = establish_baseline(start_eq, args.budget, getattr(args, "reset_state", False))
        baseline = st["baseline_equity"]
        spent = baseline - start_eq
        print(f"  equity ${start_eq:.2f} | budget baseline ${baseline:.2f} "
              f"| already spent ${spent:.2f} of ${args.budget:.0f}")
        if spent >= args.budget:
            print(f"  🛑 cumulative budget already reached (${spent:.2f}); nothing to do."); return 0
        # set account leverage UPFRONT while flat (maker_scalp_round can't set it
        # mid-trade, so positions otherwise open at the account default).
        if open_positions(cfg):
            print("  ⚠️ not flat — refusing to set leverage / start (close positions first)."); return 1
        for s in DEFAULT_SYMBOLS:
            try:
                set_leverage(s, lev, cfg)
            except Exception as e:
                print(f"  warn: could not set {s} leverage to {lev}x: {e}")
        print(f"  account leverage set to {lev}x for {', '.join(DEFAULT_SYMBOLS)}")
    vol_total, rounds_done, t0 = 0.0, 0, time.time()
    syms = DEFAULT_SYMBOLS
    while rounds_done < args.max_rounds and (time.time() - t0) < args.max_seconds:
        # budget kill-switch (live only — cumulative drawdown vs persisted baseline)
        if live:
            cur = read_equity(cfg)
            cost = (baseline - cur) if (cur is not None and baseline is not None) else 0.0
            if cost >= args.budget:
                print(f"  🛑 budget reached: cumulative cost ${cost:.2f} ≥ ${args.budget:.0f}")
                break
        sym = syms[rounds_done % len(syms)]
        if live:
            r = maker_scalp_round(sym, cfg, margin=args.margin, leverage=lev)
            vol = float(r.get("volume", 0) or 0)
        else:
            p = measure_plan(args.budget, args.margin, lev)
            vol = p["round_volume"]                      # estimated
            r = {"ok": True, "filled": True, "volume": vol, "dry_run": True}
        vol_total += vol
        rounds_done += 1
        row = {"ts": datetime.now(timezone.utc).isoformat(), "round": rounds_done,
               "symbol": sym, "volume": vol, "vol_total": round(vol_total, 2),
               "live": live, "result": r}
        with open(_log_path(), "a") as f:
            f.write(json.dumps(row) + "\n")
        print(f"  round {rounds_done} {sym}: vol +${vol:,.0f} (total ${vol_total:,.0f})"
              + ("" if live else " [dry]"))
        # volume cap (primary bound — robust to a shared account where manual
        # trades confound the equity-based budget guard)
        if getattr(args, "max_volume", 0) and vol_total >= args.max_volume:
            print(f"  🛑 volume cap reached: ${vol_total:,.0f} ≥ ${args.max_volume:,.0f}"); break
        if not live and rounds_done >= min(args.max_rounds, measure_plan(
                args.budget, args.margin, lev)["rounds_within_budget"]):
            print("  (dry-run reached planned round count)"); break
        if live and getattr(args, "pace_seconds", 0) > 0:
            time.sleep(args.pace_seconds)   # spread volume over the window
    # ALWAYS flatten on exit (live)
    if live:
        for pos in open_positions(cfg):
            close_position(pos, cfg)
        final_eq = read_equity(cfg)
        realized = (start_eq - final_eq) if (final_eq is not None) else None
        print(f"  done: {rounds_done} rounds, volume ${vol_total:,.0f}, "
              f"realized cost ${realized:.2f}" if realized is not None else
              f"  done: {rounds_done} rounds, volume ${vol_total:,.0f}")
    else:
        print(f"  DRY-RUN done: {rounds_done} rounds, est volume ${vol_total:,.0f}, no orders placed.")
    return 0


def cmd_report(args) -> int:
    rows = []
    for fp in sorted(glob.glob(str(MEASURE_DIR / "measure_*.jsonl"))):
        with open(fp, encoding="utf-8") as f:
            for ln in f:
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    pass
    live_rows = [r for r in rows if r.get("live")]
    vol = sum(r.get("volume", 0) for r in live_rows)
    print(f"=== MEASURE REPORT === live rounds: {len(live_rows)} | total volume ${vol:,.0f}")
    if vol <= 0:
        print("  No LIVE volume logged yet — run with --live (and MEASURE_FARM_LIVE=1) first.")
        return 0
    if args.sopoints is not None and args.sopoints > 0:
        per_dollar = args.sopoints / vol
        per_1k = per_dollar * 1000
        print(f"  SoPoints credited: {args.sopoints:.0f}")
        print(f"  -> {per_1k:.4f} SoPoints per $1,000 volume")
        for val in (0.1, 0.3, 0.7):
            print(f"     at ${val}/pt: ${args.sopoints * val:,.2f} reward")
    else:
        print("  Pass --sopoints <credited> (from SoDEX snapshot) to compute points-per-$.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="SoDEX measure-farm (bounded SoPoints calibration)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("plan"); pp.set_defaults(fn=cmd_plan)
    rp = sub.add_parser("run"); rp.set_defaults(fn=cmd_run)
    rp.add_argument("--live", action="store_true")
    rp.add_argument("--max-rounds", type=int, default=40)
    rp.add_argument("--max-seconds", type=float, default=3600)
    rp.add_argument("--pace-seconds", type=float, default=0,
                    help="sleep between rounds (live) to spread volume over the window")
    rp.add_argument("--max-volume", type=float, default=0,
                    help="cap cumulative OUR volume (primary bound; robust to shared-account manual trades)")
    rp.add_argument("--reset-state", action="store_true",
                    help="reset the persisted budget baseline (start a fresh session)")
    rep = sub.add_parser("report"); rep.set_defaults(fn=cmd_report)
    rep.add_argument("--sopoints", type=float, default=None)
    for p in (pp, rp):
        p.add_argument("--budget", type=float, default=34.0)
        p.add_argument("--margin", type=float, default=8.0)
        p.add_argument("--leverage", type=int, default=3)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
