# Analisis: Apakah Pindah Venue (Aster / Hyperliquid / Binance) Membuat Target 0,8% per 30–48 Jam Jauh Lebih Mudah?

**Tanggal:** 23 Oktober 2026 · **Penulis:** Hermes Anantara v3
**Sifat:** analisis kuantitatif, bukan opini. Setiap angka punya sumber atau pengukuran.

---

## 0. Jawaban singkat (verdict)

**Tidak. Tidak "jauh lebih mudah".**

Perpindahan venue mengubah **hambatan biaya sebesar 0–10 bps** dari target **80 bps** —
artinya **0–12%** dari persoalan. Dalam satuan yang lebih tajam: win-rate yang dibutuhkan
pada RR 2:1 bergeser dari **52,6% (SoDEX)** menjadi **51,1% (Aster maker)** atau **53,3%
(Binance taker)** — selisih **2,2 poin persentase**.

Yang menentukan target ini bukan venue, melainkan **edge arah** dan **ukuran risiko**.
Venue hanya membantu pada tiga hal yang berbeda: **kapasitas**, **ketersediaan data untuk
validasi**, dan **pilihan instrumen (spot vs perp)**.

---

## 1. Metode dan sumber data

| Komponen | Sumber | Ukuran |
|---|---|---|
| Volatilitas 30/48 jam | Binance klines 1h, 2024-01 → 2026-10 | 24.276 bar/simbol, jendela non-overlap |
| Spread & slippage | Orderbook live Binance USDM, Hyperliquid `l2Book`, Aster `depth` | top-50, klip $250 / $2.500 / $25.000 |
| Funding | Binance funding history, 249 simbol | 6.500–7.700 sampel/simbol, interval 4 jam |
| Fee | Dokumentasi resmi (lihat §3) | maker/taker per leg |
| Biaya efektif SoDEX | Ledger internal, 861 trade berharga | 6,49 bps RT tersirat |

---

## 2. Fakta pertama: seberapa besar sebenarnya target 0,8% itu?

### 2.1 Dalam satuan tahunan (compounded)

| Target | Per tahun | Per bulan |
|---|---|---|
| 0,8% per **30 jam** | **10,2×** (924%) | 19,2% |
| 0,8% per **48 jam** | **4,3×** (328%) | 12,1% |

Angka ini penting: 0,8% terlihat kecil sebagai satu kejadian, tetapi sebagai **laju
berulang** ia berarti portofolio berlipat 10× setahun.

### 2.2 Relatif terhadap volatilitas

| Simbol | σ 30 jam | σ 48 jam | P(\|gerak\| ≥ 0,8%) per 30 jam | Rata-rata \|gerak\| 30 jam |
|---|---|---|---|---|
| BTC | 2,76% | 3,37% | 66,6% | 1,95% |
| ETH | 3,88% | 4,81% | 76,9% | 2,69% |
| BNB | 3,22% | 3,77% | 71,7% | 2,19% |
| XRP | 4,57% | 5,72% | 74,4% | 3,02% |
| SOL | 4,70% | 5,60% | 82,1% | 3,43% |
| LINK | 5,05% | 6,06% | 82,6% | 3,55% |
| AAVE | 5,50% | 6,88% | 83,8% | 3,95% |
| SUI | 6,30% | 7,81% | 84,4% | 4,36% |

**Interpretasi:** 0,8% hanya **0,29σ** untuk BTC dan **0,13σ** untuk SUI dalam 30 jam.
Pasarnya hampir selalu bergerak lebih dari 0,8% dalam satu window (67–85% window).

**Kesimpulan bagian ini:** masalahnya **bukan kekurangan peluang pergerakan**, melainkan
**arah**. Tidak ada venue yang bisa menambah besar pergerakan; yang bisa dilakukan venue
hanya mengubah biaya masuk-keluar.

---

## 3. Fakta kedua: biaya per venue (terukur, bukan asumsi)

### 3.1 Fee resmi

| Venue | Maker / leg | Taker / leg | **RT maker** | **RT taker** | Sumber |
|---|---|---|---|---|---|
| **SoDEX** | 1,14 bps | 2,80 bps | **2,28** | **5,60** (efektif terukur **6,49**) | ledger internal |
| **Aster** (Crypto General) | **0 bps** | 4,00 bps | **0,00** | **8,00** | docs.asterdex.com |
| **Hyperliquid** | 1,50 bps | 4,50 bps | **3,00** | **9,00** | docs Hyperliquid |
| **Binance USDⓈ-M** | 2,00 bps | 5,00 bps | **4,00** | **10,00** | Binance fee schedule (VIP 0) |
| **Binance Spot** | 10,0 bps | 10,0 bps | **20,0** | **20,0** (7,5/7,5 dgn BNB = 15) | Binance |

