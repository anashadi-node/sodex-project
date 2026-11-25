#!/usr/bin/env python3
"""D0.5 — SoDEX twoway edge-leak audit (fee-gate closure).

READ-ONLY. Changes no strategy, gate, exit policy, leverage, or live flag.

It answers ONE question: where does the 3,26 bps/trade that separates twoway
from the 2x-fee T1 gate actually live?

Falsification protocol (mandatory, see skill `signal-gate-falsification`):
  1. duplication ratio measured BEFORE anything else
  2. arm split (signal vs a-priori-labelled RANDOM control)
  3. cluster bootstrap by horizon-width blocks (30h), never per-row
  4. per-dimension breakdown + BH-FDR (q=0.10)
  5. negative control: random bucket selection null (>=200 draws)

Any candidate fix is a MEASUREMENT fix until RISET confirms otherwise; the
strategy itself must not change before T1 passes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ROOT / "docs/handover/RISET_TO_DIVISI_2026-10-01/harness"))

import sodex_harness_reeval as H  # noqa: E402
from anantara_harness import evaluate  # noqa: E402

REPORT_DIR = ROOT / "reports/sodex"
OUT_MD = REPORT_DIR / "SODEX_D05_EDGE_LEAK.md"
OUT_JSON = REPORT_DIR / "SODEX_D05_EDGE_LEAK.json"

BPS = 10000.0
FEE_BPS = H.SODEX_FEE_BPS
CLUSTER_HOURS = 30.0
SEED = 20261003
N_BOOT = 10000
N_CONTROL = 200
CONTROL_TRACK = "RANDOM"      # a-priori label written by the control harness
ARM_SIGNAL = "SIGNAL"
ARM_CONTROL = "CONTROL"


# ───────────────────────── arm split / duplication ─────────────────────────

def arm_of(row: dict[str, Any]) -> str:
    """A-priori arm label. Never derived from the trade outcome."""
    return ARM_CONTROL if str(row.get("track") or "").upper() == CONTROL_TRACK else ARM_SIGNAL


def duplication_ratio(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Rows per unique (pair, entry-hour). >1 means the loop re-logged bars."""
    keys = set()
    for r in rows:
        try:
            entry, _ = H.trade_times(r)
        except Exception:
            continue
        keys.add((H.trade_symbol(r), entry.replace(minute=0, second=0, microsecond=0)))
    return {"n_rows": len(rows), "n_unique": len(keys), "ratio": round(len(rows) / len(keys), 3) if keys else None}


# ───────────────────────── beta-neutral excess ─────────────────────────

