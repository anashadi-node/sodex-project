# PRAREG-29 — HASIL PENUTUPAN: Ladder Turnover Momentum Cross-Sectional

**Tanggal:** 22-Okt-2026 · **Hash protokol:** `a5a6041d8e10cce6…` (dibekukan 02:22Z, sebelum skrip ditulis)
**Status:** **Keluarga momentum cross-sectional DITUTUP** (aturan penutupan pra-registrasi §5 terpicu).

## 1. Hasil (BEKU, ketiga varian, ketiga tingkat biaya)

| Varian | Biaya | Sharpe | CAGR | %/48 jam | maxDD | Turnover | ex-top3 %/48j |
|---|---|---|---|---|---|---|---|
| **R=7 (primer)** | 25bps | +0,541 | +12,1% | **+0,0628%** | −43,1% | 48,3× | +0,0479% |
| R=7 | 10bps | +0,793 | +20,6% | +0,1026% | −30,2% | 48,3× | +0,0828% |
| R=7 | 0bps | +0,962 | +26,6% | **+0,1292%** | −25,9% | 48,3× | **+0,1061%** |
| R=3 | 25bps | +0,356 | +6,4% | +0,0338% | −49,2% | 75,7× | −0,0427% |
| R=14 | 25bps | +0,509 | +10,8% | +0,0563% | −49,3% | 34,5× | +0,0465% |

Gerbang lolos/gagal @25bps: **ketiganya GAGAL** — b (maxDD), d (blok), e (p), f (lantai), g (DSR), h (robustness), i (turnover). Sub-periode R=7: 2019-21 **+0,82**, 2022-23 −0,03, 2024-26 **+0,66** → 2/3 positif (gerbang c lolos).

p-value: R=7 **0,0549** · R=3 0,204 · R=14 0,0944 — terhadap α Bonferroni **3,70e-4**. DSR: 0,138 / 0,053 / 0,121 vs syarat 0,95.

## 2. Yang sebenarnya ditemukan (ini bagian pentingnya)

**Q1 — apakah edge bertahan setelah turnover diturunkan? SEBAGIAN ya, tapi tidak cukup.**
Turnover turun 137× → **48,3×/tahun** (R=7), dan Sharpe 25bps naik dari **+0,05 → +0,54**. Beban biaya turun dari 34%/tahun ke 12%/tahun. Jadi diagnosis PRAREG-28 benar: **biaya adalah pembunuh utama, bukan sinyalnya.** Tapi setelah biaya diturunkan pun, hasil neto **+0,063%/48j** masih **di bawah lantai tangga 0,10%**.

**Q2 — apakah edge-nya lebar atau artefak 1–3 nama? LEBIH LEBAR DARI DUGAAN, tapi sangat tipis.**
Ini koreksi penting terhadap framing PRAREG-28. Pada **0bps**, tanpa 3 kontributor teratas, R=7 masih memberi **+0,106%/48j (Sharpe +0,81, total +384%)**. Artinya: **ada edge lintas-sectional yang nyata dan tidak bergantung pada LUNA/XRP/ADA** — berbeda dari kesimpulan awal saya yang terlalu keras menyebut "artefak LUNA". Buktinya juga: kontributor teratas **berganti** antar varian (R=7: BTC/ADA/XLM; R=3: LUNA/XRP/ADA; R=14: ALGO/ETC/RUNE) — pola khas edge sebaran, bukan satu peristiwa.

**Tapi besarnya hanya ≈0,13%/48 jam kotor (≈0,11% tanpa 3 nama terbaik) — sekitar 1/6 dari target 0,8%, dan separuhnya habis oleh biaya realistis.**

## 3. Akar masalah yang tersisa (bukan biaya lagi)

Setelah biaya ditekan, penghalang berikutnya adalah **risiko, bukan return**:

| | R=7 @25bps | Syarat |
|---|---|---|
| %/48 jam | 0,063% | ≥0,10% |
| maxDD | **−43,1%** | ≤20% |
| Blok 20-hari positif | 44,6% | ≥60% |
| p-value | 0,055 | <3,7e-4 |

Rasio return/risiko: **0,063% per 48 jam dengan drawdown 43%** = untuk mendapat 0,8% Anda harus menanggung drawdown ~550%. Itu bukan instrumen investasi, itu opsi lotre. **Inilah alasan sesungguhnya keluarga ini ditutup** — bukan karena sinyalnya nol, tapi karena geometri risikonya tidak bisa dipakai pada skala yang dibutuhkan.

## 4. Pelajaran metodologis (dicatat jujur)

1. **Turnover ≠ 1/R.** Perkiraan apriori saya 19,6× untuk R=7; aktual **48,3×**. Penyebab: (a) bobot mengambang antar rebalance lalu dinormalisasi ulang ke equal-weight — normalisasi itu sendiri menghasilkan turnover; (b) universe berganti tiap bulan; (c) nama keluar/masuk leg. Pelajaran: perkiraan turnover dari aritmetika sederhana **underestimate 2,5×**; ke depan, turnover harus diukur dari simulasi, bukan diasumsikan.
2. **B=2.000 terlalu kasar untuk α Bonferroni.** PRAREG-28 memakai B=2.000 (resolusi 5e-4) sementara α=3,7e-4 — p tidak akan pernah bisa di bawah α. PRAREG-29 memakai B=20.000 (resolusi 5e-5). Diperbaiki.
3. **Uji ex-top3 harus jadi gerbang, bukan catatan.** Sudah diterapkan di PRAREG-29 dan langsung mengubah gambaran (Q2 terjawab "lebar tapi tipis", bukan "artefak").

## 5. Verdict & konsekuensi

**Keluarga momentum cross-sectional DITUTUP** sesuai aturan pra-registrasi: gerbang h gagal di ketiga varian (25bps). Tidak ada varian R lain, tidak ada ubah K, tidak ada ubah band. Aturan ini dipatuhi **persis seperti tertulis**, meskipun R=7 adalah hasil struktural terbaik yang pernah dicapai program ini (Sharpe 0,96 kotor, 2/3 sub-periode positif, tahan uji ex-top3).

**Untuk target 0,8%:** jalur ini memberi **maksimum ≈0,13%/48 jam kotor**. Jarak ke 0,8% = **6,2×**. Tidak ada parameter yang bisa menutup jarak 6× tanpa menaikkan risiko ke tingkat yang sudah ditolak V2 §9.

**Implikasi untuk proyek:** sekarang **dua keluarga mekanisme** sudah diuji tuntas dan ditutup:
1. Trend-following long-only (PRAREG-23/24/25) — habis, 0 dari 21 mesin.
2. Momentum cross-sectional long/short (PRAREG-28/29) — edge nyata tapi 6× terlalu kecil dan drawdown 2× terlalu besar.

Keluarga yang **belum** diuji tetap seperti rekomendasi PRAREG-25 §9: mean-reversion berbasis likuidasi/OI, dan basis/carry lintas-venue. Keduanya membutuhkan data yang belum dimiliki (likuidasi/OI historis; dua venue paralel) — jadi tidak bisa dimulai tanpa akuisisi data lebih dulu.

*PRAREG-29 selesai 22-Okt-2026 · 3 trial dicatat di registry (132→135) · tidak ada kode produksi/eksekusi disentuh · arm A/B tidak berubah*
