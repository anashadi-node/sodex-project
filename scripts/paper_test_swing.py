#!/usr/bin/env python3
"""
ANANTARA SAKTI — Gate 2 Paper Test v3: 17-Asset Universe
=========================================================
Expanded from 4 pairs to full 17-asset SoDEX radar (2026-08-22):
  BTC ETH SOL HYPE BNB XRP DOGE BCH ZEC ONDO LINK AAVE SUI UNI ADA TRX ENA
  NOT on SoDEX: PENDLE TAO JUP (skipped — no SoDEX-USD perp available)

Strategy: v3 regime-switched momentum LONG-only, min-hold 12h before SL.
MAX_TOTAL_POSITIONS=5 — monitors all 17 but holds max 5 concurrent positions.

Run: python3 scripts/paper_test_swing.py --loop --interval 300
Status: python3 scripts/paper_test_swing.py --status
"""
import argparse, json, os, random, time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

PROJECT = Path(__file__).resolve().parents[1]
from cost_model import round_trip_frac as _rt_cost  # SUMBER TUNGGAL biaya (audit 30-Sep-2026)
# Suffix state/log utk track terpisah (mis. _partial) — hindari campur data.
_STATE_SUFFIX = os.environ.get("PAPER_STATE_SUFFIX", "")
STATE_FILE = PROJECT / "data" / f"paper_test_swing_state{_STATE_SUFFIX}.json"
LOG_FILE = PROJECT / "data" / f"paper_test_swing{_STATE_SUFFIX}.jsonl"
MONITOR_JSON = PROJECT / "data" / f"paper_test_swing_latest{_STATE_SUFFIX}.json"

# ── EXIT ENGINE (2026-08-13, exit-lab OOS-validated) ──
# base   = TP2.5/SL1/TIME48 (konfigurasi lama)
# partial= ambil 50% profit di +1.2%, sisa 50% ke TP2.5, SL protektif di +1.2%
# Bukti exit-lab: partial IS +27.8% vs base -9.9% ; OOS +58.6% vs +29.0%.
EXIT_MODE = os.environ.get("PAPER_EXIT_MODE", "base").lower()
PARTIAL_PCT = float(os.environ.get("PAPER_PARTIAL_PCT", "0.012"))
PARTIAL_FRAC = float(os.environ.get("PAPER_PARTIAL_FRAC", "0.5"))

# ── Pairs & Spreads (17-asset SoDEX radar, 2026-08-22) ──
# NOT on SoDEX: PENDLE TAO JUP
PAIRS = [
    "BTC", "ETH", "SOL", "HYPE", "BNB", "XRP", "DOGE",
    "BCH", "ONDO", "LINK", "AAVE", "SUI", "UNI",
    "TRX", "ENA", "ASTER", "PUMP", "LIT",
]
BINANCE_SYMBOLS = {
    "BTC":  "BTCUSDT",  "ETH":  "ETHUSDT",  "SOL":  "SOLUSDT",
    "HYPE": "HYPEUSDT", "BNB":  "BNBUSDT",  "XRP":  "XRPUSDT",
    "DOGE": "DOGEUSDT", "BCH":  "BCHUSDT",  "ONDO": "ONDOUSDT",
    "LINK": "LINKUSDT", "AAVE": "AAVEUSDT",
    "SUI":  "SUIUSDT",  "UNI":  "UNIUSDT",  "ADA":  "ADAUSDT",
    "TRX":  "TRXUSDT",  "ENA":  "ENAUSDT",
    "ASTER": "ASTERUSDT", "PUMP": "PUMPUSDT", "LIT":  "LITUSDT",
}
SODEX_SYMBOLS = {
    "BTC":  "BTC-USD",  "ETH":  "ETH-USD",  "SOL":  "SOL-USD",
    "HYPE": "HYPE-USD", "BNB":  "BNB-USD",  "XRP":  "XRP-USD",
    "DOGE": "DOGE-USD", "BCH":  "BCH-USD",  "ONDO": "ONDO-USD",
    "LINK": "LINK-USD", "AAVE": "AAVE-USD",
    "SUI":  "SUI-USD",  "UNI":  "UNI-USD",  "ADA":  "ADA-USD",
    "TRX":  "TRX-USD",  "ENA":  "ENA-USD",
    "ASTER": "ASTER-USD", "PUMP": "PUMP-USD", "LIT":  "LIT-USD",
}
# Estimated RT spreads (fraction of price) based on SoDEX microstructure
SPREADS = {
    "BTC":  0.00002, "ETH":  0.00005, "SOL":  0.00014,
    "HYPE": 0.00025, "BNB":  0.00006, "XRP":  0.00008,
    "DOGE": 0.00014, "BCH":  0.00015, "ZEC":  0.00020,
    "ONDO": 0.00025, "LINK": 0.00012, "AAVE": 0.00020,
    "SUI":  0.00018, "UNI":  0.00015, "ADA":  0.00010,
    "TRX":  0.00010, "ENA":  0.00025,
    # 2026-08-31 live-measured (orderbook/ticker): ASTER 1.4bps vol-kecil → 4bps,
    # PUMP 2.3bps → 4bps, LIT top-of-book $107/side THIN-BOOK → 8bps (kategori HYPE/SUI/SILVER)
    "ASTER": 0.0004, "PUMP": 0.0004, "LIT": 0.0008,
}
# 2026-08-31: ZEC dihapus dari SWING (n=9, WR 33%, EV -$28.76, 6/9 EMERGENCY_SL).
# BUKAN anti-predictive global — profitable di SWING_PARTIAL (+$14.48, WR 62.5%)
# dan DONCHIAN (+$7.22). Exit-geometry SWING base (min-hold 12h) yang tidak cocok
# untuk pair volatil (ATR 1.85%+). ZEC tetap terpantau via SWING_PARTIAL.
# 2026-09-04: ADA dihapus dari SWING & SWING_PARTIAL (kriteria block sama seperti
# HYPE/ENA di DONCHIAN: n>=5, WR<40%, EV<0). Data: SWING n=5 WR=20% PnL=-$32.60,
# SWING_PARTIAL n=3 WR=33% PnL=-$30.04. Total lintas 2 track: n=8 WR=25% EV=-$62.64.
# ADA tetap terpantau di REALWIDE/TWOWAY/DONCHIAN (belum ada bukti anti-edge di sana).

