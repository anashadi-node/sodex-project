# Rencana Paralel A/B — Target Berjenjang & Pencarian Edge Efek Besar
**SoDEX · 24 Oktober 2026 · status: read-only, tidak ada perubahan kode trading**

---

## 1. Ringkasan (baca ini dulu)

- **Tidak ada edge netto yang lolos uji** pada seluruh keluarga yang diuji hari ini. Gerbang live tetap **DITUTUP**.
- **Jalur A** = target berjenjang yang bisa dipertanggungjawabkan secara statistik, dan **berfungsi untuk modal berapa pun** (parameter, bukan konstanta).
- **Jalur B** = pencarian keluarga edge dengan efek per-trade besar (≥100 bps) — satu-satunya jenis edge yang bisa dibuktikan dengan jumlah trade yang realistis.
- **Temuan paling penting hari ini**: angka "t=5,7" pada bounce 1 jam ternyata **artefak spread**. Gross +20,6 bps < spread implisit median 26,2 bps → net **−25 bps**. Ini persis jenis jebakan yang membuat strategi terlihat hebat di backtest lalu rugi di live.
- **Tangga modal**: dengan $243 atau $500 **tidak ada** konfigurasi yang bisa dibuktikan secara ekonomi. Dengan $1.000–$2.000 hanya jalur hold 72 jam. Dengan **$5.000** jalur hold 24 jam (sesuai mandat 1–30 jam) mulai bisa dibuktikan.

---

## 2. Jalur A — Target berjenjang

### 2.1 Tiga tingkat target

| Tier | %/30 jam | %/tahun (simple) | Sharpe tahunan yang dibutuhkan @vol 20 / 30 / 40 / 60% | Status |
|---|---|---|---|---|
| **T1 North Star** | 0,80% | 234% | 11,68 / 7,79 / 5,84 / 3,89 | harga mati, tidak diubah |
| **T2 Operasional** | 0,25% | 73% | 3,65 / 2,43 / 1,82 / 1,22 | diusulkan (butuh approval) |
| **T3 Lantai** | 0,10% | 29% | 1,46 / 0,97 / 0,73 / 0,49 | diusulkan (fase awal) |

**Analogi.** T1 itu seperti menargetkan lari 100 m di bawah 9 detik. Boleh tetap dipasang di dinding sebagai cita-cita, tapi Anda tidak boleh menyusun program latihan harian seolah-olah 9 detik sudah pasti tercapai. T2/T3 adalah target latihan yang membuat kemajuan bisa diukur.

### 2.2 Rumus inti: edge per trade yang wajib ada

```
edge_netto_per_trade (bps) = target_per_window × 10.000 / (leverage × turnover_per_window)
turnover_per_window = 30 / hold_hours
```

Dengan leverage 2×:

| Tier | hold 1 jam | hold 6 jam | hold 24 jam | hold 72 jam |
|---|---|---|---|---|
| T1 0,80% | 1,3 bps | 8,0 bps | **32,0 bps** | **96,0 bps** |
| T2 0,25% | 0,4 bps | 2,5 bps | 10,0 bps | 30,0 bps |
| T3 0,10% | 0,2 bps | 1,0 bps | 4,0 bps | 12,0 bps |

**Ini angka yang paling penting di seluruh dokumen.** Target 0,8% pada hold 24 jam berarti setiap trade harus menghasilkan **32 bps bersih setelah fee dan setelah spread**. Bukan 32 bps bruto — 32 bps **netto**.

Pembanding nyata: mesin swing terbaik yang pernah diukur menghasilkan **+3,04 bps bruto** (≈ −5,7 bps netto pada biaya 8,8 bps). Jarak ke syarat T1 adalah **faktor 10** dalam arah yang salah.

### 2.3 Yang berubah dan yang tidak berubah ketika modal naik

| Besaran | Ikut modal? | Penjelasan |
|---|---|---|
| $ per window | **Ya, linear** | 0,8% × modal. $243 → $1,94; $2.000 → $16,00 |
| % per window | **Tidak** | target persentase tidak berubah oleh ukuran modal |
| Sharpe yang dibutuhkan | **Tidak** | ditentukan target dan volatilitas, bukan modal |
| Edge netto per trade | **Tidak** | hanya bergantung target, leverage, turnover |
| Biaya spread per trade | **Tidak** | ditentukan likuiditas pair |
| Jumlah posisi bersamaan | **Ya** | 1 posisi per ~$333, maksimum 10 |
| Diversifikasi (Sharpe portofolio) | **Ya** | Sharpe naik ≈ √(N₂/N₁) bila edge per trade tetap |
| Biaya fee relatif untuk membuktikan edge | **Ya, turun** | fee% = n × biaya × leverage / N |

