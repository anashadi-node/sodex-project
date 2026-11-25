# SoDEX Division Audit R2 — 2026-09-11

## Scope

Audit ulang source-of-truth exchange, seluruh paper tracks, active live entrypoints, systemd services, state files, logs, target denominator, regression tests, and suspicious-code patterns.

Credential/private-key values tidak dibaca ke laporan.

## Executive verdict

Target wallet ROI >= 0.7% belum terbukti stabil. Lebih penting: pada audit ini ditemukan divergence antara exchange dan local state. Live entry harus tetap HALT sampai rekonsiliasi manual selesai.

Tidak ada klaim "100% bebas bug selamanya". Yang diverifikasi adalah defect yang ditemukan, fix yang diterapkan, test yang lulus, dan residual risk yang masih terbuka.

## Exchange truth — latest successful sync

Snapshot: `data/sodex_real_sync_snapshot.json` (latest observed 2026-09-11T15:24:10Z)

- Perps balance: $92.909633396352293124
- Current observed perps position: AAVE-USD size 0.35
- Earlier read in same audit observed HYPE-USD size 0.81 and AAVE-USD size 0.35; later snapshots showed only AAVE. HYPE close/ownership event belum direkonsiliasi.
- Open orders: 0
- Spot rows: 15
- Spot bid-marked equity: $67.3869851210875
- Spot unpriced: `vsMAG7.ssi`, `aUNITREE`
- Conservative priced lower bound: $160.296618517440
- Lower-bound 0.7% target: $1.122076329622

`$108.10` tidak lagi dianggap denominator valid. Tidak diubah otomatis karena dua holdings tidak punya mark-to-market resmi.

## Critical findings

### C1 — Exchange/local position divergence

**IS:** exchange reported live perps position(s), local live state `open={}`.

**WHERE:** `realwide_micro_live_state.json` vs authoritative `/accounts/{address}/positions` endpoint.

**WHEN:** latest audit; AAVE present in latest snapshot, HYPE appeared in prior successful snapshot.

**EXTENT:** at least one confirmed untracked perps position; event ownership and close history unresolved.

**Root cause:** live engine trusted local state for entry/exit, while watchdog only checked periodically. Legacy/manual/external execution can create positions not represented in local state.

**Fix:**
- watchdog now detects untracked perps positions;
- realwide live entry guard blocks new entries unless exchange symbols exactly match local state;
- API error also blocks entries;
- live kill switch enabled.

**Residual:** existing untracked AAVE must be reconciled by owner/exchange history. No close order was sent automatically.

### C2 — Spot source-of-truth incompleteness

**IS:** account has 15 spot balance rows; local spot state has no open positions.

**Root cause:** sync originally stored only `spot_vusdc`, discarding non-vUSDC balances.

**Fix:** sync now persists `spot_balances`, spot marks, `spot_equity_usd`, and `spot_unpriced`. Watchdog scans all non-zero non-vUSDC holdings and blocks live spot entries on mismatch.

**Residual:** old/legacy holdings require explicit classification. No automatic allowlist was added.

### C3 — Denominator materially stale

Old scripts used inconsistent values: 94.572, 119.67, 139.37, 107.70, and 108.10.

**Fix:** active scripts use runtime env/fallback policy; wallet denominator now reads marked spot equity and fails closed when holdings are unpriced.

**Current status:** `.env.swing` must not be promoted from 108.10 to an invented value. `sodex_wallet_denominator.py` exits non-zero when `vsMAG7.ssi`/`aUNITREE` are unpriced. This is intentional.

### C4 — HYPE spot fetch mismatch

Swing paper used Binance spot-only endpoint for HYPE, causing recurring `Invalid symbol` and biased asset coverage.

**Fix:** spot-to-futures fallback added to hourly and 15m confirmation fetch. Confirmation changed from fail-open to fail-closed. Pasar-Anantara fallback stale denominator also corrected.

### C5 — Live service restart defeated manual stop

Both live units use `Restart=always`.

**Fix/containment:** native kill files enabled:

- `data/REALWIDE_LIVE_KILL`
- `data/SPOT_LIVE_KILL`

Services remain installed and reversible, but live engine must not open/close automatically while reconciliation is unresolved.

## Paper/live progress

All SoDEX paper services remained active during containment, including Short-Bear priority. Live services are contained, not promoted.

SHORT-BEAR remains paper-only. n is still far below n>=20 initial evaluation and n>=50 live candidate threshold. No gate was loosened to manufacture trade count.

Aggregate historical tracks are not treated as proof of current edge. REALWIDE/TWOWAY recent-window degradation remains a target risk. Fees, slippage, funding, latency, fill/reject rate, and independent OOS reconciliation remain required evidence.

## Regression and security verification

Latest full suite after prior SoDEX changes:

```text
3502 passed, 8 skipped, 292 warnings, 34 subtests passed
124.29 seconds
```

Latest targeted suite after R2 fixes:

```text
23 passed, 0 failed
```

Checks:

- modified SoDEX files py_compile: PASS
- targeted git diff check: PASS
- no new `dry_run=False` / `shuffle=True` in active SoDEX scope
- no credential values exposed
- no withdrawal executed
- no close order executed
- static scan findings in retired/non-SoDEX audit helpers were not treated as active SoDEX malware

Warnings: deprecation warnings remain in unrelated tests; they are technical debt, not test failures.

## Bottleneck

Single limiting constraint: trustworthy forward, cost-adjusted expectancy after exchange/local reconciliation. More entries, leverage, or services cannot solve missing source-of-truth.

## Acceptance criteria before live resume

1. Reconcile AAVE/HYPE ownership, order IDs, side, entry, size, margin, and intended exit with exchange history.
2. Classify every non-vUSDC spot row; close/recover or explicitly document legacy/manual dust. Do not silently allowlist.
3. Achieve a successful sync with zero unpriced holdings or an approved auditable valuation policy.
4. Run watchdog with zero CRITICAL mismatch.
5. Run entry-guard tests and full suite green.
6. Remove kill files only after explicit approval and re-verification.
7. Keep SHORT-BEAR paper-only until n>=50 and net cost-adjusted evidence passes.

## Current decision

**LIVE: HALT/CONTAINED. PAPER: CONTINUE. SHORT-BEAR: PRIORITY #1.**

No claim of 0.7% stability. No leverage increase. No gate relaxation. No live promotion.
