# D10 — Analisis Kritis Dokumen `ANANTARA_SoDEX_Swing_Strategies_FINAL_V1`

**Divisi SoDEX · Hermes Anantara v3 · 5 Oktober 2026**
**Objek:** `~/Downloads/ANANTARA_SoDEX_Swing_Strategies_FINAL_V1.html` (38.580 byte · 784 baris · 13 bagian · 13 tabel · 24 rumus · 17 blok kode · 6 DOI)
**Metode:** pembacaan penuh + pembandingan silang terhadap **acuan resmi** (`ANANTARA_MASTER_Evidence_V1` + `V2_Supplement`) dan **bukti empiris internal** (D07, D08, D09, maturation tracker, A/B arm yang sedang berjalan).

---

## 0. Ringkasan Eksekutif

> **Dokumen ini JAUH DI ATAS RATA-RATA dalam integritas metodologis — tetapi rekomendasi utamanya menunjuk ke arah yang sudah kita buktikan gagal.**
>
> | Aspek | Penilaian |
> |---|---|
> | Kejujuran epistemik (label, pengakuan "bukan janji profit") | **Sangat baik** |
> | Keabsahan sitasi (6 DOI) | **Semua sah — 6/6 sudah ada di acuan resmi kita** |
> | Akurasi fakta venue (fee, funding, mark price) | **Cocok dengan catatan kita** |
> | Kesesuaian dengan prioritas acuan resmi | **⚠️ Menukar #1↔#2, membuang Lead/Lag** |
> | Kesesuaian dengan bukti empiris internal | **❌ Benturan serius di strategi #1, #4, dan §4** |
> | Kelayakan target (0,8%/48 jam) | **⚠️ Menuntut 1,5× Sharpe terbaik yang dokumen sendiri kutip** |
> | Kesiapan data untuk dieksekusi | **~25%** — L2/L4/mark/index/OI **tidak ada** |
>
> **Putusan: JANGAN adopsi urutan build dokumen ini apa adanya.** Ambil kerangka validasinya (§11–§13) — itu kelas satu. Tapi **jangan** bangun #1 (sudah gagal) dan **jangan** tambah gerbang #4/SLQS sebelum gerbang yang sudah ada divalidasi.

---

## 1. Peta Dokumen — Apa Sebenarnya Isinya

| Bagian | Isi | Sifat |
|---|---|---|
| §1 | Mandat ilmiah + 5 label semantik | **Kerangka** |
| §2 | Fakta venue SoDEX (index/mark, fee, funding, API, margin, TP/SL) | **Fakta** |
| §3 | Ranking Final Top-4 | **Rekomendasi** |
| §4 | Gerbang likuiditas universal (SLQS) | **Desain** |
| §5 | **#1** External-Regime Adaptive Trend/Breakout | **Rekomendasi** |
| §6 | **#2** Global Order Flow + Konfirmasi SoDEX | **Rekomendasi** |
| §7 | **#3** ProSP 4H/8H probability-tail | **Rekomendasi** |
| §8 | **#4** Risk-Managed Regime Momentum | **Rekomendasi** |
| §9 | Overlay funding/premium/OI | **Desain** |
| §10 | Arsitektur multi-strategi | **Desain** |
| §11 | Akuntansi Net-PNL | **Kerangka** |
| §12 | Backtest sadar-Mark-Price | **Metode** |
| §13 | Gerbang validasi ilmiah (DSR/PBO/CPCV) | **Metode** |
| §14 | Urutan build (13 langkah) | **Rencana** |
| §15 | Format laporan wajib | **Kerangka** |
| §16 | Keputusan akhir | **Kesimpulan** |
| §17 | Registry sumber (6 DOI + 8 doc SoDEX) | **Sumber** |

---

## 2. Yang BENAR dan Berharga — Kredit yang Memang Layak

Saya harus jujur: bagian-bagian ini **lebih baik daripada kebanyakan dokumen strategi** yang beredar.

