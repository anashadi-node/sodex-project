import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sodex_recovery_monitor.py"
spec = importlib.util.spec_from_file_location("sodex_recovery_monitor", MODULE_PATH)
assert spec is not None and spec.loader is not None
mon: Any = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mon)


class RecoveryMonitorTests(unittest.TestCase):
    def make_project(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "data").mkdir()
        (root / "reports").mkdir()
        return tmp, root

    def write_state(self, root, name, closed, open_obj=None):
        state = {"closed": closed, "open": open_obj or {}}
        (root / "data" / name).write_text(json.dumps(state))

    def test_metrics_uses_wallet_target_not_position_target(self):
        trades = [{"pnl_usd": 1.0}, {"pnl_usd": 0.5}, {"pnl_usd": -0.5}]
        got = mon.metrics(trades, wallet=100.0)
        self.assertEqual(got["n"], 3)
        self.assertEqual(got["hit_target_count"], 1)
        self.assertFalse(got["target_met"])
        self.assertAlmostEqual(got["avg_wallet_roi_pct"], 0.3333, places=4)

    def test_parse_time_accepts_iso_seconds_and_ms(self):
        iso = "2026-09-15T00:00:00+00:00"
        ts = mon.parse_time(iso)
        self.assertEqual(mon.parse_time(str(int(ts))), ts)
        self.assertEqual(mon.parse_time(int(ts * 1000)), ts)

    def test_chop_gate_violation_detects_signal_forward_long_only(self):
        tmp, root = self.make_project()
        self.addCleanup(tmp.cleanup)
        cutoff = mon.parse_time("2026-09-15T00:00:00+00:00")
        self.write_state(root, "paper_test_realwide_state.json", [
            {"side": "LONG", "regime": "CHOP", "track": "SIGNAL", "entry_ts": cutoff + 10, "sym": "BTC"},
            {"side": "SHORT", "regime": "CHOP", "track": "SIGNAL", "entry_ts": cutoff + 20, "sym": "ETH"},
            {"side": "LONG", "regime": "CHOP", "track": "SIGNAL", "entry_ts": cutoff - 10, "sym": "SOL"},
            # negative-control arm: never gated by design -> not a violation
            {"side": "LONG", "regime": "CHOP", "track": "RANDOM", "entry_ts": cutoff + 30, "sym": "LINK"},
            # BTC data error: documented fail-open (regime None) -> not a violation
            {"side": "LONG", "regime": None, "track": "SIGNAL", "entry_ts": cutoff + 40, "sym": "UNI"},
            # legacy row predating the track field: unattributable -> not a violation
            {"side": "LONG", "regime": "CHOP", "entry_ts": cutoff + 50, "sym": "AVAX"},
        ])
        self.write_state(root, "paper_test_twoway_state.json", [])
        got = mon.chop_gate_violations([], root, cutoff)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["track"], "REALWIDE")
        self.assertEqual(got[0]["regime"], "CHOP")
        self.assertEqual(got[0]["pair"], "BTC")

    def test_shortbear_variant_telemetry_counts_last_24h(self):
        tmp, root = self.make_project()
        self.addCleanup(tmp.cleanup)
        variant = "fast_exit_2h"
        self.write_state(root, f"paper_test_shortbear_{variant}_state.json", [], {})
        rows = [
            {"cycle_iso": "2026-09-15T12:00:00+00:00", "decision": "blocked_signal", "native_mark": 100},
            {"cycle_iso": "2026-09-14T00:00:00+00:00", "decision": "entry", "candidate": True},
        ]
        tele = root / "data" / f"paper_test_shortbear_{variant}_telemetry.jsonl"
        tele.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        now_ts = mon.parse_time("2026-09-15T13:00:00+00:00")
        got = mon.shortbear_variants(root, now_ts)[0]
        self.assertEqual(got["variant"], variant)
        self.assertEqual(got["telemetry_24h"], 1)
        self.assertEqual(got["native_mark_rows_24h"], 1)
        self.assertEqual(got["decisions_24h"], {"blocked_signal": 1})

    def test_build_payload_is_normal_when_controls_clean(self):
        tmp, root = self.make_project()
        self.addCleanup(tmp.cleanup)
        for _, fname in mon.TRACKS:
            self.write_state(root, fname, [])
        (root / "data" / "REALWIDE_LIVE_KILL").write_text("1")
        (root / "data" / "SPOT_LIVE_KILL").write_text("1")
        old_read_wallet = mon.read_wallet
        try:
            mon.read_wallet = lambda project: (158.66, "test", None)
            payload = mon.build_payload(root, cutoff="2026-09-15T00:00:00+00:00")
        finally:
            mon.read_wallet = old_read_wallet
        self.assertEqual(payload["verdict"], "NORMAL")
        self.assertEqual(payload["target_usd"], round(158.66 * 0.008, 6))

    def test_build_payload_uses_user_deadline_16_oct_wib(self):
        tmp, root = self.make_project()
        self.addCleanup(tmp.cleanup)
        for _, fname in mon.TRACKS:
            self.write_state(root, fname, [])
        (root / "data" / "REALWIDE_LIVE_KILL").write_text("1")
        (root / "data" / "SPOT_LIVE_KILL").write_text("1")
        old_read_wallet = mon.read_wallet
        try:
            mon.read_wallet = lambda project: (158.66, "test", None)
            payload = mon.build_payload(root, cutoff="2026-09-15T00:00:00+00:00")
        finally:
            mon.read_wallet = old_read_wallet
        self.assertEqual(payload["deadline_utc"], "2026-10-16T16:59:59+00:00")

    def test_build_payload_treats_archived_kill_switches_as_live_resume(self):
        tmp, root = self.make_project()
        self.addCleanup(tmp.cleanup)
        for _, fname in mon.TRACKS:
            self.write_state(root, fname, [])
        (root / "data" / "sodex_go_live_resume_20260920T150726Z.json").write_text(
            json.dumps({"decision": "SODEX_MICRO_LIVE_RESUME_APPROVED_BY_USER"})
        )
        old_read_wallet = mon.read_wallet
        try:
            mon.read_wallet = lambda project: (158.66, "test", None)
            payload = mon.build_payload(root, cutoff="2026-09-15T00:00:00+00:00")
        finally:
            mon.read_wallet = old_read_wallet
        self.assertTrue(payload["live_resume_approved"])
        self.assertEqual(payload["verdict"], "NORMAL")
        self.assertNotIn("live kill switch missing", payload["issues"])


    # ── perilaku baru 2026-10-06: exit code, riwayat, notifikasi ──

    def fake_payload(self, verdict="ALERT", issues=None, violations=None):
        return {
            "verdict": verdict,
            "issues": issues if issues is not None else ["CHOP gate violations: 1"],
            "wallet": {"value": 158.66, "source": "test", "note": None},
            "target_usd": 1.26928,
            "services": {"anantara-paper-realwide.service": True},
            "chop_gate_violations": violations if violations is not None else [
                {"track": "REALWIDE", "pair": "BTC", "entry": "2026-10-05T06:00:00+00:00", "regime": "CHOP"}],
            "generated_utc": "2026-10-06T00:15:32+00:00",
        }

    def test_main_exits_zero_on_finding_and_strict_exits_one(self):
        """Temuan TIDAK boleh membuat systemd melihat unit gagal; --strict mengembalikan perilaku lama."""
        payload = self.fake_payload()
        old_build, old_write, old_hist = mon.build_payload, mon.write_outputs, mon.append_history
        try:
            mon.build_payload = lambda *a, **k: payload
            mon.write_outputs = lambda *a, **k: (Path("/dev/null"), Path("/dev/null"))
            mon.append_history = lambda *a, **k: Path("/dev/null")
            self.assertEqual(mon.main(["--no-notify"]), 0)                 # temuan -> tetap 0
            self.assertEqual(mon.main(["--strict", "--no-notify"]), 1)     # opt-in perilaku lama
        finally:
            mon.build_payload, mon.write_outputs, mon.append_history = old_build, old_write, old_hist

    def test_main_exits_one_only_when_monitor_itself_crashes(self):
        old_build = mon.build_payload
        try:
            def boom(*a, **k):
                raise RuntimeError("sengaja")
            mon.build_payload = boom
            self.assertEqual(mon.main(["--no-notify"]), 1)                 # crash -> 1
        finally:
            mon.build_payload = old_build

    def test_append_history_persists_violation_details(self):
        """Riwayat harus menyimpan RINCIAN pelanggaran (berkas state dipangkas -> bukti bisa hilang)."""
        tmp, root = self.make_project()
        self.addCleanup(tmp.cleanup)
        payload = self.fake_payload()
        hist = mon.append_history(payload, project=root)
        self.assertTrue(hist.exists())
        rec = json.loads(hist.read_text().strip().splitlines()[-1])
        self.assertEqual(rec["verdict"], "ALERT")
        self.assertEqual(rec["violation_count"], 1)
        self.assertEqual(rec["violations"][0]["pair"], "BTC")
        snaps = list((root / "reports" / "sodex" / "recovery_violations").glob("violations_*.json"))
        self.assertEqual(len(snaps), 1)
        # baris kedua ditambahkan, bukan menimpa
        mon.append_history(payload, project=root)
        self.assertEqual(len(hist.read_text().strip().splitlines()), 2)

    def test_should_notify_dedupes_then_reminds_after_12h(self):
        tmp, root = self.make_project()
        self.addCleanup(tmp.cleanup)
        payload = self.fake_payload()
        t0 = 1_800_000_000.0
        self.assertTrue(mon.should_notify(payload, project=root, now_ts=t0))    # temuan baru
        mon.mark_notified(payload, project=root, now_ts=t0)
        self.assertFalse(mon.should_notify(payload, project=root, now_ts=t0 + 3600))   # sama -> diam
        self.assertTrue(mon.should_notify(payload, project=root, now_ts=t0 + 13 * 3600))  # >12j -> ingatkan
        clean = self.fake_payload(verdict="NORMAL", issues=[])
        self.assertFalse(mon.should_notify(clean, project=root, now_ts=t0))     # tanpa temuan -> tidak pernah


if __name__ == "__main__":
    unittest.main()
