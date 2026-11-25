# SoDEX Project Structure

Generated UTC: `2026-07-16T14:22:06.411969+00:00`

Mode: `READ_ONLY_SODEX_PROJECT_STRUCTURE`

Policy: `no moves, no deletes, no live actions; canonical structure only`

## Summary

- Total indexed files: `182`
- `core_decision`: `10`
- `data`: `27`
- `docs`: `30`
- `execution`: `6`
- `legacy_or_archive`: `34`
- `market_data`: `6`
- `research`: `10`
- `safety`: `10`
- `services`: `12`
- `tests`: `37`

## Canonical Domains

### `core_decision`

Read-only decision, target, probability, policy, and volume planning layer.

Canonical entry points:
- `scripts/sodex_quant_stat_engine.py`
- `scripts/sodex_system_map.py`
- `scripts/sodex_target_policy.py`

### `safety`

Safety halt, guardian, deadman, reconciliation, and order-surface controls.

Canonical entry points:
- `scripts/sodex_safety_guardian.py`
- `scripts/sodex_deadman_switch.py`
- `scripts/sodex_order_surface_audit.py`

### `execution`

Order-capable or historically order-capable engines; must stay behind operator approval and guards.

Canonical entry points:
- `anantara/sodex_twin_engine.py`
- `scripts/sodex_micro_pilot.py`
- `anantara/sodex_farming.py`

### `market_data`

Collectors, ticker scans, OBI, funding, and monitor evaluation inputs.

Canonical entry points:
- `scripts/sodex_market_ticker_scanner.py`
- `scripts/sodex_monitor_eval.py`
- `scripts/sodex_funding_collector.py`

### `research`

Backtests, paper tests, autonomous research, and academic/quant experiments.

Canonical entry points:
- `scripts/research`
- `scripts/sodex_autonomous_research.py`
- `docs/SODEX_QUANT_STAT_ANALYTIC_TRADING_RESEARCH_2026-07-16.md`

### `services`

Systemd unit files and operator service/timer entry points.

Canonical entry points:
- `systemd/sodex-monitor-eval.timer`
- `systemd/sodex-market-ticker-scanner.service`

### `docs`

Human-readable operating doctrine, system map, status, audit, and handover material.

Canonical entry points:
- `docs/SODEX_SYSTEM_MAP.md`
- `docs/SODEX_PROJECT_STRUCTURE.md`

### `data`

Generated local state, latest reports, JSONL histories, halt flags, and ledgers.

Canonical entry points:
- `data/sodex_quant_stat/latest.json`
- `data/sodex_system_map/latest.json`
- `data/SAFETY_HALT`

### `tests`

Unit and regression tests for SoDEX safety, decision, monitoring, and execution helpers.

Canonical entry points:
- `tests/test_sodex_quant_stat_engine.py`
- `tests/test_sodex_project_structure.py`

### `legacy_or_archive`

Historical reports, old drafts, and compatibility artifacts. Keep read-only unless explicitly migrated.

Canonical entry points:
- `docs/archive`
- `docs/*STATUS*`
- `reports/*SODEX*`

## Indexed Files

### `core_decision`

- `scripts/sodex_e2dir_amplifier.py` (present)
- `scripts/sodex_event_barbell.py` (present)
- `scripts/sodex_mode_audit.py` (present)
- `scripts/sodex_project_structure.py` (present)
- `scripts/sodex_quant_stat_engine.py` (present)
- `scripts/sodex_scalp_microstructure.py` (present)
- `scripts/sodex_system_map.py` (present)
- `scripts/sodex_ta_probability_gate.py` (present)
- `scripts/sodex_target_policy.py` (present)
- `scripts/sodex_volume_planner.py` (present)

### `data`

