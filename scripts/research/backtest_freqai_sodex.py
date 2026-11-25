#!/usr/bin/env python3
"""
ANANTARA SAKTI — Walk-forward LightGBM (FreqAI-style) edge test on SoDEX data.

Trains the project's actual model (LightGBM) on SoDEX 1h history with the
v3.2 feature philosophy (9 indicators x periods [14,50] + basics), labels =
forward 24h return, and walk-forward validation (NO look-ahead, NO shuffle —
the project's hard rules). Reports whether ML predictions have directional edge.

This answers "does the FreqAI model have edge on SoDEX?" without the Freqtrade
backtest machinery (pair-naming / funding-data / identifier-collision blockers).

Run in freqtrade container (has lightgbm+talib+pandas):
  docker compose exec -T freqtrade python3 /tmp/backtest_freqai_sodex.py
"""
from __future__ import annotations
import sys
import warnings
from pathlib import Path
import numpy as np
import pandas as pd
import talib
import lightgbm as lgb

warnings.filterwarnings("ignore")
DATA = Path("/freqtrade/user_data/data/sodex/perps")
SYMBOLS = ["BTC_USD", "ETH_USD", "SOL_USD"]
PERIODS = [14, 50]
LABEL_PERIODS = 24        # forward horizon (24h), matches FreqAI label_period_candles
TRAIN_MIN = 1500          # min candles before first prediction
RETRAIN_EVERY = 168       # weekly retrain (speed)
THRESHOLD = 0.004         # |pred| must exceed 0.4% to take a trade
FEE = 0.00012             # maker per side

LGB_PARAMS = dict(n_estimators=800, learning_rate=0.03, num_leaves=31,
                  min_child_samples=20, feature_fraction=0.8, bagging_fraction=0.8,
                  bagging_freq=5, verbosity=-1, n_jobs=2)


def make_features(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c, v = (df[x].values.astype(float) for x in ("open", "high", "low", "close", "volume"))
    f = pd.DataFrame(index=df.index)
    for p in PERIODS:
        f[f"rsi_{p}"] = talib.RSI(c, p)
        f[f"adx_{p}"] = talib.ADX(h, l, c, p)
        f[f"mfi_{p}"] = talib.MFI(h, l, c, v, p)
        f[f"atr_{p}"] = talib.ATR(h, l, c, p) / c
        up, mid, lo = talib.BBANDS(c, p)
        f[f"bbw_{p}"] = (up - lo) / mid
        f[f"bbp_{p}"] = (c - lo) / (up - lo + 1e-9)
        macd, sig, hist = talib.MACD(c, p, p * 2, max(2, p // 2))
        f[f"macdh_{p}"] = hist / c
        f[f"emar_{p}"] = c / talib.EMA(c, p) - 1
        f[f"roc_{p}"] = talib.ROC(c, p)
    # basics
    f["pct_1"] = pd.Series(c).pct_change(1).values
    f["pct_5"] = pd.Series(c).pct_change(5).values
    f["vol_sma"] = v / (talib.SMA(v, 20) + 1e-9)
    f["hl_range"] = (h - l) / c
    obv = talib.OBV(c, v)
    f["obv_r"] = obv / (talib.SMA(obv, 20) + 1e-9)
    return f


def backtest(name: str) -> dict | None:
    fpath = DATA / f"{name}-1h.feather"
    if not fpath.exists():
        print(f"  {name}: no data"); return None
    df = pd.read_feather(fpath).sort_values("date").reset_index(drop=True)
    feats = make_features(df)
    close = df["close"].values.astype(float)
    label = pd.Series(close).shift(-LABEL_PERIODS).values / close - 1  # forward 24h return
    cols = list(feats.columns)
    X = feats.values
    n = len(df)

    preds = np.full(n, np.nan)
    model = None
    for t in range(TRAIN_MIN, n - LABEL_PERIODS):
        if (t - TRAIN_MIN) % RETRAIN_EVERY == 0:
            # train on rows whose label is fully known (end at t-LABEL_PERIODS)
            tr_end = t - LABEL_PERIODS
            Xtr, ytr = X[:tr_end], label[:tr_end]
            mask = ~np.isnan(Xtr).any(axis=1) & ~np.isnan(ytr)
            Xtr, ytr = Xtr[mask], ytr[mask]
            if len(Xtr) < 500:
                continue
            model = lgb.LGBMRegressor(**LGB_PARAMS)
            model.fit(Xtr, ytr)
        if model is not None and not np.isnan(X[t]).any():
            preds[t] = model.predict(X[t].reshape(1, -1))[0]

    # Non-overlapping trade sim: step every LABEL_PERIODS, act on prediction
    trades, dir_correct, dir_total = [], 0, 0
    t = TRAIN_MIN
    while t < n - LABEL_PERIODS:
        p = preds[t]
        if not np.isnan(p) and abs(p) >= THRESHOLD:
            direction = 1 if p > 0 else -1
            actual = label[t]
            if not np.isnan(actual):
                dir_total += 1
                if (actual > 0) == (direction > 0):
                    dir_correct += 1
                trades.append(actual * direction - 2 * FEE)
            t += LABEL_PERIODS  # non-overlapping hold
        else:
            t += 1
    if not trades:
        print(f"  {name}: 0 trades"); return None
    wins = [x for x in trades if x > 0]
    gw = sum(wins); gl = -sum(x for x in trades if x < 0)
    eq = 1.0; pk = 1.0; mdd = 0.0
    for x in trades:
        eq *= (1 + x); pk = max(pk, eq); mdd = min(mdd, (eq - pk) / pk)
    pf = gw / gl if gl > 0 else 9.99
    print(f"  {name}: {len(trades)} trades | dir-acc {dir_correct/dir_total*100:.0f}% | "
          f"win {len(wins)/len(trades)*100:.0f}% | PF {pf:.2f} | "
          f"total {(eq-1)*100:+.1f}% (unlev) | maxDD {mdd*100:.1f}%")
    return {"pf": pf, "total": (eq - 1) * 100, "dir_acc": dir_correct / dir_total * 100,
            "trades": len(trades), "mdd": mdd * 100}


def main():
    print("Walk-forward LightGBM (FreqAI-style) edge test — SoDEX 1h, label=fwd 24h return")
    print(f"train_min {TRAIN_MIN}, retrain/{RETRAIN_EVERY}h, threshold {THRESHOLD*100:.1f}%, "
          f"no-shuffle walk-forward (no look-ahead). UNLEVERAGED.\n")
    rows = []
    for s in SYMBOLS:
        r = backtest(s)
        if r:
            rows.append(r)
    if rows:
        print(f"\nAVG: PF {sum(r['pf'] for r in rows)/len(rows):.2f} | "
              f"dir-acc {sum(r['dir_acc'] for r in rows)/len(rows):.0f}% | "
              f"total {sum(r['total'] for r in rows)/len(rows):+.1f}%")
        print("Verdict: EDGE if avg PF > 1.2 and dir-acc > 52%.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
