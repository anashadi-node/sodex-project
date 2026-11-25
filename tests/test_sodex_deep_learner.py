"""Tests for anantara/sodex_deep_learner.py — Loop Deep Learning Ability."""
from __future__ import annotations
import json
import math
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from unittest import mock


# ── import under test ──────────────────────────────────────────────────────────
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from anantara import sodex_deep_learner as DL


# ──────────────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────────────

def _fake_db(path: Path, n_fills: int = 30, n_rts: int = 10) -> None:
    """Create a minimal twin_engine.db with synthetic fills + RTs."""
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE fills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, engine TEXT, bucket TEXT,
            pair TEXT, side TEXT, price TEXT, qty TEXT,
            notional TEXT, fee TEXT, maker INTEGER, rt_id TEXT
        )""")
    conn.execute("""
        CREATE TABLE rts (
            rt_id TEXT PRIMARY KEY,
            ts_close TEXT, engine TEXT, pair TEXT,
            volume TEXT, net_pnl TEXT
        )""")
    now = datetime.now(timezone.utc)
    for i in range(n_fills):
        hour = (i % 24)
        ts = (now - timedelta(hours=i * 0.5)).isoformat()
        side = "buy" if i % 2 == 0 else "sell"
        pair = "PEPE/USDC" if i % 3 != 0 else "SHIB/USDC"
        conn.execute(
            "INSERT INTO fills (ts, engine, bucket, pair, side, price, qty, "
            "notional, fee, maker) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ts, "E1", "S", pair, side, "0.000003", "1000000",
             "3.0", "0.001", 1)
        )
    for i in range(n_rts):
        ts = (now - timedelta(hours=i * 1.0)).isoformat()
        net = 0.0005 if i % 3 != 0 else -0.0002
        conn.execute(
            "INSERT INTO rts (rt_id, ts_close, engine, pair, volume, net_pnl) "
            "VALUES (?,?,?,?,?,?)",
            (f"E1-PEPE-{i}", ts, "E1", "PEPE/USDC", "6.0", str(net))
        )
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# FillAnalyzer tests
# ──────────────────────────────────────────────────────────────────────────────

class TestFillAnalyzer(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "twin_engine.db"
        _fake_db(self.db, n_fills=40, n_rts=12)

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_incremental_returns_counts(self):
        analyzer = DL.FillAnalyzer(self.db)
        fills, rts = analyzer.load_incremental()
        self.assertGreater(fills, 0)
        self.assertGreater(rts, 0)

    def test_load_incremental_fills_are_tracked(self):
        """Fills/RTs are incremental — second call does not double-count."""
        analyzer = DL.FillAnalyzer(self.db)
        f1, r1 = analyzer.load_incremental()
        f2, r2 = analyzer.load_incremental()
        self.assertEqual(f2, 0, "No new fills in DB → second call returns 0 fills")
        self.assertEqual(r2, 0, "No new RTs in DB → second call returns 0 RTs")
        self.assertGreater(r1, 0, "First call must load some RTs")

    def test_stats_keyed_by_pair_bucket(self):
        analyzer = DL.FillAnalyzer(self.db)
        analyzer.load_incremental()
        keys = set(analyzer.stats.keys())
        # at least PEPE/USDC should appear
        pepe_keys = [k for k in keys if k[0] == "PEPE/USDC"]
        self.assertGreater(len(pepe_keys), 0)

    def test_fill_rate_positive_after_rts(self):
        analyzer = DL.FillAnalyzer(self.db)
        analyzer.load_incremental()
        # find any key with rts > 0
        for (pair, bucket), s in analyzer.stats.items():
            if s["rts"] > 0:
                fr = analyzer.fill_rate(pair, bucket)
                self.assertGreater(fr, 0.0)
                return
        # if no RTs found (unlikely with fake_db), skip
        self.skipTest("No RTs in test DB")

    def test_net_rate_nan_when_insufficient_rts(self):
        analyzer = DL.FillAnalyzer(self.db)
        analyzer.load_incremental()
        # a bucket with 0 rts should return nan
        nr = analyzer.net_rate("NONEXISTENT/USDC", "h00_05")
        self.assertTrue(math.isnan(nr))

    def test_summary_nonempty(self):
        analyzer = DL.FillAnalyzer(self.db)
        analyzer.load_incremental()
        s = analyzer.summary()
        self.assertIsInstance(s, dict)
        self.assertGreater(len(s), 0)

    def test_missing_db_returns_zeros(self):
        analyzer = DL.FillAnalyzer(Path("/nonexistent/path.db"))
        fills, rts = analyzer.load_incremental()
        self.assertEqual(fills, 0)
        self.assertEqual(rts, 0)


# ──────────────────────────────────────────────────────────────────────────────
# SpreadBandit tests
# ──────────────────────────────────────────────────────────────────────────────

class TestSpreadBandit(unittest.TestCase):

    def test_select_returns_valid_arm(self):
        bandit = DL.SpreadBandit()
        arm = bandit.select("PEPE/USDC", "h12_17")
        self.assertIn(arm, DL._SPREAD_LADDER)

    def test_update_does_not_crash(self):
        bandit = DL.SpreadBandit()
        for _ in range(20):
            bandit.update("PEPE/USDC", "h12_17", 0.0012, 0.0003)

    def test_best_spread_bounded_by_base(self):
        bandit = DL.SpreadBandit()
        base = 0.0012
        # populate with enough updates so exploitation kicks in
        for _ in range(30):
            bandit.update("PEPE/USDC", "h12_17", 0.0010, 0.0005)
            bandit.update("PEPE/USDC", "h12_17", 0.0030, -0.0010)
        best = bandit.best_spread("PEPE/USDC", "h12_17", base)
        lo = base * DL._MIN_SPREAD_MULT
        hi = base * DL._MAX_SPREAD_MULT
        self.assertGreaterEqual(best, lo)
        self.assertLessEqual(best, hi)

    def test_best_spread_falls_back_to_base_without_data(self):
        bandit = DL.SpreadBandit()
        base = 0.0015
        best = bandit.best_spread("SHIB/USDC", "h00_05", base)
        # no data → stays at base
        self.assertAlmostEqual(best, base, places=6)

    def test_reward_clipped_on_extreme_net_rate(self):
        bandit = DL.SpreadBandit()
        # extreme positive reward should be clipped to 0.002
        bandit.update("PEPE/USDC", "h06_11", 0.0015, 999.0)
        i = min(range(len(bandit.arms)),
                key=lambda j: abs(bandit.arms[j] - 0.0015))
        mu = bandit._mu["PEPE/USDC|h06_11"][i]
        self.assertLessEqual(mu, 0.002)

    def test_state_returns_dict(self):
        bandit = DL.SpreadBandit()
        bandit.update("PEPE/USDC", "h00_05", 0.0010, 0.0002)
        state = bandit.state()
        self.assertIsInstance(state, dict)
        self.assertIn("PEPE/USDC|h00_05", state)


# ──────────────────────────────────────────────────────────────────────────────
# FillProbModel tests
# ──────────────────────────────────────────────────────────────────────────────

class TestFillProbModel(unittest.TestCase):

    def test_predict_before_training_returns_half(self):
        m = DL.FillProbModel()
        p = m.predict_proba(0.0015, 12, "NEUTRAL", 0.5)
        self.assertAlmostEqual(p, 0.5, places=6)

    def test_learn_one_increments_count(self):
        m = DL.FillProbModel()
        if not m._river_ok:
            self.skipTest("River not available")
        for i in range(60):
            m.learn_one(0.0015, 12, "NEUTRAL", 0.5, i % 2 == 0)
        self.assertEqual(m.trained_count, 60)

    def test_predict_proba_in_range_after_training(self):
        m = DL.FillProbModel()
        if not m._river_ok:
            self.skipTest("River not available")
        for i in range(60):
            m.learn_one(0.0015, i % 24, "NEUTRAL", 0.3, i % 3 != 0)
        p = m.predict_proba(0.0015, 12, "NEUTRAL", 0.3)
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)

    def test_learn_one_no_crash_without_river(self):
        m = DL.FillProbModel()
        m._river_ok = False  # simulate missing River
        m.learn_one(0.0015, 12, "NEUTRAL", 0.5, True)  # must not crash
        self.assertEqual(m.trained_count, 0)


# ──────────────────────────────────────────────────────────────────────────────
# RegimeEnricher tests
# ──────────────────────────────────────────────────────────────────────────────

class TestRegimeEnricher(unittest.TestCase):

    def test_force_regime_env_respected(self):
        enricher = DL.RegimeEnricher()
        with mock.patch.dict(os.environ, {"TE_E1_FORCE_REGIME": "BEAR"}):
            regime = enricher._compute()
        self.assertEqual(regime, "BEAR")

    def test_returns_neutral_on_coingecko_failure(self):
        enricher = DL.RegimeEnricher()
        # make CoinGecko fail
        with mock.patch.object(enricher, "_get_btc_momentum", return_value=None), \
             mock.patch.object(enricher, "_read_intel_regime", return_value="NEUTRAL"):
            regime = enricher._compute()
        self.assertEqual(regime, "NEUTRAL")

    def test_bull_on_positive_momentum(self):
        enricher = DL.RegimeEnricher()
        with mock.patch.object(enricher, "_get_btc_momentum",
                               return_value={"price": 65000, "change_24h": 3.0, "change_1h": 1.5}), \
             mock.patch.object(enricher, "_read_intel_regime", return_value="BULL"):
            regime = enricher._compute()
        self.assertEqual(regime, "BULL")

    def test_bear_on_negative_momentum(self):
        enricher = DL.RegimeEnricher()
        with mock.patch.object(enricher, "_get_btc_momentum",
                               return_value={"price": 55000, "change_24h": -5.0, "change_1h": -2.0}), \
             mock.patch.object(enricher, "_read_intel_regime", return_value="BEAR"):
            regime = enricher._compute()
        self.assertEqual(regime, "BEAR")

    def test_accuracy_none_before_10_samples(self):
        enricher = DL.RegimeEnricher()
        for _ in range(5):
            enricher.log_accuracy("BULL", "BULL")
        self.assertIsNone(enricher.accuracy())

    def test_accuracy_computed_after_10_samples(self):
        enricher = DL.RegimeEnricher()
        for _ in range(10):
            enricher.log_accuracy("BULL", "BULL")
        acc = enricher.accuracy()
        self.assertIsNotNone(acc)
        self.assertAlmostEqual(acc, 1.0, places=6)

    def test_accuracy_log_capped_at_200(self):
        enricher = DL.RegimeEnricher()
        for _ in range(250):
            enricher.log_accuracy("NEUTRAL", "NEUTRAL")
        self.assertLessEqual(len(enricher._accuracy_log), 200)


# ──────────────────────────────────────────────────────────────────────────────
# CrossSystemExperienceMiner tests
# ──────────────────────────────────────────────────────────────────────────────

class TestCrossSystemExperienceMiner(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.external = self.root / "external"
        self.external.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_collects_lessons_from_external_files(self):
        source = self.external / "operator_note.md"
        source.write_text(
            "Lesson: PEPE spread too tight during drawdown regime.\n"
            "Experience: reduce risk when PNL turns negative.\n"
        )
        miner = DL.CrossSystemExperienceMiner(sources=[], external_dir=self.external)
        payload = miner.collect()
        self.assertEqual(payload["dimension"], "cross_system_experience")
        self.assertGreaterEqual(payload["lessons_count"], 1)
        self.assertEqual(payload["quality"], "OK")

    def test_secret_lines_are_not_exported(self):
        source = self.external / "bad_note.md"
        source.write_text(
            "TELEGRAM_BOT_TOKEN=123:secret\n"
            "Lesson: risk control must react to drawdown.\n"
            "SODEX_PRIVATE_KEY=0xabcdef\n"
        )
        miner = DL.CrossSystemExperienceMiner(sources=[], external_dir=self.external)
        payload = miner.collect()
        text = json.dumps(payload)
        self.assertIn("risk control", text)
        self.assertNotIn("TELEGRAM_BOT_TOKEN", text)
        self.assertNotIn("SODEX_PRIVATE_KEY", text)
        self.assertNotIn("123:secret", text)


# ──────────────────────────────────────────────────────────────────────────────
# ParamWriter tests
# ──────────────────────────────────────────────────────────────────────────────

class TestParamWriter(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig_learned = DL.LEARNED_PARAMS
        DL.LEARNED_PARAMS = Path(self.tmp.name) / "sodex_learned_params.json"

    def tearDown(self):
        DL.LEARNED_PARAMS = self.orig_learned
        DL.reset_learned_cache()
        self.tmp.cleanup()

    def _make_components(self):
        db_path = Path(self.tmp.name) / "twin_engine.db"
        _fake_db(db_path, n_fills=60, n_rts=25)
        analyzer = DL.FillAnalyzer(db_path)
        analyzer.load_incremental()
        bandit = DL.SpreadBandit()
        for i in range(30):
            bandit.update("PEPE/USDC", "h12_17", 0.0012, 0.0003)
        model = DL.FillProbModel()
        enricher = DL.RegimeEnricher()
        return analyzer, bandit, model, enricher

    def test_write_creates_valid_json(self):
        analyzer, bandit, model, enricher = self._make_components()
        writer = DL.ParamWriter()
        payload = writer.write(bandit, model, analyzer, enricher,
                               {"PEPE/USDC": 0.0010, "SHIB/USDC": 0.0015}, {})
        self.assertTrue(DL.LEARNED_PARAMS.exists())
        data = json.loads(DL.LEARNED_PARAMS.read_text())
        self.assertIn("pairs", data)
        self.assertIn("ts", data)
        self.assertEqual(data["version"], 2)
        self.assertEqual(data["capability"], "awareness_experience_learning")
        self.assertIn("awareness", data)
        self.assertIn("experience", data)
        self.assertIn("cross_system_experience", data)
        self.assertIn("learning", data)

    def test_awareness_experience_learning_payload_shape(self):
        analyzer, bandit, model, enricher = self._make_components()
        writer = DL.ParamWriter()
        payload = writer.write(
            bandit, model, analyzer, enricher, {"PEPE/USDC": 0.0010}, {}
        )
        self.assertEqual(payload["awareness"]["dimension"], "awareness")
        self.assertEqual(payload["experience"]["dimension"], "experience")
        self.assertEqual(payload["cross_system_experience"]["dimension"], "cross_system_experience")
        self.assertEqual(payload["learning"]["dimension"], "learning")
        self.assertIn("PEPE/USDC", payload["learning"]["recommendations"])
        self.assertGreater(payload["experience"]["unique_rt_ids_seen"], 0)

    def test_write_spread_within_bounds(self):
        analyzer, bandit, model, enricher = self._make_components()
        # populate bandit with data to drive adaptation
        for _ in range(30):
            bandit.update("PEPE/USDC", "h12_17", 0.0008, 0.0005)
        writer = DL.ParamWriter()
        base = 0.0010
        payload = writer.write(bandit, model, analyzer, enricher,
                               {"PEPE/USDC": base, "SHIB/USDC": 0.0015}, {})
        learned = payload["pairs"]["PEPE/USDC"]["min_spread"]
        self.assertGreaterEqual(learned, base * DL._MIN_SPREAD_MULT)
        self.assertLessEqual(learned, base * DL._MAX_SPREAD_MULT)

    def test_write_low_confidence_uses_base(self):
        """With < MIN_FILLS_ADAPT fills, confidence is low → use base spread."""
        db_path = Path(self.tmp.name) / "twin_engine2.db"
        _fake_db(db_path, n_fills=5, n_rts=2)  # very few fills
        analyzer = DL.FillAnalyzer(db_path)
        analyzer.load_incremental()
        bandit = DL.SpreadBandit()
        model = DL.FillProbModel()
        enricher = DL.RegimeEnricher()
        writer = DL.ParamWriter()
        base = 0.0010
        payload = writer.write(bandit, model, analyzer, enricher,
                               {"PEPE/USDC": base}, {})
        pepe = payload["pairs"]["PEPE/USDC"]
        self.assertEqual(pepe["confidence"], "low")
        self.assertAlmostEqual(pepe["min_spread"], base, places=6)

    def test_read_current_returns_none_when_missing(self):
        self.assertIsNone(DL.ParamWriter.read_current())

    def test_get_learned_spread_returns_none_when_missing(self):
        result = DL.ParamWriter.get_learned_spread("PEPE/USDC", 0.0010)
        self.assertIsNone(result)


# ──────────────────────────────────────────────────────────────────────────────
# get_learned_min_spread (engine integration) tests
# ──────────────────────────────────────────────────────────────────────────────

class TestGetLearnedMinSpread(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig_learned = DL.LEARNED_PARAMS
        DL.LEARNED_PARAMS = Path(self.tmp.name) / "sodex_learned_params.json"

    def tearDown(self):
        DL.LEARNED_PARAMS = self.orig_learned
        DL.reset_learned_cache()
        self.tmp.cleanup()

    def _write_params(self, pair: str, spread: float, age_s: int = 0) -> None:
        ts = (datetime.now(timezone.utc) -
              timedelta(seconds=age_s)).isoformat()
        data = {
            "ts": ts,
            "version": 1,
            "pairs": {
                pair: {"min_spread": spread, "base_spread": 0.0010,
                       "confidence": "med", "n_fills": 50,
                       "fill_prob": 0.6, "delta_bps": 2.0, "source": "bandit"}
            }
        }
        DL.LEARNED_PARAMS.write_text(json.dumps(data))
        DL.reset_learned_cache()

    def test_returns_learned_value(self):
        self._write_params("PEPE/USDC", 0.0011)
        val = DL.get_learned_min_spread("PEPE/USDC", 0.0010)
        self.assertAlmostEqual(val, 0.0011, places=6)

    def test_returns_env_default_when_file_missing(self):
        val = DL.get_learned_min_spread("PEPE/USDC", 0.0010)
        self.assertAlmostEqual(val, 0.0010, places=6)

    def test_returns_env_default_when_stale(self):
        # write file with ts 120s in the past (> 90s TTL)
        self._write_params("PEPE/USDC", 0.0011, age_s=120)
        val = DL.get_learned_min_spread("PEPE/USDC", 0.0010)
        self.assertAlmostEqual(val, 0.0010, places=6)

    def test_returns_env_default_when_pair_not_in_file(self):
        self._write_params("SHIB/USDC", 0.0016)
        val = DL.get_learned_min_spread("PEPE/USDC", 0.0010)
        self.assertAlmostEqual(val, 0.0010, places=6)

    def test_returns_env_default_when_out_of_bounds_low(self):
        # 0.0003 < 0.0010 × 0.50 = 0.0005 → reject
        self._write_params("PEPE/USDC", 0.0003)
        val = DL.get_learned_min_spread("PEPE/USDC", 0.0010)
        self.assertAlmostEqual(val, 0.0010, places=6)

    def test_returns_env_default_when_out_of_bounds_high(self):
        # 0.025 > 0.0010 × 2.0 = 0.002 → reject
        self._write_params("PEPE/USDC", 0.025)
        val = DL.get_learned_min_spread("PEPE/USDC", 0.0010)
        self.assertAlmostEqual(val, 0.0010, places=6)

    def test_returns_env_default_on_corrupt_json(self):
        DL.LEARNED_PARAMS.write_text("{ invalid json }")
        DL.reset_learned_cache()
        val = DL.get_learned_min_spread("PEPE/USDC", 0.0010)
        self.assertAlmostEqual(val, 0.0010, places=6)


# ──────────────────────────────────────────────────────────────────────────────
# DeepLearnerLoop integration tests
# ──────────────────────────────────────────────────────────────────────────────

class TestDeepLearnerLoop(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "twin_engine.db"
        _fake_db(self.db, n_fills=60, n_rts=20)
        self.orig_learned = DL.LEARNED_PARAMS
        self.orig_log = DL.DEEP_LOG
        DL.LEARNED_PARAMS = Path(self.tmp.name) / "sodex_learned_params.json"
        DL.DEEP_LOG       = Path(self.tmp.name) / "sodex_deep_learning.jsonl"

    def tearDown(self):
        DL.LEARNED_PARAMS = self.orig_learned
        DL.DEEP_LOG       = self.orig_log
        DL.reset_learned_cache()
        self.tmp.cleanup()

    def test_run_once_creates_params_file(self):
        loop = DL.DeepLearnerLoop(
            db_path=self.db,
            base_spreads={"PEPE/USDC": 0.0010, "SHIB/USDC": 0.0015},
        )
        payload = loop.run_once()
        self.assertTrue(DL.LEARNED_PARAMS.exists())
        self.assertIn("pairs", payload)
        self.assertIn("regime", payload)

    def test_run_once_payload_has_correct_pairs(self):
        loop = DL.DeepLearnerLoop(
            db_path=self.db,
            base_spreads={"PEPE/USDC": 0.0010},
        )
        payload = loop.run_once()
        self.assertIn("PEPE/USDC", payload["pairs"])

    def test_run_once_spread_within_bounds(self):
        loop = DL.DeepLearnerLoop(
            db_path=self.db,
            base_spreads={"PEPE/USDC": 0.0010},
        )
        payload = loop.run_once()
        base = 0.0010
        learned = payload["pairs"]["PEPE/USDC"]["min_spread"]
        self.assertGreaterEqual(learned, base * DL._MIN_SPREAD_MULT)
        self.assertLessEqual(learned, base * DL._MAX_SPREAD_MULT)

    def test_multiple_steps_stable(self):
        loop = DL.DeepLearnerLoop(
            db_path=self.db,
            base_spreads={"PEPE/USDC": 0.0010, "SHIB/USDC": 0.0015},
        )
        for _ in range(3):
            payload = loop.run_once()
        # all iterations must produce valid output
        self.assertIn("version", payload)
        self.assertEqual(payload["version"], 2)
        self.assertEqual(payload["experience"]["rts_total_loaded"], 20)

    def test_audit_log_written_after_step(self):
        loop = DL.DeepLearnerLoop(
            db_path=self.db,
            base_spreads={"PEPE/USDC": 0.0010},
        )
        # force log write by resetting timestamp
        loop._last_log_ts = 0.0
        loop.run_once()
        self.assertTrue(DL.DEEP_LOG.exists())

    def test_dead_hour_detector_smoke(self):
        d = DL.DeadHourDetector()
        result = d.get_dead_hours()
        self.assertIsInstance(result, dict)


# ──────────────────────────────────────────────────────────────────────────────
# Utility tests
# ──────────────────────────────────────────────────────────────────────────────

class TestUtilities(unittest.TestCase):

    def test_hour_bucket_boundaries(self):
        self.assertEqual(DL._hour_bucket(0),  "h00_05")
        self.assertEqual(DL._hour_bucket(5),  "h00_05")
        self.assertEqual(DL._hour_bucket(6),  "h06_11")
        self.assertEqual(DL._hour_bucket(11), "h06_11")
        self.assertEqual(DL._hour_bucket(12), "h12_17")
        self.assertEqual(DL._hour_bucket(17), "h12_17")
        self.assertEqual(DL._hour_bucket(18), "h18_23")
        self.assertEqual(DL._hour_bucket(23), "h18_23")

    def test_ts_to_hour_parses_iso(self):
        ts = "2026-07-07T14:30:00+00:00"
        self.assertEqual(DL._ts_to_hour(ts), 14)

    def test_ts_to_hour_handles_garbage(self):
        self.assertEqual(DL._ts_to_hour("not-a-timestamp"), 0)

    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.json"
            DL._atomic_write(path, '{"key": 1}')
            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text())["key"], 1)

    def test_atomic_write_no_tmp_file_left(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.json"
            DL._atomic_write(path, '{"x": 2}')
            tmp_path = path.with_suffix(".tmp")
            self.assertFalse(tmp_path.exists())

    def test_load_base_spreads_uses_env(self):
        with mock.patch.dict(os.environ, {
            "TE_SPOT_PAIR":   "PEPE/USDC",
            "TE_SPOT_PAIR_2": "SHIB/USDC",
            "TE_SPOT_PAIR_3": "",
            "TE_E1_MIN_SPREAD":       "0.0013",
            "TE_E1_PAIR2_MIN_SPREAD": "0.0017",
        }):
            spreads = DL._load_base_spreads()
        self.assertAlmostEqual(spreads["PEPE/USDC"], 0.0013, places=6)
        self.assertAlmostEqual(spreads["SHIB/USDC"], 0.0017, places=6)

    def test_load_base_spreads_no_pair3_when_empty(self):
        with mock.patch.dict(os.environ, {"TE_SPOT_PAIR_3": ""}):
            spreads = DL._load_base_spreads()
        self.assertNotIn("", spreads)

    def test_load_base_spreads_skips_blank_pair2(self):
        with mock.patch.dict(os.environ, {
            "TE_SPOT_PAIR": "PEPE/USDC",
            "TE_SPOT_PAIR_2": "",
            "TE_SPOT_PAIR_3": "",
        }, clear=False):
            spreads = DL._load_base_spreads()
        self.assertIn("PEPE/USDC", spreads)
        self.assertNotIn("", spreads)
        self.assertNotIn("SHIB/USDC", spreads)


# ──────────────────────────────────────────────────────────────────────────────
# Fable5 Scientific Components
# ──────────────────────────────────────────────────────────────────────────────

def _fake_db_with_weekly_points(path: Path, n_rts: int = 20,
                                 with_points: bool = True,
                                 win_rate: float = 0.7) -> None:
    """Extended fake DB with weekly_points table and price in fills."""
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE fills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, engine TEXT, bucket TEXT,
            pair TEXT, side TEXT, price TEXT, qty TEXT,
            notional TEXT, fee TEXT, maker INTEGER, rt_id TEXT
        )""")
    conn.execute("""
        CREATE TABLE rts (
            rt_id TEXT PRIMARY KEY,
            ts_close TEXT, engine TEXT, pair TEXT,
            volume TEXT, net_pnl TEXT
        )""")
    conn.execute("""
        CREATE TABLE weekly_points (
            week_sat TEXT PRIMARY KEY,
            points TEXT, note TEXT
        )""")
    now = datetime.now(timezone.utc)
    base_price = 0.000003
    for i in range(n_rts * 4):
        ts = (now - timedelta(hours=i * 0.25)).isoformat()
        side = "buy" if i % 2 == 0 else "sell"
        price = base_price * (1 + (i % 5 - 2) * 0.01)
        conn.execute(
            "INSERT INTO fills (ts, engine, bucket, pair, side, price, qty, "
            "notional, fee, maker) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ts, "E1", "S", "PEPE/USDC", side, str(price), "1000000",
             str(price * 1000000), "0.001", 1)
        )
    for i in range(n_rts):
        ts = (now - timedelta(hours=i * 1.0)).isoformat()
        net = 0.05 if i / n_rts < win_rate else -0.02
        conn.execute(
            "INSERT INTO rts (rt_id, ts_close, engine, pair, volume, net_pnl) "
            "VALUES (?,?,?,?,?,?)",
            (f"E1-PEPE-{i}", ts, "E1", "PEPE/USDC", "10.0", str(net))
        )
    if with_points:
        conn.execute(
            "INSERT INTO weekly_points (week_sat, points, note) VALUES (?,?,?)",
            ("2026-07-12", "850.5", "measured from dashboard")
        )
    conn.commit()
    conn.close()


