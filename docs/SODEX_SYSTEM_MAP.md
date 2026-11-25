# SoDEX Farming System Map

Generated UTC: `2026-07-16T14:22:06.213319+00:00`

Mode: `READ_ONLY_SODEX_SYSTEM_MAP`

Policy: `no orders, no cancels, no leverage change, no credential change, no service restart`

Summary status: `degraded`

## Canonical Flow

1. `data_collectors`
2. `market_scan`
3. `technical_probability_gate`
4. `quant_stat_decision_engine`
5. `autonomous_research`
6. `monitor_eval`
7. `deep_learning_loop`
8. `policy_and_gates`
9. `execution_guard`
10. `supervisor_reporting`
11. `operator_approval`
12. `micro_pilot_or_engine`
13. `experience_log_back_to_learning`

## Account Snapshot

- `total_equity_usd`: `369.6409358264666`
- `spot_equity_usd`: `223.49952025423931`
- `perps_account_value_usd`: `146.1414155722273`
- `open_perps_positions`: `0`

## Blockers

- `micro_pilot_negative_edge_cooldown`

## Subsystems

| Subsystem | Status | Role | Evidence | Next Action |
|---|---:|---|---|---|
| `data_collectors` | `ok` | Raw OBI, spot/perps observation, and pre-gain monitor inputs for all downstream decisions. | freqtrade_user_data/data/sodex/obi/obi_*.jsonl=fresh age_min=0.08; data/pregain_monitor_state.json=fresh age_min=21.64 | Keep collectors fresh; stale OBI invalidates short-term microstructure decisions. |
| `market_scan` | `ok` | Realtime read-only SoDEX ticker scan, liquidity ranking, movers, zero-book detection. | data/sodex_market_scan/latest.json=fresh age_min=0.12 | Use short_watch only as candidate input; require policy and microstructure gates before live exposure. |
| `technical_probability_gate` | `ok` | Seven-signal TA and quantitative probability layer before any live micro-scalp entry. | scripts/sodex_ta_probability_gate.py=fresh age_min=47.95; scripts/e2_signal_scanner.py=fresh age_min=10809.84; data/e2_signal_latest.jsonl=fresh age_min=5860.78; data/sodex_market_scan/history.jsonl=fresh age_min=0.12 | Require probability >=0.80 and ratio-budget adverse-loss pass before any live short probe. |
| `quant_stat_decision_engine` | `ok` | Read-only SoDEX quantitative statistical fusion layer: TA probability, calibration, fill probability, costs, and ratio budget. | scripts/sodex_quant_stat_engine.py=fresh age_min=18.78; data/sodex_quant_stat/latest.json=fresh age_min=3.47; data/sodex_quant_stat/history.jsonl=fresh age_min=3.47 | Run the quant-stat engine before any volume increase; treat calibration gaps as WAIT, not permission to trade. |
| `monitor_eval` | `ok` | Account truth, PnL/ledger, halt status, position truth, and risk summary. | data/sodex_monitor_eval/latest.json=fresh age_min=1.8 | Keep this as canonical account truth before approving any execution lane. |
| `deep_learning_loop` | `ok` | Awareness + Experience + Learning parameter loop for spreads, confidence, and regime memory. | data/sodex_learned_params.json=fresh age_min=0.56; data/sodex_deep_learning.jsonl=fresh age_min=1.56 | Continue validating learned params with out-of-sample gates before live promotion. |
| `autonomous_research` | `ok` | External/local research loop, candidate discovery, and adaptive policy evidence. | data/sodex/research/autonomous_status.json=fresh age_min=0.87 | Treat research as advisory; require monitor_eval and execution guard agreement before live use. |
| `policy_and_gates` | `ok` | Scientific go/no-go layer: target policy, mode audit, event barbell, E2Dir amplifier, and fee/spread scanner. | scripts/sodex_target_policy.py=fresh age_min=109.03; scripts/sodex_mode_audit.py=fresh age_min=30475.95; scripts/sodex_event_barbell.py=fresh age_min=30431.71; scripts/sodex_e2dir_amplifier.py=fresh age_min=106.32; scripts/sodex_scalp_microstructure.py=fresh age_min=108.56 | Promote only when realized edge, win-rate, fee ratio, and official reconciliation all pass. |
| `micro_pilot` | `cooldown` | Small controlled live/perps pilot lane for short-only experiments under loss budget. | data/sodex_micro_pilot.jsonl=fresh age_min=58.65 | Keep live paused when net edge is negative; use paper/e2dir scans until edge recovers. |
| `execution_guard` | `ok` | Code surface audit for order-capable modules and guardrail discipline. | scripts/sodex_order_surface_audit.py=fresh age_min=11686.48 | Review inactive guardian/deadman units before increasing notional or autonomy. |
| `supervisor_reporting` | `ok` | Mission supervisor, capital reporting, and integrated status documents for operator decisions. | data/sodex/mission_supervisor/latest.json=fresh age_min=10.89; data/sodex_system_map/latest.json=fresh age_min=3.29; data/sodex_project_structure/latest.json=fresh age_min=3.6; docs/SODEX_PROJECT_STRUCTURE.md=fresh age_min=3.6 | Refresh supervisor/reporting artifacts before any long autonomous run. |
| `telegram_alerting` | `ok` | Operator alerts and capital reports. | data/telegram_health.json=stale age_min=6155.87 | Rotate TELEGRAM_BOT_TOKEN if verdict remains unauthorized; do not log the token value. |

