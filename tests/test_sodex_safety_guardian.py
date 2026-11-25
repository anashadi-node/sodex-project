"""Tests for sodex_safety_guardian — autonomous per-minute position/order protection."""
import importlib.util
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

_SPEC = importlib.util.spec_from_file_location(
    "sodex_safety_guardian",
    str(Path(__file__).resolve().parent.parent / "scripts" / "sodex_safety_guardian.py"),
)
guardian = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(guardian)

# Jangan cemari log/heartbeat/state PRODUKSI saat test — alihkan ke /tmp.
import tempfile as _tf
_TMP = Path(_tf.mkdtemp(prefix="guardian_test_"))
guardian.LOG = _TMP / "safety_guardian.log"
guardian.HEARTBEAT = _TMP / "heartbeat.json"
guardian.ENGINE_ALIVE_TS = _TMP / "engine_last_alive.json"


class _FakeHalt:
    """PosixPath.exists() tidak bisa di-patch (read-only); ganti seluruh HALT_FILE."""
    def __init__(self, exists: bool):
        self._exists = exists
    def exists(self) -> bool:
        return self._exists


class SymbolIdTests(TestCase):
    def test_derives_symbol_id_from_symbol_string(self):
        self.assertEqual(guardian._symbol_id_for("vPEPE_vUSDC"), 5)
        self.assertEqual(guardian._symbol_id_for("vSHIB_vUSDC"), 15)
        self.assertEqual(guardian._symbol_id_for("BTC-USD"), 1)

    def test_zec_perp_symbol_id_present(self):
        # BUG-K fix: ZEC was missing → orphan perp orders couldn't be cancelled
        self.assertEqual(guardian._symbol_id_for("ZEC-USD"), 18)
        self.assertIn("ZEC", guardian.SYMBOL_ID)

    def test_xaut_perp_symbol_id_present(self):
        self.assertEqual(guardian._symbol_id_for("XAUT-USD"), 11)
        self.assertIn("XAUT", guardian.SYMBOL_ID)

    def test_unknown_symbol_returns_none(self):
        self.assertIsNone(guardian._symbol_id_for("vWXYZ_vUSDC"))


class KillSwitchTests(TestCase):
    def test_halt_file_triggers_cancel_all(self):
        orders = [{"_market": "spot", "symbol": "vPEPE_vUSDC", "orderID": "1", "clOrdID": "c1"}]
        with patch.object(guardian, "HALT_FILE", _FakeHalt(True)), \
             patch.object(guardian, "list_open_orders", return_value=orders) as lo, \
             patch.object(guardian, "cancel_order", return_value=True) as co, \
             patch.object(guardian, "write_heartbeat"), \
             patch.object(guardian, "tg_send"):
            guardian.cycle(address="0xabc")
            lo.assert_called()
            co.assert_called_once()


class UnmanagedOrderTests(TestCase):
    def test_engine_dead_long_with_orders_cancels_all(self):
        orders = [{"_market": "spot", "symbol": "vSHIB_vUSDC", "orderID": "9", "clOrdID": "c9"}]
        with patch.object(guardian, "HALT_FILE", _FakeHalt(False)), \
             patch.object(guardian, "list_open_orders", return_value=orders), \
             patch.object(guardian, "engine_dead_secs", return_value=300.0), \
             patch.object(guardian, "cancel_order", return_value=True) as co, \
             patch.object(guardian, "write_heartbeat"), \
             patch.object(guardian, "tg_send"):
            guardian.cycle(address="")
            co.assert_called_once()

    def test_engine_alive_fresh_orders_no_cancel(self):
        orders = [{"_market": "spot", "symbol": "vPEPE_vUSDC", "orderID": "3",
                   "clOrdID": "c3", "ts": guardian.time.time()}]
        with patch.object(guardian, "HALT_FILE", _FakeHalt(False)), \
             patch.object(guardian, "list_open_orders", return_value=orders), \
             patch.object(guardian, "engine_dead_secs", return_value=0.0), \
             patch.object(guardian, "cancel_order", return_value=True) as co, \
             patch.object(guardian, "check_margin"), \
             patch.object(guardian, "write_heartbeat"), \
             patch.object(guardian, "tg_send"):
            guardian.cycle(address="")
            co.assert_not_called()


