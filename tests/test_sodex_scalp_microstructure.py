from unittest import TestCase


class SodexScalpMicrostructureTests(TestCase):
    def test_ratio_budget_is_roundtrip_loss_bps(self):
        from scripts import sodex_scalp_microstructure as scalp

        expected_ratio = 7000.0  # post-emergency base ratio
        self.assertAlmostEqual(float(scalp.ratio_budget_loss_bps()), 2 / expected_ratio * 10000)

    def test_taker_fails_but_maker_can_be_candidate_when_spread_covers_fee(self):
        from scripts import sodex_scalp_microstructure as scalp

        rows = scalp.build_rows(
            [{
                "name": "XPL-USD",
                "status": "TRADING",
                "makerFee": "0.00012",
                "takerFee": "0.0004",
            }],
            [{
                "symbol": "XPL-USD",
                "bidPx": "0.0910",
                "askPx": "0.0911",
                "quoteVolume": "138000",
                "changePct": "-12",
                "fundingRate": "0.0000125",
            }],
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertFalse(row.taker_ratio_pass)
        self.assertTrue(row.maker_ratio_pass_before_adverse)
        self.assertEqual(row.scalp_lane, "MAKER_ONLY_CANDIDATE")
        self.assertGreater(row.taker_roundtrip_loss_bps, row.ratio_budget_loss_bps)
