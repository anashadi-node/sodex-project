#!/usr/bin/env python3
"""
H1b v3 — KEBIJAKAN EXIT dengan HORIZON TETAP (perbaikan 2 cacat v2)
  v2 cacat-1: kolom 'baseline' tidak terpetakan -> harness fail-closed (benar, tapi tak ada data)
  v2 cacat-2: KONTROL NEGATIF LOLOS karena jendela = [entry, exit aktual]
              -> random exit = keluar di tengah hold -> menang otomatis (set uji terlalu mudah)

v3: SEMUA kebijakan disimulasikan pada HORIZON TETAP H jam dari entry (H=24 primer, 48 sensitivitas),
    jadi kontrol negatif benar-benar acak dalam horizon yang sama. Baseline aktual dilaporkan
    terpisah sebagai referensi (bukan pembanding langsung, karena holdnya berbeda-beda).

Gate: G2 cost stress 1x/1.5x/2x | G3 universe likuid vs mikro | G4 long vs short |
      G5 stabilitas 4 subperiode | G7 kriteria = R bersih | B0 Donchian sebagai benchmark.
"""
import json, math, os, random
from datetime import datetime
import pandas as pd
import numpy as np

ROOT = '/home/USER/anantara-sakti'
DATA = f'{ROOT}/freqtrade_user_data/data/binance/futures'
OUT = f'{ROOT}/docs/research/masterplan/riset_metode_sodex_cex_20260914/H1B_V3.json'
FEE = 8e-4
STRESS = [1.0, 1.5, 2.0]
HORIZONS = [24, 48]
N_RANDOM = 25          # kontrol negatif: rata-rata 25 undian acak per trade (stabil)
random.seed(20260914)

POLICIES = ['tp_0.5R', 'tp_1R', 'tp_1.5R', 'tp_2R', 'ladder_1R',
            'trail_0.5R', 'trail_0.75R', 'trail_1R', 'time_half', 'hold_to_end', 'RANDOM_control']


def load_trades():
    out = []
    for rel, key, tag in [('data/paper_test_realwide_state.json', 'closed', 'realwide'),
                          ('data/paper_test_twoway_state.json', 'closed_trades', 'twoway'),
                          ('data/paper_test_swing_state.json', 'closed_trades', 'swing')]:
        p = f'{ROOT}/{rel}'
        if not os.path.exists(p):
            continue
        for t in json.load(open(p)).get(key, []):
            try:
                if tag == 'realwide':
                    sym = t['sym']; side = 'L' if t['side'] == 'L' else 'S'
                    e = t['entry_iso']; ep = float(t['entry_p']); sl = float(t['sl'])
                else:
                    sym = t['pair']; side = 'L' if t['direction'] == 'LONG' else 'S'
                    e = t['entry_time']; ep = float(t['entry_price'])
                    sl = abs(ep - float(t['sl_price'])) / ep
                if not (sym and e and ep > 0 and sl > 0):
                    continue
                out.append(dict(tag=tag, sym=sym, side=side, e=e, entry=ep, sl=sl,
                                actual_pct=float(t.get('pnl_pct') or 0.0)))
            except Exception:
                continue
    return out


_c = {}
def candles(sym):
    if sym in _c:
        return _c[sym]
    f = f'{DATA}/{sym}_USDT_USDT-1h-futures.feather'
    d = None
    if os.path.exists(f):
        x = pd.read_feather(f)
        c = [k for k in x.columns if 'date' in k.lower() or 'time' in k.lower()][0]
        x = x.rename(columns={c: 'ts'})
        x['ts'] = pd.to_datetime(x['ts'], utc=True, errors='coerce')
        d = x.dropna(subset=['ts']).sort_values('ts').reset_index(drop=True)
    _c[sym] = d
    return d


def ts_of(s):
    try:
        return pd.Timestamp(datetime.fromisoformat(str(s).replace('Z', '+00:00')))
    except Exception:
        try:
            return pd.to_datetime(float(s), unit='s', utc=True)
        except Exception:
            return None


