#!/usr/bin/env python3
"""
ANANTARA SAKTI — Pre-Gain/Loser paper-trade simulator (pure core + backtest).

The bridge from "radar" to "is this actually tradeable for profit". The basic
validator (signal_tracker) only asks "did price drift the right way in 24h". This
asks the REAL question: if you had taken the trade setup (entry, -SL%, +TP%,
R:R), would it have PROFITED after fees — did it hit take-profit or stop-loss
first? That is the "probabilitas pasti" that must be MEASURED before any capital.

`simulate_trade` is a pure triple-barrier simulation (López de Prado style, same
discipline as the project's SoDEX scalp backtests): walk the forward price path,
first barrier touched wins (SL / TP / timeout). Conservative: a candle that spans
BOTH barriers is scored as a STOP-LOSS (pessimistic = honest). Stdlib only, tested.

Nothing here places a real order. It reads logged signals + historical candles
and reports honest expectancy. Live execution is a separate, gated, user-triggered
step that should only follow a PROVEN positive expectancy here.
"""
from __future__ import annotations

import time
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

try:
    from anantara import signal_tracker
except ImportError:                               # flat context
    import signal_tracker                          # type: ignore

# Default trade geometry — updated 2026-06-06 audit:
# IMPORTANT: SL=5% used in production (pregain_execution.py).
# The old DEFAULT_SL_PCT=7.0 was stale and caused edge stats to be computed
# with wrong geometry. Updated to match actual execution parameters.
DEFAULT_SL_PCT = 3.0     # v8.6: SL=3% optimal from 1,420-signal batch sweep (E=+1.014R)
DEFAULT_TP_PCT = 20.0    # take-profit (T1) distance %
# Round-trip taker fee + estimated funding cost for SHORT (24h hold):
# - Taker fee: 0.045% × 2 sides = 0.090%
# - Funding cost (SHORT, ~18%/yr avg): 18/365 = 0.049%/day
# - Total: 0.09 + 0.05 = 0.14% conservative estimate
DEFAULT_FEE_PCT     = 0.09    # round-trip taker fee only (for LONG positions)
DEFAULT_FUNDING_PCT = 0.05    # daily funding cost for SHORT (~18%/yr ÷ 365)


def simulate_trade(direction: str, entry: float, path: list[dict],
                   sl_pct: float = DEFAULT_SL_PCT, tp_pct: float = DEFAULT_TP_PCT,
                   fee_pct: float = DEFAULT_FEE_PCT,
                   funding_pct: float = 0.0) -> dict:
    """Simulate one trade through a forward price `path` (oldest→newest candles,
    each {high, low, close}). Triple-barrier; returns outcome + fee-adjusted P&L.

    outcome: 'TP' | 'SL' | 'TIMEOUT' | 'NODATA'
    realized_pct: signed % return in the trade direction, AFTER all costs.
    r_multiple: realized_pct / sl_pct (risk units; +3R is a clean TP at 1:3).

    `funding_pct`: additional cost per trade (e.g. funding rate for SHORT positions).
                   For SHORT: positive value = additional drag (you PAY funding).
                   Default 0 (backward-compatible). Use DEFAULT_FUNDING_PCT for SHORT.
    """
    d = direction.upper()
    if entry <= 0 or not path or d not in ("LONG", "SHORT"):
        return {"outcome": "NODATA", "realized_pct": 0.0, "r_multiple": 0.0, "bars": 0}

    if d == "LONG":
        sl, tp = entry * (1 - sl_pct / 100), entry * (1 + tp_pct / 100)
    else:
        sl, tp = entry * (1 + sl_pct / 100), entry * (1 - tp_pct / 100)

    total_cost = fee_pct + funding_pct   # all costs combined

    def _result(outcome: str, exit_px: float, bars: int) -> dict:
        move = (exit_px - entry) / entry * 100.0
        realized = (move if d == "LONG" else -move) - total_cost
        return {"outcome": outcome, "realized_pct": round(realized, 4),
                "r_multiple": round(realized / sl_pct, 3) if sl_pct > 0 else 0.0,
                "bars": bars}

    for i, c in enumerate(path, 1):
        hi, lo = c.get("high", 0), c.get("low", float("inf"))
        if hi <= 0 or lo == float("inf"):
            continue   # skip malformed candles — don't let bad data trigger barriers
        if d == "LONG":
            hit_sl, hit_tp = lo <= sl, hi >= tp
        else:
            hit_sl, hit_tp = hi >= sl, lo <= tp
        # Pessimistic rule: when a single candle spans BOTH barriers simultaneously,
        # we declare SL. This prevents optimistic backtesting where ambiguous candles
        # are resolved in the trader's favour. Conservative = honest.
        if hit_sl:
            return _result("SL", sl, i)
        if hit_tp:
            return _result("TP", tp, i)
    return _result("TIMEOUT", path[-1]["close"], len(path))


