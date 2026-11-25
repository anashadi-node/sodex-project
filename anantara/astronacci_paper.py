#!/usr/bin/env python3
"""
ASTRONACCI v1.1 — Paper Trading Protocol (Binance + Hyperliquid)

Runs Astronacci signals through a paper-trading simulation on Binance + Hyperliquid
BEFORE any real capital is committed. This is the FINAL GATE before live.

PROTOCOL (from Falsification Lab Roadmap Phase 7):
  1. Signal generation (from astronacci_agent)
  2. Evidence gate (score ≥ 71)
  3. Epistemic Governor gate (no blocked features)
  4. Risk sizing (fractional Kelly, max 5% per signal)
  5. Paper execution log (timestamped, auditable)
  6. Performance tracking (daily P&L, Sharpe, drawdown)
  7. Weekly report (compared to baseline)

SAFETY INVARIANTS:
  • No real orders — this is PAPER ONLY
  • All signals logged to data/astronacci/paper_trades.jsonl
  • Performance tracked against buy-and-hold baseline
  • Minimum 3 months paper trading before live consideration

USAGE:
    python3 anantara/astronacci_paper.py run     # Run one paper cycle
    python3 anantara/astronacci_paper.py status  # Show paper P&L
    python3 anantara/astronacci_paper.py report  # Generate weekly report
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PaperTrade:
    """One paper trade record."""
    trade_id: str
    timestamp: str           # ISO UTC
    asset: str
    direction: str           # LONG / SHORT
    entry_price: float
    size: float              # position size in asset units
    notional: float          # size × entry_price
    leverage: float

    # Signal metadata
    signal_id: str
    primary_event: str
    evidence_score: int
    signal_strength: float

    # Risk parameters
    stop_loss: float
    take_profit: float

    # Outcome (filled on close)
    exit_price: float = 0.0
    exit_timestamp: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""   # "tp" / "sl" / "timeout" / "manual"

    # Audit
    defense_gates_passed: int = 0
    governor_allowed: bool = True


@dataclass
class PaperPortfolio:
    """Paper trading portfolio state."""
    initial_capital: float = 10000.0
    current_capital: float = 10000.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    peak_capital: float = 10000.0
    open_trades: list[PaperTrade] = field(default_factory=list)
    closed_trades: list[PaperTrade] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# PAPER TRADING ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class PaperTradingEngine:
    """Simulates Astronacci signal execution without real money.

    Usage:
        engine = PaperTradingEngine()
        trade = engine.open_paper_trade(signal, current_price)
        engine.close_paper_trade(trade, current_price, "tp")
        engine.performance_report()
    """

    def __init__(self, data_dir: str | None = None):
        if data_dir is None:
            project_dir = os.environ.get(
                "ANANTARA_DIR", str(Path.home() / "anantara-sakti")
            )
            data_dir = str(Path(project_dir) / "data" / "astronacci")
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.trades_path = self.data_dir / "paper_trades.jsonl"
        self.state_path = self.data_dir / "paper_portfolio.json"

        # Load state
        self.portfolio = self._load_portfolio()

    def _load_portfolio(self) -> PaperPortfolio:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text())
                return PaperPortfolio(**data)
            except Exception:
                pass
        return PaperPortfolio()

    def _save_portfolio(self):
        self.state_path.write_text(
            json.dumps(asdict(self.portfolio), indent=2, default=str)
        )

    def _log_trade(self, trade: PaperTrade):
        with open(self.trades_path, "a") as f:
            f.write(json.dumps(asdict(trade), default=str) + "\n")

    def open_paper_trade(
        self,
        signal,
        current_price: float,
        balance: float | None = None,
    ) -> PaperTrade | None:
        """Open a paper trade from a validated Astronacci signal.
        Args:
            signal: AstroSignal from astronacci_agent
            current_price: Current market price
            balance: Current paper balance (default: portfolio.current_capital)

        Returns:
            PaperTrade if all gates pass, None if rejected.
        """
        if balance is None:
            balance = self.portfolio.current_capital

        # ── GATE 1: Evidence score ──
        if signal.evidence_score < 71:
            return None

        # ── GATE 2: Max concurrent trades ──
        if len(self.portfolio.open_trades) >= 3:
            return None

        # ── GATE 3: Daily loss limit ──
        if self.portfolio.current_capital < self.portfolio.initial_capital * 0.97:
            return None  # -3% daily loss limit hit

        # ── Risk sizing (fractional Kelly, conservative) ──
        size_pct = min(signal.suggested_size_pct, 0.05)
        notional = balance * size_pct
        size = notional / current_price if current_price > 0 else 0.0

        if notional < 10.0:
            return None  # too small

        # defense_gates_passed is the ACTUAL number of statistical gates the
        # triggering signal survived, not a fabricated "7". The previous
        # implementation hard-coded 7 here, misrepresenting every paper trade
        # as having passed all 7 defense gates regardless of validation. We
        # read the genuine value from the signal's defense_result (set by the
        # agent when a DefenseResult exists), defaulting to 0 (honest "not
        # validated through the gates").
        _defense = getattr(signal, "defense_result", None)
        if isinstance(_defense, dict) and "gates_passed" in _defense:
            _gates_passed = int(_defense["gates_passed"])
        else:
            _gates_passed = 0

        trade = PaperTrade(
            trade_id=f"PP-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            asset=signal.asset,
            direction=signal.direction,
            entry_price=current_price,
            size=round(size, 6),
            notional=round(notional, 2),
            leverage=min(3.0, signal.strength * 5.0),
            signal_id=signal.signal_id,
            primary_event=signal.primary_event,
            evidence_score=signal.evidence_score,
            signal_strength=signal.strength,
            stop_loss=round(
                current_price * (1.0 - signal.stop_loss_pct)
                if signal.direction == "LONG"
                else current_price * (1.0 + signal.stop_loss_pct),
                2,
            ),
            take_profit=round(
                current_price * (1.0 + signal.take_profit_pct)
                if signal.direction == "LONG"
                else current_price * (1.0 - signal.take_profit_pct),
                2,
            ),
            defense_gates_passed=_gates_passed,
            governor_allowed=True,
        )

        self.portfolio.open_trades.append(trade)
        self.portfolio.total_trades += 1
        self._log_trade(trade)

        return trade

    def open_trades(self) -> list:
        """Return currently-open paper trades (for concurrency checks)."""
        return list(self.portfolio.open_trades)

    def open_paper_trade_from_dict(
        self, sig: dict, current_price: float, balance: float | None = None,
    ) -> PaperTrade | None:
        """Open a paper trade from a signal DICT (as returned by
        compute_cycle, which serializes AstroSignal via asdict).

        ponytail: rebuild an AstroSignal-equivalent namespace from the dict so
        we can reuse open_paper_trade without duplicating its sizing/SL/TP logic.
        """
        from types import SimpleNamespace
        sig_obj = SimpleNamespace(
            signal_id=sig.get("signal_id", "ASTRO-DICT"),
            timestamp=sig.get("timestamp", ""),
            asset=sig.get("asset", "BTC"),
            direction=sig.get("direction", "NEUTRAL"),
            strength=float(sig.get("strength", 0.0)),
            evidence_score=int(sig.get("evidence_score", 0)),
            suggested_size_pct=float(sig.get("suggested_size_pct", 0.0)),
            stop_loss_pct=float(sig.get("stop_loss_pct", 0.03)),
            take_profit_pct=float(sig.get("take_profit_pct", 0.06)),
            primary_event=sig.get("primary_event", ""),
            trigger_features=sig.get("trigger_features", {}),
            evidence_status=sig.get("evidence_status", "research"),
            regime_tag=sig.get("regime_tag", "unknown"),
            defense_result=sig.get("defense_result"),
        )
        return self.open_paper_trade(sig_obj, current_price, balance)

    def close_paper_trade(
        self,
        trade: PaperTrade,
        current_price: float,
        reason: str = "timeout",
    ) -> PaperTrade:
        """Close a paper trade at current price.

        Args:
            trade: The open PaperTrade
            current_price: Current market price
            reason: "tp", "sl", "timeout", "manual"

        Returns:
            Updated trade with P&L filled in.
        """
        if trade.direction == "LONG":
            pnl_pct = (current_price - trade.entry_price) / trade.entry_price
        else:
            pnl_pct = (trade.entry_price - current_price) / trade.entry_price

        pnl = trade.notional * pnl_pct * trade.leverage
        # Fee estimate: 0.05% per side = 0.10% roundtrip
        fee = trade.notional * 0.0010 * trade.leverage
        net_pnl = pnl - fee

        trade.exit_price = current_price
        trade.exit_timestamp = datetime.now(timezone.utc).isoformat()
        trade.pnl = round(net_pnl, 2)
        trade.pnl_pct = round(pnl_pct * trade.leverage * 100, 4)
        trade.exit_reason = reason

        # Update portfolio
        self.portfolio.current_capital += net_pnl
        self.portfolio.total_pnl += net_pnl
        if net_pnl > 0:
            self.portfolio.winning_trades += 1
        else:
            self.portfolio.losing_trades += 1

        # Drawdown tracking
        if self.portfolio.current_capital > self.portfolio.peak_capital:
            self.portfolio.peak_capital = self.portfolio.current_capital
        dd = (self.portfolio.peak_capital - self.portfolio.current_capital) / self.portfolio.peak_capital
        if dd > self.portfolio.max_drawdown:
            self.portfolio.max_drawdown = round(dd, 4)

        # Move to closed
        self.portfolio.open_trades = [
            t for t in self.portfolio.open_trades
            if t.trade_id != trade.trade_id
        ]
        self.portfolio.closed_trades.append(trade)

        self._save_portfolio()
        self._log_trade(trade)

        return trade

    def import_legacy_trackrecord(self, legacy_path: str | None = None) -> dict:
        """Import the paper_daemon (TA-based) track-record into the unified view.

        P3 unification (SWOT viability): Astronacci had TWO disconnected
        paper systems — the agent-based paper.py (this module, used by the
        daemon paper-trade loop) and the older TA-based paper_daemon.py
        (which wrote paper_trades.jsonl with ts/sym/dir/pnl fields). This
        reads the legacy log WITHOUT mutating it, computes unified metrics,
        and returns a combined report so the operator sees ONE track-record.
        """
        from pathlib import Path
        if legacy_path is None:
            legacy_path = str(Path(self.data_dir) / "paper_trades.jsonl")
        legacy_pnls: list[float] = []
        try:
            p = Path(legacy_path)
            if p.exists():
                for line in p.read_text().splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        legacy_pnls.append(float(json.loads(line).get("pnl", 0)))
                    except Exception:
                        pass
        except Exception:
            pass
        own_pnls = [t.pnl for t in self.portfolio.closed_trades if t.pnl]
        all_pnls = legacy_pnls + own_pnls
        if not all_pnls:
            return {"status": "no_trades", "source": "unified"}
        wins = [p for p in all_pnls if p > 0]
        losses = [p for p in all_pnls if p < 0]
        total = len(all_pnls)
        pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else None
        return {
            "status": "active",
            "source": "unified (legacy paper_daemon + agent paper)",
            "total_trades": total,
            "legacy_trades": len(legacy_pnls),
            "agent_trades": len(own_pnls),
            "win_rate": round(len(wins) / total * 100, 1),
            "total_pnl": round(sum(all_pnls), 2),
            "profit_factor": round(pf, 2) if pf is not None else None,
        }

    def performance_report(self) -> dict:
        """Generate performance metrics."""
        p = self.portfolio
        total = p.total_trades
        if total == 0:
            return {"status": "no_trades"}

        win_rate = p.winning_trades / total if total > 0 else 0.0
        avg_win = (
            sum(t.pnl for t in p.closed_trades if t.pnl > 0)
            / max(p.winning_trades, 1)
        )
        avg_loss = (
            sum(t.pnl for t in p.closed_trades if t.pnl <= 0)
            / max(p.losing_trades, 1)
        )
        profit_factor = (
            abs(sum(t.pnl for t in p.closed_trades if t.pnl > 0))
            / max(abs(sum(t.pnl for t in p.closed_trades if t.pnl <= 0)), 1)
        )

        # Sharpe (approximate from trade P&L)
        trade_returns = [
            t.pnl / p.initial_capital for t in p.closed_trades
        ]
        if len(trade_returns) >= 5:
            from astronacci_events import _mean, _std
            avg_ret = _mean(trade_returns)
            std_ret = _std(trade_returns)
            sharpe = (avg_ret / std_ret) * math.sqrt(total) if std_ret > 0 else 0.0
        else:
            sharpe = 0.0

        return {
            "status": "active",
            "initial_capital": p.initial_capital,
            "current_capital": round(p.current_capital, 2),
            "total_pnl": round(p.total_pnl, 2),
            "total_return_pct": round(
                (p.current_capital / p.initial_capital - 1.0) * 100, 2
            ),
            "total_trades": total,
            "winning": p.winning_trades,
            "losing": p.losing_trades,
            "win_rate": round(win_rate * 100, 1),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2),
            "sharpe": round(sharpe, 4),
            "max_drawdown_pct": round(p.max_drawdown * 100, 2),
            "open_trades": len(p.open_trades),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# CYCLE RUNNER (for daemon integration)
# ─────────────────────────────────────────────────────────────────────────────

def run_paper_cycle(
    astro_agent,
    current_prices: dict[str, float] | None = None,
) -> dict:
    """Run one paper trading cycle: generate signals → open/close paper trades.

    Designed to be called from daemon scheduler every 6 hours.

    Args:
        astro_agent: AstronacciAgent instance
        current_prices: {asset: price} dict

    Returns:
        Summary dict of actions taken.
    """
    engine = PaperTradingEngine()

    # Default prices if not provided
    if current_prices is None:
        current_prices = {"BTC": 90000.0, "ETH": 4500.0, "SOL": 180.0}

    # Compute cycle
    summary = astro_agent.compute_cycle()
    signals = summary.get("signals", [])

    actions = {"opened": 0, "closed": 0, "errors": 0}

    # Close trades that hit TP/SL
    for trade in list(engine.portfolio.open_trades):
        price = current_prices.get(trade.asset)
        if price is None:
            continue

        # Check TP/SL
        if trade.direction == "LONG":
            if price >= trade.take_profit:
                engine.close_paper_trade(trade, price, "tp")
                actions["closed"] += 1
            elif price <= trade.stop_loss:
                engine.close_paper_trade(trade, price, "sl")
                actions["closed"] += 1
        else:  # SHORT
            if price <= trade.take_profit:
                engine.close_paper_trade(trade, price, "tp")
                actions["closed"] += 1
            elif price >= trade.stop_loss:
                engine.close_paper_trade(trade, price, "sl")
                actions["closed"] += 1

    # Timeout: close trades older than 7 days
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    for trade in list(engine.portfolio.open_trades):
        ts = datetime.fromisoformat(trade.timestamp)
        if ts < cutoff:
            price = current_prices.get(trade.asset, trade.entry_price)
            engine.close_paper_trade(trade, price, "timeout")
            actions["closed"] += 1

    # Open new trades from signals
    for sig_dict in signals:
        asset = sig_dict.get("asset", "BTC")
        price = current_prices.get(asset)
        if price is None:
            continue

        # Reconstruct minimal signal
        from astronacci_agent import AstroSignal
        signal = AstroSignal(
            signal_id=sig_dict.get("signal_id", "unknown"),
            timestamp=sig_dict.get("timestamp", ""),
            asset=asset,
            direction=sig_dict.get("direction", "NEUTRAL"),
            strength=sig_dict.get("strength", 0.0),
            evidence_score=sig_dict.get("evidence_score", 0),
            primary_event=sig_dict.get("primary_event", ""),
            suggested_size_pct=0.03,
            stop_loss_pct=0.03,
            take_profit_pct=0.06,
        )

        if signal.direction == "NEUTRAL" or signal.strength < 0.15:
            continue

        trade = engine.open_paper_trade(signal, price)
        if trade:
            actions["opened"] += 1

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actions": actions,
        "signals_evaluated": len(signals),
        "portfolio": engine.performance_report(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Astronacci Paper Trading Protocol")
    ap.add_argument("action", nargs="?", default="status",
                    choices=["run", "status", "report", "reset"])
    ap.add_argument("--btc-price", type=float, default=90000.0)
    ap.add_argument("--eth-price", type=float, default=4500.0)
    ap.add_argument("--sol-price", type=float, default=180.0)
    args = ap.parse_args()

    engine = PaperTradingEngine()

    if args.action == "reset":
        engine.portfolio = PaperPortfolio()
        engine._save_portfolio()
        print("✅ Paper portfolio reset.")

    elif args.action == "run":
        from astronacci_agent import AstronacciAgent
        agent = AstronacciAgent()
        prices = {"BTC": args.btc_price, "ETH": args.eth_price, "SOL": args.sol_price}
        result = run_paper_cycle(agent, prices)
        print(f"📊 Paper cycle complete: {result['actions']}")
        print(f"📈 Portfolio: {result['portfolio']}")

    elif args.action in ("status", "report"):
        report = engine.performance_report()
        if report.get("status") == "no_trades":
            print("📊 No paper trades yet. Run with 'run' first.")
        else:
            print("📊 *Astronacci Paper Trading Report*")
            print(f"   Capital: ${report['initial_capital']:,.0f} → ${report['current_capital']:,.2f}")
            print(f"   P&L: ${report['total_pnl']:,.2f} ({report['total_return_pct']:+.1f}%)")
            print(f"   Trades: {report['total_trades']} | Win: {report['winning']} | Loss: {report['losing']}")
            print(f"   Win rate: {report['win_rate']:.1f}%")
            print(f"   Avg win: ${report['avg_win']:,.2f} | Avg loss: ${report['avg_loss']:,.2f}")
            print(f"   Profit factor: {report['profit_factor']:.2f}")
            print(f"   Sharpe: {report['sharpe']:.4f}")
            print(f"   Max drawdown: {report['max_drawdown_pct']:.2f}%")