class TestSPRTMonitorFable5(unittest.TestCase):
    """Tests for SPRTMonitor — Wald's Sequential Probability Ratio Test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "twin_engine.db"
        _fake_db_with_weekly_points(self.db, n_rts=60, win_rate=0.70)

    def tearDown(self):
        self.tmp.cleanup()

    def test_analyze_returns_ok_status(self):
        sprt = DL.SPRTMonitor()
        result = sprt.analyze(self.db)
        self.assertEqual(result["status"], "ok")

    def test_analyze_returns_pairs_dict(self):
        sprt = DL.SPRTMonitor()
        result = sprt.analyze(self.db)
        self.assertIn("pairs", result)
        self.assertIn("PEPE/USDC", result["pairs"])

    def test_pair_data_fields_present(self):
        sprt = DL.SPRTMonitor()
        result = sprt.analyze(self.db)
        pd = result["pairs"]["PEPE/USDC"]
        for field in ("llr", "n_rts", "wins", "losses", "wr", "status"):
            self.assertIn(field, pd)

    def test_llr_increases_with_high_win_rate(self):
        # 70% WR → consistently positive LLR after enough trades
        sprt = DL.SPRTMonitor()
        result = sprt.analyze(self.db)
        pd = result["pairs"]["PEPE/USDC"]
        self.assertGreater(pd["llr"], 0.0, "High WR should push LLR positive")

    def test_llr_bounded(self):
        sprt = DL.SPRTMonitor()
        result = sprt.analyze(self.db)
        for _, pd in result["pairs"].items():
            self.assertGreaterEqual(pd["llr"], -10.0)
            self.assertLessEqual(pd["llr"], 10.0)

    def test_edge_confirmed_status_at_high_llr(self):
        # With many wins, eventually edge_confirmed (LLR > 2.944)
        sprt = DL.SPRTMonitor()
        result = sprt.analyze(self.db)
        pd = result["pairs"]["PEPE/USDC"]
        # At 70% WR, 60 rts: status should be edge_confirmed or collecting high
        self.assertIn(pd["status"], ("edge_confirmed", ) + tuple(
            f"collecting_{p}pct" for p in range(50, 101)))

    def test_n_pairs_tracked_correct(self):
        sprt = DL.SPRTMonitor()
        result = sprt.analyze(self.db)
        self.assertEqual(result["n_pairs_tracked"], len(result["pairs"]))

    def test_no_db_returns_no_db_status(self):
        sprt = DL.SPRTMonitor()
        result = sprt.analyze(Path("/nonexistent/path.db"))
        self.assertEqual(result["status"], "no_db")

    def test_wr_field_matches_wins_losses(self):
        sprt = DL.SPRTMonitor()
        result = sprt.analyze(self.db)
        pd = result["pairs"]["PEPE/USDC"]
        expected_wr = pd["wins"] / pd["n_rts"] if pd["n_rts"] > 0 else 0.0
        self.assertAlmostEqual(pd["wr"], expected_wr, places=4)


class TestHawkesIntensityEstimatorFable5(unittest.TestCase):
    """Tests for HawkesIntensityEstimator — EWMA activity detector."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "twin_engine.db"
        _fake_db_with_weekly_points(self.db, n_rts=20, win_rate=0.6)

    def tearDown(self):
        self.tmp.cleanup()

    def test_estimate_returns_ok_status(self):
        h = DL.HawkesIntensityEstimator()
        result = h.estimate(self.db)
        self.assertEqual(result["status"], "ok")

    def test_estimate_returns_pair_data(self):
        h = DL.HawkesIntensityEstimator()
        result = h.estimate(self.db)
        self.assertIn("pairs", result)

    def test_intensity_is_non_negative(self):
        h = DL.HawkesIntensityEstimator()
        result = h.estimate(self.db)
        for pair, pd in result["pairs"].items():
            self.assertGreaterEqual(pd["intensity"], 0.0)

    def test_activity_state_is_valid(self):
        h = DL.HawkesIntensityEstimator()
        result = h.estimate(self.db)
        for pair, pd in result["pairs"].items():
            self.assertIn(pd["activity_state"], ("ACTIVE", "IDLE"))

    def test_fields_present(self):
        h = DL.HawkesIntensityEstimator()
        result = h.estimate(self.db)
        for pair, pd in result["pairs"].items():
            for f in ("intensity", "activity_state", "n_fills_15min",
                      "threshold_on", "threshold_off"):
                self.assertIn(f, pd, f"Missing field: {f}")

    def test_no_db_returns_no_db(self):
        h = DL.HawkesIntensityEstimator()
        result = h.estimate(Path("/nonexistent.db"))
        self.assertEqual(result["status"], "no_db")

    def test_tau_present_in_result(self):
        h = DL.HawkesIntensityEstimator()
        result = h.estimate(self.db)
        self.assertIn("tau_s", result)
        self.assertEqual(result["tau_s"], 90.0)

    def test_hysteresis_state_persists(self):
        h = DL.HawkesIntensityEstimator()
        r1 = h.estimate(self.db)
        # Force cache expiry
        h._cache_ts = 0.0
        r2 = h.estimate(self.db)
        # State should not flip erroneously between calls
        for pair in r1.get("pairs", {}):
            if pair in r2.get("pairs", {}):
                self.assertIn(r2["pairs"][pair]["activity_state"], ("ACTIVE", "IDLE"))