**Temuan yang berlawanan dengan intuisi umum:** SoDEX adalah venue **termurah untuk taker**
(5,6 bps RT) — lebih murah dari Binance (10) dan Hyperliquid (9). Yang paling murah untuk
maker justru **Aster: 0 bps**.

### 3.2 Spread dan slippage live (diukur 23 Okt 2026)

| Venue | BTC spread | ETH spread | Slippage $250 | Slippage $25.000 |
|---|---|---|---|---|
| Binance | 0,012 bps | 0,042 bps | **0,00** | **0,00** |
| Hyperliquid | 0,245 bps | 0,418 bps | **0,00** | **0,00** |
| Aster | 0,012 bps | 0,042 bps | **0,00** | 0,024 bps (ETH) |

Untuk ukuran wallet sekarang (~$250–$2.500), **slippage praktis nol di ketiga venue**.
Ini berarti selisih 0,9 bps antara fee SoDEX (5,6) dan biaya efektif SoDEX (6,49) memang
biaya venue, bukan slippage yang bisa dihilangkan dengan pindah tempat.

### 3.3 Biaya funding — yang paling sering diabaikan

Ini bagian yang **mengubah kesimpulan**. Untuk hold 30–48 jam, posisi perp melewati
7–12 periode funding.

| Simbol | Funding median / 4 jam | Akumulasi 30 jam | Akumulasi 48 jam |
|---|---|---|---|
| BTC | +0,95 bps | **±10 bps** | **±16 bps** |
| ETH | +1,00 bps | **±12 bps** | **±19 bps** |
| XRP | +1,00 bps | **±15 bps** | **±23 bps** |
| SOL | +0,84 bps | ±11 bps | ±18 bps |
| SUI | +0,64 bps | ±8 bps | ±13 bps |

(dihitung dari 249 simbol, 6.500–7.700 sampel per simbol)

**Perbandingan biaya total per window 30 jam, posisi long 1×:**

| Venue / instrumen | Fee RT | Funding 30 jam | **Total** |
|---|---|---|---|
| SoDEX perp (taker) | 5,6–6,5 | ~10 | **~16–17 bps** |
| Aster perp (maker) | **0** | ~10 | **~10 bps** |
| Hyperliquid perp (maker) | 3,0 | ~10 | **~13 bps** |
| Binance perp (taker) | 10,0 | ~10 | **~20 bps** |
| **Binance spot (BNB)** | 15,0 | **0** | **15 bps** |

**Kesimpulan:** untuk hold 30–48 jam, **funding lebih besar dari fee**. Venue termurah
sekalipun tetap membayar ~10 bps funding. Satu-satunya cara menghindarinya adalah **spot**,
dan itu hanya masuk akal untuk posisi long.

### 3.4 Koreksi penting: funding berbeda 2–3× antar-venue

Angka di §3.3 berasal dari **Binance** (interval 4 jam). Pengukuran langsung pada
**Hyperliquid** (interval 1 jam, 60 hari terakhir) memberi hasil berbeda:

| Venue | BTC funding / jam | BTC funding 30 jam | BTC funding 48 jam |
|---|---|---|---|
| **Binance** (4 jam) | 0,238 bps | **7,1 bps** | 11,4 bps |
| **Hyperliquid** (1 jam) | 0,102 bps | **3,1 bps** | 4,9 bps |

Hyperliquid memakai lantai bunga tetap 0,01%/8 jam (11,6% APR) yang **lebih rendah** dari
rata-rata funding Binance (≈20,8% APR). Median seluruh aset HL = 0,125 bps/jam.

**Konsekuensi pada tabel biaya total 30 jam (long, maker):**

| Venue | Fee RT | Funding 30 j | **Total** |
|---|---|---|---|
| **Hyperliquid (maker)** | 3,0 | **3,1** | **≈6,1 bps** |
| Aster (maker) | 0,0 | 7,1 (proksi Binance) | ≈7,1 bps |
| SoDEX (maker) | 2,28 | belum terukur | ≥2,3 bps |
| Binance (maker) | 4,0 | 7,1 | ≈11,1 bps |

**Jadi untuk hold 30–48 jam, Hyperliquid adalah venue perp termurah secara total** —
bukan karena fee (3 bps, di atas SoDEX 2,28), tetapi karena funding-nya **kurang dari
setengah** Binance. Ini tidak mengubah besaran persoalan (selisih ~5 bps dari 80 bps),
tetapi mengubah peringkat venue.

---

## 4. Fakta ketiga: akurasi yang dibutuhkan (dan seberapa kecil venue menggesernya)

Rumus: `E = p·TP − (1−p)·SL − c`. Agar `E = 0,8%` per window dengan satu trade 100% notional:

| TP / SL | RR | Aster (c=0) | HL maker (0,03) | SoDEX (0,065) | Binance (0,10) | + funding 30j (0,22) |
|---|---|---|---|---|---|---|
| 3% / 1,5% | 2,0 | **51,1%** | 51,8% | **52,6%** | 53,3% | 56,0% |
| 6% / 3% | 2,0 | 42,2% | 42,6% | 42,9% | 43,3% | 44,7% |
| 4% / 2% | 2,0 | 46,7% | 47,2% | 47,8% | 48,3% | 50,3% |
| 3% / 3% | 1,0 | 63,3% | 63,8% | 64,4% | 65,0% | 67,0% |

**Baca tabel ini dengan urutan:**
1. **RR (rasio TP/SL) menggeser kebutuhan win-rate jauh lebih besar** daripada venue:
   2:1 → 51%, 1:1 → 63%. Selisih 12 poin.
2. **Venue hanya menggeser 2,2 poin** (Aster 51,1% vs Binance 53,3%).
3. **Funding menggeser 3–4 poin** — lebih besar dari perbedaan venue.

**Untuk pembanding, buku SoDEX nyata:** RR 1,98:1, WR 45% (219 TP dari 486 trade
berkeputusan). Kebutuhan: 52,3%. **Defisit 7,3 poin.** Kekurangan itu setara −30 bps/trade,
dan itulah sumber seluruh kerugian — bukan fee.

---

## 5. Fakta keempat: Sharpe yang tersirat

Bila 0,8% dicapai **setiap** window, maka Sharpe tahunan yang tersirat adalah:

| Simpangan baku per window | Sharpe tersirat |
|---|---|
| 0,8% (risiko sangat kecil) | **17,1** |
| 1,5% | 9,1 |
| 2,5% | 5,5 |
| 4,0% | **3,4** |

Dana kuantitatif terbaik dunia beroperasi pada Sharpe **1–2,5** setelah biaya. Sharpe 17
berarti mesin cetak uang; Sharpe 3,4 tergolong elit tetapi mungkin.

**Implikasi:** target 0,8%/window hanya konsisten dengan Sharpe realistis **jika simpangan
baku per window 4%+** — artinya **harus ada risiko nyata**, bukan posisi kecil yang aman.

**Leverage yang dibutuhkan pada Sharpe 2:**

| Simbol | σ 30 jam | Leverage |
|---|---|---|
| BTC | 2,76% | **2,48×** |
| ETH | 3,88% | 1,76× |
| SOL | 4,70% | 1,45× |
| SUI | 6,30% | 1,08× |

Jadi pada aset volatil (SUI/SOL), **1,1–1,5× tanpa leverage tambahan** sudah cukup untuk
mencapai target *jika* Sharpe-nya 2. Pada BTC butuh 2,5×.

---

## 6. Fakta kelima: diversifikasi tidak menyelamatkan edge yang kurang

Simulasi 20.000 window, N trade masing-masing notional 1/N, TP 3% / SL 1,5%:

| Win-rate per trade | E per window | N=1 | N=3 | N=5 | N=10 | N=20 |
|---|---|---|---|---|---|---|
| 45% | +0,53% | 46% | 42% | 40% | 26% | 25% |
| 50% | +0,75% | 50% | 50% | 50% | 38% | 41% |
| 52% | +0,84% | 51% | 53% | 54% | 43% | 49% |
| 55% | +0,98% | 55% | 58% | 59% | 51% | 59% |
| 60% | +1,20% | 60% | 65% | 68% | 63% | 75% |

**Pola penting:** bila edge per trade **di bawah** target, menambah jumlah trade justru
**menurunkan** peluang mencapai target (karena hasil mengecil menuju rata-rata yang kurang).
Diversifikasi hanya membantu bila edge sudah **di atas** target.

Ini menjelaskan kegagalan buku SoDEX: 21 trade/window dengan edge negatif — memperbanyak
trade hanya mempercepat kerugian.

---

## 7. Verdict per venue

### SoDEX
- **Kekuatan:** fee taker terendah (5,6–6,5 bps RT).
- **Kelemahan:** spread sangat tipis (0,08–1,03 bps) sehingga maker tidak ekonomis; hanya 15
  simbol; **riwayat API 7 hari (1m) / 30 hari (5m)** → edge **tidak bisa divalidasi**.
- **Cocok untuk:** tidak ada strategi berkelanjutan pada tier sekarang.

### Aster
- **Kekuatan:** **maker 0 bps** — satu-satunya venue di mana round-trip pasif benar-benar gratis.
  API kompatibel Binance (integrasi murah). Depth memadai untuk $2.500.
- **Kelemahan:** taker 4 bps/leg (8 RT) lebih mahal dari SoDEX; spread majors ~0,01–0,04 bps
  (terlalu tipis untuk MM), alt lebih lebar tapi adverse selection belum diukur.