- `data/SAFETY_HALT` (generated)
- `data/SODEX_SPOT_SELL_VERIFIED` (generated)
- `data/halt_archive/SAFETY_HALT.cleared-20260711T114446Z.json` (generated)
- `data/halt_archive/SAFETY_HALT.cleared-20260711T114925Z.json` (generated)
- `data/halt_archive/SAFETY_HALT.cleared-20260712-0603.json` (generated)
- `data/halt_archive/SAFETY_HALT.cleared-20260712-0622-real-equity-guard.json` (generated)
- `data/sodex/mission_supervisor/latest.json` (generated)
- `data/sodex/research/autonomous_learning.json` (generated)
- `data/sodex/research/autonomous_status.json` (generated)
- `data/sodex/sodex_ledger.db` (generated)
- `data/sodex/twin_engine.db` (generated)
- `data/sodex_deep_learning.jsonl` (generated)
- `data/sodex_e1_recovery_operator_card.md` (generated)
- `data/sodex_funding/funding_history.jsonl` (generated)
- `data/sodex_funding/funding_signals_latest.json` (generated)
- `data/sodex_learned_params.json` (generated)
- `data/sodex_market_scan/latest.json` (generated)
- `data/sodex_micro_pilot.jsonl` (generated)
- `data/sodex_monitor_eval/latest.json` (generated)
- `data/sodex_monitor_eval/official_dashboard.json` (generated)
- `data/sodex_profit_baseline.json` (generated)
- `data/sodex_project_structure/latest.json` (generated)
- `data/sodex_quant_stat/history.jsonl` (generated)
- `data/sodex_quant_stat/latest.json` (generated)
- `data/sodex_spot_sell_support_packet.json` (generated)
- `data/sodex_system_map/latest.json` (generated)
- `data/sodex_watchlist_gate/latest.json` (generated)

### `docs`

- `docs/RISET_SCALPING_LOW_LIQUIDITY_DEX.md` (present)
- `docs/SODEX_4H_TEST_REPORT_2026-06-20.md` (present)
- `docs/SODEX_COMPENDIUM_FOR_MYTHOS.md` (present)
- `docs/SODEX_E2_RESEARCH_2026-06-20.md` (present)
- `docs/SODEX_FARMING_AZ_REPORT_2026-07-12.html` (present)
- `docs/SODEX_FARMING_AZ_REPORT_2026-07-12.md` (present)
- `docs/SODEX_FARMING_COMPLETION.md` (present)
- `docs/SODEX_FARMING_COMPREHENSIVE.md` (present)
- `docs/SODEX_FARMING_DOCTRINE.md` (present)
- `docs/SODEX_FARMING_HANDOFF.md` (present)
- `docs/SODEX_FARMING_HANDOVER_2026-06-25.md` (present)
- `docs/SODEX_FARMING_MASTERPLAN_2026-06-18.md` (present)
- `docs/SODEX_FARMING_RESEARCH_REPORT_2026-07-08.html` (present)
- `docs/SODEX_MONITOR_EVALUATION.md` (present)
- `docs/SODEX_PROJECT_STRUCTURE.md` (present)
- `docs/SODEX_QUANT_STAT_ANALYTIC_TRADING_RESEARCH_2026-07-16.md` (present)
- `docs/SODEX_RADICAL_84H_PLAN.md` (present)
- `docs/SODEX_SYSTEM_MAP.md` (present)
- `docs/SODEX_TA_PROBABILITY_GATE_AUDIT_2026-07-16.md` (present)
- `docs/SODEX_V2_BUG_REPORT.md` (present)
- `docs/SODEX_WATCHLIST_GATE.md` (present)
- `docs/superpowers/specs/2026-06-29-sodex-farming-radical-overhaul-design.md` (present)
- `reports/SODEX_12WALLET_AUDIT_20260714.html` (present)
- `reports/SODEX_FARMING_AUDIT_REKOMENDASI_2026-06-12.md` (present)
- `reports/SODEX_FARMING_AUDIT_REKOMENDASI_2026-06-12.pdf` (present)
- `reports/SODEX_FARMING_AUDIT_ROOT_CAUSE_2026-06-29.md` (present)
- `reports/SODEX_FARMING_ENGINE_UPGRADE_2026-07-11.md` (present)
- `reports/SODEX_FARMING_OVERHAUL_RESULTS_2026-06-29.md` (present)
- `reports/SODEX_FARMING_VOLUME_STRATEGY_2026-06-30.md` (present)
- `reports/SODEX_RADICAL_RESEARCH_2026-07-08.md` (present)