class TestMarkoutTrackerFable5(unittest.TestCase):
    """Tests for MarkoutTracker — Glosten-Milgrom edge analysis."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "twin_engine.db"
        _fake_db_with_weekly_points(self.db, n_rts=30, win_rate=0.8)
        self.base_spreads = {"PEPE/USDC": 0.0010}

    def tearDown(self):
        self.tmp.cleanup()

    def test_analyze_returns_ok_status(self):
        m = DL.MarkoutTracker()
        result = m.analyze(self.db, self.base_spreads)
        self.assertEqual(result["status"], "ok")

    def test_pair_data_present(self):
        m = DL.MarkoutTracker()
        result = m.analyze(self.db, self.base_spreads)
        self.assertIn("pairs", result)

    def test_fields_present(self):
        m = DL.MarkoutTracker()
        result = m.analyze(self.db, self.base_spreads)
        for pair, pd in result["pairs"].items():
            for f in ("n_rts", "avg_volume", "net_edge_pct",
                      "adverse_pct", "gm_gate_ok", "regime"):
                self.assertIn(f, pd)

    def test_gm_gate_ok_is_bool(self):
        m = DL.MarkoutTracker()
        result = m.analyze(self.db, self.base_spreads)
        for pair, pd in result["pairs"].items():
            self.assertIsInstance(pd["gm_gate_ok"], bool)

    def test_n_rts_positive(self):
        m = DL.MarkoutTracker()
        result = m.analyze(self.db, self.base_spreads)
        for pair, pd in result["pairs"].items():
            self.assertGreater(pd["n_rts"], 0)

    def test_interpretation_present(self):
        m = DL.MarkoutTracker()
        result = m.analyze(self.db, self.base_spreads)
        self.assertIn("interpretation", result)

    def test_no_db_returns_no_db(self):
        m = DL.MarkoutTracker()
        result = m.analyze(Path("/no.db"), self.base_spreads)
        self.assertEqual(result["status"], "no_db")

    def test_high_winrate_positive_net_edge(self):
        # 80% WR with positive net_pnl should yield positive net_edge
        m = DL.MarkoutTracker()
        result = m.analyze(self.db, self.base_spreads)
        if "PEPE/USDC" in result["pairs"]:
            pd = result["pairs"]["PEPE/USDC"]
            # With 80% WR (net=0.05 each win, -0.02 each loss):
            # avg_net_pnl > 0 → net_edge_pct > 0
            self.assertGreater(pd["net_edge_pct"], 0.0)


class TestTullockContestTrackerFable5(unittest.TestCase):
    """Tests for TullockContestTracker — SoPoints competition analysis."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_data_returns_no_data_status(self):
        db = Path(self.tmp.name) / "tw.db"
        _fake_db_with_weekly_points(db, n_rts=5, with_points=False)
        t = DL.TullockContestTracker()
        result = t.analyze(db)
        self.assertEqual(result["status"], "no_data")

    def test_no_data_has_action_hint(self):
        db = Path(self.tmp.name) / "tw.db"
        _fake_db_with_weekly_points(db, n_rts=5, with_points=False)
        t = DL.TullockContestTracker()
        result = t.analyze(db)
        self.assertIn("action", result)

    def test_with_points_returns_ok_status(self):
        db = Path(self.tmp.name) / "tw.db"
        _fake_db_with_weekly_points(db, n_rts=5, with_points=True)
        t = DL.TullockContestTracker()
        result = t.analyze(db)
        self.assertEqual(result["status"], "ok")

    def test_with_points_fields_present(self):
        db = Path(self.tmp.name) / "tw.db"
        _fake_db_with_weekly_points(db, n_rts=5, with_points=True)
        t = DL.TullockContestTracker()
        result = t.analyze(db)
        for f in ("pts_received", "our_share_pct", "n_weeks_tracked", "advice"):
            self.assertIn(f, result)

    def test_our_share_positive(self):
        db = Path(self.tmp.name) / "tw.db"
        _fake_db_with_weekly_points(db, n_rts=5, with_points=True)
        t = DL.TullockContestTracker()
        result = t.analyze(db)
        if result["status"] == "ok":
            self.assertGreater(result["our_share_pct"], 0.0)
            self.assertLessEqual(result["our_share_pct"], 100.0)

    def test_no_db_returns_no_db(self):
        t = DL.TullockContestTracker()
        result = t.analyze(Path("/no.db"))
        self.assertEqual(result["status"], "no_db")


