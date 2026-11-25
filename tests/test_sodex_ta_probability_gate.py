from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import TestCase


class SodexTaProbabilityGateTests(TestCase):
    def _bearish_candles(self, n: int = 60):
        from scripts.sodex_ta_probability_gate import Candle

        start = datetime.now(timezone.utc) - timedelta(minutes=n - 1)
        candles = []
        for i in range(n):
            price = 100.0 - (i * 0.03)
            candles.append(Candle(
                ts=start + timedelta(minutes=i),
                open=price + 0.005,
                high=price + 0.006,
                low=price - 0.006,
                close=price - 0.005,
                volume_usd=1000 + i,
                bid=price - 0.002,
                ask=price + 0.002,
                change_pct=-3.0,
                funding_rate=0.00001,
            ))
        return candles

    def test_bearish_clean_candles_pass_short_probability_gate(self):
        from scripts.sodex_ta_probability_gate import evaluate_candles

        result = evaluate_candles(
            "TEST-USD",
            self._bearish_candles(),
            side="sell",
            notional_usd=Decimal("10"),
            min_ratio=Decimal("5100"),
        )

        self.assertTrue(result["passes"])
        self.assertEqual(result["direction"], "SHORT")
        self.assertGreaterEqual(result["probability"], 0.80)
        self.assertEqual(result["coverage"], 1.0)
        self.assertEqual(len(result["signals"]), 7)

    def test_insufficient_candles_block_gate(self):
        from scripts.sodex_ta_probability_gate import evaluate_candles

        result = evaluate_candles("TEST-USD", self._bearish_candles(10), side="sell")

        self.assertFalse(result["passes"])
        self.assertIn("ta_data_insufficient_min_30_candles", result["reasons"])
