#!/usr/bin/env python3
"""Mode A signal engine: daily Donchian-ensemble trend following, spot, long-only, no leverage.

Frozen spec (PRAREG-23b candidate):
  assets      : BTC, ETH, XAUT (BNB, LINK only in paper)
  lookbacks   : 5,10,20,30,60,90,150,250,360 days
  entry       : close_t > max(close_{t-L..t-1})
  stop        : max(prev stop, (max+min)/2 of closes over last L incl. t); exit if close_t < prev stop
  signal      : mean over lookbacks of in-position flags (0..1)
  weight      : signal * min(1, VT / vol90) / n_eligible ; VT = 0.50 ; vol90 = std(daily simple returns, 90d) * sqrt(365)
  eligible    : asset has >= 360 daily closes
  total cap   : sum(weights) <= 1 (no leverage)
  band        : trade an asset only if target==0 and holding>0, or |target-current| > 0.20 * max(target, 0.05)
  timing      : closes through UTC day t-1 give the target used during UTC day t (backtest trades at close of day t)

The engine is stateless: it recomputes everything from the full daily history each run (deterministic).
Provide history from at least 2017-08-17 for BTC/ETH (signals from that start are identical to full-history signals,
verified); XAUT from its own start (Coin Metrics 2020-01-25), eligible after 360 closes.

NOTE: fetch_binance_daily() was NOT executed in the build environment (network allowlist). Test it yourself first.
"""
import json, math, sys
import numpy as np
import pandas as pd

LOOKBACKS = [5, 10, 20, 30, 60, 90, 150, 250, 360]
VT = 0.50
BAND = 0.20
MIN_HIST = 360
VOL_WIN = 90


def donchian_signal(close: pd.Series) -> pd.Series:
    p = close.values.astype(float)
    n = len(p)
    out = np.zeros(n)
    for L in LOOKBACKS:
        inpos = False
        stop = -np.inf
        for t in range(L, n):
            hi_prev = p[t - L:t].max()
            w2 = p[t - L + 1:t + 1]
            mid = (w2.max() + w2.min()) / 2
            if not inpos:
                if p[t] > hi_prev:
                    inpos = True
                    stop = mid
            else:
                if p[t] < stop:
                    inpos = False
                    stop = -np.inf
                else:
                    stop = max(stop, mid)
            out[t] += 1.0 if inpos else 0.0
    return pd.Series(out / len(LOOKBACKS), index=close.index)


def target_history(closes: dict, vt: float = VT) -> pd.DataFrame:
    """Target weight decided at each daily close (index = that close's date)."""
    px = pd.DataFrame({k: v for k, v in closes.items()}).sort_index()
    sig = pd.DataFrame({k: donchian_signal(closes[k].dropna()) for k in closes}).reindex(px.index).fillna(0.0)
    ret = px.pct_change()
    vol = ret.rolling(VOL_WIN).std() * math.sqrt(365)
    elig = (px.notna().cumsum() >= MIN_HIST) & px.notna()
    n_el = elig.sum(axis=1).replace(0, np.nan)
    tgt = (sig * np.minimum(1.0, vt / vol)).where(elig, 0.0).div(n_el, axis=0).fillna(0.0)
    tot = tgt.sum(axis=1)
    return tgt.div(np.maximum(tot, 1.0), axis=0)


def latest_targets(closes: dict, vt: float = VT) -> dict:
    t = target_history(closes, vt)
    last = t.iloc[-1]
    return {"asof_close": str(t.index[-1].date()), "weights": {k: float(last[k]) for k in t.columns}}


def rebalance_orders(current: dict, target: dict, band: float = BAND) -> dict:
    """Weights are fractions of total equity. Returns signed trade fractions (+buy / -sell); {} entries omitted."""
    orders = {}
    for k, t in target.items():
        w = current.get(k, 0.0)
        diff = t - w
        if (t == 0 and w > 0) or abs(diff) > band * max(t, 0.05):
            orders[k] = diff
    return orders


def fetch_binance_daily(symbol: str, start_ms: int = 1502928000000) -> pd.Series:
    """Daily closes (UTC) from Binance public klines; drops the still-open current day. UNTESTED in build env."""
    import urllib.request
    rows, cur = [], start_ms
    while True:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&startTime={cur}&limit=1000"
        with urllib.request.urlopen(url, timeout=30) as r:
            batch = json.loads(r.read())
        if not batch:
            break
        rows += batch
        cur = batch[-1][6] + 1
        if len(batch) < 1000:
            break
    s = pd.Series({pd.Timestamp(x[0], unit="ms").normalize(): float(x[4]) for x in rows}).sort_index()
    today = pd.Timestamp.utcnow().tz_localize(None).normalize()
    return s[s.index < today]


def load_csv(path: str) -> pd.Series:
    d = pd.read_csv(path, parse_dates=[0])
    d = d.set_index(d.columns[0]).iloc[:, 0].astype(float).sort_index()
    return d[~d.index.duplicated(keep="last")]


if __name__ == "__main__":
    # usage: mode_a_engine.py btc.csv eth.csv xaut.csv [current_weights.json]
    names = ["btc", "eth", "xaut"]
    closes = {n: load_csv(p) for n, p in zip(names, sys.argv[1:4])}
    res = latest_targets(closes)
    if len(sys.argv) > 4:
        cur = json.load(open(sys.argv[4]))
        res["orders"] = rebalance_orders(cur, res["weights"])
    print(json.dumps(res, indent=2))