### `execution`

- `anantara/sodex_autofarm.py` (present)
- `anantara/sodex_farming.py` (present)
- `anantara/sodex_measure.py` (present)
- `anantara/sodex_twin_engine.py` (present)
- `scripts/sodex_micro_pilot.py` (present)
- `scripts/sodex_spot_daemon.py` (present)

### `legacy_or_archive`

- `anantara/perps_volume_engine.py` (present)
- `anantara/scalp_predictor.py` (present)
- `anantara/skills/sodex-api-patterns.md` (present)
- `anantara/sodex_deep_learner.py` (present)
- `anantara/sodex_directional.py` (present)
- `anantara/sodex_event_shock_guard.py` (present)
- `anantara/sodex_governor.py` (present)
- `anantara/sodex_intel_layer.py` (present)
- `anantara/sodex_model_server.py` (present)
- `anantara/sodex_pregain_scanner.py` (present)
- `anantara/sodex_signal.py` (present)
- `anantara/sodex_spot_farm.py` (present)
- `anantara/sodex_spot_governor.py` (present)
- `anantara/sodex_state_io.py` (present)
- `anantara/sodex_wide_farm.py` (present)
- `docs/SODEX_FARMING_STATUS_2026-06-25.md` (present)
- `docs/SODEX_FARMING_STATUS_2026-06-26.md` (present)
- `docs/archive/src_draft_20260527/sodex_integration.py` (present)
- `scripts/build_sodex_cli.sh` (present)
- `scripts/gen_sodex_audit_html.py` (present)
- `scripts/sodex_84h_supervisor.py` (present)
- `scripts/sodex_deep_learn.py` (present)
- `scripts/sodex_downloader.py` (present)
- `scripts/sodex_e1_autopilot.py` (present)
- `scripts/sodex_e1_recovery_gate.py` (present)
- `scripts/sodex_event_runway.py` (present)
- `scripts/sodex_live_short_accelerator.py` (present)
- `scripts/sodex_mode2_metrics.py` (present)
- `scripts/sodex_profit_report.py` (present)
- `scripts/sodex_profit_scan.py` (present)
- `scripts/sodex_radical_gate.py` (present)
- `scripts/sodex_refresh_intel_snapshot.py` (present)
- `scripts/sodex_spot_sell_recovery.py` (present)
- `scripts/sodex_watchlist_gate_accelerator.py` (present)

### `market_data`

- `anantara/sodex_funding_collector.py` (present)
- `scripts/sodex_market_ticker_scanner.py` (present)
- `scripts/sodex_monitor_eval.py` (present)
- `scripts/sodex_obi_collector.py` (present)
- `scripts/sodex_spot_collector.py` (present)
- `scripts/sodex_spot_monitor.py` (present)

### `research`

- `scripts/research/analyze_scalp_regime.py` (present)
- `scripts/research/backtest_freqai_sodex.py` (present)
- `scripts/research/backtest_scalp_lt.py` (present)
- `scripts/research/backtest_scalp_tb.py` (present)
- `scripts/research/backtest_scalp_v2.py` (present)
- `scripts/research/backtest_scalp_wf.py` (present)
- `scripts/research/sim_sodex_farming.py` (present)
- `scripts/sodex_autonomous_research.py` (present)
- `scripts/sodex_maker_paper_test.py` (present)
- `scripts/sodex_maker_paper_v2.py` (present)

### `safety`

