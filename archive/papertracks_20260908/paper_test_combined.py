#!/usr/bin/env python3
"""Gate-2 THIRD track — COMBINED long/short + Pre-Sentiment + Intelligence (READ-ONLY paper).

Runs alongside min-hold + REAL-wide tracks WITHOUT touching them. Own state files.
Paper only — no real orders.

Thesis (user directive): every regime has opportunity. Trade LONG in confirmed bull,
SHORT in confirmed bear. Raw short is weak (PF 1.04) → rescue it with a multi-source
confirmation gate so we only short when market AND coin are truly bearish.

Three complementary signals must AGREE before entry:
  1. PRICE     — v3 momentum (long) / bear-momentum (short)   [timing]
  2. INTEL     — market condition score (hermes /intelligence/current)  [environment]
                 LONG needs score >= 52 ; SHORT needs score <= 48
  3. SENTIMENT — per-coin forecast direction (hermes /prediction/current/SYM)  [direction]
                 must match trade side, but ONLY enforced for coins whose live
                 hit-rate >= 0.55 (BTC/SOL/ETH qualify); else advisory-only.

Geometry: REAL-wide — SL 2% / TP 4% (price), stop from t=0, 3×, 48h time-stop.
Graceful: if hermes unreachable, fall back to price+regime only (still runs, logs it).

Run:    python3 scripts/paper_test_combined.py --loop --interval 300
Status: python3 scripts/paper_test_combined.py --status
Check:  python3 scripts/paper_test_combined.py demo
"""
from __future__ import annotations
import argparse, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
import backtest_swing_gate1_v3 as v3
from research_short_bear import short_signal, long_signal   # reuse validated signals

STATE_FILE = PROJECT / "data" / "paper_test_combined_state.json"
LOG_FILE   = PROJECT / "data" / "paper_test_combined.jsonl"
MON_JSON   = PROJECT / "data" / "paper_test_combined_latest.json"

PAIRS = ["BTC", "SOL", "ETH"]
BN = {"BTC": "BTCUSDT", "SOL": "SOLUSDT", "ETH": "ETHUSDT"}
SPREAD = {"BTC": 0.00013, "ETH": 0.00020, "SOL": 0.00035}
MAKER_FEE = 0.00024

TP_PCT, SL_PCT = 0.040, 0.020
LEVERAGE = 3
TIME_STOP_H, COOLDOWN_H, MAX_TOTAL = 30, 12, 2
NOTIONAL = 100.0

HERMES = "http://127.0.0.1:8000"
# RELAXED (env-tunable): widen intel bands toward neutral so gated tracks fire
# more (data collection). NOT edge — Gate-2 uses strict bands. PAPER_RELAXED=0
# restores strict 52/48. Shared by combined/scs + real-money spot/perps (still
# size-minimal + session-capped).
_RELAXED = os.environ.get("PAPER_RELAXED", "1") == "1"
INTEL_LONG_MIN = float(os.environ.get("PAPER_INTEL_LONG_MIN", "50.5" if _RELAXED else "52.0"))
INTEL_SHORT_MAX = float(os.environ.get("PAPER_INTEL_SHORT_MAX", "49.5" if _RELAXED else "48.0"))
FC_RELIABLE_HR = 0.55     # only enforce forecast for coins with hit-rate >= this
FC_MIN_CONF = float(os.environ.get("PAPER_FC_MIN_CONF", "0.50" if _RELAXED else "0.55"))

# ── ADAPTIVE GATE (closed-loop, 2026-08-14) ──────────────────────────────────
# Membaca data/adaptive_gate.json (ditulis anantara.adaptive_gate_applier) untuk
# menyesuaikan intel bands dari hasil swing deep learner. FAIL-CLOSED:
#   • hanya TIGHTEN dari nilai env/relaxed saat ini — tidak pernah lebih longgar
#   • gate JSON > 30 menit → kedaluwarsa → kembali ke default env.
ADAPTIVE_GATE_FILE = PROJECT / "data" / "adaptive_gate.json"
ADAPTIVE_GATE_TTL  = 1800   # 30 menit
_adaptive_cache = {"ts": 0.0, "long_min": None, "short_max": None}


