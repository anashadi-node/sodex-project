#!/usr/bin/env python3
"""
H1b v4 — NEUTRALISASI BETA (G6). Perbaikan atas v3 yang terkontaminasi drift pasar.

Masalah v3: sampel 95% LONG pada pasar yang naik +32% (BTC, 56 hari).
   -> E[R] semua kebijakan memuat beta, dan kebijakan "tahan lebih lama" menangkap lebih banyak beta.
Perbaikan: untuk setiap trade, hitung EXCESS return terhadap pasar pada horizon yang SAMA:
   excess_t = sign_t * r_trade_t - sign_t * r_market_t     (beta = 1, pasar = BTC)
   R_excess = excess / risk
Semua kebijakan dinilai ulang pada R_excess. Kontrol negatif diuji ulang.
"""
import json, math, os, random
from datetime import datetime
import pandas as pd
import numpy as np

ROOT = '/home/USER/anantara-sakti'
DATA = f'{ROOT}/freqtrade_user_data/data/binance/futures'
OUT = f'{ROOT}/docs/research/masterplan/riset_metode_sodex_cex_20260914/H1B_V4_BETANEUTRAL.json'
FEE = 8e-4
STRESS = [1.0, 1.5, 2.0]
HZ = 24
random.seed(20260914)
POLICIES = ['tp_0.5R', 'tp_1R', 'tp_1.5R', 'tp_2R', 'ladder_1R', 'trail_0.5R',
            'trail_0.75R', 'trail_1R', 'time_half', 'hold_to_end', 'RANDOM_control']


def candles(sym):
    f = f'{DATA}/{sym}_USDT_USDT-1h-futures.feather'
    if not os.path.exists(f):
        return None
    x = pd.read_feather(f)
    c = [k for k in x.columns if 'date' in k.lower() or 'time' in k.lower()][0]
    x = x.rename(columns={c: 'ts'})
    x['ts'] = pd.to_datetime(x['ts'], utc=True, errors='coerce')
    return x.dropna(subset=['ts']).sort_values('ts').reset_index(drop=True)


def ts_of(s):
    try:
        return pd.Timestamp(datetime.fromisoformat(str(s).replace('Z', '+00:00')))
    except Exception:
        try:
            return pd.to_datetime(float(s), unit='s', utc=True)
        except Exception:
            return None