**Analogi.** Menaikkan modal itu seperti memperbesar kapal. Ia menambah daya angkut dan membuat kapal lebih stabil (diversifikasi), tetapi **tidak menambah kecepatan angin**. Kalau anginnya nol, kapal besar tetap tidak bergerak — hanya lebih mahal.

### 2.4 Tangga modal — konfigurasi yang bisa dibuktikan

Kriteria "bisa dibuktikan" = biaya fee untuk menjalankan eksperimen ≤ 50% modal.

| Modal | Posisi | Notional/posisi | Konfigurasi yang bisa dibuktikan |
|---|---|---|---|
| $243 | 1 | $486 | **TIDAK ADA** |
| $500 | 2 | $500 | **TIDAK ADA** |
| $1.000 | 3 | $667 | T1 @ hold 72 jam (fee 48% modal) |
| $2.000 | 6 | $667 | T1 @ hold 72 jam (fee 24% modal) |
| $5.000 | 10 | $1.000 | **T1 @ hold 24 jam** (fee 44%) + hold 72 jam |
| $10.000 | 10 | $2.000 | T1 @ hold 24 jam + hold 72 jam |

Catatan penting: hold 72 jam **di luar mandat 1–30 jam** yang berlaku sekarang. Jadi:

- **Untuk menguji T1 di dalam mandat (hold ≤30 jam), tiket modalnya ≈ $5.000.**
- Dengan $1.000–$2.000, satu-satunya jalur uji T1 adalah hold 72 jam → butuh amandemen horizon (keputusan Anda, bukan keputusan saya).

### 2.5 Aturan naik/turun tingkat

```
T3 aktif  → naik ke T2 bila: 3 window berturut ≥ T3 DAN t-stat ≥ 2,0 DAN DD < 10%
T2 aktif  → naik ke T1 bila: 6 window berturut ≥ T2 DAN t-stat ≥ 2,5 DAN DD < 15%
T1 aktif  → itu hanya boleh setelah edge T1 terbukti OOS, bukan setelah 6 window bagus
Turun     → 2 window berturut < 0 → turun satu tingkat
Berhenti  → DD ≥ 20% modal → semua posisi ditutup, evaluasi ulang
```

### 2.6 Yang dilarang (jalur A)

- Menaikkan frekuensi untuk mengejar nominal. Volume bukan target.
- Menambah notional per posisi melebihi `leverage × modal / N`.
- Mengaktifkan live tanpa satu hipotesis yang lulus gerbang §3.5.
- Mengubah T1 (0,8%) tanpa keputusan eksplisit Anda.

---

## 3. Jalur B — Pencarian edge efek besar

### 3.1 Hukum biaya: edge harus melewati fee **dan** spread

```
biaya_nyata_per_trade (bps) = fee_taker 2 leg (5,6) + spread_implisit_pair
```

Spread implisit diukur dengan estimator Roll dari data 1 jam (bukan asumsi):

| Statistik spread implisit (94 pair) | Nilai |
|---|---|
| median | **26,2 bps** |
| p25 | 11,2 bps |
| p75 | 43,2 bps |
| p90 | 63,4 bps |
| maksimum (CASHCAT) | 147 bps |
| pair dengan Roll **terukur** < 6 bps | **4 pair**: BCH 2,8 · SOL 3,4 · BNB 3,6 · TRX 5,0 |
| pair dengan Roll **tak terdefinisi** (cov ≥ 0) | **17 pair** — biaya tidak terukur; wajib diperlakukan mahal, bukan murah |

**Aturan biaya terkunci.** Biaya per pair = **fee taker + maksimum(Roll sepanjang sampel, spread snapshot L2)**. Snapshot L2 mengukur satu momen likuiditas; Roll mengukur biaya rata-rata sepanjang tahun. Memakai yang lebih kecil akan melahirkan edge palsu — itu yang terjadi pada LIT (0,6 bps vs 57,4 bps).

