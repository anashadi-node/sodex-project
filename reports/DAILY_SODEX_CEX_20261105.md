# DAILY REPORT — SoDEX + CEX-Binance
**Date:** 2026-11-05 (UTC)
**Generated:** 23:00 UTC

## 📊 EXECUTIVE SUMMARY

- **SoDEX Target:** ≥0.7% total wallet/window (1-30h)
- **CEX Target:** ≥0.7% total wallet/window (1-30h, paper)

## 🌍 MACRO CONTEXT

- **Current Policy:** YELLOW
- **Event:** NFP
- **Pre-event T-24h:** YES
- **Active Window:** NO
- **Block New Entries:** NO
- **CEX Threshold Mult:** 1.2x
- **SoDEX Capital Mult:** 0.75x
- **SoDEX Spread Add:** 0.04%
- **Reason:** macro pre-event T-24h: NFP in 14.5h

## 📅 NEXT MACRO EVENTS (48h)

- **NFP**: 14.5h (UTC: 2026-11-06 13:30)

## 📈 CEX BINANCE FUTURES (Paper)

```

```

## 📈 CEX BINANCE SPOT (Paper)

```

```

## 🔄 SODEX RECOVERY MONITOR

```
SoDEX recovery monitor: NORMAL | wallet=243.39 source=.env.swing target_usd=1.94712 issues=0
Wrote /home/USER/anantara-sakti/reports/SODEX_RECOVERY_MONITOR_LATEST.md
Wrote /home/USER/anantara-sakti/reports/SODEX_RECOVERY_MONITOR_LATEST.json
Appended /home/USER/anantara-sakti/reports/sodex/RECOVERY_MONITOR_HISTORY.jsonl
```

## 📊 SODEX MONITOR EVALUATION

```
SODEX MONITORING & EVALUASI (READ-ONLY)
ts_utc        : 2026-11-05T23:00:49.900749+00:00
window        : 31 Oktober 2026 - 7 November 2026 (weekly 7 sodex)
snapshot      : 7 November 2026 07:00 WIB
status        : FAIL
reasons       : weekly_volume_below_target, weekly_win_rate_missing
risk_score    : 36 / YELLOW
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
total_equity_usd    : 244.978274
free_usd_total      : 234.238749
spot_equity_usd     : 58.293771
perps_account_value : 186.684503
open_positions      : 0

SENSITIVE MONITOR SIGNALS
- no_weekly_fills (+16) {}
- official_dashboard_degraded (+12) {'quality': 'STALE_OR_EMPTY'}
- weekly_verdict_fail (+8) {'reasons': ['weekly_volume_below_target', 'weekly_win_rate_missing']}

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
- 🟡 SoDEX Risk Score: 36/YELLOW (improved from 54/ORANGE)

## 🛡️ RISK SUMMARY

- **dry_run CEX:** TRUE (paper only)
- **SAFETY_HALT:** INACTIVE
- **SoDEX Real Positions:** Check watchdog output
- **Macro Policy:** Active defensive controls
