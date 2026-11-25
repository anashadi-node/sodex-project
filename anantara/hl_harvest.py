#!/usr/bin/env python3
"""
anantara/hl_harvest.py — Hyperliquid cross-venue funding-rate arbitrage

STRATEGY: delta-neutral cross-venue spread capture.
  Short perp on the HIGHER-rate exchange (collect funding).
  Long perp on the LOWER-rate exchange (pay less / collect if negative).
  Net yield ≈ |rate_Binance - rate_HL| - fees.  Delta = 0 (both legs cancel).

TYPICAL SPREADS (2026-05):
  ARB  ~20%/yr (Binance >> HL)
  LTC  ~10%/yr
  ETH  ~ 8%/yr

MODES:
  plan    — show live spreads + allocation table (no key required)
  monitor — show open HL positions + accrued funding (needs HL_HARVEST_ADDRESS)
  run     — open cross-venue legs (needs HL_HARVEST_API_SECRET + FUNDING_LIVE=1)
  close   — close all open HL legs (needs HL_HARVEST_API_SECRET + FUNDING_LIVE=1)

ENV VARS (in .env):
  HL_HARVEST_ADDRESS  public address of your HL account (read-only monitoring)
  HL_HARVEST_API_SECRET  private key of the AGENT/API wallet, NOT main wallet.
                  Create at app.hyperliquid.xyz → API → Add Agent Wallet.
                  Never use your main wallet private key here.
  FUNDING_LIVE    set to "1" to enable real order execution (omit = dry-run)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore  — network calls require httpx; tests mock them

# ── Config ────────────────────────────────────────────────────────────────────
HL_API       = "https://api.hyperliquid.xyz"
BINANCE_FAPI = "https://fapi.binance.com/fapi/v1"
_TIMEOUT     = 10
_TIMEOUT_BN  = 6   # Binance API — faster fail, faster retry

UNIVERSE = ["BTC", "ETH", "SOL", "ARB", "LTC", "BNB", "DOGE", "LINK",
            "AVAX", "MATIC", "OP", "SUI", "APT", "INJ", "TIA",
            # 2026-09-06 user-approved additions — all verified available on
            # >=3 of 5 funding venues before inclusion (HYPE/ZEC/BCH/UNI/AAVE/
            # ASTER on 5, PAXG on 4, XAUT on 3). dYdX liquidity-gated
            # separately below; assets failing that gate still scan the 4 CEX.
            "HYPE", "ZEC", "BCH", "UNI", "XAUT", "AAVE", "PAXG", "ASTER",
            # 2026-09-11 (disetujui user) — 23 aset baru, universe 23 -> 46.
            #
            # ALASAN: distribusi spread terbukti FAT-TAILED. Dari 11.769
            # observasi: median 10,9% | p90 26,3% | p99 91,4% | maks 319%.
            # Profit datang dari EKOR, bukan rata-rata — 1% teratas rata-rata
            # 145%. Uji falsifikasi membuktikan sifat ini: tanpa LINK+INJ,
            # RoC jatuh dari +121,6% ke +7,3%.
            #
            # Ketergantungan pada 1-2 pemenang adalah SIFAT strategi ekor,
            # bukan cacat. Obatnya bukan menebak pemenang (mustahil), tapi
            # MEMPERBANYAK KESEMPATAN menangkap ekor. Menggandakan universe
            # menggandakan peluang tanpa menambah modal maupun risiko per
            # posisi — setiap posisi tetap delta-neutral dan tetap tunduk
            # pada gate 25% + consistency 4 jam + syarat break-even.
            #
            # SYARAT SELEKSI (bukan tebakan): tersedia di >=4 dari 5 venue
            # DAN volume Binance >=$50jt/hari. Semua terverifikasi live
            # 2026-09-11; 19 dari 23 hadir di kelima venue.
            "XRP", "NEAR", "ENA", "ADA", "TAO", "WLD", "TRUMP", "DOT",
            "ETHFI", "DASH", "ONDO", "FIL", "PENGU", "TRX", "XLM",
            "MET", "VVV", "WLFI", "LIT", "USELESS", "PUMP", "PONS", "XAG"]

# MATIC migrated to POL on Binance Futures (2025). HL still uses MATIC ticker.
# Map to correct Binance symbol for cross-venue hedge.
BINANCE_SYMBOL_MAP: dict[str, str] = {"MATIC": "POLUSDT"}

# Cross-venue thresholds. Set from the controlled venue study (2026-08-16):
# 15 shared coins, HL x Binance, identical 365-day window, OOS-selected.
# The OOS curve is an inverted U with a 20-30% plateau peaking at 25%:
#   entry 10% -> -0.13%/yr | 15% -> +1.07% | 20% -> +1.66%
#   entry 25% -> +1.78%    | 30% -> +1.77% | 50% -> +1.37% | 100% -> +0.64%
# The mechanism is break-even hold: one round trip costs 0.07%, so a 10% spread
# needs 61h to pay for itself while the average position only lasts 49h — a
# structural loss. At 25% break-even falls to 25h against a 64h hold.
# 25% is chosen over 30% as the plateau centre: same return, 58% more trades.
# Evidence: scripts/hl_venue_study.py, data/hl_venue_study_latest.json.
# These govern the CROSS-VENUE path only. The basis strategy keeps its own,
# separately validated floors (BASIS_MIN_RATE_ANN / BASIS_MIN_EXIT_ANN).
MIN_SPREAD_ANN  = 0.25   # 25%/yr — OOS-optimal cross-venue entry (was 15%)
MIN_SPREAD_EXIT = 0.02   # 2%/yr — hold through decay; exiting at 5% cut trades
                         # short of break-even. Sign-flip risk is carried by the
                         # pnl-guard (-5% alert / -12% force close) instead.
SPREAD_CONSISTENCY = 2   # require ≥2 consecutive snapshots above threshold before entry

ALLOC_CAP       = 0.35   # max fraction of capital to any single asset
MIN_NOTIONAL    = 10.0   # minimum position size per leg ($)
MAX_NEW_NOTIONAL = 20.0  # hard cap per new asset — Binance margin limit after 8+ positions

# ── Telegram Notification (sync, non-blocking) ────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def _telegram_send(msg: str, silent: bool = True) -> None:
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        httpx.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID, "text": msg,
            "parse_mode": "Markdown", "disable_notification": silent,
        }, timeout=httpx.Timeout(connect=5.0, read=5.0, write=5.0, pool=2.0))
    except Exception:
        pass

# ── Kelly sizing (from risk_metrics.py) — adaptive position sizing ──────────
# Estimate from HL Harvest history: ~70% of positions maintain spread >8% for >1 day
# avg_win = spread capture (8-25%/yr), avg_loss = RT cost + slippage (~1-2%)
_KELLY_WIN_RATE  = 0.70   # % of positions that stay profitable
_KELLY_AVG_WIN   = 0.12   # avg annual spread captured (12%/yr)
_KELLY_AVG_LOSS  = 0.02   # avg loss when spread collapses + RT cost

def _kelly_notional(balance: float) -> float:
    """Kelly-based position size given current HL balance.
    Uses fractional_kelly from risk_metrics if available, else fixed cap."""
    try:
        from anantara.risk_metrics import fractional_kelly
        kelly_frac = fractional_kelly(_KELLY_WIN_RATE, _KELLY_AVG_WIN, _KELLY_AVG_LOSS, fraction=0.5)
        if kelly_frac > 0:
            return min(balance * kelly_frac, MAX_NEW_NOTIONAL)
    except ImportError:
        pass
    return min(balance * 0.15, MAX_NEW_NOTIONAL)  # fallback: 15% of balance


def _spread_consistent(sym: str, min_spread: float = MIN_SPREAD_ANN,
                       snapshots: int = SPREAD_CONSISTENCY) -> bool:
    """Fase 2 gate: require N consecutive spread snapshots above threshold.
    Prevents opening on momentary 1-hour spread spikes that vanish immediately."""
    if snapshots <= 1:
        return True  # gate disabled
    state = _load_state()
    history = state.get("spread_history", [])
    if len(history) < snapshots:
        return False  # not enough data
    recent = history[-snapshots:]
    for snap in recent:
        spread = snap.get("spreads", {}).get(sym, 0)
        if spread < min_spread:
            return False
    return True


def _basis_rate_consistent(sym: str, min_rate: float | None = None,
                            snapshots: int | None = None) -> bool:
    """R1 gate: require N consecutive HL-rate snapshots ≥ min_rate before basis entry."""
    if min_rate is None:
        min_rate = BASIS_MIN_RATE_ANN
    if snapshots is None:
        snapshots = BASIS_CONSISTENCY
    if snapshots <= 1:
        return True
    state = _load_state()
    history = state.get("spread_history", [])
    if len(history) < snapshots:
        return False
    recent = history[-snapshots:]
    for snap in recent:
        hl_rate = snap.get("hl_rates", {}).get(sym, 0)
        if abs(hl_rate) < min_rate:
            return False
    return True


def _basis_rate_consistent(sym: str, min_rate: float | None = None,
                           snapshots: int | None = None) -> bool:
    """AUDIT FIX 2026-08-25: live stability gate for R1 basis entry.

    Mirrors the replay engine's STAB gate (>=70% positive funding over 240h)
    using the daemon's spread_history snapshots as the proxy: the last
    `snapshots` recorded HL rates for `sym` must all be >= min_rate in absolute
    value. Returns True when there is not enough history yet (warmup) so a
    freshly restarted daemon is not permanently locked out — the replay's
    WARMUP_H behavior."""
    if min_rate is None:
        min_rate = BASIS_MIN_RATE_ANN
    if snapshots is None:
        snapshots = BASIS_CONSISTENCY
    if snapshots <= 1:
        return True
    state = _load_state()
    history = state.get("spread_history", [])
    recent = history[-snapshots:]
    if len(recent) < snapshots:
        # warmup: not enough snapshots yet — allow (replay warmup semantics)
        return True
    for snap in recent:
        hl_rate = abs(snap.get("hl_rates", {}).get(sym, 0))
        if hl_rate and hl_rate < min_rate:
            return False
        if hl_rate == 0 and sym not in snap.get("hl_rates", {}):
            return False   # symbol missing from snapshot = no evidence
    return True


def find_basis_opportunities(min_rate: float | None = None) -> list[dict]:
    if min_rate is None:
        min_rate = BASIS_MIN_RATE_ANN
    """R1: Scan HL perp funding rates for basis trade candidates.

    Basis trade: long underlying spot (Binance) + short HL perp.
    Delta = 0 (spot long + perp short cancel price moves).
    Net yield ≈ |HL funding rate| − BASIS_ROUND_TRIP per round-trip.

    This harvests the FULL structural premium (8–18%/yr, positive 92% of time)
    instead of the transient cross-venue spread differential (which collapses in ~2h
    and produces net –0.15%/trade after fees).

    Returns: list sorted by |hl_rate| descending, only assets ≥ min_rate.
    """
    hl_rates = fetch_hl_rates()
    if not hl_rates:
        return []

    opps = []
    for sym in UNIVERSE:
        rate = hl_rates.get(sym)
        if rate is None:
            continue
        abs_rate = abs(rate)
        net = abs_rate - BASIS_ROUND_TRIP
        if abs_rate < min_rate:
            continue
        # Positive rate: short perp collects funding, hedge with long spot
        # Negative rate: long perp collects (rare but symmetric — R5 harvest)
        direction = "SHORT_PERP_LONG_SPOT" if rate > 0 else "LONG_PERP_SHORT_SPOT"
        days_to_breakeven = (BASIS_ROUND_TRIP / abs_rate * 365) if abs_rate > 0 else 9999
        opps.append({
            "sym":              sym,
            "hl_rate_ann":      rate,
            "abs_rate_ann":     abs_rate,
            "net_ann":          net,
            "direction":        direction,
            "rt_cost":          BASIS_ROUND_TRIP,
            "breakeven_days":   round(days_to_breakeven, 1),
        })

    opps.sort(key=lambda x: x["abs_rate_ann"], reverse=True)
    return opps


def _calculate_funding_pnl(hl_rates: dict, bn_rates: dict, positions: dict,
                            hours_held: float = 1.0) -> dict[str, float]:
    """Fase 3: Calculate actual funding PnL per pair based on current rates.

    LONG position:  receives funding when rate < 0 (pays when > 0)
    SHORT position: receives funding when rate > 0 (pays when < 0)

    Returns {sym: net_funding_dollars} for the period (hours_held).
    Positive = profit, negative = loss."""
    pnl = {}
    for sym, pos in positions.items():
        side = pos.get("side", "?")
        notl = float(pos.get("notional", 0))
        hl_r = hl_rates.get(sym, 0)   # annual rate
        bn_r = bn_rates.get(sym, 0) if bn_rates else 0

        # Hourly funding rate = annual / (24 * 365)
        hl_hourly = hl_r / (24 * 365)
        bn_hourly = bn_r / (24 * 365)

        # LONG pays funding when rate > 0, receives when rate < 0
        # SHORT receives when rate > 0, pays when rate < 0
        if side == "long":
            hl_funding = -hl_hourly * notl * hours_held
            bn_funding = -bn_hourly * notl * hours_held
        else:  # short
            hl_funding = hl_hourly * notl * hours_held
            bn_funding = bn_hourly * notl * hours_held

        pnl[sym] = round(hl_funding + bn_funding, 6)

    return pnl


# Fees (cross-venue: 2 exchanges × taker entry + taker exit = 4 legs)
# HL fee from app.hyperliquid.xyz/portfolio (Tier 0, unified account):
BINANCE_TAKER   = 0.0004  # 0.04% (Binance futures taker, Tier 0)
HL_TAKER        = 0.00045 # 0.045% (HL taker, Tier 0 confirmed in app)
HL_MAKER        = 0.00015 # 0.015% (HL maker, Tier 0) — post-only ALO orders
ROUND_TRIP_COST = (BINANCE_TAKER + HL_TAKER) * 2  # per $ notional per RT (taker)

# Fee maker venue non-HL (tier dasar, terverifikasi 2026-09-11):
#   Binance USDM 0,020% | Bybit 0,020% | OKX 0,020% | dYdX v4 0,020%
CEX_MAKER = 0.0002
# MAKER_ROUND_TRIP lama = HL_MAKER x 4 = 0,060%, yang mengandaikan KEEMPAT
# kaki berada di Hyperliquid. Posisi cross-venue TIDAK begitu: 2 kaki di HL
# (buka+tutup) dan 2 kaki di venue lawan. Fee sebenarnya 17% lebih mahal.
# Understate fee = melebih-lebihkan RoC; dikoreksi supaya angka jujur.
MAKER_ROUND_TRIP = (HL_MAKER * 2) + (CEX_MAKER * 2)   # 0,070% cross-venue RT

# ── R1 Basis trade constants (long spot + short perp, single venue delta-neutral) ─
# Basis trade harvests FULL HL funding premium (structural 8–18%/yr, 92% positive)
# vs cross-venue differential (transient, collapses in ~2h, net –0.15%/trade).
BN_SPOT_TAKER       = 0.001          # Binance SPOT taker fee 0.10% (api/v3, Tier 0)
BN_SPOT_MAKER       = 0.001          # Binance SPOT maker 0.10% (same tier 0 default)
BASIS_ROUND_TRIP    = (BN_SPOT_TAKER + HL_MAKER) * 2   # 0.23% per full RT (spot open+close + perp open+close)
# 2026-09-06: 12% → 25%. Bukan pengetatan sembarangan — perbaikan aritmetika.
# Di gate 12% sistem masuk pada spread 12-15% lalu membayar fee drag 64.58%/thn
# (hold 31 jam = 281 RT/thn x 0.23%). Secara matematis mustahil untung.
# Uji 168 snapshot: gate 25% masih menyisakan 58.3% waktu dengan peluang,
# turun 18 poin dari gate 12% (76.2%) tapi spread yang ditangkap 2x lipat.
BASIS_MIN_RATE_ANN  = 0.25           # 25%/yr entry floor
BASIS_MIN_EXIT_ANN  = 0.04           # 4%/yr — auto-close when HL funding collapses below this
BASIS_CONSISTENCY   = 3              # N consecutive HL-rate snapshots ≥ 12%/yr before entry
BASIS_ALLOC_CAP     = 0.50           # max 50% of total capital in basis positions per asset
BASIS_MAX_NOTIONAL  = 25.0           # hard cap per basis position ($)
# AUDIT FIX 2026-08-25: concurrent basis position cap (replay: max concurrency
# drives required capital — unbounded entries would over-commit the pool).
BASIS_MAX_POSITIONS = 5             # max simultaneous R1 basis positions
# Re-log a dry-run candidate only when its |rate| moved more than this (3pp).
BASIS_RELOG_PP      = 0.03
BASIS_STATE_KEY_HL  = "basis_hl_legs"
BASIS_STATE_KEY_SPOT = "basis_spot_legs"

# Binance SPOT API base (different from FAPI for futures)
BINANCE_SAPI = "https://api.binance.com/api/v3"

STATE_FILE = Path.home() / "anantara-sakti" / "data" / "hl_harvest.json"
DECISION_LOG = Path.home() / "anantara-sakti" / "data" / "hl_decisions.jsonl"

# ── Monotonic nonce (replay-attack protection) ────────────────────────────────
# pregain_execution.py uses the same pattern — both use a module-level lock so
# two concurrent calls within the same millisecond get distinct nonces.
import threading as _threading
_hl_nonce_lock: _threading.Lock = _threading.Lock()
_hl_last_nonce: int = 0


def _hl_next_nonce() -> int:
    global _hl_last_nonce
    with _hl_nonce_lock:
        ts_ms = int(time.time() * 1000)
        _hl_last_nonce = max(_hl_last_nonce + 1, ts_ms)
        return _hl_last_nonce


# ── Private key format validator ──────────────────────────────────────────────
import re as _re_hl

def _hl_key_valid(k: str) -> bool:
    """Validate HL_API_SECRET format before signing (64-char hex, optional 0x prefix)."""
    if not k:
        return False
    return bool(_re_hl.fullmatch(r"[0-9a-f]{64}", k.strip().lower().replace("0x", "")))


# ── Decision logging (audit trail for autonomous operations) ──────────────────

def _log_decision(action: str, details: str, **kwargs) -> None:
    """Append one JSON line to decision log. Thread-safe via append mode."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "details": details,
        **kwargs,
    }
    try:
        DECISION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(DECISION_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # logging is best-effort, never block operations

# ── Binance FUTURES execution (untuk kaki hedge cross-venue arb) ──────────────

def _binance_futures_order(side: str, symbol: str, notional_usd: float,
                            dry_run: bool = True) -> dict:
    """Execute Binance FUTURES market order. side='BUY'|'SELL'.
    symbol: base tanpa USDT, e.g. 'MATIC', 'ETH'.
    Returns {"ok": bool, "qty": float, "price": float, "reason": str}."""
    api_key = os.getenv("BINANCE_API_KEY", "")
    secret  = os.getenv("BINANCE_API_SECRET", "")
    if not api_key or not secret:
        return {"ok": False, "reason": "BINANCE_API_KEY/SECRET tidak ada di .env"}
    if dry_run:
        return {"ok": True, "qty": 0.0, "price": 0.0, "reason": "DRY-RUN logged only"}

    try:
        import hmac as _hmac, hashlib as _hash, urllib.request as _req, urllib.parse as _uparse
        # Apply symbol mapping (e.g., MATIC → POLUSDT on Binance Futures)
        bn_sym = BINANCE_SYMBOL_MAP.get(symbol, symbol) + "USDT"

        # Fetch current price untuk hitung qty
        price_url = f"{BINANCE_FAPI}/ticker/price?symbol={bn_sym}"
        with _req.urlopen(price_url, timeout=_TIMEOUT_BN) as r:
            price = float(json.load(r)["price"])

        # Get lot size filter untuk rounding
        info_url = f"{BINANCE_FAPI}/exchangeInfo"
        with _req.urlopen(info_url, timeout=_TIMEOUT_BN) as r:
            info = json.load(r)
        step_size = 1.0
        for s in info.get("symbols", []):
            if s["symbol"] == bn_sym:
                for f in s.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        step_size = float(f["stepSize"])
        qty = notional_usd / price
        # Round ke step_size (guard against zero)
        if step_size <= 0:
            step_size = 1.0
        precision = int(round(-math.log10(step_size)))
        qty = round(round(qty / step_size) * step_size, precision)
        if qty <= 0:
            return {"ok": False, "reason": f"Qty terlalu kecil: {qty} ({bn_sym})"}

        # Place market order
        ts = int(time.time() * 1000)
        params = {
            "symbol": bn_sym, "side": side, "type": "MARKET",
            "quantity": qty, "timestamp": ts, "recvWindow": 5000,
        }
        qs = _uparse.urlencode(params)
        sig = _hmac.new(secret.encode(), qs.encode(), _hash.sha256).hexdigest()
        url = f"{BINANCE_FAPI}/order?{qs}&signature={sig}"
        rq = _req.Request(url, method="POST", headers={"X-MBX-APIKEY": api_key})
        with _req.urlopen(rq, timeout=10) as r:
            result = json.load(r)
        # Extract actual fill price — Binance MARKET order response uses 'fills'
        # array for real execution prices; 'avgPrice' is not always present.
        fills = result.get("fills", [])
        if fills:
            filled_price = float(fills[0]["price"])
        else:
            cum_qty = float(result.get("cummulativeQuoteQty", 0) or 0)
            exec_qty = float(result.get("executedQty", qty) or qty)
            filled_price = cum_qty / exec_qty if exec_qty > 0 else price
        return {"ok": True, "qty": qty, "price": filled_price,
                "order_id": result.get("orderId"), "reason": "executed"}
    except Exception as e:
        reason = str(e)[:120]
        # Decode Binance error body for actionable messages
        try:
            body = json.loads(e.read().decode())
            bn_msg = body.get("msg", "")
            if "insufficient" in bn_msg.lower():
                reason = f"Binance margin habis — deposit USDT atau kurangi posisi"
            else:
                reason = f"{bn_msg} (code={body.get('code','?')})"
        except Exception:
            pass
        return {"ok": False, "reason": reason}


# ── Public API ────────────────────────────────────────────────────────────────

def _hl_post(body: dict) -> dict | list | None:
    try:
        r = httpx.post(f"{HL_API}/info", json=body,
                        timeout=httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0))
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[hl_harvest] HL API error: {e}", file=sys.stderr)
        return None


def fetch_hl_meta() -> tuple[list, list] | None:
    """Return (universe_list, asset_ctxs_list). Not cached — see _asset_index."""
    data = _hl_post({"type": "metaAndAssetCtxs"})
    if not data or len(data) < 2:
        return None
    return data[0]["universe"], data[1]


# ── Rate cache (short-lived, avoids duplicate API calls in auto+summary chains) ─

_rate_cache: dict[str, tuple[float, dict]] = {}  # key → (timestamp, data)
_RATE_CACHE_TTL: float = 5.0  # 5 seconds — fresh enough for same command chain


def _clear_rate_cache() -> None:
    """Clear rate cache. Call in test setUp() to prevent cross-test contamination."""
    _rate_cache.clear()


