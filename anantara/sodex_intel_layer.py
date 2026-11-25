#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║  SoDEX Intel Layer v1.0 — Sentiment + Macro Overlay        ║
║  Integrates: intelligence.py + sentiment + macro → autofarm║
╚══════════════════════════════════════════════════════════════╝

Provides:
  get_regime()          → {score, label, multiplier, flags}
  should_trade()        → True/False with reason
  get_capital_mult()    → 0.5x / 1.0x / 2.0x based on regime
  get_spread_min()      → dynamic spread threshold
  circuit_breaker_ok()  → True/False (macro emergency stop)

Data sources (no Redis required for basic mode):
  Fear & Greed: alternative.me API (free, no key)
  Optional Redis: sentiment_collector data if Redis is running

USAGE:
  from anantara.sodex_intel_layer import IntelLayer
  intel = IntelLayer()
  regime = intel.get_regime()
  if intel.should_trade():
      capital = base_capital * intel.get_capital_mult()
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import urllib.request
import urllib.error

try:
    from anantara import macro_data, macro_policy
except ImportError:  # flat script context
    import macro_data  # type: ignore
    import macro_policy  # type: ignore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [INTEL] %(message)s")
log = logging.getLogger("sodex_intel")

# ── Redis (optional) ───────────────────────────────────────
_redis = None

def _get_redis():
    """Lazy Redis connection (optional)."""
    global _redis
    if _redis is not None:
        return _redis
    try:
        import redis
        r = redis.Redis(host="localhost", port=6379, db=0, socket_timeout=2)
        r.ping()
        _redis = r
        return r
    except Exception:
        _redis = False
        return None

# ── Fear & Greed (direct API, no deps) ──────────────────────
_FG_CACHE = {"value": 50, "label": "Neutral", "ts": 0}
_FG_TTL = 3600  # cache 1 hour

