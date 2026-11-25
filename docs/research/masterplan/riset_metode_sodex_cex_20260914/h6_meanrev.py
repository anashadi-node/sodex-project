#!/usr/bin/env python3
"""
RISET H6 — Mean reversion lintas horizon vs biaya nyata.
Hipotesis (dari P03: mean-reversion 15-menit Binance, 90% dari 183 pair):
  Reversal jangka pendek NYATA secara statistik, tetapi edge gross < biaya.
  Pertanyaan kita: apakah pada horizon 1h/4h/1d edge melebihi biaya?

Uji:
  1) Autokorelasi lag-1 return (per simbol, pooled)
  2) Strategi kontrarian: signal = −sign(r_prev) → hasil = signal × r_next (bps)
  3) Variance ratio (VR<1 = mean reverting)
  4) t-stat pooled + per-simbol sign count
  5) Pembanding biaya nyata Binance USDM: taker 4,5 bps/sisi, maker 2,0 bps/sisi
Output: JSON + tabel stdout. Read-only.
"""
import json, math, os, glob
import pandas as pd
import numpy as np

ROOT = '/home/USER/anantara-sakti'
DATA = f'{ROOT}/freqtrade_user_data/data/binance/futures'
OUT = f'{ROOT}/docs/research/masterplan/riset_metode_sodex_cex_20260914/H6_RESULT.json'

COST = {'taker_rt_bps': 9.0, 'maker_rt_bps': 4.0}


def load(sym, tf):
    f = f'{DATA}/{sym}_USDT_USDT-{tf}-futures.feather'
    if not os.path.exists(f):
        return None
    d = pd.read_feather(f)
    c = [x for x in d.columns if 'date' in x.lower() or 'time' in x.lower()][0]
    d = d.rename(columns={c: 'ts'})
    d['ts'] = pd.to_datetime(d['ts'], utc=True, errors='coerce')
    return d.dropna(subset=['ts']).sort_values('ts').reset_index(drop=True)


def test(tf, horizon_bars):
    """Kontrarian: masuk melawan arah bar sebelumnya, tahan horizon_bars."""
    per = []
    pooled_sig, pooled_ret = [], []
    for f in sorted(glob.glob(f'{DATA}/*_USDT_USDT-{tf}-futures.feather')):
        sym = os.path.basename(f).split('_')[0]
        d = load(sym, tf)
        if d is None or len(d) < 300:
            continue
        c = d['close'].astype(float).values
        # return bar ke-i (close-to-close)
        r = np.diff(np.log(c))
        n = len(r) - horizon_bars - 1
        if n < 200:
            continue
        # PERBAIKAN: sinyal dari bar i, forward MULAI bar i+1 (tanpa look-ahead)
        sig = -np.sign(r[:n])
        fwd = np.array([r[i + 1:i + 1 + horizon_bars].sum() for i in range(n)])
        pnl_bps = sig * fwd * 1e4
        # autokorelasi lag-1
        ac1 = float(np.corrcoef(r[:-1], r[1:])[0, 1]) if len(r) > 10 else float('nan')
        # variance ratio VR(q)
        var1 = np.var(r)
        varq = np.var(fwd) / horizon_bars if horizon_bars > 1 else var1
        vr = float(varq / var1) if var1 > 0 else float('nan')
        per.append(dict(sym=sym, n=int(n), mean_bps=float(np.mean(pnl_bps)),
                        median_bps=float(np.median(pnl_bps)),
                        hit=float(np.mean(pnl_bps > 0)), ac1=ac1, vr=vr))
        pooled_sig.append(sig); pooled_ret.append(fwd)

    if not per:
        return None
    S = np.concatenate(pooled_sig); R = np.concatenate(pooled_ret)
    pnl = S * R * 1e4
    n = len(pnl)
    mu = float(np.mean(pnl)); sd = float(np.std(pnl, ddof=1))
    se = sd / math.sqrt(n) if n else float('nan')
    t = mu / se if se and se > 0 else float('nan')
    per_sym_positive = sum(1 for p in per if p['mean_bps'] > 0)
    return dict(tf=tf, horizon_bars=horizon_bars, n_pooled=int(n), n_symbols=len(per),
                mean_bps=mu, median_bps=float(np.median(pnl)),
                sd_bps=sd, t_stat=t, hit=float(np.mean(pnl > 0)),
                per_symbol_positive=per_sym_positive,
                per_symbol_frac_positive=per_sym_positive / len(per),
                ac1_median=float(np.nanmedian([p['ac1'] for p in per])),
                vr_median=float(np.nanmedian([p['vr'] for p in per])),
                cost=COST,
                net_taker_bps=mu - COST['taker_rt_bps'],
                net_maker_bps=mu - COST['maker_rt_bps'],
                per_symbol=per)


def main():
    res = {}
    for tf, hb in [('1h', 1), ('4h', 1), ('1d', 1), ('1h', 4), ('1h', 24)]:
        key = f'{tf}_h{hb}'
        r = test(tf, hb)
        if r:
            r.pop('per_symbol')
            res[key] = r
    json.dump(res, open(OUT, 'w'), indent=1, default=str)

    print(f"{'skenario':<10}{'n':>9}{'mean_bps':>10}{'t':>8}{'hit%':>7}"
          f"{'ac1':>8}{'VR':>7}{'net_taker':>11}{'net_maker':>11}")
    for k, v in res.items():
        print(f"{k:<10}{v['n_pooled']:>9}{v['mean_bps']:>10.3f}{v['t_stat']:>8.2f}"
              f"{v['hit']*100:>7.1f}{v['ac1_median']:>8.4f}{v['vr_median']:>7.3f}"
              f"{v['net_taker_bps']:>11.3f}{v['net_maker_bps']:>11.3f}")
    print(f"\nbiaya diasumsikan: {COST}")
    print(f"simbol: {list(res.values())[0]['n_symbols'] if res else 0}")
    print(f"tersimpan: {OUT}")


if __name__ == '__main__':
    main()