def fetch_hl_rates() -> dict:
    """Current HL funding rates as {SYMBOL: annual_rate_decimal}.
    HL rates are per 1 hour; annualize × 24 × 365. Cached 5s."""
    now = time.time()
    cached = _rate_cache.get("hl")
    if cached and (now - cached[0]) < _RATE_CACHE_TTL:
        return cached[1]

    result = fetch_hl_meta()
    if not result:
        return {}
    universe, ctxs = result
    out = {}
    for asset, ctx in zip(universe, ctxs):
        name = asset["name"]
        if name in UNIVERSE:
            rate_1h = float(ctx.get("funding", 0) or 0)
            out[name] = rate_1h * 24 * 365  # annualize
    _rate_cache["hl"] = (now, out)
    return out


def fetch_binance_rates() -> dict:
    """Current Binance perpetual funding rates as {SYMBOL: annual_rate_decimal}.
    Binance rates are per 8 hours; annualize × 3 × 365. Cached 5s."""
    now = time.time()
    cached = _rate_cache.get("bn")
    if cached and (now - cached[0]) < _RATE_CACHE_TTL:
        return cached[1]

    wanted = {}
    for s in UNIVERSE:
        bn_sym = BINANCE_SYMBOL_MAP.get(s, s) + "USDT"
        wanted[bn_sym] = s

    # v3.3.5: Retry with exponential backoff — ISP intermittent block
    last_error = ""
    for attempt in range(3):
        try:
            r = httpx.get(f"{BINANCE_FAPI}/premiumIndex",
                           timeout=httpx.Timeout(connect=8.0, read=12.0, write=5.0, pool=5.0))
            r.raise_for_status()
            out = {}
            for item in r.json():
                sym = item.get("symbol", "")
                base = wanted.get(sym)
                if base:
                    rate_8h = float(item.get("lastFundingRate", 0) or 0)
                    out[base] = rate_8h * 3 * 365  # annualize
            _rate_cache["bn"] = (now, out)
            if attempt > 0:
                print(f"[hl_harvest] Binance API recovered after {attempt+1} attempts", file=sys.stderr)
            return out
        except Exception as e:
            last_error = str(e)
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))  # 1.5s, 3s backoff

    print(f"[hl_harvest] Binance API error (3 attempts): {last_error}", file=sys.stderr)
    return {}


def _api_blackout() -> tuple[bool, str]:
    """Detect when upstream data is unavailable, before a cycle acts on it.

    Every fetch_* here degrades to 0.0 / {} / [] on failure, which is
    indistinguishable from a genuine zero balance or a genuine absence of
    spreads. A blind cycle therefore logs "$0.00 USDC" as if it were fact and
    appends empty spread snapshots that poison the consistency gates.
    HL funding rates are the minimum viable input: no rates, no honest cycle.

    Returns (is_blackout, reason).
    """
    if httpx is None:
        return True, f"httpx not installed for {sys.executable}"
    if not fetch_hl_rates():
        return True, "HL API returned no funding rates"
    return False, ""


def find_opportunities(min_spread: float = MIN_SPREAD_ANN) -> list[dict]:
    """Compare HL vs Binance funding rates. Returns opps ≥ min_spread sorted desc.

    Graceful degradation: when Binance API is unreachable (ISP block common on
    Indonesian networks), returns HL-only extreme rates (|rate| ≥ 15%/yr) as
    single-leg positions that earn funding — directionally exposed but rate-positive.
    """
    hl_rates = fetch_hl_rates()
    bn_rates = fetch_binance_rates()
    ops = []

    if bn_rates:
        # Full cross-venue analysis (delta-neutral preferred)
        for sym in UNIVERSE:
            hl = hl_rates.get(sym)
            bn = bn_rates.get(sym)
            if hl is None or bn is None:
                continue
            spread = abs(bn - hl)
            net    = spread - ROUND_TRIP_COST
            if spread >= min_spread:
                direction = "SHORT_BN_LONG_HL" if bn > hl else "SHORT_HL_LONG_BN"
                ops.append({"sym": sym, "direction": direction,
                             "spread_ann": spread, "net_ann": net,
                             "hl_ann": hl, "binance_ann": bn, "source": "cross_venue"})
    else:
        # HL-only fallback when Binance blocked: extreme rates are worth capturing
        # even as directional positions (rate income > typical daily volatility at 25x)
        for sym, rate in hl_rates.items():
            if abs(rate) >= 0.15:   # ≥15%/yr on HL alone
                direction = "LONG_HL" if rate < 0 else "SHORT_HL"
                ops.append({"sym": sym, "direction": direction,
                             "spread_ann": abs(rate), "net_ann": abs(rate) - HL_TAKER * 2,
                             "hl_ann": rate, "binance_ann": None, "source": "hl_only"})

    ops.sort(key=lambda x: x["spread_ann"], reverse=True)
    return ops


def _is_cross_venue_entry(o: dict) -> bool:
    """Only two-sided cross-venue opportunities may reach execution paths."""
    return (
        o.get("source") == "cross_venue"
        and o.get("direction") in {"SHORT_BN_LONG_HL", "SHORT_HL_LONG_BN"}
        and o.get("binance_ann") is not None
        and o.get("hl_ann") is not None
    )


# ── HL account state (public) ─────────────────────────────────────────────────

def fetch_hl_positions(address: str) -> list[dict]:
    """Open perp positions for address. Returns list of {sym, side, size, entryPx,
    unrealizedPnl, cumFunding}."""
    data = _hl_post({"type": "clearinghouseState", "user": address})
    if not data:
        return []
    positions = []
    for pos in data.get("assetPositions", []):
        p = pos.get("position", {})
        size = float(p.get("szi", 0) or 0)
        if size == 0:
            continue
        positions.append({
            "sym":            p.get("coin", "?"),
            "side":           "long" if size > 0 else "short",
            "size":           abs(size),
            "entry_px":       float(p.get("entryPx", 0) or 0),
            "unrealized_pnl": float(p.get("unrealizedPnl", 0) or 0),
            "cum_funding":    float(p.get("cumFunding", {}).get("allTime", 0) or 0),
            "leverage":       p.get("leverage", {}).get("value", "?"),
        })
    return positions


def fetch_hl_spot_balance(address: str) -> float:
    """USDC balance in HL SPOT / unified account."""
    data = _hl_post({"type": "spotClearinghouseState", "user": address})
    if not data:
        return 0.0
    for b in (data.get("balances") or []):
        if b.get("coin", "").upper() in ("USDC", "USD"):
            return float(b.get("total", 0) or 0)
    return 0.0


def fetch_hl_balance(address: str) -> float:
    """Total available USDC for trading — handles both classic and unified accounts.

    Hyperliquid unified account: SPOT USDC automatically serves as collateral
    for perpetual futures. In this mode, clearinghouseState shows $0 even when
    funds are available, because the actual balance is in spotClearinghouseState.

    Returns: max(perp_equity, spot_usdc) — the larger reflects available capital.
    """
    perp_data = _hl_post({"type": "clearinghouseState", "user": address})
    perp_bal  = 0.0
    if perp_data:
        # Try both cross-margin (unified) and isolated-margin summaries
        for key in ("crossMarginSummary", "marginSummary"):
            val = float((perp_data.get(key) or {}).get("accountValue", 0) or 0)
            if val > perp_bal:
                perp_bal = val
        # Also check withdrawable (direct collateral in perp)
        perp_bal = max(perp_bal, float(perp_data.get("withdrawable", 0) or 0))

    spot_bal = fetch_hl_spot_balance(address)

    # Unified account: spot USDC IS the trading capital — return whichever is larger
    return max(perp_bal, spot_bal)


# ── EIP-712 Signing (for trading) ─────────────────────────────────────────────

def _sign_action(private_key: str, action: dict, vault_address: str | None,
                 nonce: int, is_mainnet: bool = True) -> dict:
    """Sign a HL exchange action with EIP-712 (phantom agent scheme).

    v3.3.1: Rewritten to match official hyperliquid-python-sdk sign_l1_action EXACTLY.
    Critical: msgpack.packb WITHOUT use_bin_type or custom float handler.
    Returns {"r": hex, "s": hex, "v": int} dict."""
    import msgpack
    from eth_utils import keccak, to_hex
    from eth_account import Account
    from eth_account.messages import encode_typed_data

    # 1. action_hash: msgpack without any special encoding
    data = msgpack.packb(action)
    data += nonce.to_bytes(8, "big")
    if vault_address is None:
        data += b"\x00"
    else:
        data += b"\x01"
        # str.lstrip strips a CHARACTER SET, not a prefix. Stripping the two
        # characters 0 and x from "0x0794…" also eats the leading 0 of the body
        # → wrong bytes, or ValueError on an odd-length string: a signature
        # over the wrong vault. Remove the prefix explicitly.
        vault_hex = vault_address.lower()
        if vault_hex.startswith("0x"):
            vault_hex = vault_hex[2:]
        data += bytes.fromhex(vault_hex)
    # Note: no expires_after for our use case
    connection_id = keccak(data)

    # 2. construct_phantom_agent
    phantom_agent = {
        "source": "a" if is_mainnet else "b",
        "connectionId": connection_id,
    }

    # 3. l1_payload — match SDK's EIP712Domain exactly
    typed_data = {
        "domain": {
            "chainId": 1337,
            "name": "Exchange",
            "verifyingContract": "0x0000000000000000000000000000000000000000",
            "version": "1",
        },
        "types": {
            "Agent": [
                {"name": "source", "type": "string"},
                {"name": "connectionId", "type": "bytes32"},
            ],
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
        },
        "primaryType": "Agent",
        "message": phantom_agent,
    }

    # 4. sign_inner — use encode_typed_data + sign_message (match SDK exactly)
    structured = encode_typed_data(full_message=typed_data)
    acct = Account.from_key(private_key)
    signed = acct.sign_message(structured)
    return {"r": to_hex(signed["r"]), "s": to_hex(signed["s"]), "v": signed["v"]}


def _exchange(private_key: str, action: dict,
              vault_address: str | None = None) -> dict | None:
    """Post a signed action to HL /exchange. Returns response JSON or None."""
    if not _hl_key_valid(private_key):
        print("[hl_harvest] ERROR: HL_API_SECRET format invalid — signing aborted",
              file=sys.stderr)
        return None
    nonce = _hl_next_nonce()   # monotonic — prevents replay attacks on same-ms calls
    try:
        sig = _sign_action(private_key, action, vault_address, nonce)
    except Exception as e:
        print(f"[hl_harvest] Signing error: {type(e).__name__}: {e}", file=sys.stderr)
        return None
    payload = {
        "action":       action,
        "nonce":        nonce,
        "signature":    sig,
        "vaultAddress": vault_address,
    }
    try:
        r = httpx.post(f"{HL_API}/exchange", json=payload,
                       headers={"Content-Type": "application/json"},
                       timeout=httpx.Timeout(connect=5.0, read=12.0, write=5.0, pool=5.0))
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[hl_harvest] Exchange error: {e}", file=sys.stderr)
        return None


# ── Asset index lookup ────────────────────────────────────────────────────────

_hl_meta_cache: dict | None = None
_hl_meta_cache_ts: float = 0.0
_META_CACHE_TTL: float = 300.0  # 5 min — funding rates change hourly, indices rarely

def _asset_index(sym: str) -> int | None:
    global _hl_meta_cache, _hl_meta_cache_ts
    now = time.time()
    if _hl_meta_cache is None or (now - _hl_meta_cache_ts) > _META_CACHE_TTL:
        result = fetch_hl_meta()
        if result:
            universe, _ = result
            _hl_meta_cache = {a["name"]: i for i, a in enumerate(universe)}
            _hl_meta_cache_ts = now
    if _hl_meta_cache is None:
        return None
    return _hl_meta_cache.get(sym)


# ── Order placement (HL side) ─────────────────────────────────────────────────

def _place_order(private_key: str, sym: str, is_buy: bool,
                 notional: float, is_dry_run: bool) -> dict:
    """Market-order on HL. Returns {ok, sym, side, size, price, reason}.

    Both live and dry_run paths return the same keys so callers (hedge_status,
    run-command state save) can access 'price' and 'size' unconditionally.
    """
    if is_dry_run:
        # size/price are 0.0 placeholders: no real fill, price unknown at dry-run time.
        # hedge_status() guards with 'if entry > 0' before using these values.
        return {"ok": True, "dry_run": True, "sym": sym,
                "side": "long" if is_buy else "short",
                "size": 0.0, "price": 0.0,
                "notional": notional}

    asset_idx = _asset_index(sym)
    if asset_idx is None:
        return {"ok": False, "sym": sym, "reason": "asset not found on HL"}

    # Get current mark price to size the order
    result = fetch_hl_meta()
    if not result:
        return {"ok": False, "sym": sym, "reason": "cannot fetch HL meta"}
    universe, ctxs = result
    ctx = ctxs[asset_idx]
    mark_px = float(ctx.get("markPx", 0) or 0)
    if mark_px <= 0:
        return {"ok": False, "sym": sym, "reason": "invalid mark price"}

    size = round(notional / mark_px, 6)
    # v3.3.1: HL tick grid fix — use oracle for buys, impact_bid for sells
    oracle_px = float(ctx.get("oraclePx", 0) or mark_px)
    impact_pxs = ctx.get("impactPxs", [])
    if is_buy:
        limit_px_raw = round(oracle_px, 5)
    else:
        limit_px_raw = float(impact_pxs[0]) if len(impact_pxs) > 0 else round(oracle_px * 0.995, 5)
        limit_px_raw = round(limit_px_raw, 5)

    # Tick alignment: match oracle's decimal precision (HL rejects off-tick prices)
    # oracle "5.719" → 3dp; "627.71" → 2dp; "0.1107" → 4dp
    oracle_str = ctx.get("oraclePx", "0")
    oracle_dp = len(oracle_str.split(".")[1]) if "." in oracle_str else 0
    limit_px = round(limit_px_raw, oracle_dp)

    from decimal import Decimal as _D
    px_wire = str(_D(str(limit_px)).normalize())

    # Adaptive size rounding: 1dp for most, more for expensive coins
    for sz_dp in [1, 2, 3]:
        sz_test = round(size, sz_dp)
        if sz_test > 0:
            size = sz_test
            break
    sz_wire = str(_D(str(size)).normalize())

    action = {
        "type": "order",
        "orders": [{
            "a": asset_idx,
            "b": is_buy,
            "p": px_wire,
            "s": sz_wire,
            "r": False,
            "t": {"limit": {"tif": "Ioc"}},  # Immediate-or-cancel (taker)
        }],
        "grouping": "na",
    }

    resp = _exchange(private_key, action)
    if resp and resp.get("status") == "ok":
        statuses = resp.get("response", {}).get("data", {}).get("statuses", [])
        if not statuses:
            return {"ok": False, "sym": sym, "reason": "empty statuses in response"}

        # Check for order-level errors (e.g. "Order has invalid price")
        order_error = statuses[0].get("error")
        if order_error:
            return {"ok": False, "sym": sym, "reason": f"HL: {order_error}"}

        filled = statuses[0].get("filled", {})
        filled_sz = float(filled.get("totalSz", 0) or 0)
        filled_px = float(filled.get("avgPx", 0) or 0)

        # CRITICAL: only claim success if order actually FILLED
        if filled_sz <= 0:
            return {"ok": False, "sym": sym,
                    "reason": f"HL order accepted but not filled (sz={filled_sz})"}

        return {
            "ok":     True,
            "sym":    sym,
            "side":   "long" if is_buy else "short",
            "size":   filled_sz,
            "price":  filled_px,
            "notional": notional,
        }
    return {"ok": False, "sym": sym,
            "reason": str(resp)[:120] if resp else "no response"}


def _place_order_maker(private_key: str, sym: str, is_buy: bool,
                       notional: float, is_dry_run: bool,
                       offset_pct: float = 0.0003) -> dict:
    """R3: Post-only (ALO) maker limit order on HL perp. Fee = 0.015% vs 0.045% taker.

    Places at mark ± offset_pct so the order rests in the book (never crosses spread).
    Returns same contract as _place_order: {ok, sym, side, size, price, order_type}.
    order_type='maker_resting' means filled=0 but order is live on the book with order_id.
    Caller may poll for fill or cancel via cmd_cancel_maker().
    """
    if is_dry_run:
        return {"ok": True, "dry_run": True, "sym": sym,
                "side": "long" if is_buy else "short",
                "size": 0.0, "price": 0.0, "notional": notional,
                "order_type": "maker_dry_run"}

    asset_idx = _asset_index(sym)
    if asset_idx is None:
        return {"ok": False, "sym": sym, "reason": "asset not found on HL"}

    result = fetch_hl_meta()
    if not result:
        return {"ok": False, "sym": sym, "reason": "cannot fetch HL meta"}
    universe, ctxs = result
    ctx = ctxs[asset_idx]
    mark_px = float(ctx.get("markPx", 0) or 0)
    if mark_px <= 0:
        return {"ok": False, "sym": sym, "reason": "invalid mark price"}

    size = round(notional / mark_px, 6)
    # ALO: place BELOW mark to buy (passive bid), ABOVE mark to sell (passive ask)
    limit_px = mark_px * (1.0 - offset_pct if is_buy else 1.0 + offset_pct)
    # float_to_wire: normalize via Decimal to strip trailing zeros
    from decimal import Decimal as _D
    px_wire = str(_D(str(limit_px)).normalize())
    sz_wire = str(_D(str(size)).normalize())

    action = {
        "type": "order",
        "orders": [{
            "a": asset_idx,
            "b": is_buy,
            "p": px_wire,
            "s": sz_wire,
            "r": False,
            "t": {"limit": {"tif": "Alo"}},  # Add Liquidity Only = post-only maker
        }],
        "grouping": "na",
    }

    resp = _exchange(private_key, action)
    if resp and resp.get("status") == "ok":
        statuses = resp.get("response", {}).get("data", {}).get("statuses", [])
        if not statuses:
            return {"ok": False, "sym": sym, "reason": "empty statuses (maker)"}
        order_error = statuses[0].get("error")
        if order_error:
            return {"ok": False, "sym": sym, "reason": f"HL: {order_error}"}

        filled  = statuses[0].get("filled", {})
        resting = statuses[0].get("resting", {})

        if filled and float(filled.get("totalSz", 0) or 0) > 0:
            return {"ok": True, "sym": sym, "side": "long" if is_buy else "short",
                    "size": float(filled["totalSz"]), "price": float(filled.get("avgPx", limit_px)),
                    "notional": notional, "order_type": "maker_filled",
                    "order_id": filled.get("oid")}
        elif resting:
            # Order accepted and resting on book — report success but note unfilled
            return {"ok": True, "sym": sym, "side": "long" if is_buy else "short",
                    "size": size, "price": limit_px, "notional": notional,
                    "order_type": "maker_resting", "order_id": resting.get("oid"),
                    "note": "resting on book — monitor or cancel"}

    return {"ok": False, "sym": sym, "reason": str(resp)[:120] if resp else "no response"}


def _binance_spot_order(side: str, symbol: str, notional_usd: float,
                         dry_run: bool = True) -> dict:
    """R1: Execute Binance SPOT market order (api/v3, not fapi). side='BUY'|'SELL'.
    Used as spot hedge leg for basis trade (long spot + short perp delta-neutral).
    Returns {"ok": bool, "qty": float, "price": float, "reason": str}."""
    api_key = os.getenv("BINANCE_API_KEY", "")
    secret  = os.getenv("BINANCE_API_SECRET", "")
    if not api_key or not secret:
        return {"ok": False, "reason": "BINANCE_API_KEY/SECRET tidak ada di .env"}
    if dry_run:
        return {"ok": True, "qty": 0.0, "price": 0.0, "reason": "DRY-RUN spot"}

    try:
        import hmac as _hmac, hashlib as _hash, urllib.request as _req, urllib.parse as _uparse
        bn_sym = BINANCE_SYMBOL_MAP.get(symbol, symbol) + "USDT"

        # Fetch current price
        price_url = f"{BINANCE_SAPI}/ticker/price?symbol={bn_sym}"
        with _req.urlopen(price_url, timeout=_TIMEOUT_BN) as r:
            price = float(json.load(r)["price"])

        # Get lot size filter
        info_url = f"{BINANCE_SAPI}/exchangeInfo?symbol={bn_sym}"
        with _req.urlopen(info_url, timeout=_TIMEOUT_BN) as r:
            info = json.load(r)
        step_size = 1.0
        for s in info.get("symbols", []):
            if s["symbol"] == bn_sym:
                for f in s.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        step_size = float(f["stepSize"])

        qty = notional_usd / price
        if step_size <= 0:
            step_size = 1e-8
        precision = max(0, int(round(-math.log10(step_size))))
        qty = round(round(qty / step_size) * step_size, precision)
        if qty <= 0:
            return {"ok": False, "reason": f"Spot qty terlalu kecil: {qty} ({bn_sym})"}

        ts = int(time.time() * 1000)
        params = {
            "symbol": bn_sym, "side": side, "type": "MARKET",
            "quantity": qty, "timestamp": ts, "recvWindow": 5000,
        }
        qs = _uparse.urlencode(params)
        sig = _hmac.new(secret.encode(), qs.encode(), _hash.sha256).hexdigest()
        url = f"{BINANCE_SAPI}/order?{qs}&signature={sig}"
        rq = _req.Request(url, method="POST", headers={"X-MBX-APIKEY": api_key})
        with _req.urlopen(rq, timeout=10) as r:
            result = json.load(r)

        fills = result.get("fills", [])
        if fills:
            filled_price = sum(float(f["price"]) * float(f["qty"]) for f in fills) / \
                           sum(float(f["qty"]) for f in fills)
        else:
            cum_qty  = float(result.get("cummulativeQuoteQty", 0) or 0)
            exec_qty = float(result.get("executedQty", qty) or qty)
            filled_price = cum_qty / exec_qty if exec_qty > 0 else price

        return {"ok": True, "qty": qty, "price": filled_price,
                "order_id": result.get("orderId"), "reason": "spot executed"}
    except Exception as e:
        reason = str(e)[:120]
        try:
            body = json.loads(e.read().decode())  # type: ignore
            bn_msg = body.get("msg", "")
            reason = f"{bn_msg} (code={body.get('code','?')})"
        except Exception:
            pass
        return {"ok": False, "reason": f"BN spot error: {reason}"}


def _close_position(private_key: str, sym: str, size: float,
                    is_currently_long: bool, is_dry_run: bool) -> dict:
    """Close (reduce-only) an existing HL position."""
    if is_dry_run:
        return {"ok": True, "dry_run": True, "sym": sym, "msg": "would close"}

    asset_idx = _asset_index(sym)
    if asset_idx is None:
        return {"ok": False, "sym": sym, "reason": "asset not found"}

    result = fetch_hl_meta()
    if not result:
        return {"ok": False, "sym": sym, "reason": "cannot fetch meta"}
    universe, ctxs = result
    ctx = ctxs[asset_idx]
    mark_px = float(ctx.get("markPx", 0) or 0)
    if mark_px <= 0:
        return {"ok": False, "sym": sym, "reason": "invalid mark price"}

    is_buy_to_close = not is_currently_long  # close long → sell; close short → buy
    # v3.3.2: Tick-aligned close — oracle for buys, impact_bid for sells
    oracle_px = float(ctx.get("oraclePx", 0) or mark_px)
    impact_pxs = ctx.get("impactPxs", [])
    oracle_str = ctx.get("oraclePx", "0")
    oracle_dp = len(oracle_str.split(".")[1]) if "." in oracle_str else 0
    if is_buy_to_close:
        limit_px = round(oracle_px, oracle_dp)
    else:
        limit_px = float(impact_pxs[0]) if len(impact_pxs) > 0 else round(oracle_px * 0.995, oracle_dp)
        limit_px = round(limit_px, oracle_dp)
    from decimal import Decimal as _D
    px_wire = str(_D(str(limit_px)).normalize())
    sz_wire = str(_D(str(size)).normalize())

    action = {
        "type": "order",
        "orders": [{
            "a": asset_idx,
            "b": is_buy_to_close,
            "p": px_wire,
            "s": sz_wire,
            "r": True,  # reduce-only
            "t": {"limit": {"tif": "Ioc"}},
        }],
        "grouping": "na",
    }
    resp = _exchange(private_key, action)
    if resp and resp.get("status") == "ok":
        return {"ok": True, "sym": sym, "msg": "closed"}
    return {"ok": False, "sym": sym,
            "reason": str(resp)[:120] if resp else "no response"}


