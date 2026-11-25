"""Regresi readout A/B exit REGIME_FLIP.

Bug nyata yang dijaga di sini: `systemctl show --timestamp=unix` mengembalikan
`@1793938151`, bukan angka polos — tanpa strip '@' seluruh arm jadi "cut time
tidak terbaca" dan readout diam-diam MONITOR selamanya.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sodex_ab_flip_readout as ab  # noqa: E402


def _row(t: datetime, pnl: float, reason: str = "SL", status: str = "CLOSED") -> str:
    return json.dumps({
        "status": status, "pnl_pct": pnl, "exit_reason": reason,
        "exit_time": t.isoformat(), "pair": "XRP", "id": f"XRP_{t.timestamp()}",
    })


class TestCutFilter:
    def test_unit_start_parses_at_prefix(self, monkeypatch):
        monkeypatch.setattr(ab.subprocess, "run", lambda *a, **k: type(
            "R", (), {"stdout": "ActiveEnterTimestamp=@1793938151\n"})())
        t = ab.unit_start("fake.service")
        assert t == datetime.fromtimestamp(1793938151, tz=timezone.utc)

    def test_pre_restart_trades_excluded(self, tmp_path, monkeypatch):
        cut = datetime(2026, 11, 6, 7, 5, tzinfo=timezone.utc)
        f = tmp_path / "lane.jsonl"
        f.write_text("\n".join([
            _row(cut - timedelta(hours=3), -0.02, "REGIME_FLIP"),
            _row(cut + timedelta(minutes=30), -0.01, "SL"),
            _row(cut + timedelta(hours=1), 0.02, "TP"),
        ]) + "\n")
        rows = ab.load_closed(f)
        post = [r for r in rows if ab.lane_edge.ts_of(r) >= cut]
        assert len(rows) == 3
        assert len(post) == 2
        assert all("FLIP" not in str(r["exit_reason"]) for r in post)

    def test_open_trades_ignored(self, tmp_path):
        f = tmp_path / "lane.jsonl"
        f.write_text(_row(datetime.now(timezone.utc), -0.01, status="OPEN") + "\n")
        assert ab.load_closed(f) == []
