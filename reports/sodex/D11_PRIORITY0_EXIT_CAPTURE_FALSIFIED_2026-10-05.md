# D11 — PRIORITY 0: Panen Exit-Capture Dieksekusi → **FALSIFIED**

**Divisi SoDEX · Hermes Anantara v3 · 5 Oktober 2026**
**Pemicu:** rekomendasi D10 (`PRIORITAS 0 — panen exit-capture, bukti terkuat, biaya terendah`).
**Hasil:** **hipotesis D10 ditolak oleh data.** Exit bukan tuas yang bisa dipanen pada lane ini.

---

## 0. Ringkasan dalam Satu Tabel

| Hipotesis D10 | Uji | Hasil |
|---|---|---|
| Geometri exit ATR-adaptif mengalahkan SL/TP tetap | A/B 3 arm, 59,6 hari | **❌ FALSIFIED** — kontrol menang |
| Vol gate ATR>2% adalah penyebab (bukan sekadar pengecualian) | A2 = gate DIMATIKAN | **❌ FALSIFIED** — gate-OFF sedikit lebih buruk |
| PEAK_TRAIL bernilai +1,80 pp/trade | Hitung ulang dari data mentah | **❌ TIDAK TERVALIDASI** — n hanya **5** |
| Capture leak (median MFE > median realized) adalah kebocoran yang bisa dipanen | Analisis `peak_g` + kontribusi ekor | **⚠️ TERBALIK** — memanen MFE justru membunuh profit |
| Lane REAL-WIDE punya edge positif | bootstrap cluster 10.000 | **❌ TIDAK SIGNIFIKAN** — CI95 memuat nol |

> **Kesimpulan utama: kesimpulan saya sendiri di D10 ("prioritas 0 = panen exit") SALAH.**
> Data menolaknya. Ini dilaporkan apa adanya — itulah gunanya falsifikasi.

---

## 1. Kesalahan Saya Sendiri yang Ditemukan Lebih Dulu

**Skala `pnl_pct` salah 100×.** Nilai disimpan sebagai **fraksi** (`-0.00219`), bukan persen.

| | Sempat saya laporkan | **Benar** |
|---|---|---|
| mean KONTROL | +0,002% | **+0,203%** |
| `atr_pct` ONDO | 0,014% | **0,916%** |
| SL / TP median | — | **1,50% / 6,00%** |

Diperbaiki sebelum kesimpulan apa pun ditarik. **Pelajaran:** selalu cek skala terhadap nilai yang punya arti fisik (SL=1,5%, TP=6% → `min≈−3%`, `max≈+6,6%` → konsisten).

---

## 2. Eksperimen A/B Exit — Struktur Arm Rusak

| Arm | Unit systemd | Status | n | Rentang |
|---|---|---|---|---|
| KONTROL (SL1,5 / TP6) | `anantara-paper-realwide.service` | **running** | **245** | 06-Agu → 04-Okt |
| **A1** `_atrvol` (SL=1×ATR, gate ON) | `...-atrvol.service` | **`inactive (dead)` + `disabled`** | **25** | 26-Sep → **30-Sep** |
| A2 `_atrvolopen` (SL=1×ATR, gate OFF) | `...-atrvolopen.service` | **running** | **63** | 26-Sep → 04-Okt |

**Dua cacat desain:**

1. **A1 mati sejak 1-Okt 11:17** pada **n=25**, di bawah kriteria pra-registrasi sendiri (**n ≥ 30/arm**). Penyebab terdeteksi: baris `Documentation=docs/cex/AB_REALWIDE_ATR_ARM_20260925.md` di unit file (systemd mengharapkan URL) membanjiri log. Unit kini `disabled`.
2. **Kontrol berjalan 3× lebih lama** dari kedua arm → akumulasi n tidak sebanding. Perbandingan mentah menyesatkan.

---

## 3. Hasil — Semua Arm, dan Jendela yang Adil

### 3.1 Seluruh riwayat (TIDAK sebanding — periode berbeda)

