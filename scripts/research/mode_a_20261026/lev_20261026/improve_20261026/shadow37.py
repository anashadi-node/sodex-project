#!/usr/bin/env python3
"""PRAREG-37 SHADOW — mencatat varian vol-target (25%, cap 2,5) berdampingan dengan PRAREG-36.
Tanpa order, tanpa modal, tanpa mengubah sel/gate PRAREG-36. Tujuan: data forward nyata untuk
membandingkan alokasi risiko, bukan untuk mengklaim edge."""
from __future__ import annotations
import json, math, os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); LEV = os.path.dirname(HERE); PARENT = os.path.dirname(LEV)
sys.path.insert(0, LEV); sys.path.insert(0, PARENT); sys.path.insert(0, os.path.dirname(PARENT))
import hybrid36 as h36, lev_study as ls, mode_a_engine as eng  # noqa

VT, CAP, FLOOR = 0.25, 2.5, 1.0
COLS = ["btc", "eth", "xaut"]; COST = 0.0010


def extend_funding(f, ledger_path):
    """Sambung funding BEKU (CSV berhenti 2026-10-26, hari terakhir parsial) dengan funding forward
    dari ledger hybrid36 (sumber sama: Binance fapi publik, unit sama bps/hari; hari tumpang-tindih
    2026-10-25 identik). Hanya hari SETELAH hari penuh terakhir yang diganti. Aturan cakupan >1%
    => StudyError di build_fund TIDAK dilonggarkan: hari tanpa data tetap kosong."""
    if not os.path.exists(ledger_path):
        return f
    led = [json.loads(x) for x in open(ledger_path) if x.strip()]
    corr = {r["asof"]: r.get("funding_bps") for r in led if r.get("event") == "KOREKSI_FUNDING"}
    fw = {r["asof"]: (corr.get(r["asof"]) or r.get("funding_bps")) for r in led if r.get("kind") == "rec"}
    out = dict(f)
    for n in ("btc", "eth"):
        s = f[n]; day = s.index.normalize(); cnt = s.groupby(day).count()
        last_full = cnt[cnt >= 3].index.max()
        add = {pd.Timestamp(a): float(v[n]) for a, v in fw.items()
               if v and v.get(n) is not None and math.isfinite(float(v[n])) and pd.Timestamp(a) > last_full}
        out[n] = pd.concat([s[day <= last_full], pd.Series(add, dtype=float)]).sort_index()
    return out


def load(fdir):
    px = {}
    for k in COLS:
        p = os.path.join(fdir, f"{k}.csv")
        px[k] = pd.read_csv(p, index_col="date", parse_dates=True)["close"]
    P = pd.DataFrame(px).dropna()
    _, _, f = ls.load_all()
    f = extend_funding(f, os.path.join(fdir, "ledger.jsonl"))
    return P, ls.build_fund(P, f)


def series(fdir):
    P, fund = load(fdir)
    T = eng.target_history({k: P[k] for k in COLS}, mode="B2", validate=False)
    r1 = (T.shift(1) * P.pct_change(fill_method=None)).sum(axis=1)
    volp = r1.rolling(20).std() * math.sqrt(365)
    L = (VT / volp).clip(FLOOR, CAP)
    R = P.pct_change(fill_method=None).fillna(0.0)
    F = fund.reindex(P.index).fillna(0.0)[COLS] if len(fund) else pd.DataFrame(0.0, index=P.index, columns=COLS)
    E = T * L.values[:, None]
    Ep = E.shift(1).fillna(0.0)
    gross = (Ep * R).sum(axis=1)
    turn = (E - Ep * (1 + R)).abs().sum(axis=1)
    perp = (E - E.clip(lower=0, upper=1))
    net = gross - turn * COST - (perp * F / 1e4).sum(axis=1)
    out = pd.DataFrame({"L": L, "net": net, "gross": gross}).iloc[21:]
    eq = (1 + out["net"].clip(lower=-0.999999)).cumprod()
    out["equity"] = eq; out["mdd"] = eq / eq.cummax() - 1
    return out.dropna()


def record(fdir):
    os.makedirs(fdir, exist_ok=True)
    s = series(os.path.join(LEV, "forward36"))
    last = s.index[-1]
    p = os.path.join(fdir, "shadow_ledger.jsonl")
    have = set()
    if os.path.exists(p):
        have = {json.loads(x)["asof"] for x in open(p)}
    # isi SEMUA hari yang belum tercatat sejak hari pertama ledger (celah akibat run gagal);
    # baris yang diisi belakangan diberi backfill=True. Nilai dihitung kausal dari data <= hari itu.
    start = min(have) if have else str(last.date())
    todo = [d for d in s.index if str(d.date()) >= start and str(d.date()) not in have]
    if not todo:
        print(f"asof {last.date()} sudah tercatat — tidak menulis ulang"); return
    with open(p, "a") as fh:
        for d in todo:
            row = s.loc[d]
            rec = {"kind": "shadow", "asof": str(d.date()), "L": round(float(row["L"]), 4),
                   "net": float(row["net"]), "equity": float(row["equity"]), "mdd": float(row["mdd"]),
                   "varian": f"voltarget {VT:.2f} cap {CAP} floor {FLOOR}"}
            if d != last:
                rec["backfill"] = True
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
            print(f"tercatat asof {d.date()} L={rec['L']} net={rec['net']:.6f} equity={rec['equity']:.4f}"
                  + (" [backfill]" if d != last else ""))


def status(fdir):
    p = os.path.join(fdir, "shadow_ledger.jsonl")
    if not os.path.exists(p): print("BELUM_ADA_DATA"); return
    rows = [json.loads(x) for x in open(p)]
    s = pd.DataFrame(rows).set_index("asof").sort_index()      # backfill ditulis belakangan => urutkan per asof
    n = len(s); eq = float(s["equity"].iloc[-1]); mdd = float(s["mdd"].min()) * 100
    mu = float(s["net"].mean())
    print(json.dumps({"n_hari": n, "dari": s.index[0], "sampai": s.index[-1], "equity": round(eq, 4),
                      "M_per5h_pct": round(mu * 5 / 24 * 100, 5), "mdd_pct": round(mdd, 2),
                      "L_rata2": round(float(s["L"].mean()), 3)}, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    d = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "shadow37")
    {"record": record, "status": status}[cmd](d)
