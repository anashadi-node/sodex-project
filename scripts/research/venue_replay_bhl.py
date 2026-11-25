#!/usr/bin/env python3
"""REPLAY 3 KELUARGA SINYAL × 3 VENUE — Binance vs Hyperliquid vs SoDEX.

Pertanyaan (user 25-Okt): apakah target SoDEX (0,8%/window 30j) mungkin tercapai
bila diterapkan di market venue Binance dan Hyperliquid?

DESAIN (anti-bias):
- ALPHA dan BIAYA dipisah: sinyal direplay pada SATU price path (Binance 1h,
  180 hari — terpanjang), fill disimulasikan identik; biaya round-trip per venue
  dihitung dari model masing-masing. Gross = fungsi sinyal; net = gross - biaya.
- PARAMETER PRODUKSI, tanpa tuning: realwide/twoway TP6/SL3/TIME24 (rev A2
  27-Sep), donchian TP4/SL2/TIME30. Entry di OPEN bar berikutnya (no look-ahead).
- Geometri exit konservatif: SL dicek dulu dalam bar; jika TP & SL sama-sama di
  dalam 1 bar, SL yang diambil (worst-case fill).
- Satu posisi terbuka per simbol (cooldown sampai exit).
- Kontrol negatif: entri acak (p=0,03/bar, seed beku) HARUS rugi sebesar biaya.
- Triangulasi path: replay ulang 90 hari terakhir pada price path SoDEX real
  (era >= 12-Jun real, bukan mirror) — gross Binance-path vs SoDEX-path dibanding.

KELUARGA (definisi sinyal dari kode produksi):
  1. momentum   : v3 regime MOMENTUM (ADX>25, c>s50>s200) + 4/5 checklist
  2. donchian   : Donchian-20 breakout + volok + BULL (ADX>22, golden cross)
  3. twoway     : momentum LONG + mirror SHORT (BEAR: c<s50<s200, ADX>22)

KELUARAN: reports/sodex/VENUE_REPLAY_BHL.json + tabel stdout.
"""
from __future__ import annotations

import json
import math
import os
import random
import statistics as st
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np

import backtest_swing_gate1_v3 as v3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DON = 20
SEED = 20261025

# ── Biaya per venue (bps, round-trip = fee 2 sisi + spread 2 sisi + funding) ──
# SoDEX: cost_model.py (taker 4,0/sisi; spread per pair; funding 0,13/8h)
# Binance USDM: taker 0,04%/sisi (VIP0 publik); spread proxy sama dgn SoDEX dict;
#               funding 8h (model sama, orde magnitudo sama).
# Hyperliquid: taker 0,045%/sisi (fee publik); spread proxy; funding 8h.
VENUE = {
    "sodex":   {"taker": 4.0, "spread_default": 3.8},
    "binance": {"taker": 4.0, "spread_default": 1.5},
    "hyperliquid": {"taker": 4.5, "spread_default": 1.5},
}
SPREAD_OVR = {"BTC": 1.3, "ETH": 2.0, "SOL": 3.5, "XRP": 2.0, "DOGE": 2.0,
              "BCH": 2.0, "LINK": 2.0, "AAVE": 2.0, "ADA": 4.97, "UNI": 2.27,
              "ENA": 6.14, "ARB": 2.0, "AVAX": 2.0, "ASTER": 4.0, "PUMP": 4.0,
              "LIT": 8.0, "BNB": 2.0, "HYPE": 8.0, "SUI": 8.0}
FUNDING_8H_BPS = 0.13


def cost_bps(sym: str, hold_h: float, venue: str) -> float:
    v = VENUE[venue]
    spr = SPREAD_OVR.get(sym.upper(), v["spread_default"])
    fund = FUNDING_8H_BPS * (hold_h / 8.0)
    return 2 * v["taker"] + 2 * spr + fund


