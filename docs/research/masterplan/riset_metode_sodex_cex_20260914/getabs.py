#!/usr/bin/env python3
"""Ambil abstract paper prioritas -> simpan ke hits.jsonl + cetak."""
import importlib.util, pathlib, time

HERE = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location("harvest", HERE / "harvest.py")
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)

PRIORITY = [
    ("P01", "2607.19453"),  # Audit model candle Binance spot
    ("P02", "2606.15715"),  # Hyperliquid market impact
    ("P03", "2608.21888"),  # short-horizon mean reversion crypto
    ("P04", "2609.05663"),  # LLM trading agents production
    ("P05", "2607.11888"),  # adaptive market making perp
    ("P06", "2602.11708"),  # trend-following adaptive portfolio crypto
    ("P07", "2606.00071"),  # BTC prediction meta-review
    ("P08", "2606.09478"),  # vol forecasting + return under regimes
    ("P09", "2606.30037"),  # output heads fat-tailed returns
    ("P10", "2609.37963"),  # AMM LP active-passive gap
    ("P11", "2608.19389"),  # CLP reinforcement learning
    ("P12", "2609.14481"),  # high-frequency swapping Arbitrum
]

for tag, aid in PRIORITY:
    print("=" * 10, tag, aid)
    try:
        H.absx(aid)
    except Exception as e:
        print("  ERR", type(e).__name__, str(e)[:120])
    print()
    time.sleep(2)
