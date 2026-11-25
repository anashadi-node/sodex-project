"""Telemetri funnel A/B 9 (paper_test_twoway) — regresi.

Fitur: hitungan per-tahap gate pada siklus entry, DEFAULT OFF (TW_FUNNEL=0),
ditulis atomik ke JSON terpisah per state-file sehingga beberapa arm tidak
saling menimpa. Nol perubahan keputusan trading.
"""
import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "scripts"))

import paper_test_twoway as tw  # noqa: E402

SOURCE = (PROJECT / "scripts" / "paper_test_twoway.py").read_text()

REQUIRED_COUNTERS = [
    "pairs_scanned",
    "skip_both_caps_full",
    "skip_pair_gate",
    "skip_pair_cap",
    "skip_cooldown",
    "skip_random_btc_gate",
    "skip_random_dir_gate",
    "skip_block_long_signal",
    "skip_signal_inactive",
    "skip_no_price",
    "skip_signal_cap",
    "skip_pair_pos_cap",
    "skip_chop_gate",
    "skip_dir_gate",
    "skip_btc_gate",
    "skip_pre24",
    "entry_random",
    "entry_signal",
    "fetch_error",
]


class FunnelDisabledTest(unittest.TestCase):
    def test_disabled_by_default_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "funnel.json"
            old_enabled, old_path, old_counts = tw.FUNNEL_ENABLED, tw.FUNNEL_JSON, dict(tw._FO)
            try:
                tw.FUNNEL_ENABLED = False
                tw.FUNNEL_JSON = target
                tw._f("skip_btc_gate")
                tw.funnel_flush("2026-11-11T00:00:00+00:00")
                self.assertEqual(tw._FO, {})
                self.assertFalse(target.exists(), "funnel harus tidak menulis apa pun saat OFF")
            finally:
                tw.FUNNEL_ENABLED, tw.FUNNEL_JSON = old_enabled, old_path
                tw._FO.clear()
                tw._FO.update(old_counts)


class FunnelEnabledTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.target = Path(self._td.name) / "paper_test_twoway_ab9a_state_funnel.json"
        self._old = (tw.FUNNEL_ENABLED, tw.FUNNEL_JSON, dict(tw._FO))
        tw.FUNNEL_ENABLED = True
        tw.FUNNEL_JSON = self.target
        tw._FO.clear()

    def tearDown(self):
        tw.FUNNEL_ENABLED, tw.FUNNEL_JSON = self._old[0], self._old[1]
        tw._FO.clear()
        tw._FO.update(self._old[2])
        self._td.cleanup()

    def test_writes_cycle_counts_and_accumulates_totals(self):
        tw._f("skip_btc_gate", 3)
        tw._f("pairs_scanned", 23)
        tw.funnel_flush("2026-11-11T00:00:00+00:00", {"open_signal": 0})

        data = json.loads(self.target.read_text())
        self.assertEqual(data["cycle"]["skip_btc_gate"], 3)
        self.assertEqual(data["cycle"]["pairs_scanned"], 23)
        self.assertEqual(data["totals"], {"skip_btc_gate": 3, "pairs_scanned": 23})
        self.assertEqual(data["n_cycles"], 1)
        self.assertEqual(data["timestamp"], "2026-11-11T00:00:00+00:00")
        self.assertEqual(data["since"], "2026-11-11T00:00:00+00:00")
        self.assertEqual(data["context"], {"open_signal": 0})
        self.assertTrue(data["state_file"].endswith(".json"))
        self.assertEqual(tw._FO, {}, "counter siklus harus di-reset setelah flush")

        tw._f("skip_btc_gate")
        tw.funnel_flush("2026-11-11T00:05:00+00:00")
        data2 = json.loads(self.target.read_text())
        self.assertEqual(data2["cycle"], {"skip_btc_gate": 1})
        self.assertEqual(data2["totals"]["skip_btc_gate"], 4)
        self.assertEqual(data2["n_cycles"], 2)
        self.assertEqual(data2["since"], "2026-11-11T00:00:00+00:00")

    def test_flush_is_atomic_and_leaves_no_temp_file(self):
        tw._f("entry_signal", 1)
        tw.funnel_flush("2026-11-11T00:00:00+00:00")
        leftovers = list(self.target.parent.glob("*.tmp"))
        self.assertEqual(leftovers, [])
        self.assertTrue(self.target.exists())

    def test_empty_cycle_does_not_rewrite_existing_file(self):
        tw._f("skip_btc_gate", 2)
        tw.funnel_flush("2026-11-11T00:00:00+00:00")
        before = self.target.read_text()
        tw.funnel_flush("2026-11-11T00:05:00+00:00")
        self.assertEqual(self.target.read_text(), before)


