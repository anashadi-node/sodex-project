# SoDEX D0.5 — twoway Edge-Leak Audit (fee-gate closure)

Generated UTC: 2026-11-24T23:04:46.064472+00:00
Track: **twoway** · source `/home/USER/anantara-sakti/data/paper_test_twoway_state.json`
Fee 8.0 bps/step · cluster block = 30.0 h

## Verdict
- `FAIL_CI95_SPANS_ZERO_AND_COST_2X_GAP`
- Gross (beta-neutral, signal arm): **2.92 bps**
- 1× fee: -5.08 bps · 2× fee: -13.08 bps
- Gap to 2× gate: **13.08 bps**
- CI95 (cluster bootstrap): [-22.97, 29.77] · p(excess>0) = 0.5801

## 1. Duplication
- all rows: 602 → 601 unique pair-hour (ratio 1.002)
- signal arm: 512 → 512 (ratio 1.0)

## 2. Arm split (a-priori label, not outcome-derived)
- signal n=512 · control n=90 (label `RANDOM`)

## 3. Contamination of the T1 measurement
| view | excess bps |
|---|---:|
| all rows (harness as-is) | -0.16 |
| signal arm only | 2.92 |
| **delta recovered** | **3.08** |

## 4. Clustered inference (30 h blocks)
| view | n | n_blocks | mean bps | CI95 bps | p(>0) |
|---|---:|---:|---:|---|---:|
| all | 602 | 69 | -0.16 | [-24.17, 23.93] | 0.486 |
| signal | 512 | 67 | 2.92 | [-22.97, 29.77] | 0.5801 |
| control | 90 | 25 | -17.7 | [-63.75, 31.51] | 0.2416 |

### Symbol breakdown (signal arm)

| symbol | n | excess bps | n≥20 |
|---|---:|---:|:--:|
| LIT | 1 | 177.61 | no |
| SUI | 20 | 59.18 | yes |
| BNB | 17 | 57.42 | no |
| AVAX | 15 | 46.04 | no |
| UNI | 24 | 42.34 | yes |
| ASTER | 21 | 34.98 | yes |
| BCH | 17 | 29.46 | no |
| DOGE | 49 | 23.97 | yes |
| AAVE | 24 | 20.18 | yes |
| SOL | 45 | 17.98 | yes |
| PUMP | 18 | 16.1 | no |
| XRP | 19 | 6.98 | no |
| ONDO | 19 | -6.18 | no |
| TRX | 16 | -14.08 | no |
| LINK | 20 | -18.77 | yes |

### side breakdown (signal arm)

| bucket | n | excess bps | n≥20 |
|---|---:|---:|:--:|
| SHORT | 42 | 60.94 | yes |
| LONG | 470 | -2.27 | yes |

### regime breakdown (signal arm)

| bucket | n | excess bps | n≥20 |
|---|---:|---:|:--:|
| BEAR_MOMENTUM | 42 | 60.94 | yes |
| MOMENTUM | 470 | -2.27 | yes |

### exit_reason breakdown (signal arm)

| bucket | n | excess bps | n≥20 |
|---|---:|---:|:--:|
| TP | 137 | 198.78 | yes |
| TIME_30.0h | 26 | 42.76 | yes |
| TIME_30h | 121 | -6.17 | yes |
| TIME_48h | 8 | -8.09 | no |
| SL | 220 | -118.36 | yes |

## 5. Per-bucket tests (block-level t, BH-FDR q=0.10)

| dim | bucket | n | n_blocks | t | p | q |
|---|---|---:|---:|---:|---|---:|
| symbol | DOGE | 49 | 38 | 0.738 | 0.4604 | 0.8992 |
| symbol | SOL | 45 | 37 | 0.825 | 0.4093 | 0.8992 |
| symbol | ETH | 47 | 40 | -1.292 | 0.1964 | 0.8992 |
| symbol | BTC | 47 | 42 | -1.314 | 0.1890 | 0.8992 |
| symbol | AAVE | 24 | 21 | 0.284 | 0.7766 | 0.8992 |
| symbol | BCH | 17 | 17 | 0.525 | 0.5996 | 0.8992 |
| symbol | ONDO | 19 | 19 | -0.115 | 0.9081 | 0.9284 |
| symbol | ADA | 19 | 17 | -1.201 | 0.2298 | 0.8992 |
| symbol | XAUT | 11 | 11 | -0.558 | 0.5771 | 0.8992 |
| symbol | SILVER | 10 | 10 | -0.422 | 0.6728 | 0.8992 |
| symbol | ARB | 13 | 13 | -0.285 | 0.7755 | 0.8992 |
| symbol | UNI | 24 | 20 | 0.995 | 0.3197 | 0.8992 |
| symbol | HYPE | 20 | 18 | -0.671 | 0.5024 | 0.8992 |
| symbol | AVAX | 15 | 13 | 0.651 | 0.5153 | 0.8992 |
| symbol | SUI | 20 | 18 | 1.183 | 0.2370 | 0.8992 |
| symbol | ENA | 20 | 19 | -0.090 | 0.9284 | 0.9284 |
| symbol | LIT | 1 | 1 | n/a | n/a | n/a |
| symbol | XRP | 19 | 16 | 0.293 | 0.7692 | 0.8992 |
| symbol | LINK | 20 | 18 | -0.107 | 0.9144 | 0.9284 |
| symbol | ASTER | 21 | 21 | 0.669 | 0.5033 | 0.8992 |
| symbol | BNB | 17 | 16 | 1.216 | 0.2239 | 0.8992 |
| symbol | PUMP | 18 | 17 | 0.429 | 0.6679 | 0.8992 |
| symbol | TRX | 16 | 16 | -0.342 | 0.7322 | 0.8992 |
| side | SHORT | 42 | 13 | 1.387 | 0.1654 | 0.3309 |
| side | LONG | 470 | 62 | -0.601 | 0.5480 | 0.5480 |
| regime | BEAR_MOMENTUM | 42 | 13 | 1.387 | 0.1654 | 0.3309 |
| regime | MOMENTUM | 470 | 62 | -0.601 | 0.5480 | 0.5480 |
| exit_reason | SL | 220 | 54 | -8.219 | 0.0000 | 0.0000 |
| exit_reason | TIME_48h | 8 | 4 | -1.264 | 0.2063 | 0.2579 |
| exit_reason | TP | 137 | 45 | 8.314 | 0.0000 | 0.0000 |
| exit_reason | TIME_30h | 121 | 41 | -0.634 | 0.5258 | 0.5258 |
| exit_reason | TIME_30.0h | 26 | 10 | 1.804 | 0.0712 | 0.1187 |

## 6. Negative control — random bucket selection

- draws: 200 · null max-bucket p95 = **67.21 bps**, p99 = 95.79 bps
- If the best observed bucket does not exceed p95, it is selection noise.

## Safety
- No strategy/gate/exit/leverage change. No order. Measurement-only.