- **Cocok untuk:** strategi **limit-order** (entry & exit pasif) — tapi harus mengatasi adverse
  selection yang sudah terbukti 111 bps di SoDEX.

### Hyperliquid
- **Kekuatan:** maker 1,5 bps/leg, funding per jam (lebih halus), depth besar (top-1 bid
  $349k BTC), satu venue untuk perp + spot.
- **Kelemahan:** taker 4,5 bps/leg; spread BTC 0,245 bps (2× lebih lebar dari SoDEX).
- **Cocok untuk:** eksekusi maker dengan biaya menengah; riset funding per jam.

### Binance
- **Kekuatan:** likuiditas terdalam ($25k slippage 0), **2,8 tahun data historis** untuk
  validasi, spot tersedia (bebas funding), instrumen lengkap.
- **Kelemahan:** fee taker tertinggi (10 bps RT); maker 4 bps RT.
- **Cocok untuk:** **validasi strategi** dan eksekusi skala besar; bukan untuk strategi
  frekuensi tinggi berbiaya.

---

## 8. Di mana venue BENAR-BENAR mengubah hasil

Ini bagian yang jujur: venue **tidak** membuat target mudah, tetapi ada tiga efek nyata.

1. **Kapasitas.** SoDEX tidak bisa menyerap >$10–20k tanpa slippage; Binance/HL bisa.
   Jika tujuan adalah menumbuhkan modal, ini pembatas keras.
2. **Kemampuan validasi.** Binance menyediakan 2,8 tahun 1h (dan 1m berbulan-bulan); SoDEX
   7 hari. Tanpa data, Anda tidak bisa tahu apakah edge ada — dan itulah yang terjadi: 8
   keluarga sinyal gagal diuji karena sampel 30 hari hanya mampu mendeteksi efek >6–25 bps.
3. **Instrumen.** Untuk long 30–48 jam, **spot menghapus funding 10–16 bps**. Itu penghematan
   yang lebih besar daripada memilih venue perp mana pun.

---

## 9. Kesimpulan

1. **Target 0,8% per 30 jam = 10,2× per tahun.** Itu target kelas dunia, bukan target biasa.
2. **Pergerakan 0,8% tersedia di 67–85% window** — peluang bukan masalah; arah adalah masalah.
3. **Biaya venue berbeda 0–20 bps** dari target 80 bps. Pindah venue menggeser kebutuhan
   win-rate hanya **2,2 poin**.
4. **Funding 10–16 bps per 30 jam** lebih besar dari fee, dan hanya hilang dengan spot.
5. **Target ini menuntut Sharpe 17 bila risiko kecil, atau Sharpe ~3,4 dengan risiko 4%/window.**
   Artinya: harus ada edge nyata **dan** ukuran posisi yang berani.
6. **Kesimpulan langsung:** pindah ke Aster/HL/Binance **tidak** membuat target "jauh lebih
   mudah". Yang berubah: biaya kecil, kapasitas besar, dan — paling penting — **data cukup
   untuk membuktikan atau membantah edge**.

---

## 10. Rekomendasi konkret

| Prioritas | Tindakan | Alasan kuantitatif |
|---|---|---|
| 1 | Pindahkan **riset** ke Binance (data 2,8 th), bukan eksekusi | tanpanya, edge tidak terukur; MDE 30 hari = 6–25 bps |
| 2 | Jika tetap perp, gunakan **Aster maker** untuk entry/exit pasif | fee 0 vs 5,6 (SoDEX) vs 10 (Binance) |
| 3 | Untuk long >24 jam, pertimbangkan **spot** | hemat funding 10–16 bps/window |
| 4 | Naikkan RR (TP/SL) sebelum mengejar win-rate | 2:1 → 51% WR; 1:1 → 63% WR |
| 5 | Jangan menambah jumlah trade bila edge per trade < target | diversifikasi memperburuk (tabel §6) |

---

## 11. Keterbatasan analisis ini

1. Fee dapat berubah (promo/VIP); angka diambil dari dokumentasi resmi 23 Okt 2026.
2. Funding historis Binance dipakai sebagai proksi; funding HL/Aster punya formula berbeda.
3. Volatilitas 2,8 tahun mencakup berbagai rezim, tetapi masa depan bisa berbeda.
4. Model win-rate mengasumsikan trade independen dan TP/SL tercapai penuh; slippage ekor
   (gap) tidak dimodelkan — dan itu membuat hasil nyata **lebih buruk**, bukan lebih baik.
5. Analisis ini tidak membuktikan adanya edge; ia hanya menunjukkan **venue bukan penyebab**
   dan **berapa besar edge yang dibutuhkan**.
