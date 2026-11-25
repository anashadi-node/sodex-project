import re
from pathlib import Path
from unittest import TestCase


class SodexWatchdogPolicyTests(TestCase):
    def test_watchdog_ignores_stale_restart_signal_and_honors_halt(self):
        source = Path("scripts/watchdog_twin.sh").read_text()

        self.assertIn("MAX_RESTART_SIGNAL_AGE_SEC", source)
        self.assertIn("stale restart signal ignored", source)
        self.assertIn("HALT active — restart suppressed", source)
        self.assertIn("WATCHDOG_LOCK_DIR", source)
        self.assertIn("another watchdog already active", source)
        self.assertIn("OLD_CMD", source)
        self.assertIn("watchdog_twin.sh", source)
        self.assertIn("HALT active before restart — restart suppressed", source)
        self.assertIn('halt_active() { [ -f "$PNL_HALT_FILE" ] || [ -f "$SAFETY_HALT_FILE" ]; }', source)
        self.assertIn("if halt_active; then", source)

    def test_engine_writes_safety_halt_on_hard_stop(self):
        source = Path("anantara/sodex_twin_engine.py").read_text()

        self.assertIn("def write_safety_halt", source)
        self.assertIn('write_safety_halt(str(e))', source)
        self.assertIn('"source": "sodex_twin_engine"', source)

    def test_watchdog_pve_pause_gate_uses_defined_path_and_logger(self):
        source = Path("scripts/watchdog_twin.sh").read_text()

        self.assertIn("apply_pve_pause_gate()", source)
        self.assertIn('if [[ -f "data/PVE_PAUSE" ]]; then', source)
        # TE_PVE_ENABLED=0 was removed after BUG-B fix (2026-07-06); now .env is source of truth
        self.assertNotIn("export TE_PVE_ENABLED=0", source)
        self.assertIn('log "INFO PVE_PAUSE gate active', source)
        self.assertGreaterEqual(source.count("apply_pve_pause_gate"), 2)
        self.assertNotIn("${PROJECT}/data/PVE_PAUSE", source)
        self.assertNotIn("log_msg", source)


class S11SingleCapitalSourceTests(TestCase):
    """Regresi S11 (audit 06-Okt-2026): TE_CAPITAL_USD punya 3 nilai tergantung
    jalur start -- engine default 60, watchdog (.env kanonik) 30, dan
    start_twin_live.sh fallback 94 karena whitelist-nya cuma export 5 key
    sehingga TE_CAPITAL_USD dari .env DIBUANG. Cap risiko modal tak boleh
    tergantung jalur start; .env = satu sumber kebenaran."""

    def test_start_twin_live_sources_full_env_without_capital_hardcode(self):
        source = Path("scripts/start_twin_live.sh").read_text()
        # Full-env load, sama dgn watchdog (satu sumber kebenaran)
        self.assertIn("set -a", source)
        self.assertIn("source .env", source)
        self.assertIn("set +a", source)
        # Tidak ada fallback `${TE_CAPITAL_USD:-<angka>}` yang menimpa .env
        self.assertIsNone(
            re.search(r'TE_CAPITAL_USD="\$\{TE_CAPITAL_USD:-[0-9]+\}"', source),
            "fallback TE_CAPITAL_USD=!= kebijakan modal via pintu belakang (S11 fix) -- .env kanonik")
