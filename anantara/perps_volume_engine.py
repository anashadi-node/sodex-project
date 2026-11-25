#!/usr/bin/env python3
"""Perps Volume Engine v3 — Taker execution, guaranteed fills (2026-06-28)

v3 FIX: Limit-IOC at bid/ask (same side as book) is cancelled by exchange without
filling — returns valid oid but never crosses spread → phantom fill. Switching to
TAKER prices (BUY@ask / SELL@bid) guarantees real SoDEX-counted fills.
Cost per RT = spread + 2×fee, capped by TE_PVE_DAILY_LOSS ($5 default).

v3 CHANGES vs v2:
  - BUY placed at ASK → crosses spread → taker fill (guaranteed)
  - SELL placed at BID → crosses spread → taker fill (guaranteed)
  - direction="auto": BEAR regime → SHORT, BULL/NEUTRAL → LONG
  - multi-pair: TE_PVE_PAIRS=SPCX-USD,CHZ-USD,...

Strategy per tick:
  LONG mode: BUY @ ask → SELL @ bid (taker; BULL adds directional profit)
  SHORT mode: SELL @ bid → BUY @ ask (taker; BEAR adds directional profit)

Risk Controls:
  - Max position: $130 notional (configurable)
  - Max inventory age: 5 menit → force close
  - Daily loss limit: $5 → auto-pause
  - Cooldown: 300s between trades per pair (conservative $1.3M/wk target)
  - Regime-aware: auto-selects direction from intel JSONL

INTEGRATION: Called from Orchestrator loop (every ~10 iterations per pair).
Enable via TE_PVE_ENABLED=1.
"""

import json, logging, os, time
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from typing import Optional

PROJECT = Path(os.environ.get("ANANTARA_DIR", str(Path(__file__).resolve().parent.parent)))
PVE_PAUSE_FILE = PROJECT / "data" / "PVE_PAUSE"

# ── Config defaults (override via env) ──
PVE_ENABLED = os.environ.get("TE_PVE_ENABLED", "0") == "1"
PVE_PAIRS = os.environ.get("TE_PVE_PAIRS", "SPCX-USD")  # comma-separated
PVE_MAX_NOTIONAL = D(os.environ.get("TE_PVE_MAX_NOTIONAL", "30"))
PVE_COOLDOWN_S = float(os.environ.get("TE_PVE_COOLDOWN", "5"))
PVE_MAX_AGE_MINUTES = int(os.environ.get("TE_PVE_MAX_AGE", "5"))
PVE_DAILY_LOSS_LIMIT = D(os.environ.get("TE_PVE_DAILY_LOSS", "5"))
PVE_MIN_SPREAD_PCT = D(os.environ.get("TE_PVE_MIN_SPREAD", "0.03"))  # 0.03% = 3× maker fee
PVE_DIRECTION = os.environ.get("TE_PVE_DIRECTION", "auto")  # "long", "short", "auto"
# Fill reconciliation (Upgrade #1): verify IOC fills via real position delta.
# Default ON — set to "0" only if the positions CLI is flaky enough to false-flag.
PVE_VERIFY_FILLS = os.environ.get("TE_PVE_VERIFY_FILLS", "1") == "1"
# Settle window: a real taker IOC fill may not show in `positions` instantly.
# Poll a few times before declaring phantom, so settle-lag never mis-flags a real
# fill (which on open would double-open next tick). 0s in tests = instant.
PVE_FILL_SETTLE_SEC = float(os.environ.get("TE_PVE_FILL_SETTLE_SEC", "1.0"))
PVE_FILL_SETTLE_TRIES = int(os.environ.get("TE_PVE_FILL_SETTLE_TRIES", "3"))

# F3a (2026-06-29): REGIME PAUSE GATE — insight operator: E1/E2 RUSAK saat BEAR
# (trade rugi terlepas arah karena adverse selection di trending market). Saat regime
# BEAR terdeteksi (intel BTC_dir<0 conf≥0.55), PVE PAUSE total (skip semua trade).
# Hanya aktif trade di BULL/NEUTRAL (kondisi sideways/up dimana E1/E2 historis bagus).
# Default ON (regime-aware). Set "0" untuk trade di semua regime (legacy behavior).
PVE_PAUSE_ON_BEAR = os.environ.get("TE_PVE_PAUSE_ON_BEAR", "1") == "1"

# F3b (2026-06-29): GOVERNOR EV GATE — wire sodex_governor.evaluate_roundtrip() to
# PVE tick. Block trades with negative expectancy (RC-2 fix). Governor needs model_prob
# (from sodex-model:8001 if available, else conservative default), win_rate/avg_win/
# avg_loss (from recent RT history), spread/depth (from book), fee (maker/taker).
PVE_GOVERNOR_GATE = os.environ.get("TE_PVE_GOVERNOR_GATE", "1") == "1"
PVE_MODEL_URL = os.environ.get("TE_PVE_MODEL_URL", "http://localhost:8001")  # LightGBM dir
PVE_MODEL_FALLBACK_PROB = float(os.environ.get("TE_PVE_MODEL_FALLBACK_PROB", "0.55"))
PVE_GOV_MIN_RR = float(os.environ.get("TE_PVE_GOV_MIN_RR", "1.3"))  # min reward:risk

# F3d (2026-06-29): WEEKLY NET KILL-SWITCH — jalan tengah governor ketat vs volume.
# Governor EV gate (F3b) terlalu ketat untuk modal/edge saat ini (reject semua pair).
# Jalan tengah: allow trading (volume), tapi auto-PAUSE jika NET mingguan < threshold.
# NET = total_pnl - total_fee, di-reset tiap snapshot Sabtu 07:00 WIB.
# Threshold -3% dari modal baseline ( bleeding terkendali sebelum pause).
PVE_WEEKLY_NET_KILL = os.environ.get("TE_PVE_WEEKLY_NET_KILL", "1") == "1"
PVE_WEEKLY_NET_FLOOR = D(os.environ.get("TE_PVE_WEEKLY_NET_FLOOR", "-25"))  # -$25/week cap
PVE_DB_PATH = Path(os.environ.get("TE_PVE_DB_PATH", str(PROJECT / "twin_engine.db")))
PVE_BLOCKED_PAIRS = {
    p.strip().upper()
    for p in os.environ.get("TE_PVE_BLOCKED_PAIRS", "CHZ-USD").split(",")
    if p.strip()
}

# ── F1 (2026-06-29): MAKER path (post-only GTC inside-spread) ──
# Maker fee 0.012%/side vs taker 0.04%/side = 70% fee saving + rebate tier potential.
# Maker path places post-only (GTX) limit INSIDE the spread: BUY@bid−offset, SELL@ask+offset.
# oid=0 from GTX = order would cross → exchange rejects cleanly (no ghost, verified live).
PVE_MAKER_PATH = os.environ.get("TE_PVE_MAKER_PATH", "0") == "1"  # OFF by default (opt-in)
PVE_MAKER_OFFSET_TICKS = D(os.environ.get("TE_PVE_MAKER_OFFSET_TICKS", "2"))  # ticks inside
PVE_MAKER_FEE_PCT = D(os.environ.get("TE_PVE_MAKER_FEE", "0.012"))  # 0.012% per side
PVE_MAKER_TAKER_FALLBACK = os.environ.get("TE_PVE_MAKER_TAKER_FALLBACK", "0") == "1"
PVE_HONEST_RATIO_GUARD = os.environ.get("TE_PVE_HONEST_RATIO_GUARD", "1") == "1"
PVE_HONEST_RATIO_FLOOR = D(
    os.environ.get("HONEST_RATIO_FLOOR", "8000").split("#", 1)[0].strip())
PVE_HONEST_STATE_FILE = Path(os.environ.get(
    "TE_PVE_HONEST_STATE_FILE", str(PROJECT / "data" / "honest_ratio_experiment.json")))
PVE_HONEST_RECOVERY_MODE = os.environ.get("TE_PVE_HONEST_RECOVERY_MODE", "0") == "1"
PVE_HONEST_RECOVERY_HEADROOM = D(os.environ.get(
    "TE_PVE_HONEST_RECOVERY_HEADROOM", "1.05").split("#", 1)[0].strip())
PVE_HONEST_RECOVERY_MAX_DROP_BPS = D(os.environ.get(
    "TE_PVE_HONEST_RECOVERY_MAX_DROP_BPS", "10").split("#", 1)[0].strip())
PVE_HONEST_RECOVERY_MIN_CAPTURE_BPS = D(os.environ.get(
    "TE_PVE_HONEST_RECOVERY_MIN_CAPTURE_BPS", "3.0").split("#", 1)[0].strip())

# ── RC2 fix (2026-07-18): PER-PAIR DRIFT VETO — the Jul-17 loss mechanism ──
# ROOT CAUSE (verified across 4 independent audits + realized-price calibration):
# _effective_direction() resolves "auto" → short/long from the BTC regime, NOT the
# traded pair's own trend. On Jul-17 SOL was rallying (calibration base_rate 0.286 =
# price ROSE 71% at 30m) while BTC momentum read BEAR → PVE SHORTed a rising SOL →
# adverse fills stacked on fees. This is a DEFENSIVE veto: it blocks ONLY the clearly
# adverse open (SHORT into a rising pair / LONG into a falling pair). When the pair
# has no clear drift (FLAT) it does NOT veto — the volume-farm doctrine is that
# direction may be coin-flip (the TA gate has NO proven directional edge, so we only
# avoid the adverse case, we do not try to predict). Uses the pair's OWN realtime 1h
# momentum (always fresh) — same proven EMA20/EMA50+ROC mechanism as _regime(), which
# is why it is more robust than a stale historical base_rate. Fail-open on data error.
PVE_DRIFT_VETO = os.environ.get("TE_PVE_DRIFT_VETO", "1") == "1"  # ON by default (defense)
PVE_DRIFT_ROC = float(os.environ.get("TE_PVE_DRIFT_ROC", "0.3"))  # % ROC1h to call a drift

# ── U3 (2026-07-18): FEE-AWARE MIN-CAPTURE GATE — profit-by-construction ──
# The doctrine is "volume is a RESULT of profitability" (no breakeven/wash farming).
# The legacy _maker_viable() returned True on ANY positive spread ("fee-saving mode"),
# which posts quotes where the captured spread < round-trip fee → every such RT is a
# NET LOSS (just smaller than a taker's). That silently erodes the honest ratio and
# breaks the >69%-profitable target. U3 requires the captured spread to exceed the RT
# fee by at least MIN_CAPTURE_BPS, so each posted RT is net-positive by construction →
# account value does not bleed → honest ratio stays high (the 1:11,000 goal). It also
# EXPOSES which pairs are farmable: a tight perp (SOL ~1.3 bps spread vs 2.4 bps RT
# fee) simply will not pass — profitable maker farming needs wider-spread pairs.
#   net_capture_bps = spread_bps − rt_fee_bps ;  post only if net_capture_bps ≥ floor
# Default 0.0 = backward-compatible legacy (fee-saving). Set >0 (e.g. 1.0) to enforce
# profit-capture — recommended, and set in .env for the live farm.
PVE_MIN_CAPTURE_BPS = float(os.environ.get("TE_PVE_MIN_CAPTURE_BPS", "0.0"))

