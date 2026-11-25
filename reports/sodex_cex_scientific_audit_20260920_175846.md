# SoDEX + CEX Scientific Audit

Generated UTC: 2026-09-20T17:58:46.931166+00:00
## 1. Data sources loaded
- `data/paper_test_realwide_state.json`: type=dict extracted_trades=159 size=89343
- `data/paper_test_shortbear_state.json`: type=dict extracted_trades=15 size=12830
- `data/realwide_micro_live_state.json`: type=dict extracted_trades=1 size=1790
- `data/spot_live_test_state.json`: type=dict extracted_trades=1 size=618
- `data/paper_test_spot_swing_cex.json`: type=dict extracted_trades=401 size=215710
- `data/paper_test_spot_swing_cex_spot.json`: type=dict extracted_trades=102 size=57645
- `data/paper_test_spot_swing_cex_trades.jsonl`: type=list extracted_trades=401 size=117096
- `data/paper_test_spot_swing_cex_spot_trades.jsonl`: type=list extracted_trades=102 size=30244

## 2. Service/timer liveness
- `anantara-realwide-livetest.service`: active=active, enabled=enabled
- `anantara-spot-livetest.service`: active=active, enabled=enabled
- `anantara-paper-realwide.service`: active=active, enabled=enabled
- `sodex-monitor-eval.timer`: active=active, enabled=enabled
- `anantara-sodex-watchdog.timer`: active=active, enabled=enabled
- `anantara-sodex-realsync.timer`: active=active, enabled=enabled
- `cex-momadx-isolated-gate.timer`: active=active, enabled=enabled
- `cex-spot-momadx-isolated-gate.timer`: active=active, enabled=enabled

## 3. Aggregate edge metrics (bootstrap falsification)
- **ALL**: n=1182 WR=41.5% total=+1.9953 mean=+0.0017 PF=1.19 CI95_mean=[+0.0002,+0.0032] P(E>0)=98.9%
- **SRC data/paper_test_realwide_state.json**: n=159 WR=52.2% total=+1.0395 mean=+0.0065 PF=1.46 CI95_mean=[-0.0003,+0.0138] P(E>0)=96.9%
- **SRC data/paper_test_shortbear_state.json**: n=15 WR=66.7% total=-0.0080 mean=-0.0005 PF=0.88 CI95_mean=[-0.0052,+0.0036] P(E>0)=42.7%
- **SRC data/paper_test_spot_swing_cex.json**: n=401 WR=41.6% total=+0.6223 mean=+0.0016 PF=1.20 CI95_mean=[-0.0004,+0.0035] P(E>0)=94.4%
- **SRC data/paper_test_spot_swing_cex_spot.json**: n=102 WR=30.4% total=-0.1368 mean=-0.0013 PF=0.86 CI95_mean=[-0.0057,+0.0031] P(E>0)=26.4%
- **SRC data/paper_test_spot_swing_cex_spot_trades.jsonl**: n=102 WR=30.4% total=-0.1368 mean=-0.0013 PF=0.86 CI95_mean=[-0.0057,+0.0031] P(E>0)=25.9%
- **SRC data/paper_test_spot_swing_cex_trades.jsonl**: n=401 WR=41.6% total=+0.6223 mean=+0.0016 PF=1.20 CI95_mean=[-0.0004,+0.0035] P(E>0)=94.6%
- **SRC data/realwide_micro_live_state.json**: n=1 WR=0.0% total=-0.0092 mean=-0.0092 PF=0.00
- **SRC data/spot_live_test_state.json**: n=1 WR=100.0% total=+0.0021 mean=+0.0021 PF=inf

## 4. Track / side / exit reason Pareto

### TRACK
- TRACK ?: n=176 WR=53.4% total=+1.0244 mean=+0.0058 PF=1.44 CI95_mean=[-0.0005,+0.0127] P(E>0)=96.2%
- TRACK RANDOM: n=516 WR=41.5% total=+0.6850 mean=+0.0013 PF=1.16 CI95_mean=[-0.0005,+0.0033] P(E>0)=92.0%
- TRACK SIGNAL: n=490 WR=37.1% total=+0.2859 mean=+0.0006 PF=1.07 CI95_mean=[-0.0011,+0.0023] P(E>0)=75.0%

### SIDE
- SIDE ?: n=81 WR=85.2% total=+1.2149 mean=+0.0150 PF=7.91 CI95_mean=[+0.0118,+0.0180] P(E>0)=100.0%
- SIDE L: n=159 WR=52.2% total=+1.0395 mean=+0.0065 PF=1.46 CI95_mean=[-0.0005,+0.0140] P(E>0)=96.1%
- SIDE SHORT: n=15 WR=66.7% total=-0.0080 mean=-0.0005 PF=0.88 CI95_mean=[-0.0053,+0.0039] P(E>0)=42.5%
- SIDE LONG: n=1 WR=0.0% total=-0.0092 mean=-0.0092 PF=0.00
- SIDE 1: n=614 WR=36.2% total=-0.0551 mean=-0.0001 PF=0.99 CI95_mean=[-0.0017,+0.0015] P(E>0)=45.9%
- SIDE -1: n=312 WR=34.0% total=-0.1868 mean=-0.0006 PF=0.93 CI95_mean=[-0.0028,+0.0017] P(E>0)=29.8%

### REASON
- REASON TP: n=320 WR=100.0% total=+8.4751 mean=+0.0265 PF=inf CI95_mean=[+0.0253,+0.0276] P(E>0)=100.0%
- REASON ?: n=174 WR=53.4% total=+1.0315 mean=+0.0059 PF=1.45 CI95_mean=[-0.0003,+0.0127] P(E>0)=96.8%
- REASON TIME_STOP: n=150 WR=50.7% total=+0.2516 mean=+0.0017 PF=1.54 CI95_mean=[+0.0000,+0.0034] P(E>0)=97.6%
- REASON SYSTEM_UPGRADE: n=18 WR=0.0% total=+0.0000 mean=+0.0000 PF=0.00 CI95_mean=[+0.0000,+0.0000] P(E>0)=0.0%
- REASON TIME_30h: n=2 WR=50.0% total=-0.0071 mean=-0.0035 PF=0.23 CI95_mean=[-0.0092,+0.0021] P(E>0)=24.5%
- REASON EMERGENCY_SL: n=264 WR=0.0% total=-3.0349 mean=-0.0115 PF=0.00 CI95_mean=[-0.0121,-0.0109] P(E>0)=0.0%
- REASON SL: n=254 WR=0.0% total=-4.7210 mean=-0.0186 PF=0.00 CI95_mean=[-0.0194,-0.0178] P(E>0)=0.0%