**Konsekuensi.** Setiap hipotesis yang efek brutonya < ~30 bps di pair menengah **secara otomatis gugur** — bukan karena sinyalnya salah, tapi karena spread memakan seluruh edge. Ini menjelaskan kenapa seluruh mesin swing negatif: mereka bertaruh pada gerakan 3–100 bps di instrumen dengan pintu masuk 26 bps.

**Analogi.** Anda mencari uang logam di jalan. Di jalan sepi (pair likuid) ongkos masuknya 1 sen. Di jalan ramai (pair tipis) ongkos masuknya 26 sen. Sebagian besar "edge" yang ditemukan adalah uang logam 20 sen di jalan yang ongkosnya 26 sen.

### 3.2 R01 — Cascade reversal (pre-registered, FAIL)

**Hipotesis.** Setelah gerakan 1 jam ≥5%, harga berbalik karena overshoot likuidasi.

**Pre-registrasi.** `data/prereg/R01_cascade_reversal.criteria.json`, SHA-256 `f8303827a4fa3deb…`, dikunci sebelum mean dihitung. Hanya n dan σ yang dipakai untuk power analysis.

**Power analysis (sebelum uji).** n = 1.446 event non-overlap, σ = 580 bps, MDE(80%) = 43 bps < ambang ekonomi 100 bps → **terpower, layak diuji**.

**Hasil.**

| Sampel | n | gross | net (biaya 8,8 bps) | t | CI95 blok-harian |
|---|---|---|---|---|---|
| Semua | 1.446 | +29,0 bps | +20,2 bps | +1,32 | [−21, +56] |
| IS 60% | 867 | — | +27,1 bps | +1,29 | — |
| **OOS 40%** | **579** | — | **+9,8 bps** | **+0,45** | — |

Kriteria lulus: OOS ≥ 100 bps **dan** t ≥ 1,96. Hasil: **GAGAL**. Keluarga ditutup, dilarang re-tuning threshold/horizon pada dataset ini.

### 3.3 R01b — Bounce 1 jam: contoh sempurna jebakan spread

Pada threshold 3% dan hold 1 jam, hasil awal terlihat spektakuler:

| Versi uji | n | net | t | CI95 blok-harian |
|---|---|---|---|---|
| Biaya datar 8,8 bps (entry close) | 9.052 | **+15,1 bps** | **+5,69** | [+8, +22] |
| Biaya datar 8,8 bps (entry open berikutnya) | 9.052 | +15,1 bps | +5,69 | [+8, +22] |
| **Biaya nyata: fee 5,6 + spread Roll per pair** | **7.824** | **−25,0 bps** | — | **[−37, −14]** |
| Biaya nyata, OOS 40% | 3.130 | −35,1 bps | — | [−51, −18] |
| Biaya nyata, subset 21 pair "murah" (16 di antaranya biaya tak terukur → biaya dirender terlalu rendah, jadi ini batas atas) | 1.504 | −20,2 bps | — | [−35, −5] |

**Kesimpulan.** Gross +20,6 bps < spread median 26,2 bps. Yang terukur bukan edge, melainkan **pantulan bid-ask** — dan untuk memanennya Anda harus menjadi pihak yang mengutip harga, bukan pihak yang menyeberang. Dengan fee taker 5,6 bps dan spread 26 bps, menyeberang dua kali berarti membayar 31 bps untuk memanen 20 bps.

**Pelajaran yang dikunci menjadi aturan.** Setiap uji edge wajib memakai biaya per-pair, bukan konstanta. Ini akan mencegah pengulangan kesalahan yang sama.

### 3.3b Uji ulang pada pair yang biayanya benar-benar terukur

Setelah koreksi data (17 pair dengan Roll tak terdefinisi dikeluarkan), uji diulang pada 9 pair yang biayanya terukur — BTC, ETH, SOL, BNB, BCH, TRX (Roll) + CL, LIT, HYPE (spread dari L2):

| Varian | n | gross | biaya | net | t | CI95 blok-harian | OOS net | OOS t |
|---|---|---|---|---|---|---|---|---|
| \|3%\| H=6 jam | 530 | +29,3 | 7,0 | **+22,4 bps** | 1,37 | **[−14, +61]** | +15,6 | 0,62 |
| \|3%\| H=3 jam | 619 | +23,7 | 6,9 | +16,8 bps | 1,38 | [−9, +43] | +23,1 | 1,21 |
| \|2%\| H=6 jam | 1.308 | +19,0 | 7,1 | +11,9 bps | 1,34 | [−11, +32] | +13,8 | 0,98 |
| \|5%\| H=6 jam | 89 | +24,0 | 6,8 | +17,2 bps | 0,36 | [−95, +126] | +5,1 | 0,06 |