class StaleOrderTests(TestCase):
    def test_old_order_while_engine_alive_is_cancelled(self):
        old_ts = guardian.time.time() - 1200  # 20 mnt lalu > STALE_SEC(600)
        orders = [{"_market": "spot", "symbol": "vPEPE_vUSDC", "orderID": "7",
                   "clOrdID": "c7", "ts": old_ts}]
        with patch.object(guardian, "HALT_FILE", _FakeHalt(False)), \
             patch.object(guardian, "list_open_orders", return_value=orders), \
             patch.object(guardian, "engine_dead_secs", return_value=0.0), \
             patch.object(guardian, "cancel_order", return_value=True) as co, \
             patch.object(guardian, "check_margin"), \
             patch.object(guardian, "write_heartbeat"), \
             patch.object(guardian, "tg_send"):
            guardian.cycle(address="")
            co.assert_called_once()


class ConfigSanityTests(TestCase):
    def test_normalizes_inline_comments_from_systemd_environment(self):
        with patch.dict(guardian.os.environ, {
            "TE_PVE_MAX_NOTIONAL": "60   # operator note",
            "UNRELATED_SETTING": "value#kept",
        }, clear=False):
            guardian._normalize_systemd_environment()
            self.assertEqual(guardian.os.environ["TE_PVE_MAX_NOTIONAL"], "60")
            self.assertEqual(guardian.os.environ["UNRELATED_SETTING"], "value#kept")

    def test_intervals_are_sane(self):
        self.assertLessEqual(guardian.CHECK_INTERVAL, 60, "harus per-menit atau lebih cepat")
        self.assertGreater(guardian.GRACE_SEC, guardian.CHECK_INTERVAL)
        self.assertGreater(guardian.STALE_SEC, guardian.GRACE_SEC)


class RatioFloorTests(TestCase):
    def test_ratio_breach_never_escalates_tiny_e1_loss_to_global_halt(self):
        now = 1_780_000_000.0
        rows = [
            ("E1", now - 60, 100.0, -0.04),
            ("PVE", now - 60, 7_400.0, -2.0),
        ]
        result = guardian._evaluate_ratio_floor_pure(rows, now, 4_500, 24, 2_000)
        self.assertTrue(result[0])
        self.assertEqual(result[4], "PVE_PAUSE")

    def test_fixed_24h_window_warming_defers_rolling_guard(self):
        now = 1_780_000_000.0
        state = {
            "ts_start": guardian.datetime.fromtimestamp(
                now - 12 * 3600, guardian.timezone.utc
            ).isoformat(),
            "ratio_policy": "fixed_24h_window",
            "window_hours": 24,
        }
        state_file = _TMP / "honest_ratio_experiment.json"
        state_file.write_text(guardian.json.dumps(state))
        with patch.object(guardian, "HONEST_RATIO_STATE", state_file):
            self.assertTrue(guardian._fixed_ratio_window_warming(now))
            self.assertFalse(guardian._fixed_ratio_window_warming(now + 13 * 3600))


