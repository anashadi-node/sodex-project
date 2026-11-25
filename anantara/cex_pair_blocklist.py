#!/usr/bin/env python3
"""
ANANTARA SAKTI — CEX Auto-Pair Blocklist
v1.0 (2026-08-13) — Data-driven pair protection for R4 bootstrap.

Pure Python, stdlib-only (psycopg2 for DB access, in daemon env).
Provides:
  1. compute_pair_stats()  — per-pair-direction WR/avg/net since deploy
  2. decide_blocks()       — which pairs meet HARD/SOFT block criteria
  3. save_blocklist()/load_blocklist() — JSON persistence (host ↔ container)
  4. is_pair_blocked()     — quick check for the strategy gate

Criteria (from daemon job_cex_accuracy_check "Add to _PAIR_BLOCKS if n≥5"):
  HARD BLOCK: n >= 5 AND WR < 25% AND avg_pct < -1.5%
  SOFT BLOCK: n >= 3 AND WR < 25% AND avg_pct < -1.5% (alert-only tier)

Purpose: protects the R4 bootstrap from pairs that are consistently
underperforming (e.g. LINK WR=17% n=6 in Aug 2026) by vetoing their entries
in confirm_trade_entry, without human intervention. The blocklist file is
written by the daemon (host) and read by the strategy (container) via the
shared freqtrade_user_data mount.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────
# v8.x epoch — mencakup r6_bear_v8.2 (WR 70%, E+0.55%) + r8_*. Semua pair
# sejak deploy v8 dimonitor. PREVIOUSLY "2026-08-22" — mengecualikan 23
# profitable r6 trades (bug audit 2026-09-01).
_DEPLOY_DATE = "2026-08-01 00:00:00"
_BLOCKLIST_FILE = "freqtrade_user_data/data/binance/cex_pair_blocklist.json"

# Criteria thresholds (aligned with daemon pair-degradation logic)
_HARD_MIN_N = 5      # enough sample before a hard block
_HARD_MAX_WR = 0.25  # WR below 25% = consistently losing
_HARD_MAX_AVG = -1.5  # avg PnL below -1.5%
_SOFT_MIN_N = 3      # alert tier at n>=3

# v1.1 (2026-08-13): full lifecycle — HARD → PROBATION → UNBLOCK / RE-BLOCK
# A pair stuck in HARD forever is bad (no chance to recover) AND wasteful if it
# was a temporary regime. Lifecycle:
#   HARD (n>=5, WR<25%, avg<-1.5%) → entries vetoed, open trades cut at -1.5%.
#   After COOLDOWN_DAYS in HARD, if CURRENT stats recovered (WR>=40% OR avg>=0)
#   → move to PROBATION (watch tier): entries allowed but cut at -1.0% tighter.
#   PROBATION pair that stays profitable (WR>=45% over >=3 new trades) → UNBLOCK.
#   PROBATION pair that turns losing again (WR<25%) → RE-BLOCK to HARD.
_COOLDOWN_DAYS = 7            # minimum days in HARD before probation eligible
_PROBATION_RECOVER_WR = 0.40  # current WR at/above = "looks recovered" → probation
_PROBATION_RECOVER_AVG = 0.0  # or avg >= 0
_UNBLOCK_MIN_N = 3            # new trades needed (while in probation) to confirm
_UNBLOCK_MIN_WR = 0.45        # WR threshold to confirm recovery → unblock
_REBLOCK_MAX_WR = 0.25        # probation pair dropping below → re-block to HARD
_DEFAULT_PROBATION = {"blocked_at": None, "probation_start": None, "n_since": 0,
                      "wins_since": 0, "pnl_since": 0.0}


def _key_to_pair(key: str) -> str:
    """Convert 'LINK_SHORT' back to a freqtrade pair fragment."""
    return key.split("_")[0]


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


def _blocklist_path() -> Path:
    """Resolve blocklist JSON path (works on host and in container)."""
    candidates = []
    # 1. Explicit ANANTARA_DIR (daemon on host)
    if os.environ.get("ANANTARA_DIR"):
        candidates.append(Path(os.environ["ANANTARA_DIR"]) / _BLOCKLIST_FILE)
    # 2. Default home path (host, when ANANTARA_DIR unset)
    candidates.append(Path.home() / "anantara-sakti" / _BLOCKLIST_FILE)
    # 3. In freqtrade container: /freqtrade/user_data is mounted to freqtrade_user_data/
    candidates.append(Path("/freqtrade/user_data") / "data/binance/cex_pair_blocklist.json")
    # Prefer a path whose parent already exists (host wins; container last resort)
    for cand in candidates:
        if cand.parent.exists():
            return cand
    return candidates[-1]


def compute_pair_stats(dbname: str = "anantara", since: str = _DEPLOY_DATE,
                       conn=None) -> dict[str, dict]:
    """Per-pair-direction stats for closed trades since `since`.

    Returns {pair_dir_key: {"n","wins","pnl_sum","avg_pct","wr"}} where
    pair_dir_key is e.g. "LINK_SHORT". Fails gracefully (empty dict) on error.
    """
    _own_conn = conn is None
    try:
        if _own_conn:
            conn = _get_pg_conn(dbname)
        cur = conn.cursor()
        cur.execute("""
            SELECT pair, CASE WHEN is_short THEN 'SHORT' ELSE 'LONG' END AS dir,
                   close_profit
            FROM trades
            WHERE is_open = false
              AND strategy LIKE '%%AnantaraTrendFocused%%'
              AND open_date >= %s
        """, (since,))
        rows = cur.fetchall()
    except Exception as e:
        log.error(f"compute_pair_stats: {e}")
        return {}
    finally:
        if _own_conn and conn is not None:
            conn.close()

    stats: dict[str, dict] = {}
    for pair, direction, profit in rows:
        key = f"{pair.split('/')[0]}_{direction}"
        s = stats.setdefault(key, {"n": 0, "wins": 0, "pnl_sum": 0.0})
        s["n"] += 1
        if profit > 0:
            s["wins"] += 1
        s["pnl_sum"] += profit

    for s in stats.values():
        s["avg_pct"] = round(s["pnl_sum"] / s["n"] * 100, 2) if s["n"] else 0.0
        s["wr"] = round(s["wins"] / s["n"], 3) if s["n"] else 0.0
    return stats


def decide_blocks(stats: dict[str, dict]) -> dict[str, dict]:
    """Classify pairs into HARD and SOFT blocks from per-pair stats.

    Returns {"hard": {key: {n, wr, avg_pct}}, "soft": {...}}.
    """
    hard, soft = {}, {}
    for key, s in stats.items():
        if s["n"] >= _HARD_MIN_N and s["wr"] < _HARD_MAX_WR and s["avg_pct"] < _HARD_MAX_AVG:
            hard[key] = {"n": s["n"], "wr": s["wr"], "avg_pct": s["avg_pct"]}
        elif s["n"] >= _SOFT_MIN_N and s["wr"] < _HARD_MAX_WR and s["avg_pct"] < _HARD_MAX_AVG:
            soft[key] = {"n": s["n"], "wr": s["wr"], "avg_pct": s["avg_pct"]}
    return {"hard": hard, "soft": soft}


def save_blocklist(path: Path | None = None,
                   hard: dict | None = None, soft: dict | None = None,
                   probation: dict | None = None) -> Path:
    """Write blocklist JSON (hard + soft + probation + metadata). Returns path."""
    path = path or _blocklist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hard": hard or {},
        "soft": soft or {},
        "probation": probation or {},
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")
    log.info(f"cex_pair_blocklist: saved {len(payload['hard'])} hard, "
             f"{len(payload['soft'])} soft, {len(payload['probation'])} probation → {path}")
    return path


def load_blocklist(path: Path | None = None) -> dict:
    """Read blocklist JSON. Returns {"generated_ts":..., "hard":{}, "soft":{},
    "probation":{}}. Returns empty structure on missing/corrupt (fails open)."""
    path = path or _blocklist_path()
    empty = {"generated_ts": None, "hard": {}, "soft": {}, "probation": {}}
    if not path.exists():
        return empty
    try:
        data = json.loads(path.read_text())
        return {
            "generated_ts": data.get("generated_ts"),
            "hard": data.get("hard", {}),
            "soft": data.get("soft", {}),
            "probation": data.get("probation", {}),
        }
    except Exception as e:
        log.error(f"load_blocklist: {e}")
        return empty


def is_pair_blocked(pair: str, blocklist: dict, side: str = "SHORT") -> bool:
    """True if this pair+side is in the HARD block set. Fails open (False)."""
    try:
        key = f"{pair.split('/')[0]}_{side.upper()}"
        return key in (blocklist or {}).get("hard", {})
    except Exception:
        return False


def is_pair_probation(pair: str, blocklist: dict, side: str = "SHORT") -> bool:
    """True if this pair+side is in the PROBATION (watch) tier."""
    try:
        key = f"{pair.split('/')[0]}_{side.upper()}"
        return key in (blocklist or {}).get("probation", {})
    except Exception:
        return False


def _probation_defaults(blocked_at: str | None = None) -> dict:
    p = dict(_DEFAULT_PROBATION)
    if blocked_at:
        p["blocked_at"] = blocked_at
    return p


def evaluate_lifecycle(prev: dict, stats: dict, now=None) -> dict:
    """Advance the blocklist lifecycle: HARD→PROBATION→UNBLOCK / RE-BLOCK.

    Pure function (no I/O). Inputs:
      prev  — previously persisted blocklist (from load_blocklist)
      stats — current per-pair stats (from compute_pair_stats)
      now   — datetime (UTC); defaults to datetime.now(timezone.utc)

    Returns new {"hard":..,"soft":..,"probation":..,"unblocked":[...],"reblocked":[...]}
    where unblocked/reblocked carry human-readable reasons for alerting.
    """
    now = now or datetime.now(timezone.utc)
    hard = dict(prev.get("hard", {}))
    soft = dict(prev.get("soft", {}))
    prob = dict(prev.get("probation", {}))
    unblocked, reblocked = [], []

    # ── 1. Fresh HARD classification from current stats ─────────────────
    fresh = decide_blocks(stats)
    for key, info in fresh["hard"].items():
        if key in prob and prob[key].get("probation_start"):
            # Was on probation → now losing again → RE-BLOCK (record event)
            hard[key] = dict(info)
            reblocked.append(f"{key} (WR={info['wr']:.0%} n={info['n']})")
            log.warning(f"cex_pair_blocklist: {key} PROBATION→HARD re-block "
                        f"(WR={info['wr']:.0%})")
            # Reset probation bookkeeping for a future transition window
            prob[key] = _probation_defaults(blocked_at=now.isoformat(timespec="seconds"))
            prob[key]["_last_n"] = stats.get(key, {}).get("n", 0)
        elif key not in hard:
            hard[key] = dict(info)  # new block; probation bookkeeping starts
            prob[key] = _probation_defaults(blocked_at=now.isoformat(timespec="seconds"))
            prob[key]["_last_n"] = stats.get(key, {}).get("n", 0)
    # Soft tier: track but never block (alert-only)
    soft = fresh["soft"]

    # ── 2. HARD → PROBATION (cooldown + recovery) ─────────────────────
    for key in list(hard.keys()):
        pinfo = prob.get(key, _probation_defaults())
        blocked_at = pinfo.get("blocked_at")
        if not blocked_at:
            blocked_at = now.isoformat(timespec="seconds")
            pinfo["blocked_at"] = blocked_at
            prob[key] = pinfo
        try:
            bdt = datetime.fromisoformat(str(blocked_at))
            age_days = (now - bdt).total_seconds() / 86400.0
        except Exception:
            age_days = 0.0
        s = stats.get(key, {})
        recovered = (s.get("wr", 0) >= _PROBATION_RECOVER_WR
                     or s.get("avg_pct", -99) >= _PROBATION_RECOVER_AVG)
        if age_days >= _COOLDOWN_DAYS and recovered:
            prob[key] = {**pinfo, "probation_start": now.isoformat(timespec="seconds"),
                         "n_since": 0, "wins_since": 0, "pnl_since": 0.0,
                         "_last_n": s.get("n", 0)}
            del hard[key]
            log.info(f"cex_pair_blocklist: {key} HARD→PROBATION (cooldown "
                     f"{age_days:.0f}d, WR={s.get('wr',0):.0%})")

    # ── 3. PROBATION → UNBLOCK or RE-BLOCK ─────────────────────────────
    for key in list(prob.keys()):
        if key in hard:  # already handled above
            continue
        pinfo = prob[key]
        if not pinfo.get("probation_start"):
            continue
        s = stats.get(key, {})
        # Track new trades since probation started (using stored _last_n)
        cur_n = s.get("n", 0)
        last_n = pinfo.get("_last_n", 0)
        new_trades = max(0, cur_n - last_n)
        # Approximate wins among new trades from aggregate (conservative):
        # credit only if aggregate WR is healthy; else count 0 wins.
        new_wins = new_trades if s.get("wr", 0) >= _UNBLOCK_MIN_WR else 0
        n_since = pinfo.get("n_since", 0) + new_trades
        wins_since = pinfo.get("wins_since", 0) + new_wins
        prob[key] = {**pinfo, "n_since": n_since, "wins_since": wins_since,
                     "_last_n": cur_n}
        if s.get("wr", 0) < _REBLOCK_MAX_WR and s.get("n", 0) >= _SOFT_MIN_N:
            # turned losing again → back to HARD
            hard[key] = {"n": s.get("n"), "wr": s.get("wr"), "avg_pct": s.get("avg_pct")}
            del prob[key]
            reblocked.append(f"{key} (WR={s.get('wr',0):.0%} n={s.get('n')})")
            log.warning(f"cex_pair_blocklist: {key} PROBATION→HARD re-block "
                        f"(WR={s.get('wr',0):.0%})")
        elif n_since >= _UNBLOCK_MIN_N and wins_since / n_since >= _UNBLOCK_MIN_WR:
            del prob[key]
            unblocked.append(f"{key} (WR={wins_since/n_since:.0%} n={n_since})")
            log.info(f"cex_pair_blocklist: {key} PROBATION→UNBLOCK "
                     f"(WR={wins_since/n_since:.0%} n={n_since})")

    return {"hard": hard, "soft": soft, "probation": prob,
            "unblocked": unblocked, "reblocked": reblocked}


def refresh_blocklist(dbname: str = "anantara", path: Path | None = None) -> dict:
    """Full pipeline: stats → lifecycle → persist. Returns blocklist dict."""
    stats = compute_pair_stats(dbname)
    prev = load_blocklist(path)
    evolved = evaluate_lifecycle(prev, stats)
    save_blocklist(path, evolved["hard"], evolved["soft"], evolved["probation"])
    out = load_blocklist(path)
    out["_events"] = {"unblocked": evolved["unblocked"], "reblocked": evolved["reblocked"]}
    return out
