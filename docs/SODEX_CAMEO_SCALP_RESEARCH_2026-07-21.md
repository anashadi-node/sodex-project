# SoDEX CAMEO-Scalp Research

Generated: 2026-07-21

Mode: read-only; no order placement or cancellation path

Method: **CAMEO-Scalp (Cost-Aware Multi-timeframe Edge & Opportunity)**

## Objective

Identify a SoDEX asset and BUY/SELL direction over 1, 3, 5, or 15 minutes only
when expected directional profit covers spread, slippage proxy, and fees while
preserving an honest real volume/cost ratio of at least 1:4500.

## Decision Pipeline

1. Convert 2.15 million L1 snapshots across 80 usable assets into one-minute
   bars without future data.
2. Measure momentum at 1/3/5/15 minutes, realized volatility, path efficiency,
   L1 imbalance, spread, depth, and intraminute range.
3. Fit a pooled nonlinear return model separately for each horizon.
4. Select the minimum predicted edge on the chronological validation window.
5. Open the sealed OOS window and price BUY at ask / SELL at bid, including two
   effective taker fees of 3.60 bps per leg.
6. Require at least 30 global OOS round trips and positive validation/OOS LCB95.
7. Require each asset to have at least eight OOS round trips, positive LCB95,
   and ratio at least 1:4500.
8. A current BUY/SELL is `TRADE_READY` only when both the model and asset gates
   pass. The report remains hard-coded with `promotion_allowed=false`.

The operative quantity is not raw probability. It is:

`predicted edge margin = abs(predicted move) - current spread - all fees`

## Current Evidence

The simple directional grid tested 82 assets and 1/3/5/15-minute regimes with
maker-entry/taker-exit fees. It produced zero fully eligible candidates.

CAMEO then tested 80 usable assets under the stricter taker/taker execution
stress. The table is a representative run; `latest.json` is authoritative as
the hourly forward window grows. No horizon passed:

| Horizon | Validation LCB95 | OOS LCB95 | Model gate |
| --- | ---: | ---: | --- |
| 1 minute | -36.61 bps | -12.88 bps | FAIL |
| 3 minutes | -21.19 bps | -14.12 bps | FAIL |
| 5 minutes | -19.32 bps | -31.33 bps | FAIL |
| 15 minutes | -12.89 bps | -28.72 bps | FAIL |

The lower-fee stress also failed all four horizons. Therefore fee reduction
alone does not solve the problem; directional forecasts are not stable enough
across the train, validation, and OOS regimes.

## Research Watch, Not Signals

- VIRTUAL showed the most interesting 15-minute asset-level OOS behavior in one
  run, but its LCB95 remained negative and the global model failed.
- WLD showed six profitable 5-minute OOS observations, below the minimum sample
  and inside a globally failing model.
- MRVL and SKHY produced isolated positive windows but failed validation or
  sample-size requirements.

These assets are forward-research priorities. They are not current trade calls.

## Why WAIT Is Required

A market can move while still having no measurable, repeatable edge after
execution costs. Treating every price movement as an opportunity creates
selection bias and damages the real ratio. CAMEO permits WAIT whenever expected
profit does not have a positive lower confidence bound.

## Forward Gate

The hourly read-only timer expands regime coverage. Live consideration requires:

- at least seven independent days, not one 24-hour regime;
- positive validation and rolling OOS LCB95 after full costs;
- at least 100 forward round trips for the selected horizon;
- asset-specific LCB95 positive with at least 30 forward round trips;
- global honest ratio at least 1:4500 before opening new risk;
- explicit authorization and separate order-safety verification.

## Artifacts

- `scripts/sodex_mtf_scalp_lab.py`
- `data/sodex_mtf_scalp_lab/latest.json`
- `data/sodex_mtf_scalp_lab/decision_ledger.jsonl`
- `systemd/sodex-cameo-scalp-research.service`
- `systemd/sodex-cameo-scalp-research.timer`

## Research Basis

- SoDEX fee schedule: https://sodex.com/documentation/trading-mechanics/trading-fees
- SoDEX order types: https://sodex.com/documentation/trading-mechanics/orders-types
- Order-flow price impact: https://arxiv.org/abs/1011.6402
- Multi-level OFI: https://arxiv.org/abs/1907.06230