# ── State persistence ─────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"hl_legs": {}, "binance_legs": {}}


def _save_state(state: dict) -> None:
    """Atomic write (tmp → os.replace) — crash-safe for live position state.
    A non-atomic write that crashes mid-write would corrupt the state file,
    causing _load_state() to return {} and lose all open position records.
    """
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(STATE_FILE) + ".tmp"
    Path(tmp).write_text(json.dumps(state, indent=2))
    os.replace(tmp, str(STATE_FILE))
    try:
        STATE_FILE.chmod(0o600)  # restrict to owner-only (contains position data)
    except Exception:
        pass


# ── CLI commands ──────────────────────────────────────────────────────────────

SURVIVAL_EVAL_FILE = Path.home() / "anantara-sakti" / "data" / "hl_survival_eval_latest.json"
LEARNING_EVAL_FILE = Path.home() / "anantara-sakti" / "data" / "hl_learning_eval_latest.json"


def _print_oos_reality_check() -> None:
    """Print the out-of-sample counter-evidence next to the snapshot yield.

    The snapshot yield annualizes a spread observed right now, which is the most
    optimistic reading available and the one most likely to justify a bad live
    entry. The scheduled evals measure what actually happened: how often a
    position survives to break-even, and whether the edge clears fees OOS.
    Printing them together stops the plan from reading like a forecast.
    """
    lines: list[str] = []
    try:
        coins = json.loads(SURVIVAL_EVAL_FILE.read_text()).get("coins", [])
        if coins:
            surv, flip = [], []
            for c in coins:
                h72 = (c.get("horizons") or {}).get("72h") or {}
                if isinstance(h72.get("survival_pct"), (int, float)):
                    surv.append(h72["survival_pct"])
                if isinstance(h72.get("sign_flip_pct"), (int, float)):
                    flip.append(h72["sign_flip_pct"])
            if surv:
                lines.append(f"  ⚠️  OOS survival @72h: {sum(surv)/len(surv):.1f}% "
                             f"(sign-flip {sum(flip)/len(flip):.1f}%) across {len(surv)} coins")
    except Exception:
        pass
    try:
        coins = json.loads(LEARNING_EVAL_FILE.read_text()).get("coins", [])
        if coins:
            failing = sum(1 for c in coins if "OOS_FAIL" in str(c.get("decision", "")))
            if failing:
                lines.append(f"  ⚠️  OOS walk-forward: {failing}/{len(coins)} coins FAIL "
                             f"fee-adjusted out-of-sample")
    except Exception:
        pass

    if lines:
        print("\n  ── Reality check (scheduled evals) ──")
        for ln in lines:
            print(ln)
        print("  The snapshot yield above assumes the spread persists; these say it does not.")


def cmd_plan(capital: float, min_spread: float = MIN_SPREAD_ANN):
    """Display current cross-venue spread opportunities (read-only)."""
    print(f"\n{'='*62}")
    print(f" HYPERLIQUID × BINANCE — Cross-Venue Arb Plan  (capital ${capital:.0f})")
    print(f"{'='*62}")
    print(f" Fetching live rates …")

    raw_ops = find_opportunities(min_spread)
    ops = [o for o in raw_ops if _is_cross_venue_entry(o)]
    if not ops:
        print(f"\n  No executable cross-venue assets meet spread ≥ {min_spread*100:.1f}%/yr right now.")
        hl_only = [o for o in raw_ops if o.get("source") == "hl_only"]
        if hl_only:
            print("  RESEARCH ONLY: Binance data is unavailable; HL-only signals are not delta-neutral.")
            for o in hl_only[:5]:
                print(f"    {o['sym']:8s}  HL {o['hl_ann']*100:+6.2f}%/yr  "
                      f"source={o.get('source')} direction={o.get('direction')}")
            return
        print(f"  Best cross-venue assets below threshold:")
        ops_all = [o for o in find_opportunities(0.0) if _is_cross_venue_entry(o)]
        for o in ops_all[:5]:
            print(f"    {o['sym']:8s}  BN {o['binance_ann']*100:+6.2f}%/yr  "
                  f"HL {o['hl_ann']*100:+6.2f}%/yr  "
                  f"spread {o['spread_ann']*100:.2f}%/yr")
        return

    print(f"\n {'SYM':<7}{'DIRECTION':<22}{'SPREAD':>9}{'HL':>9}{'BINANCE':>9}{'ALLOC':>8}")
    print(f" {'-'*64}")

    total_alloc = 0.0
    plan_rows = []
    for o in ops:
        alloc = min(capital * ALLOC_CAP, capital - total_alloc)
        alloc = max(alloc, 0)
        if alloc < MIN_NOTIONAL:
            break
        total_alloc += alloc
        plan_rows.append({**o, "alloc": alloc})

        direction_label = ("SHORT Binance / LONG HL"
                           if o["direction"] == "SHORT_BN_LONG_HL"
                           else "LONG Binance / SHORT HL")
        print(f" {o['sym']:<7}{direction_label:<22}"
              f"{o['spread_ann']*100:>8.2f}%"
              f"{o['hl_ann']*100:>8.2f}%"
              f"{o['binance_ann']*100:>8.2f}%"
              f"  ${alloc:>6.0f}")

    print(f"\n  Total deployed: ${total_alloc:.0f} / ${capital:.0f}")
    rt_cost_pct = ROUND_TRIP_COST * 100
    weighted_spread = sum(r["spread_ann"] for r in plan_rows) / len(plan_rows) if plan_rows else 0
    weighted_net = weighted_spread - ROUND_TRIP_COST
    print(f"  Round-trip fee: {rt_cost_pct:.3f}% per notional")
    print(f"  Snapshot yield (avg, if spread holds 1yr): {weighted_net*100:.2f}%/yr")
    hold_days_breakeven = (ROUND_TRIP_COST / weighted_spread * 365) if weighted_spread > 0 else 999
    print(f"  Break-even hold: {hold_days_breakeven:.1f} days")
    _print_oos_reality_check()
    print(f"\n  To open: python3 anantara/hl_harvest.py run --capital {capital:.0f}")
    print(f"  Requires: HL_API_SECRET in .env + FUNDING_LIVE=1")
    print()


def cmd_basis_plan(capital: float):
    """R1: Display HL basis trade opportunities (long spot + short perp, delta-neutral).

    Scans FULL HL funding rate (not cross-venue spread differential). Captures structural
    premium (8–18%/yr positive 92% of time) vs current strategy's transient differential.

    No API key required — read-only rate fetch."""
    print(f"\n{'='*66}")
    print(f" BASIS HARVEST PLAN  —  HL Perp Funding  (capital ${capital:.0f})")
    print(f" Strategy: Long BN Spot + Short HL Perp  (delta-neutral)")
    print(f" Entry fee: {BASIS_ROUND_TRIP*100:.2f}%/RT  |  Break-even hold ≈ 7 days at 12%/yr")
    print(f"{'='*66}")

    hl_rates = fetch_hl_rates()
    if not hl_rates:
        print("\n  ❌ Cannot fetch HL rates.")
        return

    opps = find_basis_opportunities(min_rate=0.04)  # show all ≥4%/yr for reference
    if not opps:
        print(f"\n  No assets with HL funding ≥ 4%/yr right now.")
        print(f"  Current HL rates:")
        for sym, r in sorted(hl_rates.items(), key=lambda x: abs(x[1]), reverse=True)[:8]:
            print(f"    {sym:<8}  {r*100:+.2f}%/yr")
        return

    print(f"\n {'SYM':<7}{'DIRECTION':<24}{'HL RATE':>9}{'NET/YR':>9}{'B/E DAYS':>10}{'ALLOC':>8}{'STATUS':>10}")
    print(f" {'-'*77}")

    total_alloc = 0.0
    for o in opps:
        alloc = min(capital * BASIS_ALLOC_CAP, BASIS_MAX_NOTIONAL, capital - total_alloc)
        if alloc < MIN_NOTIONAL:
            break
        entry_ok = o["abs_rate_ann"] >= BASIS_MIN_RATE_ANN
        status = "✅ ENTRY" if entry_ok else "⚪ BELOW"
        dir_lbl = ("SHORT HL / LONG BN SPOT" if o["direction"] == "SHORT_PERP_LONG_SPOT"
                   else "LONG HL / SHORT BN SPOT")
        print(f" {o['sym']:<7}{dir_lbl:<24}"
              f"{o['hl_rate_ann']*100:>+8.2f}%"
              f"{o['net_ann']*100:>+8.2f}%"
              f"{o['breakeven_days']:>10.1f}d"
              f"  ${alloc:>5.0f}"
              f"{status:>10}")
        if entry_ok:
            total_alloc += alloc

    print(f"\n  Entry threshold  : {BASIS_MIN_RATE_ANN*100:.0f}%/yr (net positive after {BASIS_ROUND_TRIP*100:.2f}% RT fee)")
    print(f"  Auto-exit at     : {BASIS_MIN_EXIT_ANN*100:.0f}%/yr (prevents paying funding after collapse)")
    print(f"  Consistency gate : {BASIS_CONSISTENCY} consecutive hourly snapshots ≥ threshold")
    print(f"  Max per position : ${BASIS_MAX_NOTIONAL:.0f}")
    print(f"  Total deployable : ${total_alloc:.0f} / ${capital:.0f}")
    print(f"\n  Benchmark: HLP Vault ~20%/yr passive (no active management)")
    print(f"  Target   : basis harvest 12–18%/yr net after fees")
    print(f"\n  To execute: python3 anantara/hl_harvest.py basis-run --capital {capital:.0f}")
    print(f"  Requires : BINANCE_API_KEY + BINANCE_API_SECRET + HL_HARVEST_API_SECRET + FUNDING_LIVE=1")
    print()


def cmd_monitor():
    """Show open HL positions + hedge status. Auto-syncs state with live positions."""
    address = os.getenv("HL_HARVEST_ADDRESS", "")
    if not address:
        print("HL_ADDRESS not set in .env")
        return

    balance      = fetch_hl_balance(address)
    spot_balance = fetch_hl_spot_balance(address)
    positions    = fetch_hl_positions(address)
    state        = _load_state()

    # ── Auto-sync: clear stale HL legs when account has no open positions ──────
    if not positions and state.get("hl_legs"):
        state["hl_legs"] = {}
        state.setdefault("closed_at", datetime.now(timezone.utc).isoformat())
        _save_state(state)
        print("[hl_harvest] Auto-synced: HL legs cleared (no open positions)")

    print(f"\n{'='*62}")
    print(f" HYPERLIQUID POSITIONS  —  {address[:10]}…")
    print(f" PERP Balance: ${balance:.2f} USDC  |  SPOT Balance: ${spot_balance:.2f} USDC")
    print(f" {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*62}")

    is_unified = spot_balance > 1 and balance <= spot_balance
    if is_unified:
        print(f"  ✅ Unified account — SPOT USDC otomatis jadi collateral PERP")
        print(f"     Tidak perlu transfer terpisah")

    if not positions:
        print("  ✅ No open positions on Hyperliquid.")
        if balance < 10 and spot_balance < 1:
            print(f"  ⚠️  Balance ${balance:.2f} — deposit USDC ke {address[:10]}… untuk mulai")
            ops = find_opportunities()
            if ops:
                print(f"  💡 Best opportunity now: {ops[0]['sym']} {ops[0]['spread_ann']*100:.1f}%/yr")
    else:
        print(f"\n  {'SYM':<7}{'SIDE':<6}{'SIZE':>9}{'ENTRY':>10}{'UPNL':>12}{'UPNL%':>8}{'HEDGE':>8}")
        print(f"  {'-'*62}")
        total_upnl = 0.0
        total_notional = 0.0
        stop_loss_pct = 5.0  # alert threshold

        bn_legs = state.get("binance_legs", {})
        for p in positions:
            notional  = p["size"] * p["entry_px"]
            upnl_pct  = p["unrealized_pnl"] / notional * 100 if notional > 0 else 0
            hedge_tag = "✅" if (bn_legs.get(p["sym"], {}).get("side") and
                                 not bn_legs.get(p["sym"], {}).get("note")) else "⚠️ NAKED"
            risk_icon = "🔴" if upnl_pct < -stop_loss_pct else ("🟡" if upnl_pct < -2 else "🟢")
            total_upnl     += p["unrealized_pnl"]
            total_notional += notional
            print(f"  {p['sym']:<7}{p['side']:<6}{p['size']:>9.4f}"
                  f"${p['entry_px']:>9.4f}"
                  f"  {risk_icon}${p['unrealized_pnl']:>+8.2f}"
                  f" {upnl_pct:>+7.2f}%"
                  f"  {hedge_tag}")
            print(f"         notional ${notional:.0f}  lev {p.get('leverage',1)}x  "
                  f"cum_funding ${p['cum_funding']:+.4f}")

        total_pnl_pct = total_upnl / total_notional * 100 if total_notional > 0 else 0
        net = total_upnl + sum(p["cum_funding"] for p in positions)
        print(f"\n  {'─'*62}")
        print(f"  Total UPNL: ${total_upnl:+.2f} ({total_pnl_pct:+.2f}%)  "
              f"Net (incl funding): ${net:+.4f}")
        if total_upnl < -total_notional * stop_loss_pct / 100:
            print(f"  🔴 STOP-LOSS ALERT: UPNL > {stop_loss_pct}% — run: make hl-close")

        # Hedge status
        unhedged = [sym for sym in (p["sym"] for p in positions)
                    if bn_legs.get(sym, {}).get("note")]
        if unhedged:
            print(f"\n  ⚠️  UNHEDGED (no Binance leg): {', '.join(unhedged)}")
            print(f"     Delta-neutral risk: posisi ini bersifat DIRECTIONAL")

    # Binance legs
    bn_legs = state.get("binance_legs", {})
    if bn_legs:
        print(f"\n  Binance legs (local state):")
        for sym, leg in bn_legs.items():
            status = "✅ OPEN" if not leg.get("note") else "⚠️  PLANNED (belum dibuka)"
            print(f"    {sym}: {leg.get('side','?')} ${leg.get('notional',0):.0f}  {status}")

    # ── Spread history snapshot (appended each monitor cycle) ──
    try:
        hl_rates = fetch_hl_rates()
        bn_rates = fetch_binance_rates()
        snap = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "spreads": {}, "hl_rates": {}}
        for sym in state.get("hl_legs", {}):
            hl_r = hl_rates.get(sym, 0)
            bn_r = bn_rates.get(sym, 0) if bn_rates else None
            snap["spreads"][sym] = round(abs(hl_r - bn_r), 6) if bn_r is not None else round(abs(hl_r), 6)
        # Record raw rates like the auto cycle does. Previously this snapshot
        # only covered open legs, so with zero positions it was ALWAYS empty —
        # every monitor run appended a permanently blind entry.
        for sym in UNIVERSE:
            if sym in hl_rates:
                snap["hl_rates"][sym] = round(hl_rates[sym], 6)

        # Never store an empty snapshot: besides skewing the blindness metric,
        # it interrupts the run of consecutive snapshots that _spread_consistent
        # requires, so a monitor call could indefinitely disarm the entry gate.
        if snap["spreads"] or snap["hl_rates"]:
            history = state.setdefault("spread_history", [])
            history.append(snap)
            # Keep last 168 entries (7 days at hourly)
            if len(history) > 168:
                state["spread_history"] = history[-168:]
            _save_state(state)
    except Exception as e:
        # history is best-effort and must never block monitor, but a silent
        # failure here is how blind data went unnoticed before.
        print(f"[hl_harvest] Monitor snapshot skipped ({type(e).__name__}: {e})",
              file=sys.stderr)

    print()


def cmd_run(capital: float, dry_run: bool = True):
    """Open cross-venue positions. Requires HL_API_SECRET + FUNDING_LIVE=1."""
    # ── Concurrent run lock — prevent two live runs from colliding ──
    lockfile = STATE_FILE.parent / ".hl_run.lock"
    if not dry_run and lockfile.exists():
        age = time.time() - lockfile.stat().st_mtime
        if age < 120:  # lock younger than 2 min — another run in progress
            print("[hl_harvest] ❌ Another run is in progress (lock < 2 min old). Aborting.")
            return

    private_key = os.getenv("HL_HARVEST_API_SECRET", "").strip()
    is_live     = os.getenv("FUNDING_LIVE", "") == "1"

    if not private_key and not dry_run:
        print("ERROR: HL_API_SECRET not set. Add agent wallet key to .env")
        print("       Create at: app.hyperliquid.xyz → API → Add Agent Wallet")
        sys.exit(1)
    if private_key and not _hl_key_valid(private_key):
        print("ERROR: HL_API_SECRET format invalid (must be 64-char hex or 0x+64hex)")
        sys.exit(1)
    if not is_live:
        dry_run = True

    # Write lock only for actual live runs (after is_live validation)
    if not dry_run:
        lockfile.write_text(str(int(time.time())))

    label = "DRY-RUN" if dry_run else "LIVE"
    print(f"\n[hl_harvest] run — {label}  capital ${capital:.0f}")

    ops = find_opportunities()
    if not ops:
        print("No opportunities meet the spread threshold. No positions opened.")
        # Release on this early exit too — otherwise a live run that finds
        # nothing leaves the lock behind and spuriously blocks the next run
        # for the full 2-minute staleness window.
        if not dry_run and lockfile.exists():
            lockfile.unlink()
        return

    state = _load_state()
    state.setdefault("binance_legs", {})
    state.setdefault("hl_legs", {})
    deployed = 0.0

    # Cap allocation by actual HL balance to avoid over-allocation
    address = os.getenv("HL_HARVEST_ADDRESS", "")
    balance = fetch_hl_balance(address) if address else capital
    safe_cap = min(capital, balance * 3)  # max 3x leverage on total deployed
    print(f"  Balance: ${balance:.2f}  |  Safe cap: ${safe_cap:.0f}")

    for o in ops:
        if not _is_cross_venue_entry(o):
            print(f"  {o.get('sym', '?')}: skip non-cross-venue opportunity "
                  f"({o.get('source', 'unknown')})")
            continue
        if deployed >= safe_cap:
            break
        alloc = min(safe_cap * ALLOC_CAP, safe_cap - deployed)
        # Kelly-based adaptive sizing: larger when spreads are persistent, smaller in chaos
        kelly_cap = _kelly_notional(balance)
        alloc = min(alloc, kelly_cap, MAX_NEW_NOTIONAL)
        if alloc < MIN_NOTIONAL:
            break

        sym = o["sym"]
        if sym in state["hl_legs"]:
            print(f"  {sym}: already has open HL leg — skip")
            continue

        # ── Fase 2: Spread consistency gate — require N consecutive snapshots ──
        if not _spread_consistent(sym):
            print(f"  {sym}: spread consistency gate — need {SPREAD_CONSISTENCY} "
                  f"consecutive snapshots ≥{MIN_SPREAD_ANN*100:.0f}%")
            continue

        # ── Delay antar order (0.8s) — cegah HL API rate-limit + nonce collision ──
        time.sleep(0.8)

        # HL leg — dengan retry untuk transient EIP-712 / wallet errors
        hl_is_buy = (o["direction"] == "SHORT_BN_LONG_HL")  # long HL if BN > HL
        hl_result = None
        for attempt in range(3):
            hl_result = _place_order(private_key, sym, hl_is_buy, alloc, dry_run)
            if hl_result.get("ok"):
                break
            reason = hl_result.get("reason", "")
            if "does not exist" in str(reason) and attempt < 2:
                print(f"  {sym}: HL retry {attempt+2}/3 — EIP-712 transient error")
                time.sleep(2.0)
            else:
                break
        if hl_result.get("ok"):
            state["hl_legs"][sym] = {
                **hl_result,
                "opened_at":  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "spread_ann": o["spread_ann"],
                "direction":  o["direction"],
            }
            print(f"  {sym}: HL {'LONG' if hl_is_buy else 'SHORT'}  "
                  f"${alloc:.0f}  spread {o['spread_ann']*100:.2f}%/yr  [{label}]")

            # Binance hedge leg — eksekusi otomatis (atomic delta-neutral)
            # if HL is LONG → Binance SELL/SHORT (hedge); jika HL SHORT → Binance BUY/LONG
            bn_side     = "SELL" if hl_is_buy else "BUY"
            bn_is_short = hl_is_buy
            print(f"  {sym}: Binance {bn_side} FUTURES ${alloc:.0f}  [{label}]")
            bn_result = _binance_futures_order(bn_side, sym, alloc, dry_run)
            if bn_result.get("ok"):
                state["binance_legs"][sym] = {
                    "side":      "short" if bn_is_short else "long",
                    "notional":  alloc,
                    "qty":       bn_result.get("qty", 0),
                    "entry_px":  bn_result.get("price", 0),
                    "order_id":  bn_result.get("order_id"),
                    "direction": o["direction"],
                    "opened_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                print(f"  {sym}: ✅ delta-neutral OPEN  "
                      f"HL={'LONG' if hl_is_buy else 'SHORT'} + BN={bn_side}  "
                      f"spread {o['spread_ann']*100:.2f}%/yr")
                deployed += alloc
            else:
                # Binance gagal → rollback kaki HL agar tidak directional
                print(f"  {sym}: ❌ Binance leg GAGAL ({bn_result.get('reason','?')}) "
                      f"— ROLLBACK kaki HL")
                hl_size = float(hl_result.get("size", 0))
                if hl_size > 0:
                    _close_position(private_key, sym, hl_size, hl_is_buy, dry_run)
                else:
                    # Fallback: tutup via _place_order sisi berlawanan
                    print(f"  {sym}: close via reverse order (size from result missing)")
                    _place_order(private_key, sym, not hl_is_buy, alloc, dry_run)
                state["hl_legs"].pop(sym, None)
        else:
            print(f"  {sym}: HL leg FAILED — {hl_result.get('reason','?')}")

    _save_state(state)
    # Clean up run lock — ONLY if this invocation acquired it. A dry-run never
    # writes the lock (see acquire above), so releasing unconditionally let a
    # paper/dry-run cycle delete a concurrent LIVE run's lock and break mutual
    # exclusion, allowing two live runs to open duplicate legs.
    if not dry_run:
        lockfile = STATE_FILE.parent / ".hl_run.lock"
        if lockfile.exists():
            lockfile.unlink()
    print(f"\n  Total deployed: ${deployed:.0f}  |  State saved: {STATE_FILE}")


