#!/usr/bin/env python3
"""
ANANTARA SAKTI — CEX SPOT Deep Loop Learning (v1.0, 2026-08-17)

Sibling of cex_deep_loop.py, but for the Binance **SPOT** swing paper test
(scripts/paper_test_spot_swing_cex.py). Closes the gap the futures deep-loop
never covered: the spot LONG-only swing track (1-30h, target >=0.7%/trade) now
has its own autonomous learn-experience loop.

WHAT IT LEARNS (per COIN + per ENTRY-PATH, from the test's own CLOSED trades)
  1. Per-coin expectancy on the SIGNAL track (momentum+ADX LONG).
  2. Which coins are PROVEN-LOSING -> auto-veto (the strategy skips them).
  3. Which coins are PROVEN-STRONG  -> boost flag (priority).
  4. SIGNAL-vs-RANDOM alpha: does the model actually beat a coin-flip? (report)

v1.1 (2026-08-25) — PATH-LEVEL LEARNING (audit finding: per-coin learning was
  blind to direction/path quality). Durable log proves: regime-short E=+1.86%,
  momentum paths E=+2.21% vs regime-long E=+0.37% (below the 0.7% target).
  The learner now ALSO groups by entry_signal path and applies the same
  3-confirmation veto / boost rules at path level. The paper test consumes
  path vetoes to skip weak entry paths and boosts to prioritise strong ones.
  Same falsification-first rigour; fails open; RANDOM never touched.

SCIENTIFIC RIGOUR (falsification-first, per project doctrine)
  - A veto needs THREE independent confirmations, not just a negative average:
      (a) enough sample (n >= _VETO_MIN_N),
      (b) negative expectancy AND destructive profit-factor (PF < _VETO_MAX_PF),
      (c) bootstrap P(E>0) < 0.5  (the profit is not merely bad luck of sign).
    Requiring all three keeps the false-veto rate low.
  - A boost needs n >= _BOOST_MIN_N, expectancy >= _BOOST_MIN_EXP AND
    bootstrap P(E>0) >= _BOOST_MIN_PEPOS (0.90) — the same >=90% confidence bar
    the bootstrap monitor uses for a GO decision.
  - Wilson 95% lower bound on win-rate is reported for transparency.
  - SIGNAL-vs-RANDOM uses a deterministic permutation test (report-only; never a
    trading gate — the control track must never influence live behaviour).
  - Fails OPEN: missing/corrupt state -> zero vetoes (never blocks spuriously).
  - RANDOM track is NEVER vetoed/boosted — it is the scientific control.
  - Read-only on the paper-test state; output is a separate atomic JSON file.

Pure stdlib. Runs via daemon job_cex_spot_deep_loop (daily) + on-demand CLI.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
from datetime import datetime, timezone
from pathlib import Path

try:                                     # dual import: package (tests) or flat (daemon)
    from anantara import cex_target_framework as _tf
except ImportError:                      # pragma: no cover
    import cex_target_framework as _tf

log = logging.getLogger(__name__)

_STATE_FILE = "data/paper_test_spot_swing_cex_spot.json"
_TRADES_LOG = "data/paper_test_spot_swing_cex_spot_trades.jsonl"  # durable source
_LEARNING_FILE = "data/cex_spot_deep_loop.json"
# v1.1: minimum sample before a PATH-level veto/boost is allowed. Paths pool
# trades across all coins, so evidence accumulates faster than per-coin — but
# n>=8 still keeps false vetoes low while reacting sooner.
_PATH_VETO_MIN_N = 8
_PATH_BOOST_MIN_N = 8

# F3 FIX (audit 2026-09-01): only the entry paths the paper test CAN STILL EMIT
# are eligible for path-level veto/boost. Legacy tags ('momentum+adx+regime',
# 'momentum+adx+regime+harbar', 'momentum+adx') are pre-v2.0 tags that
# scripts/paper_test_spot_swing_cex.py no longer produces (it now emits only
# regime-long/regime-short). Boosting a dead tag was the observed defect: the
# learner BOOSTED 'momentum+adx+regime' (E=+2.3%, 100% TP, fixed-barrier era)
# even though no live trade can ever carry that tag again — a permanent stale
# edge signal. Filter to live tags only.
_LIVE_PATHS = frozenset({"spot-ofi-long", "spot-mom-adx"})

# Evidence thresholds ----------------------------------------------------------
_VETO_MIN_N = 5            # min SIGNAL trades on a coin before a veto is allowed
_VETO_MAX_PF = 0.7         # profit-factor below this (+ negative E) = destructive
_VETO_MAX_PEPOS = 0.5      # bootstrap P(E>0) below this confirms real weakness
_BOOST_MIN_N = 5
_BOOST_MIN_EXP = 0.3       # expectancy (%) above this = strong coin
_BOOST_MIN_PEPOS = 0.90    # >=90% bootstrap confidence the coin is profitable
_BOOTSTRAP_B = 2000        # bootstrap resamples (deterministic seed)
_Z95 = 1.959963984540054   # z for 95% two-sided
_ALPHA_P = 0.05            # SIGNAL must beat RANDOM at p<0.05 to claim edge
_ALPHA_MIN_N = 30          # min matched samples per track for a valid verdict


# ── paths ─────────────────────────────────────────────────────────────────────
def _project_dir() -> Path:
    return Path(os.environ.get("ANANTARA_DIR",
                str(Path(__file__).resolve().parent.parent)))


def _state_path() -> Path:
    return _project_dir() / _STATE_FILE


def _learning_path() -> Path:
    return _project_dir() / _LEARNING_FILE


# ── statistics (pure stdlib) ─────────────────────────────────────────────────
def _wilson_lower(wins: int, n: int, z: float = _Z95) -> float:
    """Wilson score 95% lower bound on the win-rate."""
    if n <= 0:
        return 0.0
    p = wins / n
    denom = 1.0 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return max(0.0, (centre - margin) / denom)


def _bootstrap_p_e_positive(pnls: list[float], b: int = _BOOTSTRAP_B,
                            seed: int = 20260817) -> float:
    """Deterministic bootstrap: P(mean resampled expectancy > 0)."""
    n = len(pnls)
    if n == 0:
        return 0.0
    rng = random.Random(seed)
    hits = 0
    for _ in range(b):
        s = 0.0
        for _ in range(n):
            s += pnls[rng.randrange(n)]
        if s > 0:          # mean > 0  <=>  sum > 0
            hits += 1
    return hits / b


def _permutation_alpha(sig: list[float], rnd: list[float],
                       b: int = _BOOTSTRAP_B, seed: int = 424242) -> dict:
    """Two-sided permutation test on mean(SIGNAL) - mean(RANDOM). Report-only."""
    if not sig or not rnd:
        return {"obs_diff_pct": None, "p_value": None, "n_sig": len(sig),
                "n_rnd": len(rnd)}
    obs = (sum(sig) / len(sig) - sum(rnd) / len(rnd)) * 100
    pool = sig + rnd
    n_s = len(sig)
    rng = random.Random(seed)
    ge = 0
    for _ in range(b):
        rng.shuffle(pool)
        a = pool[:n_s]
        c = pool[n_s:]
        diff = (sum(a) / len(a) - sum(c) / len(c)) * 100
        if abs(diff) >= abs(obs):
            ge += 1
    return {"obs_diff_pct": round(obs, 3), "p_value": round(ge / b, 4),
            "n_sig": n_s, "n_rnd": len(rnd)}


def _coin_stats(pnls: list[float]) -> dict:
    """Full scientific stat pack for one coin's pnl fractions."""
    n = len(pnls)
    if n == 0:
        return {"n": 0, "wr": 0.0, "wr_wilson_lo": 0.0, "expectancy": 0.0,
                "net_pct": 0.0, "pf": 0.0, "p_e_pos": 0.0}
    wins = sum(1 for p in pnls if p > 0)
    gw = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0))
    return {
        "n": n,
        "wr": round(wins / n, 3),
        "wr_wilson_lo": round(_wilson_lower(wins, n), 3),
        "expectancy": round(sum(pnls) / n * 100, 3),
        "net_pct": round(sum(pnls) * 100, 3),
        "pf": round(gw / gl, 3) if gl > 0 else 0.0,
        "p_e_pos": round(_bootstrap_p_e_positive(pnls), 3),
    }

