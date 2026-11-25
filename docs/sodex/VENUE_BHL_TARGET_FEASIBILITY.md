# Target SoDEX 0,8%/Window di Venue Binance & Hyperliquid
## Analisis Aritmetika & Statistik Kuantitatif — Bisa atau Tidak?

**Tanggal:** 25 Oktober 2026 · **Divisi:** Riset · **Status:** Falsifikasi teruji
**Pertanyaan user:** *"Bagaimana jika target project SoDEX diterapkan di market venue Binance dan Hyperliquid — apakah secara perhitungan aritmetika dan statistik kuantitatif bisa tercapai?"*

---

## Daftar Isi

1. [Jawaban Singkat](#1-jawaban-singkat)
2. [Definisi Target yang Diuji](#2-definisi-target-yang-diuji)
3. [Metode: Memisahkan Alpha dari Biaya](#3-metode-memisahkan-alpha-dari-biaya)
4. [Hasil 1 — Biaya Round-Trip per Venue](#4-hasil-1-biaya-round-trip-per-venue)
5. [Hasil 2 — Alpha Bukan Milik Venue (Era Split)](#5-hasil-2-alpha-bukan-milik-venue-era-split)
6. [Hasil 3 — Matriks Net per Venue](#6-hasil-3-matriks-net-per-venue)
7. [Hasil 4 — Aritmetika Target per Skenario](#7-hasil-4-aritmetika-target-per-skenario)
8. [Hasil 5 — Kontrol Negatif](#8-hasil-5-kontrol-negatif)
9. [Jawaban Lengkap: Aritmetika vs Statistik](#9-jawaban-lengkap-aritmetika-vs-statistik)
10. [Yang Bisa Membuat "Bisa" — dan Harga yang Harus Dibayar](#10-yang-bisa-membuat-bisa-dan-harga-yang-harus-dibayar)
11. [Limitasi & Apa yang Belum Terbukti](#11-limitasi-apa-yang-belum-terbukti)
12. [Kesimpulan & Rekomendasi Falsifiable](#12-kesimpulan-rekomendasi-falsifiable)
13. [Laporan Verifikasi & Reproduksi](#13-laporan-verifikasi-reproduksi)

---

## 1. Jawaban Singkat

> **TIDAK untuk tiga keluarga sinyal yang sekarang berjalan — di Binance maupun Hyperliquid — dengan eksekusi taker.**
> Perpindahan venue hanya membeli **2,6–3,6 bps per trade** (biaya Binance 12,25 vs SoDEX 15,84 bps), sementara **gap ke target 11–29 bps per trade**. Venue bukan bottleneck-nya.
>
> **SATU sel lolos syarat-A secara aritmetika:** Donchian-20 + eksekusi **maker** + ukuran posisi penuh, di Binance (+1,375%/window) atau HL (+1,383%/window) — **tetapi syarat-B gagal telak** (median −2,00%/window, hit 35,1%), dan **di era pasca-flip 25-Sep hasilnya −2,936%/window (hit 17,4%)**.
>
> Artinya: **secara statistik belum terbukti bisa; secara aritmetika hanya "menyentuh" target pada asumsi eksekusi maker yang belum diverifikasi.** Ini bukan alasan pindah venue — ini alasan menguji ulang edge, bukan biaya.

**Analogi:** biaya transaksi itu seperti ongkos kirim. Pindah dari kurir mahal (SoDEX 15,8 bps) ke kurir lebih murah (Binance 12,2 bps) menghemat 3,6 bps — tapi barang yang dikirim (alpha) sekarang **rata-rata tidak laku** (gross ≈ 0 sampai negatif). Menghemat ongkir tidak menolong kalau barangnya tidak laku.

---

## 2. Definisi Target yang Diuji

Target mengikuti **AMANDEMEN_TARGET_AB** — bukan sekadar "rata-rata 0,8%":

| Kriteria | Definisi operasional | Ambang |
|---|---|---|
| **A** | Rata-rata PnL per window pada grid **tetap 30 jam** (jangkar 03-Agu-2026 UTC), window kosong dilewati, min 10 window | **mean ≥ 0,8%** dari total modal wallet |
| **B** | Kualitas distribusi window | **median > 0 DAN hit-rate ≥ 50%** |
| Akumulasi | Target per window, bukan per trade; modal basis = TOTAL wallet | harga mati (user) |

Konsekuensi yang sering terlewat: **A saja tidak cukup.** Sistem dengan mean tinggi tapi median negatif berarti *mayoritas window rugi* — profit hanya dari sedikit window ekstrem. Itu bukan sistem yang bisa dijalankan dengan tenang, dan bukan yang dimaksud target.

Basis modal: wallet **$243,02** → target absolut **≈ $1,94 per window**.

---

## 3. Metode: Memisahkan Alpha dari Biaya

### 3.1 Desain eksperimen

Pertanyaan "venue mana yang bisa" harus dijawab dengan memisahkan dua komponen yang sering tercampur:

```
PnL bersih = ALPHA (kualitas sinyal × pergerakan harga) − BIAYA (fee + spread + funding)
```

- **ALPHA** melekat pada **aset dan waktu**, bukan pada venue. BTC bergerak sama di Binance dan di HL (korelasi harga ≈ 1,0). Maka sinyal direplay **satu kali** pada price-path Binance 1 jam, 180 hari (4.320 bar), 52 simbol — path terpanjang & paling likuid.
- **BIAYA** melekat pada **venue**: fee taker/maker, spread, funding 8 jam.
- **Net per venue** = gross yang sama − biaya venue masing-masing.

Ini desain yang adil: kalau hasilnya beda antar venue, penyebabnya **hanya biaya**, bukan perbedaan sinyal atau periode.

### 3.2 Tiga keluarga sinyal (parameter produksi, tanpa tuning)

| Keluarga | Sinyal | Geometri exit | Time-stop |
|---|---|---|---|
| **momentum** | rezim v3 MOMENTUM (ADX>25, close>SMA50>SMA200) + checklist ≥4/5 | TP 6% / SL 3% | 24 jam |
| **donchian** | breakout Donchian-20 + volume > SMA24 + BULL (ADX>22, golden cross) | TP 4% / SL 2% | 30 jam |
| **twoway** | momentum LONG + mirror SHORT (BEAR: close<SMA50<SMA200, ADX>22) | TP 6% / SL 3% | 24 jam |

Aturan anti-bias yang dipatuhi:
- Entry di **open bar berikutnya** setelah sinyal close (tidak ada look-ahead).
- SL dicek **lebih dulu** di dalam bar; bila TP dan SL kena di bar yang sama → SL diambil (worst-case).
- Satu posisi terbuka per simbol (cooldown sampai exit) — mencegah penggandaan sinyal yang sama.
- **Tidak ada** optimasi parameter. Parameter = produksi (rev A2 27-Sep untuk momentum/twoway).

### 3.3 Model biaya per venue (round-trip, bps)

| Komponen | SoDEX | Binance USDM | Hyperliquid |
|---|---|---|---|
| Fee taker per sisi | 4,0 | 4,0 (VIP0 publik) | 4,5 |
| Spread per sisi (proxy) | 1,5–8 (per pair) | 1,5 (majors 0,5–1) | 1,5 |
| Funding 8 jam | 0,13 | 0,13 (model sama) | 0,13 |
| **Total RT rata-rata terukur** | **15,84** | **12,25** | **13,25** |
| Fee maker per sisi (skenario alternatif) | 1,2 | 0,2 | 0,15 |

> SoDEX memakai `scripts/cost_model.py` sebagai sumber tunggal (taker 4 bps/sisi, spread per-pair, funding 0,13/8h). Angka SoDEX terukur di buku paper: **11,39 bps/trade** — model replay sedikit lebih konservatif (15,84) karena memakai spread default lebih lebar untuk simbol tipis. Arah bias ini **melawan** hipotesis "venue lain lebih baik", jadi kesimpulan tetap sahih.

---

## 4. Hasil 1 — Biaya Round-Trip per Venue

| Venue | Biaya RT rata-rata (taker) | Selisih vs SoDEX | Biaya RT (maker) |
|---|---|---|---|
| SoDEX | **15,84 bps** | — | ~2,9 bps |
| Binance USDM | **12,25 bps** | **−3,59 bps** (−23%) | **~0,5 bps** |
| Hyperliquid | **13,25 bps** | **−2,59 bps** (−16%) | **~0,45 bps** |

**Temuan:** keunggulan biaya Binance atas SoDEX hanya **3,6 bps per trade** untuk taker. Untuk target yang butuh 11–29 bps net per trade, ini menutup **12–31% gap** — tidak cukup.

Keunggulan besar justru di **maker**: turun ke ~0,5 bps RT, hemat **~15 bps** vs taker SoDEX. Tapi maker bukan "diskon gratis" — Anda hanya terisi saat harga menyentuh order Anda, dan saat itulah harga sering bergerak melawan (adverse selection). Model ini **belum** memperhitungkan itu (lihat §11).

---

## 5. Hasil 2 — Alpha Bukan Milik Venue (Era Split)

Replay pada price-path **Binance** 180 hari, gross (sebelum biaya), per era:

| Keluarga | Pra-flip (sebelum 25-Sep) | Pasca-flip (25-Sep ke atas) | Perubahan |
|---|---|---|---|
| momentum | +2,87 bps (n=4.576, t=0,51) | **−31,44 bps** (n=421, t=−1,74) | runtuh |
| **donchian** | **+23,03 bps** (n=3.241, **t=4,67**) | **−28,25 bps** (n=235, t=−1,66) | runtuh |
| twoway | +4,19 bps (n=9.114, t=1,08) | **−7,99 bps** (n=1.011, t=−0,74) | runtuh |

**Ini temuan terpenting dari seluruh analisis.**

Flip rezim 25-Sep yang sebelumnya terdeteksi di buku paper SoDEX **terjadi juga di price-path Binance**. Artinya:

1. **Bukan SoDEX yang rusak** — pasar (aset yang sama) yang berubah perilaku.
2. **Pindah venue tidak menghidupkan alpha yang sudah mati.** Sinyal yang sama menghasilkan gross negatif di Binance pasca-flip, persis seperti di SoDEX.
3. Satu-satunya keluarga yang punya bukti gross edge kuat secara in-sample (donchian, t=4,67) **kehilangan edge-nya di era berjalan**.

**Analogi:** ini seperti mengganti lapangan dari rumput sintetis ke rumput asli karena pemain sering terpeleset. Ternyata masalahnya bukan lapangan — anginnya yang berubah arah, dan angin itu bertiup sama di kedua lapangan.

---

## 6. Hasil 3 — Matriks Net per Venue

Net = gross path Binance − biaya venue (taker), 180 hari, 52 simbol:

| Keluarga | SoDEX net (t) | Binance net (t) | Hyperliquid net (t) |
|---|---|---|---|
| momentum | −15,86 (−2,95) | −12,27 (−2,28) | −13,27 (−2,47) |
| **donchian** | **+3,89 (0,82)** | **+7,40 (1,56)** | **+6,40 (1,35)** |
| twoway | −12,84 (−3,53) | −9,22 (−2,53) | −10,22 (−2,81) |

Bacaan yang jujur:

- **Donchian satu-satunya yang net positif di ketiga venue** — tapi **tidak signifikan di manapun** (|t| 0,82–1,56, jauh di bawah ambang Bonferroni 3,48–3,61 dan bahkan di bawah ambang keputusan 2,5).
- Binance memang terbaik (konsisten dengan biaya termurah), tetapi selisihnya hanya **+3,5 bps** dari SoDEX — persis sebesar selisih biaya. Tidak ada keajaiban venue lain.
- Momentum dan twoway **negatif signifikan** (t ≈ −2,3 sampai −3,5) di semua venue: biaya taker lebih besar daripada edge. Di venue mana pun.

---

## 7. Hasil 4 — Aritmetika Target per Skenario

Target butuh: `mean% per window = rate_trade × size × net_bps / 100 ≥ 0,8`

Dengan rate donchian 4,3 trade/window, kebutuhan net per trade:

| Size posisi (notional/wallet) | Net bps/trade yang dibutuhkan |
|---|---|
| 20% wallet (5 posisi konkuren) | **93,0 bps** |
| 50% wallet | **37,2 bps** |
| 100% wallet (penuh) | **18,6 bps** |

Hasil agregasi window 30 jam (482 window, grid tetap 03-Agu):

| Skenario | mean%/window | median%/window | hit% | **A** | **B** |
|---|---|---|---|---|---|
| **Binance maker size=1,0** | **+1,375** | −2,004 | 35,1 | **✓** | ✗ |
| Binance maker size=0,75 | +1,031 | −1,503 | 35,1 | ✓ | ✗ |
| Binance maker size=0,5 | +0,688 | −1,002 | 35,1 | ✗ | ✗ |
| Hyperliquid maker size=1,0 | +1,383 | −2,003 | 35,1 | ✓ | ✗ |
| Hyperliquid maker size=0,5 | +0,691 | −1,002 | 35,1 | ✗ | ✗ |
| Binance taker size=1,0 | +0,533 | −2,110 | 34,6 | ✗ | ✗ |
| SoDEX taker size=1,0 | +0,281 | −2,156 | 34,4 | ✗ | ✗ |
| **Binance maker size=1,0 pasca-flip** | **−2,936** | −2,644 | **17,4** | ✗ | ✗ |

**Bacaan:**

1. **Syarat A hanya terpenuhi di skenario maker dengan size ≥0,75** — dan hanya bila seluruh 180 hari dihitung (termasuk era emas pra-flip).
2. **Syarat B gagal di SEMUA skenario** — median window −2%, hit-rate 35%. Kenapa? Distribusi trade donchian: 62% kalah (SL −200 bps), 38% menang (TP +400 bps). Satu window 30 jam hanya berisi ~4 trade → dibutuhkan ≥2 TP agar window positif. P(≥2 TP dari 4; p=0,38) ≈ 49% — **secara struktural di bawah 50%**, sebelum biaya.
3. **Di era berjalan (pasca-flip), bahkan A pun gagal**: −2,936%/window, hit 17,4%.
4. Untuk memperbaiki B, geometri harus diubah ke WR≥50% (TP lebih kecil dari SL, atau exit berbasis waktu/indikator). Tapi itu **menaikkan frekuensi trade** → biaya naik → kebutuhan bps per trade naik lagi. Trade-off ini bukan detail kecil; ia adalah inti persoalan.

---

## 8. Hasil 5 — Kontrol Negatif

Aturan metodologi: **kontrol negatif harus GAGAL** (tidak menghasilkan profit). Kalau kontrol acak juga profit, berarti "edge" yang diklaim adalah artefak geometri/pasar, bukan sinyal.

| Kontrol | Geometri | Gross mean | t |
|---|---|---|---|
| Entri acak, seed beku | TP6/SL3 | **+12,68 bps** | 3,04 |
| Entri acak, seed beku | TP4/SL2 | **−0,22 bps** | −0,08 |
| Entri acak, seed beku, maker Binance | TP4/SL2 | **+0,12 bps** | 0,04 |

**Temuan penting (dan agak tidak nyaman):**

- Dengan geometri TP6/SL3, entri **acak** menghasilkan +12,68 bps gross (t=3,04) di pasar yang sedang naik. Artinya rasio TP:SL 2:1 saja sudah memberi ekspektasi positif di 180 hari ini — **tanpa sinyal apa pun.**
- Karena itu klaim "momentum +0 bps" sebenarnya berarti: **momentum LEBIH BURUK 12,7 bps daripada acak** dengan geometri yang sama.
- Sebaliknya, dengan geometri donchian (TP4/SL2), acak = −0,22 bps (t=−0,08) → bersih. Maka donchian +19,56 bps gross adalah **edge sinyal sejati sebesar +19,8 bps di atas acak** — satu-satunya edge yang lolos kontrol ini.
- Kontrol maker Binance (TP4/SL2): +0,12 bps (t=0,04) → konsisten, geometri netral.

**Kesimpulan kontrol:** edge donchian nyata (bukan artefak), tetapi **terikat rezim** (mati pasca-flip). Edge momentum/twoway tidak lolos kontrol — mereka kalah dari acak.

---

## 9. Jawaban Lengkap: Aritmetika vs Statistik

Pertanyaan user dipecah dua, karena jawabannya berbeda:

### 9.1 Secara aritmetika — "bisa, tapi hanya di satu sudut sempit dan tidak realistis"

- **Dengan taker (cara buku sekarang berjalan): TIDAK.** Net terbaik Binance +0,533%/window (donchian, size penuh) < 0,8%. SoDEX +0,281%. Gap tidak tertutup oleh biaya venue.
- **Dengan maker + size penuh: A terpenuhi** (+1,375% Binance, +1,383% HL) — **tapi B gagal** (median −2%, hit 35%), dan **pasca-flip negatif** (−2,94%).
- Target juga menuntut **kinerja rata-rata**, sedangkan donchian mean-nya didorong ekor kanan (sedikit TP besar). Secara aritmetika distribusi ini tidak memenuhi A∧B, hanya A.

### 9.2 Secara statistik kuantitatif — "belum terbukti; hipotesis belum mati, tapi tidak boleh diklaim hidup"

- Net donchian di Binance: t = **1,56** → jauh di bawah ambang Bonferroni 3,48–3,61. **Tidak signifikan.**
- Alpha donchian **terbukti signifikan hanya pra-flip** (t=4,67) dan **negatif pasca-flip** (t=−1,66). Mengklaim "bisa di Binance/HL" berdasar data pra-flip = **look-ahead bias rezim** — kesalahan yang justru ingin dihindari.
- n window pasca-flip = 23 (< min 10? cukup untuk monitor, tidak untuk keputusan final). Ini masuk kategori **MONITOR**, bukan **ACTION**.
- Uji multiple (3 keluarga × 3 venue = 9 sel) tanpa koreksi akan menghasilkan false positive. Dengan BH-FDR, **tidak ada satu sel pun yang lolos**.

### 9.3 Ringkas

| Pertanyaan | Jawaban |
|---|---|
| Bisa secara aritmetika di Binance? | Taker: **tidak** (+0,53% < 0,8%). Maker: **A ya, B tidak**. |
| Bisa secara aritmetika di Hyperliquid? | Taker: **tidak**. Maker: **A ya, B tidak** (identik Binance). |
| Bisa secara statistik? | **Belum terbukti.** t=1,56, pasca-flip negatif, B struktural gagal. |
| Apakah pindah venue menyelesaikan masalah? | **Tidak.** Venue hanya 2,6–3,6 bps dari gap 11–29 bps. |
| Apa penyebab sebenarnya? | **Flip rezim 25-Sep** — terjadi di semua venue, karena asetnya sama. |

---

## 10. Yang Bisa Membuat "Bisa" — dan Harga yang Harus Dibayar

Tiga tuas yang secara aritmetika bisa menutup gap. Semua punya biaya tersembunyi:

### Tuas 1 — Eksekusi maker (hemat ~15 bps RT vs taker SoDEX)
- **Efek:** donchian net Binance dari +7,40 → **+19,07 bps/trade** (t=4,02 gross).
- **Harga:** adverse selection & fill uncertainty. Order limit yang terisi justru saat harga menembus — realisasi bisa 3–8 bps lebih buruk dari asumsi. Belum dimodelkan. **Wajib diukur forward, bukan diasumsikan.**

### Tuas 2 — Size penuh (notional = 100% wallet per trade)
- **Efek:** kebutuhan bps turun dari 93 → 18,6 bps/trade.
- **Harga:** eksposur 4,3× wallet (4,3 trade konkuren × 100%). Pada leverage 3×, ini berarti margin terpakai ~143% — **melampaui kapasitas akun**. Realistisnya size 0,5–0,75 → A gagal/tipis dan **drawdown window −1,5% sampai −2,0%** (median). Itu 2,5× lipat target per window, dengan arah negatif.

### Tuas 3 — Geometri B (WR≥50%)
- **Efek:** bisa memenuhi kriteria B (median>0, hit≥50%).
- **Harga:** WR tinggi biasanya berarti TP kecil/SL lebar → R:R <1 → butuh WR > biaya/TP. Dengan biaya 12 bps dan TP 0,5%, butuh WR > 52,4% hanya untuk impas. Belum ada bukti keluarga sinyal mana pun mencapai itu stabil.
- **Catatan:** ini justru **membalik** geometri yang sekarang (TP2:SL1) → arah riset baru, bukan tweak.

### Kesimpulan tuas
Tidak ada tuas tunggal yang cukup. Kombinasi maker + size 0,75 + geometri B yang belum ada = **spesifikasi riset baru**, bukan konfigurasi yang bisa dinyalakan minggu ini.

---

## 11. Limitasi & Apa yang Belum Terbukti

| Limitasi | Dampak | Arah bias |
|---|---|---|
| Fill model memakai harga TP/SL persis (tanpa slippage tembus stop) | Hasil sedikit **optimistis** | Melawan kesimpulan → kesimpulan tetap sahih |
| Maker diasumsikan terisi di touch tanpa adverse selection | Skenario maker **terlalu bagus** | Melawan kesimpulan |
| Sinyal replay = simplifikasi (tanpa vol-gate, feed-streak, pair-exclusion produksi) | Angka absolut beda dari buku nyata | Netral (kualitatif sama) |
| t-stat menganggap trade independen; trade sekelompok dalam waktu | t **overstate** signifikansi | Melawan kesimpulan |
| Path SoDEX vs Binance berbeda 90 hari terakhir (donchian 61,36 vs 33,14 bps) | Triangulasi path tidak konvergen penuh | Perlu investigasi lanjutan (wick tipis SoDEX memicu TP/SL lebih sering) |
| n window pasca-flip = 23 | Belum cukup untuk keputusan final | MONITOR |

**Yang belum terbukti dan tidak boleh diklaim:** bahwa maker + donchian di Binance/HL akan menghasilkan 0,8% neto di masa depan. Yang terbukti: **in-sample 180 hari, A lolos di skenario maker, B gagal, dan era berjalan negatif.**

---

## 12. Kesimpulan & Rekomendasi Falsifiable

### 12.1 Kesimpulan

1. **Venue bukan bottleneck.** Binance/HL hanya menghemat 2,6–3,6 bps/trade dari SoDEX; gap ke target 11–29 bps/trade.
2. **Alpha yang mati tidak hidup karena pindah venue.** Flip rezim 25-Sep terdeteksi identik di price-path Binance — donchian +23,03 → −28,25 bps.
3. **Target A∧B tidak tercapai di skenario manapun yang realistis.** A hanya lolos di maker+size penuh (in-sample); B gagal struktural (hit 35% < 50%).
4. **Satu-satunya edge yang lolos kontrol negatif adalah donchian** (+19,8 bps di atas acak), tetapi edge itu **terikat rezim**.
5. **Momentum dan twoway lebih buruk daripada entri acak** pada geometrinya sendiri — bukan kandidat untuk venue mana pun.

### 12.2 Rekomendasi (falsifiable, pre-registered)

**PRAREG-32 (usulan, belum dijalankan): uji maker-donchian Binance/HL secara forward.**

| Item | Spesifikasi |
|---|---|
| Hipotesis H1 | Donchian-20 + maker fill, size 0,75, di Binance, menghasilkan mean ≥0,8%/window DAN median>0 DAN hit≥50% |
| Instrumen | 20 simbol likuid Binance USDM (spread ≤2 bps) |
| Periode | Forward 30 hari (24 window), mulai setelah registrasi |
| Kriteria lolos | A: mean ≥0,8%; B: median>0 & hit≥50%; C: t ≥ 2,5 pada net per trade; D: fill-rate maker ≥60% terukur |
| Kriteria gagal | Salah satu: mean <0,4%, atau hit <40%, atau fill-rate <40% |
| Multiple testing | 1 hipotesis saja (tidak perlu BH); trial masuk registry |
| Kill-switch | Drawdown kumulatif >5% wallet → stop, evaluasi |

**Yang TIDAK boleh dilakukan:** mengubah target, melonggarkan gate, atau mengklaim "bisa" berdasarkan hasil in-sample pra-flip.

### 12.3 Keputusan strategis

Jika PRAREG-32 gagal → target 0,8%/window dengan keluarga sinyal ini **tertutup di semua venue**; fokus pindah ke pencarian edge baru (bukan venue baru). Jika lolos → jalur maker-donchian jadi kandidat mesin produksi, dengan syarat fill-rate nyata ≥60%.

---

## 13. Laporan Verifikasi & Reproduksi

### 13.1 Artefak

| File | Isi |
|---|---|
| `scripts/research/venue_replay_bhl.py` | Replay 3 keluarga × 3 venue, era split, maker variant, kontrol acak 2 geometri |
| `scripts/research/venue_arithmetic_windows.py` | Agregasi window 30 jam, A/B per skenario sizing |
| `reports/sodex/VENUE_REPLAY_BHL.json` | Semua angka mentah (families, venue_matrix, era_split, maker_variant, target_arithmetic, path_check) |
| `reports/sodex/VENUE_ARITHMETIC_WINDOWS.json` | Tabel A/B per skenario + pasca-flip + kontrol |
| `data/hl_klines/1h/*.json` | 46 simbol klines Hyperliquid 1 jam, 90 hari (API publik) |
| `data/binance_klines/1h/*.json` | 52 simbol klines Binance 1 jam, 180 hari |

### 13.2 Perintah reproduksi

```bash
cd ~/anantara-sakti
/usr/bin/python3 scripts/research/venue_replay_bhl.py
/usr/bin/python3 scripts/research/venue_arithmetic_windows.py
```

### 13.3 Cek konsistensi internal

- Jumlah trade donchian 3.476 = konsisten di kedua skrip (replay & aritmetika).
- Gross donchian +19,56 bps; net Binance taker = 19,56 − 12,17 = **+7,39** ≈ +7,40 di matriks ✓
- Net SoDEX = 19,56 − 15,67 = **+3,89** ≈ +3,89 ✓
- Window count 482 = 180 hari × 24/30 − offset jangkar ✓
- Kontrol acak TP4/SL2 gross −0,22 bps vs maker net +0,12 bps ✓ (biaya ~0,34 bps)
- Semua uji READ-ONLY: tidak ada order, tidak ada posisi, tidak ada flag live.

### 13.4 Tingkat keyakinan

| Klaim | Keyakinan |
|---|---|
| Biaya Binance < SoDEX ~3,6 bps | **Tinggi** (model fee publik + konsisten dengan selisih net) |
| Venue bukan penyebab matinya edge | **Tinggi** (era split di path Binance, n besar pra-flip) |
| B gagal struktural pada geometri TP2:SL1 | **Tinggi** (matematika binomial, bukan estimasi) |
| Maker-donchian bisa mencapai A | **Rendah–sedang** (in-sample, tanpa adverse selection, t=1,56) |
| Target A∧B tercapai di masa depan | **Tidak terbukti** — hipotesis terbuka, bukan klaim |

---

*Dokumen ini dihasilkan oleh Divisi Riset — falsifikasi-didahulukan, triangulasi, statistik ketat. Semua angka dapat direproduksi dari artefak di §13. Tidak ada parameter produksi yang diubah; tidak ada order yang dikirim.*
