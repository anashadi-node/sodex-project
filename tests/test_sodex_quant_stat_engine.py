#!/usr/bin/env python3
"""Tests for the read-only SoDEX quantitative statistical decision engine."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path


class TestQuantStatMath(unittest.TestCase):
    def test_ratio_budget_uses_roundtrip_volume(self) -> None:
        from scripts.sodex_quant_stat_engine import ratio_budget_usd

        self.assertEqual(ratio_budget_usd(Decimal("12"), Decimal("5100")), Decimal("0.00470588"))

    def test_cost_model_blocks_when_adverse_exceeds_ratio_budget(self) -> None:
        from scripts.sodex_quant_stat_engine import build_cost_model

        model = build_cost_model(
            notional_usd=Decimal("12"),
            min_ratio=Decimal("5100"),
            spread_pct=0.0010,
            atr_pct=0.0040,
            maker_fee_rate=0.000108,
            fill_probability=0.75,
            direction_probability=0.82,
        )

        self.assertGreater(model["expected_adverse_loss_usd"], model["ratio_budget_usd"])
        self.assertFalse(model["ratio_pass"])

    def test_spread_pct_accepts_market_spread_bps(self) -> None:
        from scripts.sodex_quant_stat_engine import _spread_pct

        self.assertAlmostEqual(_spread_pct({"spread_bps": 2.5}, None), 0.00025)


class TestCalibrationAndFill(unittest.TestCase):
    def test_calibration_requires_minimum_empirical_samples(self) -> None:
        from scripts.sodex_quant_stat_engine import build_calibration_summary

        rows = [{"probability": 0.82, "outcome": 1} for _ in range(5)]
        summary = build_calibration_summary(rows, min_samples=30)

        self.assertFalse(summary["passes"])
        self.assertIn("calibration_samples_below_minimum", summary["reasons"])

    def test_calibration_passes_when_brier_beats_baseline(self) -> None:
        from scripts.sodex_quant_stat_engine import build_calibration_summary

        rows = []
        for _ in range(70):
            rows.append({"probability": 0.70, "outcome": 1})
        for _ in range(30):
            rows.append({"probability": 0.70, "outcome": 0})
        summary = build_calibration_summary(rows, min_samples=30)

        self.assertTrue(summary["passes"])
        self.assertLessEqual(summary["brier"], summary["brier_baseline_alwaysbase"])

    def test_fill_probability_rewards_tight_liquid_positive_maker_edge(self) -> None:
        from scripts.sodex_quant_stat_engine import estimate_fill_probability

        strong = estimate_fill_probability({
            "spread_bps": 2.0,
            "quote_volume_usd": 2_000_000,
            "maker_gross_edge_bps": 2.4,
            "scalp_lane": "MAKER_ONLY_CANDIDATE",
        })
        weak = estimate_fill_probability({
            "spread_bps": 90.0,
            "quote_volume_usd": 10_000,
            "maker_gross_edge_bps": -1.0,
            "scalp_lane": "REJECT_TOO_WIDE_ADVERSE_SELECTION",
        })

        self.assertGreater(strong, 0.70)
        self.assertLess(weak, 0.45)


class TestDecisionEngine(unittest.TestCase):
    def _ta_gate(self, probability: float = 0.86, passes: bool = True) -> dict:
        return {
            "symbol": "SOL-USD",
            "side": "sell",
            "direction": "SHORT",
            "probability": probability,
            "short_probability": probability,
            "passes": passes,
            "coverage": 1.0,
            "candles": 80,
            "latest_age_seconds": 30,
            "signals": {name: {"score_short": 0.8} for name in (
                "ema_trend",
                "rsi",
                "macd",
                "bollinger",
                "vwap",
                "atr_realized_vol",
                "orderflow_microstructure",
            )},
            "reasons": [] if passes else ["ta_probability_below_minimum"],
        }

    def test_decision_blocks_when_safety_halt_active(self) -> None:
        from scripts.sodex_quant_stat_engine import build_decision

        decision = build_decision(
            symbol="SOL-USD",
            side="sell",
            ta_gate=self._ta_gate(),
            market_row={"spread_pct": 0.0001, "quote_volume_usd": 2_000_000},
            micro_row={"spread_bps": 1.0, "quote_volume_usd": 2_000_000, "maker_gross_edge_bps": 2.0,
                       "scalp_lane": "MAKER_ONLY_CANDIDATE"},
            calibration={"passes": True, "n": 100, "brier": 0.20, "brier_baseline_alwaysbase": 0.25, "reasons": []},
            notional_usd=Decimal("12"),
            min_ratio=Decimal("5100"),
            safety_halt_active=True,
        )

        self.assertEqual(decision["decision"], "BLOCK")
        self.assertIn("safety_halt_active", decision["blockers"])

    def test_decision_waits_when_calibration_is_not_empirical(self) -> None:
        from scripts.sodex_quant_stat_engine import build_decision

        decision = build_decision(
            symbol="SOL-USD",
            side="sell",
            ta_gate=self._ta_gate(),
            market_row={"spread_pct": 0.0001, "quote_volume_usd": 2_000_000},
            micro_row={"spread_bps": 1.0, "quote_volume_usd": 2_000_000, "maker_gross_edge_bps": 2.0,
                       "scalp_lane": "MAKER_ONLY_CANDIDATE"},
            calibration={"passes": False, "n": 5, "reasons": ["calibration_samples_below_minimum"]},
            notional_usd=Decimal("12"),
            min_ratio=Decimal("5100"),
            safety_halt_active=False,
        )

        self.assertEqual(decision["decision"], "WAIT")
        self.assertIn("calibration_not_passed", decision["blockers"])

    def test_decision_can_be_trade_ready_only_when_all_gates_pass(self) -> None:
        from scripts.sodex_quant_stat_engine import build_decision

        decision = build_decision(
            symbol="SOL-USD",
            side="sell",
            ta_gate=self._ta_gate(0.92),
            market_row={"spread_pct": 0.00002, "quote_volume_usd": 5_000_000},
            micro_row={"spread_bps": 0.2, "quote_volume_usd": 5_000_000, "maker_gross_edge_bps": 3.0,
                       "scalp_lane": "MAKER_ONLY_CANDIDATE"},
            calibration={"passes": True, "n": 240, "brier": 0.18, "brier_baseline_alwaysbase": 0.24, "reasons": []},
            notional_usd=Decimal("12"),
            min_ratio=Decimal("5100"),
            safety_halt_active=False,
        )

        self.assertEqual(decision["decision"], "TRADE_READY")
        self.assertEqual(decision["blockers"], [])
        self.assertGreaterEqual(decision["prob_direction"], 0.80)
        self.assertGreaterEqual(decision["prob_fill_15s"], 0.60)
        self.assertTrue(decision["cost_model"]["ratio_pass"])


class TestPersistence(unittest.TestCase):
    def test_rows_by_symbol_reads_current_scanner_shape(self) -> None:
        from scripts.sodex_quant_stat_engine import _rows_by_symbol

        rows = _rows_by_symbol({
            "items": [{"symbol": "BTC-USD", "quote_volume_usd": 100}],
            "rankings": {
                "short_watch": [{"symbol": "SOL-USD", "quote_volume_usd": 200}],
                "top_losers": [{"symbol": "ETH-USD", "quote_volume_usd": 300}],
            },
        })

        self.assertIn("BTC-USD", rows)
        self.assertIn("SOL-USD", rows)
        self.assertIn("ETH-USD", rows)

    def test_run_engine_writes_latest_and_history_without_order_surface(self) -> None:
        from scripts.sodex_quant_stat_engine import run_engine

        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scan_dir = root / "data" / "sodex_market_scan"
            monitor_dir = root / "data" / "sodex_monitor_eval"
            out_dir = root / "data" / "sodex_quant_stat"
            scan_dir.mkdir(parents=True)
            monitor_dir.mkdir(parents=True)
            (scan_dir / "latest.json").write_text(json.dumps({
                "ts": now.isoformat(),
                "short_watch": [{"symbol": "SOL-USD", "spread_pct": 0.00002, "quote_volume_usd": 5_000_000}],
            }))
            (monitor_dir / "latest.json").write_text(json.dumps({"halt_status": {"active": False}}))
            rows = []
            start = now - timedelta(minutes=79)
            for i in range(80):
                price = 100.0 - i * 0.02
                rows.append(json.dumps({
                    "ts": (start + timedelta(minutes=i)).isoformat(),
                    "short_watch": [{
                        "symbol": "SOL-USD",
                        "mid": price,
                        "bid": price - 0.001,
                        "ask": price + 0.001,
                        "quote_volume_usd": 5_000_000 + i,
                        "change_pct": -3.0,
                        "funding_rate": 0.00001,
                    }],
                }))
            (scan_dir / "history.jsonl").write_text("\n".join(rows))

            report = run_engine(
                project=root,
                output_dir=out_dir,
                symbols=["SOL-USD"],
                notional_usd=Decimal("12"),
                min_ratio=Decimal("5100"),
                persist=True,
                now=now,
                min_calibration_samples=999,
            )

            self.assertEqual(report["mode"], "READ_ONLY_SODEX_QUANT_STAT")
            self.assertTrue((out_dir / "latest.json").exists())
            self.assertTrue((out_dir / "history.jsonl").exists())
            self.assertEqual(report["policy"], "no orders, no cancels, no leverage change, no service restart")
            text = json.dumps(report["decisions"]).lower()
            self.assertNotIn("place_order", text)
            self.assertNotIn("cancel_order", text)
            self.assertNotIn("execstart", text)


if __name__ == "__main__":
    unittest.main()
