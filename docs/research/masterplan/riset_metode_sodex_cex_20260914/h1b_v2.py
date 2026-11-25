#!/usr/bin/env python3
"""
H1b v2 — SIMULASI KEBIJAKAN EXIT dengan PROTOKOL DIPERKETAT (ANANTARA Master Evidence V1/V2)

Gate yang diterapkan:
  G2  cost stress 1x / 1,5x / 2x  (fee 8 bps RT SoDEX tier-0 sebagai basis)
  G3  universe: laporkan TERPISAH likuid vs mikro-cap (ADV dari candle 1h)
  G4  alpha long vs short TERPISAH
  G5  stabilitas 4 subperiode kronologis
  G7  kriteria = R bersih, BUKAN akurasi/label
  B0  benchmark Donchian-ensemble long/flat 1x pada universe & periode sama

Kontrol negatif: RANDOM_control (keluar di bar acak) HARUS kalah.
Fail-closed: trade tanpa lintasan harga DIBUANG + dihitung; NaN -> policy ditandai GAGAL.
"""
import json, math, os, random
from datetime import datetime
import pandas as pd
import numpy as np

ROOT = '/home/USER/anantara-sakti'
DATA = f'{ROOT}/freqtrade_user_data/data/binance/futures'
OUT = f'{ROOT}/docs/research/masterplan/riset_metode_sodex_cex_20260914/H1B_V2.json'
FEE_BASE = 8e-4          # SoDEX perp tier-0 taker round-trip (0,040% x2) = 8 bps
STRESS = [1.0, 1.5, 2.0]
random.seed(20260914)

POLICIES = ['baseline', 'tp_0.5R', 'tp_1R', 'tp_1.5R', 'tp_2R', 'ladder_1R',
            'trail_0.5R', 'trail_0.75R', 'trail_1R', 'time_half', 'RANDOM_control']


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
                    e, x = t['entry_iso'], t['exit_iso']
                    ep = float(t['entry_p']); sl = float(t['sl'])
                else:
                    sym = t['pair']; side = 'L' if t['direction'] == 'LONG' else 'S'
                    e, x = t['entry_time'], t['exit_time']
                    ep = float(t['entry_price']); sl = abs(ep - float(t['sl_price'])) / ep
                if not (sym and e and x and ep > 0 and sl > 0):
                    continue
                out.append(dict(tag=tag, sym=sym, side=side, e=e, x=x, entry=ep, sl=sl,
                                pnl_pct=float(t.get('pnl_pct') or 0.0)))
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


def adv_usd(sym):
    """Median dollar volume per jam (proxy likuiditas)."""
    d = candles(sym)
    if d is None or len(d) < 50:
        return None, None
    qcol = [c for c in d.columns if 'quote' in c.lower()]
    if qcol:
        q = pd.to_numeric(d[qcol[0]], errors='coerce').dropna()
    else:
        q = (pd.to_numeric(d['close'], errors='coerce') *
             pd.to_numeric(d['volume'], errors='coerce')).dropna()
    return (float(q.median()) if len(q) else None), d


def sim_policy(H, L, C, entry, risk, side, pol, holdbars):
    s = 1.0 if side == 'L' else -1.0
    n = len(C)
    if n == 0:
        return float('nan')
    if pol == 'RANDOM_control':
        i = random.randrange(n)
        return s * (C[i] - entry) / entry / risk
    if pol == 'time_half':
        j = min(max(1, int(holdbars * 0.5)), n - 1)
        return s * (C[j] - entry) / entry / risk
    if pol.startswith('tp_'):
        k = float(pol[3:-1])
        tgt = entry * (1 + s * k * risk); stop = entry * (1 - s * risk)
        for i in range(n):
            if (L[i] <= stop) if side == 'L' else (H[i] >= stop):
                return -1.0
            if (H[i] >= tgt) if side == 'L' else (L[i] <= tgt):
                return k
        return s * (C[-1] - entry) / entry / risk
    if pol == 'ladder_1R':
        tgt = entry * (1 + s * 1.0 * risk); stop = entry * (1 - s * risk)
        half = False
        for i in range(n):
            if not half and ((H[i] >= tgt) if side == 'L' else (L[i] <= tgt)):
                half = True; stop = entry
            if (L[i] <= stop) if side == 'L' else (H[i] >= stop):
                tail = 0.0 if half else -1.0
                return 0.5 * 1.0 + 0.5 * tail if half else -1.0
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


