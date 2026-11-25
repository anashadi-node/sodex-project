#!/usr/bin/env python3
"""Tests for the SoDEX project structure index."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class TestSodexProjectStructure(unittest.TestCase):
    def test_classify_paths_into_canonical_domains(self) -> None:
        from scripts.sodex_project_structure import classify_path

        self.assertEqual(classify_path(Path("scripts/sodex_quant_stat_engine.py"))["domain"], "core_decision")
        self.assertEqual(classify_path(Path("scripts/sodex_project_structure.py"))["domain"], "core_decision")
        self.assertEqual(classify_path(Path("scripts/sodex_safety_guardian.py"))["domain"], "safety")
        self.assertEqual(classify_path(Path("systemd/sodex-monitor-eval.timer"))["domain"], "services")
        self.assertEqual(classify_path(Path("scripts/research/backtest_freqai_sodex.py"))["domain"], "research")
        self.assertEqual(classify_path(Path("docs/SODEX_SYSTEM_MAP.md"))["domain"], "docs")
        self.assertEqual(classify_path(Path("data/sodex_quant_stat/latest.json"))["domain"], "data")
        self.assertEqual(classify_path(Path("tests/test_sodex_quant_stat_engine.py"))["domain"], "tests")

    def test_build_report_includes_required_operational_domains(self) -> None:
        from scripts.sodex_project_structure import build_report

        report = build_report(Path.cwd())
        domains = {item["domain"] for item in report["items"]}

        for required in ("core_decision", "safety", "services", "research", "docs", "data", "tests"):
            self.assertIn(required, domains)
        self.assertEqual(report["mode"], "READ_ONLY_SODEX_PROJECT_STRUCTURE")
        self.assertIn("no moves", report["policy"])
        self.assertFalse(any("__pycache__" in item["path"] for item in report["items"]))
        self.assertFalse(any(item["path"].endswith(".pyc") for item in report["items"]))

    def test_build_markdown_contains_canonical_sections(self) -> None:
        from scripts.sodex_project_structure import build_markdown

        markdown = build_markdown({
            "ts": "2026-07-16T00:00:00+00:00",
            "mode": "READ_ONLY_SODEX_PROJECT_STRUCTURE",
            "policy": "no moves",
            "summary": {"total": 2, "by_domain": {"core_decision": 1, "safety": 1}},
            "canonical_domains": [{"domain": "core_decision", "purpose": "Decision"}],
            "items": [
                {"path": "scripts/sodex_quant_stat_engine.py", "domain": "core_decision", "status": "present"},
                {"path": "scripts/sodex_safety_guardian.py", "domain": "safety", "status": "present"},
            ],
            "recommendations": ["Keep live execution gated."],
        })

        self.assertIn("# SoDEX Project Structure", markdown)
        self.assertIn("core_decision", markdown)
        self.assertIn("scripts/sodex_quant_stat_engine.py", markdown)
        self.assertIn("Keep live execution gated.", markdown)

    def test_persist_writes_latest_and_markdown(self) -> None:
        from scripts.sodex_project_structure import persist_report

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = {
                "ts": "2026-07-16T00:00:00+00:00",
                "mode": "READ_ONLY_SODEX_PROJECT_STRUCTURE",
                "policy": "no moves",
                "summary": {"total": 0, "by_domain": {}},
                "canonical_domains": [],
                "items": [],
                "recommendations": [],
            }
            persist_report(root, report)

            self.assertTrue((root / "data" / "sodex_project_structure" / "latest.json").exists())
            self.assertTrue((root / "docs" / "SODEX_PROJECT_STRUCTURE.md").exists())


if __name__ == "__main__":
    unittest.main()
