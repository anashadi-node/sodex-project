#!/usr/bin/env python3
"""
ANANTARA SAKTI — Gate 1 Backtest v3: Hold-Duration-Optimized
=============================================================
v2 BUG: pnl_usd always 0 — fixed in v3.
v2 FINDING: Hold-duration thesis CONFIRMED.
  1-6h:  -0.50% avg, 20% WR  → LOSS ZONE
  6-12h: +0.05% avg, 34% WR  → BREAKEVEN
  12-24h: +0.75% avg, 49% WR → PROFIT ZONE
  24-48h: +0.88% avg, 65% WR → BEST ZONE

v3 strategy: Only enter when setup quality high AND let trades run.
  - MIN_HOLD_BEFORE_SL = 12h (don't cut winners during loss zone)
  - Target trades: ~50-100 per pair in 17 months (quality > quantity)
  - Confirm cooldown works properly
"""
from __future__ import annotations

import json, math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT / "freqtrade_user_data" / "data" / "binance" / "futures"
OUT_DIR = PROJECT / "data" / "gate1_backtest"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── SoDEX costs ───────────────────────────────────────────────────────────
MAKER_FEE = 0.00024  # round-trip
SPREAD_MAP = {"BTC": 0.00013, "ETH": 0.00020, "SOL": 0.00035}
LEVERAGE = 5
NOTIONAL = 100.0  # per trade notional (for PnL calc)
TP_PCT = 0.025
SL_PCT = 0.010
TIME_STOP_H = 48
MAX_POS = 2
COOLDOWN_BARS = 24  # 24h between entries
MIN_HOLD_SL_H = 12  # v3: don't SL in first 12h (avoid loss zone)
MIN_WARMUP = 200

# Entry (same as v2, tuned)
MOM_ADX_MIN = 25
MOM_TREND_STRENGTH = 0.012
MR_SHOCK = -0.030
MR_RSI_OVERSOLD = 25
MR_VOL_RATIO = 1.3
MR_BB = 20

def rsi(c, p=14):
    d = np.diff(c, prepend=c[0])
    g = np.where(d>0,d,0.); l = np.where(d<0,-d,0.)
    ag = pd.Series(g).ewm(span=p,adjust=False).mean().values
    al = pd.Series(l).ewm(span=p,adjust=False).mean().values
    return 100-100/(1+np.divide(ag,al,out=np.ones_like(ag),where=al>0))

def bb(c,p=20,ns=2.0):
    m=pd.Series(c).rolling(p).mean().values; s=pd.Series(c).rolling(p).std().values
    return m,m+ns*s,m-ns*s

def rr(c,lb):
    r=np.full_like(c,np.nan); r[lb:]=(c[lb:]-c[:-lb])/c[:-lb]; return r

def sma(c,p): return pd.Series(c).rolling(p).mean().values

def atr(h,l,c,p=14):
    tr=np.maximum(h-l,np.maximum(abs(h-np.roll(c,1)),abs(l-np.roll(c,1)))); tr[0]=h[0]-l[0]
    return pd.Series(tr).ewm(span=p,adjust=False).mean().values

def adx(h,l,c,p=14):
    t=atr(h,l,c,p); u=h-np.roll(h,1); d=np.roll(l,1)-l
    pdm=np.where((u>d)&(u>0),u,0.); ndm=np.where((d>u)&(d>0),d,0.)
    ts=pd.Series(t).ewm(span=p,adjust=False).mean().values
    pdi=100*pd.Series(pdm).ewm(span=p,adjust=False).mean().values/ts
    ndi=100*pd.Series(ndm).ewm(span=p,adjust=False).mean().values/ts
    return pd.Series(100*abs(pdi-ndi)/(pdi+ndi+1e-10)).ewm(span=p,adjust=False).mean().values

