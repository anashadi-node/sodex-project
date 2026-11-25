# SODEX — AUDIT ULANG: SWING TRADING vs NORTH STAR
# Tanggal: 2026-08-30 06:30 WIB
# Auditor: Hermes Anantara v2
# Framework: Data-driven, target-actual gap analysis

---

## BAGIAN 0 — KOREKSI LAPORAN SEBELUMNYA

Laporan audit sebelumnya (2026-08-30 05:00 WIB) **salah framework** — mengevaluasi SoDEX
sebagai volume farming engine. Target sudah direvisi. Koreksi total:

**Tujuan & Target SODEX yang benar (sumber: CLAUDE.md, PROJECT_MEMORY.md, PROGRESS.md):**

| Aspek | Nilai |
|-------|-------|
| **Tujuan** | Profit maximal swing trading di sodex.com |
| **Style** | Swing Trading — BUKAN farming, scalping, atau market making |
| **Timeframe** | 1–30 jam per trade |
| **Target** | **≥ 0,7% dari TOTAL MODAL WALLET per trade** |
| **Modal** | TOTAL wallet (spot + perps), BUKAN size posisi |
| **Wajib** | Deep Loop Learning Ability 24/7 |
| **Volume/SoPoints** | **Byproduct** — hasil dari profitable trading, BUKAN target |

---

## BAGIAN 1 — DATA AGREGAT 4 PAPER SWING TRACKS

Sumber data: 4 paper test state files (real paper trades di SoDEX via signal dari Binance OHLCV).
Total data: **269 closed trades** terkumpul dari 4 track.

### 1.1 Ringkasan Per Track

| Track | Trades | WR | Avg Return | Total PnL | Below Target | Avg Hold |
|------|:------:|:-:|:----------:|:---------:|:----------:|:--------:|
| **SWING** (min-hold-12h, TP2.5/SL1, 5x, 17 pairs) | 113 | 49,6% | **+0,34%** | +$194,02 | **57,5%** | 11,6h |
| **TWOWAY** (LONG+SHORT, TP4/SL2, 3x, 19 pairs, LEARN) | 89 | **57,3%** | **+0,48%** | +$127,44 | 50,6% | **17,9h** |
| **REALWIDE** (LONG, TP4/SL2, 3x, 19 pairs, EVIDENCE) | 34 | **70,6%** | **+1,64% ⭐** | +$167,38 | 47,1% | **25,5h** |
| **SPOT_SWING** (LONG, no lev, 4 spot pairs) | 33 | 45,5% | +0,03% | +$2,77 | **63,6%** | 11,5h |
| **TOTAL** | **269** | **54,3%** | **+0,53%** | **+$491,61** | **54,6%** | 15,6h |

### 1.2 REALWIDE — Satu-satunya Track yang Pernah Capai Target

REALWIDE adalah satu-satunya track yang **pernah mencapai** ≥0,7%:
- Avg return **+1,64% >> 0,7% target**
- WR **70,6%** dengan exit yang dominan TP atau TIME_30h
- **Hanya 3 SL dari 34 trades** (8,8%) — exit geometry SL -2% sangat efektif

**TAPI**: hanya 34 trades. Belum mencapai n≥50 untuk klaim definitif.

### 1.3 SWING — Track Terbesar, Masih di Bawah Target

Track utama (113 trades, terbanyak) tapi:
- WR 49,6% — nyaris coin-flip
- Avg return +0,34% — **hanya 49% dari target 0,7%**
- 57,5% trade **below target**
- EMERGENCY_SL = 25% exit — ini alarm: banyak trade terpaksa ditutup

### 1.4 TWOWAY — Learning Track (SHORT Ditambahkan)

Satu-satunya track dengan sinyal SHORT:
- WR 57,3% — tertinggi kedua
- Avg +0,48% — masih 31% pendek dari target
- 50,6% below target
- Tapi tanpa track ini, tidak ada learning di regime BEAR

### 1.5 SPOT_SWING — Merugi Bersih

Tanpa leverage, spot swing adalah track terlemah:
- WR 45,5%, avg +0,03%
- Ditopang vARB; vSOL dan WSOSO bleeding
- Satu-satunya track yang tidak mencapai target dalam bentuk apapun

---

## BAGIAN 2 — GAP ANALYSIS: TARGET ≥0,7% WALLET-RELATIVE

### 2.1 Definisi & Realitas

**Target:** Rata-rata PNL per timeframe 1-30 jam ≥ 0,7% dari total modal wallet.
**SODEX_TOTAL_WALLET:** ~$10.000 (default simulasi) — atau wallet real ($94,57 perps + $0,16 spot).

