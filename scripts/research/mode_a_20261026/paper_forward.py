#!/usr/bin/env python3
"""PRAREG-23b — pencatat paper-forward + evaluator Mode A/B1/B2. DRY-RUN SAJA: tidak ada order, tidak ada kredensial.

  paper_forward.py record <fwd_dir>   # update data Binance, tulis target harian ke ledger (idempoten, backfill terbendera)
  paper_forward.py eval   <fwd_dir>   # hitung metrik + gerbang beku PRAREG-23b dari ledger saja (deterministik)

Ledger  = <fwd_dir>/ledger.jsonl  (append-only; satu baris per tanggal penutupan 'asof'; tidak pernah ditimpa)
Data    = <fwd_dir>/{btc,eth,xaut}.csv  (riwayat harian; dibekukan hash-nya di registry)
"""
from __future__ import annotations
import hashlib, json, math, os, sys, datetime as dt
import numpy as np
import pandas as pd
import mode_a_engine as eng
from bt_indep import simulate, stats

HERE = os.path.dirname(os.path.abspath(__file__))
SYMS = {"btc": "BTCUSDT", "eth": "ETHUSDT", "xaut": "XAUTUSDT"}
MODES = ("A", "B1", "B2")
FIRST_ASOF = pd.Timestamp("2026-10-25")        # target pertama (dieksekusi di penutupan 26-Okt)
WIN_FIRST, WIN_LAST = pd.Timestamp("2026-10-26"), pd.Timestamp("2026-11-25")   # 31 hari-return; 26-Okt = hari entry (biaya beli pertama ikut)
N_WIN = 31
COST = 0.001                                    # 0,10%/sisi (primer); 0,25% = sensitivitas
GATE = {"G3_mdd_min": -10.0, "G4_cum_min": -5.0, "G1_max_backfill": 3, "G1_max_dataerr_days": 2}