def effective_intel_gate():
    """Return (long_min, short_max) dengan adaptive override (fail-closed)."""
    now = time.time()
    if now - _adaptive_cache["ts"] > 120:   # refresh cache tiap 2 menit
        _adaptive_cache["long_min"] = None
        _adaptive_cache["short_max"] = None
        try:
            gate = json.loads(ADAPTIVE_GATE_FILE.read_text())
            if time.time() - ADAPTIVE_GATE_FILE.stat().st_mtime <= ADAPTIVE_GATE_TTL:
                lm = gate.get("intel_long_min")
                sm = gate.get("intel_short_max")
                if lm is not None:
                    _adaptive_cache["long_min"] = max(float(lm), INTEL_LONG_MIN)
                if sm is not None:
                    _adaptive_cache["short_max"] = min(float(sm), INTEL_SHORT_MAX)
        except Exception:
            pass   # file tidak ada/corrupt → tetap default
        _adaptive_cache["ts"] = now
    lm = _adaptive_cache["long_min"] if _adaptive_cache["long_min"] is not None else INTEL_LONG_MIN
    sm = _adaptive_cache["short_max"] if _adaptive_cache["short_max"] is not None else INTEL_SHORT_MAX
    return lm, sm


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def fetch_ohlcv(sym, limit=300):
    r = requests.get("https://api.binance.com/api/v3/klines",
                     params={"symbol": sym, "interval": "1h", "limit": limit}, timeout=10)
    k = r.json()
    return {"o": np.array([float(x[1]) for x in k]), "h": np.array([float(x[2]) for x in k]),
            "l": np.array([float(x[3]) for x in k]), "c": np.array([float(x[4]) for x in k]),
            "v": np.array([float(x[5]) for x in k]), "dates": np.array([int(x[0]) for x in k])}


def get_intel():
    """Market condition score. Returns (score, label) or (None, 'unavailable')."""
    try:
        d = requests.get(f"{HERMES}/intelligence/current", timeout=6).json()
        return float(d.get("composite_score", 50.0)), d.get("label", "NEUTRAL")
    except Exception:
        return None, "unavailable"


def get_forecast(sym):
    """Per-coin direction. Returns dict {dir, conf, eligible} or None."""
    try:
        d = requests.get(f"{HERMES}/prediction/current/{sym}", timeout=6).json()
        fc = d.get("forecast", {})
        return {"dir": fc.get("direction"), "conf": float(fc.get("confidence", 0)),
                "eligible": bool(fc.get("trade_eligible", False))}
    except Exception:
        return None


def get_reliable_coins():
    """Coins with PROVEN directional SKILL (hit_rate - base_rate), not raw hit_rate.
    Audit 2026-08-21: raw hit_rate was a base-rate illusion (UP-bias + bull sample →
    BTC 100% hit but 0% skill). A coin gates the forecast direction ONLY if it beats
    its own drift baseline by >=5% with n>=20. Currently that's nobody → the
    Pre-Sentiment gate correctly abstains instead of enforcing a skill-less signal."""
    try:
        d = requests.get(f"{HERMES}/prediction/accuracy", timeout=6).json()
        per = d.get("per_symbol", {})
        # single source of truth = the significance-gated `reliable` flag
        # (skill > 1.96·SE, n>=20). No point-estimate fallback (that re-let OP in).
        return {s for s, v in per.items() if v.get("reliable")}
    except Exception:
        return set()