class PnlBreakerTests(TestCase):
    """Per-engine cumulative-PnL breaker (anti death-by-thousand-cuts, E2 incident)."""

    def setUp(self):
        # Pin thresholds to defaults so the test is hermetic regardless of env.
        self._saved = {k: getattr(guardian, k) for k in (
            "PNL_WINDOW_H", "PNL_MIN_N", "PNL_WR_FLOOR", "PNL_LOSS_USD",
            "PNL_BLEED_N", "PNL_BLEED_WR", "PNL_BLEED_USD")}
        guardian.PNL_WINDOW_H = 24.0
        guardian.PNL_MIN_N = 30
        guardian.PNL_WR_FLOOR = 0.35
        guardian.PNL_LOSS_USD = 10.0
        guardian.PNL_BLEED_N = 50
        guardian.PNL_BLEED_WR = 0.55
        guardian.PNL_BLEED_USD = 25.0
        self.now = 1_780_000_000.0

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(guardian, k, v)

    def _iso(self, hours_ago):
        from datetime import datetime, timezone
        return datetime.fromtimestamp(self.now - hours_ago * 3600, timezone.utc).isoformat()

    def test_dead_engine_ignored(self):
        # E2's actual shape, but all RTs are 176h+ old → outside window → silent.
        rows = [("E2", self._iso(176 + i * 0.01), -0.06) for i in range(605)]
        self.assertEqual(guardian.evaluate_pnl_breaches(rows, self.now), {})

    def test_live_broken_signal_trips(self):
        # E2-shape but inside the window: catastrophic WR + real loss → T1.
        rows = [("E2", self._iso(0.1), (0.5 if i % 29 == 0 else -0.06)) for i in range(300)]
        b = guardian.evaluate_pnl_breaches(rows, self.now)
        self.assertIn("E2", b)
        self.assertIn("broken_signal", b["E2"])

    def test_healthy_high_volume_engine_never_false_fires(self):
        # E1 = 93.5% WR market-maker; must not halt even with many small losses.
        rows = [("E1", self._iso(1), (0.02 if i % 16 else -0.10)) for i in range(500)]
        self.assertNotIn("E1", guardian.evaluate_pnl_breaches(rows, self.now))

    def test_net_positive_engine_never_trips(self):
        rows = [("PVE", self._iso(2), (0.30 if i % 3 else -0.20)) for i in range(72)]
        self.assertNotIn("PVE", guardian.evaluate_pnl_breaches(rows, self.now))

    def test_small_sample_is_silent(self):
        # Real loss but n < MIN_N → no statistical confidence → no halt.
        rows = [("X", self._iso(0.1), -5.0)] * 10
        self.assertEqual(guardian.evaluate_pnl_breaches(rows, self.now), {})

    def test_sustained_bleed_trips(self):
        # WR ~50% (above broken-signal floor) but steady net bleed → T2.
        rows = [("Y", self._iso(1), (0.5 if i % 2 else -1.5)) for i in range(60)]
        b = guardian.evaluate_pnl_breaches(rows, self.now)
        self.assertIn("Y", b)
        self.assertIn("sustained_bleed", b["Y"])

    def test_iso_and_text_pnl_parsed(self):
        # Ledger reality: ts_close is ISO string, net_pnl is TEXT.
        rows = [("Z", self._iso(0.5), "-0.40") for _ in range(40)]
        b = guardian.evaluate_pnl_breaches(rows, self.now)
        self.assertIn("Z", b)  # WR=0%, cum=-$16 → broken_signal

    def test_breaker_off_when_disabled(self):
        with patch.object(guardian, "PNL_BREAKER_ON", False):
            self.assertFalse(guardian.check_pnl_breaker())