class TestKellyInventoryCapFable5(unittest.TestCase):
    """Tests for KellyInventoryCap — fractional Kelly inventory sizing."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "twin_engine.db"
        _fake_db_with_weekly_points(self.db, n_rts=30, win_rate=0.65)
        self.base_spreads = {"PEPE/USDC": 0.0010}

    def tearDown(self):
        self.tmp.cleanup()

    def test_compute_returns_ok(self):
        k = DL.KellyInventoryCap()
        result = k.compute(self.db, 500.0, self.base_spreads)
        self.assertEqual(result["status"], "ok")

    def test_pairs_data_present(self):
        k = DL.KellyInventoryCap()
        result = k.compute(self.db, 500.0, self.base_spreads)
        self.assertIn("pairs", result)

    def test_cap_usd_is_non_negative(self):
        k = DL.KellyInventoryCap()
        result = k.compute(self.db, 500.0, self.base_spreads)
        for pair, pd in result["pairs"].items():
            if "cap_usd" in pd:
                self.assertGreaterEqual(pd["cap_usd"], 0.0)

    def test_cap_bounded_at_25pct(self):
        k = DL.KellyInventoryCap()
        capital = 400.0
        result = k.compute(self.db, capital, self.base_spreads)
        for pair, pd in result["pairs"].items():
            if "cap_usd" in pd:
                self.assertLessEqual(pd["cap_usd"], capital * 0.25 + 0.01)

    def test_kelly_fraction_is_quarter(self):
        k = DL.KellyInventoryCap()
        self.assertEqual(k._FRACTION, 0.25)

    def test_no_db_returns_no_db(self):
        k = DL.KellyInventoryCap()
        result = k.compute(Path("/no.db"), 100.0, self.base_spreads)
        self.assertEqual(result["status"], "no_db")

    def test_insufficient_data_has_default_cap(self):
        # With only 1-2 RTs, should return insufficient_data but still have cap_usd
        k = DL.KellyInventoryCap()
        db = Path(self.tmp.name) / "small.db"
        _fake_db_with_weekly_points(db, n_rts=2, win_rate=0.5)
        result = k.compute(db, 500.0, self.base_spreads)
        for pair, pd in result["pairs"].items():
            if pd.get("status") == "insufficient_data":
                self.assertIn("cap_usd", pd)

    def test_capital_usd_in_result(self):
        k = DL.KellyInventoryCap()
        result = k.compute(self.db, 350.0, self.base_spreads)
        self.assertEqual(result["capital_usd"], 350.0)


class TestAvellanedaStoikovFable5(unittest.TestCase):
    """Tests for AvellanedaStoikovParams — optimal spread estimation."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "twin_engine.db"
        _fake_db_with_weekly_points(self.db, n_rts=30, win_rate=0.6)
        self.base_spreads = {"PEPE/USDC": 0.0010}

    def tearDown(self):
        self.tmp.cleanup()

    def test_estimate_returns_ok(self):
        a = DL.AvellanedaStoikovParams()
        b = DL.SpreadBandit()
        result = a.estimate(self.db, b, self.base_spreads)
        self.assertEqual(result["status"], "ok")

    def test_formula_in_result(self):
        a = DL.AvellanedaStoikovParams()
        b = DL.SpreadBandit()
        result = a.estimate(self.db, b, self.base_spreads)
        self.assertIn("formula", result)
        self.assertIn("Avellaneda", result["formula"])

    def test_pairs_data_fields(self):
        a = DL.AvellanedaStoikovParams()
        b = DL.SpreadBandit()
        result = a.estimate(self.db, b, self.base_spreads)
        for pair, pd in result.get("pairs", {}).items():
            for f in ("sigma_sq", "kappa", "gamma", "as_total_spread",
                      "as_optimal_spread_clamped", "interpretation"):
                self.assertIn(f, pd)

    def test_sigma_sq_non_negative(self):
        a = DL.AvellanedaStoikovParams()
        b = DL.SpreadBandit()
        result = a.estimate(self.db, b, self.base_spreads)
        for pair, pd in result.get("pairs", {}).items():
            self.assertGreaterEqual(pd["sigma_sq"], 0.0)

    def test_optimal_spread_clamped_within_bounds(self):
        a = DL.AvellanedaStoikovParams()
        b = DL.SpreadBandit()
        result = a.estimate(self.db, b, self.base_spreads)
        for pair, pd in result.get("pairs", {}).items():
            base = self.base_spreads.get(pair, 0.001)
            clamped = pd["as_optimal_spread_clamped"]
            self.assertGreaterEqual(clamped, base * 0.5 - 1e-9)
            self.assertLessEqual(clamped, base * 3.0 + 1e-9)

    def test_gamma_matches_constant(self):
        a = DL.AvellanedaStoikovParams()
        b = DL.SpreadBandit()
        result = a.estimate(self.db, b, self.base_spreads)
        for pair, pd in result.get("pairs", {}).items():
            self.assertEqual(pd["gamma"], 0.1)

    def test_no_db_returns_no_db(self):
        a = DL.AvellanedaStoikovParams()
        b = DL.SpreadBandit()
        result = a.estimate(Path("/no.db"), b, self.base_spreads)
        self.assertEqual(result["status"], "no_db")


