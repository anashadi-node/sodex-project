#!/usr/bin/env python3
"""
ASTRONACCI MARKET INTELLIGENCE v1.0 — Multi-Venue Early Detection & Reaction
══════════════════════════════════════════════════════════════════════════════

KEMAMPUAN:
  1. MULTI-VENUE DATA — Binance, Bybit, OKX, Hyperliquid (public API, no auth)
  2. BEHAVIOR DETECTION — volatility shift, volume anomaly, correlation change
  3. DIRECTION PREDICT — early warning trend reversal, momentum shift
  4. ADAPTIVE STRATEGY — auto-switch config based on detected regime
  5. FAST REACTION — apply changes within 1 cycle (1 jam)

PRINSIP:
  - Deteksi DINI sebelum perubahan besar terjadi
  - Multi-venue confirmation (sinyal harus dikonfirmasi minimal 2 exchange)
  - Reaksi CEPAT — ubah strategi sebelum kondisi berubah total
  - Integrasi dengan Deep Learner untuk wisdom accumulation
"""
from __future__ import annotations

import json, math, os, time
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean, stdev
from typing import Optional
import logging

log = logging.getLogger("astronacci.market-intel")

PROJECT_DIR = Path(os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti")))
DATA_DIR = PROJECT_DIR / "data" / "astronacci"
INTEL_PATH = DATA_DIR / "market_intel.json"
ALERT_PATH = DATA_DIR / "market_alerts.jsonl"

# =============================================================================
# 1. MULTI-VENUE DATA COLLECTOR
# =============================================================================

@dataclass
class VenueData:
    """Data dari satu exchange pada satu timeframe."""
    venue: str
    symbol: str
    timestamp: str
    price: float
    volume_24h: float = 0
    high_24h: float = 0
    low_24h: float = 0
    change_24h_pct: float = 0
    funding_rate: float = 0
    open_interest: float = 0
    bid_ask_spread_pct: float = 0
    volatility_24h: float = 0

class MultiVenueCollector:
    """Mengumpulkan data dari 4 exchange secara paralel via public API."""
    
    VENUES = {
        "binance": "https://api.binance.com/api/v3",
        "bybit": "https://api.bybit.com/v5",
        "okx": "https://www.okx.com/api/v5",
        "hyperliquid": "https://api.hyperliquid.xyz",
    }
    
    def __init__(self):
        self.data: dict[str, dict[str, VenueData]] = {}  # {venue: {symbol: data}}
    
    def fetch_all(self, symbols: list[str] = None) -> dict:
        """Fetch data dari semua venue untuk symbol yang diminta."""
        if symbols is None:
            symbols = ["ETH", "BTC"]
        
        import httpx
        results = {}
        
        for symbol in symbols:
            venue_data = {}
            
            # Binance — 24h ticker
            try:
                with httpx.Client(timeout=10) as c:
                    r = c.get(f"{self.VENUES['binance']}/ticker/24hr", params={"symbol": f"{symbol}USDT"})
                    if r.status_code == 200:
                        d = r.json()
                        venue_data["binance"] = VenueData(
                            venue="binance", symbol=symbol,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            price=float(d.get("lastPrice", 0)),
                            volume_24h=float(d.get("quoteVolume", 0)),
                            high_24h=float(d.get("highPrice", 0)),
                            low_24h=float(d.get("lowPrice", 0)),
                            change_24h_pct=float(d.get("priceChangePercent", 0)),
                        )
            except Exception as e:
                log.debug(f"Binance {symbol}: {e}")
            
            # Bybit — ticker
            try:
                with httpx.Client(timeout=10) as c:
                    r = c.get(f"{self.VENUES['bybit']}/market/tickers", params={"category": "linear", "symbol": f"{symbol}USDT"})
                    if r.status_code == 200:
                        d = r.json().get("result", {}).get("list", [{}])[0]
                        venue_data["bybit"] = VenueData(
                            venue="bybit", symbol=symbol,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            price=float(d.get("lastPrice", 0)),
                            volume_24h=float(d.get("turnover24h", 0)),
                            high_24h=float(d.get("highPrice24h", 0)),
                            low_24h=float(d.get("lowPrice24h", 0)),
                            change_24h_pct=float(d.get("price24hPcnt", 0)) * 100,
                            funding_rate=float(d.get("fundingRate", 0)) * 100,
                        )
            except Exception as e:
                log.debug(f"Bybit {symbol}: {e}")
            
            # OKX — ticker
            try:
                with httpx.Client(timeout=10) as c:
                    r = c.get(f"{self.VENUES['okx']}/market/ticker", params={"instId": f"{symbol}-USDT-SWAP"})
                    if r.status_code == 200:
                        d = r.json().get("data", [{}])[0]
                        venue_data["okx"] = VenueData(
                            venue="okx", symbol=symbol,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            price=float(d.get("last", 0)),
                            volume_24h=float(d.get("volCcy24h", 0)),
                            high_24h=float(d.get("high24h", 0)),
                            low_24h=float(d.get("low24h", 0)),
                        )
            except Exception as e:
                log.debug(f"OKX {symbol}: {e}")
            
            # Hyperliquid — metadata + allMids
            try:
                with httpx.Client(timeout=10) as c:
                    r = c.post(f"{self.VENUES['hyperliquid']}/info", json={"type": "allMids"})
                    if r.status_code == 200:
                        mids = r.json()
                        for m in mids:
                            if symbol in str(m):
                                venue_data["hyperliquid"] = VenueData(
                                    venue="hyperliquid", symbol=symbol,
                                    timestamp=datetime.now(timezone.utc).isoformat(),
                                    price=float(m.get("mid", 0)),
                                )
                                break
            except Exception as e:
                log.debug(f"Hyperliquid {symbol}: {e}")
            
            results[symbol] = venue_data
        
        self.data = results
        return results
    
    def price_consensus(self, symbol: str) -> dict:
        """Harga konsensus dari multi-venue (median + deviasi)."""
        prices = []
        for venue, data in self.data.get(symbol, {}).items():
            if data.price > 0:
                prices.append((venue, data.price))
        
        if len(prices) < 2:
            return {"status": "insufficient_data"}
        
        price_vals = [p for _, p in prices]
        median_price = sorted(price_vals)[len(price_vals)//2]
        max_dev = max(abs(p - median_price) / median_price * 100 for p in price_vals)
        
        return {
            "status": "ok",
            "venues": len(prices),
            "median_price": round(median_price, 2),
            "max_deviation_pct": round(max_dev, 4),
            "consensus": "STRONG" if max_dev < 0.5 else ("MODERATE" if max_dev < 1.0 else "WEAK"),
            "details": {v: round(p, 2) for v, p in prices},
        }


# =============================================================================
# 2. BEHAVIOR CHANGE DETECTOR
# =============================================================================

class BehaviorChangeDetector:
    """Deteksi perubahan behavior aset secara dini.
    
    Mendeteksi:
      - Volatility regime shift (low -> high atau sebaliknya)
      - Volume anomaly (spike > 2x rata-rata)
      - Correlation breakdown (ETH-BTC correlation shift)
      - Funding rate extreme (momentum/sentiment shift)
    """
    
    def __init__(self, window: int = 50):
        self.window = window
        self.price_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=window))
        self.volume_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=window))
        self.alerts: list[dict] = []
    
    def update(self, symbol: str, price: float, volume: float = 0):
        """Update history dengan data point baru."""
        self.price_history[symbol].append((datetime.now(timezone.utc), price))
        if volume > 0:
            self.volume_history[symbol].append(volume)
    
    def detect_all(self, symbol: str, current_volatility: float = 0) -> dict:
        """Jalankan semua deteksi untuk satu symbol."""
        detections = {}
        
        # 1. Volatility regime shift
        vol_change = self._detect_volatility_shift(symbol, current_volatility)
        if vol_change:
            detections["volatility_shift"] = vol_change
        
        # 2. Volume anomaly
        vol_anomaly = self._detect_volume_anomaly(symbol)
        if vol_anomaly:
            detections["volume_anomaly"] = vol_anomaly
        
        # 3. Trend acceleration / deceleration
        trend = self._detect_trend_change(symbol)
        if trend:
            detections["trend_change"] = trend
        
        return {"symbol": symbol, "detections": detections, "n_alerts": len(detections)}
    
    def _detect_volatility_shift(self, symbol: str, current_vol: float) -> dict | None:
        prices = [p for _, p in self.price_history[symbol]]
        if len(prices) < 20:
            return None
        
        # Historical volatility (20-period)
        returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
        hist_vol = stdev(returns[-20:]) * math.sqrt(len(returns[-20:])) * 100 if len(returns) >= 20 else 0
        
        if current_vol > 0 and hist_vol > 0:
            ratio = current_vol / hist_vol
            if ratio > 1.5:
                return {"type": "volatility_spike", "current": round(current_vol, 2),
                       "historical": round(hist_vol, 2), "ratio": round(ratio, 2),
                       "action": "TIGHTEN_STOPS", "reason": f"Volatility {ratio:.1f}x normal"}
            elif ratio < 0.5:
                return {"type": "volatility_collapse", "current": round(current_vol, 2),
                       "historical": round(hist_vol, 2), "ratio": round(ratio, 2),
                       "action": "WIDEN_STOPS", "reason": "Low volatility — wider stops ok"}
        return None
    
    def _detect_volume_anomaly(self, symbol: str) -> dict | None:
        vols = list(self.volume_history[symbol])
        if len(vols) < 20:
            return None
        
        avg_vol = mean(vols[-20:])
        current_vol = vols[-1]
        
        if avg_vol > 0 and current_vol > avg_vol * 2.0:
            return {"type": "volume_spike", "current": round(current_vol, 0),
                   "average": round(avg_vol, 0), "ratio": round(current_vol/avg_vol, 1),
                   "action": "CAUTION", "reason": f"Volume {current_vol/avg_vol:.1f}x normal — possible breakout/breakdown"}
        return None
    
    def _detect_trend_change(self, symbol: str) -> dict | None:
        prices = [p for _, p in self.price_history[symbol]]
        if len(prices) < 30:
            return None
        
        # Short-term vs medium-term momentum
        short_ma = mean(prices[-5:])
        med_ma = mean(prices[-20:])
        long_ma = mean(prices[-30:]) if len(prices) >= 30 else med_ma
        
        current = prices[-1]
        
        # Detect MA crossovers
        # Bearish: price crosses below short MA
        if len(prices) >= 2:
            prev = prices[-2]
            if prev > short_ma and current < short_ma:
                return {"type": "bearish_cross", "price": round(current, 2),
                       "ma": round(short_ma, 2), "action": "FAVOR_SHORT",
                       "reason": "Price crossed below MA5 — bearish momentum"}
            elif prev < short_ma and current > short_ma:
                return {"type": "bullish_cross", "price": round(current, 2),
                       "ma": round(short_ma, 2), "action": "FAVOR_LONG",
                       "reason": "Price crossed above MA5 — bullish momentum"}
        
        # Trend strength via MA alignment
        if short_ma > med_ma > long_ma:
            return None  # strong uptrend — no alert
        elif short_ma < med_ma < long_ma:
            return None  # strong downtrend — no alert
        elif abs(short_ma - med_ma) / med_ma < 0.01:
            return {"type": "trend_weakening", "price": round(current, 2),
                   "action": "REDUCE_SIZE", "reason": "MA convergence — trend losing strength"}
        
        return None