## 5. Symbol Pareto (toxic / productive)

### Worst symbols
- SYM ONDO: n=20 WR=30.0% total=-0.2556 mean=-0.0128 PF=0.24 CI95_mean=[-0.0209,-0.0042] P(E>0)=0.3%
- SYM SUI: n=25 WR=28.0% total=-0.2161 mean=-0.0086 PF=0.42 CI95_mean=[-0.0173,+0.0004] P(E>0)=3.2%
- SYM ADA: n=80 WR=37.5% total=-0.1979 mean=-0.0025 PF=0.77 CI95_mean=[-0.0072,+0.0025] P(E>0)=15.7%
- SYM ENA: n=35 WR=31.4% total=-0.1302 mean=-0.0037 PF=0.71 CI95_mean=[-0.0122,+0.0072] P(E>0)=20.8%
- SYM TSLA: n=8 WR=0.0% total=-0.1302 mean=-0.0163 PF=0.00 CI95_mean=[-0.0168,-0.0157] P(E>0)=0.0%
- SYM NVDA: n=10 WR=0.0% total=-0.1300 mean=-0.0130 PF=0.00 CI95_mean=[-0.0157,-0.0100] P(E>0)=0.0%
- SYM BCH: n=52 WR=28.8% total=-0.0886 mean=-0.0017 PF=0.81 CI95_mean=[-0.0068,+0.0036] P(E>0)=26.4%
- SYM GOOGL: n=6 WR=33.3% total=-0.0647 mean=-0.0108 PF=0.05 CI95_mean=[-0.0170,-0.0046] P(E>0)=0.1%
- SYM SILVER: n=5 WR=40.0% total=-0.0545 mean=-0.0109 PF=0.11 CI95_mean=[-0.0235,+0.0014] P(E>0)=4.4%
- SYM NEAR: n=36 WR=27.8% total=-0.0537 mean=-0.0015 PF=0.85 CI95_mean=[-0.0085,+0.0061] P(E>0)=34.4%
- SYM XAUT: n=17 WR=11.8% total=-0.0498 mean=-0.0029 PF=0.27 CI95_mean=[-0.0052,-0.0002] P(E>0)=1.7%
- SYM TRX: n=11 WR=45.5% total=-0.0443 mean=-0.0040 PF=0.31 CI95_mean=[-0.0091,+0.0011] P(E>0)=5.5%
- SYM JUP: n=12 WR=33.3% total=-0.0429 mean=-0.0036 PF=0.81 CI95_mean=[-0.0229,+0.0175] P(E>0)=34.1%
- SYM LINK: n=62 WR=27.4% total=-0.0387 mean=-0.0006 PF=0.93 CI95_mean=[-0.0065,+0.0059] P(E>0)=41.7%
- SYM MU: n=8 WR=25.0% total=-0.0198 mean=-0.0025 PF=0.16 CI95_mean=[-0.0063,+0.0005] P(E>0)=6.7%

### Best symbols
- SYM SOL: n=104 WR=41.3% total=+0.5685 mean=+0.0055 PF=1.76 CI95_mean=[+0.0006,+0.0110] P(E>0)=98.7%
- SYM UNI: n=44 WR=45.5% total=+0.3948 mean=+0.0090 PF=1.80 CI95_mean=[-0.0024,+0.0216] P(E>0)=93.8%
- SYM BTC: n=94 WR=52.1% total=+0.3927 mean=+0.0042 PF=1.74 CI95_mean=[+0.0003,+0.0084] P(E>0)=98.3%
- SYM ETH: n=87 WR=54.0% total=+0.3509 mean=+0.0040 PF=1.61 CI95_mean=[-0.0005,+0.0088] P(E>0)=96.2%
- SYM PUMP: n=23 WR=47.8% total=+0.3007 mean=+0.0131 PF=3.10 CI95_mean=[+0.0005,+0.0279] P(E>0)=97.9%
- SYM LIT: n=14 WR=42.9% total=+0.2303 mean=+0.0165 PF=4.15 CI95_mean=[+0.0012,+0.0322] P(E>0)=98.3%
- SYM AAVE: n=31 WR=54.8% total=+0.2033 mean=+0.0066 PF=1.81 CI95_mean=[-0.0027,+0.0158] P(E>0)=91.2%
- SYM BNB: n=31 WR=48.4% total=+0.1881 mean=+0.0061 PF=2.13 CI95_mean=[-0.0024,+0.0162] P(E>0)=90.4%
- SYM AVAX: n=45 WR=46.7% total=+0.1802 mean=+0.0040 PF=1.56 CI95_mean=[-0.0027,+0.0120] P(E>0)=86.3%
- SYM ASTER: n=21 WR=52.4% total=+0.1528 mean=+0.0073 PF=1.87 CI95_mean=[-0.0060,+0.0228] P(E>0)=84.7%
- SYM PENDLE: n=34 WR=35.3% total=+0.1527 mean=+0.0045 PF=1.57 CI95_mean=[-0.0033,+0.0126] P(E>0)=87.3%
- SYM ZEC: n=60 WR=36.7% total=+0.1313 mean=+0.0022 PF=1.19 CI95_mean=[-0.0051,+0.0095] P(E>0)=71.8%
- SYM TAO: n=8 WR=50.0% total=+0.1184 mean=+0.0148 PF=6.22 CI95_mean=[-0.0002,+0.0298] P(E>0)=97.5%
- SYM HYPE: n=42 WR=47.6% total=+0.0831 mean=+0.0020 PF=1.23 CI95_mean=[-0.0045,+0.0084] P(E>0)=73.6%
- SYM HOOD: n=12 WR=66.7% total=+0.0481 mean=+0.0040 PF=1.71 CI95_mean=[-0.0050,+0.0127] P(E>0)=81.9%

