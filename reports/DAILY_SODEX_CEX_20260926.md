# DAILY REPORT — SoDEX + CEX-Binance
**Date:** 2026-09-26 (UTC)
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
🟢 *CEX Binance USDM Futures Swing Paper* — 2026-09-26T23:00 UTC
━━━━━━━━━━━━━━━━━━━━━
  SIGNAL : n=189 open=0 WR=41% E=+0.17% PF=1.23
  RANDOM : n=240 open=3 WR=42% E=+0.18% PF=1.22
```

## 📈 CEX BINANCE SPOT (Paper)

```
🟢 *CEX Spot Swing Paper (SPOT murni)* — 2026-09-26T23:00 UTC
━━━━━━━━━━━━━━━━━━━━━
*SIGNAL* open: 0
*RANDOM* open: 3
  ONDO random dir=1 entry=0.5484 hold=15.2h
  AAVE random dir=1 entry=154.18 hold=15.0h
  UNI random dir=1 entry=9.606 hold=9.8h
*SPOT-OFI-long closed*: n=49 | WR=26.5% | Σ=$-11.05 (modal $400: -2.76%)
Target: ≥ +0.7% modal/window (1-30h, akumulasi)
```

## 🔄 SODEX RECOVERY MONITOR

```
SoDEX recovery monitor: NORMAL | wallet=276.26860049168124 source=verified_snapshot target_usd=1.93388 issues=0
Wrote /home/USER/anantara-sakti/reports/SODEX_RECOVERY_MONITOR_LATEST.md
Wrote /home/USER/anantara-sakti/reports/SODEX_RECOVERY_MONITOR_LATEST.json
```

## 📊 SODEX MONITOR EVALUATION

```
SODEX MONITORING & EVALUASI (READ-ONLY)
ts_utc        : 2026-09-26T23:00:12.802290+00:00
window        : 26 September 2026 - 3 Oktober 2026 (weekly 3 sodex)
snapshot      : 3 Oktober 2026 07:00 WIB
status        : FAIL
reasons       : account_api_not_ok, weekly_volume_below_target, weekly_win_rate_below_target, realized_pnl_negative, volume_fee_ratio_below_target, e1_profit_does_not_cover_e2_fees, combined_pnl_negative
risk_score    : 78 / RED
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
ledger_total_usd    : 338.18
ledger_weighted_usd : 676.37
ledger_spot_usd     : 338.18
ledger_perps_usd    : 0.00
delta_total_usd     : -147,914.53
realized_pnl_usd    : -0.612050
fees_usd            : 0.106528
volume_to_fee_ratio : 1:3,174.60
rt_count/win_rate   : 31 / 6.45%

REAL ACCOUNT NOW
total_equity_usd    : 277.486557
free_usd_total      : 267.587367
spot_equity_usd     : 65.271753
perps_account_value : 212.214803
open_positions      : 1

SENSITIVE MONITOR SIGNALS
- account_api_degraded (+18) {'quality': 'PARTIAL'}
- stale_last_fill (+22) {'age_min': 143.89}
- official_dashboard_degraded (+12) {'quality': 'STALE_OR_EMPTY'}
- open_positions_with_stale_fills (+18) {'open_positions': 1, 'fill_age_min': 143.88678801666669}
- weekly_verdict_fail (+8) {'reasons': ['account_api_not_ok', 'weekly_volume_below_target', 'weekly_win_rate_below_target', 'realized_pnl_negative', 'volume_fee_ratio_below_target', 'e1_profit_does_not_cover_e2_fees', 'combined_pnl_negative']}

AUTO-REPAIR PLAN
- OPERATOR_POSITION_RECONCILIATION_REQUIRED [HIGH] ['open_positions_with_stale_fills']
- CHECK_API_CONNECTIVITY [MEDIUM] ['account_api_degraded']

WARNINGS
- /spot/accounts/0x4a464b82b1c1233791351483c90c53e2a2fbc799/trades:HTTP_429
- missing_api_sections:spot_trades
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
