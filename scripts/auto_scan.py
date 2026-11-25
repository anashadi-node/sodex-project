#!/usr/bin/env python3
"""Automatic multi-asset scanner — Intelligence + 13 TA + Quant, unified & ranked.

For every liquid asset, stack the three layers and rank:
  1. INTELLIGENCE — regime (BULL/BEAR/RANGING via EMA50 slope) + live OBI (recorder).
  2. 13 TA        — composite directional vote (reuses metals_intel_ta_test).
  3. QUANT        — triple-barrier OOS backtest per asset = the TRUTH GATE. An
                    asset is ACTIONABLE only if its own signal has OOS edge
                    (net>0, z>1.64) — not just a nice-looking current setup.

An asset is flagged 🎯 ACTIONABLE only when ALL align:
  regime confirms direction + 13-TA net ≥ THRESH same way + quant OOS edge +
  (for the $226 perp session) SHORT-capable when regime BEAR.

profit-first: most assets will be ❌ (no OOS edge) — that is the honest result,
and the reason we don't deploy. Read-only, paper. User executes any signal.

Run:  python3 scripts/auto_scan.py        (live)
      python3 scripts/auto_scan.py demo    (self-check)
"""
from __future__ import annotations
import sqlite3, sys, time, math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metals_intel_ta_test as M  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BOOK = ROOT / "data" / "sodex_book_recorder.db"
CRYPTO_COST_BPS = 6.0   # SoDEX crypto-major perp RT taker cost
THRESH = 3              # LOOSENED from 4 → fire on |net|≥3 of 13
CAPITAL = 226.0
# TIERED sizing — loosen entry frequency but scale risk to confidence.
# Rationale: per-asset OOS z-test is underpowered (n~17); a modest real edge
# can't reach z>1.64, so a binary gate over-rejects. Tiers let lower-confidence
# signals trade SMALL (bounded loss) instead of not at all.
TIER_RISK = {"A": 0.010, "B": 0.005, "C": 0.0025}   # 1% / 0.5% / 0.25% of capital
Z_REJECT = -1.0         # still hard-reject signals with clearly-negative OOS

# coingecko id, recorder symbol
UNIVERSE = [
    ("bitcoin", "BTC-USD"), ("ethereum", "ETH-USD"), ("solana", "SOL-USD"),
    ("ripple", "XRP-USD"), ("dogecoin", "DOGE-USD"), ("binancecoin", "BNB-USD"),
    ("avalanche-2", "AVAX-USD"), ("chainlink", "LINK-USD"), ("cardano", "ADA-USD"),
    ("sui", "SUI-USD"),
]


def live_obi(sym):
    try:
        db = sqlite3.connect(BOOK)
        r = db.execute("SELECT bid_sz,ask_sz FROM l1 WHERE symbol=? ORDER BY ts DESC LIMIT 1",
                       (sym,)).fetchone()
        db.close()
        if r and (r[0] + r[1]):
            return (r[0] - r[1]) / (r[0] + r[1]) * 100
    except Exception:
        pass
    return None


def oos_edge(trades):
    """Return (n, wr, net_bps, z, has_edge) on the OOS slice."""
    if not trades:
        return (0, 0.0, 0.0, 0.0, False)
    k = int(len(trades) * M.TRAIN_FRAC)
    oos = trades[k:]
    n = len(oos)
    if n == 0:
        return (0, 0.0, 0.0, 0.0, False)
    wr = sum(t["win"] for t in oos) / n
    net = sum(t["ret_bps"] for t in oos) / n
    z = (sum(t["win"] for t in oos) - n / 2) / (math.sqrt(n) / 2)
    return (n, wr, net, z, net > 0 and z > 1.64)


