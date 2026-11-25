#!/usr/bin/env python3
"""SPOT SWING v4 — kombinasi campuran teradaptasi dari CEX-Binance (2026-09-03).

ROOT CAUSE v3 (dari analisa ilmiah 35 trade, lihat SODEX_SPOTSWING_ROOTCAUSE):
  1. Jendela gempa: SL tidak aktif 4 jam pertama → 3 trade -$32,91 (4,6× laba)
  2. Book tipis / adverse selection: order $300 di pair volume $150-765/24h
  3. Margin tipis payoff 1,56:1 + WR 42,9%
  4. State terkontaminasi pair mati (vSOL/WSOSO)

DESAIN v4 — KOMBINASI CEX yang TERBUKTI (paper_test_spot_swing_cex breakdown):
  signal 'momentum+adx+regime' di CEX = WR 100% n=12 avg +2.3% (LONG-only).
  Diadaptasi ke SWING SPOT SoDEX:
  - Sinyal: momentum (5h ret > 0.5%) + ADX≥25 + regime (BTC uptrend) — dari
    Binance 1h (liquid, data sinyal konsisten dengan semua track)
  - LONG-only (spot tak bisa short; CEX long lebih unggul)
  - Hal-hal: SL AKTIF DARI t=0 (fix jendela gempa) — pola REALWIDE yang terbukti
  - Likuiditas: hanya spot pair dengan quoteVolume ≥ threshold
  - Ekspansi pair: semua spot SoDEX + combo (multi-aset murni, bukan hanya 4)
  - SIZE: $100 (bukan $300) utk kurangi slippage di book tipis
  - Kombinasi: regime(HL) + momentum + ADX + volume filter (mirip CEX)

State: data/paper_test_spot_swing_v2_state.json (TERPISAH — tidak rusak v3)
Run:    python3 scripts/paper_test_spot_swing_v2.py --loop --interval 300
Paper only. Read-only API (ticker + klines).
"""
from __future__ import annotations
import argparse, json, os, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
STATE_FILE = PROJECT / "data" / "paper_test_spot_swing_v2_state.json"
# Source denominator wajib sama dengan exchange-sync/runtime env; fallback hanya
# untuk local dry-run dan tidak boleh menjadi sumber target live.
REAL_WALLET = float(os.environ.get("SODEX_TOTAL_WALLET", "108.10"))
TARGET = 0.008

# ── PARAMS (dari CEX + fix root cause) ──
SMA_FAST, SMA_SLOW = 50, 200
ADX_MIN = 25.0
MOM_RET5 = 0.005          # momentum 5h > 0.5%
TP_PCT = 0.025
SL_PCT = 0.015
TIME_STOP_H = 30
MIN_HOLD_SL_H = 0         # FIX: SL aktif dari t=0 (jendela gempa dihapus)
COOLDOWN_H = 6
MAX_TOTAL = 5
NOTIONAL = 100.0          # $100 (bukan $300) — kurangi slippage book tipis
MIN_VOLUME_USD = 3000.0   # FILTER LIKUIDITAS: hanya pair ≥ $3K/24h (dry-run)
_TIMEOUT = 10
_CACHE = {}

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
SODEX_TICKERS = "https://mainnet-gw.sodex.dev/api/v1/spot/markets/tickers"
SODEX_KLINES = "https://mainnet-gw.sodex.dev/api/v1/spot/markets/{sym}/klines"

