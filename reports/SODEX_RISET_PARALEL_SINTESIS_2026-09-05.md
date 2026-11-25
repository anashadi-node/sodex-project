# SODEX — SINTESIS 5 RISET PARALEL & IMPLEMENTASI FILTER (2026-09-05)
## Sumber: 5 subagent riset paralel (549 trades, 6 track, 2026-08-06 s/d 09-05)

## TEMUAN KUAT (semua lolos signifikansi)
### 1. DEAD ZONE jam UTC 5/12/17/18
- n=88: WR 27.3%, avg -0.73% (p=1.2e-05 vs sisa) — **TERVALIDASI lintas 549 trade**
- Prime zone 3/10/15 UTC: n=95, WR 71.6%, avg +1.25% (p=5.1e-07)
- Konsisten per-track: SWING 20%→50.8%, TWOWAY 28.9%→55.4%, PARTIAL 33.3%→59.8%
- ✅ IMPLEMENTED (paper)

### 2. VOLATILITY GATE ATR14 1h
- SL-cepat masuk saat ATR 2x normal (2.37% vs 1.17%, q=0.016 FDR — satu-satunya metrik lolos univariat)
- Filter ATR>2%: buang 13/59, hilangkan 7/12 SL-cepat, WR 52.5→54.3%
- ✅ IMPLEMENTED (paper)

### 3. PAIR LOLOS BH-FDR: BTC +0.70%, SOL +0.80%, DOGE +0.72%, UNI +1.12%
- ETH +0.37% positif tidak signifikan; AAVE/ZEC flat; tidak ada pair n≥20 rugi signifikan
- BCH/SUI negatif preliminer (n<20)

### 4. HOLD 8-30 jam sweet spot: +1.62%, WR 61.3% (p=0.0085 FDR)
- Hold <8h rugi (WR 33-37%); >30h flat (modal terikat)
- TP avg 8.6h vs SL avg 6.5h

### 5. BREAKEVEN-TRAIL: SL_PROTECT WR 75.9% (FDR-sig)
- ✅ IMPLEMENTED (paper): peak_g ≥1.2% → keluar ≤0.4%

### 6. PORTFOLIO: 2-3 posisi sedang (SOL+UNI+DOGE, L=2) TERBAIK
- E[daily ROI] +4.93%, P(≥0.7%)=61.3%, maxDD 15.7%
- L=3 BERBAHAYA semua skenario (P(ruin) 5-10%)

### 7. Kelly: f*=4.69 DILARANG (ruin 42.6%); batas quarter-to-half = 1.2-2.4x

### 8. Conviction TIDAK prediktif (r=0.05, p=0.30) — jangan sizing berdasar conviction

## IMPLEMENTASI (PAPER ONLY — sesuai prinsip maturasi)
- `_entry_vol_gate()`: skip entry ATR14/C > 2%
- `_entry_dead_zone_hour()`: skip entry jam UTC 5/12/17/18
- `peak_g` breakeven-trail (SL_PROTECT)

## LIVE: TETAP TP4/SL2 pinned — menunggu n≥30 forward evidence geometri baru
## DONCHIAN: berhenti (edge negatif, Kelly=0) — pertimbangkan ganti universe