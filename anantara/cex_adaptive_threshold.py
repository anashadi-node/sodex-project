#!/usr/bin/env python3
"""
ANANTARA SAKTI — CEX Adaptive Threshold (v1.0, 2026-08-23)
Per-pair adaptive threshold multiplier for Perbaikan #4 (v8.7).

What it does:
  Reads the last _ROLLING_N closed trades per pair from PostgreSQL,
  computes WR and expectancy, and writes a JSON multiplier file.

Multiplier rules (falsification-first, min n required):
  WR < 40%  → mult ×1.30  (pair underperforming, stricter threshold)
  WR > 65%  → mult ×0.85  (pair outperforming, looser threshold)
  Otherwise → mult ×1.00  (neutral)

Output: data/binance/cex_adaptive_thresholds.json
  {"BTC": {"mult": 1.0, "wr": 0.62, "n": 12}, ...}

Runs via daemon job_cex_adaptive_threshold every 2h.
Pure stdlib + psycopg2 (same daemon env as cex_deep_loop.py).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_ROLLING_N = 10          # last N closed trades per pair
_MIN_N = 4               # minimum n before applying multiplier (K9: lowered 6→4, early signal)
_WR_UNDERPERFORM = 0.40  # below this → stricter
_WR_OUTPERFORM = 0.65    # above this → looser
_MULT_STRICT = 1.30
_MULT_LOOSE = 0.85
_RECENT_DAYS = 7         # K9: trades within this window weighted 2× (time-decay)
_OUTPUT_FILE = "freqtrade_user_data/data/binance/cex_adaptive_thresholds.json"


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


def _resolve_output_path() -> Path:
    cwd = Path(os.environ.get("FREQTRADE_WORKDIR", "/home/USER/anantara-sakti"))
    p = cwd / _OUTPUT_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def compute_adaptive_thresholds() -> dict:
    """Query PostgreSQL for per-pair WR and return multiplier dict.

    K9 (v8.7): time-decay weighting — trades from last _RECENT_DAYS counted 2×.
    This makes the multiplier more responsive to recent regime shifts without
    waiting for _ROLLING_N trades (especially important for pairs with 4-6 trades).
    """
    result: dict[str, dict] = {}
    try:
        conn = _get_pg_conn("anantara")
    except Exception as e:
        log.warning(f"[adaptive_thr] DB connect failed: {e}")
        return result

    try:
        from collections import defaultdict
        from datetime import datetime, timezone, timedelta
        cur = conn.cursor()
        # K9: include close_date for time-decay weighting
        cur.execute("""
            SELECT
                pair,
                close_profit,
                close_date
            FROM trades
            WHERE strategy LIKE '%%AnantaraTrendFocused%%'
              AND is_open = FALSE
              AND close_date IS NOT NULL
            ORDER BY close_date DESC
            LIMIT 2000
        """)
        rows = cur.fetchall()

        now = datetime.now(timezone.utc)
        recent_cutoff = now - timedelta(days=_RECENT_DAYS)

        # Group by pair, take last _ROLLING_N, store (pnl, is_recent)
        per_pair: dict[str, list[tuple[float, bool]]] = defaultdict(list)
        for pair, close_profit, close_date in rows:
            coin = pair.split("/")[0] if "/" in pair else pair
            if close_profit is not None and len(per_pair[coin]) < _ROLLING_N:
                # Normalize datetime timezone for comparison
                cd = close_date
                if hasattr(cd, 'tzinfo') and cd.tzinfo is None:
                    cd = cd.replace(tzinfo=timezone.utc)
                is_recent = (cd >= recent_cutoff) if cd else False
                per_pair[coin].append((float(close_profit), is_recent))

        for coin, entries in per_pair.items():
            n = len(entries)
            if n < _MIN_N:
                result[coin] = {"mult": 1.0, "wr": None, "n": n, "reason": "insufficient_n"}
                continue

            # K9: time-decay WR — recent trades weight 2x, older weight 1x
            weighted_wins = 0.0
            weighted_n = 0.0
            raw_wins = 0
            for pnl, is_recent in entries:
                w = 2.0 if is_recent else 1.0
                if pnl > 0:
                    weighted_wins += w
                    raw_wins += 1
                weighted_n += w
            wr = weighted_wins / weighted_n if weighted_n > 0 else (raw_wins / n)

            if wr < _WR_UNDERPERFORM:
                mult = _MULT_STRICT
                reason = f"underperform WR={wr:.1%} (time-decay)"
            elif wr > _WR_OUTPERFORM:
                mult = _MULT_LOOSE
                reason = f"outperform WR={wr:.1%} (time-decay)"
            else:
                mult = 1.0
                reason = f"neutral WR={wr:.1%}"
            result[coin] = {
                "mult": mult, "wr": round(wr, 3), "n": n,
                "n_recent": sum(1 for _, r in entries if r),
                "reason": reason,
            }
            log.info(f"[adaptive_thr] {coin}: mult={mult:.2f} n={n} WR={wr:.1%} ({reason})")

    except Exception as e:
        log.warning(f"[adaptive_thr] query error: {e}")
    finally:
        conn.close()

    return result


def run() -> dict:
    """Main entry: compute + write + return result dict."""
    data = compute_adaptive_thresholds()
    out_path = _resolve_output_path()
    payload = {
        "generated_ts": datetime.now(timezone.utc).isoformat(),
        "rolling_n": _ROLLING_N,
        "min_n": _MIN_N,
        "pairs": data,
    }
    try:
        tmp = out_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(out_path)
        log.info(f"[adaptive_thr] wrote {len(data)} pairs → {out_path}")
    except Exception as e:
        log.warning(f"[adaptive_thr] write failed: {e}")
    return payload


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import pprint
    pprint.pprint(run())
