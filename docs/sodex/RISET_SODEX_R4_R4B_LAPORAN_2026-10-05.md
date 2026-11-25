# Laporan Riset SoDEX — R4, R4-B, R4-C & R4-D: Menguji 16 Mesin, 41 Evaluasi di Tiga Venue

**Tanggal:** 05-Okt-2026 · **Penulis:** Hermes Anantara v3 · **Status:** Fase DEV selesai, hasil negatif dilaporkan apa adanya

---

## Daftar Isi

- [1. Ringkasan untuk yang sibuk (baca ini dulu)](#1-ringkasan-untuk-yang-sibuk-baca-ini-dulu)
- [2. Latar: target yang kita kejar](#2-latar-target-yang-kita-kejar)
- [3. Cara kami menguji (dan kenapa caranya penting)](#3-cara-kami-menguji-dan-kenapa-caranya-penting)
- [4. Hasil R4: lima mesin pertama (H1–H5)](#4-hasil-r4-lima-mesin-pertama-h1h5)
- [5. Hasil R4-B: lima mesin kedua (H6–H10)](#5-hasil-r4-b-lima-mesin-kedua-h6h10)
- [6. Uji silang venue: Binance vs Hyperliquid](#6-uji-silang-venue-binance-vs-hyperliquid)
- [7. Temuan inti: apa yang sebenarnya menghambat](#7-temuan-inti-apa-yang-sebenarnya-menghambat)
- [8. R4-C: apakah biaya yang menjadi hambatan? (uji eksekusi pasif)](#8-r4-c-apakah-biaya-yang-menjadi-hambatan-uji-eksekusi-pasif)
- [9. Kejujuran: kesalahan yang kami temukan sendiri](#9-kejujuran-kesalahan-yang-kami-temukan-sendiri)
- [10. Apa yang TIDAK kami lakukan](#10-apa-yang-tidak-kami-lakukan)
- [11. Langkah berikutnya](#11-langkah-berikutnya)
- [12. R4-D: kelas kejadian dan penutupnya (H13abc)](#12-r4-d-kelas-kejadian-dan-penutupnya-h13abc)
- [13. Glosarium awam](#13-glosarium-awam)
- [14. Lampiran: cara memeriksa ulang](#14-lampiran-cara-memeriksa-ulang)

---

## 1. Ringkasan untuk yang sibuk (baca ini dulu)

Kami menguji **15 mesin trading** (strategi) dengan cara yang ketat: aturannya ditulis dan
dikunci **sebelum** hasilnya dilihat. Hasilnya:

| Yang diuji | Jumlah | Hasil |
|---|---|---|
| Mesin H1–H5 (R4) di Binance 36 bulan | 5 | **5 gagal** |
| Mesin H6–H10 (R4-B) di Binance 36 bulan | 5 | **5 gagal** |
| Mesin H6–H10 di Hyperliquid 4 jam | 5 | **5 gagal** |
| Mesin H6–H10 di Hyperliquid 1 hari (6,1 tahun) | 5 | **5 gagal** |
| Mesin H11–H12 (eksekusi pasif/maker) di 3 venue | 9 | **9 gagal** |

**Total 29 evaluasi mesin, 29 gagal.** Ini bukan kabar buruk yang disembunyikan — ini justru
hasil yang **berguna**: kami sekarang tahu **persis** apa yang menghambat, dan hambatannya
bukan yang selama ini diduga.

**Hambatannya adalah: BESARNYA keuntungan per transaksi — bukan jumlah mesin, bukan Sharpe,
bukan frekuensi trading.**

| Dugaan penyebab | Kesimpulan | Alasan singkat |
|---|---|---|
| Kurang mesin | **Salah** | Rata-rata portofolio = campuran rata-rata mesin. Menambah mesin hanya memperkecil goyangan, **tidak** menaikkan rata-rata |
| Kurang Sharpe | **Salah** | Mesin H8 punya Sharpe 2,65–3,91 (lolos syarat 2,3) tapi keuntungannya cuma 0,011–0,022% per 48 jam (target 0,8%) |
| Kurang frekuensi | **Salah** | Biaya 0,40% per transaksi; kalau sering trading, biaya makan 69% per tahun |
| **Kurang besar untung per transaksi** | **BENAR** | Yang terbaik hanya 0,40–0,47% per transaksi; yang dibutuhkan 6,00% → **kurang 14 kali** |

**Satu temuan yang bertahan di ketiga venue:** mesin "carry funding ekstrem" (H8) memang
**benar-benar bisa menebak waktu yang bagus** (dibuktikan dengan uji acak: peluang kebetulan
hanya 0,5%). Tapi uangnya **13–15× terlalu kecil** untuk mencapai target.

**Temuan kedua (dari uji eksekusi pasif/maker):** menurunkan biaya trading **berhasil** —
biaya bukan lagi hambatan utama — tetapi muncul hambatan baru yang lebih keras:
**adverse selection**. Order pasif hanya terisi **ketika harga bergerak melawan kita**, sehingga
"menang kecil sering, kalah besar sesekali". Rinciannya di [bab 8](#8-r4-c-apakah-biaya-yang-menjadi-hambatan-uji-eksekusi-pasif).

---

## 2. Latar: target yang kita kejar

Target SoDEX: **0,8% dari TOTAL modal wallet per 48 jam**, tanpa leverage.

Mari kita terjemahkan ke bahasa sederhana:

| Kalau target ini dipertahankan 48 jam, lalu diulang terus | Hasil setahun |
|---|---|
| 0,8% per 48 jam | ≈ **+328% per tahun** (majemuk) |
| Setara per hari | ≈ **0,4% per hari** |

**Analogi:** bayangkan Anda punya modal Rp 1.000.000. Target ini berarti setiap dua hari
modal harus bertambah Rp 8.000 — terus-menerus, tanpa henti, tanpa pinjaman (leverage).
Setahun kemudian modalnya menjadi sekitar Rp 4.280.000. Ini target yang **sangat ambisius**
untuk trading tanpa leverage.

Inilah kenapa kami tidak bisa asal "coba-coba strategi": setiap ide harus lulus ujian yang
ketat sebelum dipercaya.

---

## 3. Cara kami menguji (dan kenapa caranya penting)

Ada empat pengaman yang membuat hasil ini bisa dipercaya:

### 3.1 Pra-registrasi (aturan dikunci sebelum lihat hasil)

**Analogi:** seperti ujian di mana soal **dan kunci jawabannya** ditulis dulu, baru dikoreksi.
Kalau kuncinya bisa diubah setelah melihat jawaban, semua orang jadi pintar.

Kami menulis aturan hipotesis, menaruhnya di git (tercatat tanggal & kodenya), **baru**
menjalankan pengujian. Setelah hasil keluar, angka di dokumen itu tidak boleh diubah lagi.

### 3.2 Lockbox (data ujian yang disegel)

Data dibagi dua:

| Fase | Periode | Fungsi |
|---|---|---|
| **DEV** | 2022-10-01 → 2025-09-30 | tempat menguji ide (boleh dilihat) |
| **LOCKBOX** | 2025-10-01 → 2026-09-30 | disegel; **hanya dibuka kalau ide lulus DEV** |

**Analogi:** belajar dari buku latihan (DEV), lalu ujian sesungguhnya (LOCKBOX) pakai soal
yang belum pernah dilihat. Kalau ide gagal di latihan, ujiannya tidak perlu dibuka.

### 3.3 Kontrol acak (apakah lebih baik dari keberuntungan?)

Setiap mesin dibandingkan dengan **versi acak** yang punya jumlah transaksi dan lama
menahan yang sama, tapi waktu masuknya diundi. Kalau mesin tidak lebih baik dari undian,
berarti ia tidak punya keunggulan nyata.

### 3.4 Koreksi multi-uji (jangan tertipu kebetulan)

Menguji 15 mesin sekaligus berarti ada banyak kesempatan "kelihatan bagus karena kebetulan".
Kami memakai koreksi **BH-FDR** (ambang ketat 10%) dan **PBO** (mengukur seberapa sering
"pemenang" ternyata palsu). Syarat: PBO < 20%.

---

## 4. Hasil R4: lima mesin pertama (H1–H5)

Data: Binance USDM Futures, 11 koin besar, 36 bulan, 547 jendela waktu (masing-masing 48 jam),
biaya 0,40% per transaksi.

| Mesin | Idenya (bahasa awam) | Untung per 48 jam | Sharpe | Lolos? |
|---|---|---|---|---|
| H1 | Ikuti tren: kalau harga di atas rata-rata & naik, beli | −0,210% | −0,83 | Gagal |
| H2 | Tembus batas: beli kalau menembus puncak 48 jam | +0,056% | +0,39 | Gagal |
| H3 | Panen funding: cari koin yang bayar bunga tinggi | −0,354% | −93,0 | Gagal (rugi signifikan) |
| H4 | Balik arah: beli saat harga jatuh terlalu dalam | −0,132% | −0,90 | Gagal |
| H5 | Gabungan: ikuti tren hanya saat pasar sesuai | −0,102% | −0,45 | Gagal |

**PBO = 0,647** (syarat < 0,20) → artinya "pemenang" di keluarga ini 65% kemungkinan palsu.
Kontrol acak: 0,540 / 0,639 / 0,631 → mesin **tidak lebih baik dari undian**.

**Pelajaran kunci dari R4:** H1 gagal karena **frekuensi** — terlalu sering trading, biaya
0,40% per transaksi menjadi beban **69% per tahun**. Sementara H3 (panen funding) mustahil
secara aritmetika: funding yang terkumpul jauh lebih kecil dari biayanya.

---

## 5. Hasil R4-B: lima mesin kedua (H6–H10)

Kami susun mesin baru berdasarkan pelajaran R4: **frekuensi rendah, tahan lama (14–30 hari),
cari kejadian ekstrem**.

| Mesin | Idenya (bahasa awam) | Untung per 48 jam | Sharpe | Segmen untung | Transaksi | Untung/transaksi | Dibutuhkan | Lolos? |
|---|---|---|---|---|---|---|---|---|
| H6 | Beli koin terkuat, jual terlemah (30 hari) | +0,000% | 0,11 | 2/3 | 304 | −0,18% | 6,00% | Gagal |
| H7 | Ikuti tren lambat (7/30/90 hari), tahan 30 hari | −0,090% | −0,37 | 1/3 | 331 | −1,95% | 12,40% | Gagal |
| H8 | Panen funding **saat sangat ekstrem** | +0,011% | **2,65** | 2/3 | 136 | **+0,40%** | 6,00% | Gagal |
| H9 | Beli setelah harga jatuh ekstrem | −0,030% | −0,21 | 0/3 | 177 | +1,10% | 6,00% | Gagal |
| H10 | Beli yang terlemah, jual yang terkuat | −0,006% | −1,65 | 0/3 | 308 | −1,01% | 6,00% | Gagal |

**PBO = 0,25** (syarat < 0,20) → tetap gagal.

### Kenapa H8 penting (meski tetap gagal)

H8 adalah satu-satunya yang **arahnya benar**: untung per transaksi **+0,40%** (positif!) dan
Sharpe 2,65. Yang membuatnya gagal adalah **besarannya**: 0,40% vs 6,00% yang dibutuhkan.

**Uji acak membuktikan sinyalnya nyata:** kontrol acak hanya 0,49% peluang menandingi H8.
Artinya filter "funding ekstrem" **memang memilih waktu yang lebih baik dari undian** — bukan
kebetulan. Tapi uang yang dihasilkan terlalu kecil.

### Penutupan aritmetika: kenapa carry funding tidak bisa diselamatkan

| | Nilai |
|---|---|
| Funding di rezim ekstrem (persentil-95) | ≈ 0,029% per hari (≈ 10,4% per tahun) |
| Target kita butuh | 0,4% per hari (≈ 146% per tahun) |
| Selisih | **14 kali** |

Menahan lebih lama **tidak** menolong, karena biaya tumbuh seiring waktu:

| Lama tahan | Funding terkumpul | Yang dibutuhkan target | Selisih |
|---|---|---|---|
| 14 hari | ≈ 0,41% | 6,00% | 5,6% |
| 30 hari | ≈ 0,87% | 12,40% | 11,5% |
| 60 hari | ≈ 1,74% | 24,40% | 22,7% |

---

## 6. Uji silang venue: Binance vs Hyperliquid

**Pertanyaan:** apakah mesin-mesin ini gagal karena pasarnya (semua venue sama) atau karena
struktur Binance saja? Kami jalankan **aturan yang sama persis** di Hyperliquid (bursa DEX)
dengan tiga kerapatan data.

| Kerapatan data | Rentang | H6 | H7 | H8 | H9 | H10 | PBO |
|---|---|---|---|---|---|---|---|
| Binance 1 jam | 36 bulan | Gagal | Gagal | Gagal | Gagal | Gagal | 0,250 |
| Hyperliquid 4 jam | 15 bulan | Gagal | Gagal | Gagal | Gagal | Gagal | 0,353 |
| Hyperliquid 1 hari | **6,1 tahun** | Gagal | Gagal | Gagal | Gagal | Gagal | 0,881 |

**Hasil: 15 dari 15 gagal.** Tidak ada mesin yang hidup di venue lain.

**Yang bertahan (replikasi tiga kali):** H8 (carry funding ekstrem) menunjukkan pola yang sama
di ketiga venue — uji acak **0,0049 / 0,0050 / 0,0050**. Ini bukti kuat bahwa sinyalnya nyata,
bukan kebetulan satu venue.

**Kesimpulan:** kelas strategi "sinyal halus pada koin besar" **sudah ditutup** dengan bukti
tiga venue. Bukan "belum cukup data" — datanya 6,1 tahun dan tiga venue, dan hasilnya konsisten
nol.

---

## 7. Temuan inti: apa yang sebenarnya menghambat

### 7.1 Matematika portofolio (kenapa menambah mesin tidak menolong)

**Analogi:** bayangkan Anda punya 8 pekerja. Nilai rata-rata pekerjaan mereka **tidak bisa
melebihi pekerja terbaik**. Menambah pekerja membuat hasil **lebih stabil** (goyangan lebih
kecil), tapi **rata-ratanya tidak naik**.

Ini kami verifikasi dengan 20.000 simulasi: menaikkan porsi dari 0% ke 100% hanya menggerakkan
rata-rata **di antara** dua nilai mesin (0,162% → 0,814%), tidak pernah melewatinya.

**Konsekuensi:** yang harus diperbaiki adalah **rata-rata per mesin**, bukan jumlah mesin.

### 7.2 Sharpe tinggi tidak berarti target tercapai

H8 punya Sharpe 2,65–3,91 (di atas syarat 2,3) tapi keuntungannya 0,011–0,022% per 48 jam.
Target butuh 0,8%.

**Analogi:** seorang penembak yang selalu tepat sasaran tapi pelurunya kecil — konsisten,
tapi tidak cukup untuk menjatuhkan sasaran. Sharpe mengukur **konsistensi**, bukan **besaran**.

### 7.3 Angka yang harus ditutup

| | Nilai |
|---|---|
| Target | 146% per tahun (tanpa leverage) |
| Keunggulan terbaik yang terbukti | ≈ 10% per tahun |
| **Selisih** | **≈ 14 kali** |

Ini bukan masalah optimasi (menggeser parameter). Ini masalah **jenis keunggulan** —
keunggulan yang kami uji terlalu kecil untuk target ini.

---

## 8. R4-C: apakah biaya yang menjadi hambatan? (uji eksekusi pasif)

Setelah R4-B, satu hipotesis masih hidup: **mungkin yang membunuh semua mesin adalah biaya**.
Semua perhitungan sebelumnya memakai biaya **taker 0,40%** per transaksi. Kalau kita memasang
order **pasif (maker)** — menunggu di harga, bukan menabrak pasar — biayanya turun lebih dari 10×:

| | Taker | Maker |
|---|---|---|
| Binance per sisi | 0,05% | **0,02%** |
| Hyperliquid per sisi | 0,045% | **0,015%** |
| Pulang-pergi | 0,40% (aturan program) | **0,03–0,04%** |

**Analogi:** kalau biaya trading itu seperti **ongkos kirim**, maka selama ini kita mengirim
barang dengan **kurir ekspres** (mahal, cepat). Sekarang kita uji apakah memakai **kurir biasa**
(murah, tapi barang baru terkirim kalau ada yang mau mengangkut) bisa menyelamatkan usaha.

**Aturan dikunci sebelum dijalankan** (pra-registrasi), lalu hasilnya:

| Mesin | Binance 36 bln | HL 4 jam | HL 1 hari (6,1 th) |
|---|---|---|---|
| H11a — mesin momentum lama, masuk pakai order pasif | Gagal | Gagal | Gagal |
| H11b — mesin balik-arah lama, masuk pakai order pasif | Gagal | Gagal | Gagal |
| H12 — penyedia likuiditas pasif (beli 0,5×ATR di bawah, jual di atas) | Gagal | Gagal | Gagal |

**Hasil: 9 dari 9 gagal.**

### Tapi di sini ada temuan yang sangat penting

Mesin H12 (penyedia likuiditas) **lolos uji biaya** di ketiga venue:

| Venue | Untung rata-rata (median) per transaksi | Yang dibutuhkan | Lolos uji biaya? |
|---|---|---|---|
| Binance 1 jam | +1,063% | 0,440% | **Ya** |
| Hyperliquid 4 jam | +1,578% | 0,430% | **Ya** |
| Hyperliquid 1 hari | **+4,974%** | 0,430% | **Ya** |

…tetapi **tetap rugi** setelah semuanya dihitung:

| Venue | Untung per 48 jam |
|---|---|
| Binance 1 jam | −0,0797% |
| Hyperliquid 4 jam | −0,3879% |
| Hyperliquid 1 hari | −0,0215% |

**Bagaimana mungkin "median untung 5%" tapi "rata-rata rugi"?**
Karena **median ≠ rata-rata**. Bayangkan 10 transaksi: 9 kali menang kecil (+2% masing-masing),
1 kali kalah besar (−25%). Median-nya +2% (kelihatan bagus), tapi rata-ratanya **negatif**.

**Analogi:** seperti menjadi **penjual payung** yang hanya kebanjiran pembeli saat hujan deras —
kelihatannya laris, tapi Anda selalu menjual tepat sebelum harga payung anjlok kembali.
Inilah yang disebut **adverse selection**: order pasif hanya terisi **ketika pasar bergerak
melawan kita**. Kita membeli 0,5×ATR di bawah harga **karena** harga sedang jatuh — dan sering
terus jatuh.

**Kesimpulan jujur:** eksekusi pasif **memang menghapus hambatan biaya** (terbukti di tiga venue),
tetapi **tidak** menghasilkan keuntungan. Hambatan berpindah, bukan hilang: dari **biaya** menjadi
**adverse selection**.

**Satu hal yang tetap kokoh:** sinyal momentum beku (H11a) terbukti **lebih baik dari undian**
(uji acak 0,005 di ketiga asumsi margin antrian) — jadi informasinya nyata, hanya **besarannya**
kurang 8–16×.

## 9. Kejujuran: kesalahan yang kami temukan sendiri

Bagian ini penting. Kami menemukan **7 kesalahan** dalam proses — semuanya kami perbaiki dan
catat. Tidak ada yang disembunyikan.

| # | Kesalahan | Akibat kalau dibiarkan | Cara ditemukan |
|---|---|---|---|
| 1 | **Look-ahead** (membaca data masa depan) di mesin lintas-seksi | Hasil mustahil (−250.000%) | Angka tidak wajar di run pertama |
| 2 | Arah mesin H10 terbalik | H10 jadi sama dengan H6 | Pemeriksaan kode |
| 3 | Mesin H8 tidak punya kontrol acak | Kriteria putusan tidak lengkap | Pemeriksaan kriteria |
| 4 | Lama tahan H8 dihitung per-record, padahal jadwal funding Binance tidak seragam (SOL punya 98 periode 2 jam) | Lama tahan bukan 14 hari untuk SOL | **Uji reproduksibilitas** (jalankan ulang → 4 mesin identik, H8 bergeser) |
| 5 | Angka n & p di laporan H6/H10 salah tulis | Laporan tidak akurat | Audit silang ke JSON mentah |
| 6 | Model fill: harga `min(open, L)` = perilaku *market order*, bukan order pasif | Biaya maker dihitung padahal sebenarnya taker | Smoke test 2 bulan BTC |
| 7 | Model fill: limit keluar diuji di bar yang sama dengan pemasangan | Look-ahead halus | Smoke test |
| 8 | Model fill: limit tepat di harga acuan = *marketable* (laju fill 100%) | Keuntungan pasif palsu | Smoke test |
| 9 | Trade pasif boleh **tumpang tindih** (≈40% sinyal BTC) | Eksposur ganda tersembunyi — melanggar aturan beku "satu posisi per simbol" | Run pertama → pemeriksaan aturan beku |

**Yang paling penting:** kesalahan #4 dan #9 ditemukan justru karena kami **menjalankan ulang**
dan membandingkan hasil. Kalau kami tidak memverifikasi, kami akan melaporkan angka yang salah.
Kesalahan #9 mengubah angka (H11a: +0,0912% → **+0,0515%** per 48 jam) tetapi **tidak** mengubah
putusan — dan angka yang benar adalah yang **lebih jelek**, jadi arah koreksinya jujur.

---

## 10. Apa yang TIDAK kami lakukan

Batas keamanan **tidak disentuh sama sekali**:

| Batas | Status |
|---|---|
| Gate T1 | Utuh |
| Leverage | **Tidak dipakai** (tetap nol) |
| Target 0,8% per 48 jam | **Tidak diubah** |
| `SODEX_TOTAL_WALLET` | Tidak diubah |
| E1 | Tetap beku |
| Arm A1 | Tetap mati |
| `RW_MARGIN_UTIL_CAP` | Tetap OFF (default) |
| Lane uang nyata | Tidak disentuh (script hanya **membaca** data) |
| Lockbox | **Tetap tertutup** (tidak ada yang lulus) |

Semua script riset bersifat **read-only**: hanya membaca data pasar dan menulis laporan.

---

## 11. Langkah berikutnya

### Yang sudah diuji dan hasilnya

| Jalur | Status | Hasil |
|---|---|---|
| Sinyal statistik pada 11 koin besar (H1–H10) | **Selesai** | 20 evaluasi, semua gagal |
| Eksekusi pasif/maker (H11–H12) | **Selesai** | 9 evaluasi, semua gagal — **hambatan biaya teratasi, hambatan adverse selection muncul** |

### Spesifikasi yang harus dipenuhi mesin berikutnya (hasil kuantifikasi, bukan tebakan)

Dari seluruh pengujian, kita sekarang bisa menuliskan **syarat minimum** secara eksak:

| Jalan | Syarat minimum | Sudah ada? |
|---|---|---|
| Frekuensi tinggi (hold ≤ 48 jam) | ≥ **0,44% bersih** per transaksi **dan** fill tidak merugikan (bebas adverse selection) | Belum — H12 median 1,06% tapi **adverse selection** menghapusnya |
| Frekuensi rendah (hold 14 hari) | ≥ **6,00% bruto** per transaksi | Belum — terbaik 0,40–0,47% |
| Frekuensi sangat rendah (hold 30 hari) | ≥ **12,40% bruto** per transaksi | Belum |

**Kesimpulan keras:** target 0,8%/48 jam **tidak bisa** dicapai oleh kelas strategi
"sinyal statistik pada koin likuid" — di tiga venue, enam kerapatan data, dan dua model biaya
(taker & maker). Yang tersisa hanya **kelas kejadian**, bukan kelas sinyal.

### Jalur B (SUDAH dikerjakan — hasilnya di §12)

Mencari keuntungan **puluhan persen per transaksi** dari kejadian langka dan tidak efisien:

| Sumber | Kenapa bisa besar | Data yang dibutuhkan |
|---|---|---|
| Likuidasi besar berantai | Harga dipaksa bergerak jauh dalam menit | Data likuidasi (Binance/HL menyediakan sebagian) |
| Listing / delisting koin | Harga melompat puluhan persen | Kalender listing + data koin baru |
| Koin kecil (bukan 11 koin besar) | Spread lebar, likuiditas tipis, kurang efisien | Data koin kecil (perlu diunduh) |
| Kejadian protokol (depeg, hack, fork) | Lompatan harga sekali seumur | Berita + data on-chain |

Semua jalur ini punya **karakter berbeda**: kejadian langka **tidak** bisa diuji dengan 36 bulan
data harian saja — butuh data per menit dan daftar kejadian. Ini pekerjaan baru, bukan optimasi.

### Rekomendasi jujur

1. **Jangan ubah target** (0,8%/48 jam tetap harga mati) — tapi **akui secara eksplisit** bahwa
   target ini menuntut kelas kejadian, bukan kelas sinyal.
2. **Jangan tambah leverage** untuk menutup selisih 14× — itu melanggar batas keamanan dan
   mengubah risiko secara fundamental.
3. **Langkah paling murah yang informatif:** jalankan **Jalur B tahap 1** (unduh data likuidasi
   + daftar koin baru 12–24 bulan), lalu ukur berapa besar lompatan harga rata-rata per kejadian.
   Kalau lompatannya < 6%, kelas ini juga tertutup **sebelum** menulis satu baris strategi.

---

## 12. R4-D: kelas kejadian dan penutupnya (H13abc)

Kelas mesin sebelumnya gagal dengan dua sebab berulang: **besarannya kurang ~14×** dan
**biaya masuk memakan keuntungan**. Bab ini menguji kelas yang berbeda secara mendasar —
bukan sinyal halus pada koin likuid, melainkan **kejadian ekstrem**: lompatan harga ≥3%
(juga ≥5% dan ≥8%) dalam **satu jam** — dengan **batas risiko ekor** yang selama ini absen.

Pra-registrasi **dibekukan lebih dulu** (`docs/sodex/R4D_PROTOKOL_H13_2026-10-05.md`, komit
`d63e7ee`): arah posisi **melawan** gerakan (fade), masuk di bar berikutnya, tahan **24 jam**,
**stop keras 1,5×ATR**, **aturan klaster** (hanya kejadian pertama per 24 jam per simbol),
kontrol acak 200 ulangan, BH-FDR q=0,10, PBO, DSR. Setelah hasil keluar **tidak ada ambang
yang diubah**.

### 12.1 Empat tier — dan mengapa tier pertama menentukan

| Tier | Data | Model biaya | Jendela |
|---|---|---|---|
| Tier-2 | Binance 1 jam | bar · slippage diasumsikan 0,02% | 36 bulan |
| **Tier-1 (PUTUSAN)** | Binance 1 jam **+ data 1-menit** | **terukur** pada bar kejadian · stop intrabar | 24 bulan |
| Tier-3a | Hyperliquid 4 jam | bar | 15 bulan |
| Tier-3b | Hyperliquid 1 hari | bar | 6,1 tahun |

Tier-1 memakai **17.360.640 bar 1-menit** (396 berkas Binance Vision, sha256 terverifikasi,
unduhan berhenti 2025-09 agar LOCKBOX tidak tersentuh). Bedanya bukan jumlah data:
Tier-2 **mengasumsikan** biaya, Tier-1 **mengukurnya** pada saat yang paling menentukan —
yaitu tepat di bar kejadian.

### 12.2 Hasil: 12 evaluasi, 0 lulus

Format: `mean per 48 jam · Sharpe · p kontrol acak`. Kolom kontrol **0,0050** = sinyal nyata
(bukan undian); **1,00** = tidak bisa dibedakan dari acak.

| Tier | H13a θ=3% | H13b θ=5% | H13c θ=8% |
|---|---|---|---|
| Binance 1 jam (bar) | +0,0541% · 0,58 · **0,0050** | +0,0486% · 0,57 · **0,0050** | +0,0097% · 0,22 · **0,0050** |
| **Binance 1 jam (1-menit)** | **−0,0641% · −0,59 · 1,00** | **−0,0473% · −0,56 · 1,00** | **−0,0098% · −0,20 · 0,0050** |
| HL 4 jam (bar) | +0,0266% · 0,44 · 1,00 | −0,0185% · −0,35 · 1,00 | +0,0616% · 0,92 · **0,0050** |
| HL 1 hari (bar) | −0,0093% · −0,36 · 1,00 | −0,0383% · −1,17 · 1,00 | −0,0322% · −0,80 · 1,00 |

PBO 0,571 / 0,595 / 0,099 / 0,258 · BH-FDR **nol lulus** · segmen positif maksimum 2/3 ·
**LOCKBOX tidak dibuka**.

### 12.3 Temuan terpenting seluruh program: model biaya MEMBALIKKAN TANDA

| Kejadian | Slippage **terukur** | Bruto/transaksi (terukur) | Bruto (asumsi 0,02%) | Anggaran dibutuhkan |
|---|---|---|---|---|
| θ=3% | 0,248% | **−0,722%** | −0,086% | 0,748% |
| θ=5% | 0,446% | **−1,250%** | +0,567% | 0,946% |
| θ=8% | **0,482%** | −0,166% | +0,313% | 0,982% |

Dua bacaan yang harus dibaca bersama:

1. **Slippage tumbuh bersama keganasan kejadian** — 0,248% → 0,446% → **0,482%**.
   Semakin besar lompatannya, semakin mahal masuk ke dalamnya.
2. **Keuntungan kotor tidak tumbuh secepat itu.** Pada θ=8%, bruto hanya +0,313% sementara
   biaya eksekusi 0,482% + fee. Karena itu **anggaran naik dari 0,540% ke 0,982%** — hampir
   dua kali — sehingga ambang yang tadinya "anggaran OK" di Tier-2 menjadi **tidak mungkin**.

**Kesimpulan:** yang membunuh kelas kejadian bukan sinyalnya (waktunya terbukti bukan
undian), melainkan **harga masuk**. Semakin besar peluang, semakin mahal pintunya — dan
biaya menang. Ini bentuk kuantitatif dari *adverse selection* yang pertama kali muncul di R4-C.

### 12.4 Yang bertahan (dinyatakan apa adanya)

- Waktu kejadian **bukan undian**: Binance 1 jam pada **ketiga** ambang (p=0,0050) dan
  HL 4 jam pada ambang 8% (p=0,0050).
- Namun besarnya tetap **13–15× kurang** dari target dan Sharpe hanya 0,22–0,92 (perlu 2,3).
- Ekor kiri tetap gemuk: persentil-5 antara **−5,4%** dan **−10,7%**; stop tersentuh
  **36–45%** trade (batas ekor bekerja, tapi tidak mengubah tanda).
- **HL 1 hari: sinyalnya hilang** (kontrol 1,00 di ketiga ambang) — kelas kejadian tidak
  bertahan pada grid harian.

### 12.5 Batas kejujuran (dinyatakan di muka, bukan setelah ditanya)

1. Kontrol Tier-1 memakai model bar, bukan 1-menit (200 ulangan × data 1-menit tidak
   terjangkau). Arah biasnya tidak jelas → kriteria kontrol Tier-1 dilaporkan sebagai
   **pendukung**; konfirmasi penuh ada di Tier-2 yang modelnya cocok dengan mesinnya.
2. Slippage didefinisikan sebagai |pergerakan 1 menit| pada bar kejadian — **dibekukan di
   pra-registrasi**. Ini **batas konservatif**, bukan estimator tak bias.
3. Data 1-menit **bukan** data tick/buku order; posisi antrian tetap tidak dimodelkan.
4. `p_day_cluster` tidak signifikan (0,02–0,79) → efek **tidak reliabel** di tingkat
   portofolio jendela, sekalipun arahnya positif di Tier-2.

### 12.6 Putusan kumulatif dan artinya bagi target

| Program | Evaluasi | Lulus |
|---|---|---|
| R4 (H1–H5) | 5 | 0 |
| R4-B (H6–H10 × 3 venue) | 15 | 0 |
| R4-C (H11–H12 × 3 venue) | 9 | 0 |
| **R4-D (H13a/b/c × 4 tier)** | **12** | **0** |
| **TOTAL** | **41** | **0** |

Dengan tertutupnya kelas kejadian, tiga pintu sudah benar-benar tertutup: **kelas sinyal**
(R4/R4-B), **kelas pembuat pasar** (R4-C), dan **kelas kejadian** (R4-D). Kesemuanya gagal
bukan karena sinyalnya kosong, tapi karena **selisih antara peluang dan biaya eksekusi**.

Target 0,8%/48 jam **tidak diubah** dan tetap harga mati. Yang harus berubah adalah
**akses eksekusi**, bukan sinyalnya — dan itu masalah akun/venue (tier biaya, rebat,
akses likuiditas), bukan masalah riset sinyal. Ini keputusan Mas Anas, bukan keputusan
yang boleh kami ambil sendiri.

---

## 13. Glosarium awam

| Istilah | Arti sederhana |
|---|---|
| **DEV / LOCKBOX** | Data latihan / data ujian yang disegel |
| **Pra-registrasi** | Menulis aturan & kunci jawaban sebelum melihat hasil |
| **Sharpe** | Ukuran konsistensi (bukan besaran) keuntungan |
| **PBO** | Peluang "pemenang" kita sebenarnya palsu |
| **BH-FDR** | Koreksi supaya tidak tertipu kebetulan saat menguji banyak ide |
| **Taker / Maker** | Order yang menabrak pasar (mahal) / order yang menunggu di harga (murah) |
| **Model fill** | Aturan kapan order pasif dianggap benar-benar terisi |
| **Look-ahead** | Kesalahan memakai informasi masa depan (mustahil di dunia nyata) |
| **ATR** | Ukuran seberapa besar harga biasanya bergerak (volatilitas) |
| **Funding** | Bunga berkala yang dibayar antar trader di pasar berjangka |
| **Carry** | Strategi memanen bunga/funding |
| **Konveks (kombinasi)** | Rata-rata yang selalu berada di antara dua nilai, tidak melewatinya |
| **Adverse selection** | Order pasif hanya terisi **ketika harga bergerak melawan kita** — jadi yang terisi adalah kabar buruk |
| **Median vs rata-rata** | Median = nilai tengah (tahan terhadap pencilan); rata-rata = jumlah dibagi banyak (dipengaruhi kalah besar) |
| **Margin antrian** | Jarak ekstra dari harga pasar supaya order benar-benar *menunggu*, bukan menabrak pasar |
| **Eksposur ganda** | Dua posisi terbuka bersamaan pada satu simbol — setara leverage tersembunyi (dilarang) |

---

## 14. Lampiran: cara memeriksa ulang

Semua bisa diperiksa ulang oleh siapa pun:

| Berkas | Isi |
|---|---|
| `docs/sodex/R4_PROTOKOL_DATA_4TAHUN_2026-10-05.md` | Protokol data R4 (beku) |
| `docs/sodex/R4_HIPOTESIS_H1_H5_2026-10-05.md` | Definisi H1–H5 (beku) |
| `docs/sodex/R4B_PROTOKOL_H6_H10_2026-10-05.md` | Pra-registrasi H6–H10 (beku) |
| `docs/sodex/R4C_PROTOKOL_H11_H12_2026-10-05.md` | Pra-registrasi H11–H12 + koreksi model (beku) |
| `reports/sodex/R4_DEV_results.json` | Hasil mentah R4 |
| `reports/sodex/R4B_DEV_results.json` | Hasil mentah R4-B (Binance) |
| `reports/sodex/R4B_HL4h_results.json` | Hasil mentah HL 4 jam |
| `reports/sodex/R4B_HL1d_results.json` | Hasil mentah HL 1 hari |
| `scripts/r4_dev_harness.py` | Program uji R4 |
| `scripts/r4b_harness.py` | Program uji R4-B (multi-venue) |
| `scripts/r4c_harness.py` | Program uji R4-C (model fill maker) |
| `scripts/download_hl_deep.py` | Pengunduh data Hyperliquid (diperbaiki) |
| `reports/sodex/R4C_DEV_2026-10-05.md` | Laporan R4-C (maker) 3 venue + F-1 |
| `reports/sodex/R4C_DEV_results.json` | Hasil mentah R4-C Binance (q=5bp) |
| `reports/sodex/R4C_HL4h_results.json` · `R4C_HL1d_results.json` | Hasil mentah R4-C Hyperliquid |

**Reproduksi (siapa pun bisa menjalankan):**

```bash
cd ~/anantara-sakti
.venv-research/bin/python3 scripts/r4b_harness.py                  # Binance
R4B_TIER=hl4h .venv-research/bin/python3 scripts/r4b_harness.py    # Hyperliquid 4 jam
R4B_TIER=hl1d .venv-research/bin/python3 scripts/r4b_harness.py    # Hyperliquid 1 hari
.venv-research/bin/python3 scripts/r4c_harness.py                  # maker (R4-C) Binance
R4B_TIER=hl4h .venv-research/bin/python3 scripts/r4c_harness.py    # maker (R4-C) HL 4 jam
R4B_TIER=hl1d .venv-research/bin/python3 scripts/r4c_harness.py    # maker (R4-C) HL 1 hari
R4C_QUEUE_BP=0.0 .venv-research/bin/python3 scripts/r4c_harness.py # sensitivitas margin 0 bp
```

---
*Hermes Anantara v3 · 05-Okt-2026 · Laporan riset R4 & R4-B · hasil negatif dilaporkan apa adanya.*