# ── U4 (2026-07-18): ADVERSE-SELECTION GATE (OBI + L1 depth) ──
# Wide-spread pairs are farmable (U3) but wide spread often = THIN book = high adverse
# selection: your maker quote is a free option for informed flow. Two defensive checks
# before OPENing, from the L1 orderbook we can read now (no WebSocket):
#   1. L1 depth: if min(bid,ask) notional < MIN_L1_DEPTH_USD → book too thin → skip.
#   2. OBI = (bid_qty−ask_qty)/(bid_qty+ask_qty): if strongly AGAINST our fill side,
#      skip (opening a BUY into heavy sell pressure = filled right before price drops).
# HONEST CAVEAT: static OBI is a WEAK predictor (prior SoDEX research: "static OBI
# dead; cumOFI = lead"). So this fires only on EXTREME imbalance (|OBI|≥threshold) as a
# coarse backstop — true tick-level OFI/VPIN needs the U1 WebSocket recorder (not built).
# CLOSE is never gated (exit always allowed). Fail-open on any read error.
PVE_ADVERSE_GATE = os.environ.get("TE_PVE_ADVERSE_GATE", "1") == "1"  # ON by default
PVE_OBI_ADVERSE = float(os.environ.get("TE_PVE_OBI_ADVERSE", "0.6"))  # |OBI| extreme floor
PVE_MIN_L1_DEPTH_USD = float(os.environ.get("TE_PVE_MIN_L1_DEPTH_USD", "300"))  # thin-book floor
# OFI upgrade (U1→U4): when the microstructure recorder (sodex_book_recorder) has
# accumulated ≥ MIN_SNAPS L1 snapshots for the pair, use real cumulative OFI (a genuine
# order-FLOW signal, per Cont-Kukanov-Stoikov) as the PRIMARY adverse signal instead of
# the weaker static OBI. ofi_norm = OFI / mean_L1_depth (dimensionless "depth-equivalents"
# of net flow). Falls back to static OBI when the recorder has too little data.
PVE_OFI_ADVERSE = float(os.environ.get("TE_PVE_OFI_ADVERSE", "1.5"))  # depth-equiv flow floor
PVE_OFI_MIN_SNAPS = int(os.environ.get("TE_PVE_OFI_MIN_SNAPS", "5"))  # min snaps to trust OFI
PVE_OFI_WINDOW_S = float(os.environ.get("TE_PVE_OFI_WINDOW_S", "90"))  # OFI lookback seconds
PVE_BOOK_DB = os.environ.get("TE_PVE_BOOK_DB", str(PROJECT / "data" / "sodex_book_recorder.db"))

# ── ADAPTIVE MODE (2026-07-19): trade WITH the current trend on the selected assets ──
# Operator principle: in any regime there is always a trending asset; farming WITH its
# trend makes the directional MTM a tailwind (positions win → offset fee → ratio ↑). The
# adaptive selector (scripts/sodex_adaptive_selector.py) picks, each cycle, the strongest
# trending farmable pairs + their with-trend direction and writes them to a JSON file.
# When ADAPTIVE is on, PVE reads that file: it OPENS this pair only if it is currently
# selected, and in the selector's direction (overriding auto/BTC regime). If the pair is
# not selected (no clear trend) or the file is stale, PVE skips opening it (no forcing a
# trade with no tailwind). This is trend-FOLLOWING (reaction), not prediction.
PVE_ADAPTIVE = os.environ.get("TE_PVE_ADAPTIVE", "0") == "1"
PVE_ADAPTIVE_FILE = os.environ.get("TE_PVE_ADAPTIVE_FILE", str(PROJECT / "data" / "sodex_adaptive_selection.json"))
PVE_ADAPTIVE_MAX_AGE = float(os.environ.get("TE_PVE_ADAPTIVE_MAX_AGE", "900"))  # 15-min freshness