**Status: bukan edge — kandidat yang belum lulus.** Tiga alasan:

1. **Semua CI95 memuat nol.** Titik estimasi positif, tapi tidak bisa dibedakan dari kebetulan.
2. **Konsentrasi ekstrem.** Pada \|3%\| H=6, LIT menyumbang 267 dari 530 trade (+39 bps); BCH −30 bps, SOL −11 bps, HYPE −5 bps.
3. **Post-hoc.** Subset ini dipilih *setelah* melihat hasil, jadi tidak boleh diklaim sebagai temuan. Kalau mau diuji serius, harus masuk registry sebagai R08 dengan prereg baru dan uji forward — bukan di-deploy.

Yang bisa dikatakan secara jujur: pada pair likuid, arah efeknya **berbeda** dari pair tipis (reversal vs continuation). Itu petunjuk riset, bukan izin trading.

### 3.3c Uji konfirmasi R08 — prereg terkunci, hasil: TUTUP

Prereg `R08_liquid_reversal_replication.criteria.json`, SHA-256 `55732fbb93079f73…`, dikunci **sebelum** uji. Tujuh kriteria, semua wajib. Hasil:

| Kriteria | SoDEX (discovery) | Binance (replikasi) | Status |
|---|---|---|---|
| K1 replikasi venue: net > 0 & CI95 > 0 | +22,4 bps, CI [−14, +61] | **−40,2 bps, CI [−72, −10]** | **GAGAL** |
| K2 tiga segmen positif | +73,8 / **−13,7** / +7,0 | −4,9 / −41,9 / −73,8 | **GAGAL** |
| K3 t ≥ 3,0 | t = 1,37 | t = −2,79 | **GAGAL** |
| K4 konsentrasi pair ≤ 40% | LIT = **61%** | LITUSDT = 43% | **GAGAL** |
| K5 kontrol arah (50 seed) | 4% seed menang | **30% seed menang** | GAGAL di Binance |
| K6 kontrol entry acak ≤ 0 | −6,6 bps | −35,9 bps | LULUS |
| K7 daya: n ≥ n_required | 530 vs **2.201** | 713 vs tidak tercapai | **GAGAL** |

**Penyebab utama kegagalan: estimasi biaya LIT salah.** Snapshot L2 satu waktu memberi spread 0,6 bps; estimator Roll sepanjang satu tahun memberi **57,4 bps** (Binance 64,5 bps). Dengan biaya yang benar:

| Asset | SoDEX gross | Roll 1 tahun | Net benar | Binance gross | Roll | Net |
|---|---|---|---|---|---|---|
| LIT | +45,0 | **57,4** | **−18,0** | +18,2 | 64,5 | −56,3 |
| BTC | +73,8 (n=10) | n/a | +68,2 | −41,3 | 10,2 | −61,5 |
| SOL | −2,0 | 3,4 | −11,1 | +9,1 | 24,7 | −25,7 |
| HYPE | +2,2 | 39,3 | −42,7 | −18,6 | 38,4 | −67,0 |
| BNB | +125,3 (n=13) | 3,6 | +116,1 | +69,3 | 11,6 | +47,7 |
| ETH | +28,7 | n/a | +23,1 | −29,5 | n/a | −39,5 |
| BCH | −21,3 | 2,8 | −29,7 | −29,4 | n/a | −39,4 |

Hanya BNB yang positif di kedua venue — dengan n=13 di SoDEX, itu **bukan bukti**, itu kebetulan yang belum punya daya.

**Aturan baru yang dikunci.** Biaya per pair = **maksimum** dari (a) Roll sepanjang sampel dan (b) spread snapshot L2 — bukan snapshot saja. Snapshot satu waktu mengukur satu momen likuiditas, bukan biaya yang akan Anda bayar sepanjang tahun.

**Keputusan: R08 TUTUP.** Tidak ada re-tuning. Keluarga reversal dinyatakan selesai di kedua arah (cascade dan bounce).

### 3.3d R07 diuji — likuidasi paksa tidak dibalik, justru dilanjutkan

R07 selama ini disebut "satu-satunya pintu dengan efek ≥100 bps". Uji ini menutupnya, dan sekaligus menemukan sesuatu yang lebih kecil tapi nyata.