## Data Dependencies

### data_collectors
- Upstream: `SoDEX public/orderbook endpoints`, `collector services`
- Downstream: `market_scan`, `pregain`, `microstructure_scan`, `deep_learning_loop`
- Services: `anantara-obi.service`=unknown_bus_denied, `anantara-spot.service`=unknown_bus_denied
- Findings: obi_files=56; obi_newest=freqtrade_user_data/data/sodex/obi/obi_20260716.jsonl

### market_scan
- Upstream: `bin/sodex tickers spot`, `bin/sodex tickers perps`
- Downstream: `technical_probability_gate`, `candidate_scoring`, `micro_pilot`, `operator_review`
- Services: `sodex-market-ticker-scanner.service`=unknown_bus_denied
- Findings: markets_seen=112 perps=82 spot=30 zero_book=6

### technical_probability_gate
- Upstream: `market_scan history`, `E2 signal scanner`, `SoDEX ticker/orderbook snapshots`
- Downstream: `quant_stat_decision_engine`, `policy_and_gates`, `live_short_accelerator`, `micro_pilot`
- Findings: e2_signal_scanner exists but is Binance-limited and advisory; sodex_ta_probability_gate converts local SoDEX scanner history into seven-signal probability evidence

### quant_stat_decision_engine
- Upstream: `technical_probability_gate`, `market_scan`, `monitor_eval`, `micro_pilot experience log`
- Downstream: `policy_and_gates`, `operator_approval`, `micro_pilot`
- Findings: sodex_quant_stat_engine is read-only and emits TRADE_READY/WAIT/BLOCK decisions; live promotion still requires operator approval and existing execution guards

### monitor_eval
- Upstream: `SoDEX account endpoints`, `local ledger`, `position state`
- Downstream: `target_policy`, `event_barbell`, `capital_report`, `safety_gates`
- Services: `sodex-monitor-eval.timer`=unknown_bus_denied
- Findings: total_equity_usd=369.6409358264666; perps_positions=0 quality=OK; halt_active=True

### deep_learning_loop
- Upstream: `monitor_eval`, `fills`, `market_scan`, `experience log`
- Downstream: `twin_engine`, `scanner_thresholds`, `operator_policy`
- Services: `sodex-deep-learner.service`=unknown_bus_denied
- Findings: regime=NEUTRAL; awareness_experience_learning_present=True

### autonomous_research
- Upstream: `market data`, `local research notebooks`, `Hermes/intel snapshots`
- Downstream: `target_policy`, `e2dir_amplifier`, `mode_audit`
- Services: `sodex-autonomous-research.service`=unknown_bus_denied
- Findings: keys=35

### policy_and_gates
- Upstream: `monitor_eval`, `market_scan`, `technical_probability_gate`, `quant_stat_decision_engine`, `autonomous_research`, `deep_learning_loop`
- Downstream: `execution_guard`, `operator_approval`, `micro_pilot`
- Findings: Current target policy blocks E1/E2 scale and allows only tightly capped micro short lane.

### micro_pilot
- Upstream: `target_policy`, `market_scan`, `technical_probability_gate`, `microstructure_scan`, `monitor_eval`
- Downstream: `experience_log`, `deep_learning_loop`, `event_barbell`
- Findings: live_closed=13 net_delta_usd=-0.34303656 win_rate=0.0

### execution_guard
- Upstream: `order-capable scripts`, `runtime safety templates`
- Downstream: `operator_approval`, `live_readiness`
- Services: `sodex-guardian.service`=unknown_bus_denied, `sodex-safety-guardian.service`=unknown_bus_denied, `sodex-deadman.timer`=unknown_bus_denied
- Findings: Order surface audit script exists; guardian/deadman service states are reported separately.

### supervisor_reporting
- Upstream: `monitor_eval`, `system_map`, `capital_report`
- Downstream: `operator_review`, `telegram_alerting`, `manual_approval`
- Services: `sodex-84h-supervisor.service`=unknown_bus_denied, `sodex-capital-report.timer`=unknown_bus_denied
- Findings: System map is now the primary local operator map; mission supervisor artifact is reported for freshness.

### telegram_alerting
- Upstream: `capital_report`, `monitor_eval`, `telegram credentials`
- Downstream: `operator_response`
- Services: `sodex-capital-report.timer`=unknown_bus_denied
- Findings: verdict=ok; http_status=200
