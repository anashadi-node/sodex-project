# Mencari Kunci Rezim Pasar

*Penjelasan Sederhana A–Z tentang Strategi, Metode, dan Target Proyek SoDEX*

**Disusun untuk:** Mas Anas
**Tanggal:** 5 Oktober 2026
**Oleh:** Hermes Anantara v3 — Divisi SoDEX
**Berkas pendamping:** `D07_RCA_FILTER_DAN_FAKTOR_2026-10-05.md`, `D08_PREDIKTOR_REZIM_EXANTE_2026-10-05.md`

---

## Daftar Isi

- [1. Ringkasan Dua Menit (buat yang sibuk)](#1-ringkasan-dua-menit-buat-yang-sibuk)
- [2. Target Kita: Sebenarnya Mengejar Apa?](#2-target-kita-sebenarnya-mengejar-apa)
- [3. SoDEX dan "twoway" Itu Apa?](#3-sodex-dan-twoway-itu-apa)
- [4. Kamus Sederhana: 12 Istilah yang Sering Muncul](#4-kamus-sederhana-12-istilah-yang-sering-muncul)
- [5. "Prediktor Ex-Ante" Itu Apa? (Analogi Cuaca)](#5-prediktor-ex-ante-itu-apa-analogi-cuaca)
- [6. Masalah Sebenarnya: Strategi Ini Menang Karena Apa?](#6-masalah-sebenarnya-strategi-ini-menang-karena-apa)
- [7. Cara Saya Menyelidiki: 8 Langkah](#7-cara-saya-menyelidiki-8-langkah)
- [8. Yang Ditemukan: Angka Sebenarnya](#8-yang-ditemukan-angka-sebenarnya)
- [9. Empat Jebakan yang Hampir Menipu Saya](#9-empat-jebakan-yang-hampir-menipu-saya)
- [10. Kenapa Temuannya Belum Bisa Dipakai?](#10-kenapa-temuannya-belum-bisa-dipakai)
- [11. Apa Artinya untuk Target 0,8% per 48 Jam](#11-apa-artinya-untuk-target-08-per-48-jam)
- [12. Langkah Berikutnya](#12-langkah-berikutnya)
- [13. Catatan Verifikasi dan Cara Mengulang](#13-catatan-verifikasi-dan-cara-mengulang)

---

## 1. Ringkasan Dua Menit (buat yang sibuk)

Kita punya mesin trading otomatis di bursa SoDEX. Bulan-bulan ini hasilnya **tidak mencapai target**. Saya diminta mencari tahu **kenapa** — bukan menambal dengan trik.

**Tiga hal yang saya temukan, berurutan:**

| # | Temuan | Artinya |
|---|---|---|
| 1 | Masalahnya **bukan biaya transaksi** | Bahkan kalau biaya nol, periode terakhir tetap rugi. Jadi menurunkan fee tidak akan menolong. |
| 2 | Masalahnya **bukan strategi masuk yang buruk** | Saya uji 12 cara menyaring entry. **Nol** yang lolos uji. |
| 3 | Masalahnya **bukan bug** | Kode tidak berubah di periode kritis. Tidak ada kesalahan program. |

**Lalu apa masalahnya?** Strategi ini sebenarnya **bertaruh bahwa koin kecil (altcoin) akan naik lebih cepat dari Bitcoin**. Betnya menang di satu musim, kalah di musim lain.

**Kemudian saya kejar satu pertanyaan lanjutan yang lebih menguntungkan:** *bisakah kita tahu lebih dulu musim mana yang sedang berjalan, lalu hanya berdagang di musim yang bagus?*

**Jawabannya: BISA — tapi belum cukup kuat.** Saya menemukan satu pengukur yang **terbukti secara statistik** (peluang kebetulan cuma 1,2%): **kalau volatilitas Bitcoin sedang tinggi, strategi ini bekerja lebih baik (+75 poin basis per trade).**

**Tapi** pada rezim pasar yang sedang berjalan sekarang, angkanya masih **−1,44 poin basis**, sementara biaya pulang-pergi butuh **+16 poin basis**. Artinya: **masih belum layak dijalankan dengan uang.**

**Keputusan:** tetap **jangan GO-LIVE**. Tapi sekarang kita punya peta yang jelas, bukan tebakan.

> **Analogi cepat:** Saya seperti dokter yang mendapati pasien tidak sakit karena infeksi (biaya), bukan karena salah makan (filter). Ternyata pasiennya **alergi musim**. Saya menemukan tes alerginya — tapi tesnya belum cukup tajam untuk dipakai memutuskan operasi.

---

## 2. Target Kita: Sebenarnya Mengejar Apa?

Target proyek SoDEX adalah **0,8% dari TOTAL modal wallet per 48 jam** — dihitung dari seluruh isi wallet (spot + perps), **bukan** dari ukuran satu posisi.

**Kenapa pembedaan ini penting?**

Bayangkan kamu punya tabungan Rp100 juta, lalu kamu memakai Rp5 juta untuk berdagang dan untung 10%.

| Cara menghitung | Hasil | Jujur? |
|---|---|---|
| Dari uang yang dipakai (Rp5 juta) | +10% | ❌ Menyesatkan |
| Dari **seluruh** tabungan (Rp100 juta) | +0,5% | ✅ Inilah yang dipakai |

Banyak orang tertipu angka pertama. Kita memakai angka kedua **sengaja**, karena itulah ukuran yang benar-benar menentukan kekayaan bertambah atau tidak.

**Konsekuensinya:** kalau kita hanya memakai sebagian kecil modal, maka persentase yang kita butuhkan dari modal tersebut menjadi **sangat besar**. Itulah kenapa target ini **sulit tetapi jujur** — dan itu memang harga mati yang sudah disepakati.

---

## 3. SoDEX dan "twoway" Itu Apa?

| Istilah | Penjelasan bahasa awam |
|---|---|
| **SoDEX** | Sebuah bursa kripto terdesentralisasi (tanpa perantara bank). Kita berdagang kontrak berjangka di sini. |
| **Perpetual / perps** | Kontrak "taruhan harga" tanpa tanggal kedaluwarsa. Bisa bertaruh harga naik (LONG) atau turun (SHORT). |
| **twoway** | Nama mesin kita. Namanya begitu karena ia bisa membuka dua arah: LONG saat pasar naik, SHORT saat pasar turun. |
| **LONG** | Bertaruh harga akan NAIK. Untung kalau benar. |
| **SHORT** | Bertaruh harga akan TURUN. Untung kalau benar. |
| **Swing trading** | Gaya berdagang yang menahan posisi **1–30 jam**, bukan hitungan detik. Seperti menunggu ombak besar, bukan riak kecil. |

**Penting dicatat:** mesin `twoway` saat ini **hampir hanya membuka LONG**. Sisi SHORT-nya praktis mati sejak 1 September 2026 karena filter "death-cross" menahannya. Jadi dalam praktiknya, kita sedang menilai **sisi LONG-nya saja**.

---

## 4. Kamus Sederhana: 12 Istilah yang Sering Muncul

| Istilah | Arti sederhana |
|---|---|
| **Alpha** | Keuntungan dari **kecerdasan** kita sendiri. Kalau ini yang ada, hasilnya bertahan di musim apa pun. |
| **Beta** | Keuntungan karena **ikut arus pasar**. Naik saat pasar naik — bukan karena kita pintar. |
| **Basis poin (bps)** | Satuan kecil. 1 bps = 0,01%. Jadi 100 bps = 1%. Dipakai supaya tidak salah baca koma. |
| **Fee pulang-pergi** | Biaya masuk + biaya keluar. Kita: **8 bps** sekali jalan penuh, jadi bolak-balik **16 bps**. |
| **Excess (kelebihan)** | Hasil setelah dikurangi "apa yang seharusnya didapat kalau cuma ikut pasar". Ini penentu apakah kita benar-benar punya skill. |
| **Rezim** | "Musim" pasar. Musim altcoin menang, musim Bitcoin menang, musim sepi, musim panik. |
| **Ex-ante** | Diketahui **sebelum** kejadian. Contoh: ramalan cuaca pagi. |
| **Ex-post** | Diketahui **sesudah** kejadian. Contoh: laporan cuaca sore. |
| **Filter** | Menyaring mana trade yang boleh jalan. Seperti **menyortir ikan** dari jaring. |
| **Gate (gerbang)** | Mematikan/menyalakan **seluruh mesin**. Seperti **memilih kolam** mana yang digarap. |
| **DSR** | Uji yang mengetatkan penilaian sesuai **berapa banyak ide yang sudah dicoba**. Makin banyak mencoba, makin ketat. |
| **Holdout / jendela forward** | Uji kejujuran: jalankan sistem di masa depan yang belum pernah dilihat, tanpa mengubah apa pun. |

---

## 5. "Prediktor Ex-Ante" Itu Apa? (Analogi Cuaca)

### 5.1 Bedanya "meramal" dan "mengintip"

Bayangkan kamu petani.

**Pengintip** adalah orang yang sore baru bilang, *"tadi pagi sepertinya hujan ya"* — setelah melihat tanah basah. Dia tidak meramal apa pun; dia membaca masa lalu.

**Peramal** adalah orang yang pagi-pagi buta sudah bilang, *"bawa payung, siang hujan"* — **sebelum** setitik air jatuh.

**Prediktor ex-ante = sang peramal.** Syaratnya satu dan mutlak:

> Setiap angka yang dipakai untuk memutuskan **harus sudah ada sebelum keputusan itu diambil**.

Dalam sistem kita: kalau kita memutuskan membuka posisi jam 14:00, maka semua pengukur yang kita pakai hanya boleh berasal dari data **sebelum jam 14:00**. Data jam 14:05 tidak boleh "bocor" masuk.

**Kenapa ini sangat penting?** Karena meramal dengan data masa depan selalu terlihat hebat di uji coba, lalu **hancur total** saat uang sungguhan dipakai. Ini kesalahan paling mematikan di dunia kuantitatif. Kita menyebutnya **look-ahead bias** (mengintip ke depan).

### 5.2 Pengukur apa saja yang saya uji?

Semuanya **hanya** dari data yang sudah ada sebelum posisi dibuka:

| Kode | Nama manusiawi | Cara kerjanya |
|---|---|---|
| K1 | **Kekuatan alt (1 hari)** | Apakah koin kecil naik lebih cepat dari Bitcoin dalam 24 jam terakhir? |
| K2 | **Kekuatan alt (7 hari)** | Sama, tapi jendela seminggu. |
| K3 | **Keluasan pasar** | Berapa persen koin yang sedang naik? |
| K4 | **Volatilitas Bitcoin** | Seberapa "goncang" harga Bitcoin 24 jam terakhir? |
| K5 | **Tren Bitcoin** | Bitcoin sedang di atas atau di bawah rata-rata jangka panjangnya? |

### 5.3 Kenapa saya hanya menguji lima ini?

Karena **aturan anti-menipu-diri-sendiri** (anti-p-hacking) berbunyi:

> Kandidat harus **dideklarasikan lebih dulu**, sebelum melihat hasil. Setelah hasil keluar, **tidak boleh** menambah ide baru lalu mengaku "ini dia yang benar!".

**Analogi:** Kalau kamu menembak panah dulu, baru menggambar sasarannya di tempat panah menancap — itu bukan jago menembak, itu menipu diri. Limanya sudah saya tulis di kode sebelum dijalankan. Dan setiap kandidat **membayar penalti** karena sudah ikut diuji — itulah gunanya uji DSR.

---

## 6. Masalah Sebenarnya: Strategi Ini Menang Karena Apa?

### 6.1 Potong waktu menjadi tiga bagian

Angka rata-rata sepanjang masa itu **menipu**. Contohnya begini:

> Rata-rata cuaca tahun ini "sejuk". Padahal itu gabungan musim hujan yang dingin dan kemarau yang terik. Rata-ratanya nyaman; kenyataannya ekstrem bergantian.

Maka saya potong periode studi menjadi **tiga segmen waktu yang setara**, dan menilai masing-masing.

**Hasil untuk sisi LONG:**

| Segmen | Jumlah trade | Menang? | Kelebihan (excess) | Setelah biaya 2× |
|---|---:|---:|---:|---:|
| S1 (06 Agu – 04 Sep) | 108 | 38,9% | −10,19 bps | −26,19 bps |
| S2 (04 Sep – 19 Sep) | 108 | 50,9% | **+62,96 bps** | +46,96 bps |
| S3 (19 Sep – 03 Okt) | 109 | 29,4% | **−28,40 bps** | −44,40 bps |

**Rata-rata sederhananya +8,01 bps — tampak lumayan.** Tetapi rata-rata itu cuma gabungan dari: rugi, untung besar, rugi.

### 6.2 Batas yang menohok

Batas antara "untung besar" dan "rugi" adalah **19 September 2026** — **tepat tanggal mesin SoDEX dihentikan sementara (halt)**.

Saya punya dugaan: mungkin kodenya berubah saat itu, dan perubahan itulah biang keroknya.

### 6.3 Dugaan itu gugur

Saya periksa riwayat perubahan kode mesin pada 10–25 September: **tidak ada satu pun perubahan.** Kode sama persis. Berarti perubahan hasil **bukan** dari perubahan program.

### 6.4 Jawaban sebenarnya

Lalu saya periksa kondisi pasar di tiap segmen:

| Segmen | Pergerakan Bitcoin | Volatilitas | Hasil strategi |
|---|---|---|---|
| S1 | **meledak +23,36%** | 0,428% (tinggi) | rugi secara relatif |
| S2 | tenang +2,08% | 0,341% (rendah) | **untung besar** |
| S3 | naik +4,50% | 0,371% | rugi |

**Inilah kuncinya:**

> Strategi ini, secara diam-diam, adalah **taruhan bahwa koin kecil mengalahkan Bitcoin**. Ia menang saat "musim altcoin" datang (September), dan kalah saat Bitcoin yang memimpin (Agustus & Oktober).

**Bukti paling kuat:** pada periode terakhir (S3) strategi **rugi −28,40 bps sebelum biaya apa pun dihitung**. Kalau biaya nol saja rugi, maka **menurunkan fee tidak akan menyelamatkan apa pun.** Masalahnya di arah taruhan, bukan di ongkos.

Ini konsisten dengan analisis lebih lama yang menunjukkan angka **beta = 0,887** dan **alpha ≈ 0**. Beta tinggi = ikut arus. Alpha nol = tidak ada kecerdasan sendiri.

---

## 7. Cara Saya Menyelidiki: 8 Langkah

| Langkah | Yang saya lakukan | Kenapa |
|---|---|---|
| **1** | Kumpulkan semua trade yang sudah tertutup | Dasar penilaian |
| **2** | Uji 12 cara menyaring entry | Mungkin entry-nya yang salah pilih |
| **3** | Potong waktu jadi 3 segmen | Cek apakah hasilnya bertahan, bukan sekali mujur |
| **4** | Cek riwayat kode di periode kritis | Mungkin ada bug |
| **5** | Ambil data harga alt (234.634 batang 15 menit) | Perlu bahan mentah untuk meramal |
| **6** | Bangun 5 prediktor **ex-ante** dari data itu | Calon "kunci rezim" |
| **7** | Uji tiap prediktor dengan uji permutasi | Membuang hasil yang cuma kebetulan |
| **8** | Koreksi multiple-testing (BH-FDR) | Menghukum diri karena menguji banyak ide |

### 7.1 Apa itu "uji permutasi"? (analogi)

**Pertanyaan:** *"Kita menang lebih besar saat volatilitas tinggi. Itu nyata, atau cuma kebetulan?"*

**Cara mengujinya (analogi):** Ambil 316 kartu hasil trade. Acak kartunya berulang kali **10.000 kali**, lalu lihat: seberapa sering pengacakan murni menghasilkan selisih **sebesar** yang kita amati?

- Kalau pengacakan **sering** menghasilkan selisih sebesar itu → hasil kita **cuma kebetulan**. ❌
- Kalau pengacakan **hampir tidak pernah** sebesar itu → hasil kita **nyata**. ✅

Hasil kita: dari 10.000 pengacakan, hanya **1,22%** yang mencapai selisih sebesar milik kita. Maka nilainya nyata.

### 7.2 Apa itu koreksi BH-FDR? (analogi)

**Analogi:** Kalau kamu melempar 100 koin, hampir pasti ada yang muncul "kepala" 7 kali berturut-turut. Itu bukan koin ajaib — itu **hukum peluang**.

Karena saya menguji **5 prediktor**, maka salah satunya bisa tampak hebat **hanya karena saya menguji lima**. Koreksi BH-FDR mengetatkan ambang: dari 5% menjadi **2%**. Prediktor terbaik kita mencapai **1,22%** — jadi **tetap lolos** meski sudah dihukum.

---

## 8. Yang Ditemukan: Angka Sebenarnya

### 8.1 Lima prediktor diuji

Ambang "layak" = 16 bps (biaya pulang-pergi). Yang lebih besar dari nol berarti menguntungkan.

| Prediktor | Selisih (vol tinggi vs rendah) | Peluang kebetulan (p) | Verdict |
|---|---:|---:|---|
| **Volatilitas BTC ≥ median** | **+75,16 bps** | **0,0122** | ✅ **NYATA** |
| Kekuatan alt 1 hari > BTC | −38,02 bps | 0,2633 | ❌ |
| Kekuatan alt 7 hari > BTC | −37,79 bps | 0,2688 | ❌ |
| Keluasan pasar > 50% | −46,34 bps | 0,1560 | ❌ |
| Tren BTC > rata-rata | −18,84 bps | 0,5388 | ❌ |

**Hanya satu yang nyata: volatilitas Bitcoin.** Empat lainnya tidak berbeda dari kebetulan.

### 8.2 Tapi arahnya KEBALIKAN dari dugaan saya

Saya menduga: *"pasar tenang = lebih aman = lebih untung."*

Kenyataannya: **pasar goncang = lebih untung.** Dugaan saya salah, dan data yang menang. (Ini alasan kenapa saya wajib mendeklarasikan kandidat lebih dulu — supaya tidak "memindahkan sasaran" setelah melihat hasil.)

### 8.3 Bahan bacaan penting: kembarannya

Lihat tabel di atas — empat prediktor lain **negatif**. Artinya: kalau kita memakai **kebalikannya**, angkanya jadi positif besar:

| Kandidat (kebalikan) | Edge | Setelah biaya 2× |
|---|---:|---:|
| "Koin kecil sedang KALAH dari BTC" | +56,53 bps | +40,53 bps |
| "Pasar sedang menyempit (mayoritas turun)" | +41,11 bps | +25,11 bps |
| "BTC di bawah rata-rata panjang" | +39,38 bps | +23,38 bps |

**Bacaan sederhananya:** mesin LONG ini punya kecenderungan **membeli saat pasar sedang lesu**, lalu menuai saat pasar pulih. Itu masuk akal secara nalar dagang — tetapi harus saya sampaikan dengan jujur: **ketiga kebalikan ini tidak lolos** uji 3-segmen (mereka juga tidak cukup presisi untuk dinilai).

---

## 9. Empat Jebakan yang Hampir Menipu Saya

Bagian ini saya tulis sengaja. Karena kejujuran yang paling berguna adalah **mengakui di mana diri sendiri hampir salah**.

### Jebakan 1 — "Volatilitas tinggi" bisa jadi cuma nama lain untuk "bulan tertentu"

Volatilitas Bitcoin **menurun** dari bulan ke bulan (Agustus tinggi, Oktober rendah).

**Bahayanya:** kalau begitu, "volatilitas tinggi" sebenarnya cuma cara lain bilang **"jangan trading bulan Agustus"** — bukan kecerdasan, hanya penanggalan.

**Cara saya membuang jebakan ini:** Saya belah data **di dalam setiap segmen**, memakai ambang masing-masing. Dengan begitu, faktor waktu **mati total** — tiap segmen dibandingkan dengan dirinya sendiri. Hasilnya: pemisahannya **masih ada**, jadi ini bukan sekadar penanggalan.

### Jebakan 2 — "Untung besar" bisa jadi cuma 2-3 trade keberuntungan

Selisih di segmen S2 mencapai **+136 bps**. Angka sebesar itu **wajib dicurigai**.

**Cara saya memeriksa:** Saya potong 10% nilai teratas dan terbawah, dan menghitung sumbangan 3 trade terbaik.

**Hasilnya:** 3 trade teratas hanya menyumbang **0,25 pp** masing-masing. Distribusinya memang lebar (10% terburuk ≈ −2,2%; 10% terbaik ≈ +4,2%). Jadi ini **bukan** 2-3 trade mujur — ini memang variasi yang lebar. Curiga itu terjawab, tapi dengan hasil yang menenangkan.

### Jebakan 3 — UJI SAYA SENDIRI SALAH ⚠️

Ini yang paling penting.

Uji pertama saya melaporkan **semua prediktor "tidak signifikan"**. Termasuk yang sebenarnya nyata.

**Kenapa?** Saya memakai prosedur yang salah: saya membangun "dunia tanpa efek" (data diacak), lalu memeriksa apakah **dunia tanpa efek itu** terpisah dari nol. Tentu saja tidak — dunia tanpa efek **selalu** berpusat di nol. Jadi syaratnya tidak pernah terpenuhi, dan **semua** dilaporkan gagal.

**Bagaimana saya tahu itu bug?** Ada kejanggalan yang tidak masuk akal: nilai yang saya amati (**+71,35**) berada **di luar rentang kepercayaannya sendiri**. Itu mustahil untuk prosedur yang benar. Kejanggalan itulah yang membongkar kesalahannya.

**Setelah diperbaiki:** p = 0,0122 → **NYATA**.

> **Pelajaran:** kalau saya tidak memeriksa kejanggalan itu, saya akan melaporkan "tidak ada apa-apa" dan **membuang temuan nyata**. Kecurigaan terhadap hasil yang "terlalu rapi" bekerja dua arah.

### Jebakan 4 — Angka yang tampak sah tapi artinya salah

Saat data masih sedikit ("pemanasan"), program saya melaporkan **"return 24 jam"** padahal yang dihitung hanya **15 menit**.

**Bahayanya:** angkanya tampak normal, tidak error, tidak crash — tapi **artinya bohong**. Prediktor menelan angka palsu itu sebagai sinyal.

**Bagaimana ketahuan?** Bukan dari mata saya, tapi dari **unit test** yang sengaja saya tulis untuk memeriksa kasus ekstrem. Test itu **gagal**, dan kegagalan itulah yang mengungkap bug.

**Perbaikannya:** jendela waktu harus benar-benar terpenuhi. Kalau belum, kembalikan "tidak ada data" — bukan angka palsu.

---

## 10. Kenapa Temuannya Belum Bisa Dipakai?

Ini bagian yang paling penting untuk dipahami, karena di sinilah banyak orang keliru mengambil kesimpulan.

### 10.1 Masalahnya: presisi

Setiap trade punya variasi hasil ±264 bps (sekitar 2,6%). Ketika saya memotong data menjadi segmen-segmen kecil (53 trade per kelompok), ketelitian hasilnya jadi:

> **± 146 bps**

Artinya: efek sebesar **75 bps** yang kita cari itu **lebih kecil dari ketelitian alat ukurnya**. Seperti mencoba menimbang bulu mata dengan timbangan beras.

### 10.2 Angka per segmen

| Segmen | Setelah biaya 2× | Ketelitian | Kesimpulan JUJUR |
|---|---:|---:|---|
| S1 | −24,96 bps | ±119 bps | **terlalu bising untuk dinilai** |
| S2 | +89,30 bps | ±157 bps | tampak layak |
| S3 (terkini) | **−1,44 bps** | ±146 bps | **terlalu bising untuk dinilai** |

### 10.3 Amandemen aturan (penting)

Aturan lama saya: *"sebuah temuan harus positif di KETIGA segmen waktu, kalau tidak, dianggap gagal."*

**Aturan itu terlalu keras.** Menyebut S1 "gagal" padahal alat ukurnya hanya presisi ±119 bps adalah **kesalahan statistik** — kita menuntut bukti yang instrumen kita sendiri tidak mampu berikan.

**Aturan yang diperbaiki:**

> Segmen yang **tidak cukup presisi** dilaporkan sebagai **"belum dinilai"** — bukan **"gagal"**.

### 10.4 Jadi kenapa tetap tidak dijalankan?

Karena **kehati-hatian adalah kebijakan yang benar**, walaupun secara statistik belum tuntas:

1. **Titik estimasi di rezim terkini = −1,44 bps**, sementara butuh **+16 bps**. Kita tidak boleh mempertaruhkan uang pada perkiraan yang belum terpisah dari nol.
2. **Ini lead, bukan obat.** Ia layak dipantau, bukan dipasang sekarang.
3. **Aturan kami tegas:** tidak ada gerbang yang dipasang ke produksi sebelum lolos uji 3-segmen yang presisi.

---

## 11. Apa Artinya untuk Target 0,8% per 48 Jam

Mari saya sambungkan kembali ke target besar.

| Pertanyaan | Jawaban berdasarkan bukti |
|---|---|
| Apakah masalahnya biaya? | **Bukan.** Periode terakhir rugi sebelum biaya apa pun. |
| Apakah masalahnya entry? | **Bukan.** 12 filter diuji, nol layak. |
| Apakah masalahnya bug? | **Bukan.** Kode tidak berubah di periode kritis. |
| Apakah masalahnya strategi? | **Ya.** Ini taruhan arah (beta 0,887, alpha ≈ 0), bukan kecerdasan. |
| Apakah ada jalan keluar? | **Ada petunjuknya** — rezim volatilitas — **tapi belum cukup kuat.** |
| Aman dijalankan dengan uang sekarang? | **Tidak.** Estimasi di rezim terkini masih di bawah ambang biaya. |

**Kesimpulan yang jujur:**

> Target 0,8%/48 jam **belum bisa dicapai** oleh mesin `twoway` sebagaimana adanya. Bukan karena kesalahan teknis, tetapi karena mesin ini **tidak memiliki alpha** — ia hanya meminjam gerakan pasar, dan pinjaman itu sedang mahal.

**Yang TIDAK saya lakukan (dan ini sengaja):**

- ❌ Tidak menurunkan target supaya terlihat tercapai
- ❌ Tidak memasang leverage untuk mengejar angka (itu memperbesar risiko, bukan menambah kecerdasan)
- ❌ Tidak melonggarkan gerbang T1
- ❌ Tidak memasang gerbang rezim yang belum lolos uji, hanya supaya ada "kemajuan"
- ❌ Tidak mengubah fee tier atau mengaktifkan jalur maker yang sudah terbukti nol fill

---

## 12. Langkah Berikutnya

| Prioritas | Langkah | Alasan |
|---|---|---|
| **1** | Lanjutkan jendela forward 30 hari (sedang berjalan, hari ke-3 dari 30) | Ini **satu-satunya** cara sah menguji T1, sekaligus **menambah presisi** |
| **2** | Kumpulkan lebih banyak trade (≈5,5 trade/hari) | Presisi naik seiring jumlah data — itu menghukum atau menguatkan temuan ini |
| **3** | Uji ulang **volatilitas** saat data cukup (±100 trade/kelompok) | Untuk memisahkan efek 75 bps dari derau secara meyakinkan |
| **4** | Cari mesin **kedua** yang tidak berkorelasi | Menurunkan risiko total, bukan menambah taruhan sejenis |
| **5** | Biarkan sisi SHORT dinilai ulang saat rezim berubah | Sisi itu praktis mati; jangan dipaksa hidup tanpa bukti |

**Perkiraan waktu:** dengan 5,5 trade/hari, untuk mendapatkan presisi ±40 bps (cukup untuk menilai efek 75 bps) dibutuhkan sekitar **1.700 trade** per kelompok — artinya butuh **berbulan-bulan**, bukan berminggu-minggu. Karena itu **sabar adalah bagian dari strategi**, bukan kegagalan.

---

## 13. Catatan Verifikasi dan Cara Mengulang

Semua angka dalam dokumen ini dihasilkan oleh program yang bisa dijalankan ulang. **Tidak ada angka yang saya karang.**

### 13.1 Cara mengulang

```bash
cd ~/anantara-sakti

# 1. Cek sumber data yang tersedia
python3 scripts/sodex_regime_source_discovery.py

# 2. Jalankan studi prediktor rezim (read-only)
python3 scripts/sodex_regime_gate_study.py --dry-run

# 3. Jalankan test yang mengunci anti-look-ahead
python3 -m pytest tests/test_sodex_regime_gate_study.py -q
```

### 13.2 Berkas terkait

| Berkas | Isi |
|---|---|
| `reports/sodex/D07_RCA_FILTER_DAN_FAKTOR_2026-10-05.md` | Analisis akar masalah: kenapa filter gagal, kenapa ini soal faktor |
| `reports/sodex/D08_PREDIKTOR_REZIM_EXANTE_2026-10-05.md` | Laporan teknis lengkap studi prediktor rezim |
| `scripts/sodex_regime_gate_study.py` | Program studi (5 prediktor, uji 3 segmen) |
| `tests/test_sodex_regime_gate_study.py` | 12 test, termasuk 4 test anti-look-ahead |

### 13.3 Jaminan yang dipegang

| Jaminan | Status |
|---|---|
| Tidak ada data masa depan dipakai | ✅ dikunci 4 unit test |
| Kandidat dideklarasikan sebelum melihat hasil | ✅ 5 prediktor, di kode |
| Penalti multiple-testing diterapkan | ✅ `n_trials` + BH-FDR |
| Registri uji tidak pernah direset | ✅ append-only |
| Jendela forward tidak disentuh | ✅ read-only |
| Gerbang T1 tidak dilonggarkan | ✅ |
| Perubahan kode lewat review sebelum commit | ✅ |
| Suite test hijau | ✅ **4.486 lulus, 0 gagal** |

---

### Penutup

Tiga kalimat yang saya ingin Anda bawa:

1. **Masalahnya bukan ongkos, bukan bug, bukan cara masuk** — tetapi bahwa mesin ini **tidak punya kecerdasan sendiri**; ia meminjam gerakan pasar.
2. **Saya menemukan satu kunci rezim yang nyata secara statistik** (volatilitas Bitcoin, peluang kebetulan 1,2%) — **tetapi kuncinya belum cukup tajam** untuk dipakai memutuskan.
3. **Karena itu: jangan dijalankan dengan uang sekarang.** Tapi sekarang kita tahu persis apa yang harus ditunggu dan diuji — dan itu jauh lebih berharga daripada optimisme tanpa dasar.

---

*Dokumen ini disusun oleh Hermes Anantara v3 — Divisi SoDEX | 5 Oktober 2026*
*Semua angka dapat direproduksi dari `scripts/sodex_regime_gate_study.py`.*
