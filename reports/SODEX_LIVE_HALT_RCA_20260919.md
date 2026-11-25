# SoDEX Live Halt RCA — 2026-09-19 01:01 WIB

## Problem statement
Weekly SoDEX live fills are zero while live services appear active. Need know whether this is service failure, valid containment, or stale blocker.

## Evidence
- `data/SAFETY_HALT`: active, payload timestamp `2026-08-01T07:43:15Z`, reason `loss-cap`; file mtime `2026-09-06T05:43:14Z`.
- `data/REALWIDE_LIVE_KILL`: active, empty sentinel, mtime `2026-09-11T15:19:19Z`.
- `data/SPOT_LIVE_KILL`: active, empty sentinel, mtime `2026-09-11T15:19:19Z`.
- `logs/realwide_micro_live.log`: repeats `HALT: KILL_SWITCH` every 5 min.
- `logs/spot_live_test.log`: repeats `KILL switch present — no trading` every 5 min.
- `twin_engine.db` latest `fills/rts`: `2026-07-23T07:35:41Z`; current weekly window has 0 fills and 0 RTs.
- Real sync/watchdog: 0 perps positions, 0 open orders, clean reconciliation.
- Recovery monitor: NORMAL; live kills remain true; paper tracks continue.

## KT IS / IS NOT
| Dim | IS | IS NOT | Distinction | Change / latent condition |
|---|---|---|---|---|
| WHAT | Live fills zero despite active services | Paper tracks still producing evidence | Live services are contained by sentinels, not crashed | Kill files and global halt are active |
| WHERE | Realwide/spot live engines, weekly ledger | Realsync/watchdog/read-only monitors | Execution paths check native kill sentinels | Monitor previously reported only SAFETY_HALT, not live kill files |
| WHEN | Current weekly window 2026-09-12..19 | Historical fills existed until 2026-07-23 | Live containment after reconciliation defects | 2026-09-11 kill switch containment remains active |
| EXTENT | 0 weekly live fills, 0 RTs, no open positions | Paper REALWIDE/TWOWAY/SPOT continue | No capital at risk now; no orders being sent | Intentional fail-closed state |

## Root cause
Primary root cause: live execution is intentionally blocked by `REALWIDE_LIVE_KILL` and `SPOT_LIVE_KILL`, plus global `SAFETY_HALT`. Services are active but loop into no-trading state.

Contributing cause: `sodex_monitor_eval.py` reported `SAFETY_HALT` but did not expose native live kill files, so dashboard/operator view under-explained why fills stayed zero.

Rejected hypotheses:
- Service crash: rejected; live services active and logs update every 5 minutes.
- Exchange/local mismatch currently open: rejected now; watchdog/realsync show 0 positions and 0 open orders.
- Forced live should be resumed automatically: rejected; clearing sentinels could immediately allow real orders, requiring explicit GO-LIVE decision.

## Corrective action executed
- Updated `scripts/sodex_monitor_eval.py` to report `live_kills` and add repair-plan action `LIVE_KILL_ACTIVE_NO_TRADING`.
- Added regression tests in `tests/test_sodex_monitor_eval.py`.
- Did not clear halt/kill files. Did not restart live services. Did not place orders.

## Verification
- `python3 -m pytest tests/test_sodex_monitor_eval.py tests/test_sodex_stability_check.py tests/test_cex_learning_analyzer.py -q --tb=short` → 63 passed.
- `python3 -m pytest tests/ -q --tb=short` → 3739 passed, 13 skipped, 83 subtests passed.
- `python3 scripts/sodex_monitor_eval.py --no-api --no-persist` now prints `live_kills: REALWIDE_LIVE_KILL, SPOT_LIVE_KILL` and repair action `LIVE_KILL_ACTIVE_NO_TRADING`.

## Decision
Remain fail-closed. Next safe action is paper/recovery monitoring, not live unblock.

To unblock live, required explicit GO-LIVE approval and separate preflight: current account sync with env sourced, no open positions/orders, kill/halt archive not delete, then restart one live service at a time with 30-minute monitor.
