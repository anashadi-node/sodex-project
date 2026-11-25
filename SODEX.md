# ANANTARA SAKTI — SoDEX System (complete reference)

SoDEX (sodex.com) is the **primary** market: reliable (no VPN), full API.
**REVISED 2026-08-01: Goal = profit maximal swing trading 1h–48h.** Volume/SoPoints
= byproduct, not objective. This doc is the comprehensive reference.

For the **superseded** volume-farming doctrine, see `docs/SODEX_FARMING_DOCTRINE.md`
(historical reference only — no longer the operating target).

## 1. Account
- Master account: `0x4a464b82b1c1233791351483c90c53e2a2fbc799` (aid 180570)
- API key name: `ANANTARASAKTI` (privkey in `.env` SODEX_PRIVATE_KEY, chmod 600)
- Capital: ~$123 vUSDC (perps). SoPoints tracked at sodex.com (not via API).
- Current fee: maker 0.0114%, taker 0.038% (Tier 0 + 5% staking discount).
- Staking tier: 1 (30+ SOSO staked → 5% fee discount).

## 2. Fee Structure (LIVE since March 13, 2026 — source: sodex.com/docs)

### Perps Fee Tiers (14-Day Rolling Volume)
| Tier | 14D Volume | Taker | Maker |
|------|-----------|-------|-------|
| 0 | ≤ $5M | 0.040% | 0.012% |
| 1 | > $5M | 0.036% | 0.010% |
| 2 | > $25M | 0.032% | 0.006% |
| 3 | > $100M | 0.028% | 0.002% |
| 4 | > $500M | 0.026% | **0.000%** |
| 5 | > $2B | 0.024% | 0.000% |
| 6 | > $7B | 0.022% | 0.000% |

### Spot Fee Tiers
| Tier | 14D Volume | Taker | Maker |
|------|-----------|-------|-------|
| 0 | ≤ $5M | 0.065% | 0.035% |
| 1-6 | ... | ... | ... |

### Weighted Volume (Perps + Spot Combined!)
```
14D Weighted Volume = (14D Perps Volume) + 2 × (14D Spot Volume)
```
**Spot counts DOUBLE toward tier!**

### Staking Fee Discount
| Discount | SOSO Staked | Cost @ $0.368 |
|----------|-------------|---------------|
| 5% (now) | ≥ 30 | ~$11 |
| 10% | ≥ 300 | ~$110 |
| 15% | ≥ 3,000 | ~$1,104 |
| 20% | ≥ 30,000 | ~$11,040 |

### Maker Rebates (NEGATIVE FEE — Platform PAYS YOU!)
| Tier | 14D Maker Volume Share | Maker Fee |
|------|----------------------|-----------|
| 1 | > 0.50% of platform | **-0.001%** |
| 2 | > 1.50% of platform | **-0.002%** |
| 3 | > 3.00% of platform | **-0.003%** |

Current API state: `feeTier:0, stakingTier:1, makerRebateTier:0`
Check: `curl -s "https://mainnet-gw.sodex.dev/api/v1/perps/accounts/{addr}/fee-rate"`

## 3. Two independent subsystems

### A. SCALP farming (ACTIVE — SoPoints volume) — user's proven method
**Goal: generate trading volume cheaply for SoPoints + fee tier progression.**
- Mechanism: patient maker open + maker close (patient_mm_round) → volume at
  near-zero directional risk. Volume/round = 2 × (margin × leverage).
- Live-tested economics: ~$2,325 volume per cycle (BTC + SOL), 99%+ maker rate.
- Liquid symbols: BTC, SILVER, ZEC, XAUT, ETH, HYPE, BCH, NVDA, AMZN, US500
  (top 10 by spread tightness, all <0.01% spread).
- Safety: confirms position opened → closes ACTUAL filled qty reduce-only → verifies
  flat → retries 3× + alerts if residual. Monitor stop-loss is the backstop.
- Daemon: `job_sodex_scalp` every 10 min, gated by enable + kill + SCALP_MODE +
  daily volume cap. Skips if any position open (no stacking).

Config (`.env`):
```
SODEX_SCALP_MODE=1            # scalp (volume) vs directional
SODEX_SCALP_LEVERAGE=20      # user's method
SODEX_SCALP_MARGIN=25        # per round ($25×20x×N rounds = same vol as $100×20x×1, safer)
SODEX_SCALP_ROUNDS=2         # round-trips per 20-min cycle
SODEX_SCALP_DAILY_VOLUME_CAP=8000   # safety; ~$3/day max cost
SODEX_SCALP_SYMBOLS=BTC-USD,ETH-USD,SOL-USD,XAUT-USD
```
NOTE: cost scales with VOLUME, not margin-per-round. Smaller margin + more rounds =
same SoPoints volume + same cost, lower per-round risk. Raise SCALP_MARGIN only if
the account is large enough to absorb a failed-close at that notional.

### B. Directional model trading (RESEARCH/idle — thin edge)
- LightGBM 48h model server (port 8001, 57 assets), OOS-gated, walk-forward whitelist
  (10 assets: HYPE/1000PEPE/HYPE/GOOGL/WLFI/BTC/ZEC/SOL/AXS/BERA/HBAR).
- Edge is THIN (PF 1.2-2.0, dir 52-65%) — directional farming BLED -$3.66 (wrong SOL
  shorts). **Disabled when SCALP_MODE=1.** Kept for research; not the SoPoints engine.