class PerpsVolumeEngine:
    """Regime-adaptive perps market maker (limit-IOC, multi-pair).

    LONG mode (BULL/NEUTRAL): BUY @ ask → SELL @ bid  (taker, guaranteed fill)
    SHORT mode (BEAR):         SELL @ bid → BUY @ ask  (taker, guaranteed fill)
    Both modes pay spread as farming cost; directional mode adds price-move alpha.
    """

    def __init__(self, adapter, ledger, pair: str = "SPCX-USD", direction: str | None = None):
        self.x = adapter
        self.led = ledger
        self.pair = pair
        self.direction = direction or PVE_DIRECTION  # "long", "short", or "auto"
        self._sodex_bin = str(PROJECT / "bin" / "sodex")
        # ponytail: 5-min regime cache — avoid hitting intel JSONL every tick
        self._regime_cache: str = "NEUTRAL"
        self._regime_cache_ts: float = 0.0
        # RC2 fix: 5-min OWN-pair drift cache (RISING/FALLING/FLAT) for _drift_veto.
        self._drift_cache: str = "FLAT"
        self._drift_cache_ts: float = 0.0
        # U4: short-lived L1 OBI/depth cache. Default (neutral OBI, inf depth) = fail-open.
        self._obi_cache: tuple = (0.0, float("inf"))
        self._obi_cache_ts: float = 0.0
        
        # ── Per-instance state ──
        self.inv_qty: D = D(0)           # current token inventory
        self.inv_cost: D = D(0)          # total cost basis (USDC)
        self._inventory_direction: str | None = None  # side of verified real exposure
        self._last_order_ts: float = 0.0
        self._last_fill_check_ts: float = 0.0
        self._daily_loss: D = D(0)
        self._daily_loss_date: str = ""
        self._paused: bool = False
        self._total_rt: int = 0
        self._total_pnl: D = D(0)
        self._total_vol: D = D(0)
        self._phantom_count: int = 0     # opens/closes that returned oid but no real fill
        # F1 maker: resting order tracking (oid, qty, side, ts). Prevents re-quote spam.
        # Cleared when fill detected (via _real_pos delta) or order cancelled/expired.
        self.pending_maker: dict = {}    # {"oid": str, "qty": D, "side": str, "ts": float}
        self._maker_max_age_s: float = float(os.environ.get("TE_PVE_MAKER_MAX_AGE", "300"))
        self._inv_open_ts: float = 0.0      # epoch when current inventory was opened
        self._inv_max_hold_s: float = float(os.environ.get("TE_PVE_INV_MAX_HOLD", "120"))

        # ── Restore state ──
        self._restore_state()
    
    # ══════════════════════════════════════════════════════════════
    # STATE PERSISTENCE
    # ══════════════════════════════════════════════════════════════
    def _state_key(self, suffix: str) -> str:
        return f"pve_{self.pair.replace('-', '_')}_{suffix}"
    
    def _restore_state(self):
        """Load persisted state from ledger on init + reconcile with exchange position.
        F1 fix (2026-06-29): jika DB bilang ada inventory tapi exchange flat → phantom
        (sisa trade lama / posisi ditutup manual) → reset inv_qty agar tidak stuck di
        mode 'close inventory yang tidak ada' (infinite maker-close reject loop)."""
        self.inv_qty = D(self.led.get_state(self._state_key("inv_qty"), "0"))
        self.inv_cost = D(self.led.get_state(self._state_key("inv_cost"), "0"))
        self._total_rt = int(self.led.get_state(self._state_key("total_rt"), "0"))
        self._total_pnl = D(self.led.get_state(self._state_key("total_pnl"), "0"))
        self._total_vol = D(self.led.get_state(self._state_key("total_vol"), "0"))
        # Ledger.get_state is Decimal-only, so persist the UTC date as YYYYMMDD.
        saved_loss_date = str(self.led.get_state(
            self._state_key("daily_loss_date"), "0"))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if saved_loss_date == today.replace("-", ""):
            self._daily_loss_date = today
            self._daily_loss = D(self.led.get_state(
                self._state_key("daily_loss"), "0"))
        # Reconcile with exchange: if DB has inv but exchange flat → phantom, reset.
        if self.inv_qty > 0:
            try:
                real = self._real_pos()
                if real <= 0:
                    logging.warning("PVE %s PHANTOM-INV reset: DB inv=%s but exchange flat "
                                    "(real=%s). Resetting inv to 0 to avoid maker-close loop.",
                                    self.pair, float(self.inv_qty), float(real))
                    self.inv_qty = D(0)
                    self.inv_cost = D(0)
                    self.pending_maker = {}
                    self._save_state()
                else:
                    logging.info("PVE %s restored: inv=%s cost=$%s rt=%s pnl=$s (real=%s)",
                                 self.pair, float(self.inv_qty), float(self.inv_cost),
                                 self._total_rt, float(self._total_pnl), float(real))
            except Exception as e:
                logging.warning("PVE %s restore reconcile exc (keep DB inv): %s", self.pair, e)
                logging.info("PVE %s restored: inv=%s cost=$%s rt=%s pnl=$s",
                             self.pair, float(self.inv_qty), float(self.inv_cost),
                             self._total_rt, float(self._total_pnl))
    
    def _save_state(self):
        """Persist current state to ledger."""
        self.led.set_state(self._state_key("inv_qty"), str(self.inv_qty))
        self.led.set_state(self._state_key("inv_cost"), str(self.inv_cost))
        self.led.set_state(self._state_key("total_rt"), str(self._total_rt))
        self.led.set_state(self._state_key("total_pnl"), str(self._total_pnl))
        self.led.set_state(self._state_key("total_vol"), str(self._total_vol))
        self.led.set_state(self._state_key("daily_loss"), str(self._daily_loss))
        self.led.set_state(
            self._state_key("daily_loss_date"), self._daily_loss_date.replace("-", ""))
    
    # ══════════════════════════════════════════════════════════════
    # REGIME DETECTION
    # ══════════════════════════════════════════════════════════════
    def _regime(self) -> str:
        """Detect BEAR/BULL/NEUTRAL regime REAL-TIME from BTC price momentum.
        FIX (2026-07-07): intel JSONL pipeline output konstan fc_BTC_dir_enc=0 (placeholder
        rusak) → regime selalu NEUTRAL → tidak pernah cegah rugi saat market turun.
        Solusi: fetch BTC 1h candle Binance langsung, hitung EMA20/EMA50 slope + ROC.
        Antisipasi dini otonom: BEAR jika EMA20<EMA50 DAN ROC1h<-0.3% → pause PVE.
        ponytail: 1 API call, 3s timeout; EMA cukup untuk momentum, upgrade ke MACD/RSI jika perlu."""
        now = time.time()
        if now - self._regime_cache_ts < 300:  # 5-min cache
            return self._regime_cache
        try:
            import requests as _req
            r = _req.get("https://api.binance.com/api/v3/klines",
                         params={"symbol": "BTCUSDT", "interval": "1h", "limit": 55},
                         timeout=3)
            if r.status_code != 200:
                return self._regime_cache or "NEUTRAL"
            candles = r.json()
            closes = [float(c[4]) for c in candles]  # index 4 = close price
            if len(closes) < 50:
                return self._regime_cache or "NEUTRAL"
            # EMA20 dan EMA50
            def ema(data, period):
                k = 2 / (period + 1)
                e = data[0]
                for p in data[1:]:
                    e = p * k + e * (1 - k)
                return e
            ema20 = ema(closes[-20:], 20)
            ema50 = ema(closes[-50:], 50)
            # Rate of change (1h): (close_now - close_1h_ago) / close_1h_ago
            roc1h = (closes[-1] - closes[-2]) / closes[-2] * 100 if closes[-2] else 0
            # Rate of change (3h) untuk konfirmasi momentum
            roc3h = (closes[-1] - closes[-4]) / closes[-4] * 100 if len(closes) >= 4 and closes[-4] else 0
            # Regime decision (antisipasi dini):
            # BEAR jika EMA20<EMA50 (downtrend) DAN (ROC1h<-0.3% ATAU ROC3h<-0.5%) → momentum turun
            # BULL jika EMA20>EMA50 DAN ROC1h>0.2% → momentum naik
            # NEUTRAL jika tidak jelas (sideways)
            if ema20 < ema50 and (roc1h < -0.3 or roc3h < -0.5):
                regime = "BEAR"
            elif ema20 > ema50 and roc1h > 0.2:
                regime = "BULL"
            else:
                regime = "NEUTRAL"
            self._regime_cache = regime
            self._regime_cache_ts = now
            logging.info("PVE regime REAL-TIME: BTC=$%.0f EMA20=%.0f EMA50=%.0f ROC1h=%+.3f%% ROC3h=%+.3f%% → %s",
                         closes[-1], ema20, ema50, roc1h, roc3h, regime)
            return regime
        except Exception as e:
            logging.debug("regime realtime exc: %s", e)
            return self._regime_cache or "NEUTRAL"

    def _adaptive_selection(self) -> str | None:
        """The adaptive selector's current pick for THIS pair: 'long'/'short' if this
        pair is currently selected (trending + farmable) and the file is fresh, else
        None (not selected / stale → caller skips opening). Read-only, fail-safe."""
        if not PVE_ADAPTIVE:
            return None
        try:
            if not os.path.exists(PVE_ADAPTIVE_FILE):
                return None
            if (time.time() - os.path.getmtime(PVE_ADAPTIVE_FILE)) > PVE_ADAPTIVE_MAX_AGE:
                return None  # stale → fall back to skip (no forcing an untrended trade)
            import json as _json
            sel = _json.loads(Path(PVE_ADAPTIVE_FILE).read_text())
            d = sel.get("directions", {}).get(self.pair)
            return d if d in ("long", "short") else None
        except Exception as e:
            logging.debug("adaptive selection read exc: %s", e)
            return None

    def _adaptive_blocked(self) -> bool:
        """Adaptive mode ON and this pair is NOT currently selected → skip opening it."""
        return PVE_ADAPTIVE and self._adaptive_selection() is None

    def _effective_direction(self) -> str:
        """Resolve direction. Adaptive mode: use the selector's with-trend direction for
        this pair when selected. Else "auto" → regime; else the explicit direction."""
        # Closing must follow the side of the position that actually exists. This is
        # especially important when close-only recovery adopts exposure created before
        # a restart while the adaptive selector has since changed direction.
        if self.inv_qty > 0 and self._inventory_direction in ("long", "short"):
            return self._inventory_direction
        if PVE_ADAPTIVE:
            adir = self._adaptive_selection()
            if adir in ("long", "short"):
                return adir
        if self.direction == "auto":
            # Directional exposure belongs to this market, so follow its own
            # confirmed drift first. BTC is only a fallback when that signal is flat.
            pair_drift = self._pair_drift()
            if pair_drift == "RISING":
                return "long"
            if pair_drift == "FALLING":
                return "short"
            return "short" if self._regime() == "BEAR" else "long"
        return self.direction

    def _pair_drift(self) -> str:
        """OWN-PAIR realtime momentum: 'RISING' / 'FALLING' / 'FLAT'.

        RC2 fix (2026-07-18): direction for "auto" comes from the BTC regime, but the
        real risk is trading AGAINST the *traded pair's own* trend (short a rallying
        SOL / long a crashing one). This measures the pair itself — Binance 1h klines
        for {base}USDT are a fresh proxy since SoDEX perps track Binance. Same
        EMA20/EMA50 + ROC mechanism as _regime(), so it is always fresh (unlike a
        historical calibration base_rate, which can be hours stale). 5-min cached.
        Fail-open: returns the last cache ('FLAT' at cold start) on any error → no veto.
        """
        now = time.time()
        if now - self._drift_cache_ts < 300:  # 5-min cache
            return self._drift_cache
        try:
            base = self.pair.replace("/", "-").split("-")[0].upper()
            sym = f"{base}USDT"
            import requests as _req
            r = _req.get("https://api.binance.com/api/v3/klines",
                         params={"symbol": sym, "interval": "1h", "limit": 55},
                         timeout=3)
            if r.status_code != 200:
                return self._drift_cache
            closes = [float(c[4]) for c in r.json()]
            if len(closes) < 50:
                return self._drift_cache

            def ema(data, period):
                k = 2 / (period + 1)
                e = data[0]
                for p in data[1:]:
                    e = p * k + e * (1 - k)
                return e

            ema20 = ema(closes[-20:], 20)
            ema50 = ema(closes[-50:], 50)
            roc1h = (closes[-1] - closes[-2]) / closes[-2] * 100 if closes[-2] else 0
            roc3h = (closes[-1] - closes[-4]) / closes[-4] * 100 if len(closes) >= 4 and closes[-4] else 0
            # RISING needs BOTH trend (EMA) and momentum (ROC) agreement — a single
            # noisy candle must not fire the veto. Symmetric for FALLING. Else FLAT.
            if ema20 > ema50 and (roc1h > PVE_DRIFT_ROC or roc3h > PVE_DRIFT_ROC * 1.5):
                drift = "RISING"
            elif ema20 < ema50 and (roc1h < -PVE_DRIFT_ROC or roc3h < -PVE_DRIFT_ROC * 1.5):
                drift = "FALLING"
            else:
                drift = "FLAT"
            self._drift_cache = drift
            self._drift_cache_ts = now
            logging.info("PVE %s OWN-DRIFT: %s EMA20=%.5g EMA50=%.5g ROC1h=%+.3f%% → %s",
                         self.pair, sym, ema20, ema50, roc1h, drift)
            return drift
        except Exception as e:
            logging.debug("pair drift exc: %s", e)
            return self._drift_cache

    def _drift_veto(self, direction: str) -> tuple:
        """Defensive per-pair drift veto (RC2). Blocks ONLY a clearly-adverse OPEN:
        SHORT into a rising pair, or LONG into a falling pair. FLAT drift → no veto
        (volume-farm doctrine: coin-flip direction is acceptable when the pair has no
        clear trend, since the TA gate has no proven edge — we avoid the adverse case,
        we do not try to predict). Returns (vetoed: bool, reason: str)."""
        if not PVE_DRIFT_VETO:
            return False, "drift_veto_disabled"
        drift = self._pair_drift()
        if direction == "short" and drift == "RISING":
            return True, "drift_veto_short_into_rising"
        if direction == "long" and drift == "FALLING":
            return True, "drift_veto_long_into_falling"
        return False, f"drift_ok_{drift.lower()}"

    def _l1_obi(self) -> tuple:
        """L1 order-book imbalance + binding-side depth in USD, from a depth-1 book.
        Returns (obi, min_depth_usd). obi = (bid_qty−ask_qty)/(bid_qty+ask_qty) ∈ [−1,1]
        (positive = bid/buy pressure). 5s cache. Fail-open: returns last cache
        ((0.0, inf) at cold start) on any read error → no adverse block."""
        now = time.time()
        if now - self._obi_cache_ts < 5:
            return self._obi_cache
        try:
            mkt = "perps" if "-USD" in self.pair.upper() else "spot"
            j = self.x._sodex(["orderbook", mkt, self.pair, "--depth", "1", "--format", "json"])
            if not j or not j.get("bids") or not j.get("asks"):
                return self._obi_cache
            bid = float(j["bids"][0]["price"]); bq = float(j["bids"][0]["quantity"])
            ask = float(j["asks"][0]["price"]); aq = float(j["asks"][0]["quantity"])
            obi = (bq - aq) / (bq + aq) if (bq + aq) > 0 else 0.0
            depth = min(bid * bq, ask * aq)
            self._obi_cache = (obi, depth)
            self._obi_cache_ts = now
            return self._obi_cache
        except Exception as e:
            logging.debug("l1_obi exc: %s", e)
            return self._obi_cache

    def _recent_ofi(self) -> tuple:
        """Normalized cumulative OFI for this pair from the microstructure recorder DB
        over the last PVE_OFI_WINDOW_S. Returns (ofi_norm, n_snaps). ofi_norm = OFI /
        mean_L1_depth (dimensionless depth-equivalents of net flow; + = net buy). OFI
        inlined (identical to sodex_book_recorder.compute_ofi — kept in sync by a test)
        so the live engine never depends on scripts/ import paths. (0.0, 0) if the
        recorder has no/too-little data → caller falls back to static OBI. Fail-open."""
        try:
            if not os.path.exists(PVE_BOOK_DB):
                return 0.0, 0
            import sqlite3
            con = sqlite3.connect(f"file:{PVE_BOOK_DB}?mode=ro", uri=True, timeout=3)
            cut = time.time() - PVE_OFI_WINDOW_S
            rows = con.execute(
                "SELECT bid, ask, bid_sz, ask_sz FROM l1 WHERE symbol=? AND ts>=? ORDER BY ts",
                (self.pair, cut)).fetchall()
            con.close()
            n = len(rows)
            if n < 2:
                return 0.0, n
            ofi = 0.0
            for i in range(1, n):
                bp0, ap0, bs0, as0 = rows[i - 1]
                bp1, ap1, bs1, as1 = rows[i]
                e_bid = bs1 if bp1 > bp0 else (bs1 - bs0 if bp1 == bp0 else -bs0)
                e_ask = as1 if ap1 < ap0 else (as1 - as0 if ap1 == ap0 else -as0)
                ofi += (e_bid - e_ask)
            mean_depth = sum((r[2] + r[3]) for r in rows) / (2 * n)
            ofi_norm = ofi / mean_depth if mean_depth > 1e-9 else 0.0
            return ofi_norm, n
        except Exception as e:
            logging.debug("recent_ofi exc: %s", e)
            return 0.0, 0

    def _adverse_gate(self, direction: str) -> tuple:
        """U4 defensive adverse-selection gate for OPENs. Blocks when the L1 book is too
        thin (< MIN_L1_DEPTH_USD) or when order flow is EXTREMELY against our fill side.
        Uses real cumulative OFI (from the U1 recorder) as the PRIMARY signal when enough
        snapshots exist, else falls back to the weaker static OBI. Returns (blocked, reason)."""
        if not PVE_ADVERSE_GATE:
            return False, "adverse_gate_disabled"
        obi, depth = self._l1_obi()
        if depth < PVE_MIN_L1_DEPTH_USD:
            logging.info("PVE %s U4 skip: L1 depth $%.0f < floor $%.0f (thin book)",
                         self.pair, depth, PVE_MIN_L1_DEPTH_USD)
            return True, "adverse_thin_book"
        # Prefer real OFI flow when the recorder has enough data.
        ofi_norm, n_ofi = self._recent_ofi()
        if n_ofi >= PVE_OFI_MIN_SNAPS:
            if direction == "long" and ofi_norm <= -PVE_OFI_ADVERSE:
                logging.info("PVE %s U4 skip: OFI=%.2f (sell flow) vs long-open (n=%d)",
                             self.pair, ofi_norm, n_ofi)
                return True, "adverse_ofi_long_into_sellflow"
            if direction == "short" and ofi_norm >= PVE_OFI_ADVERSE:
                logging.info("PVE %s U4 skip: OFI=%.2f (buy flow) vs short-open (n=%d)",
                             self.pair, ofi_norm, n_ofi)
                return True, "adverse_ofi_short_into_buyflow"
            return False, "adverse_ok_ofi"
        # Fallback: static OBI (recorder cold / insufficient snapshots).
        if direction == "long" and obi <= -PVE_OBI_ADVERSE:
            logging.info("PVE %s U4 skip: OBI=%.2f (sell pressure) vs long-open", self.pair, obi)
            return True, "adverse_obi_long_into_sell"
        if direction == "short" and obi >= PVE_OBI_ADVERSE:
            logging.info("PVE %s U4 skip: OBI=%.2f (buy pressure) vs short-open", self.pair, obi)
            return True, "adverse_obi_short_into_buy"
        return False, "adverse_ok"

    # ══════════════════════════════════════════════════════════════
    # F3b (2026-06-29): GOVERNOR EV GATE — block negative-expectancy trades
    # ══════════════════════════════════════════════════════════════
    def _model_prob(self) -> float:
        """Get directional probability from LightGBM model server (sodex-model:8001).
        Falls back to conservative PVE_MODEL_FALLBACK_PROB if model down.
        ponytail: one GET, 2s timeout; upgrade to streaming if latency-critical."""
        if not PVE_MODEL_URL:
            return PVE_MODEL_FALLBACK_PROB
        try:
            import requests
            r = requests.get(f"{PVE_MODEL_URL}/predict",
                             params={"symbol": self.pair}, timeout=2)
            if r.status_code == 200:
                j = r.json()
                return float(j.get("prob_up", j.get("prob", PVE_MODEL_FALLBACK_PROB)))
        except Exception:
            pass
        return PVE_MODEL_FALLBACK_PROB

    def _win_stats(self) -> tuple:
        """Estimate win_rate, avg_win_pct, avg_loss_pct from recent RT history.
        Returns (win_rate, avg_win_pct, avg_loss_pct). Conservative if no data.
        ponytail: pull from DB rts table via ledger; cold-start uses priors."""
        try:
            n = max(self._total_rt, 1)
            # We only have aggregate pnl, not per-RT — approximate from total_pnl sign.
            # Conservative prior: WR 0.55, win 0.15%, loss 0.10% (matches gov self-test).
            if self._total_rt < 20:
                return 0.55, 0.15, 0.10
            avg_pnl_pct = float(self._total_pnl) / float(self._total_vol) * 100 if self._total_vol > 0 else 0
            # If historical avg positive, assume WR 0.58; else 0.50 (coinflip at best)
            wr = 0.58 if avg_pnl_pct > 0 else 0.50
            return wr, max(abs(avg_pnl_pct), 0.15), max(abs(avg_pnl_pct) * 0.8, 0.10)
        except Exception:
            return 0.55, 0.15, 0.10

    def _governor_gate(self, bk) -> tuple:
        """Run governor EV gate. Returns (approved: bool, reason: str).
        Skips if governor unavailable (fail-open to legacy behavior on import error)."""
        if not PVE_GOVERNOR_GATE:
            return True, "governor_disabled"
        try:
            from anantara import sodex_governor as gov
        except Exception:
            return True, "governor_unavailable_fail_open"
        mid = (bk.bid + bk.ask) / 2
        spread_pct = float((bk.ask - bk.bid) / mid * 100) if mid > 0 else 0
        depth_usd = float(PVE_MAX_NOTIONAL)  # proxy (we don't poll full depth each tick)
        volume_24h = 1_000_000  # conservative proxy
        atr_pct = max(spread_pct * 3, 0.3)  # ATR proxy: 3× spread, floor 0.3%
        model_prob = self._model_prob()
        win_rate, avg_win, avg_loss = self._win_stats()
        fee_pct = float(PVE_MAKER_FEE_PCT) * 2 if PVE_MAKER_PATH else 0.08  # RT fee %
        try:
            d = gov.evaluate_roundtrip(
                atr_pct=atr_pct, spread_pct=spread_pct, depth_usd=depth_usd,
                volume_24h_usd=volume_24h, rr=PVE_GOV_MIN_RR, model_prob=model_prob,
                win_rate=win_rate, avg_win_pct=avg_win, avg_loss_pct=avg_loss,
                fee_pct=fee_pct)
            if not d.approved:
                logging.info("PVE %s GOVERNOR-REJECT: %s (prob=%.2f wr=%.2f spread=%.3f%%)",
                             self.pair, d.reason, model_prob, win_rate, spread_pct)
            return d.approved, d.reason
        except Exception as e:
            logging.warning("PVE %s governor exc (fail-open): %s", self.pair, e)
            return True, f"governor_exc_{e}"

    # ══════════════════════════════════════════════════════════════
    # ORDER PLACEMENT (proven pattern from HEDGE)
    # ══════════════════════════════════════════════════════════════
    def _place_buy(self, limit_px: D, qty: D) -> Optional[str]:
        """Place BUY limit-IOC at limit_px (pass ask → crosses spread → taker fill)."""
        try:
            o = self.x.place_limit_ioc_perp(self.pair, "buy", qty, limit_px)
            if o and o.oid and o.oid != "0":
                return o.oid
        except Exception as e:
            logging.warning("PVE %s buy limit-IOC exc: %s", self.pair, e)

        # Fallback: market-IOC
        try:
            o = self.x.place_market_ioc(self.pair, "buy", qty, limit_px)
            if o and o.oid and o.oid != "0":
                return o.oid
        except Exception as e:
            logging.warning("PVE %s buy market-IOC exc: %s", self.pair, e)

        return None

    def _place_sell(self, limit_px: D, qty: D) -> Optional[str]:
        """Place SELL limit-IOC at limit_px (pass bid → crosses spread → taker fill)."""
        try:
            o = self.x.place_limit_ioc_perp(self.pair, "sell", qty, limit_px)
            if o and o.oid and o.oid != "0":
                return o.oid
        except Exception as e:
            logging.warning("PVE %s sell limit-IOC exc: %s", self.pair, e)

        # Fallback: market-IOC
        try:
            o = self.x.place_market_ioc(self.pair, "sell", qty, limit_px)
            if o and o.oid and o.oid != "0":
                return o.oid
        except Exception as e:
            logging.warning("PVE %s sell market-IOC exc: %s", self.pair, e)

        return None

    def _force_close_taker(self, direction: str, bk, close_qty: D) -> dict:
        """Close expired maker inventory with a verified reduce-only market IOC.

        This path is never used to open or increase exposure. It exists because a
        rejected/stale GTX close can otherwise pin margin indefinitely and stop all
        subsequent volume generation.
        """
        side = "buy" if direction == "short" else "sell"
        ref_px = bk.ask if side == "buy" else bk.bid
        pos_before = self._real_pos()
        try:
            order = self.x.place_market_ioc(
                self.pair, side, close_qty, ref_px, reduce_only=True)
        except (AttributeError, TypeError) as exc:
            logging.error("PVE %s reduce-only fallback unavailable: %s", self.pair, exc)
            return {"action": "skip", "reason": "reduce_only_fallback_unavailable"}
        except Exception as exc:
            logging.warning("PVE %s reduce-only fallback failed: %s", self.pair, exc)
            return {"action": "skip", "reason": "reduce_only_fallback_failed"}
        if not order or not order.oid or order.oid == "0":
            return {"action": "skip", "reason": "reduce_only_fallback_rejected"}
        _filled, verified = self._verify_fill(pos_before, close_qty, "maker-expired-close")
        if not verified:
            return {"action": "skip", "reason": "reduce_only_fallback_phantom"}

        close_notional = close_qty * ref_px
        pnl = (self.inv_cost - close_notional if direction == "short"
               else close_notional - self.inv_cost)
        self._total_rt += 1
        self._total_pnl += pnl
        self._daily_loss += max(D(0), -pnl)
        self._total_vol += close_notional
        rt_id = f"PVE-{self.pair.replace('-','_')}-{self._total_rt}"
        fee = D("0.00036")
        open_side = "sell" if direction == "short" else "buy"
        try:
            open_px = self.inv_cost / close_qty if close_qty > 0 else ref_px
            self.led.fill("PVE", "P", self.pair, open_side, open_px, close_qty,
                          self.inv_cost * fee, False, rt_id)
            self.led.fill("PVE", "P", self.pair, side, ref_px, close_qty,
                          close_notional * fee, False, rt_id)
            self.led.rt_close(rt_id, "PVE", self.pair,
                              self.inv_cost + close_notional, pnl)
        except Exception as exc:
            logging.warning("PVE %s fallback close-ledger exc: %s", self.pair, exc)
        logging.warning(
            "PVE %s REDUCE-ONLY FALLBACK close qty=%s px=%s pnl=$%.4f oid=%s",
            self.pair, float(close_qty), float(ref_px), float(pnl), order.oid)
        self.inv_qty = D(0)
        self.inv_cost = D(0)
        self._inv_open_ts = 0.0
        self.pending_maker = {}
        self._last_order_ts = time.time()
        self._save_state()
        return {"action": side, "oid": str(order.oid), "qty": float(close_qty),
                "px": float(ref_px), "pnl": float(pnl), "direction": direction,
                "maker": False, "reduce_only": True, "fallback": True}
    
    # ══════════════════════════════════════════════════════════════
    # RISK GATES
    # ══════════════════════════════════════════════════════════════
    def _check_daily_loss(self) -> bool:
        """Returns True if daily loss limit exceeded (should pause)."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._daily_loss_date != today:
            self._daily_loss = D(0)
            self._daily_loss_date = today
            self.led.set_state(self._state_key("daily_loss"), "0")
            self.led.set_state(self._state_key("daily_loss_date"), today.replace("-", ""))
        return self._daily_loss >= PVE_DAILY_LOSS_LIMIT

    def _check_weekly_net_kill(self) -> bool:
        """F3d (2026-06-29): weekly NET kill-switch. Pause if NET week < floor.
        NET week = total_pnl_week - total_fee_week, queried from DB rts+fills.
        Reset tiap snapshot Sabtu 07:00 WIB (00:00 UTC Sabtu).
        Fail-closed: if the accounting DB cannot be read, trading must stop."""
        if not PVE_WEEKLY_NET_KILL:
            return False
        db = None
        try:
            import sqlite3 as _sq
            db_path = Path(PVE_DB_PATH)
            if not db_path.exists():
                logging.error("PVE %s WEEKLY-NET-KILL fail-closed: DB missing at %s",
                              self.pair, db_path)
                return True
            db = _sq.connect(str(db_path))
            cur = db.cursor()
            now = datetime.now(timezone.utc)
            back = (now.weekday() - 5) % 7  # Saturday=5
            week_start_dt = (now - timedelta(days=back)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            week_start = week_start_dt.strftime("%Y-%m-%d %H:%M:%S")
            cur.execute("""SELECT COALESCE(SUM(CAST(net_pnl AS REAL)),0) FROM rts
                          WHERE ts_close >= ?""", (week_start,))
            pnl = float(cur.fetchone()[0] or 0)
            cur.execute("""SELECT COALESCE(SUM(CAST(fee AS REAL)),0) FROM fills
                          WHERE ts >= ?""", (week_start,))
            fee = float(cur.fetchone()[0] or 0)
            db.close()
            net = pnl - fee
            if net <= float(PVE_WEEKLY_NET_FLOOR):
                logging.warning("PVE %s WEEKLY-NET-KILL: week_net=$%.2f (pnl=%.2f fee=%.2f) "
                                "<= floor=$%s — PAUSING", self.pair, net, pnl, fee,
                                float(PVE_WEEKLY_NET_FLOOR))
                return True
        except Exception as e:
            logging.error("PVE %s WEEKLY-NET-KILL fail-closed: %s", self.pair, e)
            return True
        finally:
            if db is not None:
                db.close()
        return False
    
    def _check_spread_ok(self, spread_pct: D) -> bool:
        """Returns True if spread is wide enough to trade."""
        return spread_pct >= PVE_MIN_SPREAD_PCT
    
    def _check_cooldown(self) -> bool:
        """Returns True if in cooldown (should skip this loop)."""
        return (time.time() - self._last_order_ts) < PVE_COOLDOWN_S

    def _activate_ratio_pause(self, reason: str) -> None:
        """Fail closed locally without stopping engines needed to drain exposure."""
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "source": "perps_volume_engine",
            "reason": reason,
        }
        try:
            PVE_PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = PVE_PAUSE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2))
            tmp.replace(PVE_PAUSE_FILE)
        except Exception as exc:
            logging.error("PVE %s cannot activate ratio pause: %s", self.pair, exc)

    def _honest_ratio_recovery_active(self) -> bool:
        """Allow only maker recovery through a pause owned by the ratio gate."""
        if not PVE_HONEST_RECOVERY_MODE or not PVE_MAKER_PATH:
            return False
        try:
            pause = json.loads(PVE_PAUSE_FILE.read_text())
        except (OSError, ValueError):
            return False
        return (
            pause.get("source") == "sodex_honest_ratio_gate"
            and pause.get("recovery_enabled", True) is not False
        )

    def _recovery_ratio_gate(self, current_ratio: D, floor: D,
                             fee_fraction: D, next_rt_volume: D,
                             volume: D, cost: D) -> tuple[bool, str]:
        """Permit ratio-improving maker RTs while the aggregate ratio recovers."""
        if not self._honest_ratio_recovery_active():
            return False, "honest_ratio_breached"
        if fee_fraction <= 0:
            marginal_ratio = D("Infinity")
        else:
            marginal_ratio = D(1) / fee_fraction
        recovery_floor = floor * PVE_HONEST_RECOVERY_HEADROOM
        if marginal_ratio < recovery_floor:
            return False, "honest_ratio_recovery_marginal_too_low"
        projected_cost = cost + next_rt_volume * fee_fraction
        projected_ratio = ((volume + next_rt_volume) / projected_cost
                           if projected_cost > 0 else D("Infinity"))
        if projected_ratio <= current_ratio:
            return False, "honest_ratio_recovery_not_improving"

        # A losing canary quarantines its own market without deadlocking every
        # future opportunity. The selector independently removes recent losers;
        # an unseen pair may still run one bounded canary under the global loss cap.
        state_key = f"pve_honest_recovery_last_ratio:{self.pair}"
        try:
            last_ratio = D(str(self.led.get_state(state_key, "0")))
        except Exception:
            return False, "honest_ratio_recovery_state_unavailable"
        tolerance = D(1) - PVE_HONEST_RECOVERY_MAX_DROP_BPS / D(10000)
        if last_ratio > 0 and current_ratio < last_ratio * tolerance:
            return False, "honest_ratio_recovery_deteriorated"
        try:
            self.led.set_state(state_key, str(current_ratio))
        except Exception:
            return False, "honest_ratio_recovery_state_unavailable"
        return True, "honest_ratio_recovery_open"

    def _honest_ratio_open_gate(self, next_rt_volume: D) -> tuple[bool, str]:
        """Retain hard loss protection while delegating floor to its policy window.

        Fixed-window mode evaluates the ratio over 24 hours externally. It does not
        require each individual order to satisfy the aggregate floor.
        """
        if not PVE_HONEST_RATIO_GUARD:
            return True, "ratio_guard_disabled"
        try:
            state = json.loads(PVE_HONEST_STATE_FILE.read_text())
            av_now = self.x.perps_account_value()
            if av_now is None:
                return False, "honest_ratio_av_unavailable"
            av_start = D(str(state["av_start"]))
            floor = max(D(str(state.get("floor", 0))), PVE_HONEST_RATIO_FLOOR)
            import sqlite3 as _sq
            db = _sq.connect(f"file:{PVE_DB_PATH}?mode=ro", uri=True, timeout=3)
            try:
                row = db.execute(
                    "SELECT COALESCE(SUM(CAST(volume AS REAL)),0) FROM rts "
                    "WHERE engine='PVE' AND ts_close>=?", (state["ts_start"],)
                ).fetchone()
            finally:
                db.close()
            volume = D(str(row[0] or 0))
            cost = max(D(0), av_start - D(str(av_now)))
            loss_cap = D(str(state.get("loss_cap_usd", "4")))
            if cost >= loss_cap:
                return False, "honest_ratio_loss_cap_reached"
            if state.get("ratio_policy") == "fixed_24h_window":
                return True, "honest_ratio_24h_window_open"
            fee_fraction = (PVE_MAKER_FEE_PCT / D(100)
                            if PVE_MAKER_PATH else D("0.0004"))
            if cost > 0 and volume / cost < floor:
                current_ratio = volume / cost
                allowed, recovery_reason = self._recovery_ratio_gate(
                    current_ratio, floor, fee_fraction, next_rt_volume, volume, cost)
                if allowed:
                    return True, recovery_reason
                if recovery_reason == "honest_ratio_breached":
                    reason = (f"honest ratio breached before open: "
                              f"{current_ratio:.1f} < {floor}")
                    self._activate_ratio_pause(reason)
                return False, recovery_reason
            projected_volume = volume + next_rt_volume
            projected_cost = cost + next_rt_volume * fee_fraction
            if projected_cost > 0 and projected_volume / projected_cost < floor:
                return False, "honest_ratio_projected_below_floor"
            return True, "honest_ratio_projected_ok"
        except Exception as exc:
            logging.warning("PVE %s honest-ratio open gate unavailable: %s",
                            self.pair, exc)
            return False, "honest_ratio_truth_unavailable"

    def _global_position_gate(self) -> tuple[bool, str]:
        """Block new pair opens until account position truth is verified and isolated."""
        try:
            positions = self.x.perps_positions()
        except Exception:
            return True, "global_position_truth_unavailable"
        if getattr(self.x, "_perps_positions_read_ok", None) is False:
            return True, "global_position_truth_unavailable"
        other = [
            symbol for symbol, qty in (positions or {}).items()
            if symbol != self.pair and D(str(qty)) != 0
        ]
        # Let the orchestrator prioritize the engine that can drain an unexpected
        # out-of-band position instead of continuing to rotate idle candidates.
        try:
            self.x._pve_other_positions = other
        except Exception:
            pass
        if other:
            return True, "other_perp_position_open"
        return False, "verified_isolated"

    # ══════════════════════════════════════════════════════════════
    # F1 (2026-06-29): MAKER PATH — post-only GTC inside-spread
    # ══════════════════════════════════════════════════════════════
    def _rt_fee_bps(self) -> float:
        """Round-trip maker fee in basis points (both sides). PVE_MAKER_FEE_PCT is a
        percent per side (0.012 = 0.012%/side); ×2 sides ×100 = bps."""
        return float(PVE_MAKER_FEE_PCT) * 2.0 * 100.0

    def _maker_viable(self, bid: D, ask: D) -> bool:
        """True if a maker round-trip is worth posting.

        Legacy "fee-saving" mode (PVE_MIN_CAPTURE_BPS ≤ 0): any positive spread — maker
        beats taker whenever half-spread > 0, but this ALSO posts RTs whose captured
        spread < fee → net loss (smaller than taker's). Kept only for backward compat.

        U3 profit-capture mode (PVE_MIN_CAPTURE_BPS > 0, recommended): require
        net_capture = spread_bps − rt_fee_bps ≥ PVE_MIN_CAPTURE_BPS, so every posted RT
        is net-positive by construction (serves >69%-profitable + high honest-ratio).
        A tight perp whose spread ≤ rt_fee simply won't pass — profitable maker farming
        needs wider-spread pairs (this gate exposes that, rather than bleeding on SOL)."""
        mid = (bid + ask) / 2
        if mid <= 0:
            return False
        spread_bps = float((ask - bid) / mid) * 1e4
        if PVE_MIN_CAPTURE_BPS <= 0:
            return spread_bps > 0.0  # legacy fee-saving mode
        net_capture_bps = spread_bps - self._rt_fee_bps()
        viable = net_capture_bps >= PVE_MIN_CAPTURE_BPS
        if not viable:
            logging.info("PVE %s U3 skip: spread=%.2fbps net_capture=%.2fbps < floor=%.2fbps "
                         "(rt_fee=%.2fbps) — unprofitable maker, waiting for wider spread",
                         self.pair, spread_bps, net_capture_bps, PVE_MIN_CAPTURE_BPS,
                         self._rt_fee_bps())
        return viable

    def _maker_price(self, side: str, bid: D, ask: D, offset_ticks: D) -> D:
        """Compute maker price for resting order.
        COMPETITIVE mode (default, TE_PVE_MAKER_COMPETITIVE=1 — paper-v2 validated
        2026-07-14): rest AT the touch for fast fills on wide-spread venues:
          BUY  → bid + offset (just above bid = new best bid)
          SELL → ask − offset (just below ask = new best ask)
        Clamped so it never crosses (post-only safety). On wide venues (DRAM 0.33%)
        this still captures ~full spread minus 1 tick → net-positive, but fills far
        better than legacy ask+offset (which strands above the market in a trend).
        LEGACY mode (=0): BUY@bid−offset / SELL@ask+offset (max capture, worst fill).
        tick_size inferred from price magnitude (same band logic as _calc_qty)."""
        mid = (bid + ask) / 2
        # Tick size bands matching _calc_qty precision bands
        if mid >= D("1000"):
            tick = D("0.1")
        elif mid >= D("100"):
            tick = D("0.01")
        elif mid >= D("10"):
            tick = D("0.01")
        elif mid >= D("1"):
            tick = D("0.001")
        else:
            tick = D("0.0001")   # sub-dollar: ENA, PEPE-perp, etc.
        effective_offset = offset_ticks * tick
        competitive = os.environ.get("TE_PVE_MAKER_COMPETITIVE", "1") == "1"
        if competitive:
            if side == "buy":
                px = bid + effective_offset
                return px if px < ask else bid      # never cross ask (post-only safe)
            px = ask - effective_offset
            return px if px > bid else ask          # never cross bid (post-only safe)
        # legacy (max capture, worst fill)
        if side == "buy":
            return bid - effective_offset
        return ask + effective_offset

    def _calc_qty(self, mid: D) -> D:
        """Compute trade qty from notional/mid, rounded to valid step.
        Extracted from tick() so maker path reuses identical sizing."""
        raw_qty = float(PVE_MAX_NOTIONAL / mid)
        if mid > 1000:
            qty = D(str(round(raw_qty, 4)))
        elif mid > 100:
            qty = D(str(round(raw_qty, 2)))
        elif mid > 10:
            qty = D(str(round(raw_qty, 2)))
        elif mid > 1:
            qty = D(str(round(raw_qty, 1)))
        else:
            qty = D(str(int(raw_qty)))
        return qty

    def _place_maker(self, side: str, price: D, qty: D, reduce_only: bool = False):
        """Place post-only (GTX) maker order inside the spread.
        Returns (oid_str, order_obj). oid="0" → exchange rejected (would cross) — clean skip.
        Adapter must implement place_limit_gtx_perp(perp, side, qty, price, reduce_only)."""
        try:
            o = self.x.place_limit_gtx_perp(self.pair, side, qty, price, reduce_only)
        except AttributeError:
            logging.warning("PVE %s adapter has no place_limit_gtx_perp — maker path unavailable", self.pair)
            return "0", None
        except Exception as e:
            logging.warning("PVE %s maker place exc: %s", self.pair, e)
            return "0", None
        if o and o.oid and o.oid != "0":
            return str(o.oid), o
        return "0", None

    # ══════════════════════════════════════════════════════════════
    # FILL RECONCILIATION (Upgrade #1) — volume integrity
    # ══════════════════════════════════════════════════════════════
    def _real_pos(self) -> D:
        """Abs real perp position qty for this pair from the exchange.
        Returns 0 if flat OR unverifiable (positions read failed/empty) — callers
        use a *delta* so an outage degrades to 'unverified' (no volume minted),
        never to a false fill."""
        if not PVE_VERIFY_FILLS:
            return D(0)
        try:
            positions = self.x.perps_positions()
        except Exception as e:
            logging.warning("PVE %s pos-read exc: %s", self.pair, e)
            return D(0)
        return abs(positions.get(self.pair, D(0)))

    def _real_pos_signed(self) -> D:
        """Signed real perp position (negative=short, positive=long) for this pair.
        0 if flat OR unverifiable. Used by the accumulation guard to sync inv_qty
        from exchange truth each tick (2026-07-14 fix). Defensive: any non-numeric
        or read failure → D(0) (treat as unverifiable, never crash the tick)."""
        if not PVE_VERIFY_FILLS:
            return D(0)
        try:
            positions = self.x.perps_positions()
            val = positions.get(self.pair, D(0))
            return val if isinstance(val, D) else D(str(val))
        except Exception as e:
            logging.warning("PVE %s pos-read exc: %s", self.pair, e)
            return D(0)

    def _verify_fill(self, pos_before: D, expected: D, leg: str) -> tuple[D, bool]:
        """Confirm an IOC actually filled by position delta.

        Returns (real_qty, verified). verified=True only when the exchange shows a
        position change ≥ half the expected qty — that is the *only* proof SoDEX
        gives that the order crossed (no fills feed exists). On open, real_qty is
        the verified inventory to track; volume is minted only when verified.

        Polls within a bounded settle window: a real fill that the positions
        endpoint hasn't yet reflected appears within a retry or two; a true
        phantom never does. This keeps settle-lag from false-flagging a real
        open (which would otherwise re-open next tick → 2× exposure).
        # ponytail: fixed poll/sleep; replace with an order-status/fills API when
        # SoDEX exposes one (then no settle guessing is needed).
        """
        if not PVE_VERIFY_FILLS:
            return expected, True
        for attempt in range(max(1, PVE_FILL_SETTLE_TRIES)):
            delta = abs(self._real_pos() - pos_before)
            if delta >= expected / 2:
                return (delta if delta > 0 else expected), True
            if attempt < PVE_FILL_SETTLE_TRIES - 1 and PVE_FILL_SETTLE_SEC > 0:
                time.sleep(PVE_FILL_SETTLE_SEC)
        self._phantom_count += 1
        logging.warning("PVE %s PHANTOM %s: oid returned but position delta=%s "
                        "(expected ~%s) — no volume minted [phantom#%d]",
                        self.pair, leg, float(delta), float(expected),
                        self._phantom_count)
        return D(0), False

    # ══════════════════════════════════════════════════════════════
    # F1 (2026-06-29): MAKER TICK — post-only inside-spread open/close
    # ══════════════════════════════════════════════════════════════
    def _check_maker_fill(self) -> bool:
        """Check if pending_maker order filled via real position delta.
        OPEN fill: update inv_qty/inv_cost, mint volume.
        CLOSE fill (is_close): settle PnL + RT, record ledger, reset inventory.
        Stale → cancel + clear. ponytail: _real_pos delta recon; upgrade if order-status API."""
        if not self.pending_maker:
            return False
        pm = self.pending_maker
        is_close = pm.get("is_close", False)
        pos = self._real_pos()
        if is_close:
            # Close filled when position delta drops toward 0 (was inv_qty, now ~0)
            if pos <= self.inv_qty / 2:
                # Settle close: PnL + RT (mirror taker close logic)
                close_qty = self.inv_qty
                if pm["side"] == "buy":  # closing a SHORT
                    close_notional = close_qty * pm["px"]
                    pnl = self.inv_cost - close_notional
                else:  # closing a LONG
                    close_notional = close_qty * pm["px"]
                    pnl = close_notional - self.inv_cost
                _fee = D("0.00012")  # maker 0.012%/side
                _rt_fees = (self.inv_cost + close_notional) * _fee
                pnl_net = pnl - _rt_fees   # true net after both-side maker fees
                self._total_rt += 1
                self._total_pnl += pnl_net
                self._daily_loss += max(D(0), -pnl_net)  # B39: accumulate true net loss
                self._total_vol += close_notional
                rt_id = f"PVE-{self.pair.replace('-','_')}-{self._total_rt}"
                try:
                    self.led.fill("PVE", "P", self.pair, "buy" if pm["side"]=="sell" else "sell",
                                  self.inv_cost/close_qty if close_qty>0 else pm["px"],
                                  close_qty, self.inv_cost*_fee, True, rt_id)
                    self.led.fill("PVE", "P", self.pair, pm["side"], pm["px"], close_qty,
                                  close_notional*_fee, True, rt_id)
                    self.led.rt_close(rt_id, "PVE", self.pair,
                                      self.inv_cost + close_notional, pnl)
                except Exception as _e:
                    logging.warning("PVE %s maker close-ledger exc: %s", self.pair, _e)
                logging.info("PVE %s MAKER-CLOSE-FILLED gross=$%.4f net=$%.4f RT=%d",
                             self.pair, float(pnl), float(pnl_net), self._total_rt)
                self.inv_qty = D(0)
                self.inv_cost = D(0)
                self._inv_open_ts = 0.0
                self.pending_maker = {}
                self._save_state()
                return True
        else:
            # Open filled when position delta ≥ half pending qty
            if pos >= pm["qty"] / 2:
                self.inv_qty = pos if pos > 0 else pm["qty"]
                self.inv_cost = self.inv_qty * pm["px"]
                self._inv_open_ts = time.time()   # B39: track when inventory opened
                self._total_vol += self.inv_cost
                self._last_order_ts = time.time()
                logging.info("PVE %s MAKER-FILLED %s qty=%s px=%s oid=%s vol=$%.2f",
                             self.pair, pm["side"], float(self.inv_qty), float(pm["px"]),
                             pm["oid"], float(self.inv_cost))
                self.pending_maker = {}
                return True
        # Stale check
        if time.time() - pm["ts"] > self._maker_max_age_s:
            logging.info("PVE %s maker EXPIRED (no fill %ds) oid=%s — re-quote next tick",
                         self.pair, int(time.time() - pm["ts"]), pm["oid"])
            if self._cancel_pending_maker(pm):
                self.pending_maker = {}
        return False

    def _cancel_pending_maker(self, pending: dict) -> bool:
        """Cancel a stale maker order; fail closed if cancellation is unconfirmed."""
        try:
            order = type("O", (), {
                "oid": pending["oid"], "pair": self.pair,
                "cl_ord_id": "", "side": pending["side"],
            })()
            if not hasattr(self.x, "cancel"):
                return False
            cancelled = self.x.cancel(order)
            if cancelled is False:
                logging.error(
                    "PVE %s maker cancel UNCONFIRMED oid=%s — keep pending; no re-quote",
                    self.pair, pending["oid"])
                return False
            return True
        except Exception as exc:
            logging.error("PVE %s maker cancel failed oid=%s: %s",
                          self.pair, pending.get("oid"), exc)
            return False

    def _maker_tick(self, bk, mid: D, qty: D) -> dict:
        """Maker execution: post-only limit inside spread.
        OPEN  flat: BUY@bid−off (long) / SELL@ask+off (short)
        CLOSE have-inv: opposite side maker, reduce-only
        oid=0 = would cross → skip cleanly (no ghost, no volume minted).
        Resting orders tracked in pending_maker to prevent re-quote spam."""
        # Step 1: if a maker order is pending, check fill FIRST (don't spam new orders)
        if self.pending_maker:
            filled = self._check_maker_fill()
            if filled and self.inv_qty > 0:
                # Just opened via maker fill → next tick will close. Return fill event.
                return {"action": "maker_filled_open", "oid": "",
                        "qty": float(self.inv_qty), "direction": "long"}
            if self.pending_maker:
                if (PVE_PAUSE_FILE.exists()
                        and self.pending_maker.get("is_close")
                        and time.time() - self.pending_maker["ts"] >= self._inv_max_hold_s):
                    pm = self.pending_maker
                    if not self._cancel_pending_maker(pm):
                        return {"action": "skip", "reason": "maker_cancel_unconfirmed"}
                    self.pending_maker = {}
                    logging.warning("PVE %s CLOSE-ONLY maker aged out; reduce-only fallback",
                                    self.pair)
                    return self._force_close_taker(
                        self._effective_direction(), bk, D(str(pm["qty"])))
                # Still resting → skip this tick (let it fill or expire)
                return {"action": "skip", "reason": "maker_resting"}
        # A close order may expire at the normal maker max-age before the position
        # reaches its max hold. Re-quoting used to reset the order age forever, so
        # the reduce-only fallback was never reached. Position age is the invariant.
        position_hold_s = (
            time.time() - self._inv_open_ts if self._inv_open_ts > 0 else 0
        )
        if (self.inv_qty > 0 and PVE_PAUSE_FILE.exists()
                and position_hold_s >= self._inv_max_hold_s):
            logging.warning(
                "PVE %s CLOSE-ONLY position aged out at %ds; reduce-only fallback",
                self.pair, int(position_hold_s))
            return self._force_close_taker(
                self._effective_direction(), bk, self.inv_qty)
        d = self._effective_direction()
        off = PVE_MAKER_OFFSET_TICKS
        # ── ACCUMULATION GUARD (2026-07-14 fix, defense-in-depth) ──
        # Root cause of the -$8.58 short-accumulation: fill-detection read 0 (broken
        # positions CLI) → engine thought it was flat → re-opened every tick → stacked
        # shorts to -15.7 (vs $130 cap). Now sync inv_qty from the REAL exchange
        # position each tick: if a position already exists we adopt it and go to CLOSE
        # (never stack a second open); if the exchange is flat but we think we hold,
        # reset. This makes over-accumulation impossible even if fill detection lags.
        real_signed = self._real_pos_signed()
        real_abs = abs(real_signed)
        if real_abs >= qty / 2:
            self._inventory_direction = "short" if real_signed < 0 else "long"
            if self.inv_qty <= 0:
                self.inv_qty = real_abs
                logging.warning("PVE %s ACCUM-GUARD: adopt untracked real pos %.4f "
                                "(signed %.4f) → CLOSE only", self.pair,
                                float(real_abs), float(real_signed))
            # A close-only adoption can set quantity before this method has a book.
            # Seed a neutral mark basis here so max-hold and reduce-only fallback are
            # active immediately; never leave recovered exposure with cost=0.
            if self.inv_cost <= 0:
                self.inv_cost = real_abs * mid
        elif self.inv_qty > 0:
            logging.info("PVE %s: exchange flat but inv_qty=%.4f → reset flat",
                         self.pair, float(self.inv_qty))
            self.inv_qty = D(0)
            self.inv_cost = D(0)
            self._inventory_direction = None
        if self.inv_qty <= 0:
            # ── OPEN ──
            # Exchange position reads can lag one tick after a close. The outer
            # pause gate may therefore enter drain-only, then reconciliation above
            # discovers the account is flat. Recheck here so that transition can
            # never turn into a new risk-increasing order in the same tick.
            if PVE_PAUSE_FILE.exists() and not self._honest_ratio_recovery_active():
                return {"action": "skip", "reason": "pve_pause_open_blocked"}
            # ADAPTIVE: only OPEN a pair the selector currently rides (trending). Not
            # selected / stale file → skip (don't force a trade with no tailwind).
            if self._adaptive_blocked():
                return {"action": "skip", "reason": "adaptive_not_selected", "direction": d}
            if self._honest_ratio_recovery_active():
                recovery_drift = self._pair_drift()
                recovery_aligned = (
                    (d == "long" and recovery_drift == "RISING")
                    or (d == "short" and recovery_drift == "FALLING")
                )
                if not recovery_aligned:
                    return {"action": "skip", "reason": "recovery_drift_unconfirmed",
                            "direction": d, "drift": recovery_drift}
            # RC2 (2026-07-18): never OPEN against the pair's own drift. This is the
            # single change that structurally removes the Jul-17 loss mechanism
            # (short into a rallying SOL). Close is never vetoed (see below).
            _vetoed, _vreason = self._drift_veto(d)
            if _vetoed:
                logging.info("PVE %s MAKER-OPEN drift-veto: dir=%s %s",
                             self.pair, d, _vreason)
                return {"action": "skip", "reason": _vreason, "direction": d}
            # U4: adverse-selection gate (thin book / extreme OBI against our side).
            _ablock, _areason = self._adverse_gate(d)
            if _ablock:
                logging.info("PVE %s MAKER-OPEN adverse-gate: dir=%s %s",
                             self.pair, d, _areason)
                return {"action": "skip", "reason": _areason, "direction": d}
            if d == "short":
                side = "sell"
                px = self._maker_price("sell", bk.bid, bk.ask, off)
            else:
                side = "buy"
                px = self._maker_price("buy", bk.bid, bk.ask, off)
            oid, _o = self._place_maker(side, px, qty, reduce_only=False)
            if oid == "0":
                logging.info("PVE %s maker OPEN skip (would cross) px=%s dir=%s",
                             self.pair, float(px), d)
                return {"action": "skip", "reason": "maker_cross_reject",
                        "direction": d}
            # Track resting order (do NOT set inv_qty until fill confirmed)
            self.pending_maker = {"oid": oid, "qty": qty, "side": side,
                                  "px": px, "ts": time.time()}
            self._last_order_ts = time.time()
            logging.info("PVE %s MAKER-OPEN %s px=%s oid=%s dir=%s",
                         self.pair, d, float(px), oid, d)
            return {"action": side, "oid": oid, "qty": float(qty),
                    "px": float(px), "direction": d, "maker": True}
        else:
            # ── CLOSE (reduce-only maker) ──
            close_qty = self.inv_qty
            force_close_due = False
            if d == "short":
                side = "buy"
                px = self._maker_price("buy", bk.bid, bk.ask, off)
                # B39 PROFITABLE-CLOSE GATE: for a SHORT, closing via BUY is only
                # net-positive when close_buy_px < open_sell_px. If price has risen
                # above our entry, placing the close now locks in a guaranteed loss.
                # Wait for price to drop back. After _inv_max_hold_s, close anyway
                # (accept loss) to cap maximum directional exposure.
                if self.inv_cost > 0 and close_qty > 0:
                    open_px_pu = self.inv_cost / close_qty
                    hold_s = time.time() - self._inv_open_ts
                    capture_bps = (open_px_pu - px) / open_px_pu * D(10000)
                    required_capture = (
                        PVE_HONEST_RECOVERY_MIN_CAPTURE_BPS
                        if self._honest_ratio_recovery_active() else D(0)
                    )
                    capture_insufficient = (
                        capture_bps < required_capture
                        if required_capture > 0 else capture_bps <= 0
                    )
                    if capture_insufficient:
                        if hold_s < self._inv_max_hold_s:
                            logging.info(
                                "PVE %s CLOSE-WAIT: capture=%.2fbps < %.2fbps "
                                "px=%s open=%s hold=%ds < max=%ds",
                                self.pair, float(capture_bps), float(required_capture),
                                float(px), float(open_px_pu), int(hold_s),
                                int(self._inv_max_hold_s))
                            return {"action": "skip", "reason": (
                                "recovery_capture_wait" if required_capture > 0
                                else "close_wait_price_recovery")}
                        logging.warning(
                            "PVE %s CLOSE-FORCED: hold %ds >= max %ds, "
                            "capture %.2fbps < %.2fbps px=%s open=%s",
                            self.pair, int(hold_s), int(self._inv_max_hold_s),
                            float(capture_bps), float(required_capture),
                            float(px), float(open_px_pu))
                        force_close_due = True
            else:
                side = "sell"
                px = self._maker_price("sell", bk.bid, bk.ask, off)
                # Symmetric gate for LONG direction
                if self.inv_cost > 0 and close_qty > 0:
                    open_px_pu = self.inv_cost / close_qty
                    hold_s = time.time() - self._inv_open_ts
                    capture_bps = (px - open_px_pu) / open_px_pu * D(10000)
                    required_capture = (
                        PVE_HONEST_RECOVERY_MIN_CAPTURE_BPS
                        if self._honest_ratio_recovery_active() else D(0)
                    )
                    capture_insufficient = (
                        capture_bps < required_capture
                        if required_capture > 0 else capture_bps <= 0
                    )
                    if capture_insufficient:
                        if hold_s < self._inv_max_hold_s:
                            logging.info(
                                "PVE %s CLOSE-WAIT (LONG): capture=%.2fbps < %.2fbps "
                                "px=%s open=%s hold=%ds < max=%ds",
                                self.pair, float(capture_bps), float(required_capture),
                                float(px), float(open_px_pu), int(hold_s),
                                int(self._inv_max_hold_s))
                            return {"action": "skip", "reason": (
                                "recovery_capture_wait" if required_capture > 0
                                else "close_wait_price_recovery")}
                        logging.warning(
                            "PVE %s CLOSE-FORCED (LONG): hold %ds >= max %ds, "
                            "capture %.2fbps < %.2fbps",
                            self.pair, int(hold_s), int(self._inv_max_hold_s),
                            float(capture_bps), float(required_capture))
                        force_close_due = True
            oid, _o = self._place_maker(side, px, close_qty, reduce_only=True)
            if oid == "0":
                logging.info("PVE %s maker CLOSE skip (would cross) px=%s", self.pair, float(px))
                if (PVE_MAKER_TAKER_FALLBACK
                        and (force_close_due or PVE_PAUSE_FILE.exists())):
                    return self._force_close_taker(d, bk, close_qty)
                return {"action": "skip", "reason": "maker_cross_reject_close"}
            # Track close order; on fill, settle PnL + RT (mirror taker close logic)
            self.pending_maker = {"oid": oid, "qty": close_qty, "side": side,
                                  "px": px, "ts": time.time(), "is_close": True}
            self._last_order_ts = time.time()
            logging.info("PVE %s MAKER-CLOSE px=%s oid=%s", self.pair, float(px), oid)
            return {"action": side, "oid": oid, "qty": float(close_qty),
                    "px": float(px), "direction": d, "maker": True}

    # ══════════════════════════════════════════════════════════════
    # MAIN TICK — dipanggil setiap loop
    # ══════════════════════════════════════════════════════════════
    def tick(self) -> dict:
        """Satu siklus engine. Returns dict dengan hasil.
        
        Returns:
            {"action": "buy"|"sell"|"skip", "oid": str, "reason": str}
        """
        if not PVE_ENABLED:
            return {"action": "skip", "reason": "disabled"}
        if self.pair.upper() in PVE_BLOCKED_PAIRS:
            return {"action": "skip", "reason": f"pair_blocked_{self.pair}"}
        # A safety pause blocks risk-increasing opens, never position-reducing closes.
        # Keeping engines alive in drain-only mode prevents unmanaged exposure.
        if PVE_PAUSE_FILE.exists() and self.inv_qty <= 0 and not self.pending_maker:
            # Reconcile exchange truth before declaring this engine flat. A position
            # unknown to the local DB still has to reach the close path during a pause.
            real_signed = self._real_pos_signed()
            if real_signed == 0 and not self._honest_ratio_recovery_active():
                return {"action": "skip", "reason": "pve_pause_open_blocked"}
            if real_signed != 0:
                self.inv_qty = abs(real_signed)
                self._inventory_direction = "short" if real_signed < 0 else "long"
                logging.warning(
                    "PVE %s CLOSE-ONLY adopt real pos %.6f (%s)", self.pair,
                    float(self.inv_qty), self._inventory_direction)
        if self._paused:
            return {"action": "skip", "reason": "paused"}
        if self._check_daily_loss():
            self._paused = True
            logging.warning("PVE %s PAUSED: daily loss limit $%s reached",
                           self.pair, float(PVE_DAILY_LOSS_LIMIT))
            return {"action": "skip", "reason": "daily_loss_limit"}
        # F3d (2026-06-29): weekly NET kill-switch — pause if week NET below floor.
        if self._check_weekly_net_kill():
            self._paused = True
            return {"action": "skip", "reason": "weekly_net_kill"}
        # F3a (2026-06-29): REGIME PAUSE GATE — skip trading in BEAR market.
        # Insight operator: E1/E2 RUSAK saat BEAR (adverse selection trending market).
        # Pause total, bukan switch direction, karena rugi terlepas arah.
        # Exception: jika ada inventory yang harus di-close (cut loss), tetap allow close.
        # FIX BUG (2026-07-07): hapus self.direction=="auto" check — gate harus aktif
        # terlepas dari direction (explicit long/short pun tetap pause saat BEAR, karena
        # adverse selection trending market rugi terlepas arah per insight operator).
        if PVE_PAUSE_ON_BEAR and self.inv_qty <= 0:
            regime = self._regime()
            if regime == "BEAR":
                return {"action": "skip", "reason": "regime_bear_pause"}
        # Skip non-selected candidates before spawning an orderbook CLI process. Keep
        # a truth check so an out-of-band position is still adopted and closed.
        if self.inv_qty <= 0 and not self.pending_maker and self._adaptive_blocked():
            real_signed = self._real_pos_signed()
            if real_signed == 0:
                return {"action": "skip", "reason": "adaptive_not_selected"}
            self.inv_qty = abs(real_signed)
            self._inventory_direction = "short" if real_signed < 0 else "long"
            logging.warning("PVE %s adopt non-selected real pos %.6f (%s) for close",
                            self.pair, float(self.inv_qty), self._inventory_direction)
        # F1 (2026-06-29): cooldown applies AFTER a completed round-trip (fill), not after
        # order placement. Maker re-quote needs to be aggressive (cancel stale + re-place
        # fresh price). Blocking maker re-quote by cooldown = order stuck at stale price
        # → never fills → 0 volume. Skip cooldown for maker path when no fill this cycle.
        is_maker = PVE_MAKER_PATH
        if not is_maker and self._check_cooldown():
            return {"action": "skip", "reason": "cooldown"}

        # ── Fetch orderbook ──
        try:
            bk = self.x.book(self.pair)  # book() handles both spot & perps
        except Exception as e:
            logging.warning("PVE %s book fetch failed: %s", self.pair, e)
            return {"action": "skip", "reason": "book_fail"}
        
        if bk.bid <= 0 or bk.ask <= 0:
            return {"action": "skip", "reason": "no_book"}
        
        spread_pct = (bk.ask - bk.bid) / bk.bid * 100
        if not self._check_spread_ok(D(str(spread_pct))):
            return {"action": "skip", "reason": f"spread_too_thin_{spread_pct:.3f}%"}

        # F3b (2026-06-29): GOVERNOR EV GATE — block negative-expectancy trades.
        # Skip open if governor rejects (asset/prob/EV). Close (cut loss) always allowed.
        if self.inv_qty <= 0 and not self.pending_maker:
            blocked, position_reason = self._global_position_gate()
            if blocked:
                return {"action": "skip", "reason": position_reason}
            approved, reason = self._governor_gate(bk)
            if not approved:
                return {"action": "skip", "reason": f"gov_reject_{reason}"}
        
        # ── Calculate qty (refactored to _calc_qty for maker/taker reuse) ──
        mid = (bk.bid + bk.ask) / 2
        qty = self._calc_qty(mid)
        if qty <= 0:
            return {"action": "skip", "reason": "qty_zero"}
        # Close-only recovery may adopt a real position before an orderbook is
        # available. Seed a neutral mark basis here for both maker and taker close
        # paths so an external position is never reported as pure profit from zero.
        if self.inv_qty > 0 and self.inv_cost <= 0:
            self.inv_cost = self.inv_qty * mid
        if self.inv_qty <= 0 and not self.pending_maker:
            allowed, ratio_reason = self._honest_ratio_open_gate(qty * mid * 2)
            if not allowed:
                return {"action": "skip", "reason": ratio_reason}

        # ── F1 (2026-06-29): MAKER path dispatch (post-only GTC inside-spread) ──
        # Maker path active when TE_PVE_MAKER_PATH=1 AND spread is wide enough that
        # half-spread covers maker fee (else maker capture is negative → skip to taker
        # fallback or skip entirely). Maker cuts fee 0.04%→0.012%/side (70% saving).
        if PVE_MAKER_PATH and self._maker_viable(bk.bid, bk.ask):
            return self._maker_tick(bk, mid, qty)

        # U3: maker not viable (spread too thin to capture > fee). In profit-capture
        # mode, do NOT OPEN via the higher-fee taker path — that is an even larger net
        # loss. Only guards OPENs (inv_qty<=0); an existing position still falls through
        # to the taker CLOSE below (exit is always permitted, even at a thin spread).
        if PVE_MAKER_PATH and PVE_MIN_CAPTURE_BPS > 0 and self.inv_qty <= 0:
            return {"action": "skip", "reason": "u3_spread_below_capture_floor"}

        # ── Decide action (direction-aware) ──
        d = self._effective_direction()
        if self.inv_qty <= 0:
            # No open position → open one
            # ADAPTIVE: only open pairs the selector currently rides (trending).
            if self._adaptive_blocked():
                return {"action": "skip", "reason": "adaptive_not_selected", "direction": d}
            # RC2 (2026-07-18): per-pair drift veto — block adverse-direction opens
            # (short into a rising pair / long into a falling pair). Same defense as
            # the maker path; close (below) is never vetoed.
            _vetoed, _vreason = self._drift_veto(d)
            if _vetoed:
                logging.info("PVE %s OPEN drift-veto: dir=%s %s", self.pair, d, _vreason)
                return {"action": "skip", "reason": _vreason, "direction": d}
            # U4: adverse-selection gate (thin book / extreme OBI against our side).
            _ablock, _areason = self._adverse_gate(d)
            if _ablock:
                logging.info("PVE %s OPEN adverse-gate: dir=%s %s", self.pair, d, _areason)
                return {"action": "skip", "reason": _areason, "direction": d}
            if d == "short":
                # SHORT mode: SELL at bid (taker — crosses spread, guaranteed fill)
                pos_before = self._real_pos()
                oid = self._place_sell(bk.bid, qty)
                if oid:
                    real_qty, verified = self._verify_fill(pos_before, qty, "short-open")
                    if not verified:
                        return {"action": "skip", "reason": "short_open_phantom"}
                    self.inv_qty = real_qty
                    self.inv_cost = real_qty * bk.bid  # proceeds from short open at bid
                    self._last_order_ts = time.time()
                    self._total_vol += self.inv_cost
                    logging.info("PVE %s SHORT qty=%s @ bid=%s oid=%s vol=$%.2f dir=%s",
                                 self.pair, float(real_qty), float(bk.bid), oid,
                                 float(self.inv_cost), d)
                    self._save_state()
                    return {"action": "sell", "oid": oid, "qty": float(real_qty),
                            "px": float(bk.bid), "direction": d}
                return {"action": "skip", "reason": "short_open_failed"}
            else:
                # LONG mode: BUY at ask (taker — crosses spread, guaranteed fill)
                pos_before = self._real_pos()
                oid = self._place_buy(bk.ask, qty)
                if oid:
                    real_qty, verified = self._verify_fill(pos_before, qty, "long-open")
                    if not verified:
                        return {"action": "skip", "reason": "long_open_phantom"}
                    self.inv_qty = real_qty
                    self.inv_cost = real_qty * bk.ask  # cost basis at ask
                    self._last_order_ts = time.time()
                    self._total_vol += self.inv_cost
                    logging.info("PVE %s LONG qty=%s @ ask=%s oid=%s vol=$%.2f dir=%s",
                                 self.pair, float(real_qty), float(bk.ask), oid,
                                 float(self.inv_cost), d)
                    self._save_state()
                    return {"action": "buy", "oid": oid, "qty": float(real_qty),
                            "px": float(bk.ask), "direction": d}
                return {"action": "skip", "reason": "long_open_failed"}
        else:
            # Have open position → close it
            close_qty = self.inv_qty
            if d == "short":
                # Close short: BUY at ask (taker — crosses spread, guaranteed fill)
                pos_before = self._real_pos()
                oid = self._place_buy(bk.ask, close_qty)
                if oid:
                    _filled, verified = self._verify_fill(pos_before, close_qty, "short-close")
                    if not verified:
                        # phantom close: position unchanged → keep inventory, retry
                        # next tick. NEVER flatten (guardian rule).
                        return {"action": "skip", "reason": "short_close_phantom"}
                    close_notional = close_qty * bk.ask
                    pnl = self.inv_cost - close_notional  # short: bid_open - ask_close
                    self._total_rt += 1
                    self._total_pnl += pnl
                    self._daily_loss += max(D(0), -pnl)
                    self._total_vol += close_notional
                    # B39: record to ledger so vol_perps_week counts PVE volume
                    rt_id = f"PVE-{self.pair.replace('-','_')}-{self._total_rt}"
                    open_notional = self.inv_cost
                    _fee = D("0.0002")  # ponytail: taker 0.02%/side estimate
                    try:
                        open_px = open_notional / close_qty if close_qty > 0 else bk.ask
                        self.led.fill("PVE", "P", self.pair, "sell", open_px, close_qty,
                                      open_notional * _fee, False, rt_id)
                        self.led.fill("PVE", "P", self.pair, "buy", bk.bid, close_qty,
                                      close_notional * _fee, False, rt_id)
                        self.led.rt_close(rt_id, "PVE", self.pair,
                                          open_notional + close_notional, pnl)
                    except Exception as _e:
                        logging.warning("PVE %s fill-record exc: %s", self.pair, _e)
                    logging.info("PVE %s SHORT-CLOSE qty=%s @ ask=%s oid=%s PnL=$%.4f RT=%d",
                                 self.pair, float(close_qty), float(bk.ask), oid,
                                 float(pnl), self._total_rt)
                    self.inv_qty = D(0)
                    self.inv_cost = D(0)
                    self._last_order_ts = time.time()
                    self._save_state()
                    return {"action": "buy", "oid": oid, "qty": float(close_qty),
                            "px": float(bk.ask), "pnl": float(pnl), "direction": d}
                return {"action": "skip", "reason": "short_close_failed"}
            else:
                # Close long: SELL at bid (taker — crosses spread, guaranteed fill)
                pos_before = self._real_pos()
                oid = self._place_sell(bk.bid, close_qty)
                if oid:
                    _filled, verified = self._verify_fill(pos_before, close_qty, "long-close")
                    if not verified:
                        # phantom close: position unchanged → keep inventory, retry
                        # next tick. NEVER flatten (guardian rule).
                        return {"action": "skip", "reason": "long_close_phantom"}
                    sell_notional = close_qty * bk.bid
                    pnl = sell_notional - self.inv_cost  # long: bid_close - ask_open
                    self._total_rt += 1
                    self._total_pnl += pnl
                    self._daily_loss += max(D(0), -pnl)
                    self._total_vol += sell_notional
                    # B39: record to ledger so vol_perps_week counts PVE volume
                    rt_id = f"PVE-{self.pair.replace('-','_')}-{self._total_rt}"
                    open_notional = self.inv_cost
                    _fee = D("0.0002")  # ponytail: taker 0.02%/side estimate
                    try:
                        open_px = open_notional / close_qty if close_qty > 0 else bk.bid
                        self.led.fill("PVE", "P", self.pair, "buy", open_px, close_qty,
                                      open_notional * _fee, False, rt_id)
                        self.led.fill("PVE", "P", self.pair, "sell", bk.ask, close_qty,
                                      sell_notional * _fee, False, rt_id)
                        self.led.rt_close(rt_id, "PVE", self.pair,
                                          open_notional + sell_notional, pnl)
                    except Exception as _e:
                        logging.warning("PVE %s fill-record exc: %s", self.pair, _e)
                    logging.info("PVE %s LONG-CLOSE qty=%s @ bid=%s oid=%s PnL=$%.4f RT=%d",
                                 self.pair, float(close_qty), float(bk.bid), oid,
                                 float(pnl), self._total_rt)
                    self.inv_qty = D(0)
                    self.inv_cost = D(0)
                    self._last_order_ts = time.time()
                    self._save_state()
                    return {"action": "sell", "oid": oid, "qty": float(close_qty),
                            "px": float(bk.bid), "pnl": float(pnl), "direction": d}
                return {"action": "skip", "reason": "long_close_failed"}
    
    # ══════════════════════════════════════════════════════════════
    # STATS
    # ══════════════════════════════════════════════════════════════
    def stats(self) -> dict:
        return {
            "pair": self.pair,
            "inv_qty": float(self.inv_qty),
            "inv_cost": float(self.inv_cost),
            "total_rt": self._total_rt,
            "total_pnl": float(self._total_pnl),
            "total_vol": float(self._total_vol),
            "paused": self._paused,
            "daily_loss": float(self._daily_loss),
        }
    
    def summary(self) -> str:
        s = self.stats()
        return (f"PVE {s['pair']}: RT={s['total_rt']} PnL=${s['total_pnl']:.4f} "
                f"vol=${s['total_vol']:.2f} inv={s['inv_qty']:.4f} "
                f"{'⏸️' if s['paused'] else '▶️'}")


# ── Factory ──
def create_engines(adapter, ledger, pairs_str: str = "") -> list:
    """Create PerpsVolumeEngine instances for configured pairs."""
    if not PVE_ENABLED:
        return []
    pairs = [p.strip() for p in (pairs_str or PVE_PAIRS).split(",") if p.strip()]
    engines = []
    for pair in pairs:
        if pair.upper() in PVE_BLOCKED_PAIRS:
            logging.warning("PVE engine skipped blocked pair: %s", pair)
            continue
        try:
            eng = PerpsVolumeEngine(adapter, ledger, pair, direction=PVE_DIRECTION)
            engines.append(eng)
            logging.info("PVE engine created: %s direction=%s", pair, PVE_DIRECTION)
        except Exception as e:
            logging.warning("PVE engine creation failed for %s: %s", pair, e)
    return engines