def aggregate(results: list[dict], grades: Optional[list[str]] = None) -> dict:
    """Aggregate simulated trades into honest expectancy stats.

    IMPORTANT: grades must be filtered in parallel with results to avoid
    misalignment when NODATA entries are removed. This function handles that
    internally — callers just pass raw results + grades lists of EQUAL LENGTH.

    Raises ValueError if len(results) != len(grades): a mismatch means some
    results would be matched to the wrong grade, producing silently corrupt
    expectancy-per-grade stats. Better to fail loudly than report wrong data.
    """
    if grades is not None:
        if len(results) != len(grades):
            raise ValueError(
                f"aggregate(): results ({len(results)}) and grades ({len(grades)}) "
                "must be the same length — any length mismatch would silently corrupt "
                "grade-level expectancy stats via misaligned zip()."
            )
        pairs = [(r, g) for r, g in zip(results, grades) if r["outcome"] != "NODATA"]
        res    = [p[0] for p in pairs]
        g_filt = [p[1] for p in pairs]
    else:
        res    = [r for r in results if r["outcome"] != "NODATA"]
        g_filt = None

    n = len(res)
    if not n:
        return {"n": 0}
    wins = [r for r in res if r["realized_pct"] > 0]
    tp   = sum(1 for r in res if r["outcome"] == "TP")
    sl   = sum(1 for r in res if r["outcome"] == "SL")
    to   = sum(1 for r in res if r["outcome"] == "TIMEOUT")
    avg_r = sum(r["r_multiple"] for r in res) / n
    out = {
        "n": n,
        "win_rate":        round(len(wins) / n * 100, 1),
        "tp_pct":          round(tp / n * 100, 1),
        "sl_pct":          round(sl / n * 100, 1),
        "timeout_pct":     round(to / n * 100, 1),
        "avg_realized_pct":round(sum(r["realized_pct"] for r in res) / n, 3),
        "expectancy_r":    round(avg_r, 3),
        "profitable":      avg_r > 0,
    }
    if g_filt:
        by = {}
        for g in ("S", "A", "B", "C"):
            sub = [r for r, gr in zip(res, g_filt) if gr == g]
            if sub:
                sw = [r for r in sub if r["realized_pct"] > 0]
                by[g] = {
                    "n":               len(sub),
                    "win_rate":        round(len(sw) / len(sub) * 100, 1),
                    "expectancy_r":    round(sum(x["r_multiple"]    for x in sub) / len(sub), 3),
                    "avg_realized_pct":round(sum(x["realized_pct"]  for x in sub) / len(sub), 3),
                }
        out["by_grade"] = by
    return out


# ── Local cache loader (imported once at module level, no sys.path pollution) ──
_load_candles_fn = None   # set lazily on first call

def _get_local_candles(coin: str, interval: str) -> list[dict]:
    """Return locally-cached candles if available, else [].

    Hasil di-memoize per (coin, interval): semula loader dijalankan ulang untuk
    SETIAP sinyal (11.003 sinyal = 11.003 pembacaan file) sehingga job gate
    mingguan tidak pernah selesai. Cache hanya untuk proses ini (tidak menahan
    perubahan data di disk antar-run).
    """
    return list(_memo_candles(coin, interval))


@lru_cache(maxsize=512)
def _memo_candles(coin: str, interval: str) -> tuple[dict, ...]:
    global _load_candles_fn
    if _load_candles_fn is None:
        try:
            import os, sys as _sys
            proj = os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti"))
            if proj not in _sys.path:
                _sys.path.insert(0, proj)
            from scripts.download_hl_history import load_candles  # type: ignore
            _load_candles_fn = load_candles
        except Exception:
            _load_candles_fn = lambda *_: []   # graceful: never try again
    try:
        return tuple(_load_candles_fn(coin, interval) or ())
    except Exception:
        return ()


# ── IO boundary (not unit-tested) ─────────────────────────────────────────────
_BUCKET_MS = 30 * 24 * 3600 * 1000          # jendela fetch candle: 30 hari
_EMPTY_BUCKETS: set[tuple[str, str, int]] = set()   # negative cache (coin, interval, bucket)


