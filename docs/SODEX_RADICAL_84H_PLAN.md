# SoDEX Radical 84H Plan

Last updated: 2026-06-20 WIB

This plan is the high-pressure build and validation path before any full-real
trading decision. It does not authorize live orders by itself. The live decision
must pass `make sodex-radical-gate`.

## Hard Deadlines

- Build/validation window: 84 hours from the current operator cycle.
- User event deadline: 2026-07-25 WIB.
- Weekly volume target: at least $1,300,000 official SoDEX credited volume.
- Total Real Ratio target: minimum 1:9,000, maximum target is no net loss.
- Weekly profitable transaction ratio: above 69%.

## Current Blockers

The full-real gate blocks when any of these are true:

- official SoDEX credited volume is below target;
- official net-cost ratio is below 1:9,000;
- E1 profit coverage is short;
- official SoDEX dashboard is materially lower than internal ledger;
- open perp positions are present;
- weekly win rate is below 69%.

## Scientific Definitions

- Official raw volume = SoDEX dashboard `spot + futures`.
- Official weighted volume = `futures + 2 * spot`.
- Gross ratio = official volume / fees.
- Net-cost ratio = official volume / max(fees - E1 realized profit, 0).
- E1 profit coverage = realized profit needed to keep net-cost ratio at least
  1:9,000 and, at maximum quality, reduce net cost to zero.

Internal ledger volume is audit evidence only. It must not replace official
SoDEX credited volume for event progress.

## Radical Operating Thesis

The target cannot be reached by simple volume churn. The engine must become a
two-lane system:

- E1: profit engine. It must harvest enough spread/edge to subsidize all volume
  generation. E1 owns spot capital, low-cap maker capture, inventory skew, and
  forced-flush safety.
- E2: volume engine. It may scale only after E1 closes the profit coverage gap.
  E2 owns futures/perps notional, but only under maker-only, hedged, or
  edge-gated modes.

Fee-only maker volume is not enough for the 1:9,000 ratio target. With the
current planner assumptions, pure maker economics cap near 1:8,333 before E1
profit subsidy. Therefore, the radical formula is:

```text
Total Real Ratio = official credited volume / max(total fees - E1 realized profit, 0)
Required E1 profit = max(0, gross cost - official credited volume / 9000)
```

Example at $1,300,000 weekly official volume:

- pure maker gross cost around $156;
- maximum allowed net cost at 1:9,000 is $144.44;
- minimum E1 profit subsidy is about $11.56 before any extra safety buffer.

## 84H Work Sequence

### Phase 1: Reconciliation First

Goal: eliminate false confidence from internal ledger inflation.

- Treat SoDEX dashboard as canonical.
- Run `make sodex-84h-supervisor` as the top-level read-only mission loop.
- Run `make sodex-reconcile` before any E2 scale increase.
- Recompute `make sodex-radical-gate` every 30 to 60 minutes.
- If official dashboard remains stale while ledger rises, keep mode
  `CAPPED_CATCHUP_RECON_FIRST`.
- Do not increase E2 scale while `official_ledger_reconciliation_gap` is active.

Pass criteria:

- official volume moves in the same direction as ledger after a new official
  screenshot/API update; or
- the gap is understood and documented as dashboard lag.
- total official/ledger credit-rate is at least 75%, and perps credit-rate is
  not critical, before E2 is allowed to amplify volume.

### Phase 2: E1 Profit Burst

Goal: generate the missing E1 profit coverage before scaling E2.

Current required E1 gap is computed by `make sodex-radical-gate`.

Candidate radical methods:

- concentrate spot/E1 capital on the pairs where realized spread capture remains
  positive after maker fees;
- rotate between PEPE, SHIB, and any newly proven SoDEX spot pair only when
  inventory cap and flush safety are green;
- use tighter inventory skew so E1 exits inventory faster instead of trapping
  capital;
- allocate the planned additional $100 spot capital only to E1 after the gate
  confirms spot route quality.

Kill criteria:

- E1 net-cost ratio deteriorates for two consecutive gate cycles;
- inventory value breaches cap;
- forced flush happens at negative realized edge repeatedly;
- official ratio falls while fees rise.

### Phase 3: E2 Volume Amplifier

Goal: use perp/future volume only after E1 profit coverage improves the combined
net-cost ratio.

Candidate radical methods:

- maker-only perps on the tightest pair basket;
- delta-light or hedged two-leg exposure when available;
- short time-in-market with no stacking;
- no scale-up while open positions remain from previous cycles;
- allocate the planned additional $150 perp capital only after E1 gap is under
  control and open-position gate is green.

Kill criteria:

- open perp positions remain across gate cycles;
- taker fills appear;
- ratio falls below the prior gate cycle;
- unrealized PnL drawdown offsets E1 coverage.

### Phase 4: Full-Real Readiness

Full-real is blocked until:

- `make sodex-radical-gate` returns no hard blockers;
- official raw or weighted net-cost ratio is at least 1:9,000;
- E1 profit coverage gap is zero or intentionally overfunded;
- open perp positions are zero before scale-up;
- user explicitly approves the live transition.

## Required Commands

Read-only status:

```bash
python3 scripts/sodex_monitor_eval.py
python3 scripts/sodex_volume_planner.py
make sodex-84h-supervisor
make sodex-reconcile
make sodex-radical-gate
make collector-status
```

24/7 read-only loop:

```bash
python3 scripts/sodex_84h_supervisor.py --loop --interval 900 --refresh-monitor
```

The supervisor writes:

- `data/sodex/mission_supervisor/latest.json`
- `data/sodex/mission_supervisor/history.jsonl`

It never places orders, transfers funds, changes leverage, or authorizes live
trading by itself.

Focused verification:

```bash
python3 -m unittest tests.test_sodex_volume_planner tests.test_sodex_radical_gate tests.test_sodex_reconciliation_audit tests.test_sodex_84h_supervisor -v
python3 -m py_compile scripts/sodex_volume_planner.py scripts/sodex_radical_gate.py scripts/sodex_reconciliation_audit.py scripts/sodex_84h_supervisor.py
```
