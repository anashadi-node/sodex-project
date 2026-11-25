from unittest import TestCase


class SodexRefreshIntelSnapshotTests(TestCase):
    def test_build_snapshot_maps_hermes_intel_and_forecasts_to_policy_jsonl_shape(self):
        from scripts import sodex_refresh_intel_snapshot as refresh

        row = refresh.build_snapshot(
            {
                "composite_score": 47.9,
                "label": "NEUTRAL",
                "dominant_signal": "fg_contrarian",
                "explainability": "fg_contrarian(+10.6), flow_tilt(-3.8)",
                "inputs": {"fg_raw": 12, "mcap_change_24h": -2.16, "regime": "RANGING"},
                "components": {"flow_tilt": -3.8, "funding_tilt": -0.5},
            },
            {
                "BTC": {"forecast": {"direction": "DOWN", "confidence": 0.72, "signal_agreement": 0.61}},
                "ETH": {"forecast": {"direction": "NEUTRAL", "confidence": 0.5}},
                "SOL": {"forecast": {"direction": "UP", "confidence": 0.64, "signal_agreement": 0.2}},
            },
            ts=1782388612,
        )

        self.assertEqual(row["ts"], 1782388612)
        self.assertEqual(row["composite_score"], 47.9)
        self.assertEqual(row["event_risk_level"], "RED")
        self.assertGreaterEqual(row["event_risk_score"], 70.0)
        self.assertEqual(row["fc_BTC_dir_enc"], -1)
        self.assertEqual(row["fc_ETH_dir_enc"], 0)
        self.assertEqual(row["fc_SOL_dir_enc"], 1)
        self.assertAlmostEqual(row["fc_BTC_conf"], 0.72)

    def test_degraded_forecast_is_neutralized_for_policy(self):
        from scripts import sodex_refresh_intel_snapshot as refresh

        row = refresh.build_snapshot(
            {"composite_score": 62, "inputs": {}, "components": {}},
            {
                "BTC": {
                    "forecast": {
                        "direction": "DOWN",
                        "confidence": 0.91,
                        "signal_agreement": 0.88,
                        "fallback": True,
                    },
                    "llm_degraded": True,
                    "trade_eligible": False,
                    "quality": "DEGRADED_LLM_FALLBACK",
                }
            },
            ts=1782388612,
        )

        self.assertEqual(row["fc_BTC_dir_enc"], 0)
        self.assertEqual(row["fc_BTC_conf"], 0.0)
        self.assertEqual(row["fc_BTC_agreement"], 0.0)
        self.assertFalse(row["fc_BTC_eligible"])
