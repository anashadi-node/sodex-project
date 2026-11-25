#!/usr/bin/env python3
"""
ANANTARA SAKTI — Two-Way Swing LEARNING Track (LONG + SHORT, 1h-30h band)
=========================================================================
Added 2026-08-06 per user approval ("melebarkan strategi: SHORT + timeframe"):
swing/realwide adalah LONG-only → jarang fire di regime non-bull → nol learning.
Track ini menambah kaki SHORT simetris (bear-momentum) dengan geometri REAL-wide
(SL -2% AKTIF dari t=0, TP +4%, 3×, time-stop 30h) → trade mengalir di BULL dan
BEAR → data belajar naik cepat menuju SIGNIFICANT (n>=20).

SINYAL pada bar TERTUTUP (len-2). RELAXED learning mode default (PAPER_RELAXED=1).
⚠️ LEARNING/COLLECTION ONLY — BUKAN bukti Gate-2. Promosi tetap pakai sinyal
STRICT (PAPER_RELAXED=0).

Universe: BTC, ETH, SOL, DOGE (likuid + spread SoDEX diketahui).
Run: python3 scripts/paper_test_twoway.py --loop --interval 300
"""
import argparse, json, os, random, sys, time
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

PROJECT = Path(__file__).resolve().parents[1]
from cost_model import round_trip_frac as _rt_cost  # SUMBER TUNGGAL biaya (audit 30-Sep-2026)
STATE_FILE = Path(os.environ.get("TW_STATE_FILE", str(PROJECT / "data" / "paper_test_twoway_state.json")))
LOG_FILE = Path(os.environ.get("TW_LOG_FILE", str(PROJECT / "data" / "paper_test_twoway.jsonl")))
MON_JSON = Path(os.environ.get("TW_MON_JSON", str(PROJECT / "data" / "paper_test_twoway_latest.json")))

# ── Telemetri funnel (DEFAULT OFF, TW_FUNNEL=1 untuk hidupkan) ────────────────
# Kenapa ada: arm riset bisa 0 trade berhari-hari dan penyebabnya hanya dugaan
# ("gate momentum BTC"). Funnel mencatat berapa kali TIAP cabang gate diambil
# per siklus, sehingga bottleneck dibuktikan dari data, bukan hipotesis.
# Tidak mengubah satu pun keputusan trading: semua counter dipasang SEBELUM
# `continue`/`break` yang sudah ada. Path default diturunkan dari STATE_FILE
# supaya tiap arm punya file sendiri (pelajaran: satu file bersama = saling timpa).
FUNNEL_ENABLED = os.environ.get("TW_FUNNEL", "0") == "1"
FUNNEL_JSON = Path(os.environ.get(
    "TW_FUNNEL_JSON", str(STATE_FILE.with_name(f"{STATE_FILE.stem}_funnel.json"))))
_FO: dict = {}


def _f(key: str, n: int = 1) -> None:
    """Naikkan counter funnel siklus ini (no-op total bila TW_FUNNEL=0)."""
    if FUNNEL_ENABLED:
        _FO[key] = _FO.get(key, 0) + n


