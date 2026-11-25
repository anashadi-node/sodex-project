#!/usr/bin/env python3
"""
ANANTARA SAKTI — CEX Profitability Tracker (v1.0, 2026-08-23)
=============================================================
North Star monitor: is CEX-Binance actually achieving the
≥0.7% per swing cycle of TOTAL WALLET target? (F6: was 0.5% — wrong.)

Key distinction: the 0.7% target is NOT 0.7% of stake per trade.
It is 0.7% of the TOTAL WALLET per completed swing (1-30h hold).

With wallet=400 USDT and stake=20 USDT (5% of wallet per position):
  - 0.7% wallet gain = $2.80 per swing cycle
  - A ROI exit at 3% of stake (12h tier) earns $0.60 per trade → 0.15% of wallet
  - Multiple simultaneous positions can compound within one swing window
  - The 0.7% target requires either many concurrent positions OR high per-trade %

This module reports honestly how far the system is from that target.
It does NOT weaken the target or make excuses. If we are below 0.7%,
it reports the actual gap and grades it NEGATIVE or BELOW_TARGET.

Rules applied (from cex_target_framework.py):
  Rule 1 — Expectancy gate: does mean PnL clear a minimum floor?
  Rule 2 — Monthly projection: where does the achieved rate project to?
  Rule 5 — Drawdown halt: has accumulated loss breached the 8% halt threshold?
  Rule 6 — Wald SPRT: is the observed win rate statistically distinguishable
            from a coin flip (p0=0.45 H0 vs p1=0.58 H1)?

Output: freqtrade_user_data/data/binance/cex_profitability_report.json
Runs via daemon job_cex_profitability_report every 4h.
Pure stdlib + psycopg2 (same daemon env as cex_deep_loop.py).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from anantara.cex_target_framework import (
        expectancy_gate,
        wald_sprt,
        drawdown_halt,
        monthly_projection,
        NORTH_STAR_TARGET,
    )
except ImportError:
    from cex_target_framework import (  # type: ignore[no-redef]
        expectancy_gate,
        wald_sprt,
        drawdown_halt,
        monthly_projection,
        NORTH_STAR_TARGET,
    )

log = logging.getLogger(__name__)

_WALLET_USDT: float = float(os.environ.get("CEX_WALLET_USDT", "400"))
# F6 FIX (audit 2026-09-01): grade against the CANONICAL North Star target
# (0.8% of total wallet per 30h cycle), imported from cex_target_framework.py.
# Was hardcoded 0.005 mislabeled "(Astronacci CEX)" — wrong project AND wrong
# number; now single-sourced from the masterplan's ≥0.7% figure.
_TARGET_PER_CYCLE: float = NORTH_STAR_TARGET   # 0.8% of total wallet per 30h
_LOOKBACK_DAYS: int = 90           # full lookback for SPRT and 90d window
_RECENT_DAYS: int = 7              # short window for current regime read
_OUTPUT_FILE = "freqtrade_user_data/data/binance/cex_profitability_report.json"

# Expectancy gate floor: 10% of target (0.05%) — needs SOME positive expectancy
# even if not yet hitting the full 0.5% North Star on each trade
_E_GATE_FLOOR: float = _TARGET_PER_CYCLE * 0.10


def _get_pg_conn(dbname: str = "anantara"):
    import psycopg2
    env_path = (
        Path(os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti"))) / ".env"
    )
    env_vars: dict = {}
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip()
    except OSError:
        pass
    return psycopg2.connect(
        host=env_vars.get("POSTGRES_HOST", os.environ.get("POSTGRES_HOST", "localhost")),
        port=env_vars.get("POSTGRES_PORT", os.environ.get("POSTGRES_PORT", "5432")),
        dbname=dbname,
        user=env_vars.get("POSTGRES_USER", os.environ.get("POSTGRES_USER", "anantara")),
        password=env_vars.get("POSTGRES_PASSWORD",
                              os.environ.get("POSTGRES_PASSWORD", "")),
    )


def _fetch_closed_trades(lookback_days: int = _LOOKBACK_DAYS,
                         wallet_usdt: float = _WALLET_USDT) -> list[dict]:
    """Query PostgreSQL; return list of per-trade dicts with wallet-fraction PnL.

    Per-trade wallet PnL:
      close_profit (DB) = fraction of stake_amount (e.g. 0.03 = 3% of $20 = $0.60)
      wallet_frac = profit_abs / wallet_usdt = $0.60 / $400 = 0.0015 (0.15% of wallet)
    """
    try:
        conn = _get_pg_conn("anantara")
    except Exception as e:
        log.warning(f"[profit_tracker] DB connect failed: {e}")
        return []

    try:
        cur = conn.cursor()
        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        cur.execute(
            """
            SELECT
                pair,
                stake_amount,
                close_profit,
                close_date,
                open_date,
                exit_reason
            FROM trades
            WHERE strategy LIKE '%%AnantaraTrendFocused%%'
              AND is_open = FALSE
              AND close_date IS NOT NULL
              AND close_date >= %s
            ORDER BY close_date DESC
            """,
            (since,),
        )
        rows = cur.fetchall()
    except Exception as e:
        log.warning(f"[profit_tracker] query error: {e}")
        return []
    finally:
        conn.close()

    trades = []
    for pair, stake_amount, close_profit, close_date, open_date, exit_reason in rows:
        if close_profit is None or stake_amount is None:
            continue
        cd = close_date
        if hasattr(cd, "tzinfo") and cd.tzinfo is None:
            cd = cd.replace(tzinfo=timezone.utc)
        od = open_date
        if od and hasattr(od, "tzinfo") and od.tzinfo is None:
            od = od.replace(tzinfo=timezone.utc)

        stake = float(stake_amount)
        profit_frac = float(close_profit)    # fraction of stake
        profit_abs = stake * profit_frac     # absolute USDT
        wallet_frac = profit_abs / wallet_usdt  # fraction of total wallet

        hold_hours = None
        if od and cd:
            hold_hours = round((cd - od).total_seconds() / 3600, 1)

        trades.append({
            "pair": pair,
            "stake_usdt": stake,
            "profit_abs": round(profit_abs, 4),
            "wallet_frac": round(wallet_frac, 6),
            "close_date": cd,
            "exit_reason": exit_reason or "",
            "hold_hours": hold_hours,
        })

    return trades


def _window_stats(trades: list[dict], days: int,
                  now: datetime | None = None) -> dict:
    """Compute wallet-fraction PnL stats for trades within the last `days` window."""
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    subset = [t for t in trades if t["close_date"] >= cutoff]
    n = len(subset)
    target_pct = round(_TARGET_PER_CYCLE * 100, 3)   # 0.5%

    if n == 0:
        return {
            "n": 0,
            "mean_wallet_pct": 0.0,
            "total_wallet_pct": 0.0,
            "wins": 0,
            "wr": 0.0,
            "target_pct": target_pct,
            "vs_target": round(-target_pct, 3),
        }

    pnls = [t["wallet_frac"] for t in subset]
    wins = sum(1 for p in pnls if p > 0)
    total = sum(pnls)
    mean = total / n

    return {
        "n": n,
        "mean_wallet_pct": round(mean * 100, 4),     # % of wallet per cycle
        "total_wallet_pct": round(total * 100, 4),   # cumulative % gain over window
        "wins": wins,
        "wr": round(wins / n, 4),
        "target_pct": target_pct,
        "vs_target": round((mean - _TARGET_PER_CYCLE) * 100, 4),  # gap to target
    }


def _window30h_rollup(trades: list[dict], now: datetime | None = None) -> dict:
    """TARGET UTAMA resmi (definisi user 27-Sep-2026, clarified):
    SETIAP rentang 30 jam, divisi WAJIB memperoleh PNL KUMULATIF >= 0,8% dari
    TOTAL wallet (spot+future). Jadi yang di-grade adalah AKUMULASI per window
    30 jam berurutan (bukan mean per-trade). Window di-anchor mundur dari `now`
    agar deterministik: [now-30h, now), [now-60h, now-30h), dst.
    Window terakhir (berjalan/inkomplit) ditandai `in_progress` dan tidak
    menentukan FAIL sampai umurnya penuh 30 jam.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if not trades:
        return {"windows": [], "n_full": 0, "fails": 0, "on_target": None,
                "latest_complete_pct": None}
    closes = sorted((t["close_date"] for t in trades if t.get("close_date")))
    frac_by_date = {}
    for t in trades:
        cd = t.get("close_date")
        if cd is not None:
            frac_by_date[cd] = frac_by_date.get(cd, 0.0) + t["wallet_frac"]
    import math
    # jumlah window minimal yang mencakup seluruh data (lebar 30 jam)
    span_h = (now - closes[0]).total_seconds() / 3600.0
    n_win = max(1, math.ceil(span_h / 30.0))
    windows = []
    for k in range(n_win):
        end = now - timedelta(hours=30 * k)
        start = end - timedelta(hours=30)
        tot = sum(v for d, v in frac_by_date.items() if start <= d < end)
        # k=0 = window berjalan: angka bisa berubah sampai pos open di dalamnya
        # close — ditandai in_progress, TIDAK menentukan FAIL.
        windows.append({
            "start": start.isoformat(), "end": end.isoformat(),
            "cum_wallet_pct": round(tot * 100, 4),
            "target_pct": round(_TARGET_PER_CYCLE * 100, 3),
            "on_target": tot >= _TARGET_PER_CYCLE,
            "in_progress": k == 0,
        })
    full = [w for w in windows if not w["in_progress"]]
    fails = sum(1 for w in full if not w["on_target"])
    latest_full = full[0] if full else None
    return {
        "windows": windows[:8],                      # hemat: 8 window ~ 10 hari
        "n_full": len(full),
        "fails": fails,
        "on_target": (latest_full["on_target"] if latest_full else None),
        "latest_complete_pct": (latest_full["cum_wallet_pct"] if latest_full else None),
    }


