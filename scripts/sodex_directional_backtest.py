#!/usr/bin/env python3
"""SoDEX directional edge backtest — READ-ONLY, no orders, no capital.

Question this answers: is there ANY directional signal on SoDEX perps whose
forward mid-move beats realistic taker cost (spread + fee), out-of-sample?

It reads the L1 book recorder (mid-price series, all symbols) and, where
available, the public-trade recorder (aggressor side → order-flow imbalance).
It builds 1-minute mid bars, evaluates three signal families, and validates the
train-selected best variant on a chronological OOS holdout. Pure IO + pure math,
no exchange client, no order path.

Signals:
  MOM_k   momentum  — trade WITH sign of return over past k minutes
  REV_k   reversion — trade AGAINST that return (deviation from k-bar mean)
  OFI_k   order-flow imbalance (needs trades db) — WITH net aggressor sign

Cost model (taker in / taker out, conservative):
  cost_bps = spread_bps + 2 * taker_fee_bps_per_leg
An entry only "wins" if signed forward mid-return exceeds this cost.
"""
from __future__ import annotations

import argparse
import math
import sqlite3
import statistics
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
BOOK_DB = PROJECT / "data" / "sodex_book_recorder.db"
TRADES_DB = PROJECT / "data" / "sodex_public_trades.db"

TAKER_FEE_BPS_PER_LEG = 2.0  # SoDEX taker ≈ 0.02%/leg (queue-fill lab cost model)
BAR_SEC = 60                 # 1-minute bars
TRAIN_FRAC = 0.60            # chronological train / OOS split


# ── data loading ─────────────────────────────────────────────────────────────
def load_bars(symbol: str, db: Path = BOOK_DB) -> list[dict]:
    """1-minute mid bars for one symbol: {t, mid, spread_bps}. Last snap per minute."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT ts, bid, ask FROM l1 WHERE symbol=? AND bid>0 AND ask>0 ORDER BY ts",
            (symbol,),
        ).fetchall()
    finally:
        con.close()
    buckets: dict[int, tuple] = {}
    for ts, bid, ask in rows:
        b = int(ts // BAR_SEC)
        buckets[b] = (bid, ask)  # keep last snap in the minute
    bars = []
    for b in sorted(buckets):
        bid, ask = buckets[b]
        mid = (bid + ask) / 2.0
        if mid <= 0:
            continue
        spread_bps = (ask - bid) / mid * 1e4
        bars.append({"t": b, "mid": mid, "spread_bps": spread_bps})
    return bars


def median_spread_bps(symbol: str, db: Path = BOOK_DB) -> float:
    """Median L1 spread (bps) for a symbol from the 24h book — cost proxy for
    the 3-day trades-price backtest where no book snapshot exists."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT bid, ask FROM l1 WHERE symbol=? AND bid>0 AND ask>0", (symbol,)
        ).fetchall()
    finally:
        con.close()
    sp = [(a - b) / ((a + b) / 2) * 1e4 for b, a in rows if (a + b) > 0]
    return statistics.median(sp) if sp else 999.0