class FunnelCoverageTest(unittest.TestCase):
    def test_every_gate_counter_is_incremented_in_run_cycle(self):
        tree = ast.parse(SOURCE)
        run_cycle = next(n for n in ast.walk(tree)
                         if isinstance(n, ast.FunctionDef) and n.name == "run_cycle")
        keys = set()
        for node in ast.walk(run_cycle):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "_f" and node.args
                    and isinstance(node.args[0], ast.Constant)):
                keys.add(node.args[0].value)
        missing = [k for k in REQUIRED_COUNTERS if k not in keys]
        self.assertEqual(missing, [], f"counter belum dipasang: {missing}")

    def test_funnel_defaults_to_off_when_env_absent(self):
        self.assertEqual(tw.FUNNEL_ENABLED, os.environ.get("TW_FUNNEL", "0") == "1")

    def test_env_enables_funnel_and_derives_per_state_path(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "paper_test_twoway_ab9c_state.json"
            env = dict(os.environ, TW_FUNNEL="1", TW_STATE_FILE=str(state))
            env.pop("TW_FUNNEL_JSON", None)
            code = ("import sys, json; sys.path.insert(0, %r); sys.path.insert(0, %r);"
                    "import paper_test_twoway as tw;"
                    "print(json.dumps({'enabled': tw.FUNNEL_ENABLED,"
                    "'path': str(tw.FUNNEL_JSON), 'state': str(tw.STATE_FILE)}))"
                    % (str(PROJECT), str(PROJECT / "scripts")))
            out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                 text=True, env=env, cwd=str(PROJECT), timeout=180)
            self.assertEqual(out.returncode, 0, out.stderr[-2000:])
            payload = json.loads(out.stdout.strip().splitlines()[-1])
            self.assertTrue(payload["enabled"])
            self.assertEqual(payload["state"], str(state))
            self.assertEqual(Path(payload["path"]).name,
                             "paper_test_twoway_ab9c_state_funnel.json")
            self.assertEqual(Path(payload["path"]).parent, state.parent)


class FunnelLabelTest(unittest.TestCase):
    """Cabang else run_cycle harus membedakan saturasi asli vs sub-siklus exit-only.

    Regresi: sampai 2026-11-15 keduanya dicatat "cycle_caps_full", sehingga arm
    dengan 0 posisi terbuka tetap melaporkan saturasi (rasio palsu ~4:1) dan
    saturasi sungguhan tertutupi di telemetri.
    """

    def _run_cycle_f_calls(self):
        tree = ast.parse(SOURCE)
        run_cycle = next(n for n in ast.walk(tree)
                         if isinstance(n, ast.FunctionDef) and n.name == "run_cycle")
        return [n for n in ast.walk(run_cycle)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_f" and n.args]

    def test_caps_full_counter_is_guarded_by_do_entries(self):
        conds = [c.args[0] for c in self._run_cycle_f_calls()
                 if isinstance(c.args[0], ast.IfExp)]
        self.assertTrue(conds, "penanda cycle_caps_full harus berupa IfExp(do_entries…)")
        pairs = [(c.body.value, c.orelse.value) for c in conds
                 if isinstance(c.body, ast.Constant) and isinstance(c.orelse, ast.Constant)]
        self.assertIn(("cycle_caps_full", "cycle_exit_only"), pairs)

    def test_no_unconditional_caps_full_increment(self):
        bare = [c for c in self._run_cycle_f_calls()
                if isinstance(c.args[0], ast.Constant) and c.args[0].value == "cycle_caps_full"]
        self.assertEqual(bare, [], "cycle_caps_full tidak boleh naik tanpa cek do_entries")


if __name__ == "__main__":
    unittest.main()