def gate(side, sym, intel_score, fc, reliable):
    """Return (ok: bool, reason: str). side = 'L' or 'S'."""
    long_min, short_max = effective_intel_gate()   # adaptive override (fail-closed)
    # INTEL gate (environment). If unavailable → skip intel gate (graceful).
    if intel_score is not None:
        if side == "L" and intel_score < long_min:
            return False, f"intel {intel_score:.0f}<{long_min:.1f} (not risk-on)"
        if side == "S" and intel_score > short_max:
            return False, f"intel {intel_score:.0f}>{short_max:.1f} (not risk-off)"
    # SENTIMENT gate (direction). Enforce only for reliable coins.
    if sym in reliable and fc and fc["dir"]:
        want = "UP" if side == "L" else "DOWN"
        if fc["dir"] != want:
            return False, f"forecast {fc['dir']}≠{want}"
        if fc["conf"] < FC_MIN_CONF:
            return False, f"forecast conf {fc['conf']:.2f}<{FC_MIN_CONF}"
    return True, "confirmed"


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"open": {}, "closed": [], "last_entry": {}, "created": now_iso()}


def save_state(st):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1)); tmp.replace(STATE_FILE)


# ── EDGE-GATE AGREGAT (2026-08-11): skip arah yg agregat anti-predictive (n>=8)
GATE_FILE = PROJECT / "data" / "paper_test_edge_gate.json"
_gate_cache = {"ts": 0.0, "data": {}}


def direction_gate_blocks(label, direction):
    now = time.time()
    if now - _gate_cache["ts"] > 60:
        try:
            _gate_cache["data"] = json.loads(GATE_FILE.read_text())
            _gate_cache["ts"] = now
        except Exception:
            _gate_cache["data"] = {}
    data = _gate_cache["data"]
    # Staleness guard: a frozen gate (writer down) must NOT permanently block a
    # paper track. >90min stale -> fail-OPEN. Fixes silent-freeze from dead writer.
    try:
        if time.time() - GATE_FILE.stat().st_mtime > 5400:
            return False
    except Exception:
        return False
    # _STANDBY (blanket flapping-block) is advisory for PAPER data collection:
    # flapping is exactly when we want samples. Keep only the surgical, evidence-
    # based per-direction PAUSE (anti-predictive, n>=8).
    g = (data.get("gate") or {}).get(label) or {}
    agg = data.get("_AGGREGATE") or {}
    return g.get(direction) == "PAUSE" or agg.get(direction) == "PAUSE"


def cycle(st, dry=False):
    hits = []
    intel_score, intel_label = get_intel()
    reliable = get_reliable_coins()
    for p in PAIRS:
        try:
            d = fetch_ohlcv(BN[p])
        except Exception:
            hits.append(f"{p}:fetch_err"); continue
        px = float(d["c"][-1]); cost = MAKER_FEE + SPREAD.get(p, 0.0035)

        # manage open
        if p in st["open"]:
            t = st["open"][p]
            hold_h = (time.time() - t["entry_ts"]) / 3600.0
            side = 1 if t["side"] == "L" else -1
            g = side * (px - t["entry_p"]) / t["entry_p"]
            reason = None
            if g >= TP_PCT: reason = "TP"
            elif g <= -SL_PCT: reason = "SL"        # stop from t=0 (no min-hold)
            elif hold_h >= TIME_STOP_H: reason = "TIME_30h"
            if reason:
                pnl = g - cost
                rec = {**t, "exit_p": px, "exit_iso": now_iso(), "exit_r": reason,
                       "pnl_pct": pnl, "pnl_usd": pnl * NOTIONAL * LEVERAGE, "hold_h": round(hold_h, 1)}
                if not dry:
                    st["closed"].append(rec); del st["open"][p]; st["last_entry"][p] = time.time()
                    with open(LOG_FILE, "a") as f: f.write(json.dumps(rec) + "\n")
                hits.append(f"{p}:CLOSE {t['side']} {reason} {pnl*100:+.2f}%")
                continue
            hits.append(f"{p}:HOLD {t['side']} {g*100:+.2f}% {hold_h:.0f}h"); continue

        # entry search
        if len(st["open"]) >= MAX_TOTAL:
            continue
        if (time.time() - st["last_entry"].get(p, 0)) / 3600.0 < COOLDOWN_H:
            continue
        i = len(d["c"]) - 2   # last CLOSED bar
        side = "L" if long_signal(d, i) else ("S" if short_signal(d, i) else None)
        if not side:
            continue
        if direction_gate_blocks("COMBINED", "LONG" if side == "L" else "SHORT"):
            hits.append(f"{p}:{side}-AGG-GATED"); continue   # agregat PAUSE → skip
        fc = get_forecast(p)
        ok, why = gate(side, p, intel_score, fc, reliable)
        if not ok:
            hits.append(f"{p}:{side}-BLOCK {why}"); continue
        t = {"sym": p, "side": side, "entry_p": px, "entry_ts": time.time(),
             "entry_iso": now_iso(), "intel": intel_score, "intel_label": intel_label,
             "fc_dir": (fc or {}).get("dir"), "reason": why}
        if not dry:
            st["open"][p] = t
        hits.append(f"{p}:ENTRY {side} @{px} ({why}, intel={intel_score})")
    return hits


