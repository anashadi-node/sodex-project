"""Regresi fill journal daemon + konsumsi watchdog.

Konteks (2026-11-06): daemon live membuka posisi tanpa jejak state lokal,
sehingga watchdog melaporkan UNTRACKED palsu. Fill journal = sumber kebenaran
"posisi ini dikelola daemon". Journal harus best-effort (tidak boleh
menghentikan trading) dan watchdog harus fail-open ke CRITICAL bila data hilang.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import anantara.sodex_farming as farming  # noqa: E402
import sodex_live_watchdog as watchdog  # noqa: E402


@pytest.fixture()
def journal(tmp_path, monkeypatch):
    path = tmp_path / "fills.jsonl"
    monkeypatch.setattr(farming, "FILL_JOURNAL", path)
    return path


def _read(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


class TestFarmingJournal:
    def test_place_success_writes_symbol_order_id(self, journal):
        farming._journal_order(
            ["orders", "place", "perps", "--symbol", "NEAR-USD", "--side", "buy"],
            {"data": {"orderID": 32429257467, "status": "FILLED", "filledQty": "18.3"}},
            None,
        )
        rec = _read(journal)[0]
        assert rec["cmd"] == "place"
        assert rec["symbol"] == "NEAR-USD"
        assert rec["order_id"] == 32429257467
        assert rec["ok"] is True
        assert rec["filled_qty"] == "18.3"

    def test_error_recorded_not_raised(self, journal):
        farming._journal_order(
            ["orders", "place", "perps", "--symbol", "WIF-USD"],
            None,
            "sodex API error (code 429): Rate limit exceeded",
        )
        rec = _read(journal)[0]
        assert rec["ok"] is False
        assert "429" in rec["error"]

    def test_non_order_command_ignored(self, journal):
        farming._journal_order(["balance", "perps"], {"data": {}}, None)
        assert not journal.exists()

    def test_journal_failure_does_not_raise(self, tmp_path, monkeypatch):
        blocker = tmp_path / "blocker"
        blocker.write_text("x")
        monkeypatch.setattr(farming, "FILL_JOURNAL", blocker / "sub" / "fills.jsonl")
        farming._journal_order(
            ["orders", "cancel", "perps", "--symbol", "WIF-USD"], {"data": {}}, None
        )


class TestWatchdogConsumption:
    def _write(self, path: Path, *records: dict) -> None:
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    def _rec(self, symbol, *, filled="1", status="FILLED", ok=True,
             reduce_only=False, hours_ago=1):
        ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        argv = ["perps", "--symbol", symbol]
        if reduce_only:
            argv.append("--reduce-only")
        return {"ts": ts.isoformat(), "cmd": "place", "argv": argv, "ok": ok,
                "symbol": symbol, "status": status, "filled_qty": filled}

    def test_filled_place_tracks_symbol(self, journal, monkeypatch):
        monkeypatch.setattr(watchdog, "DAEMON_FILL_JOURNAL", journal)
        self._write(journal, self._rec("NEAR-USD"))
        assert watchdog.load_daemon_journal_symbols() == {"NEAR-USD"}

    def test_pending_entry_tracked_failed_place_ignored(self, journal, monkeypatch):
        """Fill datang setelah place (status NEW) -> symbol tetap milik daemon."""
        monkeypatch.setattr(watchdog, "DAEMON_FILL_JOURNAL", journal)
        self._write(
            journal,
            self._rec("WIF-USD", filled="0", status="NEW"),
            self._rec("ETH-USD", ok=False),
        )
        assert watchdog.load_daemon_journal_symbols() == {"WIF-USD"}

    def test_reduce_only_pending_does_not_untrack(self, journal, monkeypatch):
        monkeypatch.setattr(watchdog, "DAEMON_FILL_JOURNAL", journal)
        self._write(
            journal,
            self._rec("WIF-USD"),
            self._rec("WIF-USD", filled="0", status="NEW", reduce_only=True),
        )
        assert watchdog.load_daemon_journal_symbols() == {"WIF-USD"}

    def test_reduce_only_fill_removes_symbol(self, journal, monkeypatch):
        monkeypatch.setattr(watchdog, "DAEMON_FILL_JOURNAL", journal)
        self._write(journal, self._rec("NEAR-USD"), self._rec("NEAR-USD", reduce_only=True))
        assert watchdog.load_daemon_journal_symbols() == set()

    def test_stale_entries_ignored(self, journal, monkeypatch):
        monkeypatch.setattr(watchdog, "DAEMON_FILL_JOURNAL", journal)
        self._write(journal, self._rec("NEAR-USD", hours_ago=24 * 30))
        assert watchdog.load_daemon_journal_symbols(max_age_days=7) == set()

    def test_missing_journal_fails_open(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watchdog, "DAEMON_FILL_JOURNAL", tmp_path / "nope.jsonl")
        assert watchdog.load_daemon_journal_symbols() == set()