# ── v3 Strategy (ACCELERATED: cooldown 12h validated) ─────────────────
MAX_POSITIONS = 1          # per pair
MAX_TOTAL_POSITIONS = 5    # across all 20 pairs (limit concurrent capital exposure)
COOLDOWN_HOURS = 12        # was 24h — validated: PF retained >95%, SOL+DOGE improved
MIN_HOLD_SL_H = 0        # FIX 2026-09-04 (approved): SL aktif dari t=0, samakan
                          # REALWIDE (0% EMERGENCY_SL, WR 60.8%, ROI +4.23%).
                          # SEBELUM: 12h menahan SL normal, hanya EMERGENCY_SL(-2%)
                          # bisa fire → 28% trade (37/132) kena 2x kerugian normal.
TP_PCT = 0.025
SL_PCT = 0.010
# ── A/B REGIME_FLIP (disetujui Owner 2026-11-06) ─────────────────────────────
# Replay berpasangan n=1363 (swing/partial/strict, slip 5bps, p<0.0001):
# exit REGIME_FLIP = -0.21pp/trade vs +0.18pp bila dibiarkan kena TP/SL
# (Δ = +0.35..0.44pp). Arm TREATMENT: SW_REGIME_FLIP=0 → flip exit dimatikan.
# Arm KONTROL: lane partial/strict tetap SW_REGIME_FLIP=1.
SW_REGIME_FLIP = os.environ.get("SW_REGIME_FLIP","1").strip() not in ("0","false","False","no")
# Keputusan Owner 2026-11-07: HENTIKAN entry LONG-sinyal di lane swing produksi.
# Bukti (n=411): pra-entry 24j SIGNAL +2,3..+3,7% vs kontrol RANDOM -1,0% (p=3e-121),
# net 24j per lane -0,55..-2,03pp dgn CI95 bawah < 0, sementara track RANDOM ~0.
# Fungsi: hanya memblokir entry SIGNAL (LONG); track RANDOM tetap jalan sebagai kontrol.
# Default OFF -> lane riset (9a/9b/9c) dan siapa pun yg tak memakai env ini tidak berubah.
SW_BLOCK_LONG_SIGNAL = os.environ.get("SW_BLOCK_LONG_SIGNAL","0").strip() not in ("0","false","False","no")

_BLOCK_LOGGED: dict = {}


def _block_log(label: str, pair: str, ttl: float = 3600.0) -> None:
    """Cetak 1x/jam per pair saat entry diblokir — jejak audit, bukan spam log."""
    now = time.time()
    if now - _BLOCK_LOGGED.get((label, pair), 0.0) < ttl:
        return
    _BLOCK_LOGGED[(label, pair)] = now
    print(f"  SKIP {pair}: LONG-sinyal dihentikan (keputusan Owner 2026-11-07)")
# A/B 2 (2026-11-06): macro gate defensif. Default OFF → lane kontrol tidak berubah.
# Basis: skip VIX>=20/HY>=4.2 + window event makro menaikkan gross 6 lane
# +22,1pp → +50,2pp (n=3734). Efek kecil (~+0,0075pp/trade) tapi arahnya jelas.
SW_MACRO_GUARD = os.environ.get("SW_MACRO_GUARD","0").strip() in ("1","true","True","yes","on")
# ── A/B BTC-REGIME ENTRY GATE (2026-11-07, DEFAULT OFF, fail-open) ──────────
# Bukti ledger (double-check audit): swing  keep n=597 -0.037% vs block n=329
# -0.238% (Δ +0.201pp, BH p=0.0112); partial keep n=642 -0.056% vs block
# n=359 -0.202% (Δ +0.146pp, BH p=0.0132). strict TIDAK dapat gate (p=0.3053).
# Gate hanya memblokir ENTRY BARU; exit loop posisi terbuka tetap jalan.
SW_BTC_GATE = os.environ.get("SW_BTC_GATE","0").strip() in ("1","true","True","yes","on")
SW_BTC_MOM_DAYS = int(os.environ.get("SW_BTC_MOM_DAYS", "30"))
_btc_gate_cache = {"ts": 0.0, "ok": True}

# ── A/B 8b TRAILING EXIT (2026-11-06, disetujui Owner; DEFAULT OFF) ─────────
# Varian replay exit-geometry `trail1r`: +0,055..+0,074pp/trade TAPI p=0,14–0,43
# (belum signifikan) → dijalankan sebagai UJI KONFIRMASI di lane riset terisolasi,
# bukan klaim perbaikan. Trigger 0 = fitur mati → lane produksi tidak berubah.
SW_TRAIL_TRIGGER_R = float(os.environ.get("SW_TRAIL_TRIGGER_R", "0") or 0)
SW_TRAIL_R = float(os.environ.get("SW_TRAIL_R", "1.0"))


def trail_decision(peak: float, gross: float, sl: float,
                   trigger_r: float | None = None, trail_r: float | None = None) -> bool:
    """True = trailing exit terpicu.

    Syarat: puncak untung sudah >= trigger_r x SL (senjata terkokang), lalu harga
    mundur >= trail_r x SL dari puncak. trigger_r <= 0 berarti fitur OFF.
    Satuan semua argumen = fraksi harga (mis. 0.01 = 1%), R diukur dari SL efektif.
    """
    trig = SW_TRAIL_TRIGGER_R if trigger_r is None else trigger_r
    dist = SW_TRAIL_R if trail_r is None else trail_r
    if trig <= 0:
        return False
    return peak >= trig * sl and gross <= peak - dist * sl