| # | Kekuatan | Bukti |
|---|---|---|
| 1 | **Tidak mengklaim profit.** §1: *"Hermes must not assume profitability. Tidak ada paper peer-reviewed yang membuktikan Top-4 ini profitable secara langsung di SoDEX."* | Langka & benar |
| 2 | **Label semantik eksplisit** (VERIFIED / DESIGN / HYPOTHESIS / POLICY / PROHIBITED) | **Identik** dengan kerangka kita |
| 3 | **Semua 6 DOI sah** | 6/6 sudah terverifikasi di Master Evidence kita (1-Okt) — **tidak ada sitasi karangan** |
| 4 | **Fee cocok persis** | Perp taker 0,040% / maker 0,012% → **RT 8 bps** ✅ sama dengan catatan kita |
| 5 | **Funding per jam cocok** | Data kita: `funding_time_utc` naik per jam; terukur **0,125 bps/jam** ✅ |
| 6 | **Mark Price berbasis referensi global** | ✅ Persis temuan T1 kita: mesin kita punya **β 0,887** ke faktor global |
| 7 | **Kejujuran tentang #2**: *"this evidence is principally daily/weekly. A 1H/4H/8H SoDEX implementation is a new testable hypothesis"* | Benar & penting |
| 8 | **Kejujuran tentang #4**: *"combining risk-managed momentum with an UP→UP gate is our synthesis… a new hypothesis"* | Benar & penting |
| 9 | **Melarang optimasi akurasi/WR/Sharpe in-sample** (§1.1) | Benar |
| 10 | **Melarang fill SL di harga stop secara naif** (§12.1) | Benar — persis jebakan yang kita hindari |
| 11 | **Wajib DSR + PBO + purged/embargoed CV + cost stress 1,5×/2×** | **Selaras** G1–G8 kita |
| 12 | **Leverage hanya setelah edge tervalidasi**; *"No live-money promotion without explicit human approval"* | **Selaras** Red Lines kita |

**Kesimpulan bagian ini:** dokumen ini bukan dokumen sampah. Ia ditulis dengan disiplin. Masalahnya ada di **isi rekomendasi**, bukan di **cara berpikirnya**.

---

## 3. Deviasi dari Acuan Resmi ANANTARA

Acuan resmi kita (`ANANTARA_MASTER_Evidence_Research_Technical_Reference_V1.html`) menetapkan urutan prioritas riset:

| Prioritas | Acuan RESMI (V1) | Skor | Dokumen BARU | Selisih |
|---|---|---|---|---|
| **#1** | **Global Order Flow + Nonlinier ML** | **92/100** | #2 | **⬇️ turun 1** |
| **#2** | **Regime-Adaptive Trend / Breakout** | **87/100** | **#1** | **⬆️ naik 1** |
| #3 | Cross-Crypto Lead/Lag | (CORE) | **— HILANG —** | **❌ dibuang** |
| #4 | Risk-Managed + Regime-Conditioned Momentum | (CORE) | #4 | = |
| #5 | ProSP probability-tail | (NEW/recent) | **#3** | **⬆️ naik 2** |
| #6 | Basis + price-volume (family fitur) | (kandidat) | §9 overlay | = |

**Tiga deviasi, semuanya material:**

1. **#1 ↔ #2 ditukar.** Acuan resmi menilai **Order Flow 92** dan **Regime-Adaptive 87** — selisih 5 poin. Dokumen baru membalikkannya **tanpa menyebut skor apa pun dan tanpa menjelaskan alasan pembalikan.** Ini bukan kesalahan kecil: urutan menentukan apa yang dibangun lebih dulu, dan anggaran waktu kita terbatas.

2. **Cross-Crypto Lead/Lag dibuang seluruhnya.** Acuan resmi menyebutnya 11×, dan mencatat *"terbukti paling jelas pada minute-level"*. Membuangnya dari konteks **swing** sebenarnya **dapat dibela** (bukti menit-an tidak otomatis transfer ke swing) — tetapi dokumen baru **tidak menyebut penghapusan itu sama sekali**, apalagi alasannya. Penghapusan senyap = kehilangan jejak keputusan.

3. **ProSP naik #5 → #3.** Acuan resmi menandai ProSP sebagai *"sudah tersedia online pada 2026 tetapi **issue date-nya 15 Oktober 2026**"* — yaitu **10 hari setelah hari ini**. Dokumen baru menyebutnya "High but recent" (jujur, bagus) tetapi tetap menaikkannya dua peringkat.

> **Catatan penting:** dokumen baru mempersempit bahasa acuan resmi dari *"urutan = prioritas riset, BUKAN janji profit"* menjadi **"Final Top-4 Ranking"** dengan **"Build first / Build second / Build conditionally"**. Ini **meningkatkan kekuatan klaim** melampaui bukti yang mendasarinya — tepat jenis pergeseran yang mandatnya sendiri (§1) larang.

