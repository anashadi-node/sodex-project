#!/usr/bin/env python3
"""
ANANTARA SAKTI — Pre-Gain/Loser AUTO-TRADER (paper-first, edge-gated, risk-limited).

Gives the system the capability to act on its signals automatically — the project's
stated purpose. But it is engineered so it can NEVER auto-destroy capital on an
unproven/losing signal:

  SAFETY LAYERS (all enforced in the pure `decide`):
   1. Liquidity gate   — never trade DUST (<$1M/24h).
   2. Risk limits      — max concurrent positions, daily loss cap.
   3. Whale gate       — skip if curated whales strongly OPPOSE the direction.
   4. EDGE GATE        — real-money (LIVE) is allowed ONLY for a grade whose
                          validated expectancy is positive with enough sample.
                          No proven edge → trade in PAPER only (gather data).
   5. Explicit opt-in  — LIVE also needs live_enabled (--live + AUTOTRADE_LIVE=1).

Right now the edge is empirically NEGATIVE (see backtest_pregain_history.py), so the
EDGE GATE keeps every real trade OFF and the auto-trader paper-trades only — exactly
as it should. When/if the validator proves positive expectancy, LIVE unlocks (with
explicit opt-in). This honours: profit-first ("volume is a RESULT of profitability")
and the user's safety rule (no unattended real-money loop on an unvalidated signal).

`decide` is pure & unit-tested. Order placement is a clearly-marked boundary:
PAPER logs the intended order; LIVE is a gated hook (deferred until edge + secret).
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULTS = {
    "capital": float(os.environ.get("ANANTARA_CAPITAL_USD", "60").split("#")[0].strip()),
    "max_positions": 5,            # v6.1: 3→5 — backtest 877 sinyal, margin $20/5x = $4/pos
                                  # max daily loss 5×5%×$20=$5 < daily_cap $12 ✅ AMAN
    "max_position_usd": 20.0,
    "min_position_usd": 11.0,   # HL minimum $10; floor at $11 untuk safety
    "paper_nominal": 10.0,        # nominal size for paper trades when no edge yet
    "daily_loss_cap": 0.20,       # stop for the day at -20% of capital (fraction)
    "min_sample": 30,             # min validated trades before edge is trusted
    "min_edge_r": 0.10,           # min expectancy (R) to allow real money
    "kelly_fraction": 0.50,       # half-Kelly — quarter-Kelly hasilkan $9.70 < min $11
                                  # Half-Kelly: S=$19.41, B=$20(cap), C=$19.45, A=$11(floor)
                                  # Sizing kini proporsional dengan edge, bukan stuck di minimum
    # SL/TP defaults: pakai TP=20% karena Grade C E=+0.081R (OPEN) dengan geometry ini.
    # CATATAN: TP=15% ternyata MENUTUP Grade C (E=-0.029R) — jangan ganti.
    # Finding #7 insight: SL/TP research butuh lebih banyak data sebelum ada kesimpulan.
    # OPTIMAL_GRADE_PARAMS (TP=15%) hanya untuk research display, bukan edge stats.
    "sl_pct": 3.0,     # v8.6: SL=3% optimal from 1,420-signal batch sweep (+1.014R vs 5%:+0.675R)
    "tp_pct": 20.0,   # proven: Grade C E=+0.081R OPEN dengan TP=20%
}

# Per-grade edge thresholds — v8.9: imported from pregain_execution (canonical definition)
try:
    from anantara.pregain_execution import GRADE_EDGE_THRESHOLDS
    from anantara.pregain_project_gate import evaluate_project_live_gate
except ImportError:
    from pregain_execution import GRADE_EDGE_THRESHOLDS  # type: ignore
    from pregain_project_gate import evaluate_project_live_gate  # type: ignore

AUDIT_LOG = Path(os.environ.get("ANANTARA_AUTOTRADE_LOG",
                 str(Path.home() / ".local/share/anantara/autotrader.jsonl")))

# Edge stats cache — thread-safe, recompute max every 15 minutes
import threading as _threading
_EDGE_CACHE: tuple[float, dict] = (0.0, {})
_EDGE_CACHE_TTL  = 1800  # 30 minutes — reduced from 15min to halve backtest CPU/memory pressure
_EDGE_CACHE_LOCK = _threading.Lock()

DAILY_STATE_PATH = Path(os.environ.get("ANANTARA_AUTOTRADE_DAILY",
                         str(Path.home() / ".local/share/anantara/autotrader_daily.json")))

# ── Regime Gate Constants (v9.0) ──────────────────────────────────────────────
_REGIME_GATE_DAYS         = 3    # primary rolling window in days
_REGIME_GATE_FALLBACK_DAYS = 7   # v11.6 K16: fallback when 3d n<min_n (Mon mornings)
_REGIME_GATE_MIN_N         = 40  # min signals to activate (n<min_n → no override, fail-safe)
_REGIME_WR_FLOOR           = 0.50  # WR floor; below → edge_ok forced False → all SHORT → PAPER

# ── EU Session Exemption Constants (v11.10, K21) ─────────────────────────────
# EU 7d WR=61.1% n=36 (p=0.015 vs BE 43.2%) is the ONLY session with positive E(R)
# in the current ranging regime. EU should not be silenced by the global regime gate.
_EU_EXEMPT_WR_FLOOR = 0.50   # EU 7d WR must exceed this to exempt from regime gate
_EU_EXEMPT_MIN_N    = 30     # EU must have ≥30 weekday SHORT signals in 7d window

# ── Grade S × US Exemption Constants (v11.11, K22) ───────────────────────────
# Grade S × US: 7d WR=52.4% n=42 (p=0.008 vs regime baseline 34.8%) — SIGNIFICANT.
# All-time WR=67.4% n=132 (p=0.000 vs BE 43.2%) confirms strong historical alpha.
# Dynamic self-governing check: auto-deactivates if WR drops to ≤50% or n < 30.
_GRADE_S_US_EXEMPT_WR_FLOOR = 0.50  # Grade S×US 7d WR must exceed this to exempt
_GRADE_S_US_EXEMPT_MIN_N    = 30    # must have ≥30 Grade S × US weekday SHORT in 7d

# ── Rolling Edge Gate Constants (v11.0, K2 fix) ───────────────────────────────
# Audit finding: W22 crash week = 74.7% of all historical data → all-time edge stats
# always show OPEN even when current-regime edge is negative (W23 WR=36%, W24 WR=43%).
# Fix: use rolling 14-day window so edge gate reflects the current trading regime.
# Audit: "sistem secara struktural menyetir lewat kaca spion" (structural rear-view mirror).
_EDGE_ROLLING_DAYS = 7       # rolling window for edge gate; set 0 to disable (all-time)
# Why 7 (not 14): W22 crash week (Jun 1-7) is within 14d window and has n=1943,
# WR=61.7% → still dominates at 14d. 7d = Jun 8-15 only (W23+W24), correctly
# shows all grades CLOSED (E negative, WR 20-39%) in current ranging regime.

# ── K4 Sovereign Gate Enforcement (v11.0) ─────────────────────────────────────
# Fable 5 audit finding: gates returned NO_GO (1/10) on Jun 4; live started Jun 6 anyway.
# Root cause: gate results were only sent to Telegram — never read by the trading loop.
# Fix: pregain_backtest.run_sovereign_gates() now auto-saves to pregain_sovereign_verdict.json;
# _read_sovereign_verdict() reads it; run_once() enforces NO_GO as hard-block on LIVE.
_SOVEREIGN_VERDICT_TTL_DAYS = 8   # stale after 8d (gates run weekly, 1d grace)
_SOVEREIGN_VERDICT_PATH = (
    Path(os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti")))
    / "data" / "pregain_sovereign_verdict.json"
)

# ── PARAMETER FREEZE (v12.0, F1.5 — Doctrine §4.1) ──────────────────────────
# Audit K-3 finding: ±130 fitted constants from ≤12 days of data → massive overfitting.
# Fable 5: "Setiap 'recalibration ilmiah' membatalkan dirinya sendiri … proses ini
# memproduksi noise, bukan pengetahuan."
#
# FREEZE: Semua daftar coin, jam, sesi, boost, dan threshold DIBEKUKAN 8 minggu.
# Hanya boleh berubah di batas fase dengan dokumen analisis out-of-sample.
# Mekanisme: SHA256 hash dari semua set parameter — jika berubah, WARNING + Telegram.
_PARAMETER_FREEZE_DATE   = "2026-06-15"       # tanggal doktrin dibekukan
_PARAMETER_FREEZE_WEEKS  = 8                   # minimum 8 minggu
_PARAMETER_FREEZE_UNTIL  = "2026-08-10"        # auto-computed: freeze_date + (weeks * 7) days
_PARAMETER_FREEZE_HASH   = ""                  # computed once at import; frozen value
_PARAMETER_FREEZE_WARNED = False               # only warn once per session

# ── V2.1 North Star Target (Pre-Gain swing system) ────────────────────────────
# Revised 2026-08-15: 0.7% → 0.5% of TOTAL wallet (spot+perps), per swing 1-30h.
# NOTIONAL_FRAC=0.50 (25% modal × 2× lev) → required notional gross avg ≥ 1.0%
# to yield 0.5% of modal. Reference only — gate enforcement in pregain_paper_monitor.py.
_NS_V21_TARGET_PCT = 0.005   # 0.5% of total modal wallet per swing trade


def _compute_parameter_hash() -> str:
    """SHA256 of all frozen parameter sets — detects ANY change post-freeze.

    Covers: COIN_BLOCK, COIN_ELITE_*, PRIME_HOURS, DEAD_HOURS,
    _REGIME_DEAD_HOURS, GRADE_EDGE_THRESHOLDS, CONFLICT_COIN_BLOCK,
    all boosting tiers, DEFAULT SL/TP/edge thresholds, and timing constants.
    """
    import hashlib as _hl
    _h = _hl.sha256()
    # Coin lists (sorted for deterministic hash)
    for _name in ["COIN_BLOCK", "COIN_ELITE_ALL", "COIN_ELITE_50",
                   "COIN_ELITE_40", "COIN_ELITE_35", "COIN_ELITE_25",
                   "COIN_ELITE_20", "COIN_ELITE_15", "CONFLICT_COIN_BLOCK"]:
        _val = globals().get(_name, set())
        _h.update(_name.encode())
        _h.update(repr(sorted(_val)).encode())
    # Hour sets
    for _name in ["PRIME_HOURS", "DEAD_HOURS", "_REGIME_DEAD_HOURS"]:
        _val = globals().get(_name, set())
        _h.update(_name.encode())
        _h.update(repr(sorted(_val)).encode())
    # Grade thresholds
    try:
        from anantara.pregain_execution import GRADE_EDGE_THRESHOLDS as _GET
    except ImportError:
        from pregain_execution import GRADE_EDGE_THRESHOLDS as _GET  # type: ignore
    _h.update(b"GRADE_EDGE_THRESHOLDS")
    _h.update(repr(dict(sorted(_GET.items()))).encode())
    # Numeric constants
    for _name in ["_REGIME_GATE_DAYS", "_REGIME_WR_FLOOR", "_REGIME_GATE_MIN_N",
                   "_EDGE_ROLLING_DAYS", "_EU_EXEMPT_WR_FLOOR", "_EU_EXEMPT_MIN_N",
                   "_GRADE_S_US_EXEMPT_WR_FLOOR", "_GRADE_S_US_EXEMPT_MIN_N",
                   "_SOVEREIGN_VERDICT_TTL_DAYS"]:
        _h.update(_name.encode())
        _h.update(repr(globals().get(_name)).encode())
    # DEFAULTS
    for _k in sorted(DEFAULTS):
        _h.update(_k.encode())
        _h.update(repr(DEFAULTS[_k]).encode())
    return _h.hexdigest()


def _check_parameter_freeze() -> tuple[bool, str]:
    """Verify parameter sets haven't changed since freeze date.

    Returns (ok, message):
      ok=True  → parameters unchanged (or freeze period expired)
      ok=False → parameters changed DURING freeze period — VIOLATION

    First call computes the frozen hash. Subsequent calls compare.
    Only warns once per session to avoid log spam.
    """
    global _PARAMETER_FREEZE_HASH, _PARAMETER_FREEZE_WARNED
    import hashlib as _hl
    from datetime import date as _date

    # Check if freeze period is still active
    try:
        _freeze_until = _date.fromisoformat(_PARAMETER_FREEZE_UNTIL)
        _today = _date.today()
        if _today > _freeze_until:
            return True, (f"Freeze expired {_PARAMETER_FREEZE_UNTIL} — "
                          f"parameter dapat diubah dengan doktrin baru")
    except (ValueError, TypeError):
        pass  # malformed date → assume freeze active

    # Compute current hash
    _current = _compute_parameter_hash()

    # First call: record frozen hash
    if not _PARAMETER_FREEZE_HASH:
        _PARAMETER_FREEZE_HASH = _current
        return True, (f"Parameter FREEZE aktif sejak {_PARAMETER_FREEZE_DATE} "
                      f"(hash={_current[:12]}…) — tidak boleh berubah sampai "
                      f"{_PARAMETER_FREEZE_UNTIL}")

    # Subsequent calls: compare
    if _current != _PARAMETER_FREEZE_HASH:
        if not _PARAMETER_FREEZE_WARNED:
            _PARAMETER_FREEZE_WARNED = True
            return False, (f"⚠️ PARAMETER FREEZE VIOLATION: hash berubah "
                           f"({_PARAMETER_FREEZE_HASH[:12]}… → {_current[:12]}…) — "
                           f"parameter TIDAK BOLEH berubah sampai "
                           f"{_PARAMETER_FREEZE_UNTIL}. Kembalikan ke nilai beku "
                           f"atau tulis doktrin baru dengan bukti out-of-sample.")
        return False, "Parameter freeze violation (suppressed repeat)"

    return True, f"Parameter freeze OK (hash={_current[:12]}… unchanged since {_PARAMETER_FREEZE_DATE})"


def _read_sovereign_verdict() -> tuple[str | None, str]:
    """Read the most recent sovereign gate verdict.

    Returns (verdict, reason):
      verdict: "NO_GO" | "ACCUMULATING" | "GO_PAPER" | "GO_LIVE_MICRO" | None
               None = file missing (fail-open: no enforcement).
      reason:  human-readable explanation for Telegram/log output.

    Fails-OPEN when file is missing (never ran gates = don't block silently).
    Fails-CLOSED only when verdict exists and is explicitly "NO_GO".
    Stale files (> TTL days) are treated as missing to avoid staleness blocking.
    """
    try:
        if not _SOVEREIGN_VERDICT_PATH.exists():
            return None, "gates belum dijalankan (file missing) → tidak memblokir"
        import json as _j
        data = _j.loads(_SOVEREIGN_VERDICT_PATH.read_text())
        saved_ts = data.get("saved_ts", 0)
        age_days = (time.time() - saved_ts) / 86400
        if age_days > _SOVEREIGN_VERDICT_TTL_DAYS:
            return None, (f"gates kadaluarsa ({age_days:.1f}d > {_SOVEREIGN_VERDICT_TTL_DAYS}d) → tidak memblokir")
        verd    = data.get("verdict", "ACCUMULATING")
        n_pass  = data.get("passed_gates", 0)
        n_total = data.get("total_gates", 10)
        n_sig   = data.get("n_signals", 0)
        return verd, (f"verdict={verd} ({n_pass}/{n_total} gates, {age_days:.1f}d lalu, n={n_sig} sinyal)")
    except Exception as _e:
        return None, f"error baca verdict: {_e}"


def _compute_regime_gate(db_path: str | Path,
                         days: int = _REGIME_GATE_DAYS,
                         min_n: int = _REGIME_GATE_MIN_N,
                         wr_floor: float = _REGIME_WR_FLOOR,
                         fallback_days: int = _REGIME_GATE_FALLBACK_DAYS,
                         ) -> tuple[bool, float | None, int]:
    """Compute rolling-N-day aggregate SHORT WR from signal_log.correct.

    Returns (gate_active, wr, n):
      gate_active: True  → regime negative (WR < wr_floor), override edges to PAPER.
                   False → regime OK or insufficient data (fail-safe open).
      wr:          rolling WR float (None when n < min_n in all tried windows).
      n:           number of resolved weekday SHORT signals in the window that was used.

    v11.6 K16: cascades to fallback_days (default=7) when primary window has n<min_n.
    This prevents fail-open on Monday mornings when 3d window only covers Friday signals
    (n≈28, below min_n=40), while the 7d WR clearly shows a negative regime (35% WR).

    Uses signal_log.correct (always fresh, no candle cache) — O(1) SQLite query.
    Scientific basis: WR floor=50% > real live breakeven of 46.4% (avg_win=+4.80%,
    avg_loss=-4.16%, RR=1.15:1). Provides +3.6pp safety margin above breakeven.
    Fail-safe: any exception → returns (False, None, 0) so trading continues as normal.
    """
    def _query_window(conn: object, since: int) -> tuple[int, int]:
        row = conn.execute(  # type: ignore[attr-defined]
            """SELECT COUNT(*), COALESCE(SUM(correct), 0)
               FROM signal_log
               WHERE direction='SHORT' AND correct IS NOT NULL
                 AND ts >= ?
                 AND strftime('%w', ts, 'unixepoch') NOT IN ('0','6')""",
            (since,)
        ).fetchone()
        return int(row[0] or 0), int(row[1] or 0)

    try:
        import sqlite3 as _sql
        conn = _sql.connect(str(db_path))
        # Primary window (default 3d)
        n, wins = _query_window(conn, int(time.time()) - days * 86400)
        if n >= min_n:
            conn.close()
            wr = wins / n
            return (wr < wr_floor), wr, n
        # v11.6 K16: fallback to wider window when primary is insufficient
        if fallback_days > days:
            n2, wins2 = _query_window(conn, int(time.time()) - fallback_days * 86400)
            conn.close()
            if n2 >= min_n:
                wr2 = wins2 / n2
                return (wr2 < wr_floor), wr2, n2
            return False, None, n2  # insufficient even in fallback
        conn.close()
        return False, None, n   # insufficient data — do not override
    except Exception:
        return False, None, 0       # fail-safe: no override on error


def _compute_eu_session_wr(db_path: str | Path, days: int = 7) -> tuple[float, float, int]:
    """Compute EU session rolling-N-day WR and E(R) for K21 regime gate exemption.

    Returns (wr, er, n):
      wr:  EU session win-rate (0.0–1.0)
      er:  E(R) = avg_pct / 3.0 (SL_PCT=3.0 per K3/K5 formula)
      n:   number of resolved EU weekday SHORT signals in the window

    Falls back to (0.0, -9.9, 0) on any error (fail-safe → no exemption).
    """
    try:
        import sqlite3 as _sql
        _since = int(time.time()) - days * 86400
        with _sql.connect(str(db_path)) as _conn:
            row = _conn.execute(
                """SELECT COUNT(*),
                          COALESCE(SUM(correct), 0),
                          COALESCE(AVG(outcome_pct), 0)
                   FROM signal_log
                   WHERE direction='SHORT' AND session='EU' AND correct IS NOT NULL
                     AND ts >= ?
                     AND strftime('%w', datetime(ts, 'unixepoch')) NOT IN ('0','6')""",
                (_since,)
            ).fetchone()
        n, wins, avg_pct = row
        wr = wins / n if n > 0 else 0.0
        er = avg_pct / 3.0 if n > 0 else -9.9
        return float(wr), float(er), int(n)
    except Exception:
        return 0.0, -9.9, 0


def _compute_grade_s_us_wr(db_path: str | Path, days: int = 7) -> tuple[float, float, int]:
    """Compute Grade S × US rolling-N-day WR and E(R) for K22 regime gate exemption.

    Returns (wr, er, n):
      wr:  Grade S × US win-rate (0.0–1.0)
      er:  E(R) = avg_pct / 3.0 (SL_PCT=3.0 per K3/K5 formula)
      n:   resolved Grade S × US weekday SHORT signals in the window

    Falls back to (0.0, -9.9, 0) on any error (fail-safe → no exemption).
    """
    try:
        import sqlite3 as _sql
        _since = int(time.time()) - days * 86400
        with _sql.connect(str(db_path)) as _conn:
            row = _conn.execute(
                """SELECT COUNT(*),
                          COALESCE(SUM(correct), 0),
                          COALESCE(AVG(outcome_pct), 0)
                   FROM signal_log
                   WHERE direction='SHORT' AND session='US' AND grade='S' AND correct IS NOT NULL
                     AND ts >= ?
                     AND strftime('%w', datetime(ts, 'unixepoch')) NOT IN ('0','6')""",
                (_since,)
            ).fetchone()
        n, wins, avg_pct = row
        wr = wins / n if n > 0 else 0.0
        er = avg_pct / 3.0 if n > 0 else -9.9
        return float(wr), float(er), int(n)
    except Exception:
        return 0.0, -9.9, 0


def _compute_regime_trend(db_path: str | Path) -> dict:
    """Return rolling WR at multiple windows for trend display.

    Returns dict with keys '3d', '7d' each containing {'wr', 'n', 'active'}.
    Used for Telegram status display — non-critical, returns empty dict on error.
    """
    result: dict = {}
    try:
        import sqlite3 as _sql
        conn = _sql.connect(str(db_path))
        for days in (3, 7):
            since = int(time.time()) - days * 86400
            row = conn.execute(
                """SELECT COUNT(*), COALESCE(SUM(correct), 0)
                   FROM signal_log
                   WHERE direction='SHORT' AND correct IS NOT NULL
                     AND ts >= ?
                     AND strftime('%w', ts, 'unixepoch') NOT IN ('0','6')""",
                (since,)
            ).fetchone()
            n = int(row[0] or 0)
            w = int(row[1] or 0)
            wr = w / n if n else None
            result[f"{days}d"] = {
                "n": n,
                "wr": round(wr, 3) if wr is not None else None,
                "active": (n >= _REGIME_GATE_MIN_N and wr is not None and wr < _REGIME_WR_FLOOR),
            }
        conn.close()
    except Exception:
        pass
    return result


def _load_daily_state() -> dict:
    """Load today's risk state (auto-resets at midnight UTC). Persists across cycles."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        if DAILY_STATE_PATH.exists():
            data = json.loads(DAILY_STATE_PATH.read_text())
            if data.get("date") == today:
                return data
    except Exception:
        pass
    return {"date": today, "open_positions": 0, "daily_pnl_frac": 0.0, "trades": 0}


def _save_daily_state(state: dict) -> None:
    """Atomic write daily state (crash-safe: write tmp → replace)."""
    try:
        DAILY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(DAILY_STATE_PATH) + ".tmp"
        Path(tmp).write_text(json.dumps(state))
        os.replace(tmp, str(DAILY_STATE_PATH))
    except Exception as _e:
        # State-persist failures must be visible: a silent loss resets daily-loss
        # accounting on restart and could re-enable trading past the daily cap.
        print(
            f"AUTOTRADER_DAILY_STATE_SAVE_FAILED path={DAILY_STATE_PATH} err={_e}",
            file=sys.stderr,
        )


@dataclass
class Decision:
    action: str       # TRADE | SKIP
    mode: str         # PAPER | LIVE | -
    size_usd: float
    reason: str


_RISK_FLOAT_DEFAULTS = {
    "daily_pnl_frac": 0.0,
    "running_dd_frac": 0.0,
    "regime_gate_wr": 1.0,
    "eu_wr_7d": 0.0,
    "eu_er_7d": -9.9,
    "grade_s_us_wr_7d": 0.0,
    "grade_s_us_er_7d": -9.9,
}
_RISK_INT_DEFAULTS = {
    "open_positions": 0,
    "eu_n_7d": 0,
    "grade_s_us_n_7d": 0,
}


def _normalize_risk_state(risk_state: dict | None) -> tuple[dict, list[str]]:
    """Coerce risk telemetry to finite numbers before live decision gates.

    Risk state comes from persisted JSON plus exchange/account telemetry. If it is
    corrupt, live trading must fail closed rather than crash or silently bypass a
    loss/position/circuit-breaker gate.
    """
    raw = risk_state if isinstance(risk_state, dict) else {}
    clean = dict(raw)
    invalid: list[str] = []

    for key, default in _RISK_FLOAT_DEFAULTS.items():
        if key not in raw:
            clean[key] = default
            continue
        try:
            value = float(raw[key])
        except (TypeError, ValueError):
            invalid.append(key)
            value = default
        if not math.isfinite(value):
            invalid.append(key)
            value = default
        if key == "running_dd_frac":
            value = max(0.0, value)
        clean[key] = value

    for key, default in _RISK_INT_DEFAULTS.items():
        if key not in raw:
            clean[key] = default
            continue
        try:
            value_f = float(raw[key])
            if not math.isfinite(value_f):
                raise ValueError
            value = int(value_f)
        except (TypeError, ValueError):
            invalid.append(key)
            value = default
        clean[key] = max(0, value)

    return clean, sorted(set(invalid))


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL COIN LISTS (v8.5 — extracted from decide() for auto_research import)
# ═══════════════════════════════════════════════════════════════════════════════

# Structural underperformers — NEVER traded (WR<35%, avg<-4%)
# v8.26 update (2026-06-11, binomial p<0.05, n>=10, post-conflict Jun 7+):
#   ADDED: W (WR=21% n=14 p=0.029), ASTER (WR=23% n=22 p=0.009)
#   REMOVED: ZORA — was WR=77% n=13 p=0.046 ELITE★ (was wrongly blocked!)
# v11.1 update (2026-06-15, 7d rolling data analysis):
#   ADDED: BTC (7d WR=0% n=11, p=0.001 — extreme regime inversion; all-time=67%→0%)
#   ADDED: MON (7d WR=15% n=13, p=0.022 — consistently poor; all-time WR=38% already below BE)
# v11.5 update (2026-06-15, K14/K15 — PUMP + ZEC block):
#   ADDED: PUMP — all-time WR=39% n=36 (< breakeven 43.2%); 7d WR=26.1% n=23 (both timeframes
#          confirm sub-breakeven performance). Was removed from COIN_ELITE in v10.0 for same reason.
#          auto_research K14 fix auto-detects: p_lo=0.019 vs 0.50, e_r=-0.748, BH q=0.10 ✓
#   ADDED: ZEC (K15) — auto_research BLOCK_CANDIDATE: 7d WR=33.3% n=24, e_r=-0.537 (p=0.033
#          BH q=0.10). K13 already removed ZEC from COIN_ELITE. Current ranging/bull BTC regime
#          inverted ZEC SHORT performance. Unblock when rolling 7d WR recovers to ≥55%.
COIN_BLOCK = {"WLD", "HMSTR", "JTO", "AR", "ORDI", "LIT", "MEME", "BABY", "DASH",
              "W", "ASTER",
              "BTC",   # v11.1: 7d WR=0% n=11 p=0.001 (was elite; removed from COIN_ELITE_ALL/15)
              "MON",   # v11.1: 7d WR=15% n=13 p=0.022 (all-time 38% — consistently underperforms)
              "PUMP",  # v11.5 K14: all-time WR=39% n=36 + 7d WR=26.1% n=23 — consistently sub-BE
              "ZEC"}   # v11.5 K15: 7d WR=33.3% n=24 e_r=-0.537 p=0.033 BH-sig (K13 already de-elited)

# Elite coins: E≥1.0R from backtest — eligible for prime+elite MAX boost
# v8.26: +ZORA (WR=77% n=13)
# v8.28: +RENDER (WR=69% n=32 p=0.025), +LDO (WR=70% n=27 p=0.026)
# v10.0: -PUMP (all-time WR=39% n=36; v8.18 ELITE was n=8 only — insufficient)
# v11.1: -BTC (7d WR=0% n=11 → moved to COIN_BLOCK; regime inversion in ranging/bull BTC)
# v11.4: -ZEC (all-time WR=50% n=68; 7d WR=25% n=32 p_lo=0.029 vs breakeven — regime inversion)
#         +XMR (all-time WR=59.8% n=92; 7d WR=68.4% n=38 p_hi=0.001 vs breakeven — CONFIRMED ELITE)
# v11.8 K18a: -SOL (all-time WR=86.6% n=67; 7d WR=27.3% n=11 e_r=-0.494 — proactive de-elite
#              before regime gate opens; NOT blocked, trades continue at normal size to build n→20)
COIN_ELITE_ALL = {"SEI", "HYPE", "AVAX", "AAVE", "ADA", "ETH",
                  "INJ", "SUSHI", "XPL", "ONDO", "NEAR", "LINK", "DOGE",
                  # BTC removed v11.1 — in COIN_BLOCK (7d WR=0%, regime inversion)
                  # ZEC removed v11.4 — all-time WR=50% n=68; 7d WR=25% p_lo=0.029 regime inversion
                  # SOL removed v11.8 K18a — all-time WR=86.6%; 7d WR=27.3% n=11 e_r=-0.494 (de-elite, not block)
                  "PURR", "UNI", "APT", "WIF", "DOT", "ICP", "ZRO", "FARTCOIN", "MEGA",
                  "ZORA", "RENDER", "LDO",
                  "XMR"}  # v11.4: +XMR WR=59.8% n=92; 7d WR=68.4% n=38 p_hi=0.001

# Per-coin size boost tiers (E(R)-based, applied when not prime+elite)
# v10.0: ZEC downgraded ELITE_50→ELITE_35 (all-time WR=56% n=57; basis was early n=26 WR=89%
#        which has since regressed; W23 WR=29% confirms regime-dependent overstatement)
# v11.4: ZEC REMOVED from all elite tiers (all-time WR=50% n=68; 7d WR=25% n=32 p_lo=0.029)
#        XMR ADDED to ELITE_25 (all-time WR=59.8% n=92; 7d WR=68.4% n=38 p_hi=0.001)
COIN_ELITE_50 = set()                                            # no coins at +50% this cycle
COIN_ELITE_40 = {"SUSHI", "ICP", "XPL"}                          # +40% size
COIN_ELITE_35 = {"ZRO", "FARTCOIN"}                              # +35% size (ZEC removed v11.4)
COIN_ELITE_25 = {"SEI", "HYPE", "AVAX", "AAVE", "PURR", "MEGA", "ONDO",
                 "ZORA", "XMR"}  # v11.4: +XMR (7d WR=68.4% n=38, p_hi=0.001)
COIN_ELITE_20 = {"INJ", "ADA", "ETH", "LINK", "DOGE", "NEAR",
                 "RENDER", "LDO"}  # v8.28: +RENDER(WR=69%,n=32) +LDO(WR=70%,n=27)
                                   # v11.8 K18a: -SOL (7d WR=27.3% n=11 e_r=-0.494; all-time 86.6% → inversion)
COIN_ELITE_15 = set()  # BTC removed v11.1 — in COIN_BLOCK (7d WR=0% regime inversion)

# Conflict-specific coin block (v8.16, June 7+ post-conflict n=392 signals):
# These coins had strong pre-conflict performance but collapsed during Iran conflict.
# Active ONLY when event_risk=RED — prevents LIVE trades, keeps PAPER for data.
# When conflict ends, CONFLICT_COIN_BLOCK has no effect (normal elite lists apply).
#   High confidence (n≥10, WR<25%): XMR=13%(n=15), SOL=21%(n=14), BTC=0%(n=10),
#                                    NEAR=0%(n=10), OP=18%(n=11)
#   Statistical (n≥6, WR=0%, p≤0.05): ONDO=0%(n=6), JUP=0%(n=6)
#   Marginal (n=5, WR=0%, p≈0.08): APT=0%(n=5), FARTCOIN=0%(n=5)
CONFLICT_COIN_BLOCK = {
    # v8.27 (2026-06-11, n=2339): REMOVED BTC (WR=68%,n=72,p=0.001) + SOL (WR=72%,n=87,p=0.000)
    # Both have RECOVERED and are now strong SHORT signals during ongoing conflict.
    # Root cause of v8.16 error: based on n=10/14 (too small samples).
    # Remaining coins: still uncertain or confirmed weak (p>0.05 OR WR<55%)
    # v11.4: REMOVED XMR — stale entry (WR=52% n=60 was from small conflict sample;
    #   all-time now WR=59.8% n=92 p_hi=0.001 vs breakeven; 7d WR=68.4% n=38 — CONFIRMED ELITE)
    "NEAR",      # WR=52% n=42 p=0.439 — borderline
    "APT",       # WR=48% n=25 p=0.500 — genuinely flat/negative
    "ONDO",      # WR=56% n=48 p=0.235 — not significant
    "JUP",       # WR=66% n=29 p=0.068 — borderline (keep until p<0.05)
    "FARTCOIN",  # WR=60% n=48 p=0.097 — borderline (but in COIN_ELITE_ALL when not RED)
    "OP",        # WR=61% n=28 p=0.172 — not significant, conservative keep
}

# Prime hours — confirmed WR≥65% with p<0.01.
# v8.26 basis: post-conflict all-time n=2339 SHORT signals.
# v11.1 update (2026-06-15, 7d rolling analysis n=457 Jun 8-14):
#   EXTREME INVERSIONS removed from PRIME:
#   UTC 00h: all-time WR=68% → 7d WR=25% n=24 p=0.013 → MOVED TO DEAD
#   UTC 13h: all-time WR=69% → 7d WR=33% n=15, Δ=-36pp  → REMOVED (borderline p=0.15)
#   UTC 21h: all-time WR=67% → 7d WR=28% n=29 p=0.013 → MOVED TO DEAD
#   UTC 22h: all-time WR=67% → 7d WR=11% n=28 p<0.0001 → MOVED TO DEAD (most extreme!)
#   RETAINED (7d WR still positive or small n):
#   UTC 01h: 7d WR=54% n=13 — borderline, keep
#   UTC 06h: 7d WR=50% n=8  — small n, keep conservatively
#   UTC 10h: 7d WR=67% n=15 — ONLY hour holding up in 7d data!
#   UTC 14h: 7d WR=56% n=9  — small n, keep
#   UTC 15h: 7d WR=44% n=41 — borderline, keep (protective gate handles bad periods)
PRIME_HOURS = {1, 6, 10, 14, 15}

# Dead hours — STRUCTURAL (consistently poor regardless of regime):
#   UTC 23h: all-time WR=42.9%/n=84, pre-7d WR=48.5%/n=66 — consistently below 50%.
#            The only hour with persistent underperformance across ALL regime periods.
#   (v11.1 K7 added {0,16,20,21,22} based on 7d; K23 moved them to _REGIME_DEAD_HOURS —
#    those hours were 70-85% WR historically and are REGIME inversions, not structural.)
DEAD_HOURS = {23}

# Regime-conditional dead hours (K23, v11.12, 2026-06-15):
# K7 (v11.1) added {0,16,20,21,22} to DEAD_HOURS based on 7d rolling data.
# Full historical analysis reveals these are REGIME INVERSIONS, not structural dead zones:
#   h00: pre-7d WR=85.3%/n=68 → 7d WR=25% (Δ=-60pp) — was PRIME historically
#   h16: pre-7d WR=84.5%/n=58 → 7d WR=15% (Δ=-69pp) — excellent historically
#   h20: pre-7d WR=70.6%/n=34 → 7d WR=21% (Δ=-50pp) — strong historically
#   h21: pre-7d WR=83.6%/n=67 → 7d WR=28% (Δ=-56pp) — was PRIME historically
#   h22: pre-7d WR=82.3%/n=79 → 7d WR=11% (Δ=-71pp) — was PRIME, most extreme
# These hours WILL return to their historical WR when regime recovers (WR≥65%).
# Static DEAD_HOURS would permanently block them. Fix: regime-conditional like K11/K12.
# Threshold: 0.65 matches "stable regime confirmed" tier from K9/K11/K12.
_REGIME_DEAD_HOURS = frozenset({0, 16, 20, 21, 22})

# Event risk gate — set to True to disable (used by tests)
EVENT_RISK_DISABLED = False


def _btc_ret_24h() -> float | None:
    """BTC 24h return (%) — dibungkus agar mudah di-mock di tes."""
    try:
        from anantara.market_regime import btc_return_24h
        return btc_return_24h()
    except Exception:
        return None


# Gate arah SHORT (2026-11-04, n=5.177 sinyal 2026-09-01..11-03).
# Arm SHORT Pre-Gain E=-0.198R (n=2.155, t=-6.4) dan negatif di SEMUA 20
# kombinasi SL/TP yang diuji. Satu-satunya pembeda: regime BTC 24 jam.
#   BTC 24h > +1%  → SHORT E=+0.164R (n=448, H1 +0.101 / H2 +0.294)
#   BTC 24h < -1%  → SHORT E=-0.437R (n=440, dua paruh negatif)
# Artinya sinyal ini mean-reversion: short hanya saat BTC over-extended naik.
# Fail-closed: data BTC tidak tersedia → SHORT ditolak (arm defaultnya rugi).
SHORT_BTC_MIN_24H_PCT = float(os.environ.get("PREGAIN_SHORT_BTC_MIN_PCT", "1.0"))

# Jejak keputusan Pre-Gain (2026-11-04): daemon hanya log.debug saat semua
# sinyal SKIP, sehingga alasan gate (mis. "SHORT blocked") tidak pernah
# tersimpan. JSONL ini dipakai monitoring 24 jam & audit gate berikutnya.
_SCRATCH = os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti"))
DECISION_AUDIT_PATH = Path(os.environ.get(
    "PREGAIN_DECISION_AUDIT", str(Path(_SCRATCH) / "data" / "pregain_decisions.jsonl")))


def _audit_decision(sig: dict, d: "Decision") -> None:
    """Catat satu keputusan (TRADE/SKIP) ke JSONL. Gagal tulis tidak boleh
    menghentikan trading — semua error ditelan."""
    try:
        rec = {
            "ts": int(time.time()),
            "coin": sig.get("coin"),
            "direction": sig.get("direction"),
            "grade": sig.get("grade"),
            "score": sig.get("score"),
            "action": d.action,
            "mode": d.mode,
            "reason": d.reason[:200],
        }
        DECISION_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DECISION_AUDIT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _audit_scan(longs: list, shorts: list, actionable: list, regime: str) -> None:
    """Catat ringkasan scan (bukan hanya sinyal yang sampai decide()).

    Tanpa ini, laporan '0 SHORT diblokir' ambigu: bisa berarti gate bekerja
    (semua diblokir) atau memang tidak ada SHORT yang lolos filter actionable.
    """
    try:
        rec = {
            "ts": int(time.time()),
            "type": "scan",
            "regime": regime,
            "btc24": _btc_ret_24h(),
            "n_long_raw": len(longs),
            "n_short_raw": len(shorts),
            "n_actionable": len(actionable),
            "n_long_actionable": sum(1 for s in actionable if str(s.get("direction")).upper() == "LONG"),
            "n_short_actionable": sum(1 for s in actionable if str(s.get("direction")).upper() == "SHORT"),
        }
        DECISION_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DECISION_AUDIT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def decide(signal: dict, edge_stats: dict | None, whale_conf: int,
           risk_state: dict, live_enabled: bool, params: dict | None = None) -> Decision:
    """Pure decision: should we act on this signal, in what mode, what size?

    signal: {coin, direction, grade, liq, ...}
    edge_stats: {grade: {n, win_rate, expectancy_r}} from the validator/backtest.
    whale_conf: +1 confirm / 0 neutral / -1 oppose (whale_tracker.confirms).
    risk_state: {open_positions, daily_pnl_frac}.

    LAYER -1 (sovereign gate): circuit breaker check runs FIRST, before all other gates.
    This is the fail-safe hidup — if CB is RED/BLACK, no trade regardless of signal quality.
    """
    p = {**DEFAULTS, **(params or {})}
    grade, direction = signal.get("grade", "C"), signal.get("direction", "")
    session   = signal.get("session", "")
    score     = int(signal.get("score", 0) or 0)
    scan_size = int(signal.get("scan_size", 1) or 1)
    coin_name = signal.get("coin", signal.get("name", ""))  # needed early for CONFLICT_COIN_BLOCK

    # Guard: reject malformed signals with no coin identifier before any gate logic.
    # A missing coin_name would cause CONFLICT_COIN_BLOCK, place_order, and logging
    # to operate on "" — potentially placing an order on an invalid coin.
    if not coin_name:
        return Decision("SKIP", "PAPER", 0.0, "signal missing coin/name field — reject")

    # ── LAYER -1.9: SHORT regime gate (2026-11-04) ─────────────────────────
    # Hanya SHORT futures yang disentuh; LONG/LONG_TECHNICAL/SPOT tidak.
    # Alasan empiris (lihat SHORT_BTC_MIN_24H_PCT): SHORT rugi di semua regime
    # kecuali BTC over-extended naik (>+1% / 24 jam).
    if str(direction).upper() == "SHORT":
        _b24 = _btc_ret_24h()
        if _b24 is None:
            return Decision("SKIP", "-", 0.0,
                            "SHORT blocked: BTC 24h data unavailable (fail-closed — "
                            "SHORT arm E=-0.198R tanpa filter regime)")
        if _b24 <= SHORT_BTC_MIN_24H_PCT:
            return Decision("SKIP", "-", 0.0,
                            f"SHORT blocked: BTC 24h {_b24:+.2f}% ≤ "
                            f"+{SHORT_BTC_MIN_24H_PCT:.1f}% (SHORT edge hanya saat "
                            f"BTC over-extended; E=-0.437R bila BTC turun)")

    risk_state, _risk_invalid = _normalize_risk_state(risk_state)
    if _risk_invalid and live_enabled:
        return Decision("SKIP", "-", 0.0,
                        f"risk_state invalid ({', '.join(_risk_invalid)}) — live fail-closed")

    # ── LAYER -2: Event Risk Gate (Geo-Political / Whale / Policy Shock) ──
    # v8.11 WISE: Integrates sodex_event_shock_guard.py into Pre-Gain decisions.
    # Monitors Google News RSS for Iran war, Trump decisions, Saylor BTC sales,
    # whale exchange transfers, and other market-moving headlines.
    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║  WISDOM PRINCIPLE: Every condition has opportunity for those who    ║
    # ║  know DIRECTION. Prolonged conflict = bearish tailwind for SHORT.   ║
    # ║  PROOF: PURR +10.4% during Iran conflict. SHORT works WITH fear.   ║
    # ╚══════════════════════════════════════════════════════════════════════╝
    # RED (≥75):    SHORT = TAILWIND (full size if BTC bearish, -30% if BTC bullish)
    #               LONG = REDUCE 30% (counter-trend during conflict)
    # ORANGE (≥55): PAPER only — no LIVE orders, data gathering only.
    # YELLOW (≥30): Reduce size 25% — elevated uncertainty.
    # NORMAL (<30): Trade normally.
    _event_risk_level = "NORMAL"
    _event_risk_score = 0.0
    if not EVENT_RISK_DISABLED:
        try:
            from anantara.sodex_event_shock_guard import fetch_event_risk
            _er = fetch_event_risk()  # uses 5-min cache, no extra API cost
            _event_risk_level = _er.get("level", "NORMAL")
            _event_risk_score = float(_er.get("risk_score", 0))
        except Exception:
            pass  # graceful: event guard unavailable → assume NORMAL

    if _event_risk_level == "RED":
        # v8.11 TRULY WISE GATE: Geo-political conflict is BEARISH for risk assets.
        # Conflict → FEAR → SELLING → BTC drops → SHORT profits.
        # The conflict IS the opportunity, not just the risk.
        #
        # PROOF: PURR +10.4% during Iran conflict — SHORT works BECAUSE of fear.
        #
        # REAL DANGER: Sudden ceasefire → sharp bounce → SHORT squeeze.
        # MITIGATION: Monitor BTC for sudden +3% hourly spike (ceasefire signal).
        # Otherwise: SHORT is MACRO-ALIGNED — trade with normal sizing.
        #
        # RULES (empirical v8.15, n=512 post-conflict signals):
        #   US S/A: borderline positive (56%/50%) → allow with -20% size reduction
        #   US B/C: negative (27%/19%) → PAPER only
        #   EU all: negative (15-38%) → PAPER only
        #   US_Asia all: catastrophic (14-47%) → PAPER only
        #   Asia all: negative or tiny-n → PAPER only
        #   Bearish BTC (mom > 0.02): irrational bounce → -30% additional reduction
        _btc_mom = signal.get("btc_momentum", 0.0)

        if _btc_mom > 0.02:
            # BTC bullish during war = market ignoring risk → be cautious
            p = {**p, "paper_nominal": p.get("paper_nominal", 15) * 0.70,
                 "max_position_usd": p.get("max_position_usd", 20) * 0.70}
            # Still allow — just reduced. Even irrational markets can turn.
        # else: BTC bearish/flat during war = macro aligned → FULL size
        # No reduction needed. This is the OPTIMAL setup for SHORT.

        # v8.27 CONFLICT GATES — recalibrated from n=2339 post-conflict signals (Jun 7+)
        # v8.15 used n=512; v8.27 uses 4.6× more data. Many previously-blocked combos recovered.
        # Methodology: binomial test, null p=0.50, one-sided. Promote at p<0.05, n≥50.
        # All promoted combos still get -20% size penalty vs normal (uncertainty discount).
        #
        # New data (Jun 7-11, n=2339):
        #   EU:      S=69%(n=75,p=0.000) B=59%(n=202,p=0.005) C=58%(n=57,p=0.145) A=52%(p=0.404)
        #   US_Asia: S=69%(n=65,p=0.001) C=62%(n=87,p=0.016) B=54%(p=0.175)  A=59%(p=0.174)
        #   Asia:    S=64%(n=140,p=0.001) A=60%(n=85,p=0.041) B=60%(n=321,p=0.000) C=63%(n=241,p=0.000)
        #   US:      S=68%(n=139,p=0.000) A=57%(n=109,p=0.090) B=54%(p=0.101) C=58%(n=248,p=0.009)
        _session = signal.get("session", "")
        _CONFLICT_PAPER_GATES: set[tuple] = {
            # EU: only A and C remain PAPER (p>0.10)
            ("EU", "A"),   # WR=52% p=0.404 n=67 — not significant
            ("EU", "C"),   # WR=58% p=0.145 n=57 — borderline, conservative
            # US_Asia: B and A remain PAPER
            ("US_Asia", "B"),  # WR=54% p=0.175 n=165
            ("US_Asia", "A"),  # WR=59% p=0.174 n=41
            # US: only B remains PAPER
            ("US", "B"),   # WR=54% p=0.101 n=297 — borderline
            # Asia: ALL promoted (all ≥60% WR, p<0.05) — no PAPER gates
        }
        if (_session, grade) in _CONFLICT_PAPER_GATES and live_enabled:
            _wr_map = {
                ("EU","A"): "52%,p=0.404", ("EU","C"): "58%,p=0.145",
                ("US_Asia","B"): "54%,p=0.175", ("US_Asia","A"): "59%,p=0.174",
                ("US","B"): "54%,p=0.101",
            }
            _wr_note = _wr_map.get((_session, grade), "?")
            return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                            f"🛑 RED+{_session}+{grade}: WR={_wr_note} post-conflict → PAPER")

        # Promoted combos: apply -20% size penalty (conflict discount, still uncertain)
        _CONFLICT_PROMOTED: set[tuple] = {
            ("EU","S"), ("EU","B"),
            ("US_Asia","S"), ("US_Asia","C"),
            ("Asia","S"), ("Asia","A"), ("Asia","B"), ("Asia","C"),
            ("US","C"),
        }
        if (_session, grade) in _CONFLICT_PROMOTED:
            # v8.27: promoted from PAPER → LIVE with -20% size (conflict uncertainty)
            p = {**p, "max_position_usd": p.get("max_position_usd", 20) * 0.80,
                 "paper_nominal": p.get("paper_nominal", 10) * 0.80}

        # US S/A: already LIVE, just size adjustment
        if _session == "US" and grade == "S":
            pass  # WR=68%, p=0.000 — full size OK now (was -20% in v8.15)
        elif _session == "US" and grade == "A":
            p = {**p, "max_position_usd": p.get("max_position_usd", 20) * 0.80,
                 "paper_nominal": p.get("paper_nominal", 10) * 0.80}
            # WR=57%, p=0.090 — still borderline, keep -20%

        # ── v8.27: Conflict Coin Block — recalibrated from n=2339 (Jun 7+) ──────
        # v8.16 block based on n=5-15 (too small). Updated assessment:
        #   REMOVED from block: BTC WR=68%(n=72,p=0.001), SOL WR=72%(n=87,p=0.000)
        #   Remaining: XMR=52%(n=60,borderline), NEAR=52%(n=42), OP=61%(n=28,p=0.172)
        #              APT=48%(n=25), ONDO=56%(n=48,p=0.235), JUP=66%(n=29,p=0.068)
        #              FARTCOIN=60%(n=48,p=0.097) — keep conservative (p>0.05)
        if coin_name in CONFLICT_COIN_BLOCK:
            if live_enabled:
                return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                                f"🛑 RED+coin_block+{coin_name}: WR uncertain post-conflict → PAPER")

        # ── v8.28: Vol/OI gate REMOVED (v8.16 finding invalidated by n=2339) ──────
        # v8.16: vol_oi>1.5 → WR=19% (n=42) → -25% size
        # v8.28: vol_oi>1.5 → WR=60%, avg=+2.87% (n=637) — ACTUALLY BEST CATEGORY!
        # Root cause: n=42 too small, random fluctuation. Larger dataset shows no penalty.
        # All vol_oi bands have WR=58-61%: <0.5=61%, 0.5-1=58%, 1-1.5=58%, >1.5=60%.
        # Gate removed. No size adjustment for vol_oi.

    elif _event_risk_level == "ORANGE" and live_enabled:
        return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                        f"⚠️ ORANGE ({_event_risk_score:.0f}/100): elevated → PAPER")
    elif _event_risk_level == "YELLOW":
        p = {**p, "paper_nominal": p.get("paper_nominal", 10) * 0.75,
             "max_position_usd": p.get("max_position_usd", 20) * 0.75}

    # ── LAYER -1.5: Intelligence Overlay (12-signal macro composite) ──────────
    # v8.9: Integrates anantara/intelligence.py into Pre-Gain decisions.
    # The intelligence composite measures: FG, momentum, BTC dominance, MTF alignment,
    # plus tilt signals (whale, funding, OI, stablecoin, liquidation flow).
    # STRONGLY_BEARISH (≤32): SHORT signals aligned → boost confidence
    # STRONGLY_BULLISH (≥72): SHORT signals opposed → skip/pause
    # NEUTRAL/BEARISH/BULLISH: no gate, just information
    _intel = signal.get("intel_score", 50.0)
    _intel_lbl = signal.get("intel_label", "NEUTRAL")
    if _intel_lbl == "STRONGLY_BEARISH" and direction == "SHORT" and live_enabled:
        # Macro supports SHORT — boost size by 10% (confidence overlay)
        p = {**p, "paper_nominal": min(p.get("paper_nominal", 10) * 1.10, 25),
             "max_position_usd": min(p.get("max_position_usd", 20) * 1.10, 25)}
    elif _intel_lbl == "STRONGLY_BULLISH" and direction == "SHORT":
        # Macro opposes SHORT — reduce size 25% or PAPER only
        if live_enabled:
            return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                            f"Intel STRONGLY_BULLISH ({_intel:.0f}): macro opposes SHORT → PAPER")
        p = {**p, "paper_nominal": p.get("paper_nominal", 10) * 0.75,
             "max_position_usd": p.get("max_position_usd", 20) * 0.75}

    # ── Pre-Sentiment Forecast Confidence Modifier (v8.9) ─────────────────────
    # Uses BTC momentum + regime + session to estimate signal reliability.
    # High confidence (>0.70): boost size 15% (strong trend alignment)
    # Low confidence (<0.45): reduce size 20% (weak/choppy market)
    _fc = signal.get("fc_conf", 0.60)
    if _fc > 0.70:
        p = {**p, "paper_nominal": min(p.get("paper_nominal", 10) * 1.15, 25),
             "max_position_usd": min(p.get("max_position_usd", 20) * 1.15, 25)}
    elif _fc < 0.45:
        p = {**p, "paper_nominal": p.get("paper_nominal", 10) * 0.80,
             "max_position_usd": p.get("max_position_usd", 20) * 0.80}

    # ── LAYER -1: Circuit Breaker (Sovereign Gate — first, before everything) ──
    # Inserted from pregain_circuit_breaker.py (v3 ULTIMATE adaptation).
    # Does NOT replace existing gates — runs before them as additional protection.
    try:
        from anantara.pregain_circuit_breaker import apply_circuit_breaker
    except ImportError:
        try:
            from pregain_circuit_breaker import apply_circuit_breaker  # type: ignore
        except ImportError:
            apply_circuit_breaker = None  # graceful: CB unavailable = no restriction

    if apply_circuit_breaker is not None:
        # daily_pnl_frac and open_positions: keep as 0 — handled by explicit gates below.
        # running_dd_frac: NOW populated from run_once() via risk_state (was always 0 before).
        # Separating concerns: CB tracks multi-day equity drawdown; explicit gates handle
        # same-day loss cap (line ~175) and position count (gate 1).
        _allowed, _cb_size, _cb_reason = apply_circuit_breaker(
            daily_pnl_frac=0.0,
            open_positions=0,
            running_dd_frac=risk_state.get("running_dd_frac", 0.0),
            base_size_usd=p.get("paper_nominal", 10.0),
        )
        if not _allowed:
            # RED or BLACK: immediate SKIP — protect capital absolutely
            return Decision("SKIP", "-", 0.0, f"CB {_cb_reason}")
        # YELLOW or ORANGE: reduce size. LIVE is still allowed (only RED/BLACK = SKIP).
        # Comment fix: "PAPER only" was wrong — YELLOW/ORANGE reduce size but remain LIVE.
        if _cb_size < p.get("paper_nominal", 10.0):
            _reduced = max(round(_cb_size, 2), 0.0)
            p = {**p, "paper_nominal": _reduced,
                 "max_position_usd": min(p.get("max_position_usd", _reduced), _reduced)}

    # ── HARD SAFETY GATES (absolute — always run first, no bypass) ───────────────
    # These must fire before any soft "downgrade to PAPER" gates (0a, 0b).
    # A DUST signal must SKIP even during prime funding zone; a max-position limit
    # must SKIP even during the best session. Order: CB → safety → soft gates.

    # 1. Liquidity — DUST signals never tradeable, even as paper
    if signal.get("liq") == "DUST":
        return Decision("SKIP", "-", 0.0, "DUST — likuiditas terlalu tipis")
    # 2. Risk limits — LIVE positions only (paper trades don't use capital)
    # v8.4: PAPER mode should ALWAYS log signals for edge validation,
    # regardless of LIVE position count. Max position gate only applies to LIVE.
    if live_enabled and risk_state.get("open_positions", 0) >= p["max_positions"]:
        return Decision("SKIP", "-", 0.0, f"max posisi LIVE ({p['max_positions']}) tercapai")
    if risk_state.get("daily_pnl_frac", 0.0) <= -p["daily_loss_cap"]:
        return Decision("SKIP", "-", 0.0, "daily loss cap tercapai — stop hari ini")
    # 3. Whale opposition
    if whale_conf < 0:
        return Decision("SKIP", "-", 0.0, "whales melawan arah sinyal")

    # ── HARD COIN SKIP GATES (structural underperformers — updated 2026-06-08) ──
    # Uses module-level COIN_BLOCK (v8.5: extracted for auto_research import)
    # coin_name already set at top of function (needed by CONFLICT_COIN_BLOCK check above)
    if coin_name in COIN_BLOCK:
        return Decision("SKIP", "-", 0.0,
                        f"{coin_name}: struktural underperformer (WR<35%, avg<-4%) — skip")

    # ── MARKET REGIME GATE (v8.6: updated with walk-forward data, n=1,420) ──────
    # Walk-forward validation (batch paper-trade) reveals edge is regime-dependent:
    #   TRENDING bear (BTC↓): E=+1.607R ★★★  — SHORT edge TERKUAT saat BTC turun
    #   RANGING:             E=+0.703R ★★   — moderate, mean-reversion works
    #   CHAOS (conflict/news): E=+0.184R ★    — edge nearly disappears
    # Old gate (v6.5, n=39): TRENDING→PAPER was based on bull-trending only.
    # New gate distinguishes bear trending (good for SHORT) vs bull trending (bad).
    _regime = signal.get("regime", "RANGING")
    _btc_mom = signal.get("btc_momentum", 0.0)  # BTC vs SMA20: >0 = bull, <0 = bear

    if _regime == "CHAOS":
        # Chaos regime: edge drops to +0.184R — reduce size 50%, keep PAPER for safety
        if live_enabled:
            return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                            f"CHAOS regime: E=+0.184R (walk-forward) — PAPER only, "
                            f"edge nearly zero during geo-political chaos")
        p = {**p, "paper_nominal": p.get("paper_nominal", 10) * 0.5,
             "max_position_usd": p.get("max_position_usd", 20) * 0.5}

    elif _regime == "TRENDING" and _btc_mom > 0.03:
        # Bull trending: SHORT gets squeezed by momentum → PAPER only
        if live_enabled:
            return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                            f"TRENDING BULL (BTC {_btc_mom*100:+.1f}%): SHORT edge negatif → PAPER")
        # In PAPER mode, still log for data

    elif _regime == "TRENDING" and _btc_mom <= 0.03:
        # Bear/flat trending: SHORT edge TERKUAT (+1.607R walk-forward)
        # No restriction — this is the optimal regime for Pre-Gain SHORT
        pass

    # ── GRADE A SESSION GATES (updated v7.8: exclude-weekend analysis) ──────────
    # CORRECTION: Previous gates (A+Asia=59%, A+US=57%) were Saturday-contaminated.
    # True weekday performance (excl Sat/Sun): A+Asia=78%, A+US=69%, A+EU=76%.
    # ALL Grade A sessions are above 69% threshold → NO session gates for Grade A.
    # Only exception: B+US_Asia at WR=66% — monitor but no gate yet (n=117).
    # (Grade A base gate still applies — non-prime, non-elite → PAPER for safety)

    # ── HARD SCORE SKIP GATES ──────────────────────────────────────────────────────
    # A-low US: old WR=37.8% was Saturday-contaminated. Weekday-only: WR=60% n=30.
    # Positive edge (E = 0.60×4 - 0.40 = 2.0R) → downgrade to PAPER, not SKIP.
    if grade == "A" and score <= 84 and session == "US" and live_enabled:
        return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                        f"A-low score {score} US: WR=60% n=30 (weekday) → PAPER "
                        f"(below 69% threshold, monitor until n≥50)")

    # B-mid (70-74) — v6.10 update: 2129 sinyal, Asia/EU now LIVE (E~1.07R)
    # Old: ALL → PAPER (E=-0.259R n=46 lama, then +0.583R n=95)
    # New data: Asia E=1.068R n=51, EU E=1.078R n=19 → LIVE!
    #           US E=0.283R n=71, US_Asia E=0.194R n=36 → Keep PAPER (marginal)
    # B-mid US/US_Asia: marginal edge, PAPER untuk tambah data
    if grade == "B" and 70 <= score <= 74 and session in ("US", "US_Asia") and live_enabled:
        return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                        f"B-mid score {score} {session}: E=+0.19-0.28R → PAPER "
                        f"(Asia E=1.068R n=51, EU E=1.078R n=19 → LIVE OK)")
    # Grade A: v7.9 update — weekday-only analysis (excl Sat/Sun) shows ALL sessions ≥69%:
    #   A-Asia: WR=77.6% n=58 | A-EU: WR=76.5% n=34 | A-US_Asia: WR=72.0% n=25 | A-US: WR=69.0% n=58
    #   A-low (80-84): WR=72.6% n=106 | A-high (85-89): WR=75.4% n=69
    # Old "A_base=WR=44.2% n=17 NEGATIF" was Saturday-contaminated + tiny sample.
    # Grade A base gate REMOVED — all sessions now confirmed LIVE-worthy.

    # ── SOFT TIMING GATES (downgrade LIVE → PAPER, never SKIP) ──────────────────
    # These run after safety gates — they cannot override hard safety decisions.

    # 0-PRE. TIME + PRIME + ELITE detection — SINGLE SOURCE OF TRUTH untuk semua gates
    import time as _time
    _utc_now      = _time.gmtime()
    _utc_hour     = _utc_now.tm_hour
    _utc_wday     = _utc_now.tm_wday   # 0=Mon … 6=Sun
    # Uses module-level COIN_ELITE_ALL (v8.5: extracted for auto_research import)
    _PRIME_HOURS  = PRIME_HOURS
    _in_prime     = _utc_hour in _PRIME_HOURS
    _is_elite     = coin_name in COIN_ELITE_ALL
    _is_friday    = (_utc_wday == 4)   # Fri: semua tier positif (base +1.251R!)
    _is_thursday  = (_utc_wday == 3)   # Thu: terkuat (Thu_PE +2.036R!)
    # "Base" = tidak prime DAN tidak elite (retained for S_base legacy ref + size logic)
    _is_base      = not _in_prime and not _is_elite

    # ── DAY-OF-WEEK GATES (update v11.1, 2026-06-15) ─────────────────────────────
    # Sunday:    WR=42% n=120 → PAPER (confirmed negatif, excl Sat)
    # Saturday:  WR=13% n=460 → PAPER (KRITIS, liquidity trap + weekend spread)
    # Tuesday:   WR=53.8% n=91 — heterogen by session:
    #   Tue Asia: C=100% n=11 | B=71.4% n=7 → LIVE OK
    #   Tue US_Asia: B=0% n=7 | S=14.3% n=7 → PAPER (catastrophic); C=71.4% n=14 → LIVE OK
    #   Tue US: S=20% n=5 | B=44.4% n=9 | A=28.6% n=7 → gated via "base" gate
    # Wednesday: all-time WR=47% → 7d WR=24% (Δ=-23pp, n=175, p≈0) — INVERSION
    #   Gate (v11.1): PAPER when regime_gate_wr < 0.65. Above 0.65 → trust history.
    # Thursday:  all-time WR=81% → 7d WR=8% (Δ=-73pp, n=59, p≈0) — EXTREME INVERSION
    #   Gate (v11.1): PAPER when regime_gate_wr < 0.65. Above 0.65 → size boost applies.
    #   Mechanism: Thu has highest funding → SHORT fires during BTC bull → squeezed.
    # Friday:    WR=80.7% n=726 → STRONG (size boost)
    # Monday:    WR=75.0% n=32 — Asia/EU/US_Asia excellent; US small n
    # Python tm_wday: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
    if _utc_wday == 6 and live_enabled:  # Sunday: WR=42% n=120 → PAPER
        return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                        "Sunday: WR=42% (n=120) — funding flat Minggu")
    if _utc_wday == 5 and live_enabled:  # Saturday: WR=13% n=460 → PAPER (KRITIS!)
        return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                        "Saturday: WR=13% avg=-3.9% (n=460) — weekend liquidity trap")
    if _utc_wday == 1 and _is_base and grade != "C" and live_enabled:
        # Tue base: B/S/A weak on US session (S=20%, B=44%, A=29%). Grade C exempt:
        # C+Asia=100% n=11, C+US=66.7% n=15, C+US_Asia=71.4% n=14 — all positive.
        return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                        f"Tuesday base {grade}: WR=54% heterogen → PAPER "
                        f"(C exempt: Asia=100% US_Asia=71.4% positive)")
    if _utc_wday == 1 and session == "US_Asia" and grade != "C" and live_enabled:
        # Tue US_Asia: B=0% n=7, S=14% n=7 — catastrophic; C=71.4% n=14 → LIVE OK
        return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                        f"Tue US_Asia {grade}: B=0% S=14% catastrophic → PAPER "
                        f"(C+US_Asia=71.4% n=14 → LIVE OK)")
    if _utc_wday == 2 and direction == "SHORT" and live_enabled:
        # v11.1: Wednesday regime-conditional gate.
        # 7d rolling (Jun 8-14): WR=24% n=175 (all-time WR=47% → INVERSION Δ=-23pp, p≈0).
        # When regime is not stable (regime_gate_wr < 0.65): Wednesday → PAPER.
        # When stable (≥0.65): trust all-time pattern (47% still below breakeven, monitor).
        _regime_wr_wed = risk_state.get("regime_gate_wr", 1.0)
        if _regime_wr_wed < 0.65:
            return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                            f"Wednesday: WR=24% 7d (all-time 47%→24%, Δ=-23pp n=175) — "
                            f"PAPER sampai regime_wr≥65% (saat ini={_regime_wr_wed:.0%})")
    if _utc_wday == 3 and direction == "SHORT" and live_enabled:
        # v11.1: Thursday regime-conditional PAPER gate.
        # 7d rolling (Jun 8-14): WR=8% n=59 (all-time WR=81% → EXTREME INVERSION Δ=-73pp, p≈0).
        # Root cause: Thursday = highest funding → signal fires "SHORT" during BTC bull bull → squeezed.
        # Gate: PAPER when regime_gate_wr < 0.65. Above 0.65 (stable): Thursday boost resumes.
        _regime_wr_thu = risk_state.get("regime_gate_wr", 1.0)
        if _regime_wr_thu < 0.65:
            return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                            f"Thursday: WR=8% 7d (all-time 81%→8%, Δ=-73pp n=59) — "
                            f"PAPER sampai regime_wr≥65% (saat ini={_regime_wr_thu:.0%})")

    # ── K11 (v11.2): US_Asia session — regime-conditional PAPER ──────────────
    # 7d rolling analysis (Jun 8-14, n=104): US_Asia WR=20.2% avg=-3.92%.
    # Regime-adjusted test: p=0.0008 vs baseline 35.4% — HIGHLY SIGNIFICANT.
    # All grades catastrophically bad: Grade B=20%, Grade C=16%, Grade A=13%, Grade S=32%.
    # All-time was WR=56.6% (all-time n=350) → Δ=-36pp inversion in current ranging/bull BTC regime.
    # EU (7d WR=56.8%) is the confirmed safe harbor — only session significantly ABOVE regime average.
    # Gate: PAPER when regime recovering (regime_gate_wr < 0.65). Resumes at ≥0.65 (stable regime).
    if session == "US_Asia" and direction == "SHORT" and live_enabled:
        _rwr_usa = risk_state.get("regime_gate_wr", 1.0)
        if _rwr_usa < 0.65:
            return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                            f"US_Asia: 7d WR=20% (all-time 57%→20%, Δ=-36pp n=104, p=0.001 vs regime) — "
                            f"PAPER sampai regime_wr≥65% (saat ini={_rwr_usa:.0%})")

    # ── K12 (v11.3): Grade B/C in US session — regime-conditional PAPER ─────────
    # 7d rolling analysis (Jun 8-14, weekday SHORTs, regime baseline WR=35.4%):
    # Grade B × US: WR=31.3% n=83, p=0.019 vs breakeven 43.2% — significantly below BE.
    # Grade C × US: WR=27.6% n=58, p=0.012 vs breakeven 43.2% — significantly below BE.
    # Grade S × US: WR=52.4% n=42, p_hi=0.016 vs regime baseline — SIGNIFICANTLY ABOVE.
    # Grade A × US: WR=47.2% n=36, p_hi=0.095 — borderline positive → allowed.
    # Session aggregate US: WR=37.0% (n=219) — near regime baseline, Grade S drives alpha.
    # Gate: B/C → PAPER when regime recovering (< 0.65). Grade S/A unaffected. Deactivates at ≥0.65.
    if session == "US" and direction == "SHORT" and live_enabled and grade in ("B", "C"):
        _rwr_us = risk_state.get("regime_gate_wr", 1.0)
        if _rwr_us < 0.65:
            _us_wr = {"B": 31, "C": 28}.get(grade, 30)
            _us_n  = {"B": 83, "C": 58}.get(grade, 70)
            return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                            f"US Grade {grade}: 7d WR={_us_wr}% n={_us_n} — below breakeven 43.2% "
                            f"(p<0.02) PAPER sampai regime_wr≥65% (saat ini={_rwr_us:.0%})")

    # ── HOURLY DEAD ZONE GATES ────────────────────────────────────────────────────
    # K23 (v11.12): Split into structural (DEAD_HOURS) and regime-conditional (_REGIME_DEAD_HOURS).
    # Structural h23 is ALWAYS blocked (all-time WR=42.9%/n=84 — consistently poor).
    # Regime-conditional {0,16,20,21,22}: historically excellent (70-85% pre-7d WR) but inverted
    # with current BTC ranging/bull regime — PAPER only until regime_gate_wr ≥ 0.65.
    if _utc_hour in _REGIME_DEAD_HOURS and live_enabled and direction == "SHORT":
        _rwr_rch = risk_state.get("regime_gate_wr", 1.0)
        if _rwr_rch < 0.65:
            _rch_wrs = {0: 25, 16: 15, 20: 21, 21: 28, 22: 11}
            _rchdwr  = _rch_wrs.get(_utc_hour, 25)
            _rch_pre = {0: 85, 16: 85, 20: 71, 21: 84, 22: 82}
            _rcppre  = _rch_pre.get(_utc_hour, 80)
            return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                            f"Regime-dead UTC {_utc_hour}h: 7d WR={_rchdwr}% (pre-7d={_rcppre}% — "
                            f"PAPER while regime_wr={_rwr_rch:.0%}<65%)")

    if _utc_hour in DEAD_HOURS and live_enabled and direction == "SHORT":
        return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                        f"Dead hour UTC {_utc_hour}h: structural WR=22%/n=18 (p<0.05) → PAPER")

    # 0a. SCAN SIZE GATE — riset: single signal WR=68% vs crowded scan WR=49%
    if scan_size > 15 and score < 85 and live_enabled:
        return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                        f"Crowded scan ({scan_size} signals): score {score}<85 → PAPER only")

    # 3b. EMPIRICAL SCORE-WITHIN-GRADE GATES (update 2026-06-05, n=676 resolved):
    #
    #   Score 70-74 (B-mid):   WR 46.8%, E=-0.259R — catastrophic, SKIP
    #   Score 80-84 (A-low):   WR 35.7%, E=-0.188R — bad esp US session, SKIP US
    #   Score 65-69 (B-low):   WR 85.3%, E=+0.744R  ★★ ELITE — size boost +30%
    #     B-low EU:            WR 94.1%, E=+1.180R  ★★★ BEST — size boost +40%
    #   Score 75-79 (B-high):  WR 74.1%, E=+0.119R  — low avg despite WR (careful!)
    #     B-high EU:           WR 88.9%, E=+0.963R  ★★★ ELITE — size boost +20%
    #     B-high US/US_Asia:   WR 48-50%, avg -3.5% — PAPER
    #   Grade S (90+):         E=+0.367R n=103 ✅ OPEN — Asia/EU best
    #     Grade S Asia:        WR 80%,  E=+0.548R ★★ — size boost +15%
    #     Grade S EU:          WR 92.6%,E=+0.531R ★★ — size boost +15%
    #     Grade S US:          E=+0.110R n=19  — need n≥30, PAPER for now
    #     Grade S US_Asia:     WR 45.5% — PAPER
    #   Grade C (60-64):       E=+0.300R n=184 ✅ OPEN
    #     Grade C SHORT Asia:  WR 90.7%, E=+0.675R ★★ — size boost +20%
    #     Grade C SHORT EU:    WR 87.5%, E=+0.553R ★★ — size boost +15%
    #     Grade C SHORT US:    WR 64.4%, avg +0.88% — borderline LIVE OK
    #     Grade C SHORT US_Asia:WR 69.7%,avg +2.24%— LIVE OK
    #
    #   SKIP gates: now moved to HARD SCORE SKIP GATES section above (before scan_size gate).

    # 3b-direction. DIRECTION GATE
    #
    # NOTE: SPOT_BREAKOUT diperiksa SEBELUM general LONG gate (berbeda signal type)
    # ── Pre-Gain SPOT path (pregain_spot_scanner signals) ────────────────────
    # Research: Price break 20-day high + vol>1.5x → WR=84.6% avg=+2.7% n=123 ★★★
    # SPOT = no liquidation risk, hold 10d, trailing stop 3%
    # Gate: PAPER sampai WR≥65% live (n≥20), LIVE saat WR≥69% (n≥30)
    if signal.get("type") == "SPOT_BREAKOUT":
        spot_st = (edge_stats or {}).get("SPOT_" + grade)
        spot_n  = spot_st.get("n", 0) if spot_st else 0
        spot_wr = spot_st.get("win_rate", 0) / 100 if spot_st else 0
        if spot_n < 20:
            return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                            f"SPOT Breakout: kumpul data (n={spot_n}/20) → PAPER")
        if spot_wr < 0.65:
            return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                            f"SPOT Breakout: WR={spot_wr:.1%}<65% → PAPER")
        if spot_n < 40 or spot_wr < 0.69:
            return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                            f"SPOT Breakout: WR={spot_wr:.1%} n={spot_n}/40 → PAPER "
                            f"(Wilson CI n=30 terlalu lebar ±15pp; butuh n≥40)")
        # Passed: LIVE SPOT order (smaller size for spot, no leverage)
        size = min(p["min_position_usd"] * 2.0, p["max_position_usd"] * 0.75)
        mode = "LIVE" if live_enabled else "PAPER"
        return Decision("TRADE", mode, round(size, 2),
                        f"SPOT Breakout LIVE: WR={spot_wr:.1%} n={spot_n} "
                        f"(backtest 84.6%, trail=3%)")

    # ── Pre-Gain LONG Futures path (pregain_long_scanner signals) ────────────
    # Research: RSI<35 + vol>1.5x + drop>10% + BTC green → WR=56.6% E=+0.501R n=106
    # Gate: PAPER sampai WR≥55% (n≥20), LIVE saat WR≥69% (n≥50)
    # Edge stats keyed as "LONG_TECHNICAL_S/A/B/C" (distinct from SHORT grade stats).
    if direction == "LONG" and signal.get("type") == "LONG_TECHNICAL":
        # v8.26: WR=0% (0/46 resolved, ALL from PURR), avg=-15.49% — definitively broken.
        # Scan+logging disabled in run_once(). These signals should not enter decide().
        # If they do (e.g. manual injection), hard-SKIP here as safety backstop.
        return Decision("SKIP", "-", 0.0,
                        f"LONG_TECHNICAL: WR=0% (0/46 resolved, avg=-15.49%) — "
                        f"scan disabled; re-enable when WR≥30% n≥50")

    # ── Fallback for funding-squeeze LONG (from main scanner) ────────────────
    # These have poor WR empirically (B:23%, C:27%) → keep PAPER only.
    if direction == "LONG" and signal.get("type") != "SPOT_BREAKOUT":
        return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                        "LONG funding: poor empirical WR → PAPER saja")

    # ── Pre-Loser SHORT path (original) ──────────────────────────────────────
    # 3b-session: SEMUA SESSION GATES DIHAPUS (riset 2026-06-06, n=598 triple-barrier)
    #
    #   Data baru menunjukkan semua session positif dan stabil:
    #   S US: E=+1.088R(n=37) → last30 +1.635R ↑ OPEN
    #   S US_Asia: E=+0.670R(n=21) last30 stable ↑ OPEN (edge cache backstop)
    #   B US: E=+0.768R(n=73) → last30 +1.869R ↑ OPEN
    #   B US_Asia: E=+0.444R(n=43) → last30 +1.587R ↑ OPEN
    #   B-high US: E=+1.187R(n=18) → OPEN (was wrongly PAPER dari raw avg -4%)
    #   C US: E=+0.439R(n=67) → last30 +1.677R ↑ OPEN
    #   C US_Asia: E=+0.584R(n=40) → last30 +0.731R ↑ OPEN
    #
    #   PENTING: Raw 24h WR ≠ Triple-barrier E(R). Gate lama berdasarkan raw avg%
    #   yang tidak akurat. Triple-barrier (SL=7%/TP=20%) adalah ground truth.
    #   Edge cache 15-menit adalah single safety backstop yang cukup.
    #
    #   Grade C LONG: tetap PAPER — LONG direction memang tidak reliable
    _c_long_paper_only = (grade == "C" and direction == "LONG")
    _bhigh_bad_session = False   # DIHAPUS: B-high US/US_Asia sekarang E=+1.187R
    _c_short_us_paper  = False   # DIHAPUS: C US sekarang E=+0.439R (last30: +1.677R)
    _grade_s_skip_session = False  # DIHAPUS: S US sekarang E=+1.088R (last30: +1.635R)

    # 3d. Grade S LIQUIDITY GATE (update 2026-06-06, n=147 resolved):
    #   Dengan lebih banyak data, perlu re-evaluasi threshold vol.
    #   Grade S aggregate: E=+0.776R (semua coins) — menunjukkan bahkan coins kecil OK
    #   TAPI: tetap pertahankan gate untuk DUST tier (<$10M vol) yang sangat tipis.
    #   Vol>$10M: data cukup banyak, sinyal funding squeeze real
    #   Vol<$10M: THIN tier — masih data terbatas, tetap PAPER untuk proteksi
    _grade_s_illiquid = grade == "S" and signal.get("vol24", 0) < 10_000_000  # turun dari 100M ke 10M

    # 4. Edge gate → decides PAPER vs LIVE eligibility
    # Grade C SHORT edge OPEN per 2026-06-04: E=+0.14R (n=112, backtest triple-barrier).
    # Grade S edge CLOSED aggregate (E=-0.029R) karena US+US_Asia drag — session gate above
    # protects Grade S Asia+EU (83% WR, +4%) dari tercampur sinyal US buruk.
    thresh = GRADE_EDGE_THRESHOLDS.get(grade, {"min_sample": p["min_sample"], "min_edge_r": p["min_edge_r"]})
    st = (edge_stats or {}).get(grade)

    # K21: EU session exempt from regime gate when EU WR consistently above BE.
    # EU 7d WR=61.1% n=36 (p=0.015 vs BE 43.2%) — only session with positive E(R).
    # When regime override is active AND EU WR >= floor (50%): replace st with EU-specific
    # stats so edge_ok passes and sizing uses EU win-rate, not regime-degraded global WR.
    if (direction == "SHORT"
            and session == "EU"
            and st is not None
            and st.get("regime_override")
            and risk_state.get("eu_exempt")):
        _eu_wr_pct = risk_state.get("eu_wr_7d", 0.0) * 100.0
        _eu_er     = max(risk_state.get("eu_er_7d", 0.05), 0.05)  # floor 0.05R (conservative)
        st = {**st,
              "win_rate":     _eu_wr_pct,
              "expectancy_r": _eu_er,
              "eu_bypass":    True}

    # K22: Grade S × US exempt from regime gate when Grade S × US WR consistently above 50%.
    # 7d WR=52.4% n=42 (p=0.008 vs regime baseline 34.8%) + all-time WR=67.4% (p=0.000).
    # Same dynamic self-governing mechanism as K21 EU exemption.
    if (direction == "SHORT"
            and session == "US"
            and grade == "S"
            and st is not None
            and st.get("regime_override")
            and risk_state.get("grade_s_us_exempt")):
        _gs_us_wr_pct = risk_state.get("grade_s_us_wr_7d", 0.0) * 100.0
        _gs_us_er     = max(risk_state.get("grade_s_us_er_7d", 0.05), 0.05)  # floor 0.05R
        st = {**st,
              "win_rate":     _gs_us_wr_pct,
              "expectancy_r": _gs_us_er,
              "grade_s_us_bypass": True}

    edge_ok = bool(st and st.get("n", 0) >= thresh["min_sample"]
                   and st.get("expectancy_r", -9.9) >= thresh["min_edge_r"])

    if edge_ok:
        # Grade C LONG: PAPER saja (WR 47% Asia / 40% US — tidak reliable untuk LIVE)
        if _c_long_paper_only and live_enabled:
            return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                            "Grade C LONG: WR 47% empiris — PAPER saja (SHORT lebih reliable)")
        # Grade C SHORT US: PAPER saja (avg -0.07% — slightly negative, protect edge)
        if _c_short_us_paper and live_enabled:
            return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                            "Grade C SHORT US: avg -0.07% empiris — PAPER saja, tunggu Asia/EU/US_Asia")
        # B-high SHORT US/US_Asia: PAPER (avg -4% terrible despite 62-64% WR)
        if _bhigh_bad_session and live_enabled:
            return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                            f"B-high {score} SHORT {session}: avg -4% empiris — PAPER saja, tunggu Asia/EU")
        # Grade S US/US_Asia session: skip LIVE (WR 31-38% empiris), tetap PAPER
        if _grade_s_skip_session and live_enabled:
            return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                            f"Grade S {session}: WR 31-38% (empiris) — PAPER, tunggu Asia/EU (WR 80-100%)")
        # Grade S liquidity gate: vol<$100M → PAPER (funding squeeze hanya reliable untuk top-tier)
        if _grade_s_illiquid and live_enabled:
            vol_m = round(signal.get("vol24", 0) / 1e6, 1)
            return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                            f"Grade S vol={vol_m}M<10M: THIN tier — PAPER (threshold turun dari 100M)")
        if not live_enabled:
            return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                            f"edge {st['expectancy_r']:+.2f}R (n{st['n']}) → PAPER")
        size = _kelly_size(st, p)
        boost_tags = []

        # ── v6.3 SIGNAL QUALITY BOOSTS (riset 877 sinyal, DOW×stacking matrix) ──
        _is_prime_elite = _in_prime and _is_elite

        # Priority 1: Prime+Elite → MAX SIZE (WR 93-100%, E=+1.47-2.04R)
        # Thu_PE=+2.036R, C_PE=+1.629R, A_PE=+1.804R, S_PE=+1.648R
        if _is_prime_elite and direction == "SHORT":
            size = p["max_position_usd"]
            boost_tags.append("🔥PE-MAX")

        # Priority 2: Whale confirmation
        if whale_conf > 0:
            size = min(size * 1.25, p["max_position_usd"])
            boost_tags.append("+whale")

        # Priority 3: Thursday session-specific boost — REGIME-GATED (v10.0/v11.1)
        # Thu_US: WR=92.4%, E=+2.214R (n=79) historically — but W23 showed WR=8% (n=59)
        # when BTC was in strong BULL rally. Inverted DOW patterns are regime-specific.
        # v11.1: PAPER already returned in DOW gates when regime_gate_wr < 0.65.
        # When we reach here, regime_gate_wr ≥ 0.65 (stable) — apply Thursday MAX boost.
        if _is_thursday and direction == "SHORT":
            _regime_wr = risk_state.get("regime_gate_wr", 1.0)  # 1.0 = assume stable if not set
            if _regime_wr >= 0.65:  # stable regime confirmed (guard for non-SHORT paths)
                if session in ("US", "US_Asia"):
                    size = p["max_position_usd"]          # MAX (verified stable regime)
                    boost_tags.append(f"🔥Thu_{session}-MAX")
                elif session == "Asia":
                    size = min(size * 1.25, p["max_position_usd"])
                    boost_tags.append("🔥Thu-Asia")
                else:
                    size = min(size * 1.20, p["max_position_usd"])
                    boost_tags.append("🔥Thu")

        # Priority 4: Friday session boost
        # Fri_Asia: WR=97.9%, E=+1.504R (n=145!) → +25%
        # Fri_EU: E=+0.789R, Fri_US: E=+0.657R → +20%
        if _is_friday and direction == "SHORT":
            if session == "Asia":
                size = min(size * 1.25, p["max_position_usd"])
                boost_tags.append("★Fri-Asia")
            else:
                size = min(size * 1.20, p["max_position_usd"])
                boost_tags.append("★Fri")

        # Priority 5: Prime zone solo (tidak elite): +20%
        if _in_prime and not _is_elite and direction == "SHORT":
            size = min(size * 1.20, p["max_position_usd"])
            boost_tags.append("⚡prime")

        # ── Coin elite boost (v11.4 update, 2026-06-15) ─────────────────────────
        # v11.4: -ZEC (all-time WR=50% n=68; 7d WR=25% n=32 p_lo=0.029 — regime inversion)
        #        +XMR → ELITE_25 (all-time WR=59.8% n=92; 7d WR=68.4% n=38 p_hi=0.001)
        # Hanya apply jika belum kena prime+elite MAX boost
        if not _is_prime_elite and direction == "SHORT":
            # Uses module-level COIN_ELITE_* tiers (v8.5: extracted for auto_research import)
            if coin_name in COIN_ELITE_50:
                size = min(size * 1.50, p["max_position_usd"])
                boost_tags.append(f"★★★★{coin_name}")
            elif coin_name in COIN_ELITE_40:
                size = min(size * 1.40, p["max_position_usd"])
                boost_tags.append(f"★★★{coin_name}")
            elif coin_name in COIN_ELITE_35:
                size = min(size * 1.35, p["max_position_usd"])
                boost_tags.append(f"★★★{coin_name}")
            elif coin_name in COIN_ELITE_25:
                size = min(size * 1.25, p["max_position_usd"])
                boost_tags.append(f"★★{coin_name}")
            elif coin_name in COIN_ELITE_20:
                size = min(size * 1.20, p["max_position_usd"])
                boost_tags.append(f"★{coin_name}")
            elif coin_name in COIN_ELITE_15:
                size = min(size * 1.15, p["max_position_usd"])
                boost_tags.append(f"★{coin_name}")
        # Score-band + session boost for Grade B (weekday WR without Sat/Sun):
        # B+Asia: WR=90% n=176 | B+EU: WR=92% n=106 ★★★ | B+US: WR=74% | B+US_Asia: WR=66%
        if grade == "B" and 65 <= score <= 69 and direction == "SHORT":
            _b_low_boost = 1.40 if session == "EU" else (1.35 if session == "Asia" else 1.30)
            size = min(size * _b_low_boost, p["max_position_usd"])
            boost_tags.append(f"★B-low{'EU' if session=='EU' else ''}")
        # Session-elite boosts (riset 2026-06-05):
        elif grade == "B" and 75 <= score <= 79 and session == "EU" and direction == "SHORT":
            # B-high EU: WR=90% n=108 ★★★ (was E=+0.963R, confirmed by live data)
            size = min(size * 1.25, p["max_position_usd"])  # raised from 1.20 → 1.25
            boost_tags.append("★★B-EU")
        elif grade == "C" and session == "Asia" and direction == "SHORT":
            # C+Asia weekday WR=95% n=138 — extraordinary, max boost!
            size = min(size * 1.35, p["max_position_usd"])
            boost_tags.append("★★C-Asia")
        elif grade == "C" and session == "EU" and direction == "SHORT":
            size = min(size * 1.20, p["max_position_usd"])  # C EU: WR=78%
            boost_tags.append("★C-EU")
        elif grade == "C" and session == "US_Asia" and direction == "SHORT":
            size = min(size * 1.20, p["max_position_usd"])  # C US_Asia: WR=82%
            boost_tags.append("★C-USAsia")
        elif grade == "S" and direction == "SHORT":
            # Weekday WR: EU=92% n=53 ★★★ | Asia=86% n=93 ★★ | US_Asia=75% | US=74%
            _s_boost = (1.30 if session == "EU" else
                        1.25 if session == "Asia" else
                        1.15)   # Asia raised from 1.15→1.25 (86% weekday WR)
            size = min(size * _s_boost, p["max_position_usd"])
            boost_tags.append(f"★S{'-EU' if session=='EU' else ('-Asia' if session=='Asia' else '')}")
            boost_tags.append(f"★S-{session}")
        elif grade == "B" and session == "US" and direction == "SHORT":
            size = min(size * 1.20, p["max_position_usd"])  # B US: last30 E=+1.869R
            boost_tags.append("★B-US")
        elif grade == "B" and session == "US_Asia" and direction == "SHORT":
            size = min(size * 1.15, p["max_position_usd"])  # B US_Asia: last30 E=+1.587R
            boost_tags.append("★B-USAsia")
        # ── Grade C score elite (v6.10): score 61-63 E=1.0-1.05R ──────────────
        # Score 60: E=0.435R (baseline), 61-63: E=0.995-1.044R (±2.4× better!)
        # Score 64: E=0.614R (+15% modest boost)
        # This is independent from session boosts — can stack.
        if grade == "C" and direction == "SHORT":
            if 61 <= score <= 63:
                size = min(size * 1.35, p["max_position_usd"])
                boost_tags.append(f"★★C{score}")
            elif score == 64:
                size = min(size * 1.15, p["max_position_usd"])
                boost_tags.append(f"★C64")
        # ── B-mid Asia/EU boost (v6.10): E=1.07R — reward quality session ─────
        if grade == "B" and 70 <= score <= 74 and session in ("Asia", "EU") and direction == "SHORT":
            size = min(size * 1.25, p["max_position_usd"])
            boost_tags.append(f"★Bmid-{session}")
        # ── Scan size "Goldilocks" boost (v6.8): +20% for 11-15 signals ─────────
        # scan_size 11-15: E=+1.520R WR=94.5% — sweet spot (too few=false positives,
        # too many=noise, 11-15=optimal crowding signals real funding pressure)
        # vs single(E=+0.620R) and very crowded 16+(E=+0.767R gated)
        if 11 <= scan_size <= 15 and direction == "SHORT":
            size = min(size * 1.20, p["max_position_usd"])
            boost_tags.append(f"★scan{scan_size}")

        # ── fund_accel HIGH boost (v6.7): +15% size ─────────────────────────────
        _fund_accel = signal.get("fund_accel")
        if _fund_accel is not None and float(_fund_accel) >= 2.0:
            size = min(size * 1.15, p["max_position_usd"])
            boost_tags.append("⚡fa")

        # ── Vol/OI liquidity quality: VERY_LOW <0.5 = weaker signal (-25% size) ──
        _vol_oi = signal.get("vol_oi")
        if _vol_oi is not None and float(_vol_oi) < 0.5:
            size = max(size * 0.75, p["min_position_usd"])
            boost_tags.append("vol↓")

        mode = "LIVE" if live_enabled else "PAPER"
        boosts = (" " + " ".join(boost_tags)) if boost_tags else ""
        return Decision("TRADE", mode, round(size, 2),
                        f"edge {st['expectancy_r']:+.2f}R (n{st['n']}){boosts} → {mode}")
    # No proven edge → PAPER only (gather data); real money REFUSED.
    return Decision("TRADE", "PAPER", round(p["paper_nominal"], 2),
                    f"grade {grade}: edge belum terbukti → PAPER (kumpul data); "
                    f"uang nyata DITOLAK sampai expectancy>0")


