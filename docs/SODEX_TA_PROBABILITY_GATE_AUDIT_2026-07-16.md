# SoDEX TA Probability Gate Audit - 2026-07-16

## Verdict

SoDEX Farming already had several TA/probability-like components, but none was a mandatory pre-entry gate for `scripts/sodex_micro_pilot.py`.

Root cause of the recent low-quality live probe:

1. `sodex_micro_pilot.py` selected by microstructure, spread, liquidity, 24h change, funding, policy, and ratio budget.
2. It did not require 7 technical-analysis signals before placing a live entry.
3. `scripts/sodex_live_short_accelerator.py` could print a live command when maker microstructure passed, even if directional TA probability was weak.

## Existing Similar Systems Found

| System | Evidence | Useful | Gap |
|---|---|---:|---|
| `scripts/e2_signal_scanner.py` | 7 signals: RSI, MACD, Bollinger, momentum, volume trend, EMA, ATR | yes | Binance-only, five symbols, stale latest data, not wired to SoDEX execution |
| `anantara/directional_predictor.py` | 9 TA signals plus OOS calibration and Brier score | yes | Binance advisory research, not SoDEX ratio-aware |
| `anantara/pregain_engines.py` | 7-engine suite: volume Z, RVOL, OI velocity, funding, CVD proxy, liquidation, MTF | yes | Pregain/HL-oriented, not micro-pilot gate |
| `anantara/sodex_farming.py::compute_quality_score` | 8 technical + 1 intelligence signal quality score | partial | Maker quality/fill conditions, not directional probability for current micro-pilot |
| `scripts/research/backtest_freqai_sodex.py` | RSI/ADX/MFI/ATR/Bollinger/MACD/EMA/ROC/OBV walk-forward | yes | Research-only, dependency-heavy, not live gate |
| `scripts/sodex_scalp_microstructure.py` | maker/taker fee, spread, gross edge scan | yes | Execution-cost gate, not 7-signal direction gate |

## Architecture Change

New canonical flow:

```text
data_collectors
-> market_scan
-> technical_probability_gate
-> autonomous_research
-> monitor_eval
-> deep_learning_loop
-> policy_and_gates
-> execution_guard
-> operator_approval
-> micro_pilot_or_engine
-> experience_log_back_to_learning
```

The new `technical_probability_gate` layer is now represented in `scripts/sodex_system_map.py`.

## Implemented Guard

New module:

- `scripts/sodex_ta_probability_gate.py`

Seven signals:

1. EMA trend and slope
2. RSI
3. MACD histogram
4. Bollinger position and width
5. VWAP deviation
6. ATR / realized volatility / drift
7. Orderflow microstructure: 24h change, spread, funding

Gate requirements:

- local SoDEX scanner data must be fresh
- at least 30 pseudo-candles
- all seven signals covered
- direction must match intended side
- probability must be at least `0.80`
- estimated ATR/spread adverse loss must fit the active ratio budget, currently `1:5100`

## Live Safety Result

`scripts/sodex_micro_pilot.py` now evaluates `ta_probability_gate` before live entry. If it fails, reason is:

```text
ta_probability_gate_failed
```

`scripts/sodex_live_short_accelerator.py` now blocks live command generation if the same gate fails.

This does not clear `data/SAFETY_HALT` and does not place orders.

## Current Local Evidence

Fresh SoDEX scanner history was available from `data/sodex_market_scan/history.jsonl`.

Sample gate checks on current scanner data rejected SOL, ETH, BTC, SPCX, and SNDK short probes because probability was below `0.80`, direction was neutral/long, or ATR/spread adverse-loss exceeded the ratio budget.

This is the desired behavior: no live volume is allowed when the quantitative direction edge is not strong enough.