def boot_ci(x, it=2000, seed=7):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    if len(x) < 8:
        return float('nan'), float('nan')
    rng = np.random.default_rng(seed)
    bs = [np.mean(rng.choice(x, len(x), replace=True)) for _ in range(it)]
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def b0_donchian(syms, t0, t1, fee=8e-4, lookbacks=(5, 10, 15, 20, 25, 30, 40, 50, 60)):
    """B0 = Donchian-ensemble long/flat, 1x, cost per turnover. Return harian di periode."""
    daily = []
    for sym in syms:
        d = candles(sym)
        if d is None or len(d) < 400:
            continue
        s = d.set_index('ts')['close'].astype(float).resample('1D').last().dropna()
        s = s[(s.index >= t0) & (s.index <= t1)]
        if len(s) < 60:
            continue
        sigs = []
        for L in lookbacks:
            hh = s.rolling(L).max().shift(1)
            sigs.append((s > hh).astype(float))
        sig = pd.concat(sigs, axis=1).mean(axis=1)
        pos = (sig > 0.5).astype(float)          # long/flat
        ret = s.pct_change().fillna(0.0)
        pos_prev = pos.shift(1).fillna(0.0)
        turn = (pos - pos_prev).abs()
        strat = pos_prev * ret - turn * fee
        daily.append(strat.rename(sym))
    if not daily:
        return None
    M = pd.concat(daily, axis=1)
    port = M.mean(axis=1)                        # equal-weight ensemble
    eq = (1 + port).cumprod()
    yrs = max(len(port) / 365.0, 1e-9)
    cagr = float(eq.iloc[-1] ** (1 / yrs) - 1) if len(eq) else float('nan')
    sd = float(port.std())
    sharpe = float(port.mean() / sd * math.sqrt(365)) if sd > 0 else float('nan')
    dd = float((eq / eq.cummax() - 1).min()) if len(eq) else float('nan')
    return dict(n_days=int(len(port)), n_syms=int(M.shape[1]), cagr=cagr,
                sharpe=sharpe, maxdd=dd, total=float(eq.iloc[-1] - 1) if len(eq) else float('nan'))


