# SoDEX v2 Upgrade — Bug Report
**Date**: 2026-06-16 | **Account**: 180570 (0x0794…8ef47) | **CLI**: bin/sodex (post-upgrade)

## Bug 1: SOL-USD Ghost Position (CRITICAL)
**Symptom**: `leverage SOL-USD 5` returns "cannot update leverage with open positions" but `positions` returns `null`.

**Steps to reproduce**:
1. Had SOL SHORT -1.514 @ $74.34 before upgrade
2. Post-upgrade: placed reduce-only BUY 1.514 @ 74.30 — filled ✅
3. USDC balance increased confirming close
4. `positions` returns `null`
5. `leverage SOL-USD 5` STILL fails with "open positions"
6. Market IOC reduce-only BUYs also fill but ghost persists

**Impact**: Cannot open new SOL-USD positions. Leverage locked.

---

## Bug 2: All Perps — New Position Orders Return orderID=0 (CRITICAL)
**Symptom**: ALL `orders place perps` (non-reduce-only) return `orderID: 0` with empty error.

**Tested symbols**: BTC-USD, ETH-USD, SOL-USD, 1000PEPE-USD, SPCX-USD, DOGE-USD

**What works**:
- ✅ Leverage updates (all symbols except SOL)
- ✅ Tickers, orderbook, markets, balance
- ✅ Reduce-only orders on SOL (to close)
- ✅ Spot engine (PEPE/USDC, SHIB/USDC) — fully functional

**What fails**:
- ❌ All new perps position orders (any symbol, any side)
- ❌ Market orders (IOC): `timeInForce is invalid` without explicit --tif ioc
- ❌ Reduce-only on symbols WITHOUT existing position

**Suspected cause**: Perps engine in close-only/reduce-only mode post-upgrade.

---

## Bug 3: Positions API Returns null
**Symptom**: `bin/sodex positions` returns `null` even when positions exist (verified by leverage check).

**Expected**: Empty array `[]` when no positions, or position objects when positions exist.

---

## CLI Changes Noted (v1 → v2)
- `account balance` → `balance [spot|perps]`
- `orders cancel`: now requires `--symbol-id` (numeric) + `--order-id`
  - SPOT: requires BOTH `--order-id` AND `--cl-ord-id`
  - PERPS: only `--order-id` needed
- `orders list`: requires `[spot|perps]` positional arg
- NEW: `tickers [spot|perps]`, `positions`, `leverage`, `transfer`
- REMOVED: `funding` command; funding rate now in `tickers perps` response
- REST API paths changed (all return 404)

## Request
1. Clear SOL-USD ghost position
2. Enable full perps trading (remove close-only restriction)
3. Fix positions API null response
4. Document CLI migration guide for API users