| Arm | n | mean | median | WR | SD |
|---|---|---|---|---|---|
| **KONTROL** | 245 | **+0,203%** | −0,044% | **49,4%** | 2,36 |
| A1 `_atrvol` | 25 | **−0,905%** | −1,549% | 32,0% | 1,11 |
| A2 `_atrvolopen` | 63 | −0,123% | −0,889% | 42,9% | 3,28 |

### 3.2 Jendela bersama (26-Sep → 30-Sep, 4,5 hari) — perbandingan ADIL

| Arm | n | mean | WR | CI95 |
|---|---|---|---|---|
| KONTROL | 25 | **−0,504%** | 28,0% | [−1,382%, +0,375%] |
| A1 `_atrvol` | 24 | **−0,962%** | 29,2% | [−1,401%, −0,523%] |
| A2 `_atrvolopen` | 34 | **−0,606%** | 38,2% | [−1,282%, +0,070%] |

**Bacaan:**
- **Ketiga arm RUGI** di jendela yang sama.
- **Semua CI95 tumpang-tindih** → **tidak ada perbedaan signifikan** antar arm.
- Uji A1 vs KONTROL: selisih −0,458 pp, SE(gabungan) 0,501 → **t = −0,91 → tidak signifikan.**
- **Kontrol tidak kalah** — bahkan unggul pada WR sepanjang riwayat (49,4% vs 32,0%).

> **Putusan A/B: geometri exit ATR-adaptif TIDAK memperbaiki expectancy. Vol gate BUKAN akar masalah.**

---

## 4. Mengapa Geometri ATR Gagal — Mekanismenya Terlihat

Distribusi alasan keluar (KONTROL vs A2):

| Alasan | KONTROL | A2 |
|---|---|---|
| **TP tercapai** | **33 (13,5%)** | **3 (4,8%)** ← anjlok |
| SL | 80 (32,7%) | 24 (38,1%) |
| SL_PROTECT | 57 (23,3%) | 15 (23,8%) |

Menaikkan SL/TP secara proporsional ATR (A2: TP = 4×SL) **melebarkan target** → **hit-rate TP jatuh dari 13,5% ke 4,8%** sementara SL naik. Menang lebih besar *saat* menang, tapi **jauh lebih jarang** — dan hasilnya lebih buruk.

---

## 5. Capture Leak — Diagnosis D10 TERBALIK

`peak_g` = MFE (puncak menguntungkan selama posisi). Ini pengukuran capture langsung.

**KONTROL (n=245):**

| Ukuran | Nilai |
|---|---|
| median MFE (`peak_g`) | **+0,548%** |
| median realized | **−0,044%** |
| **capture ratio** | **−8,0%** |
| trade menyentuh MFE ≥ 0,5% | **125 (51,0%)** |
| trade menyentuh MFE ≥ 1,0% | **98 (40,0%)** |
| batas atas teoretis (exit persis di puncak) | +1,363% vs aktual +0,203% |

Sekilas: "kita memberi balik 1,16 pp/trade — panen!" **Itu jebakan.**

### Mengapa memanen MFE akan MERUSAK, bukan memperbaiki

```
10 trade terbaik  = +62,2%   = 125% dari seluruh profit
33 trade terbaik  = +167,0%  = 336% dari seluruh profit
buang 33 terbaik  -> sisanya = -117,2%
```

**Seluruh profit berasal dari 33 trade (13,5%) — dan trade itu adalah pemenang TP besar (mean +5,03%).**

Aturan exit yang "memanen lebih cepat" (trailing lebih ketat, TP lebih kecil) akan **memotong justru 33 trade yang menopang semuanya.** Menangkap median MFE +0,548% berarti membunuh ekor +5,03%.

> **Ini profil lotere klasik, bukan kebocoran yang bisa dipanen.** Diagnosis "bottleneck = capture exit" (H1) **tidak sahih sebagai tuas aksi** pada lane ini.

### KLARIFIKASI PENTING