def btc_regime_ok(days=None, max_age_s=900):
    """True = boleh entry baru. False = BTC momentum N-hari negatif."""
    if not SW_BTC_GATE:
        return True
    now = time.time()
    if now - float(_btc_gate_cache["ts"]) < max_age_s:
        return bool(_btc_gate_cache["ok"])
    d = int(days or SW_BTC_MOM_DAYS)
    ok = True
    try:
        rows = _fetch_binance_klines("BTCUSDT", "1d", d + 5)
        if isinstance(rows, list) and len(rows) > d:
            c = [float(x[4]) for x in rows]
            ok = (c[-1] / c[-1 - d] - 1) >= 0
    except Exception:
        ok = True          # fail-open: data hilang != bukti regime jelek
    _btc_gate_cache["ts"] = now
    _btc_gate_cache["ok"] = ok
    return ok
# ── ATR-SCALED GEOMETRY (arm riset 2026-09-25, env-gated, DEFAULT OFF) ──────
# Bukti: korelasi ATR% vs SL-rate = +0.750 (p_perm=0.0006, 16 pair, n>=8/pair).
# SL tetap 1% = 0.14x ATR harian ONDO (ATR 7.4%) vs 1.69x untuk BTC (0.59%):
# pair volatil kena stop oleh noise, bukan oleh tesis yang salah. ONDO sendiri
# +72.6% dalam 90 hari (buy-hold) tapi track kita negatif -> masalah geometri.
# Arm uji: SL = mult*ATR (dibatasi floor..cap), TP = SL*RR (R:R dijaga).
# Set PAPER_ATR_SL=1 HANYA di instance riset terisolasi.
ATR_SL_ENABLED = os.environ.get("PAPER_ATR_SL", "0") == "1"
ATR_SL_MULT = float(os.environ.get("PAPER_ATR_SL_MULT", "1.0"))
ATR_SL_FLOOR = float(os.environ.get("PAPER_ATR_SL_FLOOR", "0.010"))
ATR_SL_CAP = float(os.environ.get("PAPER_ATR_SL_CAP", "0.040"))
ATR_RR = float(os.environ.get("PAPER_ATR_RR", "2.5"))


def eff_tp_sl(pos: dict) -> tuple:
    """(TP%, SL%) efektif utk sebuah posisi. Default = konstanta produksi."""
    if not ATR_SL_ENABLED:
        return TP_PCT, SL_PCT
    atr = float(pos.get("atr_pct") or 0.0)
    sl = min(max(ATR_SL_MULT * atr, ATR_SL_FLOOR), ATR_SL_CAP)
    return round(sl * ATR_RR, 6), round(sl, 6)

TIME_STOP_H = 30
LEVERAGE = 5
NOTIONAL = 100.0
MAKER_FEE_RT = 0.00024
TARGET_MIN_PCT = 0.008   # North Star: ≥0.8% net per 30h window (user GO 27-Sep)
# North Star (2026-08-14): denominator = TOTAL modal wallet (spot+perps).
# Priority: SODEX_TOTAL_WALLET env → ground_truth.json observed balance (≥$100) →
# NOTIONAL×LEVERAGE ($500). Using leveraged exposure as default ensures metric is
# meaningful: 0.7%×$500=$3.50 minimum, TP2.5% on $500=$12.50 clearly beats it.

def _read_wallet_capital() -> float:
    env_val = os.environ.get("SODEX_TOTAL_WALLET")
    if env_val:
        return float(env_val)
    gt = PROJECT / "data" / "ground_truth.json"
    if gt.exists():
        try:
            with open(gt) as _f:
                _d = json.load(_f)
            total = _d.get("hl_total", {}).get("observed_account_value_usd", 0)
            if total >= 100:
                return float(total)
        except Exception:
            pass
    return NOTIONAL * LEVERAGE   # effective position exposure per trade

TOTAL_WALLET_CAPITAL = _read_wallet_capital()

# Binance API
SODEX_TICKERS = "https://mainnet-gw.sodex.dev/api/v1/perps/markets/tickers"
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
BINANCE_FAPI_KLINES = "https://fapi.binance.com/fapi/v1/klines"


def _fetch_binance_klines(symbol: str, interval: str, limit: int):
    """Spot first; futures fallback for symbols such as HYPE."""
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    errors = []
    for endpoint in (BINANCE_KLINES, BINANCE_FAPI_KLINES):
        try:
            r = requests.get(endpoint, params=params, timeout=15)
            data = r.json()
            if isinstance(data, list) and data:
                return data
            errors.append(f"{endpoint}: invalid response")
        except Exception as exc:
            errors.append(f"{endpoint}: {type(exc).__name__}")
    raise RuntimeError(f"OHLCV unavailable for {symbol}: {'; '.join(errors)}")

def fetch_prices_sodex():
    """Fetch prices from SoDEX perps API (primary source). Returns partial dict on partial success."""
    try:
        r = requests.get(SODEX_TICKERS, timeout=10)
        data = r.json()
        tickers = data if isinstance(data, list) else data.get("data", data.get("result", []))
        ticker_map = {t.get("symbol"): t for t in tickers if isinstance(t, dict)}
        prices = {}
        for pair in PAIRS:
            sdex_sym = SODEX_SYMBOLS[pair]
            t = ticker_map.get(sdex_sym)
            if t:
                px = float(t.get("lastPx", 0) or 0)
                if px > 0:
                    prices[pair] = px
        return prices  # partial OK — caller fills gaps via Binance
    except Exception:
        return {}

def fetch_prices_binance():
    """Fetch prices from Binance (fallback)."""
    prices = {}
    for pair in PAIRS:
        try:
            sym = BINANCE_SYMBOLS[pair]
            r = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": sym}, timeout=10)
            prices[pair] = float(r.json()["price"])
        except Exception:
            pass
    return prices

