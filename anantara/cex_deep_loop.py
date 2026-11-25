#!/usr/bin/env python3
"""
ANANTARA SAKTI — CEX Deep Loop Learning (v2.0, 2026-08-23)

v2.0 overhaul (2026-08-23):
  - Wilson CI lower bound replaces raw WR threshold.
    Veto only when we are statistically confident (p<0.10, one-tailed binomial)
    that the path's TRUE win rate is below 50%.  At n=5 this requires WR=0%;
    at n=15 requires WR<27%; at n=25 requires WR<36%.  Prevents deadlock on
    small samples with random negative streaks.
  - Time-decay weighting: trades in the last 7 days count 2×.  More recent
    evidence weighs heavier than stale data from a different regime.
  - Aggregate family veto REMOVED → monitoring/alert only.  The aggregate veto
    was the root cause of the Aug-22 deadlock that froze ALL r8_* entry paths
    from v8.7 day 1 because it fired before any path had n≥15.
  - Veto auto-expiry: if a vetoed path has received ZERO new trades for
    _EXPIRY_DAYS days, the veto is cleared.  Prevents permanent zombies.
  - Separate per-path statistics include CI bounds for transparency.
  - _VETO_MIN_N lowered 15→10 (the Wilson p<0.10 gate now supplies the
    statistical confidence, so 10 is enough evidence: a 0/11 path is p=0.001).
    _AGG_VETO_MIN_N removed with the aggregate family veto (see above).
  - Fails open on any DB/IO error (unchanged safety invariant).

v1.2 (2026-08-22): _VETO_MIN_N 5→15, _BOOST_MIN_N 5→10, _AGG_VETO_MIN_N 8→20
  (superseded by v2.0: _VETO_MIN_N→10, aggregate veto removed)
v1.1 (2026-08-13): aggregate veto for r8_* family
v1.0 (2026-08-13): initial per-entry-path learning

Pure stdlib + psycopg2 (daemon env). Runs via job_cex_deep_loop daily.
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

_DEPLOY_DATE = "2026-08-01 00:00:00"   # v8.x epoch — mencakup r6_bear_v8.2
                                        # (n=23 WR 70% E+0.55%, 8-11 Agu) + r8_*
                                        # PREVIOUSLY "2026-08-22" — mengecualikan
                                        # 23 profitable r6 trades (bug audit 2026-09-01)
_LEARNING_FILE = "freqtrade_user_data/data/binance/cex_deep_loop.json"
_ENTRY_PATHS = ["r8_freqai", "r8_trend", "r8_neutral", "r8_pregain", "r8_pure",
                "r8_long_neutral", "r8_long_pregain", "r6_bear_v8.2"]

# ── Monitor-only paths (preregistered decision 2026-09-13) ──────────────────
# r6-bear-short: boost deep-loop berasal dari data freqtrade-era lama
# (_DEPLOY_DATE 2026-08-01, n=23 WR=70%) sedangkan paper ledger menunjukkan
# n=23 WR=26% E=-0.08% p=0.017. Keputusan: R6 monitor-only, TIDAK boleh
# menerima BOOST dari deep-loop. Veto tetap diizinkan (arah konsisten).
_MONITOR_ONLY_PATHS = {"r6_bear_v8.2"}

# ── Statistical veto thresholds (falsification-first) ────────────────────────
# Require BOTH: enough sample (n≥10) AND clear statistical evidence that WR<50%.
# Wilson/binomial p<0.10 supplies the confidence: at n=10 and WR=0% → p≈0.001
# (veto); at n=11 and WR=0% → p≈0.0005 (veto); at n=15 and WR=0.27 → p≈0.083
# (veto); at n=5 and WR=0.40 → p=0.185 → NO veto. Much safer than raw threshold.
_VETO_MIN_N = 10            # absolute minimum before ANY veto is considered
_VETO_P_THRESHOLD = 0.10    # one-tailed p-value < this to veto (WR ≪ 50%)
_BOOST_MIN_N = 10           # minimum trades before boosting
_BOOST_MIN_EXPECTANCY = 0.25  # expectancy >= 0.25% avg return → boost flag

# ── Freshness guard (v2.1, 2026-09-19) ───────────────────────────────────────
# RCA: veto/boost diputuskan dari tabel `trades` Freqtrade. Untuk beberapa path
# (r6_bear_v8.2 terakhir 12 Agu, r8_freqai 23 Agu, r8_trend 25 Agu) tabel itu
# BERHENTI mengalir, sehingga keputusan diambil atas bukti berumur 25–38 hari —
# sementara ledger paper-test menunjukkan hasil yang berlawanan untuk path yang
# sama (r6: DB WR 69.6% vs paper-test WR 26.1%). Bukti basi TIDAK boleh dipakai
# untuk mem-veto/meng-boost: keputusan terakhir dibawa (carry-forward), bukan
# dihitung ulang. Fail-safe: tidak ada veto baru DAN tidak ada pembukaan veto lama.
_MAX_EVIDENCE_AGE_DAYS = 14  # bukti lebih tua dari ini → decision_source=carried_forward

# ── Time-weighting ────────────────────────────────────────────────────────────
_RECENT_WINDOW_DAYS = 7     # trades in this window counted 2× (recency bias)

# ── Auto-expiry ───────────────────────────────────────────────────────────────
_EXPIRY_DAYS = 14           # clear veto if path has 0 new trades for this long


# ──────────────────────────────────────────────────────────────────────────────
# Statistical helpers
# ──────────────────────────────────────────────────────────────────────────────

def _norm_cdf(z: float) -> float:
    """Standard normal CDF (Abramowitz & Stegun approximation, error < 1.5e-7)."""
    if z < 0:
        return 1.0 - _norm_cdf(-z)
    t = 1.0 / (1.0 + 0.2316419 * z)
    poly = t * (0.319381530
                + t * (-0.356563782
                       + t * (1.781477937
                              + t * (-1.821255978 + t * 1.330274429))))
    return 1.0 - (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * z * z) * poly


def _binom_lower_pval(wins: int, n: int, p0: float = 0.50) -> float:
    """One-tailed p-value for H0: true_WR = p0, observed WR ≤ wins/n.

    Uses normal approximation with continuity correction (safe for n≥10).
    Returns 1.0 when n < 10 (insufficient data — fail open).
    """
    if n < 10:
        return 1.0  # insufficient data → no evidence → no veto
    # Continuity correction: test wins+0.5 / n vs p0
    z = (wins + 0.5 - n * p0) / math.sqrt(n * p0 * (1 - p0))
    return _norm_cdf(z)  # lower tail probability


def _wilson_ci(wins: int, n: int, z: float = 1.645) -> tuple[float, float]:
    """Wilson score confidence interval (z=1.645 → 90% two-sided = 5% each tail)."""
    if n == 0:
        return (0.0, 1.0)
    p_hat = wins / n
    denom = 1 + z * z / n
    centre = (p_hat + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


# ──────────────────────────────────────────────────────────────────────────────
# DB access
# ──────────────────────────────────────────────────────────────────────────────

def _get_pg_conn(dbname: str = "anantara"):
    import psycopg2
    env_path = Path(os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti"))) / ".env"
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
        password=env_vars.get("POSTGRES_PASSWORD", os.environ.get("POSTGRES_PASSWORD", "")),
    )


def _learning_path() -> Path:
    candidates = []
    if os.environ.get("ANANTARA_DIR"):
        candidates.append(Path(os.environ["ANANTARA_DIR"]) / _LEARNING_FILE)
    candidates.append(Path.home() / "anantara-sakti" / _LEARNING_FILE)
    candidates.append(Path("/freqtrade/user_data") / "data/binance/cex_deep_loop.json")
    for cand in candidates:
        if cand.parent.exists():
            return cand
    return candidates[-1]


# ──────────────────────────────────────────────────────────────────────────────
# Trade data fetch with timestamps
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_trades_by_path() -> dict[str, list[tuple[float, datetime]]]:
    """Fetch closed R4 trades since _DEPLOY_DATE → {enter_tag: [(pnl, close_date), ...]}."""
    conn = None
    try:
        conn = _get_pg_conn("anantara")
        cur = conn.cursor()
        cur.execute("""
            SELECT enter_tag, close_profit, close_date
            FROM trades
            WHERE is_open = false
              AND strategy LIKE '%%AnantaraTrend%%'
              AND open_date >= %s
              AND close_date IS NOT NULL
            ORDER BY close_date DESC
        """, (_DEPLOY_DATE,))
        rows = cur.fetchall()
    except Exception as e:
        log.error(f"_fetch_trades_by_path: {e}")
        return {}
    finally:
        if conn is not None:
            conn.close()

    by_path: dict[str, list[tuple[float, datetime]]] = {}
    for tag, pnl, close_dt in rows:
        tag = tag or "?"
        by_path.setdefault(tag, []).append((float(pnl or 0.0), close_dt))
    return by_path


# ──────────────────────────────────────────────────────────────────────────────
# Statistics with time-weighting
# ──────────────────────────────────────────────────────────────────────────────

def _weighted_path_stats(entries: list[tuple[float, datetime]], now: datetime) -> dict:
    """Compute path statistics with time-decay weighting.

    Trades in the last _RECENT_WINDOW_DAYS are weighted 2×; older = 1×.
    Reports both raw (unweighted) and effective (weighted) values.
    Includes Wilson CI lower bound and one-tailed p-value.
    """
    if not entries:
        return {
            "n": 0, "wr": 0.0, "expectancy": 0.0, "net_pct": 0.0, "pf": 0.0,
            "wilson_ci_lo": 0.0, "wilson_ci_hi": 1.0, "pval": 1.0,
            "weighted_n": 0.0, "weighted_wr": 0.0, "weighted_expectancy": 0.0,
            "last_trade_days_ago": None,
        }

    cutoff = now - timedelta(days=_RECENT_WINDOW_DAYS)
    # Make cutoff naive to compare with potentially naive DB timestamps
    cutoff_naive = cutoff.replace(tzinfo=None)
    raw_pnls = [pnl for pnl, _ in entries]
    n = len(raw_pnls)

    # ── Raw stats (for transparency) ──────────────────────────────────────────
    wins_raw = sum(1 for p in raw_pnls if p > 0)
    wr_raw = wins_raw / n
    expectancy_raw = sum(raw_pnls) / n * 100
    gw = sum(p for p in raw_pnls if p > 0)
    gl = abs(sum(p for p in raw_pnls if p <= 0))
    pf = round(gw / gl, 3) if gl > 0 else (float("inf") if gw > 0 else 0.0)

    # ── Wilson CI on raw wins/n (most reliable for veto decisions) ─────────
    ci_lo, ci_hi = _wilson_ci(wins_raw, n)
    pval = _binom_lower_pval(wins_raw, n)

    # ── Time-weighted stats ────────────────────────────────────────────────
    weighted_pnl_sum = 0.0
    weighted_wins = 0.0
    weighted_n = 0.0
    for pnl, ts in entries:
        ts_naive = ts.replace(tzinfo=None) if ts.tzinfo is not None else ts
        w = 2.0 if ts_naive >= cutoff_naive else 1.0
        weighted_n += w
        weighted_pnl_sum += pnl * w
        if pnl > 0:
            weighted_wins += w
    weighted_wr = weighted_wins / weighted_n if weighted_n > 0 else 0.0
    weighted_exp = weighted_pnl_sum / weighted_n * 100 if weighted_n > 0 else 0.0

    # ── Recency: most recent trade ────────────────────────────────────────
    most_recent = entries[0][1] if entries else None  # entries sorted DESC
    if most_recent is not None:
        mr_naive = most_recent.replace(tzinfo=None) if most_recent.tzinfo is not None else most_recent
        now_naive = now.replace(tzinfo=None)
        days_ago = (now_naive - mr_naive).total_seconds() / 86400
    else:
        days_ago = None

    return {
        "n": n,
        "wr": round(wr_raw, 3),
        "expectancy": round(expectancy_raw, 3),
        "net_pct": round(sum(raw_pnls) * 100, 3),
        "pf": pf,
        "wilson_ci_lo": round(ci_lo, 3),
        "wilson_ci_hi": round(ci_hi, 3),
        "pval": round(pval, 4),
        "weighted_n": round(weighted_n, 1),
        "weighted_wr": round(weighted_wr, 3),
        "weighted_expectancy": round(weighted_exp, 3),
        "last_trade_days_ago": round(days_ago, 1) if days_ago is not None else None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Core analysis
# ──────────────────────────────────────────────────────────────────────────────

def analyze_paths(dbname: str = "anantara") -> dict:
    """Analyze per-entry-path stats from live trades.

    Veto logic (v2.0 — Wilson CI):
      1. n >= _VETO_MIN_N  (enough absolute sample)
      2. one-tailed p-value < _VETO_P_THRESHOLD  (statistically confident WR < 50%)
      3. weighted_expectancy < 0  (time-weighted returns are negative)
      All three must hold simultaneously → veto fires.

    Aggregate veto REMOVED (monitoring note only).

    Returns dict with full stats per tag.
    """
    by_path = _fetch_trades_by_path()
    now = datetime.now(timezone.utc)
    out: dict = {}

    for tag, entries in by_path.items():
        s = _weighted_path_stats(entries, now)

        # ── Veto decision (Wilson CI + p-value + weighted expectancy) ──────
        sufficient_n = s["n"] >= _VETO_MIN_N
        stat_significant = s["pval"] < _VETO_P_THRESHOLD  # p(WR<50%) < 10%
        negative_return = s["weighted_expectancy"] < 0.0

        veto = sufficient_n and stat_significant and negative_return
        # Freshness guard (dipakai lagi setelah boost dihitung di bawah).
        _age = s.get("last_trade_days_ago")
        stale = _age is not None and _age > _MAX_EVIDENCE_AGE_DAYS
        veto_reason: str | None = None
        if veto:
            veto_reason = (
                f"n={s['n']} p={s['pval']:.3f}<{_VETO_P_THRESHOLD} "
                f"WR={s['wr']:.1%} wExp={s['weighted_expectancy']:+.2f}%"
            )

        # ── Boost decision ────────────────────────────────────────────────
        boost = (s["n"] >= _BOOST_MIN_N and
                 s["weighted_expectancy"] >= _BOOST_MIN_EXPECTANCY)
        monitor_only = tag in _MONITOR_ONLY_PATHS
        if monitor_only:
            # Historical r6 boost comes from legacy Freqtrade-era data; current
            # paper ledger makes this path quarantine/monitor-only. Veto may fire,
            # boost must not reach entry prioritization.
            boost = False
        if stale:
            # Bukti basi: JANGAN veto/boost di sini. refresh_learning() akan
            # membawa keputusan terakhir (carry-forward) supaya bukti tua tidak
            # membuka veto lama maupun membuat veto baru.
            veto = False
            boost = False

        out[tag] = {**s, "veto": veto, "boost": boost}
        if stale:
            out[tag]["stale"] = True
            out[tag]["stale_days"] = _age
        if monitor_only:
            out[tag]["monitor_only"] = True
        if veto_reason:
            out[tag]["veto_reason"] = veto_reason
        if veto:
            log.warning(f"cex_deep_loop: VETO {tag} ({veto_reason})")
        elif boost:
            log.info(f"cex_deep_loop: BOOST {tag} "
                     f"(n={s['n']} wExp={s['weighted_expectancy']:+.2f}% "
                     f"WR={s['wr']:.1%})")

    # ── Aggregate family monitoring (alert only, no veto) ─────────────────
    r8_pnls: list[float] = []
    for tag, entries in by_path.items():
        if tag.startswith("r8_"):
            r8_pnls.extend(p for p, _ in entries)
    if r8_pnls:
        n_agg = len(r8_pnls)
        wr_agg = sum(1 for p in r8_pnls if p > 0) / n_agg
        exp_agg = sum(r8_pnls) / n_agg * 100
        gw = sum(p for p in r8_pnls if p > 0)
        gl = abs(sum(p for p in r8_pnls if p <= 0))
        pf_agg = round(gw / gl, 3) if gl > 0 else 0.0
        log.info(f"cex_deep_loop: r8_* aggregate "
                 f"n={n_agg} WR={wr_agg:.1%} E={exp_agg:+.2f}% PF={pf_agg:.2f} "
                 f"(monitoring only — no aggregate veto in v2.0)")

    return out


def _apply_expiry(current_paths: dict, saved_vetoed: list[str], now: datetime) -> dict:
    """Expire a saved veto only after current evidence no longer triggers veto.

    No-trade age by itself is not recovery evidence: a vetoed path naturally has
    few/no new trades because it is blocked. Clearing it would re-enable a
    statistically bad path without falsification.
    """
    for tag in saved_vetoed:
        if tag not in current_paths:
            continue
        if current_paths[tag].get("veto"):
            continue
        days_ago = current_paths[tag].get("last_trade_days_ago")
        if days_ago is not None and days_ago >= _EXPIRY_DAYS:
            current_paths[tag]["veto_reason"] = (
                f"veto_expired_{days_ago:.0f}d_no_new_trades_after_recovery"
            )
            log.info(f"cex_deep_loop: EXPIRE stale saved veto for {tag} "
                     f"(current evidence recovered; no new trades in {days_ago:.0f}d)")
    return current_paths


# ──────────────────────────────────────────────────────────────────────────────
# Persistence
# ──────────────────────────────────────────────────────────────────────────────

def save_learning(path: Path | None = None, paths: dict | None = None) -> Path:
    """Persist per-path learning to JSON atomically."""
    path = path or _learning_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "2.0",
        "generated_ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "deploy_date": _DEPLOY_DATE,
        "veto_min_n": _VETO_MIN_N,
        "veto_p_threshold": _VETO_P_THRESHOLD,
        "paths": paths or {},
        "vetoed": sorted(k for k, v in (paths or {}).items() if v.get("veto")),
        "boosted": sorted(
            k for k, v in (paths or {}).items()
            if v.get("boost") and k not in _MONITOR_ONLY_PATHS
        ),
        "monitor_only": sorted(_MONITOR_ONLY_PATHS),
        "max_evidence_age_days": _MAX_EVIDENCE_AGE_DAYS,
        "stale_paths": sorted(k for k, v in (paths or {}).items() if v.get("stale")),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)
    log.info(f"cex_deep_loop: saved {len(payload['vetoed'])} vetoed, "
             f"{len(payload['boosted'])} boosted → {path}")
    return path


def load_learning(path: Path | None = None) -> dict:
    """Read learning JSON. Fails open (empty structure) on missing/corrupt."""
    path = path or _learning_path()
    empty = {"generated_ts": None, "paths": {}, "vetoed": [], "boosted": []}
    if not path.exists():
        return empty
    try:
        data = json.loads(path.read_text())
        return {
            "generated_ts": data.get("generated_ts"),
            "paths": data.get("paths", {}),
            "vetoed": data.get("vetoed", []),
            "boosted": data.get("boosted", []),
        }
    except Exception as e:
        log.error(f"load_learning: {e}")
        return empty


def refresh_learning(dbname: str = "anantara", path: Path | None = None) -> dict:
    """Full pipeline: analyze paths → carry-forward stale → apply expiry → persist."""
    current_paths = analyze_paths(dbname)

    saved = load_learning(path)
    # Freshness guard (v2.1): path dengan bukti basi MEMBAWA keputusan terakhir.
    # Tanpa ini, path yang berhenti mengalir data (r6/r8_freqai/r8_trend) akan
    # di-veto/di-boost atas bukti berumur 25–38 hari, atau sebaliknya: veto lama
    # terbuka sendiri karena "tidak ada bukti baru". Keduanya salah.
    prev_veto = set(saved.get("vetoed", []) or [])
    prev_boost = set(saved.get("boosted", []) or [])
    for tag, st in current_paths.items():
        if st.get("stale"):
            st["veto"] = tag in prev_veto
            st["boost"] = tag in prev_boost
            st["decision_source"] = "carried_forward_stale"

    # Apply expiry to previously-vetoed paths
    current_paths = _apply_expiry(current_paths, saved.get("vetoed", []), datetime.now(timezone.utc))

    save_learning(path, current_paths)
    return load_learning(path)


def is_path_vetoed(entry_tag: str, learning: dict) -> bool:
    """True if this entry path is auto-vetoed by deep-loop learning."""
    try:
        return entry_tag in (learning or {}).get("vetoed", [])
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    import pprint
    result = refresh_learning()
    print("\n=== Deep Loop Learning State ===")
    print(f"Vetoed:  {result['vetoed']}")
    print(f"Boosted: {result['boosted']}")
    print("\nPer-path details:")
    for tag, stats in result.get("paths", {}).items():
        print(f"  {tag}: n={stats.get('n')} WR={stats.get('wr',0):.1%} "
              f"E={stats.get('expectancy',0):+.2f}% pval={stats.get('pval',1):.3f} "
              f"veto={stats.get('veto')} boost={stats.get('boost')}")
