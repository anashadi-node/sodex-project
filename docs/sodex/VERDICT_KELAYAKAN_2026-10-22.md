# VERDICT KELAYAKAN — Tujuan/Target/Timeline SoDEX setelah cabut Track-55

**Tanggal:** 22-Okt-2026 · **Pertanyaan:** apakah dengan mencabut Track-55, Tujuan/Target/Timeline SoDEX masih bisa terwujud baik?
**Metode:** baca ulang SELURUH mesin pencarian edge yang pernah dijalankan (PRAREG-19 s/d 27, ~21 mesin + 2 keluarga sinyal), jalankan ulang tracker resmi hari ini, bandingkan tren 3 snapshot (19/21/22-Okt).

## Jawaban singkat

**Mencabut Track-55 tidak mengubah kelayakan — track itu sudah mati sejak lahir (dokumen asalnya sendiri bilang butuh 406 hari sertifikasi, kita cuma punya 42).** Kelayakan sebenarnya 100% ditentukan oleh dua hal lain, dan **keduanya menunjukkan tren memburuk, bukan membaik**, per data hari ini:

1. **Buku aktif (TWO-WAY, Track-30)** — metrik geraknya **menjauh** dari syarat lolos, bukan mendekat.
2. **Pencarian edge baru (PRAREG-19→25, 21+ mesin)** — program ini sudah menyatakan diri **HABIS** ("jangan lanjutkan menambang keluarga ini") pada 9-Okt, dan tidak ada yang baru sejak itu.

Verdict jujur: **target 0,8%/window pada tenggat 25-Nov kemungkinan besar TIDAK tercapai lewat jalur yang sedang berjalan.** Ini bukan karena risetnya buruk — justru karena risetnya teliti dan sudah menguji habis satu keluarga mekanisme. Detail dan jalan keluar di bawah.

---

## 1. Analogi sederhana dulu

Bayangkan Anda mencari satu resep masakan yang pasti laku dijual dengan margin 0,8% dari modal toko per 30 jam jualan. Anda sudah coba **21 resep** (mesin trading) dan **2 keluarga bumbu** (strategi tren harian: 6 varian ukuran + 2 varian jumlah bahan) — total lebih dari **100 kombinasi diuji**, semuanya dicatat jujur termasuk yang gagal (bukan dibuang diam-diam). Resep terbaik yang ketemu baru menghasilkan **1/10 dari target**, dan dokumen ujinya sendiri bilang "kelas rasa ini sudah habis, jangan diulang lagi dengan bumbu beda tapi resep sama." Mencabut "izin masak 48 jam" (Track-55) tidak membuat resep yang sudah terbukti kurang itu jadi lebih enak. Yang dibutuhkan adalah **resep yang benar-benar baru**, bukan menghapus satu aturan dapur yang sudah tidak dipakai.

---

## 2. Data hari ini (22-Okt) — tren TWO-WAY (buku utama, Track-30)

| Tanggal snapshot | n window | Mean/window | **Median/window** | **Hit ≥0,8%** | WR keseluruhan |
|---|---|---|---|---|---|
| 19-Okt | 54 | +1,607% | **+0,422%** | 26/54 = 48,1% | 41,3% |
| 21-Okt | 57 | +1,146% | **+0,167%** | 27/57 = 47,4% | 40,9% |
| **22-Okt (hari ini)** | 58 | +1,272% | **−0,320%** | 27/58 = **46,6%** | **40,8%** |

**Median baru saja berbalik dari positif ke negatif.** Hit rate turun 3 snapshot berturut-turut (48,1%→47,4%→46,6%), **menjauh** dari syarat 50%, bukan mendekat. Window baru yang masuk dalam 3 hari terakhir **mayoritas kalah**, bukan menang — artinya performa *forward* (yang betul-betul baru, bukan hasil lama) sedang **menarik turun** rata-rata historis, bukan menaikkannya.

Gate REAL-WIDE (mesin kedua) hari ini: mean +0,641%, median **−0,307%**, hit 11/31=35,5% — lebih jauh lagi dari lolos.

**PRAREG-26 (lever seleksi mesin, andalan utama untuk verdict 25-Nov):** hari ini `mesin_terpilih_terakhir: []` — **nol mesin lolos seleksi saat ini** (butuh ≥20 trade/14hari DAN net PnL>0 — hampir semua mesin sedang rugi 14 hari terakhir). Window subset terisi **5 dari minimum 12** yang dibutuhkan. Proyeksi dari laju saat ini (0,497 window/hari) akan mencapai ~22 window pada 25-Nov — **cukup secara JUMLAH data**, tapi substansinya (apakah subset benar-benar mengalahkan buku penuh) belum bisa dijawab karena mesinnya sering kosong sama sekali.

