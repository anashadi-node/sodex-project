#!/usr/bin/env python3
"""
ANANTARA SAKTI — SoSoValue Macro Context Layer.

Adds a 3rd INDEPENDENT signal mechanism to the Pre-Gain/Loser scanner:
  • VOL_REGIME    : volume/flow (price-derived)
  • ATR_COMPRESS  : volatility structure (price-derived)
  • MACRO (this)  : ETF institutional flow + sector trend + macro events
                    ← fully INDEPENDENT from price/volume/volatility

Why this matters for TRUE confluence:
  The previous 'confluence' study (improve_v2) showed correlated indicators
  DIDN'T help. Real confluence needs independent mechanisms. ETF inflow/outflow
  reflects INSTITUTIONAL behaviour (billions in/out of BTC ETFs) — it has NO
  correlation with short-term price vol or ATR. That independence = genuine signal.

Three sub-signals (all from SoSoValue API, key in .env SOSOVALUE_API_KEY):
  1. ETF_FLOW   : net BTC+ETH ETF inflow last 3 days → macro bias BULLISH/BEARISH
  2. SECTOR_HOT : coin's crypto sector in top performers today → tailwind present
  3. MACRO_CALM : no major economic event (FOMC/CPI) within 24h → timing safe

Graceful degradation: if SOSOVALUE_API_KEY not set → all sub-signals return
NEUTRAL (zero score adjustment). Scanner keeps working without the API key;
adding the key just improves signal quality.

Pure functions are unit-tested. IO fetches are isolated at the bottom.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

SOSOVALUE_API  = "https://openapi.sosovalue.com/openapi/v1"
API_KEY_ENV    = "SOSOVALUE_API_KEY"
CACHE_TTL_SEC  = 300   # 5-minute cache (well within 20 req/min rate limit)

# Sector → HL coin mapping (curated from SoSoValue sector names)
# Used to check if a coin belongs to a hot sector
SECTOR_COINS: dict[str, list[str]] = {
    "DeFi":         ["AAVE","UNI","CRV","LDO","MKR","COMP","SUSHI","BAL","YFI"],
    "Layer 2":      ["OP","ARB","MATIC","IMX","METIS","BOBA","STRK","ZK"],
    "AI":           ["FET","AGIX","OCEAN","AKT","NMR","GRT","TAO","RENDER"],
    "Gaming/NFT":   ["AXS","SAND","MANA","GALA","IMX","MAGIC","BEAM","RON"],
    "Layer 1":      ["SOL","AVAX","NEAR","APT","SUI","SEI","INJ","TON"],
    "Infrastructure":["LINK","DOT","ATOM","HBAR","VET","EGLD","ALGO"],
    # HL uses 'k' prefix for 1000x meme coins; coin.upper() gives "KPEPE" etc.
    # Both the direct name AND the uppercase k-prefix variant must be present.
    "Meme":         ["DOGE","SHIB","PEPE","BONK","WIF","FLOKI","NEIRO",
                     "KPEPE","KBONK","KSHIB","KFLOKI"],  # HL k-prefix (uppercase)
    "RWA":          ["ONDO","CFG","TRU","MPL","COVAL","POLYX","RIO"],
    "BTC Ecosystem":["ORDI","SATS","RATS","MUBI","BTCS","WBTC","cbBTC"],
    "Privacy":      ["XMR","ZEC","DASH","SCRT","ROSE","NYM"],
}

# ETF tickers to track (BTC + ETH spot ETFs)
BTC_ETF_TICKERS = ["IBIT", "FBTC", "BITB", "ARKB", "BTCO", "HODL", "BRRR"]
ETH_ETF_TICKERS = ["ETHA", "FETH", "ETHW", "CETH", "ETHV"]

# CoinGecko category name → SECTOR_COINS key (fallback when SoSoValue sector unavailable)
CG_SECTOR_MAP: dict[str, str] = {
    "Decentralized Finance (DeFi)": "DeFi",
    "Layer 2 (L2)":                 "Layer 2",
    "Artificial Intelligence (AI)": "AI",
    "Gaming (GameFi)":              "Gaming/NFT",
    "NFT":                          "Gaming/NFT",
    "Layer 1 (L1)":                 "Layer 1",
    "Infrastructure":               "Infrastructure",
    "Meme":                         "Meme",
    "Real World Assets (RWA)":      "RWA",
    "Privacy Coins":                "Privacy",
    "Bitcoin Fork":                 "BTC Ecosystem",
}


@dataclass
class EtfSentiment:
    net_inflow_3d_bn: float   # net inflow last 3 days in $B (+ = inflow, - = outflow)
    bias: str                 # BULLISH | BEARISH | NEUTRAL
    strength: float           # 0.0–1.0 (magnitude-scaled)
    label: str                # human-readable

@dataclass
class SectorBias:
    hot_sectors: list[str]      # sectors with positive performance today
    cold_sectors: list[str]     # sectors with negative performance today
    coin_biases: dict[str, str] # {coin: HOT|COLD|NEUTRAL}

@dataclass
class MacroEvent:
    name: str
    date: str
    hours_until: float

@dataclass
class MacroContext:
    etf: EtfSentiment
    sector: SectorBias
    events: list[MacroEvent]
    # Score adjustment for a given signal direction (+/- points to add)
    long_adj: int
    short_adj: int
    reason: str
    from_cache: bool = False

@dataclass
class TopMover:
    symbol: str
    side: str                 # GAINER | LOSER
    change_pct: float
    rank: int
    range_pos_pct: float = 0.0
    name: str = ""
    raw: dict = field(default_factory=dict)

@dataclass
class TopMoverContext:
    gainers: list[TopMover]
    losers: list[TopMover]
    reason: str
    from_cache: bool = False

@dataclass
class MarketSnapshot:
    symbol: str
    currency_id: str
    price: float
    change_pct_24h: float
    turnover_24h: float
    high_24h: float
    low_24h: float
    marketcap_rank: int
    range_pos_pct: float = 0.0
    raw: dict = field(default_factory=dict)


# ── Pure logic (tested) ──────────────────────────────────────────────────────

def etf_sentiment_from_data(history: list[dict]) -> EtfSentiment:
    """Compute ETF sentiment from raw /etfs/summary-history records.

    Each record expected: {date, netInflow (float, USD millions)}.
    Last 3 records used for recency-weighted bias.
    """
    if not history:
        return EtfSentiment(0.0, "NEUTRAL", 0.0, "no ETF data")
    recent = sorted(history, key=lambda x: x.get("date",""), reverse=True)[:3]
    net_m  = sum(float(r.get("netInflow", 0) or 0) for r in recent)   # USD millions
    net_bn = net_m / 1000.0
    if abs(net_bn) < 0.1:
        return EtfSentiment(net_bn, "NEUTRAL", 0.0, f"ETF net ≈ neutral (${net_m:.0f}M/3d)")
    strength = min(1.0, abs(net_bn) / 2.0)   # saturates at $2B
    if net_bn > 0:
        return EtfSentiment(net_bn, "BULLISH", strength,
                            f"ETF +${net_m:.0f}M/3d → institutional inflow 🟢")
    return EtfSentiment(net_bn, "BEARISH", strength,
                        f"ETF -${abs(net_m):.0f}M/3d → institutional outflow 🔴")


def sector_bias_from_data(spotlight: list[dict]) -> SectorBias:
    """Build sector hot/cold lists from /currencies/sector-spotlight records.

    Each record expected: {sector (str), change24h (float %)}.
    """
    hot, cold = [], []
    for r in (spotlight or []):
        sector = r.get("sector") or r.get("name") or ""
        chg    = float(r.get("change24h") or r.get("priceChange24h") or 0)
        if chg > 2.0:
            hot.append(sector)
        elif chg < -2.0:
            cold.append(sector)

    coin_biases: dict[str, str] = {}
    for sector, coins in SECTOR_COINS.items():
        bias = ("HOT" if sector in hot else "COLD" if sector in cold else "NEUTRAL")
        for coin in coins:
            if coin not in coin_biases or bias == "HOT":
                coin_biases[coin] = bias
    return SectorBias(hot, cold, coin_biases)


def macro_events_from_data(events: list[dict], now_utc: Optional[datetime] = None) -> list[MacroEvent]:
    """Find major events within the next 48h."""
    now = now_utc or datetime.now(timezone.utc)
    HIGH_IMPACT = {"FOMC", "CPI", "PPI", "PCE", "NFP", "GDP", "INTEREST RATE",
                   "FED", "FEDERAL RESERVE", "INFLATION", "UNEMPLOYMENT"}
    result = []
    for ev in (events or []):
        name = str(ev.get("event") or ev.get("name") or "")
        date_str = str(ev.get("date") or ev.get("releaseDate") or "")
        if not name or not date_str:
            continue
        if not any(k in name.upper() for k in HIGH_IMPACT):
            continue
        try:
            ev_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if ev_dt.tzinfo is None:
                ev_dt = ev_dt.replace(tzinfo=timezone.utc)
            diff = (ev_dt - now).total_seconds() / 3600.0
            if 0 <= diff <= 48:
                result.append(MacroEvent(name, date_str, round(diff, 1)))
        except Exception:
            pass
    return sorted(result, key=lambda x: x.hours_until)


def compute_macro_context(etf: EtfSentiment, sector: SectorBias,
                          events: list[MacroEvent]) -> MacroContext:
    """Compute score adjustments for LONG/SHORT based on macro context (pure)."""
    long_adj = short_adj = 0
    reasons = []

    # ETF flow adjustment (strongest macro signal — institutional $B moves)
    if etf.bias == "BULLISH" and etf.strength > 0.2:
        pts = int(etf.strength * 20)
        long_adj  += pts; short_adj -= int(pts * 0.5)
        reasons.append(etf.label)
    elif etf.bias == "BEARISH" and etf.strength > 0.2:
        pts = int(etf.strength * 20)
        short_adj += pts; long_adj -= int(pts * 0.5)
        reasons.append(etf.label)

    # Macro event caution (reduce both if major event within 24h)
    near_events = [e for e in events if e.hours_until <= 24]
    if near_events:
        ev_names = ", ".join(e.name for e in near_events[:2])
        long_adj  = int(long_adj  * 0.6)   # dampen by 40%
        short_adj = int(short_adj * 0.6)
        reasons.append(f"⚠️ macro event <24h: {ev_names}")

    reason = " | ".join(reasons) if reasons else "macro neutral"
    return MacroContext(etf, sector, events, long_adj, short_adj, reason)


def coin_sector_adj(coin: str, sector: SectorBias, direction: str) -> int:
    """Per-coin sector adjustment: +8 if sector tailwind, -8 if headwind."""
    bias = sector.coin_biases.get(coin.upper(), "NEUTRAL")
    if bias == "HOT"  and direction == "LONG":  return  8
    if bias == "COLD" and direction == "SHORT": return  8
    if bias == "HOT"  and direction == "SHORT": return -8
    if bias == "COLD" and direction == "LONG":  return -8
    return 0


def _extract_top_mover_rows(payload, keys: tuple[str, ...]) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return []
    for key in keys:
        rows = data.get(key)
        if isinstance(rows, list):
            return [x for x in rows if isinstance(x, dict)]
    return []


def _flat_top_mover_rows(payload) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [x for x in payload["data"] if isinstance(x, dict)]
    return []


def _top_mover_symbol(row: dict) -> str:
    raw = str(
        row.get("symbol")
        or row.get("ticker")
        or row.get("base")
        or row.get("currency")
        or row.get("coin")
        or row.get("token")
        or row.get("name")
        or ""
    ).strip()
    if not raw:
        return ""
    raw = raw.split("/")[0].split("-")[0].split("_")[0]
    raw = re.sub(r"^[#$]+", "", raw)
    raw = re.sub(r"[^A-Za-z0-9]", "", raw)
    raw = raw.upper()
    if raw.startswith("1000") and len(raw) > 4:
        raw = raw[4:]
    if raw.startswith("K") and len(raw) > 2:
        raw = raw[1:]
    return raw


def _top_mover_change(row: dict) -> float:
    for key in (
        "change24h", "priceChange24h", "change_pct_24h", "priceChangePercent",
        "changePercent", "change_pct", "change",
    ):
        if key not in row or row.get(key) in (None, ""):
            continue
        try:
            val = float(str(row.get(key)).strip().rstrip("%"))
        except (TypeError, ValueError):
            continue
        return val * 100 if abs(val) <= 1.0 and key not in {"change"} else val
    return 0.0


def _top_mover_from_row(row: dict, side: str, rank: int) -> TopMover | None:
    symbol = _top_mover_symbol(row)
    if not symbol:
        return None
    change = _top_mover_change(row)
    return TopMover(
        symbol=symbol,
        side=side,
        change_pct=change,
        rank=rank,
        range_pos_pct=_range_position_pct(
            _row_float(row, "price", "currentPrice", "last", "close"),
            _row_float(row, "high_24h", "high24h", "high"),
            _row_float(row, "low_24h", "low24h", "low"),
        ),
        name=str(row.get("name") or row.get("fullName") or symbol),
        raw=row,
    )


def _row_float(row: dict, *keys: str) -> float:
    for key in keys:
        try:
            val = float(row.get(key) or 0.0)
        except (TypeError, ValueError):
            continue
        if val:
            return val
    return 0.0


def _range_position_pct(price: float, high: float, low: float) -> float:
    if price <= 0 or high <= low:
        return 0.0
    return max(0.0, min(100.0, (price - low) / (high - low) * 100.0))


def top_movers_from_data(payload) -> TopMoverContext:
    """Normalize SoSoValue top gainer/loser payload variants into coin symbols."""
    flat_rows = _flat_top_mover_rows(payload)
    if flat_rows:
        inferred_gainers: list[dict] = []
        inferred_losers: list[dict] = []
        for row in flat_rows:
            change = _top_mover_change(row)
            if change > 0:
                inferred_gainers.append(row)
            elif change < 0:
                inferred_losers.append(row)
        gainers = [
            mover for idx, row in enumerate(inferred_gainers, start=1)
            if (mover := _top_mover_from_row(row, "GAINER", idx))
        ]
        losers = [
            mover for idx, row in enumerate(inferred_losers, start=1)
            if (mover := _top_mover_from_row(row, "LOSER", idx))
        ]
    else:
        gainer_keys = ("topGainers", "top_gainers", "gainers", "gain", "up")
        loser_keys = ("topLosers", "top_losers", "losers", "lose", "down")
        gainers = [
            mover for idx, row in enumerate(_extract_top_mover_rows(payload, gainer_keys), start=1)
            if (mover := _top_mover_from_row(row, "GAINER", idx))
        ]
        losers = [
            mover for idx, row in enumerate(_extract_top_mover_rows(payload, loser_keys), start=1)
            if (mover := _top_mover_from_row(row, "LOSER", idx))
        ]

    reason = f"sosovalue top movers: {len(gainers)} gainers, {len(losers)} losers"
    return TopMoverContext(gainers[:50], losers[:50], reason)


def market_snapshot_from_data(symbol: str, currency_id: str, payload) -> MarketSnapshot | None:
    """Normalize /currencies/{currency_id}/market-snapshot response."""
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(data, dict):
        return None
    try:
        price = float(data.get("price") or 0.0)
    except (TypeError, ValueError):
        price = 0.0
    if price <= 0:
        return None
    try:
        rank = int(float(data.get("marketcap_rank") or 0))
    except (TypeError, ValueError):
        rank = 0
    def f(key: str) -> float:
        try:
            return float(data.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    change_pct = f("change_pct_24h")
    if abs(change_pct) <= 1.0:
        change_pct *= 100
    high_24h = f("high_24h")
    low_24h = f("low_24h")
    range_pos_pct = _range_position_pct(price, high_24h, low_24h)
    return MarketSnapshot(
        symbol=symbol.upper(),
        currency_id=str(currency_id),
        price=price,
        change_pct_24h=change_pct,
        turnover_24h=f("turnover_24h"),
        high_24h=high_24h,
        low_24h=low_24h,
        marketcap_rank=rank,
        range_pos_pct=range_pos_pct,
        raw=data,
    )


def top_movers_from_market_snapshots(snapshots: list[MarketSnapshot]) -> TopMoverContext:
    gainers = [
        TopMover(s.symbol, "GAINER", s.change_pct_24h, idx + 1, s.range_pos_pct, raw=s.raw)
        for idx, s in enumerate(sorted(
            [x for x in snapshots if x.change_pct_24h > 0],
            key=lambda x: x.change_pct_24h,
            reverse=True,
        ))
    ]
    losers = [
        TopMover(s.symbol, "LOSER", s.change_pct_24h, idx + 1, s.range_pos_pct, raw=s.raw)
        for idx, s in enumerate(sorted(
            [x for x in snapshots if x.change_pct_24h < 0],
            key=lambda x: x.change_pct_24h,
        ))
    ]
    return TopMoverContext(
        gainers[:50],
        losers[:50],
        f"sosovalue market snapshots: {len(gainers)} gainers, {len(losers)} losers",
    )


# ── IO boundary (not unit-tested, graceful degradation) ─────────────────────

_CACHE: dict[str, tuple[float, object]] = {}

def _cached(key: str, fn, *args):
    """Simple time-based cache (5 min TTL)."""
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < CACHE_TTL_SEC:
        return _CACHE[key][1]
    result = fn(*args)
    _CACHE[key] = (now, result)
    return result


_API_KEY_CACHE: tuple[float, str] = (0.0, "")   # (timestamp, key)
_API_KEY_TTL = 60.0   # re-read .env at most once per minute

def _api_key() -> str:
    """Return SoSoValue API key (cached 60s — avoids repeated .env reads per scan)."""
    global _API_KEY_CACHE
    now = time.time()
    if now - _API_KEY_CACHE[0] < _API_KEY_TTL:
        return _API_KEY_CACHE[1]
    # Read from .env file first, then fall back to os.environ
    key = os.environ.get(API_KEY_ENV, "")
    env_path = Path(os.environ.get("ANANTARA_DIR",
                    str(Path.home() / "anantara-sakti"))) / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text().splitlines():
                if line.startswith(API_KEY_ENV + "="):
                    key = line.split("=", 1)[1].strip()
                    break
        except Exception:
            pass
    _API_KEY_CACHE = (now, key)
    return key


def _get(path: str, params: dict | None = None) -> list | dict:
    import httpx
    key = _api_key()
    if not key:
        return []
    try:
        r = httpx.get(f"{SOSOVALUE_API}{path}",
                      headers={"x-soso-api-key": key}, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data.get("data", data) if isinstance(data, dict) else data
        return []
    except Exception:
        # Network error, JSON parse error, etc. — degrade gracefully to empty.
        return []


def _post(path: str, body: dict | None = None) -> list | dict:
    import httpx
    key = _api_key()
    if not key:
        return []
    try:
        r = httpx.post(f"{SOSOVALUE_API}{path}",
                       headers={"x-soso-api-key": key, "Content-Type": "application/json"},
                       json=body or {}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data.get("data", data) if isinstance(data, dict) else data
        return []
    except Exception:
        return []


def fetch_currency_map() -> dict[str, str]:
    """Map SoSoValue currency symbols to currency IDs."""
    def _fetch():
        raw = _post("/data/default/coin/list", {})
        result: dict[str, str] = {}
        rows = raw if isinstance(raw, list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("currencyName") or row.get("name") or "").upper()
            currency_id = str(row.get("currencyId") or row.get("id") or "")
            if symbol and currency_id:
                result[symbol] = currency_id
        return result
    return _cached("currency_map", _fetch)


def fetch_market_snapshot(symbol: str, currency_id: str | None = None) -> MarketSnapshot | None:
    sym = symbol.upper()
    cid = currency_id or fetch_currency_map().get(sym, "")
    if not cid:
        return None
    def _fetch():
        return market_snapshot_from_data(sym, cid, _get(f"/currencies/{cid}/market-snapshot"))
    return _cached(f"market_snapshot:{sym}:{cid}", _fetch)


def fetch_market_snapshots(symbols: list[str], max_assets: int = 5) -> list[MarketSnapshot]:
    result: list[MarketSnapshot] = []
    seen: set[str] = set()
    currency_map = fetch_currency_map()
    requested = 0
    for raw_symbol in symbols:
        symbol = raw_symbol.upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        currency_id = currency_map.get(symbol, "")
        if not currency_id:
            continue
        snap = fetch_market_snapshot(symbol, currency_id)
        requested += 1
        if snap:
            result.append(snap)
        if requested >= max_assets:
            break
    return result


def fetch_etf_history() -> list[dict]:
    """BTC ETF daily flow — normalized to {date, netInflow(USD millions)} for pure fn."""
    def _fetch():
        raw = _get("/etfs/summary-history",
                   params={"symbol": "BTC", "country_code": "US", "limit": 10})
        return [{"date": r.get("date", ""),
                 "netInflow": float(r.get("total_net_inflow") or 0) / 1_000_000}
                for r in (raw if isinstance(raw, list) else [])]
    return _cached("etf_hist", _fetch)


def _fetch_sector_coingecko() -> list[dict]:
    """CoinGecko /coins/categories as fallback sector data (free tier, no key needed).
    Maps CoinGecko category names → SECTOR_COINS keys via CG_SECTOR_MAP."""
    import httpx
    try:
        r = httpx.get("https://api.coingecko.com/api/v3/coins/categories",
                      headers={"Accept": "application/json"}, timeout=12)
        if r.status_code != 200:
            return []
        seen: set[str] = set()
        result = []
        for d in r.json():
            mapped = CG_SECTOR_MAP.get(d.get("name", ""))
            if mapped and mapped not in seen:
                chg = float(d.get("market_cap_change_24h") or 0)
                result.append({"sector": mapped, "change24h": round(chg, 3)})
                seen.add(mapped)
        return result
    except Exception:
        return []


def fetch_sector_data() -> list[dict]:
    """Crypto sector 24h change — SoSoValue first, CoinGecko fallback.
    Normalized to {sector, change24h(%)} for pure fn."""
    def _fetch():
        # Try SoSoValue (may return empty list if tier restriction or no data)
        raw = _get("/crypto-stocks/sector")
        # Use explicit len check: `if raw` would treat [] as falsy and fallback
        # when SoSoValue legitimately returned an empty sector list (rare but valid).
        if isinstance(raw, list) and len(raw) > 0:
            return [{"sector": r.get("sector_name", ""),
                     "change24h": float(r.get("change_pct_24h") or 0) * 100}
                    for r in raw]
        # Fallback: CoinGecko categories (free, reliable)
        return _fetch_sector_coingecko()
    return _cached("sector", _fetch)


def fetch_macro_events() -> list[dict]:
    """Macro economic events — normalized to [{event, date}] for pure fn.
    API returns [{date, events:[name,...]}]; expanded to one record per event."""
    def _fetch():
        raw = _get("/macro/events")
        result = []
        for r in (raw if isinstance(raw, list) else []):
            for ev_name in (r.get("events") or []):
                result.append({"event": ev_name, "date": r.get("date", "")})
        return result
    return _cached("macro_ev", _fetch)


def fetch_macro_context() -> MacroContext:
    """Full macro context (cached 5 min). Returns NEUTRAL on any error/no key."""
    key = _api_key()
    if not key:
        neutral_etf    = EtfSentiment(0.0, "NEUTRAL", 0.0, "SOSOVALUE_API_KEY not set")
        neutral_sector = SectorBias([], [], {})
        return MacroContext(neutral_etf, neutral_sector, [], 0, 0,
                            "macro: key missing → neutral (set SOSOVALUE_API_KEY in .env)")
    try:
        def _full():
            etf     = etf_sentiment_from_data(fetch_etf_history())
            sector  = sector_bias_from_data(fetch_sector_data())
            events  = macro_events_from_data(fetch_macro_events())
            return compute_macro_context(etf, sector, events)
        ctx = _cached("full_ctx", _full)
        ctx.from_cache = True
        return ctx
    except Exception as e:
        neutral_etf    = EtfSentiment(0.0, "NEUTRAL", 0.0, f"fetch error: {e}")
        neutral_sector = SectorBias([], [], {})
        return MacroContext(neutral_etf, neutral_sector, [], 0, 0, f"macro error: {e}")


def fetch_top_mover_context(symbols: list[str] | None = None, max_assets: int = 5) -> TopMoverContext:
    """Fetch SoSoValue Top Gainer/Top Loser context; empty context on any issue."""
    if not _api_key():
        return TopMoverContext([], [], "top movers: key missing")

    def _fetch():
        if symbols:
            snapshots = fetch_market_snapshots(symbols, max_assets=max_assets)
            if snapshots:
                return top_movers_from_market_snapshots(snapshots)
            return TopMoverContext([], [], "top movers: no market snapshots for requested symbols")
        paths = os.environ.get(
            "SOSOVALUE_TOP_MOVERS_PATHS",
            "/currencies/top-movers,/currencies/market/top-movers,/crypto-market/top-gainers-losers",
        )
        for path in [p.strip() for p in paths.split(",") if p.strip()]:
            ctx = top_movers_from_data(_get(path))
            if ctx.gainers or ctx.losers:
                ctx.reason = f"{ctx.reason} via {path}"
                return ctx
        return TopMoverContext([], [], "top movers: unavailable")

    try:
        cache_key = "top_movers:" + ",".join(symbols[:max_assets]) if symbols else "top_movers"
        ctx = _cached(cache_key, _fetch)
        ctx.from_cache = True
        return ctx
    except Exception as exc:
        return TopMoverContext([], [], f"top movers error: {exc}")


if __name__ == "__main__":
    ctx = fetch_macro_context()
    print(f"Macro context:")
    print(f"  ETF    : {ctx.etf.label}")
    print(f"  Sectors hot : {ctx.sector.hot_sectors}")
    print(f"  Sectors cold: {ctx.sector.cold_sectors}")
    if ctx.events:
        print(f"  Events  : {[(e.name, e.hours_until) for e in ctx.events]}")
    print(f"  LONG adj : {ctx.long_adj:+d}  SHORT adj: {ctx.short_adj:+d}")
    print(f"  Reason  : {ctx.reason}")