def cmd_basis_run(capital: float, dry_run: bool = True, use_maker: bool = True):
    """R1+R3: Open basis trade positions (long BN spot + short HL perp, delta-neutral).

    Harvests FULL HL funding rate (structural 8–18%/yr) instead of cross-venue spread.
    Uses post-only maker orders on HL (R3) for 3× cheaper fees (0.015% vs 0.045%).
    Atomic: if either leg fails, the other is rolled back.
    Requires: BINANCE_API_KEY + BINANCE_API_SECRET + HL_HARVEST_API_SECRET + FUNDING_LIVE=1.
    """
    lockfile = STATE_FILE.parent / ".hl_basis.lock"
    if not dry_run and lockfile.exists():
        age = time.time() - lockfile.stat().st_mtime
        if age < 120:
            print("[hl_harvest] ❌ Basis run in progress (lock < 2 min). Aborting.")
            return

    private_key = os.getenv("HL_HARVEST_API_SECRET", "").strip()
    is_live     = os.getenv("FUNDING_LIVE", "") == "1"

    if not private_key and not dry_run:
        print("ERROR: HL_API_SECRET not set.")
        sys.exit(1)
    if private_key and not _hl_key_valid(private_key):
        print("ERROR: HL_API_SECRET format invalid (must be 64-char hex)")
        sys.exit(1)
    if not is_live:
        dry_run = True

    if not dry_run:
        lockfile.write_text(str(int(time.time())))

    label = "DRY-RUN" if dry_run else "LIVE"
    print(f"\n[hl_harvest] basis-run — {label}  capital ${capital:.0f}")
    print(f"  Strategy: Long BN Spot + Short HL Perp  "
          f"({'maker ALO' if use_maker else 'taker IOC'} on HL)")

    opps = find_basis_opportunities()
    if not opps:
        print(f"  No basis opportunities ≥ {BASIS_MIN_RATE_ANN*100:.0f}%/yr right now.")
        if not dry_run and lockfile.exists():
            lockfile.unlink()
        return

    state = _load_state()
    state.setdefault(BASIS_STATE_KEY_HL, {})
    state.setdefault(BASIS_STATE_KEY_SPOT, {})

    address = os.getenv("HL_HARVEST_ADDRESS", "")
    balance = fetch_hl_balance(address) if address else capital
    deployed = 0.0

    for o in opps:
        if deployed >= capital * BASIS_ALLOC_CAP:
            break
        sym = o["sym"]
        if sym in state[BASIS_STATE_KEY_HL]:
            print(f"  {sym}: already has basis position — skip")
            continue

        # Consistency gate: N consecutive HL-rate snapshots above threshold
        if not _basis_rate_consistent(sym):
            print(f"  {sym}: basis gate — need {BASIS_CONSISTENCY} consecutive "
                  f"snapshots ≥{BASIS_MIN_RATE_ANN*100:.0f}%/yr ({o['hl_rate_ann']*100:.1f}% now)")
            continue

        alloc = min(capital * BASIS_ALLOC_CAP - deployed, BASIS_MAX_NOTIONAL,
                    balance * 0.5)
        alloc = max(alloc, 0)
        if alloc < MIN_NOTIONAL:
            break

        time.sleep(0.8)

        # SHORT HL perp leg (collect positive funding) or LONG for negative
        is_perp_short = (o["direction"] == "SHORT_PERP_LONG_SPOT")
        perp_is_buy   = not is_perp_short  # short perp = sell = not buy

        if use_maker:
            hl_result = _place_order_maker(private_key, sym, perp_is_buy, alloc, dry_run)
        else:
            hl_result = _place_order(private_key, sym, perp_is_buy, alloc, dry_run)

        if not hl_result.get("ok"):
            print(f"  {sym}: HL perp leg FAILED — {hl_result.get('reason','?')}")
            continue

        print(f"  {sym}: HL {'SHORT' if is_perp_short else 'LONG'} perp "
              f"${alloc:.0f}  rate {o['hl_rate_ann']*100:.2f}%/yr  [{label}]")

        # LONG BN spot leg (hedge delta)
        bn_side = "BUY" if is_perp_short else "SELL"
        print(f"  {sym}: BN spot {bn_side} ${alloc:.0f}  [{label}]")
        bn_result = _binance_spot_order(bn_side, sym, alloc, dry_run)

        if bn_result.get("ok"):
            state[BASIS_STATE_KEY_HL][sym] = {
                **hl_result,
                "opened_at":     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "hl_rate_ann":   o["hl_rate_ann"],
                "direction":     o["direction"],
            }
            state[BASIS_STATE_KEY_SPOT][sym] = {
                "side":       "long" if is_perp_short else "short",
                "notional":   alloc,
                "qty":        bn_result.get("qty", 0),
                "entry_px":   bn_result.get("price", 0),
                "order_id":   bn_result.get("order_id"),
                "venue":      "binance_spot",
                "opened_at":  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            _save_state(state)
            deployed += alloc
            print(f"  {sym}: ✅ BASIS OPEN  "
                  f"HL-{'SHORT' if is_perp_short else 'LONG'} + BN-{bn_side} SPOT  "
                  f"rate {o['hl_rate_ann']*100:.2f}%/yr  net {o['net_ann']*100:.2f}%/yr  [{label}]")
            _log_decision("BASIS_OPEN",
                          f"{sym}: HL {'short' if is_perp_short else 'long'} perp + BN spot "
                          f"rate={o['hl_rate_ann']*100:.2f}%/yr net={o['net_ann']*100:.2f}%/yr",
                          sym=sym, rate=round(o["hl_rate_ann"], 6),
                          notional=alloc, dry_run=dry_run)
        else:
            # Binance spot failed → rollback HL perp to avoid naked directional
            print(f"  {sym}: ❌ BN spot FAILED ({bn_result.get('reason','?')}) → rollback HL perp")
            if not dry_run:
                _close_position(private_key, sym,
                                float(hl_result.get("size", alloc / 100)), perp_is_buy, dry_run)
            state[BASIS_STATE_KEY_HL].pop(sym, None)
            _save_state(state)

    if not dry_run and lockfile.exists():
        lockfile.unlink()
    print(f"\n  Total basis deployed: ${deployed:.0f}  |  State saved.")


def cmd_basis_close(dry_run: bool = True):
    """R1: Close all open basis positions (HL perp + BN spot) atomically."""
    private_key = os.getenv("HL_HARVEST_API_SECRET", "").strip()
    is_live     = os.getenv("FUNDING_LIVE", "") == "1"
    if not is_live:
        dry_run = True

    state       = _load_state()
    hl_legs     = state.get(BASIS_STATE_KEY_HL, {})
    spot_legs   = state.get(BASIS_STATE_KEY_SPOT, {})
    label       = "DRY-RUN" if dry_run else "LIVE"

    print(f"\n[hl_harvest] basis-close — {label}")
    if not hl_legs:
        print("  No open basis positions.")
        return

    hl_rates = fetch_hl_rates()
    for sym, pos in list(hl_legs.items()):
        is_perp_short = (pos.get("direction") == "SHORT_PERP_LONG_SPOT")
        is_currently_long_perp = not is_perp_short
        size = float(pos.get("size", 0))

        # Close HL perp leg
        hl_res = _close_position(private_key, sym, size, is_currently_long_perp, dry_run)

        # Close BN spot leg
        spot_leg = spot_legs.get(sym, {})
        if spot_leg and not spot_leg.get("note"):
            bn_side = "SELL" if is_perp_short else "BUY"  # close spot long → sell
            bn_res  = _binance_spot_order(bn_side, sym, spot_leg.get("notional", 0), dry_run)
        else:
            bn_res = {"ok": True, "reason": "no spot leg"}

        ok = hl_res.get("ok") and bn_res.get("ok")
        icon = "✅" if ok else "❌"
        entry_rate   = pos.get("hl_rate_ann", 0)
        current_rate = hl_rates.get(sym, 0)
        print(f"  {icon} {sym}: perp {'OK' if hl_res.get('ok') else 'FAIL'}  "
              f"spot {'OK' if bn_res.get('ok') else 'FAIL'}  "
              f"entry {entry_rate*100:+.2f}%/yr → exit {current_rate*100:+.2f}%/yr  [{label}]")

        if ok:
            state[BASIS_STATE_KEY_HL].pop(sym, None)
            state[BASIS_STATE_KEY_SPOT].pop(sym, None)
            _log_decision("BASIS_CLOSE",
                          f"{sym}: closed — entry {entry_rate*100:.2f}% exit {current_rate*100:.2f}%",
                          sym=sym, dry_run=dry_run)

    _save_state(state)
    print()


def cmd_close(dry_run: bool = True):
    """Close ALL open positions on BOTH HL and Binance (delta-neutral close)."""
    private_key = os.getenv("HL_HARVEST_API_SECRET", "").strip()
    is_live     = os.getenv("FUNDING_LIVE", "") == "1"
    address     = os.getenv("HL_HARVEST_ADDRESS", "")

    if not private_key and not dry_run:
        print("ERROR: HL_API_SECRET not set.")
        sys.exit(1)
    if private_key and not _hl_key_valid(private_key):
        print("ERROR: HL_API_SECRET format invalid")
        sys.exit(1)
    if not is_live:
        dry_run = True

    positions = fetch_hl_positions(address) if address else []
    state     = _load_state()
    label     = "DRY-RUN" if dry_run else "LIVE"

    print(f"\n[hl_harvest] close — {label}")
    if not positions:
        print("  No open HL positions found.")
    else:
        for pos in positions:
            sym     = pos["sym"]
            is_long = pos["side"] == "long"
            sz      = pos["size"]

            # 1. Close HL leg
            result_hl = _close_position(private_key, sym, sz,
                                        is_long, dry_run)
            hl_ok = result_hl.get("ok")
            print(f"  HL {sym}: {'✅ closed' if hl_ok else '❌ '+str(result_hl.get('reason','?'))}  [{label}]")

            # 2. Close Binance leg (hedge)
            bn_leg = state.get("binance_legs", {}).get(sym, {})
            if bn_leg and not dry_run:
                bn_side = bn_leg.get("side", "")
                bn_notional = bn_leg.get("notional", 0)
                close_side = "SELL" if bn_side == "long" else "BUY"
                result_bn = _binance_futures_order(close_side, sym, bn_notional, False)
                bn_ok = result_bn.get("ok")
                print(f"  BN {sym}: {'✅ closed' if bn_ok else '❌ '+str(result_bn.get('reason','?'))}")
            elif bn_leg:
                print(f"  BN {sym}: would close {bn_leg.get('side')} (dry-run)")
            else:
                print(f"  BN {sym}: no Binance leg in state — skip")

            # 3. Clean state + log
            if hl_ok:
                old_hl = state.get("hl_legs", {}).pop(sym, None)
                old_bn = state.get("binance_legs", {}).pop(sym, None)
                _log_decision("MANUAL_CLOSE",
                    f"{sym}: HL {old_hl.get('side','?')} + BN {old_bn.get('side','?')} closed. "
                    f"Spread was {old_hl.get('spread_ann',0)*100:.1f}%/yr, "
                    f"HL px={result_hl.get('price',0):.4f}",
                    sym=sym, side=old_hl.get('side','?') if old_hl else '?',
                    notional=old_hl.get('notional',0) if old_hl else 0)

    _save_state(state)
    print()


def cmd_emergency_close(dry_run: bool = True):
    """BLACK SWAN: close ALL positions on both HL and Binance immediately.
    Use when: war, regulatory action, exchange hack, extreme volatility.
    Closes HL legs via reduce-only + Binance legs via market order.
    Delta-neutral pairs are closed together to minimize slippage loss."""
    private_key = os.getenv("HL_HARVEST_API_SECRET", "")
    is_live     = os.getenv("FUNDING_LIVE", "") == "1"
    address     = os.getenv("HL_HARVEST_ADDRESS", "")

    if not is_live:
        dry_run = True

    state     = _load_state()
    hl_legs   = state.get("hl_legs", {})
    bn_legs   = state.get("binance_legs", {})
    positions = fetch_hl_positions(address) if address else []
    label     = "DRY-RUN" if dry_run else "🚨 LIVE EMERGENCY"

    print(f"\n{'='*62}")
    print(f"  🚨 EMERGENCY CLOSE — {label}")
    print(f"  ALL positions on HL + Binance will be closed.")
    print(f"{'='*62}")

    closed_hl = 0
    closed_bn = 0

    # 1. Close HL legs
    if positions:
        print(f"\n  HL positions ({len(positions)}):")
        for pos in positions:
            sym = pos["sym"]
            is_currently_long = (pos["side"] == "long")
            result = _close_position(private_key, sym, pos["size"],
                                     is_currently_long, dry_run)
            status = "✅" if result.get("ok") else "❌"
            print(f"    {status} {sym}: {'closed' if result.get('ok') else result.get('reason','?')}")
            if result.get("ok"):
                closed_hl += 1
    else:
        print(f"\n  HL positions: none found on exchange")

    # 2. Close Binance legs
    if bn_legs:
        print(f"\n  Binance legs ({len(bn_legs)}):")
        for sym, leg in bn_legs.items():
            if leg.get("note"):
                continue  # skip planned-but-not-opened
            bn_side = "BUY" if leg.get("side") == "short" else "SELL"
            notl = leg.get("notional", 0)
            result = _binance_futures_order(bn_side, sym, notl, dry_run)
            status = "✅" if result.get("ok") else "❌"
            print(f"    {status} {sym}: {bn_side} ${notl:.0f} — "
                  f"{'closed' if result.get('ok') else result.get('reason','?')}")
            if result.get("ok"):
                closed_bn += 1
    else:
        print(f"\n  Binance legs: none in state")

    # 3. Clear state
    if not dry_run:
        state["hl_legs"] = {}
        state["binance_legs"] = {}
        state["emergency_closed_at"] = datetime.now(timezone.utc).isoformat()
        _save_state(state)

    print(f"\n  {'─'*42}")
    print(f"  HL closed: {closed_hl}  |  Binance closed: {closed_bn}")
    print(f"  State: {'CLEARED' if not dry_run else 'DRY-RUN (unchanged)'}")
    _log_decision("EMERGENCY_CLOSE",
                  f"{'DRY-RUN' if dry_run else 'LIVE'}: HL={closed_hl}, BN={closed_bn}",
                  dry_run=dry_run, hl_closed=closed_hl, bn_closed=closed_bn)
    print(f"{'='*62}\n")


def cmd_pnl_guard(stop_loss_pct: float = 5.0, critical_pct: float = 12.0,
                  dry_run: bool = True) -> int:
    """Stop-loss guard: alerts when UPNL exceeds threshold, closes if critical.

    This is the function that was MISSING during the ARB/INJ position loss.
    Called by daemon job_hl_monitor every hour to protect against naked exposure.

    stop_loss_pct : warn when any position UPNL < -stop_loss_pct% of notional
    critical_pct  : auto-CLOSE when UPNL < -critical_pct% (requires FUNDING_LIVE=1)
    Returns: 0 = all OK, 1 = alert triggered, 2 = closed positions
    """
    address = os.getenv("HL_HARVEST_ADDRESS", "")
    if not address:
        return 0
    positions = fetch_hl_positions(address)
    if not positions:
        return 0

    private_key = os.getenv("HL_HARVEST_API_SECRET", "")
    is_live     = os.getenv("FUNDING_LIVE", "") == "1" and not dry_run

    alerts = []
    closes = []
    for p in positions:
        notional = p["size"] * p["entry_px"]
        if notional <= 0:
            continue
        upnl_pct = p["unrealized_pnl"] / notional * 100
        sym      = p["sym"]

        if upnl_pct < -critical_pct:
            closes.append((sym, upnl_pct, notional))
        elif upnl_pct < -stop_loss_pct:
            alerts.append((sym, upnl_pct, notional))

    exit_code = 0
    if alerts:
        exit_code = 1
        print(f"⚠️  PNL GUARD ALERT — {len(alerts)} posisi melebihi stop-loss {stop_loss_pct}%:")
        for sym, pct, notional in alerts:
            print(f"   {sym}: UPNL {pct:+.2f}% (${notional * pct / 100:.2f})")
        print(f"   Aksi: monitor ketat. Jika berlanjut, jalankan: make hl-close")

    if closes:
        exit_code = 2
        print(f"🔴 PNL GUARD CRITICAL — {len(closes)} posisi >{critical_pct}% loss — AUTO-CLOSE:")
        for sym, pct, notional in closes:
            print(f"   {sym}: UPNL {pct:+.2f}% (${notional * pct / 100:.2f}) → CLOSING")

        if private_key and is_live:
            state = _load_state()
            for sym, pct, notional in closes:
                # Find position to close
                for p in positions:
                    if p["sym"] == sym:
                        is_currently_long = (p["side"] == "long")
                        result = _close_position(private_key, sym, p["size"],
                                                 is_currently_long, False)
                        if result.get("ok"):
                            state.get("hl_legs", {}).pop(sym, None)
                            print(f"   ✅ {sym}: closed (LIVE)")
                        else:
                            print(f"   ❌ {sym}: close FAILED — {result.get('reason','?')}")
            _save_state(state)
        else:
            print(f"   DRY-RUN — set FUNDING_LIVE=1 dan jalankan: make hl-close")

    if not alerts and not closes:
        total_upnl = sum(p["unrealized_pnl"] for p in positions)
        print(f"✅ PNL guard OK — {len(positions)} posisi, total UPNL ${total_upnl:+.2f}")

    return exit_code


def cmd_rates():
    """Show current rates on both exchanges. Graceful if Binance unavailable."""
    hl_rates = fetch_hl_rates()
    bn_rates = fetch_binance_rates()

    if bn_rates:
        print(f"\n{'SYM':<8}{'BINANCE/yr':>11}{'HL/yr':>10}{'SPREAD':>10}")
        print(f"{'-'*40}")
        rows = []
        for sym in UNIVERSE:
            hl = hl_rates.get(sym)
            bn = bn_rates.get(sym)
            if hl is None or bn is None:
                continue
            rows.append((sym, bn, hl, abs(bn - hl)))
        rows.sort(key=lambda x: x[3], reverse=True)
        for sym, bn, hl, spread in rows:
            flag = " ✅" if spread >= MIN_SPREAD_ANN else ""
            print(f"{sym:<8}{bn*100:>+10.3f}%{hl*100:>+9.3f}%{spread*100:>9.3f}%{flag}")
    else:
        # Binance unreachable (common ISP block) — show HL rates only
        print(f"\n⚠️  Binance API tidak tersedia (ISP block?) — menampilkan HL rates only")
        print(f"\n{'SYM':<8}{'HL/yr':>12}{'SIGNAL':>20}")
        print(f"{'-'*42}")
        rows = sorted(hl_rates.items(), key=lambda x: abs(x[1]), reverse=True)
        for sym, hl in rows[:12]:
            if abs(hl) < 0.05:
                continue
            signal = ("🟢 SHORT HL (collect)" if hl > 0.10 else
                      "🔵 LONG HL (collect)" if hl < -0.10 else
                      "⚪ neutral")
            print(f"{sym:<8}{hl*100:>+11.2f}%  {signal}")
        print(f"\n  Tip: Gunakan VPN untuk akses Binance API dan cross-venue arb.")
    print()


def cmd_funding_stats():
    """R4+R7: Scientific analytics on HL funding rates + basis opportunity scoring.

    Shows:
    - Live absolute HL funding rates (annualized) for all UNIVERSE assets
    - Cross-venue spread vs basis spread comparison
    - Funding rate trend from backfill history (AR-1 direction)
    - Structural premium score per asset (for R7 term-structure harvest)
    - HLP Vault benchmark comparison
    """
    hl_rates = fetch_hl_rates()
    bn_rates = fetch_binance_rates()
    state    = _load_state()
    history  = state.get("spread_history", [])

    print(f"\n{'='*72}")
    print(f"  HL FUNDING RATE ANALYTICS  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Scientific basis: funding positive 92% of time (BitMEX 2025 study)")
    print(f"  HLP Vault benchmark: ~20%/yr (baseline passive yield)")
    print(f"{'='*72}")

    # Build per-asset analytics
    rows = []
    for sym in UNIVERSE:
        hl_r = hl_rates.get(sym, None)
        bn_r = bn_rates.get(sym, None) if bn_rates else None
        if hl_r is None:
            continue

        cross_spread = abs(hl_r - bn_r) if bn_r is not None else None
        basis_rate   = abs(hl_r)

        # Trend from history (AR-1: last 6 snapshots)
        hl_hist_rates = [
            snap.get("hl_rates", {}).get(sym, 0)
            for snap in history[-6:]
            if snap.get("hl_rates", {}).get(sym, 0) != 0
        ]
        if len(hl_hist_rates) >= 2:
            trend = hl_hist_rates[-1] - hl_hist_rates[-2]
            trend_str = "↑" if trend > 0.005 else ("↓" if trend < -0.005 else "→")
        else:
            trend_str = "?"

        # Structural score: high abs rate + positive = bullish basis candidate
        score = basis_rate * (1.1 if hl_r > 0 else 0.9)  # slight premium for positive

        basis_entry = "✅ ENTRY" if basis_rate >= BASIS_MIN_RATE_ANN else ""
        rows.append({
            "sym": sym, "hl_r": hl_r, "bn_r": bn_r,
            "cross": cross_spread, "basis": basis_rate,
            "trend": trend_str, "score": score, "basis_entry": basis_entry,
        })

    rows.sort(key=lambda x: x["basis"], reverse=True)

    print(f"\n  {'SYM':<7}{'HL RATE':>10}{'BN RATE':>10}{'CROSS-VENUE':>13}{'BASIS':>9}{'TREND':>6}{'SIGNAL':>10}")
    print(f"  {'-'*68}")
    for r in rows:
        hl_str   = f"{r['hl_r']*100:>+9.2f}%"
        bn_str   = f"{r['bn_r']*100:>+9.2f}%" if r["bn_r"] is not None else "     N/A%"
        cr_str   = f"{r['cross']*100:>12.2f}%" if r["cross"] is not None else "        N/A"
        ba_str   = f"{r['basis']*100:>8.2f}%"
        print(f"  {r['sym']:<7}{hl_str}{bn_str}{cr_str}{ba_str}{r['trend']:>6}  {r['basis_entry']}")

    # Summary comparison
    n_basis_entry = sum(1 for r in rows if r["basis"] >= BASIS_MIN_RATE_ANN)
    n_cross_entry = sum(1 for r in rows if r["cross"] is not None and r["cross"] >= MIN_SPREAD_ANN)
    avg_abs_rate  = sum(r["basis"] for r in rows) / len(rows) if rows else 0

    print(f"\n  {'─'*68}")
    print(f"  Basis entries (≥{BASIS_MIN_RATE_ANN*100:.0f}%/yr HL rate)   : {n_basis_entry}/{len(rows)} assets")
    print(f"  Cross-venue entries (≥{MIN_SPREAD_ANN*100:.0f}%/yr spread) : {n_cross_entry}/{len(rows)} assets")
    print(f"  Avg absolute HL rate                  : {avg_abs_rate*100:.2f}%/yr")
    print(f"  Basis RT cost                         : {BASIS_ROUND_TRIP*100:.2f}% (break-even ~7d at 12%/yr)")
    print(f"  Cross-venue RT cost (maker)           : {MAKER_ROUND_TRIP*100:.3f}% (ALO post-only)")
    print(f"  Cross-venue RT cost (taker, current)  : {ROUND_TRIP_COST*100:.3f}%")
    print(f"\n  HLP Vault (~20%/yr) : deposit at app.hyperliquid.xyz/vaults for passive baseline")
    if n_basis_entry > 0:
        print(f"  ✅ Basis trade available — run: make hl-basis-plan")
    else:
        print(f"  ⏳ No basis entries now — check hourly (rates change with market sentiment)")
    print(f"{'='*72}\n")


# ── Autonomous check cycle (for daemon 24/7) ──────────────────────────────────

def cmd_auto(dry_run: bool = True) -> int:
    """Single autonomous check cycle — scan, decide, log, act.
    Designed to be called by daemon every 30 min (replaces manual monitoring).
    Returns: 0=OK, 1=alert, 2=critical action taken.

    v3.3.4: Respects FUNDING_LIVE=1 env var even without --live flag.
    v3.4.0: Auto-entry + circuit breaker for fully autonomous operation."""
    # Belt and suspenders: --live flag OR FUNDING_LIVE env var
    if os.getenv("FUNDING_LIVE", "") == "1":
        dry_run = False
    exit_code = 0
    address = os.getenv("HL_HARVEST_ADDRESS", "")
    is_live = not dry_run and os.getenv("FUNDING_LIVE", "") == "1"

    # ── Blackout guard: abort before writing fake zeros ──────────────────────
    # Without this the cycle "succeeds" while blind: balance logs as $0.00,
    # spread snapshots append empty, and systemd reports Finished. Fail loud.
    blackout, blackout_reason = _api_blackout()
    if blackout:
        _log_decision("API_BLACKOUT",
                      f"Cycle aborted — {blackout_reason}. No state written; "
                      "zeros would be indistinguishable from real data.",
                      reason=blackout_reason)
        _telegram_send(f"🚨 *HL HARVEST BLIND*\n{blackout_reason}\nCycle aborted, no state written.",
                       silent=False)
        print(f"[hl_harvest] 🚨 API BLACKOUT: {blackout_reason}", file=sys.stderr)
        return 2

    # ── v3.4.0: Circuit Breaker ─────────────────────────────────────────────
    # Protects capital: halts new entries when losses accumulate
    state = _load_state()
    breaker = state.get("_circuit_breaker", {})
    breaker_active = False
    breaker_reason = ""

    # Check 1: Total UPNL < -10% of deployed capital
    if address:
        chain_pos = fetch_hl_positions(address) if address else []
        total_upnl = sum(p.get("unrealized_pnl", 0) or 0 for p in chain_pos)
        total_deployed = sum(float(p.get("notional", 0)) for p in state.get("hl_legs", {}).values())
        if total_deployed > 0 and total_upnl < -total_deployed * 0.10:
            breaker_active = True
            breaker_reason = f"UPNL {total_upnl/total_deployed*100:.0f}% < -10% of deployed"

    # Check 2: Consecutive losing exits ≥ 3
    recent_exits = breaker.get("consecutive_losses", 0)
    if recent_exits >= 3:
        breaker_active = True
        breaker_reason = f"{recent_exits} consecutive losing exits"

    # Check 3: CHAOS regime (extreme funding on 3+ assets — checked below)

    if breaker_active and not breaker.get("active"):
        _log_decision("CIRCUIT_BREAKER", f"ACTIVATED: {breaker_reason}. No new entries until reset.",
                      reason=breaker_reason)
        _telegram_send(f"🛑 *CIRCUIT BREAKER* ACTIVATED\n{breaker_reason}", silent=False)
        print(f"[hl_harvest] 🛑 CIRCUIT BREAKER: {breaker_reason}")
    elif not breaker_active and breaker.get("active"):
        _log_decision("CIRCUIT_BREAKER", "RESET — conditions normalized.")
        print(f"[hl_harvest] ✅ CIRCUIT BREAKER RESET")
    breaker["active"] = breaker_active
    breaker["reason"] = breaker_reason
    state["_circuit_breaker"] = breaker
    _save_state(state)

    # 1. PnL guard — auto-close if critical
    guard_result = cmd_pnl_guard(stop_loss_pct=5.0, critical_pct=12.0, dry_run=dry_run)
    if guard_result >= 2:
        _log_decision("CRITICAL_CLOSE", f"PnL guard triggered auto-close (code={guard_result})",
                      guard_code=guard_result)
        exit_code = max(exit_code, 2)
    elif guard_result == 1:
        _log_decision("PNL_ALERT", "Position(s) below -5% stop-loss", guard_code=guard_result)
        exit_code = max(exit_code, 1)

    # 2. Spread scan — log opportunities
    ops = find_opportunities()
    if ops:
        top = ops[0]
        _log_decision("OPPORTUNITY_SCAN",
                      f"Top: {top['sym']} {top['spread_ann']*100:.1f}%/yr, "
                      f"{len(ops)} assets above {MIN_SPREAD_ANN*100:.0f}%",
                      top_sym=top["sym"], top_spread=round(top["spread_ann"], 6),
                      n_opportunities=len(ops))

    # 2.5 ── Market regime detection: chaos = extreme funding across multiple assets ──
    hl_rates = fetch_hl_rates()
    extreme_rates = {s: r for s, r in hl_rates.items() if abs(r) > 1.0}  # >100%/yr
    regime = "NORMAL"
    if len(extreme_rates) >= 3:
        regime = "CHAOS"
        # Reduce Kelly win-rate assumption in chaos (spreads less reliable)
        global _KELLY_WIN_RATE
        _KELLY_WIN_RATE = 0.50  # more conservative
    elif extreme_rates:
        regime = "ELEVATED"
        _KELLY_WIN_RATE = 0.60
    else:
        _KELLY_WIN_RATE = 0.70  # normal

    if extreme_rates:
        worst = max(extreme_rates, key=lambda s: abs(extreme_rates[s]))
        _log_decision("REGIME_CHECK",
                      f"Regime: {regime} | {len(extreme_rates)} assets with "
                      f"|rate| > 100%/yr (worst: {worst} {extreme_rates[worst]*100:+.1f}%/yr). "
                      f"Kelly WR adjusted to {_KELLY_WIN_RATE:.0%}.",
                      regime=regime, n_extreme=len(extreme_rates),
                      kelly_wr=_KELLY_WIN_RATE)
        if regime == "CHAOS":
            breaker_active = True
            breaker_reason = (
                f"CHAOS regime: {len(extreme_rates)} assets with |funding| > 100%/yr"
            )
            state = _load_state()
            breaker = state.get("_circuit_breaker", {})
            if not breaker.get("active"):
                _log_decision("CIRCUIT_BREAKER",
                              f"ACTIVATED: {breaker_reason}. No new entries until reset.",
                              reason=breaker_reason)
                _telegram_send(f"🛑 *CIRCUIT BREAKER* ACTIVATED\n{breaker_reason}",
                               silent=False)
                print(f"[hl_harvest] 🛑 CIRCUIT BREAKER: {breaker_reason}")
            breaker["active"] = True
            breaker["reason"] = breaker_reason
            state["_circuit_breaker"] = breaker
            _save_state(state)
            exit_code = max(exit_code, 1)

    # 2.6 ── v3.3.4: Rate Velocity Monitoring ──────────────────────────────────
    # Detect funding rate jumps >30pp between cycles (OP lesson: -21%→-67% in 30min)
    state = _load_state()  # load early for rate velocity check
    prev_rates = state.get("_prev_hl_rates", {})
    velocity_alerts = []
    for sym, rate in hl_rates.items():
        prev = prev_rates.get(sym)
        if prev is not None and abs(rate - prev) > 0.30:  # >30pp change
            direction = "⬆" if rate > prev else "⬇"
            velocity_alerts.append((sym, prev, rate))
            _log_decision("RATE_VELOCITY_ALERT",
                f"{sym}: HL rate {prev*100:+.1f}% → {rate*100:+.1f}% "
                f"({direction} {abs(rate-prev)*100:.0f}pp in 30min) — potential direction flip risk!",
                sym=sym, rate_before=round(prev,6), rate_after=round(rate,6),
                delta_pp=round((rate-prev)*100, 1))
    if velocity_alerts:
        print(f"[hl_harvest] ⚡ RATE VELOCITY: {len(velocity_alerts)} assets with >30pp swing!")
        for sym, prev, rate in velocity_alerts[:3]:
            print(f"  {sym}: {prev*100:+.1f}% → {rate*100:+.1f}%")
        exit_code = max(exit_code, 1)
    # Store current rates for next cycle
    state["_prev_hl_rates"] = hl_rates
    _save_state(state)

    # 3. Position audit
    state = _load_state()
    hl_legs = state.get("hl_legs", {})
    bn_legs = state.get("binance_legs", {})

    if hl_legs:
        hl_rates = fetch_hl_rates()
        bn_rates = fetch_binance_rates()
        meta = fetch_hl_meta()

        for sym in list(hl_legs.keys()):  # iterate copy — dict may be mutated during exit
            pos = hl_legs.get(sym)
            if not pos:
                continue
            entry = float(pos.get("price", 0))
            side = pos.get("side", "?")
            notl = float(pos.get("notional", 0))
            hl_r = hl_rates.get(sym, 0)
            bn_r = bn_rates.get(sym, 0) if bn_rates else 0
            spread = abs(hl_r - bn_r)

            # Mark price
            mark = entry
            if meta:
                for a, c in zip(meta[0], meta[1]):
                    if a["name"] == sym:
                        mark = float(c.get("markPx", entry) or entry)
                        break

            pnl_pct = ((entry - mark) / entry * 100) if side == "short" else ((mark - entry) / entry * 100)
            hedge_ok = sym in bn_legs and not bn_legs[sym].get("note")

            # ── v3.3.4: Direction Flip Detection (with BN-down guard) ────────
            current_direction = pos.get("direction", "")
            bn_r_val = bn_r if bn_r is not None else 0
            # Only check flip when Binance is actually available (bn_r dict non-empty)
            # When BN is down, bn_r=0 for all coins → false positives
            bn_available = bool(bn_rates)  # empty dict = BN down
            correct_direction = "SHORT_BN_LONG_HL" if bn_r_val > hl_r else "SHORT_HL_LONG_BN"
            direction_flipped = (bn_available and current_direction and
                                current_direction != correct_direction and
                                spread >= MIN_SPREAD_ANN)

            if direction_flipped:
                _log_decision("DIRECTION_FLIP_ALERT",
                    f"{sym}: position is {current_direction} but market now wants {correct_direction}! "
                    f"HL={hl_r*100:+.1f}%/yr BN={bn_r_val*100:+.1f}%/yr spread={spread*100:.1f}%",
                    sym=sym, old_dir=current_direction, new_dir=correct_direction,
                    hl_rate=round(hl_r, 6), bn_rate=round(bn_r_val, 6))
                _telegram_send(f"⚠️ *DIRECTION FLIP* {sym}\n{current_direction} → {correct_direction}\nHL={hl_r*100:+.1f}% BN={bn_r_val*100:+.1f}%")
                print(f"[hl_harvest] ⚠️  DIRECTION FLIP {sym}: {current_direction} → {correct_direction} "
                      f"(HL={hl_r*100:+.1f}% BN={bn_r_val*100:+.1f}%)")
                exit_code = max(exit_code, 1)

                # ── v3.3.5: Auto-Flip Execution ──────────────────────────────
                # Close wrong-side position + reopen on correct side
                if not dry_run:
                    private_key = os.getenv("HL_HARVEST_API_SECRET", "")
                    is_live = os.getenv("FUNDING_LIVE", "") == "1"
                    if private_key and is_live and spread >= MIN_SPREAD_ANN:
                        print(f"[hl_harvest] 🔄 AUTO-FLIP {sym}: closing wrong side, reopening correct...")
                        is_currently_long = (side == "long")
                        # 1. Close HL leg
                        r_hl = _close_position(private_key, sym,
                                               float(pos.get("size", 0)), is_currently_long, False)
                        # 2. Close BN leg
                        bn_leg = bn_legs.get(sym, {})
                        r_bn = {"ok": True}
                        if bn_leg and not bn_leg.get("note"):
                            bn_close_side = "BUY" if bn_leg.get("side") == "short" else "SELL"
                            r_bn = _binance_futures_order(bn_close_side, sym,
                                                          bn_leg.get("notional", 0), False)

                        if r_hl.get("ok") and r_bn.get("ok"):
                            state.get("hl_legs", {}).pop(sym, None)
                            state.get("binance_legs", {}).pop(sym, None)
                            _save_state(state)
                            _log_decision("AUTO_FLIP_CLOSE",
                                f"{sym}: closed {current_direction} (wrong side). "
                                f"HL={'ok' if r_hl.get('ok') else 'FAIL'} BN={'ok' if r_bn.get('ok') else 'FAIL'}",
                                sym=sym)

                            # 3. Reopen on correct side
                            time.sleep(1.0)  # avoid nonce collision
                            new_is_buy = (correct_direction == "SHORT_BN_LONG_HL")
                            notional = float(pos.get("notional", 0))
                            r_new_hl = _place_order(private_key, sym, new_is_buy, notional, False)

                            if r_new_hl.get("ok"):
                                bn_new_side = "SELL" if new_is_buy else "BUY"
                                r_new_bn = _binance_futures_order(bn_new_side, sym, notional, False)
                                if r_new_bn.get("ok"):
                                    state["hl_legs"][sym] = {
                                        **r_new_hl,
                                        "opened_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                        "spread_ann": spread, "direction": correct_direction,
                                    }
                                    state["binance_legs"][sym] = {
                                        "side": "short" if new_is_buy else "long",
                                        "notional": notional,
                                    }
                                    _save_state(state)
                                    _log_decision("AUTO_FLIP_REOPEN",
                                        f"{sym}: reopened {correct_direction} (correct side). "
                                        f"Spread={spread*100:.1f}% HL={'ok'} BN={'ok'}",
                                        sym=sym, new_direction=correct_direction)
                                    print(f"[hl_harvest] ✅ AUTO-FLIP {sym} COMPLETE: now {correct_direction}")
                                    exit_code = max(exit_code, 2)
                                else:
                                    _log_decision("AUTO_FLIP_FAILED",
                                        f"{sym}: HL reopened but BN FAILED — NAKED! Check manually.",
                                        sym=sym)
                            else:
                                _log_decision("AUTO_FLIP_FAILED",
                                    f"{sym}: HL close ok but reopen FAILED — position lost.",
                                    sym=sym)
                        else:
                            _log_decision("AUTO_FLIP_FAILED",
                                f"{sym}: close failed — HL={'ok' if r_hl.get('ok') else 'FAIL'} "
                                f"BN={'ok' if r_bn.get('ok') else 'FAIL'}",
                                sym=sym)
                elif direction_flipped and dry_run:
                    _log_decision("AUTO_FLIP_DRY",
                        f"{sym}: would flip {current_direction} → {correct_direction} (dry-run)",
                        sym=sym)

            # ── Fase 2 Auto-Exit: close when spread collapses ──────────────────
            # Tier 1: spread below MIN_SPREAD_EXIT → close to prevent paying funding after reversal
            # Tier 2: spread < 3% AND PnL < -3% → emergency close
            should_close = False
            close_reason = ""

            if spread < MIN_SPREAD_EXIT and entry > 0:
                should_close = True
                close_reason = f"spread {spread*100:.1f}% < {MIN_SPREAD_EXIT*100:.0f}% exit gate"
            elif spread < 0.03 and pnl_pct < -3.0 and entry > 0:
                should_close = True
                close_reason = f"spread {spread*100:.1f}% < 3% AND PnL {pnl_pct:+.1f}% < -3%"

            if should_close and not dry_run:
                private_key = os.getenv("HL_HARVEST_API_SECRET", "")
                is_live = os.getenv("FUNDING_LIVE", "") == "1"
                if private_key and is_live:
                    is_currently_long = (side == "long")
                    # Close HL leg
                    result_hl = _close_position(private_key, sym,
                                                float(pos.get("size", 0)), is_currently_long, False)
                    # Close Binance leg
                    bn_leg = bn_legs.get(sym, {})
                    if bn_leg and not bn_leg.get("note"):
                        bn_close_side = "BUY" if bn_leg.get("side") == "short" else "SELL"
                        result_bn = _binance_futures_order(bn_close_side, sym,
                                                           bn_leg.get("notional", 0), False)
                    else:
                        result_bn = {"ok": True, "reason": "no BN leg to close"}

                    if result_hl.get("ok") and result_bn.get("ok"):
                        state.get("hl_legs", {}).pop(sym, None)
                        state.get("binance_legs", {}).pop(sym, None)
                        _save_state(state)
                        _log_decision("AUTO_EXIT", f"{sym}: {close_reason} — BOTH legs closed",
                                      sym=sym, reason=close_reason)
                        _telegram_send(f"🚪 *AUTO-EXIT* {sym}\n{close_reason}\nUPNL: {pnl_pct:+.1f}%")
                        exit_code = max(exit_code, 2)
                        print(f"[hl_harvest] AUTO-EXIT {sym}: {close_reason} — BOTH legs closed")

                        # ── v3.4.0: Circuit breaker loss tracking ──────────
                        pos_upnl = pnl_pct  # from position audit above
                        cb = state.get("_circuit_breaker", {})
                        if pos_upnl < 0:
                            cb["consecutive_losses"] = cb.get("consecutive_losses", 0) + 1
                            if cb["consecutive_losses"] >= 3:
                                cb["active"] = True
                                cb["reason"] = f"{cb['consecutive_losses']} consecutive losing exits"
                                _log_decision("CIRCUIT_BREAKER",
                                    f"ACTIVATED: {cb['consecutive_losses']} consecutive losses after {sym} exit",
                                    consecutive_losses=cb["consecutive_losses"])
                                print(f"[hl_harvest] 🛑 CIRCUIT BREAKER: {cb['consecutive_losses']} consecutive losses")
                        else:
                            cb["consecutive_losses"] = 0  # reset on profit
                        state["_circuit_breaker"] = cb
                        _save_state(state)
                    else:
                        _log_decision("AUTO_EXIT_FAILED",
                                      f"{sym}: HL={'ok' if result_hl.get('ok') else 'FAIL'}, "
                                      f"BN={'ok' if result_bn.get('ok') else 'FAIL'}",
                                      sym=sym)
                else:
                    _log_decision("AUTO_EXIT_DRY", f"{sym}: would close — {close_reason}", sym=sym)
            elif spread < MIN_SPREAD_ANN:
                _log_decision("SPREAD_ALERT", f"{sym}: spread {spread*100:.1f}% < {MIN_SPREAD_ANN*100:.0f}%",
                              sym=sym, spread=round(spread, 6))

            if not hedge_ok:
                _log_decision("UNHEDGED_ALERT", f"{sym}: no Binance hedge leg!", sym=sym)
                exit_code = max(exit_code, 1)

    # 4. Spread history snapshot — accumulate even with 0 positions (paper validation)
    # R1+R4: Now tracks BOTH cross-venue spreads AND absolute HL rates for basis analytics
    try:
        hl_r = fetch_hl_rates() if 'hl_rates' not in dir() else hl_rates
        bn_r = fetch_binance_rates()
        state_snap = _load_state()
        snap = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "spreads": {},
            "hl_rates": {},   # NEW: track absolute HL rates for basis analytics + R4 trend
        }
        # Track cross-venue spreads (existing arb legs + top opportunities)
        tracked_syms: set[str] = set(state_snap.get("hl_legs", {}).keys())
        tracked_syms.update(state_snap.get(BASIS_STATE_KEY_HL, {}).keys())
        if ops:
            tracked_syms.update(o["sym"] for o in ops[:5])
        for sym in tracked_syms:
            if sym not in snap["spreads"]:
                snap["spreads"][sym] = (round(abs(hl_r.get(sym, 0) - bn_r.get(sym, 0)), 6)
                                        if bn_r else round(abs(hl_r.get(sym, 0)), 6))
        # Track absolute HL rates for ALL UNIVERSE assets — basis analytics needs this
        for sym in UNIVERSE:
            if sym in hl_r:
                snap["hl_rates"][sym] = round(hl_r[sym], 6)

        # Only record snapshots that actually captured something. An empty
        # snapshot is not evidence of "no spread" — it is evidence of no data,
        # and storing it dilutes the consistency gates and the blindness metric.
        if snap.get("spreads") or snap.get("hl_rates"):
            history = state_snap.setdefault("spread_history", [])
            history.append(snap)
            if len(history) > 168:
                state_snap["spread_history"] = history[-168:]
            _save_state(state_snap)
        else:
            print("[hl_harvest] Snapshot skipped — no market data captured this cycle",
                  file=sys.stderr)
    except Exception as e:
        print(f"[hl_harvest] Spread history error (non-critical): {type(e).__name__}: {e}",
              file=sys.stderr)

    # 5 ── v3.3.5: Cumulative P&L tracking (reload state to avoid race) ────
    try:
        # CRITICAL: reload state — spread history save above may have modified it.
        # Using old state object would overwrite spread_history with stale data.
        state = _load_state()
        hl_legs = state.get("hl_legs", {})
        if hl_legs and address:
            chain = fetch_hl_positions(address) if address else []
            current_upnl = sum(p.get("unrealized_pnl", 0) or 0 for p in chain)
            current_funding = sum(p.get("cum_funding", 0) or 0 for p in chain)
            prev_pnl = state.get("_cumulative_pnl", {})
            prev_pnl["last_upnl"] = round(current_upnl, 6)
            prev_pnl["last_funding"] = round(current_funding, 6)
            prev_pnl["last_ts"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            prev_pnl.setdefault("peak_upnl", current_upnl)
            prev_pnl.setdefault("trough_upnl", current_upnl)
            if current_upnl > prev_pnl["peak_upnl"]:
                prev_pnl["peak_upnl"] = round(current_upnl, 6)
            if current_upnl < prev_pnl["trough_upnl"]:
                prev_pnl["trough_upnl"] = round(current_upnl, 6)
            state["_cumulative_pnl"] = prev_pnl
            _save_state(state)
            bal = fetch_hl_balance(address) if address else 0
            _log_decision("BALANCE",
                f"Balance=${bal:.2f} UPNL=${current_upnl:+.4f} "
                f"Funding=${current_funding:+.6f} Positions={len(hl_legs)}",
                balance=round(bal, 2), upnl=round(current_upnl, 6),
                funding=round(current_funding, 6), n_positions=len(hl_legs))
    except Exception:
        pass

    # 4b. R1: Scan basis opportunities and log
    try:
        basis_opps = find_basis_opportunities()
        if basis_opps:
            top_b = basis_opps[0]
            _log_decision("BASIS_SCAN",
                          f"Top basis: {top_b['sym']} {top_b['hl_rate_ann']*100:.1f}%/yr "
                          f"net {top_b['net_ann']*100:.1f}%/yr  "
                          f"({len(basis_opps)} assets ≥{BASIS_MIN_RATE_ANN*100:.0f}%/yr)",
                          top_sym=top_b["sym"], top_rate=round(top_b["hl_rate_ann"], 6),
                          n_basis=len(basis_opps))
    except Exception:
        pass

    # 4c. R1: Auto-exit basis positions when HL rate drops below exit threshold
    try:
        private_key_auto = os.getenv("HL_HARVEST_API_SECRET", "")
        is_live_auto     = os.getenv("FUNDING_LIVE", "") == "1"
        state_b          = _load_state()
        basis_hl_legs    = state_b.get(BASIS_STATE_KEY_HL, {})
        if basis_hl_legs:
            for sym, pos in list(basis_hl_legs.items()):
                current_rate = abs(hl_r.get(sym, 0)) if 'hl_r' in dir() else 0
                if current_rate >= BASIS_MIN_EXIT_ANN:
                    continue

                # Proteksi hold minimum (2026-09-06). Setiap RT memotong 0.23%;
                # keluar sebelum posisi sempat membayar biayanya sendiri berarti
                # rugi terjamin. Contoh: masuk di 25%/thn, keluar setelah 1 hari
                # → panen 0.068% tapi bayar 0.23% = rugi bersih.
                # Break-even hold = BASIS_ROUND_TRIP / entry_rate * 365 hari.
                entry_ts = pos.get("entry_ts") or pos.get("ts")
                held_days = None
                if entry_ts:
                    try:
                        entry_dt = datetime.fromisoformat(str(entry_ts).replace("Z", "+00:00"))
                        held_days = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 86400
                    except (ValueError, TypeError):
                        held_days = None

                entry_rate = abs(float(pos.get("rate", 0) or 0))
                be_days = (BASIS_ROUND_TRIP / entry_rate * 365) if entry_rate > 0 else 0

                if held_days is not None and be_days > 0 and held_days < be_days:
                    _log_decision("BASIS_EXIT_HELD",
                                  f"{sym}: rate {current_rate*100:.1f}%/yr di bawah exit, "
                                  f"tapi baru ditahan {held_days:.1f} hari < break-even "
                                  f"{be_days:.1f} hari. Ditahan — keluar sekarang rugi pasti.",
                                  sym=sym, held_days=round(held_days, 2),
                                  be_days=round(be_days, 2))
                    continue

                _log_decision("BASIS_EXIT_SIGNAL",
                              f"{sym}: HL rate {current_rate*100:.1f}%/yr "
                              f"< {BASIS_MIN_EXIT_ANN*100:.0f}%/yr exit threshold"
                              + (f" (ditahan {held_days:.1f} hari)" if held_days is not None else ""),
                              sym=sym, rate=round(current_rate, 6),
                              held_days=round(held_days, 2) if held_days is not None else None)
                if not dry_run and private_key_auto and is_live_auto:
                    cmd_basis_close(dry_run=False)
                    exit_code = max(exit_code, 2)
    except Exception as e:
        print(f"[hl_harvest] Basis auto-exit error: {type(e).__name__}: {e}",
              file=sys.stderr)

    # 4d ── AUDIT FIX 2026-08-25: R1 BASIS AUTO-ENTRY ────────────────────────
    # Gap found in audit: cmd_auto scanned basis opportunities (BASIS_SCAN) and
    # auto-exited them, but NEVER entered. The only OOS-validated config
    # (replay: maker + entry>=12%/yr + exit<4%) never got paper/live cycles,
    # so the project could not accumulate real entry->exit evidence.
    # Entry rules mirror the replay engine exactly:
    #   - |HL rate| >= BASIS_MIN_RATE_ANN (12%/yr)
    #   - stability gate: >=70% positive funding over last 240h (BASIS_CONSISTENCY
    #     snapshots as the live proxy)
    #   - position caps: max BASIS_MAX_POSITIONS concurrent, per-position notional
    #     capped by BASIS_MAX_NOTIONAL and balance
    try:
        state_be = _load_state()
        basis_legs = state_be.get(BASIS_STATE_KEY_HL, {})
        breaker_now = state_be.get("_circuit_breaker", {})
        # AUDIT FIX (cont.) 2026-08-25: dedup ledger for dry-run evidence.
        # Without it the same candidate logs 48x/day at identical rates —
        # noise, not evidence. Re-log only when |rate| moved >BASIS_RELOG_PP
        # or the symbol is new.
        dry_log = state_be.setdefault("_basis_dry_log", {})
        if not breaker_now.get("active") and len(basis_legs) < BASIS_MAX_POSITIONS:
            basis_opps_fresh = find_basis_opportunities()
            for b in basis_opps_fresh:
                if len(basis_legs) >= BASIS_MAX_POSITIONS:
                    break
                sym_b = b["sym"]
                if sym_b in basis_legs:
                    continue
                if not _basis_rate_consistent(sym_b):
                    _log_decision("BASIS_ENTRY_SKIP",
                                  f"{sym_b}: rate {b['abs_rate_ann']*100:.1f}%/yr but "
                                  f"consistency gate failed (<{BASIS_CONSISTENCY} consecutive "
                                  f"snapshots >= {BASIS_MIN_RATE_ANN*100:.0f}%/yr)",
                                  sym=sym_b)
                    continue
                prev_rate = dry_log.get(sym_b, {}).get("rate", 0.0) if isinstance(dry_log.get(sym_b), dict) else 0.0
                rate_moved = abs(b["abs_rate_ann"] - prev_rate) > BASIS_RELOG_PP
                if dry_run or os.getenv("FUNDING_LIVE", "") != "1":
                    if sym_b in dry_log and not rate_moved:
                        continue   # unchanged candidate — already logged
                    _log_decision("BASIS_ENTRY_DRY",
                                  f"{sym_b}: would enter R1 basis {b['direction']} "
                                  f"~${BASIS_MAX_NOTIONAL:.0f} at {b['abs_rate_ann']*100:.1f}%/yr "
                                  f"(net {b['net_ann']*100:.1f}%, breakeven {b['breakeven_days']}d) — dry-run",
                                  sym=sym_b, rate=round(b['abs_rate_ann'], 6))
                    dry_log[sym_b] = {"rate": b["abs_rate_ann"],
                                      "ts": datetime.now(timezone.utc).isoformat()}
                    _save_state(state_be)
                    continue
                # live path — delegate to the battle-tested cmd_basis_run sizing
                _log_decision("BASIS_ENTRY_SIGNAL",
                              f"{sym_b}: entering R1 basis at {b['abs_rate_ann']*100:.1f}%/yr",
                              sym=sym_b, rate=round(b["abs_rate_ann"], 6))
                # AUDIT FIX 2026-09-06: blok ini tadinya hanya mencatat lalu
                # `break` — signal menyala 2026-08-25..09-06 tanpa satu pun
                # order. "Delegate to cmd_basis_run" ada di komentar, tidak
                # di kode. Kini benar-benar mendelegasi:
                cmd_basis_run(capital=BASIS_MAX_NOTIONAL, dry_run=False, use_maker=True)
                break   # one entry per cycle; next cycle re-evaluates
    except Exception as e:
        print(f"[hl_harvest] Basis auto-entry error (non-critical): {type(e).__name__}: {e}",
              file=sys.stderr)

    # 5 ── v3.4.0: AUTO-ENTRY (after all exits) ─────────────────────────────
    # Must run AFTER position audit/exit to avoid opening when slots are full
    if is_live and not breaker_active:
        state_final = _load_state()
        current_hl = state_final.get("hl_legs", {})
        MAX_POSITIONS = 3

        if len(current_hl) < MAX_POSITIONS:
            # Re-fetch opportunities (may have changed during this cycle)
            ops_fresh = find_opportunities()
            private_key_auto = os.getenv("HL_HARVEST_API_SECRET", "")
            balance = fetch_hl_balance(address) if address else 0
            slots = MAX_POSITIONS - len(current_hl)

            for o in ops_fresh:
                if slots <= 0:
                    break
                if not _is_cross_venue_entry(o):
                    _log_decision("AUTO_ENTRY_SKIP",
                                  f"{o.get('sym','?')}: skip non-cross-venue opportunity "
                                  f"source={o.get('source','unknown')} direction={o.get('direction','?')}",
                                  sym=o.get("sym"), source=o.get("source"),
                                  direction=o.get("direction"))
                    continue
                sym = o["sym"]
                if sym in current_hl:
                    continue
                if not _spread_consistent(sym):
                    continue

                kelly = _kelly_notional(balance)
                alloc = min(kelly, MAX_NEW_NOTIONAL, balance * 0.15)
                if alloc < MIN_NOTIONAL:
                    continue

                print(f"[hl_harvest] 🤖 AUTO-ENTRY {sym}: {o['spread_ann']*100:.1f}% "
                      f"{o['direction']} — ${alloc:.0f}")

                is_buy = (o["direction"] == "SHORT_BN_LONG_HL")
                r_hl = _place_order(private_key_auto, sym, is_buy, alloc, False)

                if r_hl.get("ok"):
                    bn_side = "SELL" if is_buy else "BUY"
                    r_bn = _binance_futures_order(bn_side, sym, alloc, False)
                    if r_bn.get("ok"):
                        state_final["hl_legs"][sym] = {
                            **r_hl,
                            "opened_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "spread_ann": o["spread_ann"], "direction": o["direction"],
                        }
                        state_final["binance_legs"][sym] = {
                            "side": "short" if is_buy else "long", "notional": alloc,
                        }
                        _save_state(state_final)
                        _log_decision("AUTO_ENTRY",
                            f"{sym}: {o['direction']} ${alloc:.0f} at {o['spread_ann']*100:.1f}%/yr",
                            sym=sym, notional=round(alloc,2), spread=round(o['spread_ann'],6))
                        _telegram_send(f"🤖 *AUTO-ENTRY* {sym}\n{o['direction']}\nSpread: {o['spread_ann']*100:.1f}%/yr\nSize: ${alloc:.0f}\nPortfolio: {len(state_final['hl_legs'])}/{MAX_POSITIONS}")
                        print(f"[hl_harvest] ✅ AUTO-ENTRY {sym} — {len(state_final['hl_legs'])}/{MAX_POSITIONS} positions")
                        exit_code = max(exit_code, 2)
                        slots -= 1
                        time.sleep(1.0)
                    else:
                        _log_decision("AUTO_ENTRY_FAILED", f"{sym}: BN leg failed", sym=sym)
                        # Rollback HL
                        is_long = is_buy
                        _close_position(private_key_auto, sym, float(r_hl.get("size",0)), is_long, False)
                else:
                    print(f"[hl_harvest] AUTO-ENTRY {sym} SKIP: {r_hl.get('reason','?')[:80]}")

    # 6. Balance snapshot + Periodic Telegram Report (every 6 hours)
    if address:
        balance = fetch_hl_balance(address)
        _log_decision("BALANCE", f"${balance:.2f} USDC", balance=round(balance, 2))

        # Send summary every 6 hours (0, 6, 12, 18 UTC)
        current_hour = datetime.now(timezone.utc).hour
        if current_hour % 6 == 0:
            state_f = _load_state()
            hl_legs_f = state_f.get("hl_legs", {})
            chain_f = fetch_hl_positions(address) if address else []
            upnl = sum(p.get("unrealized_pnl", 0) or 0 for p in chain_f)
            cb_f = state_f.get("_circuit_breaker", {})

            lines = [
                "📊 *HL HARVEST — 6H REPORT*",
                f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC",
                f"💰 Balance: ${balance:.2f}",
                f"📈 Positions: {len(hl_legs_f)}/3 | UPNL: ${upnl:+.2f}",
                f"🛡️ Breaker: {'ACTIVE' if cb_f.get('active') else 'OK'} | Losses: {cb_f.get('consecutive_losses',0)}",
            ]
            for sym, pos in hl_legs_f.items():
                cp = next((p for p in chain_f if p['sym']==sym), None)
                if cp:
                    lines.append(f"  • {sym}: {pos.get('side','?')} ${pos.get('notional',0):.0f} | spread {pos.get('spread_ann',0)*100:.1f}% | UPNL ${cp['unrealized_pnl']:+.2f}")
            if not hl_legs_f:
                lines.append("  ⚠️ No active positions")
            _telegram_send("\n".join(lines), silent=True)

    # ── v3.7.0: Multi-venue funding scan (4 venue) ─────────────────────────
    # Menggantikan spatial-arb scanner v3.6.0 yang dihapus: uji empiris
    # 2026-09-06 menunjukkan spatial arb rugi 17/18 coin (spread rata-rata
    # 0.095% vs fee 0.4%) dan peluangnya mati <30 detik — medan HFT, bukan
    # medan kita. Funding spread antar venue justru 26-78%/thn dan bertahan
    # berjam-jam. Lihat scan_multivenue_funding().
    try:
        mv_ops = scan_multivenue_funding()
        if mv_ops:
            top = mv_ops[0]
            _log_decision("MULTIVENUE_FUNDING_SCAN",
                f"{len(mv_ops)} peluang ≥{MV_MIN_SPREAD_ANN*100:.0f}%/yr. "
                f"Top: {top['sym']} {top['spread_ann']*100:.1f}%/yr "
                f"(LONG {top['long_venue']} / SHORT {top['short_venue']})",
                n_opps=len(mv_ops), top_sym=top["sym"],
                top_spread=round(top["spread_ann"], 6),
                long_venue=top["long_venue"], short_venue=top["short_venue"])
            print(f"[hl_harvest] 🌐 MULTI-VENUE: {len(mv_ops)} peluang, "
                  f"top {top['sym']} {top['spread_ann']*100:.1f}%/yr "
                  f"(LONG {top['long_venue']} / SHORT {top['short_venue']})")
    except Exception as e:
        print(f"[hl_harvest] Multi-venue scan error: {type(e).__name__}: {e}",
              file=sys.stderr)

    return exit_code


# ── v3.7.0: Multi-Venue Funding Scanner ───────────────────────────────────────
# Menggantikan spatial-arb scanner (v3.6.0, dihapus). Bukti empiris 2026-09-06:
#   Spatial arb 6 venue, 18 coin : 17/18 RUGI. Spread rata-rata 0.095% vs fee
#   0.4%. Peluang terbaik (INJ +0.007%) mati dalam <30 detik — 2/5 sampel saja
#   di atas fee. Scan 30 menit tidak akan pernah menangkapnya: medan HFT.
#   Funding spread antar venue : 26-78%/thn, bertahan berjam-jam. Itu medan kita.
#
# INJ membuktikan kenapa multi-venue penting: funding di HL dan Binance sama
# (+11.0%) sehingga scanner dual-venue melihat spread 0% dan melewatkannya.
# Di Bybit funding-nya -67.2% → spread sebenarnya 78.2%/thn.
#
# READ-ONLY: hanya memindai dan mencatat. Tidak menempatkan order.

MV_VENUES = ("Hyperliquid", "Binance", "Bybit", "OKX", "dYdX")
MV_MIN_SPREAD_ANN = 0.25   # 25%/thn — sejajar MIN_SPREAD_ANN cross-venue
MV_TARGET_HOLD_DAYS = 30   # target hold; menentukan fee drag tahunan
MV_TIMEOUT = 6

# dYdX liquidity gate (riset 9-venue 2026-09-06). dYdX funding paling
# independen (stdev 47pp vs 2-6pp CEX lain) TAPI market kecilnya ekstrem:
# LINK OI $376k / volume $134k/hari, dYdX 1150x lebih tipis dari Binance.
# Funding ratusan persen di market setipis itu = gejala, bukan peluang:
# satu pemain menengah bisa membalikkan arah funding kapan saja. Gate
# berbasis OI + volume membuang LINK/LTC/UNI/AAVE/ASTER, menyisakan
# ETH/SOL/BTC/HYPE/ZEC/PAXG yang benar-benar layak dieksekusi.
# Aset yang gagal gate tetap discan di 4 venue CEX — gate ini dYdX saja.
DYDX_MIN_OI_USD  = 100_000     # open interest minimum (ada lawan transaksi)
DYDX_MIN_VOL_USD = 50_000      # volume 24 jam minimum ($100 = <0,2% volume)
DYDX_MIN_TRADES  = 100         # trade 24 jam minimum (aliran order kontinu)
DYDX_PASS_EITHER = False       # WAJIB ketiganya — bukan salah satu
# 2026-09-11 (audit, disetujui user): kalibrasi ulang berbasis UJI KELAYAKAN
# EKSEKUSI, bukan angka bulat. Tiga kriteria harus lolos SEMUA:
#   1. trades24H >= 100  -> pasar hidup, bukan mati (AAVE cuma 4 trade/hari)
#   2. vol24H >= $50k    -> notional $100 tidak menggerakkan harga
#   3. OI >= $100k       -> ada lawan transaksi saat keluar posisi
# Hasil: 5 coin (BTC, ETH, LTC, SOL, ZEC).
# Ambang lama OI $5jt ATAU vol $1jt meloloskan 9 coin, tapi 6 di antaranya
# PALSU akibat bug konversi volume (lihat _mv_fetch_dydx). Setelah bug
# diperbaiki ambang lama hanya meloloskan 3 coin — terlalu ketat, membuang
# LTC (funding 17,2%/thn, 216 trade) dan ZEC (5,1%/thn, vol $83k) yang
# pasarnya nyata dan layak dieksekusi pada notional kita.

import urllib.request as _ur   # stdlib: dipakai semua fetcher multi-venue di bawah


def _mv_fetch_hyperliquid() -> dict:
    """Funding Hyperliquid (settle per JAM → annualisasi x24x365)."""
    out = {}
    try:
        req = _ur.Request(f"{HL_API}/info",
                          data=json.dumps({"type": "metaAndAssetCtxs"}).encode(),
                          headers={"Content-Type": "application/json",
                                   "User-Agent": "anantara-mv/1.0"})
        with _ur.urlopen(req, timeout=MV_TIMEOUT) as r:
            data = json.load(r)
        if isinstance(data, list) and len(data) == 2:
            for asset, ctx in zip(data[0]["universe"], data[1]):
                name = asset.get("name")
                if name in UNIVERSE:
                    try:
                        out[name] = float(ctx["funding"]) * 24 * 365
                    except (KeyError, TypeError, ValueError):
                        pass
    except Exception:
        pass
    return out


def _mv_fetch_binance() -> dict:
    """Funding Binance USDM (settle per 8 JAM → annualisasi x3x365)."""
    out = {}
    try:
        req = _ur.Request(f"{BINANCE_FAPI}/premiumIndex",
                          headers={"User-Agent": "anantara-mv/1.0"})
        with _ur.urlopen(req, timeout=MV_TIMEOUT) as r:
            for item in json.load(r):
                sym = item.get("symbol", "")
                if sym.endswith("USDT") and sym[:-4] in UNIVERSE:
                    try:
                        out[sym[:-4]] = float(item["lastFundingRate"]) * 3 * 365
                    except (KeyError, TypeError, ValueError):
                        pass
    except Exception:
        pass
    return out


def _mv_fetch_bybit() -> dict:
    """Funding Bybit linear perp (settle per 8 JAM → annualisasi x3x365)."""
    out = {}
    try:
        req = _ur.Request("https://api.bybit.com/v5/market/tickers?category=linear",
                          headers={"User-Agent": "anantara-mv/1.0"})
        with _ur.urlopen(req, timeout=MV_TIMEOUT) as r:
            data = json.load(r)
        for item in data.get("result", {}).get("list", []):
            sym = item.get("symbol", "")
            if sym.endswith("USDT") and sym[:-4] in UNIVERSE:
                try:
                    out[sym[:-4]] = float(item["fundingRate"]) * 3 * 365
                except (KeyError, TypeError, ValueError):
                    pass
    except Exception:
        pass
    return out


def _mv_fetch_okx() -> dict:
    """Funding OKX swap (settle per 8 JAM → annualisasi x3x365).

    OKX tidak punya endpoint bulk untuk funding, jadi satu request per coin.
    Universe 23 coin = 23 request x ~0.15s ≈ 3.5s per siklus — masih jauh di
    bawah interval 30 menit, dan venue yang gagal hanya mengurangi data, bukan
    mematikan siklus.
    """
    out = {}
    for coin in UNIVERSE:
        try:
            req = _ur.Request(
                f"https://www.okx.com/api/v5/public/funding-rate?instId={coin}-USDT-SWAP",
                headers={"User-Agent": "anantara-mv/1.0"})
            with _ur.urlopen(req, timeout=3) as r:
                data = json.load(r)
            if data.get("data"):
                out[coin] = float(data["data"][0]["fundingRate"]) * 3 * 365
        except Exception:
            continue
    return out


def _mv_fetch_dydx() -> dict:
    """Funding dYdX v4 (settle per JAM → annualisasi x24x365), dengan gate likuiditas.

    Satu-satunya venue dengan sinyal funding benar-benar independen (stdev
    47pp), tapi market kecilnya berbahaya: LINK OI $376k, volume $134k/hari —
    1150x lebih tipis dari Binance. Funding +194% di situ gejala pasar tipis.
    Market di bawah gate OI/volume dilewati; angkanya nyata, tapi tidak bisa
    dipercaya untuk posisi 30 hari.
    """
    out = {}
    try:
        req = _ur.Request("https://indexer.dydx.trade/v4/perpetualMarkets",
                          headers={"User-Agent": "anantara-mv/1.0"})
        with _ur.urlopen(req, timeout=MV_TIMEOUT) as r:
            markets = json.load(r).get("markets", {})
    except Exception:
        return out
    for key, m in markets.items():
        base = key.split("-")[0]
        if base not in UNIVERSE:
            continue
        try:
            oi_usd = float(m.get("openInterest", 0)) * float(m.get("oraclePrice", 0))
            vol_raw = float(m.get("volume24H", 0))
            # volume24H dYdX SELALU dalam USD (terverifikasi 2026-09-11 via uji
            # falsifikasi: volume/trades24H hanya masuk akal sebagai USD —
            # BTC $1.708/trade. Heuristik lama "kalau vol < 50% OI maka kali
            # harga" MENGGELEMBUNGKAN volume: BTC jadi $293 MILIAR, ZEC $89 juta,
            # PAXG $26 juta — semuanya lolos gate karena angka palsu.)
            vol_usd = vol_raw
            trades = float(m.get("trades24H", 0) or 0)
            oi_ok = oi_usd >= DYDX_MIN_OI_USD
            vol_ok = vol_usd >= DYDX_MIN_VOL_USD
            tr_ok = trades >= DYDX_MIN_TRADES
            if DYDX_PASS_EITHER:
                passes = (oi_ok or vol_ok) and tr_ok
            else:
                passes = oi_ok and vol_ok and tr_ok
            if not passes:
                continue
            out[base] = float(m["nextFundingRate"]) * 24 * 365
        except (KeyError, TypeError, ValueError):
            continue
    return out


def fetch_multivenue_rates() -> dict:
    """Funding rate tahunan dari 4 venue. Bentuk: {coin: {venue: rate_ann}}.

    Venue yang gagal dilewati diam-diam — sebagian data tetap berguna, dan
    jumlah venue yang berhasil dilaporkan lewat scan_multivenue_funding().
    """
    rates: dict[str, dict[str, float]] = {}
    for venue, fetcher in (("Hyperliquid", _mv_fetch_hyperliquid),
                           ("Binance", _mv_fetch_binance),
                           ("Bybit", _mv_fetch_bybit),
                           ("OKX", _mv_fetch_okx),
                           ("dYdX", _mv_fetch_dydx)):
        for coin, rate in fetcher().items():
            rates.setdefault(coin, {})[venue] = rate
    return rates


def scan_multivenue_funding(min_spread: float = MV_MIN_SPREAD_ANN) -> list[dict]:
    """Cari spread funding terbesar lintas 4 venue, urut dari terbesar.

    Untuk tiap coin: LONG di venue dengan funding TERENDAH (bayar sedikit /
    malah menerima kalau negatif), SHORT di venue dengan funding TERTINGGI
    (menerima funding). Delta gabungan nol — yang dipanen selisih funding.

    Mengembalikan list dict siap pakai untuk logging dan eksekusi nanti.
    """
    rates = fetch_multivenue_rates()
    ops = []
    for coin, venue_rates in rates.items():
        if len(venue_rates) < 2:
            continue
        long_venue = min(venue_rates, key=venue_rates.get)
        short_venue = max(venue_rates, key=venue_rates.get)
        if long_venue == short_venue:
            continue          # semua venue punya rate identik — tidak ada spread
        spread = venue_rates[short_venue] - venue_rates[long_venue]
        if spread < min_spread:
            continue
        ops.append({
            "sym": coin,
            "spread_ann": round(spread, 6),
            "long_venue": long_venue,
            "long_rate_ann": round(venue_rates[long_venue], 6),
            "short_venue": short_venue,
            "short_rate_ann": round(venue_rates[short_venue], 6),
            "n_venues": len(venue_rates),
            # Fee drag = biaya RT dibagi rata sepanjang target hold, bukan
            # dikurangkan sekali. Di hold 30 hari: 12 RT/thn x 0.06% = 0.73%/thn.
            "net_ann": round(spread - (365 / MV_TARGET_HOLD_DAYS) * MAKER_ROUND_TRIP, 6),
        })
    ops.sort(key=lambda o: -o["spread_ann"])
    return ops


def cmd_multivenue(min_spread: float = MV_MIN_SPREAD_ANN):
    """Tampilkan peluang funding lintas venue. READ-ONLY, tanpa API key."""
    print(f"\n{'='*74}")
    print(f"  MULTI-VENUE FUNDING SCAN  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Venue: {', '.join(MV_VENUES)}  |  Ambang: {min_spread*100:.0f}%/thn")
    print(f"{'='*74}\n")

    rates = fetch_multivenue_rates()
    if not rates:
        print("  Tidak ada data funding — semua venue gagal dihubungi.\n")
        return

    venues_seen = sorted({v for vr in rates.values() for v in vr})
    print(f"  Venue merespons : {len(venues_seen)}/{len(MV_VENUES)} ({', '.join(venues_seen)})")
    print(f"  Coin terkumpul  : {len(rates)}\n")

    print(f"  {'Coin':<7}{'LONG di':<24}{'SHORT di':<24}{'Spread':>11}")
    print(f"  {'-'*66}")

    shown = 0
    for coin, vr in sorted(rates.items(),
                           key=lambda kv: -((max(kv[1].values()) - min(kv[1].values()))
                                            if len(kv[1]) > 1 else 0)):
        if len(vr) < 2:
            continue
        lo = min(vr, key=vr.get)
        hi = max(vr, key=vr.get)
        spread = vr[hi] - vr[lo]
        mark = "  <== ambil" if spread >= min_spread else ""
        print(f"  {coin:<7}{lo + f' {vr[lo]*100:+.1f}%':<24}"
              f"{hi + f' {vr[hi]*100:+.1f}%':<24}{spread*100:>9.1f}%{mark}")
        shown += 1

    ops = scan_multivenue_funding(min_spread)
    print(f"\n  Peluang ≥{min_spread*100:.0f}%/thn : {len(ops)} dari {shown} coin")
    if ops:
        top = ops[0]
        print(f"  Terbaik            : {top['sym']} {top['spread_ann']*100:.1f}%/thn "
              f"(net {top['net_ann']*100:.1f}%/thn setelah fee maker)")
    print()


# ── v3.7.0: END Multi-Venue Funding Scanner ───────────────────────────────────

def cmd_health() -> int:
    """Autonomous Monitoring & Evaluation — comprehensive system health.
    Covers: positions, performance, anomalies, infrastructure, risk.
    Returns 0=healthy, 1=warnings, 2=critical.
    Designed for: manual `make hl-health` + daemon periodic check."""
    import json as _json
    from collections import defaultdict as _dd

    state = _load_state()
    address = os.getenv("HL_HARVEST_ADDRESS", "")
    exit_code = 0

    print(f"\n{'='*64}")
    print(f"  🏥 HL HARVEST — M&E HEALTH DASHBOARD")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"{'='*64}")

    # ── 1. POSITIONS ──────────────────────────────────────────────────────
    chain = fetch_hl_positions(address) if address else []
    balance = fetch_hl_balance(address) if address else 0
    hl_legs = state.get("hl_legs", {})
    bn_legs = state.get("binance_legs", {})
    hl_rates = fetch_hl_rates()
    bn_rates = fetch_binance_rates()

    print(f"\n📊 POSITIONS: {len(chain)} on-chain / {len(hl_legs)} state")
    print(f"   Balance: ${balance:.2f}")

    total_upnl = 0.0
    for p in chain:
        sym = p['sym']; upnl = p['unrealized_pnl']; total_upnl += upnl
        hl_r = hl_rates.get(sym, 0); bn_r = bn_rates.get(sym, 0) if bn_rates else 0
        spread = abs(hl_r - bn_r)
        pos = hl_legs.get(sym, {})
        notional = pos.get('notional', 0)
        pnl_pct = (upnl / notional * 100) if notional else 0

        icon = '🟢' if spread > 0.15 else ('🟡' if spread > 0.05 else '🔴')
        dir_ok = '✅' if bn_legs.get(sym) else '❌ NAKED'
        print(f"   {icon} {sym:5s} {p['side']:5s} ${notional:.0f} "
              f"spread={spread*100:5.1f}% UPNL=${upnl:+.2f} ({pnl_pct:+.1f}%) "
              f"hedge={dir_ok} funding=${p.get('cum_funding',0):+.4f}")
    if not chain:
        print(f"   ⚠️  No active positions")

    # ── 2. PERFORMANCE METRICS ─────────────────────────────────────────────
    log_file = DECISION_LOG
    cb = state.get("_circuit_breaker", {})
    if log_file.exists():
        with open(log_file) as f:
            all_lines = [_json.loads(l) for l in f if l.strip()]

        exits = [l for l in all_lines if l.get('action') in ('AUTO_EXIT','MANUAL_CLOSE')]
        entries = [l for l in all_lines if l.get('action') in ('AUTO_ENTRY')
                   or ('opened' in l.get('details','') and 'AUTO' in l.get('action',''))]

        # Win rate (approximate from UPNL trends)
        balances = [l for l in all_lines if l.get('action')=='BALANCE']

        print(f"\n📈 PERFORMANCE:")
        print(f"   Decision log: {len(all_lines)} entries")
        print(f"   Tracked exits: {len(exits)} | Entries: {len(entries)}")
        print(f"   Balance snapshots: {len(balances)}")
        print(f"   Total UPNL (live): ${total_upnl:+.2f}")

        # Balance trend
        if len(balances) >= 2:
            first_bal = float(balances[0].get('balance', 0) or 0)
            last_bal = float(balances[-1].get('balance', 0) or 0)
            chg = last_bal - first_bal
            print(f"   Balance trend: ${first_bal:.2f} → ${last_bal:.2f} ({chg:+.2f})")

        # Circuit breaker status
        if cb.get("active"):
            print(f"   ⚠️  Circuit breaker: ACTIVE — {cb.get('reason','?')}")
            exit_code = max(exit_code, 1)
        else:
            print(f"   Circuit breaker: STANDBY")

    # ── 3. ANOMALY DETECTION ──────────────────────────────────────────────
    print(f"\n🔍 ANOMALY SCAN:")
    anomalies = 0

    # Check 1: Naked positions (HL without BN)
    for sym in hl_legs:
        if sym not in bn_legs:
            print(f"   🔴 NAKED: {sym} has HL leg but no BN hedge!")
            anomalies += 1

    # Check 2: Phantom positions (state without on-chain)
    chain_syms = {p['sym'] for p in chain}
    for sym in hl_legs:
        if sym not in chain_syms:
            print(f"   🔴 PHANTOM: {sym} in state but NOT on-chain!")
            anomalies += 1
    for p in chain:
        if p['sym'] not in hl_legs:
            print(f"   🟡 LEAKED: {p['sym']} on-chain but NOT in state!")
            anomalies += 1

    # Check 3: Stale spread history
    sh = state.get("spread_history", [])
    if sh:
        last_ts = sh[-1].get('ts', '')
        if last_ts:
            try:
                last_dt = datetime.fromisoformat(last_ts.replace('Z', '+00:00'))
                age_min = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
                if age_min > 60:
                    print(f"   🟡 STALE: spread history last updated {age_min:.0f} min ago")
                    anomalies += 1
            except (ValueError, TypeError) as e:
                # A bare except here muted the staleness detector itself — the
                # one check meant to notice a frozen system. Report, don't hide.
                print(f"   🟡 STALE CHECK FAILED: unparseable timestamp {last_ts!r} ({e})")
                anomalies += 1

    # Check 4: Rate velocity (extreme swings)
    prev_rates = state.get("_prev_hl_rates", {})
    for sym, rate in hl_rates.items():
        prev = prev_rates.get(sym)
        if prev is not None and abs(rate - prev) > 0.50:
            print(f"   ⚠️  VELOCITY: {sym} HL rate {prev*100:+.1f}% → {rate*100:+.1f}% (>50pp!)")
            anomalies += 1

    # Check 5: Balance <= 0 or critically low
    if balance <= 0:
        print(f"   🔴 CRITICAL: Balance ${balance:.2f} — cannot trade!")
        anomalies += 1
        exit_code = max(exit_code, 2)
    elif balance < MIN_NOTIONAL:
        print(f"   🟡 LOW CAPITAL: Balance ${balance:.2f} < minimum ${MIN_NOTIONAL:.0f}/position")
        anomalies += 1
        exit_code = max(exit_code, 1)

    # Check 6: data blindness — cycles that ran but captured nothing.
    # This is the check that was missing when a broken interpreter left 71/168
    # snapshots empty for days while every cycle still exited "Finished".
    blind_hist = state.get("spread_history", [])[-24:]
    if blind_hist:
        blind = [s for s in blind_hist if not s.get("hl_rates") and not s.get("spreads")]
        blind_pct = len(blind) / len(blind_hist) * 100
        good = [s for s in blind_hist if s.get("hl_rates") or s.get("spreads")]
        if blind:
            print(f"   {'🔴' if blind_pct >= 50 else '🟡'} BLIND CYCLES: "
                  f"{len(blind)}/{len(blind_hist)} recent snapshots captured no data "
                  f"({blind_pct:.0f}%) — check interpreter deps + API reachability")
            anomalies += 1
            exit_code = max(exit_code, 2 if blind_pct >= 50 else 1)
        if not good:
            print(f"   🔴 CRITICAL: no usable market data in last {len(blind_hist)} cycles")
            exit_code = max(exit_code, 2)

    if anomalies == 0:
        print(f"   ✅ No anomalies detected")
    else:
        print(f"   ⚠️  {anomalies} anomalies found")
        exit_code = max(exit_code, 1)

    # ── 4. INFRASTRUCTURE ─────────────────────────────────────────────────
    print(f"\n⚙️  INFRASTRUCTURE:")
    print(f"   HL API: {'🟢' if hl_rates else '🔴'} | BN API: {'🟢' if bn_rates else '🔴'}")
    print(f"   State file: {STATE_FILE.stat().st_size} bytes")
    print(f"   Decision log: {DECISION_LOG.stat().st_size if DECISION_LOG.exists() else 0} bytes")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from anantara.market_regime import fetch_regime as _fr
        regime = _fr()
        print(f"   Market regime: {regime.regime} (mom={regime.momentum*100:+.1f}% vol_z={regime.vol_z:.2f})")
    except Exception:
        print(f"   Market regime: unavailable")

    # ── 5. RISK ASSESSMENT ────────────────────────────────────────────────
    print(f"\n⚠️  RISK ASSESSMENT:")
    risks = []
    if balance > 0 and total_upnl < -balance * 0.10:
        risks.append(f"🔴 UPNL {total_upnl/balance*100:.0f}% < -10% — CRITICAL")
        exit_code = max(exit_code, 2)
    elif balance <= 0 and total_upnl < 0:
        risks.append(f"🔴 UPNL ${total_upnl:+.2f} with zero balance — CRITICAL")
        exit_code = max(exit_code, 2)
    if len(chain) >= 3:
        risks.append(f"🟡 Portfolio full ({len(chain)}/3) — no entry slots")
    if not bn_rates:
        risks.append(f"🟡 Binance down — cross-venue data incomplete")
    if cb.get("active"):
        risks.append(f"🔴 Circuit breaker active — no new entries")
    if len(chain) == 0:
        risks.append(f"🟡 Zero positions — capital idle")

    if risks:
        for r in risks: print(f"   {r}")
    else:
        print(f"   ✅ No significant risks")

    print(f"\n{'='*64}")
    print(f"  Exit code: {exit_code} ({'✅ HEALTHY' if exit_code==0 else '⚠️  WARNINGS' if exit_code==1 else '🔴 CRITICAL'})")
    print(f"{'='*64}\n")
    return exit_code