**`PEAK_TRAIL` — yang di memori tercatat +1,80 pp/trade — hanya memiliki n = 5.**
`PEAK_TRAIL` KONTROL n=5 (mean +1,626%), A2 n=4 (mean +1,941%). **Total n = 9.**
Kriteria pra-registrasi sendiri: **n ≥ 30 per arm.** Angka "+1,80 pp" **BELUM TERVALIDASI** — ia estimasi dari 5 titik. Memori sudah dikoreksi.

---

## 6. REKONSILIASI — Dua Pandangan yang Tampak Bertentangan

Ini bagian tersulit dan terpenting.

| Pandangan | Angka | Tafsir |
|---|---|---|
| **A. Mean per trade** | +0,203% | bootstrap cluster 10.000 → CI95 **[−0,261%, +0,749%]**, P(mean≤0)=**0,209** → **TIDAK SIGNIFIKAN** |
| **B. Jalur wallet kronologis** | $243,57 → **$392,81** = **+61,3%** / 59,6 hari = **+0,805%/hari** | **201% dari target 0,4%/hari** |

**Keduanya benar, dan keduanya menggambarkan data yang sama.** Yang menjelaskan jurangnya:

```
n hari              : 49     hari positif: 26 (53,1%)
median harian       : +$0,47 = +0,194% wallet
mean harian         : +$3,05 = +1,250% wallet   <- mean 6,4x median
hari terburuk       : -$59,38 = -24,38% wallet
drawdown maks       : -26,08%
```

### 6.1 Gate RESMI sudah menangkap masalahnya

`data/sodex_maturation_status.json` — REAL-WIDE (n=145):

| Kriteria gate | Nilai | Lulus? |
|---|---|---|
| n ≥ 50 | 145 | ✅ |
| WR ≥ 50% | 54,48% | ✅ |
| PF ≥ 1,5 | **1,405** | ❌ |
| **window_mean ≥ 0,8%** | **2,016%** | **✅** |
| **window_median > 0** | **0,00%** | **❌** |
| **window_hit ≥ 50%** | **39,1%** (9/23) | **❌** |

**Veridkt: NO-GO.** Catatan tracker: *"median window +0,00% < 0,8%; hanya 9/23 window capai 0,8%; window terburuk −13,4%"*.

> **Inilah inti seluruh persoalan:**

> **Target 0,8%/48 jam terlampaui pada MEAN (+2,016%) — tetapi NOL pada MEDIAN, dan hanya 39% jendela mencapainya.**
>
> Mean tinggi itu **ekor**, bukan edge. Jendela khas menghasilkan **persis nol**.

### 6.2 Uang nyata sudah menjawab

```
live: n_real=8   usd_real=-22.69   wr_real=0.375
      best_real=+2.17   worst_real=-19.06
```

**Satu-satunya uji forward dengan uang sungguhan: 8 trade, RUGI $22,69, WR 37,5%.** n kecil, tetapi inilah satu-satunya angka yang tidak bisa dibantah sebagai "paper".

---

## 7. Putusan PRIORITY 0

| # | Putusan | Dasar |
|---|---|---|
| P0-1 | **Geometri exit ATR-adaptif: GUGUR** | A/B: kontrol ≥ kedua arm; CI95 tumpang-tindih |
| P0-2 | **Vol gate BUKAN akar masalah** | A2 (gate OFF) tidak lebih baik |
| P0-3 | **PEAK_TRAIL belum terbukti** (n=9) | di bawah ambang pra-registrasi n≥30 |
| P0-4 | **"Capture leak" bukan tuas aksi** | profit = 33 trade ekor; memanen MFE membunuh mereka |
| P0-5 | **Lane REAL-WIDE tidak punya edge signifikan** | bootstrap CI95 memuat nol; live −$22,69 |
| P0-6 | **A1 harus diputuskan** | mati di n=25 (di bawah ambang); menunjukkan negatif |