def load_klines(path: str):
    d = json.load(open(path))
    bars = d if isinstance(d, list) else d.get("bars") or []
    rows = []
    for b in bars:
        if isinstance(b, dict):
            t = b.get("t") or b.get("time")
            o, h, l, c = (b.get("o"), b.get("h"), b.get("l"), b.get("c"))
            v = b.get("v", 0)
        else:
            t, o, h, l, c, v = b[:6]
        if isinstance(t, str):
            t = datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
        else:
            t = float(t)
            if t > 1e11:
                t /= 1000.0
        rows.append((t, float(o), float(h), float(l), float(c), float(v)))
    rows.sort()
    return rows


def arrays(rows):
    a = {k: np.array([r[i] for r in rows]) for i, k in enumerate(("t", "o", "h", "l", "c", "v"))}
    return a


def sma(x, n):
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        c = np.convolve(x, np.ones(n) / n, mode="valid")
        out[n - 1:] = c
    return out


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    ru = sma(up, n)
    rd = sma(dn, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100 - 100 / (1 + ru / rd)
    return out


def adx(h, l, c, n=14):
    up = np.diff(h, prepend=h[0])
    dn = -np.diff(l, prepend=l[0])
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum(np.maximum(h[1:] - l[1:], np.abs(h[1:] - c[:-1])), np.abs(l[1:] - c[:-1]))
    tr = np.concatenate([[tr[0]], tr])
    atr = sma(tr, n)
    pdi = 100 * sma(plus_dm, n) / atr
    mdi = 100 * sma(minus_dm, n) / atr
    with np.errstate(divide="ignore", invalid="ignore"):
        dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
    return sma(dx, n)


def rr(c, n):
    out = np.full(len(c), np.nan)
    out[n:] = c[n:] / c[:-n] - 1
    return out


def simulate_family(sym: str, d: dict, family: str, random_ctrl: bool = False,
                    tp_override: float | None = None, sl_override: float | None = None):
    """Balikin list trade: entry/exit ts, gross bps (path Binance)."""
    c, h, l, o, v, t = d["c"], d["h"], d["l"], d["o"], d["v"], d["t"]
    n = len(c)
    trades = []
    busy_until = 0.0
    s50, s200 = sma(c, 50), sma(c, 200)
    a = adx(h, l, c)
    rv = rsi(c)
    va = sma(v, 24)
    r24, r4, r1 = rr(c, 24), rr(c, 4), rr(c, 1)
    rng = random.Random(hash(sym) & SEED)
    min_warm = 210
    tp_pct, sl_pct, time_h = (0.06, 0.03, 24) if family != "donchian" else (0.04, 0.02, 30)
    if tp_override is not None:
        tp_pct, sl_pct = tp_override, sl_override
    for i in range(min_warm, n - 1):
        ts_open = t[i + 1]  # entry pada open bar berikutnya
        if ts_open < busy_until:
            continue
        if random_ctrl:
            if rng.random() >= 0.03:
                continue
            direction = "LONG" if rng.random() < 0.5 else "SHORT"
        else:
            direction = None
            if family == "momentum":
                if not (a[i] > v3.MOM_ADX_MIN and c[i] > s50[i] and s50[i] > s200[i]):
                    continue
                chk = 0
                if c[i] > sma(c, 24)[i]: chk += 1
                if 40 < rv[i] < 60: chk += 1
                if va[i] > 0 and v[i] / va[i] > 1.1: chk += 1
                if not np.isnan(r24[i]) and r24[i] > v3.MOM_TREND_STRENGTH: chk += 1
                if not np.isnan(r1[i]) and r1[i] < 0.003: chk += 1
                if chk >= 4:
                    direction = "LONG"
            elif family == "donchian":
                if i < DON + 1:
                    continue
                va_ = va[i] if not np.isnan(va[i]) else v[i]
                breakout = c[i] > h[i - DON:i].max()
                volok = v[i] > va_
                bull = a[i] > 22 and c[i] > s50[i] and s50[i] > s200[i]
                if breakout and volok and bull:
                    direction = "LONG"
            elif family == "twoway":
                # LONG leg = momentum; SHORT leg = mirror BEAR (death cross)
                if a[i] > v3.MOM_ADX_MIN and c[i] > s50[i] and s50[i] > s200[i]:
                    chk = 0
                    if c[i] > sma(c, 24)[i]: chk += 1
                    if 40 < rv[i] < 60: chk += 1
                    if va[i] > 0 and v[i] / va[i] > 1.1: chk += 1
                    if not np.isnan(r24[i]) and r24[i] > v3.MOM_TREND_STRENGTH: chk += 1
                    if not np.isnan(r1[i]) and r1[i] < 0.003: chk += 1
                    if chk >= 4:
                        direction = "LONG"
                elif a[i] > v3.MOM_ADX_MIN and c[i] < s50[i] and s50[i] < s200[i]:
                    chk = 0
                    if c[i] < sma(c, 24)[i]: chk += 1
                    if 40 < rv[i] < 60: chk += 1
                    if va[i] > 0 and v[i] / va[i] > 1.1: chk += 1
                    if not np.isnan(r24[i]) and r24[i] < -v3.MOM_TREND_STRENGTH: chk += 1
                    if not np.isnan(r1[i]) and r1[i] > -0.003: chk += 1
                    if chk >= 4:
                        direction = "SHORT"
            if direction is None:
                continue
        # entry di open bar i+1; walk ke depan
        ep = o[i + 1]
        if ep <= 0:
            continue
        sgn = 1.0 if direction == "LONG" else -1.0
        tp_p = ep * (1 + sgn * tp_pct)
        sl_p = ep * (1 - sgn * sl_pct)
        exit_px, exit_ts, reason = None, None, None
        j_end = min(i + 1 + int(math.ceil(time_h)), n)
        for j in range(i + 1, j_end):
            if j >= n:
                break
            if sgn > 0:
                if l[j] <= sl_p:
                    exit_px, exit_ts, reason = sl_p, t[j], "SL"; break
                if h[j] >= tp_p:
                    exit_px, exit_ts, reason = tp_p, t[j], "TP"; break
            else:
                if h[j] >= sl_p:
                    exit_px, exit_ts, reason = sl_p, t[j], "SL"; break
                if l[j] <= tp_p:
                    exit_px, exit_ts, reason = tp_p, t[j], "TP"; break
        if exit_px is None:
            k = min(j_end - 1, n - 1)
            exit_px, exit_ts, reason = c[k], t[k], "TIME"
        gross = sgn * (exit_px / ep - 1) * 1e4
        hold = (exit_ts - ts_open) / 3600.0
        trades.append({"sym": sym, "dir": direction, "entry_ts": ts_open, "exit_ts": exit_ts,
                       "gross": round(gross, 2), "hold_h": round(hold, 2), "reason": reason})
        busy_until = exit_ts
    return trades


def agg_stats_g(gs, name):
    """Aggregasi untuk daftar gross bps murni (tanpa dict trade)."""
    if not gs:
        return None
    wr = sum(1 for x in gs if x > 0) / len(gs) * 100
    pf = (sum(x for x in gs if x > 0) / max(1e-9, -sum(x for x in gs if x < 0)))
    m, sd = st.mean(gs), st.pstdev(gs)
    return {"label": name, "n": len(gs), "gross_mean": round(m, 2), "WR": round(wr, 1),
            "PF": round(pf, 2), "t": round(m / (sd / math.sqrt(len(gs))), 2) if sd > 0 else None}


def agg_stats(trs, name):
    if not trs:
        return None
    g = [t["gross"] for t in trs]
    wr = sum(1 for t in trs if t["gross"] > 0) / len(trs) * 100
    pf = (sum(t["gross"] for t in trs if t["gross"] > 0) /
          max(1e-9, -sum(t["gross"] for t in trs if t["gross"] < 0)))
    m = st.mean(g)
    sd = st.pstdev(g)
    tt = m / (sd / math.sqrt(len(g))) if sd > 0 else float("nan")
    return {"label": name, "n": len(trs), "gross_mean": round(m, 2), "gross_median": round(st.median(g), 2),
            "WR": round(wr, 1), "PF": round(pf, 2), "t": round(tt, 2),
            "hold_mean_h": round(st.mean([t["hold_h"] for t in trs]), 1)}


def main() -> None:
    out_all = {"families": {}, "random_control": {}, "venue_matrix": {}, "path_check": {}}
    bin_rows = {s: load_klines(f"{ROOT}/data/binance_klines/1h/{s}USDT.json")
                for s in ("BTC",)}
    syms = sorted(f[:-len("USDT.json")] for f in os.listdir(f"{ROOT}/data/binance_klines/1h")
                  if f.endswith("USDT.json"))
    # simbol dengan >= 2000 bar agar warmup cukup
    keep = []
    for s in syms:
        p = f"{ROOT}/data/binance_klines/1h/{s}USDT.json"
        rows = load_klines(p)
        if len(rows) >= 1500:
            keep.append((s, rows))
    print(f"simbol layak: {len(keep)}")

    fam_trades = {}
    for fam in ("momentum", "donchian", "twoway"):
        allt = []
        for s, rows in keep:
            allt.extend(simulate_family(s, arrays(rows), fam))
        allt.sort(key=lambda x: x["entry_ts"])
        fam_trades[fam] = allt
        stt = agg_stats(allt, fam)
        out_all["families"][fam] = stt
        print(fam, stt)

    # kontrol acak — DUA geometri: TP6/SL3 (geometri momentum) dan TP4/SL2
    # (geometri donchian) agar perbandingan donchian-vs-acak tidak terkontaminasi
    # perbedaan geometri (audit 25-Okt).
    def run_random(tp, sl):
        allt = []
        for s, rows in keep:
            allt.extend(simulate_family(s, arrays(rows), "none", random_ctrl=True,
                                        tp_override=tp, sl_override=sl))
        return agg_stats(allt, f"RANDOM tp{int(tp*100)}/sl{int(sl*100)}"), allt
    out_all["random_control"], _ = run_random(0.06, 0.03)
    out_all["random_control_donch_geo"], rnd_dg = run_random(0.04, 0.02)
    print("RANDOM tp6/3", out_all["random_control"])
    print("RANDOM tp4/2", out_all["random_control_donch_geo"])


    # era split: pra vs pasca flip 25-Sep (padanan era paper SoDEX)
    FLIP = datetime(2026, 9, 25, tzinfo=timezone.utc).timestamp()
    era = {}
    for fam, trs in fam_trades.items():
        era[fam] = {}
        for tag, filt in (("pra", lambda t: t["exit_ts"] < FLIP),
                          ("pasca", lambda t: t["exit_ts"] >= FLIP)):
            g = [t["gross"] for t in trs if filt(t)]
            era[fam][tag] = agg_stats_g(g, tag)
    out_all["era_split"] = era
    print("era_split:", json.dumps(era))

    # tabel aritmetika target 0,8%/window per venue/family
    W = 30 * 3600.0
    nwin = len(keep[0][1]) * 3600 / W if keep else 1
    span_h = (keep[0][1][-1][0] - keep[0][1][0][0]) / 3600 if keep else 1
    nwin = span_h / 30.0
    tbl = []
    for fam, trs in fam_trades.items():
        for ven in ("sodex", "binance", "hyperliquid"):
            # sizing: maks 5 posisi konkuren × 20% wallet = 100% wallet ekspos penuh
            rate = len(trs) / nwin
            eff_frac = min(1.0, 5 * 0.2)
            per_trade_pct_target = 0.8 / (rate * eff_frac)
            need_bps = per_trade_pct_target * 100
            costs = [cost_bps(t["sym"], t["hold_h"], ven) for t in trs]
            net_m = st.mean([t["gross"] - c for t, c in zip(trs, costs)])
            tbl.append({"family": fam, "venue": ven, "trade_per_window": round(rate, 1),
                        "need_net_bps_per_trade": round(need_bps, 1),
                        "actual_net_bps": round(net_m, 2),
                        "gap_bps": round(need_bps - net_m, 2)})
    out_all["target_arithmetic"] = tbl
    print("target_arithmetic:")
    for r in tbl:
        print(f"  {r['family']:10} {r['venue']:12} rate={r['trade_per_window']:>5}/win "
              f"butuh={r['need_net_bps_per_trade']:>6} bps/trade aktual={r['actual_net_bps']:>7} "
              f"gap={r['gap_bps']:>7}")

    # varian maker (passive) Binance/HL: biaya = fee maker 2 sisi + spread - 1/2 spread × 2
    maker_fee = {"binance": 0.2, "hyperliquid": 0.15}
    mk = {}
    for fam, trs in fam_trades.items():
        mk[fam] = {}
        for ven in ("binance", "hyperliquid"):
            nets = []
            for t in trs:
                spr = SPREAD_OVR.get(t["sym"].upper(), VENUE[ven]["spread_default"])
                fund = FUNDING_8H_BPS * (t["hold_h"] / 8.0)
                cb = 2 * maker_fee[ven] + fund  # maker: menyebar di dalam spread, spread tidak dibayar penuh
                nets.append(t["gross"] - cb)
            m, sd = st.mean(nets), st.pstdev(nets)
            mk[fam][ven] = {"net_mean": round(m, 2), "t": round(m / (sd / math.sqrt(len(nets))), 2),
                            "cost_mean": round(2 * maker_fee[ven] + FUNDING_8H_BPS * st.mean([t["hold_h"] for t in trs]) / 8, 2)}
    out_all["maker_variant"] = mk
    print("maker_variant:", json.dumps(mk))

    # matriks venue: net = gross - cost(venue, hold)
    for fam, trs in fam_trades.items():
        out_all["venue_matrix"][fam] = {}
        for ven in ("sodex", "binance", "hyperliquid"):
            for tag, tt in (("net", trs),):
                netted = []
                for t in tt:
                    cb = cost_bps(t["sym"], t["hold_h"], ven)
                    netted.append({**t, "net": round(t["gross"] - cb, 2), "cost": round(cb, 2)})
                nn = [t["net"] for t in netted]
                wr = sum(1 for x in nn if x > 0) / len(nn) * 100
                m, sd = st.mean(nn), st.pstdev(nn)
                tt_ = m / (sd / math.sqrt(len(nn))) if sd > 0 else float("nan")
                pf = (sum(x for x in nn if x > 0) / max(1e-9, -sum(x for x in nn if x < 0)))
                out_all["venue_matrix"][fam][ven] = {
                    "n": len(nn), "cost_mean_bps": round(st.mean([t["cost"] for t in netted]), 2),
                    "net_mean": round(m, 2), "net_median": round(st.median(nn), 2),
                    "WR": round(wr, 1), "PF": round(pf, 2), "t": round(tt_, 2)}
        print(fam, json.dumps(out_all["venue_matrix"][fam]))

    # cek path: replay 90 hari terakhir pada SoDEX real vs Binance (gross harus dekat)
    cut = datetime(2026, 7, 27, tzinfo=timezone.utc).timestamp()
    for fam in ("momentum", "donchian", "twoway"):
        try:
            sx = [s for s, _ in keep if os.path.exists(f"{ROOT}/data/sodex_klines/1h/{s}-USD.json")]
            g_bin = [t["gross"] for t in fam_trades[fam] if t["entry_ts"] >= cut]
            if not sx:
                continue
            allt = []
            for s in sx[:15]:
                rows = load_klines(f"{ROOT}/data/sodex_klines/1h/{s}-USD.json")
                if len(rows) < 1500:
                    continue
                allt.extend(simulate_family(s, arrays(rows), fam))
            g_sdx = [t["gross"] for t in allt if t["entry_ts"] >= cut]
            out_all["path_check"][fam] = {
                "bin_path_n": len(g_bin), "bin_mean": round(st.mean(g_bin), 2) if g_bin else None,
                "sdx_path_n": len(g_sdx), "sdx_mean": round(st.mean(g_sdx), 2) if g_sdx else None}
        except Exception as e:
            out_all["path_check"][fam] = {"err": repr(e)}
    print("path_check:", json.dumps(out_all["path_check"]))

    json.dump(out_all, open(f"{ROOT}/reports/sodex/VENUE_REPLAY_BHL.json", "w"), indent=1)


if __name__ == "__main__":
    main()
