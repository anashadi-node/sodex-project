#!/usr/bin/env python3
"""Ambil data PUBLIK untuk studi leverage: OHLC harian Binance (BTC, ETH) + funding historis Binance USDM. Read-only, cache CSV."""
import json, os, time, urllib.request, pandas as pd
D = os.path.dirname(os.path.abspath(__file__))
H = {"User-Agent": "Mozilla/5.0"}
def get(u):
    for i in range(4):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=30))
        except Exception as e: time.sleep(3 * (i + 1)); err = e
    raise err
def ohlc(sym):
    out, st = [], 1502928000000
    while True:
        k = get(f"https://data-api.binance.vision/api/v3/klines?symbol={sym}&interval=1d&limit=1000&startTime={st}")
        if not k: break
        out += k; st = k[-1][0] + 86400000
        if len(k) < 1000: break
        time.sleep(0.5)
    df = pd.DataFrame(out).iloc[:, :5]; df.columns = ["t", "open", "high", "low", "close"]
    df["date"] = pd.to_datetime(df.t, unit="ms").dt.normalize(); df = df.drop(columns="t").set_index("date").astype(float)
    return df[~df.index.duplicated()]
def funding(sym):
    out, st = [], 1567000000000
    while True:
        k = get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&limit=1000&startTime={st}")
        if not k: break
        out += k; st = k[-1]["fundingTime"] + 1
        if len(k) < 1000: break
        time.sleep(0.5)
    df = pd.DataFrame(out); df["t"] = pd.to_datetime(df.fundingTime, unit="ms"); df["rate_bps"] = df.fundingRate.astype(float) * 1e4
    return df.set_index("t")["rate_bps"]
if __name__ == "__main__":
  for s, n in (("BTCUSDT", "btc"), ("ETHUSDT", "eth")):
      o = ohlc(s); o.to_csv(f"{D}/{n}_ohlc.csv"); f = funding(s); f.to_csv(f"{D}/{n}_funding_binance.csv")
      print(n, len(o), o.index[0].date(), o.index[-1].date(), "| funding", len(f), f.index[0].date(), f.index[-1].date(), "mean bps/8h", round(f.mean(), 3))
