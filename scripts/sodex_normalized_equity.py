#!/usr/bin/env python3
"""Build an auditable SoDEX trading-only normalized equity series.

Observed wallet equity can jump because of denominator changes, unpriced assets,
transfers, or late venue reconciliation. This script keeps those jumps visible and
builds a separate normalized series from local engine net PnL plus venue reconcile
PnL only. Read-only.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import statistics as st
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CAPITAL_REPORT = ROOT / "data/capital_report.jsonl"
RECONCILE = ROOT / "data/reconcile/state_reconcile.jsonl"
REPORT_DIR = ROOT / "reports/sodex"


def parse_dt(value: Any) -> dt.datetime:
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else math.nan


def pstdev(xs: list[float]) -> float:
    if not xs:
        return math.nan
    mu = mean(xs)
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / len(xs))


def max_drawdown_from_equity(equity: list[float]) -> float:
    if not equity:
        return math.nan
    peak = equity[0]
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


def load_capital_rows(path: Path = CAPITAL_REPORT) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("equity") is None:
            continue
        rows.append({
            "ts": parse_dt(row["ts"]),
            "equity": float(row["equity"]),
            "stats": row.get("stats") or {},
        })
    return sorted(rows, key=lambda r: r["ts"])


def load_reconcile_events(path: Path = RECONCILE) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rec = row.get("closed_record") or {}
        pnl = rec.get("pnl_usd_net", rec.get("pnl_usd"))
        if pnl is None:
            continue
        out.append({
            "ts": parse_dt(row.get("ts_utc")),
            "pnl_usd": float(pnl),
            "lane": row.get("lane"),
            "action": row.get("action"),
            "symbol": rec.get("pair") or rec.get("coin") or rec.get("vsym"),
            "reason": rec.get("exit_reason") or rec.get("reason"),
        })
    return sorted(out, key=lambda r: r["ts"])


def reconcile_sum_between(events: list[dict[str, Any]], start: dt.datetime, end: dt.datetime) -> float:
    return sum(e["pnl_usd"] for e in events if start < e["ts"] <= end)


def build_series(capital_rows: list[dict[str, Any]], reconcile_events: list[dict[str, Any]], jump_threshold: float = 0.20) -> dict[str, Any]:
    """Observed-equity series plus a fail-closed verdict on the normalized series.

    FAIL-CLOSED SINCE 2026-10-04. The previous version accumulated `stats.net_6h`
    onto the first snapshot's equity and reported the result as a "trading-only
    normalized equity". That reconstruction is not supported by the data:

      * `net_6h` is a ROLLING 6 h window but snapshots arrive every ~4.8 h median
        (min 0 s), so consecutive values overlap and summing them double-counts.
        Measured over the full history: sum(net_6h) = -$592.152 against an observed
        equity change of -$502.435 (over-count 0.91x).
      * `net_today` differences do not reconcile either: intra-day increments sum
        to +$34.659 against an observed -$502.435.
      * The accumulated series therefore drifted below zero (min -$115.55, 18 rows),
        producing the impossible `maxdd_trading_only = -115.473%` (equity cannot
        lose more than 100%) that this report carried as a strategy metric.

    The `stats` block is telemetry, not a ledger. It cannot rebuild the wallet, so
    no normalized trading-only series is emitted and the strategy metrics are
    INVALID rather than fabricated. Observed equity stays available for diagnostics.
    """
    usable = [r for r in capital_rows if float(r["equity"]) > 0]
    zero_or_negative = len(capital_rows) - len(usable)

    if len(usable) < 2:
        return {"valid": False, "reason": "FAIL_CLOSED: fewer than 2 snapshots with equity > 0", "rows": [],
                "zero_or_negative_snapshot_count": zero_or_negative}

    # Observed series (diagnostic): equity deltas are non-overlapping by construction.
    rows = []
    for prev, cur in zip(usable, usable[1:]):
        observed_delta = float(cur["equity"]) - float(prev["equity"])
        prev_eq = float(prev["equity"])
        rows.append({
            "ts": cur["ts"].isoformat(),
            "observed_equity": float(cur["equity"]),
            "observed_delta_usd": observed_delta,
            "local_net_6h_usd": float((cur.get("stats") or {}).get("net_6h") or 0.0),
            "reconcile_net_usd": reconcile_sum_between(reconcile_events, prev["ts"], cur["ts"]),
            "large_observed_jump": bool(prev_eq > 0 and abs(observed_delta / prev_eq) > jump_threshold),
        })

    observed_total = float(usable[-1]["equity"]) - float(usable[0]["equity"])
    net6h_total = sum(r["local_net_6h_usd"] for r in rows)
    over_count = (net6h_total / observed_total) if observed_total else math.nan
    jumps = [r for r in rows if r["large_observed_jump"]]

    # ── RCA 2026-10-04: deret trading-only yang SAH ─────────────────────────
    # `observed_delta_usd` TILING by construction (lihat baris di atas), jadi ia
    # dapat dijumlahkan tanpa double-count. Kegagalan lama bukan karena data
    # kurang, melainkan karena deret dibangun dari `net_6h` (rolling 6 jam,
    # sampel ~4,8 jam -> tumpang-tindih -> over-count 0,91x) sehingga kurva
    # melayang di bawah nol dan menghasilkan MaxDD -115,473% (mustahil).
    # Tidak ada event deposit/withdraw/transfer di state_reconcile.jsonl, jadi
    # tidak ada aliran eksternal yang perlu dikeluarkan: seluruh perubahan
    # equity adalah hasil trading/operasional. Event reconcile TIDAK dikurangkan
    # karena equity snapshot sudah mencerminkannya (mengurangkan = hapus ganda).
    equity_curve, deltas, intervals_h = [], [], []
    running = float(usable[0]["equity"])
    equity_curve.append(running)
    prev_ts = usable[0]["ts"]
    for r in rows:
        running += float(r["observed_delta_usd"])
        equity_curve.append(running)
        # Kurva trading-only kumulatif per baris. Konsumen hilir
        # (normalized_window_distance_metrics) memakai kunci ini untuk mengukur
        # jarak ke target per jendela; kini terisi karena deretnya SAH.
        r["normalized_equity"] = running
        deltas.append(float(r["observed_delta_usd"]))
        cur_ts = dt.datetime.fromisoformat(r["ts"])
        intervals_h.append(max(0.0, (cur_ts - prev_ts).total_seconds() / 3600.0))
        prev_ts = cur_ts

    # MaxDD pada kurva equity yang sah. `peak <= 0` dilewati agar tidak membagi nol.
    peak, maxdd = equity_curve[0], 0.0
    for v in equity_curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = min(maxdd, (v - peak) / peak)

    # Sharpe per-interval dari return antar-snapshot, disetahunkan memakai
    # interval MEDIAN YANG SEBENARNYA (bukan asumsi 6 jam).
    rets = [d / p for d, p in zip(deltas, equity_curve[:-1]) if p > 0]
    med_h = st.median([h for h in intervals_h if h > 0]) if any(h > 0 for h in intervals_h) else math.nan
    ppy = (8760.0 / med_h) if (med_h and med_h > 0) else math.nan

    def _sharpe(xs):
        if len(xs) < 2:
            return math.nan
        sd = st.pstdev(xs)
        return (st.mean(xs) / sd * math.sqrt(ppy)) if (sd > 0 and ppy == ppy) else math.nan

    # JEBAKAN TERUKUR 2026-10-04: Sharpe dari RATA-RATA ARITMETIKA memberi +3,03
    # pada kurva yang NYATA-NYATA kehilangan 67% nilainya (746,78 -> 244,33).
    # Sebabnya: ekuitas menyusut 3x, jadi pergerakan dolar yang sama menjadi
    # persentase yang jauh lebih besar di akhir -> mean return positif padahal
    # level jatuh. Mean aritmetika +1,0177e-01 vs mean log -1,980959e-03.
    # Yang interpretabel adalah rata-rata LOG (geometrik): exp(sum(log)) =
    # 0,3272 = persis compounding sebenarnya. Jadi `sharpe_log` yang dipakai,
    # `sharpe_arithmetic` hanya disimpan sebagai bukti jebakannya.
    log_rets = [math.log(1.0 + a) for a in rets if (1.0 + a) > 0]
    sharpe_arith = _sharpe(rets)
    sharpe_log = _sharpe(log_rets)
    compounding = math.exp(sum(log_rets)) if log_rets else math.nan

    return {
        "valid": True,
        "reason": (
            "OK: deret trading-only dibangun dari `observed_delta_usd` (TILING, non-overlapping). "
            f"`stats.net_6h` TIDAK dipakai sebagai sumber -- ia rolling 6 jam pada sampel ~4,8 jam "
            f"(sum net_6h={net6h_total:.3f} vs observed {observed_total:.3f} = {over_count:.4f}x), "
            "sehingga versi lama over-count dan melahirkan maxdd -115,473% yang mustahil. Angka itu "
            "tidak kembali: `sharpe_ann_6h_trading_only` tetap NaN dan `maxdd_trading_only` dihitung "
            "dari kurva observed serta dibatasi [-1, 0]."
        ),
        "series_role": "TRADING_ONLY_TILING_OBSERVED_DELTAS",
        "n_rows": len(rows),
        "zero_or_negative_snapshot_count": zero_or_negative,
        "start_ts": usable[0]["ts"].isoformat(),
        "end_ts": usable[-1]["ts"].isoformat(),
        "start_equity_usd": float(usable[0]["equity"]),
        "end_equity_usd": float(usable[-1]["equity"]),
        "observed_total_delta_usd": observed_total,
        "total_local_net_6h_usd": net6h_total,
        "net6h_over_count_ratio": over_count,
        "total_reconcile_net_usd": sum(r["reconcile_net_usd"] for r in rows),
        "large_observed_jump_count": len(jumps),
        "large_observed_jumps_sample": jumps[:8],
        "sharpe_ann_6h_trading_only": math.nan,   # net_6h: TIDAK sah (rolling) -- diagnostik saja
        "maxdd_trading_only": maxdd,
        "sharpe_ann_trading_only": sharpe_log,          # KANONIK: rata-rata log (geometrik)
        "sharpe_ann_trading_only_arithmetic": sharpe_arith,
        "sharpe_arithmetic_interpretable": False,
        "mean_return_arithmetic": st.mean(rets) if rets else math.nan,
        "mean_return_log": st.mean(log_rets) if log_rets else math.nan,
        "compounding_factor": compounding,
        "equity_min_usd": min(equity_curve),
        "median_interval_hours": med_h,
        "periods_per_year": ppy,
        "n_deltas": len(deltas),
        "external_flow_events": 0,
        "caveat": (
            "AGREGAT semua lane (wallet), BUKAN Sharpe satu strategi. "
            f"{len(jumps)} lompatan >{int(jump_threshold*100)}% (likuidasi/freeze 30-Sep) "
            "SENGAJA tidak dibuang; sepuluh delta terburuk saja melebihi total kerugian. "
            "Pakai sharpe_ann_trading_only (log/geometrik); versi aritmetika positif "
            "secara palsu karena ekuitas menyusut. Snapshot equity<=0 dibuang."
        ),
        "rows": rows,
    }


def build_from_files(capital_path: Path = CAPITAL_REPORT, reconcile_path: Path = RECONCILE) -> dict[str, Any]:
    return build_series(load_capital_rows(capital_path), load_reconcile_events(reconcile_path))


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    result = build_from_files()
    out = REPORT_DIR / "sodex_normalized_equity_20261002.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True))
    print(json.dumps({
        "out": str(out),
        "n_rows": result.get("n_rows"),
        "total_normalized_pnl_usd": result.get("total_normalized_pnl_usd"),
        "sharpe_ann_6h_trading_only": result.get("sharpe_ann_6h_trading_only"),
        "large_observed_jump_count": result.get("large_observed_jump_count"),
    }, indent=2))


if __name__ == "__main__":
    main()
