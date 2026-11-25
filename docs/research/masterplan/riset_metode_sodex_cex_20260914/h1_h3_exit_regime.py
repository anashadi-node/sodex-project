#!/usr/bin/env python3
"""
RISET H1 + H3 — Analisis empiris exit-geometry & regime volatilitas.
Data: state trade SoDEX (3 track) + candle Binance 1h sebagai proxy lintasan harga.

H1: ukur MAE/MFE dalam satuan R (|entry-sl|) -> evaluasi apakah bracket mekanis
    memulihkan kerugian, dan berapa banyak winner yang "hampir kena stop".
H3: E[R] per sextile volatilitas realisasi saat entry.

Output: JSON ringkas + tabel ke stdout. TIDAK mengubah sistem apa pun.
"""
import json, math, os, statistics as st
from datetime import datetime, timezone
import pandas as pd

ROOT = '/home/USER/anantara-sakti'
DATA = f'{ROOT}/freqtrade_user_data/data/binance/futures'
OUT = f'{ROOT}/docs/research/masterplan/riset_metode_sodex_cex_20260914/H1_H3_RESULT.json'

def load_trades():
    trades = []
    specs = [
        ('data/paper_test_realwide_state.json', 'closed', 'realwide'),
        ('data/paper_test_twoway_state.json', 'closed_trades', 'twoway'),
        ('data/paper_test_swing_state.json', 'closed_trades', 'swing'),
    ]
    for rel, key, tag in specs:
        p = f'{ROOT}/{rel}'
        if not os.path.exists(p):
            continue
        d = json.load(open(p))
        for t in d.get(key, []):
            try:
                if tag == 'realwide':
                    sym = t['sym']; side = 'L' if t['side'] == 'L' else 'S'
                    e_iso, x_iso = t['entry_iso'], t['exit_iso']
                    ep, xp = float(t['entry_p']), float(t['exit_p'])
                    tp, sl, lev = float(t['tp']), float(t['sl']), float(t.get('lev', 1))
                    exit_r = t.get('exit_r')
                else:
                    sym = t['pair']; side = 'L' if t['direction'] == 'LONG' else 'S'
                    e_iso, x_iso = t['entry_time'], t['exit_time']
                    ep, xp = float(t['entry_price']), float(t['exit_price'])
                    tp_p, sl_p = float(t['tp_price']), float(t['sl_price'])
                    risk = abs(ep - sl_p) / ep if ep else None
                    tp = abs(tp_p - ep) / ep if ep else None
                    sl = risk; lev = 1.0
                    exit_r = t.get('exit_reason')
                if not (sym and e_iso and x_iso and ep > 0 and xp > 0):
                    continue
                trades.append(dict(tag=tag, sym=sym, side=side, entry_iso=e_iso, exit_iso=x_iso,
                                   entry=ep, exit=xp, tp=tp, sl=sl, lev=lev, exit_r=str(exit_r),
                                   pnl_pct=float(t.get('pnl_pct') or 0.0),
                                   wallet_roi=float(t.get('wallet_roi') or 0.0),
                                   hold_h=float(t.get('hold_h') or t.get('hold_hours') or 0.0)))
            except Exception:
                continue
    return trades

def load_candles(sym, tf='1h'):
    f = f'{DATA}/{sym}_USDT_USDT-{tf}-futures.feather'
    if not os.path.exists(f):
        return None
    d = pd.read_feather(f)
    c = [x for x in d.columns if 'date' in x.lower() or 'time' in x.lower()][0]
    d = d.rename(columns={c: 'ts'})
    d['ts'] = pd.to_datetime(d['ts'], utc=True, errors='coerce')
    d = d.dropna(subset=['ts']).sort_values('ts')
    return d

def parse_iso(s):
    try:
        return pd.Timestamp(datetime.fromisoformat(str(s).replace('Z', '+00:00')))
    except Exception:
        try:
            return pd.to_datetime(float(s), unit='s', utc=True)
        except Exception:
            return None

