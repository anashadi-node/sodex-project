#!/usr/bin/env python3
"""PRAREG-36 — pencatat + evaluator paper-forward HYBRID (spot + perp). DRY-RUN: tanpa order, tanpa kredensial.

  hybrid36.py record <dir>   # update harga, catat closes+target+funding harian ke ledger (append-only, idempoten)
  hybrid36.py eval   <dir>   # hitung metrik + 7 gerbang beku dari ledger saja (deterministik, tanpa jaringan)
  hybrid36.py status <dir>   # ringkas progres jendela
"""
from __future__ import annotations
import contextlib, fcntl, hashlib, json, math, os, sys, datetime as dt
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); PARENT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, PARENT)
import mode_a_engine as eng
import lev_hybrid as lh
import lev_study as ls

SYMS = ("btc", "eth", "xaut")
SENG = {"btc": "BTCUSDT", "eth": "ETHUSDT", "xaut": "XAUTUSDT"}
# ===================== PLAN BEKU (PRAREG-36) =====================
PLAN36 = dict(
    cells={"B2": 1.5, "A": 2.0}, primary="B2", comparator="A",
    first_asof="2026-10-25", win_first="2026-10-26", win_last="2026-11-24", n_win=30,
    cost=0.0010, p_bh=0.025, alpha=0.05, target_M=0.010, mdd_cap=-35.0,
    stress=1.5, near_liq=0.20, seed=36, n_boot=5000, block=5,
    g1_max_backfill=3, g1_max_dataerr=2,
)


def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()


@contextlib.contextmanager
def _lock(fdir: str):
    """Kunci eksklusif per direktori: dua proses record bersamaan tidak boleh menulis rec ganda."""
    os.makedirs(fdir, exist_ok=True)
    with open(os.path.join(fdir, ".ledger.lock"), "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _read(p):
    return [json.loads(x) for x in open(p) if x.strip()] if os.path.exists(p) else []


_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))


def resolve_fdir(fdir: str) -> str:
    """Path relatif (mis. 'forward36') diselesaikan ke direktori modul, bukan cwd.
    Tanpa ini, `hybrid36.py eval forward36` dari root repo membaca ledger kosong
    dan melaporkan 'BELUM_ADA_DATA' padahal 8 rec ada di disk (silent zero)."""
    if os.path.isdir(fdir):
        return fdir
    cand = os.path.join(_MODULE_DIR, fdir)
    return cand if os.path.isdir(cand) else fdir



def _append(path, obj):
    with open(path, "a") as f:
        f.write(json.dumps(obj, sort_keys=True) + "\n"); f.flush(); os.fsync(f.fileno())


def _funding_bps(day: pd.Timestamp) -> dict:
    """Funding Binance per tanggal UTC (bps/hari). Gagal jaringan -> None (dicatat, tidak mengarang)."""
    try:
        import fetch_lev_data as fl
        out = {}
        for k, s in (("btc", "BTCUSDT"), ("eth", "ETHUSDT")):
            d = fl.funding(s)                     # Series bps/8 jam, indeks waktu
            ser = d.groupby(pd.to_datetime(d.index).normalize()).sum()
            out[k] = float(ser.get(day, np.nan))
        out["xaut"] = out["btc"]                    # proksi (dicatat di dokumen)
        return out
    except Exception:
        return None


def record(fdir: str, today: pd.Timestamp | None = None, update: bool = True, fetch_funding: bool = True) -> dict:
    with _lock(fdir):
        return _record_locked(fdir, today, update, fetch_funding)


