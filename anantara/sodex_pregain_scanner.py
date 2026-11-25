#!/usr/bin/env python3
"""
SoDEX-native Top Pre-Gain/Loser scanner.

This adapter connects the existing Anantara Pre-Gain scoring core to SoDEX
spot + perps markets. It is a scanner/router only: no live orders are placed.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from anantara import pregain_signals
except ImportError:
    import pregain_signals  # type: ignore

try:
    from anantara import sosovalue_macro
except ImportError:
    import sosovalue_macro  # type: ignore


SODEX_SPOT_URL = os.environ.get("SODEX_SPOT_URL", "https://mainnet-gw.sodex.dev/api/v1/spot")
SODEX_PERPS_URL = os.environ.get("SODEX_PERPS_URL", "https://mainnet-gw.sodex.dev/api/v1/perps")
DEFAULT_MIN_SCORE = int(os.environ.get("SODEX_PREGAIN_MIN_SCORE", "60"))
DEFAULT_TOP_N = int(os.environ.get("SODEX_PREGAIN_TOP_N", "5"))
DEFAULT_WATCH_SCORE = int(os.environ.get("SODEX_PREGAIN_WATCH_SCORE", "40"))
MIN_VOL_USD = float(os.environ.get("SODEX_PREGAIN_MIN_VOL_USD", "100000"))
STATE_FILE = Path(os.environ.get(
    "SODEX_PREGAIN_STATE_FILE",
    str(Path.home() / ".local/share/anantara/sodex_pregain_state.json"),
))
STATE_MIN_INTERVAL_S = 30 * 60
STATE_MAX_INTERVAL_S = 24 * 3600
SOSO_EXP_EVENT_TS = os.environ.get("SODEX_SOSO_EXP_EVENT_TS", "2026-06-12T12:00:00+00:00")
SOSO_EXP_PRE_WINDOW_H = float(os.environ.get("SODEX_SOSO_EXP_PRE_WINDOW_H", "96"))
SOSO_EXP_POST_WINDOW_H = float(os.environ.get("SODEX_SOSO_EXP_POST_WINDOW_H", "12"))
SOSO_EXP_CATALYST_BOOST = int(os.environ.get("SODEX_SOSO_EXP_CATALYST_BOOST", "28"))
SOSO_EXP_DISTRIBUTION_RISK_PENALTY = int(os.environ.get("SODEX_SOSO_EXP_DISTRIBUTION_RISK_PENALTY", "8"))
SOSO_SNAPSHOT_MAX_ASSETS = int(os.environ.get("SODEX_SOSO_SNAPSHOT_MAX_ASSETS", "3"))


@dataclass
class SodexCandidate:
    symbol: str
    base: str
    market: str
    route: str
    direction: str
    score: int
    grade: str
    mark: float
    chg: float
    vol24: float
    spread_pct: float
    reasons: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "base": self.base,
            "market": self.market,
            "route": self.route,
            "direction": self.direction,
            "score": self.score,
            "grade": self.grade,
            "mark": self.mark,
            "chg": round(self.chg, 4),
            "vol24": round(self.vol24, 2),
            "spread_pct": round(self.spread_pct, 5),
            "reasons": self.reasons,
        }


def _fetch_json(url: str, timeout: int = 12) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "anantara-sodex-pregain/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_rows(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("tickers", "markets", "rows"):
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
    return []


def _num(row: dict, *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            try:
                return float(row.get(key))
            except (TypeError, ValueError):
                continue
    return default


def _symbol(row: dict) -> str:
    return str(row.get("symbol") or row.get("name") or row.get("displayName") or "")


def _base_from_symbol(symbol: str, market: str) -> str:
    if market == "spot":
        s = symbol.replace("v", "", 1)
        return s.split("_")[0].split("/")[0].replace("USDC", "")
    return symbol.split("-")[0].replace("1000", "")


def _normalize_ticker(row: dict, market: str) -> dict | None:
    symbol = _symbol(row)
    if not symbol:
        return None
    bid = _num(row, "bidPx", "bid", "bestBid", "b")
    ask = _num(row, "askPx", "ask", "bestAsk", "a")
    last = _num(row, "lastPx", "last", "price", "markPx", "mark")
    prev = _num(row, "prevDayPx", "openPx", "open", default=last)
    vol24 = _num(row, "quoteVolume", "volume_24h", "dayNtlVlm", "volume", "q")
    if vol24 <= 0:
        base_vol = _num(row, "baseVolume", "v")
        vol24 = base_vol * last if base_vol and last else 0.0
    if last <= 0:
        if bid > 0 and ask > 0:
            last = (bid + ask) / 2
        else:
            return None
    chg = _num(row, "changePct", "priceChangePercent", "chg")
    if chg == 0 and prev > 0:
        chg = (last - prev) / prev * 100
    spread_pct = ((ask - bid) / last * 100) if bid > 0 and ask > 0 else 999.0
    funding = _num(row, "funding", "fundingRate", "funding_rate")
    ann_fund = funding * 24 * 365 * 100 if abs(funding) < 1 else funding
    oi_raw = _num(row, "openInterest", "openInterestUsd", "oi")
    oi_usd = oi_raw * last if oi_raw > 0 and oi_raw < vol24 * 10 and "openInterestUsd" not in row else oi_raw
    return {
        "name": _base_from_symbol(symbol, market),
        "symbol": symbol,
        "market": market,
        "mark": last,
        "chg": chg,
        "fund": funding,
        "ann_fund": ann_fund,
        "oi": oi_usd,
        "vol24": vol24,
        "oi_vol": oi_usd / vol24 if vol24 > 0 and oi_usd > 0 else 0.0,
        "vol_oi": vol24 / oi_usd if oi_usd > 0 else 0.0,
        "liq": pregain_signals.liq_tier(vol24),
        "spread_pct": spread_pct,
        "_raw": row,
    }


def _soso_exp_event_context(now: datetime | None = None) -> dict:
    """SoSoValue EXP allocation/distribution catalyst window for WSOSO/SOSO."""
    try:
        event_ts = datetime.fromisoformat(SOSO_EXP_EVENT_TS.replace("Z", "+00:00"))
    except ValueError:
        return {"active": False, "reason": "invalid_event_ts"}
    if event_ts.tzinfo is None:
        event_ts = event_ts.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    hours_until = (event_ts.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds() / 3600.0
    active = -SOSO_EXP_POST_WINDOW_H <= hours_until <= SOSO_EXP_PRE_WINDOW_H
    if hours_until > 0:
        phase = "PRE_EVENT"
    elif hours_until >= -SOSO_EXP_POST_WINDOW_H:
        phase = "POST_EVENT_DISTRIBUTION"
    else:
        phase = "EXPIRED"
    return {
        "active": active,
        "phase": phase,
        "event_ts": event_ts.astimezone(timezone.utc).isoformat(),
        "hours_until": round(hours_until, 2),
    }


def _top_mover_symbols(top_movers, side: str) -> dict[str, Any]:
    movers = getattr(top_movers, "gainers" if side == "GAINER" else "losers", []) or []
    return {getattr(m, "symbol", "").upper(): m for m in movers if getattr(m, "symbol", "")}


def _top_mover_adj(asset: dict, direction: str, top_movers=None) -> tuple[int, list[str]]:
    """Score SoDEX assets that overlap SoSoValue Top Gainer/Loser watch data."""
    if not top_movers:
        return 0, []
    base = str(asset.get("name") or "").upper()
    if not base:
        return 0, []
    gainers = _top_mover_symbols(top_movers, "GAINER")
    losers = _top_mover_symbols(top_movers, "LOSER")
    chg = float(asset.get("chg", 0.0) or 0.0)

    if direction == "LONG" and base in gainers:
        mover = gainers[base]
        if chg > 18.0:
            return -8, [f"SOSO_TOP_GAINER_CHASE_RISK(rank={mover.rank})"]
        boost = 22 if chg <= 8.0 else 14
        reason = f"SOSO_PRE_TOP_GAINER_MATCH(rank={mover.rank},chg={mover.change_pct:.1f}%)"
        if getattr(mover, "range_pos_pct", 0.0) >= 75.0:
            boost += 6
            reason = f"{reason}:NEAR_24H_HIGH({mover.range_pos_pct:.0f}%)"
        return boost, [reason]
    if direction == "SHORT" and base in losers:
        mover = losers[base]
        if chg < -18.0:
            return -8, [f"SOSO_TOP_LOSER_CHASE_RISK(rank={mover.rank})"]
        boost = 22 if chg >= -8.0 else 14
        reason = f"SOSO_PRE_TOP_LOSER_MATCH(rank={mover.rank},chg={mover.change_pct:.1f}%)"
        if 0.0 < getattr(mover, "range_pos_pct", 0.0) <= 25.0:
            boost += 6
            reason = f"{reason}:NEAR_24H_LOW({mover.range_pos_pct:.0f}%)"
        return boost, [reason]
    if direction == "LONG" and base in losers:
        mover = losers[base]
        return -12, [f"SOSO_TOP_LOSER_HEADWIND(rank={mover.rank})"]
    if direction == "SHORT" and base in gainers:
        mover = gainers[base]
        return -12, [f"SOSO_TOP_GAINER_HEADWIND(rank={mover.rank})"]
    return 0, []


def _load_state() -> dict:
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text())
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {"assets": {}}


def _save_state(assets: list[dict]) -> None:
    now = datetime.now(timezone.utc).timestamp()
    rows = {}
    for asset in assets:
        key = f"{asset.get('market')}:{asset.get('symbol')}"
        rows[key] = {
            "ts": now,
            "ann_fund": asset.get("ann_fund", 0.0),
            "oi": asset.get("oi", 0.0),
            "vol24": asset.get("vol24", 0.0),
            "mark": asset.get("mark", 0.0),
        }
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(STATE_FILE) + ".tmp"
        Path(tmp).write_text(json.dumps({"ts": now, "assets": rows}, indent=2))
        os.replace(tmp, str(STATE_FILE))
    except Exception:
        pass


def enrich_with_state(assets: list[dict], state: dict | None = None) -> list[dict]:
    """Add leading deltas: funding acceleration, OI velocity, volume acceleration."""
    state = state or _load_state()
    prev_rows = state.get("assets", {}) if isinstance(state, dict) else {}
    now = datetime.now(timezone.utc).timestamp()
    enriched = []
    for asset in assets:
        a = dict(asset)
        key = f"{a.get('market')}:{a.get('symbol')}"
        prev = prev_rows.get(key, {}) if isinstance(prev_rows, dict) else {}
        elapsed_h = (now - float(prev.get("ts", 0) or 0)) / 3600 if prev else 0.0
        if STATE_MIN_INTERVAL_S / 3600 <= elapsed_h <= STATE_MAX_INTERVAL_S / 3600:
            a["fund_accel"] = (a.get("ann_fund", 0.0) - float(prev.get("ann_fund", 0) or 0)) / elapsed_h
            oi_prev = float(prev.get("oi", 0) or 0)
            vol_prev = float(prev.get("vol24", 0) or 0)
            a["oi_velocity_pct"] = ((a.get("oi", 0.0) - oi_prev) / oi_prev * 100) if oi_prev > 0 else 0.0
            a["vol_accel_pct"] = ((a.get("vol24", 0.0) - vol_prev) / vol_prev * 100) if vol_prev > 0 else 0.0
        else:
            a["fund_accel"] = 0.0
            a["oi_velocity_pct"] = 0.0
            a["vol_accel_pct"] = 0.0
        enriched.append(a)

    vols = [a.get("vol24", 0.0) for a in enriched if a.get("vol24", 0.0) > 0]
    if len(vols) >= 5:
        import math
        import statistics
        logs = [math.log(v) for v in vols]
        mu = statistics.mean(logs)
        sd = max(statistics.pstdev(logs), abs(mu) * 0.01 if mu else 0.01)
        for a in enriched:
            a["_vz"] = (math.log(max(a.get("vol24", 0.0), 1.0)) - mu) / sd
    return enriched


def fetch_perps_assets() -> list[dict]:
    payload = _fetch_json(f"{SODEX_PERPS_URL}/markets/tickers")
    assets = []
    for row in _extract_rows(payload):
        asset = _normalize_ticker(row, "perps")
        if asset and asset["vol24"] >= MIN_VOL_USD:
            assets.append(asset)
    return assets


def fetch_spot_assets() -> list[dict]:
    payload = _fetch_json(f"{SODEX_SPOT_URL}/markets/tickers")
    assets = []
    for row in _extract_rows(payload):
        asset = _normalize_ticker(row, "spot")
        if asset and asset["vol24"] >= MIN_VOL_USD:
            assets.append(asset)
    return assets


def _spot_score(asset: dict, macro=None, top_movers=None) -> tuple[int, list[str]]:
    """Leading spot-long score from sector/macro tailwind + liquidity + tradability.

    Spot has no native short/funding/OI. To keep this a pre-gain signal, the score
    favours assets with macro/sector tailwind before the move is mature.
    """
    score = 0
    reasons = []
    chg = asset["chg"]
    spread = asset["spread_pct"]
    event_ctx = _soso_exp_event_context()
    if asset["name"] in {"SOSO", "WSOSO"} and event_ctx.get("active"):
        if event_ctx.get("phase") == "PRE_EVENT":
            score += SOSO_EXP_CATALYST_BOOST
            reasons.append(f"SOSO_EXP_PRE_EVENT({event_ctx['hours_until']:.1f}h)")
        else:
            score += max(0, SOSO_EXP_CATALYST_BOOST // 2)
            score -= SOSO_EXP_DISTRIBUTION_RISK_PENALTY
            reasons.append("SOSO_EXP_DISTRIBUTION_RISK")
    sector_adj = sosovalue_macro.coin_sector_adj(asset["name"], macro.sector, "LONG") if macro else 0
    if sector_adj > 0:
        score += 28
        reasons.append("SOSO_SECTOR_TAILWIND")
    elif sector_adj < 0:
        score -= 18
        reasons.append("SOSO_SECTOR_HEADWIND")
    if macro and macro.long_adj > 0:
        score += macro.long_adj
        reasons.append("SOSO_MACRO_BULLISH")
    elif macro and macro.long_adj < 0:
        score += macro.long_adj
        reasons.append("SOSO_MACRO_BEARISH")
    tm_adj, tm_reasons = _top_mover_adj(asset, "LONG", top_movers=top_movers)
    if tm_adj:
        score += tm_adj
        reasons.extend(tm_reasons)
    if -4.0 <= chg <= 8.0:
        score += 20
        reasons.append(f"PRE_MOVE_ZONE({chg:.1f}%)")
    elif 8.0 < chg <= 18.0:
        score += 8
        reasons.append(f"EARLY_BUT_MOVING({chg:.1f}%)")
    elif chg > 18.0:
        score -= 30
        reasons.append(f"CHASE_RISK({chg:.1f}%)")
    elif chg < -18.0:
        score -= 15
        reasons.append(f"FALLING_KNIFE({chg:.1f}%)")
    if asset["vol24"] >= 1_000_000:
        score += 20
        reasons.append("LIQUID_SPOT")
    if 0.05 <= spread <= 0.60:
        score += 20
        reasons.append(f"CAPTURABLE_SPREAD({spread:.3f}%)")
    if spread > 1.0:
        score -= 25
        reasons.append(f"SPREAD_TOO_WIDE({spread:.3f}%)")
    return max(0, min(100, score)), reasons[:4]


def build_candidates(
    perps_assets: list[dict],
    spot_assets: list[dict],
    min_score: int = DEFAULT_MIN_SCORE,
    macro=None,
    top_movers=None,
) -> tuple[list[SodexCandidate], list[SodexCandidate]]:
    longs: list[SodexCandidate] = []
    shorts: list[SodexCandidate] = []
    bn_rates: dict[str, float] = {}

    for asset in perps_assets:
        long_score, long_reasons = pregain_signals.score_long(asset, bn_rates)
        short_score, short_reasons = pregain_signals.score_short(asset, bn_rates)
        fas, fasig = pregain_signals.score_funding_accel(asset)
        if fas > 0:
            short_score = min(100, short_score + fas)
            short_reasons = (short_reasons + fasig)[:4]
        oi_vel = float(asset.get("oi_velocity_pct", 0.0) or 0.0)
        vol_accel = float(asset.get("vol_accel_pct", 0.0) or 0.0)
        if oi_vel > 8 and abs(asset.get("chg", 0.0)) < 8:
            boost = min(18, int(oi_vel))
            long_score = min(100, long_score + boost)
            short_score = min(100, short_score + boost // 2)
            long_reasons = (long_reasons + [f"OI_VELOCITY(+{oi_vel:.1f}%)"])[:4]
            short_reasons = (short_reasons + [f"OI_VELOCITY(+{oi_vel:.1f}%)"])[:4]
        if vol_accel > 25 and abs(asset.get("chg", 0.0)) < 10:
            boost = min(12, int(vol_accel / 5))
            long_score = min(100, long_score + boost)
            long_reasons = (long_reasons + [f"VOL_ACCEL(+{vol_accel:.1f}%)"])[:4]
        if macro:
            long_adj = macro.long_adj + sosovalue_macro.coin_sector_adj(asset["name"], macro.sector, "LONG")
            short_adj = macro.short_adj + sosovalue_macro.coin_sector_adj(asset["name"], macro.sector, "SHORT")
            if long_adj:
                long_score = min(100, max(0, long_score + long_adj))
                long_reasons = (long_reasons + [f"SOSO_ADJ({long_adj:+d})"])[:4]
            if short_adj:
                short_score = min(100, max(0, short_score + short_adj))
                short_reasons = (short_reasons + [f"SOSO_ADJ({short_adj:+d})"])[:4]
        long_tm_adj, long_tm_reasons = _top_mover_adj(asset, "LONG", top_movers=top_movers)
        if long_tm_adj:
            long_score = min(100, max(0, long_score + long_tm_adj))
            long_reasons = (long_reasons + long_tm_reasons)[:4]
        short_tm_adj, short_tm_reasons = _top_mover_adj(asset, "SHORT", top_movers=top_movers)
        if short_tm_adj:
            short_score = min(100, max(0, short_score + short_tm_adj))
            short_reasons = (short_reasons + short_tm_reasons)[:4]
        if long_score >= min_score and asset["liq"] != "DUST":
            longs.append(SodexCandidate(
                symbol=asset["symbol"], base=asset["name"], market="perps",
                route="PERPS_LONG", direction="LONG", score=long_score,
                grade=pregain_signals.grade(long_score), mark=asset["mark"],
                chg=asset["chg"], vol24=asset["vol24"], spread_pct=asset["spread_pct"],
                reasons=long_reasons, raw=asset["_raw"],
            ))
        if short_score >= min_score and asset["liq"] != "DUST":
            shorts.append(SodexCandidate(
                symbol=asset["symbol"], base=asset["name"], market="perps",
                route="PERPS_SHORT", direction="SHORT", score=short_score,
                grade=pregain_signals.grade(short_score), mark=asset["mark"],
                chg=asset["chg"], vol24=asset["vol24"], spread_pct=asset["spread_pct"],
                reasons=short_reasons, raw=asset["_raw"],
            ))

    perps_bases = {a["name"] for a in perps_assets}
    for asset in spot_assets:
        score, reasons = _spot_score(asset, macro=macro, top_movers=top_movers)
        if score >= min_score and asset["liq"] != "DUST":
            route = "SPOT_LONG" if asset["name"] not in perps_bases else "SPOT_LONG_OR_PERPS_LONG"
            longs.append(SodexCandidate(
                symbol=asset["symbol"], base=asset["name"], market="spot",
                route=route, direction="LONG", score=score,
                grade=pregain_signals.grade(score), mark=asset["mark"],
                chg=asset["chg"], vol24=asset["vol24"], spread_pct=asset["spread_pct"],
                reasons=reasons, raw=asset["_raw"],
            ))

    longs.sort(key=lambda c: (c.score, c.vol24), reverse=True)
    shorts.sort(key=lambda c: (c.score, c.vol24), reverse=True)
    return longs, shorts


def scan(
    min_score: int = DEFAULT_MIN_SCORE,
    top_n: int = DEFAULT_TOP_N,
    include_assets: bool = False,
) -> dict:
    errors: list[str] = []
    try:
        perps_assets = fetch_perps_assets()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        perps_assets = []
        errors.append(f"perps:{type(exc).__name__}")
    try:
        spot_assets = fetch_spot_assets()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        spot_assets = []
        errors.append(f"spot:{type(exc).__name__}")

    try:
        macro = sosovalue_macro.fetch_macro_context()
    except Exception:
        macro = None
    try:
        snapshot_symbols = [
            a["name"] for a in sorted(
                spot_assets + perps_assets,
                key=lambda x: (x.get("market") == "spot", x.get("vol24", 0.0)),
                reverse=True,
            )
        ]
        top_movers = sosovalue_macro.fetch_top_mover_context(
            symbols=snapshot_symbols,
            max_assets=SOSO_SNAPSHOT_MAX_ASSETS,
        )
    except Exception:
        top_movers = None

    perps_assets = enrich_with_state(perps_assets)
    spot_assets = enrich_with_state(spot_assets)
    watch_floor = min(DEFAULT_WATCH_SCORE, min_score)
    radar_longs, radar_shorts = build_candidates(
        perps_assets, spot_assets, min_score=1, macro=macro, top_movers=top_movers
    )
    watch_longs, watch_shorts = build_candidates(
        perps_assets, spot_assets, min_score=watch_floor, macro=macro, top_movers=top_movers
    )
    longs = [c for c in watch_longs if c.score >= min_score]
    shorts = [c for c in watch_shorts if c.score >= min_score]
    watch_longs = [c for c in watch_longs if c.score < min_score]
    watch_shorts = [c for c in watch_shorts if c.score < min_score]
    tracked_long_keys = {(c.market, c.symbol, c.direction) for c in longs + watch_longs}
    tracked_short_keys = {(c.market, c.symbol, c.direction) for c in shorts + watch_shorts}
    radar_longs = [
        c for c in radar_longs
        if (c.market, c.symbol, c.direction) not in tracked_long_keys
    ]
    radar_shorts = [
        c for c in radar_shorts
        if (c.market, c.symbol, c.direction) not in tracked_short_keys
    ]
    _save_state(perps_assets + spot_assets)
    observed_assets = [
        {
            "symbol": a.get("symbol"),
            "market": a.get("market"),
            "mark": a.get("mark", 0.0),
            "chg": a.get("chg", 0.0),
            "vol24": a.get("vol24", 0.0),
            "spread_pct": a.get("spread_pct", 0.0),
        }
        for a in perps_assets + spot_assets
    ]
    result = {
        "status": "OK" if not errors else "PARTIAL",
        "ts": datetime.now(timezone.utc).isoformat(),
        "min_score": min_score,
        "watch_score": watch_floor,
        "universe": {"perps": len(perps_assets), "spot": len(spot_assets)},
        "top_longs": [c.to_dict() for c in longs[:top_n]],
        "top_shorts": [c.to_dict() for c in shorts[:top_n]],
        "watchlist_longs": [c.to_dict() for c in watch_longs[:top_n]],
        "watchlist_shorts": [c.to_dict() for c in watch_shorts[:top_n]],
        "radar_longs": [c.to_dict() for c in radar_longs[:top_n]],
        "radar_shorts": [c.to_dict() for c in radar_shorts[:top_n]],
        "diagnostics": {
            "max_long_score": (
                longs[0].score if longs else
                watch_longs[0].score if watch_longs else
                radar_longs[0].score if radar_longs else 0
            ),
            "max_short_score": (
                shorts[0].score if shorts else
                watch_shorts[0].score if watch_shorts else
                radar_shorts[0].score if radar_shorts else 0
            ),
            "trade_grade_longs": len(longs),
            "trade_grade_shorts": len(shorts),
            "watch_longs": len(watch_longs),
            "watch_shorts": len(watch_shorts),
            "radar_longs": len(radar_longs),
            "radar_shorts": len(radar_shorts),
        },
        "macro": {
            "reason": getattr(macro, "reason", "unavailable"),
            "long_adj": getattr(macro, "long_adj", 0),
            "short_adj": getattr(macro, "short_adj", 0),
            "hot_sectors": getattr(getattr(macro, "sector", None), "hot_sectors", []),
            "cold_sectors": getattr(getattr(macro, "sector", None), "cold_sectors", []),
        },
        "top_movers": {
            "reason": getattr(top_movers, "reason", "unavailable"),
            "gainers": [getattr(m, "symbol", "") for m in (getattr(top_movers, "gainers", []) or [])[:10]],
            "losers": [getattr(m, "symbol", "") for m in (getattr(top_movers, "losers", []) or [])[:10]],
        },
        "catalysts": {
            "soso_exp": _soso_exp_event_context(),
        },
        "errors": errors,
    }
    if include_assets:
        result["observed_assets"] = observed_assets
    return result


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="SoDEX Top Pre-Gain/Loser scanner")
    parser.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE)
    parser.add_argument("--top", type=int, default=DEFAULT_TOP_N)
    args = parser.parse_args()
    print(json.dumps(scan(min_score=args.min_score, top_n=args.top), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
