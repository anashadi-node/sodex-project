# SoDEX Approved Recommendations — Validation Run 2026-09-17 23:45 WIB

## Executed
- Read-only validation after user approved recommendations.
- No production param changed; no live path touched.
- Tested realwide toxic-pair filtering + SHORT-BEAR exit/pair evidence.

## Realwide OOS walk-forward
- Chronological split: train=93, test=40.
- Test baseline: n=40 WR=30.0% PF=0.10 avg_wallet=-1.559% target=2.5% avg_pct=-0.825%.

| k | block from train worst | test result | removed_test |
|---:|---|---|---:|
| 1 | `['ADA']` | n=38 WR=31.6% PF=0.11 avg_wallet=-1.482% target=2.6% avg_pct=-0.784% | 2 |
| 2 | `['ADA', 'HYPE']` | n=36 WR=30.6% PF=0.10 avg_wallet=-1.507% target=2.8% avg_pct=-0.797% | 4 |
| 3 | `['ADA', 'HYPE', 'SUI']` | n=32 WR=34.4% PF=0.13 avg_wallet=-1.292% target=3.1% avg_pct=-0.683% | 8 |
| 4 | `['ADA', 'HYPE', 'SUI', 'ONDO']` | n=30 WR=36.7% PF=0.15 avg_wallet=-1.172% target=3.3% avg_pct=-0.620% | 10 |
| 5 | `['ADA', 'HYPE', 'SUI', 'ONDO', 'AVAX']` | n=29 WR=37.9% PF=0.15 avg_wallet=-1.211% target=3.4% avg_pct=-0.641% | 11 |
| 8 | `['ADA', 'HYPE', 'SUI', 'ONDO', 'AVAX', 'AAVE', 'ASTER', 'ENA']` | n=26 WR=30.8% PF=0.12 avg_wallet=-1.398% target=3.8% avg_pct=-0.739% | 14 |

## Full-sample realwide filter check (NOT deployment proof)
| Filter | Result | Bootstrap mean CI95 wallet | Removed |
|---|---|---|---:|
| `['none']` | n=133 WR=48.9% PF=1.41 avg_wallet=0.629% target=29.3% avg_pct=0.333% | 0.629% [-0.165%, 1.437%] | 0 |
| `['SUI']` | n=126 WR=50.8% PF=1.56 avg_wallet=0.820% target=31.0% avg_pct=0.434% | 0.820% [-0.013%, 1.678%] | 7 |
| `['SUI', 'ADA', 'ONDO']` | n=114 WR=52.6% PF=1.83 avg_wallet=1.132% target=34.2% avg_pct=0.599% | 1.132% [0.272%, 2.049%] | 19 |
| `['SUI', 'ADA', 'ONDO', 'HYPE']` | n=108 WR=53.7% PF=1.98 avg_wallet=1.287% target=35.2% avg_pct=0.681% | 1.287% [0.333%, 2.248%] | 25 |
| `['SUI', 'ADA', 'ONDO', 'HYPE', 'SILVER', 'XRP', 'TRX', 'BCH']` | n=93 WR=57.0% PF=2.26 avg_wallet=1.661% target=39.8% avg_pct=0.878% | 1.661% [0.592%, 2.771%] | 40 |

## SHORT-BEAR evidence
- Overall: n=15 WR=66.7% PF=0.91 avg_wallet=-0.053% target=6.7% avg_pct=-0.051%.
- Exit `MR_EXIT`: n=10 WR=100.0% PF=inf avg_wallet=0.570% target=10.0% avg_pct=0.768%.
- Exit `SL`: n=5 WR=0.0% PF=0.00 avg_wallet=-1.300% target=0.0% avg_pct=-1.690%.
- MR_EXIT target hits: 1/10; winner avg remains below target.

## Decision
- **Do not hard-block realwide pairs yet.** Full sample suggests SUI/ADA/ONDO/HYPE are toxic, but OOS split does not prove robust improvement; recent test window is weak overall.
- **Treat SUI/ADA/ONDO/HYPE as BLOCK_CANDIDATE only**, monitor forward until each has n≥20 or walk-forward confirms.
- **Keep SHORT-BEAR paper-only.** Excluding UNI/XRP/BTC improves PF but target ROI remains below 0.7%; MR_EXIT exits winners too early.
- **No SL/TP/leverage change yet**; next step must be research-only MR_EXIT ladder simulation/backtest.

## Next controlled actions
1. Add/read-only monitor report for block candidates SUI/ADA/ONDO/HYPE, not production veto.
2. Run MR_EXIT ladder simulation using historical OHLCV or enriched telemetry; acceptance: winner wallet_avg ≥0.9%, PF>1.2, n≥30.
3. If validation passes: write failing tests first, then implement minimal gate/exit change, then Pre-Deploy Review.

## SHORT-BEAR telemetry replay: profit-threshold ladder (research-only)
- Episodes reconstructed from telemetry: 8. Caveat: 5-min sampled replay, not tick/OHLC intrabar exact.
| Profit threshold | Result |
|---:|---|
| 0.5% | n=8, WR=75.0%, PF=1.21, avg_wallet=0.083%, target_rate=37.5%, avg_hold=2.6h |
| 0.6% | n=8, WR=75.0%, PF=1.24, avg_wallet=0.094%, target_rate=37.5%, avg_hold=3.7h |
| 0.7% | n=8, WR=75.0%, PF=1.31, avg_wallet=0.121%, target_rate=37.5%, avg_hold=4.8h |
| 0.8% | n=8, WR=75.0%, PF=1.42, avg_wallet=0.165%, target_rate=50.0%, avg_hold=5.2h |
| 0.9% | n=8, WR=75.0%, PF=1.42, avg_wallet=0.165%, target_rate=50.0%, avg_hold=5.2h |
| 1.0% | n=8, WR=75.0%, PF=1.42, avg_wallet=0.165%, target_rate=50.0%, avg_hold=5.2h |
| 1.2% | n=8, WR=75.0%, PF=1.42, avg_wallet=0.165%, target_rate=50.0%, avg_hold=5.2h |
| 1.5% | n=8, WR=75.0%, PF=1.42, avg_wallet=0.165%, target_rate=50.0%, avg_hold=5.2h |

Decision: MR_EXIT threshold alone does not pass target. Combo `block UNI+XRP` + profit threshold 0.9–1.2% is promising (n=6, avg_wallet=0.746%, target_rate=66.7%) but **not actionable yet** because n<30 and replay is 5-min sampled, not tick/OHLC exact. Keep SHORT-BEAR paper-only and collect more data.