def load(sym):
    df=pd.read_feather(DATA_DIR/f"{sym}_USDT_USDT-1h-futures.feather")
    cs={c.lower():c for c in df.columns}
    return {"dates":pd.to_datetime(df[cs.get("date",df.columns[0])]).values,
            "o":df[cs.get("open","open")].values.astype(float),
            "h":df[cs.get("high","high")].values.astype(float),
            "l":df[cs.get("low","low")].values.astype(float),
            "c":df[cs.get("close","close")].values.astype(float),
            "v":df[cs.get("volume","volume")].values.astype(float)}

def regime(d,i):
    if i<MIN_WARMUP: return "UNKNOWN"
    c,h,l=d["c"],d["h"],d["l"]
    a=adx(h,l,c); s50=sma(c,50); s200=sma(c,200)
    if i>=200 and a[i]>MOM_ADX_MIN and c[i]>s50[i] and s50[i]>s200[i]: return "MOMENTUM"
    if i>=50:
        rv=rsi(c)
        if a[i]<20 and (rv[i]<MR_RSI_OVERSOLD or rv[i]>70): return "MEAN_REVERT"
    return "UNKNOWN"

def signal(d,i,reg):
    if i<MIN_WARMUP: return {"active":False}
    c,h,l,v=d["c"],d["h"],d["l"],d["v"]
    rv=rsi(c); _,_,bl=bb(c,MR_BB,2.0); va=sma(v,24); vr=v[i]/va[i] if va[i]>0 else 1.0

    if reg=="MOMENTUM":
        r24=rr(c,24); r1=rr(c,1); s24=sma(c,24)
        chk=0
        if c[i]>s24[i]: chk+=1
        if 40<rv[i]<60: chk+=1
        if vr>1.1: chk+=1
        if i>=24 and not np.isnan(r24[i]) and r24[i]>MOM_TREND_STRENGTH: chk+=1
        if i>=1 and not np.isnan(r1[i]) and r1[i]<0.003: chk+=1
        if chk>=4: return {"active":True,"direction":"LONG","conviction":chk/5.0,"regime":"MOMENTUM"}

    elif reg=="MEAN_REVERT":
        r4=rr(c,4); chk=0
        if i>=4 and not np.isnan(r4[i]) and r4[i]<=MR_SHOCK: chk+=1
        if rv[i]<MR_RSI_OVERSOLD: chk+=1
        if i>=MR_BB and c[i]<=bl[i] and not np.isnan(bl[i]): chk+=1
        if vr>MR_VOL_RATIO: chk+=1
        if chk>=3: return {"active":True,"direction":"LONG","conviction":min(chk/3.0,1.0),"regime":"MEAN_REVERT"}

    return {"active":False}

@dataclass
class Trade:
    sym: str; entry_i: int; entry_p: float; entry_t: str; regime: str; conviction: float
    exit_i: int=-1; exit_p: float=0.0; exit_t: str=""; exit_r: str=""
    pnl_pct: float=0.0; pnl_usd: float=0.0; hold_h: float=0.0
    def close(self,i,p,ts,reason,spread):
        self.exit_i=i; self.exit_p=p; self.exit_t=ts; self.exit_r=reason
        gross=(p-self.entry_p)/self.entry_p
        cost=MAKER_FEE+spread
        self.pnl_pct=gross-cost
        self.pnl_usd=self.pnl_pct*NOTIONAL*LEVERAGE
        self.hold_h=(i-self.entry_i)*1.0

