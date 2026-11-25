# DAILY REPORT — SoDEX + CEX-Binance
**Date:** 2026-11-20 (UTC)
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
SoDEX recovery monitor: NORMAL | wallet=231.0982622323927 source=verified_snapshot target_usd=1.848786 issues=0
Wrote /home/USER/anantara-sakti/reports/SODEX_RECOVERY_MONITOR_LATEST.md
Wrote /home/USER/anantara-sakti/reports/SODEX_RECOVERY_MONITOR_LATEST.json
Appended /home/USER/anantara-sakti/reports/sodex/RECOVERY_MONITOR_HISTORY.jsonl
```

## 📊 SODEX MONITOR EVALUATION

```
SODEX MONITORING & EVALUASI (READ-ONLY)
ts_utc        : 2026-11-20T23:00:49.669646+00:00
window        : 14 November 2026 - 21 November 2026 (weekly 21 sodex)
snapshot      : 21 November 2026 07:00 WIB
status        : FAIL
reasons       : account_api_not_ok, weekly_volume_below_target, weekly_win_rate_missing
risk_score    : 80 / RED
repair_signal : False
ledger_quality: OK
api_quality   : API_UNAVAILABLE
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
total_equity_usd    : 0.000000
free_usd_total      : 0.000000
spot_equity_usd     : 0.000000
perps_account_value : 0.000000
open_positions      : 0

SENSITIVE MONITOR SIGNALS
- account_api_degraded (+18) {'quality': 'API_UNAVAILABLE'}
- no_weekly_fills (+16) {}
- official_dashboard_degraded (+12) {'quality': 'STALE_OR_EMPTY'}
- position_truth_not_verified (+26) {'quality': 'UNVERIFIED', 'positions_endpoint_count': 0, 'state_P_count': 0}
- weekly_verdict_fail (+8) {'reasons': ['account_api_not_ok', 'weekly_volume_below_target', 'weekly_win_rate_missing']}

AUTO-REPAIR PLAN
- OPERATOR_POSITION_RECONCILIATION_REQUIRED [HIGH] ['position_truth_not_verified']
- CHECK_API_CONNECTIVITY [MEDIUM] ['account_api_degraded']

WARNINGS
- no ledger fills in current weekly window
- no closed RTs in current weekly window
- /perps/accounts/0x4a464b82b1c1233791351483c90c53e2a2fbc799/state:HTTP_429
- /perps/accounts/0x4a464b82b1c1233791351483c90c53e2a2fbc799/balances:HTTP_429
- /perps/accounts/0x4a464b82b1c1233791351483c90c53e2a2fbc799/positions:HTTP_429
- /perps/accounts/0x4a464b82b1c1233791351483c90c53e2a2fbc799/trades:HTTP_429
- /perps/accounts/0x4a464b82b1c1233791351483c90c53e2a2fbc799/fundings:HTTP_429
- /perps/accounts/0x4a464b82b1c1233791351483c90c53e2a2fbc799/fee-rate:HTTP_429
- /spot/accounts/0x4a464b82b1c1233791351483c90c53e2a2fbc799/balances:HTTP_429
- /spot/accounts/0x4a464b82b1c1233791351483c90c53e2a2fbc799/trades:HTTP_429
- /spot/markets/tickers:HTTP_429
- /perps/markets/tickers:HTTP_429
- missing_api_sections:perps_state,perps_balances,perps_positions,perps_trades,perps_fundings,fee_rate,spot_balances,spot_trades,spot_tickers,perps_tickers
- position_truth_source_missing
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
