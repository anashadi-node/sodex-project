import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import sodex_adaptive_selector as selector


class AdaptiveSelectorContinuityTests(unittest.TestCase):
    def test_momentum_rejects_direction_when_roc1_has_already_reversed(self):
        rising = [100 + i * 0.2 for i in range(55)]
        rising[-4] = rising[-1] - 2
        rising[-2] = rising[-1] + 0.2
        self.assertEqual(selector.momentum(rising, roc_thr=0.05)["direction"], "neutral")

    def test_recovery_rank_requires_capture_and_quarantines_recent_loser(self):
        farmable = [
            {"symbol": "PUMP-USD", "farmable": True, "net_capture_bps": 7.0,
             "qvol": 100000, "l1_depth": 2000},
            {"symbol": "ENA-USD", "farmable": True, "net_capture_bps": 9.0,
             "qvol": 20000, "l1_depth": 1000},
            {"symbol": "ZEC-USD", "farmable": True, "net_capture_bps": 3.0,
             "qvol": 400000, "l1_depth": 2000},
        ]
        momenta = {
            symbol: {"direction": "long", "strength": 1.0, "roc1h": 0.2}
            for symbol in ("PUMP-USD", "ENA-USD", "ZEC-USD")
        }
        performance = {
            "PUMP-USD": {"n": 6, "net_pnl": -0.07, "last_pnl": -0.01},
            "ENA-USD": {"n": 0, "net_pnl": 0.0, "last_pnl": 0.0},
        }

        with patch.object(selector, "RECOVERY_MIN_NET_CAPTURE_BPS", 5.0):
            ranked = selector.rank(
                farmable, momenta, recovery=True, performance=performance,
            )

        self.assertEqual([row["symbol"] for row in ranked], ["ENA-USD"])

    def test_recent_pair_performance_uses_bounded_latest_round_trips(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "ledger.db"
            import sqlite3
            db = sqlite3.connect(db_path)
            db.execute("CREATE TABLE rts(ts_close TEXT, engine TEXT, pair TEXT, net_pnl TEXT)")
            for idx, pnl in enumerate(("1", "2", "3", "4")):
                db.execute("INSERT INTO rts VALUES(?, 'PVE', 'ENA-USD', ?)",
                           (f"2026-07-20T00:00:0{idx}+00:00", pnl))
            db.commit()
            db.close()
            with patch.object(selector, "LEDGER_DB", db_path):
                perf = selector._recent_pair_performance(limit=3)
        self.assertEqual(
            perf["ENA-USD"], {"n": 3, "net_pnl": 9.0, "last_pnl": 4.0})

    def test_systemd_inline_comments_are_removed_from_strategy_values(self):
        with patch.dict(os.environ, {
            "TE_PVE_MAX_NOTIONAL": "60  # bounded clip",
            "UNRELATED_VALUE": "keep#literal",
        }, clear=False):
            selector._normalize_systemd_environment()
            self.assertEqual(os.environ["TE_PVE_MAX_NOTIONAL"], "60")
            self.assertEqual(os.environ["UNRELATED_VALUE"], "keep#literal")

    def test_source_outage_preserves_last_known_good_without_refreshing_timestamp(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "selection.json"
            previous = {
                "ts": "2026-07-20T00:00:00+00:00",
                "selected": [{"symbol": "SOL-USD", "direction": "long"}],
                "te_pve_pairs": "SOL-USD",
                "directions": {"SOL-USD": "long"},
            }
            out.write_text(json.dumps(previous))
            with patch.object(selector, "OUT_FILE", out), \
                 patch.object(selector, "fetch_tickers", return_value=[]):
                result = selector.select()
            self.assertEqual(result["ts"], previous["ts"])
            self.assertTrue(result["preserved_previous"])
            self.assertEqual(result["quality"], "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD")
            self.assertEqual(json.loads(out.read_text()), previous)

    def test_source_outage_without_previous_writes_degraded_empty_state(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "selection.json"
            with patch.object(selector, "OUT_FILE", out), \
                 patch.object(selector, "fetch_tickers", return_value=[]):
                result = selector.select()
            self.assertEqual(result["quality"], "SOURCE_UNAVAILABLE")
            self.assertFalse(result["preserved_previous"])
            self.assertEqual(result["selected"], [])
            self.assertEqual(json.loads(out.read_text())["quality"], "SOURCE_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
