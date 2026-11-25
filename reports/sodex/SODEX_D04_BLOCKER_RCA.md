# SoDEX D0.4 — Forward-Funded T1 Re-evaluation + Blocker RCA

Generated UTC: 2026-11-24T23:04:43.460622+00:00
Harness run: 2026-11-24T23:04:41.761954+00:00
Fee assumption: 8.0 bps per leg-stress step

## Verdict
- T1 status: **FAIL**
- RCA verdict: `T1_FAIL_BLOCKER_RCA_READY`
- Forward funding archive: `READY` (1284.91 h, 100657 rows)
- Live order/unfreeze: **NO** until T1 passes + explicit GO-LIVE approval

## Per-track blocker RCA

| Track | n | WR% | Gross bps | 1x bps | 2x bps | Fee drag bps | DSR | Failing checks |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| swing | 445 | 34.83 | -16.49 | -24.49 | -32.49 | -8.00 | 0.0000 | 4 |
| twoway | 512 | 41.41 | 2.92 | -5.08 | -13.08 | -8.00 | 0.0060 | 4 |
| realwide | 298 | 39.6 | -11.24 | -19.24 | -27.24 | -8.00 | 0.0001 | 4 |

### Failing checks detail

**swing** (n=445, passed=False)
- `net_pos_1x` — need > 8.0 bps gross, gap 24.49 bps
- `net_pos_2x` — need > 16.0 bps gross, gap 32.49 bps
- `ci95_lower_positive` — need CI95 low > 0, gap 31.24 bps
- `dsr_passed` — need DSR >= 0.95, gap 0.95 bps
- worst contributors: ASTER(15×-84.98bps), PUMP(18×-66.54bps), SUI(28×-41.65bps), ONDO(24×-42.09bps), BCH(21×-44.46bps)

**twoway** (n=512, passed=False)
- `net_pos_1x` — need > 8.0 bps gross, gap 5.08 bps
- `net_pos_2x` — need > 16.0 bps gross, gap 13.08 bps
- `ci95_lower_positive` — need CI95 low > 0, gap 15.03 bps
- `dsr_passed` — need DSR >= 0.95, gap 0.944 bps
- worst contributors: ETH(47×-32.15bps), ADA(19×-74.38bps), BTC(47×-23.21bps), HYPE(20×-35.22bps), ENA(20×-19.32bps)

**realwide** (n=298, passed=False)
- `net_pos_1x` — need > 8.0 bps gross, gap 19.24 bps
- `net_pos_2x` — need > 16.0 bps gross, gap 27.24 bps
- `ci95_lower_positive` — need CI95 low > 0, gap 33.71 bps
- `dsr_passed` — need DSR >= 0.95, gap 0.9499 bps
- worst contributors: ETH(24×-54.37bps), AAVE(20×-40.2bps), ASTER(16×-34.8bps), TRX(10×-43.98bps), DOGE(9×-45.12bps)

## Binding constraint

**twoway** is closest to passing: 4 failing checks, gross 2.92 bps vs 2× fee 16 bps.
Binding gap: `net_pos_1x` — 5.08 bps short.

## Funding/borrow blocker
- Verdict: `FAIL_CLOSED`
- exact/rate-estimated/missing: `0/0/0`
- coverage: `0.0%`
- Historical 42 SHORT remain fail-closed (no look-ahead imputation from current rates).

## Safety locks
- No leverage increase.
- No exit/gate/position-sizing change without backtest/OOS evidence + approval.
- No live order before GO-LIVE decision.
- No target downgrade.