## 6. Duplicate / inflated-n check
- normalized_trade_rows=1182 pnl_rows=1182 duplicate_extra_rows=9
- DUP x4: ('data/paper_test_shortbear_state.json', 'BTC', 'SHORT', None, None, None, None, None)
- DUP x3: ('data/paper_test_shortbear_state.json', 'SOL', 'SHORT', None, None, None, None, None)
- DUP x3: ('data/paper_test_shortbear_state.json', 'DOGE', 'SHORT', None, None, None, None, None)
- DUP x2: ('data/paper_test_shortbear_state.json', 'UNI', 'SHORT', None, None, None, None, None)
- DUP x2: ('data/paper_test_shortbear_state.json', 'XRP', 'SHORT', None, None, None, None, None)

## 7. Open position snapshot
- `data/paper_test_realwide_state.json` open: n=1 sample={'TRX': {'sym': 'TRX', 'side': 'L', 'entry_p': 0.3407, 'entry_ts': 1789858965.3820765, 'entry_iso': '2026-09-19T23:02:45.382077+00:00', 'regime': 'MOMENTUM_RELAXED', 'conviction': 0.6, 'btc_regime': 'BULL', 'tp': 0.06, 'sl': 0.015, 'lev': 3, 'peak_g': 0.018197828001174005}}
- `data/paper_test_shortbear_state.json` open: n=0 sample={}
- `data/realwide_micro_live_state.json` open: n=0 sample={}
- `data/spot_live_test_state.json` open: n=0 sample={}

## 8. Recent log gate/error counts (tail-window approx)

### `logs/adaptive_gate_applier.log` size=776199
counts={'gate': 2767}
```
adaptive_gate diterapkan: long_min=50.5 short_max=48.0 (iteration 10796)
adaptive_gate diterapkan: long_min=50.5 short_max=48.0 (iteration 10797)
adaptive_gate diterapkan: long_min=50.5 short_max=48.0 (iteration 10798)
adaptive_gate diterapkan: long_min=50.5 short_max=48.0 (iteration 10799)
adaptive_gate diterapkan: long_min=50.5 short_max=48.0 (iteration 10800)
adaptive_gate diterapkan: long_min=50.5 short_max=48.0 (iteration 10801)
adaptive_gate diterapkan: long_min=50.5 short_max=48.0 (iteration 10802)
adaptive_gate diterapkan: long_min=50.5 short_max=48.0 (iteration 10803)
adaptive_gate diterapkan: long_min=50.5 short_max=48.0 (iteration 10804)
adaptive_gate diterapkan: long_min=50.5 short_max=48.0 (iteration 10805)
adaptive_gate diterapkan: long_min=50.5 short_max=48.0 (iteration 10806)
adaptive_gate diterapkan: long_min=50.5 short_max=48.0 (iteration 10807)
```

### `logs/capital_report.log` size=1092960
counts={'HALT': 493, 'ERROR': 3}
```
   vBTC: 0.00 (~$12.12)
   vETH: 0.00 (~$6.26)
   vARB: 0.75 (~$0.15)
   vAVAX: 0.01 (~$0.08)
   vXLM: 0.22 (~$0.04)

🤖 Daemon: 🔴 STOPPED
🛑 Safety: clear
🛡️  Monitoring: 🔴 ISSUES

<i>Report otomatis — Anantara Sakti Capital Guard</i>
[2026-09-20 23:00:43 WIB] DONE: Equity $173.18 | Net 6h: $0.0000
```

### `logs/deadman_switch.log` size=243
counts={'HALT': 4}
```
[2026-09-18 17:58:03Z] DEADMAN: NO_RESTART_HALT_ACTIVE: fill_age=82702m hb_age=69735.1m policy=SAFETY_HALT_ACTIVE
[2026-09-20 14:39:46Z] DEADMAN: NO_RESTART_HALT_ACTIVE: fill_age=85384m hb_age=72416.8m policy=SAFETY_HALT_SHORT_PILOT_CANDIDATE
```

### `logs/fomc_window_monitor.log` size=526306
counts={'ERROR': 4}
```
[2026-09-19 02:29:08 UTC] INFO: CEX macro policy not yet visible in recent logs (may be normal if no entry attempt)
[2026-09-19 02:29:08 UTC] INFO: CEX macro policy not yet visible in recent logs (may be normal if no entry attempt)
[2026-09-19 02:29:08 UTC] SoDEX: regime=DANGER_ZONE macro_level=NORMAL capital_mult=1.0 spread_add=0.0 trade_ok=True cb_ok=True
[2026-09-19 02:29:08 UTC] SoDEX: regime=DANGER_ZONE macro_level=NORMAL capital_mult=1.0 spread_add=0.0 trade_ok=True cb_ok=True
[2026-09-19 02:29:08 UTC] FOMC: 951.50h until event | pre_event=False active_window=False
[2026-09-19 02:29:08 UTC] FOMC: 951.50h until event | pre_event=False active_window=False
[2026-09-19 02:34:10 UTC] INFO: CEX macro policy not yet visible in recent logs (may be normal if no entry attempt)
[2026-09-19 02:34:10 UTC] INFO: CEX macro policy not yet visible in recent logs (may be normal if no entry attempt)
[2026-09-19 02:34:10 UTC] SoDEX: regime=DANGER_ZONE macro_level=NORMAL capital_mult=1.0 spread_add=0.0 trade_ok=True cb_ok=True
[2026-09-19 02:34:10 UTC] SoDEX: regime=DANGER_ZONE macro_level=NORMAL capital_mult=1.0 spread_add=0.0 trade_ok=True cb_ok=True
[2026-09-19 02:34:10 UTC] FOMC: 951.40h until event | pre_event=False active_window=False
[2026-09-19 02:34:10 UTC] FOMC: 951.40h until event | pre_event=False active_window=False
```

