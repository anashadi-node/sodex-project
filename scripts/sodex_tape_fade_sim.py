#!/usr/bin/env python3
"""Simulasi FADE kejadian ekstrem pada TAPE NYATA SoDEX + biaya dari BUKU L1 NYATA.

Beda mendasar dari R4-D: tidak ada asumsi slippage. Biaya masuk/keluar diambil dari
setengah spread buku L1 yang benar-benar terekam (per simbol, dan per saat bila tersedia).

READ-ONLY: hanya membaca data/sodex_public_trades.db + data/sodex_book_recorder.db.
Tidak menyentuh lane live, gate, leverage, sizing, atau target.

Batas (dinyatakan di muka):
  - Tape hanya 3,0 hari (2026-07-30..08-02) -> n kecil. Hasil = MONITOR, bukan ACTION.
  - Buku L1 hanya 24 jam (2026-08-01..02) -> bila tidak tersedia di saat kejadian,
    dipakai median setengah spread simbol itu (dilaporkan sebagai aproksimasi).
  - Hold 24 jam -> kejadian dalam 24 jam terakhir tape dipotong (exit di akhir tape).
"""
from __future__ import annotations

import json
import sqlite3
import statistics
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TAPE = ROOT / "data" / "sodex_public_trades.db"
BOOK = ROOT / "data" / "sodex_book_recorder.db"
REP = ROOT / "reports" / "sodex"
THETAS = (0.015, 0.02, 0.03, 0.05)
HOLD_S = 24 * 3600
FEE_PER_SIDE = 0.000108      # 0,0108%/sisi — tingkat taker yang terbukti dibayar paper test SoDEX
FEE_ALT = 0.00045            # 0,045%/sisi — tarif taker HL (pembanding)
N_CTRL = 200
SEED = 20261005


def load_tape() -> dict[str, pd.DataFrame]:
    c = sqlite3.connect(f"file:{TAPE}?mode=ro", uri=True)
    df = pd.read_sql_query("SELECT symbol, ts, side, price, qty FROM trades ORDER BY ts", c)
    c.close()
    out = {}
    for s, g in df.groupby("symbol"):
        g = g.reset_index(drop=True)
        out[s] = g
    return out


def load_spreads() -> dict[str, float]:
    """Median setengah spread per simbol dari buku L1 nyata (fraksi, bukan bp)."""
    c = sqlite3.connect(f"file:{BOOK}?mode=ro", uri=True)
    d = pd.read_sql_query("""SELECT symbol, bid, ask FROM l1
                             WHERE bid IS NOT NULL AND ask IS NOT NULL AND bid>0 AND ask>bid""", c)
    c.close()
    d["half"] = (d["ask"] - d["bid"]) / ((d["ask"] + d["bid"]) / 2) / 2.0
    return {s: float(g["half"].median()) for s, g in d.groupby("symbol")}


def bars_1h(g: pd.DataFrame) -> pd.DataFrame:
    t = pd.to_datetime(g["ts"], unit="s", utc=True)
    b = pd.DataFrame({"price": g["price"].to_numpy()}, index=t)
    o = b["price"].resample("1h").agg(["first", "max", "min", "last", "count"]).dropna()
    return o


def run_symbol(sym: str, g: pd.DataFrame, half: float, fee: float, theta: float, ctrl: bool, rng, mode: str = "fade") -> list[dict]:
    b = bars_1h(g)
    if len(b) < 30:
        return []
    ret = b["last"].pct_change().to_numpy()
    ts = b.index.astype("int64").to_numpy().astype(float) / 1e9   # epoch detik
    t_arr = g["ts"].to_numpy()
    p_arr = g["price"].to_numpy()
    res = []
    if ctrl:
        lo, hi = 1, len(b) - 2
        if hi <= lo:
            return []
        idxs = rng.integers(lo, hi, size=min(60, hi - lo))
    else:
        idxs = [i for i in range(1, len(b) - 1) if np.isfinite(ret[i]) and abs(ret[i]) >= theta]
    for i in idxs:
        _dir = 1.0 if ret[i] > 0 else -1.0
        d = -_dir if mode == "fade" else _dir    # fade = melawan bar; momentum = searah bar
        t_ev = ts[i]
        # masuk: trade pertama setelah bar kejadian
        j = int(np.searchsorted(t_arr, t_ev, side="right"))
        if j >= len(t_arr):
            continue
        p_in = p_arr[j] * (1.0 + d * half)        # menyeberang setengah spread
        t_exit_target = t_arr[j] + HOLD_S
        k = int(np.searchsorted(t_arr, t_exit_target, side="left"))
        if k >= len(t_arr):
            k = len(t_arr) - 1
        p_out = p_arr[k] * (1.0 - d * half)
        gross = d * (p_out / p_in - 1.0)
        net = gross - 2 * fee
        res.append({"sym": sym, "t": t_arr[j], "gross": gross, "net": net,
                    "half_bp": half * 1e4, "filled": True})
    return res


def main() -> int:
    tape = load_tape()
    spreads = load_spreads()
    rng = np.random.default_rng(SEED)
    print(f"[TAPE] {len(tape)} simbol · {sum(len(g) for g in tape.values()):,} trade")
    out = {"sumber": "tape SoDEX nyata + buku L1 nyata", "fee_per_side": FEE_PER_SIDE,
           "n_ctrl": N_CTRL, "results": {}}
    for mode in ("fade", "momentum"):
      for fee, flabel in ((FEE_PER_SIDE, "fee 0,0108%/sisi"), (FEE_ALT, "fee 0,045%/sisi")):
        for theta in THETAS:
            tr, ct = [], []
            for sym, g in tape.items():
                half = spreads.get(sym, 0.0001)
                tr += run_symbol(sym, g, half, fee, theta, False, rng, mode)
                ct += run_symbol(sym, g, half, fee, theta, True, rng, mode)
            if not tr:
                continue
            net = np.array([x["net"] for x in tr])
            gro = np.array([x["gross"] for x in tr])
            cnet = np.array([x["net"] for x in ct]) if ct else np.array([0.0])
            p_ctrl = float((cnet >= net.mean()).mean()) if len(ct) else float("nan")
            key = f"{mode}_theta_{theta}_{'fee108' if fee==FEE_PER_SIDE else 'fee45'}"
            out["results"][key] = {
                "mode": mode, "theta_pct": theta * 100, "fee_label": flabel, "n": len(net),
                "mean_net_pct": round(float(net.mean()) * 100, 4),
                "median_net_pct": round(float(np.median(net)) * 100, 4),
                "wr_pct": round(float((net > 0).mean()) * 100, 1),
                "mean_gross_pct": round(float(gro.mean()) * 100, 4),
                "mean_half_spread_bp": round(float(np.mean([x["half_bp"] for x in tr])), 3),
                "ctrl_mean_pct": round(float(cnet.mean()) * 100, 4), "ctrl_p": round(p_ctrl, 4),
                "n_ctrl": len(ct),
            }
            r = out["results"][key]
            print(f"[TAPE] {mode:8} theta={theta:.1%} {flabel}: n={r['n']} net={r['mean_net_pct']:+.4f}% "
                  f"bruto={r['mean_gross_pct']:+.4f}% menang={r['wr_pct']:.1f}% "
                  f"spread={r['mean_half_spread_bp']:.2f}bp ctrl={r['ctrl_mean_pct']:+.4f}% p={r['ctrl_p']:.4f}")
    REP.mkdir(parents=True, exist_ok=True)
    p = REP / "TAPE_SODEX_fade_results.json"
    p.write_text(json.dumps(out, indent=1))
    print(f"[TAPE] tersimpan: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
