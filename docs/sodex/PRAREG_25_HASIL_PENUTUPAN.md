# PRAREG-25 — PENUTUPAN: BREADTH (UNIVERSE 6 → TOP-20 LIKUID)

**VONIS: GAGAL — KEDUA LENGAN.** Dan yang lebih penting: **hipotesis "daya statistik" TERBANTALIK secara empiris.**

- Protokol dibekukan sebelum eksekusi: `sha256 a256d35025c2a888…`, 69 baris, `reports/sodex/PRAREG25_BEKU.json`.
- Data: pool 66 simbol Binance spot USDT, **66/66 layak**, 1d, 2017-08-17 → 2026-10-09 (`data/prereg25/MANIFEST.json`).
- Sinyal: **identik** PRAREG-23 (`series_for` diimpor) — lulus uji ekuivalensi.
- Biaya utama 25 bps/sisi. Bootstrap 2.000 iter, blok 20 hari. DSR dengan n_trials = 80 (jujur).
- Tidak ada order, tidak ada posisi, tidak ada flag live yang disentuh.

---

## 1. Uji ekuivalensi menyelamatkan run (temuan teknis yang wajib dicatat)

Replikasi vektor saya awalnya **divergen** dari algoritma beku: BTC hari 367, L=5 → 6.425,825 vs 6.386,285.

**Sebab:** algoritma beku memakai `cl[i-L:i+1]` = **L+1 bar** untuk hi/lo (inklusif hari ini),
tetapi `cl[i-L:i]` = **L bar** untuk ambang breakout. Replikasi saya memakai L untuk keduanya.

**Perbaikan:** `rolling(L+1)` untuk hi/lo. Uji ulang → **IDENTIK**: BTC/ETH/SOL × ~3.000 hari × 9 window,
plus silang-periksa ke `series_for` asli BTC. **Algoritma beku tidak diubah** — hanya replikasi diperbaiki.
Konsistensi tambahan: hasil jendela terverifikasi **identik** sebelum dan sesudah perbaikan unduhan (END).

---

## 2. Hasil utama — jendela terverifikasi (≤ 2025-10-09), 25 bps/sisi

| Seri | Sharpe | Return total | maxDD | Eksposur | Blok 20h positif | Median blok | **%/48 jam** | CAGR | p vs BTC | DSR |
|---|---|---|---|---|---|---|---|---|---|---|
| **BTC B&H** | +0,95 | +2.861% | −83,2% | 1,00 | 55% | +1,99% | — | — | — | — |
| EW-pool (66 koin) | +0,81 | +1.200% | −90,4% | — | — | — | — | — | — | — |
| **S-A** kontrol (÷N) | +1,07 | +91,3% | **−13,0%** | 0,078 | 39% | +0,00% | +0,0436% | +8,3% | 0,392 | 0,722 |
| **S-B** primer (tanpa ÷N) | +0,92 | +1.711% | −81,5% | 0,651 | 39% | +0,00% | +0,1949% | +42,7% | 0,524 | 0,570 |

Pada biaya 10 bps: S-A S=+1,14 (+0,0465%/48j) · S-B S=+1,02 (+0,2232%/48j).

## 3. Gerbang (8 kriteria, semua wajib)

| # | Kriteria | S-A | S-B |
|---|---|---|---|
| a | Sharpe ≥ BTC | ✅ 1,07 ≥ 0,95 | ❌ **0,92 < 0,95** |
| b | maxDD ≤ 50% BTC (−41,6%) | ✅ −13,0% | ❌ **−81,5%** |
| c | Positif ≥2/3 sub-periode | ✅ 3/3 (1,74/0,35/1,01) | ✅ 2/3 (1,84/**−0,44**/0,72) |
| d | ≥60% blok 20h positif **dan** median > 0 | ❌ 39%, median ≈ 0 | ❌ 39%, median ≈ 0 |
| e | p < 0,025 (Bonferroni 2 lengan) | ❌ **0,392** | ❌ **0,524** |
| h | DSR > 0 (n_trials = 80) | ✅ 0,722 | ✅ 0,570 |
| f | ≥ 0,10%/48 jam | ❌ **0,0436%** | ✅ 0,1949% |
| g | Eksposur ≥ 0,30 | n/a | ✅ 0,651 |
| | **HASIL** | **GAGAL** (d, e, f) | **GAGAL** (a, b, d, e) |