@lru_cache(maxsize=4096)
def _window_candles(coin: str, interval: str, bucket_start_ms: int, hl_api: str) -> tuple[dict, ...]:
    """Candle satu koin untuk satu jendela 30 hari (di-cache per proses)."""
    import httpx
    end = bucket_start_ms + _BUCKET_MS
    try:
        r = httpx.post(f"{hl_api}/info", timeout=15, json={
            "type": "candleSnapshot",
            "req": {"coin": coin, "interval": interval,
                    "startTime": bucket_start_ms, "endTime": end},
        })
        data = r.json()
    except Exception:
        return ()
    if not isinstance(data, list):
        return ()
    return tuple({"t": int(c["t"]), "h": float(c["h"]), "l": float(c["l"]),
                  "c": float(c["c"])} for c in data if c and "h" in c)


def fetch_path(coin: str, start_ts: int, hours: int = 24,
               interval: str = "1h", hl_api: str = "https://api.hyperliquid.xyz",
               cache_only: bool = False) -> list[dict]:
    """HL candles for `coin` from start_ts (unix sec) for `hours` → path candles.

    Priority: (1) local cache "4h" data (360d, offline-capable) →
              (2) local cache with requested interval →
              (3) live HL API (skipped when cache_only=True).

    Uses 4h candles as primary local source (360d available) before falling back
    to the API. 4h candles are conservative for triple-barrier (larger spans →
    more ambiguous candles → more SL calls = pessimistic = honest).
    cache_only=True: return [] instead of hitting API — for fast offline backtest.
    """
    start_ms = start_ts * 1000
    end_ms   = (start_ts + hours * 3600) * 1000

    # ── Try local 4h cache (360d coverage, primary local source) ──────────────
    local_4h = _get_local_candles(coin, "4h")
    if local_4h:
        sliced = [c for c in local_4h if start_ms <= c["t"] <= end_ms]
        if sliced:
            return [{"high": c["h"], "low": c["l"], "close": c["c"]} for c in sliced]

    # ── Try local with requested interval (e.g., if "1h" was downloaded later) ─
    if interval != "4h":
        local_req = _get_local_candles(coin, interval)
        if local_req:
            sliced = [c for c in local_req if start_ms <= c["t"] <= end_ms]
            if sliced:
                return [{"high": c["h"], "low": c["l"], "close": c["c"]} for c in sliced]

    if cache_only:
        return []

    # ── Ambil per-koin per-jendela 30 hari, bukan per-sinyal ──────────────────
    # Sebelumnya setiap sinyal memanggil API (5.396 sinyal = 5.396 request) →
    # job gate mingguan tak pernah selesai. Sekarang cukup ~1 request/coin/30h.
    _bucket = (start_ts * 1000 // _BUCKET_MS) * _BUCKET_MS
    _raw: list[dict] = []
    for _b in (_bucket, _bucket + _BUCKET_MS):
        if _b > end_ms:
            break
        _key = (coin, interval, _b)
        if _key in _EMPTY_BUCKETS:      # negative cache: jangan ulang request
            continue
        _c = _window_candles(coin, interval, _b, hl_api)
        if not _c:
            _EMPTY_BUCKETS.add(_key)
        _raw.extend(_c)
    _res = [c for c in _raw if start_ms <= c["t"] <= end_ms]
    if _res:
        return [{"high": c["h"], "low": c["l"], "close": c["c"]} for c in _res]
    if _raw:
        # Ada candle di jendela tetapi tidak di rentang sinyal → data memang tipis.
        return []

    # ── Fallback: satu request tepat pada rentang sinyal ───────────────────────
    import httpx
    r = httpx.post(f"{hl_api}/info", timeout=12, json={
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": interval, "startTime": start_ms, "endTime": end_ms},
    })
    data = r.json()
    if not isinstance(data, list):
        _EMPTY_BUCKETS.add((coin, interval, _bucket))
        return []
    if not data:
        _EMPTY_BUCKETS.add((coin, interval, _bucket))
        return []
    return [{"high": float(c["h"]), "low": float(c["l"]), "close": float(c["c"])}
            for c in data if c and "h" in c]


def backtest_logged(db_path: str | Path, fetch_path_fn: Callable[[str, int], list[dict]],
                    horizon_sec: int = 24 * 3600, now: Optional[int] = None,
                    sl_pct: float = DEFAULT_SL_PCT, tp_pct: float = DEFAULT_TP_PCT,
                    fee_pct: float = DEFAULT_FEE_PCT,
                    per_grade_params: dict | None = None,
                    session_filter: list[str] | None = None,
                    since_ts: Optional[int] = None,
                    last_n: Optional[int] = None,
                    direction_filter: Optional[str] = None,
                    score_min: Optional[int] = None,
                    score_max: Optional[int] = None,
                    score_exclude_range: Optional[tuple] = None,
                    sig_type_filter: Optional[str] = None,
                    exclude_dow: Optional[list] = None) -> dict:
    """Replay every logged signal that is ≥horizon old as a simulated trade.

    `fetch_path_fn(coin, ts)` returns the forward candle path.
    `per_grade_params`: optional {grade: {sl_pct, tp_pct}} for grade-specific geometry.
    `session_filter`: optional list of sessions to include, e.g. ["Asia", "EU"].
                      When set, only signals from those sessions are simulated.
    `since_ts`: optional unix timestamp — only signals after this are included.
    `last_n`: optional int — only use the N most recent resolved signals.
    `direction_filter`: optional "SHORT" or "LONG" — restrict to one direction.
                        Useful for Grade B where LONG is skip-gated in production.
    `score_min/score_max`: optional score range filter (inclusive).
    `score_exclude_range`: optional (lo, hi) tuple — exclude scores in [lo, hi].
    `exclude_dow`: optional list of SQLite strftime(%w) day values to exclude.
                   SQLite: 0=Sun, 1=Mon, ..., 6=Sat. Example: ['0','6'] = exclude weekend.
                   Use this to exclude gated days (Sat/Sun) from edge stats so the stats
                   reflect ACTUAL production-gate performance, not all historical signals.
    """
    now = int(now if now is not None else time.time())
    conn = signal_tracker.connect(db_path)
    try:
        q = ("SELECT coin,direction,entry_price,grade,ts,session,score "
             "FROM signal_log WHERE ts <= ?")
        params: list = [now - horizon_sec]
        if since_ts is not None:
            q += " AND ts >= ?"
            params.append(since_ts)
        if direction_filter is not None:
            q += " AND direction = ?"
            params.append(direction_filter.upper())
        if score_min is not None:
            q += " AND score >= ?"
            params.append(int(score_min))
        if score_max is not None:
            q += " AND score <= ?"
            params.append(int(score_max))
        if score_exclude_range is not None:
            lo, hi = int(score_exclude_range[0]), int(score_exclude_range[1])
            q += f" AND NOT (score >= {lo} AND score <= {hi})"
        if sig_type_filter is not None:
            q += " AND sig_type = ?"
            params.append(sig_type_filter)
        if exclude_dow:
            # strftime('%w', ts, 'unixepoch'): 0=Sun, 1=Mon, ..., 6=Sat
            placeholders = ",".join(f"'{d}'" for d in exclude_dow)
            q += f" AND strftime('%w', ts, 'unixepoch') NOT IN ({placeholders})"
        q += " ORDER BY ts DESC"
        if last_n is not None:
            q += f" LIMIT {int(last_n)}"
        rows = conn.execute(q, params).fetchall()
    finally:
        conn.close()
    results, grades = [], []
    for coin, direction, entry, grade, ts, session, score in rows:
        # Session filter: skip signals not in target sessions
        if session_filter and (session or "Unknown") not in session_filter:
            continue
        path = fetch_path_fn(coin, ts) or []
        # Per-grade SL/TP override (empirically tuned to each grade's behavior)
        if per_grade_params and grade in per_grade_params:
            gp = per_grade_params[grade]
            _sl = gp.get("sl_pct", sl_pct)
            _tp = gp.get("tp_pct", tp_pct)
        else:
            _sl, _tp = sl_pct, tp_pct
        # Add funding cost for SHORT positions (pays funding ~0.05%/day on HL)
        _funding = DEFAULT_FUNDING_PCT if direction.upper() == "SHORT" else 0.0
        results.append(simulate_trade(direction, entry, path, _sl, _tp, fee_pct, _funding))
        grades.append(grade)
    return aggregate(results, grades)


# Empirically derived optimal SL/TP per grade (updated 2026-06-04, 320 signals)
#
# Finding #7 (background scan, more complete data):
#   Grade S Asia+EU: SL=7%/TP=12% → E=+0.208R n=18 (best Asia+EU)
#   Grade S ALL:     SL=7%/TP=15% → E=+0.136R n=30 ← EDGE GATE TERBUKA!
#   Grade S ALL:     SL=7%/TP=10% → E=-0.239R (NEGATIF — jangan pakai)
#
#   TP=15% optimal untuk ALL sessions karena:
#   - Asia+EU WR tinggi (60%+) tapi TP=12% lebih sering hit dari TP=20%
#   - US/US_Asia sudah difilter oleh session gate di autotrader
#   - SL=7%/TP=15% ALL sessions: E=+0.136R ≥ 0.10R threshold → edge OPEN
#
# Grade C: SL=7%/TP=15% → E=+0.140R (n=112) — LIVE eligible
OPTIMAL_GRADE_PARAMS: dict[str, dict] = {
    # v8.6: SL=3% optimal from batch paper-trade sweep (E=+1.014R vs SL=5% E=+0.675R)
    "S": {"sl_pct": 3.0, "tp_pct": 20.0},
    "A": {"sl_pct": 3.0, "tp_pct": 20.0},
    "B": {"sl_pct": 3.0, "tp_pct": 20.0},
    "C": {"sl_pct": 3.0, "tp_pct": 20.0},
}


def format_report(rep: dict, sl_pct: float = DEFAULT_SL_PCT, tp_pct: float = DEFAULT_TP_PCT) -> str:
    """Human-readable paper-trade backtest report."""
    if not rep.get("n"):
        return ("📉 PAPER-TRADE BACKTEST: belum ada sinyal ≥24 jam untuk disimulasikan.\n"
                "   Biarkan radar mengumpulkan sinyal dulu (validate-first).")
    be = round(100 / (1 + tp_pct / sl_pct), 1)    # break-even win-rate for this R:R
    verdict = ("✅ EXPECTANCY POSITIF — setup layak dilanjutkan (validasi terus)"
               if rep["profitable"] else
               "❌ EXPECTANCY NEGATIF — setup ini RUGI setelah fee → JANGAN tradingkan")
    L = [f"📊 PAPER-TRADE BACKTEST (triple-barrier, R:R 1:{tp_pct/sl_pct:.0f}, fee {DEFAULT_FEE_PCT}%)",
         f"   n={rep['n']} trades simulasi  |  win-rate {rep['win_rate']}% "
         f"(break-even {be}%)",
         f"   TP {rep['tp_pct']}% · SL {rep['sl_pct']}% · timeout {rep['timeout_pct']}%",
         f"   avg P&L/trade {rep['avg_realized_pct']}%  |  EXPECTANCY {rep['expectancy_r']}R",
         f"   → {verdict}"]
    if rep.get("by_grade"):
        L.append("   Per grade:")
        for g, b in rep["by_grade"].items():
            wr_str = f"win {b['win_rate']}%" if b.get("win_rate") is not None else ""
            L.append(f"     {g}: n={b['n']:>3}  {b['expectancy_r']:+.2f}R  {wr_str}")
    L.append("   Catatan: butuh ≥30-50 trade sebelum dipercaya. Candle ambigu = SL (pesimis/jujur).")
    return "\n".join(L)


def rolling_edge_report(db_path: str | Path,
                        fetch_path_fn: Callable[[str, int], list[dict]],
                        grade: str = "C",
                        windows: tuple[int, ...] = (20, 40, 80),
                        horizon_sec: int = 24 * 3600,
                        now: Optional[int] = None) -> str:
    """Rolling-window edge stability report for one grade.

    Filters to grade-specific signals first, then takes the N most recent —
    so last-40 means the 40 most recent Grade X signals (not 40 mixed signals).
    Helps detect edge drift/degradation before capital is at risk.

    Returns a formatted multi-line string suitable for Telegram or CLI.
    """
    _now = int(now if now is not None else time.time())
    conn = signal_tracker.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT coin, direction, entry_price, ts, session "
            "FROM signal_log WHERE grade=? AND ts <= ? ORDER BY ts DESC",
            (grade, _now - horizon_sec)
        ).fetchall()
    finally:
        conn.close()

    total_n = len(rows)
    gp = OPTIMAL_GRADE_PARAMS.get(grade, {})
    _sl = gp.get("sl_pct", DEFAULT_SL_PCT)
    _tp = gp.get("tp_pct", DEFAULT_TP_PCT)

    def _eval_window(subset: list) -> dict:
        res = []
        for coin, direction, entry, ts, _ in subset:
            path = fetch_path_fn(coin, ts) or []
            res.append(simulate_trade(direction, entry, path, _sl, _tp, DEFAULT_FEE_PCT))
        valid = [r for r in res if r["outcome"] != "NODATA"]
        if not valid:
            return {"n": 0}
        wins = sum(1 for r in valid if r["realized_pct"] > 0)
        avg_r = sum(r["r_multiple"] for r in valid) / len(valid)
        return {
            "n": len(valid),
            "win_rate": round(wins / len(valid) * 100, 1),
            "expectancy_r": round(avg_r, 3),
        }

    lines = [f"📈 ROLLING EDGE — Grade {grade} SL={_sl}%/TP={_tp}% (cache-only)"]
    lines.append(f"   Total resolved Grade {grade}: {total_n}")

    for w in windows:
        subset = rows[:w]
        stats = _eval_window(subset)
        n = stats.get("n", 0)
        if n < 5:
            lines.append(f"   last-{w:>3}: n={n} (terlalu sedikit untuk cache-only)")
            continue
        e = stats.get("expectancy_r", 0.0)
        wr = stats.get("win_rate", 0.0)
        trend = "✅" if e > 0.05 else ("⚠️" if e > 0 else "❌")
        lines.append(f"   last-{w:>3}: n={n:>3}  E={e:+.3f}R  WR={wr:.1f}%  {trend}")

    lines.append(f"   (last-N = N most recent Grade {grade} signals; NODATA = no local cache)")
    return "\n".join(lines)


