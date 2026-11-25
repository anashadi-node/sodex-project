#!/usr/bin/env python3
"""
ANANTARA SAKTI — Signal Tracker & Hit-Rate Validator

The honesty engine of the Pre-Gain/Loser scanner. Every scan logs its actionable
signals to SQLite. Later, `backfill_outcomes` looks up what actually happened
`horizon` hours after each signal and records whether the called direction was
profitable. `hit_rate_report` then tells the TRUTH:

    "Of all score≥60 signals, what % actually moved the right way after fees?"

This converts the scanner from an unverifiable oracle into a self-measuring
radar. If real hit-rate ≈ 50%, that is the answer — no edge — and the user is
saved capital. If it is meaningfully >55% after costs, it is worth pursuing.
No prediction is trusted until this validator earns it.

Schema v2 additions (backward-compatible):
  session     — trading session at signal time (Asia|EU|US|US_Asia)
  fund_accel  — funding acceleration (%/yr per hour) at signal time
  vol_oi      — vol/OI turnover ratio at signal time

Schema v3 additions:
  sig_type    — signal source: SHORT | LONG_FUNDING | LONG_TECHNICAL | SPOT_BREAKOUT

Pure stdlib (sqlite3). The price lookup used by backfill is injected, so the
logic is unit-testable offline.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

DEFAULT_HORIZON_SEC = 24 * 3600          # judge a signal 24h later
# Round-trip cost assumption (taker both legs ~ conservative). A directional call
# only counts as a WIN if it cleared this hurdle, so hit-rate is fee-honest.
DEFAULT_FEE_HURDLE_PCT = 0.10            # 0.10% move needed to beat fees+slippage


_SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,      -- unix seconds when signal emitted
    coin        TEXT    NOT NULL,
    direction   TEXT    NOT NULL,      -- 'LONG' | 'SHORT'
    score       REAL    NOT NULL,      -- attention score 0-100 (NOT a probability)
    grade       TEXT    NOT NULL,      -- S | A | B | C
    entry_price REAL    NOT NULL,
    regime      TEXT,
    vol24       REAL,
    liq_tier    TEXT,                  -- LIQUID | THIN | DUST
    session     TEXT,                  -- Asia | EU | US | US_Asia
    fund_accel  REAL    DEFAULT 0,    -- funding acceleration (%/yr/h) at signal time
    vol_oi      REAL    DEFAULT 0,    -- vol/OI turnover ratio at signal time
    patterns    TEXT    DEFAULT '',   -- fired pattern names CSV e.g. "SHORT_SQUEEZE,COIL"
    outcome_pct REAL,                  -- signed return in signal direction, % (NULL until resolved)
    correct     INTEGER,               -- 1 if outcome beat fee hurdle, else 0
    outcome_ts  INTEGER,               -- when outcome was computed
    sig_type    TEXT    DEFAULT ''     -- SHORT | LONG_FUNDING | LONG_TECHNICAL | SPOT_BREAKOUT
);
CREATE INDEX IF NOT EXISTS idx_signal_unresolved ON signal_log(outcome_pct) WHERE outcome_pct IS NULL;
CREATE INDEX IF NOT EXISTS idx_signal_session ON signal_log(session) WHERE session IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_signal_patterns ON signal_log(patterns) WHERE patterns != '';
"""

