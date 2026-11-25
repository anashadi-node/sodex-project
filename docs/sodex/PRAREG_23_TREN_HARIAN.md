---
name: prereg-23-tren-harian
description: PRAREG-23 — pra-registrasi dibekukan untuk inti trend-following harian (long-only spot) + satelit carry. Dijalankan setelah disetujui Anas 09-Okt-2026.
metadata:
  type: project
---

# PRAREG-23 — INTI TREND-FOLLOWING HARIAN (LONG-ONLY SPOT) + SATELIT CARRY

**Status: DIBEKUKAN SEBELUM DATA DIEVALUASI.**
Protokol ini ditulis dan di-hash **sebelum** satu baris hasil backtest dilihat. Setelah hash
dibuat, **tidak ada ambang, aturan, atau universe yang boleh berubah.** Varian apa pun yang
kemudian dicoba **wajib** dicatat sebagai trial tambahan di `cex_trial_registry`.

- Tanggal beku: 09-Okt-2026
- Dasar: rekomendasi Claude `REKOMENDASI_HERMES_SODEX_2026-10-09.html` §4, §7 (H1), §5 (H2),
  disetujui Anas 09-Okt-2026 (termasuk substitusi universe).
- Ambang keputusan: **t ≥ 3,6** (N≈164 trial; jangan ada keputusan di t < 2,5).
- Target: tangga **0,10% lantai / 0,25% sasaran / 0,40% stretch per 48 jam** (disetujui
  Anas 09-Okt-2026); **0,8%/48 jam tetap arah jangka panjang.** PRAREG-23 **tidak** mengejar 0,8%.

---

## H1 — INTI: ENSEMBLE DONCHIAN HARIAN

### Universe (disetujui Anas 09-Okt-2026)
`BTC, ETH, SOL, BNB, LINK, XRP` — **substitusi** untuk XAUT & HYPE yang **tidak terdaftar di
Binance spot** (verifikasi API: `XAUTUSDT` & `HYPEUSDT` → tidak ada data).
Daftar pair **spot SoDEX** diverifikasi via API pada hari pertama; pair yang tidak ada di SoDEX
spot **dikeluarkan** dan dicatat (pengurangan universe diperbolehkan; penambahan tidak).

### Data
- Sinyal: **penutupan harian UTC dari Binance spot** (bukan SoDEX; riwayat SoDEX baru sejak Okt 2025).
- Berkas: `data/prereg23/{SYM}_1d.json` (fingerprint di `data/prereg23/MANIFEST.json`).
- **Pemisahan jendela WAJIB dilaporkan dua-duanya:**
  - **Jendela terverifikasi**: sampai **2025-10-09** (bar terakhir API Binance hidup; dicek 09-Okt-2026).
  - **Ekstensi**: 2025-10-10 → 2026-10-07 (dari berkas lokal; **tidak dapat diverifikasi** ke bursa hidup).
- Pemanasan 360 hari. Koin masuk portofolio hanya setelah punya ≥360 hari riwayat.
- Koin masuk/keluar saat data tersedia — **tidak ada** penambahan/pengurangan diskresi.

### Sinyal (satu konfigurasi saja — tanpa tuning)
Untuk setiap `L ∈ {5, 10, 20, 30, 60, 90, 150, 250, 360}` hari:

1. **Masuk** bila `close[t] > max(close[t-L .. t-1])`.
2. **Keluar** bila `close[t] < stop[t]`, dengan
   `stop[t] = max(stop[t-1], (max(close[t-L .. t]) + min(close[t-L .. t])) / 2)`.
   `stop` di-set saat masuk dan hanya boleh **naik** (ratchet) selama posisi terbuka.

### Ensemble & ukuran
```
bobot_koin[t] = (jumlah window L yang sedang long / 9)
                × min(1, 0,25 / vol_tahunan_90h)
                ÷ jumlah_koin_eligible
```
- **Tanpa leverage.** Total bobot ≤ 100%. Sisanya **USDC**.
- `vol_tahunan_90h = std(ret harian 90 hari) × √365`.

