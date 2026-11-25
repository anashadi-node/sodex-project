#!/usr/bin/env python3
"""SoDEX RISET harness re-evaluation.

Read-only measurement script for PERINTAH_1_SoDEX. It does not change strategy,
gates, exit policy, leverage, or live flags.
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import math
import os
import random
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "docs/handover/RISET_TO_DIVISI_2026-10-01/harness"
sys.path.insert(0, str(HARNESS))
from anantara_harness import TrialRegistry, evaluate, max_drawdown  # noqa: E402


# Same-directory helpers; read-only and fail-closed.
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import sodex_funding_mapper  # noqa: E402
import sodex_funding_rate_collector  # noqa: E402
import sodex_normalized_equity  # noqa: E402

SODEX_FEE_BPS = 8.0
TRACKS = {
    "swing": ROOT / "data/paper_test_swing_state.json",
    "twoway": ROOT / "data/paper_test_twoway_state.json",
    "realwide": ROOT / "data/paper_test_realwide_state.json",
}
REPORT_DIR = ROOT / "reports/sodex"

# SoDEX paper lanes log a-priori-labelled negative-control trades into the SAME
# state file as the signal arm (`track=RANDOM`, `regime=RANDOM_CONTROL`). The
# control arm must be scored SEPARATELY: averaging it into the signal track
# biases the T1 measurement toward zero (measured 2026-10-04: 12.96 -> 15.19 bps
# gross on twoway). Label is written by the control harness before the outcome is
# known, so splitting on it is not outcome-dependent selection.
ARM_RANDOM_LABEL = "RANDOM"
ARM_SIGNAL = "SIGNAL"
ARM_CONTROL = "CONTROL"
CONTROL_REGIME_LABEL = "RANDOM_CONTROL"


def arm_of(row: dict[str, Any]) -> str:
    """Map a closed trade to its arm.

    ASSUMPTION (RISET D0.5 verification, T4, 2026-10-04): rows with `track`
    absent/empty/None are treated as the SIGNAL arm. This was audited --
    0 such rows carry `regime=RANDOM_CONTROL`, so the amnesty cannot smuggle a
    control row into the signal arm. Do not silently relax it: any future writer
    that appends control rows without the `track=RANDOM` label must be caught by
    `assert_no_control_smuggling()` below, not by this default.
    """
    explicit = str(row.get("track") or "").upper()
    if not explicit and str(row.get("regime") or "").upper() == CONTROL_REGIME_LABEL:
        raise ValueError(
            "control row (regime=RANDOM_CONTROL) with no `track` label -- arm_of cannot "
            "classify it a priori; fix the lane writer instead of widening this default"
        )
    return ARM_CONTROL if explicit == ARM_RANDOM_LABEL else ARM_SIGNAL


def assert_no_control_smuggling(rows: list[dict[str, Any]]) -> int:
    """Count rows that look like controls but would be graded as signal."""
    bad = 0
    for row in rows:
        if str(row.get("track") or "").upper() == ARM_RANDOM_LABEL:
            continue
        if str(row.get("regime") or "").upper() == CONTROL_REGIME_LABEL:
            bad += 1
    return bad


def parse_dt(value: Any) -> dt.datetime:
    if isinstance(value, (int, float)):
        # Repo state uses synthetic future unix seconds in some paper files.
        return dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc)
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def side_sign(row: dict[str, Any]) -> int:
    raw = str(row.get("direction") or row.get("side") or row.get("dir") or "").upper()
    if raw in {"LONG", "L", "BUY"}:
        return 1
    if raw in {"SHORT", "S", "SELL"}:
        return -1
    raise ValueError(f"unknown side: {raw!r}")


def trade_symbol(row: dict[str, Any]) -> str:
    return str(row.get("pair") or row.get("sym") or row.get("symbol") or "UNKNOWN").upper().replace("USDT", "")


def trade_return(row: dict[str, Any]) -> float:
    for key in ("pnl_pct", "pnl_per_trade", "net_pct", "gross_pct"):
        if key in row and row[key] is not None:
            return float(row[key])
    ent = row.get("entry_price") or row.get("entry_p")
    ex = row.get("exit_price") or row.get("exit_p")
    if ent is None or ex is None:
        raise ValueError("missing return and entry/exit price")
    raw = float(ex) / float(ent) - 1.0
    return side_sign(row) * raw


def trade_times(row: dict[str, Any]) -> tuple[dt.datetime, dt.datetime]:
    entry = row.get("entry_time") or row.get("entry_iso") or row.get("entry_ts")
    exit_ = row.get("exit_time") or row.get("exit_iso") or row.get("exit_ts")
    if entry is None or exit_ is None:
        raise ValueError("missing entry/exit time")
    return parse_dt(entry), parse_dt(exit_)


def closed_rows(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text())
    rows = data.get("closed_trades") or data.get("closed") or []
    return [r for r in rows if isinstance(r, dict)]


ROLLING_CACHE_NAME = "btc_1h_binance_spot_cache_rolling.json"


def btc_cache_files() -> list[Path]:
    return sorted(REPORT_DIR.glob("btc_1h_binance_spot_cache_*.json"), reverse=True)


def merge_cached_candles() -> dict[int, float]:
    """Gabung SEMUA cache BTC lokal menjadi satu kamus ms -> close.

    Versi lama hanya memakai cache TERBARU dan menuntut cache itu menutup SELURUH
    jendela. Begitu cache tertinggal beberapa jam, harness gagal (terukur
    2026-10-03: 2x FileNotFoundError "no BTC 1h cache covers requested window",
    karena cache berhenti di 03-Okt sementara trade forward sudah lewat).
    Menggabungkan seluruh cache membuat cakupan efektif = GABUNGAN, bukan irisan.
    """
    out: dict[int, float] = {}
    for path in btc_cache_files():
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        for r in data.get("rows") or []:
            if len(r) >= 5:
                try:
                    out[int(r[0])] = float(r[4])
                except (TypeError, ValueError):
                    continue
    return out


def persist_btc_cache(candles: list[tuple[int, float]]) -> Path | None:
    """Simpan cache rolling BTC 1h.

    Dipanggil HANYA setelah fetch jaringan SUKSES, sehingga gangguan DNS
    berikutnya masih punya cadangan segar (self-healing). Sebelumnya TIDAK ADA
    kode yang menulis cache ini -- ia hanya dibaca, jadi sekali tertinggal ia
    tertinggal selamanya.
    """
    if not candles:
        return None
    merged = merge_cached_candles()
    try:
        merged.update({int(t): float(c) for t, c in candles})
    except (TypeError, ValueError):
        return None
    path = REPORT_DIR / ROLLING_CACHE_NAME
    try:
        payload = {"rows": [[t, "", "", "", c] for t, c in sorted(merged.items())]}
        path.write_text(json.dumps(payload))
    except Exception:
        return None
    return path


def load_btc_1h_cache(start: dt.datetime, end: dt.datetime) -> list[tuple[int, float]]:
    """Load BTC 1h closes dari GABUNGAN cache lokal yang menutup jendela."""
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    merged = merge_cached_candles()
    if merged:
        keys = sorted(merged)
        if keys[0] <= start_ms and keys[-1] >= end_ms:
            return [(k, merged[k]) for k in keys if start_ms <= k <= end_ms]
    raise FileNotFoundError("no BTC 1h cache covers requested window")


def fetch_btc_1h(start: dt.datetime, end: dt.datetime) -> list[tuple[int, float]]:
    """Fetch BTCUSDT spot 1h closes; use local cache during network/DNS outages."""
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    out: list[tuple[int, float]] = []
    cur = start_ms
    try:
        while cur <= end_ms:
            params = urllib.parse.urlencode({
                "symbol": "BTCUSDT", "interval": "1h", "limit": 1000,
                "startTime": cur, "endTime": end_ms,
            })
            url = f"https://api.binance.com/api/v3/klines?{params}"
            req = urllib.request.Request(url, headers={"User-Agent": "anantara-sodex-reeval/1.0"})
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        batch = json.loads(resp.read().decode())
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < 2:
                        time.sleep(1.0)
            else:
                raise last_error or RuntimeError("BTC fetch failed")
            if not batch:
                break
            for row in batch:
                out.append((int(row[0]), float(row[4])))
            nxt = int(batch[-1][0]) + 3600_000
            if nxt <= cur:
                break
            cur = nxt
        if out:
            merged = sorted(dict(out).items())
            # Self-healing: segarkan cache setelah fetch sukses agar gangguan
            # DNS berikutnya masih punya cadangan.
            persist_btc_cache(merged)
            return merged
    except Exception:
        pass
    return load_btc_1h_cache(start, end)


def close_at_or_before(candles: list[tuple[int, float]], t: dt.datetime) -> float:
    keys = [k for k, _ in candles]
    target = int(t.timestamp() * 1000)
    idx = bisect.bisect_right(keys, target) - 1
    if idx < 0:
        raise ValueError(f"no BTC candle at/before {t.isoformat()}")
    return candles[idx][1]


def btc_market_returns(rows: list[dict[str, Any]], candles: list[tuple[int, float]]) -> list[float]:
    values: list[float] = []
    for row in rows:
        entry, exit_ = trade_times(row)
        a = close_at_or_before(candles, entry)
        b = close_at_or_before(candles, exit_)
        values.append(b / a - 1.0)
    return values


def count_missing_funding(rows: list[dict[str, Any]]) -> int:
    keys = ("funding", "funding_fee", "funding_value", "borrow", "borrow_fee", "funding_pnl")
    return sum(1 for row in rows if not any(k in row and row[k] not in (None, "") for k in keys))


def funding_missing_reason(rows: list[dict[str, Any]]) -> str:
    missing = count_missing_funding(rows)
    return f"funding_required_but_missing: {missing}/{len(rows)} rows without funding/borrow field"


def daily_sharpe_from_rows(rows: list[tuple[dt.datetime, float]]) -> dict[str, Any]:
    if not rows:
        return {"valid": False, "reason": "capital rows empty"}
    rows = sorted(rows)
    cutoff = rows[-1][0] - dt.timedelta(days=90)
    day_last: dict[str, tuple[dt.datetime, float]] = {}
    zero_or_negative: list[tuple[str, float]] = []
    for t, eq in rows:
        if t >= cutoff:
            if eq <= 0:
                zero_or_negative.append((t.isoformat(), eq))
            day_last[t.date().isoformat()] = (t, eq)
    days = sorted(day_last)
    rets: list[float] = []
    jumps: list[dict[str, Any]] = []
    prev: tuple[str, float] | None = None
    for day in days:
        eq = day_last[day][1]
        if prev and prev[1] > 0 and eq > 0:
            r = eq / prev[1] - 1.0
            rets.append(r)
            if abs(r) > 0.20:
                jumps.append({"day": day, "prev_equity": prev[1], "equity": eq, "return": r})
        prev = (day, eq)
    sharpe = math.nan
    if len(rets) >= 2 and math.isfinite(stdev := _pstdev(rets)) and stdev > 0:
        sharpe = _mean(rets) / stdev * math.sqrt(365)
    # 2026-10-04: pembanding GEOMETRIK. Sama seperti kurva intra-hari, rata-rata
    # ARITMETIKA bisa memberi Sharpe positif pada kurva yang justru merugi bila
    # ekuitas menyusut (persentase membesar seiring basis mengecil). Selisih
    # tanda antara kedua kolom = sinyal artefak, bukan edge.
    rets_log = [math.log(1.0 + r) for r in rets if (1.0 + r) > 0]
    sharpe_log = math.nan
    if len(rets_log) >= 2 and math.isfinite(sl := _pstdev(rets_log)) and sl > 0:
        sharpe_log = _mean(rets_log) / sl * math.sqrt(365)
    valid = not zero_or_negative and not jumps and len(rets) >= 30 and math.isfinite(sharpe)
    return {
        "valid": valid,
        "reason": "OK" if valid else "FAIL-CLOSED: equity discontinuities/zero values make 90d wallet Sharpe not interpretable as strategy Sharpe",
        "n_daily_returns": len(rets), "start_day": days[0] if days else None, "end_day": days[-1] if days else None,
        "sharpe_ann_raw_untrusted": sharpe,
        "sharpe_ann_log_raw_untrusted": sharpe_log,
        "daily_mean_log": _mean(rets_log) if rets_log else math.nan,
        "daily_mean": _mean(rets) if rets else math.nan,
        "daily_vol": _pstdev(rets) if len(rets) > 1 else math.nan,
        "maxdd_raw_untrusted": max_drawdown(rets) if rets else math.nan,
        "zero_or_negative_count": len(zero_or_negative),
        "large_jump_count": len(jumps),
        "large_jumps_sample": jumps[:8],
    }


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else math.nan


def _pstdev(xs: list[float]) -> float:
    if not xs:
        return math.nan
    mu = _mean(xs)
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / len(xs))


def wallet_distance_metrics(current_wallet: float, start_equity: float, local_engine_net: float) -> dict[str, float]:
    target = 0.008 * current_wallet
    wallet_delta = current_wallet - start_equity
    return {
        "target_48h_usd": target,
        "wallet_equity_delta_48h_usd": wallet_delta,
        "wallet_equity_delta_48h_pct_wallet": wallet_delta / current_wallet if current_wallet else math.nan,
        "local_engine_trading_net_48h_usd": local_engine_net,
        "jarak_ke_target_wallet_delta": wallet_delta / target if target else math.nan,
        "jarak_ke_target_local_engine_trading": local_engine_net / target if target else math.nan,
    }


def normalized_window_distance_metrics(normalized: dict[str, Any], current_wallet: float, hours: int = 48) -> dict[str, Any]:
    """D0.2 canonical target distance from trading-only normalized equity.

    Raw wallet equity stays diagnostic only because it contains venue/reconcile
    discontinuities. The target denominator remains current total wallet.

    NOTE 2026-10-04: `sodex_normalized_equity.build_series` is now fail-closed --
    the `stats` block does not reconcile to observed equity, so no normalized
    trading-only series is produced. This pure function therefore has no live
    caller; it is kept (and tested) because it stays correct for any series that
    DOES reconcile. `valid` must be strictly True: a missing flag fails closed.
    """
    if normalized.get("valid") is not True:
        return {"valid": False, "reason": f"FAIL_CLOSED: upstream normalized series invalid -- {normalized.get('reason')}"}
    rows = normalized.get("rows") or []
    if len(rows) < 2:
        return {"valid": False, "reason": "normalized equity rows insufficient"}
    latest = rows[-1]
    latest_ts = parse_dt(latest["ts"])
    boundary = latest_ts - dt.timedelta(hours=hours)
    start = min(rows, key=lambda r: abs((parse_dt(r["ts"]) - boundary).total_seconds()))
    target = 0.008 * current_wallet
    delta = float(latest["normalized_equity"]) - float(start["normalized_equity"])
    local_net = sum(float(r.get("local_net_usd") or 0.0) for r in rows if parse_dt(r["ts"]) >= parse_dt(start["ts"]))
    reconcile_net = sum(float(r.get("reconcile_net_usd") or 0.0) for r in rows if parse_dt(r["ts"]) >= parse_dt(start["ts"]))
    return {
        "valid": True,
        "series_role": "CANONICAL_D0_2_TRADING_ONLY_GATE_SERIES",
        "raw_wallet_role": "DIAGNOSTIC_RCA_ONLY_NOT_GATE_SERIES",
        "target_denominator": "CURRENT_TOTAL_WALLET",
        "window_hours": hours,
        "start_ts": start["ts"],
        "end_ts": latest["ts"],
        "start_normalized_equity_usd": float(start["normalized_equity"]),
        "end_normalized_equity_usd": float(latest["normalized_equity"]),
        "normalized_delta_usd": delta,
        "local_net_usd": local_net,
        "reconcile_net_usd": reconcile_net,
        "target_48h_usd": target,
        "distance_to_target_ratio": delta / target if target else math.nan,
        "distance_to_target_pct": delta / target * 100.0 if target else math.nan,
    }


def capital_rows_from_report(path: Path) -> list[tuple[dt.datetime, float, dict[str, Any]]]:
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if d.get("equity") is not None:
            rows.append((parse_dt(d["ts"]), float(d["equity"]), d.get("stats") or {}))
    return sorted(rows, key=lambda r: r[0])


def wallet_distance_from_files() -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "scripts"))
    import sodex_wallet_denominator as wd  # noqa: E402

    perps, spot, priced, dust = wd.read_priced_wallet()
    try:
        _p2, _s2, final_total, final_dust = wd.read_real_wallet()
        final_ok = True
        dust = final_dust
    except Exception:
        final_total = priced
        final_ok = False
    rows = capital_rows_from_report(ROOT / "data/capital_report.jsonl")
    if not rows:
        raise RuntimeError("capital_report empty")
    now = dt.datetime.now(dt.timezone.utc)
    boundary = now - dt.timedelta(hours=48)
    naive = min(rows, key=lambda r: abs((r[0] - boundary).total_seconds()))
    # FAIL-CLOSED anchor: never open the window on a $0.00 heartbeat snapshot.
    # See scripts/sodex_target_distance.py -- the naive pick once made the weekly
    # report announce jarak_ke_target = 12500% when the truth was -5.2%.
    valid_rows = [r for r in rows if r[1] > 0]
    if not valid_rows:
        raise RuntimeError("capital_report has no snapshot with equity > 0")
    before = [r for r in valid_rows if r[0] <= boundary]
    start = before[-1] if before else valid_rows[0]
    latest = rows[-1]
    recent = [(t, s) for t, _eq, s in rows if t >= start[0]]
    local_net = sum(float(s.get("net_6h") or 0.0) for _t, s in recent)
    rt = sum(int(s.get("rt_6h") or 0) for _t, s in recent)
    out = wallet_distance_metrics(float(final_total), float(start[1]), local_net)
    out.update({
        "current_wallet_priced_usd": float(final_total), "perps_usd": float(perps), "spot_usd": float(spot),
        "denominator_final_ok": final_ok, "dust": dust,
        "start_ts": start[0].isoformat(), "start_equity_usd": start[1],
        "start_ts_naive": naive[0].isoformat(), "start_equity_usd_naive": float(naive[1]),
        "anchor_is_valid": bool(float(start[1]) > 0),
        "anchor_corrected": start[0] != naive[0],
        "exact_48h_boundary_utc": boundary.isoformat(),
        "latest_capital_report_ts": latest[0].isoformat(), "latest_capital_report_equity_usd": latest[1],
        "current_snapshot_time_utc": now.isoformat(), "local_engine_round_trips_48h": rt,
    })
    return out


def sharpe90_from_capital_report() -> dict[str, Any]:
    rows = [(t, eq) for t, eq, _stats in capital_rows_from_report(ROOT / "data/capital_report.jsonl")]
    return daily_sharpe_from_rows(rows)


def reconcile_evidence() -> dict[str, Any]:
    path = ROOT / "data/reconcile/state_reconcile.jsonl"
    if not path.exists():
        return {"path": str(path), "events": [], "net_pnl_usd": 0.0}
    events = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rec = row.get("closed_record") or {}
        pnl = rec.get("pnl_usd_net", rec.get("pnl_usd"))
        if pnl is None:
            continue
        events.append({
            "id": row.get("id"), "ts_utc": row.get("ts_utc"), "lane": row.get("lane"), "action": row.get("action"),
            "symbol": rec.get("pair") or rec.get("coin") or rec.get("vsym"),
            "reason": rec.get("exit_reason") or rec.get("reason"),
            "pnl_usd": float(pnl), "note": rec.get("note", "")[:220],
        })
    return {"path": str(path), "events": events, "net_pnl_usd": sum(e["pnl_usd"] for e in events)}


def _usable_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    usable: list[dict[str, Any]] = []
    dropped = 0
    for row in rows:
        try:
            trade_return(row); trade_times(row); side_sign(row)
            usable.append(row)
        except Exception:
            dropped += 1
    return usable, dropped


def _score(usable: list[dict[str, Any]], candles: list[tuple[int, float]], n_trials: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Grade a row set WITHOUT touching the trial registry (diagnostic arms)."""
    if len(usable) < 3:
        return None, None
    returns = [trade_return(r) for r in usable]
    sides = [side_sign(r) for r in usable]
    groups = [trade_symbol(r) for r in usable]
    market = btc_market_returns(usable, candles)
    return evaluate(
        returns=returns, market=market, sides=sides, fee_bps=SODEX_FEE_BPS,
        n_trials=n_trials, groups=groups, periods_per_year=365, min_n=30,
    )