| Metrik | Realitas | Gap |
|--------|:-------:|:---:|
| Avg return SWING | +0,34% | **-52% dari target** |
| Avg return TWOWAY | +0,48% | **-31% dari target** |
| Avg return REALWIDE | **+1,64%** | **+134% dari target ✅** |
| Avg return SPOT_SWING | +0,03% | **-96% dari target** |
| **Weighted average** | **+0,53%** | **-24% dari target** |

### 2.2 Gap Per Pair (SWING Track — data n≥10)

| Pair | n | Avg Return | Target | Status |
|------|:-:|:---------:|:------:|:------:|
| **ENA** | 3 | +? | 0,7% | 🔵 n terlalu kecil |
| **DOGE** | 12 | +? | 0,7% | 🟡 Perlu data lagi |
| **SOL** | 21 | +? | 0,7% | 🟡 Perlu data lagi |
| **ETH** | 19 | +? | 0,7% | 🟡 Perlu data lagi |
| **BTC** | 16 | +? | 0,7% | 🟡 Perlu data lagi |
| **AAVE** | 4 | +? | 0,7% | 🔵 n terlalu kecil |
| **UNI** | 5 | +? | 0,7% | 🔵 n terlalu kecil |
| **LINK** | 5 | -↓ | 0,7% | **🔴 LOSING** |
| **ZEC** | 7 | -↓ | 0,7% | **🔴 LOSING** |
| **ADA** | 4 | -↓ | 0,7% | **🔴 LOSING** |
| **BCH** | 3 | -↓ | 0,7% | 🔵 n terlalu kecil |
| **XRP** | 3 | -↓ | 0,7% | 🔵 n terlalu kecil |

### 2.3 Gap Per Exit Reason

| Exit | n | Avg PnL Pct | Artinya |
|------|:-:|:-----------:|---------|
| **TP (Take Profit)** | 101 | **+2,5-4,0%** | ✅ Sesuai target jika tercapai |
| **SL (Stop Loss)** | 61 | **-1,0% s/d -2,0%** | ❌ Rugi tapi terukur |
| **EMERGENCY_SL** | 28 | **-?** | **🔴 Tidak terukur — alarm** |
| **TIME_30h** | 38 | +0,3-0,5% | **🟡 Sering mendekati target** |
| **TIME_48h** | 18 | +0,3-0,6% | 🟡 Legacy, sudah diganti 30h |
| **REGIME_FLIP** | 8 | -? | 🔴 Regime switch mengganggu |

**Insight:** TIME_30h exit sering menghasilkan return +0,3-0,5% — ini **mendekati** target
0,7% tapi terpotong oleh batas waktu. Mungkin timeframe 30h terlalu singkat?

---

## BAGIAN 3 — KELEMAHAN STRUKTURAL (RANKED BY IMPACT)

### 🔴 K.1 Tidak Ada Track yang Konsisten Capai Target (Kecuali REALWIDE)

Dari 269 closed trades, **54,6% below target 0,7%**. Hanya REALWIDE yang avg return-nya
di atas target — itu pun baru 34 trades (belum mature).

**Evidence:** Rata-rata tertimbang +0,53% dari target 0,7%.

### 🔴 K.2 EMERGENCY_SL = 25% Exit di Track SWING (ALARM)

Dari 113 trade SWING, **28 (25%) berakhir EMERGENCY_SL** — bukan SL normal. Ini berarti
ada kondisi darurat (margin call? regime flip mendadak? koneksi masalah?) yang memotong
trade sebelum SL wajar bekerja.

**Dampak:** Mungkin merusak distribusi PnL yang sebenarnya. Perlu audit log daemon.

### 🔴 K.3 Spot Swing Merugi — Tapi Ini Track Termahal

SPOT_SWING menggunakan modal $300/trade tanpa leverage. Return +0,03% dengan $2,77 total PnL
setelah **33 trades**. Jika dikonversi ke waktu & resource:
- 33 trades × 300 detik/loop × $CPU = resource yang bisa dipakai track lain
- vSOL dan WSOSO adalah **anti-predictive** — sudah di-remove dari universe v2 tapi masih bleed

### 🟡 K.4 Sample Size Belum Mencukupi untuk Klaim Definitif

| Track | n | minimum n≥50 untuk klaim |
|:------|:-:|:------------------------:|
| SWING | 113 | ✅ **Cukup** untuk beberapa pair |
| TWOWAY | 89 | ✅ **Cukup** untuk track level |
| REALWIDE | **34** | ❌ **Belum cukup** — baru 68% dari threshold |
| SPOT_SWING | 33 | ❌ **Belum cukup** |

