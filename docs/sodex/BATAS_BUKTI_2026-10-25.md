# BATAS BUKTI — APA YANG BISA & TIDAK BISA DIBUKTIKAN SEBELUM 25 NOV 2026

**Tanggal:** 25 Okt 2026 · **Ambang:** |t| ≥ 4,11 (N=1.261, Bonferroni α=0,05)
**Pertanyaan:** dengan data yang mungkin ada sampai 25 Nov, klaim apa yang sah?

---

## 1. Aritmetika dasar

Efek terkecil yang bisa dibuktikan (MDE) = `t × sd / √n`.

| Buku | n window | sd | **MDE** | Target 0,8% |
|---|---|---|---|---|
| REALWIDE 30 jam | 63 | 8,72% | **4,52%** | 5,6× di bawah MDE |
| REALWIDE 72 jam | 26 | 14,45% | **11,65%** | 14,6× |
| TWOWAY 72 jam | 27 | 27,40% | **21,67%** | 27,1× |

Dengan tambahan window sampai 25 Nov (≈31 hari):

| Buku | n menjadi | MDE |
|---|---|---|
| REALWIDE 30 jam | 88 | **3,82%** |
| REALWIDE 72 jam | 36 | **9,90%** |

**Artinya:** bahkan jika edge sebenarnya tepat 0,8%, kita **tidak akan bisa**
membuktikannya dengan t ≥ 4,11 sebelum 25 Nov. Yang akan terlihat hanyalah noise.

## 2. Berapa window yang benar-benar dibutuhkan?

| Kondisi | n window | Waktu (30 jam/window) |
|---|---|---|
| sd 8,72% (satu simbol) | **2.007** | **6,9 tahun** |
| portofolio 10 simbol, ρ=0,5 (sd 6,47%) | 1.104 | 3,8 tahun |
| portofolio 10 simbol, ρ=0,2 (sd 4,61%) | 562 | 1,9 tahun |
| portofolio 10 simbol, ρ=0,1 (sd 3,80%) | 381 | 1,3 tahun |

**Satu-satunya tuas struktural yang mengubah aritmetika ini adalah diversifikasi**
(menurunkan sd portofolio), bukan pencarian sinyal tambahan.

## 3. Yang BISA dibuktikan sebelum 25 Nov

| Klaim | Alat | Status |
|---|---|---|
| Spread menutup fee maker | kampanye H1 | data 1 Nov |
| Adverse selection < spread | kampanye H2 | data 1 Nov |
| Kedalaman cukup untuk $250 | kampanye H4 | data 1 Nov |
| MM net > 0 | kampanye H6 | data 1 Nov |
| Biaya total per round-trip | ledger + fee resmi | sudah: 6,49 bps |
| Tidak ada edge di 1.080 uji harga | grid BH-FDR | sudah: 0 lolos |

**Itu semua adalah bukti MEKANISME dan BIAYA — bukan bukti target 0,8%.**

## 4. Yang TIDAK bisa dibuktikan sebelum 25 Nov

1. Bahwa suatu mesin mencapai **0,8% per window** secara statistik.
2. Bahwa **skew opsi** memprediksi reversal (butuh 120 hari; kolektor kini 180 hari).
3. Bahwa **paper test** akan menghasilkan hal yang sama di uang nyata.
4. Bahwa **target 0,8%** bisa dicapai dengan modal $3,17 (lot minimum & fee).

## 5. Implikasi untuk keputusan 25 Nov

Keputusan **tidak boleh** berbunyi "apakah 0,8% terbukti?". Jawabannya sudah pasti
**tidak** — bukan karena strateginya buruk, tapi karena **waktu tidak cukup untuk
mengumpulkan bukti sebesar itu**.

Keputusan yang sah berbunyi:

> "Apakah mekanisme venue + biaya + expectancy cukup baik untuk melanjutkan
> ke uang nyata dengan ukuran kecil, sambil target 0,8% tetap menjadi sasaran
> operasional yang diuji bertahun-tahun?"

## 6. Tiga opsi kebijakan (butuh keputusan Mas Anas)

| Opsi | Isi | Konsekuensi |
|---|---|---|
| **A** | Pertahankan target 0,8%; verdict Nov hanya soal mekanisme; target diuji bertahun-tahun | jujur, tapi target tidak akan "terbukti" dalam waktu dekat |
| **B** | Definisikan ulang "berhasil" = expectancy positif setelah biaya (bukan 0,8%) | bisa dibuktikan lebih cepat, tetapi mengubah target (perlu persetujuan eksplisit) |
| **C** | Naikkan frekuensi + diversifikasi 10+ simbol tak berkorelasi untuk menurunkan sd | secara aritmetika paling kuat (1,9 tahun → 1,3 tahun), butuh modal & infrastruktur lebih besar |

**Tidak ada opsi yang membuat 0,8% terbukti dalam 31 hari.** Itu fakta aritmetika,
bukan pesimisme.

## 7. Prediksi falsifiable

1. Jika kampanye 1 Nov menunjukkan H1/H2/H6 gagal → tidak ada strategi apa pun
   yang bisa menutup biaya di SoDEX; venue ditutup untuk swing.
2. Jika H1/H2/H4/H6 lulus → mekanisme layak; target tetap belum terbukti,
   dan uji berikutnya adalah forward kecil, bukan klaim 0,8%.
3. Jika ada klaim "0,8% tercapai" dengan n < 2.007 window tanpa diversifikasi →
   klaim itu **pasti** artefak noise atau p-hacking.
