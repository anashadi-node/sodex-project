#!/usr/bin/env python3
"""Read-only SoDEX monitoring and weekly evaluation.

This collector deliberately does not place, cancel, or sign orders. It reconciles:
- local twin-engine ledger (`fills`, `rts`);
- live SoDEX public account API data;
- weekly window anchored at Saturday 07:00 WIB (Saturday 00:00 UTC).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


UTC = timezone.utc
WIB = timezone(timedelta(hours=7))
PROJECT_DIR = Path(os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti")))
DEFAULT_DB = PROJECT_DIR / "twin_engine.db"
DEFAULT_ENV = PROJECT_DIR / ".env"
DEFAULT_OUT = PROJECT_DIR / "data" / "sodex_monitor_eval"
SAFETY_HALT_FILE = PROJECT_DIR / "data" / "SAFETY_HALT"
PNL_HALT_FILE = PROJECT_DIR / "data" / "PNL_HALT"
LIVE_KILL_FILES = {
    "REALWIDE_LIVE_KILL": PROJECT_DIR / "data" / "REALWIDE_LIVE_KILL",
    "SPOT_LIVE_KILL": PROJECT_DIR / "data" / "SPOT_LIVE_KILL",
}
TELEGRAM_HEALTH_FILE = PROJECT_DIR / "data" / "telegram_health.json"
SODEX_API = "https://mainnet-gw.sodex.dev/api/v1"
USER_AGENT = "anantara-sakti-sodex-monitor-eval/1.0"

TARGET_WEEKLY_VOLUME_USD = Decimal(os.environ.get("SODEX_EVAL_TARGET_WEEKLY_VOLUME", "1300000"))
TARGET_WIN_RATE = Decimal(os.environ.get("SODEX_EVAL_TARGET_WIN_RATE", "0.69"))
EMERGENCY_RATIO_UNTIL_WIB = datetime(2026, 7, 18, 9, 30, tzinfo=WIB)
_DEFAULT_TARGET_VOLUME_FEE_RATIO = "5100" if datetime.now(WIB) <= EMERGENCY_RATIO_UNTIL_WIB else "7000"
TARGET_VOLUME_FEE_RATIO = Decimal(os.environ.get("SODEX_EVAL_TARGET_VOLUME_FEE_RATIO", _DEFAULT_TARGET_VOLUME_FEE_RATIO))
# E2Dir paper→live promotion gate (explicit, evidence-based). Real-money flip stays
# operator-manual; this only emits a PROMOTE-READY verdict when robustness proven.
PROMOTE_MIN_N = int(os.environ.get("SODEX_E2DIR_PROMOTE_MIN_N", "50"))
PROMOTE_WILSON_FLOOR = float(os.environ.get("SODEX_E2DIR_PROMOTE_WILSON_FLOOR", "0.50"))
PROMOTE_FRESH_HOURS = int(os.environ.get("SODEX_E2DIR_PROMOTE_FRESH_HOURS", "72"))
# Early-loss detection (antisipasi kerugian sangat dini) — window pendek, per-engine/pair.
EARLY_LOSS_WINDOW_MIN = int(os.environ.get("SODEX_EARLY_LOSS_WINDOW_MIN", "60"))

# --- Penjaga integritas ledger (30-Sep-2026) ---
# Hanya RT yang TERAUDIT yang boleh masuk metrik: minimal satu fill-nya
# bertimestamp di dalam window. Baris hasil ID daur-ulang (penghitung _rt
# di-reset 0 tiap sesi + INSERT OR REPLACE, insiden 28-Sep-2026) punya ts_close
# di dalam window tetapi SELURUH fill-nya di luar window → WR/PnL-nya menyesatkan.
# Terukur: 324 dari 325 baris window 26-Sep→3-Okt tak teraudit, sehingga WR 29,23%
# (95/325) adalah angka palsu; sampel yang benar-benar sah = 1 baris.
# Penghitung RT sudah diperbaiki di sodex_twin_engine (commit 87d484f); penjaga
# ini melindungi metrik dari data historis yang sudah tercemar.
_RT_AUDITED_SQL = """
                  AND EXISTS (SELECT 1 FROM fills f
                              WHERE f.rt_id = rts.rt_id AND f.ts >= ? AND f.ts < ?)"""
EARLY_LOSS_USD_FLOOR = float(os.environ.get("SODEX_EARLY_LOSS_USD_FLOOR", "3.0"))
EARLY_LOSS_PAIR_FLOOR = float(os.environ.get("SODEX_EARLY_LOSS_PAIR_FLOOR", "2.0"))
SENSITIVE_STALE_FILL_MIN = int(os.environ.get("SODEX_SENSITIVE_STALE_FILL_MIN", "15"))
SENSITIVE_FILL_RT_GAP_MIN_FILLS = int(os.environ.get("SODEX_SENSITIVE_FILL_RT_GAP_MIN_FILLS", "6"))
SENSITIVE_OFFICIAL_DRIFT_MULTIPLE = Decimal(os.environ.get("SODEX_SENSITIVE_OFFICIAL_DRIFT_MULTIPLE", "2.0"))
ID_MONTHS = {
    1: "Januari",
    2: "Februari",
    3: "Maret",
    4: "April",
    5: "Mei",
    6: "Juni",
    7: "Juli",
    8: "Agustus",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Desember",
}


@dataclass(frozen=True)
class WeekWindow:
    start: datetime
    end: datetime

    @property
    def label(self) -> str:
        return f"{self.start.isoformat()}_to_{self.end.isoformat()}"


def now_utc() -> datetime:
    return datetime.now(UTC)


def week_window(now: datetime | None = None) -> WeekWindow:
    """Current SoDEX evaluation week.

    Boundary: Saturday 07:00 WIB == Saturday 00:00 UTC.
    """
    now = now or now_utc()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    now = now.astimezone(UTC)
    days_back = (now.weekday() - 5) % 7
    start = (now - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    return WeekWindow(start=start, end=end)


def format_id_date(dt: datetime) -> str:
    dt = dt.astimezone(WIB)
    return f"{dt.day} {ID_MONTHS[dt.month]} {dt.year}"


def week_display(window: WeekWindow) -> dict[str, str]:
    start_wib = window.start.astimezone(WIB)
    end_wib = window.end.astimezone(WIB)
    return {
        "range": f"{format_id_date(start_wib)} - {format_id_date(end_wib)}",
        "snapshot_wib": f"{format_id_date(end_wib)} 07:00 WIB",
        "weekly_label": f"weekly {end_wib.day} sodex",
    }


def week_display_from_report_window(window: dict[str, Any]) -> dict[str, str]:
    try:
        start = datetime.fromisoformat(str(window["start"]))
        end = datetime.fromisoformat(str(window["end"]))
        return week_display(WeekWindow(start=start, end=end))
    except Exception:
        return {
            "range": str(window.get("range") or "?"),
            "snapshot_wib": str(window.get("snapshot_wib") or "?"),
            "weekly_label": str(window.get("weekly_label") or "weekly ? sodex"),
        }


def _official_dashboard_path(out_dir: Path) -> Path:
    override = os.environ.get("SODEX_EVAL_OFFICIAL_DASHBOARD", "").strip()
    return Path(override) if override else out_dir / "official_dashboard.json"


def _select_dashboard_record(payload: Any, window: WeekWindow) -> dict[str, Any] | None:
    records: list[dict[str, Any]]
    if isinstance(payload, dict) and isinstance(payload.get("snapshots"), list):
        records = [x for x in payload["snapshots"] if isinstance(x, dict)]
    elif isinstance(payload, list):
        records = [x for x in payload if isinstance(x, dict)]
    elif isinstance(payload, dict):
        records = [payload]
    else:
        return None

    display = week_display(window)
    for record in records:
        if (
            str(record.get("window_label") or record.get("label") or "") == window.label
            or str(record.get("weekly_label") or "") == display["weekly_label"]
            or str(record.get("range") or "") == display["range"]
        ):
            return record
    return records[-1] if records else None


def _first_decimal(record: dict[str, Any], keys: tuple[str, ...]) -> Decimal:
    for key in keys:
        if key in record:
            return dec(record.get(key))
    return Decimal("0")


def load_official_dashboard_snapshot(
    out_dir: Path,
    window: WeekWindow,
    ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load the official SoDEX points dashboard snapshot, if available.

    This is intentionally separate from the internal ledger. The dashboard is the
    canonical source for volume credited by SoDEX points; the ledger remains the
    audit source for bot-side fills, fees, RTs, and realized PnL.
    """
    path = _official_dashboard_path(out_dir)
    if not path.exists():
        return {
            "quality": "MISSING",
            "canonical": False,
            "path": str(path),
            "warnings": ["official_dashboard_snapshot_missing"],
        }

    try:
        payload = json.loads(path.read_text())
    except Exception as exc:
        return {
            "quality": "INVALID_JSON",
            "canonical": False,
            "path": str(path),
            "warnings": [f"official_dashboard_json_invalid:{type(exc).__name__}"],
        }

    record = _select_dashboard_record(payload, window)
    if record is None:
        return {
            "quality": "NO_RECORD",
            "canonical": False,
            "path": str(path),
            "warnings": ["official_dashboard_record_missing"],
        }

    display = week_display(window)
    window_match = (
        str(record.get("window_label") or record.get("label") or "") == window.label
        or str(record.get("weekly_label") or "") == display["weekly_label"]
        or str(record.get("range") or "") == display["range"]
    )
    spot = _first_decimal(record, ("spot_volume_usd", "spot_usd", "spotVol", "spot_volume"))
    perps = _first_decimal(
        record,
        ("futures_volume_usd", "perps_volume_usd", "perps_usd", "future_volume_usd", "futuresVol"),
    )
    total = _first_decimal(record, ("total_volume_usd", "total_usd", "volume_usd", "total_volume"))
    if total <= 0:
        total = spot + perps

    quality = "OK" if window_match and total > 0 else "STALE_OR_EMPTY"
    warnings: list[str] = []
    if not window_match:
        warnings.append("official_dashboard_window_mismatch")
    if total <= 0:
        warnings.append("official_dashboard_volume_empty")

    official = {
        "quality": quality,
        "canonical": quality == "OK",
        "path": str(path),
        "source": str(record.get("source") or "sodex.com/points"),
        "observed_at": record.get("observed_at"),
        "window": {
            "range": str(record.get("range") or display["range"]),
            "weekly_label": str(record.get("weekly_label") or display["weekly_label"]),
            "window_label": str(record.get("window_label") or record.get("label") or window.label),
        },
        "volume": {
            "spot_usd": float(spot),
            "perps_usd": float(perps),
            "total_usd": float(total),
        },
        "warnings": warnings,
    }

    ledger_volume = (ledger or {}).get("volume") or {}
    ledger_total = dec(ledger_volume.get("raw_total_usd"))
    if ledger_total > 0:
        ledger_spot = dec(ledger_volume.get("spot_usd"))
        ledger_perps = dec(ledger_volume.get("perps_usd"))
        official["reconciliation"] = {
            "ledger_spot_usd": float(ledger_spot),
            "ledger_perps_usd": float(ledger_perps),
            "ledger_total_usd": float(ledger_total),
            "spot_delta_usd": float(ledger_spot - spot),
            "perps_delta_usd": float(ledger_perps - perps),
            "total_delta_usd": float(ledger_total - total),
            "ledger_over_official_multiple": float(ledger_total / total) if total > 0 else None,
        }
    return official


