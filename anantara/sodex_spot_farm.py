#!/usr/bin/env python3
"""
# ⚠️  DEPRECATED (2026-06-08) — Superseded by sodex_autofarm.py v3.1. Remove after 2026-06-22.
ANANTARA SAKTI — SoDEX SPOT low-cap maker-farm executor (dry-run by default).

The first SoDEX avenue where "volume is a RESULT of profitability" can hold:
spot low-caps (PEPE 0.28%, SHIB 0.18%) have spreads WIDER than the spot round-trip
maker fee (0.07%), unlike perps (razor-thin). This executor posts TWO-SIDED
post-only (gtx) maker orders to capture that spread while generating SoPoints
volume — but ONLY if the per-roundtrip expected net edge clears the gate.

SAFETY (matches the project's hard rules):
  • DRY-RUN by default — prints the exact CLI orders it WOULD place, places nothing.
  • LIVE is TRIPLE-gated: --live  AND  SODEX_SPOT_FARM_LIVE=1  AND  a proven-edge
    flag file (data/sodex/spot/PROVEN) that analyze_spot_maker.py writes only when
    net_edge>0 on real fill. Until profitability is PROVEN, live is refused.
  • Profitability gate: skip any pair whose live spread ≤ 2·maker_fee + adverse_buffer.
  • Anti-wash: post-only (gtx) maker only, minimum hold ≥ MIN_HOLD_S, small size cap.

Run (safe):   python3 anantara/sodex_spot_farm.py plan --capital 270
Live (gated): SODEX_SPOT_FARM_LIVE=1 python3 anantara/sodex_spot_farm.py run --live
"""
from __future__ import annotations
import argparse, json, os, subprocess, urllib.request

SPOT_REST = "https://mainnet-gw.sodex.dev/api/v1/spot"
SODEX_BIN = os.environ.get("SODEX_BIN", "./bin/sodex")
PROVEN_FLAG = "freqtrade_user_data/data/sodex/spot/PROVEN"
# displayName → internal name, for the wide-spread low-caps
PAIRS = {"PEPE/USDC": "vPEPE_vUSDC", "SHIB/USDC": "vSHIB_vUSDC", "SUI/USDC": "vSUI_vUSDC"}
SPOT_MAKER_FEE = 0.035          # % per side (Spark)
ADVERSE_BUFFER = 0.05           # % conservative adverse-selection reserve (until measured)
MIN_HOLD_S = 900                # ≥15 min hold (anti-wash/sybil) per external playbooks
MAX_ORDER_USD = float(os.environ.get("SPOT_FARM_MAX_ORDER_USD", "20"))   # hard per-order cap
_HDRS = {"Accept": "application/json", "User-Agent": "anantara-spotfarm/1.0"}


def fetch_book(name: str) -> dict | None:
    try:
        req = urllib.request.Request(f"{SPOT_REST}/markets/{name}/orderbook?limit=5", headers=_HDRS)
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.load(r).get("data", {})
    except Exception:
        return None


def _num(x: float) -> str:
    """Plain decimal (no scientific notation), trailing zeros stripped — CLI-safe."""
    s = f"{x:.12f}".rstrip("0").rstrip(".") if abs(x) < 1 else f"{x:.6f}".rstrip("0").rstrip(".")
    return s or "0"


def gate(spread_pct: float) -> tuple[bool, float]:
    """Profitability gate: net edge per roundtrip = spread − 2·fee − adverse_buffer."""
    net = spread_pct - 2 * SPOT_MAKER_FEE - ADVERSE_BUFFER
    return net > 0, net


def plan(capital: float, live: bool):
    proven = os.path.exists(PROVEN_FLAG)
    allow_deprecated = os.environ.get("SODEX_ALLOW_DEPRECATED_SPOT_EXECUTOR") == "1"
    live_ok = live and allow_deprecated and os.environ.get("SODEX_SPOT_FARM_LIVE") == "1" and proven
    if live and not live_ok:
        if not allow_deprecated:
            why = "deprecated executor disabled; use scripts/sodex_spot_daemon.py once"
        elif os.environ.get("SODEX_SPOT_FARM_LIVE") != "1":
            why = "SODEX_SPOT_FARM_LIVE!=1"
        else:
            why = f"edge NOT proven (missing {PROVEN_FLAG})"
        mode = f"🟡 DRY-RUN (live refused: {why})"
    else:
        mode = "🔴 LIVE" if live_ok else "🟡 DRY-RUN (paper)"
    per = min(MAX_ORDER_USD, capital / max(1, len(PAIRS)))
    print(f"=== SoDEX SPOT maker-farm {mode} | ${per:.0f}/order, hold ≥{MIN_HOLD_S//60}min, "
          f"maker {SPOT_MAKER_FEE}%/side ===")
    print(f"  gate: spread > 2·{SPOT_MAKER_FEE}% + {ADVERSE_BUFFER}% adverse = "
          f"{2*SPOT_MAKER_FEE+ADVERSE_BUFFER:.3f}% to be net-profitable\n")
    n_pass = 0
    for disp, name in PAIRS.items():
        ob = fetch_book(name)
        if not ob or not ob.get("bids") or not ob.get("asks"):
            print(f"  {disp:<11} book unavailable"); continue
        bid, ask = float(ob["bids"][0][0]), float(ob["asks"][0][0])
        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid * 100 if mid > 0 else 0
        ok, net = gate(spread_pct)
        qty = per / mid
        tag = f"PASS net {net:+.3f}%/RT" if ok else f"skip (net {net:+.3f}%)"
        print(f"  {disp:<11} spread {spread_pct:>7.4f}% → {tag}")
        if ok:
            n_pass += 1
            buy = [SODEX_BIN, "orders", "place", "spot", "--symbol", disp,
                   "--side", "buy", "--type", "limit", "--price", _num(bid),
                   "--qty", _num(qty), "--tif", "gtx"]
            sell = [SODEX_BIN, "orders", "place", "spot", "--symbol", disp,
                    "--side", "sell", "--type", "limit", "--price", _num(ask),
                    "--qty", _num(qty), "--tif", "gtx"]
            if live_ok:
                print(f"    [LIVE place buy@{_num(bid)}] …"); _place(buy)
                print(f"    [LIVE place sell@{_num(ask)}] …"); _place(sell)
            else:
                print(f"    would: {' '.join(buy)}")
                print(f"    would: {' '.join(sell)}")
    print(f"\n  {n_pass}/{len(PAIRS)} pairs pass the profitability gate now.")
    if not proven:
        print(f"  NOTE: edge not yet PROVEN — run analyze_spot_maker.py on accumulated data;")
        print(f"  it writes {PROVEN_FLAG} only when net_edge>0 on real fill. Live stays refused until then.")


def _place(cmd: list[str]):
    try:
        r = subprocess.run(cmd + ["--format", "json"], capture_output=True, text=True, timeout=30)
        print(f"      -> {(r.stdout or r.stderr).strip()[:160]}")
    except Exception as e:
        print(f"      -> error {str(e)[:120]}")


def main():
    ap = argparse.ArgumentParser(description="SoDEX spot low-cap maker-farm (dry-run default)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("plan", "run"):
        p = sub.add_parser(c)
        p.add_argument("--capital", type=float, default=270)
        p.add_argument("--live", action="store_true")
    args = ap.parse_args()
    plan(args.capital, live=(args.cmd == "run" and args.live))


if __name__ == "__main__":
    raise SystemExit(main())
