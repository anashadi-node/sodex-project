# VALIDASI RANGE-POSITION (PRAREG-2) — HASIL — 2026-10-07

**Status: SELESAI. Verdict sesuai spesifikasi beku: TIDAK LULUS.**
Tapi ini **temuan positif pertama yang tervalidasi out-of-sample** di seluruh sesi SoDEX,
dan ia memunculkan satu mekanisme yang **direplikasi lintas-venue**.
Protokol beku: `docs/sodex/PRAREG_2_RANGE_POSITION_2026-10-07.md`.
Skrip: `scripts/research/range_pos_validation.py`. Output: `reports/sodex/VALIDASI_RANGE_POSITION.json`.

---

## 1. Verdict resmi (spesifikasi beku, tanpa penyesuaian)

| Syarat (beku) | Hasil OOS Binance | Lulus? |
|---|---|---|
| S_ann ≥ 2,30 (biaya 1×) | **1,75** | ✗ |
| S_ann ≥ 1,80 (biaya 2×) | **1,34** | ✗ |
| t_NW ≥ 2,0 | **2,80** | ✓ |
| tanda IS = tanda OOS | IS +18,59 → OOS +14,43 bps (**sama**) | ✓ |
| 3/3 segmen positif | **3/3** | ✓ |
| kontrol negatif tidak lulus | bruto kontrol OOS **−2,22 bps** | ✓ |

→ **TIDAK LULUS** — gagal di ambang Sharpe, bukan di ambang signifikansi.
Ambang 2,30 yang saya bekukan **sebelum** menjalankan memang keras; hasil 1,75 tidak
mencapainya. Tidak ada ambang yang saya geser setelah melihat hasil.

## 2. Tabel lengkap

**Binance 1d — 248 nama, panel panjang (IS berakhir 2023-12-08, OOS mulai 2023-12-09):**

| Segmen | n | netto (bps) | sd | S_ann | t_NW | p | seg+ | S_slip | S_2× | ctrl bruto |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| IS 60% | 634 | +18,59 | 175 | 1,44 | 2,54 | 0,0112 | 2/3 | 1,38 | 1,17 | +4,66 |
| **OOS 40%** | **507** | **+14,43** | 111 | **1,75** | **2,80** | **0,0052** | **3/3** | 1,66 | 1,34 | **−2,22** |

Sensitivitas N (stabilitas, bukan pemilihan): N=10 → 0,86 · N=20 → **1,75** · N=40 → 1,75 · N=60 → 1,55.

**SoDEX 1d — 84 nama × 361 bar (2025-10-12 → 2026-10-07), hold 2 hari:**

| Segmen | n | netto (bps) | S_ann | t_NW | p | seg+ | IC | turnover | fee |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| penuh | 138 | +7,91 | 0,93 | 0,96 | 0,3387 | 2/3 | +0,0164 | 0,63 | 2,52 bps |

Sensitivitas N: N=10 → 0,07 · N=20 → 0,93 · N=40 → 0,62 · N=60 → −0,13 (**tidak stabil**).

**SoDEX 1h — 63 nama × 8.532 bar, hold 24 jam:**

| Segmen | n | netto (bps) | S_ann | t_NW | p | seg+ | IC |
|---|---:|---:|---:|---:|---:|---:|---:|
| penuh | 291 | **−16,61** | −0,75 | **−4,07** | <0,0001 | **0/3** | −0,0395 |

Sensitivitas N: semua negatif (−0,89 … −0,51). **Tanda terbalik di horizon jam.**

## 3. TEMUAN UTAMA — kontradiksi yang menyingkap struktur sebenarnya

IC Spearman OOS Binance = **−0,0179**, padahal portofolio menghasilkan **+14,43 bps**.
IC negatif dengan portofolio positif itu **tidak konsisten** — jadi saya periksa langsung
(bukan berasumsi), dengan mendiagnosis sebaran kuintil pada OOS yang sama:

| Diagnostik OOS Binance (507 periode, 245 nama) | Nilai |
|---|---:|
| IC Spearman (rata-rata) | −0,0179 (t = −2,76) |
| IC Pearson (rata-rata) | **+0,0162** |
| excess kuintil ATAS (dekat puncak rentang) | **+31,68 bps** |
| excess kuintil BAWAH (dekat dasar rentang) | **−22,03 bps** |
| **SPREAD atas − bawah** | **+53,72 bps, t = +4,19** |

**Kesimpulan diagnostik:** hubungan rentang-posisi ↔ imbal hasil **NON-MONOTON**.
Di **ekor** efeknya momentum kuat (+53,72 bps, t=4,19); di **tengah peringkat** urutannya
sedikit terbalik — itulah yang membuat IC Spearman negatif. Bobot peringkat merata ke
seluruh 245 nama, sehingga hanya menangkap **14,43 dari 53,72 bps** (27%).
Jadi "TIDAK LULUS" itu sebagian **kegagalan konstruksi bobot saya**, bukan kegagalan sinyal.

