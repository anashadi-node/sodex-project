#!/usr/bin/env python3
"""Batch 6 — perluasan korpus."""
import sys, time, importlib.util, pathlib

HERE = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location("harvest", HERE / "harvest.py")
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)

QUERIES = [
    ("X01_vpin_toxicity",   "order flow toxicity VPIN"),
    ("X02_market_impact",   "market impact model metaorder"),
    ("X03_basis_stablecoin","stablecoin basis arbitrage"),
    ("X04_xsec_momentum",   "cross-sectional momentum factor"),
    ("X05_carry",           "carry trade futures basis"),
    ("X06_portfolio_crypto","cryptocurrency portfolio construction"),
    ("X07_execution_algo",  "execution algorithm TWAP VWAP"),
    ("X08_changepoint",     "change point detection financial"),
    ("X09_rl_execution",    "reinforcement learning execution"),
    ("X10_sentiment",       "sentiment news cryptocurrency returns"),
    ("X11_onchain",         "onchain metrics cryptocurrency returns"),
    ("X12_riskparity",      "risk parity allocation cryptocurrency"),
]
n = int(sys.argv[1]) if len(sys.argv) > 1 else 4
for tag, q in QUERIES:
    print("=" * 8, tag, "|", q)
    try:
        H.arxiv(q, n)
    except Exception as e:
        print("  ERR", type(e).__name__, str(e)[:110])
    time.sleep(3)
