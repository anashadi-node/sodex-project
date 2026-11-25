#!/usr/bin/env python3
"""Audit edge lintas-lane paper SoDEX. READ-ONLY: hanya membaca data/paper_*state.json.

Pertanyaan tunggal: lane mana yang punya mean pnl_pct/trade > 0 dengan bukti statistik, bukan sekadar mean positif?
Aturan (HUKUM_BUKTI): dedup trade; epoch dihormati; CI95 bootstrap; p one-sided H0: mean<=0; koreksi BH lintas lane
n>=MIN_N; "KANDIDAT" hanya bila n>=MIN_N & CI95 bawah>0 & q<0.05. Selain itu BUKAN kandidat (n kecil = belum tahu).
Sizing/leverage menskala mean DAN risiko, tidak membuat edge -> lane mean<=0 tidak bisa 'diselamatkan' dengan sizing.
"""
from __future__ import annotations
import argparse, datetime as dt, glob, json, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIN_N, N_BOOT, SEED, TARGET = 20, 5000, 20261125, 0.008
FIELDS = ("pnl_pct", "net_pct", "gross_pct")   # urutan: net-of-fee dulu; gross_pct = TANPA fee (menggelembungkan)
# Batas epoch E6 (docs/sodex/PAPER_EPOCH_E6_20261115.md): hanya trade dengan exit_time >= batas.
EPOCH = {"paper_test_twoway_ab9a": "2026-11-15T00:55:52+00:00", "paper_test_twoway_ab9b": "2026-11-15T00:55:52+00:00",
         "paper_test_twoway_ab9c": "2026-11-15T00:55:52+00:00", "paper_test_twoway_ab9d": "2026-11-15T00:55:52+00:00",
         "paper_test_twoway_ab9e": "2026-11-15T01:06:50+00:00"}


def _ts(r, keys):
    for k in keys:
        v = r.get(k)
        if v in (None, ""):
            continue
        try:
            if isinstance(v, (int, float)) or str(v).replace(".", "", 1).isdigit():
                return dt.datetime.fromtimestamp(float(v), tz=dt.timezone.utc)
            t = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
        except (ValueError, OverflowError, OSError):
            continue
    return None


def load_trades(path):
    """-> (list[(key, exit_dt, pnl)], status). Skema tak dikenal => status eksplisit, bukan 0 diam-diam."""
    try:
        s = json.load(open(path))
    except (OSError, json.JSONDecodeError):
        return [], "TAK_TERBACA", set()
    ct = next((s[k] for k in ("closed_trades", "closed", "trades") if isinstance(s, dict) and isinstance(s.get(k), list)), None)
    if ct is None:
        return [], "TANPA_DAFTAR_TRADE", set()
    out, seen, basis = [], set(), set()
    for r in ct:
        fld = next((k for k in FIELDS if isinstance(r.get(k), (int, float)) and np.isfinite(r[k])), None) if isinstance(r, dict) else None
        if fld is None:
            continue
        basis.add(fld)
        ex = _ts(r, ("exit_time", "exit_iso", "exit_utc", "exit_ts"))
        en = _ts(r, ("entry_time", "entry_iso", "entry_utc", "entry_ts"))
        key = (r.get("pair") or r.get("symbol"), str(en), str(ex), r.get("side") or r.get("direction"))
        if key in seen or ex is None:
            continue                                  # DEDUP; tanpa exit_time tak bisa difilter epoch
        seen.add(key); out.append((key, ex, float(r[fld])))
    return out, ("OK" if out else "NOL_TRADE"), basis


def boot(x, rng):
    m = rng.choice(x, size=(N_BOOT, len(x)), replace=True).mean(axis=1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5)), float((m <= 0).mean())


def bh(p):
    p = np.asarray(p, float); n = len(p); o = np.argsort(p); q = np.empty(n)
    q[o] = np.minimum.accumulate((p[o] * n / np.arange(1, n + 1))[::-1])[::-1]
    return np.clip(q, 0, 1)


