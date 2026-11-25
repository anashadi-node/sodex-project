#!/usr/bin/env python3
"""SODEX proxy lab -- READ-ONLY. Dua tes, spesifikasi ditulis SEBELUM menjalankan (lihat docstring).

TES 1 (fidelity): seberapa dekat harga Binance 1h dengan tape SoDEX nyata? (BTC/ETH/SOL, 2026-06-01..08-31 saja; tidak menyentuh F1/lockbox)
  keluaran: korelasi return 1h, selisih abs median/p95 (bp), kecocokan bar 'gerak>=1,5%'.
TES 2 (daya prediksi proksi, SELURUH 14 simbol yang ada di SoDEX+Binance): momentum vs fade setelah gerak 1h >= theta.
  grid beku: theta {2,3,4,5}% x arah {momentum, fade} = 8 uji; BH-FDR q=0,10 atas 8 uji.
  sinyal di CLOSE bar t, masuk OPEN bar t+1 (tanpa look-ahead), tahan 24 bar, klaster 24 bar per simbol (ambil pertama).
  biaya bersih = 2*(5bp spread + 2bp fee) + 10bp stres = 24bp.
  split: DEV 2025-03-17..2025-12-31, OOS 2026-01-01..2026-08-31. Data >=2026-09-01 TIDAK dipakai.
  p = sign-flip level HARI (satu sisi), fungsi day_signflip_p milik F1.
Tidak ada jalur order/jaringan.
"""
import statistics as st
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sodex_prereg_f1 as f1  # noqa: E402  (day_signflip_p)

B = ROOT / "freqtrade_user_data/data/binance/futures"
SYMS = "AAVE ARB AVAX BNB BTC DOGE ETH HYPE LIT SOL SUI UNI XRP ZEC".split()
COST = 2 * (5 + 2) / 1e4 + 10 / 1e4
HOLD = 24
THETAS = (0.02, 0.03, 0.04, 0.05)
DEV_END = pd.Timestamp("2025-12-31 23:00", tz="UTC")
OOS_END = pd.Timestamp("2026-08-31 23:00", tz="UTC")


def bars(sym):
    d = pd.read_feather(B / f"{sym}_USDT_USDT-1h-futures.feather")
    d = d[(d["date"] <= OOS_END)].reset_index(drop=True)
    return d


def episodes(sym, theta, sign):
    """sign=+1 momentum, -1 fade -> list[(date_utc_day, split, net)]"""
    d = bars(sym)
    o, c, dt = d["open"].values, d["close"].values, d["date"]
    out, last = [], -10**9
    for t in range(1, len(d) - HOLD - 2):
        r = c[t] / c[t - 1] - 1.0
        if abs(r) < theta or t - last < HOLD:
            continue
        # kontinuitas: bar berurutan 1 jam (hindari lubang data)
        if (dt.iloc[t + 1] - dt.iloc[t]) != pd.Timedelta(hours=1) or (dt.iloc[t] - dt.iloc[t - 1]) != pd.Timedelta(hours=1):
            continue
        last = t
        dr = (1 if r > 0 else -1) * sign
        entry, exit_ = o[t + 1], o[t + 1 + HOLD]
        net = dr * (exit_ / entry - 1.0) - COST
        split = "DEV" if dt.iloc[t] <= DEV_END else "OOS"
        out.append((dt.iloc[t].strftime("%Y%m%d"), split, net, sym))
    return out


def bh(pvals, q=0.10):
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    thr = -1
    for rank, i in enumerate(order, 1):
        if pvals[i] <= q * rank / m:
            thr = rank
    ok = [False] * m
    for rank, i in enumerate(order, 1):
        if rank <= thr:
            ok[i] = True
    return ok


def tes2():
    print("\n== TES 2: daya prediksi proksi Binance 1h (14 simbol, biaya 24bp) ==")
    rows, ps = [], []
    for th in THETAS:
        for sign, name in ((1, "momentum"), (-1, "fade")):
            eps = [e for s in SYMS for e in episodes(s, th, sign)]
            for split in ("DEV", "OOS", "ALL"):
                sub = [e for e in eps if split == "ALL" or e[1] == split]
                if len(sub) < 5:
                    rows.append((th, name, split, len(sub), None, None, None)); continue
                r = [e[2] for e in sub]
                byday = {}
                for e in sub:
                    byday.setdefault(e[0], []).append(e[2])
                p = f1.day_signflip_p(byday, n=6000)
                rows.append((th, name, split, len(sub), st.mean(r) * 100, 100 * sum(1 for x in r if x > 0) / len(r), p))
    # BH hanya atas 8 uji (ALL)
    allr = [r for r in rows if r[2] == "ALL" and r[6] is not None]
    flags = bh([r[6] for r in allr])
    sig = {(r[0], r[1]) for r, f in zip(allr, flags) if f}
    print(f"{'theta':>5} {'arah':>9} {'split':>4} {'n':>5} {'mean%':>8} {'WR%':>6} {'p_hari':>7}  BH(q=.10,8 uji)")
    for r in rows:
        if r[4] is None:
            print(f"{r[0]*100:4.0f}% {r[1]:>9} {r[2]:>5} {r[3]:>5}   (n<5)"); continue
        tag = "LOLOS" if (r[2] == "ALL" and (r[0], r[1]) in sig) else ""
        print(f"{r[0]*100:4.0f}% {r[1]:>9} {r[2]:>5} {r[3]:>5} {r[4]:+8.3f} {r[5]:6.1f} {r[6]:7.3f}  {tag}")


def tes1():
    print("== TES 1: fidelity Binance 1h vs tape SoDEX (2026-06-01..08-31) ==")
    import json
    T = ROOT / "freqtrade_user_data/data/sodex/trades"
    for sym in ("BTC", "ETH", "SOL"):
        px = {}
        for f in sorted(T.glob("trades_2026*.jsonl")):
            day = f.name[7:15]
            if not ("20260601" <= day <= "20260831"):
                continue
            with open(f) as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("sym") != f"{sym}-USD":
                        continue
                    ts = float(r["ts"]) / 1000.0
                    h = int(ts // 3600)
                    if h not in px or ts >= px[h][0]:
                        px[h] = (ts, float(r["price"]))
        d = bars(sym)
        d = d[(d["date"] >= "2026-06-01") & (d["date"] <= "2026-08-31 23:00")]
        bn = {int(x.timestamp() // 3600): c for x, c in zip(d["date"], d["close"])}
        # close bar jam h = harga akhir jam h => tape: trade terakhir dalam jam h
        hs = sorted(set(px) & set(bn))
        rs, rb, absd = [], [], []
        for a, b in zip(hs, hs[1:]):
            if b - a != 1:
                continue
            rs.append(px[b][1] / px[a][1] - 1); rb.append(bn[b] / bn[a] - 1)
        lv = [abs(px[h][1] / bn[h] - 1) * 1e4 for h in hs]
        mx = pd.Series(rs).corr(pd.Series(rb))
        big_s = {i for i, x in enumerate(rs) if abs(x) >= 0.015}
        big_b = {i for i, x in enumerate(rb) if abs(x) >= 0.015}
        jac = len(big_s & big_b) / max(len(big_s | big_b), 1)
        lv.sort()
        print(f"{sym}: jam-cocok={len(hs)} corr_ret1h={mx:.4f} |level-diff| median={lv[len(lv)//2]:.1f}bp p95={lv[int(.95*len(lv))]:.1f}bp  bar>=1,5%: sodex={len(big_s)} binance={len(big_b)} jaccard={jac:.2f}")


if __name__ == "__main__":
    tes1()
    tes2()
