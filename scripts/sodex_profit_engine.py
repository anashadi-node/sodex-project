#!/usr/bin/env python3
"""SoDEX Profit Engine — single decision authority that unifies every method.

The mission target: maximize expected value per trade. Since 5+ audits + a
713-sample test prove NO directional-prediction edge exists to buy, EV is
maximized structurally, not by guessing direction. Every candidate trade must
pass ONE gate that stacks all proven levers:

  1. REGIME    (regime_gate)      — trade only WITH a confirmed multi-day trend.
  2. PORTFOLIO — max 3 positions, correlation cap, daily-loss halt (DeepSeek +
                 our research: concentration > diversification; bag-holding kills).
  3. SIZING    (asymmetric_sizing)— risk 1%/trade, R:R >= 3 so 40% WR is still +EV,
                 mandatory stop-loss, leverage <= 5x.
  4. NEUTRAL   — if no directional trade qualifies (usual case), route to
                 delta-neutral funding harvest (the only proven +EV).

This is the collaboration the mission asks for: perp / spot / neutral all decided
by one engine. profit-first + honesty: it does NOT promise profit every trade —
it refuses negative-EV trades and only fires structurally-favorable ones.
Paper-only; deploys no capital.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from regime_gate import Regime, gate, CRYPTO_MAJORS  # noqa: E402
from asymmetric_sizing import plan, expectancy  # noqa: E402

# ── portfolio policy (DeepSeek-validated + our research) ─────────────────────
MAX_POSITIONS = 3        # concentration beats diversification (audit finding)
MAX_CORRELATED = 1       # max same-direction crypto-major bets (the 0/4 lesson)
DAILY_LOSS_HALT = -0.06  # halt new entries if account down 6% today
MIN_RR = 3.0             # asymmetry floor: 40% WR × 3R = +0.6R
ASSUMED_WR = 0.42        # honest prior for regime-confirmed entry (no edge > this)


@dataclass
class Decision:
    action: str          # ENTER | REFUSE | NEUTRAL
    symbol: str
    direction: str
    reason: str
    plan: dict | None = None
    expectancy_r: float = 0.0


def _open_positions(paper_path: Path):
    try:
        return [t for t in json.loads(paper_path.read_text())["trades"]
                if t["status"] == "open"]
    except FileNotFoundError:
        return []                       # no file yet = genuinely 0 positions
    except Exception:
        return None                     # corrupt/unreadable = cannot verify → fail-closed


def evaluate(symbol: str, direction: str, entry: float, atr: float,
             account_usd: float, regime: Regime, obi_pct: float,
             spread_bps: float, tf_score: int,
             daily_pnl_frac: float = 0.0,
             paper_path: Path | None = None) -> Decision:
    """Run a candidate through every gate. Return one authoritative Decision."""
    direction = direction.upper()
    paper_path = paper_path or (Path(__file__).resolve().parent.parent / "data" / "paper_trades.json")
    openp = _open_positions(paper_path)
    if openp is None:                   # unreadable state → fail-closed, don't add risk
        return Decision("REFUSE", symbol, direction,
                        "cannot read positions state (corrupt) — fail-closed")

    # ── PORTFOLIO GATES (cheap, first) ──────────────────────────────────────
    if daily_pnl_frac <= DAILY_LOSS_HALT:
        return Decision("REFUSE", symbol, direction,
                        f"daily loss {daily_pnl_frac*100:.1f}% <= halt {DAILY_LOSS_HALT*100:.0f}%")
    if len(openp) >= MAX_POSITIONS:
        return Decision("REFUSE", symbol, direction,
                        f"max {MAX_POSITIONS} positions open (concentration policy)")
    if any(p["symbol"] == symbol for p in openp):
        return Decision("REFUSE", symbol, direction, f"already have {symbol} position")
    corr = sum(1 for p in openp
               if p["symbol"] in CRYPTO_MAJORS and p["direction"].upper() == direction)

    # ── REGIME + FLOW + COST GATE ───────────────────────────────────────────
    g = gate(direction, regime, obi_pct, spread_bps, tf_score, corr)
    if g.decision == "NEUTRAL_ONLY":
        return Decision("NEUTRAL", symbol, direction,
                        f"regime {regime.label} → no directional edge; route funding-neutral")
    if g.decision != "ALLOW":
        return Decision("REFUSE", symbol, direction, g.reasons[0] if g.reasons else "gate refuse")

    # ── ASYMMETRIC SIZING (mandatory SL, R:R >= MIN_RR) ─────────────────────
    tp = plan(symbol, direction, entry, atr, account_usd, regime)
    if tp is None:
        return Decision("REFUSE", symbol, direction, "no sizing plan (regime/atr)")
    if tp.rr < MIN_RR - 1e-9:
        return Decision("REFUSE", symbol, direction,
                        f"R:R {tp.rr:.2f} < floor {MIN_RR} (asymmetry insufficient)")

    ev = expectancy(ASSUMED_WR, tp.rr)
    if ev <= 0:
        return Decision("REFUSE", symbol, direction, f"EV {ev:+.2f}R <= 0 at prior WR {ASSUMED_WR}")

    return Decision("ENTER", symbol, direction,
                    f"regime-confirmed {direction}; gate score {g.score}; "
                    f"R:R {tp.rr:.1f}; EV {ev:+.2f}R @ {ASSUMED_WR:.0%} prior",
                    plan=asdict(tp), expectancy_r=round(ev, 3))


def demo():
    from regime_gate import classify
    acct = 1000.0
    bear = classify("SOL-USD", 74.0, -12.0, False)   # confirmed BEAR
    rang = classify("SOL-USD", 74.0, 0.5, True)       # RANGING
    fresh = Path("/tmp/_pe_empty.json")
    fresh.write_text(json.dumps({"trades": []}))

    # ranging → NEUTRAL (route funding), never ENTER
    d = evaluate("SOL-USD", "SHORT", 74.0, 1.5, acct, rang, -30, 0.5, -4, 0.0, fresh)
    assert d.action == "NEUTRAL", d

    # confirmed bear + flow + no stack → ENTER with +EV and a full plan
    d = evaluate("SOL-USD", "SHORT", 74.0, 1.5, acct, bear, -30, 0.5, -4, 0.0, fresh)
    assert d.action == "ENTER" and d.expectancy_r > 0 and d.plan, d
    assert d.plan["rr"] >= MIN_RR and d.plan["risk_usd"] <= acct * 0.011

    # daily-loss halt blocks everything
    d = evaluate("SOL-USD", "SHORT", 74.0, 1.5, acct, bear, -30, 0.5, -4, -0.07, fresh)
    assert d.action == "REFUSE" and "halt" in d.reason, d

    # max-positions: 3 open → refuse
    full = Path("/tmp/_pe_full.json")
    full.write_text(json.dumps({"trades": [
        {"symbol": s, "direction": "LONG", "status": "open"} for s in ("A", "B", "C")]}))
    d = evaluate("SOL-USD", "SHORT", 74.0, 1.5, acct, bear, -30, 0.5, -4, 0.0, full)
    assert d.action == "REFUSE" and "max" in d.reason, d

    # correlation cap: 1 crypto-major SHORT open → 2nd refused by gate
    one = Path("/tmp/_pe_one.json")
    one.write_text(json.dumps({"trades": [
        {"symbol": "BTC-USD", "direction": "SHORT", "status": "open"}]}))
    d = evaluate("ETH-USD", "SHORT", 1900, 40, acct,
                 classify("ETH-USD", 1900, -12, False), -30, 0.5, -4, 0.0, one)
    assert d.action == "REFUSE" and "correlation" in d.reason.lower(), d

    # corrupt positions file → fail-CLOSED (REFUSE), never fail-open to ENTER
    bad = Path("/tmp/_pe_bad.json")
    bad.write_text("{corrupt")
    d = evaluate("SOL-USD", "SHORT", 74.0, 1.5, acct, bear, -30, 0.5, -4, 0.0, bad)
    assert d.action == "REFUSE" and "fail-closed" in d.reason, d

    print("demo OK — ranging→NEUTRAL, bear→ENTER(+EV+plan), loss-halt, max-pos, corr-cap, "
          "fail-closed all enforced")


if __name__ == "__main__":
    demo() if len(sys.argv) > 1 and sys.argv[1] == "demo" else print(__doc__)
