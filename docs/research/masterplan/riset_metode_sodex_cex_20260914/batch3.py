#!/usr/bin/env python3
"""Batch driver: jalankan N query arXiv berurutan dengan jeda sopan."""
import sys, time, importlib.util, pathlib

HERE = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location("harvest", HERE / "harvest.py")
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)

QUERIES = [
    # --- S: SoDEX (DEX perps, microstructure, funding, swing 1-30h) ---
    ("S1_funding_arb",        "funding rate arbitrage perpetual futures profitability"),
    ("S2_basis_trade",        "basis trade cash and carry cryptocurrency futures premium"),
    ("S3_orderflow_crypto",   "order flow imbalance cryptocurrency price prediction"),
    ("S4_lob_deeplearning",   "deep learning limit order book mid price prediction"),
    ("S5_dex_amm_perp",       "decentralized exchange perpetual futures automated market maker"),
    ("S6_mev_liquidity",      "maximal extractable value liquidity arbitrage decentralized exchange"),
    # --- C: CEX-Binance (swing, ML, regime, sizing, execution) ---
    ("C1_intraday_momentum",  "intraday momentum cryptocurrency returns horizon hours"),
    ("C2_regime_switching",   "markov switching regime cryptocurrency volatility trading"),
    ("C3_vol_targeting",      "volatility targeting position sizing time series momentum"),
    ("C4_meta_labeling",      "meta labeling triple barrier financial machine learning"),
    ("C5_optimal_execution",  "optimal execution market impact limit orders"),
    ("C6_rl_trading",         "deep reinforcement learning trading cryptocurrency out of sample"),
]

n = int(sys.argv[1]) if len(sys.argv) > 1 else 4
for tag, q in QUERIES:
    print("=" * 8, tag)
    try:
        H.arxiv(q, n)
    except Exception as e:
        print("  ERR", type(e).__name__, str(e)[:120])
    time.sleep(3)
