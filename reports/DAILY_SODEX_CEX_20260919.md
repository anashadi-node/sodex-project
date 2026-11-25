# DAILY REPORT — SoDEX + CEX-Binance
**Date:** 2026-09-19 (UTC)
**Generated:** 23:00 UTC

## 📊 EXECUTIVE SUMMARY

- **SoDEX Target:** ≥0.7% total wallet/window (1-30h)
- **CEX Target:** ≥0.7% total wallet/window (1-30h, paper)

## 🌍 MACRO CONTEXT

- **Current Policy:** NORMAL
- **Event:** NFP
- **Pre-event T-24h:** NO
- **Active Window:** NO
- **Block New Entries:** NO
- **CEX Threshold Mult:** 1.0x
- **SoDEX Capital Mult:** 1.0x
- **SoDEX Spread Add:** 0.0%
- **Reason:** macro normal

## 📅 NEXT MACRO EVENTS (48h)


## 📈 CEX BINANCE FUTURES (Paper)

```
🟢 *CEX Binance USDM Futures Swing Paper* — 2026-09-19T23:00 UTC
━━━━━━━━━━━━━━━━━━━━━
  SIGNAL : n=189 open=0 WR=41% E=+0.17% PF=1.23
  RANDOM : n=209 open=2 WR=43% E=+0.17% PF=1.21
```

## 📈 CEX BINANCE SPOT (Paper)

```
🟢 *CEX Spot Swing Paper (SPOT murni)* — 2026-09-19T23:00 UTC
━━━━━━━━━━━━━━━━━━━━━
*SIGNAL* open: 0
*RANDOM* open: 3
  TRX random dir=1 entry=0.3385 hold=23.9h
  JUP random dir=1 entry=0.2778 hold=8.9h
  ETH random dir=1 entry=2627.84 hold=0.3h
*SPOT-OFI-long closed*: n=49 | WR=26.5% | Σ=$-11.05 (modal $400: -2.76%)
Target: ≥ +0.7% modal/window (1-30h, akumulasi)
```

## 🔄 SODEX RECOVERY MONITOR

```
SoDEX recovery monitor: NORMAL | wallet=173.33792125561047 source=verified_snapshot target_usd=1.213365 issues=0
Wrote /home/USER/anantara-sakti/reports/SODEX_RECOVERY_MONITOR_LATEST.md
Wrote /home/USER/anantara-sakti/reports/SODEX_RECOVERY_MONITOR_LATEST.json
```

## 📊 SODEX MONITOR EVALUATION

```
SODEX MONITORING & EVALUASI (READ-ONLY)
ts_utc        : 2026-09-19T23:00:14.067369+00:00
window        : 19 September 2026 - 26 September 2026 (weekly 26 sodex)
snapshot      : 26 September 2026 07:00 WIB
status        : FAIL
reasons       : weekly_volume_below_target, weekly_win_rate_missing
risk_score    : 36 / YELLOW
repair_signal : False
ledger_quality: OK
api_quality   : OK
telegram      : OK / ok
live_kills    : REALWIDE_LIVE_KILL, SPOT_LIVE_KILL

OFFICIAL SODEX DASHBOARD VOLUME
quality             : STALE_OR_EMPTY
source              : sodex.com/points screenshot
official_total_usd  : 148,252.71
official_spot_usd   : 132,732.25
official_futures_usd: 15,520.46

INTERNAL LEDGER AUDIT
ledger_total_usd    : 0.00
ledger_weighted_usd : 0.00
ledger_spot_usd     : 0.00
ledger_perps_usd    : 0.00
delta_total_usd     : 0.00
realized_pnl_usd    : +0.000000
fees_usd            : 0.000000
volume_to_fee_ratio : 1:0.00
rt_count/win_rate   : 0 / 0.00%

REAL ACCOUNT NOW
total_equity_usd    : 173.202655
free_usd_total      : 110.017987
spot_equity_usd     : 63.184669
perps_account_value : 110.017986
open_positions      : 0

SENSITIVE MONITOR SIGNALS
- no_weekly_fills (+16) {}
- official_dashboard_degraded (+12) {'quality': 'STALE_OR_EMPTY'}
- weekly_verdict_fail (+8) {'reasons': ['weekly_volume_below_target', 'weekly_win_rate_missing']}

AUTO-REPAIR PLAN
- HALT_ACTIVE_NO_RESTART [HIGH] ['SAFETY_HALT']
- LIVE_KILL_ACTIVE_NO_TRADING [HIGH] ['REALWIDE_LIVE_KILL', 'SPOT_LIVE_KILL']

WARNINGS
- no ledger fills in current weekly window
- no closed RTs in current weekly window
- no_fills_this_window
- no_closed_rts_this_window
- official_dashboard_window_mismatch

saved_latest : /home/USER/anantara-sakti/data/sodex_monitor_eval/latest.json
```

## ⚠️ ANOMALIES & ACTION ITEMS

- 🔴 **SAFETY_HALT ACTIVE**: {
  "ts": "2026-08-01T07:43:15.663418+00:00",
  "source": "sodex_twin_engine",
  "reason": "loss-cap"
}
- 🟡 CEX Futures SIGNAL WR (41%) < RANDOM WR (43%) — expectancy positive but win rate lagging
- 🔴 CEX Spot OFI-long WR 26.5% — deeply negative, DO NOT LIVE
- 🔴 SoDEX Monitor Eval: FAIL (weekly_volume_below_target, weekly_win_rate_missing)
- 🟡 SoDEX Risk Score: 36/YELLOW (improved from 54/ORANGE)

## 🛡️ RISK SUMMARY

- **dry_run CEX:** TRUE (paper only)
- **SAFETY_HALT:** ACTIVE
- **SoDEX Real Positions:** Check watchdog output
- **Macro Policy:** NORMAL