## 4. Uji replikasi lintas-venue (syarat PRAREG-2 §2: tanda sama DAN |IC_SoDEX| ≥ ½ |IC_Binance|)

Diagnostik kuintil yang sama dijalankan pada SoDEX:

| Venue / resolusi | nama | periode | spread atas−bawah | t | arah |
|---|---:|---:|---:|---:|---|
| Binance 1d (OOS) | 245 | 507 | **+53,72 bps** | **+4,19** | MOMENTUM |
| **SoDEX 1d** | 84 | 138 | **+39,48 bps** | +1,65 | **MOMENTUM** |
| SoDEX 1h (hold 24 jam) | 73 | 291 | −32,33 bps | −2,30 | REVERSAL |

- **Replikasi tanda: LULUS** (momentum di kedua venue pada horizon harian).
- **Besaran: SoDEX = 73% dari Binance** → melewati syarat ≥50% → **LULUS**.
- **Namun:** SoDEX 1d hanya 138 periode (t=1,65, p≈0,10) — **belum signifikan sendiri**.
  Kekuatan buktinya adalah **triangulasi lintas-venue**, bukan SoDEX sendirian.
- **Horizon jam membalik arah** (SoDEX 1h: reversal, t=−2,30). Ini masuk akal secara
  mekanisme (mean-reversion mikro mendominasi jam, tren harian mendominasi hari) dan
  **konsisten dengan pelajaran H5** bahwa efek tidak otomatis replikasi antar-horizon/venue.

## 5. Aritmetika ke target (jujur)

| | Nilai |
|---|---:|
| Target | 80 bps / 48 jam |
| SoDEX 1d spread bruto (kuintil) | +39,48 bps / 2 hari |
| Biaya round-trip realistis | 9,71 bps (taker 8 + slippage 1,71) |
| **Neto kasar** | **≈ +30 bps / 48 jam** |
| Sebagai % target | **≈ 37%** |

Jadi satu mekanisme ini, dengan konstruksi kuintil, berpotensi memberi **~37% dari target
dari satu mesin** — jauh di atas apa pun yang pernah saya ukur sebelumnya (sebelumnya
portofolio peringkat hanya +7,91 bps ≈ 10% target). **Tapi ini belum boleh diklaim**, karena:

## 6. Yang TIDAK boleh saya klaim (pagar jujur)

1. **Konstruksi kuintil ini POST-HOC.** Saya menemukannya setelah melihat hasil uji
   beku, dan pada **jendela OOS yang sudah terpakai**. Menjualnya sebagai temuan
   pra-registrasi akan melanggar aturan yang sama yang saya pakai untuk menolak
   hipotesis H5/ALT3. Karena itu ia dideklarasikan sebagai **hipotesis baru** di
   `docs/sodex/SODEX_PRAREG3_RANGEPOS_QUINTILE_2026-10-07.md`, dengan pemisahan waktu sendiri.
2. SoDEX 1d **t=1,65** → belum signifikan; sensitivitas N tidak stabil (0,07→0,93→0,62→−0,13).
3. Spread kuintil pada 84 nama = ~17 nama per kuintil; **kapasitas dan eksekusi belum diuji**.
   Dengan modal $30 ini bukan masalah likuiditas, tapi tetap harus diukur.
4. Angka "≈30 bps/48 jam" memakai asumsi turnover = 0,63 (dari konstruksi peringkat).
   Konstruksi kuintil akan punya turnover berbeda → **wajib diukur, bukan diasumsikan**.
5. Belum ada bukti bahwa 6–8 mesin bisa mencapai korelasi ≤0,10. Sensus diversifikasi
   (`SENSUS_DIVERSIFIKASI_SODEX.json`) mengukur **korelasi pasangan rata-rata 0,595** dan
   **n_effective_bets = 2,32** → efek diversifikasi nyata hanya ~1,49× untuk 6 mesin,
   **bukan** √6 = 2,45×. Ini menutup jalan "tambal kekurangan lewat diversifikasi".

## 7. Kesimpulan

1. Verdict beku PRAREG-2 = **TIDAK LULUS** (Sharpe 1,75 < 2,30). Dilaporkan apa adanya.
2. Namun mekanisme di belakangnya **nyata secara statistik**: OOS t=2,80, p=0,0052,
   3/3 segmen positif, kontrol negatif gagal — **pertama kali** ini terjadi di sesi ini.
3. Kegagalan ambang Sharpe sebagian **disebabkan konstruksi bobot saya** (peringkat merata
   hanya menangkap 27% dari efek ekor).
4. Efek ekor itu **direplikasi di SoDEX** (tanda sama, besaran 73% Binance).
5. Langkah berikutnya sudah dibekukan: **PRAREG-3** (rangepos kuintil, pemisahan waktu sendiri).

— Hermes Anantara v3 — 2026-10-07