# ── v1.1 path-level grouping ───────────────────────────────────────────────
def _closed_by_path(state: dict | None, from_log: dict | None = None) -> dict[str, list[float]]:
    """Group CLOSED SIGNAL-track pnl by ENTRY-PATH (entry_signal tag).

    Live mode reads the durable log directly (it carries entry_signal);
    test mode groups from the in-memory state. Returns {path_tag: [pnl,...]}.
    """
    by_path: dict[str, list[float]] = {}
    if state is not None:
        for pos in (state.get("tracks", {}).get("SIGNAL", []) or []):
            if pos.get("status") != "CLOSED" or pos.get("pnl_pct") is None:
                continue
            by_path.setdefault(pos.get("entry_signal", "?"), []).append(
                float(pos["pnl_pct"]))
        return by_path
    path = _project_dir() / _TRADES_LOG
    if not path.exists():
        return by_path
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("track") != "SIGNAL" or r.get("status") != "CLOSED" \
                    or r.get("pnl_pct") is None:
                continue
            by_path.setdefault(r.get("entry_signal", "?"), []).append(
                float(r["pnl_pct"]))
    except Exception as e:
        log.error(f"cex_spot_deep_loop._closed_by_path: {e}")
    return by_path

# ── data source (read-only on paper-test state) ──────────────────────────────
def _closed_by_coin(state: dict, track: str) -> dict[str, list[float]]:
    """Group CLOSED pnl fractions by coin for a given track (from state)."""
    by_coin: dict[str, list[float]] = {}
    for pos in (state.get("tracks", {}).get(track, []) or []):
        if pos.get("status") != "CLOSED":
            continue
        pnl = pos.get("pnl_pct")
        if pnl is None:
            continue
        by_coin.setdefault(pos.get("pair", "?"), []).append(float(pnl))
    return by_coin


