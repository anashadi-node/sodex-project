#!/usr/bin/env python3
"""D0.5b — SoDEX exit-geometry diagnostic (READ-ONLY).

Designed and realized exit geometry of the SoDEX paper lanes. Answers the
diagnostic question left by D0.5: *where* the per-trade edge leaks, measured,
not guessed.

The only exit reason that is NOT outcome-determined is the time stop, so it is
the only one that admits a falsifiable claim: "time-stop exits are
systematically non-productive". Everything else (TP, SL) is tautological —
a stop-loss trade is a losing trade by construction — so it is reported as
accounting only, never as an edge claim.

Protocol: duplication ratio first, cluster bootstrap (block = 30 h horizon),
paired counterfactual, negative control (shuffled time-stop label, >=200 draws),
BH-FDR where several hypotheses are tested.

Changes no strategy, gate, exit, leverage, or live flag.
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
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "docs/handover/RISET_TO_DIVISI_2026-10-01/harness"))

import sodex_harness_reeval as H  # noqa: E402

REPORT_DIR = ROOT / "reports/sodex"
OUT_MD = REPORT_DIR / "SODEX_D05B_EXIT_GEOMETRY.md"
OUT_JSON = REPORT_DIR / "SODEX_D05B_EXIT_GEOMETRY.json"

BPS = 10000.0
FEE_BPS = H.SODEX_FEE_BPS
CLUSTER_HOURS = 30.0
SEED = 20261004
N_BOOT = 10000
N_CONTROL = 200


# ───────────────────────── helpers ─────────────────────────

def _dist(a: float, b: float) -> float:
    """Absolute fractional distance between two prices."""
    return abs(float(b) / float(a) - 1.0)


def _planned(row: dict[str, Any]) -> dict[str, float] | None:
    entry, tp, sl = row.get("entry_price"), row.get("tp_price"), row.get("sl_price")
    if entry in (None, 0) or tp is None or sl is None:
        return None
    entry = float(entry)
    tp_d, sl_d = _dist(entry, tp), _dist(entry, sl)
    if tp_d <= 0 or sl_d <= 0:
        return None
    return {"tp_dist": tp_d, "sl_dist": sl_d, "rr": tp_d / sl_d}


def _block(ts: dt.datetime) -> int:
    return int(ts.timestamp() // (CLUSTER_HOURS * 3600))


def build(rows: list[dict[str, Any]], candles: list[tuple[int, float]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        try:
            ret = H.trade_return(r)
            side = H.side_sign(r)
            entry_t, exit_t = H.trade_times(r)
        except Exception:
            continue
        mkt = H.btc_market_returns([r], candles)[0]
        plan = _planned(r) or {}
        out.append({
            "pair": H.trade_symbol(r),
            "side": "LONG" if side > 0 else "SHORT",
            "exit_reason": str(r.get("exit_reason") or "UNKNOWN").upper(),
            "hold_hours": float(r.get("hold_hours") or 0.0),
            "realized_dist": abs(ret),
            "excess": side * ret - side * mkt,
            "block": _block(entry_t),
            "tp_dist": plan.get("tp_dist"),
            "sl_dist": plan.get("sl_dist"),
            "rr": plan.get("rr"),
        })
    return out


def duplication(rows: list[dict[str, Any]]) -> dict[str, Any]:
    keys = set()
    for r in rows:
        try:
            entry, _ = H.trade_times(r)
        except Exception:
            continue
        keys.add((H.trade_symbol(r), entry.replace(minute=0, second=0, microsecond=0)))
    return {"n_rows": len(rows), "n_unique": len(keys), "ratio": round(len(rows) / len(keys), 3) if keys else None}


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _rnd(x: float | None, nd: int = 4) -> float | None:
    return round(x, nd) if x is not None else None


def exit_accounting(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        groups[t["exit_reason"]].append(t)
    total_n = len(trades)
    rows = []
    for reason, ts in groups.items():
        ex = [t["excess"] for t in ts]
        m = _mean(ex)
        rows.append({
            "exit_reason": reason, "n": len(ts), "share": len(ts) / total_n if total_n else None,
            "mean_excess_bps": round(m * BPS, 2) if m is not None else None,
            "total_excess_bps": round(sum(ex) * BPS, 1),
            "contrib_to_mean_bps": round(sum(ex) * BPS / total_n, 2) if total_n else None,
            "mean_hold_hours": round(_mean([t["hold_hours"] for t in ts]) or 0.0, 2),
            "outcome_determined": reason != "TIME_30H" and reasontype(reason),
        })
    rows.sort(key=lambda r: r["contrib_to_mean_bps"] or 0, reverse=True)
    return rows


def reasontype(reason: str) -> bool:
    """True when the label is decided by the OUTCOME (TP/SL), so its P&L is tautological."""
    return reason.startswith("TP") or reason.startswith("SL")


def geometry(trades: list[dict[str, Any]]) -> dict[str, Any]:
    plan = [t for t in trades if t.get("rr")]
    tp = [t["realized_dist"] for t in trades if t["exit_reason"].startswith("TP")]
    sl = [t["realized_dist"] for t in trades if t["exit_reason"].startswith("SL")]
    n = len(trades)
    wins = sum(1 for t in trades if t["excess"] > 0)
    out: dict[str, Any] = {
        "n": n,
        "wr": wins / n if n else None,
        "n_planned": len(plan),
        "mean_planned_tp_dist_pct": _rnd((_mean([t["tp_dist"] for t in plan]) or 0.0) * 100 if plan else None),
        "mean_planned_sl_dist_pct": _rnd((_mean([t["sl_dist"] for t in plan]) or 0.0) * 100 if plan else None),
        "mean_planned_rr": _rnd(_mean([t["rr"] for t in plan])),
        "mean_realized_tp_pct": _rnd((_mean(tp) or 0.0) * 100 if tp else None),
        "mean_realized_sl_pct": _rnd((_mean(sl) or 0.0) * 100 if sl else None),
        "n_tp": len(tp), "n_sl": len(sl),
    }
    if tp and sl:
        g = _mean(tp)
        l = _mean(sl)
        if g is not None and l is not None and l > 0:
            out["mean_realized_rr"] = round(g / l, 4)
            out["breakeven_wr_no_fee"] = round(l / (g + l), 4)
            fee = FEE_BPS / BPS
            out["breakeven_wr_fee_1x"] = round((l + fee) / (g + l), 4)
            out["breakeven_wr_fee_2x"] = round((l + 2 * fee) / (g + l), 4)
            out["fee_share_of_tp_pct"] = round(fee / g * 100, 2)
            wr = out["wr"] or 0.0
            out["edge_per_trade_bps"] = round((wr * g - (1 - wr) * l) * BPS, 2)
            out["breakeven_wr_gap_pp"] = round(((out["breakeven_wr_fee_2x"] or 0) - wr) * 100, 2)
    return out


# ───────────────────────── inference ─────────────────────────

def cluster_bootstrap(trades: list[dict[str, Any]], value=None, n_iter: int = N_BOOT, seed: int = SEED) -> dict[str, Any]:
    key = value or (lambda t: t["excess"])
    blocks: dict[int, list[float]] = defaultdict(list)
    for t in trades:
        blocks[t["block"]].append(float(key(t)))
    ids = sorted(blocks)
    if not ids:
        return {"mean": None, "ci95": None, "p_pos": None, "n_blocks": 0, "n": 0}
    rng = random.Random(seed)
    means = []
    for _ in range(n_iter):
        pick = [ids[rng.randrange(len(ids))] for _ in ids]
        vals = [v for b in pick for v in blocks[b]]
        if vals:
            means.append(sum(vals) / len(vals))
    means.sort()
    point = sum(key(t) for t in trades) / len(trades)
    return {
        "mean": point,
        "ci95": [means[int(0.025 * len(means))], means[int(0.975 * len(means)) - 1]],
        "p_pos": sum(1 for m in means if m > 0) / len(means),
        "n_blocks": len(ids), "n": len(trades),
    }


def time_stop_counterfactual(trades: list[dict[str, Any]], n_iter: int = N_BOOT, seed: int = SEED) -> dict[str, Any]:
    """Paired counterfactual: what if time-stop exits returned 0 instead of their P&L?

    Reported as the SIZE of the leak, not as a recommendation — avoiding a time
    stop is not achievable, only re-designing one is.
    """
    is_time = [t["exit_reason"].startswith("TIME") for t in trades]
    if not any(is_time):
        return {"note": "no time-stop exits"}
    delta = [(-t["excess"] if i else 0.0) for t, i in zip(trades, is_time)]
    paired = [{"block": t["block"], "d": d} for t, d in zip(trades, delta)]
    boot = cluster_bootstrap(paired, value=lambda x: x["d"], n_iter=n_iter, seed=seed)
    return {
        "n_time": sum(is_time),
        "leak_bps": round(sum(delta) / len(delta) * BPS, 2),
        "paired_ci95_bps": [round(boot["ci95"][0] * BPS, 2), round(boot["ci95"][1] * BPS, 2)] if boot["ci95"] else None,
        "n_blocks": boot["n_blocks"],
    }


def time_stop_null(trades: list[dict[str, Any]], n_iter: int = N_CONTROL, seed: int = SEED) -> dict[str, Any]:
    """Negative control: shuffle the time-stop LABEL (same count), rebuild the leak.

    If the observed leak sits inside this null band, 'time stops are
    non-productive' is just saying 'some subset was unlucky'.
    """
    k = sum(1 for t in trades if t["exit_reason"].startswith("TIME"))
    if k == 0 or k == len(trades):
        return {"note": "degenerate label", "n": 0}
    idx = list(range(len(trades)))
    rng = random.Random(seed)
    nulls = []
    for _ in range(n_iter):
        rng.shuffle(idx)
        chosen = set(idx[:k])
        leak = sum(-trades[i]["excess"] for i in chosen) / len(trades) * BPS
        nulls.append(leak)
    nulls.sort()
    return {
        "n": len(nulls),
        "p50_bps": round(nulls[len(nulls) // 2], 2),
        "p95_bps": round(nulls[int(0.95 * len(nulls)) - 1], 2),
        "p99_bps": round(nulls[int(0.99 * len(nulls)) - 1], 2),
        "frac_ge_observed": None,  # filled by caller
    }


# ───────────────────────── report ─────────────────────────

def analyse(track: str = "twoway") -> dict[str, Any]:
    path = H.TRACKS[track]
    raw = H.closed_rows(path)
    signal = [r for r in raw if H.arm_of(r) == H.ARM_SIGNAL]
    times = []
    for r in raw:
        try:
            times.append(H.trade_times(r))
        except Exception:
            continue
    if not times:
        raise RuntimeError(f"no parseable trades in {path}")
    candles = H.fetch_btc_1h(min(a for a, _ in times) - dt.timedelta(days=3), max(b for _, b in times) + dt.timedelta(days=1))

    trades = build(signal, candles)
    acc = exit_accounting(trades)
    geo = geometry(trades)
    boot = cluster_bootstrap(trades)
    tp_c = next((r["contrib_to_mean_bps"] for r in acc if r["exit_reason"].startswith("TP")), 0.0)
    sl_c = next((r["contrib_to_mean_bps"] for r in acc if r["exit_reason"].startswith("SL")), 0.0)
    time_c = sum(r["contrib_to_mean_bps"] for r in acc if r["exit_reason"].startswith("TIME"))
    gross = (boot["mean"] or 0.0) * BPS
    binding = {
        "tp_contrib_bps": tp_c, "sl_contrib_bps": sl_c, "time_contrib_bps": round(time_c, 2),
        "gross_bps": round(gross, 2), "fee_2x_bps": 2 * FEE_BPS,
        "margin_over_fee_2x_bps": round(gross - 2 * FEE_BPS, 2),
        "time_share_of_gross_pct": round(abs(time_c) / abs(gross) * 100, 2) if gross else None,
    }
    cf = time_stop_counterfactual(trades)
    null = time_stop_null(trades)
    if null.get("n") and cf.get("leak_bps") is not None:
        null["frac_ge_observed"] = None
        null["observed_bps"] = cf["leak_bps"]
        null["verdict"] = (
            "LEAK_BEYOND_NULL" if cf["leak_bps"] > (null.get("p95_bps") or 1e9) else "INSIDE_NULL_BAND"
        )
    return {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "track": track, "source": str(path),
        "fee_bps": FEE_BPS, "cluster_hours": CLUSTER_HOURS,
        "duplication": duplication(raw),
        "n_signal": len(trades),
        "exit_accounting": acc,
        "binding": binding,
        "geometry": geo,
        "cluster_bootstrap": {
            "mean_bps": round((boot["mean"] or 0) * BPS, 2),
            "ci95_bps": [round(boot["ci95"][0] * BPS, 2), round(boot["ci95"][1] * BPS, 2)] if boot["ci95"] else None,
            "p_pos": boot["p_pos"], "n_blocks": boot["n_blocks"],
        },
        "time_stop_counterfactual": cf,
        "time_stop_null": null,
        "verdict": _verdict(geo, boot, cf, null),
        "safety": {
            "changed_strategy": "NO", "changed_sl_tp_gate_leverage": "NO",
            "placed_order": "NO", "measurement_only": "YES",
        },
    }


def _verdict(geo: dict[str, Any], boot: dict[str, Any], cf: dict[str, Any], null: dict[str, Any]) -> str:
    ci = boot.get("ci95")
    if ci and ci[0] > 0 and cf.get("leak_bps", 0) <= 0:
        return "EDGE_POSITIVE_SIGNIFICANT"
    if null.get("verdict") == "LEAK_BEYOND_NULL":
        return "TIME_STOP_LEAK_REAL_PENDING_RISET"
    return "TIME_STOP_LEAK_INSIDE_NULL_BAND"


def render_md(a: dict[str, Any]) -> str:
    g, acc, cf, null = a["geometry"], a["exit_accounting"], a["time_stop_counterfactual"], a["time_stop_null"]
    L = [
        "# SoDEX D0.5b — Exit-Geometry Diagnostic (read-only)",
        "",
        f"Generated UTC: {a['generated_utc']}",
        f"Track **{a['track']}** · n_signal {a['n_signal']} · fee {a['fee_bps']} bps · cluster {a['cluster_hours']} h",
        "",
        "## Verdict", f"- `{a['verdict']}`",
        f"- Excess mean: {a['cluster_bootstrap']['mean_bps']} bps · CI95 {a['cluster_bootstrap']['ci95_bps']} · p(>0) {a['cluster_bootstrap']['p_pos']}",
        "",
        "## 1. Exit-reason accounting (bps)",
        "| reason | n | share | mean bps | contribution to mean bps | mean hold h | outcome-determined |",
        "|---|---:|---:|---:|---:|---:|:--:|",
    ]
    for r in acc:
        L.append(f"| {r['exit_reason']} | {r['n']} | {r['share']:.1%} | {r['mean_excess_bps']} | {r['contrib_to_mean_bps']} | {r['mean_hold_hours']} | {'yes' if r['outcome_determined'] else 'NO (actionable)'} |")
    L += [
        "",
        "### 1b. Binding constraint",
        "| komponen | bps |",
        "|---|---:|",
        f"| TP contribution | {a['binding']['tp_contrib_bps']} |",
        f"| SL contribution | {a['binding']['sl_contrib_bps']} |",
        f"| time-stop contribution | {a['binding']['time_contrib_bps']} |",
        f"| **gross excess** | **{a['binding']['gross_bps']}** |",
        f"| fee 2× | {a['binding']['fee_2x_bps']} |",
        f"| **margin over 2× fee** | **{a['binding']['margin_over_fee_2x_bps']}** |",
        f"| time-stop as share of gross | {a['binding']['time_share_of_gross_pct']}% |",
        "",
        "## 2. Designed vs realized geometry",
        "**Basis: raw realized price move (bukan beta-neutral excess).** Tabel ini menggambarkan geometri exit apa adanya, bukan alpha. Untuk keputusan gate, yang berlaku adalah excess beta-neutral di bagian 1.",
        "| metric | value |",
        "|---|---:|",
        f"| n planned (tp/sl recorded) | {g['n_planned']} |",
        f"| mean planned TP distance | {g['mean_planned_tp_dist_pct']}% |",
        f"| mean planned SL distance | {g['mean_planned_sl_dist_pct']}% |",
        f"| mean planned R:R | {g['mean_planned_rr']} |",
        f"| mean realized TP | {g['mean_realized_tp_pct']}% (n={g['n_tp']}) |",
        f"| mean realized SL | {g['mean_realized_sl_pct']}% (n={g['n_sl']}) |",
        f"| mean realized R:R | {g.get('mean_realized_rr')} |",
        f"| actual WR | {g['wr']:.1%} |",
        f"| break-even WR (no fee) | {g.get('breakeven_wr_no_fee'):.1%} |" if g.get("breakeven_wr_no_fee") is not None else "| break-even WR (no fee) | n/a |",
        f"| break-even WR (fee 1×) | {g.get('breakeven_wr_fee_1x'):.1%} |" if g.get("breakeven_wr_fee_1x") is not None else "| break-even WR (fee 1×) | n/a |",
        f"| break-even WR (fee 2×) | {g.get('breakeven_wr_fee_2x'):.1%} |" if g.get("breakeven_wr_fee_2x") is not None else "| break-even WR (fee 2×) | n/a |",
        f"| gap to break-even WR at 2× fee | {g.get('breakeven_wr_gap_pp')} pp |",
        f"| fee as share of mean TP | {g.get('fee_share_of_tp_pct')}% |",
        "",
        "## 3. Time-stop leak — paired counterfactual",
        "| metric | value |",
        "|---|---:|",
        f"| n time-stop trades | {cf.get('n_time')} |",
        f"| leak (bps of mean) | {cf.get('leak_bps')} |",
        f"| paired CI95 (bps) | {cf.get('paired_ci95_bps')} |",
        f"| blocks | {cf.get('n_blocks')} |",
        "",
        "## 4. Negative control — shuffled time-stop label",
        f"- draws: {null.get('n')} · null p50 = {null.get('p50_bps')} bps · p95 = **{null.get('p95_bps')}** · p99 = {null.get('p99_bps')}",
        f"- observed leak {null.get('observed_bps')} bps vs null p95 {null.get('p95_bps')} → **{null.get('verdict')}**",
        "- Inside the null band means the time-stop subset is not distinguishable from a randomly chosen subset of the same size.",
        "",
        "## 5. Duplication", f"- rows {a['duplication']['n_rows']} → {a['duplication']['n_unique']} unique pair-hour (ratio {a['duplication']['ratio']})",
        "",
        "## Safety", "- No strategy/SL/TP/gate/leverage change. No order. Measurement-only.", "",
    ]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SoDEX D0.5b exit-geometry diagnostic")
    ap.add_argument("--track", default="twoway")
    ap.add_argument("--out-md", type=Path, default=OUT_MD)
    ap.add_argument("--out-json", type=Path, default=OUT_JSON)
    args = ap.parse_args(argv)
    a = analyse(args.track)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(a, indent=2, ensure_ascii=False, default=str))
    args.out_md.write_text(render_md(a))
    print(json.dumps({
        "json": str(args.out_json), "md": str(args.out_md), "verdict": a["verdict"],
        "wr": a["geometry"]["wr"], "breakeven_wr_fee_2x": a["geometry"].get("breakeven_wr_fee_2x"),
        "breakeven_wr_gap_pp": a["geometry"].get("breakeven_wr_gap_pp"),
        "planned_rr": a["geometry"].get("mean_planned_rr"),
        "time_leak_bps": a["time_stop_counterfactual"].get("leak_bps"),
        "null_p95_bps": a["time_stop_null"].get("p95_bps"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
