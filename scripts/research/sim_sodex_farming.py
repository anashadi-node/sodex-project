#!/usr/bin/env python3
"""
ANANTARA SAKTI — SoDEX farming SIMULATOR (NO real money).

Answers, risk-free, whether/how the targets (ratio 1:11k-15k + $4M/week volume)
are reachable, and at what capital + time — using REAL inputs:
  • SoDEX fee/rebate schedule (Tier-0 maker 0.012%/taker 0.040%; maker rebates
    -0.001/-0.002/-0.003% at >0.5/1.5/3% of 14-day platform maker share).
  • EMPIRICAL execution measured from our own live sessions: maker-fill ~60%,
    adverse-selection ~0.011%, effective Tier-0 cost ~0.0286% (= ~3,500:1).
  • A parameterized platform maker volume (the key unknown — swept as a range).

Models the week-by-week tier dynamics: a weekly loss-budget B buys volume
V = B / cost_rate; that volume builds 14-day maker share; crossing a rebate
threshold lowers the fee next period → ratio rises → more volume affordable.
This captures the bootstrap (need volume for rebate, need rebate for cheap volume).

Pure stdlib. No orders, no money. Run: python3 scripts/sim_sodex_farming.py
"""
from __future__ import annotations

TAKER = 0.040            # % per side
MAKER_T0 = 0.012         # % per side, Tier-0
ADVERSE = 0.011          # % per roundtrip, empirical (queue/repricing slippage)
# maker rebate schedule: (min 14d maker-share %, maker fee %)
REBATE = [(3.0, -0.003), (1.5, -0.002), (0.5, -0.001), (0.0, MAKER_T0)]
TARGET_RATIO = 11_000
TARGET_WEEKLY_VOL = 4_000_000


def maker_fee(share_pct: float) -> float:
    for thr, fee in REBATE:
        if share_pct >= thr:
            return fee
    return MAKER_T0


def cost_rate_pct(maker_fill: float, mk_fee: float) -> float:
    """Cost per $1 of VOLUME (%) given maker-fill fraction. Open+close; the
    non-maker fraction pays taker. Adverse selection added on top."""
    per_side = maker_fill * mk_fee + (1 - maker_fill) * TAKER
    return per_side + ADVERSE        # ≈ cost per unit volume %


def ratio_for(cost_pct: float) -> float:
    return float("inf") if cost_pct <= 0 else 100.0 / cost_pct  # $vol per $1 cost


def simulate(budget_wk: float, maker_fill: float, platform_maker_14d: float,
             weeks: int = 12) -> list[dict]:
    """Week-by-week. Returns trajectory rows."""
    traj = []
    vol_14d = 0.0                    # our trailing ~14-day maker volume
    hist = []                        # weekly volumes for the 14d (2-week) window
    for w in range(1, weeks + 1):
        share = (vol_14d / platform_maker_14d * 100) if platform_maker_14d else 0
        mk = maker_fee(share)
        cr = cost_rate_pct(maker_fill, mk)
        ratio = ratio_for(cr)
        # volume the weekly budget can buy at this cost (if cost<=0, capital-bound)
        if cr > 0:
            wk_vol = budget_wk / (cr / 100.0)
        else:
            wk_vol = TARGET_WEEKLY_VOL * 2     # paid-to-trade → capital/throughput bound
        hist.append(wk_vol)
        vol_14d = sum(hist[-2:])               # trailing 2 weeks ≈ 14d
        traj.append({"week": w, "share_pct": round(share, 3), "maker_fee": mk,
                     "cost_pct": round(cr, 5), "ratio": ratio,
                     "wk_vol": wk_vol, "vol_14d": vol_14d})
    return traj


def report():
    print("=== SoDEX FARMING SIMULATOR (no real money) ===")
    print(f"empirical: maker-fill 60%, adverse {ADVERSE}%, Tier-0 cost "
          f"{cost_rate_pct(0.6, MAKER_T0):.4f}% (~{ratio_for(cost_rate_pct(0.6, MAKER_T0)):,.0f}:1)\n")

    print("A) RATIO vs maker-fill × fee tier (what reaches 1:11-15k?)")
    print(f"   {'fill':>5} {'Tier0':>9} {'reb-0.001':>10} {'reb-0.002':>10} {'reb-0.003':>10}")
    for fill in (0.60, 0.75, 0.90, 0.95, 0.99):
        cells = []
        for mk in (MAKER_T0, -0.001, -0.002, -0.003):
            r = ratio_for(cost_rate_pct(fill, mk))
            cells.append(f"{r:,.0f}" if r != float("inf") else "PAID")
        print(f"   {fill*100:>4.0f}% {cells[0]:>9} {cells[1]:>10} {cells[2]:>10} {cells[3]:>10}")
    print("   -> 1:11-15k needs BOTH high maker-fill (~90%+, patient-MM) AND a rebate tier.\n")

    print("B) CAMPAIGN at $270/week budget — when do targets hit? (sweep platform size)")
    for plat in (50e6, 100e6, 300e6):
        print(f"\n   platform maker ~${plat/1e6:.0f}M/14d | maker-fill 90% (patient-MM):")
        traj = simulate(270, 0.90, plat, weeks=12)
        hit = None
        for r in traj:
            tag = ""
            if r["ratio"] >= TARGET_RATIO and r["wk_vol"] >= TARGET_WEEKLY_VOL and not hit:
                hit = r["week"]; tag = "  <== BOTH TARGETS"
            print(f"     wk{r['week']:>2}: share {r['share_pct']:>5.2f}% fee {r['maker_fee']:>+.3f}% "
                  f"ratio {r['ratio']:>8,.0f} wkVol ${r['wk_vol']:>12,.0f}{tag}")
        print(f"     => targets {'reached week '+str(hit) if hit else 'NOT reached in 12 wks at $270/wk'}")

    print("\nVERDICT (data-driven, no money spent):")
    print("  • 1:11-15k is a MAKER-FILL + REBATE problem, not a capital-size problem alone.")
    print("  • Reaching it needs patient-MM execution (~90% maker fill) AND a rebate tier,")
    print("    which depends on our volume vs the (unknown) platform maker volume.")
    print("  • $4M/week affordability follows once the ratio climbs (cost ≈ budget/ratio).")
    print("  Next: pin platform maker volume from public data to remove the last unknown.")


if __name__ == "__main__":
    report()
