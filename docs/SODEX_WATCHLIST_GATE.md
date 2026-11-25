# SoDEX Watchlist Gate Accelerator

Generated UTC: `2026-07-15T22:01:45.652633+00:00`

Mode: `READ_ONLY_SODEX_WATCHLIST_GATE_ACCELERATOR`

Policy: `no orders, no cancels, no leverage change, no credential change`

Latency: `1.969 ms`

## Global State

- Policy decision: `BLOCK_E2_E1_RESEARCH_ONLY`
- Regime: `NEUTRAL`
- Position truth: `{'quality': 'OK', 'open_count': 2, 'verified_flat': False, 'open_symbols': ['BTC-USD', 'SOL-USD'], 'blockers': ['open_perp_positions_present'], 'pass': False}`
- System blockers: `['micro_pilot_negative_edge_cooldown']`

## Counts

- `watchlist`: `32`
- `ready_review`: `0`
- `near_ready_cooldown`: `0`
- `blocked`: `32`

## Top Watchlist Gates

| Symbol | Status | Score | Spread bps | Liquidity | Maker edge bps | Funding bps | Blockers |
|---|---:|---:|---:|---:|---:|---:|---|
| `BTC-USD` | `BLOCKED` | 58.94 | 0.154417 | 26795464.34 | -2.005583 | -0.041991 | fee_edge, loss_budget, micro_pilot_cooldown, open_perp_positions_present, policy_gate, short_momentum_weak |
| `ETH-USD` | `BLOCKED` | 58.83 | 0.521281 | 22360205.87 | -1.638719 | 0.077626 | fee_edge, loss_budget, micro_pilot_cooldown, open_perp_positions_present, policy_gate, short_momentum_weak |
| `SOL-USD` | `BLOCKED` | 58.5 | 1.293076 | 6337701.91 | -0.866924 | 0.125 | fee_edge, loss_budget, micro_pilot_cooldown, open_perp_positions_present, policy_gate, short_momentum_weak |
| `SUI-USD` | `BLOCKED` | 58.48 | 1.328462 | 888994.31 | -0.831538 | 0.125 | fee_edge, loss_budget, micro_pilot_cooldown, open_perp_positions_present, policy_gate |
| `BNB-USD` | `BLOCKED` | 58.31 | 1.721022 | 864616.69 | -0.438978 | 0.125 | fee_edge, loss_budget, micro_pilot_cooldown, open_perp_positions_present, policy_gate, short_momentum_weak |
| `CL-USD` | `BLOCKED` | 58.24 | 1.506762 | 664883.68 | -0.653238 | 0.0625 | fee_edge, loss_budget, micro_pilot_cooldown, open_perp_positions_present, policy_gate, short_momentum_weak |
| `UNI-USD` | `BLOCKED` | 57.86 | 2.760524 | 594489.32 | 0.600524 | 0.06029 | fee_edge, loss_budget, micro_pilot_cooldown, open_perp_positions_present, policy_gate |
| `SKHX-USD` | `BLOCKED` | 55.64 | 7.89254 | 907161.62 | 5.73254 | 0.0625 | loss_budget, micro_pilot_cooldown, open_perp_positions_present, policy_gate |
| `XAUT-USD` | `BLOCKED` | 54.71 | 6.148776 | 1993691.32 | 3.988776 | 0.0625 | loss_budget, micro_pilot_cooldown, open_perp_positions_present, policy_gate, short_momentum_weak |
| `SILVER-USD` | `BLOCKED` | 50.25 | 0.172731 | 64711.32 | -1.987269 | 0.51201 | fee_edge, liquidity, liquidity_thin, loss_budget, micro_pilot_cooldown, open_perp_positions_present, policy_gate |
| `SKHY-USD` | `BLOCKED` | 50.19 | 16.770276 | 1105276.13 | 14.610276 | 0.0625 | loss_budget, micro_pilot_cooldown, open_perp_positions_present, policy_gate, spread, spread_wide |
| `SPCX-USD` | `BLOCKED` | 49.16 | 17.623733 | 522226.06 | 15.463733 | 0.0625 | loss_budget, micro_pilot_cooldown, open_perp_positions_present, policy_gate, spread, spread_wide |
| `ZEC-USD` | `BLOCKED` | 46.84 | 14.92356 | 458642.12 | 12.76356 | 0.125 | loss_budget, micro_pilot_cooldown, open_perp_positions_present, policy_gate, short_momentum_weak, spread, spread_wide |
| `META-USD` | `BLOCKED` | 44.61 | 20.432312 | 2906929.82 | 18.272312 | 0.0625 | loss_budget, micro_pilot_cooldown, open_perp_positions_present, policy_gate, short_momentum_weak, spread, spread_wide |
| `SNDK-USD` | `BLOCKED` | 43.74 | 28.709026 | 5366764.53 | 26.549026 | 0.0625 | loss_budget, micro_pilot_cooldown, open_perp_positions_present, policy_gate, spread, spread_wide |
| `MSFT-USD` | `BLOCKED` | 43.29 | 20.432617 | 322515.39 | 18.272617 | 0.0625 | loss_budget, micro_pilot_cooldown, open_perp_positions_present, policy_gate, short_momentum_weak, spread, spread_wide |
| `HYPE-USD` | `BLOCKED` | 42.66 | 16.266836 | 115973.19 | 14.106836 | 0.125 | loss_budget, micro_pilot_cooldown, open_perp_positions_present, policy_gate, short_momentum_weak, spread, spread_wide |
| `NVDA-USD` | `BLOCKED` | 41.88 | 21.217908 | 172109.89 | 19.057908 | 0.0625 | loss_budget, micro_pilot_cooldown, open_perp_positions_present, policy_gate, short_momentum_weak, spread, spread_wide |
| `AMZN-USD` | `BLOCKED` | 41.77 | 21.953036 | 206236.66 | 19.793036 | 0.0625 | loss_budget, micro_pilot_cooldown, open_perp_positions_present, policy_gate, short_momentum_weak, spread, spread_wide |
| `MRVL-USD` | `BLOCKED` | 41.68 | 28.121212 | 164094.66 | 25.961212 | 0.0625 | loss_budget, micro_pilot_cooldown, open_perp_positions_present, policy_gate, spread, spread_wide |
