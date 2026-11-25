#!/usr/bin/env python3
"""ANANTARA SAKTI — SoDEX funding collector (F2, 2026-06-29).

SoDEX exposes funding only via per-account /fundings history REST (no public per-pair
endpoint, unlike Binance). This collector polls that, computes realized funding rate
per pair per 1h interval, and ranks pairs by funding magnitude to surface
funding-squeeze signals.

Edge thesis (validated by E2_RESEARCH §12, n=30 WR 63.3%):
  - Over-funded pair (LONG holders PAY) → SHORT receives funding → squeeze SHORT.
  - Under-funded pair (SHORT holders PAY) → LONG receives funding → squeeze LONG.
This module = DATA layer only (signal + paper execution wired separately, F2 phase 2).

Usage:
  python3 anantara/sodex_funding_collector.py collect   # poll REST, persist JSONL
  python3 anantara/sodex_funding_collector.py signals    # rank current squeeze signals
"""
from __future__ import annotations
import json
import logging
import os
import time
from decimal import Decimal as D
from pathlib import Path

import requests

LOG = logging.getLogger("sodex_funding")

SODEX_BASE = os.environ.get("SODEX_BASE_URL", "https://mainnet-gw.sodex.dev")
SODEX_ADDR = os.environ.get("SODEX_ADDRESS", "")
DATA_DIR = Path(os.environ.get("SODEX_FUNDING_DIR", "data/sodex_funding"))
FUNDING_JSONL = DATA_DIR / "funding_history.jsonl"
SIGNALS_JSON = DATA_DIR / "funding_signals_latest.json"

# Signal threshold: funding fee magnitude must exceed this to be actionable.
# SPCX observed ~0.00279/h; CHZ ~0.000006/h (noise). Threshold 0.0005/h filters noise.
MIN_FUNDING_STRENGTH = float(os.environ.get("TE_FUNDING_MIN_STRENGTH", "0.0005"))

# ponytail: poll cadence — SoDEX funding settles every 3600s (1h). Polling every 15 min
# catches each settlement without hammering. Upgrade to websocket if SoDEX exposes one.
POLL_INTERVAL_S = int(os.environ.get("TE_FUNDING_POLL_S", "900"))


# ══════════════════════════════════════════════════════════════
# DATA LAYER — parse + fetch
# ══════════════════════════════════════════════════════════════
def parse_funding_history(resp: dict | None) -> list[dict]:
    """Parse /fundings REST response into normalized rows.
    Returns [{pair, side, fee, coin, ts, pos_id}, ...] or [] on null/empty.
    fee sign convention: positive = holder RECEIVES funding; negative = holder PAYS.
    """
    if not resp:
        return []
    data = resp.get("data") if isinstance(resp, dict) else resp
    if not data:
        return []
    rows = []
    for d in data:
        try:
            rows.append({
                "pair": d.get("symbol", ""),
                "side": d.get("positionSide", ""),
                "fee": D(str(d.get("fundingFee", "0"))),
                "coin": d.get("feeCoin", ""),
                "ts": int(d.get("timestamp", 0)),
                "pos_id": d.get("positionID"),
            })
        except (ValueError, TypeError, KeyError) as e:
            LOG.debug("skip malformed funding row %s: %s", d, e)
    return rows


def fetch_funding_history(address: str, base: str = SODEX_BASE,
                          limit: int = 50, timeout: int = 15) -> list[dict]:
    """Fetch per-account funding history from SoDEX REST.
    Public-ish endpoint (needs account addr, no signing). Returns parsed rows or []."""
    if not address:
        LOG.warning("fetch_funding_history: no SODEX_ADDRESS set")
        return []
    url = f"{base}/api/v1/perps/accounts/{address}/fundings"
    try:
        r = requests.get(url, params={"limit": limit}, timeout=timeout)
        if r.status_code != 200:
            LOG.warning("funding history HTTP %s for %s", r.status_code, address[:10])
            return []
        return parse_funding_history(r.json())
    except (requests.RequestException, ValueError) as e:
        LOG.warning("funding history fetch exc: %s", e)
        return []