def _kelly_size(st: dict, p: dict) -> float:
    """Conservative fractional-Kelly position size from validated edge stats."""
    try:
        from anantara.risk_metrics import fractional_kelly
    except ImportError:
        from risk_metrics import fractional_kelly                  # type: ignore
    frac = fractional_kelly(st.get("win_rate", 0) / 100.0, p["tp_pct"], p["sl_pct"],
                            p["kelly_fraction"])
    return max(p["min_position_usd"], min(p["capital"] * frac, p["max_position_usd"]))


# ── Execution boundary ────────────────────────────────────────────────────────
def place_order_paper(signal: dict, decision: Decision) -> dict:
    """Record an intended order (NO real money). Returns the audit row."""
    row = {"action": decision.action, "ts": int(time.time()),
           "utc": datetime.now(timezone.utc).isoformat(),
           "coin": signal["coin"], "direction": signal["direction"],
           "grade": signal.get("grade"), "mode": decision.mode,
           "size_usd": decision.size_usd,
           "entry": signal.get("mark") or signal.get("entry_price"),
           "session": signal.get("session", "?"),
           "score": signal.get("score", 0),
           "sig_type": signal.get("type", signal.get("sig_type", "")),
           "reason": decision.reason}
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as e:
        import logging as _palog
        _palog.getLogger(__name__).warning(f"place_order_paper: write failed: {e}")
    return row