def dec(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


def as_float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def read_env_value(path: Path, key: str) -> str:
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    except FileNotFoundError:
        return ""
    return ""


def _extract_data(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


class SodexApi:
    def __init__(self, base_url: str = SODEX_API, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.errors: list[str] = []
        try:
            import httpx  # type: ignore
        except Exception:
            self._httpx = None
        else:
            self._httpx = httpx

    def get(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        if self._httpx is not None:
            try:
                with self._httpx.Client(
                    headers={"user-agent": USER_AGENT, "accept": "application/json"},
                    timeout=self.timeout,
                ) as client:
                    response = client.get(url)
                if response.status_code != 200:
                    self.errors.append(f"{path}:HTTP_{response.status_code}")
                    return None
                return response.json()
            except Exception as exc:
                self.errors.append(f"{path}:{type(exc).__name__}")
                return None

        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode())
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            self.errors.append(f"{path}:{type(exc).__name__}")
            return None


def aggregate_ledger(db_path: Path, window: WeekWindow) -> dict[str, Any]:
    if not db_path.exists():
        return {"quality": "MISSING_DB", "warnings": [f"db not found: {db_path}"]}

    start = window.start.isoformat()
    end = window.end.isoformat()
    try:
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        return {"quality": "DB_OPEN_ERROR", "warnings": [str(exc)]}

    try:
        fill_row = con.execute(
            """
            SELECT COUNT(*) AS n,
                   COALESCE(SUM(CAST(notional AS REAL)), 0) AS volume,
                   COALESCE(SUM(CAST(fee AS REAL)), 0) AS fees,
                   COALESCE(SUM(CASE WHEN maker=1 THEN 1 ELSE 0 END), 0) AS maker_n,
                   COALESCE(SUM(CASE WHEN maker=0 THEN 1 ELSE 0 END), 0) AS taker_n,
                   MIN(ts) AS first_ts,
                   MAX(ts) AS last_ts
            FROM fills
            WHERE ts >= ? AND ts < ?
            """,
            (start, end),
        ).fetchone()
        by_bucket = {
            row["bucket"]: dict(row)
            for row in con.execute(
                """
                SELECT bucket,
                       COUNT(*) AS n,
                       COALESCE(SUM(CAST(notional AS REAL)), 0) AS volume,
                       COALESCE(SUM(CAST(fee AS REAL)), 0) AS fees
                FROM fills
                WHERE ts >= ? AND ts < ?
                GROUP BY bucket
                """,
                (start, end),
            )
        }
        by_engine = [
            dict(row)
            for row in con.execute(
                """
                SELECT engine,
                       bucket,
                       COUNT(*) AS fills,
                       ROUND(COALESCE(SUM(CAST(notional AS REAL)), 0), 8) AS volume_usd,
                       ROUND(COALESCE(SUM(CAST(fee AS REAL)), 0), 8) AS fees_usd,
                       ROUND(COALESCE(AVG(CASE WHEN maker=1 THEN 1.0 ELSE 0.0 END), 0), 6) AS maker_rate
                FROM fills
                WHERE ts >= ? AND ts < ?
                GROUP BY engine, bucket
                ORDER BY engine, bucket
                """,
                (start, end),
            )
        ]
        by_pair = [
            dict(row)
            for row in con.execute(
                """
                SELECT pair,
                       bucket,
                       COUNT(*) AS fills,
                       ROUND(COALESCE(SUM(CAST(notional AS REAL)), 0), 8) AS volume_usd,
                       ROUND(COALESCE(SUM(CAST(fee AS REAL)), 0), 8) AS fees_usd
                FROM fills
                WHERE ts >= ? AND ts < ?
                GROUP BY pair, bucket
                ORDER BY volume_usd DESC
                """,
                (start, end),
            )
        ]
        rt_row = con.execute(
            f"""
            SELECT COUNT(*) AS n,
                   COALESCE(SUM(CAST(volume AS REAL)), 0) AS rt_volume,
                   COALESCE(SUM(CAST(net_pnl AS REAL)), 0) AS pnl,
                   COALESCE(SUM(CASE WHEN CAST(net_pnl AS REAL) > 0 THEN 1 ELSE 0 END), 0) AS wins,
                   COALESCE(SUM(CASE WHEN CAST(net_pnl AS REAL) <= 0 THEN 1 ELSE 0 END), 0) AS losses,
                   COALESCE(SUM(CASE WHEN CAST(net_pnl AS REAL) > 0 THEN CAST(net_pnl AS REAL) ELSE 0 END), 0) AS gross_profit,
                   COALESCE(SUM(CASE WHEN CAST(net_pnl AS REAL) < 0 THEN -CAST(net_pnl AS REAL) ELSE 0 END), 0) AS gross_loss
            FROM rts
            WHERE ts_close >= ? AND ts_close < ?{_RT_AUDITED_SQL}
            """,
            (start, end, start, end),
        ).fetchone()
        # Berapa baris yang DIBUANG penjaga (transparansi: kalau besar, ledger
        # sedang tercemar dan angka metrik tidak boleh dipercaya apa adanya).
        rt_unverified_row = con.execute(
            f"""
            SELECT COUNT(*) AS n
            FROM rts
            WHERE ts_close >= ? AND ts_close < ?
              AND NOT EXISTS (SELECT 1 FROM fills f
                              WHERE f.rt_id = rts.rt_id AND f.ts >= ? AND f.ts < ?)
            """,
            (start, end, start, end),
        ).fetchone()
        by_engine_rt = [
            dict(row)
            for row in con.execute(
                f"""
                SELECT engine,
                       COUNT(*) AS rts,
                       ROUND(COALESCE(SUM(CAST(volume AS REAL)), 0), 8) AS volume_usd,
                       ROUND(COALESCE(SUM(CAST(net_pnl AS REAL)), 0), 8) AS pnl_usd
                FROM rts
                WHERE ts_close >= ? AND ts_close < ?{_RT_AUDITED_SQL}
                GROUP BY engine
                ORDER BY engine
                """,
                (start, end, start, end),
            )
        ]
    except sqlite3.Error as exc:
        con.close()
        return {"quality": "DB_QUERY_ERROR", "warnings": [str(exc)]}
    finally:
        try:
            con.close()
        except Exception:
            pass

    fills = int(fill_row["n"])
    raw_volume = dec(fill_row["volume"])
    fees = dec(fill_row["fees"])
    spot_volume = dec(by_bucket.get("S", {}).get("volume") if "S" in by_bucket else 0)
    perps_volume = dec(by_bucket.get("P", {}).get("volume") if "P" in by_bucket else 0)
    weighted_volume = perps_volume + (spot_volume * Decimal("2"))
    rts = int(rt_row["n"])
    rt_unverified = int(rt_unverified_row["n"])
    wins = int(rt_row["wins"])
    losses = int(rt_row["losses"])
    realized = dec(rt_row["pnl"])
    gross_loss = dec(rt_row["gross_loss"])
    # --- Engine-level PnL & Fee coverage (E1 = profit engine, E2 = volume engine) ---
    e1_pnl = Decimal("0")
    e2_pnl = Decimal("0")
    e1_fees = Decimal("0")
    e2_fees = Decimal("0")
    for eng in by_engine:
        eng_name = str(eng.get("engine", ""))
        eng_fee = Decimal(str(eng.get("fees_usd", "0")))
        if eng_name == "E1":
            e1_fees += eng_fee
        elif eng_name == "E2":
            e2_fees += eng_fee
    for eng in by_engine_rt:
        eng_name = str(eng.get("engine", ""))
        eng_pnl = Decimal(str(eng.get("pnl_usd", "0")))
        if eng_name == "E1":
            e1_pnl = eng_pnl
        elif eng_name == "E2":
            e2_pnl = eng_pnl
    e1_covers_e2_fees = bool(e1_pnl >= e2_fees)
    e1_covers_all_fees = bool(e1_pnl >= (e1_fees + e2_fees))
    combined_no_loss = bool(e1_pnl + e2_pnl >= 0)

    warnings: list[str] = []
    if fills == 0:
        warnings.append("no ledger fills in current weekly window")
    if rts == 0:
        warnings.append("no closed RTs in current weekly window")
    if rt_unverified > 0:
        # Ledger tercemar: baris ber-ts_close di window tapi fill-nya di luar
        # window (ID daur-ulang). Metrik di atas SUDAH mengecualikannya; sinyal
        # ini supaya angka tersebut tidak dipercaya sebagai kinerja strategi.
        warnings.append(f"rt_rows_unverifiable_excluded:{rt_unverified}")

    return {
        "quality": "OK",
        "window": {"start": start, "end": end},
        "fills": {
            "count": fills,
            "maker_count": int(fill_row["maker_n"]),
            "taker_count": int(fill_row["taker_n"]),
            "maker_rate": (int(fill_row["maker_n"]) / fills) if fills else None,
            "first_ts": fill_row["first_ts"],
            "last_ts": fill_row["last_ts"],
        },
        "volume": {
            "spot_usd": float(spot_volume),
            "perps_usd": float(perps_volume),
            "raw_total_usd": float(raw_volume),
            "weighted_total_usd": float(weighted_volume),
            "rt_closed_volume_usd": float(dec(rt_row["rt_volume"])),
        },
        "costs": {"fees_usd": float(fees)},
        "pnl": {"realized_net_usd": float(realized)},
        "rts": {
            "count": rts,
            # Hanya RT TERAUDIT (fill-nya ada di dalam window) yang dihitung.
            "audited_only": True,
            "excluded_unverifiable": rt_unverified,
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / rts) if rts else None,
            "gross_profit_usd": float(dec(rt_row["gross_profit"])),
            "gross_loss_usd": float(gross_loss),
            "profit_factor": float(dec(rt_row["gross_profit"]) / gross_loss) if gross_loss > 0 else None,
        },
        "ratios": {
            "volume_to_fee": float(raw_volume / fees) if fees > 0 else None,
            "weighted_volume_to_fee": float(weighted_volume / fees) if fees > 0 else None,
            "volume_to_realized_loss": float(raw_volume / (-realized)) if realized < 0 else None,
            "cost_coverage_realized_pnl_over_fee": float(realized / fees) if fees > 0 else None,
        },
        "coverage": {
            "e1_realized_pnl": float(e1_pnl),
            "e1_fees_usd": float(e1_fees),
            "e2_realized_pnl": float(e2_pnl),
            "e2_fees_usd": float(e2_fees),
            "e1_covers_e2_fees": e1_covers_e2_fees,
            "e1_covers_all_fees": e1_covers_all_fees,
            "combined_no_loss": combined_no_loss,
        },
        "by_engine": by_engine,
        "by_pair": by_pair,
        "warnings": warnings,
    }


def _list_from_data(payload: Any, key: str) -> list[dict[str, Any]]:
    data = _extract_data(payload)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        value = data.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def _state_position_records(payload: Any) -> list[dict[str, Any]]:
    data = _extract_data(payload)
    if not isinstance(data, dict):
        return []
    raw_positions = data.get("P")
    if not isinstance(raw_positions, list):
        return []
    positions: list[dict[str, Any]] = []
    for p in raw_positions:
        if not isinstance(p, dict):
            continue
        size = dec(p.get("sz"))
        if abs(size) <= Decimal("0.00000001"):
            continue
        symbol = str(p.get("s") or "")
        positions.append(
            {
                "symbol": symbol,
                "side": "LONG" if size > 0 else "SHORT",
                "size": float(size),
                "entry_price": float(dec(p.get("ep"))),
                "unrealized_pnl_field_usd": float(dec(p.get("ur"))),
                "initial_margin_usd": float(dec(p.get("iw"))),
                "leverage": p.get("l"),
                "source": "state.P",
            }
        )
    return positions


def _position_truth(
    *,
    raw_positions: Any,
    raw_state: Any,
    endpoint_positions: list[dict[str, Any]],
    state_positions: list[dict[str, Any]],
) -> dict[str, Any]:
    endpoint_available = raw_positions is not None
    state_data = _extract_data(raw_state) if raw_state is not None else None
    state_available = isinstance(state_data, dict)
    endpoint_open = [p for p in endpoint_positions if abs(dec(p.get("size"))) > Decimal("0.00000001")]
    endpoint_symbols = sorted(str(p.get("symbol") or "") for p in endpoint_open)
    state_symbols = sorted(str(p.get("symbol") or "") for p in state_positions)
    disagreement = endpoint_available and state_available and endpoint_symbols != state_symbols
    open_count = max(len(endpoint_open), len(state_positions))
    verified_flat = endpoint_available and state_available and open_count == 0 and not disagreement
    quality = "OK"
    warnings: list[str] = []
    if disagreement:
        quality = "DISAGREE"
        warnings.append("perps_positions_disagree_with_state_P")
    elif not endpoint_available or not state_available:
        quality = "UNVERIFIED"
        warnings.append("position_truth_source_missing")
    return {
        "quality": quality,
        "verified_flat": verified_flat,
        "open_count": open_count,
        "positions_endpoint_count": len(endpoint_open),
        "state_P_count": len(state_positions),
        "positions_endpoint_available": endpoint_available,
        "state_P_available": state_available,
        "canonical_source": "max(positions_endpoint,state.P)",
        "positions": state_positions if len(state_positions) >= len(endpoint_open) else endpoint_open,
        "warnings": warnings,
    }


def _account_open_position_count(account: dict[str, Any]) -> int:
    truth = account.get("position_truth") or {}
    if isinstance(truth, dict) and "open_count" in truth:
        return int(dec(truth.get("open_count")))
    return len(((account.get("assets") or {}).get("perps_positions") or []))


def _price_from_ticker(t: dict[str, Any]) -> Decimal:
    bid = dec(t.get("bidPx"))
    ask = dec(t.get("askPx"))
    if bid > 0 and ask > 0:
        return (bid + ask) / Decimal("2")
    for key in ("markPrice", "lastPx", "indexPrice"):
        px = dec(t.get(key))
        if px > 0:
            return px
    return Decimal("0")


def _spot_price_maps(tickers: list[dict[str, Any]]) -> tuple[dict[str, Decimal], dict[str, str]]:
    prices: dict[str, Decimal] = {"vUSDC": Decimal("1")}
    symbols: dict[str, str] = {}
    for t in tickers:
        symbol = str(t.get("symbol", ""))
        if not symbol.endswith("_vUSDC"):
            continue
        coin = symbol.removesuffix("_vUSDC")
        px = _price_from_ticker(t)
        if px > 0:
            prices[coin] = px
            symbols[coin] = symbol
    return prices, symbols


def _perps_ticker_map(tickers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(t.get("symbol")): t for t in tickers if t.get("symbol")}


def aggregate_account(address: str, window: WeekWindow, *, api: SodexApi | None = None, no_api: bool = False) -> dict[str, Any]:
    if no_api:
        return {"quality": "DISABLED", "warnings": ["api disabled by --no-api"]}
    if not address:
        return {"quality": "MISSING_ADDRESS", "warnings": ["SODEX_ADDRESS not found"]}

    api = api or SodexApi()
    paths = {
        "perps_state": f"/perps/accounts/{address}/state",
        "perps_balances": f"/perps/accounts/{address}/balances",
        "perps_positions": f"/perps/accounts/{address}/positions",
        "perps_trades": f"/perps/accounts/{address}/trades",
        "perps_fundings": f"/perps/accounts/{address}/fundings",
        "fee_rate": f"/perps/accounts/{address}/fee-rate",
        "spot_balances": f"/spot/accounts/{address}/balances",
        "spot_trades": f"/spot/accounts/{address}/trades",
        "spot_tickers": "/spot/markets/tickers",
        "perps_tickers": "/perps/markets/tickers",
    }
    raw = {name: api.get(path) for name, path in paths.items()}
    warnings = list(api.errors)
    missing = [name for name, payload in raw.items() if payload is None]
    if missing:
        warnings.append(f"missing_api_sections:{','.join(missing)}")

    spot_tickers = _list_from_data(raw.get("spot_tickers"), "tickers")
    spot_prices, spot_symbols = _spot_price_maps(spot_tickers)
    perps_tickers = _perps_ticker_map(_list_from_data(raw.get("perps_tickers"), "tickers"))

    spot_assets = []
    spot_usdc = Decimal("0")
    spot_equity = Decimal("0")
    for b in _list_from_data(raw.get("spot_balances"), "balances"):
        coin = str(b.get("coin", ""))
        locked = dec(b.get("locked"))
        # SoDEX `total` already includes wallet inventory that may be locked by
        # resting orders. Adding `locked` double-counts SELL inventory and
        # inflates equity exactly when risk reporting must be conservative.
        total = dec(b.get("total"))
        if abs(total) <= Decimal("0.00000001"):
            continue
        px = spot_prices.get(coin)
        usd = total * px if px is not None else None
        if coin == "vUSDC":
            spot_usdc = total
        if usd is not None:
            spot_equity += usd
        spot_assets.append(
            {
                "coin": coin,
                "symbol": spot_symbols.get(coin),
                "total": float(total),
                "locked": float(locked),
                "price_usd": as_float(px),
                "value_usd": as_float(usd),
                "quality": "PRICED" if px is not None else "NO_PRICE",
            }
        )

    perps_balances = []
    perps_vusdc = Decimal("0")
    for b in _list_from_data(raw.get("perps_balances"), "balances"):
        coin = str(b.get("coin", ""))
        total = dec(b.get("total"))
        if coin == "vUSDC":
            perps_vusdc = total
        perps_balances.append(
            {
                "coin": coin,
                "total": float(total),
                "price_usd": float(dec(b.get("price"), Decimal("1"))),
                "collateral": float(dec(b.get("collateral"))),
            }
        )

    perps_state = _extract_data(raw.get("perps_state")) if raw.get("perps_state") else {}
    perps_account_value = dec(perps_state.get("av")) if isinstance(perps_state, dict) else Decimal("0")

    positions = []
    unrealized_total = Decimal("0")
    for p in _list_from_data(raw.get("perps_positions"), "positions"):
        symbol = str(p.get("symbol", ""))
        size = dec(p.get("size"))
        mark = _price_from_ticker(perps_tickers.get(symbol, {}))
        entry = dec(p.get("avgEntryPrice"))
        side = "LONG" if size > 0 else "SHORT" if size < 0 else "FLAT"
        unrealized = Decimal("0")
        if mark > 0 and entry > 0 and size != 0:
            unrealized = (mark - entry) * size
            unrealized_total += unrealized
        positions.append(
            {
                "symbol": symbol,
                "side": side,
                "size": float(size),
                "entry_price": float(entry),
                "mark_price": as_float(mark if mark > 0 else None),
                "initial_margin_usd": float(dec(p.get("initialMargin"))),
                "realized_pnl_field_usd": float(dec(p.get("realizedPnL"))),
                "unrealized_pnl_calc_usd": float(unrealized),
                "leverage": p.get("leverage"),
            }
        )
    state_positions = _state_position_records(raw.get("perps_state"))
    truth = _position_truth(
        raw_positions=raw.get("perps_positions"),
        raw_state=raw.get("perps_state"),
        endpoint_positions=positions,
        state_positions=state_positions,
    )
    warnings.extend(truth.get("warnings") or [])

    start_ms = int(window.start.timestamp() * 1000)
    end_ms = int(window.end.timestamp() * 1000)
    api_trades = []
    api_fee_warnings: list[str] = []
    for market, payload in (("perps", raw.get("perps_trades")), ("spot", raw.get("spot_trades"))):
        for t in _list_from_data(payload, "trades"):
            ts = int(dec(t.get("time")))
            if start_ms <= ts < end_ms:
                notional = dec(t.get("price")) * dec(t.get("quantity"))
                fee_coin = str(t.get("feeCoin") or "vUSDC")
                fee_amount = dec(t.get("fee"))
                fee_px = Decimal("1") if fee_coin == "vUSDC" else spot_prices.get(fee_coin)
                fee_usd = fee_amount * fee_px if fee_px is not None else Decimal("0")
                if fee_px is None:
                    api_fee_warnings.append(f"fee coin price missing:{fee_coin}")
                api_trades.append(
                    {
                        "market": market,
                        "symbol": t.get("symbol"),
                        "side": t.get("side"),
                        "time": ts,
                        "notional_usd": float(notional),
                        "fee_coin": fee_coin,
                        "fee_amount": float(fee_amount),
                        "fee_usd": float(fee_usd),
                        "is_maker": bool(t.get("isMaker")),
                    }
                )

    api_trade_volume = sum(dec(t["notional_usd"]) for t in api_trades)
    api_trade_fees = sum(dec(t["fee_usd"]) for t in api_trades)
    warnings.extend(sorted(set(api_fee_warnings)))
    api_funding = Decimal("0")
    for f in _list_from_data(raw.get("perps_fundings"), "fundings"):
        ts = int(dec(f.get("timestamp")))
        if start_ms <= ts < end_ms:
            api_funding += dec(f.get("fundingFee"))

    fee_rate = _extract_data(raw.get("fee_rate")) if raw.get("fee_rate") else {}
    total_equity = spot_equity + perps_account_value
    quality = "OK" if not missing else "PARTIAL"
    if len(missing) == len(paths):
        quality = "API_UNAVAILABLE"

    return {
        "quality": quality,
        "address": f"{address[:10]}...{address[-6:]}",
        "account_value": {
            "spot_equity_usd": float(spot_equity),
            "perps_account_value_usd": float(perps_account_value),
            "total_equity_usd": float(total_equity),
            "spot_vusdc_usd": float(spot_usdc),
            "perps_vusdc_usd": float(perps_vusdc),
            "free_usd_total": float(spot_usdc + perps_vusdc),
            "perps_unrealized_pnl_calc_usd": float(unrealized_total),
        },
        "assets": {"spot": spot_assets, "perps_balances": perps_balances, "perps_positions": positions},
        "position_truth": truth,
        "api_weekly_activity": {
            "trade_count_returned_in_window": len(api_trades),
            "trade_volume_returned_usd": float(api_trade_volume),
            "trade_fees_returned_usd": float(api_trade_fees),
            "funding_returned_usd": float(api_funding),
            "note": "API trade endpoints may be paginated; ledger remains primary for full-week totals.",
        },
        "fee_rate": fee_rate if isinstance(fee_rate, dict) else {},
        "warnings": warnings,
    }


def evaluate(
    window: WeekWindow,
    ledger: dict[str, Any],
    account: dict[str, Any],
    *,
    official_dashboard: dict[str, Any] | None = None,
    target_volume: Decimal = TARGET_WEEKLY_VOLUME_USD,
    target_win_rate: Decimal = TARGET_WIN_RATE,
    target_ratio: Decimal = TARGET_VOLUME_FEE_RATIO,
) -> dict[str, Any]:
    reasons: list[str] = []
    warnings: list[str] = []
    ledger_volume = dec((ledger.get("volume") or {}).get("raw_total_usd"))
    volume = ledger_volume
    canonical_source = "internal_ledger"
    official_volume = Decimal("0")
    if official_dashboard and official_dashboard.get("quality") == "OK" and official_dashboard.get("canonical"):
        official_volume = dec((official_dashboard.get("volume") or {}).get("total_usd"))
        if official_volume > 0:
            volume = official_volume
            canonical_source = "official_dashboard"
    pnl = dec((ledger.get("pnl") or {}).get("realized_net_usd"))
    ledger_ratio = dec((ledger.get("ratios") or {}).get("volume_to_fee"), Decimal("-1"))
    fees = dec((ledger.get("costs") or {}).get("fees_usd"))
    ratio = (volume / fees) if fees > 0 else ledger_ratio
    rts = ledger.get("rts") or {}
    win_rate_value = rts.get("win_rate")
    win_rate = dec(win_rate_value, Decimal("-1")) if win_rate_value is not None else None

    if ledger.get("quality") != "OK":
        reasons.append("ledger_not_ok")
    if account.get("quality") not in ("OK", "DISABLED"):
        reasons.append("account_api_not_ok")
    if volume < target_volume:
        reasons.append("weekly_volume_below_target")
    if win_rate is None:
        reasons.append("weekly_win_rate_missing")
    elif win_rate < target_win_rate:
        reasons.append("weekly_win_rate_below_target")
    if pnl < 0:
        reasons.append("realized_pnl_negative")
    if ratio < target_ratio and ratio >= 0:  # ponytail: skip check when no fee data (ratio=-1 or None)
        reasons.append("volume_fee_ratio_below_target")
    # --- E1 Profit Engine → E2 Volume Engine coverage check (No-Loss Guarantee) ---
    coverage = ledger.get("coverage") or {}
    if not coverage.get("e1_covers_e2_fees", False):
        reasons.append("e1_profit_does_not_cover_e2_fees")
    if not coverage.get("combined_no_loss", False):
        reasons.append("combined_pnl_negative")
    if (ledger.get("fills") or {}).get("count", 0) == 0:
        warnings.append("no_fills_this_window")
    if (ledger.get("rts") or {}).get("count", 0) == 0:
        warnings.append("no_closed_rts_this_window")
    if canonical_source == "official_dashboard" and ledger_volume > volume:
        warnings.append("official_dashboard_lower_than_internal_ledger")
    if official_dashboard and official_dashboard.get("quality") not in (None, "OK"):
        warnings.extend(official_dashboard.get("warnings") or [])

    hard_fail = bool(reasons)
    status = "FAIL" if hard_fail else "PASS"
    return {
        "status": status,
        "reasons": reasons,
        "warnings": warnings,
        "targets": {
            "weekly_volume_usd": float(target_volume),
            "weekly_win_rate_min": float(target_win_rate),
            "volume_fee_ratio_min": float(target_ratio),
            "snapshot_boundary": "Saturday 07:00 WIB / Saturday 00:00 UTC",
        },
        "progress": {
            "elapsed_hours": round((min(now_utc(), window.end) - window.start).total_seconds() / 3600, 4),
            "remaining_hours": round(max(0.0, (window.end - now_utc()).total_seconds() / 3600), 4),
            "weekly_volume_pct": float(volume / target_volume) if target_volume > 0 else None,
            "canonical_volume_usd": float(volume),
            "canonical_volume_source": canonical_source,
            "internal_ledger_volume_usd": float(ledger_volume),
            "win_rate": float(win_rate) if win_rate is not None and win_rate >= 0 else None,
            "volume_fee_ratio": float(ratio) if ratio >= 0 else None,
            "realized_pnl_usd": float(pnl),
            "e1_realized_pnl": float(coverage.get("e1_realized_pnl", 0) if isinstance(coverage, dict) else 0),
            "e1_fees_usd": float(coverage.get("e1_fees_usd", 0) if isinstance(coverage, dict) else 0),
            "e2_realized_pnl": float(coverage.get("e2_realized_pnl", 0) if isinstance(coverage, dict) else 0),
            "e2_fees_usd": float(coverage.get("e2_fees_usd", 0) if isinstance(coverage, dict) else 0),
            "e1_covers_e2_fees": bool(coverage.get("e1_covers_e2_fees", False) if isinstance(coverage, dict) else False),
            "e1_covers_all_fees": bool(coverage.get("e1_covers_all_fees", False) if isinstance(coverage, dict) else False),
            "combined_no_loss": bool(coverage.get("combined_no_loss", False) if isinstance(coverage, dict) else False),
        },
    }


def _wilson_lower(wins: int, n: int, z: float = 1.96) -> float:
    """Wilson score lower bound for a binomial proportion (95% by default)."""
    if n <= 0:
        return 0.0
    p = wins / n
    denom = 1.0 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return max(0.0, (centre - margin) / denom)


def evaluate_e2dir_promotion(db_path: Path = DEFAULT_DB, now: datetime | None = None) -> dict[str, Any]:
    """Explicit paper→live promote gate for E2Dir funding-squeeze.

    READY only when fresh (last PROMOTE_FRESH_HOURS) signals satisfy ALL:
      n >= PROMOTE_MIN_N, Wilson-lower(WR) >= PROMOTE_WILSON_FLOOR, avg PnL > 0.
    Does NOT flip live — emits verdict + the operator command to promote.
    """
    now = now or now_utc()
    cutoff = (now - timedelta(hours=PROMOTE_FRESH_HOURS)).astimezone(UTC).isoformat()
    out: dict[str, Any] = {
        "ready": False,
        "n": 0,
        "wr": None,
        "wilson_lower": None,
        "avg_pnl_usd": None,
        "total_pnl_usd": None,
        "fresh_hours": PROMOTE_FRESH_HOURS,
        "criteria": {
            "min_n": PROMOTE_MIN_N,
            "wilson_lower_floor": PROMOTE_WILSON_FLOOR,
            "ev_after_fee_positive": True,
        },
        "blockers": [],
        "promote_command": "set TE_E2_DIR_LIVE=1 in scripts/watchdog_twin.sh then restart watchdog",
    }
    try:
        con = sqlite3.connect(str(db_path))
        try:
            rows = con.execute(
                "SELECT pnl FROM e2_dir_signals WHERE opened_ts >= ?", (cutoff,)
            ).fetchall()
        finally:
            con.close()
    except Exception as exc:  # ponytail: DB missing/locked → not ready, surface reason
        out["blockers"].append(f"db_error:{exc}")
        return out
    pnls = [float(r[0]) for r in rows if r[0] is not None]
    n = len(pnls)
    out["n"] = n
    if n == 0:
        out["blockers"].append("no_fresh_signals")
        return out
    wins = sum(1 for p in pnls if p > 0)
    total = sum(pnls)
    avg = total / n
    wl = _wilson_lower(wins, n)
    out["wr"] = round(wins / n, 4)
    out["wilson_lower"] = round(wl, 4)
    out["avg_pnl_usd"] = round(avg, 6)
    out["total_pnl_usd"] = round(total, 6)
    if n < PROMOTE_MIN_N:
        out["blockers"].append("n_below_min")
    if wl < PROMOTE_WILSON_FLOOR:
        out["blockers"].append("wilson_lower_below_floor")
    if avg <= 0:
        out["blockers"].append("ev_not_positive")
    out["ready"] = not out["blockers"]
    return out


def detect_early_loss(db_path: Path = DEFAULT_DB, now: datetime | None = None) -> dict[str, Any]:
    """Deteksi kerugian SANGAT DINI — window pendek (default 60m), per-engine + per-pair +
    velocity (akselerasi). Alert SEBELUM daily-loss cap tercapai, agar bisa antisipasi:
      - window_loss: total PnL window < -floor
      - pair_bleeding: ada pair rugi > pair_floor (tangkap 1 pair bleeder dini)
      - loss_accelerating: rugi window-ini lebih buruk dari window-sebelumnya
    Dipanggil tiap siklus monitor-eval → repair/pause dini. READ-ONLY (tak trade)."""
    now = now or now_utc()
    w_start = (now - timedelta(minutes=EARLY_LOSS_WINDOW_MIN)).astimezone(UTC).isoformat()
    p_start = (now - timedelta(minutes=2 * EARLY_LOSS_WINDOW_MIN)).astimezone(UTC).isoformat()
    out: dict[str, Any] = {
        "alert": False, "reasons": [], "window_min": EARLY_LOSS_WINDOW_MIN,
        "recent_pnl_usd": None, "prior_pnl_usd": None, "by_engine": {}, "worst_pair": None,
        "floors": {"window_usd": EARLY_LOSS_USD_FLOOR, "pair_usd": EARLY_LOSS_PAIR_FLOOR},
    }
    try:
        con = sqlite3.connect(str(db_path))
        con.row_factory = sqlite3.Row
        try:
            recent = con.execute(
                "SELECT engine, pair, CAST(net_pnl AS REAL) AS p FROM rts WHERE ts_close>=?",
                (w_start,)).fetchall()
            prow = con.execute(
                "SELECT COALESCE(SUM(CAST(net_pnl AS REAL)),0) FROM rts WHERE ts_close>=? AND ts_close<?",
                (p_start, w_start)).fetchone()
        finally:
            con.close()
    except Exception as exc:
        out["reasons"].append(f"db_error:{exc}")
        return out
    rec = sum((r["p"] or 0.0) for r in recent)
    prior = float(prow[0] or 0.0) if prow else 0.0
    out["recent_pnl_usd"] = round(rec, 4)
    out["prior_pnl_usd"] = round(prior, 4)
    eng: dict[str, float] = {}
    pair: dict[str, float] = {}
    for r in recent:
        eng[r["engine"]] = eng.get(r["engine"], 0.0) + (r["p"] or 0.0)
        pair[r["pair"]] = pair.get(r["pair"], 0.0) + (r["p"] or 0.0)
    out["by_engine"] = {k: round(v, 4) for k, v in eng.items()}
    if pair:
        wp, wpnl = min(pair.items(), key=lambda kv: kv[1])
        out["worst_pair"] = {"pair": wp, "pnl_usd": round(wpnl, 4)}
        if wpnl < -EARLY_LOSS_PAIR_FLOOR:
            out["reasons"].append(f"pair_bleeding:{wp}={wpnl:.2f}")
    if rec < -EARLY_LOSS_USD_FLOOR:
        out["reasons"].append(f"window_loss={rec:.2f}")
    if rec < 0 and rec < prior - EARLY_LOSS_USD_FLOOR:
        out["reasons"].append(f"loss_accelerating recent={rec:.2f} prior={prior:.2f}")
    out["alert"] = bool(out["reasons"])
    return out


def _parse_ts(value: Any) -> datetime | None:
    """Parse ISO or sqlite UTC timestamp into aware UTC datetime."""
    if not value:
        return None
    text = str(value).strip()
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _age_minutes(value: Any, now: datetime) -> float | None:
    """Return timestamp age in minutes."""
    dt = _parse_ts(value)
    if dt is None:
        return None
    return max(0.0, (now.astimezone(UTC) - dt).total_seconds() / 60)


def build_monitor_risk(
    ledger: dict[str, Any],
    account: dict[str, Any],
    official_dashboard: dict[str, Any],
    early_loss: dict[str, Any],
    verdict: dict[str, Any],
    now: datetime | None = None,
    telegram_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute sensitive operational risk score from independent evidence."""
    now = now or now_utc()
    signals: list[dict[str, Any]] = []

    def add(name: str, points: int, evidence: dict[str, Any] | None = None) -> None:
        signals.append({"name": name, "points": points, "evidence": evidence or {}})

    ledger_quality = ledger.get("quality")
    account_quality = account.get("quality")
    if ledger_quality != "OK":
        add("ledger_degraded", 30, {"quality": ledger_quality})
    if account_quality not in ("OK", "DISABLED"):
        add("account_api_degraded", 18, {"quality": account_quality})
    if early_loss.get("alert"):
        add("early_loss_alert", 28, {"reasons": early_loss.get("reasons") or []})

    fills = ledger.get("fills") or {}
    rts = ledger.get("rts") or {}
    fill_count = int(fills.get("count") or 0)
    # `rts.count` = RT TERAUDIT (dipakai metrik kinerja). Alarm gap menanyakan hal
    # BERBEDA: "apakah RT sedang DICATAT sama sekali?" → pakai hitungan mentah
    # (teraudit + yang dikeluarkan penjaga). Menyamakan keduanya membuat penjaga
    # integritas memicu alarm palsu: terukur 30-Sep, rt_count 325→0 menaikkan
    # skor risiko 60→90 (RED) padahal pencatatan RT tetap berjalan.
    rt_count = int(rts.get("count") or 0)
    rt_count_raw = rt_count + int(rts.get("excluded_unverifiable") or 0)
    fill_age = _age_minutes(fills.get("last_ts"), now)
    if fill_count == 0:
        add("no_weekly_fills", 16, {})
    elif fill_age is not None and fill_age > SENSITIVE_STALE_FILL_MIN:
        add("stale_last_fill", 22, {"age_min": round(fill_age, 2)})
    if fill_count >= SENSITIVE_FILL_RT_GAP_MIN_FILLS and rt_count_raw == 0:
        add("fills_without_closed_rt", 30, {"fills": fill_count, "rts": rt_count_raw})

    recon = official_dashboard.get("reconciliation") or {}
    official_quality = official_dashboard.get("quality")
    delta = dec(recon.get("total_delta_usd"))
    multiple = dec(recon.get("ledger_over_official_multiple"), Decimal("0"))
    if official_quality not in (None, "OK", "MISSING"):
        add("official_dashboard_degraded", 12, {"quality": official_quality})
    if delta > Decimal("1000") and multiple >= SENSITIVE_OFFICIAL_DRIFT_MULTIPLE:
        add("official_ledger_drift", 20, {"delta_usd": float(delta), "multiple": float(multiple)})

    open_position_count = _account_open_position_count(account)
    truth = account.get("position_truth") or {}
    if open_position_count and (fill_age is None or fill_age > SENSITIVE_STALE_FILL_MIN):
        add("open_positions_with_stale_fills", 18, {"open_positions": open_position_count, "fill_age_min": fill_age})
    if isinstance(truth, dict) and truth.get("quality") in {"DISAGREE", "UNVERIFIED"}:
        add(
            "position_truth_not_verified",
            26,
            {
                "quality": truth.get("quality"),
                "positions_endpoint_count": truth.get("positions_endpoint_count"),
                "state_P_count": truth.get("state_P_count"),
            },
        )
    if verdict.get("status") == "FAIL":
        add("weekly_verdict_fail", 8, {"reasons": verdict.get("reasons") or []})
    if telegram_health and telegram_health.get("quality") == "DEGRADED":
        add(
            "telegram_alert_channel_degraded",
            18,
            {"verdict": telegram_health.get("verdict")},
        )

    score = min(100, sum(int(s["points"]) for s in signals))
    if score >= 70:
        level = "RED"
    elif score >= 45:
        level = "ORANGE"
    elif score >= 20:
        level = "YELLOW"
    else:
        level = "GREEN"
    return {
        "score": score,
        "level": level,
        "signals": signals,
        "fill_age_min": None if fill_age is None else round(fill_age, 2),
        "method": "additive bounded score; independent evidence only; no live trade action",
    }


def read_halt_status(
    safety_halt_file: Path = SAFETY_HALT_FILE,
    pnl_halt_file: Path = PNL_HALT_FILE,
) -> dict[str, Any]:
    for kind, path in (("SAFETY_HALT", safety_halt_file), ("PNL_HALT", pnl_halt_file)):
        if path.exists():
            detail: Any = None
            try:
                detail = json.loads(path.read_text())
            except Exception:
                detail = path.read_text(errors="ignore")[:500]
            return {"active": True, "kind": kind, "path": str(path), "detail": detail}
    return {"active": False, "kind": None, "path": None, "detail": None}


def read_live_kill_status(kill_files: dict[str, Path] = LIVE_KILL_FILES) -> dict[str, Any]:
    """Report native live kill switches; does not clear or mutate them."""
    active = {name: str(path) for name, path in kill_files.items() if path.exists()}
    return {
        "active": bool(active),
        "active_files": sorted(active),
        "paths": active,
    }


def read_telegram_health(path: Path = TELEGRAM_HEALTH_FILE) -> dict[str, Any]:
    if not path.exists():
        return {"quality": "MISSING", "path": str(path), "verdict": "no_health_file"}
    try:
        data = json.loads(path.read_text())
        verdict = str(data.get("verdict") or "unknown")
        return {
            "quality": "OK" if verdict == "ok" else "DEGRADED",
            "path": str(path),
            "verdict": verdict,
            "token_present": bool(data.get("token_present")),
            "token_format_ok": bool(data.get("token_format_ok")),
            "chat_present": bool(data.get("chat_present")),
            "http_status": ((data.get("getMe") or {}).get("http_status")
                            if isinstance(data.get("getMe"), dict) else None),
        }
    except Exception as exc:
        return {
            "quality": "DEGRADED",
            "path": str(path),
            "verdict": "unreadable_health_file",
            "error": type(exc).__name__,
        }


def build_repair_plan(
    monitor_risk: dict[str, Any],
    early_loss: dict[str, Any],
    halt_status: dict[str, Any] | None = None,
    live_kills: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build non-trading auto-repair plan from monitor risk signals."""
    names = {str(s.get("name")) for s in monitor_risk.get("signals") or []}
    actions: list[dict[str, Any]] = []
    watchdog_restart = False
    halt_active = bool((halt_status or {}).get("active"))
    if halt_active:
        actions.append({
            "type": "HALT_ACTIVE_NO_RESTART",
            "severity": "HIGH",
            "reason": [str((halt_status or {}).get("kind") or "HALT_ACTIVE")],
            "safe": "restart suppressed until operator clears halt file",
        })
    if (live_kills or {}).get("active"):
        actions.append({
            "type": "LIVE_KILL_ACTIVE_NO_TRADING",
            "severity": "HIGH",
            "reason": list((live_kills or {}).get("active_files") or []),
            "safe": "live entry intentionally blocked; requires explicit GO-LIVE decision to clear",
        })
    position_reconcile_required = bool(
        names & {"open_positions_with_stale_fills", "position_truth_not_verified"}
    )
    if position_reconcile_required:
        actions.append({
            "type": "OPERATOR_POSITION_RECONCILIATION_REQUIRED",
            "severity": "HIGH",
            "reason": sorted(names & {"open_positions_with_stale_fills", "position_truth_not_verified"}),
            "safe": "report only; no order placement or exposure change",
        })
    restart_reasons = names & {"fills_without_closed_rt"}
    if "stale_last_fill" in names and not position_reconcile_required:
        actions.append({
            "type": "STALE_FILL_OBSERVED_NO_RESTART",
            "severity": "MEDIUM",
            "reason": ["stale_last_fill"],
            "safe": "stale fill alone does not prove engine failure; refresh monitor/accelerator before live probe",
        })
    if restart_reasons:
        if not halt_active and not position_reconcile_required:
            watchdog_restart = True
            actions.append({
                "type": "WATCHDOG_RESTART_SIGNAL",
                "severity": "HIGH",
                "reason": sorted(restart_reasons),
                "safe": "signal file only; watchdog still honors halt files",
            })
        elif position_reconcile_required:
            actions.append({
                "type": "RESTART_SUPPRESSED_POSITION_RECONCILE_FIRST",
                "severity": "HIGH",
                "reason": sorted(restart_reasons),
                "safe": "restart cannot resolve open-position truth; operator reconciliation required first",
            })
    if early_loss.get("alert"):
        actions.append({
            "type": "PAUSE_OR_BLOCK_BLEEDING_ENGINE",
            "severity": "HIGH",
            "reason": early_loss.get("reasons") or [],
            "worst_pair": early_loss.get("worst_pair"),
            "safe": "recommendation/report only; no order placement",
        })
    if "official_ledger_drift" in names:
        actions.append({
            "type": "REFRESH_OFFICIAL_DASHBOARD_SNAPSHOT",
            "severity": "MEDIUM",
            "reason": ["official_ledger_drift"],
            "safe": "data refresh only",
        })
    if "account_api_degraded" in names:
        actions.append({
            "type": "CHECK_API_CONNECTIVITY",
            "severity": "MEDIUM",
            "reason": ["account_api_degraded"],
            "safe": "read-only diagnostic",
        })
    return {
        "mode": "READ_ONLY_REPAIR_PLAN",
        "watchdog_restart_signal": watchdog_restart,
        "actions": actions,
        "operator_required_for_live_trading_changes": True,
    }


def build_report(
    *,
    db_path: Path = DEFAULT_DB,
    env_path: Path = DEFAULT_ENV,
    out_dir: Path = DEFAULT_OUT,
    no_api: bool = False,
    at: datetime | None = None,
    api: SodexApi | None = None,
    target_volume: Decimal = TARGET_WEEKLY_VOLUME_USD,
    target_win_rate: Decimal = TARGET_WIN_RATE,
    target_ratio: Decimal = TARGET_VOLUME_FEE_RATIO,
) -> dict[str, Any]:
    ts = at or now_utc()
    window = week_window(ts)
    address = os.environ.get("SODEX_ADDRESS", "").strip() or read_env_value(env_path, "SODEX_ADDRESS")
    ledger = aggregate_ledger(db_path, window)
    account = aggregate_account(address, window, api=api, no_api=no_api)
    official_dashboard = load_official_dashboard_snapshot(out_dir, window, ledger)
    verdict = evaluate(
        window,
        ledger,
        account,
        official_dashboard=official_dashboard,
        target_volume=target_volume,
        target_win_rate=target_win_rate,
        target_ratio=target_ratio,
    )
    early_loss = detect_early_loss(db_path, ts)
    telegram_health = read_telegram_health()
    monitor_risk = build_monitor_risk(
        ledger, account, official_dashboard, early_loss, verdict, ts, telegram_health
    )
    halt_status = read_halt_status()
    live_kills = read_live_kill_status()
    repair_plan = build_repair_plan(monitor_risk, early_loss, halt_status, live_kills)
    return {
        "schema_version": 1,
        "ts": ts.astimezone(UTC).isoformat(),
        "project": "anantara-sakti/sodex-farming",
        "mode": "READ_ONLY_MONITORING_EVALUATION",
        "window": {
            "start": window.start.isoformat(),
            "end": window.end.isoformat(),
            "label": window.label,
            **week_display(window),
        },
        "verdict": verdict,
        "early_loss": early_loss,
        "monitor_risk": monitor_risk,
        "repair_plan": repair_plan,
        "halt_status": halt_status,
        "live_kills": live_kills,
        "telegram_health": telegram_health,
        "e2dir_promotion": evaluate_e2dir_promotion(db_path, ts),
        "official_dashboard": official_dashboard,
        "ledger": ledger,
        "account": account,
        "output_dir": str(out_dir),
        "scientific_notes": [
            "Official SoDEX dashboard/points data is canonical for volume credited by SoDEX when present and window-matched.",
            "Ledger fills/rts are internal audit data for bot fills, fees, realized PnL, RT count, and discrepancy checks.",
            "API account data is primary for current assets, open positions, free USD, and account value.",
            "When API or DB is unavailable, the report marks quality degraded instead of inventing values.",
            "No signed endpoint, order placement, order cancel, or trading command is used by this script.",
        ],
    }


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def persist_report(report: dict[str, Any], out_dir: Path = DEFAULT_OUT) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    latest = out_dir / "latest.json"
    history = out_dir / "history.jsonl"
    payload = json.dumps(report, indent=2, sort_keys=True)
    atomic_write(latest, payload)
    with history.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, sort_keys=True) + "\n")
    return latest, history


def format_text(report: dict[str, Any]) -> str:
    verdict = report["verdict"]
    official = report.get("official_dashboard") or {}
    ledger = report["ledger"]
    account = report["account"]
    volume = ledger.get("volume", {})
    official_volume = official.get("volume") or {}
    recon = official.get("reconciliation") or {}
    pnl = ledger.get("pnl", {})
    ratios = ledger.get("ratios", {})
    rts = ledger.get("rts", {})
    value = account.get("account_value", {})
    monitor_risk = report.get("monitor_risk") or {}
    repair_plan = report.get("repair_plan") or {}
    live_kills = report.get("live_kills") or {}
    telegram_health = report.get("telegram_health") or {}
    lines = [
        "SODEX MONITORING & EVALUASI (READ-ONLY)",
        f"ts_utc        : {report['ts']}",
        f"window        : {report['window'].get('range')} ({report['window'].get('weekly_label')})",
        f"snapshot      : {report['window'].get('snapshot_wib')}",
        f"status        : {verdict['status']}",
        f"reasons       : {', '.join(verdict['reasons']) if verdict['reasons'] else '-'}",
        f"risk_score    : {monitor_risk.get('score', 0)} / {monitor_risk.get('level', 'GREEN')}",
        f"repair_signal : {repair_plan.get('watchdog_restart_signal', False)}",
        f"ledger_quality: {ledger.get('quality')}",
        f"api_quality   : {account.get('quality')}",
        f"telegram      : {telegram_health.get('quality', 'MISSING')} / {telegram_health.get('verdict', '-')}",
        f"live_kills    : {', '.join(live_kills.get('active_files') or []) if live_kills.get('active') else '-'}",
        "",
        "OFFICIAL SODEX DASHBOARD VOLUME",
        f"quality             : {official.get('quality', 'MISSING')}",
        f"source              : {official.get('source', '-')}",
        f"official_total_usd  : {official_volume.get('total_usd', 0):,.2f}",
        f"official_spot_usd   : {official_volume.get('spot_usd', 0):,.2f}",
        f"official_futures_usd: {official_volume.get('perps_usd', 0):,.2f}",
        "",
        "INTERNAL LEDGER AUDIT",
        f"ledger_total_usd    : {volume.get('raw_total_usd', 0):,.2f}",
        f"ledger_weighted_usd : {volume.get('weighted_total_usd', 0):,.2f}",
        f"ledger_spot_usd     : {volume.get('spot_usd', 0):,.2f}",
        f"ledger_perps_usd    : {volume.get('perps_usd', 0):,.2f}",
        f"delta_total_usd     : {recon.get('total_delta_usd', 0):,.2f}",
        f"realized_pnl_usd    : {pnl.get('realized_net_usd', 0):+,.6f}",
        f"fees_usd            : {(ledger.get('costs') or {}).get('fees_usd', 0):,.6f}",
        f"volume_to_fee_ratio : 1:{ratios.get('volume_to_fee', 0) or 0:,.2f}",
        f"rt_count/win_rate   : {rts.get('count', 0)} / {((rts.get('win_rate') or 0) * 100):.2f}%",
        "",
        "REAL ACCOUNT NOW",
        f"total_equity_usd    : {value.get('total_equity_usd', 0):,.6f}",
        f"free_usd_total      : {value.get('free_usd_total', 0):,.6f}",
        f"spot_equity_usd     : {value.get('spot_equity_usd', 0):,.6f}",
        f"perps_account_value : {value.get('perps_account_value_usd', 0):,.6f}",
        f"open_positions      : {_account_open_position_count(account)}",
    ]
    if monitor_risk.get("signals"):
        lines.extend(["", "SENSITIVE MONITOR SIGNALS"])
        for sig in (monitor_risk.get("signals") or [])[:8]:
            lines.append(f"- {sig.get('name')} (+{sig.get('points')}) {sig.get('evidence') or {}}")
    if repair_plan.get("actions"):
        lines.extend(["", "AUTO-REPAIR PLAN"])
        for act in (repair_plan.get("actions") or [])[:6]:
            lines.append(f"- {act.get('type')} [{act.get('severity')}] {act.get('reason')}")
    warnings = list(ledger.get("warnings") or []) + list(account.get("warnings") or []) + list(verdict.get("warnings") or [])
    if warnings:
        lines.extend(["", "WARNINGS", *[f"- {w}" for w in warnings]])
    return "\n".join(lines)


def format_telegram_report(report: dict[str, Any]) -> str:
    verdict = report.get("verdict") or {}
    official = report.get("official_dashboard") or {}
    ledger = report.get("ledger") or {}
    account = report.get("account") or {}
    volume = ledger.get("volume") or {}
    official_volume = official.get("volume") or {}
    recon = official.get("reconciliation") or {}
    pnl = ledger.get("pnl") or {}
    costs = ledger.get("costs") or {}
    ratios = ledger.get("ratios") or {}
    rts = ledger.get("rts") or {}
    value = account.get("account_value") or {}
    open_position_count = _account_open_position_count(account)
    monitor_risk = report.get("monitor_risk") or {}
    repair_plan = report.get("repair_plan") or {}
    live_kills = report.get("live_kills") or {}
    reasons = verdict.get("reasons") or []
    progress = verdict.get("progress") or {}
    weekly_pct = progress.get("weekly_volume_pct")
    weekly_pct_text = "-" if weekly_pct is None else f"{float(weekly_pct) * 100:.1f}%"
    ratio = ratios.get("volume_to_fee")
    ratio_text = "-" if ratio is None else f"1:{float(ratio):,.0f}"
    official_ratio = progress.get("volume_fee_ratio")
    official_ratio_text = "-" if official_ratio is None else f"1:{float(official_ratio):,.0f}"
    win_rate = rts.get("win_rate")
    win_rate_text = "-" if win_rate is None else f"{float(win_rate) * 100:.2f}%"
    ts = str(report.get("ts", "?"))[:19].replace("T", " ")
    window = report.get("window") or {}
    display = week_display_from_report_window(window)
    official_ok = official.get("quality") == "OK" and official.get("canonical")

    lines = [
        "SoDEX Monitoring & Evaluasi",
        f"ts UTC: {ts}",
        f"periode: {display['range']} ({display['weekly_label']})",
        f"snapshot: {display['snapshot_wib']}",
        f"status: {verdict.get('status', '?')}",
        f"reason: {', '.join(reasons) if reasons else '-'}",
        f"risk: {monitor_risk.get('level', 'GREEN')} {monitor_risk.get('score', 0)}/100",
        f"repair signal: {repair_plan.get('watchdog_restart_signal', False)}",
        f"live kills: {', '.join(live_kills.get('active_files') or []) if live_kills.get('active') else '-'}",
        f"quality: official={official.get('quality', 'MISSING')} ledger={ledger.get('quality', '?')} api={account.get('quality', '?')}",
        "",
        "Official SoDEX dashboard",
        f"official total: ${float(official_volume.get('total_usd') or 0):,.0f}" if official_ok else "official total: unavailable",
        f"spot/futures: ${float(official_volume.get('spot_usd') or 0):,.0f} / ${float(official_volume.get('perps_usd') or 0):,.0f}" if official_ok else "spot/futures: unavailable",
        f"target progress: {weekly_pct_text}",
        f"official volume/fee: {official_ratio_text}",
        "",
        "Internal ledger audit",
        f"ledger total: ${float(volume.get('raw_total_usd') or 0):,.0f}",
        f"ledger weighted: ${float(volume.get('weighted_total_usd') or 0):,.0f}",
        f"ledger spot/perps: ${float(volume.get('spot_usd') or 0):,.0f} / ${float(volume.get('perps_usd') or 0):,.0f}",
        f"delta ledger-official: ${float(recon.get('total_delta_usd') or 0):,.0f}" if official_ok else "delta ledger-official: unavailable",
        f"realized PnL: ${float(pnl.get('realized_net_usd') or 0):+,.6f}",
        f"fees: ${float(costs.get('fees_usd') or 0):,.6f}",
        f"ledger volume/fee: {ratio_text}",
        f"RT/win rate: {int(rts.get('count') or 0)} / {win_rate_text}",
        "",
        "Account now",
        f"total equity: ${float(value.get('total_equity_usd') or 0):,.6f}",
        f"free USD: ${float(value.get('free_usd_total') or 0):,.6f}",
        f"open positions: {open_position_count}",
    ]
    if monitor_risk.get("signals"):
        top = monitor_risk.get("signals")[:4]
        lines += ["", "Sensitive signals:"] + [
            f"- {s.get('name')} (+{s.get('points')})" for s in top
        ]
    if repair_plan.get("actions"):
        lines += ["", "Auto-repair plan:"] + [
            f"- {a.get('type')} [{a.get('severity')}]" for a in repair_plan.get("actions")[:4]
        ]
    el = report.get("early_loss") or {}
    if el.get("alert"):
        lines += ["", "🚨 EARLY-LOSS ALERT (deteksi dini)",
                  f"window {el.get('window_min')}m: recent=${el.get('recent_pnl_usd')} prior=${el.get('prior_pnl_usd')}",
                  f"by_engine: {el.get('by_engine')}",
                  f"worst_pair: {el.get('worst_pair')}",
                  f"reasons: {', '.join(el.get('reasons') or [])}"]
    elif el.get("recent_pnl_usd") is not None:
        lines += ["", f"early-loss: OK (recent ${el.get('recent_pnl_usd')}/{el.get('window_min')}m, no alert)"]
    promo = report.get("e2dir_promotion") or {}
    if promo:
        if promo.get("ready"):
            lines += ["", "🚀 E2Dir PROMOTE-READY (paper→live)",
                      f"n={promo.get('n')} WR={promo.get('wr')} wilson_lo={promo.get('wilson_lower')} avg=${promo.get('avg_pnl_usd')}",
                      f"action: {promo.get('promote_command')}"]
        else:
            lines += ["", f"E2Dir promote gate: n={promo.get('n')} wilson_lo={promo.get('wilson_lower')} "
                      f"avg=${promo.get('avg_pnl_usd')} blockers={', '.join(promo.get('blockers') or []) or '-'}"]
    warnings = (
        list(official.get("warnings") or [])
        + list(ledger.get("warnings") or [])
        + list(account.get("warnings") or [])
        + list(verdict.get("warnings") or [])
    )
    if warnings:
        lines.extend(["", "Warnings:"] + [f"- {w}" for w in warnings[:6]])
    return "\n".join(lines)[:3900]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SoDEX read-only monitoring and weekly evaluation")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--no-api", action="store_true", help="skip live API calls")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--no-persist", action="store_true", help="do not write latest/history files")
    parser.add_argument("--strict-exit", action="store_true", help="exit 2 when evaluation verdict is not PASS")
    parser.add_argument("--target-volume", type=Decimal, default=TARGET_WEEKLY_VOLUME_USD)
    parser.add_argument("--target-win-rate", type=Decimal, default=TARGET_WIN_RATE)
    parser.add_argument("--target-ratio", type=Decimal, default=TARGET_VOLUME_FEE_RATIO)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    started = time.time()
    report = build_report(
        db_path=args.db,
        env_path=args.env,
        out_dir=args.out_dir,
        no_api=args.no_api,
        target_volume=args.target_volume,
        target_win_rate=args.target_win_rate,
        target_ratio=args.target_ratio,
    )
    report["runtime_seconds"] = round(time.time() - started, 4)
    if not args.no_persist:
        latest, history = persist_report(report, args.out_dir)
        report["persisted"] = {"latest": str(latest), "history": str(history)}

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_text(report))
        if not args.no_persist:
            print(f"\nsaved_latest : {report['persisted']['latest']}")
    if args.strict_exit and report["verdict"]["status"] != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
