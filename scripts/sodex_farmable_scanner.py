#!/usr/bin/env python3
"""U7 (2026-07-18): SoDEX farmable-pair scanner — READ-ONLY, no orders, no capital.

Purpose: the maker-volume target ($1.3M/wk profitably) is impossible on tight-spread
perps (SOL/BTC/ETH spread < 2.4 bps maker RT fee → every maker RT loses). Profitable
maker farming lives on WIDE-spread pairs — but a wide spread with a thin book is a trap
(can't actually fill, and any fill is adverse). This scanner ranks the live perps
universe by *net capture after fee* AND *liquidity*, so we only ever point PVE at pairs
that are genuinely farmable-profitable.

One call to /perps/markets/tickers returns all pairs with bidPx/askPx/bidSz/askSz/
quoteVolume/fundingRate — no per-pair orderbook calls needed. Pure ranking logic is
separated from IO so it is deterministically unit-tested.

    farmable  ⟺  net_capture_bps ≥ MIN_NET_CAPTURE_BPS
                 AND quoteVolume_24h ≥ MIN_QVOL_USD
                 AND L1_depth_usd    ≥ MIN_L1_DEPTH_USD

where net_capture_bps = spread_bps − rt_fee_bps  (rt_fee = 2×maker_fee).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

OUT_FILE = PROJECT / "data" / "sodex_farmable_pairs.json"

# Maker round-trip fee in bps (0.012%/side × 2 × 100). Matches PVE_MAKER_FEE_PCT.
DEFAULT_RT_FEE_BPS = float(os.environ.get("PVE_MAKER_FEE_RT_BPS", "2.4"))
# Farmable thresholds (tunable via env).
MIN_NET_CAPTURE_BPS = float(os.environ.get("FARMABLE_MIN_NET_CAPTURE_BPS", "1.0"))
MIN_QVOL_USD = float(os.environ.get("FARMABLE_MIN_QVOL_USD", "10000"))
MIN_L1_DEPTH_USD = float(os.environ.get("FARMABLE_MIN_L1_DEPTH_USD", "500"))


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def evaluate_pair(row: dict, rt_fee_bps: float = DEFAULT_RT_FEE_BPS,
                  min_net_capture: float = MIN_NET_CAPTURE_BPS,
                  min_qvol: float = MIN_QVOL_USD,
                  min_l1_depth: float = MIN_L1_DEPTH_USD) -> dict:
    """PURE: metrics + farmable verdict for one ticker row.

    L1 depth = min(bid_notional, ask_notional) — the binding side for a round-trip.
    score = net_capture_bps × (1 + log10(quoteVolume)) — rewards both capture and
    liquidity so a fat-spread illiquid trap (200 bps / $3k) never outranks a real
    farmable pair once it passes the liquidity floor."""
    sym = row.get("symbol", "")
    bid = _f(row.get("bidPx"))
    ask = _f(row.get("askPx"))
    bid_sz = _f(row.get("bidSz"))
    ask_sz = _f(row.get("askSz"))
    qvol = _f(row.get("quoteVolume"))
    funding = _f(row.get("fundingRate"))
    mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else 0.0
    spread_bps = ((ask - bid) / mid * 1e4) if mid > 0 else 0.0
    net_capture_bps = spread_bps - rt_fee_bps
    bid_notional = bid * bid_sz
    ask_notional = ask * ask_sz
    l1_depth_usd = min(bid_notional, ask_notional)
    obi = ((bid_sz - ask_sz) / (bid_sz + ask_sz)) if (bid_sz + ask_sz) > 0 else 0.0
    farmable = (net_capture_bps >= min_net_capture
                and qvol >= min_qvol
                and l1_depth_usd >= min_l1_depth
                and mid > 0)
    score = (net_capture_bps * (1 + math.log10(qvol)) if (farmable and qvol > 1) else 0.0)
    return {
        "symbol": sym,
        "mid": round(mid, 6),
        "spread_bps": round(spread_bps, 2),
        "net_capture_bps": round(net_capture_bps, 2),
        "qvol_24h_usd": round(qvol, 0),
        "l1_depth_usd": round(l1_depth_usd, 0),
        "obi": round(obi, 3),
        "funding_rate": funding,
        "farmable": farmable,
        "score": round(score, 1),
    }


def rank_farmable(rows: list, **kw) -> list:
    """PURE: evaluate all rows, return farmable ones sorted by score desc."""
    evals = [evaluate_pair(r, **kw) for r in rows if isinstance(r, dict)]
    farm = [e for e in evals if e["farmable"]]
    farm.sort(key=lambda e: -e["score"])
    return farm


def recommend_pairs(ranked: list, k: int = 3) -> str:
    """Top-k farmable symbols as a TE_PVE_PAIRS value."""
    return ",".join(e["symbol"] for e in ranked[:k])


# ── IO ──────────────────────────────────────────────────────────────────────
def fetch_perps_tickers() -> list:
    """Read-only /perps/markets/tickers via the live adapter env (no auth needed)."""
    try:
        import anantara.sodex_twin_engine as te
        c = te.SodexLiveAdapter(te.Config())
        j = c._api_get("/perps/markets/tickers")
        from anantara.sodex_twin_engine import _data_list
        rows = _data_list(j, "tickers") if isinstance(j, dict) else (j or [])
        return rows if isinstance(rows, list) else []
    except Exception as e:  # pragma: no cover — network/env dependent
        print(f"fetch error: {e}", file=sys.stderr)
        return []


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


def scan(write: bool = True) -> dict:
    rows = fetch_perps_tickers()
    ranked = rank_farmable(rows)
    result = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "universe_n": len(rows),
        "farmable_n": len(ranked),
        "rt_fee_bps": DEFAULT_RT_FEE_BPS,
        "thresholds": {"min_net_capture_bps": MIN_NET_CAPTURE_BPS,
                       "min_qvol_usd": MIN_QVOL_USD, "min_l1_depth_usd": MIN_L1_DEPTH_USD},
        "recommended_te_pve_pairs": recommend_pairs(ranked, 3),
        "farmable": ranked,
    }
    if write:
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUT_FILE.write_text(json.dumps(result, indent=2))
    return result


def _fmt_report(res: dict) -> str:
    lines = [f"🔎 SoDEX FARMABLE SCAN — {res['farmable_n']}/{res['universe_n']} pairs",
             f"floor: net≥{res['thresholds']['min_net_capture_bps']}bps "
             f"vol≥${res['thresholds']['min_qvol_usd']:,.0f} depth≥${res['thresholds']['min_l1_depth_usd']:,.0f}",
             "— — —"]
    for e in res["farmable"][:8]:
        lines.append(f"{e['symbol']:12s} net={e['net_capture_bps']:+.1f}bps "
                     f"vol=${e['qvol_24h_usd']:,.0f} depth=${e['l1_depth_usd']:,.0f}")
    lines.append("— — —")
    lines.append(f"→ TE_PVE_PAIRS={res['recommended_te_pve_pairs']}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="U7 SoDEX farmable-pair scanner (read-only)")
    ap.add_argument("--scan", action="store_true", help="scan + print table")
    ap.add_argument("--recommend", action="store_true", help="print TE_PVE_PAIRS line only")
    ap.add_argument("--report", action="store_true", help="send Telegram report")
    ap.add_argument("--json", action="store_true", help="print full JSON")
    args = ap.parse_args()

    res = scan(write=True)
    if args.recommend:
        print(f"TE_PVE_PAIRS={res['recommended_te_pve_pairs']}")
        return 0
    if args.json:
        print(json.dumps(res, indent=2))
        return 0
    if args.report:
        ok = _tg_send(_fmt_report(res))
        print(f"report sent: {ok}")
        return 0
    # default = table
    print(_fmt_report(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
