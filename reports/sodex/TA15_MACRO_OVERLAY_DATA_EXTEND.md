# TA15 — Overlay Rezim BTC pada Panel Diperluas + Koreksi Sumber Rezim (PRAREG-15)

**Tanggal:** 2026-10-08 · **Prareg:** `reports/sodex/PRAREG15_MACRO_OVERLAY_DATA_EXTEND_PROTOCOL.json` (commit `7c59241`, terbeku sebelum backfill & evaluasi)
**Hasil:** **0/18 lolos gerbang penuh · R1 5/9 · keluarga fade H48 (4 prareg) = 0 lolos kumulatif**

## Yang berubah (keduanya dideklarasikan SEBELUM hasil)

1. **Tambah data.** Panel Binance 1h: 9.648 → **24.276 bar** (2024-01-01 → 2026-10-08, 0 gap). Sebaran rezim: BULL 9.096 / CHOP 7.716 / BEAR 7.440 bar → est n window **189 / 160 / 155** (semua ≥ 90 → kanal segmen terbuka di Binance). Skrip: `scripts/research/binance_backfill_klines_1h.py` (54/54 simbol merged, 0 gagal; universe tetap; puller beku tak disentuh).
2. **Koreksi bug sumber kolom rezim (deklarasi terbuka).** TA13/TA14 memakai fallback `px.columns[0]` yang di venue SoDEX = **1000BONK-USD** (format kolom `{SYM}-USD`; `BTCUSDT` tak pernah cocok). Kini: `BTCUSDT` → else `BTC-USD` → else fallback. Bukti bar murni: SoDEX TA14 1.272/1.427/3.432 bar = rezim BONK 257 hari; TA15 dengan BTC-USD = 2.334/2.750/3.466 bar. Hasil TA13/TA14 tetap sah historis-deskriptif (0/18, tanpa keputusan).

**Tidak diubah:** ARM_MAP (hold 48), N_MIN=40, BH q=0,10, EMA10/30, fee, kontrol shuffle, mesin `run_mech` (SEG_MIN=30, seed 20261007), no-lookahead shift(1), tanpa trim warmup EMA.

## Temuan kunci

1. **Near-miss lama MATI karena substansi, bukan lagi struktur.** `MACD_FADE_H48|BEAR|binance`: n 77 → **151** (segmen kini terhitung = 2/3), tetapi **net −3,38 bps**, t=−0,29, p=0,77, |t_ctrl|=5,18. Edge PRAREG-14 tidak bertahan pada data diperluas → **fluke in-sample**. Ini falsifikasi tepat sasaran: kanal segmen dibuka lewat data, dan sel itu gagal karena angkanya.
2. **Satu lead tersisa (hanya bisa diuji forward).** `MACD_FADE_H48|BULL|sodex`: n=49, net **+39,97 bps**, t=9,61, p<0,0001, |t_ctrl|=0,95, S_ann=4,59, S_fee2x=4,00 — lolos SEMUA gerbang kecuali **seg (struktural: n<90 = plafon umur venue)**. Binance BULL menolak konfirmasi (IC berlawanan tanda → R1 gagal) → tidak terkonfirmasi lintas-venue.
3. `BB_POS_H48|BULL|sodex`: lolos kecuali |t_ctrl|≥2,0 (ctrl_t −6,89) → indikasi drift BULL, bukan edge fade.
4. R1 lintas-venue **5/9** (TA14: 8/9) — turun karena label rezim SoDEX kini BTC asli (dulu membandingkan BONK-regime vs BTC-regime). Perbandingan kini jujur.

## Tabel 18 sel

