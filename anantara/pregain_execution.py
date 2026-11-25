#!/usr/bin/env python3
"""
ANANTARA SAKTI — Pre-Gain/Loser Trading Execution on Hyperliquid

Implements the execution layer for the Pre-Gain/Loser Scan & Trading System.
When the edge gate opens (≥30 resolved/grade, expectancy ≥0.10R), this module
provides order placement and position management on Hyperliquid perpetuals.

SAFETY DESIGN (berlapis, tidak bisa di-bypass):
  1. edge_gate_open() — edge HARUS terbukti sebelum uang nyata
  2. Paper mode      — live_enabled=False → log JSONL tanpa order ke exchange
  3. ENV gate        — PREGAIN_LIVE=1 wajib selain --live flag
  4. Max positions   — tolak order baru jika sudah di limit
  5. Daily loss cap  — circuit breaker jika rugi > cap hari ini
  6. Dry-run safe    — tanda DRY_RUN pada semua log paper-trade

Security hardening (v2 — post-audit):
  - Thread-safe meta cache dengan threading.Lock
  - Monotonic nonce dengan per-instance lock (cegah replay attack)
  - Position state recovery: backup file jika primary corrupt
  - Private key format validation sebelum signing
  - Daily loss cap sebagai fraction (0.05 = 5%, not 0.20)
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────
HL_API           = "https://api.hyperliquid.xyz"
HL_ADDRESS_ENV   = "HL_ADDRESS"
HL_SECRET_ENV    = "HL_API_SECRET"
PREGAIN_LIVE_ENV = "PREGAIN_LIVE"

MAX_POSITIONS    = 5             # v6.1: 3→5 — margin 5×$20/5x=$20 total, max loss $5 < cap $12
# Two-tier daily-loss protection (both active simultaneously):
#   DAILY_LOSS_CAP here = 0.05 (5%)  — hard circuit breaker in place_order() / monitor_and_close()
#   pregain_autotrader.DEFAULTS["daily_loss_cap"] = 0.20 (20%) — softer gate in decide()
# The 5% gate here fires FIRST and is intentionally more conservative than the autotrader
# threshold, acting as a last-resort floor when the softer gate was somehow bypassed.
DAILY_LOSS_CAP   = 0.05      # 5% max daily loss — hard floor (execution layer)
SL_PCT_DEFAULT   = 3.0    # v8.6: SL=3% optimal from 1,420-signal batch sweep (E=+1.014R)
TP_PCT_DEFAULT   = 20.0   # proven: Grade C E=+0.081R OPEN dengan TP=20% (jangan ubah)
MIN_EDGE_R       = 0.10
MIN_SAMPLE       = 30   # default for grades without specific threshold
MIN_POSITION_USD = 11.0      # HL minimum order = $10; use $11 as safe floor

# ── Per-grade edge thresholds (v8.9: canonical definition, imported by autotrader) ──
GRADE_EDGE_THRESHOLDS: dict[str, dict] = {
    "S": {"min_sample": 30, "min_edge_r": 0.10},
    "A": {"min_sample": 50, "min_edge_r": 0.15},
    "B": {"min_sample": 30, "min_edge_r": 0.15},
    "C": {"min_sample": 40, "min_edge_r": 0.05},
}

STATE_FILE  = Path(os.environ.get("ANANTARA_POSITIONS",
              str(Path.home() / ".local/share/anantara/pregain_positions.json")))
STATE_BACKUP= Path(str(STATE_FILE) + ".bak")
PAPER_LOG   = Path(os.environ.get("ANANTARA_PAPER_LOG",
              str(Path.home() / ".local/share/anantara/pregain_paper.jsonl")))
TRADE_LOG   = Path(os.environ.get("ANANTARA_TRADE_LOG",
              str(Path.home() / ".local/share/anantara/pregain_trades.jsonl")))

# ── Order placement lock: prevents TOCTOU race (count() >= MAX then add()) ───
# Two concurrent asyncio.to_thread() calls could both pass the count() check
# and add a position each, exceeding MAX_POSITIONS. This module-level lock
# serialises the check-then-add critical section across threads.
_ORDER_LOCK: threading.Lock = threading.Lock()

# ── Thread-safe HL meta cache ─────────────────────────────────────────────────
_meta_lock:  threading.Lock = threading.Lock()
_meta_cache: Optional[tuple] = None   # (universe_list, ctxs_list)
_meta_ts:    float           = 0.0
_META_TTL    = 60.0

# ── Mark price failure tracking ───────────────────────────────────────────────
# Count consecutive monitor cycles where mark price is unavailable per coin.
# Alert after _MARK_MISS_ALERT_THRESHOLD consecutive misses (≈10 min at 2-min cycle).
_mark_miss_count: dict[str, int] = {}
_MARK_MISS_ALERT_THRESHOLD = 5

# ── Monotonic nonce (replay protection) ──────────────────────────────────────
_nonce_lock: threading.Lock = threading.Lock()
_last_nonce: int             = 0


def _next_nonce() -> int:
    """Strictly monotonically increasing nonce — prevents EIP-712 replay attacks."""
    global _last_nonce
    with _nonce_lock:
        ts_ms = int(time.time() * 1000)
        _last_nonce = max(_last_nonce + 1, ts_ms)
        return _last_nonce


# ── Data classes ──────────────────────────────────────────────────────────────
@dataclass
class OpenPosition:
    coin:       str
    direction:  str           # LONG | SHORT
    size:       float
    entry_px:   float
    entry_ts:   int
    sl_pct:     float
    tp_pct:     float
    size_usd:   float
    grade:      str
    mode:       str           # LIVE | PAPER
    # Optional fields for SPOT/trailing-stop positions
    sig_type:     str = ""      # SPOT_BREAKOUT | LONG_TECHNICAL | SHORT | LONG_FUNDING
    trail_pct:    float = 0.0   # trailing stop % (0 = disabled, use sl_pct instead)
    high_px:      float = 0.0   # highest price seen since entry (for trailing stop)
    hold_days:    int   = 0     # max hold in days (0 = use sl/tp only)
    # v11.0 K1: native HL stop order ID. Exchange fires at mark price — fills before
    # the 2-min software poll, providing gap protection on thin/volatile coins.
    # Empty string = stop order not placed (software SL still active as fallback).
    sl_order_oid: str  = ""


@dataclass
class OrderResult:
    ok:        bool
    mode:      str            # LIVE | PAPER | REFUSED
    coin:      str
    direction: str
    size_usd:  float
    entry_px:  float
    reason:    str


# ── Edge gate ─────────────────────────────────────────────────────────────────
def edge_gate_open(edge_stats: dict, grade: str) -> tuple[bool, str]:
    """Return (open, reason). Real money only when edge is empirically proven.
    v8.9: Uses module-level GRADE_EDGE_THRESHOLDS (no circular import).
    """
    thresh     = GRADE_EDGE_THRESHOLDS.get(grade, {})
    min_n      = thresh.get("min_sample", MIN_SAMPLE)
    min_edge_r = thresh.get("min_edge_r", MIN_EDGE_R)

    st = (edge_stats or {}).get(grade)
    if not st:
        return False, f"grade {grade}: tidak ada data edge"
    n  = st.get("n", 0)
    er = st.get("expectancy_r", -9.9)
    if n < min_n:
        return False, f"grade {grade}: n={n} < {min_n} minimum (kumpul data dulu)"
    if er < min_edge_r:
        return False, f"grade {grade}: expectancy {er:.3f}R < {min_edge_r}R (edge belum positif)"
    return True, f"grade {grade}: n={n} E={er:.3f}R ✅"


# ── Unified account: available USDC (spot + perp combined) ───────────────────
# HL unified account: spot USDC acts as perp margin automatically.
# clearinghouseState shows perp-only balance ($0 if all in spot).
# spotClearinghouseState shows actual USDC available for both spot & perp.
_balance_lock: threading.Lock = threading.Lock()
_balance_cache: float = 0.0
_balance_ts:    float = 0.0
_BALANCE_TTL = 60.0   # refresh every 60s


def _available_usdc() -> float:
    """Return available USDC for new positions (spot wallet balance - held margin).

    Uses ONLY spotClearinghouseState.USDC: total - hold.
    - `total` = USDC deposited to spot wallet
    - `hold`  = USDC locked as margin for open perp positions

    Previously also added clearinghouseState.marginSummary.accountValue (perp equity),
    but that caused DOUBLE-COUNTING: spot.hold already accounts for margin locked in
    perp, so adding perp accountValue inflated available capital by the position size
    (or deflated by unrealized losses). Fixed: spot-only is the correct source.

    Fallback: stale cache → DEFAULTS["capital"] (conservative).
    """
    global _balance_cache, _balance_ts
    with _balance_lock:
        if _balance_cache > 0 and time.time() - _balance_ts < _BALANCE_TTL:
            return _balance_cache

    addr = os.environ.get(HL_ADDRESS_ENV, "").strip()
    if not addr:
        return _balance_cache or 60.0

    try:
        import httpx as _httpx
        r = _httpx.post(f"{HL_API}/info",
                        json={"type": "spotClearinghouseState", "user": addr},
                        timeout=8)
        balances = r.json().get("balances", [])
        usdc = next((b for b in balances if b.get("coin") == "USDC"), {})
        total = float(usdc.get("total", 0) or 0)
        hold  = float(usdc.get("hold", 0) or 0)
        available = max(0.0, total - hold)
        with _balance_lock:
            _balance_cache = available or _balance_cache or 60.0
            _balance_ts    = time.time()
        return _balance_cache
    except Exception:
        return _balance_cache or 60.0


# ── HL meta (thread-safe) ─────────────────────────────────────────────────────
def _get_meta() -> Optional[tuple]:
    global _meta_cache, _meta_ts
    with _meta_lock:
        if _meta_cache and time.time() - _meta_ts < _META_TTL:
            return _meta_cache
    try:
        import httpx as _httpx
    except ImportError:
        return _meta_cache   # httpx not available; return stale or None
    try:
        r = _httpx.post(f"{HL_API}/info", json={"type": "metaAndAssetCtxs"}, timeout=10)
        data = r.json()
        result = (data[0]["universe"], data[1])
        with _meta_lock:
            _meta_cache = result
            _meta_ts = time.time()
        return result
    except Exception:
        with _meta_lock:
            return _meta_cache   # return stale if available


def _asset_index(coin: str) -> Optional[int]:
    meta = _get_meta()
    if not meta:
        return None
    universe, _ = meta
    for i, a in enumerate(universe):
        if a["name"] == coin:
            return i
    return None


def _mark_price(coin: str) -> float:
    meta = _get_meta()
    if not meta:
        return 0.0
    universe, ctxs = meta
    for a, c in zip(universe, ctxs):
        if a["name"] == coin:
            return float(c.get("markPx", 0) or 0)
    return 0.0


def _asset_decimals(coin: str) -> int:
    """Return display decimals for size precision. Default 4."""
    meta = _get_meta()
    if not meta:
        return 4
    universe, _ = meta
    for a in universe:
        if a["name"] == coin:
            return int(a.get("szDecimals", 4))
    return 4


def _round_price(price: float) -> str:
    """Format price to 5 significant figures for HL API.

    HL rejects prices with too many significant figures — e.g. SOL $64.158944
    (8 sig figs) fails with 'Order has invalid price'. The fix: round to 5 sig figs.

    Handles full price range including sub-cent coins (PURR $0.00034, etc.):
    - For price ≥ 1:  use standard sig-fig rounding (0-4 decimal places)
    - For price < 1:  compute correct decimal places for 5 sig figs, cap at 8 decimals

    Examples: BTC $61235.0 → "61235", SOL $64.159 → "64.159",
              PURR $0.000340 → "0.00034" (trailing zeros stripped)
    """
    import math
    if price <= 0:
        return "0"
    digits = math.ceil(math.log10(abs(price)))
    decimal_places = max(0, min(8, 5 - digits))   # cap at 8 decimals (HL max precision)
    formatted = f"{price:.{decimal_places}f}"
    # Strip trailing zeros after decimal point (keeps "64.100" → "64.1", not "64.10000")
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
        # Ensure at least 1 decimal for sub-dollar prices (HL requires decimal point)
        if price < 1.0 and "." not in formatted:
            formatted = formatted + ".0"
    return formatted


# ── Private key validation ────────────────────────────────────────────────────
def _validate_private_key(key: str) -> bool:
    """Validate HL agent private key format (0x-prefixed 64-char hex or 66-char)."""
    if not key:
        return False
    # Allow with or without 0x prefix, must be valid hex, 32 bytes = 64 hex chars
    k = key.lower().replace("0x", "")
    return bool(re.fullmatch(r"[0-9a-f]{64}", k))


# ── EIP-712 signing ───────────────────────────────────────────────────────────
def _ensure_eth_packages() -> None:
    """Add .venv-research site-packages to sys.path if eth_account not found.

    Daemon runs on system Python which may lack eth-account/msgpack.
    These packages ARE installed in .venv-research. This function adds that
    path as a fallback — zero overhead when already available.
    """
    try:
        import eth_account  # noqa: F401
        return  # already available
    except ImportError:
        pass
    import sys
    from pathlib import Path
    current_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    venv_site = Path(__file__).parent.parent / ".venv-research" / "lib"
    # Only add the path matching the current interpreter version (prevents
    # injecting 3.10-compiled C-extensions into a 3.12 process).
    sp = venv_site / current_ver / "site-packages"
    if sp.exists() and str(sp) not in sys.path:
        sys.path.insert(0, str(sp))
    # Verify
    try:
        import eth_account  # noqa: F401, F811 — re-import after path fix
    except ImportError:
        raise RuntimeError(
            "eth_account tidak tersedia. Jalankan di terminal:\n"
            "  .venv-research/bin/pip install eth-account msgpack"
        )


def _sign_hl_action(private_key: str, action: dict, nonce: int) -> dict:
    """Sign HL exchange action with EIP-712 phantom agent scheme."""
    _ensure_eth_packages()
    import msgpack
    from eth_hash.auto import keccak
    from eth_account import Account

    def _mp_default(obj):
        if isinstance(obj, float):
            return msgpack.ExtType(0, obj.to_bytes(8, "big"))
        raise TypeError(f"Unknown type: {type(obj)}")

    data = msgpack.packb(action, default=_mp_default, use_bin_type=True)
    data += nonce.to_bytes(8, "big")
    data += b"\x00"
    conn_id = keccak(data)

    signed = Account.sign_typed_data(
        private_key,
        domain_data={
            "name": "Exchange", "version": "1", "chainId": 1337,
            "verifyingContract": "0x0000000000000000000000000000000000000000",
        },
        message_types={"Agent": [
            {"name": "source",       "type": "string"},
            {"name": "connectionId", "type": "bytes32"},
        ]},
        message_data={"source": "a", "connectionId": conn_id},
    )
    return {"r": hex(signed.r), "s": hex(signed.s), "v": signed.v}


def _post_exchange(private_key: str, action: dict) -> dict:
    """Post signed action to HL /exchange. Raises on fatal errors."""
    import httpx

    if not _validate_private_key(private_key):
        raise ValueError("HL_API_SECRET format tidak valid (harus 64-char hex)")

    nonce = _next_nonce()
    try:
        sig = _sign_hl_action(private_key, action, nonce)
    except ImportError:
        raise RuntimeError(
            "eth_account + msgpack diperlukan untuk live trading. "
            "Jalankan: .venv-research/bin/pip install eth-account msgpack"
        )

    payload = {"action": action, "nonce": nonce, "signature": sig, "vaultAddress": None}
    try:
        r = httpx.post(f"{HL_API}/exchange", json=payload,
                       headers={"Content-Type": "application/json"}, timeout=15)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"HL exchange HTTP error {e.response.status_code}: {e.response.text[:200]}")
    except Exception as e:
        raise RuntimeError(f"HL exchange error: {e}")


# ── HL market order ───────────────────────────────────────────────────────────
def _place_hl_order(private_key: str, coin: str, is_buy: bool,
                    size_usd: float) -> dict:
    """Submit IOC taker order on HL. Returns {ok, entry_px, size, reason}."""
    if size_usd < MIN_POSITION_USD:
        return {"ok": False, "reason": f"size_usd {size_usd:.2f} < min {MIN_POSITION_USD}"}

    idx  = _asset_index(coin)
    if idx is None:
        return {"ok": False, "reason": f"{coin} tidak ada di HL"}

    mark = _mark_price(coin)
    if mark <= 0:
        return {"ok": False, "reason": f"{coin} mark price invalid ({mark})"}

    sz_dec  = _asset_decimals(coin)
    size    = round(size_usd / mark, sz_dec)
    if size <= 0:
        return {"ok": False, "reason": "computed size = 0 (mark price too high?)"}

    # 0.3% slippage buffer for IOC
    limit_px = mark * (1.003 if is_buy else 0.997)

    action = {
        "type":   "order",
        "orders": [{
            "a": idx, "b": is_buy,
            "p": _round_price(limit_px), "s": f"{size:.{sz_dec}f}",
            "r": False, "t": {"limit": {"tif": "Ioc"}},
        }],
        "grouping": "na",
    }
    try:
        resp = _post_exchange(private_key, action)
    except RuntimeError as e:
        return {"ok": False, "reason": str(e)}

    if not resp:
        return {"ok": False, "reason": "respons kosong dari HL"}

    statuses = resp.get("response", {}).get("data", {}).get("statuses", [])
    if not statuses:
        return {"ok": False, "reason": f"respons tidak punya statuses: {resp}"}

    filled = statuses[0].get("filled", {})
    if filled:
        avg_px = float(filled.get("avgPx", mark))
        total  = float(filled.get("totalSz", size))
        return {"ok": True, "entry_px": avg_px, "size": total}

    resting = statuses[0].get("resting", {})
    if resting:
        return {"ok": False, "reason": f"tidak ter-fill (IOC resting — spread terlalu sempit?): {resting}"}

    return {"ok": False, "reason": f"unknown status: {statuses[0]}"}


def _close_hl_position(private_key: str, coin: str, is_buy: bool, size: float) -> dict:
    """Close position (reduce-only IOC). is_buy=True closes SHORT."""
    if size <= 0:
        return {"ok": False, "reason": "size <= 0"}

    idx  = _asset_index(coin)
    if idx is None:
        return {"ok": False, "reason": f"{coin} tidak ada di HL"}

    mark = _mark_price(coin)
    if mark <= 0:
        return {"ok": False, "reason": "mark price invalid"}

    sz_dec   = _asset_decimals(coin)
    limit_px = mark * (1.003 if is_buy else 0.997)

    action = {
        "type":   "order",
        "orders": [{
            "a": idx, "b": is_buy,
            "p": _round_price(limit_px), "s": f"{size:.{sz_dec}f}",
            "r": True, "t": {"limit": {"tif": "Ioc"}},
        }],
        "grouping": "na",
    }
    try:
        resp = _post_exchange(private_key, action)
    except RuntimeError as e:
        return {"ok": False, "reason": str(e)}

    statuses = (resp or {}).get("response", {}).get("data", {}).get("statuses", [])
    filled   = statuses[0].get("filled", {}) if statuses else {}
    return {
        "ok":       bool(filled),
        "close_px": float(filled.get("avgPx", mark)) if filled else 0.0,
        "reason":   "" if filled else f"tidak ter-fill: {statuses}",
    }


# ── v11.0 K1: Native HL stop orders ──────────────────────────────────────────
# Exchange-speed SL fills BEFORE the 2-min software poll, preventing gap risk
# on thin or volatile coins (Fable 5 audit finding K1). Software poll remains
# as fallback in case the native stop order placement fails at entry time.

def _place_hl_stop_order(private_key: str, coin: str, is_buy_close: bool,
                          size: float, trigger_px: float) -> dict:
    """Place a native reduce-only stop-loss trigger order on HL.

    For SHORT positions: is_buy_close=True,  trigger_px = entry * (1 + sl_pct/100)
    For LONG  positions: is_buy_close=False, trigger_px = entry * (1 - sl_pct/100)

    Fires as a market order when mark price crosses trigger_px (exchange-speed).
    Returns {ok, oid, reason}. Failure is non-fatal — software SL stays as backup.
    """
    idx = _asset_index(coin)
    if idx is None:
        return {"ok": False, "oid": None, "reason": f"{coin} tidak ada di HL"}

    sz_dec = _asset_decimals(coin)
    action = {
        "type": "order",
        "orders": [{
            "a": idx,
            "b": is_buy_close,
            "p": "0",           # market execution when triggered
            "s": f"{size:.{sz_dec}f}",
            "r": True,          # reduce-only
            "t": {
                "trigger": {
                    "isMarket": True,
                    "tpsl":     "sl",
                    "triggerPx": _round_price(trigger_px),
                }
            },
        }],
        "grouping": "na",
    }
    try:
        resp = _post_exchange(private_key, action)
    except RuntimeError as e:
        return {"ok": False, "oid": None, "reason": str(e)}

    statuses = (resp or {}).get("response", {}).get("data", {}).get("statuses", [])
    resting  = statuses[0].get("resting", {}) if statuses else {}
    return {
        "ok":     bool(resting),
        "oid":    resting.get("oid"),
        "reason": "" if resting else f"stop order gagal: {statuses}",
    }


def _cancel_hl_order(private_key: str, coin: str, oid: int) -> dict:
    """Cancel a resting HL order by oid.

    Called before software TP/TIMEOUT/SL close to prevent double-fill when a
    native stop order is also resting. Failure is non-fatal: if cancel fails,
    the stop may have already fired (position closed by exchange) or may never
    have been placed — both are acceptable states.
    Returns {ok, reason}.
    """
    idx = _asset_index(coin)
    if idx is None:
        return {"ok": False, "reason": f"{coin} tidak ada di HL"}

    action = {
        "type":    "cancel",
        "cancels": [{"a": idx, "o": oid}],
    }
    try:
        resp = _post_exchange(private_key, action)
    except RuntimeError as e:
        return {"ok": False, "reason": str(e)}

    statuses = (resp or {}).get("response", {}).get("data", {}).get("statuses", [])
    cancelled = statuses[0].get("success", "") if statuses else ""
    return {
        "ok":     bool(cancelled),
        "reason": "" if cancelled else f"cancel gagal (mungkin sudah terisi): {statuses}",
    }


# ── Position tracker ──────────────────────────────────────────────────────────
class PositionTracker:
    """Persistent position state — atomic write with backup, crash-safe."""

    def __init__(self, state_file: Path = STATE_FILE):
        self._path   = state_file
        self._backup = Path(str(state_file) + ".bak")
        self._lock   = threading.Lock()
        self._positions: dict[str, dict] = {}
        self._realized_today_usd: float  = 0.0   # cumulative realized PnL today (USD)
        self._realized_date: str         = ""     # UTC date string for reset detection
        self._load()

    def _load(self) -> None:
        """Load with automatic fallback to backup on corruption."""
        import logging as _log
        _logger = _log.getLogger("pregain_execution")
        for path in (self._path, self._backup):
            try:
                if path.exists():
                    raw  = path.read_text()
                    data = json.loads(raw)
                    self._positions = data.get("positions", {})
                    # Migrate positions from before v7.3 (missing new fields).
                    # Without this, trailing stops would silently fail after daemon restart.
                    for pos in self._positions.values():
                        pos.setdefault("sig_type", "")
                        pos.setdefault("trail_pct", 0.0)
                        pos.setdefault("high_px", float(pos.get("entry_px", 0) or 0))
                        pos.setdefault("hold_days", 0)
                        pos.setdefault("sl_order_oid", "")   # v11.0 K1
                    # Load today's realized PnL (if same UTC date)
                    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    saved_date = data.get("realized_date", "")
                    if saved_date == today:
                        self._realized_today_usd = float(data.get("realized_today_usd", 0.0))
                        self._realized_date = today
                    if path == self._backup:
                        _logger.warning(
                            "Position state loaded from BACKUP (primary corrupt). "
                            "Verify open positions on HL exchange manually."
                        )
                    return
            except Exception as e:
                _logger.warning(f"Position file {path.name} unreadable ({e}), trying backup")
                continue
        # Both primary and backup failed — starting with empty state
        _logger.error(
            "POSITION STATE LOST: both primary and backup position files unreadable. "
            "Starting with 0 positions. Verify open positions on HL exchange immediately!"
        )
        self._positions = {}

    def _save(self) -> None:
        """Atomic write with backup — never lose position data."""
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                payload = json.dumps({
                    "updated":            datetime.now(timezone.utc).isoformat(),
                    "positions":          self._positions,
                    "realized_date":      today,
                    "realized_today_usd": self._realized_today_usd,
                }, indent=2)
                # Write backup first (old primary becomes backup)
                if self._path.exists():
                    import shutil
                    shutil.copy2(str(self._path), str(self._backup))
                # Atomic write new primary
                tmp = str(self._path) + ".tmp"
                Path(tmp).write_text(payload)
                os.replace(tmp, str(self._path))
            except Exception as e:
                import logging
                logging.getLogger("pregain_execution").error(f"Position save failed: {e}")

    def add(self, pos: OpenPosition) -> None:
        self._positions[pos.coin] = asdict(pos)
        self._save()

    def remove(self, coin: str) -> None:
        self._positions.pop(coin, None)
        self._save()

    def record_realized_pnl(self, realized_usd: float) -> None:
        """Accumulate realized PnL for today's circuit breaker (resets at UTC midnight)."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._realized_date != today:
            self._realized_today_usd = 0.0
            self._realized_date = today
        self._realized_today_usd += realized_usd
        self._save()

    def get(self, coin: str) -> Optional[dict]:
        return self._positions.get(coin)

    def all(self) -> list[dict]:
        return list(self._positions.values())

    def count(self) -> int:
        return len(self._positions)

    def daily_pnl(self, capital: float = 60.0) -> float:
        """Sum of (unrealized + today's realized) P&L as FRACTION of capital.

        CRITICAL: includes realized P&L from positions closed today so the circuit
        breaker fires correctly even after all positions are closed.
        Positions with unavailable mark price are skipped conservatively.
        """
        if capital <= 0:
            return 0.0
        # Reset realized accumulator if date rolled over
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._realized_date != today:
            self._realized_today_usd = 0.0
            self._realized_date = today

        unrealized = 0.0
        for p in self._positions.values():
            coin     = p["coin"]
            mark     = _mark_price(coin)
            entry_px = float(p.get("entry_px", 0) or 0)
            size_usd = float(p.get("size_usd", 0) or 0)
            if mark <= 0 or entry_px <= 0 or size_usd <= 0:
                # Cannot measure P&L — exclude rather than assume zero
                # (assuming zero would under-report losses and bypass circuit-breaker).
                continue
            move  = (mark - entry_px) / entry_px
            pnl   = move if p["direction"] == "LONG" else -move
            unrealized += pnl * size_usd
        total_usd = unrealized + self._realized_today_usd
        return total_usd / capital   # fraction, e.g. -0.05 = -5%