def status(st):
    c = st["closed"]
    intel_score, intel_label = get_intel()
    if not c:
        print(f"COMBINED track — open={len(st['open'])} closed=0 · market intel={intel_score} ({intel_label})")
        return
    wins = sum(1 for t in c if t["pnl_pct"] > 0)
    longs = [t for t in c if t["side"] == "L"]; shorts = [t for t in c if t["side"] == "S"]
    gp = sum(t["pnl_pct"] for t in c if t["pnl_pct"] > 0)
    gl = -sum(t["pnl_pct"] for t in c if t["pnl_pct"] <= 0)
    pf = gp / gl if gl > 0 else float("inf")
    tot = sum(t["pnl_usd"] for t in c)
    print(f"COMBINED (long+short, intel+sentiment-gated, {LEVERAGE}×)")
    print(f"  n={len(c)} WR={100*wins/len(c):.0f}% PF={pf:.2f} net=${tot:+.2f} "
          f"| L={len(longs)} S={len(shorts)} | open={len(st['open'])} | market={intel_label}")
    MON_JSON.write_text(json.dumps({"n": len(c), "wr": wins/len(c), "pf": pf, "net_usd": tot,
                                    "n_long": len(longs), "n_short": len(shorts),
                                    "open": len(st["open"]), "ts": now_iso()}, indent=1))


def demo():
    # gate logic must block mismatches and pass confirmations.
    rel = {"SOL"}
    ok, _ = gate("L", "SOL", 60.0, {"dir": "UP", "conf": 0.7, "eligible": True}, rel)
    assert ok, "confirmed long blocked"
    ok, _ = gate("L", "SOL", 40.0, {"dir": "UP", "conf": 0.7}, rel)
    assert not ok, "long allowed in risk-off market"
    ok, _ = gate("S", "SOL", 40.0, {"dir": "DOWN", "conf": 0.7}, rel)
    assert ok, "confirmed short blocked"
    ok, _ = gate("S", "SOL", 40.0, {"dir": "UP", "conf": 0.7}, rel)
    assert not ok, "short allowed against UP forecast"
    ok, _ = gate("S", "XYZ", 40.0, {"dir": "UP", "conf": 0.7}, rel)  # unreliable coin
    assert ok, "forecast wrongly enforced on unreliable coin"
    ok, _ = gate("L", "SOL", None, None, rel)   # intel unavailable → graceful pass
    assert ok, "graceful fallback broken"
    assert "combined" in STATE_FILE.name
    print("demo OK — gate blocks mismatches, passes confirmations, graceful fallback works")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="once")
    ap.add_argument("--loop", action="store_true"); ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--status", action="store_true"); ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.cmd == "demo":
        demo(); return
    st = load_state()
    if a.status:
        status(st); return
    if a.loop:
        while True:
            hits = cycle(st, dry=a.dry)
            if not a.dry: save_state(st)
            print(f"[{now_iso()}] {' | '.join(hits) or 'no action'}")
            time.sleep(a.interval)
    else:
        hits = cycle(st, dry=a.dry)
        if not a.dry: save_state(st)
        print(f"[{now_iso()}] {' | '.join(hits) or 'no action'}"); status(st)


if __name__ == "__main__":
    main()
