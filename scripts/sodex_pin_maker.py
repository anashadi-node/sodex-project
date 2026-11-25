#!/usr/bin/env python3
"""PIN-Maker: approved real-live paired inventory-neutral maker canary.

Posts equal post-only bid/ask orders on one perp. Both fills complete an
inventory-neutral round trip; a one-sided fill is held only until the quote TTL,
then flattened reduce-only. Exchange position and open-order reads are mandatory.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from decimal import Decimal as D, ROUND_DOWN, ROUND_UP
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def _normalize_systemd_environment() -> None:
    for key, value in list(os.environ.items()):
        if key.startswith(("TE_", "PVE_", "HONEST_", "SODEX_")) and "#" in value:
            os.environ[key] = value.split("#", 1)[0].rstrip()


_normalize_systemd_environment()

from anantara.sodex_twin_engine import (  # noqa: E402
    Config as TwinConfig,
    Ledger,
    Order,
    SodexLiveAdapter,
)


@dataclass(frozen=True)
class PinConfig:
    pair: str = "XPL-USD"
    notional_usd: D = D("20")
    quote_ttl_s: float = 60.0
    close_ttl_s: float = 60.0
    min_net_capture_bps: D = D("4")
    adverse_buffer_bps: D = D("1")
    ratio_floor: D = D("4500")
    loss_cap_usd: D = D("0.25")
    max_round_trips: int = 100
    min_ratio_round_trips: int = 5
    interval_s: float = 2.0
    settle_s: float = 0.5
    tick_size: D = D("0")
    qty_step: D = D("0")
    min_notional_usd: D = D("10")
    price_improve_ticks: int = 0
    research_gate_path: Path | None = None


def research_gate_allows(
    path: Path, pair: str, notional_usd: D, ratio_floor: D
) -> tuple[bool, str]:
    """Require executable-size forward evidence before a research-gated pilot."""
    try:
        report = json.loads(path.read_text())
    except (OSError, ValueError):
        return False, "research_gate_unavailable"
    try:
        report_floor = D(str(report["cost_model"]["ratio_floor"]))
        scenario = report["results"][pair]["queue_scenarios"]["1.0"]
        tested_notional = D(str(scenario["notional_usd"]))
    except (KeyError, TypeError, ValueError):
        return False, "research_gate_missing_pair"
    if report_floor < ratio_floor:
        return False, "research_gate_ratio_floor_too_low"
    if tested_notional < notional_usd:
        return False, "research_gate_notional_too_low"
    if not scenario.get("micro_pilot_gate_pass", False):
        return False, "research_gate_not_passed"
    return True, "research_gate_passed"


class PinMaker:
    def __init__(self, adapter, ledger, config: PinConfig, state_path: Path):
        self.x = adapter
        self.ledger = ledger
        self.cfg = config
        self.state_path = state_path
        self.state = self._load_state()

    def _load_state(self) -> dict:
        try:
            value = json.loads(self.state_path.read_text())
            if isinstance(value, dict):
                return value
        except (OSError, ValueError):
            pass
        return {
            "schema_version": 1,
            "method": "PIN-Maker (Paired Inventory-Neutral Maker)",
            "status": "READY",
            "pair": self.cfg.pair,
            "started_at": time.time(),
            "av_start": None,
            "round_trips": 0,
            "volume_usd": 0.0,
            "gross_pnl_usd": 0.0,
            "fees_usd": 0.0,
            "net_pnl_usd": 0.0,
            "paired": 0,
            "orphans": 0,
            "active": None,
            "halt_reason": None,
        }

    def _save(self) -> None:
        self.state["updated_at"] = time.time()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2) + "\n")
        tmp.replace(self.state_path)

    def _positions(self) -> dict[str, D] | None:
        for attempt in range(3):
            try:
                positions = self.x.perps_positions()
                if getattr(self.x, "_perps_positions_read_ok", True) is not False:
                    return {str(symbol): D(str(qty)) for symbol, qty in positions.items()}
            except Exception as exc:
                logging.warning("PIN position truth attempt %d failed: %s", attempt + 1, exc)
            if attempt < 2:
                time.sleep(min(self.cfg.settle_s, 0.25))
        return None

    def _orders(self) -> list[dict] | None:
        for attempt in range(3):
            try:
                rows, read_ok = self.x._sodex_list_truth(
                    ["orders", "list", "perps", "--format", "json"], timeout=15)
                if read_ok:
                    return rows
            except Exception as exc:
                logging.warning("PIN order truth attempt %d failed: %s", attempt + 1, exc)
            if attempt < 2:
                time.sleep(min(self.cfg.settle_s, 0.25))
        return None

    @staticmethod
    def _oid(row: dict) -> str:
        return str(row.get("orderID") or row.get("orderId") or row.get("id") or "")

    def _pair_order(self, row: dict) -> bool:
        symbol = str(row.get("symbol") or "").upper()
        return symbol == self.cfg.pair.upper() or self.cfg.pair.split("-")[0] in symbol

    def _cancel(self, leg: dict) -> bool:
        order = Order(
            oid=str(leg["oid"]), pair=self.cfg.pair, side=str(leg["side"]),
            price=D(str(leg["price"])), qty=D(str(leg["qty"])),
            cl_ord_id=str(leg.get("cl_ord_id") or ""),
        )
        return self.x.cancel(order) is not False

    def _qty(self, mid: D) -> D:
        raw = self.cfg.notional_usd / mid
        if self.cfg.qty_step > 0:
            minimum = self.cfg.min_notional_usd / mid
            units = (max(raw, minimum) / self.cfg.qty_step).to_integral_value(
                rounding=ROUND_UP
            )
            return units * self.cfg.qty_step
        if mid < 1:
            return raw.quantize(D("1"), rounding=ROUND_DOWN)
        if mid < 10:
            return raw.quantize(D("0.0001"), rounding=ROUND_DOWN)
        return raw.quantize(D("0.01"), rounding=ROUND_DOWN)

    def _risk_gate(self) -> tuple[bool, str]:
        if self.state.get("status") == "HALTED":
            return False, str(self.state.get("halt_reason") or "halted")
        if self.cfg.notional_usd < self.cfg.min_notional_usd:
            return False, "configured_notional_below_market_minimum"
        if (self.cfg.tick_size < 0 or self.cfg.qty_step < 0
                or self.cfg.price_improve_ticks < 0):
            return False, "invalid_market_rules"
        if int(self.state["round_trips"]) >= self.cfg.max_round_trips:
            return False, "canary_complete"
        if D(str(self.state["net_pnl_usd"])) <= -self.cfg.loss_cap_usd:
            return False, "pin_realized_loss_cap"
        if int(self.state["round_trips"]) >= self.cfg.min_ratio_round_trips:
            cumulative_net = D(str(self.state["net_pnl_usd"]))
            if cumulative_net < 0:
                realized_ratio = D(str(self.state["volume_usd"])) / -cumulative_net
                if realized_ratio < self.cfg.ratio_floor:
                    return False, "pin_realized_ratio_floor"
        av_now = self.x.perps_account_value()
        if av_now is None:
            return False, "account_value_unavailable"
        if self.state["av_start"] is None:
            self.state["av_start"] = str(av_now)
            self._save()
        av_loss = max(D(0), D(str(self.state["av_start"])) - D(str(av_now)))
        if av_loss >= self.cfg.loss_cap_usd:
            return False, "pin_account_value_loss_cap"
        maker_fee = D(str(self.x.cfg.perp_maker_fee))
        marginal_ratio = D(1) / maker_fee if maker_fee > 0 else D("Infinity")
        if marginal_ratio < self.cfg.ratio_floor * D("1.05"):
            return False, "marginal_ratio_below_recovery_floor"
        if self.cfg.research_gate_path is not None:
            allowed, reason = research_gate_allows(
                self.cfg.research_gate_path,
                self.cfg.pair,
                self.cfg.notional_usd,
                self.cfg.ratio_floor,
            )
            if not allowed:
                return False, reason
        return True, "approved"

    def preflight(self) -> tuple[bool, str]:
        positions = self._positions()
        orders = self._orders()
        if positions is None or orders is None:
            return False, "exchange_truth_unavailable"
        if positions.get(self.cfg.pair, D(0)) != 0 and not self.state.get("active"):
            return False, "unowned_position_exists"
        if not self.state.get("active"):
            if any(qty != 0 for qty in positions.values()):
                return False, "other_perp_position_open"
            if orders:
                return False, "unowned_perp_order_exists"
        return self._risk_gate()

    def resume_after_flat(self) -> tuple[bool, str]:
        """One-shot operator recovery that preserves all cumulative accounting."""
        positions = self._positions()
        orders = self._orders()
        if positions is None or orders is None:
            return False, "resume_exchange_truth_unavailable"
        if any(qty != 0 for qty in positions.values()):
            return False, "resume_position_exists"
        if orders:
            return False, "resume_order_exists"
        self.state["active"] = None
        self.state["status"] = "READY"
        self.state["halt_reason"] = None
        self._save()
        return True, "resumed_flat"

    def _halt(self, reason: str) -> dict:
        self.state["status"] = "HALTED"
        self.state["halt_reason"] = reason
        self._save()
        logging.error("PIN HALTED: %s", reason)
        return {"action": "halt", "reason": reason}

    def _place_pair(self) -> dict:
        allowed, reason = self.preflight()
        if not allowed:
            return self._halt(reason)
        book = self.x.book(self.cfg.pair)
        mid = book.mid
        improve = self.cfg.tick_size * self.cfg.price_improve_ticks
        quote_bid = book.bid + improve
        quote_ask = book.ask - improve
        if quote_bid >= quote_ask:
            return {"action": "wait", "reason": "inside_quote_crossed"}
        spread_bps = (quote_ask - quote_bid) / mid * D(10000)
        fee_bps = D(str(self.x.cfg.perp_maker_fee)) * D(20000)
        net_capture = spread_bps - fee_bps - self.cfg.adverse_buffer_bps
        if net_capture < self.cfg.min_net_capture_bps:
            return {"action": "wait", "reason": "spread_below_pin_floor",
                    "net_capture_bps": float(net_capture)}
        qty = self._qty(quote_bid)
        if qty <= 0:
            return self._halt("qty_zero")

        buy = self.x.place_limit_gtx_perp(
            self.cfg.pair, "buy", qty, quote_bid, reduce_only=False)
        if not buy or buy.oid == "0":
            return {"action": "wait", "reason": "buy_gtx_rejected"}
        active = {
            "opened_ts": time.time(), "qty": str(qty), "bid": str(quote_bid),
            "ask": str(quote_ask), "entry_bid": str(quote_bid),
            "entry_ask": str(quote_ask), "seen_position": False,
            "buy": {"oid": str(buy.oid), "side": "buy", "price": str(quote_bid),
                    "qty": str(qty), "cl_ord_id": str(buy.cl_ord_id or "")},
            "sell": None,
        }
        self.state["active"] = active
        self.state["status"] = "QUOTING"
        self.state["halt_reason"] = None
        self._save()

        sell = self.x.place_limit_gtx_perp(
            self.cfg.pair, "sell", qty, quote_ask, reduce_only=False)
        if not sell or sell.oid == "0":
            self._cancel(active["buy"])
            positions = self._positions()
            orders = self._orders()
            if positions is None or orders is None:
                return self._halt("second_leg_cleanup_truth_unavailable")
            if positions.get(self.cfg.pair, D(0)) != 0:
                return self._flatten(positions[self.cfg.pair], "second_leg_rejected")
            open_oids = {self._oid(row) for row in orders}
            if str(active["buy"]["oid"]) in open_oids:
                return self._halt("second_leg_cleanup_unconfirmed")
            self.state["active"] = None
            self.state["status"] = "READY"
            self._save()
            return {"action": "wait", "reason": "sell_gtx_rejected"}
        active["sell"] = {
            "oid": str(sell.oid), "side": "sell", "price": str(quote_ask),
            "qty": str(qty), "cl_ord_id": str(sell.cl_ord_id or ""),
        }
        self._save()
        logging.info("PIN QUOTE %s qty=%s bid=%s ask=%s buy=%s sell=%s net=%.2fbps",
                     self.cfg.pair, qty, quote_bid, quote_ask, buy.oid, sell.oid,
                     float(net_capture))
        return {"action": "quote", "pair": self.cfg.pair, "qty": float(qty),
                "bid": float(quote_bid), "ask": float(quote_ask)}

    def _record_cycle(self, kind: str, exit_px: D | None = None) -> dict:
        active = self.state["active"]
        qty = D(active["qty"])
        bid = D(active["bid"])
        ask = D(active["ask"])
        maker_fee = D(str(self.x.cfg.perp_maker_fee))
        if kind == "paired":
            gross = (ask - bid) * qty
            fees = (ask + bid) * qty * maker_fee
            if int(active.get("entry_sign") or 1) > 0:
                entry_px, entry_side = bid, "buy"
                close_px, close_side = ask, "sell"
            else:
                entry_px, entry_side = ask, "sell"
                close_px, close_side = bid, "buy"
            maker_close = True
        else:
            signed = D(str(active.get("orphan_signed") or 0))
            if exit_px is None or signed == 0:
                return self._halt("orphan_accounting_unavailable")
            taker_fee = D(str(self.x.cfg.perp_taker_fee))
            if signed > 0:
                gross = (exit_px - bid) * abs(signed)
                entry_px, entry_side, close_side = bid, "buy", "sell"
            else:
                gross = (ask - exit_px) * abs(signed)
                entry_px, entry_side, close_side = ask, "sell", "buy"
            fees = entry_px * abs(signed) * maker_fee + exit_px * abs(signed) * taker_fee
            qty = abs(signed)
            close_px = exit_px
            maker_close = False
        net = gross - fees
        volume = (entry_px + close_px) * qty
        rt_id = f"PIN-{self.cfg.pair.replace('-', '_')}-{int(time.time() * 1000)}"
        try:
            self.ledger.fill("PVE", "P", self.cfg.pair, entry_side, entry_px, qty,
                             entry_px * qty * maker_fee, True, rt_id)
            close_fee_rate = maker_fee if maker_close else D(str(self.x.cfg.perp_taker_fee))
            self.ledger.fill("PVE", "P", self.cfg.pair, close_side, close_px, qty,
                             close_px * qty * close_fee_rate, maker_close, rt_id)
            self.ledger.rt_close(rt_id, "PVE", self.cfg.pair, volume, gross)
        except Exception as exc:
            return self._halt(f"ledger_write_failed:{exc}")
        self.state["round_trips"] += 1
        self.state["volume_usd"] += float(volume)
        self.state["gross_pnl_usd"] += float(gross)
        self.state["fees_usd"] += float(fees)
        self.state["net_pnl_usd"] += float(net)
        cumulative_net = D(str(self.state["net_pnl_usd"]))
        self.state["realized_ratio"] = (
            float(D(str(self.state["volume_usd"])) / -cumulative_net)
            if cumulative_net < 0 else None)
        self.state["paired" if kind == "paired" else "orphans"] += 1
        self.state["active"] = None
        self.state["status"] = "READY"
        self._save()
        logging.info("PIN %s RT=%d vol=$%.2f gross=$%.5f fee=$%.5f net=$%.5f",
                     kind.upper(), self.state["round_trips"], float(volume),
                     float(gross), float(fees), float(net))
        return {"action": "complete", "kind": kind, "rt_id": rt_id,
                "volume": float(volume), "net_pnl": float(net)}

    def _flatten(self, signed: D, reason: str) -> dict:
        active = self.state.get("active")
        if not active:
            return self._halt("flatten_without_active_state")
        accounting_qty = D(str(active.get("initial_qty") or abs(signed)))
        active["orphan_signed"] = str(accounting_qty if signed > 0 else -accounting_qty)
        for key in ("buy", "sell"):
            leg = active.get(key)
            if leg:
                self._cancel(leg)
        book = self.x.book(self.cfg.pair)
        side = "sell" if signed > 0 else "buy"
        ref_px = book.bid if side == "sell" else book.ask
        order = self.x.place_market_ioc(
            self.cfg.pair, side, abs(signed), ref_px, reduce_only=True)
        if not order or order.oid == "0":
            return self._halt(f"orphan_flatten_rejected:{reason}")
        for _ in range(4):
            time.sleep(self.cfg.settle_s)
            positions = self._positions()
            if positions is not None and positions.get(self.cfg.pair, D(0)) == 0:
                return self._record_cycle("orphan", exit_px=ref_px)
        return self._halt(f"orphan_flatten_unverified:{reason}")

    def _transition_to_maker_close(self, observed_signed: D) -> dict:
        """Freeze a partial first-leg fill, then quote only its reduce-only close."""
        active = self.state["active"]
        observed_qty = abs(observed_signed)
        for key in ("buy", "sell"):
            leg = active.get(key)
            if leg and not self._cancel(leg):
                return self._halt("partial_cancel_unconfirmed")
        time.sleep(self.cfg.settle_s)
        positions = self._positions()
        if positions is None:
            return self._halt("partial_position_truth_unavailable")
        signed = positions.get(self.cfg.pair, D(0))
        if signed == 0:
            active["qty"] = str(observed_qty)
            active["initial_qty"] = str(observed_qty)
            return self._record_cycle("paired")

        book = self.x.book(self.cfg.pair)
        qty = abs(signed)
        entry_bid = D(str(active.get("entry_bid") or active["bid"]))
        entry_ask = D(str(active.get("entry_ask") or active["ask"]))
        if signed > 0:
            side = "sell"
            # Moving to entry price still has zero gross loss; maker fees alone
            # imply ~1:9259, safely above the 1:6300 recovery floor.
            price = max(entry_bid, book.ask)
            active["bid"] = str(entry_bid)
            active["ask"] = str(price)
        else:
            side = "buy"
            price = min(entry_ask, book.bid)
            active["bid"] = str(price)
            active["ask"] = str(entry_ask)
        close_order = self.x.place_limit_gtx_perp(
            self.cfg.pair, side, qty, price, reduce_only=True)
        if not close_order or close_order.oid == "0":
            return self._flatten(signed, "partial_maker_close_rejected")
        active["qty"] = str(qty)
        active["initial_qty"] = str(qty)
        active["entry_sign"] = 1 if signed > 0 else -1
        active["closing"] = True
        active.setdefault("close_opened_ts", time.time())
        active["buy"] = None
        active["sell"] = None
        active[side] = {
            "oid": str(close_order.oid), "side": side, "price": str(price),
            "qty": str(qty), "cl_ord_id": str(close_order.cl_ord_id or ""),
        }
        self._save()
        logging.info("PIN PARTIAL %s qty=%s -> reduce-only maker %s@%s oid=%s",
                     "LONG" if signed > 0 else "SHORT", qty, side, price,
                     close_order.oid)
        return {"action": "maker_close", "side": side, "qty": float(qty),
                "price": float(price), "reduce_only": True}

    def _manage_active(self) -> dict:
        active = self.state["active"]
        positions = self._positions()
        orders = self._orders()
        if positions is None or orders is None:
            for key in ("buy", "sell"):
                if active.get(key):
                    self._cancel(active[key])
            return self._halt("active_exchange_truth_unavailable")
        signed = positions.get(self.cfg.pair, D(0))
        qty = D(active["qty"])
        if signed != 0:
            active["seen_position"] = True
            self._save()
            if not active.get("closing"):
                return self._transition_to_maker_close(signed)
            expected_sign = int(active.get("entry_sign") or 0)
            if ((signed > 0) != (expected_sign > 0)
                    or abs(signed) > D(str(active.get("initial_qty") or qty)) * D("1.05")):
                return self._flatten(signed, "maker_close_position_anomaly")
        own_oids = {str(active[key]["oid"]) for key in ("buy", "sell") if active.get(key)}
        open_oids = {self._oid(row) for row in orders}
        remaining = own_oids & open_oids
        if signed == 0 and active.get("closing"):
            for key in ("buy", "sell"):
                leg = active.get(key)
                if leg and str(leg["oid"]) in remaining:
                    if not self._cancel(leg):
                        return self._halt("filled_close_cancel_unconfirmed")
            return self._record_cycle("paired")
        if signed == 0 and not remaining:
            if active.get("seen_position"):
                return self._record_cycle("paired")
            # Both orders can disappear because of an external cancel or reject.
            # Without observing a nonzero exchange position, no real volume is minted.
            self.state["active"] = None
            self.state["status"] = "READY"
            self._save()
            return {"action": "discard", "reason": "paired_fill_unverified"}
        phase_opened_ts = (
            float(active.get("close_opened_ts") or active["opened_ts"])
            if active.get("closing") else float(active["opened_ts"])
        )
        phase_ttl_s = self.cfg.close_ttl_s if active.get("closing") else self.cfg.quote_ttl_s
        expired = time.time() - phase_opened_ts >= phase_ttl_s
        if active.get("closing") and signed != 0 and not remaining and not expired:
            return self._transition_to_maker_close(signed)
        if expired:
            for key in ("buy", "sell"):
                leg = active.get(key)
                if leg and str(leg["oid"]) in remaining:
                    if not self._cancel(leg):
                        return self._halt("ttl_cancel_unconfirmed")
            time.sleep(self.cfg.settle_s)
            positions = self._positions()
            if positions is None:
                return self._halt("ttl_position_truth_unavailable")
            signed = positions.get(self.cfg.pair, D(0))
            if signed != 0:
                return self._flatten(signed, "ttl_orphan")
            self.state["active"] = None
            self.state["status"] = "READY"
            self._save()
            return {"action": "expire", "reason": "no_fill"}
        return {"action": "monitor", "position": float(signed),
                "remaining_orders": len(remaining)}

    def tick(self) -> dict:
        if self.state.get("active"):
            return self._manage_active()
        allowed, reason = self._risk_gate()
        if not allowed:
            return self._halt(reason)
        return self._place_pair()

    def shutdown_cleanup(self) -> None:
        active = self.state.get("active")
        if not active:
            return
        was_halted = self.state.get("status") == "HALTED"
        halt_reason = self.state.get("halt_reason")
        for key in ("buy", "sell"):
            if active.get(key):
                self._cancel(active[key])
        positions = self._positions()
        if positions is not None:
            signed = positions.get(self.cfg.pair, D(0))
            if signed != 0:
                self._flatten(signed, "shutdown")
            else:
                self.state["active"] = None
                if was_halted:
                    self.state["status"] = "HALTED"
                    self.state["halt_reason"] = halt_reason
                else:
                    self.state["status"] = "READY"
                    self.state["halt_reason"] = None
                self._save()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-live", action="store_true")
    parser.add_argument("--resume-flat", action="store_true",
                        help="clear a halt only after exchange proves no positions/orders")
    parser.add_argument("--pair", default=os.environ.get("PIN_PAIR", "XPL-USD"))
    parser.add_argument("--notional", default=os.environ.get("PIN_NOTIONAL_USD", "20"))
    parser.add_argument("--ttl", type=float, default=float(os.environ.get("PIN_TTL_S", "60")))
    parser.add_argument("--close-ttl", type=float,
                        default=float(os.environ.get("PIN_CLOSE_TTL_S", "60")))
    parser.add_argument("--loss-cap", default=os.environ.get("PIN_LOSS_CAP_USD", "0.25"))
    parser.add_argument("--max-rt", type=int, default=int(os.environ.get("PIN_MAX_RT", "100")))
    parser.add_argument("--min-ratio-rt", type=int,
                        default=int(os.environ.get("PIN_MIN_RATIO_RT", "5")))
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--tick-size", default=os.environ.get("PIN_TICK_SIZE", "0"))
    parser.add_argument("--qty-step", default=os.environ.get("PIN_QTY_STEP", "0"))
    parser.add_argument("--min-notional", default=os.environ.get("PIN_MIN_NOTIONAL", "10"))
    parser.add_argument("--inside-ticks", type=int,
                        default=int(os.environ.get("PIN_INSIDE_TICKS", "0")))
    parser.add_argument(
        "--min-net-capture-bps",
        default=os.environ.get("PIN_MIN_NET_CAPTURE_BPS", "4"),
        help="minimum spread capture after maker fees and adverse buffer",
    )
    parser.add_argument("--research-gate", type=Path, default=None)
    parser.add_argument("--state", type=Path,
                        default=PROJECT / "data" / "sodex_pin_maker_state.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.approved_live or os.environ.get("CONFIRM_LIVE") != "YES":
        raise SystemExit("PIN-Maker live requires --approved-live and CONFIRM_LIVE=YES")
    lock_path = PROJECT / "data" / "sodex_pin_maker.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = lock_path.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("PIN-Maker already running")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    twin_cfg = TwinConfig()
    adapter = SodexLiveAdapter(twin_cfg)
    ledger = Ledger(str(PROJECT / os.environ.get("TE_DB", "twin_engine.db")))
    cfg = PinConfig(
        pair=args.pair, notional_usd=D(str(args.notional)), quote_ttl_s=args.ttl,
        close_ttl_s=args.close_ttl,
        ratio_floor=D(os.environ.get("HONEST_RATIO_FLOOR", "4500").split("#", 1)[0].strip()),
        loss_cap_usd=D(str(args.loss_cap)), max_round_trips=args.max_rt,
        min_ratio_round_trips=args.min_ratio_rt,
        interval_s=args.interval,
        tick_size=D(str(args.tick_size)), qty_step=D(str(args.qty_step)),
        min_notional_usd=D(str(args.min_notional)),
        price_improve_ticks=args.inside_ticks,
        min_net_capture_bps=D(str(args.min_net_capture_bps)),
        research_gate_path=args.research_gate,
    )
    engine = PinMaker(adapter, ledger, cfg, args.state)
    if args.resume_flat:
        ok, reason = engine.resume_after_flat()
        print(json.dumps({"ok": ok, "reason": reason}), flush=True)
        return 0 if ok else 1
    running = True

    def stop(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        ok, reason = engine.preflight()
        if not ok:
            engine._halt(reason)
            return 0
        while running and engine.state.get("status") != "HALTED":
            result = engine.tick()
            print(json.dumps(result), flush=True)
            time.sleep(cfg.interval_s)
    finally:
        engine.shutdown_cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
