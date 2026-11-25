# SoDEX SHORT-BEAR vs Realwide Bottleneck Audit — 2026-09-17 23:33 WIB

## Scope
- User-approved audit after timeline review.
- Read-only analysis. No parameter/code change.
- Target: ≥0.7% total wallet ROI per 1–30h swing/window.

## Verdict
- **Realwide is closest to target**: n=133, WR=48.9%, PF=1.41, avg wallet ROI=0.629%, target-hit=39/133 (29.3%). Gap to target: 0.071pp.
- **SHORT-BEAR main is not target-capable yet**: n=15, WR=66.7%, PF=0.91, avg wallet ROI=-0.053%, target-hit=1/15 (6.7%).
- Root bottleneck differs:
  - Realwide: toxic pair selection suppresses an otherwise target-capable engine.
  - SHORT-BEAR: exit geometry/payoff asymmetry; high WR but winners too small vs SL.

## Realwide evidence
| Metric | Value |
|---|---:|
| n | 133 |
| WR | 48.9% |
| PF | 1.41 |
| avg pnl_pct | 0.333% |
| avg wallet ROI | 0.629% |
| target hit | 39/133 = 29.3% |
| open | 1 |

### Realwide exit contribution
| Exit | n | WR | avg_pct | sum_pct | wallet_avg |
|---|---:|---:|---:|---:|---:|
| SL | 46 | 0.0% | -1.951% | -89.733% | -3.688% |
| SL_BEAR | 7 | 0.0% | -1.179% | -8.252% | -2.229% |
| TP | 26 | 100.0% | 4.723% | 122.800% | 8.931% |
| TIME_30h | 23 | 60.9% | 0.639% | 14.706% | 1.209% |
| SL_PROTECT | 23 | 95.7% | 0.263% | 6.057% | 0.498% |

### Realwide toxic-pair counterfactual
| Filter | n | WR | PF | avg_pct | wallet_avg | target_rate |
|---|---:|---:|---:|---:|---:|---:|
| none | 133 | 48.9% | 1.41 | 0.333% | 0.629% | 29.3% |
| exclude SUI | 126 | 50.8% | 1.56 | 0.434% | 0.820% | 31.0% |
| exclude SUI,ADA,ONDO | 114 | 52.6% | 1.83 | 0.599% | 1.132% | 34.2% |
| exclude SUI,ADA,ONDO,HYPE | 108 | 53.7% | 1.98 | 0.681% | 1.287% | 35.2% |

**Finding:** removing only SUI already lifts avg wallet ROI above 0.7% (0.820%). Strong hypothesis: SoDEX realwide target is blocked mainly by pair-selection, not exit engine.

## SHORT-BEAR evidence
| Metric | Main SHORT-BEAR |
|---|---:|
| n | 15 |
| WR | 66.7% |
| PF | 0.91 |
| avg pnl_pct | -0.051% |
| avg wallet ROI | -0.053% |
| target hit | 1/15 = 6.7% |
| open | 0 |

### SHORT-BEAR exits
| Exit | n | WR | avg_pct | sum_pct | wallet_avg |
|---|---:|---:|---:|---:|---:|
| SL | 5 | 0.0% | -1.690% | -8.450% | -1.300% |
| MR_EXIT | 10 | 100.0% | 0.768% | 7.680% | 0.570% |

**Finding:** MR_EXIT produces frequent wins but average wallet ROI 0.570% < 0.7%; SL wipes the edge. This is exit geometry/payoff asymmetry, not directional accuracy.

### SHORT-BEAR pair counterfactual
| Filter | n | WR | PF | avg_pct | wallet_avg | target_rate |
|---|---:|---:|---:|---:|---:|---:|
| none | 15 | 66.7% | 0.91 | -0.051% | -0.053% | 6.7% |
| exclude UNI | 13 | 76.9% | 1.52 | 0.202% | 0.139% | 7.7% |
| exclude UNI,XRP | 11 | 81.8% | 2.08 | 0.341% | 0.216% | 9.1% |
| exclude UNI,XRP,BTC | 7 | 85.7% | 3.47 | 0.544% | 0.404% | 14.3% |

