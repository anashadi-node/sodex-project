#!/usr/bin/env python3
"""Honest Rasio Real gate for bounded PVE farming.

The built-in guardian ratio uses cost = -sum(rt_net_pnl), which OVER-STATES the
ratio ~16x (reads 70,524 when the honest ratio is ~4,370) because it ignores
fees, funding, adverse selection, and open-position mark-to-market. This gate
uses the ONLY honest cost: the drop in the perps account value (`av`) since the
experiment baseline. That isolates true PVE cost.

    honest_ratio_24h = pve_volume_in_window / max(0, av_window_start - av_now)

Enforcement uses fixed 24-hour windows, not an order-by-order floor. If the
completed window ratio is below FLOOR after at least MIN_VOL, write
data/PVE_PAUSE (+ restart signal) so PVE stays close-only/recovery-only.
An honest-ratio-owned pause is released only after the ratio recovers with
configured headroom; pauses from other safety systems are never removed here.
Capital is independently hard-capped by the engine's TE_LOSS_CAP_USD guard; this
gate is the *quality* bound (pause when volume is not efficient enough).

READ-ONLY w.r.t. the exchange (no orders). Only local control files are written.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

TE_DB = PROJECT / "twin_engine.db"
STATE_FILE = PROJECT / "data" / "honest_ratio_experiment.json"
STATUS_FILE = PROJECT / "data" / "honest_ratio_status.json"
HISTORY_FILE = PROJECT / "data" / "honest_ratio_24h_history.jsonl"
PVE_PAUSE_FILE = PROJECT / "data" / "PVE_PAUSE"
RESTART_SIGNAL = PROJECT / "data" / "GUARDIAN_RESTART_SIGNAL"

def _env_float(name: str, default: str) -> float:
    """Parse numeric EnvironmentFile values, including systemd inline comments."""
    raw = os.environ.get(name)
    if raw is None:
        try:
            for line in (PROJECT / ".env").read_text().splitlines():
                if line.lstrip().startswith(f"{name}="):
                    raw = line.split("=", 1)[1]
                    break
        except OSError:
            pass
    raw = default if raw is None else raw
    value = raw.split("#", 1)[0].strip()
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric, got {raw!r}") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be > 0, got {parsed}")
    return parsed


DEFAULT_FLOOR = _env_float("HONEST_RATIO_FLOOR", "6500")
DEFAULT_MIN_VOL = _env_float("HONEST_RATIO_MIN_VOL", "2000")
DEFAULT_RESUME_HEADROOM = max(
    1.0, _env_float("HONEST_RATIO_RESUME_HEADROOM", "1.05")
)
DEFAULT_WINDOW_HOURS = _env_float("HONEST_RATIO_WINDOW_HOURS", "24")


def _normalize_systemd_environment() -> None:
    """Match shell `.env` inline-comment semantics before importing the engine."""
    prefixes = ("TE_", "PVE_", "ADAPT_", "HONEST_", "GUARDIAN_")
    for key, value in list(os.environ.items()):
        if key.startswith(prefixes) and "#" in value:
            os.environ[key] = value.split("#", 1)[0].rstrip()


def evaluate_ratio(av_start: float, av_now: float | None, vol: float,
                   floor: float, min_vol: float) -> dict:
    """Pure honest-ratio evaluation. cost = perps av drop (>=0)."""
    if av_now is None:
        return {
            "vol": round(vol, 2),
            "cost": None,
            "ratio": None,
            "floor": floor,
            "min_vol": min_vol,
            "vol_gate_met": vol >= min_vol,
            "evaluable": False,
            "breached": False,
        }
    cost = max(0.0, av_start - av_now)
    ratio = (vol / cost) if cost > 1e-9 else float("inf")
    breached = (vol >= min_vol) and (cost > 1e-9) and (ratio < floor)
    return {
        "vol": round(vol, 2),
        "cost": round(cost, 4),
        "ratio": (round(ratio, 1) if ratio != float("inf") else None),
        "floor": floor,
        "min_vol": min_vol,
        "vol_gate_met": vol >= min_vol,
        "evaluable": True,
        "breached": breached,
    }


def _perps_av_now() -> float | None:
    """Live perps account value (av) via SoDEX API — the honest cost anchor."""
    try:
        _normalize_systemd_environment()
        import anantara.sodex_twin_engine as te
        cfg = te.Config()
        c = te.SodexLiveAdapter(cfg)
        addr = (c._env.get("SODEX_ADDRESS") or "").strip()
        if not addr:
            return None
        ps = c._api_get(f"/perps/accounts/{addr}/state")
        data = ps.get("data", ps) if isinstance(ps, dict) else {}
        av = data.get("av")
        return float(av) if av is not None else None
    except Exception:
        return None


def _pve_cum_volume(since_ts_iso: str | None = None) -> float:
    """Cumulative PVE round-trip volume from the ledger (optionally since ts)."""
    if not TE_DB.exists():
        return 0.0
    try:
        con = sqlite3.connect(f"file:{TE_DB}?mode=ro", uri=True, timeout=5)
        if since_ts_iso:
            row = con.execute(
                "SELECT COALESCE(SUM(CAST(volume AS REAL)),0) FROM rts "
                "WHERE engine='PVE' AND ts_close>=?", (since_ts_iso,)).fetchone()
        else:
            row = con.execute(
                "SELECT COALESCE(SUM(CAST(volume AS REAL)),0) FROM rts "
                "WHERE engine='PVE'").fetchone()
        con.close()
        return float(row[0] or 0.0)
    except Exception:
        return 0.0


def _pve_rt_stats(since_ts_iso: str) -> dict:
    """RT count + net pnl + fees since baseline (for honest reporting)."""
    if not TE_DB.exists():
        return {"n_rt": 0, "rt_net": 0.0, "fees": 0.0, "n_fill": 0}
    try:
        con = sqlite3.connect(f"file:{TE_DB}?mode=ro", uri=True, timeout=5)
        n_rt, rt_net = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(CAST(net_pnl AS REAL)),0) FROM rts "
            "WHERE engine='PVE' AND ts_close>=?", (since_ts_iso,)).fetchone()
        n_fill, fees = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(CAST(fee AS REAL)),0) FROM fills "
            "WHERE engine='PVE' AND ts>=?", (since_ts_iso,)).fetchone()
        con.close()
        return {"n_rt": int(n_rt or 0), "rt_net": float(rt_net or 0.0),
                "fees": float(fees or 0.0), "n_fill": int(n_fill or 0)}
    except Exception:
        return {"n_rt": 0, "rt_net": 0.0, "fees": 0.0, "n_fill": 0}


def _tg_send(msg: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return False
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception:
        return False


def load_state() -> dict | None:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return None


def init_experiment(floor: float, min_vol: float,
                    window_hours: float = DEFAULT_WINDOW_HOURS) -> dict:
    """Capture the account-value baseline for a new fixed evaluation window."""
    av = _perps_av_now()
    if av is None:
        raise RuntimeError("cannot read perps av to set baseline")
    ts = datetime.now(timezone.utc).isoformat()
    state = {
        "ts_start": ts,
        "av_start": av,
        "vol_start": _pve_cum_volume(),
        "floor": floor,
        "min_vol": min_vol,
        "ratio_policy": "fixed_24h_window",
        "window_hours": window_hours,
        "capital_usd": 30.0,
        "loss_cap_usd": float(os.environ.get("TE_LOSS_CAP_USD", "4")),
    }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))
    return state


def compute_status() -> dict | None:
    """Current honest metrics for the active fixed window."""
    st = load_state()
    if not st:
        return None
    av_now = _perps_av_now()
    vol_now = _pve_cum_volume(st["ts_start"])
    rt = _pve_rt_stats(st["ts_start"])
    # Never let an old experiment baseline silently weaken a newer operator floor.
    floor = max(float(st.get("floor", DEFAULT_FLOOR)), DEFAULT_FLOOR)
    min_vol = max(float(st.get("min_vol", DEFAULT_MIN_VOL)), DEFAULT_MIN_VOL)
    elapsed_min = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(st["ts_start"])).total_seconds() / 60.0
    window_hours = float(st.get("window_hours", DEFAULT_WINDOW_HOURS))
    window_complete = elapsed_min >= window_hours * 60
    ev = evaluate_ratio(st["av_start"], av_now, vol_now, floor, min_vol)
    if not window_complete:
        ev["breached"] = False
    status = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "elapsed_min": round(elapsed_min, 1),
        "ratio_policy": st.get("ratio_policy", "legacy_cumulative"),
        "window_hours": window_hours,
        "window_complete": window_complete,
        "window_remaining_min": round(max(0.0, window_hours * 60 - elapsed_min), 1),
        "av_start": round(st["av_start"], 4),
        "av_now": (round(av_now, 4) if av_now is not None else None),
        "av_readable": av_now is not None,
        "data_quality": "OK" if av_now is not None else "ACCOUNT_VALUE_UNAVAILABLE",
        **ev,
        "n_rt": rt["n_rt"], "n_fill": rt["n_fill"],
        "rt_net": round(rt["rt_net"], 4), "fees": round(rt["fees"], 4),
        "pve_pause_active": PVE_PAUSE_FILE.exists(),
        "loss_cap_usd": st.get("loss_cap_usd"),
    }
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps(status, indent=2))
    return status


def _archive_and_roll_window(status: dict) -> dict:
    """Archive a completed window and start the next one without another API read."""
    if not status.get("window_complete") or not status.get("evaluable"):
        raise ValueError("only a completed evaluable window can be rolled")
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_FILE.open("a") as handle:
        handle.write(json.dumps(status, separators=(",", ":")) + "\n")
    previous = load_state() or {}
    new_state = {
        "ts_start": status["ts"],
        "av_start": status["av_now"],
        "vol_start": _pve_cum_volume(),
        "floor": status["floor"],
        "min_vol": status["min_vol"],
        "ratio_policy": "fixed_24h_window",
        "window_hours": status["window_hours"],
        "capital_usd": previous.get("capital_usd", 30.0),
        "loss_cap_usd": previous.get("loss_cap_usd", 4.0),
    }
    STATE_FILE.write_text(json.dumps(new_state, indent=2))
    return new_state


def _activate_pause(status: dict | None, reason: str) -> bool:
    """Atomically activate the local PVE pause and request one guarded restart."""
    if PVE_PAUSE_FILE.exists():
        return False
    ts = (status or {}).get("ts") or datetime.now(timezone.utc).isoformat()
    payload = {
        "ts": ts,
        "source": "sodex_honest_ratio_gate",
        "reason": reason,
    }
    PVE_PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PVE_PAUSE_FILE.write_text(json.dumps(payload, indent=2))
    RESTART_SIGNAL.write_text(json.dumps({
        "ts": ts,
        "type": "honest-ratio-gate",
        "reason": reason,
    }, indent=2))
    return True


def _clear_owned_pause_if_recovered(status: dict) -> bool:
    """Resume only an honest-ratio-owned pause after recovery with headroom."""
    if not PVE_PAUSE_FILE.exists():
        return False
    if not status.get("evaluable") or not status.get("vol_gate_met"):
        return False
    if status.get("breached"):
        return False
    ratio = status.get("ratio")
    if ratio is None:
        ratio = float("inf") if status.get("cost") == 0 else 0.0
    resume_floor = float(status["floor"]) * DEFAULT_RESUME_HEADROOM
    status["resume_floor"] = round(resume_floor, 1)
    if float(ratio) < resume_floor:
        return False
    try:
        pause = json.loads(PVE_PAUSE_FILE.read_text())
    except (OSError, ValueError):
        return False
    if pause.get("source") != "sodex_honest_ratio_gate":
        return False
    PVE_PAUSE_FILE.unlink()
    return True


def enforce() -> dict | None:
    """Evaluate only completed windows; retain hard data-availability protection."""
    status = compute_status()
    if status is None:
        _activate_pause(None, "honest ratio baseline unavailable")
        return None
    if not status["evaluable"]:
        activated = _activate_pause(status, "perps account value unavailable; ratio not provable")
        if activated:
            _tg_send(
                "HONEST-RATIO GATE DATA UNAVAILABLE - PVE PAUSED\n"
                "Perps account value cannot be read, so the minimum ratio cannot be proven."
            )
    elif not status.get("window_complete", True):
        pass
    elif status["breached"]:
        reason = (f"honest ratio 1:{status['ratio']:,.0f} < 1:{status['floor']:,.0f} "
                  f"vol=${status['vol']:,.0f} cost=${status['cost']:.2f}")
        activated = _activate_pause(status, reason)
        if activated:
            _tg_send(
                f"HONEST-RATIO GATE BREACH - PVE PAUSED\n"
                f"Rasio jujur 1:{status['ratio']:,.0f} < floor 1:{status['floor']:,.0f}\n"
                f"vol=${status['vol']:,.0f} cost=${status['cost']:.2f} "
                f"(fees=${status['fees']:.2f} rt_net=${status['rt_net']:.2f})\n"
                f"RT={status['n_rt']} elapsed={status['elapsed_min']:.0f}m"
            )
    elif _clear_owned_pause_if_recovered(status):
        ratio_text = ("no AV loss" if status["ratio"] is None
                      else f"1:{status['ratio']:,.0f}")
        _tg_send(
            "HONEST-RATIO GATE RECOVERED - PVE RESUMED\n"
            f"Rasio jujur {ratio_text} >= resume "
            f"1:{status['resume_floor']:,.0f} (floor 1:{status['floor']:,.0f}).\n"
            "Floor berikutnya tetap dinilai pada rata-rata jendela 24 jam."
        )
    # compute_status() runs before enforcement. Reflect a pause created by this same
    # cycle immediately so operators never see pve_pause_active=false on a breach.
    if status.get("pve_pause_active") != PVE_PAUSE_FILE.exists():
        status["pve_pause_active"] = PVE_PAUSE_FILE.exists()
        STATUS_FILE.write_text(json.dumps(status, indent=2))
    if status.get("window_complete") and status.get("evaluable"):
        _archive_and_roll_window(status)
        status["window_rotated"] = True
    return status


def report() -> dict | None:
    """Send a precise 30-min progress report to Telegram."""
    status = compute_status()
    if status is None:
        _tg_send("ℹ️ Honest-ratio experiment belum di-init.")
        return None
    ratio_s = f"1:{status['ratio']:,.0f}" if status["ratio"] is not None else "n/a (cost≈0)"
    pass_fail = "✅ ≥ floor" if (status["ratio"] is None or status["ratio"] >= status["floor"]) else "❌ < floor"
    if not status["window_complete"]:
        pass_fail = f"warming 24h ({status['window_remaining_min'] / 60:.1f}h left)"
    elif not status["vol_gate_met"]:
        pass_fail = f"⏳ warming (vol<${status['min_vol']:,.0f})"
    av_line = f"${status['av_now']:.2f}" if status["av_readable"] else "API unreachable"
    msg = (
        f"📊 PVE $30 PILOT — HONEST RASIO REAL\n"
        f"⏱ {status['elapsed_min']:.0f} min | {status['ts'][11:19]} UTC\n"
        f"— — —\n"
        f"Rasio jujur: {ratio_s}  [{pass_fail}]\n"
        f"Floor 24h: 1:{status['floor']:,.0f}\n"
        f"Volume: ${status['vol']:,.0f}\n"
        f"Cost (perps av drop): ${status['cost']:.2f}\n"
        f"  · fees: ${status['fees']:.2f}\n"
        f"  · rt_net: ${status['rt_net']:.2f}\n"
        f"RT closed: {status['n_rt']} | fills: {status['n_fill']}\n"
        f"perps av: {av_line} (start ${status['av_start']:.2f})\n"
        f"PVE paused: {'YES 🛑' if status['pve_pause_active'] else 'no ▶️'}\n"
        f"Loss-cap backstop: ${status['loss_cap_usd']}"
    )
    _tg_send(msg)
    return status


def main() -> int:
    ap = argparse.ArgumentParser(description="Honest Rasio Real gate for $30 PVE pilot")
    ap.add_argument("--init", action="store_true", help="Capture baseline at experiment start")
    ap.add_argument("--enforce", action="store_true", help="Check + pause PVE on breach")
    ap.add_argument("--report", action="store_true", help="Send Telegram progress report")
    ap.add_argument("--status", action="store_true", help="Print current status JSON")
    ap.add_argument("--floor", type=float, default=DEFAULT_FLOOR)
    ap.add_argument("--min-vol", type=float, default=DEFAULT_MIN_VOL)
    ap.add_argument("--window-hours", type=float, default=DEFAULT_WINDOW_HOURS)
    args = ap.parse_args()

    if args.init:
        st = init_experiment(args.floor, args.min_vol, args.window_hours)
        print(json.dumps(st, indent=2))
        return 0
    if args.report:
        s = report()
        print(json.dumps(s, indent=2) if s else "not initialised")
        return 0
    if args.status:
        s = compute_status()
        print(json.dumps(s, indent=2) if s else "not initialised")
        return 0
    # default = enforce
    s = enforce()
    print(json.dumps(s, indent=2) if s else "not initialised")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
