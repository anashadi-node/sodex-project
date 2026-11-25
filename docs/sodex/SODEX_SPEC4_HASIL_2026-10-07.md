# SODEX SPEC4 — HASIL (mikro-struktur menit & lintas-venue) — 2026-10-07

**Status: SELESAI. VERDICT FORMAL: GAGAL — 0 dari 13 sel hipotesis lulus.**
Pra-registrasi beku: `docs/sodex/SODEX_SPEC4_PRAREG_2026-10-07.md`.
Harness: `scripts/sodex_spec4_micro.py`. Kalibrasi: `tests/test_sodex_spec4_harness.py` (9/9 lulus).

---

## 1. Ringkasan satu paragraf (bahasa awam)

Kami menguji dua cara "mencuri start" di SoDEX pada resolusi **1 menit**: (H9) menebak arah
SoDEX dari gerakan Binance yang lebih dulu bergerak, dan (H10) membaca **arus order** SoDEX
sendiri (beli vs jual) untuk menebak harga 15–60 menit ke depan. Hasilnya: **nol**. Net hasil
tiap sel = **−8,0 bp**, yaitu persis sama dengan biaya transaksi bolak-balik. Artinya sinyalnya
**tidak mengandung informasi apa pun** tentang harga berikutnya. Uji kalibrasi memperkuat ini:
panel **sintetis random-walk** (yang secara desain tidak punya edge) menghasilkan angka yang
**tidak bisa dibedakan** dari run nyata (−8,03 vs −8,01 bp).

## 2. Tabel lengkap — 13 sel hipotesis (keluarga BH, m=13)

Semua nilai dalam bp (1 bp = 0,01%). `net_bp` sudah dikurangi biaya **base** 8 bp round-trip.

| Kode | n_rebal | hari | net_bp | CI95 | stress (16bp) | p | top_share | OOS stress | Gerbang gagal |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| H9_k1_H5 | 116.941 | 137 | −8,13 | [−8,2, −8,0] | −16,13 | 1,000 | 0,34 | −16,09 | c2,c3,c4,c5,c6 |
| H9_k1_H15 | 38.979 | 137 | −8,05 | [−8,3, −7,8] | −16,05 | 1,000 | 0,34 | −16,25 | c2,c3,c4,c5,c6 |
| H9_k1_H60 | 9.744 | 137 | −8,25 | [−9,3, −7,2] | −16,25 | 1,000 | 0,38 | −16,57 | c2,c3,c4,c5,c6 |
| H9_k5_H5 | 116.941 | 137 | −8,11 | [−8,2, −8,0] | −16,11 | 1,000 | 0,33 | −16,15 | c2,c3,c4,c5,c6 |
| H9_k5_H15 | 38.979 | 137 | −8,37 | [−8,6, −8,1] | −16,37 | 1,000 | 0,34 | −16,45 | c2,c3,c4,c5,c6 |
| H9_k5_H60 | 9.744 | 137 | **−8,64** | [−9,7, −7,6] | −16,64 | 1,000 | 0,34 | −16,95 | c2,c3,c4,c5,c6 |
| H9_k15_H5 | 116.935 | 137 | −8,08 | [−8,2, −8,0] | −16,08 | 1,000 | 0,34 | −16,14 | c2,c3,c4,c5,c6 |
| H9_k15_H15 | 38.979 | 137 | −8,09 | [−8,4, −7,8] | −16,09 | 1,000 | 0,34 | −16,17 | c2,c3,c4,c5,c6 |
| H9_k15_H60 | 9.744 | 137 | −8,59 | [−9,6, −7,5] | −16,59 | 1,000 | 0,35 | −18,16 | c2,c3,c4,c5,c6 |
| H10_W15_H15 | 36.186 | 137 | −8,01 | [−8,3, −7,7] | −16,01 | 1,000 | 0,34 | −16,06 | c2,c3,c4,c5,c6 |
| H10_W15_H60 | 9.040 | 137 | **−7,64** | [−8,8, −6,5] | −15,64 | 1,000 | 0,37 | −15,40 | c2,c3,c4,c5,c6 |
| H10_W60_H15 | 36.390 | 137 | −8,26 | [−8,5, −8,0] | −16,26 | 1,000 | 0,34 | −16,02 | c2,c3,c4,c5,c6 |
| H10_W60_H60 | 9.091 | 137 | −9,40 | [−10,5, −8,4] | −17,40 | 1,000 | 0,38 | −16,28 | c2,c3,c4,c5,c6 |

