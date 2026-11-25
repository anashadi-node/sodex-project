#!/usr/bin/env python3
"""SoDEX Deep Learner — CLI entry point.

Usage:
  python3 scripts/sodex_deep_learn.py              # run once + print report
  python3 scripts/sodex_deep_learn.py --loop       # continuous loop (60s interval)
  python3 scripts/sodex_deep_learn.py --status     # show learned params + regime
  python3 scripts/sodex_deep_learn.py --reset      # delete learned params (use env defaults)
  python3 scripts/sodex_deep_learn.py --n 5        # run N iterations then exit

The loop is designed to run as a systemd service alongside the twin engine.
It is READ-ONLY with respect to the exchange — it only writes to:
  data/sodex_learned_params.json   (read by engine at runtime)
  data/sodex_deep_learning.jsonl   (audit trail)

Systemd unit: anantara/systemd/sodex-deep-learner.service
"""
from __future__ import annotations
import argparse, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

# add project root to path
_HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HERE))

from anantara.sodex_deep_learner import (
    DeepLearnerLoop,
    ParamWriter,
    LEARNED_PARAMS,
    DEEP_LOG,
    _load_base_spreads,
    _log,
)


def _print_status() -> None:
    data = ParamWriter.read_current()
    if not data:
        print("No learned params found. Run 'python3 scripts/sodex_deep_learn.py' first.")
        return
    ts = data.get("ts", "?")
    print(f"\n{'='*60}")
    print(f"  SoDEX Deep Learner — Learned Parameters")
    print(f"  Generated: {ts}")
    print(f"  Regime:    {data.get('regime', '?')}")
    acc = data.get("regime_accuracy")
    print(f"  Regime accuracy: {f'{acc:.1%}' if acc else 'insufficient data'}")
    print(f"  Fill model n: {data.get('fill_model_n', 0)}")
    awareness = data.get("awareness") or {}
    experience = data.get("experience") or {}
    cross_system = data.get("cross_system_experience") or {}
    learning = data.get("learning") or {}
    if awareness or experience or learning:
        print(f"  Capability: {data.get('capability', 'legacy')}")
        print(f"  Awareness:  {awareness.get('quality', '?')} | "
              f"active={awareness.get('active_pairs', [])} "
              f"observed={awareness.get('observed_pairs', [])}")
        print(f"  Experience: fills={experience.get('fills_total_loaded', 0)} "
              f"rts={experience.get('rts_total_loaded', 0)} "
              f"unique_rt={experience.get('unique_rt_ids_seen', 0)}")
        print(f"  CrossExp:   {cross_system.get('quality', '?')} | "
              f"sources={cross_system.get('sources_count', 0)} "
              f"lessons={cross_system.get('lessons_count', 0)}")
        print(f"  Learning:   bucket={learning.get('current_bucket', '?')} "
              f"min_fills_adapt={learning.get('min_fills_adapt', '?')}")
    print(f"{'='*60}")
    for pair, d in data.get("pairs", {}).items():
        base = d.get("base_spread", 0)
        learned = d.get("min_spread", 0)
        delta_bps = d.get("delta_bps", 0)
        sign = "+" if delta_bps >= 0 else ""
        print(f"  {pair:15s}  spread={learned:.4f} (base={base:.4f} "
              f"Δ={sign}{delta_bps:.1f}bps) conf={d.get('confidence','?')}"
              f"  fill_p={d.get('fill_prob', 0):.2f}  n={d.get('n_fills', 0)}")
        rec = (learning.get("recommendations") or {}).get(pair, {})
        if rec:
            print(f"  {'':15s}  decision={rec.get('decision')} "
                  f"reason={rec.get('reason')}")
    dead = data.get("dead_hours", {})
    if dead:
        print(f"\n  Dead hours (BH-FDR corrected):")
        for pair, hours in dead.items():
            print(f"    {pair}: UTC {hours}")
    print(f"{'='*60}\n")


def _run_loop(n_iterations: int = 0) -> None:
    loop = DeepLearnerLoop()
    _log(f"Starting Loop Deep Learning Ability | DB={loop.analyzer.db_path}")
    _log(f"Base spreads: {loop.base_spreads}")
    _log(f"Output: {LEARNED_PARAMS}")
    loop.run(max_iterations=n_iterations)


def _run_once() -> None:
    loop = DeepLearnerLoop()
    _log(f"Running single Deep Learn step...")
    payload = loop.run_once()
    _print_status()
    fills = loop.analyzer._fills_total
    rts   = loop.analyzer._rts_total
    _log(f"Done: fills_loaded={fills}, rts_loaded={rts}, "
         f"regime={payload.get('regime')}, file={LEARNED_PARAMS}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SoDEX Loop Deep Learning Ability"
    )
    parser.add_argument("--loop",   action="store_true",
                        help="Run continuous loop (60s interval)")
    parser.add_argument("--status", action="store_true",
                        help="Show current learned params")
    parser.add_argument("--reset",  action="store_true",
                        help="Delete learned params (revert to env defaults)")
    parser.add_argument("--n",      type=int, default=0,
                        help="Run N iterations then exit (0=forever with --loop)")
    args = parser.parse_args()

    if args.reset:
        if LEARNED_PARAMS.exists():
            LEARNED_PARAMS.unlink()
            _log(f"Deleted {LEARNED_PARAMS} — engine will use env defaults")
        else:
            _log("No learned params file found")
        return

    if args.status:
        _print_status()
        return

    if args.loop:
        _run_loop(n_iterations=args.n)
    else:
        # default: run once and print
        if args.n > 1:
            _run_loop(n_iterations=args.n)
        else:
            _run_once()


if __name__ == "__main__":
    main()