---

## 4. BENTURAN DENGAN BUKTI EMPIRIS INTERNAL — Bagian Terpenting

Ini inti analisis. Dokumen ini ditulis seolah kita mulai dari nol. Kita tidak.

### 4.1 ❌ Strategi #1 SUDAH DIBANGUN dan SUDAH GAGAL

Dokumen menempatkan **External-Regime Adaptive Trend/Breakout** sebagai **#1 — "Build first"**.

Reality check — infrastruktur itu **sudah ada dan sudah diuji**:

| Komponen dokumen | Padanan yang sudah ada di ekosistem | Status |
|---|---|---|
| "Global regime gate" | `_regime_gate_ok()`, `btc_regime()` | **Produksi** |
| "Local breakout signal" | `anantara/sodex_directional.py`, `sodex_signal.py` | **Ada** |
| "Regime engine" | `anantara/market_regime.py`, `regime_nowcast.py`, `directional_predictor.py` | **Ada** |
| "Vol gate" | `_entry_vol_gate(thr=2.0%)` | **Produksi** |
| "Dead zone / jam buruk" | `_entry_dead_zone_hour()` | **Produksi** |

**Hasil yang sudah kita peroleh:**

| Uji | Hasil |
|---|---|
| **T1 (track twoway)** | **FAIL struktural** |
| Akar masalah | **Eksposur faktor alt-vs-BTC, β = 0,887** — bukan biaya, bukan filter, bukan bug |
| Segmen S1 / S2 / S3 | −10,19 / +62,96 / **−28,40 bps** |
| S3 (terkini) | **RUGI −28,40 bps SEBELUM biaya** |
| Prediktor rezim ex-ante terbaik (D08) | `vol BTC ≥ median` → **+75,16 bps, p=0,0122** (lolos BH-FDR) |
| **Tapi di S3 terkini** | **−1,44 bps** → efeknya **terlalu kecil** vs biaya 19 bps |

> **Dokumen merekomendasikan "Build first" untuk sesuatu yang sudah kita bangun dan sudah gagal — tanpa menyebut kegagalan itu.**

Yang membuat ini bukan kebetulan: dokumen sendiri menyatakan (§2.1) bahwa SoDEX Index/Mark **bergantung pada informasi pasar global**. Itu **tepat** penyebab kegagalan T1 — karena semua peserta memakai referensi global yang sama, **arahnya tidak bisa menjadi alpha lokal**. Dokumen mengidentifikasi mekanismenya dengan benar, lalu **tidak menarik konsekuensinya**.

### 4.2 ❌ §4 (SLQS) = Menambah Gerbang di Atas Gerbang yang BELUM TERVALIDASI

Dokumen §4 mewajibkan gerbang likuiditas 6-komponen (SLQS) dengan bobot **yang dokumen sendiri akui belum diketahui** (`HYPOTHESIS`).

Kondisi gerbang kita sekarang:

| Fakta | Nilai |
|---|---|
| Gerbang produksi aktif | **3** (`_entry_vol_gate`, `_entry_dead_zone_hour`, `_regime_gate_ok`) |
| Tingkat blokir entry | **87,5%** |
| Uji setelah koreksi | **0 dari 12** CI95 mengecualikan nol |
| Putusan | **Belum tervalidasi** |
| Plus gerbang tracker: `pairs_pause` REAL-wide (ADA, ARB, DOGE…), SWING-PARTIAL (LIT), status `_REGIME: FLAPPING`, `_STANDBY: True` | — |

Menambahkan SLQS 6-bobot **tanpa metode validasi** berarti menumpuk gerbang yang belum terbukti di atas gerbang yang belum terbukti. Risikonya kongkret: blokir naik dari 87,5% ke arah yang lebih tinggi, sementara **tidak ada yang bisa membuktikan gerbang baru itu menambah edge** — karena alat untuk membuktikannya belum dipakai pada gerbang yang lama.

**Aturan yang benar:** validasi gerbang yang **sudah ada** dulu (protokol di `skill: signal-gate-falsification`), baru tambah.

### 4.3 ❌ Bottleneck TERBESAR yang Sudah Kita Ketahui TIDAK DISEBUT

Temuan internal kita, status **CONFIRMED**:

```
H1  CONFIRMED  n=732 trade SoDEX:
      median MFE      +1,087R   (puncak menguntungkan rata-rata)
      median realized −0,125R   (yang benar-benar didapat)
      52,2% posisi MENYENTUH +1R
      11,3% posisi RUGI sempat menyentuh +1R
    → bottleneck = CAPTURE (keluar), BUKAN SINYAL (masuk)
```

Artinya: **masalah utama kita bukan "sinyal entry kurang pintar" — tapi "profit yang sudah didapat tidak dipanen".** Estimasi kebocoran: **~1,2R per trade**.

Bukti pendukung terukur:
```
r(ATR%, SL-rate) = +0,750,  p_perm = 0,0006  (20.000 permutasi)
   → makin volatil pair, makin sering SL 1% tersentuh
Sizing TIDAK vol-aware → risiko efektif per trade naik seiring ATR
```

Dokumen §5.8 menyebut *"volatility-adjusted trailing stop"* — **satu butir dalam daftar**, tanpa bobot, tanpa kaitan ke temuan capture di atas. Padahal **PEAK_TRAIL** (temuan internal) bernilai **+1,80 pp/trade** — dan target kita hanya **0,80%/48 jam**. Satu perbaikan exit yang sudah terukur bernilai **>2× target**.

> **Kesimpulan:** dokumen mengoptimalkan **pintu masuk** (entry gates, strategi baru), sementara bukti terkuat kita menunjuk ke **pintu keluar**. Ini arah yang salah, dan berpotensi menghabiskan berbulan-bulan.

Saat ini pun sudah ada **A/B exit yang sedang berjalan** dengan kriteria pra-registrasi (n ≥ 30/arm) — `AB_REALWIDE_ATR_ARM_20260925` dan `AB_SWING_ATR_GEOMETRY_20260925`. Dokumen tidak menyebutnya.

### 4.4 ❌ Masalah KORELASI: #1 dan #4 adalah Faktor yang Sama

Target resmi kita (opsi B) mensyaratkan **6–8 mesin dengan korelasi antar-mesin ≤ 0,1** supaya Sharpe portofolio mencapai ~5,5–5,8.

Dokumen mengusulkan 4 strategi. Mari periksa independensinya:

| Strategi | Sifat | Faktor | Grup |
|---|---|---|---|
| #1 Trend/Breakout | directional, time-series | **TREND/MOMENTUM** | **A** |
| #4 Risk-Managed Momentum | cross-sectional, 2mgg formasi | **TREND/MOMENTUM** | **A** |
| #3 ProSP | cross-sectional prob-tail | sebagian **MOMENTUM** (fitur §7.7: *"multi-horizon return/momentum"*) | **A/lemah** |
| #2 Order Flow ML | informasi mikro-struktur | **ORDER FLOW** | **B** |

Di literatur, time-series trend dan cross-sectional momentum berkorelasi **~0,7–0,9**. Jadi dari 4 "mesin" dokumen, **realistisnya hanya ~2 faktor independen** (Trend/Momentum dan Order Flow) — dan #3 miring ke grup yang sama.

> **Konsekuensi aritmetika:** 2 mesin independen (bukan 6–8) → Sharpe portofolio ≈ SR × √2, bukan SR × √6–8. Kita **tidak akan mencapai** target lewat daftar ini, sekalipun keempatnya berhasil — karena keempatnya bukan empat taruhan berbeda.

Dokumen §10 memang memperingatkan *"Do not implement this ensemble first"* (bagus), tapi tidak pernah memeriksa **korelasi antar keempatnya** — padahal itu syarat kelayakan utama.

### 4.5 ❌ Overlay §9 Belum Bisa Dijalankan

Dokumen §3.1 menyatakan overlay **Funding + Premium + OI** *"must condition all strategies"* — wajib untuk semuanya.

| Komponen | Ketersediaan kita |
|---|---|
| Funding | ✅ 92 simbol — **tapi hanya ~2,5 hari riwayat** (5.612 baris; SoDEX tanpa endpoint historis) |
| Premium (perp−index) | ❌ **0 berkas** |
| Open Interest | ❌ 1 berkas saja, tanpa deret waktu |

Overlay yang **diwajibkan untuk semua strategi** tidak punya data untuk dijalankan. Dokumen tidak memeriksa ketersediaan data sama sekali.

---

## 5. Persoalan Numerik & Klaim Kuantitatif

### 5.1 Angka paper dipakai tanpa penanda "in-sample"

