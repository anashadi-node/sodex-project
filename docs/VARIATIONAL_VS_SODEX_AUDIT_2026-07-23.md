# Variational Omni vs SoDEX Audit

Date: 2026-07-23  
Decision horizon: migration after 2026-08-01

## Executive decision

**Conditional GO** for read-only research and a small, manual directional pilot.  
**NO-GO** for automated volume farming at this time.

The blocker is not market size. Variational has materially more reported volume, open interest, and markets than SoDEX. The blockers are contractual and technical: Variational's trading API is not available, its Terms prohibit unauthorized bots and resource farming, and Omni uses one RFQ liquidity provider rather than an order book. The current SoDEX maker/PVE engines therefore cannot be ported safely or honestly.

## Snapshot comparison

Public snapshots were taken around 2026-07-22 22:24 UTC.

| Metric | Variational Omni | SoDEX local scan | Interpretation |
|---|---:|---:|---|
| 24h perpetual volume | $855.2M | $87.4M | Variational reported volume is about 9.78x |
| Perpetual markets | 514 | 82 | Variational has about 6.27x more listings |
| TVL | $140.0M | Not in ticker scan | Venue-wide Variational value |
| Open interest | $1.362B | Not in ticker scan | About 9.73x Variational TVL; leverage and cross-margin concentration matter |
| Execution | RFQ; OLP sole counterparty | Central limit order book | Existing maker logic is not portable |
| Trading fees | Advertised zero; spread remains | Tier 0: 4 bps taker, 1.2 bps maker | Zero fee does not mean zero execution cost |
| Trading API | Not available | REST/WebSocket trading API | Automated Variational execution is currently impossible through an official API |
| Reward end | No later than end of Q3 2026 | User reports 2026-08-01 for current event | Aug 1 leaves at most about eight weeks if Variational runs to Sep 30 |

Top Variational volume in the snapshot was concentrated in BTC ($351.2M), ETH ($124.3M), XAU ($115.7M), HYPE ($46.8M), and SOL ($29.3M). Its $1,000 RFQ spread must be measured per requested size; it is not equivalent to SoDEX top-of-book spread.

At $1,000 quote size, the snapshot's tight liquid group began with BTC (0.76 bps), ETH (1.14 bps), SOL (1.25 bps), XAU (2.59 bps), and XRP (2.98 bps). SoDEX top-of-book was tighter for BTC and ETH, approximately equal for SOL, and wider for XAU and HYPE. This is a screening result, not an executable-price guarantee.

## Market structure findings

1. Omni is not an order book. Each order requests a firm quote from the Omni Liquidity Provider (OLP), which is the sole counterparty and earns the spread.
2. Omni currently uses cross margin. A loss or liquidation in one position can consume collateral supporting other positions.
3. Variational offers market, limit, stop-loss, and take-profit orders. Limit orders are all-or-nothing; partial fills are only on the roadmap. A documented 0.1-second check interval can miss shorter price crossings.
4. Indicative prices are not guaranteed execution prices. Actual RFQ price varies with size, OLP risk, and market conditions.
5. Funding windows vary from one to eight hours. Raw API funding values must not be compared before normalizing units and interval.
6. The public API may cache quote data for up to 600 seconds. Every decision must reject stale quotes and obtain a fresh firm quote in the UI.

## Reward and farming findings

Variational Points began on 2025-12-17 and are distributed weekly. The program can end earlier, but no later than the end of Q3 2026. Points and boosts do not have guaranteed monetary value or a published deterministic conversion to `$VAR`; the token is not live.

The important constraint is explicit: Variational's Terms prohibit resource farming, account boosting, botting, unauthorized code controlling an account, wash trading, and arbitrage between Variational and other platforms. Points may be modified, deducted, or withheld for inorganic activity. Repetitive volume generation is therefore a disqualification risk, not an optimization target.

The safe objective is **positive expectancy from genuine market exposure**, with points treated as an uncertain rebate. Do not trade solely to manufacture volume.

## Economics gate

For every manual pilot trade, record:

`net_edge_bps = expected_move_bps - entry_spread_bps - exit_spread_bps - slippage_bps - normalized_funding_bps - liquidation_risk_buffer_bps`

Execute only when conservative `net_edge_bps > 0` before assigning any value to points. The advertised zero fee removes an explicit commission but does not remove spread, adverse selection, funding, liquidation penalties, or bridge/deposit costs.

The loss-refund pool was `$0` in the public snapshot. It must be valued at zero in risk calculations unless the live pool is funded and the trader is eligible; refunds are a lottery, not insurance.

## Security and eligibility

