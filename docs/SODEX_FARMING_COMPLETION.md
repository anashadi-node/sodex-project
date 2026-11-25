# SoDEX Farming Completion Report

Updated: 2026-06-10 18:30 WIB

## Completion Status

SoDEX farming is complete as a guarded, evidence-driven operating system:

- Autonomous read-only research service is installed, enabled, and running.
- Spot live execution is wired behind event-risk and adaptive-policy gates.
- Governor target tracking, risk state, kill switch, stale-lock detection, and wrapper doctor are operational.
- Unit tests, syntax checks, secret hygiene, port locality, and knowledge health pass.
- Live trading is intentionally blocked while the current market/event regime is unsafe.

This is the correct completed state for the current evidence. Completion does
not mean forcing orders when the guard says the route has negative expectancy.

## Latest Verified Evidence

Commands run on 2026-06-10:

```bash
bash scripts/quality_check.sh
python3 scripts/sodex_spot_daemon.py status
python3 scripts/sodex_spot_daemon.py doctor
systemctl --user status sodex-autonomous-research --no-pager
```

Results:

- `QUALITY GATE PASSED`
- `sodex-autonomous-research.service` active and enabled
- Research status fresh
- Learning strength: `STRONG_LEARNING_ACTIVE`
- Learning score: `100`
- Outcomes observed: `36,599`
- Current live route: `SPOT_LONG`
- Operator status: `BLOCKED_EVENT_RISK`
- External live gate: `BLOCK_LIVE`
- Event level: `RED`
- Event opportunity route: `PERPS_SHORT`
- Spot live route decision: blocked by event risk

## Current Trading Decision

Do not force `SPOT_LONG` live.

Reason:

- Event risk is RED.
- Live gate is `BLOCK_LIVE`.
- Route policy blocks `SPOT_LONG`.
- Current opportunity bias is `SHORT`, and `PERPS_SHORT` is research-only during the shock.

The completed system is doing its job: it keeps learning, blocks unsafe live
execution, and waits for evidence-backed promotion before allowing capital.

## Completed Components

| Component | Status | Evidence |
|---|---:|---|
| Autonomous research loop | Complete | systemd service active |
| Event shock guard | Complete | RED gate blocks live |
| Adaptive policy gate | Complete | route-level promote/block/watch decisions |
| Spot daemon wrapper | Complete | `status`, `doctor`, `kill`, `unkill`, `once` |
| Spot governor | Complete | weekly target, drawdown, win-rate, ratio tracking |
| Autofarm execution guard | Complete | preflight before subprocess launch |
| Knowledge vault | Complete | doctor status OK |
| Test suite | Complete | 974 tests passing |
| Quality gate | Complete | passed on 2026-06-10 |

## Remaining Non-Blocking Work

These are improvement items, not blockers to completion:

- Reduce or deduplicate historical OBI duplicate rows. The current quality gate reports them but does not fail.
- Sync older docs that still describe deprecated GTX/wide-farm paths.
- Re-run live route check after event risk returns to normal.
- Add a concise dashboard view for weekly volume progress and guard reason.

## Operating Rule

Live SoDEX farming may resume only when all are true:

- Event live gate is not `BLOCK_LIVE`.
- Adaptive policy promotes the intended live route.
- The route has positive learned edge and meets the target win-rate rule.
- Kill switch is off and no autofarm lock is active.
- `bash scripts/quality_check.sh` passes.