def sha(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _read(path):
    if not os.path.exists(path):
        return []
    return [json.loads(x) for x in open(path) if x.strip()]


def _append(path, obj):
    with open(path, "a") as f:
        f.write(json.dumps(obj, sort_keys=True) + "\n")
        f.flush(); os.fsync(f.fileno())


def record(fdir: str, today: pd.Timestamp | None = None, update: bool = True) -> dict:
    led = os.path.join(fdir, "ledger.jsonl")
    today = (today if today is not None else eng.today_utc()).normalize()
    rows = _read(led)
    have = {r["asof"] for r in rows if r.get("kind") == "rec"}
    try:
        if update:
            for k, s in SYMS.items():
                eng.update_history(os.path.join(fdir, f"{k}.csv"), s, today)
        closes = {k: eng.load_csv(os.path.join(fdir, f"{k}.csv")) for k in SYMS}
        eng.validate_closes(closes, today=today)
        th = {m: eng.target_history(closes, mode=m, validate=False) for m in MODES}
    except Exception as e:                                           # fail-closed: tidak ada target, dicatat sebagai kejadian
        _append(led, {"kind": "event", "event": "GAGAL_DATA", "utc": dt.datetime.now(dt.timezone.utc).isoformat(), "pesan": str(e)[:300]})
        return {"status": "GAGAL_DATA", "pesan": str(e)}
    last = closes["btc"].index[-1]
    d = FIRST_ASOF if not have else max(pd.Timestamp(x) for x in have) + pd.Timedelta(days=1)
    esha = sha(os.path.join(HERE, "mode_a_engine.py"))
    wrote = []
    while d <= last and d <= WIN_LAST:
        key = str(d.date())
        if key not in have:
            rec = {"kind": "rec", "asof": key, "backfill": bool(d < last),
                   "closes": {k: float(closes[k].loc[d]) for k in SYMS},
                   "targets": {m: {k: float(th[m].loc[d, k]) for k in SYMS} for m in MODES},
                   "engine_sha256": esha, "utc": dt.datetime.now(dt.timezone.utc).isoformat()}
            _append(led, rec); wrote.append(key)
        d += pd.Timedelta(days=1)
    return {"status": "OK", "ditulis": wrote, "bar_terakhir": str(last.date())}


def evaluate(fdir: str) -> dict:
    rows = _read(os.path.join(fdir, "ledger.jsonl"))
    recs = {r["asof"]: r for r in rows if r.get("kind") == "rec"}
    ev = [r for r in rows if r.get("kind") == "event"]
    out: dict = {"n_rec": len(recs), "events_gagal_data": len(ev)}
    if len(recs) < 2:
        out["vonis"] = "BELUM_ADA_DATA"; return out
    idx = pd.to_datetime(sorted(recs))
    full = pd.date_range(idx[0], idx[-1])
    out["gap_tanggal"] = [str(x.date()) for x in full.difference(idx)]
    px = {k: pd.Series({pd.Timestamp(a): recs[a]["closes"][k] for a in recs}).sort_index() for k in SYMS}
    out["backfill_n"] = sum(1 for r in recs.values() if r["backfill"])
    res = {}
    for m in MODES:
        tg = pd.DataFrame({pd.Timestamp(a): recs[a]["targets"][m] for a in recs}).T.sort_index()
        for cost, tag in ((COST, "c010"), (0.0025, "c025")):
            r, _ = simulate(px, tg, start=str((idx[0] + pd.Timedelta(days=1)).date()), cost=cost)
            r = r.loc[WIN_FIRST:WIN_LAST]
            if len(r) == 0:
                continue
            eq = (1 + r).cumprod(); mdd = float((eq / eq.cummax() - 1).min() * 100)
            n = len(r); mu = float(r.mean()); sd = float(r.std()) if n > 1 else float("nan")
            se = sd / math.sqrt(n) if n > 1 else float("nan")
            res[f"{m}_{tag}"] = {"n": n, "cum_pct": round(float(eq.iloc[-1] - 1) * 100, 3), "M_per5h_pct": round(mu * 5 / 24 * 100, 5),
                                 "ci95_per5h": [round((mu - 1.96 * se) * 5 / 24 * 100, 5), round((mu + 1.96 * se) * 5 / 24 * 100, 5)],
                                 "t": round(mu / se, 2) if se and se > 0 else None, "mdd_pct": round(mdd, 2)}
    out["hasil"] = res
    a = res.get("A_c010")
    n_done = a["n"] if a else 0
    out["n_hari_window"] = n_done
    if n_done < N_WIN:
        out["vonis"] = f"BERJALAN ({n_done}/{N_WIN} hari)"; return out
    g = {"G1_lengkap": bool(not out["gap_tanggal"] and out["backfill_n"] <= GATE["G1_max_backfill"] and out["events_gagal_data"] <= GATE["G1_max_dataerr_days"]),
         "G2_target_cocok_engine": None,
         "G3_mdd_A": bool(a["mdd_pct"] >= GATE["G3_mdd_min"]),
         "G4_cum_A": bool(a["cum_pct"] >= GATE["G4_cum_min"])}
    # G2: hitung ulang target dari harga yang tercatat (tanpa jaringan) — harus identik dengan target di ledger
    full = {k: eng.load_csv(os.path.join(fdir, f"{k}.csv")) for k in SYMS}
    thf = {m: eng.target_history(full, mode=m, validate=False) for m in MODES}
    bad = 0
    for a_, r_ in recs.items():
        for m in MODES:
            for k in SYMS:
                if abs(thf[m].loc[pd.Timestamp(a_), k] - r_["targets"][m][k]) > 1e-12:
                    bad += 1
    g["G2_target_cocok_engine"] = bool(bad == 0); out["g2_selisih"] = bad
    out["gerbang"] = g
    out["vonis"] = "LAYAK_DIPERTIMBANGKAN (butuh keputusan GO user)" if all(g.values()) else "NO-GO"
    out["catatan"] = "B1/B2 tidak punya jalur live dari PRAREG-23b. Target 0,010%/5j dilaporkan, BUKAN gerbang (31 hari tak punya daya)."
    return out


if __name__ == "__main__":
    cmd, fdir = sys.argv[1], sys.argv[2]
    if cmd == "record":
        print(json.dumps(record(fdir), indent=2))
    elif cmd == "eval":
        print(json.dumps(evaluate(fdir), indent=2, default=str))
    else:
        raise SystemExit("perintah: record | eval")