def fetch_prices():
    """Fetch prices: SoDEX primary, Binance fills any gaps."""
    prices = fetch_prices_sodex()
    missing = [p for p in PAIRS if p not in prices or prices[p] <= 0]
    if missing:
        binance = fetch_prices_binance()
        for p in missing:
            if p in binance and binance[p] > 0:
                prices[p] = binance[p]
    return prices
def rsi(c, p=14):
    d = np.diff(c, prepend=c[0])
    g = np.where(d > 0, d, 0.0)
    l = np.where(d < 0, -d, 0.0)
    ag = pd.Series(g).ewm(span=p, adjust=False).mean().values
    al = pd.Series(l).ewm(span=p, adjust=False).mean().values
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.divide(ag, al, out=np.ones_like(ag), where=al > 0)
    return 100.0 - (100.0 / (1.0 + rs))

def sma(c, p):
    return pd.Series(c).rolling(p).mean().values

def rr(c, lb):
    r = np.full_like(c, np.nan)
    r[lb:] = (c[lb:] - c[:-lb]) / c[:-lb]
    return r

def atr(h, l, c, p=14):
    tr = np.maximum(h - l, np.maximum(abs(h - np.roll(c, 1)), abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    return pd.Series(tr).ewm(span=p, adjust=False).mean().values

def adx(h, l, c, p=14):
    t = atr(h, l, c, p)
    u = h - np.roll(h, 1)
    d = np.roll(l, 1) - l
    pdm = np.where((u > d) & (u > 0), u, 0.0)
    ndm = np.where((d > u) & (d > 0), d, 0.0)
    ts = pd.Series(t).ewm(span=p, adjust=False).mean().values
    pdi = 100 * pd.Series(pdm).ewm(span=p, adjust=False).mean().values / ts
    ndi = 100 * pd.Series(ndm).ewm(span=p, adjust=False).mean().values / ts
    return pd.Series(100 * abs(pdi - ndi) / (pdi + ndi + 1e-10)).ewm(span=p, adjust=False).mean().values

def fetch_ohlcv(binance_symbol: str, limit: int = 300):
    data = _fetch_binance_klines(binance_symbol, "1h", limit)
    return {
        "close": np.array([float(d[4]) for d in data]),
        "high": np.array([float(d[2]) for d in data]),
        "low": np.array([float(d[3]) for d in data]),
        "open": np.array([float(d[1]) for d in data]),
        "volume": np.array([float(d[5]) for d in data]),
    }


def _confirm_15m(pair: str, direction: str = "LONG") -> bool:
    """15m confirmation; unavailable data must reject the entry (fail-closed)."""
    try:
        sym = BINANCE_SYMBOLS.get(pair, pair + "USDT")
        k = _fetch_binance_klines(sym, "15m", 25)
        if len(k) < 22:
            return False
        c = np.array([float(x[4]) for x in k])
        i = len(c) - 2  # last fully closed 15m bar
        s20 = sma(c, 20)
        if np.isnan(s20[i]):
            return False
        if direction == "LONG":
            return bool(c[i] > s20[i])   # price above 15m SMA20 = uptrend confirmed
        else:
            return bool(c[i] < s20[i])   # price below 15m SMA20 = downtrend confirmed
    except Exception:
        return False  # fail-closed — no confirmation, no entry

# ── RELAXED data-collection knobs (env-tunable). Loosen entry so PAPER trades
# happen and generate learning data. NOT proof of edge — Gate-2 promotion still
# needs strict-signal performance. Set PAPER_RELAXED=0 to restore strict v3.
_RELAXED = os.environ.get("PAPER_RELAXED", "1") == "1"
_ADX_MIN = float(os.environ.get("PAPER_ADX_MIN", "15" if _RELAXED else "25"))
_MIN_CHECKS = int(os.environ.get("PAPER_MIN_CHECKS", "3" if _RELAXED else "4"))
_REQUIRE_GOLDEN = os.environ.get("PAPER_REQUIRE_GOLDEN", "0" if _RELAXED else "1") == "1"


def check_signal(data: dict, pair: str) -> dict:
    c, h, l, v = data["close"], data["high"], data["low"], data["volume"]
    # FIX 2026-08-06 (audit): sinyal harus di bar TERAKHIR TERTUTUP (index -2),
    # bukan bar yang sedang berjalan (-1). Di bar -1, v[i] = volume parsial jam
    # berjalan → vol_ratio = v[i]/avg24 selalu < 1.1 → cek volume TIDAK PERNAH
    # lolos live (backtest memakai bar lengkap). Disamakan dengan REAL-wide.
    i = len(c) - 2
    if i < 200:
        return {"active": False, "reason": "insufficient_data"}

    a = adx(h, l, c)
    s50 = sma(c, 50)
    s200 = sma(c, 200)
    rv = rsi(c)

    # Momentum regime. Relaxed: lower ADX floor + optional golden-cross so entries
    # fire in mild/choppy uptrends (data collection), still require c>SMA50 (uptrend).
    golden_ok = (s50[i] > s200[i]) if _REQUIRE_GOLDEN else True
    if a[i] <= _ADX_MIN or c[i] <= s50[i] or not golden_ok:
        return {"active": False, "reason": "no_momentum_regime"}

    r24 = rr(c, 24)
    r1 = rr(c, 1)
    s24 = sma(c, 24)
    va = sma(v, 24)
    vr = v[i] / va[i] if va[i] > 0 else 1.0

    checks = 0
    reasons = []
    if c[i] > s24[i]:
        checks += 1
        reasons.append("above_sma24")
    if 40 < rv[i] < 60:
        checks += 1
        reasons.append("rsi_mid")
    if vr > 1.1:
        checks += 1
        reasons.append("vol_above_avg")
    if i >= 24 and not np.isnan(r24[i]) and r24[i] > 0.012:
        checks += 1
        reasons.append("strong_24h_trend")
    if i >= 1 and not np.isnan(r1[i]) and r1[i] < 0.003:
        checks += 1
        reasons.append("minor_pullback")

    if checks >= _MIN_CHECKS:
        # A/B BTC-REGIME GATE (2026-11-07): entry baru hanya saat BTC momentum
        # N-hari >= 0. Default OFF; fail-open bila feed gagal.
        if not btc_regime_ok():
            return {"active": False, "reason": "btc_regime_block"}
        # ASYMMETRIC REGIME FILTER (2026-08-15): momentum-long only in confirmed
        # 1h uptrend + not turning on 30m. Fixes Aug12+ 8/8 loss (entered in chop).
        import regime_filter as rf
        _sym = f"{pair}USDT"
        if not rf.entry_regime_ok(_sym):
            return {"active": False, "reason": "regime_not_uptrend"}
        if rf.fast_regime_bad(_sym):
            return {"active": False, "reason": "regime_30m_turning"}
        # 15m multi-timeframe confirmation: price must be above 15m SMA20.
        # Eliminates signals where 1h bar closed bullish but 15m is already
        # reversing — reduces false entries from the ~65min signal lag.
        if not _confirm_15m(pair, "LONG"):
            return {"active": False, "reason": "15m_below_sma20"}
        return {
            "active": True, "direction": "LONG", "conviction": checks / 5.0,
            "reasons": reasons, "regime": "MOMENTUM",
            "relaxed": _RELAXED, "adx": float(a[i]),
            "atr_pct": float(atr(h, l, c)[i] / c[i]),
        }
    return {"active": False, "reason": f"checks_{checks}/{_MIN_CHECKS}"}

# ── State ────────────────────────────────────────────────────────────────
def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            state = json.load(f)
        # Migrate: ensure all current PAIRS have entries in by_pair
        for p in PAIRS:
            if p not in state.get("by_pair", {}):
                state.setdefault("by_pair", {})[p] = {"pnl": 0, "n": 0, "wins": 0}
            state["by_pair"][p].setdefault("below", 0)
        # Migrate: TIME_STOP 48→30 → bucket 24-48h renamed 24-30h
        hb = state.setdefault("hold_buckets", {})
        if "24-48h" in hb and "24-30h" not in hb:
            hb["24-30h"] = hb.pop("24-48h")
        hb.setdefault("24-30h", [])
        state.setdefault("n_below_target", 0)
        # Recompute n_below_target from closed_trades using current TOTAL_WALLET_CAPITAL.
        # Handles wallet-value changes between runs (e.g. $10k→$500 fix 2026-08-22).
        if "closed_trades" in state and state["closed_trades"]:
            n_below = 0
            pair_below: dict = {p: 0 for p in PAIRS}
            for ct in state["closed_trades"]:
                pnl_usd = ct.get("pnl_usd", 0)
                wroi = pnl_usd / TOTAL_WALLET_CAPITAL
                bt = wroi < TARGET_MIN_PCT
                ct["wallet_roi"] = wroi
                ct["below_target"] = bt
                if bt:
                    n_below += 1
                    pair_below[ct.get("pair", "")] = pair_below.get(ct.get("pair", ""), 0) + 1
            state["n_below_target"] = n_below
            for p in PAIRS:
                if p in state["by_pair"]:
                    state["by_pair"][p]["below"] = pair_below.get(p, 0)
        return state
    return {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "positions": [], "closed_trades": [],
        "last_entry": {}, "total_pnl": 0.0, "n_trades": 0, "n_wins": 0,
        "n_below_target": 0,
        "by_pair": {p: {"pnl": 0, "n": 0, "wins": 0, "below": 0} for p in PAIRS},
        "hold_buckets": {"1-6h": [], "6-12h": [], "12-24h": [], "24-30h": []},
    }

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


# ── EDGE-GATE / STANDBY (2026-08-11): standby saat regime flapping → blok entry
GATE_FILE = PROJECT / "data" / "paper_test_edge_gate.json"
_gate_cache = {"ts": 0.0, "data": {}}


def direction_gate_blocks(label, direction):
    now = time.time()
    if now - _gate_cache["ts"] > 60:
        try:
            _gate_cache["data"] = json.loads(GATE_FILE.read_text())
            _gate_cache["ts"] = now
        except Exception:
            _gate_cache["data"] = {}
    data = _gate_cache["data"]
    # Staleness guard: a frozen gate (writer down) must NOT permanently block a
    # paper track. >90min stale -> fail-OPEN. Fixes silent-freeze from dead writer.
    try:
        if time.time() - GATE_FILE.stat().st_mtime > 5400:
            return False
    except Exception:
        return False
    # _STANDBY (blanket flapping-block) is advisory for PAPER data collection:
    # flapping is exactly when we want samples. Keep only the surgical, evidence-
    # based per-direction PAUSE (anti-predictive, n>=8).
    g = (data.get("gate") or {}).get(label) or {}
    agg = data.get("_AGGREGATE") or {}
    return g.get(direction) == "PAUSE" or agg.get(direction) == "PAUSE"

def log_trade(pos):
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(pos, default=str) + "\n")

# ── Cycle ────────────────────────────────────────────────────────────────
# ── KONTROL RANDOM (audit 30-Sep-2026) ───────────────────────────────────────
# Tanpa kontrol acak, angka lane ini TIDAK interpretable (uji falsifikasi lane CEX
# membuktikan sinyal bisa KALAH dari random: Δmean −0.249 pp). Desain mengikuti
# kontrol lane CEX/REAL-wide yang sudah terbukti: MESIN EXIT SAMA, entry TANPA
# filter alpha, arah regime-matched, SLOT TERPISAH (anti-kelaparan), laju tetap.
TRACK_SIGNAL = "SIGNAL"
TRACK_RANDOM = "RANDOM"
RANDOM_CONTROL_ENABLED = os.environ.get("SW_RANDOM_CONTROL", "1") == "1"
RANDOM_ENTRY_P = float(os.environ.get("SW_RANDOM_ENTRY_P", "0.03"))
MAX_RANDOM = int(os.environ.get("SW_MAX_RANDOM", "2"))
_RNG = random.Random(int(os.environ.get("SW_RANDOM_SEED", "20260930")))

# ── MODEL FILL BERBASIS LEVEL (audit 1-Okt-2026, approved user) ──────────────
# Exit lama memakai harga POLL: TP/stop tercatat jauh di luar level yang
# dikonfigurasi (artefak menggelembungkan hasil). Model order rest di venue:
# TP = limit terisi tepat di level; SL/EMERGENCY_SL = stop-market di level
# - slippage; SL_PROTECT = stop protektif di +PARTIAL_PCT. Exit market
# (TIME_*, REGIME_FLIP) tetap memakai harga poll. Rollback: SW_LEVEL_FILL=0.
SW_LEVEL_FILL = os.environ.get("SW_LEVEL_FILL", "1") == "1"
SW_SLIP_BPS = float(os.environ.get("SW_SLIP_BPS", "5"))
SW_SLIP = SW_SLIP_BPS / 10000.0


def sw_fill_for(reason, entry_p, tp, sl, px):
    """Harga fill realistis per jenis exit (order rest di venue)."""
    if reason == "TP":
        return entry_p * (1 + tp)
    if reason == "SL":
        return entry_p * (1 - sl) * (1 - SW_SLIP)
    if reason == "EMERGENCY_SL":
        return entry_p * (1 - sl * 2.0) * (1 - SW_SLIP)
    if reason == "SL_PROTECT":
        return entry_p * (1 + PARTIAL_PCT)
    return px


def _random_entry_decision(rng_val: float, open_tracks, max_random: int = MAX_RANDOM,
                           p: float = RANDOM_ENTRY_P) -> bool:
    """True bila kontrol RANDOM boleh membuka posisi siklus ini (murni, teruji)."""
    if not RANDOM_CONTROL_ENABLED:
        return False
    if sum(1 for t in open_tracks if t == TRACK_RANDOM) >= max_random:
        return False
    return rng_val < p


def run_cycle(do_entries: bool = True):
    now = datetime.now(timezone.utc)
    state = load_state()
    prices = fetch_prices()

    # Check exits
    for pos in state["positions"]:
        pair = pos["pair"]
        entry_p = pos["entry_price"]
        current_p = prices.get(pair, entry_p)
        gross = (current_p - entry_p) / entry_p
        hold_h = (now - datetime.fromisoformat(pos["entry_time"])).total_seconds() / 3600
        spread = SPREADS.get(pair, 0.005)

        exit_ok = False
        reason = ""
        # EXIT PARTIAL: saat gross >= +1.2%, kunci 50% profit; SL sisa protektif +1.2%
        if EXIT_MODE == "partial" and not pos.get("partial_done") and gross >= PARTIAL_PCT:
            pos["partial_done"] = True
            pos["partial_price"] = current_p
            pos["partial_pnl"] = PARTIAL_FRAC * PARTIAL_PCT   # 50% x +1.2% = +0.6% terkunci
            print(f"  PARTIAL {pair}: kunci {PARTIAL_FRAC:.0%} di +{PARTIAL_PCT:.1%} (${pos['partial_pnl']*NOTIONAL*LEVERAGE:+.2f})")

        _tp, _sl = eff_tp_sl(pos)
        # TRAIL (A/B 8b): puncak untung wajib disimpan agar bertahan antar siklus.
        _peak = max(float(pos.get("peak_gross") or 0.0), gross)
        pos["peak_gross"] = _peak
        if gross >= _tp:
            exit_ok = True
            reason = "TP"
        elif trail_decision(_peak, gross, _sl):
            exit_ok = True
            reason = "TRAIL"
        elif gross <= -(_sl * 2.0):
            # EMERGENCY HARD SL: 2× normal SL — thesis definitively invalidated.
            # Fires regardless of MIN_HOLD_SL_H (no min-hold protection).
            # Scientific basis: if price moves 2% against a 1%-SL swing trade,
            # the setup was wrong. Continuing to hold = gambler's ruin.
            # Prevents the observed -2.88% SUI scenario from compounding to -5%.
            exit_ok = True
            reason = "EMERGENCY_SL"
        elif EXIT_MODE == "partial" and pos.get("partial_done"):
            if gross <= PARTIAL_PCT and hold_h >= MIN_HOLD_SL_H:
                exit_ok = True
                reason = "SL_PROTECT"   # sisa 50% dilindungi di +1.2%
        elif gross <= -_sl and hold_h >= MIN_HOLD_SL_H:
            exit_ok = True
            reason = "SL"
        elif hold_h >= TIME_STOP_H:
            exit_ok = True
            reason = f"TIME_{TIME_STOP_H}h"
        elif SW_REGIME_FLIP and hold_h >= MIN_HOLD_SL_H and gross < _tp * 0.5:
            # REGIME_FLIP early exit: position is past the min-hold gate, not
            # trending toward TP, AND the 1h trend has reversed + 30m confirms.
            # Fixes the 12-24h "dead zone" (empirical avg=-0.483%) where the
            # SL was armed at t=0 but MIN_HOLD_SL_H=12 prevents firing.
            try:
                import regime_filter as rf
                _sym = f"{pair}USDT"
                if not rf.entry_regime_ok(_sym) and rf.fast_regime_bad(_sym):
                    exit_ok = True
                    reason = "REGIME_FLIP"
            except Exception:
                pass

        if exit_ok:
            # Harga FILL: TP/SL/EMERGENCY_SL/SL_PROTECT = level order rest di venue;
            # TIME_*/REGIME_FLIP = market (harga poll). Deteksi tetap di harga poll.
            fill_px = sw_fill_for(reason, entry_p, _tp, _sl, current_p) if SW_LEVEL_FILL else current_p
            gross_fill = (fill_px - entry_p) / entry_p
            # PnL: partial → total = 50%x(+1.2%) + 50%x(gross sisa dari entry)
            if EXIT_MODE == "partial" and pos.get("partial_done"):
                total_gross = pos["partial_pnl"] + PARTIAL_FRAC * gross_fill
            else:
                total_gross = gross_fill
            # BIAYA BENAR (audit 30-Sep-2026): taker 2 sisi + spread 2 sisi + funding.
            net = total_gross - float(_rt_cost(venue="perps", order_type="taker",
                                                    pair=pair, include_funding=True))
            pnl_usd = net * NOTIONAL * LEVERAGE
            wallet_roi = pnl_usd / TOTAL_WALLET_CAPITAL
            below_target = wallet_roi < TARGET_MIN_PCT
            pos["exit_price"] = fill_px
            pos["fill_model"] = "level" if fill_px != current_p else "poll"
            pos["exit_time"] = now.isoformat()
            pos["exit_reason"] = reason
            pos["status"] = "CLOSED"
            pos["pnl_pct"] = net
            pos["pnl_usd"] = pnl_usd
            pos["wallet_roi"] = wallet_roi
            pos["hold_hours"] = hold_h
            pos["below_target"] = below_target

            state["closed_trades"].append(pos)
            state["total_pnl"] += pnl_usd
            state["n_trades"] += 1
            if pnl_usd > 0:
                state["n_wins"] += 1
            state["by_pair"][pair]["pnl"] += pnl_usd
            state["by_pair"][pair]["n"] += 1
            if below_target:
                state["n_below_target"] += 1
                state["by_pair"][pair]["below"] += 1
            if pnl_usd > 0:
                state["by_pair"][pair]["wins"] += 1

            if hold_h <= 6:
                state["hold_buckets"]["1-6h"].append(net)
            elif hold_h <= 12:
                state["hold_buckets"]["6-12h"].append(net)
            elif hold_h <= 24:
                state["hold_buckets"]["12-24h"].append(net)
            else:
                state["hold_buckets"]["24-30h"].append(net)

            log_trade(pos)
            print(f"  CLOSED {pair}: {reason} | ${pnl_usd:+.2f} ({net:+.3%}) | {hold_h:.1f}h")

    state["positions"] = [p for p in state["positions"] if p.get("status") != "CLOSED"]

    # Entry scan — skipped on fast exit-only cycles (do_entries=False)
    # Cap PER-TRACK: RANDOM tidak boleh memakan slot SIGNAL (anti-kelaparan).
    total_open = len(state["positions"])
    _signal_open = sum(1 for p in state["positions"]
                       if p.get("track", TRACK_SIGNAL) == TRACK_SIGNAL)
    if do_entries and _signal_open < MAX_TOTAL_POSITIONS:
        for pair in PAIRS:
            pair_open = sum(1 for p in state["positions"] if p.get("pair") == pair)
            if pair_open >= MAX_POSITIONS:
                continue

            # Cooldown
            last_entry = state["last_entry"].get(pair)
            if last_entry:
                last_dt = datetime.fromisoformat(last_entry)
                if (now - last_dt).total_seconds() / 3600 < COOLDOWN_HOURS:
                    continue

            try:
                data = fetch_ohlcv(BINANCE_SYMBOLS[pair], limit=300)
                sig = check_signal(data, pair)

                if sig.get("active") and SW_BLOCK_LONG_SIGNAL:
                    # Keputusan Owner 2026-11-07: LONG-sinyal dihentikan. SENGAJA tidak
                    # `continue` — kalau continue, blok kontrol RANDOM untuk pair yang sama
                    # ikut terlewat dan lane kehilangan pembandingnya.
                    _block_log("SWING", pair)
                if sig.get("active") and not SW_BLOCK_LONG_SIGNAL:
                    if direction_gate_blocks("SWING", "LONG"):
                        continue   # STANDBY/PAUSE → skip
                    if SW_MACRO_GUARD:
                        try:
                            from anantara.macro_gate import block_reason as _macro_block
                            _why = _macro_block("LONG")
                        except Exception as _e:
                            _why = None
                            print(f"  macro_gate error (fail-open): {_e}")
                        if _why:
                            print(f"  SKIP {pair}: macro gate {_why}")
                            continue
                    current_p = prices[pair]
                    _tp_e, _sl_e = eff_tp_sl({"atr_pct": sig.get("atr_pct", 0)})
                    tp_price = current_p * (1 + _tp_e)
                    sl_price = current_p * (1 - _sl_e)
                    trade_id = f"{pair}_{now.strftime('%Y%m%d_%H%M%S')}"

                    pos = {
                        "id": trade_id, "pair": pair, "entry_price": current_p,
                        "track": TRACK_SIGNAL,
                        "entry_time": now.isoformat(), "direction": "LONG",
                        "tp_price": tp_price, "sl_price": sl_price,
                        "time_stop_time": (now + timedelta(hours=TIME_STOP_H)).isoformat(),
                        "status": "OPEN", "regime": sig.get("regime", ""),
                        "conviction": sig.get("conviction", 0),
                        "atr_pct": sig.get("atr_pct", 0),
                        "entry_reasons": sig.get("reasons", []),
                    }
                    state["positions"].append(pos)
                    state["last_entry"][pair] = now.isoformat()
                    print(f"  NEW {pair}: ${current_p:.2f} | Conv:{sig['conviction']:.0%} | Checks:{'+'.join(sig.get('reasons',[]))}")

                # ── KONTROL RANDOM: entry TANPA sinyal alpha (MESIN EXIT SAMA) ──
                # Bar & data SAMA dengan kandidat SIGNAL (i = bar tertutup), ATR dari
                # fungsi yang sama → geometri exit identik, jadi yang diuji benar-benar
                # ENTRY TIMING. Sengaja TANPA filter alpha (kalau ikut difilter, ia
                # bukan kontrol). Arah tetap regime-matched agar adil.
                _tracks_open = [x.get("track", TRACK_SIGNAL) for x in state["positions"]]
                if _random_entry_decision(_RNG.random(), _tracks_open) \
                        and not direction_gate_blocks("SWING", "LONG"):
                    _i = len(data["close"]) - 2
                    if _i >= 20:
                        _atr_pct = float(atr(data["high"], data["low"], data["close"])[_i]
                                         / data["close"][_i])
                        _tp_r, _sl_r = eff_tp_sl({"atr_pct": _atr_pct})
                        _rp = prices[pair]
                        state["positions"].append({
                            "id": f"{pair}_{now.strftime('%Y%m%d_%H%M%S')}_R",
                            "pair": pair, "entry_price": _rp,
                            "track": TRACK_RANDOM,
                            "entry_time": now.isoformat(), "direction": "LONG",
                            "tp_price": _rp * (1 + _tp_r), "sl_price": _rp * (1 - _sl_r),
                            "time_stop_time": (now + timedelta(hours=TIME_STOP_H)).isoformat(),
                            "status": "OPEN", "regime": "RANDOM_CONTROL", "conviction": 0,
                            "atr_pct": _atr_pct, "entry_reasons": ["random"],
                        })
                        state["last_entry"][pair] = now.isoformat()
                        print(f"  NEW {pair}: RANDOM control @${_rp:.2f}")
            except Exception as e:
                print(f"  Signal error {pair}: {e}")

    save_state(state)

    # Summary
    wr = state["n_wins"] / max(state["n_trades"], 1)
    by_pair_str = " | ".join(
        f"{p}:{state['by_pair'][p]['pnl']:+.0f}/{state['by_pair'][p]['n']}t"
        for p in PAIRS
    )
    b30 = state["hold_buckets"].get("24-30h", [])
    b30_avg = np.mean(b30) if b30 else 0
    thr = 1 - state["n_below_target"] / max(state["n_trades"], 1)
    print(f"  State: {state['n_trades']}t WR:{wr:.1%} PnL:${state['total_pnl']:+.0f} "
          f"Open:{len(state['positions'])} | {by_pair_str} | 24-30h:{b30_avg:+.3%}(n={len(b30)}) "
          f"| ≥0.7%:{thr:.0%}")

    # Monitor JSON
    monitor = {
        "timestamp": now.isoformat(),
        "prices": prices,
        "n_trades": state["n_trades"], "n_wins": state["n_wins"],
        "win_rate": wr, "total_pnl": state["total_pnl"],
        "open_positions": len(state["positions"]),
        "by_pair": state["by_pair"],
        "n_below_target": state["n_below_target"],
        "target_hit_rate": 1 - state["n_below_target"] / max(state["n_trades"], 1),
        "hold_buckets": {k: {"n": len(v), "avg": float(np.mean(v)) if v else 0} for k, v in state["hold_buckets"].items()},
    }
    with open(MONITOR_JSON, "w") as f:
        json.dump(monitor, f, indent=2)

    return state

def print_status():
    state = load_state()
    wr = state["n_wins"] / max(state["n_trades"], 1)
    print(f"📊 PAPER TEST STATUS — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  Pairs: {', '.join(PAIRS)}")
    print(f"  Trades: {state['n_trades']} closed | WR: {wr:.1%} | PnL: ${state['total_pnl']:+.2f}")
    print(f"  Open: {len(state['positions'])}")
    for p in state["positions"]:
        print(f"    {p['id']}: {p['pair']} ${p['entry_price']:.2f} TP:${p['tp_price']:.2f} SL:${p['sl_price']:.2f}")
    print(f"  By pair:")
    for pair in PAIRS:
        bp = state["by_pair"].get(pair, {"pnl": 0, "n": 0, "wins": 0})
        pwr = bp["wins"] / max(bp["n"], 1)
        print(f"    {pair}: PnL ${bp['pnl']:+.0f} | {bp['n']}t | WR {pwr:.0%}")
    print(f"  Hold buckets:")
    for k, v in state["hold_buckets"].items():
        print(f"    {k}: n={len(v)} avg={np.mean(v):+.3%}" if v else f"    {k}: empty")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.status:
        print_status()
        return
    if args.once:
        run_cycle()
        return
    if args.loop:
        # Fast-exit architecture: poll exits every 60s, entries every N cycles
        # where N = interval // 60 (default interval=300 → entries every 5 cycles).
        # Achieves 5× faster exit response vs original 300s monolithic loop while
        # keeping the same effective entry frequency. Addresses: "kurang cepat
        # merespon perubahan arah market" (user-identified weakness).
        _EXIT_POLL = 60
        _n_entry = max(args.interval // _EXIT_POLL, 1)
        _c = 0
        print(f"🔄 GATE 2 PAPER TEST v3 — 17-Asset Universe ({', '.join(PAIRS[:5])}...)")
        print(f"   Exit poll: {_EXIT_POLL}s | Entry every {_n_entry} cycles (~{_n_entry*_EXIT_POLL}s)")
        print(f"   TP: {TP_PCT:.1%} | SL: {SL_PCT:.1%} (min hold {MIN_HOLD_SL_H}h) | Max: {MAX_TOTAL_POSITIONS} pos")
        while True:
            try:
                _do_entries = (_c % _n_entry == 0)
                print(f"\n[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC]"
                      f" {'ENTRY+EXIT' if _do_entries else 'EXIT-ONLY'}")
                run_cycle(do_entries=_do_entries)
                _c += 1
            except KeyboardInterrupt:
                print("\n⏹️  Stopped.")
                break
            except Exception as e:
                print(f"  ❌ {e}")
            time.sleep(_EXIT_POLL)

if __name__ == "__main__":
    main()
