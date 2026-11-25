# AUDIT SoDEX + CEX — Continuous Improvement (Read-Only)

Tanggal: 2026-09-28 14:40 WIB · Cron dcdcace8f119 · Target terverifikasi: **0,8% TOTAL wallet divisi per rentang 30 jam, kumulatif** (user GO 27-Sep; commit 88180f7, 7be549b). Read-only: tidak ada kode/config/deploy diubah.

## SoDEX (REALWIDE perp paper + micro-live, wallet 174.55–279.74)

| Window | n | Sum PnL | WR | PF | CI95 bootstrap (10k) | p(EV>0) |
|---|---|---|---|---|---|---|
| Lifetime | 218 | +$177.58 | 50.0% | 1.36 | — | — |
| 30d | 185 | +$22.36 | 46.5% | — | [-0.87, +1.11]/trade | 58.6% |
| 7d | 54 | +$12.90 | 40.7% | 1.11 | [-1.47, +2.12]/trade | 58.6% |
| **30h berjalan** | 16 | **-$36.74** | **18.8%** | 0.38 | [-4.50, +1.07]/trade | **7.7%** |

- Rolling 30h (step 6h, 7d): **13/27 window ≥ target** (+$2.24 basis 279.74; sama pada basis 1.40/174.55), 14/27 negatif. Worst -$36.74 (= -13% wallet!), best +$31.86. Varian window >> target 0.8%.
- Per-trade ≥0.7% wallet ROI: 54/218 (24.8%) — basis per-trade memang mustahil, resmi kumulatif-per-window (konsisten keputusan gate v3).
- **Akar window merah: kaskade SL tanpa proteksi.** 7d: naked SL n=23, avg -$4.85 (total -$111.66 = 81% pendorong); SL_PROTECT n=16 justru +$4.27 (fitur kerja); TP n=4 +$73.26 (avg +18.32); TIME_30h n=10 +$52.96. Loser kecil tapi jumlahnya 6× winner.
- **Konflik rezim (temuan utama):** 100% entry 7d bertag `btc_regime=BULL` (LONG-only), padahal swing_deep_learning regime = **BEAR_MILD**, btc_mom_4h = -0.382, intel 32.3 BEARISH, F&G 37.8. Gate entry realwide tidak membaca sinyal intel-layer — pola identik lesin CEX 2026-09-09 (LONG cascade di tape turun → WR 0%).
- Conviction terbalik: cv=0.6 → +$35.12 (n=38); cv=0.8 → -$22.12 (n=14); cv=1.0 → -$0.11 (n=2). n<20 → MONITOR, bukan aksi.
- Micro-live (dana mikro): 5 trade 7d, **+$1.65**, campuran PEAK_TRAIL/TIME/SL — sehat.

## CEX (futures + spot paper)

| Track | 7d n | Sum pct | WR | p(EV>0) | Catatan |
|---|---|---|---|---|---|
| FUTURES SIGNAL | **0** | — | — | — | **Mati 14 hari** (exit terakhir 09-14) |
| FUTURES RANDOM | 29 | +16.70% | 44.8% | 87.5% | mesin exit positif |
| SPOT SIGNAL | **0** | — | — | — | Mati sejak 09-14 |
| SPOT RANDOM | 34 | +3.50% | 38.2% | 58.3% | |

- Deep loop verdict: NO_EDGE (Δ -0.399%, p=0.3285); SPRT REJECT_EDGE (LLR -3.78); matched_alpha SIGNAL -0.16% p_e_pos 0.006; quarantine agregat AKTIF; spot-ofi-long di-vETO (n=49, E=-0.225%, PF 0.75); spot-mom-adx probe n=7. Signal-off = by design, benar.
- **Bottleneck CEX**: sinyal alpha-negatif (terverifikasi) + tidak ada jalur entry terverifikasi positif → kontribusi ke target 0.8% = 0 sambil konsumsi kapasitas. Plus: track CEX tidak mencatat wallet-ROI → kontribusi window tak terukur langsung.

## SHORTBEAR — stall 12 hari (Phase 2.7/2.8 class)

Terakhir exit 2026-09-16; n=15 lifetime (WR 66.7%, PF 0.91). Regime sekarang BEAR_MILD = geometri ideal MR-SHORT, UCB1 weight tertinggi (1.80) — learner INGIN track ini jalan tapi 0 trade 12 hari. Kandidat bug reachability, bukan kondisi pasar.

## Temuan Struktur Lain

1. **Denominator divergence**: `.env.swing SODEX_TOTAL_WALLET=174.55` vs wallet live 279.74 (ae55b22) → target window $1.40 vs $2.24 (selisih 60%). Trap denominator dari audit skill — harus direkonsiliasi sebelum evaluasi gate.
2. **Kontaminan di window_plan.json**: top_assets memuat BOXX/QQQ/TSLA/SCHD (saham ter-tokenisasi) — mode RECOMMEND-ONLY jadi tidak ada efek trade, tapi melanggar pola "purge kontaminan di SEMUA daftar universe".
3. LINK_SHORT hard-block aktif di blocklist CEX (konsisten, tidak ada anomali).

## BLOCK_CANDIDATE

- **Tidak ada baru** dengan n≥20. spot-ofi-long sudah di-vETO sistem (n=49). conviction≥0.8 n=16 <20 → MONITOR saja.

## Verdict per Project

| Project | Status vs target 0.8%/30h | Bottleneck tunggal |
|---|---|---|
| SoDEX | 13/27 window pass; window berjalan FAIL -13% | Gate entry tidak konsumsi sinyal intel-BEARISH → kaskade SL LONG di tape turun |
| CEX | 0 kontribusi (signal mati by design) | Tidak ada jalur entry alpha-positif terverifikasi |
| SHORTBEAR | Stall | Reachability bug (dugaan), bukan pasar |

## Next Action Aman (urutan prioritas)

1. **Rekonsiliasi denominator** SODEX_TOTAL_WALLET (174.55 vs 279.74) — 5 menit, tanpa risiko, prasyarat evaluasi gate sah.
2. Selidiki stall SHORTBEAR (kenapa 0 trade 12 hari padahal UCB1 tertinggi + BEAR_MILD) — baca gate entry-nya, jangan ubah dulu.
3. Siapkan proposal (butuh approval + backtest): sinkronkan regime-gate realwide ke intel-layer (veto LONG saat intel<45 saat BEAR_MILD) — backtest dulu di 218 trade historis; jangan deploy tanpa persetujuan.
4. Tambah akuntansi wallet-ROI ke track CEX supaya kontribusi window terukur.
5. Monitor conviction-0.8 sampai n≥20; bersihkan kontaminan saham dari window planner scan.
