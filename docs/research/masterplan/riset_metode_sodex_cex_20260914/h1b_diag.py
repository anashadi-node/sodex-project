#!/usr/bin/env python3
"""
DIAGNOSTIK H1b v3 — mengapa E[R] simulasi sangat besar?
Hipotesis yang diuji:
  T1 BETA: sampel didominasi LONG (775 vs 37) dan pasar NAIK pada periode itu
           -> E[R] positif = beta, bukan alpha  (G6 wajib)
  T2 INFLASI R: R dinormalisasi oleh stop yang berbeda-beda; trade ber-stop TIPIS
           menghasilkan R raksasa -> mean R tidak sebanding antar trade
  T3 B0 kosong karena periode sampel hanya ~56 hari (< syarat 60 hari)
"""
import json, math, os
from datetime import datetime
import pandas as pd
import numpy as np

ROOT = '/home/USER/anantara-sakti'
DATA = f'{ROOT}/freqtrade_user_data/data/binance/futures'
RES = f'{ROOT}/docs/research/masterplan/riset_metode_sodex_cex_20260914/H1B_V3.json'


def candles(sym):
    f = f'{DATA}/{sym}_USDT_USDT-1h-futures.feather'
    if not os.path.exists(f):
        return None
    x = pd.read_feather(f)
    c = [k for k in x.columns if 'date' in k.lower() or 'time' in k.lower()][0]
    x = x.rename(columns={c: 'ts'})
    x['ts'] = pd.to_datetime(x['ts'], utc=True, errors='coerce')
    return x.dropna(subset=['ts']).sort_values('ts').reset_index(drop=True)


r = json.load(open(RES))
print('=== 1) actual_R vs simulasi (horizon 24h) ===')
h = r['horizons']['H24']
print(f"  n={h['n']} | actual_R mean={h['actual_R_mean']:.3f} median={h['actual_R_median']:.3f}")
for p in ['hold_to_end', 'RANDOM_control', 'trail_0.5R', 'tp_1R']:
    e = h['policies'].get(p, {})
    if 'meanR' in e:
        print(f"  {p:<16} meanR={e['meanR']:>7.3f} medianR={e['medianR']:>7.3f} WR={e['wr']*100:.1f}%")

print('\n=== 2) T1 BETA: arah pasar selama periode sampel ===')
for s in ['BTC', 'ETH', 'SOL']:
    d = candles(s)
    if d is None:
        continue
    for lo, hi in [('2026-08-06', '2026-10-01'), ('2026-09-01', '2026-10-01')]:
        w = d[(d['ts'] >= lo) & (d['ts'] <= hi)]
        if len(w) < 10:
            continue
        ret = float(w['close'].iloc[-1] / w['close'].iloc[0] - 1)
        print(f"  {s} {lo}..{hi}: return={ret*100:>7.2f}%  (n={len(w)} jam)")

print('\n=== 3) T2 INFLASI R: sebaran risk (stop) per trade ===')
import json as J
tr = []
for rel, key, tag in [('data/paper_test_realwide_state.json', 'closed', 'realwide'),
                      ('data/paper_test_twoway_state.json', 'closed_trades', 'twoway'),
                      ('data/paper_test_swing_state.json', 'closed_trades', 'swing')]:
    p = f'{ROOT}/{rel}'
    if not os.path.exists(p):
        continue
    for t in J.load(open(p)).get(key, []):
        try:
            if tag == 'realwide':
                sl = float(t['sl']); side = 'L' if t['side'] == 'L' else 'S'
                pnl = float(t.get('pnl_pct') or 0.0)
            else:
                ep = float(t['entry_price'])
                sl = abs(ep - float(t['sl_price'])) / ep
                side = 'L' if t['direction'] == 'LONG' else 'S'
                pnl = float(t.get('pnl_pct') or 0.0)
            tr.append(dict(tag=tag, sl=sl, side=side, pnl=pnl, R=pnl / sl if sl > 0 else None))
        except Exception:
            continue
df = pd.DataFrame([x for x in tr if x['R'] is not None])
print(f"  n={len(df)}")
print(f"  risk (stop, % notional): min={df.sl.min()*100:.3f}% p25={df.sl.quantile(.25)*100:.3f}% "
      f"median={df.sl.median()*100:.3f}% p75={df.sl.quantile(.75)*100:.3f}% max={df.sl.max()*100:.2f}%")
print(f"  actual R: mean={df.R.mean():.3f} median={df.R.median():.3f}")
print(f"  R mean per kelompok stop:")
df['bucket'] = pd.cut(df.sl, [0, 0.005, 0.01, 0.02, 0.05, 1])
for b, g in df.groupby('bucket', observed=True):
    print(f"    stop {str(b):<18} n={len(g):>4} R mean={g.R.mean():>7.3f} median={g.R.median():>7.3f} "
          f"| pnl% mean={g.pnl.mean()*100:>6.3f}%")

print('\n=== 4) T3 B0: ketersediaan data per simbol (butuh >= 60 hari di periode sampel) ===')
cnt = 0
for s in sorted({x['tag'] for x in tr}):
    pass
syms = sorted({t.split('_')[0] for t in os.listdir(DATA) if t.endswith('-1d-futures.feather')})
ok = 0
for s in syms:
    d = candles(s)
    if d is None:
        continue
    w = d[(d['ts'] >= '2026-08-06') & (d['ts'] <= '2026-10-01')]
    days = len(w) / 24
    if days >= 55:
        ok += 1
print(f"  simbol dengan data di periode sampel: {sum(1 for s in syms if candles(s) is not None)}")
print(f"  simbol dengan >= 55 hari di periode sampel: {ok}")
print("  -> B0 pada periode sampel TIDAK LAYAK (hanya ~56 hari). Hitung B0 pada periode data penuh.")

print('\n=== 5) B0 pada periode data PENUH (benchmark referensi) ===')
FEE = 8e-4
daily = []
for s in syms:
    d = candles(s)
    if d is None or len(d) < 400:
        continue
    cl = d.set_index('ts')['close'].astype(float).resample('1D').last().dropna()
    if len(cl) < 120:
        continue
    sig = pd.concat([(cl > cl.rolling(L).max().shift(1)).astype(float)
                     for L in (5, 10, 15, 20, 25, 30, 40, 50, 60)], axis=1).mean(axis=1)
    pos = (sig > 0.5).astype(float)
    ret = cl.pct_change().fillna(0.0)
    st = pos.shift(1).fillna(0.0) * ret - (pos - pos.shift(1).fillna(0.0)).abs() * FEE
    daily.append(st.rename(s))
port = pd.concat(daily, axis=1).mean(axis=1)
eq = (1 + port).cumprod()
yrs = len(port) / 365.0
print(f"  n_simbol={len(daily)} hari={len(port)} periode={port.index[0].date()}..{port.index[-1].date()}")
print(f"  B0 equal-weight: total={eq.iloc[-1]-1:+.2%} CAGR={(eq.iloc[-1]**(1/yrs)-1):+.2%} "
      f"Sharpe={port.mean()/port.std()*math.sqrt(365):.2f} MaxDD={(eq/eq.cummax()-1).min():.1%}")
# benchmark beli-tahan BTC
btc = candles('BTC')
if btc is not None:
    b = btc.set_index('ts')['close'].astype(float).resample('1D').last().dropna()
    print(f"  BTC buy&hold sama periode: {(b.iloc[-1]/b.iloc[0]-1):+.2%}")
