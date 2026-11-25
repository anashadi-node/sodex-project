# WEEKLY DEEP AUDIT — SoDEX + CEX-Binance
**Week:** 2026-10-11 to 2026-10-18
**Generated:** 2026-10-18 23:31 UTC

## 1. PERFORMANCE vs NORTH STAR (≥0.7%/window)

| Divisi | Target | 7d Actual | 30d Trend | Status |
|--------|--------|-----------|-----------|--------|
| **SoDEX** | 0.7% wallet/window | *extract from recovery* | *compare* | 🟡/🔴 |
| **CEX Futures** | 0.7% wallet/window | *extract from paper* | *compare* | 🟡/🔴 |
| **CEX Spot** | 0.7% wallet/window | *extract from paper* | *compare* | 🔴 |

## 2. GATE RECALIBRATION EVIDENCE (7d Rolling)

### CEX Gates (from auto_research_pregain)
```
=== Pre-Gain Daily Research ===
🔬 *AUTO-RESEARCH REPORT* — Pre-Gain System
   2026-10-18 23:31 UTC

📊 *Edge Stats (weekday-only)*

✅ Signal quality: within normal range (no degradation)

📅 *DOW Performance (weekday-only, 7d rolling vs all-time)*
   ✅ Thu: WR=58.3% E=1.29R n=840
   ✅ Fri: WR=55.2% E=0.65R n=1336
   ⚠️ Tue: WR=40.9% E=0.02R n=709
   ⚠️ Wed: WR=38.3% E=-0.16R n=883
   ⚠️ Mon: WR=37.9% E=0.04R n=425
   📋 Sun: WR=27.2% E=-0.50R n=907
   📋 Sat: WR=23.9% E=-0.58R n=1365

🔭 *Signal Type Stats*
   LONG_FUNDING: total=4985 resolved=3072 WR=23%
   LONG_TECHNICAL: total=1132 resolved=905 WR=0%
   SHORT: total=8345 resolved=6465 WR=31%
   SPOT_BREAKOUT: total=699 resolved=561 WR=68%

_Autonomous research | Next: deep research in 3.0h_

🤖 *AUTONOMOUS IMPROVEMENT RECOMMENDATIONS*

✅ No autonomous improvements needed. System optimally configured.

=== Signal Quality ===
✅ All clean
```

### SoDEX Governor (expectancy gate)
```

```

## 3. PAIR-LEVEL ANALYSIS

| Pair | Divisi | 7d n | 7d WR | 7d Expectancy | p-value | Action |
|------|--------|------|-------|---------------|---------|--------|
| *auto-populated from research* | | | | | | |

**Block Candidates (WR<40%, n≥20, p<0.05 BH-FDR):**
- *auto-populated*

**Boost Candidates (WR>60%, n≥20, E>0):**
- *auto-populated*

**Expired Gates (p>0.05, n≥50):**
- *auto-populated*

## 4. REGIME ACCURACY (HMM BULL/BEAR/CHOP)

```
=== Deep Loop Learning State ===
Vetoed:  []
Boosted: []

Per-path details:
```

| Regime | 7d Trades | WR | Expectancy | Gate Accuracy |
|--------|-----------|-----|------------|---------------|
| BULL | *auto* | *auto* | *auto* | *auto* |
| BEAR | *auto* | *auto* | *auto* | *auto* |
| CHOP | *auto* | *auto* | *auto* | *auto* |

## 5. MACRO POLICY EFFECTIVENESS

- **Current Level:** NORMAL
- **Event:** FOMC
- **T-24h Entry Reduction:** *measure entry_rate_pre_event / entry_rate_normal*
- **Active Window Blocked Entries:** *count where block_new_entries=True*
- **SoDEX Capital Reduction:** capital_mult=1.0 during events
- **Loss Avoided Estimate:** *counterfactual PnL during macro stress vs normal*

## 6. PARAMETER CHANGE PROPOSALS (Evidence-Based)

| Proposal | Divisi | Evidence (n, WR, p-value, BH-FDR, OOS) | Impact Estimate | Status |
|----------|--------|----------------------------------------|-----------------|--------|
| *Example: Block AAVE* | SoDEX | n=28, WR=35%, p=0.012, BH-FDR=0.045, OOS=-$45 | Reduce loss ~$45/wk | ⏳ Pending |
| *Example: Lower CEX threshold* | CEX | n=156, WR=41%→44%, p=0.03, OOS +$120 | Improve WR | ⏳ Pending |

**ALL PROPOSALS REQUIRE:**
- Backtest OOS evidence (min n≥30)
- Test suite PASS
- Pre-Deploy Review Protocol
- Manager approval untuk parameter fundamental

## 7. RISK & COMPLIANCE

- **dry_run CEX:** TRUE (paper only) ✅
- **SAFETY_HALT SoDEX:** INACTIVE
- **Macro Policy Compliance:** CEX threshold_mult applied, SoDEX capital_mult applied
- **No dry_run=false changes** without Owner approval
- **No shuffle=true** on time-series data
- **No credential exposure** in logs/outputs