---

## 3. Pencarian edge baru — program ini SUDAH menyatakan diri habis (9-Okt)

Ini bagian paling penting yang jarang terlihat dari ringkasan harian. Program pencarian mekanisme baru (bukan buku yang sudah jalan, tapi "resep baru") sudah menguji:

| Tahap | Yang diuji | Hasil |
|---|---|---|
| Sapuan awal | 108 sel parameter, 24 sel PRAREG-19, 21 mesin lain, 57 simbol | **0 lolos semua** |
| PRAREG-23 (H1, replikasi paper akademik) | Trend-following 6 koin, 2019-2026 | Sharpe 1,47 (lolos vs BTC) tapi **gagal p-value (p=0,0835)** dan gagal uji "bukan cuma hari beruntung". Hasil: **0,0738%/48 jam** |
| PRAREG-24 (4 varian ukuran posisi) | Naikkan eksposur dari 0,107 → 0,624 | 3 varian **lewat lantai 0,10%** (sampai 0,2804%/48j) — **TAPI** p-value justru **memburuk** (0,082→0,184) dan drawdown memburuk (−12%→−64%). Semua **GAGAL** |
| PRAREG-25 (breadth 6→20 koin) | Tambah jumlah koin untuk menaikkan daya statistik | **Hipotesis terbantahkan**: Sharpe malah turun, p-value malah memburuk (0,108→0,524). Koin tambahan cuma menyumbang varians, bukan alpha |

**Kesimpulan tertulis program ini sendiri (09-Okt, `PRAREG_25_HASIL_PENUTUPAN.md` §7):**
> *"Keluarga mesin trend-following harian long-only spot sudah HABIS pada ambang evidensi program. Jangan lanjutkan menambang keluarga ini."*
> *"SoDEX 0 mesin lulus dari 21; target 0,8%/48j butuh α ≥ 43,4 bps/48j — kelas yang belum pernah terlihat pada seluruh program ini."*

**Jarak ke tangga target yang pernah disetujui 09-Okt** (lantai 0,10% / sasaran 0,25% / stretch 0,40% / penuh 0,8%):

| Mekanisme terbaik yang pernah ditemukan | %/48 jam | Jarak ke lantai 0,10% | Jarak ke 0,8% |
|---|---|---|---|
| H1 baseline (PRAREG-23) | 0,0738% | kurang 1,36× | kurang 10,84× |
| V1 (eksposur dinaikkan, tapi p-value gagal) | 0,2636% | **lolos lantai** | kurang 3,03× |
| rangepos kuintil (dari memo 9-Okt, t=3,75, LOLOS BH-FDR) | ≈20–23 bps | **lolos lantai** | kurang **≈3,5×** |

**Rangepos kuintil adalah satu-satunya mekanisme yang pernah lolos uji statistik ketat (BH-FDR, t=3,75) sepanjang seluruh program** — tapi baru di level ≈20-23bps/48j, bukan 80bps. Dan mekanisme ini **belum pernah disertifikasi forward di SoDEX** (masih di Binance historis 7 tahun).

---

## 4. Jawaban langsung: apakah Tujuan/Target/Timeline masih bisa terwujud?

| | Status jujur | Alasan |
|---|---|---|
| **Tujuan** (profit bersih, swing, SoDEX) | ✅ **masih relevan dan realistis sebagai arah** | Tidak ada yang membatalkan "mencari strategi profitable" sebagai tujuan — yang terbukti sulit adalah ANGKA tertentu, bukan arahnya |
| **Target 0,8%/window** | ⚠️ **kemungkinan besar TIDAK tercapai pada 25-Nov lewat jalur sekarang** | Tren TWO-WAY memburuk 3 snapshot beruntun; program pencarian edge baru menyatakan diri habis; mekanisme terbaik yang pernah ditemukan (rangepos) masih ≈3,5× di bawah target |
| **Timeline 25-Nov (verdict PRAREG-26)** | ⚠️ **data akan cukup secara jumlah (≈22 window), tapi kemungkinan verdict = GAGAL, bukan tertunda** | Ini BUKAN masalah "kurang waktu" lagi (seperti Track-55) — ini masalah "mekanismenya belum ditemukan". Lebih banyak waktu dengan mekanisme yang sama tidak otomatis menaikkan edge (sudah dibuktikan PRAREG-25: breadth/waktu tambahan tidak membantu) |