| sel | n | net bps | to | t | \|t_ctrl\| | S_ann | S_f2x | seg | BH | gerbang gagal |
|---|---|---|---|---|---|---|---|---|---|---|
| MACD_FADE_H48\|BULL\|sodex | 49 | 39,97 | 1,29 | 9,61 | 0,95 | 4,59 | 4,00 | - | Y | seg+<3 (struktural) |
| MACD_FADE_H48\|BULL\|binance | 190 | −23,13 | 1,32 | −2,50 | 1,33 | −1,48 | −1,91 | 0 | Y | gross/net≤0; S<2,3; seg |
| MACD_FADE_H48\|CHOP\|sodex | 46 | 20,82 | 1,26 | 1,83 | 3,74 | 2,21 | 1,67 | - | F | t; \|t_ctrl\|; BH; S_f2x; seg |
| MACD_FADE_H48\|CHOP\|binance | 163 | −10,66 | 1,34 | −1,08 | 0,83 | −1,06 | −1,72 | 1 | F | gross/net≤0; S; seg |
| **MACD_FADE_H48\|BEAR\|sodex** | 52 | 17,10 | 1,37 | 1,04 | 0,05 | 1,68 | 1,14 | - | F | t; BH; S<2,3; seg |
| **MACD_FADE_H48\|BEAR\|binance** | 151 | **−3,38** | 1,35 | −0,29 | **5,18** | −0,32 | −0,95 | 2 | F | net≤0; t; \|t_ctrl\|; BH; S; seg |
| KONFL_FADE_H48\|BULL\|sodex | 49 | 17,86 | 1,34 | 1,64 | 1,67 | 2,36 | 1,65 | - | F | t; BH; S_f2x; seg |
| KONFL_FADE_H48\|BULL\|binance | 190 | −29,27 | 1,33 | −3,25 | 1,26 | −2,35 | −2,88 | 0 | Y | gross/net≤0; S; seg |
| KONFL_FADE_H48\|CHOP\|sodex | 46 | −2,29 | 1,34 | −0,26 | 0,79 | −0,26 | −0,87 | - | F | net≤0; t; BH; S; seg |
| KONFL_FADE_H48\|CHOP\|binance | 163 | −7,24 | 1,37 | −0,97 | 1,66 | −0,86 | −1,67 | 1 | F | gross/net≤0; t; BH; S; seg |
| KONFL_FADE_H48\|BEAR\|sodex | 52 | 20,24 | 1,39 | 3,52 | 2,99 | 2,35 | 1,71 | - | Y | \|t_ctrl\|≥2,0; S_f2x; seg |
| KONFL_FADE_H48\|BEAR\|binance | 151 | −6,11 | 1,35 | −0,97 | 2,10 | −0,72 | −1,52 | 2 | F | net≤0; \|t_ctrl\|; t; BH; S; seg |
| BB_POS_H48\|BULL\|sodex | 49 | 23,01 | 1,30 | 8,07 | 6,89 | 3,31 | 2,56 | - | Y | \|t_ctrl\|≥2,0; seg |
| BB_POS_H48\|BULL\|binance | 190 | −24,80 | 1,31 | −2,71 | 0,45 | −1,97 | −2,48 | 0 | Y | gross/net≤0; S; seg |
| BB_POS_H48\|CHOP\|sodex | 46 | −22,73 | 1,30 | −2,46 | 0,73 | −3,35 | −4,10 | - | Y | gross/net≤0; S; seg |
| BB_POS_H48\|CHOP\|binance | 163 | −10,15 | 1,31 | −0,78 | 1,83 | −1,34 | −2,21 | 1 | F | gross/net≤0; t; BH; S; seg |
| BB_POS_H48\|BEAR\|sodex | 52 | 13,92 | 1,34 | 2,66 | 1,17 | 1,91 | 1,18 | - | Y | S<2,3; S_f2x; seg |
| BB_POS_H48\|BEAR\|binance | 151 | 2,77 | 1,32 | 0,33 | 0,50 | 0,32 | −0,45 | 2 | F | t; BH; S; seg |

Catatan: `gross/net≤0` + `S<2,3` + `seg` pada semua sel BULL/CHOP binance menandakan arah fade pada venue Binance justru negatif di regime naik/sideways (uncond MACD_FADE binance net = −13,27 bps, n=504).

## Keputusan (sesuai kriteria prareg)

0 lolos → keluarga fade H48 (4 prareg: 12/13/14/15; kumulatif 0 lolos penuh) **ditutup** atau diputuskan Mas Anas. Opsi yang tersaji:

- **A-selesai** — tutup keluarga fade H48 secara resmi; catat verdict 0 lolos.
- **B** — forward paper PRAREG-16 untuk lead `MACD_FADE_H48|BULL|sodex` (un-certifiable historis karena umur venue; verdict mesin hanya sah dari data forward). Perlu keputusan Mas Anas (target 0,8% & HARD_STOP 20 Nov).
- **C** — pivot ke sumber edge baru: Pilar 2 (TA7/TA10) & Pilar 3 (TA11) tutup; keluarga fade tutup → portofolio mesin SoDEX butuh kandidat dari jalur lain.

**Sifat hasil: DESKRIPTIF historis. Lulus gerbang hanya menandai kandidat forward, bukan verdict mesin. Target 0,8%/48 jam tidak berubah.**
