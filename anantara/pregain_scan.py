#!/usr/bin/env python3
"""
ANANTARA SAKTI — Pre-Gain/Loser scan pipeline (importable: CLI + daemon).

The single source of truth for the Top Pre-Gain/Loser Scan System. Wires together:
  pregain_signals  (pure scoring, tested)
  market_regime    (BTC risk gate — raise the bar in CHAOS)
  signal_tracker   (logs every actionable call → honest hit-rate later)

Both scripts/pregain_scanner.py (rich terminal) and the daemon's 2-hourly Telegram
job import from here, so the radar speaks ONE honest language everywhere:
  • score = attention score, NOT a probability of profit
  • DUST coins (<$1M/24h) are never emitted as actionable (liquidity discipline)
  • every actionable signal is logged for validation — no claim trusted until measured
"""
from __future__ import annotations

import json
import math
import os
import re as _re
import statistics as _stats
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore  — network calls unavailable; tests mock fetch_hl/fetch_binance

# ── Module-level TTL cache (5 min) — thread-safe, max-size-bounded ──────────
import threading as _threading
_CACHE: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 300  # 5 minutes
_CACHE_MAX = 200  # max entries — prevent unbounded memory growth in daemon
_CACHE_LOCK = _threading.Lock()
_CACHE_INFLIGHT: dict[str, _threading.Event] = {}
# Telemetry — exposed via cache_stats() for observability
_cache_hits   = 0
_cache_misses = 0
_cache_evicts = 0


def _cached_call(key: str, fn):
    """Thread-safe TTL cache with max-size eviction and per-key stampede control.

    Guards against:
      1. Race condition: two threads checking key simultaneously
         (old code: both get cache miss → double fetch). Threads now coalesce
         behind one in-flight fetch for the same key.
      2. Memory leak: unbounded growth in long-running daemon
         (old code: entries never evicted beyond TTL expiry).

    Max 200 entries → ~8KB memory, evicts oldest 20 on overflow.
    """
    global _cache_hits, _cache_misses, _cache_evicts
    while True:
        now = time.monotonic()
        with _CACHE_LOCK:
            if key in _CACHE and now - _CACHE[key][0] < _CACHE_TTL:
                _cache_hits += 1
                return _CACHE[key][1]

            event = _CACHE_INFLIGHT.get(key)
            if event is None:
                event = _threading.Event()
                _CACHE_INFLIGHT[key] = event
                _cache_misses += 1
                owner = True
            else:
                owner = False

        if owner:
            try:
                result = fn()
                with _CACHE_LOCK:
                    # Evict oldest entries if at capacity (LRU-lite: delete 10% oldest)
                    if len(_CACHE) >= _CACHE_MAX:
                        oldest = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:_CACHE_MAX // 10]
                        for k, _ in oldest:
                            del _CACHE[k]
                        _cache_evicts += len(oldest)
                    _CACHE[key] = (time.monotonic(), result)
                return result
            finally:
                with _CACHE_LOCK:
                    _CACHE_INFLIGHT.pop(key, None)
                    event.set()

        # Another thread is fetching this key. Wait, then loop to read cache or
        # become the next owner if the fetch failed before populating the cache.
        event.wait()


def cache_stats() -> dict:
    """Return {hits, misses, evictions, size} for observability dashboards."""
    with _CACHE_LOCK:
        return {"hits": _cache_hits, "misses": _cache_misses,
                "evictions": _cache_evicts, "size": len(_CACHE)}

try:                                              # package context (daemon / CLI)
    from anantara import market_regime, signal_tracker, pregain_signals, sosovalue_macro
    from anantara.signal_tracker import Signal
except ImportError:                               # flat context (container)
    import market_regime, signal_tracker, pregain_signals, sosovalue_macro  # type: ignore
    from signal_tracker import Signal                                         # type: ignore

HL_API  = "https://api.hyperliquid.xyz"
BN_API  = "https://fapi.binance.com/fapi/v1"
TIMEOUT = 12
MIN_VOL = 100_000   # minimum $100K 24h volume to appear on radar at all