| Klaim dokumen | Disetahunkan | Persoalan |
|---|---|---|
| §8.1 — momentum 3,18%/minggu | **≈ 409%/tahun** | Ini angka **sampel riset**, bukan live. Dokumen menyebutnya apa adanya sebagai temuan paper, tapi menaruhnya di tabel ranking sebagai bukti pendukung |
| §8.1 — 3,47%/minggu (risk-managed) | **≈ 489%/tahun** | Sama |
| §6.1 — Sharpe long-short 3,61 | **≈ 217%/tahun** | Sharpe 3,61 adalah **ekstrem**; hampir selalu menyusut di luar sampel |

Dokumen §8.7 memang mencantumkan risiko *"small/illiquid winners can create fake backtest alpha"* — **jujur** — tetapi angka besar itu tetap berada di tabel bukti tanpa label "in-sample". Pembaca bisa salah menyimpulkan tingkat kelayakan.

### 5.2 Klaim "funding cap 4% per jam" perlu verifikasi

Dokumen §2.3: *"The funding cap documented by SoDEX is 4% per hour."*

Data kita: funding terukur **0,125 bps/jam** = 0,00125%. Cap 4%/jam berarti **3.200× lebih besar** dari yang teramati. Bisa jadi (a) batas stres teoretis, (b) salah baca dokumen, atau (c) salah satu satuan. **Tidak terverifikasi** — tandai `HYPOTHESIS`, jangan pakai sebagai asumsi.

### 5.3 Ketidaksesuaian internal: untung kecil vs target besar

Dokumen §4 (SLQS) dirancang untuk menyaring pasar dengan spread/depth yang baik. Tapi dokumen tidak pernah menghitung: **berapa trade/tahun yang tersisa setelah SLQS + hurdle net-edge + 3 gerbang kita?** Dengan 182 slot/48 jam setahun dan penyaringan berlapis (yang sudah memblokir 87,5%), jumlah trade yang benar-benar terjadi bisa turun di bawah ambang daya uji statistik. **Trade-off daya-uji vs selektivitas tidak dibahas.**

---

## 6. Analisis Kelayakan Target — Matematika

Target resmi: **0,8% dari TOTAL wallet per 48 jam.**

```
0,8% / 48 jam   =  0,40% / hari
disetahunkan    =  328% / tahun  (4,28× modal)
padanan Sharpe  ≈  5,5   (asumsi vol kripto 60%/tahun)
```

Biaya per trade 48 jam (dari data nyata kita):

| Komponen | Nilai | Sumber |
|---|---|---|
| Fee RT perp taker | **8,0 bps** | Dokumen §2.2 ✅ + catatan kita |
| Funding 48 jam @0,125 bps/jam | **6,0 bps** | Data kita, 92 simbol |
| Slippage/spread | ~5,0 bps | estimasi konservatif |
| **Total biaya** | **≈ 19,0 bps** | |
| **Bruto minimal agar NET 80 bps** | **≈ 99 bps per trade** | |

Jadi target menuntut **~99 bps gross per trade, konsisten, 182 kali setahun.**

Pembanding terhadap dokumen itu sendiri:

```
Sharpe long-short terbaik yang dokumen kutip (§6.1)  = 3,61
Sharpe yang dibutuhkan target kita                    ≈ 5,5
                                                       ──────
                                               target = 1,51× lebih tinggi
```

> **Target kita menuntut kita mengalahkan Sharpe terbaik dari paper terbaik yang dokumen sendiri kutip, sebesar 51%** — dan angka 3,61 itu sendiri sudah angka sampel riset.
>
> **Kabar baiknya:** target kita **bukan** "satu strategi Sharpe 5,5". Target kita dirancang lewat **diversifikasi**: 6–8 mesin pada Sharpe ~2,3 dengan korelasi ≤0,1 → Sharpe portofolio ≈ 2,3 × √6–8 ≈ 5,6–6,5. **Jadi syarat sesungguhnya bukan "cari strategi hebat" — melainkan "cari 6–8 strategi yang TIDAK saling berkorelasi".** Dan itulah tepatnya yang daftar Top-4 dokumen ini **gagal penuhi** (§4.4).

Ini kesimpulan paling penting dari seluruh analisis: **dokumen menyelesaikan masalah yang salah.**

---

## 7. Kesenjangan Data — Bisakah Rencana Ini Dieksekusi?