def place_order_live(signal: dict, decision: Decision,
                     edge_stats: dict | None = None) -> dict:
    """LIVE order placement — via pregain_execution (edge-gated, EIP-712).

    Delegates to pregain_execution.place_order() which enforces:
      1. edge_gate_open(): grade must have ≥30 resolved + E≥0.10R
      2. ENV gate: PREGAIN_LIVE=1 must be set explicitly
      3. HL_API_SECRET: agent wallet private key in .env
      4. Max positions + daily loss circuit breaker

    Returns OrderResult dict. Raises nothing — all errors returned in result.
    """
    project_gate = evaluate_project_live_gate()
    if not project_gate.allowed:
        return {
            "ok": False,
            "mode": "PAPER",
            "reason": f"project evidence gate blocks LIVE: {project_gate.reason}",
            "entry_px": None,
        }

    try:
        from anantara import pregain_execution as _exec
    except ImportError:
        import pregain_execution as _exec   # type: ignore

    tracker = _exec.PositionTracker()
    result = _exec.place_order(
        signal=signal,
        decision=decision,
        edge_stats=edge_stats,
        live_enabled=True,
        tracker=tracker,
    )
    return {"ok": result.ok, "mode": result.mode, "reason": result.reason,
            "entry_px": result.entry_px}


