import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sodex_forward_reeval_loop as loop


class TestSodexForwardReevalLoop(unittest.TestCase):
    def test_funding_archive_fail_closed_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            result = loop.funding_archive_summary(Path(td) / "missing.jsonl")
        self.assertEqual(result["verdict"], "FAIL_CLOSED")
        self.assertEqual(result["n_rows"], 0)

    def test_funding_archive_warmup_before_24h_span(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rates.jsonl"
            rows = [
                {"collected_utc": "2026-10-02T00:00:00+00:00", "symbol": "BTC"},
                {"collected_utc": "2026-10-02T06:00:00+00:00", "symbol": "ETH"},
            ]
            path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            result = loop.funding_archive_summary(path, min_span_hours=24)
        self.assertEqual(result["verdict"], "WARMING_UP")
        self.assertAlmostEqual(result["span_hours"], 6.0)
        self.assertEqual(result["unique_symbols"], 2)

    def test_snapshot_keeps_t1_fail_closed_and_preserves_no_build(self):
        harness = {
            "generated_utc": "2026-10-02T10:00:00+00:00",
            "tracks": [
                {"track": "twoway", "n": 42, "grade": {"passed": False}, "result": {"excess_mean": 0.01}}
            ],
            "canonical_normalized_target_distance": {
                "valid": True,
                "distance_to_target_pct": -10.0,
                "normalized_delta_usd": -0.2,
                "target_48h_usd": 2.0,
            },
            "funding_map": {"verdict": "FAIL_CLOSED", "n_exact": 0, "n_rate_estimated": 0, "n_missing": 42},
            "decision": {"t1_status": "FAIL"},
            "registry_count": 4,
        }
        archive = {"verdict": "READY", "n_rows": 200, "span_hours": 30.0, "unique_symbols": 90}
        snap = loop.build_loop_record(harness, archive, harness_exit_code=0)
        self.assertEqual(snap["verdict"], "T1_FAIL_FORWARD_MONITOR")
        self.assertEqual(snap["safety"]["build_new_strategy_machine_now"], "NO")
        self.assertEqual(snap["safety"]["unfreeze_real_money"], "NO")
        self.assertEqual(snap["funding_map"]["n_missing"], 42)

    def test_append_jsonl_preserves_every_forward_trial(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "loop.jsonl"
            loop.append_jsonl(path, {"run_id": "a"})
            loop.append_jsonl(path, {"run_id": "b"})
            rows = [json.loads(x) for x in path.read_text().splitlines()]
        self.assertEqual([r["run_id"] for r in rows], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