Dokumen §14 menetapkan urutan build 13 langkah. Langkah 1–6 adalah **infrastruktur data**. Status kita:

| Kebutuhan (dokumen §14) | Status kita | Kelengkapan |
|---|---|---|
| SoDEX raw recorder (trades, candles) | `orderflow_capture` — **hanya BTC/ETH/SOL, sumber Binance** | 🟡 25% |
| **bookTicker** | **0 berkas** | ❌ |
| **L2 / L4 book** | **0 berkas** | ❌ |
| **mark / index price** | **0 berkas deret waktu** (snapshot `perps_marks[92]` ada, tapi titik-titik bukan deret) | ❌ |
| funding | ✅ 92 simbol — **riwayat hanya ~2,5 hari** | 🟡 |
| **Open Interest** | 1 berkas, tanpa deret waktu | ❌ |
| tickers | sebagian | 🟡 |
| Binance reference recorder | sebagian (3 simbol) | 🟡 |
| **Hyperliquid reference** | **tidak ada** | ❌ |
| **SLQS + riwayat likuiditas/kapasitas** | **tidak ada** | ❌ |
| **Backtester sadar-Mark-Price + simulator fill berbasis depth** | **tidak ada** | ❌ |
| **Instrument master point-in-time** | **tidak ada** | ❌ |
| Cost engine + pemilih spot-vs-perp | sebagian (`sodex_funding_collector`) | 🟡 |

**Perkiraan kesiapan: ~25%.**

Implikasi konkret:

1. **#2 (Order Flow)** butuh flow lintas-venue (Binance + Hyperliquid + konfirmasi lokal SoDEX). Kita punya **3 simbol dari satu venue**. Dokumen §6.2 menggambarkan arsitektur 3-lapis yang **dua lapisnya belum kita rekam**.
2. **#3 (ProSP)** butuh **universe cross-sectional yang lebar dan likuid**. Kita punya 92 perp, tapi **belum tahu berapa yang lolos SLQS** — dan SLQS-nya sendiri belum dibangun. Dokumen §7.3 sudah memperingatkan hal ini (bagus).
3. **Overlay §9** mustahil: premium & OI tidak ada.
4. **§12 (backtest sadar-Mark-Price dengan fill berbasis depth)** butuh L2/L4 yang **tidak kita miliki**. Backtest kita saat ini tidak bisa memenuhi standar dokumen itu.

**Temuan tambahan:** data orderflow kita (`obi`, `cvd`, `trades`) berakhir `t=1791157331843` ≈ **5 Oktober 2026** — **SEGAR**. Ini kontras tajam dengan `sodex_model_server` yang datanya **beku 21-Mei** (D09). Jadi: **data flow kita segar; data model kita busuk.** Dua masalah berbeda yang sering tertukar.

---

## 8. Ketidakakuratan Teknis Spesifik (Butir demi Butir)