- `anantara/sodex_guardian_daemon.py` (present)
- `scripts/engine_watchdog.py` (present)
- `scripts/hl_watchdog.py` (present)
- `scripts/sodex_autonomous_guardian.py` (present)
- `scripts/sodex_deadman_switch.py` (present)
- `scripts/sodex_order_surface_audit.py` (present)
- `scripts/sodex_reconciliation_audit.py` (present)
- `scripts/sodex_safety_guardian.py` (present)
- `scripts/system_watchdog.py` (present)
- `scripts/watchdog_twin.sh` (present)

### `services`

- `anantara/systemd/sodex-deep-learner.service` (present)
- `systemd/hl-watchdog.service` (present)
- `systemd/hl-watchdog.timer` (present)
- `systemd/sodex-84h-supervisor.service` (present)
- `systemd/sodex-capital-report.service` (present)
- `systemd/sodex-capital-report.timer` (present)
- `systemd/sodex-guardian.service` (present)
- `systemd/sodex-market-ticker-scanner.service` (present)
- `systemd/sodex-monitor-eval.service` (present)
- `systemd/sodex-monitor-eval.timer` (present)
- `systemd/sodex-sentinel.service` (present)
- `systemd/sodex-twin-watchdog.service` (present)

### `tests`

- `tests/test_measure.py` (present)
- `tests/test_perps_volume_engine.py` (present)
- `tests/test_perps_volume_engine_maker.py` (present)
- `tests/test_sodex_84h_supervisor.py` (present)
- `tests/test_sodex_autonomous_guardian.py` (present)
- `tests/test_sodex_deadman_switch.py` (present)
- `tests/test_sodex_deep_learner.py` (present)
- `tests/test_sodex_e1_autopilot.py` (present)
- `tests/test_sodex_e1_recovery_gate.py` (present)
- `tests/test_sodex_e2dir_amplifier.py` (present)
- `tests/test_sodex_event_barbell.py` (present)
- `tests/test_sodex_event_runway.py` (present)
- `tests/test_sodex_funding_collector.py` (present)
- `tests/test_sodex_guardian_daemon.py` (present)
- `tests/test_sodex_live_short_accelerator.py` (present)
- `tests/test_sodex_market_ticker_scanner.py` (present)
- `tests/test_sodex_micro_pilot.py` (present)
- `tests/test_sodex_mode_audit.py` (present)
- `tests/test_sodex_monitor_eval.py` (present)
- `tests/test_sodex_order_surface_audit.py` (present)
- `tests/test_sodex_project_structure.py` (present)
- `tests/test_sodex_quant_stat_engine.py` (present)
- `tests/test_sodex_radical_gate.py` (present)
- `tests/test_sodex_reconciliation_audit.py` (present)
- `tests/test_sodex_refresh_intel_snapshot.py` (present)
- `tests/test_sodex_safety_guardian.py` (present)
- `tests/test_sodex_scalp_microstructure.py` (present)
- `tests/test_sodex_spot_farming.py` (present)
- `tests/test_sodex_spot_sell_recovery.py` (present)
- `tests/test_sodex_system_map.py` (present)
- `tests/test_sodex_ta_probability_gate.py` (present)
- `tests/test_sodex_target_policy.py` (present)
- `tests/test_sodex_telegram_guard.py` (present)
- `tests/test_sodex_twin_engine_e2.py` (present)
- `tests/test_sodex_volume_planner.py` (present)
- `tests/test_sodex_watchdog_policy.py` (present)
- `tests/test_sodex_watchlist_gate_accelerator.py` (present)

## Recommendations

- Keep runtime execution behind safety_halt, quant_stat_decision_engine, policy gates, and operator approval.
- Do not physically move legacy SoDEX files until import/service references are migrated and tested.
- Treat docs/status/reports as historical evidence; use docs/SODEX_SYSTEM_MAP.md and docs/SODEX_PROJECT_STRUCTURE.md as current entry points.
- Use data/sodex_quant_stat/latest.json and data/sodex_system_map/latest.json as current machine-readable control-plane outputs.