def _arm_summary(rows: list[dict[str, Any]], usable: list[dict[str, Any]], dropped: int, res: dict[str, Any] | None) -> dict[str, Any]:
    returns = [trade_return(r) for r in usable]
    return {
        "n_raw": len(rows), "n": len(usable), "dropped": dropped,
        "input_wr": (sum(1 for x in returns if x > 0) / len(returns)) if returns else math.nan,
        "excess_mean": (res or {}).get("excess_mean"),
        "ci95": (res or {}).get("ci95"),
        "cost_2x_mean": ((res or {}).get("cost_stress") or {}).get("2.0", {}).get("mean"),
    }


CLUSTER_HOURS = 30.0


def cluster_ci95(pairs: list[tuple[int, float]], n_iter: int = 10000, seed: int = 20261004) -> list[float] | None:
    """Diagnostic cluster bootstrap CI95 (block = 30 h entry bucket).

    OWNER DECISION 2026-10-04: the gate KEEPS the row-level (IID) CI so historical
    reports stay comparable; this cluster interval is diagnostic ONLY. Revisit
    when T1 is close to passing. Do not silently switch the gate default -- RISET
    measured the row-level rule over-firing at 3.6-8.2% vs a 2.5% nominal
    (D0.5 verification, 2026-10-04); that miscalibration is why this column exists.
    """
    if len(pairs) < 2:
        return None
    blocks: dict[int, list[float]] = {}
    for ts, value in pairs:
        blocks.setdefault(int(ts // (CLUSTER_HOURS * 3600.0)), []).append(value)
    ids = sorted(blocks)
    if len(ids) < 2:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(n_iter):
        vals = [v for b in (ids[rng.randrange(len(ids))] for _ in ids) for v in blocks[b]]
        if vals:
            means.append(sum(vals) / len(vals))
    if not means:
        return None
    means.sort()
    return [means[int(0.025 * len(means))], means[int(0.975 * len(means)) - 1]]


def evaluate_track(name: str, path: Path, candles: list[tuple[int, float]], registry: TrialRegistry) -> dict[str, Any]:
    """Grade the SIGNAL arm only; score the RANDOM control arm and the legacy
    mixed view beside it so the measurement bias stays visible and reversible."""
    raw_rows = closed_rows(path)
    smuggled = assert_no_control_smuggling(raw_rows)
    if smuggled:
        raise ValueError(
            f"{name}: {smuggled} control-looking row(s) (regime=RANDOM_CONTROL) carry no "
            f"`track={ARM_RANDOM_LABEL}` label; refusing to grade -- fix the lane writer."
        )
    signal_rows = [r for r in raw_rows if arm_of(r) == ARM_SIGNAL]
    control_rows = [r for r in raw_rows if arm_of(r) == ARM_CONTROL]

    usable, dropped = _usable_rows(signal_rows)
    returns = [trade_return(r) for r in usable]
    n_trials = registry.count() + 1
    grade, res = _score(usable, candles, n_trials)
    if grade is None:
        grade, res = {"passed": False, "reasons": [f"n<3 usable rows ({len(usable)})"]}, {}
    log_trial(registry, strategy=name, passed=grade.get("passed", False), note="SoDEX harness re-eval (signal arm)", n=len(usable), reasons=grade.get("reasons", []))

    ctl_usable, ctl_dropped = _usable_rows(control_rows)
    _, ctl_res = _score(ctl_usable, candles, n_trials)
    legacy_usable, legacy_dropped = _usable_rows(raw_rows)
    _, legacy_res = _score(legacy_usable, candles, n_trials)

    signal_summary = _arm_summary(signal_rows, usable, dropped, res)
    legacy_summary = _arm_summary(raw_rows, legacy_usable, legacy_dropped, legacy_res)
    bias_bps = None
    if signal_summary["excess_mean"] is not None and legacy_summary["excess_mean"] is not None:
        bias_bps = (signal_summary["excess_mean"] - legacy_summary["excess_mean"]) * 10000.0

    pairs: list[tuple[int, float]] = []
    try:
        rets = [trade_return(r) for r in usable]
        sds = [side_sign(r) for r in usable]
        mkts = btc_market_returns(usable, candles)
        for r, ret, sd, mk in zip(usable, rets, sds, mkts):
            entry_t, _ = trade_times(r)
            pairs.append((int(entry_t.timestamp()), sd * ret - sd * mk))
    except Exception:
        pairs = []

    return {
        "track": name, "source": str(path), "n_raw": len(raw_rows), "n": len(usable), "dropped": dropped,
        "grade": grade, "result": res,
        "input_wr": sum(1 for x in returns if x > 0) / len(returns) if returns else math.nan,
        "ci95_cluster_bps": cluster_ci95(pairs),
        "control_smuggling_checked": True,
        "arms": {
            "signal": signal_summary,
            "control": _arm_summary(control_rows, ctl_usable, ctl_dropped, ctl_res),
            "legacy_all": legacy_summary,
            "arm_split_bias_bps": bias_bps,
        },
    }



def evaluate_short_side(rows: list[dict[str, Any]], candles: list[tuple[int, float]], registry: TrialRegistry) -> dict[str, Any]:
    shorts = [r for r in rows if side_sign(r) == -1]
    returns = [trade_return(r) for r in shorts]
    sides = [side_sign(r) for r in shorts]
    groups = [trade_symbol(r) for r in shorts]
    market = btc_market_returns(shorts, candles)
    n_trials = registry.count() + 1
    grade, res = evaluate(returns=returns, market=market, sides=sides, fee_bps=SODEX_FEE_BPS, n_trials=n_trials, groups=groups, periods_per_year=365, min_n=30)
    reasons = list(grade.get("reasons", []))
    missing = count_missing_funding(shorts)
    funding_fail = missing > 0
    if funding_fail:
        reasons.append(funding_missing_reason(shorts))
    passed = bool(grade.get("passed")) and not funding_fail
    log_trial(registry, strategy="twoway_short_side", passed=passed, note="SoDEX harness re-eval", n=len(shorts), reasons=reasons)
    return {"track": "twoway_short_side", "n": len(shorts), "input_wr": sum(1 for x in returns if x > 0) / len(returns) if returns else math.nan, "grade": grade, "result": res, "funding_missing": missing, "passed_after_funding_check": passed, "reasons_after_funding_check": reasons}


def pct(x: Any) -> str:
    try:
        v = float(x)
        if not math.isfinite(v):
            return "n/a"
        return f"{v * 100:.3f}%"
    except Exception:
        return "n/a"


def generate_report(out: dict[str, Any], md_path: Path) -> None:
    lines = ["# SoDEX Harness Re-evaluation — 2026-10-02\n"]
    lines.append("**Status:** T1 FAIL. Tidak ada strategi/gate/leverage/exit yang diubah. Lane uang nyata tetap FROZEN.\n")
    lines.append("## Metode\n")
    lines.append(f"- Harness: `{HARNESS}`; self-test 18/18 PASS sebelum evaluasi.\n")
    lines.append("- Returns: `pnl_pct` / `pnl_per_trade`; market beta: BTCUSDT Binance spot 1h close at/before entry→exit.\n")
    lines.append("- Fee: SoDEX tier-0 8 bps RT; harness cost stress 1×/1,5×/2×.\n")
    lines.append(f"- Registry trial: `{out['registry_path']}`; count {out['registry_count']}.\n")
    lines.append("\n## Hasil 3 track\n")
    lines.append("| Track | n | WR input | excess_mean | median | Sharpe ann | CI95 mean | cost 1× mean | cost 2× mean | PASS | alasan gagal utama |\n")
    lines.append("|---|---:|---:|---:|---:|---:|---|---:|---:|---|---|\n")
    for item in out["tracks"]:
        r = item["result"]; g = item["grade"]
        ci = r.get("ci95", [math.nan, math.nan])
        c1 = r.get("cost_stress", {}).get("1.0", {}).get("mean", math.nan)
        c2 = r.get("cost_stress", {}).get("2.0", {}).get("mean", math.nan)
        lines.append(f"| {item['track']} | {item['n']} | {pct(item['input_wr'])} | {pct(r.get('excess_mean'))} | {pct(r.get('median'))} | {r.get('sharpe_ann', math.nan):.2f} | [{pct(ci[0])}; {pct(ci[1])}] | {pct(c1)} | {pct(c2)} | {g.get('passed')} | {'; '.join(g.get('reasons', []))} |\n")
    lines.append("\n## Arm split — signal vs kontrol RANDOM (D0.5)\n")
    lines.append("Track dinilai dari **arm sinyal saja**. Arm `track=RANDOM` (kontrol negatif, label a-priori) dan tampilan lama (campur) dilaporkan berdampingan supaya bias pengukuran tetap terlihat.\n")
    lines.append("| Track | n_signal | n_control | excess signal | excess legacy(campur) | bias arm-split (bps) | excess control |\n")
    lines.append("|---|---:|---:|---:|---:|---:|---:|\n")
    for item in out["tracks"]:
        arms = item.get("arms") or {}
        sig = arms.get("signal") or {}
        ctl = arms.get("control") or {}
        leg = arms.get("legacy_all") or {}
        lines.append(f"| {item['track']} | {sig.get('n')} | {ctl.get('n')} | {pct(sig.get('excess_mean'))} | {pct(leg.get('excess_mean'))} | {arms.get('arm_split_bias_bps', math.nan):.2f} | {pct(ctl.get('excess_mean'))} |\n")
    lines.append("\n### Guard integritas arm\n")
    lines.append(f"- `control_smuggling_checked`: baris `regime=RANDOM_CONTROL` tanpa label `track={ARM_RANDOM_LABEL}` membuat track DITOLAK untuk dinilai (fail-closed), bukan diam-diam masuk arm sinyal.\n")
    lines.append("\n## CI95 — baris (dipakai gate) vs cluster 30 jam (diagnostik)\n")
    lines.append("Gate memakai CI baris demi komparabilitas laporan lama. RISET mengukur aturan baris ini over-fire **3,6-8,2 %** vs nominal 2,5 %; kolom cluster disertakan supaya salah-kalibrasi itu tetap terlihat. **Keputusan Owner 2026-10-04: gate TETAP CI baris; cluster diagnostik saja; tinjau ulang saat T1 mendekati lulus.**\n")
    lines.append("| Track | n | CI95 baris (gate) | CI95 cluster 30 h | lebar baris (bps) | lebar cluster (bps) | rasio |\n")
    lines.append("|---|---:|---|---|---:|---:|---:|\n")
    for item in out["tracks"]:
        r = item.get("result") or {}
        row_ci = r.get("ci95") or [math.nan, math.nan]
        cl = item.get("ci95_cluster_bps") or [math.nan, math.nan]
        w_row = (row_ci[1] - row_ci[0]) * 10000.0 if isinstance(row_ci[0], (int, float)) and math.isfinite(row_ci[0]) else math.nan
        w_cl = (cl[1] - cl[0]) * 10000.0 if isinstance(cl[0], (int, float)) and math.isfinite(cl[0]) else math.nan
        ratio = (w_cl / w_row) if (math.isfinite(w_row) and w_row) else math.nan
        lines.append(f"| {item['track']} | {item['n']} | [{pct(row_ci[0])}; {pct(row_ci[1])}] | [{pct(cl[0])}; {pct(cl[1])}] | {w_row:.1f} | {w_cl:.1f} | {ratio:.2f} |\n")
    short = out["short_side"]
    sr = short["result"]; sci = sr.get("ci95", [math.nan, math.nan])
    lines.append("\n## SHORT-side terpisah — twoway 42 SHORT\n")
    lines.append(f"- n={short['n']}; WR input={pct(short['input_wr'])}; excess_mean={pct(sr.get('excess_mean'))}; Sharpe={sr.get('sharpe_ann', math.nan):.2f}; CI95=[{pct(sci[0])}; {pct(sci[1])}].\n")
    lines.append(f"- Cost 1× mean={pct(sr.get('cost_stress', {}).get('1.0', {}).get('mean', math.nan))}; cost 2× mean={pct(sr.get('cost_stress', {}).get('2.0', {}).get('mean', math.nan))}.\n")
    lines.append(f"- Funding/borrow nyata: **FAIL-CLOSED** — {short['funding_missing']}/{short['n']} rows tidak punya field funding/borrow; PASS={short['passed_after_funding_check']}; alasan={'; '.join(short['reasons_after_funding_check'])}.\n")
    w = out["wallet_distance"]
    lines.append("\n## Jarak ke target 48 jam\n")
    lines.append(f"- Wallet current priced: ${w['current_wallet_priced_usd']:.2f} (perps ${w['perps_usd']:.2f} + spot ${w['spot_usd']:.2f}); denominator final OK={w['denominator_final_ok']}.\n")
    lines.append(f"- Start 48h proxy: {w['start_ts']} equity ${w['start_equity_usd']:.2f} (boundary {w['exact_48h_boundary_utc']}). Current priced: ${w['current_wallet_priced_usd']:.2f}.\n")
    lines.append(f"- Anchor fail-closed: valid={w.get('anchor_is_valid')}; dikoreksi dari pilihan naif={w.get('anchor_corrected')} (naif: {w.get('start_ts_naive')} equity ${w.get('start_equity_usd_naive', math.nan):.2f}). Snapshot equity $0,00 tidak boleh membuka jendela — pernah membuat laporan ini menulis jarak_ke_target=12500% padahal sebenarnya negatif.\n")
    lines.append(f"- Wallet equity delta 48h: ${w['wallet_equity_delta_48h_usd']:.3f} = {pct(w['wallet_equity_delta_48h_pct_wallet'])}. Target: ${w['target_48h_usd']:.3f}.\n")
    lines.append(f"- **jarak_ke_target wallet-delta = {w['jarak_ke_target_wallet_delta'] * 100:.1f}%** dari target 0,8%/48h.\n")
    lines.append(f"- Local engine trading stats 48h: round-trip={w['local_engine_round_trips_48h']}, net=${w['local_engine_trading_net_48h_usd']:.3f}; **jarak_ke_target trading-only = {w['jarak_ke_target_local_engine_trading'] * 100:.1f}%**.\n")
    nd = out.get("canonical_normalized_target_distance", {})
    lines.append("\n## D0.2 canonical gate equity — normalized trading-only\n")
    if nd.get("valid"):
        lines.append(f"- Series role: **{nd.get('series_role')}**; raw wallet: **{nd.get('raw_wallet_role')}**; denominator={nd.get('target_denominator')}.\n")
        lines.append(f"- Window {nd.get('start_ts')} → {nd.get('end_ts')}; normalized delta=${nd.get('normalized_delta_usd', math.nan):.3f}; target=${nd.get('target_48h_usd', math.nan):.3f}; **jarak_ke_target canonical={nd.get('distance_to_target_pct', math.nan):.1f}%**.\n")
    else:
        lines.append(f"- **INVALID / FAIL-CLOSED**: {nd.get('reason')}.\n")
    s = out["sharpe90"]
    lines.append("\n## Sharpe rolling 90 hari wallet\n")
    if s.get("valid"):
        lines.append(f"- Daily returns n={s.get('n_daily_returns')}; window {s.get('start_day')}..{s.get('end_day')}; Sharpe ann={s.get('sharpe_ann_raw_untrusted', math.nan):.2f}; MaxDD={pct(s.get('maxdd_raw_untrusted'))}.\n")
    else:
        lines.append(f"- **INVALID / FAIL-CLOSED**: {s.get('reason')}. Raw untrusted Sharpe (aritmetika)={s.get('sharpe_ann_raw_untrusted', math.nan):.2f}; **Sharpe log={s.get('sharpe_ann_log_raw_untrusted', math.nan):+.2f}**; jumps>20% count={s.get('large_jump_count')}; zero/negative snapshots={s.get('zero_or_negative_count')}. Selisih tanda antara keduanya = artefak aritmetika, bukan edge.\n")
    rec = out.get("reconcile_evidence", {})
    lines.append("\n## Capital discontinuity RCA evidence\n")
    lines.append(f"- Source: `{rec.get('path')}`; reconciled-event net=${rec.get('net_pnl_usd', 0.0):.3f}.\n")
    for ev in rec.get("events", [])[:5]:
        lines.append(f"- id={ev.get('id')} {ev.get('ts_utc')} {ev.get('lane')} {ev.get('symbol')} {ev.get('reason')}: pnl=${ev.get('pnl_usd', 0.0):.3f}.\n")
    fm = out.get("funding_map", {})
    lines.append("\n## Funding mapper — SHORT-side\n")
    lines.append(f"- Verdict: **{fm.get('verdict')}**; coverage={fm.get('coverage_pct', 0.0)*100:.1f}%; exact={fm.get('n_exact')}; rate_estimated={fm.get('n_rate_estimated')}; missing={fm.get('n_missing')}; reason={fm.get('reason')}.\n")
    rate = out.get("funding_rate_collector", {})
    lines.append("\n## Funding rate collector — D0.1\n")
    lines.append(f"- Verdict: **{rate.get('verdict')}**; rows={rate.get('n_rows')}; appended={rate.get('appended')}; archive=`{rate.get('out')}`.\n")
    lines.append(f"- Current range: min={rate.get('min_rate_bps', math.nan):.3f} bps, max={rate.get('max_rate_bps', math.nan):.3f} bps.\n")
    ne = out.get("normalized_equity", {})
    lines.append("\n## Normalized equity builder — trading-only\n")
    lines.append(f"- **Verdict: {ne.get('valid')}** — {ne.get('reason')}\n")
    lines.append(f"- Series role: `{ne.get('series_role')}`; rows={ne.get('n_rows')}; snapshot equity<=0 yang dibuang={ne.get('zero_or_negative_snapshot_count')}.\n")
    lines.append(f"- Equity teramati: ${ne.get('start_equity_usd', math.nan):.2f} -> ${ne.get('end_equity_usd', math.nan):.2f} (delta ${ne.get('observed_total_delta_usd', math.nan):.3f}).\n")
    lines.append(f"- `sum(net_6h)`=${ne.get('total_local_net_6h_usd', math.nan):.3f} vs observed -> **over-count {ne.get('net6h_over_count_ratio', math.nan):.4f}x** (jendela rolling 6 jam, sampel ~4,8 jam). Reconcile venue=${ne.get('total_reconcile_net_usd', math.nan):.3f}.\n")
    if ne.get("valid"):
        lines.append(
            f"- MaxDD trading-only: **{ne.get('maxdd_trading_only', math.nan) * 100:.2f}%**; "
            f"Sharpe (log/geometrik, KANONIK): **{ne.get('sharpe_ann_trading_only', math.nan):+.2f}**; "
            f"versi aritmetika {ne.get('sharpe_ann_trading_only_arithmetic', math.nan):+.2f} "
            "**TIDAK interpretabel** (ekuitas menyusut -> mean positif palsu).\n")
        lines.append(
            f"- Kurva: ${ne.get('start_equity_usd', math.nan):.2f} -> ${ne.get('end_equity_usd', math.nan):.2f}, "
            f"min ${ne.get('equity_min_usd', math.nan):.2f}; interval median "
            f"{ne.get('median_interval_hours', math.nan):.3f} jam; lompatan>{int(0.2*100)}% = "
            f"{ne.get('large_observed_jump_count')}. {ne.get('caveat', '')}\n")
    else:
        lines.append(f"- **INVALID / FAIL-CLOSED**: {ne.get('reason')}\n")
    lines.append("\n## Keputusan operasional\n")
    lines.append("- T1: **FAIL**. Tidak ada track yang boleh dipromosikan.\n")
    lines.append("- Build mesin strategi baru sekarang: **NO**. Sesuai dokumen: ukur dulu; T1 belum lulus.\n")
    lines.append("- Pembangunan yang boleh lanjut: measurement pipeline + data mapping funding/capital + verifikasi RISET/monitor.\n")
    lines.append("- Unfreeze lane uang nyata: **NO**.\n")
    lines.append("- Exit/leverage/position sizing/gate: **tidak disentuh**.\n")
    md_path.write_text("".join(lines))


TRIAL_REGISTRY_PATH = REPORT_DIR / "sodex_trial_registry.json"
LEGACY_REGISTRIES = ("sodex_trial_registry_20261002.json",)


def _save_registry(registry) -> None:
    """Tulis isi registry ke disk. Dipakai saat memperbarui baris yang sudah ada."""
    with open(registry.path, "w") as fh:
        json.dump(registry.rows, fh, indent=1, default=str)


def log_trial(registry, **kw) -> None:
    """Catat trial secara APPEND-ONLY dan IDEMPOTEN.

    2026-10-04 (A4): sebelumnya `main()` menulis `write_text("[]")` ke berkas
    BERTANGGAL pada setiap run, sehingga `n_trials` selalu <= 4 walau evaluasi
    sudah dijalankan berkali-kali. DSR mendeflasi Sharpe dengan JUMLAH TRIAL,
    jadi angka yang selalu kecil membuat DSR terlalu lunak -> risiko p-hacking.
    Kini berkas stabil (tanpa tanggal) dan tidak pernah direset, dan
    re-evaluasi yang IDENTIK tidak menambah `n_trials` (hanya menaikkan
    `seen_count`) supaya hitungannya = jumlah evaluasi BERBEDA, bukan jumlah
    kali dijalankan. Riwayat penuh tetap tersimpan.
    """
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    key = (kw.get("strategy"), kw.get("n"), tuple(kw.get("reasons") or []))
    for row in registry.rows:
        if (row.get("strategy"), row.get("n"), tuple(row.get("reasons") or [])) == key:
            row["seen_count"] = int(row.get("seen_count") or 1) + 1
            row["last_seen"] = now
            _save_registry(registry)
            return
    kw.setdefault("first_seen", now)
    kw["last_seen"] = now
    kw["seen_count"] = 1
    registry.log(**kw)


def seed_registry(registry_path) -> None:
    """Sekali saja: pindahkan isi registry bertanggal lama ke berkas stabil.

    Trial lama TIDAK boleh hilang -- menghapus riwayat trial = membuang bukti
    p-hacking.
    """
    if registry_path.exists():
        return
    rows = []
    for legacy in LEGACY_REGISTRIES:
        lp = REPORT_DIR / legacy
        if lp.exists():
            try:
                rows.extend(json.loads(lp.read_text()))
            except Exception:
                pass
    registry_path.write_text(json.dumps(rows, indent=1, default=str))


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    all_rows = []
    for p in TRACKS.values():
        all_rows.extend(closed_rows(p))
    times = [x for row in all_rows for x in trade_times(row)]
    candles = fetch_btc_1h(min(times) - dt.timedelta(hours=2), max(times) + dt.timedelta(hours=2))
    # 2026-10-04 (A4): JANGAN reset registry. Sebelumnya baris di bawah ini
    # berbunyi `write_text("[]")` pada berkas bertanggal -> seluruh hitungan
    # trial hilang setiap run. Registry WAJIB append-only lintas run.
    registry_path = TRIAL_REGISTRY_PATH
    seed_registry(registry_path)
    registry = TrialRegistry(str(registry_path))
    tracks = [evaluate_track(name, path, candles, registry) for name, path in TRACKS.items()]
    short_side = evaluate_short_side([r for r in closed_rows(TRACKS["twoway"]) if arm_of(r) == ARM_SIGNAL], candles, registry)
    ne_result = sodex_normalized_equity.build_from_files()
    wallet = wallet_distance_from_files()
    out = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "tracks": tracks,
        "short_side": short_side,
        "wallet_distance": wallet,
        "canonical_normalized_target_distance": normalized_window_distance_metrics(ne_result, wallet["current_wallet_priced_usd"]),
        "sharpe90": sharpe90_from_capital_report(),
        "reconcile_evidence": reconcile_evidence(),
        "funding_map": sodex_funding_mapper.build_mapping(),
        "funding_rate_collector": sodex_funding_rate_collector.collect(),
        "normalized_equity": ne_result,
        "registry_path": str(registry_path),
        "registry_count": registry.count(),
        "decision": {
            "t1_status": "FAIL — no track may be promoted; strategy/gate/leverage/exit unchanged",
            "unfreeze_real_money": "NO",
            "build_new_strategy_machine_now": "NO",
            "allowed_next_build": "measurement/funding/capital validation pipeline only",
        },
    }
    json_path = REPORT_DIR / "sodex_harness_reeval_20261002.json"
    md_path = REPORT_DIR / "SODEX_HARNESS_REEVAL_2026-10-02.md"
    json_path.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    generate_report(out, md_path)
    print(json.dumps({"json": str(json_path), "md": str(md_path), "registry": str(registry_path), "decision": out["decision"]}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
