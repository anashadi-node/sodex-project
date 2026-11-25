#!/usr/bin/env python3
"""
ANANTARA SAKTI — SoDEX Volume & Ratio Planner

Target: Rasio Total Real min target aktif, max NO-LOSS, Volume 1.3M+ USD/minggu
Snapshot: Sabtu 07:00 WIB (00:00 UTC) — akumulasi Senin 00:00 – Sabtu 00:00 UTC

Calculator untuk proyeksi volume, biaya, dan rasio pada berbagai konfigurasi
scalp farming + directional farming + spot maker farming.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MONITOR_JSON = PROJECT_DIR / "data" / "sodex_monitor_eval" / "latest.json"
WIB = timezone(timedelta(hours=7))

TARGET_WEEKLY_VOLUME_USD = 1_300_000
BASE_VOLUME_FEE_RATIO = 7_000
EMERGENCY_VOLUME_FEE_RATIO = 5_100
EMERGENCY_RATIO_UNTIL_WIB = datetime(2026, 7, 18, 9, 30, tzinfo=WIB)
_DEFAULT_TARGET_VOLUME_FEE_RATIO = (
    EMERGENCY_VOLUME_FEE_RATIO if datetime.now(WIB) <= EMERGENCY_RATIO_UNTIL_WIB else BASE_VOLUME_FEE_RATIO
)
TARGET_VOLUME_FEE_RATIO = int(os.environ.get("SODEX_PLANNER_TARGET_VOLUME_FEE_RATIO", _DEFAULT_TARGET_VOLUME_FEE_RATIO))
TARGET_REAL_RATIO_MAX = None
TARGET_WIN_RATE = 0.69
MAX_CATCHUP_DAYS = 4
DEFAULT_ADDITIONAL_SPOT_CAPITAL_USD = 100
DEFAULT_ADDITIONAL_PERP_CAPITAL_USD = 150

# ── SoDEX Fee Structure ──────────────────────────────────────────────
MAKER_FEE = 0.00012   # 0.012%
TAKER_FEE = 0.00024   # 0.024%
SPREAD_BTC = 0.000013 # ~0.0013% (BTC/ETH/SOL tight)
SPREAD_ALT = 0.0005   # ~0.05% (mid-cap)
SPREAD_WIDE = 0.0028  # ~0.28% (PEPE/SHIB spot)

# ── Snapshot Window ──────────────────────────────────────────────────
# Sabtu 07:00 WIB = Sabtu 00:00 UTC
# Periode: Senin 00:00 UTC → Sabtu 00:00 UTC = 5 hari (120 jam)
SNAPSHOT_HOURS_PER_WEEK = 120  # 5 hari efektif


@dataclass
class MonitorContext:
    """Latest read-only SoDEX monitor facts used for catch-up planning."""
    capital_usd: float = 0.0
    official_spot_usd: float = 0.0
    official_futures_usd: float = 0.0
    official_volume_usd: float = 0.0
    canonical_volume_usd: float = 0.0
    ledger_raw_usd: float = 0.0
    ledger_weighted_usd: float = 0.0
    fees_usd: float = 0.0
    realized_pnl_usd: float = 0.0
    win_rate: float | None = None
    cost_coverage: float | None = None
    official_lagging_ledger: bool = False


@dataclass
class FarmConfig:
    """Konfigurasi farming scenario."""
    name: str
    margin_per_round: float      # USD own funds
    leverage: int
    rounds_per_cycle: int
    cycles_per_hour: float       # berapa cycle per jam
    maker_fill_ratio: float      # 0.0-1.0, seberapa sering kena maker
    spread_pct: float            # as % (0.0013 = 0.0013%)
    hours_per_week: int = SNAPSHOT_HOURS_PER_WEEK


def _num(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def load_monitor_context(path: Path | str = DEFAULT_MONITOR_JSON) -> MonitorContext:
    """Load the latest read-only monitor report.

    Official dashboard volume is canonical for SoDEX-credited progress when
    present; ledger values remain the bot-side audit trail for fills, fees, RTs,
    and realized PnL.
    """
    payload = json.loads(Path(path).read_text())
    account_value = ((payload.get("account") or {}).get("account_value") or {})
    official = payload.get("official_dashboard") or {}
    official_volume = official.get("volume") or {}
    ledger = payload.get("ledger") or {}
    ledger_volume = ledger.get("volume") or {}
    ratios = ledger.get("ratios") or {}
    rts = ledger.get("rts") or {}
    costs = ledger.get("costs") or {}
    pnl = ledger.get("pnl") or {}
    progress = (payload.get("verdict") or {}).get("progress") or {}

    official_ok = official.get("quality") == "OK" and bool(official.get("canonical"))
    official_total = _num(official_volume.get("total_usd")) if official_ok else 0.0
    official_spot = _num(official_volume.get("spot_usd")) if official_ok else 0.0
    official_futures = _num(official_volume.get("perps_usd")) if official_ok else 0.0
    ledger_raw = _num(ledger_volume.get("raw_total_usd"))
    canonical = _num(progress.get("canonical_volume_usd"), official_total or ledger_raw)

    return MonitorContext(
        capital_usd=_num(account_value.get("total_equity_usd")),
        official_spot_usd=official_spot,
        official_futures_usd=official_futures,
        official_volume_usd=official_total,
        canonical_volume_usd=canonical,
        ledger_raw_usd=ledger_raw,
        ledger_weighted_usd=_num(ledger_volume.get("weighted_total_usd")),
        fees_usd=_num(costs.get("fees_usd")),
        realized_pnl_usd=_num(pnl.get("realized_net_usd")),
        win_rate=_num(rts.get("win_rate"), -1.0) if rts.get("win_rate") is not None else None,
        cost_coverage=(
            _num(ratios.get("cost_coverage_realized_pnl_over_fee"), -1.0)
            if ratios.get("cost_coverage_realized_pnl_over_fee") is not None else None
        ),
        official_lagging_ledger=bool(
            official_ok
            and ledger_raw > official_total > 0
        ),
    )


def _ratio(volume: float, fees: float) -> float | None:
    if fees <= 0:
        return None
    return volume / fees


def fmt_money(value: float | None, *, signed: bool = False, precision: int = 2) -> str:
    if value is None:
        return "n/a"
    sign = "+" if signed else ""
    return f"${value:{sign},.{precision}f}"


def fmt_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"1:{value:,.2f}"


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


def compute_real_ratios(
    ctx: MonitorContext,
    *,
    target_volume: float = TARGET_WEEKLY_VOLUME_USD,
) -> dict:
    """Compute ratio variants without mixing SoDEX official and local ledger units."""
    official_weighted = ctx.official_futures_usd + (ctx.official_spot_usd * 2)
    net_cost = max(0.0, ctx.fees_usd - max(0.0, ctx.realized_pnl_usd))
    raw_profit_needed_min = max(0.0, ctx.fees_usd - (ctx.official_volume_usd / TARGET_VOLUME_FEE_RATIO))
    weighted_profit_needed_min = max(0.0, ctx.fees_usd - (official_weighted / TARGET_VOLUME_FEE_RATIO))
    no_loss_profit_needed = max(0.0, ctx.fees_usd)
    return {
        "official_raw_volume_usd": ctx.official_volume_usd,
        "official_weighted_volume_usd": official_weighted,
        "ledger_raw_volume_usd": ctx.ledger_raw_usd,
        "ledger_weighted_volume_usd": ctx.ledger_weighted_usd,
        "fees_usd": ctx.fees_usd,
        "realized_pnl_usd": ctx.realized_pnl_usd,
        "official_raw_volume_fee_ratio": _ratio(ctx.official_volume_usd, ctx.fees_usd),
        "official_weighted_volume_fee_ratio": _ratio(official_weighted, ctx.fees_usd),
        "ledger_raw_volume_fee_ratio": _ratio(ctx.ledger_raw_usd, ctx.fees_usd),
        "ledger_weighted_volume_fee_ratio": _ratio(ctx.ledger_weighted_usd, ctx.fees_usd),
        "official_raw_net_cost_ratio": _ratio(ctx.official_volume_usd, net_cost),
        "official_weighted_net_cost_ratio": _ratio(official_weighted, net_cost),
        "ledger_raw_net_cost_ratio": _ratio(ctx.ledger_raw_usd, net_cost),
        "ledger_weighted_net_cost_ratio": _ratio(ctx.ledger_weighted_usd, net_cost),
        "net_cost_usd": net_cost,
        "profit_needed_for_official_raw_target_ratio": raw_profit_needed_min,
        "profit_needed_for_official_weighted_target_ratio": weighted_profit_needed_min,
        "profit_needed_for_no_loss": no_loss_profit_needed,
        "extra_profit_needed_for_official_raw_target_ratio": max(0.0, raw_profit_needed_min - ctx.realized_pnl_usd),
        "extra_profit_needed_for_official_weighted_target_ratio": max(0.0, weighted_profit_needed_min - ctx.realized_pnl_usd),
        "extra_profit_needed_for_no_loss": max(0.0, no_loss_profit_needed - ctx.realized_pnl_usd),
        "official_raw_progress": ctx.official_volume_usd / target_volume if target_volume > 0 else None,
        "official_weighted_progress": official_weighted / target_volume if target_volume > 0 else None,
        "ledger_raw_progress": ctx.ledger_raw_usd / target_volume if target_volume > 0 else None,
        "ledger_weighted_progress": ctx.ledger_weighted_usd / target_volume if target_volume > 0 else None,
        "fee_rate_vs_official_raw": ctx.fees_usd / ctx.official_volume_usd if ctx.official_volume_usd > 0 else None,
        "fee_rate_vs_official_weighted": ctx.fees_usd / official_weighted if official_weighted > 0 else None,
        "fee_rate_vs_ledger_raw": ctx.fees_usd / ctx.ledger_raw_usd if ctx.ledger_raw_usd > 0 else None,
        "fee_rate_vs_ledger_weighted": ctx.fees_usd / ctx.ledger_weighted_usd if ctx.ledger_weighted_usd > 0 else None,
    }


def build_capital_topup_model(
    ctx: MonitorContext,
    *,
    additional_spot_usd: float = DEFAULT_ADDITIONAL_SPOT_CAPITAL_USD,
    additional_perp_usd: float = DEFAULT_ADDITIONAL_PERP_CAPITAL_USD,
) -> dict:
    additional_total = max(0.0, additional_spot_usd) + max(0.0, additional_perp_usd)
    projected_total = ctx.capital_usd + additional_total
    return {
        "current_capital_usd": ctx.capital_usd,
        "additional_spot_usd": max(0.0, additional_spot_usd),
        "additional_perp_usd": max(0.0, additional_perp_usd),
        "additional_total_usd": additional_total,
        "projected_total_capital_usd": projected_total,
        "max_loss_budget_25pct_usd": projected_total * 0.25,
        "spot_lane": "E1/profit engine inventory and wide-spread maker capture",
        "perp_lane": "E2/volume engine, hedged or maker-only unless edge-gated",
    }


def build_catchup_plan(
    ctx: MonitorContext,
    *,
    target_volume: float = TARGET_WEEKLY_VOLUME_USD,
    max_days: float = MAX_CATCHUP_DAYS,
    target_ratio: float = TARGET_VOLUME_FEE_RATIO,
) -> dict:
    """Calculate the capped catch-up requirement for the next max_days."""
    current = max(0.0, ctx.canonical_volume_usd)
    remaining = max(0.0, target_volume - current)
    horizon_hours = max(1, int(round(max_days * 24)))
    guards: list[str] = []

    if ctx.official_lagging_ledger:
        guards.append("official_dashboard_lower_than_internal_ledger")
    if ctx.win_rate is not None and ctx.win_rate < TARGET_WIN_RATE:
        guards.append("weekly_win_rate_below_target")
    if ctx.realized_pnl_usd < 0:
        guards.append("realized_pnl_negative")
    if ctx.cost_coverage is not None and ctx.cost_coverage < 1.0:
        guards.append("cost_not_fully_covered_by_realized_pnl")

    if ctx.realized_pnl_usd < 0 or (ctx.win_rate is not None and ctx.win_rate < TARGET_WIN_RATE):
        risk_mode = "RESEARCH_ONLY"
    else:
        risk_mode = "CAPPED_CATCH_UP"
    if ctx.official_lagging_ledger:
        risk_mode += "_RECON_FIRST"

    projected_fee_budget = remaining / target_ratio if target_ratio > 0 else 0.0
    max_loss_budget = max(0.0, ctx.capital_usd * 0.25)

    return {
        "target_volume_usd": target_volume,
        "current_volume_usd": current,
        "remaining_volume_usd": remaining,
        "horizon_hours": horizon_hours,
        "required_volume_per_hour_usd": remaining / horizon_hours,
        "required_volume_per_day_usd": remaining / max_days if max_days > 0 else remaining,
        "target_ratio": target_ratio,
        "projected_fee_budget_usd": projected_fee_budget,
        "max_loss_budget_usd": max_loss_budget,
        "risk_mode": risk_mode,
        "guards": guards,
    }


def calc_roundtrip(cfg: FarmConfig) -> dict:
    """Calculate single roundtrip economics."""
    notional = cfg.margin_per_round * cfg.leverage
    volume_per_rt = notional * 2  # open + close

    # Cost: weighted average of maker vs taker
    maker_cost = notional * MAKER_FEE * 2 * cfg.maker_fill_ratio
    taker_cost = notional * TAKER_FEE * 2 * (1 - cfg.maker_fill_ratio)
    spread_cost = notional * cfg.spread_pct * (1 - cfg.maker_fill_ratio)
    total_cost = maker_cost + taker_cost + spread_cost

    ratio = volume_per_rt / total_cost if total_cost > 0 else float('inf')

    return {
        "notional": notional,
        "volume_per_rt": volume_per_rt,
        "maker_cost": maker_cost,
        "taker_cost": taker_cost,
        "spread_cost": spread_cost,
        "total_cost": total_cost,
        "ratio": ratio,
    }


def project_weekly(cfg: FarmConfig) -> dict:
    """Project weekly volume + cost for a given config."""
    rt = calc_roundtrip(cfg)
    cycles_per_week = cfg.cycles_per_hour * cfg.hours_per_week
    rounds_per_week = cycles_per_week * cfg.rounds_per_cycle

    weekly_volume = rt["volume_per_rt"] * rounds_per_week
    weekly_cost = rt["total_cost"] * rounds_per_week

    # Effective ratio (volume / cost for the week)
    effective_ratio = weekly_volume / weekly_cost if weekly_cost > 0 else float('inf')

    # Budget needed per week
    budget_needed = weekly_cost

    return {
        "config": cfg.name,
        "notional_per_rt": rt["notional"],
        "volume_per_rt": rt["volume_per_rt"],
        "cost_per_rt": rt["total_cost"],
        "ratio_per_rt": rt["ratio"],
        "rounds_per_week": rounds_per_week,
        "weekly_volume": weekly_volume,
        "weekly_cost": weekly_cost,
        "effective_ratio": effective_ratio,
        "budget_needed_weekly": budget_needed,
        "cycles_per_hour": cfg.cycles_per_hour,
        "maker_fill": cfg.maker_fill_ratio,
        "leverage": cfg.leverage,
        "margin": cfg.margin_per_round,
    }


def required_e1_subsidy_for_ratio(
    *,
    volume_usd: float,
    gross_cost_usd: float,
    target_ratio: float = TARGET_VOLUME_FEE_RATIO,
) -> dict:
    """Profit subsidy needed from E1 so total net-cost ratio reaches target."""
    max_net_cost = volume_usd / target_ratio if target_ratio > 0 else gross_cost_usd
    required_profit = max(0.0, gross_cost_usd - max_net_cost)
    net_cost_after_subsidy = max(0.0, gross_cost_usd - required_profit)
    return {
        "volume_usd": volume_usd,
        "gross_cost_usd": gross_cost_usd,
        "target_ratio": target_ratio,
        "max_net_cost_usd": max_net_cost,
        "required_e1_profit_usd": required_profit,
        "net_cost_after_subsidy_usd": net_cost_after_subsidy,
        "gross_ratio": _ratio(volume_usd, gross_cost_usd),
        "subsidized_ratio": _ratio(volume_usd, net_cost_after_subsidy),
    }


def find_path_to_target(
    target_volume: float,
    target_ratio_min: float,
    max_cost_per_week: float,
    current_capital: float,
) -> list[dict]:
    """Find feasible config paths to hit volume + ratio targets."""
    paths = []

    # Explore parameter space
    for leverage in [5, 10, 15, 20, 25]:
        for margin in [8, 15, 25, 50, 100, 150]:
            if margin * leverage > 15000:  # cap notional at $15K
                continue
            for maker_fill in [0.3, 0.5, 0.7, 0.85, 1.0]:
                for cycles_per_hour in [1, 2, 3, 6, 12]:
                    cfg = FarmConfig(
                        name=f"L{leverage}x_M{margin}_MK{int(maker_fill*100)}",
                        margin_per_round=margin,
                        leverage=leverage,
                        rounds_per_cycle=1,
                        cycles_per_hour=cycles_per_hour,
                        maker_fill_ratio=maker_fill,
                        spread_pct=SPREAD_BTC,
                    )
                    proj = project_weekly(cfg)

                    if (proj["weekly_volume"] >= target_volume
                            and proj["effective_ratio"] >= target_ratio_min
                            and proj["weekly_cost"] <= max_cost_per_week
                            and margin <= current_capital * 0.5):  # max 50% per round
                        paths.append(proj)

    # Sort by best ratio first
    paths.sort(key=lambda x: (-x["effective_ratio"], -x["weekly_volume"]))
    return paths[:20]


def run_all_scenarios(
    current_capital: float,
    *,
    target_volume: float = TARGET_WEEKLY_VOLUME_USD,
    monitor: MonitorContext | None = None,
    max_days: float = MAX_CATCHUP_DAYS,
):
    """Print comprehensive scenario analysis."""
    print("=" * 78)
    print("  ANANTARA SAKTI — SoDEX Volume & Ratio Planner")
    print(f"  Target: Total Real Ratio min 1:{TARGET_VOLUME_FEE_RATIO:,} · max NO-LOSS · "
          f"Volume ${target_volume:,.0f}+/minggu")
    print("  Snapshot: Sabtu 07:00 WIB (00:00 UTC)")
    print("=" * 78)

    if monitor is not None:
        print("\n── LIVE MONITOR CONTEXT (READ-ONLY) ──")
        print(f"  Capital/equity : ${monitor.capital_usd:,.2f}")
        print(f"  Official volume: ${monitor.official_volume_usd:,.2f}")
        print(f"  Ledger weighted: ${monitor.ledger_weighted_usd:,.2f}")
        print(f"  PnL / fees     : ${monitor.realized_pnl_usd:+,.2f} / ${monitor.fees_usd:,.2f}")
        if monitor.win_rate is not None:
            print(f"  RT win-rate    : {monitor.win_rate:.2%}")
        plan = build_catchup_plan(monitor, target_volume=target_volume, max_days=max_days)
        print("\n── 4x24H CATCH-UP REQUIREMENT ──")
        print(f"  Remaining vol  : ${plan['remaining_volume_usd']:,.2f}")
        print(f"  Required/day   : ${plan['required_volume_per_day_usd']:,.2f}")
        print(f"  Required/hour  : ${plan['required_volume_per_hour_usd']:,.2f}")
        print(f"  Fee budget @1:{TARGET_VOLUME_FEE_RATIO:,}: ${plan['projected_fee_budget_usd']:,.2f}")
        print(f"  Risk mode      : {plan['risk_mode']}")
        if plan["guards"]:
            print(f"  Guards         : {', '.join(plan['guards'])}")

        ratios = compute_real_ratios(monitor, target_volume=target_volume)
        topup = build_capital_topup_model(monitor)
        print("\n── REAL VOLUME/FEE RATIOS ──")
        print(f"  SoDEX official raw      : {fmt_money(ratios['official_raw_volume_usd'])} / "
              f"${ratios['fees_usd']:,.6f} = {fmt_ratio(ratios['official_raw_volume_fee_ratio'])}")
        print(f"  SoDEX official weighted : {fmt_money(ratios['official_weighted_volume_usd'])} / "
              f"${ratios['fees_usd']:,.6f} = {fmt_ratio(ratios['official_weighted_volume_fee_ratio'])}")
        print(f"  Official raw net-cost   : {fmt_money(ratios['official_raw_volume_usd'])} / "
              f"${ratios['net_cost_usd']:,.6f} = {fmt_ratio(ratios['official_raw_net_cost_ratio'])}")
        print(f"  Official weighted net   : {fmt_money(ratios['official_weighted_volume_usd'])} / "
              f"${ratios['net_cost_usd']:,.6f} = {fmt_ratio(ratios['official_weighted_net_cost_ratio'])}")
        print(f"  Internal ledger raw     : {fmt_money(ratios['ledger_raw_volume_usd'])} / "
              f"${ratios['fees_usd']:,.6f} = {fmt_ratio(ratios['ledger_raw_volume_fee_ratio'])}")
        print(f"  Internal ledger weighted: {fmt_money(ratios['ledger_weighted_volume_usd'])} / "
              f"${ratios['fees_usd']:,.6f} = {fmt_ratio(ratios['ledger_weighted_volume_fee_ratio'])}")
        print(f"  Official raw progress   : {fmt_pct(ratios['official_raw_progress'])}")
        print(f"  Official weighted prog. : {fmt_pct(ratios['official_weighted_progress'])}")
        print("\n── E1 PROFIT COVERAGE NEEDED ──")
        print(f"  Raw official 1:{TARGET_VOLUME_FEE_RATIO:,}: need E1 profit "
              f"${ratios['profit_needed_for_official_raw_target_ratio']:,.2f}; "
              f"extra from now ${ratios['extra_profit_needed_for_official_raw_target_ratio']:,.2f}")
        print(f"  Weighted official 1:{TARGET_VOLUME_FEE_RATIO:,}: need E1 profit "
              f"${ratios['profit_needed_for_official_weighted_target_ratio']:,.2f}; "
              f"extra from now ${ratios['extra_profit_needed_for_official_weighted_target_ratio']:,.2f}")
        print(f"  NO-LOSS max target: need E1 profit ${ratios['profit_needed_for_no_loss']:,.2f}; "
              f"extra from now ${ratios['extra_profit_needed_for_no_loss']:,.2f}")
        print("\n── CAPITAL TOP-UP MODEL (NO TRANSFER DONE) ──")
        print(f"  Add spot/perp   : ${topup['additional_spot_usd']:,.2f} / "
              f"${topup['additional_perp_usd']:,.2f}")
        print(f"  Projected cap   : ${topup['projected_total_capital_usd']:,.2f}")
        print(f"  25% risk budget : ${topup['max_loss_budget_25pct_usd']:,.2f}")

    # ── SCENARIO A: Current baseline ─────────────────────────────────
    print("\n── SCENARIO A: Current Scalp Farming (BASELINE) ──")
    current = FarmConfig(
        name="CURRENT",
        margin_per_round=25,
        leverage=20,
        rounds_per_cycle=2,
        cycles_per_hour=3,   # every 20 min
        maker_fill_ratio=0.3,  # mostly taker for instant open+close
        spread_pct=SPREAD_BTC,
    )
    proj = project_weekly(current)
    _print_scenario(proj, target_volume)

    # ── SCENARIO B: Optimized maker-biased ───────────────────────────
    print("\n── SCENARIO B: Maker-Optimized (post-only GTX, tighter timing) ──")
    maker_opt = FarmConfig(
        name="MAKER_OPT",
        margin_per_round=25,
        leverage=20,
        rounds_per_cycle=1,
        cycles_per_hour=12,  # every 5 min
        maker_fill_ratio=0.85,  # target 85% maker
        spread_pct=SPREAD_BTC,
    )
    proj = project_weekly(maker_opt)
    _print_scenario(proj, target_volume)

    # ── SCENARIO C: Higher margin + leverage ─────────────────────────
    print("\n── SCENARIO C: Scale-Up (higher margin + max leverage) ──")
    scale_up = FarmConfig(
        name="SCALE_UP",
        margin_per_round=100,
        leverage=25,
        rounds_per_cycle=1,
        cycles_per_hour=6,   # every 10 min
        maker_fill_ratio=0.7,
        spread_pct=SPREAD_BTC,
    )
    proj = project_weekly(scale_up)
    _print_scenario(proj, target_volume)

    # ── SCENARIO D: Ultra-efficient (pure maker theoretical max) ──
    print("\n── SCENARIO D: Pure Maker (theoretical ceiling) ──")
    pure_maker = FarmConfig(
        name="PURE_MAKER",
        margin_per_round=100,
        leverage=25,
        rounds_per_cycle=1,
        cycles_per_hour=6,
        maker_fill_ratio=1.0,  # 100% maker
        spread_pct=0.0,        # no spread cost on maker
    )
    proj = project_weekly(pure_maker)
    _print_scenario(proj, target_volume)

    # ── FEASIBILITY: Path to targets ─────────────────────────────────
    print(f"\n── PATH FINDER: Configurations hitting ${target_volume:,.0f}+/week at 1:{TARGET_VOLUME_FEE_RATIO:,}+ ──")
    print(f"  Capital: ${current_capital:,.0f} | Max budget 25% = ${current_capital*0.25:,.0f}/week")

    paths = find_path_to_target(
        target_volume=target_volume,
        target_ratio_min=TARGET_VOLUME_FEE_RATIO,
        max_cost_per_week=current_capital * 0.25,
        current_capital=current_capital,
    )

    if paths:
        for i, p in enumerate(paths):
            print(f"\n  Path {i+1}: {p['config']}")
            print(f"    Margin ${p['margin']:.0f} × {p['leverage']}x = ${p['notional_per_rt']:,.0f} notional")
            print(f"    {p['cycles_per_hour']:.0f} RT/h · {p['maker_fill']*100:.0f}% maker")
            print(f"    → {p['weekly_volume']:,.0f} vol/minggu · ${p['weekly_cost']:,.2f} cost · "
                  f"Rasio 1:{p['effective_ratio']:,.0f}")
    else:
        print("\n  ❌ NO feasible path found with current capital constraints.")
        print(f"     Capital needed: ~${_min_capital_for_target(target_volume):,.0f}+")
        print(f"     At current ~${current_capital:,.0f}, max theoretical weekly volume:")
        _show_max_theoretical(current_capital)

    # ── CAPITAL GAP ANALYSIS ─────────────────────────────────────────
    print("\n── CAPITAL GAP: What's needed for targets ──")
    _capital_gap_analysis(current_capital, target_volume)

    # ── RECOMMENDATIONS ──────────────────────────────────────────────
    print("\n── REKOMENDASI ──")
    print("  1. Scale bertahap: naikkan margin dari $25 → $50 → $100 → $150")
    print("  2. Optimasi maker: gunakan GTX (post-only), hindari market order")
    print("  3. Tambah frekuensi: dari 3x/jam → 6-12x/jam saat spread tight")
    print("  4. Multi-symbol: BTC+ETH+SOL+XAUT paralel (4× volume)")
    print("  5. Spot maker: unlock PROVEN flag → tambahan volume low-cap")
    print("  6. Pertimbangkan tambahan modal untuk scaling")


def _print_scenario(proj: dict, target_volume: float = TARGET_WEEKLY_VOLUME_USD):
    """Print one scenario projection."""
    print(f"  Config      : {proj['config']}")
    print(f"  Per RT       : ${proj['notional_per_rt']:,.0f} notional → "
          f"${proj['volume_per_rt']:,.0f} vol · ${proj['cost_per_rt']:.4f} cost")
    print(f"  Ratio/RT     : 1:{proj['ratio_per_rt']:,.0f}")
    print(f"  Volume/week  : ${proj['weekly_volume']:,.0f}")
    print(f"  Cost/week    : ${proj['weekly_cost']:,.2f}")
    print(f"  Eff. Ratio   : 1:{proj['effective_ratio']:,.0f}")
    subsidy = required_e1_subsidy_for_ratio(
        volume_usd=proj["weekly_volume"],
        gross_cost_usd=proj["weekly_cost"],
    )
    print(f"  E1 subsidy   : {fmt_money(subsidy['required_e1_profit_usd'])} "
          f"to reach 1:{TARGET_VOLUME_FEE_RATIO:,}")
    hit_vol = "✅" if proj['weekly_volume'] >= target_volume else "❌"
    hit_ratio = "✅" if proj['effective_ratio'] >= TARGET_VOLUME_FEE_RATIO else "❌"
    hit_subsidized = "✅" if subsidy["required_e1_profit_usd"] <= proj["weekly_cost"] else "❌"
    print(f"  Target hit   : Vol {hit_vol} | Fee-only ratio {hit_ratio} | E1-subsidized {hit_subsidized}")


def _min_capital_for_target(target_vol: float = TARGET_WEEKLY_VOLUME_USD) -> float:
    """Estimate minimum capital needed for target volume at the real-ratio target."""
    # At the configured target ratio, cost = volume / ratio.
    # Need ~$250 buffer per week, and enough margin for positions
    weekly_cost = target_vol / TARGET_VOLUME_FEE_RATIO
    # Need at least margin per round × max positions
    margin_needed = 100 * 4  # $400 working capital
    return max(weekly_cost * 3, margin_needed)  # ~$750 absolute minimum


def _show_max_theoretical(capital: float):
    """Show maximum theoretical volume for given capital."""
    budget = capital * 0.25  # 25% loss budget
    # Best case: pure maker, 1:8333
    best_ratio = 2 / (MAKER_FEE * 2)  # 8333
    max_vol = budget * best_ratio
    budget_50 = capital * 0.50
    max_vol_50 = budget_50 * best_ratio
    print(f"    25% budget (${budget:,.0f}): max ${max_vol:,.0f}/week at pure maker")
    print(f"    50% budget (${budget_50:,.0f}): max ${max_vol_50:,.0f}/week at pure maker")
    print(f"    Realistic (70% maker): ${max_vol*0.7:,.0f} / ${max_vol_50*0.7:,.0f}")


def _capital_gap_analysis(capital: float, target_vol: float = TARGET_WEEKLY_VOLUME_USD):
    """Analyze how much capital is needed for targets."""
    target_ratio = TARGET_VOLUME_FEE_RATIO

    # Cost at target ratio
    cost_at_target = target_vol / target_ratio  # $250

    # Margin needed per round at various leverage
    print(f"  Target cost/week: ${cost_at_target:,.0f}")
    print(f"  Current capital: ${capital:,.0f}")
    print()

    for leverage in [5, 10, 20, 25]:
        for maker_pct in [0.5, 0.7, 0.85, 1.0]:
            # cost per RT at this config (maker/taker mix)
            eff_fee = (maker_pct * MAKER_FEE + (1 - maker_pct) * TAKER_FEE) * 2
            # volume needed per RT: ratio = 2 / eff_fee
            ratio = 2 / eff_fee
            # margin × lev needed to generate volume
            # volume_per_rt = 2 × margin × lev
            # num_rt = target_vol / volume_per_rt
            # total_cost = num_rt × margin × lev × eff_fee
            # = (target_vol / (2×margin×lev)) × margin × lev × eff_fee
            # = target_vol × eff_fee / 2
            # Wait, cost is independent of margin! It's purely % based.
            # cost = target_vol × eff_fee / 2... no:
            # Each RT: vol = 2×margin×lev, cost = margin×lev×eff_fee
            # ratio = vol/cost = 2/eff_fee → PURELY determined by fee structure!
            # So any margin×lev gives same ratio. Volume depends on how many RTs.
            # num_rt = target_vol / (2×margin×lev)
            # cost = num_rt × margin × lev × eff_fee
            #      = target_vol / (2×margin×lev) × margin × lev × eff_fee
            #      = target_vol × eff_fee / 2

            # So for target volume:
            cost_weekly = target_vol * eff_fee / 2
            # Working capital: margin × max_concurrent_positions
            margin_needed = cost_weekly * 4  # buffer

            if cost_weekly <= capital * 0.25 and ratio >= target_ratio:
                print(f"  ✅ L{leverage}x MK{int(maker_pct*100)}% → "
                      f"${cost_weekly:,.0f}/week cost · 1:{ratio:,.0f} ratio · "
                      f"~${margin_needed:,.0f} capital needed")

    gap = max(0, cost_at_target - capital * 0.25)
    if gap > 0:
        print(f"\n  ⚠️ Gap: need ${gap:,.0f} more capital OR higher maker fill")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="SoDEX Volume & Ratio Planner")
    ap.add_argument("--capital", type=float, default=None,
                    help="Current capital in USD (default: latest monitor equity, else 134)")
    ap.add_argument("--target-volume", type=float, default=TARGET_WEEKLY_VOLUME_USD,
                    help="Weekly target volume in USD")
    ap.add_argument("--monitor-json", type=Path, default=DEFAULT_MONITOR_JSON,
                    help="Read-only latest monitor JSON path")
    ap.add_argument("--max-days", type=float, default=MAX_CATCHUP_DAYS,
                    help="Catch-up horizon in days")
    args = ap.parse_args()
    monitor = load_monitor_context(args.monitor_json) if args.monitor_json.exists() else None
    capital = args.capital
    if capital is None:
        capital = monitor.capital_usd if monitor and monitor.capital_usd > 0 else 134
    run_all_scenarios(
        capital,
        target_volume=args.target_volume,
        monitor=monitor,
        max_days=args.max_days,
    )
