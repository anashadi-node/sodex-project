import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


class SodexE1RecoveryGateTests(TestCase):
    def _patch_paths(self, gate, root: Path):
        return (
            patch.object(gate, "SELL_BLOCK", root / "SODEX_SPOT_SELL_BLOCKED"),
            patch.object(gate, "SELL_VERIFIED", root / "SODEX_SPOT_SELL_VERIFIED"),
            patch.object(gate, "SAFETY_HALT", root / "SAFETY_HALT"),
            patch.object(gate, "PNL_HALT", root / "PNL_HALT"),
            patch.object(gate, "OPERATOR_CARD", root / "operator.md"),
            patch.object(gate, "ARCHIVE_DIR", root / "archive"),
        )

    def test_status_phase_zero_when_no_sellable_inventory(self):
        from scripts import sodex_e1_recovery_gate as gate

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            patches = self._patch_paths(gate, root)
            for p in patches:
                p.start()
                self.addCleanup(p.stop)
            gate.SELL_BLOCK.write_text(json.dumps({"reason": "sell blocked"}))
            with patch.object(gate, "_sell_status", return_value={
                "sell_test_plan": {
                    "action": "NO_EXISTING_INVENTORY_ABOVE_MIN_NOTIONAL",
                    "reason": "dust",
                },
            }), patch.object(gate, "_e1_readiness", return_value={
                "ready_for_live": False,
                "blockers": ["SPOT_SELL_CAPABILITY_BLOCKED"],
            }):
                status = gate.build_status()

        self.assertEqual(status["phase"], "PHASE_0_NEEDS_SELL_TEST_INVENTORY")

    def test_clear_sell_block_requires_verified_file(self):
        from scripts import sodex_e1_recovery_gate as gate

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            patches = self._patch_paths(gate, root)
            for p in patches:
                p.start()
                self.addCleanup(p.stop)
            gate.SELL_BLOCK.write_text("{}")
            result = gate.clear_sell_block(confirm=True)

        self.assertEqual(result["status"], "ERROR")
        self.assertIn("SODEX_SPOT_SELL_VERIFIED", result["reason"])

    def test_clear_sell_block_archives_when_verified_exists(self):
        from scripts import sodex_e1_recovery_gate as gate

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            patches = self._patch_paths(gate, root)
            for p in patches:
                p.start()
                self.addCleanup(p.stop)
            gate.SELL_BLOCK.write_text(json.dumps({"reason": "old"}))
            gate.SELL_VERIFIED.write_text(json.dumps({"pair": "AVAX/USDC"}))
            result = gate.clear_sell_block(confirm=True)
            archived_exists = Path(result["archived_to"]).exists()

        self.assertEqual(result["status"], "OK")
        self.assertFalse(gate.SELL_BLOCK.exists())
        self.assertTrue(archived_exists)

    def test_operator_card_is_written(self):
        from scripts import sodex_e1_recovery_gate as gate

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            patches = self._patch_paths(gate, root)
            for p in patches:
                p.start()
                self.addCleanup(p.stop)
            with patch.object(gate, "build_status", return_value={
                "ts": "2026-07-08T00:00:00+00:00",
                "event_deadline": "2026-07-25",
                "phase": "PHASE_0_NEEDS_SELL_TEST_INVENTORY",
                "next_action": "Do UI test",
                "sell_test_plan": {
                    "estimated_min_sell_notional_usd": 5.0,
                    "action": "NO_EXISTING_INVENTORY_ABOVE_MIN_NOTIONAL",
                    "reason": "dust",
                    "operator_steps": ["Create inventory", "Sell it"],
                },
            }):
                result = gate.write_operator_card()
                text = Path(result["path"]).read_text()

        self.assertEqual(result["status"], "OK")
        self.assertIn("Current phase: PHASE_0_NEEDS_SELL_TEST_INVENTORY", text)
