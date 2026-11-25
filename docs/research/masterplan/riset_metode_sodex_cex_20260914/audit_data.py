#!/usr/bin/env python3
"""Audit kelayakan data untuk metode riset (SoDEX + CEX-Binance)."""
import pandas as pd, glob, os, collections, json

BASE = '/home/USER/anantara-sakti/freqtrade_user_data/data'
out = {}

# 1) Simbol & rentang historis (binance futures)
rows = []
for f in sorted(glob.glob(f'{BASE}/binance/futures/*-1h-futures.feather')):
    sym = os.path.basename(f).split('_')[0]
    try:
        d = pd.read_feather(f)
        c = [x for x in d.columns if 'date' in x.lower() or 'time' in x.lower()][0]
        rows.append((sym, len(d), str(d[c].min())[:10], str(d[c].max())[:10]))
    except Exception as e:
        rows.append((sym, -1, 'ERR', str(e)[:30]))

print(f"=== BINANCE FUTURES 1h: {len(rows)} simbol ===")
if rows:
    mins = min(r[2] for r in rows if r[1] > 0)
    maxs = max(r[3] for r in rows if r[1] > 0)
    tot = sum(r[1] for r in rows if r[1] > 0)
    print(f"rentang gabungan: {mins} .. {maxs} | total baris 1h: {tot:,}")
    print("contoh:", rows[:5])
    # distribusi panjang
    lens = sorted(r[1] for r in rows if r[1] > 0)
    print(f"baris/simbol: min={lens[0]:,} median={lens[len(lens)//2]:,} max={lens[-1]:,}")

# 2) timeframe lain
for tf in ['4h', '1d']:
    fs = glob.glob(f'{BASE}/binance/futures/*-{tf}-futures.feather')
    print(f"{tf}: {len(fs)} file")

# 3) funding rate
fs = glob.glob(f'{BASE}/binance/futures/*-funding_rate.feather')
print(f"funding: {len(fs)} file")
if fs:
    d = pd.read_feather(fs[0])
    c = [x for x in d.columns if 'date' in x.lower() or 'time' in x.lower()][0]
    print(f"  contoh {os.path.basename(fs[0])}: rows={len(d)} {str(d[c].min())[:10]}..{str(d[c].max())[:10]} cols={list(d.columns)}")

# 4) venue lain
for v in ['okx', 'bitget', 'bybit', 'hyperliquid']:
    fs = glob.glob(f'{BASE}/{v}/**/*.feather', recursive=True)
    if fs:
        print(f"{v}: {len(fs)} file")

# 5) OBI
obi = '/home/USER/anantara-sakti/data/pregain_v24/features/obi_1m.jsonl'
if os.path.exists(obi):
    print(f"\nOBI: {os.path.getsize(obi)/1e6:.1f} MB")
    with open(obi) as fh:
        first = fh.readline()
        n = 1
        for _ in fh:
            n += 1
            if n > 200000:
                break
    rec = json.loads(first)
    print(f"  baris(dibaca)={'>=200000' if n>200000 else n} keys={list(rec.keys())}")
    print(f"  contoh={ {k: str(v)[:40] for k, v in list(rec.items())[:8]} }")
