"""Astronacci autonomous self-monitor & self-heal module (Round 6).

Runs a battery of honesty checks on the system and, where safe, applies
non-destructive self-healing. Designed to be invoked by the daemon on a
frequent schedule (e.g. hourly) so the system polices itself 24/7.

Design principles (falsification-first, ponytail):
  - NEVER silently mutate production decisions (no auto-promote / auto-trade).
  - Self-heal actions are limited to SAFE operations: refresh stale data,
    re-evaluate stale registry entries through the honest 7-gate defense,
    demote entries that no longer pass, and log everything.
  - Every finding is scored and emitted in a structured report so a human
    (or the LLM agent) can review what the monitor did.
  - Std lib only. No new dependencies.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

try:
    import logging
    log = logging.getLogger("astronacci.monitor")
except Exception:  # pragma: no cover
    log = None


@dataclass
class CheckResult:
    name: str
    status: str            # "ok" | "warn" | "fail"
    detail: str
    healed: bool = False   # True if a self-heal action was applied
    heal_action: str = ""


@dataclass
class MonitorReport:
    timestamp: str
    overall: str           # "healthy" | "degraded" | "critical"
    checks: list[CheckResult] = field(default_factory=list)
    healed_count: int = 0

    def add(self, c: CheckResult):
        self.checks.append(c)
        if c.healed:
            self.healed_count += 1
        if c.status == "fail" and self.overall != "critical":
            self.overall = "critical"
        elif c.status == "warn" and self.overall == "healthy":
            self.overall = "degraded"

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "overall": self.overall,
            "healed_count": self.healed_count,
            "checks": [asdict(c) for c in self.checks],
        }


class AstronacciMonitor:
    """Autonomous health monitor + safe self-healer."""

    # Stale threshold: a daily dataset older than this (days) needs refresh.
    DATA_STALE_DAYS = 3

    # North Star (2026-08-13): swing TF 1-30h. The dataset that actually drives
    # trade decisions is {SYM}_4h.jsonl, NOT the daily file. Daily freshness is
    # measured in whole days, so a 16h stall on the 4h feed reads as age=0 and
    # passes — which is exactly how the 2026-08-14 pipeline outage stayed
    # invisible. 8h = 2 missed 4h bars: past normal fetch lag, well inside the
    # 1-30h decision horizon.
    SWING_TF = "4h"
    SWING_STALE_HOURS = 8
    SWING_REFETCH_DAYS = 180  # mirrors SWING_DAYS_DATA in astronacci_paper_daemon

    def __init__(self, project_dir: str | None = None):
        self.project_dir = Path(project_dir or os.environ.get(
            "ANANTARA_DIR", str(Path.home() / "anantara-sakti")
        ))
        self.data_dir = self.project_dir / "data" / "astronacci"
        self.monitors_dir = self.data_dir / "monitors"
        self.monitors_dir.mkdir(parents=True, exist_ok=True)

    # ── entry point ──────────────────────────────────────────────────────
    def run(self, heal: bool = True) -> MonitorReport:
        """Run all checks; apply safe self-heals when `heal=True`."""
        report = MonitorReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            overall="healthy",
        )
        self._check_imports(report)
        self._check_data_freshness(report, heal)
        self._check_swing_freshness(report, heal)
        self._check_registry_honesty(report, heal)
        self._check_paper_loop_sanity(report)
        self._check_determinism(report)
        self._check_market_intel(report)
        self._check_paper_performance(report)
        self._save(report)
        if log:
            log.info(
                f"Monitor: {report.overall} | {len(report.checks)} checks | "
                f"{report.healed_count} healed"
            )
        return report

    # ── individual checks ────────────────────────────────────────────────
    def _check_imports(self, report: MonitorReport):
        """Every astronacci_* module must import (list read from disk, not hand-kept)."""
        # ponytail: glob instead of a hardcoded list. The old 16-name list had drifted
        # behind the 23 modules on disk and did NOT cover astronacci_data_collector or
        # astronacci_paper_daemon — exactly the two whose 2026-08-14 httpx failure went
        # undetected for 13h. Deriving from disk kills this drift class permanently.
        names = sorted(p.stem for p in Path(__file__).parent.glob("astronacci_*.py"))
        failed = []
        for n in names:
            try:
                __import__(n)
            except Exception as e:
                failed.append(f"{n}: {type(e).__name__}: {e}")
        if failed:
            report.add(CheckResult(
                "imports", "fail",
                f"{len(failed)} modules failed: " + "; ".join(failed[:2]),
            ))
        else:
            report.add(CheckResult("imports", "ok", f"all {len(names)} modules import"))

    # Canonical daily datasets we own and refresh: {SYMBOL}_1d.jsonl.
    # Venue-prefixed files (binance_public_*, bybit_public_*) are frozen
    # historical exports, NOT live datasets — exclude them from freshness.
    CANONICAL_SYMBOLS = ("BTC", "ETH", "SOL", "ARB", "LTC")

    def _check_data_freshness(self, report: MonitorReport, heal: bool):
        """Daily datasets must be recent; self-heal by re-fetching stale ones.

        Only checks CANONICAL files ({SYMBOL}_1d.jsonl). Venue-prefixed
        exports (binance_public_*, bybit_public_*) are frozen historical
        snapshots and are intentionally excluded — flagging them produced a
        perpetual false-warn that the self-heal could never clear.
        """
        stale = []
        for sym in self.CANONICAL_SYMBOLS:
            p = self.data_dir / f"{sym}_1d.jsonl"
            if not p.exists():
                stale.append((sym, -1))  # missing
                continue
            try:
                with open(p) as f:
                    lines = f.read().strip().split("\n")
                if not lines:
                    stale.append((sym, -1))
                    continue
                last = json.loads(lines[-1])
                ts = last.get("timestamp", "")[:10]
                if not ts:
                    continue
                last_dt = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - last_dt).days
                if age > self.DATA_STALE_DAYS:
                    stale.append((sym, age))
            except Exception:
                continue
        if not stale:
            report.add(CheckResult("data_freshness", "ok", "all daily datasets recent"))
            return
        detail = ", ".join(f"{n}({d}d)" for n, d in stale[:5])
        healed = False
        action = ""
        still_stale = list(stale)
        if heal:
            # Safe self-heal: re-fetch the canonical assets from public API.
            try:
                from astronacci_pipeline import AstroDataPipeline
                pipe = AstroDataPipeline()
                refreshed = []
                for sym, _ in stale:
                    if sym in self.CANONICAL_SYMBOLS:
                        try:
                            ds = pipe.fetch(sym, "1d", days=365, save=True)
                            if ds and ds.bars:
                                refreshed.append(sym)
                        except Exception:
                            pass
                if refreshed:
                    healed = True
                    action = f"refreshed: {','.join(refreshed)}"
                    # Only report symbols that REMAIN stale after the heal,
                    # so a successful refresh clears the warning instead of
                    # re-reporting the (now-fresh) data as stale.
                    still_stale = [(s, a) for s, a in stale if s not in refreshed]
            except Exception as e:
                action = f"refresh attempted, failed: {type(e).__name__}"
        # Final status reflects post-heal state: if everything got refreshed,
        # the check is OK; otherwise warn with what remains stale.
        if not still_stale:
            report.add(CheckResult(
                "data_freshness", "ok",
                f"all canonical daily datasets fresh ({detail} → healed)",
                healed=healed, heal_action=action,
            ))
        else:
            remain = ", ".join(f"{n}({d}d)" for n, d in still_stale[:5])
            report.add(CheckResult(
                "data_freshness", "warn",
                f"{len(still_stale)} still stale after heal: {remain}",
                healed=healed, heal_action=action,
            ))

    def _check_swing_freshness(self, report: MonitorReport, heal: bool):
        """Swing-TF datasets must be fresh in HOURS — the North Star decision feed.

        Only symbols that already have a {SYM}_{SWING_TF}.jsonl are checked; a
        canonical symbol with no swing file is not running the swing track and
        is not an error.
        """
        stale = []
        for sym in self.CANONICAL_SYMBOLS:
            p = self.data_dir / f"{sym}_{self.SWING_TF}.jsonl"
            if not p.exists():
                continue  # symbol not on the swing track — by design, not stale
            try:
                with open(p) as f:
                    lines = f.read().strip().split("\n")
                if not lines or not lines[-1]:
                    stale.append((sym, -1.0))
                    continue
                ts = json.loads(lines[-1]).get("timestamp", "")
                if not ts:
                    continue
                last_dt = datetime.fromisoformat(ts)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                age_h = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600.0
                if age_h > self.SWING_STALE_HOURS:
                    stale.append((sym, age_h))
            except Exception:
                continue

        if not stale:
            report.add(CheckResult(
                "swing_freshness", "ok",
                f"all {self.SWING_TF} datasets fresh (<{self.SWING_STALE_HOURS}h)",
            ))
            return

        detail = ", ".join(f"{n}({d:.1f}h)" for n, d in stale[:5])
        healed = False
        action = ""
        still_stale = list(stale)
        if heal:
            try:
                from astronacci_pipeline import AstroDataPipeline
                pipe = AstroDataPipeline()
                refreshed = []
                for sym, _ in stale:
                    try:
                        ds = pipe.fetch(sym, self.SWING_TF,
                                        days=self.SWING_REFETCH_DAYS, save=True)
                        if ds and ds.bars:
                            refreshed.append(sym)
                    except Exception:
                        pass
                if refreshed:
                    healed = True
                    action = f"refreshed: {','.join(refreshed)}"
                    still_stale = [(s, a) for s, a in stale if s not in refreshed]
            except Exception as e:
                action = f"refresh attempted, failed: {type(e).__name__}"

        if not still_stale:
            report.add(CheckResult(
                "swing_freshness", "ok",
                f"all {self.SWING_TF} datasets fresh ({detail} → healed)",
                healed=healed, heal_action=action,
            ))
        else:
            remain = ", ".join(f"{n}({d:.1f}h)" for n, d in still_stale[:5])
            suffix = " after heal" if heal else ""
            report.add(CheckResult(
                "swing_freshness", "fail",
                f"{len(still_stale)} {self.SWING_TF} datasets stale{suffix}: {remain}",
                healed=healed, heal_action=action,
            ))

    def _check_registry_honesty(self, report: MonitorReport, heal: bool):
        """No `production` entry may exist without a real defense_result.
        Self-heal: demote any stale production entry to `research`."""
        try:
            from astronacci_ablation import EvidenceRegistry
            reg = EvidenceRegistry()
        except Exception as e:
            report.add(CheckResult("registry_honesty", "fail", f"registry load: {e}"))
            return
        entries = getattr(reg, "_entries", {}) or {}
        stale_prod = [
            n for n, e in entries.items()
            if e.status == "production"
            and not (
                isinstance(e.test_results.get("defense_result"), dict)
                and e.test_results["defense_result"].get("gates_passed", 0) >= 5
            )
        ]
        if not stale_prod:
            report.add(CheckResult(
                "registry_honesty", "ok",
                f"{len(entries)} entries, all production backed by defense",
            ))
            return
        healed = False
        action = ""
        if heal:
            for name in stale_prod:
                e = entries[name]
                reg.register(
                    feature_name=name, layer=e.layer, layer_name=e.layer_name,
                    evidence_score=min(e.evidence_score, 50),
                    test_results=e.test_results,
                    notes=(e.notes + " | " if e.notes else "")
                              + "MONITOR: demoted stale production→research (no valid defense)",
                )
            healed = True
            action = f"demoted {len(stale_prod)} stale production entries"
        report.add(CheckResult(
            "registry_honesty", "warn" if stale_prod else "ok",
            f"{len(stale_prod)} stale production (no defense): "
            + ", ".join(stale_prod[:3]),
            healed=healed, heal_action=action,
        ))

    def _check_paper_loop_sanity(self, report: MonitorReport):
        """Open paper trades must all have defense_gates_passed >= 5
        (the loop only opens production signals). Flag any that don't."""
        path = self.data_dir / "paper" / "portfolio.json"
        if not path.exists():
            report.add(CheckResult("paper_loop", "ok", "no portfolio yet"))
            return
        try:
            data = json.loads(path.read_text())
        except Exception:
            report.add(CheckResult("paper_loop", "warn", "portfolio unreadable"))
            return
        open_trades = data.get("open_trades", [])
        bad = [t.get("signal_id", "?") for t in open_trades
               if t.get("defense_gates_passed", 0) < 5]
        if bad:
            report.add(CheckResult(
                "paper_loop", "fail",
                f"{len(bad)} open trades without defense: {bad[:3]}",
            ))
        else:
            report.add(CheckResult(
                "paper_loop", "ok",
                f"{len(open_trades)} open trades, all defense-backed",
            ))

    def _check_determinism(self, report: MonitorReport):
        """Statistical functions must be reproducible (no global-RNG leaks)."""
        try:
            from astronacci_stats import probability_of_backtest_overfitting
            from astronacci_improve import DeepAnalysisEngine
            is_m = [0.5, 0.6, 0.4, 0.7, 0.55, 0.45, 0.65, 0.5]
            oos = [0.3, 0.5, 0.2, 0.4, 0.35, 0.25, 0.45, 0.3]
            pbo_runs = [probability_of_backtest_overfitting(is_m, oos)["pbo"]
                        for _ in range(3)]
            import random
            random.seed(2024); before = random.random()
            random.seed(2024)
            probability_of_backtest_overfitting(is_m, oos)
            vals = [0.01, -0.02, 0.03, -0.01, 0.005, -0.03, 0.02, 0.015]
            DeepAnalysisEngine._bootstrap_pvalue(vals, 100)
            after = random.random()
            det = len(set(pbo_runs)) == 1 and before == after
            report.add(CheckResult(
                "determinism", "ok" if det else "fail",
                f"PBO reproducible={len(set(pbo_runs))==1}, global RNG clean={before==after}",
            ))
        except Exception as e:
            report.add(CheckResult("determinism", "fail", f"{type(e).__name__}: {e}"))

    def _check_market_intel(self, report: MonitorReport):
        """Market behavior early-warning + adaptive engine must be importable
        and functional. This guards the Round 7 wiring: market_intel was a
        ghost module (built, never wired) and is now the live reaction layer.
        If it silently breaks (import error, bad evaluate() contract), the
        hourly daemon job would fail invisibly — this check surfaces it.
        """
        try:
            from astronacci_market_intel import (
                MarketIntelligence, AdaptiveStrategyEngine,
            )
            # Functional smoke: a synthetic price series + volume spike must
            # produce a valid adaptive verdict without raising.
            intel = MarketIntelligence()
            import random as _r
            rng = _r.Random(123)
            prices = [100.0]
            for _ in range(35):
                prices.append(prices[-1] * (1 + rng.gauss(0, 0.01)))
            for p in prices:
                intel.behavior.update("TEST", p, volume=rng.uniform(80, 120))
            beh = intel.behavior.detect_all("TEST", current_volatility=2.0)
            strat = intel.adaptive.evaluate(beh, {"direction": "NEUTRAL",
                                                  "confidence": 0.5})
            mode = strat.get("mode")
            valid_modes = set(AdaptiveStrategyEngine.MODES.keys())
            if mode not in valid_modes:
                report.add(CheckResult(
                    "market_intel", "fail",
                    f"adaptive returned invalid mode={mode!r} (not in {valid_modes})",
                ))
            else:
                report.add(CheckResult(
                    "market_intel", "ok",
                    f"scan+evaluate functional, mode={mode}, "
                    f"{len(beh.get('detections', {}))} detections",
                ))
        except Exception as e:
            report.add(CheckResult(
                "market_intel", "fail", f"{type(e).__name__}: {e}",
            ))

    # ── persistence ──────────────────────────────────────────────────────
    def _check_paper_performance(self, report: MonitorReport):
        """Paper-trade track-record honesty check.

        Reads the TA-based `paper_trades.jsonl` (paper_daemon format) AND
        the Round-11 OOS forward track-record `paper_oos_forward.jsonl`,
        and reports win-rate / PnL / profit-factor. Flags when the track-
        record is losing (profit factor < 1) — an honest 'the current
        strategy is not profitable yet' rather than silence. NOT a self-
        heal: we never delete losing trades; we surface them so the
        operator sees the real edge status.
        """
        # Read each track-record SEPARATELY so the operator sees which
        # strategy is which — combining a dead legacy strategy (large loss)
        # with a new OOS edge (profit) would obscure both. Honest reporting
        # means showing each on its own merits.
        def _read_pnls(fname: str) -> list[float]:
            out: list[float] = []
            p = self.data_dir / fname
            try:
                if not p.exists():
                    return out
                with open(p) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            out.append(float(json.loads(line).get("pnl", 0)))
                        except Exception:
                            pass
            except Exception:
                pass
            return out

        legacy = _read_pnls("paper_trades.jsonl")     # old TA strategy (paper_daemon)
        oos = _read_pnls("paper_oos_forward.jsonl")   # Round-11 LONG-only edge (forward)

        def _summ(label, pnls):
            if not pnls:
                return f"{label}: no trades"
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            pos = sum(wins); neg = sum(losses)
            pf = round(pos / abs(neg), 2) if neg != 0 else None
            wr = round(len(wins) / len(pnls) * 100, 1)
            return f"{label}: n={len(pnls)} WR={wr}% PF={pf} PnL={round(sum(pnls),2)}"

        legacy_detail = _summ("legacy-TA", legacy)
        oos_detail = _summ("OOS-edge", oos)

        if not legacy and not oos:
            report.add(CheckResult(
                "paper_performance", "ok",
                "no paper trades yet (no production signal → none opened)",
            ))
            return

        # Verdict hinges on the CURRENT edge (OOS), not the dead legacy.
        def _pf(pnls):
            pos = sum(p for p in pnls if p > 0)
            neg = sum(p for p in pnls if p < 0)
            return (pos / abs(neg)) if neg != 0 else None

        oos_pf = _pf(oos)
        # Honest verdict: if we have an OOS track-record, that's what matters
        # for live-readiness. Legacy loss is informational only.
        if oos:
            status = "warn" if (oos_pf is not None and oos_pf < 1.0) else "ok"
        else:
            # No OOS yet — fall back to legacy verdict (will be 'warn').
            legacy_pf = _pf(legacy)
            status = "warn" if (legacy_pf is None or legacy_pf < 1.0) else "ok"
        report.add(CheckResult(
            "paper_performance", status,
            f"{legacy_detail} | {oos_detail}",
        ))

    # ── persistence ──────────────────────────────────────────────────────
    def _save(self, report: MonitorReport):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = self.monitors_dir / f"monitor_{stamp}.json"
        out.write_text(json.dumps(report.to_dict(), indent=2))
        # Keep a latest symlink/copy for dashboards.
        latest = self.monitors_dir / "monitor_latest.json"
        latest.write_text(json.dumps(report.to_dict(), indent=2))


def self_monitor_and_heal(heal: bool = True) -> dict:
    """Module-level entry point for the daemon / CLI / LLM agent."""
    return AstronacciMonitor().run(heal=heal).to_dict()


if __name__ == "__main__":
    r = self_monitor_and_heal(heal=True)
    print(json.dumps(r, indent=2))
    sys.exit(0 if r["overall"] != "critical" else 1)
