#!/usr/bin/env python3
"""
VALIDASI H6b — Momentum harian: funding, walk-forward, per-simbol, regime.
Tujuan: menguji apakah edge momentum 1d bertahan setelah biaya nyata (fee + funding)
dan stabil lintas waktu/simbol/regime.

Protokol:
  sinyal = sign(return hari sebelumnya)  [long jika naik, short jika turun]
  PnL_gross = sinyal x return hari berikutnya
  biaya_funding = sinyal x Σ funding rate hari itu   (bayar jika positif)
  biaya_fee = turnover x fee_per_side (asumsikan 1 round-trip/hari)
  PnL_net = gross - funding - fee
Split: separuh awal vs separuh akhir (walk-forward sederhana) + per simbol.
Output: JSON + tabel. Read-only.
"""
import json, math, os, glob
import pandas as pd
import numpy as np

ROOT = '/home/USER/anantara-sakti'
DATA = f'{ROOT}/freqtrade_user_data/data/binance/futures'
OUT = f'{ROOT}/docs/research/masterplan/riset_metode_sodex_cex_20260914/H6B_VALIDASI.json'
FEE_RT_BPS = 9.0     # taker round-trip
MIN_DAYS = 200


def load_tf(sym, tf):
    f = f'{DATA}/{sym}_USDT_USDT-{tf}-futures.feather'
    if not os.path.exists(f):
        return None
    d = pd.read_feather(f)
    c = [x for x in d.columns if 'date' in x.lower() or 'time' in x.lower()][0]
    d = d.rename(columns={c: 'ts'})
    d['ts'] = pd.to_datetime(d['ts'], utc=True, errors='coerce')
    return d.dropna(subset=['ts']).sort_values('ts').reset_index(drop=True)


def load_funding(sym):
    f = f'{DATA}/{sym}_USDT_USDT-1h-funding_rate.feather'
    if not os.path.exists(f):
        return None
    d = pd.read_feather(f)
    d = d.rename(columns={d.columns[0]: 'ts'})
    d['ts'] = pd.to_datetime(d['ts'], utc=True, errors='coerce')
    d = d.dropna(subset=['ts'])
    d['fund'] = pd.to_numeric(d['open'], errors='coerce').fillna(0.0)  # rate per 8h
    return d[['ts', 'fund']].sort_values('ts')


def daily(sym):
    d = load_tf(sym, '1h')
    if d is None or len(d) < 500:
        return None
    d = d.set_index('ts')['close'].astype(float)
    day = d.resample('1D').last().dropna()
    if len(day) < MIN_DAYS:
        return None
    r = np.log(day).diff().dropna()
    # funding harian
    fu = load_funding(sym)
    fd = None
    if fu is not None:
        fu = fu.set_index('ts')['fund']
        fd = fu.resample('1D').sum().reindex(r.index).fillna(0.0)
    return r, fd


def run():
    rows = []
    for f in sorted(glob.glob(f'{DATA}/*_USDT_USDT-1h-futures.feather')):
        sym = os.path.basename(f).split('_')[0]
        out = daily(sym)
        if out is None:
            continue
        r, fd = out
        rr = r.values
        sig = np.sign(rr[:-1])
        gross = sig * rr[1:] * 1e4
        fund = (sig * fd.values[1:] * 1e4) if fd is not None else np.zeros(len(gross))
        net = gross - fund - FEE_RT_BPS
        n = len(net)
        if n < MIN_DAYS:
            continue
        h = n // 2
        rows.append(dict(
            sym=sym, n=n,
            gross=float(np.mean(gross)), funding=float(np.mean(fund)),
            net=float(np.mean(net)),
            t_net=float(np.mean(net) / (np.std(net, ddof=1) / math.sqrt(n))) if n > 2 else float('nan'),
            hit=float(np.mean(net > 0)),
            net_h1=float(np.mean(net[:h])), net_h2=float(np.mean(net[h:])),
            funding_mean=float(np.mean(fd.values)) if fd is not None else float('nan'),
        ))

    if not rows:
        print('tidak ada data'); return
    df = pd.DataFrame(rows)
    agg = dict(
        n_symbols=int(len(df)), n_days_total=int(df['n'].sum()),
        gross_bps=float(df['gross'].mean()), funding_bps=float(df['funding'].mean()),
        net_bps=float(df['net'].mean()),
        net_bps_weighted=float((df['net'] * df['n']).sum() / df['n'].sum()),
        frac_symbols_net_positive=float((df['net'] > 0).mean()),
        frac_symbols_h1_and_h2_positive=float(((df['net_h1'] > 0) & (df['net_h2'] > 0)).mean()),
        median_symbol_net_bps=float(df['net'].median()),
        mean_funding_rate_8h=float(df['funding_mean'].mean()),
        fee_rt_bps=FEE_RT_BPS,
    )

    # pooled t-stat
    per_sym_t = df['t_net'].replace([np.inf, -np.inf], np.nan).dropna()
    agg['median_symbol_t'] = float(per_sym_t.median())
    agg['n_symbols_t_gt_2'] = int((per_sym_t > 2).sum())
    agg['n_symbols_t_lt_-2'] = int((per_sym_t < -2).sum())

    json.dump(dict(agg=agg, per_symbol=rows), open(OUT, 'w'), indent=1, default=str)

    print('=== AGREGAT ===')
    for k, v in agg.items():
        print(f'  {k}: {v}')
    print('\n=== PER SIMBOL (urut net) ===')
    for r in sorted(rows, key=lambda x: -x['net'])[:30]:
        print(f"  {r['sym']:<8} n={r['n']:>4} gross={r['gross']:>8.2f} fund={r['funding']:>7.2f} "
              f"net={r['net']:>8.2f} t={r['t_net']:>6.2f} hit={r['hit']*100:>5.1f}% "
              f"h1={r['net_h1']:>7.2f} h2={r['net_h2']:>7.2f}")
    print(f'\ntersimpan: {OUT}')


if __name__ == '__main__':
    run()