def _record_locked(fdir: str, today: pd.Timestamp | None, update: bool, fetch_funding: bool) -> dict:
    led = os.path.join(fdir, "ledger.jsonl"); os.makedirs(fdir, exist_ok=True); open(led, "a").close()
    today = (today if today is not None else eng.today_utc()).normalize()
    rows = _read(led); have = {r["asof"] for r in rows if r.get("kind") == "rec"}
    try:
        if update:
            for k, s in SENG.items():
                p = os.path.join(fdir, f"{k}.csv")
                if not os.path.exists(p):                      # seed: riwayat tervalidasi dari Mode A, fallback fetch penuh
                    src = os.path.join(PARENT, "forward", f"{k}.csv")
                    if os.path.exists(src):
                        import shutil; shutil.copy(src, p)
                    else:
                        d = eng.fetch_binance_daily(s, 1502928000000, today)
                        d.rename("close").to_csv(p, index_label="date")
                eng.update_history(p, s, today)
        closes = {k: eng.load_csv(os.path.join(fdir, f"{k}.csv")) for k in SYMS}
        eng.validate_closes(closes, today=today)
        th = {a: eng.target_history(closes, mode=a, validate=False) for a in PLAN36["cells"]}
    except Exception as e:
        _append(led, {"kind": "event", "event": "GAGAL_DATA", "utc": dt.datetime.now(dt.timezone.utc).isoformat(), "pesan": str(e)[:300]})
        return {"status": "GAGAL_DATA", "pesan": str(e)}
    last = closes["btc"].index[-1]
    d = pd.Timestamp(PLAN36["first_asof"]) if not have else max(pd.Timestamp(x) for x in have) + pd.Timedelta(days=1)
    esha = sha(os.path.join(PARENT, "mode_a_engine.py")); wrote = []
    while d <= last and d <= pd.Timestamp(PLAN36["win_last"]):
        key = str(d.date())
        if key not in have:
            fb = _funding_bps(d) if fetch_funding else None
            _append(led, {"kind": "rec", "asof": key, "backfill": bool(d < last),
                          "closes": {k: float(closes[k].loc[d]) for k in SYMS},
                          "targets": {a: {k: float(th[a].loc[d, k]) for k in SYMS} for a in PLAN36["cells"]},
                          "funding_bps": fb, "engine_sha256": esha, "utc": dt.datetime.now(dt.timezone.utc).isoformat()})
            wrote.append(key)
        d += pd.Timedelta(days=1)
    return {"status": "OK", "ditulis": wrote, "bar_terakhir": str(last.date()), "sel": PLAN36["cells"]}


def _corrections(rows) -> dict:
    """KOREKSI_FUNDING append-only: asof -> {btc,eth,xaut}. Baris rec tidak pernah ditimpa."""
    c = {}
    for r in rows:
        if r.get("kind") == "event" and r.get("event") == "KOREKSI_FUNDING":
            c[r["asof"]] = r["funding_bps"]
    return c


def refund(fdir: str) -> dict:
    """Isi funding yang NULL pada rec lama dengan event koreksi (bukan menimpa ledger)."""
    led = os.path.join(fdir, "ledger.jsonl"); rows = _read(led); corr = _corrections(rows); n = 0
    for r in rows:
        if r.get("kind") != "rec" or r.get("funding_bps") or r["asof"] in corr:
            continue
        fb = _funding_bps(pd.Timestamp(r["asof"]))
        if fb is None:
            return {"status": "GAGAL_FUNDING", "asof": r["asof"]}
        _append(led, {"kind": "event", "event": "KOREKSI_FUNDING", "asof": r["asof"], "funding_bps": fb,
                      "utc": dt.datetime.now(dt.timezone.utc).isoformat(), "alasan": "rec awal ditulis saat jalur funding masih bug (Series vs DataFrame)"})
        n += 1
    return {"status": "OK", "dikoreksi": n}


def _frame(recs):
    asof = sorted(recs)
    px = pd.DataFrame({k: [recs[a]["closes"][k] for a in asof] for k in SYMS}, index=pd.to_datetime(asof))
    tg = {arm: pd.DataFrame({k: [recs[a]["targets"][arm][k] for a in asof] for k in SYMS}, index=pd.to_datetime(asof)) for arm in PLAN36["cells"]}
    fd = pd.DataFrame({k: [float((recs[a].get("funding_bps") or {}).get(k, np.nan)) for a in asof] for k in SYMS}, index=pd.to_datetime(asof))
    return px, tg, fd


