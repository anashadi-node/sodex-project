# DAILY REPORT — SoDEX + CEX-Binance
**Date:** 2026-11-24 (UTC)
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

```

## 📈 CEX BINANCE SPOT (Paper)

```

```

## 🔄 SODEX RECOVERY MONITOR

```
SoDEX recovery monitor: NORMAL | wallet=242.6585815930613 source=verified_snapshot target_usd=1.941269 issues=0
Wrote /home/USER/anantara-sakti/reports/SODEX_RECOVERY_MONITOR_LATEST.md
Wrote /home/USER/anantara-sakti/reports/SODEX_RECOVERY_MONITOR_LATEST.json
Appended /home/USER/anantara-sakti/reports/sodex/RECOVERY_MONITOR_HISTORY.jsonl
```

## 📊 SODEX MONITOR EVALUATION

```
SODEX MONITORING & EVALUASI (READ-ONLY)
ts_utc        : 2026-11-24T23:00:06.974074+00:00
window        : 21 November 2026 - 28 November 2026 (weekly 28 sodex)
snapshot      : 28 November 2026 07:00 WIB
status        : FAIL
reasons       : weekly_volume_below_target, weekly_win_rate_missing
risk_score    : 54 / ORANGE
repair_signal : False
ledger_quality: OK
api_quality   : OK
telegram      : OK / ok
live_kills    : -

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
total_equity_usd    : 243.311663
free_usd_total      : 218.713580
spot_equity_usd     : 25.091660
perps_account_value : 218.220003
open_positions      : 2

SENSITIVE MONITOR SIGNALS
- no_weekly_fills (+16) {}
- official_dashboard_degraded (+12) {'quality': 'STALE_OR_EMPTY'}
- open_positions_with_stale_fills (+18) {'open_positions': 2, 'fill_age_min': None}
- weekly_verdict_fail (+8) {'reasons': ['weekly_volume_below_target', 'weekly_win_rate_missing']}

AUTO-REPAIR PLAN
- OPERATOR_POSITION_RECONCILIATION_REQUIRED [HIGH] ['open_positions_with_stale_fills']

WARNINGS
- no ledger fills in current weekly window
- no closed RTs in current weekly window
- no_fills_this_window
- no_closed_rts_this_window
- official_dashboard_window_mismatch

saved_latest : /home/USER/anantara-sakti/data/sodex_monitor_eval/latest.json
```

## ⚠️ ANOMALIES & ACTION ITEMS

- 🔴 SoDEX Monitor Eval: FAIL (weekly_volume_below_target, weekly_win_rate_missing)

## 🛡️ RISK SUMMARY

- **dry_run CEX:** TRUE (paper only)
- **SAFETY_HALT:** INACTIVE
- **SoDEX Real Positions:** Check watchdog output
- **Macro Policy:** NORMAL
