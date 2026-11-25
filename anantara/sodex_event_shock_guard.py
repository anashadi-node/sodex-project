#!/usr/bin/env python3
"""External event shock guard for SoDEX research.

Read-only headline risk monitor for geopolitical, policy, and whale-treasury
events that can invalidate short-horizon crypto signals before price data fully
reflects the shock.
"""
from __future__ import annotations

import email.utils
import html
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


CACHE_TTL_S = int(os.environ.get("SODEX_EVENT_RISK_TTL_S", "300"))
MAX_ITEMS_PER_FEED = int(os.environ.get("SODEX_EVENT_RISK_MAX_ITEMS", "8"))
_CACHE: tuple[float, dict] = (0.0, {})

QUERIES = [
    "Iran OR Hormuz OR war bitcoin OR crypto",
    "Trump crypto bitcoin tariff Fed regulation",
    "\"Michael Saylor\" OR Strategy bitcoin sale",
    "\"Whale Alert\" bitcoin exchange transfer",
    "\"token unlock\" OR \"token distribution\" OR \"vesting\" bitcoin crypto",
]

EVENT_RULES = {
    "geo": {
        "weight": 35,
        "terms": ("iran", "hormuz", "war", "missile", "sanction", "geopolitical"),
    },
    "policy": {
        "weight": 28,
        "terms": ("trump", "tariff", "fed", "sec", "regulation", "executive order"),
    },
    "whale": {
        "weight": 26,
        "terms": ("whale", "saylor", "strategy", "microstrategy", "exchange transfer"),
    },
    "tokenomics": {
        "weight": 22,
        "terms": ("unlock", "distribution", "vesting", "airdrop", "token release",
                  "foundation sale", "treasury sale", "cliff"),
    },
    "panic": {
        "weight": 14,
        "terms": ("sell", "sold", "sale", "crash", "plunge", "liquidation", "outflow"),
    },
}


@dataclass
class HeadlineHit:
    title: str
    link: str
    source: str
    published: str
    categories: list[str] = field(default_factory=list)
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title[:180],
            "link": self.link,
            "source": self.source,
            "published": self.published,
            "categories": self.categories,
            "score": round(self.score, 2),
        }


