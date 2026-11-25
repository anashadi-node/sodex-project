#!/usr/bin/env python3
"""
H1b — SIMULASI KEBIJAKAN EXIT pada trade nyata (kelanjutan H1).
Sesuai skill riset-penelitian: falsifikasi, kontrol negatif, bootstrap CI, fail-closed.

Untuk setiap trade kita replay lintasan harga (candle 1h Binance sebagai proxy) dan
menerapkan beberapa kebijakan exit alternatif, lalu membandingkan E[R] & WR setelah biaya.

Kebijakan:
  baseline        : hasil aktual sistem (dari record)
  tp_0.5R / 1R / 1.5R / 2R : target tetap
  ladder_1R       : 50% di +1R, sisa stop ke BE, keluar di akhir jendela
  trail_0.5R / 0.75R / 1R  : trailing stop dari puncak
  time_half       : keluar di 50% durasi aktual
  RANDOM (kontrol negatif): keluar di bar acak dalam jendela

Aturan konservatif intrabar: bila satu candle menyentuh SL DAN TP, anggap SL lebih dulu.
Biaya: round-trip 9 bps (taker) diterapkan pada setiap kebijakan (termasuk baseline).
FAIL-CLOSED: trade tanpa lintasan harga -> DIBUANG dan dihitung; tidak pernah dianggap lulus.
"""
import json, math, os, random
from datetime import datetime
import pandas as pd
import numpy as np

ROOT = '/home/USER/anantara-sakti'
DATA = f'{ROOT}/freqtrade_user_data/data/binance/futures'
OUT = f'{ROOT}/docs/research/masterplan/riset_metode_sodex_cex_20260914/H1B_SIM.json'
FEE_RT = 9e-4          # 9 bps round-trip (fraksi)
BARS = 5000
random.seed(20260914)

POLICIES = ['baseline', 'tp_0.5R', 'tp_1R', 'tp_1.5R', 'tp_2R',
            'ladder_1R', 'trail_0.5R', 'trail_0.75R', 'trail_1R',
            'time_half', 'RANDOM_control']


def load_trades():
    trades = []
    for rel, key, tag in [('data/paper_test_realwide_state.json', 'closed', 'realwide'),
                          ('data/paper_test_twoway_state.json', 'closed_trades', 'twoway'),
                          ('data/paper_test_swing_state.json', 'closed_trades', 'swing')]:
        p = f'{ROOT}/{rel}'
        if not os.path.exists(p):
            continue
        d = json.load(open(p))
        for t in d.get(key, []):
            try:
                if tag == 'realwide':
                    sym = t['sym']; side = 'L' if t['side'] == 'L' else 'S'
                    e_iso, x_iso = t['entry_iso'], t['exit_iso']
                    ep = float(t['entry_p']); tp, sl = float(t['tp']), float(t['sl'])
                else:
                    sym = t['pair']; side = 'L' if t['direction'] == 'LONG' else 'S'
                    e_iso, x_iso = t['entry_time'], t['exit_time']
                    ep = float(t['entry_price'])
                    sl = abs(ep - float(t['sl_price'])) / ep
                    tp = abs(float(t['tp_price']) - ep) / ep
                if not (sym and e_iso and x_iso and ep > 0 and sl > 0):
                    continue
                trades.append(dict(tag=tag, sym=sym, side=side, e_iso=e_iso, x_iso=x_iso,
                                   entry=ep, sl=sl, tp=tp,
                                   pnl_pct=float(t.get('pnl_pct') or 0.0)))
            except Exception:
                continue
    return trades


_cache = {}
def candles(sym):
    if sym in _cache:
        return _cache[sym]
    f = f'{DATA}/{sym}_USDT_USDT-1h-futures.feather'
    d = None
    if os.path.exists(f):
        x = pd.read_feather(f)
        c = [k for k in x.columns if 'date' in k.lower() or 'time' in k.lower()][0]
        x = x.rename(columns={c: 'ts'})
        x['ts'] = pd.to_datetime(x['ts'], utc=True, errors='coerce')
        d = x.dropna(subset=['ts']).sort_values('ts').reset_index(drop=True)
    _cache[sym] = d
    return d


def ts(s):
    try:
        return pd.Timestamp(datetime.fromisoformat(str(s).replace('Z', '+00:00')))
    except Exception:
        try:
            return pd.to_datetime(float(s), unit='s', utc=True)
        except Exception:
            return None