# Idempotent migrations for existing databases that predate schema v2/v3/v4.
# Each ALTER TABLE is attempted; OperationalError = column already exists → skip.
# IMPORTANT: Add new columns here (not in _SCHEMA) so existing DBs get migrated.
# Indexes on new columns go here too (after column exists).
_MIGRATIONS = [
    "ALTER TABLE signal_log ADD COLUMN session TEXT",
    "ALTER TABLE signal_log ADD COLUMN fund_accel REAL DEFAULT 0",
    "ALTER TABLE signal_log ADD COLUMN vol_oi REAL DEFAULT 0",
    "ALTER TABLE signal_log ADD COLUMN patterns TEXT DEFAULT ''",
    "ALTER TABLE signal_log ADD COLUMN sig_type TEXT DEFAULT ''",  # v4: signal source type
    "CREATE INDEX IF NOT EXISTS idx_signal_type ON signal_log(sig_type) WHERE sig_type != ''",
    # v5 (2026-08-23, Opposite audit P2): capture execution-cost context AT SIGNAL
    # TIME. Data gap #1 simulator ("orderbook_depth_at_signal") — HL impactPxs
    # ($5k depth effective spread) sudah dihitung scanner tapi tidak pernah
    # disimpan per-sinyal. Tanpa ini, cost model memakai proxy statis.
    "ALTER TABLE signal_log ADD COLUMN impact_spread_pct REAL DEFAULT 0",
    "CREATE INDEX IF NOT EXISTS idx_signal_impact ON signal_log(impact_spread_pct) WHERE impact_spread_pct > 0",
]


@dataclass
class Signal:
    coin: str
    direction: str         # LONG | SHORT
    score: float
    grade: str
    entry_price: float
    regime: str = ""
    vol24: float = 0.0
    liq_tier: str = ""
    fund_accel: float = 0.0   # funding acceleration (%/yr/h) injected by run_scan()
    vol_oi: float = 0.0       # vol/OI turnover ratio at signal time
    patterns: str = ""        # fired pattern names CSV e.g. "SHORT_SQUEEZE,COIL"
    sig_type: str = ""        # signal source: SHORT|LONG_FUNDING|LONG_TECHNICAL|SPOT_BREAKOUT
    impact_spread_pct: float = 0.0  # $5k-depth effective spread % at signal time (v5)


def session_name(utc_hour: int | None = None) -> str:
    """Detect trading session from UTC hour.

    Research basis (360d HL data, Jun 2025–May 2026):
      Asia    (00:00–08:00 UTC): altcoin signal win-rate historically ~70–80%
      EU      (08:00–12:00 UTC): similar to Asia, momentum tends to continue
      US      (12:00–20:00 UTC): mixed, influenced by US macro/news flow
      US_Asia (20:00–24:00 UTC): transition period, historically lower ~54%

    Session is stored in signal_log so the validator can empirically confirm
    (or deny) these session effects on OUR actual signals — not just backtested ones.
    """
    h = utc_hour if utc_hour is not None else datetime.now(timezone.utc).hour
    if 0 <= h < 8:
        return "Asia"
    if 8 <= h < 12:
        return "EU"
    if 12 <= h < 20:
        return "US"
    return "US_Asia"


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA)
    # Idempotent schema migration: silently ignore if column already exists.
    for sql in _MIGRATIONS:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            pass   # OperationalError: duplicate column — already migrated
    return conn


def log_signals(db_path: str | Path, signals: list[Signal],
                now: Optional[int] = None, cooldown_sec: int = 0) -> int:
    """Persist actionable signals. Returns count actually inserted.

    `cooldown_sec` > 0 de-duplicates: a (coin, direction) signal is skipped if an
    identical one was already logged within the last `cooldown_sec` seconds. This
    stops rapid manual re-runs from double-counting the same call and biasing the
    hit-rate (legitimate periodic observations further apart still log normally).

    Session is auto-detected from wall-clock UTC so each signal carries the
    session context it was emitted in (used for session-stratified win-rate analysis).
    """
    now = int(now if now is not None else time.time())
    sess = session_name()   # detect session at log time, not signal creation time
    conn = connect(db_path)
    try:
        inserted = 0
        for s in signals:
            if cooldown_sec > 0:
                # Include sig_type in cooldown check: LONG_FUNDING and SPOT_BREAKOUT
                # are different strategies on the same coin+direction, each needs tracking.
                dup = conn.execute(
                    "SELECT 1 FROM signal_log "
                    "WHERE coin=? AND direction=? AND sig_type=? AND ts >= ? LIMIT 1",
                    (s.coin, s.direction, s.sig_type or "", now - cooldown_sec)).fetchone()
                if dup:
                    continue
            conn.execute(
                "INSERT INTO signal_log "
                "(ts,coin,direction,score,grade,entry_price,"
                " regime,vol24,liq_tier,session,fund_accel,vol_oi,patterns,sig_type,"
                " impact_spread_pct) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (now, s.coin, s.direction, float(s.score), s.grade,
                 float(s.entry_price), s.regime, float(s.vol24), s.liq_tier,
                 sess, float(s.fund_accel), float(s.vol_oi),
                 s.patterns or "", s.sig_type or "",
                 float(getattr(s, "impact_spread_pct", 0.0) or 0.0)))
            inserted += 1
        conn.commit()
        return inserted
    finally:
        conn.close()