# ── Daily summary ─────────────────────────────────────────────────────────────

def cmd_summary():
    """Concise daily dashboard — all positions, PnL, yield, alerts. One glance.
    Gracefully degrades: if any API is slow/unreachable, shows partial data."""
    state    = _load_state()
    hl_legs  = state.get("hl_legs", {})
    bn_legs  = state.get("binance_legs", {})

    # Fetch rates with timeout protection — each call has its own timeout,
    # but we catch here to prevent one slow API from blocking everything.
    try:
        hl_rates = fetch_hl_rates()
    except Exception:
        hl_rates = {}
    try:
        bn_rates = fetch_binance_rates()
    except Exception:
        bn_rates = {}
    address  = os.getenv("HL_HARVEST_ADDRESS", "")
    try:
        balance  = fetch_hl_balance(address) if address else 0.0
    except Exception:
        balance = 0.0
    try:
        meta = fetch_hl_meta()
    except Exception:
        meta = None

    print(f"\n{'='*62}")
    offline_flags = []
    if not hl_rates: offline_flags.append("HL rates")
    if not bn_rates: offline_flags.append("Binance")
    if not balance: offline_flags.append("balance")
    offline_note = f"  ⚠️ OFFLINE: {', '.join(offline_flags)}" if offline_flags else ""
    print(f"  HL HARVEST — DAILY SUMMARY  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  ${balance:.2f} USDC{offline_note}")
    print(f"{'='*62}")

    if not hl_legs:
        print("  No open positions.")
        return

    total_notl = 0.0
    total_est_yield = 0.0
    total_pnl_dollar = 0.0
    alerts = []

    print(f"\n  {'Pair':<6} {'PnL':>8} {'Spread':>8} {'Net/yr':>8} {'Status':>10}")
    print(f"  {'-'*42}")

    for sym, hl_pos in hl_legs.items():
        entry   = float(hl_pos.get("price", 0))
        side    = hl_pos.get("side", "?")
        notl    = float(hl_pos.get("notional", 0))
        hl_r    = hl_rates.get(sym, 0)
        bn_r    = bn_rates.get(sym, 0) if bn_rates else 0
        spread  = abs(hl_r - bn_r)
        net_yr  = notl * max(spread - ROUND_TRIP_COST, 0)

        # Mark price from meta
        mark = entry
        if meta:
            for a, c in zip(meta[0], meta[1]):
                if a["name"] == sym:
                    mark = float(c.get("markPx", entry) or entry)
                    break

        if side == "short":
            pnl_pct = (entry - mark) / entry * 100 if entry > 0 else 0
        else:
            pnl_pct = (mark - entry) / entry * 100 if entry > 0 else 0

        total_notl += notl
        total_est_yield += net_yr
        total_pnl_dollar += pnl_pct / 100 * notl

        # Trend: compare spread with last history snapshot
        trend = ""
        history = state.get("spread_history", [])
        if len(history) >= 2:
            prev = history[-2].get("spreads", {}).get(sym)
            curr = history[-1].get("spreads", {}).get(sym) if history else None
            if prev and curr:
                trend = "↑" if curr > prev * 1.05 else ("↓" if curr < prev * 0.95 else "→")

        icon = "🟢" if pnl_pct > 0 else ("🟡" if pnl_pct > -3 else "🔴")
        hedge_ok = sym in bn_legs and not bn_legs[sym].get("note")

        if spread < MIN_SPREAD_ANN:
            alerts.append(f"{sym}: spread {spread*100:.1f}% < {MIN_SPREAD_ANN*100:.0f}% threshold")
        if not hedge_ok:
            alerts.append(f"{sym}: UNHEDGED!")
        if pnl_pct < -5:
            alerts.append(f"{sym}: PnL {pnl_pct:+.1f}% < -5%")

        print(f"  {sym:<6} {icon}{pnl_pct:>+6.2f}%  {spread*100:>7.1f}%{trend:>2} "
              f"${net_yr:>6.2f}  {'✅ hedged' if hedge_ok else '⚠️ NAKED':>10}")

    # ── Market Health Index ──────────────────────────────────────────────
    n_above = sum(1 for s in [abs(hl_rates.get(sym,0) - bn_rates.get(sym,0))
                               for sym in hl_legs] if s > MIN_SPREAD_ANN)
    health_pct = n_above / len(hl_legs) * 100 if hl_legs else 0
    health_label = ("🟢 HEALTHY" if health_pct >= 60 else
                    "🟡 MODERATE" if health_pct >= 30 else "🔴 WEAK")

    # ── Paper PnL: estimated funding accrued since open ──────────────────
    if hl_legs and hl_rates:
        now_ts = datetime.now(timezone.utc)
        total_funding_pnl = 0.0
        for sym, pos in hl_legs.items():
            opened_str = pos.get("opened_at", "")
            if opened_str:
                try:
                    opened = datetime.fromisoformat(opened_str.replace("Z", "+00:00"))
                    hours = max(0, (now_ts - opened).total_seconds() / 3600)
                except Exception:
                    hours = 0
            else:
                hours = 0
            notl = float(pos.get("notional", 0))
            side = pos.get("side", "?")
            hl_r = hl_rates.get(sym, 0)
            bn_r = bn_rates.get(sym, 0) if bn_rates else 0
            hl_hourly = hl_r / (24 * 365)
            bn_hourly = bn_r / (24 * 365)
            if side == "long":
                funding = (-hl_hourly - bn_hourly) * notl * hours
            else:
                funding = (hl_hourly + bn_hourly) * notl * hours
            total_funding_pnl += funding

        print(f"  Paper funding PnL (est): ${total_funding_pnl:+.4f}  |  "
              f"Net PnL: ${total_pnl_dollar + total_funding_pnl:+.2f}")

    print(f"\n  {'─'*42}")
    print(f"  Market Health: {health_label} ({n_above}/{len(hl_legs)} pairs >{MIN_SPREAD_ANN*100:.0f}%)")
    print(f"  Total notional: ${total_notl:.0f}  |  Total PnL: ${total_pnl_dollar:+.2f}")
    print(f"  Est. yield: ${total_est_yield:.2f}/yr  |  Monthly: ${total_est_yield/12:.2f}")

    if alerts:
        print(f"\n  ⚠️  ALERTS:")
        for a in alerts:
            print(f"     {a}")
    else:
        print(f"\n  ✅ No alerts — all systems nominal.")

    # R1: Basis trade positions section
    basis_hl   = state.get(BASIS_STATE_KEY_HL, {})
    basis_spot = state.get(BASIS_STATE_KEY_SPOT, {})
    if basis_hl:
        print(f"\n  {'─'*42}")
        print(f"  BASIS POSITIONS (Long Spot + Short Perp):")
        print(f"  {'Pair':<6} {'HL Rate':>9} {'Spot':>7} {'Net/yr':>9} {'Hold':>10}")
        total_basis_notl = 0.0
        total_basis_yield = 0.0
        now_ts = datetime.now(timezone.utc)
        for sym, pos in basis_hl.items():
            entry_rate  = pos.get("hl_rate_ann", 0)
            current_r   = hl_rates.get(sym, 0)
            notl        = float(pos.get("notional", 0))
            spot_ok     = sym in basis_spot and not basis_spot[sym].get("note")
            net_yr      = notl * max(abs(current_r) - BASIS_ROUND_TRIP, 0)
            opened_str  = pos.get("opened_at", "")
            hold_hours  = 0.0
            if opened_str:
                try:
                    opened   = datetime.fromisoformat(opened_str.replace("Z", "+00:00"))
                    hold_hours = max(0, (now_ts - opened).total_seconds() / 3600)
                except Exception:
                    pass
            funding_earned = notl * abs(current_r) / (24 * 365) * hold_hours
            spot_tag = "✅spot" if spot_ok else "⚠️NAKED"
            rate_icon = "🟢" if abs(current_r) >= BASIS_MIN_RATE_ANN else ("🟡" if abs(current_r) >= BASIS_MIN_EXIT_ANN else "🔴")
            print(f"  {sym:<6} {rate_icon}{current_r*100:>+7.2f}% {spot_tag:>8} "
                  f"${net_yr:>6.2f}/yr  {hold_hours:>6.0f}h  earned ~${funding_earned:+.3f}")
            total_basis_notl  += notl
            total_basis_yield += net_yr
        print(f"  Basis total: ${total_basis_notl:.0f} notional  |  "
              f"Est yield ${total_basis_yield:.2f}/yr  |  ${total_basis_yield/12:.3f}/mo")

    # Live basis opportunities (always show even with no positions)
    basis_opps = find_basis_opportunities()
    if basis_opps:
        print(f"\n  Basis opportunities now: {len(basis_opps)} assets ≥{BASIS_MIN_RATE_ANN*100:.0f}%/yr")
        for o in basis_opps[:3]:
            print(f"    {o['sym']:<6}  {o['hl_rate_ann']*100:>+7.2f}%/yr  "
                  f"net {o['net_ann']*100:>+6.2f}%/yr  b/e {o['breakeven_days']:.0f}d")
        print(f"  → Run: make hl-basis-run")
    else:
        print(f"\n  No basis entries now (HL rate < {BASIS_MIN_RATE_ANN*100:.0f}%/yr on all assets)")

    print(f"{'='*62}\n")