**Perkiraan subjektif (bukan model formal, dari tren + lebar CI):** probabilitas TWO-WAY lolos A&B penuh (hit≥50% DAN median>0) pada 25-Nov — **rendah, kira-kira 1 dari 5 hingga 1 dari 3** — karena titik estimasi sudah di bawah syarat dan arah pergerakan 3 hari terakhir negatif, bukan netral.

**Ini bukan kegagalan proses.** Protokol pra-registrasi bekerja dengan benar — justru karena protokolnya ketat, kita TAHU dengan jujur bahwa keluarga mekanisme ini sudah habis, alih-alih terus menipu diri dengan menggeser ambang.

---

## 5. Apa yang BISA dilakukan agar Tujuan tetap terwujud (meski Target 0,8% di 25-Nov kemungkinan gagal)

| # | Opsi | Realistis untuk 25-Nov? | Realistis jangka menengah (Q1 2027)? |
|---|---|---|---|
| 1 | Tunggu PRAREG-26 25-Nov apa adanya, terima hasil jujur (GO atau NO-GO) | ✅ sudah berjalan, tidak perlu aksi baru | — |
| 2 | **Adopsi tangga target** (0,10/0,25/0,40/0,80%) sebagai target resmi, bukan hanya alat ukur mekanisme — ganti "harga mati 0,8%" dengan "harga mati = tangga, naik berjenjang setelah tiap tahap tersertifikasi" | ⚠️ perlu persetujuan user; tidak mengubah angka hasil, hanya mengubah definisi "sukses" | ✅ **jalur paling realistis secara ilmiah** — rangepos sudah di level "sasaran" (0,25%), tinggal disertifikasi forward di SoDEX |
| 3 | **Uji keluarga mekanisme yang BELUM dicoba** (per rekomendasi tertulis PRAREG-25 §9): mean-reversion berbasis likuidasi/OI, cross-sectional momentum market-neutral (bukan long-only), basis/carry lintas-venue | ❌ tidak akan selesai sebelum 25-Nov | ✅ ini satu-satunya jalan menuju 0,8% yang belum terbukti mati — karena yang sudah dicoba (trend-following long-only) **terbukti habis** |
| 4 | Sertifikasi forward rangepos kuintil di SoDEX (bukan cuma Binance historis) | ❌ butuh ≥12 window baru = ~15 hari minimum, mepet | ✅ realistis, dan ini mekanisme terbaik yang ada |
| 5 | Pertahankan 0,8% sebagai angka tapi perpanjang timeline (give-up baru, bukan 30-Nov) | ⚠️ keputusan user, dan riset PRAREG-25 menunjukkan **menambah waktu tanpa mekanisme baru tidak menaikkan edge** — jadi ini **tidak disarankan** tanpa dikombinasikan dengan opsi 3 |

**Rekomendasi saya (bijaksana, bukan hanya teknis):** Opsi **2 + 3 bersamaan**. Opsi 2 memberi kejujuran statistik langsung (tangga sudah ada basis datanya, tidak perlu riset baru). Opsi 3 adalah satu-satunya jalan ilmiah yang tersisa menuju 0,8% penuh — karena opsi 1/4/5 semuanya bergantung pada mekanisme yang **sudah dinyatakan habis oleh riset kita sendiri**.

---

## 6. Satu kalimat jujur untuk menutup

**Mencabut Track-55 benar dan perlu (itu sudah mati sejak 9-Okt), tapi itu bukan sebab masalah dan mencabutnya tidak menyelesaikan masalah.** Masalah sebenarnya: dari >100 kombinasi mekanisme yang diuji dengan disiplin ilmiah tinggi sejak awal Oktober, **belum satu pun mendekati 0,8%/window**, dan buku yang sedang berjalan sekarang justru bergerak menjauh dari syarat lolos dalam 3 hari terakhir. Target 0,8% pada 25-Nov **kemungkinan besar tidak tercapai** — bukan karena kurang usaha, tapi karena buktinya memang belum ada. Jalan ke depan yang jujur: terima verdict 25-Nov apa adanya, dan mulai (sekarang, paralel) menguji keluarga mekanisme yang benar-benar baru — bukan variasi dari yang sudah terbukti habis.

*Disusun 22-Okt-2026 · seluruh angka dari dokumen ber-hash yang sudah ada + 2 eksekusi skrip tracker hari ini · tidak ada parameter/target/kode yang diubah.*