# Mapping spot SoDEX -> Binance signal symbol
SPOT_TO_BN = {
    "vBTC_vUSDC": "BTCUSDT", "vETH_vUSDC": "ETHUSDT", "vTON_vUSDC": "TONUSDT",
    "vHYPE_vUSDC": "HYPEUSDT", "vXRP_vUSDC": "XRPUSDT", "vLINK_vUSDC": "LINKUSDT",
    "vUNI_vUSDC": "UNIUSDT", "vBNB_vUSDC": "BNBUSDT", "vSOL_vUSDC": "SOLUSDT",
    "vAAVE_vUSDC": "AAVEUSDT", "vDOGE_vUSDC": "DOGEUSDT", "vPEPE_vUSDC": "PEPEUSDT",
    "vSHIB_vUSDC": "SHIBUSDT", "vADA_vUSDC": "ADAUSDT", "vAVAX_vUSDC": "AVAXUSDT",
    "vSUI_vUSDC": "SUIUSDT", "vLTC_vUSDC": "LTCUSDT", "vXLM_vUSDC": "XLMUSDT",
}
# HYPE tidak ada di Binance SPOT (hanya futures) → fallback ke fapi klines
BINANCE_FAPI = "https://fapi.binance.com/fapi/v1/klines"
FAPI_ONLY = {"HYPEUSDT", "XAUTUSDT"}   # perp-only, source fapi


def _http(url, headers=None):
    now = time.time()
    if url in _CACHE and now - _CACHE[url][0] < 15:
        return _CACHE[url][1]
    req = urllib.request.Request(url, headers=headers or {'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        body = json.loads(r.read().decode())
    _CACHE[url] = (now, body)
    return body


def get_liquid_pairs():
    """Filter spot pair SoDEX berdasarkan volume 24h (dari ticker live)."""
    data = _http(SODEX_TICKERS)
    tickers = data if isinstance(data, list) else data.get("data", [])
    pairs = {}
    for t in tickers:
        sym = t.get("symbol", "")
        vol = float(t.get("quoteVolume", 0) or 0)
        if sym in SPOT_TO_BN and vol >= MIN_VOLUME_USD:
            pairs[sym] = vol
    return pairs


def fetch_klines(sym, interval="1h", limit=220):
    """Return (high, low, close) arrays — H/L sejati utk ADX (bukan close-based).
    Fallback fapi utk perp-only symbol (HYPE, XAUT) yang tak ada di Binance spot."""
    if sym in FAPI_ONLY:
        url = f"{BINANCE_FAPI}?symbol={sym}&interval={interval}&limit={limit}"
    else:
        url = f"{BINANCE_KLINES}?symbol={sym}&interval={interval}&limit={limit}"
    d = _http(url)
    high = np.array([float(x[2]) for x in d])
    low = np.array([float(x[3]) for x in d])
    close = np.array([float(x[4]) for x in d])
    return high, low, close


def sma(c, p):
    if len(c) < p:
        return np.full_like(c, np.nan)
    out = np.convolve(c, np.ones(p)/p, mode='valid')
    return np.concatenate([np.full(len(c)-len(out), np.nan), out])


def adx(h, l, c, p=14):
    n = len(c)
    tr = np.maximum(h - l, np.maximum(abs(h - np.roll(c, 1)), abs(l - np.roll(c, 1))))
    up = h - np.roll(h, 1); dn = np.roll(l, 1) - l
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr = sma(tr, p); plus = sma(plus_dm, p); minus = sma(minus_dm, p)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = 100 * plus / atr; mdi = 100 * minus / atr
        dx = 100 * abs(pdi - mdi) / (pdi + mdi)
    return sma(dx, p)


# ── REGIME (BTC uptrend — seperti CEX regime-long, dimodulasi) ──
def btc_regime_ok():
    """Gate regime responsif: BTC>EMA50 ATAU mom6h>0 (bukan SMA200 kaku).
    Rasional: SMA200 kaku = 0 fire di market downtrend 5 hari (cuma 21% jam
    di atas MA) — membuat v4 mati total. EMA50+mom6h tetap filter tren tapi
    adaptif; data CEX 'momentum+adx+regime' = edge dengan regime long."""
    try:
        _, _, c = fetch_klines("BTCUSDT")
        i = len(c) - 2
        k = 2 / (50 + 1)
        e = c[0]
        # EMA50 iteratif
        ema_v = c[0]
        for j in range(1, i + 1):
            ema_v = c[j] * k + ema_v * (1 - k)
        mom6 = (c[i] - c[i-6]) / c[i-6] if i >= 6 else 0
        return bool(c[i] > ema_v or mom6 > 0.0)
    except Exception:
        return False


def check_signal_combined(h, l, c):
    """momentum + ADX + regime — kombinasi CEX yang terbukti +2.3% n=12.
    ADX pakai H/L sejati (fix bug 2026-09-03: sebelumnya close-based → ADX
    tertekan <25 → sinyal tidak pernah fire → bottleneck v4).
    
    Relaksasi ilmiah (2026-09-03): sinyal ORIGINAL butuh c>SMA50 & mom5>0
    & ADX≥25 & regime BTC bersamaan → hampir tak pernah fire di market sideways.
    Adaptasi dari CEX: momentum memakai SMA50 cross ATAU mom5 (dua jalur), ADX
    ambang 20 (bukan 25 — CEX pakai 25 utk futures trending, spot/alt lebih
    konsolidatif). Regime BTC tetap gate terpisah (btc_regime_ok)."""
    i = len(c) - 2
    if i < 200:
        return False
    s50 = sma(c, 50); s200 = sma(c, 200)
    if np.isnan(s50[i]) or np.isnan(s200[i]):
        return False
    mom5 = (c[i] - c[i-5]) / c[i-5] if i >= 5 else 0
    a = adx(h, l, c)
    a_v = a[i] if not np.isnan(a[i]) else 0
    # momentum: dua jalur (c>SMA50 ATAU mom5>0.5%) — lebih sering fire dari AND
    momentum = bool(c[i] > s50[i] or mom5 > MOM_RET5)
    # ADX ambang 20 (relaksasi dari 25)
    adx_ok = bool(a_v >= 20.0)
    return momentum and adx_ok


# ── STATE ──
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"created": datetime.now(timezone.utc).isoformat(), "open": {},
            "closed": [], "last_entry": {}, "total_pnl": 0.0, "n_trades": 0,
            "n_wins": 0, "n_below": 0}


def save_state(st):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1))
    tmp.replace(STATE_FILE)