### `logs/funding_carry_factor_error.log` size=80375
counts={'ERROR': 67, 'opened': 2}
```
2026-09-20 13:37:05,597 [funding-carry] INFO: [funding-carry] 4 active, total_pnl_pct=-0.47% cycle=4
2026-09-20 14:37:06,592 [funding-carry] INFO: [funding-carry] 4 active, total_pnl_pct=+0.13% cycle=4
2026-09-20 15:37:07,500 [funding-carry] INFO: [funding-carry] 4 active, total_pnl_pct=-0.62% cycle=4
2026-09-20 16:37:08,371 [funding-carry] INFO: [funding-carry] 4 active, total_pnl_pct=-0.96% cycle=4
2026-09-20 17:37:09,170 [funding-carry] INFO: [funding-carry] 4 active, total_pnl_pct=-0.71% cycle=4
2026-09-20 18:37:10,025 [funding-carry] INFO: [funding-carry] 4 active, total_pnl_pct=-0.42% cycle=4
2026-09-20 19:37:16,888 [funding-carry] INFO: [funding-carry] 4 active, total_pnl_pct=+1.08% cycle=4
2026-09-20 20:37:34,110 [funding-carry] INFO: [funding-carry] 4 active, total_pnl_pct=+1.32% cycle=4
2026-09-20 21:37:34,900 [funding-carry] INFO: [funding-carry] 4 active, total_pnl_pct=+0.90% cycle=4
2026-09-20 22:37:35,667 [funding-carry] INFO: [funding-carry] 4 active, total_pnl_pct=+1.20% cycle=4
2026-09-20 23:37:36,398 [funding-carry] INFO: [funding-carry] 4 active, total_pnl_pct=-0.93% cycle=4
2026-09-21 00:37:37,126 [funding-carry] INFO: [funding-carry] 4 active, total_pnl_pct=+0.54% cycle=4
```

### `logs/ofi_breadth_factor_error.log` size=6493
counts={'ERROR': 1}
```
2026-09-04 01:24:29,244 [ofi-breadth] INFO: [ofi-breadth] cycle heartbeat — using backtest-validated params
2026-09-04 02:24:29,244 [ofi-breadth] INFO: [ofi-breadth] cycle heartbeat — using backtest-validated params
2026-09-04 03:24:29,244 [ofi-breadth] INFO: [ofi-breadth] cycle heartbeat — using backtest-validated params
2026-09-04 04:24:29,245 [ofi-breadth] INFO: [ofi-breadth] cycle heartbeat — using backtest-validated params
2026-09-04 05:24:29,245 [ofi-breadth] INFO: [ofi-breadth] cycle heartbeat — using backtest-validated params
2026-09-04 06:24:29,245 [ofi-breadth] INFO: [ofi-breadth] cycle heartbeat — using backtest-validated params
2026-09-04 07:24:29,245 [ofi-breadth] INFO: [ofi-breadth] cycle heartbeat — using backtest-validated params
2026-09-04 08:24:29,245 [ofi-breadth] INFO: [ofi-breadth] cycle heartbeat — using backtest-validated params
2026-09-04 09:06:15,119 [ofi-breadth] INFO: OFI Breadth live loop — interval 3600s
2026-09-04 09:06:15,119 [ofi-breadth] INFO: Backtest verified: PF 1.47, net +0.43% across 510 OOS trades
2026-09-04 09:06:15,119 [ofi-breadth] INFO: Live mode: monitoring mid-cap pairs for OFI signals
2026-09-04 09:06:15,120 [ofi-breadth] INFO: [ofi-breadth] cycle heartbeat — using backtest-validated params
```

### `logs/orderflow_capture_error.log` size=796056
counts={'ERROR': 610, 'Traceback': 609}
```
Traceback (most recent call last):
  File "/home/USER/anantara-sakti/scripts/orderflow_capture_service.py", line 15, in <module>
    import orderflow_capture as oc
  File "/home/USER/anantara-sakti/scripts/orderflow_capture.py", line 15, in <module>
    import websocket
ModuleNotFoundError: No module named 'websocket'
Traceback (most recent call last):
  File "/home/USER/anantara-sakti/scripts/orderflow_capture_service.py", line 15, in <module>
    import orderflow_capture as oc
  File "/home/USER/anantara-sakti/scripts/orderflow_capture.py", line 15, in <module>
    import websocket
ModuleNotFoundError: No module named 'websocket'
```

### `logs/paper_cex_momadx.log` size=66153
counts={'KILL': 39, 'blocked': 37, 'gate': 596, 'opened': 296}
```
  [REGIME] BTC=CHOP
  [KILL] Futures SIGNAL entries blocked; existing positions still managed
  [ISOLATED] instance riset terpisah — only_paths=['momentum+adx+regime'] ledger=trades.jsonl gate=gate.json
[spot-swing] 2026-09-20T17:45:31+00:00 opened=[] open_total=0 signal=9 random=7
  [REGIME] BTC=CHOP
  [KILL] Futures SIGNAL entries blocked; existing positions still managed
  [ISOLATED] instance riset terpisah — only_paths=['momentum+adx+regime'] ledger=trades.jsonl gate=gate.json
[spot-swing] 2026-09-20T17:50:35+00:00 opened=[] open_total=0 signal=9 random=7
  [REGIME] BTC=CHOP
  [KILL] Futures SIGNAL entries blocked; existing positions still managed
  [ISOLATED] instance riset terpisah — only_paths=['momentum+adx+regime'] ledger=trades.jsonl gate=gate.json
[spot-swing] 2026-09-20T17:55:38+00:00 opened=[] open_total=0 signal=9 random=7
```

### `logs/paper_cex_spot_momadx.log` size=21303
counts={'KILL': 2, 'gate': 4, 'opened': 291}
```
[spot-swing-spot] 2026-09-20T16:59:36+00:00 opened=[] n_sig=7 n_rnd=5
[spot-swing-spot] 2026-09-20T17:04:40+00:00 opened=[] n_sig=7 n_rnd=5
[spot-swing-spot] 2026-09-20T17:09:45+00:00 opened=[] n_sig=7 n_rnd=5
[spot-swing-spot] 2026-09-20T17:14:48+00:00 opened=[] n_sig=7 n_rnd=5
[spot-swing-spot] 2026-09-20T17:19:52+00:00 opened=[] n_sig=7 n_rnd=5
[spot-swing-spot] 2026-09-20T17:24:56+00:00 opened=[] n_sig=7 n_rnd=5
[spot-swing-spot] 2026-09-20T17:29:59+00:00 opened=[] n_sig=7 n_rnd=5
[spot-swing-spot] 2026-09-20T17:35:06+00:00 opened=[] n_sig=7 n_rnd=5
[spot-swing-spot] 2026-09-20T17:40:09+00:00 opened=[] n_sig=7 n_rnd=5
[spot-swing-spot] 2026-09-20T17:45:14+00:00 opened=[] n_sig=7 n_rnd=5
[spot-swing-spot] 2026-09-20T17:50:17+00:00 opened=[] n_sig=7 n_rnd=5
[spot-swing-spot] 2026-09-20T17:55:21+00:00 opened=[] n_sig=7 n_rnd=5
```