class PositionRiskTests(TestCase):
    """Perps OPEN-position early-warning (blind-spot: PnL breaker hanya lihat RT tertutup).

    Insiden WLD: open leg terisi, close leg telat, klip baru → notional ~3× klip.
    Pemicu ALERT-only (read-only, TIDAK auto-close): drift notional + uPnL ROE dalam.
    """
    CLIP = 120.0     # klip PVE live (TE_PVE_MAX_NOTIONAL)
    MULT = 2.5       # drift jika notional > 2.5× klip
    ROE = -15.0      # ROE floor %

    def _eval(self, positions):
        return guardian.evaluate_position_risk(positions, self.CLIP, self.MULT, self.ROE)

    def test_wld_inventory_drift_flagged(self):
        # WLD ~$363 notional ≈ 3× klip → drift (raw API shape s/sz/ep/ur/iw).
        pos = [{"s": "WLD-USD", "sz": 776, "ep": 0.468, "ur": -1.8, "iw": 72.6}]
        a = self._eval(pos)
        self.assertIn("WLD-USD", a)
        self.assertIn("inventory_drift", a["WLD-USD"])

    def test_healthy_clip_size_silent(self):
        # Notional ~$110 < 2.5×clip, ROE ~ -1% → no alert.
        pos = [{"s": "CHZ-USD", "sz": 1000, "ep": 0.11, "ur": -1.0, "iw": 22.0}]
        self.assertEqual(self._eval(pos), {})

    def test_deep_roe_loss_flagged(self):
        # Notional kecil (no drift) tapi uPnL -$6 / margin $24 = -25% ROE → roe trigger.
        pos = [{"s": "HBAR-USD", "sz": 500, "ep": 0.20, "ur": -6.0, "iw": 24.0}]
        a = self._eval(pos)
        self.assertIn("HBAR-USD", a)
        self.assertIn("roe", a["HBAR-USD"])

    def test_normalized_shape_supported(self):
        # open_positions() ternormalisasi (symbol/quantity/entryPrice/unrealizedPnl/margin).
        pos = [{"symbol": "SPCX-USD", "quantity": -2000, "entryPrice": 0.25,
                "unrealizedPnl": -0.5, "margin": 100.0}]
        a = self._eval(pos)  # notional=$500 > $300 → drift
        self.assertIn("SPCX-USD", a)

    def test_sentinel_unverified_not_alerted(self):
        # open_positions() balikkan sentinel saat API gagal — jangan alert palsu.
        pos = [{"symbol": "UNKNOWN", "quantity": 0, "warning": "api_unverified"}]
        self.assertEqual(self._eval(pos), {})

    def test_empty_and_flat_positions_silent(self):
        self.assertEqual(self._eval([]), {})
        self.assertEqual(self._eval([{"s": "X-USD", "sz": 0, "ep": 1.0}]), {})

    def test_check_position_risk_off_when_disabled(self):
        with patch.object(guardian, "POS_RISK_ON", False), \
             patch.object(guardian, "_api_get") as ag:
            guardian.check_position_risk("0xabc")
            ag.assert_not_called()

    def test_check_position_risk_alert_only_no_halt(self):
        # End-to-end via cycle path: drift posisi → tg_send dipanggil, TIDAK menulis HALT.
        state = {"data": {"P": [{"s": "WLD-USD", "sz": 776, "ep": 0.468, "ur": -1.8, "iw": 72.6}]}}
        with patch.object(guardian, "POS_RISK_ON", True), \
             patch.object(guardian, "POS_CLIP_USD", self.CLIP), \
             patch.object(guardian, "POS_NOTIONAL_MULT", self.MULT), \
             patch.object(guardian, "POS_ROE_FLOOR", self.ROE), \
             patch.object(guardian, "_api_get", return_value=state), \
             patch.object(guardian, "HALT_FILE", _FakeHalt(False)), \
             patch.object(guardian, "tg_send") as tg:
            guardian.check_position_risk("0xabc")
            tg.assert_called_once()


