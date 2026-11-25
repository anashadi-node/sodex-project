#!/usr/bin/env python3
"""Batch 4 — query disesuaikan semantik arXiv (metadata-driven, hindari over-spesifik)."""
import sys, time, importlib.util, pathlib

HERE = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location("harvest", HERE / "harvest.py")
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)

QUERIES = [
    ("S_funding",     "funding rate perpetual"),
    ("S_basis",       "cryptocurrency futures basis"),
    ("S_micro",       "cryptocurrency market microstructure"),
    ("S_hl",          "Hyperliquid market impact adverse selection"),
    ("S_arb_dex",     "arbitrage decentralized exchange"),
    ("S_liquidity",   "liquidity provision automated market maker"),
    ("C_momentum",    "time series momentum cryptocurrency"),
    ("C_regime",      "regime switching volatility forecasting"),
    ("C_sizing",      "position sizing Kelly criterion"),
    ("C_label",       "triple barrier labeling"),
    ("C_walkfwd",     "walk forward backtest overfitting"),
    ("C_exec",        "optimal execution algorithmic trading"),
    ("C_lstm",        "LSTM cryptocurrency price forecasting"),
    ("C_xai",         "explainable machine learning finance"),
]

n = int(sys.argv[1]) if len(sys.argv) > 1 else 4
for tag, q in QUERIES:
    print("=" * 8, tag, "|", q)
    try:
        H.arxiv(q, n)
    except Exception as e:
        print("  ERR", type(e).__name__, str(e)[:110])
    time.sleep(3)