### `logs/paper_learning_watchdog.log` size=2515998
counts={'ERROR': 7}
```
IVE:🟡0.2% · PERPS-SHORT:🔴0.0%
[paper-watchdog] INFO: enrichment: file kosong (grace — daemon baru, menunggu cycle)
[paper-watchdog] INFO: high-edge: SWING:🟢1.7% · SWING-PARTIAL:🟢1.3% · SPOT-SWING:🔴0.0% · REAL-wide:🟢1.8% · COMBINED:🔴0.0% · COMBINED-SCS:🔴0.0% · TWO-WAY:🟢2.2% · FAST:🔴0.0% · DONCHIAN:🟢2.8% · SPOT-SWING-CEX:🟡1.7% · SPOT-LIVE:🟡0.2% · PERPS-SHORT:🔴0.0%
[paper-watchdog] SEMUA SEHAT ✅ enrichment: file kosong (grace — daemon baru, menunggu cycle) | high-edge: SWING:🟢1.7% · SWING-PARTIAL:🟢1.3% · SPOT-SWING:🔴0.0% · REAL-wide:🟢1.8% · COMBINED:🔴0.0% · COMBINED-SCS:🔴0.0% · TWO-WAY:🟢2.2% · FAST:🔴0.0% · DONCHIAN:🟢2.8% · SPOT-SWING-CEX:🟡1.7% · SPOT-LIVE:🟡0.2% · PERPS-SHORT:🔴0.0%
[paper-watchdog] INFO: enrichment: file kosong (grace — daemon baru, menunggu cycle)
[paper-watchdog] INFO: high-edge: SWING:🟢1.7% · SWING-PARTIAL:🟢1.3% · SPOT-SWING:🔴0.0% · REAL-wide:🟢1.8% · COMBINED:🔴0.0% · COMBINED-SCS:🔴0.0% · TWO-WAY:🟢2.2% · FAST:🔴0.0% · DONCHIAN:🟢2.8% · SPOT-SWING-CEX:🟡1.7% · SPOT-LIVE:🟡0.2% · PERPS-SHORT:🔴0.0%
[paper-watchdog] SEMUA SEHAT ✅ enrichment: file kosong (grace — daemon baru, menunggu cycle) | high-edge: SWING:🟢1.7% · SWING-PARTIAL:🟢1.3% · SPOT-SWING:🔴0.0% · REAL-wide:🟢1.8% · COMBINED:🔴0.0% · COMBINED-SCS:🔴0.0% · TWO-WAY:🟢2.2% · FAST:🔴0.0% · DONCHIAN:🟢2.8% · SPOT-SWING-CEX:🟡1.7% · SPOT-LIVE:🟡0.2% · PERPS-SHORT:🔴0.0%
[paper-watchdog] INFO: enrichment: file kosong (grace — daemon baru, menunggu cycle)
[paper-watchdog] INFO: high-edge: SWING:🟢1.7% · SWING-PARTIAL:🟢1.3% · SPOT-SWING:🔴0.0% · REAL-wide:🟢1.8% · COMBINED:🔴0.0% · COMBINED-SCS:🔴0.0% · TWO-WAY:🟢2.2% · FAST:🔴0.0% · DONCHIAN:🟢2.8% · SPOT-SWING-CEX:🟡1.7% · SPOT-LIVE:🟡0.2% · PERPS-SHORT:🔴0.0%
[paper-watchdog] SEMUA SEHAT ✅ enrichment: file kosong (grace — daemon baru, menunggu cycle) | high-edge: SWING:🟢1.7% · SWING-PARTIAL:🟢1.3% · SPOT-SWING:🔴0.0% · REAL-wide:🟢1.8% · COMBINED:🔴0.0% · COMBINED-SCS:🔴0.0% · TWO-WAY:🟢2.2% · FAST:🔴0.0% · DONCHIAN:🟢2.8% · SPOT-SWING-CEX:🟡1.7% · SPOT-LIVE:🟡0.2% · PERPS-SHORT:🔴0.0%
```

### `logs/paper_test_combined_error.log` size=2340
counts={'ERROR': 12, 'Traceback': 12}
```
Traceback (most recent call last):
  File "/home/USER/anantara-sakti/scripts/paper_test_combined.py", line 31, in <module>
    import numpy as np
ModuleNotFoundError: No module named 'numpy'
Traceback (most recent call last):
  File "/home/USER/anantara-sakti/scripts/paper_test_combined.py", line 31, in <module>
    import numpy as np
ModuleNotFoundError: No module named 'numpy'
Traceback (most recent call last):
  File "/home/USER/anantara-sakti/scripts/paper_test_combined.py", line 31, in <module>
    import numpy as np
ModuleNotFoundError: No module named 'numpy'
```

### `logs/paper_test_combined_scs_error.log` size=484621
counts={'ERROR': 633, 'Traceback': 13, 'gate': 1}
```
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404
2026-08-29 08:14:37,926 WARNING sentiment: Liquidations fetch failed (retry in 60 min): Client error '404 Not Found' for url 'https://fapi.binance.com/futures/data/allForceOrders?symbol=BTCUSDT&limit=100'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404
2026-08-29 08:55:03,480 WARNING sentiment: Global fetch failed: Client error '429 Too Many Requests' for url 'https://api.coingecko.com/api/v3/global'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/429
2026-08-29 09:00:20,197 WARNING sentiment: Global fetch failed: 
2026-08-29 09:15:25,217 WARNING sentiment: Liquidations fetch failed (retry in 60 min): Client error '404 Not Found' for url 'https://fapi.binance.com/futures/data/allForceOrders?symbol=BTCUSDT&limit=100'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404
2026-08-29 09:27:11,253 WARNING sentiment: Liquidations fetch failed (retry in 60 min): Client error '404 Not Found' for url 'https://fapi.binance.com/futures/data/allForceOrders?symbol=BTCUSDT&limit=100'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404
2026-08-29 09:37:08,968 WARNING sentiment: Liquidations fetch failed (retry in 60 min): Client error '404 Not Found' for url 'https://fapi.binance.com/futures/data/allForceOrders?symbol=BTCUSDT&limit=100'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404
```