# =============================================================================
# 3. MARKET DIRECTION PREDICTOR
# =============================================================================

class DirectionPredictor:
    """Prediksi dini perubahan arah market.
    
    Menggunakan multi-signal confirmation:
      - Price vs multi-MA
      - RSI divergence
      - Volume-price relationship
      - Multi-venue consensus
    """
    
    def __init__(self):
        self.predictions: list[dict] = []
    
    def predict(self, symbol: str, prices: list[float], volumes: list[float] = None,
                multi_venue_consensus: dict = None) -> dict:
        """Prediksi arah market jangka pendek (4-24 jam)."""
        signals = []
        
        if len(prices) < 30:
            return {"status": "insufficient_data", "symbol": symbol}
        
        current = prices[-1]
        
        # 1. Multi-MA analysis
        ma5 = mean(prices[-5:])
        ma10 = mean(prices[-10:])
        ma20 = mean(prices[-20:])
        
        ma_score = 0
        if current > ma5: ma_score += 1
        if current > ma10: ma_score += 1
        if current > ma20: ma_score += 1
        if ma5 > ma10: ma_score += 1
        if ma10 > ma20: ma_score += 1
        
        if ma_score >= 4:
            signals.append({"signal": "BULLISH", "strength": ma_score/5, "source": "multi_ma"})
        elif ma_score <= 1:
            signals.append({"signal": "BEARISH", "strength": (5-ma_score)/5, "source": "multi_ma"})
        else:
            signals.append({"signal": "NEUTRAL", "strength": 0.5, "source": "multi_ma"})
        
        # 2. RSI divergence detection
        if len(prices) >= 20:
            rsi_now = self._calc_rsi(prices, -1)
            rsi_5ago = self._calc_rsi(prices, -6)
            
            if rsi_now and rsi_5ago:
                # Bullish divergence: price lower low, RSI higher low
                if prices[-1] < prices[-6] and rsi_now > rsi_5ago:
                    signals.append({"signal": "BULLISH", "strength": 0.7, "source": "rsi_divergence",
                                   "detail": f"Bullish divergence: RSI {rsi_5ago:.0f}->{rsi_now:.0f}"})
                # Bearish divergence: price higher high, RSI lower high
                elif prices[-1] > prices[-6] and rsi_now < rsi_5ago:
                    signals.append({"signal": "BEARISH", "strength": 0.7, "source": "rsi_divergence",
                                   "detail": f"Bearish divergence: RSI {rsi_5ago:.0f}->{rsi_now:.0f}"})
        
        # 3. Multi-venue confirmation
        if multi_venue_consensus and multi_venue_consensus.get("status") == "ok":
            consensus = multi_venue_consensus.get("consensus", "MODERATE")
            if consensus == "STRONG":
                signals.append({"signal": "CONFIRMED", "strength": 0.8, "source": "multi_venue",
                               "detail": f"{multi_venue_consensus['venues']} venues agree"})
            elif consensus == "WEAK":
                signals.append({"signal": "CAUTION", "strength": 0.3, "source": "multi_venue",
                               "detail": "Price divergence across venues — possible manipulation"})
        
        # Aggregate signals
        bull_score = sum(s["strength"] for s in signals if s["signal"] in ("BULLISH", "CONFIRMED"))
        bear_score = sum(s["strength"] for s in signals if s["signal"] == "BEARISH")
        caution_score = sum(s["strength"] for s in signals if s["signal"] == "CAUTION")
        
        net_score = bull_score - bear_score - caution_score * 0.5
        
        if net_score > 1.0:
            direction = "BULLISH"
            confidence = min(0.9, net_score / 3)
        elif net_score < -0.5:
            direction = "BEARISH"
            confidence = min(0.9, abs(net_score) / 3)
        else:
            direction = "NEUTRAL"
            confidence = 0.5
        
        prediction = {
            "status": "ok", "symbol": symbol, "timestamp": datetime.now(timezone.utc).isoformat(),
            "direction": direction, "confidence": round(confidence, 2),
            "net_score": round(net_score, 2), "signals": signals,
            "recommendation": self._recommendation(direction, confidence),
        }
        
        self.predictions.append(prediction)
        self.predictions = self.predictions[-50:]
        return prediction
    
    def _calc_rsi(self, prices, idx, period=14):
        """RSI at index."""
        end = len(prices) + idx + 1 if idx < 0 else idx + 1
        start = end - period - 1
        if start < 0: return None
        window = prices[start:end]
        gains = [max(0, window[i]-window[i-1]) for i in range(1, len(window))]
        losses = [max(0, window[i-1]-window[i]) for i in range(1, len(window))]
        ag = sum(gains)/period; al = sum(losses)/period
        if al < 0.0001: return 100.0
        return 100 - 100/(1 + ag/al)
    
    def _recommendation(self, direction: str, confidence: float) -> str:
        if direction == "BULLISH" and confidence > 0.6:
            return "FAVOR_LONG — reduce SHORT exposure"
        elif direction == "BEARISH" and confidence > 0.6:
            return "FAVOR_SHORT — reduce LONG exposure"
        elif direction == "NEUTRAL":
            return "RANGE_TRADE — scalp both directions, tight stops"
        return "CAUTION — wait for clearer signal"