def _directional_return(direction: str, entry: float, exit_: float) -> float:
    """Signed % return in the signal's direction (LONG up = +, SHORT down = +)."""
    if entry <= 0:
        return 0.0
    raw = (exit_ - entry) / entry * 100.0
    return raw if direction.upper() == "LONG" else -raw


def backfill_outcomes(db_path: str | Path,
                      price_fn: Callable[[str], Optional[float]],
                      horizon_sec: int = DEFAULT_HORIZON_SEC,
                      fee_hurdle_pct: float = DEFAULT_FEE_HURDLE_PCT,
                      now: Optional[int] = None,
                      hist_price_fn: Optional[Callable[[str, int], Optional[float]]] = None,
                      sig_type_filter: Optional[str] = None,
                      sig_type_exclude: Optional[str] = None,
                      ) -> int:
    """Resolve signals older than `horizon_sec` that have no outcome yet.

    `price_fn(coin)` → current price (fast fallback for fresh signals).
    `hist_price_fn(coin, signal_ts)` → price at signal_ts+horizon (accurate
    for old signals, e.g. if daemon was offline). Falls back to price_fn when
    hist_price_fn is None or returns None/0.
    `sig_type_filter`: if set, only resolve signals with this sig_type.
    `sig_type_exclude`: if set, skip signals with this sig_type (use separate call).
    Returns the number of signals resolved this call.
    """
    now = int(now if now is not None else time.time())
    cutoff = now - horizon_sec
    conn = connect(db_path)
    resolved = 0
    try:
        q = ("SELECT id,coin,direction,entry_price,ts FROM signal_log "
             "WHERE outcome_pct IS NULL AND ts <= ?")
        params: list = [cutoff]
        if sig_type_filter is not None:
            q += " AND sig_type = ?"
            params.append(sig_type_filter)
        if sig_type_exclude is not None:
            q += " AND (sig_type IS NULL OR sig_type != ?)"
            params.append(sig_type_exclude)
        rows = conn.execute(q, params).fetchall()
        for sid, coin, direction, entry, signal_ts in rows:
            price: Optional[float] = None
            if hist_price_fn is not None:
                price = hist_price_fn(coin, signal_ts)
            # Explicit None check: `if not price` would incorrectly fallback for price=0.0
            # (valid but indicating price crashed to zero, which is a real outcome).
            # We only fallback when hist_price_fn returned None (no data), not on 0.
            if price is None or price <= 0:
                price = price_fn(coin)
            if price is None or price <= 0:
                continue
            ret = _directional_return(direction, entry, price)
            correct = 1 if ret > fee_hurdle_pct else 0
            conn.execute(
                "UPDATE signal_log SET outcome_pct=?,correct=?,outcome_ts=? WHERE id=?",
                (round(ret, 4), correct, now, sid),
            )
            resolved += 1
        conn.commit()
        return resolved
    finally:
        conn.close()