def compute_report(wallet_usdt: float = _WALLET_USDT) -> dict:
    """Fetch closed trades; compute windows + framework rules; return report dict."""
    now = datetime.now(timezone.utc)
    trades = _fetch_closed_trades(wallet_usdt=wallet_usdt)

    # All-time pnls as wallet fractions (90d lookback)
    all_pnls = [t["wallet_frac"] for t in trades]
    n_all = len(all_pnls)

    # --- Rule 1: expectancy gate --------------------------------------------------
    # min_e set to 10% of North Star target (0.05%) — a lenient floor so the gate
    # fires only when expectancy is truly negligible, not just below the ambitious target.
    e_gate = expectancy_gate(all_pnls, min_e=_E_GATE_FLOOR)

    # --- Rule 6: Wald SPRT --------------------------------------------------------
    # H0: true WR = 0.45 (coin flip favoring bears — cautious null)
    # H1: true WR = 0.58 (meaningful edge)
    wins_all = sum(1 for p in all_pnls if p > 0)
    sprt = wald_sprt(wins_all, n_all, p0=0.45, p1=0.58, alpha=0.05, beta=0.10)

    # --- Rule 5: drawdown halt ----------------------------------------------------
    # Reconstruct equity curve from oldest to newest trade for running drawdown
    equity = [1.0]
    for t in reversed(trades):
        equity.append(equity[-1] * (1.0 + t["wallet_frac"]))
    dd = drawdown_halt(equity)

    # --- Rule 2: monthly projection -----------------------------------------------
    mean_all = sum(all_pnls) / n_all if n_all > 0 else 0.0
    proj = monthly_projection(mean_all)

    # --- Window stats -------------------------------------------------------------
    w7  = _window_stats(trades, 7,  now)
    w30 = _window_stats(trades, 30, now)
    w90 = _window_stats(trades, 90, now)
    # --- TARGET UTAMA (definisi user 27-Sep): kumulatif per rentang 30 jam -------
    w30h = _window30h_rollup(trades, now)

    # --- Grade ---------------------------------------------------------------------
    # Grade mengikuti definisi resmi: PNL KUMULATIF window 30 jam terakhir yang
    # sudah penuh >= target (0,8% total wallet). mean-7d HANYA dipakai fallback
    # bila belum ada window 30 jam penuh (data < 30 jam).
    target_pct = _TARGET_PER_CYCLE * 100               # 0.8
    eps = 1e-6                                         # float round-trip tolerance
    if w30h["latest_complete_pct"] is not None:
        cum = w30h["latest_complete_pct"]
        if cum >= target_pct - eps:
            grade = "ON_TARGET"
        elif cum >= target_pct * 0.5 - eps:
            grade = "APPROACHING_TARGET"
        elif cum > 0:
            grade = "POSITIVE_BELOW_TARGET"
        else:
            grade = "NEGATIVE"
    else:
        mean_7d_pct = w7["mean_wallet_pct"]            # % of wallet per cycle
        if mean_7d_pct >= target_pct - eps:
            grade = "ON_TARGET"
        elif mean_7d_pct >= target_pct * 0.5 - eps:
            grade = "APPROACHING_TARGET"
        elif mean_7d_pct > 0:
            grade = "POSITIVE_BELOW_TARGET"
        else:
            grade = "NEGATIVE"

    return {
        "generated_ts": now.isoformat(),
        "wallet_usdt": wallet_usdt,
        "target_per_cycle_pct": round(_TARGET_PER_CYCLE * 100, 3),  # 0.5
        "grade": grade,
        "7d":  w7,
        "30d": w30,
        "90d": w90,
        "window_30h": w30h,   # kumulatif per rentang 30 jam = definisi TARGET UTAMA
        "expectancy_gate": e_gate,
        "sprt": sprt,
        "drawdown": dd,
        "monthly_projection": proj,
        "n_total": n_all,
    }


def _resolve_output_path() -> Path:
    cwd = Path(os.environ.get("FREQTRADE_WORKDIR", "/home/USER/anantara-sakti"))
    p = cwd / _OUTPUT_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def run() -> dict:
    """Main entry: compute report, write JSON atomically, log summary."""
    report = compute_report()
    out_path = _resolve_output_path()
    try:
        tmp = out_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(report, indent=2, default=str))
        tmp.replace(out_path)
    except Exception as e:
        log.warning(f"[profit_tracker] write failed: {e}")

    grade   = report["grade"]
    w7      = report["7d"]
    n7      = w7["n"]
    mean7   = w7["mean_wallet_pct"]
    target  = report["target_per_cycle_pct"]
    sprt_d  = report["sprt"]["decision"]
    dd_val  = report["drawdown"]["dd"]

    log.info(
        f"[profit_tracker] {grade} | 7d mean={mean7:+.3f}%/cycle "
        f"(target={target:.1f}%) | n={n7} | SPRT={sprt_d} | DD={dd_val:.1%}"
    )
    if report["drawdown"]["halt"]:
        log.warning(f"[profit_tracker] ⚠ DRAWDOWN HALT: {dd_val:.1%} ≥ 8%")

    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import pprint
    pprint.pprint(run())