### `logs/paper_test_donchian_error.log` size=681
counts={'ERROR': 3, 'Traceback': 3}
```
                        ~~^^^
KeyError: 'HYPE'
Traceback (most recent call last):
  File "/home/USER/anantara-sakti/scripts/paper_test_donchian.py", line 78, in <module>
    _FUTURES_SYMBOLS = {BN[c] for c in FUTURES_ONLY}
                        ~~^^^
KeyError: 'HYPE'
Traceback (most recent call last):
  File "/home/USER/anantara-sakti/scripts/paper_test_donchian.py", line 78, in <module>
    _FUTURES_SYMBOLS = {BN[c] for c in FUTURES_ONLY}
                        ~~^^^
KeyError: 'HYPE'
```

### `logs/paper_test_fast.log` size=5361124
counts={'skip': 555, 'gate': 555}
```
  State: 173t WR:43% PnL:$-23 Open:4
  State: 173t WR:43% PnL:$-23 Open:4
  State: 173t WR:43% PnL:$-23 Open:4
  State: 173t WR:43% PnL:$-23 Open:4
  State: 173t WR:43% PnL:$-23 Open:4
  State: 173t WR:43% PnL:$-23 Open:4
  State: 173t WR:43% PnL:$-23 Open:4
  State: 173t WR:43% PnL:$-23 Open:4
  State: 173t WR:43% PnL:$-23 Open:4
  State: 173t WR:43% PnL:$-23 Open:4
  State: 173t WR:43% PnL:$-23 Open:4
  State: 173t WR:43% PnL:$-23 Open:4
```

### `logs/paper_test_fast_error.log` size=10505
counts={'ERROR': 55, 'Traceback': 55}
```
Traceback (most recent call last):
  File "/home/USER/anantara-sakti/scripts/paper_test_fast.py", line 29, in <module>
    import numpy as np
ModuleNotFoundError: No module named 'numpy'
Traceback (most recent call last):
  File "/home/USER/anantara-sakti/scripts/paper_test_fast.py", line 29, in <module>
    import numpy as np
ModuleNotFoundError: No module named 'numpy'
Traceback (most recent call last):
  File "/home/USER/anantara-sakti/scripts/paper_test_fast.py", line 29, in <module>
    import numpy as np
ModuleNotFoundError: No module named 'numpy'
```

### `logs/paper_test_learning.log` size=238294
counts={'gate': 1640}
```
✅ Laporan pembelajaran: /home/USER/anantara-sakti/docs/PAPER_TEST_LEARNING_REPORT.md
✅ Data pembelajaran: /home/USER/anantara-sakti/data/paper_test_learning.json
✅ Edge-gate: /home/USER/anantara-sakti/data/paper_test_edge_gate.json
✅ Laporan pembelajaran: /home/USER/anantara-sakti/docs/PAPER_TEST_LEARNING_REPORT.md
✅ Data pembelajaran: /home/USER/anantara-sakti/data/paper_test_learning.json
✅ Edge-gate: /home/USER/anantara-sakti/data/paper_test_edge_gate.json
✅ Laporan pembelajaran: /home/USER/anantara-sakti/docs/PAPER_TEST_LEARNING_REPORT.md
✅ Data pembelajaran: /home/USER/anantara-sakti/data/paper_test_learning.json
✅ Edge-gate: /home/USER/anantara-sakti/data/paper_test_edge_gate.json
✅ Laporan pembelajaran: /home/USER/anantara-sakti/docs/PAPER_TEST_LEARNING_REPORT.md
✅ Data pembelajaran: /home/USER/anantara-sakti/data/paper_test_learning.json
✅ Edge-gate: /home/USER/anantara-sakti/data/paper_test_edge_gate.json
```

### `logs/paper_test_learning_error.log` size=2233
counts={'ERROR': 11, 'Traceback': 11}
```
Traceback (most recent call last):
  File "/home/USER/anantara-sakti/scripts/paper_test_learning.py", line 27, in <module>
    import requests as _req
ModuleNotFoundError: No module named 'requests'
Traceback (most recent call last):
  File "/home/USER/anantara-sakti/scripts/paper_test_learning.py", line 27, in <module>
    import requests as _req
ModuleNotFoundError: No module named 'requests'
Traceback (most recent call last):
  File "/home/USER/anantara-sakti/scripts/paper_test_learning.py", line 27, in <module>
    import requests as _req
ModuleNotFoundError: No module named 'requests'
```

### `logs/paper_test_realwide.log` size=3696498
counts={}
```
[2026-09-20T17:45:19.968269+00:00] [EXIT] TRX:HOLD +0.88% 18.7h
[2026-09-20T17:46:34.796226+00:00] [EXIT] TRX:HOLD +0.79% 18.7h
[2026-09-20T17:47:41.417306+00:00] [ENTRY+EXIT] TRX:HOLD +0.85% 18.7h
[2026-09-20T17:48:50.712059+00:00] [EXIT] TRX:HOLD +0.85% 18.8h
[2026-09-20T17:49:55.384908+00:00] [EXIT] TRX:HOLD +0.82% 18.8h
[2026-09-20T17:51:05.008954+00:00] [EXIT] TRX:HOLD +0.82% 18.8h
[2026-09-20T17:52:10.079924+00:00] [EXIT] TRX:HOLD +0.79% 18.8h
[2026-09-20T17:53:16.821306+00:00] [ENTRY+EXIT] TRX:HOLD +0.82% 18.8h
[2026-09-20T17:54:21.374761+00:00] [EXIT] TRX:HOLD +0.82% 18.9h
[2026-09-20T17:55:27.567212+00:00] [EXIT] TRX:HOLD +0.82% 18.9h
[2026-09-20T17:56:32.231544+00:00] [EXIT] TRX:HOLD +0.79% 18.9h
[2026-09-20T17:57:41.896999+00:00] [EXIT] TRX:HOLD +0.82% 18.9h
```