# ── Hedge completeness check ──────────────────────────────────────────────────

def cmd_hedge_status() -> int:
    """Audit open HL legs against Binance legs — detect unhedged delta exposure.

    Returns exit code: 0 = fully hedged, 1 = incomplete (action required).
    Outputs a clear report with specific actions for each incomplete position.
    """
    state     = _load_state()
    hl_legs   = state.get("hl_legs", {})
    bn_legs   = state.get("binance_legs", {})
    hl_rates  = fetch_hl_rates()
    bn_rates  = fetch_binance_rates()

    print(f"\n{'='*62}")
    print(f"  ANANTARA — HL ARB HEDGE STATUS AUDIT")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*62}")

    if not hl_legs:
        print("  ✅ Tidak ada open HL legs — tidak ada risiko unhedged.")
        return 0

    issues   = []
    warnings = []

    for sym, hl_pos in hl_legs.items():
        hl_side    = hl_pos.get("side", "?")
        entry      = float(hl_pos.get("price", 0))   # key set by _place_order()
        notional   = float(hl_pos.get("notional", 0))
        hl_ann     = (hl_rates.get(sym) or 0) * 100
        bn_ann     = (bn_rates.get(sym) or 0) * 100 if bn_rates else 0
        spread_ann = abs(hl_ann - bn_ann)

        # Check if Binance leg exists in state
        bn_leg    = bn_legs.get(sym, {})
        bn_opened = not bool(bn_leg.get("note"))   # "note" means not yet opened

        # Current price
        meta = _hl_post({"type": "metaAndAssetCtxs"})
        mark = 0.0
        if meta and len(meta) >= 2:
            for a, c in zip(meta[0]["universe"], meta[1]):
                if a["name"] == sym:
                    mark = float(c.get("markPx", 0) or 0)
                    break

        if hl_side == "short":
            pnl_pct = (entry - mark) / entry * 100 if entry > 0 else 0
        else:
            pnl_pct = (mark - entry) / entry * 100 if entry > 0 else 0

        # Determine if this is a problem
        status_icon = "✅" if bn_opened else "⚠️"
        hedge_txt   = "hedged" if bn_opened else "⚠️ UNHEDGED"

        print(f"\n  {status_icon} {sym}")
        print(f"     HL leg   : {hl_side.upper()} {notional:.1f} USDC @ ${entry:.4f}")
        print(f"     Mark px  : ${mark:.4f}  (PnL: {pnl_pct:+.2f}%)")
        print(f"     HL fund  : {hl_ann:+.1f}%/yr  |  BN fund: {bn_ann:+.1f}%/yr  |  spread: {spread_ann:.1f}%/yr")
        print(f"     Binance  : {hedge_txt}")

        if not bn_opened:
            # Determine recommended action
            bn_side = "long" if hl_side == "short" else "short"
            if spread_ann >= 5.0:
                action = (f"BUKA Binance {bn_side.upper()} {sym} ${notional:.0f} notional "
                          f"→ lock {spread_ann:.1f}%/yr delta-neutral")
                issues.append((sym, action))
            else:
                action = (f"Spread {spread_ann:.1f}%/yr < 5%/yr threshold. "
                          f"Pertimbangkan TUTUP HL leg (stop directional exposure).")
                warnings.append((sym, action))
            print(f"     ACTION   : {action}")

    print(f"\n{'='*62}")
    has_issues = bool(issues) or bool(warnings)

    if not has_issues:
        print(f"  ✅ SEMUA POSISI DELTA-NEUTRAL — tidak ada tindakan diperlukan.")
    else:
        if issues:
            print(f"  ❌ {len(issues)} POSISI UNHEDGED (perlu dibuka Binance leg):")
            for sym, action in issues:
                print(f"     • {sym}: {action}")
        if warnings:
            print(f"  ⚠️  {len(warnings)} POSISI UNHEDGED dengan spread kecil:")
            for sym, action in warnings:
                print(f"     • {sym}: {action}")
        print(f"\n  Untuk membuka Binance hedge leg:")
        print(f"    FUNDING_LIVE=1 python3 anantara/hl_harvest.py run --live")
        print(f"  Untuk menutup HL leg (jika tidak worth hedging):")
        print(f"    FUNDING_LIVE=1 python3 anantara/hl_harvest.py close --live")

    print(f"{'='*62}\n")
    return 1 if has_issues else 0