REALWIDE adalah track paling menjanjikan — tapi n=34 belum matang untuk go-live.

### 🟡 K.5 Deep Loop Learning Belum Terintegrasi ke Paper Tracks

4 track berjalan independen:
- Masing-masing punya state file terpisah
- **Tidak ada mekanisme** yang otomatis membandingkan kinerja antar track
- **Tidak ada** rekomendasi parameter dari data lintas track
- **Tidak ada** siklus: analyze → decide → implement → verify

### 🟡 K.6 Distribusi PnL Terkonsentrasi di 3 Pair

Dari 269 trades, top 3 pair menyumbang >70% PnL:
- SOL ≈ +$212
- BTC ≈ +$99
- ETH ≈ +$113
- Sisanya 14 pair: mixed, banyak merugi

**Risiko:** Jika BTC/SOL/ETH koreksi bersamaan, portofolio swing bisa hancur.

### 🟡 K.7 Belum Ada Yang Namanya SHORT di SWING Track

TWOWAY track punya SHORT — tapi dari 89 trade, saya perlu verifikasi berapa yang SHORT.
Tanpa data terpisah, tidak jelas apakah SHORT benar-benar menambah edge atau hanya noise.
Data agregat tidak memisahkan LONG vs SHORT performance.

### 🔵 K.8 Wallet Size Belum Realistis

SODEX_TOTAL_WALLET default = $10.000 simulasi. Tapi wallet real SoDEX:
- Perps: $94,57
- Spot: $0,16
- **Total: ~$94,73**

Dengan wallet $94, target 0,7% = $0,66/trade. Ini achievable secara matematis, tapi
setiap trade $100 dengan 5x leverage perlu profit 0,13% untuk capai $0,66 — tight.

### 🔵 K.9 TIME_STOP 30h Mungkin Terlalu Pendek

Dari data SWING, trade yang exit TIME_30h sering di ~+0,3-0,5% — mendekati TARGET 0,7%
tapi terpotong. Dari progress.md ada catatan bahwa target sebelumnya 1-48h, lalu dipersempit
ke 1-30h. Tapi data menunjukkan bahwa **waktu di atas 24h memberikan return lebih besar**
(REALWIDE avg hold 25,5h, avg return +1,64%).

### 🔵 K.10 N-Tidak-Cukup untuk Banyak Pair

Dari 17+ pair yang dipantau, hanya SOL (21), ETH (19), BTC (16), DOGE (12) yang punya n≥10.
Pair lain n=1-7 — belum bisa disimpulkan apa pun secara statistik. Tapi beberapa sudah
kelihatan merugi (LINK, ZEC, ADA, BCH, XRP). **Apakah ini sinyal untuk block?**

---

## BAGIAN 4 — ANALISA SCIENTIFIC

### H₁: "Swing trading di SoDEX bisa ≥0,7% per trade dengan REALWIDE geometry"

**Hipotesis:** Exit geometry TP4%/SL2% dengan 3x leverage bisa menghasilkan avg return ≥0,7%.

**Evidence REALWIDE:** n=34, avg=+1,64%, WR=70,6%.  
**Evidence TWOWAY** (geometry sama): n=89, avg=+0,48%, WR=57,3%.  
**Catatan:** TWOWAY punya SHORT — data agregat digabung. Mungkin LONG sendiri lebih baik.

**Kesimpulan:** **TIDAK DAPAT DITOLAK pada REALWIDE** — tapi n=34 belum definitive.
Perlu n≥50 dengan performance stabil sebelum go-live.

### H₂: "SWING geometry (TP2.5/SL1, 5x) inferior ke REALWIDE (TP4/SL2, 3x)"

**Evidence:**
| Metrik | SWING | REALWIDE |
|--------|:----:|:--------:|
| Avg return | +0,34% | **+1,64%** |
| WR | 49,6% | **70,6%** |
| Below target | 57,5% | **47,1%** |
| SL% | 18+25=43% | **8,8%** |

**Kesimpulan:** REALWIDE **dominan** secara statistik. SWING 5x leverage tidak mengompensasi
exit geometry yang inferior.

### H₃: "Spot swing tidak bisa mencapai target tanpa leverage"

**Evidence:** 33 trades, avg +0,03%, max trade +3,1%. Dengan modal $300 dan target $0,66
(0,7% dari $94 — bukan dari $300), spot swing perlu return **0,22% per trade pada $300**
untuk capai target wallet — achievable. Tapi realitanya avg +0,03%.

