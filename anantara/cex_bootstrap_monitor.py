#!/usr/bin/env python3
"""
ANANTARA SAKTI — CEX Bootstrap Progress Monitor
v2.0 (2026-08-23) — Updated for v8.7 strategy (r8_* active paths).

Pure Python, stdlib-only (psycopg2 + numpy for computations, both in daemon env).
Provides:
  1. bootstrap_confidence() — running CI95 P(E>0) from R4 trades
  2. eta_to_100() — ETA to n=100 milestone in days
  3. pair_entry_stats() — per-pair entry rate, WR, avg PnL
  4. pair_entry_stats_active() — per-pair stats filtered to r8_* active paths
  5. get_path_split_stats() — r8_* (active) vs r6_bear (legacy/dead) split
  6. bootstrap_progress_report() — Telegram-formatted summary
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────
_BOOTSTRAP_ITERATIONS = 10_000
_BOOTSTRAP_SEED = 42
_TARGET_N = 100
_CI_LEVEL = 0.95
# v8.7 epoch: strategy upgraded to r8_* paths (r8_freqai/trend/neutral/pregain/pure).
# Aligned with cex_deep_loop.py _DEPLOY_DATE = "2026-08-22 23:00:00".
_DEPLOY_DATE = "2026-08-22 23:00:00"

# Active enter_tag pattern in v8.7 (AnantaraTrendFocused_v4).
# Legacy tag r6_bear_v8.2 is dead — no new trades use it.
_ACTIVE_TAG_PATTERN = "r8_%"
_LEGACY_TAG = "r6_bear_v8.2"


def _get_pg_conn(dbname: str = "anantara"):
    """Create PostgreSQL connection from .env credentials."""
    import psycopg2
    env_path = Path(os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti"))) / ".env"
    env_vars: dict = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env_vars[k.strip()] = v.strip()
    return psycopg2.connect(
        host=env_vars.get("POSTGRES_HOST", "localhost"),
        port=env_vars.get("POSTGRES_PORT", "5432"),
        dbname=dbname,
        user=env_vars.get("POSTGRES_USER", "anantara"),
        password=env_vars.get("POSTGRES_PASSWORD", ""),
    )


# ── Core: Bootstrap Confidence ──────────────────────────────────────────

def bootstrap_confidence(trades: list[float], n_iter: int = _BOOTSTRAP_ITERATIONS,
                         seed: int = _BOOTSTRAP_SEED) -> dict:
    """Compute bootstrap CI95 P(E>0) from list of trade profit fractions.

    Args:
        trades: list of profit values (e.g., close_profit from DB, 0.01 = +1%).
        n_iter: bootstrap iterations (default 10,000).
        seed: random seed for reproducibility.

    Returns:
        dict with keys: n, mean, std, ci_lower, ci_upper, p_positive, verdict.
        p_positive = fraction of bootstrap sample means that are > 0.
        If n < 5, returns placeholder with p_positive=None.
    """
    if len(trades) < 5:
        return {
            "n": len(trades), "mean": None, "std": None,
            "ci_lower": None, "ci_upper": None,
            "p_positive": None,
            "verdict": "⏳ n<5 — need more trades",
        }

    rng = np.random.default_rng(seed)
    arr = np.array(trades, dtype=float)
    n = len(arr)
    bootstrap_means = np.empty(n_iter)

    for i in range(n_iter):
        sample = rng.choice(arr, size=n, replace=True)
        bootstrap_means[i] = np.mean(sample)

    mean = float(np.mean(arr))
    std = float(np.std(arr))
    ci_lower = float(np.percentile(bootstrap_means, (1 - _CI_LEVEL) / 2 * 100))
    ci_upper = float(np.percentile(bootstrap_means, (1 + _CI_LEVEL) / 2 * 100))
    p_positive = float(np.mean(bootstrap_means > 0))

    if p_positive >= 0.90:
        verdict = "✅ GO — P(E>0)≥90%"
    elif p_positive >= 0.75:
        verdict = "🟡 PROMISING — P(E>0)≥75%"
    elif p_positive >= 0.50:
        verdict = "🟠 UNCERTAIN — P(E>0)≥50%"
    else:
        verdict = "🔴 BELOW 50% — more data needed"

    return {
        "n": n, "mean": mean, "std": std,
        "ci_lower": ci_lower, "ci_upper": ci_upper,
        "p_positive": p_positive,
        "verdict": verdict,
    }


# ── Core: ETA to n=100 ─────────────────────────────────────────────────

def eta_to_100(total_trades: int, deploy_date_str: str = _DEPLOY_DATE) -> dict:
    """Calculate ETA to n=100 based on current trade rate since deploy.

    Args:
        total_trades: current R4 trade count (all-time or since v8.2).
        deploy_date_str: ISO datetime string of v8.2 deploy.

    Returns:
        dict with keys: current_n, days_elapsed, rate_per_day, eta_days, eta_date.
    """
    deploy_dt = datetime.fromisoformat(deploy_date_str).replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    days_elapsed = max((now - deploy_dt).total_seconds() / 86400, 0.01)  # avoid div/0

    rate_per_day = total_trades / days_elapsed
    remaining = max(_TARGET_N - total_trades, 0)

    if rate_per_day > 0:
        eta_days = remaining / rate_per_day
    else:
        eta_days = float("inf")

    eta_date = (now + timedelta(days=eta_days)).strftime("%d %b %Y") if eta_days < 999 else "∞"

    return {
        "current_n": total_trades,
        "target_n": _TARGET_N,
        "days_elapsed": round(days_elapsed, 1),
        "rate_per_day": round(rate_per_day, 2),
        "eta_days": round(eta_days, 1) if eta_days < 999 else float("inf"),
        "eta_date": eta_date,
        "on_track_45d": days_elapsed <= 45 and eta_days <= (45 - days_elapsed),
    }


# ── Core: Pair-level Entry Stats ────────────────────────────────────────

def pair_entry_stats(since_deploy: bool = True) -> dict:
    """Get per-pair entry statistics from R4 (Binance) trades.

    Args:
        since_deploy: if True, only count trades since v8.2 deploy date.

    Returns:
        dict: {pair_name: {n, wins, wr, avg_pnl, last_entry}}
    """
    try:
        conn = _get_pg_conn("anantara")
        cur = conn.cursor()

        date_filter = ""
        params: tuple = ()
        if since_deploy:
            date_filter = "AND open_date >= %s"
            params = (_DEPLOY_DATE,)

        cur.execute(
            """
            SELECT pair, COUNT(*) as n,
                   SUM(CASE WHEN close_profit > 0 THEN 1 ELSE 0 END) as wins,
                   AVG(close_profit) as avg_pnl,
                   MAX(open_date) as last_entry
            FROM trades
            WHERE is_open = false
              AND strategy LIKE %s
              """
            + (" " + date_filter if date_filter else "")
            + """
            GROUP BY pair
            ORDER BY n DESC
        """,
            ("%AnantaraTrendFocused%",) + params,
        )

        stats: dict = {}
        for row in cur.fetchall():
            pair, n, wins, avg_pnl, last_entry = row
            coin = pair.split("/")[0]
            stats[coin] = {
                "n": int(n),
                "wins": int(wins),
                "wr": round(wins / n, 3) if n > 0 else 0,
                "avg_pnl": round(float(avg_pnl) * 100, 2) if avg_pnl else 0,
                "last_entry": last_entry.isoformat() if last_entry else None,
            }

        conn.close()
        return stats

    except Exception as e:
        log.warning(f"pair_entry_stats: {e}")  # visible: a swallowed DB error here
        return {}


def pair_entry_stats_active() -> dict:
    """Per-pair stats filtered to r8_* active paths ONLY (v8.7+).

    Returns {coin: {n, wins, wr, avg_pnl, last_entry}}.
    Filters to enter_tag LIKE 'r8_%' — the live strategy paths in v8.7.
    """
    try:
        conn = _get_pg_conn("anantara")
        cur = conn.cursor()
        cur.execute(
            """
            SELECT pair, COUNT(*) as n,
                   SUM(CASE WHEN close_profit > 0 THEN 1 ELSE 0 END) as wins,
                   AVG(close_profit) as avg_pnl,
                   MAX(open_date) as last_entry
            FROM trades
            WHERE is_open = false
              AND strategy LIKE %s
              AND open_date >= %s
              AND enter_tag LIKE %s
              AND close_profit IS NOT NULL
            GROUP BY pair
            ORDER BY n DESC
            """,
            ("%AnantaraTrendFocused%", _DEPLOY_DATE, _ACTIVE_TAG_PATTERN),
        )
        stats: dict = {}
        for row in cur.fetchall():
            pair, n, wins, avg_pnl, last_entry = row
            coin = pair.split("/")[0]
            stats[coin] = {
                "n": int(n),
                "wins": int(wins),
                "wr": round(wins / n, 3) if n > 0 else 0,
                "avg_pnl": round(float(avg_pnl) * 100, 2) if avg_pnl else 0,
                "last_entry": last_entry.isoformat() if last_entry else None,
            }
        conn.close()
        return stats
    except Exception as e:
        log.warning(f"pair_entry_stats_active: {e}")  # visible: never hide DB errors
        return {}


# Keep legacy alias so any old caller won't crash (returns empty — correct for v8.7)
def pair_entry_stats_r6_bear() -> dict:  # noqa: dead alias
    """Deprecated: r6_bear_v8.2 is a dead tag in v8.7. Returns empty."""
    return {}


# ── Core: All-time vs v8.2 trade count ──────────────────────────────────

def get_trade_counts() -> dict:
    """Get all-time and post-v8.2 trade counts and profit values."""
    try:
        conn = _get_pg_conn("anantara")
        cur = conn.cursor()

        # All-time R4.  %% used uniformly (harmless without params; future-proof
        # if a parameter is ever added — see the escaping note on the query below).
        cur.execute("""
            SELECT COUNT(*), AVG(close_profit), ARRAY_AGG(close_profit)
            FROM trades
            WHERE is_open = false
              AND strategy LIKE '%%AnantaraTrendFocused%%'
              AND close_profit IS NOT NULL
        """)
        all_row = cur.fetchone()
        all_n = int(all_row[0]) if all_row[0] else 0
        all_avg = float(all_row[1]) if all_row[1] else 0
        all_profits = list(all_row[2]) if all_row[2] else []

        # Since v8.7 deploy.  NOTE: this query passes a parameter (%s), so the
        # literal %-signs in the LIKE pattern MUST be escaped as %% — otherwise
        # psycopg2 treats %A…%s as format placeholders → IndexError (silent 0s).
        cur.execute(
            """
            SELECT COUNT(*), AVG(close_profit), ARRAY_AGG(close_profit)
            FROM trades
            WHERE is_open = false
              AND strategy LIKE '%%AnantaraTrendFocused%%'
              AND close_profit IS NOT NULL
              AND open_date >= %s
            """,
            (_DEPLOY_DATE,),
        )
        new_row = cur.fetchone()
        new_n = int(new_row[0]) if new_row[0] else 0
        new_avg = float(new_row[1]) if new_row[1] else 0
        new_profits = list(new_row[2]) if new_row[2] else []

        conn.close()

        return {
            "all_time": {"n": all_n, "avg": all_avg, "profits": all_profits},
            "since_v82": {"n": new_n, "avg": new_avg, "profits": new_profits},
        }
    except Exception as e:
        log.warning(f"get_trade_counts: {e}")  # visible: silent zeros hid the %% bug
        return {"all_time": {"n": 0, "avg": 0, "profits": []},
                "since_v82": {"n": 0, "avg": 0, "profits": []}}


# ── v8.7: Path-split stats (r8_* active vs r6_bear legacy) ─────────────

def get_path_split_stats() -> dict:
    """Separate r8_* (live active paths) from r6_bear (dead legacy tag).

    v8.7 reality:
      - r8_freqai / r8_trend / r8_neutral / r8_pregain / r8_pure = ACTIVE paths
      - r6_bear_v8.2 = dead/legacy tag, 0 new trades since v8.7 deploy

    Returns dict with keys: r8_active, r6_legacy, all_paths.
    Each key → {n, avg, profits, win_rate}.
    """
    try:
        conn = _get_pg_conn("anantara")
        cur = conn.cursor()

        def _fetch_path(tag_filter: str) -> dict:
            op = "LIKE" if "%" in tag_filter else "="
            cur.execute(
                f"""
                SELECT COUNT(*), ARRAY_AGG(close_profit),
                       SUM(CASE WHEN close_profit > 0 THEN 1 ELSE 0 END)
                FROM trades
                WHERE is_open = false
                  AND strategy LIKE '%%AnantaraTrendFocused%%'
                  AND close_profit IS NOT NULL
                  AND open_date >= %s
                  AND enter_tag {op} %s
                """,
                (_DEPLOY_DATE, tag_filter),
            )
            row = cur.fetchone()
            n = int(row[0]) if row[0] else 0
            profits = [float(x) for x in row[1]] if row[1] else []
            wins = int(row[2]) if row[2] else 0
            return {
                "n": n,
                "profits": profits,
                "avg": float(sum(profits) / n) if n > 0 else 0.0,
                "win_rate": wins / n if n > 0 else 0.0,
            }

        r8_active = _fetch_path(_ACTIVE_TAG_PATTERN)   # r8_% — live strategy paths
        r6_legacy = _fetch_path(_LEGACY_TAG)            # r6_bear_v8.2 — dead tag
        all_paths = _fetch_path("%%")                   # all closed trades since deploy

        conn.close()
        return {"r8_active": r8_active, "r6_legacy": r6_legacy, "all_paths": all_paths}

    except Exception as e:
        log.warning(f"get_path_split_stats: {e}")  # visible: never hide DB errors
        empty = {"n": 0, "profits": [], "avg": 0.0, "win_rate": 0.0}
        return {"r8_active": empty, "r6_legacy": dict(empty), "all_paths": dict(empty)}


# ── Composite: Full Bootstrap Progress Report ───────────────────────────

def bootstrap_progress_report() -> str:
    """Generate a Telegram-formatted bootstrap progress summary.

    v8.7: Active paths are r8_* (r8_freqai/trend/neutral/pregain/pure).
    r6_bear_v8.2 is a dead legacy tag — shown as reference only (always 0).
    Bootstrap P(E>0) is computed on r8_* active trades only.
    """
    counts = get_trade_counts()
    all_n = counts["all_time"]["n"]
    new_n = counts["since_v82"]["n"]
    new_profits = counts["since_v82"]["profits"]

    paths = get_path_split_stats()
    r8 = paths["r8_active"]    # live strategy paths (r8_freqai/trend/neutral/pregain/pure)
    r6 = paths["r6_legacy"]    # dead tag (always 0 in v8.7)

    # Bootstrap on r8_* ONLY — this is the active path set
    bs_r8 = bootstrap_confidence(r8["profits"])
    # Bootstrap on aggregate for reference
    bs_all = bootstrap_confidence(new_profits)
    eta = eta_to_100(r8["n"])  # ETA uses r8_* active count

    # Build message
    lines = [
        "📊 *Bootstrap Progress — v8.7*",
        "━━━━━━━━━━━━━━━━━━━━━",
    ]

    # ── Active paths: r8_* (r8_freqai/trend/neutral/pregain/pure) ────────
    progress_bar = _make_bar(r8["n"], _TARGET_N, width=14)
    lines.append(f"*r8_\\* (ACTIVE paths)*: {r8['n']}/{_TARGET_N} {progress_bar}")

    if bs_r8["p_positive"] is not None:
        lines.append(
            f"*P(E>0)*: {bs_r8['p_positive']:.1%} "
            f"[{bs_r8['ci_lower']*100:+.2f}%, {bs_r8['ci_upper']*100:+.2f}%]"
        )
        lines.append(f"*Verdict*: {bs_r8['verdict']}")
        lines.append(
            f"*Mean*: {bs_r8['mean']*100:+.2f}% | "
            f"*WR*: {r8['win_rate']:.0%} | "
            f"*Std*: {bs_r8['std']*100:.2f}%"
        )
    else:
        lines.append(f"*P(E>0)*: ⏳ n={r8['n']}<5 — accumulating...")

    # Rate & ETA
    rate_str = f"{eta['rate_per_day']:.1f}/day" if eta['rate_per_day'] > 0 else "no trades yet"
    eta_str = f"{eta['eta_days']:.0f}d → {eta['eta_date']}" if eta['eta_days'] < 999 else "∞"
    on_track = "✅ ON TRACK" if eta.get('on_track_45d') else "⚠️ BEHIND"
    lines.append(f"*Rate*: {rate_str} | *ETA n=100*: {eta_str} {on_track}")

    # ── Legacy tag: r6_bear_v8.2 (dead — should always be 0 in v8.7) ────
    if r6["n"] > 0:
        lines.append("━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"⚠️ *r6_bear (LEGACY/dead tag)*: {r6['n']}t "
                     f"WR={r6['win_rate']:.0%} avg={r6['avg']*100:+.2f}%")
        lines.append("  _Unexpected: r6_bear should have 0 trades since v8.7 deploy_")

    # ── Aggregate (all r8_* paths, for reference) ────────────────────────
    if new_n > 0:
        lines.append("━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"*Aggregate (all paths, since v8.7)*: {new_n}t  all-time: {all_n}")
        if bs_all["p_positive"] is not None:
            lines.append(f"  P(E>0)={bs_all['p_positive']:.1%}")

    # ── Per-pair breakdown (r8_* active paths only) ───────────────────────
    r8_pairs = pair_entry_stats_active()
    if r8_pairs:
        lines.append("━━━━━━━━━━━━━━━━━━━━━")
        lines.append("*By Pair — r8_\\* active paths*:")
        max_n = max(p["n"] for p in r8_pairs.values()) if r8_pairs else 1
        for coin, stats in sorted(r8_pairs.items(), key=lambda x: -x[1]["n"]):
            bar = _make_bar(stats["n"], max(1, max_n), width=6)
            lines.append(
                f"  {coin:5s}: {stats['n']:2d}t {bar} WR={stats['wr']:.0%} "
                f"avg={stats['avg_pnl']:+.1f}%"
            )
    else:
        lines.append("")
        lines.append("_No r8_\\* trades yet — accumulating since v8.7 deploy_")

    lines.append("")
    lines.append(f"_Next update: {(datetime.now(timezone.utc) + timedelta(hours=6)).strftime('%H:%M UTC')}_")

    return "\n".join(lines)


def _make_bar(value: int, total: int, width: int = 10) -> str:
    """Simple ASCII progress bar."""
    if total <= 0:
        return "[          ]"
    filled = min(int(value / total * width), width)
    return "[" + "█" * filled + "░" * (width - filled) + "]"


# ── Self-test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if "--report" in sys.argv:
        print(bootstrap_progress_report())
    elif "--pairs" in sys.argv:
        stats = pair_entry_stats()
        for coin, s in sorted(stats.items()):
            print(f"{coin}: {s}")
    elif "--bootstrap" in sys.argv:
        counts = get_trade_counts()
        bs = bootstrap_confidence(counts["since_v82"]["profits"])
        print(bs)
    elif "--eta" in sys.argv:
        counts = get_trade_counts()
        eta = eta_to_100(counts["since_v82"]["n"])
        print(eta)
    else:
        # Full test
        print("=== Bootstrap Monitor Self-Test ===\n")
        counts = get_trade_counts()
        print(f"All-time R4 trades: {counts['all_time']['n']}")
        print(f"v8.2 trades: {counts['since_v82']['n']}")
        print()
        bs = bootstrap_confidence(counts["since_v82"]["profits"])
        print(f"Bootstrap: {bs}")
        print()
        eta = eta_to_100(counts["since_v82"]["n"])
        print(f"ETA: {eta}")
        print()
        pairs = pair_entry_stats()
        print(f"Pair stats: {pairs}")
        print()
        print("=" * 60)
        print(bootstrap_progress_report())