def load_bars_from_trades(symbol: str, db: Path = TRADES_DB,
                          spread_bps: float = 0.0) -> list[dict]:
    """1-minute bars from public trade prices (last trade in minute). Spans the
    full 3-day trade history. spread_bps attached as fixed cost proxy."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT ts, price FROM trades WHERE symbol=? AND price>0 ORDER BY ts", (symbol,)
        ).fetchall()
    finally:
        con.close()
    buckets: dict[int, float] = {}
    for ts, price in rows:
        buckets[int(ts // BAR_SEC)] = price
    return [{"t": b, "mid": buckets[b], "spread_bps": spread_bps} for b in sorted(buckets)]


def list_symbols(db: Path = BOOK_DB) -> list[str]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return [r[0] for r in con.execute(
            "SELECT symbol, COUNT(*) n FROM l1 GROUP BY symbol HAVING n>500 ORDER BY n DESC"
        ).fetchall()]
    finally:
        con.close()


def load_ofi_bars(symbol: str, db: Path = TRADES_DB) -> dict[int, float]:
    """Per-minute net aggressor notional (BUY +, SELL -) for one symbol."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT ts, side, price, qty FROM trades WHERE symbol=? ORDER BY ts", (symbol,)
        ).fetchall()
    finally:
        con.close()
    ofi: dict[int, float] = {}
    for ts, side, price, qty in rows:
        b = int(ts // BAR_SEC)
        notional = (price or 0) * (qty or 0)
        s = str(side).upper()
        signed = notional if s.startswith("B") else -notional
        ofi[b] = ofi.get(b, 0.0) + signed
    return ofi


# ── signal evaluation ────────────────────────────────────────────────────────
def _fwd_ret_bps(bars: list[dict], i: int, h: int) -> float | None:
    if i + h >= len(bars):
        return None
    return (bars[i + h]["mid"] / bars[i]["mid"] - 1.0) * 1e4


def gen_trades(bars: list[dict], ofi: dict[int, float], sig: str, k: int, h: int,
               thr_bps: float, non_overlap: bool = True) -> list[tuple[int, float, float]]:
    """Return list of (bar_time, signed_fwd_ret_bps, spread_bps) for entries.

    Position sign is +1 long / -1 short. signed_fwd_ret_bps is position*forward.
    Bars must be contiguous in the minute grid for the lookback to be valid; we
    skip entries whose k-back or h-forward bar has a time gap. With non_overlap
    (default), once an entry is taken the next candidate must start >= h bars
    later — removes the overlapping-hold inflation that fakes significance."""
    out = []
    n = len(bars)
    last_exit_t = -1
    for i in range(k, n - h):
        if non_overlap and bars[i]["t"] < last_exit_t:
            continue
        # require contiguous minute grid over [i-k, i+h]
        if bars[i]["t"] - bars[i - k]["t"] != k:
            continue
        if bars[i + h]["t"] - bars[i]["t"] != h:
            continue
        if sig in ("MOM", "REV"):
            past = (bars[i]["mid"] / bars[i - k]["mid"] - 1.0) * 1e4
            if abs(past) < thr_bps:
                continue
            pos = (1 if past > 0 else -1) if sig == "MOM" else (-1 if past > 0 else 1)
        elif sig == "OFI":
            flow = sum(ofi.get(bars[j]["t"], 0.0) for j in range(i - k + 1, i + 1))
            if abs(flow) < thr_bps:  # thr_bps here = min notional USD
                continue
            pos = 1 if flow > 0 else -1
        else:
            continue
        fwd = _fwd_ret_bps(bars, i, h)
        if fwd is None:
            continue
        out.append((bars[i]["t"], pos * fwd, bars[i]["spread_bps"]))
        last_exit_t = bars[i]["t"] + h  # block overlapping entries until this hold closes
    return out


def stats(trades: list[tuple[int, float, float]], with_cost: bool = True) -> dict:
    if not trades:
        return {"n": 0, "mean_bps": 0.0, "wr": 0.0, "sharpe": 0.0, "sum_bps": 0.0}
    pnls = []
    for _, signed_fwd, spread in trades:
        cost = (spread + 2 * TAKER_FEE_BPS_PER_LEG) if with_cost else 0.0
        pnls.append(signed_fwd - cost)
    mean = statistics.mean(pnls)
    sd = statistics.pstdev(pnls) if len(pnls) > 1 else 0.0
    wr = sum(1 for p in pnls if p > 0) / len(pnls)
    sharpe = (mean / sd * math.sqrt(len(pnls))) if sd > 0 else 0.0
    return {"n": len(pnls), "mean_bps": mean, "wr": wr, "sharpe": sharpe, "sum_bps": sum(pnls)}


def split_trades(trades: list, bars: list[dict]) -> tuple[list, list]:
    if not bars:
        return [], []
    t0, t1 = bars[0]["t"], bars[-1]["t"]
    cut = t0 + int((t1 - t0) * TRAIN_FRAC)
    train = [t for t in trades if t[0] <= cut]
    oos = [t for t in trades if t[0] > cut]
    return train, oos


# ── sweep driver ─────────────────────────────────────────────────────────────
def run_sweep(symbols: list[str], families: list[str], verbose: bool = True,
              mode: str = "book") -> dict:
    """Pool trades across symbols for each (signal,k,h,thr) variant, split
    chronologically, select the best variant by TRAIN Sharpe, report its OOS.

    mode='book'  : 24h L1 mid bars, all liquid symbols.
    mode='trades': 3-day bars built from public trade prices (12 stock symbols),
                   real OFI, fixed median-spread cost proxy."""
    KS = [3, 5, 10, 15, 30]
    HS = [5, 10, 15, 30, 60]
    MOM_THR = [3.0, 5.0, 10.0, 20.0]        # bps of past move
    OFI_THR = [1000.0, 5000.0, 20000.0]     # min net notional USD

    # preload bars + ofi once per symbol
    data = {}
    need_ofi = "OFI" in families
    for s in symbols:
        if mode == "trades":
            sp = median_spread_bps(s)
            bars = load_bars_from_trades(s, spread_bps=sp)
        else:
            bars = load_bars(s)
        if len(bars) < 200:
            continue
        ofi = load_ofi_bars(s) if need_ofi else {}
        data[s] = (bars, ofi)
    if verbose:
        print(f"loaded {len(data)} symbols with usable bars (mode={mode})")

    variants = []
    for fam in families:
        thrs = OFI_THR if fam == "OFI" else MOM_THR
        for k in KS:
            for h in HS:
                for thr in thrs:
                    variants.append((fam, k, h, thr))

    results = []
    for (fam, k, h, thr) in variants:
        pooled_train, pooled_oos = [], []
        for s, (bars, ofi) in data.items():
            if fam == "OFI" and not ofi:
                continue
            trs = gen_trades(bars, ofi, fam, k, h, thr)
            tr, oo = split_trades(trs, bars)
            pooled_train.extend(tr)
            pooled_oos.extend(oo)
        st_tr = stats(pooled_train, with_cost=True)
        st_oo = stats(pooled_oos, with_cost=True)
        st_tr_gross = stats(pooled_train, with_cost=False)
        results.append({
            "variant": f"{fam}_k{k}_h{h}_thr{thr:g}",
            "fam": fam, "k": k, "h": h, "thr": thr,
            "train": st_tr, "oos": st_oo, "train_gross": st_tr_gross,
        })

    # rank by TRAIN net mean-bps (edge magnitude) with a minimum sample floor
    ranked = [r for r in results if r["train"]["n"] >= 100]
    ranked.sort(key=lambda r: -r["train"]["mean_bps"])

    # per-symbol OOS consistency for the train-selected best (robustness check)
    per_sym = {}
    if ranked:
        b = ranked[0]
        for s, (bars, ofi) in data.items():
            if b["fam"] == "OFI" and not ofi:
                continue
            trs = gen_trades(bars, ofi, b["fam"], b["k"], b["h"], b["thr"])
            _, oo = split_trades(trs, bars)
            st = stats(oo, with_cost=True)
            if st["n"] >= 5:
                per_sym[s] = st
    return {"n_symbols": len(data), "n_variants": len(variants), "mode": mode,
            "results": results, "ranked": ranked, "best_per_symbol_oos": per_sym}


def _fmt(res: dict, top: int = 15) -> str:
    L = [f"SoDEX DIRECTIONAL BACKTEST — {res['n_symbols']} symbols, "
         f"{res['n_variants']} variants (net of spread+fee)",
         "",
         f"{'variant':22} {'trN':>5} {'trGrossBps':>10} {'trNetBps':>9} "
         f"{'trShrp':>7} | {'oosN':>5} {'oosNetBps':>9} {'oosWR':>6} {'oosShrp':>7}",
         "-" * 100]
    for r in res["ranked"][:top]:
        t, o, g = r["train"], r["oos"], r["train_gross"]
        L.append(f"{r['variant']:22} {t['n']:5} {g['mean_bps']:10.2f} {t['mean_bps']:9.2f} "
                 f"{t['sharpe']:7.2f} | {o['n']:5} {o['mean_bps']:9.2f} "
                 f"{o['wr']*100:5.1f}% {o['sharpe']:7.2f}")
    # honest verdict on the TRAIN-selected best: require BOTH positive pooled OOS
    # AND per-symbol consistency (majority of symbols positive) to rule out the
    # "one trending window / one symbol" regime-luck illusion.
    if res["ranked"]:
        best = res["ranked"][0]
        o = best["oos"]
        ps = res.get("best_per_symbol_oos", {})
        n_sym = len(ps)
        n_pos = sum(1 for st in ps.values() if st["mean_bps"] > 0)
        frac_pos = (n_pos / n_sym) if n_sym else 0.0
        pooled_ok = o["mean_bps"] > 0 and o["n"] >= 100
        consistent = n_sym >= 5 and frac_pos >= 0.60
        L += ["", f"TRAIN-selected best: {best['variant']}",
              f"  OOS pooled: n={o['n']} net={o['mean_bps']:.2f}bps WR={o['wr']*100:.1f}% "
              f"sum={o['sum_bps']:.0f}bps",
              f"  OOS per-symbol consistency: {n_pos}/{n_sym} positive ({frac_pos*100:.0f}%)",
              f"  VERDICT: {'✅ ROBUST OOS EDGE' if (pooled_ok and consistent) else '❌ NO ROBUST EDGE (pooled-luck or inconsistent)'}"]
        # show per-symbol breakdown
        if ps:
            L += ["", "  Per-symbol OOS (best variant):"]
            for s, st in sorted(ps.items(), key=lambda kv: -kv[1]["mean_bps"]):
                L.append(f"    {s:16} n={st['n']:4} net={st['mean_bps']:7.2f}bps "
                         f"WR={st['wr']*100:5.1f}%")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="SoDEX directional edge backtest (read-only)")
    ap.add_argument("--families", default="MOM,REV,OFI",
                    help="comma list: MOM,REV,OFI")
    ap.add_argument("--symbols", default="", help="comma list; default = all liquid")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--mode", default="book", choices=["book", "trades"])
    args = ap.parse_args()
    fams = [f.strip().upper() for f in args.families.split(",") if f.strip()]
    if args.symbols:
        syms = [s.strip() for s in args.symbols.split(",") if s.strip()]
    elif args.mode == "trades":
        con = sqlite3.connect(f"file:{TRADES_DB}?mode=ro", uri=True)
        syms = [r[0] for r in con.execute(
            "SELECT symbol, COUNT(*) n FROM trades GROUP BY symbol HAVING n>2000 ORDER BY n DESC"
        ).fetchall()]
        con.close()
    else:
        syms = list_symbols()
    res = run_sweep(syms, fams, mode=args.mode)
    print(_fmt(res, args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