def _finite_float(value, default: float | None = None) -> float | None:
    """Convert provider values to finite floats; return default on bad input."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _sanitize_asset_row(row: dict) -> dict | None:
    """Validate and canonicalize one market row before any signal math.

    Public venues occasionally emit partial rows, strings, NaN/Inf, zero marks, or
    stale volume. A single malformed asset must be quarantined before scoring so it
    cannot crash the daemon, poison caches, or become an actionable signal.
    """
    if not isinstance(row, dict):
        return None

    name = str(row.get("name", "")).strip().upper()
    mark = _finite_float(row.get("mark"))
    vol24 = _finite_float(row.get("vol24"))
    chg = _finite_float(row.get("chg"), 0.0)
    ann_fund = _finite_float(row.get("ann_fund"), 0.0)
    oi = _finite_float(row.get("oi"), 0.0)

    if not name or mark is None or vol24 is None or chg is None or ann_fund is None or oi is None:
        return None
    if mark <= 0 or vol24 < MIN_VOL or oi < 0:
        return None
    if abs(ann_fund) > _ANOMALY_MAX_ANN_FUND_PCT:
        return None

    fund = _finite_float(row.get("fund"), ann_fund / (24 * 365 * 100))
    impact_spread_pct = _finite_float(row.get("impact_spread_pct"), 0.0) or 0.0
    premium_pct = _finite_float(row.get("premium_pct"), None)
    oi_vol = _finite_float(row.get("oi_vol"), oi / vol24 if vol24 > 0 else 0.0) or 0.0
    vol_oi = _finite_float(row.get("vol_oi"), vol24 / oi if oi > 0 else 0.0) or 0.0

    clean = dict(row)
    clean.update({
        "name": name,
        "mark": mark,
        "chg": chg,
        "fund": fund or 0.0,
        "ann_fund": ann_fund,
        "oi": oi,
        "vol24": vol24,
        "oi_vol": oi_vol,
        "vol_oi": vol_oi,
        "liq": row.get("liq") or pregain_signals.liq_tier(vol24),
        "impact_spread_pct": max(0.0, impact_spread_pct),
        "premium_pct": premium_pct,
    })
    return clean


def _sanitize_assets(rows: list[dict]) -> list[dict]:
    """Return only finite, tradable market rows; preserve feed order."""
    clean = []
    seen = set()
    for row in rows or []:
        asset = _sanitize_asset_row(row)
        if asset is None:
            continue
        name = asset["name"]
        if name in seen:
            continue
        seen.add(name)
        clean.append(asset)
    return clean

# ── Pattern extraction — digunakan oleh log_actionable + learner ──────────────
_PATTERN_RE = _re.compile(r'([A-Z][A-Z_]+)\(')


def _extract_patterns(sigs: list[str]) -> str:
    """Ekstrak nama pattern kanonik dari sig-label strings untuk learning.

    Contoh: ["💥SHORT_SQUEEZE(-120%/yr)", "🌀COIL(OI/Vol=6.5x)"]
            → "SHORT_SQUEEZE,COIL"

    Disimpan di signal_tracker kolom patterns agar PregainLearner bisa
    menghitung per-pattern win-rate. Sig tanpa '(' (test fixtures dsb) → "".
    """
    names = []
    for sig in sigs:
        m = _PATTERN_RE.search(sig)
        if m:
            names.append(m.group(1))
    return ",".join(names)

SIGNAL_DB = os.environ.get("ANANTARA_SIGNAL_DB",
                           str(Path.home() / ".local/share/anantara/signals.db"))
ACTIONABLE_MIN = 60      # min attention score to log a signal & validate it later
LOG_COOLDOWN_SEC = 3600       # don't re-log same coin+direction within 1h (anti-bias)
_SPOT_LOG_COOLDOWN_SEC = 86400  # K20: max 1 SPOT signal per coin per day (was LOG_COOLDOWN_SEC*3=3h, same TAO issue)

# ── Binance rates persistent cache — cross-venue signals survive VPN outages ──
_BN_CACHE_FILE = Path(os.environ.get("ANANTARA_BN_CACHE",
                      str(Path.home() / ".local/share/anantara/bn_rate_cache.json")))
_BN_CACHE_TTL  = 2 * 3600   # 2h max stale (funding rates flip fast — audit: was 6h)
_bn_cache_active = False     # True when using persistent cache (not live API)
_BN_CACHE_SCHEMA_VERSION = 2  # bump if format changes, forces cache invalidation


def _save_bn_cache(rates: dict) -> None:
    """Persist Binance funding rates so HL_LEAD/BN_LEAD signals survive VPN outages."""
    try:
        _BN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(_BN_CACHE_FILE) + ".tmp"
        Path(tmp).write_text(json.dumps({
            "ts":      time.time(),
            "version": _BN_CACHE_SCHEMA_VERSION,
            "rates":   rates,
        }))
        os.replace(tmp, str(_BN_CACHE_FILE))
    except Exception:
        pass


def _load_bn_cache() -> dict[str, float]:
    """Load cached Binance rates if < 2h stale. Validates schema version."""
    try:
        if _BN_CACHE_FILE.exists():
            raw  = _BN_CACHE_FILE.read_text()
            data = json.loads(raw)
            # Schema version check (invalidates old format)
            if data.get("version") != _BN_CACHE_SCHEMA_VERSION:
                return {}
            age = time.time() - data.get("ts", 0)
            if 0 < age < _BN_CACHE_TTL:
                rates = data.get("rates", {})
                if isinstance(rates, dict) and rates:   # non-empty dict = valid
                    return rates
    except Exception:
        pass
    return {}


# ── Funding Tracker — persists between scans to detect funding acceleration ──
# Research finding (360d HL data): accelerating funding (+20%/yr per 24h) lifts
# SHORT signal win-rate from 69% → 72%. Best combo (f>80 + accel + timing) = 80%.
FUND_TRACKER_PATH = Path(os.environ.get("ANANTARA_FUND_TRACKER",
                         str(Path.home() / ".local/share/anantara/fund_tracker.json")))


def _load_fund_tracker() -> dict:
    try:
        return json.loads(FUND_TRACKER_PATH.read_text()) if FUND_TRACKER_PATH.exists() else {}
    except Exception:
        return {}


_fund_tracker_lock = _threading.Lock()


def _save_fund_tracker(data: dict) -> None:
    """Thread-safe atomic write of fund tracker (prevents race on concurrent scans)."""
    with _fund_tracker_lock:
        try:
            FUND_TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = str(FUND_TRACKER_PATH) + ".tmp"
            Path(tmp).write_text(json.dumps(data))
            os.replace(tmp, str(FUND_TRACKER_PATH))
        except Exception:
            pass


def _compute_fund_accel(stored: dict, coin: str, current_ann: float) -> float:
    """Funding acceleration in %/yr per hour vs last scan.
    Returns 0 if no prior data or too old (>24h) or too fresh (<30min)."""
    prev = stored.get(coin)
    if not prev:
        return 0.0
    elapsed_h = (time.time() - prev["ts"]) / 3600
    if elapsed_h < 0.5 or elapsed_h > 24:
        return 0.0
    return (current_ann - prev["rate"]) / elapsed_h   # %/yr per hour


# ── Funding History Cache — lightweight trend slope over last N funding periods ──
# Separate from FUND_TRACKER (which tracks acceleration between daemon scans).
# This cache stores the last 3-6 raw funding rates to compute a LINEAR TREND:
#   positive slope = funding trending up = SHORT pressure building
#   negative slope = funding trending down = potential LONG setup
# TTL = 8h (one funding settlement period — rates reset every 8h on HL).
FUND_CACHE_FILE = Path(os.environ.get("ANANTARA_FUND_CACHE",
                       str(Path.home() / ".local/share/anantara/fund_history_cache.json")))
FUND_CACHE_TTL  = 8 * 3600   # 8h = one funding period

_fund_cache_lock = _threading.Lock()


def _load_fund_cache() -> dict:
    """Load persisted funding history (coin → {rates: [...], ts: epoch}), ignoring stale entries."""
    try:
        if FUND_CACHE_FILE.exists():
            raw = FUND_CACHE_FILE.read_text()
            return json.loads(raw) if raw.strip() else {}
    except Exception:
        pass
    return {}


def _save_fund_cache(data: dict) -> None:
    """Thread-safe atomic write of funding history cache."""
    with _fund_cache_lock:
        try:
            FUND_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = str(FUND_CACHE_FILE) + ".tmp"
            Path(tmp).write_text(json.dumps(data))
            os.replace(tmp, str(FUND_CACHE_FILE))
        except Exception:
            pass


def _fund_trend_slope(rates) -> float:
    """Linear regression slope of last N funding rates (annualized %/yr units).

    Returns the slope as %/yr per period (positive = funding trending upward).
    Uses simple OLS without scipy — stdlib only.

    Example: rates=[-10, +5, +20, +50] → strong positive slope → SHORT signal
             rates=[+80, +40, +20,  +5] → declining slope → squeeze may be fading

    v8.4: Numeric stability — guards against zero variance in x-values.
    v8.25: Guard against None/non-list input (corrupt cache entry).
    """
    if not rates or not isinstance(rates, (list, tuple)):
        return 0.0
    n = len(rates)
    if n < 2:
        return 0.0
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(rates) / n
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, rates))
    den = sum((x - x_mean) ** 2 for x in xs)
    if den <= 0:
        return 0.0   # all x identical (shouldn't happen with range(n), but defensive)
    return num / den


def _fetch_fund_trend(coin: str, cache: dict) -> float:
    """Get funding trend slope for a coin. Returns slope in %/yr per period.

    The cache maps coin → {rates: [r1, r2, ...], ts: epoch}.
    Called once per scan; the current rate is appended by run_scan() after
    fetching, keeping the history rolling (max 6 periods = 48h).

    Returns 0.0 if no history or cache entry is stale (>FUND_CACHE_TTL).
    A positive return means funding is trending UP (SHORT pressure building).
    """
    entry = cache.get(coin)
    if not entry:
        return 0.0
    age = time.time() - entry.get("ts", 0)
    if age > FUND_CACHE_TTL * 3:    # tolerate up to 3 periods (24h) of staleness
        return 0.0
    rates = entry.get("rates", [])
    return _fund_trend_slope(rates)


# ── OBI Snapshot Reader — injects latest L1 imbalance into asset dicts ──────
# Reads from the most-recent OBI JSONL file (collected by anantara-obi, every 4s).
# We take the LAST snapshot for each coin in the day's file — "current" orderbook.
# Format per row: {"ts":ms, "sym":"BTC-USD", "bv20":float, "av20":float, ...}
# sym on HL is "BTC-USD"; the HL universe uses "BTC" → strip "-USD" suffix.

_OBI_DIR = Path(os.environ.get("ANANTARA_OBI_DIR",
                str(Path(os.environ.get("ANANTARA_DIR",
                    str(Path.home() / "anantara-sakti")))
                    / "freqtrade_user_data" / "data" / "sodex" / "obi")))

# In-memory cache: (file_mtime, {coin: obi_l1_imbalance})
_obi_snapshot_cache: tuple[float, dict] = (0.0, {})


def _load_latest_obi_snapshot() -> dict[str, float]:
    """Return {coin: obi_l1_imbalance} from the most-recent OBI file.

    obi_l1_imbalance = bv20 / (bv20 + av20) — bid fraction at depth-20 (L1).
    Range [0, 1]: >0.6 bid-heavy, <0.4 ask-heavy, 0.4-0.6 neutral.

    Cached by file mtime — only re-parsed when the file changes (every 4s writes).
    Returns {} gracefully if OBI dir missing or files unreadable.
    """
    global _obi_snapshot_cache
    try:
        # Find today's file first; fall back to most-recent available
        import datetime as _dt
        today_name = "obi_" + _dt.date.today().strftime("%Y%m%d") + ".jsonl"
        today_path = _OBI_DIR / today_name
        obi_path   = today_path if today_path.exists() else None
        if obi_path is None:
            # Fall back to most-recently modified file
            files = sorted(_OBI_DIR.glob("obi_*.jsonl"), key=lambda p: p.stat().st_mtime)
            obi_path = files[-1] if files else None
        if obi_path is None:
            return {}

        mtime = obi_path.stat().st_mtime
        if _obi_snapshot_cache[0] == mtime:
            return _obi_snapshot_cache[1]   # file unchanged — return cached result

        # Parse file: keep LAST row per symbol (most recent snapshot)
        latest: dict[str, dict] = {}
        with open(obi_path) as f:
            for line in f:
                try:
                    row = json.loads(line)
                    sym = row.get("sym", "")
                    if sym and row.get("bv20") is not None:
                        latest[sym] = row   # overwrite with each newer row
                except (json.JSONDecodeError, KeyError):
                    pass

        # Compute imbalance: bv20 / (bv20 + av20); coin = sym minus "-USD" suffix
        result: dict[str, float] = {}
        for sym, row in latest.items():
            coin = sym.replace("-USD", "").replace("-USDT", "")
            bv   = float(row.get("bv20", 0) or 0)
            av   = float(row.get("av20", 0) or 0)
            total = bv + av
            if total > 0:
                result[coin] = bv / total

        _obi_snapshot_cache = (mtime, result)
        return result
    except Exception:
        return {}


# ── Data fetchers ───────────────────────────────────────────────────────────
_ANOMALY_PRICE_SPIKE_PCT = 50.0    # >50% move in 24h = likely data glitch, skip
_ANOMALY_MAX_ANN_FUND_PCT = 1000.0 # >1000%/yr funding = corrupted, skip


def _is_anomalous(mark: float, prev: float, oi: float, fund: float) -> bool:
    """Anomaly Detection (v3 ULTIMATE Layer 2 — lightweight, per-asset).

    Detects corrupt/glitch API data sebelum masuk ke engines:
    1. Price spike > 50% in 24h  — exchange glitch or bad prevDayPx
    2. Negative OI               — API parse error
    3. Extreme funding rate      — >1000%/yr = corrupted (normal range ±300%/yr)

    Tidak filter volatilitas tinggi yang valid (BTC crash -30% dst),
    hanya filter data yang CLEARLY tidak mungkin terjadi di market nyata.
    """
    if prev > 0:
        pct_chg = abs((mark - prev) / prev * 100)
        if pct_chg > _ANOMALY_PRICE_SPIKE_PCT:
            return True   # extreme spike — likely stale prevDayPx (exchange downtime)
    if oi < 0:
        return True       # negative OI = parse error
    ann_fund_abs = abs(fund * 24 * 365 * 100)
    if ann_fund_abs > _ANOMALY_MAX_ANN_FUND_PCT:
        return True       # corrupted funding rate
    return False


def _fetch_hl_raw() -> list[dict]:
    """Actual HL API call — call via fetch_hl() for cached version.

    v8.4: Added proper httpx error handling. Previously, if httpx was None
    (import failed) or the API returned non-JSON/corrupt data, the entire
    scan pipeline would crash with unhandled NameError/JSONDecodeError.
    Now all error paths return [] gracefully.
    """
    if httpx is None:
        return []   # httpx not installed — tests/offline mode
    try:
        r = httpx.post(f"{HL_API}/info", json={"type": "metaAndAssetCtxs"}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, httpx.TimeoutException, json.JSONDecodeError, Exception):
        return []
    # Guard: API must return [{"universe": [...]}, asset_contexts] — tolerate
    # provider schema drift/malformed partial responses without killing daemon scans.
    if (not isinstance(data, list) or len(data) < 2
            or not isinstance(data[0], dict)
            or not isinstance(data[0].get("universe"), list)
            or not isinstance(data[1], list)):
        return []
    universe, ctxs = data[0]["universe"], data[1]
    rows = []
    for asset, ctx in zip(universe, ctxs):
        try:
            mark = float(ctx.get("markPx", 0) or 0)
            prev = float(ctx.get("prevDayPx", mark) or mark)
            oi   = float(ctx.get("openInterest", 0) or 0) * mark   # USD OI
            vol  = float(ctx.get("dayNtlVlm", 0) or 0)
            fund = float(ctx.get("funding", 0) or 0)
            if mark <= 0 or vol < MIN_VOL:
                continue
            # Anomaly Detection: skip asset dengan data korup/glitch
            if _is_anomalous(mark, prev, oi, fund):
                continue
            # Impact spread — $5k depth effective spread (proxy for execution cost)
            # impactPxs = [impact_bid_5k, impact_ask_5k]; missing → 0 → spread=0 (safe)
            impact_pxs   = ctx.get("impactPxs") or [0, 0]
            impact_bid   = float(impact_pxs[0] if len(impact_pxs) > 0 else 0) or 0.0
            impact_ask   = float(impact_pxs[1] if len(impact_pxs) > 1 else 0) or 0.0
            impact_spread_pct = ((impact_ask - impact_bid) / mark * 100
                                 if mark > 0 and impact_ask > 0 and impact_bid > 0
                                 else 0.0)
            # premium_pct — basis signal: (mark - oracle) / oracle × 100
            # HL API "premium" field = (mid - oracle) / oracle (raw fraction).
            # We convert to % and store as premium_pct for score_premium().
            oracle    = float(ctx.get("oraclePx", 0) or 0)
            prem_raw  = ctx.get("premium")
            if prem_raw is not None:
                premium_pct = float(prem_raw) * 100   # e.g. -0.000765 → -0.0765%
            elif oracle > 0:
                premium_pct = (mark - oracle) / oracle * 100
            else:
                premium_pct = None
            rows.append({
                "name": asset["name"], "mark": mark,
                "chg": (mark - prev) / prev * 100 if prev > 0 else 0,
                "fund": fund, "ann_fund": fund * 24 * 365 * 100,
                "oi": oi, "vol24": vol,
                "oi_vol": oi / vol if vol > 0 else 0,
                "vol_oi": vol / oi if oi > 0 else 0,
                "liq": pregain_signals.liq_tier(vol),
                "impact_spread_pct": impact_spread_pct,
                "premium_pct": premium_pct,
            })
        except Exception:
            pass
    return rows


def fetch_hl() -> list[dict]:
    """All HL perp contexts (5-min cache — reduces API calls across scan+validate+autotrade)."""
    return _cached_call("hl_assets", _fetch_hl_raw)


def _fetch_binance_raw() -> dict[str, float]:
    """Fetch Binance funding rates. v8.4: explicit httpx None guard."""
    if httpx is None:
        return {}
    global _bn_cache_active
    try:
        r = httpx.get(f"{BN_API}/premiumIndex", timeout=TIMEOUT)
        r.raise_for_status()
        rates = {d["symbol"].replace("USDT", ""): float(d.get("lastFundingRate", 0)) * 3 * 365 * 100
                 for d in r.json() if "USDT" in d.get("symbol", "")}
        if rates:
            _bn_cache_active = False
            _save_bn_cache(rates)   # persist for future outages
        return rates
    except Exception:
        cached = _load_bn_cache()
        if cached:
            _bn_cache_active = True
            return cached           # cross-venue signals survive VPN/network outage
        _bn_cache_active = False
        return {}


def fetch_binance() -> dict[str, float]:
    """{base: annualized_funding_pct} from Binance (5-min in-memory cache).
    Falls back to persistent disk cache (6h TTL) when Binance API unreachable."""
    return _cached_call("bn_rates", _fetch_binance_raw)


# ── Scan ────────────────────────────────────────────────────────────────────
def run_scan(min_score: int, show_long: bool = True, show_short: bool = True,
             log: bool = True, verbose: bool = True):
    """Fetch → regime gate → macro context → score → (optionally) log actionable signals.
    Returns (longs, shorts, regime)."""
    assets = _sanitize_assets(fetch_hl())
    bn     = fetch_binance()
    regime = _cached_call("regime", market_regime.fetch_regime)  # 5-min cache
    floor  = max(min_score, regime.min_score_floor)

    # ── Funding acceleration: compare current vs last scan ────────────────────
    # Empirical: f>80 + accel + Asia/EU session → 80% win-rate (vs 57% baseline)
    stored_fund = _load_fund_tracker()
    for a in assets:
        a["fund_accel"] = _compute_fund_accel(stored_fund, a["name"], a["ann_fund"])
    # Save current funding for next scan (after loop so we don't overwrite mid-loop)
    _save_fund_tracker({a["name"]: {"ts": time.time(), "rate": a["ann_fund"]}
                        for a in assets})

    # ── OI Delta (per-hour) — uses existing OI snapshot from pregain_engines ──
    # Inject oi_delta_hr into each asset BEFORE the scoring loop so score_oi_delta()
    # can read it. Computed here (not inside engines block) because engines block is
    # inside a try/except and we need this field unconditionally.
    # oi_snapshot loaded later in "Load OI history snapshot" block below; we use a
    # local pre-load here just for injection, keeping the engines block unchanged.
    _oi_snap_for_delta: dict = {}
    try:
        from anantara import pregain_engines as _pe_early
        _oi_snap_for_delta = _pe_early.load_oi_snapshot()
    except Exception:
        pass
    _now_ts = time.time()
    for a in assets:
        name = a.get("name", "")
        oi_now = a.get("oi", 0.0)
        prev_entry = _oi_snap_for_delta.get(name, {})
        oi_prev = prev_entry.get("oi", 0.0)
        snap_ts  = prev_entry.get("ts", 0.0)
        elapsed_h = (_now_ts - snap_ts) / 3600 if snap_ts > 0 else 0.0
        if oi_prev > 0 and 0.1 <= elapsed_h <= 12:
            # %/hr: positive = OI growing (more positions opening)
            a["oi_delta_hr"] = (oi_now - oi_prev) / oi_prev * 100 / elapsed_h
        else:
            a["oi_delta_hr"] = None   # first scan or snapshot too stale/fresh

    # ── Funding trend — rolling slope over last 3+ stored funding readings ────
    # Uses fund_history_cache (FUND_CACHE_FILE). Append current rate each scan;
    # keep max 6 periods (48h) so old data doesn't dominate.
    stored_fund_hist = _load_fund_cache()
    for a in assets:
        name = a.get("name", "")
        a["fund_trend"] = _fetch_fund_trend(name, stored_fund_hist)
        # Append current reading to rolling history (max 6 periods kept)
        entry = stored_fund_hist.get(name, {"rates": [], "ts": 0})
        rates_hist = entry.get("rates", [])
        rates_hist.append(a["ann_fund"])
        if len(rates_hist) > 6:
            rates_hist = rates_hist[-6:]   # keep only the last 6 readings
        stored_fund_hist[name] = {"rates": rates_hist, "ts": _now_ts}
    _save_fund_cache(stored_fund_hist)
    # ── Compute cross-sectional log-volume z-score (_vz) ──────────────────────
    # Used by score_atr_compression to detect if THIS coin has unusual volume
    # relative to the rest of the market. Log-scale is more robust for skewed
    # distributions (crypto volume spans 3+ orders of magnitude).
    log_vols = [math.log(a["vol24"]) for a in assets if a["vol24"] > 0]
    if len(log_vols) >= 5:
        lv_mean = _stats.mean(log_vols)
        lv_std  = _stats.pstdev(log_vols)
        # Minimum std = 1% of |mean|. Prevents division-by-near-zero when all coins
        # have nearly identical volume (uniform market) — avoids inflated z-scores
        # that would spuriously fire ATR_COMPRESSION on uniform-volume conditions.
        lv_std  = max(lv_std, abs(lv_mean) * 0.01) if lv_mean != 0 else max(lv_std, 0.01)
        for a in assets:
            a["_vz"] = (math.log(max(a["vol24"], 1)) - lv_mean) / lv_std
    # ──────────────────────────────────────────────────────────────────────────
    # ★ Macro context (SoSoValue ETF + sector + events) — independent 3rd mechanism
    macro = sosovalue_macro.fetch_macro_context()
    if verbose:
        key_set = bool(sosovalue_macro._api_key())
        macro_tag = f"| macro: {macro.reason[:50]}" if key_set else "| macro: (set SOSOVALUE_API_KEY)"
        bn_tag = (f"📦 {len(bn)} Binance rates (cached)" if _bn_cache_active
                  else f"🟢 {len(bn)} Binance rates" if bn else "⚠️ 0 Binance rates (unavailable)")
        print(f"  {len(assets)} HL assets · {bn_tag} · "
              f"regime {regime.regime} (x{regime.multiplier}, floor {floor}) "
              f"{macro_tag}")

    # ★ LEARNER: dapatkan composite regime×session multiplier SEKALI per scan
    # is_trained() = False → _lm = 1.0 (tanpa efek) sampai ≥15 resolved
    _lm = 1.0
    _learner_obj = None
    try:
        from anantara import pregain_learner as _pl
        _learner_obj = _pl.get_learner()
        if _learner_obj.is_trained():
            _current_session = signal_tracker.session_name()
            _lm = _learner_obj.get_composite_mult(regime.regime, _current_session)
    except Exception:
        pass

    # ── Load OI history snapshot for M3 OI velocity (accurate) ─────────────
    # Save current snapshot BEFORE loop so delta is calculated vs PREVIOUS scan
    try:
        from anantara import pregain_engines as _pe
        _oi_snapshot = _pe.load_oi_snapshot()
        _pe.save_oi_snapshot(assets)   # persist for NEXT scan
    except Exception:
        _pe = None
        _oi_snapshot = {}

    # ── Load OBI snapshots (latest per coin from anantara-obi collector) ─────
    # Graceful: {} when OBI dir missing or files unreadable; daemon unaffected.
    _obi_map = _load_latest_obi_snapshot()

    longs, shorts = [], []
    for a in assets:
        # Inject OBI L1 imbalance — None when no snapshot (score_obi_confirmation
        # returns 0 safely on None, so the loop is always backward-compatible)
        a["obi_l1_imbalance"] = _obi_map.get(a["name"])

        ls, lsigs = pregain_signals.score_long(a, bn)
        ss, ssigs = pregain_signals.score_short(a, bn)
        chg = a.get("chg", 0)
        # ★ FUND_ACCEL: funding still rising fast → squeeze pressure building
        # Research: f>80 + accel + timing → 80% win-rate (vs 57% baseline)
        fas, fasig = pregain_signals.score_funding_accel(a)
        if fas > 0:
            ss = min(100, ss + fas); ssigs = (ssigs + fasig)[:4]

        # OBI now integrated inside score_long/score_short (v8.1) via fund-direction gate.

        # ★ VOL_REGIME signal (empirically validated, +0.193R over 365d)
        vrs, vrsig = pregain_signals.score_vol_regime(a, regime.atr_ratio)
        if vrs > 0:
            if chg > 0: ls = min(100, ls + vrs); lsigs = (lsigs + vrsig)[:4]
            else:        ss = min(100, ss + vrs); ssigs = (ssigs + vrsig)[:4]
        # ★ ATR_COMPRESSION→EXPANSION signal (OOS +0.454R, catches transition early)
        acs, acsig = pregain_signals.score_atr_compression(
            a, regime.atr_ratio, regime.atr_ratio_prev)
        if acs > 0:
            if chg > 0: ls = min(100, ls + acs); lsigs = (lsigs + acsig)[:4]
            else:        ss = min(100, ss + acs); ssigs = (ssigs + acsig)[:4]

        # ★ MACRO adjustment (ETF flow + sector bias — truly independent mechanism)
        # NOTE: OI Delta, Premium, and Funding Trend are integrated inside
        # pregain_signals.score_long() and score_short() (v8.1 lines 233-242).
        # They read oi_delta_hr / premium_pct / fund_trend fields injected above.
        ls += macro.long_adj  + sosovalue_macro.coin_sector_adj(a["name"], macro.sector, "LONG")
        ss += macro.short_adj + sosovalue_macro.coin_sector_adj(a["name"], macro.sector, "SHORT")
        # Apply directional multipliers (bear phase penalises longs, bull phase penalises shorts)
        ls = min(100, max(0, int(ls * regime.long_multiplier)))
        ss = min(100, max(0, int(ss * regime.short_multiplier)))
        # ★ LEARNER: per-pattern × regime×session × coin-level multiplier
        if _learner_obj is not None and _learner_obj.is_trained():
            coin_name = a.get("name", "")
            _lp_long  = _learner_obj.get_pattern_composite_mult(_extract_patterns(lsigs))
            _lp_short = _learner_obj.get_pattern_composite_mult(_extract_patterns(ssigs))
            # Coin gate: 0.0 = BLOCKED (structural bull/bear), 1.3 = BOOSTED
            _lc_long  = _learner_obj.get_coin_mult(coin_name, "LONG")
            _lc_short = _learner_obj.get_coin_mult(coin_name, "SHORT")
            ls = min(100, max(0, int(round(ls * _lm * _lp_long  * _lc_long))))
            ss = min(100, max(0, int(round(ss * _lm * _lp_short * _lc_short))))

        # ★ 7-ENGINE BOOST (ULTIMATE v2 — M5 CVD, M6 Liq-Prox, M7 MTF additive)
        # Adds M5/M6/M7 score boost ON TOP of existing empirical pattern scores.
        # Additive approach: preserves empirically-validated pattern signals while
        # adding the 3 missing engines from ULTIMATE v2 (CVD, liq-prox, MTF).
        # Max boost: +15 pts (caps signal quality without replacing base score).
        if _pe is not None:
            try:
                _ann_fund_prev = stored_fund.get(a["name"], {}).get("rate", 0.0)
                _eng_s = _pe.compute_all_engines_rest(
                    a, direction="SHORT", regime=regime.regime,
                    btc_momentum=regime.momentum,
                    ann_fund_prev=_ann_fund_prev,
                    oi_snapshot=_oi_snapshot,   # M3: actual OI delta saat tersedia
                )
                _eng_l = _pe.compute_all_engines_rest(
                    a, direction="LONG", regime=regime.regime,
                    btc_momentum=regime.momentum,
                    ann_fund_prev=_ann_fund_prev,
                    oi_snapshot=_oi_snapshot,   # M3: actual OI delta saat tersedia
                )
                # Boost = engine score / 100 × 15 (max +15 pts per direction)
                # Only adds when engine agrees with direction (positive signal)
                _boost_s = int(_eng_s["score_7engine"] / 100 * 15)
                _boost_l = int(_eng_l["score_7engine"] / 100 * 15)
                ss = min(100, ss + _boost_s)
                ls = min(100, ls + _boost_l)
                # Store engine details in asset dict for transparency
                a["_eng_short"] = _eng_s
                a["_eng_long"]  = _eng_l
            except Exception:
                pass

        if ls >= floor:
            longs.append({**a, "score": ls, "lsigs": lsigs, "grade": pregain_signals.grade(ls)})
        if ss >= floor:
            shorts.append({**a, "score": ss, "ssigs": ssigs, "grade": pregain_signals.grade(ss)})

    longs.sort(key=lambda x: x["score"], reverse=True)
    shorts.sort(key=lambda x: x["score"], reverse=True)

    if log:
        log_actionable(longs, shorts, regime.regime, verbose=verbose)
    return longs, shorts, regime


def log_actionable(longs: list[dict], shorts: list[dict], regime: str,
                   verbose: bool = True) -> int:
    """Persist actionable signals (score≥ACTIONABLE_MIN, NOT dust) for hit-rate
    validation. The honesty engine: every call is graded against reality in 24h."""
    # Impact spread gate: skip execution if effective $5k spread > 0.3% (30bps).
    # 0.3% round-trip = ~6× our 0.05% fee — liquidity too thin, slippage kills edge.
    # Uses impactPxs from HL API ([bid_5k, ask_5k]). 0.0 = data missing → safe pass.
    _MAX_IMPACT_SPREAD_PCT = 0.3

    sigs = []
    for r in longs:
        if r["score"] >= ACTIONABLE_MIN and r["liq"] != "DUST":
            if not r.get("mark") or r["mark"] <= 0:
                continue   # skip signals with no valid entry price — backtest would use 0
            # Skip if impact spread too wide (illiquid = slippage kills edge)
            if r.get("impact_spread_pct", 0) > _MAX_IMPACT_SPREAD_PCT:
                continue
            sigs.append(Signal(r["name"], "LONG", r["score"], r["grade"],
                               r["mark"], regime, r["vol24"], r["liq"],
                               fund_accel=r.get("fund_accel", 0.0),
                               vol_oi=r.get("vol_oi", 0.0),
                               patterns=_extract_patterns(r.get("lsigs", [])),
                               sig_type="LONG_FUNDING",
                               impact_spread_pct=r.get("impact_spread_pct", 0.0)))
    for r in shorts:
        if r["score"] >= ACTIONABLE_MIN and r["liq"] != "DUST":
            if not r.get("mark") or r["mark"] <= 0:
                continue   # skip signals with no valid entry price — backtest would use 0
            # Skip if impact spread too wide
            if r.get("impact_spread_pct", 0) > _MAX_IMPACT_SPREAD_PCT:
                continue
            sigs.append(Signal(r["name"], "SHORT", r["score"], r["grade"],
                               r["mark"], regime, r["vol24"], r["liq"],
                               fund_accel=r.get("fund_accel", 0.0),
                               vol_oi=r.get("vol_oi", 0.0),
                               patterns=_extract_patterns(r.get("ssigs", [])),
                               sig_type="SHORT",
                               impact_spread_pct=r.get("impact_spread_pct", 0.0)))
    if not sigs:
        return 0
    try:
        Path(SIGNAL_DB).parent.mkdir(parents=True, exist_ok=True)
        # 1h cooldown: rapid re-runs won't double-count the same coin+direction
        # (prevents hit-rate bias); periodic daemon scans (2h) still log normally.
        n = signal_tracker.log_signals(SIGNAL_DB, sigs, cooldown_sec=LOG_COOLDOWN_SEC)
        if verbose:
            dup = len(sigs) - n
            extra = f" ({dup} dilewati — cooldown anti-duplikat)" if dup else ""
            print(f"  📝 {n} sinyal actionable dicatat ke validator (dinilai +24 jam){extra}")
        return n
    except Exception as e:
        if verbose:
            print(f"  ⚠️  gagal mencatat sinyal: {e}")
        return 0


def validate() -> str:
    """Backfill outcomes for signals ≥24h old using OHLC triple-barrier simulation.

    K-5 FIX (v12.0): Sebelumnya menggunakan snapshot harga T+24h yang menggelembungkan
    WR ±10pp. Sekarang menggunakan simulate_trade() dengan jalur harga forward penuh
    (high/low/close per candle) — menangkap SL intraday yang terlewat oleh snapshot.

    Setiap sinyal yang resolved disimpan ke ChromaDB AI memory (layer 3).
    """
    try:
        prices = {a["name"]: a["mark"] for a in fetch_hl()}
    except Exception:
        prices = {}

    # K-5 FIX: Gunakan OHLC triple-barrier, bukan snapshot close price.
    # fetch_path() mengembalikan list[dict] candle {high, low, close} forward;
    # simulate_trade() berjalan di atas path tersebut dengan aturan pesimis.
    # Ini menghilangkan ±10pp inflasi WR dari metode snapshot lama.
    try:
        from anantara import pregain_backtest as _pb
    except ImportError:
        import pregain_backtest as _pb   # type: ignore

    def _candle_path(coin: str, signal_ts: int) -> list[dict]:
        """Fetch forward candle path for triple-barrier simulation."""
        try:
            return _pb.fetch_path(coin, signal_ts, hours=25) or []
        except Exception:
            return []

    # SHORT signals: 24h horizon, 3%/20% geometry, funding cost included
    n = _pb.backfill_outcomes_ohlc(
        db_path=SIGNAL_DB,
        fetch_path_fn=_candle_path,
        horizon_sec=24 * 3600,
        sl_pct=3.0, tp_pct=20.0,
        fee_pct=0.09, funding_pct=0.05,
        sig_type_exclude="SPOT_BREAKOUT")

    # SPOT_BREAKOUT: 10d horizon, no funding cost (spot), different geometry
    n_spot = _pb.backfill_outcomes_ohlc(
        db_path=SIGNAL_DB,
        fetch_path_fn=_candle_path,
        horizon_sec=10 * 24 * 3600,
        sl_pct=20.0, tp_pct=20.0,    # trailing stop handles exit; wide SL as safety
        fee_pct=0.09, funding_pct=0.0,
        sig_type_filter="SPOT_BREAKOUT")
    n += n_spot

    # Fallback: signals > 7 days old that still don't have candle data in local cache
    # use the old snapshot method as last resort (stale data, better than NULL forever).
    n_fallback = signal_tracker.backfill_outcomes(
        SIGNAL_DB, lambda c: prices.get(c),
        horizon_sec=7 * 24 * 3600,   # only for signals > 7 days old
        sig_type_exclude="SPOT_BREAKOUT")
    n_spot_fb = signal_tracker.backfill_outcomes(
        SIGNAL_DB, lambda c: prices.get(c),
        horizon_sec=10 * 24 * 3600,
        sig_type_filter="SPOT_BREAKOUT")
    n += n_fallback + n_spot_fb

    # ── Learning loop: refresh weights dari sinyal yang baru resolved ─────────
    # Selalu refresh (bukan hanya jika n > 0) agar in-memory weights terkini
    # setelah restart daemon — learner punya throttle internal (REFRESH_INTERVAL=1h).
    # force=True: bypass throttle karena ini adalah explicit validate call.
    try:
        from anantara import pregain_learner as _pl
        _pl.get_learner().refresh(SIGNAL_DB, force=True)
    except Exception as e:
        import logging as _vlog
        _vlog.getLogger(__name__).warning(f"validate: learner refresh non-critical: {e}")

    # ── AI Layer integration: store resolved signals in ChromaDB ─────────────
    # Builds up pattern memory for future similarity-based veto.
    # Graceful: if ai_agent_framework not installed, skip silently.
    if n > 0:
        _feed_ai_memory(n)

    rep = signal_tracker.hit_rate_report(SIGNAL_DB)
    return f"Resolved {n} sinyal baru.\n\n" + signal_tracker.format_report(rep)


def _feed_ai_memory(n_new: int) -> None:
    """Store recently resolved signals into ChromaDB AI pattern memory.

    Called after backfill_outcomes(). Gracefully skips if ChromaDB unavailable.
    Builds the trade pattern store that enables similarity-based validation.
    """
    try:
        try:
            from anantara.ai_agent_framework import TradePatternMemory
        except ImportError:
            from ai_agent_framework import TradePatternMemory   # type: ignore

        memory = TradePatternMemory()
        if not memory._ready:
            return   # ChromaDB not installed — skip silently

        # Load recently resolved signals
        import sqlite3
        conn = sqlite3.connect(SIGNAL_DB)
        try:
            # Clamp limit: n_new*5 but never >500 (prevent memory DoS)
            limit = min(max(50, n_new * 5), 500)
            rows = conn.execute("""
                    SELECT id, coin, direction, score, grade, ann_fund, vol24,
                           regime, outcome_pct, correct, entry_price
                    FROM signal_log
                    WHERE outcome_pct IS NOT NULL
                    ORDER BY outcome_ts DESC
                    LIMIT ?
                """, (limit,)).fetchall()
        finally:
            conn.close()

        for row in rows:
            sid, coin, direction, score, grade, ann_fund, vol24, regime, outcome_pct, correct, entry_px = row
            if outcome_pct is None:
                continue
            features = {
                "symbol":       coin,
                "direction":    direction,
                "score":        float(score or 0),
                "funding_rate": float(ann_fund or 0) / (24 * 365 * 100),  # normalize
                # log(1000) minimum gives meaningful spread even for low-vol coins
                "vol24_log":    math.log(max(float(vol24 or 1000), 1000)),
                "model_prob":   float(score or 50) / 100.0,  # score as proxy prob
                "hour":         0.0,    # not stored in signal_log
                "atr_pct":      0.0,
                "spread_pct":   0.0,
                "obi5":         0.0,
                "vol_imbalance":0.0,
            }
            outcome = "win" if correct else "loss"
            trade_id = f"pregain_{sid}"
            memory.store(trade_id, features, outcome, float(outcome_pct or 0))

    except Exception:
        pass   # AI memory is non-critical — never block validate()


def regime_summary() -> str:
    """Ringkasan market regime saat ini: kondisi BTC + dampak ke scanner."""
    try:
        reg = _cached_call("regime", market_regime.fetch_regime)
    except Exception as e:
        return f"❌ Regime fetch error: {e}"

    icons = {"TRENDING": "📈", "RANGING": "↔️", "CHAOS": "🌪️"}
    icon  = icons.get(reg.regime, "❓")
    lines = [
        f"{icon} *Market Regime: {reg.regime}*",
        f"   ATR ratio  : {reg.atr_ratio:.2f}x baseline",
        f"   ATR prev   : {reg.atr_ratio_prev:.2f}x (4h ago)",
        f"   Vol z-score: {reg.vol_z:+.2f}σ",
        f"   BTC vs SMA : {reg.momentum*100:+.2f}%",
        f"",
        f"   Score multiplier : ×{reg.multiplier}",
        f"   Min score floor  : {reg.min_score_floor}",
        f"   Reason: _{reg.reason}_",
    ]
    if reg.regime == "CHAOS":
        lines.append("\n⚠️ _CHAOS: hanya sinyal ≥70 yang actionable, ukuran posisi dikecilkan._")
    elif reg.regime == "TRENDING":
        lines.append("\n✅ _TRENDING: sinyal momentum lebih andal, semua floor berlaku._")
    else:
        lines.append("\n↔️ _RANGING: mean-reversion lebih dominan, balanced long/short._")

    # ATR compression status
    if reg.atr_ratio_prev < 0.85 and reg.atr_ratio > reg.atr_ratio_prev * 1.15:
        lines.append(f"\n🌋 _ATR COMPRESSION→EXPANSION aktif: ATR naik dari "
                     f"{reg.atr_ratio_prev:.2f}x → {reg.atr_ratio:.2f}x — "
                     f"peluang breakout sedang terbuka._")
    return "\n".join(lines)


def progress_report() -> str:
    """Progress menuju live trading: sinyal per grade vs threshold yang dibutuhkan.
    Menampilkan progress bar, Grade C edge status, session breakdown, dan ETA."""
    try:
        rep = signal_tracker.hit_rate_report(SIGNAL_DB)
    except Exception as e:
        return f"📊 Signal DB error: {e}"

    total    = rep.get("total", 0)
    resolved = rep.get("resolved", 0)
    pending  = rep.get("pending", 0)

    if total == 0:
        return ("📊 *PRE-GAIN — PROGRESS LIVE TRADING*\n"
                "   Belum ada sinyal logged.\n"
                "   Daemon scan otomatis setiap 2 jam → sinyal terakumulasi sendiri.\n"
                "   Target: Grade C ≥40 resolved + E≥0.05R · Grade S ≥30 + E≥0.10R.")

    L = ["📊 *PRE-GAIN — PROGRESS KE LIVE TRADING*",
         f"   Total: {total} | Resolved: {resolved} | Pending: {pending}"]

    # ── Per-grade status ──────────────────────────────────────────────────────
    # Grade C edge thresholds (pregain_autotrader.GRADE_EDGE_THRESHOLDS)
    _thresholds = {"S": (30, 0.10), "A": (50, 0.15), "B": (30, 0.15), "C": (40, 0.05)}
    _grade_sess = rep.get("by_grade_session", {})

    for grade in ("S", "A", "B", "C"):
        b   = rep["by_grade"].get(grade, {})
        n   = b.get("n", 0)
        wr  = b.get("win_rate")
        avg = b.get("avg_outcome_pct")
        min_n, min_er = _thresholds.get(grade, (30, 0.10))

        filled = min(20, int(n / min_n * 20))
        bar = "█" * filled + "░" * (20 - filled)
        pct = min(100, int(n / min_n * 100))

        if n >= min_n:
            if grade == "C" and wr is not None and wr > 55:
                # Grade C edge OPEN — backtest shows E=+0.14R
                status = f"🟢 EDGE OPEN — E=+0.14R (backtest) · SHORT Asia/EU/US_Asia → LIVE"
            elif grade == "S" and wr is not None:
                # Grade S: show Asia+EU truth window
                gs_ae = _grade_sess.get("S", {})
                ae_n  = sum(gs_ae.get(s, {}).get("n", 0) for s in ("Asia", "EU"))
                ae_wr = (sum(gs_ae.get(s, {}).get("win_rate", 0) or 0
                             for s in ("Asia", "EU") if gs_ae.get(s, {}).get("n", 0)) /
                         max(1, sum(1 for s in ("Asia", "EU")
                                    if gs_ae.get(s, {}).get("n", 0))))
                status = (f"⚠️ Aggregate E=-0.03R (US drag) | "
                          f"Asia+EU: n={ae_n} WR={ae_wr:.0f}% — tunggu session gate")
            elif wr is not None and wr > 55:
                status = f"⚠️ {n} sampel — jalankan /pregain-backtest"
            elif wr is not None and wr >= 45:
                status = f"⚠️ {n} sampel, edge lemah ({wr}%)"
            else:
                status = f"❌ {n} sampel, WR rendah ({wr}%)"
        else:
            status = f"{pct}% menuju threshold ({n}/{min_n})"

        L.append(f"   Grade {grade}: [{bar}] {status}")
        if n > 0 and wr is not None:
            avg_str = f"{avg:+.3f}%" if avg is not None else "?"
            L.append(f"             WR={wr}% | avg={avg_str}")
            # Session mini-breakdown per grade (top 2 sesi terbaik)
            sess_data = _grade_sess.get(grade, {})
            sess_sorted = sorted(
                [(s, d) for s, d in sess_data.items() if d.get("n", 0) >= 3],
                key=lambda x: x[1].get("avg_outcome_pct") or -99, reverse=True)
            if sess_sorted:
                _si = {"Asia": "🌏", "EU": "🇪🇺", "US": "🇺🇸", "US_Asia": "🌙"}
                best = [(f"{_si.get(s,'📡')}{s}:n={d['n']}WR={d.get('win_rate',0):.0f}%"
                         f"avg={d.get('avg_outcome_pct',0):+.1f}%")
                        for s, d in sess_sorted[:2]]
                L.append(f"             ↳ {' | '.join(best)}")

    # ── Grade C SHORT edge highlight ─────────────────────────────────────────
    gc_short = sum(
        _grade_sess.get("C", {}).get(s, {}).get("n", 0)
        for s in ("Asia", "EU", "US_Asia"))
    gc_short_wr = 0
    try:
        conn = signal_tracker.connect(SIGNAL_DB)
        try:
            row = conn.execute(
                "SELECT COUNT(*), AVG(correct)*100 FROM signal_log "
                "WHERE grade='C' AND direction='SHORT' AND session IN ('Asia','EU','US_Asia') "
                "AND outcome_pct IS NOT NULL").fetchone()
        finally:
            conn.close()
        if row and row[0]:
            gc_short = row[0]
            gc_short_wr = round(row[1] or 0, 0)
    except Exception:
        pass

    if gc_short >= 20:
        L.append(f"\n🟢 *GRADE C SHORT PRIME SESSIONS: n={gc_short} WR={gc_short_wr:.0f}%*")
        L.append("   Asia/EU/US_Asia SHORT → edge OPEN · aktifkan LIVE ketika siap")
        L.append("   (US SHORT masih PAPER — avg -0.07%, borderline)")

    # ── Signal rate + ETA ─────────────────────────────────────────────────────
    try:
        conn = signal_tracker.connect(SIGNAL_DB)
        try:
            row = conn.execute("SELECT MIN(ts), COUNT(*) FROM signal_log").fetchone()
        finally:
            conn.close()

        first_ts, total_all = (row[0] or 0), (row[1] or 0)
        if first_ts and total_all > 0:
            days_elapsed = max(1, (time.time() - first_ts) / 86400)
            rate_per_day = round(total_all / days_elapsed, 1)

            # Grade C SHORT Asia+EU ETA (highest priority since edge is OPEN)
            gc_n = rep["by_grade"].get("C", {}).get("n", 0)
            gs_n = rep["by_grade"].get("S", {}).get("n", 0)
            gc_rate = max(0.1, gc_n / days_elapsed)
            gs_ae_n = sum(_grade_sess.get("S", {}).get(s, {}).get("n", 0)
                          for s in ("Asia", "EU"))

            L.append(f"\n   Rate sinyal: {rate_per_day}/hari | Aktif: {round(days_elapsed, 1)} hari")
            if gc_n >= 40:
                L.append("   Grade C: ✅ edge gate terbuka — SHORT Asia/EU/US_Asia siap LIVE")
            L.append(f"   Grade S Asia+EU: n={gs_ae_n} (true edge window, WR 83%+)")
    except Exception:
        pass

    # ── Overall session breakdown ─────────────────────────────────────────────
    by_sess = rep.get("by_session", {})
    if by_sess:
        _sess_icons = {"Asia": "🌏", "EU": "🇪🇺", "US": "🇺🇸", "US_Asia": "🌙"}
        L.append("\n   Overall session (semua grade):")
        for sess in ("Asia", "EU", "US", "US_Asia"):
            b = by_sess.get(sess)
            if b and b.get("n"):
                icon = _sess_icons.get(sess, "📡")
                wr_s = f"WR={b['win_rate']}%" if b["win_rate"] is not None else "?"
                avg_s = f"avg={b['avg_outcome_pct']:+.1f}%" if b.get("avg_outcome_pct") is not None else ""
                note = " ← TRUE EDGE" if sess in ("Asia", "EU") else " ← PAPER"
                L.append(f"   {icon} {sess:<8}: n={b['n']}  {wr_s}  {avg_s}{note}")

    L.append("\n   /pregain-backtest → expectancy R per grade")
    L.append("   /pregain-trend → 7-hari rolling | /pregain-gates → 10 sovereign gates")
    return "\n".join(L)


def trend_report(days: int = 7) -> str:
    """Rolling win-rate untuk `days` hari terakhir — deteksi tren kualitas sinyal.

    Melengkapi progress_report() (all-time) dengan gambaran RECENT performance.
    Win-rate yang menurun = peringatan bahwa kondisi pasar mungkin berubah.
    Breakdown per sesi memvalidasi riset Asia/EU 80% vs US_Asia 54%.
    """
    try:
        rep = signal_tracker.rolling_win_rate(SIGNAL_DB, days=days)
    except Exception as e:
        return f"📊 Trend error: {e}"

    n = rep.get("n", 0)
    if not n:
        return (f"📊 *PRE-GAIN TREND ({days}d)*\n"
                f"   Belum ada sinyal resolved dalam {days} hari terakhir.\n"
                f"   Sinyal terakumulasi setiap 30 menit, resolved setelah 24 jam.")

    wr = rep.get("win_rate")
    avg = rep.get("avg_outcome_pct")
    verdict = ("✅ ada edge" if wr and wr > 55 else
               "⚠️ mendekati (≥50%)" if wr and wr >= 50 else "❌ di bawah acak")
    avg_str = f"{avg:+.3f}%" if avg is not None else "?"

    L = [
        f"📈 *PRE-GAIN TREND {days} HARI TERAKHIR*",
        f"   n={n} resolved | win-rate {wr}% | avg {avg_str}  → {verdict}",
    ]

    by_sess = rep.get("by_session", {})
    if by_sess:
        _sess_icons = {"Asia": "🌏", "EU": "🇪🇺", "US": "🇺🇸", "US_Asia": "🌙"}
        L.append("   Per sesi (empiris dari sinyal kita):")
        for sess in ("Asia", "EU", "US", "US_Asia"):
            b = by_sess.get(sess)
            if b and b.get("n"):
                icon = _sess_icons.get(sess, "📡")
                wr_s = f"win {b['win_rate']}%" if b["win_rate"] is not None else "?"
                avg_s = f"avg {b['avg_outcome_pct']:+.3f}%" if b.get("avg_outcome_pct") is not None else ""
                L.append(f"   {icon} {sess:<8}: n={b['n']}  {wr_s}  {avg_s}")
    else:
        L.append("   (session data belum tersedia — sinyal lama tidak punya kolom session)")

    L.append(f"\n   /pregain-validate → all-time  |  /pregain-trend → {days}d rolling")
    return "\n".join(L)


def backtest() -> str:
    """Paper-trade simulate every logged signal ≥24h old (triple-barrier SL/TP)
    and return an honest expectancy report — the real 'would-it-profit' answer."""
    try:
        from anantara import pregain_backtest
    except ImportError:
        import pregain_backtest                                     # type: ignore
    rep = pregain_backtest.backtest_logged(SIGNAL_DB, pregain_backtest.fetch_path)
    return pregain_backtest.format_report(rep)


# ── Telegram summary (daemon) ────────────────────────────────────────────────
def telegram_summary(longs: list[dict], shorts: list[dict], regime,
                     macro=None) -> str:
    """Compact, HONEST Telegram message for the daemon's periodic scan job."""
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    # Market bias indicator based on BTC momentum direction
    if regime.momentum <= -0.03:
        bias_tag = f"🔴 BEAR (long×{regime.long_multiplier} short×{regime.short_multiplier})"
    elif regime.momentum >= 0.03:
        bias_tag = f"🟢 BULL (long×{regime.long_multiplier} short×{regime.short_multiplier})"
    else:
        bias_tag = f"⚪ Neutral (BTC {regime.momentum*100:+.1f}% vs SMA20)"

    # Session quality annotation (research: Asia/EU = 80% win, US→Asia = 54%)
    utc_hour = datetime.now(timezone.utc).hour
    if 0 <= utc_hour < 12 or 16 <= utc_hour < 20:
        session_name = "Asia" if utc_hour < 8 else ("EU" if utc_hour < 12 else "US")
        session_tag = f"📡 {session_name} session (sinyal lebih reliable)"
    else:
        session_tag = "⚠️ US→Asia session (win-rate lebih rendah ~54%)"

    L = [f"🎯 *Pre-Gain/Loser Radar* · {now}",
         f"🌐 Regime: *{regime.regime}* | {bias_tag}",
         f"{session_tag}"]

    # Macro context — tampilkan jika tersedia (key set + bukan error)
    if macro and "key missing" not in macro.reason and "error" not in macro.reason:
        etf_tag = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⚪"}.get(macro.etf.bias, "⚪")
        L.append(f"{etf_tag} ETF: {macro.etf.label[:55]}")
        if macro.sector.hot_sectors:
            L.append(f"🔥 Sektor hot: {', '.join(macro.sector.hot_sectors[:3])}")
        if macro.sector.cold_sectors:
            L.append(f"🧊 Sektor cold: {', '.join(macro.sector.cold_sectors[:2])}")
        if macro.events:
            near = [e for e in macro.events if e.hours_until <= 24]
            if near:
                L.append(f"⚠️ Event <24h: {near[0].name}")
        adj_str = f"LONG {macro.long_adj:+d}pt / SHORT {macro.short_adj:+d}pt"
        L.append(f"📊 Macro adj: {adj_str}")

    def _engine_mini(eng: dict, direction: str) -> str:
        """Mini 7-engine breakdown untuk top signal (1 baris singkat).

        Menampilkan engines yang AKTIF (score > 0.3) saja — mengurangi clutter.
        Format: M1:vz M3:oi M5:cvd M7:mtf (hanya yang signifikan)
        """
        if not eng:
            return ""
        parts = []
        if eng.get("m1_zscore", 0) > 0.3:
            parts.append(f"Z{eng['m1_zscore']:.1f}")
        if eng.get("m3_oi_vel", 0) > 0.3:
            parts.append(f"OI{eng['m3_oi_vel']:.1f}")
        m5 = eng.get("m5_cvd", 0)
        if abs(m5) > 0.3:
            parts.append(f"CVD{m5:+.1f}")
        m7 = eng.get("m7_mtf", 0)
        if abs(m7) > 0.25:
            parts.append(f"MTF{m7:+.1f}")
        if eng.get("m6_liq_prox", 0) > 0.4:
            parts.append(f"LIQ{eng['m6_liq_prox']:.1f}")
        return f"  _{'+'.join(parts) or 'base'}_" if parts else ""

    def _line(r, arrow):
        liq = {"LIQUID": "🟢", "THIN": "🟡", "DUST": "🔴"}.get(r["liq"], "·")
        sigs = r["lsigs"] if arrow == "▲" else r["ssigs"]
        top = sigs[0] if sigs else "—"
        base = (f"{arrow} {r['name']} `{r['score']}`{r['grade']} {liq} "
                f"{r['chg']:+.1f}% | {r['ann_fund']:+.0f}%/yr | {top}")
        # Engine breakdown (hanya untuk top-1 signal — bukan semua agar tidak spam)
        return base

    def _line_with_engines(r, arrow):
        """Sama seperti _line tapi tambah engine breakdown untuk top signal."""
        liq = {"LIQUID": "🟢", "THIN": "🟡", "DUST": "🔴"}.get(r["liq"], "·")
        sigs = r["lsigs"] if arrow == "▲" else r["ssigs"]
        top = sigs[0] if sigs else "—"
        base = (f"{arrow} {r['name']} `{r['score']}`{r['grade']} {liq} "
                f"{r['chg']:+.1f}% | {r['ann_fund']:+.0f}%/yr | {top}")
        eng_key = "_eng_long" if arrow == "▲" else "_eng_short"
        eng = r.get(eng_key, {})
        eng_line = _engine_mini(eng, "LONG" if arrow == "▲" else "SHORT")
        return base + ("\n" + eng_line if eng_line else "")

    actionable_l = [r for r in longs if r["score"] >= ACTIONABLE_MIN and r["liq"] != "DUST"]
    actionable_s = [r for r in shorts if r["score"] >= ACTIONABLE_MIN and r["liq"] != "DUST"]

    if actionable_l:
        L.append("\n*BUY/LONG candidates:*")
        # Top-1: tampilkan engine breakdown; sisanya: ringkas
        if actionable_l:
            L.append(_line_with_engines(actionable_l[0], "▲"))
            L += [_line(r, "▲") for r in actionable_l[1:5]]
    if actionable_s:
        L.append("\n*SELL/SHORT candidates:*")
        if actionable_s:
            L.append(_line_with_engines(actionable_s[0], "▼"))
            L += [_line(r, "▼") for r in actionable_s[1:5]]
    if not actionable_l and not actionable_s:
        L.append("\n_Tidak ada kandidat actionable (≥60, non-dust) saat ini._")

    L.append(f"\n⚠️ _score = attention rank, BUKAN probabilitas profit. "
             f"DUST (<$1M) di-skip. /pregain-validate untuk hit-rate nyata._")
    return "\n".join(L)