def _closed_from_log() -> dict[str, dict[str, list[float]]]:
    """Group CLOSED pnl by track→coin from the durable trade log (preferred:
    immutable, survives state pruning). Returns {} if the log is absent."""
    path = _project_dir() / _TRADES_LOG
    if not path.exists():
        return {}
    out: dict[str, dict[str, list[float]]] = {"SIGNAL": {}, "RANDOM": {}}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("status") != "CLOSED" or r.get("pnl_pct") is None:
                continue
            trk = r.get("track", "?")
            out.setdefault(trk, {}).setdefault(
                r.get("pair", "?"), []).append(float(r["pnl_pct"]))
    except Exception as e:
        log.error(f"cex_spot_deep_loop._closed_from_log: {e}")
        return {}
    return out


def _matched_stats(deltas: dict[str, list[float]]) -> dict:
    """Aggregate per-track matched-alpha deltas into stats."""
    out = {"SIGNAL": None, "RANDOM": None}
    for trk, xs in deltas.items():
        if trk in out and xs:
            out[trk] = {"n": len(xs), "mean_alpha_pct": round(sum(xs) / len(xs) * 100, 4),
                        "pos_frac": round(sum(1 for x in xs if x > 0) / len(xs), 3),
                        "p_e_pos": round(_bootstrap_p_e_positive(xs), 3)}
    return out


def _matched_from_state(state: dict) -> dict:
    """Matched-alpha deltas from an in-memory state (test path)."""
    acc: dict[str, list[float]] = {"SIGNAL": [], "RANDOM": []}
    for trk in ("SIGNAL", "RANDOM"):
        for pos in (state.get("tracks", {}).get(trk, []) or []):
            if pos.get("status") != "CLOSED" or pos.get("pnl_pct") is None \
                    or pos.get("buyhold_pct") is None:
                continue
            acc[trk].append(float(pos["pnl_pct"]) - float(pos["buyhold_pct"]))
    return _matched_stats(acc)