**Definisi event (beku, prereg `19433e49bcef39b8…`):** OI Binance turun ≥2% dalam 15 menit **dan** dominasi taker satu sisi (rasio ≤0,55 atau ≥1,80). Arah trade = fade. Entry open 1 jam berikutnya, exit +1/2/4/8 jam. Biaya per pair.

**Hasil, 1.044 event (2025-09 → 2026-10, 12 simbol):**

| Horizon | SoDEX net | t | Binance net | t |
|---|---|---|---|---|
| 1 jam | **−20,7 bps** | −5,52 | **−36,8 bps** | −8,48 |
| 2 jam | −14,5 | −2,74 | −30,1 | −5,02 |
| 4 jam (utama) | −7,7 | −1,07 | −27,2 | −3,50 |
| 8 jam | −19,1 | −2,04 | −30,9 | −3,08 |

Kontrol arah: 0% seed mengalahkan efek di SoDEX (16% di Binance). Kontrol entry acak: −22,6 bps. Konsentrasi ENA 33%.

**Yang penting bukan angka negatifnya, tapi tandanya yang konsisten di dua venue dengan arah sama.** Membalik hipotesis (kontinuasi, bukan fade) memberi **+13,7 bps bruto pada 1 jam** dengan **t = +5,52** — signifikan, tapi setelah biaya 7,0 bps hanya tersisa **+6,7 bps net**, dan efeknya hilang di 4 jam.

**Kenapa tidak boleh langsung dipakai.** Arah ini ditemukan dari data yang sama yang sudah dilihat. Menukar tanda setelah melihat hasil adalah data mining. Prereg R09 dikunci sekarang (`R09_forced_flow_continuation.criteria.json`) dan hanya mengizinkan klaim setelah **n≥60 event baru** terkumpul.

**Collector sudah hidup** (`anantara-forced-flow.service`, aktif 24-Okt 09:32 WIB): OI Binance per **15 detik** (bukan 5 menit seperti arsip), event OI collapse, dan mid SoDEX pada saat event +30s/+1m/+5m/+15m/+1j/+4j. Alasannya: histori 1m SoDEX tidak bisa di-backfill (endpoint trades tanpa paginasi, klines 1m tidak tersedia), jadi harga pasca-event harus direkam saat kejadian. Self-test jalur follow-up lulus (spread BTC terukur 0,124 bps pada saat uji).

### 3.4 Registry hipotesis

| ID | Hipotesis | Efek yang diharapkan | Status | Alasan |
|---|---|---|---|---|
| R01 | Cascade reversal 6 jam | 100–300 bps | **TUTUP** | OOS +9,8 bps, t=0,45 |
| R01b | Bounce 1 jam | 24 bps bruto | **TUTUP** | netto −25 bps setelah spread nyata |
| R02 | Session-open tokenized equity | 50–150 bps | **TUTUP** | spread nama equity 100+ bps; hanya 5 pair likuid yang tidak punya sesi |
| R03 | Funding ekstrem → reversal | 20–50 bps | **TUTUP** | median 0,125 bps/jam; jauh di bawah noise |
| R04 | Basis lintas venue (SoDEX–Binance) | 10–30 bps | **TUTUP** | korelasi 0,9815; lag ±1 jam ≈ 0 |
| R05 | Fade listing baru | 200–500 bps | **DITUNDA** | hanya 6 listing baru → n terlalu kecil, MDE ≫ efek |
| R06 | Market making / maker | spread | **TUTUP** | spread 0,1–1,1 bps < maker fee 2,28 bps |
| R07 | **Event-driven on-chain flow** | 100–400 bps | **TUTUP (fade)** | diuji 1044 event: fade −20,7 bps t=−5,52; lihat §3.3d |
| R08 | Reversal pair likuid \|3%\|/6 jam (post-hoc) | +22 bps | **TUTUP** | gagal 6 dari 7 kriteria; lihat §3.3c |
| R09 | Kontinuasi setelah de-leveraging paksa | +13,7 bps (post-hoc) | **FORWARD** | inversi R07; collector hidup, butuh n≥60 baru; lihat §3.3d |

**Tidak ada lagi hipotesis dengan efek ≥100 bps yang bisa diuji.** Yang tersisa hanya R09 (+6,7 bps net, menunggu data forward) dan R05 (ditunda karena n terlalu kecil). Konsekuensinya harus dikatakan apa adanya: pada 60 jendela 30 jam yang sudah terealisasi, capaian rata-rata **−1,36% per jendela** terhadap modal $244 — bukan 0,8%.