def fetch_fear_greed() -> dict:
    """Fetch Fear & Greed Index from alternative.me (free, no key)."""
    global _FG_CACHE
    now = time.time()
    if now - _FG_CACHE["ts"] < _FG_TTL:
        return _FG_CACHE

    try:
        url = "https://api.alternative.me/fng/?limit=1"
        req = urllib.request.Request(url, headers={"User-Agent": "SoDEX-Intel/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("data"):
                item = data["data"][0]
                _FG_CACHE = {
                    "value": int(item["value"]),
                    "label": item["value_classification"],
                    "ts": now,
                }
                return _FG_CACHE
    except Exception as e:
        log.warning(f"F&G fetch failed: {e}")

    # Return stale cache rather than nothing
    return _FG_CACHE

# ── Intelligence Composite (lightweight, no Redis) ──────────
def compute_intel_score(fg: dict = None) -> dict:
    """
    Compute simplified 0-100 intelligence score.
    Uses F&G as primary signal (proven contrarian indicator).

    Score interpretation:
      0-30  : Extreme Fear   → contrarian opportunity, spreads wide
      30-45 : Fear            → cautious, spreads elevated
      45-55 : Neutral         → baseline
      55-70 : Greed           → spreads tightening
      70-100: Extreme Greed   → spreads tightest, highest risk
    """
    if fg is None:
        fg = fetch_fear_greed()

    fg_value = fg["value"]
    fg_label = fg["label"]

    # Contrarian: invert F&G
    # Extreme Fear (0) → high opportunity (80-100)
    # Extreme Greed (100) → low opportunity (0-20)
    contrarian = 100 - fg_value

    # Try Redis for richer data
    r = _get_redis()
    bonus = 0
    flags = []

    if r:
        try:
            # Funding rate tilt
            funding_raw = r.get("sentiment:funding_avg")
            if funding_raw:
                funding = json.loads(funding_raw)
                btc_fund = float(funding.get("BTC", 0))
                if btc_fund > 0.05:
                    bonus -= 8  # longs crowded → bearish
                    flags.append("FUNDING_OVERHEATED")
                elif btc_fund < -0.03:
                    bonus += 8  # shorts crowded → contrarian bullish
                    flags.append("FUNDING_CONTRARIAN")

            # Liquidation tilt
            liq_raw = r.get("sentiment:liq_1h")
            if liq_raw:
                liq = json.loads(liq_raw)
                long_liq = float(liq.get("long_liq_usd", 0))
                if long_liq > 50_000_000:
                    bonus += 5  # massive long liq → bounce signal
                    flags.append("LONG_LIQ_BOUNCE")

            # Stablecoin tilt
            stable_raw = r.get("sentiment:global")
            if stable_raw:
                global_data = json.loads(stable_raw)
                stable_dom = float(global_data.get("stablecoin_dom", 0))
                if stable_dom > 10:
                    bonus -= 5  # capital fleeing to stables
                    flags.append("RISK_OFF_STABLECOIN")
        except Exception as e:
            log.debug(f"Redis data parse: {e}")

    # Clamp bonus
    bonus = max(-15, min(15, bonus))
    score = max(0, min(100, contrarian + bonus))

    # Determine label (OPPORTUNITY LEVEL, not greed)
    # High score = market fear = opportunity (contrarian)
    # Low score = market greed = danger
    if score >= 70:
        label = "HIGH_OPPORTUNITY"   # Market fearful → spreads wide
    elif score >= 55:
        label = "ELEVATED"           # Above-average spreads
    elif score >= 45:
        label = "NEUTRAL"            # Baseline
    elif score >= 30:
        label = "LOW_OPPORTUNITY"    # Market greedy → spreads tight
    else:
        label = "DANGER_ZONE"        # Extreme greed → avoid

    return {
        "score": score,
        "label": label,
        "fg_value": fg_value,
        "fg_label": fg_label,
        "bonus": bonus,
        "flags": flags,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

# ── PUBLIC API ──────────────────────────────────────────────

class IntelLayer:
    """Lightweight sentiment/macro overlay for SoDEX autofarm."""

    def __init__(self):
        self._last_regime = None
        self._last_check = 0
        self._cache_ttl = 300  # 5 min
        self._last_macro_policy = None
        self._last_macro_check = 0

    def get_macro_policy(self) -> dict:
        """Official US macro policy: cached, defensive-only."""
        now = time.time()
        if self._last_macro_policy and (now - self._last_macro_check) < self._cache_ttl:
            return self._last_macro_policy
        try:
            snap = macro_data.fetch_macro_snapshot_sync()
            ctx = {
                "snapshot": snap,
                "macro_tilt": macro_data.compute_macro_tilt(snap),
                "event_guard": macro_data.event_guard_status(),
                "next_events": macro_data.next_macro_events(limit=3),
            }
            policy = macro_policy.assess_macro_policy(ctx)
        except Exception as exc:
            policy = {
                "level": "UNKNOWN", "sodex_capital_mult": 0.75,
                "sodex_spread_add_pct": 0.04, "active_event_window": False,
                "reason": f"macro policy unavailable: {type(exc).__name__}",
            }
        self._last_macro_policy = policy
        self._last_macro_check = now
        return policy

    def get_regime(self) -> dict:
        """Get current market regime with caching."""
        now = time.time()
        if self._last_regime and (now - self._last_check) < self._cache_ttl:
            return self._last_regime

        fg = fetch_fear_greed()
        regime = compute_intel_score(fg)
        macro_pol = self.get_macro_policy()
        regime["macro_policy"] = macro_pol
        if macro_pol.get("level") not in (None, "NORMAL"):
            regime.setdefault("flags", []).append(f"MACRO_{macro_pol.get('level')}")
        self._last_regime = regime
        self._last_check = now
        return regime

    def should_trade(self) -> tuple[bool, str]:
        """
        Should we deploy capital?
        Trade when: market fearful (wider spreads, more opportunity).
        Don't trade when: extreme greed (F&G > 90), liquidation cascades.
        """
        regime = self.get_regime()
        score = regime["score"]
        fg_value = regime["fg_value"]

        macro_pol = regime.get("macro_policy") or {}
        if macro_pol.get("active_event_window"):
            return False, str(macro_pol.get("reason") or "macro release window active")

        # Circuit breaker: Extreme Greed in market = dangerous
        # (F&G > 85 → contrarian score < 15 → spreads tight, reversal risk)
        if fg_value > 85:
            return False, f"F&G_EXTREME_GREED_{fg_value} — reversal risk, spreads tight"

        # Check Redis for liquidation cascade
        r = _get_redis()
        if r:
            try:
                liq_raw = r.get("sentiment:liq_1h")
                if liq_raw:
                    liq = json.loads(liq_raw)
                    total_liq = float(liq.get("long_liq_usd", 0)) + float(liq.get("short_liq_usd", 0))
                    if total_liq > 200_000_000:
                        return False, f"LIQ_CASCADE_${total_liq/1e6:.0f}M"
            except Exception:
                pass

        return True, "OK"

    def get_capital_mult(self) -> float:
        """
        Dynamic capital multiplier based on regime.
        High fear (high score) = wider spreads → deploy MORE.
        High greed (low score) = tighter spreads → deploy LESS.
        """
        regime = self.get_regime()
        score = regime["score"]
        fg = regime["fg_value"]

        # Base on raw F&G for simplicity
        if fg <= 25:
            base = 2.0   # Extreme Fear → double down (widest spreads)
        elif fg <= 40:
            base = 1.5   # Fear → 1.5x
        elif fg <= 60:
            base = 1.0   # Neutral → normal
        elif fg <= 75:
            base = 0.75  # Greed → reduced
        else:
            base = 0.5   # Extreme Greed → half (tightest spreads)
        macro_mult = float((regime.get("macro_policy") or {}).get("sodex_capital_mult", 1.0) or 1.0)
        return max(0.25, min(2.0, base * macro_mult))

    def get_spread_min(self) -> float:
        """
        Dynamic minimum spread threshold.
        Lower threshold during fear (spreads naturally wider).
        Higher threshold during greed (need more safety margin).
        """
        regime = self.get_regime()
        fg = regime["fg_value"]

        if fg <= 25:
            base = 0.25  # Extreme Fear: spreads naturally wide
        elif fg <= 40:
            base = 0.28
        elif fg <= 60:
            base = 0.30  # Neutral: baseline
        elif fg <= 75:
            base = 0.32
        else:
            base = 0.35  # Extreme Greed: tight spreads, need margin
        macro_add = float((regime.get("macro_policy") or {}).get("sodex_spread_add_pct", 0.0) or 0.0)
        return round(base + macro_add, 3)

    def circuit_breaker_ok(self) -> tuple[bool, str]:
        """
        Macro emergency stop check.
        Returns (True=ok_to_trade, reason).
        """
        regime = self.get_regime()
        flags = regime.get("flags", [])
        macro_pol = regime.get("macro_policy") or {}

        if macro_pol.get("active_event_window"):
            return False, str(macro_pol.get("reason") or "macro release window active")

        if "FUNDING_OVERHEATED" in flags:
            return False, "Funding extremely positive — longs crowded, reversal risk"

        if "RISK_OFF_STABLECOIN" in flags:
            return False, "Capital fleeing to stablecoins — risk-off"

        return True, "OK"

    def summary(self) -> str:
        """One-line summary for logging."""
        regime = self.get_regime()
        trade_ok, reason = self.should_trade()
        cb_ok, cb_reason = self.circuit_breaker_ok()
        mult = self.get_capital_mult()
        spread = self.get_spread_min()

        status = "🟢" if (trade_ok and cb_ok) else "🔴"
        return (
            f"{status} Intel:{regime['score']}({regime['label']}) "
            f"F&G:{regime['fg_value']} "
            f"Mult:{mult:.1f}x Spread≥{spread:.2f}% "
            f"Flags:{','.join(regime['flags']) if regime['flags'] else 'none'} "
            f"| Trade:{reason} CB:{cb_reason}"
        )


# ── CLI ─────────────────────────────────────────────────────
if __name__ == "__main__":
    intel = IntelLayer()
    regime = intel.get_regime()

    print("╔══════════════════════════════════════════════╗")
    print("║  SoDEX Intel Layer — Market Regime Check    ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"  Score:       {regime['score']} ({regime['label']})")
    print(f"  Fear & Greed: {regime['fg_value']} ({regime['fg_label']})")
    print(f"  Bonus:       {regime['bonus']:+.0f}")
    print(f"  Flags:       {', '.join(regime['flags']) if regime['flags'] else 'none'}")
    print(f"  Timestamp:   {regime['ts']}")
    print()
    print(f"  Trade OK:     {intel.should_trade()}")
    print(f"  Capital Mult: {intel.get_capital_mult():.1f}x")
    print(f"  Spread Min:   {intel.get_spread_min():.2f}%")
    print(f"  Circuit Brk:  {intel.circuit_breaker_ok()}")
    print()
    print(f"  {intel.summary()}")