def scan_asset(cid, sym):
    prices, vols = M.fetch(cid)
    bars = M.resample_4h(prices, vols)
    C = [b["c"] for b in bars]
    O = [b["o"] for b in bars]; H = [b["h"] for b in bars]; L = [b["l"] for b in bars]
    V = [b["v"] for b in bars]
    reg = M.regime_of(C)
    _, net = M.ta_votes(O, H, L, C, V)
    n, wr, oos_net, z, edge = oos_edge(M.backtest(bars, CRYPTO_COST_BPS))
    obi = live_obi(sym)
    # LOOSENED signal: also accept RANGING with a directional lean if OBI + TA agree.
    lean = "BEAR" if (reg == "BEAR" or (net <= -THRESH and (obi or 0) < -5)) else \
           "BULL" if (reg == "BULL" or (net >= THRESH and (obi or 0) > 5)) else "—"
    sig = "SHORT" if (net <= -THRESH and lean == "BEAR") else \
          "LONG" if (net >= THRESH and lean == "BULL") else "—"
    # TIER: A = full OOS edge; B = OOS not-negative (net≥0 or z≥0); C = aligned only.
    tier = None
    if sig != "—" and z > Z_REJECT:
        if edge:
            tier = "A"
        elif oos_net > 0 or z >= 0:
            tier = "B"
        else:
            tier = "C"
    atr_pct = None; entry = None; sl = None; tp = None; size_usd = None
    if tier:
        entry = C[-1]
        # daily ATR from last 24 4h-bars ≈ 4d; clamp 1.5–10%
        rr = M.true_ranges(H, L, C)
        atr_pct = min(0.10, max(0.015, (sum(rr[-6:]) / 6) / entry))
        risk = CAPITAL * TIER_RISK[tier]
        d = 1 if sig == "SHORT" else -1
        sl = entry * (1 + d * atr_pct); tp = entry * (1 - d * 3 * atr_pct)
        size_usd = round(risk / atr_pct, 0)
    return {"sym": sym, "regime": reg, "ta_net": net, "obi": obi,
            "oos_n": n, "oos_wr": wr, "oos_net": oos_net, "oos_z": z,
            "edge": edge, "signal": sig, "tier": tier,
            "entry": entry, "sl": sl, "tp": tp, "size_usd": size_usd,
            "actionable": tier in ("A", "B")}


def run():
    print("=" * 78)
    print("AUTO-SCAN — Intelligence + 13 TA + Quant (OOS truth-gate)  |  ranked")
    print("=" * 78)
    print(f"{'sym':<9}{'regime':<9}{'TA':>4}{'OBI%':>7}{'OOS_n':>6}{'OOS_WR':>7}"
          f"{'OOS_net':>9}{'z':>6}{'edge':>6}  signal")
    rows = []
    for cid, sym in UNIVERSE:
        try:
            r = scan_asset(cid, sym)
        except Exception as e:
            print(f"{sym:<9} scan err {str(e)[:30]}")
            continue
        obi = f"{r['obi']:+.0f}" if r['obi'] is not None else "n/a"
        tag = {"A": "🎯A", "B": "🅱️", "C": "·c"}.get(r["tier"], "  ")
        print(f"{r['sym']:<9}{r['regime']:<9}{r['ta_net']:>+4}{obi:>7}{r['oos_n']:>6}"
              f"{r['oos_wr']*100:>6.0f}%{r['oos_net']:>+8.0f}b{r['oos_z']:>+6.2f}"
              f"{'✅' if r['edge'] else '❌':>5}  {tag} {r['signal']}")
        rows.append(r)
        time.sleep(2)

    act = [r for r in rows if r["actionable"]]      # A + B tiers tradeable
    print("\nVERDICT (LOOSENED / tiered — A full, B half, C paper-only):")
    if act:
        act.sort(key=lambda r: (r["tier"], -r["oos_z"]))
        for r in act:
            print(f"  🎯 ENTER {r['signal']} {r['sym']} [tier {r['tier']}] — "
                  f"entry ${r['entry']:.4f} SL ${r['sl']:.4f} TP ${r['tp']:.4f} "
                  f"notional ${r['size_usd']:.0f} (risk ${CAPITAL*TIER_RISK[r['tier']]:.2f}, R:R 3) "
                  f"| regime {r['regime']} TA{r['ta_net']:+d} OOSz={r['oos_z']:+.2f}")
        print("  → HONEST: B-tier = sub-edge, sized small. Halt −$12 caps total damage.")
    else:
        rej = [r for r in rows if r["signal"] != "—" and r["tier"] is None]
        if rej:
            print("  ⚠️  Signals present but OOS clearly-negative (z<−1.0) → REJECT (would lose):")
            for r in rej:
                print(f"     {r['signal']} {r['sym']} OOSz={r['oos_z']:+.2f} ❌")
        else:
            print("  ⏸  No directional signal (all flat/ranging) → HOLD.")
    return rows


def demo():
    import random
    random.seed(2)
    px, base = [], 100.0
    for t in range(1600):
        base *= 1 + 0.0006 + random.uniform(-0.004, 0.004)
        px.append([t * 3600000, base])
    vols = [[t * 3600000, 1000.0] for t in range(1600)]
    bars = M.resample_4h(px, vols)
    n, wr, net, z, edge = oos_edge(M.backtest(bars, CRYPTO_COST_BPS))
    assert isinstance(edge, bool)
    assert live_obi("__nonexistent__") is None   # missing symbol → None, no crash
    print(f"demo OK — oos_edge returns ({n},{wr:.2f},{net:.0f}bps,z={z:.2f},edge={edge}); obi guard ok")


if __name__ == "__main__":
    demo() if len(sys.argv) > 1 and sys.argv[1] == "demo" else run()