**Sel terbaik (H10_W15_H60)** — *edge kotor* = net + biaya = **+0,36 bp**, dengan CI95 kotor
**[−0,8, +1,5] bp**. Jadi batas atas edge yang bisa kami klaim dari seluruh 13 sel ≈ **+1,5 bp**.

### Komposisi keluarga sebenarnya (35 baris di JSON — semuanya gagal)

`reports/sodex/sodex_spec4_20261007.json` memuat **35 baris**, bukan 13:

| Kelompok | Jumlah | net_bp | verdict |
|---|---:|---|---|
| **Sel hipotesis (keluarga BH, m=13)** | 13 | −8,01 … −9,40 (≈ **−8 bp = persis biaya 1×**) | **semua False** |
| Kontrol F-a (sinyal dibalik / fade) | 13 | −6,60 … −8,36 (≈ −8 bp juga) | semua False |
| Mode market-neutral 2-leg (H9) | 9 | −15,51 … −16,24 (≈ **−16 bp = biaya 4 sisi**) | semua False |

**Semua 35 baris `verdict = False`**, dan **semua** `p = 1,000`. Tidak ada satu pun sel — termasuk
varian 2-leg — yang punya edge kotor di atas biayanya. (Superlatif gross terbesar di seluruh
keluarga, +1,40 bp, muncul di sel *fade* `H10_W60_H60_FADE` — yaitu arah **terbalik** — dan ia
masih di dalam noise, CI memuat nol.)

### Mode market-neutral H9 (2-leg, 9 sel — informasi saja, bukan gerbang)
| Kode | net_bp | stress |
|---|---:|---:|
| H9_k1_H5_MN | −15,99 | −23,99 |
| H9_k1_H15_MN | −15,99 | −23,99 |
| H9_k1_H60_MN | −16,24 | −24,24 |
| H9_k5_H5_MN | −15,99 | −23,99 |
| H9_k5_H15_MN | −16,03 | −24,03 |
| H9_k5_H60_MN | −15,85 | −23,85 |
| H9_k15_H5_MN | −15,98 | −23,98 |
| H9_k15_H15_MN | −16,01 | −24,01 |
| H9_k15_H60_MN | −15,51 | −23,51 |

Biaya 4 sisi (16 bp) membuat mode ini kalah **bahkan sebelum** edge dihitung — konsisten dengan
"tidak ada edge": net = −16,0 bp berarti edge kotor ≈ 0 pada setiap sel.

### Sensitivitas slippage (sel terbaik H10_W15_H60)
| Slippage tambahan per sisi | net_bp |
|---|---:|
| +0 bp | −7,64 |
| +1 bp | −9,64 |
| +2 bp | −11,64 |
| +5 bp | −17,64 |
| maker (1,2 bp/sisi) | −13,24 |

Tidak ada skenario biaya di mana sel ini positif.

## 3. Kontrol negatif F-a..F-c — semuanya lulus syarat

| Kode | Kontrol | Syarat | Hasil |
|---|---|---|---|
| F-a | sinyal dibalik (fade) | harus ≤ 0 | **0/13 fade positif** → OK |
| F-b | tanda sinyal diacak per blok 60 menit dalam simbol-hari | p > 0,05 | **6/6 p > 0,05** (0,087 … 0,737) → OK |
| F-c | panel sintetis random-walk | tidak boleh lulus | **0/13 lulus** → OK |

