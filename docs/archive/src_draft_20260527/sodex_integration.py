#!/usr/bin/env python3
"""
ANANTARA SAKTI — SoDEX Integration (ValueChain DEX)

Wrapper untuk interaksi dengan SoDEX DEX:
- Public REST API untuk market data (unsigned)
- Signed trading actions via bin/sodex CLI (EIP-712)
- Account state dan position tracking

Mengikuti best practices dari skills/sodex-api-patterns.md.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from typing import Any, Optional

import httpx

from src.config import sodex_cfg, SODEX_UNIVERSE, PROJECT_DIR
from src.utils.constants import SoDEXAPIException

log = logging.getLogger("anantara.sodex")


# ── Public REST API ──────────────────────────────────────────────────


async def _api_get(endpoint: str, params: dict | None = None) -> dict:
    """Unsigned GET request ke SoDEX public API."""
    url = f"{sodex_cfg.perps_url}{endpoint}"
    try:
        async with httpx.AsyncClient(
            timeout=15,
            headers={"Accept": "application/json"},
        ) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        log.error(f"SoDEX API error {e.response.status_code}: {e.response.text[:200]}")
        return {"error": str(e.response.status_code)}
    except Exception as e:
        log.error(f"SoDEX API request failed: {e}")
        return {"error": str(e)[:200]}


async def get_markets() -> dict:
    """List all available perps markets with metadata."""
    return await _api_get("/markets/symbols")


async def get_tickers() -> dict:
    """All market tickers (24h price stats)."""
    return await _api_get("/markets/tickers")


async def get_ticker(symbol: str) -> dict:
    """Single market 24h ticker.

    Returns: {"last": float, "bid": float, "ask": float, "change_pct": float, ...}
    """
    data = await _api_get("/markets/tickers")
    tickers = data.get("data", []) or []
    for t in tickers:
        if t.get("symbol") == symbol:
            return {
                "symbol": symbol,
                "last": float(t.get("lastPx", 0) or 0),
                "bid": float(t.get("bid", t.get("lastPx", 0)) or 0),
                "ask": float(t.get("ask", t.get("lastPx", 0)) or 0),
                "high": float(t.get("highPx", 0) or 0),
                "low": float(t.get("lowPx", 0) or 0),
                "change_pct": float(t.get("changePct", 0) or 0),
                "volume_24h": float(t.get("quoteVolume", 0) or 0),
            }
    return {}


async def get_klines(symbol: str, interval: str = "1h", limit: int = 72) -> list[dict]:
    """OHLCV klines for a symbol.

    Returns list of {"t": timestamp, "o": open, "h": high, "l": low, "c": close, "v": volume}.
    All values are STRING from API — converted to float here.
    """
    data = await _api_get(
        f"/markets/{symbol}/klines",
        params={"interval": interval, "limit": limit},
    )
    raw = data.get("data", []) or []
    return [
        {
            "t": int(k["t"]),
            "o": float(k["o"]),
            "h": float(k["h"]),
            "l": float(k["l"]),
            "c": float(k["c"]),
            "v": float(k["v"]),
        }
        for k in raw
    ]


async def get_orderbook(symbol: str) -> dict:
    """L1 order book (best bid/ask)."""
    return await _api_get(f"/markets/{symbol}/orderbook")


# ── Account State (Unsigned, via address) ────────────────────────────


async def get_account_state() -> dict:
    """Account state: equity, margin, PnL."""
    if not sodex_cfg.address:
        return {"error": "SoDEX address not configured"}
    return await _api_get(f"/accounts/{sodex_cfg.address}/state")


async def get_balances() -> dict:
    """Per-asset balances."""
    return await _api_get(f"/accounts/{sodex_cfg.address}/balances")


async def get_positions() -> dict:
    """Open positions with unrealized PnL."""
    return await _api_get(f"/accounts/{sodex_cfg.address}/positions")


async def get_open_orders() -> dict:
    """Open/pending orders."""
    return await _api_get(f"/accounts/{sodex_cfg.address}/orders")


async def get_trade_history() -> dict:
    """Trade history."""
    return await _api_get(f"/accounts/{sodex_cfg.address}/trades")


async def get_fee_rate() -> dict:
    """Current maker/taker fee rates."""
    return await _api_get(f"/accounts/{sodex_cfg.address}/fee-rate")


# ── Signed Actions (via CLI subprocess) ──────────────────────────────


def _cli_run(args: list[str], auth: bool = False, timeout: int = 30) -> Optional[dict]:
    """Run bin/sodex CLI command with EIP-712 signing.

    Args:
        args: CLI arguments (without bin/sodex prefix)
        auth: If True, include --private-key and --rpc-url
        timeout: Command timeout in seconds

    Returns:
        Parsed JSON output, or None on failure.
    """
    cmd = [sodex_cfg.cli_path]
    if auth and sodex_cfg.private_key:
        cmd.extend(["--private-key", sodex_cfg.private_key])
    if sodex_cfg.rpc_url:
        cmd.extend(["--rpc-url", sodex_cfg.rpc_url])
    cmd.extend(args)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            log.warning(f"SoDEX CLI error [{result.returncode}]: {result.stderr[:200]}")
            return None
        # Try JSON parse, fallback to text
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"text": result.stdout.strip()}
    except subprocess.TimeoutExpired:
        log.error(f"SoDEX CLI timeout: {' '.join(args[:4])}")
        return None
    except FileNotFoundError:
        log.error(f"SoDEX CLI not found at {sodex_cfg.cli_path}")
        return None
    except Exception as e:
        log.error(f"SoDEX CLI error: {e}")
        return None


def place_order(
    symbol: str,
    side: str,
    order_type: str,
    price: str,
    qty: str,
    tif: str = "gtx",
) -> Optional[dict]:
    """Place a perps order via CLI.

    Args:
        symbol: "BTC-USD"
        side: "buy" or "sell"
        order_type: "limit" or "market"
        price: String price
        qty: String quantity
        tif: "gtc", "ioc", or "gtx" (post-only)

    Returns:
        Order result dict or None on failure.
    """
    return _cli_run([
        "orders", "place", "perps",
        "--symbol", symbol,
        "--side", side,
        "--type", order_type,
        "--price", price,
        "--qty", qty,
        "--tif", tif,
    ], auth=True)


def cancel_order(symbol: str, order_id: str) -> Optional[dict]:
    """Cancel an open order."""
    return _cli_run([
        "orders", "cancel", str(order_id),
        "--symbol", symbol,
    ], auth=True)


def set_leverage(symbol: str, leverage: int) -> bool:
    """Set leverage for a symbol. Returns True on success."""
    result = _cli_run([
        "leverage", "set", symbol, str(leverage),
    ], auth=True)
    if result and isinstance(result, dict):
        text = result.get("text", "")
        return "leverage set to" in text.lower()
    return False


def get_balance_perps() -> Optional[list[dict]]:
    """Get perps balance via CLI."""
    return _cli_run(["balance", "perps", sodex_cfg.address])


def get_open_positions_list() -> list[dict]:
    """Get open positions via CLI. Returns list of position dicts."""
    result = _cli_run(["positions", "perps", sodex_cfg.address])
    if result and isinstance(result, list):
        return result
    return []


def close_position(symbol: str, quantity: str) -> Optional[dict]:
    """Market-close a position (reduce-only).

    Uses the opposite side to close.
    """
    # Determine side by checking current position
    positions = get_open_positions_list()
    pos = next((p for p in positions if p.get("symbol") == symbol), None)
    if not pos:
        return None
    # If positionAmt positive = LONG, sell to close
    amt = float(pos.get("positionAmt", 0) or 0)
    side = "sell" if amt > 0 else "buy"
    return _cli_run([
        "orders", "place", "perps",
        "--symbol", symbol,
        "--side", side,
        "--type", "market",
        "--qty", quantity,
        "--tif", "ioc",
        "--reduce-only",
    ], auth=True)


# ── Convenience ──────────────────────────────────────────────────────


async def get_equity() -> float:
    """Get account equity in USD."""
    state = await get_account_state()
    if "error" in state:
        return 0.0
    data = state.get("data", {}) or {}
    return float(data.get("av", 0) or 0)


async def health_check() -> bool:
    """Quick connectivity check."""
    try:
        data = await _api_get("/markets/tickers")
        return "data" in data
    except Exception:
        return False


def validate_signing() -> dict:
    """Test EIP-712 signing with an unfillable order (zero risk)."""
    result = place_order(
        symbol="BTC-USD",
        side="buy",
        order_type="limit",
        price="1.00",  # impossible price — will never fill
        qty="0.001",
        tif="gtx",
    )
    if result:
        order_id = result.get("orderId") or result.get("id")
        if order_id:
            cancel_order("BTC-USD", str(order_id))
            return {"ok": True, "message": "Signing validated — order created and cancelled"}
    return {"ok": False, "message": "Signing validation failed"}