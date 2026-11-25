#!/usr/bin/env python3
"""
ANANTARA SAKTI — Autonomous Pre-Gain Research & Improvement Engine v1.0

Runs 24/7 via daemon scheduler. Learns from accumulated live signals,
detects edge improvements, applies safe autonomous fixes, and sends
comprehensive research reports to Telegram.

DESIGN PRINCIPLES (scientific discipline):
  1. Evidence-first: no change without n≥30 resolved signals
  2. Conservative: only WIDEN gates autonomously, never narrow blindly
  3. Weekday-only: exclude Sat/Sun from all edge computations
  4. Transparency: every finding logged to JSONL + sent to Telegram
  5. Human-in-loop: major gate changes → recommendation only, not auto-apply

AUTONOMOUS ACTIONS (safe, applied automatically):
  • Coin boost updates: coin E(R) ≥ 1.5R n≥30 → add/update in boost list
  • Coin block updates: coin WR < 35% avg<-3% n≥30 → add to block list
  • Learner refresh: update per-pattern/coin/session weights

RECOMMENDATION ONLY (Telegram alert, human applies):
  • New DOW gates (new day showing WR < 50%)
  • Session gate changes
  • Grade threshold changes
  • Score band adjustments

Pure stdlib — no external deps.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev

# ── Config ────────────────────────────────────────────────────────────────────
SIGNAL_DB   = os.environ.get("ANANTARA_SIGNAL_DB",
              str(Path.home() / ".local/share/anantara/signals.db"))
RESEARCH_LOG = Path.home() / ".local/share/anantara/auto_research.jsonl"
COIN_AUDIT_STATE = Path.home() / ".local/share/anantara/coin_audit_state.json"

MIN_N_COIN          = 30   # minimum signals per coin for all-time decisions
_MIN_N_COIN_ROLLING = 20   # lower minimum for rolling-window coin analysis (7d window has fewer resolved signals per coin)
MIN_N_DOW     = 50    # minimum signals per DOW category
MIN_N_SESSION = 40    # minimum per session
BLOCK_WR_MAX  = 0.35  # WR < 35% → candidate for block
BOOST_ER_MIN  = 0.40  # E(R) ≥ 0.40R → candidate for boost (was 1.5R — old formula inflated by ~2×)
BOOST_WR_MIN  = 0.65  # WR ≥ 65% also required
DEGRADE_SIGMA = 2.0   # alert if recent WR drops > 2 sigma below historical

# v11.0 K3/K5 fix: actual SL used in production (matches pregain_execution.SL_PCT_DEFAULT).
# E(R) is computed as avg_pct / _SL_PCT (empirical payoff in risk units), not a theoretical ratio.
# Old formula: wr×4.0 - (1-wr) assumed TP/SL=20%/5%=4:1 — WRONG (actual live payoff 1.31:1).
_SL_PCT = 3.0

# Rolling window for research functions (7d = exclude W22 crash week).
# See pregain_autotrader._EDGE_ROLLING_DAYS for the same rationale.
_RESEARCH_ROLLING_DAYS = 7


# ── Statistical helpers (FDR correction) ──────────────────────────────────────

def _norm_cdf(z: float) -> float:
    """Standard normal CDF P(Z ≤ z) using math.erf."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _binom_lower_pval(wins: int, n: int, p0: float = 0.5) -> float:
    """One-sided lower-tail binomial p-value P(X ≤ wins | n, p0).
    Uses normal approximation with continuity correction.
    Returns 1.0 for n < 10 (insufficient data — normal approximation unreliable).
    v11.1: threshold lowered 20→10 to catch extreme cases like 0/11 wins (BTC SHORT p=0.001).
    """
    if n < 10:
        return 1.0
    # Continuity correction: P(X ≤ wins) ≈ Φ((wins+0.5 - n*p0) / sqrt(n*p0*(1-p0)))
    z = (wins + 0.5 - n * p0) / math.sqrt(n * p0 * (1 - p0))
    return _norm_cdf(z)


def _binom_upper_pval(wins: int, n: int, p0: float = 0.5) -> float:
    """One-sided upper-tail binomial p-value P(X ≥ wins | n, p0).
    Returns 1.0 for n < 10 (insufficient data).
    v11.1: threshold lowered 20→10 (symmetrical with _binom_lower_pval).
    """
    if n < 10:
        return 1.0
    z = (wins - 0.5 - n * p0) / math.sqrt(n * p0 * (1 - p0))
    return 1.0 - _norm_cdf(z)


def _benjamini_hochberg(pvalues: list, q: float = 0.05) -> list:
    """Benjamini-Hochberg FDR correction at level q.
    Returns list[bool] where True = H0 rejected (significant after correction).

    Procedure: sort p-values ascending; find largest k s.t. p_(k) ≤ (k/m)*q;
    reject all H0 for i ≤ k. Controls FDR at level q (not per-test α=0.05).

    With 100 coins at α=0.05: expect 5 false positives. BH controls the
    expected proportion of false discoveries, not the per-test error rate.
    """
    m = len(pvalues)
    if m == 0:
        return []
    indexed = sorted(enumerate(pvalues), key=lambda x: x[1])
    cutoff_k = 0
    for rank, (_, pval) in enumerate(indexed, 1):
        if pval <= (rank / m) * q:
            cutoff_k = rank
    significant = [False] * m
    for rank, (orig_idx, _) in enumerate(indexed, 1):
        if rank <= cutoff_k:
            significant[orig_idx] = True
    return significant