F-c sangat penting: run sintetis menghasilkan **−8,03 bp** vs run nyata **−8,01 bp**
(pada H9_k1_H5). Artinya harness **tidak mampu membedakan data nyata dari random walk** —
sebuah cara keras untuk menyatakan "tidak ada edge untuk dideteksi".

## 4. Daftar deviasi dari pra-registrasi (dibuka, bukan disembunyikan)

Pra-registrasi melarang pelonggaran. Semua deviasi di bawah adalah **pengetatan atau
koreksi kepatuhan**, dan semuanya diterapkan **sebelum** hasil nyata dibaca:

| # | Pasal | Isi pra-reg | Yang benar-benar dijalankan | Sifat |
|---|---|---|---|---|
| D1 | §1 Data | tape mencakup 92 simbol | **Hanya BTC/ETH/SOL** yang punya transaksi di jendela IS (BTC $2,1 M, ETH $1,0 M, SOL $470 jt selama Jun–Agu 2026). Simbol lain nol transaksi | **menyempitkan** |
| D2 | §1 Universe | "median notional/menit ≥ $100 dan ≥30% menit punya trade" (ambigu) | Diartikan: median dihitung **atas menit yang bertransaksi**; ditambah kolom coverage. Angka mentah dilaporkan di §5 | klarifikasi |
| D3 | §2 H10 | hold H ∈ {15, 60} | Implementasi awal saya memakai {5, 15, 60} (6 sel). **Ditemukan & diperbaiki jadi 4 sel** sebelum hasil nyata dibaca → m = 13 sesuai §4 | **menyempitkan** |
| D4 | §4 | CI95 tiap sel | Awalnya tidak dihitung; ditambahkan | kepatuhan |
| D5 | §3 | sensitivitas slippage +0/+1/+2/+5 bp/sisi | Ditambahkan (tabel §2) | kepatuhan |
| D6 | §6 c1 | `n_rebal ≥ 300` **dan ≥ 60 hari** | Awalnya hanya n; ditambah syarat hari | **menyempitkan** |
| D7 | §6 c6 | net > 0 di OOS pada biaya **stress** | Awalnya memakai biaya base; diperbaiki ke stress | **menyempitkan** |
| D8 | §4 | dedup pasangan (simbol × hari) | Pada resolusi menit dengan `stride = H` tidak ada jendela yang dipakai ulang; satu (simbol, hari) memang muncul beberapa kali karena resolusi menit. Aturan itu ditulis untuk studi jendela harian (H5/ALT3) | klarifikasi |
| D9 | §7 | "Tidak menyentuh OOS sebelum keputusan IS dibekukan" | Harness menghitung **IS dan OOS dalam satu run**, jadi OOS terpakai sebelum keputusan IS dibekukan terpisah. **Ini pelanggaran prosedur dan saya akui.** Dampak material: **nol** — IS dan OOS keduanya −8,0 bp (base) / −16 bp (stress) di 13 sel, jadi keputusan tidak bergantung pada OOS. Di putaran berikutnya gerbang OOS dipisah menjadi perintah `--final` terpisah dan tidak dijalankan sampai IS dibekukan | **pelanggaran prosedur** |

**Tidak ada** ambang yang disetel ulang setelah melihat hasil. **Tidak ada** varian yang
ditambah setelah hasil keluar.

## 5. Aturan universe, diterapkan apa adanya (dari IS saja)

Median notional per menit **yang bertransaksi** dan coverage menit (IS = 2026-05-24 … 2026-08-31):

| Simbol | menit bertransaksi | median notional/menit | coverage | total notional IS |
|---|---:|---:|---:|---:|
| BTC-USD | 119.909 | $1.069 | 93,7% | $2,14 M |
| ETH-USD | 118.318 | $530 | 92,4% | $1,01 M |
| SOL-USD | 99.028 | $312 | 77,4% | $470 jt |
| ZEC-USD | 759 | $82 | 0,6% | $3,9 jt |
| SILVER-USD | 759 | $49 | 0,6% | $3,0 jt |
| *semua 87 simbol lain* | 0 | — | 0% | $0 |