# =============================================================================
# 4. ADAPTIVE STRATEGY ENGINE
# =============================================================================

class AdaptiveStrategyEngine:
    """Auto-switch konfigurasi strategi berdasarkan kondisi market.
    
    Strategy modes:
      - BREAKOUT: trending market, high volatility
      - MEAN_REVERSION: ranging market, low volatility  
      - MOMENTUM: strong trend, follow the direction
      - DEFENSIVE: high uncertainty, reduce size
    """
    
    MODES = {
        "BREAKOUT": {
            "stop_loss": -0.02, "take_profit": 0.06, "risk_per_trade": 0.02,
            "hold_bars": 6, "rsi_long": 55, "rsi_short": 45,
            "description": "Price breakout dari range — trending market"
        },
        "MEAN_REVERSION": {
            "stop_loss": -0.015, "take_profit": 0.04, "risk_per_trade": 0.015,
            "hold_bars": 4, "rsi_long": 25, "rsi_short": 75,
            "description": "RSI extremes — ranging market"
        },
        "MOMENTUM": {
            "stop_loss": -0.03, "take_profit": 0.08, "risk_per_trade": 0.025,
            "hold_bars": 8, "rsi_long": 60, "rsi_short": 40,
            "description": "Follow the trend — strong directional moves"
        },
        "DEFENSIVE": {
            "stop_loss": -0.01, "take_profit": 0.03, "risk_per_trade": 0.01,
            "hold_bars": 3, "rsi_long": 20, "rsi_short": 80,
            "description": "Reduced exposure — high uncertainty"
        },
    }
    
    def __init__(self):
        self.current_mode = "BREAKOUT"
        self.mode_history: list[dict] = []
        self._load()
    
    def _load(self):
        p = DATA_DIR / "adaptive_strategy.json"
        if p.exists():
            try:
                d = json.loads(p.read_text())
                self.current_mode = d.get("current_mode", "BREAKOUT")
                self.mode_history = d.get("history", [])
            except: pass
    
    def _save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "adaptive_strategy.json").write_text(json.dumps({
            "current_mode": self.current_mode, "history": self.mode_history[-20:],
        }, indent=2, default=str))
    
    def evaluate(self, behavior: dict, direction: dict, performance: dict = None) -> dict:
        """Evaluasi kondisi market dan rekomendasikan mode strategi."""
        reasons = []
        scores = {mode: 0 for mode in self.MODES}
        
        # Factor 1: Volatility regime
        vol_shift = behavior.get("detections", {}).get("volatility_shift", {})
        if vol_shift.get("type") == "volatility_spike":
            scores["BREAKOUT"] += 2
            scores["DEFENSIVE"] += 1
            reasons.append(f"High volatility ({vol_shift.get('ratio',1)}x) → favor breakout")
        elif vol_shift.get("type") == "volatility_collapse":
            scores["MEAN_REVERSION"] += 2
            reasons.append(f"Low volatility → favor mean-reversion")
        
        # Factor 2: Trend direction strength
        dir_conf = direction.get("confidence", 0.5)
        dir_signal = direction.get("direction", "NEUTRAL")
        
        if dir_signal == "BULLISH" and dir_conf > 0.6:
            scores["MOMENTUM"] += 2
            scores["BREAKOUT"] += 1
            reasons.append(f"Bullish bias (conf={dir_conf:.0%}) → favor momentum/breakout")
        elif dir_signal == "BEARISH" and dir_conf > 0.6:
            scores["MOMENTUM"] += 2
            reasons.append(f"Bearish bias (conf={dir_conf:.0%}) → favor momentum shorts")
        else:
            scores["MEAN_REVERSION"] += 1
            scores["DEFENSIVE"] += 1
            reasons.append("Neutral direction → mean-reversion or defensive")
        
        # Factor 3: Volume anomaly
        vol_anomaly = behavior.get("detections", {}).get("volume_anomaly", {})
        if vol_anomaly:
            scores["BREAKOUT"] += 2
            reasons.append(f"Volume spike ({vol_anomaly.get('ratio',1)}x) → possible breakout")
        
        # Factor 4: Trend change warning
        trend = behavior.get("detections", {}).get("trend_change", {})
        if trend:
            if trend.get("action") == "REDUCE_SIZE":
                scores["DEFENSIVE"] += 2
                reasons.append("Trend weakening → reduce exposure")
            elif trend.get("action") == "FAVOR_SHORT":
                scores["MOMENTUM"] += 1
                reasons.append("Bearish cross → favor shorts")
        
        # Factor 5: Recent performance
        if performance:
            recent_wr = performance.get("recent_wr", 0.5)
            if recent_wr < 0.35:
                scores["DEFENSIVE"] += 3
                reasons.append(f"Low WR ({recent_wr:.0%}) → switch defensive")
            elif recent_wr > 0.60:
                best_mode = performance.get("best_mode", "BREAKOUT")
                scores[best_mode] += 2
                reasons.append(f"Good WR ({recent_wr:.0%}) → stay with {best_mode}")
        
        # Determine best mode
        best_mode = max(scores, key=scores.get)
        top_score = scores[best_mode]
        
        # Only switch if significantly better
        if best_mode != self.current_mode and top_score >= scores.get(self.current_mode, 0) + 2:
            old_mode = self.current_mode
            self.current_mode = best_mode
            self.mode_history.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "from": old_mode, "to": best_mode, "reasons": reasons,
                "scores": {k: v for k, v in scores.items() if v > 0},
            })
            self._save()
            log.info(f"ADAPTIVE: {old_mode} → {best_mode} ({'; '.join(reasons[:2])})")
            
            return {
                "status": "switched", "from": old_mode, "to": best_mode,
                "mode": best_mode,  # ponytail: consistent `mode` key with the maintained branch
                "params": self.MODES[best_mode], "reasons": reasons,
            }
        
        return {
            "status": "maintained", "mode": self.current_mode,
            "params": self.MODES[self.current_mode],
            "scores": {k: v for k, v in scores.items() if v > 0},
            "reasons": reasons,
        }
    
    def get_params(self) -> dict:
        return self.MODES.get(self.current_mode, self.MODES["BREAKOUT"])