### 3.5 Gerbang universal (enam syarat, semua wajib)

```
G1  gross ≥ fee + 2 × spread_Roll(pair)          margin 2x, bukan impas
G2  OOS t ≥ 2,0 dan CI95 blok-harian seluruhnya > 0
G3  konsentrasi top-3 pair ≤ 50% dari total PnL absolut
G4  bertahan pada entry open bar berikutnya (bukan hanya harga cetak)
G5  n ≥ n_required sehingga MDE ≤ 1/2 efek yang diharapkan
G6  kriteria dikunci + SHA-256 sebelum mean dihitung
```

Tidak ada pengecualian. Satu hipotesis yang gagal satu syarat = tutup.

---

## 4. Posisi hari ini terhadap target

| Ukuran | Nilai terukur | Syarat T1 (hold 24 jam) | Selisih |
|---|---|---|---|
| Edge netto per trade | −5,7 bps (swing) | +32,0 bps | **−37,7 bps** |
| Drawdown paper (swing) | −$554 pada akun $243 | < 20% modal | **11x melewati batas** |
| Drawdown paper (twoway) | −$328 pada akun $243 | < 20% modal | **6,7x melewati batas** |
| Konsistensi | 1 dari 3 bulan positif | 6 window berturut | belum mulai |

**Artinya.** Bukan "hampir sampai". Selisihnya bukan faktor 1,2 yang bisa ditutup dengan tuning; ini faktor 10 pada edge dan faktor 11 pada risiko.

---

## 5. Keputusan yang diminta

1. **Tier operasional**: pilih T2 (0,25%) atau T3 (0,10%) sebagai target aktif fase ini, dengan T1 tetap sebagai North Star yang tidak diubah.
2. **Tiket modal**: jika ingin menguji T1 di dalam mandat 1–30 jam, dibutuhkan ±$5.000. Jika modal dijaga $1.000–$2.000, satu-satunya jalur adalah hold 72 jam → butuh amandemen horizon.
3. **Penutupan keluarga R01–R06**: setujui status tutup dan larangan re-tuning.
4. **R07**: setujui pembangunan collector on-chain flow (biaya: storage + waktu 6–8 minggu) sebagai satu-satunya jalur B yang tersisa — atau setujui kill total untuk B.

Sampai empat hal di atas diputuskan, tidak ada perubahan kode maupun konfigurasi trading.

---

## 6. Lampiran — metode & reproduksibilitas

**Data.** `data/sodex_klines/1h/*.json` (94 pair, median 6.524 bar, span 2025-10-28 → 2026-10-23), field `o/h/l/c/v/q`. Volume quote tersedia sehingga likuiditas per event bisa diukur.

**Spread implisit.** Estimator Roll: `s = 2·√(−cov(rₜ, rₜ₋₁))`, dalam bps, per pair, minimum 500 bar. Bila cov ≥ 0, spread dilaporkan 0 (konservatif ke arah biaya rendah).

**Power analysis.** `MDE = 2,8 × σ / √n` (α=0,05 dua sisi, power 80%). `n_required = (2,8σ/edge)²`.

**Bootstrap.** Blok harian, 1.200–2.000 resampel, CI persentil 2,5/97,5 — untuk menangani korelasi silang antar pair pada jam yang sama.

**Reproduksi.**

```bash
python3 scripts/sodex_capital_plan.py --capital 2000          # rencana & tangga
python3 scripts/sodex_capital_plan.py --capital 5000 --json   # machine-readable
sha256sum data/prereg/R01_cascade_reversal.criteria.json      # f8303827a4fa3deb…
```

**Berkas terkait.**
- `data/prereg/R01_cascade_reversal.criteria.json` + `.sha256`
- `scripts/sodex_capital_plan.py`
- `docs/sodex/PLAN_AB_PARALEL_2026-10-24.md` (dokumen ini)

**Batas kejujuran.** Semua uji di atas memakai harga close/open bar, bukan VWAP, dan tidak memodelkan antrean order. Pada pair likuid dengan spread <6 bps, kesalahan model ini kecil (1–3 bps). Pada pair tipis, angka netto bisa lebih buruk dari yang dilaporkan, bukan lebih baik.
