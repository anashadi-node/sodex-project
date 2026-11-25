#!/usr/bin/env python3
"""Tests for the read-only SoDEX Quant-Engine calibration harvester.

The harvester turns logged forecasts + public price history into clean
(probability, directional-outcome) rows. These tests lock the outcome
semantics (SHORT correct iff price fell), the price-matching tolerance, the
flat/noise deadband, and the engine's consumption of the resulting store.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class TestPriceIndex(unittest.TestCase):
    def test_price_at_matches_within_tolerance_and_picks_nearest(self) -> None:
        from scripts.sodex_quant_calibration_harvest import price_at

        timeline = ([100.0, 200.0, 300.0], [10.0, 20.0, 30.0])
        # Nearest to 205 is epoch 200 (dist 5) -> price 20.0
        self.assertEqual(price_at(timeline, 205.0, tolerance_sec=60), 20.0)

    def test_price_at_returns_none_when_outside_tolerance(self) -> None:
        from scripts.sodex_quant_calibration_harvest import price_at

        timeline = ([100.0, 500.0], [10.0, 50.0])
        # 300 is 200s from both -> beyond 180s tolerance
        self.assertIsNone(price_at(timeline, 300.0, tolerance_sec=180))

    def test_build_price_index_reads_all_sections(self) -> None:
        from scripts.sodex_quant_calibration_harvest import build_price_index

        base = datetime(2026, 7, 18, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scan.jsonl"
            with path.open("w") as fh:
                fh.write(json.dumps({
                    "ts": _iso(base),
                    "short_watch": [{"symbol": "SOL-USD", "mid": 100.0}],
                    "top_gainers": [{"symbol": "ARB-USD", "bid": 1.0, "ask": 1.02}],
                    "top_losers": [{"symbol": "SOL-USD", "last": 101.0}],
                }) + "\n")
            index = build_price_index(path)
        self.assertIn("SOL-USD", index)
        self.assertIn("ARB-USD", index)
        # ARB uses bid/ask midpoint
        self.assertAlmostEqual(index["ARB-USD"][1][0], 1.01)


class TestOutcomeSemantics(unittest.TestCase):
    def _write_history(self, tmp: str, forecast_prob: float, price_now: float, price_future: float):
        base = datetime(2026, 7, 18, 0, 0, tzinfo=timezone.utc)
        quant = Path(tmp) / "quant.jsonl"
        market = Path(tmp) / "market.jsonl"
        with quant.open("w") as fh:
            fh.write(json.dumps({
                "ts": _iso(base),
                "decisions": [{"symbol": "SOL-USD", "side": "sell", "prob_direction": forecast_prob}],
            }) + "\n")
        with market.open("w") as fh:
            # price at forecast time
            fh.write(json.dumps({"ts": _iso(base), "short_watch": [{"symbol": "SOL-USD", "mid": price_now}]}) + "\n")
            # price at horizon (30m later)
            fh.write(json.dumps({
                "ts": _iso(base + timedelta(minutes=30)),
                "short_watch": [{"symbol": "SOL-USD", "mid": price_future}],
            }) + "\n")
        return quant, market

    def test_short_correct_when_price_falls(self) -> None:
        from scripts.sodex_quant_calibration_harvest import harvest_rows

        with tempfile.TemporaryDirectory() as tmp:
            quant, market = self._write_history(tmp, 0.85, 100.0, 98.0)
            rows = harvest_rows(quant_history=quant, market_history=market, horizon_min=30, deadband_bps=5.0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], 1)  # price fell -> SHORT correct
        self.assertLess(rows[0]["realized_return"], 0)

    def test_short_wrong_when_price_rises(self) -> None:
        from scripts.sodex_quant_calibration_harvest import harvest_rows

        with tempfile.TemporaryDirectory() as tmp:
            quant, market = self._write_history(tmp, 0.85, 100.0, 102.0)
            rows = harvest_rows(quant_history=quant, market_history=market, horizon_min=30, deadband_bps=5.0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], 0)  # price rose -> SHORT wrong

    def test_flat_move_flagged_within_deadband(self) -> None:
        from scripts.sodex_quant_calibration_harvest import harvest_rows

        with tempfile.TemporaryDirectory() as tmp:
            # 2bps move, deadband 5bps -> flat
            quant, market = self._write_history(tmp, 0.85, 100.0, 100.02)
            rows = harvest_rows(quant_history=quant, market_history=market, horizon_min=30, deadband_bps=5.0)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["flat"])

    def test_forecast_dropped_when_future_price_missing(self) -> None:
        from scripts.sodex_quant_calibration_harvest import harvest_rows

        base = datetime(2026, 7, 18, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            quant = Path(tmp) / "quant.jsonl"
            market = Path(tmp) / "market.jsonl"
            with quant.open("w") as fh:
                fh.write(json.dumps({
                    "ts": _iso(base),
                    "decisions": [{"symbol": "SOL-USD", "side": "sell", "prob_direction": 0.85}],
                }) + "\n")
            with market.open("w") as fh:
                # only the "now" price exists; no snapshot near +30m
                fh.write(json.dumps({"ts": _iso(base), "short_watch": [{"symbol": "SOL-USD", "mid": 100.0}]}) + "\n")
            rows = harvest_rows(quant_history=quant, market_history=market, horizon_min=30)
        self.assertEqual(rows, [])


class TestSummaryAndBaseline(unittest.TestCase):
    def test_summary_excludes_flat_rows_and_computes_pooled_brier(self) -> None:
        from scripts.sodex_quant_calibration_harvest import summarize

        rows = [
            {"symbol": "SOL-USD", "probability": 0.9, "outcome": 1, "flat": False},
            {"symbol": "SOL-USD", "probability": 0.9, "outcome": 1, "flat": False},
            {"symbol": "SOL-USD", "probability": 0.5, "outcome": 0, "flat": True},  # excluded
        ]
        summary = summarize(rows, exclude_flat=True)
        self.assertEqual(summary["rows_total"], 3)
        self.assertEqual(summary["rows_used"], 2)
        self.assertEqual(summary["rows_flat_excluded"], 1)
        self.assertEqual(summary["pooled"]["n"], 2)


class TestEngineConsumesOutcomeStore(unittest.TestCase):
    def test_outcome_store_reader_skips_flat_and_reads_directional_outcome(self) -> None:
        from scripts.sodex_quant_stat_engine import calibration_rows_from_outcome_store

        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "cal.jsonl"
            with store.open("w") as fh:
                fh.write(json.dumps({"mode": "live", "closed": True, "symbol": "SOL-USD",
                                     "probability": 0.85, "outcome": 1, "flat": False}) + "\n")
                fh.write(json.dumps({"mode": "live", "closed": True, "symbol": "SOL-USD",
                                     "probability": 0.5, "outcome": 0, "flat": True}) + "\n")
                fh.write(json.dumps({"mode": "backtest", "closed": True, "symbol": "SOL-USD",
                                     "probability": 0.7, "outcome": 1, "flat": False}) + "\n")
            rows = calibration_rows_from_outcome_store(store, symbol="SOL-USD")
        # only the first row qualifies (live, closed, not flat)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], 1)
        self.assertAlmostEqual(rows[0]["probability"], 0.85)

    def test_run_engine_grows_calibration_n_from_outcome_store(self) -> None:
        from scripts.sodex_quant_stat_engine import run_engine

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "data" / "sodex_market_scan").mkdir(parents=True)
            (project / "data" / "sodex_monitor_eval").mkdir(parents=True)
            # minimal market latest so a candidate symbol exists
            (project / "data" / "sodex_market_scan" / "latest.json").write_text(json.dumps({
                "short_watch": [{"symbol": "SOL-USD", "mid": 100.0, "bid": 99.9, "ask": 100.1,
                                 "spread_bps": 2.0, "quote_volume_usd": 500000.0}],
            }))
            (project / "data" / "sodex_market_scan" / "history.jsonl").write_text("")
            (project / "data" / "sodex_monitor_eval" / "latest.json").write_text(json.dumps({}))
            # outcome store with 40 pooled directional samples
            store = project / "data" / "sodex_quant_calibration.jsonl"
            with store.open("w") as fh:
                for i in range(40):
                    fh.write(json.dumps({"mode": "live", "closed": True, "symbol": "SOL-USD",
                                         "probability": 0.8, "outcome": 1 if i % 5 else 0,
                                         "flat": False}) + "\n")
            report = run_engine(project=project, persist=False, min_calibration_samples=30)
        sol = next((d for d in report["decisions"] if d["symbol"] == "SOL-USD"), None)
        self.assertIsNotNone(sol)
        self.assertGreaterEqual(sol["calibration_n"], 30)


class TestIsotonicRecalibrationInEngine(unittest.TestCase):
    def test_recalibrate_returns_none_without_enough_evidence(self) -> None:
        from scripts.sodex_quant_stat_engine import recalibrate_probability

        rows = [{"probability": 0.8, "outcome": 1} for _ in range(5)]
        self.assertIsNone(recalibrate_probability(0.8, rows, min_samples=30))

    def test_recalibrate_debiases_overconfident_prob_toward_empirical(self) -> None:
        from scripts.sodex_quant_stat_engine import recalibrate_probability

        # History: whenever the gate said ~0.85 SHORT, price actually fell only ~20%.
        rows = [{"probability": 0.85, "outcome": 1 if i < 8 else 0} for i in range(40)]
        recal = recalibrate_probability(0.85, rows, min_samples=30)
        self.assertIsNotNone(recal)
        self.assertLess(recal, 0.5)  # de-biased far below the overconfident 0.85

    def test_build_decision_uses_recalibrated_prob_and_reports_raw(self) -> None:
        from scripts.sodex_quant_stat_engine import build_decision
        from decimal import Decimal

        ta_gate = {"probability": 0.9, "passes": True, "signals": {}}
        dec = build_decision(
            symbol="SOL-USD",
            side="sell",
            ta_gate=ta_gate,
            market_row={"quote_volume_usd": 500000.0, "spread_bps": 2.0},
            micro_row={"spread_bps": 2.0, "quote_volume_usd": 500000.0,
                       "scalp_lane": "MAKER_ONLY_CANDIDATE", "maker_gross_edge_bps": 3.0},
            calibration={"passes": True, "brier": 0.2, "n": 40},
            notional_usd=Decimal("12"),
            min_ratio=Decimal("5100"),
            safety_halt_active=False,
            recalibrated_probability=0.30,
        )
        self.assertEqual(dec["prob_direction"], 0.3)          # gate sees recalibrated
        self.assertEqual(dec["prob_direction_raw"], 0.9)      # raw preserved
        self.assertTrue(dec["recalibrated"])
        self.assertIn("direction_probability_below_minimum", dec["blockers"])  # 0.30 < 0.80

    def test_run_engine_applies_recalibration_end_to_end(self) -> None:
        from scripts.sodex_quant_stat_engine import run_engine

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "data" / "sodex_market_scan").mkdir(parents=True)
            (project / "data" / "sodex_monitor_eval").mkdir(parents=True)
            (project / "data" / "sodex_market_scan" / "latest.json").write_text(json.dumps({
                "short_watch": [{"symbol": "SOL-USD", "mid": 100.0, "bid": 99.9, "ask": 100.1,
                                 "spread_bps": 2.0, "quote_volume_usd": 500000.0}],
            }))
            (project / "data" / "sodex_market_scan" / "history.jsonl").write_text("")
            (project / "data" / "sodex_monitor_eval" / "latest.json").write_text(json.dumps({}))
            # anti-correlated store: high stated prob but mostly wrong outcomes
            store = project / "data" / "sodex_quant_calibration.jsonl"
            with store.open("w") as fh:
                for i in range(40):
                    fh.write(json.dumps({"mode": "live", "closed": True, "symbol": "SOL-USD",
                                         "probability": 0.85, "outcome": 1 if i < 8 else 0,
                                         "flat": False}) + "\n")
            report = run_engine(project=project, persist=False, min_calibration_samples=30)
        sol = next((d for d in report["decisions"] if d["symbol"] == "SOL-USD"), None)
        self.assertIsNotNone(sol)
        self.assertTrue(sol["recalibrated"])
        # The anti-correlated store (P=0.85 stated, only 20% fell) makes the isotonic
        # map a constant at the empirical rate, so the engine's used probability is
        # de-biased to ~0.20 regardless of the raw gate value -> no overconfident SHORT.
        self.assertAlmostEqual(sol["prob_direction"], 0.2, places=3)
        self.assertLess(sol["prob_direction"], 0.5)


if __name__ == "__main__":
    unittest.main()