def _metrics(r: pd.Series) -> dict:
    n = len(r); mu = float(r.mean()) if n else float("nan"); sd = float(r.std(ddof=1)) if n > 1 else float("nan")
    eq = (1 + r.clip(lower=-0.999999)).cumprod(); mdd = float((eq / eq.cummax() - 1).min() * 100) if n else float("nan")
    w31 = r.rolling(PLAN36["n_win"]).apply(lambda x: (1 + x).prod() - 1, raw=True).dropna()
    return {"n": n, "M_per5h_pct": round(mu * 5 / 24 * 100, 5), "cum_pct": round(float(eq.iloc[-1] - 1) * 100, 3) if n else None,
            "mdd_pct": round(mdd, 2), "vol_harian_pct": round(sd * 100, 3) if n > 1 else None,
            "win30_terburuk_pct": round(float(w31.min() * 100), 2) if len(w31) else None,
            "win30_positif": round(float((w31 > 0).mean()), 3) if len(w31) else None}


def _boot(r: pd.Series, seed=PLAN36["seed"], nb=PLAN36["n_boot"], bl=PLAN36["block"]) -> float:
    x = r.values; n = len(x)
    if n < 10: return 1.0
    rng = np.random.default_rng(seed); k = math.ceil(n / bl)
    st = rng.integers(0, n - bl + 1, size=(nb, k)); ix = (st[:, :, None] + np.arange(bl)[None, None, :]).reshape(nb, -1)[:, :n]
    m = x[ix].mean(axis=1) * 5 / 24 * 100
    return round(float((m <= 0).mean()), 4)