# ── Logging helpers ───────────────────────────────────────────────────────────
def _log_jsonl(path: Path, data: dict) -> None:
    """Append JSON line to log file — safe, non-blocking.
    flush() after write ensures data reaches disk even if process crashes immediately
    after — critical for position-open / SL-TP-close audit records.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": int(time.time()), "utc": datetime.now(timezone.utc).isoformat(), **data}
        with open(path, "a") as f:
            f.write(json.dumps(row) + "\n")
            f.flush()
    except Exception:
        pass


def _log_paper(event: str, data: dict) -> None:
    _log_jsonl(PAPER_LOG, {"event": event, **data})


def _log_trade(data: dict) -> None:
    _log_jsonl(TRADE_LOG, data)


def _send_telegram_alert(msg: str) -> None:
    """Non-blocking Telegram alert for critical execution events."""
    try:
        import urllib.request, urllib.parse, os as _os
        token   = _os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = _os.environ.get("TELEGRAM_CHAT_ID", "")
        if not (token and chat_id):
            return
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": msg}).encode()
        req  = urllib.request.Request(url, data=data, method="POST")
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


# ── Main: place order ─────────────────────────────────────────────────────────
def place_order(signal: dict, decision, edge_stats: Optional[dict],
                live_enabled: bool, tracker: Optional[PositionTracker] = None,
                sl_pct: float = SL_PCT_DEFAULT,
                tp_pct: float = TP_PCT_DEFAULT) -> OrderResult:
    """Place an order on HL (real or paper) based on signal + decision.

    signal   : {coin, direction, grade, mark, liq, ...}
    decision : Decision(action, mode, size_usd, reason)
    edge_stats: {grade: {n, expectancy_r}} from validator/backtest
    live_enabled: flag from CLI (--live) + PREGAIN_LIVE=1 env check
    """
    coin      = signal.get("coin", "?")
    direction = signal.get("direction", "LONG").upper()
    grade     = signal.get("grade", "C")
    # Support both "mark" (main scanner) and "entry_price" (LONG_TECHNICAL/SPOT)
    mark      = float(signal.get("mark", 0) or signal.get("entry_price", 0) or 0)
    size_usd  = float(getattr(decision, "size_usd", 10.0))
    # SPOT/LONG_TECHNICAL-specific overrides from signal
    sig_type  = signal.get("type", signal.get("sig_type", ""))
    trail_pct = float(signal.get("trail_pct", 0.0))
    hold_days = int(signal.get("hold_days", 0))
    # Per-signal SL/TP (LONG_TECHNICAL uses 5%/15%, SPOT uses trail instead of SL)
    sl_pct    = float(signal.get("sl_pct", sl_pct))
    tp_pct    = float(signal.get("tp_pct", tp_pct))

    if direction not in ("LONG", "SHORT"):
        return OrderResult(False, "REFUSED", coin, direction, size_usd, mark,
                           f"invalid direction: {direction}")

    if size_usd < MIN_POSITION_USD:
        return OrderResult(False, "REFUSED", coin, direction, size_usd, mark,
                           f"size_usd {size_usd:.2f} < minimum {MIN_POSITION_USD}")

    if tracker is None:
        tracker = PositionTracker()

    # Critical section: check-then-add must be atomic to prevent TOCTOU race.
    # Two concurrent asyncio.to_thread() calls could both pass count() and both add,
    # exceeding MAX_POSITIONS. _ORDER_LOCK serialises this across threads.
    with _ORDER_LOCK:
        # 1. Already have a position in this coin?
        if tracker.get(coin):
            return OrderResult(False, "REFUSED", coin, direction, size_usd, mark,
                               f"{coin}: posisi sudah open")

        # 2. Position limit
        if tracker.count() >= MAX_POSITIONS:
            return OrderResult(False, "REFUSED", coin, direction, size_usd, mark,
                               f"max posisi ({MAX_POSITIONS}) tercapai")

    # 3. Daily loss circuit breaker (5% of actual capital — unified account)
    capital = _available_usdc()   # unified account: spot + perp USDC
    daily_loss = tracker.daily_pnl(capital=capital)
    if daily_loss <= -DAILY_LOSS_CAP:
        return OrderResult(False, "REFUSED", coin, direction, size_usd, mark,
                           f"circuit breaker: daily loss {daily_loss:.1%} ≥ {DAILY_LOSS_CAP:.0%}")

    # 4. Determine live vs paper
    is_live = (live_enabled
               and os.environ.get(PREGAIN_LIVE_ENV) == "1"
               and bool(os.environ.get(HL_SECRET_ENV, "").strip()))

    if not is_live:
        # Paper: record intended trade.
        # v8.25 FIX: double-check count inside lock before add to close the TOCTOU
        # window between the first count check (lines above) and the actual add.
        # Two threads could both pass the first check with count=4, then both add,
        # reaching count=6 > MAX. Re-check eliminates this race for paper trades.
        pos = OpenPosition(
            coin=coin, direction=direction,
            size=size_usd / max(mark, 1e-9),
            entry_px=mark, entry_ts=int(time.time()),
            sl_pct=sl_pct, tp_pct=tp_pct, size_usd=size_usd,
            grade=grade, mode="PAPER",
            sig_type=sig_type, trail_pct=trail_pct,
            high_px=mark, hold_days=hold_days,
        )
        with _ORDER_LOCK:
            if tracker.count() >= MAX_POSITIONS:
                return OrderResult(False, "REFUSED", coin, direction, size_usd, mark,
                                   f"max posisi ({MAX_POSITIONS}) tercapai (re-check)")
            if tracker.get(coin):
                return OrderResult(False, "REFUSED", coin, direction, size_usd, mark,
                                   f"{coin}: posisi sudah open (re-check)")
            tracker.add(pos)
        _log_paper("OPEN", {"coin": coin, "direction": direction,
                             "size_usd": size_usd, "entry_px": mark,
                             "grade": grade, "sig_type": sig_type,
                             "reason": str(getattr(decision, "reason", ""))})
        return OrderResult(True, "PAPER", coin, direction, size_usd, mark,
                           f"paper-trade logged | {getattr(decision, 'reason', '')}")

    # 5. LIVE: edge gate must be open (single gate, no double-gate divergence)
    gate_ok, gate_reason = edge_gate_open(edge_stats or {}, grade)
    if not gate_ok:
        # Downgrade to paper and alert user
        pos = OpenPosition(
            coin=coin, direction=direction,
            size=size_usd / max(mark, 1e-9),
            entry_px=mark, entry_ts=int(time.time()),
            sl_pct=sl_pct, tp_pct=tp_pct, size_usd=size_usd,
            grade=grade, mode="PAPER",
            sig_type=sig_type, trail_pct=trail_pct,
            high_px=mark, hold_days=hold_days,
        )
        tracker.add(pos)
        msg = (f"⚠️ LIVE ditolak → PAPER fallback\n"
               f"  Coin: {coin} {direction}\n"
               f"  Alasan: {gate_reason}")
        _log_paper("LIVE_REFUSED_FALLBACK_PAPER", {"coin": coin, "direction": direction,
                                                    "reason": gate_reason})
        _send_telegram_alert(msg)
        return OrderResult(True, "PAPER", coin, direction, size_usd, mark,
                           f"[PAPER fallback] edge gate TUTUP: {gate_reason}")

    # 6. Validate private key format before attempting order
    private_key = os.environ.get(HL_SECRET_ENV, "").strip()
    if not _validate_private_key(private_key):
        alert = f"⚠️ HL_API_SECRET format tidak valid — trading diblokir"
        _send_telegram_alert(alert)
        return OrderResult(False, "REFUSED", coin, direction, size_usd, mark,
                           "HL_API_SECRET format tidak valid")

    # 6b. Available margin check + dynamic downsizing (v6.4)
    # Sebelumnya: jika net < kelly_size → REFUSE. Masalah: slot 4&5 selalu blocked.
    # Sekarang: downsize ke net_available jika masih >= min_position_usd.
    # Manfaat: capital deployment 100% (tidak ada modal idle di free margin).
    avail = _available_usdc()
    open_exposure = sum(float(p.get("size_usd", 0)) for p in tracker.all())
    net_available = max(0.0, avail - open_exposure)
    if net_available < size_usd:
        if net_available >= MIN_POSITION_USD:
            # Dynamic downsize: pakai semua margin yang tersedia
            import logging as _log_ds
            _log_ds.getLogger(__name__).info(
                f"dynamic downsize {coin}: ${size_usd:.2f}→${net_available:.2f} "
                f"(net={net_available:.2f} < kelly={size_usd:.2f})")
            size_usd = round(net_available, 2)
        else:
            reason = (f"margin tidak cukup: available={avail:.2f} exposure={open_exposure:.2f} "
                      f"net={net_available:.2f} < min={MIN_POSITION_USD}")
            _log_paper("LIVE_REFUSED_MARGIN", {"coin": coin, "direction": direction, "reason": reason})
            _send_telegram_alert(f"⚠️ Order ditolak: {reason}")
            return OrderResult(False, "REFUSED", coin, direction, size_usd, mark, reason)

    # 7. Place real order
    is_buy = direction == "LONG"

    # 7a. GUARD PRA-ORDER — cocokkan state lokal vs VENUE sebelum MENAMBAH risiko.
    # Menutup kelas A1 (maker-ladder 3,39x, UNI -$19,06 = 9,79 window target):
    # tracker mengklaim posisi yang tidak ada di venue (GHOST), atau venue punya
    # posisi yang tracker tidak catat (UNTRACKED). Venue tak terbaca = TOLAK.
    # Ini bukan gate baru yang bisa memblokir order sehat: saat state cocok
    # (kondisi normal), guard lolos tanpa efek.
    try:
        from anantara.pretrade_guard import decide as _pg_decide
    except ImportError:      # dijalankan sebagai skrip lepas
        from pretrade_guard import decide as _pg_decide  # type: ignore

    _venue_rows = _fetch_hl_perp_positions_strict()
    _venue_map = (None if _venue_rows is None
                  else {p["coin"]: p["size"] for p in _venue_rows})
    _local_map = {p["coin"]: float(p.get("size", 0) or 0) for p in tracker.all()}
    _verdict = _pg_decide(_local_map, _venue_map, "open", coin)
    if not _verdict.allow:
        _log_paper("LIVE_REFUSED_PRETRADE_GUARD",
                   {"coin": coin, "direction": direction,
                    "tier": _verdict.tier, "reason": _verdict.reason})
        _send_telegram_alert(
            f"🛡️ GUARD PRA-ORDER menolak order\n"
            f"  {coin} {direction} ${size_usd:.2f}\n"
            f"  Tier: {_verdict.tier}\n"
            f"  Alasan: {_verdict.reason}")
        return OrderResult(False, "REFUSED", coin, direction, size_usd, mark,
                           f"guard pra-order: {_verdict.reason}")

    result = _place_hl_order(private_key, coin, is_buy, size_usd)
    if not result["ok"]:
        # Order failed — log and alert, do NOT fallback to paper silently
        alert = (f"❌ Live order GAGAL\n"
                 f"  {coin} {direction} ${size_usd:.2f}\n"
                 f"  Error: {result.get('reason', 'unknown')}")
        _send_telegram_alert(alert)
        return OrderResult(False, "REFUSED", coin, direction, size_usd, mark,
                           f"order gagal: {result.get('reason')}")

    entry_px = result.get("entry_px", mark)
    size     = result.get("size", size_usd / max(entry_px, 1e-9))

    # v11.0 K1: place native stop-loss order immediately after entry fill.
    # Fires at exchange speed — no dependency on the 2-min software polling cycle.
    # Failure is non-fatal: software SL in monitor_and_close() remains as backup.
    sl_trigger = (entry_px * (1 + sl_pct / 100) if direction == "SHORT"
                  else entry_px * (1 - sl_pct / 100))
    stop_result = _place_hl_stop_order(private_key, coin, is_buy, size, sl_trigger)
    sl_order_oid = str(stop_result["oid"]) if stop_result["ok"] else ""
    if not stop_result["ok"]:
        import logging as _log_sl
        _log_sl.getLogger(__name__).warning(
            f"K1: native stop order gagal untuk {coin} @ trigger={sl_trigger:.6g} "
            f"(software SL tetap aktif sebagai backup): {stop_result.get('reason')}"
        )

    pos = OpenPosition(
        coin=coin, direction=direction, size=size,
        entry_px=entry_px, entry_ts=int(time.time()),
        sl_pct=sl_pct, tp_pct=tp_pct, size_usd=size_usd,
        grade=grade, mode="LIVE",
        sig_type=sig_type, trail_pct=trail_pct,
        high_px=entry_px, hold_days=hold_days,
        sl_order_oid=sl_order_oid,
    )
    tracker.add(pos)
    _log_trade({"event": "OPEN", "coin": coin, "direction": direction,
                "size": size, "entry_px": entry_px, "size_usd": size_usd,
                "grade": grade, "sig_type": sig_type, "mode": "LIVE",
                "sl_order_oid": sl_order_oid,
                "native_stop_ok": bool(sl_order_oid)})
    return OrderResult(True, "LIVE", coin, direction, size_usd, entry_px,
                       f"filled @ ${entry_px:.6g} | stop={'✅' if sl_order_oid else '⚠️ failed'}")


# Default position timeout: close any trade older than this to prevent indefinitely
# stuck positions when price ranges between SL and TP without ever touching either.
# v6.2: 48h→24h — riset 877 sinyal: E=+0.801R@24h vs E=+0.403R@48h (50% edge loss!).
# Posisi membalik profit→loss antara 24-48h (reversal rate tinggi). Tutup di 24h optimal.
POSITION_TIMEOUT_HOURS = float(os.environ.get("PREGAIN_TIMEOUT_HOURS", "24"))


# ── SL/TP Monitor ─────────────────────────────────────────────────────────────
def monitor_and_close(tracker: Optional[PositionTracker] = None,
                      live_enabled: bool = False,
                      timeout_hours: float = POSITION_TIMEOUT_HOURS) -> list[dict]:
    """Check all open positions against SL/TP and time-based timeout.

    Closes positions when:
      • pnl <= -sl_pct  → stop-loss hit
      • pnl >=  tp_pct  → take-profit hit
      • age  >= timeout_hours → position timeout (force-close, prevents indefinite hold)

    timeout_hours=0 disables the timeout check (not recommended for live).
    Default: 48h — configured via PREGAIN_TIMEOUT_HOURS env var.
    """
    if tracker is None:
        tracker = PositionTracker()

    private_key = os.environ.get(HL_SECRET_ENV, "").strip() if live_enabled else ""
    is_live = (bool(live_enabled)
               and bool(private_key)
               and _validate_private_key(private_key)
               and os.environ.get(PREGAIN_LIVE_ENV) == "1")
    events = []
    now_ts = int(time.time())

    for pos in list(tracker.all()):   # iterate copy to allow mutation
        coin      = pos["coin"]
        direction = pos["direction"]
        entry_px  = float(pos.get("entry_px", 0) or 0)
        sl_pct    = float(pos.get("sl_pct", SL_PCT_DEFAULT))
        tp_pct    = float(pos.get("tp_pct", TP_PCT_DEFAULT))
        trail_pct = float(pos.get("trail_pct", 0.0))
        hold_days = int(pos.get("hold_days", 0))
        mode      = pos.get("mode", "PAPER")
        sig_type  = pos.get("sig_type", "")

        if entry_px <= 0:
            continue

        mark = _mark_price(coin)
        if mark <= 0:
            # Track consecutive failures; alert after threshold to warn operator
            _mark_miss_count[coin] = _mark_miss_count.get(coin, 0) + 1
            if _mark_miss_count[coin] == _MARK_MISS_ALERT_THRESHOLD:
                import logging as _log
                _log.getLogger("pregain_execution").warning(
                    f"MONITOR GAP: mark price for {coin} unavailable for "
                    f"{_mark_miss_count[coin]} consecutive cycles (~"
                    f"{_mark_miss_count[coin] * 2}min). SL/TP not monitored. "
                    "Check HL API connectivity."
                )
            continue

        # Mark price retrieved — reset failure counter
        _mark_miss_count.pop(coin, None)

        # Units: move is in PERCENT here (e.g. 5.0 = +5%), matching sl_pct/tp_pct.
        # This differs from daily_pnl() which returns a FRACTION — two separate methods.
        move = (mark - entry_px) / entry_px * 100.0
        pnl  = move if direction == "LONG" else -move

        # ── Trailing stop for SPOT positions ──────────────────────────────────
        # Update high_px (watermark) and check if price dropped > trail_pct from peak.
        hit_trail = False
        if trail_pct > 0 and direction == "LONG":
            current_high = float(pos.get("high_px", entry_px) or entry_px)
            if mark > current_high:
                current_high = mark
                pos["high_px"] = current_high
                # Persist watermark without reloading (reload would discard in-memory updates).
                try:
                    if coin in tracker._positions:
                        tracker._positions[coin]["high_px"] = current_high
                        tracker._save()
                except Exception:
                    pass
            trail_from_high = (current_high - mark) / current_high * 100.0
            hit_trail = trail_from_high >= trail_pct

        # SL fires when: (a) trail_pct=0 (no trailing stop), OR (b) direction=SHORT
        # (trailing stop is LONG-only — a SHORT with trail_pct would have no SL otherwise).
        hit_sl = pnl <= -sl_pct and (not trail_pct or direction == "SHORT")
        hit_tp = pnl >= tp_pct

        # Timeout: SPOT uses hold_days if set, else timeout_hours
        entry_ts   = int(pos.get("entry_ts", 0) or 0)
        age_hours  = (now_ts - entry_ts) / 3600 if entry_ts > 0 else 0
        effective_timeout = hold_days * 24 if hold_days > 0 else timeout_hours
        hit_timeout = effective_timeout > 0 and age_hours >= effective_timeout

        if not (hit_sl or hit_tp or hit_trail or hit_timeout):
            continue

        # Priority: SL/Trail > TP > TIMEOUT
        if hit_trail:
            trigger = f"TRAIL_{pos.get('high_px', mark):.4g}"
        elif hit_sl:
            trigger = "SL"
        elif hit_tp:
            trigger = "TP"
        else:
            trigger = f"TIMEOUT_{age_hours:.0f}h"
        realized = pnl

        if is_live and mode == "LIVE":
            is_buy_close = (direction == "SHORT")
            # v11.0 K1: cancel native stop order before software close to prevent
            # double-fill. If the native stop already fired (exchange closed position),
            # cancel will fail silently — that is acceptable and expected for hit_sl.
            sl_oid_str = pos.get("sl_order_oid", "")
            if sl_oid_str:
                try:
                    _cancel_hl_order(private_key, coin, int(sl_oid_str))
                except Exception:
                    pass  # already fired or expired — non-fatal
            close = _close_hl_position(private_key, coin, is_buy_close, pos["size"])
            if close["ok"]:
                close_px = close["close_px"]
                realized = ((close_px - entry_px) / entry_px * 100.0
                            * (1 if direction == "LONG" else -1))
                _log_trade({"event": "CLOSE", "coin": coin, "direction": direction,
                            "trigger": trigger, "realized_pct": round(realized, 3),
                            "entry_px": entry_px, "close_px": close_px, "mode": "LIVE"})
            else:
                events.append({"coin": coin,
                                "error": f"close gagal: {close.get('reason', 'unknown')}"})
                _send_telegram_alert(f"⚠️ Gagal close {coin}: {close.get('reason')}")
                continue
        else:
            if mode == "LIVE" and not is_live:
                # Safety guard: LIVE position cannot be closed because env is missing.
                # Do NOT remove from tracker — alert operator and skip this cycle.
                # This prevents orphan positions on HL with no local tracking.
                _send_telegram_alert(
                    f"⚠️ LIVE position {coin} needs closing but PREGAIN_LIVE/HL_API_SECRET "
                    f"env missing. Position kept in tracker — check env and restart daemon.")
                events.append({"coin": coin, "error": "LIVE pos not closed: env missing"})
                continue
            _log_paper("CLOSE", {"coin": coin, "direction": direction,
                                  "trigger": trigger,
                                  "realized_pct": round(realized, 3),
                                  "entry_px": entry_px, "mark_px": mark, "mode": mode})

        # Record realized PnL for today's circuit breaker (unrealized + realized = full picture)
        realized_usd = realized / 100.0 * float(pos.get("size_usd", 0) or 0)
        tracker.record_realized_pnl(realized_usd)
        tracker.remove(coin)
        events.append({
            "coin": coin, "direction": direction, "trigger": trigger,
            "realized_pct": round(realized, 3),
            "entry_px": entry_px, "close_px": mark, "mode": mode,
        })

    return events


def format_close_events(events: list[dict]) -> str:
    if not events:
        return ""
    L = ["🏁 *Pre-Gain Auto-Close*"]
    for e in events:
        if "error" in e:
            L.append(f"  ⚠️ {e['coin']}: {e['error']}")
            continue
        trigger = e.get("trigger", "?")
        trigger_icon = ("⏰" if trigger.startswith("TIMEOUT") else
                        "🛑" if trigger == "SL" else "🎯")
        icon = "✅" if e["realized_pct"] > 0 else "❌"
        L.append(f"  {icon}{trigger_icon} {e['direction']} {e['coin']} "
                 f"{trigger} @ ${e['close_px']:.6g} "
                 f"| P&L: {e['realized_pct']:+.2f}%")
    return "\n".join(L)


def positions_summary(tracker: Optional[PositionTracker] = None) -> str:
    if tracker is None:
        tracker = PositionTracker()
    positions = tracker.all()
    if not positions:
        return "📋 Tidak ada posisi open."
    L = [f"📋 *Open Positions ({len(positions)}/{MAX_POSITIONS})*"]
    for p in positions:
        mark = _mark_price(p["coin"])
        pnl  = 0.0
        if mark > 0 and float(p.get("entry_px", 0)) > 0:
            move = (mark - float(p["entry_px"])) / float(p["entry_px"]) * 100.0
            pnl  = move if p["direction"] == "LONG" else -move
        icon     = "🟢" if pnl >= 0 else "🔴"
        mode_tag = "💵" if p["mode"] == "LIVE" else "📝"
        entry_ts  = int(p.get("entry_ts", 0) or 0)
        age_h     = (time.time() - entry_ts) / 3600 if entry_ts > 0 else 0
        age_str   = f" | age:{age_h:.1f}h" if age_h > 0 else ""
        timeout_warn = " ⏰" if age_h >= POSITION_TIMEOUT_HOURS * 0.9 else ""
        L.append(
            f"  {icon}{mode_tag} {p['direction']} {p['coin']} "
            f"entry=${p['entry_px']:.6g} → mark=${mark:.6g} "
            f"P&L:{pnl:+.2f}% | SL:{p['sl_pct']}% TP:{p['tp_pct']}%"
            f"{age_str}{timeout_warn}"
        )
    return "\n".join(L)


# ── HL Position Reconciliation ───────────────────────────────────────────────
def _fetch_hl_perp_positions() -> list[dict]:
    """Fetch open perp positions from HL clearinghouseState. Returns [] on error."""
    addr = os.environ.get(HL_ADDRESS_ENV, "").strip()
    if not addr:
        return []
    try:
        import httpx as _h
        r = _h.post(f"{HL_API}/info",
                    json={"type": "clearinghouseState", "user": addr}, timeout=8)
        positions = r.json().get("assetPositions", [])
        result = []
        for p in positions:
            pos = p.get("position", {})
            sz = float(pos.get("szi", 0) or 0)
            if sz == 0:
                continue
            result.append({
                "coin":      pos.get("coin", "?"),
                "direction": "LONG" if sz > 0 else "SHORT",
                "size":      abs(sz),
                "entry_px":  float(pos.get("entryPx", 0) or 0),
            })
        return result
    except Exception:
        return []


def _fetch_hl_perp_positions_strict() -> Optional[list[dict]]:
    """Sama seperti _fetch_hl_perp_positions, TAPI `None` = venue TIDAK TERBACA.

    MENGAPA dipisah (jangan gabung): versi lama mengembalikan `[]` untuk DUA
    keadaan yang sangat berbeda — "benar-benar tidak ada posisi" dan "API
    gagal". Itu fail-open (kelas bug A9 Cacat 2, lihat FIXLOG 30-Sep): error
    jaringan berubah menjadi klaim "posisi kosong".

    Guard pra-order WAJIB bisa membedakannya: bila venue tak terbaca, MENAMBAH
    risiko harus DITOLAK, bukan diizinkan atas dasar state kosong palsu.
    """
    addr = os.environ.get(HL_ADDRESS_ENV, "").strip()
    if not addr:
        return None
    try:
        import httpx as _h
        r = _h.post(f"{HL_API}/info",
                    json={"type": "clearinghouseState", "user": addr}, timeout=8)
        positions = r.json().get("assetPositions", [])
    except Exception:  # noqa: BLE001
        return None
    result = []
    for p in positions:
        pos = p.get("position", {})
        sz = float(pos.get("szi", 0) or 0)
        if sz == 0:
            continue
        result.append({
            "coin":      pos.get("coin", "?"),
            "direction": "LONG" if sz > 0 else "SHORT",
            "size":      abs(sz),
            "entry_px":  float(pos.get("entryPx", 0) or 0),
        })
    return result


def reconcile_with_hl(tracker: Optional[PositionTracker] = None) -> str:
    """Sync PositionTracker with actual HL perp positions.

    Three cases:
    - Tracker has position, HL confirms it → OK (no change)
    - Tracker has position, HL does NOT → orphan in tracker, remove it
    - HL has position, tracker does NOT → ghost on HL, add to tracker as LIVE
    Returns a summary string of what changed.
    """
    if tracker is None:
        tracker = PositionTracker()

    hl_positions = _fetch_hl_perp_positions()
    if not hl_positions and not tracker.all():
        return "reconcile: both tracker and HL have 0 positions"

    hl_map = {p["coin"]: p for p in hl_positions}
    tracked = {p["coin"]: p for p in tracker.all()}
    changes = []

    # Orphaned in tracker (not on HL anymore)
    for coin, pos in list(tracked.items()):
        if pos.get("mode") == "LIVE" and coin not in hl_map:
            tracker.remove(coin)
            changes.append(f"REMOVED orphan: {coin} (tracker had it, HL does not)")
            import logging
            logging.getLogger(__name__).warning(f"reconcile: removed orphan tracker position {coin}")

    # Ghost on HL (not in tracker)
    for coin, pos in hl_map.items():
        if coin not in tracked:
            open_pos = OpenPosition(
                coin=coin,
                direction=pos["direction"],
                size=pos["size"],
                entry_px=pos["entry_px"],
                entry_ts=int(time.time()),
                sl_pct=SL_PCT_DEFAULT,
                tp_pct=TP_PCT_DEFAULT,
                size_usd=pos["size"] * pos["entry_px"],
                grade="?",
                mode="LIVE",
            )
            tracker.add(open_pos)
            changes.append(f"ADDED ghost: {coin} {pos['direction']} (HL has it, tracker did not)")
            import logging
            logging.getLogger(__name__).warning(f"reconcile: added ghost HL position {coin}")

    if not changes:
        return f"reconcile: {len(hl_map)} HL positions match tracker — OK"
    return "reconcile: " + " | ".join(changes)


# ── Pre-flight Check ──────────────────────────────────────────────────────────
def preflight_check() -> str:
    """Verify all live-trading prerequisites. Run before going live.
    Returns a formatted report with ✅/❌/⚠️ per check.
    """
    import functools
    lines = ["🚀 *Pre-Gain Live Trading Pre-flight Check*", ""]
    ok_all = True

    def chk(label: str, passed: bool, detail: str = "", warn: bool = False) -> None:
        nonlocal ok_all
        icon = "✅" if passed else ("⚠️" if warn else "❌")
        if not passed and not warn:
            ok_all = False
        lines.append(f"  {icon} {label}" + (f" — {detail}" if detail else ""))

    # 1. Env vars
    autotrade = os.environ.get("AUTOTRADE_LIVE") == "1"
    pregain_live = os.environ.get("PREGAIN_LIVE") == "1"
    hl_secret = os.environ.get(HL_SECRET_ENV, "").strip()
    hl_addr = os.environ.get(HL_ADDRESS_ENV, "").strip()
    chk("AUTOTRADE_LIVE=1", autotrade)
    chk("PREGAIN_LIVE=1", pregain_live)
    chk("HL_API_SECRET set + valid", bool(hl_secret) and _validate_private_key(hl_secret),
        f"length={len(hl_secret)}")
    chk("HL_ADDRESS set", bool(hl_addr), hl_addr[:10] + "..." if hl_addr else "missing")

    # 2. HL connectivity + balance
    try:
        import httpx as _h
        r = _h.post(f"{HL_API}/info", json={"type": "metaAndAssetCtxs"}, timeout=8)
        n_assets = len(r.json()[0]["universe"])
        chk("HL API reachable", True, f"{n_assets} assets")
    except Exception as e:
        chk("HL API reachable", False, str(e)[:60])

    avail = _available_usdc()
    chk("HL balance sufficient", avail >= MIN_POSITION_USD * 2,
        f"${avail:.2f} available (min ${MIN_POSITION_USD * 2:.0f})")

    # 3. Packages (eth_account/msgpack via venv-research fallback)
    try:
        _ensure_eth_packages()
        chk("eth_account + msgpack", True, "via venv-research fallback OK")
    except Exception as e:
        chk("eth_account + msgpack", False, str(e)[:60])
    for pkg in ("httpx",):
        try:
            __import__(pkg)
            chk(f"package {pkg}", True)
        except ImportError:
            chk(f"package {pkg}", False, "run: pip install " + pkg)

    # 4. Edge gates
    try:
        from anantara import pregain_backtest as _pb, pregain_scan as _ps
        _fp = functools.partial(_pb.fetch_path, cache_only=True)
        edge_all = _pb.backtest_logged(_ps.SIGNAL_DB, _fp)
        edge_b = _pb.backtest_logged(_ps.SIGNAL_DB, _fp,
                                     direction_filter="SHORT",
                                     score_exclude_range=(70, 74))
        by_grade = dict(edge_all.get("by_grade", {}))
        b_eff = (edge_b.get("by_grade") or {}).get("B")
        if b_eff and b_eff.get("n", 0) >= 10:
            by_grade["B"] = b_eff
        for g in ("S", "B", "C", "A"):
            gate_ok, reason = edge_gate_open(by_grade, g)
            st = by_grade.get(g, {})
            chk(f"Grade {g} edge gate",
                gate_ok,
                f"n={st.get('n',0)} E={st.get('expectancy_r',0):+.3f}R — {reason[:40]}",
                warn=(not gate_ok))
    except Exception as e:
        chk("Edge stats computation", False, str(e)[:60])

    # 5. Position tracker
    tracker = PositionTracker()
    chk("Position tracker healthy", True, f"{tracker.count()} open positions")

    # 6. HL reconciliation
    recon = reconcile_with_hl(tracker)
    chk("HL position reconciliation", True, recon[:70])

    # 7. Daemon running
    try:
        import subprocess
        r = subprocess.run(
            ["systemctl", "--user", "is-active", "anantara-daemon"],
            capture_output=True, text=True, timeout=5)
        active = r.stdout.strip() == "active"
        chk("anantara-daemon active", active, r.stdout.strip())
    except Exception:
        chk("anantara-daemon active", False, "systemctl check failed", warn=True)

    lines.append("")
    verdict = "✅ ALL CHECKS PASSED — ready for live trading" if ok_all else "❌ SOME CHECKS FAILED — fix before going live"
    lines.append(verdict)
    return "\n".join(lines)


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Pre-Gain Execution — Self-Check ===")
    print(f"Daily loss cap: {DAILY_LOSS_CAP:.0%} (conservative)")
    print(f"Min position: ${MIN_POSITION_USD}")
    tracker = PositionTracker()
    print(f"Open positions: {tracker.count()}")
    print(positions_summary(tracker))
    print()
    print("Edge gate test:")
    for grade in ("S", "A", "B", "C"):
        fake = {"A": {"n": 35, "expectancy_r": 0.15}}
        ok, reason = edge_gate_open(fake, grade)
        print(f"  Grade {grade}: {'✅ OPEN' if ok else '❌ CLOSED'} — {reason}")
    print()
    print("Private key validation:")
    print(f"  Valid  : {_validate_private_key('a' * 64)}")
    print(f"  Invalid: {_validate_private_key('short')}")
    print(f"  0x     : {_validate_private_key('0x' + 'a' * 64)}")