def sim(H, L, C, entry, risk, side, pol, n):
    if n < 2:
        return float('nan')
    s = 1.0 if side == 'L' else -1.0
    if pol == 'hold_to_end':
        return s * (C[-1] - entry) / entry / risk
    if pol == 'time_half':
        return s * (C[max(1, n // 2)] - entry) / entry / risk
    if pol == 'RANDOM_control':
        return s * (C[random.randrange(n)] - entry) / entry / risk
    if pol.startswith('tp_'):
        k = float(pol[3:-1]); stop = entry * (1 - s * risk); tgt = entry * (1 + s * k * risk)
        for i in range(n):
            if (L[i] <= stop) if side == 'L' else (H[i] >= stop):
                return -1.0
            if (H[i] >= tgt) if side == 'L' else (L[i] <= tgt):
                return k
        return s * (C[-1] - entry) / entry / risk
    if pol == 'ladder_1R':
        stop = entry * (1 - s * risk); tgt = entry * (1 + s * 1.0 * risk); half = False
        for i in range(n):
            if not half and ((H[i] >= tgt) if side == 'L' else (L[i] <= tgt)):
                half = True; stop = entry
            if (L[i] <= stop) if side == 'L' else (H[i] >= stop):
                return 0.5 * 1.0 if half else -1.0
        tail = s * (C[-1] - entry) / entry / risk
        return (0.5 * 1.0 + 0.5 * tail) if half else tail
    if pol.startswith('trail_'):
        k = float(pol[6:-1]); peak = entry; stop = entry * (1 - s * risk)
        for i in range(n):
            if side == 'L':
                peak = max(peak, H[i]); stop = max(stop, peak - k * risk * entry)
                if L[i] <= stop:
                    return (stop - entry) / entry / risk
            else:
                peak = min(peak, L[i]); stop = min(stop, peak + k * risk * entry)
                if H[i] >= stop:
                    return (entry - stop) / entry / risk
        return s * (C[-1] - entry) / entry / risk
    return float('nan')


def boot_ci(x, it=2000, seed=13):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    if len(x) < 8:
        return float('nan'), float('nan')
    rng = np.random.default_rng(seed)
    b = [float(np.mean(rng.choice(x, len(x), replace=True))) for _ in range(it)]
    return float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))


def main():
    # trades
    tr = []
    for rel, key, tag in [('data/paper_test_realwide_state.json', 'closed', 'realwide'),
                          ('data/paper_test_twoway_state.json', 'closed_trades', 'twoway'),
                          ('data/paper_test_swing_state.json', 'closed_trades', 'swing')]:
        p = f'{ROOT}/{rel}'
        if not os.path.exists(p):
            continue
        for t in json.load(open(p)).get(key, []):
            try:
                if tag == 'realwide':
                    tr.append(dict(tag=tag, sym=t['sym'], side='L' if t['side'] == 'L' else 'S',
                                   e=t['entry_iso'], entry=float(t['entry_p']), sl=float(t['sl']),
                                   pnl=float(t.get('pnl_pct') or 0.0)))
                else:
                    ep = float(t['entry_price'])
                    tr.append(dict(tag=tag, sym=t['pair'],
                                   side='L' if t['direction'] == 'LONG' else 'S',
                                   e=t['entry_time'], entry=ep,
                                   sl=abs(ep - float(t['sl_price'])) / ep,
                                   pnl=float(t.get('pnl_pct') or 0.0)))
            except Exception:
                continue

    btc = candles('BTC').set_index('ts')['close'].astype(float)

    rows, dropped = [], 0
    for t in tr:
        e = ts_of(t['e'])
        if e is None or not t['sl'] > 0:
            dropped += 1; continue
        d = candles(t['sym'])
        if d is None or not len(d):
            dropped += 1; continue
        w = d[(d['ts'] >= e) & (d['ts'] < e + pd.Timedelta(hours=HZ))]
        if len(w) < 6:
            dropped += 1; continue
        # pasar pada horizon sama
        mw = btc[(btc.index >= e) & (btc.index < e + pd.Timedelta(hours=HZ))]
        if len(mw) < 6:
            dropped += 1; continue
        r_mkt = float(mw.iloc[-1] / mw.iloc[0] - 1) * (1.0 if t['side'] == 'L' else -1.0)

        H = w['high'].astype(float).values; L = w['low'].astype(float).values
        C = w['close'].astype(float).values
        risk = t['sl']; feeR = FEE / risk
        row = dict(sym=t['sym'], tag=t['tag'], side=t['side'], t_entry=e, n=len(w),
                   r_mkt=r_mkt, risk=risk,
                   actual_excess_R=(t['pnl'] - r_mkt) / risk)
        for p in POLICIES:
            g = sim(H, L, C, t['entry'], risk, t['side'], p, len(w))
            row[p + '_raw'] = g
            row[p] = (g - r_mkt / risk) if not math.isnan(g) else float('nan')   # EXCESS
            for m in STRESS:
                row[f'{p}__net{m}'] = (row[p] - feeR * m) if not math.isnan(row[p]) else float('nan')
        rows.append(row)
        del w

    df = pd.DataFrame(rows)
    print(f'trade={len(tr)} dianalisis={len(df)} dibuang={dropped} | horizon {HZ}j | pasar=BTC')
    print(f'rata-rata return pasar searah posisi pada horizon: {df.r_mkt.mean()*100:+.3f}% '
          f'(median {df.r_mkt.median()*100:+.3f}%)')
    print(f'actual EXCESS R: mean={df.actual_excess_R.mean():.3f} median={df.actual_excess_R.median():.3f}')

    res = {'n': len(df), 'horizon_h': HZ, 'fee_bps': FEE * 1e4,
           'mean_market_move_%': float(df.r_mkt.mean() * 100), 'policies': {}}
    print(f"\n{'kebijakan (EXCESS R)':<22}{'E[R]':>8}{'medR':>8}{'WR%':>7}{'CI95':>20}{'net1x':>8}{'net2x':>8}")
    for p in POLICIES:
        v = df[p].astype(float)
        if v.notna().sum() < 8:
            res['policies'][p] = {'FAILED': int(v.notna().sum())}
            print(f'{p:<22}  GAGAL (n={int(v.notna().sum())})'); continue
        lo, hi = boot_ci(v)
        e = dict(n=int(v.notna().sum()), meanR=float(v.mean()), medianR=float(v.median()),
                 wr=float((v > 0).mean()), ci95=[lo, hi],
                 net1x=float(df[f'{p}__net1.0'].mean()), net2=float(df[f'{p}__net2.0'].mean()),
                 meanR_raw=float(df[p + '_raw'].mean()))
        res['policies'][p] = e
        print(f"{p:<22}{e['meanR']:>8.3f}{e['medianR']:>8.3f}{e['wr']*100:>7.1f}"
              f"{'['+format(lo,'.3f')+','+format(hi,'.3f')+']':>20}{e['net1x']:>8.3f}{e['net2']:>8.3f}")

    rc = res['policies'].get('RANDOM_control', {})
    cand = {k: v for k, v in res['policies'].items() if 'net1x' in v}
    best = max(cand, key=lambda k: cand[k]['net1x']) if cand else None
    res['negative_control'] = {'random_net1x': rc.get('net1x'), 'best': best,
                               'best_net1x': cand[best]['net1x'] if best else None,
                               'passed': bool(best and cand[best]['net1x'] > rc.get('net1x', 9) + 0.02)}
    print(f"\n>> KONTROL NEGATIF (excess): random={rc.get('net1x')} | terbaik={best} "
          f"({cand[best]['net1x'] if best else None}) | "
          f"{'LULUS' if res['negative_control']['passed'] else 'GAGAL — tidak ada kebijakan mengalahkan acak (+) setelah beta dinetralkan'}")

    json.dump(res, open(OUT, 'w'), indent=1, default=str)
    print(f'tersimpan: {OUT}')


if __name__ == '__main__':
    main()