| # | Lokasi | Persoalan | Tingkat |
|---|---|---|---|
| 1 | §3 | #1↔#2 ditukar tanpa menyebut skor acuan resmi (92 vs 87) | **Tinggi** |
| 2 | §3 | Cross-Crypto Lead/Lag dihapus senyap (acuan resmi: CORE #3, 11 sebutan) | Sedang |
| 3 | §3 | ProSP naik #5→#3, padahal acuan resmi menandainya terbit 15-Okt-2026 (10 hari ke depan) | Sedang |
| 4 | §3/§16 | Mengubah "prioritas riset" menjadi "Final Ranking" + "Build first" — klaim lebih kuat dari bukti | **Tinggi** |
| 5 | §5 | #1 sudah dibangun (`_regime_gate_ok`, `sodex_directional.py`) dan sudah **FAIL** (T1, β 0,887) — tidak disebut | **Kritis** |
| 6 | §4 | SLQS menambah gerbang tanpa protokol validasi; gerbang lama (3) memblokir 87,5% dan **0/12 tervalidasi** | **Kritis** |
| 7 | §5.8 | Exit capture (bottleneck CONFIRMED, ~1,2R/trade) hanya jadi satu butir daftar; rantai kausal ke temuan internal tidak dibuat | **Kritis** |
| 8 | §3/§10 | Korelasi antar 4 strategi tidak diperiksa; #1 & #4 = faktor sama → tidak bisa memenuhi syarat ρ≤0,1 | **Tinggi** |
| 9 | §2.3 | "Funding cap 4%/jam" — 3.200× di atas funding teramati; tak terverifikasi | Sedang |
| 10 | §8.1 | 3,18%/minggu (≈409%/th) disajikan sebagai bukti tanpa label in-sample | Sedang |
| 11 | §3.1/§9 | Overlay "wajib untuk semua strategi" tanpa cek ketersediaan data (premium & OI = 0) | **Tinggi** |
| 12 | §14 | Urutan build tidak menyebut A/B exit yang **sedang berjalan** (`AB_*_ATR_*_20260925`, n≥30/arm, pra-registrasi) | Sedang |
| 13 | §4/§13 | Trade-off selektivitas vs daya uji tidak dibahas (berpotensi menekan n di bawah ambang statistik) | Sedang |
| 14 | §2.5 | Margin tier (40×/25×/20×) disebut **dengan benar** sebagai batas bursa, bukan leverage strategi — **ini akurat**, tapi tidak dikaitkan ke plafon nyata kita `LEVEL2_MARGIN_UTIL_CAP = 0,70` | Rendah |

---

## 9. Yang HARUS Diadopsi (Rekomendasi Konkret)

Saya memisahkan dengan tegas: **adopsi** vs **tolak**.

### ✅ ADOPSI — nilai tinggi, biaya rendah

| # | Tindakan | Alasan |
|---|---|---|
| A1 | **Adopsi §11–§13 sebagai standar pelaporan wajib** (akuntansi Net-PNL, backtest sadar-Mark, gerbang DSR/PBO/CPCV) | Selaras G1–G8 kita; menaikkan standar tanpa biaya arsitektur |
| A2 | **Adopsi §15 (format laporan strategi)** sebagai template baku keluaran riset SoDEX | Memudahkan perbandingan antar-mesin |
| A3 | **Adopsi §4.1 komponen SLQS sebagai DAFTAR FITUR** (bukan gerbang) — spread, depth, turnover, frekuensi trade, slippage, price-alignment | Fitur bagus untuk **diukur & dianalisis**, bukan untuk memblokir sebelum tervalidasi |
| A4 | **Adopsi §9 sebagai overlay KONTEKS & BIAYA** (bukan prediktor arah) — dokumen sendiri sudah menetapkan ini dengan benar | Persis postur yang benar |
| A5 | **Adopsi §12.1 (larangan fill SL di harga stop)** ke backtester kita | Mencegah ilusi hasil |
| A6 | **Naikkan #2 (Order Flow) ke prioritas #1** — sesuai acuan resmi | Bukti terkuat + kita punya 1,6 GB data segar |
| A7 | **Bangun recorder yang belum ada**: bookTicker, L2/L4, mark/index, OI | Prasyarat mutlak apa pun |

### ❌ TOLAK — untuk sekarang

| # | Tindakan | Alasan |
|---|---|---|
| T1 | **Jangan "Build first" #1 (Regime-Adaptive Trend/Breakout)** | Sudah gagal (β 0,887, S3 −28,40 bps sebelum biaya) |
| T2 | **Jangan tambah gerbang SLQS sebagai gerbang** | 3 gerbang lama belum tervalidasi (0/12) tapi sudah blokir 87,5%; tambah gerbang = memperburuk rasio sinyal/derau |
| T3 | **Jangan bangun #4 (Momentum) sebagai mesin independen** | Sekeluarga dengan #1; melanggar syarat ρ≤0,1 |
| T4 | **Jangan pakai #3 (ProSP) sebelum universe likuid terbukti** | Dokumen sendiri sudah mensyaratkan ini (§7.3) |
| T5 | **Jangan jadikan dokumen ini pengganti acuan resmi** | Menukar #1↔#2 dan menghapus Lead/Lag tanpa jejak keputusan |

### 🎯 URUTAN YANG SAYA USULKAN (berbeda dari dokumen)

```
PRIORITAS 0 — PANEN YANG SUDAH ADA (bukti terkuat, biaya terendah)
  ├─ Selesaikan A/B exit ATR (n≥30/arm sudah pra-registrasi, sedang jalan)
  ├─ Ukur ulang PEAK_TRAIL (+1,80 pp/trade) dengan protokol falsifikasi
  └─ Jadikan sizing vol-aware (bukti: r(ATR%,SL-rate)=+0,750, p=0,0006)
     → menyerang bottleneck CONFIRMED (capture, ~1,2R/trade)

PRIORITAS 1 — VALIDASI GERBANG YANG SUDAH ADA
  └─ Jalankan skill: signal-gate-falsification pada 3 gerbang produksi
     → tanpa ini, gerbang baru apa pun tidak bisa dinilai

PRIORITAS 2 — #2 ORDER FLOW (sesuai acuan resmi #1)
  ├─ Perluas recorder: Hyperliquid + SoDEX lokal + lebih banyak simbol
  └─ Ablation M0→M5 dokumen §6.4, biaya 1x/1,5x/2x, DSR

PRIORITAS 3 — INFRASTRUKTUR DATA
  └─ bookTicker, L2/L4, mark/index, OI (prasyarat untuk §12 & §9)

PRIORITAS 4 — kandidat mesin BARU yang benar-benar TIDAK berkorelasi
  └─ cari faktor di luar Trend/Momentum/Order Flow (mis. funding-carry,
     likuidasi, struktur basis) — inilah jalan ke 6-8 mesin ρ≤0,1
```

---

## 10. Keterbatasan Analisis Ini

Saya menyatakan batasnya secara terbuka:

1. **Tidak bisa memverifikasi DOI secara online.** Web dalam keadaan mati (HTTP 402 `insufficient_funds`). Namun **tidak diperlukan**: ke-6 DOI sudah ada di acuan resmi kita yang **sudah diverifikasi di Crossref pada 1-Okt-2026**. Yang bisa saya pastikan: **tidak ada sitasi karangan**.
2. **Tidak membaca isi paper aslinya.** Penilaian saya atas klaim paper (mis. Sharpe 3,61) terbatas pada **bagaimana dokumen mengutipnya**, bukan pada kebenaran paper itu sendiri.
3. **Korelasi antar-strategi (§4.4) adalah penilaian analitis**, bukan hasil pengukuran. Untuk mengukurnya perlu kurva ekuitas tiap strategi — dan itu memang bagian dari rekomendasi ini (bangun mandiri dulu, ukur korelasi, baru router).
4. **Saya tidak mengubah apa pun.** Analisis ini read-only terhadap produksi. `unfreeze = NO`, gate T1 utuh, target tidak diubah.

---

## 11. Verifikasi & Reprodusibilitas

| Item | Nilai |
|---|---|
| Dokumen objek | 38.580 byte · 784 baris · 13 bagian · 6 DOI |
| Acuan pembanding | Master Evidence V1 (98.727 B, 12 DOI) + V2 Supplement (19.444 B, 6 DOI) |
| DOI baru di dokumen | **0** (6/6 sudah ada di acuan) |
| Padanan modul yang diperiksa | `sodex_directional.py`, `market_regime.py`, `regime_nowcast.py`, `sodex_signal.py`, `sodex_governor.py`, `paper_test_twoway.py`, `paper_test_realwide.py`, `realwide_micro_live.py` |
| Data diperiksa | `orderflow_capture_*.jsonl` (1,6 GB, 3 simbol, s/d 5-Okt), `data/sodex_funding/funding_rates_history.jsonl` (5.612 baris, 92 simbol), `data/sodex_real_sync_snapshot.json` (92 perp) |
| Berkas A/B diperiksa | `docs/cex/AB_REALWIDE_ATR_ARM_20260925.md`, `docs/cex/AB_SWING_ATR_GEOMETRY_20260925.md` |
| Registry trial | `reports/sodex/sodex_trial_registry.json` — 31 entri |
| Produksi disentuh | **tidak** |

### Perintah reproduksi
```bash
# Peta dokumen
python3 -c "import re,sys; s=open('~/Downloads/ANANTARA_SoDEX_Swing_Strategies_FINAL_V1.html').read(); print(len(re.findall(r'<section id=',s)))"

# Overlap DOI
# (lihat skrip di lampiran laporan; 6/6 DOI dokumen ada di Master Evidence)

# Kelayakan target
python3 -c "print(f'{(1.008)**(365/2)-1:.1%} per tahun')"   # -> 328.1%
```

---

*D10 · Divisi SoDEX · Hermes Anantara v3 · 5 Oktober 2026*
*Berkas pendamping: `D07_RCA_FILTER_DAN_FAKTOR`, `D08_PREDIKTOR_REZIM_EXANTE`, `D09_FALSIFIKASI_MODEL_LIGHTGBM`*
