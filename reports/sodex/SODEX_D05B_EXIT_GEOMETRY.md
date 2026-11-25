# SoDEX D0.5b — Exit-Geometry Diagnostic (read-only)

Generated UTC: 2026-11-24T23:04:48.972180+00:00
Track **twoway** · n_signal 512 · fee 8.0 bps · cluster 30.0 h

## Verdict
- `TIME_STOP_LEAK_INSIDE_NULL_BAND`
- Excess mean: 2.92 bps · CI95 [-23.38, 29.07] · p(>0) 0.5787

## 1. Exit-reason accounting (bps)
| reason | n | share | mean bps | contribution to mean bps | mean hold h | outcome-determined |
|---|---:|---:|---:|---:|---:|:--:|
| TP | 137 | 26.8% | 198.78 | 53.19 | 8.94 | yes |
| TIME_30.0H | 26 | 5.1% | 42.76 | 2.17 | 30.01 | NO (actionable) |
| TIME_48H | 8 | 1.6% | -8.09 | -0.13 | 48.03 | NO (actionable) |
| TIME_30H | 121 | 23.6% | -6.17 | -1.46 | 30.22 | NO (actionable) |
| SL | 220 | 43.0% | -118.36 | -50.86 | 9.31 | yes |

### 1b. Binding constraint
| komponen | bps |
|---|---:|
| TP contribution | 53.19 |
| SL contribution | -50.86 |
| time-stop contribution | 0.58 |
| **gross excess** | **2.92** |
| fee 2× | 16.0 |
| **margin over 2× fee** | **-13.08** |
| time-stop as share of gross | 19.87% |

## 2. Designed vs realized geometry
**Basis: raw realized price move (bukan beta-neutral excess).** Tabel ini menggambarkan geometri exit apa adanya, bukan alpha. Untuk keputusan gate, yang berlaku adalah excess beta-neutral di bagian 1.
| metric | value |
|---|---:|
| n planned (tp/sl recorded) | 512 |
| mean planned TP distance | 3.6758% |
| mean planned SL distance | 2.0% |
| mean planned R:R | 1.8379 |
| mean realized TP | 3.5449% (n=137) |
| mean realized SL | 2.2073% (n=220) |
| mean realized R:R | 1.606 |
| actual WR | 41.4% |
| break-even WR (no fee) | 38.4% |
| break-even WR (fee 1×) | 39.8% |
| break-even WR (fee 2×) | 41.1% |
| gap to break-even WR at 2× fee | -0.26 pp |
| fee as share of mean TP | 2.26% |

## 3. Time-stop leak — paired counterfactual
| metric | value |
|---|---:|
| n time-stop trades | 155 |
| leak (bps of mean) | -0.59 |
| paired CI95 (bps) | [-8.28, 7.13] |
| blocks | 67 |

## 4. Negative control — shuffled time-stop label
- draws: 200 · null p50 = -1.21 bps · p95 = **5.29** · p99 = 7.99
- observed leak -0.59 bps vs null p95 5.29 → **INSIDE_NULL_BAND**
- Inside the null band means the time-stop subset is not distinguishable from a randomly chosen subset of the same size.

## 5. Duplication
- rows 602 → 601 unique pair-hour (ratio 1.002)

## Safety
- No strategy/SL/TP/gate/leverage change. No order. Measurement-only.
