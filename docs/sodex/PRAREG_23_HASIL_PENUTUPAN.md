# PRAREG-23 H1 — HASIL & PENUTUPAN

**Status: GAGAL pada gerbang beku. TIDAK live.**
Dieksekusi 09-Okt-2026 setelah protokol di-hash (`sha256 f4ba693bc1e89e36…`, 121 baris,
`reports/sodex/PRAREG23_BEKU.json`). Tidak ada ambang yang diubah setelah hasil dilihat.

## Hasil — jendela terverifikasi (≤ 2025-10-09)

| Metrik | Strategi | BTC buy-and-hold | EW buy-and-hold |
|---|---|---|---|
| Sharpe (biaya 25 bps) | **+1.47** | +0.94 | +1.25 |
| Sharpe (biaya 10 bps) | +1.53 | +0.94 | +1.25 |
| Return total | +199.9% | +2739.2% | +24415.3% |
| Drawdown maksimum | **-12.2%** | -83.2% | -82.9% |
| Eksposur rata-rata | **0.11** (≈89% USDC) | 1,00 | 1,00 |
| **Return per 48 jam** | **0.0738%** | — | — |
| CAGR | 14.4% | — | — |

Sub-periode (Sharpe 25 bps): 2019–2021 **+2.19** ·
2022–2023 **+0.71** · 2024–2026 **+1.49** → **3 dari 3 positif**.

## Gerbang (semua wajib) — HASIL

| # | Kriteria | Hasil | |
|---|---|---|---|
| a | Sharpe ≥ Sharpe BTC | 1.47 ≥ 0.94 | **LOLOS** |
| b | maxDD ≤ 50% × BTC | -12.2% ≥ -41.6% | **LOLOS** |
| c | Positif di ≥2 dari 3 sub-periode | 3/3 | **LOLOS** |
| d | Sharpe tanpa 5% hari terbaik > 0,5 | **-1.56** | **GAGAL** |
| e | Selisih Sharpe vs BTC p < 0,05 | **p = 0.0835** | **GAGAL** |

**VONIS: GAGAL → TIDAK ADA TRADING AKTIF.** Sesuai protokol; pilihan lanjut adalah keputusan Anas.

## Tiga hal yang harus dicatat apa adanya

1. **Kelas pertama yang tidak nol.** Dari sapuan sebelumnya (108 sel → baterai 0/36 · 24 sel PRAREG-19 → 0/24 ·
   21 mesin → 0 lolos · 57 simbol → 0 promosi), H1 adalah yang **pertama mengalahkan Sharpe BTC**,
   dengan **drawdown ~7× lebih dangkal**, dan **positif 3/3 sub-periode**. Hasilnya **0.0738%/48 jam** —
   **belum mencapai lantai 0,10%** (kurang **1.36×**).
2. **Klaim makalah TEREPLIKASI.** Paper (Zarattini–Pagani–Barbon 2025) mengklaim Sharpe >1,5; kita ukur
   **+1.47 net @25 bps** dan **+1.53 @10 bps** pada universe berbeda
   (6 koin, 2019–2026). Replikasi independen **berhasil**.
3. **Kedua kriteria yang gagal punya SEBAB yang sama: edge hidup di ekor.** Buang 5% hari terbaik → Sharpe
   menjadi **-1.56**. Laba strategi ini berasal dari segelintir hari besar —
   itu *definisi* trend-following. Konsekuensinya: dengan 6,5 tahun data kita **tidak dapat memisahkan**
   hasil ini dari keberuntungan (p = 0.0835), dan ambang keputusan program **t ≥ 3,6** masih jauh.

## Cacat desain yang DICATAT (bukan alasan mengubah protokol ini)

Kriteria (d) — "Sharpe tanpa 5% hari terbaik > 0,5" — **secara struktural hampir mustahil** untuk strategi
trend-following, karena kelas ini *didefinisikan* oleh ketergantungan pada sedikit pemenang besar.
Kriteria itu masuk akal untuk strategi mean-reverting, tetapi menghukum kelas ini berdasarkan sifatnya sendiri.

- **SAH:** catat sebagai pelajaran untuk **PRAREG-24**, dirumuskan & di-hash **sebelum** data berikutnya dilihat.
- **TIDAK SAH:** melonggarkan kriteria (d) sekarang, setelah melihat hasil — itu goalpost-moving,
  pola yang dilarang protokol ini sendiri.

## Jarak ke tangga yang Anda setujui

0.0738%/48 jam → lantai 0,10% = **1.36×** · sasaran 0,25% = **3.39×** ·
stretch 0,40% = **5.42×** · 0,8% = **10.84×**.

## Yang belum diuji

- **H2 (satelit carry SoDEX)** — belum dijalankan (butuh dump funding SoDEX).
- **Eksposur 0.11 mungkin terlalu konservatif.** Rumus ensemble (÷ jumlah koin) membuat
  portofolio 89% USDC. Varian tanpa pembagi N, atau vol-target lebih tinggi,
  **belum diuji** — dan setiap varian = **trial tambahan** yang menaikkan ambang t.
- **Ekstensi 2025-10-10 → 2026-10-07** (tidak terverifikasi ke bursa hidup): Sharpe
  1.29, sub-periode 2024–2026 turun ke 0.92 —
  arahnya **melemah**, konsisten dengan laporan peluruhan edge trend-following pasca-2021.