---

## 4. INTI ILMIAH: hipotesis breadth **TERBANTALIK**

Hipotesis yang saya pra-registrasikan: PRAREG-24 gagal pada (d),(e) karena **daya statistik**;
menambah jumlah taruhan independen (6 → 20 koin) harus **menurunkan p-value** tanpa menaikkan risiko.

**Yang terjadi justru sebaliknya.** Perbandingan apel-ke-apel (25 bps, jendela terverifikasi):

| Konfigurasi | Universe | Sharpe | maxDD | Eksposur | %/48 jam | **p** |
|---|---|---|---|---|---|---|
| V0 ÷N (PRAREG-24) | 6 | **+1,47** | −12,2% | 0,107 | 0,0738% | **0,082** |
| V1 tanpa ÷N (PRAREG-24) | 6 | +1,40 | **−50,2%** | 0,480 | 0,2636% | 0,108 |
| S-A ÷N (PRAREG-25) | **20** | +1,07 (−0,40) | −13,0% | 0,078 | 0,0436% | 0,392 |
| S-B tanpa ÷N (PRAREG-25) | **20** | +0,92 (−0,48) | **−81,5%** | 0,651 | 0,1949% | 0,524 |

**Breadth 6 → 20: Sharpe TURUN 0,40–0,48 · maxDD memburuk −50% → −81,5% · p-value NAIK (0,108 → 0,524).**

Mekanismenya jelas dan tidak mistis:
1. Koin peringkat 7–20 menurut likuiditas punya **persistensi tren lebih lemah** dan **volatilitas idiosinkratik jauh lebih besar** → mereka menyumbang **varians**, bukan **alpha**.
2. Pada cap Σw ≤ 1,00 tanpa pembagi, eksposur naik ke **0,651** dan portofolio menjadi **proksi beta pasar**: maxDD −81,5% ≈ BTC −83,2%. Sinyal tren kehilangan perannya.
3. Karena alpha tidak bertambah sedangkan varians bertambah, **p-value memburuk secara matematis** — persis kebalikan dari hipotesis.

**Kesimpulan: menambah breadth BUKAN alat untuk membeli daya statistik pada keluarga mesin ini.**

---

## 5. Sensitivitas wajib (S-B, 25 bps, jendela terverifikasi)

| Skenario | Sharpe | Return | maxDD | %/48 jam | p |
|---|---|---|---|---|---|
| Baseline S-B | +0,92 | +1.711% | −81,5% | 0,1949% | 0,524 |
| **Tanpa 3 kontributor terbaik** (BTC, BNB, ETH) | **+0,67** | **+471%** | −82,1% | +0,1172% | 0,766 |
| Tanpa koin delisting (9 simbol) | +0,97 | +2.045% | −79,2% | +0,2062% | 0,483 |

- **Ketergantungan pada pemenang: parah.** Buang 3 koin → return jatuh **−74%** (1.711% → 471%) dan Sharpe 0,92 → 0,67. Yang bekerja adalah **majors**, bukan breadth.
- **Delisting bukan penyebab kegagalan** (tanpanya malah sedikit lebih baik) → bias survivorship bukan penyumbat utama di sini; kejujuran ini penting agar tidak salah menyalahkan data.
- **Turnover:** S-A **3,6×/tahun** (hemat) vs S-B **34,1×/tahun** (churn harian) → beban biaya ≈ 8,5%/tahun pada 25 bps untuk lengan agresif.

## 6. Ekstensi 2025-10-10 → 2026-10-09 (tidak terverifikasi)

| Seri | Sharpe | %/48 jam | Sub-periode terakhir |
|---|---|---|---|
| BTC | 0,95 → **0,83** | — | — |
| S-A | 1,07 → **0,96** | 0,0436% → 0,0376% | 1,01 → **0,65** |
| S-B | 0,92 → **0,78** | 0,1949% → 0,1492% | 0,72 → **0,26** |

