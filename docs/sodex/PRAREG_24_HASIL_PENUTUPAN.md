# PRAREG-24 — VARIAN EKSPOSUR: HASIL & PENUTUPAN

**Vonis: GAGAL — keempat varian.** Dieksekusi 09-Okt-2026 setelah protokol di-hash
(`sha256 b1adfbbb947d4c41…`, 68 baris, `reports/sodex/PRAREG24_BEKU.json`). Tidak ada ambang diubah.
Sinyal **identik** PRAREG-23 (kode `series_for` yang sama diimpor, bukan disalin).

## Uji konsistensi internal — LOLOS
V0 (baseline) mereproduksi PRAREG-23 H1 **tepat**: Sharpe **+1,47**, **0,0738%/48 jam**, eksposur 0,107.
Artinya mesin perbandingan sahih dan perbedaan antarvariant benar-benar berasal dari **sizing**.

## Hasil — jendela terverifikasi (≤ 2025-10-09), biaya 25 bps/sisi

| Varian | Sharpe | Return total | maxDD | Eksposur | Blok 20h positif | **%/48 jam** | p vs BTC | Gerbang |
|---|---|---|---|---|---|---|---|---|
| **BTC B&H** | +0.95 | +2861% | -83.2% | 1,00 | — | — | — | — |
| V0 — baseline (= PRAREG-23 H1, ÷N, vt 25%) | +1.47 | +199.9% | -12.2% | 0.107 | 42% | **+0.0738%** | 0.0815 | **GAGAL** |
| V1 — tanpa pembagi N, vt 25% | +1.40 | +4,924.3% | -50.2% | 0.480 | 43% | **+0.2636%** | 0.1080 | **GAGAL** |
| V2 — ÷N, vol-target 50% | +1.45 | +679.2% | -22.6% | 0.205 | 42% | **+0.1381%** | 0.0720 | **GAGAL** |
| V3 — tanpa pembagi N, vol-target 50% | +1.26 | +6,353.1% | -63.5% | 0.624 | 45% | **+0.2804%** | 0.1840 | **GAGAL** |

Sub-periode & kriteria per varian (25 bps, terverifikasi):

| Varian | a Sharpe≥BTC | b maxDD≤50%BTC | c ≥2/3 subperiode | d blok≥60% & median>0 | e p<0,0167 | f ≥0,10%/48j | g eksp≥0,30 |
|---|---|---|---|---|---|---|---|
| V0_baseline_H1 | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| V1_tanpa_pembagi_N | ✅ | ❌ | ✅ | ❌ | ❌ | ✅ | ✅ |
| V2_voltarget_50 | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |
| V3_gabungan | ✅ | ❌ | ✅ | ❌ | ❌ | ✅ | ✅ |

## Temuan utama — penyumbat SUDAH BERPINDAH

1. **Eksposur BUKAN lagi penyumbat.** Tiga varian **melewati lantai 0,10%/48 jam**:
   V2 **0.1381%** (maxDD hanya -22.6%),
   V1 **0.2636%**, V3 **0.2804%**
   — bahkan **di atas "sasaran" 0,25%** tangga Anda.
   Diagnosis PRAREG-23 ("sizing penyumbat") **terbukti benar dan sudah diperbaiki**.
2. **Penyumbat baru = BUKTI STATISTIK, bukan eksposur.** Menaikkan eksposur menaikkan return **dan**
   risiko secara proporsional: Sharpe hampir tidak berubah (1,47 → 1,40/1,45/1,26), maxDD memburuk
   (−12% → −50%/−23%/−64%), dan **p-value justru MEMBURUK** (0,0815 → 0,108/0,072/0,184).
   Dengan aturan **p < 0,0167** dan **t ≥ 3,6**, tidak satu pun layak deploy.
3. **Hanya ~42–45% blok 20-hari yang positif.** Kurang dari separuh waktu strategi ini untung —
   konsekuensi ekor yang sama dengan H1. Kriteria (d) gagal untuk **semua** varian.
4. **Emas vs risiko ada menunya, tapi tanpa bukti:** V2 memberi 0,1381%/48j pada maxDD −22,6%;
   V3 memberi 0,2804%/48j pada maxDD −63,5%. Keduanya **tidak terbukti** secara statistik.
5. **Ekstensi (tidak terverifikasi) melemah lagi:** Sharpe V0 1,47→1.29,
   V3 1,26→1.08; %/48j semua turun ~15–20%.
   Konsisten dengan peluruhan edge trend-following pasca-2021.

## Diagnostik berikutnya (BUKAN dijalankan tanpa persetujuan Anda)

Karena penyumbatnya kini **daya statistik**, satu-satunya arah yang sah adalah **menambah jumlah taruhan
independen**, bukan menambah risiko per taruhan:
- **Perluas universe** dari 6 → 20–50 koin likuid (rotasi), seperti konstruksi makalah aslinya.
  Lebih banyak taruhan independen = **daya statistik naik** tanpa menaikkan eksposur per koin.
- Alternatif: **triwulan/harian-bloc** yang lebih banyak, atau horizon lebih panjang (hitungan lebih sedikit).
- **Yang TIDAK boleh:** melonggarkan (e)/(d), atau memilih varian terbaik setelah melihat hasil.

## Disiplin yang dipegang
- Protokol di-hash sebelum eksekusi; V0 mengunci kesahihan perbandingan.
- Tidak ada ambang yang dilonggarkan; (d) diganti **dengan pengungkapan risiko goalpost-moving terbuka**,
  dan (e) justru **diperketat** ke Bonferroni 0,0167.
- **Tidak ada order, tidak ada flag live, tidak ada posisi.**