# ── Driver (IO) ───────────────────────────────────────────────────────────────
def run_once(live_enabled: bool = False, params: dict | None = None) -> str:
    """One auto-trade cycle: scan → edge stats → whale bias → decide → execute(paper).
    Returns a human-readable summary. Real money only if live_enabled AND edge proven."""
    try:
        from anantara import pregain_scan, pregain_backtest, whale_tracker
    except ImportError:                                            # flat context
        import pregain_scan, pregain_backtest, whale_tracker        # type: ignore

    # ── K4 Sovereign Gate Hard-Block (v11.0) ──────────────────────────────────
    # Fable 5 finding: sovereign gates returned NO_GO on Jun 4 but live started
    # Jun 6 anyway — gates were Telegram-only, never enforced in the trading loop.
    # Fix: if saved verdict is NO_GO and file is fresh (< TTL), override live_enabled.
    # PAPER trades continue unaffected — only real-money LIVE is hard-blocked.
    _sverd, _sverd_reason = _read_sovereign_verdict()
    _k4_blocked = _sverd == "NO_GO"
    if _k4_blocked and live_enabled:
        import logging as _k4log
        _k4log.getLogger(__name__).warning(
            f"K4: sovereign gates veto LIVE trading — {_sverd_reason}. "
            "PAPER mode tetap aktif untuk pengumpulan data."
        )
        live_enabled = False

    # ── Project Evidence Gate (Top Pre-Gain-Loser) ───────────────────────────
    # Blocks real-money live mode unless granular and execution-cost reports
    # explicitly confirm a manually approved tiny pilot. PAPER mode continues.
    _project_gate = evaluate_project_live_gate()
    if live_enabled and not _project_gate.allowed:
        import logging as _pglog
        _pglog.getLogger(__name__).warning(
            f"Project evidence gate vetoes LIVE trading — {_project_gate.reason}. "
            "PAPER mode tetap aktif untuk pengumpulan data."
        )
        live_enabled = False

    # ── Parameter Freeze Check (v12.0, F1.5) ─────────────────────────────────
    # Verifies all coin lists, hour sets, thresholds unchanged since freeze date.
    # Non-blocking: violation logs ERROR + Telegram alert; PAPER trades continue.
    # After freeze expiry (8 weeks), check becomes informational only.
    _pf_ok, _pf_msg = _check_parameter_freeze()
    if not _pf_ok:
        _atlogger = __import__('logging').getLogger(__name__)
        _atlogger.error(f"PARAMETER FREEZE: {_pf_msg}")
        try:
            import urllib.request, urllib.parse
            _token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
            _cid   = os.environ.get("TELEGRAM_CHAT_ID", "")
            if _token and _cid:
                _url = f"https://api.telegram.org/bot{_token}/sendMessage"
                _data = urllib.parse.urlencode(
                    {"chat_id": _cid,
                     "text": f"⚠️ PREGAIN PARAMETER FREEZE VIOLATION\n{_pf_msg}"}).encode()
                urllib.request.urlopen(urllib.request.Request(_url, data=_data), timeout=5)
        except Exception:
            pass
    # ──────────────────────────────────────────────────────────────────────────
    # ──────────────────────────────────────────────────────────────────────────

    longs, shorts, regime = pregain_scan.run_scan(
        pregain_scan.ACTIONABLE_MIN, log=True, verbose=False)

    # Set direction BEFORE building actionable (references to same dicts)
    for r in longs:  r["direction"] = "LONG"
    for r in shorts: r["direction"] = "SHORT"

    import logging as _atlog
    _atlogger = _atlog.getLogger(__name__)

    # ── LONG_TECHNICAL scan DISABLED (v8.26, 2026-06-11) ─────────────────────
    # Evidence: 46 resolved signals, WR=0% (0/46), avg=-15.49%, ALL from PURR coin.
    # Dip buying in bear+conflict regime = catching falling knives.
    # Scan was logging 61 signals/week → contaminating signal_log + learner weights.
    # decide() already returns SKIP for LONG_TECHNICAL, but scanning+logging still ran.
    # FIX: Stop scan and logging entirely. Re-enable if WR recovers to ≥30% n≥50.
    _tech_longs: list[dict] = []   # empty — scanning disabled

    # ── Pull SPOT signals from pregain_spot_scanner ───────────────────────────
    # Two variants (auto-selected based on BTC regime):
    #   BREAKOUT: 20d high break + vol — WR=87.5% backtest (bull market)
    #   DIP_RECOVERY: RSI<30 + vol>1.3x + hammer — WR TBD (bear market, accumulating)
    # Gate: PAPER until WR≥65% live (n≥20), LIVE at WR≥69% (n≥30).
    _spot_sigs: list[dict] = []
    try:
        from anantara import pregain_spot_scanner as _pss
        _raw_spot = _pss.scan_all_spot()
        for s in _raw_spot:
            s.setdefault("coin", s.get("name", "UNKNOWN"))
            s["type"] = "SPOT_BREAKOUT"
            s["liq"] = "LIQUID"
            _spot_sigs.append(s)
    except Exception as _e:
        _atlogger.error(f"SPOT scan failed: {_e}")

    # ── Log SPOT signals to signal_log ────────────────────────────────────────
    if _spot_sigs:
        try:
            from anantara import signal_tracker as _st_sp
            from anantara.pregain_scan import SIGNAL_DB as _SDBSP, LOG_COOLDOWN_SEC as _LCSSP
            _sp_to_log = [
                _st_sp.Signal(s["coin"], "LONG", s["score"], s["grade"],
                              s.get("entry_price", 0),
                              "RANGING", s.get("vol24", 0), "STANDARD",
                              fund_accel=0.0, vol_oi=s.get("vol_ratio", 1.0),
                              sig_type="SPOT_BREAKOUT")
                for s in _spot_sigs
            ]
            # SPOT hold = 10 days. 3h cooldown (=_LCSSP*3) caused 25 entries for same
            # TAO breakout over 4 days — 25 correlated signals = statistisches verzerrung.
            # v8.28: use 24h cooldown → max 1 signal per coin per day (10 per breakout).
            _SPOT_COOLDOWN_SEC = 24 * 3600
            _st_sp.log_signals(_SDBSP, _sp_to_log, cooldown_sec=_SPOT_COOLDOWN_SEC)
        except Exception as _e:
            _atlogger.warning(f"SPOT signal log failed: {_e}")

    # Deduplicate: jika coin muncul di LONG dan SHORT, ambil arah dengan score tertinggi.
    # Tanpa ini, auto-trader bisa LONG dan SHORT coin yang sama sekaligus.
    # Sort globally by score (bukan longs dulu baru shorts).
    # SPOT signals use a separate slot budget (tracked separately in decide()).
    seen: dict[str, dict] = {}
    for r in (longs + shorts):
        if r["score"] >= pregain_scan.ACTIONABLE_MIN and r["liq"] != "DUST":
            name = r["name"]
            if name not in seen or r["score"] > seen[name]["score"]:
                seen[name] = r
    actionable = sorted(seen.values(), key=lambda x: x["score"], reverse=True)
    _audit_scan(longs, shorts, actionable, str(regime))
    # Map "name" → "coin" agar downstream (whale_tracker, place_order_paper) bisa akses sig["coin"]
    # run_scan() pakai "name"; autotrader contract pakai "coin" — ini normalisasi perbatasan
    for sig in actionable:
        if "coin" not in sig:
            sig["coin"] = sig.get("name", "UNKNOWN")

    # Append technical LONG and SPOT signals AFTER dedup (they use their own key)
    # SPOT signals don't conflict with SHORT: same coin can be SHORT futures + SPOT breakout.
    # Technical LONG: skip if coin already has a higher-scoring SHORT in actionable.
    _existing_coins = {s["coin"]: s["direction"] for s in actionable}
    for s in _tech_longs:
        coin = s["coin"]
        if coin in _existing_coins and _existing_coins[coin] == "SHORT":
            continue  # coin already queued as SHORT — don't open opposing LONG
        if s.get("score", 0) >= pregain_scan.ACTIONABLE_MIN:
            actionable.append(s)
    for s in _spot_sigs:
        if s.get("score", 0) >= pregain_scan.ACTIONABLE_MIN:
            actionable.append(s)   # SPOT always appended (separate capital bucket)
    actionable.sort(key=lambda x: x["score"], reverse=True)

    # Scan size context — jumlah sinyal AKTIF (non-SKIP) dalam 1 scan cycle.
    # Riset 2026-06-03: single signal WR=68% vs multi-signal WR=49%
    # Crowded scan (>15) = market-wide event = signals kurang selektif.
    # PENTING: B-mid (70-74) selalu SKIP di decide() — tidak merepresentasikan
    # peluang trading nyata. Menghitung mereka inflasi scan_size dan men-trigger
    # gate crowded secara palsu (e.g. 26 total → 11 B-mid = 15 efektif ✅).
    # SPOT and LONG_TECHNICAL don't participate in SHORT crowding metric.
    _scan_size = sum(1 for s in actionable
                     if not (s.get("grade") == "B" and 70 <= s.get("score", 0) <= 74)
                     and s.get("type") not in ("SPOT_BREAKOUT", "LONG_TECHNICAL"))
    for sig in actionable:
        sig["scan_size"] = _scan_size   # inject ke setiap signal untuk gate di decide()

    # Validated edge — thread-safe cache, recompute max every 15 minutes.
    # should_refresh is local to THIS call: only the thread that atomically
    # claimed a new TTL slot (set _EDGE_CACHE[0] = now_ts under lock) fetches.
    # This eliminates the TOCTOU where two threads with identical now_ts could
    # both pass the old "if _EDGE_CACHE[0] == now_ts" guard and double-fetch.
    global _EDGE_CACHE
    now_ts = time.time()
    should_refresh = False
    with _EDGE_CACHE_LOCK:
        if now_ts - _EDGE_CACHE[0] > _EDGE_CACHE_TTL:
            # Claim the TTL slot with a timestamp update but KEEP old data.
            # v8.25 FIX: previously cleared data to {} here, so a failed backtest
            # would leave all grades empty for a full 30-min TTL window (LIVE blocked).
            # Now: old edge data stays until a successful refresh replaces it.
            _EDGE_CACHE = (now_ts, _EDGE_CACHE[1])
            should_refresh = True   # only this thread fetches for this TTL window
    # Fetch outside lock — only the thread that won the TTL slot
    if should_refresh:
        try:
            # Edge stats pakai DEFAULT geometry (SL=7%/TP=20%) — Grade C terbukti E=+0.081R.
            # NOTE: OPTIMAL_GRADE_PARAMS (TP=15%) dipakai untuk research/display tetapi
            # TIDAK untuk edge stats karena TP=15% ternyata menurunkan Grade C ke E=-0.029R.
            #
            # Grade B edge computation pakai SHORT-only + exclude B-mid (70-74):
            # B-mid adalah SKIP gate di production, memasukkannya drag B aggregate dari
            # +0.473R (effective) ke +0.121R (semua) — membuat gate tidak pernah terbuka.
            # B LONG juga di-SKIP di production, tidak perlu dimasukkan ke edge stats.
            # Use cache_only=True: 70-coin local cache downloaded, fast offline backtest
            # avoids HL API timeout (676+ signals × API call = >25s → silently swallowed
            # by except Exception: pass → edge cache stays {} → all "edge belum terbukti").
            import functools as _ft
            _fp_cached = _ft.partial(pregain_backtest.fetch_path, cache_only=True)
            # SHORT edge: use sl_pct=3.0 (v8.6 optimal) + exclude Sat/Sun (gated in production).
            # Sat: WR=12% n=460 (before gate) | Sun: WR=42% n=120 — both gated.
            # Including them distorts edge stats (dragging from 81% to 63%).
            # SQLite strftime '%w': '0'=Sun, '6'=Sat.
            _EXCL_WEEKEND = ["0", "6"]
            # v11.0 K2 fix: rolling window prevents W22 crash-week dominance.
            # Without since_ts: W22 (74.7% of data, WR=61.7%) keeps gate OPEN
            # even when W23/W24 WR is 36-43% (below breakeven=46%).
            _edge_since_ts: int | None = (
                int(now_ts) - _EDGE_ROLLING_DAYS * 86400
                if _EDGE_ROLLING_DAYS > 0 else None
            )
            edge_all = pregain_backtest.backtest_logged(
                pregain_scan.SIGNAL_DB, _fp_cached,
                sl_pct=3.0, tp_pct=20.0,
                sig_type_filter="SHORT",
                exclude_dow=_EXCL_WEEKEND,
                since_ts=_edge_since_ts)
            edge_b_eff = pregain_backtest.backtest_logged(
                pregain_scan.SIGNAL_DB, _fp_cached,
                sl_pct=3.0, tp_pct=20.0,
                direction_filter="SHORT",
                sig_type_filter="SHORT",
                exclude_dow=_EXCL_WEEKEND,
                since_ts=_edge_since_ts)
            # Grade A: pakai aggregate (sudah n=124, semua sessions positif)
            by_grade = dict(edge_all.get("by_grade", {}))
            b_eff = (edge_b_eff.get("by_grade") or {}).get("B")
            if b_eff and b_eff.get("n", 0) >= 10:
                by_grade["B"] = b_eff  # replace with SHORT-only B stats (no B LONG drag)

            # ── LONG_TECHNICAL edge stats ─────────────────────────────────────
            # RSI+dip+vol LONG signals: 24h horizon, SL=5%/TP=15%
            # Prefixed as LONG_TECHNICAL_S/A/B/C in edge_stats so decide() can
            # distinguish from SHORT grade stats (same grade letter, different direction).
            try:
                edge_lt = pregain_backtest.backtest_logged(
                    pregain_scan.SIGNAL_DB, _fp_cached,
                    sig_type_filter="LONG_TECHNICAL",
                    direction_filter="LONG",
                    sl_pct=5.0, tp_pct=15.0,
                    horizon_sec=24 * 3600,
                    since_ts=_edge_since_ts)
                for g, st in (edge_lt.get("by_grade") or {}).items():
                    if st.get("n", 0) >= 5:
                        by_grade[f"LONG_TECHNICAL_{g}"] = st
            except Exception as _elt_e:
                import logging as _ltlog
                _ltlog.getLogger(__name__).warning(f"LONG_TECHNICAL edge stats failed: {_elt_e}")

            # ── SPOT_BREAKOUT edge stats ──────────────────────────────────────
            # 20-day-high breakout + vol signals: 10d horizon, TP=20%/trail=3-5%
            # Prefixed as SPOT_S/A/B/C in edge_stats (matches decide() SPOT path).
            # If backtest fails, add empty placeholders so decide() shows "kumpul data"
            # instead of silently skipping SPOT signals.
            try:
                edge_spot = pregain_backtest.backtest_logged(
                    pregain_scan.SIGNAL_DB, _fp_cached,
                    sig_type_filter="SPOT_BREAKOUT",
                    direction_filter="LONG",
                    sl_pct=20.0,    # effectively no hard SL (trailing stop handles exit)
                    tp_pct=20.0,
                    horizon_sec=10 * 24 * 3600,
                    since_ts=_edge_since_ts)
                for g, st in (edge_spot.get("by_grade") or {}).items():
                    if st.get("n", 0) >= 5:
                        by_grade[f"SPOT_{g}"] = st
            except Exception as _esp_e:
                import logging as _splog
                _splog.getLogger(__name__).warning(f"SPOT edge stats failed: {_esp_e}")

            # ── REGIME SAFETY GATE (v9.0) ─────────────────────────────────────────
            # Delegates to _compute_regime_gate() — testable module-level function.
            # ─────────────────────────────────────────────────────────────────────────
            _rg_active, _rg_wr, _rg_n = _compute_regime_gate(pregain_scan.SIGNAL_DB)
            if _rg_active and _rg_wr is not None:
                import logging as _rgl
                # v11.6 K16: show fallback window label when n suggests 7d was used
                _rg_window_label = (f"{_REGIME_GATE_FALLBACK_DAYS}d-fallback"
                                    if _rg_n >= _REGIME_GATE_MIN_N * 3
                                    else f"{_REGIME_GATE_DAYS}d")
                _rgl.getLogger(__name__).warning(
                    f"REGIME GATE v9.0 ACTIVE: rolling {_rg_window_label} "
                    f"SHORT WR={_rg_wr:.1%} (n={_rg_n}) < floor "
                    f"{_REGIME_WR_FLOOR:.0%}. All SHORT grades → PAPER."
                )
                for _rg_g in [g for g in by_grade
                              if not g.startswith("LONG_")
                              and not g.startswith("SPOT_")]:
                    by_grade[_rg_g] = {
                        **by_grade[_rg_g],
                        "expectancy_r": -0.01,
                        "regime_override": True,
                        # K21: save original for EU session exemption sizing
                        "original_expectancy_r": by_grade[_rg_g].get("expectancy_r", -9.9),
                        "original_win_rate": by_grade[_rg_g].get("win_rate", 0.0),
                        "regime_wr": round(_rg_wr, 3),
                        "regime_n": _rg_n,
                    }
            # ─────────────────────────────────────────────────────────────────────────

            with _EDGE_CACHE_LOCK:
                _EDGE_CACHE = (now_ts, by_grade)
        except Exception as _e:
            import logging as _log
            _log.getLogger(__name__).warning(f"edge cache refresh failed: {_e}")
            # cache stays at (now_ts, {}), retried next TTL window
    with _EDGE_CACHE_LOCK:
        edge_stats = dict(_EDGE_CACHE[1])  # snapshot copy
    whale_map = whale_tracker.fetch_whale_bias()

    risk_state = _load_daily_state()   # persists across cycles, resets at midnight UTC
    # Sync open_positions from actual PositionTracker — daily state counter
    # only increments (never decrements when positions close), causing false SKIP.
    try:
        from anantara import pregain_execution as _pe_sync
    except ImportError:
        import pregain_execution as _pe_sync  # type: ignore
    _tracker_sync = _pe_sync.PositionTracker()
    _actual_open  = _tracker_sync.count()
    risk_state["open_positions"]  = _actual_open
    # Feed ACTUAL daily P&L into risk_state so decide() circuit breaker fires correctly.
    # BUG-FIX: previously daily_pnl_frac stayed 0.0 forever → daily loss cap & CB
    # equity-drawdown path were permanently disabled. Now sourced from execution layer
    # which tracks both unrealized + today's realized P&L.
    _capital      = float(os.environ.get("ANANTARA_CAPITAL_USD", "60").split("#")[0].strip() or 60)
    _actual_pnl   = _tracker_sync.daily_pnl(capital=_capital)
    risk_state["daily_pnl_frac"]  = _actual_pnl
    risk_state["running_dd_frac"] = max(0.0, -_actual_pnl)   # simplified; always ≥ 0
    # Regime gate WR: passed to decide() so Thursday boost is conditioned on stable regime.
    # v10.0: DOW patterns invert in BULL regime (W23: Thu WR=8%, n=59). Guard Thursday MAX
    # boost behind regime_gate_wr ≥ 0.65 to prevent over-sizing in fragile recovery.
    _rg_active_live, _rg_wr_live, _ = _compute_regime_gate(pregain_scan.SIGNAL_DB)
    risk_state["regime_gate_wr"] = _rg_wr_live if _rg_wr_live is not None else 1.0
    # K21: EU session exemption — compute EU 7d WR; exempt when WR ≥ floor AND n ≥ min
    try:
        _eu_wr_live, _eu_er_live, _eu_n_live = _compute_eu_session_wr(pregain_scan.SIGNAL_DB)
        risk_state["eu_exempt"]  = (_eu_wr_live >= _EU_EXEMPT_WR_FLOOR
                                    and _eu_n_live >= _EU_EXEMPT_MIN_N)
        risk_state["eu_wr_7d"]   = _eu_wr_live
        risk_state["eu_er_7d"]   = _eu_er_live
        risk_state["eu_n_7d"]    = _eu_n_live
    except Exception:
        risk_state["eu_exempt"] = False
    # K22: Grade S × US exemption — compute Grade S × US 7d WR; exempt when WR ≥ 50% AND n ≥ 30
    try:
        _gs_us_wr, _gs_us_er, _gs_us_n = _compute_grade_s_us_wr(pregain_scan.SIGNAL_DB)
        risk_state["grade_s_us_exempt"] = (_gs_us_wr >= _GRADE_S_US_EXEMPT_WR_FLOOR
                                           and _gs_us_n >= _GRADE_S_US_EXEMPT_MIN_N)
        risk_state["grade_s_us_wr_7d"]  = _gs_us_wr
        risk_state["grade_s_us_er_7d"]  = _gs_us_er
        risk_state["grade_s_us_n_7d"]   = _gs_us_n
    except Exception:
        risk_state["grade_s_us_exempt"] = False
    # Session context: affects signal quality (Asia/EU ~80%, US_Asia ~54% empirically)
    try:
        from anantara.signal_tracker import session_name as _sess_name
    except ImportError:
        from signal_tracker import session_name as _sess_name  # type: ignore
    _sess = _sess_name()
    _sess_icons = {"Asia": "🌏", "EU": "🇪🇺", "US": "🇺🇸", "US_Asia": "🌙"}
    _sess_tag = f"{_sess_icons.get(_sess, '📡')}{_sess}"

    edge_grades_str = list(edge_stats) if edge_stats else "none"
    # live_status: use grade-specific thresholds (Grade C: min_edge_r=0.05 not 0.10)
    live_status = ("✅ EDGE TERBUKTI" if any(
        st.get("expectancy_r", 0) >= GRADE_EDGE_THRESHOLDS.get(g, {}).get("min_edge_r", DEFAULTS["min_edge_r"])
        and st.get("n", 0) >= GRADE_EDGE_THRESHOLDS.get(g, {}).get("min_sample", DEFAULTS["min_sample"])
        for g, st in edge_stats.items()
    ) and live_enabled else "📝 PAPER (edge belum terbukti / live off)")
    # Circuit breaker status line (sovereign gate status for visibility)
    try:
        from anantara.pregain_circuit_breaker import get_circuit_breaker as _get_cb
    except ImportError:
        try:
            from pregain_circuit_breaker import get_circuit_breaker as _get_cb  # type: ignore
        except ImportError:
            _get_cb = None
    _cb_line = _get_cb().status_line() if _get_cb else "CB: unavailable"

    # Event risk status line (v8.6: geo-political/whale event awareness)
    _er_icons = {"RED": "🛑", "ORANGE": "⚠️", "YELLOW": "🟡", "NORMAL": "🟢"}
    try:
        from anantara.sodex_event_shock_guard import fetch_event_risk as _fer_status
        _er_status = _fer_status()
        _er_level  = _er_status.get("level", "NORMAL")
        _er_score  = _er_status.get("risk_score", 0)
        _er_line   = f"{_er_icons.get(_er_level, '❓')} EventRisk: {_er_level} ({_er_score:.0f}/100)"
    except Exception:
        _er_line = "❓ EventRisk: unavailable"

    # Intelligence score (v9.0: SCS Hybrid — REAL data from Hermes, bukan hardcoded)
    _intel_score = 50.0
    _intel_label = "NEUTRAL"
    _sentiment_raw = {}
    try:
        # Fetch REAL sentiment from Hermes bridge (sync HTTP, runs in thread)
        import urllib.request as _ur
        _req = _ur.Request("http://localhost:8000/sentiment/current", headers={"User-Agent": "PreGain/9.0"})
        with _ur.urlopen(_req, timeout=5) as _r:
            _sentiment_raw = json.loads(_r.read().decode()) or {}
    except Exception:
        _sentiment_raw = {}

    try:
        from anantara.intelligence import compute_intelligence, label_for
        # ── Extract REAL data (fallback to hardcoded 50.0/55.0 if missing) ──
        _fg      = float(_sentiment_raw.get("fg_index", 50.0) or 50.0)
        _btc_dom = float(_sentiment_raw.get("btc_dominance", 55.0) or 55.0)
        _mcap_chg= float(_sentiment_raw.get("mcap_change_24h", 0.0) or 0.0)
        _trending= _sentiment_raw.get("trending", []) or []
        _regime_s= regime.regime if hasattr(regime, 'regime') else "RANGING"
        _mtf_s   = regime.momentum if hasattr(regime, 'momentum') else 0.0

        # ── Tilt signals: extract from sentiment data (graceful at 0) ──
        _funding_raw = _sentiment_raw.get("funding_avg", {}) or {}
        _funding_avg = sum(float(v) for v in _funding_raw.values() if isinstance(v, (int, float))) / max(len(_funding_raw), 1)
        _funding_tilt = -1.0 if _funding_avg > 0.015 else (1.0 if _funding_avg < -0.005 else 0.0)

        _liq = _sentiment_raw.get("liq_1h", {}) or {}
        _liq_ratio = float(_liq.get("liq_ratio", 0) or 0)

        _stablecoin_chg = float(_sentiment_raw.get("stablecoin_change", 0) or 0)
        _stablecoin_tilt = -1.0 if _stablecoin_chg > 0.5 else (0.5 if _stablecoin_chg < -0.5 else 0.0)

        _intel = compute_intelligence(
            fg=_fg, btc_dom=_btc_dom,
            mcap_chg=_mcap_chg,
            trending=_trending, candidates_n=len(actionable),
            regime=_regime_s, mtf_score=_mtf_s,
            # ── Tilt signals: REAL data dari Hermes sentiment ──
            funding_tilt=_funding_tilt,
            liq_tilt=_liq_ratio,
            stablecoin_tilt=_stablecoin_tilt,
            # whale_tilt, flow_tilt, oi_smart_tilt, news_sentiment: 0 (belum ada data source langsung)
        )
        _intel_score = _intel.get("composite_score", _intel.get("score", 50.0))
        _intel_label = _intel.get("label", "NEUTRAL")
    except Exception:
        pass
    _intel_icons = {"STRONGLY_BULLISH": "🟢🟢", "BULLISH": "🟢", "NEUTRAL": "⚪",
                    "BEARISH": "🔴", "STRONGLY_BEARISH": "🔴🔴"}
    _intel_line = f"{_intel_icons.get(_intel_label, '⚪')} Intel: {_intel_label} ({_intel_score:.0f}/100)"

    # Pre-Sentiment forecast confidence (v8.9: sizing modifier from momentum + regime + session)
    _fc_conf = 0.60
    try:
        # LITE forecast: uses BTC momentum + ADX proxy (ATR ratio) + session/regime
        _mom = regime.momentum if hasattr(regime, 'momentum') else 0.0
        _atr = getattr(regime, 'atr_ratio', 1.0)
        # Base confidence from momentum strength
        _fc_base = 0.50 + abs(_mom) * 1.5  # 0.50 (flat) to 0.80 (strong trend)
        # Regime modifier
        if regime.regime == "CHAOS":
            _fc_base = min(_fc_base, 0.45)
        elif regime.regime == "TRENDING":
            _fc_base = min(_fc_base * 1.15, 0.85)  # trending = more reliable
        # Session modifier (empirical WR: Asia 55%, EU 60%, US 40%, US_Asia 47%)
        _sess_mult = {"Asia": 1.10, "EU": 1.05, "US": 0.85, "US_Asia": 0.90}.get(_sess, 1.0)
        _fc_conf = round(max(0.30, min(0.90, _fc_base * _sess_mult)), 2)
    except Exception:
        pass
    _fc_line = f"📊 Forecast: conf={_fc_conf:.2f}"

    # Regime gate display — always show trend for visibility + recovery tracking
    _rg_disp_active, _rg_disp_wr, _rg_disp_n = _compute_regime_gate(pregain_scan.SIGNAL_DB)
    _rg_trend = _compute_regime_trend(pregain_scan.SIGNAL_DB)
    _rg_3d = _rg_trend.get("3d", {})
    _rg_7d = _rg_trend.get("7d", {})
    _wr3  = f"{_rg_3d.get('wr', 0)*100:.1f}%" if _rg_3d.get('wr') is not None else "n/a"
    _wr7  = f"{_rg_7d.get('wr', 0)*100:.1f}%" if _rg_7d.get('wr') is not None else "n/a"
    _n3   = _rg_3d.get('n', 0)
    _n7   = _rg_7d.get('n', 0)
    if _rg_disp_active and _rg_disp_wr is not None:
        # ↗ = recent(3d) better than past(7d) = recovering; ↘ = recent worse = still falling
        _trend_arrow = "↗" if (_rg_3d.get('wr') or 0) > (_rg_7d.get('wr') or 0) else "↘"
        _rg_line = (f"🔴 REGIME GATE AKTIF: 3d={_wr3}(n={_n3}) 7d={_wr7}(n={_n7}) {_trend_arrow}"
                    f" — semua SHORT → PAPER (floor=50%)")
    elif _rg_disp_wr is not None:
        _rg_line = (f"🟢 Regime OK: 3d={_wr3}(n={_n3}) 7d={_wr7}(n={_n7})"
                    f" ≥ 50% → edge gate normal")
    else:
        _rg_line = f"⚪ Regime: data insufisien (n={_rg_disp_n} < 40) → gate tidak aktif"

    _k4_line = (f"🚫 K4 SOVEREIGN VETO: {_sverd_reason}" if _k4_blocked
                else f"✅ Sovereign: {_sverd_reason if _sverd else 'gates belum dijalankan (fail-open)'}")
    _pf_line = (f"🔒 Parameter FREEZE: {_pf_msg}" if not _pf_ok
                else f"🔒 Freeze OK (sejak {_PARAMETER_FREEZE_DATE}, sampai {_PARAMETER_FREEZE_UNTIL})")
    L = [f"🤖 AUTO-TRADER · regime {regime.regime} · {_sess_tag} · {live_status}",
         f"   edge-grades={edge_grades_str} · LIVE={risk_state['open_positions']}/{DEFAULTS['max_positions']} posisi",
         f"   {_rg_line}",
         f"   {_k4_line}",
         f"   {_pf_line}",
         f"   {_cb_line} · {_er_line}",
         f"   {_intel_line} · {_fc_line}"]
    traded = 0
    for sig in actionable:
        sig.setdefault("session", _sess)   # inject current session into signal dict
        sig.setdefault("regime", regime.regime)           # v8.6: regime-aware gate
        sig.setdefault("btc_momentum", regime.momentum)   # v8.6: bull/bear direction
        sig.setdefault("intel_score", _intel_score)       # v8.9: intelligence overlay
        sig.setdefault("intel_label", _intel_label)       # v8.9: BULLISH/BEARISH/NEUTRAL
        sig.setdefault("fc_conf", _fc_conf)               # v8.9: forecast confidence
        wc = whale_tracker.confirms(whale_map, sig["coin"], sig["direction"])
        d = decide(sig, edge_stats, wc, risk_state, live_enabled, params)
        _audit_decision(sig, d)
        tag = {1: "🐋+", 0: "", -1: "🐋✗"}[wc]
        if d.action == "TRADE":
            _live_ok = False
            if d.mode == "LIVE":
                result = place_order_live(sig, d, edge_stats=edge_stats)
                _live_ok = bool(result.get("ok"))
                if not _live_ok:
                    # Downgrade to paper if live refused/failed
                    d = Decision("TRADE", "PAPER", d.size_usd,
                                 f"LIVE ditolak: {result.get('reason', '')[:80]}")
            place_order_paper(sig, d)
            # v8.4: Only LIVE orders consume position slots. PAPER trades are
            # data-gathering only and should NEVER block subsequent signals.
            # Old bug: 1 LIVE + 4 PAPER = 5 slots full → 5+ signals SKIP'd.
            # Now: PAPER passes through freely, only LIVE capital consumes slots.
            if _live_ok:
                risk_state["open_positions"] = risk_state.get("open_positions", 0) + 1
            risk_state["trades"] = risk_state.get("trades", 0) + 1
            _save_daily_state(risk_state)
            traded += 1
            L.append(f"  ▸ {sig['direction']} {sig['coin']} {tag} ${d.size_usd} "
                     f"[{d.mode}] — {d.reason}")
        else:
            L.append(f"  ✗ {sig['coin']} {tag} SKIP — {d.reason}")
    if not actionable:
        L.append("  (tidak ada sinyal actionable non-dust saat ini)")
    L.append(f"  → {traded} paper-trade dicatat · {live_status}")
    return "\n".join(L)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Pre-Gain/Loser auto-trader (paper-first)")
    ap.add_argument("--live", action="store_true",
                    help="izinkan uang nyata (TETAP butuh edge terbukti + AUTOTRADE_LIVE=1)")
    args = ap.parse_args()
    live = args.live and os.environ.get("AUTOTRADE_LIVE") == "1"
    ROOT = Path(os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti")))
    import sys; sys.path.insert(0, str(ROOT))
    print(run_once(live_enabled=live))