def _matched_alpha_from_log() -> dict:
    """Live matched-holding alpha per track = mean(pnl - buyhold) over the
    identical window. This is the beta-immune edge metric the spec mandates
    (baseline = buy&hold, not zero). Only trades that carry buyhold_pct count."""
    path = _project_dir() / _TRADES_LOG
    out = {"SIGNAL": None, "RANDOM": None}
    if not path.exists():
        return out
    acc: dict[str, list[float]] = {"SIGNAL": [], "RANDOM": []}
    try:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("status") != "CLOSED" or r.get("pnl_pct") is None \
                    or r.get("buyhold_pct") is None:
                continue
            trk = r.get("track", "?")
            if trk in acc:
                acc[trk].append(float(r["pnl_pct"]) - float(r["buyhold_pct"]))
    except Exception as e:
        log.error(f"cex_spot_deep_loop._matched_alpha_from_log: {e}")
        return out
    return _matched_stats(acc)


def analyze(state: dict | None = None) -> dict:
    """Analyze SIGNAL-track per-coin expectancy + SIGNAL-vs-RANDOM alpha.

    Source of truth: the durable trade log (immutable) when present; otherwise
    the paper-test state file. `state` arg forces the state source (tests)."""
    from_log = {} if state is not None else _closed_from_log()
    if from_log:
        sig_by_coin = from_log.get("SIGNAL", {})
        rnd_by_coin = from_log.get("RANDOM", {})
    else:
        if state is None:
            try:
                state = json.loads(_state_path().read_text())
            except Exception as e:
                log.error(f"cex_spot_deep_loop.analyze: {e}")
                state = {}
        sig_by_coin = _closed_by_coin(state, "SIGNAL")
        rnd_by_coin = _closed_by_coin(state, "RANDOM")
    coins: dict[str, dict] = {}
    for coin, pnls in sig_by_coin.items():
        s = _coin_stats(pnls)
        veto = (s["n"] >= _VETO_MIN_N and s["expectancy"] < 0
                and s["pf"] < _VETO_MAX_PF and s["p_e_pos"] < _VETO_MAX_PEPOS)
        boost = (s["n"] >= _BOOST_MIN_N and s["expectancy"] >= _BOOST_MIN_EXP
                 and s["p_e_pos"] >= _BOOST_MIN_PEPOS)
        if veto:
            s["veto_reason"] = (f"E={s['expectancy']:+.2f}% PF={s['pf']:.2f} "
                                f"P(E>0)={s['p_e_pos']:.2f} n={s['n']}")
        coins[coin] = {**s, "veto": veto, "boost": boost}

    # ── v1.1 PATH-level learning: same 3-confirmation rules, grouped by
    # entry_signal. Paths pool across coins → evidence accumulates faster.
    # A path veto means the ENTRY LOGIC itself is proven-losing regardless of
    # which coin it fires on — the paper test skips that path entirely.
    paths: dict[str, dict] = {}
    for ptag, pnls in _closed_by_path(state, from_log).items():
        if ptag not in _LIVE_PATHS:          # F3: skip dead/legacy tags
            continue
        s = _coin_stats(pnls)
        pveto = (s["n"] >= _PATH_VETO_MIN_N and s["expectancy"] < 0
                 and s["pf"] < _VETO_MAX_PF and s["p_e_pos"] < _VETO_MAX_PEPOS)
        pboost = (s["n"] >= _PATH_BOOST_MIN_N
                  and s["expectancy"] >= _BOOST_MIN_EXP
                  and s["p_e_pos"] >= _BOOST_MIN_PEPOS)
        if pveto:
            s["veto_reason"] = (f"path E={s['expectancy']:+.2f}% "
                                f"PF={s['pf']:.2f} P(E>0)={s['p_e_pos']:.2f} "
                                f"n={s['n']}")
        paths[ptag] = {**s, "veto": pveto, "boost": pboost}

    # SIGNAL-vs-RANDOM aggregate alpha (report-only, never a gate)
    sig_all = [p for v in sig_by_coin.values() for p in v]
    rnd_all = [p for v in rnd_by_coin.values() for p in v]
    alpha = _permutation_alpha(sig_all, rnd_all)

    # HONEST ALPHA VERDICT — the anti-self-deception gate. Raw WR/E can look
    # spectacular purely from bull-market BETA (a RANDOM long wins too when BTC
    # rips). Genuine skill = SIGNAL beats the RANDOM control significantly.
    # Never declare edge on beta. (Doctrine: baseline is RANDOM, not zero.)
    p = alpha.get("p_value")
    diff = alpha.get("obs_diff_pct")
    n_ok = (alpha.get("n_sig", 0) >= _ALPHA_MIN_N and alpha.get("n_rnd", 0) >= _ALPHA_MIN_N)
    if not n_ok or p is None:
        verdict = "INSUFFICIENT_DATA"        # not enough matched samples yet
    elif diff > 0 and p < _ALPHA_P:
        verdict = "EDGE_CONFIRMED"           # SIGNAL significantly beats RANDOM
    elif diff > 0:
        verdict = "BETA_ONLY"                # positive but not vs-RANDOM significant
    else:
        verdict = "NO_EDGE"                  # SIGNAL not better than a coin-flip
    alpha["verdict"] = verdict

    # Live matched-holding alpha (beta-immune): SIGNAL vs its OWN buy&hold.
    # A positive vs-RANDOM diff can still be pure beta if BOTH beat/lag buy&hold
    # together — this is the stricter, spec-mandated check. Read the durable log
    # only in live mode; in test mode (explicit state) derive from state tracks.
    matched = _matched_from_state(state) if state is not None else _matched_alpha_from_log()
    sig_m = matched.get("SIGNAL")
    if sig_m and sig_m["n"] >= _ALPHA_MIN_N:
        if sig_m["mean_alpha_pct"] > 0 and sig_m["p_e_pos"] >= 0.90:
            alpha["matched_verdict"] = "BEATS_BUYHOLD"
        elif sig_m["mean_alpha_pct"] <= 0:
            alpha["matched_verdict"] = "LOSES_TO_BUYHOLD"   # timing subtracts value
        else:
            alpha["matched_verdict"] = "INCONCLUSIVE"
    else:
        alpha["matched_verdict"] = "INSUFFICIENT_DATA"

    # Aggregate no-edge quarantine: if SPOT timing loses to BOTH random control
    # and its own buy&hold, no live SPOT path should keep opening entries. This
    # is a paper-only containment layer; path-specific vetoes still handle
    # individual failures when aggregate edge recovers.
    #
    # v1.3 FIX (2026-09-19) — ANTI-DEADLOCK. Sebelum ini, quarantina agregat
    # memveto SEMUA path hidup tanpa melihat n per path. Akibatnya nyata:
    # spot-mom-adx (n=7) diveto padahal ambangnya sendiri _PATH_VETO_MIN_N=8,
    # dan karena tidak ada entry baru, verdict agregat tak akan pernah berubah
    # -> track SPOT SIGNAL terkunci mati permanen (tak bisa falsifikasi, tak
    # bisa pulih). Sekarang: path dengan n < _PATH_VETO_MIN_N adalah PROBE —
    # bukti belum cukup untuk diveto, jadi tetap boleh mengumpulkan data.
    # Quarantina agregat tetap berlaku untuk path yang buktinya sudah cukup.
    _agg_q = (alpha.get("verdict") == "NO_EDGE"
              and alpha.get("matched_verdict") == "LOSES_TO_BUYHOLD")
    if _agg_q:
        for ptag, row in paths.items():
            if ptag not in _LIVE_PATHS:
                continue
            _n_path = int(row.get("n") or 0)
            if _n_path < _PATH_VETO_MIN_N:
                row["probe"] = True
                row["probe_reason"] = (
                    f"aggregate quarantine aktif tapi n={_n_path} < "
                    f"{_PATH_VETO_MIN_N} -> probe (kumpulkan bukti dulu)"
                )
                row["veto"] = False
                row["boost"] = False
                continue
            row["veto"] = True
            row["boost"] = False
            row["veto_reason"] = (
                f"aggregate NO_EDGE + LOSES_TO_BUYHOLD; "
                f"path E={row.get('expectancy', 0):+.2f}% n={_n_path}"
            )
    analysis_agg_quarantine = bool(_agg_q)

    # ── Target framework (0.8%-audit Revisi 3): principled, overfitting-resistant
    # verdict. Edge = SIGNAL's timing beats buy&hold (matched alpha>0). Decide via
    # Wald SPRT (rule 6) + expectancy gate (rule 1); project to a per-MONTH target
    # (rule 2) — never per-cycle. Raw beta WR is deliberately ignored here.
    tf: dict = {}
    if sig_m and sig_m["n"] >= 1:
        succ = round(sig_m["pos_frac"] * sig_m["n"])
        tf["sprt"] = _tf.wald_sprt(succ, sig_m["n"])          # ACCEPT/REJECT/CONTINUE
        tf["expectancy_gate"] = {
            "pass": bool(sig_m["mean_alpha_pct"] / 100 > _tf.MIN_NET_E
                         and sig_m["p_e_pos"] >= _tf.BOOT_FRAC),
            "mean_alpha_pct": sig_m["mean_alpha_pct"], "p_gt0": sig_m["p_e_pos"]}
    # per-month projection uses the SIGNAL's realized per-cycle return (beta+alpha)
    if sig_all:
        tf["monthly"] = _tf.monthly_projection(sum(sig_all) / len(sig_all))
    return {"coins": coins, "paths": paths, "signal_vs_random": alpha,
            "matched_alpha": matched, "target_framework": tf,
            "aggregate_quarantine": analysis_agg_quarantine}