def analyse():
    trades = load_trades()
    print(f"trades dimuat: {len(trades)}")

    cache = {}
    rows = []
    missing = 0
    for t in trades:
        e = parse_iso(t['entry_iso']); x = parse_iso(t['exit_iso'])
        if e is None or x is None or x <= e:
            missing += 1; continue
        sym = t['sym']
        if sym not in cache:
            cache[sym] = load_candles(sym)
        d = cache[sym]
        if d is None or not len(d):
            missing += 1; continue
        w = d[(d['ts'] >= e) & (d['ts'] <= x)]
        if not len(w):
            missing += 1; continue

        ep = t['entry']; risk = t['sl']
        if not risk or risk <= 0:
            missing += 1; continue

        hi = float(w['high'].max()); lo = float(w['low'].min())
        if t['side'] == 'L':
            mfe = (hi - ep) / ep      # favorable
            mae = (lo - ep) / ep      # adverse (negatif)
        else:
            mfe = (ep - lo) / ep
            mae = (ep - hi) / ep

        r_mae = mae / risk    # berapa R melawan
        r_mfe = mfe / risk    # berapa R menguntungkan
        realized = t['pnl_pct'] / risk if risk else 0.0   # R tercapai

        # volatilitas realisasi 24 candle sebelum entry (proxy regime)
        pre = d[d['ts'] < e].tail(24)
        rv = None
        if len(pre) > 3:
            rets = pre['close'].pct_change().dropna()
            if len(rets) > 2:
                rv = float(rets.std() * math.sqrt(24))

        rows.append(dict(**{k: t[k] for k in ('tag','sym','side','exit_r','lev','hold_h')},
                         treat_pct=t['pnl_pct'], wallet_roi=t['wallet_roi'],
                         risk=risk, r_mae=r_mae, r_mfe=r_mfe, realized_R=realized, rv24=rv))
        del w

    print(f"dianalisis: {len(rows)} | dilewati (tanpa candle/tanggal): {missing}")
    if not rows:
        return None

    df = pd.DataFrame(rows)
    res = {}
    res['n'] = int(len(df))

    # --- Ringkasan dasar
    res['mean_treat_pct'] = float(df['treat_pct'].mean())
    res['median_treat_pct'] = float(df['treat_pct'].median())
    res['wr'] = float((df['treat_pct'] > 0).mean())

    # --- H1: statistik R
    res['H1'] = {
        'n': int(len(df)),
        'median_R_realized': float(df['realized_R'].median()),
        'mean_R_realized': float(df['realized_R'].mean()),
        'median_r_mfe': float(df['r_mfe'].median()),
        'median_r_mae': float(df['r_mae'].median()),
        # winner yang sempat nyaris kena stop (MAE hampir -1R)
        'frac_winners_mae_worse_than_-0.75R': float(((df['treat_pct'] > 0) & (df['r_mae'] <= -0.75)).mean()),
        # loser yang sempat capai +1R (bracket akan menyelamatkan)
        'frac_losers_touched_+1R': float(((df['treat_pct'] <= 0) & (df['r_mfe'] >= 1.0)).mean()),
        'frac_losers_touched_+0.5R': float(((df['treat_pct'] <= 0) & (df['r_mfe'] >= 0.5)).mean()),
        'frac_all_touched_+1R': float((df['r_mfe'] >= 1.0).mean()),
        'frac_all_touched_+0.5R': float((df['r_mfe'] >= 0.5).mean()),
    }
    # Perluasan bukti P04: posisi capai >= +300bps (favorable excursion) tapi ditutup negatif
    df = df.copy()
    df['fav_bps'] = df['r_mfe'] * df['risk'] * 1e4
    res['H1']['frac_fav300_with_negative_close'] = float(
        ((df['fav_bps'] >= 300) & (df['treat_pct'] <= 0)).sum() / max((df['fav_bps'] >= 300).sum(), 1))
    res['H1']['frac_positions_reaching_+300bps'] = float((df['fav_bps'] >= 300).mean())

    # --- H3: sextile volatilitas
    d3 = df.dropna(subset=['rv24']).copy()
    if len(d3) > 24:
        try:
            d3['sext'] = pd.qcut(d3['rv24'], 6, labels=False, duplicates='drop')
            g = d3.groupby('sext').agg(n=('treat_pct', 'size'),
                                       mean_pct=('treat_pct', 'mean'),
                                       median_pct=('treat_pct', 'median'),
                                       wr=('treat_pct', lambda s: float((s > 0).mean())),
                                       mean_R=('realized_R', 'mean'),
                                       rv_lo=('rv24', 'min'), rv_hi=('rv24', 'max'))
            res['H3_sextile_vol'] = json.loads(g.reset_index().to_json(orient='records'))
        except Exception as e:
            res['H3_sextile_vol'] = f'ERR {e}'

    json.dump(res, open(OUT, 'w'), indent=1, default=str)
    print('\n=== H1 (exit geometry) ===')
    for k, v in res['H1'].items():
        print(f"  {k}: {v}")
    print('\n=== H3 (E[R] per sextile volatilitas 24h pra-entry) ===')
    for r in res.get('H3_sextile_vol', []) if isinstance(res.get('H3_sextile_vol'), list) else []:
        print(f"  sextil {int(r['sext'])}: n={int(r['n'])} mean={r['mean_pct']*100:.3f}% "
              f"median={r['median_pct']*100:.3f}% WR={r['wr']*100:.1f}% "
              f"rv[{r['rv_lo']*100:.2f}%..{r['rv_hi']*100:.2f}%]")
    print(f"\ntersimpan: {OUT}")
    return res

if __name__ == '__main__':
    analyse()
