"""Tests for SoDEX IntelLayer macro policy integration."""
import unittest
from unittest import mock

from anantara import sodex_intel_layer as sil


class TestSodexIntelLayerMacroPolicy(unittest.TestCase):
    def setUp(self):
        self.intel = sil.IntelLayer()
        self.fg = {"value": 50, "label": "Neutral", "ts": 1}

    def test_pre_event_policy_reduces_capital_and_raises_spread(self):
        policy = {"level": "YELLOW", "sodex_capital_mult": 0.75,
                  "sodex_spread_add_pct": 0.04, "active_event_window": False,
                  "reason": "macro pre-event"}
        with mock.patch.object(sil, "fetch_fear_greed", return_value=self.fg), \
             mock.patch.object(sil.IntelLayer, "get_macro_policy", return_value=policy):
            self.intel._last_regime = None
            self.assertAlmostEqual(self.intel.get_capital_mult(), 0.75)
            self.assertAlmostEqual(self.intel.get_spread_min(), 0.34)

    def test_active_macro_window_breaks_circuit(self):
        policy = {"level": "ORANGE", "sodex_capital_mult": 0.5,
                  "sodex_spread_add_pct": 0.08, "active_event_window": True,
                  "reason": "macro release window active: FOMC"}
        with mock.patch.object(sil.IntelLayer, "get_macro_policy", return_value=policy):
            ok, reason = self.intel.circuit_breaker_ok()
        self.assertFalse(ok)
        self.assertIn("macro release", reason)


if __name__ == "__main__":
    unittest.main()
