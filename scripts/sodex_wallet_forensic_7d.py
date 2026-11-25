#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError as exc:  # pragma: no cover
    raise SystemExit("httpx is required; run from the Anantara research venv") from exc


PERPS = "https://mainnet-gw.sodex.dev/api/v1/perps"
SPOT = "https://mainnet-gw.sodex.dev/api/v1/spot"
LIMIT = 100
MAX_PAGES = 500


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def dt_from_ms(value: int | float | str | None) -> datetime | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000, timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fnum(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        if math.isfinite(number):
            return number
    except (TypeError, ValueError):
        pass
    return default


def quantiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0, "p25": 0, "median": 0, "p75": 0, "max": 0, "mean": 0}
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "p25": ordered[len(ordered) // 4],
        "median": statistics.median(ordered),
        "p75": ordered[(len(ordered) * 3) // 4],
        "max": ordered[-1],
        "mean": statistics.fmean(ordered),
    }


def pct(numerator: float, denominator: float) -> float:
    return numerator / denominator * 100.0 if denominator else 0.0


def money(value: float) -> str:
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000:
        return f"{sign}${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{sign}${value / 1_000:.2f}K"
    return f"{sign}${value:.2f}"


@dataclass
class FetchResult:
    data: Any
    error: str | None = None


class SodexClient:
    def __init__(self, timeout: float = 25.0):
        self.client = httpx.Client(timeout=timeout, headers={"user-agent": "anantara-sodex-wallet-audit/1.0"})

    def get(self, url: str) -> FetchResult:
        try:
            response = self.client.get(url)
            if response.status_code != 200:
                return FetchResult(None, f"HTTP {response.status_code}")
            body = response.json()
            if body.get("code") != 0:
                return FetchResult(None, f"API code {body.get('code')}")
            return FetchResult(body.get("data"))
        except Exception as exc:
            return FetchResult(None, f"{type(exc).__name__}: {exc}")

    def paginated_since(self, url: str, cutoff_ms: int, max_pages: int = MAX_PAGES) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        pages = 0
        stopped_by_cutoff = False
        for page in range(max_pages):
            separator = "&" if "?" in url else "?"
            result = self.get(f"{url}{separator}limit={LIMIT}&offset={page * LIMIT}")
            pages += 1
            if result.error:
                errors.append(result.error)
                break
            data = result.data or []
            if isinstance(data, dict):
                data = [data]
            if not data:
                break
            typed_rows = [row for row in data if isinstance(row, dict)]
            rows.extend(row for row in typed_rows if int(row.get("time") or 0) >= cutoff_ms)
            times = [int(row.get("time") or 0) for row in typed_rows]
            if times and max(times) < cutoff_ms:
                stopped_by_cutoff = True
                break
            if len(typed_rows) < LIMIT:
                break
            time.sleep(0.08)
        return rows, {"pages": pages, "errors": errors, "stopped_by_cutoff": stopped_by_cutoff}


def normalize_addresses(raw: str) -> tuple[list[str], list[str]]:
    seen: set[str] = set()
    unique: list[str] = []
    duplicates: list[str] = []
    for token in raw.replace("&", ",").replace("\n", ",").split(","):
        address = token.strip().lower()
        if not address:
            continue
        if not (address.startswith("0x") and len(address) == 42):
            continue
        if address in seen:
            duplicates.append(address)
            continue
        seen.add(address)
        unique.append(address)
    return unique, duplicates


def realized_from_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    positions: dict[str, dict[str, float]] = defaultdict(lambda: {"qty": 0.0, "avg": 0.0})
    realized_by_symbol: dict[str, float] = defaultdict(float)
    gross_realized = 0.0
    for trade in sorted(trades, key=lambda row: int(row.get("time") or 0)):
        symbol = str(trade.get("symbol") or "")
        price = fnum(trade.get("price"))
        qty = fnum(trade.get("quantity"))
        if not symbol or price <= 0 or qty <= 0:
            continue
        signed_qty = qty if str(trade.get("side")).upper() == "BUY" else -qty
        pos = positions[symbol]
        old_qty = pos["qty"]
        old_avg = pos["avg"]
        if old_qty == 0 or old_qty * signed_qty > 0:
            new_qty = old_qty + signed_qty
            pos["avg"] = ((abs(old_qty) * old_avg) + (abs(signed_qty) * price)) / abs(new_qty)
            pos["qty"] = new_qty
            continue
        close_qty = min(abs(old_qty), abs(signed_qty))
        pnl = (price - old_avg) * close_qty if old_qty > 0 else (old_avg - price) * close_qty
        gross_realized += pnl
        realized_by_symbol[symbol] += pnl
        new_qty = old_qty + signed_qty
        if new_qty == 0:
            pos["qty"] = 0.0
            pos["avg"] = 0.0
        elif old_qty * new_qty > 0:
            pos["qty"] = new_qty
        else:
            pos["qty"] = new_qty
            pos["avg"] = price
    return {
        "gross_realized_pnl_reconstructed": gross_realized,
        "by_symbol": dict(sorted(realized_by_symbol.items(), key=lambda item: abs(item[1]), reverse=True)),
        "open_lot_count_from_window": sum(1 for pos in positions.values() if abs(pos["qty"]) > 1e-12),
    }


def classify(summary: dict[str, Any]) -> str:
    maker_trade_pct = summary["perps_7d"]["maker_trade_pct"]
    total_trades = summary["perps_7d"]["trades"]
    unique_symbols = summary["perps_7d"]["unique_symbols"]
    if total_trades == 0:
        return "INACTIVE_OR_NO_RECENT_PERPS"
    if maker_trade_pct >= 85:
        return "PURE_MAKER_FARM"
    if maker_trade_pct >= 60:
        return "MAKER_DOMINANT_HYBRID"
    if maker_trade_pct <= 10 and unique_symbols >= 10:
        return "MULTI_ASSET_TAKER_BOT"
    if maker_trade_pct <= 10:
        return "TAKER_CHURN_OR_DIRECTIONAL_BOT"
    return "HYBRID_BOT"


def analyze_wallet(client: SodexClient, address: str, cutoff_ms: int) -> dict[str, Any]:
    state_result = client.get(f"{PERPS}/accounts/{address}/state")
    fee_result = client.get(f"{PERPS}/accounts/{address}/fee-rate")
    positions_result = client.get(f"{PERPS}/accounts/{address}/positions")
    perps_trades, perps_fetch = client.paginated_since(f"{PERPS}/accounts/{address}/trades", cutoff_ms)
    spot_trades, spot_fetch = client.paginated_since(f"{SPOT}/accounts/{address}/trades", cutoff_ms, max_pages=60)

    state = state_result.data if isinstance(state_result.data, dict) else {}
    fee = fee_result.data if isinstance(fee_result.data, dict) else {}
    positions_data = positions_result.data if isinstance(positions_result.data, dict) else {}
    positions = [row for row in positions_data.get("positions", []) if isinstance(row, dict)]
    active_positions = [row for row in positions if row.get("active")]

    volume_by_symbol: dict[str, float] = defaultdict(float)
    fee_by_symbol: dict[str, float] = defaultdict(float)
    trade_count_by_symbol: Counter[str] = Counter()
    maker_count_by_symbol: Counter[str] = Counter()
    buy_count_by_symbol: Counter[str] = Counter()
    sell_count_by_symbol: Counter[str] = Counter()
    hour_count: Counter[str] = Counter()
    day_count: Counter[str] = Counter()
    sizes: list[float] = []
    timestamps: list[int] = []
    maker_trades = 0
    maker_volume = 0.0
    total_fees = 0.0

    for trade in perps_trades:
        symbol = str(trade.get("symbol") or "UNKNOWN")
        size = fnum(trade.get("price")) * fnum(trade.get("quantity"))
        fee_value = fnum(trade.get("fee"))
        is_maker = bool(trade.get("isMaker"))
        trade_time = int(trade.get("time") or 0)
        dt = dt_from_ms(trade_time)
        volume_by_symbol[symbol] += size
        fee_by_symbol[symbol] += fee_value
        trade_count_by_symbol[symbol] += 1
        sizes.append(size)
        timestamps.append(trade_time)
        total_fees += fee_value
        if is_maker:
            maker_trades += 1
            maker_volume += size
            maker_count_by_symbol[symbol] += 1
        if str(trade.get("side")).upper() == "BUY":
            buy_count_by_symbol[symbol] += 1
        else:
            sell_count_by_symbol[symbol] += 1
        if dt:
            hour_count[f"{dt.hour:02d}:00"] += 1
            day_count[dt.strftime("%a")] += 1

    total_volume = sum(volume_by_symbol.values())
    first_trade = dt_from_ms(min(timestamps)) if timestamps else None
    last_trade = dt_from_ms(max(timestamps)) if timestamps else None
    span_hours = ((last_trade - first_trade).total_seconds() / 3600.0) if first_trade and last_trade and last_trade > first_trade else 0.0
    intervals_ms = [b - a for a, b in zip(sorted(timestamps), sorted(timestamps)[1:]) if b >= a]
    realized = realized_from_trades(perps_trades)

    state_positions = [row for row in state.get("P", []) if isinstance(row, dict)]
    unrealized_by_symbol = {str(row.get("s")): fnum(row.get("ur")) for row in state_positions if row.get("s")}
    current_unrealized = sum(unrealized_by_symbol.values())
    active_realized = sum(fnum(row.get("realizedPnL")) for row in active_positions)
    active_fees = sum(fnum(row.get("cumTradingFee")) for row in active_positions)
    recent_position_realized = sum(
        fnum(row.get("realizedPnL"))
        for row in positions
        if int(row.get("updatedAt") or row.get("createdAt") or 0) >= cutoff_ms
    )

    spot_volume_by_symbol: dict[str, float] = defaultdict(float)
    for trade in spot_trades:
        spot_volume_by_symbol[str(trade.get("symbol") or "UNKNOWN")] += fnum(trade.get("price")) * fnum(trade.get("quantity"))

    top_symbols = []
    for symbol, volume in sorted(volume_by_symbol.items(), key=lambda item: item[1], reverse=True)[:15]:
        trades = trade_count_by_symbol[symbol]
        maker_count = maker_count_by_symbol[symbol]
        buys = buy_count_by_symbol[symbol]
        sells = sell_count_by_symbol[symbol]
        top_symbols.append({
            "symbol": symbol,
            "volume": volume,
            "trades": trades,
            "fees": fee_by_symbol[symbol],
            "maker_trade_pct": pct(maker_count, trades),
            "buy_trade_pct": pct(buys, buys + sells),
            "approx_realized_pnl_from_window": realized["by_symbol"].get(symbol, 0.0),
            "current_unrealized_pnl": unrealized_by_symbol.get(symbol, 0.0),
        })

    summary = {
        "address": address,
        "fetch_errors": {
            "state": state_result.error,
            "fee_rate": fee_result.error,
            "positions": positions_result.error,
            "perps_trades": perps_fetch["errors"],
            "spot_trades": spot_fetch["errors"],
        },
        "account": {
            "aid": state.get("aid") or state.get("uid"),
            "account_value": fnum(state.get("av")),
            "available_margin": fnum(state.get("am")),
            "maintenance_margin": fnum(state.get("mm")),
            "margin_ratio_pct": fnum(state.get("mmr")) * 100.0,
            "balances": [{"asset": row.get("a"), "wallet_balance": fnum(row.get("wb"))} for row in state.get("B", []) if isinstance(row, dict)],
            "fee_tier": fee.get("feeTier"),
            "staking_tier": fee.get("stakingTier"),
            "maker_fee_rate_pct": fnum(fee.get("makerFeeRate")) * 100,
            "taker_fee_rate_pct": fnum(fee.get("takerFeeRate")) * 100,
        },
        "perps_7d": {
            "trades": len(perps_trades),
            "first_trade_utc": iso(first_trade),
            "last_trade_utc": iso(last_trade),
            "span_hours_observed": span_hours,
            "total_volume": total_volume,
            "volume_per_day": total_volume / 7.0,
            "total_fees": total_fees,
            "effective_fee_rate_pct": pct(total_fees, total_volume),
            "maker_trades": maker_trades,
            "taker_trades": len(perps_trades) - maker_trades,
            "maker_trade_pct": pct(maker_trades, len(perps_trades)),
            "maker_volume": maker_volume,
            "taker_volume": total_volume - maker_volume,
            "maker_volume_pct": pct(maker_volume, total_volume),
            "unique_symbols": len(volume_by_symbol),
            "trade_size": quantiles(sizes),
            "median_interval_ms": statistics.median(intervals_ms) if intervals_ms else None,
            "trades_per_hour_observed": len(perps_trades) / span_hours if span_hours > 0 else 0,
            "hour_count_utc": dict(sorted(hour_count.items())),
            "day_count_utc": dict(day_count),
        },
        "spot_7d": {
            "trades": len(spot_trades),
            "total_volume": sum(spot_volume_by_symbol.values()),
            "top_symbols": dict(sorted(spot_volume_by_symbol.items(), key=lambda item: item[1], reverse=True)[:10]),
        },
        "positions": {
            "active_count": len(active_positions),
            "history_count_fetched": len(positions),
            "active_margin": sum(fnum(row.get("initialMargin")) for row in active_positions),
            "active_realized_pnl_position_api": active_realized,
            "active_cum_fees_position_api": active_fees,
            "recent_position_realized_pnl_api": recent_position_realized,
            "current_unrealized_pnl_state_api": current_unrealized,
            "top_active": sorted([
                {
                    "symbol": row.get("symbol"),
                    "side": "LONG" if fnum(row.get("size")) > 0 else "SHORT",
                    "size": fnum(row.get("size")),
                    "leverage": row.get("leverage"),
                    "initial_margin": fnum(row.get("initialMargin")),
                    "realized_pnl": fnum(row.get("realizedPnL")),
                    "unrealized_pnl": unrealized_by_symbol.get(str(row.get("symbol")), 0.0),
                    "created_at_utc": iso(dt_from_ms(row.get("createdAt"))),
                    "updated_at_utc": iso(dt_from_ms(row.get("updatedAt"))),
                }
                for row in active_positions
            ], key=lambda row: abs(row["realized_pnl"]) + abs(row["unrealized_pnl"]), reverse=True)[:15],
        },
        "pnl_estimates": {
            "trade_window_gross_realized_pnl_reconstructed": realized["gross_realized_pnl_reconstructed"],
            "trade_window_net_realized_pnl_reconstructed_minus_fees": realized["gross_realized_pnl_reconstructed"] - total_fees,
            "trade_window_open_lot_count": realized["open_lot_count_from_window"],
            "position_api_current_total_pnl_active_realized_plus_unrealized": active_realized + current_unrealized,
            "pnl_quality_note": "Trade reconstruction is approximate because positions may predate the 7d window; position API PnL is current/open-position based, not a clean 7d realized statement.",
        },
        "top_symbols": top_symbols,
    }
    summary["classification"] = classify(summary)
    return summary


def render_markdown(results: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# SoDEX Wallet Forensic Audit — 7D")
    lines.append("")
    lines.append(f"- Generated UTC: `{meta['generated_utc']}`")
    lines.append(f"- Window UTC: `{meta['window_start_utc']}` → `{meta['window_end_utc']}`")
    lines.append(f"- Input addresses: `{meta['input_address_count']}`; unique audited: `{meta['unique_address_count']}`; duplicates skipped: `{len(meta['duplicates'])}`")
    lines.append("- Source: SoDEX public `mainnet-gw.sodex.dev` account, fee, position, perps trades, and spot trades endpoints.")
    lines.append("- Safety: read-only API collection; no signed endpoints, no order placement, no credential use.")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    total_volume = sum(row["perps_7d"]["total_volume"] for row in results)
    total_fees = sum(row["perps_7d"]["total_fees"] for row in results)
    total_trades = sum(row["perps_7d"]["trades"] for row in results)
    total_value = sum(row["account"]["account_value"] for row in results)
    total_unreal = sum(row["positions"]["current_unrealized_pnl_state_api"] for row in results)
    total_active_realized = sum(row["positions"]["active_realized_pnl_position_api"] for row in results)
    lines.append(f"- Aggregate account value: **{money(total_value)}** across {len(results)} unique wallets.")
    lines.append(f"- Aggregate 7D perps activity: **{total_trades:,} trades**, **{money(total_volume)} volume**, **{money(total_fees)} fees**.")
    lines.append(f"- Current open-position PnL snapshot: **{money(total_active_realized)} realized-on-active + {money(total_unreal)} unrealized**.")
    lines.append("- Important caveat: SoDEX public trades prove volume/fees; exact 7D net PnL needs account equity snapshots or full position lifecycle beyond the visible window.")
    lines.append("")
    lines.append("## Wallet Matrix")
    lines.append("")
    lines.append("| # | Address | AID | Value | 7D Trades | 7D Vol | Fees | Maker% | Active Pos | API PnL Snapshot | Class |")
    lines.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for idx, row in enumerate(sorted(results, key=lambda item: item["perps_7d"]["total_volume"], reverse=True), 1):
        p = row["perps_7d"]
        account = row["account"]
        pos = row["positions"]
        api_pnl = pos["active_realized_pnl_position_api"] + pos["current_unrealized_pnl_state_api"]
        lines.append(
            f"| {idx} | `{row['address'][:10]}…{row['address'][-6:]}` | {account['aid'] or ''} | "
            f"{money(account['account_value'])} | {p['trades']:,} | {money(p['total_volume'])} | "
            f"{money(p['total_fees'])} | {p['maker_trade_pct']:.1f}% | {pos['active_count']} | "
            f"{money(api_pnl)} | {row['classification']} |"
        )
    lines.append("")
    lines.append("## Why Volume And PnL Can Both Be High")
    lines.append("")
    lines.append("1. **Profit is mostly not from volume itself.** The public data shows volume and fees directly; positive PnL usually comes from directional exposure, market-making spread capture, or open unrealized gains.")
    lines.append("2. **Several wallets use taker-heavy burst bots.** This creates high volume quickly, but it is only profitable if their signal/arbitrage edge beats taker fees and slippage.")
    lines.append("3. **Maker-dominant wallets have better fee economics.** High maker percentage lowers explicit cost and can generate volume without paying the full taker tax.")
    lines.append("4. **Large account buffers make the PnL look safer.** Many wallets can carry many open positions; smaller Anantara capital cannot copy that drawdown profile.")
    lines.append("5. **Open-position PnL can mask realized churn losses.** A wallet may pay heavy fees and still show positive current PnL because one large open winner dominates the snapshot.")
    lines.append("")
    lines.append("## Per-Wallet Deep Dive")
    lines.append("")
    for row in sorted(results, key=lambda item: item["perps_7d"]["total_volume"], reverse=True):
        p = row["perps_7d"]
        account = row["account"]
        pos = row["positions"]
        pnl = row["pnl_estimates"]
        lines.append(f"### `{row['address']}`")
        lines.append("")
        lines.append(f"- Account: AID `{account['aid']}`, value {money(account['account_value'])}, available margin {money(account['available_margin'])}, fee maker/taker `{account['maker_fee_rate_pct']:.4f}%` / `{account['taker_fee_rate_pct']:.4f}%`, tier `{account['fee_tier']}`, staking `{account['staking_tier']}`.")
        lines.append(f"- 7D perps: {p['trades']:,} trades, {money(p['total_volume'])} volume, {money(p['total_fees'])} fees, effective fee `{p['effective_fee_rate_pct']:.4f}%`, maker `{p['maker_trade_pct']:.1f}%` by trades / `{p['maker_volume_pct']:.1f}%` by volume.")
        lines.append(f"- Timing: `{p['first_trade_utc']}` → `{p['last_trade_utc']}`, median interval `{p['median_interval_ms']}` ms, observed velocity `{p['trades_per_hour_observed']:.1f}` trades/hour.")
        lines.append(f"- Positions: {pos['active_count']} active, active margin {money(pos['active_margin'])}, active realized {money(pos['active_realized_pnl_position_api'])}, current unrealized {money(pos['current_unrealized_pnl_state_api'])}.")
        lines.append(f"- PnL estimates: reconstructed 7D gross realized {money(pnl['trade_window_gross_realized_pnl_reconstructed'])}; after fetched trade fees {money(pnl['trade_window_net_realized_pnl_reconstructed_minus_fees'])}; open-position API snapshot {money(pnl['position_api_current_total_pnl_active_realized_plus_unrealized'])}.")
        lines.append(f"- Classification: `{row['classification']}`.")
        if row["top_symbols"]:
            lines.append("")
            lines.append("| Symbol | Vol | Trades | Maker% | Buy% | Fees | Recon Realized | Curr Unreal |")
            lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
            for sym in row["top_symbols"][:8]:
                lines.append(
                    f"| `{sym['symbol']}` | {money(sym['volume'])} | {sym['trades']:,} | "
                    f"{sym['maker_trade_pct']:.1f}% | {sym['buy_trade_pct']:.1f}% | {money(sym['fees'])} | "
                    f"{money(sym['approx_realized_pnl_from_window'])} | {money(sym['current_unrealized_pnl'])} |"
                )
        if pos["top_active"]:
            lines.append("")
            lines.append("| Active Symbol | Side | Lev | Margin | Realized | Unrealized | Updated UTC |")
            lines.append("|---|---|---:|---:|---:|---:|---|")
            for active in pos["top_active"][:8]:
                lines.append(
                    f"| `{active['symbol']}` | {active['side']} | {active['leverage']} | "
                    f"{money(active['initial_margin'])} | {money(active['realized_pnl'])} | "
                    f"{money(active['unrealized_pnl'])} | `{active['updated_at_utc']}` |"
                )
        lines.append("")
    lines.append("## Lessons For Anantara")
    lines.append("")
    lines.append("- Replicate constraints, not trades: maker ratio, effective fee rate, max open positions, position age, and symbol concentration matter more than raw volume.")
    lines.append("- Do not copy taker-heavy wallets unless Anantara has independent cross-venue/arbitrage evidence; taker fees create a hard negative expectancy hurdle.")
    lines.append("- Favor maker-first probes on symbols with proven fill probability and low adverse selection; stop if volume/loss ratio breaks policy.")
    lines.append("- Treat open unrealized PnL as unstable; require closed-trade/equity-snapshot validation before scaling any farming tactic.")
    lines.append("- Keep SoPoints/SOSO reward proof separate from trading PnL; high volume is only worth paying for if credited points have verified expected value.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only 7D SoDEX wallet forensic audit")
    parser.add_argument("--addresses", required=True, help="comma/newline separated EVM addresses")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--out-dir", default="reports/sodex")
    args = parser.parse_args()

    addresses, duplicates = normalize_addresses(args.addresses)
    if not addresses:
        raise SystemExit("No valid addresses provided")

    now = utc_now()
    cutoff = now - timedelta(days=args.days)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    client = SodexClient()
    results = []
    for idx, address in enumerate(addresses, 1):
        print(f"[{idx}/{len(addresses)}] audit {address}", flush=True)
        results.append(analyze_wallet(client, address, cutoff_ms))
        time.sleep(0.15)

    meta = {
        "generated_utc": iso(now),
        "window_start_utc": iso(cutoff),
        "window_end_utc": iso(now),
        "days": args.days,
        "input_address_count": len(addresses) + len(duplicates),
        "unique_address_count": len(addresses),
        "duplicates": duplicates,
    }
    payload = {"meta": meta, "wallets": results}

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"sodex_wallet_forensic_7d_{stamp}.json"
    md_path = out_dir / f"sodex_wallet_forensic_7d_{stamp}.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(render_markdown(results, meta), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "wallets": len(results)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
