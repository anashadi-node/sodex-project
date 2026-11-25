#!/usr/bin/env python3
"""REGIME-SWITCHING GATE — matikan trading di sideways/bear (2026-09-05).

Fondasi ilmiah (arXiv 2602.11708, Adaptive Trend): di market SIDEWAYS
rata-rata strategi trend-following hanya +0.63%/trade & WR 47.8%, dan di
BEAR malah -0.21%/trade WR 41.3%. Bahkan strategi top dunia PUN menderita
di bear. Kesimpulan: JANGAN memaksa profit di sideways/bear — MATIKAN,
lindungi modal, tunggu bull/trend. "Siapa yang selangkah lebih maju = yang
membaca regime paling cepat & tidak melawan arus."

Implementasi: klasifikasi regime 3-state (BULL/NEUTRAL/BEAR) berbasis
HMM-like rule (harga vs EMA50 + ADX + slope), lalu:
  - BULL  : izinkan LONG (momentum) — track realwide jalan.
  - NEUTRAL (sideways): kurangi exposure 50%, hanya pair dengan edge kuat
    (larang entry baru jika ATR rendah & ADX<20).
  - BEAR  : IZINKAN HANYA SHORT dengan filter ketat (momentum turun nyata),
    atau FLAT (no trade) — jangan memaksa.

Read-only gate — tidak mengirim order. Dipakai service live/paper.
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paper_test_shortbear as sb

STATE_FILE = Path(__file__).resolve().parents[1] / "data" / "regime_switch_state.json"


def classify(sym="BTCUSDT", lookback=300):
    """Klasifikasi regime 3-state. Return dict dgn score & verdict."""
    try:
        d = sb.fetch_ohlcv(sym, limit=lookback)
    except Exception:
        return {"verdict": "UNKNOWN", "score": 0, "reason": "fetch_err"}
    c = d["c"]
    i = len(c) - 2
    if i < 200:
        return {"verdict": "UNKNOWN", "score": 0, "reason": "insufficient"}
    # EMA50
    k = 2 / 51
    ema = c[0]
    for j in range(1, i + 1):
        ema = c[j] * k + ema * (1 - k)
    # ADX via v3
    import backtest_swing_gate1_v3 as v3
    a = v3.adx(d["h"], d["l"], c)
    adx = float(a[i]) if not np.isnan(a[i]) else 20.0
    # slope 24h & 72h
    r24 = (c[i] - c[i-24]) / c[i-24] if i >= 24 else 0
    r72 = (c[i] - c[i-72]) / c[i-72] if i >= 72 else r24
    # skor -1..+1: dominasi trend SHORT-TERM (reaktivitas cepat utk sideways)
    score = 0.0
    score += 0.3 if c[i] > ema else -0.3
    score += 0.7 if r24 > 0.005 else (-0.7 if r24 < -0.005 else 0.0)
    score += 0.2 if r72 > 0.01 else (-0.2 if r72 < -0.01 else 0.0)
    # PENALTI SMA50 (fix 2026-09-06): harga di bawah SMA50 = struktural BEAR,
    # berapa pun r24/r72. Ini sinkronkan dgn gate lain (macro_btc_long_blocked)
    # yang selama ini kontradiksi (classifier bilang BULL, gate blockir LONG).
    s50 = v3.sma(c, 50)
    below_sma50 = c[i] < s50[i]
    if below_sma50:
        score -= 0.5
    else:
        score += 0.2
    if adx < 18:
        score *= 0.5  # sideways: lemahkan sinyal, prefer NEUTRAL
    elif adx > 25 and r24 < -0.01:
        score -= 0.4  # ADX tinggi + turun = tren bear kuat

    verdict = "BULL" if score > 0.35 else ("BEAR" if score < -0.35 else "NEUTRAL")
    out = {"verdict": verdict, "score": round(score, 3), "adx": round(adx, 1),
           "r24": round(r24 * 100, 2), "vs_ema": round((c[i]/ema - 1) * 100, 2),
           "ts": time.time()}
    json.dump(out, open(STATE_FILE, "w"), indent=1)
    return out


def gate_allowed(verdict, direction, mode="live"):
    """Kebijakan exposure per regime."""
    if verdict == "BULL":
        return direction == "LONG" or direction == "SHORT"  # long utama
    if verdict == "NEUTRAL":
        return direction == "LONG" and mode != "live"  # paper boleh collect
    if verdict == "BEAR":
        return direction == "SHORT"  # hanya short, filter ketat
    return False


if __name__ == "__main__":
    out = classify()
    print(f"REGIME BTC: {out.get('verdict')}  score={out.get('score')} "
          f"ADX={out.get('adx')} r24={out.get('r24')}% vsEMA={out.get('vs_ema')}%")
    print(f"  LONG allowed: {gate_allowed(out.get('verdict'), 'LONG')}")
    print(f"  SHORT allowed: {gate_allowed(out.get('verdict'), 'SHORT')}")