# ── K-5: OHLC Triple-Barrier Outcome Resolution ─────────────────────────────
# Audit finding: snapshot outcome (price at T+24h) inflates WR by ±10pp.
# This function replaces signal_tracker.backfill_outcomes() for Pre-Gain signals.
# Uses simulate_trade() — the same triple-barrier engine as backtest_logged() —
# so the "edge stats" and "live outcomes" are measured on the SAME yardstick.
# Conservative: candle spanning BOTH barriers = SL (pessimistic = honest).

def backfill_outcomes_ohlc(db_path: str | Path,
                           fetch_path_fn: Callable[[str, int], list[dict]],
                           horizon_sec: int = 24 * 3600,
                           sl_pct: float = DEFAULT_SL_PCT,
                           tp_pct: float = DEFAULT_TP_PCT,
                           fee_pct: float = DEFAULT_FEE_PCT,
                           funding_pct: float = 0.0,
                           now: Optional[int] = None,
                           sig_type_filter: Optional[str] = None,
                           sig_type_exclude: Optional[str] = None,
                           ) -> int:
    """Resolve unresolved signals using OHLC triple-barrier simulation.

    Unlike signal_tracker.backfill_outcomes() which uses a single close price
    at T+24h (snapshot method, inflates WR ±10pp), THIS function walks the full
    forward price path and applies the same triple-barrier logic as
    simulate_trade() — SL, TP, TIMEOUT, with the pessimistic ambiguous-candle rule.

    Args:
      db_path        : path to signal_log SQLite DB
      fetch_path_fn  : (coin, signal_ts) → list[dict] of {high, low, close} candles
      horizon_sec    : how far forward to look (default 24h)
      sl_pct, tp_pct : trade geometry (default 3%/20% per doctrine)
      fee_pct        : round-trip taker fee (default 0.09%)
      funding_pct    : daily funding cost for SHORT positions (default 0.05%)
      sig_type_filter/exclude : same as backfill_outcomes()

    Returns number of signals resolved this call.
    """
    import sqlite3 as _sql
    _now = int(now if now is not None else time.time())
    _cutoff = _now - horizon_sec
    conn = _sql.connect(str(db_path))
    resolved = 0
    try:
        # Ensure schema has required columns (idempotent)
        conn.executescript(signal_tracker._SCHEMA)
        q = ("SELECT id, coin, direction, entry_price, ts, sig_type FROM signal_log "
             "WHERE outcome_pct IS NULL AND ts <= ?")
        params: list = [_cutoff]
        if sig_type_filter is not None:
            q += " AND sig_type = ?"
            params.append(sig_type_filter)
        if sig_type_exclude is not None:
            q += " AND (sig_type IS NULL OR sig_type != ?)"
            params.append(sig_type_exclude)
        rows = conn.execute(q, params).fetchall()

        for sid, coin, direction, entry, signal_ts, sig_type in rows:
            if entry <= 0:
                continue
            path = fetch_path_fn(coin, signal_ts)
            if not path:
                continue  # no candle data → can't resolve yet

            # SHORT signals pay funding; LONG signals don't
            _fund = funding_pct if (direction or "").upper() == "SHORT" else 0.0
            result = simulate_trade(direction, entry, path,
                                    sl_pct=sl_pct, tp_pct=tp_pct,
                                    fee_pct=fee_pct, funding_pct=_fund)
            if result["outcome"] == "NODATA":
                continue

            conn.execute(
                "UPDATE signal_log SET outcome_pct=?, correct=?, outcome_ts=? WHERE id=?",
                (round(result["realized_pct"], 4),
                 1 if result["realized_pct"] > 0 else 0,
                 _now, sid),
            )
            resolved += 1
        conn.commit()
        return resolved
    finally:
        conn.close()