def audit(files, since=None):
    rng = np.random.default_rng(SEED); rows = []
    for f in files:
        name = os.path.basename(f).replace("_state.json", "")
        tr, st, basis = load_trades(f)
        cut = _ts({"x": EPOCH.get(name)}, ("x",)) if name in EPOCH else None
        if since:
            cut = max(cut, since) if cut else since
        x = np.array([p for _, ex, p in tr if cut is None or ex >= cut])
        r = {"lane": name, "status": st, "n": int(len(x)), "epoch_dari": cut.isoformat() if cut else "semua", "basis": "/".join(sorted(basis)) or "-"}
        if len(x):
            r.update(mean_pct=float(x.mean() * 100), hit=float((x > 0).mean()), p_ge_target=float((x >= TARGET).mean()))
            if len(x) >= 2:
                lo, hi, p = boot(x, rng); r.update(ci_lo=lo * 100, ci_hi=hi * 100, p=p)
        rows.append(r)
    fam = [r for r in rows if r["n"] >= MIN_N and "p" in r]
    for r, q in zip(fam, bh([r["p"] for r in fam]) if fam else []):
        r["q"] = float(q)
    for r in rows:
        ok = r["n"] >= MIN_N and r.get("ci_lo", -1) > 0 and r.get("q", 1) < 0.05
        if ok and r["basis"] == "gross_pct":
            r["verdict"] = "GROSS_SAJA_PERLU_NET"; continue      # tanpa fee/spread tak boleh jadi kandidat
        r["verdict"] = "KANDIDAT" if ok else ("TIDAK_ADA_EDGE" if r["n"] >= MIN_N else "DATA_KURANG")
    return sorted(rows, key=lambda r: (-(r["n"] >= MIN_N), -r.get("mean_pct", -1e9)))


def render(rows, now):
    L = [f"# Audit edge lintas-lane — {now:%Y-%m-%d %H:%M} UTC", "",
         f"Metode: dedup, epoch E6 untuk ab9*, bootstrap {N_BOOT}x seed {SEED}, H0 mean<=0 (one-sided), BH lintas lane n>={MIN_N}.", "",
         "| lane | basis | n | mean %/trade | CI95 (%) | hit | ≥0,8% | q(BH) | verdict |", "|---|---|---:|---:|---|---:|---:|---:|---|"]
    for r in rows:
        ci = f"[{r['ci_lo']:+.2f}, {r['ci_hi']:+.2f}]" if "ci_lo" in r else "—"
        L.append(f"| {r['lane']} | {r['basis']} | {r['n']} | {r.get('mean_pct', float('nan')):+.3f} | {ci} | "
                 f"{r.get('hit', float('nan')):.0%} | {r.get('p_ge_target', float('nan')):.0%} | {r['q']:.3f} | {r['verdict']} |"
                 if "q" in r else
                 f"| {r['lane']} | {r['basis']} | {r['n']} | {r.get('mean_pct', float('nan')):+.3f} | {ci} | "
                 f"{r.get('hit', float('nan')):.0%} | {r.get('p_ge_target', float('nan')):.0%} | — | {r['verdict']} |")
    k = [r["lane"] for r in rows if r["verdict"] == "KANDIDAT"]
    L += ["", f"**Kandidat edge terbukti: {len(k)}** {k}", "",
          "Catatan: mean pnl_pct dihitung per posisi (notional), bukan % total wallet. n<20 = belum tahu, bukan 'gagal'."]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--since", default=None, help="ISO UTC; hanya exit_time >= ini")
    ap.add_argument("--glob", default=os.path.join(ROOT, "data", "paper_test*_state.json"))
    a = ap.parse_args(argv)
    since = _ts({"x": a.since}, ("x",)) if a.since else None
    rows = audit(sorted(glob.glob(a.glob)), since)
    print(render(rows, dt.datetime.now(dt.timezone.utc)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