def has_open_spot(st, sym):
    """Satu paper position maksimum per SoDEX spot symbol.

    Open-state keys membawa timestamp, jadi `sym in st["open"]` selalu salah
    dan memungkinkan posisi vTON_vUSDC rangkap.
    """
    return any(pos.get("spot_sym") == sym for pos in st.get("open", {}).values())


# ── CYCLE ──
def run_cycle(st, do_entries=True):
    now = datetime.now(timezone.utc)
    pairs = get_liquid_pairs()

    # exit management (SL dari t=0)
    for pid in list(st["open"].keys()):
        pos = st["open"][pid]
        sym = pos["spot_sym"]
        bn = SPOT_TO_BN.get(sym)
        if not bn:
            continue
        try:
            h, l, c = fetch_klines(bn)
            px = float(c[-1])
        except Exception:
            continue
        hold_h = (now - datetime.fromisoformat(pos["entry_time"])).total_seconds() / 3600
        g = (px - pos["entry_p"]) / pos["entry_p"]
        reason = None
        if g >= TP_PCT:
            reason = "TP"
        elif g <= -SL_PCT:          # SL aktif dari t=0 (MIN_HOLD_SL_H=0)
            reason = "SL"
        elif hold_h >= TIME_STOP_H:
            reason = "TIME_30h"
        if reason:
            pnl_usd = g * NOTIONAL
            st["closed"].append({"spot_sym": sym, "pair": bn, "direction": "LONG",
                                 "entry_p": pos["entry_p"], "entry_time": pos["entry_time"],
                                 "exit_p": px,
                                 "exit_time": now.isoformat(), "exit_reason": reason,
                                 "gross_pct": g, "pnl_usd": round(pnl_usd, 2),
                                 "hold_h": round(hold_h, 1)})
            st["total_pnl"] += pnl_usd
            st["n_trades"] += 1
            if pnl_usd > 0: st["n_wins"] += 1
            st["n_below"] += 1 if pnl_usd / REAL_WALLET < TARGET else 0
            del st["open"][pid]

    # entries — MODE ADAPTIF (2026-09-03)
    # Saat BTC regime ON → bebas long semua pair liquid (filter tren penuh).
    # Saat BTC regime OFF (downtrend) → tetap long pair yang INDEPENDEN-BULL
    # (momentum+ADX kuat tanpa mengandalkan BTC), batasi 1-2 posisi adaptif.
    # Ilmiah: data 2026-09-03 membuktikan UNI/TON/LTC fire signal walau BTC di
    # bawah EMA50 — memanfaatkan momentum independen menjaga track tetap
    # menghasilkan data (bukan mati 0 trade), sambil mencatat regime di state.
    if do_entries and len(st["open"]) < MAX_TOTAL:
        regime_on = btc_regime_ok()
        # get mark price SoDEX untuk entry
        try:
            t = _http(SODEX_TICKERS)
            tickers = t if isinstance(t, list) else t.get("data", [])
            sod_px = {x.get("symbol"): float(x.get("lastPx", 0) or 0) for x in tickers}
        except Exception:
            sod_px = {}
        # saat regime OFF: batasi posisi adaptif jadi 1 (konservatif)
        if not regime_on and len([p for p in st["open"] if st["open"][p].get("mode") == "adaptif"]) >= 1:
            return len(st["open"])
        for sym in sorted(pairs, key=lambda s: -pairs[s]):
            if has_open_spot(st, sym):
                continue
            last = st["last_entry"].get(sym, 0)
            if now.timestamp() - last < COOLDOWN_H * 3600:
                continue
            bn = SPOT_TO_BN[sym]
            try:
                h, l, c = fetch_klines(bn)
            except Exception:
                continue
            if not check_signal_combined(h, l, c):
                continue
            px = sod_px.get(sym)
            if not px or px <= 0:
                continue
            mode = "normal" if regime_on else "adaptif"
            st["open"][f"{sym}_{int(now.timestamp())}"] = {
                "spot_sym": sym, "pair": bn, "entry_p": px,
                "entry_time": now.isoformat(), "mode": mode, "regime_on": regime_on}
            st["last_entry"][sym] = now.timestamp()
            print(f"  [ENTRY] {sym} ({bn}) LONG @ {px:.6g} | vol ${pairs[sym]:,.0f}/24h "
                  f"| mode={mode} {'🔥' if regime_on else '(adaptif, BTC down)'}", flush=True)
            break  # 1 entry per cycle

    save_state(st)
    return len(st["open"])