→ Universe hasil filter = **{BTC-USD, ETH-USD, SOL-USD}** (3 simbol).

### ⚠️ KOREKSI WAJIB: ini keterbatasan TAPE, bukan fakta pasar

Tabel di atas adalah cakupan **tape collector kita**. Itu **bukan** bukti bahwa 87 simbol
lain tidak diperdagangkan. Bukti yang berlawanan ada di data milik venue sendiri:
`reports/sodex/UNIVERSE_SODEX_1D.json` (dibuat dari klines harian venue) menunjukkan
puluhan simbol dengan volume nyata — AAVE-USD ≈ $699 rb/hari, ARB-USD ≈ $965 rb/hari,
AVAX-USD ≈ $87 rb/hari — dan panel harian dipakai di studi lain memuat **76 nama**.

Artinya tape menit kita (yang mengambil dari feed trades global) **hanya menangkap 3 nama
teraktif**; sisanya tidak terekam. Konsekuensinya untuk kesimpulan SPEC4:

- H10 (order-flow native) **hanya teruji pada 3 simbol — karena tipe kita hanya punya 3**,
  bukan karena 89 simbol lain tidak likuid. Vonis "tidak ada edge order-flow" berlaku untuk
  BTC/ETH/SOL, **bukan** untuk seluruh venue.
- H9 (lead-lag) juga terbatas pada 3 simbol, walau argumen likuiditas tidak sekuat H10
  (lead-lag butuh harga kontinu, dan hanya 3 simbol yang punya harga menit kontinu).

Ini kelemahan cakupan yang harus diperbaiki sebelum mengklaim apa pun tentang venue secara
keseluruhan. Perbaikannya = perluas langganan collector (bukan analisis baru).

**Konsekuensi gerbang c5 yang jujur:** gerbang **c5** (share satu simbol ≤ 30%) secara
struktural sulit dipenuhi dengan 3 simbol — tiap simbol menyumbang ~33%. Di run nyata
`top_share` = 0,33–0,38, jadi c5 gagal **bahkan kalau** edge-nya ada. Ini bukan alasan untuk
melonggarkan c5; itu artinya arsitektur apa pun yang diuji di universe 3-simbol akan ditolak
oleh gerbang ini sampai cakupan simbol bertambah. Dilaporkan apa adanya.

## 6. Yang sebenarnya membunuh target: rasio biaya-terhadap-edge

Ini temuan terpenting, dan bukan soal arsitektur.

- Target: **0,8% per 48 jam = 80 bp per 48 jam**.
- Biaya SoDEX taker: **8 bp round-trip** (4 bp/sisi).
- Edge kotor terbaik yang terukur dari 13 sel: **≈ +0,4 bp per posisi** (batas atas CI95 ≈ +1,5 bp).

Diperlukan edge kotor per posisi sebesar `8 + 80/N` bp, dengan N = jumlah round-trip per 48 jam:

| N (round-trip / 48 jam) | Edge kotor minimum per posisi |
|---:|---:|
| 1 | 88 bp |
| 2 | 48 bp |
| 4 | 28 bp |
| 8 | 18 bp |
| 16 | 13 bp |
| 48 | 9,7 bp |

Sementara yang tersedia **≈ 0,4 bp**. Selisihnya ± **20×–200×**, dan **bertanda salah** — jadi
**tidak ada frekuensi trading yang bisa menutupnya**. Menambah jumlah trade hanya memperbesar
kerugian (biaya 8 bp, edge 0,4 bp → tiap trade merugi 7,6 bp).