# ── persistence ──────────────────────────────────────────────────────────────
def save_learning(analysis: dict, path: Path | None = None) -> Path:
    path = path or _learning_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    coins = analysis.get("coins", {})
    paths = analysis.get("paths", {})
    payload = {
        "generated_ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "coins": coins,
        "paths": paths,
        "vetoed": sorted(k for k, v in coins.items() if v.get("veto")),
        "boosted": sorted(k for k, v in coins.items() if v.get("boost")),
        "vetoed_paths": sorted(k for k, v in paths.items() if v.get("veto")),
        "boosted_paths": sorted(k for k, v in paths.items() if v.get("boost")),
        "signal_vs_random": analysis.get("signal_vs_random", {}),
        "matched_alpha": analysis.get("matched_alpha", {}),
        "target_framework": analysis.get("target_framework", {}),
        "aggregate_quarantine": bool(analysis.get("aggregate_quarantine", False)),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)
    log.info(f"cex_spot_deep_loop: {len(payload['vetoed'])} vetoed, "
             f"{len(payload['boosted'])} boosted → {path}")
    return path


def load_learning(path: Path | None = None) -> dict:
    """Read learning JSON. Fails open (no vetoes) on missing/corrupt."""
    path = path or _learning_path()
    empty = {"generated_ts": None, "coins": {}, "paths": {}, "vetoed": [],
             "boosted": [], "vetoed_paths": [], "boosted_paths": [],
             "signal_vs_random": {}, "matched_alpha": {}, "target_framework": {},
             "aggregate_quarantine": False}
    if not path.exists():
        return empty
    try:
        data = json.loads(path.read_text())
        return {
            "generated_ts": data.get("generated_ts"),
            "coins": data.get("coins", {}),
            "paths": data.get("paths", {}),
            "vetoed": data.get("vetoed", []),
            "boosted": data.get("boosted", []),
            "vetoed_paths": data.get("vetoed_paths", []),
            "boosted_paths": data.get("boosted_paths", []),
            "signal_vs_random": data.get("signal_vs_random", {}),
            "matched_alpha": data.get("matched_alpha", {}),
            "target_framework": data.get("target_framework", {}),
            "aggregate_quarantine": bool(data.get("aggregate_quarantine", False)),
        }
    except Exception as e:
        log.error(f"cex_spot_deep_loop.load_learning: {e}")
        return empty