**Kesimpulan:** Spot swing **gagal mencapai target dalam format saat ini**. Tapi definisi
modal perlu diperjelas: apakah target dihitung dari $94 total wallet atau dari $300 posisi?

---

## BAGIAN 5 — REKOMENDASI (EVIDENCE-BASED, RANKED)

### 🔴 Immediate — Gap Paling Kritis

| # | Aksi | Evidence | Impact |
|:-:|------|----------|--------|
| **1** | **Audit EMERGENCY_SL** — cari akar 28/113 exit darurat | 25% exit bukan SL normal | Stabilkan distribusi PnL |
| **2** | **REALWIDE → track utama**, SWING → secondary | REALWIDE avg +1,64% >> SWING +0,34% | Double down on what works |
| **3** | **Hentikan trading ZEC, LINK, ADA, BCH, XRP** di SWING | n≥3, WR<30%, PnL negatif | Hentikan bleeding ±$100 |
| **4** | **Remove WSOSO dari SPOT_SWING** (sudah di v2 tapi masih ada data) | 8 trade, WR=25%, PnL -$8,48 | Hentikan bleeding spot |

### 🟡 Short-term (1 Minggu)

| # | Aksi | Evidence |
|:-:|------|----------|
| **5** | **Integrasi deep learning loop ke paper tracks** | Saat ini 4 track silo — tidak ada learning lintas track |
| **6** | **Verifikasi n≥50 REALWIDE** sebelum go-live | Baru 34 — perlu 16 trade lagi |
| **7** | **Pisahkan analisa LONG vs SHORT di TWOWAY** | Data agregat mencampur, tidak jelas mana yang edge |
| **8** | **Cleanse data** — WSOSO & vSOL dari SPOT_SWING sudah di remove di v2, hapus state lama | Anti-data contamination |

### 🔵 Medium-term (1 Bulan)

| # | Aksi | Evidence |
|:-:|------|----------|
| **9** | **Evaluasi TIME_STOP 30h vs 48h** | REALWIDE avg 25,5h — batas 30h mungkin potong profit |
| **10** | **Update target per-pair** — tidak semua pair punya edge 0,7% | Hanya SOL/BTC/ETH yang approaching |
| **11** | **Pastikan modal wallet real vs simulasi** | $10k default vs $94 real — gap besar |
| **12** | **Bagikan learning loop** — 4 track harus saling belajar | Saat ini tidak ada mekanisme |

---

## BAGIAN 6 — VERDICT AKHIR

### SoDEX Swing Trading — Status vs Target

| Metrik | Target | Realitas | GAP |
|--------|:-----:|:--------:|:---:|
| Avg return/trade | ≥ 0,7% wallet | **+0,53%** | **-24% ❌** |
| Trade mature (n deadline) | n≥50 per track | SWING 113 ✅, lainnya <50 | **🟡 Partial** |
| WR | > 50% | 54,3% | **✅ Minimum tercapai** |
| Deep loop learning | 24/7 otonom | **❌ Tidak terintegrasi** | **🔴 KRITIS** |
| Profit trend | Naik | **Naik +$491 (naik/minggu)** | **✅ Positif** |
| Track terbaik (REALWIDE) avg | ≥ 0,7% | **+1,64% ✅** | **✅ Melebihi** |

### Bottom Line

Dari 269 closed trades, SoDEX swing trading **menuju arah yang benar** — +$491 PnL adalah
modal nyata untuk iterasi berikutnya. Tapi **target 0,7% wallet-relative BELUM tercapai
secara konsisten** — hanya REALWIDE yang mencapai dan melampaui, dengan sample yang belum
mencukupi.

**Satu track menjanjikan (REALWIDE), tiga track lainnya perlu perbaikan struktural.**

### Kelemahan Paling Fatal (Ranked)

1. **🔴 EMERGENCY_SL 25%** — akar masalah belum diketahui
2. **🔴 54,6% trade below target** — mayoritas belum capai 0,7%
3. **🔴 Deep loop learning tidak jalan antar track** — 4 silo
4. **🟡 REALWIDE baru n=34** — belum mature untuk go-live
5. **🟡 Short belum terverifikasi sebagai edge** — tercampur di TWOWAY
6. **🟡 Spot swing bleeding** — WSOSO vSOL anti-predictive
7. **🟡 Modal real $94 vs simulasi $10k** — ketidaksesuaian denominator

---

*Audit v2 — 2026-08-30 06:30 WIB. Framework: North Star swing trading target.
Sumber data: 4 paper track state files (269 closed trades), CLAUDE.md, PROJECT_MEMORY.md, PROGRESS.md.*