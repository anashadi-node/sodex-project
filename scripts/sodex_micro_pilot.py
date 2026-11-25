#!/usr/bin/env python3
"""Tiny SoDEX bear-market micro pilot.

The pilot is intentionally small: find a liquid negative-momentum perp,
optionally open a tiny SHORT, wait briefly, and close reduce-only.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP, InvalidOperation
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))
from scripts.sodex_ta_probability_gate import evaluate_symbol_gate

LOG_PATH = PROJECT / "data" / "sodex_micro_pilot.jsonl"
ENV_PATH = PROJECT / ".env"
SAFETY_HALT = PROJECT / "data" / "SAFETY_HALT"
PNL_HALT = PROJECT / "data" / "PNL_HALT"
DEFAULT_NOTIONAL_USD = Decimal("12")
WIB = timezone(timedelta(hours=7))
EMERGENCY_RATIO_UNTIL_WIB = datetime(2026, 7, 18, 9, 30, tzinfo=WIB)
_DEFAULT_MIN_REAL_VOLUME_LOSS_RATIO = "5100" if datetime.now(WIB) <= EMERGENCY_RATIO_UNTIL_WIB else "7000"
MIN_REAL_VOLUME_LOSS_RATIO = Decimal(os.environ.get("SODEX_MIN_REAL_VOLUME_LOSS_RATIO", _DEFAULT_MIN_REAL_VOLUME_LOSS_RATIO))
MAX_SPREAD_PCT = Decimal("0.0012")
MIN_QUOTE_VOLUME_USD = Decimal("75000")
MIN_NEGATIVE_CHANGE_PCT = Decimal("-1.0")
MAX_LIVE_CYCLES = 12
MAX_PRE_ENTRY_REBOUND_PCT = Decimal("0.0005")
MIN_TA_PROBABILITY = Decimal("0.80")
EVENT_END_WIB = datetime(2026, 7, 25, tzinfo=WIB)


def dec(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def extract_data(payload: Any) -> Any:
    if isinstance(payload, dict):
        for key in ("data", "result"):
            if key in payload:
                return payload[key]
    return payload


def as_list(payload: Any, key: str) -> list[dict[str, Any]]:
    data = extract_data(payload)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict) and isinstance(data.get(key), list):
        return [x for x in data[key] if isinstance(x, dict)]
    return []


def load_env(path: Path = ENV_PATH) -> dict[str, str]:
    env = os.environ.copy()
    if not path.exists():
        return env
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


def halt_active() -> bool:
    return SAFETY_HALT.exists() or PNL_HALT.exists()


def run_json(args: list[str], *, auth: bool = False, timeout: int = 45) -> Any:
    proc = subprocess.run(
        args,
        cwd=PROJECT,
        env=load_env() if auth else os.environ.copy(),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"command_failed:{args[:4]}:rc={proc.returncode}:{proc.stderr[-500:]}")
    text = proc.stdout.strip()
    return json.loads(text) if text else None


def monitor_report() -> dict[str, Any]:
    return run_json([sys.executable, "scripts/sodex_monitor_eval.py", "--json"], auth=True, timeout=90)


def target_policy(report: dict[str, Any]) -> dict[str, Any]:
    from scripts.sodex_target_policy import evaluate_target_policy

    return evaluate_target_policy(report)


def open_positions(report: dict[str, Any]) -> list[dict[str, Any]]:
    return (((report.get("account") or {}).get("assets") or {}).get("perps_positions") or [])


def venue_state_readable() -> bool:
    """True HANYA bila state posisi venue benar-benar TERBACA.

    MENGAPA perlu: `open_positions()` memakai rantai `or []`, sehingga report yang
    gagal atau parsial menghasilkan daftar KOSONG — "venue tak terbaca" menjadi
    identik dengan "venue kosong". Akibatnya order baru bisa ditumpuk di atas
    posisi yang sebenarnya ada (kelas cacat fill-phantom rc=0/orderID=0, dan
    maker-ladder 3,39x yang membuat UNI -$19,06).

    Guard pra-order WAJIB membedakan "benar-benar tidak ada posisi" dari "tidak
    bisa dibaca". Bila ragu, TOLAK menambah risiko — bukan izinkan atas dasar
    state kosong palsu.
    """
    try:
        rep = monitor_report()
    except Exception:                              # noqa: BLE001 - fail-closed
        return False
    if not isinstance(rep, dict):
        return False
    acct = rep.get("account")
    if not isinstance(acct, dict):
        return False
    assets = acct.get("assets")
    if not isinstance(assets, dict):
        return False
    return isinstance(assets.get("perps_positions"), list)


def equity_usd(report: dict[str, Any]) -> Decimal:
    return dec((((report.get("account") or {}).get("account_value") or {}).get("total_equity_usd")))


def perps_account_value_usd(report: dict[str, Any]) -> Decimal:
    return dec((((report.get("account") or {}).get("account_value") or {}).get("perps_account_value_usd")))


def days_to_event_end(now: datetime | None = None) -> Decimal:
    current = now or datetime.now(WIB)
    if current.tzinfo is None:
        current = current.replace(tzinfo=WIB)
    seconds = max(0.0, (EVENT_END_WIB - current.astimezone(WIB)).total_seconds())
    return Decimal(str(seconds)) / Decimal("86400")


def micro_lane(policy: dict[str, Any]) -> dict[str, Any] | None:
    for lane in policy.get("opportunity_lanes") or []:
        if lane.get("lane") == "SAFETY_HALT_SHORT_PILOT":
            return lane
    for lane in policy.get("opportunity_lanes") or []:
        if lane.get("lane") == "RATIO_RECOVERY_MAKER_ONLY":
            return lane
    for lane in policy.get("opportunity_lanes") or []:
        if lane.get("lane") == "DEADLINE_MICRO_CATCHUP":
            return lane
    for lane in policy.get("opportunity_lanes") or []:
        if lane.get("lane") == "MICRO_PRE_LOSER_SHORT_ONLY":
            return lane
    return None


def iter_micro_logs(path: Path = LOG_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text().splitlines():
            if line.strip():
                payload = json.loads(line)
                if isinstance(payload, dict):
                    rows.append(payload)
    except Exception:
        return rows
    return rows


def micro_daily_net_usd(now: datetime | None = None, path: Path = LOG_PATH) -> Decimal:
    current = now or datetime.now(timezone.utc)
    day = current.astimezone(WIB).date()
    total = Decimal("0")
    for row in iter_micro_logs(path):
        if row.get("mode") != "live":
            continue
        try:
            ts = datetime.fromisoformat(str(row.get("ts_utc"))).astimezone(WIB)
        except Exception:
            continue
        if ts.date() == day:
            delta = row.get("perps_account_delta_usd")
            if delta is None and "account_delta_usd" not in row:
                continue
            total += dec(delta if delta is not None else row.get("account_delta_usd"))
    return total


def micro_daily_loss_used_usd(now: datetime | None = None, path: Path = LOG_PATH) -> Decimal:
    net = micro_daily_net_usd(now, path)
    return abs(net) if net < 0 else Decimal("0")


def micro_daily_volume_usd(now: datetime | None = None, path: Path = LOG_PATH) -> Decimal:
    current = now or datetime.now(timezone.utc)
    day = current.astimezone(WIB).date()
    total = Decimal("0")
    for row in iter_micro_logs(path):
        if row.get("mode") != "live":
            continue
        try:
            ts = datetime.fromisoformat(str(row.get("ts_utc"))).astimezone(WIB)
        except Exception:
            continue
        if ts.date() != day:
            continue
        if not row.get("closed") and dec(row.get("opened_size")) == 0:
            continue
        total += dec(row.get("projected_roundtrip_volume_usd"))
    return total


def projected_roundtrip_volume_usd(notional: Decimal) -> Decimal:
    return max(Decimal("0"), notional * Decimal("2"))


def max_loss_for_ratio(notional: Decimal, ratio: Decimal = MIN_REAL_VOLUME_LOSS_RATIO) -> Decimal:
    volume = projected_roundtrip_volume_usd(notional)
    if volume <= 0 or ratio <= 0:
        return Decimal("0")
    return volume / ratio


def cumulative_ratio_loss_remaining_usd(
    requested_notional: Decimal,
    *,
    daily_loss_used_usd: Decimal,
    daily_volume_usd: Decimal,
    ratio: Decimal = MIN_REAL_VOLUME_LOSS_RATIO,
) -> Decimal:
    if ratio <= 0:
        return Decimal("0")
    allowed = (daily_volume_usd + projected_roundtrip_volume_usd(requested_notional)) / ratio
    return allowed - daily_loss_used_usd


def policy_allows_micro(
    policy: dict[str, Any],
    report: dict[str, Any],
    requested_notional: Decimal,
    *,
    halt_exists: bool = False,
    override_halt: bool = False,
    daily_loss_used_usd: Decimal = Decimal("0"),
    daily_volume_usd: Decimal = Decimal("0"),
    allow_ratio_recovery: bool = False,
) -> tuple[bool, str, dict[str, Any] | None]:
    lane = micro_lane(policy)
    if not lane:
        return False, "micro_lane_missing", None
    if open_positions(report):
        return False, "open_perps_present", lane
    if not bool((policy.get("signal") or {}).get("fresh")):
        return False, "signal_not_fresh", lane
    max_notional = dec(lane.get("max_notional_usd"))
    if requested_notional <= 0 or requested_notional > max_notional:
        return False, "notional_above_lane_cap", lane
    max_daily_loss = dec(lane.get("max_daily_loss_usd"))
    if max_daily_loss > 0 and daily_loss_used_usd >= max_daily_loss and not allow_ratio_recovery:
        return False, "micro_daily_loss_cap_reached", lane
    ratio_budget = dec(lane.get("max_loss_for_min_ratio_usd")) or max_loss_for_ratio(requested_notional)
    if ratio_budget > 0 and daily_loss_used_usd >= ratio_budget:
        remaining = cumulative_ratio_loss_remaining_usd(
            requested_notional,
            daily_loss_used_usd=daily_loss_used_usd,
            daily_volume_usd=daily_volume_usd,
        )
        if not allow_ratio_recovery and remaining <= 0:
            return False, "farming_ratio_loss_budget_reached", lane
    if halt_exists and not override_halt:
        return False, "safety_halt_active", lane
    return True, "ok", lane


def current_barbell_gate(report: dict[str, Any]) -> dict[str, Any]:
    try:
        from scripts.sodex_event_barbell import evaluate_barbell, read_jsonl, MICRO_LOG

        return evaluate_barbell(report, read_jsonl(MICRO_LOG))
    except Exception:
        return {}


def barbell_allows_micro_live(barbell: dict[str, Any], *, override: bool = False) -> bool:
    if override:
        return True
    return str(barbell.get("phase") or "") not in {
        "MICRO_EDGE_NEGATIVE_COOLDOWN",
        "STOP_LIVE_RESEARCH_ONLY",
    }


@dataclass(frozen=True)
class Candidate:
    symbol: str
    bid: Decimal
    ask: Decimal
    mid: Decimal
    spread_pct: Decimal
    change_pct: Decimal
    quote_volume: Decimal
    funding_rate: Decimal
    score: Decimal


def _book_price(book: dict[str, Any], side: str) -> Decimal:
    levels = book.get(side) or []
    if not isinstance(levels, list) or not levels:
        return Decimal("0")
    first = levels[0]
    if isinstance(first, dict):
        return dec(first.get("price") or first.get("px"))
    if isinstance(first, list) and first:
        return dec(first[0])
    return Decimal("0")


def score_candidate(
    ticker: dict[str, Any],
    book: dict[str, Any],
    *,
    ratio_recovery: bool = False,
) -> Candidate | None:
    symbol = str(ticker.get("symbol") or "")
    bid = _book_price(book, "bids") or dec(ticker.get("bidPx"))
    ask = _book_price(book, "asks") or dec(ticker.get("askPx"))
    if not symbol or bid <= 0 or ask <= 0 or ask <= bid:
        return None
    mid = (bid + ask) / Decimal("2")
    spread_pct = (ask - bid) / mid
    change_pct = dec(ticker.get("changePct") or ticker.get("priceChangePercent"))
    quote_volume = dec(ticker.get("quoteVolume") or ticker.get("volumeUsd") or ticker.get("volume"))
    funding_rate = dec(ticker.get("fundingRate"))
    if spread_pct > MAX_SPREAD_PCT:
        return None
    if quote_volume < MIN_QUOTE_VOLUME_USD:
        return None
    if not ratio_recovery and change_pct > MIN_NEGATIVE_CHANGE_PCT:
        return None
    volume_score = min(quote_volume / Decimal("1000000"), Decimal("5"))
    spread_score = max(Decimal("0"), Decimal("2") - (spread_pct * Decimal("1000")))
    # For SHORT-only probes, positive funding is helpful because shorts receive
    # funding; negative funding means shorts pay funding and should be penalized.
    funding_bonus = Decimal("0.35") if funding_rate > 0 else Decimal("-0.35") if funding_rate < 0 else Decimal("0")
    if ratio_recovery:
        direction_score = min(abs(change_pct), Decimal("2"))
        score = volume_score + spread_score + funding_bonus + direction_score
    else:
        score = abs(change_pct) + volume_score + spread_score + funding_bonus
    return Candidate(symbol, bid, ask, mid, spread_pct, change_pct, quote_volume, funding_rate, score)


def tickers() -> list[dict[str, Any]]:
    payload = run_json(["bin/sodex", "tickers", "perps", "--format", "json"], timeout=45)
    return as_list(payload, "tickers")


def markets() -> list[dict[str, Any]]:
    payload = run_json(["bin/sodex", "markets", "perps", "--format", "json"], timeout=45)
    return as_list(payload, "markets")


def symbol_id(symbol: str) -> int:
    for market in markets():
        if str(market.get("name") or market.get("displayName") or "") == symbol:
            return int(dec(market.get("id")))
    return 0


def orderbook(symbol: str) -> dict[str, Any]:
    payload = run_json(["bin/sodex", "orderbook", "perps", symbol, "--depth", "3", "--format", "json"], timeout=45)
    data = extract_data(payload)
    return data if isinstance(data, dict) else {}


def _prefilter_tickers(
    ticker_rows: list[dict[str, Any]],
    forced_symbol: str | None,
    *,
    ratio_recovery: bool = False,
) -> list[dict[str, Any]]:
    if forced_symbol:
        return [row for row in ticker_rows if str(row.get("symbol") or "") == forced_symbol]
    if ratio_recovery:
        prelim = [
            row for row in ticker_rows
            if dec(row.get("quoteVolume") or row.get("volumeUsd") or row.get("volume")) >= MIN_QUOTE_VOLUME_USD
        ]
        return sorted(
            prelim,
            key=lambda row: (
                dec(row.get("quoteVolume") or row.get("volumeUsd") or row.get("volume")),
                -abs(dec(row.get("changePct") or row.get("priceChangePercent"))),
            ),
            reverse=True,
        )[:12]
    prelim = [
        row for row in ticker_rows
        if dec(row.get("changePct") or row.get("priceChangePercent")) <= MIN_NEGATIVE_CHANGE_PCT
        and dec(row.get("quoteVolume") or row.get("volumeUsd") or row.get("volume")) >= MIN_QUOTE_VOLUME_USD
    ]
    return sorted(
        prelim,
        key=lambda row: (
            abs(dec(row.get("changePct") or row.get("priceChangePercent"))),
            dec(row.get("quoteVolume") or row.get("volumeUsd") or row.get("volume")),
        ),
        reverse=True,
    )[:12]


def select_candidate(
    ticker_rows: list[dict[str, Any]],
    *,
    forced_symbol: str | None = None,
    ratio_recovery: bool = False,
) -> Candidate | None:
    candidates: list[Candidate] = []
    for ticker in _prefilter_tickers(ticker_rows, forced_symbol, ratio_recovery=ratio_recovery):
        symbol = str(ticker.get("symbol") or "")
        try:
            book = orderbook(symbol)
            candidate = score_candidate(ticker, book, ratio_recovery=ratio_recovery)
        except Exception:
            candidate = None
        if candidate:
            candidates.append(candidate)
    return max(candidates, key=lambda c: c.score, default=None)


def market_specs(symbol: str) -> dict[str, Decimal]:
    try:
        markets = as_list(run_json(["bin/sodex", "markets", "perps", "--format", "json"]), "markets")
    except Exception:
        return {}
    for market in markets:
        if str(market.get("name") or market.get("displayName") or "") != symbol:
            continue
        return {
            "step_size": dec(market.get("stepSize"), Decimal("0")),
            "min_quantity": dec(market.get("minQuantity"), Decimal("0")),
            "min_notional": dec(market.get("minNotional"), Decimal("0")),
        }
    return {}


def qty_for_notional(notional: Decimal, price: Decimal, symbol: str | None = None) -> str:
    if notional <= 0 or price <= 0:
        raise ValueError("invalid_notional_or_price")
    qty = notional / price
    specs = market_specs(symbol) if symbol else {}
    step = specs.get("step_size") or (Decimal("1") if qty >= 1 else Decimal("0.000001"))
    min_qty = specs.get("min_quantity") or Decimal("0")
    min_notional = specs.get("min_notional") or Decimal("0")
    rounded = (qty / step).to_integral_value(rounding=ROUND_DOWN) * step
    if rounded <= 0:
        rounded = (qty / step).to_integral_value(rounding=ROUND_UP) * step
    required = max(qty, min_qty, (min_notional / price) if min_notional > 0 else Decimal("0"))
    if rounded < min_qty or (min_notional > 0 and rounded * price < min_notional):
        rounded = (required / step).to_integral_value(rounding=ROUND_UP) * step
    return format(rounded.normalize(), "f")


def short_continuation_ok(entry_mid: Decimal, latest_mid: Decimal, max_rebound_pct: Decimal = MAX_PRE_ENTRY_REBOUND_PCT) -> bool:
    if entry_mid <= 0 or latest_mid <= 0:
        return False
    return latest_mid <= entry_mid * (Decimal("1") + max_rebound_pct)


def place_order(
    symbol: str,
    side: str,
    qty: str,
    *,
    order_type: str = "market",
    tif: str = "ioc",
    price: Decimal | None = None,
    reduce_only: bool = False,
    allow_safety_halt_entry: bool = False,
) -> Any:
    if halt_active() and not reduce_only and not allow_safety_halt_entry:
        raise RuntimeError("safety_halt_active_order_block")
    # GUARD PRA-ORDER (fail-closed): venue WAJIB terbaca sebelum MENAMBAH risiko.
    # Menutup/mengurangi posisi SELALU diizinkan — guard yang memblokir exit saat
    # API hiccup justru menjadi sumber kerugian baru, bukan pengaman.
    if not reduce_only and not venue_state_readable():
        raise RuntimeError("venue_state_unreadable_refuse_open")
    args = [
        "bin/sodex",
        "orders",
        "place",
        "perps",
        "--symbol",
        symbol,
        "--side",
        side,
        "--type",
        order_type,
        "--tif",
        tif,
        "--qty",
        qty,
    ]
    if order_type == "limit":
        if price is None or price <= 0:
            raise ValueError("limit_order_requires_price")
        args.extend(["--price", format(price.normalize(), "f")])
    if reduce_only:
        args.append("--reduce-only")
    args.extend(["--format", "json"])
    return run_json(args, auth=True, timeout=45)


def order_ref(order: Any) -> tuple[int, str]:
    row = order[0] if isinstance(order, list) and order else order
    if not isinstance(row, dict):
        return 0, ""
    return int(dec(row.get("orderID"))), str(row.get("clOrdID") or "")


def cancel_order(symbol: str, order: Any) -> Any:
    oid, cl_ord_id = order_ref(order)
    sid = symbol_id(symbol)
    if sid <= 0 or (oid <= 0 and not cl_ord_id):
        return {"cancelled": False, "reason": "missing_symbol_or_order_id", "symbol_id": sid}
    args = ["bin/sodex", "orders", "cancel", "perps", "--symbol-id", str(sid)]
    if oid > 0:
        args.extend(["--order-id", str(oid)])
    else:
        args.extend(["--cl-ord-id", cl_ord_id])
    args.extend(["--format", "json"])
    return run_json(args, auth=True, timeout=45)


def _price_tick(*prices: Decimal) -> Decimal:
    exponents = [price.normalize().as_tuple().exponent for price in prices if price > 0]
    if not exponents:
        return Decimal("0")
    return Decimal("1").scaleb(min(exponents))


def maker_sell_price(bid: Decimal, ask: Decimal) -> Decimal:
    if bid <= 0 or ask <= 0 or ask <= bid:
        return ask
    tick = _price_tick(bid, ask)
    improved = ask - tick
    return improved if tick > 0 and improved > bid else ask


def maker_buy_price(bid: Decimal, ask: Decimal) -> Decimal:
    if bid <= 0 or ask <= 0 or ask <= bid:
        return bid
    tick = _price_tick(bid, ask)
    improved = bid + tick
    return improved if tick > 0 and improved < ask else bid


def entry_order_args(args: argparse.Namespace, candidate: Candidate) -> tuple[str, str, Decimal | None]:
    if args.entry_mode == "maker":
        return "limit", "gtx", maker_sell_price(candidate.bid, candidate.ask)
    return "market", "ioc", None


def reduce_exit_order_args(args: argparse.Namespace, symbol: str) -> tuple[str, str, Decimal | None]:
    if args.exit_mode != "maker":
        return "market", "ioc", None
    book = orderbook(symbol)
    bid = _book_price(book, "bids")
    ask = _book_price(book, "asks")
    if bid <= 0 or ask <= 0:
        return "market", "ioc", None
    return "limit", "gtx", maker_buy_price(bid, ask)


def position_size(report: dict[str, Any], symbol: str) -> Decimal:
    for pos in open_positions(report):
        if str(pos.get("symbol")) == symbol:
            return dec(pos.get("size"))
    return Decimal("0")


def append_log(record: dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def is_ratio_recovery_lane(lane: dict[str, Any] | None) -> bool:
    return bool(lane and lane.get("lane") == "RATIO_RECOVERY_MAKER_ONLY")


def ta_probability_gate(
    symbol: str,
    *,
    side: str,
    notional: Decimal,
    min_probability: Decimal = MIN_TA_PROBABILITY,
) -> dict[str, Any]:
    return evaluate_symbol_gate(
        symbol,
        side=side,
        notional_usd=notional,
        min_ratio=MIN_REAL_VOLUME_LOSS_RATIO,
        min_probability=min_probability,
    )


def build_record(args: argparse.Namespace) -> dict[str, Any]:
    requested = dec(args.notional)
    report = monitor_report()
    policy = target_policy(report)
    daily_loss_used = micro_daily_loss_used_usd()
    daily_volume = micro_daily_volume_usd()
    ok, reason, lane = policy_allows_micro(
        policy,
        report,
        requested,
        halt_exists=halt_active(),
        override_halt=bool(args.operator_override_safety_halt or not args.live),
        daily_loss_used_usd=daily_loss_used,
        daily_volume_usd=daily_volume,
        allow_ratio_recovery=bool(args.entry_mode == "maker"),
    )
    account_equity = equity_usd(report)
    perps_equity = perps_account_value_usd(report)
    barbell = current_barbell_gate(report) if args.live else {}
    cumulative_remaining = cumulative_ratio_loss_remaining_usd(
        requested,
        daily_loss_used_usd=daily_loss_used,
        daily_volume_usd=daily_volume,
    )
    ratio_recovery = bool(args.entry_mode == "maker" and is_ratio_recovery_lane(lane))
    record: dict[str, Any] = {
        "ts": time.time(),
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "live" if args.live else "dry_run",
        "allowed": ok,
        "reason": reason,
        "policy_decision": policy.get("decision"),
        "regime": policy.get("regime"),
        "blockers": policy.get("blockers"),
        "lane": lane,
        "requested_notional_usd": float(requested),
        "projected_roundtrip_volume_usd": float(projected_roundtrip_volume_usd(requested)),
        "min_real_volume_loss_ratio": float(MIN_REAL_VOLUME_LOSS_RATIO),
        "max_loss_for_min_ratio_usd": float(max_loss_for_ratio(requested)),
        "safety_halt_active": SAFETY_HALT.exists(),
        "account_equity_before_usd": float(account_equity),
        "perps_account_before_usd": float(perps_equity),
        "micro_daily_loss_used_usd": float(daily_loss_used),
        "micro_daily_volume_usd": float(daily_volume),
        "cumulative_ratio_loss_remaining_usd": float(cumulative_remaining),
        "ratio_recovery_mode": ratio_recovery,
        "ratio_recovery_requires_zero_incremental_loss": ratio_recovery,
        "event_days_left": float(days_to_event_end()),
        "barbell_phase": barbell.get("phase") if barbell else None,
        "entry_mode": args.entry_mode,
        "exit_mode": args.exit_mode,
        "min_ta_probability": float(dec(getattr(args, "min_ta_probability", MIN_TA_PROBABILITY))),
    }
    if not ok:
        return record
    if args.live and not barbell_allows_micro_live(
        barbell,
        override=bool(args.operator_override_barbell_cooldown),
    ):
        record.update({"allowed": False, "reason": "barbell_micro_cooldown"})
        return record

    candidate = select_candidate(tickers(), forced_symbol=args.symbol, ratio_recovery=ratio_recovery)
    if not candidate:
        record.update({"allowed": False, "reason": "no_candidate"})
        return record
    qty = qty_for_notional(requested, candidate.mid, candidate.symbol)
    record.update({
        "symbol": candidate.symbol,
        "side": "sell",
        "qty": qty,
        "mid": float(candidate.mid),
        "spread_pct": float(candidate.spread_pct),
        "change_pct": float(candidate.change_pct),
        "quote_volume": float(candidate.quote_volume),
        "score": float(candidate.score),
    })
    ta_gate = ta_probability_gate(
        candidate.symbol,
        side="sell",
        notional=requested,
        min_probability=dec(getattr(args, "min_ta_probability", MIN_TA_PROBABILITY)),
    )
    record["ta_probability_gate"] = ta_gate
    if args.live and not ta_gate.get("passes"):
        record.update({"allowed": False, "reason": "ta_probability_gate_failed"})
        return record
    if not args.live:
        return record

    if float(args.confirm_seconds) > 0:
        time.sleep(max(0.0, float(args.confirm_seconds)))
        latest_book = orderbook(candidate.symbol)
        latest_bid = _book_price(latest_book, "bids")
        latest_ask = _book_price(latest_book, "asks")
        latest_mid = (latest_bid + latest_ask) / Decimal("2") if latest_bid > 0 and latest_ask > 0 else Decimal("0")
        record["confirm_mid"] = float(latest_mid)
        if not short_continuation_ok(candidate.mid, latest_mid, dec(args.max_pre_entry_rebound_pct)):
            record.update({"allowed": False, "reason": "short_continuation_failed"})
            return record
        if latest_bid > 0 and latest_ask > latest_bid:
            candidate = Candidate(
                candidate.symbol,
                latest_bid,
                latest_ask,
                latest_mid,
                (latest_ask - latest_bid) / latest_mid,
                candidate.change_pct,
                candidate.quote_volume,
                candidate.funding_rate,
                candidate.score,
            )
            record["confirm_bid"] = float(latest_bid)
            record["confirm_ask"] = float(latest_ask)

    order_type, tif, entry_price = entry_order_args(args, candidate)
    if entry_price is not None:
        record["entry_price"] = float(entry_price)
    open_result = place_order(
        candidate.symbol,
        "sell",
        qty,
        order_type=order_type,
        tif=tif,
        price=entry_price,
        reduce_only=False,
        allow_safety_halt_entry=bool(
            args.operator_override_safety_halt
            and lane
            and lane.get("lane") == "SAFETY_HALT_SHORT_PILOT"
        ),
    )
    time.sleep(max(0.0, float(args.hold_seconds)))
    after_open = monitor_report()
    size = position_size(after_open, candidate.symbol)
    record["open_order"] = open_result
    record["opened_size"] = float(size)
    if size >= 0:
        if args.entry_mode == "maker":
            try:
                record["open_cancel"] = cancel_order(candidate.symbol, open_result)
            except Exception as exc:
                record["open_cancel_error"] = str(exc)[:300]
        after_no_fill = monitor_report()
        record.update({
            "closed": False,
            "reason": "no_maker_short_fill_detected" if args.entry_mode == "maker" else "no_short_fill_detected",
            "account_equity_after_usd": float(equity_usd(after_no_fill)),
            "account_delta_usd": float(equity_usd(after_no_fill) - account_equity),
            "perps_account_after_usd": float(perps_account_value_usd(after_no_fill)),
            "perps_account_delta_usd": float(perps_account_value_usd(after_no_fill) - perps_equity),
        })
        return record

    close_qty = format(abs(size).normalize(), "f")
    close_results: list[Any] = []
    close_cancels: list[Any] = []
    exit_attempts = max(1, int(args.exit_maker_attempts)) if args.exit_mode == "maker" else 1
    exit_wait = (
        float(args.exit_maker_attempt_seconds)
        if float(args.exit_maker_attempt_seconds) > 0
        else float(args.hold_seconds)
    )
    after_close = after_open
    residual = size
    for _attempt in range(exit_attempts):
        exit_type, exit_tif, exit_price = reduce_exit_order_args(args, candidate.symbol)
        if exit_price is not None:
            record["exit_price"] = float(exit_price)
        close_result = place_order(
            candidate.symbol,
            "buy",
            close_qty,
            order_type=exit_type,
            tif=exit_tif,
            price=exit_price,
            reduce_only=True,
        )
        close_results.append(close_result)
        time.sleep(max(2.0, exit_wait if args.exit_mode == "maker" else 2.0))
        after_close = monitor_report()
        residual = position_size(after_close, candidate.symbol)
        if residual == 0:
            break
        if args.exit_mode == "maker":
            try:
                close_cancels.append(cancel_order(candidate.symbol, close_result))
            except Exception as exc:
                record["close_cancel_error"] = str(exc)[:300]
        else:
            break
    if residual != 0:
        fallback = place_order(candidate.symbol, "buy", format(abs(residual).normalize(), "f"), reduce_only=True)
        record["close_fallback_order"] = fallback
        time.sleep(2)
        after_close = monitor_report()
        residual = position_size(after_close, candidate.symbol)
    close_result = close_results[-1] if close_results else None
    record.update({
        "close_order": close_result,
        "close_orders": close_results,
        "close_cancels": close_cancels,
        "closed": residual == 0,
        "residual_size": float(residual),
        "account_equity_after_usd": float(equity_usd(after_close)),
        "account_delta_usd": float(equity_usd(after_close) - account_equity),
        "perps_account_after_usd": float(perps_account_value_usd(after_close)),
        "perps_account_delta_usd": float(perps_account_value_usd(after_close) - perps_equity),
        "reason": "ok" if residual == 0 else "residual_position_after_retry",
    })
    if args.exit_mode == "maker" and residual == 0 and "close_fallback_order" in record:
        record["reason"] = "maker_exit_timeout_taker_fallback"
    loss = max(Decimal("0"), perps_equity - perps_account_value_usd(after_close))
    ratio_budget = max_loss_for_ratio(requested)
    if residual == 0 and loss > ratio_budget:
        record["reason"] = "farming_ratio_breach_after_close"
        record["volume_loss_ratio_actual"] = float(projected_roundtrip_volume_usd(requested) / loss) if loss > 0 else None
    return record


def run_cycles(args: argparse.Namespace) -> list[dict[str, Any]]:
    cycles = max(1, int(args.cycles))
    if args.live:
        cycles = min(cycles, MAX_LIVE_CYCLES)
    records: list[dict[str, Any]] = []
    for index in range(cycles):
        record = build_record(args)
        record["cycle"] = index + 1
        record["cycles_requested"] = int(args.cycles)
        append_log(record)
        records.append(record)
        maker_no_fill = (
            args.live
            and args.entry_mode == "maker"
            and record.get("reason") == "no_maker_short_fill_detected"
            and not record.get("opened_size")
        )
        if not maker_no_fill and (record.get("reason") != "ok" or not record.get("closed", not args.live)):
            break
        if index < cycles - 1 and not maker_no_fill:
            time.sleep(max(0.0, float(args.cooldown_seconds)))
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SoDEX bear-market micro pilot")
    parser.add_argument("--live", action="store_true", help="place real tiny orders; default is dry-run")
    parser.add_argument("--notional", default=str(DEFAULT_NOTIONAL_USD), help="target notional USD")
    parser.add_argument("--hold-seconds", type=float, default=2.0)
    parser.add_argument("--confirm-seconds", type=float, default=3.0)
    parser.add_argument("--max-pre-entry-rebound-pct", default=str(MAX_PRE_ENTRY_REBOUND_PCT))
    parser.add_argument("--exit-maker-attempts", type=int, default=1)
    parser.add_argument("--exit-maker-attempt-seconds", type=float, default=0.0)
    parser.add_argument("--cycles", type=int, default=1, help="bounded cycle count; live is capped internally")
    parser.add_argument("--cooldown-seconds", type=float, default=300.0)
    parser.add_argument("--symbol", help="force one perps symbol, still validated")
    parser.add_argument(
        "--min-ta-probability",
        default=str(MIN_TA_PROBABILITY),
        help="minimum seven-signal TA probability required before live entry",
    )
    parser.add_argument(
        "--entry-mode",
        choices=("taker", "maker"),
        default="taker",
        help="entry execution route: taker=market IOC, maker=post-only limit at best ask",
    )
    parser.add_argument(
        "--exit-mode",
        choices=("taker", "maker"),
        default="taker",
        help="exit execution route: taker=reduce-only market IOC, maker=post-only reduce-only at best bid with taker fallback",
    )
    parser.add_argument(
        "--operator-override-safety-halt",
        action="store_true",
        help="allow operator-approved micro live while SAFETY_HALT exists",
    )
    parser.add_argument(
        "--operator-override-barbell-cooldown",
        action="store_true",
        help="allow operator-approved micro live even when Event Barbell is in cooldown",
    )
    args = parser.parse_args(argv)
    records = run_cycles(args)
    output: Any = records[0] if len(records) == 1 else records
    print(json.dumps(output, indent=2, sort_keys=True))
    last = records[-1] if records else {}
    return 0 if last.get("reason") in {"ok", "safety_halt_active"} or last.get("allowed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