# ── Two-venue reconciliation ──────────────────────────────────────────────────

def cmd_reconcile() -> int:
    """FASE 1.5: Compare state file vs actual positions on BOTH venues.
    Detects naked legs, phantom positions, and state mismatches.
    Returns: 0=all matched, 1=asymmetry detected, 2=critical mismatch.

    This is the single most important safety component — it would have
    caught F-1 (7 naked Binance legs) within 1 hour instead of 6 days."""
    state     = _load_state()
    hl_legs   = state.get("hl_legs", {})
    bn_legs   = state.get("binance_legs", {})
    address   = os.getenv("HL_HARVEST_ADDRESS", os.getenv("HL_ADDRESS", ""))
    issues    = []

    print(f"\n{'='*62}")
    print(f"  TWO-VENUE RECONCILIATION  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*62}")

    # 1. HL side: compare state vs actual fills
    if hl_legs:
        hl_positions_raw = fetch_hl_positions(address) if address else []
        hl_actual = {p["sym"]: p for p in hl_positions_raw}

        print(f"\n  HYPERLIQUID:")
        for sym, pos in hl_legs.items():
            side = pos.get("side", "?")
            size = float(pos.get("size", 0))
            actual = hl_actual.get(sym)

            if actual:
                actual_size = actual["size"]
                size_diff = abs(size - actual_size)
                if size_diff < max(size * 0.01, 0.001):  # 1% tolerance
                    print(f"    ✅ {sym}: state={size:.4f} on-chain={actual_size:.4f} MATCH")
                else:
                    issues.append(f"HL {sym}: size mismatch state={size:.4f} vs on-chain={actual_size:.4f}")
                    print(f"    ⚠️  {sym}: state={size:.4f} on-chain={actual_size:.4f} MISMATCH")
            else:
                # State says we have position but HL doesn't → PHANTOM
                issues.append(f"HL {sym}: PHANTOM — in state but NOT on-chain!")
                print(f"    🔴 {sym}: PHANTOM! State says {side} {size:.4f} but NOT on-chain")

        # Reverse: HL has positions not in state → LEAKED
        for sym in hl_actual:
            if sym not in hl_legs:
                issues.append(f"HL {sym}: LEAKED — on-chain but NOT in state!")
                print(f"    🔴 {sym}: LEAKED! On-chain but not in state file")
    else:
        print(f"\n  HYPERLIQUID: No state entries")

    # 2. Binance side: verify via order IDs
    if bn_legs:
        print(f"\n  BINANCE:")
        for sym, leg in bn_legs.items():
            if leg.get("note"):
                continue  # planned but not opened
            oid = leg.get("order_id")
            side = leg.get("side", "?")
            notl = leg.get("notional", 0)

            if oid:
                # Verify order exists on Binance
                bn_sym = (BINANCE_SYMBOL_MAP.get(sym, sym) + "USDT")
                try:
                    import hmac as _hm, hashlib as _hs, urllib.request as _r, urllib.parse as _up
                    api_key = os.getenv("BINANCE_API_KEY", "")
                    secret  = os.getenv("BINANCE_API_SECRET", "")
                    if api_key and secret:
                        ts = int(time.time() * 1000)
                        params = {"symbol": bn_sym, "orderId": oid, "timestamp": ts, "recvWindow": 5000}
                        qs = _up.urlencode(params)
                        sig = _hm.new(secret.encode(), qs.encode(), _hs.sha256).hexdigest()
                        rq = _r.Request(f"https://fapi.binance.com/fapi/v1/order?{qs}&signature={sig}",
                                       headers={"X-MBX-APIKEY": api_key})
                        with _r.urlopen(rq, timeout=8) as r:
                            o = json.load(r)
                        o_status = o.get("status", "?")
                        o_exec = o.get("executedQty", "0")
                        if o_status == "FILLED":
                            print(f"    ✅ {sym}: order={oid} FILLED qty={o_exec}")
                        else:
                            issues.append(f"BN {sym}: order status={o_status}")
                            print(f"    ⚠️  {sym}: order={oid} status={o_status}")
                except Exception as e:
                    issues.append(f"BN {sym}: cannot verify order {oid} — {str(e)[:60]}")
                    print(f"    ⚠️  {sym}: cannot verify order={oid}")
            else:
                issues.append(f"BN {sym}: no order_id in state")
                print(f"    ⚠️  {sym}: no order_id — DRY-RUN entry?")

        # Critical: state has BN legs without matching HL legs?
        for sym in bn_legs:
            if sym not in hl_legs and not bn_legs[sym].get("note"):
                issues.append(f"CRITICAL: {sym} BN leg without HL leg — NAKED EXPOSURE!")
                print(f"    🔴 {sym}: BN leg WITHOUT matching HL leg!")
    else:
        print(f"\n  BINANCE: No state entries")

    # 3. Verdict
    print(f"\n  {'─'*42}")
    if not hl_legs and not bn_legs:
        print(f"  ✅ No positions to reconcile — system is idle.")
        exit_code = 0
    elif not issues:
        print(f"  ✅ ALL MATCHED — state = reality on both venues.")
        exit_code = 0
    else:
        print(f"  🔴 {len(issues)} ASYMMETRIES DETECTED:")
        for i in issues:
            print(f"     • {i}")
        exit_code = 2 if any("CRITICAL" in i or "NAKED" in i or "PHANTOM" in i for i in issues) else 1

    # Log result
    _log_decision("RECONCILE", f"{len(issues)} issues, exit={exit_code}",
                  n_issues=len(issues), exit_code=exit_code)
    print(f"{'='*62}\n")
    return exit_code