# ── Sovereign validation integration ──────────────────────────────────────────

def sharpe_stats(results: list[dict]) -> dict:
    """Compute Sharpe-related statistics from simulate_trade results.

    Used by pregain_validation_gates (Gate 2 MinBTL, Gate 5 Bootstrap CI).
    Returns dict with: n, mean_r, std_r, sr_annualized, skewness, excess_kurtosis.
    Pure stdlib — matches pregain_validation_gates._moments() interface.
    """
    import math
    valid = [r["r_multiple"] for r in results if r["outcome"] != "NODATA"]
    n = len(valid)
    if n < 2:
        return {"n": n, "mean_r": 0.0, "std_r": 1.0,
                "sr_annualized": 0.0, "skewness": 0.0, "excess_kurtosis": 0.0}
    mu = sum(valid) / n
    var = sum((x - mu) ** 2 for x in valid) / max(n - 1, 1)
    std = var ** 0.5 or 1e-9
    sr = mu / std * math.sqrt(252.0)
    skew = (sum((x - mu) ** 3 for x in valid) / n) / (std ** 3) if n >= 3 else 0.0
    kurt = (sum((x - mu) ** 4 for x in valid) / n) / (std ** 4) - 3.0 if n >= 4 else 0.0
    return {
        "n": n, "mean_r": round(mu, 4), "std_r": round(std, 4),
        "sr_annualized": round(sr, 3), "skewness": round(skew, 3),
        "excess_kurtosis": round(kurt, 3),
    }


