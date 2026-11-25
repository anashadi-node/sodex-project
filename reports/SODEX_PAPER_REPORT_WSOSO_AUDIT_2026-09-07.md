# SODEX — REPORT PAPER TEST LENGKAP + AUDIT ASET WSOSO (2026-09-07)

## A. REPORT PAPER TEST (semua track, wallet $139.37)

| Track | n | WR% | avg wallet ROI/trade | PF | cum wallet ROI% | trades >=0.7% | open |
|---|---|---|---|---|---|---|---|
| realwide | 77 | 58 | +2.288% | 2.43 | +176.17 | 38 (49%) | 8 |
| twoway | 160 | 51 | +0.948% | 1.56 | +151.73 | 80 (50%) | 6 |
| swing | 171 | 46 | +0.701% | 1.23 | +119.83 | 77 (45%) | 4 |
| donchian | 62 | 47 | +0.547% | 1.39 | +33.90 | 28 (45%) | 5 |
| spot_swing_v2 | 20 | 45 | +0.325% | 1.81 | +6.50 | 6 (30%) | 5 |
| aster | 28 | 43 | +0.255% | 1.27 | +7.15 | 12 (43%) | 6 |
| swing_partial | 168 | 57 | +0.155% | 1.30 | +26.09 | 86 (51%) | 7 |
| portfolio | 5 | 40 | -0.272% | 0.73 | -1.36 | 1 | 3 |
| shortbear | 1 | 0 | -1.110% | 0.0 | -1.11 | 0 | 0 |
| hyperliquid | 2 open (BTC+ETH, fix baru 07 Sep) | - | - | - | - | - | 2 |

GRAND: 692 closed trades, WR 51%, cumW +518.9%, 328 (47%) tercapai >=0.7%/trade.

Insight:
1. REALWIDE role-model: +2.288%/trade = 3.3x target, PF 2.43, WR 58%.
2. TWOWAY #2: +0.948%/trade, PF 1.56.
3. SWING tepat target (+0.701%), margin warp-tipis (WR 46%).
4. HYPERLIQUID kembali jalan post-fix (BTC+ETH entry).

## B. AUDIT MENDALAM ASET "SSOSO" (konklusi: = WSOSO, wrapped SOSO)

### Fakta terbukti (source of truth: exchange API + trade history)
1. Pair "SSOSO_vUSDC" TIDAK EXISTS (API: symbol not found). Token SOSO-family di SoDEX = WSOSO (spot wrapped) + SOSO (native staking).
2. SOSO price ~$0.27-0.37; staking 30+ = 5% fee discount (stake tier 1), 300+ = 10% (tier 2).
3. TRADE HISTORY REAL (semua $ fills akun, ~600 lifetime):
   - 2026-08-05 BUY 33 WSOSO @0.3638 (web dashboard user)
   - 2026-08-06 BUY 13 WSOSO @0.359
   - 2026-08-07 BUY 16.72 WSOSO @0.3587
   - NO SELL WSOSO EVER in trade history. NIL market-sell discovered.
4. Balance spot sekarang (API live): WSOSO=0.0000563 (dust), SOSO=0, vUSDC=$28.37.
5. Fee-rate endpoint: feeTier 0, stakingTier 1 -> SOSO STAKING AKTIF (30+).

### Kesimpulan audit
Aset "SSOSO" = WSOSO. Tidak pernah dijwar via market (0 sell trade). Kebanyakan went ke STAKING (stakingTier=1 active -> balance off-balance-sheet). Kata lain: internal sub-account transfer. Bukan di-redeem ke USDC visible (no sell credit).

### Tindakan user di dashboard
1. Dashboard -> Wallet/Staking tab: cek staked SOSO balance.
2. Cek sub-accounts (internal transfer).
3. Jika both empty: contact SoDEX support dgn tradeID evidence (62.72 bought, never sold).

## C. STATUS INFRA
- 12 service active, 55+ test pass (incl 6 multivenue regresi fix).
- Hyperliquid deep fix (allMids schema) mungkicoin: track jalan kembali.
- Watchdog: 0 CRITICAL.