### `logs/paper_test_realwide_error.log` size=143093
counts={'ERROR': 273, 'Traceback': 273, 'gate': 1}
```
               ~~~~~~^^^^
IndexError: index -1 is out of bounds for axis 0 with size 0
Traceback (most recent call last):
  File "/home/USER/anantara-sakti/scripts/paper_test_realwide.py", line 448, in <module>
    main()
  File "/home/USER/anantara-sakti/scripts/paper_test_realwide.py", line 432, in main
    hits = cycle(st, dry=a.dry, do_entries=_do_entries)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/USER/anantara-sakti/scripts/paper_test_realwide.py", line 314, in cycle
    if not d or not d.get("c") or len(d.get("c") or []) == 0:
                    ^^^^^^^^^^
ValueError: The truth value of an array with more than one element is ambiguous. Use a.any() or a.all()
```

### `logs/paper_test_realwide_watchdog.log` size=9075247
counts={'ERROR': 2}
```
[2026-09-20 17:57:14Z] REAL-wide healthy n=159
[2026-09-20 17:57:14Z] REAL-wide healthy n=159
[2026-09-20 17:57:15Z] TWO-WAY progress n=265 pf=1.44
[2026-09-20 17:57:15Z] TWO-WAY progress n=265 pf=1.44
[2026-09-20 17:57:16Z] TWO-WAY healthy n=265
[2026-09-20 17:57:16Z] TWO-WAY healthy n=265
[2026-09-20 17:57:16Z] DONCHIAN healthy n=114
[2026-09-20 17:57:16Z] DONCHIAN healthy n=114
[2026-09-20 17:57:16Z] SPOT-LIVE healthy lines=14
[2026-09-20 17:57:16Z] SPOT-LIVE healthy lines=14
[2026-09-20 17:57:16Z] PERPS-SHORT down -> restart
[2026-09-20 17:57:16Z] PERPS-SHORT down -> restart
```

### `logs/paper_test_shortbear.log` size=499907
counts={'ERROR': 9}
```
[2026-09-20T17:29:25] SCAN ok=6 err=0 signal=0 open=0
[2026-09-20T17:29:25] FUNNEL sufficient=6 bear_stack=0 chk4=0 r1neg=0 candidate=0 max_chk=2
[2026-09-20T17:34:27] SCAN ok=6 err=0 signal=0 open=0
[2026-09-20T17:34:27] FUNNEL sufficient=6 bear_stack=0 chk4=0 r1neg=0 candidate=0 max_chk=2
[2026-09-20T17:39:29] SCAN ok=6 err=0 signal=0 open=0
[2026-09-20T17:39:29] FUNNEL sufficient=6 bear_stack=0 chk4=0 r1neg=0 candidate=0 max_chk=2
[2026-09-20T17:44:31] SCAN ok=6 err=0 signal=0 open=0
[2026-09-20T17:44:31] FUNNEL sufficient=6 bear_stack=0 chk4=0 r1neg=0 candidate=0 max_chk=2
[2026-09-20T17:49:33] SCAN ok=6 err=0 signal=0 open=0
[2026-09-20T17:49:33] FUNNEL sufficient=6 bear_stack=0 chk4=0 r1neg=0 candidate=0 max_chk=2
[2026-09-20T17:54:34] SCAN ok=6 err=0 signal=0 open=0
[2026-09-20T17:54:34] FUNNEL sufficient=6 bear_stack=0 chk4=0 r1neg=0 candidate=0 max_chk=2
```

### `logs/paper_test_shortbear_variants.log` size=129299
counts={'ERROR': 357}
```
[2026-09-20T17:01:09] SCAN variants=7 pairs=6
[2026-09-20T17:06:15] SCAN variants=7 pairs=6
[2026-09-20T17:11:22] SCAN variants=7 pairs=6
[2026-09-20T17:16:24] SCAN variants=7 pairs=6
[2026-09-20T17:21:26] SCAN variants=7 pairs=6
[2026-09-20T17:26:27] SCAN variants=7 pairs=6
[2026-09-20T17:31:29] SCAN variants=7 pairs=6
[2026-09-20T17:36:31] SCAN variants=7 pairs=6
[2026-09-20T17:41:33] SCAN variants=7 pairs=6
[2026-09-20T17:46:35] SCAN variants=7 pairs=6
[2026-09-20T17:51:37] SCAN variants=7 pairs=6
[2026-09-20T17:56:39] SCAN variants=7 pairs=6
```

### `logs/paper_test_spot_swing_cex.log` size=1076746
counts={'KILL': 1122, 'blocked': 1122, 'opened': 1122}
```
  [REGIME] BTC=CHOP
  [KILL] Futures SIGNAL entries blocked; existing positions still managed
[spot-swing] 2026-09-20T17:42:46+00:00 opened=[] open_total=0 signal=189 random=212
  [REGIME] BTC=CHOP
  [KILL] Futures SIGNAL entries blocked; existing positions still managed
[spot-swing] 2026-09-20T17:47:50+00:00 opened=[] open_total=0 signal=189 random=212
  [REGIME] BTC=CHOP
  [KILL] Futures SIGNAL entries blocked; existing positions still managed
[spot-swing] 2026-09-20T17:52:55+00:00 opened=[] open_total=0 signal=189 random=212
  [REGIME] BTC=CHOP
  [KILL] Futures SIGNAL entries blocked; existing positions still managed
[spot-swing] 2026-09-20T17:57:59+00:00 opened=[] open_total=0 signal=189 random=212
```

### `logs/paper_test_spot_swing_cex_error.log` size=242607
counts={'ERROR': 995, 'Traceback': 995}
```
Traceback (most recent call last):
  File "/home/USER/anantara-sakti/scripts/paper_test_spot_swing_cex.py", line 34, in <module>
    import numpy as np
ModuleNotFoundError: No module named 'numpy'
Traceback (most recent call last):
  File "/home/USER/anantara-sakti/scripts/paper_test_spot_swing_cex.py", line 34, in <module>
    import numpy as np
ModuleNotFoundError: No module named 'numpy'
Traceback (most recent call last):
  File "/home/USER/anantara-sakti/scripts/paper_test_spot_swing_cex.py", line 34, in <module>
    import numpy as np
ModuleNotFoundError: No module named 'numpy'
```

