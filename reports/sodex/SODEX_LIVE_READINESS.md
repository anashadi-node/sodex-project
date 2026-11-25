# SoDEX Live Readiness — D0.3 Control Board

Generated UTC: 2026-11-24T23:04:43.117752+00:00
D0.3 run: `20261124T170438Z`

## Verdict
- Live ready: **NO**
- Live order/unfreeze: **NO** until all gates pass + explicit user GO-LIVE approval.
- Current verdict: `T1_FAIL_FORWARD_MONITOR`

## Current blockers
- T1 RISET tracks not passed
- funding/borrow evidence incomplete

## Target distance
- Canonical series: `CANONICAL_D0_2_TRADING_ONLY_GATE_SERIES`
- Normalized delta 48h: $11.796
- Target 48h: $1.945
- Distance to target: +606.646%

## Funding evidence
- Archive rows: `100057`
- Unique symbols: `100`
- Span hours: `1278.9045012183333`
- 24h ETA UTC: `ready`
- Bad rows: `0`
- Funding map verdict: `FAIL_CLOSED`
- Exact/rate-estimated/missing: `0/0/0`
- In-window shorts: `n/a` (ok `n/a` / missing `0`)
- Pre-archive shorts: `n/a` (archive start `n/a`)

## RISET tracks
| Track | n | Passed | Excess mean | Cost 2x mean |
|---|---:|---:|---:|---:|
| swing | 445 | False | -0.165% | -0.325% |
| twoway | 512 | False | +0.029% | -0.131% |
| realwide | 298 | False | -0.112% | -0.272% |

## Timeline gate menuju real live
1. D0.3 — 24h funding archive: collector + loop stabil, no bad rows.
2. D1/T1 — 30d paper, beta-netral, biaya 1x/2x, funding complete, all tracks pass.
3. D2/T2 — rolling 90d Sharpe >= 1,5; still net positive cost 2x.
4. D3/T3 — mesin kedua terukur, korelasi antar-mesin <= 0,3.
5. D4/T4 — implementation shortfall < 25% di paper/live-small rehearsal.
6. GO-LIVE — hanya setelah human approval; start smallest safe size; monitor 30 menit pertama + daily kill-switch.

## Safety locks
- No leverage increase.
- No exit/gate/position-sizing change without backtest/OOS evidence + approval.
- No live order before GO-LIVE decision.
- No target downgrade.