**Finding:** UNI and XRP are clearly bad in this small sample. Excluding them turns PF positive but still below 0.7% wallet target. Pair filter alone insufficient.

## SHORT-BEAR variants
| Variant | n | WR | PF | avg_pct | wallet_avg | target_hit |
|---|---:|---:|---:|---:|---:|---:|
| main | 15 | 66.7% | 0.91 | -0.051% | -0.053% | 6.7% |
| baseline_control | 5 | 60.0% | 0.78 | -0.142% | -0.088% | 0.0% |
| fast_exit_2h | 5 | 40.0% | 0.39 | -0.290% | -0.182% | 0.0% |
| closed_candle_entry | 5 | 60.0% | 0.61 | -0.316% | -0.200% | 0.0% |
| venue_native_guard | 5 | 60.0% | 0.78 | -0.142% | -0.088% | 0.0% |
| sodex_mark_execution | 5 | 60.0% | 0.64 | -0.276% | -0.174% | 20.0% |
| strict_rsi_volume | 1 | 100.0% | inf | 0.920% | 0.580% | 0.0% |
| strict_all_5 | 1 | 100.0% | inf | 0.920% | 0.580% | 0.0% |

**Finding:** strict variants are promising but n=1 only. Not actionable yet. Fast-exit 2h worsens result.

## KT IS / IS NOT
| Dim | IS | IS NOT | Distinction | Change / latent condition |
|---|---|---|---|---|
| WHAT | SHORT-BEAR high WR but negative expectancy | Realwide lower WR but positive PF and near target | SHORT-BEAR winner size capped by MR_EXIT; losers fixed SL | Exit geometry takes small mean-reversion profit before target |
| WHERE | UNI/XRP/BTC weak subset; SL/MR_EXIT only | Realwide TP/TIME_30h on SOL/UNI/ETH/BTC strong | Pair universe and exit ladder differ | SHORT-BEAR pair eligibility too broad for payoff profile |
| WHEN | Latest 7d: SHORT-BEAR recent avg positive but tiny; variants n low | Realwide recent 7d weak but historical n=133 robust | SHORT-BEAR still sample-starved | Need more n before parameter mutation |
| EXTENT | Target-hit only 6.7% | Realwide target-hit 29.3%, and >0.7% if SUI excluded | Directional accuracy not enough | Payoff asymmetry + pair toxic list |

## Root cause candidates
1. **SHORT-BEAR MR_EXIT exits too early** — survives all evidence. Winners avg wallet 0.570% < target; SL avg -1.300% wallet.
2. **SHORT-BEAR pair universe too broad** — partial cause. UNI/XRP removal improves PF, but still below target.
3. **SHORT-BEAR 2h fast exit** — rejected. Variant worsens PF and avg.
4. **Realwide overall engine bad** — rejected. Excluding toxic pairs lifts wallet_avg > target.

## Recommendations (no code yet)
1. **Realwide immediate research path**: backtest/forward-validate toxic-pair block candidate: SUI first, then SUI+ADA+ONDO+HYPE. Need n≥20 per excluded group or controlled walk-forward before deploy.
2. **SHORT-BEAR containment**: do not promote/live. Keep paper-only until n≥30 and PF>1.2 with wallet_avg ≥0.7%.
3. **SHORT-BEAR next experiment**: test MR_EXIT threshold/partial-exit ladder in paper/backtest, not production. Aim winner wallet_avg ≥0.9% so SL can be absorbed.
4. **SHORT-BEAR pair block candidate**: monitor UNI/XRP as BLOCK_CANDIDATE; n too low for hard block, but evidence direction negative.
5. **Do not change SL/TP/leverage yet**: red-line requires backtest improvement proof.

## Artifacts
- Machine-readable data: `reports/sodex_shortbear_realwide_bottleneck_audit_20260917.json`
- This report: `reports/sodex_shortbear_realwide_bottleneck_audit_20260917.md`