def _default_feeds() -> list[str]:
    custom = os.environ.get("SODEX_EVENT_RSS_URLS", "").strip()
    if custom:
        return [x.strip() for x in custom.split(",") if x.strip()]
    feeds = []
    for query in QUERIES:
        q = urllib.parse.quote_plus(query)
        feeds.append(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en")
    return feeds


def _parse_date(value: str) -> datetime | None:
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _age_factor(published: str, now: datetime) -> float:
    dt = _parse_date(published)
    if not dt:
        return 0.8
    age_h = max(0.0, (now - dt).total_seconds() / 3600)
    if age_h <= 6:
        return 1.0
    if age_h <= 24:
        return 0.7
    if age_h <= 72:
        return 0.4
    return 0.15


def _classify(title: str, description: str, published: str, now: datetime) -> tuple[float, list[str]]:
    text = f"{title} {description}".lower()
    categories = []
    score = 0.0
    for name, rule in EVENT_RULES.items():
        if any(term in text for term in rule["terms"]):
            categories.append(name)
            score += float(rule["weight"])
    if "bitcoin" in text or "btc" in text or "crypto" in text:
        score += 8
    return min(100.0, score * _age_factor(published, now)), categories


def _fetch_feed(url: str, timeout: int = 8) -> list[HeadlineHit]:
    req = urllib.request.Request(url, headers={"User-Agent": "anantara-sodex-event-guard/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    root = ET.fromstring(data)
    now = datetime.now(timezone.utc)
    hits: list[HeadlineHit] = []
    for item in root.findall(".//item")[:MAX_ITEMS_PER_FEED]:
        title = html.unescape(item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = html.unescape(item.findtext("description") or "").strip()
        published = (item.findtext("pubDate") or "").strip()
        source = item.findtext("source") or ""
        score, categories = _classify(title, desc, published, now)
        if score <= 0 or not categories:
            continue
        hits.append(HeadlineHit(title, link, source, published, categories, score))
    return hits


def _level(score: float) -> str:
    if score >= 75:
        return "RED"
    if score >= 55:
        return "ORANGE"
    if score >= 30:
        return "YELLOW"
    return "NORMAL"


def event_route_policy(level: str, risk_score: float, categories: list[str]) -> dict[str, Any]:
    """Route-aware event policy: shocks close some routes but reveal others."""
    cats = set(categories or [])
    risk_off = bool(cats & {"geo", "policy", "panic", "whale"})
    if level == "NORMAL":
        return {
            "regime": "NORMAL",
            "opportunity_bias": "BALANCED",
            "size_multiplier": 1.0,
            "route_gates": {
                "SPOT_LONG": "ALLOW_LIVE",
                "PERPS_LONG": "ALLOW_LIVE",
                "PERPS_SHORT": "ALLOW_LIVE",
            },
            "opportunity_routes": ["SPOT_LONG", "PERPS_LONG", "PERPS_SHORT"],
            "notes": ["normal event risk"],
        }
    if level == "YELLOW":
        return {
            "regime": "CAUTION",
            "opportunity_bias": "BALANCED",
            "size_multiplier": 0.5,
            "route_gates": {
                "SPOT_LONG": "ALLOW_REDUCED_LIVE",
                "PERPS_LONG": "ALLOW_REDUCED_LIVE",
                "PERPS_SHORT": "ALLOW_REDUCED_LIVE",
            },
            "opportunity_routes": ["SPOT_LONG", "PERPS_LONG", "PERPS_SHORT"],
            "notes": ["reduced size while event risk is elevated"],
        }
    if level == "ORANGE":
        bias = "SHORT" if risk_off else "BALANCED"
        return {
            "regime": "RISK_OFF_ELEVATED" if risk_off else "ELEVATED_UNCERTAINTY",
            "opportunity_bias": bias,
            "size_multiplier": 0.25,
            "route_gates": {
                "SPOT_LONG": "RESEARCH_ONLY",
                "PERPS_LONG": "RESEARCH_ONLY",
                "PERPS_SHORT": "RESEARCH_ONLY" if risk_off else "PAPER_ONLY",
            },
            "opportunity_routes": ["PERPS_SHORT"] if risk_off else ["PERPS_LONG", "PERPS_SHORT"],
            "notes": ["live spot-long paused; continue paper/risk-off opportunity tracking"],
        }
    # RED and any future more severe external shock level.
    bias = "SHORT" if risk_off else "NONE"
    return {
        "regime": "RISK_OFF_SHOCK" if risk_off else "SHOCK_UNCLEAR_DIRECTION",
        "opportunity_bias": bias,
        "size_multiplier": 0.0,
        "route_gates": {
            "SPOT_LONG": "BLOCK_LIVE",
            "PERPS_LONG": "BLOCK_LIVE",
            "PERPS_SHORT": "RESEARCH_ONLY" if risk_off else "BLOCK_LIVE",
        },
        "opportunity_routes": ["PERPS_SHORT"] if risk_off else [],
        "notes": [
            "block live spot-long during shock",
            "keep measuring risk-off short/hedge opportunities instead of stopping research",
        ],
    }


def enrich_event_route_policy(risk: dict[str, Any]) -> dict[str, Any]:
    """Backfill route-aware event fields for legacy status snapshots."""
    enriched = dict(risk or {})
    level = str(enriched.get("level") or "NORMAL")
    try:
        risk_score = float(enriched.get("risk_score") or 0.0)
    except (TypeError, ValueError):
        risk_score = 0.0

    categories = enriched.get("categories")
    if not isinstance(categories, list) or not categories:
        category_set = set()
        for hit in enriched.get("top_hits", []) or []:
            if not isinstance(hit, dict):
                continue
            for category in hit.get("categories", []) or []:
                if isinstance(category, str) and category:
                    category_set.add(category)
        categories = sorted(category_set)
    else:
        categories = sorted({str(category) for category in categories if category})

    route_policy = enriched.get("route_policy")
    if not isinstance(route_policy, dict) or not route_policy:
        route_policy = event_route_policy(level, risk_score, categories)

    enriched["categories"] = categories
    enriched["route_policy"] = route_policy
    enriched["opportunity_bias"] = enriched.get("opportunity_bias") or route_policy.get("opportunity_bias")
    enriched["opportunity_routes"] = enriched.get("opportunity_routes") or route_policy.get("opportunity_routes", [])
    return enriched


def fetch_event_risk(force: bool = False) -> dict:
    global _CACHE
    now_s = time.time()
    if not force and _CACHE[1] and now_s - _CACHE[0] < CACHE_TTL_S:
        cached = dict(_CACHE[1])
        cached["from_cache"] = True
        return cached

    errors = []
    hits: list[HeadlineHit] = []
    for url in _default_feeds():
        try:
            hits.extend(_fetch_feed(url))
        except Exception as exc:
            errors.append(type(exc).__name__)

    hits.sort(key=lambda h: h.score, reverse=True)
    risk_score = min(100.0, sum(h.score for h in hits[:5]) / 2.0)
    level = _level(risk_score)
    categories = sorted({cat for hit in hits[:5] for cat in hit.categories})
    result = {
        "status": "OK" if hits or not errors else "PARTIAL",
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "risk_score": round(risk_score, 2),
        "live_gate": "BLOCK_LIVE" if level in {"ORANGE", "RED"} else "ALLOW_WITH_CAUTION",
        "categories": categories,
        "reason": " | ".join(h.title[:90] for h in hits[:3]) if hits else "no external shock headlines",
        "top_hits": [h.to_dict() for h in hits[:5]],
        "errors": errors[:4],
        "from_cache": False,
    }
    result = enrich_event_route_policy(result)
    _CACHE = (now_s, result)
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(fetch_event_risk(force=True), indent=2))