def hit_rate_report(db_path: str | Path) -> dict:
    """Aggregate resolved signals into honest hit-rate statistics.

    Returns a dict with keys:
      total, resolved, pending — signal counts
      overall                  — aggregate {n, win_rate, avg_outcome_pct}
      by_grade                 — per grade S/A/B/C
      by_direction             — LONG vs SHORT
      by_regime                — per market regime
      by_session               — per trading session (Asia|EU|US|US_Asia)
                                 empty if session column not yet populated
    """
    conn = connect(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM signal_log").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM signal_log WHERE outcome_pct IS NULL").fetchone()[0]
        resolved = conn.execute(
            "SELECT COUNT(*) FROM signal_log WHERE outcome_pct IS NOT NULL").fetchone()[0]

        def _bucket(where: str = "", params: tuple = ()) -> dict:
            q = ("SELECT COUNT(*), SUM(correct), AVG(outcome_pct) "
                 "FROM signal_log WHERE outcome_pct IS NOT NULL")
            if where:
                q += " AND " + where
            row = conn.execute(q, params).fetchone()
            if row is None:
                return {"n": 0, "win_rate": None, "avg_outcome_pct": None}
            n, wins, avg = row
            n = n or 0
            wins = wins or 0
            return {
                "n": n,
                "win_rate": round(wins / n * 100, 1) if n else None,
                "avg_outcome_pct": round(avg, 3) if avg is not None else None,
            }

        by_grade = {g: _bucket("grade=?", (g,)) for g in ("S", "A", "B", "C")}
        by_dir   = {d: _bucket("direction=?", (d,)) for d in ("LONG", "SHORT")}

        by_regime: dict = {}
        for (rg,) in conn.execute(
                "SELECT DISTINCT regime FROM signal_log WHERE outcome_pct IS NOT NULL"):
            by_regime[rg or "?"] = _bucket("regime=?", (rg,))

        # Session breakdown — only populated after schema v2 migration
        by_session: dict = {}
        try:
            for (sess,) in conn.execute(
                    "SELECT DISTINCT session FROM signal_log "
                    "WHERE outcome_pct IS NOT NULL AND session IS NOT NULL"):
                by_session[sess] = _bucket("session=?", (sess,))
        except Exception:
            pass   # graceful: old schema without session column

        # Grade × Session cross-product — enables session-aware edge evaluation.
        # by_grade_session["S"]["Asia"] = {n, win_rate, avg_outcome_pct}
        # Used by: progress_report (session breakdown per grade),
        #          future: autotrader session-filtered Grade S edge check.
        by_grade_session: dict = {}
        try:
            for g in ("S", "A", "B", "C"):
                grade_sess: dict = {}
                for (sess,) in conn.execute(
                        "SELECT DISTINCT session FROM signal_log "
                        "WHERE outcome_pct IS NOT NULL AND session IS NOT NULL AND grade=?",
                        (g,)):
                    grade_sess[sess] = _bucket("grade=? AND session=?", (g, sess))
                if grade_sess:
                    by_grade_session[g] = grade_sess
        except Exception:
            pass   # graceful: old schema

        # Signal type breakdown — tracks edge per source (SHORT/LONG_TECHNICAL/SPOT)
        by_sig_type: dict = {}
        try:
            for (st,) in conn.execute(
                    "SELECT DISTINCT sig_type FROM signal_log "
                    "WHERE outcome_pct IS NOT NULL AND sig_type IS NOT NULL AND sig_type != ''"):
                by_sig_type[st] = _bucket("sig_type=?", (st,))
        except Exception:
            pass

        # BTC beta decomposition: how does SHORT WR correlate with market direction?
        # This reveals whether edge is scanner alpha or pure BTC-bear beta.
        # Proxy: regime column captures market state at signal time.
        # RANGING = sideways, TRENDING = directional. WR gap shows beta dependence.
        btc_beta: dict = {}
        try:
            for (rg,) in conn.execute(
                    "SELECT DISTINCT regime FROM signal_log "
                    "WHERE outcome_pct IS NOT NULL AND direction='SHORT' AND regime IS NOT NULL"):
                btc_beta[rg or "?"] = _bucket("direction='SHORT' AND regime=?", (rg,))
        except Exception:
            pass

        return {
            "total": total, "resolved": resolved, "pending": pending,
            "overall": _bucket(),
            "by_grade": by_grade, "by_direction": by_dir,
            "by_regime": by_regime, "by_session": by_session,
            "by_grade_session": by_grade_session,
            "by_sig_type": by_sig_type,
            "btc_beta": btc_beta,   # SHORT WR per regime — beta decomposition proxy
        }
    finally:
        conn.close()


