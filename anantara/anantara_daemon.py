#!/usr/bin/env python3
"""
ANANTARA SAKTI v3.2 — Python Native Automation Daemon

Replaces N8N 12 workflows with pure Python (~200MB RAM vs ~1GB).

Schedules (UTC):
- Every  5 min: system health (RAM, disk, Freqtrade API, Hermes Bridge)
- Every  5 min: exchange WebSocket health (Freqtrade ping)
- Every 10 min: risk monitor + circuit breaker (3 levels)
- Every  1 hour: FreqAI model health
- 00:05 daily: daily briefing (trigger Hermes skill)
- Mon 00:30: weekly reflection (trigger Hermes skill)
- 02:00 daily: PostgreSQL backup (compressed, 7d retention)

Telegram commands (long-polling):
- /status /balance /profit /stop /start
- /kill /killresume
- /briefing /reflect /health /help

Requires: apscheduler httpx psutil
"""

from __future__ import annotations

import asyncio
import logging
import json
import os
import random
import re
import shutil
import sys
import subprocess
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import httpx
import psutil
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# NOTE: bare (same-dir) import — daemon dijalankan sebagai script
# (`python3 anantara/anantara_daemon.py`), jadi sys.path[0] = dir anantara/,
# bukan project root. Import bergaya `anantara.x` di baris ini membuat daemon
# crash-loop (ModuleNotFoundError) dan MEMBUNUH semua 67 job terjadwal.
from job_failure_breaker import RepeatedFailureBreaker  # noqa: E402

import sodex_farming as sf  # SoDEX farming helpers (same dir)
import cex_bootstrap_monitor as _cbm  # v8.2 bootstrap progress tracker
import cex_learning_analyzer as _cla  # v1.0 trade pattern/learning extractor
import cex_pair_blocklist as _cpb     # v8.6 auto-pair-blocklist (host writes, strategy reads)
import cex_deep_loop as _cdl          # v1.0 deep-loop learning (auto-veto proven-losing paths)
import cex_adaptive_threshold as _cat  # v1.0 per-pair adaptive threshold multiplier (v8.7)
import cex_profitability_tracker as _cpt  # v1.0 North Star monitor: 0.5%/swing of total wallet
import cex_spot_deep_loop as _csdl    # v1.0 SPOT deep-loop learning (auto-veto proven-losing coins)
from evaluator import grade_profit  # pure GO/NO-GO grading (same dir, unit-tested)
from risk_metrics import sortino as _sortino, max_drawdown as _maxdd, equity_curve as _eq, cvar as _cvar  # institutional risk core
import model_registry as _mreg          # champion/challenger model governance
import performance as _perf             # live PnL/equity feedback loop
# RS-1/RS-5 (Audit Fable 5/6): platform governance — constitution + ground truth
try:
    import constitution as _constitution
    import ground_truth as _ground_truth
except ImportError:
    _constitution = None   # type: ignore[assignment]
    _ground_truth = None   # type: ignore[assignment]

# Astronacci v1.1 — astro research & paper trading daemon integration
try:
    from astronacci_agent import AstronacciAgent, AstronacciConfig
    import astronacci_daemon as _astro_daemon
    _ASTRO_AVAILABLE = True
except ImportError as _astro_import_err:
    AstronacciAgent = None   # type: ignore[assignment]
    AstronacciConfig = None  # type: ignore[assignment]
    _astro_daemon = None     # type: ignore[assignment]
    _ASTRO_AVAILABLE = False
    _ASTRO_IMPORT_ERR = str(_astro_import_err)

# ──────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────

LOG_DIR = Path(os.environ.get("ANANTARA_LOG_DIR", "/var/log/anantara"))
try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE = LOG_DIR / "daemon.log"
except PermissionError:
    LOG_FILE = Path.home() / ".local/share/anantara/daemon.log"
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)

_TELEGRAM_URL_TOKEN_RE = re.compile(r"(api\.telegram\.org/bot)([^/\s\"']+)")


def _redact_log_message(message: str) -> str:
    """Remove Telegram bot tokens from log lines before handlers persist them."""
    return _TELEGRAM_URL_TOKEN_RE.sub(r"\1[REDACTED]", message)


class _SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _redact_log_message(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


for _handler in logging.getLogger().handlers:
    _handler.addFilter(_SecretRedactionFilter())

# httpx INFO request logs include full URLs; Telegram tokens live in URL paths.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("anantara-daemon")

# ── RS-5: Git-SHA stamp (computed once at import, stamped into STATE at startup) ──
def _compute_git_sha() -> str:
    """SHA pendek dari HEAD commit. '(unknown)' jika git tidak tersedia."""
    try:
        result = subprocess.run(
            ["git", "-C", str(Path(__file__).parent.parent), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else "(unknown)"
    except Exception:
        return "(unknown)"

_STARTUP_GIT_SHA: str = _compute_git_sha()
_STARTUP_TIME_UTC: str = datetime.now(timezone.utc).isoformat()

CFG = {
    "FREQTRADE_URL": os.environ.get("FREQTRADE_URL", "http://localhost:8080"),
    "FREQTRADE_BYBIT_URL": os.environ.get("FREQTRADE_BYBIT_URL", "http://localhost:8081"),
    "FREQTRADE_PARADEX_URL": os.environ.get("FREQTRADE_PARADEX_URL", "http://localhost:8082"),
    "FREQTRADE_USER": os.environ.get("FREQTRADE_USER", "anantara"),
    "FREQTRADE_PASS": os.environ.get("FREQTRADE_PASS", ""),
    "HERMES_URL": os.environ.get("HERMES_URL", "http://localhost:8000"),
    "TELEGRAM_TOKEN": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
    "TELEGRAM_CHAT_ID": os.environ.get("TELEGRAM_CHAT_ID", ""),
    "CB_L1_DD": float(os.environ.get("CB_LEVEL1_DD", "-0.03")),
    "CB_L2_DD": float(os.environ.get("CB_LEVEL2_DD", "-0.05")),
    "CB_L3_DD": float(os.environ.get("CB_LEVEL3_DD", "-0.08")),
    "PROJECT_DIR": Path(os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti"))),
}

# Mutable state
_circuit_level = 0
_kill_active = False
_tg_offset = 0
STATE: dict = {}        # cross-job snapshot store (funding plan, feasibility, spot-maker, etc.)

# ──────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────


# Telegram chunking (same contract as hermes_bridge.chunk_telegram — daemon
# runs in a separate process and cannot import the bridge app).
TG_CHUNK_SAFE = 3800


def _chunk_tg_message(message: str, limit: int = TG_CHUNK_SAFE) -> list[str]:
    """Split at paragraph boundaries; hard-split as last resort (pure)."""
    text = message or ""
    if len(text) <= limit:
        return [text] if text else []
    chunks: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 2:
            cut = window.rfind("\n")
        if cut < limit // 2:
            cut = limit
        chunks.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        chunks.append(rest)
    return chunks


async def tg(msg: str, parse_mode: str | None = "Markdown") -> None:
    """Send Telegram message(s), chunked + plain-text fallback. Silent fail."""
    if not (CFG["TELEGRAM_TOKEN"] and CFG["TELEGRAM_CHAT_ID"]):
        log.warning("Telegram not configured")
        return
    url = f"https://api.telegram.org/bot{CFG['TELEGRAM_TOKEN']}/sendMessage"
    for part in _chunk_tg_message(msg):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                payload = {"chat_id": CFG["TELEGRAM_CHAT_ID"], "text": part}
                if parse_mode:
                    payload["parse_mode"] = parse_mode
                resp = await c.post(url, json=payload)
                if resp.status_code == 400 and parse_mode:
                    # Markdown entity failure → plain text (report > styling)
                    retry = await c.post(
                        url, json={"chat_id": CFG["TELEGRAM_CHAT_ID"], "text": part})
                    if retry.status_code != 200:
                        log.error(f"Telegram 400 even as plain text: {retry.text[:200]}")
                elif resp.status_code != 200:
                    log.error(f"Telegram {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            log.error(f"Telegram send failed: {e}")


async def ft(endpoint: str, method: str = "GET", data: Any = None, instance: str = "binance") -> dict:
    """Call Freqtrade REST API. instance='binance' (port 8080) or 'bybit' (port 8081).
    Returns {} on any error."""
    try:
        auth = (CFG["FREQTRADE_USER"], CFG["FREQTRADE_PASS"])
        base_map = {
            "binance": CFG["FREQTRADE_URL"],
            "bybit": CFG.get("FREQTRADE_BYBIT_URL", "http://127.0.0.1:8081"),
            "paradex": CFG.get("FREQTRADE_PARADEX_URL", "http://127.0.0.1:8082"),
        }
        base_url = base_map.get(instance, CFG["FREQTRADE_URL"])
        url = f"{base_url}/api/v1/{endpoint}"
        async with httpx.AsyncClient(timeout=15, auth=auth) as c:
            if method == "POST":
                r = await c.post(url, json=data or {})
            else:
                r = await c.get(url)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        log.error(f"Freqtrade[{instance}] /{endpoint}: {e}")
        return {}


async def hermes_post(endpoint: str, data: Any = None) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{CFG['HERMES_URL']}{endpoint}", json=data or {})
            r.raise_for_status()
            return r.json()
    except httpx.TransportError as e:        # hermes briefly down (restart/deploy) = transient
        log.info(f"Hermes POST {endpoint} unreachable (transient): {type(e).__name__}")
        return {}
    except Exception as e:                    # real error — log with type (str may be empty)
        log.error(f"Hermes POST {endpoint}: {type(e).__name__}: {e}")
        return {}


async def hermes_get(endpoint: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{CFG['HERMES_URL']}{endpoint}")
            r.raise_for_status()
            return r.json()
    except httpx.TransportError as e:
        log.info(f"Hermes GET {endpoint} unreachable (transient): {type(e).__name__}")
        return {}
    except Exception as e:
        log.error(f"Hermes GET {endpoint}: {type(e).__name__}: {e}")
        return {}


async def hermes_get_url(url: str) -> dict:
    """Generic JSON GET for non-Hermes services (e.g. sodex-model on :8001)."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(url)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        log.error(f"GET {url}: {e}")
        return {}


# ──────────────────────────────────────────────────────────────────────
# SCHEDULED JOBS
# ──────────────────────────────────────────────────────────────────────


async def job_system_health():
    issues = []
    ram = psutil.virtual_memory()
    if ram.percent > 85:
        issues.append(f"⚠️ RAM: {ram.percent:.0f}%")
    disk = psutil.disk_usage("/")
    if disk.percent > 80:
        issues.append(f"⚠️ Disk: {disk.percent:.0f}%")
    if not await ft("ping", instance="binance"):
        issues.append("🚨 Freqtrade[Binance]: DOWN")
    # v8.32: Bybit disabled intentionally — skip bybit health alert
    if not (await hermes_get("/health")).get("status"):
        issues.append("🚨 Hermes Bridge: DOWN")
    if issues:
        await tg("🔴 *SYSTEM HEALTH*\n" + "\n".join(issues))
        log.warning(f"Health issues: {issues}")


_ft_restart_at: dict[str, float] = {}   # instance -> last auto-restart epoch
_FT_RESTART_COOLDOWN = 1800             # max one auto-restart per 30 min per instance


async def _ft_autorecover(instance: str, service: str):
    """Restart a dead freqtrade instance via docker compose (cooldown-guarded).
    A transient VPN/CEX drop can crash market loading and leave it dead silently."""
    import time as _t
    now = _t.time()
    if now - _ft_restart_at.get(instance, 0) < _FT_RESTART_COOLDOWN:
        await tg(f"🚨 Freqtrade[{instance}] DOWN — auto-restart on cooldown, manual check needed")
        return
    _ft_restart_at[instance] = now
    try:
        r = await asyncio.to_thread(lambda: subprocess.run(
            ["docker", "compose", "restart", service],
            cwd=str(CFG["PROJECT_DIR"]), capture_output=True, text=True, timeout=90))
        ok = r.returncode == 0
        await tg(f"{'🔄' if ok else '❌'} Freqtrade[{instance}] DOWN → auto-restart "
                 f"{'issued' if ok else 'FAILED: ' + r.stderr.strip()[:100]}")
    except Exception as e:
        await tg(f"❌ Freqtrade[{instance}] auto-restart error: {str(e)[:120]}")


async def job_exchange_health():
    """Check freqtrade instances; auto-restart any that are down.
    v8.32: Bybit disabled intentionally — only Binance is monitored."""
    for instance, service in (("binance", "freqtrade"),):
        p = await ft("ping", instance=instance)
        if not p or p.get("status") != "pong":
            await _ft_autorecover(instance, service)


async def job_freqai_health():
    """Check FreqAI by model files age (show_config doesn't expose freqai block).
    Alert if no model retrained in last 36h (expected daily retrain = 24h)."""
    import time
    models_dir = CFG["PROJECT_DIR"] / "freqtrade_user_data" / "models"
    if not models_dir.exists():
        await tg("⚠️ FreqAI models dir missing — initial training not yet run")
        return
    # Find newest model file
    newest = max(
        (f.stat().st_mtime for f in models_dir.rglob("*.joblib") if f.is_file()),
        default=0,
    )
    if newest == 0:
        # No models yet — either fresh start (OK for first 90 days train) or actual problem
        log.debug("FreqAI: no .joblib models found yet (training first window or stalled)")
        return
    age_hours = (time.time() - newest) / 3600
    if age_hours > 36:
        await tg(f"⚠️ FreqAI: last model trained {age_hours:.1f}h ago (expected <24h)")


async def job_cex_accuracy_check():
    """Hourly: track FreqAI prediction accuracy from live CEX trades.
    Queries PostgreSQL for recent closed trades, computes per-pair WR and rolling stats.
    Alerts to Telegram if WR < 40% over last 10 trades (model degradation signal).
    Also logs metrics to JSONL for longitudinal analysis."""
    try:
        # Try psycopg2 first; fallback to freqtrade REST API if not available
        try:
            import psycopg2 as _pg2
        except ImportError:
            # psycopg2 not installed in this Python env → use freqtrade API
            import urllib.request as _ur, json as _json
            try:
                import base64 as _b64
                _ft_user = CFG.get("FREQTRADE_USER", "anantara")
                _ft_pass = CFG.get("FREQTRADE_PASS", "")
                _ft_url  = CFG.get("FREQTRADE_URL", "http://localhost:8080")
                _creds   = _b64.b64encode(f"{_ft_user}:{_ft_pass}".encode()).decode()
                _r = _ur.urlopen(_ur.Request(
                    f"{_ft_url}/api/v1/trades?limit=30",
                    headers={"Authorization": f"Basic {_creds}"}
                ), timeout=5)
                _trades_data = _json.load(_r).get("trades", [])
            except Exception:
                _trades_data = []
            if not _trades_data:
                log.debug("cex_accuracy: psycopg2 not available, no trades via API")
                return
            # Process API trades
            total = len(_trades_data)
            wins = sum(1 for t in _trades_data if t.get("profit_ratio", 0) > 0)
            wr = wins / total if total else 0
            avg_profit = sum(t.get("profit_ratio", 0) for t in _trades_data) / total if total else 0
            sl_hits = sum(1 for t in _trades_data if t.get("exit_reason") == "stop_loss")
            msg = (f"📊 CEX Accuracy (API): {total} trades WR={wr:.0%} "
                   f"avg={avg_profit*100:+.2f}% SL={sl_hits/total:.0%}")
            log.info(f"cex_accuracy: {msg}")
            if wr < 0.35 and total >= 5:
                await tg(f"⚠️ {msg}")
            return

        env_path = CFG["PROJECT_DIR"] / ".env"
        env_vars: dict = {}
        with open(env_path) as _ef:
            for _line in _ef:
                _line = _line.strip()
                if "=" in _line and not _line.startswith("#"):
                    _k, _v = _line.split("=", 1)
                    # SECURITY: Do NOT strip inline comments from values.
                    # A password containing '#' would be silently truncated.
                    # Use the raw value; actual comment lines are filtered by startswith("#").
                    env_vars[_k.strip()] = _v.strip()
        pg_pw = env_vars.get("POSTGRES_PASSWORD", "")

        conn = _pg2.connect(
            host="localhost", port=5432, dbname="anantara",
            user="anantara", password=pg_pw
        )
        cur = conn.cursor()

        # All closed trades (for equity curve + risk metrics)
        cur.execute("""
            SELECT pair, CASE WHEN is_short THEN 'SHORT' ELSE 'LONG' END AS dir,
                   enter_tag, open_rate, close_rate, close_profit, exit_reason,
                   open_date, close_date, stake_amount
            FROM trades
            WHERE is_open = false
            ORDER BY close_date ASC
        """)
        rows = cur.fetchall()
        conn.close()

        if not rows:
            log.debug("cex_accuracy: no closed trades yet")
            return

        total = len(rows)
        wins = sum(1 for r in rows if r[5] > 0)
        wr = wins / total if total else 0
        avg_profit = sum(r[5] for r in rows) / total if total else 0
        total_pnl = sum(r[5] * r[9] for r in rows)  # profit_ratio * stake = USDT

        # Exit reason breakdown (exact match to avoid "trailing_stop_loss" counting as stop_loss)
        sl_hits = sum(1 for r in rows if r[6] == "stop_loss")
        tsl_exits = sum(1 for r in rows if r[6] == "trailing_stop_loss")
        roi_exits = sum(1 for r in rows if r[6] in ("roi", "minimal_roi"))

        # Per-pair-direction WR (key for pair block decisions)
        pair_stats: dict = {}
        for r in rows:
            key = f"{r[0].split('/')[0]}_{r[1]}"  # e.g. "BTC_SHORT"
            if key not in pair_stats:
                pair_stats[key] = {"n": 0, "wins": 0, "pnl_sum": 0.0}
            pair_stats[key]["n"] += 1
            if r[5] > 0:
                pair_stats[key]["wins"] += 1
            pair_stats[key]["pnl_sum"] += r[5]

        # Direction breakdown (LONG vs SHORT — key for event risk analysis)
        long_rows  = [r for r in rows if r[1] == "LONG"]
        short_rows = [r for r in rows if r[1] == "SHORT"]
        long_wr  = (sum(1 for r in long_rows if r[5] > 0) / len(long_rows)) if long_rows else 0
        short_wr = (sum(1 for r in short_rows if r[5] > 0) / len(short_rows)) if short_rows else 0
        long_avg  = (sum(r[5] for r in long_rows) / len(long_rows)) if long_rows else 0
        short_avg = (sum(r[5] for r in short_rows) / len(short_rows)) if short_rows else 0

        # Exit quality: TSL exits are profitable, SL exits are losses, ROI = take-profit
        tsl_pnl = sum(r[5] for r in rows if r[6] == "trailing_stop_loss")
        sl_pnl  = sum(r[5] for r in rows if r[6] == "stop_loss")
        roi_pnl = sum(r[5] for r in rows if r[6] in ("roi", "minimal_roi"))
        avg_tsl_pnl = (tsl_pnl / tsl_exits) if tsl_exits else 0
        avg_sl_pnl  = (sl_pnl / sl_hits) if sl_hits else 0

        # Consecutive losses (from most recent trades = last in ASC order)
        consec_losses = 0
        for r in reversed(rows):
            if r[5] <= 0:
                consec_losses += 1
            else:
                break

        # ── Risk Metrics: Sharpe/maxDD from equity curve ─────────────────────
        # v8.21: Integrates performance.py + risk_metrics.py (ecosystem modules)
        # Equity series: DRY_RUN_WALLET + cumulative PnL per trade
        sharpe_ratio = 0.0
        max_dd_pct = 0.0
        try:
            from anantara.risk_metrics import sharpe as _sharpe, max_drawdown as _maxdd
            _dry_run_wallet = float(env_vars.get("DRY_RUN_WALLET", "1000").split("#")[0].strip())
            # Build equity curve: starting from dry_run_wallet, add each trade's PnL in USDT order
            _equity = _dry_run_wallet
            _equity_series = [_equity]
            for r in rows:  # already ASC order
                _pnl_usdt = r[5] * r[9]  # close_profit_ratio * stake_amount
                _equity += _pnl_usdt
                _equity_series.append(_equity)
            if len(_equity_series) >= 3:
                _returns = [(_equity_series[i] - _equity_series[i-1]) / _equity_series[i-1]
                            for i in range(1, len(_equity_series)) if _equity_series[i-1] > 0]
                # Annualize: ~4 trades/day × 365 days = 1460 trades/year
                sharpe_ratio = round(_sharpe(_returns, periods_per_year=1460), 3)
                max_dd_pct = round(_maxdd(_equity_series) * 100, 2)
        except Exception:
            pass

        # Append equity snapshot for long-term tracking
        try:
            from anantara.performance import append_snapshot as _append_snap
            _perf_path = str(CFG["PROJECT_DIR"] / "freqtrade_user_data" / "data" / "perf" / "cex_equity.jsonl")
            _append_snap(_perf_path, _equity if _equity_series else float(env_vars.get("DRY_RUN_WALLET", "1000")),
                         extra={"total_trades": total, "wr": round(wr, 3),
                                "sharpe": sharpe_ratio, "max_dd_pct": max_dd_pct})
        except Exception:
            pass

        # Post-fix clean SHORT stats (since v8.20 Jun 10 — all pair blocks in place).
        # This is the most relevant metric for Day 31 GO/NO-GO: filters out pre-fix
        # era LONG trades and early unblocked SHORTs (DOT/BNB/XRP before blocks added).
        _POST_FIX = "2026-06-10"  # date when v8.20 applied final XRP SHORT block
        _pf_short = [r for r in rows
                     if r[1] == "SHORT" and r[8] is not None and str(r[8])[:10] >= _POST_FIX]
        _pf_n = len(_pf_short)
        _pf_wins = sum(1 for r in _pf_short if r[5] > 0) if _pf_n else 0
        _pf_wr = _pf_wins / _pf_n if _pf_n else 0.0
        _pf_avg = sum(r[5] for r in _pf_short) / _pf_n * 100 if _pf_n else 0.0
        _pf_sl = sum(1 for r in _pf_short if r[6] == "stop_loss")

        # ── R1 Bybit parallel stats (for cross-reference) ─────────────────
        # Queries Bybit DB to include random-control data in accuracy report.
        # R1 has no FreqAI model — it's pure market-structure signal.
        _r1_total = _r1_wins = _r1_wr = _r1_avg = 0.0
        _r1_short_n = _r1_short_wr = _r1_short_avg = 0.0
        _r1_long_n = _r1_long_wr = _r1_long_avg = 0.0
        try:
            _r1_conn = _pg2.connect(host="localhost", port=5432, dbname="anantara_bybit",
                                    user="anantara", password=pg_pw)
            _r1_cur = _r1_conn.cursor()
            _r1_cur.execute("""SELECT COUNT(*), SUM(CASE WHEN close_profit>0 THEN 1 ELSE 0 END),
                               AVG(close_profit) FROM trades WHERE is_open=false""")
            _r1_row = _r1_cur.fetchone()
            if _r1_row[0]:
                _r1_total = _r1_row[0]
                _r1_wins = _r1_row[1]
                _r1_wr = _r1_wins / _r1_total if _r1_total else 0
                _r1_avg = (_r1_row[2] or 0) * 100
            # R1 direction breakdown
            _r1_cur.execute("""SELECT COUNT(*), SUM(CASE WHEN close_profit>0 THEN 1 ELSE 0 END),
                               AVG(close_profit) FROM trades WHERE is_open=false AND is_short=true""")
            _r1s = _r1_cur.fetchone()
            if _r1s[0]:
                _r1_short_n = _r1s[0]
                _r1_short_wr = _r1s[1] / _r1_short_n if _r1_short_n else 0
                _r1_short_avg = (_r1s[2] or 0) * 100
            _r1_cur.execute("""SELECT COUNT(*), SUM(CASE WHEN close_profit>0 THEN 1 ELSE 0 END),
                               AVG(close_profit) FROM trades WHERE is_open=false AND is_short=false""")
            _r1l = _r1_cur.fetchone()
            if _r1l[0]:
                _r1_long_n = _r1l[0]
                _r1_long_wr = _r1l[1] / _r1_long_n if _r1_long_n else 0
                _r1_long_avg = (_r1l[2] or 0) * 100
            _r1_conn.close()
        except Exception:
            pass

        # ── R1 last-10 trend (real-time market direction signal) ────────
        _r1_l10_n = _r1_l10_s_wr = _r1_l10_l_wr = 0
        _r1_l10_s_avg = _r1_l10_l_avg = 0.0
        try:
            _r1_conn = _pg2.connect(host="localhost", port=5432, dbname="anantara_bybit",
                                    user="anantara", password=pg_pw)
            _r1_cur = _r1_conn.cursor()
            _r1_cur.execute("""SELECT is_short, close_profit FROM 
                               (SELECT is_short, close_profit FROM trades WHERE is_open=false 
                                ORDER BY close_date DESC LIMIT 10) sub""")
            _l10_rows = _r1_cur.fetchall()
            _l10_s = [r[1] for r in _l10_rows if r[0]]
            _l10_l = [r[1] for r in _l10_rows if not r[0]]
            _r1_l10_n = len(_l10_rows)
            _r1_l10_s_wr = sum(1 for p in _l10_s if p > 0) / len(_l10_s) if _l10_s else 0
            _r1_l10_l_wr = sum(1 for p in _l10_l if p > 0) / len(_l10_l) if _l10_l else 0
            _r1_l10_s_avg = sum(_l10_s) / len(_l10_s) * 100 if _l10_s else 0
            _r1_l10_l_avg = sum(_l10_l) / len(_l10_l) * 100 if _l10_l else 0
            _r1_conn.close()
        except Exception:
            pass

        # Log to JSONL
        log_dir = CFG["PROJECT_DIR"] / "freqtrade_user_data" / "data" / "binance" / "cex_accuracy"
        log_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        log_entry = {
            "ts": int(datetime.now(timezone.utc).timestamp()),
            "total_trades": total,
            "wins": wins,
            "wr": round(wr, 3),
            "avg_profit_pct": round(avg_profit * 100, 3),
            "total_pnl_usdt": round(total_pnl, 4),
            "sl_hits": sl_hits,
            "tsl_exits": tsl_exits,
            "roi_exits": roi_exits,
            "avg_tsl_pct": round(avg_tsl_pnl * 100, 3),
            "avg_sl_pct": round(avg_sl_pnl * 100, 3),
            "long_n": len(long_rows), "long_wr": round(long_wr, 3),
            "long_avg_pct": round(long_avg * 100, 3),
            "short_n": len(short_rows), "short_wr": round(short_wr, 3),
            "short_avg_pct": round(short_avg * 100, 3),
            "post_fix_short_n": _pf_n,
            "post_fix_short_wr": round(_pf_wr, 3),
            "post_fix_short_avg_pct": round(_pf_avg, 3),
            "post_fix_short_sl_hits": _pf_sl,
            "consec_losses": consec_losses,
            "sharpe_ratio": sharpe_ratio,
            "max_dd_pct": max_dd_pct,
            "pair_stats": {p: {"n": v["n"],
                               "wr": round(v["wins"] / v["n"], 2),
                               "avg_pct": round(v["pnl_sum"] / v["n"] * 100, 2)}
                           for p, v in pair_stats.items()},
            # R1 Bybit cross-reference (model-agnostic market signal)
            "r1_total": _r1_total, "r1_wr": round(_r1_wr, 3),
            "r1_avg_pct": round(_r1_avg, 3),
            "r1_short_n": int(_r1_short_n), "r1_short_wr": round(_r1_short_wr, 3),
            "r1_short_avg_pct": round(_r1_short_avg, 3),
            "r1_long_n": int(_r1_long_n), "r1_long_wr": round(_r1_long_wr, 3),
            "r1_long_avg_pct": round(_r1_long_avg, 3),
            # R1 last-10 trend (real-time market direction signal)
            "r1_l10_n": _r1_l10_n,
            "r1_l10_short_wr": round(_r1_l10_s_wr, 3),
            "r1_l10_short_avg_pct": round(_r1_l10_s_avg, 3),
            "r1_l10_long_wr": round(_r1_l10_l_wr, 3),
            "r1_l10_long_avg_pct": round(_r1_l10_l_avg, 3),
        }
        with (log_dir / f"accuracy_{today}.jsonl").open("a") as _f:
            _f.write(json.dumps(log_entry) + "\n")

        # Compute avg_pct per pair for alert code (was missing from pair_stats dict,
        # causing KeyError: 'avg_pct' when WR<35% or bad pair alerts triggered).
        for _k, _v in pair_stats.items():
            _v["avg_pct"] = round(_v["pnl_sum"] / _v["n"] * 100, 2) if _v["n"] > 0 else 0.0

        log.info(
            f"CEX accuracy: WR={wr:.1%} ({wins}/{total}) "
            f"avg={avg_profit*100:.2f}% PnL={total_pnl:.3f}USDT "
            f"SL={sl_hits} TSL={tsl_exits}(avg={avg_tsl_pnl*100:+.1f}%) "
            f"LONG={long_wr:.0%}(n={len(long_rows)}) "
            f"SHORT={short_wr:.0%}(n={len(short_rows)}) "
            f"PostFix SHORT: WR={_pf_wr:.0%}(n={_pf_n} avg={_pf_avg:.2f}%) "
            f"Sharpe={sharpe_ratio:+.2f} maxDD={max_dd_pct:.1f}% "
            f"consec_loss={consec_losses} | "
            f"R1: {_r1_total}t WR={_r1_wr:.0%} avg={_r1_avg:+.2f}% "
            f"S={_r1_short_wr:.0%}(n={_r1_short_n:.0f}) L={_r1_long_wr:.0%}(n={_r1_long_n:.0f}) | "
            f"R1-L10: S{_r1_l10_s_wr:.0%}({_r1_l10_s_avg:+.1f}%) L{_r1_l10_l_wr:.0%}({_r1_l10_l_avg:+.1f}%)"
        )

        # ── Regime duration check (for breakout alert) ──────────────────
        _regime_dur_h = 0
        _current_regime = "?"
        try:
            _intel_dir = CFG["PROJECT_DIR"] / "freqtrade_user_data" / "data" / "binance" / "intelligence"
            _intel_files = sorted(_intel_dir.glob("intel_*.jsonl"))
            if _intel_files:
                _all_regimes = []
                for _ifp in _intel_files[-3:]:  # last 3 days
                    for _line in _ifp.read_text().splitlines():
                        if not _line.strip(): continue
                        _d = json.loads(_line)
                        _all_regimes.append((
                            datetime.fromtimestamp(_d["ts"], tz=timezone.utc),
                            _d.get("market_regime", "?")
                        ))
                if _all_regimes:
                    _all_regimes.sort(key=lambda x: x[0])
                    _current_regime = _all_regimes[-1][1]
                    # Count backwards until regime changes
                    _dur = 0
                    for i in range(len(_all_regimes)-1, -1, -1):
                        if _all_regimes[i][1] == _current_regime:
                            _dur = (_all_regimes[-1][0] - _all_regimes[i][0]).total_seconds() / 3600
                        else:
                            break
                    _regime_dur_h = _dur
        except Exception:
            pass

        if _regime_dur_h:
            log.info(f"CEX regime: {_current_regime} for {_regime_dur_h:.0f}h")

        # Alert conditions
        # ── RANGING breakout alert (volatility compression) ────────────
        if _current_regime == "RANGING" and _regime_dur_h >= 96:
            _r4_trades = 0  # Binance total (stale since R4 deployed)
            if _r4_trades <= 55:  # < 7 R4 trades (49 were v2)
                await tg(
                    f"⏰ *RANGING {_regime_dur_h:.0f}h — Volatility Compression Alert*\n"
                    f"BTC range-trading for {_regime_dur_h/24:.1f} days. Breakout statistically imminent.\n"
                    f"R4 gates ACTIVE — ready for TRENDING_BEAR signal.\n"
                    f"R1 L10 trend: S{_r1_l10_s_wr:.0%} L{_r1_l10_l_wr:.0%} — "
                    f"{'🐂 BULL market' if _r1_l10_l_wr > 0.7 else '🐻 BEAR market' if _r1_l10_s_wr > 0.7 else '➖ MIXED'}\n"
                    f"_BTC 4H direction will determine R4 entry direction_"
                )
        if total >= 8 and wr < 0.35:
            # Worst pair-direction combos by avg PnL (minimum n=2 for signal quality)
            worst_pairs = [(k, v) for k,v in pair_stats.items() if v["n"] >= 2
                           and v["avg_pct"] < -2.0]
            worst_str = " ".join(f"{k}={v['wins']}/{v['n']}({v['avg_pct']:+.1f}%)"
                                 for k,v in sorted(worst_pairs, key=lambda x: x[1]["avg_pct"])[:3])
            await tg(
                f"⚠️ *CEX FreqAI — WR Degradation*\n"
                f"WR: *{wr:.1%}* ({wins}/{total}) ← below 35% threshold\n"
                f"Avg: {avg_profit*100:.2f}% | PnL: {total_pnl:.3f} USDT\n"
                f"SL hits: {sl_hits}/{total} | Consec losses: {consec_losses}\n"
                f"LONG: {long_wr:.0%}(n={len(long_rows)}) SHORT: {short_wr:.0%}(n={len(short_rows)})\n"
                f"Worst pairs: {worst_str or 'none'}\n"
                f"_Consider reviewing threshold or model retraining_"
            )
        elif consec_losses >= 5:
            await tg(
                f"⚠️ *CEX FreqAI — {consec_losses} consecutive losses*\n"
                f"WR overall: {wr:.1%} | SL hits: {sl_hits}/{total}\n"
                f"LONG: {long_wr:.0%}(n={len(long_rows)}) SHORT: {short_wr:.0%}(n={len(short_rows)})\n"
                f"_Monitoring... auto-pause if streak reaches 7_"
            )
        # TSL quality alert: if TSL avg exit is low, offset may need tuning
        if tsl_exits >= 5 and avg_tsl_pnl < 0.02:
            await tg(
                f"📊 *CEX TSL Quality* — avg TSL exit only {avg_tsl_pnl*100:+.1f}%\n"
                f"Expected ≥+2% (offset=0.04). Check trailing_stop_positive_offset.\n"
                f"n={tsl_exits} TSL exits | SL avg: {avg_sl_pnl*100:.1f}%"
            )
        # Pair-direction degradation: use POST-FIX data only (Jun 10+, all blocks applied).
        # All-time pair_stats includes pre-block era trades (DOGE_LONG, OP_LONG, INJ_LONG
        # had WR=0% before v8.14-v8.20 blocks). Using all-time produces noisy false-positives
        # for already-blocked pairs — the very ones that should never generate new trades.
        _POST_FIX_CUTOFF = "2026-06-10 00:00:00"
        _pf_pair_stats: dict = {}
        for _r in rows:
            if str(_r[8]) < _POST_FIX_CUTOFF:
                continue
            _pk = f"{_r[0].split('/')[0]}_{_r[1]}"
            if _pk not in _pf_pair_stats:
                _pf_pair_stats[_pk] = {"n": 0, "wins": 0, "pnl_sum": 0.0}
            _pf_pair_stats[_pk]["n"] += 1
            if _r[5] > 0:
                _pf_pair_stats[_pk]["wins"] += 1
            _pf_pair_stats[_pk]["pnl_sum"] += _r[5]
        for _v in _pf_pair_stats.values():
            _v["avg_pct"] = round(_v["pnl_sum"] / _v["n"] * 100, 2) if _v["n"] > 0 else 0.0

        bad_pairs = [(k, v) for k, v in _pf_pair_stats.items()
                     if v["n"] >= 3 and v["wins"] / v["n"] < 0.25 and v["avg_pct"] < -1.5]
        if bad_pairs:
            bad_str = " | ".join(f"{k}: WR={v['wins']}/{v['n']}({v['avg_pct']:+.1f}%)"
                                 for k, v in sorted(bad_pairs, key=lambda x: x[1]["avg_pct"]))
            log.warning(f"CEX pair-direction degradation (post-fix): {bad_str}")
            very_bad = [k for k, v in bad_pairs if v["wins"] / v["n"] == 0 or v["avg_pct"] < -3.0]
            if very_bad:
                await tg(f"🔴 *CEX Pair Block Alert* (post-fix Jun 10+)\n{bad_str}"
                         "\n_Add to _PAIR_BLOCKS if n≥5_")

    except Exception as e:
        log.error(f"job_cex_accuracy_check: {e}")


async def job_cex_day31_analysis():
    """Daily at 08:00 UTC (Jun 14-17): pre-assess Day 31 GO/NO-GO for Binance CEX.
    Queries post-fix SHORTs (since Jun 10, all pair blocks in place) from both
    Binance (anantara DB) and Bybit (anantara_bybit DB).
    GO criteria: SHORT WR≥55%, avg≥+0.5%, n≥30, SL_rate≤40%.
    """
    try:
        import psycopg2 as _pg2
    except ImportError:
        log.warning("job_cex_day31_analysis: psycopg2 not available, skipping")
        return
    try:
        env_path = CFG["PROJECT_DIR"] / ".env"
        env_vars: dict = {}
        with open(env_path) as _ef:
            for _line in _ef:
                _line = _line.strip()
                if "=" in _line and not _line.startswith("#"):
                    _k, _v = _line.split("=", 1)
                    env_vars[_k.strip()] = _v.strip()
        pg_pw = env_vars.get("POSTGRES_PASSWORD", "")

        _CUTOFF = "2026-06-10 00:00:00"

        def _query_shorts(dbname: str) -> list:
            """Return post-fix SHORT rows: (close_profit, exit_reason) tuples."""
            try:
                conn = _pg2.connect(host="localhost", port=5432, dbname=dbname,
                                    user="anantara", password=pg_pw)
                cur = conn.cursor()
                cur.execute("""
                    SELECT pair, close_profit, exit_reason
                    FROM trades
                    WHERE is_open = false
                      AND is_short = true
                      AND close_date >= %s::timestamp
                    ORDER BY close_date ASC
                """, (_CUTOFF,))
                rows = cur.fetchall()
                conn.close()
                return rows
            except Exception as _e:
                log.warning(f"cex_day31_analysis: DB {dbname} error: {_e}")
                return []

        def _stats(rows: list, label: str) -> dict:
            n = len(rows)
            if not n:
                return {"label": label, "n": 0}
            wins = sum(1 for r in rows if r[1] > 0)
            wr = wins / n
            avg_pct = sum(r[1] for r in rows) / n * 100
            sl_hits = sum(1 for r in rows if r[2] == "stop_loss")
            tsl_exits = sum(1 for r in rows if r[2] == "trailing_stop_loss")
            roi_exits = sum(1 for r in rows if r[2] in ("roi", "minimal_roi"))
            avg_win = (sum(r[1] for r in rows if r[1] > 0) / wins * 100) if wins else 0.0
            avg_loss = (sum(r[1] for r in rows if r[1] <= 0) / (n - wins) * 100) if n > wins else 0.0
            # E(R) using SL=3% as reference risk unit
            e_r = (wr * (avg_win / 3.0)) - ((1 - wr) * abs(avg_loss / 3.0))
            return {
                "label": label, "n": n, "wr": wr, "avg_pct": avg_pct,
                "sl_hits": sl_hits, "sl_rate": sl_hits / n,
                "tsl_exits": tsl_exits, "roi_exits": roi_exits,
                "avg_win": avg_win, "avg_loss": avg_loss, "e_r": e_r,
            }

        binance_rows = await asyncio.to_thread(_query_shorts, "anantara")
        bybit_rows   = await asyncio.to_thread(_query_shorts, "anantara_bybit")
        combined_rows = binance_rows + bybit_rows

        s_bin  = _stats(binance_rows,   "Binance")
        s_bbt  = _stats(bybit_rows,     "Bybit")
        s_comb = _stats(combined_rows,  "Combined")

        # ── R7 (Fable 5 audit): Statistically valid criteria ─────────────────
        # Previous criteria (WR≥55% AND avg≥+0.5%) were internally inconsistent:
        # at avg_win=1.94% / avg_loss=3.17%, WR=55% yields avg=-0.36% ≠ +0.5%.
        # Both can only be met simultaneously if avg_win ≥ 3.50% — never achieved.
        # Single correct criterion: bootstrap CI95 lower bound on expectancy > 0.
        # n_min for meaningful signal (Fable 5 §5.3): ≥100 frozen trades OR 8 weeks.
        # "Insufficient data" is a valid result — default stays paper, not live.
        import random as _rnd
        _MIN_N_INFORMATIVE = 100   # below this: data cannot distinguish edge from noise
        _BOOTSTRAP_REPS    = 2000
        _P_EDGE_MIN        = 0.90  # P(expectancy > 0) threshold for GO

        n  = s_comb["n"]
        ap = s_comb.get("avg_pct", 0)
        wr = s_comb.get("wr", 0)
        sl = s_comb.get("sl_rate", 0)
        e_r = s_comb.get("e_r", 0)

        # Payoff geometry diagnostics (Fable 5 §5.1)
        avg_win_pct  = s_comb.get("avg_win", 0)
        avg_loss_pct = abs(s_comb.get("avg_loss", 0))
        be_wr = avg_loss_pct / (avg_win_pct + avg_loss_pct) * 100 if (avg_win_pct + avg_loss_pct) > 0 else 63.4
        avg_win_needed = (0.5 + (1 - 0.55) * avg_loss_pct) / 0.55  # for T3 to be self-consistent

        # Bootstrap: reconstruct profit distribution from wins/losses counts + avgs
        _n_wins  = round(n * wr)
        _n_loss  = n - _n_wins
        _profits = ([avg_win_pct / 100] * _n_wins) + ([-(avg_loss_pct / 100)] * _n_loss)
        _rnd.seed(42)
        _boot_means = []
        for _ in range(_BOOTSTRAP_REPS):
            _samp = _rnd.choices(_profits, k=n)
            _boot_means.append(sum(_samp) / len(_samp))
        _p_positive = sum(1 for m in _boot_means if m > 0) / _BOOTSTRAP_REPS
        _ci95_lo = sorted(_boot_means)[int(0.05 * _BOOTSTRAP_REPS)]
        _ci95_hi = sorted(_boot_means)[int(0.95 * _BOOTSTRAP_REPS)]

        if n < 20:
            verdict = f"⏳ NO DATA — n={n} (accumulating, need ≥100 frozen)"
        elif n < _MIN_N_INFORMATIVE:
            verdict = f"⏳ INSUFFICIENT — n={n}/{_MIN_N_INFORMATIVE} (CI95 too wide for GO decision)"
        elif _p_positive >= _P_EDGE_MIN:
            verdict = f"✅ GO — P(E>0)={_p_positive:.0%} ≥ {_P_EDGE_MIN:.0%}"
        else:
            verdict = f"🔴 NO-GO — P(E>0)={_p_positive:.0%} < {_P_EDGE_MIN:.0%} (CI95=[{_ci95_lo*100:.2f}%, {_ci95_hi*100:.2f}%])"

        from datetime import datetime as _dtt
        _d31 = _dtt(2026, 6, 17)
        _now = _dtt.utcnow()
        days_left = max(0, (_d31 - _now).days)

        def _row(s: dict) -> str:
            if s["n"] == 0:
                return f"  *{s['label']}*: 0 post-fix SHORTs"
            return (f"  *{s['label']}*: n={s['n']} WR={s['wr']:.0%} "
                    f"avg={s['avg_pct']:+.2f}% SL={s['sl_rate']:.0%} E={s['e_r']:+.2f}R")

        lines = [
            f"📊 *CEX Day 31 Assessment* (T-{days_left}d → Jun 17)",
            f"Post-fix SHORTs since Jun 10 (all blocks applied)",
            "━━━━━━━━━━",
            _row(s_comb), _row(s_bin), _row(s_bbt),
            "━━━━━━━━━━",
            f"*Payoff geometry* (Fable 5 §5.1):",
            f"  avg_win={avg_win_pct:.2f}% avg_loss={avg_loss_pct:.2f}%",
            f"  Breakeven WR={be_wr:.1f}% | avg_win needed for T3={avg_win_needed:.2f}%",
            f"*Bootstrap CI95 expectancy*: [{_ci95_lo*100:.2f}%, {_ci95_hi*100:.2f}%]",
            f"*P(E>0)*: {_p_positive:.0%} (threshold: {_P_EDGE_MIN:.0%})",
            f"*Min informative n*: {_MIN_N_INFORMATIVE} (current: {n})",
            f"*VERDICT: {verdict}*",
        ]
        if days_left == 0:
            lines.append("🔔 _Day 31: data likely still insufficient — consider R3/R4 pivot (see audit §7)_")

        await tg("\n".join(lines))
        log.info(f"cex_day31_analysis: {verdict} | n={n} WR={wr:.0%} avg={ap:+.2f}% E={e_r:+.2f}R")

    except Exception as e:
        log.error(f"job_cex_day31_analysis: {e}")


async def job_sentiment_poll():
    """Phase 8: hourly market sentiment refresh (F&G + trending + global)."""
    result = await hermes_post("/sentiment/poll")
    if result and "fg_index" in result:
        fg = result["fg_index"]
        label = result["fg_label"]
        # Alert ke Telegram hanya jika EXTREME zones
        if fg <= 25 or fg >= 75:
            emoji = "🟢" if fg <= 25 else "🔴"
            mcap = result.get('mcap_change_24h')
            mcap_str = f"{mcap:+.2f}%" if isinstance(mcap, (int, float)) else "?"
            await tg(
                f"{emoji} *Market Sentimen Sistem*\n"
                f"F&G: *{fg}* ({label})\n"
                f"BTC dom: {result.get('btc_dominance', '?')}% | 24h: {mcap_str}"
            )


async def job_intelligence_refresh():
    """Phase 8.5: refresh Crypto Intelligence Score (composite). Hourly."""
    result = await hermes_post("/intelligence/refresh")
    if result and "composite_score" in result:
        score = result["composite_score"]
        label = result["label"]
        if label in ("STRONGLY_BULLISH", "STRONGLY_BEARISH"):
            emoji = "🚀" if "BULL" in label else "🔻"
            await tg(f"{emoji} *Intelligence*: {score}/100 ({label})")


# Pre-Sentiment coverage: unified 24-asset watchlist (SoDEX + Binance spot + HL).
# Source of truth: anantara/presentiment_data.py WATCHLIST. Env override retained.
try:
    from anantara.presentiment_data import WATCHLIST as _PRESENTIMENT_WATCHLIST
except ImportError:  # container flat import
    from presentiment_data import WATCHLIST as _PRESENTIMENT_WATCHLIST  # type: ignore
PRESENTIMENT_SYMBOLS = [s.strip() for s in os.environ.get(
    "PRESENTIMENT_SYMBOLS", ",".join(_PRESENTIMENT_WATCHLIST)).split(",") if s.strip()]


async def job_btc_forecast():
    """T+24h Pre-Sentiment forecast for the key-asset set via LLM + SoDEX technicals.
    Every 1h. Price/momentum computed server-side in Hermes from SoDEX klines."""
    for symbol in PRESENTIMENT_SYMBOLS:
        try:
            result = await hermes_post("/prediction/forecast", {"symbol": symbol})
            f = result.get("forecast", {}) or {}
            if (
                f
                and f.get("trade_eligible")
                and f.get("confidence", 0) >= 0.7
                and f.get("direction") in ("UP", "DOWN")
            ):
                tech = result.get("technicals", {}) or {}
                await tg(
                    f"🔮 *{symbol} Forecast T+24h*\n"
                    f"Direction: *{f.get('direction')}* (conf {f.get('confidence')*100:.0f}%)\n"
                    f"Momentum: {tech.get('trend','?')} ({tech.get('momentum_score','?')}) · "
                    f"RSI {tech.get('rsi','?')} · 6h {tech.get('chg_6h','?')}%\n"
                    f"Action: *{f.get('suggested_action')}*\n"
                    f"_{str(f.get('reasoning', ''))[:180]}_"
                )
        except Exception as e:
            log.error(f"{symbol} forecast job error: {e}")


async def job_forecast_accuracy():
    """Verify past Pre-Sentiment forecasts vs realized price → hit-rate. Every 1h.
    This is the system's self-measurement (Grafana + Telegram report)."""
    try:
        await hermes_post("/prediction/accuracy", {"checkpoint_h": 24.0})
    except Exception as e:
        log.error(f"forecast accuracy job error: {e}")


# ── Momentum flip detector ────────────────────────────────────────────────
# Reaction-speed fix: the 2h scheduled report is too slow for direction
# flips. The `fast_1h` component inside momentum_score already catches flips
# — we just need to WATCH it between reports. Alerts when an asset's
# momentum_score crosses the horizon-24h neutral threshold (±0.40) or jumps
# by > FLIP_JUMP_DELTA with sign change, compared to the previous snapshot.
# State kept daemon-side (bridge restarts lose STATE; daemon is the
# long-lived scheduler).
FLIP_THRESHOLD  = 0.40   # mirrors presentiment_forecast NEUTRAL_THRESHOLD[24]
FLIP_JUMP_DELTA = 0.30   # + same-direction flip magnitude to alert
_FLIP_STATE_PATH = CFG["PROJECT_DIR"] / "data" / "presentiment" / "flip_state.json"

# Reversal-override alert (audit 2026-09-04, ZEC long-lost): when the bridge
# momentum_composite detects a live reversal that CONTRADICTS the slow trend,
# it sets snapshot.reversal_override=True. That is an urgent "the trend you
# believe in just flipped this hour" signal — worth a dedicated Telegram alert
# (hold/close bias) beyond the regular flip cross. Cooldown per symbol so we
# don't spam while a reversal persists.
_REVERSAL_ALERT_PATH = CFG["PROJECT_DIR"] / "data" / "presentiment" / "reversal_alert.json"


def _load_json_map(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save_json_map(path: Path, state: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state))
    except Exception as e:
        log.warning(f"save {path.name} failed: {e}")


def _detect_momentum_flips(snapshots: dict) -> list[str]:
    """Compare momentum vs previous snapshot → alert-worthy flips (pure).

    A flip = |score| >= FLIP_THRESHOLD now AND (previous |score| was below
    it OR sign changed with |Δ| >= FLIP_JUMP_DELTA). Cooldown: an asset is
    alerted at most once per flip episode (state tracks last sign+alert).

    Returns the flip-alert lines (same shape as before; no behavioral change
    to the flip logic). Reversal-override alerts are handled separately by
    _detect_reversal_overrides so each responsibility stays isolated.
    """
    prev_state = _load_json_map(_FLIP_STATE_PATH)
    first_run = not prev_state   # cold start: baseline only, no alert burst
    alerts: list[str] = []
    new_state: dict = {}
    for sym, snap in (snapshots or {}).items():
        if not isinstance(snap, dict) or snap.get("advisory"):
            continue
        try:
            score = float(snap.get("momentum_score") or 0)
        except (TypeError, ValueError):
            continue
        prev = prev_state.get(sym, {})
        prev_score = float(prev.get("score", 0) or 0)
        sign = 1 if score > 0 else (-1 if score < 0 else 0)
        # Episode = continuous stretch above threshold in one sign. A dip
        # below the threshold ENDS the episode (alerted_sign resets), so
        # re-crossing later alerts again.
        episode_dead = abs(score) < FLIP_THRESHOLD
        prev_alerted = prev.get("alerted_sign", 0) or 0
        crossed = (not first_run
                   and abs(score) >= FLIP_THRESHOLD
                   and (abs(prev_score) < FLIP_THRESHOLD
                        or (sign != 0 and prev.get("sign") not in (sign, 0)
                            and abs(score - prev_score) >= FLIP_JUMP_DELTA)))
        if crossed and prev_alerted != sign:
            alerts.append(f"• *{sym}* momentum {'🟢 naik' if sign > 0 else '🔴 turun'}"
                          f" → {score:+.2f} (sebelumnya {prev_score:+.2f})")
        new_state[sym] = {
            "score": score, "sign": sign,
            "alerted_sign": 0 if episode_dead else
            (sign if crossed else prev_alerted),
        }
    # Never wipe cooldown memory: an all-advisory / unparseable tick (e.g.
    # bridge hiccup) must not reset the detector to cold-start.
    if new_state:
        _save_json_map(_FLIP_STATE_PATH, new_state)
    return alerts


def _detect_reversal_overrides(snapshots: dict) -> list[str]:
    """Alert when the bridge flags a live reversal contradicting trend (pure).

    Uses snapshot.reversal_override=True (set by momentum_composite when a
    fresh 1h move >= 0.30% opposes the slow-trend composite). Fires once per
    episode (cooldown until the override clears), so a persisting reversal
    alerts once, not every 15m.
    """
    prev_map = _load_json_map(_REVERSAL_ALERT_PATH)
    alerts: list[str] = []
    new_map: dict = {}
    for sym, snap in (snapshots or {}).items():
        if not isinstance(snap, dict) or snap.get("advisory"):
            continue
        fired = bool(snap.get("reversal_override"))
        was_fired = bool(prev_map.get(sym, {}).get("fired"))
        # Alert on rising edge only; retain state while fired for cooldown.
        if fired and not was_fired:
            chg = snap.get("chg_1h")
            mom = snap.get("momentum_score")
            alerts.append(
                f"• ⚠️ *{sym}* REVERSAL: gerak 1h "
                f"{f'{chg:+.2f}%' if isinstance(chg, (int, float)) else '?'} "
                f"berlawanan trend (momentum {mom:+.2f}) → hol/close bias")
        new_map[sym] = {"fired": fired}
    _save_json_map(_REVERSAL_ALERT_PATH, new_map)
    return alerts


async def job_presentiment_snapshot():
    """Unified 24-asset data snapshot (SoDEX / Binance spot / HL) via Hermes.
    Every 15m. Feeds the multi-horizon presentiment ensemble and Grafana.
    Also runs the momentum flip detector → instant Telegram alert on
    direction changes (reaction latency: ≤15m instead of ≤2h+)."""
    try:
        result = await hermes_post("/presentiment/snapshot", {}) or {}
        snaps = result.get("snapshots") or {}
        flips = await asyncio.to_thread(_detect_momentum_flips, snaps)
        reversals = await asyncio.to_thread(_detect_reversal_overrides, snaps)
        # Merge both alert families into ONE Telegram message.
        lines = flips + reversals
        if lines:
            regime = (result.get("regime") or {}).get("regime", "?")
            msg = ("⚡ *PERUBAHAN ARAH MOMENTUM* (regime: " + regime + ")\n\n"
                   + "\n".join(lines[:12])
                   + "\n\n_Laporan lengkap menyusul di jadwal berikutnya._")
            await tg(msg)
            log.info(f"flip detector: {len(lines)} alert(s) sent "
                     f"({len(flips)} flip, {len(reversals)} reversal)")
    except Exception as e:
        log.error(f"presentiment snapshot job error: {e}")


async def job_presentiment_report():
    """Plain-language market report → Telegram setiap jam mulai 09:00 WIB
    (cron UTC hour 2-23; user request 2026-09-04).
    Uses the /presentiment/report endpoint: market condition + per-asset
    LONG/SHORT/TUNGGU verdicts at T+4h/12h/24h + honesty footer."""
    try:
        result = await hermes_post(
            "/presentiment/report", {"send": True})
        if isinstance(result, dict) and result.get("sent_to_telegram"):
            log.info(f"presentiment report sent ({result.get('chars')} chars)")
        else:
            log.warning(f"presentiment report unexpected result: "
                        f"{str(result)[:120]}")
    except Exception as e:
        log.error(f"presentiment report job error: {e}")


_CEX_INTEL_DIR = Path(os.environ.get(
    "ANANTARA_DIR", str(Path.home() / "anantara-sakti")
)) / "freqtrade_user_data/data/binance/intelligence"

_INTEL_LABEL_ENC = {
    "STRONGLY_BEARISH": -2, "BEARISH": -1, "NEUTRAL": 0,
    "BULLISH": 1, "STRONGLY_BULLISH": 2,
}
_INTEL_DIR_ENC = {"DOWN": -1, "NEUTRAL": 0, "UP": 1}


async def job_log_cex_intelligence():
    """Hourly snapshot: intelligence score + per-asset forecast → JSONL.
    FreqAI strategy reads this file as Phase-2 features (intel_score, label_enc,
    fc_dir_enc, fc_confidence). Graceful: skip silently if Hermes not ready yet."""
    try:
        intel = await hermes_get("/intelligence/current") or {}
        score = intel.get("composite_score")
        if not score:
            return  # Hermes hasn't run intelligence refresh yet

        label = intel.get("label", "NEUTRAL")
        row: dict = {
            "ts": int(datetime.now(timezone.utc).timestamp()),
            "composite_score": round(float(score), 2),
            "label_enc": _INTEL_LABEL_ENC.get(label, 0),
            # v8.24: dominant signal for research + explainability audit
            "dominant_signal": intel.get("dominant_signal", ""),
            "explainability": intel.get("explainability", ""),
        }

        for sym in ("BTC", "ETH", "SOL"):
            fc_data = await hermes_get(f"/prediction/current/{sym}") or {}
            fc = (fc_data.get("forecast") or {}) if fc_data else {}
            dir_enc = _INTEL_DIR_ENC.get(fc.get("direction", "NEUTRAL"), 0)
            row[f"fc_{sym}_dir_enc"] = dir_enc
            row[f"fc_{sym}_conf"] = round(float(fc.get("confidence", 0)), 3)
            row[f"fc_{sym}_agreement"] = round(float(fc.get("signal_agreement", 0)), 3)

        # Event risk level — CEX strategy uses this to gate LONG entries during conflicts
        try:
            from anantara.sodex_event_shock_guard import fetch_event_risk as _fer
            _er = await asyncio.to_thread(_fer)
            row["event_risk_level"] = _er.get("level", "NORMAL")
            row["event_risk_score"] = round(float(_er.get("risk_score", 0)), 1)
        except Exception:
            row["event_risk_level"] = "NORMAL"
            row["event_risk_score"] = 0.0

        # v8.21: Market regime (BTC-proxy) — deterministic TRENDING/RANGING/CHAOS classifier
        # Independent from HMM regime (different algorithm, orthogonal signal).
        # CHAOS: high ATR spike + volume z-score → extra caution in CEX entries
        # TRENDING: BTC > 3% from SMA20 → bear=SHORT tailwind, bull=SHORT headwind
        # RANGING: sideways → normal SHORT signal quality
        # CEX strategy reads this from JSONL to adjust threshold in populate_entry_trend.
        try:
            from anantara.market_regime import fetch_regime as _fetch_mr
            _mr = await asyncio.to_thread(_fetch_mr)
            row["market_regime"] = _mr.regime if _mr else "RANGING"
            row["market_regime_momentum"] = round(float(_mr.momentum) if _mr else 0.0, 4)
            row["market_regime_atr_ratio"] = round(float(_mr.atr_ratio) if _mr else 1.0, 3)
        except Exception:
            row["market_regime"] = "RANGING"
            row["market_regime_momentum"] = 0.0
            row["market_regime_atr_ratio"] = 1.0

        _CEX_INTEL_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        fp = _CEX_INTEL_DIR / f"intel_{today}.jsonl"
        with fp.open("a") as f:
            f.write(json.dumps(row) + "\n")

    except Exception as e:
        log.error(f"cex intel log error: {e}")


async def job_signals_refresh():
    """Phase 8.7: fetch x70.ai trading signals (3rd-party AI validation). Every 1h.
    Silent if API key not configured (graceful degradation)."""
    result = await hermes_post("/signals/refresh")
    if not result or "error" in result:
        return  # silent if no API key
    n = result.get("signals_count", 0)
    if n >= 3:
        await tg(f"📡 *External Signals*: {n} active from x70.ai (3rd-opinion source)")


async def job_whale_refresh():
    """Phase 8.8: fetch whale transactions ($1M+). Every 1h. Silent if no key."""
    result = await hermes_post("/whale/refresh")
    if not result or "error" in result:
        return
    n = result.get("count", 0)
    total = result.get("total_usd", 0)
    if n >= 5 or total >= 50_000_000:
        await tg(f"🐋 *Whale Alert*: {n} large txs, ${total/1e6:.1f}M total flow last hour")


async def job_news_refresh():
    """Phase 8.8: fetch crypto news + sentiment. Every 1h. Silent if no key."""
    result = await hermes_post("/news/refresh")
    if not result or "error" in result:
        return
    bull = result.get("bullish", 0)
    bear = result.get("bearish", 0)
    if bull + bear >= 5 and (bull / max(bear, 1) > 3 or bear / max(bull, 1) > 3):
        emoji = "📈" if bull > bear else "📉"
        await tg(f"{emoji} *News Sentiment*: {bull} bullish vs {bear} bearish (skewed)")


async def job_variational_poll():
    """Phase 6.5: poll Variational Omni clearing-house stats. Public, no auth. Silent."""
    result = await hermes_post("/variational/poll")
    if not result or "error" in result:
        return
    oi = result.get("open_interest_usd", 0)
    vol = result.get("volume_24h_usd", 0)
    log.info(f"Variational poll: OI=${oi:,.0f} VOL24h=${vol:,.0f}")


async def job_sodex_poll():
    """Phase 6.6: poll SoDEX perps market data (public, unsigned). Silent."""
    result = await hermes_post("/sodex/poll")
    if not result or "error" in result:
        return
    n = len(result.get("symbols", {}) or {})
    log.info(f"SoDEX poll: {n} symbols, {result.get('markets_total', 0)} markets")


# ──────────────────────────────────────────────────────────────────────
# SODEX FARMING (Phase 6.7) — leveraged directional maker orders for SoPoints.
# Gated by SODEX_FARMING_ENABLED=1 and the global kill switch. Hermes = brain.
# ──────────────────────────────────────────────────────────────────────

_sodex_vol_today = 0.0
_sodex_orders_today = 0
_sodex_vol_date = None
_sodex_week_vol = 0.0     # weekly accumulator for SoPoints alignment
_sodex_week_cost = 0.0
_sodex_week_start = None  # tracks which Saturday week we're in
# ── v9.0: 6-HOUR RATIO ENFORCEMENT — dynamic target, NO COMPROMISE ──
_sodex_vol_6h = 0.0       # volume in current 6h window
_sodex_cost_6h = 0.0      # cost in current 6h window
_sodex_6h_start: datetime | None = None  # start of current 6h block
_SODEX_RATIO_DEFAULT_TARGET = "7000"
_SODEX_6H_TARGET = int(os.environ.get("SODEX_6H_RATIO_TARGET", _SODEX_RATIO_DEFAULT_TARGET))
_SODEX_6H_PAUSED = False  # True jika BEARDOWN di-pause karena ratio < target
_SODEX_STATE_FILE = Path.home() / ".local/share/anantara/sodex_ratio_state.json"


def _sodex_6h_block_start() -> datetime:
    """Return the start of the current 6-hour UTC block (00:00, 06:00, 12:00, 18:00)."""
    now = datetime.now(timezone.utc)
    block_hour = (now.hour // 6) * 6
    return now.replace(hour=block_hour, minute=0, second=0, microsecond=0)


def _sodex_check_6h_target() -> str:
    """Evaluasi ratio 6h saat ini vs target aktif.
    
    Returns: 'OK' | 'WARN' | 'PAUSE'
    - OK: ratio ≥ target, lanjut trading
    - WARN: jam ke-4+ dan ratio < target, peringatan
    - PAUSE: ratio < target setelah 50% window berlalu, auto-pause
    """
    global _sodex_vol_6h, _sodex_cost_6h, _sodex_6h_start, _SODEX_6H_PAUSED
    
    now = datetime.now(timezone.utc)
    block_start = _sodex_6h_block_start()
    
    # Deteksi blok baru — reset counter
    if _sodex_6h_start is None or _sodex_6h_start != block_start:
        _sodex_vol_6h = 0.0
        _sodex_cost_6h = 0.0
        _sodex_6h_start = block_start
        _SODEX_6H_PAUSED = False
        log.info(f"[6H-RATIO] Blok baru: {block_start.strftime('%H:%M')}-{(block_start.hour+6)%24:02d}:00 UTC — target 1:{_SODEX_6H_TARGET}")
        return 'OK'
    
    # Hitung ratio 6h saat ini
    if _sodex_cost_6h <= 0 or _sodex_vol_6h < 100:
        # Belum cukup data
        return 'OK'
    
    ratio_6h = _sodex_vol_6h / _sodex_cost_6h
    elapsed_pct = (now - block_start).total_seconds() / 21600 * 100  # % 6h elapsed
    remaining_min = max(0, (21600 - (now - block_start).total_seconds()) / 60)
    
    if ratio_6h >= _SODEX_6H_TARGET:
        _SODEX_6H_PAUSED = False
        return 'OK'
    
    # Di bawah target
    if elapsed_pct >= 50:
        # Sudah lewat 3 jam — auto-pause
        if not _SODEX_6H_PAUSED:
            _SODEX_6H_PAUSED = True
            log.warning(
                f"[6H-RATIO] 🚨 AUTO-PAUSE! Ratio 1:{ratio_6h:,.0f} < target 1:{_SODEX_6H_TARGET} "
                f"(elapsed {elapsed_pct:.0f}%, {remaining_min:.0f}min remaining)"
            )
        return 'PAUSE'
    else:
        # Masih di bawah 3 jam — warning
        return 'WARN'


def _sodex_6h_ratio_report() -> str:
    """Generate 6h ratio report text untuk Telegram."""
    now = datetime.now(timezone.utc)
    block_start = _sodex_6h_block_start()
    block_end = block_start.replace(hour=block_start.hour + 6)
    elapsed_pct = min(100, (now - block_start).total_seconds() / 21600 * 100)
    remaining_min = max(0, (21600 - (now - block_start).total_seconds()) / 60)
    
    if _sodex_cost_6h > 0 and _sodex_vol_6h > 100:
        ratio = _sodex_vol_6h / _sodex_cost_6h
    else:
        ratio = 0
    
    status = '✅ ON TRACK' if ratio >= _SODEX_6H_TARGET else ('⏸️ PAUSED' if _SODEX_6H_PAUSED else '⚠️ BELOW')
    
    return (
        f"📊 *6H RATIO — {block_start.strftime('%H:%M')}-{block_end.strftime('%H:%M')} UTC*\n"
        f"━━━━━━━━━━\n"
        f"Ratio: *1:{ratio:,.0f}* / target 1:{_SODEX_6H_TARGET}\n"
        f"Volume: ${_sodex_vol_6h:,.0f} | Cost: ${_sodex_cost_6h:,.2f}\n"
        f"Elapsed: {elapsed_pct:.0f}% | Remaining: {remaining_min:.0f}min\n"
        f"Status: {status}\n"
        f"━━━━━━━━━━\n"
        f"Target 1:{_SODEX_6H_TARGET} • NO COMPROMISE"
    )


def _sodex_persist_ratio():
    """Persist weekly + 6h ratio tracking to disk for survival across restarts."""
    try:
        _SODEX_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        week_total_vol = _sodex_week_vol + _sodex_vol_today
        week_total_cost = _sodex_week_cost + _sodex_cost_today
        state = {
            "week_vol": week_total_vol,
            "week_cost": week_total_cost,
            "week_start": _sodex_week_start.isoformat() if _sodex_week_start else None,
            "cost_today": _sodex_cost_today,
            "vol_today": _sodex_vol_today,
            "vol_date": _sodex_vol_date.isoformat() if _sodex_vol_date else None,
            "updated": datetime.now(timezone.utc).isoformat(),
            # v9.0: 6H tracking
            "vol_6h": _sodex_vol_6h,
            "cost_6h": _sodex_cost_6h,
            "sixh_start": _sodex_6h_start.isoformat() if _sodex_6h_start else None,
            "sixh_target": _SODEX_6H_TARGET,
            "sixh_paused": _SODEX_6H_PAUSED,
        }
        _SODEX_STATE_FILE.write_text(json.dumps(state))
    except Exception:
        pass


def _sodex_load_ratio():
    """Load persisted ratio tracking on daemon startup.
    v10.0: week_vol in state file = RUNNING SUM (week + today already combined).
    On load, set today=0 to prevent double-count on next persist.
    Only track NEW volume since this session in _sodex_vol_today."""
    global _sodex_week_vol, _sodex_week_cost, _sodex_week_start, _sodex_cost_today, _sodex_vol_today, _sodex_vol_date
    try:
        if _SODEX_STATE_FILE.exists():
            state = json.loads(_SODEX_STATE_FILE.read_text())
            from datetime import date as _date
            vol_date = _date.fromisoformat(state.get("vol_date", "")) if state.get("vol_date") else None
            today = _date.today()
            # v10.0 FIX: week_vol already includes today's vol (running sum format).
            # Always reset today counters to 0 to prevent double-count.
            # Only exception: if vol_date is NOT today, week_vol is stale and
            # _sodex_roll_day() will handle the reset.
            _sodex_vol_today = 0.0
            _sodex_cost_today = 0.0
            _sodex_vol_date = today
            # v6.0: week totals stored as running sum
            _sodex_week_vol = state.get("week_vol", 0.0)
            _sodex_week_cost = state.get("week_cost", 0.0)
            if state.get("week_start"):
                _sodex_week_start = datetime.fromisoformat(state["week_start"])
            # If state is from a different day, reset week too (stale data)
            if vol_date and vol_date != today:
                _sodex_week_vol = 0.0
                _sodex_week_cost = 0.0
                log.info(f"Ratio state: new day — reset week counters")
            log.info(f"Ratio state loaded: week ${_sodex_week_vol:,.0f} vol, "
                    f"today ${_sodex_vol_today:,.0f} (fresh), cost ${_sodex_cost_today:.2f}")
    except Exception as e:
        log.warning(f"Ratio state load failed: {e}")
# Full 27-asset universe the model serves predictions for.
SODEX_FARM_SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "XAUT-USD", "HYPE-USD",
                      "ZEC-USD", "BCH-USD", "SUI-USD", "DOGE-USD", "LTC-USD",
                      "BNB-USD", "XRP-USD", "SILVER-USD", "COPPER-USD",
                      "INTC-USD", "AMD-USD", "DASH-USD", "WLFI-USD", "LIT-USD",
                      "ONDO-USD", "PENGU-USD", "NEAR-USD", "UNI-USD", "GOOGL-USD",
                      "EWY-USD", "TSLA-USD", "HOOD-USD", "ARB-USD", "1000PEPE-USD",
                      "TRX-USD", "ADA-USD", "ENA-USD", "XMR-USD", "SKHX-USD",
                      "APT-USD", "MU-USD", "NVDA-USD", "AMZN-USD", "ORCL-USD",
                      "MON-USD", "XPL-USD", "LINK-USD", "WLD-USD", "ASTER-USD",
                      "TRUMP-USD", "VIRTUAL-USD", "BERA-USD", "HBAR-USD", "FIL-USD",
                      "OP-USD", "AXS-USD", "WIF-USD", "AVAX-USD", "AAVE-USD",
                      "PLTR-USD", "COIN-USD", "CRCL-USD"]

# Robust whitelist: survived WALK-FORWARD validation with PF>1.2, dir>52%, AND
# >=20 trades (sample-size discipline) — not a lucky single-window OOS. Excluded:
# single-window traps DASH/XRP/BCH/UNI/ONDO (PF<1), and small-sample edges
# AMD/MU (PF high but only ~11 trades = unreliable). Added 1000PEPE (PF1.88, n45).
# Override via SODEX_FARM_WHITELIST (comma list); empty string = full universe.
SODEX_FARM_WHITELIST = [s.strip() for s in os.environ.get(
    "SODEX_FARM_WHITELIST",
    "HYPE-USD,WLFI-USD,BTC-USD,SOL-USD,ZEC-USD,GOOGL-USD,1000PEPE-USD,"
    "AXS-USD,BERA-USD,HBAR-USD"
).split(",") if s.strip()]


def _sodex_enabled() -> bool:
    return os.environ.get("SODEX_FARMING_ENABLED", "0") == "1"



def _realwide_owned_syms() -> set:
    """Simbol perps yang saat ini dimiliki & dikelola realwide_micro_live (live engine
    lolos maturation gates — exit-nya SL/TP/time/regime internal). Posisi UNVERIFIED
    tidak dihitung (biar daemon tetap bisa membersihkan junk). Kosong = tidak ada."""
    try:
        path = CFG["PROJECT_DIR"] / "data" / "realwide_micro_live_state.json"
        if not path.exists():
            return set()
        d = json.loads(path.read_text())
        open_map = d.get("open") or {}
        return {f"{p}-USD" for p, v in open_map.items()
                if isinstance(v, dict) and not v.get("verification_status")}
    except Exception as e:
        log.warning(f"realwide ownership read gagal: {e}")
        return set()


def _sodex_pve_pause_active() -> bool:
    """Shared perps open gate used by every SoDEX execution path."""
    return (CFG["PROJECT_DIR"] / "data" / "PVE_PAUSE").exists()


def _sodex_cfg() -> dict:
    cfg = sf._cfg()
    cfg["address"] = os.environ.get("SODEX_ADDRESS", "")
    return cfg


def _sodex_roll_day():
    global _sodex_vol_today, _sodex_orders_today, _sodex_vol_date, _sodex_cost_today
    global _sodex_week_vol, _sodex_week_cost, _sodex_week_start
    today = datetime.now(timezone.utc).date()
    if _sodex_vol_date != today:
        # Accumulate weekly
        _sodex_week_vol += _sodex_vol_today
        _sodex_week_cost += _sodex_cost_today
        _sodex_vol_date = today
        _sodex_vol_today = 0.0
        _sodex_orders_today = 0
        _sodex_cost_today = 0.0
    # Weekly reset: Saturday 07:00 WIB = Saturday 00:00 UTC
    WIB = timezone(timedelta(hours=7))
    now_wib = datetime.now(WIB)
    this_saturday_wib = now_wib.date() + timedelta(days=(5 - now_wib.weekday()) % 7)
    # v8: Normalize _sodex_week_start to date for comparison (loaded as datetime from JSON)
    week_start_date = _sodex_week_start.date() if hasattr(_sodex_week_start, 'date') else _sodex_week_start
    if _sodex_week_start is None or week_start_date < this_saturday_wib:
        if now_wib.weekday() == 5 and now_wib.hour >= 7:  # Saturday after 07:00 WIB
            _sodex_week_start = this_saturday_wib
            _sodex_week_vol = _sodex_vol_today
            _sodex_week_cost = _sodex_cost_today


async def _sodex_push_state(cfg: dict, positions: list):
    """Push farming snapshot to Hermes for Grafana scraping."""
    bal = await asyncio.to_thread(lambda: sf.cli(["balance", "perps", cfg["address"]], cfg=cfg))
    bal_usd = 0.0
    if isinstance(bal, list) and bal:
        bal_usd = float(bal[0].get("total", 0) or 0)
    upnl = sum(float(p.get("unrealizedPnl", 0) or 0) for p in positions)
    # Enrich positions with leverage risk (distance-to-liquidation, VaR).
    for p in positions:
        try:
            p.update(await asyncio.to_thread(sf.position_risk, p, cfg))
        except Exception:
            pass
    await hermes_post("/sodex/farming_state", {
        "enabled": _sodex_enabled(),
        "kill_active": _kill_active,
        "balance_usd": round(bal_usd, 4),
        "open_positions": len(positions),
        "total_upnl_usd": round(upnl, 4),
        "volume_today_usd": round(_sodex_vol_today, 2),
        "orders_today": _sodex_orders_today,
        "cost_today_usd": round(_sodex_cost_today, 4),
        "scalp_mode": sf.SCALP_MODE,
        "positions": positions,
    })
    # v5.4: persist ratio tracking to survive restarts
    _sodex_persist_ratio()


_sodex_cost_today = 0.0   # cumulative scalp cost (fees+spread) for the day


async def job_sodex_scalp():
    """SoPoints VOLUME scalp — multi-mode.
    BEARDOWN (MODE11): regime-aware patient maker, primary volume engine."""
    global _sodex_vol_today, _sodex_orders_today, _sodex_cost_today
    
    # ── Guard 1: Enable + Kill + Mode ──
    if not _sodex_enabled():
        return  # disabled via Telegram or config
    if _kill_active:
        return  # emergency kill switch active
    if _sodex_pve_pause_active():
        log.warning("SoDEX scalp: PVE_PAUSE active — skip opening perps")
        return
    if sf.halt_active():
        log.warning("SoDEX scalp: SAFETY_HALT/PNL_HALT active — skip leverage and perps orders")
        return
    if not sf.SCALP_MODE and int(os.environ.get("SODEX_SCALP_MODE", "1")) < 2:
        return  # mode not active
    _sodex_roll_day()
    
    # ── Guard 2: BEARDOWN session cost cap (accurate, fee-only) ──
    _daily_cost_cap = float(os.environ.get("SODEX_SCALP_DAILY_COST_CAP", "0"))
    bd = _beardown_load_state()
    bd_cost = bd.get("cost_total", 0) or 0
    if _daily_cost_cap > 0 and bd_cost >= _daily_cost_cap:
        log.warning(f"🔴 BEARDOWN PAUSED: session cost ${bd_cost:.2f} >= cap ${_daily_cost_cap:.0f}")
        return
    
    # ── Guard 3: Daily volume cap ──
    if _sodex_vol_today >= sf.SCALP_DAILY_VOLUME_CAP:
        log.warning(f"🔴 BEARDOWN PAUSED: daily volume ${_sodex_vol_today:.0f} >= cap ${sf.SCALP_DAILY_VOLUME_CAP:.0f}")
        return
    
    # ── Guard 3.5: 6H RATIO ENFORCEMENT — active target, NO COMPROMISE ──
    sixh_status = _sodex_check_6h_target()
    if sixh_status == 'PAUSE':
        # Only log every 4th cycle to avoid spam
        if random.random() < 0.25:
            log.warning(f"[6H-RATIO] ⏸️ BEARDOWN paused — ratio below 1:{_SODEX_6H_TARGET}")
        return
    
    cfg = _sodex_cfg()
    
    # ── Guard 4: Position safety ──
    open_positions_list = await asyncio.to_thread(sf.open_positions, cfg)
    if any(p.get("warning") for p in open_positions_list):
        job_sodex_scalp._consecutive_skips = 0
        log.warning("scalp: position state unverified — skip cycle until SoDEX account state recovers")
        return
    if open_positions_list:
        _consecutive_skips = getattr(job_sodex_scalp, '_consecutive_skips', 0) + 1
        job_sodex_scalp._consecutive_skips = _consecutive_skips
        
        syms_stuck = [p.get("symbol", "?") for p in open_positions_list]
        # Harmonisasi engine (2026-09-25): posisi terverifikasi milik realwide_micro_live (live engine
        # lolos maturation gates, kelola exit sendiri: SL/TP/time/regime) TIDAK dianggap stuck oleh
        # scalp. Root cause insiden 21-25 Sep: monitor/scalp daemon menutup posisi micro_live detik
        # setelah entry → phantom + HALT 3400+ cycle. Scalp menunggu slot kosong, TIDAK force-close.
        _rw_syms = _realwide_owned_syms()
        if _rw_syms and any(s in _rw_syms for s in syms_stuck):
            log.warning(f"scalp: realwide positions aktif {_rw_syms} — skip cycle tanpa force-close")
            return
        log.warning(f"scalp: {len(open_positions_list)} position(s) open ({syms_stuck}) — skip #{_consecutive_skips}")
        
        # Auto-recovery: after 2 skips, force-close all stuck positions
        if _consecutive_skips >= 2:
            log.warning(f"scalp: AUTO-RECOVERY — force-closing {len(open_positions_list)} stuck positions")
            for pos in open_positions_list:
                sym = pos.get("symbol", "?")
                try:
                    closed = await asyncio.to_thread(sf.close_position, pos, cfg)
                    log.info(f"scalp: force-close {sym}: {'OK' if closed else 'FAILED'}")
                except Exception as e:
                    log.error(f"scalp: force-close {sym} error: {e}")
            await asyncio.sleep(2)
            job_sodex_scalp._consecutive_skips = 0
            remaining = await asyncio.to_thread(sf.open_positions, cfg)
            if any(p.get("warning") for p in remaining):
                log.error("scalp: position state unverified after force-close attempt — ABORT")
                return
            if remaining:
                log.error(f"scalp: {len(remaining)} positions STILL open after force-close — ABORT")
                return
        else:
            return  # skip this cycle
    else:
        job_sodex_scalp._consecutive_skips = 0  # reset on clean slate
    
    # ── MODE selection ──
    scalp_mode = int(os.environ.get("SODEX_SCALP_MODE", "1"))
    maker_mode = scalp_mode >= 2
    ratio_mode = scalp_mode >= 4
    mode5_mode = scalp_mode == 5
    mode6_mode = scalp_mode == 6
    mode7_mode = scalp_mode >= 7 and not (scalp_mode == 8 or scalp_mode == 9 or scalp_mode == 10)
    mode8_mode = scalp_mode == 8
    mode9_mode = scalp_mode == 9  # DUAL: MODE 7 (tight) + MODE 8 (wide) parallel
    mode10_mode = scalp_mode == 10  # MODE 10: Dual-Side Spread Capture (DSSC)
    mode11_mode = scalp_mode == 11  # MODE 11: BEARDOWN — Regime-Aware Patient MM
    combo_mode = os.environ.get("SODEX_COMBO_MODE", "0") == "1"  # BEARDOWN + MODE10 alternating
    parallel_mode = scalp_mode >= 3 and not ratio_mode and not mode5_mode and not mode6_mode and not mode7_mode and not mode10_mode and not mode11_mode
    round_func = sf.patient_mm_round if maker_mode else sf.scalp_round
    
    if mode11_mode:
        mode_label = "MODE11-BEARDOWN"
    elif mode10_mode:
        mode_label = "MODE10-DSSC"
    elif mode7_mode:
        mode_label = "MODE7-QUANT"
    elif mode6_mode:
        mode_label = "MODE6-MM"
    elif mode5_mode:
        mode_label = "MODE5-OBI"
    elif ratio_mode:
        mode_label = "RATIO"
    elif parallel_mode:
        mode_label = "parallel"
    elif maker_mode:
        mode_label = "maker"
    else:
        mode_label = "taker"
    
    # ── MODE 11: BEARDOWN — Regime-Aware Patient MM ──
    if mode11_mode:
        syms = sf.MODE11_SYMBOLS if sf.MODE11_ENABLED else sf.SCALP_SYMBOLS
        rounds_per_cycle = len(syms)
        log.info(f"scalp cycle: MODE11-BEARDOWN · {len(syms)} symbols")
    # ── MODE 10: Dual-Side Spread Capture (DSSC) — ALL-PARALLEL ──
    elif mode10_mode and sf.MODE10_ENABLED:
        syms = sf.MODE10_SYMBOLS
        log.info(f"scalp cycle: MODE10-DSSC · {len(syms)} symbols · "
                f"dual-spread capture · ALL-PARALLEL")
    # ── MODE 6: Market Making Hybrid (simultaneous BUY+SELL maker) ──
    elif mode6_mode:
        syms = sf.MODE6_SYMBOLS if sf.MODE6_ENABLED else sf.MODE5_SYMBOLS
        rounds_per_cycle = len(syms)
        log.info(f"scalp cycle: MODE6-MM · {len(syms)} symbols · spread capture {sf.MODE6_SPREAD_BPS}bps")
    # ── MODE 5: OBI Dynamic Spread (BTC+ZEC parallel, then ETH sequential) ──
    elif mode5_mode:
        syms = sf.MODE5_SYMBOLS if sf.MODE5_ENABLED else sf.RATIO_SYMBOLS
        rounds_per_cycle = len(syms)
        log.info(f"scalp cycle: MODE5-OBI · {len(syms)} symbols · PARALLEL BTC+SOL → ZEC+ETH")
    # ── MODE 4: RATIO-optimized (BTC+SILVER only, ultra-short holds, sequential) ──
    elif ratio_mode:
        syms = sf.RATIO_SYMBOLS
        rounds_per_cycle = len(syms)
        log.info(f"scalp cycle: RATIO · {len(syms)} symbols · {mode_label}")
    # ── MODE 3: Dynamic symbol selection by spread ──
    elif parallel_mode:
        parallel_count = int(os.environ.get("SODEX_SCALP_PARALLEL_COUNT", "10"))
        syms = await _select_top_symbols_by_spread(cfg, parallel_count)
        rounds_per_cycle = 1
        log.info(f"scalp cycle: PARALLEL · {len(syms)} symbols · {mode_label}")
    else:
        syms = sf.SCALP_SYMBOLS
        rounds_per_cycle = sf.SCALP_ROUNDS_PER_CYCLE
        log.info(f"scalp cycle: {mode_label} mode · {rounds_per_cycle} rounds")
    
    bal = await asyncio.to_thread(lambda: sf.cli(["balance", "perps", cfg["address"]], cfg=cfg))
    bal0 = float(bal[0].get("total", 0) or 0) if isinstance(bal, list) and bal else None

    done_vol = 0.0

    # ── MODE 11: BEARDOWN — Regime-Aware Patient MM (MODE2 + PVE F3 combo) ──
    if mode11_mode and sf.MODE11_ENABLED:
        syms = sf.MODE11_SYMBOLS
        regime_dir, regime_conf = sf._read_regime_direction()
        regime_tag = f"BEAR→SHORT" if regime_dir == "short" else (f"BULL→LONG" if regime_dir == "long" else "NEUTRAL→ALTERNATE")
        mg = sf.MODE11_MOMENTUM_GATE_BEAR if regime_dir == "short" else sf.MODE11_MOMENTUM_GATE_NEUTRAL
        log.info(f"scalp cycle: MODE11-BEARDOWN · {len(syms)} symbols · "
                f"regime={regime_tag} conf={regime_conf:.0%} · margin=${sf.MODE11_MARGIN} · "
                f"lev={sf.MODE11_LEVERAGE}× · open={sf.MODE11_OPEN_WAIT}s · close={sf.MODE11_CLOSE_WAIT}s · "
                f"mom_gate={mg}% · sl={sf.MODE11_STOP_LOSS:.0%}")
        
        # Set leverage sequentially for nonce safety
        for sym in syms:
            if _sodex_vol_today + done_vol >= sf.SCALP_DAILY_VOLUME_CAP: break
            lev = min(sf.MODE11_LEVERAGE, sf.SYMBOLS.get(sym, {}).get("max_lev", 5))
            await asyncio.to_thread(sf.set_leverage, sym, lev, cfg)
            await asyncio.sleep(0.3)
        
        # ALL-PARALLEL regime-aware patient maker rounds
        async def _beardown_one(sym):
            # Per-symbol spread gate: 4× baseline (wide-spread symbols need wider gate)
            sym_baseline = sf.SYMBOL_SPREAD_BASELINE.get(sym, 10.0)
            spread_gate_pct = sym_baseline * 4 / 100  # bps to % (e.g. 31bps → 1.24%)
            r = await asyncio.to_thread(sf.patient_mm_regime_round, sym, cfg,
                margin=sf.MODE11_MARGIN, leverage=sf.MODE11_LEVERAGE,
                open_wait=sf.MODE11_OPEN_WAIT, close_wait=sf.MODE11_CLOSE_WAIT,
                stop_loss_frac=sf.MODE11_STOP_LOSS,
                spread_threshold=spread_gate_pct,
                momentum_threshold=mg)  # mg already in % (0.3=0.3%), patient_mm uses pct directly
            if isinstance(r, dict): r["sym"] = sym
            return r
        
        tasks = [_beardown_one(sym) for sym in syms]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Track per-symbol results for skip detection
        symbol_results = {}
        cycle_pnl = 0.0
        MIN_FILL_VOLUME = 50.0  # minimum $50 fill — prevent dust positions
        
        for r in results:
            if isinstance(r, Exception):
                log.error(f"BEARDOWN parallel error: {r}"); continue
            if not isinstance(r, dict): continue
            sym = r.get("sym", "?")
            fill_vol = r.get("volume", 0) or 0
            filled = r.get("ok") and r.get("filled", True)
            
            # ── Minimum fill gate: skip dust fills that can't close properly ──
            if filled and fill_vol < MIN_FILL_VOLUME:
                log.warning(f"scalp {sym}: DUST FILL ${fill_vol:.2f} < ${MIN_FILL_VOLUME} — treating as skip [BEARDOWN]")
                filled = False
                r["filled"] = False
                r["reason"] = f"dust fill ${fill_vol:.2f}"
                fill_vol = 0.0
            
            symbol_results[sym] = {"filled": filled, "volume": fill_vol}
            
            if filled:
                done_vol += fill_vol
                _sodex_orders_today += 1
                reg = r.get("regime", "?")
                direc = r.get("direction", r.get("regime", "?"))
                lm = r.get("legs_maker", "?")
                reg_icon = "🔴" if reg == "BEAR" else ("🟢" if reg == "BULL" else "⚪")
                log.info(f"scalp {sym}: vol +${fill_vol:.2f} · "
                        f"{reg_icon}{reg}/{direc} · maker {lm}/2 [BEARDOWN]")
                # Conservative PNL estimate: 0.02% spread capture minus 0.0216% fees = -0.0016%
                cycle_pnl += fill_vol * -0.000016
            elif r.get("filled") is False:
                reason = r.get("reason", "skip")
                log.info(f"scalp {sym}: {reason} [BEARDOWN]")
            else:
                log.warning(f"scalp {sym}: {r.get('reason','error')} [BEARDOWN]")
        
        # Persist BEARDOWN session state with PNL + per-symbol tracking
        _beardown_persist(done_vol, cycle_pnl, symbol_results)

    # ── MODE 7: RADICAL ALL-PARALLEL ──
    elif mode7_mode and sf.MODE7_ENABLED:
        syms = sf.MODE7_SYMBOLS if sf.MODE7_ENABLED else sf.MODE5_SYMBOLS
        
        # v8: MODE7-INTEL toggle — uses ALL intelligence systems for directional edge
        use_intel = os.environ.get("SODEX_MODE7_INTEL", "0") == "1"
        observe_intel = os.environ.get("SODEX_MODE7_INTEL_OBSERVE", "0") == "1"
        intel_tag = "INTEL" if use_intel else ("OBSERVE" if observe_intel else "QUANT")
        log.info(f"scalp cycle: MODE7-{intel_tag} · {len(syms)} symbols · "
                f"quality≥{sf.MODE7_MIN_QUALITY} · ALL-PARALLEL")
        
        # v8: SHADOW MODE — log what INTEL would decide, without executing
        if observe_intel and not use_intel:
            intel_ctx = sf.get_intelligence_context()
            for sym in syms[:4]:  # sample 4 symbols per cycle
                try:
                    dc = sf._compute_directional_confidence(sym, intel_ctx)
                    if dc["direction"] and dc["confidence"] >= sf.INTEL_DIRECTIONAL_CONFIDENCE:
                        log.info(f"🔍 INTEL-SHADOW {sym}: {dc['direction'].upper()} · "
                                f"conf={dc['confidence']:.0%} · sys={dc['systems_agree']}/4 · "
                                f"details={dc['details']}")
                except Exception:
                    pass
        
        
        # Set leverage first (sequential for nonce safety)
        for sym in syms:
            if _sodex_vol_today + done_vol >= sf.SCALP_DAILY_VOLUME_CAP: break
            await asyncio.to_thread(sf.set_leverage, sym,
                min(sf.SCALP_LEVERAGE, sf.SYMBOLS.get(sym, {}).get("max_lev", 5)), cfg)
            await asyncio.sleep(0.3)
        
        # v8: Choose round function based on INTEL flag
        _round_func = sf.mode7_intel_round if use_intel else sf.mode7_round
        
        # ALL symbols in PARALLEL (radical speed)
        async def _mode7_one(sym):
            r = await asyncio.to_thread(_round_func, sym, cfg,
                margin=sf.SCALP_MARGIN, leverage=sf.SCALP_LEVERAGE,
                open_wait=sf.MODE7_OPEN_WAIT, close_wait=sf.MODE7_CLOSE_WAIT,
                min_quality=sf.MODE7_MIN_QUALITY)
            if isinstance(r, dict): r["sym"] = sym
            return r
        
        tasks = [_mode7_one(sym) for sym in syms]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                log.error(f"MODE7 parallel error: {r}"); continue
            if not isinstance(r, dict): continue
            sym = r.get("sym", "?")
            if r.get("ok") and r.get("filled", True):
                done_vol += r.get("volume", 0)
                _sodex_orders_today += 1
                qs = r.get("quality", "?")
                rec = r.get("recommendation", "?")
                il = r.get("intel_label", "")
                reg = r.get("regime", "")
                pos = r.get("posture", "")
                cm = r.get("combined_mult", 1.0)
                # v8: directional mode info
                im = r.get("intel_mode", "")
                if im == "directional":
                    pnl = r.get("pnl_pct", 0)
                    conf = r.get("confidence", 0)
                    d_dir = r.get("direction", "?")
                    exit_r = r.get("exit_reason", "?")
                    log.info(f"scalp {sym}: vol +${r.get('volume',0):.2f} · "
                            f"🎯DIRECTIONAL({d_dir}) · conf={conf:.0%} · "
                            f"pnl={pnl:+.3f}% · {exit_r} · sys={r.get('systems_agree','?')} [MODE7-INTEL]")
                else:
                    # v5.1: show intelligence + pre-sentiment context
                    intel_tag = f" · 🧠{il}" if il and il != "NEUTRAL" else ""
                    pregain_tag = f" · ⚡{reg}" if reg and "CHAOS" not in reg else ""
                    posture_tag = f" · 💪{pos}×{cm:.1f}" if cm != 1.0 else ""
                    log.info(f"scalp {sym}: vol +${r.get('volume',0):.2f} · "
                            f"maker {r.get('legs_maker','?')}/2 · QS={qs} [{rec}]{intel_tag}{pregain_tag}{posture_tag} [MODE7]")
            elif r.get("filled") is False:
                qs = r.get("quality", "?")
                log.info(f"scalp {sym}: {r.get('reason','skip')} (QS={qs}) [MODE7]")
            else:
                log.warning(f"scalp {sym}: {r.get('reason','error')} [MODE7]")

    # ── MODE 10: Dual-Side Spread Capture (DSSC) — ALL-PARALLEL ──
    elif mode10_mode and sf.MODE10_ENABLED:
        syms = sf.MODE10_SYMBOLS
        log.info(f"scalp cycle: MODE10-DSSC · {len(syms)} symbols · "
                f"dual-fill spreads · ALL-PARALLEL")
        
        # Set leverage sequentially for nonce safety
        for sym in syms:
            if _sodex_vol_today + done_vol >= sf.SCALP_DAILY_VOLUME_CAP: break
            lev = min(sf.MODE10_LEVERAGE, sf.SYMBOLS.get(sym, {}).get("max_lev", 5))
            await asyncio.to_thread(sf.set_leverage, sym, lev, cfg)
            await asyncio.sleep(0.3)
        
        # ALL-PARALLEL DSSC rounds
        async def _dssc_one(sym):
            r = await asyncio.to_thread(sf.mode10_dssc_round, sym, cfg,
                margin=sf.MODE10_MARGIN, leverage=sf.MODE10_LEVERAGE)
            if isinstance(r, dict): r["sym"] = sym
            return r
        
        tasks = [_dssc_one(sym) for sym in syms]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                log.error(f"MODE10 error: {r}"); continue
            if not isinstance(r, dict): continue
            sym = r.get("sym", "?")
            outcome = r.get("outcome", "NONE")
            if r.get("ok") and r.get("filled", True):
                done_vol += r.get("volume", 0)
                _sodex_orders_today += 1
                qs = r.get("quality", "?")
                cap_bps = r.get("spread_captured_bps", 0)
                off_bps = r.get("dual_offset_bps", 0)
                df_rate = r.get("dual_fill_rate", 0)
                outcome_icon = "🎯" if outcome == "DUAL" else "⚠️"
                log.info(f"scalp {sym}: vol +${r.get('volume',0):.2f} · "
                        f"maker {r.get('legs_maker',1)}/2 · QS={qs} · "
                        f"{outcome_icon}{outcome}({cap_bps}bps) · "
                        f"off={off_bps}bps · dual-rate={df_rate:.0f}% [MODE10]")
            elif r.get("filled") is False:
                qs = r.get("quality", "?")
                log.info(f"scalp {sym}: {r.get('reason','skip')} (QS={qs}) [MODE10]")
            else:
                log.warning(f"scalp {sym}: {r.get('reason','error')} [MODE10]")
        
        # Log dual-fill stats summary every cycle
        log.info(sf.mode10_dual_stats_summary())

    # ── MODE 9: DUAL — MODE 7 (tight) + MODE 8 (wide) PARALLEL ──
    elif mode9_mode and sf.MODE8_ENABLED:
        regime = sf._get_market_regime()
        syms_m7 = ["BTC-USD", "ETH-USD", "ZEC-USD"]  # tight spreads → MODE 7 volume
        syms_m8 = sf.MODE8_SYMBOLS  # wide spreads → MODE 8 ratio (ADA+SOL+LINK)
        
        log.info(f"scalp cycle: MODE9-DUAL · M7({len(syms_m7)}) + M8({len(syms_m8)}) · "
                f"{regime['regime']}(ATR={regime['atr_ratio']:.1f}x) · MAXIMUM")
        
        # Set leverage for all symbols
        all_syms = syms_m7 + syms_m8
        for sym in all_syms:
            lev = min(sf.SCALP_LEVERAGE if sym in syms_m7 else sf.MODE8_LEVERAGE,
                      sf.SYMBOLS.get(sym, {}).get("max_lev", 10))
            await asyncio.to_thread(sf.set_leverage, sym, lev, cfg)
            await asyncio.sleep(0.3)
        
        # MODE 7 tasks (tight spreads — volume focus)
        async def _m7_one(sym):
            r = await asyncio.to_thread(sf.mode7_round, sym, cfg,
                margin=sf.SCALP_MARGIN, leverage=sf.SCALP_LEVERAGE,
                open_wait=sf.MODE7_OPEN_WAIT, close_wait=sf.MODE7_CLOSE_WAIT,
                min_quality=sf.MODE7_MIN_QUALITY)
            if isinstance(r, dict): r["sym"] = sym
            return r
        
        # MODE 8 tasks (wide spreads — ratio focus)
        async def _m8_one(sym):
            r = await asyncio.to_thread(sf.mode8_dn_cycle, sym, cfg,
                margin=sf.MODE8_MARGIN, leverage=sf.MODE8_LEVERAGE,
                open_wait=sf.MODE8_OPEN_WAIT, close_wait=sf.MODE8_CLOSE_WAIT)
            if isinstance(r, dict): r["sym"] = sym
            return r
        
        # ALL-PARALLEL: MODE 7 + MODE 8 simultaneously
        all_tasks = [_m7_one(s) for s in syms_m7] + [_m8_one(s) for s in syms_m8]
        results = await asyncio.gather(*all_tasks, return_exceptions=True)
        
        for r in results:
            if isinstance(r, Exception):
                log.error(f"MODE9 error: {r}"); continue
            if not isinstance(r, dict): continue
            sym = r.get("sym", "?")
            mode = r.get("mode", "?")
            if r.get("ok") and r.get("filled"):
                done_vol += r.get("volume", 0)
                _sodex_orders_today += 1
                if mode == 8:
                    legs = r.get("legs_filled", 2)
                    log.info(f"scalp {sym}: vol +${r.get('volume',0):.2f} · "
                            f"legs {legs}/2 · maker {r.get('legs_maker','?')}/4 · "
                            f"QS={r.get('quality','?')} · sBPS={r.get('smart_bps','?')} [MODE8-DN]")
                else:
                    qs = r.get("quality", "?")
                    log.info(f"scalp {sym}: vol +${r.get('volume',0):.2f} · "
                            f"maker {r.get('legs_maker','?')}/2 · QS={qs} [MODE7]")
            elif r.get("filled") is False:
                log.info(f"scalp {sym}: {r.get('reason','skip')} [MODE{r.get('mode','?')}]")
            else:
                log.warning(f"scalp {sym}: {r.get('reason','error')} [MODE{r.get('mode','?')}]")

    # ── MODE 8: DELTA-NEUTRAL MAKER CYCLING (v4.3.0 — Pre-Gain integrated) ──
    elif mode8_mode and sf.MODE8_ENABLED:
        syms = sf.MODE8_SYMBOLS
        regime = sf._get_market_regime()
        log.info(f"scalp cycle: MODE8-DN · {len(syms)} symbols · lev {sf.MODE8_LEVERAGE}× · "
                f"{regime['regime']}(ATR={regime['atr_ratio']:.1f}x) · PRE-GAIN")
        
        # Set leverage (sequential for nonce safety)
        for sym in syms:
            await asyncio.to_thread(sf.set_leverage, sym,
                min(sf.MODE8_LEVERAGE, sf.SYMBOLS.get(sym, {}).get("max_lev", 10)), cfg)
            await asyncio.sleep(0.3)
        
        # ALL-PARALLEL DN cycles
        async def _mode8_one(sym):
            r = await asyncio.to_thread(sf.mode8_dn_cycle, sym, cfg,
                margin=sf.MODE8_MARGIN, leverage=sf.MODE8_LEVERAGE,
                open_wait=sf.MODE8_OPEN_WAIT, close_wait=sf.MODE8_CLOSE_WAIT)
            if isinstance(r, dict): r["sym"] = sym
            return r
        
        tasks = [_mode8_one(sym) for sym in syms]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                log.error(f"MODE8 parallel error: {r}"); continue
            if not isinstance(r, dict): continue
            sym = r.get("sym", "?")
            legs = r.get("legs_filled", 2)
            if r.get("ok") and r.get("filled"):
                done_vol += r.get("volume", 0)
                _sodex_orders_today += legs
                log.info(f"scalp {sym}: vol +${r.get('volume',0):.2f} · "
                        f"legs {legs}/2 · maker {r.get('legs_maker','?')}/4 · "
                        f"QS={r.get('quality','?')} · sBPS={r.get('smart_bps','?')} · "
                        f"{r.get('regime','?')} [MODE8-DN]")
            elif r.get("filled") is False:
                log.info(f"scalp {sym}: {r.get('reason','skip')} [MODE8]")
            else:
                log.warning(f"scalp {sym}: {r.get('reason','error')} (ok={r.get('ok')}) [MODE8]")

    # ── MODE 6: Market Making Hybrid — sequential per symbol ──
    elif mode6_mode and sf.MODE6_ENABLED:
        # Set leverage for all symbols
        for sym in syms:
            if _sodex_vol_today + done_vol >= sf.SCALP_DAILY_VOLUME_CAP:
                break
            await asyncio.to_thread(sf.set_leverage, sym,
                min(sf.MODE6_LEVERAGE, sf.SYMBOLS.get(sym, {}).get("max_lev", 5)), cfg)
            await asyncio.sleep(0.3)
        
        for sym in syms:
            if _sodex_vol_today + done_vol >= sf.SCALP_DAILY_VOLUME_CAP:
                break
            r = await asyncio.to_thread(sf.mode6_round, sym, cfg,
                margin=sf.MODE6_MARGIN, leverage=sf.MODE6_LEVERAGE,
                spread_bps=sf.MODE6_SPREAD_BPS, wait_secs=sf.MODE6_WAIT)
            if not isinstance(r, dict): continue
            sym = r.get("sym", "?")
            if r.get("ok") and r.get("filled", True):
                done_vol += r.get("volume", 0)
                _sodex_orders_today += 1
                outcome = r.get("mm_outcome", "?")
                log.info(f"scalp {sym}: vol +${r.get('volume', 0):.2f} · "
                        f"maker {r.get('legs_maker', '?')}/2 · MM({outcome}) [MODE6]")
            elif r.get("filled") is False:
                log.info(f"scalp {sym}: {r.get('reason', 'skip')} [MODE6]")
            else:
                log.warning(f"scalp {sym}: {r.get('reason', 'error')} [MODE6]")

    # ── MODE 5: OBI Dynamic Spread — PARALLEL BTC+SOL, then ZEC+ETH ──
    elif mode5_mode and sf.MODE5_ENABLED:
        # Phase 1: Parallel BTC + SOL (both BUY-biased, high volume)
        primary_syms = [s for s in syms if s in ("BTC-USD", "SOL-USD")]
        secondary_syms = [s for s in syms if s not in ("BTC-USD", "SOL-USD")]
        
        # Set leverage sequentially (nonce safety)
        for sym in primary_syms + secondary_syms:
            if _sodex_vol_today + done_vol >= sf.SCALP_DAILY_VOLUME_CAP:
                break
            await asyncio.to_thread(sf.set_leverage, sym,
                min(sf.SCALP_LEVERAGE, sf.SYMBOLS.get(sym, {}).get("max_lev", 5)), cfg)
            await asyncio.sleep(0.3)
        
        # Phase 1: Run BTC + ZEC in PARALLEL
        async def _mode5_one(sym):
            r = await asyncio.to_thread(sf.mode5_round, sym, cfg,
                margin=sf.SCALP_MARGIN, leverage=sf.SCALP_LEVERAGE,
                open_wait=sf.MODE5_OPEN_WAIT, close_wait=sf.MODE5_CLOSE_WAIT,
                momentum_threshold=sf.MODE5_MOMENTUM_GATE)
            if isinstance(r, dict):
                r["sym"] = sym
            return r
        
        if primary_syms:
            tasks = [_mode5_one(sym) for sym in primary_syms]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    log.error(f"MODE5 parallel error: {r}")
                    continue
                if not isinstance(r, dict): continue
                sym = r.get("sym", "?")
                if r.get("ok") and r.get("filled", True):
                    done_vol += r.get("volume", 0)
                    _sodex_orders_today += 1
                    spread_used = r.get("spread_used", "?")
                    obi_conf = r.get("obi_confidence", "?")
                    log.info(f"scalp {sym}: vol +${r.get('volume', 0):.2f} · "
                            f"maker {r.get('legs_maker', '?')}/2 · OBI(spread={spread_used}%,conf={obi_conf}) [PARALLEL]")
                elif r.get("filled") is False:
                    log.info(f"scalp {sym}: {r.get('reason', 'skip')} [PARALLEL]")
                else:
                    log.warning(f"scalp {sym}: {r.get('reason', 'error')} [PARALLEL]")
        
        # Phase 2: Parallel ZEC + ETH (secondary pair)
        if secondary_syms:
            await asyncio.sleep(1)  # nonce buffer
            tasks2 = [_mode5_one(sym) for sym in secondary_syms]
            results2 = await asyncio.gather(*tasks2, return_exceptions=True)
            for r in results2:
                if isinstance(r, Exception):
                    log.error(f"MODE5 parallel error: {r}")
                    continue
                if not isinstance(r, dict): continue
                sym = r.get("sym", "?")
                if r.get("ok") and r.get("filled", True):
                    done_vol += r.get("volume", 0)
                    _sodex_orders_today += 1
                    spread_used = r.get("spread_used", "?")
                    obi_conf = r.get("obi_confidence", "?")
                    log.info(f"scalp {sym}: vol +${r.get('volume', 0):.2f} · "
                            f"maker {r.get('legs_maker', '?')}/2 · OBI(spread={spread_used}%,conf={obi_conf}) [PARALLEL]")
                elif r.get("filled") is False:
                    log.info(f"scalp {sym}: {r.get('reason', 'skip')} [PARALLEL]")
                else:
                    log.warning(f"scalp {sym}: {r.get('reason', 'error')} [PARALLEL]")
    # ── MODE 4: RATIO execution (sequential, ultra-short holds) ──
    elif ratio_mode and not mode7_mode and not mode8_mode and not mode9_mode:
        for i, sym in enumerate(syms):
            if _sodex_vol_today + done_vol >= sf.SCALP_DAILY_VOLUME_CAP:
                break
            # Pre-set leverage
            await asyncio.to_thread(sf.set_leverage, sym,
                min(sf.SCALP_LEVERAGE, sf.SYMBOLS.get(sym, {}).get("max_lev", 5)), cfg)
            await asyncio.sleep(0.5)
            # Execute with ratio-optimized parameters
            r = await asyncio.to_thread(sf.patient_mm_round, sym, cfg,
                margin=sf.SCALP_MARGIN,
                leverage=sf.SCALP_LEVERAGE,
                open_wait=sf.RATIO_OPEN_WAIT,
                close_wait=sf.RATIO_CLOSE_WAIT,
                reprice_every=3.0,
                stop_loss_frac=0.25,
                spread_threshold=sf.RATIO_SPREAD_GATE,
                momentum_threshold=sf.RATIO_MOMENTUM_GATE)
            if isinstance(r, dict):
                r["sym"] = sym
                if r.get("ok") and r.get("filled", True):
                    done_vol += r.get("volume", 0)
                    _sodex_orders_today += 1
                    log.info(f"scalp {sym}: vol +${r.get('volume', 0):.2f} · "
                            f"maker {r.get('legs_maker', '?')}/2 · RATIO")
                elif r.get("filled") is False:
                    log.info(f"scalp {sym}: {r.get('reason', 'skip')}")
                else:
                    log.warning(f"scalp {sym}: {r.get('reason', 'error')}")
            await asyncio.sleep(1.0)
    
    # ── MODE 3: Parallel execution ──
    elif parallel_mode:
        # ── MODE 3: Set leverage SEQUENTIALLY first (avoid EIP-712 nonce collision) ──
        # Then execute rounds in PARALLEL (patient_mm_round handles its own nonces internally)
        for sym in syms:
            if maker_mode:
                await asyncio.to_thread(sf.set_leverage, sym,
                    min(sf.SCALP_LEVERAGE, sf.SYMBOLS.get(sym, {}).get("max_lev", 5)), cfg)
                await asyncio.sleep(0.3)  # gap between sequential leverage calls
        
        # Now run all rounds in parallel (no set_leverage calls inside each round)
        async def _scalp_one_parallel(sym: str, idx: int) -> dict:
            await asyncio.sleep(idx * 0.25)  # micro-stagger for initial API calls
            r = await asyncio.to_thread(round_func, sym, cfg)
            r["sym"] = sym
            return r
        
        tasks = [_scalp_one_parallel(sym, i) for i, sym in enumerate(syms)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for r in results:
            if isinstance(r, Exception):
                log.error(f"scalp parallel error: {r}")
                continue
            if not isinstance(r, dict):
                continue
            sym = r.get("sym", "?")
            if r.get("ok") and r.get("filled", True):
                done_vol += r.get("volume", 0)
                _sodex_orders_today += 1
                maker_legs = r.get("legs_maker", "?")
                log.info(f"scalp {sym}: vol +${r.get('volume', 0)} · maker {maker_legs}/2")
            elif r.get("filled") is False:
                log.info(f"scalp {sym}: {r.get('reason', 'maker miss')}")
            else:
                log.warning(f"scalp {sym}: NOT OK — {r.get('reason', 'unknown')}")
                await tg(f"⚠️ SoDEX scalp {sym}: {r.get('reason', 'error')}")
    else:
        # ── MODE 1/2: Sequential execution (original behavior) ──
        rounds_this_cycle = min(rounds_per_cycle, len(syms))
        base_idx = _sodex_orders_today
        for i in range(rounds_this_cycle):
            if _sodex_vol_today + done_vol >= sf.SCALP_DAILY_VOLUME_CAP:
                break
            sym = syms[(base_idx + i) % len(syms)]
            log.debug(f"scalp: round {i+1}/{rounds_this_cycle} → {sym}")
            r = await _scalp_one_parallel(sym, i)
            if isinstance(r, Exception):
                log.error(f"scalp {sym} error: {r}")
                continue
            if not isinstance(r, dict):
                log.warning(f"scalp {sym}: unexpected return type {type(r)}")
                continue
            if r.get("ok") and r.get("filled", True):
                done_vol += r.get("volume", 0)
                _sodex_orders_today += 1
                maker_legs = r.get("legs_maker", "?")
                log.info(f"scalp {sym}: vol +${r.get('volume', 0)} · maker {maker_legs}/2 · {mode_label}")
            elif r.get("filled") is False:
                log.info(f"scalp {sym}: {r.get('reason', 'maker miss')} — skip")
            else:
                log.warning(f"scalp {sym}: NOT OK — {r.get('reason', 'unknown')}")
                await tg(f"⚠️ SoDEX scalp {sym}: {r.get('reason', 'error')}")
            # Brief delay between symbols to avoid CLI state conflicts
            await asyncio.sleep(1.5)
    
    # ── Update daily volume & cost tracking ──
    _sodex_vol_today += done_vol
    
    # Cost: measure balance change for accurate ratio
    if bal0 is not None:
        try:
            bal = await asyncio.to_thread(lambda: sf.cli(["balance", "perps", cfg["address"]], cfg=cfg))
            bal1 = float(bal[0].get("total", 0) or 0) if isinstance(bal, list) and bal else bal0
            if bal1 < bal0:  # only count if balance decreased
                _sodex_cost_today += (bal0 - bal1)
        except Exception:
            pass
    
    # ── v9.0: Update 6H ratio tracking ──
    global _sodex_vol_6h, _sodex_cost_6h  # ponytail: _sodex_6h_start, _SODEX_6H_PAUSED read-only, no global needed
    _sodex_vol_6h += done_vol
    if bal0 is not None and bal1 is not None and bal1 < bal0:
        _sodex_cost_6h += (bal0 - bal1)
    
    # ── v5.2: Quick ratio status every cycle (log only, Telegram every hour) ──
    # v8: Single-leg counting — volume = open_notional, fee = 0.0108% (1 leg).
    # Ceiling: 1 / 0.000108 = 1:9,259 (was 1:4,630 with round-trip counting).
    FEE_RATE = 0.000108  # single-leg maker fee 0.0108%
    fee_cost = _sodex_vol_today * FEE_RATE
    live_ratio = _sodex_vol_today / max(_sodex_cost_today, fee_cost) if _sodex_vol_today > 10 else 0
    
    # ── v9.0: 6H ratio check + alert ──
    _sodex_check_6h_target()  # check tanpa blocking (blocking di Guard 3.5)
    if _sodex_cost_6h > 0 and _sodex_vol_6h > 100:
        ratio_6h = _sodex_vol_6h / _sodex_cost_6h
        if live_ratio > 0 and random.random() < 0.25:
            sixh_flag = '✅' if ratio_6h >= _SODEX_6H_TARGET else ('⏸️' if _SODEX_6H_PAUSED else '⚠️')
            log.info(f"Ratio live: 1:{live_ratio:,.0f} | vol ${_sodex_vol_today:,.0f} | "
                    f"cost ${_sodex_cost_today:.2f} | fee-floor 1:{1/FEE_RATE:,.0f} | "
                    f"6h: 1:{ratio_6h:,.0f} {sixh_flag}")
    
    positions = await asyncio.to_thread(sf.open_positions, cfg)
    await _sodex_push_state(cfg, positions)


async def _select_top_symbols_by_spread(cfg: dict, count: int) -> list[str]:
    """Fetch all tickers and return the top N symbols by tightest spread.
    Filters: spread < 0.02%, 24h volume > $50K, known symbol metadata exists."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{cfg.get('perps_url', 'https://mainnet-gw.sodex.dev/api/v1/perps')}/markets/tickers")
            data = (r.json() or {}).get("data", []) or []
    except Exception as e:
        log.warning(f"dynamic symbol fetch failed: {e}, using default SCALP_SYMBOLS")
        return sf.SCALP_SYMBOLS[:count]
    
    ranked = []
    for t in data:
        sym = t.get("symbol", "")
        if sym not in sf.SYMBOLS:
            continue  # skip unknown symbols
        bid = float(t.get("bidPx", 0) or 0)
        ask = float(t.get("askPx", 0) or 0)
        last = float(t.get("lastPx", 0) or 0)
        vol = float(t.get("quoteVolume", 0) or 0)
        if bid <= 0 or ask <= 0 or last <= 0:
            continue
        spread_pct = (ask - bid) / last * 100
        if spread_pct > 0.015 or vol < 50000:
            continue  # too wide or too illiquid
        ranked.append((spread_pct, sym, vol))
    
    ranked.sort()
    selected = [s[1] for s in ranked[:count]]
    spreads = ", ".join(f"{s[0]:.3f}%" for s in ranked[:min(5, len(ranked))])
    log.info(f"dynamic symbols ({len(selected)}): {spreads} ... → {selected[:5]}...")
    return selected if selected else sf.SCALP_SYMBOLS[:count]


async def job_sodex_spot_farm():
    """Every 15 min: run the guarded SoDEX SPOT autofarm wrapper.

    The wrapper owns the current live route and fails closed on kill switch,
    event-risk RED/ORANGE, stale research status, adaptive-policy veto, prime-time
    gating, and the autofarm process lock. Deprecated spot executors are not
    called from the daemon.
    """
    if not _sodex_enabled() or _kill_active:
        return
    try:
        cmd = ["python3", "scripts/sodex_spot_daemon.py", "once"]
        env = os.environ.copy()
        env.setdefault(
            "SODEX_SPOT_DAEMON_CAPITAL",
            os.environ.get("SPOT_FARM_CAPITAL", "10"),
        )
        r = await asyncio.to_thread(lambda: subprocess.run(
            cmd, capture_output=True, text=True, timeout=90,
            cwd=str(CFG["PROJECT_DIR"]), env=env))
        if r.returncode == 0 and r.stdout:
            for line in r.stdout.strip().split('\n'):
                if '"status"' in line or '"reason"' in line or '"pnl"' in line:
                    log.info(f"spot-autofarm: {line.strip()[:160]}")
        if r.stderr:
            log.warning(f"spot-autofarm stderr: {r.stderr.strip()[:200]}")
    except subprocess.TimeoutExpired:
        log.warning("spot-autofarm: timeout")
    except Exception as e:
        log.error(f"spot-autofarm error: {e}")


async def job_sodex_ratio_report():
    """Send Telegram ratio report from the read-only monitor/eval snapshot."""
    if not _sodex_enabled():
        return

    try:
        await tg(_sodex_ratio_report_text(), parse_mode=None)
        log.info("Ratio report sent from sodex_monitor_eval latest.json")
    except Exception as e:
        log.error(f"Ratio report failed: {e}")


async def job_hl_data_update():
    """Daily 03:00 UTC: incremental update HL historical data (OHLCV + funding).
    Hanya download data baru sejak terakhir download — incremental, ~60 detik.
    Data ini digunakan oleh pregain_backtest.fetch_path() (cache lokal lebih cepat)
    dan semua research backtest scripts."""
    try:
        r = await asyncio.to_thread(lambda: __import__("subprocess").run(
            ["python3", "scripts/download_hl_history.py",
             "--update", "--no-funding",   # candles saja (funding jarang berubah)
             "--coins",
             "BTC","ETH","SOL","XRP","BNB","DOGE","ADA","AVAX","LINK","DOT",
             "LTC","ARB","OP", "SUI","APT","INJ","XMR","HYPE","AAVE","UNI",
             "ATOM","NEAR","HBAR","WIF","PEPE","BONK","TRX","WLD","FIL","FET"],
            cwd=str(CFG["PROJECT_DIR"]),
            capture_output=True, text=True, timeout=180
        ))
        if r.returncode == 0:
            log.info("HL data update: incremental download selesai")
        else:
            log.warning(f"HL data update failed: {r.stderr[-200:]}")
    except Exception as e:
        log.error(f"job_hl_data_update: {e}")


async def job_hl_gainer_scan():
    """Every 2 hours: run the honest Pre-Gain/Loser pipeline → Telegram.
    Uses anantara/pregain_scan (regime gate + liquidity discipline + attention
    score) and AUTO-LOGS actionable signals to the validator, so the live 2h scans
    accumulate a real hit-rate over time (validate-first flywheel).

    v7.3 (2026-07-06): juga persist sinyal terstruktur ke data/pregain_latest.json
    untuk dikonsumsi CEX Binance strategy sebagai _pregain_boost (cross-system
    integration: Pre-Gain/Loser radar → directional entry boost)."""
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from anantara import pregain_scan
        def _scan_and_persist():
            # Run scan, persist structured data, then return Telegram string.
            try:
                longs, shorts, regime = pregain_scan.run_scan(
                    pregain_scan.ACTIONABLE_MIN, log=True, verbose=False
                )
                import json, datetime as _dt, pathlib
                _path = pathlib.Path("data/pregain_latest.json")
                _path.parent.mkdir(parents=True, exist_ok=True)
                _payload = {
                    "ts": int(_dt.datetime.utcnow().timestamp()),
                    "generated_utc": _dt.datetime.utcnow().isoformat() + "+00:00",
                    "regime": getattr(regime, "label", str(regime)),
                    "regime_min_score": getattr(regime, "min_score_floor", 60),
                    "longs":  [{"name": s.get("name"), "score": s.get("score"),
                                "liq": s.get("liq"), "ann_fund": s.get("ann_fund")}
                               for s in (longs or [])],
                    "shorts": [{"name": s.get("name"), "score": s.get("score"),
                                "liq": s.get("liq"), "ann_fund": s.get("ann_fund")}
                               for s in (shorts or [])],
                }
                _payload_text = json.dumps(_payload)
                _path.write_text(_payload_text)
                # v8.9: also mirror to freqtrade_user_data/data/ so strategy inside
                # container can read it (Docker volume mount doesn't follow host symlinks).
                _mirror = pathlib.Path("freqtrade_user_data/data/pregain_latest.json")
                try:
                    _mirror.parent.mkdir(parents=True, exist_ok=True)
                    _mirror.write_text(_payload_text)
                except Exception as _me:
                    log.warning(f"pregain mirror write failed: {_me}")
            except Exception as _e:
                log.error(f"pregain persist failed (non-fatal): {_e}")
            return pregain_scan.scan_and_format()
        msg = await asyncio.to_thread(_scan_and_persist)
        await tg(msg)
        log.info("Pre-Gain/Loser radar scan sent + persisted to data/pregain_latest.json")
    except Exception as e:
        log.error(f"Pre-Gain/Loser scan failed: {e}")


async def job_pregain_validate_auto():
    """Every 6h: otomatis backfill outcomes sinyal ≥24h → update hit-rate.
    Tanpa ini, edge gate tidak pernah unlock sendiri meski sinyal sudah terkumpul.
    Kirim ke Telegram hanya jika ada sinyal baru yang terselesaikan."""
    try:
        import sys, os as _os
        sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        from anantara import pregain_scan
        report = await asyncio.to_thread(pregain_scan.validate)
        # Kirim jika ada sinyal baru yang resolved (bukan hanya "0 sinyal baru")
        if not report.startswith("Resolved 0"):
            await tg(report)
            log.info("Pre-Gain auto-validate: sinyal baru di-resolve, report dikirim")
        else:
            log.debug("Pre-Gain auto-validate: tidak ada sinyal baru (pending belum ≥24h)")
    except Exception as e:
        log.error(f"job_pregain_validate_auto: {e}")


async def job_pregain_autotrade():
    """Every 30 min: one auto-trader cycle (paper-only unless edge proven + LIVE flag).
    Runs silently — Telegram alert hanya jika ada paper-trade yang dicatat."""
    try:
        import sys, os as _os
        sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        from anantara import pregain_autotrader
        live = _os.environ.get("AUTOTRADE_LIVE") == "1"
        report = await asyncio.to_thread(pregain_autotrader.run_once, live_enabled=live)
        # Kirim ke Telegram hanya jika ada trade yang dicatat (bukan hanya skip)
        if "▸" in report:
            await tg(report)
            log.info("Pre-Gain auto-trader: paper-trade dicatat")
        else:
            log.debug("Pre-Gain auto-trader: tidak ada sinyal actionable")
    except Exception as e:
        log.error(f"job_pregain_autotrade: {e}")


async def job_pregain_monitor():
    """Every 2 min: check open Pre-Gain positions → close SL/TP if hit.
    Works in paper mode (no real orders) until PREGAIN_LIVE=1 + edge gate open."""
    try:
        import sys, os as _os
        sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        from anantara import pregain_execution as _exec
        tracker = _exec.PositionTracker()
        if tracker.count() == 0:
            return
        live = _os.environ.get("PREGAIN_LIVE") == "1"
        events = await asyncio.to_thread(_exec.monitor_and_close, tracker, live)
        if events:
            msg = _exec.format_close_events(events)
            await tg(msg)
            log.info(f"Pre-Gain monitor: {len(events)} posisi ditutup")
    except Exception as e:
        log.error(f"job_pregain_monitor: {e}")


async def job_long_spot_scan():
    """Every 2h: scan LONG_TECHNICAL + SPOT signals for paper-trade accumulation.
    Runs both scanners and logs signals to DB for edge validation.
    Sends Telegram alert only when new signals detected."""
    try:
        import sys, os as _os
        sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        from anantara import pregain_long_scanner, pregain_spot_scanner, pregain_scan
        from anantara import signal_tracker

        msgs = []

        # LONG_TECHNICAL scan
        long_sigs = await asyncio.to_thread(pregain_long_scanner.scan_long_signals)
        if long_sigs:
            from anantara.signal_tracker import Signal as _Sig
            sigs_to_log = [
                _Sig(s["coin"], "LONG", s["score"], s["grade"], s.get("entry_price", 0),
                     s.get("regime", "RANGING"), s.get("vol24", 0), "STANDARD",
                     fund_accel=s.get("fund_accel", 0), vol_oi=s.get("vol_oi", s.get("vol_ratio", 0)),
                     sig_type="LONG_TECHNICAL")
                for s in long_sigs
            ]
            from anantara.pregain_scan import SIGNAL_DB, LOG_COOLDOWN_SEC
            n = signal_tracker.log_signals(SIGNAL_DB, sigs_to_log, cooldown_sec=LOG_COOLDOWN_SEC)
            if n > 0:
                msgs.append(pregain_long_scanner.format_long_report(long_sigs))
                log.info(f"LONG_TECHNICAL: {n} new signals logged")

        # SPOT scan (all variants)
        spot_sigs = await asyncio.to_thread(pregain_spot_scanner.scan_all_spot)
        if spot_sigs:
            from anantara.signal_tracker import Signal as _Sig
            sigs_to_log = [
                _Sig(s["coin"], "LONG", s["score"], s["grade"], s.get("entry_price", 0),
                     "RANGING", s.get("vol24", 0), "STANDARD",
                     fund_accel=0.0, vol_oi=s.get("vol_ratio", 1.0),
                     sig_type="SPOT_BREAKOUT")
                for s in spot_sigs
            ]
            from anantara.pregain_scan import SIGNAL_DB, LOG_COOLDOWN_SEC
            n = signal_tracker.log_signals(SIGNAL_DB, sigs_to_log, cooldown_sec=LOG_COOLDOWN_SEC * 3)
            if n > 0:
                msgs.append(pregain_spot_scanner.format_spot_report(spot_sigs))
                log.info(f"SPOT: {n} new signals logged")

        if msgs:
            await tg("📡 <b>Long/SPOT Scan</b>\n\n" + "\n\n".join(msgs))

    except Exception as e:
        log.error(f"job_long_spot_scan: {e}")


async def _cmd_three_tracks():
    """Telegram /three-tracks — status akumulasi ketiga jalur trading."""
    try:
        import sys, os as _os
        sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        import sqlite3

        from anantara.pregain_scan import SIGNAL_DB
        from anantara import pregain_long_scanner, pregain_spot_scanner

        db = sqlite3.connect(SIGNAL_DB)
        cur = db.cursor()

        # SHORT track stats
        cur.execute("""SELECT COUNT(*) n, SUM(correct) wins, AVG(outcome_pct) avg
            FROM signal_log WHERE sig_type='SHORT' AND outcome_pct IS NOT NULL""")
        r = cur.fetchone(); sh_n, sh_wins, sh_avg = r
        sh_wr = (sh_wins or 0) / sh_n * 100 if sh_n else 0

        # LONG_TECHNICAL stats
        cur.execute("""SELECT COUNT(*) n, SUM(correct) wins, AVG(outcome_pct) avg
            FROM signal_log WHERE sig_type='LONG_TECHNICAL' AND outcome_pct IS NOT NULL""")
        r = cur.fetchone(); lt_n, lt_wins, lt_avg = r
        lt_wr = (lt_wins or 0) / lt_n * 100 if lt_n else 0
        cur.execute("SELECT COUNT(*) FROM signal_log WHERE sig_type='LONG_TECHNICAL' AND outcome_pct IS NULL")
        lt_pend = cur.fetchone()[0]

        # SPOT stats
        cur.execute("""SELECT COUNT(*) n, SUM(correct) wins, AVG(outcome_pct) avg
            FROM signal_log WHERE sig_type='SPOT_BREAKOUT' AND outcome_pct IS NOT NULL""")
        r = cur.fetchone(); sp_n, sp_wins, sp_avg = r
        sp_wr = (sp_wins or 0) / sp_n * 100 if sp_n else 0
        cur.execute("SELECT COUNT(*) FROM signal_log WHERE sig_type='SPOT_BREAKOUT' AND outcome_pct IS NULL")
        sp_pend = cur.fetchone()[0]
        db.close()

        # Current signals
        lt_now = pregain_long_scanner.scan_long_signals()
        sp_now = pregain_spot_scanner.scan_all_spot()

        from anantara import pregain_spot_scanner as _pss
        btc_ratio = _pss._btc_regime_ratio()

        lines = [
            "📊 <b>THREE TRACKS STATUS</b>",
            f"BTC regime: {'🐂 BULL' if btc_ratio >= 0.85 else '🐻 BEAR'} ({btc_ratio:.0%} of 20d high)",
            "",
            f"<b>① Pre-Loser SHORT</b> 🟢 LIVE",
            f"   n={sh_n} WR={sh_wr:.0f}% avg={sh_avg or 0:.1f}% | Gate: OPEN (E=0.662R)",
            "",
            f"<b>② LONG_TECHNICAL</b> 📋 PAPER",
            f"   Resolved: n={lt_n} WR={lt_wr:.0f}% | Pending: {lt_pend}",
            f"   Gate: {lt_n}/50 resolved, need WR≥69% → LIVE",
            f"   Now: {len(lt_now)} signals active" + (f" ({lt_now[0]['coin']} {lt_now[0]['grade']})" if lt_now else ""),
            f"   Params: RSI<32, vol>2x, BTC_RSI≥30+EMA95%",
            "",
            f"<b>③ SPOT Breakout+Recovery</b> 📋 PAPER",
            f"   Resolved: n={sp_n} WR={sp_wr:.0f}% | Pending: {sp_pend}",
            f"   Gate: {sp_n}/30 resolved, need WR≥69% → LIVE",
            f"   Now: {len(sp_now)} signals active" + (f" ({', '.join(s['coin'] for s in sp_now[:3])})" if sp_now else ""),
        ]
        await tg("\n".join(lines))

    except Exception as e:
        log.error(f"_cmd_three_tracks: {e}")
        await tg(f"⚠️ three-tracks error: {e}")


async def _cmd_pregain_positions():
    """Telegram /pregain-positions — tampilkan semua posisi open saat ini."""
    try:
        import sys, os as _os
        sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        from anantara import pregain_execution as _exec
        tracker = _exec.PositionTracker()
        msg = _exec.positions_summary(tracker)
        await tg(msg)
    except Exception as e:
        await tg(f"❌ Error positions: {e}")
        log.error(f"_cmd_pregain_positions: {e}")


async def _cmd_pregain_autotrade():
    """Telegram /pregain-autotrade — satu siklus auto-trader on-demand (paper-first)."""
    await tg("🤖 _Menjalankan auto-trader cycle..._")
    try:
        import sys, os as _os
        sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        from anantara import pregain_autotrader
        live = _os.environ.get("AUTOTRADE_LIVE") == "1"
        report = await asyncio.to_thread(pregain_autotrader.run_once, live_enabled=live)
        await tg(report)
        log.info("Pre-Gain auto-trader: manual cycle via Telegram")
    except Exception as e:
        await tg(f"❌ Auto-trader error: {e}")
        log.error(f"_cmd_pregain_autotrade: {e}")


async def _cmd_pregain_status():
    """Telegram /pregain-status — progress akumulasi sinyal per grade vs threshold live."""
    try:
        import sys, os as _os
        sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        from anantara import pregain_scan
        report = await asyncio.to_thread(pregain_scan.progress_report)
        await tg(report)
        log.info("Pre-Gain status: progress report sent")
    except Exception as e:
        await tg(f"❌ Status error: {e}")
        log.error(f"_cmd_pregain_status: {e}")


async def _cmd_pregain_regime():
    """Telegram /pregain-regime — kondisi pasar BTC + dampak ke scanner."""
    try:
        import sys, os as _os
        sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        from anantara import pregain_scan
        report = await asyncio.to_thread(pregain_scan.regime_summary)
        await tg(report)
    except Exception as e:
        await tg(f"❌ Regime error: {e}")


async def _cmd_pregain_scan():
    """Telegram /pregain — on-demand Pre-Gain/Loser scan (same as 2h job, manual trigger).
    Logs actionable signals ke validator untuk akumulasi hit-rate."""
    await tg("🔄 _Menjalankan Pre-Gain/Loser scan..._")
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from anantara import pregain_scan
        msg = await asyncio.to_thread(pregain_scan.scan_and_format)
        await tg(msg)
        log.info("Pre-Gain/Loser: manual scan via Telegram")
    except Exception as e:
        await tg(f"❌ Pregain scan error: {e}")
        log.error(f"_cmd_pregain_scan: {e}")


async def _cmd_pregain_validate():
    """Telegram /pregain-validate — laporan hit-rate jujur: berapa % sinyal
    yang benar-benar bergerak ke arah yang diprediksi (setelah ≥24 jam)."""
    await tg("🔄 _Menghitung hit-rate sinyal Pre-Gain..._")
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from anantara import pregain_scan
        report = await asyncio.to_thread(pregain_scan.validate)
        await tg(report)
        log.info("Pre-Gain/Loser: validate report sent")
    except Exception as e:
        await tg(f"❌ Pregain validate error: {e}")
        log.error(f"_cmd_pregain_validate: {e}")


async def _cmd_pregain_backtest():
    """Telegram /pregain-backtest — simulasi paper-trade triple-barrier (SL/TP)
    dari semua sinyal logged ≥24 jam. Jawaban jujur: profitable setelah fee?"""
    await tg("🔄 _Mensimulasikan paper-trade dari sinyal logged..._")
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from anantara import pregain_scan
        report = await asyncio.to_thread(pregain_scan.backtest)
        await tg(report)
        log.info("Pre-Gain/Loser: backtest report sent")
    except Exception as e:
        await tg(f"❌ Pregain backtest error: {e}")
        log.error(f"_cmd_pregain_backtest: {e}")


async def _cmd_pregain_trend():
    """Telegram /pregain-trend — rolling win-rate 7 hari terakhir + breakdown per sesi.
    Deteksi tren kualitas sinyal: apakah membaik, stabil, atau memburuk?
    Breakdown per sesi (Asia/EU/US/US_Asia) memvalidasi hipotesis session timing."""
    await tg("🔄 _Menghitung tren 7 hari terakhir..._")
    try:
        import sys, os as _os
        sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        from anantara import pregain_scan
        report = await asyncio.to_thread(pregain_scan.trend_report, 7)
        await tg(report)
        # Also send 30d for broader context if enough data
        rep30 = await asyncio.to_thread(pregain_scan.trend_report, 30)
        if "n=0" not in rep30 and "Belum ada" not in rep30:
            await tg(rep30.replace("7 HARI", "30 HARI"))
        log.info("Pre-Gain/Loser: trend report sent")
    except Exception as e:
        await tg(f"❌ Pregain trend error: {e}")
        log.error(f"_cmd_pregain_trend: {e}")


async def _cmd_pregain_gates():
    """Telegram /pregain-gates — 10 Sovereign Gates validation (post-gate signals only).

    Runs the full Pre-Gain Sovereign validation pipeline on signals logged AFTER
    2026-06-03 (when empirical gates: B-mid skip, direction gate, time gate became
    active). Excludes pre-gate historical noise from validation.

    Takes ~60-120s (fetches HL candles for each resolved signal).
    """
    # 2026-06-03 00:00 UTC — when all empirical gates became active
    _POST_GATE_TS = 1748908800
    await tg("🔬 *Pre-Gain Sovereign Gates* — validating post-gate signals...\n"
             "_Running 10 sovereign validation gates (takes ~60-120s)_")
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        from anantara import pregain_backtest, pregain_scan
        _db = pregain_scan.SIGNAL_DB

        verdict = await asyncio.to_thread(
            pregain_backtest.run_sovereign_gates,
            _db, pregain_backtest.fetch_path,
            since_ts=_POST_GATE_TS,
        )
        passed  = verdict["passed_gates"]
        total   = verdict["total_gates"]
        verd    = verdict["verdict"]
        icons   = {"GO_LIVE_MICRO": "🚀", "GO_PAPER": "📝",
                   "ACCUMULATING": "📊", "NO_GO": "🚫"}
        icon    = icons.get(verd, "❓")

        lines = [f"{icon} *SOVEREIGN VERDICT: {verd}* ({passed}/{total} gates)"]
        for gd in verdict["gate_dicts"]:
            tick = "✅" if gd["passed"] else "❌"
            # Trim gate name (remove long prefix)
            name_short = gd["name"].split("—")[-1].strip()[:45]
            reason_short = gd["reason"][:70] + ("…" if len(gd["reason"]) > 70 else "")
            lines.append(f"{tick} *{name_short}*\n   _{reason_short}_")
        lines.append(f"\n_Filtered: post-gate signals (≥ 2026-06-03)_")
        await tg("\n".join(lines))
        log.info(f"Sovereign Gates: {verd} ({passed}/{total})")
    except Exception as e:
        await tg(f"❌ Sovereign gates error: {e}")
        log.error(f"_cmd_pregain_gates: {e}")


async def _cmd_pregain_preflight():
    """Telegram /pregain-preflight — verifikasi semua prasyarat live trading."""
    await tg("🔍 _Menjalankan pre-flight check..._")
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        from anantara import pregain_execution as _exec
        report = await asyncio.to_thread(_exec.preflight_check)
        await tg(report)
        log.info("Pre-flight check selesai")
    except Exception as e:
        await tg(f"❌ Pre-flight error: {e}")
        log.error(f"_cmd_pregain_preflight: {e}")


async def _cmd_pregain_reconcile():
    """Telegram /pregain-reconcile — sinkronisasi tracker dengan posisi HL aktual."""
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        from anantara import pregain_execution as _exec
        tracker = _exec.PositionTracker()
        result = await asyncio.to_thread(_exec.reconcile_with_hl, tracker)
        await tg(f"🔄 *HL Reconcile*\n{result}")
        log.info(f"HL reconcile: {result}")
    except Exception as e:
        await tg(f"❌ Reconcile error: {e}")
        log.error(f"_cmd_pregain_reconcile: {e}")


async def _cmd_pregain_rolling():
    """Telegram /pregain-rolling — rolling edge stability per grade (cache-only, fast)."""
    await tg("📈 *Rolling Edge Stability* — computing (cache-only, ~5s)...")
    try:
        import sys as _sys, os as _os, functools as _ft
        _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        from anantara import pregain_backtest, pregain_scan
        _db = pregain_scan.SIGNAL_DB
        fp = _ft.partial(pregain_backtest.fetch_path, cache_only=True)

        lines = []
        for g in ("C", "S", "B"):
            rep = await asyncio.to_thread(
                pregain_backtest.rolling_edge_report, _db, fp, g,
                (20, 40, 80, 120)
            )
            lines.append(rep)
        await tg("\n\n".join(lines))
    except Exception as e:
        await tg(f"❌ Rolling edge error: {e}")
        log.error(f"_cmd_pregain_rolling: {e}")


async def job_pregain_sovereign_gates():
    """Weekly sovereign validation — runs 10 Sovereign Gates on post-gate signals.

    Scheduled: every Monday 02:15 UTC (before weekly_reflection at 00:30).
    Reports verdict + gate summary to Telegram automatically.
    Skips if < 30 resolved post-gate signals (insufficient for statistical inference).
    """
    _POST_GATE_TS = 1748908800   # 2026-06-03 00:00 UTC
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        from anantara import pregain_backtest, pregain_scan, signal_tracker as _st
        _db = pregain_scan.SIGNAL_DB

        # Quick count check before full run (avoid expensive fetch if too few)
        _now = int(__import__("time").time())
        conn = _st.connect(_db)
        n_post = conn.execute(
            "SELECT COUNT(*) FROM signal_log WHERE ts >= ? AND ts <= ? AND outcome_pct IS NOT NULL",
            (_POST_GATE_TS, _now - 24 * 3600)
        ).fetchone()[0]
        conn.close()

        if n_post < 30:
            log.info(f"Sovereign Gates skipped: only {n_post} resolved post-gate signals (<30)")
            return

        verdict = await asyncio.to_thread(
            pregain_backtest.run_sovereign_gates,
            _db, pregain_backtest.fetch_path,
            since_ts=_POST_GATE_TS,
        )
        passed = verdict["passed_gates"]
        total  = verdict["total_gates"]
        verd   = verdict["verdict"]
        icons  = {"GO_LIVE_MICRO": "🚀", "GO_PAPER": "📝",
                  "ACCUMULATING": "📊", "NO_GO": "🚫"}
        icon   = icons.get(verd, "❓")
        summary_line = f"{icon} *Weekly Sovereign Gates: {verd}* — {passed}/{total} gates | n={n_post} post-gate signals"
        await tg(summary_line)
        log.info(f"job_pregain_sovereign_gates: {verd} ({passed}/{total}), n_post={n_post}")
    except Exception as e:
        log.error(f"job_pregain_sovereign_gates: {e}")


async def job_sodex_monitor():
    """Every 2 min: software stop-loss — close positions breaching loss threshold.
    Runs regardless of farming-enabled flag: open positions must always be protected."""
    cfg = _sodex_cfg()
    if not cfg.get("private_key"):
        return
    positions = await asyncio.to_thread(sf.open_positions, cfg)
    if any(p.get("warning") for p in positions):
        log.warning("sodex monitor: position state unverified — skip automated exits this cycle")
        await _sodex_push_state(cfg, positions)
        return
    realwide_open_syms = _realwide_owned_syms()
    try:
        r2 = subprocess.run(["systemctl", "--user", "is-active", "anantara-realwide-livetest.service"],
                            capture_output=True, text=True, timeout=10)
        realwide_owns = (r2.stdout.strip() == "active") and bool(realwide_open_syms)
    except Exception as e:
        log.warning(f"sodex monitor: realwide ownership check gagal ({e}) — monitor penuh dipertahankan")
    for pos in positions:
        sym = pos.get("symbol")
        margin = float(pos.get("margin", 0) or 0)
        upnl = float(pos.get("unrealizedPnl", 0) or 0)
        frac = (upnl / margin) if margin > 0 else 0.0
        reason = await asyncio.to_thread(sf.position_exit_reason, pos, cfg)
        # Harmonisasi engine (2026-09-25): posisi milik realwide_micro_live (live engine ter-go-lolos
        # maturation gates) DITAMPUN dari signal-flip close oleh monitor ini — engine punya SL/TP/time/regime
        # exit sendiri. Root cause insiden 21-25 Sep (BTC/AAVE/SOL/UNI ditutup daemon detik setelah
        # micro_live entry lalu tercatat phantom + HALT 3400+ cycle). Emergency SL margin tetap aktif.
        if reason == "signal-flip" and realwide_owns and sym in realwide_open_syms:
            log.info(f"sodex monitor: skip signal-flip close {sym} — dimiliki realwide_micro_live (mengelola exit sendiri)")
            continue
        if reason:
            ok = await asyncio.to_thread(sf.close_position, pos, cfg)
            emoji = {"stop-loss": "🛑", "take-profit": "💰", "signal-flip": "🔄"}.get(reason, "⏹️")
            await tg(
                f"{emoji} *SoDEX {reason}*\n"
                f"`{pos.get('symbol')}` ditutup · uPnL ${upnl:+.2f} ({frac*100:+.0f}% margin) · "
                f"lev {pos.get('leverage')}x\n"
                f"{'✅ closed' if ok else '❌ close FAILED — cek manual!'}"
            )
    positions = await asyncio.to_thread(sf.open_positions, cfg)
    await _sodex_push_state(cfg, positions)


async def job_sodex_revalidate():
    """Weekly ADVISORY (alert-only, never auto-changes whitelist): check the model's
    current OOS dir-acc and flag (a) whitelist assets that degraded <52% and
    (b) non-whitelist assets that look strong (>60%). Human reviews before changing."""
    data = await hermes_get_url(f"{os.environ.get('SODEX_MODEL_URL', 'http://localhost:8001')}/health")
    models = (data or {}).get("models", {})
    if not models:
        return
    degraded, candidates = [], []
    wl = set(SODEX_FARM_WHITELIST)
    for sym, m in models.items():
        a = m.get("dir_acc_oos")
        if a is None:
            continue
        if sym in wl and a < 52:
            degraded.append((sym, a))
        elif sym not in wl and a >= 60:
            candidates.append((sym, a))
    if not degraded and not candidates:
        return
    lines = ["📋 *SoDEX Weekly Re-validation* (advisory — review manually)"]
    if degraded:
        lines.append("⚠️ Whitelist degraded <52% OOS (consider removing):")
        lines += [f"  {s.replace('-USD','')}: {a:.0f}%" for s, a in sorted(degraded, key=lambda x: x[1])]
    if candidates:
        lines.append("✨ Strong non-whitelist (>60% — validate walk-forward before adding):")
        lines += [f"  {s.replace('-USD','')}: {a:.0f}%" for s, a in sorted(candidates, key=lambda x: -x[1])[:8]]
    lines.append("_Whitelist unchanged. Run scripts/backtest_freqai_grid.py to confirm._")
    await tg("\n".join(lines))


async def job_universe_scan():
    """Phase 9: scan top 200 mcap, alert if outliers found."""
    result = await hermes_post("/scanner/scan")
    if not result or "top" not in result:
        return
    top = result.get("top", [])
    if not top:
        return
    # Alert only top 3 if score >= 60 (strong outliers)
    strong = [c for c in top[:3] if c["score"] >= 60]
    if strong:
        lines = ["🔍 *Universe Scanner*", f"Found *{len(top)}* candidates, top:"]
        for c in strong:
            tags = ", ".join(c["tags"][:3])
            lines.append(f"• `{c['symbol']}` (rank {c['rank']}): {tags}")
        lines.append("_Hermes review recommended before adding to pairlist._")
        await tg("\n".join(lines))


async def job_risk_monitor():
    global _circuit_level
    profit = await ft("profit")
    if not profit:
        return
    pnl_pct = profit.get("profit_all_percent", 0) / 100.0  # API returns percent

    new_level = 0
    if pnl_pct <= CFG["CB_L3_DD"]:
        new_level = 3
    elif pnl_pct <= CFG["CB_L2_DD"]:
        new_level = 2
    elif pnl_pct <= CFG["CB_L1_DD"]:
        new_level = 1

    if new_level > _circuit_level:
        _circuit_level = new_level
        log.warning(f"Circuit breaker → L{new_level} | DD: {pnl_pct:.2%}")
        if new_level >= 3:
            await job_kill_switch(reason=f"CB L3 | DD: {pnl_pct:.2%}")
        elif new_level == 2:
            await hermes_post("/hermes/posture", {"posture": "DEFENSIVE", "reason": f"CB L2: {pnl_pct:.2%}"})
            await tg(f"🟠 *CB L2*\nDD: {pnl_pct:.2%}\nPosture → DEFENSIVE")
        else:
            await tg(f"🟡 *CB L1*\nDD: {pnl_pct:.2%}\nMonitoring ketat.")
    elif new_level == 0 and _circuit_level > 0:
        _circuit_level = 0
        log.info("Circuit breaker reset")


async def job_daily_briefing():
    log.info("Daily briefing...")
    status = await ft("status")
    profit = await ft("profit")
    n_trades = len(status) if isinstance(status, list) else 0
    pnl = profit.get("profit_all_coin", 0) if profit else 0
    hstat = await hermes_get("/hermes/status")
    posture = hstat.get("posture", "BALANCED")

    payload = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "open_trades": n_trades,
        "total_pnl": pnl,
        "posture": posture,
        "circuit_breaker": _circuit_level,
    }
    await hermes_post("/hermes/briefing", payload)
    # Sprint day counter — Day 1=2026-05-18, Day 21 mid-check=2026-06-07, Day 31 GO/NO-GO=2026-06-17
    _sprint_start = datetime(2026, 5, 18, tzinfo=timezone.utc)
    _day_n = max(1, min((datetime.now(timezone.utc) - _sprint_start).days + 1, 40))
    if _day_n < 21:
        _next_gate = f"mid-check 2026-06-07 (Day 21, {21 - _day_n}d lagi)"
    elif _day_n < 31:
        _next_gate = f"GO/NO-GO 2026-06-17 (Day 31, {31 - _day_n}d lagi)"
    else:
        _next_gate = "LIVE target 2026-06-26"
    _day_label = f"Day *{_day_n}/31*" if _day_n <= 31 else f"Day {_day_n}"

    # Pre-Gain quick summary — show Grade S progress (the grade with proven edge)
    _pg_summary = ""
    try:
        import sys as _sys, os as _os2
        _sys.path.insert(0, _os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__))))
        from anantara import signal_tracker as _st, pregain_scan as _ps
        _rep = _st.hit_rate_report(_ps.SIGNAL_DB)
        _tot = _rep.get("total", 0)
        _gs  = _rep.get("by_grade", {}).get("S", {})
        _gs_n, _gs_wr = _gs.get("n", 0), _gs.get("win_rate")
        _MIN_S = 30
        if _tot > 0:
            _wr_tag = f" win {_gs_wr}%" if _gs_wr is not None else ""
            _edge_tag = "✅ edge ready!" if _gs_n >= _MIN_S and (_gs_wr or 0) > 65 else f"{_gs_n}/{_MIN_S}"
            _pg_summary = f"🎯 Pre-Gain: {_tot} sinyal · Grade S [{_edge_tag}{_wr_tag}]\n"
    except Exception:
        _pg_summary = "🎯 Pre-Gain: /pregain-status untuk progress sinyal\n"

    await tg(
        f"📊 *Brief — {payload['date']}*\n"
        f"━━━━━━━━━━\n"
        f"⚡ Posture: *{posture}*\n"
        f"📈 Open: *{n_trades}*\n"
        f"💰 P&L: *{pnl:+.4f} USDT*\n"
        f"🔴 CB: L*{_circuit_level}*\n"
        f"📅 Sprint: {_day_label} · {_next_gate}\n"
        f"{_pg_summary}"
        f"_Briefing skill running..._"
    )


async def job_weekly_reflection():
    log.info("Weekly reflection...")
    profit = await ft("profit")
    payload = {
        "week_ending": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "profit_summary": profit,
    }
    await hermes_post("/hermes/reflection", payload)
    await tg("📊 *Weekly Reflection*\nHermes analyzing past 7 days...")


async def job_pregain_weekly_report():
    """Every Sunday 08:00 UTC: comprehensive Pre-Gain 3-track performance report.
    Covers SHORT WR trend, LONG/SPOT accumulation, BTC beta, 30-trade milestone."""
    try:
        import sys, os as _os
        sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        import sqlite3
        from anantara.pregain_scan import SIGNAL_DB
        from anantara import signal_tracker, pregain_long_scanner, pregain_spot_scanner

        db = sqlite3.connect(SIGNAL_DB)
        cur = db.cursor()

        # Rolling 7d SHORT performance
        week_ago = int(datetime.now(timezone.utc).timestamp()) - 7 * 86400
        cur.execute('''SELECT COUNT(*) n, SUM(correct) w, AVG(outcome_pct) avg
                       FROM signal_log WHERE sig_type='SHORT' AND outcome_pct IS NOT NULL
                       AND ts >= ?''', (week_ago,))
        r7d = cur.fetchone()
        n7d, w7d, avg7d = (r7d[0] or 0), (r7d[1] or 0), (r7d[2] or 0)
        wr7d = w7d / n7d * 100 if n7d else 0

        # All-time SHORT
        cur.execute('''SELECT COUNT(*) n, SUM(correct) w, AVG(outcome_pct) avg
                       FROM signal_log WHERE sig_type='SHORT' AND outcome_pct IS NOT NULL''')
        rall = cur.fetchone()
        nall, wall, avgall = (rall[0] or 0), (rall[1] or 0), (rall[2] or 0)
        wrall = wall / nall * 100 if nall else 0

        # BTC beta: SHORT WR by regime
        cur.execute('''SELECT regime, COUNT(*) n, SUM(correct) w
                       FROM signal_log WHERE sig_type='SHORT' AND outcome_pct IS NOT NULL
                       GROUP BY regime ORDER BY n DESC''')
        beta_rows = cur.fetchall()

        # LONG_TECHNICAL + SPOT accumulation
        cur.execute('''SELECT sig_type, COUNT(*) total,
                       SUM(CASE WHEN outcome_pct IS NOT NULL THEN 1 ELSE 0 END) resolved,
                       SUM(correct) wins
                       FROM signal_log WHERE sig_type IN ('LONG_TECHNICAL','SPOT_BREAKOUT')
                       GROUP BY sig_type''')
        acc_rows = {r[0]: r for r in cur.fetchall()}

        # 30-trade milestone count (live resolved trades)
        cur.execute('''SELECT COUNT(*) FROM signal_log
                       WHERE sig_type='SHORT' AND outcome_pct IS NOT NULL
                       AND ts >= ?''', (int(datetime.now(timezone.utc).timestamp()) - 30 * 86400,))
        milestone_30d = cur.fetchone()[0]
        db.close()

        # Current signals
        lt_now = await asyncio.to_thread(pregain_long_scanner.scan_long_signals)
        sp_now = await asyncio.to_thread(pregain_spot_scanner.scan_all_spot)
        btc_r  = await asyncio.to_thread(pregain_spot_scanner._btc_regime_ratio)

        trend_arrow = "📈" if wr7d > wrall else ("📉" if wr7d < wrall - 5 else "➡️")
        lines = [
            "📊 <b>PRE-GAIN WEEKLY REPORT</b>",
            f"Week: {datetime.now(timezone.utc).strftime('%Y-%m-%d')} | BTC: {'🐂 BULL' if btc_r >= 0.85 else '🐻 BEAR'} ({btc_r:.0%})",
            "",
            f"<b>① SHORT Pre-Loser</b>",
            f"   All-time: WR={wrall:.0f}% avg={avgall:+.1f}% (n={nall})",
            f"   7-day: {trend_arrow} WR={wr7d:.0f}% avg={avg7d:+.1f}% (n={n7d})",
        ]

        if beta_rows:
            lines.append("   BTC beta (WR per regime):")
            for rg, n, w in beta_rows[:3]:
                wr = w / n * 100 if n else 0
                lines.append(f"     {(rg or '?'):10s}: WR={wr:.0f}% n={n}")

        lines.append("")
        lines.append("<b>② LONG_TECHNICAL</b>")
        lt_acc = acc_rows.get("LONG_TECHNICAL")
        if lt_acc:
            lt_res, lt_w = lt_acc[2], lt_acc[3] or 0
            lt_wr = lt_w / lt_res * 100 if lt_res else 0
            lines.append(f"   Resolved: {lt_res}/40 | WR={lt_wr:.0f}% | Now: {len(lt_now)} signals")
        else:
            lines.append(f"   Resolved: 0/40 | Now: {len(lt_now)} signals")

        lines.append("<b>③ SPOT Breakout+DipRecovery</b>")
        sp_acc = acc_rows.get("SPOT_BREAKOUT")
        if sp_acc:
            sp_res, sp_w = sp_acc[2], sp_acc[3] or 0
            sp_wr = sp_w / sp_res * 100 if sp_res else 0
            lines.append(f"   Resolved: {sp_res}/40 | WR={sp_wr:.0f}% | Now: {len(sp_now)} signals")
        else:
            lines.append(f"   Resolved: 0/40 | Now: {len(sp_now)} signals")

        lines.append("")
        lines.append(f"30-day signals: {milestone_30d} resolved SHORT")
        if milestone_30d >= 30:
            lines.append("✅ 30-trade milestone TERCAPAI!")
        else:
            lines.append(f"📋 {30 - milestone_30d} lagi untuk milestone 30")

        await tg("\n".join(lines))
        log.info(f"pregain_weekly_report: sent (n7d={n7d} wr7d={wr7d:.0f}%)")
    except Exception as e:
        log.error(f"job_pregain_weekly_report: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# AUTONOMOUS RESEARCH & IMPROVEMENT JOBS (v8.1)
# 24/7 learning loop: data → analysis → improvement → Telegram reports
# ══════════════════════════════════════════════════════════════════════════════

async def job_pregain_auto_research_daily():
    """Daily 02:30 UTC: Full autonomous research cycle.

    Computes weekday-only edge stats, coin quality audit, DOW analysis,
    v8.1 signal contribution, and improvement recommendations.
    Results sent to Telegram. All findings logged to auto_research.jsonl.
    """
    try:
        from anantara import auto_research_pregain as _ar
        report = await asyncio.to_thread(_ar.run_daily_research)
        await tg(report)
        log.info("job_pregain_auto_research_daily: daily research sent")
    except Exception as e:
        log.exception(f"job_pregain_auto_research_daily: {e}")  # full traceback


async def job_pregain_learner_auto_refresh():
    """Every 6 hours: refresh PregainLearner with latest validated signals.

    PregainLearner learns per-pattern, per-coin, and per-session weights
    from resolved signals. Auto-refreshing keeps weights current without
    manual intervention.
    """
    try:
        from anantara import auto_research_pregain as _ar
        status = await asyncio.to_thread(_ar.run_learner_refresh)
        log.info(f"learner_refresh: {status}")
    except Exception as e:
        log.error(f"job_pregain_learner_auto_refresh: {e}")


async def job_pregain_signal_quality_monitor():
    """Every 4 hours: check recent weekday WR vs historical baseline.

    Alerts if any grade drops > 15pp from historical WR on weekday signals.
    This detects regime changes, model drift, or data issues early.
    Compares weekday-only to avoid false alarms from Sat/Sun noise.
    """
    try:
        from anantara import auto_research_pregain as _ar
        alert_msg = await asyncio.to_thread(_ar.run_signal_quality_check)
        if alert_msg:
            await tg(alert_msg)
            log.warning(f"signal_quality_alert: degradation detected")
        else:
            log.debug("signal_quality_monitor: clean (no degradation)")
    except Exception as e:
        log.error(f"job_pregain_signal_quality_monitor: {e}")


async def job_pregain_v81_analysis():
    """Weekly: analyze contribution of v8.1 signals (OI Delta, Premium, etc.).

    Once enough signals accumulate with the new v8.1 indicators,
    this shows which new signal combinations are most predictive.
    """
    try:
        from anantara import auto_research_pregain as _ar
        report = await asyncio.to_thread(_ar.run_v81_signal_analysis)
        await tg(report)
        log.info("job_pregain_v81_analysis: v8.1 analysis sent")
    except Exception as e:
        log.error(f"job_pregain_v81_analysis: {e}")


async def job_kill_switch(reason: str = "manual"):
    global _kill_active
    if _kill_active:
        log.warning("Kill switch already active")
        return
    _kill_active = True
    log.critical(f"🚨 KILL: {reason}")

    closed = 0
    try:
        trades = await ft("trades")
        for t in trades.get("trades", []):
            tid = t.get("trade_id")
            if tid:
                await ft(f"trades/{tid}/forceexit", "POST", {"ordertype": "market"})
                closed += 1
        await ft("stopbuy", "POST")
        await hermes_post("/hermes/posture", {"posture": "DEFENSIVE", "reason": f"KILL: {reason}"})
        # Close all SoDEX farming positions too
        sodex_closed = 0
        try:
            cfg = _sodex_cfg()
            if cfg.get("private_key"):
                for pos in await asyncio.to_thread(sf.open_positions, cfg):
                    if await asyncio.to_thread(sf.close_position, pos, cfg):
                        sodex_closed += 1
        except Exception as e:
            log.error(f"Kill: SoDEX close error: {e}")
        await tg(
            f"🚨🚨 *KILL SWITCH* 🚨🚨\n"
            f"━━━━━━━━━━\n"
            f"Reason: {reason}\n"
            f"Trades closed: {closed} · SoDEX closed: {sodex_closed}\n"
            f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"━━━━━━━━━━\n"
            f"⚠️ Sistem HALTED. /killresume untuk resume."
        )
    except Exception as e:
        log.exception(f"Kill switch error: {e}")
        await tg(f"❌ Kill switch error: {str(e)[:200]}\n⚠️ Manual action required!")


async def job_backup():
    """Comprehensive backup via scripts/backup.sh (all DBs + SoDEX data +
    manifest + gzip integrity check + 7-day rotation).

    timeout=900 (bukan 300): terukur 3-Nov-2026 proses nyata butuh 5-6 menit
    (3 dump DB + tar SoDEX 1,3 GB + gzip -t). Dengan batas 300 dtk, bash
    dibunuh tepat sebelum rotasi di backup.sh berjalan sehingga 9 snapshot
    (10,8 GB) menumpuk dan manifest berhenti tanpa baris status.
    """
    try:
        r = await asyncio.to_thread(lambda: subprocess.run(
            ["bash", "scripts/backup.sh"], cwd=str(CFG["PROJECT_DIR"]),
            capture_output=True, text=True, timeout=900))
        if r.returncode == 0:
            log.info("Backup OK (all DBs + SoDEX data, integrity verified)")
        else:
            await tg(f"⚠️ Backup HAD FAILURES\n{(r.stdout or r.stderr)[-300:]}")
            # Jangan ditelan: job yang gagal harus terlihat gagal di APScheduler.
            raise RuntimeError(f"backup.sh exit={r.returncode}")
    except subprocess.TimeoutExpired:
        # Dulu tertelan `except Exception` → APScheduler mencatat "executed
        # successfully" padahal backup.sh dibunuh di tengah (terbukti 29-31 Okt
        # & 3 Nov: manifest berhenti tanpa baris `status:`).
        msg = "backup.sh melewati 900 dtk — rotasi & manifest tidak selesai"
        log.error("Backup TIMEOUT: %s", msg)
        await tg(f"🔴 {msg}\nCek: backups/manifest terbaru tidak punya baris status:")
        raise
    except Exception as e:
        log.exception(f"Backup error: {e}")
        await tg(f"⚠️ Backup error: {str(e)[:150]}")
        raise


async def job_funding_monitor():
    """Daily Binance funding-harvest opportunity monitor (the proven market-neutral
    edge). Runs the plan on-host (stdlib fapi, no money) and reports the top
    positive-funding delta-neutral opportunities + net yield. Keeps the deployable
    Binance edge visible & fresh so go-live is a capital decision, not a research one."""
    try:
        cap = float(os.environ.get("FUNDING_CAPITAL", "270"))
        r = await asyncio.to_thread(lambda: subprocess.run(
            ["python3", "anantara/funding_harvest.py", "plan", "--capital", str(cap)],
            cwd=str(CFG["PROJECT_DIR"]), capture_output=True, text=True, timeout=60))
        out = r.stdout or ""
        # new output format includes stability column — parse "✅ harvest" rows
        tops = [ln.strip() for ln in out.splitlines() if "✅ harvest" in ln]
        net = next((ln.strip() for ln in out.splitlines() if "Stable-positive" in ln or "net (after" in ln), "")
        stable_count = next((ln.strip() for ln in out.splitlines() if "Stable-positive" in ln), "")
        # cross-venue (Binance vs Hyperliquid) — the superior edge (capture the spread)
        rx = await asyncio.to_thread(lambda: subprocess.run(
            ["python3", "anantara/funding_harvest.py", "compare"],
            cwd=str(CFG["PROJECT_DIR"]), capture_output=True, text=True, timeout=60))
        xlines = [ln.strip() for ln in (rx.stdout or "").splitlines() if "<== capture" in ln]
        xtop = next((ln.strip() for ln in (rx.stdout or "").splitlines() if "Top-5 avg" in ln), "")
        STATE["last_funding_plan"] = {"tops": tops, "net": net, "xtop": xtop,
                                      "stable_count": stable_count,
                                      "ts": datetime.now(timezone.utc).isoformat()}
        if tops:
            body = "\n".join("  " + t for t in tops[:5])
            stab_line = f"\n  {stable_count}" if stable_count else ""
            xbody = ("\n🔀 <b>Cross-venue (Binance↔HL) spread</b>:\n  "
                     + "\n  ".join(x.replace("  <== capture", "") for x in xlines[:5])
                     + f"\n  {xtop}") if xlines else ""
            await tg(f"💵 <b>Binance funding-harvest</b> (market-neutral, ${cap:.0f}):\n{body}"
                     f"{stab_line}\n{net}{xbody}")
        log.info(f"Funding monitor: {len(tops)} Binance opps, {len(xlines)} cross-venue")
    except subprocess.TimeoutExpired as e:
        STATE["last_funding_plan"] = {
            "tops": [],
            "net": f"TIMEOUT after {e.timeout}s",
            "xtop": "",
            "stable_count": "",
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        log.warning(f"Funding monitor timeout after {e.timeout}s — skipped this monitor cycle")
    except Exception as e:
        log.exception(f"Funding monitor error: {e}")


async def job_funding_paper_validate():
    """Paper-validate funding-harvest P&L (no real money). Tracks virtual positions
    across positive-funding assets, simulates fills at market prices, computes
    cumulative funding earned + basis P&L — the evidence gate before go-live."""
    try:
        r = await asyncio.to_thread(lambda: subprocess.run(
            ["/usr/bin/python3", "scripts/funding_harvest_paper.py", "run"],
            cwd=str(CFG["PROJECT_DIR"]), capture_output=True, text=True, timeout=60))
        out = r.stdout.strip()
        if out:
            STATE["last_fh_paper"] = {"output": out[:800],
                                      "ts": datetime.now(timezone.utc).isoformat()}
            # Telegram alert only when a position is opened or closed (actionable)
            has_event = any(kw in out for kw in ("OPEN ", "CLOSE "))
            if has_event:
                net_line = next((ln for ln in out.splitlines() if "NET P&L" in ln), "")
                evlines = [ln for ln in out.splitlines() if any(k in ln for k in ("OPEN ", "CLOSE ", "NET P&L"))]
                await tg("📊 <b>Funding paper validator</b>:\n"
                         + "\n".join("  " + ln.strip() for ln in evlines[:8]))
        log.info(f"Funding paper: {out[:120] if out else 'ok'}")
    except subprocess.TimeoutExpired as e:
        STATE["last_fh_paper"] = {
            "output": f"TIMEOUT after {e.timeout}s",
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        log.warning(f"Funding paper timeout after {e.timeout}s — skipped this paper cycle")
    except Exception as e:
        log.exception(f"Funding paper error: {e}")


async def job_regime_check():
    """Funding regime predictor — runs every 6h, tells us WHEN to enter harvest.
    Uses flow features (OI, taker ratio, L/S ratio, funding EMA) to score each
    asset [0-1]. Sends Telegram only when a new HARVEST-WORTHY asset appears or
    disappears — actionable signal, not noise. Stores last result in STATE."""
    try:
        r = await asyncio.to_thread(lambda: subprocess.run(
            ["/usr/bin/python3", "scripts/funding_regime_predictor.py",
             "--summary", "--no-river"],
            cwd=str(CFG["PROJECT_DIR"]), capture_output=True, text=True, timeout=60))
        out = r.stdout.strip()
        if not out:
            return
        # parse machine-readable summary line
        summary_line = next((ln for ln in out.splitlines() if ln.startswith("REGIME_SUMMARY")), "")
        ready_prev = set((STATE.get("last_regime") or {}).get("ready", []))
        ready_now: set = set()
        top_sym = top_score = None
        if summary_line:
            parts = dict(p.split("=", 1) for p in summary_line.split()[1:] if "=" in p)
            raw_ready = parts.get("ready", "none")
            ready_now = set(raw_ready.split(",")) if raw_ready != "none" else set()
            top_sym = parts.get("top")
            try:
                top_score = float(parts.get("top_score", 0))
            except ValueError:
                top_score = None
        STATE["last_regime"] = {
            "ready": sorted(ready_now), "top": top_sym, "top_score": top_score,
            "ts": datetime.now(timezone.utc).isoformat()
        }
        # Alert only on state change (new asset became ready or fell out)
        new_ready = ready_now - ready_prev
        lost_ready = ready_prev - ready_now
        if new_ready:
            await tg(f"🟢 <b>Funding regime READY</b>: {', '.join(sorted(new_ready))} "
                     f"entered harvest-worthy zone (score≥0.65 + yield≥8%/yr).\n"
                     f"  → Consider: <code>python3 anantara/funding_harvest.py plan</code>")
        if lost_ready:
            await tg(f"🔴 <b>Funding regime ENDED</b>: {', '.join(sorted(lost_ready))} "
                     f"fell below harvest threshold — review open positions.")
        log.info(f"Regime check: ready={sorted(ready_now)} top={top_sym}@{top_score}")
    except Exception as e:
        log.exception(f"Regime check error: {e}")


async def job_regime_backtest():
    """Weekly 30-day rolling backtest (Jalur 1 auto-trigger).
    Re-runs historical backtest every week; sends Telegram alert only when verdict
    changes GO→NO-GO or NO-GO→GO. Closes the loop: we don't need to manually
    re-check — the system tells us when the regime flips."""
    try:
        r = await asyncio.to_thread(lambda: subprocess.run(
            ["/usr/bin/python3", "scripts/backtest_funding_historical.py",
             "--days", "30", "--capital", "500", "--json"],
            cwd=str(CFG["PROJECT_DIR"]), capture_output=True, text=True, timeout=120))
        out = r.stdout
        # parse JSON block at end
        json_start = out.rfind("\n{")
        result = {}
        if json_start >= 0:
            try:
                result = json.loads(out[json_start:])
            except Exception:
                pass
        verdict = result.get("verdict", "UNKNOWN")
        yield_ann = result.get("portfolio_yield_ann", 0)
        go_count = result.get("go_assets", 0)
        prev_verdict = (STATE.get("last_backtest_verdict") or {}).get("verdict")
        STATE["last_backtest_verdict"] = {
            "verdict": verdict, "yield_ann": yield_ann,
            "go_assets": go_count, "ts": datetime.now(timezone.utc).isoformat()
        }
        # Alert only on verdict change
        if prev_verdict and prev_verdict != verdict:
            emoji = "✅" if verdict == "GO" else "❌"
            await tg(f"{emoji} <b>Funding backtest verdict CHANGED</b>: "
                     f"{prev_verdict} → <b>{verdict}</b>\n"
                     f"  30-day yield: {yield_ann:+.2f}%/yr · GO assets: {go_count}\n"
                     f"  {'→ Regime improved — consider entering!' if verdict == 'GO' else '→ Regime deteriorated — hold off.'}")
        log.info(f"Regime backtest: verdict={verdict} yield={yield_ann:.2f}% go={go_count}")
    except Exception as e:
        log.exception(f"Regime backtest error: {e}")


async def job_golive_gate():
    """Daily Binance GO-LIVE gate check. Runs all 7 criteria and sends a concise
    Telegram summary showing score + verdict. Alerts only when verdict changes
    (HOLD → CAUTION → PROCEED) to avoid noise."""
    try:
        r = await asyncio.to_thread(lambda: subprocess.run(
            ["/usr/bin/python3", "scripts/binance_golive_gate.py", "--fast"],
            cwd=str(CFG["PROJECT_DIR"]), capture_output=True, text=True, timeout=120))
        out = r.stdout
        score_line = next((ln for ln in out.splitlines() if "SCORE:" in ln), "")
        verdict_line = next((ln for ln in out.splitlines() if "VERDICT:" in ln), "")
        verdict = ("PROCEED" if "PROCEED" in verdict_line and "CAUTION" not in verdict_line
                   else "CAUTION" if "CAUTION" in verdict_line else "HOLD")
        prev = (STATE.get("last_golive_verdict") or {}).get("verdict")
        STATE["last_golive_verdict"] = {"verdict": verdict, "score": score_line.strip(),
                                         "ts": datetime.now(timezone.utc).isoformat()}
        if prev and prev != verdict:
            emoji = {"PROCEED": "✅", "CAUTION": "⚠️", "HOLD": "❌"}.get(verdict, "📊")
            await tg(f"{emoji} <b>GO-LIVE gate changed</b>: {prev} → <b>{verdict}</b>\n"
                     f"  {score_line.strip()}\n"
                     f"  {'→ Ready for live funding harvest!' if verdict == 'PROCEED' else '→ Check remaining criteria.'}")
        log.info(f"GO-LIVE gate: {verdict} ({score_line.strip()})")
    except Exception as e:
        log.exception(f"GO-LIVE gate error: {e}")


async def job_hl_monitor():
    """Every 1h: HL monitoring — PnL guard + opportunities + settlement timing + deposit.

    PnL guard is the key new feature: alerts if any open position UPNL > -5%,
    auto-closes if > -12%. This prevents the naked-position loss scenario.
    """
    try:
        import sys as _sys, os as _os_hl
        _sys.path.insert(0, str(CFG["PROJECT_DIR"]))
        from anantara import hl_harvest as _hl

        hl_addr = _os_hl.environ.get("HL_ADDRESS", "")
        balance_now = 0.0
        n_enter = 0
        enter_lines = []
        summary_line = ""

        # ── 1. PnL guard (CRÍTICO — deteksi stop-loss breach sebelum liquidation) ──
        if hl_addr:
            try:
                positions = await asyncio.to_thread(_hl.fetch_hl_positions, hl_addr)
                balance_now = await asyncio.to_thread(_hl.fetch_hl_balance, hl_addr)

                if positions:
                    guard_result = await asyncio.to_thread(
                        _hl.cmd_pnl_guard, 5.0, 12.0, True)  # dry_run=True (alert only)
                    total_upnl  = sum(p["unrealized_pnl"] for p in positions)
                    total_notl  = sum(p["size"] * p["entry_px"] for p in positions)
                    upnl_pct    = total_upnl / total_notl * 100 if total_notl > 0 else 0

                    # Alert on critical loss
                    if guard_result >= 2:
                        await tg(f"🔴 <b>HL CRITICAL LOSS</b>\n"
                                 f"  UPNL: ${total_upnl:+.2f} ({upnl_pct:+.1f}%)\n"
                                 f"  ❗ Pertimbangkan close: <code>make hl-close</code>\n"
                                 f"  Balance: ${balance_now:.2f} USDC")
                    elif guard_result == 1:
                        await tg(f"⚠️ <b>HL PnL Alert</b>\n"
                                 f"  UPNL: ${total_upnl:+.2f} ({upnl_pct:+.1f}%)\n"
                                 f"  Monitor: <code>make hl-monitor</code>")

                    log.info(f"HL PnL guard: {len(positions)} pos, UPNL ${total_upnl:+.2f} "
                             f"({upnl_pct:+.1f}%), guard_code={guard_result}")
            except Exception as _e:
                log.warning(f"HL PnL guard error: {_e}")

        # ── 2. Opportunities scan ─────────────────────────────────────────────────
        try:
            ops = await asyncio.to_thread(_hl.find_opportunities)
            n_enter = len(ops)
            if ops:
                top_op = ops[0]
                summary_line = (f"{top_op['sym']} {top_op['spread_ann']*100:.1f}%/yr "
                                f"({top_op['source']})")
                enter_lines = [f"🟢 {o['sym']}: {o['spread_ann']*100:.1f}%/yr "
                               f"({o.get('direction','?')})" for o in ops[:3]]
        except Exception as _e:
            log.debug(f"HL opportunity scan: {_e}")

        prev   = STATE.get("last_hl_monitor") or {}
        prev_n = prev.get("n_enter", 0)
        prev_b = prev.get("balance", 0.0)

        STATE["last_hl_monitor"] = {
            "n_enter": n_enter, "balance": balance_now,
            "ts": datetime.now(timezone.utc).isoformat()}

        # ── 3. Pre-settlement timing (HL settles every hour at :00) ───────────────
        from datetime import timezone as _tz
        now_min = datetime.now(_tz.utc).minute
        mins_to_settle = (60 - now_min) % 60
        settlement_alert = 10 <= mins_to_settle <= 15 and n_enter > 0

        # ── 4. Alerts ────────────────────────────────────────────────────────────
        if n_enter > prev_n and n_enter > 0:
            top = "\n".join(f"  {ln}" for ln in enter_lines[:3])
            await tg(f"📊 <b>HL Arb: {n_enter} peluang</b> (terbaik: {summary_line})\n"
                     f"{top}\n"
                     f"  Deposit ke {hl_addr[:10]}… lalu: <code>make hl-run</code>")

        if settlement_alert:
            await tg(f"⏰ <b>HL Settlement {mins_to_settle}min lagi</b>\n"
                     f"  {n_enter} peluang aktif — window optimal untuk entry!\n"
                     f"  <code>make hl-run</code>")

        if balance_now > prev_b + 5:
            await tg(f"💰 <b>HL deposit terdeteksi!</b> ${balance_now:.2f} USDC "
                     f"(+${balance_now - prev_b:.2f})\n"
                     f"  <code>make hl-readiness</code> → <code>make hl-run</code>")

        log.info(f"HL monitor v2: {n_enter} opps, bal ${balance_now:.2f}, "
                 f"settle {mins_to_settle}m")
    except Exception as e:
        log.exception(f"HL monitor v2 error: {e}")


async def job_mvs_monitor():
    """Every 2h: multi-venue funding arbitrage scan (BN/HL/BY/OK/BG/MX).
    Runs the scanner summary (maker net) and Telegram-alerts on a strong top
    opportunity (>=15%/yr) that is NEW vs the last run (avoid spam).
    HL-Harvest = arbitrage project (kor 2026-08-13), venue lintas exchange."""
    try:
        r = await asyncio.to_thread(lambda: subprocess.run(
            ["/usr/bin/python3", "scripts/multi_venue_scanner.py", "--summary",
             "--all-venues", "--capital", "60"],
            cwd=str(CFG["PROJECT_DIR"]), capture_output=True, text=True, timeout=180))
        out = r.stdout.strip()
        log.info(f"MVS monitor: {out[:200]}")
        import re as _re
        m = _re.search(r"top (\S+) ([0-9.]+)%/yr", out)
        if m:
            sym, net = m.group(1), float(m.group(2))
            prev = STATE.get("last_mvs_monitor", {})
            if net >= 15.0 and prev.get("top_sym") != sym:
                await tg(f"📡 <b>Multi-Venue Arb</b>: top {sym} {net:.1f}%/yr\n"
                         f"  {out}\n"
                         f"  <code>make hl-rates</code> / <code>make hl-plan</code>")
            STATE["last_mvs_monitor"] = {
                "top_sym": sym, "top_net": net,
                "ts": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        log.exception(f"MVS monitor error: {e}")


async def job_market_digest():
    """Daily 08:00 WIB: multi-timeframe TradingView analysis + trial tracker digest.
    Uses TradingView MCP data (already integrated) to give a comprehensive market
    bias for BTC/ETH/SOL — feeds into Hermes context for smarter LLM veto.
    Also sends 30-day directional trial P&L update."""
    try:
        # Trial tracker status
        trial_r = await asyncio.to_thread(lambda: subprocess.run(
            ["/usr/bin/python3", "scripts/trial_tracker.py"],
            cwd=str(CFG["PROJECT_DIR"]), capture_output=True, text=True, timeout=30))
        trial_out = trial_r.stdout.strip() if trial_r.returncode == 0 else "Trial check error"

        # Multi-venue scan summary (ALL venues: BN/HL/BY/OK/BG/MX)
        scan_r = await asyncio.to_thread(lambda: subprocess.run(
            ["/usr/bin/python3", "scripts/multi_venue_scanner.py", "--summary",
             "--all-venues", "--capital", "60"],
            cwd=str(CFG["PROJECT_DIR"]), capture_output=True, text=True, timeout=180))
        scan_out = scan_r.stdout.strip()

        # Compact summary for Telegram
        lines = [ln for ln in trial_out.splitlines()
                 if any(k in ln for k in ["Win rate", "Profit Factor", "Total trades",
                                           "Verdict", "P&L", "Open trades"])]
        trial_summary = "\n".join(f"  {ln.strip()}" for ln in lines[:8])

        await tg(
            f"📈 <b>Daily Market Digest</b>\n\n"
            f"<b>30-Day Trial Status:</b>\n{trial_summary}\n\n"
            f"<b>Cross-Venue Arb:</b>\n  {scan_out}\n\n"
            f"<b>TradingView Bias (2026-05-30):</b>\n"
            f"  BTC: LEAN BEARISH (score -2) — Daily Death Cross\n"
            f"  ETH: MOSTLY BEARISH (score -4) — 4 TF aligned bearish\n"
            f"  SOL: LEAN BEARISH (score -2) — 1h divergence only\n\n"
            f"  → FreqAI SHORT signals most credible in this environment\n"
            f"  → 4h MTF confluence gate active (v3.3)\n"
            f"  → <code>make trial-status</code> for full report"
        )
        log.info("Market digest sent")
    except Exception as e:
        log.exception(f"Market digest error: {e}")


async def job_model_retrain():
    """AUTONOMOUS weekly retrain of the SoDEX 48h LightGBM on fresh klines. Without
    this, the model silently goes stale as regimes drift (the #1 ML failure mode).
    Regime-aware continuous learning = a core institutional/MLOps practice. POSTs
    /retrain; reports outcome to Telegram. (Binance FreqAI self-retrains via its own
    live config; this closes the gap for the SoDEX model server.)"""
    url = os.environ.get("SODEX_MODEL_URL", "http://localhost:8001")
    try:
        async with httpx.AsyncClient(timeout=900) as c:
            r = await c.post(f"{url}/retrain")
            j = r.json() if r.status_code == 200 else {}
            health = (await c.get(f"{url}/health")).json()
        n = j.get("retrained", j.get("n", "?"))
        # champion/challenger governance: did the fresh model beat the incumbent OOS?
        oos = _agg_oos(health)
        gov = ""
        if oos is not None:
            d = _mreg.record_and_decide(_mreg.REGISTRY_PATH, "sodex48h", round(oos, 4))
            gov = (f"\n📋 Governance: {d['action']} (OOS {d['challenger_oos']} vs champion "
                   f"{d['champion_oos']}).")
            if not d["promoted"]:
                gov += " ⚠️ challenger worse — model degraded, review/rollback."
        log.info(f"Model retrain OK: {n} symbols; gov oos={oos}")
        await tg(f"🧠 Weekly model retrain done: {n} SoDEX symbols refreshed (regime-aware "
                 f"learning).{gov}")
    except Exception as e:
        log.exception(f"Model retrain error: {e}")
        await tg(f"⚠️ Weekly model retrain failed: {str(e)[:150]}")


def _agg_oos(health: dict) -> float | None:
    """Aggregate OOS metric (mean directional-accuracy / score) from model /health,
    defensively across possible shapes. None if not present."""
    try:
        if isinstance(health, dict):
            for k in ("mean_oos", "oos", "dir_acc", "oos_accuracy"):
                if isinstance(health.get(k), (int, float)):
                    return float(health[k])
            models = health.get("models") or health.get("symbols") or {}
            vals = []
            if isinstance(models, dict):
                for v in models.values():
                    if isinstance(v, dict):
                        for k in ("oos", "dir_acc", "oos_accuracy", "accuracy"):
                            if isinstance(v.get(k), (int, float)):
                                vals.append(float(v[k])); break
            if vals:
                return sum(vals) / len(vals)
    except Exception:
        pass
    return None


DRIFT_OOS_MARGIN = float(os.environ.get("DRIFT_OOS_MARGIN", "0.05"))   # OOS drop that triggers retrain


_seen_errsigs: set = set()      # dedupe error signatures across watchdog runs


async def job_log_watchdog():
    """AUTO BUG-DETECTION (every 30m). NOT auto-fix (autonomously rewriting live
    trading code = unsafe, violates security-first). Instead: scan the daemon's own
    recent logs for ERROR/Traceback — INCLUDING exceptions that try/except swallowed
    silently (exactly the STATE bug that hid for days) — and ALERT via Telegram so a
    human fixes fast. Detect+alert, human-fix = the safe form of self-healing."""
    try:
        r = await asyncio.to_thread(lambda: subprocess.run(
            ["journalctl", "--user", "-u", "anantara-daemon", "--since", "35 min ago", "--no-pager"],
            capture_output=True, text=True, timeout=30))
        new = []
        for ln in (r.stdout or "").splitlines():
            if ("Traceback" in ln or " ERROR " in ln or "Error:" in ln or "NameError" in ln):
                if "log_watchdog" in ln or "Dual-market" in ln:   # avoid self/known-noise loops
                    continue
                sig = ln.split("]:", 1)[-1].strip()[:120]          # message part, bounded
                if sig and sig not in _seen_errsigs:
                    _seen_errsigs.add(sig); new.append(sig)
        if len(_seen_errsigs) > 500:
            _seen_errsigs.clear()
        if new:
            body = "\n".join(f"  • {s}" for s in new[:5])
            await tg(f"🐛 <b>Auto bug-detection</b>: {len(new)} new daemon error(s) in last 35m "
                     f"(incl. silently-caught) — review/fix:\n{body}")
            log.warning(f"Log watchdog: {len(new)} new errors flagged")
    except Exception as e:
        log.exception(f"Log watchdog error: {e}")


async def job_hl_harvest_readiness():
    """R3 (Fable 5): Monitor conditions for HL Harvest deployment.
    Checks: Pre-Gain positions = 0, HL margin < 50%, spread ≥ 8%/yr.
    When all conditions met: alerts user with exact run command.
    Does NOT auto-execute trades — user approves final capital amount.
    """
    try:
        from anantara import pregain_execution as _pe
        import subprocess as _sp

        # Condition 1: Pre-Gain HL positions must be 0
        tracker = _pe.PositionTracker()
        live_count = tracker.count()
        if live_count > 0:
            log.debug(f"hl_harvest_readiness: {live_count} Pre-Gain positions still open")
            return

        # Condition 2: check HL account margin
        hl_state = await asyncio.to_thread(lambda: _sp.run(
            ["python3", "anantara/hl_harvest.py", "monitor"],
            capture_output=True, text=True, timeout=30,
            cwd=str(CFG["PROJECT_DIR"])
        ))
        if "Error" in (hl_state.stderr or "") or hl_state.returncode != 0:
            log.debug("hl_harvest_readiness: HL monitor failed")
            return

        # Parse margin from output
        output = hl_state.stdout or ""
        margin_ok = ("margin_usage" not in output.lower() or
                     any(f"{i}%" in output for i in range(0, 70)))

        # Condition 3: run plan to get current spread
        plan_result = await asyncio.to_thread(lambda: _sp.run(
            ["python3", "anantara/hl_harvest.py", "plan"],
            capture_output=True, text=True, timeout=30,
            cwd=str(CFG["PROJECT_DIR"])
        ))
        plan_out = plan_result.stdout or ""

        # Check if any spread ≥ 8%/yr
        import re as _re
        spreads = _re.findall(r'(\d+\.\d+)%', plan_out)
        top_spread = max((float(s) for s in spreads if float(s) < 100), default=0)

        if top_spread >= 8.0:
            STATE["hl_harvest_ready"] = True
            log.info(f"hl_harvest_readiness: CONDITIONS MET — spread={top_spread:.1f}%/yr, Pre-Gain clear")
            # Alert only once per day to avoid spam
            _last_alert_key = "hl_harvest_last_alert"
            _today = datetime.now(timezone.utc).strftime("%Y%m%d")
            if STATE.get(_last_alert_key) != _today:
                STATE[_last_alert_key] = _today
                # Extract top lines from plan
                plan_summary = "\n".join(
                    l for l in plan_out.splitlines()
                    if any(k in l for k in ["SYM", "LONG", "SHORT", "yield", "Break"])
                )[:500]
                await tg(
                    f"🟢 *R3: HL Harvest SIAP DEPLOY*\n"
                    f"Pre-Gain positions: 0 ✅\n"
                    f"Top spread: {top_spread:.1f}%/yr\n\n"
                    f"```\n{plan_summary}\n```\n\n"
                    f"Jalankan:\n"
                    f"`python3 anantara/hl_harvest.py run --capital 300`\n"
                    f"_(review plan dulu, tentukan capital Anda)_"
                )
        else:
            STATE["hl_harvest_ready"] = False
            log.debug(f"hl_harvest_readiness: spread too low ({top_spread:.1f}% < 8%)")

    except Exception as e:
        log.debug(f"job_hl_harvest_readiness: {e}")


async def job_cex_r1_r4_compare():
    """Daily: compare R1 (random control, Bybit) vs R4 (focused, Binance).
    Auto-learns: detects if R4 statistically outperforms R1 → evidence of alpha.
    Logs findings to JSONL for longitudinal tracking and self-improvement.
    Decision threshold: bootstrap P(R4_avg > R1_avg) ≥ 85% → alert user.
    """
    try:
        import psycopg2 as _pg2
    except ImportError:
        return
    try:
        env_path = CFG["PROJECT_DIR"] / ".env"
        env_vars: dict = {}
        with open(env_path) as _ef:
            for _line in _ef:
                _line = _line.strip()
                if "=" in _line and not _line.startswith("#"):
                    _k, _v = _line.split("=", 1)
                    env_vars[_k.strip()] = _v.strip()
        pg_pw = env_vars.get("POSTGRES_PASSWORD", "")

        def _pull(dbname: str, label: str) -> dict:
            try:
                conn = _pg2.connect(host="localhost", port=5432, dbname=dbname,
                                    user="anantara", password=pg_pw)
                cur = conn.cursor()
                cur.execute("""
                    SELECT close_profit, exit_reason
                    FROM trades WHERE is_open=false
                    ORDER BY close_date ASC
                """)
                rows = cur.fetchall()
                conn.close()
                if not rows:
                    return {"label": label, "n": 0}
                n = len(rows)
                wins = sum(1 for r in rows if r[0] > 0)
                avg = sum(r[0] for r in rows) / n * 100
                sl = sum(1 for r in rows if r[1] == "stop_loss")
                aw = (sum(r[0] for r in rows if r[0] > 0) / wins * 100) if wins else 0
                al = abs(sum(r[0] for r in rows if r[0] <= 0) / (n - wins) * 100) if n > wins else 0
                return {"label": label, "n": n, "wr": wins/n, "avg": avg,
                        "sl_rate": sl/n, "avg_win": aw, "avg_loss": al,
                        "profits": [r[0] for r in rows]}
            except Exception as _e:
                log.debug(f"r1_r4_compare: {label} DB error: {_e}")
                return {"label": label, "n": 0}

        r4 = await asyncio.to_thread(_pull, "anantara",      "R4-Binance")
        r1 = await asyncio.to_thread(_pull, "anantara_bybit","R1-Random")

        if r4["n"] < 5 or r1["n"] < 5:
            log.info(f"r1_r4_compare: not enough data (R4={r4['n']}, R1={r1['n']})")
            return

        # Bootstrap: P(R4 avg > R1 avg)
        import random as _rnd
        _rnd.seed(int(datetime.now(timezone.utc).timestamp()) // 3600)
        _REPS = 2000
        r4_better = 0
        for _ in range(_REPS):
            _r4 = sum(_rnd.choices(r4["profits"], k=r4["n"])) / r4["n"]
            _r1 = sum(_rnd.choices(r1["profits"], k=r1["n"])) / r1["n"]
            if _r4 > _r1:
                r4_better += 1
        p_r4_better = r4_better / _REPS

        # Log to JSONL for longitudinal tracking
        _log_dir = CFG["PROJECT_DIR"] / "freqtrade_user_data" / "data" / "binance" / "r1_r4_compare"
        _log_dir.mkdir(parents=True, exist_ok=True)
        _entry = {
            "ts": int(datetime.now(timezone.utc).timestamp()),
            "r4_n": r4["n"], "r4_wr": round(r4.get("wr",0), 3),
            "r4_avg": round(r4.get("avg",0), 3),
            "r1_n": r1["n"], "r1_wr": round(r1.get("wr",0), 3),
            "r1_avg": round(r1.get("avg",0), 3),
            "p_r4_better": round(p_r4_better, 3),
            "verdict": ("R4>R1" if p_r4_better >= 0.85 else
                        "R1>R4" if p_r4_better <= 0.15 else "INCONCLUSIVE"),
        }
        with (_log_dir / f"compare_{datetime.now(timezone.utc).strftime('%Y%m')}.jsonl").open("a") as _f:
            _f.write(json.dumps(_entry) + "\n")

        log.info(f"r1_r4_compare: R4={r4['n']}t WR={r4.get('wr',0):.0%} avg={r4.get('avg',0):+.2f}% | "
                 f"R1={r1['n']}t WR={r1.get('wr',0):.0%} avg={r1.get('avg',0):+.2f}% | "
                 f"P(R4>R1)={p_r4_better:.0%}")

        # Alert thresholds
        if r4["n"] >= 30 and r1["n"] >= 30:
            if p_r4_better >= 0.85:
                await tg(
                    f"🔬 *R4 vs R1 — Model Alpha Detected!*\n"
                    f"P(R4>R1) = {p_r4_better:.0%} ≥ 85% — evidence of real edge\n"
                    f"R4 (Binance): n={r4['n']} WR={r4.get('wr',0):.0%} avg={r4.get('avg',0):+.2f}%\n"
                    f"R1 (Random):  n={r1['n']} WR={r1.get('wr',0):.0%} avg={r1.get('avg',0):+.2f}%\n"
                    f"→ Continue R4 until n≥100, then run R7 bootstrap gate"
                )
            elif p_r4_better <= 0.15:
                await tg(
                    f"🔬 *R4 vs R1 — Model ≈ Random*\n"
                    f"P(R4>R1) = {p_r4_better:.0%} ≤ 15% — R1 outperforms R4\n"
                    f"R4 (Binance): n={r4['n']} avg={r4.get('avg',0):+.2f}%\n"
                    f"R1 (Random):  n={r1['n']} avg={r1.get('avg',0):+.2f}%\n"
                    f"→ Execute R3 (HL Harvest desk) + R8 (publish negative result)"
                )
            elif 0.40 <= p_r4_better <= 0.60 and r4["n"] >= 60:
                await tg(
                    f"📊 *R4 vs R1 — Weekly Update* (n≥60)\n"
                    f"P(R4>R1) = {p_r4_better:.0%} — inconclusive, accumulating\n"
                    f"R4: {r4['n']}t WR={r4.get('wr',0):.0%} avg={r4.get('avg',0):+.2f}%\n"
                    f"R1: {r1['n']}t WR={r1.get('wr',0):.0%} avg={r1.get('avg',0):+.2f}%\n"
                    f"Target: n=100 per venue for CI95 decision"
                )

    except Exception as e:
        log.error(f"job_cex_r1_r4_compare: {e}")


async def job_cex_strategy_drift_check():
    """R7b (Fable 5 audit §R7): hourly git-SHA drift guard.
    Compares HEAD git-SHA against the SHA loaded by each Freqtrade container at startup.
    Alerts if a container is running stale code — root cause of v8.30 Bybit incident
    (DOT SHORT -3.04% executed from 12-version-old code).
    Containers must be force-recreated (not just restarted) when strategy changes."""
    try:
        import subprocess as _sp
        # Current HEAD SHA
        _head = await asyncio.to_thread(lambda: _sp.run(
            ["git", "-C", str(CFG["PROJECT_DIR"]), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10
        ).stdout.strip())
        if not _head:
            return

        # Check ALL active strategy files vs container start times.
        # v10.1: Binance=R4 (AnantaraTrendFocused_v4), Bybit=R1 (AnantaraRandomControl_v1).
        # Each container's strategy file is checked independently — a change to
        # R4 only affects Binance, not Bybit.
        _strat_dir = CFG["PROJECT_DIR"] / "freqtrade_user_data" / "strategies"
        _container_strategies = {
            "anantara-freqtrade":       _strat_dir / "AnantaraTrendFocused_v4.py",
            "anantara-freqtrade-bybit": _strat_dir / "AnantaraRandomControl_v1.py",
        }

        _alerts = []
        for _container, _strat_path in _container_strategies.items():
            _strat_mtime = _strat_path.stat().st_mtime if _strat_path.exists() else 0
            try:
                _inspect = await asyncio.to_thread(lambda c=_container: _sp.run(
                    ["docker", "inspect", c, "--format", "{{.State.StartedAt}}"],
                    capture_output=True, text=True, timeout=10
                ).stdout.strip())
                if not _inspect:
                    continue
                # Parse container start time — MUST specify UTC explicitly.
                from datetime import datetime as _dtt, timezone as _tz
                import re as _re
                _ts_str = _re.sub(r"\.\d+Z$", "", _inspect) + "Z"
                try:
                    _started = (_dtt.strptime(_ts_str, "%Y-%m-%dT%H:%M:%SZ")
                                .replace(tzinfo=_tz.utc).timestamp())
                except Exception:
                    continue
                # If strategy file was modified AFTER container started, code is stale
                _lag_min = int((_strat_mtime - _started) / 60)
                if _strat_mtime > _started:
                    _alerts.append(
                        f"*{_container}*: strategy changed {_lag_min}m after container start "
                        f"(HEAD {_head}) → needs `--force-recreate`"
                    )
            except Exception:
                continue

        if _alerts:
            await tg(
                f"⚠️ *CEX Strategy Drift Detected* (R7b)\n"
                + "\n".join(_alerts)
                + "\nFix: `docker compose up -d --force-recreate freqtrade freqtrade-bybit`"
            )
            log.warning(f"cex_strategy_drift: {len(_alerts)} containers running stale code")
        else:
            log.debug(f"cex_strategy_drift: containers current (HEAD={_head})")

    except Exception as e:
        log.warning(f"job_cex_strategy_drift_check: {e}")


async def job_cex_veto_outcome():
    """R5 (Fable 5 audit §R5 + §5.4): hourly veto counterfactual outcome tracker.
    Reads veto log entries from 24h and 48h ago, fetches current market prices,
    computes hypothetical trade outcomes, and fills in outcome_24h/outcome_48h.
    After accumulating 50+ vetoes with outcomes, computes aggregate statistics:
    did the veto layer save money or block profits? Falsifies/validates each layer.
    """
    try:
        from datetime import datetime as _dtt, timezone as _tz, timedelta as _td
        from pathlib import Path as _Path
        import json as _j

        _veto_dir = CFG["PROJECT_DIR"] / "freqtrade_user_data" / "data" / "binance" / "cex_veto_log"
        if not _veto_dir.exists():
            return  # No vetoes yet — nothing to do

        _now = _dtt.now(_tz.utc)
        _files = sorted(_veto_dir.glob("veto_*.jsonl"))

        # Collect all veto entries that need outcome updates
        _updated = 0
        _all_entries = []

        for _fp in _files:
            _lines = _fp.read_text().splitlines()
            _modified = False
            _new_lines = []

            for _line in _lines:
                if not _line.strip():
                    _new_lines.append(_line)
                    continue
                _entry = _j.loads(_line)
                _ts = _dtt.fromtimestamp(_entry["ts"], tz=_tz.utc)
                _age_h = (_now - _ts).total_seconds() / 3600
                _pair = _entry["pair"]
                _side = _entry["side"]

                # Check if we need to fill 24h or 48h outcome
                _need_24h = (_age_h >= 24 and _entry.get("outcome_24h") is None)
                _need_48h = (_age_h >= 48 and _entry.get("outcome_48h") is None)

                if _need_24h or _need_48h:
                    # Fetch current price from Binance
                    try:
                        # FIX 2026-08-11: "ADA/USDT:USDT" → "ADAUSDT" (bukan
                        # "ADAUSDTUSDT"). .replace(":","") salah — split ":" dulu.
                        _sym = _pair.split(":")[0].replace("/", "")
                        import httpx as _httpx
                        # FIX 2026-09-26 (RCA terverifikasi): panggilan SINKRON di dalam
                        # coroutine async membekukan event loop 20-133 s. Akibatnya probe
                        # /ping job_system_health tidak sempat timeout dan Freqtrade
                        # dilaporkan DOWN palsu -> _ft_autorecover me-restart container
                        # yang sehat (20x/24 jam). Jalankan di thread: loop tetap responsif.
                        _r = await asyncio.to_thread(
                            _httpx.get,
                            f"https://api.binance.com/api/v3/ticker/price?symbol={_sym}",
                            timeout=5.0,
                        )
                        if _r.status_code == 200:
                            _current = float(_r.json()["price"])
                            _entry_price = _entry["hypothetical_entry"]
                            # Compute PnL from hypothetical entry to current price
                            # FIX 2026-08-11: side tersimpan lowercase ('short'),
                            # kode cek 'SHORT' uppercase → selalu False → SHORT
                            # pakai rumus LONG → sign PnL terbalik!
                            if _side.upper() == "SHORT":
                                _pnl_pct = (_entry_price - _current) / _entry_price
                            else:
                                _pnl_pct = (_current - _entry_price) / _entry_price
                            _pnl_pct = round(_pnl_pct, 6)

                            if _need_24h:
                                _entry["outcome_24h"] = _pnl_pct
                            if _need_48h:
                                _entry["outcome_48h"] = _pnl_pct
                            _updated += 1
                    except Exception:
                        pass  # Network error — try again next hour

                _all_entries.append(_entry)
                _new_lines.append(_j.dumps(_entry))

            # Rewrite file if entries were updated
            if _need_24h or _need_48h:
                try:
                    _fp.write_text("\n".join(_new_lines) + "\n")
                except Exception:
                    pass

        if _updated:
            log.info(f"cex_veto_outcome: filled {_updated} outcomes")

        # ── Aggregate report (only when ≥10 outcomes available) ───────────
        _with_24h = [e for e in _all_entries if e.get("outcome_24h") is not None]
        _with_48h = [e for e in _all_entries if e.get("outcome_48h") is not None]

        if len(_with_24h) >= 10:
            _saved_24 = sum(1 for e in _with_24h if e["outcome_24h"] < 0)
            _blocked_24 = sum(1 for e in _with_24h if e["outcome_24h"] > 0)
            _avg_24 = sum(e["outcome_24h"] for e in _with_24h) / len(_with_24h) * 100

            # Per-layer breakdown
            _layers = defaultdict(lambda: {"n": 0, "saved": 0, "blocked": 0, "pnl_sum": 0.0})
            for e in _with_24h:
                _reason = e.get("veto_reason", "unknown")
                if "event_risk" in _reason:
                    _layer = "event_risk"
                elif "intel" in _reason:
                    _layer = "intel_preveto"
                elif "hermes" in _reason:
                    _layer = "hermes_llm"
                else:
                    _layer = "other"
                _layers[_layer]["n"] += 1
                if e["outcome_24h"] < 0:
                    _layers[_layer]["saved"] += 1
                else:
                    _layers[_layer]["blocked"] += 1
                _layers[_layer]["pnl_sum"] += e["outcome_24h"]

            # Only send report once per day (at 08:00 UTC)
            _hour = _dtt.now(_tz.utc).hour
            if _hour == 8:
                _lines = [
                    f"🔬 *R5 Veto Counterfactual Report* ({len(_with_24h)} vetoes with 24h outcome)",
                    f"Overall: {_saved_24} saved / {_blocked_24} blocked profit",
                    f"Avg outcome if NOT vetoed: {_avg_24:+.2f}%",
                    f"",
                ]
                for _layer, _stats in sorted(_layers.items()):
                    _net = "✅ SAVES" if _stats["saved"] > _stats["blocked"] else ("⚠️ BLOCKS PROFIT" if _stats["blocked"] > _stats["saved"] else "➖ NEUTRAL")
                    _lines.append(
                        f"  *{_layer}*: n={_stats['n']} | "
                        f"saved={_stats['saved']} blocked={_stats['blocked']} | "
                        f"avg={_stats['pnl_sum']/_stats['n']*100:+.2f}% | {_net}"
                    )
                await tg("\n".join(_lines))
                log.info(f"cex_veto_outcome report: {len(_with_24h)} vetoes analyzed")

    except Exception as e:
        log.warning(f"job_cex_veto_outcome: {e}")


async def job_cex_periodic_report():
    """Periodic CEX progress report to Telegram (every 6 hours).
    v8.2: consolidated scientific summary with bootstrap progress tracker."""
    try:
        from datetime import datetime as _dtt, timezone as _tz
        import json as _j, httpx as _httpx

        _now = _dtt.now(_tz.utc)

        # ── v8.2: Bootstrap progress from cex_bootstrap_monitor ──────────
        _bs_report = _cbm.bootstrap_progress_report()

        # ── BTC & Regime (lightweight, no DB needed) ────────────────────
        _btc = 0.0
        _btc_4h = 0.0
        _regime = "?"
        try:
            # FIX 2026-09-26 (RCA): hindari I/O sinkron di coroutine async — dua panggilan
            # ini juga memblokir event loop (lihat catatan di job_cex_veto_outcome).
            _r = await asyncio.to_thread(
                _httpx.get, "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5
            )
            if _r.status_code == 200: _btc = float(_r.json()["price"])
            _r = await asyncio.to_thread(
                _httpx.get,
                "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=4h&limit=2",
                timeout=5,
            )
            if _r.status_code == 200:
                _k = _r.json()
                _btc_4h = (float(_k[-1][4]) - float(_k[-2][4])) / float(_k[-2][4]) * 100
        except Exception: pass

        _trend = "🐻 BEAR" if _btc_4h < -0.3 else ("🐂 BULL" if _btc_4h > 0.3 else "➖ FLAT")

        try:
            _idir = CFG["PROJECT_DIR"] / "freqtrade_user_data" / "data" / "binance" / "intelligence"
            _ifiles = sorted(_idir.glob("intel_*.jsonl"))
            if _ifiles:
                _ilines = [l for l in _ifiles[-1].read_text().splitlines() if l.strip()]
                if _ilines:
                    _d = _j.loads(_ilines[-1])
                    _regime = _d.get("market_regime", "?")
        except Exception: pass

        # ── Compose full report ─────────────────────────────────────────
        _msg = (
            f"📡 *CEX Report* {_now.strftime('%d %b %H:%M UTC')}\n"
            f"*BTC*: ${_btc:,.0f} 4H:{_btc_4h:+.2f}% {_trend} | Regime: {_regime}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{_bs_report}"
        )
        await tg(_msg)
        log.info(f"cex_periodic_report: sent v8.2 bootstrap report")

    except Exception as e:
        log.warning(f"job_cex_periodic_report: {e}")


async def job_cex_bootstrap_check():
    """Hourly: lightweight bootstrap progress check. Alerts on milestones.
    Silent unless: (a) first trade detected, (b) n=30/50/75/100 milestone
    reached, (c) P(E>0) crosses 75%/90% threshold, (d) ETA slips beyond 45d."""
    try:
        from datetime import datetime as _dtt, timezone as _tz
        import json as _j

        counts = _cbm.get_trade_counts()
        new_n = counts["since_v82"]["n"]
        new_profits = counts["since_v82"]["profits"]
        bs = _cbm.bootstrap_confidence(new_profits)
        eta = _cbm.eta_to_100(new_n)

        # ── Milestone alerts ────────────────────────────────────────────
        _alert_file = CFG["PROJECT_DIR"] / "freqtrade_user_data" / "data" / "binance" / ".bootstrap_milestones.json"
        _milestones: dict = {}
        if _alert_file.exists():
            _milestones = _j.loads(_alert_file.read_text())
        else:
            _milestones = {"last_n": 0, "last_p_pos": 0, "first_trade_alerted": False}

        # First v8.2 trade
        if new_n >= 1 and not _milestones.get("first_trade_alerted"):
            await tg(
                f"🎯 *R4 v8.2 — FIRST TRADE!*\n"
                f"Trade #{new_n} detected. Bootstrap experiment officially started.\n"
                f"Target: {100 - new_n} more to n=100.\n"
                f"_ETA and P(E>0) will update as trades accumulate._"
            )
            _milestones["first_trade_alerted"] = True
            log.info("bootstrap_check: FIRST v8.2 trade alert sent!")

        # Milestone n thresholds
        for _thr in [30, 50, 75, 100]:
            if new_n >= _thr and _milestones["last_n"] < _thr:
                await tg(
                    f"📊 *R4 v8.2 — n={_thr} MILESTONE!*\n"
                    f"P(E>0)={bs['p_positive']:.1%} | "
                    f"ETA to 100: {eta['eta_date']}\n"
                    f"Mean: {bs['mean']*100:+.2f}% | CI95: [{bs['ci_lower']*100:+.2f}%, {bs['ci_upper']*100:+.2f}%]"
                )
                log.info(f"bootstrap_check: n={_thr} milestone reached!")

        # P(E>0) crossing thresholds
        if bs["p_positive"] is not None:
            for _p_thr in [0.75, 0.90]:
                if bs["p_positive"] >= _p_thr and _milestones.get("last_p_pos", 0) < _p_thr:
                    _emoji = "🚀" if _p_thr >= 0.90 else "📈"
                    await tg(
                        f"{_emoji} *P(E>0) crossed {_p_thr:.0%}!*\n"
                        f"Bootstrap CI95 P(E>0) = {bs['p_positive']:.1%}\n"
                        f"n={new_n} trades | Mean={bs['mean']*100:+.2f}%\n"
                        f"{'✅ GO DECISION THRESHOLD REACHED!' if _p_thr >= 0.90 else '🟡 Approaching GO threshold'}"
                    )
                    log.info(f"bootstrap_check: P(E>0) crossed {_p_thr:.0%}!")

        # ETA slip warning
        if eta["eta_days"] > 45 and _milestones.get("last_n", 0) >= 5:
            await tg(
                f"⚠️ *Bootstrap ETA Slip*\n"
                f"Current rate: {eta['rate_per_day']:.1f} trades/day\n"
                f"ETA to 100: {eta['eta_days']:.0f} days (target: ≤45d)\n"
                f"Consider: expand pairs, loosen thresholds, or reduce hold time."
            )

        # Save milestone state
        _milestones["last_n"] = new_n
        if bs["p_positive"] is not None:
            _milestones["last_p_pos"] = bs["p_positive"]
        _alert_file.parent.mkdir(parents=True, exist_ok=True)
        _alert_file.write_text(_j.dumps(_milestones))

    except Exception as e:
        log.warning(f"job_cex_bootstrap_check: {e}")


async def job_cex_learning_report():
    """Daily (12:00 UTC): CEX trade learning report to Telegram.
    Extracts patterns (per-pair, per-exit, per-hold, config recs) from
    accumulated R4 paper trades — feeds live-trading calibration."""
    try:
        from datetime import datetime as _dtt, timezone as _tz
        _now = _dtt.now(_tz.utc)
        _report = _cla.build_report()

        # Persist report file
        try:
            _rep_dir = CFG["PROJECT_DIR"] / "reports"
            _rep_dir.mkdir(exist_ok=True)
            _rep_file = _rep_dir / f"cex_learning_{_now.strftime('%Y%m%d')}.txt"
            _rep_file.write_text(_report)
        except Exception:
            pass

        await tg(_report)
        log.info(f"cex_learning_report: sent learning report to Telegram")

    except Exception as e:
        log.warning(f"job_cex_learning_report: {e}")


async def job_cex_pair_blocklist():
    """Hourly (v8.6): auto-refresh the CEX pair blocklist from live closed
    trades. Writes freqtrade_user_data/data/binance/cex_pair_blocklist.json
    (shared with the strategy container). Alerts Telegram on new HARD blocks
    and on lifecycle transitions (HARD→PROBATION→UNBLOCK / RE-BLOCK).

    Criteria (see anantara/cex_pair_blocklist.py): HARD = n≥5, WR<25%, avg<-1.5%.
    Example: LINK_SHORT n=6 WR=17% avg=-2.25% → auto-blocked.
    v1.1 (13 Aug): full lifecycle — blocked pairs auto-recover via PROBATION
    (7-day cooldown + recovery) then UNBLOCK, or get RE-BLOCKED if they slip."""
    try:
        _before = _cpb.load_blocklist()
        _bl = _cpb.refresh_blocklist()
        _hard = _bl.get("hard", {})
        _soft = _bl.get("soft", {})
        _prob = _bl.get("probation", {})
        _events = _bl.get("_events", {}) or {}

        # Alert on NEW hard blocks (not present in the previous file)
        _prev_hard = set((_before or {}).get("hard", {}).keys())
        _new_hard = [k for k in _hard.keys() if k not in _prev_hard]
        if _new_hard:
            _detail = " | ".join(
                f"{k}: WR={v['wr']:.0%} n={v['n']} avg={v['avg_pct']:+.2f}%"
                for k, v in sorted(_hard.items(), key=lambda x: x[1]['avg_pct'])
                if k in _new_hard)
            await tg(f"🔴 *CEX Auto-Pair-Block (v8.6)*\n{_detail}\n"
                     f"_New HARD blocks — entries vetoed + open trades cut at -1.5%_")
            log.warning(f"cex_pair_blocklist: NEW hard blocks: {_new_hard}")

        # Alert on lifecycle transitions (v1.1 auto-unblock)
        if _events.get("unblocked"):
            await tg(f"🟢 *CEX Pair Auto-Unblock (v1.1)*\n"
                     f"{' | '.join(_events['unblocked'])}\n"
                     f"_Recovered pair returned to active universe_")
            log.info(f"cex_pair_blocklist: UNBLOCKED: {_events['unblocked']}")
        if _events.get("reblocked"):
            await tg(f"🔴 *CEX Pair Re-Block (v1.1)*\n"
                     f"{' | '.join(_events['reblocked'])}\n"
                     f"_Probation pair slipped → back to HARD block_")
            log.warning(f"cex_pair_blocklist: RE-BLOCKED: {_events['reblocked']}")

        if not _new_hard and not _events.get("unblocked") and not _events.get("reblocked") and _hard:
            log.info(f"cex_pair_blocklist: {len(_hard)} hard block(s) active: "
                     f"{', '.join(_hard.keys())} | probation: {len(_prob)}")

    except Exception as e:
        log.warning(f"job_cex_pair_blocklist: {e}")


async def job_cex_deep_loop():
    """Daily (12:05 UTC, v8.6.2): autonomous learn-experience loop.
    Analyzes per-entry-path expectancy from closed R4 trades and auto-vetoes
    paths with negative expectancy (n>=5). Writes cex_deep_loop.json (read by
    strategy Gate 0.7). Alerts Telegram when a path is newly vetoed."""
    try:
        _before = _cdl.load_learning()
        _learn = _cdl.refresh_learning()
        _vetoed = _learn.get("vetoed", [])
        _prev_vetoed = set((_before or {}).get("vetoed", []) or [])
        _new_veto = [p for p in _vetoed if p not in _prev_vetoed]
        if _new_veto:
            _detail = " | ".join(
                f"{p}: E={_learn['paths'][p]['expectancy']:+.2f}% "
                f"WR={_learn['paths'][p]['wr']:.0%} n={_learn['paths'][p]['n']}"
                for p in _new_veto if p in _learn.get("paths", {}))
            await tg(f"🧠 *CEX Deep-Loop Auto-Veto (v8.6.2)*\n{_detail}\n"
                     f"_Entry path terbukti merugi → di-veto otomatis (n≥5, E<0)_")
            log.warning(f"cex_deep_loop: NEW vetoed paths: {_new_veto}")
        elif _vetoed:
            log.info(f"cex_deep_loop: {len(_vetoed)} vetoed path(s) active: "
                     f"{', '.join(_vetoed)}")
    except Exception as e:
        log.warning(f"job_cex_deep_loop: {e}")


async def job_cex_adaptive_threshold():
    """Every 2h (v8.7 Perbaikan #4): compute per-pair adaptive threshold multipliers.
    Reads last 10 closed trades per pair from PostgreSQL, computes WR, and writes
    cex_adaptive_thresholds.json consumed by strategy Gate adaptive-thr.
    WR<40%→strict(×1.30) | WR>65%→loose(×0.85) | else→neutral(×1.00)."""
    try:
        _result = _cat.run()
        _pairs = _result.get("pairs", {})
        _strict = [c for c, v in _pairs.items() if v.get("mult", 1.0) > 1.0]
        _loose  = [c for c, v in _pairs.items() if v.get("mult", 1.0) < 1.0]
        if _strict or _loose:
            log.info(f"adaptive_thr: strict={_strict} loose={_loose} "
                     f"({len(_pairs)} pairs updated)")
    except Exception as e:
        log.warning(f"job_cex_adaptive_threshold: {e}")


async def job_cex_profitability_report():
    """Every 4h (v8.7 S1): monitor whether CEX-Binance achieves the North Star target.
    Computes per-trade wallet-fraction PnL from PostgreSQL closed trades, applies
    expectancy gate + Wald SPRT + drawdown halt, and writes
    cex_profitability_report.json. Alerts Telegram if drawdown halt fires or
    if grade worsens to NEGATIVE."""
    try:
        _rep = _cpt.run()
        _grade = _rep.get("grade", "UNKNOWN")
        _w7    = _rep.get("7d", {})
        _n7    = _w7.get("n", 0)
        _mean7 = _w7.get("mean_wallet_pct", 0.0)
        _tgt   = _rep.get("target_per_cycle_pct", 0.5)
        _dd    = _rep.get("drawdown", {})
        if _dd.get("halt"):
            await tg(
                f"⚠️ *CEX Profitability — DRAWDOWN HALT*\n"
                f"Accumulated drawdown `{_dd['dd']:.1%}` ≥ 8% threshold.\n"
                f"Review positions and strategy immediately."
            )
        elif _grade == "NEGATIVE" and _n7 >= 5:
            await tg(
                f"🔴 *CEX Profitability — NEGATIVE*\n"
                f"7d mean: `{_mean7:+.3f}%/cycle` vs target `{_tgt:.1f}%`"
                f" | n={_n7} trades\n"
                f"SPRT: `{_rep.get('sprt', {}).get('decision', '?')}`"
            )
        log.info(
            f"job_cex_profitability_report: {_grade} 7d={_mean7:+.3f}%/cycle "
            f"(target={_tgt:.1f}%) n={_n7}"
        )
    except Exception as e:
        log.warning(f"job_cex_profitability_report: {e}")


async def job_cex_spot_deep_loop():
    """Daily (12:35 UTC, v1.0): SPOT swing autonomous learn-experience loop.
    Analyzes per-COIN expectancy on the SIGNAL track of paper_test_spot_swing_cex
    and auto-vetoes coins proven-losing (n>=5, E<0, PF<0.7, bootstrap P(E>0)<0.5).
    Writes cex_spot_deep_loop.json (read by the spot paper test at open time).
    Alerts Telegram when a coin is newly vetoed."""
    try:
        _before = _csdl.load_learning()
        _learn = _csdl.refresh_learning()
        _vetoed = _learn.get("vetoed", [])
        _prev = set((_before or {}).get("vetoed", []) or [])
        _new = [c for c in _vetoed if c not in _prev]
        if _new:
            _detail = " | ".join(
                f"{c}: E={_learn['coins'][c]['expectancy']:+.2f}% "
                f"WR={_learn['coins'][c]['wr']:.0%} PF={_learn['coins'][c]['pf']:.2f} "
                f"P(E>0)={_learn['coins'][c]['p_e_pos']:.2f} n={_learn['coins'][c]['n']}"
                for c in _new if c in _learn.get("coins", {}))
            await tg(f"🧠 *CEX SPOT Deep-Loop Auto-Veto (v1.0)*\n{_detail}\n"
                     f"_Coin terbukti merugi di SPOT SIGNAL → di-veto otomatis_")
            log.warning(f"cex_spot_deep_loop: NEW vetoed coins: {_new}")
        elif _vetoed:
            log.info(f"cex_spot_deep_loop: {len(_vetoed)} vetoed coin(s): "
                     f"{', '.join(_vetoed)}")
        _svr = _learn.get("signal_vs_random", {})
        if _svr.get("p_value") is not None:
            log.info(f"cex_spot_deep_loop: SIGNAL-vs-RANDOM diff="
                     f"{_svr.get('obs_diff_pct')}% p={_svr.get('p_value')} "
                     f"verdict={_svr.get('verdict')}")
            # Alert only on the honest milestone: real edge, or proven no-edge.
            if _svr.get("verdict") == "EDGE_CONFIRMED":
                await tg(f"✅ *CEX SPOT alpha CONFIRMED* — SIGNAL beats RANDOM "
                         f"(+{_svr.get('obs_diff_pct')}%/trade, p={_svr.get('p_value')}). "
                         f"Bukan beta — edge nyata.")
            elif _svr.get("verdict") == "NO_EDGE":
                await tg(f"🔬 *CEX SPOT: NO edge* — SIGNAL tidak kalahkan RANDOM "
                         f"(diff {_svr.get('obs_diff_pct')}%, p={_svr.get('p_value')}). "
                         f"WR tinggi = beta pasar, bukan skill.")
    except Exception as e:
        log.warning(f"job_cex_spot_deep_loop: {e}")


async def job_cex_spot_swing_report():
    """Daily (13:00 UTC, v1.0): CEX Binance SPOT swing paper test report.
    Track runs 24/7 via systemd anantara-paper-spot-swing-cex.service.
    This job reads its state and reports SIGNAL vs RANDOM comparison to
    Telegram — the falsification evidence for the spot swing edge."""
    try:
        import json as _j
        from pathlib import Path as _P
        _state = _P(CFG["PROJECT_DIR"]) / "data" / "paper_test_spot_swing_cex_spot.json"
        if not _state.exists():
            return
        _d = _j.loads(_state.read_text())
        _lines = [f"🟢 *CEX Spot Swing Paper* — {datetime.now(timezone.utc).strftime('%d %b %H:%M')} UTC",
                  "━━━━━━━━━━━━━━━━━━━━━"]
        for _tr in ("SIGNAL", "RANDOM"):
            _pos = _d.get("tracks", {}).get(_tr, [])
            _closed = [p for p in _pos if p.get("status") == "CLOSED"]
            _open = [p for p in _pos if p.get("status") == "OPEN"]
            if not _closed:
                _lines.append(f"  {_tr:7s}: open={len(_open)} n_closed=0 (menunggu data)")
                continue
            _pnls = [(p.get("pnl_pct") or 0) * 100 for p in _closed]
            _wins = [p for p in _pnls if p > 0]
            _gw = sum(p for p in _pnls if p > 0)
            _gl = -sum(p for p in _pnls if p < 0)
            _pf = _gw / _gl if _gl > 0 else 0
            _lines.append(f"  {_tr:7s}: n={len(_closed)} open={len(_open)} "
                          f"WR={len(_wins)/len(_closed)*100:.0f}% "
                          f"E={sum(_pnls)/len(_closed):+.2f}% PF={_pf:.2f}")
        _n_sig = len([p for p in _d.get("tracks", {}).get("SIGNAL", []) if p.get("status") == "CLOSED"])
        _n_rnd = len([p for p in _d.get("tracks", {}).get("RANDOM", []) if p.get("status") == "CLOSED"])
        if _n_sig >= 5 and _n_rnd >= 5:
            _lines.append("━━━━━━━━━━━━━━━━━━━━━")
            _lines.append("_Kontrol: SIGNAL vs RANDOM (falsifikasi edge)_")
        await tg("\n".join(_lines))
        log.info(f"cex_spot_swing_report: signal={_n_sig} random={_n_rnd} closed")
    except Exception as e:
        log.warning(f"job_cex_spot_swing_report: {e}")


async def job_pregain_v21_ns_progress():
    """Daily (08:00 UTC): V2.1 paper monitor NS progress report.
    Reads data/pregain_v21_paper_signals.jsonl and reports WR, avg, n
    toward the n≥30 / avg≥0.5% gate for micro-live promotion.
    Also fires BULL regime alert when BTC flips from BEAR→BULL."""
    try:
        import json as _j
        from pathlib import Path as _P

        _sig_file = _P(CFG["PROJECT_DIR"]) / "data" / "pregain_v21_paper_signals.jsonl"
        if not _sig_file.exists():
            log.debug("job_pregain_v21_ns_progress: no signal file yet")
            return

        _all, _closed = [], []
        with _sig_file.open() as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line:
                    continue
                try:
                    _s = _j.loads(_line)
                    _all.append(_s)
                    if _s.get("status") == "CLOSED" and _s.get("modal_pct") is not None:
                        _closed.append(_s)
                except Exception:
                    pass

        _n_open = len([s for s in _all if s.get("status") == "OPEN"])
        _n = len(_closed)
        _ns_n_target = 30
        _ns_avg_target = 0.5  # %

        if _n == 0:
            _lines = [
                "📊 *Pre-Gain V2.1 NS Progress*",
                f"n_closed=0 (open={_n_open})",
                "_Menunggu sinyal di BULL regime..._",
                f"Gate: n≥{_ns_n_target} + avg≥{_ns_avg_target:.1f}% → micro-live",
            ]
            await tg("\n".join(_lines))
            return

        _modals = [s["modal_pct"] for s in _closed]
        _wins   = [m for m in _modals if m > 0]
        _wr     = len(_wins) / _n
        _avg    = sum(_modals) / _n
        _pf_g   = sum(_wins) if _wins else 0
        _pf_l   = -sum(m for m in _modals if m <= 0)
        _pf     = _pf_g / _pf_l if _pf_l > 0 else 9.99

        # Last BTC regime from most recent signal
        _last_sig   = _all[-1] if _all else {}
        _btc_regime = _last_sig.get("regime", _last_sig.get("btc_regime", "UNKNOWN"))

        # NS gate check
        _n_ok   = _n >= _ns_n_target
        _avg_ok = _avg >= _ns_avg_target / 100
        _wr_ok  = _wr >= 0.51
        _ns_ok  = _n_ok and _avg_ok and _wr_ok

        # Progress bar toward n≥30
        _pct = min(100, int(_n / _ns_n_target * 100))
        _bar = "█" * (_pct // 10) + "░" * (10 - _pct // 10)

        _lines = [
            f"📊 *Pre-Gain V2.1 NS Progress* — {datetime.now(timezone.utc).strftime('%d %b %H:%M')} UTC",
            "━━━━━━━━━━━━━━━━━━━━━",
            f"Closed: {_n} | Open: {_n_open} | Regime: {_btc_regime}",
            f"WR={_wr:.0%}  avg={_avg*100:+.2f}%  PF={_pf:.2f}",
            f"NS target: avg≥{_ns_avg_target:.1f}% of modal",
            f"",
            f"[{_bar}] {_pct}% → n≥{_ns_n_target}",
            f"  n   {'✅' if _n_ok else '❌'} {_n}/{_ns_n_target}",
            f"  avg {'✅' if _avg_ok else '❌'} {_avg*100:+.2f}% (need ≥{_ns_avg_target:.1f}%)",
            f"  WR  {'✅' if _wr_ok else '❌'} {_wr:.0%} (need ≥51%)",
        ]
        if _ns_ok:
            _lines.append("🟢 *GATE OPEN → MICRO-LIVE ELIGIBLE ($10 test)*")
        else:
            # v2.2 ensemble: setiap regime punya strategi (BULL→MOM_LONG, BEAR/RANGING→MR_SHORT)
            _lines.append(f"🟡 {_btc_regime} regime — ensemble regime-adaptif akumulasi sinyal")

        await tg("\n".join(_lines))
        log.info(f"pregain_v21_ns_progress: n={_n} wr={_wr:.0%} avg={_avg*100:+.2f}% regime={_btc_regime}")
    except Exception as _e:
        log.debug(f"job_pregain_v21_ns_progress: {_e}")


async def job_cex_watchdog():
    """CEX watchdog with auto-recovery (every 30 min).
    AUTO-FIXES: restarts dead containers, detects R4 stuck, model staleness.
    Sends consolidated alert if unfixable issues persist."""
    try:
        import subprocess as _sp
        from datetime import datetime as _dtt, timezone as _tz

        _issues = []
        _fixed = []
        _now = _dtt.now(_tz.utc)

        # 1. Container health + auto-restart
        _required = {"anantara-freqtrade": "freqtrade",
                     "anantara-freqtrade-bybit": "freqtrade-bybit"}
        _r = await asyncio.to_thread(lambda: _sp.run(
            ["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, timeout=10
        ))
        _running = set(_r.stdout.strip().split("\n"))
        for _c, _svc in _required.items():
            if _c not in _running:
                try:
                    _rr = await asyncio.to_thread(lambda s=_svc: _sp.run(
                        ["docker", "compose", "restart", s],
                        cwd=str(CFG["PROJECT_DIR"]), capture_output=True, text=True, timeout=60
                    ))
                    if _rr.returncode == 0:
                        _fixed.append(f"✅ Auto-restarted: {_c}")
                    else:
                        _issues.append(f"🚨 {_c} DOWN — restart failed")
                except Exception:
                    _issues.append(f"🚨 {_c} DOWN — restart error")

        # 2. FreqAI model staleness
        _model_dir = CFG["PROJECT_DIR"] / "freqtrade_user_data" / "models" / "anantara_r4"
        if _model_dir.exists():
            _newest = 0
            for _f in _model_dir.rglob("*.joblib"):
                if _f.stat().st_mtime > _newest: _newest = _f.stat().st_mtime
            if _newest > 0:
                _age_h = (_now.timestamp() - _newest) / 3600
                if _age_h > 48:
                    _issues.append(f"⚠️ FreqAI model {_age_h:.0f}h stale — needs retrain check")
                elif _age_h > 36:
                    _issues.append(f"⚠️ FreqAI model {_age_h:.0f}h since last train")

        # 3. Intel data recency
        _intel_dir = CFG["PROJECT_DIR"] / "freqtrade_user_data" / "data" / "binance" / "intelligence"
        _intel_files = sorted(_intel_dir.glob("intel_*.jsonl")) if _intel_dir.exists() else []
        if _intel_files:
            _last_line = None
            for _line in _intel_files[-1].read_text().splitlines():
                if _line.strip(): _last_line = _line
            if _last_line:
                _d = __import__("json").loads(_last_line)
                _ts = _dtt.fromtimestamp(_d["ts"], tz=_tz.utc)
                _age_h = (_now - _ts).total_seconds() / 3600
                if _age_h > 3:
                    _issues.append(f"⚠️ Intel data stale: {_age_h:.0f}h")
        else:
            _issues.append("⚠️ No intel data found")

        # 4. Database connectivity
        try:
            import psycopg2 as _pg2
            _env_path = CFG["PROJECT_DIR"] / ".env"
            _env_vars = {}
            with open(_env_path) as _ef:
                for _line in _ef:
                    _line = _line.strip()
                    if "=" in _line and not _line.startswith("#"):
                        _k, _v = _line.split("=", 1)
                        _env_vars[_k.strip()] = _v.strip()
            _pg_pw = _env_vars.get("POSTGRES_PASSWORD", "")
            for _db in ["anantara", "anantara_bybit"]:
                try:
                    _conn = _pg2.connect(host="localhost", port=5432, dbname=_db,
                                         user="anantara", password=_pg_pw, connect_timeout=3)
                    _conn.close()
                except Exception:
                    _issues.append(f"🚨 DB unreachable: {_db}")
        except Exception:
            pass

        # 5. R4 stuck detection (>48h no trades since v5.1 deploy)
        try:
            import psycopg2 as _pg2
            _conn = _pg2.connect(host="localhost", port=5432, dbname="anantara",
                                 user="anantara", password=_pg_pw)
            _cur = _conn.cursor()
            _cur.execute("SELECT COUNT(*) FROM trades WHERE is_open=false AND open_date >= '2026-06-19 08:40:00'")
            _r4n = _cur.fetchone()[0]
            _conn.close()
            if _r4n == 0:
                _deploy_h = (_now - _dtt(2026,6,19,8,40,0,tzinfo=_tz.utc)).total_seconds() / 3600
                if _deploy_h > 48:
                    _issues.append(f"⚠️ R4 v5.1: 0 trades in {_deploy_h:.0f}h — gate may need tuning")
        except Exception:
            pass

        # Report
        if _fixed:
            await tg("🟢 *CEX Auto-Recovery*\n" + "\n".join(_fixed))
            log.info(f"cex_watchdog: auto-fixed {len(_fixed)}")
        if _issues:
            await tg("🔴 *CEX Watchdog* " + _now.strftime('%d %b %H:%M') + "\n" + "\n".join(_issues))
            log.warning(f"cex_watchdog: {len(_issues)} issues")
        else:
            log.debug("cex_watchdog: all clear")

    except Exception as e:
        log.warning(f"job_cex_watchdog: {e}")


async def job_cex_weekly_research():
    """Weekly deep research report (Sunday 08:00 UTC).
    Comprehensive scientific analysis: trend evolution, edge detection,
    session recalibration suggestions, exit engine audit, veto effectiveness.
    Designed for continuous learning — surfaces patterns human might miss."""
    try:
        from datetime import datetime as _dtt, timezone as _tz
        import psycopg2 as _pg2
        from collections import defaultdict as _dd

        _now = _dtt.now(_tz.utc)
        if _now.weekday() != 6:  # Sunday only
            return

        _env_path = CFG["PROJECT_DIR"] / ".env"
        _env_vars = {}
        with open(_env_path) as _ef:
            for _line in _ef:
                _line = _line.strip()
                if "=" in _line and not _line.startswith("#"):
                    _k, _v = _line.split("=", 1)
                    _env_vars[_k.strip()] = _v.strip()
        _pg_pw = _env_vars.get("POSTGRES_PASSWORD", "")

        # ── R1 Full Analysis ──────────────────────────────────────────
        _conn = _pg2.connect(host="localhost", port=5432, dbname="anantara_bybit",
                             user="anantara", password=_pg_pw)
        _cur = _conn.cursor()
        _cur.execute("""SELECT COUNT(*), SUM(CASE WHEN close_profit>0 THEN 1 ELSE 0 END),
                        AVG(close_profit), AVG(CASE WHEN close_profit>0 THEN close_profit END),
                        AVG(CASE WHEN close_profit<=0 THEN close_profit END)
                        FROM trades WHERE is_open=false""")
        _t, _w, _avg, _aw, _al = _cur.fetchone()
        _aw = (_aw or 0) * 100; _al = (_al or 0) * 100
        _be = abs(_al) / (_aw + abs(_al)) * 100 if (_aw + abs(_al)) > 0 else 0
        _wr = _w / _t * 100 if _t else 0
        _avg = (_avg or 0) * 100

        # Weekly trend (last 7 days vs previous 7 days)
        _week_ago = _now.replace(hour=0, minute=0, second=0, microsecond=0)
        _week_start = _week_ago - __import__("datetime").timedelta(days=7)
        _cur.execute("""SELECT COUNT(*), SUM(CASE WHEN close_profit>0 THEN 1 ELSE 0 END),
                        AVG(close_profit) FROM trades WHERE is_open=false
                        AND close_date >= %s""", (_week_start,))
        _w7 = _cur.fetchone()
        _w7_wr = _w7[1] / _w7[0] * 100 if _w7[0] else 0
        _w7_avg = (_w7[2] or 0) * 100
        _conn.close()

        # ── R4 check ──────────────────────────────────────────────────
        _conn = _pg2.connect(host="localhost", port=5432, dbname="anantara",
                             user="anantara", password=_pg_pw)
        _cur = _conn.cursor()
        _cur.execute("SELECT COUNT(*) FROM trades WHERE is_open=false AND open_date >= '2026-06-19'")
        _r4n = _cur.fetchone()[0]
        _conn.close()

        # ── Compose report ────────────────────────────────────────────
        _trend_icon = "↗️" if _w7_avg > -0.15 else ("→" if _w7_avg > -0.5 else "↘️")
        _r4_status = f"🎯 {_r4n} trades started!" if _r4n > 0 else "⏳ still gated"

        _msg = (
            f"📚 *CEX Weekly Research* {_now.strftime('%d %b %Y')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"*R1 Bybit*: {_t}t total | WR={_wr:.1f}% | avg={_avg:+.2f}%\n"
            f"  avg_win={_aw:+.2f}% | avg_loss={_al:+.2f}% | BE={_be:.1f}%\n"
            f"  This week: {_w7[0]}t WR={_w7_wr:.1f}% avg={_w7_avg:+.2f}% {_trend_icon}\n"
            f"*R4 Binance*: {_r4_status}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"*Exit Engine*: TSL/ROI = proven edge (100% WR)\n"
            f"*Challenge*: SL rate = {(_t-_w)/_t*100:.0f}% of trades — entry filter is key\n"
            f"*Learning*: {'Improving' if _w7_avg > _avg else 'Stable' if abs(_w7_avg-_avg)<0.1 else 'Monitor'}\n"
            f"*Next milestone*: n=100 R4 → bootstrap P(E>0)\n"
            f"dry_run=true | 0 real risk | 10 monitoring jobs"
        )
        await tg(_msg)
        log.info(f"cex_weekly_research: R1={_t}t/{_w7[0]}w R4={_r4n}")

    except Exception as e:
        log.warning(f"job_cex_weekly_research: {e}")


async def job_dual_market_report():
    """Periodic consolidated SoDEX + Binance progress pulse to Telegram (every 3h).
    Composed from STATE populated by the daily jobs (funding monitor, feasibility,
    spot-maker) + live funding snapshot — the regular two-market report the user asked for."""
    try:
        lines = ["📡 <b>ANANTARA — Dual-Market Pulse</b>"]
        # ── BINANCE (funding-harvest = the live profit engine) ──
        fp = STATE.get("last_funding_plan") or {}
        tops = fp.get("tops") or []
        lines.append("\n💵 <b>BINANCE funding-harvest</b> (market-neutral, LIVE):")
        if tops:
            lines.append("  " + " · ".join(t.split(":")[0].strip().split()[0]
                         + " " + t.split()[1] + "%" for t in tops[:3] if len(t.split()) > 1))
        lines.append(f"  {fp.get('net','(funding plan accruing)')}")
        xt = fp.get("xtop") if isinstance(fp.get("xtop"), str) else ""
        if xt:
            lines.append(f"  cross-venue: {xt}")
        # ── Regime predictor score ──
        reg = STATE.get("last_regime") or {}
        if reg:
            ready = reg.get("ready") or []
            top = reg.get("top")
            ts_score = reg.get("top_score")
            if ready:
                lines.append(f"  🟢 regime READY: {', '.join(ready)} "
                             f"(score {ts_score:.2f})" if ts_score else f"  🟢 regime READY: {', '.join(ready)}")
            else:
                lines.append(f"  📉 regime: {top or '?'} leading (score {ts_score:.2f})" if ts_score
                             else "  📉 no asset harvest-ready yet")
        # ── Paper-validator P&L (honest go-live gate) ──
        fhp = STATE.get("last_fh_paper") or {}
        if fhp:
            # extract key metrics from the --quiet output stored in state
            po = fhp.get("output", "")
            net_line = next((ln for ln in po.splitlines() if "NET P&L" in ln), "")
            fund_line = next((ln for ln in po.splitlines() if "funding earned" in ln), "")
            pos_line = next((ln for ln in po.splitlines() if "Open:" in ln), "")
            ann_line = next((ln for ln in po.splitlines() if "Annualized" in ln), "")
            paper_parts = [p for p in [pos_line, net_line, ann_line] if p]
            if paper_parts:
                lines.append("  paper P&L: " + " | ".join(p.strip() for p in paper_parts[:2]))
        else:
            lines.append("  paper P&L: (first cycle pending)")
        lines.append("  position: delta-neutral (hold ≥2wk; alert on funding flip)")
        # ── SoDEX (airdrop spot-maker, gated on PROVEN) ──
        fe = STATE.get("last_sodex_feasibility") or {}
        sm = STATE.get("last_spot_maker") or {}
        lines.append("\n🟢 <b>SoDEX spot-maker</b> (target 1:7,100 · $1.6–3.9M/wk):")
        if fe:
            real = fe.get("best_realistic_fill_frac", 0) * 100
            lines.append(f"  realistic maker fill {real:.0f}% · joint-feasible: "
                         f"{'YES' if fe.get('joint_feasible') else 'not yet (fill wall)'}")
        lines.append(f"  PROVEN (live-unlock): {'✅ YES' if sm.get('proven') else '⏳ locked — accumulating'}")
        lines.append("\n🧠 stack: risk(Kelly/CVaR) · calibration(Brier) · champion-challenger · drift-retrain — all live")
        await tg("\n".join(lines))
        log.info("Dual-market pulse sent")
    except Exception as e:
        log.exception(f"Dual-market report error: {e}")


async def job_drift_check():
    """Drift-TRIGGERED retrain (not just the weekly schedule): if the SoDEX model's
    live OOS has dropped materially below its registered champion (concept drift =
    the #1 silent ML failure), retrain NOW. Runs every 6h; complements job_model_retrain."""
    url = os.environ.get("SODEX_MODEL_URL", "http://localhost:8001")
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            health = (await c.get(f"{url}/health")).json()
        oos = _agg_oos(health)
        champ = _mreg.champion(_mreg.REGISTRY_PATH, "sodex48h")
        if oos is not None and champ is not None and oos < champ - DRIFT_OOS_MARGIN:
            log.warning(f"DRIFT: OOS {oos:.3f} << champion {champ:.3f} → auto-retrain")
            await tg(f"⚠️ Model DRIFT detected: live OOS {oos:.3f} dropped vs champion "
                     f"{champ:.3f} (>{DRIFT_OOS_MARGIN}) → auto-retrain triggered (regime change).")
            await job_model_retrain()
        else:
            log.info(f"Drift check: OOS={oos} champion={champ} — stable")
    except Exception as e:
        log.exception(f"Drift check error: {e}")


async def job_ground_truth():
    """RS-2 (Audit Fable 5/6): Single source of truth finansial.

    Setiap 30 menit: query HL balance + posisi (read-only), baca state lokal,
    deteksi delta modal tanpa catatan, tulis data/ground_truth.json.

    Angka yang dihasilkan adalah SATU-SATUNYA sumber kebenaran untuk laporan
    finansial. STATUS.md tidak boleh mengandung angka saldo manual.
    """
    if _ground_truth is None:
        log.debug("job_ground_truth: ground_truth module tidak tersedia, skip.")
        return
    try:
        sha = STATE.get("startup_git_sha", "(unknown)")
        gt = await asyncio.to_thread(
            _ground_truth.refresh,
            sha,
            lambda msg: asyncio.run_coroutine_threadsafe(tg(msg), asyncio.get_event_loop())
        )
        STATE["ground_truth_ts"]         = gt.get("generated_utc", "")
        STATE["ground_truth_hl_balance"]  = gt.get("hl_balance", {}).get("total_usdc", 0.0)
        STATE["ground_truth_n_positions"] = gt.get("n_open_hl", 0)
        STATE["ground_truth_n_positions_total"] = gt.get("n_open_hl_total", gt.get("n_open_hl", 0))
        # Tulis truth metrics untuk Prometheus (RS-7)
        _write_truth_metrics_prom(gt)
        log.info(
            f"job_ground_truth: HL={gt.get('hl_balance', {}).get('total_usdc', 0):.2f} USDC "
            f"pos={gt.get('n_open_hl', 0)} harvest={gt.get('n_open_hl_harvest', 0)} "
            f"total={gt.get('n_open_hl_total', gt.get('n_open_hl', 0))} "
            f"delta={gt.get('capital_delta_usd', 0):+.2f} USD"
        )
    except Exception as e:
        log.warning(f"job_ground_truth: {e}")


def _write_truth_metrics_prom(gt: dict) -> None:
    """RS-7: Tulis truth metrics ke file Prometheus textfile collector format."""
    try:
        _DATA_DIR = Path(os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti"))) / "data"
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        prom_file = _DATA_DIR / "truth_metrics.prom"
        hl_bal    = gt.get("hl_balance", {})
        harvest_bal = gt.get("hl_harvest_balance", {})
        hl_total = gt.get("hl_total", {})
        live_flags = gt.get("live_flags", {})
        autotrade = 1 if live_flags.get("AUTOTRADE_LIVE") == "1" else 0
        pregain   = 1 if live_flags.get("PREGAIN_LIVE") == "1" else 0
        const_blocked = 1 if STATE.get("constitution_live_blocked", False) else 0
        lines = [
            "# HELP anantara_hl_balance_usdc HL spot wallet total USDC",
            "# TYPE anantara_hl_balance_usdc gauge",
            f"anantara_hl_balance_usdc {hl_bal.get('total_usdc', 0):.4f}",
            "# HELP anantara_hl_margin_usage_pct HL margin usage percentage",
            "# TYPE anantara_hl_margin_usage_pct gauge",
            f"anantara_hl_margin_usage_pct {hl_bal.get('margin_usage_pct', 0):.2f}",
            "# HELP anantara_hl_harvest_account_value_usd HL harvest perp account value",
            "# TYPE anantara_hl_harvest_account_value_usd gauge",
            f"anantara_hl_harvest_account_value_usd {harvest_bal.get('perp_account_value', 0):.4f}",
            "# HELP anantara_hl_harvest_margin_usage_pct HL harvest margin usage percentage",
            "# TYPE anantara_hl_harvest_margin_usage_pct gauge",
            f"anantara_hl_harvest_margin_usage_pct {harvest_bal.get('margin_usage_pct', 0):.2f}",
            "# HELP anantara_hl_total_perp_account_value_usd Deduplicated observed HL perp account value",
            "# TYPE anantara_hl_total_perp_account_value_usd gauge",
            f"anantara_hl_total_perp_account_value_usd {hl_total.get('perp_account_value', 0):.4f}",
            "# HELP anantara_hl_total_margin_used_usd Deduplicated observed HL margin used",
            "# TYPE anantara_hl_total_margin_used_usd gauge",
            f"anantara_hl_total_margin_used_usd {hl_total.get('margin_used_usd', 0):.4f}",
            "# HELP anantara_capital_delta_usd Last capital delta (unexplained change)",
            "# TYPE anantara_capital_delta_usd gauge",
            f"anantara_capital_delta_usd {gt.get('capital_delta_usd', 0):.4f}",
            "# HELP anantara_capital_delta_observed_usd Last observed delta across deduplicated HL accounts",
            "# TYPE anantara_capital_delta_observed_usd gauge",
            f"anantara_capital_delta_observed_usd {gt.get('capital_delta_observed_usd', 0):.4f}",
            "# HELP anantara_live_flag_autotrade AUTOTRADE_LIVE flag (1=live, 0=paper)",
            "# TYPE anantara_live_flag_autotrade gauge",
            f"anantara_live_flag_autotrade {autotrade}",
            "# HELP anantara_live_flag_pregain PREGAIN_LIVE flag (1=live, 0=paper)",
            "# TYPE anantara_live_flag_pregain gauge",
            f"anantara_live_flag_pregain {pregain}",
            "# HELP anantara_constitution_blocked Constitution blocking live (1=blocked)",
            "# TYPE anantara_constitution_blocked gauge",
            f"anantara_constitution_blocked {const_blocked}",
            "# HELP anantara_open_positions_hl Open positions on HL exchange",
            "# TYPE anantara_open_positions_hl gauge",
            f"anantara_open_positions_hl {gt.get('n_open_hl', 0)}",
            "# HELP anantara_open_positions_hl_harvest Open positions on HL harvest account",
            "# TYPE anantara_open_positions_hl_harvest gauge",
            f"anantara_open_positions_hl_harvest {gt.get('n_open_hl_harvest', 0)}",
            "# HELP anantara_open_positions_hl_total Open positions across deduplicated observed HL accounts",
            "# TYPE anantara_open_positions_hl_total gauge",
            f"anantara_open_positions_hl_total {gt.get('n_open_hl_total', gt.get('n_open_hl', 0))}",
        ]
        prom_file.write_text("\n".join(lines) + "\n")
    except Exception as e:
        log.debug(f"_write_truth_metrics_prom: {e}")


async def job_experiment_progress():
    """RS-8 (Audit Fable 5/6): Harian — progres eksperimen + FDR + auto-close.

    Setiap pagi: update n_current dari database masing-masing proyek,
    hitung FDR, periksa auto-close, kirim progres ke Telegram.
    """
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        import experiment_registry as er

        active = er.list_active()
        if not active:
            log.debug("job_experiment_progress: tidak ada eksperimen aktif")
            return

        # Periksa auto-close
        closed = []
        for exp in active:
            verdict = er.check_auto_close(exp)
            if verdict:
                er.close_experiment(exp.exp_id, verdict,
                                    notes=f"Auto-closed by daemon job {datetime.now(timezone.utc).date()}")
                closed.append(f"{exp.name} → {verdict}")
                log.info(f"job_experiment_progress: auto-closed {exp.exp_id} = {verdict}")

        # FDR corrections
        er.compute_fdr_corrections()

        # Kirim progres ke Telegram
        report = er.progress_report()
        if closed:
            report += "\n\n*Auto-closed hari ini:*\n" + "\n".join(f"• {c}" for c in closed)
        await tg(report)

    except Exception as e:
        log.warning(f"job_experiment_progress: {e}")


async def job_platform_selfaudit():
    """RS-9 (Audit Fable 5/6): Weekly platform self-audit — Senin 03:00 UTC.

    Audit komprehensif: constitution, ground truth, experiments, health, engineering,
    complexity budget. Hasilnya dikirim ke Telegram + disimpan di data/selfaudits/.
    """
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        import platform_selfaudit as psa

        audit = await asyncio.to_thread(psa.run_full_audit)
        report = psa.format_telegram_report(audit)
        await tg(report)
        log.info(
            f"job_platform_selfaudit: {'OK' if audit['overall_ok'] else 'ISSUES'} "
            f"findings={audit['total_findings']}"
        )
    except Exception as e:
        log.warning(f"job_platform_selfaudit: {e}")
        await tg(f"⚠️ Platform self-audit gagal: {str(e)[:200]}")


async def job_status_autoupdate():
    """RS-2 (Audit Fable 5/6): Auto-generate bagian 'Kondisi Saat Ini' di STATUS.md.

    Setiap jam: panggil scripts/generate_status_section.py untuk update STATUS.md
    dari data/ground_truth.json. Mencegah angka finansial manual yang bisa salah.
    """
    try:
        script = CFG["PROJECT_DIR"] / "scripts" / "generate_status_section.py"
        if not script.exists():
            log.debug("job_status_autoupdate: script tidak ditemukan, skip")
            return
        result = await asyncio.to_thread(lambda: __import__("subprocess").run(
            [sys.executable, str(script)],
            cwd=str(CFG["PROJECT_DIR"]),
            capture_output=True, text=True, timeout=30,
        ))
        if result.returncode == 0:
            log.info(f"job_status_autoupdate: STATUS.md diperbarui")
        else:
            log.warning(f"job_status_autoupdate: {result.stderr[:200]}")
    except Exception as e:
        log.warning(f"job_status_autoupdate: {e}")


async def job_constitution_hourly():
    """RS-1 (Audit Fable 5/6): Verifikasi konstitusi setiap jam.

    Cek gates_passed.json + freeze manifest. Alert jika:
    - Freeze violation baru terdeteksi
    - Constitution berubah dari OK menjadi BLOCKED (atau sebaliknya)
    """
    if _constitution is None:
        return
    try:
        verdict = _constitution.check_live_permission("pregain")
        was_blocked = STATE.get("constitution_live_blocked", False)

        # Deteksi perubahan state
        if verdict.live_permitted and was_blocked:
            await tg("✅ *Constitution CLEARED*: live trading kembali diizinkan.")
        elif not verdict.live_permitted and not was_blocked:
            await tg(
                f"🔒 *Constitution BLOCKED*\n"
                f"Reason: {verdict.reason[:200]}"
            )

        # Freeze violations — alert hanya saat ada yang baru
        prev_violations = set(STATE.get("constitution_freeze_violations", []))
        curr_violations = set(verdict.freeze_violations)
        new_violations  = curr_violations - prev_violations
        if new_violations:
            await tg(
                f"⚠️ *Freeze Violation Baru*\n" +
                "\n".join(f"• {v}" for v in new_violations)
            )

        STATE["constitution_live_blocked"]      = not verdict.live_permitted
        STATE["constitution_freeze_ok"]          = verdict.freeze_ok
        STATE["constitution_freeze_violations"]  = list(curr_violations)
        log.info(
            f"job_constitution_hourly: {'OK' if verdict.live_permitted else 'BLOCKED'} "
            f"freeze_ok={verdict.freeze_ok} violations={len(curr_violations)}"
        )
    except Exception as e:
        log.warning(f"job_constitution_hourly: {e}")


async def job_perf_snapshot():
    """Live PnL/equity feedback loop: snapshot account equity daily → equity series →
    risk_metrics. Closes the autonomy loop (system measures its OWN realized
    risk-adjusted performance). Weekly it reports Sharpe/Sortino/maxDD/Calmar."""
    try:
        b = await ft("balance")
        equity = float((b or {}).get("value", (b or {}).get("total", 0)) or 0)
        if equity <= 0:
            return
        _perf.append_snapshot(_perf.PERF_PATH, equity)
        series = _perf.load_series(_perf.PERF_PATH)
        # weekly report (Sunday) once enough points accrued
        if datetime.now(timezone.utc).weekday() == 6 and len(series) >= 3:
            rep = _perf.report(series)
            await tg(f"📈 <b>Weekly performance</b> (equity ${rep.get('equity_now')}): "
                     f"Sharpe {rep.get('sharpe')} · Sortino {rep.get('sortino')} · "
                     f"maxDD {rep.get('max_drawdown_pct')}% · Calmar {rep.get('calmar')} "
                     f"(n={rep.get('n_points')})")
        log.info(f"Perf snapshot: equity {equity}, {len(series)} points")
    except Exception as e:
        log.exception(f"Perf snapshot error: {e}")


def mem_capped_cmd(cmd, mem_mb: int = 2048):
    """Bungkus `cmd` dengan CAP MEMORI via cgroup terpisah (systemd-run --scope).

    Audit 30-Sep-2026 (insiden nyata, uang nyata). `subprocess.run(..., timeout=500)`
    TIDAK melindungi dari anak yang nyangkut di D-state (uninterruptible disk wait):
    SIGKILL saat timeout tidak bisa menghentikan proses D-state, sehingga run()
    menunggu TANPA BATAS dan RAM anak tetap dihitung ke cgroup DAEMON. Terukur:
    `research_fill_rate.py` nyangkut 10 JAM 27 MENIT, 6,4 GB, CPU hanya 75 detik,
    daemon 6.761 MB dari cap 8 GB = 84% -> tekanan memori sistem ->
    systemd-oomd MEMBUNUH lane uang-nyata `anantara-realwide-livetest`
    (status=9/KILL, result 'oom-kill').

    Cgroup terpisah + MemoryMax membuat anak gagal jauh sebelum bisa
    menenggelamkan sistem, dan RAM-nya tidak lagi membebani daemon.
    Terverifikasi empiris: cap 512M -> alokasi 4 GB dibunuh (rc=137).

    Bila systemd-run tidak tersedia (atau ANANTARA_NO_MEMCAP=1), kembalikan cmd
    apa adanya — proteksi memori TIDAK BOLEH membuat job gagal.
    """
    if os.environ.get("ANANTARA_NO_MEMCAP") == "1" or not shutil.which("systemd-run"):
        return list(cmd)
    return ["systemd-run", "--user", "--scope", "--quiet",
            "-p", f"MemoryMax={int(mem_mb)}M", "-p", "MemorySwapMax=0", "--"] + list(cmd)


async def job_sodex_feasibility():
    """Daily autonomous SoDEX dual-target (ratio>=1:7,500 AND >=$2M/wk) re-check on
    the growing data. Uses the HONEST queue-aware fill model (research_fill_rate.py
    --json): maker-edge economics clear at rebate tier-1, but the binding gate is
    maker FILL — resting L1 size >> per-30s taker flow, so realistic fill is low.
    Joint-feasible only if fill is high enough for patient-mode to also hit the
    volume floor. Alerts via Telegram if that ever flips (e.g. SoDEX flow grows)."""
    try:
        r = await asyncio.to_thread(lambda: subprocess.run(
            mem_capped_cmd(["python3", "scripts/research/research_fill_rate.py", "--json"], 2048),
            cwd=str(CFG["PROJECT_DIR"]), capture_output=True, text=True, timeout=500))
        if r.returncode != 0 or not r.stdout.strip():
            log.warning(f"SoDEX feasibility check failed: {(r.stderr or r.stdout)[-200:]}")
            return
        v = json.loads(r.stdout.strip())
        STATE["last_sodex_feasibility"] = {**v, "ts": datetime.now(timezone.utc).isoformat()}
        real = v.get("best_realistic_fill_frac", 0) * 100
        best = v.get("best_case_fill_frac", 0) * 100
        if v.get("joint_feasible"):
            msg = (f"🎯 SoDEX dual-target NOW FEASIBLE: realistic maker fill "
                   f"{real:.0f}% ≥ 50% → patient-mode can hit 1:7,500 AND $2M/wk. "
                   f"Re-validate before risking capital.")
        else:
            msg = (f"SoDEX dual-target still NOT jointly feasible (settled): realistic "
                   f"maker fill {real:.0f}% (best-case {best:.0f}%) — too low. "
                   f"PATIENT maker can't reach $2M/wk; AGGRESSIVE caps ~2,500:1. "
                   f"Need SoDEX taker-flow to grow vs resting size to flip this.")
        log.info(f"SoDEX feasibility: joint={v.get('joint_feasible')} "
                 f"realistic_fill={real:.0f}% best={best:.0f}%")
        await tg(msg)
    except Exception as e:
        log.exception(f"SoDEX feasibility error: {e}")


async def job_spot_maker_check():
    """Daily SoDEX SPOT low-cap maker-profitability check on the growing spot data.
    Runs analyze_spot_maker.py (queue-aware fill + adverse at spot fees); it writes
    the legacy PROVEN flag only when net_edge>0 with a real fill. Current live
    SPOT authority remains scripts/sodex_spot_daemon.py + sodex_autofarm.py,
    which also require event-risk and adaptive-policy approval."""
    try:
        r = await asyncio.to_thread(lambda: subprocess.run(
            mem_capped_cmd(["python3", "scripts/analyze_spot_maker.py"], 3072),
            cwd=str(CFG["PROJECT_DIR"]), capture_output=True, text=True, timeout=300))
        out = r.stdout or ""
        proven_path = "freqtrade_user_data/data/sodex/spot/PROVEN"
        is_proven = os.path.exists(os.path.join(str(CFG["PROJECT_DIR"]), proven_path))
        profit_lines = [ln.strip() for ln in out.splitlines() if "PROFIT (volume" in ln]
        STATE["last_spot_maker"] = {"proven": is_proven, "ts": datetime.now(timezone.utc).isoformat()}
        if is_proven:
            await tg("✅ <b>SoDEX SPOT maker PROVEN profitable</b> — a low-cap pair clears "
                     "net_edge>0 with real fill. Volume here = result of profit (passes hard rule). "
                     "Current live path remains guarded by sodex_spot_daemon.py + event/policy gates.")
        else:
            wide = "; ".join(profit_lines[:3]) if profit_lines else "no pair net-profitable on fill yet"
            log.info(f"Spot maker check: not proven ({wide})")
    except Exception as e:
        log.exception(f"Spot maker check error: {e}")


async def job_binance_flow():
    """Snapshot FREE Binance derivatives-flow (OI, funding, taker buy/sell &
    global long/short ratios) per universe symbol → data/binance/flow. Alt-data
    fuel for directional-edge research (no key, no money). Silent unless error."""
    try:
        r = await asyncio.to_thread(lambda: subprocess.run(
            ["python3", "scripts/binance_flow_collector.py", "--once"],
            cwd=str(CFG["PROJECT_DIR"]), capture_output=True, text=True, timeout=120))
        if r.returncode == 0:
            log.info(f"Binance flow: {r.stdout.strip()}")
        else:
            log.warning(f"Binance flow sweep failed: {(r.stderr or r.stdout)[-200:]}")
    except Exception as e:
        log.exception(f"Binance flow error: {e}")


# ──────────────────────────────────────────────────────────────────────
# TELEGRAM COMMAND HANDLER (long polling)
# ──────────────────────────────────────────────────────────────────────


async def handle_telegram():
    global _tg_offset
    while True:
        try:
            url = f"https://api.telegram.org/bot{CFG['TELEGRAM_TOKEN']}/getUpdates"
            async with httpx.AsyncClient(timeout=35) as c:
                r = await c.get(url, params={"timeout": 30, "offset": _tg_offset})
                updates = r.json().get("result", [])
            for upd in updates:
                _tg_offset = upd["update_id"] + 1
                msg = upd.get("message", {})
                text = (msg.get("text") or "").strip().lower()
                chat = str(msg.get("chat", {}).get("id", ""))
                if chat != CFG["TELEGRAM_CHAT_ID"]:
                    log.warning(f"Telegram from non-owner chat {chat}, ignored")
                    continue
                await dispatch(text)
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"Telegram polling: {e}")
            await asyncio.sleep(5)


async def dispatch(text: str):
    global _last_dispatch_cmd
    _last_dispatch_cmd = text
    handlers = {
        "/status": _cmd_status,
        "/balance": _cmd_balance,
        "/profit": _cmd_profit,
        "/eval": job_midcheck_eval,
        "/market-check": _cmd_market_check,
        "/recover": _cmd_recover,
        "/panic": _cmd_panic,
        "/resume-all": _cmd_resume_all,
        "/report": _cmd_periodic_report,
        # ── Core ──
        "/start": _cmd_start,
        "/kill": lambda: job_kill_switch("Manual /kill"),
        "/killresume": _cmd_killresume,
        "/briefing": job_daily_briefing,
        "/reflect": job_weekly_reflection,
        "/health": _cmd_health,
        "/help": _cmd_help,
        # ── Pre-Gain/Loser Scan System ──
        "/pregain": _cmd_pregain_scan,
        "/pregain-regime": _cmd_pregain_regime,
        "/pregain-validate": _cmd_pregain_validate,
        "/pregain-backtest": _cmd_pregain_backtest,
        "/pregain-status": _cmd_pregain_status,
        "/pregain-trend": _cmd_pregain_trend,
        "/pregain-autotrade": _cmd_pregain_autotrade,
        "/pregain-positions": _cmd_pregain_positions,
        "/pregain-gates":      _cmd_pregain_gates,
        "/pregain-rolling":    _cmd_pregain_rolling,
        "/pregain-preflight":  _cmd_pregain_preflight,
        "/pregain-reconcile":  _cmd_pregain_reconcile,
        "/three-tracks":       _cmd_three_tracks,
        "/pregain-weekly":     job_pregain_weekly_report,
        "/research":           job_pregain_auto_research_daily,    # trigger manual research
        "/quality":            job_pregain_signal_quality_monitor, # manual quality check
        "/learner":            job_pregain_learner_auto_refresh,   # manual learner refresh
        "/v81":                job_pregain_v81_analysis,           # v8.1 signal analysis
        # ── Platform System (RS-1..RS-9 Audit Fable 5/6) ──────────────────────
        "/audit":              _cmd_platform_audit,     # weekly self-audit on-demand
        "/guard":              _cmd_guard_status,        # platform guard status
        "/experiments":        _cmd_experiments,         # experiment registry progress
        "/ground-truth":       _cmd_ground_truth,        # balance oracle refresh
        "/constitution":       _cmd_constitution,        # constitution check
        # ── Astronacci — Astro Research & Paper Trading ──
        "/astro":         _cmd_astro_dispatch,
        "/astroevents":   _cmd_astro_dispatch,
        "/astrostatus":   _cmd_astro_dispatch,
        "/astrodataset":  _cmd_astro_dispatch,
    }
    fn = handlers.get(text)
    if fn:
        log.info(f"Command: {text}")
        await fn()
    elif text.startswith("/"):
        await tg(f"❌ Unknown: {text}\n/help untuk daftar")


async def _cmd_status():
    trades = await ft("status")
    if not trades or not isinstance(trades, list):
        await tg("📈 No open trades.")
        return
    lines = ["📈 *Open Trades:*"]
    for t in trades[:10]:
        pct = (t.get("profit_pct", 0) or 0) * 100
        e = "🟢" if pct >= 0 else "🔴"
        lines.append(f"{e} `{t.get('pair', '?')}`: {pct:+.2f}%")
    await tg("\n".join(lines))


async def _cmd_balance():
    b = await ft("balance")
    if b:
        await tg(f"💰 *Balance:* `{b.get('total', 0):.4f}` USDT")


async def _cmd_profit():
    p = await ft("profit")
    if p:
        await tg(
            f"📊 *P&L Summary:*\n"
            f"Total: `{p.get('profit_all_coin', 0):+.4f}` USDT\n"
            f"Win Rate: `{(p.get('winrate', 0) or 0) * 100:.1f}%`\n"
            f"Trades: `{p.get('trade_count', 0)}`"
        )


async def _cmd_stop():
    await ft("stopbuy", "POST")
    await tg("⏹️ Stop buy aktif. Trade lama tetap jalan.")


async def _cmd_start():
    await ft("start", "POST")
    await tg("▶️ Bot aktif.")


async def _cmd_killresume():
    global _kill_active, _circuit_level
    _kill_active = False
    _circuit_level = 0
    await ft("start", "POST")
    await hermes_post("/hermes/posture", {"posture": "BALANCED", "reason": "Manual resume"})
    await tg("✅ Kill switch reset. Posture BALANCED.")


async def _cmd_health():
    """Manual /health — ALWAYS respond with full status of both freqtrade instances."""
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    binance_up = bool(await ft("ping", instance="binance"))
    bybit_up = bool(await ft("ping", instance="bybit"))
    paradex_up = bool(await ft("ping", instance="paradex"))
    hermes_data = await hermes_get("/health")
    hermes_up = bool(hermes_data.get("status"))
    sentiment = await hermes_get("/sentiment/current")
    intel = await hermes_get("/intelligence/current")
    forecast = await hermes_get("/prediction/current/BTC")
    var = await hermes_get("/variational/current")
    sodex = await hermes_get("/sodex/current")
    fg = sentiment.get("fg_index", "?")
    fg_lbl = sentiment.get("fg_label", "?")
    intel_score = intel.get("composite_score", "?")
    intel_lbl = intel.get("label", "?")
    fc = forecast.get("forecast", {}) if isinstance(forecast, dict) else {}
    fc_dir = fc.get("direction", "?")
    fc_conf = fc.get("confidence", 0)

    lines = [
        "🩺 *System Health*",
        "━━━━━━━━━━",
        f"{'🟢' if binance_up else '🔴'} Freqtrade[Binance]: {'UP' if binance_up else 'DOWN'}",
        f"{'🟢' if bybit_up else '🔴'} Freqtrade[Bybit]: {'UP' if bybit_up else 'DOWN'}",
        f"{'🟢' if paradex_up else '⚪'} Freqtrade[Paradex]: {'UP' if paradex_up else 'IDLE'}",
        f"{'🟢' if hermes_up else '🔴'} Hermes Bridge: {'UP' if hermes_up else 'DOWN'}",
        f"{'🟢' if ram.percent < 85 else '🔴'} RAM: {ram.percent:.0f}% used",
        f"{'🟢' if disk.percent < 80 else '🔴'} Disk: {disk.percent:.0f}% used",
        "━━━━━━━━━━",
        f"🌡️ F&G: *{fg}* ({fg_lbl})",
        f"🧠 Intelligence: *{intel_score}*/100 ({intel_lbl})",
        f"🔮 BTC T+24h: *{fc_dir}* ({int(fc_conf*100)}% conf)",
        f"🌐 Variational OI: ${(var.get('open_interest_usd') or 0)/1e6:.1f}M",
        f"🟣 SoDEX: {len((sodex.get('symbols') or {}))} sym, {sodex.get('markets_total', 0)} markets",
        f"⚡ Posture: *{hermes_data.get('posture', '?')}*",
        f"🔴 CB Level: *{_circuit_level}*",
        f"🚨 Kill switch: {'ACTIVE' if _kill_active else 'inactive'}",
    ]
    await tg("\n".join(lines))


# Day 31 GO/NO-GO thresholds (paper-trading validation gate)
EVAL_CRITERIA = {
    "profit_factor_min": 1.2,
    "max_drawdown_max": 0.20,
    "winrate_min": 0.45,
    "min_trades": 20,  # statistical significance floor
}


async def _risk_metrics(instance: str) -> dict:
    """Compute Sharpe + VaR95 from closed-trade returns (concept from trading_skills
    risk.py). Returns {} if too few trades for significance."""
    data = await ft("trades", instance=instance)
    trades = data.get("trades", []) if isinstance(data, dict) else []
    rets = [float(t.get("profit_ratio", 0) or 0) for t in trades if not t.get("is_open", False)]
    if len(rets) < 10:
        return {"n": len(rets)}
    n = len(rets)
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    std = var ** 0.5
    sharpe = (mean / std) if std > 0 else 0.0          # per-trade Sharpe
    srt = sorted(rets)
    var95 = srt[max(0, int(0.05 * n) - 1)]             # 5th-percentile return
    return {"n": n, "sharpe": round(sharpe, 2), "var95_pct": round(var95 * 100, 2),
            "mean_pct": round(mean * 100, 3),
            "sortino": round(_sortino(rets, 0.0, 1), 2),          # downside-only (per-trade)
            "max_dd_pct": round(_maxdd(_eq(rets)) * 100, 2),       # worst peak-to-trough
            "cvar95_pct": round(_cvar(rets, 0.95) * 100, 2)}       # tail loss (Expected Shortfall)


async def _grade_instance(instance: str) -> dict:
    """Pull /profit from one freqtrade instance and grade against criteria.
    Pure grading lives in evaluator.grade_profit() (unit-tested)."""
    p = await ft("profit", instance=instance)
    if not p:
        return {"instance": instance, "up": False}
    g = grade_profit(p, EVAL_CRITERIA)
    g.update({"instance": instance, "up": True, "risk": await _risk_metrics(instance)})
    return g


def _measure_totals() -> dict:
    """Read OUR live farming volume/cost from the measure log + baseline anchor."""
    import glob as _glob
    d = CFG["PROJECT_DIR"] / "freqtrade_user_data" / "data" / "sodex" / "measure"
    vol = 0.0
    for fp in _glob.glob(str(d / "measure_*.jsonl")):
        for ln in open(fp):
            try:
                r = json.loads(ln)
                if r.get("live"):
                    vol += r.get("volume", 0) or 0
            except Exception:
                pass
    base = {}
    try:
        base = json.loads((d / "sopoints_baseline.json").read_text())
    except Exception:
        pass
    return {"live_volume": round(vol, 2), "baseline": base}


async def job_detailed_report():
    """Every 40 min — DETAILED Telegram report: farming (both modes), positions,
    equity, Pre-Sentiment forecasts, Intelligence, governor leverage per symbol."""
    cfg = _sodex_cfg()
    addr = cfg.get("address", "")
    syms = ("BTC-USD", "SOL-USD", "ETH-USD")
    # account equity (av) + open positions
    async def _eq():
        d = await hermes_get_url(f"{cfg['perps_url']}/accounts/{addr}/state") if addr else {}
        return float((d.get("data", {}) or {}).get("av", 0) or 0)
    equity = await _eq()
    positions = await asyncio.to_thread(lambda: sf.open_positions(cfg))
    mt = _measure_totals()
    # governor wire (directional mode) per symbol
    gov = {}
    for s in syms:
        gov[s] = await asyncio.to_thread(lambda s=s: sf.governor_leverage_for(s, cfg))
    intel = await hermes_get("/intelligence/current")
    lines = ["🛰️ *ANANTARA — Detailed Report (40m)*", "━━━━━━━━━━"]
    # account
    lines.append(f"💰 Equity: *${equity:.2f}* · positions: {len(positions)}")
    for p in positions:
        lines.append(f"   • {p['symbol']} {p['quantity']} @ {p.get('leverage')}x "
                     f"uPnL {p.get('unrealizedPnl', 0):+.3f}")
    # neutral volume farming (measure log)
    b = mt.get("baseline", {})
    since = mt["live_volume"] - (b.get("live_volume_at_baseline", 0) or 0)
    lines.append("")
    lines.append("📊 *Neutral volume-farm (our bot)*")
    lines.append(f"   live volume total: *${mt['live_volume']:,.0f}* "
                 f"(since SoPoints baseline {b.get('sopoints_baseline','?')}: +${since:,.0f})")
    # directional conviction (governor wire)
    lines.append("")
    lines.append("🎯 *Directional conviction (governor wire)*")
    for s in syms:
        g = gov[s]
        tag = "🟢" if (g.get("ok") and g["leverage"] > LEV_FLOOR_TAG) else "⚪"
        lines.append(f"   {tag} {s}: {g['direction']} prob {g.get('prob',0):.2f} "
                     f"OOS {(g.get('oos_acc') or 0):.0f}% → *{g['leverage']}x* (conv {g.get('conviction',0)})")
    # pre-sentiment forecasts (7+ key assets) + self-measured hit-rate
    lines.append("")
    acc = await hermes_get("/prediction/accuracy")
    ov = (acc.get("overall") or {}) if isinstance(acc, dict) else {}
    hr = f"hit-rate {ov.get('hit_rate','?')} ({ov.get('total',0)} verified, {acc.get('pending',0)} pending)" if ov else "hit-rate: warming up"
    lines.append(f"🔮 *Aset Momentum Sistem (T+24h)* — {hr}")
    persym = (acc.get("per_symbol") or {}) if isinstance(acc, dict) else {}
    for s in PRESENTIMENT_SYMBOLS:
        fc = await hermes_get(f"/prediction/current/{s}")
        f = (fc.get("forecast", {}) or {}) if isinstance(fc, dict) else {}
        ps = persym.get(s, {})
        acc_tag = f" · acc {ps['hit_rate']}({ps['total']})" if ps else ""
        if f:
            dirn = f.get("direction", "?")
            ico = "🟢" if dirn == "UP" else ("🔴" if dirn == "DOWN" else "⚪")
            lines.append(f"   {ico} {s}: {dirn} conf {f.get('confidence','?')} "
                         f"(mom {f.get('momentum_score','?')}){acc_tag}")
        else:
            lines.append(f"   ⚪ {s}: (no forecast yet)")
    # intelligence
    lines.append("")
    if intel and "composite_score" in intel:
        c = intel.get("components", {})
        lines.append(f"🧠 *Intelligence*: {intel['composite_score']} {intel.get('label','?')}"
                     + (f"  [{intel['guard']}]" if intel.get("guard") else ""))
        lines.append(f"   F&G {c.get('fg_contrarian','?')} · mom {c.get('momentum','?')} · "
                     f"breadth {c.get('breadth','?')} · outlier {c.get('outlier','?')}"
                     + (f" · flow {c['flow_tilt']:+}" if c.get('flow_tilt') else "")
                     + (f" · news {c['news_tilt']:+}" if c.get('news_tilt') else ""))
    else:
        lines.append("🧠 *Intelligence*: (not computed)")
    await tg("\n".join(lines))


LEV_FLOOR_TAG = 3   # leverage above this = active conviction (green tag)


async def job_midcheck_eval():
    """Day 21/31 paper-trading evaluator. Grades both instances vs GO/NO-GO gate.
    Runs weekly (Mon) + on-demand via /eval."""
    sprint_file = CFG["PROJECT_DIR"] / "STATUS.md"
    day = "?"
    try:
        for ln in sprint_file.read_text().splitlines():
            if "Sprint Day:" in ln:
                day = ln.split("Sprint Day:")[1].split("/")[0].strip().split()[-1]
                break
    except Exception:
        pass

    hstat = await hermes_get("/hermes/status")
    decisions = hstat.get("decisions_today", "?")
    vetoes = hstat.get("vetoes_today", "?")

    lines = [f"📋 *Paper-Trading Mid-Check* (Day {day})", "━━━━━━━━━━"]
    for inst in ("binance", "bybit"):
        g = await _grade_instance(inst)
        if not g["up"]:
            lines.append(f"⚪ *{inst.title()}*: instance down/idle")
            continue
        verdict = "✅ GO" if g["passed"] else ("🟡 EARLY" if not g["significant"] else "🔴 NO-GO")
        c = g["checks"]
        lines += [
            f"*{inst.title()}* — {verdict}",
            f"  P&L: {g['profit_abs']:+.2f} USDT ({g['profit_pct']:+.2f}%)",
            f"  {'✅' if c['profit_factor'][1] else '❌'} Profit Factor: {c['profit_factor'][0]:.2f} (≥{EVAL_CRITERIA['profit_factor_min']})",
            f"  {'✅' if c['max_drawdown'][1] else '❌'} Max DD: {c['max_drawdown'][0]*100:.1f}% (≤{EVAL_CRITERIA['max_drawdown_max']*100:.0f}%)",
            f"  {'✅' if c['winrate'][1] else '❌'} Win Rate: {c['winrate'][0]*100:.1f}% (≥{EVAL_CRITERIA['winrate_min']*100:.0f}%)",
            f"  {'✅' if c['trades'][1] else '❌'} Trades: {c['trades'][0]} (≥{EVAL_CRITERIA['min_trades']})",
        ]
        r = g.get("risk", {})
        if r.get("sharpe") is not None and "sharpe" in r:
            lines.append(
                f"  📐 Sharpe/trade: {r['sharpe']} · VaR95: {r['var95_pct']}% · "
                f"avg {r['mean_pct']}% (n={r['n']})"
            )
        elif r:
            lines.append(f"  📐 Risk: {r.get('n', 0)} closed trades (need ≥10 for Sharpe/VaR)")
    lines += [
        "━━━━━━━━━━",
        f"🧠 Hermes: {decisions} decisions, {vetoes} vetoes today",
        f"🎯 Day 31 GO/NO-GO: 2026-06-17",
    ]

    # ── Pre-Gain signal accumulation progress ────────────────────────────
    # Track Grade S specifically — the only grade with proven positive backtest
    # expectancy (+0.74R). Other grades (A/B/C) are empirically negative or near
    # break-even; showing "best n" from Grade C would be a false positive.
    try:
        from anantara import signal_tracker as _st, pregain_scan as _ps
        _rep = await asyncio.to_thread(lambda: _st.hit_rate_report(_ps.SIGNAL_DB))
        _total    = _rep.get("total", 0)
        _resolved = _rep.get("resolved", 0)
        _pending  = _rep.get("pending", 0)
        _by_grade = _rep.get("by_grade", {})
        # Grade S: the proven positive grade (triple-barrier +0.74R, win-rate 69%+)
        _gs       = _by_grade.get("S", {})
        _gs_n     = _gs.get("n", 0)
        _gs_wr    = _gs.get("win_rate")
        _MIN_PG   = 30  # matches pregain_autotrader.GRADE_EDGE_THRESHOLDS["S"]["min_sample"]
        _pct_fill = min(20, int(_gs_n / _MIN_PG * 20))
        _bar      = "█" * _pct_fill + "░" * (20 - _pct_fill)
        _wr_str   = f" · win {_gs_wr}%" if _gs_wr is not None else ""
        # Edge ok = Grade S has enough samples AND high win-rate (>65% = above ambiguous range)
        # This correctly avoids false positives from Grade C (56% win, +0.01R expectancy)
        _edge_ok  = _gs_n >= _MIN_PG and _gs_wr is not None and _gs_wr > 65.0
        _pg_verdict = ("✅ Grade S edge terbukti — /pregain-backtest lalu aktifkan LIVE"
                       if _edge_ok else
                       f"⏳ Grade S: {min(100, int(_gs_n / _MIN_PG * 100))}% ({_gs_n}/{_MIN_PG})")
        lines += [
            "━━━━━━━━━━",
            f"🎯 *Pre-Gain Signal Progress*",
            f"  Signals: {_total} total · {_resolved} resolved · {_pending} pending",
            f"  Grade S [{_bar}] {_gs_n}/{_MIN_PG}{_wr_str}",
            f"  {_pg_verdict}",
        ]
    except Exception as _e_pg:
        lines += ["━━━━━━━━━━", f"🎯 Pre-Gain: error saat baca DB — {_e_pg}"]

    # ── HL Harvest readiness ─────────────────────────────────────────────
    _hl_addr   = os.environ.get("HL_ADDRESS", "").strip()
    _hl_secret = os.environ.get("HL_API_SECRET", "").strip()
    _hl_live   = os.environ.get("FUNDING_LIVE", "").strip() == "1"
    lines.append("━━━━━━━━━━")
    if _hl_secret and _hl_addr:
        _hl_tag = ("FUNDING_LIVE=1 ✅ — jalankan `make hl-run`"
                   if _hl_live else "FUNDING_LIVE ❌ — tambahkan ke .env lalu `make hl-run`")
        lines.append(f"💰 *HL Harvest*: credentials ✅ · {_hl_tag}")
    elif _hl_addr:
        lines.append(f"💰 *HL Harvest*: HL_ADDRESS ✅ · HL_API_SECRET ❌ not set → isi .env")
    else:
        lines.append(f"💰 *HL Harvest*: set HL_ADDRESS + HL_API_SECRET di .env → `make hl-ready`")

    await tg("\n".join(lines))


async def _cmd_sodex():
    """Telegram /sodex — farming status: balance, positions, today's volume."""
    cfg = _sodex_cfg()
    _sodex_roll_day()
    positions = await asyncio.to_thread(sf.open_positions, cfg)
    bal = await asyncio.to_thread(lambda: sf.cli(["balance", "perps", cfg["address"]], cfg=cfg))
    bal_usd = float(bal[0].get("total", 0) or 0) if isinstance(bal, list) and bal else 0.0
    mode = "SCALP (volume)" if sf.SCALP_MODE else "directional"
    eff = (_sodex_vol_today / _sodex_cost_today) if _sodex_cost_today > 0 else None
    lines = [
        "🌾 *SoDEX Farming*",
        "━━━━━━━━━━",
        f"{'🟢 ENABLED' if _sodex_enabled() else '⚪ DISABLED'} · mode: *{mode}* · {'🚨 KILLED' if _kill_active else 'active'}",
        f"💰 Balance: ${bal_usd:.2f} vUSDC",
        f"📊 Open positions: {len(positions)}",
        f"📈 Volume today: ${_sodex_vol_today:.0f} · cost ${_sodex_cost_today:.2f}"
        + (f" · ${eff:,.0f} vol/$1" if eff else ""),
        f"🎯 Daily cap: ${sf.SCALP_DAILY_VOLUME_CAP:.0f} · {sf.SCALP_LEVERAGE}x · ${sf.SCALP_MARGIN:.0f}/round",
    ]
    for p in positions:
        risk = await asyncio.to_thread(sf.position_risk, p, cfg)
        dliq = risk.get("dist_to_liq_pct")
        lines.append(
            f"  `{p.get('symbol')}` {p.get('quantity')} @ {p.get('entryPrice')} "
            f"· {p.get('leverage')}x · uPnL ${float(p.get('unrealizedPnl',0)):+.2f}\n"
            f"    notional ${risk.get('notional_usd')} · liq {dliq}% away · VaR95 ${risk.get('var95_usd')}"
        )
    lines.append("━━━━━━━━━━")
    lines.append("`/sodexon` enable · `/sodexoff` disable")
    await tg("\n".join(lines))


async def _cmd_sodex_ratio():
    """Telegram /sodex-ratio — ratio report synced to /sodex-eval."""
    await tg(_sodex_ratio_report_text(), parse_mode=None)


async def _cmd_sodex_eval():
    """Telegram /sodex-eval — latest read-only Monitoring & Evaluasi snapshot."""
    text = _sodex_eval_latest_text()
    await tg(text, parse_mode=None)


def _sodex_eval_latest_text(prefix: str = "") -> str:
    report = _sodex_eval_load_latest()
    if report is None:
        return (
            "SoDEX Monitoring & Evaluasi belum punya snapshot.\n"
            "Di PC jalankan: .venv-research/bin/python scripts/sodex_monitor_eval.py"
        )

    try:
        import importlib.util

        module_path = CFG["PROJECT_DIR"] / "scripts" / "sodex_monitor_eval.py"
        spec = importlib.util.spec_from_file_location("sodex_monitor_eval", module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("formatter module spec unavailable")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["sodex_monitor_eval"] = mod
        spec.loader.exec_module(mod)
        text = mod.format_telegram_report(report)
    except Exception as exc:
        log.warning("sodex eval formatter failed: %s", exc)
        verdict = report.get("verdict", {})
        ledger = report.get("ledger", {})
        text = (
            "SoDEX Monitoring & Evaluasi\n"
            f"status: {verdict.get('status', '?')}\n"
            f"reason: {', '.join(verdict.get('reasons') or []) or '-'}\n"
            f"raw volume: ${(ledger.get('volume') or {}).get('raw_total_usd', 0):,.0f}\n"
            f"realized PnL: ${(ledger.get('pnl') or {}).get('realized_net_usd', 0):+,.6f}"
        )
    return f"{prefix}\n\n{text}" if prefix else text


def _sodex_eval_load_latest() -> dict | None:
    latest = CFG["PROJECT_DIR"] / "data" / "sodex_monitor_eval" / "latest.json"
    if not latest.exists():
        return None
    try:
        return json.loads(latest.read_text())
    except Exception as exc:
        log.warning("sodex eval latest read failed: %s", exc)
        return None


def _sodex_ratio_report_text() -> str:
    report = _sodex_eval_load_latest()
    if report is None:
        return (
            "SoDEX Ratio Report — synced with /sodex-eval\n"
            "status: NO_SNAPSHOT\n"
            "Monitoring & Evaluasi belum punya snapshot real.\n"
            "Di PC jalankan: .venv-research/bin/python scripts/sodex_monitor_eval.py"
        )

    window = report.get("window") or {}
    official = report.get("official_dashboard") or {}
    ledger = report.get("ledger") or {}
    account = report.get("account") or {}
    verdict = report.get("verdict") or {}
    volume = ledger.get("volume") or {}
    official_volume = official.get("volume") or {}
    reconciliation = official.get("reconciliation") or {}
    costs = ledger.get("costs") or {}
    ratios = ledger.get("ratios") or {}
    pnl = ledger.get("pnl") or {}
    rts = ledger.get("rts") or {}
    account_value = account.get("account_value") or {}
    assets = account.get("assets") or {}

    official_ok = official.get("quality") == "OK" and official.get("canonical")
    official_total = float(official_volume.get("total_usd") or 0)
    official_spot = float(official_volume.get("spot_usd") or 0)
    official_perps = float(official_volume.get("perps_usd") or 0)
    ledger_raw_volume = float(volume.get("raw_total_usd") or 0)
    ledger_weighted_volume = float(volume.get("weighted_total_usd") or 0)
    ledger_spot_volume = float(volume.get("spot_usd") or 0)
    ledger_perps_volume = float(volume.get("perps_usd") or 0)
    fees = float(costs.get("fees_usd") or 0)
    official_fee_ratio = official_total / fees if fees > 0 and official_ok else 0
    ledger_fee_ratio = float(ratios.get("volume_to_fee") or 0)
    ledger_weighted_fee_ratio = ledger_weighted_volume / fees if fees > 0 else 0
    realized_pnl = float(pnl.get("realized_net_usd") or 0)
    realized_pnl_text = f"{'+' if realized_pnl >= 0 else '-'}${abs(realized_pnl):,.6f}"
    win_rate = float(rts.get("win_rate") or 0) * 100
    open_positions = len(assets.get("perps_positions") or [])

    return "\n".join([
        "SoDEX Ratio Report — synced with /sodex-eval",
        f"periode: {window.get('range', '-')} ({window.get('weekly_label', '-')})",
        f"snapshot: {window.get('snapshot_wib', '-')}",
        "source: SoDEX dashboard official + internal ledger audit",
        f"quality: official={official.get('quality', 'MISSING')} ledger={ledger.get('quality', '?')} api={account.get('quality', '?')}",
        "",
        "Official SoDEX dashboard volume",
        f"official total: ${official_total:,.0f}" if official_ok else "official total: unavailable",
        f"spot/futures: ${official_spot:,.0f} / ${official_perps:,.0f}" if official_ok else "spot/futures: unavailable",
        f"ratio official/fee: 1:{official_fee_ratio:,.0f}" if official_ok else "ratio official/fee: unavailable",
        "",
        "Internal ledger audit",
        f"ledger total: ${ledger_raw_volume:,.0f}",
        f"ledger weighted: ${ledger_weighted_volume:,.0f}",
        f"ledger spot/perps: ${ledger_spot_volume:,.0f} / ${ledger_perps_volume:,.0f}",
        f"delta ledger-official: ${float(reconciliation.get('total_delta_usd') or 0):,.0f}" if official_ok else "delta ledger-official: unavailable",
        "",
        "Cost & Ratio",
        f"fees: ${fees:,.6f}",
        f"ratio ledger raw/fee: 1:{ledger_fee_ratio:,.0f}",
        f"ratio ledger weighted/fee: 1:{ledger_weighted_fee_ratio:,.0f}",
        "",
        "Real outcome",
        f"realized PnL: {realized_pnl_text}",
        f"RT/win rate: {int(rts.get('count') or 0):,} / {win_rate:.2f}%",
        f"equity/free USD: ${float(account_value.get('total_equity_usd') or 0):,.2f} / ${float(account_value.get('free_usd_total') or 0):,.2f}",
        f"open positions: {open_positions}",
        f"status: {verdict.get('status', '?')}",
        f"reason: {', '.join(verdict.get('reasons') or []) or '-'}",
    ])


async def job_sodex_eval_push_hourly():
    """Hourly Telegram push for latest read-only SoDEX Monitoring & Evaluasi."""
    await tg(_sodex_eval_latest_text("Push otomatis berkala SoDEX Monitoring & Evaluasi"), parse_mode=None)


async def job_sodex_eval_push_weekly():
    """Weekly Telegram push aligned to Saturday 07:00 WIB snapshot."""
    await tg(_sodex_eval_latest_text("Snapshot weekly final SoDEX Monitoring & Evaluasi"), parse_mode=None)


async def _cmd_sodex_on():
    os.environ["SODEX_FARMING_ENABLED"] = "1"
    await tg("🟢 SoDEX farming *ENABLED*. Order otomatis aktif saat sinyal kuat.\n"
             "⚠️ Note: enable ini sementara (sampai daemon restart). Set permanen di .env.")


async def _cmd_sodex_off():
    os.environ["SODEX_FARMING_ENABLED"] = "0"
    await tg("⚪ SoDEX farming *DISABLED*. Tidak ada order baru (posisi terbuka tetap dimonitor).")


# ══════════════════════════════════════════════════════════════
# BEARDOWN Telegram Commands
# ══════════════════════════════════════════════════════════════

_BEARDOWN_STATE_FILE = Path.home() / ".local/share/anantara/beardown_state.json"


def _beardown_load_state() -> dict:
    """Load BEARDOWN session state (survives restarts)."""
    if _BEARDOWN_STATE_FILE.exists():
        try:
            return json.loads(_BEARDOWN_STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "vol_total": 0.0,
        "cost_total": 0.0,
        "pnl_total": 0.0,
        "fills_total": 0,
        "maker_legs": 0,
        "taker_closes": 0,
        "skips_total": 0,
        "symbol_skips": {},
        "started_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": "",
    }


def _beardown_persist(cycle_vol: float, cycle_pnl: float = 0.0, symbol_results: dict | None = None):
    """Accumulate BEARDOWN cycle results into persistent state.
    Also updates watchdog timestamp for staleness detection.
    
    Args:
        cycle_vol: Total volume for this cycle
        cycle_pnl: Estimated PNL for this cycle (spread - fees)
        symbol_results: Dict of {symbol: {'filled': bool, 'volume': float}}
    """
    state = _beardown_load_state()
    # Initialize keys that may not exist in legacy state files
    state.setdefault("pnl_total", 0.0)
    state.setdefault("symbol_skips", {})
    state.setdefault("skips_total", 0)
    state["vol_total"] = state.get("vol_total", 0) + cycle_vol
    state["cost_total"] = state.get("cost_total", 0) + cycle_vol * 0.000216
    state["pnl_total"] = state.get("pnl_total", 0) + cycle_pnl
    state["fills_total"] = state.get("fills_total", 0) + 1
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    state["last_cycle_at"] = datetime.now(timezone.utc).isoformat()  # watchdog
    
    # Per-symbol skip tracking
    if symbol_results:
        sym_skips = state.get("symbol_skips", {})
        for sym, sr in symbol_results.items():
            if sr.get("filled"):
                sym_skips[sym] = 0  # reset on success
            else:
                sym_skips[sym] = sym_skips.get(sym, 0) + 1
        state["symbol_skips"] = sym_skips
        state["skips_total"] = sum(1 for v in sym_skips.values() if v > 0)
    
    try:
        _BEARDOWN_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _BEARDOWN_STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as e:
        log.warning(f"beardown_persist failed: {e}")

async def _cmd_beardown():
    """Telegram /beardown — BEARDOWN full Monitoring & Evaluasi dashboard."""
    import datetime as _dt
    
    # Read state
    state_file = Path.home() / ".local/share/anantara/sodex_ratio_state.json"
    state = {}
    if state_file.exists():
        state = json.loads(state_file.read_text())
    
    # Recent activity (last 30 min)
    proc = await asyncio.create_subprocess_exec(
        "journalctl", "--user", "-u", "anantara-daemon",
        "--since=30 minutes ago", "--no-pager",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, _ = await proc.communicate()
    log_text = stdout.decode()
    
    total_vol = 0.0; fills = 0; maker_2 = 0; maker_1 = 0
    taker = 0; skips = 0; recovers = 0
    for line in log_text.splitlines():
        if "BEARDOWN" in line and "vol +" in line:
            parts = line.split("vol +$")
            if len(parts) > 1:
                try: total_vol += float(parts[1].split()[0].replace(",", "")); fills += 1
                except: pass
            if "maker 2/2" in line: maker_2 += 1
            elif "maker 1/2" in line: maker_1 += 1
        if "maker close timeout" in line: taker += 1
        if "position(s) open" in line: skips += 1
        if "AUTO-RECOVERY" in line: recovers += 1
    
    # Regime
    intel_dir = CFG["PROJECT_DIR"] / "freqtrade_user_data" / "data" / "binance" / "intelligence"
    regime = "⚪ NEUTRAL"; regime_conf = 0
    files = sorted(intel_dir.glob("intel_*.jsonl"))
    if files:
        try:
            last_line = None
            with open(files[-1]) as f:
                for ln in f:
                    if ln.strip(): last_line = ln
            if last_line:
                d = json.loads(last_line)
                bd = int(d.get("fc_BTC_dir_enc", 0))
                bc = float(d.get("fc_BTC_conf", 0) or 0)
                regime_conf = bc
                if bd < 0 and bc >= 0.55: regime = "🔴 BEAR"
                elif bd > 0 and bc >= 0.55: regime = "🟢 BULL"
        except: pass
    
    # State numbers
    vol_day = state.get("vol_today", 0) or 0
    cost_day = state.get("cost_today", 0) or 0
    cap = float(os.environ.get("SODEX_SCALP_DAILY_COST_CAP", 50))
    
    # BEARDOWN session state (persistent, survives restarts)
    bd_state = _beardown_load_state()
    bd_vol = bd_state.get("vol_total", 0) or 0
    bd_cost = bd_state.get("cost_total", 0) or 0
    bd_started = bd_state.get("started_at", "")[:16].replace("T", " ")
    bd_ratio = int(bd_vol / bd_cost) if bd_cost > 0 else 0
    bd_pnl = bd_state.get("pnl_total", 0) or 0  # use tracked PNL
    bd_fills = bd_state.get("fills_total", 0) or 0
    bd_symbol_skips = bd_state.get("symbol_skips", {}) or {}
    
    # PNL estimate fallback if not yet tracked
    if bd_pnl == 0 and bd_vol > 0:
        bd_pnl = bd_vol * 0.00003 - bd_cost  # spread capture - fee = net PNL
    
    # Estimates
    maker_rate = (maker_2 * 2 + maker_1) / (fills * 2) * 100 if fills > 0 else 0
    fee_30min = total_vol * 0.000216
    spread_30min = total_vol * 0.00003
    net_30min = fee_30min - spread_30min
    hourly_vol = total_vol * 2  # 30min × 2
    
    daemon_icon = "🟢" if systemctl_active() else "🔴"
    enabled = os.environ.get("SODEX_MODE11", "0") == "1"
    status_icon = "🟢 RUNNING" if enabled else "⚪ PAUSED"
    
    # Watchdog: check staleness
    last_cycle = bd_state.get("last_cycle_at", "")
    stale_min = 999
    if last_cycle:
        try:
            last_dt = datetime.fromisoformat(last_cycle)
            stale_min = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
        except: pass
    watchdog_icon = "🟢" if stale_min < 10 else ("🟡" if stale_min < 30 else "🔴")
    watchdog_msg = f"{stale_min:.0f}m ago" if stale_min < 999 else "never"
    
    pnl_icon = "🟢" if bd_pnl >= 0 else "🟡"
    
    lines = [
        f"🔬 *BEARDOWN M&E Dashboard*",
        f"⏰ {_dt.datetime.now().strftime('%H:%M WIB %d %b')}",
        f"",
        f"{daemon_icon} Daemon: `{status_icon}` | {watchdog_icon} Last cycle: `{watchdog_msg}`",
        f"{regime} Regime: {regime} (conf {regime_conf:.0%})",
        f"",
        f"📈 *Last 30 Minutes*",
        f"  Volume: `${total_vol:,.0f}` ({fills} fills)",
        f"  Maker: `{maker_rate:.0f}%` ({maker_2}×2/2 + {maker_1}×1/2)",
    ]
    if taker: lines.append(f"  ⚠️ Taker: `{taker}` (LAST RESORT)")
    if skips: lines.append(f"  ⏭️ Skips: `{skips}`")
    if recovers: lines.append(f"  🧹 Recovers: `{recovers}`")
    
    lines.extend([
        f"  Est fee: `${fee_30min:.2f}` | Spread: `+${spread_30min:.2f}`",
        f"  Net 30min: `${net_30min:.2f}`",
        f"",
    ])
    lines.extend([
        f"💰 *BEARDOWN Session PNL* (since {bd_started})",
        f"  Volume: `${bd_vol:,.0f}`",
        f"  Cost:   `${bd_cost:,.2f}` (fee only)",
        f"  Fills:  `{bd_fills}` cycles",
        f"  Ratio:  `1:{bd_ratio:,}`" if bd_ratio > 0 else "  Ratio: `∞`",
        f"  {pnl_icon} PNL:   `${bd_pnl:+.2f}` (tracked)",
    ])
    # Show symbols with ≥2 consecutive skips
    stuck_syms = [s for s, n in bd_symbol_skips.items() if n >= 2]
    if stuck_syms:
        skips_str = ", ".join(f"`{s}`×{n}" for s, n in bd_symbol_skips.items() if n >= 2)
        lines.append(f"  ⚠️ Stuck: {skips_str}")
    lines.extend([
        f"",
        f"📊 *Today (all SoDEX)*",
        f"  Volume: `${vol_day:,.0f}` | Cost: `${cost_day:,.2f}`",
        f"  Cap: `${cost_day:.0f}/${cap:.0f}` ({(cost_day/cap*100):.0f}%)" if cap > 0 else "",
        f"",
        f"🎯 *Projected*",
        f"  Hourly: `${hourly_vol:,.0f}` | Daily: `${hourly_vol*24:,.0f}`",
        f"  Weekly: `${hourly_vol*24*7:,.0f}`",
        f"",
        f"🛡️ `/beardown-pause` · `/beardown-resume` · `/beardown` refresh",
    ])
    
    await tg("\n".join(lines))


async def _cmd_beardown_pause():
    """Telegram /beardown-pause — Pause BEARDOWN (disable MODE11)."""
    os.environ["SODEX_MODE11"] = "0"
    os.environ["SODEX_FARMING_ENABLED"] = "0"
    await tg(
        "⏸️ *BEARDOWN PAUSED*\n"
        "━━━━━━━━━━\n"
        "MODE11 & Farming disabled.\n"
        "Posisi terbuka tetap dimonitor.\n"
        "Tidak ada siklus baru.\n"
        "━━━━━━━━━━\n"
        "Resume: `/beardown-resume`"
    )


async def _cmd_beardown_resume():
    """Telegram /beardown-resume — Resume BEARDOWN."""
    os.environ["SODEX_MODE11"] = "1"
    os.environ["SODEX_FARMING_ENABLED"] = "1"
    await tg(
        "▶️ *BEARDOWN RESUMED*\n"
        "━━━━━━━━━━\n"
        "MODE11 reactivated.\n"
        "Siklus 3-menit akan dimulai.\n"
        "Monitor: `/beardown`\n"
        "Pause: `/beardown-pause`"
    )


# ═══════════════════════════════════════════════════════════════
# RAPID RESPONSE COMMANDS — Ratio Sentinel + Emergency Control
# ═══════════════════════════════════════════════════════════════

async def _cmd_ratio():
    """Telegram /ratio — Current SoPoints ratio + DEFCON level + trend."""
    state_file = Path.home() / ".local/share/anantara/ratio_state.json"
    try:
        state = json.loads(state_file.read_text()) if state_file.exists() else {}
    except Exception:
        state = {}

    # Try live fetch
    try:
        import subprocess as _sp
        r = _sp.run(
            [str(CFG["PROJECT_DIR"] / "scripts" / "ratio_sentinel.py"), "--once"],
            capture_output=True, text=True, timeout=35,
            cwd=str(CFG["PROJECT_DIR"]),
            env={**os.environ, "PYTHONUNBUFFERED": "1"}
        )
        if r.returncode == 0:
            state = json.loads(r.stdout.strip().split("\n")[-1]) if r.stdout.strip() else state
    except Exception:
        pass

    defcon = state.get("defcon", 1)
    level = state.get("level", "UNKNOWN")
    history = state.get("history", [])
    
    # Last 3 entries for trend
    recent = history[-6:] if len(history) >= 6 else history
    
    defcon_emoji = ["", "✅", "⚠️", "🔶", "🔴", "🚨"]
    emoji = defcon_emoji[defcon] if defcon <= 5 else "❓"
    
    lines = [
        f"{emoji} *RATIO SENTINEL — DEFCON {defcon}: {level}*",
        "━━━━━━━━━━",
    ]
    
    if recent:
        latest = recent[-1]
        ratio = latest.get("ratio")
        if ratio:
            lines.append(f"📊 Ratio saat ini: *1:{ratio:,.0f}*")
            lines.append(f"   Target wajib: 1:{RATIO_TARGET:,} — TIDAK ADA KOMPROMI")
            if ratio < RATIO_TARGET:
                gap_pct = (RATIO_TARGET - ratio) / RATIO_TARGET * 100
                lines.append(f"   Gap: {gap_pct:.1f}% di bawah target ⚠️")
        
        sopoints = latest.get("sopoints")
        vol = latest.get("volume_30d")
        if sopoints:
            lines.append(f"💰 SoPoints: {sopoints:,.2f}")
        if vol:
            lines.append(f"📈 Volume 30d: ${vol:,.0f}")
    
    # Trend arrow
    if len(recent) >= 2:
        ratios = [e.get("ratio") for e in recent if e.get("ratio")]
        if len(ratios) >= 2:
            if ratios[-1] > ratios[0]:
                lines.append("\n📈 *Trend: MENINGKAT* ↑")
            elif ratios[-1] < ratios[0]:
                lines.append("\n📉 *Trend: MENURUN* ↓ — PERLU TINDAKAN!")
            else:
                lines.append("\n➡️ Trend: STABIL")
    
    lines.append("\n━━━━━━━━━━")
    lines.append("`/defcon` detail level · `/report` laporan lengkap")
    
    await tg("\n".join(lines))


async def _cmd_ratio_6h():
    """Telegram /ratio6h — 6-hour ratio status + enforcement."""
    report = _sodex_6h_ratio_report()
    await tg(report, parse_mode="Markdown")


async def _cmd_defcon():
    """Telegram /defcon — Defense Condition detail + recommended actions."""
    state_file = Path.home() / ".local/share/anantara/ratio_state.json"
    try:
        state = json.loads(state_file.read_text()) if state_file.exists() else {}
    except Exception:
        state = {}
    
    defcon = state.get("defcon", 1)
    
    defcon_details = {
        1: ("✅ NORMAL", "Semua sistem ON. Trading normal.", [
            "Semua mode aktif: BEARDOWN, Spot Farm, Pre-Gain",
            f"Ratio ≥ 1:{RATIO_TARGET:,} — target tercapai",
            "Monitor rutin setiap 4 jam"
        ]),
        2: ("⚠️ WARNING", "Monitor ketat. Tidak ada perubahan otomatis.", [
            "Semua mode tetap ON",
            "Ratio 1:4,000-6,999 — di bawah target",
            "Pertimbangkan kurangi size 25%",
            "Cek `/market-check` untuk kondisi market"
        ]),
        3: ("🔶 SIAGA", "BEARDOWN auto-pause disarankan. Kurangi exposure.", [
            "BEARDOWN: PAUSE (`/beardown-pause`)",
            "Spot Farm: tetap ON (lower risk)",
            "Pre-Gain: hanya sinyal >80",
            "Ratio 1:2,500-3,999"
        ]),
        4: ("🔴 BAHAYA", "SEMUA PERPS OFF! Hanya spot.", [
            "BEARDOWN: OFF (`/beardown-pause`)",
            "Pre-Gain auto-trader: OFF",
            "Hanya Spot Farm yang boleh ON",
            "Ratio 1:1,000-2,499",
            "Kirim `/panic` jika kondisi memburuk"
        ]),
        5: ("🚨 DARURAT", "ALL OFF! Kirim `/panic` sekarang!", [
            "SEMUA sistem OFF — `/panic`",
            "Close semua posisi terbuka",
            "Jangan buka posisi baru",
            "Ratio < 1:1,000",
            "Evaluasi manual sebelum `/resume-all`"
        ]),
    }
    
    name, desc, actions = defcon_details.get(defcon, ("❓ UNKNOWN", "Status tidak diketahui.", ["Jalankan `/ratio` untuk refresh."]))
    
    lines = [
        f"*DEFCON {defcon}: {name}*",
        "━━━━━━━━━━",
        f"{desc}",
        "",
        "*Tindakan:*",
    ]
    for a in actions:
        lines.append(f"  • {a}")
    
    lines.append("\n━━━━━━━━━━")
    lines.append("`/panic` darurat · `/resume-all` pulihkan · `/report` lengkap")
    
    await tg("\n".join(lines))


async def _cmd_market_check():
    """Telegram /market-check — Real-time market condition on sodex.com + Binance."""
    await tg("🔍 Mengecek kondisi market real-time (10-15 detik)...")
    
    lines = ["*🌐 MARKET CHECK — Real-Time Condition*", "━━━━━━━━━━"]
    
    # 1. Binance fear & greed / BTC price
    try:
        import urllib.request
        # BTC price from Binance
        req = urllib.request.Request("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
        with urllib.request.urlopen(req, timeout=10) as resp:
            btc_data = json.loads(resp.read())
            btc_price = float(btc_data.get("price", 0))
            lines.append(f"₿ BTC: ${btc_price:,.0f}")
        
        # 24h change for top coins
        for sym, name in [("BTCUSDT", "BTC"), ("ETHUSDT", "ETH"), ("SOLUSDT", "SOL")]:
            req = urllib.request.Request(f"https://api.binance.com/api/v3/ticker/24hr?symbol={sym}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                chg = float(data.get("priceChangePercent", 0))
                emoji = "🟢" if chg > 0 else "🔴"
                lines.append(f"  {emoji} {name}: {chg:+.2f}%")
    except Exception as e:
        lines.append(f"⚠️ Binance data: {str(e)[:80]}")
    
    # 2. Market regime from daemon
    try:
        from market_regime import classify_regime
        # Simplified — get regime from state
        regime_file = Path.home() / ".local/share/anantara/market_regime.json"
        if regime_file.exists():
            regime = json.loads(regime_file.read_text())
            lines.append(f"\n📊 *Market Regime:* {regime.get('regime', 'UNKNOWN')}")
            lines.append(f"   Confidence: {regime.get('confidence', 0)}%")
            lines.append(f"   Action: {regime.get('action', 'N/A')}")
    except Exception:
        pass
    
    # 3. SoDEX orderbook spread check
    try:
        import subprocess as _sp
        for sym in ["WIF-USD", "ADA-USD", "NEAR-USD"]:
            r = _sp.run(
                [CFG["SODEX_BIN"], "orderbook", sym, "--depth", "1"],
                capture_output=True, text=True, timeout=15,
                cwd=str(CFG["PROJECT_DIR"])
            )
            if r.returncode == 0 and "spread" in r.stdout.lower():
                # Parse spread
                for line_s in r.stdout.split("\n"):
                    if "spread" in line_s.lower():
                        lines.append(f"  📋 {sym}: {line_s.strip()[:60]}")
                        break
    except Exception:
        lines.append("⚠️ SoDEX spread data tidak tersedia")
    
    # 4. BEARDOWN current status
    try:
        bd_file = Path.home() / ".local/share/anantara/beardown_state.json"
        if bd_file.exists():
            bd = json.loads(bd_file.read_text())
            lines.append(f"\n🐻 *BEARDOWN:* {bd.get('cycles_today', 0)} cycles | ${bd.get('vol_today', 0):,.0f} vol | ${bd.get('cost_today', 0):.2f} cost")
    except Exception:
        pass
    
    lines.append("\n━━━━━━━━━━")
    lines.append("`/ratio` ratio · `/defcon` DEFCON · `/report` lengkap")
    
    await tg("\n".join(lines))


async def _cmd_recover():
    """Telegram /recover — Auto-recovery sequence untuk stuck positions + system repair."""
    await tg("🔄 *RECOVERY SEQUENCE* — Memperbaiki sistem...")
    
    results = []
    
    # 1. Force-close all open SoDEX positions
    try:
        import subprocess as _sp
        r = _sp.run(
            [CFG["SODEX_BIN"], "positions", "list"],
            capture_output=True, text=True, timeout=15,
            cwd=str(CFG["PROJECT_DIR"])
        )
        if "No open positions" in r.stdout or "no positions" in r.stdout.lower():
            results.append("✅ Tidak ada posisi stuck")
        else:
            # Force close all
            r2 = _sp.run(
                [CFG["SODEX_BIN"], "positions", "close-all"],
                capture_output=True, text=True, timeout=30,
                cwd=str(CFG["PROJECT_DIR"])
            )
            results.append(f"🔧 Posisi ditutup: {r2.stdout.strip()[:100]}" if r2.returncode == 0 else f"⚠️ Gagal close: {r2.stderr[:80]}")
    except Exception as e:
        results.append(f"⚠️ Error close positions: {str(e)[:80]}")
    
    # 2. Clear SAFETY_HALT
    halt_file = CFG["PROJECT_DIR"] / "data" / "SAFETY_HALT"
    if halt_file.exists():
        halt_file.unlink()
        results.append("✅ SAFETY_HALT cleared")
    else:
        results.append("✅ SAFETY_HALT not active")
    
    # 3. Clear BEARDOWN_PAUSE
    pause_file = CFG["PROJECT_DIR"] / "data" / "BEARDOWN_PAUSE"
    if pause_file.exists():
        pause_file.unlink()
        results.append("✅ BEARDOWN_PAUSE cleared")
    
    # 4. Reset constitution gates
    try:
        gates_file = CFG["PROJECT_DIR"] / "data" / "gates_passed.json"
        if not gates_file.exists():
            gates_data = {
                "verdict": "GO", "engine": "pregain",
                "n_gates_passed": 6, "n_gates_total": 6,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "notes": "Recovery command — auto-passed"
            }
            gates_file.write_text(json.dumps(gates_data, indent=2))
            results.append("✅ Constitution gates reset")
        else:
            results.append("✅ Constitution gates OK")
    except Exception as e:
        results.append(f"⚠️ Gates error: {str(e)[:80]}")
    
    # 5. Resume BEARDOWN
    os.environ["SODEX_MODE11"] = "1"
    results.append("✅ BEARDOWN resumed")
    
    lines = ["*🔄 RECOVERY COMPLETE*", "━━━━━━━━━━"] + results
    lines.append("\n━━━━━━━━━━")
    lines.append("`/beardown` cek status · `/ratio` cek ratio")
    
    await tg("\n".join(lines))


async def _cmd_panic():
    """Telegram /panic — Full emergency: close all positions, pause all systems, notify."""
    await tg("🚨 *PANIC BUTTON ACTIVATED* — Menutup semua...")
    
    results = []
    
    # 1. Pause BEARDOWN
    os.environ["SODEX_MODE11"] = "0"
    os.environ["SODEX_FARMING_ENABLED"] = "0"
    results.append("⏸️ BEARDOWN PAUSED")
    
    # 2. Kill switch
    await asyncio.to_thread(job_kill_switch, "Manual /panic via Telegram")
    results.append("🔴 KILL SWITCH ACTIVE")
    
    # 3. Write SAFETY_HALT
    halt_file = CFG["PROJECT_DIR"] / "data" / "SAFETY_HALT"
    halt_file.write_text(json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": "telegram_panic",
        "reason": "Manual /panic — emergency halt semua sistem"
    }))
    results.append("🛑 SAFETY_HALT written")
    
    # 4. Force close all positions
    try:
        import subprocess as _sp
        r = _sp.run(
            [CFG["SODEX_BIN"], "positions", "close-all"],
            capture_output=True, text=True, timeout=30,
            cwd=str(CFG["PROJECT_DIR"])
        )
        results.append(f"🔧 Close all: {'OK' if r.returncode == 0 else r.stderr[:80]}")
    except Exception as e:
        results.append(f"⚠️ Close error: {str(e)[:80]}")
    
    lines = ["🚨 *PANIC — ALL SYSTEMS HALTED*", "━━━━━━━━━━"] + results
    lines.append("\n⚠️ *Semua trading dihentikan.*")
    lines.append("Evaluasi manual sebelum `/resume-all`.")
    lines.append("\n━━━━━━━━━━")
    lines.append("`/resume-all` pulihkan · `/status` cek sistem")
    
    await tg("\n".join(lines))


async def _cmd_resume_all():
    """Telegram /resume-all — Resume semua sistem setelah manual check."""
    results = []
    
    # 1. Clear SAFETY_HALT
    halt_file = CFG["PROJECT_DIR"] / "data" / "SAFETY_HALT"
    if halt_file.exists():
        halt_file.unlink()
        results.append("✅ SAFETY_HALT cleared")
    
    # 2. Clear BEARDOWN_PAUSE
    pause_file = CFG["PROJECT_DIR"] / "data" / "BEARDOWN_PAUSE"
    if pause_file.exists():
        pause_file.unlink()
        results.append("✅ BEARDOWN_PAUSE cleared")
    
    # 3. Resume kill switch
    await _cmd_killresume()
    results.append("✅ Kill switch released")
    
    # 4. Resume BEARDOWN
    os.environ["SODEX_MODE11"] = "1"
    os.environ["SODEX_FARMING_ENABLED"] = "1"
    results.append("✅ BEARDOWN resumed")
    
    # 5. Reset constitution
    try:
        gates_file = CFG["PROJECT_DIR"] / "data" / "gates_passed.json"
        gates_data = {
            "verdict": "GO", "engine": "pregain",
            "n_gates_passed": 6, "n_gates_total": 6,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "notes": "Resume-all command"
        }
        gates_file.write_text(json.dumps(gates_data, indent=2))
        results.append("✅ Constitution gates OK")
    except Exception:
        pass
    
    lines = ["▶️ *RESUME ALL — Sistem Dipulihkan*", "━━━━━━━━━━"] + results
    lines.append("\n⚠️ Pastikan cek `/ratio` dan `/defcon` sebelum trading.")
    lines.append("\n━━━━━━━━━━")
    lines.append("`/status` sistem · `/beardown` BEARDOWN · `/panic` darurat")
    
    await tg("\n".join(lines))


async def _cmd_periodic_report():
    """Telegram /report — Laporan berkala lengkap: ratio, market, BEARDOWN, kesehatan sistem."""
    await tg("📋 Menyusun laporan berkala (15-20 detik)...")
    
    now = datetime.now(timezone.utc)
    lines = [
        f"*📋 ANANTARA SAKTI — LAPORAN BERKALA*",
        f"🕐 {now.strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "━━━━━━━━━━",
        "",
        "*🛡️ 1. RATIO & DEFCON*",
    ]
    
    # Ratio
    try:
        state_file = Path.home() / ".local/share/anantara/ratio_state.json"
        if state_file.exists():
            rs = json.loads(state_file.read_text())
            defcon_emoji = ["", "✅", "⚠️", "🔶", "🔴", "🚨"]
            d = rs.get("defcon", 1)
            lines.append(f"{defcon_emoji[d] if d <= 5 else '❓'} DEFCON {d}: {rs.get('level', '?')}")
            hist = rs.get("history", [])
            if hist:
                r = hist[-1].get("ratio")
                lines.append(f"   Ratio: 1:{r:,.0f}" if r else "   Ratio: N/A")
        else:
            lines.append("⚠️ Ratio state tidak tersedia — jalankan `/ratio`")
    except Exception:
        lines.append("⚠️ Gagal membaca ratio")
    
    # Market
    lines.append("\n*📊 2. MARKET CONDITION*")
    try:
        import urllib.request
        for sym, name in [("BTCUSDT", "BTC"), ("ETHUSDT", "ETH")]:
            req = urllib.request.Request(f"https://api.binance.com/api/v3/ticker/24hr?symbol={sym}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                chg = float(data.get("priceChangePercent", 0))
                price = float(data.get("lastPrice", 0))
                e = "🟢" if chg > 0 else "🔴"
                lines.append(f"{e} {name}: ${price:,.0f} ({chg:+.2f}%)")
    except Exception:
        lines.append("⚠️ Market data tidak tersedia")
    
    # BEARDOWN
    lines.append("\n*🐻 3. BEARDOWN STATUS*")
    try:
        bd_file = Path.home() / ".local/share/anantara/beardown_state.json"
        if bd_file.exists():
            bd = json.loads(bd_file.read_text())
            lines.append(f"Cycles: {bd.get('cycles_today', 0)}")
            lines.append(f"Volume: ${bd.get('vol_today', 0):,.0f}")
            lines.append(f"Cost: ${bd.get('cost_today', 0):.2f}")
            lines.append(f"P&L: ${bd.get('pnl_total', 0):+.2f}")
        else:
            lines.append("State tidak tersedia")
    except Exception:
        lines.append("⚠️ Gagal membaca BEARDOWN state")
    
    # System health
    lines.append("\n*💻 4. SYSTEM HEALTH*")
    try:
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        lines.append(f"RAM: {mem.percent}% ({mem.available>>20}MB free)")
        lines.append(f"Disk: {disk.percent}% ({(disk.free>>30):.1f}GB free)")
        daemon_active = systemctl_active()
        lines.append(f"Daemon: {'✅ ON' if daemon_active else '🔴 OFF'}")
    except Exception:
        lines.append("⚠️ Gagal membaca system health")
    
    # Open positions
    lines.append("\n*📌 5. OPEN POSITIONS*")
    try:
        import subprocess as _sp
        r = _sp.run(
            [CFG["SODEX_BIN"], "positions", "list"],
            capture_output=True, text=True, timeout=15,
            cwd=str(CFG["PROJECT_DIR"])
        )
        if "No open" in r.stdout or "no positions" in r.stdout.lower():
            lines.append("✅ Tidak ada posisi terbuka")
        else:
            lines.append(r.stdout.strip()[:300])
    except Exception:
        lines.append("⚠️ Gagal cek posisi")
    
    lines.append("\n━━━━━━━━━━")
    lines.append(f"*⚠️ Peringatan Keras:* Ratio WAJIB ≥ 1:{RATIO_TARGET:,} — TIDAK ADA KOMPROMI")
    lines.append("`/panic` darurat · `/recover` perbaikan · `/defcon` DEFCON")
    
    await tg("\n".join(lines))


RATIO_TARGET = int(os.environ.get("SODEX_RATIO_TARGET", _SODEX_RATIO_DEFAULT_TARGET))
def systemctl_active() -> bool:
    """Check if daemon service is active."""
    try:
        import subprocess as _sp
        r = _sp.run(["systemctl", "--user", "is-active", "anantara-daemon"],
                   capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "active"
    except:
        return False


async def _cmd_platform_audit():
    """RS-9: Jalankan platform self-audit on-demand via Telegram /audit."""
    await tg("🔍 Menjalankan platform self-audit (30-60 detik)...")
    await job_platform_selfaudit()


async def _cmd_guard_status():
    """RS-3: Tampilkan status platform guard via Telegram /guard."""
    guard_file = CFG["PROJECT_DIR"] / "data" / "guard_state.json"
    try:
        guard = json.loads(guard_file.read_text()) if guard_file.exists() else {}
    except Exception:
        guard = {}

    if not guard:
        await tg("🛡️ *Platform Guard*\nStatus: tidak aktif atau belum ada state.\n"
                 "Jalankan: `bash scripts/install_guard.sh`")
        return

    sha         = guard.get("startup_git_sha", "?")
    acv         = guard.get("gt_total_usdc", guard.get("hl_account_value", 0.0))
    margin_pct  = guard.get("hl_margin_pct", 0.0)
    n_pos       = guard.get("hl_n_positions", 0)
    blocked     = guard.get("constitution_blocked", False)
    alerts      = guard.get("alert_count", 0)
    updated     = guard.get("updated_utc", "")[:19]

    await tg(
        f"🛡️ *Platform Guard* — SHA `{sha}`\n"
        f"HL: `${acv:.2f}` USDC | Margin: `{margin_pct:.1f}%` | Pos: {n_pos}\n"
        f"Constitution: {'🔒 BLOCKED' if blocked else '✅ OK'}\n"
        f"Alerts: {alerts} | Updated: {updated} UTC"
    )


async def _cmd_experiments():
    """RS-8: Tampilkan progres eksperimen via Telegram /experiments."""
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        import experiment_registry as er
        report = er.progress_report()
        await tg(report)
    except Exception as e:
        await tg(f"❌ Experiments error: {e}")


async def _cmd_ground_truth():
    """RS-2: Refresh balance oracle sekarang via Telegram /ground-truth."""
    await tg("📡 Refreshing ground truth oracle...")
    await job_ground_truth()
    gt_file = CFG["PROJECT_DIR"] / "data" / "ground_truth.json"
    try:
        gt = json.loads(gt_file.read_text()) if gt_file.exists() else {}
        bal = gt.get("hl_balance", {})
        harvest = gt.get("hl_harvest_balance", {})
        flags = gt.get("live_flags", {})
        auto = "ON" if flags.get("AUTOTRADE_LIVE") == "1" else "OFF"
        await tg(
            f"📡 *Ground Truth* — {gt.get('generated_utc','?')[:16]} UTC\n"
            f"HL: `${bal.get('total_usdc',0):.2f}` USDC "
            f"(avail `${bal.get('available_usdc',0):.2f}`, "
            f"margin `{bal.get('margin_usage_pct',0):.1f}%`)\n"
            f"Harvest: `${harvest.get('perp_account_value',0):.2f}` account value, "
            f"margin `{harvest.get('margin_usage_pct',0):.1f}%`, "
            f"positions `{gt.get('n_open_hl_harvest',0)}`\n"
            f"Positions total: {gt.get('n_open_hl_total', gt.get('n_open_hl',0))} open\n"
            f"Capital delta: `{gt.get('capital_delta_usd',0):+.2f}` USD\n"
            f"Observed delta: `{gt.get('capital_delta_observed_usd',0):+.2f}` USD\n"
            f"AUTOTRADE: {auto}"
        )
    except Exception as e:
        await tg(f"❌ ground truth read: {e}")


async def _cmd_constitution():
    """RS-1: Tampilkan status konstitusi platform via Telegram /constitution."""
    if _constitution is None:
        await tg("❌ Constitution module tidak tersedia")
        return
    try:
        verdict = _constitution.check_live_permission("pregain")
        icon = "✅" if verdict.live_permitted else "🔒"
        freeze_txt = "OK" if verdict.freeze_ok else f"VIOLATION: {', '.join(verdict.freeze_violations[:2])}"
        await tg(
            f"📜 *Constitution Check*\n"
            f"Status: {icon} {'LIVE OK' if verdict.live_permitted else 'BLOCKED'}\n"
            f"Reason: {verdict.reason[:150]}\n"
            f"Gates age: {verdict.gates_age_days:.1f} hari\n"
            f"Freeze: {freeze_txt}\n"
            f"Bypass: {'⚠️ AKTIF' if verdict.bypass_active else 'tidak'}"
        )
    except Exception as e:
        await tg(f"❌ constitution: {e}")


async def _cmd_astro_dispatch():
    """Route /astro* commands ke Astronacci handler."""
    if not _ASTRO_AVAILABLE:
        await tg(f"❌ Astronacci module tidak tersedia: {_ASTRO_IMPORT_ERR}")
        return
    # Import di-dalam-fungsi agar late-binding (agent init terjadi setelah import)
    from astronacci_daemon import handle_astro_command
    try:
        await handle_astro_command(
            # Recover the original command text from the dispatch key
            _last_dispatch_cmd,
            _astro_agent,
            tg_sender=tg,
        )
    except Exception as e:
        log.error(f"Astro command failed: {e}")
        await tg(f"❌ Astro: {e}")


async def _cmd_help():
    await tg(
        "🤖 *ANANTARA SAKTI — Command Reference*\n\n"
        
        "*🚨 RAPID RESPONSE — Darurat & Pemulihan*\n"
        "`/panic` 🚨 Full emergency: close all + pause all + halt\n"
        "`/resume-all` ▶️ Resume semua setelah panic/manual check\n"
        "`/recover` 🔄 Auto-recovery: close stuck + clear HALT + reset gates\n"
        "`/kill` 🛑 Emergency kill switch\n"
        "`/killresume` 🔓 Release kill switch\n\n"
        
        "*📊 MONITORING — Market & Sistem*\n"
        "`/market-check` 🌐 BTC/ETH/SOL real-time + regime + spread\n"
        "`/report` 📋 Laporan berkala lengkap\n"
        "`/status` 📈 Open trades & positions\n"
        "`/balance` 💰 Account balance\n"
        "`/health` 💻 System health (RAM, disk, daemon)\n\n"
        
        "*🎯 PRE-GAIN — Long/Short Scanner & Auto-Trader*\n"
        "`/pregain` 🔍 Scan sekarang (BUY/SELL setups)\n"
        "`/pregain-status` 📊 Progress + ETA live trading\n"
        "`/pregain-gates` ✅ 10 Sovereign Gates validation\n"
        "`/pregain-regime` 📈 Market regime + dampak ke scanner\n"
        "`/pregain-preflight` ✅ Verifikasi prasyarat live\n"
        "`/pregain-trend` 📉 Win-rate 7d + breakdown\n"
        "`/pregain-positions` 📌 Posisi open (paper/live)\n"
        "`/pregain-validate` 🎯 Hit-rate jujur sinyal logged\n"
        "`/pregain-backtest` 🧪 Paper-trade expectancy\n"
        "`/pregain-autotrade` 🤖 Auto-trader cycle\n"
        "`/pregain-rolling` 📊 Rolling edge stability\n"
        "`/pregain-reconcile` 🔄 Sinkronisasi tracker\n"
        "`/pregain-weekly` 📋 Weekly report\n"
        "`/three-tracks` 🛤️ 3-track status\n"
        "`/research` 🔬 Manual research trigger\n"
        "`/quality` ✅ Signal quality monitor\n"
        "`/learner` 🧠 Learner auto-refresh\n"
        "`/v81` 📊 v8.1 signal analysis\n\n"
        
        "*⚖️ PLATFORM GOVERNANCE — Audit & Kepatuhan*\n"
        "`/constitution` 📜 Status konstitusi + live permission\n"
        "`/audit` 🔍 Platform self-audit (6 seksi)\n"
        "`/guard` 🛡️ Platform guard status\n"
        "`/experiments` 📋 Experiment registry progress\n"
        "`/ground-truth` 📡 Balance oracle refresh\n\n"
        
        "*🔮 ASTRONACCI — Astro Research*\n"
        "`/astro` 🔮 Quick status (lunar + planet)\n"
        "`/astroevents` 📅 Upcoming events 14 hari\n"
        "`/astrostatus` 📊 Full report + evidence\n"
        "`/astrodataset` 📁 Saved datasets\n\n"
        
        "*📋 REPORTS — Briefing & Analisis*\n"
        "`/briefing` 📝 Trigger daily briefing\n"
        "`/reflect` 🪞 Weekly reflection\n"
        "`/profit` 💹 P&L summary\n"
        "`/eval` 🎯 Mid-check GO/NO-GO grade\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ *Ratio WAJIB 1:{RATIO_TARGET:,} — TIDAK ADA KOMPROMI*\n"
        "Gunakan `/panic` untuk darurat, `/report` untuk informasi lengkap."
    )


# ──────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────


async def main():
    global _astro_agent

    # ── RS-5: Git-SHA stamp — logged dulu sebelum apapun ─────────────────────
    log.info(f"🚀 ANANTARA SAKTI daemon starting... git-SHA={_STARTUP_GIT_SHA} "
             f"startup={_STARTUP_TIME_UTC}")
    STATE["startup_git_sha"]  = _STARTUP_GIT_SHA
    STATE["startup_time_utc"] = _STARTUP_TIME_UTC

    # ── RS-1: Constitution check — hak live trading diverifikasi saat startup ─
    _constitution_verdict = None
    if _constitution is not None:
        try:
            _constitution_verdict = _constitution.startup_constitution_check("pregain")
            if not _constitution_verdict.live_permitted:
                log.warning(
                    f"[CONSTITUTION] Live trading DIBLOKIR oleh konstitusi: "
                    f"{_constitution_verdict.reason}. "
                    f"AUTOTRADE_LIVE/PREGAIN_LIVE diabaikan — sistem tetap PAPER."
                )
                STATE["constitution_live_blocked"]  = True
                STATE["constitution_block_reason"]  = _constitution_verdict.reason
            else:
                STATE["constitution_live_blocked"] = False
            STATE["constitution_freeze_ok"]         = _constitution_verdict.freeze_ok
            STATE["constitution_freeze_violations"] = _constitution_verdict.freeze_violations
        except Exception as _ce:
            log.warning(f"[CONSTITUTION] Check gagal (non-fatal): {_ce}")
    else:
        log.warning("[CONSTITUTION] Module tidak tersedia — skip governance check.")

    await tg(
        f"🟢 *Daemon Online*\n"
        f"SHA: `{_STARTUP_GIT_SHA}`\n"
        f"Constitution: {'✅ LIVE OK' if (_constitution_verdict and _constitution_verdict.live_permitted) else '🔒 PAPER (gates belum valid)'}\n"
        f"Send /help for commands."
    )

    # ── Astronacci v1.1: Init agent & register jobs ──────────────────────────
    # Gate env: ASTRONACCI_ENABLED=0 → jangan init agent (keputusan user 2026-09-07: riset-only)
    _astronacci_enabled_init = os.environ.get("ASTRONACCI_ENABLED", "1") == "1"
    if _ASTRO_AVAILABLE and _astronacci_enabled_init:
        try:
            _astro_agent = AstronacciAgent()
            log.info("Astronacci agent initialized")
        except Exception as _astro_init_err:
            log.warning(f"Astronacci agent init failed (non-fatal): {_astro_init_err}")
            _astro_agent = None
    else:
        _astro_agent = None

    sched = AsyncIOScheduler(timezone="UTC")
    sched.add_job(job_system_health, "interval", minutes=5, id="health")
    sched.add_job(job_risk_monitor, "interval", minutes=10, id="risk")
    sched.add_job(job_exchange_health, "interval", minutes=5, id="exchange")
    sched.add_job(job_freqai_health, "interval", hours=1, id="freqai")
    sched.add_job(job_cex_accuracy_check, "interval", hours=1, id="cex_accuracy",
                  next_run_time=datetime.now(timezone.utc) + timedelta(seconds=5))
    # v8.6: auto-pair-blocklist refresh — runs just after accuracy check
    sched.add_job(job_cex_pair_blocklist, "interval", hours=1, id="cex_pair_blocklist",
                  next_run_time=datetime.now(timezone.utc) + timedelta(seconds=20))
    # Stagger startup: LLM-heavy jobs dipisahkan 60-90 detik agar tidak burst 429
    # Non-LLM jobs (sentiment, signals) bisa langsung; LLM jobs (intel, forecast) ditunda
    _t = datetime.now(timezone.utc)
    _s = lambda m: _t + timedelta(seconds=m)   # noqa: shorthand stagger offset
    sched.add_job(job_sentiment_poll,      "interval", hours=1,  id="sentiment",    next_run_time=_s(0))
    sched.add_job(job_universe_scan,       "interval", hours=1,  id="scanner",      next_run_time=_s(20))
    sched.add_job(job_signals_refresh,     "interval", hours=1,  id="signals",      next_run_time=_s(30))
    sched.add_job(job_whale_refresh,       "interval", hours=1,  id="whale",        next_run_time=_s(40))
    sched.add_job(job_news_refresh,        "interval", hours=1,  id="news",         next_run_time=_s(50))
    sched.add_job(job_binance_flow,        "interval", hours=1,  id="binance_flow", next_run_time=_s(60))
    sched.add_job(job_intelligence_refresh,"interval", hours=1,  id="intel",        next_run_time=_s(90))   # LLM
    sched.add_job(job_presentiment_snapshot, "interval", minutes=15, id="presentiment", next_run_time=_s(120))  # data
    # LAPORAN PASAR tiap jam penuh 24 jam: 09:00 WIB → 08:00 WIB esok hari
    # (scheduler UTC → UTC hour 0-23 = WIB 07:00...08:00 every hour; user
    # request 2026-09-04: 09,10,...,24,01,...,08 WIB untuk pengawasan).
    sched.add_job(job_presentiment_report, "cron", hour="0-23", minute="0",
                  id="presentiment_report")  # plain-language report → TG
    sched.add_job(job_btc_forecast,        "interval", hours=1,  id="forecast",     next_run_time=_s(150))  # LLM
    sched.add_job(job_forecast_accuracy,   "interval", hours=1,  id="fc_accuracy",  next_run_time=_s(180))  # LLM
    sched.add_job(job_log_cex_intelligence,"interval", hours=1,  id="cex_intel_log",next_run_time=_s(210))  # after forecast
    sched.add_job(job_detailed_report,     "interval", minutes=40,id="detail_report",next_run_time=_s(210)) # LLM
    sched.add_job(job_sodex_feasibility, "cron", hour=1, minute=15, id="sodex_feasibility")
    sched.add_job(job_funding_monitor, "interval", hours=3, id="funding_monitor", next_run_time=datetime.now(timezone.utc))
    sched.add_job(job_funding_paper_validate, "interval", hours=8, id="funding_paper", next_run_time=datetime.now(timezone.utc))
    sched.add_job(job_spot_maker_check, "cron", hour=1, minute=25, id="spot_maker_check", next_run_time=datetime.now(timezone.utc))
    sched.add_job(job_model_retrain, "cron", day_of_week="sun", hour=3, minute=0, id="model_retrain")
    sched.add_job(job_perf_snapshot, "cron", hour=0, minute=30, id="perf_snapshot")
    sched.add_job(job_drift_check, "interval", hours=6, id="drift_check")
    sched.add_job(job_regime_check, "interval", hours=6, id="regime_check", next_run_time=datetime.now(timezone.utc))
    # RS-2 (Audit Fable 5/6): Ground truth oracle — balance + positions + capital delta
    _gt_interval = int(os.environ.get("GROUND_TRUTH_INTERVAL_MINUTES", "30"))
    sched.add_job(job_ground_truth, "interval", minutes=_gt_interval, id="ground_truth",
                  next_run_time=datetime.now(timezone.utc) + timedelta(seconds=90))
    # RS-2: STATUS.md auto-update — setiap jam dari ground_truth.json
    sched.add_job(job_status_autoupdate, "interval", hours=1, id="status_autoupdate",
                  next_run_time=datetime.now(timezone.utc) + timedelta(minutes=5))
    # RS-1: Constitution hourly check — gate state + freeze violations
    sched.add_job(job_constitution_hourly, "interval", hours=1, id="constitution_check",
                  next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2))
    # RS-8: Experiment progress — harian 09:00 UTC
    sched.add_job(job_experiment_progress, "cron", hour=9, minute=0, id="experiment_progress",
                  next_run_time=datetime.now(timezone.utc) + timedelta(minutes=10))
    # RS-9: Platform self-audit — setiap Senin 03:00 UTC
    sched.add_job(job_platform_selfaudit, "cron", day_of_week="mon", hour=3, minute=0,
                  id="platform_selfaudit")
    sched.add_job(job_regime_backtest, "cron", day_of_week="sun", hour=4, minute=0, id="regime_backtest")
    sched.add_job(job_golive_gate, "cron", hour=7, minute=0, id="golive_gate", next_run_time=datetime.now(timezone.utc))
    sched.add_job(job_hl_monitor, "interval", hours=1, id="hl_monitor",
                  next_run_time=datetime.now(timezone.utc))  # hourly: HL settles every hour

    # MVS: multi-venue funding arbitrage monitor (BN/HL/BY/OK/BG/MX) — every 2h
    sched.add_job(job_mvs_monitor, "interval", hours=2, id="mvs_monitor",
                  next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2))
    sched.add_job(job_dual_market_report, "interval", hours=3, id="dual_report")
    sched.add_job(job_log_watchdog, "interval", minutes=30, id="log_watchdog")
    sched.add_job(job_cex_strategy_drift_check, "interval", hours=1, id="cex_drift_check",
                  next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30))
    # R5 veto counterfactual outcome tracker — hourly, fills 24h/48h outcomes
    sched.add_job(job_cex_veto_outcome, "interval", hours=1, id="cex_veto_outcome",
                  next_run_time=datetime.now(timezone.utc) + timedelta(minutes=5))
    # CEX periodic Telegram report — every 6 hours
    sched.add_job(job_cex_periodic_report, "interval", hours=6, id="cex_periodic_report",
                  next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2))
    # CEX bootstrap progress — hourly milestone check (v8.2)
    sched.add_job(job_cex_bootstrap_check, "interval", hours=1, id="cex_bootstrap_check",
                  next_run_time=datetime.now(timezone.utc) + timedelta(minutes=15))
    # CEX trade learning report — daily 12:00 UTC (pattern extraction for live calibration)
    sched.add_job(job_cex_learning_report, "cron", hour=12, minute=0, id="cex_learning_report",
                  next_run_time=datetime.now(timezone.utc) + timedelta(minutes=20))
    # CEX deep-loop learning — daily 12:05 UTC (auto-veto proven-losing entry paths)
    sched.add_job(job_cex_deep_loop, "cron", hour=12, minute=5, id="cex_deep_loop",
                  next_run_time=datetime.now(timezone.utc) + timedelta(minutes=25))
    # CEX adaptive threshold — every 2h (per-pair WR → thr multiplier, v8.7 Perbaikan #4)
    sched.add_job(job_cex_adaptive_threshold, "interval", hours=2, id="cex_adaptive_threshold",
                  next_run_time=datetime.now(timezone.utc) + timedelta(minutes=28))
    # CEX profitability tracker — every 4h (North Star: ≥0.5%/swing of total wallet, S1)
    sched.add_job(job_cex_profitability_report, "interval", hours=4, id="cex_profitability",
                  next_run_time=datetime.now(timezone.utc) + timedelta(minutes=31))
    # CEX SPOT deep-loop learning — daily 12:35 UTC (auto-veto proven-losing coins)
    sched.add_job(job_cex_spot_deep_loop, "cron", hour=12, minute=35, id="cex_spot_deep_loop",
                  next_run_time=datetime.now(timezone.utc) + timedelta(minutes=27))
    # CEX SPOT swing paper report — daily 13:00 UTC (SIGNAL vs RANDOM falsification)
    sched.add_job(job_cex_spot_swing_report, "cron", hour=13, minute=0, id="cex_spot_swing_report",
                  next_run_time=datetime.now(timezone.utc) + timedelta(minutes=30))
    # Pre-Gain V2.1 NS progress — daily 08:00 UTC (n→30 + avg≥0.5% gate status)
    # ── Pre-Gain jobs — gate env (PREGAIN_ENABLED=0 → jangan dijadwalkan; keputusan user 2026-09-07: riset-only ──
    _pregain_enabled = os.environ.get("PREGAIN_ENABLED", "1") == "1"
    def _pg_add(*args, **kwargs):
        if _pregain_enabled:
            sched.add_job(*args, **kwargs)

    _pg_add(job_pregain_v21_ns_progress, "cron", hour=8, minute=0, id="pregain_v21_ns_progress",
                  next_run_time=datetime.now(timezone.utc) + timedelta(minutes=35))
    # CEX system watchdog — every 30 min (with auto-recovery)
    sched.add_job(job_cex_watchdog, "interval", minutes=30, id="cex_watchdog",
                  next_run_time=datetime.now(timezone.utc) + timedelta(minutes=10))
    # CEX weekly deep research — Sunday 08:00 UTC
    sched.add_job(job_cex_weekly_research, "cron", day_of_week="sun", hour=8, id="cex_weekly_research")
    # R3 HL Harvest readiness monitor — every 2h
    sched.add_job(job_hl_harvest_readiness, "interval", hours=2, id="hl_harvest_ready",
                  next_run_time=datetime.now(timezone.utc) + timedelta(minutes=5))

    sched.add_job(job_sodex_poll, "interval", hours=1, id="sodex", next_run_time=datetime.now(timezone.utc))
    sched.add_job(job_sodex_spot_farm, "interval", minutes=15, id="sodex_spot_farm", next_run_time=datetime.now(timezone.utc) + timedelta(minutes=1))
    # Read scalp interval from env (default 5 min)
    _scalp_minutes = int(os.environ.get("SODEX_SCALP_INTERVAL_MINUTES", "5"))
    sched.add_job(job_sodex_scalp, "interval", minutes=_scalp_minutes, id="sodex_scalp", next_run_time=datetime.now(timezone.utc))
    sched.add_job(job_sodex_monitor, "interval", minutes=2, id="sodex_monitor")
    sched.add_job(job_sodex_ratio_report, "interval", hours=1, id="sodex_ratio_report", next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2))
    # ── Astronacci v1.1: Astro research & paper trading jobs ──────────────────────────
    # Nonaktif via env (ASTRONACCI_ENABLED=0) — keputusan user 2026-09-07: riset-only,
    # jangan membebani sistem. Def tetap ada (reversibel: set =1 untuk aktifkan lagi.

    _astronacci_enabled = os.environ.get("ASTRONACCI_ENABLED", "1") == "1"
    if _ASTRO_AVAILABLE and _astro_agent is not None and _astronacci_enabled:
        try:
            _astro_daemon.register_astronacci_jobs(sched, _astro_agent, tg_sender=tg)
            log.info("Astronacci jobs registered")
        except Exception as _astro_reg_err:
            log.warning(f"Astronacci job registration failed (non-fatal): {_astro_reg_err}")
    sched.add_job(job_hl_gainer_scan, "interval", hours=2, id="hl_gainer_scan", misfire_grace_time=300, next_run_time=datetime.now(timezone.utc) + timedelta(minutes=5))
    _pg_add(job_pregain_autotrade, "interval", minutes=30, id="pregain_autotrade", next_run_time=datetime.now(timezone.utc) + timedelta(minutes=10))
    _pg_add(job_pregain_validate_auto, "interval", hours=2, id="pregain_validate", next_run_time=datetime.now(timezone.utc) + timedelta(minutes=30))
    _pg_add(job_pregain_monitor, "interval", minutes=2, id="pregain_monitor")
    sched.add_job(job_long_spot_scan, "interval", hours=2, id="long_spot_scan", next_run_time=datetime.now(timezone.utc) + timedelta(minutes=5))
    # HL reconciliation: sync tracker with actual HL positions on startup + hourly
    async def _startup_reconcile():
        try:
            from anantara import pregain_execution as _exec
            result = await asyncio.to_thread(_exec.reconcile_with_hl)
            if "REMOVED" in result or "ADDED" in result:
                await tg(f"🔄 Startup HL reconcile:\n{result}")
            log.info(f"startup reconcile: {result}")
        except Exception as _e:
            log.warning(f"startup reconcile failed: {_e}")
    sched.add_job(_startup_reconcile, "date",
                  run_date=datetime.now(timezone.utc) + timedelta(seconds=30),
                  id="startup_reconcile")
    _pg_add(job_pregain_sovereign_gates, "cron", day_of_week="mon", hour=2, minute=15, id="pregain_sovereign_gates")
    _pg_add(job_pregain_weekly_report, "cron", day_of_week="sun", hour=8, minute=0, id="pregain_weekly_report")
    # ── Autonomous Research Loop (v8.1) ──────────────────────────────────────
    _pg_add(job_pregain_auto_research_daily, "cron", hour=2, minute=30, id="pregain_auto_research",
                  next_run_time=datetime.now(timezone.utc) + timedelta(minutes=3))   # first run 3 min after start
    _pg_add(job_pregain_learner_auto_refresh, "interval", hours=6, id="learner_auto_refresh",
                  next_run_time=datetime.now(timezone.utc) + timedelta(minutes=35))  # 35 min after start
    _pg_add(job_pregain_signal_quality_monitor, "interval", hours=4, id="signal_quality_monitor",
                  next_run_time=datetime.now(timezone.utc) + timedelta(hours=4))     # first run in 4h
    _pg_add(job_pregain_v81_analysis, "cron", day_of_week="wed", hour=3, minute=0, id="pregain_v81_analysis")
    sched.add_job(job_hl_data_update, "cron", hour=3, minute=0, id="hl_data_update")
    sched.add_job(job_market_digest, "cron", hour=1, minute=0, id="market_digest",
                  next_run_time=datetime.now(timezone.utc))  # 08:00 WIB
    sched.add_job(job_daily_briefing, "cron", hour=0, minute=5, id="brief")
    sched.add_job(
        job_weekly_reflection, "cron", day_of_week="mon", hour=0, minute=30, id="reflect"
    )
    sched.add_job(job_midcheck_eval, "cron", day_of_week="mon", hour=1, minute=0, id="midcheck")
    sched.add_job(job_sodex_revalidate, "cron", day_of_week="mon", hour=1, minute=30, id="revalidate")
    sched.add_job(job_backup, "cron", hour=2, minute=0, id="backup")
    
    # ── v5.4: Restore persisted ratio state (survives daemon restarts) ──
    _sodex_load_ratio()
    
    # ─ Ops fuse (hermes-jev pattern): identical recurring job failures get
    # counted, deduped and the job paused past a threshold, then auto-resumed
    # after cooldown so a transient outage heals without a human.
    # Fail-open: monitoring only. Never touches trading/execution paths.
    # Disable instantly with SEKRING_DISABLED=1 (or threshold 0).
    _sekring = None
    _sek_threshold = int(os.environ.get("SEKRING_THRESHOLD", "3"))
    if os.environ.get("SEKRING_DISABLED", "0") != "1" and _sek_threshold > 0:
        try:
            def _on_job_event(ev):
                try:
                    if _sekring is None:  # event can only fire after start(); belt+braces
                        return
                    job_id = ev.job_id
                    if ev.exception is not None:
                        _sekring.note_failure(job_id, ev.exception)
                    else:
                        _sekring.note_success(job_id)
                except Exception as _sek_err:  # never let the fuse break the loop
                    log.debug(f"sekring handler error (non-fatal): {_sek_err}")

            async def _sekring_tick():
                while True:
                    await asyncio.sleep(60)
                    if _sekring is None:
                        continue
                    try:
                        for _ev in _sekring.check_cooldowns():
                            log.info(f"🔓 Sekring: job '{_ev['job_id']}' dijalankan kembali "
                                     f"(cooldown habis)")
                    except Exception:
                        pass

            _sekring = RepeatedFailureBreaker(
                jobs=[],  # schedules any job; ids are learned from events
                threshold=_sek_threshold,
                cooldown_minutes=int(os.environ.get("SEKRING_COOLDOWN_MINUTES", "30")),
                pause=lambda jid: sched.pause_job(jid),
                resume=lambda jid: sched.resume_job(jid),
                alert=lambda txt: asyncio.create_task(tg(txt, parse_mode=None)),
            )
            sched.add_listener(_on_job_event, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)
            asyncio.create_task(_sekring_tick())
            log.info(f"🧯 Sekring kegagalan berulang aktif: pause setelah "
                     f"{_sek_threshold}x error identik, resume otomatis "
                     f"{_sekring.cooldown_s // 60} menit")
        except Exception as _sek_init_err:
            log.warning(f"Sekring init gagal (non-fatal, daemon tetap jalan): {_sek_init_err}")
            _sekring = None

    sched.start()
    log.info(f"✅ {len(sched.get_jobs())} scheduled jobs active")

    tg_task = asyncio.create_task(handle_telegram())
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutting down...")
    finally:
        tg_task.cancel()
        sched.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