class EngineHealthTests(TestCase):
    """Stall detector (blind-spot ke-3): engine beku berhenti hasilkan RT → tak
    terlihat PnL-breaker. Verdict per-engine: BLEEDING/STALLED/IDLE/HEALTHY.
    ALERT-only — TIDAK pernah menulis SAFETY_HALT (drain sah bisa berjeda)."""

    def setUp(self):
        keys = ("PNL_WINDOW_H", "PNL_MIN_N", "PNL_WR_FLOOR", "PNL_LOSS_USD",
                "PNL_BLEED_N", "PNL_BLEED_WR", "PNL_BLEED_USD",
                "STALL_H", "STALL_LOOKBACK_H")
        self._saved = {k: getattr(guardian, k) for k in keys}
        guardian.PNL_WINDOW_H = 24.0
        guardian.PNL_MIN_N = 30
        guardian.PNL_WR_FLOOR = 0.35
        guardian.PNL_LOSS_USD = 10.0
        guardian.PNL_BLEED_N = 50
        guardian.PNL_BLEED_WR = 0.55
        guardian.PNL_BLEED_USD = 25.0
        guardian.STALL_H = 6.0
        guardian.STALL_LOOKBACK_H = 48.0
        self.now = 1_780_000_000.0

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(guardian, k, v)

    def _iso(self, hours_ago):
        from datetime import datetime, timezone
        return datetime.fromtimestamp(self.now - hours_ago * 3600, timezone.utc).isoformat()

    def test_active_engine_is_healthy(self):
        rows = [("E1", self._iso(1), (0.02 if i % 16 else -0.10)) for i in range(500)]
        h = guardian.evaluate_engine_health(rows, self.now)
        self.assertEqual(h["E1"]["verdict"], "HEALTHY")

    def test_frozen_engine_is_stalled(self):
        # RT terakhir 10h lalu: > STALL_H(6) tapi < LOOKBACK(48) → STALLED.
        rows = [("F", self._iso(10 + i * 0.01), 0.02) for i in range(40)]
        h = guardian.evaluate_engine_health(rows, self.now)
        self.assertEqual(h["F"]["verdict"], "STALLED")

    def test_long_dead_engine_is_idle_not_stalled(self):
        # E2 mati 176h (> LOOKBACK) → IDLE → tak spam alert stall.
        rows = [("E2", self._iso(176 + i * 0.01), -0.06) for i in range(605)]
        h = guardian.evaluate_engine_health(rows, self.now)
        self.assertEqual(h["E2"]["verdict"], "IDLE")

    def test_bleeding_takes_priority_over_stall(self):
        # Engine nge-bleed di window → BLEEDING (selaras PnL-breaker), bukan verdict lain.
        rows = [("E2", self._iso(0.1), (0.5 if i % 29 == 0 else -0.06)) for i in range(300)]
        h = guardian.evaluate_engine_health(rows, self.now)
        self.assertEqual(h["E2"]["verdict"], "BLEEDING")

    def _iso_real(self, hours_ago):
        # check_engine_stall() pakai time.time() nyata → bangun rows relatif waktu nyata.
        from datetime import datetime, timezone
        return datetime.fromtimestamp(guardian.time.time() - hours_ago * 3600,
                                      timezone.utc).isoformat()

    def test_check_engine_stall_off_when_disabled(self):
        with patch.object(guardian, "STALL_ON", False), \
             patch.object(guardian, "_load_rts") as lr:
            guardian.check_engine_stall()
            lr.assert_not_called()

    def test_check_engine_stall_alerts_no_halt(self):
        rows = [("F", self._iso_real(10 + i * 0.01), 0.02) for i in range(40)]
        with patch.object(guardian, "STALL_ON", True), \
             patch.object(guardian, "_load_rts", return_value=rows), \
             patch.object(guardian, "tg_send") as tg:
            guardian.check_engine_stall()
            tg.assert_called_once()

    def test_check_engine_stall_silent_when_all_healthy(self):
        rows = [("E1", self._iso_real(1), 0.02) for i in range(100)]
        with patch.object(guardian, "STALL_ON", True), \
             patch.object(guardian, "_load_rts", return_value=rows), \
             patch.object(guardian, "tg_send") as tg:
            guardian.check_engine_stall()
            tg.assert_not_called()


class LogNoDuplicateTests(TestCase):
    """BUG-L: log() harus tidak menulis dua kali ke file yg sama.
    Sebelum fix: print() (stdout → systemd → file) + open(LOG,"a") = 2× per baris.
    Setelah fix: hanya print(), systemd menangani file.
    """

    def test_log_writes_exactly_once_per_call(self):
        import io, sys
        buf = io.StringIO()
        with patch.object(sys, "stdout", buf):
            guardian.log("test-single-write")
        output = buf.getvalue()
        self.assertEqual(output.count("test-single-write"), 1)

    def test_log_does_not_open_file_directly(self):
        # BUG-L fix verifikasi: log() tidak lagi buka file secara langsung.
        import builtins
        calls = []
        real_open = builtins.open
        def spy_open(path, *a, **kw):
            calls.append(str(path))
            return real_open(path, *a, **kw)
        import io, sys
        with patch.object(builtins, "open", spy_open), \
             patch.object(sys, "stdout", io.StringIO()):
            guardian.log("test-no-file-open")
        log_path = str(guardian.LOG)
        opened_log = [c for c in calls if c == log_path]
        self.assertEqual(opened_log, [], f"log() opened log file directly: {calls}")

    def test_zec_perp_symbol_id_present(self):
        # BUG-K fix: ZEC was missing → orphan perp orders couldn't be cancelled
        self.assertEqual(guardian._symbol_id_for("ZEC-USD"), 18)
        self.assertIn("ZEC", guardian.SYMBOL_ID)
