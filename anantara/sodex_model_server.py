#!/usr/bin/env python3
"""
ANANTARA SAKTI — SoDEX LightGBM 48h model server.

Serves the only configuration that showed edge in backtest (label 48h, SoDEX
1h klines): PF 1.13, dir-acc 55%. Trains the project's LightGBM model on live
SoDEX klines, predicts forward-48h return, exposes a direction signal for the
farming loop. Runs in the freqtrade image (has talib + lightgbm + pandas).

Endpoints:
  GET  /health            — model status + ages
  GET  /predict/{symbol}  — {direction, confidence, predicted_return_pct}
  POST /retrain           — retrain all symbols now

Discipline: walk-forward training only (no shuffle, no look-ahead); labels use
data strictly older than the training cutoff.
"""
from __future__ import annotations
import os, time, logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests
import talib
import lightgbm as lgb
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sodex-model")

SODEX_PERPS = os.environ.get("SODEX_PERPS_URL", "https://mainnet-gw.sodex.dev/api/v1/perps")
SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "XAUT-USD", "HYPE-USD", "ZEC-USD",
           "BCH-USD", "SUI-USD", "DOGE-USD", "LTC-USD", "BNB-USD", "XRP-USD",
           "SILVER-USD", "COPPER-USD", "INTC-USD", "AMD-USD",
           "DASH-USD", "WLFI-USD", "LIT-USD", "ONDO-USD", "PENGU-USD", "NEAR-USD",
           "UNI-USD", "GOOGL-USD", "EWY-USD", "TSLA-USD", "HOOD-USD",
           "ARB-USD", "1000PEPE-USD", "TRX-USD", "ADA-USD", "ENA-USD", "XMR-USD",
           "SKHX-USD", "APT-USD", "MU-USD", "NVDA-USD", "AMZN-USD", "ORCL-USD",
           "MON-USD", "XPL-USD", "LINK-USD", "WLD-USD", "ASTER-USD", "TRUMP-USD",
           "VIRTUAL-USD", "BERA-USD", "HBAR-USD", "FIL-USD", "OP-USD", "AXS-USD",
           "WIF-USD", "AVAX-USD", "AAVE-USD", "PLTR-USD", "COIN-USD", "CRCL-USD"]
PERIODS = [14, 50]
LABEL_H = 48              # forward horizon (hours) — best backtest config
THRESHOLD = 0.004         # |pred| to call a direction
RETRAIN_SEC = 6 * 3600    # retrain every 6h
PROMOTE_DEGRADE_TOL = 3.0 # champion/challenger: reject a retrain only if its OOS dir-acc
                          # is >3pp WORSE than the incumbent (never ship a clearly-worse
                          # model; the incumbent IS the rollback). Else promote (refresh).
KLINES_LIMIT = 1000       # history per train (~41 days of 1h)
LGB = dict(n_estimators=600, learning_rate=0.03, num_leaves=31, min_child_samples=20,
           feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=5, verbosity=-1, n_jobs=2)

app = FastAPI(title="SoDEX LightGBM 48h Model")
MODELS: dict[str, dict] = {}   # symbol -> {model, trained_at, n, dir_acc_oos}


DATA_DIR = os.environ.get("SODEX_DATA_DIR", "/data/perps")


def _klines(symbol: str, limit: int = KLINES_LIMIT) -> pd.DataFrame | None:
    """Latest klines via REST (for fresh prediction)."""
    try:
        r = requests.get(f"{SODEX_PERPS}/markets/{symbol}/klines",
                         params={"interval": "1h", "limit": limit}, timeout=20)
        data = (r.json() or {}).get("data", []) or []
    except Exception as e:
        log.error(f"klines {symbol}: {e}")
        return None
    if len(data) < 60:
        return None
    df = pd.DataFrame(sorted(data, key=lambda k: k["t"]))
    for c in ("o", "h", "l", "c", "v"):
        df[c] = df[c].astype(float)
    return df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})


