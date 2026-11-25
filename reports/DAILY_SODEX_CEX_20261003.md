# DAILY REPORT — SoDEX + CEX-Binance
**Date:** 2026-10-03 (UTC)
**Generated:** 23:00 UTC

## 📊 EXECUTIVE SUMMARY

- **SoDEX Target:** ≥0.7% total wallet/window (1-30h)
- **CEX Target:** ≥0.7% total wallet/window (1-30h, paper)

## 🌍 MACRO CONTEXT

- **Current Policy:** NORMAL
- **Event:** CPI
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
🟢 *CEX Binance USDM Futures Swing Paper* — 2026-10-03T23:00 UTC
━━━━━━━━━━━━━━━━━━━━━
  SIGNAL : n=189 open=0 WR=41% E=+0.17% PF=1.23
  RANDOM : n=272 open=3 WR=42% E=+0.14% PF=1.17
```

## 📈 CEX BINANCE SPOT (Paper)

```
🟢 *CEX Spot Swing Paper (SPOT murni)* — 2026-10-03T23:00 UTC
━━━━━━━━━━━━━━━━━━━━━
*SIGNAL* open: 0
*RANDOM* open: 3
  SUI random dir=1 entry=1.1721 hold=6.0h
  DOGE random dir=1 entry=0.09337 hold=5.7h
  BCH random dir=1 entry=316.4 hold=0.9h
*SPOT-OFI-long closed*: n=49 | WR=26.5% | Σ=$-11.05 (modal $400: -2.76%)
Target: ≥ +0.7% modal/window (1-30h, akumulasi)
```

## 🔄 SODEX RECOVERY MONITOR

```
SoDEX recovery monitor: ALERT | wallet=243.42789906156162 source=verified_snapshot target_usd=1.947423 issues=1
Wrote /home/USER/anantara-sakti/reports/SODEX_RECOVERY_MONITOR_LATEST.md
Wrote /home/USER/anantara-sakti/reports/SODEX_RECOVERY_MONITOR_LATEST.json
```

## 📊 SODEX MONITOR EVALUATION

```
SODEX MONITORING & EVALUASI (READ-ONLY)
ts_utc        : 2026-10-03T23:00:24.412046+00:00
window        : 3 Oktober 2026 - 10 Oktober 2026 (weekly 10 sodex)
snapshot      : 10 Oktober 2026 07:00 WIB
status        : FAIL
reasons       : account_api_not_ok, weekly_volume_below_target, weekly_win_rate_missing
risk_score    : 54 / ORANGE
repair_signal : False
ledger_quality: OK
api_quality   : PARTIAL
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
total_equity_usd    : 244.346987
free_usd_total      : 234.248252
spot_equity_usd     : 58.366650
perps_account_value : 185.980337
open_positions      : 0

SENSITIVE MONITOR SIGNALS
- account_api_degraded (+18) {'quality': 'PARTIAL'}
- no_weekly_fills (+16) {}
- official_dashboard_degraded (+12) {'quality': 'STALE_OR_EMPTY'}
- weekly_verdict_fail (+8) {'reasons': ['account_api_not_ok', 'weekly_volume_below_target', 'weekly_win_rate_missing']}

AUTO-REPAIR PLAN
- CHECK_API_CONNECTIVITY [MEDIUM] ['account_api_degraded']

WARNINGS
- no ledger fills in current weekly window
- no closed RTs in current weekly window
- /spot/accounts/0x4a464b82b1c1233791351483c90c53e2a2fbc799/trades:HTTP_429
- missing_api_sections:spot_trades
- no_fills_this_window
- no_closed_rts_this_window
- official_dashboard_window_mismatch

saved_latest : /home/USER/anantara-sakti/data/sodex_monitor_eval/latest.json
```

## ⚠️ ANOMALIES & ACTION ITEMS

- 🔴 CEX Spot OFI-long WR 26.5% — deeply negative, DO NOT LIVE
- 🔴 SoDEX Monitor Eval: FAIL (weekly_volume_below_target, weekly_win_rate_missing)

## 🛡️ RISK SUMMARY

- **dry_run CEX:** TRUE (paper only)
- **SAFETY_HALT:** INACTIVE
- **SoDEX Real Positions:** Check watchdog output
- **Macro Policy:** NORMAL
