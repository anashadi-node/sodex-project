#!/usr/bin/env python3
"""Adaptive asset+direction selector for PVE — READ-ONLY, no orders.

User principle (2026-07-19): in ANY market there is always a trending asset where
farming WITH the trend makes the directional MTM a tailwind (positions win → offset
fee → honest ratio rises toward the fee ceiling). The job is to quickly + correctly
pick the asset(s) + direction to ride.

HONEST scope: this is TREND-FOLLOWING, not prediction. Calibration proved we have no
directional *predictive* edge — but riding an ALREADY-ESTABLISHED trend (momentum
persistence) is reaction, not forecast, and it tilts the MTM favorably more often than
trading against/agnostic to the trend. It cannot guarantee a tailwind in a choppy /
trendless regime (no clear trend → no edge → ratio stays fee-limited).

Pipeline: farmable universe (spread≥fee, liquid) → per-pair own momentum (EMA20/50 +
ROC on {base}USDT Binance klines) → rank by trend strength × farmability → output the
top-K pairs each with its WITH-TREND direction. Pure ranking is unit-tested.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

OUT_FILE = PROJECT / "data" / "sodex_adaptive_selection.json"
PVE_PAUSE_FILE = PROJECT / "data" / "PVE_PAUSE"
LEDGER_DB = PROJECT / "twin_engine.db"

RT_FEE_BPS = float(os.environ.get("PVE_MAKER_FEE_RT_BPS", "2.4"))
MIN_NET_CAPTURE_BPS = float(os.environ.get("ADAPT_MIN_NET_CAPTURE_BPS", "1.0"))
MIN_QVOL_USD = float(os.environ.get("ADAPT_MIN_QVOL_USD", "10000"))
MIN_L1_DEPTH_USD = float(os.environ.get("ADAPT_MIN_L1_DEPTH_USD", "500"))
ROC_TREND_THR = float(os.environ.get("ADAPT_ROC_THR", "0.3"))   # %1h to call a trend
TOP_K = int(os.environ.get("ADAPT_TOP_K", "3"))
RECOVERY_MIN_NET_CAPTURE_BPS = float(os.environ.get(
    "ADAPT_RECOVERY_MIN_NET_CAPTURE_BPS", "5.0"))
RECOVERY_PERF_LOOKBACK = int(os.environ.get("ADAPT_RECOVERY_PERF_LOOKBACK", "6"))
RECOVERY_MIN_RTS = int(os.environ.get("ADAPT_RECOVERY_MIN_RTS", "3"))


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


# ── PURE ─────────────────────────────────────────────────────────────────────
def momentum(closes: list, roc_thr: float = ROC_TREND_THR) -> dict:
    """Own-asset momentum → direction (long/short/neutral) + strength (dimensionless).
    strength = |ROC1h| + EMA-separation%%, only when EMA and ROC agree; else 0."""
    if len(closes) < 50:
        return {"direction": "neutral", "strength": 0.0, "roc1h": 0.0}

    def ema(data, period):
        k = 2 / (period + 1)
        e = data[0]
        for p in data[1:]:
            e = p * k + e * (1 - k)
        return e

    e20 = ema(closes[-20:], 20)
    e50 = ema(closes[-50:], 50)
    roc1 = (closes[-1] - closes[-2]) / closes[-2] * 100 if closes[-2] else 0.0
    roc3 = (closes[-1] - closes[-4]) / closes[-4] * 100 if len(closes) >= 4 and closes[-4] else 0.0
    ema_sep = (e20 - e50) / e50 * 100 if e50 else 0.0
    # The immediate 1h return must agree with the EMA direction. Previously a
    # strong 3h move could select LONG while roc1 was already negative (or SHORT
    # while positive), which is exactly the stale-turn entry recovery must avoid.
    up = e20 > e50 and roc1 >= 0 and (roc1 > roc_thr or roc3 > roc_thr * 1.5)
    down = e20 < e50 and roc1 <= 0 and (roc1 < -roc_thr or roc3 < -roc_thr * 1.5)
    if up:
        return {"direction": "long", "strength": abs(roc1) + abs(ema_sep), "roc1h": roc1}
    if down:
        return {"direction": "short", "strength": abs(roc1) + abs(ema_sep), "roc1h": roc1}
    return {"direction": "neutral", "strength": 0.0, "roc1h": roc1}


def farmable_metrics(row: dict) -> dict:
    bid = _f(row.get("bidPx")); ask = _f(row.get("askPx"))
    bsz = _f(row.get("bidSz")); asz = _f(row.get("askSz"))
    qv = _f(row.get("quoteVolume"))
    mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else 0.0
    spread_bps = ((ask - bid) / mid * 1e4) if mid > 0 else 0.0
    net = spread_bps - RT_FEE_BPS
    depth = min(bid * bsz, ask * asz)
    farmable = net >= MIN_NET_CAPTURE_BPS and qv >= MIN_QVOL_USD and depth >= MIN_L1_DEPTH_USD
    return {"symbol": row.get("symbol", ""), "net_capture_bps": round(net, 2),
            "qvol": qv, "l1_depth": round(depth, 0), "farmable": farmable}


def rank(farmable_list: list, momentum_by_sym: dict, top_k: int = TOP_K,
         *, recovery: bool = False, performance: dict | None = None) -> list:
    """Combine farmability + momentum → ranked with-trend selections.
    score = trend_strength × log10(qvol) × (1 + net_capture/10). Neutral excluded."""
    out = []
    performance = performance or {}
    for fm in farmable_list:
        if not fm["farmable"]:
            continue
        perf = performance.get(fm["symbol"], {})
        if recovery and fm["net_capture_bps"] < RECOVERY_MIN_NET_CAPTURE_BPS:
            continue
        if recovery and float(perf.get("last_pnl", 0.0)) < 0:
            continue
        if (recovery and int(perf.get("n", 0)) >= RECOVERY_MIN_RTS
                and float(perf.get("net_pnl", 0.0)) <= 0):
            continue
        m = momentum_by_sym.get(fm["symbol"], {"direction": "neutral", "strength": 0.0})
        if m["direction"] == "neutral" or m["strength"] <= 0:
            continue
        score = (m["strength"] * (1 + math.log10(max(fm["qvol"], 1)))
                 * (1 + fm["net_capture_bps"] / 10))
        out.append({"symbol": fm["symbol"], "direction": m["direction"],
                    "trend_strength": round(m["strength"], 3), "roc1h": round(m["roc1h"], 3),
                    "net_capture_bps": fm["net_capture_bps"], "qvol": round(fm["qvol"], 0),
                    "l1_depth": fm["l1_depth"], "score": round(score, 1),
                    "recent_rt_n": int(perf.get("n", 0)),
                    "recent_rt_net": round(float(perf.get("net_pnl", 0.0)), 6)})
    out.sort(key=lambda e: -e["score"])
    return out[:top_k]


# ── IO ───────────────────────────────────────────────────────────────────────
def _binance_closes(base: str) -> list:
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={base}USDT&interval=1h&limit=55"
        with urllib.request.urlopen(url, timeout=5) as r:
            return [float(c[4]) for c in json.loads(r.read())]
    except Exception:
        return []


def _normalize_systemd_environment() -> None:
    """Match shell `.env` inline-comment semantics for strategy settings."""
    prefixes = ("TE_", "PVE_", "ADAPT_", "HONEST_", "GUARDIAN_")
    for key, value in list(os.environ.items()):
        if key.startswith(prefixes) and "#" in value:
            os.environ[key] = value.split("#", 1)[0].rstrip()


def fetch_tickers() -> list:
    try:
        _normalize_systemd_environment()
        import anantara.sodex_twin_engine as te
        from anantara.sodex_twin_engine import _data_list
        c = te.SodexLiveAdapter(te.Config())
        j = c._api_get("/perps/markets/tickers")
        rows = _data_list(j, "tickers") if isinstance(j, dict) else (j or [])
        return rows if isinstance(rows, list) else []
    except Exception as e:  # pragma: no cover
        print(f"fetch err: {e}", file=sys.stderr)
        return []


def _load_previous() -> dict | None:
    try:
        value = json.loads(OUT_FILE.read_text())
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _honest_recovery_active() -> bool:
    try:
        pause = json.loads(PVE_PAUSE_FILE.read_text())
        return pause.get("source") == "sodex_honest_ratio_gate"
    except (OSError, ValueError):
        return False


def _allowed_pairs() -> set[str] | None:
    raw = os.environ.get("TE_PVE_PAIRS", "").split("#", 1)[0].strip()
    if not raw:
        return None
    return {item.strip() for item in raw.split(",") if item.strip()}


def _recent_pair_performance(limit: int = RECOVERY_PERF_LOOKBACK) -> dict[str, dict]:
    """Recent completed RT evidence per pair; unavailable DB fails open to cold-start."""
    grouped: dict[str, list[float]] = {}
    try:
        db = sqlite3.connect(str(LEDGER_DB))
        rows = db.execute(
            "SELECT pair, net_pnl FROM rts WHERE engine='PVE' "
            "ORDER BY ts_close DESC LIMIT 300"
        ).fetchall()
        db.close()
    except (OSError, sqlite3.Error):
        return {}
    for pair, raw_pnl in rows:
        values = grouped.setdefault(str(pair), [])
        if len(values) >= limit:
            continue
        try:
            values.append(float(raw_pnl))
        except (TypeError, ValueError):
            continue
    return {
        pair: {"n": len(values), "net_pnl": sum(values),
               "last_pnl": values[0] if values else 0.0}
        for pair, values in grouped.items()
    }


def _write_result(result: dict) -> None:
    """Replace selector output atomically so the live engine never reads partial JSON."""
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_FILE.with_suffix(OUT_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(result, indent=2))
    tmp.replace(OUT_FILE)


def select(top_k: int = TOP_K) -> dict:
    rows = fetch_tickers()
    if not rows:
        previous = _load_previous()
        if previous and previous.get("selected"):
            # Keep the original timestamp. The engine's max-age gate still expires
            # this last-known-good selection after a bounded grace period.
            return {
                **previous,
                "quality": "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD",
                "preserved_previous": True,
            }
        degraded = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "quality": "SOURCE_UNAVAILABLE",
            "preserved_previous": False,
            "universe_n": 0,
            "farmable_n": 0,
            "selected": [],
            "te_pve_pairs": "",
            "directions": {},
        }
        _write_result(degraded)
        return degraded
    allowed = _allowed_pairs()
    fmetrics = [farmable_metrics(r) for r in rows if isinstance(r, dict)]
    if allowed is not None:
        fmetrics = [item for item in fmetrics if item["symbol"] in allowed]
    farmable = [f for f in fmetrics if f["farmable"]]
    mom = {}
    for f in farmable:  # only compute momentum for farmable (bounded calls)
        base = f["symbol"].replace("-USD", "").replace("/", "")
        closes = _binance_closes(base)
        if closes:
            mom[f["symbol"]] = momentum(closes)
    recovery = _honest_recovery_active()
    performance = _recent_pair_performance() if recovery else {}
    ranked = rank(
        farmable, mom, top_k, recovery=recovery, performance=performance,
    )
    res = {"ts": datetime.now(timezone.utc).isoformat(), "quality": "OK",
           "preserved_previous": False, "universe_n": len(rows),
           "farmable_n": len(farmable), "selected": ranked,
           "recovery_mode": recovery,
           "recovery_min_net_capture_bps": RECOVERY_MIN_NET_CAPTURE_BPS,
           "te_pve_pairs": ",".join(e["symbol"] for e in ranked),
           "directions": {e["symbol"]: e["direction"] for e in ranked}}
    _write_result(res)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Adaptive asset+direction selector (read-only)")
    ap.add_argument("--select", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=TOP_K)
    args = ap.parse_args()
    res = select(args.top)
    if args.json:
        print(json.dumps(res, indent=2)); return 0
    print(f"🧭 ADAPTIVE SELECTOR — {res['farmable_n']}/{res['universe_n']} farmable, "
          f"{len(res['selected'])} trending")
    for e in res["selected"]:
        arrow = "📈LONG" if e["direction"] == "long" else "📉SHORT"
        print(f"  {e['symbol']:12s} {arrow} strength={e['trend_strength']:.2f} "
              f"roc1h={e['roc1h']:+.2f}% net={e['net_capture_bps']:+.1f}bps vol=${e['qvol']:,.0f}")
    print(f"→ TE_PVE_PAIRS={res['te_pve_pairs']}")
    print(f"→ directions={res['directions']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
