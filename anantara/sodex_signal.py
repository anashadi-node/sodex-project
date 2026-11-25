#!/usr/bin/env python3
"""
ANANTARA SAKTI — SoDEX microstructure signal engine.

Single source of truth for the scalp signal, shared by research (backtests) and
(future) live farming. Pure, stdlib-only, deterministic functions over a time
series of order-book snapshots produced by scripts/sodex_obi_collector.py.

Why this module exists: the plain cumOFI signal (one 30s window) had a real but
sub-fee edge. Research (López de Prado / pynat methodology) says the way to lift
a thin edge above costs is CONVICTION FILTERING — trade only the strongest, most
agreeing, regime-appropriate events, not every threshold cross. This engine builds:
  - multi-window order-flow (OFI over 10/30/60s) for cross-window agreement,
  - a z-score of flow (adaptive to each symbol's scale) for "how extreme",
  - static book imbalance (OBI) for a second, independent confirmation,
  - a volatility/spread REGIME gate (skip dead and chaotic conditions).
The composite rule requires all of them to align, so it fires rarely but well.

The signal is direction only (+1 long / -1 short / 0 stand-aside); the governor
(sodex_governor.py) sizes/risks/vetoes it, and expectancy is the master gate.
"""
from __future__ import annotations
from dataclasses import dataclass
import math


# ---------------- order-flow primitives ----------------
def ofi_step(prev: dict, cur: dict) -> float:
    """Cont-Kukanov-Stoikov order-flow imbalance between two snapshots,
    normalized by total depth (~[-1,1]). Uses clean L1 volumes (bbv/bav) if
    present, else aggregate top-20 (bv20/av20) as a proxy."""
    use_l1 = "bbv" in cur and "bbv" in prev
    qb, qa = (("bbv", "bav") if use_l1 else ("bv20", "av20"))
    pb0, pb1, pa0, pa1 = prev["bid"], cur["bid"], prev["ask"], cur["ask"]
    qb0, qb1, qa0, qa1 = prev[qb], cur[qb], prev[qa], cur[qa]
    e_bid = qb1 if pb1 > pb0 else (qb1 - qb0 if pb1 == pb0 else -qb0)
    e_ask = qa0 if pa1 > pa0 else (qa1 - qa0 if pa1 == pa0 else -qa1)
    return (e_bid - e_ask) / ((qb1 + qa1) or 1.0)


def _trailing_sum(values, ts, i, window_ms):
    """Sum values[j] for j<=i within window_ms before ts[i]."""
    acc, j = 0.0, i
    while j >= 1 and ts[i] - ts[j] <= window_ms:
        acc += values[j]; j -= 1
    return acc


def _mean_std(xs):
    n = len(xs)
    if n < 2:
        return 0.0, 0.0
    m = sum(xs) / n
    v = sum((x - m) ** 2 for x in xs) / (n - 1)
    return m, math.sqrt(v)


# ---------------- feature builder ----------------
@dataclass
class SignalParams:
    win_short_s: int = 10        # short flow window
    win_mid_s: int = 30          # primary flow window (z-scored)
    win_long_s: int = 60         # long flow window (confirmation)
    z_lookback_s: int = 300      # rolling window for the flow z-score
    rvol_window_s: int = 60      # window for realized volatility (regime)
    obi_field: str = "obi10"     # which static-imbalance depth to confirm with
    # composite entry gates:
    z_min: float = 1.5           # require |z(cofi_mid)| >= this (conviction)
    require_multiwin_agree: bool = True   # cofi short/mid/long same sign
    require_obi_agree: bool = True        # OBI same sign as flow
    spread_max_pct: float = 0.02          # skip if spread wider than this (% of mid)
    rvol_min_pct: float = 0.005           # skip dead tape (too little movement)
    rvol_max_pct: float = 0.20            # skip chaos (too much, adverse-selection risk)


def build_features(series: list[dict], p: SignalParams) -> list[dict]:
    """Compute per-snapshot features. series must be time-sorted, deduped."""
    n = len(series)
    ts = [r["ts"] for r in series]
    mid = [r["mid"] for r in series]
    ofi = [0.0] + [ofi_step(series[i - 1], series[i]) for i in range(1, n)]
    cof_s = [_trailing_sum(ofi, ts, i, p.win_short_s * 1000) for i in range(n)]
    cof_m = [_trailing_sum(ofi, ts, i, p.win_mid_s * 1000) for i in range(n)]
    cof_l = [_trailing_sum(ofi, ts, i, p.win_long_s * 1000) for i in range(n)]
    # per-step returns for realized vol
    ret = [0.0] + [(mid[i] - mid[i - 1]) / mid[i - 1] * 100 for i in range(1, n)]
    feats = []
    zwin_ms = p.z_lookback_s * 1000
    rvwin_ms = p.rvol_window_s * 1000
    for i in range(n):
        # z-score of mid-window flow over rolling lookback
        j = i
        hist = []
        while j >= 0 and ts[i] - ts[j] <= zwin_ms:
            hist.append(cof_m[j]); j -= 1
        mu, sd = _mean_std(hist)
        z = (cof_m[i] - mu) / sd if sd > 1e-9 else 0.0
        # realized vol over rvol window
        k = i; rets = []
        while k >= 1 and ts[i] - ts[k] <= rvwin_ms:
            rets.append(ret[k]); k -= 1
        _, rvol = _mean_std(rets) if len(rets) >= 2 else (0.0, 0.0)
        feats.append({
            "ts": ts[i], "mid": mid[i],
            "cof_s": cof_s[i], "cof_m": cof_m[i], "cof_l": cof_l[i],
            "z": z, "obi": series[i].get(p.obi_field, 0.0),
            "spread_pct": (series[i]["spread"] / mid[i] * 100) if mid[i] else 0.0,
            "rvol_pct": rvol,
        })
    return feats


def composite_signal(f: dict, p: SignalParams) -> int:
    """Direction from the composite rule: +1 long / -1 short / 0 stand aside."""
    # regime gate first (cheap rejects)
    if f["spread_pct"] > p.spread_max_pct:
        return 0
    if not (p.rvol_min_pct <= f["rvol_pct"] <= p.rvol_max_pct):
        return 0
    if abs(f["z"]) < p.z_min:
        return 0
    direction = 1 if f["cof_m"] > 0 else -1
    if p.require_multiwin_agree:
        if not (_sign(f["cof_s"]) == _sign(f["cof_m"]) == _sign(f["cof_l"]) == direction):
            return 0
    if p.require_obi_agree and _sign(f["obi"]) != direction:
        return 0
    return direction


def _sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)
