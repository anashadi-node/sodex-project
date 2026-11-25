import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


class SodexSystemMapTests(TestCase):
    def test_artifact_status_detects_missing_and_stale(self):
        from scripts import sodex_system_map as system_map

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            existing = root / "fresh.json"
            existing.write_text("{}", encoding="utf-8")

            with patch.object(system_map, "PROJECT", root):
                self.assertEqual(system_map.artifact("fresh.json", 999)["status"], "fresh")
                self.assertEqual(system_map.artifact("missing.json")["status"], "missing")

    def test_bus_denied_service_does_not_make_fresh_artifacts_inactive(self):
        from scripts import sodex_system_map as system_map

        status = system_map.status_from_services(
            {"svc": "unknown_bus_denied"},
            [{"status": "fresh"}],
        )

        self.assertEqual(status, "ok")

    def test_markdown_contains_flow_and_subsystems(self):
        from scripts import sodex_system_map as system_map

        report = {
            "ts": "2026-07-12T00:00:00+00:00",
            "mode": "READ_ONLY_SODEX_SYSTEM_MAP",
            "policy": "no orders",
            "summary_status": "degraded",
            "blockers": ["telegram_alerting_degraded"],
            "canonical_flow": ["market_scan", "monitor_eval"],
            "account_snapshot": {"total_equity_usd": 410.0},
            "subsystems": [{
                "name": "market_scan",
                "status": "ok",
                "role": "scan",
                "artifacts": [{"path": "data/x.json", "status": "fresh", "age_min": 1}],
                "next_actions": ["continue"],
                "upstream": ["bin/sodex"],
                "downstream": ["policy"],
                "services": {"svc": "active"},
                "findings": ["seen=1"],
            }],
        }

        markdown = system_map.build_markdown(report)

        self.assertIn("# SoDEX Farming System Map", markdown)
        self.assertIn("`market_scan`", markdown)
        self.assertIn("telegram_alerting_degraded", markdown)

    def test_canonical_flow_contains_quant_stat_probability_gate(self):
        from scripts import sodex_system_map as system_map

        with patch.object(system_map, "read_json", return_value={}), \
             patch.object(system_map, "service_state", return_value="active"), \
             patch.object(system_map, "artifact", return_value={
                 "path": "x",
                 "exists": True,
                 "age_min": 0,
                 "status": "fresh",
                 "stale_after_min": None,
             }), \
             patch.object(system_map, "glob_artifact", return_value={
                 "path": "x",
                 "exists": True,
                 "age_min": 0,
                 "status": "fresh",
                 "stale_after_min": None,
                 "count": 1,
             }), \
             patch.object(system_map, "micro_edge_summary", return_value={
                 "live_closed": 0,
                 "net_delta_usd": 0.0,
                 "wins": 0,
                 "losses": 0,
                 "win_rate": None,
             }):
            report = system_map.build_report()

        self.assertIn("technical_probability_gate", report["canonical_flow"])
        self.assertIn("quant_stat_decision_engine", report["canonical_flow"])
        names = {sub["name"] for sub in report["subsystems"]}
        self.assertIn("technical_probability_gate", names)
        self.assertIn("quant_stat_decision_engine", names)
