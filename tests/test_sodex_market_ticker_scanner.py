from unittest import TestCase


class SodexMarketTickerScannerTests(TestCase):
    def test_normalize_marks_zero_book_and_computes_spread(self):
        from scripts import sodex_market_ticker_scanner as scanner

        item = scanner.normalize(
            {
                "symbol": "ABC-USD",
                "bidPx": "1.00",
                "askPx": "1.01",
                "lastPx": "1.005",
                "quoteVolume": "100000",
                "changePct": "-2.5",
                "fundingRate": "0.0001",
            },
            "perps",
        )

        assert item is not None
        self.assertEqual(item["symbol"], "ABC-USD")
        self.assertFalse(item["zero_book"])
        self.assertAlmostEqual(item["spread_bps"], 99.50248756)

        zero = scanner.normalize({"symbol": "ZERO-USD", "bidPx": "0", "askPx": "0", "lastPx": "1"}, "perps")
        assert zero is not None
        self.assertTrue(zero["zero_book"])

    def test_rank_prefers_liquid_losers_for_short_watch(self):
        from scripts import sodex_market_ticker_scanner as scanner

        items = [
            {"market": "perps", "symbol": "A-USD", "quote_volume_usd": 200000, "change_pct": -3.0, "spread_bps": 5.0, "zero_book": False},
            {"market": "perps", "symbol": "B-USD", "quote_volume_usd": 200000, "change_pct": 2.0, "spread_bps": 5.0, "zero_book": False},
            {"market": "perps", "symbol": "WIDE-USD", "quote_volume_usd": 200000, "change_pct": -5.0, "spread_bps": 30.0, "zero_book": False},
            {"market": "spot", "symbol": "SPOT/USDC", "quote_volume_usd": 300000, "change_pct": -4.0, "spread_bps": 2.0, "zero_book": False},
        ]

        ranked = scanner.rank(items)

        self.assertEqual(ranked["short_watch"][0]["symbol"], "A-USD")
        self.assertNotIn("WIDE-USD", [item["symbol"] for item in ranked["short_watch"]])
        self.assertNotIn("SPOT/USDC", [item["symbol"] for item in ranked["short_watch"]])