def run(sym,data):
    c,h,l,dates=data["c"],data["h"],data["l"],data["dates"]; n=len(c)
    spread=SPREAD_MAP.get(sym,0.0035); trades=[]; open_pos=[]; last_entry=-COOLDOWN_BARS
    buckets={"1-6h":[],"6-12h":[],"12-24h":[],"24-48h":[]}

    for i in range(MIN_WARMUP,n):
        price=c[i]; ts=str(dates[i])

        for t in list(open_pos):
            gross=(price-t.entry_p)/t.entry_p; exit_ok=False; reason=""
            hold_h=i-t.entry_i
            if gross>=TP_PCT: exit_ok=True; reason="TP"
            elif gross<=-SL_PCT and hold_h>=MIN_HOLD_SL_H: exit_ok=True; reason="SL"  # v3: min hold
            elif hold_h>=TIME_STOP_H: exit_ok=True; reason=f"TIME_{TIME_STOP_H}h"
            if exit_ok:
                t.close(i,price,ts,reason,spread); trades.append(t); open_pos.remove(t)
                hh=t.hold_h; pp=t.pnl_pct
                if hh<=6: buckets["1-6h"].append(pp)
                elif hh<=12: buckets["6-12h"].append(pp)
                elif hh<=24: buckets["12-24h"].append(pp)
                else: buckets["24-48h"].append(pp)

        if i-last_entry<COOLDOWN_BARS: continue
        if len(open_pos)>=MAX_POS: continue

        reg=regime(data,i); sig=signal(data,i,reg)
        if sig.get("active") and sig.get("direction")=="LONG":
            t=Trade(sym=sym,entry_i=i,entry_p=price,entry_t=ts,regime=reg,conviction=sig["conviction"])
            open_pos.append(t); last_entry=i

    for t in open_pos:
        t.close(n-1,c[-1],str(dates[-1]),"END_OF_DATA",spread); trades.append(t)
    return trades,buckets

def metrics(ts,buckets,sym):
    if not ts: return {"symbol":sym,"n_trades":0}
    pn=np.array([t.pnl_usd for t in ts]); pc=np.array([t.pnl_pct for t in ts])
    n=len(pn); w=int(np.sum(pn>0)); l=int(np.sum(pn<0)); wr=w/n
    gp=np.sum(pn[pn>0]) if w>0 else 0; gl=abs(np.sum(pn[pn<0])) if l>0 else 0
    pf=gp/gl if gl>0 else (float("inf") if gp>0 else 0)
    ttl=np.sum(pn); avg=np.mean(pn); std=np.std(pn)
    cum=np.cumsum(pn); dd=np.max(np.maximum.accumulate(cum)-cum); ddp=dd/(NOTIONAL*2)
    m=n//2; h1=pn[:m]; h2=pn[m:]
    h1pf=(h1[h1>0].sum()/abs(h1[h1<0].sum())) if (h1<0).sum()>0 else (float("inf") if (h1>0).sum()>0 else 0)
    h2pf=(h2[h2>0].sum()/abs(h2[h2<0].sum())) if (h2<0).sum()>0 else (float("inf") if (h2>0).sum()>0 else 0)
    sh=(avg/std)*math.sqrt(24*365) if std>0 else 0
    dsr=0; 
    if std>0 and n>1:
        ts2=avg/(std/math.sqrt(n)); dsr=1.0-math.exp(-(ts2**2)/(2*n))

    bk={}; 
    for bk2,pl in buckets.items():
        if pl: a2=np.array(pl); bk[bk2]={"n":len(a2),"avg":np.mean(a2),"med":np.median(a2),"wr":np.sum(a2>0)/len(a2)}

    rg={}; 
    for rv in ["MOMENTUM","MEAN_REVERT"]:
        rt=[t for t in ts if t.regime==rv]
        if rt: rp=[t.pnl_usd for t in rt]; rg[rv]={"n":len(rt),"pnl":sum(rp),"wr":sum(1 for p in rp if p>0)/len(rt),"avg":np.mean(rp)}

    er={r:sum(1 for t in ts if t.exit_r==r) for r in set(t.exit_r for t in ts)}
    return {"symbol":sym,"n_trades":n,"wins":w,"losses":l,"win_rate":wr,"profit_factor":pf,
            "total_pnl":ttl,"avg_trade":avg,"sharpe":sh,"dsr":dsr,"max_dd_pct":ddp,"max_dd_usd":dd,
            "split_half":{"h1_pf":h1pf,"h2_pf":h2pf},"hold_buckets":bk,"by_regime":rg,"exit_reasons":er}