def refresh_learning(path: Path | None = None) -> dict:
    """Full pipeline: analyze → persist → return loaded learning."""
    save_learning(analyze(), path)
    return load_learning(path)


def is_coin_vetoed(coin: str, learning: dict | None = None) -> bool:
    """True if this coin's SIGNAL entries are auto-vetoed. Fails open."""
    try:
        lg = learning if learning is not None else load_learning()
        return coin in (lg or {}).get("vetoed", [])
    except Exception:
        return False


def is_path_vetoed(entry_signal: str, learning: dict | None = None) -> bool:
    """v1.1: True if this entry PATH is auto-vetoed by the deep-loop. Fails open."""
    try:
        lg = learning if learning is not None else load_learning()
        return entry_signal in (lg or {}).get("vetoed_paths", [])
    except Exception:
        return False


# ── CLI ───────────────────────────────────────────────────────────────────────
def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    lg = refresh_learning()
    print(f"generated: {lg['generated_ts']}")
    print(f"vetoed:  {lg['vetoed'] or '(none)'}")
    print(f"boosted: {lg['boosted'] or '(none)'}")
    svr = lg.get("signal_vs_random", {})
    print(f"SIGNAL vs RANDOM: diff={svr.get('obs_diff_pct')}% "
          f"p={svr.get('p_value')} (n_sig={svr.get('n_sig')}, n_rnd={svr.get('n_rnd')})")
    print(f"ALPHA VERDICT: {svr.get('verdict', 'INSUFFICIENT_DATA')}  "
          f"(edge only if SIGNAL beats RANDOM at p<{_ALPHA_P})")
    ma = lg.get("matched_alpha", {}).get("SIGNAL")
    if ma:
        print(f"MATCHED alpha (SIGNAL vs buy&hold): mean={ma['mean_alpha_pct']:+.3f}% "
              f"pos={ma['pos_frac']*100:.0f}% P(>0)={ma['p_e_pos']:.2f} n={ma['n']} "
              f"→ {svr.get('matched_verdict', 'INSUFFICIENT_DATA')}")
    tf = lg.get("target_framework", {})
    if tf.get("sprt"):
        print(f"SPRT edge decision: {tf['sprt']['decision']} (llr={tf['sprt']['llr']})")
    if tf.get("monthly"):
        m = tf["monthly"]
        print(f"Progress vs FIXED North Star (≥0.7%/cycle): "
              f"realized {m['monthly_pct']:+.2f}%/mo ({m['annual_pct']:+.0f}%/yr) [{m['grade']}]")
    for coin, s in sorted(lg["coins"].items()):
        flag = "VETO" if s.get("veto") else ("BOOST" if s.get("boost") else "ok")
        print(f"  {coin:6s} n={s['n']:2d} WR={s['wr']*100:3.0f}% "
              f"(wilson_lo={s['wr_wilson_lo']*100:3.0f}%) E={s['expectancy']:+.2f}% "
              f"PF={s['pf']:.2f} P(E>0)={s['p_e_pos']:.2f}  [{flag}]")
    if lg.get("paths"):
        print("PATH-level learning (v1.1):")
        for ptag, s in sorted(lg["paths"].items()):
            flag = "VETO" if s.get("veto") else ("BOOST" if s.get("boost") else "ok")
            print(f"  {ptag:28s} n={s['n']:2d} E={s['expectancy']:+.2f}% "
                  f"PF={s['pf']:.2f} P(E>0)={s['p_e_pos']:.2f}  [{flag}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