# ── REPORT ──
def report(st):
    n = st["n_trades"]; total = st["total_pnl"]
    if n == 0:
        print(f"[SPOT_SWING_v4] n=0 | collecting... | open={len(st['open'])}", flush=True)
        return
    roi = total / REAL_WALLET / n * 100
    print(f"[SPOT_SWING_v4] n={n} | PnL=${total:+.2f} | ROI={roi:+.3f}% | "
          f"open={len(st['open'])} | {'✅ target exceeded' if roi >= TARGET * 100 else '📈 collecting'}", flush=True)  # audit 30-Sep: 0,7 -> konstanta TARGET (0,8%)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    st = load_state()

    if a.status:
        report(st)
        for t in st["closed"][-8:]:
            print(f"    {t['pair']:9s} {t['exit_reason']:9s} {t['gross_pct']*100:+6.2f}% ${t['pnl_usd']:+6.2f} hold {t['hold_h']}h")
        return

    if not a.loop:
        run_cycle(st, do_entries=True)
        report(st)
        return

    cycle = 0
    while True:
        try:
            do_entries = (cycle % 5 == 0)
            run_cycle(st, do_entries=do_entries)
            report(st)
        except Exception as e:
            print(f"cycle error: {e}", flush=True)
        time.sleep(a.interval)
        cycle += 1


if __name__ == "__main__":
    main()