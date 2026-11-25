"""Ambil harian UTC: Binance (BTC,ETH,BNB,LINK -USDT) + Coin Metrics (xaut). Read-only."""
import json, urllib.request, pandas as pd, io, sys
def binance(sym, start_ms=1502928000000):
    rows, cur = [], start_ms
    while True:
        u = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=1d&startTime={cur}&limit=1000"
        b = json.loads(urllib.request.urlopen(u, timeout=30).read())
        if not b: break
        rows += b; cur = b[-1][6] + 1
        if len(b) < 1000: break
    s = pd.Series({pd.Timestamp(x[0], unit="ms"): float(x[4]) for x in rows}).sort_index()
    return s[s.index < pd.Timestamp.now("UTC").tz_localize(None).normalize()]
def cm(asset):
    u = f"https://raw.githubusercontent.com/coinmetrics/data/master/csv/{asset}.csv"
    d = pd.read_csv(io.BytesIO(urllib.request.urlopen(u, timeout=60).read()), usecols=["time", "PriceUSD"], parse_dates=["time"])
    d = d.dropna().set_index("time")["PriceUSD"].astype(float)
    d.index = d.index.tz_localize(None).normalize() if d.index.tz is not None else d.index.normalize()
    return d
out = {}
for k, sym in (("btc","BTCUSDT"),("eth","ETHUSDT"),("bnb","BNBUSDT"),("link","LINKUSDT")):
    out[k] = binance(sym)
for k in ("btc","eth","xaut"):
    out["cm_"+k] = cm(k)
for k, s in out.items():
    s.rename("close").to_csv(f"data/{k}.csv", index_label="date")
    full = pd.date_range(s.index[0], s.index[-1]); gaps = len(full.difference(s.index))
    print(f"{k:8} n={len(s):5} {s.index[0].date()}..{s.index[-1].date()} gaps={gaps} min={s.min():.4f} last={s.iloc[-1]:.2f} nonpos={(s<=0).sum()}")