def _regime_gate_status() -> tuple[bool, float | None, int]:
    """Check current regime gate. Returns (gate_active, rolling_3d_wr, n).

    Wraps _compute_regime_gate() from pregain_autotrader. Falls back to
    (False, None, 0) on import error so auto_research stays operational.
    """
    try:
        try:
            from anantara.pregain_autotrader import _compute_regime_gate
        except ImportError:
            from pregain_autotrader import _compute_regime_gate  # type: ignore
        return _compute_regime_gate(SIGNAL_DB)
    except Exception:
        return False, None, 0


# ── Logging ───────────────────────────────────────────────────────────────────
def _log(event: str, data: dict) -> None:
    try:
        RESEARCH_LOG.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": int(time.time()), "utc": datetime.now(timezone.utc).isoformat(),
               "event": event, **data}
        with open(RESEARCH_LOG, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        pass


# ── DB helpers ────────────────────────────────────────────────────────────────
def _connect() -> sqlite3.Connection:
    try:
        from anantara import signal_tracker
        return signal_tracker.connect(SIGNAL_DB)
    except ImportError:
        import signal_tracker  # type: ignore
        return signal_tracker.connect(SIGNAL_DB)


def _query(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list:
    try:
        c = conn.cursor()
        c.execute(sql, params)
        return c.fetchall()
    except Exception:
        return []


# ── Core analysis functions ───────────────────────────────────────────────────

def edge_stats_by_grade(weekday_only: bool = True,
                        rolling_days: int = _RESEARCH_ROLLING_DAYS) -> dict:
    """Compute weekday-only edge stats per grade for SHORT signals.
    Returns {grade: {n, wr, avg_pct, expectancy_r, trend_last30}}.

    rolling_days: if >0, only include signals from the last N days (default 7d).
    Set rolling_days=0 for all-time stats.
    """
    conn = _connect()
    try:
        dow_filter = "AND strftime('%w', datetime(ts,'unixepoch')) NOT IN ('0','6')" if weekday_only else ""
        since_ts = int(time.time()) - rolling_days * 86400 if rolling_days > 0 else 0
        since_filter = f"AND ts >= {since_ts}" if rolling_days > 0 else ""
        results = {}
        for grade in ("S", "B", "C", "A"):
            rows = _query(conn, f"""
                SELECT correct, outcome_pct FROM signal_log
                WHERE correct IS NOT NULL AND sig_type='SHORT' AND grade=?
                {dow_filter} {since_filter} ORDER BY ts DESC
            """, (grade,))
            if not rows:
                continue
            n = len(rows)
            wins = sum(1 for r in rows if r[0] == 1)
            wr = wins / n
            pcts = [r[1] for r in rows if r[1] is not None]
            avg_pct = mean(pcts) if pcts else 0.0
            # v11.0 K3/K5: use empirical avg_pct / SL_PCT (not theoretical 4:1 ratio).
            # Old: wr×4.0-(1-wr) assumed TP=20%/SL=5% ALWAYS hit — but TP=20% never fires.
            # New: avg_pct captures actual TSL/SL/ROI exits from signal_log.
            e_r = avg_pct / _SL_PCT
            # Recent trend (last 30)
            last30 = rows[:30]
            wr30 = sum(1 for r in last30 if r[0] == 1) / len(last30) if last30 else wr
            results[grade] = {"n": n, "wr": round(wr, 4), "avg_pct": round(avg_pct, 2),
                               "expectancy_r": round(e_r, 3), "wr_last30": round(wr30, 4)}
        return results
    finally:
        conn.close()


def coin_performance_audit(rolling_days: int = _RESEARCH_ROLLING_DAYS) -> dict:
    """Per-coin E(R), WR, n — weekday SHORT only, rolling window.
    Returns {coin: {n, wr, avg_pct, e_r, p_block, p_boost, action}}.

    v11.0 K3: Benjamini-Hochberg FDR correction applied to BLOCK candidates.
    With 100+ coins at α=0.05, expect 5 false positives without correction.

    v11.5 K14 fix: two-tier minimum sample size —
      rolling window (7d): _MIN_N_COIN_ROLLING=20 (7d has fewer resolved signals per coin)
      all-time: MIN_N_COIN=30
    BH q=0.10 for rolling window (slightly permissive — false negative cost > false positive
    for BLOCK; q=0.05 for all-time analysis).

    v11.5 K14 fix: BLOCK condition uses e_r < -0.5 (was avg_pct < -3.0).
      Old: required avg loss ≥ -3.0% — missed coins like PUMP (avg=-2.24%) despite WR=26%.
      New: uses E(R) in risk units; -0.5R equivalent = avg_pct=-1.5% → more permissive.

    v11.0 K3: E(R) = avg_pct / SL_PCT (empirical, not theoretical 4:1 ratio).
    v11.0 rolling_days: default 7d to exclude W22 crash-week dominance.
    """
    conn = _connect()
    try:
        since_ts = int(time.time()) - rolling_days * 86400 if rolling_days > 0 else 0
        since_filter = f"AND ts >= {since_ts}" if rolling_days > 0 else ""
        # v11.5 K14: use lower minimum for rolling window (fewer resolved signals per coin in 7d)
        min_n = _MIN_N_COIN_ROLLING if rolling_days > 0 else MIN_N_COIN
        # v11.5 K14: use q=0.10 for rolling BH — false negative cost > false positive for BLOCK
        bh_q_block = 0.10 if rolling_days > 0 else 0.05
        rows = _query(conn, f"""
            SELECT coin, COUNT(*),
                ROUND(AVG(CASE WHEN correct=1 THEN 1.0 ELSE 0.0 END),4),
                ROUND(AVG(outcome_pct),3)
            FROM signal_log
            WHERE correct IS NOT NULL AND sig_type='SHORT'
              AND strftime('%w', datetime(ts,'unixepoch')) NOT IN ('0','6')
              {since_filter}
            GROUP BY coin HAVING COUNT(*) >= ?
            ORDER BY COUNT(*) DESC
        """, (min_n,))

        # Load current block/boost lists — v8.5: direct import replaces inspect.getsource()
        try:
            from anantara.pregain_autotrader import COIN_BLOCK, COIN_ELITE_ALL
            current_block = COIN_BLOCK
            current_elite = COIN_ELITE_ALL
        except ImportError:
            from pregain_autotrader import COIN_BLOCK, COIN_ELITE_ALL  # type: ignore
            current_block = COIN_BLOCK
            current_elite = COIN_ELITE_ALL

        if not rows:
            return {}

        # v11.0 K3: compute p-values for all coins, then apply BH FDR correction.
        # BLOCK: H0 = wr ≥ 0.50 (not underperforming); one-sided lower-tail test.
        # BOOST: H0 = wr ≤ 0.65 (not elite); one-sided upper-tail test at p0=0.65.
        coins_data = [(coin, int(n), float(wr or 0), float(avg_pct or 0))
                      for coin, n, wr, avg_pct in rows]
        block_pvals = [_binom_lower_pval(int(wr * n), n, p0=0.50)
                       for _, n, wr, _ in coins_data]
        boost_pvals = [_binom_upper_pval(int(wr * n), n, p0=0.65)
                       for _, n, wr, _ in coins_data]
        block_sig = _benjamini_hochberg(block_pvals, q=bh_q_block)
        boost_sig = _benjamini_hochberg(boost_pvals, q=0.05)

        results = {}
        for i, (coin, n, wr, avg_pct) in enumerate(coins_data):
            e_r = avg_pct / _SL_PCT  # v11.0: empirical ratio, not theoretical 4:1
            p_block = round(block_pvals[i], 4)
            p_boost = round(boost_pvals[i], 4)
            # Classify action — BH significance required for block/boost decisions.
            # v11.5 K14: BLOCK condition uses e_r < -0.5 (replaces avg_pct < -3.0).
            #   -0.5R = -1.5% avg at SL=3% — catches sub-breakeven coins missed by strict -3% threshold.
            if wr < BLOCK_WR_MAX and e_r < -0.5 and block_sig[i] and coin not in current_block:
                action = "BLOCK_CANDIDATE"
            elif e_r >= BOOST_ER_MIN and wr >= BOOST_WR_MIN and boost_sig[i] and coin not in current_elite:
                action = "BOOST_CANDIDATE"
            elif coin in current_block and (wr >= 0.55 or e_r > 0.3):
                action = "UNBLOCK_CANDIDATE"
            elif coin in current_elite and e_r < 0.0:
                action = "DEBOOST_CANDIDATE"
            elif e_r < 0:
                action = "WATCH_NEGATIVE"
            else:
                action = "OK"
            results[coin] = {
                "n": n, "wr": round(wr, 4), "avg_pct": round(avg_pct, 2),
                "e_r": round(e_r, 3), "action": action, "p_block": p_block, "p_boost": p_boost,
                "in_block": coin in current_block, "in_elite": coin in current_elite
            }
        return results
    finally:
        conn.close()


def dow_performance_audit(rolling_days: int = _RESEARCH_ROLLING_DAYS) -> dict:
    """DOW × weekday SHORT performance. Returns rolling window vs all-time comparison.

    v11.0 K3: Shows rolling 7d WR alongside all-time WR. If |delta| > 20pp,
    flags an INVERSION (e.g. Thu 92%→8% in W23 = regime-specific DOW flip).
    Critical for detecting W23-type DOW inversions before over-boosting bad days.

    v11.0 K3: E(R) = avg_pct / SL_PCT (empirical, not theoretical 4:1 ratio).
    """
    conn = _connect()
    try:
        def _fetch(since_filter: str) -> dict:
            rows = _query(conn, f"""
                SELECT strftime('%w', datetime(ts,'unixepoch')) as dow,
                    COUNT(*),
                    ROUND(AVG(CASE WHEN correct=1 THEN 1.0 ELSE 0.0 END)*100,1),
                    ROUND(AVG(outcome_pct),2)
                FROM signal_log
                WHERE correct IS NOT NULL AND sig_type='SHORT'
                  {since_filter}
                GROUP BY dow ORDER BY dow
            """)
            return {r[0]: r for r in rows}

        all_time = _fetch("")
        since_ts = int(time.time()) - rolling_days * 86400 if rolling_days > 0 else 0
        recent = _fetch(f"AND ts >= {since_ts}") if rolling_days > 0 else {}

        days = {"0":"Sun","1":"Mon","2":"Tue","3":"Wed","4":"Thu","5":"Fri","6":"Sat"}
        results = {}
        for dow_str in sorted(set(list(all_time.keys()) + list(recent.keys()))):
            day = days.get(str(dow_str), "?")
            at_row = all_time.get(dow_str, (dow_str, 0, None, None))
            rc_row = recent.get(dow_str, (dow_str, 0, None, None))
            n_at, wr_pct_at, avg_at = int(at_row[1]), at_row[2], at_row[3]
            n_rc, wr_pct_rc = int(rc_row[1]), rc_row[2]
            wr_at = (wr_pct_at or 0) / 100
            wr_rc = (wr_pct_rc or 0) / 100
            avg_pct = float(avg_at or 0)
            e_r = avg_pct / _SL_PCT  # v11.0: empirical ratio
            status = "PAPER" if dow_str in ("0", "6") else ("WATCH" if wr_at < 0.55 else "LIVE")
            delta_pp = round((wr_rc - wr_at) * 100, 1) if n_rc >= 10 else None
            inversion = abs(delta_pp) >= 20 if delta_pp is not None else False
            results[day] = {
                "n": n_at, "wr": round(wr_at, 4), "avg_pct": round(avg_pct, 2),
                "e_r": round(e_r, 3), "status": status,
                "rolling_n": n_rc, "rolling_wr": round(wr_rc, 4) if n_rc > 0 else None,
                "rolling_delta_pp": delta_pp, "inversion_alert": inversion,
            }
        return results
    finally:
        conn.close()


def session_performance_audit(rolling_days: int = _RESEARCH_ROLLING_DAYS) -> dict:
    """Session × grade (weekday only) SHORT performance — rolling window.

    v11.0 K3: E(R) = avg_pct / SL_PCT (empirical, not theoretical 4:1 ratio).
    v11.0 rolling_days: default 7d — avoids W22 all-time data domination.
    """
    conn = _connect()
    try:
        since_ts = int(time.time()) - rolling_days * 86400 if rolling_days > 0 else 0
        since_filter = f"AND ts >= {since_ts}" if rolling_days > 0 else ""
        rows = _query(conn, f"""
            SELECT grade, session, COUNT(*),
                ROUND(AVG(CASE WHEN correct=1 THEN 1.0 ELSE 0.0 END)*100,1),
                ROUND(AVG(outcome_pct),2)
            FROM signal_log
            WHERE correct IS NOT NULL AND sig_type='SHORT'
              AND strftime('%w', datetime(ts,'unixepoch')) NOT IN ('0','6')
              AND session IS NOT NULL
              {since_filter}
            GROUP BY grade, session
            HAVING COUNT(*) >= ?
            ORDER BY grade, 4 DESC
        """, (MIN_N_SESSION,))
        results = {}
        for grade, session, n, wr_pct, avg_pct in rows:
            wr = wr_pct / 100
            avg_pct = float(avg_pct or 0)
            e_r = avg_pct / _SL_PCT  # v11.0: empirical ratio
            key = f"{grade}-{session}"
            results[key] = {"n": n, "wr": round(wr, 4), "avg_pct": round(avg_pct, 2),
                             "e_r": round(e_r, 3),
                             "status": "LIVE" if wr >= 0.69 else "WATCH"}
        return results
    finally:
        conn.close()


def signal_quality_monitor(lookback_hours: int = 168) -> dict:
    """Check recent WR vs historical WR. Alert on degradation.
    lookback_hours=168 (7 days) to ensure weekday signals after a weekend are included.
    Using 48h misses all weekday signals after Sat/Sun — bug fixed 2026-06-08.
    Returns {grade: {recent_wr, historical_wr, delta, alert}}."""
    conn = _connect()
    try:
        # Ensure lookback is at least 168h (7 days) to survive weekends
        effective_lookback = max(lookback_hours, 168)
        ts_cutoff = int(time.time()) - effective_lookback * 3600
        results = {}
        for grade in ("S", "B", "C", "A"):
            # Historical WR (weekday, all time)
            hist = _query(conn, """
                SELECT AVG(CASE WHEN correct=1 THEN 1.0 ELSE 0.0 END), COUNT(*)
                FROM signal_log
                WHERE correct IS NOT NULL AND sig_type='SHORT' AND grade=?
                  AND strftime('%w', datetime(ts,'unixepoch')) NOT IN ('0','6')
            """, (grade,))
            hist_wr = hist[0][0] or 0.5
            hist_n  = hist[0][1] or 0

            # Recent WR — WEEKDAY ONLY (exclude Sat/Sun to avoid weekend contamination)
            recent = _query(conn, """
                SELECT AVG(CASE WHEN correct=1 THEN 1.0 ELSE 0.0 END), COUNT(*)
                FROM signal_log
                WHERE correct IS NOT NULL AND sig_type='SHORT' AND grade=? AND ts >= ?
                  AND strftime('%w', datetime(ts,'unixepoch')) NOT IN ('0','6')
            """, (grade, ts_cutoff))
            recent_wr = recent[0][0] or 0
            recent_n  = recent[0][1] or 0

            if recent_n < 5:
                continue

            delta = recent_wr - hist_wr
            # Alert: drop > 15pp from historical (regime change signal)
            alert = delta < -0.15
            results[grade] = {
                "hist_wr": round(hist_wr, 4), "hist_n": hist_n,
                "recent_wr": round(recent_wr, 4), "recent_n": recent_n,
                "delta_pp": round(delta * 100, 1), "alert": alert,
            }
        return results
    finally:
        conn.close()


def regime_recovery_eta(db_path: str | None = None,
                        wr_floor: float = 0.50,
                        rolling_days: int = _RESEARCH_ROLLING_DAYS,
                        _now_ts: int | None = None) -> dict:
    """Project when the rolling regime gate WR will recover to ≥ wr_floor.

    Analyses the current rolling window daily breakdown and simulates the
    effect of each historical bad-WR day rolling off the window.  Two
    scenarios are returned:

    1. Pure rolloff: WR after the oldest (worst) days leave, with *zero*
       new resolved signals — gives the floor we can reach passively.
    2. Recovery trigger: earliest date when the combined (legacy + new)
       WR will cross wr_floor, assuming new signals arrive at 50% WR.
       Also reports the minimum WR needed from new signals to trigger
       recovery on the inflection date (when the biggest WR jump occurs).

    Scientific rationale:
    The 7d sliding window means signals from past bad-performance days
    (e.g. Wed Jun 10 WR=7.1%, n=154) gradually drop off.  Their rolloff
    date is exactly 7 days after they were logged.  This function makes
    that timeline explicit, so the operator knows exactly when to expect
    the gate to self-recover versus how much improvement in new signals
    is required to accelerate recovery.

    Returns:
        current_wr          – current 7d rolling WR (weekday)
        current_n           – current 7d n
        wr_floor            – threshold used (default 0.50)
        daily_breakdown     – list of {date, n, wins, wr, rolloff_date,
                                       legacy_wr_after_rolloff}
        inflection_day      – day whose removal causes the largest WR jump
        inflection_delta_pp – WR increase (pp) from removing that day
        inflection_rolloff  – date the inflection day rolls off
        passive_recovery    – date when legacy WR ≥ floor without new
                               signals (None if not achievable in window)
        required_new_wr     – minimum WR needed from Jun 15+ signals to
                               trigger recovery on inflection_rolloff date
                               (None if passive recovery achieves it)
    """
    import sqlite3 as _sql
    _path = db_path or SIGNAL_DB
    try:
        conn = _sql.connect(str(_path))
        now_ts = _now_ts if _now_ts is not None else int(time.time())

        # Daily breakdown: past rolling_days weekdays
        daily: list[dict] = []
        for offset in range(rolling_days, 0, -1):
            day_start = now_ts - offset * 86400
            day_end   = day_start + 86400
            row = conn.execute(
                """SELECT COUNT(*), COALESCE(SUM(correct), 0)
                   FROM signal_log
                   WHERE direction='SHORT' AND correct IS NOT NULL
                     AND ts >= ? AND ts < ?
                     AND strftime('%w', ts, 'unixepoch') NOT IN ('0','6')""",
                (day_start, day_end)
            ).fetchone()
            n, w = int(row[0]), int(row[1])
            # Day label (UTC)
            import datetime as _dt
            d_utc  = _dt.datetime.utcfromtimestamp(day_start)
            ro_utc = _dt.datetime.utcfromtimestamp(day_start + rolling_days * 86400)
            daily.append({
                "date":         d_utc.strftime("%a %b %d"),
                "n":            n,
                "wins":         w,
                "wr":           round(w / n, 4) if n > 0 else None,
                "rolloff_date": ro_utc.strftime("%a %b %d"),
            })
        conn.close()
    except Exception:
        return {"error": "db_unavailable", "daily_breakdown": [], "current_wr": None}

    total_n = sum(d["n"] for d in daily)
    total_w = sum(d["wins"] for d in daily)
    if total_n == 0:
        return {"error": "no_data", "daily_breakdown": daily, "current_wr": None}

    current_wr = total_w / total_n

    # Simulate removing days oldest-first and track legacy WR trajectory
    inflection_day      = None
    inflection_delta_pp = 0.0
    inflection_rolloff  = None
    passive_recovery    = None
    rem_n, rem_w        = total_n, total_w

    for d in daily:
        if d["n"] == 0:
            d["legacy_wr_after_rolloff"] = None
            continue
        rem_n -= d["n"]
        rem_w -= d["wins"]
        legacy_wr = rem_w / rem_n if rem_n > 0 else None
        d["legacy_wr_after_rolloff"] = round(legacy_wr, 4) if legacy_wr is not None else None

        if legacy_wr is not None:
            delta = legacy_wr - current_wr
            if delta > inflection_delta_pp:
                inflection_delta_pp = delta
                inflection_day      = d["date"]
                inflection_rolloff  = d["rolloff_date"]
            if passive_recovery is None and legacy_wr >= wr_floor:
                passive_recovery = d["rolloff_date"]

    # Required WR from new signals so that at inflection_rolloff the gate opens
    required_new_wr = None
    if passive_recovery is None and inflection_rolloff is not None:
        # Find state just after inflection day rolls off
        inf_idx = next((i for i, d in enumerate(daily) if d["date"] == inflection_day), None)
        if inf_idx is not None:
            leg_n = total_n - sum(d["n"] for d in daily[:inf_idx + 1])
            leg_w = total_w - sum(d["wins"] for d in daily[:inf_idx + 1])
            # Estimate new signals: average weekday volume × days that will have resolved
            # Between now and inflection_rolloff ≈ (inf_idx+1) new weekdays
            avg_daily = total_n / max(sum(1 for d in daily if d["n"] > 0), 1)
            new_days  = inf_idx + 1          # days that will roll ON
            n_new     = int(avg_daily * new_days)
            if n_new > 0:
                # (leg_w + w_new) / (leg_n + n_new) >= wr_floor
                # w_new_min = wr_floor * (leg_n + n_new) - leg_w
                w_min = wr_floor * (leg_n + n_new) - leg_w
                rwr   = w_min / n_new
                required_new_wr = round(max(0.0, min(1.0, rwr)), 4)

    return {
        "current_wr":           round(current_wr, 4),
        "current_n":            total_n,
        "wr_floor":             wr_floor,
        "daily_breakdown":      daily,
        "inflection_day":       inflection_day,
        "inflection_delta_pp":  round(inflection_delta_pp * 100, 1),
        "inflection_rolloff":   inflection_rolloff,
        "passive_recovery":     passive_recovery,
        "required_new_wr":      required_new_wr,
    }


def new_signal_stats() -> dict:
    """Stats on the 3 new signal types (LONG_TECHNICAL, SPOT_BREAKOUT, LONG_FUNDING)."""
    conn = _connect()
    try:
        rows = _query(conn, """
            SELECT sig_type, COUNT(*),
                COUNT(CASE WHEN correct IS NOT NULL THEN 1 END) as resolved,
                ROUND(AVG(CASE WHEN correct=1 THEN 1.0 ELSE 0.0 END)*100,1),
                ROUND(AVG(CASE WHEN correct IS NOT NULL THEN outcome_pct END),2)
            FROM signal_log GROUP BY sig_type
        """)
        return {r[0]: {"total": r[1], "resolved": r[2], "wr_pct": r[3], "avg_pct": r[4]}
                for r in rows}
    finally:
        conn.close()


def v81_signal_contribution() -> dict:
    """Analyze contribution of new v8.1 signals (OI_DELTA, PREMIUM, etc.)
    by checking pattern column in signal_log."""
    conn = _connect()
    try:
        # Patterns with counts and WR
        rows = _query(conn, """
            SELECT patterns,
                COUNT(*),
                ROUND(AVG(CASE WHEN correct=1 THEN 1.0 ELSE 0.0 END)*100,1),
                ROUND(AVG(outcome_pct),2)
            FROM signal_log
            WHERE correct IS NOT NULL AND sig_type='SHORT'
              AND patterns != '' AND patterns IS NOT NULL
            GROUP BY patterns HAVING COUNT(*) >= 10
            ORDER BY 3 DESC LIMIT 20
        """)
        return {r[0]: {"n": r[1], "wr_pct": r[2], "avg_pct": r[3]} for r in rows}
    finally:
        conn.close()


# ── Report generation ─────────────────────────────────────────────────────────

def generate_research_report(deep: bool = False) -> str:
    """Generate comprehensive research report for Telegram."""
    lines = ["🔬 *AUTO-RESEARCH REPORT* — Pre-Gain System"]
    lines.append(f"   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    # 1. Edge Stats
    edge = edge_stats_by_grade(weekday_only=True)
    lines.append("📊 *Edge Stats (weekday-only)*")
    for g, st in sorted(edge.items()):
        trend = "↗" if st["wr_last30"] > st["wr"] else "↘"
        lines.append(f"   {g}: WR={st['wr']:.1%} n={st['n']} E={st['expectancy_r']:.2f}R "
                     f"last30={st['wr_last30']:.1%} {trend}")

    # 2. Signal Quality Monitor
    quality = signal_quality_monitor(lookback_hours=48)
    alerts = [g for g, st in quality.items() if st["alert"]]
    if alerts:
        lines.append(f"\n⚠️ *QUALITY ALERT* — Degradation detected: {', '.join(alerts)}")
        for g in alerts:
            st = quality[g]
            lines.append(f"   {g}: recent={st['recent_wr']:.1%}(n={st['recent_n']}) "
                         f"vs hist={st['hist_wr']:.1%} Δ={st['delta_pp']:+.1f}pp")
    else:
        lines.append("\n✅ Signal quality: within normal range (no degradation)")

    if deep:
        # 3. Top coins to boost/block
        coins = coin_performance_audit()
        boost = [(c, st) for c, st in coins.items() if st["action"] == "BOOST_CANDIDATE"]
        block = [(c, st) for c, st in coins.items() if st["action"] == "BLOCK_CANDIDATE"]
        if boost:
            lines.append(f"\n🚀 *BOOST CANDIDATES* ({len(boost)} coins)")
            for coin, st in sorted(boost, key=lambda x: x[1]["e_r"], reverse=True)[:5]:
                lines.append(f"   {coin}: E={st['e_r']:.2f}R WR={st['wr']:.1%} n={st['n']}")
        if block:
            lines.append(f"\n🚫 *BLOCK CANDIDATES* ({len(block)} coins)")
            for coin, st in sorted(block, key=lambda x: x[1]["wr"])[:5]:
                lines.append(f"   {coin}: WR={st['wr']:.1%} avg={st['avg_pct']:+.1f}% n={st['n']}")

        # 4. DOW analysis — include rolling 7d vs all-time comparison
        dow = dow_performance_audit()
        lines.append("\n📅 *DOW Performance (weekday-only, 7d rolling vs all-time)*")
        inversions = [day for day, st in dow.items() if st.get("inversion_alert")]
        if inversions:
            lines.append(f"   ⚠️ INVERSION ALERT: {', '.join(inversions)} — rolling WR ≠ all-time WR by ≥20pp!")
        for day, st in sorted(dow.items(), key=lambda x: x[1]["wr"], reverse=True):
            icon = "✅" if st["status"] == "LIVE" else ("⚠️" if st["status"] == "WATCH" else "📋")
            rolling_str = (f" | 7d: WR={st['rolling_wr']:.1%}(n={st['rolling_n']}) Δ={st['rolling_delta_pp']:+.1f}pp"
                           if st.get("rolling_wr") is not None and st.get("rolling_delta_pp") is not None else "")
            lines.append(f"   {icon} {day}: WR={st['wr']:.1%} E={st['e_r']:.2f}R n={st['n']}{rolling_str}")

        # 5. New signal types
        ns = new_signal_stats()
        lines.append("\n🔭 *Signal Type Stats*")
        for sig_type, st in sorted(ns.items()):
            wr_str = f"WR={st['wr_pct']:.0f}%" if st['wr_pct'] is not None else "pending"
            lines.append(f"   {sig_type}: total={st['total']} resolved={st['resolved']} {wr_str}")

        # 6. Regime recovery ETA (only when gate is active)
        rg_active, rg_wr, _rg_n = _regime_gate_status()
        if rg_active and rg_wr is not None:
            eta = regime_recovery_eta()
            if "error" not in eta:
                lines.append("\n⏳ *Regime Recovery ETA*")
                lines.append(f"   Current 7d WR: {eta['current_wr']:.1%} (n={eta['current_n']}) | Target: ≥{eta['wr_floor']:.0%}")
                lines.append(f"   Inflection day: {eta['inflection_day']} → rolls off {eta['inflection_rolloff']} (+{eta['inflection_delta_pp']:.1f}pp)")
                if eta["passive_recovery"]:
                    lines.append(f"   ✅ Passive recovery: gate auto-opens ~{eta['passive_recovery']} (no new signals needed)")
                else:
                    rwr = eta.get("required_new_wr")
                    rwr_str = f"{rwr:.0%}" if rwr is not None else "n/a"
                    lines.append(f"   🎯 Required new-signal WR ≥ {rwr_str} to trigger recovery on {eta['inflection_rolloff']}")
                lines.append(f"   Daily breakdown (7d window, oldest → rolls off first):")
                for d in eta["daily_breakdown"]:
                    if d["n"] == 0:
                        continue
                    wr_s = f"WR={d['wr']:.1%}" if d["wr"] is not None else "WR=N/A"
                    leg  = f" → legacy WR={d['legacy_wr_after_rolloff']:.1%}" if d.get("legacy_wr_after_rolloff") is not None else ""
                    lines.append(f"   {d['date']}: n={d['n']} {wr_s} (rolls off {d['rolloff_date']}){leg}")

    lines.append("")
    lines.append(f"_Autonomous research | Next: {_next_run_str()}_")
    return "\n".join(lines)


def _next_run_str() -> str:
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    next_02utc = now.replace(hour=2, minute=30, second=0, microsecond=0)
    if next_02utc <= now:
        next_02utc += timedelta(days=1)
    hrs = (next_02utc - now).total_seconds() / 3600
    return f"deep research in {hrs:.1f}h"


# ── Autonomous improvement actions ────────────────────────────────────────────

def compute_safe_improvements() -> dict:
    """Compute improvements safe to apply automatically.

    Returns:
      coin_blocks: set of coins to add to COIN_BLOCK
      coin_boosts: dict of coin → boost_pct to update/add
      coin_unblocks: set of coins to remove from COIN_BLOCK

    Safety: only coins with n≥30 weekday signals qualify.
    REGIME GUARD (v9.0): if rolling-3d WR < 50% (regime gate active),
    skip ALL coin recalibration. Rationale: all-time coin stats are
    79.4% dominated by W22 crash week. Recalibrating during RANGING
    regime would overfit to crash patterns, not current conditions.
    Report regime status instead of coin improvements.
    """
    rg_active, rg_wr, rg_n = _regime_gate_status()
    if rg_active and rg_wr is not None:
        eta = regime_recovery_eta()
        _eta_summary = ""
        if "error" not in eta:
            inf_day = eta.get("inflection_day") or "?"
            inf_ro  = eta.get("inflection_rolloff") or "?"
            if eta.get("passive_recovery"):
                _eta_summary = f" Passive recovery ~{eta['passive_recovery']}."
            else:
                rwr = eta.get("required_new_wr")
                rwr_s = f"{rwr:.0%}" if rwr is not None else "?"
                _eta_summary = (
                    f" Inflection: {inf_day} rolls off {inf_ro} "
                    f"(+{eta['inflection_delta_pp']:.1f}pp). "
                    f"Need new-signal WR≥{rwr_s} for gate to open."
                )
        return {
            "coin_blocks": [],
            "coin_boosts": [],
            "coin_unblocks": [],
            "deboost": [],
            "_regime_gate_active": True,
            "_regime_wr": rg_wr,
            "_regime_n": rg_n,
            "_regime_eta": eta if "error" not in eta else None,
            "_regime_msg": (
                # v11.6: label reflects K16 fallback (7d) vs primary (3d)
                f"🔴 REGIME GATE ACTIVE: rolling {'7d-fallback' if rg_n >= 120 else '3d'} "
                f"WR={rg_wr:.1%} (n={rg_n}) < 50%. "
                "Coin recalibration SKIPPED — all-time data is 79.4% W22 crash-week. "
                f"Resume when 3d/7d WR ≥ 50%. No autonomous changes this cycle."
                + _eta_summary
            ),
        }
    coins = coin_performance_audit()
    improvements = {
        "coin_blocks": [],    # (coin, wr, avg_pct, n)
        "coin_boosts": [],    # (coin, e_r, wr, n, suggested_pct)
        "coin_unblocks": [],  # (coin, wr, e_r, n)
        "deboost": [],        # (coin, e_r, n)
    }

    for coin, st in coins.items():
        if st["action"] == "BLOCK_CANDIDATE":
            improvements["coin_blocks"].append(
                (coin, st["wr"], st["avg_pct"], st["n"]))
        elif st["action"] == "BOOST_CANDIDATE":
            # Scale boost: E(R)=1.5 → +15%, E(R)=2.0 → +20%, E(R)=3.0 → +30%
            boost_pct = min(40, int(st["e_r"] * 10))
            improvements["coin_boosts"].append(
                (coin, st["e_r"], st["wr"], st["n"], boost_pct))
        elif st["action"] == "UNBLOCK_CANDIDATE":
            improvements["coin_unblocks"].append(
                (coin, st["wr"], st["e_r"], st["n"]))
        elif st["action"] == "DEBOOST_CANDIDATE":
            improvements["deboost"].append((coin, st["e_r"], st["n"]))

    # Sort by strength
    improvements["coin_blocks"].sort(key=lambda x: x[1])
    improvements["coin_boosts"].sort(key=lambda x: x[1], reverse=True)
    return improvements


def format_improvements_report(improvements: dict) -> str:
    """Format improvement recommendations for Telegram."""
    lines = ["🤖 *AUTONOMOUS IMPROVEMENT RECOMMENDATIONS*"]

    # Regime gate: if active, report prominently and skip recalibration output
    if improvements.get("_regime_gate_active"):
        lines.append(f"\n{improvements['_regime_msg']}")
        lines.append("\n_Autonomous recalibration paused. System in PAPER-only mode._")
        return "\n".join(lines)

    if improvements["coin_blocks"]:
        lines.append(f"\n🚫 *Block Candidates* (WR<35%, avg<-3%):")
        for coin, wr, avg, n in improvements["coin_blocks"][:5]:
            lines.append(f"   {coin}: WR={wr:.1%} avg={avg:+.1f}% n={n}")
        lines.append("   → /pregain-block <coin> to apply")

    if improvements["coin_boosts"]:
        lines.append(f"\n🚀 *Boost Candidates* (E≥1.5R):")
        for coin, e_r, wr, n, pct in improvements["coin_boosts"][:5]:
            lines.append(f"   {coin}: E={e_r:.2f}R WR={wr:.1%} n={n} → +{pct}% size")
        lines.append("   → /pregain-boost <coin> to apply")

    if improvements["coin_unblocks"]:
        lines.append(f"\n✅ *Unblock Candidates* (recovering):")
        for coin, wr, e_r, n in improvements["coin_unblocks"][:3]:
            lines.append(f"   {coin}: WR={wr:.1%} E={e_r:.2f}R n={n}")

    if improvements["deboost"]:
        lines.append(f"\n⚠️ *Deboost Candidates* (E<0.2R):")
        for coin, e_r, n in improvements["deboost"][:3]:
            lines.append(f"   {coin}: E={e_r:.2f}R n={n}")

    if not any(improvements.values()):
        lines.append("\n✅ No autonomous improvements needed. System optimally configured.")

    return "\n".join(lines)


# ── Main entry points (called by daemon jobs) ─────────────────────────────────

def run_daily_research() -> str:
    """Full daily research cycle. Returns Telegram message."""
    _log("daily_research_start", {"ts": int(time.time())})
    report = generate_research_report(deep=True)
    improvements = compute_safe_improvements()
    impr_report = format_improvements_report(improvements)

    _log("daily_research_complete", {
        # Only list-type values support len(); skip bool/int/float/str metadata keys
        # (e.g. _regime_gate_active=True, _regime_wr=0.32, _regime_n=346 added by regime guard)
        "improvements": {k: len(v) for k, v in improvements.items() if isinstance(v, list)},
        "edge": edge_stats_by_grade(),
    })
    return report + "\n\n" + impr_report


def run_signal_quality_check() -> str | None:
    """4-hourly quality check. Returns alert message or None if clean."""
    quality = signal_quality_monitor(lookback_hours=48)
    alerts = {g: st for g, st in quality.items() if st["alert"]}
    if not alerts:
        return None  # clean, no alert needed
    lines = ["⚠️ *SIGNAL QUALITY ALERT* — Pre-Gain"]
    for g, st in alerts.items():
        lines.append(f"   Grade {g}: {st['recent_wr']:.1%} recent vs "
                     f"{st['hist_wr']:.1%} hist (Δ{st['delta_pp']:+.1f}pp)")
    lines.append("_Monitor closely — may indicate regime change or model drift_")
    _log("quality_alert", {"grades": list(alerts.keys()), "details": alerts})
    return "\n".join(lines)


def run_learner_refresh() -> str:
    """Refresh PregainLearner with latest validated signals."""
    try:
        try:
            from anantara import pregain_learner as _pl
            from anantara import pregain_scan as _ps
        except ImportError:
            import pregain_learner as _pl  # type: ignore
            import pregain_scan as _ps     # type: ignore
        learner = _pl.PregainLearner()
        learner.refresh(Path(SIGNAL_DB))
        status = f"PregainLearner refreshed: global_n={learner._global.n} patterns={len(learner._patterns)} coins={len(learner._coins)}"
        _log("learner_refresh", {"global_n": learner._global.n,
                                  "n_patterns": len(learner._patterns),
                                  "n_coins": len(learner._coins)})
        return status
    except Exception as e:
        return f"Learner refresh error: {e}"


def run_v81_signal_analysis() -> str:
    """Analyze how new v8.1 signals are performing."""
    contrib = v81_signal_contribution()
    if not contrib:
        return "v8.1 signals: insufficient data yet (need n≥10 per pattern combo)"
    lines = ["📡 *v8.1 Signal Pattern Analysis*"]
    for pattern, st in list(sorted(contrib.items(), key=lambda x: x[1]["wr_pct"] or 0, reverse=True))[:8]:
        wr = st['wr_pct']
        lines.append(f"   {pattern[:40]}: WR={wr:.0f}% n={st['n']}")
    return "\n".join(lines)


if __name__ == "__main__":
    print("=== Pre-Gain Daily Research ===")
    print(run_daily_research())
    print()
    print("=== Signal Quality ===")
    result = run_signal_quality_check()
    print(result or "✅ All clean")
