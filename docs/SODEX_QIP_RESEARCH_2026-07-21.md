# SoDEX QIP-Maker Research Note

Generated: 2026-07-21

Mode: read-only public-trade replay; no order-placement path

Method: **QIP-Maker (Queue-Improving Patient Maker)**

Target: honest real volume/cost ratio at least 1:4500

## Method

QIP places a hypothetical micro order one tick inside a sufficiently wide
spread. After the first passive fill it attempts a reduce-only passive close,
repriced every six seconds without crossing below zero gross spread. A quote
expires after 60 seconds and a close after 120 seconds. Entry is blocked when
absolute L1 imbalance exceeds 0.35, absolute 30-second momentum exceeds eight
bps, or spread is below four bps.

All promotion evidence is now fixed at the venue-executable **$10 per leg**.
Exchange rules confirmed MRVL has a $10 minimum order notional, and its $10
public-trade replay produced zero round trips. The otherwise strong $2 MRVL
shadow result is therefore non-executable and explicitly blocked. The forward
scanner now tests twelve independent $10 candidates selected by maker spread
and public-flow capacity rather than increasing an invalid MRVL clip.

## Evidence

The old QSF HYPE result was rejected. Price-through L1 inference suggested high
volume, but cumulative public aggressive trades produced zero HYPE round trips
after 50% or 100% displayed queue-ahead.

The strongest executable candidate in the latest forward snapshot is XAUT:

| Metric | Result |
| --- | ---: |
| Forward window | 0.4514 h |
| Round trips | 16 |
| Paired closes | 16 (100%) |
| Shadow volume | $708.97/h at $10 clips |
| Net LCB95 | +2.69 bps |
| Ratio proxy | positive net; no realized-loss denominator |
| Micro-pilot gate | **FAIL: requires at least 8 h and 100 round trips** |

The replay uses the account's measured maker fee of 1.08 bps and taker fee of
3.60 bps. XAUT is promising, not promoted: its window is too short to cover a
regime change. At executable size, HYPE, SNDK, SKHX, LIT, ZEC, and the other
new candidates currently fail the ratio or LCB requirement.

## Scientific Caveat

An inside-spread hypothetical quote has no displayed queue ahead, but the
historical public trades occurred while that hypothetical quote did not exist.
The replay assumes eligible aggressive flow would have intercepted it. This is
more realistic than price-touch inference but remains counterfactual, not
exchange-confirmed fill truth. It cannot authorize live trading.

## Promotion Gate

All conditions must pass on fresh data under the 100% queue scenario:

- at least 24 forward hours;
- at least 100 round trips;
- paired share at least 70%;
- shadow volume at least $100/h;
- realized ratio and LCB95 both remain inside 1:4500;
- separate explicit live authorization after account/order safety verification.

The report field `promotion_allowed` remains hard-coded to `false`.

A separate bounded micro-pilot gate is available for faster live fill-truth
discovery. It requires at least eight forward hours, 100 round trips, 90%
paired closes, $150/h shadow volume, positive LCB95, executable notional, and
ratio compliance. Passing it only makes the disabled 10-round-trip pilot
eligible; it does not enable or start the service.

## Global Ratio Recovery

The latest honest ledger is $9,670.09 volume and $2.8918 cost, or 1:3344. To
reach 1:4500 requires $3,343.01 additional volume if no new cost is incurred.
Under a conservative maker-fee-only ratio of 1:9259, required added volume is
about $6,505. Both are projections, not promises, and depend on forward flow
surviving the promotion gate.

## Automation and Artifacts

- `sodex-public-trade-recorder.service` records twelve executable-size candidate
  assets at a rate-limit-safe 20-second interval.
- `sodex-queue-trade-validator.timer` replays the growing forward dataset every
  30 minutes at $10 notional.
- `data/sodex_queue_trade_validation_forward.json` is the current evidence.
- `data/sodex_queue_trade_decision_ledger.jsonl` preserves each gate decision.
- `sodex-qip-xaut-pilot.service` is installed disabled/inactive with a $0.05
  loss cap and 10-round-trip cap. Its executor hard-fails before order placement
  unless the forward micro-pilot gate passes.
- The recorder and validator have no authenticated order-placement path.

## Sources

- SoDEX trading fees: https://sodex.com/documentation/trading-mechanics/trading-fees
- SoDEX API rate limits: https://sodex.com/documentation/trading-api/api-rate-limits
- Queue imbalance: https://arxiv.org/abs/1512.03492
- Queue-reactive order books: https://arxiv.org/abs/1312.0563
- Fill probability as survival: https://arxiv.org/abs/2306.05479
- Order-size-aware queue models: https://arxiv.org/abs/2405.18594