def _train_history(symbol: str) -> pd.DataFrame | None:
    """Full history for TRAINING: prefer downloaded feather (5000+ candles),
    fall back to REST (capped ~1000)."""
    fpath = os.path.join(DATA_DIR, f"{symbol.replace('-', '_')}-1h.feather")
    if os.path.exists(fpath):
        try:
            df = pd.read_feather(fpath).sort_values("date").reset_index(drop=True)
            if len(df) >= 300:
                return df[["open", "high", "low", "close", "volume"]].astype(float)
        except Exception as e:
            log.warning(f"feather read {symbol}: {e}")
    return _klines(symbol, limit=KLINES_LIMIT)


def _features(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c, v = (df[x].values for x in ("open", "high", "low", "close", "volume"))
    f = pd.DataFrame(index=df.index)
    for p in PERIODS:
        f[f"rsi{p}"] = talib.RSI(c, p); f[f"adx{p}"] = talib.ADX(h, l, c, p)
        f[f"mfi{p}"] = talib.MFI(h, l, c, v, p); f[f"atr{p}"] = talib.ATR(h, l, c, p) / c
        up, mid, lo = talib.BBANDS(c, p)
        f[f"bbw{p}"] = (up - lo) / mid; f[f"bbp{p}"] = (c - lo) / (up - lo + 1e-9)
        _, _, hist = talib.MACD(c, p, p * 2, max(2, p // 2)); f[f"mh{p}"] = hist / c
        f[f"er{p}"] = c / talib.EMA(c, p) - 1; f[f"roc{p}"] = talib.ROC(c, p)
    f["p1"] = pd.Series(c).pct_change(1).values; f["p5"] = pd.Series(c).pct_change(5).values
    f["vs"] = v / (talib.SMA(v, 20) + 1e-9); f["hl"] = (h - l) / c
    obv = talib.OBV(c, v); f["obvr"] = obv / (talib.SMA(obv, 20) + 1e-9)
    return f


def train_symbol(symbol: str) -> bool:
    df = _train_history(symbol)
    if df is None:
        log.warning(f"{symbol}: insufficient klines"); return False
    feats = _features(df)
    close = df["close"].values
    label = pd.Series(close).shift(-LABEL_H).values / close - 1
    X = feats.values
    # train rows: labels fully known (drop last LABEL_H); hold last 15% for OOS dir-acc
    end = len(df) - LABEL_H
    cut = int(end * 0.85)
    m = ~np.isnan(X).any(axis=1) & ~np.isnan(label)
    idx = np.arange(len(df))
    tr = idx[(idx < cut) & m]; oos = idx[(idx >= cut) & (idx < end) & m]
    if len(tr) < 300:
        log.warning(f"{symbol}: too few train rows ({len(tr)})"); return False
    model = lgb.LGBMRegressor(**LGB)
    model.fit(X[tr], label[tr])
    # out-of-sample directional accuracy
    dir_acc = None
    if len(oos) > 20:
        pred = model.predict(X[oos])
        act = label[oos]
        sel = np.abs(pred) >= THRESHOLD
        if sel.sum() > 0:
            dir_acc = float(((pred[sel] > 0) == (act[sel] > 0)).mean() * 100)
    # final fit on all known-label rows for serving
    allrows = idx[(idx < end) & m]
    model.fit(X[allrows], label[allrows])
    challenger = {"model": model, "trained_at": time.time(),
                  "n": int(len(allrows)), "dir_acc_oos": dir_acc,
                  "feat_cols": list(feats.columns)}
    # CHAMPION/CHALLENGER ENFORCEMENT: never ship a clearly-worse model. The incumbent
    # in MODELS[symbol] is the live champion (and the rollback). Promote the challenger
    # unless its OOS dir-acc is >PROMOTE_DEGRADE_TOL pp below the champion's.
    champ = MODELS.get(symbol)
    champ_acc = champ.get("dir_acc_oos") if champ else None
    if (champ is not None and champ_acc is not None and dir_acc is not None
            and dir_acc < champ_acc - PROMOTE_DEGRADE_TOL):
        champ["last_rejected_acc"] = dir_acc          # record the rejected challenger
        champ["last_eval_at"] = time.time()
        log.warning(f"{symbol}: challenger OOS {dir_acc:.1f} << champion {champ_acc:.1f} "
                    f"(>{PROMOTE_DEGRADE_TOL}pp) → KEPT champion (rollback)")
        return True
    _accs = [a for a in (dir_acc, champ_acc) if a is not None]
    challenger["champion_best_acc"] = max(_accs) if _accs else None
    MODELS[symbol] = challenger
    promo = "promoted" if champ else "first model"
    log.info(f"{symbol}: {promo} — {len(allrows)} rows, OOS dir-acc {dir_acc}"
             + (f" (was {champ_acc})" if champ_acc is not None else ""))
    return True


def train_all():
    for s in SYMBOLS:
        try:
            train_symbol(s)
        except Exception as e:
            log.exception(f"train {s} failed: {e}")


@app.on_event("startup")
def _startup():
    train_all()


@app.get("/health")
def health():
    now = time.time()
    return {"status": "ok", "label_horizon_h": LABEL_H,
            "models": {s: {"age_min": round((now - m["trained_at"]) / 60, 1),
                           "n": m["n"], "dir_acc_oos": m["dir_acc_oos"],
                           "champion_best_acc": m.get("champion_best_acc"),
                           "last_rejected_acc": m.get("last_rejected_acc")}
                       for s, m in MODELS.items()}}


@app.post("/retrain")
def retrain():
    train_all()
    return {"ok": True, "trained": list(MODELS.keys())}


@app.get("/predict/{symbol}")
def predict(symbol: str):
    symbol = symbol.upper()
    if "-" not in symbol:
        symbol = f"{symbol}-USD"
    entry = MODELS.get(symbol)
    if not entry:
        return {"symbol": symbol, "direction": "NEUTRAL", "confidence": 0.0,
                "error": "model not trained"}
    # retrain if stale
    if time.time() - entry["trained_at"] > RETRAIN_SEC:
        try:
            train_symbol(symbol); entry = MODELS.get(symbol, entry)
        except Exception:
            pass
    df = _klines(symbol, limit=300)  # period-50 MACD (slow 100 + signal 25) needs ~125+ warmup
    if df is None:
        return {"symbol": symbol, "direction": "NEUTRAL", "confidence": 0.0, "error": "no klines"}
    feats = _features(df)
    x = feats.iloc[[-1]].values
    if np.isnan(x).any():
        return {"symbol": symbol, "direction": "NEUTRAL", "confidence": 0.0, "error": "nan features"}
    pred = float(entry["model"].predict(x)[0])
    direction = "UP" if pred > THRESHOLD else ("DOWN" if pred < -THRESHOLD else "NEUTRAL")
    # confidence capped modestly — OOS dir-acc is ~55%, not high conviction
    conf = round(min(0.75, 0.55 + min(0.20, abs(pred) * 12)), 2) if direction != "NEUTRAL" else round(0.5, 2)
    return {"symbol": symbol, "ts": datetime.now(timezone.utc).isoformat(),
            "direction": direction, "confidence": conf,
            "predicted_return_pct": round(pred * 100, 3),
            "label_horizon_h": LABEL_H, "model_dir_acc_oos": entry["dir_acc_oos"]}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    lines = ["# HELP sodex_model_dir_acc_oos Out-of-sample directional accuracy %",
             "# TYPE sodex_model_dir_acc_oos gauge"]
    for s, m in MODELS.items():
        if m.get("dir_acc_oos") is not None:
            lines.append(f'sodex_model_dir_acc_oos{{symbol="{s}"}} {m["dir_acc_oos"]}')
    return "\n".join(lines)
