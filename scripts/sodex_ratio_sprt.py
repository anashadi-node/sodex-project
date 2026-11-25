#!/usr/bin/env python3
"""U8 (2026-07-18): Sequential Probability Ratio Test (Wald SPRT) as the capital-scaling
gate — READ-ONLY, no orders, no capital.

The doctrine target is ">69% profitable transactions". Scaling capital on a lucky small
sample (e.g. 73% over 15 RTs) is exactly how Jul-17 happened. SPRT decides — with
bounded error (α, β) — whether the realized per-RT profitability is genuinely above the
target, using the SMALLEST sample that gives statistical confidence. Capital is scaled
ONLY when SPRT accepts H1; if it accepts H0 (below target) we stop and audit; otherwise
we keep collecting. This makes "scale up" a statistical decision, not a feeling.

    H0: p = p0   (below-target profitability — do NOT scale)
    H1: p = p1   (≥ target profitability — scaling justified)
    LLR_n = k·ln(p1/p0) + (n−k)·ln((1−p1)/(1−p0))       k = profitable RTs, n = total
    accept H1 if LLR ≥ A = ln((1−β)/α)                  → SCALE_OK
    accept H0 if LLR ≤ B = ln(β/(1−α))                  → STOP_AUDIT
    else CONTINUE_COLLECT

Per-RT "profitable" = realized net_pnl > 0 (fees+spread included; positions flat between
RTs so no open-MTM leakage). This is the realized-profitability that both the >69% target
and the honest ratio depend on.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
TE_DB = PROJECT / "twin_engine.db"
OUT_FILE = PROJECT / "data" / "sodex_ratio_sprt.json"
STATE_FILE = PROJECT / "data" / "honest_ratio_experiment.json"  # reuse pilot baseline ts

# Hypotheses + error rates (tunable).
P0 = float(os.environ.get("SPRT_P0", "0.55"))   # below-target profitability
P1 = float(os.environ.get("SPRT_P1", "0.69"))   # doctrine target (>69% profitable)
ALPHA = float(os.environ.get("SPRT_ALPHA", "0.05"))  # P(scale | actually bad)
BETA = float(os.environ.get("SPRT_BETA", "0.05"))    # P(don't scale | actually good)


def sprt_binomial(k: int, n: int, p0: float = P0, p1: float = P1,
                  alpha: float = ALPHA, beta: float = BETA) -> dict:
    """PURE Wald SPRT for a Bernoulli parameter. k successes in n trials.

    Returns decision ∈ {SCALE_OK, STOP_AUDIT, CONTINUE_COLLECT} plus the log-likelihood
    ratio and the two Wald boundaries. Guards degenerate p0/p1."""
    p0 = min(max(p0, 1e-6), 1 - 1e-6)
    p1 = min(max(p1, 1e-6), 1 - 1e-6)
    a_bound = math.log((1 - beta) / alpha)     # upper: accept H1
    b_bound = math.log(beta / (1 - alpha))     # lower: accept H0
    if n <= 0:
        llr = 0.0
    else:
        llr = (k * math.log(p1 / p0)
               + (n - k) * math.log((1 - p1) / (1 - p0)))
    if llr >= a_bound:
        decision = "SCALE_OK"
    elif llr <= b_bound:
        decision = "STOP_AUDIT"
    else:
        decision = "CONTINUE_COLLECT"
    return {
        "k": k, "n": n, "wr": round(k / n, 4) if n else None,
        "p0": p0, "p1": p1, "alpha": alpha, "beta": beta,
        "llr": round(llr, 4),
        "accept_h1_at": round(a_bound, 4),
        "accept_h0_at": round(b_bound, 4),
        "decision": decision,
    }


def _baseline_ts() -> str | None:
    try:
        return json.loads(STATE_FILE.read_text()).get("ts_start")
    except Exception:
        return None


def _pve_profitability(since_ts_iso: str | None) -> tuple:
    """(k, n) = (profitable PVE RTs, total PVE RTs) from the ledger since a timestamp."""
    if not TE_DB.exists():
        return 0, 0
    try:
        con = sqlite3.connect(f"file:{TE_DB}?mode=ro", uri=True, timeout=5)
        if since_ts_iso:
            row = con.execute(
                "SELECT COUNT(*), SUM(CASE WHEN CAST(net_pnl AS REAL)>0 THEN 1 ELSE 0 END) "
                "FROM rts WHERE engine='PVE' AND ts_close>=?", (since_ts_iso,)).fetchone()
        else:
            row = con.execute(
                "SELECT COUNT(*), SUM(CASE WHEN CAST(net_pnl AS REAL)>0 THEN 1 ELSE 0 END) "
                "FROM rts WHERE engine='PVE'").fetchone()
        con.close()
        n = int(row[0] or 0); k = int(row[1] or 0)
        return k, n
    except Exception:
        return 0, 0


def compute(scope: str = "pilot") -> dict:
    """scope 'pilot' = since honest-ratio baseline; 'all' = all PVE history."""
    since = _baseline_ts() if scope == "pilot" else None
    k, n = _pve_profitability(since)
    res = sprt_binomial(k, n)
    res.update({"ts": datetime.now(timezone.utc).isoformat(), "scope": scope,
                "since": since})
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(res, indent=2))
    return res


def _tg_send(msg: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return False
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception:
        return False


def _fmt(res: dict) -> str:
    icon = {"SCALE_OK": "🟢", "STOP_AUDIT": "🔴", "CONTINUE_COLLECT": "🟡"}[res["decision"]]
    return (f"{icon} SPRT SCALING GATE [{res['scope']}]\n"
            f"WR={res['wr'] if res['wr'] is not None else 'n/a'} "
            f"(k={res['k']}/n={res['n']})\n"
            f"H0 p≤{res['p0']} vs H1 p≥{res['p1']} (α=β={res['alpha']})\n"
            f"LLR={res['llr']}  [H1≥{res['accept_h1_at']} · H0≤{res['accept_h0_at']}]\n"
            f"→ {res['decision']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="U8 SPRT capital-scaling gate (read-only)")
    ap.add_argument("--scope", choices=["pilot", "all"], default="pilot")
    ap.add_argument("--report", action="store_true", help="send Telegram")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    res = compute(args.scope)
    if args.json:
        print(json.dumps(res, indent=2))
    elif args.report:
        print(f"report sent: {_tg_send(_fmt(res))}")
    else:
        print(_fmt(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