def sim(H, L, C, entry, risk, side, pol, n):
    """Simulasi pada horizon tetap n bar. Return R. NaN = gagal (fail-closed)."""
    if n < 2:
        return float('nan')
    s = 1.0 if side == 'L' else -1.0
    if pol == 'hold_to_end':
        return s * (C[-1] - entry) / entry / risk
    if pol == 'time_half':
        j = max(1, n // 2)
        return s * (C[j] - entry) / entry / risk
    if pol == 'RANDOM_control':
        i = random.randrange(n)
        return s * (C[i] - entry) / entry / risk
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


def boot_ci(x, it=2000, seed=11):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    if len(x) < 8:
        return float('nan'), float('nan')
    rng = np.random.default_rng(seed)
    bs = [float(np.mean(rng.choice(x, len(x), replace=True))) for _ in range(it)]
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def b0(syms, t0, t1, fee):
    daily = []
    for sym in syms:
        d = candles(sym)
        if d is None or len(d) < 400:
            continue
        s = d.set_index('ts')['close'].astype(float).resample('1D').last().dropna()
        s = s[(s.index >= t0) & (s.index <= t1)]
        if len(s) < 60:
            continue
        sig = pd.concat([(s > s.rolling(L).max().shift(1)).astype(float)
                         for L in (5, 10, 15, 20, 25, 30, 40, 50, 60)], axis=1).mean(axis=1)
        pos = (sig > 0.5).astype(float)
        r = s.pct_change().fillna(0.0)
        st = pos.shift(1).fillna(0.0) * r - (pos - pos.shift(1).fillna(0.0)).abs() * fee
        daily.append(st.rename(sym))
    if not daily:
        return None
    port = pd.concat(daily, axis=1).mean(axis=1)
    eq = (1 + port).cumprod(); yrs = max(len(port) / 365.0, 1e-9)
    sd = float(port.std())
    return dict(n_days=int(len(port)), n_syms=len(daily),
                cagr=float(eq.iloc[-1] ** (1 / yrs) - 1), total=float(eq.iloc[-1] - 1),
                sharpe=float(port.mean() / sd * math.sqrt(365)) if sd > 0 else float('nan'),
                maxdd=float((eq / eq.cummax() - 1).min()))


def main():
    trades = load_trades()
    adv = {}
    for t in trades:
        if t['sym'] not in adv:
            d = candles(t['sym'])
            if d is not None and len(d):
                qc = [c for c in d.columns if 'quote' in c.lower()]
                q = (pd.to_numeric(d[qc[0]], errors='coerce') if qc
                     else pd.to_numeric(d['close'], errors='coerce') * pd.to_numeric(d['volume'], errors='coerce'))
                adv[t['sym']] = float(q.dropna().median()) if len(q.dropna()) else None
            else:
                adv[t['sym']] = None
    vals = sorted([v for v in adv.values() if v], reverse=True)
    thr = vals[len(vals) // 4] if vals else 0.0

    res = {'fee_bps': FEE * 1e4, 'liquid_threshold_adv_usd': thr, 'horizons': {}}
    for HZ in HORIZONS:
        rows, dropped, short = [], 0, 0
        for t in trades:
            e = ts_of(t['e'])
            if e is None:
                dropped += 1; continue
            d = candles(t['sym'])
            if d is None or not len(d):
                dropped += 1; continue
            w = d[(d['ts'] >= e) & (d['ts'] < e + pd.Timedelta(hours=HZ))]
            if len(w) < max(4, HZ // 4):
                dropped += 1; continue
            H = w['high'].astype(float).values; L = w['low'].astype(float).values
            C = w['close'].astype(float).values
            risk = t['sl']; feeR = FEE / risk
            r = dict(sym=t['sym'], tag=t['tag'], side=t['side'], t_entry=e, nbars=len(w),
                     adv=adv.get(t['sym']), risk=risk, actual_R=t['actual_pct'] / risk,
                     adv_ok=(adv.get(t['sym']) or 0) >= thr)
            for p in POLICIES:
                g = sim(H, L, C, t['entry'], risk, t['side'], p, len(w))
                r[p] = g
                for m in STRESS:
                    r[f'{p}__net{m}'] = g - feeR * m if not math.isnan(g) else float('nan')
            rows.append(r)
            del w
        df = pd.DataFrame(rows)
        if df.empty:
            res['horizons'][f'H{HZ}'] = {'FAILED': 'no rows'}
            continue
        print(f"\n############ HORIZON TETAP {HZ} JAM ############")
        print(f"trade dianalisis={len(df)} dibuang(fail-closed)={dropped} | "
              f"LIQUID n={int(df.adv_ok.sum())} MICRO n={int((~df.adv_ok).sum())} | "
              f"LONG n={int((df.side=='L').sum())} SHORT n={int((df.side=='S').sum())}")
        blk = {'n': int(len(df)), 'dropped': int(dropped),
               'actual_R_mean': float(df.actual_R.mean()), 'actual_R_median': float(df.actual_R.median()),
               'policies': {}}
        print(f"{'kebijakan':<16}{'E[R]':>8}{'medR':>8}{'WR%':>7}{'CI95 E[R]':>20}"
              f"{'net1x':>8}{'net1.5x':>9}{'net2x':>8}")
        for p in POLICIES:
            v = df[p].astype(float)
            if v.notna().sum() < 8:
                blk['policies'][p] = {'FAILED': int(v.notna().sum())}
                print(f'{p:<16}  GAGAL (n valid={int(v.notna().sum())})'); continue
            lo, hi = boot_ci(v)
            e = dict(n=int(v.notna().sum()), meanR=float(v.mean()), medianR=float(v.median()),
                     wr=float((v > 0).mean()), ci95=[lo, hi],
                     net1x=float(df[f'{p}__net1.0'].mean()),
                     net1_5=float(df[f'{p}__net1.5'].mean()),
                     net2=float(df[f'{p}__net2.0'].mean()))
            blk['policies'][p] = e
            print(f"{p:<16}{e['meanR']:>8.3f}{e['medianR']:>8.3f}{e['wr']*100:>7.1f}"
                  f"{'['+format(lo,'.3f')+','+format(hi,'.3f')+']':>20}"
                  f"{e['net1x']:>8.3f}{e['net1_5']:>9.3f}{e['net2']:>8.3f}")
        # kontrol negatif
        rc = blk['policies'].get('RANDOM_control', {})
        best = max([v for k, v in blk['policies'].items() if 'net1x' in v],
                   key=lambda z: z['net1x'], default=None)
        if rc and best:
            blk['negative_control'] = {
                'random_net1x': rc.get('net1x'), 'best_policy_net1x': best['net1x'],
                'control_passed': bool(best['net1x'] > rc.get('net1x', 0) + 0.02)}
            print(f"  >> KONTROL NEGATIF: random net1x={rc.get('net1x'):.3f} | "
                  f"kebijakan terbaik={best['net1x']:.3f} | "
                  f"{'LULUS (kebijakan > random+0.02R)' if blk['negative_control']['control_passed'] else 'GAGAL — tidak ada kebijakan yang mengalahkan acak secara berarti'}")
        # G4 + G5 pada LIQUID saja
        liq = df[df.adv_ok]
        if len(liq) >= 30:
            blk['liquid_only'] = {}
            print(f"  -- G3 LIQUID ONLY (n={len(liq)}) --")
            for p in ['tp_1R', 'tp_2R', 'ladder_1R', 'time_half', 'RANDOM_control']:
                blk['liquid_only'][p] = float(liq[f'{p}__net1.0'].mean())
                print(f"     {p:<15} net1x={liq[f'{p}__net1.0'].mean():>7.3f}")
            ls = liq[liq.side == 'L']; ss = liq[liq.side == 'S']
            blk['by_side'] = {'L': {'n': int(len(ls)), 'tp_1R': float(ls['tp_1R__net1.0'].mean()) if len(ls) else None,
                                    'ladder_1R': float(ls['ladder_1R__net1.0'].mean()) if len(ls) else None},
                              'S': {'n': int(len(ss)), 'tp_1R': float(ss['tp_1R__net1.0'].mean()) if len(ss) else None,
                                    'ladder_1R': float(ss['ladder_1R__net1.0'].mean()) if len(ss) else None}}
            print(f"  -- G4 SPLIT -- LONG n={len(ls)} | SHORT n={len(ss)}"
                  + (" (SHORT power tidak cukup)" if len(ss) < 30 else ""))
            dfx = liq.sort_values('t_entry').reset_index(drop=True)
            qs = [dfx.iloc[i * len(dfx) // 4:(i + 1) * len(dfx) // 4] for i in range(4)]
            blk['by_quarter'] = {}
            print(f"  -- G5 SUBPERIODE (net1x) --")
            for p in ['tp_1R', 'tp_2R', 'ladder_1R', 'RANDOM_control']:
                vv = [float(q[f'{p}__net1.0'].mean()) for q in qs if len(q)]
                npos = sum(1 for x in vv if x > 0)
                blk['by_quarter'][p] = {'values': vv, 'n_pos': npos}
                print(f"     {p:<15} " + ' '.join(f'{x:>7.3f}' for x in vv) + f'   positif {npos}/{len(vv)}')
        res['horizons'][f'H{HZ}'] = blk

    # B0
    t0 = min(ts_of(t['e']) for t in trades if ts_of(t['e']) is not None)
    t1 = max(ts_of(t['e']) for t in trades if ts_of(t['e']) is not None)
    syms = sorted({t['sym'] for t in trades})
    res['B0'] = {}
    print(f"\n=== B0 Donchian-ensemble long/flat 1x | {t0.date()}..{t1.date()} | {len(syms)} simbol ===")
    for m in STRESS:
        b = b0(syms, t0, t1, FEE * m)
        if b:
            res['B0'][f'fee_{m}x'] = b
            print(f"  fee {m}x: hari={b['n_days']} CAGR={b['cagr']*100:>7.2f}% "
                  f"Sharpe={b['sharpe']:>5.2f} MaxDD={b['maxdd']*100:>6.1f}% total={b['total']*100:>7.1f}%")
    json.dump(res, open(OUT, 'w'), indent=1, default=str)
    print(f"\ntersimpan: {OUT}")


if __name__ == '__main__':
    main()