def scan_and_format(min_score: int = ACTIONABLE_MIN) -> str:
    """One-call for the daemon: scan (logs actionable to validator) → Telegram text."""
    longs, shorts, regime = run_scan(min_score, log=True, verbose=False)
    try:
        macro = sosovalue_macro.fetch_macro_context()
    except Exception:
        macro = None
    base_text = telegram_summary(longs, shorts, regime, macro)

    import logging as _scan_log
    _logger = _scan_log.getLogger(__name__)

    # ── Pre-Gain LONG signals (Futures, technical scanner) ──────────────────
    # K19 DISABLED (2026-06-16): n=100 resolved, WR=1.0% (1/100), avg=-14.57%, e_r=-4.858.
    # ALL signals are PURR — dip-buying in bear regime catches falling knives.
    # Logging stopped to prevent DB contamination. Re-enable when:
    #   (a) scanner detects non-PURR coins OR (b) hypothesis reformulated with new signal type.
    # decide() in pregain_autotrader.py already hard-SKIPs LONG_TECHNICAL as safety backstop.
    pass  # long_sigs = _pls.scan_long_signals() — DISABLED

    # ── Pre-Gain SPOT signals (Breakout + Dip Recovery) ──────────────────────
    try:
        from anantara import pregain_spot_scanner as _pss
        spot_sigs = _pss.scan_all_spot()   # auto-selects variant by BTC regime
        if spot_sigs:
            sigs_to_log = [
                signal_tracker.Signal(
                    s["name"], "LONG", s["score"], s["grade"],
                    s.get("entry_price", 0), "RANGING",
                    s.get("vol24", 0), "STANDARD",
                    fund_accel=0.0,
                    vol_oi=s.get("vol_ratio", 1.0),
                    sig_type="SPOT_BREAKOUT",
                )
                for s in spot_sigs
                if s.get("entry_price", 0) > 0   # guard: entry_price=0 pollutes edge stats
            ]
            n_logged = signal_tracker.log_signals(
                SIGNAL_DB, sigs_to_log, cooldown_sec=_SPOT_LOG_COOLDOWN_SEC)
            if n_logged > 0:
                base_text = base_text + "\n\n" + _pss.format_spot_report(spot_sigs)
    except Exception as _e:
        _logger.error(f"scan_and_format SPOT failed: {_e}")

    return base_text
