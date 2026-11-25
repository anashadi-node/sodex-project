#!/usr/bin/env python3
"""SoDEX 16-Oct recovery monitor (read-only).

Purpose: enforce disciplined monitoring after SoDEX paper fixes without touching
orders, leverage, SL/TP, or exchange state. Produces a compact latest report for
forward evidence: wallet target, paper-track ROI, CHOP-gate violations,
Short-Bear variant telemetry, service health, and live kill switches.

KONTRAK EXIT CODE (diperbaiki 2026-10-06):
    0 = monitor BERHASIL JALAN, apa pun putusannya (NORMAL/WARNING/ALERT).
    1 = monitor RUSAK (exception) — satu-satunya arti "gagal" bagi systemd.
    1 = juga bila `--strict` dan ada temuan (perilaku lama, kini opt-in).

Alasan: sebelumnya temuan (WARNING/ALERT) keluar dengan exit 1, sehingga systemd
menandai unit FAILED. Akibatnya kegagalan NYATA (crash) tidak bisa dibedakan dari
temuan yang diharapkan — cacat keselamatan pada monitor pemulihan. Temuan kini
disampaikan lewat notifikasi + riwayat append-only, bukan lewat status unit.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
DATA = PROJECT / "data"
REPORTS = PROJECT / "reports"
TARGET_ROI = 0.008
DEFAULT_CUTOFF = "2026-09-15T00:00:00+00:00"
DEADLINE_ISO = "2026-10-16T23:59:59+07:00"
HISTORY_PATH = REPORTS / "sodex" / "RECOVERY_MONITOR_HISTORY.jsonl"
NOTIFY_STATE = DATA / "sodex_recovery_notify_state.json"
NOTIFY_REMINDER_SEC = 12 * 3600      # ingatkan ulang bila temuan sama bertahan >12 jam

TRACKS = [
    ("REALWIDE", "paper_test_realwide_state.json"),
    ("TWOWAY", "paper_test_twoway_state.json"),
    ("SHORT_BEAR", "paper_test_shortbear_state.json"),
    ("SWING", "paper_test_swing_state.json"),
    ("SWING_PARTIAL", "paper_test_swing_state_partial.json"),
    ("DONCHIAN", "paper_test_donchian_state.json"),
    ("SPOT_SWING_v4", "paper_test_spot_swing_v2_state.json"),
    ("PORTFOLIO", "paper_test_portfolio_state.json"),
]

REQUIRED_SERVICES = [
    "anantara-paper-realwide.service",
    "anantara-paper-twoway.service",
    "anantara-paper-shortbear.service",
    "anantara-paper-shortbear-variants.service",
    "anantara-sodex-realsync.timer",
    "paper-learning-watchdog.timer",
]


def parse_time(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        if value > 10_000_000_000:
            value /= 1000.0
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return parse_time(float(text))
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def trade_time(trade: dict[str, Any]) -> float | None:
    for key in ("entry_ts", "entry_time", "entry_iso", "ts", "time"):
        ts = parse_time(trade.get(key))
        if ts is not None:
            return ts
    return None


def load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text())
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def closed_trades(state: dict[str, Any]) -> list[dict[str, Any]]:
    raw = state.get("closed") or state.get("closed_trades") or []
    return [t for t in raw if isinstance(t, dict)] if isinstance(raw, list) else []


def open_count(state: dict[str, Any]) -> int:
    raw = state.get("open", state.get("positions", []))
    if isinstance(raw, (list, dict)):
        return len(raw)
    return 0


def pnl_usd(trade: dict[str, Any]) -> float:
    for key in ("pnl_usd", "pnl", "net_pnl"):
        try:
            return float(trade.get(key, 0) or 0)
        except (TypeError, ValueError):
            continue
    return 0.0


def filter_since(trades: list[dict[str, Any]], cutoff_ts: float | None) -> list[dict[str, Any]]:
    if cutoff_ts is None:
        return list(trades)
    return [t for t in trades if (trade_time(t) or 0) >= cutoff_ts]


def bootstrap_ci(values: list[float], rounds: int = 1000) -> dict[str, Any] | None:
    if len(values) < 20:
        return None
    rnd = random.Random(20260915)
    means = []
    n = len(values)
    for _ in range(rounds):
        means.append(sum(values[rnd.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo = means[int(0.025 * rounds)]
    hi = means[int(0.975 * rounds) - 1]
    p_pos = sum(1 for m in means if m > 0) / rounds
    return {"mean_ci95_usd": [round(lo, 6), round(hi, 6)], "p_pos": round(p_pos, 4)}


def metrics(trades: list[dict[str, Any]], wallet: float | None) -> dict[str, Any]:
    n = len(trades)
    out: dict[str, Any] = {"n": n}
    if n == 0:
        return out
    pnls = [pnl_usd(t) for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    total = sum(pnls)
    out.update({
        "wins": wins,
        "wr_pct": round(wins / n * 100, 2),
        "pnl_usd": round(total, 4),
        "avg_pnl_usd": round(total / n, 6),
        "profit_factor": profit_factor(pnls),
    })
    ci = bootstrap_ci(pnls)
    if ci:
        out["bootstrap"] = ci
    if wallet and wallet > 0:
        avg_roi = total / wallet / n
        hit = sum(1 for p in pnls if p / wallet >= TARGET_ROI)
        out.update({
            "avg_wallet_roi_pct": round(avg_roi * 100, 4),
            "hit_target_count": hit,
            "hit_target_pct": round(hit / n * 100, 2),
            "target_met": avg_roi >= TARGET_ROI,
        })
    return out


def profit_factor(pnls: list[float]) -> float | str:
    wins = sum(p for p in pnls if p > 0)
    losses = sum(p for p in pnls if p < 0)
    if losses == 0:
        return "inf" if wins > 0 else 0.0
    return round(wins / abs(losses), 4)


def read_wallet(project: Path = PROJECT) -> tuple[float | None, str, str | None]:
    scripts_dir = str(project / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        from sodex_wallet_denominator import read_real_wallet  # type: ignore
        result = read_real_wallet()
        if isinstance(result, tuple) and len(result) >= 3:
            total = float(result[2])
            return total, "verified_snapshot", None
    except Exception as exc:
        verified_error = f"{type(exc).__name__}: {exc}"
    else:
        verified_error = "unexpected read_real_wallet result"

    env_path = project / ".env.swing"
    try:
        for line in env_path.read_text().splitlines():
            if line.startswith("SODEX_TOTAL_WALLET="):
                return float(line.split("=", 1)[1].strip()), ".env.swing", verified_error
    except Exception as exc:
        return None, "unavailable", f"{verified_error}; env: {type(exc).__name__}: {exc}"
    return None, "unavailable", verified_error


def collect_tracks(project: Path, cutoff_ts: float | None, wallet: float | None) -> list[dict[str, Any]]:
    rows = []
    for name, fname in TRACKS:
        path = project / "data" / fname
        state = load_json(path)
        closed = closed_trades(state)
        rows.append({
            "name": name,
            "file": fname,
            "exists": path.exists(),
            "open": open_count(state),
            "all": metrics(closed, wallet),
            "forward": metrics(filter_since(closed, cutoff_ts), wallet),
        })
    return rows


def is_long(trade: dict[str, Any]) -> bool:
    side = str(trade.get("side", trade.get("direction", ""))).upper()
    return side in {"LONG", "L", "BUY"}


def regime_value(trade: dict[str, Any]) -> str:
    return str(trade.get("btc_regime", trade.get("regime", "UNKNOWN"))).upper()


def trade_track(trade: dict[str, Any]) -> str:
    return str(trade.get("track") or "").upper()


def chop_gate_violations(rows: list[dict[str, Any]], project: Path, cutoff_ts: float | None) -> list[dict[str, Any]]:
    """LONG entries that the CHOP regime gate should have skipped.

    The engine gates only the SIGNAL arm (paper_test_realwide.py:387-397,
    paper_test_twoway.py:569-571). Two classes previously produced false
    positives and are excluded here:
      * RANDOM_CONTROL rows — the by-design negative control, never gated;
      * regime of None/UNKNOWN — documentation of a fail-open on BTC data error;
      * rows predating the `track` field — legacy taxonomy, unattributable.
    Only SIGNAL-track LONG entries carrying an explicit btc_regime == "CHOP"
    count as violations.
    """
    by_name = {name: fname for name, fname in TRACKS}
    violations = []
    for name in ("REALWIDE", "TWOWAY"):
        state = load_json(project / "data" / by_name[name])
        for trade in filter_since(closed_trades(state), cutoff_ts):
            if not is_long(trade):
                continue
            if trade_track(trade) != "SIGNAL":
                continue
            if regime_value(trade) != "CHOP":
                continue
            violations.append({
                "track": name,
                "pair": trade.get("sym", trade.get("pair")),
                "entry": trade.get("entry_iso", trade.get("entry_time")),
                "regime": regime_value(trade),
            })
    return violations


def read_jsonl_tail(path: Path, max_lines: int = 2000) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = [line for line in path.read_text().splitlines() if line.strip()]
    except Exception:
        return []
    rows = []
    for line in lines[-max_lines:]:
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except json.JSONDecodeError:
            continue
    return rows


def shortbear_variants(project: Path, now_ts: float) -> list[dict[str, Any]]:
    out = []
    for state_path in sorted((project / "data").glob("paper_test_shortbear_*_state.json")):
        variant = state_path.name.removeprefix("paper_test_shortbear_").removesuffix("_state.json")
        telemetry = state_path.with_name(f"paper_test_shortbear_{variant}_telemetry.jsonl")
        state = load_json(state_path)
        rows = read_jsonl_tail(telemetry)
        recent = [r for r in rows if (parse_time(r.get("cycle_iso")) or 0) >= now_ts - 24 * 3600]
        decisions = Counter(str(r.get("decision", "unknown")) for r in recent)
        native = sum(1 for r in recent if r.get("native_mark") is not None)
        candidates = sum(1 for r in recent if str(r.get("decision", "")).startswith("entry") or r.get("candidate"))
        out.append({
            "variant": variant,
            "closed": len(closed_trades(state)),
            "open": open_count(state),
            "telemetry_24h": len(recent),
            "decisions_24h": dict(decisions.most_common()),
            "native_mark_rows_24h": native,
            "candidates_24h": candidates,
        })
    return out


def service_active(name: str) -> bool:
    try:
        res = subprocess.run(["systemctl", "--user", "is-active", name], capture_output=True, text=True, timeout=15)
        return res.stdout.strip() == "active"
    except Exception:
        return False


def service_health() -> dict[str, bool]:
    return {svc: service_active(svc) for svc in REQUIRED_SERVICES}


def live_kills(project: Path) -> dict[str, bool]:
    return {
        "REALWIDE_LIVE_KILL": (project / "data" / "REALWIDE_LIVE_KILL").exists(),
        "SPOT_LIVE_KILL": (project / "data" / "SPOT_LIVE_KILL").exists(),
    }


def live_resume_approved(project: Path) -> bool:
    """True when kill files were archived by an explicit SoDEX live-resume decision."""
    return any((project / "data").glob("sodex_go_live_resume_*.json"))


def verdict(payload: dict[str, Any]) -> tuple[str, list[str]]:
    issues = []
    if payload["wallet"]["value"] is None:
        issues.append("wallet denominator unavailable")
    if not all(payload["live_kills"].values()) and not payload.get("live_resume_approved"):
        issues.append("live kill switch missing")
    inactive = [k for k, v in payload["services"].items() if not v]
    if inactive:
        issues.append("inactive services: " + ", ".join(inactive))
    if payload["chop_gate_violations"]:
        issues.append(f"CHOP gate violations: {len(payload['chop_gate_violations'])}")
    if issues:
        level = "ALERT" if any("kill" in i or "violation" in i for i in issues) else "WARNING"
        return level, issues
    return "NORMAL", []


def build_payload(project: Path = PROJECT, cutoff: str | None = None) -> dict[str, Any]:
    now_ts = time.time()
    cutoff = cutoff or os.environ.get("SODEX_RECOVERY_CUTOFF", DEFAULT_CUTOFF)
    cutoff_ts = parse_time(cutoff)
    deadline_ts = parse_time(DEADLINE_ISO)
    days_to_deadline = max(0, int((deadline_ts - now_ts) // 86400)) if deadline_ts else None
    wallet, wallet_source, wallet_error = read_wallet(project)
    rows = collect_tracks(project, cutoff_ts, wallet)
    payload: dict[str, Any] = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "cutoff_utc": datetime.fromtimestamp(cutoff_ts, timezone.utc).isoformat() if cutoff_ts else None,
        "deadline_utc": datetime.fromtimestamp(deadline_ts, timezone.utc).isoformat() if deadline_ts else DEADLINE_ISO,
        "days_to_deadline": days_to_deadline,
        "target_roi": TARGET_ROI,
        "target_usd": round(wallet * TARGET_ROI, 6) if wallet else None,
        "wallet": {"value": wallet, "source": wallet_source, "error": wallet_error},
        "tracks": rows,
        "shortbear_variants": shortbear_variants(project, now_ts),
        "services": service_health() if project == PROJECT else {},
        "live_kills": live_kills(project),
        "live_resume_approved": live_resume_approved(project),
    }
    payload["chop_gate_violations"] = chop_gate_violations(rows, project, cutoff_ts)
    payload["verdict"], payload["issues"] = verdict(payload)
    return payload


def fmt_metric(metric: dict[str, Any]) -> str:
    if not metric.get("n"):
        return "n=0"
    roi = metric.get("avg_wallet_roi_pct")
    roi_s = "n/a" if roi is None else f"{roi:+.4f}%"
    return f"n={metric['n']} WR={metric.get('wr_pct', 0):.1f}% ROI={roi_s} PnL=${metric.get('pnl_usd', 0):+.2f}"


def render_markdown(payload: dict[str, Any]) -> str:
    wallet = payload["wallet"]
    lines = [
        "# SoDEX Recovery Monitor",
        "",
        f"Generated UTC: {payload['generated_utc']}",
        f"Verdict: {payload['verdict']}",
        f"Cutoff: {payload['cutoff_utc']}",
        f"Deadline: {payload['deadline_utc']} ({payload['days_to_deadline']} days)",
        f"Wallet: ${wallet['value']:.2f} ({wallet['source']})" if wallet["value"] is not None else f"Wallet: unavailable ({wallet['source']})",
        f"Target/trade: ${payload['target_usd']:.4f} ({payload['target_roi']*100:.2f}% wallet)" if payload["target_usd"] else "Target/trade: unavailable",
        "",
    ]
    if payload["issues"]:
        lines.append("## Issues")
        lines.extend(f"- {issue}" for issue in payload["issues"])
        lines.append("")

    lines.append("## Paper tracks")
    lines.append("| Track | Open | All | Forward since cutoff |")
    lines.append("|---|---:|---|---|")
    for row in payload["tracks"]:
        lines.append(f"| {row['name']} | {row['open']} | {fmt_metric(row['all'])} | {fmt_metric(row['forward'])} |")
    lines.append("")

    lines.append("## Short-Bear variants, last 24h")
    lines.append("| Variant | Closed | Open | Telemetry | Candidates | Native mark rows | Decisions |")
    lines.append("|---|---:|---:|---:|---:|---:|---|")
    for row in payload["shortbear_variants"]:
        lines.append(f"| {row['variant']} | {row['closed']} | {row['open']} | {row['telemetry_24h']} | {row['candidates_24h']} | {row['native_mark_rows_24h']} | `{row['decisions_24h']}` |")
    lines.append("")

    lines.append("## Controls")
    lines.append(f"- Live kills: {payload['live_kills']} (resume approved: {payload.get('live_resume_approved')})")
    lines.append(f"- Services: {payload['services']}")
    lines.append(f"- CHOP gate violations: {len(payload['chop_gate_violations'])}")
    return "\n".join(lines) + "\n"


def write_outputs(payload: dict[str, Any], project: Path = PROJECT) -> tuple[Path, Path]:
    reports = project / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    md = reports / "SODEX_RECOVERY_MONITOR_LATEST.md"
    js = reports / "SODEX_RECOVERY_MONITOR_LATEST.json"
    md.write_text(render_markdown(payload))
    js.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return md, js


def env_get(key: str, project: Path = PROJECT) -> str:
    """Ambil nilai dari .env tanpa pernah mencatatnya ke log."""
    try:
        for line in open(project / ".env", encoding="utf-8", errors="ignore"):
            m = re.match(rf"^\s*{key}\s*=\s*(.*?)\s*$", line)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def send_telegram(text: str, project: Path = PROJECT) -> bool:
    tok, cid = env_get("TELEGRAM_BOT_TOKEN", project), env_get("TELEGRAM_CHAT_ID", project)
    if not tok or not cid:
        return False
    try:
        data = urllib.parse.urlencode({"chat_id": cid, "text": text, "parse_mode": "HTML"}).encode()
        urllib.request.urlopen(
            urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=data), timeout=10)
        return True
    except Exception:                                          # noqa: BLE001
        return False


def notify_signature(payload: dict[str, Any]) -> str:
    return payload["verdict"] + "|" + "|".join(sorted(payload["issues"]))


def should_notify(payload: dict[str, Any], project: Path = PROJECT,
                  now_ts: float | None = None) -> bool:
    """Notifikasi bila tanda-tangan temuan BERUBAH, atau temuan sama bertahan >12 jam."""
    if not payload["issues"]:
        return False
    now_ts = now_ts if now_ts is not None else time.time()
    try:
        state = json.loads((project / "data" / "sodex_recovery_notify_state.json").read_text())
    except Exception:                                          # noqa: BLE001
        state = {}
    if state.get("signature") != notify_signature(payload):
        return True
    return (now_ts - float(state.get("last_ts") or 0)) >= NOTIFY_REMINDER_SEC


def mark_notified(payload: dict[str, Any], project: Path = PROJECT,
                  now_ts: float | None = None) -> None:
    try:
        (project / "data").mkdir(parents=True, exist_ok=True)
        (project / "data" / "sodex_recovery_notify_state.json").write_text(json.dumps(
            {"signature": notify_signature(payload), "verdict": payload["verdict"],
             "last_ts": now_ts if now_ts is not None else time.time()}, indent=1))
    except Exception:                                          # noqa: BLE001
        pass


def append_history(payload: dict[str, Any], project: Path = PROJECT) -> Path:
    """Riwayat append-only — satu baris JSON per jalan.

    Penting: berkas state paper (REALWIDE 255, TWOWAY 396 trade) DIPANGKAS, sehingga
    bukti pelanggaran bisa lenyap sebelum sempat diperiksa (kasus 2026-10-04/05).
    Riwayat ini menyimpan temuan + rincian pelanggaran agar tetap dapat diaudit.
    """
    reports = project / "reports" / "sodex"
    reports.mkdir(parents=True, exist_ok=True)
    hist = reports / "RECOVERY_MONITOR_HISTORY.jsonl"
    rec = {
        "ts_utc": payload["generated_utc"],
        "verdict": payload["verdict"],
        "issues": payload["issues"],
        "wallet": payload["wallet"]["value"],
        "target_usd": payload["target_usd"],
        "services_down": [k for k, v in payload["services"].items() if not v],
        "violation_count": len(payload["chop_gate_violations"]),
        "violations": payload["chop_gate_violations"],
    }
    with open(hist, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    if payload["chop_gate_violations"]:
        snap = reports / "recovery_violations"
        snap.mkdir(parents=True, exist_ok=True)
        stamp = re.sub(r"[^0-9]", "", payload["generated_utc"])[:14]
        (snap / f"violations_{stamp}.json").write_text(
            json.dumps(payload["chop_gate_violations"], indent=1))
    return hist


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SoDEX 16-Oct recovery monitor (read-only)")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 bila ada temuan (perilaku lama; default 0 asal monitor berhasil jalan)")
    ap.add_argument("--no-notify", action="store_true", help="lewati notifikasi Telegram")
    args = ap.parse_args(argv)

    try:
        payload = build_payload()
        md, js = write_outputs(payload)
    except Exception as exc:                                   # noqa: BLE001
        print(f"MONITOR GAGAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1                                               # 1 = monitor RUSAK, bukan temuan

    print(f"SoDEX recovery monitor: {payload['verdict']} | wallet={payload['wallet']['value']} "
          f"source={payload['wallet']['source']} target_usd={payload['target_usd']} "
          f"issues={len(payload['issues'])}")
    for issue in payload["issues"]:
        print(f"  ISSUE: {issue}")                             # teks isu masuk journal (dulu tidak)
    print(f"Wrote {md}")
    print(f"Wrote {js}")

    try:
        print(f"Appended {append_history(payload)}")
    except Exception as exc:                                   # noqa: BLE001
        print(f"  (riwayat gagal ditulis: {type(exc).__name__})", file=sys.stderr)

    if payload["issues"] and not args.no_notify and should_notify(payload):
        detail = "\n".join(f"• {i}" for i in payload["issues"])
        sent = send_telegram(
            f"<b>SoDEX recovery monitor: {payload['verdict']}</b>\n{detail}\n"
            f"wallet={payload['wallet']['value']} target_usd={payload['target_usd']}\n"
            f"pelanggaran CHOP: {len(payload['chop_gate_violations'])}", )
        print(f"  notifikasi: {'terkirim' if sent else 'TIDAK terkirim'}")
        mark_notified(payload)

    return 1 if (args.strict and payload["verdict"] != "NORMAL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