def funnel_flush(now_iso: str, context: dict | None = None) -> None:
    """Tulis counter siklus + akumulasi total (atomik), lalu reset counter siklus."""
    if not FUNNEL_ENABLED or not _FO:
        return
    path = Path(FUNNEL_JSON)
    prev = {}
    try:
        prev = json.loads(path.read_text())
    except Exception:
        prev = {}
    totals = dict(prev.get("totals") or {})
    for k, v in _FO.items():
        totals[k] = totals.get(k, 0) + int(v)
    payload = {
        "timestamp": now_iso,
        "since": prev.get("since") or now_iso,
        "pid": os.getpid(),
        "state_file": str(STATE_FILE),
        "n_cycles": int(prev.get("n_cycles") or 0) + 1,
        "cycle": dict(_FO),
        "totals": totals,
        "context": context or {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    os.replace(tmp, path)
    _FO.clear()

# Universe expanded 2026-08-29 to the verified SoDEX-tradeable set (max throughput
# under the corrected TP=4% geometry). SILVER→XAGUSDT & HYPE→HYPEUSDT resolved via
# Binance-futures fallback in fetch_ohlcv/_confirm_15m (no Binance spot listing).
PAIRS = ["BTC", "ETH", "XRP", "SOL", "HYPE", "DOGE", "BCH", "ONDO", "LINK",
         "AAVE", "SUI", "ADA", "TRX", "UNI", "ENA", "XAUT", "SILVER", "ARB", "AVAX",
         "ASTER", "PUMP", "LIT", "BNB"]
BINANCE_SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "XRP": "XRPUSDT", "SOL": "SOLUSDT",
                   "HYPE": "HYPEUSDT", "DOGE": "DOGEUSDT", "BCH": "BCHUSDT", "ONDO": "ONDOUSDT",
                   "LINK": "LINKUSDT", "AAVE": "AAVEUSDT", "SUI": "SUIUSDT", "ADA": "ADAUSDT",
                   "TRX": "TRXUSDT", "UNI": "UNIUSDT", "ENA": "ENAUSDT", "XAUT": "XAUTUSDT",
                   "SILVER": "XAGUSDT", "ARB": "ARBUSDT", "AVAX": "AVAXUSDT",
                   "ASTER": "ASTERUSDT", "PUMP": "PUMPUSDT", "LIT": "LITUSDT",
                   "BNB": "BNBUSDT"}
SODEX_SYMBOLS = {p: f"{p}-USD" for p in PAIRS}
# Live-measured SoDEX spreads (2026-08-29), floored 2bps; thin-book (HYPE/SUI/SILVER) 8bps.
SPREADS = {"BTC": 0.00013, "ETH": 0.00020, "SOL": 0.00035,
           "XRP": 0.0002, "HYPE": 0.0008, "DOGE": 0.0002, "BCH": 0.0002,
           "ONDO": 0.000285, "LINK": 0.0002, "AAVE": 0.0002, "SUI": 0.0008,
           "ADA": 0.000497, "TRX": 0.0002, "UNI": 0.000227, "ENA": 0.000614,
           "XAUT": 0.000605, "SILVER": 0.0008, "ARB": 0.0002, "AVAX": 0.0002,
           "ASTER": 0.0004, "PUMP": 0.0004, "LIT": 0.0008, "BNB": 0.0002}
MAKER_FEE_RT = 0.00024

# REAL-wide geometry (corrected method: stop AKTIF dari t=0, no min-hold landmine)
# TP 2%→4% REVERTED (2026-08-29): TP=2% experiment FAILED. N=87 WR=58.6%
# avg=+0.521% — below North Star 0.7%, mathematically impossible to reach 0.7%
# with 1:1 R:R unless WR→100%. REALWIDE (TP=4%/SL=2%, N=33) avg=+1.568% PROVEN.
# Scientific basis: 2:1 R:R dengan WR=69.7% → E = 0.697×4 - 0.303×2 = 2.18% gross.
# Same geometry here with death-cross SHORT gate. Revert to 4%.
TP_PCT = float(os.environ.get("TW_TP_PCT", "0.040"))
SL_PCT = float(os.environ.get("TW_SL_PCT", "0.020"))
# A/B 9 (default OFF): sinyal terbukti ANTI-PREDICTIVE (uji matched pair x minggu,
# Delta -1,50pp @24h, q<0,001, 20/21 pair konsisten). Flag ini hanya MEMBALIK arah
# yang diperdagangkan; filter/gate tetap dinilai dari arah sinyal asli supaya
# perubahannya satu variabel. Revert: hapus env ini.
INVERT_SIGNAL = os.environ.get("TW_INVERT_SIGNAL", "0") == "1"
# A/B 9c (default OFF): hanya masuk bila harga SUDAH NAIK >= X% dalam 24 jam terakhir.
# Dasar (H5, 2026-11-07): entry SIGNAL datang setelah kenaikan 24 jam +2,68% vs RANDOM
# -1,09% (Mann-Whitney p=3e-121) dan kenaikan itu memprediksi hasil negatif di dalam
# pair yang sama (Spearman -0,046 @24j, p=0,014; -0,119 @72j, p=1,5e-10). Filter ini
# menahan hipotesis "chase" yang sama tanpa harus short ke seluruh pasar.
PRE24_MIN = os.environ.get("TW_PRE24_MIN") or None
PRE24_MIN = None if PRE24_MIN is None else float(PRE24_MIN)
# Keputusan Owner 2026-11-07: hentikan entry yang DIPERDAGANGKAN sebagai LONG di lane
# twoway produksi (lihat SW_BLOCK_LONG_SIGNAL untuk bukti). Dicek SETELAH
# invert_direction -> lane riset 9a/9b/9c (arah akhir SHORT) tidak terpengaruh.
BLOCK_LONG_SIGNAL = os.environ.get("TW_BLOCK_LONG_SIGNAL", "0").strip() not in ("0", "false", "False", "no")

_BLOCK_LOGGED: dict = {}


def _block_log(label: str, pair: str, ttl: float = 3600.0) -> None:
    """Cetak 1x/jam per pair saat entry diblokir — jejak audit, bukan spam log."""
    now = time.time()
    if now - _BLOCK_LOGGED.get((label, pair), 0.0) < ttl:
        return
    _BLOCK_LOGGED[(label, pair)] = now
    print(f"  SKIP {pair}: LONG-sinyal dihentikan (keputusan Owner 2026-11-07)")
LEVERAGE = 3
TIME_STOP_H = float(os.environ.get("TW_TIME_STOP_H", "30"))   # covers target 1h-30h (North Star)
TARGET_MIN_PCT = 0.008    # North Star: ≥0.8% net per 30h window (user GO 27-Sep)
COOLDOWN_H = float(os.environ.get("TW_COOLDOWN_H", "12"))
MAX_POSITIONS = 1          # per pair
MAX_TOTAL_POSITIONS = int(os.environ.get("TW_MAX_SIGNAL", "6"))   # 19-asset universe (2026-08-29) → more concurrent samples
NOTIONAL = float(os.environ.get("TW_NOTIONAL", "100.0"))

# ── Self-heal feed (audit 19-Okt-2026) ────────────────────────────────────────
# 11–19 Okt 2026 unit ini buta 8 hari: semua pair "no klines" tapi proses tetap
# hidup (0 restart). Tiga siklus entry berturut dengan SEMUA pair gagal fetch =
# koneksi proses rusak → keluar dengan kode 2 supaya systemd membuat proses baru.
EMPTY_STREAK_LIMIT = 3
_EMPTY_STREAK = 0
# Observability: tanpa ini, FATAL "feed buta" hanya bilang "semua pair gagal fetch"
# tanpa menyebut penyebabnya (insiden 2026-11-09 07:13-08:44 tidak bisa didiagnosis).
_LAST_FETCH_ERR = ""


def _feed_streak_next(prev: int, attempted: int, ok: int, min_pairs: int = 5) -> int:
    """Perbarui hitungan siklus berturut semua-fetch-gagal.

    Hanya dihitung bila ada percobaan fetch yang cukup; pair yang dilewati gate
    (cooldown/pair-gate/slot penuh) tidak dianggap kegagalan feed.
    """
    if attempted >= min_pairs and ok == 0:
        return prev + 1
    return 0


def _read_wallet_capital() -> float:
    env_val = os.environ.get("SODEX_TOTAL_WALLET")
    if env_val:
        return float(env_val)
    gt = Path(__file__).resolve().parents[1] / "data" / "ground_truth.json"
    if gt.exists():
        try:
            with open(gt) as _f:
                _d = json.load(_f)
            total = _d.get("hl_total", {}).get("observed_account_value_usd", 0)
            if total >= 100:
                return float(total)
        except Exception:
            pass
    return NOTIONAL * LEVERAGE  # denominator = actual exposure


TOTAL_WALLET_CAPITAL = _read_wallet_capital()

SODEX_TICKERS = "https://mainnet-gw.sodex.dev/api/v1/perps/markets/tickers"
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"

# Learning knobs (env-tunable). Relaxed default utk alir data belajar.
_RELAXED = os.environ.get("PAPER_RELAXED", "1") == "1"
_ADX_MIN = float(os.environ.get("PAPER_ADX_MIN", "15" if _RELAXED else "25"))
_MIN_CHECKS = int(os.environ.get("PAPER_MIN_CHECKS", "3" if _RELAXED else "4"))
_REQUIRE_GOLDEN = os.environ.get("PAPER_REQUIRE_GOLDEN", "0" if _RELAXED else "1") == "1"

# CHOP regime gate (RCA 2026-09-15): TWO-WAY LONG PnL by BTC daily regime:
# BULL n=102 +$281.22 vs CHOP n=97 -$131.46. SHORT leg tetap disabled by
# evidence. Gate hanya memblok entry LONG baru saat CHOP; open positions tetap
# dikelola exit. PAPER_CHOP_GATE=0 disables for experiment.
CHOP_GATE_ENABLED = os.environ.get("PAPER_CHOP_GATE", "1") == "1"
_chop_regime_cache = {"ts": 0.0, "regime": None}

# Kuota riset (2026-11-13): arm eksperimen AB9a/9b/9c berjalan 6 hari dengan
# 0 entry karena gate BTC momentum selalu memblok (regime BEAR). Tanpa data,
# uji A/B tidak menghasilkan bukti apa pun. Dengan PAPER_BTC_GATE_QUOTA=N,
# arm itu boleh melewati gate maksimum N entry per siklus. Default 0 =
# perilaku produksi tidak berubah (hanya unit riset yang menyalakan).
BTC_GATE_QUOTA = int(os.environ.get("PAPER_BTC_GATE_QUOTA", "0") or 0)
# Kaki SHORT (2026-11-13): dimatikan hardcoded sejak 2026-09-02. Di regime BEAR
# itu membuat lane buta satu arah (funnel: reason_no_signal 22/23 pair, 0 entry
# 6 hari). Nyalakan hanya untuk arm riset lewat env; default 0.
SHORT_LEG_ENABLED = os.environ.get("TW_SHORT_LEG", "0") == "1"
_btc_quota: dict[str, int] = {"signal": 0, "random": 0}


def btc_gate_pass(label: str) -> bool:
    """True bila gate BTC lolos, atau kuota riset label ini masih tersedia.

    Kuota dipisah per label: kalau digabung, arm RANDOM (dievaluasi lebih dulu)
    menghabiskan kuota dan arm SIGNAL tetap 0 entry — persis data yang dibutuhkan
    uji A/B hilang.
    """
    if btc_momentum_ok():
        return True
    if BTC_GATE_QUOTA > 0 and _btc_quota.get(label, 0) < BTC_GATE_QUOTA:
        _btc_quota[label] = _btc_quota.get(label, 0) + 1
        _f(f"quota_pass_{label}")
        return True
    return False


def btc_daily_regime(max_age_s=900):
    now = time.time()
    if now - float(_chop_regime_cache["ts"]) < max_age_s:
        return _chop_regime_cache["regime"]
    reg = None
    try:
        rows = _raw_klines("BTCUSDT", "1d", 210)
        if isinstance(rows, list) and len(rows) >= 201:
            c = [float(x[4]) for x in rows]
            i = len(c) - 1
            sma200 = sum(c[i - 199:i + 1]) / 200
            mom = c[i] / c[i - 1] - 1
            if c[i] > sma200 and mom > 0:
                reg = "BULL"
            elif c[i] < sma200 and mom < 0:
                reg = "BEAR"
            else:
                reg = "CHOP"
    except Exception:
        reg = None
    _chop_regime_cache["ts"] = now
    _chop_regime_cache["regime"] = reg
    return reg


# ── A/B 3 (disetujui Owner 2026-11-06): regime entry gate ────────────────────
# Falsifikasi pada ledger internal (entry-time, forward-looking, close sebelum
# entry): blok entry baru saat momentum BTC N-hari NEGATIF.
#   twoway  n=599 keep 457 +0.110%/tr vs block 142 -0.441%/tr  delta +0.551pp p=0.011
#   swing   n=926 keep 597 -0.037%     vs block 329 -0.238%     delta +0.201pp p=0.0155
#   partial n=1000 keep 642 -0.056%    vs block 358 -0.202%     delta +0.146pp p=0.0198
#   strict  n=593  TIDAK ada efek (p=0.31) -> sengaja tidak dipasang di arm itu.
# Default OFF supaya arm kontrol identik; fail-open bila feed Binance gagal.
TW_REGIME_GATE = os.environ.get("TW_REGIME_GATE", "0") == "1"
TW_REGIME_MOM_DAYS = int(os.environ.get("TW_REGIME_MOM_DAYS", "30"))
_regime_mom_cache = {"ts": 0.0, "ok": True}


def btc_momentum_ok(days=None, max_age_s=900):
    """True = boleh entry baru. False = BTC momentum N-hari negatif."""
    if not TW_REGIME_GATE:
        return True
    now = time.time()
    if now - float(_regime_mom_cache["ts"]) < max_age_s:
        return bool(_regime_mom_cache["ok"])
    days = int(days or TW_REGIME_MOM_DAYS)
    ok = True
    try:
        rows = _raw_klines("BTCUSDT", "1d", days + 5)
        if isinstance(rows, list) and len(rows) > days:
            c = [float(x[4]) for x in rows]
            ok = (c[-1] / c[-1 - days] - 1) >= 0
    except Exception:
        ok = True          # fail-open: data hilang != bukti regime jelek
    _regime_mom_cache["ts"] = now
    _regime_mom_cache["ok"] = ok
    return ok


def fetch_prices():
    prices = {}
    try:
        r = requests.get(SODEX_TICKERS, timeout=10)
        data = r.json()
        tickers = data if isinstance(data, list) else data.get("data", data.get("result", []))
        for pair in PAIRS:
            match = [t for t in tickers if t.get("symbol") == SODEX_SYMBOLS[pair]]
            if match:
                prices[pair] = float(match[0].get("lastPx", 0) or 0)
    except Exception:
        pass
    if len(prices) < len(PAIRS):
        for pair in PAIRS:
            try:
                r = requests.get("https://api.binance.com/api/v3/ticker/price",
                                 params={"symbol": BINANCE_SYMBOLS[pair]}, timeout=10)
                prices[pair] = float(r.json()["price"])
            except Exception:
                pass
    return prices


def rsi(c, p=14):
    d = np.diff(c, prepend=c[0])
    g = np.where(d > 0, d, 0.0); l = np.where(d < 0, -d, 0.0)
    ag = pd.Series(g).ewm(span=p, adjust=False).mean().values
    al = pd.Series(l).ewm(span=p, adjust=False).mean().values
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.divide(ag, al, out=np.ones_like(ag), where=al > 0)
    return 100.0 - (100.0 / (1.0 + rs))


def sma(c, p):
    return pd.Series(c).rolling(p).mean().values


def rr(c, lb):
    r = np.full_like(c, np.nan); r[lb:] = (c[lb:] - c[:-lb]) / c[:-lb]
    return r


def adx(h, l, c, p=14):
    tr = np.maximum(h - l, np.maximum(abs(h - np.roll(c, 1)), abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    t = pd.Series(tr).ewm(span=p, adjust=False).mean().values
    u = h - np.roll(h, 1); d = np.roll(l, 1) - l
    pdm = np.where((u > d) & (u > 0), u, 0.0); ndm = np.where((d > u) & (d > 0), d, 0.0)
    pdi = 100 * pd.Series(pdm).ewm(span=p, adjust=False).mean().values / t
    ndi = 100 * pd.Series(ndm).ewm(span=p, adjust=False).mean().values / t
    return pd.Series(100 * abs(pdi - ndi) / (pdi + ndi + 1e-10)).ewm(span=p, adjust=False).mean().values


_LAST_KLINES_ERR = {}  # sym -> alasan gagal terakhir (status/exception), diagnostik saja
# Anggaran retry PER SIKLUS. Alasan: blackout Binance bersifat total per siklus
# (23/23 pair gagal bersamaan, 49 kejadian terukur). Tanpa anggaran, retry 2x
# menggandakan beban (46 req) tepat saat endpoint sedang membatasi kita →
# memperpanjang blackout. Habis anggaran = lanjut tanpa retry sampai siklus
# berikutnya (tidak mengubah keputusan trading, hanya beban jaringan).
RETRY_BUDGET_PER_CYCLE = int(os.environ.get("TW_RETRY_BUDGET", "4"))
_RETRY_BUDGET = None  # None = tanpa batas (pemanggilan di luar siklus)


def _raw_klines(sym, interval, limit, attempts=2):
    """Spot klines, fallback to Binance futures (fapi) for perp-only symbols
    (HYPE, XAG/silver). Same row schema; existing spot pairs never hit fapi.

    Retry 2x dengan backoff kecil: kegagalan transien (429/timeout) sebelumnya
    membuat pair di-skip diam-diam (23% scan gagal pada 2026-11-12) sehingga
    entry bergantung pada keberuntungan API, bukan pada sinyal.
    """
    reason = "tidak ada respons"
    global _RETRY_BUDGET
    n_att = max(attempts, 1)
    if _RETRY_BUDGET is not None and _RETRY_BUDGET <= 0:
        n_att = 1   # anggaran siklus habis → jangan tambah beban saat outage
    for _ in range(n_att):
        for base in (BINANCE_KLINES, "https://fapi.binance.com/fapi/v1/klines"):
            try:
                r = requests.get(base, params={"symbol": sym, "interval": interval,
                                               "limit": limit}, timeout=15,
                                 headers={"User-Agent": "anantara-sakti/1.0"})
                if r.status_code != 200:
                    reason = f"HTTP {r.status_code} {base.split('/')[2]}"
                    continue
                k = r.json()
                if isinstance(k, list) and len(k) >= 2:
                    _LAST_KLINES_ERR.pop(sym, None)
                    return k
                reason = f"body bukan list {base.split('/')[2]}"
            except Exception as e:  # noqa: BLE001 — jaringan/timeout apa pun
                reason = f"{type(e).__name__} {base.split('/')[2]}"
                continue
        if _RETRY_BUDGET is not None:
            if _RETRY_BUDGET <= 0:
                break
            _RETRY_BUDGET -= 1
        time.sleep(0.4)
    _LAST_KLINES_ERR[sym] = reason[:120]
    return []


def fetch_ohlcv(sym, limit=300):
    data = _raw_klines(sym, "1h", limit)
    if not data:
        raise RuntimeError(f"API error {sym}: no klines (spot+fapi), "
                           f"sebab={_LAST_KLINES_ERR.get(sym, 'unknown')}")
    return {"close": np.array([float(x[4]) for x in data]),
            "high": np.array([float(x[2]) for x in data]),
            "low": np.array([float(x[3]) for x in data]),
            "volume": np.array([float(x[5]) for x in data])}


def _atr_pct(d, period=14):
    """ATR(period)/close pada bar terakhir — RECORDING ONLY.

    Diverifikasi 22-Okt-2026: field `atr_pct` pada state sebelumnya hardcode 0.0
    dan TIDAK PERNAH dibaca oleh logika entry/exit/sizing mana pun. Fungsi ini
    hanya mengisi nilai yang benar agar diagnostik (sizing, filter volatilitas,
    TP adaptif) punya data bila kelak dipakai — tidak mengubah keputusan apa pun.
    Fail-open: error/kurang data -> 0.0 (perilaku lama).
    """
    try:
        h, l, c = d["high"], d["low"], d["close"]
        if len(c) < period + 1:
            return 0.0
        px = float(c[-1])
        if px <= 0:
            return 0.0
        prev = c[-(period + 1):-1]
        tr = np.maximum(h[-period:] - l[-period:],
                        np.maximum(np.abs(h[-period:] - prev), np.abs(l[-period:] - prev)))
        return float(np.mean(tr) / px)
    except Exception:
        return 0.0


def _confirm_15m(pair: str, direction: str) -> bool:
    """15m SMA20 multi-timeframe alignment check — fail-OPEN on any error.

    Scientific basis (short-lag validation): 1h bar close has ~65min lag total.
    A 15m check verifies the directional bias still holds on a finer timeframe,
    reducing entries into signals that already reversed before the poll fired.
    LONG: price must be > 15m SMA20 (uptrend still valid).
    SHORT: price must be < 15m SMA20 (downtrend still valid).
    """
    try:
        sym = BINANCE_SYMBOLS.get(pair, pair + "USDT")
        k = _raw_klines(sym, "15m", 25)
        if not isinstance(k, list) or len(k) < 22:
            return True  # insufficient bars → fail-open
        c = np.array([float(x[4]) for x in k])
        i = len(c) - 2  # last fully closed 15m bar
        s20 = sma(c, 20)
        if np.isnan(s20[i]):
            return True
        if direction == "LONG":
            return bool(c[i] > s20[i])
        else:
            return bool(c[i] < s20[i])
    except Exception:
        return True  # fail-open — never block learning data collection


def check_signal(data, pair: str = ""):
    """Return LONG / SHORT / inactive. Bar terakhir TERTUTUP (len-2). Simetris dua-arah.

    Scientific improvements (2026-08-23, updated 2026-08-30):
    1. SHORT now requires death-cross (SMA50 < SMA200) as hard structural gate.
       Root cause of SHORT WR=44%: entries fired on any c<SMA50 including in
       bull uptrends where the bear leg is a pullback, not a real downtrend.
       Death-cross confirms structural bear market before committing.
    2. RSI range for SHORT changed from 40-60 → 30-48 (2026-08-30).
       RSI 40-60 for LONG = bouncing from oversold toward neutral = correct.
       RSI 40-60 for SHORT = same symmetric logic was WRONG: high RSI in bear
       leg = momentum still partially bullish = bad SHORT entry. 30-48 captures
       the confirmed bear-momentum phase. Further tightened from 55→48 after
       audit v3 confirmed 52% TIME_30h rate (n=21 SHORT).
    3. 15m multi-timeframe confirmation added for both legs.
    4. Bearish momentum gate (c[i] < c[i-1]) added for SHORT (2026-08-30):
       death-cross alone is too late — price stabilizes after the cross. Require
       the 1h candle to be actively dropping to filter oscillating post-cross.
    """
    c, h, l, v = data["close"], data["high"], data["low"], data["volume"]
    i = len(c) - 2
    if i < 200:
        return {"active": False, "reason": "insufficient_data"}
    a = adx(h, l, c); s50 = sma(c, 50); s200 = sma(c, 200)
    rv = rsi(c); s24 = sma(c, 24); va = sma(v, 24)
    vr = v[i] / va[i] if va[i] > 0 else 1.0
    r24 = rr(c, 24); r1 = rr(c, 1)

    if a[i] <= _ADX_MIN:
        return {"active": False, "reason": "no_trend"}

    # LONG leg: momentum up (c>SMA50, golden opsional)
    long_ok = c[i] > s50[i]
    if _REQUIRE_GOLDEN:
        long_ok = long_ok and s50[i] > s200[i]
    if long_ok:
        chk, reasons = 0, []
        if c[i] > s24[i]: chk += 1; reasons.append("above_sma24")
        if 40 < rv[i] < 60: chk += 1; reasons.append("rsi_mid")
        if vr > 1.1: chk += 1; reasons.append("vol_above_avg")
        if i >= 24 and not np.isnan(r24[i]) and r24[i] > 0.012: chk += 1; reasons.append("strong_24h_trend")
        if i >= 1 and not np.isnan(r1[i]) and r1[i] < 0.003: chk += 1; reasons.append("minor_pullback")
        if chk >= _MIN_CHECKS:
            if pair and not _confirm_15m(pair, "LONG"):
                return {"active": False, "reason": "15m_below_sma20"}
            return {"active": True, "direction": "LONG", "conviction": chk / 5.0,
                    "reasons": reasons, "regime": "MOMENTUM", "relaxed": _RELAXED,
                    "adx": float(a[i])}

    # SHORT leg: structural bear-momentum.
    # HARD GATE: death-cross (SMA50 < SMA200) required.
    # Rationale: c<SMA50 alone fires in bull pullbacks; death-cross confirms the
    # downtrend is structural, not a temporary dip against a bull trend.
    # SECOND GATE: bearish momentum — c[i] < c[i-1] ensures the price is still
    # actively dropping, not just oscillating below the death cross (52% TIME_30h
    # rate in audit proved death-cross alone is too late).
    # ─── DISABLED 2026-09-02 (scientific block, n≥20 & WR<40%) ───────────────
    # Data 37 SHORT trades: WR 29.7%, PnL -$55.77, ROI -1.59% wallet.
    # Post-fix gate (RSI 30-48 + momentum) n=9: WR 11.1% — LEBIH BURUK.
    # Pattern: entry saat oversold/bear-momentum → snap-back bounce → SL -2%
    # (6/9 post-fix = SL). Tidak ada edge SHORT terukur di venue SoDEX saat ini.
    # Kode dibiarkan untuk A/B re-enable jika riset venue/aset baru menunjukkan
    # edge SHORT (lihat reports/ riset venue 2026-09-02).
    #
    # 2026-11-13 — TEMUAN: di regime BEAR, LONG leg menuntut c > SMA50 sehingga
    # tidak pernah aktif, sementara short_ok = False hardcoded. Funnel arm AB9
    # menunjukkan reason_no_signal 22/23 pair selama 6 hari → 0 entry. Lane jadi
    # buta satu arah. TW_SHORT_LEG=1 menyalakan kaki SHORT HANYA untuk arm riset
    # (default 0 = perilaku produksi tidak berubah). Bukti lama n=37 tetap acuan:
    # kalau data baru tetap WR<40% pada n≥20, matikan lagi.
    short_ok = SHORT_LEG_ENABLED
    if short_ok:
        chk, reasons = 0, []
        if c[i] < s24[i]: chk += 1; reasons.append("below_sma24")
        # RSI 30-48 for SHORT: captures only confirmed bear-momentum.
        # Previous limit 30-55: 52% SHORT trades hit TIME_30h without profit
        # (audit v3, n=21). RSI 48-55 indicates weakening-but-not-dead bull
        # momentum — entries in that range are premature. 30-48 selects the
        # phase where RSI is definitively losing grip.
        if 30 < rv[i] < 48: chk += 1; reasons.append("rsi_bear_zone")
        if vr > 1.1: chk += 1; reasons.append("vol_above_avg")
        if i >= 24 and not np.isnan(r24[i]) and r24[i] < -0.012: chk += 1; reasons.append("strong_24h_drop")
        if i >= 1 and not np.isnan(r1[i]) and r1[i] > -0.003: chk += 1; reasons.append("minor_bounce")
        if chk >= _MIN_CHECKS:
            if pair and not _confirm_15m(pair, "SHORT"):
                return {"active": False, "reason": "15m_above_sma20"}
            return {"active": True, "direction": "SHORT", "conviction": chk / 5.0,
                    "reasons": reasons, "regime": "BEAR_MOMENTUM", "relaxed": _RELAXED,
                    "adx": float(a[i])}
    return {"active": False, "reason": "no_signal"}


def _migrate_below_target(st):
    """Recompute wallet_roi + below_target using current TOTAL_WALLET_CAPITAL."""
    for t in st.get("closed_trades", []):
        pnl_usd = t.get("pnl_usd")
        if pnl_usd is not None:
            new_roi = pnl_usd / TOTAL_WALLET_CAPITAL
            t["wallet_roi"] = new_roi
            t["below_target"] = new_roi < TARGET_MIN_PCT
    st["n_below_target"] = sum(
        1 for t in st.get("closed_trades", []) if t.get("below_target"))
    by_pair = st.get("by_pair") or {}
    for pair, stats in by_pair.items():
        stats["below"] = sum(
            1 for t in st.get("closed_trades", [])
            if t.get("pair") == pair and t.get("below_target"))
    return st


def load_state():
    if STATE_FILE.exists():
        try:
            st = json.loads(STATE_FILE.read_text())
            st.setdefault("n_below_target", 0)
            for p in PAIRS:
                st.setdefault("by_pair", {}).setdefault(p, {"pnl": 0, "n": 0, "wins": 0, "below": 0})
                st["by_pair"][p].setdefault("below", 0)
            _migrate_below_target(st)
            return st
        except Exception:
            pass
    return {"started_at": datetime.now(timezone.utc).isoformat(), "positions": [],
            "closed_trades": [], "last_entry": {}, "total_pnl": 0.0,
            "n_trades": 0, "n_wins": 0, "n_below_target": 0,
            "by_pair": {p: {"pnl": 0, "n": 0, "wins": 0, "below": 0} for p in PAIRS}}


def save_state(st):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE_FILE)
    try:
        dfd = os.open(STATE_FILE.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


# ── EDGE-GATE (2026-08-08): skip arah yg diukur anti-predictive (avg_fav < 40% avg_adv, n>=8)
GATE_FILE = PROJECT / "data" / "paper_test_edge_gate.json"
_gate_cache = {"ts": 0.0, "data": {}}


_PRE24_CACHE: dict = {}


def pre24_pct(pair: str, now_ts: float | None = None, ttl: float = 300.0):
    """Perubahan harga 24 jam terakhir (%) dari kline 1h. None bila data tidak cukup.

    Dipakai A/B 9c; di-cache 5 menit agar tidak menambah beban API saat loop 300 detik.
    """
    ts = now_ts if now_ts is not None else time.time()
    hit = _PRE24_CACHE.get(pair)
    if hit and ts - hit[0] < ttl:
        return hit[1]
    try:
        rows = _raw_klines(BINANCE_SYMBOLS.get(pair, pair + "USDT"), "1h", 26)
    except Exception:
        rows = []
    if len(rows) < 25:
        return None
    val = (float(rows[-1][4]) / float(rows[-25][4]) - 1) * 100
    _PRE24_CACHE[pair] = (ts, val)
    return val


def invert_direction(direction: str, invert: bool | None = None) -> str:
    """Arah yang DIPERDAGANGKAN. invert=True membalik arah sinyal saja.

    Dipakai A/B 9 (SHORT pada pilihan sinyal) karena sinyal LONG lane ini
    anti-predictive; filter entry tidak ikut berubah -> satu variabel.
    """
    if invert is None:
        invert = INVERT_SIGNAL
    if not invert:
        return direction
    return "SHORT" if direction == "LONG" else "LONG"


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
    own = g.get(direction)
    # Own significant verdict wins over the cross-track aggregate (which pools all
    # tracks incl. inferior geometries). A polluted aggregate PAUSE must not veto a
    # track whose OWN edge is proven KEEP. Own PAUSE still blocks; undecided defers.
    if own == "PAUSE":
        return True
    if own == "KEEP":
        return False
    return agg.get(direction) == "PAUSE"


def pair_gate_blocks(label, pair):
    """True = pair is a proven structural drag (learning loop pairs_pause:
    n>=8 AND pnl<0 AND WR<40%). Same cache + staleness fail-open as above."""
    now = time.time()
    if now - _gate_cache["ts"] > 60:
        try:
            _gate_cache["data"] = json.loads(GATE_FILE.read_text())
            _gate_cache["ts"] = now
        except Exception:
            _gate_cache["data"] = {}
    try:
        if time.time() - GATE_FILE.stat().st_mtime > 5400:
            return False
    except Exception:
        return False
    pp = (_gate_cache["data"].get("pairs_pause") or {}).get(label) or []
    return pair in pp


TRACK_SIGNAL = "SIGNAL"
TRACK_RANDOM = "RANDOM"
RANDOM_CONTROL_ENABLED = os.environ.get("TW_RANDOM_CONTROL", "1") == "1"
RANDOM_ENTRY_P = float(os.environ.get("TW_RANDOM_ENTRY_P", "0.03"))
MAX_RANDOM = int(os.environ.get("TW_MAX_RANDOM", "2"))
_RNG = random.Random(int(os.environ.get("TW_RANDOM_SEED", "20260930")))

# ── MODEL FILL BERBASIS LEVEL (audit 1-Okt-2026, approved user) ──────────────
# Masalah sama dengan lane REAL-wide: exit memakai harga POLL. TWOWAY punya dua
# arah, jadi slippage harus diterapkan pada sisi yang MERUGIKAN: LONG → fill di
# bawah level SL; SHORT → fill di ATAS level SL. TP (limit) selalu tepat di level.
# Rollback tanpa ubah kode: TW_LEVEL_FILL=0.
TW_LEVEL_FILL = os.environ.get("TW_LEVEL_FILL", "1") == "1"
TW_SLIP_BPS = float(os.environ.get("TW_SLIP_BPS", "5"))
TW_SLIP = TW_SLIP_BPS / 10000.0


def level_fill_price(entry, direction, cur, tp_pct=None, sl_pct=None):
    """(reason, fill_price) bila harga poll sudah melewati level TP/SL; else (None, None)."""
    tp_pct = TP_PCT if tp_pct is None else tp_pct
    sl_pct = SL_PCT if sl_pct is None else sl_pct
    is_long = direction == "LONG"
    tp_px = entry * (1 + tp_pct) if is_long else entry * (1 - tp_pct)
    sl_px = entry * (1 - sl_pct) if is_long else entry * (1 + sl_pct)
    hit_tp = cur >= tp_px if is_long else cur <= tp_px
    hit_sl = cur <= sl_px if is_long else cur >= sl_px
    if hit_tp:
        return "TP", tp_px
    if hit_sl:
        return "SL", (sl_px * (1 - TW_SLIP) if is_long else sl_px * (1 + TW_SLIP))
    return None, None


def _random_entry_decision(rng_val: float, open_tracks, max_random: int = MAX_RANDOM,
                           p: float = RANDOM_ENTRY_P) -> bool:
    """True bila kontrol RANDOM boleh entry (murni → bisa diuji tanpa jaringan)."""
    if not RANDOM_CONTROL_ENABLED:
        return False
    if sum(1 for t in open_tracks if t == TRACK_RANDOM) >= max_random:
        return False
    return rng_val < p


def run_cycle(do_entries: bool = True):
    _btc_quota["signal"] = 0   # reset kuota riset per siklus (2026-11-13)
    _btc_quota["random"] = 0
    now = datetime.now(timezone.utc)
    st = load_state()
    prices = fetch_prices()

    # ── exits (geometri REAL-wide: SL dari t=0, TP, time-stop 30h) ──
    for pos in st["positions"]:
        pair = pos["pair"]; direction = pos["direction"]
        entry = pos["entry_price"]; cur = prices.get(pair, entry)
        gross = (cur - entry) / entry
        if direction == "SHORT":
            gross = -gross                       # normalisasi: positif = profit
        hold_h = (now - datetime.fromisoformat(pos["entry_time"])).total_seconds() / 3600
        reason = None
        fill_px = cur                     # default: harga poll (dan exit market TIME_*)
        if TW_LEVEL_FILL:
            _lr, _lpx = level_fill_price(entry, direction, cur)
            if _lr:
                reason, fill_px = _lr, _lpx
        if not reason and gross >= TP_PCT:
            reason = "TP"
        elif not reason and gross <= -SL_PCT:
            reason = "SL"
        elif not reason and hold_h >= TIME_STOP_H:
            reason = f"TIME_{TIME_STOP_H}h"
        if reason:
            # BIAYA BENAR (audit 30-Sep-2026): taker 2 sisi + spread 2 sisi + funding.
            _gross_fill = (fill_px - entry) / entry
            if direction == "SHORT":
                _gross_fill = -_gross_fill   # normalisasi ulang dari harga FILL
            net = _gross_fill - float(_rt_cost(venue="perps", order_type="taker",
                                               pair=pair, include_funding=True))
            pnl = net * NOTIONAL * LEVERAGE
            wallet_roi = pnl / TOTAL_WALLET_CAPITAL
            below_target = wallet_roi < TARGET_MIN_PCT
            pos.update({"exit_price": fill_px, "exit_time": now.isoformat(), "exit_reason": reason,
                        "status": "CLOSED", "pnl_pct": net, "pnl_usd": pnl, "wallet_roi": wallet_roi,
                        "fill_model": ("level" if (TW_LEVEL_FILL and fill_px != cur) else "poll"),
                        "hold_hours": hold_h, "below_target": below_target})
            st["closed_trades"].append(pos)
            st["total_pnl"] += pnl; st["n_trades"] += 1
            st["by_pair"][pair]["pnl"] += pnl; st["by_pair"][pair]["n"] += 1
            if below_target:
                st["n_below_target"] += 1; st["by_pair"][pair]["below"] += 1
            if pnl > 0:
                st["n_wins"] += 1; st["by_pair"][pair]["wins"] += 1
            with open(LOG_FILE, "a") as f:
                f.write(json.dumps(pos, default=str) + "\n")
            print(f"  CLOSED {pair} {direction}: {reason} ${pnl:+.2f} ({net:+.3%}) {hold_h:.1f}h")
    st["positions"] = [p for p in st["positions"] if p.get("status") != "CLOSED"]

    # ── entries (skipped on fast exit-only cycles) ──
    _sig_n = sum(1 for q in st["positions"] if q.get("track", TRACK_SIGNAL) == TRACK_SIGNAL)
    _rnd_n = sum(1 for q in st["positions"] if q.get("track", TRACK_SIGNAL) == TRACK_RANDOM)

    def _funnel_ctx() -> dict:
        """Konteks funnel dihitung saat flush (bukan saat masuk blok entry)."""
        _s = sum(1 for q in st["positions"] if q.get("track", TRACK_SIGNAL) == TRACK_SIGNAL)
        _r = sum(1 for q in st["positions"] if q.get("track", TRACK_SIGNAL) == TRACK_RANDOM)
        return {
            "pairs": len(PAIRS), "prices": len(prices),
            "open_signal": _s, "open_random": _r,
            "max_signal": MAX_TOTAL_POSITIONS, "max_random": MAX_RANDOM,
            "block_long_signal": bool(BLOCK_LONG_SIGNAL), "invert_signal": bool(INVERT_SIGNAL),
            "pre24_min": PRE24_MIN, "tp_pct": TP_PCT, "sl_pct": SL_PCT,
        }

    if do_entries and (_sig_n < MAX_TOTAL_POSITIONS or _rnd_n < MAX_RANDOM):
        global _EMPTY_STREAK, _LAST_FETCH_ERR, _RETRY_BUDGET
        _attempted = _ok = 0
        _RETRY_BUDGET = RETRY_BUDGET_PER_CYCLE   # anggaran retry di-reset per siklus
        for pair in PAIRS:
            # Re-check total INSIDE the loop: with a 19-pair universe many pairs can
            # qualify in one cycle and overshoot the cap (correlated pseudo-samples).
            # Cap dihitung PER-TRACK: RANDOM tidak boleh memakan slot SIGNAL.
            _sig_n = sum(1 for q in st["positions"]
                         if q.get("track", TRACK_SIGNAL) == TRACK_SIGNAL)
            _rnd_n = sum(1 for q in st["positions"]
                         if q.get("track", TRACK_SIGNAL) == TRACK_RANDOM)
            _f("pairs_scanned")
            if _sig_n >= MAX_TOTAL_POSITIONS and _rnd_n >= MAX_RANDOM:
                _f("skip_both_caps_full")
                break   # kedua arm penuh → tidak ada yang bisa entry
            if pair_gate_blocks("TWO-WAY", pair):
                _f("skip_pair_gate")
                continue   # per-pair prune: proven structural drag → skip
            if sum(1 for p in st["positions"] if p.get("pair") == pair) >= MAX_POSITIONS:
                _f("skip_pair_cap")
                continue
            last_entry = st["last_entry"].get(pair)
            if last_entry:
                if (now - datetime.fromisoformat(last_entry)).total_seconds() / 3600 < COOLDOWN_H:
                    _f("skip_cooldown")
                    continue
            try:
                _attempted += 1
                d = fetch_ohlcv(BINANCE_SYMBOLS[pair])
                sig = check_signal(d, pair)
                _ok += 1

                # ── KONTROL RANDOM: entry TANPA sinyal alpha (MESIN EXIT SAMA) ──
                # Data/harga SAMA dengan kandidat SIGNAL; geometri exit identik
                # (TP/SL sama) → yang diuji ENTRY TIMING. Arah regime-matched agar
                # adil (bukan selalu LONG). Cooldown per-pair di atas sudah berlaku.
                if pair in prices and prices[pair] > 0:
                    _tracks = [q.get("track", TRACK_SIGNAL) for q in st["positions"]]
                    if _random_entry_decision(_RNG.random(), _tracks):
                        if not btc_gate_pass("random"):
                            _f("skip_random_btc_gate")
                            continue   # A/B 3 regime gate (arm RANDOM ikut di-gate)
                        _btc_r = btc_daily_regime()
                        _dir = "SHORT" if _btc_r == "BEAR" else "LONG"
                        if not direction_gate_blocks("TWO-WAY", _dir):
                            _cur = prices[pair]
                            _tp = _cur * (1 + TP_PCT) if _dir == "LONG" else _cur * (1 - TP_PCT)
                            _sl = _cur * (1 - SL_PCT) if _dir == "LONG" else _cur * (1 + SL_PCT)
                            st["positions"].append({
                                "id": f"{pair}_{_dir}_{now.strftime('%Y%m%d_%H%M%S')}_R",
                                "pair": pair, "direction": _dir, "entry_price": _cur,
                                "track": TRACK_RANDOM,
                                "entry_time": now.isoformat(), "tp_price": _tp, "sl_price": _sl,
                                "time_stop_time": (now + timedelta(hours=TIME_STOP_H)).isoformat(),
                                "status": "OPEN", "regime": "RANDOM_CONTROL",
                                "btc_regime": _btc_r, "conviction": 0, "atr_pct": _atr_pct(d),
                                "entry_reasons": ["random"],
                            })
                            st["last_entry"][pair] = now.isoformat()
                            _f("entry_random")
                            print(f"  NEW {pair} {_dir}: RANDOM control ${_cur:.2f}")
                        else:
                            _f("skip_random_dir_gate")

                _block_long_sig = bool(BLOCK_LONG_SIGNAL and sig.get("active")
                                       and invert_direction(sig.get("direction", "LONG")) == "LONG")
                if _block_long_sig:
                    _f("skip_block_long_signal")
                    _block_log("TWO-WAY", pair)
                if not _block_long_sig and sig.get("active") and pair in prices and prices[pair] > 0 \
                        and _sig_n < MAX_TOTAL_POSITIONS \
                        and sum(1 for p in st["positions"] if p.get("pair") == pair) < MAX_POSITIONS:
                    direction = sig["direction"]
                    # FIX 2026-11-14 (terukur, bukan opini): inversi WAJIB diterapkan
                    # SEBELUM gate arah. `direction_gate_blocks` mengukur edge dari arah
                    # yang BENAR-BENAR ditradingkan; kalau urutannya setelah gate, gate
                    # menilai arah dasar yang justru dibalik. Bukti arm 9a/9b/9c
                    # (TW_SHORT_LEG=1 + TW_INVERT_SIGNAL=1, regime BEAR): base SHORT →
                    # dibalik jadi LONG → n=39 SIGNAL LONG −3,585%/tr (CI −4,568..−2,560,
                    # WR 25,6%) vs SIGNAL SHORT n=14 +1,309%/tr (WR 100%). Gate arah tidak
                    # pernah melihat LONG itu karena diperiksa di arah dasar.
                    if INVERT_SIGNAL:
                        direction = invert_direction(direction)
                    if CHOP_GATE_ENABLED and direction == "LONG":
                        _btc_reg = btc_daily_regime()
                        if _btc_reg == "CHOP":
                            _f("skip_chop_gate")
                            continue
                    if direction_gate_blocks("TWO-WAY", direction):
                        _f("skip_dir_gate")
                        continue   # edge-gate: arah ini anti-predictive → skip
                    if not btc_gate_pass("signal"):
                        _f("skip_btc_gate")
                        continue   # A/B 3: BTC mom<0 → entry baru diblok (kontrol = lane lain)
                    cur = prices[pair]
                    _pre24 = None
                    if PRE24_MIN is not None:
                        _pre24 = pre24_pct(pair)
                        if _pre24 is None or _pre24 < PRE24_MIN:
                            _f("skip_pre24")
                            continue   # A/B 9c: bukan setup "sudah naik" -> lewati
                    tp = cur * (1 + TP_PCT) if direction == "LONG" else cur * (1 - TP_PCT)
                    sl = cur * (1 - SL_PCT) if direction == "LONG" else cur * (1 + SL_PCT)
                    pos = {"id": f"{pair}_{direction}_{now.strftime('%Y%m%d_%H%M%S')}",
                           "track": TRACK_SIGNAL,
                           "pair": pair, "direction": direction, "entry_price": cur,
                           "entry_time": now.isoformat(), "tp_price": tp, "sl_price": sl,
                           "time_stop_time": (now + timedelta(hours=TIME_STOP_H)).isoformat(),
                           "status": "OPEN", "regime": sig.get("regime", ""),
                           "btc_regime": btc_daily_regime(),
                           "conviction": sig.get("conviction", 0), "atr_pct": _atr_pct(d),
                           "pre24_pct": _pre24,
                           "entry_reasons": sig.get("reasons", [])}
                    st["positions"].append(pos)
                    st["last_entry"][pair] = now.isoformat()
                    _f("entry_signal")
                    print(f"  NEW {pair} {direction}: ${cur:.2f} conv {sig['conviction']:.0%} "
                          f"[{'+'.join(sig.get('reasons', []))}]")
                elif not _block_long_sig:
                    # Diagnostik murni: alasan kandidat SIGNAL tidak diteruskan syarat
                    # majemuk di atas. Tidak ada keputusan trading yang berubah.
                    if not sig.get("active"):
                        _f("skip_signal_inactive")
                        # diagnosis: alasan inaktif (insufficient_data/no_trend/15m_*/no_signal)
                        _f(f"reason_{sig.get('reason') or 'unknown'}")
                    elif pair not in prices or not (prices[pair] > 0):
                        _f("skip_no_price")
                    elif _sig_n >= MAX_TOTAL_POSITIONS:
                        _f("skip_signal_cap")
                    else:
                        _f("skip_pair_pos_cap")
            except Exception as e:
                _f("fetch_error")
                _LAST_FETCH_ERR = f"{pair}: {type(e).__name__}: {e}"[:300]
                print(f"  Signal error {pair}: {e}")

        _EMPTY_STREAK = _feed_streak_next(_EMPTY_STREAK, _attempted, _ok)
        if _attempted >= 20 and _ok == 0:
            # Blackout total satu siklus (49 kejadian terukur, semuanya 23/23 pair).
            # Tanpa baris ringkas ini, blackout hanya terlihat sebagai 23 baris
            # "Signal error" yang mudah tenggelam di log.
            print(f"  [WARN] feed blackout: {_attempted}/{_attempted} pair gagal "
                  f"— sebab terakhir: {_LAST_FETCH_ERR or '(tidak terekam)'}")
        funnel_flush(now.isoformat(), _funnel_ctx())
    else:
        # Dua sebab BERBEDA masuk ke cabang ini:
        #   (a) do_entries=False -> sub-siklus khusus exit-poll (4 dari 5 siklus saat
        #       interval 300s / exit-poll 60s). Normal, BUKAN saturasi.
        #   (b) do_entries=True tapi cap penuh (6 SIGNAL + 2 RANDOM) -> saturasi asli.
        # Sebelum perbaikan ini keduanya dicatat sebagai "cycle_caps_full", sehingga
        # telemetri melaporkan saturasi palsu dengan rasio ~4:1 dan menutupi saturasi
        # sungguhan. Funnel tetap di-flush di kedua kasus agar bukti tidak hilang.
        _f("cycle_caps_full" if do_entries else "cycle_exit_only")
        funnel_flush(now.isoformat(), _funnel_ctx())

    save_state(st)
    wr = st["n_wins"] / max(st["n_trades"], 1)
    thr = 1 - st["n_below_target"] / max(st["n_trades"], 1)
    print(f"  State: {st['n_trades']}t WR:{wr:.1%} PnL:${st['total_pnl']:+.0f} "
          f"Open:{len(st['positions'])} | ≥{TARGET_MIN_PCT:.1%}:{thr:.0%}")
    with open(MON_JSON, "w") as f:
        json.dump({"timestamp": now.isoformat(), "prices": prices,
                   "n_trades": st["n_trades"], "n_wins": st["n_wins"], "win_rate": wr,
                   "total_pnl": st["total_pnl"], "open_positions": len(st["positions"]),
                   "n_below_target": st["n_below_target"], "target_hit_rate": thr,
                   "by_pair": st["by_pair"]}, f, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.status:
        st = load_state()
        wr = st["n_wins"] / max(st["n_trades"], 1)
        thr = 1 - st["n_below_target"] / max(st["n_trades"], 1)
        print(f"TWO-WAY ({', '.join(PAIRS)}) — n={st['n_trades']} WR:{wr:.1%} "
              f"PnL=${st['total_pnl']:+.2f} open={len(st['positions'])} ≥{TARGET_MIN_PCT:.1%}:{thr:.0%}")
        return
    if a.loop:
        _EXIT_POLL = 60
        _n_entry = max(a.interval // _EXIT_POLL, 1)
        _c = 0
        print(f"🔄 TWO-WAY LEARNING — LONG+SHORT | TP+{TP_PCT*100:g}%/SL-{SL_PCT*100:g}% @{LEVERAGE}x | "
              f"time-stop {TIME_STOP_H}h | exit-poll {_EXIT_POLL}s | relaxed={_RELAXED}")
        while True:
            try:
                _do_entries = (_c % _n_entry == 0)
                run_cycle(do_entries=_do_entries)
                _c += 1
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"  ❌ {e}")
            if _EMPTY_STREAK >= EMPTY_STREAK_LIMIT:
                print(f"[FATAL] feed buta {_EMPTY_STREAK} siklus entry berturut "
                      f"(semua pair gagal fetch) — keluar, systemd restart | "
                      f"error terakhir: {_LAST_FETCH_ERR or '(tidak terekam)'}",
                      file=sys.stderr)
                sys.exit(2)
            time.sleep(_EXIT_POLL)
    else:
        run_cycle()


if __name__ == "__main__":
    main()