def rolling_win_rate(db_path: str | Path, days: int = 7) -> dict:
    """Win-rate for resolved signals from the last `days` days.

    Used to detect if signal quality is trending up or down over time.
    Complements hit_rate_report() (which is all-time) — a declining rolling
    win-rate warns that market conditions may have changed.

    Returns {days, n, win_rate, avg_outcome_pct, by_session}.
    """
    cutoff_ts = int(time.time()) - days * 86400
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*), SUM(correct), AVG(outcome_pct) "
            "FROM signal_log WHERE outcome_pct IS NOT NULL AND ts >= ?",
            (cutoff_ts,)).fetchone()
        n_total, wins, avg = (row[0] or 0), (row[1] or 0), row[2]

        by_session: dict = {}
        try:
            for (sess,) in conn.execute(
                    "SELECT DISTINCT session FROM signal_log "
                    "WHERE outcome_pct IS NOT NULL AND ts >= ? AND session IS NOT NULL",
                    (cutoff_ts,)):
                sq = conn.execute(
                    "SELECT COUNT(*), SUM(correct), AVG(outcome_pct) "
                    "FROM signal_log WHERE outcome_pct IS NOT NULL AND ts >= ? AND session=?",
                    (cutoff_ts, sess)).fetchone()
                sn, sw, sa = (sq[0] or 0), (sq[1] or 0), sq[2]
                by_session[sess] = {
                    "n": sn,
                    "win_rate": round(sw / sn * 100, 1) if sn else None,
                    "avg_outcome_pct": round(sa, 3) if sa is not None else None,
                }
        except Exception:
            pass   # old schema without session column

        return {
            "days": days,
            "n": n_total,
            "win_rate": round(wins / n_total * 100, 1) if n_total else None,
            "avg_outcome_pct": round(avg, 3) if avg is not None else None,
            "by_session": by_session,
        }
    finally:
        conn.close()


def pattern_breakdown(db_path: str | Path) -> dict:
    """Per-pattern win-rate dari resolved signals (kolom patterns).

    Returns {pattern_name: {n, win_rate, avg_outcome_pct}} untuk semua pattern
    yang muncul di resolved signal log. Digunakan oleh PregainLearner dan
    Telegram /pregain-learn command.

    Menggunakan running mean (numerically stable untuk banyak sinyal).
    """
    conn = connect(db_path)
    try:
        # Graceful: patterns column mungkin belum ada di DB lama
        cols = {r[1] for r in conn.execute("PRAGMA table_info(signal_log)")}
        if "patterns" not in cols:
            return {}
        rows = conn.execute(
            "SELECT patterns, correct, outcome_pct FROM signal_log "
            "WHERE outcome_pct IS NOT NULL AND patterns IS NOT NULL AND patterns != ''"
        ).fetchall()
    finally:
        conn.close()

    acc: dict[str, dict] = {}
    for patterns_str, correct, outcome_pct in rows:
        for pname in str(patterns_str).split(","):
            pname = pname.strip()
            if not pname:
                continue
            if pname not in acc:
                acc[pname] = {"n": 0, "wins": 0, "sum_pct": 0.0}
            acc[pname]["n"]       += 1
            acc[pname]["wins"]    += int(correct or 0)
            acc[pname]["sum_pct"] += float(outcome_pct or 0.0)

    return {
        k: {
            "n":               v["n"],
            "win_rate":        round(v["wins"] / v["n"] * 100, 1) if v["n"] else None,
            "avg_outcome_pct": round(v["sum_pct"] / v["n"], 3)    if v["n"] else None,
        }
        for k, v in acc.items()
    }