# ── Readiness check ──────────────────────────────────────────────────────────

def cmd_readiness() -> int:
    """Pre-flight: cek semua prasyarat sebelum `make hl-run` dijalankan.
    Periksa credentials, key format, FUNDING_LIVE flag, dan peluang aktif.
    Returns 0 jika fully ready, 1 jika ada yang belum terpenuhi.
    """
    import re as _re

    def _key_valid(k: str) -> bool:
        if not k:
            return False
        return bool(_re.fullmatch(r"[0-9a-f]{64}", k.lower().replace("0x", "")))

    hl_addr   = os.getenv("HL_HARVEST_ADDRESS", "").strip()
    hl_secret = os.getenv("HL_HARVEST_API_SECRET", "").strip()
    live_flag = os.getenv("FUNDING_LIVE", "").strip()

    print(f"\n{'='*62}")
    print(f"  HL × BINANCE HARVEST — READINESS CHECK")
    print(f"  {time.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*62}\n")

    # 1. HL_ADDRESS
    if hl_addr:
        print(f"  ✅  HL_ADDRESS     : {hl_addr[:10]}...{hl_addr[-4:]}")
    else:
        print(f"  ❌  HL_ADDRESS     : not set")
        print(f"       → Isi di .env: HL_HARVEST_ADDRESS=0x...")

    # 2. HL_API_SECRET
    if _key_valid(hl_secret):
        masked = hl_secret[:4] + "****" + hl_secret[-4:]
        print(f"  ✅  HL_API_SECRET  : {masked}  (format valid, 64-char hex)")
    elif hl_secret:
        print(f"  ❌  HL_API_SECRET  : set tapi FORMAT TIDAK VALID (harus 64-char hex)")
    else:
        print(f"  ❌  HL_API_SECRET  : not set")
        print(f"       → Buat agent wallet: app.hyperliquid.xyz → API → Add Agent Wallet")
        print(f"       → Isi di .env: HL_HARVEST_API_SECRET=<64-char-hex-private-key>")
        print(f"       ⚠️  JANGAN pakai main wallet — gunakan agent wallet!")

    # 3. FUNDING_LIVE gate
    if live_flag == "1":
        print(f"  ✅  FUNDING_LIVE   : 1  (live orders AKTIF)")
    else:
        print(f"  ⚠️   FUNDING_LIVE   : not set — `make hl-run` akan DRY-RUN saja")
        print(f"       → Tambahkan FUNDING_LIVE=1 ke .env saat siap live")

    # 4. Peluang aktif
    print(f"\n  Mengambil live rates ...\n")
    raw_ops = find_opportunities()
    ops = [o for o in raw_ops if _is_cross_venue_entry(o)]
    if ops:
        print(f"  ✅  Peluang        : {len(ops)} aset ≥ {MIN_SPREAD_ANN*100:.0f}%/yr")
        for o in ops[:4]:
            dir_lbl = ("SHORT BN / LONG HL" if o["direction"] == "SHORT_BN_LONG_HL"
                       else "LONG BN / SHORT HL")
            print(f"       {o['sym']:<6}  {dir_lbl:<22}  "
                  f"spread {o['spread_ann']*100:+.2f}%/yr  net {o['net_ann']*100:+.2f}%/yr")
    else:
        ops_all = [o for o in find_opportunities(0.0) if _is_cross_venue_entry(o)]
        hl_only = [o for o in raw_ops if o.get("source") == "hl_only"]
        print(f"  ⚠️   Peluang        : 0 aset cross-venue di atas {MIN_SPREAD_ANN*100:.0f}%/yr saat ini")
        if hl_only:
            print("       HL-only signals terdeteksi tetapi RESEARCH ONLY, bukan live-ready.")
        if ops_all:
            best = ops_all[0]
            print(f"       Terbaik sekarang: {best['sym']} {best['spread_ann']*100:.2f}%/yr "
                  f"(threshold {MIN_SPREAD_ANN*100:.0f}%/yr)")

    # 5. Balance (jika address tersedia)
    balance_ok = False
    if hl_addr:
        try:
            balance = fetch_hl_balance(hl_addr)
            print(f"\n  \U0001f4b0 HL Balance     : ${balance:.2f} USDC")
            if balance >= MIN_NOTIONAL:
                print(f"  ✅  Capital cukup  : ${balance:.2f} ≥ minimum ${MIN_NOTIONAL:.0f}/posisi")
                balance_ok = True
            else:
                print(f"  ❌  Capital kurang : ${balance:.2f} < minimum ${MIN_NOTIONAL:.0f}/posisi")
        except Exception as e:
            print(f"\n  ⚠️  Balance fetch error: {e}")

    # Verdict & next action
    creds_ok = bool(hl_addr) and _key_valid(hl_secret)
    print(f"\n{'-'*62}")
    if creds_ok and not balance_ok:
        print(f"  ❌  BELUM SIAP — capital HL kurang atau balance tidak terverifikasi.")
        print(f"       Tetap RESEARCH ONLY sampai balance ≥ ${MIN_NOTIONAL:.0f} dan health green.")
    elif creds_ok and live_flag == "1" and ops:
        print(f"  ✅  SIAP LIVE — jalankan sekarang:")
        print(f"       make hl-run")
    elif creds_ok and live_flag != "1" and ops:
        print(f"  ⚠️   Credentials OK + peluang tersedia — SATU LANGKAH LAGI:")
        print(f"       1. Tambahkan FUNDING_LIVE=1 ke .env")
        print(f"       2. Jalankan: make hl-run")
    elif creds_ok and not ops:
        print(f"  ⚠️   Credentials OK — tunggu spread ≥ {MIN_SPREAD_ANN*100:.0f}%/yr")
        print(f"       Monitor: make hl-rates  (spread berubah setiap jam)")
    else:
        missing = []
        if not hl_addr:
            missing.append("HL_ADDRESS")
        if not _key_valid(hl_secret):
            missing.append("HL_API_SECRET (valid 64-char hex)")
        print(f"  ❌  BELUM SIAP — missing: {', '.join(missing)}")
        print(f"       Langkah:")
        print(f"       1. Buat agent wallet di app.hyperliquid.xyz → API → Add Agent Wallet")
        print(f"       2. Isi .env: HL_HARVEST_ADDRESS=0x...  dan  HL_API_SECRET=64hex...")
        print(f"       3. Set FUNDING_LIVE=1 di .env")
        print(f"       4. make hl-run")
    print()
    return 0 if (creds_ok and balance_ok and ops and live_flag == "1") else 1


# ── Historical backfill (accelerate paper validation) ─────────────────────────

def cmd_backfill(days: int = 7):
    """Radical acceleration: download historical funding rates from HL + Binance
    and backfill spread_history with cross-venue spreads.

    One run = weeks of paper validation data in ~30 seconds.
    After backfill, cmd_summary and decision gates have immediate historical context."""
    import httpx as _httpx

    now_ms = int(time.time() * 1000)
    start_ms = now_ms - days * 86400000

    print(f"\n{'='*62}")
    print(f"  HISTORICAL BACKFILL — {days} days → spread history")
    print(f"  From: {time.strftime('%Y-%m-%d', time.gmtime(start_ms/1000))}")
    print(f"  To:   {time.strftime('%Y-%m-%d', time.gmtime(now_ms/1000))}")
    print(f"{'='*62}")

    # 1. Download HL historical funding for all UNIVERSE coins
    print(f"\n  Downloading HL historical funding...")
    hl_history: dict[str, dict[int, float]] = {}  # coin → {timestamp_ms: rate}

    for coin in UNIVERSE:
        try:
            r = _httpx.post(f"{HL_API}/info", json={
                "type": "fundingHistory", "coin": coin,
                "startTime": start_ms, "endTime": now_ms
            }, timeout=15)
            data = r.json()
            if isinstance(data, list):
                hl_history[coin] = {}
                for entry in data:
                    ts = entry["time"]
                    rate = float(entry["fundingRate"]) * 24 * 365  # annualize
                    hl_history[coin][ts] = rate
        except Exception:
            pass
        if (UNIVERSE.index(coin) + 1) % 5 == 0:
            print(f"    ... {UNIVERSE.index(coin)+1}/{len(UNIVERSE)} coins")

    n_hl = sum(len(v) for v in hl_history.values())
    print(f"    ✅ {n_hl} HL funding entries across {len(hl_history)} coins")

    # 2. Download Binance historical funding
    print(f"\n  Downloading Binance historical funding...")
    bn_history: dict[str, dict[int, float]] = {}

    for coin in UNIVERSE:
        bn_sym = BINANCE_SYMBOL_MAP.get(coin, coin) + "USDT"
        try:
            r = _httpx.get(f"{BINANCE_FAPI}/fundingRate", params={
                "symbol": bn_sym, "startTime": start_ms,
                "endTime": now_ms, "limit": 1000
            }, timeout=15)
            data = r.json()
            if isinstance(data, list):
                bn_history[coin] = {}
                for entry in data:
                    ts = entry["fundingTime"]
                    rate = float(entry["fundingRate"]) * 3 * 365  # annualize
                    bn_history[coin][ts] = rate
        except Exception:
            pass

    n_bn = sum(len(v) for v in bn_history.values())
    print(f"    ✅ {n_bn} Binance funding entries across {len(bn_history)} coins")

    # 3. Merge into hourly snapshots
    # R4: Store BOTH cross-venue spreads AND absolute HL rates for basis analytics
    print(f"\n  Merging cross-venue spreads + absolute HL rates...")

    all_timestamps = set()
    for coin_data in hl_history.values():
        all_timestamps.update(coin_data.keys())

    snaps_by_hour: dict[int, dict] = {}

    for ts_ms in sorted(all_timestamps):
        hour_bucket = (ts_ms // 3600000) * 3600000
        if hour_bucket not in snaps_by_hour:
            snaps_by_hour[hour_bucket] = {"spreads": {}, "hl_rates": {}}

        for coin in UNIVERSE:
            hl_r = hl_history.get(coin, {}).get(ts_ms)
            if hl_r is None:
                continue

            # Store absolute HL rate (R4: for basis analytics and trend forecasting)
            snaps_by_hour[hour_bucket]["hl_rates"][coin] = round(hl_r, 6)

            # Find nearest Binance rate (±4 hours) for cross-venue spread
            bn_r = None
            bn_times = sorted(bn_history.get(coin, {}).keys())
            for bt in bn_times:
                if abs(bt - ts_ms) < 4 * 3600000:
                    bn_r = bn_history[coin][bt]
                    break

            if bn_r is not None:
                spread = abs(hl_r - bn_r)
                snaps_by_hour[hour_bucket]["spreads"][coin] = round(spread, 6)

    # 4. Save to state file
    state = _load_state()
    history = state.get("spread_history", [])

    for hour_ts in sorted(snaps_by_hour.keys()):
        bucket = snaps_by_hour[hour_ts]
        if len(bucket.get("hl_rates", {})) >= 3:  # only save snapshots with data
            snap = {
                "ts":       time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(hour_ts / 1000)),
                "spreads":  bucket["spreads"],
                "hl_rates": bucket["hl_rates"],  # NEW: absolute HL rates for basis
            }
            if not history or history[-1].get("ts") != snap["ts"]:
                history.append(snap)

    if len(history) > 168:
        history = history[-168:]

    state["spread_history"] = history
    _save_state(state)

    # 5. Summary stats from backfill
    n_positive = 0
    n_total    = 0
    rate_sum   = 0.0
    for snap in history:
        for sym, r in snap.get("hl_rates", {}).items():
            n_total += 1
            rate_sum += abs(r)
            if r > 0:
                n_positive += 1
    positive_pct = n_positive / n_total * 100 if n_total > 0 else 0
    avg_abs_rate = rate_sum / n_total if n_total > 0 else 0

    print(f"    ✅ {len(history)} spread history snapshots saved")
    print(f"    HL funding positive: {positive_pct:.1f}% of observations (structural bias)")
    print(f"    Avg absolute HL rate: {avg_abs_rate*100:.2f}%/yr across all assets")
    print(f"\n  {'─'*42}")
    print(f"  Backfill complete: {len(history)} snapshots across {days} days")
    print(f"  Basis analytics now available: make hl-funding-stats")
    print(f"  Next: make hl-summary  →  now has {days}d historical context")
    print(f"{'='*62}\n")

    _log_decision("BACKFILL", f"{days}d → {len(history)} snapshots, "
                  f"HL+ {positive_pct:.1f}% avg_rate {avg_abs_rate*100:.2f}%/yr",
                  days=days, snapshots=len(history),
                  hl_positive_pct=round(positive_pct, 1),
                  avg_abs_rate_ann=round(avg_abs_rate, 6))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Hyperliquid × Binance cross-venue arb executor")
    parser.add_argument("cmd",
                        choices=["plan", "monitor", "run", "close", "rates", "summary", "auto", "emergency-close", "reconcile", "backfill",
                                 "hedge-status", "readiness", "pnl-guard", "health", "multivenue"],
                        nargs="?", default="plan")
    parser.add_argument("--capital", type=float, default=300.0,
                        help="Capital to deploy in $ (default 300)")
    parser.add_argument("--min-spread", type=float, default=MIN_SPREAD_ANN,
                        help=f"Min spread %%/yr (default {MIN_SPREAD_ANN*100:.0f})")
    parser.add_argument("--live", action="store_true",
                        help="Enable live execution (else dry-run)")
    args = parser.parse_args()

    # Load .env
    env_path = Path.home() / "anantara-sakti" / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k and k not in os.environ:
                os.environ[k] = v.strip()

    dry_run = not args.live

    # ── Dependency preflight ────────────────────────────────────────────────
    # httpx absent means every HL/Binance call returns None and the whole tool
    # reports zeros instead of failing. Refuse to start rather than run blind.
    if httpx is None:
        print(f"[hl_harvest] FATAL: httpx not installed for {sys.executable}. "
              f"Every HL/Binance call would fail silently and log zeros as fact.\n"
              f"  Fix: {sys.executable} -m pip install httpx", file=sys.stderr)
        raise SystemExit(2)

    # Order-placing paths sign EIP-712 lazily inside _sign_action(). Missing
    # signing deps would surface only mid-execution — including during
    # emergency-close, exactly when it must not fail. Check up front.
    if args.cmd in ("run", "close", "emergency-close") and not dry_run:
        missing = [m for m in ("eth_account", "msgpack")
                   if importlib.util.find_spec(m) is None]
        if missing:
            print(f"[hl_harvest] FATAL: signing deps missing for {sys.executable}: "
                  f"{', '.join(missing)}. Live '{args.cmd}' would crash at signing time.\n"
                  f"  Fix: {sys.executable} -m pip install {' '.join(missing)}",
                  file=sys.stderr)
            raise SystemExit(2)

    if args.cmd == "plan":
        cmd_plan(args.capital, args.min_spread)
    elif args.cmd == "monitor":
        cmd_monitor()
    elif args.cmd == "run":
        cmd_run(args.capital, dry_run)
    elif args.cmd == "close":
        cmd_close(dry_run)
    elif args.cmd == "rates":
        cmd_rates()
    elif args.cmd == "hedge-status":
        raise SystemExit(cmd_hedge_status())
    elif args.cmd == "readiness":
        raise SystemExit(cmd_readiness())
    elif args.cmd == "pnl-guard":
        raise SystemExit(cmd_pnl_guard(dry_run=dry_run))
    elif args.cmd == "health":
        raise SystemExit(cmd_health())
    elif args.cmd == "multivenue":
        cmd_multivenue()
    elif args.cmd == "summary":
        cmd_summary()
    elif args.cmd == "auto":
        raise SystemExit(cmd_auto(dry_run=dry_run))
    elif args.cmd == "emergency-close":
        cmd_emergency_close(dry_run=dry_run)
    elif args.cmd == "reconcile":
        raise SystemExit(cmd_reconcile())
    elif args.cmd == "backfill":
        cmd_backfill()


if __name__ == "__main__":
    main()