### Eksekusi
- Sekali sehari, **00:05 UTC**, order **limit di sisi pasif**.
- **Rebalance hanya** bila `|bobot_target − bobot_nyata| > 20% × bobot_target` (kontrol biaya).
- Setelah setiap order beli: pastikan `order_id ≠ 0` dan order muncul di daftar order terbuka
  (ada bug penolakan senyap pada limit GTC BUY pasca-maintenance). Bila tidak →
  kirim ulang sebagai **limit IOC** pada ask + 5 bps.
- Batas kapasitas: satu order ≤ **1%** kedalaman ±2% pair itu.

### Biaya
- **Utama: 25 bps per sisi** (≈ 4× tarif maker nyata — sengaja konservatif).
- **Sekunder: 10 bps per sisi.**
- Hasil **wajib** dilaporkan pada kedua tingkat. Lolos/gagal dinilai pada **25 bps**.

### Pembanding
1. **BTC buy-and-hold** (benchmark utama).
2. **EW buy-and-hold** universe yang sama (**dicatat**: koin yang masih hidup hari ini →
   bias survivorship; angka ini optimistis).

### Kriteria LOLOS — semua wajib terpenuhi
| # | Kriteria |
|---|---|
| a | Sharpe neto **≥ Sharpe BTC buy-and-hold** |
| b | Drawdown maksimum **≤ 50% ×** drawdown maksimum BTC |
| c | Neto positif di **≥ 2 dari 3** sub-periode (2019–2021, 2022–2023, 2024–2026) |
| d | Setelah membuang **5% hari terbaik**, Sharpe neto masih **> 0,5** |
| e | Selisih Sharpe vs BTC: **p < 0,05**, bootstrap blok **20 hari** |

**GAGAL bila salah satu tidak terpenuhi.** Tidak ada pelonggaran, tidak ada "hampir lolos".

### Bila H1 GAGAL
Tidak ada trading aktif. Pilihan (keputusan Anas, bukan Hermes): tetap USDC, atau posisi pasif
BTC/ETH sesuai toleransi risiko.

---

## H2 — SATELIT: FUNDING CARRY DELTA-NETRAL (maks 20% modal)

- Data: dump kolektor **funding SoDEX** + harga spot/perp SoDEX per jam.
- Simulasi aturan masuk/keluar (rekomendasi §5); biaya **9,4 bps (semua maker)** dan
  **21 bps (semua taker)** per siklus 4 sisi; jendela evaluasi 5 hari.
- **Lolos bila:** funding neto setelah biaya **positif di ≥70% jendela** · rata-rata tahunan
  neto **≥5%** · gerak basis merugikan terbesar **<1%**.
- Bila **jendela independen < 20** → hasil **TIDAK KONKLUSIF** dan satelit **tidak aktif**.
- Batas: ≤20% modal · leverage perp ≤2× · margin cadangan ≥50% di atas maintenance ·
  satu pair ≤50% satelit. **Hanya** pair yang punya spot **dan** perp di SoDEX.
- **mv_funding (Binance × dYdX) BUKAN bukti untuk SoDEX** — venue berbeda; t = 1,46, tidak lolos.

---

## YANG DILARANG SELAMA PRAREG-23 BERJALAN
1. Menambah filter, indikator, atau fitur ke lane apa pun.
2. Mengubah ambang/aturan **setelah** melihat hasil.
3. Override manual pada gerbang keselamatan.
4. Memakai leverage pada inti; menaikkan ukuran setelah kerugian.
5. Menghitung hadiah farming/SoPoints/rebate sebagai laba.
6. Mengklaim "berhasil" pada **n < 20** jendela independen atau **t < 3,6**.

## PENGECUALIAN yang dinyatakan terbuka (bias yang tidak dapat dihilangkan)
- Universe dipilih **hari ini** → bias survivorship. Mitigasi: benchmark BTC (tidak tunduk
  bias koin) dan pelaporan terpisah tanpa koin terbaik.
- Satu tahun terakhir data **tidak terverifikasi** ke bursa hidup → dilaporkan terpisah.
- Aturan diambil dari abstrak makalah publik (Zarattini–Pagani–Barbon 2025) → ada pemilihan
  rule-set dari luar; **tidak** di-tuning di dalam proyek.
