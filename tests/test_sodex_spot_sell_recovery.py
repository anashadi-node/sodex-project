import argparse
import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


class SodexSpotSellRecoveryTests(TestCase):
    def test_status_reports_block_and_flat_account_snapshot(self):
        from scripts import sodex_spot_sell_recovery as rec

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = root / "SODEX_SPOT_SELL_BLOCKED"
            verified = root / "SODEX_SPOT_SELL_VERIFIED"
            monitor = root / "latest.json"
            block.write_text(json.dumps({"reason": "sell blocked"}))
            monitor.write_text(json.dumps({
                "account": {
                    "address": "0x4a464b82b1c1233791351483c90c53e2a2fbc799",
                    "quality": "OK",
                    "account_value": {
                        "total_equity_usd": 538.2,
                        "spot_vusdc_usd": 449.8,
                    },
                    "position_truth": {"open_count": 0, "verified_flat": True},
                    "assets": {
                        "spot": [{
                            "coin": "vPEPE",
                            "symbol": "vPEPE_vUSDC",
                            "total": 1000,
                            "value_usd": 0.25,
                        }],
                    },
                },
            }))

            with patch.object(rec, "BLOCK_FILE", block), \
                 patch.object(rec, "VERIFIED_FILE", verified), \
                 patch.object(rec, "MONITOR_LATEST", monitor):
                status = rec.build_status()

        self.assertEqual(status["status"], "BLOCKED")
        self.assertTrue(status["block_file"]["exists"])
        self.assertTrue(status["account"]["verified_flat"])
        self.assertEqual(status["spot_inventory"][0]["coin"], "vPEPE")
        self.assertIn("...", status["account"]["address_redacted"])
        self.assertEqual(
            status["sell_test_plan"]["action"],
            "NO_EXISTING_INVENTORY_ABOVE_MIN_NOTIONAL",
        )

    def test_status_identifies_existing_sell_candidate_above_min_notional(self):
        from scripts import sodex_spot_sell_recovery as rec

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            monitor = root / "latest.json"
            monitor.write_text(json.dumps({
                "account": {
                    "address": "0x4a464b82b1c1233791351483c90c53e2a2fbc799",
                    "quality": "OK",
                    "account_value": {"total_equity_usd": 50, "spot_vusdc_usd": 50},
                    "position_truth": {"open_count": 0, "verified_flat": True},
                    "assets": {
                        "spot": [
                            {"coin": "vUSDC", "symbol": None, "total": 50, "value_usd": 50},
                            {"coin": "vAVAX", "symbol": "vAVAX_vUSDC", "total": 1, "value_usd": 6.2},
                        ],
                    },
                },
            }))

            with patch.object(rec, "BLOCK_FILE", root / "block"), \
                 patch.object(rec, "VERIFIED_FILE", root / "verified"), \
                 patch.object(rec, "MONITOR_LATEST", monitor):
                status = rec.build_status()

        self.assertEqual(status["sell_test_plan"]["action"], "TEST_EXISTING_INVENTORY_SELL")
        self.assertEqual(status["sell_test_plan"]["sell_test_candidates"][0]["coin"], "vAVAX")

    def test_support_packet_contains_no_secrets_and_is_written(self):
        from scripts import sodex_spot_sell_recovery as rec

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(rec, "BLOCK_FILE", root / "block"), \
                 patch.object(rec, "VERIFIED_FILE", root / "verified"), \
                 patch.object(rec, "MONITOR_LATEST", root / "latest.json"), \
                 patch.object(rec, "SUPPORT_PACKET", root / "support.json"):
                result = rec.write_support_packet()
                packet_text = Path(result["path"]).read_text()

        self.assertEqual(result["status"], "OK")
        self.assertIn("No private key", packet_text)
        self.assertNotIn("SODEX_PRIVATE_KEY", packet_text)

    def test_status_falls_back_to_fresh_snapshot_when_latest_account_bad(self):
        from scripts import sodex_spot_sell_recovery as rec

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            latest = root / "latest.json"
            latest.write_text(json.dumps({"account": {"quality": "MISSING_ADDRESS"}}))
            fresh = {
                "account": {
                    "address": "0x4a464b82b1c1233791351483c90c53e2a2fbc799",
                    "quality": "OK",
                    "account_value": {
                        "total_equity_usd": 538.2,
                        "spot_vusdc_usd": 449.8,
                    },
                    "position_truth": {"open_count": 0, "verified_flat": True},
                    "assets": {"spot": [{"coin": "vAVAX", "symbol": "vAVAX_vUSDC", "total": 1, "value_usd": 6.2}]},
                },
            }

            with patch.object(rec, "BLOCK_FILE", root / "block"), \
                 patch.object(rec, "VERIFIED_FILE", root / "verified"), \
                 patch.object(rec, "MONITOR_LATEST", latest), \
                 patch.object(rec, "_fresh_monitor_snapshot", return_value=fresh):
                status = rec.build_status()

        self.assertEqual(status["account"]["total_equity_usd"], 538.2)
        self.assertEqual(status["sell_test_plan"]["action"], "TEST_EXISTING_INVENTORY_SELL")

    def test_mark_verified_requires_evidence_fields(self):
        from scripts import sodex_spot_sell_recovery as rec

        with tempfile.TemporaryDirectory() as tmp:
            verified = Path(tmp) / "verified.json"
            args = argparse.Namespace(
                pair="PEPE/USDC",
                qty="1000",
                received_usdc="0.0025",
                evidence="screenshot:/tmp/sell-ok.png",
                note="tiny manual UI SELL succeeded",
            )

            with patch.object(rec, "VERIFIED_FILE", verified):
                result = rec.mark_verified(args)
                data = json.loads(verified.read_text())

        self.assertEqual(result["status"], "OK")
        self.assertEqual(data["pair"], "PEPE/USDC")
        self.assertEqual(data["source"], "manual_ui_sell_evidence")