**Semua meluruh**, konsisten dengan temuan PRAREG-23 (edge tren melemah pasca-2021). Median blok 20-hari
bahkan berubah **negatif** pada ekstensi (−0,06% / −0,47%).

---

## 7. Kesimpulan tingkat program

Dua perbaikan independen atas PRAREG-23 H1 sudah diuji dengan protokol beku, dan **keduanya gagal — masing-masing membuat kasus statistiknya lebih buruk**:

| Perbaikan | Yang diubah | Hasil |
|---|---|---|
| PRAREG-24 | **exposure** (4 varian sizing) | Melewati lantai 0,10%/48j (V1 0,264% · V3 0,280%), tetapi p **memburuk** (0,072–0,184) dan maxDD memburuk |
| PRAREG-25 | **breadth** (6 → 20 koin) | Sharpe **turun**, maxDD **−81,5%**, p **memburuk** (0,392–0,524) |

Yang tersisa dari keluarga mesin ini: **Sharpe ~0,9–1,1 dengan maxDD ringan (−13%) tetapi hanya ~0,038–0,044%/48 jam** — jauh di bawah lantai 0,10%. Untuk menembus lantai, eksposur harus dinaikkan, dan begitu eksposur dinaikkan portofolio berubah menjadi beta pasar dengan drawdown setara BTC (gagal gerbang b).

**Keluarga mesin trend-following harian long-only spot sudah HABIS pada ambang evidensi program (t ≥ 3,6 · p < 0,025).** Ini vonis berbasis bukti, bukan opini.

## 8. Cacat desain yang saya akui (dicatat sebelum dipakai ulang)

1. **Ambang DSR yang saya pra-registrasikan terlalu lemah** — saya menulis "DSR > 0", padahal pembacaan yang bermakna adalah DSR **> 0,95**. Nilai sebenarnya 0,722 (S-A) dan 0,570 (S-B) = **tidak signifikan**. Verdikt tidak berubah (sudah GAGAL lewat gerbang lain), jadi tidak ada pelonggaran — tetapi ambang yang lemah **tidak boleh** diulang di pra-registrasi berikutnya.
2. **Median blok 20-hari ≈ 0** pada semua lengan: strategi **kalah di mayoritas jendela** dan bergantung pada ekor kanan yang jarang. Ini profil yang secara struktural sulit lolos gerbang (d) dan rentan terhadap peluruhan edge.
3. Efek **cap Σw ≤ 1,00 pada lengan tanpa pembagi**: cap membuat portofolio = beta pasar saat sinyal kuat. Cap perlu diperlakukan sebagai variabel desain yang disadari, bukan detail teknis.

## 9. Rekomendasi (keputusan ada di Mas Anas)

1. **Jangan lanjutkan menambang keluarga ini** (tren harian long-only spot, window Donchian, sizing apa pun). Bukti: dua perbaikan gagal, ekstensi meluruh, ketergantungan pada majors ekstrem.
2. **Yang masih hidup dan sudah berjalan:** `anantara-paper-spot-ratchet.service` (paper, read-only, gate ketat, ~2–8 trade/bulan) dan `sodex-rangepos-forward.timer` (VONIS TIDAK KONKLUSIF). Keduanya tanpa order.
3. **Bila ingin mengejar tangga target**, keluarga edge berikutnya harus berbeda secara **struktural** (bukan parameter/ukuran/universe), dan tetap lewat pra-registrasi + halaman registry. Kandidat yang belum diuji di program ini: **mean-reversion berbasis likuidasi/OI**, **basis & carry lintas-venue** (terhambat data SoDEX), **cross-sectional momentum relatif** (long top-N / short bottom-N, market-neutral — bukan long-only).
4. **Kenyataan venue tetap mengikat:** SoDEX 0 mesin lulus dari 21; target 0,8%/48j butuh α ≥ 43,4 bps/48j — kelas yang belum pernah terlihat pada seluruh program ini.

---

**Disiplin:** protokol tidak diubah setelah melihat hasil · tidak ada ambang dilonggarkan · 2 lengan dicatat sebagai trial baru di `reports/sodex/sodex_trial_registry.json` (76 → 78) · tidak ada order/posisi/flag live.

*Ditutup: 09-Okt-2026 · Hermes Anantara v3*