def coin_breakdown(db_path: str | Path, min_n: int = 3) -> dict:
    """Per-coin+direction win-rate dari resolved signals.

    Returns {f"{direction}:{coin}": {n, win_rate, avg_outcome_pct}} untuk pasangan
    coin+direction yang memiliki ≥ min_n resolved signals.

    Digunakan PregainLearner untuk coin-level gate:
      - win_rate < 30% + n ≥ min_n → PENALTI (coin ini konsisten gagal)
      - win_rate > 70% + n ≥ min_n → BOOST (coin ini konsisten berhasil)
    """
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT coin, direction, correct, outcome_pct FROM signal_log "
            "WHERE outcome_pct IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()

    acc: dict[str, dict] = {}
    for coin, direction, correct, outcome_pct in rows:
        key = f"{direction}:{coin}"
        if key not in acc:
            acc[key] = {"n": 0, "wins": 0, "sum_pct": 0.0}
        acc[key]["n"]       += 1
        acc[key]["wins"]    += int(correct or 0)
        acc[key]["sum_pct"] += float(outcome_pct or 0.0)

    return {
        k: {
            "coin":            k.split(":")[1],
            "direction":       k.split(":")[0],
            "n":               v["n"],
            "win_rate":        round(v["wins"] / v["n"] * 100, 1) if v["n"] else None,
            "avg_outcome_pct": round(v["sum_pct"] / v["n"], 3)    if v["n"] else None,
        }
        for k, v in acc.items() if v["n"] >= min_n
    }


def format_report(rep: dict) -> str:
    """Human-readable hit-rate report (Telegram/terminal friendly)."""
    o = rep["overall"]
    L = ["🔬 ANANTARA — VALIDATOR HIT-RATE (kebenaran, bukan klaim)",
         f"   Total sinyal: {rep['total']}  |  resolved: {rep['resolved']}  |  pending: {rep['pending']}"]
    if not o["n"]:
        L.append("   Belum ada sinyal resolved (perlu ≥24 jam data). Sabar — biarkan terkumpul.")
        return "\n".join(L)
    wr = o["win_rate"]
    verdict = ("✅ ada indikasi edge (>55%)" if wr and wr > 55 else
               "⚠️ ~koin lempar (≈50%, belum terbukti)" if wr and wr >= 45 else
               "❌ di bawah acak (<45%)")
    L.append(f"   OVERALL win-rate: {wr}%  | avg outcome: {o['avg_outcome_pct']}%  → {verdict}")
    L.append("   Per grade:")
    for g in ("S", "A", "B", "C"):
        b = rep["by_grade"][g]
        if b["n"]:
            L.append(f"     {g}: n={b['n']:>3}  win={b['win_rate']}%  avg={b['avg_outcome_pct']}%")
    L.append("   Per arah:")
    for d in ("LONG", "SHORT"):
        b = rep["by_direction"][d]
        if b["n"]:
            L.append(f"     {d:<5}: n={b['n']:>3}  win={b['win_rate']}%  avg={b['avg_outcome_pct']}%")
    if rep.get("by_regime"):
        L.append("   Per regime:")
        for rg, b in rep["by_regime"].items():
            if b["n"]:
                L.append(f"     {rg:<8}: n={b['n']:>3}  win={b['win_rate']}%  avg={b['avg_outcome_pct']}%")
    if rep.get("by_session"):
        L.append("   Per sesi trading:")
        _sess_icons = {"Asia": "🌏", "EU": "🇪🇺", "US": "🇺🇸", "US_Asia": "🌙"}
        for sess in ("Asia", "EU", "US", "US_Asia"):
            b = rep["by_session"].get(sess)
            if b and b.get("n"):
                icon = _sess_icons.get(sess, "📡")
                L.append(f"     {icon}{sess:<8}: n={b['n']:>3}  win={b['win_rate']}%  avg={b['avg_outcome_pct']}%")
    L.append("   Catatan: win = gerak searah > fee-hurdle 0.10%. Butuh ≥30-50 sampel "
             "per grade sebelum hasil dipercaya (hindari kesimpulan dari sampel kecil).")
    return "\n".join(L)


if __name__ == "__main__":
    import os
    db = os.environ.get("ANANTARA_SIGNAL_DB",
                        str(Path.home() / ".local/share/anantara/signals.db"))
    print(format_report(hit_rate_report(db)))
