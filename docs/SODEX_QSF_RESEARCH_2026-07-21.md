# SoDEX QSF-Maker Research Note

> Superseded by `SODEX_QIP_RESEARCH_2026-07-21.md`. Public-trade queue
> validation rejected HYPE and the old price-through capacity estimate.

Generated: 2026-07-21
Mode: read-only research; no live-order path
Method name: **QSF-Maker (Queue-Survival Filtered Maker)**

## Research Question

Can a queue-aware maker method increase transaction volume while keeping real
volume/cost at or above 1:6300, after replacing optimistic price-touch fills
with conservative price-through fills and separate entry/close clocks?

## Evidence Protocol

- Dataset: 24 hours of polled SoDEX L1, 82 symbols, about 2.15 million rows.
- Structural screen: 16 symbols with sufficient spread, depth, and observations.
- Search: 144 variants per symbol.
- Split: chronological 50% train, 25% validation, 25% final OOS.
- Cost model: maker 1.08 bps per filled leg; taker fallback 2.00 bps.
- Fill model: a new trade and best price must both move through the quote.
- Promotion constraint: realized ratio and 95% lower confidence bound must both
  remain inside the 1:6300 budget.

## Literature Basis

- Gould and Bonart show that queue imbalance has statistically significant
  one-tick predictive power, with stronger OOS classification for large-tick
  assets: https://arxiv.org/abs/1512.03492
- Huang, Lehalle, and Rosenbaum model the book as a queue-reactive system and
  show that a simple Poisson model can overestimate execution probability:
  https://arxiv.org/abs/1312.0563
- Arroyo, Cartea, Moreno-Pino, and Zohren treat fill time as a survival problem;
  relevant features include imbalance, volatility, activity, time, and multiple
  book levels: https://arxiv.org/abs/2306.05479
- Bodor and Carlier show that order size materially improves queue-reactive
  simulation fidelity: https://arxiv.org/abs/2405.18594

## Result

The prior XPL candidate failed under conservative replay. Its OOS baseline was
156 RT, only 2 paired, average -12.65 bps, and ratio 1:1582.

The selected QSF candidate is HYPE-USD:

| Parameter | Value |
| --- | ---: |
| Quote TTL | 30 s |
| Close TTL | 60 s |
| Minimum spread | 4 bps |
| Maximum absolute L1 OBI | 0.15 |
| Maximum absolute 30 s momentum | 8 bps |

Chronological results:

| Split | RT | Volume/h at $20 | Avg net | LCB95 | Ratio proxy |
| --- | ---: | ---: | ---: | ---: | ---: |
| Train | 362 | $1,207 | -1.43 bps | -2.57 bps | 1:13,994 |
| Validation | 172 | $1,147 | -1.15 bps | -2.81 bps | 1:17,383 |
| OOS | 190 | $1,267 | -1.03 bps | -2.47 bps | 1:19,512 |

This is not trading alpha: expected PnL remains slightly negative. It is a
bounded-cost farming hypothesis whose measured cost rate is inside the target.

## Known Limitations

- The 24-hour window covers only one market regime.
- Polled L1 cannot identify exact queue position, cancellations, or hidden size.
- Price-through inference is more conservative than touch inference but is not
  exchange-confirmed fill truth.
- Repeated research on the same OOS window will turn it into validation data.
- Current global real ratio remains below target; no new live risk is justified.

## Next Gate

`sodex-public-trade-recorder.service` now records HYPE, XPL, and EWY aggressive
public trades every two seconds. QSF remains research-only until a fresh forward
window can replay cumulative aggressive quantity against displayed queue-ahead,
including right-censored no-fill episodes. Live promotion is explicitly false.

Artifacts:

- `scripts/sodex_queue_fill_lab.py`
- `data/sodex_queue_fill_lab/latest.json`
- `data/sodex_queue_fill_lab/decision_ledger.jsonl`
- `scripts/sodex_public_trade_recorder.py`
- `data/sodex_public_trades.db`
