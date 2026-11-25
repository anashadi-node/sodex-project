#!/usr/bin/env python3
"""Batch 5 — klaster lanjutan."""
import sys, time, importlib.util, pathlib

HERE = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location("harvest", HERE / "harvest.py")
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)

QUERIES = [
    ("E01_trailing_stop",   "trailing stop loss optimization"),
    ("E02_bracket_exit",    "take profit stop loss asymmetric exit"),
    ("E03_holding_period",  "optimal holding period trading signal"),
    ("R01_vol_scaling",     "volatility scaling risk parity portfolio"),
    ("R02_deflated_sharpe", "deflated Sharpe ratio multiple testing"),
    ("R03_backtest_overfit","backtest overfitting probability"),
    ("R04_liquidation",     "liquidation cascade crypto derivatives"),
    ("R05_drawdown",        "drawdown control risk management trading"),
    ("V01_hyperliquid",     "Hyperliquid perpetual decentralized"),
    ("V02_binance_futures", "Binance futures order flow"),
    ("V03_perp_dex",        "perpetual decentralized exchange design"),
    ("V04_funding_signal",  "funding rate sentiment predictor"),
    ("M01_ensemble",        "ensemble learning financial forecasting"),
    ("M02_purged_cv",       "purged cross validation financial machine learning"),
    ("M03_regime_ml",       "market regime classification machine learning trading"),
    ("M04_feature_eng",     "feature engineering financial time series"),
]

n = int(sys.argv[1]) if len(sys.argv) > 1 else 4
for tag, q in QUERIES:
    print("=" * 8, tag, "|", q)
    try:
        H.arxiv(q, n)
    except Exception as e:
        print("  ERR", type(e).__name__, str(e)[:110])
    time.sleep(3)
