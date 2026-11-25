#!/usr/bin/env python3
"""
ASTRONACCI v1.1 — Daemon Integration & Telegram Commands

Drop-in module for anantara_daemon.py: registers Astronacci jobs in the
APScheduler and adds Telegram command handlers.

INTEGRATION (add to anantara_daemon.py):

    from astronacci_agent import AstronacciAgent, AstronacciConfig
    from astronacci_daemon import register_astronacci_jobs, handle_astro_command

    astro_agent = AstronacciAgent()
    register_astronacci_jobs(scheduler, astro_agent, tg_sender=tg)

    # In Telegram handler:
    if cmd.startswith("/astro"):
        await handle_astro_command(cmd, astro_agent, tg_sender=tg)

SCHEDULED JOBS:
  • Every 6 hours: astronacci_cycle — compute ephemeris + signals
  • Daily 00:05: astronacci_daily — event calendar for next 7 days
  • Monday 00:30: astronacci_weekly — evidence registry report + governance audit

TELEGRAM COMMANDS:
  /astro        — Quick status: lunar phase, retrograde planets, recent signals
  /astroevents  — Upcoming astro events for next 14 days
  /astrostatus  — Full status report: ephemeris + evidence + governor
  /astrodataset — List saved datasets, data freshness check
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone, timedelta

from astronacci_ephemeris import lunar_phase_name
from typing import Callable, Awaitable

log = logging.getLogger("anantara.astronacci.daemon")

# Type alias for Telegram sender
TgSender = Callable[[str], Awaitable[None]] | None


# ─────────────────────────────────────────────────────────────────────────────
# SCHEDULER REGISTRATION
# ─────────────────────────────────────────────────────────────────────────────

def register_astronacci_jobs(
    scheduler,
    astro_agent,
    tg_sender: TgSender = None,
):
    """Register all Astronacci jobs in the APScheduler.

    Call once from anantara_daemon.py during startup.

    Args:
        scheduler: AsyncIOScheduler instance
        astro_agent: AstronacciAgent instance
        tg_sender: async function(str) → None for Telegram
    """
    import asyncio

    # Dedicated background loop for Astronacci coroutines. APScheduler worker
    # threads may invoke _spawn OUTSIDE the scheduler's event loop; the old
    # code created a new event loop but never ran it, so
    # run_coroutine_threadsafe(coro, dead_loop) silently dropped every job
    # ("coroutine was never awaited" RuntimeWarnings in the daemon journal).
    _bg_loop = asyncio.new_event_loop()
    threading.Thread(target=_bg_loop.run_forever, name="astronacci-asyncio", daemon=True).start()

    def _spawn(coro, job_name: str):
        """Schedule a coroutine on the background loop and log any exception.

        Safe to call from any thread: run_coroutine_threadsafe targets the
        always-running background loop above.
        """
        import concurrent.futures

        async def _run():
            try:
                await coro
            except Exception as exc:
                log.error(
                    f"Astronacci job '{job_name}' failed with unhandled "
                    f"exception: {exc!r}",
                    exc_info=True,
                )
        try:
            future = asyncio.run_coroutine_threadsafe(_run(), _bg_loop)

            def _on_done(fut: concurrent.futures.Future):
                exc = fut.exception()
                if exc is not None:
                    log.error(f"Astronacci job '{job_name}' raised: {exc!r}")

            future.add_done_callback(_on_done)
            return future
        except Exception as exc:
            log.error(f"Astronacci job '{job_name}' could not be scheduled: {exc!r}")
            return None

    # Every 6 hours: compute ephemeris + generate signals
    scheduler.add_job(
        lambda: _spawn(
            _astro_cycle_job(astro_agent, tg_sender), "astronacci_cycle",
        ),
        "interval",
        hours=6,
        id="astronacci_cycle",
        name="Astronacci: ephemeris + signals",
        replace_existing=True,
    )

    # Daily at 00:05 UTC: event calendar
    scheduler.add_job(
        lambda: _spawn(
            _astro_daily_job(astro_agent, tg_sender), "astronacci_daily",
        ),
        "cron",
        hour=0,
        minute=5,
        id="astronacci_daily",
        name="Astronacci: daily event calendar",
        replace_existing=True,
    )

    # Monday at 00:30 UTC: weekly evidence + governance report
    scheduler.add_job(
        lambda: _spawn(
            _astro_weekly_job(astro_agent, tg_sender), "astronacci_weekly",
        ),
        "cron",
        day_of_week="mon",
        hour=0,
        minute=30,
        id="astronacci_weekly",
        name="Astronacci: weekly governance audit",
        replace_existing=True,
    )

    # Every 6h: honest paper-trade loop. Opens a paper trade ONLY for signals
    # whose triggering feature is in `production` status (survived the 7-gate
    # defense). This accumulates a real, audited track record toward live
    # trading — without ever risking capital on an unvalidated edge.
    scheduler.add_job(
        lambda: _spawn(
            _astro_paper_job(astro_agent, tg_sender), "astronacci_paper",
        ),
        "interval",
        hours=6,
        id="astronacci_paper",
        name="Astronacci: paper-trade loop (production-only)",
        replace_existing=True,
    )

    # Every 1h: autonomous self-monitor & safe self-heal. Checks imports, data
    # freshness, registry honesty, paper-loop sanity, and statistical
    # determinism. Self-heals by refreshing stale data and demoting stale
    # production entries. NEVER auto-promotes or auto-trades.
    scheduler.add_job(
        lambda: _spawn(
            _astro_monitor_job(tg_sender), "astronacci_monitor",
        ),
        "interval",
        hours=1,
        id="astronacci_monitor",
        name="Astronacci: self-monitor & heal (1h)",
        replace_existing=True,
    )

    # Every 1h: market behavior early-warning + adaptive strategy reconfig.
    # Activates the existing MarketIntelligence engine (behavior change
    # detection, direction prediction, adaptive mode switch) that was
    # previously a ghost module — built but never wired to the daemon. This
    # gives the system fast, autonomous reaction to market behavior changes
    # on Binance (and multi-venue confirmation), reconfiguring strategy
    # parameters (BREAKOUT/MEAN_REVERSION/MOMENTUM/DEFENSIVE) within one hour
    # instead of waiting for the 24h improvement cycle.
    scheduler.add_job(
        lambda: _spawn(
            _astro_market_intel_job(tg_sender), "astronacci_market_intel",
        ),
        "interval",
        hours=1,
        id="astronacci_market_intel",
        name="Astronacci: market behavior early-warning + adaptive (1h)",
        replace_existing=True,
    )

    log.info(
        "Astronacci jobs registered: cycle(6h), daily(00:05), weekly(Mon 00:30), "
        "paper-trade(6h, production-only), monitor(1h, self-heal), "
        "market-intel(1h, behavior+adaptive)"
    )


async def _astro_cycle_job(astro_agent, tg_sender: TgSender):
    """Run compute cycle, send alert if actionable signal found."""
    try:
        summary = astro_agent.compute_cycle()

        if summary.get("status") != "ok":
            log.warning(f"Astronacci cycle failed: {summary.get('error')}")
            return

        signals = summary.get("signals", [])
        if signals and tg_sender:
            for sig in signals[:3]:  # max 3 signal messages
                direction_emoji = "🟢" if sig.get("direction") == "LONG" else "🔴"
                msg = (
                    f"{direction_emoji} *Astronacci Signal*\n"
                    f"Asset: `{sig.get('asset', 'BTC')}`\n"
                    f"Direction: *{sig.get('direction')}*\n"
                    f"Event: {sig.get('primary_event', 'N/A')}\n"
                    f"Evidence: {sig.get('evidence_score', 0)}/100\n"
                    f"Strength: {sig.get('strength', 0):.3f}"
                )
                await tg_sender(msg)

        log.info(
            f"Astronacci cycle: phase={summary.get('lunar_phase')}° "
            f"signals={len(signals)} retrograde={summary.get('retrograde_planets')}"
        )

    except Exception as e:
        log.error(f"Astronacci cycle job failed: {e}")


async def _astro_paper_job(astro_agent, tg_sender: TgSender):
    """Honest paper-trade loop (runs every 6h alongside the cycle).

    Opens a paper trade ONLY when the agent's latest signal comes from a
    feature in `production` status (i.e. it survived the 7-gate defense).
    This is the track-record accumulator toward live trading: it never risks
    capital on an unvalidated edge, and every opened trade carries the real
    `defense_gates_passed` in its audit trail (TIER 2.5 + Round 3).

    Safety: capped at 3 concurrent open trades (config.max_concurrent_signals).
    """
    try:
        # Re-run the cycle so we have a fresh signal with an attached
        # defense_result (compute_cycle already gates on evidence_score).
        summary = astro_agent.compute_cycle()
        if summary.get("status") != "ok":
            return
        signals = summary.get("signals", [])
        if not signals:
            return

        from astronacci_paper import PaperTradingEngine
        from astronacci_pipeline import AstroDataPipeline
        from astronacci_ablation import EvidenceRegistry

        registry = EvidenceRegistry()
        engine = PaperTradingEngine()
        pipeline = AstroDataPipeline()

        for sig_dict in signals[:3]:
            feature_name = sig_dict.get("primary_event", "")
            entry = registry.get(feature_name) if feature_name else None
            # HONEST GATE: only trade signals whose feature is production-grade.
            if entry is None or entry.status != "production":
                continue

            # Concurrency cap
            if len(engine.open_trades()) >= getattr(
                astro_agent.cfg, "max_concurrent_signals", 3
            ):
                break

            asset = sig_dict.get("asset", "BTC")
            try:
                ds = pipeline.fetch(asset, "1d", days=1)
                price = ds.bars[-1].close if ds and ds.bars else None
            except Exception:
                price = None
            if price is None or price <= 0:
                continue

            trade = engine.open_paper_trade_from_dict(sig_dict, current_price=price)
            if trade is not None and tg_sender:
                await tg_sender(
                    f"📝 *Paper Trade Opened (production signal)*\n"
                    f"Asset: `{asset}`  Direction: *{sig_dict.get('direction')}*\n"
                    f"Entry: `{price:.2f}`  Size: {trade.notional:.0f}\n"
                    f"Defense gates: {trade.defense_gates_passed}/7\n"
                    f"Evidence: {sig_dict.get('evidence_score', 0)}/100"
                )

    except Exception as e:
        log.error(f"Astronacci paper-trade job failed: {e}")


async def _astro_monitor_job(tg_sender: TgSender):
    """Autonomous self-monitor & safe self-heal (runs hourly).

    Runs the AstronacciMonitor battery: imports, data freshness, registry
    honesty, paper-loop sanity, statistical determinism. Applies SAFE
    self-heals only (refresh data, demote stale production). Alerts Telegram
    on degraded/critical state so issues surface immediately, 24/7.
    """
    try:
        from astronacci_monitor import self_monitor_and_heal
        report = self_monitor_and_heal(heal=True)
        overall = report.get("overall", "unknown")
        healed = report.get("healed_count", 0)
        log.info(
            f"Astronacci monitor: {overall} | healed={healed} | "
            f"{len(report.get('checks', []))} checks"
        )
        if tg_sender and overall in ("degraded", "critical"):
            lines = [f"🔬 *Astronacci Monitor: {overall.upper()}*"]
            for c in report.get("checks", []):
                if c.get("status") != "ok":
                    tag = "⚠️" if c["status"] == "warn" else "❌"
                    healed_mark = " ✅healed" if c.get("healed") else ""
                    lines.append(
                        f"{tag} `{c['name']}`: {c['detail'][:80]}{healed_mark}"
                    )
            await tg_sender("\n".join(lines[:8]))
    except Exception as e:
        log.error(f"Astronacci monitor job failed: {e}")


async def _astro_market_intel_job(tg_sender: TgSender):
    """Market behavior early-warning + adaptive strategy reconfig (hourly).

    Activates MarketIntelligence: scans each tracked asset for behavior
    changes (volatility shift, volume anomaly, trend change), predicts
    direction, and reconfigures the adaptive strategy mode. Alerts Telegram
    when behavior changes are detected so the operator gets early warning
    before a large move completes. Reads the adaptive mode so the
    paper-trade / signal path can size and set stops per the live regime.
    """
    try:
        from astronacci_market_intel import MarketIntelligence
        from astronacci_pipeline import AstroDataPipeline

        intel = MarketIntelligence()
        pipeline = AstroDataPipeline()
        notable = []
        for sym in ("BTC", "ETH", "SOL"):
            prices = None
            try:
                ds = pipeline.load_dataset(sym, "1d")
                if ds and ds.bars:
                    prices = ds.price_series()
            except Exception:
                pass
            try:
                result = intel.scan(sym, prices_4h=prices)
            except Exception as e:
                log.warning(f"market-intel scan {sym} failed: {e}")
                continue
            alerts = result.get("alerts", [])
            strat = result.get("strategy", {})
            # evaluate() returns {mode, params, status, reasons, scores}.
            mode = strat.get("mode")
            if alerts or mode:
                notable.append((sym, mode, len(alerts), alerts[:2]))

        if notable and tg_sender:
            lines = ["📡 *Market Intel — behavior scan*"]
            for sym, mode, n, alerts in notable:
                amark = f" ⚠️{n} alert" if n else ""
                lines.append(f"`{sym}` mode={mode}{amark}")
                for a in alerts:
                    lines.append(f"   • {a.get('reason', str(a))[:80]}")
            await tg_sender("\n".join(lines[:10]))
        log.info(f"market-intel: {len(notable)} notable among scanned assets")
    except Exception as e:
        log.error(f"Astronacci market-intel job failed: {e}")


async def _astro_daily_job(astro_agent, tg_sender: TgSender):
    """Send daily event calendar for next 7 days."""
    try:
        events = astro_agent.upcoming_events(7)
        if not events or not tg_sender:
            return

        msg = "🔮 *Astronacci — 7-Day Event Calendar*\n\n"
        for e in events[:15]:
            emoji = "🌑" if "New Moon" in e["type"] else (
                "🌕" if "Full Moon" in e["type"] else "✨"
            )
            msg += f"{emoji} {e['date'][:10]}: {e['type']}"

        await tg_sender(msg)
        log.info(f"Daily calendar sent: {len(events)} events")

    except Exception as e:
        log.error(f"Astronacci daily job failed: {e}")


async def _astro_weekly_job(astro_agent, tg_sender: TgSender):
    """Send weekly evidence registry + governance report."""
    try:
        report = astro_agent.status_report()
        reg = report.get("evidence_registry", {})

        msg = (
            "📊 *Astronacci — Weekly Governance Report*\n\n"
            f"📁 Evidence Registry:\n"
            f"  • Production: {reg.get('by_status', {}).get('production', 0)}\n"
            f"  • Research: {reg.get('by_status', {}).get('research', 0)}\n"
            f"  • Rejected: {reg.get('by_status', {}).get('rejected', 0)}\n\n"
            f"🚦 Governor blocks: {report.get('governor', {}).get('total_blocks', 0)}\n"
            f"📡 Weekly signals: {report.get('signals_today', 0)}\n"
        )

        # Sandwich credibility check — LOG failures, never swallow silently.
        # The previous `except Exception: pass` hid a broken credibility
        # detector, giving a false sense of epistemic safety. Sandwich
        # detection is a quality-control mechanism; if it fails we must know.
        try:
            sandwich = astro_agent.governor.detect_sandwich_credibility()
            if sandwich.get("sandwich_detected"):
                msg += "\n⚠️ *WARNING: Sandwich kredibilitas terdeteksi!*"
        except Exception as sw_err:
            log.error(
                "Sandwich credibility check FAILED (epistemic QC unavailable): "
                f"{sw_err}"
            )
            msg += "\n⚠️ *WARNING: Sandwich QC unavailable — see logs*"

        if tg_sender:
            await tg_sender(msg)
        log.info("Weekly governance report sent")

    except Exception as e:
        log.error(f"Astronacci weekly job failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# TELEGRAM COMMAND HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

async def handle_astro_command(
    cmd: str,
    astro_agent,
    tg_sender: TgSender = None,
) -> str:
    """Handle /astro* Telegram commands.

    Add to anantara_daemon.py Telegram handler:

        if cmd.startswith("/astro"):
            await handle_astro_command(cmd, astro_agent, tg_sender=tg)

    Returns the message string (also sends via tg_sender if provided).
    """
    cmd_lower = cmd.lower().strip()

    if cmd_lower in ("/astro", "/astronacci"):
        return await _cmd_astro_quick(astro_agent, tg_sender)

    elif cmd_lower in ("/astroevents", "/astroevent"):
        return await _cmd_astro_events(astro_agent, tg_sender)

    elif cmd_lower in ("/astrostatus", "/astroreport"):
        return await _cmd_astro_status(astro_agent, tg_sender)

    elif cmd_lower.startswith("/astrodataset"):
        return await _cmd_astro_datasets(tg_sender)

    else:
        msg = (
            "🔮 *Astronacci Commands*\n\n"
            "/astro — Quick status\n"
            "/astroevents — Upcoming events (14 days)\n"
            "/astrostatus — Full report\n"
            "/astrodataset — Saved datasets"
        )
        if tg_sender:
            await tg_sender(msg)
        return msg


async def _cmd_astro_quick(astro_agent, tg_sender: TgSender) -> str:
    """Quick astro status message."""
    try:
        snap = astro_agent.ephemeris.compute(datetime.now(timezone.utc))
        lunar = snap.lunar

        phase_name = lunar_phase_name(lunar.phase_angle)

        retros = [b.name for b in snap.bodies.values() if b.is_retrograde]
        aspects = sum(1 for a in snap.aspects if a.proximity > 0.7)

        msg = (
            f"🔮 *Astronacci* — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            f"{phase_name} ({lunar.phase_angle:.0f}°)\n"
            f"Illumination: {lunar.illumination:.1%}\n"
            f"Days to full moon: {lunar.days_to_full:.1f}\n"
            f"Distance: {lunar.distance_km:,.0f} km\n\n"
            f"🪐 Retrograde: {', '.join(retros) if retros else 'None'}\n"
            f"✨ Significant aspects (>0.7): {aspects}\n"
            f"🌌 Cluster density: {snap.cluster.density_score:.2f}"
        )

        # Add recent signals if any
        if astro_agent.state.last_signal:
            sig = astro_agent.state.last_signal
            msg += (
                f"\n\n📡 *Last Signal:* {sig.direction} "
                f"({sig.primary_event}, strength={sig.strength:.3f})"
            )

    except Exception as e:
        msg = f"🔮 Astronacci: ephemeris unavailable ({e})"

    if tg_sender:
        await tg_sender(msg)
    return msg


async def _cmd_astro_events(astro_agent, tg_sender: TgSender) -> str:
    """Upcoming events for next 14 days."""
    try:
        events = astro_agent.upcoming_events(14)
        if not events:
            msg = "🔮 No astro events in next 14 days."
        else:
            msg = "🔮 *Astronacci — 14-Day Event Calendar*\n\n"
            for e in events[:20]:
                emoji = (
                    "🌑" if "New Moon" in e["type"]
                    else "🌕" if "Full Moon" in e["type"]
                    else "🌓" if "Quarter" in e["type"]
                    else "✨"
                )
                msg += f"{emoji} `{e['date'][:10]}`: {e['type']}"
                if e.get("details"):
                    msg += f" _({e['details']})_"
                msg += "\n"
    except Exception as e:
        msg = f"🔮 Event calendar error: {e}"

    if tg_sender:
        await tg_sender(msg)
    return msg


async def _cmd_astro_status(astro_agent, tg_sender: TgSender) -> str:
    """Full status report."""
    try:
        report = astro_agent.status_report()
        ephem = report.get("ephemeris", {})
        lunar = ephem.get("lunar", {})
        reg = report.get("evidence_registry", {})
        gov = report.get("governor", {})

        msg = (
            f"🔮 *Astronacci — Full Status*\n"
            f"`{report['timestamp'][:19]}`\n\n"
            f"🌙 *Lunar:* {lunar.get('phase', '?')}° "
            f"({lunar.get('illumination', 0):.1%})\n"
            f"📅 Days to full: {lunar.get('days_to_full', '?')}\n"
            f"🪐 Retrograde: {', '.join(ephem.get('retrograde_planets', [])) or 'none'}\n"
            f"✨ Aspects >0.7: {ephem.get('significant_aspects', 0)}\n\n"
            f"📊 *Evidence Registry:*\n"
        )

        by_status = reg.get("by_status", {})
        for status in ["production", "research", "watchlist", "rejected"]:
            count = by_status.get(status, 0)
            emoji = {"production": "✅", "research": "🔬",
                      "watchlist": "👀", "rejected": "❌"}.get(status, "•")
            msg += f"  {emoji} {status}: {count}\n"

        msg += (
            f"\n🚦 *Governor:* {gov.get('total_blocks', 0)} blocks\n"
            f"📡 Active signals: {report.get('active_signals', 0)}\n"
        )

        # Sandwich check — log failures (epistemic QC must not fail silently).
        try:
            sandwich = astro_agent.governor.detect_sandwich_credibility()
            if sandwich.get("sandwich_detected"):
                msg += "\n⚠️ *Sandwich kredibilitas terdeteksi!*"
        except Exception as sw_err:
            log.error(
                "Sandwich credibility check FAILED (epistemic QC unavailable): "
                f"{sw_err}"
            )
            msg += "\n⚠️ *Sandwich QC unavailable — see logs*"

    except Exception as e:
        msg = f"🔮 Status error: {e}"

    if tg_sender:
        await tg_sender(msg)
    return msg


async def _cmd_astro_datasets(tg_sender: TgSender) -> str:
    """List saved astro-market datasets."""
    try:
        from astronacci_pipeline import AstroDataPipeline
        pipeline = AstroDataPipeline()
        datasets = pipeline.list_datasets()

        if not datasets:
            msg = "📁 No Astronacci datasets saved yet.\nUse the data pipeline to fetch data."
        else:
            msg = f"📁 *Astronacci Datasets* ({len(datasets)})\n\n"
            for ds in sorted(datasets)[:20]:
                msg += f"  • `{ds}`\n"
    except Exception as e:
        msg = f"📁 Dataset error: {e}"

    if tg_sender:
        await tg_sender(msg)
    return msg


# ─────────────────────────────────────────────────────────────────────────────
# SELF-TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    from astronacci_agent import AstronacciAgent

    async def _test():
        agent = AstronacciAgent()

        print("=== /astro quick ===")
        msg = await _cmd_astro_quick(agent, None)
        print(msg[:500])

        print("\n=== /astroevents ===")
        msg = await _cmd_astro_events(agent, None)
        print(msg[:500])

        print("\n=== /astrostatus ===")
        msg = await _cmd_astro_status(agent, None)
        print(msg[:500])

    asyncio.run(_test())