### `logs/paper_test_spot_swing_cex_spot.log` size=129452
counts={'opened': 1791}
```
[spot-swing-spot] 2026-09-20T17:00:59+00:00 opened=[] n_sig=56 n_rnd=46
[spot-swing-spot] 2026-09-20T17:06:03+00:00 opened=[] n_sig=56 n_rnd=46
[spot-swing-spot] 2026-09-20T17:11:07+00:00 opened=[] n_sig=56 n_rnd=46
[spot-swing-spot] 2026-09-20T17:16:12+00:00 opened=[] n_sig=56 n_rnd=46
[spot-swing-spot] 2026-09-20T17:21:26+00:00 opened=[] n_sig=56 n_rnd=46
[spot-swing-spot] 2026-09-20T17:26:30+00:00 opened=[] n_sig=56 n_rnd=46
[spot-swing-spot] 2026-09-20T17:31:39+00:00 opened=[] n_sig=56 n_rnd=46
[spot-swing-spot] 2026-09-20T17:36:44+00:00 opened=[] n_sig=56 n_rnd=46
[spot-swing-spot] 2026-09-20T17:41:48+00:00 opened=[] n_sig=56 n_rnd=46
[spot-swing-spot] 2026-09-20T17:46:57+00:00 opened=[] n_sig=56 n_rnd=46
[spot-swing-spot] 2026-09-20T17:52:01+00:00 opened=[] n_sig=56 n_rnd=46
[spot-swing-spot] 2026-09-20T17:57:10+00:00 opened=[] n_sig=56 n_rnd=46
```

## 9. SQLite inventory

### `data/sodex_public_trades.db` size=74747904
- trades: rows=447480, cols=['symbol', 'trade_id', 'ts', 'side', 'price', 'qty']

### `data/twin_engine.pre_ledger_repair_20260720T1236WIB.db` size=18153472
- fills: rows=68839, cols=['id', 'ts', 'engine', 'bucket', 'pair', 'side', 'price', 'qty', 'notional', 'fee', 'maker', 'rt_id']
- rts: rows=15092, cols=['rt_id', 'ts_close', 'engine', 'pair', 'volume', 'net_pnl']
- state: rows=111, cols=['k', 'v']
- weekly_points: rows=0, cols=['week_sat', 'points', 'note']
- e2_open_pos: rows=0, cols=['id', 'pair', 'side', 'qty', 'entry_px', 'opened_ts']
- sqlite_sequence: rows=2, cols=['name', 'seq']
- e2_dir_signals: rows=92, cols=['id', 'pair', 'side', 'grade', 'funding_rate', 'obi', 'entry_px', 'exit_px', 'qty', 'pnl', 'exit_reason', 'opened_ts']

### `data/sodex_book_recorder.db` size=218566656
- l1: rows=2076660, cols=['ts', 'symbol', 'bid', 'ask', 'bid_sz', 'ask_sz', 'last']

### `data/twin_engine.pre_sol_external_repair_20260720T1814WIB.db` size=18153472
- fills: rows=68861, cols=['id', 'ts', 'engine', 'bucket', 'pair', 'side', 'price', 'qty', 'notional', 'fee', 'maker', 'rt_id']
- rts: rows=15103, cols=['rt_id', 'ts_close', 'engine', 'pair', 'volume', 'net_pnl']
- state: rows=116, cols=['k', 'v']
- weekly_points: rows=0, cols=['week_sat', 'points', 'note']
- e2_open_pos: rows=0, cols=['id', 'pair', 'side', 'qty', 'entry_px', 'opened_ts']
- sqlite_sequence: rows=2, cols=['name', 'seq']
- e2_dir_signals: rows=92, cols=['id', 'pair', 'side', 'grade', 'funding_rate', 'obi', 'entry_px', 'exit_px', 'qty', 'pnl', 'exit_reason', 'opened_ts']

### `freqtrade_user_data/tradesv3.dryrun.sqlite` size=81920
- KeyValueStore: rows=0, cols=['id', 'key', 'value_type', 'string_value', 'datetime_value', 'float_value', 'int_value']
- trades: rows=0, cols=['id', 'exchange', 'pair', 'base_currency', 'stake_currency', 'is_open', 'fee_open', 'fee_open_cost', 'fee_open_currency', 'fee_close', 'fee_close_cost', 'fee_close_currency']
- pairlocks: rows=0, cols=['id', 'pair', 'side', 'reason', 'lock_time', 'lock_end_time', 'active']
- trade_custom_data: rows=0, cols=['id', 'ft_trade_id', 'cd_key', 'cd_type', 'cd_value', 'created_at', 'updated_at']
- orders: rows=0, cols=['id', 'ft_trade_id', 'ft_order_side', 'ft_pair', 'ft_is_open', 'ft_amount', 'ft_price', 'ft_cancel_reason', 'order_id', 'status', 'symbol', 'order_type']

### `data/chroma/chroma.sqlite3` size=655360
- migrations: rows=18, cols=['dir', 'version', 'filename', 'sql', 'hash']
- acquire_write: rows=941, cols=['id', 'lock_status']
- collection_metadata: rows=1, cols=['collection_id', 'key', 'str_value', 'int_value', 'float_value', 'bool_value']
- segment_metadata: rows=0, cols=['segment_id', 'key', 'str_value', 'int_value', 'float_value', 'bool_value']
- tenants: rows=1, cols=['id']
- databases: rows=1, cols=['id', 'name', 'tenant_id']
- collections: rows=1, cols=['id', 'name', 'dimension', 'database_id', 'config_json_str', 'schema_str']
- maintenance_log: rows=0, cols=['id', 'timestamp', 'operation']
- segments: rows=2, cols=['id', 'type', 'scope', 'collection']
- embeddings: rows=2, cols=['id', 'segment_id', 'embedding_id', 'seq_id', 'created_at']

## 10. Scientific conclusions / next hypotheses
- Aggregate edge belum terfalsifikasi: CI95 mean > 0. Kandidat exploit throughput, tetap per-track split.
- Constraint utama yang dicari: gate drag vs throughput vs exit geometry. Rekomendasi hanya boleh diambil dari split dengan n cukup dan bootstrap tidak negatif.
- Safety yang mempercepat target: fail-closed unknown state, tetapi block harus surgical: pair/direction/reason yang terbukti buruk; jangan kill seluruh track kalau trunk masih positif.
