#!/usr/bin/env python3
"""Counterfactual replay: LONG-only paper tracks + BTC regime gate at entry.

Question: if entries were only allowed in BTC BULL regime (CEX v2.8 btc_regime
pattern: close>SMA200 AND 24h momentum>0), how would REALWIDE and TWO-WAY
perform? This is evidence for/against a regime gate before any live decision.
Read-only; writes reports/SODEX_REGIME_COUNTERFACTUAL_2026-09-15.json.
"""
import collections
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]


def btc_daily(n=260):
    url = (f"https://api.binance.com/api/v3/klines?"
           f"symbol=BTCUSDT&interval=1d&limit={n}")
    rows = json.loads(urllib.request.urlopen(url, timeout=20).read())
    out = []
    for r in rows:
        out.append({
            "ts": datetime.fromtimestamp(r[0] / 1000, timezone.utc),
            "close": float(r[4]),
        })
    return out


def regime_series(bars, sma_len=200, mom_h=24):
    """Regime per day: BULL close>SMA & mom>0; BEAR close<SMA & mom<0; else CHOP.
    mom is 24h ≈ 1 day for daily bars (CEX v2.8 uses mom24h)."""
    closes = [b["close"] for b in bars]
    out = []
    for i, b in enumerate(bars):
        if i < sma_len:
            out.append((b["ts"], "WARMUP", None))
            continue
        sma = sum(closes[i - sma_len:i]) / sma_len
        mom = closes[i] / closes[i - 1] - 1 if i > 0 else 0.0
        if b["close"] > sma and mom > 0:
            reg = "BULL"
        elif b["close"] < sma and mom < 0:
            reg = "BEAR"
        else:
            reg = "CHOP"
        out.append((b["ts"], reg, mom))
    return out


def regime_at(series, ts):
    reg = None
    for t, r, _m in series:
        if t <= ts:
            reg = r
        else:
            break
    return reg or "WARMUP"


def load_tracks():
    tracks = {}
    rw = json.load(open(PROJ / "data/paper_test_realwide_state.json"))["closed"]
    tracks["REALWIDE"] = [(t["entry_iso"], t) for t in rw if t.get("entry_iso")]
    tw = [json.loads(x) for x in open(PROJ / "data/paper_test_twoway.jsonl") if x.strip()]
    tracks["TWO-WAY"] = [(t["entry_time"], t) for t in tw if t.get("entry_time")]
    return tracks


def net(t):
    return float(t.get("pnl_usd", 0) or 0)


def main():
    bars = btc_daily()
    series = regime_series(bars)
    tracks = load_tracks()
    report = {"generated": datetime.now(timezone.utc).isoformat(),
              "design": "LONG entry allowed only in BTC BULL (CEX v2.8 pattern)",
              "tracks": {}}
    for name, trades in tracks.items():
        base_n = len(trades)
        base_net = sum(net(t) for _ts, t in trades)
        per_regime = collections.defaultdict(lambda: {"n": 0, "net": 0.0, "wins": 0})
        for ts, t in trades:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            reg = regime_at(series, dt)
            per_regime[reg]["n"] += 1
            per_regime[reg]["net"] += net(t)
            if net(t) > 0:
                per_regime[reg]["wins"] += 1
        gated = per_regime.get("BULL", {"n": 0, "net": 0.0, "wins": 0})
        avoided = {r: v for r, v in per_regime.items() if r != "BULL"}
        report["tracks"][name] = {
            "baseline": {"n": base_n, "net_usd": round(base_net, 2)},
            "per_regime": {r: {"n": v["n"], "net_usd": round(v["net"], 2),
                               "wr_pct": round(100 * v["wins"] / v["n"], 1)
                               if v["n"] else None}
                           for r, v in sorted(per_regime.items())},
            "gated_bull_only": {"n": gated["n"], "net_usd": round(gated["net"], 2),
                                "wr_pct": (round(100 * gated["wins"] / gated["n"], 1)
                                           if gated["n"] else None)},
            "avoided_net_usd": round(sum(v["net"] for v in avoided.values()), 2),
        }
    path = PROJ / "reports/SODEX_REGIME_COUNTERFACTUAL_2026-09-15.json"
    path.write_text(json.dumps(report, indent=1))
    print(json.dumps(report["tracks"], indent=1))
    print("wrote", path)


if __name__ == "__main__":
    main()