## 3. API quick reference (mainnet-gw.sodex.dev/api/v1/perps)
- Public (no sign): `/markets/symbols`, `/markets/tickers`, `/markets/{s}/klines`,
  `/accounts/{addr}/{state,balances,positions,orders,trades,fundings,fee-rate}`
- Signed (EIP-712 via `bin/sodex` CLI): orders place/cancel, leverage, transfer.
- Market orders REQUIRE `--tif ioc`. Leverage cmd prints text (not JSON).

## 4. Telegram controls
`/sodex` status (mode, balance, volume, cost, efficiency) · `/sodexon` `/sodexoff`
· `/kill` closes ALL + halts · `/killresume`.

## 5. P&L accounting (avoid confusion)
- **Wallet balance** = realized (closed trades hit here).
- **Unrealized PnL** widget = OPEN positions only — a DIFFERENT number.
- Balance drop = realized closed-position P&L + trading fees + funding.
  (Audited 2026-05-22: -$4.36 = -$3.66 realized losses -$0.75 fees +$0.05 funding.)
- Scalp cost ≈ fees + spread only (no directional P&L), tracked as cost_today_usd.

## 6. Safety invariants
- Scalp leverage during ~1s hold; isolated margin caps loss at the round's margin.
- Daily volume cap limits max daily cost. Monitor stop-loss backstops any stuck position.
- `.env` chmod 600, never committed. Ports localhost. CEX dry_run=true.

## 7. Backtest/research tools (scripts/)
backtest_freqai_grid.py (per-asset walk-forward), backtest_ensemble.py,
backtest_features.py, backtest_momentum.py. Run in freqtrade container.

Microstructure scalp R&D (stdlib, `make backtest-obi|backtest-short|backtest-lt`):
backtest_obi.py (OBI/OFI/cumOFI), backtest_scalp_v2.py + _wf.py (triple-barrier +
walk-forward), backtest_scalp_lt.py (1-20min), analyze_scalp_regime.py.
**Verdict (2026-05-23, 22.5h data): NO out-of-sample scalp edge at any horizon
0.5-20min, any symbol.** Directional scalping is not profitable after fees.

## 8. Edge verdict + airdrop ROI
Since scalping has no proven edge, the airdrop is a REWARD-vs-COST decision, not a
profit play. `scripts/airdrop_roi_model.py` (`make roi`): a bounded farming budget
is plausibly +EV (break-even SoPoint value ~$0.017-0.073 < plausible $0.1-0.7);
capital ($197) is the binding constraint, not edge. The undisclosed SoPoint→$
ratio is resolved EMPIRICALLY by the measure-farm controller.

## 9. Measure-farm — MANUAL, user-triggered only (anantara/sodex_measure.py)
Bounded SoPoints calibration: farm a tiny capped amount, then read SoPoints
credited to compute real points-per-$. **Live is double-gated and run MANUALLY by
the user — there is NO auto-start service** (deliberate: never run unattended
real-money loops).

```bash
# 1) plan (safe, no orders, no network):
make measure-plan                 # or: python3 anantara/sodex_measure.py plan --budget 20

# 2) LIVE (you trigger it; needs .env loaded for keys + the httpx-capable python):
set -a; . ./.env; set +a
MEASURE_FARM_LIVE=1 /usr/bin/python3 anantara/sodex_measure.py run --live \
  --budget 20 --margin 8 --leverage 3 --pace-seconds 120 --max-rounds 200
#   safety: $20 hard ceiling (persisted, crash-safe), 3x, maker-biased, always flat on exit.
#   stop anytime with Ctrl-C; resumes from persisted baseline if re-run.

# 3) after a few days, read SoPoints credited at sodex.com and:
python3 anantara/sodex_measure.py report --sopoints <credited>   # -> points per $
```
Pre-flight: `python3 anantara/sodex_farming.py validate-signing` (unfillable order
+ cancel, zero fill risk). Verified working 2026-05-23; 2-round proof: $97 vol / $0.02.

## 10. Radical Strategies (research 2026-05-28)

### Multi-Symbol Parallel (HIGHEST IMPACT)
Execute 10 symbols concurrently instead of 1 sequential. With $10 margin × 25× per symbol:
- Volume/cycle: $10,000 (vs $2,325 current)
- Daily volume: $1.44M (vs $288K current)
- Days to Tier 1: **3.5 days** (vs 17 days)
- Maker rebate share: ~5.8% → Rebate Tier 3 (-0.003% → platform PAYS you!)

### Spot 2× Weight Exploit
Spot vBTC_vUSDC spread: 0.0014% (same as perps). Spot volume counts 2× for tier.
Formula: Weighted Vol = Perps + 2×Spot. Spot farming boost tier progression by ~30%.

### SOSO Staking: Buy 270 More
Current: 30 SOSO (5% discount). Target: 300 SOSO (10% discount).
Cost: ~$99. ROI: 5.5% more volume per dollar of fees paid.

### Dynamic Spread Gate (River ML)
Replace static thresholds with ML-driven per-symbol fill-probability gates.
Use River online ML (AUC 0.79-0.83) to skip when adverse selection is high.

### Time-of-Day Blast
317K+ OBI snapshots → find optimal spread windows.
Blast max volume during tightest hours, pause during wide spread.