**Implikasi jujur:** target 80 bp/48 jam hanya masuk akal pada **horizon jam-ke-hari**
(memegang posisi untuk menangkap gerakan 50–100 bp), karena di situ biaya 8 bp hanya
memakan ~10% dari target, bukan 20×. Itu **sesuai North Star SoDEX (swing 1–30 jam)** —
dan justru berarti putaran menit ini menguji horizon yang salah untuk target tersebut.
Konsekuensinya keras: pada horizon jam-ke-hari, tiap observasi butuh jam-berhari-hari,
sehingga **jumlah episode independen** — bukan ide strategi — yang menjadi penyumbat.

## 7. Kesalahan arsitektur saya (diakui, spesifik)

Kritik "masalahnya arsitektur, bukan strategi" **benar sebagian**, dan bagian itu milik saya:

1. **ALT3** (cross-sectional) mengasumsikan SoDEX adalah pasar **dalam & lebar**.
   Kenyataannya: hanya 3 simbol yang bertransaksi, median pasar $328/jam. Arsitektur itu
   **secara struktural tidak berlaku**, dan hasil "lolos"-nya adalah artefak pasar mati.
2. **SPEC4 putaran pertama saya** mengandung **bug alignment fatal**: grid Binance dan grid
   SoDEX tidak disejajarkan, sehingga sinyal H9 tergeser ~4 hari. Ditemukan dan diperbaiki
   **sebelum** hasil nyata dibaca. Kalau lolos, H9 akan diuji pada data yang salah.
3. Formula p-value bootstrap saya awalnya salah (membandingkan distribusi yang sudah terpusat
   di rata-rata sampel dengan rata-rata itu sendiri → selalu p≈1 → **meloloskan apa pun**).
   Tertangkap oleh tes kalibrasi, lalu diperbaiki menjadi bootstrap terpusat pada H₀.
   Dua bug ini (#2 dan #3) juga sempat muncul sebagai **crash keras** saat dikembangkan
   (epoch dipakai sebagai indeks posisi; off-by-one blok bootstrap). Verifikasi bahwa
   keduanya sudah mati dan bahwa skrip ter-commit **mereproduksi hasil byte-identik**
   ada di `reports/sodex/SPEC4_VERIFIKASI_REPRODUKSI_2026-10-07.md`.

Semua ini adalah kesalahan rancangan, bukan kesalahan strategi. Tapi memperbaikinya
menghasilkan **kesimpulan yang sama**: tidak ada edge. Jadi arsitektur bukan satu-satunya
penyebab kegagalan — dan pada putaran ini, bukan penyebabnya sama sekali.

## 8. Kesimpulan

1. **SPEC4 ditutup. 0/13 sel lulus.** Dari **35 baris total** di JSON (13 sel hipotesis + 13
   kontrol fade + 9 varian market-neutral 2-leg), **semuanya `verdict=False` dan `p=1,000`**.
   Tidak ada edge lead-lag Binance→SoDEX dan tidak ada edge order-flow native SoDEX pada
   resolusi menit, untuk BTC/ETH/SOL, atas 137 hari.
2. Batas atas edge yang terukur ≈ **1,5 bp per posisi**; biaya 8 bp; target menuntut 48–88 bp.
3. Ini **bukan** kegagalan arsitektur (arsitektur lintas-venue + mikro-struktur adalah
   pendekatan yang tepat untuk venue tipis) — ini **batas empiris pasar**.
4. Kendala target = **horizon waktu & jumlah episode**, bukan cakupan data dan bukan ide.
5. Forward aktif tetap **F1 (#42)** dan **F3 (#44)** — keduanya mengumpulkan episode pada
   horizon 24 jam, yaitu horizon yang secara aritmetika memang bisa mencapai target.

**Batas jujur:** belum ada satu pun strategi yang terbukti melampaui target 0,8%/48 jam.
Yang bisa saya pastikan hanyalah bahwa dua kelas arsitektur menit sudah **dinyatakan gugur
dengan bukti**, bukan dengan dugaan.

— Hermes Anantara v3 — 2026-10-07
