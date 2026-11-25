# SoDEX + CEX-Binance Progress Report — 2026-09-21 21:22 WIB

## Executive status

- SoDEX runtime: ACTIVE, watchdog clean after live-state phantom fix.
- CEX-Binance runtime: ACTIVE in paper/research mode; GO-LIVE remains NO-GO because gates/kill are triggered by signal-vs-random evidence.
- Production safety: no secret/shuffle/dry_run regression found in touched code scan.
- Full repo QA: still not perfect — `python3 -m pytest tests/ -q --tb=short` has 53 failures, concentrated in pre-existing SoDEX spot/twin-engine test expectations. Focused SoDEX/CEX gates pass.

## SoDEX

### Current runtime

| Check | Result |
|---|---:|
| `anantara-realwide-livetest.service` | active |
| `anantara-spot-livetest.service` | active |
| `anantara-paper-realwide.service` | active |
| `anantara-sodex-watchdog.timer` | active |
| `anantara-sodex-recovery-monitor.timer` | active |
| Watchdog manual | 0 alert / 0 critical |
| Recovery monitor | NORMAL / issues=0 |
| Real perps positions | 0 |
| Real open orders | 0 |
| Local realwide open state | 0 after fix |

### Bug found + fixed

Deviation: `anantara-sodex-watchdog.service` flagged CRITICAL PHANTOM: local `realwide:BTC` claimed open, but exchange snapshot had 0 real positions and 0 open orders.

Root cause: long-running `realwide_micro_live.py --loop` loaded state once before the loop. External reconciliation fixed the JSON state, but the live process kept stale in-memory state and overwrote the fix on the next cycle.

Fix applied:

```python
# scripts/realwide_micro_live.py
if a.loop:
    while True:
        st = load_state()
        cycle(st, live=a.live)
```

Safety action:

- Stopped realwide service temporarily to prevent stale overwrite.
- Verified exchange flat: positions=0, open_orders=0.
- Archived phantom state, not deleted:
  - `data/realwide_micro_live_state.json.phantom_backup_20260921T141742Z`
  - `data/sodex_phantom_resolve_20260921T141742Z.json`
- Restarted service after focused regression passed.
- Manual watchdog after restart: `Rekonsiliasi bersih: 0 posisi lokal, 0 posisi real, match 100%`.

### SoDEX tests

```text
33 passed in 0.41s
```

Covered:

- `tests/test_realwide_micro_live_persist_on_exit.py`
- `tests/test_sodex_recovery_monitor.py`
- `tests/test_sodex_live_watchdog.py`
- `tests/test_sodex_realtime_sync.py`

## CEX-Binance

### Current runtime

Active services/timers verified:

- `anantara-paper-cex-momadx.service`
- `anantara-paper-spot-momadx.service`
- `anantara-paper-spot-swing-v2.service`
- `paper-test-futures-swing-cex.service`
- `paper-test-spot-swing-cex-spot.service`
- `cex-go-no-go-gate.timer`
- `cex-futures-deep-loop.timer`
- `cex-spot-deep-loop.timer`

### Quant progress

#### Futures / combined paper state

| Track | Closed n | Open | WR | Sum PnL pct | Avg PnL pct |
|---|---:|---:|---:|---:|---:|
| SIGNAL | 189 | 0 | 40,74% | +31,6448% | +0,1674% |
| RANDOM | 220 | 3 | 42,27% | +30,2651% | +0,1376% |

Interpretation: futures/combined SIGNAL has slightly higher average PnL than random, but WR is lower and GO/NO-GO still fails because kill/gates are not statistically safe yet.

GO/NO-GO highlights:

- Futures G1: FAIL — `net_usd=-10.79`, `PF=0.77`, `WR=24,6%`, `delta_vs_random=-0,222%`.
- Futures G2: FAIL — DSR `0,2298` < `0,95`.
- Futures kill: TRIGGERED — last50 PF `0,71`, last50 WR `24,0%` vs baseline WR `39,3%`.
- Window achievement: 8/23 windows = 34,8% reached target 0,7% total-wallet/window.
- Best current path: `momentum+adx+regime`, n=17, WR=70,59%, expectancy +1,2476% per trade, but binom p=0,0717 and n<30, so still research/probe, not live.

#### Spot paper state

| Track | Closed n | Open | WR | Sum PnL pct | Avg PnL pct |
|---|---:|---:|---:|---:|---:|
| SIGNAL | 56 | 0 | 25,00% | -17,3482% | -0,3098% |
| RANDOM | 49 | 3 | 40,82% | +9,9104% | +0,2023% |

Interpretation: spot SIGNAL is objectively worse than random now. Deep-loop quarantine is correct.

Spot deep-loop highlights:

- `spot-ofi-long`: veto=true, n=49, WR=26,5%, expectancy -0,225%, net -11,047%.
- `spot-mom-adx`: probe=true, n=7, expectancy -0,900%, still below n=8 threshold.
- Signal-vs-random: obs_diff `-0,512%`, p=0,2485, verdict `NO_EDGE`.
- SPRT: `REJECT_EDGE`, LLR `-3,78` below lower `-2,944`.
- Spot kill: TRIGGERED — last50 PF `0,49`, last50 WR `20,0%`.
- Spot projected n by deadline: 56 vs target n=158, not on track.

### CEX tests

```text
264 passed in 6.08s
```

Scope: `tests/test_cex*.py`.

## QA / Pre-deploy evidence

Focused gates:

```text
SoDEX focused: 33 passed in 0.41s
CEX focused: 264 passed in 6.08s
py_compile: OK
Secret: BERSIH
Shuffle: BERSIH
Dry_run: BERSIH
```

Full repo gate:

```text
python3 -m pytest tests/ -q --tb=short
=> FAIL, 53 failures
```

First observed failure category:

- `tests/test_sodex_spot_farming.py` expects legacy `async def job_sodex_farm():` in `anantara/anantara_daemon.py`, but that exact function no longer exists.
- This is not caused by the realwide phantom fix, but it blocks a fully clean release claim.

Other system failed unit:

- `alpaca-periodic-scan.service` remains failed. Out of scope for SoDEX/CEX, but system-wide perfection requires Alpaca follow-up.

## Verdict

- SoDEX: runtime bug fixed and live services active; current reconciliation clean.
- CEX-Binance: runtime active, tests pass, but live readiness remains blocked by statistical evidence. Correct action is keep paper/research containment, not loosen gates.
- Not yet “sempurna” system-wide because full repo still has 53 test failures and Alpaca has 1 failed service.

## Next action

Fix `tests/test_sodex_spot_farming.py` failure cluster and related SoDEX spot/twin-engine regressions until full `pytest tests/` is green, then commit/deploy cleanly.