- Use a new dedicated wallet with limited USDC, no unrelated assets, and no unlimited token approvals.
- Never give a browser extension, script, Telegram bot, or LLM seed phrases or transaction-signing authority.
- Use the official domain and Arbitrum One contract addresses published in the docs; verify every signature request.
- Indonesia is not named in the published restricted-location list, but eligibility and Indonesian derivatives rules still require independent legal review. Do not bypass location controls or use a VPN.
- A March 2025 Spearbit audit is published. The docs still describe the November 2024 Zellic report as coming soon; this is an unresolved disclosure item.

## Local code audit

`anantara/astronacci_market_variational.py` is not a Variational Omni integration. Despite its name, it currently collects public Binance and Bybit klines and runs paper-only simulation. It has no official Variational market-data adapter and no execution path. Treating it as a ready Variational engine would produce venue-model and data-source errors.

The new `scripts/variational_market_intel.py` uses the official public Omni stats endpoint, rejects malformed payloads, measures quote freshness and $1,000 RFQ spreads, compares the same-time SoDEX scan, and deliberately contains no authenticated action surface.

## Migration gates

### Before August 1

1. Run the read-only collector every five minutes and retain quote freshness, $1k spread, volume, and OI history.
2. Export SoDEX trade history and calculate realized spread, fees, funding, slippage, and points per net dollar lost.
3. Perform seven days of shadow decisions against Variational quotes with no transactions.
4. Ask Variational support in writing whether the intended workflow, automation, and reward-seeking activity are authorized.
5. Confirm live reward-tier thresholds and credited points in the UI; legacy documentation is not sufficient.

### August 1 readiness decision

Automated trading remains **NO-GO** unless all of these are true:

- an official trading API is released;
- written Terms or written authorization permit the intended automation;
- credentials can be scoped without withdrawal authority;
- empirical round-trip execution cost is below the strategy's conservative edge;
- a paper/shadow sample is profitable after spread and funding;
- points are observed and not required for break-even.

If those conditions are not met, use only small manual directional trades or postpone migration. Browser automation or reverse-engineered private endpoints is not an acceptable substitute.

## Local tooling

Run a current, read-only snapshot and compare it with SoDEX:

```bash
python3 scripts/variational_market_intel.py
```

Continuous five-minute intelligence:

```bash
python3 scripts/variational_market_intel.py --loop --interval 300
```

Offline replay:

```bash
python3 scripts/variational_market_intel.py --input snapshot.json --no-persist
```

Outputs are written to `data/variational_market_intel/latest.json` and `history.jsonl`. The collector contains no authentication or execution functionality.

## Primary sources

- Variational API: https://docs.variational.io/technical-documentation/api
- Variational Points: https://docs.variational.io/omni/rewards/points
- Variational Terms: https://docs.variational.io/legal/terms-of-use
- Restricted persons: https://docs.variational.io/legal/restricted-persons
- Omni and OLP: https://docs.variational.io/omni/about-omni and https://docs.variational.io/omni/the-omni-liquidity-provider-olp
- Fees and slippage: https://docs.variational.io/omni/trading/fees and https://docs.variational.io/omni/trading/slippage
- Quotes and funding: https://docs.variational.io/omni/trading/quoted-index-and-mark-prices and https://docs.variational.io/omni/trading/funding-rates
- Orders: https://docs.variational.io/variational-protocol/key-concepts/market-vs.-limit-orders
- Liquidation and loss refunds: https://docs.variational.io/omni/trading/liquidation and https://docs.variational.io/omni/rewards/loss-refunds
- Audits and contracts: https://docs.variational.io/technical-documentation/audits and https://docs.variational.io/technical-documentation/mainnet-contracts
- Roadmap and `$VAR`: https://docs.variational.io/roadmap and https://docs.variational.io/getting-started/usdvar-token
- SoDEX fees and API: https://sodex.com/documentation/trading-mechanics/trading-fees and https://sodex.com/documentation/trading-api/trading-api
- SoDEX Season 1: https://sodex.com/documentation/sopoints/season-1
- Indonesian oversight transition: https://www.ojk.go.id/id/berita-dan-kegiatan/siaran-pers/Documents/Pages/Bappebti-Kemendag-Alihkan-Tugas-Aset-Keuangan-Digital-termasuk-Aset-Kripto-serta-Derivatif-Keuangan-kepada-OJK-dan-BI/SPB%20Bappebti%20Kemendag%20Alihkan%20Tugas%20Pengaturan%20dan%20Pengawasan%20Aset%20Keuangan%20Digital%20termasuk%20Aset%20Kripto%20serta%20Derivatif%20Keuangan%20kepada%20OJK%20dan%20BI.pdf