def main():
    trades = load_trades()
    liq = {}
    for t in trades:
        if t['sym'] not in liq:
            liq[t['sym']] = adv_usd(t['sym'])[0]
    advs = sorted([v for v in liq.values() if v], reverse=True)
    if advs:
        thr = advs[len(advs) // 4]                # ambang kuartil teratas = "likuid"
    else:
        thr = 0.0

    rows, dropped = [], 0
    for t in trades:
        e, x = ts_of(t['e']), ts_of(t['x'])
        if e is None or x is None or x <= e:
            dropped += 1; continue
        d = candles(t['sym'])
        if d is None or not len(d):
            dropped += 1; continue
        w = d[(d['ts'] >= e) & (d['ts'] <= x)]
        if len(w) < 2:
            dropped += 1; continue
        H = w['high'].astype(float).values; L = w['low'].astype(float).values
        C = w['close'].astype(float).values
        risk = t['sl']; feeR = FEE_BASE / risk
        r = dict(sym=t['sym'], tag=t['tag'], side=t['side'], t_entry=e, nbars=len(w),
                 adv=liq.get(t['sym']), risk=risk, feeR=feeR,
                 actual_R=t['pnl_pct'] / risk if risk else float('nan'))
        for p in POLICIES:
            g = sim_policy(H, L, C, t['entry'], risk, t['side'], p, len(w))
            r[p] = g
            for m in STRESS:
                r[f'{p}__net{m}'] = (g - feeR * m) if not math.isnan(g) else float('nan')
        # capture ratio: realized / MFE
        mfe = max((H.max() - t['entry']) / t['entry'] if t['side'] == 'L'
                  else (t['entry'] - L.min()) / t['entry'], 0.0) / risk
        r['MFE_R'] = mfe
        r['capture'] = (r['actual_R'] / mfe) if mfe > 0.05 else float('nan')
        rows.append(r)
        del w

    df = pd.DataFrame(rows)
    print(f'trade dimuat={len(trades)} dianalisis={len(df)} dibuang(fail-closed)={dropped}')
    if df.empty:
        raise SystemExit('FAIL-CLOSED: tidak ada trade')

    res = {'n': len(df), 'dropped': dropped, 'fee_base_bps': FEE_BASE * 1e4,
           'liquid_threshold_adv_usd': thr, 'policies': {}}

    # G3 universes
    df['universe'] = np.where(df['adv'] >= thr, 'LIQUID', 'MICRO')
    print(f"\nuniverse: ambang ADV=${thr:,.0f}/jam | "
          f"LIQUID n={int((df.universe=='LIQUID').sum())} MICRO n={int((df.universe=='MICRO').sum())}")
    print(f"side   : LONG n={int((df.side=='L').sum())} SHORT n={int((df.side=='S').sum())}")

    print(f"\n=== KEBIJAKAN EXIT — SELURUH SAMPEL (n={len(df)}), fee {FEE_BASE*1e4:.0f} bps RT ===")
    hdr = f"{'kebijakan':<16}{'E[R]':>8}{'medR':>8}{'WR%':>7}{'CI95 E[R]':>20}{'net1x':>8}{'net1.5x':>9}{'net2x':>8}"
    print(hdr)
    for p in POLICIES:
        v = df[p].astype(float); ok = v.notna().sum()
        if ok < 8:
            res['policies'][p] = {'FAILED': 'sampel tidak cukup'}
            print(f'{p:<16}  GAGAL (n valid={ok})')
            continue
        lo, hi = boot_ci(v)
        e = {'n': int(ok), 'meanR': float(v.mean()), 'medianR': float(v.median()),
             'wr': float((v > 0).mean()), 'ci95': [lo, hi],
             'net1x': float(df[f'{p}__net1.0'].mean()), 'net1_5x': float(df[f'{p}__net1.5'].mean()),
             'net2x': float(df[f'{p}__net2.0'].mean())}
        res['policies'][p] = e
        print(f"{p:<16}{e['meanR']:>8.3f}{e['medianR']:>8.3f}{e['wr']*100:>7.1f}"
              f"{'['+format(lo,'.3f')+','+format(hi,'.3f')+']':>20}"
              f"{e['net1x']:>8.3f}{e['net1_5x']:>9.3f}{e['net2x']:>8.3f}")

    # G4 split
    print('\n=== G4: LONG vs SHORT (E[R] bersih 1x) ===')
    res['by_side'] = {}
    for side in ['L', 'S']:
        sub = df[df.side == side]
        if len(sub) < 10:
            print(f'  {side}: n={len(sub)} — TERLALU KECIL untuk disimpulkan')
            res['by_side'][side] = {'n': int(len(sub)), 'note': 'power tidak cukup'}
            continue
        res['by_side'][side] = {'n': int(len(sub))}
        print(f'  {side}: n={len(sub)}')
        for p in ['baseline', 'tp_1R', 'ladder_1R', 'trail_0.75R']:
            e = sub[f'{p}__net1.0'].mean()
            res['by_side'][side][p] = float(e)
            print(f'     {p:<14} net1x E[R] = {e:>7.3f}')

    # G5 subperiode
    print('\n=== G5: STABILITAS 4 SUBPERIODE (E[R] bersih 1x) ===')
    dfx = df.sort_values('t_entry').reset_index(drop=True)
    qs = np.array_split(dfx, 4)
    res['by_quarter'] = {}
    keys = ['baseline', 'tp_1R', 'ladder_1R', 'trail_0.75R']
    print(f"{'kebijakan':<14}" + ''.join(f"{'Q'+str(i+1):>9}" for i in range(4)) + f"{'positif':>9}")
    for p in keys:
        vals = [float(q[f'{p}__net1.0'].mean()) for q in qs]
        npos = sum(1 for v in vals if v > 0)
        res['by_quarter'][p] = {'values': vals, 'n_positive': npos}
        print(f'{p:<14}' + ''.join(f'{v:>9.3f}' for v in vals) + f'{npos:>6}/4')

    # capture ratio
    cap = df['capture'].dropna()
    if len(cap) > 10:
        res['capture_ratio'] = {'n': int(len(cap)), 'median': float(cap.median()),
                                'mean': float(cap.mean()),
                                'frac_negative': float((cap < 0).mean())}
        print(f"\n=== CAPTURE RATIO (realized / MFE) n={len(cap)} ===")
        print(f"  median={cap.median():.3f} | mean={cap.mean():.3f} | "
              f"proporsi capture negatif={100*(cap<0).mean():.1f}%")

    # B0 benchmark
    t0 = df['t_entry'].min(); t1 = df['t_entry'].max()
    syms = sorted(df['sym'].unique())
    res['B0'] = {}
    print(f"\n=== B0 (Donchian-ensemble long/flat 1x) — periode sama {t0.date()}..{t1.date()} ===")
    for m in STRESS:
        b = b0_donchian(syms, t0, t1, fee=FEE_BASE * m)
        if b:
            res['B0'][f'fee_{m}x'] = b
            print(f"  fee {m}x: hari={b['n_days']} simbol={b['n_syms']} "
                  f"CAGR={b['cagr']*100:.2f}% Sharpe={b['sharpe']:.2f} MaxDD={b['maxdd']*100:.1f}% total={b['total']*100:.1f}%")

    json.dump(res, open(OUT, 'w'), indent=1, default=str)
    print(f'\ntersimpan: {OUT}')


if __name__ == '__main__':
    main()