> **Konsekuensi: D10 salah menempatkan "panen exit" sebagai PRIORITAS 0. Jalur itu sudah dieksekusi dan ditolak data. Tidak ada gain yang bisa dipanen dari exit pada lane ini.**

---

## 8. Yang Sebenarnya Ditinggalkan

Setelah exit gugur, apa yang tersisa:

| Kandidat | Bukti | Status |
|---|---|---|
| ❌ Exit geometry / PEAK_TRAIL | FALSIFIED hari ini | tutup |
| ❌ Model LightGBM (`sodex_model_server`) | 0/57 BH-FDR (D09) | tutup |
| ❌ Regime-adaptive trend (#1 dokumen) | T1 fail struktural, β 0,887 | tutup |
| ⚠️ **Order Flow** | acuan resmi #1 (92/100); punya 1,6 GB data **SEGAR** | **BELUM DIUJI** |
| ⚠️ Funding/carry | `mv_funding` SR 12,2 = 0,19%/48h | belum cukup |
| ⚠️ Masalah **bentuk distribusi** | median window 0,00% vs mean 2,02% | **belum diserang langsung** |

### Satu temuan yang MUNCUL dari sesi ini

Semua kegagalan hari ini punya bentuk yang sama: **mean terpenuhi, median nol, ekor yang menentukan.**

- REAL-WIDE: mean window +2,02% ✅ / median 0,00% ❌
- A2: max +19,46% tetapi median −0,889%
- 33 trade menopang 336% profit

> **Target 0,8%/48 jam adalah target MEDIAN (harga mati = harus hampir selalu terpenuhi), bukan target MEAN.** Seluruh mesin kita dioptimalkan untuk mean. **Ini kesenjangan yang belum pernah diserang secara langsung.**

---

## 9. Rekomendasi Langkah Berikutnya

**Bukan** lanjut ke Order Flow dulu. Yang lebih murah dan lebih mendasar:

### R1 — Tutup eksperimen exit secara bersih (biaya rendah)
- Putuskan A1: **hentikan permanen** (matikan unit + arsipkan) atau **hidupkan ulang** untuk mencapai n=30.
- Alasan permintaan putusan: arm yang `disabled` tapi masih ada = utang operasional.

### R2 — Serang BENTUK DISTRIBUSI, bukan mean (alamat baru)
Target adalah median. Mesin kita menghasilkan ekor. Kandidat uji:
- Apakah ada sub-populasi (rezim/sesi/simbol) di mana **median** window > 0?
- Kalau tidak ada di mana pun → masalahnya bukan pemilihan trade, melainkan **distribusi payoff** yang perlu diubah (mis. exit parsial berlapis: sebagian di TP kecil agar median > 0 tanpa membunuh ekor).

### R3 — Lanjutkan Order Flow (acuan resmi #1)
Setelah R1 ditutup. Ini kandidat terkuat yang **belum** diuji, dengan data segar 1,6 GB.

---

## 10. Verifikasi

| Item | Nilai |
|---|---|
| Data | `data/paper_test_realwide_state.json` (245 closed), `..._atrvol.json` (25), `..._atrvolopen.json` (63) |
| Gate resmi | `data/sodex_maturation_status.json` (REAL-WIDE & TWO-WAY keduanya NO-GO) |
| Bootstrap | 10.000 resample, cluster per hari (49 cluster), seed 20261005 |
| Skrip | `/home/USER/.hermes/cache/scratch/{ab_arm_analysis,capture_leak,wallet_check,reconcile}.py` |
| Produksi disentuh | **tidak** (read-only; tidak ada unit diubah) |
| Memori dikoreksi | klaim `PEAK_TRAIL +1,80pp` → ditandai **belum tervalidasi** |

---

*D11 · Divisi SoDEX · Hermes Anantara v3 · 5 Oktober 2026*
*Berkas terkait: `D10_ANALISIS_DOKUMEN_SWING_STRATEGIES_V1`, `D09_FALSIFIKASI_MODEL_LIGHTGBM`, `AB_REALWIDE_ATR_ARM_20260925`*