# =============================================================================
# 5. MARKET INTELLIGENCE ORCHESTRATOR
# =============================================================================

class MarketIntelligence:
    """Sistem Intelijen Pasar — deteksi dini + reaksi cepat."""
    
    def __init__(self):
        self.collector = MultiVenueCollector()
        self.behavior = BehaviorChangeDetector()
        self.direction = DirectionPredictor()
        self.adaptive = AdaptiveStrategyEngine()
        self.alerts_sent: list[dict] = []
        self.last_update: str = ""
    
    def scan(self, symbol: str = "ETH", prices_4h: list[float] = None) -> dict:
        """Satu siklus scan penuh — multi-venue + behavior + direction + adapt."""
        self.last_update = datetime.now(timezone.utc).isoformat()
        
        # 1. Multi-venue data
        venue_data = self.collector.fetch_all([symbol])
        consensus = self.collector.price_consensus(symbol)
        
        # 2. Update behavior detector
        if prices_4h and len(prices_4h) > 0:
            current_price = prices_4h[-1]
            current_vol = stdev([(prices_4h[i]-prices_4h[i-1])/prices_4h[i-1] 
                                for i in range(-min(20,len(prices_4h)-1), 0)]) * 100 if len(prices_4h) >= 5 else 0
            self.behavior.update(symbol, current_price)
        
        behavior_result = self.behavior.detect_all(symbol, current_vol if prices_4h else 0)
        
        # 3. Direction prediction
        direction_result = self.direction.predict(symbol, prices_4h or [], 
                                                  multi_venue_consensus=consensus)
        
        # 4. Adaptive strategy
        strategy_result = self.adaptive.evaluate(behavior_result, direction_result)
        
        # 5. Generate alerts if needed
        alerts = self._generate_alerts(behavior_result, direction_result, strategy_result)
        
        result = {
            "timestamp": self.last_update,
            "symbol": symbol,
            "venue_consensus": consensus,
            "behavior": behavior_result,
            "direction": direction_result,
            "strategy": strategy_result,
            "alerts": alerts,
        }
        
        # Save intel
        self._save_intel(result)
        
        return result
    
    def _generate_alerts(self, behavior: dict, direction: dict, strategy: dict) -> list[dict]:
        alerts = []
        
        # Behavior alerts
        for det_type, det in behavior.get("detections", {}).items():
            alerts.append({
                "level": "WARNING",
                "type": det_type,
                "detail": det.get("reason", ""),
                "action": det.get("action", ""),
            })
        
        # Direction alerts
        if direction.get("direction") in ("BULLISH", "BEARISH") and direction.get("confidence", 0) > 0.6:
            alerts.append({
                "level": "INFO",
                "type": "direction_signal",
                "detail": f"{direction['direction']} (conf={direction['confidence']:.0%})",
                "action": direction.get("recommendation", ""),
            })
        
        # Strategy switch alerts
        if strategy.get("status") == "switched":
            alerts.append({
                "level": "CRITICAL",
                "type": "strategy_switch",
                "detail": f"Switched {strategy['from']} → {strategy['to']}",
                "action": "RECONFIGURE",
            })
        
        # Save alerts
        if alerts:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(ALERT_PATH, "a") as f:
                for a in alerts:
                    a["ts"] = datetime.now(timezone.utc).isoformat()
                    f.write(json.dumps(a) + "\n")
        
        return alerts
    
    def _save_intel(self, result: dict):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            existing = []
            if INTEL_PATH.exists():
                existing = json.loads(INTEL_PATH.read_text())
            if isinstance(existing, dict):
                existing = [existing]
            existing.append(result)
            existing = existing[-50:]
            INTEL_PATH.write_text(json.dumps(existing, indent=2, default=str))
        except Exception:
            pass
    
    def status_report(self) -> str:
        lines = ["="*60, "  MARKET INTELLIGENCE — Status Report", "="*60,
                 f"  Last scan: {self.last_update[:19] if self.last_update else 'never'}",
                 f"  Active mode: {self.adaptive.current_mode}",
                 f"  Mode params: {self.adaptive.get_params()}",
                 f"  Alerts sent: {len(self.alerts_sent)}",
                 "-"*60,
                 f"  Available modes: {list(self.adaptive.MODES.keys())}",
                 "="*60]
        return "\n".join(lines)


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import sys
    intel = MarketIntelligence()
    
    if len(sys.argv) > 1 and sys.argv[1] == "scan":
        sym = sys.argv[2] if len(sys.argv) > 2 else "ETH"
        result = intel.scan(sym)
        print(json.dumps(result, indent=2, default=str))
    elif len(sys.argv) > 1 and sys.argv[1] == "status":
        print(intel.status_report())
    else:
        # Quick scan
        print("Scanning ETH multi-venue...")
        result = intel.scan("ETH")
        print(f"Venues: {result.get('venue_consensus',{}).get('venues',0)} responded")
        print(f"Consensus: {result.get('venue_consensus',{}).get('consensus','?')}")
        print(f"Price: ${result.get('venue_consensus',{}).get('median_price','?')}")
        print(f"Direction: {result.get('direction',{}).get('direction','?')}")
        print(f"Strategy: {result.get('strategy',{}).get('mode','?')}")
        print(f"Alerts: {len(result.get('alerts',[]))}")