def run_policy(H, L, Cl, entry, risk, side, pol, holdbars):
    """Kembalikan R tercapai (fraksi gerak / risk). Konservatif: SL dicek sebelum TP."""
    fav_sign = 1.0 if side == 'L' else -1.0
    n = len(Cl)
    if pol == 'RANDOM_control':
        i = random.randrange(n)
        return fav_sign * (Cl[i] - entry) / entry / risk
    if pol == 'time_half':
        j = max(1, int(holdbars * 0.5))
        j = min(j, n - 1)
        return fav_sign * (Cl[j] - entry) / entry / risk
    if pol.startswith('tp_'):
        k = float(pol[3:-1])
        tgt = entry * (1 + fav_sign * k * risk)
        stop = entry * (1 - fav_sign * risk)
        for i in range(n):
            hi, lo = H[i], L[i]
            hit_stop = (lo <= stop) if side == 'L' else (hi >= stop)
            hit_tp = (hi >= tgt) if side == 'L' else (lo <= tgt)
            if hit_stop:
                return -1.0
            if hit_tp:
                return k
        return fav_sign * (Cl[-1] - entry) / entry / risk
    if pol == 'ladder_1R':
        tgt = entry * (1 + fav_sign * 1.0 * risk)
        stop = entry * (1 - fav_sign * risk)
        be = entry
        half_done = False
        for i in range(n):
            hi, lo = H[i], L[i]
            if not half_done and ((hi >= tgt) if side == 'L' else (lo <= tgt)):
                half_done = True
                stop = be
            hit_stop = (lo <= stop) if side == 'L' else (hi >= stop)
            if hit_stop:
                tail = 0.0 if half_done else -1.0
                return (0.5 * 1.0 + 0.5 * tail) if half_done else -1.0
        tail = fav_sign * (Cl[-1] - entry) / entry / risk
        return 0.5 * (1.0 if half_done else tail) + 0.5 * tail if half_done else tail
    if pol.startswith('trail_'):
        k = float(pol[6:-1])
        peak = entry
        stop = entry * (1 - fav_sign * risk)
        for i in range(n):
            hi, lo = H[i], L[i]
            if side == 'L':
                peak = max(peak, hi)
                stop = max(stop, peak - k * risk * entry)
                if lo <= stop:
                    return (stop - entry) / entry / risk
            else:
                peak = min(peak, lo)
                stop = min(stop, peak + k * risk * entry)
                if hi >= stop:
                    return (entry - stop) / entry / risk
        return fav_sign * (Cl[-1] - entry) / entry / risk
    return 0.0


def ci95(x):
    x = np.asarray(x, dtype=float)
    if len(x) < 5:
        return (float('nan'), float('nan'))
    rng = np.random.default_rng(7)
    bs = [np.mean(rng.choice(x, size=len(x), replace=True)) for _ in range(2000)]
    return (float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5)))


def main():
    trades = load_trades()
    rows = []
    dropped = 0
    for t in trades:
        e = ts(t['e_iso']); x = ts(t['x_iso'])
        if e is None or x is None or x <= e:
            dropped += 1; continue
        d = candles(t['sym'])
        if d is None or not len(d):
            dropped += 1; continue
        w = d[(d['ts'] >= e) & (d['ts'] <= x)]
        if len(w) < 2:
            dropped += 1; continue
        H = w['high'].astype(float).values
        L = w['low'].astype(float).values
        Cl = w['close'].astype(float).values
        risk = t['sl']; side = t['side']; entry = t['entry']
        row = dict(tag=t['tag'], sym=t['sym'], side=side, holdbars=len(w))
        for pol in POLICIES:
            r = run_policy(H, L, Cl, entry, risk, side, pol, len(w))
            row[pol] = r * risk - FEE_RT / risk if False else r          # R murni
            row[pol + '__netpct'] = r * risk - FEE_RT                     # net fraksi harga
        row['baseline_actual_pct'] = t['pnl_pct']
        rows.append(row)
        del w

    print(f'trade dimuat={len(trades)} dianalisis={len(rows)} dibuang(fail-closed)={dropped}')
    if not rows:
        raise SystemExit('FAIL-CLOSED: tidak ada trade yang bisa dianalisis')
    df = pd.DataFrame(rows)

    res = {'n': int(len(df)), 'dropped': int(dropped), 'fee_rt_bps': FEE_RT * 1e4, 'policies': {}}
    print(f"\n{'kebijakan':<18}{'E[R]':>9}{'medianR':>9}{'WR%':>7}{'CI95 E[R]':>22}{'net bps':>10}")
    for pol in POLICIES:
        r = df[pol].astype(float)
        net = df[pol + '__netpct'].astype(float)
        lo, hi = ci95(r)
        res['policies'][pol] = dict(
            n=int(len(r)), mean_R=float(r.mean()), median_R=float(r.median()),
            wr=float((r > 0).mean()), ci95=[lo, hi],
            net_bps_mean=float(net.mean()), net_bps_sum=float(net.sum()))
        print(f'{pol:<18}{r.mean():>9.3f}{r.median():>9.3f}{(r>0).mean()*100:>7.1f}'
              f'{"["+format(lo,".3f")+", "+format(hi,".3f")+"]":>22}{net.mean()*1e4:>10.1f}')

    # baseline aktual untuk pembanding
    res['baseline_actual'] = dict(
        mean_pct=float(df['baseline_actual_pct'].mean()),
        median_pct=float(df['baseline_actual_pct'].median()),
        wr=float((df['baseline_actual_pct'] > 0).mean()))

    json.dump(res, open(OUT, 'w'), indent=1, default=str)
    print(f"\nbaseline AKTUAL (record): mean={res['baseline_actual']['mean_pct']*100:.3f}% "
          f"median={res['baseline_actual']['median_pct']*100:.3f}% WR={res['baseline_actual']['wr']*100:.1f}%")
    print(f'tersimpan: {OUT}')


if __name__ == '__main__':
    main()
