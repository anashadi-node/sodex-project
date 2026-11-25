# DAILY REPORT — SoDEX + CEX-Binance
**Date:** 2026-09-30 (UTC)
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

- **NFP**: 37.5h (UTC: 2026-10-02 12:30)

## 📈 CEX BINANCE FUTURES (Paper)

```
🟢 *CEX Binance USDM Futures Swing Paper* — 2026-09-30T23:00 UTC
━━━━━━━━━━━━━━━━━━━━━
  SIGNAL : n=189 open=0 WR=41% E=+0.17% PF=1.23
  RANDOM : n=260 open=2 WR=42% E=+0.17% PF=1.20
```

## 📈 CEX BINANCE SPOT (Paper)

```
🟢 *CEX Spot Swing Paper (SPOT murni)* — 2026-09-30T23:00 UTC
━━━━━━━━━━━━━━━━━━━━━
*SIGNAL* open: 0
*RANDOM* open: 2
  PENDLE random dir=1 entry=2.371 hold=6.6h
  TRX random dir=1 entry=0.3382 hold=6.4h
*SPOT-OFI-long closed*: n=49 | WR=26.5% | Σ=$-11.05 (modal $400: -2.76%)
Target: ≥ +0.7% modal/window (1-30h, akumulasi)
```

## 🔄 SODEX RECOVERY MONITOR

```
SoDEX recovery monitor: NORMAL | wallet=243.42846920246046 source=verified_snapshot target_usd=1.947428 issues=0
Wrote /home/USER/anantara-sakti/reports/SODEX_RECOVERY_MONITOR_LATEST.md
Wrote /home/USER/anantara-sakti/reports/SODEX_RECOVERY_MONITOR_LATEST.json
```

## 📊 SODEX MONITOR EVALUATION

```
SODEX MONITORING & EVALUASI (READ-ONLY)
ts_utc        : 2026-09-30T23:00:25.976706+00:00
window        : 26 September 2026 - 3 Oktober 2026 (weekly 3 sodex)
snapshot      : 3 Oktober 2026 07:00 WIB
status        : FAIL
reasons       : account_api_not_ok, weekly_volume_below_target, weekly_win_rate_missing, volume_fee_ratio_below_target
risk_score    : 60 / ORANGE
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
ledger_total_usd    : 8,184.24
ledger_weighted_usd : 16,368.49
ledger_spot_usd     : 8,184.24
ledger_perps_usd    : 0.00
delta_total_usd     : -140,068.47
realized_pnl_usd    : +0.000000
fees_usd            : 2.578037
volume_to_fee_ratio : 1:3,174.60
rt_count/win_rate   : 0 / 0.00%

REAL ACCOUNT NOW
total_equity_usd    : 244.336870
free_usd_total      : 234.248252
spot_equity_usd     : 58.367116
perps_account_value : 185.969754
open_positions      : 0

SENSITIVE MONITOR SIGNALS
- account_api_degraded (+18) {'quality': 'PARTIAL'}
- stale_last_fill (+22) {'age_min': 1396.72}
- official_dashboard_degraded (+12) {'quality': 'STALE_OR_EMPTY'}
- weekly_verdict_fail (+8) {'reasons': ['account_api_not_ok', 'weekly_volume_below_target', 'weekly_win_rate_missing', 'volume_fee_ratio_below_target']}

AUTO-REPAIR PLAN
- STALE_FILL_OBSERVED_NO_RESTART [MEDIUM] ['stale_last_fill']
- CHECK_API_CONNECTIVITY [MEDIUM] ['account_api_degraded']

WARNINGS
- no closed RTs in current weekly window
- rt_rows_unverifiable_excluded:325
- /spot/accounts/0x4a464b82b1c1233791351483c90c53e2a2fbc799/trades:HTTP_429
- missing_api_sections:spot_trades
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
