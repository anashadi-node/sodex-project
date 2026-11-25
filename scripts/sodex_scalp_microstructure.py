#!/usr/bin/env python3
"""Read-only SoDEX scalp microstructure scanner.

This does not place or cancel orders.  It answers one narrow question:
which SoDEX perps have fee/spread geometry that can plausibly satisfy the
project's minimum real-volume/loss ratio.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
WIB = timezone(timedelta(hours=7))
EMERGENCY_RATIO_UNTIL_WIB = datetime(2026, 7, 18, 9, 30, tzinfo=WIB)
_DEFAULT_MIN_REAL_VOLUME_LOSS_RATIO = "5100" if datetime.now(WIB) <= EMERGENCY_RATIO_UNTIL_WIB else "7000"
MIN_REAL_VOLUME_LOSS_RATIO = Decimal(os.environ.get("SODEX_SCALP_MIN_REAL_VOLUME_LOSS_RATIO", _DEFAULT_MIN_REAL_VOLUME_LOSS_RATIO))
MIN_QUOTE_VOLUME_USD = Decimal("100000")
MAX_SPREAD_BPS = Decimal("80")


def dec(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def run_json(args: list[str]) -> Any:
    proc = subprocess.run(
        args,
        cwd=PROJECT,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"command_failed:{args[:4]}:rc={proc.returncode}:{proc.stderr[-300:]}")
    return json.loads(proc.stdout or "null")


@dataclass(frozen=True)
class ScalpRow:
    symbol: str
    mid: float
    spread_bps: float
    quote_volume_usd: float
    change_pct: float
    funding_bps: float
    maker_fee_bps_rt: float
    taker_fee_bps_rt: float
    taker_roundtrip_loss_bps: float
    ratio_budget_loss_bps: float
    maker_gross_edge_bps: float
    taker_ratio_pass: bool
    maker_ratio_pass_before_adverse: bool
    scalp_lane: str


def ratio_budget_loss_bps(ratio: Decimal = MIN_REAL_VOLUME_LOSS_RATIO) -> Decimal:
    if ratio <= 0:
        return Decimal("0")
    return (Decimal("2") / ratio) * Decimal("10000")


def classify_lane(
    *,
    quote_volume: Decimal,
    spread_bps: Decimal,
    maker_gross_edge_bps: Decimal,
    taker_loss_bps: Decimal,
    budget_bps: Decimal,
) -> str:
    if taker_loss_bps <= budget_bps:
        return "TAKER_ALLOWED_RARE"
    if quote_volume < MIN_QUOTE_VOLUME_USD:
        return "REJECT_THIN_VOLUME"
    if spread_bps > MAX_SPREAD_BPS:
        return "REJECT_TOO_WIDE_ADVERSE_SELECTION"
    if maker_gross_edge_bps > Decimal("1.0"):
        return "MAKER_ONLY_CANDIDATE"
    if maker_gross_edge_bps >= Decimal("0"):
        return "MAKER_ONLY_THIN_EDGE"
    return "REJECT_NEGATIVE_AFTER_MAKER_FEES"


def build_rows(markets: list[dict[str, Any]], tickers: list[dict[str, Any]]) -> list[ScalpRow]:
    market_by_symbol = {
        str(row.get("name") or row.get("displayName") or ""): row
        for row in markets
        if str(row.get("status") or "") == "TRADING"
    }
    budget_bps = ratio_budget_loss_bps()
    rows: list[ScalpRow] = []
    for ticker in tickers:
        symbol = str(ticker.get("symbol") or "")
        market = market_by_symbol.get(symbol)
        if not market:
            continue
        bid = dec(ticker.get("bidPx"))
        ask = dec(ticker.get("askPx"))
        if bid <= 0 or ask <= bid:
            continue
        mid = (bid + ask) / Decimal("2")
        spread_bps = ((ask - bid) / mid) * Decimal("10000")
        quote_volume = dec(ticker.get("quoteVolume"))
        maker_fee_bps_rt = dec(market.get("makerFee")) * Decimal("20000")
        taker_fee_bps_rt = dec(market.get("takerFee")) * Decimal("20000")
        taker_loss_bps = spread_bps + taker_fee_bps_rt
        maker_gross_edge_bps = spread_bps - maker_fee_bps_rt
        lane = classify_lane(
            quote_volume=quote_volume,
            spread_bps=spread_bps,
            maker_gross_edge_bps=maker_gross_edge_bps,
            taker_loss_bps=taker_loss_bps,
            budget_bps=budget_bps,
        )
        rows.append(ScalpRow(
            symbol=symbol,
            mid=float(mid),
            spread_bps=float(spread_bps),
            quote_volume_usd=float(quote_volume),
            change_pct=float(dec(ticker.get("changePct"))),
            funding_bps=float(dec(ticker.get("fundingRate")) * Decimal("10000")),
            maker_fee_bps_rt=float(maker_fee_bps_rt),
            taker_fee_bps_rt=float(taker_fee_bps_rt),
            taker_roundtrip_loss_bps=float(taker_loss_bps),
            ratio_budget_loss_bps=float(budget_bps),
            maker_gross_edge_bps=float(maker_gross_edge_bps),
            taker_ratio_pass=taker_loss_bps <= budget_bps,
            maker_ratio_pass_before_adverse=maker_fee_bps_rt <= budget_bps,
            scalp_lane=lane,
        ))
    return sorted(
        rows,
        key=lambda row: (
            row.scalp_lane == "MAKER_ONLY_CANDIDATE",
            row.maker_gross_edge_bps,
            row.quote_volume_usd,
        ),
        reverse=True,
    )


def main() -> int:
    markets = run_json(["bin/sodex", "markets", "perps", "--format", "json"])
    tickers = run_json(["bin/sodex", "tickers", "perps", "--format", "json"])
    rows = build_rows(markets if isinstance(markets, list) else [], tickers if isinstance(tickers, list) else [])
    summary = {
        "mode": "read_only",
        "min_real_volume_loss_ratio": float(MIN_REAL_VOLUME_LOSS_RATIO),
        "ratio_budget_loss_bps": float(ratio_budget_loss_bps()),
        "interpretation": {
            "taker": "must be <= ratio_budget_loss_bps; normally impossible when taker fee alone is higher",
            "maker": "only viable if both legs are maker and adverse selection is near zero or spread is captured",
        },
        "counts": {
            "total_scanned": len(rows),
            "maker_only_candidate": sum(1 for row in rows if row.scalp_lane == "MAKER_ONLY_CANDIDATE"),
            "maker_only_thin_edge": sum(1 for row in rows if row.scalp_lane == "MAKER_ONLY_THIN_EDGE"),
            "taker_ratio_pass": sum(1 for row in rows if row.taker_ratio_pass),
        },
        "top": [asdict(row) for row in rows[:20]],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