def evaluate(fdir: str, win_first: str | None = None, win_last: str | None = None) -> dict:
    led = os.path.join(fdir, "ledger.jsonl")
    if not os.path.exists(led):
        # Fail-closed: ledger hilang = kegagalan data, BUKAN "belum mulai".
        return {"n_rec": 0, "events_gagal_data": 0, "sel": PLAN36["cells"],
                "vonis": "GAGAL_DATA", "error": f"ledger tidak ada: {led}"}
    rows = _read(led)
    recs = {r["asof"]: r for r in rows if r.get("kind") == "rec"}
    errs = [r for r in rows if r.get("kind") == "event" and r.get("event") == "GAGAL_DATA"]
    out = {"n_rec": len(recs), "events_gagal_data": len(errs), "sel": PLAN36["cells"]}
    if not recs:
        out["vonis"] = "BELUM_ADA_DATA"; return out
    wf = win_first or PLAN36["win_first"]; wl = win_last or PLAN36["win_last"]
    if len(recs) < 2:                                        # baru 1 baris: cukup untuk status, belum bisa dihitung
        out["n_hari_window"] = int(pd.Series(pd.to_datetime(list(recs))).between(wf, wl).sum())
        out["vonis"] = f"BERJALAN ({out['n_hari_window']}/{PLAN36['n_win']} hari)"; return out
    corr = _corrections(rows)
    for a, fb in corr.items():
        if a in recs: recs[a]["funding_bps"] = fb
    px, tg, fd = _frame(recs); idx = px.index
    out["gap_tanggal"] = [str(x.date()) for x in pd.date_range(idx[0], idx[-1]).difference(idx)]
    out["backfill_n"] = sum(1 for r in recs.values() if r.get("backfill"))
    out["funding_hilang_hari"] = int(fd.isna().any(axis=1).sum())
    out["funding_hilang_di_jendela"] = int(fd.loc[wf:wl].isna().any(axis=1).sum())
    # gerak merugikan berbasis penutupan (keterbatasan dicatat di dokumen)
    ret = px.pct_change(fill_method=None)
    adv = ret.clip(upper=0.0).fillna(0.0)
    res, pvals = {}, {}
    for arm, L in PLAN36["cells"].items():
        f = fd.copy()
        if f.isna().any().any():
            f = f.ffill().fillna(0.0)
        sim = lh.hybrid_sim(px, tg[arm], L, str(idx[0].date()), PLAN36["cost"], PLAN36["cost"], f, adv)
        r = sim["net"].loc[wf:wl]
        m = _metrics(r); m["L"] = L
        m["hari_likuidasi"] = int(sim["liq"].loc[wf:wl].sum())
        m["hari_likuidasi_stres"] = int(sim["liq_stress"].loc[wf:wl].sum())
        m["eq_stres_min"] = round(float(sim["eq_stress"].loc[wf:wl].min()), 3)
        m["p_M_le_0"] = _boot(r); pvals[arm] = m["p_M_le_0"]
        res[arm] = m
    out["hasil"] = res
    n = res[PLAN36["primary"]]["n"]; out["n_hari_window"] = n
    win_end = pd.Timestamp(wl); win_days = pd.date_range(wf, wl)
    kurang = len(win_days.difference(idx))
    if n < PLAN36["n_win"]:
        if idx[-1] >= win_end:                                  # jendela sudah lewat tapi hari tidak lengkap
            out["gerbang"] = {"G1_data_lengkap": False, "G2_target_deterministik": None, "G3_M_utama": None,
                              "G4_mdd": None, "G5_likuidasi_stres": None, "G6_bh_signifikan": None, "G7_pembanding_positif": None}
            out["vonis"] = "DATA_INVALID"; out["alasan"] = f"hari jendela tidak lengkap: {kurang} hilang"
            return out
        out["vonis"] = f"BERJALAN ({n}/{PLAN36['n_win']} hari)"; return out
    # G2 determinisme: target dihitung ulang dari harga tercatat
    csvp = {k: os.path.join(fdir, f"{k}.csv") for k in SYMS}
    src = {k: eng.load_csv(csvp[k]) for k in SYMS} if all(os.path.exists(v) for v in csvp.values()) else {k: px[k] for k in SYMS}
    thf = {a: eng.target_history(src, mode=a, validate=False) for a in PLAN36["cells"]}
    bad = sum(1 for a in recs for arm in PLAN36["cells"] for k in SYMS
              if abs(thf[arm].loc[pd.Timestamp(a), k] - recs[a]["targets"][arm][k]) > 1e-12)
    pr, co = res[PLAN36["primary"]], res[PLAN36["comparator"]]
    g = {"G1_data_lengkap": bool(not out["gap_tanggal"] and out["backfill_n"] <= PLAN36["g1_max_backfill"] and len(errs) <= PLAN36["g1_max_dataerr"] and out["funding_hilang_di_jendela"] == 0),
         "G2_target_deterministik": bool(bad == 0), "G3_M_utama": bool(pr["M_per5h_pct"] >= PLAN36["target_M"]),
         "G4_mdd": bool(pr["mdd_pct"] >= PLAN36["mdd_cap"]), "G5_likuidasi_stres": bool(pr["hari_likuidasi_stres"] == 0),
         "G6_bh_signifikan": bool(pvals[PLAN36["primary"]] <= PLAN36["p_bh"]), "G7_pembanding_positif": bool(co["M_per5h_pct"] > 0)}
    out["g2_selisih"] = bad; out["gerbang"] = g
    if not (g["G1_data_lengkap"] and g["G2_target_deterministik"]):
        v = "DATA_INVALID"
    elif not (g["G3_M_utama"] and g["G4_mdd"] and g["G5_likuidasi_stres"]):
        v = "NO-GO"
    elif not g["G7_pembanding_positif"]:
        v = "TIDAK_KONSISTEN"
    elif not g["G6_bh_signifikan"]:
        v = "LANJUT_EKSEKUTOR_DRY_RUN"
    else:
        v = "LANJUT_EKSEKUTOR_DRY_RUN_TERBUKTI"
    out["vonis"] = v
    out["catatan"] = "Live tidak diizinkan oleh PRAREG-36; butuh 3 kunci live + GO eksplisit pengguna."
    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("perintah: record | refund | eval | status  <direktori>")
    cmd, fdir = sys.argv[1], resolve_fdir(sys.argv[2])
    if cmd == "record":
        print(json.dumps(record(fdir), indent=2, default=str))
    elif cmd == "eval":
        print(json.dumps(evaluate(fdir), indent=2, default=str))
    elif cmd == "refund":
        print(json.dumps(refund(fdir), indent=2, default=str))
    elif cmd == "status":
        r = _read(os.path.join(fdir, "ledger.jsonl")); recs = [x for x in r if x.get("kind") == "rec"]
        print(json.dumps({"n_rec": len(recs), "pertama": recs[0]["asof"] if recs else None, "terakhir": recs[-1]["asof"] if recs else None,
                          "sel": PLAN36["cells"], "target": PLAN36["n_win"]}, indent=2))
    else:
        raise SystemExit("perintah: record | refund | eval | status")