class TestDeepLearnerLoopFable5Integration(unittest.TestCase):
    """Integration tests: DeepLearnerLoop runs all Fable5 components together."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "twin_engine.db"
        _fake_db_with_weekly_points(self.db, n_rts=30, win_rate=0.65)
        self.out_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_loop(self):
        with mock.patch.object(DL, "LEARNED_PARAMS", self.out_dir / "lp.json"), \
             mock.patch.object(DL, "DEEP_LOG", self.out_dir / "dl.jsonl"):
            loop = DL.DeepLearnerLoop(
                db_path=self.db,
                base_spreads={"PEPE/USDC": 0.0010}
            )
            return loop

    def test_loop_has_all_fable5_components(self):
        loop = self._make_loop()
        self.assertIsInstance(loop.sprt,     DL.SPRTMonitor)
        self.assertIsInstance(loop.hawkes,   DL.HawkesIntensityEstimator)
        self.assertIsInstance(loop.markout,  DL.MarkoutTracker)
        self.assertIsInstance(loop.tullock,  DL.TullockContestTracker)
        self.assertIsInstance(loop.kelly,    DL.KellyInventoryCap)
        self.assertIsInstance(loop.as_params, DL.AvellanedaStoikovParams)

    def test_step_returns_fable5_keys_in_payload(self):
        with mock.patch.object(DL, "LEARNED_PARAMS", self.out_dir / "lp.json"), \
             mock.patch.object(DL, "DEEP_LOG", self.out_dir / "dl.jsonl"):
            loop = DL.DeepLearnerLoop(db_path=self.db,
                                      base_spreads={"PEPE/USDC": 0.0010})
            payload = loop.step()

        for key in ("sprt", "hawkes", "markout_gm", "tullock_contest",
                    "kelly_sizing", "avellaneda_stoikov"):
            self.assertIn(key, payload, f"Missing Fable5 key: {key}")

    def test_step_merges_sprt_into_pairs(self):
        with mock.patch.object(DL, "LEARNED_PARAMS", self.out_dir / "lp.json"), \
             mock.patch.object(DL, "DEEP_LOG", self.out_dir / "dl.jsonl"):
            loop = DL.DeepLearnerLoop(db_path=self.db,
                                      base_spreads={"PEPE/USDC": 0.0010})
            payload = loop.step()

        for pair, pd in payload["pairs"].items():
            self.assertIn("sprt_status", pd)
            self.assertIn("sprt_llr", pd)
            self.assertIn("sprt_wr", pd)

    def test_step_merges_gm_gate_into_pairs(self):
        with mock.patch.object(DL, "LEARNED_PARAMS", self.out_dir / "lp.json"), \
             mock.patch.object(DL, "DEEP_LOG", self.out_dir / "dl.jsonl"):
            loop = DL.DeepLearnerLoop(db_path=self.db,
                                      base_spreads={"PEPE/USDC": 0.0010})
            payload = loop.step()

        for pair, pd in payload["pairs"].items():
            self.assertIn("gm_edge_ok", pd)
            self.assertIn("net_edge_pct", pd)

    def test_step_merges_hawkes_into_pairs(self):
        with mock.patch.object(DL, "LEARNED_PARAMS", self.out_dir / "lp.json"), \
             mock.patch.object(DL, "DEEP_LOG", self.out_dir / "dl.jsonl"):
            loop = DL.DeepLearnerLoop(db_path=self.db,
                                      base_spreads={"PEPE/USDC": 0.0010})
            payload = loop.step()

        for pair, pd in payload["pairs"].items():
            self.assertIn("activity_state", pd)

    def test_step_merges_kelly_into_pairs(self):
        with mock.patch.object(DL, "LEARNED_PARAMS", self.out_dir / "lp.json"), \
             mock.patch.object(DL, "DEEP_LOG", self.out_dir / "dl.jsonl"):
            loop = DL.DeepLearnerLoop(db_path=self.db,
                                      base_spreads={"PEPE/USDC": 0.0010})
            payload = loop.step()

        for pair, pd in payload["pairs"].items():
            self.assertIn("kelly_cap_usd", pd)

    def test_learned_params_file_written(self):
        lp_path = self.out_dir / "lp.json"
        with mock.patch.object(DL, "LEARNED_PARAMS", lp_path), \
             mock.patch.object(DL, "DEEP_LOG", self.out_dir / "dl.jsonl"):
            loop = DL.DeepLearnerLoop(db_path=self.db,
                                      base_spreads={"PEPE/USDC": 0.0010})
            loop.step()

        self.assertTrue(lp_path.exists(), "Learned params file must be written")
        data = json.loads(lp_path.read_text())
        self.assertIn("sprt", data)
        self.assertIn("hawkes", data)
        self.assertIn("kelly_sizing", data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
