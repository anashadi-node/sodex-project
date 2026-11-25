# SODEX 2× — KONSOLIDASI RISET & ACTION PLAN (2026-09-06)
> Sumber: (1) Blueprint corrected user, (2) riset task-0 "Doubling DEX perp swing",
> (3) riset task-1 "sideways-bear playbook", (4) replay EMERGENCY_SL mandiri,
> (5) analisa throughput mandiri. Semua verifikasi data nyata.

## STRATEGI 2× — 3 PILAR (bisa dieksekusi 4-6 minggu)

### PILAR A — Portfolio Surgery (lever terbesar, x1.5-2.2 net)
**Fakta (SWING n=156):** 7 pair profit membawa +$405, 11 pair loss -$225.
Top-7: BTC, ETH, SOL, DOGE, UNI, AAVE, ENA. Bottom-11: XRP, ADA, ZEC, BCH, SUI,
ONDO, LINK, ASTER, BNB, TRX (+1).
- ✅ Konsisten dgn forensik sebelumnya (BTC/SOL/DOGE/UNI lolos BH-FDR).
- ⚠️ Jujur: per-pair n~9 — ini PRIOR, bukan bukti final. Butuh verifikasi 4
  minggu dgn Empirical-Bayes posterior WR.
- Aksi: universe LATIH fokus ke top-7 di paper (probation list utk 11 loser),
  FDR-drop hanya kalau n>=15 & p-adjusted<0.05.

### PILAR B — Exit Redesign (fix terbesar: EMERGENCY_SL 25% trade)
**Replay mandiri (n=39):** 24h recovery 35.9%, 48h recovery 48.7%.
- VERDIKT: **INCONCLUSIVE** -> JANGAN ubah EMERGENCY_SL (bukan prematur-cut
  terbukti). Ini penting: riset menduga leak, data menolak.
- Aksi T1 (tiered TP + breakeven): tutup 50% di +1R, sisa stop ke entry,
  run leg dgn ATR-trail 2.0-2.5x — potensi E +0.04-0.08R/trade (+30-60%).
  Kami SUDAH punya breakeven-trail (SL_PROTECT) — tinggal tambah partial+ATR.

### PILAR C — Filter Murah (session/funding/micro)
- **S1 entry-hour**: entry hanya 13:00-20:00 UTC + Sunday 19:00-24:00;
  ban 01:00-06:00. Literatur (Hsu 2020; Concretum 2025): WR +3-7pp.
  KAMI SUDAH punya dead-zone (5/12/17/18 UTC) — tinggal gabungkan & perluas.
- **M1 funding filter**: no-long saat funding > +0.05%/8h atau >90th pct.
  Funding ekstrem = crowded; prefer against-side.
- **M2 OI confirmation**: entry hanya saat OI delta 4h setuju arah.

### PILAR D — Risk Bunker ($139)
- Kelly: REALWIDE full 31.8% -> pakai 1.0-1.5% risk/trade (=4-5% Kelly).
- Caps: <=3 concurrent, <=2 same-direction, portfolio risk <=4%,
  max 1 per pair. (SoDEX SOL live sudah maxpos 1.)
- P4 cross-pair kill: 3+ position red -0.5R -> flatten 2 lemah.

## STATUS EKSEKUSI SEKARANG
| Item | Status |
|---|---|
| EMERGENCY_SL replay | ✅ DONE (inconclusive, jangan ubah) |
| Gate contradiction fix | ✅ DONE (regime NEUTRAL, commit 30a60fb) |
| ASTER exclude live | ✅ DONE (commit d3f0964) |
| Maturation | 9/30, WR 100%, ROI +9% — estimasi n=30: **±3-4 hari** |
| Filter short (r1h<0, no-weekend) | ✅ DONE (komit a9fcf68) |
| Pair prune top-7 | ⏳ Belum — butuh approval & verifikasi 4 minggu |
| T1 partial+ATR trail | ⏳ Belum |
| S1/M1/M2 filters | ⏳ Belum — S1 bisa digabung dgn dead-zone |
| R2 caps konfirmasi | ⏳ Sebagian terpasang (realwide maxpos 1) |

## REKOMENDASI PERTANYAAN KE USER (approval gates)
1. Setujui **T1** (partial-TP 50% +1R + ATR-trail) di paper? (1 variabel, 3-4
   minggu uji, E +30-60% potensial)
2. Setujui **S1** perluasan dead-zone entry-hour di paper (13-20 UTC main)?
3. Setujui **P1** fokus universe 23->7 di PAPER (probation 11 pair)?
4. Live realwide tetap 22-pair (ASTER excluded) sampai maturasi n=30 lulus.

## RISIKO KUNCI (jujur)
- SoDEX OI/funding feed availability BELUM diverifikasi (M1/M2 tergantung ini).
- n per pair kecil — hindari overfit drop pair (pakai FDR n>=15).
- Biaya (funding, maker fee) makan 7-14% dari gross 0.7% edge — hitung selalu
  NET-of-costs.