# ══════════════════════════════════════════════════════════════
# SIGNAL LAYER — derive funding-squeeze direction per pair
# ══════════════════════════════════════════════════════════════
def funding_signal(pair: str, fee_rows: list[tuple]) -> dict:
    """Derive funding-squeeze signal from a pair's fee rows.
    fee_rows: [(side, fee), ...] — typically latest 1h interval.
    Returns {pair, direction (long/short/None), strength, n}.
    Over-funded (LONG pays, fee<0 for LONG) → SHORT signal.
    Under-funded (SHORT pays, fee<0 for SHORT) → LONG signal.
    """
    if not fee_rows:
        return {"pair": pair, "direction": None, "strength": 0.0, "n": 0}
    # Aggregate: net funding received by each side
    long_net = sum(f for s, f in fee_rows if s == "LONG")
    short_net = sum(f for s, f in fee_rows if s == "SHORT")
    # If LONG holders pay (long_net<0) and SHORT receives (short_net>0) → over-funded → SHORT
    if short_net > 0 and long_net < 0:
        strength = abs(float(short_net))
        return {"pair": pair, "direction": "short",
                "strength": strength, "n": len(fee_rows)}
    if long_net > 0 and short_net < 0:
        strength = abs(float(long_net))
        return {"pair": pair, "direction": "long",
                "strength": strength, "n": len(fee_rows)}
    # Ambiguous or tiny → no signal
    strength = max(abs(float(long_net)), abs(float(short_net)))
    return {"pair": pair, "direction": None, "strength": strength, "n": len(fee_rows)}


def rank_signals(signals: list[dict], top_n: int = 5,
                 min_strength: float = MIN_FUNDING_STRENGTH) -> list[dict]:
    """Rank pairs by funding magnitude, filter noise below min_strength."""
    viable = [s for s in signals if s["strength"] >= min_strength]
    return sorted(viable, key=lambda s: s["strength"], reverse=True)[:top_n]


def compute_all_signals(rows: list[dict]) -> list[dict]:
    """Group funding rows by pair (latest interval), compute signal per pair."""
    by_pair: dict[str, list[tuple]] = {}
    for r in rows:
        p = r["pair"]
        by_pair.setdefault(p, []).append((r["side"], r["fee"]))
    return [funding_signal(p, fees) for p, fees in by_pair.items()]


# ══════════════════════════════════════════════════════════════
# PERSISTENCE + CLI
# ══════════════════════════════════════════════════════════════
def collect_once(address: str = SODEX_ADDR, base: str = SODEX_BASE) -> list[dict]:
    """One poll: fetch + persist JSONL + recompute signals. Returns rows."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rows = fetch_funding_history(address, base)
    ts = int(time.time())
    if rows:
        with open(FUNDING_JSONL, "a") as f:
            for r in rows:
                f.write(json.dumps({"collect_ts": ts, **{k: str(v) if isinstance(v, D) else v
                                                         for k, v in r.items()}}) + "\n")
        sigs = compute_all_signals(rows)
        ranked = rank_signals(sigs)
        with open(SIGNALS_JSON, "w") as f:
            json.dump({"ts": ts, "signals": ranked, "n_rows": len(rows)}, f, indent=2)
        LOG.info("funding collect: %d rows, %d signals, top=%s",
                 len(rows), len(ranked),
                 ranked[0]["pair"] if ranked else "none")
    return rows


def main():
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="SoDEX funding collector (F2)")
    p.add_argument("cmd", choices=["collect", "signals", "watch"])
    p.add_argument("--address", default=SODEX_ADDR)
    p.add_argument("--base", default=SODEX_BASE)
    args = p.parse_args()
    if args.cmd == "collect":
        collect_once(args.address, args.base)
    elif args.cmd == "signals":
        rows = fetch_funding_history(args.address, args.base)
        sigs = compute_all_signals(rows)
        for s in rank_signals(sigs):
            d = s['direction'] or "-"
            print(f"{s['pair']:16} dir={d:6} strength={s['strength']:.6f} n={s['n']}")
    elif args.cmd == "watch":
        LOG.info("funding collector watch: poll every %ds", POLL_INTERVAL_S)
        while True:
            try:
                collect_once(args.address, args.base)
            except Exception as e:
                LOG.error("collect exc: %s", e)
            time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