def gate(m):
    pf=m.get("profit_factor",0); h1=m.get("split_half",{}).get("h1_pf",0); h2=m.get("split_half",{}).get("h2_pf",0)
    dsr=m.get("dsr",0); dd=m.get("max_dd_pct",1); n=m.get("n_trades",0)
    ck=[("PF>=1.4",isinstance(pf,(int,float))and pf>=1.4,pf),
        ("H1 PF>1.2",isinstance(h1,(int,float))and h1>1.2,h1),
        ("H2 PF>1.2",isinstance(h2,(int,float))and h2>1.2,h2),
        ("DSR>0.95",dsr>0.95,dsr),("Max DD<25%",dd<0.25,dd),("n>=30",n>=30,n)]
    ok=[c[1] for c in ck]; return {"verdict":"PASS" if all(ok) else "FAIL","checks":[{"check":c[0],"pass":c[1],"value":round(c[2],4) if isinstance(c[2],(int,float)) else c[2]} for c in ck],"score":sum(ok),"total":6}

def main():
    print("="*70); print("ANANTARA SAKTI — Gate 1 v3: Hold-Duration-Optimized"); print(f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"); print("="*70)
    syms=["BTC","ETH","SOL"]; all_t=[]; all_b={"1-6h":[],"6-12h":[],"12-24h":[],"24-48h":[]}
    for s in syms:
        print(f"\n{'─'*50}\n🔬 {s}/USDT (v3: min-hold 12h SL)...")
        d=load(s); print(f"   {len(d['c'])} bars, {d['dates'][0]} → {d['dates'][-1]}")
        ts,bk=run(s,d); m=metrics(ts,bk,s); g=gate(m); all_t.extend(ts)
        for k in all_b: all_b[k].extend(bk.get(k,[]))
        print(f"   Trades: {m['n_trades']} | PF: {m['profit_factor']:.2f} | WR: {m['win_rate']:.1%}")
        print(f"   PnL: ${m['total_pnl']:.2f} | DD: {m['max_dd_pct']:.1%} | DSR: {m['dsr']:.3f}")
        print(f"   Gate: {g['verdict']} ({g['score']}/{g['total']})")
        for k2,v2 in m.get("hold_buckets",{}).items():
            if v2["n"]>0: print(f"     {k2}: n={v2['n']} avg={v2['avg']:.4%} wr={v2['wr']:.1%}")
        print(f"   Exit: {m.get('exit_reasons',{})}")

    print(f"\n{'='*70}\n📊 COMBINED v3\n{'='*70}")
    if all_t:
        cm=metrics(all_t,all_b,"COMBINED"); cg=gate(cm)
        print(f"Trades: {cm['n_trades']} | PF: {cm['profit_factor']:.2f} | WR: {cm['win_rate']:.1%}")
        print(f"PnL: ${cm['total_pnl']:.2f} | DD: {cm['max_dd_pct']:.1%} | DSR: {cm['dsr']:.3f}")
        print(f"\n🎯 HOLD-DURATION:")
        for k2,v2 in cm.get("hold_buckets",{}).items():
            if v2["n"]>0: print(f"  {k2}: n={v2['n']} avg={v2['avg']:.4%} wr={v2['wr']:.1%}")
        print(f"\nGate: {cg['verdict']} ({cg['score']}/{cg['total']})")
        for c in cg["checks"]: print(f"  {'✅' if c['pass'] else '❌'} {c['check']}: {c['value']}")

    out={"version":"v3","ts":datetime.now(timezone.utc).isoformat(),"combined":cm if all_t else {}}
    with open(OUT_DIR/"backtest_v3_results.json","w") as f: json.dump(out,f,indent=2,default=str)
    with open(OUT_DIR/"trades_v3.jsonl","w") as f:
        for t in all_t: f.write(json.dumps(asdict(t),default=str)+"\n")
    print(f"\nSaved: {OUT_DIR}")

if __name__=="__main__": main()
