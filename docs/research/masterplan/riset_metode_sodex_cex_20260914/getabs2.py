#!/usr/bin/env python3
import importlib.util, pathlib, time
HERE = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location("harvest", HERE / "harvest.py")
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)

PRIORITY = [
    ("P13", "2607.09426"),  # Quarter-Hour Effect crypto futures
    ("P14", "2607.09230"),  # When Does Order Flow Matter? L2 states
    ("P15", "2603.09164"),  # Slippage-at-Risk perp exchanges
    ("P16", "2609.04917"),  # AI in Equity and Crypto Markets meta-review
    ("P17", "2602.00776"),  # Explainable Patterns in Crypto Microstructure
    ("P18", "1701.03960"),  # Optimal Trading with Trailing Stop
    ("P19", "2109.10662"),  # Cointegration pairs trading crypto
    ("P20", "2607.27070"),  # criticality early-warning crypto perpetual
    ("P21", "2412.18405"),  # GMADL directional loss
    ("P22", "2606.29347"),  # Adaptive Financial Transformer regime-gated
    ("P23", "2608.23808"),  # MinervaScore robustness grade
    ("P24", "2209.05559"),  # DRL crypto backtest overfitting
]
for tag, aid in PRIORITY:
    print("=" * 10, tag, aid)
    try:
        H.absx(aid)
    except Exception as e:
        print("  ERR", type(e).__name__, str(e)[:120])
    print()
    time.sleep(2)