def run_sovereign_gates(db_path: str | Path,
                         fetch_path_fn: Callable[[str, int], list[dict]],
                         horizon_sec: int = 24 * 3600,
                         now: Optional[int] = None,
                         live_db_path: Optional[str | Path] = None,
                         since_ts: Optional[int] = None,
                         verbose: bool = False) -> dict:
    """Full Pre-Gain Sovereign 10-gate validation run.

    Reads signal DB → simulates resolved trades → runs 10 Sovereign Gates.

    Args:
      since_ts : unix timestamp — include only signals logged AFTER this time.
                 Use to filter to post-gate-implementation signals only.
                 CLI: --since 2026-06-03  (converts to unix ts automatically).
                 Recommended: 1780444800 (2026-06-03 00:00 UTC) — when empirical
                 gates (B-mid skip, direction, time gates) were all active.
                 (⚠️ FIX 2026-08-08: sebelumnya 1748908800 = 2025-06-03, SALAH)

    Extra columns required from signal_log (schema v2):
      session, patterns + implicit: grade, direction, score
    """
    _now = int(now if now is not None else time.time())

    conn = signal_tracker.connect(db_path)
    try:
        if since_ts is not None:
            rows = conn.execute(
                """SELECT coin, direction, entry_price, grade, ts,
                          score, session, patterns
                   FROM signal_log WHERE ts <= ? AND ts >= ?
                   ORDER BY ts ASC""",
                (_now - horizon_sec, int(since_ts))
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT coin, direction, entry_price, grade, ts,
                          score, session, patterns
                   FROM signal_log WHERE ts <= ?
                   ORDER BY ts ASC""",
                (_now - horizon_sec,)
            ).fetchall()
    finally:
        conn.close()

    results, grades, scores, sessions, directions = [], [], [], [], []
    for coin, direction, entry, grade, ts, score, session, patterns in rows:
        path = fetch_path_fn(coin, ts) or []
        # Use optimal grade params
        gp = OPTIMAL_GRADE_PARAMS.get(grade or "C", {})
        _sl = gp.get("sl_pct", DEFAULT_SL_PCT)
        _tp = gp.get("tp_pct", DEFAULT_TP_PCT)
        _funding = DEFAULT_FUNDING_PCT if (direction or "").upper() == "SHORT" else 0.0
        res = simulate_trade(direction, entry, path, _sl, _tp, DEFAULT_FEE_PCT, _funding)
        # Metadata untuk gate yang butuh konteks per-sinyal (mis. Gate 8 per arah)
        res.update({"direction": (direction or "SHORT").upper(),
                    "coin": coin, "ts": ts, "score": int(score) if score else 75})
        results.append(res)
        grades.append(grade or "C")
        scores.append(int(score) if score else 75)
        sessions.append(session or "Unknown")
        directions.append(direction or "SHORT")

    bt_stats = aggregate(results, grades)

    # Load live forward-test data if provided
    live_results, live_grades = [], []
    if live_db_path:
        try:
            live_conn = signal_tracker.connect(live_db_path)
            live_rows = live_conn.execute(
                "SELECT coin, direction, entry_price, grade, ts FROM signal_log "
                "WHERE ts > ? AND ts <= ?",
                (_now - 14 * 24 * 3600, _now - horizon_sec)  # last 14d live window
            ).fetchall()
            live_conn.close()
            for coin, direction, entry, grade, ts in live_rows:
                path = fetch_path_fn(coin, ts) or []
                res = simulate_trade(direction, entry, path)
                live_results.append(res)
                live_grades.append(grade or "C")
        except Exception:
            pass

    try:
        from anantara import pregain_validation_gates as pvg
    except ImportError:
        import pregain_validation_gates as pvg  # type: ignore

    verdict = pvg.run_all_gates(
        results=results,
        grades=grades,
        scores=scores,
        sessions=sessions,
        directions=directions,
        live_results=live_results,
        live_grades=live_grades,
        backtest_stats=bt_stats,
        verbose=verbose,
    )

    # K4 FIX: auto-save verdict so pregain_autotrader can enforce it.
    # Gates returned NO_GO on Jun 4 but live started Jun 6 — this closes that gap.
    # Saved to data/pregain_sovereign_verdict.json; read by _read_sovereign_verdict().
    import json as _json
    import os as _os
    _verdict_path = (
        Path(_os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti")))
        / "data" / "pregain_sovereign_verdict.json"
    )
    try:
        _verdict_path.parent.mkdir(parents=True, exist_ok=True)
        _tmp = _verdict_path.with_suffix(".tmp")
        _tmp.write_text(_json.dumps({
            "verdict":       verdict["verdict"],
            "passed_gates":  verdict["passed_gates"],
            "total_gates":   verdict["total_gates"],
            "saved_ts":      int(time.time()),
            "n_signals":     len(results),
        }, indent=2))
        _tmp.replace(_verdict_path)
    except Exception:
        pass  # non-fatal: loss of K4 enforcement if filesystem unavailable

    return verdict


if __name__ == "__main__":
    import argparse, os as _os
    _db = _os.environ.get("ANANTARA_SIGNAL_DB",
                          str(Path.home() / ".local/share/anantara/signals.db"))
    ap = argparse.ArgumentParser(description="Pre-Gain backtest + Sovereign Gates")
    ap.add_argument("--gates", action="store_true",
                    help="jalankan 10 Sovereign Gates validation")
    ap.add_argument("--since", metavar="DATE",
                    help="filter sinyal sejak tanggal (YYYY-MM-DD atau unix ts). "
                         "Gunakan 2026-06-03 untuk hanya signal post-gate-implementation.")
    ap.add_argument("--db", default=_db, help="path ke signal DB")
    args = ap.parse_args()

    # Parse --since: accept YYYY-MM-DD or unix timestamp
    _since_ts: Optional[int] = None
    if args.since:
        try:
            _since_ts = int(args.since)           # unix timestamp
        except ValueError:
            from datetime import datetime, timezone
            try:
                dt = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                _since_ts = int(dt.timestamp())
            except ValueError:
                print(f"ERROR: --since format tidak valid: {args.since!r}. Gunakan YYYY-MM-DD.")
                raise SystemExit(1)

    if args.gates:
        _label = f"sejak {args.since}" if args.since else "semua historical"
        print(f"🔬 Sovereign Gates — {_label} signals\n")
        verdict = run_sovereign_gates(args.db, fetch_path,
                                      since_ts=_since_ts, verbose=True)
        print(f"\n{'═'*60}")
        print(f"Verdict: {verdict['verdict']} ({verdict['passed_gates']}/{verdict['total_gates']} gates)")
        if _since_ts:
            total = len([r for r in verdict.get("gate_dicts", []) if r])
            print(f"Filter: signals ts ≥ {_since_ts} ({args.since})")
    else:
        rep = backtest_logged(args.db, fetch_path)
        print(format_report(rep))