def gross_excess(rows: list[dict[str, Any]], candles: list[tuple[int, float]]) -> list[dict[str, Any]]:
    """Per-trade beta-neutral excess (fraction), plus block id and metadata."""
    out = []
    for r in rows:
        try:
            ret = H.trade_return(r)
            side = H.side_sign(r)
            entry, exit_ = H.trade_times(r)
        except Exception:
            continue
        mkt = H.btc_market_returns([r], candles)[0]
        out.append({
            "pair": H.trade_symbol(r),
            "side": "LONG" if side > 0 else "SHORT",
            "regime": r.get("regime"),
            "exit_reason": r.get("exit_reason"),
            "hold_hours": r.get("hold_hours"),
            "entry_ts": entry,
            "excess": side * ret - side * mkt,
            "block": int(entry.timestamp() // (CLUSTER_HOURS * 3600)),
            "arm": arm_of(r),
        })
    return out


# ───────────────────────── clustered inference ─────────────────────────

def cluster_bootstrap(trades: list[dict[str, Any]], n_iter: int = N_BOOT, seed: int = SEED) -> dict[str, Any]:
    """Resample BLOCKS (not rows); within-block correlation is preserved."""
    blocks: dict[int, list[float]] = defaultdict(list)
    for t in trades:
        blocks[t["block"]].append(t["excess"])
    ids = sorted(blocks)
    if not ids:
        return {"mean": None, "ci95": [None, None], "p_pos": None, "n_blocks": 0, "n": 0}
    rng = random.Random(seed)
    means = []
    for _ in range(n_iter):
        pick = [ids[rng.randrange(len(ids))] for _ in ids]
        vals = [v for b in pick for v in blocks[b]]
        if vals:
            means.append(sum(vals) / len(vals))
    means.sort()
    point = sum(t["excess"] for t in trades) / len(trades)
    return {
        "mean": point,
        "ci95": [means[int(0.025 * len(means))], means[int(0.975 * len(means)) - 1]],
        "p_pos": sum(1 for m in means if m > 0) / len(means),
        "n_blocks": len(ids),
        "n": len(trades),
    }


def bucket_table(trades: list[dict[str, Any]], key: Callable[[dict[str, Any]], Any], min_n: int = 20) -> list[dict[str, Any]]:
    groups: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        groups[str(key(t))].append(t["excess"])
    rows = []
    for k, vals in groups.items():
        mean = sum(vals) / len(vals)
        rows.append({"bucket": k, "n": len(vals), "excess_bps": round(mean * BPS, 2), "meets_min_n": len(vals) >= min_n})
    rows.sort(key=lambda r: r["excess_bps"], reverse=True)
    return rows


def bh_fdr(pvals: list[float], q: float = 0.10) -> list[float]:
    """Benjamini-Hochberg q-values (rank-dependent)."""
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    qs = [1.0] * m
    prev = 1.0
    for rank, idx in enumerate(reversed(order), start=1):
        i = m - rank + 1
        val = min(prev, pvals[idx] * m / i)
        qs[idx] = val
        prev = val
    return qs


def bucket_t_pvalues(trades: list[dict[str, Any]], key: Callable[[dict[str, Any]], Any]) -> list[dict[str, Any]]:
    """One-sample t on block means per bucket: is this bucket's edge != 0?"""
    groups: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for t in trades:
        groups[str(key(t))][t["block"]].append(t["excess"])
    out = []
    for name, blocks in groups.items():
        block_means = [sum(v) / len(v) for v in blocks.values()]
        n = len(block_means)
        if n < 2:
            out.append({"bucket": name, "n": sum(len(v) for v in blocks.values()), "n_blocks": n, "p": None})
            continue
        mean = sum(block_means) / n
        var = sum((x - mean) ** 2 for x in block_means) / (n - 1)
        se = math.sqrt(var / n) if var > 0 else 0.0
        t = mean / se if se > 0 else 0.0
        p = 2 * (1 - _norm_cdf(abs(t)))
        out.append({"bucket": name, "n": sum(len(v) for v in blocks.values()), "n_blocks": n, "t": round(t, 3), "p": p})
    qs = bh_fdr([r["p"] for r in out if r["p"] is not None])
    it = iter(qs)
    for r in out:
        if r["p"] is not None:
            r["q"] = next(it)
    return out


def _norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def selection_null(trades: list[dict[str, Any]], min_n: int = 20, n_iter: int = N_CONTROL, seed: int = SEED) -> dict[str, Any]:
    """Negative control: max bucket mean when arm labels are SHUFFLED.

    If the observed best bucket is inside this null band, the 'best dimension'
    is noise, not edge.
    """
    vals = [t["excess"] for t in trades]
    rng = random.Random(seed)
    span = [0.25, 0.5, 1.0]  # bucket-count proportions to exercise
    null_max = []
    for _ in range(n_iter):
        shuffled = vals[:]
        rng.shuffle(shuffled)
        k = max(2, int(len(vals) * rng.choice(span) / len(vals) * 12))  # 12 buckets
        k = min(k, max(2, len(vals)))
        chunk = max(1, len(vals) // k)
        best = None
        for i in range(0, len(vals), chunk):
            part = shuffled[i:i + chunk]
            if len(part) < min_n:
                continue
            m = sum(part) / len(part)
            best = m if best is None else max(best, m)
        if best is not None:
            null_max.append(best * BPS)
    if not null_max:
        return {"n": 0, "p95_bps": None, "p99_bps": None}
    null_max.sort()
    return {
        "n": len(null_max),
        "p50_bps": round(null_max[len(null_max) // 2], 2),
        "p95_bps": round(null_max[int(0.95 * len(null_max)) - 1], 2),
        "p99_bps": round(null_max[int(0.99 * len(null_max)) - 1], 2),
    }


# ───────────────────────── report ─────────────────────────

def analyse(track: str = "twoway") -> dict[str, Any]:
    path = H.TRACKS[track]
    rows = H.closed_rows(path)
    signal = [r for r in rows if arm_of(r) == ARM_SIGNAL]
    control = [r for r in rows if arm_of(r) == ARM_CONTROL]
    all_times = []
    for r in rows:
        try:
            a, b = H.trade_times(r)
            all_times.append((a, b))
        except Exception:
            continue
    if not all_times:
        raise RuntimeError(f"no parseable trades in {path}")
    start = min(a for a, _ in all_times) - dt.timedelta(days=3)
    end = max(b for _, b in all_times) + dt.timedelta(days=1)
    candles = H.fetch_btc_1h(start, end)

    dup_all = duplication_ratio(rows)
    dup_sig = duplication_ratio(signal)

    ex_all = [t for t in gross_excess(rows, candles)]
    ex_sig = [t for t in gross_excess(signal, candles)]
    ex_ctl = [t for t in gross_excess(control, candles)]

    boot_all = cluster_bootstrap(ex_all)
    boot_sig = cluster_bootstrap(ex_sig)
    boot_ctl = cluster_bootstrap(ex_ctl) if len(ex_ctl) >= 5 else {"n": len(ex_ctl), "note": "control n<5"}

    dims = {
        "symbol": lambda t: t["pair"],
        "side": lambda t: t["side"],
        "regime": lambda t: t["regime"],
        "exit_reason": lambda t: t["exit_reason"],
    }
    breakdown = {name: bucket_table(ex_sig, fn) for name, fn in dims.items()}
    tests = {name: bucket_t_pvalues(ex_sig, fn) for name, fn in dims.items()}
    null = selection_null(ex_sig)

    cost_gap = FEE_BPS * 2.0 - (boot_sig["mean"] or 0.0) * BPS
    return {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "track": track,
        "source": str(path),
        "fee_bps": FEE_BPS,
        "cluster_hours": CLUSTER_HOURS,
        "duplication": {"all": dup_all, "signal": dup_sig},
        "arms": {
            "n_all": len(ex_all), "n_signal": len(ex_sig), "n_control": len(ex_ctl),
            "control_track_label": CONTROL_TRACK,
        },
        "contamination": {
            "excess_all_bps": round((boot_all["mean"] or 0.0) * BPS, 2),
            "excess_signal_only_bps": round((boot_sig["mean"] or 0.0) * BPS, 2),
            "delta_bps": round(((boot_sig["mean"] or 0.0) - (boot_all["mean"] or 0.0)) * BPS, 2),
        },
        "clustered": {"all": _ser(boot_all), "signal": _ser(boot_sig), "control": _ser(boot_ctl)},
        "cost_gate": {
            "gross_signal_bps": round((boot_sig["mean"] or 0.0) * BPS, 2),
            "cost_1x_bps": round((boot_sig["mean"] or 0.0) * BPS - FEE_BPS, 2),
            "cost_2x_bps": round((boot_sig["mean"] or 0.0) * BPS - 2 * FEE_BPS, 2),
            "gap_to_2x_bps": round(cost_gap, 2),
        },
        "breakdown": breakdown,
        "tests": tests,
        "selection_null": null,
        "verdict": _verdict(boot_sig, cost_gap),
        "safety": {
            "changed_strategy": "NO",
            "changed_gate_exit_leverage": "NO",
            "placed_order": "NO",
            "measurement_only": "YES — RISET must confirm before any pipeline change",
        },
    }


def _side_mkt(_t: dict[str, Any]) -> float:  # placeholder kept for API stability
    return 0.0


def _ser(boot: dict[str, Any]) -> dict[str, Any]:
    if boot.get("ci95") is None:
        return boot
    lo, hi = boot["ci95"]
    out = dict(boot)
    out["ci95_bps"] = [round(lo * BPS, 2), round(hi * BPS, 2)]
    out["mean_bps"] = round(boot["mean"] * BPS, 2)
    out.pop("ci95", None)
    out.pop("mean", None)
    return out


def _verdict(boot_sig: dict[str, Any], gap_bps: float) -> str:
    ci = boot_sig.get("ci95") or [None, None]
    lo = ci[0]
    if lo is None:
        return "FAIL_NO_DATA"
    if lo > 0 and gap_bps <= 0:
        return "T1_GATE_MET_PENDING_RISET_CONFIRMATION"
    if lo <= 0 and gap_bps > 0:
        return "FAIL_CI95_SPANS_ZERO_AND_COST_2X_GAP"
    if lo <= 0:
        return "FAIL_CI95_SPANS_ZERO"
    return "FAIL_COST_2X_GAP"



def render_md(a: dict[str, Any]) -> str:
    b = a["breakdown"]
    L = [
        "# SoDEX D0.5 — twoway Edge-Leak Audit (fee-gate closure)",
        "",
        f"Generated UTC: {a['generated_utc']}",
        f"Track: **{a['track']}** · source `{a['source']}`",
        f"Fee {a['fee_bps']} bps/step · cluster block = {a['cluster_hours']} h",
        "",
        "## Verdict",
        f"- `{a['verdict']}`",
        f"- Gross (beta-neutral, signal arm): **{a['cost_gate']['gross_signal_bps']} bps**",
        f"- 1× fee: {a['cost_gate']['cost_1x_bps']} bps · 2× fee: {a['cost_gate']['cost_2x_bps']} bps",
        f"- Gap to 2× gate: **{a['cost_gate']['gap_to_2x_bps']} bps**",
        f"- CI95 (cluster bootstrap): {a['clustered']['signal'].get('ci95_bps')} · p(excess>0) = {a['clustered']['signal'].get('p_pos')}",
        "",
        "## 1. Duplication",
        f"- all rows: {a['duplication']['all']['n_rows']} → {a['duplication']['all']['n_unique']} unique pair-hour (ratio {a['duplication']['all']['ratio']})",
        f"- signal arm: {a['duplication']['signal']['n_rows']} → {a['duplication']['signal']['n_unique']} (ratio {a['duplication']['signal']['ratio']})",
        "",
        "## 2. Arm split (a-priori label, not outcome-derived)",
        f"- signal n={a['arms']['n_signal']} · control n={a['arms']['n_control']} (label `{a['arms']['control_track_label']}`)",
        "",
        "## 3. Contamination of the T1 measurement",
        "| view | excess bps |",
        "|---|---:|",
        f"| all rows (harness as-is) | {a['contamination']['excess_all_bps']} |",
        f"| signal arm only | {a['contamination']['excess_signal_only_bps']} |",
        f"| **delta recovered** | **{a['contamination']['delta_bps']}** |",
        "",
        "## 4. Clustered inference (30 h blocks)",
        "| view | n | n_blocks | mean bps | CI95 bps | p(>0) |",
        "|---|---:|---:|---:|---|---:|",
    ]
    for name in ("all", "signal", "control"):
        c = a["clustered"].get(name) or {}
        if "mean_bps" not in c:
            L.append(f"| {name} | {c.get('n')} | — | n/a | n/a | n/a |")
            continue
        L.append(f"| {name} | {c.get('n')} | {c.get('n_blocks')} | {c.get('mean_bps')} | {c.get('ci95_bps')} | {c.get('p_pos')} |")
    L += ["", "### Symbol breakdown (signal arm)", "", "| symbol | n | excess bps | n≥20 |", "|---|---:|---:|:--:|"]
    for r in b["symbol"][:15]:
        L.append(f"| {r['bucket']} | {r['n']} | {r['excess_bps']} | {'yes' if r['meets_min_n'] else 'no'} |")
    for dim in ("side", "regime", "exit_reason"):
        L += ["", f"### {dim} breakdown (signal arm)", "", "| bucket | n | excess bps | n≥20 |", "|---|---:|---:|:--:|"]
        for r in b[dim]:
            L.append(f"| {r['bucket']} | {r['n']} | {r['excess_bps']} | {'yes' if r['meets_min_n'] else 'no'} |")
    L += ["", "## 5. Per-bucket tests (block-level t, BH-FDR q=0.10)", "", "| dim | bucket | n | n_blocks | t | p | q |", "|---|---|---:|---:|---:|---|---:|"]
    for dim, rows_ in a["tests"].items():
        for r in rows_:
            p = "n/a" if r.get("p") is None else f"{r['p']:.4f}"
            q = "n/a" if r.get("q") is None else f"{r['q']:.4f}"
            t = "n/a" if r.get("t") is None else f"{r['t']:.3f}"
            L.append(f"| {dim} | {r['bucket']} | {r['n']} | {r.get('n_blocks')} | {t} | {p} | {q} |")
    n = a["selection_null"]
    L += ["", "## 6. Negative control — random bucket selection", "",
          f"- draws: {n.get('n')} · null max-bucket p95 = **{n.get('p95_bps')} bps**, p99 = {n.get('p99_bps')} bps",
          "- If the best observed bucket does not exceed p95, it is selection noise.", "",
          "## Safety", "- No strategy/gate/exit/leverage change. No order. Measurement-only.", ""]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SoDEX D0.5 edge-leak audit")
    ap.add_argument("--track", default="twoway")
    ap.add_argument("--out-md", type=Path, default=OUT_MD)
    ap.add_argument("--out-json", type=Path, default=OUT_JSON)
    args = ap.parse_args(argv)
    a = analyse(args.track)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(a, indent=2, ensure_ascii=False, default=str))
    args.out_md.write_text(render_md(a))
    print(json.dumps({"json": str(args.out_json), "md": str(args.out_md), "verdict": a["verdict"],
                      "gross_signal_bps": a["cost_gate"]["gross_signal_bps"],
                      "gap_to_2x_bps": a["cost_gate"]["gap_to_2x_bps"],
                      "delta_from_contamination_bps": a["contamination"]["delta_bps"],
                      "ci95_bps": a["clustered"]["signal"].get("ci95_bps")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
